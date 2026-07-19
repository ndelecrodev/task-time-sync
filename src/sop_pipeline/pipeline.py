"""Orchestrates a full pipeline run.

One run downloads the workbook from B2, refreshes it with Jira and Clockify data,
uploads it back and notifies the team about tasks approaching their deadline.
"""

import logging

import requests
import sentry_sdk
from logtail import LogtailHandler

from sop_pipeline.clients.clockify_client import ClockifyClient
from sop_pipeline.clients.jira_client import JiraClient
from sop_pipeline.config.settings import settings
from sop_pipeline.integrations.excel_writer import ExcelWriter
from sop_pipeline.integrations.notifier import Notifier
from sop_pipeline.integrations.storage_client import StorageClient
from sop_pipeline.models.schemas import Task, TimeEntry
from sop_pipeline.services.alert_service import AlertService
from sop_pipeline.services.etl_service import EtlService

logger = logging.getLogger(__name__)


def sync_jira(etl: EtlService) -> list[Task]:
    """Fetch Jira issues, transform them and write them to the spreadsheet.

    Args:
        etl: The transformation service.

    Returns:
        list[Task]: The tasks that were persisted, reused later for alerting.
    """
    client = JiraClient()
    raw_issues = client.fetch_tasks(settings.JIRA_JQL)

    tasks = etl.transform_tasks(raw_issues)
    details = etl.transform_details(raw_issues)

    ExcelWriter.save_tasks(file_path=settings.TEMP_EXCEL_PATH, tasks=tasks)
    ExcelWriter.save_tags(settings.TEMP_EXCEL_PATH, tasks)
    ExcelWriter.save_details(settings.TEMP_EXCEL_PATH, details)

    # A discarded count well above zero means issues are vanishing from the
    # report — usually a Jira priority or issue type missing from the enums.
    logger.info(
        "Jira: %s issues fetched, %s tasks written, %s discarded",
        len(raw_issues),
        len(tasks),
        len(raw_issues) - len(tasks),
    )
    return tasks


def sync_clockify(etl: EtlService) -> list[TimeEntry]:
    """Fetch every user's time entries from Clockify and write them out.

    Args:
        etl: The transformation service.

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

    etl = EtlService()

    # None means "the Jira sync did not complete", which is different from "Jira
    # returned no tasks". Without the distinction a failed sync would silently
    # run the alert step against an empty list and look like a clean run.
    tasks: list[Task] | None = None
    try:
        tasks = sync_jira(etl)
    except Exception as error:  # pylint: disable=broad-except
        logger.error("Jira synchronisation failed: %s", error)
        sentry_sdk.capture_exception(error)

    try:
        sync_clockify(etl)
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
