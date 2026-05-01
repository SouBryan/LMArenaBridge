# Fase 3 — browser_utils.py

Continuando a migração de Camoufox → CloakBrowser.

FASE 3: Atualizar src/browser_utils.py.

Alterações:
1. Renomear a função `_normalize_camoufox_window_mode` → `_normalize_cloakbrowser_window_mode`. Atualizar docstring/comentários internos se mencionam "Camoufox".
2. Renomear a função `_maybe_apply_camoufox_window_mode` → `_maybe_apply_cloakbrowser_window_mode`. Atualizar docstring/comentários internos se mencionam "Camoufox".
3. Em qualquer comentário no topo do arquivo que mencione "Camoufox", trocar para "CloakBrowser".

A lógica interna dessas funções NÃO muda (é Win32 API puro, nada específico de browser). Apenas renomear funções e atualizar comentários/docstrings.

NÃO altere nenhum outro arquivo nesta fase.
