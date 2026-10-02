"""Orchestrates a full pipeline run.

One run downloads the workbook from B2, refreshes it with ClickUp and Clockify
data, uploads it back and notifies the team about tasks approaching their
deadline.
"""

from datetime import date
import logging

import requests
import sentry_sdk
from logtail import LogtailHandler
from sqlalchemy.exc import SQLAlchemyError

from sop_pipeline.clients.clickup_client import ClickUpClient
from sop_pipeline.clients.clockify_client import ClockifyClient
from sop_pipeline.config.settings import settings, engine
from sop_pipeline.errors.exceptions import ExcelWriteError
from sop_pipeline.integrations.excel_writer import ExcelWriter
from sop_pipeline.integrations.notifier import Notifier
from sop_pipeline.integrations.storage_client import StorageClient
from sop_pipeline.models.schemas import Task, TimeEntry
from sop_pipeline.services.alert_service import AlertService
from sop_pipeline.services.etl_service import CLICKUP_LIST_MAP, EtlService
from sop_pipeline.integrations.excel_reader import ExcelReader
from sop_pipeline.clients.postgres_client import PostgresClient
from sop_pipeline.services.employee_data_sync_service import EmployeeDataSyncService

logger = logging.getLogger(__name__)


def _filter_allowed_lists(raw_tasks: list[dict]) -> list[dict]:
    """Keep only tasks whose ClickUp list is on the explicit allowlist.

    ``ClickUpClient.fetch_tasks`` returns every task in the Space, across every
    folder and list in it; this filter narrows that down to the lists in
    ``CLICKUP_LIST_MAP``. It runs here, in the orchestration layer, rather than
    inside ``ClickUpClient``, because it is a business rule (which lists count
    for this pipeline) rather than an HTTP/pagination concern — clients in this
    codebase return raw dicts without interpreting anything (see
    architecture.md).

    The filter is by list, not folder: ClickUp reports only a task's immediate
    parent folder, so once a turma folder is split into sub-folders its id no
    longer appears on any task, while list ids survive the reorganization (see
    design-decisions.md). A new list must not silently start flowing into the
    pipeline, and must not silently disappear either: every dropped list is
    logged once per run at WARNING, so adding it to ``CLICKUP_LIST_MAP`` is a
    deliberate decision a human makes.

    Args:
        raw_tasks: Task dicts as returned by ``ClickUpClient.fetch_tasks``.

    Returns:
        list[dict]: Only the tasks whose ``list.id`` is a key of
        ``CLICKUP_LIST_MAP``.
    """
    kept = []
    dropped_lists: dict[str | None, str | None] = {}
    dropped_count = 0
    for task in raw_tasks:
        task_list = task.get("list") or {}
        if task_list.get("id") in CLICKUP_LIST_MAP:
            kept.append(task)
        else:
            dropped_count += 1
            dropped_lists[task_list.get("id")] = task_list.get("name")

    if dropped_count:
        logger.warning(
            "ClickUp: dropped %s tasks from %s lists not in CLICKUP_LIST_MAP: %s",
            dropped_count,
            len(dropped_lists),
            ", ".join(f"{list_id} ({name})" for list_id, name in dropped_lists.items()),
        )

    return kept


def sync_clickup(etl: EtlService, postgres_client: PostgresClient, name_to_id: dict) -> list[Task]:
    """Fetch ClickUp tasks, transform them and write them to the spreadsheet.

    Args:
        etl: The transformation service.
        postgres_client: Persists tasks, details and tags into Postgres.
        name_to_id: Employee canonical name mapped to ``funcionarios.id``.

    Returns:
        list[Task]: The tasks that were persisted, reused later for alerting.
    """
    client = ClickUpClient()
    raw_tasks = client.fetch_tasks(settings.CLICKUP_TEAM_ID, settings.CLICKUP_SPACE_ID)
    raw_tasks = _filter_allowed_lists(raw_tasks)

    tasks = etl.transform_tasks(raw_tasks)
    details = etl.transform_details(raw_tasks)

    # transform_details runs over the raw, unfiltered tasks, so a task
    # discarded by transform_tasks (e.g. an unmapped enum value) can still
    # produce a detail row here. Without this filter that detail row points
    # at a task_id that was never written to Postgres, and the FK on
    # detalhes_tarefa rejects the insert.
    valid_ids = {task.task_id for task in tasks}
    details = [d for d in details if d.task_id in valid_ids]

    ExcelWriter.save_tasks(file_path=settings.TEMP_EXCEL_PATH, tasks=tasks)
    ExcelWriter.save_tags(settings.TEMP_EXCEL_PATH, tasks)
    ExcelWriter.save_details(settings.TEMP_EXCEL_PATH, details)

    for task in tasks:
        # task.assignee is the joined "A, B" string, never a key of name_to_id,
        # so ids are resolved per name. responsavel_id stays the first
        # assignee, the same person assignee_email targets in Teams; names
        # that are not registered employees (the "Unmapped employee" sentinel)
        # get no id and no link.
        assignee_ids = [name_to_id[name] for name in task.assignee_names if name in name_to_id]
        first_assignee_id = name_to_id.get(task.assignee_names[0]) if task.assignee_names else None
        try:
            postgres_client.upsert_task(task=task, responsavel_id=first_assignee_id)
            postgres_client.sync_task_assignees(task_id=task.task_id, funcionario_ids=assignee_ids)
            for tag_name in task.tags:
                postgres_client.upsert_tag_and_link(task_id=task.task_id, tag_name=tag_name)
        except SQLAlchemyError as error:
            logger.error("Failed to write task %s to Postgres: %s", task.task_id, error)
            sentry_sdk.capture_exception(error)

    for detail in details:
        try:
            postgres_client.upsert_task_detail(task_id=detail.task_id, descricao=detail.description)
        except SQLAlchemyError as error:
            logger.error("Failed to write detail %s to Postgres: %s", detail.task_id, error)
            sentry_sdk.capture_exception(error)

    # Uses every in-scope task id ClickUp returned (raw_tasks is already past
    # _filter_allowed_lists), not just the ones that passed validation into
    # `tasks` — a discarded task (bad enum value, for example) is still present
    # and active in ClickUp, so it must not be archived just because our own
    # parsing rejected it.
    # The same set drives unarchiving, so the two stay symmetric: a task is
    # archived exactly when it is missing from this set, and unarchived when it
    # is in it, whether or not it passed validation.
    all_ids_from_clickup = {task["id"] for task in raw_tasks}
    if not all_ids_from_clickup:
        # An empty in-scope fetch almost always means a configuration problem
        # (wrong Space, CLICKUP_LIST_MAP out of date, a ClickUp outage), not
        # that every task was removed. Archiving now would archive everything.
        logger.warning(
            "ClickUp: no in-scope tasks returned, skipping archiving for this run; "
            "check CLICKUP_SPACE_ID and CLICKUP_LIST_MAP"
        )
    else:
        postgres_unarchived = postgres_client.unarchive_seen_tasks(all_ids_from_clickup)
        postgres_client.archive_missing_tasks(all_ids_from_clickup)
        excel_unarchived = ExcelWriter.unmark_archived_tasks(
            settings.TEMP_EXCEL_PATH, all_ids_from_clickup
        )
        ExcelWriter.mark_archived_tasks(
            settings.TEMP_EXCEL_PATH, postgres_client.get_archived_tasks()
        )
        logger.info(
            "ClickUp: %s tasks unarchived in Postgres, %s in Excel",
            postgres_unarchived,
            excel_unarchived,
        )

    # A discarded count well above zero means tasks are vanishing from the
    # report — usually a priority ClickUp sent that isn't in the enum.
    logger.info(
        "ClickUp: %s tasks fetched, %s tasks written, %s discarded",
        len(raw_tasks),
        len(tasks),
        len(raw_tasks) - len(tasks),
    )
    return tasks


def sync_clockify(
    etl: EtlService, postgres_client: PostgresClient, name_to_id: dict
) -> list[TimeEntry]:
    """Fetch every user's time entries from Clockify and write them out.

    Args:
        etl: The transformation service.
        postgres_client: Persists time entries into Postgres.
        name_to_id: Employee canonical name mapped to ``funcionarios.id``.

    Returns:
        list[TimeEntry]: The time entries that were persisted.
    """
    client = ClockifyClient()
    users = client.list_users()

    # Built once and reused for every user; rebuilding it per user made the sync
    # quadratic in the number of workspace members.
    email_by_user_id = etl.build_email_index(users)

    time_entries: list[TimeEntry] = []
    for user in users:
        raw_entries = client.fetch_time_entries(user["id"])
        time_entries.extend(etl.transform_time_entries(raw_entries, email_by_user_id))

    ExcelWriter.save_hours(settings.TEMP_EXCEL_PATH, time_entries)

    for time_entry in time_entries:
        try:
            postgres_client.upsert_time_entry(
                entry_id=time_entry.entry_id,
                funcionario_id=name_to_id.get(time_entry.employee),
                data=time_entry.entry_date,
                horas=time_entry.hours,
            )
        except SQLAlchemyError as error:
            logger.error(
                "Failed to write time entry %s to Postgres: %s", time_entry.entry_id, error
            )
            sentry_sdk.capture_exception(error)

    logger.info("Clockify: %s time entries written", len(time_entries))
    return time_entries


def process_alerts(tasks: list[Task]) -> None:
    """Decide which tasks need a deadline alert and send each notification.

    Args:
        tasks: The tasks to evaluate.
    """
    tasks_to_alert = AlertService.tasks_to_alert(tasks)

    for task in tasks_to_alert:
        Notifier.send_alert(task)

    logger.info("Alerts: %s notifications sent", len(tasks_to_alert))


def _configure_observability() -> None:
    """Wire up Sentry for exceptions and Better Stack for log shipping."""
    sentry_sdk.init(dsn=settings.SENTRY_DSN)

    betterstack_handler = LogtailHandler(
        source_token=settings.BETTERSTACK_SOURCE_TOKEN,
        host=settings.BETTERSTACK_INGESTING_HOST,
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), betterstack_handler],
    )


def run() -> None:
    """Execute one full pipeline run.

    The three sync steps are isolated from each other: a ClickUp outage must not
    stop the Clockify hours from being collected, so each step logs and reports
    its own failure instead of aborting the run.
    """
    _configure_observability()

    storage = StorageClient()
    storage.download_file(
        local_destination=settings.TEMP_EXCEL_PATH, cloud_name=settings.EXCEL_CLOUD_NAME
    )

    postgres_client = PostgresClient(engine)
    employee_sync = EmployeeDataSyncService(ExcelReader(), postgres_client)
    employee_sync.sync(settings.TEMP_EXCEL_PATH)

    name_to_id = {
        employee.canonical_name: employee.id for employee in postgres_client.get_employees()
    }
    employee_sync.sync_areas(settings.TEMP_EXCEL_PATH, name_to_id)

    etl = EtlService()

    # None means "the ClickUp sync did not complete", which is different from
    # "ClickUp returned no tasks". Without the distinction a failed sync would
    # silently run the alert step against an empty list and look like a clean run.
    tasks: list[Task] | None = None
    try:
        tasks = sync_clickup(etl, postgres_client, name_to_id)
    except Exception as error:  # pylint: disable=broad-except
        logger.error("ClickUp synchronisation failed: %s", error)
        sentry_sdk.capture_exception(error)

    try:
        sync_clockify(etl, postgres_client, name_to_id)
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Clockify synchronisation failed: %s", error)
        sentry_sdk.capture_exception(error)

    if tasks is None:
        logger.warning("Skipping alerts: the ClickUp synchronisation did not complete")
    else:
        total_tarefas = len(tasks)
        concluidas = 0
        for i in tasks:
            if i.completion_date is not None:
                concluidas += 1
        # Own try/except, isolated from the process_alerts one below: a
        # snapshot-save failure must not block alert delivery, and vice versa.
        try:
            ExcelWriter.save_progress_snapshot(
                settings.TEMP_EXCEL_PATH, date.today(), total_tarefas, concluidas
            )
        except ExcelWriteError as error:
            logger.error("Failed to save progress snapshot: %s", error)
            sentry_sdk.capture_exception(error)
        try:
            process_alerts(tasks)
        except Exception as error:  # pylint: disable=broad-except
            logger.error("Alert processing failed: %s", error)
            sentry_sdk.capture_exception(error)

    storage.upload_file(local_source=settings.TEMP_EXCEL_PATH, cloud_name=settings.EXCEL_CLOUD_NAME)

    # The heartbeat stays outside every try/except on purpose: it must only fire
    # once the workbook has actually reached the bucket. If the upload raised,
    # this line is never reached and Better Stack correctly reports a missed run.
    requests.get(settings.BETTERSTACK_HEARTBEAT_URL, timeout=10)
    logger.info("Pipeline finished, spreadsheet updated in storage")
