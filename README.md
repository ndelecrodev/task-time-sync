[English version](docs/en/readme.md)

# SOP Pipeline

Pipeline em Python que consolida **Jira** (tarefas) e **Clockify** (horas
apontadas) em uma planilha Excel hospedada no **Backblaze B2**, e avisa o time no
**Microsoft Teams** sobre tarefas com prazo próximo do vencimento.

A planilha não é um dump: ela é o produto final, com tabelas, fórmulas e abas de
indicadores. O pipeline faz *upsert* nas tabelas de dados e deixa as colunas
calculadas para as fórmulas do próprio Excel.

---

## Visão geral do fluxo

```
                         ┌──────────────┐
                         │ Backblaze B2 │
                         └──────┬───────┘
                       download │      ▲ upload
                                ▼      │
   ┌──────────┐            ┌───────────┴─────────────┐
   │ Jira API ├───issues──▶│                         │
   └──────────┘            │   EtlService            │
                           │   (valida + normaliza)  │
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
                              │ (regra de prazo)│     │  (Teams)   │
                              └─────────────────┘     └────────────┘
```

Detalhes em [`docs/architecture.md`](docs/architecture.md),
[`docs/data-model.md`](docs/data-model.md) e
[`docs/design-decisions.md`](docs/design-decisions.md).

---

## Arquitetura de pastas

| Caminho | Responsabilidade |
|---|---|
| `main.py` | Entrypoint fino; só chama `sop_pipeline.pipeline.run()`. |
| `src/sop_pipeline/pipeline.py` | Orquestra a execução: download → sync → upload → alertas. |
| `src/sop_pipeline/clients/` | Clientes HTTP das APIs externas (Jira, Clockify). Só falam HTTP; não interpretam regra de negócio. |
| `src/sop_pipeline/services/` | Regra de negócio: `EtlService` (transformação/validação) e `AlertService` (quem merece alerta). |
| `src/sop_pipeline/integrations/` | Saídas do pipeline: `ExcelWriter` (planilha), `Notifier` (Teams), `StorageClient` (B2). |
| `src/sop_pipeline/models/` | Modelos Pydantic (`Task`, `TimeEntry`, `TaskDetail`) e enums. |
| `src/sop_pipeline/config/` | Carregamento e validação das variáveis de ambiente. |
| `src/sop_pipeline/errors/` | Exceções de negócio do projeto. |
| `tests/` | Espelha a estrutura de `src/sop_pipeline/`. |
| `docs/` | Documentação de arquitetura, modelo de dados e decisões de design. |

---

## Instalação

Requer **Python 3.11+**.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

O `pip install -e .` é necessário: o pacote vive em `src/`, e é ele quem coloca
`sop_pipeline` no path.

---

## Configuração

Copie o arquivo de exemplo e preencha os valores:

```bash
cp .env.example .env    # Windows: copy .env.example .env
```

O `.env` **nunca** é versionado (está no `.gitignore`). Todo segredo do projeto
— token do Jira, chave do Clockify, webhooks do Teams, credenciais do B2 — vem de
lá; nada fica escrito no código.

As variáveis estão agrupadas por serviço dentro do `.env.example`, cada uma com um
comentário explicando onde obter o valor. Resumo:

| Grupo | Variáveis |
|---|---|
| Jira | `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_JQL`, `JIRA_CUSTOMFIELD_AREA` |
| Clockify | `API_KEY_CLOCKIFY`, `WORKSPACE_ID`, `WORKSPACE_NAME` |
| Regras de alerta | `ALERT_DAYS_LOW`, `ALERT_DAYS_MEDIUM`, `ALERT_DAYS_HIGH`, `HIGH_PRIORITIES`, `LOW_PRIORITIES` |
| Teams | `WEBHOOK_TI`, `WEBHOOK_SOP`, `WEBHOOK_IA`, `WEBHOOK_FRONT`, `WEBHOOK_DESIGN`, `WEBHOOK_DATA`, `WEBHOOK_BACK`, `WEBHOOK_NO_AREA` |
| Backblaze B2 | `B2_ENDPOINT_URL`, `B2_BUCKET_NAME`, `B2_APPLICATION_KEY`, `B2_KEY_ID`, `EXCEL_CLOUD_NAME`, `TEMP_EXCEL_PATH` |
| Observabilidade | `SENTRY_DSN`, `BETTERSTACK_HEARTBEAT_URL`, `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` |

### A consulta JQL (`JIRA_JQL`)

A variável `JIRA_JQL` define **quais issues o pipeline busca no Jira**. É uma
consulta JQL comum, no mesmo formato usado na busca avançada do Jira:

```
JIRA_JQL="project = SEUPROJETO ORDER BY created DESC"
```

O `JiraClient` envia essa string para o endpoint de busca e pagina o resultado até
o fim, então qualquer filtro válido de JQL funciona — por status, por responsável,
por data de atualização, etc.

O **valor real fica apenas no `.env` local** e não é publicado neste repositório,
porque a query contém o identificador do projeto Jira, que não deve ser público. O
`.env.example` traz apenas o formato genérico acima.

---

## Como rodar

Com o `.env` preenchido e o ambiente ativado:

```bash
python main.py
```

Ou, via o script instalado pelo `pip install -e .`:

```bash
sop-pipeline
```

Uma execução completa:

1. baixa a planilha do bucket B2 para o caminho de `TEMP_EXCEL_PATH`;
2. busca as issues do Jira e grava tarefas, etiquetas e descrições;
3. busca as horas de todos os usuários do Clockify e grava os apontamentos;
4. sobe a planilha atualizada de volta para o bucket;
5. envia os alertas de prazo para os canais do Teams;
6. dispara o heartbeat do Better Stack, confirmando que a execução terminou.

As etapas 2, 3 e 5 são isoladas entre si: se o Jira estiver fora do ar, as horas do
Clockify ainda são coletadas. Falhas são logadas e enviadas ao Sentry.

> A execução mexe em dados reais (bucket, planilha e canais do Teams). Para testar
> mudanças sem efeito colateral, trabalhe sobre uma cópia local da planilha.

---

## Desenvolvimento

```bash
pip install -e ".[dev]"

black src main.py tests      # formatação
pylint src main.py tests     # lint
pytest                       # testes
```

`black` e `pylint` são configurados no `pyproject.toml` (linha de 100 colunas).

---

## Licença

MIT — veja [LICENSE](LICENSE).
