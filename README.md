[English version](docs/en/readme.md)

# Task Time Sync

Pipeline em Python que consolida **ClickUp** (tarefas) e **Clockify** (horas
apontadas) em uma planilha Excel hospedada no **Backblaze B2** e em um schema
**Postgres** hospedado no **Supabase**, e avisa o time no **Microsoft Teams**
sobre tarefas com prazo próximo do vencimento.

A planilha não é um dump: ela é o produto final, com tabelas, fórmulas e abas de
indicadores. O pipeline faz *upsert* nas tabelas de dados e deixa as colunas
calculadas para as fórmulas do próprio Excel. O Postgres guarda os mesmos dados
de forma relacional, com o cadastro de colaboradores como fonte de verdade
compartilhada entre a planilha e o banco.

Documentação completa (arquitetura, modelo de dados, decisões de design) está
disponível em https://ndelecrodev.github.io/task-time-sync-docs/

---

## Visão geral do fluxo

```
                         ┌──────────────┐
                         │ Backblaze B2 │
                         └──────┬───────┘
                       download │      ▲ upload
                                ▼      │
                     ┌────────────────────────┐
                     │   .xlsx (cópia local)   │
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
   │ ClickUp  ├─────▶│               ││
   │   API    │      │  EtlService   │◀┴── registro de colaboradores
   └──────────┘      │ (valida +     │
   ┌──────────┐      │  normaliza)   │
   │ Clockify ├─────▶│               │
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
             │ (regra de prazo)│     │  (Teams)   │
             └─────────────────┘     └────────────┘
```

`EmployeeSyncService` roda antes do restante do pipeline em cada execução: lê a
aba `DIM_FUNCIONARIO` da planilha (a fonte editável do cadastro) e sincroniza as
linhas com a tabela `funcionarios` no Postgres. A primeira linha com um dado
e-mail é sincronizada normalmente; as seguintes que repetem o mesmo e-mail são
desviadas para a aba `DUPLICADOS_REMOVIDOS` em vez de sobrescrever o cadastro
existente. A tabela `funcionarios` também guarda `photo_url`, a foto do
colaborador consumida pelo dashboard de indicadores. Só depois da
sincronização `EtlService` carrega o registro já sincronizado para normalizar
responsáveis do ClickUp e colaboradores do Clockify para um nome canônico comum.

Detalhes em [`docs/architecture.md`](docs/architecture.md),
[`docs/data-model.md`](docs/data-model.md) e
[`docs/design-decisions.md`](docs/design-decisions.md).

---

## Arquitetura de pastas

| Caminho | Responsabilidade |
|---|---|
| `main.py` | Entrypoint fino; só chama `sop_pipeline.pipeline.run()`. |
| `src/sop_pipeline/pipeline.py` | Orquestra a execução: download → sync de colaboradores → sync ClickUp/Clockify → upload → alertas. |
| `src/sop_pipeline/clients/` | Clientes das fontes externas: `ClickUpClient` e `ClockifyClient` (HTTP, sem regra de negócio) e `PostgresClient` (upserts no schema Supabase). |
| `src/sop_pipeline/services/` | Regra de negócio: `EtlService` (transformação/validação), `AlertService` (quem merece alerta) e `EmployeeSyncService` (sincroniza `DIM_FUNCIONARIO` com o Postgres). |
| `src/sop_pipeline/integrations/` | Leitura e escrita da planilha e de sistemas externos: `ExcelReader`, `ExcelWriter`, `excel_workbook.py`/`excel_table_helpers.py` (helpers de abertura e de tabela), `Notifier` (Teams), `StorageClient` (B2). |
| `src/sop_pipeline/models/` | Modelos Pydantic (`Task`, `TimeEntry`, `TaskDetail`) e enums. |
| `src/sop_pipeline/config/` | `Settings` (variáveis de ambiente e engine do Postgres) e `EmployeeRegistry`/`EmployeeMapping` (identidade de colaboradores). |
| `src/sop_pipeline/errors/` | Exceções de negócio do projeto. |
| `tests/` | Espelha a estrutura de `src/sop_pipeline/`. |
| `docs/` | Documentação de arquitetura, modelo de dados e decisões de design. |

---

## Instalação

Requer **Python 3.11+** e [Poetry](https://python-poetry.org/).

Existem dois cenários de instalação, com comandos diferentes:

- **Só rodar o pipeline** (uso em produção/CI de execução): instala apenas as
  dependências de runtime.

  ```bash
  poetry install
  ```

- **Desenvolver/testar** (rodar `pytest`, `pylint`, `black` localmente): instala
  as dependências de runtime **e** as de desenvolvimento, via o extra `dev`.

  ```bash
  poetry install --extras dev
  ```

Em ambos os casos, o Poetry cria o ambiente virtual (fora da pasta do projeto)
e instala o próprio pacote em modo editável — não há mais nenhum passo manual
de `venv` ou `pip install -e .`.

---

## Configuração

Copie o arquivo de exemplo e preencha os valores:

```bash
cp .env.example .env    # Windows: copy .env.example .env
```

O `.env` **nunca** é versionado (está no `.gitignore`). Todo segredo do projeto
— token do ClickUp, chave do Clockify, webhooks do Teams, credenciais do B2 — vem
de lá; nada fica escrito no código.

As variáveis estão agrupadas por serviço dentro do `.env.example`, cada uma com um
comentário explicando onde obter o valor. Resumo:

| Grupo | Variáveis |
|---|---|
| ClickUp | `CLICKUP_API_TOKEN`, `CLICKUP_TEAM_ID`, `CLICKUP_LIST_ID`, `CLICKUP_AREA_FIELD_ID` |
| Clockify | `API_KEY_CLOCKIFY`, `WORKSPACE_ID`, `WORKSPACE_NAME` |
| Postgres / Supabase | `DATABASE_URL` |
| Regras de alerta | `ALERT_DAYS_LOW`, `ALERT_DAYS_MEDIUM`, `ALERT_DAYS_HIGH`, `HIGH_PRIORITIES`, `LOW_PRIORITIES` |
| Teams | `WEBHOOK_TI`, `WEBHOOK_SOP`, `WEBHOOK_IA`, `WEBHOOK_FRONT`, `WEBHOOK_DESIGN`, `WEBHOOK_DATA`, `WEBHOOK_BACK`, `WEBHOOK_NO_AREA` |
| Backblaze B2 | `B2_ENDPOINT_URL`, `B2_BUCKET_NAME`, `B2_APPLICATION_KEY`, `B2_KEY_ID`, `EXCEL_CLOUD_NAME`, `TEMP_EXCEL_PATH` |
| Observabilidade | `SENTRY_DSN`, `BETTERSTACK_HEARTBEAT_URL`, `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` |

### Obtendo o WORKSPACE_ID do Clockify

O `WORKSPACE_ID` não aparece em nenhum lugar da interface do Clockify — ele só
existe na resposta da API. Não há atualmente nenhum script auxiliar no
repositório para buscar esse valor, então o jeito mais direto é uma chamada à
API usando a mesma chave já configurada em `API_KEY_CLOCKIFY`:

```bash
curl -H "X-Api-Key: SUA_CHAVE_AQUI" https://api.clockify.me/api/v1/workspaces
```

A resposta é uma lista JSON com todos os workspaces aos quais sua conta tem
acesso. Localize o objeto cujo campo `name` corresponde ao nome do seu
workspace e copie o valor do campo `id` — esse é o `WORKSPACE_ID` a ser usado
no `.env`.

### A conexão com o Postgres (`DATABASE_URL`)

`DATABASE_URL` usa o formato `postgresql+psycopg://usuario:senha@host:porta/banco`
e deve apontar para o **transaction pooler** do Supabase (porta `6543`), não para
a conexão direta: o pooler suporta IPv4, enquanto a conexão direta do Supabase só
responde em IPv6, o que quebra em redes e provedores sem suporte a IPv6.

### Os identificadores do ClickUp (`CLICKUP_TEAM_ID`, `CLICKUP_LIST_ID`, `CLICKUP_AREA_FIELD_ID`)

`CLICKUP_LIST_ID` define **de qual List do ClickUp o pipeline busca tarefas**: o
`ClickUpClient` chama `GET /list/{list_id}/task` e pagina o resultado até o fim,
sempre com `include_closed=true` (para que tarefas concluídas continuem
aparecendo na contagem de concluídas) e `subtasks=true` (para que subtarefas
voltem como tarefas próprias, do mesmo jeito que uma issue do tipo Sub-task do
Jira aparecia na mesma busca). `CLICKUP_TEAM_ID` identifica o Team (Workspace) do
ClickUp e `CLICKUP_AREA_FIELD_ID` é o ID do campo customizado "Area" (tipo
`drop_down`) usado para rotear os alertas do Teams.

O **valor real desses IDs fica apenas no `.env` local** e não é publicado neste
repositório. O `.env.example` traz apenas placeholders vazios.

---

## Como rodar

Com o `.env` preenchido:

```bash
poetry run python main.py
```

Ou, via o script instalado pelo pacote:

```bash
poetry run sop-pipeline
```

Se preferir não prefixar cada comando com `poetry run`, use `poetry shell`
para ativar uma sessão interativa dentro do ambiente e rode os comandos
normalmente.

Uma execução completa:

1. baixa a planilha do bucket B2 para o caminho de `TEMP_EXCEL_PATH`;
2. sincroniza `DIM_FUNCIONARIO` com a tabela `funcionarios` no Postgres;
3. busca as tarefas do ClickUp e grava tarefas, etiquetas e descrições na planilha e no Postgres;
4. busca as horas de todos os usuários do Clockify e grava os apontamentos na planilha e no Postgres;
5. sobe a planilha atualizada de volta para o bucket;
6. envia os alertas de prazo para os canais do Teams;
7. dispara o heartbeat do Better Stack, confirmando que a execução terminou.

As etapas 3, 4 e 6 são isoladas entre si: se o ClickUp estiver fora do ar, as horas
do Clockify ainda são coletadas. Falhas são logadas e enviadas ao Sentry.

> A execução mexe em dados reais (bucket, planilha e canais do Teams). Para testar
> mudanças sem efeito colateral, trabalhe sobre uma cópia local da planilha.

---

## Desenvolvimento

As dependências de desenvolvimento precisam do extra `dev` (veja
[Instalação](#instalação)): `poetry install --extras dev`.

```bash
poetry run black src main.py tests      # formatação
poetry run pylint src main.py tests     # lint
poetry run pytest                       # testes
```

Ou ative `poetry shell` e rode os comandos acima sem o prefixo `poetry run`.

`black` e `pylint` são configurados no `pyproject.toml` (linha de 100 colunas).

---

## Integração contínua

O repositório usa duas GitHub Actions, definidas em `.github/workflows/`:

- **`ci.yaml`** roda em todo push e pull request para `main`: lint (`pylint src/`),
  checagem de formatação (`black --check src/ tests/`) e os testes (`pytest`, com
  cobertura enviada ao Codecov).
- **`run-pipeline.yaml`** roda o pipeline em si, todo dia às 09:50 UTC (06:50
  horário de Brasília), além de poder ser disparado manualmente pela aba Actions
  do GitHub (`workflow_dispatch`).

As credenciais que o pipeline usa em produção (ClickUp, Clockify, Postgres, B2,
Teams, observabilidade) estão configuradas como *secrets* do repositório no
GitHub Actions, não no `.env` do runner.

---

## Licença

MIT — veja [LICENSE](LICENSE).
