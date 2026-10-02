"""Pipeline-level tests for sync_clickup and sync_clockify (scenarios #5 and #12).

Every external client and the Excel writer are mocked; a real EtlService runs the
transforms. These prove two contracts: no detail is written for a task_id that
``transform_tasks`` discarded (scenario #5), and one failing Postgres upsert does
not abort the loop or skip the Excel write (scenario #12).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from sop_pipeline.pipeline import _filter_allowed_lists, sync_clickup, sync_clockify
from tests.conftest import UNMAPPED_LIST_ID

PIPELINE_LOGGER = "sop_pipeline.pipeline"

# --- _filter_allowed_lists ---------------------------------------------------------


def test_filter_allowed_lists_keeps_task_from_mapped_list(make_clickup_task) -> None:
    """A task whose list id is a key of CLICKUP_LIST_MAP passes through."""
    task = make_clickup_task()

    result = _filter_allowed_lists([task])

    assert result == [task]


def test_filter_allowed_lists_keeps_primeiro_ano_task_in_sub_folder(make_clickup_task) -> None:
    """Regression: the immediate parent folder ("Backend") no longer decides scope."""
    task = make_clickup_task(
        list={"id": "901715802315", "name": "POO"},
        folder={"id": "901711573295", "name": "Backend"},
    )

    result = _filter_allowed_lists([task])

    assert result == [task]


def test_filter_allowed_lists_drops_unmapped_list_with_warning(
    make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """A task from a list outside CLICKUP_LIST_MAP is dropped, and the drop is logged."""
    kept = make_clickup_task(task_id="ABC-1")
    dropped = [
        make_clickup_task(task_id="ABC-2", list={"id": UNMAPPED_LIST_ID, "name": "Nova lista"}),
        make_clickup_task(task_id="ABC-3", list={"id": UNMAPPED_LIST_ID, "name": "Nova lista"}),
    ]

    with caplog.at_level(logging.WARNING, logger=PIPELINE_LOGGER):
        result = _filter_allowed_lists([kept, *dropped])

    assert result == [kept]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "dropped 2 tasks from 1 lists" in warnings[0].getMessage()
    assert f"{UNMAPPED_LIST_ID} (Nova lista)" in warnings[0].getMessage()


def test_filter_allowed_lists_drops_task_missing_list(make_clickup_task) -> None:
    """A task with no list key at all is dropped rather than raising."""
    task = make_clickup_task()
    del task["list"]

    result = _filter_allowed_lists([task])

    assert result == []


def test_filter_allowed_lists_logs_nothing_when_all_kept(
    make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """No warning is emitted when every task is in scope."""
    with caplog.at_level(logging.WARNING, logger=PIPELINE_LOGGER):
        _filter_allowed_lists([make_clickup_task()])

    assert not caplog.records


# --- archive set and unarchiving ---------------------------------------------------


def test_sync_clickup_archive_set_includes_in_scope_task_that_failed_validation(
    etl_service, make_clickup_task
) -> None:
    """An in-scope task discarded by validation is still in the archive set.

    The unknown-priority task is still active in ClickUp; only our own parsing
    rejected it, so it must not be archived as if it had disappeared. A task
    from a list outside CLICKUP_LIST_MAP is out of scope and must not be in it.
    """
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        make_clickup_task(task_id="ABC-2", priority={"priority": "critical"}),
        make_clickup_task(task_id="ABC-3", list={"id": UNMAPPED_LIST_ID, "name": "Outra"}),
    ]
    postgres_client = MagicMock()

    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter"),
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        result = sync_clickup(etl_service, postgres_client, {})

    assert [task.task_id for task in result] == ["ABC-1"]
    postgres_client.archive_missing_tasks.assert_called_once_with({"ABC-1", "ABC-2"})


def test_sync_clickup_unarchives_reappearing_task_that_failed_validation(
    etl_service, make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """An archived task back with an unknown priority is unarchived but never upserted.

    Unarchiving uses the same set as archiving (every in-scope raw id, before
    validation), so a task ClickUp still returns is not left archived just
    because our own parsing rejected it.
    """
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        make_clickup_task(task_id="ABC-2", priority={"priority": "critical"}),
    ]
    postgres_client = MagicMock()
    postgres_client.unarchive_seen_tasks.return_value = 1

    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
        caplog.at_level(logging.INFO, logger=PIPELINE_LOGGER),
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        excel.unmark_archived_tasks.return_value = 1
        sync_clickup(etl_service, postgres_client, {})

    postgres_client.unarchive_seen_tasks.assert_called_once_with({"ABC-1", "ABC-2"})
    assert excel.unmark_archived_tasks.call_args.args[1] == {"ABC-1", "ABC-2"}
    upserted = [call.kwargs["task"].task_id for call in postgres_client.upsert_task.call_args_list]
    assert upserted == ["ABC-1"]
    saved = [task.task_id for task in excel.save_tasks.call_args.kwargs["tasks"]]
    assert saved == ["ABC-1"]
    assert "1 tasks unarchived in Postgres, 1 in Excel" in caplog.text


def test_sync_clickup_skips_archiving_when_in_scope_fetch_is_empty(
    etl_service, make_clickup_task, caplog: pytest.LogCaptureFixture
) -> None:
    """No in-scope task -> no archiving or unarchiving at all, and a WARNING says why."""
    tasks = [make_clickup_task(task_id="ABC-1", list={"id": UNMAPPED_LIST_ID, "name": "Outra"})]
    postgres_client = MagicMock()

    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
        caplog.at_level(logging.WARNING, logger=PIPELINE_LOGGER),
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        sync_clickup(etl_service, postgres_client, {})

    postgres_client.archive_missing_tasks.assert_not_called()
    postgres_client.unarchive_seen_tasks.assert_not_called()
    excel.mark_archived_tasks.assert_not_called()
    excel.unmark_archived_tasks.assert_not_called()
    assert "skipping archiving for this run" in caplog.text


# --- multiple assignees -------------------------------------------------------------

NAME_TO_ID = {"Alice Silva": 1, "Bob Souza": 2}


def _run_sync_with(etl_service, tasks: list[dict]) -> MagicMock:
    """Run sync_clickup over raw tasks with ClickUp and Excel mocked; return the DB mock."""
    postgres_client = MagicMock()
    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter"),
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        sync_clickup(etl_service, postgres_client, NAME_TO_ID)
    return postgres_client


def test_sync_clickup_links_every_registered_assignee(etl_service, make_clickup_task) -> None:
    """Regression: two assignees -> responsavel_id is the first, both get a link.

    responsavel_id used to be name_to_id.get(task.assignee), and the joined
    "Bob Souza, Alice Silva" string never matched, so it was always NULL.
    """
    task = make_clickup_task(
        task_id="ABC-1",
        assignees=[
            {"username": "Bob Souza", "email": "bob.jira@example.com"},
            {"username": "Alice Silva", "email": "alice.jira@example.com"},
        ],
    )

    postgres_client = _run_sync_with(etl_service, [task])

    assert postgres_client.upsert_task.call_args.kwargs["responsavel_id"] == 2
    postgres_client.sync_task_assignees.assert_called_once_with(
        task_id="ABC-1", funcionario_ids=[2, 1]
    )


def test_sync_clickup_skips_unmapped_assignee_link(etl_service, make_clickup_task) -> None:
    """One registered and one unmapped assignee -> one link, no exception."""
    task = make_clickup_task(
        task_id="ABC-1",
        assignees=[
            {"username": "Alice Silva", "email": "alice.jira@example.com"},
            {"username": "Ghost", "email": "ghost@example.com"},
        ],
    )

    postgres_client = _run_sync_with(etl_service, [task])

    assert postgres_client.upsert_task.call_args.kwargs["responsavel_id"] == 1
    postgres_client.sync_task_assignees.assert_called_once_with(
        task_id="ABC-1", funcionario_ids=[1]
    )


def test_sync_clickup_unmapped_first_assignee_leaves_responsavel_id_null(
    etl_service, make_clickup_task
) -> None:
    """responsavel_id is the first assignee, even when only a later one is registered."""
    task = make_clickup_task(
        task_id="ABC-1",
        assignees=[
            {"username": "Ghost", "email": "ghost@example.com"},
            {"username": "Alice Silva", "email": "alice.jira@example.com"},
        ],
    )

    postgres_client = _run_sync_with(etl_service, [task])

    assert postgres_client.upsert_task.call_args.kwargs["responsavel_id"] is None
    postgres_client.sync_task_assignees.assert_called_once_with(
        task_id="ABC-1", funcionario_ids=[1]
    )


def test_sync_clickup_discarded_task_gets_no_links(etl_service, make_clickup_task) -> None:
    """A task rejected by validation is neither upserted nor linked."""
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        make_clickup_task(task_id="ABC-2", priority={"priority": "critical"}),
    ]

    postgres_client = _run_sync_with(etl_service, tasks)

    linked = [call.kwargs["task_id"] for call in postgres_client.sync_task_assignees.call_args_list]
    assert linked == ["ABC-1"]


def test_sync_clickup_does_not_write_detail_for_discarded_task(
    etl_service, make_clickup_task
) -> None:
    """A detail is never written for a task_id absent from the final tasks list.

    The unknown-priority task is discarded by transform_tasks but would still get a
    detail from transform_details; the pipeline's valid_ids filter must drop it
    before both the Excel write and the Postgres upsert.
    """
    tasks = [
        make_clickup_task(task_id="ABC-1"),
        make_clickup_task(task_id="ABC-2", priority={"priority": "critical"}),
    ]
    postgres_client = MagicMock()

    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        result = sync_clickup(etl_service, postgres_client, {})

    assert [task.task_id for task in result] == ["ABC-1"]

    saved_details = excel.save_details.call_args.args[1]
    assert [detail.task_id for detail in saved_details] == ["ABC-1"]

    upserted_detail_ids = [
        call.kwargs["task_id"] for call in postgres_client.upsert_task_detail.call_args_list
    ]
    assert upserted_detail_ids == ["ABC-1"]
    assert "ABC-2" not in upserted_detail_ids


def test_sync_clickup_saves_subtask_whose_parent_is_not_in_the_run(
    etl_service, make_clickup_task
) -> None:
    """A subtask pointing at a task absent from this run is still upserted with its parent id."""
    task = make_clickup_task(task_id="ABC-2", parent="NOT-FETCHED")

    postgres_client = _run_sync_with(etl_service, [task])

    upserted = postgres_client.upsert_task.call_args.kwargs["task"]
    assert upserted.task_id == "ABC-2"
    assert upserted.parent_task_id == "NOT-FETCHED"
    postgres_client.upsert_task_detail.assert_called_once_with(
        task_id="ABC-2", descricao="Full description"
    )


def test_sync_clickup_one_failing_upsert_does_not_stop_the_rest(
    etl_service, make_clickup_task
) -> None:
    """A SQLAlchemyError on one task is isolated; the others and the Excel write proceed."""
    tasks = [make_clickup_task(task_id=f"ABC-{n}") for n in (1, 2, 3)]
    postgres_client = MagicMock()

    def fail_on_abc2(**kwargs) -> None:
        if kwargs["task"].task_id == "ABC-2":
            raise SQLAlchemyError("boom")

    postgres_client.upsert_task.side_effect = fail_on_abc2

    with (
        patch("sop_pipeline.pipeline.ClickUpClient") as clickup_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
    ):
        clickup_cls.return_value.fetch_tasks.return_value = tasks
        sync_clickup(etl_service, postgres_client, {})

    # All three tasks were attempted despite ABC-2 raising, and the workbook write
    # (which happens before the upsert loop) still occurred.
    attempted = [call.kwargs["task"].task_id for call in postgres_client.upsert_task.call_args_list]
    assert attempted == ["ABC-1", "ABC-2", "ABC-3"]
    excel.save_tasks.assert_called_once()


def test_sync_clockify_one_failing_upsert_does_not_stop_the_rest(
    etl_service, make_clockify_entry
) -> None:
    """A SQLAlchemyError on one time entry is isolated; the rest and the write proceed."""
    users = [{"id": "user-1", "email": "alice.clockify@example.com"}]
    entries = [make_clockify_entry(entry_id=f"entry-{n}", user_id="user-1") for n in (1, 2, 3)]
    postgres_client = MagicMock()

    def fail_on_entry2(**kwargs) -> None:
        if kwargs["entry_id"] == "entry-2":
            raise SQLAlchemyError("boom")

    postgres_client.upsert_time_entry.side_effect = fail_on_entry2

    with (
        patch("sop_pipeline.pipeline.ClockifyClient") as clockify_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
    ):
        client = clockify_cls.return_value
        client.list_users.return_value = users
        client.fetch_time_entries.return_value = entries
        sync_clockify(etl_service, postgres_client, {})

    attempted = [
        call.kwargs["entry_id"] for call in postgres_client.upsert_time_entry.call_args_list
    ]
    assert attempted == ["entry-1", "entry-2", "entry-3"]
    excel.save_hours.assert_called_once()
