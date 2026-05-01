# Fase 6 — transport.py (fetch functions)

Continuando a migração de Camoufox → CloakBrowser.

FASE 6: Atualizar src/transport.py — as funções fetch_lmarena_stream_via_chrome e fetch_lmarena_stream_via_camoufox.

API CloakBrowser para referência:
- `await _m().cloakbrowser_launch_persistent_context_async("./profile", headless=False)` → retorna context
- `await _m().cloakbrowser_launch_async(headless=True)` → retorna browser
- `await _m().cloakbrowser_launch_context_async(headless=True)` → retorna context
- Todas as APIs de page/context são Playwright-compatíveis (evaluate, goto, add_cookies, etc.)

1. Comentário do módulo (topo): trocar menções a "Camoufox" por "CloakBrowser".

2. Função `fetch_lmarena_stream_via_chrome()` (~linha 600):
   - REMOVER: `from playwright.async_api import async_playwright`
   - REMOVER: `chrome_path = _m().find_chrome_executable()` e o early return
   - SUBSTITUIR o bloco:
     ```python
     async with async_playwright() as p:
         context = await p.chromium.launch_persistent_context(
             user_data_dir=str(profile_dir),
             executable_path=chrome_path,
             headless=bool(headless),
             user_agent=user_agent or None,
             args=[...],
         )
     ```
     POR:
     ```python
     context = await _m().cloakbrowser_launch_persistent_context_async(
         str(profile_dir),
         headless=bool(headless),
     )
     ```
   - REMOVER o bloco `add_init_script("Object.defineProperty(navigator, 'webdriver'...")` 
   - Adaptar indentação: antes era `async with async_playwright()` como context manager; agora é try/finally com `await context.close()`
   - Toda a lógica de cookies, page.evaluate(), page.goto() permanece IDÊNTICA
   - Renomear para `fetch_lmarena_stream_via_cloakbrowser_chrome()` ou manter o nome antigo com alias

3. Função `fetch_lmarena_stream_via_camoufox()` (~linha 1112):
   - Renomear para `fetch_lmarena_stream_via_cloakbrowser()`
   - SUBSTITUIR `async with _m().AsyncCamoufox(headless=headless, main_world_eval=True) as browser:` por:
     `browser = await _m().cloakbrowser_launch_async(headless=headless)`
     Com try/finally + `await browser.close()`
   - REMOVER `main_world_eval=True`
   - REMOVER o bloco `add_init_script("Object.defineProperty(navigator, 'webdriver'...")`
   - `context = await browser.new_context(user_agent=user_agent or None)` — permanece igual
   - Toda a lógica de cookies, evaluate, goto permanece IDÊNTICA
   - Trocar `_maybe_apply_camoufox_window_mode` → `_maybe_apply_cloakbrowser_window_mode`
   - Trocar `mode_key="camoufox_fetch_window_mode"` → `mode_key="cloakbrowser_fetch_window_mode"`
   - Atualizar TODAS as strings de debug de "Camoufox" e "🦊" para "CloakBrowser" e emoji adequado (pode usar "🔒")
   - Config keys: trocar `camoufox_fetch_headless` → `cloakbrowser_fetch_headless`

IMPORTANTE: Mantenha aliases com os nomes antigos das funções para backward compat:
```python
fetch_lmarena_stream_via_camoufox = fetch_lmarena_stream_via_cloakbrowser  # backward compat
```

NÃO mexa na função camoufox_proxy_worker() nesta fase — ela será tratada na Fase 7.
NÃO altere nenhum outro arquivo.
