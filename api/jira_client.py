from typing import NamedTuple
from config.settings import settings
import requests

class PaginaResposta(NamedTuple):
        issues: list[dict]
        is_last: bool
        next_token: str | None

class JiraClient:
    def __init__(self) -> None:
        self.url_base = settings.URL_JIRA
        self.auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        self.session = requests.Session()
    
    def _montar_parametro(self, jql: str, token:str | None=None) -> dict:
        fields = "summary,assignee,priority,status,issuetype,creator,created,updated,duedate,resolutiondate,labels,description"
        params = {
            "jql":jql,
            "maxResults": 100,
            "fields": fields
        }
        if token is not None:
            params["nextPageToken"] = token
        return params

    def _buscar_pagina(self, params: dict) -> PaginaResposta:
        resp = self.session.get(url=f"{self.url_base}/rest/api/3/search/jql", auth=self.auth, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return PaginaResposta(
        issues=data["issues"], 
        is_last=data["isLast"],
        next_token=data.get("nextPageToken")
        )

    def buscar_tarefas(self, jql: str) -> list[dict]:
        cest = []
        mark_page = None

        while True:
            params = self._montar_parametro(jql, mark_page)
            pag = self._buscar_pagina(params=params)
            cest.extend(pag.issues)
            if pag.is_last:
                break
            mark_page = pag.next_token
            
        return cest