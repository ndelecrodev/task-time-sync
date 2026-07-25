"""Orchestrates a full pipeline run.

One run downloads the workbook from B2, refreshes it with Jira and Clockify data,
uploads it back and notifies the team about tasks approaching their deadline.
"""

import logging

import requests
import sentry_sdk
from logtail import LogtailHandler
from sqlalchemy.exc import SQLAlchemyError

from sop_pipeline.clients.clockify_client import ClockifyClient
from sop_pipeline.clients.jira_client import JiraClient
from sop_pipeline.config.settings import settings, engine
from sop_pipeline.integrations.excel_writer import ExcelWriter
from sop_pipeline.integrations.notifier import Notifier
from sop_pipeline.integrations.storage_client import StorageClient
from sop_pipeline.models.schemas import Task, TimeEntry
from sop_pipeline.services.alert_service import AlertService
from sop_pipeline.services.etl_service import EtlService
from sop_pipeline.integrations.excel_reader import ExcelReader
from sop_pipeline.clients.postgres_client import PostgresClient
from sop_pipeline.services.employee_data_sync_service import EmployeeDataSyncService

logger = logging.getLogger(__name__)


def sync_jira(etl: EtlService, postgres_client: PostgresClient, name_to_id: dict) -> list[Task]:
    """Fetch Jira issues, transform them and write them to the spreadsheet.

    Args:
        etl: The transformation service.
        postgres_client: Persists tasks, details and tags into Postgres.
        name_to_id: Employee canonical name mapped to ``funcionarios.id``.

    Returns:
        list[Task]: The tasks that were persisted, reused later for alerting.
    """
    client = JiraClient()
    raw_issues = client.fetch_tasks(settings.JIRA_JQL)

    tasks = etl.transform_tasks(raw_issues)
    details = etl.transform_details(raw_issues)

    # transform_details runs over the raw, unfiltered issues, so an issue
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
        try:
            postgres_client.upsert_task(task=task, responsavel_id=name_to_id.get(task.assignee))
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

    # Uses every issue key the Jira query returned, not just the ones that
    # passed validation into `tasks` — a discarded issue (bad enum value,
    # for example) is still present and active in Jira, so it must not be
    # archived just because our own parsing rejected it.
    all_ids_from_jira = {issue["key"] for issue in raw_issues}
    postgres_client.archive_missing_tasks(all_ids_from_jira)

    # A discarded count well above zero means issues are vanishing from the
    # report — usually a Jira priority or issue type missing from the enums.
    logger.info(
        "Jira: %s issues fetched, %s tasks written, %s discarded",
        len(raw_issues),
        len(tasks),
        len(raw_issues) - len(tasks),
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

    The three sync steps are isolated from each other: a Jira outage must not
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

    # None means "the Jira sync did not complete", which is different from "Jira
    # returned no tasks". Without the distinction a failed sync would silently
    # run the alert step against an empty list and look like a clean run.
    tasks: list[Task] | None = None
    try:
        tasks = sync_jira(etl, postgres_client, name_to_id)
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Jira synchronisation failed: %s", error)
        sentry_sdk.capture_exception(error)

    try:
        sync_clockify(etl, postgres_client, name_to_id)
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Clockify synchronisation failed: %s", error)
        sentry_sdk.capture_exception(error)

    if tasks is None:
        logger.warning("Skipping alerts: the Jira synchronisation did not complete")
    else:
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
