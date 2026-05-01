"""
LMArena Account Creator — Batch token farming for LMArenaBridge.

Creates anonymous LMArena accounts via CloakBrowser and harvests
arena-auth-prod-v1 tokens. Supports IPv6 rotation between accounts.

Usage:
    python -m tools.account_creator --count 5
    python -m tools.account_creator --count 3 --delay 15
    python -m tools.account_creator --count 1 --no-ipv6
"""

import asyncio
import argparse
import json
import os
import sys
import time
import uuid
import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from cloakbrowser import launch_async as cloakbrowser_launch_async
except ImportError:
    print("ERROR: cloakbrowser not installed. Run: pip install cloakbrowser")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_FILE = PROJECT_ROOT / "config.json"
ACCOUNTS_FILE = PROJECT_ROOT / "data" / "lmarena_accounts.json"
TURNSTILE_SITEKEY = "0x4AAAAAAA65vWDmG-O_lPtT"
RECAPTCHA_SITEKEY = "6Led_uYrAAAAAIP_9E8Ais_67Z6Vp4vdf40p8SQU"
RECAPTCHA_ACTION = "sign_up"
ARENA_URL = "https://arena.ai/?mode=direct"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config: dict) -> None:
    tmp = f"{CONFIG_FILE}.tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=4)
    os.replace(tmp, str(CONFIG_FILE))


def add_token_to_config(token: str) -> None:
    """Add a freshly minted token to config.json auth_tokens list."""
    config = load_config()
    tokens = config.get("auth_tokens", [])
    if token not in tokens:
        tokens.append(token)
        config["auth_tokens"] = tokens
        save_config(config)
        log(f"  ✅ Token added to config.json ({len(tokens)} total)")


def save_account(token: str, provisional_id: str) -> None:
    """Save account metadata for reference."""
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"accounts": [], "last_updated": None}

    data["accounts"].append({
        "provisional_user_id": provisional_id,
        "token_prefix": token[:40] + "...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    })
    data["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(ACCOUNTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def decode_token_expiry(token: str) -> Optional[float]:
    """Extract expiry from arena-auth-prod-v1 token."""
    if not token.startswith("base64-"):
        return None
    try:
        b64_part = token[7:]
        padding = 4 - (len(b64_part) % 4)
        if padding != 4:
            b64_part += "=" * padding
        raw = base64.b64decode(b64_part)
        session = json.loads(raw)
        return float(session.get("expires_at", 0))
    except Exception:
        return None


def is_token_valid(token: str) -> bool:
    """Check if token is non-expired."""
    expiry = decode_token_expiry(token)
    if expiry is None:
        return False
    return time.time() < (expiry - 60)


# ---------------------------------------------------------------------------
# Browser automation (CloakBrowser)
# ---------------------------------------------------------------------------

async def click_turnstile_widget(page) -> bool:
    """Best-effort click on any visible Turnstile iframe checkbox."""
    selectors = [
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[title*="Cloudflare"]',
        '#cf-turnstile iframe',
        '.cf-turnstile iframe',
    ]
    for sel in selectors:
        try:
            frames = page.frames
            for frame in frames:
                try:
                    url = frame.url or ""
                    if "challenges.cloudflare.com" in url:
                        cb = frame.locator('input[type="checkbox"]')
                        if await cb.count() > 0:
                            await cb.first.click(timeout=2000)
                            await asyncio.sleep(2)
                            return True
                except Exception:
                    pass
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click(timeout=2000)
                await asyncio.sleep(2)
                return True
        except Exception:
            pass
    return False


async def mint_turnstile_token(page) -> Optional[str]:
    """Render Turnstile widget and poll for token."""
    render_js = """async ({ sitekey }) => {
      const w = window;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

      // Cleanup previous
      try { const old = w.document.getElementById('lm-acct-turnstile'); if (old) old.remove(); } catch (e) {}

      // Ensure turnstile script loaded
      if (!w.turnstile || typeof w.turnstile.render !== 'function') {
        await new Promise((resolve) => {
          const s = w.document.createElement('script');
          s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
          s.async = true;
          s.onload = () => resolve(true);
          s.onerror = () => resolve(false);
          w.document.head.appendChild(s);
        });
        const start = Date.now();
        while ((Date.now() - start) < 15000) {
          if (w.turnstile && typeof w.turnstile.render === 'function') break;
          await sleep(250);
        }
      }

      if (!w.turnstile || typeof w.turnstile.render !== 'function') return { ok: false, widgetId: null };

      const el = w.document.createElement('div');
      el.id = 'lm-acct-turnstile';
      el.style.cssText = 'position:fixed;left:20px;top:20px;z-index:2147483647;';
      (w.document.body || w.document.documentElement).appendChild(el);

      w.__LM_ACCT_TURNSTILE_TOKEN = '';
      const widgetId = w.turnstile.render(el, {
        sitekey: sitekey,
        size: 'normal',
        appearance: 'interaction-only',
        callback: (tok) => { w.__LM_ACCT_TURNSTILE_TOKEN = String(tok || ''); },
        'error-callback': () => { w.__LM_ACCT_TURNSTILE_TOKEN = ''; },
        'expired-callback': () => { w.__LM_ACCT_TURNSTILE_TOKEN = ''; },
      });
      return { ok: true, widgetId: widgetId };
    }"""

    poll_js = """({ widgetId }) => {
      const w = window;
      try {
        const tok = w.__LM_ACCT_TURNSTILE_TOKEN;
        if (tok && String(tok).trim()) return String(tok);
        if (w.turnstile && typeof w.turnstile.getResponse === 'function') {
          return String(w.turnstile.getResponse(widgetId) || '');
        }
      } catch (e) {}
      return '';
    }"""

    cleanup_js = """({ widgetId }) => {
      const w = window;
      try { if (w.turnstile) w.turnstile.remove(widgetId); } catch (e) {}
      try { const el = w.document.getElementById('lm-acct-turnstile'); if (el) el.remove(); } catch (e) {}
      try { delete w.__LM_ACCT_TURNSTILE_TOKEN; } catch (e) {}
    }"""

    try:
        result = await asyncio.wait_for(
            page.evaluate(render_js, {"sitekey": TURNSTILE_SITEKEY}),
            timeout=30.0,
        )
    except Exception as e:
        log(f"  ⚠️ Turnstile render failed: {e}")
        return None

    if not isinstance(result, dict) or not result.get("ok"):
        log("  ⚠️ Turnstile render returned not ok")
        return None

    widget_id = result.get("widgetId")

    # Poll for token (up to 60 seconds)
    started = time.monotonic()
    token = ""
    while (time.monotonic() - started) < 60.0:
        try:
            cur = await asyncio.wait_for(
                page.evaluate(poll_js, {"widgetId": widget_id}),
                timeout=5.0,
            )
            token = str(cur or "").strip()
            if token:
                break
        except Exception:
            pass
        try:
            await click_turnstile_widget(page)
        except Exception:
            pass
        await asyncio.sleep(1.0)

    # Cleanup
    try:
        await page.evaluate(cleanup_js, {"widgetId": widget_id})
    except Exception:
        pass

    return token if token else None


async def mint_recaptcha_v3_token(page) -> Optional[str]:
    """Mint reCAPTCHA v3 token in CloakBrowser (score 0.9 native)."""
    mint_js = """async ({ sitekey, action }) => {
      const w = window;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

      // Ensure grecaptcha loaded
      if (!w.grecaptcha || !w.grecaptcha.enterprise) {
        const scriptUrl = `https://www.google.com/recaptcha/enterprise.js?render=${sitekey}`;
        await new Promise((resolve) => {
          const s = w.document.createElement('script');
          s.src = scriptUrl;
          s.async = true;
          s.onload = () => resolve(true);
          s.onerror = () => resolve(false);
          w.document.head.appendChild(s);
        });
        const start = Date.now();
        while ((Date.now() - start) < 15000) {
          if (w.grecaptcha && w.grecaptcha.enterprise && typeof w.grecaptcha.enterprise.execute === 'function') break;
          await sleep(250);
        }
      }

      const g = (w.grecaptcha?.enterprise && typeof w.grecaptcha.enterprise.execute === 'function')
        ? w.grecaptcha.enterprise
        : w.grecaptcha;
      if (!g || typeof g.execute !== 'function') return null;

      try {
        const token = await g.execute(sitekey, { action: action });
        return token || null;
      } catch (e) {
        return null;
      }
    }"""

    try:
        token = await asyncio.wait_for(
            page.evaluate(mint_js, {"sitekey": RECAPTCHA_SITEKEY, "action": RECAPTCHA_ACTION}),
            timeout=30.0,
        )
        return str(token) if token else None
    except Exception as e:
        log(f"  ⚠️ reCAPTCHA mint failed: {e}")
        return None


async def do_signup(page, turnstile_token: str, recaptcha_token: str, provisional_user_id: str) -> Optional[dict]:
    """Call /nextjs-api/sign-up with tokens."""
    signup_js = """async ({ turnstileToken, recaptchaToken, provisionalUserId }) => {
      const res = await fetch('/nextjs-api/sign-up', {
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          turnstileToken: String(turnstileToken || ''),
          recaptchaToken: String(recaptchaToken || ''),
          provisionalUserId: String(provisionalUserId || ''),
        }),
      });
      let text = '';
      try { text = await res.text(); } catch (e) {}
      return { status: Number(res.status || 0), ok: !!res.ok, body: String(text || '') };
    }"""

    try:
        resp = await asyncio.wait_for(
            page.evaluate(signup_js, {
                "turnstileToken": turnstile_token,
                "recaptchaToken": recaptcha_token,
                "provisionalUserId": provisional_user_id,
            }),
            timeout=20.0,
        )
        return resp if isinstance(resp, dict) else None
    except Exception as e:
        log(f"  ⚠️ Signup evaluate failed: {e}")
        return None


def build_cookie_from_response(body: str) -> Optional[str]:
    """Build arena-auth-prod-v1 cookie from signup response body."""
    text = str(body or "").strip()
    if not text:
        return None
    if text.startswith("base64-"):
        return text
    try:
        obj = json.loads(text)
    except Exception:
        return None

    def _is_session(val):
        if not isinstance(val, dict):
            return False
        return bool(val.get("access_token") and val.get("refresh_token"))

    session = None
    if isinstance(obj, dict):
        if _is_session(obj):
            session = obj
        elif _is_session(obj.get("session")):
            session = obj["session"]
        elif isinstance(obj.get("data"), dict):
            if _is_session(obj["data"]):
                session = obj["data"]
            elif _is_session(obj["data"].get("session")):
                session = obj["data"]["session"]

    if not session:
        return None

    # Ensure expires_at
    if not session.get("expires_at"):
        expires_in = int(session.get("expires_in") or 0)
        if expires_in > 0:
            session["expires_at"] = int(time.time()) + expires_in

    try:
        raw = json.dumps(session, separators=(",", ":")).encode("utf-8")
        b64 = base64.b64encode(raw).decode("utf-8").rstrip("=")
        return "base64-" + b64
    except Exception:
        return None


async def get_auth_cookie_from_context(context, page) -> Optional[str]:
    """Extract arena-auth-prod-v1 from browser cookies."""
    try:
        urls = ["https://arena.ai", "https://lmarena.ai"]
        for url in urls:
            try:
                cookies = await context.cookies(url)
                for c in cookies:
                    if c.get("name") == "arena-auth-prod-v1":
                        val = str(c.get("value") or "").strip()
                        if val and val.startswith("base64-"):
                            return val
            except Exception:
                pass
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main account creation flow
# ---------------------------------------------------------------------------

async def create_one_account(*, proxy_url: Optional[str] = None) -> Optional[str]:
    """
    Create a single anonymous LMArena account and return the arena-auth-prod-v1 token.
    
    Returns None on failure.
    """
    provisional_user_id = str(uuid.uuid4())
    log(f"  🆔 Provisional ID: {provisional_user_id[:8]}...")

    # Launch CloakBrowser
    launch_kwargs = {"headless": True}
    if proxy_url:
        launch_kwargs["proxy"] = proxy_url

    browser = await cloakbrowser_launch_async(**launch_kwargs)
    try:
        page = await browser.new_page()

        # Navigate to arena.ai
        log("  🌐 Navigating to arena.ai...")
        await page.goto(ARENA_URL, wait_until="domcontentloaded", timeout=60000)

        # Wait for Cloudflare challenge to pass
        for i in range(20):
            title = await page.title()
            if "Just a moment" not in title and "momento" not in title.lower():
                break
            log(f"  🛡️ Cloudflare challenge active (attempt {i+1}/20)...")
            await click_turnstile_widget(page)
            await asyncio.sleep(2)
        else:
            log("  ❌ Cloudflare challenge did not resolve in time")
            return None

        log("  ✅ Page loaded, Cloudflare passed")
        await asyncio.sleep(2)

        # Check if site already gave us an auth cookie (auto-signup)
        context = page.context
        existing = await get_auth_cookie_from_context(context, page)
        if existing and is_token_valid(existing):
            log("  🎁 Site auto-signed up! Got token from cookies directly")
            return existing

        # Step 1: Mint Turnstile token
        log("  🔄 Minting Turnstile token...")
        turnstile_token = await mint_turnstile_token(page)
        if not turnstile_token:
            log("  ❌ Failed to mint Turnstile token")
            return None
        log(f"  ✅ Turnstile token: {turnstile_token[:20]}...")

        # Step 2: Mint reCAPTCHA v3 token
        log("  🔄 Minting reCAPTCHA v3 token...")
        recaptcha_token = await mint_recaptcha_v3_token(page)
        if not recaptcha_token:
            log("  ❌ Failed to mint reCAPTCHA v3 token")
            return None
        log(f"  ✅ reCAPTCHA v3 token: {recaptcha_token[:20]}...")

        # Step 3: Signup
        log("  📝 Calling /nextjs-api/sign-up...")
        resp = await do_signup(page, turnstile_token, recaptcha_token, provisional_user_id)

        if not resp:
            log("  ❌ Signup returned None")
            return None

        status = int(resp.get("status") or 0)
        body = str(resp.get("body") or "")
        log(f"  📡 Signup response: HTTP {status}")

        if status >= 400:
            log(f"  ⚠️ Signup error body: {body[:200]}")

        # Try to extract token from response body
        cookie_from_body = build_cookie_from_response(body)
        if cookie_from_body and is_token_valid(cookie_from_body):
            log("  ✅ Got token from signup response body!")
            return cookie_from_body

        # Check cookies after signup
        await asyncio.sleep(2)
        cookie_from_ctx = await get_auth_cookie_from_context(context, page)
        if cookie_from_ctx and is_token_valid(cookie_from_ctx):
            log("  ✅ Got token from browser cookies!")
            return cookie_from_ctx

        # Wait a bit more for cookie to appear
        for _ in range(10):
            await asyncio.sleep(1)
            cookie_from_ctx = await get_auth_cookie_from_context(context, page)
            if cookie_from_ctx and is_token_valid(cookie_from_ctx):
                log("  ✅ Got token from browser cookies (delayed)!")
                return cookie_from_ctx

        log("  ❌ Could not extract auth token after signup")
        return None

    finally:
        try:
            await browser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Batch creation with optional IPv6 rotation
# ---------------------------------------------------------------------------

async def create_accounts(
    count: int = 1,
    delay_seconds: float = 10.0,
    proxy_url: Optional[str] = None,
) -> list[str]:
    """Create N accounts and return list of tokens."""
    tokens: list[str] = []

    log(f"🚀 Starting batch creation of {count} account(s)")
    if proxy_url:
        log(f"  🌐 Using proxy: {proxy_url}")
    log("")

    for i in range(count):
        log(f"━━━ Account {i+1}/{count} ━━━")
        try:
            token = await create_one_account(proxy_url=proxy_url)
            if token:
                tokens.append(token)
                add_token_to_config(token)
                save_account(token, f"batch-{i+1}")
                expiry = decode_token_expiry(token)
                if expiry:
                    exp_str = datetime.fromtimestamp(expiry, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    log(f"  📅 Token expires: {exp_str}")
            else:
                log("  ❌ Account creation failed")
        except Exception as e:
            log(f"  ❌ Exception: {type(e).__name__}: {e}")

        if i < count - 1:
            log(f"  ⏳ Waiting {delay_seconds}s before next account...")
            await asyncio.sleep(delay_seconds)
        log("")

    log(f"━━━ Summary ━━━")
    log(f"  ✅ Created: {len(tokens)}/{count}")
    log(f"  ❌ Failed: {count - len(tokens)}/{count}")
    if tokens:
        config = load_config()
        log(f"  🔑 Total tokens in config: {len(config.get('auth_tokens', []))}")

    return tokens


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LMArena Account Creator — batch farm auth tokens"
    )
    parser.add_argument("--count", "-n", type=int, default=1, help="Number of accounts to create")
    parser.add_argument("--delay", "-d", type=float, default=10.0, help="Delay between accounts (seconds)")
    parser.add_argument("--proxy", type=str, default=None, help="SOCKS5 proxy URL (e.g. socks5://127.0.0.1:40000)")
    parser.add_argument("--no-ipv6", action="store_true", help="Disable IPv6 rotation hint")

    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════╗
║     LMArena Account Creator              ║
║     CloakBrowser + Auto Signup           ║
╚══════════════════════════════════════════╝
""")

    log(f"Config: count={args.count}, delay={args.delay}s, proxy={args.proxy or 'none'}")
    log("")

    tokens = asyncio.run(create_accounts(
        count=args.count,
        delay_seconds=args.delay,
        proxy_url=args.proxy,
    ))

    sys.exit(0 if tokens else 1)


if __name__ == "__main__":
    main()
