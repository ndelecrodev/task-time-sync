"""Reads the editable employee sheet out of the Excel workbook."""

from openpyxl.utils import range_boundaries

from sop_pipeline.integrations.excel_workbook import create_column_map, open_workbook


class ExcelReader:
    """Reads sheets maintained by hand in the workbook."""

    @staticmethod
    def read_employees(file_path: str) -> list[dict]:
        """Read every row of the ``DIM_FUNCIONARIO`` sheet.

        Args:
            file_path: Path to the local workbook.

        Returns:
            list[dict]: One dict per row, keyed by column header.
        """
        workbook = open_workbook(file_path)
        worksheet = workbook["DIM_FUNCIONARIO"]
        table = worksheet.tables['dim_funcionario']

        column_map = create_column_map(worksheet=worksheet, table=table)

        rows = []
        for row_index in range(2, range_boundaries(table.ref)[3] + 1):
            row = {}
            for header, column in column_map.items():
                row[header] = worksheet.cell(row=row_index, column=column).value
            rows.append(row)

        return rows
