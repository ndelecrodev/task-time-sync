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


# --- ClickUp status type ("done"/"closed" silence alerts) --------------------------


def _overdue_task(etl_service: EtlService, make_clickup_task, status: dict):
    """An overdue, high-priority Primeiro Ano task with no date_closed."""
    raw_task = make_clickup_task(
        priority={"priority": "high"},
        due_date=_millis_in_days(-2),
        date_closed=None,
        status=status,
    )
    return etl_service.transform_tasks([raw_task])[0]


def test_overdue_task_in_done_status_type_does_not_alert(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "done" status stops alerts even though completion_date is still empty."""
    task = _overdue_task(etl_service, make_clickup_task, {"status": "done", "type": "done"})
    assert task.completion_date is None

    assert AlertService.tasks_to_alert([task]) == []


def test_overdue_task_in_custom_status_type_still_alerts(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "custom" status (e.g. in progress) is unfinished work and keeps alerting."""
    task = _overdue_task(
        etl_service, make_clickup_task, {"status": "in progress", "type": "custom"}
    )

    assert AlertService.tasks_to_alert([task]) == [task]


def test_overdue_task_in_closed_status_type_does_not_alert(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "closed" status stops alerts on its own, not only through date_closed."""
    task = _overdue_task(etl_service, make_clickup_task, {"status": "Closed", "type": "closed"})

    assert AlertService.tasks_to_alert([task]) == []
