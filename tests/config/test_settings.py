"""Tests for Settings.load_employee_registry (scenario #9).

A database failure must be caught and re-raised as SQLAlchemyError with a clear
log message rather than leaking a raw driver exception, and a config that maps one
email to two canonical names must surface as ValueError.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from sop_pipeline.config.employees import EmployeeRegistry
from sop_pipeline.config.settings import settings


def _employee_row(
    canonical_name: str,
    clickup_email: str,
    clockify_email: str,
    teams_email: str | None = None,
) -> SimpleNamespace:
    """A stand-in for a Funcionarios ORM row with the attributes the loader reads."""
    return SimpleNamespace(
        canonical_name=canonical_name,
        clickup_email=clickup_email,
        clockify_email=clockify_email,
        teams_email=teams_email,
    )


def test_load_employee_registry_returns_registry_on_success() -> None:
    """Rows fetched from Postgres are turned into a working registry."""
    rows = [
        _employee_row("Alice Silva", "alice.jira@example.com", "alice.clockify@example.com"),
        _employee_row("Bob Souza", "bob.jira@example.com", "bob.clockify@example.com"),
    ]
    client = MagicMock()
    client.get_employees.return_value = rows

    with patch("sop_pipeline.config.settings.PostgresClient", return_value=client):
        registry = settings.load_employee_registry()

    assert isinstance(registry, EmployeeRegistry)
    assert registry.resolve("alice.jira@example.com") == "Alice Silva"
    assert registry.resolve("bob.clockify@example.com") == "Bob Souza"


def test_load_employee_registry_reraises_database_error_with_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A driver failure is logged and re-raised as SQLAlchemyError, not swallowed."""
    client = MagicMock()
    client.get_employees.side_effect = OperationalError("SELECT 1", {}, Exception("no server"))

    with patch("sop_pipeline.config.settings.PostgresClient", return_value=client):
        with caplog.at_level(logging.ERROR, logger="sop_pipeline.config.settings"):
            with pytest.raises(SQLAlchemyError):
                settings.load_employee_registry()

    assert "Failure to connect to the database" in caplog.text


def test_load_employee_registry_raises_value_error_on_conflicting_mapping() -> None:
    """A duplicate email mapped to two names propagates as ValueError."""
    rows = [
        _employee_row("Alice Silva", "shared@example.com", "alice.clockify@example.com"),
        _employee_row("Bob Souza", "shared@example.com", "bob.clockify@example.com"),
    ]
    client = MagicMock()
    client.get_employees.return_value = rows

    with patch("sop_pipeline.config.settings.PostgresClient", return_value=client):
        with pytest.raises(ValueError, match="duplicate email in config"):
            settings.load_employee_registry()
