"""Pydantic models describing the data that flows through the pipeline.

These models are the contract between the API clients, the ETL service and the
spreadsheet writer. Enum *values* that are written to (or compared against) the
spreadsheet are kept in Portuguese on purpose see :class:`DeadlineStatus`.
"""

from datetime import date
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, computed_field


class Priority(str, Enum):
    """Jira issue priority, using the exact labels returned by the Jira API."""

    HIGHEST = "Highest"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    LOWEST = "Lowest"


class DeadlineStatus(Enum):
    """Deadline status of a task.

    The member *values* must match, character for character, the strings the
    Excel formula in the ``status_prazo`` column produces
    (``IF(...,"Concluído",...)``). Renaming a member is safe; changing a value
    would silently desynchronise Python from the spreadsheet.
    """

    COMPLETED = "Concluído"
    LATE = "Atrasado"
    WARNING = "Atenção"
    ON_TIME = "No prazo"
    NO_DEADLINE = "Sem prazo"


class TaskType(str, Enum):
    """Jira issue type, using the exact labels returned by the Jira API."""

    BUG = "Bug"
    TASK = "Task"
    STORY = "Story"
    EPIC = "Epic"
    SUBTASK = "Subtask"


class Task(BaseModel):
    """A Jira issue normalised for the spreadsheet.

    Attributes:
        task_id: Jira issue key (e.g. ``ABC-123``); the upsert key in the sheet.
        title: Issue summary.
        assignee: Display name of whoever the issue is assigned to.
        priority: Issue priority.
        status: Free-form workflow status name coming from Jira.
        area: Value of the Jira "area" custom field, used to route alerts.
        creation_date: Date the issue was created.
        due_date: Due date, when one is set.
        completion_date: Date the issue was resolved, when it was.
        task_type: Issue type.
        creator: Display name of whoever opened the issue.
        update_date: Date of the last update.
        assignee_email: Assignee e-mail, forwarded in the Teams alert.
        tags: Jira labels attached to the issue.
    """

    task_id: str
    title: str
    assignee: str
    priority: Priority
    status: str
    area: str | None = None
    creation_date: date
    due_date: date | None = None
    completion_date: date | None = None
    task_type: TaskType
    creator: str | None = None
    update_date: date | None = None
    assignee_email: EmailStr | None = None
    tags: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def days_remaining(self) -> int | None:
        """Days left until the due date, negative when already overdue.

        Returns:
            int | None: Day count, or ``None`` when the task has no due date.
        """
        if self.due_date is None:
            return None
        return (self.due_date - date.today()).days

    @computed_field
    @property
    def is_late(self) -> str | None:
        """Whether the task is still overdue.

        The ``"SIM"``/``"NÃO"`` strings mirror what the ``atrasado`` column
        formula produces in the spreadsheet, so both sides stay comparable. That
        formula is ``IF(AND(prazo<>"", prazo<TODAY(), data_conclusao=""), "SIM",
        "NÃO")``: a finished task counts as **not** late even when it was
        delivered past its due date, since the delay is no longer actionable.
        The completion check therefore comes first, exactly as in
        :meth:`deadline_status`.

        Returns:
            str | None: ``"NÃO"`` when the task is completed or still within its
            due date, ``"SIM"`` when it is open and overdue, or ``None`` when
            there is no due date.
        """
        if self.completion_date is not None:
            return "NÃO"
        if self.due_date is None:
            return None
        return "SIM" if self.due_date < date.today() else "NÃO"

    @computed_field
    @property
    def deadline_status(self) -> str:
        """Classify the task against its due date.

        Mirrors the ``status_prazo`` column formula in the spreadsheet, including
        the three-day warning window. The lower bound is inclusive so that a task
        due *today* reads as WARNING here exactly as the Excel formula
        (``prazo-TODAY()<=3``) classifies it.

        Returns:
            str: One of the :class:`DeadlineStatus` values.
        """
        if self.completion_date is not None:
            status = DeadlineStatus.COMPLETED
        elif self.due_date is not None:
            days_until_deadline = (self.due_date - date.today()).days
            if self.due_date < date.today():
                status = DeadlineStatus.LATE
            elif 0 <= days_until_deadline <= 3:
                status = DeadlineStatus.WARNING
            else:
                status = DeadlineStatus.ON_TIME
        else:
            status = DeadlineStatus.NO_DEADLINE
        return status.value


class TimeEntry(BaseModel):
    """A single Clockify time entry.

    Attributes:
        entry_id: Clockify entry ID; the upsert key in the ``BASE_HORAS`` sheet.
        employee: E-mail of the user the entry belongs to.
        entry_date: Local (America/Sao_Paulo) date the entry started.
        hours: Duration in hours.
    """

    entry_id: str
    employee: str
    entry_date: date
    hours: float = Field(ge=0)


class TaskDetail(BaseModel):
    """The long-form description of a task, stored on its own sheet.

    Attributes:
        task_id: Jira issue key this description belongs to.
        description: Flattened plain-text description, or ``None`` when empty.
    """

    task_id: str
    description: str | None = None
