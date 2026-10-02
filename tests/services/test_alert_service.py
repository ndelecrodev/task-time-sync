"""Tests for AlertService.tasks_to_alert.

Covers the Segundo Ano exclusion: tasks from that turma must never trigger a
Teams alert, regardless of how urgent their deadline is, while Primeiro Ano
tasks within the same window are unaffected.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sop_pipeline.services.alert_service import AlertService
from sop_pipeline.services.etl_service import EtlService

BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _millis_in_days(days: int) -> str:
    """Millisecond timestamp for `days` from now, at local noon to avoid TZ edge cases."""
    target = datetime.now(BRAZIL_TIMEZONE).replace(hour=12, minute=0, second=0, microsecond=0)
    target += timedelta(days=days)
    return str(int(target.timestamp() * 1000))


def test_segundo_ano_task_within_deadline_window_is_excluded(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A Segundo Ano task inside its alert window still never appears in the results."""
    raw_task = make_clickup_task(
        priority={"priority": "high"},
        due_date=_millis_in_days(1),
        list={"id": "901715802839", "name": "BI"},  # a Segundo Ano list
    )
    task = etl_service.transform_tasks([raw_task])[0]
    assert task.turma == "Segundo Ano"

    result = AlertService.tasks_to_alert([task])

    assert result == []


def test_primeiro_ano_task_within_deadline_window_still_alerts(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A Primeiro Ano task in the same window is unaffected by the Segundo Ano filter."""
    raw_task = make_clickup_task(
        priority={"priority": "high"},
        due_date=_millis_in_days(1),
    )
    task = etl_service.transform_tasks([raw_task])[0]
    assert task.turma == "Primeiro Ano"

    result = AlertService.tasks_to_alert([task])

    assert result == [task]


# --- completion follows the ClickUp status type ------------------------------------


def _overdue_task(etl_service: EtlService, make_clickup_task, **overrides):
    """An overdue, high-priority Primeiro Ano task; overrides set status and dates."""
    raw_task = make_clickup_task(
        priority={"priority": "high"},
        due_date=_millis_in_days(-2),
        **overrides,
    )
    return etl_service.transform_tasks([raw_task])[0]


def test_overdue_task_in_done_status_does_not_alert(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "done" task is completed through date_done, so it never alerts."""
    task = _overdue_task(
        etl_service,
        make_clickup_task,
        status={"status": "done", "type": "done"},
        date_closed=None,
        date_done=_millis_in_days(-1),
    )
    assert task.completion_date is not None

    assert AlertService.tasks_to_alert([task]) == []


def test_overdue_task_in_custom_status_still_alerts(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "custom" status is unfinished work and keeps alerting, even with a stale date."""
    task = _overdue_task(
        etl_service,
        make_clickup_task,
        status={"status": "in progress", "type": "custom"},
        date_closed=_millis_in_days(-1),
    )

    assert AlertService.tasks_to_alert([task]) == [task]


def test_overdue_task_in_closed_status_does_not_alert(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "closed" task is completed through date_closed, so it never alerts."""
    task = _overdue_task(
        etl_service,
        make_clickup_task,
        status={"status": "Closed", "type": "closed"},
        date_closed=_millis_in_days(-1),
    )

    assert AlertService.tasks_to_alert([task]) == []
