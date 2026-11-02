<a id="top"></a>

<div align="center">

[English version](docs/en/readme.md)

# Task Time Sync

**Pipeline que consolida tarefas do ClickUp e horas do Clockify em uma planilha Excel e em um banco Postgres, e avisa o time no Microsoft Teams quando um prazo está chegando.**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Poetry](https://img.shields.io/badge/Poetry-60A5FA?style=for-the-badge&logo=poetry&logoColor=white)](https://python-poetry.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)
[![Backblaze B2](https://img.shields.io/badge/Backblaze-B2-E21E29?style=for-the-badge&logo=backblaze&logoColor=white)](https://www.backblaze.com/cloud-storage)

[![CI](https://img.shields.io/github/actions/workflow/status/ndelecrodev/task-time-sync/ci.yaml?label=CI&style=flat-square)](https://github.com/ndelecrodev/task-time-sync/actions/workflows/ci.yaml)
[![Execução diária](https://img.shields.io/github/actions/workflow/status/ndelecrodev/task-time-sync/run-pipeline.yaml?label=execu%C3%A7%C3%A3o%20di%C3%A1ria&style=flat-square)](https://github.com/ndelecrodev/task-time-sync/actions/workflows/run-pipeline.yaml)
[![Cobertura](https://img.shields.io/codecov/c/github/ndelecrodev/task-time-sync?style=flat-square)](https://codecov.io/gh/ndelecrodev/task-time-sync)
[![Último commit](https://img.shields.io/github/last-commit/ndelecrodev/task-time-sync?label=%C3%BAltimo%20commit&style=flat-square)](https://github.com/ndelecrodev/task-time-sync/commits)
[![Licença](https://img.shields.io/github/license/ndelecrodev/task-time-sync?style=flat-square)](LICENSE)

[Como funciona](#como-funciona) ·
[Começando](#começando) ·
[Documentação](#documentação) ·
[Contribuindo](#contribuindo)

</div>

---

## Sumário

- [Sobre](#sobre)
- [Destaques](#destaques)
- [Como funciona](#como-funciona)
- [Regras de negócio](#regras-de-negócio)
- [Modelo de dados](#modelo-de-dados)
- [Arquitetura do código](#arquitetura-do-código)
- [Começando](#começando)
- [Desenvolvimento e testes](#desenvolvimento-e-testes)
- [Automação (GitHub Actions)](#automação-github-actions)
- [Observabilidade](#observabilidade)
- [Segurança](#segurança)
- [Documentação](#documentação)
- [Contribuindo](#contribuindo)
- [Equipe](#equipe)
- [Licença](#licença)

## Sobre

Times de projeto acompanham o trabalho em um lugar (**ClickUp**, onde as tarefas vivem) e as horas em outro (**Clockify**, onde as pessoas apontam o tempo). O **Task Time Sync** junta os dois: todos os dias ele busca as tarefas e os apontamentos, normaliza quem é quem, atualiza uma planilha Excel e um schema relacional, e avisa o canal certo do **Microsoft Teams** sobre as tarefas que estão perto do prazo.

A planilha não é um dump. Ela é o **produto final**, com tabelas, fórmulas e abas de indicadores. O pipeline faz *upsert* nas tabelas de dados e deixa as colunas calculadas para as fórmulas do próprio Excel. O Postgres guarda os mesmos dados de forma relacional, com o cadastro de colaboradores como fonte de verdade compartilhada entre a planilha e o banco.

> [!NOTE]
> Este projeto migrou a fonte de tarefas do **Jira** para o **ClickUp**. Um snapshot congelado da versão baseada em Jira está preservado na branch [`jira-integration`](https://github.com/ndelecrodev/task-time-sync/tree/jira-integration), para referência.

<!--
Prévia (opcional): adicione as imagens em docs/images/ e descomente.

<p align="center">
  <img src="docs/images/planilha-indicadores.png" alt="Aba de indicadores da planilha" width="48%">
  <img src="docs/images/alerta-teams.png" alt="Alerta de prazo no Microsoft Teams" width="48%">
</p>
-->

<p align="right"><a href="#top">voltar ao topo</a></p>

## Destaques

| | |
|---|---|
| **Duas fontes, uma identidade** | ClickUp identifica pessoas por *username*/e-mail e o Clockify por e-mail; uma camada de mapeamento reduz os dois a um nome canônico |
| **Excel como produto** | Upsert por ID, fórmulas preservadas e `fullCalcOnLoad` ligado em toda abertura do arquivo |
| **Postgres em paralelo** | Todo dado gravado na planilha tem a gravação equivalente no schema relacional (Supabase) |
| **Alertas por prioridade** | Janela de aviso maior para tarefas urgentes, canal do Teams por área e @menção ao responsável |
| **Falha isolada** | ClickUp fora do ar não impede a coleta das horas do Clockify, e vice-versa |
| **Nada se perde** | Tarefa que some do ClickUp é arquivada com data, não apagada; registro inválido é descartado com aviso, não derruba a execução |
| **Monitorado** | Exceções no Sentry, logs e heartbeat no Better Stack |
| **Bem documentado** | 29 decisões de design registradas, com o porquê de cada uma |

<p align="right"><a href="#top">voltar ao topo</a></p>

## Como funciona

```mermaid
flowchart LR
    CU["ClickUp<br/>tarefas"]
    CL["Clockify<br/>horas"]

    subgraph pipe["Task Time Sync"]
        direction TB
        EMP["EmployeeDataSyncService<br/>cadastro de colaboradores"]
        ETL["EtlService<br/>valida e normaliza"]
        ALR["AlertService<br/>regra de prazo"]
    end

    XLS[("Planilha Excel<br/>Backblaze B2")]
    PG[("Postgres<br/>Supabase")]
    TM["Microsoft Teams<br/>um canal por área"]

    XLS -- "DIM_FUNCIONARIO" --> EMP --> PG
    CU --> ETL
    CL --> ETL
    ETL --> XLS
    ETL --> PG
    ETL --> ALR --> TM

    classDef fonte fill:#fff,stroke:#7B68EE,color:#2b2370
    classDef destino fill:#fff,stroke:#3ECF8E,color:#0b5d3a
    class CU,CL fonte
    class XLS,PG,TM destino
```

### Uma execução, passo a passo

```mermaid
flowchart TD
    START(["Agendado (GitHub Actions)<br/>ou manual"]) --> DL["Baixa a planilha do B2"]
    DL --> SYNC["Sincroniza DIM_FUNCIONARIO<br/>com a tabela funcionarios"]
    SYNC --> CK
    SYNC --> CF

    subgraph iso["Etapas isoladas: uma falha não derruba a outra"]
        direction LR
        CK["ClickUp<br/>tarefas, etiquetas, descrições<br/>responsáveis e arquivamento"]
        CF["Clockify<br/>apontamentos de horas<br/>de todos os usuários"]
    end

    CK -- "sucesso" --> SNAP["Snapshot de progresso<br/>+ alertas no Teams"]
    CK -. "falha" .-> SKIP["Alertas pulados<br/>com aviso explícito"]
    SNAP --> UP
    SKIP --> UP
    CF --> UP["Sobe a planilha para o B2"]
    UP --> HB(["Heartbeat no Better Stack"])
```

1. **Baixa** a planilha do bucket B2 para uma cópia local (`TEMP_EXCEL_PATH`).
2. **Sincroniza o cadastro**: lê a aba `DIM_FUNCIONARIO` (a fonte editável) e grava as linhas na tabela `funcionarios` do Postgres, junto com os vínculos de área.
3. **ClickUp**: busca as tarefas do Space, descarta as de listas fora da allowlist e grava tarefas, etiquetas e descrições na planilha e no Postgres. Tarefas que sumiram da busca são arquivadas.
4. **Clockify**: busca as horas de todos os usuários e grava os apontamentos.
5. **Alertas**: grava o snapshot de progresso e envia os avisos de prazo ao Teams.
6. **Sobe** a planilha atualizada de volta ao bucket e dispara o **heartbeat**, confirmando que a execução terminou.

> [!WARNING]
> **Duas execuções simultâneas não são seguras.** Ambas baixariam a mesma planilha, escreveriam em cópias locais distintas e a última a subir sobrescreveria a outra. O bucket não usa lock.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Regras de negócio

### Quando uma tarefa gera alerta

Cada prioridade tem uma janela de aviso, em dias restantes até o prazo. Tarefas mais urgentes são avisadas mais cedo.

| Prioridade | Avisa quando restam | Variável |
|---|:---:|---|
| Alta (`Highest`, `High`) | 5 dias ou menos | `ALERT_DAYS_HIGH` |
| Média e **Sem prioridade** | 4 dias ou menos | `ALERT_DAYS_MEDIUM` |
| Baixa (`Low`, `Lowest`) | 3 dias ou menos | `ALERT_DAYS_LOW` |

Os valores acima são os do `.env.example` e podem ser ajustados. **Não geram alerta:** tarefa concluída, tarefa sem prazo e tarefas da turma **Segundo Ano** (decisão de produto), embora continuem em todo o resto do pipeline. Uma tarefa atrasada aparece como *"Tarefa atrasada há N dia(s)"*, em vez de um número negativo.

### Regras que valem saber

| Regra | Como funciona |
|---|---|
| **Allowlist de listas** | Só entram as tarefas cujas listas do ClickUp estão em `CLICKUP_LIST_MAP`, que também define a **área** e a **turma** de cada lista. Uma lista nova só entra depois de ganhar uma entrada ali; as descartadas são registradas em `WARNING` |
| **Conclusão** | Segue o tipo atual do status no ClickUp (`done`/`closed`). Reabrir uma tarefa limpa a data de conclusão |
| **Vários responsáveis** | A tarefa pode ter vários responsáveis; o primeiro é o `responsavel_id` e o alvo da @menção no Teams |
| **Arquivamento** | Tarefa que some da busca recebe `arquivada_em` e permanece na base; se voltar a aparecer, é desarquivada. Nenhuma linha é apagada |
| **Subtarefas** | Guardam o pai imediato em `tarefa_pai_id`; prioridade nula vira **Sem prioridade** |
| **Colaborador não mapeado** | Recebe o valor visível `Unmapped employee: <email>`, em vez de ser descartado em silêncio |
| **E-mail duplicado no cadastro** | A primeira linha sincroniza; as seguintes vão para a aba `DUPLICADOS_REMOVIDOS` |
| **E-mail do Teams** | `teams_email` tem prioridade sobre `clickup_email` nas @menções, quando os dois divergem |
| **Registro inválido** | É descartado com `warning`; um dado ruim não interrompe a execução |

<p align="right"><a href="#top">voltar ao topo</a></p>

## Modelo de dados

### Planilha

| Aba | Papel | Quem escreve |
|---|---|---|
| `BASE_TAREFAS` | Uma linha por tarefa; `dias_restantes`, `atrasado` e `status_prazo` são **fórmulas do Excel** | Pipeline |
| `DETALHES_TAREFA` | Descrição longa de cada tarefa | Pipeline |
| `BASE_HORAS` | Apontamentos de horas do Clockify | Pipeline |
| `DIM_ETIQUETAS` · `FATO_TAREFA_ETIQUETA` | Etiquetas e relação N:N com tarefas | Pipeline |
| `DIM_FUNCIONARIO` | Cadastro de colaboradores, **lido** a cada execução | Pessoas |
| `DIM_FUNCIONARIO_AREA` · `FATO_FUNCIONARIO_AREA` | Áreas e relação N:N com colaboradores | Pessoas |
| `CALCULOS` · `INDICADORES` | Métricas por pessoa e KPIs consolidados do dashboard | Fórmulas |

### Postgres

```mermaid
erDiagram
    funcionarios ||--o{ tarefas : "responsavel_id"
    funcionarios ||--o{ horas : "funcionario_id"
    funcionarios ||--o{ tarefa_responsavel : ""
    tarefas ||--o{ tarefa_responsavel : ""
    tarefas ||--o| detalhes_tarefa : ""
    tarefas ||--o{ tarefa_etiqueta : ""
    etiquetas ||--o{ tarefa_etiqueta : ""
    funcionarios ||--o{ funcionario_area : ""
    areas ||--o{ funcionario_area : ""

    funcionarios {
        int id PK
        string clickup_email
        string clockify_email
        string teams_email
        string photo_url
    }
    tarefas {
        string id PK
        string turma
        string tarefa_pai_id
        timestamp arquivada_em
    }
    horas {
        string id PK
        date data
        float horas
    }
```

O schema roda **em paralelo** à planilha, não no lugar dela. Nomes de tabela e coluna espelham o que já está implantado no Supabase e por isso ficam em português; o código em si é todo em inglês.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Arquitetura do código

A dependência aponta sempre para dentro: `pipeline` → `integrations`/`services` → `models`/`config`. Nenhum client conhece o `ExcelWriter`, e o `ExcelWriter` não conhece o ClickUp.

| Pacote | Responsabilidade |
|---|---|
| `pipeline.py` | Orquestra a execução: download → sync de colaboradores → ClickUp/Clockify → alertas → upload |
| `clients/` | Falam com as fontes: `ClickUpClient` e `ClockifyClient` (HTTP, sem regra de negócio) e `PostgresClient` (upserts via SQLAlchemy) |
| `services/` | Regra de negócio: `EtlService` (validação e normalização), `AlertService` (quem merece alerta) e `EmployeeDataSyncService` (planilha → Postgres) |
| `integrations/` | Leitura e escrita da planilha e dos destinos: `ExcelReader`, `ExcelWriter`, `Notifier` (Teams) e `StorageClient` (B2) |
| `models/` | Modelos Pydantic (`Task`, `TimeEntry`, `TaskDetail`) e enums: o contrato entre as camadas |
| `config/` | `Settings` (único ponto que lê o ambiente) e o registro de colaboradores |
| `errors/` | Exceções de negócio, todas sob `SopPipelineError` |

<details>
<summary><b>Ver a árvore de pastas</b></summary>

<br>

```
task-time-sync/
├── .github/workflows/
│   ├── ci.yaml                      lint, formatação e testes
│   └── run-pipeline.yaml            execução diária do pipeline
├── docs/
│   ├── architecture.md              fluxo, camadas e isolamento de falhas
│   ├── data-model.md                modelos, planilha e schema do Postgres
│   ├── design-decisions.md          as 29 decisões de design
│   └── en/                          versão em inglês
├── src/sop_pipeline/
│   ├── clients/                     ClickUp, Clockify e Postgres
│   ├── config/                      Settings e registro de colaboradores
│   ├── errors/                      exceções do projeto
│   ├── integrations/                Excel, Teams e Backblaze B2
│   ├── models/                      modelos Pydantic e enums
│   ├── services/                    ETL, alertas e sync de colaboradores
│   └── pipeline.py                  orquestração
├── tests/                           espelha a estrutura de src/sop_pipeline/
├── .env.example                     variáveis de ambiente, agrupadas por serviço
├── main.py                          entrypoint fino
└── pyproject.toml                   dependências, black, pylint e pytest
```

</details>

<p align="right"><a href="#top">voltar ao topo</a></p>

## Começando

### Pré-requisitos

| Ferramenta | Versão |
|---|---|
| Python | 3.11 ou mais novo |
| [Poetry](https://python-poetry.org/) | qualquer versão recente |
| Contas e chaves | ClickUp, Clockify, Backblaze B2, Postgres (Supabase), webhooks do Teams |

### 1. Clonar e instalar

```bash
git clone https://github.com/ndelecrodev/task-time-sync.git
cd task-time-sync
```

<table>
<tr><th>Só rodar o pipeline</th><th>Desenvolver e testar</th></tr>
<tr>
<td>

```bash
poetry install
```

</td>
<td>

```bash
poetry install --extras dev
```

</td>
</tr>
</table>

O Poetry cria o ambiente virtual fora da pasta do projeto e instala o pacote em modo editável: não há passo manual de `venv` nem de `pip install -e .`. O extra `dev` acrescenta `pytest`, `pylint`, `black` e `pytest-cov`.

### 2. Configurar o `.env`

<table>
<tr><th>Windows (PowerShell)</th><th>Linux / macOS</th></tr>
<tr>
<td>

```powershell
copy .env.example .env
```

</td>
<td>

```bash
cp .env.example .env
```

</td>
</tr>
</table>

Preencha os valores. O `.env.example` agrupa as variáveis por serviço e comenta onde obter cada uma.

| Grupo | Variáveis |
|---|---|
| ClickUp | `CLICKUP_API_TOKEN`, `CLICKUP_TEAM_ID`, `CLICKUP_SPACE_ID` |
| Clockify | `API_KEY_CLOCKIFY`, `WORKSPACE_ID`, `WORKSPACE_NAME` |
| Postgres / Supabase | `DATABASE_URL`, `DEFAULT_ANONYMOUS_EMAIL` |
| Regras de alerta | `ALERT_DAYS_LOW`, `ALERT_DAYS_MEDIUM`, `ALERT_DAYS_HIGH`, `HIGH_PRIORITIES`, `LOW_PRIORITIES` |
| Teams | `WEBHOOK_TI`, `WEBHOOK_SOP`, `WEBHOOK_IA`, `WEBHOOK_FRONT`, `WEBHOOK_DESIGN`, `WEBHOOK_DATA`, `WEBHOOK_BACK`, `WEBHOOK_NO_AREA` |
| Backblaze B2 | `B2_ENDPOINT_URL`, `B2_BUCKET_NAME`, `B2_APPLICATION_KEY`, `B2_KEY_ID`, `EXCEL_CLOUD_NAME`, `TEMP_EXCEL_PATH` |
| Observabilidade | `SENTRY_DSN`, `BETTERSTACK_HEARTBEAT_URL`, `BETTERSTACK_SOURCE_TOKEN`, `BETTERSTACK_INGESTING_HOST` |

> [!CAUTION]
> Nunca faça commit do `.env`. Ele já está no `.gitignore`; se aparecer no `git status`, pare e confira. O `.env.example` traz só placeholders, e os valores reais dos IDs (Team, Space, Workspace) ficam apenas no seu ambiente.

<details>
<summary><b>Onde achar o <code>WORKSPACE_ID</code> do Clockify</b></summary>

<br>

O `WORKSPACE_ID` não aparece na interface do Clockify, só na resposta da API. Use a mesma chave configurada em `API_KEY_CLOCKIFY`:

```bash
curl -H "X-Api-Key: SUA_CHAVE_AQUI" https://api.clockify.me/api/v1/workspaces
```

Na lista devolvida, procure o objeto cujo `name` é o do seu workspace e copie o campo `id`.

</details>

<details>
<summary><b>Como montar a <code>DATABASE_URL</code></b></summary>

<br>

O formato é `postgresql+psycopg://usuario:senha@host:porta/banco`. Aponte para o **transaction pooler** do Supabase (porta `6543`), não para a conexão direta: o pooler responde em IPv4, enquanto a conexão direta só responde em IPv6 e quebra em redes e provedores sem suporte a ele.

</details>

### 3. Rodar

```bash
poetry run sop-pipeline
```

Também funciona `poetry run python main.py`. Se preferir não prefixar cada comando, ative uma sessão com `poetry shell`.

> [!IMPORTANT]
> Uma execução mexe em **dados reais**: o bucket, a planilha e os canais do Teams. Para testar mudanças sem efeito colateral, trabalhe sobre uma cópia local da planilha.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Desenvolvimento e testes

```bash
poetry run black src main.py tests      # formatação
poetry run pylint src main.py tests     # lint
poetry run pytest                       # testes
```

`black` e `pylint` são configurados no `pyproject.toml`, com linha de 100 colunas.

A suíte tem mais de 150 testes (`pytest`), organizados em espelho com `src/sop_pipeline/`, e **não precisa de rede, de banco nem de credenciais**: as fontes externas são simuladas. A cobertura vai para o Codecov a cada execução da CI.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Automação (GitHub Actions)

| Workflow | Quando roda | O que faz |
|---|---|---|
| [`ci.yaml`](.github/workflows/ci.yaml) | Em todo push e pull request para `main` | `pylint`, `black --check` e `pytest` com cobertura enviada ao Codecov |
| [`run-pipeline.yaml`](.github/workflows/run-pipeline.yaml) | Todos os dias às **08:47 UTC** (05:47 em Brasília) e manualmente (*Run workflow*) | Executa o pipeline completo em produção |

As credenciais usadas em produção (ClickUp, Clockify, Postgres, B2, Teams e observabilidade) ficam como *secrets* do repositório, em *Settings → Secrets and variables → Actions*, e nunca no `.env` do runner.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Observabilidade

| Ferramenta | Papel |
|---|---|
| **Sentry** | Recebe as exceções capturadas em cada etapa, com *stack trace* |
| **Better Stack (logs)** | O `LogtailHandler` é anexado ao `logging` raiz; todo `info`, `warning` e `error` sobe para lá |
| **Better Stack (heartbeat)** | Um `GET` no fim da execução, **fora** de qualquer `try/except` de propósito: se o upload da planilha falhar, a linha nunca é alcançada e o Better Stack acusa a execução perdida |

<p align="right"><a href="#top">voltar ao topo</a></p>

## Segurança

| Medida | Como funciona |
|---|---|
| **Segredos fora do código** | Tudo vem do ambiente (`.env` local ou *secrets* do GitHub Actions), lido num único ponto: `Settings` |
| **`.env` ignorado** | Está no `.gitignore`; o repositório só traz o `.env.example`, com placeholders vazios |
| **IDs não publicados** | Team, Space e Workspace não aparecem no repositório |
| **Planilha local temporária** | A cópia de trabalho (`planilha_temp.xlsx`) e qualquer `.xlsx` são ignorados pelo Git |
| **Chave do B2** | Use uma *Application Key* limitada ao bucket do projeto |

<p align="right"><a href="#top">voltar ao topo</a></p>

## Documentação

A documentação completa também está publicada como site navegável em **[ndelecrodev.github.io/task-time-sync-docs](https://ndelecrodev.github.io/task-time-sync-docs/)**.

| Documento | O que tem |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Fluxo de uma execução, camadas, isolamento de falhas, observabilidade e concorrência |
| [`docs/data-model.md`](docs/data-model.md) | Modelos Python, mapeamento para a planilha e schema do Postgres |
| [`docs/design-decisions.md`](docs/design-decisions.md) | As 29 decisões de design, cada uma com o contexto e o porquê |
| [`docs/en/`](docs/en/readme.md) | Toda a documentação em inglês |

<p align="right"><a href="#top">voltar ao topo</a></p>

## Contribuindo

```mermaid
gitGraph
    commit id: "main"
    branch develop
    checkout develop
    commit id: "integração"
    branch feat/nova-regra
    checkout feat/nova-regra
    commit id: "feat: ..."
    commit id: "test: ..."
    checkout develop
    merge feat/nova-regra id: "PR"
    branch release
    checkout release
    commit id: "estabiliza"
    checkout main
    merge release id: "release"
```

1. Parta da `develop` atualizada e crie uma branch com prefixo do tipo: `feat/`, `fix/`, `refactor/`, `docs/`, `test/` ou `chore/`.
2. Escreva os commits em inglês, no imperativo, por exemplo `Archive Excel rows from the ClickUp id set instead of Postgres`.
3. Rode `black`, `pylint` e `pytest` antes de abrir a PR; são os mesmos checks da CI.
4. Abra a PR para a `develop`. A promoção segue `develop` → `release` → `main`, sempre por pull request.

> [!TIP]
> Antes de mexer numa regra de negócio, procure a decisão correspondente em [`docs/design-decisions.md`](docs/design-decisions.md). Boa parte do "porquê" está lá, e uma mudança que contradiz uma decisão deve atualizá-la.

<p align="right"><a href="#top">voltar ao topo</a></p>

## Equipe

<a href="https://github.com/ndelecrodev/task-time-sync/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ndelecrodev/task-time-sync" alt="Contribuidores do task-time-sync">
</a>

## Licença

Distribuído sob a licença MIT. Veja [LICENSE](LICENSE).

<p align="right"><a href="#top">voltar ao topo</a></p>
