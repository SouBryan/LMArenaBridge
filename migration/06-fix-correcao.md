# Correção da Fase 6 — código corrompido em transport.py

Há um bloco corrompido/duplicado entre `fetch_lmarena_stream_via_chrome` e `fetch_lmarena_stream_via_camoufox`. Preciso que você faça estas 2 correções:

**1. Remover o bloco corrompido.** No trecho abaixo, entre o `finally: await context.close()` que fecha `fetch_lmarena_stream_via_chrome` e o `async def fetch_lmarena_stream_via_camoufox`, existe código duplicado/lixo que precisa ser removido. O trecho corrompido começa logo após `await context.close()` (do finally de chrome) e vai até logo antes de `async def fetch_lmarena_stream_via_camoufox`. Remova essas linhas:

```python
                    await asyncio.sleep(min(2.0 * (2**attempt), 15.0))

async def fetch_lmarena_stream_via_cloakbrowser(
                int(result.get("status") or 0),
                result.get("headers") if isinstance(result, dict) else {},
                result.get("text") if isinstance(result, dict) else "",
                method=http_method,
                url=url,
            )
            return response
        except Exception as e:
            _m().debug_print(f"??? Chrome fetch transport failed: {e}")
            return None
        finally:
            await context.close()
```

Após a remoção, deve sobrar apenas 2 linhas em branco entre o `finally: await context.close()` do `fetch_lmarena_stream_via_chrome` e o `async def fetch_lmarena_stream_via_camoufox`.

**2. Renomear a função.** Após limpar o lixo, renomear `async def fetch_lmarena_stream_via_camoufox(` → `async def fetch_lmarena_stream_via_cloakbrowser(`. Não duplique — apenas renomeie a definição existente.

O alias backward compat que já existe no final do arquivo (`fetch_lmarena_stream_via_camoufox = fetch_lmarena_stream_via_cloakbrowser`) ficará correto automaticamente.

NÃO altere nenhum outro arquivo. NÃO mexa no proxy_worker nem em nenhuma outra parte do transport.py.
