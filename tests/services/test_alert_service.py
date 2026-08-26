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
        folder={"id": "fake-folder-segundo-ano", "name": "Segundo Ano"},
    )
    task = etl_service.transform_tasks([raw_task])[0]

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
