import logging
import sentry_sdk
import requests
from logtail import LogtailHandler
from api.clockify_client import ClockifyClient
from api.jira_client import JiraClient
from config.settings import settings
from integrations.notifier import Notifier
from integrations.storage_client import StorageClient
from models.schemas import RegistroHoras, Tarefa
from services.alert_service import AlertService
from services.etl_service import EtlService
from services.excel_writer import ExcelWriter


logger = logging.getLogger(__name__)


def sincronizar_jira(etl: EtlService) -> list[Tarefa]:
    
    """Busca tarefas no Jira, transforma e grava na planilha (tarefas, etiquetas, detalhes)."""

    client = JiraClient()
    issues_brutas = client.buscar_tarefas(settings.JIRA_JQL)

    tarefas = etl.transformar_tarefas(issues_brutas)
    detalhes = etl.transformar_detalhes(issues_brutas)

    ExcelWriter.save_tasks(way_file=settings.TEMP_EXCEL_PATH, tasks=tarefas)
    ExcelWriter.save_tags(settings.TEMP_EXCEL_PATH, tarefas)
    ExcelWriter.save_details(settings.TEMP_EXCEL_PATH, detalhes)

    logger.info(f"Jira: {len(issues_brutas)} issues buscadas, {len(tarefas)} tarefas gravadas")
    return tarefas


def sincronizar_clockify(etl: EtlService) -> list[RegistroHoras]:
    
    """Busca horas de todos os usuários no Clockify, transforma e grava na planilha."""

    client = ClockifyClient()
    usuarios = client.list_users()

    registros: list[RegistroHoras] = []
    for usuario in usuarios:
        entradas_brutas = client.fetch_time_entries(usuario["id"])
        registros.extend(etl.transformar_horas(entradas_brutas, usuarios))

    ExcelWriter.save_hours(settings.TEMP_EXCEL_PATH, registros)

    logger.info(f"Clockify: {len(registros)} registros de horas gravados")
    return registros


def processar_alertas(tarefas: list[Tarefa]) -> None:
    
    """Decide quais tarefas precisam de alerta e envia a notificação de cada uma."""

    tarefas_para_alertar = AlertService.tarefas_para_alertar(tarefas)

    for task in tarefas_para_alertar:
        Notifier.send_alert(task)

    logger.info(f"Alertas: {len(tarefas_para_alertar)} notificações enviadas")


def main() -> None:

    sentry_sdk.init(dsn=settings.SENTRY_DSN)
    
    handler_betterstack = LogtailHandler(
        source_token=settings.BETTERSTACK_SOURCE_TOKEN,
        host=settings.BETTERSTACK_INGESTING_HOST,
    )    
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[logging.StreamHandler(), handler_betterstack])

    storage = StorageClient()
    storage.download_file(destino_local=settings.TEMP_EXCEL_PATH, name_cloud=settings.EXCEL_CLOUD_NAME)

    etl = EtlService()

    tarefas: list[Tarefa] = []
    try:
        tarefas = sincronizar_jira(etl)
    except Exception as e:
        logger.error(f"Falha na sincronização do Jira: {e}")
        sentry_sdk.capture_exception(e)

    try:
        sincronizar_clockify(etl)
    except Exception as e:
        logger.error(f"Falha na sincronização do Clockify: {e}")
        sentry_sdk.capture_exception(e)
    try:
        processar_alertas(tarefas)
    except Exception as e:
        logger.error(f"Falha ao processar alertas: {e}")
        sentry_sdk.capture_exception(e)

    storage.upload_file(origem_local=settings.TEMP_EXCEL_PATH, name_cloud=settings.EXCEL_CLOUD_NAME)
    requests.get(settings.BETTERSTACK_HEARTBEAT_URL, timeout=10)
    logger.info("Pipeline finalizado, planilha atualizada no storage")


if __name__ == "__main__":
    main()