"""Transforms raw ClickUp and Clockify payloads into validated domain models."""

from datetime import date, datetime
from logging import getLogger
from zoneinfo import ZoneInfo

import sentry_sdk
from isodate import parse_duration
from pydantic import ValidationError

from sop_pipeline.config.settings import settings
from sop_pipeline.models.schemas import Task, TaskDetail, TaskType, TimeEntry

logger = getLogger(__name__)

NO_RESPONSIBLE = "There is no one responsible."
NO_AREA = "There is no one area."
UNKNOWN_EMAIL = "email_desconhecido@desconhecido.com"

# ClickUp's `priority.priority` labels, mapped onto the Priority enum's exact
# label strings. Chosen 1:1 by severity: urgent is the most severe level ClickUp
# offers, so it maps to Highest rather than High.
CLICKUP_PRIORITY_MAP = {
    "urgent": "Highest",
    "high": "High",
    "normal": "Medium",
    "low": "Low",
}

# Errors that must cost a single record, never the whole batch. AttributeError and
# TypeError belong here because an unexpected null in a ClickUp/Clockify payload
# surfaces as one of those, and without them a single bad record aborts the loop
# and every already-converted record is thrown away with it.
RECORD_ERRORS = (ValidationError, KeyError, AttributeError, TypeError, ValueError)


class EtlService:
    """Converts raw API payloads into :mod:`sop_pipeline.models` objects.

    Records that fail validation are logged and skipped rather than aborting the
    whole run, so one malformed ClickUp task never costs a full sync.
    """

    def __init__(self) -> None:
        """Read the configurable ClickUp custom-field ID and load employee mappings."""
        self.clickup_area_field_id = settings.CLICKUP_AREA_FIELD_ID
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
        level, since a discarded task silently disappears from the report. The
        most common cause is a null or unrecognised priority — ClickUp's four
        priority levels (urgent/high/normal/low) all map onto :class:`Priority`,
        but a task with no priority set has nothing to map.

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

        priority_label = (raw_task.get("priority") or {}).get("priority")
        priority = CLICKUP_PRIORITY_MAP.get(priority_label) if priority_label else None

        # No sentinel needed for turma: pipeline._filter_allowed_folders already
        # discards every task without a folder on the CLICKUP_FOLDER_IDS
        # allowlist before transform_tasks ever sees it, so a KeyError here would
        # only mean genuinely malformed ClickUp data — handled like any other
        # required field, by discarding this one record (see RECORD_ERRORS).
        return Task(
            task_id=raw_task["id"],
            title=raw_task.get("name", "No title"),
            assignee=assignee,
            priority=priority,
            status=(raw_task.get("status") or {}).get("status"),
            area=self._resolve_area(raw_task.get("custom_fields") or []),
            creation_date=self._parse_millis_to_date(raw_task["date_created"]),
            due_date=self._parse_millis_to_date(raw_task.get("due_date")),
            completion_date=self._parse_millis_to_date(raw_task.get("date_closed")),
            task_type=TaskType.TASK,
            creator=(raw_task.get("creator") or {}).get("username"),
            update_date=self._parse_millis_to_date(raw_task.get("date_updated")),
            assignee_email=assignee_email,
            tags=[tag.get("name") for tag in raw_task.get("tags", [])],
            turma=raw_task["folder"]["name"],
        )

    def _resolve_area(self, custom_fields: list[dict]) -> str:
        """Resolve the configured area custom field to its option label.

        ClickUp returns ``custom_fields`` as a list of field objects rather than
        a direct dict lookup like Jira's. For a ``drop_down`` field, ``value`` is
        an index into that field's own ``type_config.options`` array, not the
        label text, so the index has to be resolved against that array.

        Args:
            custom_fields: The task's ``custom_fields`` list.

        Returns:
            str: The area option's name, or :data:`NO_AREA` when the field is
            absent, has no ``value`` key, or the index doesn't resolve.
        """
        for field in custom_fields:
            if field.get("id") != self.clickup_area_field_id:
                continue
            if "value" not in field:
                return NO_AREA
            value = field.get("value")
            if value is None:
                return NO_AREA
            options = (field.get("type_config") or {}).get("options") or []
            if not isinstance(value, int) or not 0 <= value < len(options):
                return NO_AREA
            return options[value].get("name") or NO_AREA
        return NO_AREA

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
