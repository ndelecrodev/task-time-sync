"""Sends deadline alerts to the Microsoft Teams webhooks."""

import requests

from sop_pipeline.config.settings import settings
from sop_pipeline.errors.exceptions import NotificationError
from sop_pipeline.models.schemas import Task

FALLBACK_AREA = "no area"


class Notifier:
    """Formats and delivers a deadline alert for a single task.

    The message body is written in Portuguese on purpose: it is read by the team
    in the Teams channel, so it is user-facing copy rather than code.
    """

    @staticmethod
    def _resolve_webhook(area: str | None) -> str:
        """Pick the webhook that serves a given area.

        Args:
            area: Lowercase area name coming from the Jira custom field.

        Returns:
            str: The area's webhook URL, or the fallback webhook when the area is
            unknown or absent.
        """
        if area is None or area not in settings.teams_webhooks:
            return settings.teams_webhooks[FALLBACK_AREA]

        return settings.teams_webhooks[area]

    @staticmethod
    def _build_message(task: Task) -> str:
        """Render the HTML body of the alert.

        The days-remaining line switches label and wording depending on the
        task's state: an overdue task reads "Tarefa atrasada há N dia(s)"
        instead of a negative count, an on-time task reads "Dias restantes: N
        dia(s)", and a task with no due date reads "Dias restantes: Indefinido".

        Args:
            task: The task the alert is about.

        Returns:
            str: An HTML snippet accepted by the Teams/Power Automate workflow.
        """
        if task.due_date:
            deadline_text = task.due_date.strftime("%d/%m/%Y")
        else:
            deadline_text = "Sem prazo definido"

        if task.days_remaining is not None:

            if task.days_remaining < 0:
                days_label = "Tarefa atrasada há"
                days_text = f"{abs(task.days_remaining)} dia(s)"
            else:
                days_label = "Dias restantes"
                days_text = f"{task.days_remaining} dia(s)"
        else:
            days_label = "Dias restantes"
            days_text = "Indefinido"

        return (
            "<b>Alerta de prazo</b><br><br>"
            f"<b>Tarefa:</b> {task.title}<br>"
            f"<b>Prioridade:</b> {task.priority.value}<br>"
            f"<b>Prazo:</b> {deadline_text}<br>"
            f"<b>{days_label}:</b> {days_text}<br>"
            f"<b>Status:</b> {task.status}<br><br>"
            "<b>Responsável:</b> "
        )

    @staticmethod
    def send_alert(task: Task) -> None:
        """Post a deadline alert to the webhook of the task's area.

        Args:
            task: The task the alert is about.

        Raises:
            NotificationError: If the webhook request fails or is rejected.
        """
        # `area` is optional on the model, so it must be guarded here — passing
        # None straight through is fine, `_resolve_webhook` falls back for it.
        area = task.area.lower() if task.area else None
        webhook_url = Notifier._resolve_webhook(area)
        message = Notifier._build_message(task)
        email = task.assignee_email or ""
        payload = {"text": message, "email": email}
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as error:
            raise NotificationError(
                f"Failed to send alert for task {task.task_id}: {error}"
            ) from error
