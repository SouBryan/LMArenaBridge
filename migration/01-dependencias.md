# Fase 1 — Dependências

Estamos migrando este projeto de Camoufox + Playwright para CloakBrowser (cloakhq/cloakbrowser).

FASE 1: Atualizar dependências.

Alterações necessárias:

1. `requirements.txt`: Remover as linhas `camoufox` e `playwright`. Adicionar `cloakbrowser`.

2. `pyproject.toml`: Na seção `[project] dependencies`, remover `"camoufox"` e `"playwright"`. Adicionar `"cloakbrowser"`. Na seção `[project.optional-dependencies] dev`, manter tudo como está.

3. `pyproject.toml`: Na seção `[tool.pytest.ini_options] markers`, renomear o marker `"camoufox: marks tests that require Camoufox"` para `"cloakbrowser: marks tests that require CloakBrowser"`.

NÃO altere nenhum outro arquivo nesta fase. NÃO rode nenhum comando de instalação.
