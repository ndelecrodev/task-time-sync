"""HTTP client for the ClickUp REST API."""

from typing import NamedTuple

import requests

from sop_pipeline.config.settings import settings


class ClickUpPage(NamedTuple):
    """One page of results from the ClickUp list-tasks endpoint.

    Attributes:
        tasks: Raw task dicts returned by the API.
        is_last: Whether this is the final page of the result set.
    """

    tasks: list[dict]
    is_last: bool


class ClickUpClient:
    """Fetches tasks from ClickUp using page-number-based pagination."""

    def __init__(self) -> None:
        """Build the client from the configured ClickUp credentials."""
        self.base_url = "https://api.clickup.com/api/v2"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": settings.CLICKUP_API_TOKEN})

    @staticmethod
    def _build_params(page: int) -> dict:
        """Assemble the query string for a list-tasks request.

        ``include_closed`` is always set so completed tasks are still returned —
        the pipeline needs them for the "concluidas" count. ``subtasks`` is always
        set so subtasks come back as their own task rows alongside regular tasks,
        the same way a Jira "Sub-task" issue type came back from the same JQL
        search as everything else.

        Args:
            page: The 0-based page number to request.

        Returns:
            dict: Query parameters ready for ``requests``.
        """
        return {
            "page": page,
            "include_closed": "true",
            "subtasks": "true",
        }

    def _fetch_page(self, list_id: str, params: dict) -> ClickUpPage:
        """Request a single page of tasks from a list.

        Args:
            list_id: The ClickUp list to fetch tasks from.
            params: Query parameters built by :meth:`_build_params`.

        Returns:
            ClickUpPage: The tasks plus the pagination state.

        Raises:
            requests.HTTPError: If ClickUp answers with a non-2xx status.
        """
        resp = self.session.get(
            url=f"{self.base_url}/list/{list_id}/task",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return ClickUpPage(tasks=data["tasks"], is_last=data["last_page"])

    def fetch_tasks(self, list_id: str) -> list[dict]:
        """Fetch every task in a list, following all pages.

        Args:
            list_id: The ClickUp list to fetch tasks from.

        Returns:
            list[dict]: Raw task dicts, in the order ClickUp returned them.

        Raises:
            requests.HTTPError: If any page request fails.
        """
        tasks = []
        page = 0

        while True:
            params = self._build_params(page)
            result = self._fetch_page(list_id=list_id, params=params)
            tasks.extend(result.tasks)
            if result.is_last:
                break
            page += 1

        return tasks
