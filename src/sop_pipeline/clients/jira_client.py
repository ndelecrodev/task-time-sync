"""HTTP client for the Jira Cloud REST API."""

from typing import NamedTuple

import requests

from sop_pipeline.config.settings import settings


class JiraPage(NamedTuple):
    """One page of results from the Jira search endpoint.

    Attributes:
        issues: Raw issue dicts returned by the API.
        is_last: Whether this is the final page of the result set.
        next_token: Cursor to request the following page, when there is one.
    """

    issues: list[dict]
    is_last: bool
    next_token: str | None


class JiraClient:
    """Fetches issues from Jira using token-based pagination."""

    def __init__(self) -> None:
        """Build the client from the configured Jira credentials."""
        self.base_url = settings.JIRA_URL
        self.auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        self.jira_customfield_area = settings.JIRA_CUSTOMFIELD_AREA
        self.session = requests.Session()

    def _build_params(self, jql: str, token: str | None = None) -> dict:
        """Assemble the query string for a search request.

        Only the fields the ETL actually consumes are requested, which keeps the
        payload small. The area custom field ID is configurable because it
        differs per Jira instance.

        Args:
            jql: The JQL query selecting which issues to fetch.
            token: Pagination cursor; omitted on the first request.

        Returns:
            dict: Query parameters ready for ``requests``.
        """
        fields = (
            "summary,assignee,priority,status,issuetype,creator,created,updated,"
            f"duedate,resolutiondate,labels,description,{self.jira_customfield_area}"
        )
        params = {"jql": jql, "maxResults": 100, "fields": fields}
        if token is not None:
            params["nextPageToken"] = token
        return params

    def _fetch_page(self, params: dict) -> JiraPage:
        """Request a single page of search results.

        Args:
            params: Query parameters built by :meth:`_build_params`.

        Returns:
            JiraPage: The issues plus the pagination state.

        Raises:
            requests.HTTPError: If Jira answers with a non-2xx status.
        """
        resp = self.session.get(
            url=f"{self.base_url}/rest/api/3/search/jql",
            auth=self.auth,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return JiraPage(
            issues=data["issues"],
            is_last=data["isLast"],
            next_token=data.get("nextPageToken"),
        )

    def fetch_tasks(self, jql: str) -> list[dict]:
        """Fetch every issue matching a JQL query, following all pages.

        Args:
            jql: The JQL query selecting which issues to fetch.

        Returns:
            list[dict]: Raw issue dicts, in the order Jira returned them.

        Raises:
            requests.HTTPError: If any page request fails.
        """
        issues = []
        page_token = None

        while True:
            params = self._build_params(jql, page_token)
            page = self._fetch_page(params=params)
            issues.extend(page.issues)
            if page.is_last:
                break
            page_token = page.next_token

        return issues
