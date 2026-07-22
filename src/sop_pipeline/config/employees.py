"""Employee identity mapping configuration.

Maps employees across Jira and Clockify by normalizing their identifiers
(email addresses) to canonical names for use as join keys in the Excel sheet.
"""

from logging import getLogger

from pydantic import BaseModel, EmailStr, Field

logger = getLogger(__name__)


class EmployeeMapping(BaseModel):
    """A single employee with their identifiers across Jira and Clockify.

    Attributes:
        canonical_name: The normalized name used as the join key in the report.
        jira_email: The email address that appears in Jira assignee records.
        clockify_email: The email address that appears in Clockify time entries.
    """
    canonical_name: str = Field(..., description="Normalized name for the report")
    jira_email: EmailStr = Field(..., description="Email in Jira")
    clockify_email: EmailStr = Field(..., description="Email in Clockify")

    def __hash__(self) -> int:
        """Make hashable for deduplication."""
        return hash((self.canonical_name, self.jira_email, self.clockify_email))


class EmployeeRegistry:
    """Central registry of employee identity mappings.

    Validates the configuration on initialization, ensuring no duplicate email
    addresses are mapped to different canonical names (which would be a
    configuration error).
    """

    def __init__(self, employees: list[EmployeeMapping]) -> None:
        """Initialize the registry and validate consistency.

        Args:
            employees: List of employee mappings.

        Raises:
            ValueError: If any email address is mapped to multiple canonical names.
        """
        self.employees = employees
        self._by_jira_email: dict[str, str] = {}
        self._by_clockify_email: dict[str, str] = {}
        self._by_canonical_name: dict[str, EmployeeMapping] = {}

        # Build indices and detect conflicts
        for employee in employees:
            jira_lower = employee.jira_email.lower()
            clockify_lower = employee.clockify_email.lower()

            # Check for Jira email conflicts
            if jira_lower in self._by_jira_email:
                existing = self._by_jira_email[jira_lower]
                if existing != employee.canonical_name:
                    raise ValueError(
                        f"Jira email {employee.jira_email} mapped to "
                        f"both '{existing}' and '{employee.canonical_name}' "
                        f"(duplicate email in config)"
                    )
            self._by_jira_email[jira_lower] = employee.canonical_name

            # Check for Clockify email conflicts
            if clockify_lower in self._by_clockify_email:
                existing = self._by_clockify_email[clockify_lower]
                if existing != employee.canonical_name:
                    raise ValueError(
                        f"Clockify email {employee.clockify_email} mapped to "
                        f"both '{existing}' and '{employee.canonical_name}' "
                        f"(duplicate email in config)"
                    )
            self._by_clockify_email[clockify_lower] = employee.canonical_name

            # Index by canonical name
            self._by_canonical_name[employee.canonical_name] = employee

    def resolve(self, identifier: str) -> str | None:
        """Resolve an email or canonical name to its canonical form.

        Tries matching against Jira email, Clockify email, or canonical name,
        in that order. Case-insensitive for email addresses.

        Args:
            identifier: A Jira email, Clockify email, canonical name, or unknown value.

        Returns:
            str | None: The canonical name if found, None otherwise.
        """
        identifier_lower = identifier.lower()

        # Try Jira email
        if identifier_lower in self._by_jira_email:
            return self._by_jira_email[identifier_lower]

        # Try Clockify email
        if identifier_lower in self._by_clockify_email:
            return self._by_clockify_email[identifier_lower]

        # Try canonical name (case-insensitive)
        for canonical in self._by_canonical_name:
            if canonical.lower() == identifier_lower:
                return canonical

        return None
