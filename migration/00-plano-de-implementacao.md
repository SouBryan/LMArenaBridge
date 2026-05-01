# Plano de Migração: Camoufox + Playwright → CloakBrowser

## Visão Geral

Migração completa do LMArenaBridge de duas dependências de browser automation (Camoufox baseado em Firefox + Playwright para Chrome) para uma única dependência: **CloakBrowser** (Chromium anti-detect com patches C++ source-level).

### Motivação

| Problema atual | Solução com CloakBrowser |
|---|---|
| Camoufox (Firefox) leaka sinais de OS via rendering (fonts, GPU, scrollbars) | Chromium com 48 patches C++ — passa todos os testes de detecção |
| reCAPTCHA v3 depende de hacks manuais (`--disable-blink-features`, `webdriver` override) | Score 0.9 nativo (nível humano) sem nenhum hack |
| Duas engines (Chrome + Firefox) = complexidade e bugs | Uma engine só (Chromium) |
| Precisa de `find_chrome_executable()` pra achar o Chrome do sistema | CloakBrowser traz o próprio binário Chromium |
| `main_world_eval=True` (conceito Firefox Xray wrappers) pra injetar reCAPTCHA JS | `page.evaluate()` já roda no main world nativamente |
| Updates do Camoufox são lentos | CloakBrowser tem updates a cada 1-2 semanas + auto-updating binary |

### Dependências: antes vs depois

**Antes:**
- `camoufox` — Firefox anti-detect
- `playwright` — Automação Chrome/Edge via Chromium

**Depois:**
- `cloakbrowser` — Drop-in Playwright replacement com stealth nativo

---

## Mapeamento de APIs

### Launches

| Uso atual | Equivalente CloakBrowser | Notas |
|---|---|---|
| `AsyncCamoufox(headless=True, main_world_eval=True)` (context manager) | `await launch_async(headless=True)` (retorna browser) | Trocar `async with` por `try/finally + browser.close()` |
| `AsyncCamoufox(..., persistent_context=True, user_data_dir=path)` | `await launch_persistent_context_async(path, headless=...)` | Retorna context direto (não browser) |
| `async_playwright() → p.chromium.launch_persistent_context(user_data_dir=..., executable_path=..., args=[...])` | `await launch_persistent_context_async(path, headless=...)` | Elimina `executable_path`, `args`, `find_chrome_executable()` |

### APIs que NÃO mudam (Playwright-compatível)

- `context.add_cookies([...])`
- `context.add_init_script(...)` — ainda funciona mas não é mais necessário para webdriver
- `page.evaluate(...)`
- `page.goto(...)`
- `page.title()`
- `page.mouse.move(...)` / `page.mouse.wheel(...)`
- `page.wait_for_function(...)`
- `page.route(...)` / `route.fetch()` / `route.fulfill(...)` / `route.continue_()`
- `page.is_closed()`
- `context.pages`

### Coisas que são REMOVIDAS (não necessárias com CloakBrowser)

- `main_world_eval=True` — conceito Firefox-only (Xray wrappers)
- `find_chrome_executable()` — CloakBrowser traz binário próprio
- `executable_path=chrome_path` — não necessário
- `--disable-blink-features=AutomationControlled` — CloakBrowser já patcha isso
- `--no-first-run`, `--no-default-browser-check` — desnecessário
- `Object.defineProperty(navigator, 'webdriver', {get: () => undefined})` — CloakBrowser já esconde

---

## Inventário Completo de Alterações por Arquivo

### `requirements.txt`
- Remover: `camoufox`, `playwright`
- Adicionar: `cloakbrowser`

### `pyproject.toml`
- Dependências: remover `camoufox`, `playwright`, adicionar `cloakbrowser`
- Pytest marker: `camoufox` → `cloakbrowser`

### `src/constants.py` (2 constantes)
- `DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_PROXY_WINDOW_MODE`
- `DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_FETCH_WINDOW_MODE`

### `src/config.py` (4 referências)
- 2x `setdefault` com config keys renomeadas
- 2x defaults dict com config keys renomeadas
- Referências às constantes renomeadas

### `src/browser_utils.py` (2 funções)
- `_normalize_camoufox_window_mode()` → `_normalize_cloakbrowser_window_mode()`
- `_maybe_apply_camoufox_window_mode()` → `_maybe_apply_cloakbrowser_window_mode()`
- Lógica interna: sem mudança (Win32 API puro)

### `src/main.py` (~15 alterações)
- **Imports**: Remover `AsyncCamoufox`, adicionar `cloakbrowser` functions
- **Imports de browser_utils**: nomes renomeados
- **Constantes alias**: 2 renomeações
- **`get_initial_data()`**: `AsyncCamoufox` → `launch_async` + try/finally
- **Transport selection**: referências a "camoufox" em debug strings
- **Re-exports**: manter aliases temporários para backward compat
- **`camoufox_proxy_worker` task**: renomear chamada

### `src/recaptcha.py` (~20 alterações)
- **`get_recaptcha_v3_token_with_chrome()`**: Trocar `async_playwright` + `p.chromium.launch_persistent_context` por `launch_persistent_context_async`. Remover hacks stealth. Manter lógica de cookies e evaluate.
- **`get_recaptcha_v3_token()` (fallback)**: `AsyncCamoufox` → `launch_async`. Remover `main_world_eval`.
- **`_camoufox_proxy_signup_anonymous_user()`**: Renomear para `_cloakbrowser_proxy_signup_anonymous_user()`. Lógica interna inalterada (recebe `page`).
- **Debug strings**: todas as menções "Camoufox" → "CloakBrowser"

### `src/transport.py` (~100+ alterações, arquivo mais complexo)
- **`fetch_lmarena_stream_via_chrome()` (~200 linhas)**: `async_playwright` → `launch_persistent_context_async`. Remover `find_chrome_executable`, args stealth, `add_init_script`.
- **`fetch_lmarena_stream_via_camoufox()` (~440 linhas)**: Renomear para `fetch_lmarena_stream_via_cloakbrowser()`. `AsyncCamoufox` → `launch_async`. Remover `main_world_eval`, `add_init_script`.
- **`camoufox_proxy_worker()` (~1050 linhas)**: Renomear para `cloakbrowser_proxy_worker()`. Adaptar lifecycle: `AsyncCamoufox.__aenter__/__aexit__` → `launch_async/launch_persistent_context_async + close()`. Config keys renomeadas. Debug strings atualizadas.
- **Aliases backward compat**: manter nomes antigos apontando para novos

### Testes (~8 arquivos)
- Renomear 2 arquivos de teste (camoufox no nome)
- Atualizar mock targets (`AsyncCamoufox` → `cloakbrowser_launch_async`, `async_playwright` → `cloakbrowser_launch_persistent_context_async`)
- Adaptar padrão de mock: context manager → coroutine return
- Atualizar config keys e nomes de funções nos asserts

---

## Config Keys: Mapeamento Antigo → Novo

| Chave antiga | Chave nova |
|---|---|
| `camoufox_proxy_window_mode` | `cloakbrowser_proxy_window_mode` |
| `camoufox_fetch_window_mode` | `cloakbrowser_fetch_window_mode` |
| `camoufox_proxy_headless` | `cloakbrowser_proxy_headless` |
| `camoufox_fetch_headless` | `cloakbrowser_fetch_headless` |
| `camoufox_proxy_launch_timeout_seconds` | `cloakbrowser_proxy_launch_timeout_seconds` |
| `camoufox_fetch_outer_timeout_seconds` | `cloakbrowser_fetch_outer_timeout_seconds` |
| `camoufox_proxy_user_data_dir` | `cloakbrowser_proxy_user_data_dir` |
| `camoufox_proxy_persistent_context` | `cloakbrowser_proxy_persistent_context` |
| `chrome_fetch_window_mode` | `chrome_fetch_window_mode` (sem mudança — já era Chrome) |
| `chrome_fetch_outer_timeout_seconds` | `chrome_fetch_outer_timeout_seconds` (sem mudança) |

---

## Lifecycle Management: Antes vs Depois

### Padrão Camoufox (context manager)
```python
async with AsyncCamoufox(headless=True, main_world_eval=True) as browser:
    context = await browser.new_context()
    page = await context.new_page()
    # ... usa page ...
# browser fecha automaticamente
```

### Padrão CloakBrowser (launch + close)
```python
browser = await cloakbrowser_launch_async(headless=True)
try:
    context = await browser.new_context()
    page = await context.new_page()
    # ... usa page ...
finally:
    await browser.close()
```

### Padrão CloakBrowser (persistent context)
```python
context = await cloakbrowser_launch_persistent_context_async("./profile", headless=True)
try:
    page = await context.new_page()
    # ... usa page ...
finally:
    await context.close()
```

### Proxy Worker (lifecycle manual complexo)
```python
# ANTES:
browser_cm = AsyncCamoufox(headless=headless, main_world_eval=True)
browser = await asyncio.wait_for(browser_cm.__aenter__(), timeout=timeout)
# ... no cleanup:
await browser_cm.__aexit__(None, None, None)

# DEPOIS:
browser = await asyncio.wait_for(cloakbrowser_launch_async(headless=headless), timeout=timeout)
# ... no cleanup:
await browser.close()
```

---

## Padrão de Mock nos Testes: Antes vs Depois

### Mock de AsyncCamoufox (context manager)
```python
# ANTES:
@patch("src.main.AsyncCamoufox")
async def test_x(self, mock_camoufox):
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_camoufox.return_value.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_camoufox.return_value.__aexit__ = AsyncMock(return_value=False)
```

### Mock de CloakBrowser (launch async)
```python
# DEPOIS:
@patch("src.main.cloakbrowser_launch_async")
async def test_x(self, mock_launch):
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    mock_launch.return_value = mock_browser
```

### Mock de Playwright persistent context
```python
# ANTES:
@patch("src.transport.async_playwright")
async def test_x(self, mock_pw):
    mock_context = AsyncMock()
    mock_pw.return_value.__aenter__.return_value.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

# DEPOIS:
@patch("src.main.cloakbrowser_launch_persistent_context_async")
async def test_x(self, mock_launch):
    mock_context = AsyncMock()
    mock_context.close = AsyncMock()
    mock_launch.return_value = mock_context
```

---

## Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| CloakBrowser é mais novo (reputação "Medium") | Manter aliases backward compat para rollback rápido |
| Bug no CloakBrowser com cookies/persistent context | Testar extensivamente antes de deploy |
| `page.evaluate()` comportamento diferente do Camoufox `main_world_eval` | CloakBrowser é Chromium — `evaluate()` já roda no main world, sem Xray wrappers |
| Config keys antigas em configs existentes dos usuários | Podemos adicionar migration logic que lê keys antigas como fallback |

---

## Ordem de Execução: 8 Fases

1. **Dependências** — `requirements.txt`, `pyproject.toml`
2. **Constants + Config** — `src/constants.py`, `src/config.py`
3. **Browser Utils** — `src/browser_utils.py`
4. **Main (imports + startup)** — `src/main.py`
5. **reCAPTCHA** — `src/recaptcha.py`
6. **Transport (fetch functions)** — `src/transport.py` (2 funções fetch)
7. **Transport (proxy worker)** — `src/transport.py` (proxy worker + main.py task)
8. **Testes** — todos os `tests/test_*.py` afetados
