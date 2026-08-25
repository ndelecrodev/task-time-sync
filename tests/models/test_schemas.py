"""Tests for the domain models and enums (support for scenario #4).

The enum values are the exact strings the Jira API and the Excel formulas use, so
they are pinned here; the deadline computed fields are checked against dates
expressed relative to today so the assertions stay deterministic without freezing
the clock.
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from sop_pipeline.models.schemas import (
    DeadlineStatus,
    Priority,
    Task,
    TaskType,
    TimeEntry,
)


def _task(**overrides) -> Task:
    """Build a valid Task, overriding individual fields per test."""
    fields = {
        "task_id": "ABC-1",
        "title": "Do the thing",
        "assignee": "Alice Silva",
        "priority": Priority.HIGH,
        "status": "In Progress",
        "creation_date": date(2026, 1, 1),
        "task_type": TaskType.TASK,
        "turma": "Primeiro Ano",
    }
    fields.update(overrides)
    return Task(**fields)


@pytest.mark.parametrize(
    "member, value",
    [
        (Priority.HIGHEST, "Highest"),
        (Priority.HIGH, "High"),
        (Priority.MEDIUM, "Medium"),
        (Priority.LOW, "Low"),
        (Priority.LOWEST, "Lowest"),
    ],
)
def test_priority_values_match_jira_labels(member: Priority, value: str) -> None:
    """Priority members carry the exact Jira label strings."""
    assert member.value == value


@pytest.mark.parametrize(
    "member, value",
    [
        (TaskType.BUG, "Bug"),
        (TaskType.TASK, "Task"),
        (TaskType.STORY, "Story"),
        (TaskType.EPIC, "Epic"),
        (TaskType.SUBTASK, "Subtask"),
    ],
)
def test_task_type_values_match_jira_labels(member: TaskType, value: str) -> None:
    """TaskType members carry the exact Jira label strings."""
    assert member.value == value


@pytest.mark.parametrize("bad_priority", ["Critical", "Urgent", "None"])
def test_task_rejects_out_of_enum_priority(bad_priority: str) -> None:
    """A priority outside the enum fails validation."""
    with pytest.raises(ValidationError):
        _task(priority=bad_priority)


@pytest.mark.parametrize("bad_type", ["Improvement", "Incident"])
def test_task_rejects_out_of_enum_task_type(bad_type: str) -> None:
    """An issue type outside the enum fails validation."""
    with pytest.raises(ValidationError):
        _task(task_type=bad_type)


def test_time_entry_rejects_negative_hours() -> None:
    """Hours are constrained to be non-negative."""
    with pytest.raises(ValidationError):
        TimeEntry(
            entry_id="e-1",
            employee="Alice Silva",
            entry_date=date(2026, 1, 1),
            hours=-1.0,
        )


def test_deadline_status_completed_when_resolution_date_set() -> None:
    """A completed task reads as COMPLETED regardless of its due date."""
    task = _task(due_date=date.today() - timedelta(days=5), completion_date=date.today())

    assert task.deadline_status == DeadlineStatus.COMPLETED.value
    assert task.is_late == "NÃO"


def test_deadline_status_late_when_overdue_and_open() -> None:
    """An open task past its due date reads as LATE."""
    task = _task(due_date=date.today() - timedelta(days=1))

    assert task.deadline_status == DeadlineStatus.LATE.value
    assert task.is_late == "SIM"


def test_deadline_status_warning_within_three_days() -> None:
    """A task due inside the three-day window reads as WARNING."""
    task = _task(due_date=date.today() + timedelta(days=2))

    assert task.deadline_status == DeadlineStatus.WARNING.value
    assert task.days_remaining == 2


def test_deadline_status_on_time_when_far_out() -> None:
    """A task due well beyond the window reads as ON_TIME."""
    task = _task(due_date=date.today() + timedelta(days=10))

    assert task.deadline_status == DeadlineStatus.ON_TIME.value


def test_deadline_status_no_deadline_when_due_date_absent() -> None:
    """A task without a due date reads as NO_DEADLINE and has no day count."""
    task = _task(due_date=None)

    assert task.deadline_status == DeadlineStatus.NO_DEADLINE.value
    assert task.days_remaining is None
    assert task.is_late is None
