"""Writes the pipeline output into the Excel workbook.

The workbook is the final deliverable: it is not a dump, it is a living file with
its own tables, formulas and pivot-style sheets. Two conventions come from the
file itself and are relied on throughout this module:

* sheet names are uppercase, table names are lowercase;
* the first column of every table is the ID used to upsert rows.

Every literal sheet name, table name and column header in this module is a real
identifier inside the ``.xlsx`` file. They are deliberately kept in Portuguese —
translating them would break the lookups at runtime.
"""

from datetime import date
from enum import Enum

from sop_pipeline.errors.exceptions import ExcelWriteError
from sop_pipeline.models.schemas import Task, TaskDetail, TimeEntry
from sop_pipeline.integrations.excel_workbook import open_workbook, create_column_map
from sop_pipeline.integrations.excel_table_helpers import (
    expand_table,
    find_row,
    find_tag_id,
    link_exists,
    next_row,
    next_tag_id,
)

# Left side: literal column header in the spreadsheet.
# Right side: attribute name on the Task model.
TASK_COLUMN_MAP = {
    "id": "task_id",
    "titulo": "title",
    "responsavel": "assignee",
    "area": "area",
    "prioridade": "priority",
    "status": "status",
    "data_criacao": "creation_date",
    "prazo": "due_date",
    "data_conclusao": "completion_date",
    "tipo": "task_type",
    "criador": "creator",
    "data_atualizacao": "update_date",
}

# Columns owned by Excel formulas, not by Python. Kept out of TASK_COLUMN_MAP on
# purpose so the spreadsheet stays able to recalculate them on its own.
FORMULA_COLUMNS = ["dias_restantes", "atrasado", "status_prazo"]


class ExcelWriter:
    """Upserts tasks, tags, details and hours into the workbook."""

    @staticmethod
    def _copy_formulas(worksheet, new_row: int, template_row: int, column_map: dict) -> None:
        """Replicate the calculated columns onto a newly appended row.

        Copying the formula *text* verbatim works because those formulas use
        structured references such as ``base_tarefas[[#This Row],[prazo]]``, which
        resolve relative to whichever row they sit on. The same string is
        therefore correct on every row, and no offset rewriting is needed.

        Args:
            worksheet: The worksheet being written to.
            new_row: Row that has just been appended.
            template_row: Row to copy the formulas from (row 2 in practice).
            column_map: Header-to-column-index map for this table.
        """
        for column_name in FORMULA_COLUMNS:
            column = column_map[column_name]
            formula = worksheet.cell(row=template_row, column=column).value
            worksheet.cell(row=new_row, column=column, value=formula)

    @staticmethod
    def _write_task_row(worksheet, row: int, task: Task, column_map: dict) -> None:
        """Write every mapped attribute of a task onto one row.

        Args:
            worksheet: The worksheet being written to.
            row: Target row number.
            task: The task whose values are written.
            column_map: Header-to-column-index map for this table.
        """
        for header, attribute in TASK_COLUMN_MAP.items():
            value = getattr(task, attribute)

            # Enums must be unwrapped: openpyxl would otherwise write their repr.
            if isinstance(value, Enum):
                value = value.value

            cell = worksheet.cell(row=row, column=column_map[header], value=value)

            if isinstance(value, date):
                cell.number_format = "DD/MM/YYYY"

    @staticmethod
    def save_tasks(file_path: str, tasks: list[Task]) -> None:
        """Upsert tasks into the ``BASE_TAREFAS`` sheet.

        A task whose ID already exists is updated in place; a new one is appended
        and receives a copy of the calculated columns. This makes repeated runs
        idempotent.

        Args:
            file_path: Path to the local workbook.
            tasks: The tasks to persist.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet = workbook["BASE_TAREFAS"]
            table = worksheet.tables["base_tarefas"]
            column_map = create_column_map(worksheet, table)

            for task in tasks:
                row = find_row(worksheet, task.task_id, table)
                if row is not None:
                    ExcelWriter._write_task_row(worksheet, row, task, column_map)
                else:
                    row = next_row(table)
                    expand_table(table, row)
                    ExcelWriter._write_task_row(worksheet, row, task, column_map)
                    ExcelWriter._copy_formulas(
                        worksheet, row, template_row=2, column_map=column_map
                    )

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(f"Failed to save tasks to {file_path}: {error}") from error

    @staticmethod
    def mark_archived_tasks(file_path: str, archived_tasks) -> None:
        """Write the archived date into BASE_TAREFAS for already-archived tasks.

        Only the arquivada_em column is touched; every other field on
        these rows keeps its last known value from before the task
        disappeared from Jira, by design (see design-decisions.md).

        Args:
            file_path: Path to the local workbook.
            archived_tasks: Rows with task_id and arquivada_em, as
                returned by PostgresClient.get_archived_tasks.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet = workbook["BASE_TAREFAS"]
            table = worksheet.tables["base_tarefas"]
            column_map = create_column_map(worksheet=worksheet, table=table)

            for task in archived_tasks:
                row = find_row(worksheet, task.task_id, table)
                if row is None:
                    continue
                cell = worksheet.cell(
                    row=row, column=column_map["arquivada_em"], value=task.arquivada_em.date()
                )
                cell.number_format = "DD/MM/YYYY"

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(
                f"Failed to mark archived tasks in {file_path}: {error}"
            ) from error

    @staticmethod
    def _get_or_create_tag_id(worksheet, table, tag_name: str) -> int:
        """Return a tag's ID, creating the dimension row if it does not exist.

        Args:
            worksheet: The ``DIM_ETIQUETAS`` worksheet.
            table: The tag dimension table.
            tag_name: The tag name to resolve.

        Returns:
            int: The existing or newly assigned tag ID.
        """
        existing_id = find_tag_id(worksheet, table, tag_name)
        if existing_id is not None:
            return existing_id

        next_id = next_tag_id(worksheet, table)
        row = next_row(table)
        worksheet.cell(row=row, column=1, value=next_id)
        worksheet.cell(row=row, column=2, value=tag_name)
        expand_table(table, row)

        return next_id

    @staticmethod
    def _create_link(worksheet, table, task_id: str, tag_id: int) -> None:
        """Append a task-tag association to the fact table.

        Args:
            worksheet: The ``FATO_TAREFA_ETIQUETA`` worksheet.
            table: The fact table holding the associations.
            task_id: Jira issue key.
            tag_id: Surrogate tag ID.
        """
        new_row = next_row(table)

        worksheet.cell(row=new_row, column=1, value=task_id)
        worksheet.cell(row=new_row, column=2, value=tag_id)

        expand_table(table, new_row)

    @staticmethod
    def save_tags(file_path: str, tasks: list[Task]) -> None:
        """Persist task tags as a dimension plus a many-to-many fact table.

        A task can carry several tags and a tag is shared by many tasks, so the
        relation is modelled with ``DIM_ETIQUETAS`` (one row per distinct tag)
        and ``FATO_TAREFA_ETIQUETA`` (one row per association).

        Args:
            file_path: Path to the local workbook.
            tasks: The tasks whose tags are persisted.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet_tags = workbook["DIM_ETIQUETAS"]
            table_tags = worksheet_tags.tables["dim_etiquetas"]
            worksheet_links = workbook["FATO_TAREFA_ETIQUETA"]
            table_links = worksheet_links.tables["fato_tarefa_etiqueta"]

            for task in tasks:
                for tag_name in task.tags:
                    tag_id = ExcelWriter._get_or_create_tag_id(worksheet_tags, table_tags, tag_name)
                    if not link_exists(worksheet_links, table_links, task.task_id, tag_id):
                        ExcelWriter._create_link(worksheet_links, table_links, task.task_id, tag_id)

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(f"Failed to save tags to {file_path}: {error}") from error

    @staticmethod
    def save_details(file_path: str, details: list[TaskDetail]) -> None:
        """Upsert task descriptions into the ``DETALHES_TAREFA`` sheet.

        Args:
            file_path: Path to the local workbook.
            details: The task details to persist.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet = workbook["DETALHES_TAREFA"]
            table = worksheet.tables["detalhes_tarefa"]

            for detail in details:
                row = find_row(worksheet, detail.task_id, table)
                if row is None:
                    row = next_row(table)
                    expand_table(table, row)
                ExcelWriter._write_detail_row(worksheet, row, detail)

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(f"Failed to save details to {file_path}: {error}") from error

    @staticmethod
    def _write_detail_row(worksheet, row: int, detail: TaskDetail) -> None:
        """Write one task detail onto a row.

        This sheet has a fixed two-column layout (id, descricao), so the columns
        are addressed by position instead of through a header map.

        Args:
            worksheet: The ``DETALHES_TAREFA`` worksheet.
            row: Target row number.
            detail: The detail record to write.
        """
        worksheet.cell(row=row, column=1, value=detail.task_id)
        worksheet.cell(row=row, column=2, value=detail.description)

    @staticmethod
    def _write_hour_row(worksheet, row: int, time_entry: TimeEntry) -> None:
        """Write one time entry onto a row.

        This sheet has a fixed four-column layout (id, funcionario, data, horas),
        so the columns are addressed by position instead of through a header map.

        Args:
            worksheet: The ``BASE_HORAS`` worksheet.
            row: Target row number.
            time_entry: The time entry to write.
        """
        worksheet.cell(row=row, column=1, value=time_entry.entry_id)
        worksheet.cell(row=row, column=2, value=time_entry.employee)
        worksheet.cell(row=row, column=4, value=time_entry.hours)

        cell = worksheet.cell(row=row, column=3, value=time_entry.entry_date)

        if isinstance(time_entry.entry_date, date):
            cell.number_format = "DD/MM/YYYY"

    @staticmethod
    def save_hours(file_path: str, time_entries: list[TimeEntry]) -> None:
        """Upsert Clockify time entries into the ``BASE_HORAS`` sheet.

        Args:
            file_path: Path to the local workbook.
            time_entries: The time entries to persist.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet = workbook["BASE_HORAS"]
            table = worksheet.tables["base_horas"]

            for time_entry in time_entries:
                row = find_row(worksheet, time_entry.entry_id, table)
                if row is None:
                    row = next_row(table)
                    expand_table(table, row)
                ExcelWriter._write_hour_row(worksheet, row, time_entry)

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(f"Failed to save hours to {file_path}: {error}") from error

    @staticmethod
    def _write_duplicate_row(worksheet, row: int, duplicate: dict) -> None:
        """Write one removed-duplicate record onto a row.

        This sheet has a fixed four-column layout (nome, jira_email,
        clockify_email, motivo), so the columns are addressed by position
        instead of through a header map.

        Args:
            worksheet: The ``DUPLICADOS_REMOVIDOS`` worksheet.
            row: Target row number.
            duplicate: The duplicate record to write.
        """
        worksheet.cell(row=row, column=1, value=duplicate["nome"])
        worksheet.cell(row=row, column=2, value=duplicate["jira_email"])
        worksheet.cell(row=row, column=3, value=duplicate["clockify_email"])
        worksheet.cell(row=row, column=4, value=duplicate["reason"])

    @staticmethod
    def save_duplicates(file_path: str, duplicates: list[dict]) -> None:
        """Append the employee rows dropped as duplicates to the audit sheet.

        Unlike the other save_* methods this only ever appends: a removed
        duplicate is a one-time event, not a record that gets updated later.

        Args:
            file_path: Path to the local workbook.
            duplicates: The duplicate records to persist.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        try:
            workbook = open_workbook(file_path)
            worksheet = workbook["DUPLICADOS_REMOVIDOS"]
            table = worksheet.tables["duplicados_removidos"]

            for duplicate in duplicates:
                row = next_row(table)
                expand_table(table, row)
                ExcelWriter._write_duplicate_row(worksheet, row, duplicate)

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(f"Failed to save duplicates to {file_path}: {error}") from error

    @staticmethod
    def save_progress_snapshot(
        file_path: str, snapshot_date: date, total_tarefas: int, concluidas: int
    ) -> None:
        """Upsert one day's completion snapshot into ``HISTORICO_PROGRESSO``.

        Unlike ``dias_restantes``/``atrasado``/``status_prazo`` (see
        design-decisions.md decision 2), ``percentual`` is written here as a value
        computed by Python, not left as an Excel formula. Those columns are
        deliberately kept live because they describe the *current* state of a
        task that is still open. This column is the opposite case: it is a
        historical snapshot, and the whole point of ``HISTORICO_PROGRESSO`` is to
        record what the completion percentage *was* on ``snapshot_date``. A live
        formula recalculating `concluidas/total` from today's data would make
        every past row silently drift to reflect today's totals instead, erasing
        the history the sheet exists to keep.

        Args:
            file_path: Path to the local workbook.
            snapshot_date: The date this snapshot represents; also the upsert key.
            total_tarefas: Total task count at the time of the snapshot.
            concluidas: Count of tasks with a non-null completion date.

        Raises:
            ExcelWriteError: If the workbook cannot be updated or saved.
        """
        if total_tarefas == 0:
            percentual = 0
        else:
            percentual = concluidas / total_tarefas

        try:
            workbook = open_workbook(file_path=file_path)
            worksheet = workbook["HISTORICO_PROGRESSO"]
            table = worksheet.tables["historico_progresso"]
            row = find_row(worksheet, snapshot_date, table)
            if row is None:
                row = next_row(table)
                expand_table(table, row)
            worksheet.cell(row=row, column=1, value=snapshot_date)
            worksheet.cell(row=row, column=2, value=total_tarefas)
            worksheet.cell(row=row, column=3, value=concluidas)
            worksheet.cell(row=row, column=4, value=percentual)

            workbook.save(file_path)
        except (OSError, KeyError, ValueError) as error:
            raise ExcelWriteError(
                f"Failed to save and insert value in progress_snapshot to {file_path}: {error}"
            ) from error
