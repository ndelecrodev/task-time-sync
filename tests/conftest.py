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

# The ClickUp "area" custom-field id the fake Settings is configured with; the
# ClickUp task factory keys the area field by this so _build_task can read it back.
AREA_FIELD_ID = "8dffc5a5-fake-clickup-area-field"

#: Options of the fake area drop-down field, in index order — mirrors the real
#: workspace's exact option set (ti, sop, ia, back-end, front-end, design, data).
AREA_OPTIONS = ["ti", "sop", "ia", "back-end", "front-end", "design", "data"]

# The fake folder ("turma") every make_clickup_task default lives in, and one
# folder deliberately NOT on the CLICKUP_FOLDER_IDS allowlist below, for the
# folder-filter tests.
ALLOWED_FOLDER_ID = "fake-folder-primeiro-ano"
ALLOWED_FOLDER_NAME = "Primeiro Ano"
DISALLOWED_FOLDER_ID = "fake-folder-not-a-turma"

# Obviously fake, example.com-style values for every variable Settings requires.
# Real environment variables outrank the .env file in pydantic-settings, so these
# win regardless of any local .env and keep Settings() away from real credentials.
# DATABASE_URL uses sqlite so create_engine never needs a real driver or server;
# the engine is never actually used because every DB access is mocked.
_FAKE_ENV = {
    "CLICKUP_API_TOKEN": "fake-clickup-token",
    "CLICKUP_TEAM_ID": "fake-team-id",
    "CLICKUP_SPACE_ID": "fake-space-id",
    "CLICKUP_FOLDER_IDS": ALLOWED_FOLDER_ID,
    "API_KEY_CLOCKIFY": "fake-clockify-key",
    "WORKSPACE_ID": "fake-workspace-id",
    "CLICKUP_AREA_FIELD_ID": AREA_FIELD_ID,
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
def make_clickup_task():
    """Factory for a raw ClickUp task dict; keyword overrides replace top-level keys.

    The defaults describe one fully valid task assigned to Alice, with the area
    field pointing at option index 0 ("ti"). Pass ``task_id`` to change the
    task's ClickUp id, or any top-level key (e.g. ``priority={"priority":
    "urgent"}`` or ``priority=None``) to build the malformed variants the tests
    need.
    """

    def _make(task_id: str = "86b2xyz1", **overrides) -> dict:
        task = {
            "id": task_id,
            "name": "Do the thing",
            "assignees": [
                {"username": "Alice Silva", "email": "alice.jira@example.com"},
            ],
            "priority": {"priority": "high"},
            "status": {"status": "In Progress"},
            "custom_fields": [
                {
                    "id": AREA_FIELD_ID,
                    "type": "drop_down",
                    "type_config": {"options": [{"name": name} for name in AREA_OPTIONS]},
                    "value": 0,
                }
            ],
            "date_created": "1735689600000",
            "due_date": "1738368000000",
            "date_closed": None,
            "date_updated": "1735948800000",
            "creator": {"username": "Carol Lima"},
            "tags": [{"name": "backend"}],
            "description": "Full description",
            "text_content": None,
            "folder": {"id": ALLOWED_FOLDER_ID, "name": ALLOWED_FOLDER_NAME},
        }
        task.update(overrides)
        return task

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
