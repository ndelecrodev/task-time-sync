"""Reads the editable employee sheet out of the Excel workbook."""

from openpyxl.utils import range_boundaries

from sop_pipeline.integrations.excel_workbook import create_column_map, open_workbook
from sop_pipeline.config.settings import settings


class ExcelReader:
    """Reads sheets maintained by hand in the workbook."""

    @staticmethod
    def _fill_blank_emails(row: dict) -> dict:
        """Replace blank email fields with the default anonymous email.

        Args:
            row: A row dictionary with email fields.

        Returns:
            dict: The row with blank emails replaced by the default anonymous email.
        """
        if not row.get("clickup_email") or row["clickup_email"] is None:
            row["clickup_email"] = settings.DEFAULT_ANONYMOUS_EMAIL
        if not row.get("clockify_email") or row["clockify_email"] is None:
            row["clockify_email"] = settings.DEFAULT_ANONYMOUS_EMAIL
        return row

    @staticmethod
    def read_employees(file_path: str) -> list[dict]:
        """Read every row of the ``DIM_FUNCIONARIO`` sheet.

        Args:
            file_path: Path to the local workbook.

        Returns:
            list[dict]: One dict per row, keyed by column header.
        """
        rows = ExcelReader.read_sheet_as_dicts(
            file_path, sheet_name="DIM_FUNCIONARIO", table_name="dim_funcionario"
        )
        return [ExcelReader._fill_blank_emails(row) for row in rows]

    @staticmethod
    def read_dim_employee_area(file_path: str) -> list[dict]:
        """Read every row of the ``DIM_FUNCIONARIO_AREA`` sheet.

        Args:
            file_path: Path to the local workbook.

        Returns:
            list[dict]: One dict per row, keyed by column header.
        """
        return ExcelReader.read_sheet_as_dicts(
            file_path, sheet_name="DIM_FUNCIONARIO_AREA", table_name="dim_func_area"
        )

    @staticmethod
    def read_fato_employee_area(file_path: str) -> list[dict]:
        """Read every row of the ``FATO_FUNCIONARIO_AREA`` sheet.

        Args:
            file_path: Path to the local workbook.

        Returns:
            list[dict]: One dict per row, keyed by column header.
        """
        return ExcelReader.read_sheet_as_dicts(
            file_path, sheet_name="FATO_FUNCIONARIO_AREA", table_name="fato_funcionario"
        )

    @staticmethod
    def read_sheet_as_dicts(file_path: str, sheet_name: str, table_name: str) -> list[dict]:
        """Read every row of a named table on a named sheet.

        Args:
            file_path: Path to the local workbook.
            sheet_name: The worksheet containing the table.
            table_name: The Excel table to read rows from.

        Returns:
            list[dict]: One dict per row, keyed by column header.
        """
        workbook = open_workbook(file_path)
        worksheet = workbook[sheet_name]
        table = worksheet.tables[table_name]

        column_map = create_column_map(worksheet=worksheet, table=table)

        rows = []
        for row_index in range(2, range_boundaries(table.ref)[3] + 1):
            row = {}
            for header, column in column_map.items():
                row[header] = worksheet.cell(row=row_index, column=column).value
            rows.append(row)

        return rows
