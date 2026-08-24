"""Tests for the EmployeeRegistry (scenario #1).

Covers construction-time conflict detection, case-insensitive email handling and
the documented ``resolve`` lookup order (jira_email, then clockify_email, then
canonical_name).
"""

import pytest

from sop_pipeline.config.employees import EmployeeMapping, EmployeeRegistry


def _mapping(canonical_name: str, jira_email: str, clockify_email: str) -> EmployeeMapping:
    """Build an EmployeeMapping with explicit identifiers."""
    return EmployeeMapping(
        canonical_name=canonical_name,
        jira_email=jira_email,
        clockify_email=clockify_email,
    )


@pytest.mark.parametrize(
    "shared_field",
    ["jira_email", "clockify_email"],
)
def test_duplicate_email_to_two_names_raises_value_error(shared_field: str) -> None:
    """A single email mapped to two canonical names is a config error."""
    shared = "shared@example.com"
    first = _mapping(
        "Alice Silva",
        jira_email=shared if shared_field == "jira_email" else "alice.jira@example.com",
        clockify_email=shared if shared_field == "clockify_email" else "alice.clockify@example.com",
    )
    second = _mapping(
        "Bob Souza",
        jira_email=shared if shared_field == "jira_email" else "bob.jira@example.com",
        clockify_email=shared if shared_field == "clockify_email" else "bob.clockify@example.com",
    )

    with pytest.raises(ValueError, match="duplicate email in config"):
        EmployeeRegistry([first, second])


def test_duplicate_email_detection_is_case_insensitive() -> None:
    """Two casings of the same email to different names still conflict."""
    first = _mapping("Alice Silva", "Alice@Example.com", "alice.clockify@example.com")
    second = _mapping("Bob Souza", "alice@example.com", "bob.clockify@example.com")

    with pytest.raises(ValueError, match="duplicate email in config"):
        EmployeeRegistry([first, second])


def test_same_email_and_same_name_does_not_raise() -> None:
    """Repeating an identical mapping is harmless, not a conflict."""
    mapping = _mapping("Alice Silva", "alice.jira@example.com", "alice.clockify@example.com")

    registry = EmployeeRegistry([mapping, mapping])

    assert registry.resolve("alice.jira@example.com") == "Alice Silva"


def test_resolve_matches_jira_email(employee_registry: EmployeeRegistry) -> None:
    """A Jira email resolves to its canonical name."""
    assert employee_registry.resolve("alice.jira@example.com") == "Alice Silva"


def test_resolve_matches_clockify_email(employee_registry: EmployeeRegistry) -> None:
    """A Clockify email resolves to its canonical name."""
    assert employee_registry.resolve("bob.clockify@example.com") == "Bob Souza"


def test_resolve_matches_canonical_name_preserving_stored_case(
    employee_registry: EmployeeRegistry,
) -> None:
    """A canonical-name lookup is case-insensitive but returns the stored case."""
    assert employee_registry.resolve("alice silva") == "Alice Silva"


def test_resolve_emails_are_case_insensitive(employee_registry: EmployeeRegistry) -> None:
    """An email in a different casing still resolves."""
    assert employee_registry.resolve("ALICE.JIRA@EXAMPLE.COM") == "Alice Silva"


def test_resolve_returns_none_for_unknown_identifier(
    employee_registry: EmployeeRegistry,
) -> None:
    """An identifier absent from every index resolves to None."""
    assert employee_registry.resolve("stranger@example.com") is None


def test_resolve_prefers_jira_email_over_canonical_name() -> None:
    """When a value is both a Jira email and another person's name, Jira wins.

    ``resolve`` tries the Jira-email index before scanning canonical names, so a
    string that happens to be both must resolve through the email index.
    """
    ann = _mapping("ann@example.com", "ann@example.com", "ann.clockify@example.com")
    bob = _mapping("Bob Souza", "bob.jira@example.com", "bob.clockify@example.com")
    registry = EmployeeRegistry([ann, bob])

    # "ann@example.com" is Ann's jira_email and also, coincidentally, her
    # canonical name; the jira-email branch must answer first.
    assert registry.resolve("ann@example.com") == "ann@example.com"


def test_resolve_prefers_clockify_email_over_canonical_name() -> None:
    """Clockify email is tried before the canonical-name scan."""
    # "shared-name" is Bob's clockify email but also Alice's canonical name.
    alice = _mapping("shared-name@example.com", "alice.jira@example.com", "alice.ck@example.com")
    bob = _mapping("Bob Souza", "bob.jira@example.com", "shared-name@example.com")
    registry = EmployeeRegistry([alice, bob])

    assert registry.resolve("shared-name@example.com") == "Bob Souza"


def test_get_registered_email_matches_canonical_name_case_insensitively(
    employee_registry: EmployeeRegistry,
) -> None:
    """A canonical-name lookup in a different casing still resolves to the registered email."""
    assert employee_registry.get_registered_email("ALICE SILVA") == "alice.jira@example.com"


def test_get_registered_email_returns_none_for_unregistered_name(
    employee_registry: EmployeeRegistry,
) -> None:
    """A name absent from the registry resolves to None, not an exception."""
    assert employee_registry.get_registered_email("Stranger Person") is None
