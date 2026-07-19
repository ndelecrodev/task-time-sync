[Versão em Português](../../README.md)

# SOP Pipeline

A Python pipeline that consolidates **Jira** (tasks) and **Clockify** (logged hours) into an Excel spreadsheet hosted on **Backblaze B2**, and notifies the team on **Microsoft Teams** about tasks approaching their deadlines.

The spreadsheet is not a dump: it is the final product, with tables, formulas, and indicator tabs. The pipeline performs *upsert* operations on the data tables and leaves the calculated columns to Excel's own formulas.

---

## Flow overview

```
                         ┌──────────────┐
                         │ Backblaze B2 │
                         └──────┬───────┘
                       download │      ▲ upload
                                ▼      │
   ┌──────────┐            ┌───────────┴─────────────┐
   │ Jira API ├───issues──▶│                         │
   └──────────┘            │   EtlService            │
                           │   (validates + normalizes)  │
   ┌──────────┐            │                         │
   │ Clockify ├──entries──▶│                         │
   └──────────┘            └───────────┬─────────────┘
                                       │ Task / TimeEntry / TaskDetail
                                       ▼
                              ┌─────────────────┐
                              │   ExcelWriter   │
                              │  (.xlsx local)  │
                              └────────┬────────┘
                                       │ tasks
                                       ▼
                              ┌─────────────────┐     ┌────────────┐
                              │  AlertService   ├────▶│  Notifier  │
                              │ (deadline rule) │     │  (Teams)   │
                              └─────────────────┘     └────────────┘
```

Details in [`docs/en/architecture.md`](architecture.md),
[`docs/en/data-model.md`](data-model.md) and
[`docs/en/design-decisions.md`](design-decisions.md).

---

## Folder architecture

| Path | Responsibility |
|---|---|
| `main.py` | Thin entrypoint; only calls `sop_pipeline.pipeline.run()`. |
| `src/sop_pipeline/pipeline.py` | Orchestrates execution: download → sync → upload → alerts. |
| `src/sop_pipeline/clients/` | HTTP clients for external APIs (Jira, Clockify). Only speak HTTP; do not interpret business logic. |
| `src/sop_pipeline/services/` | Business logic: `EtlService` (transformation/validation) and `AlertService` (who deserves an alert). |
| `src/sop_pipeline/integrations/` | Pipeline outputs: `ExcelWriter` (spreadsheet), `Notifier` (Teams), `StorageClient` (B2). |
| `src/sop_pipeline/models/` | Pydantic models (`Task`, `TimeEntry`, `TaskDetail`) and enums. |
| `src/sop_pipeline/config/` | Environment variables loading and validation. |
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
| Alert rules | `ALERT_DAYS_LOW`, `ALERT_DAYS_MEDIUM`, `ALERT_DAYS_HIGH`, `HIGH_PRIORITIES`, `LOW_PRIORITIES` |
| Teams | `WEBHOOK_TI`, `WEBHOOK_SOP`, `WEBHOOK_IA`, `WEBHOOK_FRONT`, `WEBHOOK_DESIGN`, `WEBHOOK_DATA`, `WEBHOOK_BACK`, `WEBHOOK_NO_AREA` |
| Backblaze B2 | `B2_ENDPOINT_URL`, `B2_BUCKET_NAME`, `B2_APPLICATION_KEY`, `B2_KEY_ID`, `EXCEL_CLOUD_NAME`, `TEMP_EXCEL_PATH` |
| Observability | `SENTRY_DSN`, `BETTERSTACK_HEARTBEAT_URL`, `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` |

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
2. fetches issues from Jira and writes tasks, labels, and descriptions;
3. fetches hours from all Clockify users and writes time entries;
4. uploads the updated spreadsheet back to the bucket;
5. sends deadline alerts to Teams channels;
6. fires the Better Stack heartbeat, confirming the execution completed.

Steps 2, 3, and 5 are isolated from each other: if Jira is down, Clockify hours are still collected. Failures are logged and sent to Sentry.

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
