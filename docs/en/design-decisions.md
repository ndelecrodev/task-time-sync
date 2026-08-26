# Design decisions

> Also published as a browsable site at
> https://ndelecrodev.github.io/task-time-sync-docs/

Record of non-obvious choices in the project and the reasoning behind them.

## 1. Upsert is done by ID, scanning the first column

`ExcelWriter._find_row` traverses column 1 of the table looking for the ID. If found, it overwrites the row; if not, it adds a new one.

**Why:** makes execution **idempotent**. The pipeline runs on schedule and
the fetch to the configured Space/folders usually brings back tasks that are already in the spreadsheet. Without
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

**Why:** a single task with a missing field can't cost the entire day's synchronization. The warning goes to Better Stack for later investigation.

**Trade-off:** a systematic error (for example, `CLICKUP_AREA_FIELD_ID`
pointing to a field that no longer exists) would show up as "all tasks were skipped", with execution apparently succeeding. That's why the discard is logged at
**ERROR** level and sent to Sentry, and the sync end log includes a count: `"ClickUp: N tasks fetched, M tasks written, K discarded"` — a `K` above
zero is a sign of structural trouble, typically a priority ClickUp sent that isn't in the mapping in `EtlService` (see decision 22).

**Caution when editing this `except`:** it explicitly lists `AttributeError` and
`TypeError` (the tuple `RECORD_ERRORS`) besides `ValidationError`/`KeyError`. Without
them, an unexpected `null` field from the task source throws `AttributeError`, escapes the loop, and
brings down the entire batch — the opposite of per-record isolation that this decision
promises. This was exactly the bug, back in the Jira era: `priority: null` in a single issue would lose all the others.

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

## 11. Excel status validation is a manual copy of the task source's workflow

The validation dropdown on `BASE_TAREFAS.status` uses the list `Backlog, To
Do, In Progress, Code Review, Testing, Done`, copied from the workflow
configured in Jira on 2026-07-22 — before the ClickUp migration (decision
22). The list still documents that behavior, but is now copied from
ClickUp's status workflow going forward.

**Why:** unlike `tipo` (`TaskType`, an enum validated in
`models/schemas.py`), `status` is free text coming straight from the task
source; there is no Python-side enum for that column. A fixed list in code
would run the same risk that already materialized with `tipo` (issue `QT-6`,
with `task_type="Function"` outside the enum, was silently dropped from the
report). That is why the status list does not live in code: it lives only
in Excel's dropdown validation, and has to be copied by hand from the source.

**Trade-off:** this validation only protects manual editing of the
spreadsheet. The pipeline overwrites `status` on every run with the value
straight from the task source, without going through Excel's validation, so
a new status shows up in the report even when it is not on the dropdown
list, but editing the cell by hand with a value outside the list is blocked.

**Caution when touching this:** if the status workflow changes (a status
renamed, added, or removed), this list has to be updated by hand in Excel.
There is no automatic sync between the two.

## 12. Employee identity moved from EMPLOYEES_JSON to a Postgres table, with Excel as the editable front end

Employee mapping used to live in an environment variable (`EMPLOYEES_JSON`),
a JSON blob read at `Settings` startup. Today `Settings.load_employee_registry`
reads the `funcionarios` table in Postgres, and `EmployeeDataSyncService` is what
keeps that table current, syncing it from the workbook's `DIM_FUNCIONARIO`
tab before every run.

**Why:** a JSON blob in an environment variable could only be edited by
whoever had access to the `.env` file and knew the right syntax; a single
typo broke the mapping for the whole employee roster. Moving the source
of truth to a relational table, editable through a spreadsheet the team
already uses day to day (`DIM_FUNCIONARIO`), removes the technical barrier
to keeping the registry current. Postgres also makes that registry
available to other consumers, such as the dashboard.

**Trade-off:** pipeline startup now depends on the database being
reachable. `load_employee_registry` propagates `SQLAlchemyError` when the
connection fails, something the local JSON blob never needed to account
for. Employee sync also became one more step at the start of every run,
one that has to complete before any name normalization.

## 13. SQLAlchemy was chosen as the ORM, not Core or raw psycopg

`PostgresClient` uses SQLAlchemy declarative classes (`Funcionarios`,
`Tarefas`, and so on) and `Session` objects, instead of writing SQL directly
with `psycopg` or using SQLAlchemy's own `Core` layer.

**Why:** part of the motivation is the project's learning goal. This
project is also a space to practice ORM usage on a real case, with upserts,
relationships, and constraints. As a side effect, the ORM also keeps SQL
out of the rest of the code: upserts in `PostgresClient` read as Python
attribute assignment (`existing.canonical_name = ...`) instead of hand-built
`UPDATE ... SET` statements.

**Trade-off:** every upsert opens its own `Session` and runs a `SELECT`
before the `INSERT`/`UPDATE` (see `upsert_employee`, `upsert_task`, and so
on), which is less efficient than a native Postgres `INSERT ... ON
CONFLICT`. For the pipeline's current volume (a few hundred rows per run)
that is not a problem; it is worth revisiting if volume grows.

## 14. `person.area` in the dashboard is derived from task areas, not from a per-employee area table in Postgres

Excel has `FATO_FUNCIONARIO_AREA`, a dedicated N:N relationship between
employee and area (see decision 4). The Postgres schema has no equivalent:
there is no `funcionario_area` table. When the dashboard needs a person's
area, it derives that value from the areas of the tasks assigned to them in
`tarefas.area`.

**Why:** `FATO_FUNCIONARIO_AREA` originated in Excel for the
spreadsheet-based dashboard; replicating that table while migrating
indicators to Postgres would mean keeping one more registry in sync,
without a need today that task area doesn't already cover. In practice,
whoever works mostly on tasks in an area also belongs to it.

**Trade-off:** an employee with no assigned tasks in a period has no
derivable area in Postgres, unlike Excel, where a person's area is
registered explicitly. If that gap starts to matter, the path is adding a
`funcionario_area` table in Postgres mirroring `FATO_FUNCIONARIO_AREA`.

**Update:** the `funcionario_area` table was created in Postgres (see
decision 17), but to sync `FATO_FUNCIONARIO_AREA` through
`EmployeeDataSyncService.sync_areas`, not to feed the dashboard's
`person.area` described above. The trade-off's gap ("employee with no tasks
has no derivable area") still holds as long as the dashboard doesn't query
that table.

## 15. The alert shows "Tarefa atrasada há N dia(s)" instead of `days_remaining`'s negative number

`Task.days_remaining` is negative by design for overdue tasks (decision 2).
`Notifier._build_message`, though, never exposes that negative number in
the text: when `days_remaining < 0`, it swaps in the label "Tarefa atrasada
há" and shows `abs(days_remaining)`.

**Why:** "-3 dias restantes" is a phrase that makes the reader do the
mental math (negative means overdue, and by how many days). "Tarefa
atrasada há 3 dia(s)" communicates the same information without that extra
step, for text that gets read quickly inside a Teams notification.

**Caution when touching this:** the sign flip (`abs()`) and the label swap
have to move together. Changing one without the other produces a message
like "Dias restantes: -3 dia(s)" or "Tarefa atrasada há -3 dia(s)", both
incoherent with the rest of the text.

## 16. `EmployeeSyncService` became `EmployeeDataSyncService`, with a generic `read_sheet_as_dicts` instead of three near-identical reads

Employee sync gained a second responsibility: besides `DIM_FUNCIONARIO`,
`EmployeeDataSyncService.sync_areas` now also reads `DIM_FUNCIONARIO_AREA`
and `FATO_FUNCIONARIO_AREA`. To support that, `ExcelReader` gained a generic
method, `read_sheet_as_dicts(file_path, sheet_name, table_name)`, that opens
the workbook, finds the table, and builds the list of row dicts.
`read_employees`, `read_dim_employee_area`, and `read_fato_employee_area` all
call this helper, each one only fixing the sheet and table name it reads.

**Why:** the three reads did the same sequence of steps (open workbook, find
table, map columns, iterate rows), varying only the sheet and table. Keeping
three copies of that logic would create three places to fix the same bug if
the read format changed. The service's name also changed from
`EmployeeSyncService` to `EmployeeDataSyncService` because the class stopped
syncing identity alone; keeping the old name would now be misleading.

**Trade-off:** nothing notable. `read_sheet_as_dicts` covers exactly the same
contract `read_employees` already had before the extraction; this is a
method reorganization, not a behavior change.

## 17. Employee-area link uses two Postgres tables (`areas` + `funcionario_area`), not a text column

`upsert_area_and_link` resolves or creates a row in `Area` (table `areas`),
then resolves or creates the association row in `FuncionarioArea` (table
`funcionario_area`, composite key `funcionario_id` + `area_id`), instead of
writing the area name directly into a column on `Funcionarios`.

**Why:** same reasoning as decision 4 for `etiquetas`/`tarefa_etiqueta`: an
employee can work in more than one area, so the relationship is N:N, not
N:1. A text column on `funcionarios` would only hold one area per employee
and would require duplicating the area name on every row, with no dimension
to group by area later.

## 18. Tasks missing from the ClickUp fetch are archived by timestamp, not deleted

`PostgresClient.archive_missing_tasks` runs at the end of `sync_clickup` and
sets `tarefas.arquivada_em = now()` on every row whose `task_id` didn't show
up in the current run's fetch (`ClickUpClient.fetch_tasks(CLICKUP_TEAM_ID,
CLICKUP_SPACE_ID)`, already filtered by `pipeline._filter_allowed_folders`)
and that wasn't already archived; the row is never deleted. Before the
ClickUp migration (decision 22), this same logic ran at the end of
`sync_jira` against `JIRA_JQL`.

**Why:** follows the same philosophy as decision 8, never discard silently.
A transient ClickUp failure or a misconfigured `CLICKUP_SPACE_ID`/
`CLICKUP_FOLDER_IDS` can make the returned task list come back empty or
incomplete; without timestamp archiving, a `DELETE` at that point would wipe
out tasks that still exist in ClickUp, and the next successful
`sync_clickup` would have no way to recover what was lost. Marking with a
timestamp instead of deleting keeps the problem visible and reversible.

**Trade-off:** Caution when touching this: the set used to decide what to
archive must be `all_ids_from_clickup` (every `id` the ClickUp fetch
returned once already narrowed down to the allowed folders, but before any
`Task` validation), not `valid_ids` (the tasks that already passed Pydantic
validation, decision 8). Using `valid_ids` would archive a task discarded by
validation (an out-of-enum `priority`, for example) as if it had disappeared
from ClickUp, even though it is still active there, conflating "didn't come
back in this fetch" with "came back, but failed validation." That was, in
fact, an early version's bug (then named `all_ids_from_jira`), fixed before
it reached production.

## 19. Archiving is also marked in the spreadsheet, in a column that only ever receives that one write

`BASE_TAREFAS` gained an `arquivada_em` column, mirroring the column of the
same name in `tarefas` (decision 18). `ExcelWriter.mark_archived_tasks` runs
at the end of `sync_clickup`, right after `archive_missing_tasks`, and fetches
the already-archived tasks through `PostgresClient.get_archived_tasks` to
write the archive date into the spreadsheet.

**Why:** before this change, an archived task was only flagged in Postgres;
whoever opened the spreadsheet had no way to tell that a `BASE_TAREFAS` row
belonged to a task that had already disappeared from ClickUp, short of
querying the database directly. Writing the same flag into the spreadsheet
makes that information visible to anyone working from Excel alone.

**Trade-off:** `mark_archived_tasks` writes only the `arquivada_em` cell; it
never calls `_write_task_row` or any other path that would rewrite
`titulo`, `status`, `prazo`, or any other field on the row. This is
deliberate: an archived task no longer receives updates from ClickUp, so its
other fields must stay frozen at the last real value they held before the
task dropped out of the fetch, not get overwritten or cleared. If a
`task_id` coming from Postgres has no matching row in `BASE_TAREFAS` (it
shouldn't, since the task was written there before being archived), the
method skips it instead of raising.

## 20. `HISTORICO_PROGRESSO.percentual` is written as a value, not an Excel formula

`ExcelWriter.save_progress_snapshot` computes `percentual = concluidas /
total_tarefas` in Python and writes the result into the cell. Unlike
`dias_restantes`, `atrasado`, and `status_prazo` (decision 2), this column
is not left out of what Python writes — it is always a static value.

**Why:** decision 2 exists because those columns describe the *current*
state of a task that is still open, and so they need to recalculate on
their own every time someone opens the spreadsheet. `HISTORICO_PROGRESSO`
is the opposite case: each row is a snapshot of progress on a specific date
(`snapshot_date`), and the entire reason that sheet exists is to preserve
that snapshot. If `percentual` were a formula, it would recompute against
today's totals every time the file is opened, and every past row would
silently start lying about what progress actually was on the date it
represents — erasing the very history the sheet is meant to keep. Writing
the value at snapshot time is what makes the row a genuine historical
record instead of one more view of the present.

## 21. `EtlService._build_task` falls back to `EmployeeRegistry.get_registered_email` when the task source omits the assignee's email

When an assignee actually exists but comes without an email, `_build_task`
first normalizes the raw identifier (today ClickUp's `username`; it used to
be Jira's `displayName`) to the canonical name via
`normalize_employee_identifier`, and only then calls
`EmployeeRegistry.get_registered_email` with that already-canonicalized
name, never with the raw identifier. The fallback does not run on the
no-assignee branch (an empty assignee list), where `assignee` is the
`NO_RESPONSIBLE` sentinel — calling `get_registered_email` with a sentinel
as if it were a person's name makes no sense and must never happen. The
method was named `get_jira_email` until the ClickUp migration (decision
22); it was renamed because it now resolves an employee's registered email
regardless of the task source, not just Jira's.

**Why:** per-user email-visibility privacy settings — a GDPR-era change on
Jira Cloud, an equivalent possibility on ClickUp — can leave the assignee's
email null even for someone correctly assigned and visible everywhere else
in the tool. Using the already-canonicalized name instead of the source's
raw identifier is essential: names registered in `DIM_FUNCIONARIO` can
differ from what the task source returns, and that exact mismatch caused an
earlier bug involving an employee named "Miguel Felix Cardozo de Tomy" —
looking up the raw name here would hit the same problem. This makes the
employee registry (`DIM_FUNCIONARIO` / `EmployeeRegistry`) a second
source of truth for an employee's email, specifically so outbound Teams
@mentions still have one when the task source itself won't provide it.

## 22. The task source migrated from Jira to ClickUp only in the extraction layer; `Task` stayed the contract

`clients/jira_client.py` was replaced by `clients/clickup_client.py`, and
`EtlService._build_task`/`transform_details` were rewritten for ClickUp's
shape (a list of assignees, `custom_fields` as a list, millisecond
timestamps, and so on — see [`data-model.md`](data-model.md)). Clockify, the
Excel output, the Postgres output, Teams alerts, employee identity
resolution, and task archiving stayed exactly as they were: none of those
modules knew Jira directly, only `Task` (`models/schemas.py`), and `Task`
did not change.

**Why:** the project switched task-management tools, but the Postgres
schema, the spreadsheet's formulas and tabs, and the Teams alert flows have
no reason to change because of that — they are all consumers of the `Task`
model, not of the source API. Keeping `Task` intact (the single most
important decision of this migration) turned a vendor swap into a change
contained to the extraction layer: only the HTTP client and the dict→`Task`
mapping needed rewriting. This confirms, in practice, the design described
in the [architecture](architecture.md#layers) decision: "no client knows
about `ExcelWriter`, and `ExcelWriter` doesn't know about Jira" — now reads
the same with "Jira" swapped for "ClickUp".

Identifiers that are **data**, not code — the `funcionarios.jira_email`
column in Postgres, the `jira_email` header on the Excel `DIM_FUNCIONARIO`
tab, and the `EmployeeMapping.jira_email` field that mirrors both — were
initially kept under their old name, for the same reason as decision 6:
renaming them would break the runtime match against the schema already
deployed in Supabase and against the real spreadsheet, with no import error
to warn about it. Only the `EmployeeRegistry.get_jira_email` method was
renamed at that point (decision 21), because it is code, not data.

**Later rename of `jira_email` to `clickup_email`:** in a follow-up task, the
three data identifiers above were in fact renamed — the `funcionarios.jira_email`
column and its `check_email_jira` check constraint in Postgres, the
`jira_email` header on the Excel `DIM_FUNCIONARIO` tab, and the
`EmployeeMapping.jira_email` field, all became `clickup_email` /
`check_email_clickup`. The reasoning: unlike the code rename in decision 21
(deferred until the symbol itself stopped making sense), keeping a data
identifier named `jira_email` indefinitely — now that the project no longer
talks to Jira at all — was the kind of name that needlessly confuses the
next person reading the schema, with no real compatibility benefit: the
column and header could be renamed atomically and deliberately (a Postgres
schema migration, a manual header update in Excel via Claude for Excel, and
the matching Python-side field), unlike an uncoordinated silent rename. The
chosen name, `clickup_email`, follows the convention already used by the
sibling `clockify_email` column — naming after the concrete integrated
system rather than a generic term like "task_source_email" — and matches
the pattern of the `CLICKUP_*` identifiers already present in `Settings` and
the `clients/clickup_client.py` module.

**Multiple assignees, and the @mention trade-off:** unlike Jira, ClickUp
allows more than one assignee per task. Each assignee is normalized
individually and the canonical names are joined into `Task.assignee`
(`"Nicolas Delecrode, Daniel Nogueira"`), a call made by the project owner.
But `Task.assignee_email` is still a single email — it feeds one Teams
@mention, and an @mention can't target several people at once — so only the
**first** assignee's email is used. A task with multiple assignees always
notifies only the first one by email; the rest still show up in the report
(the spreadsheet's `responsavel` column and `tarefas` in Postgres) but don't
get a direct @mention.

**The `task_type` trade-off:** ClickUp has no direct equivalent of Jira's
`issuetype` — the only candidate, `custom_item_id`, only exists when the
workspace uses ClickUp's paid Custom Task Types feature, which this
workspace does not. Since `Task.task_type` is a required field and `Task`
couldn't change, every task from ClickUp gets a fixed `TaskType.TASK`, a
call made by the project owner. This means the report loses the
Bug/Story/Epic/Subtask distinction Jira used to provide; if the workspace
ever adopts Custom Task Types, `_build_task` will need revisiting to map
`custom_item_id` instead of using the fixed value.

**The null-priority trade-off:** ClickUp represents "no priority" as
`priority: null` in the payload (instead of Jira's object with an absent
`name`). The mapping (`urgent`→Highest, `high`→High, `normal`→Medium,
`low`→Low) only applies when `priority` isn't null; when it is,
`Task.priority` is left unset and Pydantic validation fails, discarding the
task through the same path that already existed (decision 8) — the same
behavior a priority-less Jira issue always had.

## 23. Synced ClickUp folders are an explicit allowlist, not "every folder in the Space"

`ClickUpClient.fetch_tasks` fetches the whole Space configured in
`CLICKUP_SPACE_ID` (`GET /team/{team_id}/task` with `space_ids[]=...`),
which includes any folder that exists there, of any kind.
`pipeline._filter_allowed_folders` runs right after and drops every task
whose `folder.id` isn't in `CLICKUP_FOLDER_IDS` — a fixed list, configured
in `.env`, of the folder IDs that actually represent a "turma" (today
"Primeiro Ano" and "Segundo Ano") — before `EtlService` ever sees those
tasks.

**Why:** the obvious alternative would be to automatically sync every
folder that exists in the Space, with no fixed list. That was deliberately
rejected: a folder unrelated to a "turma" could be created in the same
Space later — an internal team-planning folder, say, or a temporary
experiment — and nothing about it guarantees its tasks follow the same
contract (`turma`, `area`, priorities) the rest of the pipeline expects.
Without the allowlist, that folder would start feeding the pipeline, Teams
alerts, and reports just by having been created in the Space, without
anyone having made that call on purpose.

This is the same "never change scope silently" philosophy already present
in this project, just pointed the other way: decision 8 (never silently
discard a record) and decision 18 (never silently delete an archived task)
guard against **losing** data without warning; the folder allowlist guards
against **gaining** scope without warning. In both cases, the principle is
that a scope change — in or out — should be a deliberate act, not a side
effect of something that happened in another system (Jira before, ClickUp
now).

**Trade-off:** when a new turma is actually created (say, "Terceiro Ano"),
syncing it requires a manual action: someone has to add the new folder's ID
to `CLICKUP_FOLDER_IDS` and let the scheduled run pick it up. There's no
automatic discovery of new turmas. That friction is deliberate — it's the
price of never including a folder by accident.

## 24. `area` moved from a manually-filled `drop_down` custom field to a fixed ClickUp-list mapping

Previously, `area` came from a ClickUp `drop_down` custom field
(`CLICKUP_AREA_FIELD_ID`), filled in per task by whoever created or managed
it. That mechanism was removed entirely: `_build_task` now reads
`task["list"]["id"]` and resolves it against `EtlService.CLICKUP_LIST_TO_AREA`,
a fixed dict with one entry per ClickUp list that represents a course subject
(e.g. `"901715802295": "front-end"` for the "Desenvolvimento 1" list). When a
list's `id` isn't in the dict, the result is `NO_AREA`, the same sentinel
previously used for the unfilled field.

**Why:** the custom field depended on someone remembering to fill it in on
every task, and in practice almost nobody did — the overwhelming majority of
tasks reached the report as `NO_AREA`, defeating the point of having a
per-task area at all. The ClickUp list a task already lives in, by contrast,
maps 1:1 onto a course subject and is data the task already carries regardless
— it needs no extra per-task human action. Moving area resolution onto that
data removes the source of the problem instead of reminding people to fill in
a field.

Why a fixed Python dict rather than an `.env` setting, unlike
`CLICKUP_FOLDER_IDS`: `CLICKUP_LIST_TO_AREA` is a curriculum/business rule
tied to this specific program's list structure — which lists exist and which
subject each maps to changes about as rarely as the curriculum itself, and is
part of the pipeline's business logic, not a credential or an
environment-varying scope. `CLICKUP_FOLDER_IDS` stays in `.env` because,
unlike this, it genuinely varies by what's being synced (which turmas are
currently active), which is exactly what an environment variable exists to
capture.

**Trade-off:** the same category of deliberate friction as decision 23. A new
list created in an already-allowed folder, without a matching entry in
`CLICKUP_LIST_TO_AREA`, silently falls back to `NO_AREA` until someone updates
the dict. There's no automatic area discovery from the list's name or any
other signal — updating the mapping is a manual, conscious act, the same way
the folder allowlist works: changing what the pipeline recognizes should be
deliberate, not a side effect of a new list showing up in ClickUp.

## 25. "Segundo Ano" tasks are excluded from Teams alerts, but stay in everything else in the pipeline

`AlertService.tasks_to_alert` drops every task whose `turma` is
`"Segundo Ano"` before it ever evaluates that task's deadline window — the
comparison lives in `AlertService.EXCLUDED_TURMA`, a named constant, not a
bare literal buried in the filter. The rule is a product-owner decision:
"Segundo Ano" tasks must not generate a Teams alert, period. No further
justification is assumed here beyond that choice.

**Why the exclusion lives in `AlertService`, rather than simply not fetching
"Segundo Ano" tasks at all:** unlike decision 23 (the ClickUp folder
allowlist), where tasks from folders outside `CLICKUP_FOLDER_IDS` shouldn't
exist in the system at all and are therefore cut at the fetch step, here the
data is still needed everywhere else — Excel, Postgres, and the dashboard all
need to show "Segundo Ano" tasks normally; only the Teams alert path is
affected. Cutting at the fetch step (the way the folder allowlist does) would
remove the turma from the whole system, not just from Teams — wrong for this
rule. The exclusion stays isolated inside `AlertService`, so `sync_clickup`,
`ExcelWriter`, and `PostgresClient` are unchanged, exactly as they were.

**Trade-off:** if a third turma ever needs the same rule (never alert on
Teams), `EXCLUDED_TURMA` would need to become a collection instead of a single
string — today it's deliberately the simplest shape that fits exactly the
present case.
