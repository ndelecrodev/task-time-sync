# Data model

## Python models

Defined in `src/sop_pipeline/models/schemas.py`. They are Pydantic models: a Jira
issue that doesn't satisfy the contract is discarded with a `warning`, instead of
bringing down the entire execution.

### Employee identity

Since Jira identifies people by display name and Clockify by email, a mapping
layer normalizes both to a canonical name used as the join key.

**Editable source:** the workbook's `DIM_FUNCIONARIO` tab is where someone
corrects or adds employees by hand. Before each run, `EmployeeSyncService`
reads that tab with `ExcelReader` and writes the rows into Postgres'
`funcionarios` table via `PostgresClient.upsert_employee`, matched by either
`jira_email` or `clockify_email`. Rows whose email repeats earlier in the same
sheet are split off as duplicates and written to the `DUPLICADOS_REMOVIDOS`
tab instead of being synced.

**Runtime use:** `Settings.load_employee_registry` reads the already-synced
`funcionarios` table and builds an `EmployeeRegistry`, used by `EtlService` to
normalize `Task.assignee` (from Jira) and `TimeEntry.employee` (from Clockify)
to the canonical name.

**Unmapped employees:** if an employee is not found in the registry, they
receive a visible sentinel value (`"Unmapped employee: <email>"`) instead of
being dropped silently. This follows design decision #8: a single bad record
does not take down the whole run, and data quality issues are visible in the
report rather than hidden.

### `Task`

A normalized Jira issue. Upsert key: `task_id` (the Jira *key*).

| Field | Type | Origin in Jira |
|---|---|---|
| `task_id` | `str` | `key` |
| `title` | `str` | `fields.summary` (default `"No title"`) |
| `assignee` | `str` | `fields.assignee.displayName` |
| `priority` | `Priority` | `fields.priority.name` |
| `status` | `str` | `fields.status.name` |
| `area` | `str \| None` | custom field configured in `JIRA_CUSTOMFIELD_AREA` |
| `creation_date` | `date` | `fields.created` |
| `due_date` | `date \| None` | `fields.duedate` |
| `completion_date` | `date \| None` | `fields.resolutiondate` |
| `task_type` | `TaskType` | `fields.issuetype.name` |
| `creator` | `str \| None` | `fields.creator.displayName` |
| `update_date` | `date \| None` | `fields.updated` |
| `assignee_email` | `EmailStr \| None` | `fields.assignee.emailAddress` |
| `tags` | `list[str]` | `fields.labels` |

Computed fields (`@computed_field`), used by the alert rule and notification text — are **not** written to the spreadsheet, which has its own formulas:

| Field | Return |
|---|---|
| `days_remaining` | Days until deadline; negative if overdue; `None` if no deadline. |
| `is_late` | `"SIM"` / `"NÃO"` / `None`. |
| `deadline_status` | A value of `DeadlineStatus`. |

When Jira provides no assignee or area, the ETL uses the texts
`"There is no one responsible."` and `"There is no one area."` instead of discarding the
row — the task still appears in the report.

### `TimeEntry`

A Clockify time entry. Upsert key: `entry_id`.

| Field | Type | Origin in Clockify |
|---|---|---|
| `entry_id` | `str` | `id` |
| `employee` | `str` | email resolved from `userId` |
| `entry_date` | `date` | `timeInterval.start`, converted from UTC to America/Sao_Paulo |
| `hours` | `float` (≥ 0) | `timeInterval.duration` (ISO 8601) converted to hours |

Entries with null `duration` (timer still running) are ignored and collected in a
later execution.

### `TaskDetail`

The long description of a task, separated because it's a large text and goes in its own tab. Upsert key: `task_id`.

| Field | Type | Origin |
|---|---|---|
| `task_id` | `str` | `key` |
| `description` | `str \| None` | `fields.description`, flattened from ADF format to plain text |

### Enums

| Enum | Values |
|---|---|
| `Priority` | `Highest`, `High`, `Medium`, `Low`, `Lowest` |
| `TaskType` | `Bug`, `Task`, `Story`, `Epic`, `Subtask` |
| `DeadlineStatus` | `Concluído`, `Atrasado`, `Atenção`, `No prazo`, `Sem prazo` |

The values of `Priority` and `TaskType` are exactly the strings the Jira API returns. Those of `DeadlineStatus` are exactly the strings the `status_prazo` column formula produces in Excel. **None of these values can be translated** — only the enum member names.

---

## Mapping to the spreadsheet

Conventions for the `.xlsx` file: tab name in UPPERCASE, table name in lowercase, first column is always the ID used in upsert.

### Tabs written by Python

| Tab | Table | Columns | Written by |
|---|---|---|---|
| `BASE_TAREFAS` | `base_tarefas` | id, titulo, responsavel, area, prioridade, status, data_criacao, prazo, data_conclusao, **dias_restantes**, **atrasado**, **status_prazo**, tipo, criador, data_atualizacao | `save_tasks` |
| `DETALHES_TAREFA` | `detalhes_tarefa` | id, descricao | `save_details` |
| `BASE_HORAS` | `base_horas` | id, funcionario, data, horas | `save_hours` |
| `DIM_ETIQUETAS` | `dim_etiquetas` | id_etiqueta, nome_etiqueta | `save_tags` |
| `FATO_TAREFA_ETIQUETA` | `fato_tarefa_etiqueta` | id_tarefa, id_etiqueta | `save_tags` |

The three columns in **bold** are calculated by Excel formula; Python
only copies the formula text when creating a new row.

`Task` → `BASE_TAREFAS` is defined by the dict `TASK_COLUMN_MAP` in
`integrations/excel_writer.py`. The left side is the literal column header in the
spreadsheet (in Portuguese, so it's not translated); the right side is the attribute name in the model:

```python
TASK_COLUMN_MAP = {
    "id": "task_id",
    "titulo": "title",
    "responsavel": "assignee",
    ...
}
```

`DETALHES_TAREFA` and `BASE_HORAS` have short fixed layouts, so they are written by
column position, without going through the header map.

### Tabs that Python doesn't write

They exist in the file and are maintained manually or by formula.
`DIM_FUNCIONARIO` is the partial exception: nothing writes to it in code, but
`ExcelReader` reads it on every run to sync the registry into Postgres (see
"Employee identity" above).

| Tab | Table | Role |
|---|---|---|
| `DIM_FUNCIONARIO` | `dim_funcionario` | Employee registry (id_funcionario, nome, email), read by `ExcelReader`. |
| `DIM_FUNCIONARIO_AREA` | `dim_func_area` | Area dimension (id_area, nome_area). |
| `FATO_FUNCIONARIO_AREA` | `fato_funcionario` | N:N relationship between employee and area. |
| `CALCULOS` | `Tabela6` | Metrics per person (tasks, completed, overdue, hours, productivity). |
| `INDICADORES` | `Tabela7`, `Tabela10`, `Tabela11`, `Tabela12` | Consolidated KPIs from the dashboard. |

### Relationships

```
BASE_TAREFAS (id)
   │ 1:1
   ├──────────▶ DETALHES_TAREFA (id)
   │
   │ 1:N
   └──────────▶ FATO_TAREFA_ETIQUETA (id_tarefa) ──N:1──▶ DIM_ETIQUETAS (id_etiqueta)

DIM_FUNCIONARIO (id_funcionario)
   │ 1:N
   └──────────▶ FATO_FUNCIONARIO_AREA (id_funcionario) ──N:1──▶ DIM_FUNCIONARIO_AREA (id_area)

BASE_HORAS (funcionario) ──── links to DIM_FUNCIONARIO by email
```

## Postgres schema

Defined in `src/sop_pipeline/clients/postgres_client.py`. Table and column
names mirror the schema already deployed in Supabase and stay in Portuguese
for that reason; the upsert methods and `PostgresClient` itself are in
English.

| Table | Role | Upserted by |
|---|---|---|
| `funcionarios` | Employee identity, synced from `DIM_FUNCIONARIO`. | `upsert_employee` |
| `tarefas` | One row per Jira issue; `responsavel_id` is `NULL` when the employee could not be mapped. | `upsert_task` |
| `detalhes_tarefa` | Long-form task description. | `upsert_task_detail` |
| `horas` | One Clockify time entry; `funcionario_id` is `NULL` when the employee could not be mapped. | `upsert_time_entry` |
| `etiquetas` | Distinct tags assigned to tasks. | `upsert_tag_and_link` |
| `tarefa_etiqueta` | N:N association between `tarefas` and `etiquetas`. | `upsert_tag_and_link` |
