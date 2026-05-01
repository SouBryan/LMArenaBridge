# Fase 8 — Testes

Continuando a migração de Camoufox → CloakBrowser.

FASE 8 (FINAL): Atualizar todos os testes.

Contexto: Todos os testes usam `unittest.mock.patch` para mockar funções/classes. As referências de mock precisam apontar para os novos nomes.

Alterações necessárias por arquivo:

1. `tests/test_camoufox_window_mode.py`:
   - Renomear o arquivo para `tests/test_cloakbrowser_window_mode.py`
   - Atualizar mocks de `_normalize_camoufox_window_mode` → `_normalize_cloakbrowser_window_mode`
   - Atualizar mocks de `_maybe_apply_camoufox_window_mode` → `_maybe_apply_cloakbrowser_window_mode`
   - Atualizar referências a config keys `camoufox_*` → `cloakbrowser_*`

2. `tests/test_camoufox_proxy_anonymous_signup.py`:
   - Renomear para `tests/test_cloakbrowser_proxy_anonymous_signup.py`
   - Atualizar mocks de `_camoufox_proxy_signup_anonymous_user` → `_cloakbrowser_proxy_signup_anonymous_user`
   - Atualizar qualquer mock de `AsyncCamoufox` → mock de `cloakbrowser_launch_async`

3. `tests/test_initial_data_robustness.py`:
   - Trocar mocks de `src.main.AsyncCamoufox` → `src.main.cloakbrowser_launch_async`
   - Adaptar o mock: antes retornava um context manager, agora retorna uma coroutine que resolve para um browser mock

4. `tests/test_chrome_fetch_robustness.py`:
   - Trocar mocks de `playwright.async_api.async_playwright` → `src.main.cloakbrowser_launch_persistent_context_async`

5. `tests/test_chrome_fetch_window_mode.py`:
   - Trocar mocks de playwright → cloakbrowser
   - Atualizar config keys

6. `tests/test_recaptcha_chrome_fallback.py`:
   - Trocar mocks de `AsyncCamoufox` e `async_playwright` → `cloakbrowser_launch_async` e `cloakbrowser_launch_persistent_context_async`

7. Qualquer outro teste que mocke `fetch_lmarena_stream_via_camoufox`:
   - O alias backward compat garante que esses mocks ainda funcionem
   - Mas se quiser, pode atualizar para `fetch_lmarena_stream_via_cloakbrowser`

8. Em `tests/conftest.py`: se houver referência a camoufox marker, atualizar para cloakbrowser.

PADRÃO DE MOCK — antes:
```python
@patch("src.main.AsyncCamoufox")
async def test_x(self, mock_camoufox):
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_camoufox.return_value.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_camoufox.return_value.__aexit__ = AsyncMock(return_value=False)
```

PADRÃO DE MOCK — depois:
```python
@patch("src.main.cloakbrowser_launch_async")
async def test_x(self, mock_launch):
    mock_browser = AsyncMock()
    mock_page = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    mock_launch.return_value = mock_browser
```

PADRÃO DE MOCK para persistent context — antes:
```python
@patch("src.transport.async_playwright")
async def test_x(self, mock_pw):
    mock_context = AsyncMock()
    mock_pw.return_value.__aenter__.return_value.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
```

PADRÃO DE MOCK para persistent context — depois:
```python
@patch("src.main.cloakbrowser_launch_persistent_context_async")
async def test_x(self, mock_launch):
    mock_context = AsyncMock()
    mock_context.close = AsyncMock()
    mock_launch.return_value = mock_context
```

Após todas as alterações, rode `python -m pytest tests/ -v` e reporte o resultado.
