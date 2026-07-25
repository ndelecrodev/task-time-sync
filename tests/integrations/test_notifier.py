"""Tests for Notifier._build_message's overdue/on-time/undated formatting."""

from datetime import date, timedelta

from sop_pipeline.integrations.notifier import Notifier
from sop_pipeline.models.schemas import Priority, Task, TaskType


def _make_task(due_date: date | None) -> Task:
    return Task(
        task_id="QT-TEST",
        title="Tarefa de teste",
        assignee="Nicolas Delecrode",
        assignee_email="nicolas@example.com",
        priority=Priority.HIGH,
        status="Fazendo",
        area="TI",
        creation_date=date.today() - timedelta(days=10),
        due_date=due_date,
        completion_date=None,
        task_type=TaskType.TASK,
        creator="Alguém",
        update_date=date.today(),
        tags=[],
    )


def test_build_message_overdue_task_shows_days_late():
    task = _make_task(due_date=date.today() - timedelta(days=7))

    message = Notifier._build_message(task)

    assert "Tarefa atrasada há" in message
    assert "7 dia(s)" in message
    assert "-7" not in message


def test_build_message_on_time_task_shows_days_remaining():
    task = _make_task(due_date=date.today() + timedelta(days=5))

    message = Notifier._build_message(task)

    assert "Dias restantes:" in message
    assert "5 dia(s)" in message
    assert "Tarefa atrasada" not in message


def test_build_message_task_without_due_date_shows_indefinido():
    task = _make_task(due_date=None)

    message = Notifier._build_message(task)

    assert "Dias restantes:" in message
    assert "Indefinido" in message
