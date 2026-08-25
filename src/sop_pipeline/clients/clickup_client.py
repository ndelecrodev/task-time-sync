"""HTTP client for the ClickUp REST API."""

from typing import NamedTuple

import requests

from sop_pipeline.config.settings import settings


class ClickUpPage(NamedTuple):
    """One page of results from the ClickUp team-tasks endpoint.

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
    def _build_params(space_id: str, page: int) -> dict:
        """Assemble the query string for a team-tasks request.

        Scoping is done by ``space_ids[]`` rather than a list ID, since tasks are
        now fetched for a whole Space and narrowed down to specific folders
        ("turmas") afterwards, not for a single ClickUp List.
        ``include_closed`` is always set so completed tasks are still returned —
        the pipeline needs them for the "concluidas" count. ``subtasks`` is always
        set so subtasks come back as their own task rows alongside regular tasks,
        the same way a Jira "Sub-task" issue type came back from the same JQL
        search as everything else.

        Args:
            space_id: The ClickUp Space to scope the search to.
            page: The 0-based page number to request.

        Returns:
            dict: Query parameters ready for ``requests``.
        """
        return {
            "page": page,
            "space_ids[]": space_id,
            "include_closed": "true",
            "subtasks": "true",
        }

    def _fetch_page(self, team_id: str, params: dict) -> ClickUpPage:
        """Request a single page of tasks for a team (workspace).

        Args:
            team_id: The ClickUp Team (Workspace) to fetch tasks from.
            params: Query parameters built by :meth:`_build_params`.

        Returns:
            ClickUpPage: The tasks plus the pagination state.

        Raises:
            requests.HTTPError: If ClickUp answers with a non-2xx status.
        """
        resp = self.session.get(
            url=f"{self.base_url}/team/{team_id}/task",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return ClickUpPage(tasks=data["tasks"], is_last=data["last_page"])

    def fetch_tasks(self, team_id: str, space_id: str) -> list[dict]:
        """Fetch every task in a Space, following all pages.

        Tasks come back from every folder (and folderless list) in the Space;
        narrowing that down to the folders that count as "turmas" is the
        caller's job (see ``pipeline._filter_allowed_folders``), not this
        client's — a client stays a thin HTTP wrapper that returns raw dicts
        without interpreting anything.

        Args:
            team_id: The ClickUp Team (Workspace) to fetch tasks from.
            space_id: The ClickUp Space to scope the search to.

        Returns:
            list[dict]: Raw task dicts, in the order ClickUp returned them.

        Raises:
            requests.HTTPError: If any page request fails.
        """
        tasks = []
        page = 0

        while True:
            params = self._build_params(space_id, page)
            result = self._fetch_page(team_id=team_id, params=params)
            tasks.extend(result.tasks)
            if result.is_last:
                break
            page += 1

        return tasks
