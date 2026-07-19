from models.schemas import Tarefa
from config.settings import settings
import requests

class Notifier:

    @staticmethod
    def _resolve_webhook(area: str | None) -> str:

        if area is None or area not in settings.teams_webhooks:
            return settings.teams_webhooks["sem area"]
        
        return settings.teams_webhooks[area]

    @staticmethod
    def _build_message(task: Tarefa) -> str:
        
        if task.term:
            prazo_texto = task.term.strftime("%d/%m/%Y")
        else:
            prazo_texto = "Sem prazo definido"
        
        if task.days_remaining is not None:
            dias_texto = f"{task.days_remaining} dia(s)" 
        else:
            dias_texto = "Indefinido"

        return (
                f"<b>Alerta de prazo</b><br><br>"
                f"<b>Tarefa:</b> {task.title}<br>"
                f"<b>Prioridade:</b> {task.priority.value}<br>"
                f"<b>Prazo:</b> {prazo_texto}<br>"
                f"<b>Dias restantes:</b> {dias_texto}<br>"
                f"<b>Status:</b> {task.status}<br><br>"
                f"<b>Responsável:</b> "
            )

    @staticmethod
    def send_alert(task: Tarefa) -> None:

        webhook_url = Notifier._resolve_webhook(task.area.lower())
        message = Notifier._build_message(task)
        payload = {"text": message, "email": task.responsible_email}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()

