"""HTTP client for the Clockify REST API."""

from typing import NamedTuple

import requests

from sop_pipeline.config.settings import settings


class ClockifyPage(NamedTuple):
    """One page of time entries from Clockify.

    Attributes:
        entries: Raw time-entry dicts returned by the API.
        is_last: Whether this is the final page of the result set.
    """

    entries: list[dict]
    is_last: bool


class ClockifyClient:
    """Fetches workspace users and their time entries from Clockify."""

    def __init__(self) -> None:
        """Build the client from the configured Clockify credentials."""
        self.headers = {
            "X-Api-Key": settings.API_KEY_CLOCKIFY,
            "Content-Type": "application/json",
        }
        self.workspace_id = settings.WORKSPACE_ID
        self.session = requests.Session()
        self.base_url = "https://api.clockify.me/api/v1"

    @staticmethod
    def _build_params(page: int) -> dict:
        """Build the pagination query string for a time-entry request.

        Args:
            page: 1-based page number.

        Returns:
            dict: Query parameters ready for ``requests``.
        """
        return {"page": page, "page-size": 200}

    def list_users(self) -> list[dict]:
        """List every user in the configured workspace.

        Returns:
            list[dict]: Raw user dicts, each carrying at least ``id`` and ``email``.

        Raises:
            requests.HTTPError: If Clockify answers with a non-2xx status.
        """
        url = f"{self.base_url}/workspaces/{self.workspace_id}/users"
        resp = self.session.get(url=url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _fetch_page(self, user_id: str, params: dict) -> ClockifyPage:
        """Request a single page of one user's time entries.

        Args:
            user_id: Clockify user ID.
            params: Pagination parameters built by :meth:`_build_params`.

        Returns:
            ClockifyPage: The entries plus the pagination state.

        Raises:
            requests.HTTPError: If Clockify answers with a non-2xx status.
        """
        url = f"{self.base_url}/workspaces/{self.workspace_id}/user/{user_id}/time-entries"
        resp = self.session.get(url=url, headers=self.headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Clockify signals the end of the result set through a response header,
        # not through the JSON body.
        is_last = resp.headers.get("Last-Page") == "true"
        return ClockifyPage(entries=data, is_last=is_last)

    def fetch_time_entries(self, user_id: str) -> list[dict]:
        """Fetch every time entry of one user, following all pages.

        Args:
            user_id: Clockify user ID.

        Returns:
            list[dict]: Raw time-entry dicts.

        Raises:
            requests.HTTPError: If any page request fails.
        """
        entries = []
        page = 1

        while True:
            params = self._build_params(page=page)
            current_page = self._fetch_page(user_id=user_id, params=params)
            entries.extend(current_page.entries)
            if current_page.is_last:
                break
            page += 1

        return entries
