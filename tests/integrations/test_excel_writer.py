"""Tests for the Excel row-matching and upsert logic (scenario #10).

The row-lookup helpers are exercised against in-memory tables, and ``save_tasks``
is exercised end-to-end through a real workbook saved in ``tmp_path``: an existing
id is updated in place, a new id is appended and receives a verbatim copy of the
formula columns from the template row.
"""

from datetime import date

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table

from sop_pipeline.integrations.excel_table_helpers import (
    find_row,
    link_exists,
    next_row,
    expand_table,
)
from sop_pipeline.integrations.excel_writer import ExcelWriter
from sop_pipeline.models.schemas import Priority, Task, TaskType
from tests.integrations.conftest import TASK_HEADERS

# Column indices in the BASE_TAREFAS fixture layout (1-based).
COL_ID = 1
COL_TITULO = 2
COL_DATA_CONCLUSAO = 9
COL_TIPO = 10
COL_DIAS_RESTANTES = 13
COL_ATRASADO = 14
COL_STATUS_PRAZO = 15
COL_TURMA = 16
COL_ARQUIVADA_EM = 17
COL_TAREFA_PAI_ID = 18
FORMULA_COLS = [COL_DIAS_RESTANTES, COL_ATRASADO, COL_STATUS_PRAZO]


def _task(task_id: str, title: str) -> Task:
    """A valid Task for the writer tests."""
    return Task(
        task_id=task_id,
        title=title,
        assignee="Alice Silva",
        priority=Priority.HIGH,
        status="In Progress",
        area="TI",
        creation_date=date(2026, 1, 1),
        due_date=date(2026, 2, 1),
        task_type=TaskType.TASK,
        creator="Carol Lima",
        update_date=date(2026, 1, 5),
        turma="Primeiro Ano",
    )


# --- row-lookup helpers ----------------------------------------------------------


def test_find_row_returns_row_for_existing_id(simple_id_table) -> None:
    """A present id resolves to its 1-based row number."""
    worksheet, table = simple_id_table
    assert find_row(worksheet, "ROW-2", table) == 3


def test_find_row_returns_none_for_missing_id(simple_id_table) -> None:
    """An absent id resolves to None."""
    worksheet, table = simple_id_table
    assert find_row(worksheet, "NOPE", table) is None


def test_next_row_points_past_last_row(simple_id_table) -> None:
    """next_row returns the first free row after the table."""
    _, table = simple_id_table
    assert next_row(table) == 4


def test_expand_table_grows_the_reference(simple_id_table) -> None:
    """Expanding the table stretches its ref to include the new last row."""
    _, table = simple_id_table
    expand_table(table, 4)
    assert table.ref.endswith(":B4")


def test_link_exists_detects_present_and_absent_pairs(links_table) -> None:
    """link_exists is True only for a recorded task/tag pair."""
    worksheet, table = links_table
    assert link_exists(worksheet, table, "ABC-1", 5) is True
    assert link_exists(worksheet, table, "ABC-1", 6) is False


# --- save_tasks round-trip -------------------------------------------------------


def test_save_tasks_updates_existing_row_in_place(tasks_workbook_path: str) -> None:
    """An existing id overwrites its row without appending a new one."""
    ExcelWriter.save_tasks(tasks_workbook_path, [_task("ABC-1", "Updated title")])

    workbook = openpyxl.load_workbook(tasks_workbook_path)
    worksheet = workbook["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_ID).value == "ABC-1"
    assert worksheet.cell(row=2, column=COL_TITULO).value == "Updated title"
    assert worksheet.cell(row=2, column=COL_TURMA).value == "Primeiro Ano"
    # No row appended: the table still ends at row 2.
    assert worksheet.tables["base_tarefas"].ref.endswith("2")
    assert worksheet.cell(row=3, column=COL_ID).value is None


def test_save_tasks_appends_new_row_and_copies_formulas(tasks_workbook_path: str) -> None:
    """A new id is appended and the formula columns are copied from row 2."""
    ExcelWriter.save_tasks(tasks_workbook_path, [_task("ABC-2", "Second task")])

    workbook = openpyxl.load_workbook(tasks_workbook_path)
    worksheet = workbook["BASE_TAREFAS"]

    assert worksheet.cell(row=3, column=COL_ID).value == "ABC-2"
    assert worksheet.cell(row=3, column=COL_TITULO).value == "Second task"
    assert worksheet.cell(row=3, column=COL_TURMA).value == "Primeiro Ano"
    for column in FORMULA_COLS:
        template = worksheet.cell(row=2, column=column).value
        appended = worksheet.cell(row=3, column=column).value
        assert appended == template
        assert isinstance(appended, str) and appended.startswith("=")


# --- unmark_archived_tasks --------------------------------------------------------


def _archive_template_row(path: str) -> None:
    """Stamp arquivada_em on the fixture's ABC-1 row, as mark_archived_tasks would."""
    workbook = openpyxl.load_workbook(path)
    workbook["BASE_TAREFAS"].cell(row=2, column=COL_ARQUIVADA_EM, value=date(2026, 9, 26))
    workbook.save(path)


def test_unmark_archived_tasks_clears_row_of_seen_task(tasks_workbook_path: str) -> None:
    """An archived row whose id is in the seen set gets arquivada_em cleared, nothing else."""
    _archive_template_row(tasks_workbook_path)

    unarchived = ExcelWriter.unmark_archived_tasks(tasks_workbook_path, {"ABC-1", "NOT-IN-SHEET"})

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_ARQUIVADA_EM).value is None
    assert worksheet.cell(row=2, column=COL_TITULO).value == "Template title"
    assert unarchived == 1


def test_unmark_archived_tasks_leaves_unseen_row_archived(tasks_workbook_path: str) -> None:
    """An archived row whose id is not in the seen set keeps its date."""
    _archive_template_row(tasks_workbook_path)

    unarchived = ExcelWriter.unmark_archived_tasks(tasks_workbook_path, {"ABC-9"})

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_ARQUIVADA_EM).value is not None
    assert unarchived == 0


# --- mark_archived_tasks ----------------------------------------------------------

ARCHIVE_DATE = date(2026, 10, 6)


def _append_row(path: str, task_id: str | None) -> None:
    """Append a BASE_TAREFAS row in row 3 holding only an id and a title."""
    workbook = openpyxl.load_workbook(path)
    worksheet = workbook["BASE_TAREFAS"]
    worksheet.cell(row=3, column=COL_ID, value=task_id)
    worksheet.cell(row=3, column=COL_TITULO, value="Excel-only title")
    expand_table(worksheet.tables["base_tarefas"], 3)
    workbook.save(path)


def test_mark_archived_tasks_archives_excel_only_row_missing_from_clickup_193_vs_195(
    tasks_workbook_path: str,
) -> None:
    """Regression for the 195 (Excel) vs 193 (Postgres) active-task count.

    A task whose Postgres upsert failed lives only in the workbook. Once it is
    deleted from ClickUp, its row must be archived from the ClickUp id set,
    since Postgres has no archived row that could drive it.
    """
    _append_row(tasks_workbook_path, "86e2ydc64")

    archived = ExcelWriter.mark_archived_tasks(tasks_workbook_path, {"ABC-1"}, ARCHIVE_DATE)

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    cell = worksheet.cell(row=3, column=COL_ARQUIVADA_EM)
    assert cell.value.date() == ARCHIVE_DATE
    assert cell.number_format == "DD/MM/YYYY"
    assert worksheet.cell(row=3, column=COL_TITULO).value == "Excel-only title"
    assert worksheet.cell(row=2, column=COL_ARQUIVADA_EM).value is None
    assert archived == 1


def test_mark_archived_tasks_leaves_seen_row_active(tasks_workbook_path: str) -> None:
    """A row whose id is in the ClickUp set is not archived."""
    archived = ExcelWriter.mark_archived_tasks(tasks_workbook_path, {"ABC-1"}, ARCHIVE_DATE)

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_ARQUIVADA_EM).value is None
    assert archived == 0


def test_mark_archived_tasks_keeps_original_archive_date(tasks_workbook_path: str) -> None:
    """An already archived row keeps its original date instead of the run date."""
    _archive_template_row(tasks_workbook_path)

    archived = ExcelWriter.mark_archived_tasks(tasks_workbook_path, {"ABC-9"}, ARCHIVE_DATE)

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_ARQUIVADA_EM).value.date() == date(2026, 9, 26)
    assert archived == 0


def test_mark_archived_tasks_skips_row_with_empty_id(tasks_workbook_path: str) -> None:
    """A row with no id is never archived, even though it is not in the ClickUp set."""
    _append_row(tasks_workbook_path, None)

    archived = ExcelWriter.mark_archived_tasks(tasks_workbook_path, {"ABC-1"}, ARCHIVE_DATE)

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=3, column=COL_ARQUIVADA_EM).value is None
    assert archived == 0


def test_mark_archived_tasks_uses_table_position_when_table_is_not_at_a1(tmp_path) -> None:
    """Rows and the id column come from the table, not from sheet row 2 and column A.

    The table's header is on row 3 and its first column is B. Column A holds
    ids outside the table that disagree with the table's own ids, so reading
    column A, or starting at row 2, would archive the wrong rows.
    """
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "BASE_TAREFAS"
    for offset, header in enumerate(TASK_HEADERS):
        worksheet.cell(row=3, column=2 + offset, value=header)
    worksheet.cell(row=4, column=2, value="ABC-1")
    worksheet.cell(row=5, column=2, value="GONE-1")
    worksheet.cell(row=2, column=1, value="ABOVE-TABLE")
    worksheet.cell(row=4, column=1, value="OUTSIDE-1")
    worksheet.cell(row=5, column=1, value="ABC-1")
    last_column = get_column_letter(1 + len(TASK_HEADERS))
    worksheet.add_table(Table(displayName="base_tarefas", ref=f"B3:{last_column}5"))
    path = str(tmp_path / "offset.xlsx")
    workbook.save(path)
    archived_column = 2 + TASK_HEADERS.index("arquivada_em")

    archived = ExcelWriter.mark_archived_tasks(path, {"ABC-1"}, ARCHIVE_DATE)

    worksheet = openpyxl.load_workbook(path)["BASE_TAREFAS"]
    assert worksheet.cell(row=5, column=archived_column).value.date() == ARCHIVE_DATE
    assert worksheet.cell(row=4, column=archived_column).value is None
    assert worksheet.cell(row=3, column=archived_column).value == "arquivada_em"
    assert worksheet.cell(row=2, column=archived_column).value is None
    assert archived == 1


# --- completion cleared on reopen ---------------------------------------------------


def test_save_tasks_clears_stale_data_conclusao(tasks_workbook_path: str) -> None:
    """A row whose task has no completion_date any more gets data_conclusao emptied."""
    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_DATA_CONCLUSAO).value is not None

    ExcelWriter.save_tasks(tasks_workbook_path, [_task("ABC-1", "Reopened")])

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=2, column=COL_DATA_CONCLUSAO).value is None
    for column in FORMULA_COLS:
        assert str(worksheet.cell(row=2, column=column).value).startswith("=")


# --- subtasks ----------------------------------------------------------------------


def test_save_tasks_writes_parent_id_of_a_subtask(tasks_workbook_path: str) -> None:
    """A subtask's immediate parent id lands in tarefa_pai_id and tipo reads Subtask."""
    subtask = _task("ABC-2", "Child").model_copy(
        update={"parent_task_id": "ABC-1", "task_type": TaskType.SUBTASK}
    )

    ExcelWriter.save_tasks(tasks_workbook_path, [subtask])

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=3, column=COL_ID).value == "ABC-2"
    assert worksheet.cell(row=3, column=COL_TAREFA_PAI_ID).value == "ABC-1"
    assert worksheet.cell(row=3, column=COL_TIPO).value == "Subtask"


def test_save_tasks_leaves_parent_id_empty_for_a_regular_task(tasks_workbook_path: str) -> None:
    """A task with no parent writes an empty tarefa_pai_id."""
    ExcelWriter.save_tasks(tasks_workbook_path, [_task("ABC-2", "Top level")])

    worksheet = openpyxl.load_workbook(tasks_workbook_path)["BASE_TAREFAS"]
    assert worksheet.cell(row=3, column=COL_TAREFA_PAI_ID).value is None
    assert worksheet.cell(row=3, column=COL_TIPO).value == "Task"
