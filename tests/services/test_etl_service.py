"""Tests for EtlService (scenarios #2, #3, #4).

These exercise the "never fail the whole batch over one bad record" contract: a
single malformed record is logged and skipped while every other record in the
batch survives, and unmapped employees are marked with a visible sentinel rather
than dropped.
"""

import logging
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from sop_pipeline.models.schemas import Priority, TaskType
from sop_pipeline.services.etl_service import (
    NO_AREA,
    NO_RESPONSIBLE,
    UNKNOWN_EMAIL,
    EtlService,
)
from tests.conftest import MAPPED_LIST_AREA, MAPPED_LIST_TURMA, UNMAPPED_LIST_ID

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


def test_transform_tasks_converts_valid_task(etl_service: EtlService, make_clickup_task) -> None:
    """A well-formed task is converted and its assignee normalised."""
    result = etl_service.transform_tasks([make_clickup_task(task_id="ABC-1")])

    assert len(result) == 1
    assert result[0].task_id == "ABC-1"
    assert result[0].assignee == "Alice Silva"


# --- completion_date (current ClickUp status type) --------------------------------

DONE_MILLIS = "1738368000000"  # 2025-01-31 21:00 in Sao Paulo
CLOSED_MILLIS = "1738540800000"  # 2025-02-02 21:00 in Sao Paulo


def test_transform_tasks_done_status_uses_date_done(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "done" status has no date_closed, so completion falls back to date_done."""
    task = make_clickup_task(
        status={"status": "done", "type": "done"}, date_closed=None, date_done=DONE_MILLIS
    )

    result = etl_service.transform_tasks([task])

    assert result[0].completion_date.isoformat() == "2025-01-31"


def test_transform_tasks_closed_status_prefers_date_closed(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A "closed" status uses date_closed even when date_done is also filled."""
    task = make_clickup_task(
        status={"status": "Closed", "type": "closed"},
        date_closed=CLOSED_MILLIS,
        date_done=DONE_MILLIS,
    )

    result = etl_service.transform_tasks([task])

    assert result[0].completion_date.isoformat() == "2025-02-02"


@pytest.mark.parametrize("status_type", ["custom", "open", "unstarted"])
def test_transform_tasks_unfinished_status_ignores_stale_dates(
    etl_service: EtlService, make_clickup_task, status_type: str
) -> None:
    """A reopened task loses its completion date even if ClickUp still sends one."""
    task = make_clickup_task(
        status={"status": "review", "type": status_type},
        date_closed=CLOSED_MILLIS,
        date_done=DONE_MILLIS,
    )

    result = etl_service.transform_tasks([task])

    assert result[0].completion_date is None
    assert result[0].status == "review"


@pytest.mark.parametrize(
    "status",
    [{"status": "done"}, {"status": "done", "type": None}],
    ids=["no-type", "null-type"],
)
def test_transform_tasks_status_without_type_is_not_completed(
    etl_service: EtlService, make_clickup_task, status: dict
) -> None:
    """A status with no type reads as not completed, without raising."""
    task = make_clickup_task(status=status, date_closed=CLOSED_MILLIS, date_done=DONE_MILLIS)

    result = etl_service.transform_tasks([task])

    assert result[0].completion_date is None


def test_build_task_missing_status_key_does_not_raise_on_type(
    etl_service: EtlService, make_clickup_task
) -> None:
    """With no status key at all, the type lookup does not raise."""
    raw_task = make_clickup_task()
    del raw_task["status"]

    with pytest.raises(ValidationError) as excinfo:
        etl_service._build_task(raw_task)  # pylint: disable=protected-access

    # The only failure is the required free-text status, never the type lookup.
    assert [error["loc"] for error in excinfo.value.errors()] == [("status",)]


# --- assignee_names ----------------------------------------------------------------


def test_transform_tasks_keeps_each_assignee_name_in_source_order(
    etl_service: EtlService, make_clickup_task
) -> None:
    """assignee_names lists every canonical name; assignee stays the joined string."""
    task = make_clickup_task(
        assignees=[
            {"username": "Bob Souza", "email": "bob.jira@example.com"},
            {"username": "Ghost", "email": "ghost@example.com"},
            {"username": "Alice Silva", "email": "alice.jira@example.com"},
        ]
    )

    result = etl_service.transform_tasks([task])

    assert result[0].assignee_names == [
        "Bob Souza",
        "Unmapped employee: ghost@example.com",
        "Alice Silva",
    ]
    assert result[0].assignee == ", ".join(result[0].assignee_names)
    assert result[0].assignee_email == "bob.jira@example.com"


def test_transform_tasks_unassigned_task_has_no_assignee_names(
    etl_service: EtlService, make_clickup_task
) -> None:
    """An unassigned task keeps the placeholder in assignee but lists no names."""
    result = etl_service.transform_tasks([make_clickup_task(assignees=[])])

    assert result[0].assignee == NO_RESPONSIBLE
    assert result[0].assignee_names == []


def test_transform_tasks_discards_bad_task_and_keeps_the_others(
    etl_service: EtlService, make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """An unmapped priority label discards only that task, before and after alike."""
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        make_clickup_task(task_id="ABC-2", priority={"priority": "critical"}),
        make_clickup_task(task_id="ABC-3"),
    ]

    with caplog.at_level(logging.ERROR, logger=ETL_LOGGER):
        result = etl_service.transform_tasks(tasks)

    assert [task.task_id for task in result] == ["ABC-1", "ABC-3"]
    assert "Discarding ClickUp task ABC-2" in caplog.text


def test_transform_tasks_discards_task_missing_fields(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task without an ``assignees`` key (KeyError) is discarded, not fatal."""
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        {"id": "ABC-2"},
        make_clickup_task(task_id="ABC-3"),
    ]

    result = etl_service.transform_tasks(tasks)

    assert [task.task_id for task in result] == ["ABC-1", "ABC-3"]


def test_transform_tasks_unassigned_task_uses_placeholder(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task with no assignees keeps the placeholder name instead of being dropped."""
    result = etl_service.transform_tasks([make_clickup_task(assignees=[])])

    assert result[0].assignee == NO_RESPONSIBLE
    assert result[0].assignee_email is None


def test_transform_tasks_joins_multiple_assignees_into_one_string(
    etl_service: EtlService, make_clickup_task
) -> None:
    """Multiple assignees are each normalised and joined into one comma-separated string."""
    result = etl_service.transform_tasks(
        [
            make_clickup_task(
                assignees=[
                    {"username": "Alice Silva", "email": "alice.jira@example.com"},
                    {"username": "Bob Souza", "email": "bob.jira@example.com"},
                ]
            )
        ]
    )

    assert result[0].assignee == "Alice Silva, Bob Souza"


def test_transform_tasks_assignee_email_uses_first_assignee_only(
    etl_service: EtlService, make_clickup_task
) -> None:
    """With multiple assignees, assignee_email carries only the first one's address."""
    result = etl_service.transform_tasks(
        [
            make_clickup_task(
                assignees=[
                    {"username": "Alice Silva", "email": "alice.jira@example.com"},
                    {"username": "Bob Souza", "email": "bob.jira@example.com"},
                ]
            )
        ]
    )

    assert result[0].assignee_email == "alice.jira@example.com"


def test_transform_tasks_missing_email_falls_back_to_registry_when_mapped(
    etl_service: EtlService, make_clickup_task
) -> None:
    """No email from ClickUp, but the resolved canonical name is registered: use its registered email."""
    result = etl_service.transform_tasks(
        [make_clickup_task(assignees=[{"username": "Alice Silva", "email": None}])]
    )

    assert result[0].assignee == "Alice Silva"
    assert result[0].assignee_email == "alice.jira@example.com"


def test_transform_tasks_missing_email_and_unmapped_name_leaves_email_none(
    etl_service: EtlService, make_clickup_task
) -> None:
    """No email from ClickUp and the name isn't registered either: no crash, no wrong fallback."""
    result = etl_service.transform_tasks(
        [make_clickup_task(assignees=[{"username": "Ghost Person", "email": None}])]
    )

    assert result[0].assignee == "Unmapped employee: Ghost Person"
    assert result[0].assignee_email is None


def test_transform_tasks_with_email_never_consults_registry_fallback(
    etl_service: EtlService, make_clickup_task
) -> None:
    """When ClickUp already supplies an email, the registry fallback is never consulted."""
    with patch.object(
        etl_service.employee_registry,
        "get_registered_email",
        wraps=etl_service.employee_registry.get_registered_email,
    ) as spy:
        result = etl_service.transform_tasks([make_clickup_task()])

    assert result[0].assignee_email == "alice.jira@example.com"
    spy.assert_not_called()


def test_transform_tasks_unassigned_task_never_consults_registry_fallback(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task with no assignees never calls the registry-email fallback."""
    with patch.object(
        etl_service.employee_registry,
        "get_registered_email",
        wraps=etl_service.employee_registry.get_registered_email,
    ) as spy:
        result = etl_service.transform_tasks([make_clickup_task(assignees=[])])

    assert result[0].assignee == NO_RESPONSIBLE
    assert result[0].assignee_email is None
    spy.assert_not_called()


# --- teams_email priority ----------------------------------------------------------


def test_transform_tasks_teams_email_overrides_clickup_own_email(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A registered teams_email wins even when ClickUp itself provided an email."""
    with patch.object(
        etl_service.employee_registry, "get_teams_email", return_value="alice.teams@example.com"
    ):
        result = etl_service.transform_tasks([make_clickup_task()])

    assert result[0].assignee_email == "alice.teams@example.com"


def test_transform_tasks_teams_email_overrides_when_clickup_gave_no_email(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A registered teams_email still wins when ClickUp provided no email at all.

    Confirms teams_email is checked outside the no-email fallback branch, not
    only inside it.
    """
    with patch.object(
        etl_service.employee_registry, "get_teams_email", return_value="alice.teams@example.com"
    ):
        result = etl_service.transform_tasks(
            [make_clickup_task(assignees=[{"username": "Alice Silva", "email": None}])]
        )

    assert result[0].assignee_email == "alice.teams@example.com"


def test_transform_tasks_no_teams_email_uses_clickup_own_email(
    etl_service: EtlService, make_clickup_task
) -> None:
    """No registered teams_email: ClickUp's own email is used, unchanged."""
    with patch.object(
        etl_service.employee_registry,
        "get_teams_email",
        wraps=etl_service.employee_registry.get_teams_email,
    ) as spy:
        result = etl_service.transform_tasks([make_clickup_task()])

    assert result[0].assignee_email == "alice.jira@example.com"
    spy.assert_called_once_with("Alice Silva")


def test_transform_tasks_no_teams_email_falls_back_to_registry(
    etl_service: EtlService, make_clickup_task
) -> None:
    """No registered teams_email and no ClickUp email: registry fallback is used, unchanged."""
    with patch.object(
        etl_service.employee_registry,
        "get_teams_email",
        wraps=etl_service.employee_registry.get_teams_email,
    ):
        result = etl_service.transform_tasks(
            [make_clickup_task(assignees=[{"username": "Alice Silva", "email": None}])]
        )

    assert result[0].assignee_email == "alice.jira@example.com"


def test_transform_tasks_unassigned_task_never_consults_teams_email(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task with no assignees never calls get_teams_email, and does not crash."""
    with patch.object(
        etl_service.employee_registry,
        "get_teams_email",
        wraps=etl_service.employee_registry.get_teams_email,
    ) as spy:
        result = etl_service.transform_tasks([make_clickup_task(assignees=[])])

    assert result[0].assignee == NO_RESPONSIBLE
    assert result[0].assignee_email is None
    spy.assert_not_called()


# --- turma and area (CLICKUP_LIST_MAP) ---------------------------------------------


def test_transform_tasks_takes_turma_and_area_from_list_not_folder(
    etl_service: EtlService, make_clickup_task
) -> None:
    """Regression: a Primeiro Ano task in a sub-folder keeps its turma and area.

    After "Primeiro Ano" was split into sub-folders, ClickUp reports only the
    immediate parent (here "Backend"); turma must come from the list mapping.
    """
    task = make_clickup_task(
        list={"id": "901715802315", "name": "POO"},
        folder={"id": "901711573295", "name": "Backend"},
    )

    result = etl_service.transform_tasks([task])

    assert result[0].turma == "Primeiro Ano"
    assert result[0].area == "back-end"


def test_transform_tasks_resolves_area_and_turma_from_mapped_list(
    etl_service: EtlService, make_clickup_task
) -> None:
    """The default fixture list resolves to its mapped area and turma."""
    result = etl_service.transform_tasks([make_clickup_task()])

    assert result[0].area == MAPPED_LIST_AREA
    assert result[0].turma == MAPPED_LIST_TURMA


def test_transform_tasks_ignores_folder_name_for_turma(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A folder named like another turma does not override the list mapping."""
    task = make_clickup_task(folder={"id": "901710321390", "name": "Segundo Ano"})

    result = etl_service.transform_tasks([task])

    assert result[0].turma == MAPPED_LIST_TURMA


def test_transform_tasks_keeps_task_missing_folder(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task with no folder key is still converted: folder is no longer read."""
    task = make_clickup_task()
    del task["folder"]

    result = etl_service.transform_tasks([task])

    assert result[0].turma == MAPPED_LIST_TURMA


@pytest.mark.parametrize(
    "task_list",
    [{"id": UNMAPPED_LIST_ID}, {}, None],
    ids=["unmapped-id", "no-id", "no-list"],
)
def test_transform_tasks_discards_task_outside_list_map(
    etl_service: EtlService, make_clickup_task, caplog: pytest.LogCaptureFixture, task_list
) -> None:
    """A task whose list is not in CLICKUP_LIST_MAP is discarded and logged.

    pipeline._filter_allowed_lists keeps such tasks from ever reaching
    _build_task; this only covers the defensive KeyError/TypeError path.
    """
    task = make_clickup_task()
    if task_list is None:
        del task["list"]
    else:
        task["list"] = task_list

    with caplog.at_level(logging.ERROR, logger=ETL_LOGGER):
        result = etl_service.transform_tasks([task])

    assert result == []
    assert "Discarding ClickUp task" in caplog.text


def test_transform_tasks_resolves_area_for_another_mapped_list(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A different mapped list id resolves to its own area, not always the same one."""
    task = make_clickup_task(list={"id": "901715802315"})  # back-end (POO)

    result = etl_service.transform_tasks([task])

    assert result[0].area == "back-end"


def test_transform_tasks_resolves_area_for_a_segundo_ano_list(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A Segundo Ano list id resolves to its own area, same mapping as Primeiro Ano."""
    task = make_clickup_task(list={"id": "901715802576"})  # data (Modelagem de dados)

    result = etl_service.transform_tasks([task])

    assert result[0].area == "data"
    assert result[0].turma == "Segundo Ano"


def test_transform_tasks_resolves_area_for_another_segundo_ano_list(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A second Segundo Ano list id resolves to its own, previously-unused area."""
    task = make_clickup_task(list={"id": "901715802775"})  # dad (DAD)

    result = etl_service.transform_tasks([task])

    assert result[0].area == "dad"


# --- priority mapping ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("clickup_priority", "expected"),
    [
        ("urgent", "Highest"),
        ("high", "High"),
        ("normal", "Medium"),
        ("low", "Low"),
    ],
)
def test_transform_tasks_maps_clickup_priority_to_enum(
    etl_service: EtlService, make_clickup_task, clickup_priority: str, expected: str
) -> None:
    """Each of ClickUp's four priority levels maps onto the matching Priority member."""
    result = etl_service.transform_tasks(
        [make_clickup_task(priority={"priority": clickup_priority})]
    )

    assert result[0].priority.value == expected


@pytest.mark.parametrize(
    "priority_field",
    [
        {"priority": None},  # ClickUp's shape when no priority is set
        {"priority": {"priority": None}},
    ],
)
def test_transform_tasks_null_priority_keeps_task_as_sem_prioridade(
    etl_service: EtlService,
    make_clickup_task,
    caplog: pytest.LogCaptureFixture,
    priority_field: dict,
) -> None:
    """A task with no priority set is kept as "Sem prioridade", never discarded."""
    with caplog.at_level(logging.ERROR, logger=ETL_LOGGER):
        result = etl_service.transform_tasks([make_clickup_task(**priority_field)])

    assert len(result) == 1
    assert result[0].priority is Priority.NO_PRIORITY
    assert result[0].priority.value == "Sem prioridade"
    assert "Discarding ClickUp task" not in caplog.text


def test_transform_tasks_absent_priority_key_keeps_task_as_sem_prioridade(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A payload with no ``priority`` key at all is treated like a null priority."""
    raw_task = make_clickup_task()
    del raw_task["priority"]

    result = etl_service.transform_tasks([raw_task])

    assert result[0].priority is Priority.NO_PRIORITY


def test_transform_tasks_unknown_priority_label_is_still_discarded(
    etl_service: EtlService, make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-null label missing from CLICKUP_PRIORITY_MAP goes through the usual discard."""
    with caplog.at_level(logging.ERROR, logger=ETL_LOGGER):
        result = etl_service.transform_tasks(
            [make_clickup_task(task_id="ABC-9", priority={"priority": "critical"})]
        )

    assert result == []
    assert "Discarding ClickUp task ABC-9, it could not be converted" in caplog.text


# --- subtasks -----------------------------------------------------------------------


def test_transform_tasks_subtask_keeps_parent_id_and_type(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A raw task with a parent becomes a SUBTASK pointing at that parent."""
    result = etl_service.transform_tasks([make_clickup_task(task_id="ABC-2", parent="ABC-1")])

    assert result[0].parent_task_id == "ABC-1"
    assert result[0].task_type is TaskType.SUBTASK


@pytest.mark.parametrize("parent_field", [{"parent": None}, {}])
def test_transform_tasks_task_without_parent_is_a_regular_task(
    etl_service: EtlService, make_clickup_task, parent_field: dict
) -> None:
    """A null or absent parent leaves parent_task_id None and task_type TASK."""
    result = etl_service.transform_tasks([make_clickup_task(**parent_field)])

    assert result[0].parent_task_id is None
    assert result[0].task_type is TaskType.TASK


def test_transform_tasks_nested_subtask_stores_immediate_parent(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A subtask of a subtask points at the subtask above it, not the top-level task."""
    tasks = [
        make_clickup_task(task_id="TOP"),
        make_clickup_task(task_id="MID", parent="TOP", top_level_parent="TOP"),
        make_clickup_task(task_id="LEAF", parent="MID", top_level_parent="TOP"),
    ]

    result = {task.task_id: task.parent_task_id for task in etl_service.transform_tasks(tasks)}

    assert result == {"TOP": None, "MID": "TOP", "LEAF": "MID"}


# --- millisecond-timestamp conversion ---------------------------------------------


def test_parse_millis_to_date_converts_a_timestamp() -> None:
    """A millisecond-timestamp string converts to the matching America/Sao_Paulo date."""
    # 1735689600000 ms = 2025-01-01T00:00:00Z = 2024-12-31 in America/Sao_Paulo (UTC-3).
    result = EtlService._parse_millis_to_date("1735689600000")  # pylint: disable=protected-access

    assert result.isoformat() == "2024-12-31"


def test_parse_millis_to_date_returns_none_for_none() -> None:
    """A ``None`` timestamp converts to ``None``, e.g. an open task's ``date_closed``."""
    result = EtlService._parse_millis_to_date(None)  # pylint: disable=protected-access

    assert result is None


def test_transform_tasks_open_task_has_no_completion_date(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A task with ``date_closed: null`` converts to a Task with completion_date None."""
    result = etl_service.transform_tasks([make_clickup_task(date_closed=None)])

    assert result[0].completion_date is None


def test_transform_tasks_closed_task_has_a_completion_date(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A closed task with a millisecond ``date_closed`` gets a concrete completion_date."""
    task = make_clickup_task(
        status={"status": "Closed", "type": "closed"}, date_closed="1738368000000"
    )
    result = etl_service.transform_tasks([task])

    assert result[0].completion_date is not None


# --- transform_details (basics + the divergence at the ETL layer) ----------------


def test_transform_details_extracts_description(make_clickup_task) -> None:
    """A task's plain-text description carries straight through to the detail record."""
    details = EtlService.transform_details(
        [make_clickup_task(task_id="ABC-1", description="Hello world")]
    )

    assert len(details) == 1
    assert details[0].task_id == "ABC-1"
    assert details[0].description == "Hello world"


def test_transform_details_falls_back_to_text_content(make_clickup_task) -> None:
    """When ``description`` is absent, the detail falls back to ``text_content``."""
    details = EtlService.transform_details(
        [make_clickup_task(task_id="ABC-1", description=None, text_content="Plain fallback")]
    )

    assert details[0].description == "Plain fallback"


def test_transform_details_skips_task_missing_id(make_clickup_task) -> None:
    """A task without an id is skipped, not fatal to the rest."""
    details = EtlService.transform_details([{"name": "no id"}, make_clickup_task(task_id="ABC-2")])

    assert [detail.task_id for detail in details] == ["ABC-2"]


def test_transform_details_diverges_from_transform_tasks(
    etl_service: EtlService, make_clickup_task
) -> None:
    """A detail is still produced for a task transform_tasks discards.

    ``transform_details`` runs over the raw, unfiltered tasks, so a task with an
    unmapped priority label that never becomes a Task still yields a detail
    here. This is exactly the divergence the pipeline-level ``valid_ids``
    filter exists to correct.
    """
    tasks = [make_clickup_task(task_id="ABC-2", priority={"priority": "critical"})]

    built_tasks = etl_service.transform_tasks(tasks)
    details = EtlService.transform_details(tasks)

    assert built_tasks == []
    assert [detail.task_id for detail in details] == ["ABC-2"]
