"""Tests for ExcelReader.read_employees (scenario #11).

The reader must map each column to its header and replace blank email cells
with the default anonymous email to ensure data consistency.
"""

from sop_pipeline.integrations.excel_reader import ExcelReader
from sop_pipeline.config.settings import settings


def test_read_employees_maps_columns_to_headers(employees_workbook_path: str) -> None:
    """Every row is returned as a dict keyed by the column headers."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    assert rows[0] == {
        "nome": "Alice Silva",
        "clickup_email": "alice.jira@example.com",
        "clockify_email": "alice.clockify@example.com",
        "photo_url": "https://storage.example.com/alice.jpg",
    }


def test_read_employees_returns_all_rows(employees_workbook_path: str) -> None:
    """Both data rows are read; a blank cell does not drop the row."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    assert [row["nome"] for row in rows] == ["Alice Silva", "Bob Souza"]


def test_read_employees_replaces_blank_email_with_default(employees_workbook_path: str) -> None:
    """Blank email cells are replaced with the default anonymous email."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    # Bob's row has None for clickup_email and photo_url, but they should be replaced
    assert rows[1]["clickup_email"] == settings.DEFAULT_ANONYMOUS_EMAIL
    assert rows[1]["clockify_email"] == "bob.clockify@example.com"
    assert rows[1]["photo_url"] is None  # photo_url is not an email, so it's not replaced


def test_fill_blank_emails_replaces_none_values() -> None:
    """_fill_blank_emails replaces None email values with default anonymous email."""
    row = {
        "nome": "Test User",
        "clickup_email": None,
        "clockify_email": None,
        "photo_url": None,
    }
    
    result = ExcelReader._fill_blank_emails(row)
    
    assert result["clickup_email"] == settings.DEFAULT_ANONYMOUS_EMAIL
    assert result["clockify_email"] == settings.DEFAULT_ANONYMOUS_EMAIL
    assert result["photo_url"] is None  # photo_url should remain unchanged


def test_fill_blank_emails_keeps_non_blank_values() -> None:
    """_fill_blank_emails preserves non-blank email values."""
    row = {
        "nome": "Test User",
        "clickup_email": "user@example.com",
        "clockify_email": None,
        "photo_url": "https://example.com/photo.jpg",
    }
    
    result = ExcelReader._fill_blank_emails(row)
    
    assert result["clickup_email"] == "user@example.com"
    assert result["clockify_email"] == settings.DEFAULT_ANONYMOUS_EMAIL
    assert result["photo_url"] == "https://example.com/photo.jpg"
