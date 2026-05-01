# Fase 5 — recaptcha.py

Continuando a migração de Camoufox → CloakBrowser.

FASE 5: Atualizar src/recaptcha.py.

Contexto da API CloakBrowser (Python async):
- `from cloakbrowser import launch_async, launch_context_async, launch_persistent_context_async`
- `browser = await launch_async(headless=True)` — retorna browser Playwright-compatível
- `ctx = await launch_context_async(headless=True, storage_state="state.json")` — retorna context
- `ctx = await launch_persistent_context_async("./profile", headless=True)` — retorna context com profile persistente
- `page.evaluate(...)`, `context.add_cookies(...)`, `page.goto(...)` — idênticos ao Playwright
- NÃO precisa de `main_world_eval` (conceito Firefox-only)
- NÃO precisa de `--disable-blink-features=AutomationControlled` (CloakBrowser já faz)
- NÃO precisa de `Object.defineProperty(navigator, 'webdriver', ...)` (CloakBrowser já esconde)

Alterações:

1. No comentário do módulo (topo), trocar menções a "Camoufox" por "CloakBrowser".

2. Função `get_recaptcha_v3_token_with_chrome()` (~linha 452):
   - REMOVER: `from playwright.async_api import async_playwright`
   - ADICIONAR: usar `_m().cloakbrowser_launch_persistent_context_async` (acessando via _m() para patchability nos testes)
   - REMOVER: `chrome_path = find_chrome_executable()` e o early return se não achar
   - SUBSTITUIR o bloco `async with async_playwright() as p: context = await p.chromium.launch_persistent_context(...)` por:
     `context = await _m().cloakbrowser_launch_persistent_context_async(str(profile_dir), headless=False)`
   - REMOVER os args `executable_path`, `--disable-blink-features=AutomationControlled`, `--no-first-run`, `--no-default-browser-check`
   - REMOVER o bloco `add_init_script("Object.defineProperty(navigator, 'webdriver'...")` — CloakBrowser já faz isso
   - Manter toda a lógica de cookies (add_cookies) e page.evaluate() EXATAMENTE igual
   - Adaptar o try/finally: antes usava `async with`, agora precisa de `try: ... finally: await context.close()`

3. Função `get_recaptcha_v3_token()` (fallback Camoufox, ~linha 635):
   - SUBSTITUIR `async with _m().AsyncCamoufox(headless=True, main_world_eval=True) as browser:` por:
     `browser = await _m().cloakbrowser_launch_async(headless=True)`
     E envolver em try/finally com `await browser.close()`
   - O `context = await browser.new_context()` continua igual
   - REMOVER `main_world_eval=True` (não existe em CloakBrowser, não é necessário)
   - O resto da lógica (goto, evaluate grecaptcha, Turnstile handling) fica IGUAL

4. Função `_camoufox_proxy_signup_anonymous_user()` (~linha 239):
   - Renomear para `_cloakbrowser_proxy_signup_anonymous_user()`
   - Esta função recebe `page` como parâmetro — a lógica interna NÃO muda
   - Apenas renomear e atualizar strings de debug de "Camoufox" para "CloakBrowser"

5. Atualizar TODAS as strings de debug_print que mencionem "Camoufox" para "CloakBrowser" neste arquivo.

NÃO altere nenhum outro arquivo nesta fase.
