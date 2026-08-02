"""Tests for EtlService (scenarios #2, #3, #4).

These exercise the "never fail the whole batch over one bad record" contract: a
single malformed record is logged and skipped while every other record in the
batch survives, and unmapped employees are marked with a visible sentinel rather
than dropped.
"""

import logging
from unittest.mock import patch

import pytest

from sop_pipeline.services.etl_service import (
    NO_AREA,
    NO_RESPONSIBLE,
    UNKNOWN_EMAIL,
    EtlService,
)

ETL_LOGGER = "sop_pipeline.services.etl_service"


# --- normalize_employee_identifier (scenario #2) ---------------------------------


def test_normalize_maps_known_email_to_canonical_name(etl_service: EtlService) -> None:
    """A registered email resolves to the canonical name."""
    assert etl_service.normalize_employee_identifier("alice.jira@example.com") == "Alice Silva"


def test_normalize_marks_unmapped_email_visibly(etl_service: EtlService) -> None:
    """An unmapped email becomes the visible sentinel, never dropped or raised."""
    result = etl_service.normalize_employee_identifier("stranger@example.com")

    assert result == "Unmapped employee: stranger@example.com"


@pytest.mark.parametrize("passthrough", [None, NO_RESPONSIBLE, NO_AREA])
def test_normalize_passes_sentinels_through_unchanged(
    etl_service: EtlService, passthrough: str | None
) -> None:
    """None and the placeholder texts are returned verbatim, never wrapped."""
    assert etl_service.normalize_employee_identifier(passthrough) == passthrough


def test_normalize_warns_only_once_per_unmapped_identifier(
    etl_service: EtlService, caplog: pytest.LogCaptureFixture
) -> None:
    """The same unmapped identifier logs one warning but returns the sentinel every time."""
    with caplog.at_level(logging.WARNING, logger=ETL_LOGGER):
        first = etl_service.normalize_employee_identifier("stranger@example.com")
        second = etl_service.normalize_employee_identifier("stranger@example.com")

    warnings = [
        record
        for record in caplog.records
        if "Employee not found in mapping configuration" in record.message
    ]
    assert len(warnings) == 1
    assert first == second == "Unmapped employee: stranger@example.com"


# --- transform_time_entries (scenario #3) ----------------------------------------


def test_transform_time_entries_skips_running_timer(
    etl_service: EtlService, make_clockify_entry
) -> None:
    """A running timer (null duration) is skipped without raising."""
    entries = [make_clockify_entry(duration=None)]

    result = etl_service.transform_time_entries(entries, {"user-1": "alice.clockify@example.com"})

    assert result == []


def test_transform_time_entries_maps_known_user_to_canonical_name(
    etl_service: EtlService, make_clockify_entry
) -> None:
    """A valid entry resolves its user to the canonical employee name and hours."""
    entries = [make_clockify_entry(duration="PT1H30M")]

    result = etl_service.transform_time_entries(entries, {"user-1": "alice.clockify@example.com"})

    assert len(result) == 1
    assert result[0].employee == "Alice Silva"
    assert result[0].hours == pytest.approx(1.5)


def test_transform_time_entries_bad_record_does_not_drop_the_batch(
    etl_service: EtlService, make_clockify_entry, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed entry is logged and skipped while valid siblings survive."""
    good_before = make_clockify_entry(entry_id="ok-1", user_id="user-1")
    malformed = {"id": "bad-1", "userId": "user-1"}  # no timeInterval -> KeyError
    good_after = make_clockify_entry(entry_id="ok-2", user_id="user-1")

    with caplog.at_level(logging.WARNING, logger=ETL_LOGGER):
        result = etl_service.transform_time_entries(
            [good_before, malformed, good_after], {"user-1": "alice.clockify@example.com"}
        )

    assert [entry.entry_id for entry in result] == ["ok-1", "ok-2"]
    assert "bad-1" in caplog.text


def test_transform_time_entries_unknown_user_gets_unmapped_sentinel(
    etl_service: EtlService, make_clockify_entry
) -> None:
    """An entry whose user id is not in the index falls back to the unmapped sentinel."""
    entries = [make_clockify_entry(user_id="ghost")]

    result = etl_service.transform_time_entries(entries, {})

    assert result[0].employee == f"Unmapped employee: {UNKNOWN_EMAIL}"


# --- transform_tasks (scenario #4) -----------------------------------------------


def test_transform_tasks_converts_valid_issue(etl_service: EtlService, make_jira_issue) -> None:
    """A well-formed issue is converted and its assignee normalised."""
    result = etl_service.transform_tasks([make_jira_issue(key="ABC-1")])

    assert len(result) == 1
    assert result[0].task_id == "ABC-1"
    assert result[0].assignee == "Alice Silva"


@pytest.mark.parametrize(
    "bad_field",
    [
        {"priority": {"name": "Critical"}},  # not a Priority enum value
        {"issuetype": {"name": "Improvement"}},  # not a TaskType enum value
        {"priority": None},  # null priority -> required field missing
    ],
)
def test_transform_tasks_discards_bad_issue_and_keeps_the_others(
    etl_service: EtlService, make_jira_issue, caplog: pytest.LogCaptureFixture, bad_field: dict
) -> None:
    """An out-of-enum or missing value discards only that issue, before and after alike."""
    issues = [
        make_jira_issue(key="ABC-1"),
        make_jira_issue(key="ABC-2", **bad_field),
        make_jira_issue(key="ABC-3"),
    ]

    with caplog.at_level(logging.ERROR, logger=ETL_LOGGER):
        result = etl_service.transform_tasks(issues)

    assert [task.task_id for task in result] == ["ABC-1", "ABC-3"]
    assert "Discarding Jira issue ABC-2" in caplog.text


def test_transform_tasks_discards_issue_missing_fields(
    etl_service: EtlService, make_jira_issue
) -> None:
    """An issue without a ``fields`` dict (KeyError) is discarded, not fatal."""
    issues = [make_jira_issue(key="ABC-1"), {"key": "ABC-2"}, make_jira_issue(key="ABC-3")]

    result = etl_service.transform_tasks(issues)

    assert [task.task_id for task in result] == ["ABC-1", "ABC-3"]


def test_transform_tasks_unassigned_issue_uses_placeholder(
    etl_service: EtlService, make_jira_issue
) -> None:
    """An unassigned issue keeps the placeholder name instead of being dropped."""
    result = etl_service.transform_tasks([make_jira_issue(assignee=None)])

    assert result[0].assignee == NO_RESPONSIBLE


def test_transform_tasks_missing_email_falls_back_to_registry_when_mapped(
    etl_service: EtlService, make_jira_issue
) -> None:
    """No email from Jira, but the resolved canonical name is registered: use its Jira email."""
    result = etl_service.transform_tasks(
        [make_jira_issue(assignee={"displayName": "Alice Silva", "emailAddress": None})]
    )

    assert result[0].assignee == "Alice Silva"
    assert result[0].assignee_email == "alice.jira@example.com"


def test_transform_tasks_missing_email_and_unmapped_name_leaves_email_none(
    etl_service: EtlService, make_jira_issue
) -> None:
    """No email from Jira and the name isn't registered either: no crash, no wrong fallback."""
    result = etl_service.transform_tasks(
        [make_jira_issue(assignee={"displayName": "Ghost Person", "emailAddress": None})]
    )

    assert result[0].assignee == "Unmapped employee: Ghost Person"
    assert result[0].assignee_email is None


def test_transform_tasks_with_email_never_consults_registry_fallback(
    etl_service: EtlService, make_jira_issue
) -> None:
    """When Jira already supplies an email, the registry fallback is never consulted."""
    with patch.object(
        etl_service.employee_registry,
        "get_jira_email",
        wraps=etl_service.employee_registry.get_jira_email,
    ) as spy:
        result = etl_service.transform_tasks([make_jira_issue()])

    assert result[0].assignee_email == "alice.jira@example.com"
    spy.assert_not_called()


def test_transform_tasks_unassigned_issue_never_consults_registry_fallback(
    etl_service: EtlService, make_jira_issue
) -> None:
    """An unassigned issue's sentinel name is never passed to the registry lookup."""
    with patch.object(
        etl_service.employee_registry,
        "get_jira_email",
        wraps=etl_service.employee_registry.get_jira_email,
    ) as spy:
        result = etl_service.transform_tasks([make_jira_issue(assignee=None)])

    assert result[0].assignee == NO_RESPONSIBLE
    assert result[0].assignee_email is None
    spy.assert_not_called()


# --- transform_details (basics + the divergence at the ETL layer) ----------------


def test_transform_details_extracts_description(make_jira_issue) -> None:
    """A description ADF tree is flattened to plain text on the detail record."""
    description = {
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello world"}]}]
    }
    details = EtlService.transform_details([make_jira_issue(key="ABC-1", description=description)])

    assert len(details) == 1
    assert details[0].task_id == "ABC-1"
    assert details[0].description == "Hello world"


def test_transform_details_skips_issue_missing_key(make_jira_issue) -> None:
    """An issue without a key is skipped, not fatal to the rest."""
    details = EtlService.transform_details([{"fields": {}}, make_jira_issue(key="ABC-2")])

    assert [detail.task_id for detail in details] == ["ABC-2"]


def test_transform_details_diverges_from_transform_tasks(
    etl_service: EtlService, make_jira_issue
) -> None:
    """A detail is still produced for an issue transform_tasks discards.

    ``transform_details`` runs over the raw, unfiltered issues, so a bad-priority
    issue that never becomes a Task still yields a detail here. This is exactly
    the divergence the pipeline-level ``valid_ids`` filter exists to correct.
    """
    issues = [make_jira_issue(key="ABC-2", priority={"name": "Critical"})]

    tasks = etl_service.transform_tasks(issues)
    details = EtlService.transform_details(issues)

    assert tasks == []
    assert [detail.task_id for detail in details] == ["ABC-2"]
