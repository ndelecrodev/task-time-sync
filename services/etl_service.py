from datetime import date
from datetime import datetime
from pydantic import ValidationError
from models.schemas import Tarefa, DetalheTarefa
from config.settings import settings
from logging import getLogger

logger = getLogger(__name__)

class EtlService:
    def __init__(self) -> None:
        self.jira_customfield_area = settings.JIRA_CUSTOMFIELD_AREA

    def transformar_tarefas(self, list_tarefa: list) -> list[Tarefa]:
        tarefas = []
        for issue in list_tarefa:
            try: 
                fields = issue["fields"]
                id_task = issue["key"]
                title = fields.get("summary", "No title")
                
                if fields["assignee"] is None:
                    responsible = "There is no one responsible."
                else:
                    responsible = fields["assignee"].get("displayName")

                prioridade = fields["priority"].get("name")
                status = fields["status"].get("name")
                data_criacao = self._parse_datetime_para_date(field=fields["created"])
                tipo = fields["issuetype"].get("name")
                criador = fields["creator"].get("displayName")
                prazo = self._parse_date(date_parse=fields["duedate"])   
                data_atualizacao = self._parse_datetime_para_date(field=fields["updated"])               
                etiquetas = fields.get("labels",[])
                data_conclusao = self._parse_datetime_para_date(fields["resolutiondate"])

                if fields[self.jira_customfield_area] is None:
                    area = "There is no one area."
                else:
                    area = fields[self.jira_customfield_area].get("value")
                
                tarefa = Tarefa(id=id_task, title=title, responsible=responsible, prioridade=prioridade, status=status,area=area, data_criacao=data_criacao, prazo=prazo, data_conclusao=data_conclusao, tipo=tipo, criador=criador, data_atualizacao=data_atualizacao, etiquetas=etiquetas)

                tarefas.append(tarefa)

            except (ValidationError, KeyError) as e:
                logger.warning(f"Notice: there was an erroe: {e} and issue key:{issue['key']}")
                continue

        return tarefas

    @staticmethod
    def transformar_detalhes(brute_issues: list[dict]) -> list[DetalheTarefa]:
        pass 
    
    @staticmethod
    def _parse_date(date_parse: str | None) -> date | None:
        if date_parse is None:
            return None
        return date.fromisoformat(date_parse)

    @staticmethod
    def _parse_datetime_para_date(field:str | None) -> date | None:
        if field is None:
            return None
        datetime_field = datetime.fromisoformat(field)
        return datetime_field.date()