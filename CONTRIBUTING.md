# Contribuindo

Obrigado por querer ajudar. Este guia resume o fluxo de trabalho do projeto.

## Preparando o ambiente

```bash
git clone https://github.com/ndelecrodev/task-time-sync.git
cd task-time-sync
git switch develop
poetry install --extras dev
cp .env.example .env    # Windows: copy .env.example .env
```

Instale também os hooks locais, que rodam as mesmas checagens da CI antes do commit e do push:

```bash
pip install pre-commit
pre-commit install --install-hooks
pre-commit install --hook-type pre-push
```

> Uma execução real do pipeline mexe em bucket, planilha e canais do Teams. Para testar mudanças, trabalhe sobre uma cópia local da planilha e não rode o pipeline completo.

## Fluxo de branches

```
feat/*  fix/*  refactor/*  docs/*  test/*  chore/*
        │
        ▼ pull request
     develop ──▶ release ──▶ main
```

1. Parta da `develop` atualizada e crie uma branch com prefixo do tipo: `feat/`, `fix/`, `refactor/`, `docs/`, `test/` ou `chore/`.
2. Faça commits pequenos, em inglês e no imperativo, por exemplo `Archive Excel rows from the ClickUp id set instead of Postgres`.
3. Abra a pull request para a `develop`. A promoção segue `develop` → `release` → `main`, sempre por pull request.

O prefixo da branch (ou o início do título da PR) define o rótulo automático da PR e, com ele, a categoria das notas de release.

## Antes de abrir a PR

```bash
poetry run black src main.py tests
poetry run pylint src/
poetry run pytest
```

São os mesmos checks da CI. A suíte não precisa de rede, banco nem credenciais.

## Mudando uma regra de negócio

Boa parte do "porquê" do código está em [`docs/design-decisions.md`](docs/design-decisions.md). Antes de alterar uma regra, procure a decisão correspondente. Se a mudança contradiz uma decisão, atualize a decisão na mesma PR e, se afetar o uso, o [`README.md`](README.md) e o [`docs/data-model.md`](docs/data-model.md).

## Releases

As notas de release são montadas automaticamente a partir das PRs mergeadas na `main` (Release Drafter). Para publicar, abra o rascunho em *Releases*, confira a versão proposta e clique em *Publish release*. Use o rótulo `skip-changelog` numa PR para deixá-la de fora das notas, e `breaking` ou `major` para subir a versão maior.

## Segredos

Nunca faça commit de tokens, chaves, webhooks, IDs reais do ClickUp ou do Clockify, nem do `.env`. Veja [`SECURITY.md`](SECURITY.md).
