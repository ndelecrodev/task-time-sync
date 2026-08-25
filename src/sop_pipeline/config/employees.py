"""Employee identity mapping configuration.

Maps employees across ClickUp and Clockify by normalizing their identifiers
(email addresses) to canonical names for use as join keys in the Excel sheet.
"""

from logging import getLogger

from sop_pipeline.models.schemas import EmployeeMapping

logger = getLogger(__name__)


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
        self._by_clickup_email: dict[str, str] = {}
        self._by_clockify_email: dict[str, str] = {}
        self._by_canonical_name: dict[str, EmployeeMapping] = {}

        for employee in employees:
            clickup_lower = employee.clickup_email.lower()
            clockify_lower = employee.clockify_email.lower()

            if clickup_lower in self._by_clickup_email:
                existing = self._by_clickup_email[clickup_lower]
                if existing != employee.canonical_name:
                    raise ValueError(
                        f"ClickUp email {employee.clickup_email} mapped to "
                        f"both '{existing}' and '{employee.canonical_name}' "
                        f"(duplicate email in config)"
                    )
            self._by_clickup_email[clickup_lower] = employee.canonical_name

            if clockify_lower in self._by_clockify_email:
                existing = self._by_clockify_email[clockify_lower]
                if existing != employee.canonical_name:
                    raise ValueError(
                        f"Clockify email {employee.clockify_email} mapped to "
                        f"both '{existing}' and '{employee.canonical_name}' "
                        f"(duplicate email in config)"
                    )
            self._by_clockify_email[clockify_lower] = employee.canonical_name
            self._by_canonical_name[employee.canonical_name] = employee

    def resolve(self, identifier: str) -> str | None:
        """Resolve an email or canonical name to its canonical form.

        Tries matching against ClickUp email, Clockify email, or canonical name,
        in that order. Case-insensitive throughout.

        Args:
            identifier: A ClickUp email, Clockify email, canonical name, or unknown value.

        Returns:
            str | None: The canonical name if found, None otherwise.
        """
        identifier_lower = identifier.lower()

        if identifier_lower in self._by_clickup_email:
            return self._by_clickup_email[identifier_lower]

        if identifier_lower in self._by_clockify_email:
            return self._by_clockify_email[identifier_lower]

        for canonical in self._by_canonical_name:
            if canonical.lower() == identifier_lower:
                return canonical

        return None

    def get_registered_email(self, canonical_name: str) -> str | None:
        """Resolve a canonical name back to its registered email.

        Args:
            canonical_name: The employee's canonical name.

        Returns:
            str | None: The registered email, or ``None`` if no employee
            matches this name.
        """
        name_lower = canonical_name.lower()

        for canonical, employee in self._by_canonical_name.items():
            if canonical.lower() == name_lower:
                return employee.clickup_email

        return None
