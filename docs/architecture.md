# Arquitetura

## Fluxo de uma execução

Uma execução (`sop_pipeline.pipeline.run`) é uma sequência linear com três etapas
de sincronização isoladas entre si.

```
 1. StorageClient.download_file
    B2 ──────────────────────────────▶ planilha_temp.xlsx (disco local)

 2. sync_jira
    JiraClient.fetch_tasks(JIRA_JQL)          ── paginação por nextPageToken
        │  list[dict] cru
        ▼
    EtlService.transform_tasks    ─▶ list[Task]
    EtlService.transform_details  ─▶ list[TaskDetail]
        │
        ▼
    ExcelWriter.save_tasks    ─▶ aba BASE_TAREFAS
    ExcelWriter.save_tags     ─▶ abas DIM_ETIQUETAS + FATO_TAREFA_ETIQUETA
    ExcelWriter.save_details  ─▶ aba DETALHES_TAREFA

 3. sync_clockify
    ClockifyClient.list_users
        │  para cada usuário:
        ▼
    ClockifyClient.fetch_time_entries(user_id)  ── paginação por header Last-Page
        │  list[dict] cru
        ▼
    EtlService.transform_time_entries ─▶ list[TimeEntry]
        │
        ▼
    ExcelWriter.save_hours    ─▶ aba BASE_HORAS

 4. StorageClient.upload_file
    planilha_temp.xlsx ──────────────▶ B2   (sobrescreve o objeto)

 5. process_alerts (usa as Tasks da etapa 2)
    AlertService.tasks_to_alert  ─▶ list[Task] dentro da janela de alerta
        │
        ▼
    Notifier.send_alert ─▶ POST no webhook do Teams da área da tarefa

 6. Heartbeat
    GET BETTERSTACK_HEARTBEAT_URL   ── só é alcançado se o upload deu certo
```

## Camadas

| Camada | Módulos | Regra |
|---|---|---|
| **Clients** | `clients/jira_client.py`, `clients/clockify_client.py` | Só falam HTTP e paginação. Devolvem `dict` cru, sem interpretar nada. |
| **Services** | `services/etl_service.py`, `services/alert_service.py` | Regra de negócio pura. Não fazem I/O de rede nem de arquivo. |
| **Integrations** | `integrations/excel_writer.py`, `notifier.py`, `storage_client.py` | Saídas do pipeline. Cada uma conhece um destino externo. |
| **Models** | `models/schemas.py` | Contrato entre as camadas. Validação via Pydantic. |
| **Config** | `config/settings.py` | Único ponto que lê o ambiente. |
| **Errors** | `errors/exceptions.py` | Exceções de negócio, todas sob `SopPipelineError`. |

A dependência é sempre para dentro: `pipeline` → `integrations`/`services` →
`models`/`config`. Nenhum client conhece o `ExcelWriter`, e o `ExcelWriter` não
conhece o Jira.

## Isolamento de falhas

As três etapas de sincronização rodam cada uma no seu próprio `try/except` dentro
de `run()`. Uma indisponibilidade do Jira não impede a coleta das horas do
Clockify, e vice-versa. Cada falha é logada e enviada ao Sentry, e a execução
segue.

Se o `sync_jira` falha, o passo de alertas é **pulado** com um `warning` explícito,
em vez de rodar contra uma lista vazia. A distinção importa: "o Jira não respondeu"
não é a mesma coisa que "o Jira não tem tarefas em risco", e tratar as duas
situações igual fazia uma execução quebrada parecer limpa no log.

## Observabilidade

| Ferramenta | Papel |
|---|---|
| **Sentry** | Recebe as exceções capturadas nas três etapas, com stack trace. |
| **Better Stack (logs)** | `LogtailHandler` é anexado ao `logging` raiz; todos os `logger.info/warning/error` sobem para lá. |
| **Better Stack (heartbeat)** | Um `GET` no fim da execução. Fica **fora** de qualquer `try/except` de propósito: se o upload da planilha falhar, a linha nunca é alcançada e o Better Stack acusa a execução perdida. Colocá-lo dentro de um `try` marcaria como sucesso uma execução que não entregou nada. |

## Concorrência e agendamento

O pipeline é single-threaded e pensado para rodar de forma agendada (cron, GitHub
Actions, etc.). **Duas execuções simultâneas não são seguras**: ambas baixariam a
mesma planilha, escreveriam em cópias locais distintas e a última a subir
sobrescreveria a outra. O bucket não é usado com lock.
