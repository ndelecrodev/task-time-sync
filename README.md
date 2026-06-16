# Spreadsheet Automation Project

Sistema completo de gestão e análise de performance de equipe utilizando o Excel como dashboard principal, integrado com dados de tarefas (Jira) e controle de horas via automação em Python.

## Funcionalidades

* Controle de tarefas por colaborador: Acompanhamento detalhado do ciclo de vida de cada atividade atribuída.
* Monitoramento de horas trabalhadas: Registro e consolidação do tempo alocado pela equipe.
* Dashboard visual com KPIs: Painel gerencial e dinâmico focado em métricas estratégicas.
* Cálculo de produtividade automática: Processamento automático de indicadores de eficiência baseados em entregas versus tempo.
* Identificação de tarefas atrasadas: Alertas visuais e marcas automáticas para atividades fora do prazo.
* Gestão de prazos e status: Visão holística de cronogramas e gargalos operacionais.
* Integração com Jira (via Python): Sincronização automatizada da base de dados sem necessidade de exportações manuais.

## Arquitetura do Projeto

O ecossistema é dividido em uma camada de processamento e extração de dados (Backend) e uma camada de visualização e cálculo analítico (Frontend).

### Excel (Frontend / Dashboard)
O arquivo de planilhas é estruturado em tabelas isoladas para garantir a integridade e escalabilidade dos dados:
* DASHBOARD: Visualização executiva com KPIs centralizados e gráficos dinâmicos.
* CALCULOS: Motor interno que processa as métricas segmentadas por pessoa.
* BASE_TAREFAS: Repositório bruto dos dados extraídos do Jira.
* BASE_HORAS: Controle estruturado do ponto ou horas alocadas.
* DIM_FUNCIONARIOS: Tabela dimensional com dados cadastrais dos colaboradores.
* DETALHES_TAREFA: Descrições detalhadas e metadados adicionais das tarefas.

### Python (Backend)
Scripts responsáveis pela automação do pipeline de dados:
* Conexão segura e extração de dados via API do Jira.
* Processamento, limpeza e tratamento de dados em memória.
* Carga e atualização automática do Excel mapeando as abas de dados correspondentes.

## Fluxo de Dados

O ciclo de vida do dado percorre o seguinte fluxo linear de transformação:

Jira (Origem) -> Python (Ingestão/Tratamento) -> Excel Base (Carga) -> Dashboard (Visualização/KPIs)

## Principais Métricas

O sistema consolida e apresenta em tempo real os seguintes indicadores:
* Tarefas totais: Volumetria geral do backlog e sprint.
* Tarefas concluídas: Volume de entregas finalizadas com sucesso.
* Tarefas atrasadas: Quantidade de itens com prazo expirado em relação à data atual.
* Horas trabalhadas: Total de esforço temporal registrado pela equipe.
* Produtividade: Métrica calculada através da relação de tarefas concluídas por hora.
* Percentual de conclusão: Progresso percentual do projeto (concluídas / total).

## Estrutura de Dados

### BASE_TAREFAS
| Campo | Descrição |
| :--- | :--- |
| id | Identificador único da tarefa (Key do Jira). |
| titulo | Nome ou resumo descritivo da tarefa. |
| responsavel | Nome do colaborador alocado. |
| area | Departamento ou squad correspondente. |
| prioridade | Nível de criticidade (Highest a Lowest). |
| status | Status atual do fluxo de trabalho (ex: To Do, In Progress, Done). |
| data_inicio | Data de início da atividade. |
| prazo | Data limite para a entrega (Deadline). |
| data_conclusao | Data em que a tarefa foi movida para o status concluído. |
| dias_restantes | Cálculo de dias disponíveis até o prazo final. |
| atrasado | Marca booleana ou binária indicando atraso (Sim/Não ou 1/0). |
| status_prazo | Classificação textual do status do prazo (ex: No Prazo, Atenção, Atrasado). |

### BASE_HORAS
| Campo | Descrição |
| :--- | :--- |
| funcionario | Nome do colaborador. |
| data | Data do registro do esforço. |
| horas | Quantidade de horas trabalhadas ou alocadas no dia. |

## Níveis de Prioridade (Jira Mapping)

* Highest: Crítica
* High: Alta
* Medium: Média
* Low: Baixa
* Lowest: Muito Baixa

## Lógica de Negócio

As seguintes premissas e regras analíticas regem os cálculos automatizados:
1. Tarefa Concluída: Identificada estritamente quando o campo data_conclusao está devidamente preenchido.
2. Identificação de Atraso: Uma tarefa é marcada como atrasada se prazo for menor que hoje e a atividade ainda não estiver concluída.
3. Métrica de Produtividade: Calculada pela divisão de Tarefas Concluídas por Horas Trabalhadas.
4. Percentual de Conclusão: Mensurado através da divisão de Tarefas Concluídas pelo Total de Tarefas.

## Boas Práticas Adotadas

* Separação entre Dados e Visualização: As abas de dados (BASE_*) servem apenas como repositórios limpos, enquanto a aba DASHBOARD é isolada para consumo visual.
* Tabelas Estruturadas: Utilização do recurso Formatar como Tabela do Excel, garantindo referências estruturadas dinâmicas e fórmulas que se expandem sozinhas.
* Não Duplicação de Dados: Estrutura normalizada utilizando tabelas dimensionais (DIM_FUNCIONARIOS) conectadas por chaves.
* Cálculos no Excel: O Python é responsável apenas pela extração e transporte dos dados brutos. Os cálculos e fórmulas lógicas rodam nativamente no Excel para manter a flexibilidade do usuário.
* Backend desacoplado: Toda a regra de conexão e autenticação com o ecossistema Jira fica centralizada nos scripts Python de forma segura.

## Tecnologias Utilizadas

* Python: Linguagem core utilizada para a construção do script de backend e automação do pipeline.
* Excel: Interface visual e motor de cálculo dinâmico (fórmulas e tabelas dinâmicas).
* Pandas: Biblioteca Python para manipulação, limpeza e estruturação eficiente das matrizes de dados.
* OpenPyXL: Engine de integração utilizada pelo Python para ler, gravar e modificar planilhas Excel sem a necessidade de abrir a interface do software.
* API do Jira: Endpoint oficial utilizado para realizar as consultas (JQL) e extrair o status das tarefas em tempo real.

## Próximos Passos

- Implementação de logs e tratamento de exceções robusto na conexão com a API do Jira.
- Agendamento da automação via nuvem (ex: GitHub Actions, Airflow ou AWS Lambda) para atualização programada.
- Migração incremental ou espelhamento do dashboard para o Power BI buscando maior interatividade.
- Criação de um sistema de alertas automáticos (via e-mail ou Slack ou Teams) para notificar os colaboradores sobre tarefas próximas ao prazo de expiração.

## Autor

Projeto desenvolvido com foco em excelência operacional, automação corporativa e análise de dados focada na gestão de performance de equipes de alta performance.
