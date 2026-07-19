# Design decisions

Record of non-obvious choices in the project and the reasoning behind them.

## 1. Upsert is done by ID, scanning the first column

`ExcelWriter._find_row` traverses column 1 of the table looking for the ID. If found, it overwrites the row; if not, it adds a new one.

**Why:** makes execution **idempotent**. The pipeline runs on schedule and
the `JIRA_JQL` usually brings back issues that are already in the spreadsheet. Without
upsert, each execution would duplicate rows. With it, running twice in a row
produces exactly the same file.

**Cost:** the search is linear (O(n) per record, O(n²) per execution). For the current
scale — a few hundred rows — it's irrelevant, and keeps code without auxiliary state. If the spreadsheet grows to thousands of rows, the solution is to build an
index `{id: row}` once per tab, before the loop.

## 2. Calculated columns stay in Excel formula, not Python

`dias_restantes`, `atrasado`, and `status_prazo` are not in `TASK_COLUMN_MAP`. Python never writes values to them — it only copies the formula text when creating a new row.

**Why:** the spreadsheet is the end product and is opened by people on days the pipeline doesn't run. If these fields were written as static values,
"days remaining" would freeze at the last execution date and become incorrect.
As a formula, Excel recalculates it every time someone opens the file.

The `Task` model **also** exposes `days_remaining` / `is_late` / `deadline_status`,
but only for the alert rule and notification text, which need the value at execution time.

> Known divergence: the Excel formula uses `MAX(prazo-TODAY(),0)`, so it never shows a negative number; `Task.days_remaining` in Python returns negative for overdue tasks. Since Python doesn't write to this column, the two definitions never overlap, but it's good to know when comparing both sides.

## 3. Copying formula text works because of structured table references

`_copy_formula` copies the formula string from row 2 to the new row without rewriting any index.

**Why:** the spreadsheet's formulas use structured table references:

```
=IF(base_tarefas[[#This Row],[data_conclusao]]<>"","Concluído", ...)
```

`[#This Row]` resolves relative to the row the formula is in. The same text is,
therefore, correct in any row — there is no offset to fix, unlike what would happen with references like `J2`, `J3`.

## 4. Labels use N:N relationship

A label became two tabs: `DIM_ETIQUETAS` (one row per distinct label,
with surrogate ID) and `FATO_TAREFA_ETIQUETA` (one row per association).

**Why:** the relationship is genuinely many-to-many — a task can have
multiple labels and a label is used by multiple tasks. The alternatives were worse:

- storing labels concatenated in a cell (`"bug;urgent"`) would prevent
  counting tasks by label or building a pivot table;
- creating one column per label would require changing the spreadsheet schema
  every time the team invents a new label.

With dimensional modeling, a pivot table by label comes for free, and
`_get_or_create_tag_id` creates the dimension on demand.

The same reasoning applies to `FATO_FUNCIONARIO_AREA`: a person can work in
more than one area.

## 5. `fullCalcOnLoad` is enabled on every workbook open

`_open_workbook` always sets `workbook.calculation.fullCalcOnLoad = True`.

**Why:** openpyxl reads the *cached value* of formulas and rewrites it on save.
Without this flag, a newly-inserted row would display an empty or stale cache
until someone edits the cell. With the flag, Excel recalculates the entire file
on next open.

## 6. Spreadsheet identifiers stay in Portuguese

Tab names (`BASE_TAREFAS`), table names (`base_tarefas`), column headers (`data_criacao`), and the values of `DeadlineStatus` (`"Concluído"`) remain in
Portuguese, even though the code is all in English.

**Why:** they are not code names, they are **data**. They are looked up at runtime inside the `.xlsx` file (`workbook["BASE_TAREFAS"]`,
`worksheet.tables["base_tarefas"]`, `column_map["data_criacao"]`) and compared with
what Excel formulas produce. Translating them would break the pipeline at runtime,
with no import error to warn you.

That's why `TASK_COLUMN_MAP` exists: it's the explicit boundary between the
data world (left, Portuguese) and the code world (right, English).

## 7. Heartbeat is outside error handling

See [`architecture.md`](architecture.md#observability): the heartbeat should
fire only when the spreadsheet actually reached the bucket. It is the last line
of `run()` and is not protected by `try/except` precisely so an earlier failure
will prevent it from running.

## 8. Invalid records are discarded, they don't interrupt execution

`transform_tasks`, `transform_details`, and `transform_time_entries` catch
`ValidationError` and `KeyError` **per record**, log a `warning`, and continue.

**Why:** a single issue with a missing field can't cost the entire day's synchronization. The warning goes to Better Stack for later investigation.

**Trade-off:** a systematic error (for example, `JIRA_CUSTOMFIELD_AREA`
pointing to a field that no longer exists) would show up as "all tasks were skipped", with execution apparently succeeding. That's why the discard is logged at
**ERROR** level and sent to Sentry, and the sync end log includes a count: `"Jira: N issues fetched, M tasks written, K discarded"` — a `K` above
zero is a sign of structural trouble, typically a new priority or issue type in Jira that doesn't exist in the enums in `models/schemas.py`.

**Caution when editing this `except`:** it explicitly lists `AttributeError` and
`TypeError` (the tuple `RECORD_ERRORS`) besides `ValidationError`/`KeyError`. Without
them, an unexpected `null` field from Jira throws `AttributeError`, escapes the loop, and
brings down the entire batch — the opposite of per-record isolation that this decision
promises. This was exactly the bug: `priority: null` in a single issue would lose all the others.

## 9. Custom exceptions cover only I/O edges

`errors/exceptions.py` defines `ExcelWriteError`, `NotificationError`, and
`StorageError`, raised in `integrations/`. `TaskValidationError` is defined
but the ETL **keeps** using `except (ValidationError, KeyError): continue`.

**Why:** changing the `continue` to a `raise` would change behavior — it would abort transformation on the first bad record, which is the opposite of decision 8. Exceptions go only where generic error propagation already existed all the way to
the `try/except` in `run()`, always with `raise ... from error` to preserve the original cause.

## 10. Packages don't reexport anything in `__init__.py`

Every `__init__.py` has only a docstring; modules are imported by full path.

**Why:** `config/settings.py` instantiates `Settings()` on import, which reads and validates the `.env`. With reexportation in `integrations/__init__.py`, importing
`ExcelWriter` would pull in `Notifier`, which would pull in settings — and would suddenly require a complete `.env` just to write to a local spreadsheet. Without reexportation, `ExcelWriter` is testable in isolation.
