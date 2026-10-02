"""Transforms raw ClickUp and Clockify payloads into validated domain models."""

from datetime import date, datetime
from logging import getLogger
from typing import NamedTuple
from zoneinfo import ZoneInfo

import sentry_sdk
from isodate import parse_duration
from pydantic import ValidationError

from sop_pipeline.config.settings import settings
from sop_pipeline.models.schemas import Priority, Task, TaskDetail, TaskType, TimeEntry

logger = getLogger(__name__)

NO_RESPONSIBLE = "There is no one responsible."
NO_AREA = "There is no one area."
UNKNOWN_EMAIL = "email_desconhecido@desconhecido.com"

# ClickUp's `priority.priority` labels, mapped onto the Priority enum's exact
# label strings. Chosen 1:1 by severity: urgent is the most severe level ClickUp
# offers, so it maps to Highest rather than High. A task with no priority set
# never reaches this map; it becomes Priority.NO_PRIORITY in _build_task.
CLICKUP_PRIORITY_MAP = {
    "urgent": "Highest",
    "high": "High",
    "normal": "Medium",
    "low": "Low",
}

# ClickUp status types that mean the work is completed. Every status carries
# one of "open", "unstarted", "custom", "done" or "closed"; the status name
# itself is free text and differs per workspace, so the type is what gets
# compared. Only "closed" fills date_closed, so "done" falls back to date_done.
FINISHED_STATUS_TYPES = frozenset({"done", "closed"})

# Errors that must cost a single record, never the whole batch. AttributeError and
# TypeError belong here because an unexpected null in a ClickUp/Clockify payload
# surfaces as one of those, and without them a single bad record aborts the loop
# and every already-converted record is thrown away with it.
RECORD_ERRORS = (ValidationError, KeyError, AttributeError, TypeError, ValueError)

PRIMEIRO_ANO = "Primeiro Ano"
SEGUNDO_ANO = "Segundo Ano"


class ClickUpListInfo(NamedTuple):
    """What a ClickUp list means to the pipeline.

    Attributes:
        area: Area name, in the same vocabulary as ``settings.teams_webhooks``' keys.
        turma: The turma the list belongs to ("Primeiro Ano", "Segundo Ano").
    """

    area: str
    turma: str


# ClickUp list ("Sprint") id -> area and turma. This is the pipeline's scope
# allowlist: pipeline._filter_allowed_lists drops every task whose list id is
# not a key here. Lists, not folders, because ClickUp only reports a task's
# immediate parent folder, so a turma reorganized into sub-folders vanishes
# from the payload while its list ids stay the same (see design-decisions.md).
# Keys are strings because task["list"]["id"] comes back as a string in the
# raw payload. This is a curriculum/business mapping, not a per-environment
# setting.
CLICKUP_LIST_MAP = {
    "901715802295": ClickUpListInfo("front-end", PRIMEIRO_ANO),  # Desenvolvimento 1
    "901715802315": ClickUpListInfo("back-end", PRIMEIRO_ANO),  # POO
    "901715802329": ClickUpListInfo("back-end", PRIMEIRO_ANO),  # Lógica de Programação
    "901715802335": ClickUpListInfo("design", PRIMEIRO_ANO),  # UX
    "901715802357": ClickUpListInfo("ia", PRIMEIRO_ANO),  # Introdução à Inteligência Artificial
    "901715802434": ClickUpListInfo("sop", PRIMEIRO_ANO),  # Sistemas Operacionais
    "901716215806": ClickUpListInfo("ti", PRIMEIRO_ANO),  # Projetos
    "901715802403": ClickUpListInfo("data", PRIMEIRO_ANO),  # Banco de Dados 1
    # Segundo Ano. dad/mobile/eqs/devops/bi have no entry in
    # settings.teams_webhooks on purpose — Segundo Ano tasks never reach the
    # Teams alert path (see AlertService.EXCLUDED_TURMA), so no webhook is
    # ever looked up for these areas.
    "901715802576": ClickUpListInfo("data", SEGUNDO_ANO),  # Modelagem de dados
    "901715802657": ClickUpListInfo("ia", SEGUNDO_ANO),  # IA
    "901715802696": ClickUpListInfo("front-end", SEGUNDO_ANO),  # Desenvolvimento 2
    "901715802720": ClickUpListInfo("data", SEGUNDO_ANO),  # Banco de Dados 2
    "901715802775": ClickUpListInfo("dad", SEGUNDO_ANO),  # DAD
    "901715802792": ClickUpListInfo("mobile", SEGUNDO_ANO),  # Mobile
    "901715802817": ClickUpListInfo("eqs", SEGUNDO_ANO),  # EQS
    "901715802829": ClickUpListInfo("devops", SEGUNDO_ANO),  # DEVOPS
    "901715802839": ClickUpListInfo("bi", SEGUNDO_ANO),  # BI
    "901716191365": ClickUpListInfo("design", SEGUNDO_ANO),  # UX
}


class EtlService:
    """Converts raw API payloads into :mod:`sop_pipeline.models` objects.

    Records that fail validation are logged and skipped rather than aborting the
    whole run, so one malformed ClickUp task never costs a full sync.
    """

    def __init__(self) -> None:
        """Load employee mappings."""
        self.employee_registry = settings.load_employee_registry()
        self._unmapped_employees_warned: set[str] = set()

    def normalize_employee_identifier(self, identifier: str | None) -> str | None:
        """Normalize an employee identifier (name or email) to canonical form.

        Looks up the identifier in the employee registry. If found, returns the
        canonical name. If not found, returns a visible sentinel value.

        Args:
            identifier: A name, email, or None from ClickUp/Clockify.

        Returns:
            str | None: The canonical name, a sentinel value like "Unmapped
            employee: email", or ``None``/the sentinel constants passed straight
            through unchanged.
        """
        if identifier is None or identifier in (NO_RESPONSIBLE, NO_AREA):
            return identifier

        canonical = self.employee_registry.resolve(identifier)
        if canonical is not None:
            return canonical

        # Employee not found in config; use visible sentinel so they show up in the report.
        if identifier not in self._unmapped_employees_warned:
            logger.warning(
                "Employee not found in mapping configuration: %s; will be marked as unmapped",
                identifier,
            )
            self._unmapped_employees_warned.add(identifier)

        return f"Unmapped employee: {identifier}"

    def transform_tasks(self, raw_tasks: list) -> list[Task]:
        """Convert raw ClickUp tasks into :class:`Task` models.

        A task that cannot be converted is discarded and reported at ERROR
        level, since a discarded task silently disappears from the report. A
        task with no priority set is kept as ``Priority.NO_PRIORITY``; a
        non-null priority label missing from ``CLICKUP_PRIORITY_MAP`` still
        fails validation and is discarded here.

        Args:
            raw_tasks: Task dicts as returned by ``ClickUpClient.fetch_tasks``.

        Returns:
            list[Task]: The tasks that validated successfully.
        """
        tasks = []
        for raw_task in raw_tasks:
            try:
                tasks.append(self._build_task(raw_task))
            except RECORD_ERRORS as error:
                logger.error(
                    "Discarding ClickUp task %s, it could not be converted: %s",
                    raw_task.get("id", "???") if isinstance(raw_task, dict) else "???",
                    error,
                )
                sentry_sdk.capture_exception(error)
                continue

        return tasks

    def _build_task(self, raw_task: dict) -> Task:
        """Convert a single raw ClickUp task into a :class:`Task`.

        Args:
            raw_task: One task dict from the ClickUp list-tasks endpoint.

        Returns:
            Task: The validated task.

        Raises:
            KeyError: If a field the pipeline depends on is absent.
            ValidationError: If a value does not satisfy the model.
        """
        assignees = raw_task["assignees"] or []

        # An unassigned task still belongs in the report, so a placeholder name
        # is used rather than dropping the row. ClickUp allows multiple
        # assignees per task; each is normalized individually and the
        # canonical names are joined into one comma-separated string, since
        # Task.assignee is a single field.
        if not assignees:
            assignee = NO_RESPONSIBLE
            assignee_email = None
            canonical_names = []
        else:
            canonical_names = [
                self.normalize_employee_identifier(person.get("email") or person.get("username"))
                for person in assignees
            ]
            assignee = ", ".join(canonical_names)

            # A Teams @mention can only target one person, so only the first
            # assignee's email is carried forward. ClickUp Cloud's per-user
            # email-visibility settings can leave it null even for a correctly
            # assigned, visible user; fall back to the registry so outbound
            # Teams @mentions still have an email.
            assignee_email = assignees[0].get("email")
            if not assignee_email:
                assignee_email = self.employee_registry.get_registered_email(canonical_names[0])

            # teams_email, when registered for this person, always wins: it
            # exists specifically because clickup_email is sometimes not the
            # address linked to their Microsoft Teams account, so it overrides
            # whatever assignee_email holds above regardless of source.
            teams_email = self.employee_registry.get_teams_email(canonical_names[0])
            if teams_email:
                assignee_email = teams_email

        # A null or absent priority means "no priority set" in ClickUp and is
        # kept. An unknown non-null label maps to None and fails validation, so
        # a new ClickUp priority level is noticed instead of silently relabelled.
        priority_label = (raw_task.get("priority") or {}).get("priority")
        if priority_label is None:
            priority = Priority.NO_PRIORITY
        else:
            priority = CLICKUP_PRIORITY_MAP.get(priority_label)

        # "parent" is the immediate parent's id, so a nested subtask points at
        # the subtask above it rather than at the top-level task. It is stored
        # as is, with no check that the parent is in this run (see
        # design-decisions.md).
        parent_task_id = raw_task.get("parent")

        # No sentinel needed for area or turma: pipeline._filter_allowed_lists
        # already discards every task whose list is not in CLICKUP_LIST_MAP
        # before transform_tasks ever sees it, so a KeyError here would only
        # mean genuinely malformed ClickUp data — handled like any other
        # required field, by discarding this one record (see RECORD_ERRORS).
        # turma comes from the mapping rather than folder.name, since the folder
        # ClickUp reports is only the immediate parent (e.g. "Backend").
        list_info = CLICKUP_LIST_MAP[raw_task["list"]["id"]]

        # Completion follows the task's CURRENT status type, so a reopened task
        # loses its date even when ClickUp still sends an old date_closed or
        # date_done. A missing status or type means "not completed", never a
        # discarded task (see design-decisions.md).
        raw_status = raw_task.get("status")
        status_type = raw_status.get("type") if isinstance(raw_status, dict) else None
        if status_type in FINISHED_STATUS_TYPES:
            completion_date = self._parse_millis_to_date(
                raw_task.get("date_closed") or raw_task.get("date_done")
            )
        else:
            completion_date = None

        return Task(
            task_id=raw_task["id"],
            title=raw_task.get("name", "No title"),
            assignee=assignee,
            priority=priority,
            status=(raw_task.get("status") or {}).get("status"),
            area=list_info.area,
            creation_date=self._parse_millis_to_date(raw_task["date_created"]),
            due_date=self._parse_millis_to_date(raw_task.get("due_date")),
            completion_date=completion_date,
            task_type=TaskType.SUBTASK if parent_task_id else TaskType.TASK,
            creator=(raw_task.get("creator") or {}).get("username"),
            update_date=self._parse_millis_to_date(raw_task.get("date_updated")),
            assignee_email=assignee_email,
            tags=[tag.get("name") for tag in raw_task.get("tags", [])],
            turma=list_info.turma,
            assignee_names=canonical_names,
            parent_task_id=parent_task_id,
        )

    @staticmethod
    def transform_details(raw_tasks: list[dict]) -> list[TaskDetail]:
        """Extract the plain-text description of each task.

        Args:
            raw_tasks: Task dicts as returned by ``ClickUpClient.fetch_tasks``.

        Returns:
            list[TaskDetail]: One detail record per task that validated.
        """
        details = []
        for raw_task in raw_tasks:
            try:
                task_id = raw_task["id"]
                description = raw_task.get("description") or raw_task.get("text_content")
                details.append(TaskDetail(task_id=task_id, description=description))
            except RECORD_ERRORS as error:
                logger.warning(
                    "Detail of task %s is invalid, skipping: %s",
                    raw_task.get("id", "???") if isinstance(raw_task, dict) else "???",
                    error,
                )
        return details

    @staticmethod
    def _parse_millis_to_date(raw_millis: str | None) -> date | None:
        """Convert a millisecond Unix-timestamp string into a local calendar date.

        ClickUp reports its timestamp fields (``date_created``, ``due_date``,
        ``date_closed``, ``date_updated``) as strings holding milliseconds since
        the epoch, in UTC. Converting to America/Sao_Paulo before truncating to a
        date matters for the same reason it does for Clockify entries (see
        :meth:`_parse_utc_to_local_date`): a timestamp late in the evening in
        Brazil can already fall on the next day in UTC.

        Args:
            raw_millis: The millisecond-timestamp string, or ``None``.

        Returns:
            date | None: The date in America/Sao_Paulo, or ``None`` when the
            input was ``None``.
        """
        if raw_millis is None:
            return None
        brazil_timezone = ZoneInfo("America/Sao_Paulo")
        return datetime.fromtimestamp(int(raw_millis) / 1000, tz=brazil_timezone).date()

    @staticmethod
    def _parse_duration(duration_iso: str) -> float:
        """Convert an ISO 8601 duration (e.g. ``PT1H30M``) into hours.

        Args:
            duration_iso: The ISO 8601 duration string.

        Returns:
            float: The duration expressed in hours.
        """
        delta = parse_duration(duration_iso)
        return delta.total_seconds() / 3600

    @staticmethod
    def _parse_utc_to_local_date(raw_datetime: str) -> date:
        """Convert a UTC timestamp into the local (Brazil) calendar date.

        Clockify reports timestamps in UTC. Converting before truncating matters:
        an entry started late in the evening in Brazil already falls on the next
        day in UTC and would otherwise be attributed to the wrong date.

        Args:
            raw_datetime: ISO datetime string from Clockify.

        Returns:
            date: The date in the America/Sao_Paulo timezone.
        """
        parsed = datetime.fromisoformat(raw_datetime)
        brazil_timezone = ZoneInfo("America/Sao_Paulo")
        return parsed.astimezone(brazil_timezone).date()

    @staticmethod
    def build_email_index(users: list[dict]) -> dict[str, str]:
        """Map each Clockify user ID to that user's e-mail.

        Built once per run by the caller and reused for every user's entries;
        rebuilding it inside :meth:`transform_time_entries` would make the whole
        sync quadratic in the number of workspace users.

        Args:
            users: Workspace user dicts from ``ClockifyClient.list_users``.

        Returns:
            dict[str, str]: User ID mapped to e-mail.
        """
        return {user.get("id"): user.get("email") for user in users}

    def transform_time_entries(
        self, raw_entries: list[dict], email_by_user_id: dict[str, str]
    ) -> list[TimeEntry]:
        """Convert raw Clockify entries into :class:`TimeEntry` models.

        Normalizes the employee email to canonical name using the employee registry.

        Args:
            raw_entries: Time-entry dicts from ``ClockifyClient.fetch_time_entries``.
            email_by_user_id: Index built by :meth:`build_email_index`.

        Returns:
            list[TimeEntry]: The entries that validated successfully.
        """
        time_entries = []
        for entry in raw_entries:
            try:
                user_id = entry.get("userId", "Unknown")
                email = email_by_user_id.get(user_id, UNKNOWN_EMAIL)
                employee = self.normalize_employee_identifier(email)

                raw_duration = entry["timeInterval"]["duration"]
                # A running timer has no duration yet; Clockify sends null, which
                # isodate cannot parse. Skip it and pick it up on a later run.
                if raw_duration is None:
                    continue
                duration = EtlService._parse_duration(raw_duration)
                start_date = EtlService._parse_utc_to_local_date(entry["timeInterval"]["start"])
                time_entries.append(
                    TimeEntry(
                        entry_id=entry["id"],
                        employee=employee,
                        entry_date=start_date,
                        hours=duration,
                    )
                )
            except RECORD_ERRORS as error:
                logger.warning(
                    "Error transforming entry %s: %s",
                    entry.get("id", "???") if isinstance(entry, dict) else "???",
                    error,
                )

        return time_entries
