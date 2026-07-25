"""Tests for EmployeeDataSyncService (scenario #8).

Two rows sharing a jira_email or clockify_email must result in only the first
being upserted; every later row repeating either email is routed to the
duplicates sheet with a recorded reason.
"""

from unittest.mock import MagicMock, patch

import pytest

from sop_pipeline.services.employee_data_sync_service import EmployeeDataSyncService

SAVE_DUPLICATES = "sop_pipeline.services.employee_data_sync_service.ExcelWriter.save_duplicates"


def _row(nome: str, jira_email: str, clockify_email: str, photo_url: str | None = None) -> dict:
    """One employee row as ExcelReader.read_employees would return it."""
    return {
        "nome": nome,
        "jira_email": jira_email,
        "clockify_email": clockify_email,
        "photo_url": photo_url,
    }


def _service(rows: list[dict]) -> tuple[EmployeeDataSyncService, MagicMock]:
    """Build the service with a reader that returns ``rows`` and a mock DB client."""
    reader = MagicMock()
    reader.read_employees.return_value = rows
    postgres_client = MagicMock()
    return EmployeeDataSyncService(reader, postgres_client), postgres_client


@pytest.mark.parametrize("colliding_field", ["jira_email", "clockify_email"])
def test_sync_upserts_only_first_of_duplicate_email(colliding_field: str) -> None:
    """Only the first row of a colliding email is upserted; the rest are duplicates."""
    shared = "shared@example.com"
    first = _row(
        "Alice Silva",
        jira_email=shared if colliding_field == "jira_email" else "alice.jira@example.com",
        clockify_email=shared if colliding_field == "clockify_email" else "alice.ck@example.com",
    )
    second = _row(
        "Alice Duplicate",
        jira_email=shared if colliding_field == "jira_email" else "alice2.jira@example.com",
        clockify_email=shared if colliding_field == "clockify_email" else "alice2.ck@example.com",
    )
    service, postgres_client = _service([first, second])

    with patch(SAVE_DUPLICATES) as save_duplicates:
        service.sync("workbook.xlsx")

    postgres_client.upsert_employee.assert_called_once_with(
        canonical_name="Alice Silva",
        jira_email=first["jira_email"],
        clockify_email=first["clockify_email"],
        photo_url=first["photo_url"],
    )
    saved = save_duplicates.call_args.args[1]
    assert [row["nome"] for row in saved] == ["Alice Duplicate"]


def test_sync_records_reason_on_duplicate_rows() -> None:
    """A duplicate row carries the exact Portuguese reason string."""
    first = _row("Alice Silva", "alice.jira@example.com", "alice.ck@example.com")
    second = _row("Alice Two", "alice.jira@example.com", "alice2.ck@example.com")
    service, _ = _service([first, second])

    with patch(SAVE_DUPLICATES) as save_duplicates:
        service.sync("workbook.xlsx")

    saved = save_duplicates.call_args.args[1]
    assert saved[0]["reason"] == (
        "E-mail já foi cadastrado: alice.jira@example.com ou alice2.ck@example.com"
    )


def test_sync_treats_repeated_clockify_email_alone_as_duplicate() -> None:
    """A fresh jira_email but a repeated clockify_email is still a duplicate."""
    first = _row("Alice Silva", "alice.jira@example.com", "shared.ck@example.com")
    second = _row("Bob Souza", "bob.jira@example.com", "shared.ck@example.com")
    service, postgres_client = _service([first, second])

    with patch(SAVE_DUPLICATES) as save_duplicates:
        service.sync("workbook.xlsx")

    assert postgres_client.upsert_employee.call_count == 1
    saved = save_duplicates.call_args.args[1]
    assert [row["nome"] for row in saved] == ["Bob Souza"]


def test_sync_does_not_save_duplicates_when_all_rows_unique() -> None:
    """With no duplicates, every row is upserted and save_duplicates is never called."""
    rows = [
        _row("Alice Silva", "alice.jira@example.com", "alice.ck@example.com"),
        _row("Bob Souza", "bob.jira@example.com", "bob.ck@example.com"),
    ]
    service, postgres_client = _service(rows)

    with patch(SAVE_DUPLICATES) as save_duplicates:
        service.sync("workbook.xlsx")

    assert postgres_client.upsert_employee.call_count == 2
    save_duplicates.assert_not_called()
