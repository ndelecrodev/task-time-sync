"""Syncs employee identity and area assignments from the Excel workbook into Postgres.

The workbook's ``DIM_FUNCIONARIO`` sheet is the editable source of employee
identity: whoever maintains the pipeline adds or corrects employees there, and
this service pushes that sheet into Postgres before each run so the rest of
the pipeline can resolve names and emails to a stable ``funcionarios.id``. The
``DIM_FUNCIONARIO_AREA`` and ``FATO_FUNCIONARIO_AREA`` sheets are likewise the
editable source of which employees belong to which areas, and this service
pushes those associations into Postgres too.
"""

from sop_pipeline.integrations.excel_reader import ExcelReader
from sop_pipeline.clients.postgres_client import PostgresClient
from sop_pipeline.integrations.excel_writer import ExcelWriter


class EmployeeDataSyncService:
    """Reads employee identity and area rows from Excel and upserts them into Postgres."""

    def __init__(self, excel_reader: ExcelReader, postgres_client: PostgresClient) -> None:
        """Store the collaborators used to read and persist employee rows.

        Args:
            excel_reader: Reads the ``DIM_FUNCIONARIO`` sheet.
            postgres_client: Persists employees into Postgres.
        """
        self.excel_reader = excel_reader
        self.postgres_client = postgres_client

    @staticmethod
    def _split_duplicates(rows: list[dict]) -> tuple[list[dict], list[dict]]:
        """Separate employee rows whose email already appeared earlier in the sheet.

        A row is a duplicate the moment either of its emails was already seen,
        since that email is what identifies the employee across systems; the
        first occurrence wins and later ones are set aside for review instead
        of overwriting it.

        Args:
            rows: Employee rows as returned by ``ExcelReader.read_employees``.

        Returns:
            tuple[list[dict], list[dict]]: The unique rows, then the duplicates.
        """
        seen_jira_emails = set()
        seen_clockify_emails = set()
        unique_rows = []
        duplicate_rows = []

        for row in rows:
            jira = row["jira_email"]
            clockify = row["clockify_email"]

            if jira in seen_jira_emails or clockify in seen_clockify_emails:
                row["reason"] = f"E-mail já foi cadastrado: {jira} ou {clockify}"
                duplicate_rows.append(row)
            else:
                seen_jira_emails.add(jira)
                seen_clockify_emails.add(clockify)
                unique_rows.append(row)

        return unique_rows, duplicate_rows

    def sync(self, file_path: str) -> None:
        """Push the workbook's employee sheet into Postgres.

        Args:
            file_path: Path to the local workbook.
        """
        rows = self.excel_reader.read_employees(file_path)
        unique_rows, duplicate_rows = self._split_duplicates(rows)

        for row in unique_rows:
            self.postgres_client.upsert_employee(
                canonical_name=row["nome"],
                jira_email=row["jira_email"],
                clockify_email=row["clockify_email"],
                photo_url=row["photo_url"],
            )

        if duplicate_rows:
            ExcelWriter.save_duplicates(file_path, duplicate_rows)

    def sync_areas(self, file_path: str, name_to_id: dict) -> None:
        """Push the workbook's employee-area assignments into Postgres.

        Args:
            file_path: Path to the local workbook.
            name_to_id: Employee canonical name mapped to ``funcionarios.id``.
        """
        employee_rows = self.excel_reader.read_employees(file_path)
        id_to_name = {row["id_funcionario"]: row["nome"] for row in employee_rows}

        area_rows = self.excel_reader.read_dim_employee_area(file_path)
        area_names_by_id = {row["id_area"]: row["nome_area"] for row in area_rows}

        link_rows = self.excel_reader.read_fato_employee_area(file_path)
        for link in link_rows:
            employee_name = id_to_name.get(link["id_funcionario"])
            area_name = area_names_by_id.get(link["id_area"])
            employee_id = name_to_id.get(employee_name)

            if employee_id is None or area_name is None:
                continue

            self.postgres_client.upsert_area_and_link(employee_id=employee_id, area_name=area_name)
