# Fase 2 — Constants + Config

Continuando a migração de Camoufox → CloakBrowser.

FASE 2: Atualizar constants.py e config.py.

Em `src/constants.py`:
- Renomear `DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_PROXY_WINDOW_MODE`
- Renomear `DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE` → `DEFAULT_CLOAKBROWSER_FETCH_WINDOW_MODE`

Em `src/config.py`:
- Onde referencia `constants.DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE`, trocar para `constants.DEFAULT_CLOAKBROWSER_PROXY_WINDOW_MODE`
- Onde referencia `constants.DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE`, trocar para `constants.DEFAULT_CLOAKBROWSER_FETCH_WINDOW_MODE`
- Renomear as config keys de `"camoufox_proxy_window_mode"` → `"cloakbrowser_proxy_window_mode"` e `"camoufox_fetch_window_mode"` → `"cloakbrowser_fetch_window_mode"` (tanto nos setdefault quanto nos defaults dict)

NÃO altere nenhum outro arquivo nesta fase.
