# Fase 7 — transport.py (proxy worker)

Continuando a migração de Camoufox → CloakBrowser.

FASE 7: Atualizar src/transport.py — a função camoufox_proxy_worker() (renomear para cloakbrowser_proxy_worker).

Esta é a função mais complexa (~1050 linhas). Ela gerencia um browser singleton persistente.

Alterações:

1. Renomear `camoufox_proxy_worker()` → `cloakbrowser_proxy_worker()`
   Adicionar alias: `camoufox_proxy_worker = cloakbrowser_proxy_worker`

2. Na seção de LAUNCH (~linha 1820-1870):
   - O código atual usa `_m().AsyncCamoufox(...)` com `__aenter__`/`__aexit__` manual
   - SUBSTITUIR o padrão de persistent context:
     ```python
     browser_cm = _m().AsyncCamoufox(
         headless=headless, main_world_eval=True,
         persistent_context=True, user_data_dir=str(profile_dir),
     )
     ```
     POR: usar `_m().cloakbrowser_launch_persistent_context_async(str(profile_dir), headless=headless)`
     NOTA: Isso retorna diretamente o context (não precisa de __aenter__). Ajustar o lifecycle.
   
   - SUBSTITUIR o padrão não-persistente:
     ```python
     browser_cm = _m().AsyncCamoufox(headless=headless, main_world_eval=True)
     ```
     POR: usar `_m().cloakbrowser_launch_async(headless=headless)`
     Depois `context = await browser.new_context(...)`

   - O código atual faz `browser = await asyncio.wait_for(browser_cm.__aenter__(), timeout=launch_timeout)`.
     Adaptar para: `browser = await asyncio.wait_for(_m().cloakbrowser_launch_async(headless=headless), timeout=launch_timeout)`

   - REMOVER `main_world_eval=True` de todas as chamadas
   - REMOVER o bloco `add_init_script("Object.defineProperty(navigator, 'webdriver'...")`

3. Na seção de CLEANUP (quando needs_launch=True):
   - O código atual faz `await browser_cm.__aexit__(None, None, None)`
   - SUBSTITUIR por: `await browser.close()` (ou `await context.close()` dependendo do tipo)

4. Config keys:
   - `camoufox_proxy_headless` → `cloakbrowser_proxy_headless`
   - `camoufox_proxy_launch_timeout_seconds` → `cloakbrowser_proxy_launch_timeout_seconds`
   - `camoufox_proxy_user_data_dir` → `cloakbrowser_proxy_user_data_dir`
   - `camoufox_proxy_persistent_context` → `cloakbrowser_proxy_persistent_context`
   - `camoufox_proxy_window_mode` → `cloakbrowser_proxy_window_mode`

5. Trocar `_maybe_apply_camoufox_window_mode` → `_maybe_apply_cloakbrowser_window_mode`

6. Atualizar TODAS as strings de debug de "Camoufox" / "🦊" para "CloakBrowser" / "🔒" nesta função.

7. A lógica interna de Turnstile handling, signup, cookie management, job execution via page.evaluate — tudo PERMANECE IGUAL. Só muda o launch/lifecycle do browser.

CUIDADO com o lifecycle management: O proxy_worker gerencia browser/context/page manualmente com health checks. O padrão antigo era context manager (AsyncCamoufox), o novo é launch + close. Garanta que:
- Em caso de exception no launch, o cleanup acontece
- O retry sem persistence funciona
- `persistent_context_enabled` quando True: context = browser (retorno direto do launch_persistent_context_async)
- `persistent_context_enabled` quando False: browser = launch_async, context = browser.new_context()

Também atualize em main.py:
- O import `camoufox_proxy_worker` de transport para incluir o novo nome
- A chamada `asyncio.create_task(camoufox_proxy_worker())` → `asyncio.create_task(cloakbrowser_proxy_worker())`

NÃO mexa em testes nesta fase.
