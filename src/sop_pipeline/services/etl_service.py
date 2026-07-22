"""Transforms raw Jira and Clockify payloads into validated domain models."""

from datetime import date, datetime
from logging import getLogger
from zoneinfo import ZoneInfo

import sentry_sdk
from isodate import parse_duration
from pydantic import ValidationError

from sop_pipeline.config.settings import settings
from sop_pipeline.models.schemas import Task, TaskDetail, TimeEntry

logger = getLogger(__name__)

NO_RESPONSIBLE = "There is no one responsible."
NO_AREA = "There is no one area."
UNKNOWN_EMAIL = "email_desconhecido@desconhecido.com"

# Errors that must cost a single record, never the whole batch. AttributeError and
# TypeError belong here because an unexpected null in a Jira/Clockify payload
# surfaces as one of those, and without them a single bad record aborts the loop
# and every already-converted record is thrown away with it.
RECORD_ERRORS = (ValidationError, KeyError, AttributeError, TypeError, ValueError)


class EtlService:
    """Converts raw API payloads into :mod:`sop_pipeline.models` objects.

    Records that fail validation are logged and skipped rather than aborting the
    whole run, so one malformed Jira issue never costs a full sync.
    """

    def __init__(self) -> None:
        """Read the configurable Jira custom-field ID and load employee mappings."""
        self.jira_customfield_area = settings.JIRA_CUSTOMFIELD_AREA
        self.employee_registry = settings.load_employee_registry()
        self._unmapped_employees_warned: set[str] = set()

    def normalize_employee_identifier(self, identifier: str | None) -> str | None:
        """Normalize an employee identifier (name or email) to canonical form.

        Looks up the identifier in the employee registry. If found, returns the
        canonical name. If not found, returns a visible sentinel value.

        Args:
            identifier: A name, email, or None from Jira/Clockify.

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

    def transform_tasks(self, raw_issues: list) -> list[Task]:
        """Convert raw Jira issues into :class:`Task` models.

        An issue that cannot be converted is discarded and reported at ERROR
        level, since a discarded issue silently disappears from the report. The
        most common cause is a priority or issue type that is not part of
        :class:`Priority` / :class:`TaskType` — for example a new priority added
        in Jira but never mirrored here.

        Args:
            raw_issues: Issue dicts as returned by ``JiraClient.fetch_tasks``.

        Returns:
            list[Task]: The issues that validated successfully.
        """
        tasks = []
        for issue in raw_issues:
            try:
                tasks.append(self._build_task(issue))
            except RECORD_ERRORS as error:
                logger.error(
                    "Discarding Jira issue %s, it could not be converted: %s",
                    issue.get("key", "???") if isinstance(issue, dict) else "???",
                    error,
                )
                sentry_sdk.capture_exception(error)
                continue

        return tasks

    def _build_task(self, issue: dict) -> Task:
        """Convert a single raw Jira issue into a :class:`Task`.

        Args:
            issue: One issue dict from the Jira search endpoint.

        Returns:
            Task: The validated task.

        Raises:
            KeyError: If a field the pipeline depends on is absent.
            ValidationError: If a value does not satisfy the model.
        """
        fields = issue["fields"]

        # An unassigned issue still belongs in the report, so a placeholder name
        # is used rather than dropping the row.
        if fields["assignee"] is None:
            assignee = NO_RESPONSIBLE
            assignee_email = None
        else:
            assignee = fields["assignee"].get("displayName")
            assignee_email = fields["assignee"].get("emailAddress")

        # Normalize the assignee to canonical name using the email if available,
        # otherwise try the display name.
        if assignee_email:
            assignee = self.normalize_employee_identifier(assignee_email)
        else:
            assignee = self.normalize_employee_identifier(assignee)

        if fields[self.jira_customfield_area] is None:
            area = NO_AREA
        else:
            area = fields[self.jira_customfield_area].get("value")

        # Jira sends these as null rather than omitting them: `priority` when the
        # project has no priority scheme, `creator` on some imported issues. The
        # `or {}` keeps the lookup safe; a missing required value then fails as a
        # ValidationError, which costs this one issue instead of the whole batch.
        return Task(
            task_id=issue["key"],
            title=fields.get("summary", "No title"),
            assignee=assignee,
            priority=(fields.get("priority") or {}).get("name"),
            status=(fields.get("status") or {}).get("name"),
            area=area,
            creation_date=self._parse_datetime_to_date(field=fields["created"]),
            due_date=self._parse_date(raw_date=fields["duedate"]),
            completion_date=self._parse_datetime_to_date(fields["resolutiondate"]),
            task_type=(fields.get("issuetype") or {}).get("name"),
            creator=(fields.get("creator") or {}).get("displayName"),
            update_date=self._parse_datetime_to_date(field=fields["updated"]),
            assignee_email=assignee_email,
            tags=fields.get("labels", []),
        )

    @staticmethod
    def transform_details(raw_issues: list[dict]) -> list[TaskDetail]:
        """Extract the plain-text description of each issue.

        Args:
            raw_issues: Issue dicts as returned by ``JiraClient.fetch_tasks``.

        Returns:
            list[TaskDetail]: One detail record per issue that validated.
        """
        details = []
        for issue in raw_issues:
            try:
                task_id = issue["key"]
                raw_description = issue["fields"].get("description")
                if raw_description is None:
                    description = None
                else:
                    description = EtlService._extract_description(raw_description).strip()

                details.append(TaskDetail(task_id=task_id, description=description))
            except RECORD_ERRORS as error:
                logger.warning(
                    "Detail of task %s is invalid, skipping: %s",
                    issue.get("key", "???") if isinstance(issue, dict) else "???",
                    error,
                )
        return details

    @staticmethod
    def _extract_description(node: dict) -> str:
        """Flatten an Atlassian Document Format tree into plain text.

        ADF descriptions are a nested tree of nodes; only leaf nodes carry a
        ``text`` key, so the tree is walked recursively. Paragraph nodes get a
        trailing newline to preserve the original line breaks.

        Args:
            node: An ADF node (the document root on the first call).

        Returns:
            str: The concatenated text of the whole subtree.
        """
        text = ""
        if "text" in node.keys():
            # The key can be present with a null value on some ADF marks; `or ""`
            # keeps the concatenation from raising and losing every description.
            text += node.get("text") or ""
        elif "content" in node.keys():
            for child in node["content"]:
                if child.get("type") == "paragraph":
                    text += EtlService._extract_description(child) + "\n"
                else:
                    text += EtlService._extract_description(child)
        else:
            text += "\n"
        return text

    @staticmethod
    def _parse_date(raw_date: str | None) -> date | None:
        """Parse a plain ISO date string (``YYYY-MM-DD``).

        Args:
            raw_date: The string to parse, or ``None``.

        Returns:
            date | None: The parsed date, or ``None`` when the input was ``None``.
        """
        if raw_date is None:
            return None
        return date.fromisoformat(raw_date)

    @staticmethod
    def _parse_datetime_to_date(field: str | None) -> date | None:
        """Parse an ISO datetime string and keep only its date part.

        Args:
            field: The datetime string to parse, or ``None``.

        Returns:
            date | None: The date part, or ``None`` when the input was ``None``.
        """
        if field is None:
            return None
        datetime_field = datetime.fromisoformat(field)
        return datetime_field.date()

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

                # Normalize the employee email to canonical name
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
