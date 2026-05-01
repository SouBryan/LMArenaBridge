# Fase 4 — main.py (imports + aliases + get_initial_data)

Continuando a migração de Camoufox → CloakBrowser.

FASE 4: Atualizar src/main.py — imports, aliases, e get_initial_data().

Alterações de imports (topo do arquivo):
1. REMOVER: `from camoufox.async_api import AsyncCamoufox`
2. ADICIONAR: `from cloakbrowser import launch_async as cloakbrowser_launch_async, launch_context_async as cloakbrowser_launch_context_async, launch_persistent_context_async as cloakbrowser_launch_persistent_context_async`
3. Onde importa `_normalize_camoufox_window_mode` de browser_utils, trocar para `_normalize_cloakbrowser_window_mode`
4. Onde importa `_maybe_apply_camoufox_window_mode` de browser_utils, trocar para `_maybe_apply_cloakbrowser_window_mode`
5. Onde importa `fetch_lmarena_stream_via_camoufox` de transport, manter o import mas vamos renomear na fase 7 — por agora NÃO mexa neste import.
6. Onde importa `_camoufox_proxy_signup_anonymous_user` de recaptcha, manter por agora.

Alterações de aliases/constantes (perto das linhas 134-135):
- Renomear `DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE = constants.DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_PROXY_WINDOW_MODE = constants.DEFAULT_CLOAKBROWSER_PROXY_WINDOW_MODE`
- Renomear `DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE = constants.DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_FETCH_WINDOW_MODE = constants.DEFAULT_CLOAKBROWSER_FETCH_WINDOW_MODE`

Alterações em get_initial_data() (~linha 806):
- Substituir `async with AsyncCamoufox(headless=True, main_world_eval=True) as browser:` por:
```python
browser = await cloakbrowser_launch_async(headless=True)
try:
```
- E no final do bloco que era o `async with`, adicionar `finally: await browser.close()` no nível correto de indentação.
- O corpo interno (page = await browser.new_page(), route interceptor, goto, etc.) permanece EXATAMENTE igual.

IMPORTANTE: Manter `AsyncCamoufox` como re-export no namespace do módulo para backward compat TEMPORÁRIA — adicione logo após os novos imports: `AsyncCamoufox = None  # DEPRECATED: será removido após migração completa`

Atualize strings de debug/log que mencionem "Camoufox" no contexto de get_initial_data() para "CloakBrowser".

NÃO altere nenhuma outra função em main.py nesta fase. NÃO mexa em transport.py, recaptcha.py, ou testes.
