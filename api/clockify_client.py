from config.settings import settings
import requests
from typing import NamedTuple

class PageResponse(NamedTuple):
    entries: list[dict]
    is_last: bool

class ClockifyClient:
    def __init__(self) -> None:
        self.headers = {"X-Api-Key": settings.API_KEY_CLOCKIFY, "Content-Type": "application/json"}
        self.workspace_id = settings.WORKSPACE_ID
        self.session = requests.Session()
        self.url_base = "https://api.clockify.me/api/v1"

    def _mount_params(self, page: int) -> dict:
        return {"page": page, "page-size": 200}

    def list_users(self) -> list[dict]:
        url = f"{self.url_base}/workspaces/{self.workspace_id}/users"
        resp = self.session.get(url=url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def _fetch_page(self, user_id: str, params: dict) -> PageResponse:
        url = f"{self.url_base}/workspaces/{self.workspace_id}/user/{user_id}/time-entries"
        resp = self.session.get(url=url, headers=self.headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        is_last_dict = resp.headers
        is_last = is_last_dict.get("Last-Page") == "true"
        return PageResponse(entries=data, is_last=is_last)
    
    def fetch_time_entries(self, user_id: str) -> list[dict]:
        lista = []
        page = 1

        while True:
            params = self._mount_params(page=page)
            pag = self._fetch_page(user_id=user_id, params=params)
            lista.extend(pag.entries)
            if pag.is_last:
                break
            page += 1
        
        return lista 