"""Pipeline-level tests for sync_jira and sync_clockify (scenarios #5 and #12).

Every external client and the Excel writer are mocked; a real EtlService runs the
transforms. These prove two contracts: no detail is written for a task_id that
``transform_tasks`` discarded (scenario #5), and one failing Postgres upsert does
not abort the loop or skip the Excel write (scenario #12).
"""

from unittest.mock import MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from sop_pipeline.pipeline import sync_clockify, sync_jira


def test_sync_jira_does_not_write_detail_for_discarded_task(etl_service, make_jira_issue) -> None:
    """A detail is never written for a task_id absent from the final tasks list.

    The bad-priority issue is discarded by transform_tasks but would still get a
    detail from transform_details; the pipeline's valid_ids filter must drop it
    before both the Excel write and the Postgres upsert.
    """
    issues = [
        make_jira_issue(key="ABC-1"),
        make_jira_issue(key="ABC-2", priority={"name": "Critical"}),
    ]
    postgres_client = MagicMock()

    with (
        patch("sop_pipeline.pipeline.JiraClient") as jira_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
    ):
        jira_cls.return_value.fetch_tasks.return_value = issues
        tasks = sync_jira(etl_service, postgres_client, {})

    assert [task.task_id for task in tasks] == ["ABC-1"]

    saved_details = excel.save_details.call_args.args[1]
    assert [detail.task_id for detail in saved_details] == ["ABC-1"]

    upserted_detail_ids = [
        call.kwargs["task_id"] for call in postgres_client.upsert_task_detail.call_args_list
    ]
    assert upserted_detail_ids == ["ABC-1"]
    assert "ABC-2" not in upserted_detail_ids


def test_sync_jira_one_failing_upsert_does_not_stop_the_rest(etl_service, make_jira_issue) -> None:
    """A SQLAlchemyError on one task is isolated; the others and the Excel write proceed."""
    issues = [make_jira_issue(key=f"ABC-{n}") for n in (1, 2, 3)]
    postgres_client = MagicMock()

    def fail_on_abc2(**kwargs) -> None:
        if kwargs["task"].task_id == "ABC-2":
            raise SQLAlchemyError("boom")

    postgres_client.upsert_task.side_effect = fail_on_abc2

    with (
        patch("sop_pipeline.pipeline.JiraClient") as jira_cls,
        patch("sop_pipeline.pipeline.ExcelWriter") as excel,
    ):
        jira_cls.return_value.fetch_tasks.return_value = issues
        sync_jira(etl_service, postgres_client, {})

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
