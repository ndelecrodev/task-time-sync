from datetime import date
from datetime import datetime
from pydantic import ValidationError
from models.schemas import Tarefa, DetalheTarefa, RegistroHoras
from config.settings import settings
from logging import getLogger
from isodate import parse_duration
from zoneinfo import ZoneInfo

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
                    responsible_email = None
                else:
                    responsible = fields["assignee"].get("displayName")
                    responsible_email = fields["assignee"].get("emailAddress")

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
                
                tarefa = Tarefa(
                id=id_task, title=title,
                responsible=responsible, priority=prioridade,      
                status=status, area=area, creation_date=data_criacao, 
                term=prazo, completion_date=data_conclusao, type=tipo,
                creator=criador, update_date=data_atualizacao,responsible_email=responsible_email,tags=etiquetas
                )

                tarefas.append(tarefa)

            except (ValidationError, KeyError) as e:
                logger.warning(f"Notice: there was an error: {e} and issue key:{issue['key']}")
                continue

        return tarefas

    @staticmethod
    def transformar_detalhes(brute_issues: list[dict]) -> list[DetalheTarefa]:
        detalhes = []
        for issue in brute_issues:
            try:
                id_task = issue["key"]
                brute_description = issue["fields"].get("description")
                if brute_description is None:
                    descricao = None
                else:
                    descricao = EtlService._extrair_detalhes(brute_description).strip()

                d_tarefa = DetalheTarefa(id_tarefa=id_task, descricao=descricao)
                detalhes.append(d_tarefa)
            except (ValidationError, KeyError) as e:
                logger.warning(f"Detalhe da tarefa {issue.get('key', '???')} inválido, pulando: {e}")
        return detalhes

        
    @staticmethod
    def _extrair_detalhes(node: dict) -> str:
        text = ""
        if "text" in node.keys():
            text += node.get("text")
        elif "content" in node.keys():
            for i in node["content"]:
                if i.get("type") == "paragraph" : 
                    text += EtlService._extrair_detalhes(i) + "\n"
                else: 
                    text += EtlService._extrair_detalhes(i)
        else:
            text += "\n"    
        return text

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

    @staticmethod
    def _parse_duration(duration_iso: str) -> float:
        td = parse_duration(duration_iso)
        return td.total_seconds() / 3600
    
    @staticmethod
    def _parse_utc_to_local_date(data: str) -> date:
        string_convertida = datetime.fromisoformat(data)
        fuso_brazil = ZoneInfo("America/Sao_Paulo")
        for_zoneinfo = string_convertida.astimezone(fuso_brazil)
        return for_zoneinfo.date()
    
    @staticmethod
    def transformar_horas(entradas_brutas: list[dict], usuarios: list[dict]) -> list[RegistroHoras]:
        dic = {}
        lista = []
        for i in usuarios:
            dic[i.get("id")] = i.get("email")
        for entrada in entradas_brutas:
            try:
                user_id = entrada.get("userId", "Unknown")
                email = dic.get(user_id, "email_desconhecido@desconhecido.com")
                brute_duration = entrada["timeInterval"]["duration"]
                if brute_duration is None:
                    continue
                duration = EtlService._parse_duration(brute_duration)
                date_start = EtlService._parse_utc_to_local_date(entrada["timeInterval"]["start"])
                reg = RegistroHoras(id=entrada["id"], funcionario=email, data=date_start, horas=duration)
                lista.append(reg)
            except (ValidationError, KeyError) as error:
                logger.warning(f"Erro ao transformar entrada {entrada.get('id', '???')}: {error}")        
        
        return lista