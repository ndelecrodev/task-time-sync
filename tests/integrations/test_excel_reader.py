"""Tests for ExcelReader.read_employees (scenario #11).

The reader must map each column to its header and pass blank cells through as
``None`` rather than skipping the row or substituting a default.
"""

from sop_pipeline.integrations.excel_reader import ExcelReader


def test_read_employees_maps_columns_to_headers(employees_workbook_path: str) -> None:
    """Every row is returned as a dict keyed by the column headers."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    assert rows[0] == {
        "nome": "Alice Silva",
        "jira_email": "alice.jira@example.com",
        "clockify_email": "alice.clockify@example.com",
        "photo_url": "https://storage.example.com/alice.jpg",
    }


def test_read_employees_returns_all_rows(employees_workbook_path: str) -> None:
    """Both data rows are read; a blank cell does not drop the row."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    assert [row["nome"] for row in rows] == ["Alice Silva", "Bob Souza"]


def test_read_employees_keeps_blank_cell_as_none(employees_workbook_path: str) -> None:
    """A blank cell becomes None, not an empty string or a skipped key."""
    rows = ExcelReader.read_employees(employees_workbook_path)

    assert rows[1]["jira_email"] is None
    assert rows[1]["clockify_email"] == "bob.clockify@example.com"
    assert rows[1]["photo_url"] is None
