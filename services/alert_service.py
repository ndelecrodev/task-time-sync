from models.schemas import Tarefa
from config.settings import settings

class AlertService:

    @staticmethod
    def tarefas_para_alertar(tarefas: list[Tarefa]) -> list[Tarefa]:
        resultados = []
        for task in tarefas:
            if task.completion_date is not None:
                continue
            
            if task.days_remaining is None:
                continue

            if task.priority.value in settings.PRIORIDADES_ALTAS and task.days_remaining <= settings.ALERT_DAYS_HIGH:
                resultados.append(task)
            elif task.priority.value in settings.PRIORIDADES_BAIXAS and task.days_remaining <= settings.ALERT_DAYS_LOW:
                resultados.append(task)
        
        return resultados