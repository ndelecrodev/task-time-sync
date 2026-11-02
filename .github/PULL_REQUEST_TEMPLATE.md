## O que muda

<!-- O título da PR segue Conventional Commits: tipo(escopo opcional): descrição em minúsculas.
     Exemplo: feat(alerts): add a window for medium priority -->
<!-- Descreva a mudança em poucas linhas e o motivo dela. -->

## Tipo de mudança

- [ ] Nova funcionalidade (`feat/`)
- [ ] Correção de bug (`fix/`)
- [ ] Refatoração sem mudar comportamento (`refactor/`)
- [ ] Documentação (`docs/`)
- [ ] Testes (`test/`)
- [ ] Infra, dependências ou CI (`chore/`)

## Como testar

<!-- Comandos, dados ou passos para validar. Lembre: uma execução real mexe em bucket, planilha e canais do Teams. -->

## Checklist

- [ ] `poetry run black --check src/ tests/` passa
- [ ] `poetry run pylint src/` passa
- [ ] `poetry run pytest` passa
- [ ] Testes novos ou ajustados cobrem a mudança
- [ ] Documentação atualizada (`README.md`, `docs/`), se a mudança afeta uso ou arquitetura
- [ ] Mudança de regra de negócio registrada em `docs/design-decisions.md`
- [ ] Nenhum segredo, token, webhook ou ID real no diff

## Issues relacionadas

<!-- Closes #123 -->
