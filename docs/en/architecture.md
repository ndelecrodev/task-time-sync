# Architecture

## Execution flow

An execution (`sop_pipeline.pipeline.run`) is a linear sequence with three isolated synchronization steps.

```
 1. StorageClient.download_file
    B2 ──────────────────────────────▶ planilha_temp.xlsx (local disk)

 2. sync_jira
    JiraClient.fetch_tasks(JIRA_JQL)          ── pagination by nextPageToken
        │  raw list[dict]
        ▼
    EtlService.transform_tasks    ─▶ list[Task]
    EtlService.transform_details  ─▶ list[TaskDetail]
        │
        ▼
    ExcelWriter.save_tasks    ─▶ tab BASE_TAREFAS
    ExcelWriter.save_tags     ─▶ tabs DIM_ETIQUETAS + FATO_TAREFA_ETIQUETA
    ExcelWriter.save_details  ─▶ tab DETALHES_TAREFA

 3. sync_clockify
    ClockifyClient.list_users
        │  for each user:
        ▼
    ClockifyClient.fetch_time_entries(user_id)  ── pagination by header Last-Page
        │  raw list[dict]
        ▼
    EtlService.transform_time_entries ─▶ list[TimeEntry]
        │
        ▼
    ExcelWriter.save_hours    ─▶ tab BASE_HORAS

 4. StorageClient.upload_file
    planilha_temp.xlsx ──────────────▶ B2   (overwrites the object)

 5. process_alerts (uses Tasks from step 2)
    AlertService.tasks_to_alert  ─▶ list[Task] within alert window
        │
        ▼
    Notifier.send_alert ─▶ POST to Teams webhook for the task's area

 6. Heartbeat
    GET BETTERSTACK_HEARTBEAT_URL   ── only reached if upload succeeded
```

## Layers

| Layer | Modules | Rule |
|---|---|---|
| **Clients** | `clients/jira_client.py`, `clients/clockify_client.py` | Only speak HTTP and pagination. Return raw `dict`, without interpreting anything. |
| **Services** | `services/etl_service.py`, `services/alert_service.py` | Pure business logic. No network or file I/O. |
| **Integrations** | `integrations/excel_writer.py`, `notifier.py`, `storage_client.py` | Pipeline outputs. Each knows one external destination. |
| **Models** | `models/schemas.py` | Contract between layers. Validation via Pydantic. |
| **Config** | `config/settings.py` | Single point that reads the environment. |
| **Errors** | `errors/exceptions.py` | Business exceptions, all under `SopPipelineError`. |

Dependencies flow inward: `pipeline` → `integrations`/`services` →
`models`/`config`. No client knows about `ExcelWriter`, and `ExcelWriter` doesn't
know about Jira.

## Failure isolation

The three synchronization steps each run in their own `try/except` inside
`run()`. Jira unavailability doesn't prevent Clockify hours collection, and vice versa. Each failure is logged and sent to Sentry, and execution continues.

If `sync_jira` fails, the alert step is **skipped** with an explicit `warning`, instead of running against an empty list. The distinction matters: "Jira didn't respond"
is not the same as "Jira has no at-risk tasks", and treating both situations equally would make a broken execution look clean in the log.

## Observability

| Tool | Role |
|---|---|
| **Sentry** | Receives exceptions caught in the three steps, with stack trace. |
| **Better Stack (logs)** | `LogtailHandler` is attached to the root `logging`; all `logger.info/warning/error` go there. |
| **Better Stack (heartbeat)** | A `GET` at the end of execution. Intentionally **outside** any `try/except`: if the spreadsheet upload fails, the line is never reached and Better Stack flags the missing execution. Wrapping it in a `try` would mark a failed execution as successful. |

## Concurrency and scheduling

The pipeline is single-threaded and designed to run on a schedule (cron, GitHub
Actions, etc.). **Two simultaneous executions are not safe**: both would download the
same spreadsheet, write to separate local copies, and the last one to upload would
overwrite the other. The bucket is not used with locks.
