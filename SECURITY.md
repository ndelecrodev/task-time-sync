# Política de segurança

## Reportando uma vulnerabilidade

**Não abra uma issue pública** para falhas de segurança.

Use o relato privado do GitHub: aba **Security** do repositório → **Report a vulnerability**
([abrir](https://github.com/ndelecrodev/task-time-sync/security/advisories/new)).

Inclua o que for possível: o que foi encontrado, onde, como reproduzir e qual o impacto. A resposta inicial deve chegar em alguns dias.

## O que está no escopo

- Vazamento de segredos (tokens, chaves, webhooks, credenciais do banco ou do bucket) no código ou no histórico
- Acesso indevido à planilha, ao bucket Backblaze B2 ou ao banco Postgres
- Dependências com vulnerabilidades conhecidas que afetem o pipeline

## Se você encontrou um segredo exposto

1. Revogue ou gire a credencial no serviço de origem (ClickUp, Clockify, Backblaze, Supabase, Teams, Sentry ou Better Stack) **antes** de qualquer outra coisa.
2. Avise pelo canal privado acima.
3. Remover o arquivo do repositório não basta: o valor continua no histórico do Git.

## Versões com suporte

Correções de segurança são aplicadas na `main`, que é a versão publicada.
