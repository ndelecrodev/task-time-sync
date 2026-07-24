[Versão em Português](../../README.md)

# SOP Pipeline

A Python pipeline that consolidates **Jira** (tasks) and **Clockify** (logged hours) into an Excel spreadsheet hosted on **Backblaze B2** and a **Postgres** schema hosted on **Supabase**, and notifies the team on **Microsoft Teams** about tasks approaching their deadlines.

The spreadsheet is not a dump: it is the final product, with tables, formulas, and indicator tabs. The pipeline performs *upsert* operations on the data tables and leaves the calculated columns to Excel's own formulas. Postgres holds the same data relationally, with the employee registry as the source of truth shared between the spreadsheet and the database.

---

## Flow overview

```
                         ┌──────────────┐
                         │ Backblaze B2 │
                         └──────┬───────┘
                       download │      ▲ upload
                                ▼      │
                     ┌────────────────────────┐
                     │   .xlsx (local copy)   │
                     └──────┬──────────┬───────┘
                 DIM_FUNCIONARIO       │
                            ▼          │
                 ┌────────────────────┐│
                 │ EmployeeSyncService││
                 │   (ExcelReader)    ││
                 └─────────┬──────────┘│
                           │ upsert_employee
                           ▼           │
   ┌──────────┐      ┌───────────────┐│
   │ Jira API ├─────▶│               ││
   └──────────┘      │  EtlService   │◀┴── employee registry
   ┌──────────┐      │ (validates +  │
   │ Clockify ├─────▶│  normalizes)  │
   └──────────┘      └───────┬───────┘
                             │ Task / TimeEntry / TaskDetail
                      ┌──────┴───────┐
                      ▼              ▼
             ┌─────────────────┐  ┌─────────────────┐
             │   ExcelWriter   │  │  PostgresClient │
             │  (.xlsx local)  │  │   (Supabase)    │
             └────────┬────────┘  └─────────────────┘
                      │ tasks
                      ▼
             ┌─────────────────┐     ┌────────────┐
             │  AlertService   ├────▶│  Notifier  │
             │ (deadline rule) │     │  (Teams)   │
             └─────────────────┘     └────────────┘
```

`EmployeeSyncService` runs before the rest of the pipeline on every execution: it
reads the workbook's `DIM_FUNCIONARIO` tab (the editable source of employee
identity) and syncs the rows into the `funcionarios` table in Postgres. The
first row to use a given email is synced normally; later rows that repeat the
same email are diverted to the `DUPLICADOS_REMOVIDOS` tab instead of
overwriting the existing record. The `funcionarios` table also stores
`photo_url`, the employee photo consumed by the reporting dashboard. Only
after the sync does `EtlService` load the already-synced registry to
normalize Jira assignees and Clockify users to a shared canonical name.

Details in [`docs/en/architecture.md`](architecture.md),
[`docs/en/data-model.md`](data-model.md) and
[`docs/en/design-decisions.md`](design-decisions.md).

---

## Folder architecture

| Path | Responsibility |
|---|---|
| `main.py` | Thin entrypoint; only calls `sop_pipeline.pipeline.run()`. |
| `src/sop_pipeline/pipeline.py` | Orchestrates execution: download → employee sync → Jira/Clockify sync → upload → alerts. |
| `src/sop_pipeline/clients/` | Clients for the external sources: `JiraClient` and `ClockifyClient` (HTTP, no business logic) and `PostgresClient` (upserts into the Supabase schema). |
| `src/sop_pipeline/services/` | Business logic: `EtlService` (transformation/validation), `AlertService` (who deserves an alert), and `EmployeeSyncService` (syncs `DIM_FUNCIONARIO` into Postgres). |
| `src/sop_pipeline/integrations/` | Reads and writes the spreadsheet and external systems: `ExcelReader`, `ExcelWriter`, `excel_workbook.py`/`excel_table_helpers.py` (open/table helpers), `Notifier` (Teams), `StorageClient` (B2). |
| `src/sop_pipeline/models/` | Pydantic models (`Task`, `TimeEntry`, `TaskDetail`) and enums. |
| `src/sop_pipeline/config/` | `Settings` (environment variables and the Postgres engine) and `EmployeeRegistry`/`EmployeeMapping` (employee identity). |
| `src/sop_pipeline/errors/` | Project business exceptions. |
| `tests/` | Mirrors the structure of `src/sop_pipeline/`. |
| `docs/` | Architecture, data model, and design decision documentation. |

---

## Installation

Requires **Python 3.11+**.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

The `pip install -e .` is necessary: the package lives in `src/`, and it's what puts
`sop_pipeline` on the path.

---

## Configuration

Copy the example file and fill in the values:

```bash
cp .env.example .env    # Windows: copy .env.example .env
```

The `.env` is **never** versioned (it's in `.gitignore`). All project secrets
— Jira token, Clockify key, Teams webhooks, B2 credentials — come from there; nothing is
written in code.

Variables are grouped by service within `.env.example`, each one with a comment explaining where to get the value. Summary:

| Group | Variables |
|---|---|
| Jira | `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_JQL`, `JIRA_CUSTOMFIELD_AREA` |
| Clockify | `API_KEY_CLOCKIFY`, `WORKSPACE_ID`, `WORKSPACE_NAME` |
| Postgres / Supabase | `DATABASE_URL` |
| Alert rules | `ALERT_DAYS_LOW`, `ALERT_DAYS_MEDIUM`, `ALERT_DAYS_HIGH`, `HIGH_PRIORITIES`, `LOW_PRIORITIES` |
| Teams | `WEBHOOK_TI`, `WEBHOOK_SOP`, `WEBHOOK_IA`, `WEBHOOK_FRONT`, `WEBHOOK_DESIGN`, `WEBHOOK_DATA`, `WEBHOOK_BACK`, `WEBHOOK_NO_AREA` |
| Backblaze B2 | `B2_ENDPOINT_URL`, `B2_BUCKET_NAME`, `B2_APPLICATION_KEY`, `B2_KEY_ID`, `EXCEL_CLOUD_NAME`, `TEMP_EXCEL_PATH` |
| Observability | `SENTRY_DSN`, `BETTERSTACK_HEARTBEAT_URL`, `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` |

### The Postgres connection (`DATABASE_URL`)

`DATABASE_URL` uses the `postgresql+psycopg://user:password@host:port/database`
format and must point at Supabase's **transaction pooler** (port `6543`), not
the direct connection: the pooler supports IPv4, while Supabase's direct
connection only answers on IPv6, which breaks on networks and providers
without IPv6 support.

### The JQL query (`JIRA_JQL`)

The `JIRA_JQL` variable defines **which issues the pipeline fetches from Jira**. It is a common JQL query, in the same format used in Jira's advanced search:

```
JIRA_JQL="project = YOURPROJECT ORDER BY created DESC"
```

The `JiraClient` sends this string to the search endpoint and paginates through the results to the end, so any valid JQL filter works — by status, by assignee, by update date, etc.

The **actual value stays only in the local `.env`** and is not published to this repository, because the query contains the Jira project identifier, which should not be public. The `.env.example` brings only the generic format above.

---

## How to run

With `.env` filled and the environment activated:

```bash
python main.py
```

Or, via the script installed by `pip install -e .`:

```bash
sop-pipeline
```

A complete execution:

1. downloads the spreadsheet from the B2 bucket to the path in `TEMP_EXCEL_PATH`;
2. syncs `DIM_FUNCIONARIO` into the `funcionarios` table in Postgres;
3. fetches issues from Jira and writes tasks, labels, and descriptions to the spreadsheet and Postgres;
4. fetches hours from all Clockify users and writes time entries to the spreadsheet and Postgres;
5. uploads the updated spreadsheet back to the bucket;
6. sends deadline alerts to Teams channels;
7. fires the Better Stack heartbeat, confirming the execution completed.

Steps 3, 4, and 6 are isolated from each other: if Jira is down, Clockify hours are still collected. Failures are logged and sent to Sentry.

> Execution touches real data (bucket, spreadsheet, and Teams channels). To test changes without side effects, work on a local copy of the spreadsheet.

---

## Development

```bash
pip install -e ".[dev]"

black src main.py tests      # formatting
pylint src main.py tests     # lint
pytest                       # tests
```

`black` and `pylint` are configured in `pyproject.toml` (100-column line limit).

---

## License

MIT — see [LICENSE](../../LICENSE).
