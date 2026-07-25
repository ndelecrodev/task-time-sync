"""Shared fixtures and test-environment setup for the SOP pipeline suite.

Importing anything under ``sop_pipeline`` triggers ``Settings()`` (which validates
a fully populated environment) and ``create_engine`` at module import time, and
constructing :class:`~sop_pipeline.services.etl_service.EtlService` performs a live
``get_employees`` database call. Fake environment variables are therefore installed
*before* the first ``sop_pipeline`` import, and the ``etl_service`` fixture patches
the registry loader, so no test ever reaches a real database, network or ``.env``.
"""

import os
from unittest.mock import patch

import pytest

# Fixtures that consume other fixtures legitimately shadow their names; this is
# the standard pytest idiom, not the bug redefined-outer-name is meant to catch.
# pylint: disable=redefined-outer-name

# The Jira "area" custom-field id the fake Settings is configured with; the Jira
# issue factory keys the area field by this so _build_task can read it back.
AREA_FIELD = "customfield_10001"

# Obviously fake, example.com-style values for every variable Settings requires.
# Real environment variables outrank the .env file in pydantic-settings, so these
# win regardless of any local .env and keep Settings() away from real credentials.
# DATABASE_URL uses sqlite so create_engine never needs a real driver or server;
# the engine is never actually used because every DB access is mocked.
_FAKE_ENV = {
    "JIRA_URL": "https://jira.example.com",
    "JIRA_EMAIL": "pipeline@example.com",
    "JIRA_API_TOKEN": "fake-jira-token",
    "API_KEY_CLOCKIFY": "fake-clockify-key",
    "WORKSPACE_ID": "fake-workspace-id",
    "JIRA_CUSTOMFIELD_AREA": AREA_FIELD,
    "WEBHOOK_TI": "https://teams.example.com/ti",
    "WEBHOOK_SOP": "https://teams.example.com/sop",
    "WEBHOOK_IA": "https://teams.example.com/ia",
    "WEBHOOK_FRONT": "https://teams.example.com/front",
    "WEBHOOK_DESIGN": "https://teams.example.com/design",
    "WEBHOOK_DATA": "https://teams.example.com/data",
    "WEBHOOK_BACK": "https://teams.example.com/back",
    "WEBHOOK_NO_AREA": "https://teams.example.com/no-area",
    "B2_ENDPOINT_URL": "https://s3.example.com",
    "B2_BUCKET_NAME": "fake-bucket",
    "B2_APPLICATION_KEY": "fake-app-key",
    "B2_KEY_ID": "fake-key-id",
    "JIRA_JQL": "project = FAKE",
    "EXCEL_CLOUD_NAME": "planilha.xlsx",
    "SENTRY_DSN": "https://public@sentry.example.com/1",
    "BETTERSTACK_HEARTBEAT_URL": "https://uptime.example.com/heartbeat",
    "BETTERSTACK_SOURCE_TOKEN": "fake-source-token",
    "BETTERSTACK_INGESTING_HOST": "https://logs.example.com",
    "DATABASE_URL": "sqlite+pysqlite:///:memory:",
    "TEMP_EXCEL_PATH": "planilha_temp.xlsx",
}
os.environ.update(_FAKE_ENV)

# Imported only after the fake environment is in place.
# pylint: disable=wrong-import-position
from sop_pipeline.config.employees import EmployeeMapping, EmployeeRegistry
from sop_pipeline.config.settings import Settings
from sop_pipeline.services.etl_service import EtlService


@pytest.fixture
def employee_mappings() -> list[EmployeeMapping]:
    """Two consistent employee mappings with fake example.com identifiers."""
    return [
        EmployeeMapping(
            canonical_name="Alice Silva",
            jira_email="alice.jira@example.com",
            clockify_email="alice.clockify@example.com",
        ),
        EmployeeMapping(
            canonical_name="Bob Souza",
            jira_email="bob.jira@example.com",
            clockify_email="bob.clockify@example.com",
        ),
    ]


@pytest.fixture
def employee_registry(employee_mappings: list[EmployeeMapping]) -> EmployeeRegistry:
    """A registry built from the shared mappings."""
    return EmployeeRegistry(employee_mappings)


@pytest.fixture
def etl_service(employee_registry: EmployeeRegistry) -> EtlService:
    """A real EtlService whose registry loader is patched to avoid the DB.

    ``EtlService.__init__`` normally calls ``settings.load_employee_registry()``,
    which opens a real database session. The method is patched on the ``Settings``
    class (pydantic forbids setting a non-field attribute on the instance), which
    keeps construction offline while exercising the genuine service.
    """
    with patch.object(Settings, "load_employee_registry", return_value=employee_registry):
        yield EtlService()


@pytest.fixture
def make_jira_issue():
    """Factory for a raw Jira issue dict; keyword overrides replace ``fields`` keys.

    The defaults describe one fully valid issue assigned to Alice. Pass ``key`` to
    change the issue key, or any ``fields`` key (e.g. ``priority={"name": "Critical"}``
    or ``priority=None``) to build the malformed variants the tests need.
    """

    def _make(key: str = "ABC-1", **field_overrides) -> dict:
        fields = {
            "summary": "Do the thing",
            "assignee": {
                "displayName": "Alice Silva",
                "emailAddress": "alice.jira@example.com",
            },
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            AREA_FIELD: {"value": "TI"},
            "created": "2026-01-01T09:00:00.000-0300",
            "duedate": "2026-02-01",
            "resolutiondate": None,
            "issuetype": {"name": "Task"},
            "creator": {"displayName": "Carol Lima"},
            "updated": "2026-01-05T09:00:00.000-0300",
            "labels": ["backend"],
        }
        fields.update(field_overrides)
        return {"key": key, "fields": fields}

    return _make


@pytest.fixture
def make_clockify_entry():
    """Factory for a raw Clockify time-entry dict."""

    def _make(
        entry_id: str = "entry-1",
        user_id: str = "user-1",
        duration: str | None = "PT1H30M",
        start: str = "2026-01-01T12:00:00Z",
    ) -> dict:
        return {
            "id": entry_id,
            "userId": user_id,
            "timeInterval": {"duration": duration, "start": start},
        }

    return _make
