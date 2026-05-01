"""
LMArena Account Creator — Batch token farming for LMArenaBridge.

Creates LMArena accounts via CloakBrowser and harvests
arena-auth-prod-v1 tokens. Supports both anonymous and email-verified modes.

Usage:
    # Anonymous accounts (fast, no email needed)
    python -m tools.account_creator --count 5

    # Email-verified accounts (uses @duck.com + mail.tm)
    python -m tools.account_creator --count 3 --verified

    # Without IPv6 rotation
    python -m tools.account_creator --count 1 --no-ipv6
"""

import asyncio
import argparse
import json
import os
import re
import sys
import time
import uuid
import base64
import random
import string
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.ip_rotator import IPRotator

try:
    from cloakbrowser import launch_async as cloakbrowser_launch_async
except ImportError:
    print("ERROR: cloakbrowser not installed. Run: pip install cloakbrowser")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
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

# DuckDuckGo Email Protection
DDG_API_URL = "https://quack.duckduckgo.com/api/email/addresses"

# Mail.tm (for receiving forwarded @duck.com emails)
MAILTM_API_URL = "https://api.mail.tm"
EMAIL_POLL_INTERVAL = 3  # seconds between inbox checks
EMAIL_POLL_TIMEOUT = 120  # max wait for verification email


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


def save_account(token: str, provisional_id: str, *, email: str = "", password: str = "") -> None:
    """Save account metadata for reference."""
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ACCOUNTS_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"accounts": [], "last_updated": None}

    entry = {
        "provisional_user_id": provisional_id,
        "token_prefix": token[:40] + "...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }
    if email:
        entry["email"] = email
    if password:
        entry["password"] = password

    data["accounts"].append(entry)
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
# DuckDuckGo Email Protection (generates @duck.com aliases)
# ---------------------------------------------------------------------------

class DuckEmailService:
    """Generates @duck.com aliases via DuckDuckGo Email Protection API."""

    def __init__(self, token: str):
        self._token = token

    async def generate_alias(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DDG_API_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            address = data.get("address", "")
            if not address:
                raise ValueError(f"DDG API returned no address: {data}")
            return f"{address}@duck.com"


# ---------------------------------------------------------------------------
# Mail.tm inbox reader (receives forwarded @duck.com emails)
# ---------------------------------------------------------------------------

class MailTmInbox:
    """Reads emails from a mail.tm account to get verification links."""

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._token = ""

    async def login(self) -> bool:
        async with httpx.AsyncClient(base_url=MAILTM_API_URL, timeout=30.0) as client:
            try:
                resp = await client.post("/token", json={
                    "address": self._email,
                    "password": self._password,
                })
                resp.raise_for_status()
                self._token = resp.json().get("token", "")
                return bool(self._token)
            except Exception as e:
                log(f"  ❌ Mail.tm login failed: {e}")
                return False

    async def wait_for_magic_link(self, target_email: str, timeout: int = EMAIL_POLL_TIMEOUT) -> Optional[str]:
        """
        Poll inbox until we receive the LMArena magic link email.
        
        Returns the verification URL or None on timeout.
        """
        if not self._token:
            if not await self.login():
                return None

        start = time.time()
        checked_ids: set[str] = set()
        headers = {"Authorization": f"Bearer {self._token}"}

        log(f"  📬 Polling inbox for magic link (timeout {timeout}s)...")

        async with httpx.AsyncClient(base_url=MAILTM_API_URL, timeout=30.0) as client:
            while time.time() - start < timeout:
                try:
                    resp = await client.get("/messages", headers=headers)
                    if resp.status_code == 401:
                        # Token expired, re-login
                        if not await self.login():
                            return None
                        headers = {"Authorization": f"Bearer {self._token}"}
                        continue
                    resp.raise_for_status()
                    data = resp.json()

                    messages = data.get("hydra:member", data) if isinstance(data, dict) else data
                    if not isinstance(messages, list):
                        messages = []

                    for msg in messages:
                        msg_id = msg.get("id", "")
                        if msg_id in checked_ids:
                            continue
                        checked_ids.add(msg_id)

                        # Check if this is from LMArena/Supabase
                        from_addr = msg.get("from", {})
                        if isinstance(from_addr, dict):
                            from_email = from_addr.get("address", "").lower()
                        else:
                            from_email = str(from_addr).lower()
                        subject = str(msg.get("subject", "")).lower()

                        is_verification = (
                            "arena" in from_email or
                            "supabase" in from_email or
                            "verify" in subject or
                            "confirm" in subject or
                            "magic" in subject or
                            "sign in" in subject or
                            "log in" in subject
                        )

                        if not is_verification:
                            continue

                        # Get full message
                        detail_resp = await client.get(f"/messages/{msg_id}", headers=headers)
                        detail_resp.raise_for_status()
                        detail = detail_resp.json()

                        # Check if this email is for our target alias
                        text_body = detail.get("text", "")
                        html_body = ""
                        html_parts = detail.get("html", [])
                        if isinstance(html_parts, list):
                            html_body = "".join(html_parts)
                        elif isinstance(html_parts, str):
                            html_body = html_parts

                        # Some forwarded emails include the original recipient
                        full_content = text_body + html_body
                        # Extract magic link
                        link = self._extract_magic_link(full_content)
                        if link:
                            log(f"  📩 Magic link found! From: {from_email}")
                            return link

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        await self.login()
                        headers = {"Authorization": f"Bearer {self._token}"}
                    else:
                        log(f"  ⚠️ Inbox poll error: {e}")
                except Exception as e:
                    log(f"  ⚠️ Inbox poll error: {e}")

                elapsed = int(time.time() - start)
                if elapsed % 15 == 0 and elapsed > 0:
                    log(f"  ⏳ Still waiting... ({elapsed}s / {timeout}s)")

                await asyncio.sleep(EMAIL_POLL_INTERVAL)

        log(f"  ⏰ Timeout: No magic link received in {timeout}s")
        return None

    @staticmethod
    def _extract_magic_link(content: str) -> Optional[str]:
        """Extract verification/magic link from email content."""
        # Patterns for Supabase magic links
        patterns = [
            # Standard Supabase verify link
            r'(https?://[^\s<>"\']+/auth/v1/verify[^\s<>"\']*)',
            # arena.ai specific auth confirm
            r'(https?://[^\s<>"\']*arena\.ai[^\s<>"\']*(?:confirm|verify|callback|token)[^\s<>"\']*)',
            # Generic supabase auth links
            r'(https?://[^\s<>"\']*supabase[^\s<>"\']*(?:verify|confirm|token_hash)[^\s<>"\']*)',
            # href links with verify/confirm
            r'href=["\']([^"\']*(?:verify|confirm|magic|token_hash|auth/callback)[^"\']*)["\']',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                link = matches[0]
                # Clean HTML entities
                link = link.replace("&amp;", "&")
                return link
        return None


# ---------------------------------------------------------------------------
# Verified account creation (email + magic link)
# ---------------------------------------------------------------------------

def _generate_password(length: int = 16) -> str:
    """Generate a strong random password for the account."""
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    # Ensure at least one of each type
    pwd = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%&*"),
    ]
    pwd += [random.choice(chars) for _ in range(length - 4)]
    random.shuffle(pwd)
    return "".join(pwd)


# Store last created account credentials (used by batch loop)
_last_account_credentials: dict = {}


async def create_one_verified_account(
    *,
    proxy_url: Optional[str] = None,
    duck_email_service: Optional[DuckEmailService] = None,
    inbox: Optional[MailTmInbox] = None,
) -> Optional[str]:
    """
    Create a verified LMArena account using @duck.com email + magic link.

    Flow:
    1. Generate @duck.com alias
    2. POST /nextjs-api/sign-up/magic-link with email
    3. Poll mail.tm inbox for verification email  
    4. Follow the magic link in CloakBrowser to get the auth cookie
    
    Returns the arena-auth-prod-v1 token or None on failure.
    """
    if not duck_email_service or not inbox:
        log("  ❌ Duck email service and inbox required for verified mode")
        return None

    # Step 1: Generate @duck.com alias
    log("  🦆 Generating @duck.com alias...")
    try:
        email = await duck_email_service.generate_alias()
    except Exception as e:
        log(f"  ❌ Failed to generate duck alias: {e}")
        return None
    log(f"  📧 Email: {email}")

    # Store credentials for later retrieval
    account_password = _generate_password()
    _last_account_credentials.clear()
    _last_account_credentials["email"] = email
    _last_account_credentials["password"] = account_password

    # Generate random name
    first_names = [
        "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Jamie", "Quinn", "Avery",
        "Charlie", "Dakota", "Emerson", "Finley", "Harper", "Hayden", "Jesse", "Kai", "Logan", "Parker",
        "Peyton", "Reese", "River", "Rowan", "Sage", "Skyler", "Spencer", "Blake", "Cameron", "Drew",
        "Ellis", "Gray", "Harley", "Jaden", "Kennedy", "Lane", "Marlowe", "Nico", "Phoenix", "Remy",
        "Sawyer", "Tatum", "Wren", "Addison", "Bailey", "Corey", "Devon", "Eden", "Frankie", "Gage",
        "Hollis", "Indigo", "Jules", "Kit", "Lennox", "Milan", "Noel", "Oakley", "Paxton", "Raven",
        "Daniel", "Michael", "James", "Robert", "David", "William", "Lucas", "Henry", "Nathan", "Owen",
        "Emma", "Olivia", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Luna", "Ella", "Chloe",
        "Ethan", "Mason", "Liam", "Noah", "Oliver", "Benjamin", "Elijah", "Aiden", "Jackson", "Carter",
        "Grace", "Lily", "Zoe", "Hannah", "Aria", "Layla", "Nora", "Riley", "Stella", "Violet",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson", "Moore", "Clark",
        "Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia", "Martinez",
        "Robinson", "Lewis", "Lee", "Walker", "Hall", "Allen", "Young", "King", "Wright", "Scott",
        "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Rivera", "Mitchell",
        "Campbell", "Carter", "Roberts", "Phillips", "Evans", "Turner", "Parker", "Collins", "Edwards", "Stewart",
        "Morris", "Murphy", "Cook", "Rogers", "Morgan", "Peterson", "Cooper", "Reed", "Bailey", "Bell",
        "Howard", "Ward", "Cox", "Richardson", "Wood", "Watson", "Brooks", "Bennett", "Gray", "Price",
        "Sanders", "Powell", "Russell", "Foster", "Perry", "Butler", "Barnes", "Fisher", "Henderson", "Coleman",
        "Jenkins", "Patterson", "Graham", "Reynolds", "Hamilton", "Griffin", "Wallace", "West", "Cole", "Hayes",
        "Chapman", "Stone", "Fox", "Boyd", "Hart", "Mason", "Webb", "Burke", "Kelley", "Dunn",
    ]
    full_name = f"{random.choice(first_names)} {random.choice(last_names)}"

    # Step 2: Call /nextjs-api/sign-up/magic-link via httpx (no browser needed!)
    log("  📝 Calling /nextjs-api/sign-up/magic-link...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://arena.ai/nextjs-api/sign-up/magic-link",
                json={
                    "email": email,
                    "fullName": full_name,
                    "shouldLinkHistory": True,
                    "marketingConsent": False,
                    "registeredCountryCode": "BR",
                },
                headers={"Content-Type": "application/json"},
            )
            status = resp.status_code
            body = resp.text
    except Exception as e:
        log(f"  ❌ Magic link request failed: {e}")
        return None

    log(f"  📡 Response: HTTP {status}")
    if status >= 400:
        log(f"  ❌ Error: {body[:200]}")
        return None

    try:
        resp_data = json.loads(body)
        if not resp_data.get("success"):
            log(f"  ❌ API returned success=false: {body[:200]}")
            return None
    except Exception:
        pass

    log("  ✅ Magic link email sent!")

    # Step 3: Wait for email and extract magic link
    magic_link = await inbox.wait_for_magic_link(email, timeout=EMAIL_POLL_TIMEOUT)
    if not magic_link:
        log("  ❌ Did not receive magic link email")
        return None
    log(f"  🔗 Magic link: {magic_link[:80]}...")

    # Step 4: Open magic link in CloakBrowser to get the auth cookie
    log("  🌐 Opening magic link in CloakBrowser...")
    launch_kwargs = {"headless": True}
    if proxy_url:
        launch_kwargs["proxy"] = proxy_url

    browser = await cloakbrowser_launch_async(**launch_kwargs)
    try:
        page = await browser.new_page()
        await page.goto(magic_link, wait_until="domcontentloaded", timeout=60000)

        # Wait for Cloudflare if needed
        for i in range(10):
            title = await page.title()
            if "Just a moment" not in title:
                break
            await click_turnstile_widget(page)
            await asyncio.sleep(2)

        # Wait for redirect
        await asyncio.sleep(5)

        # Check if we landed on set-password page
        current_url = page.url
        if "/auth/set-password" in current_url or "set-password" in current_url:
            log("  🔑 Redirected to set-password page, filling password...")
            try:
                # Wait for form to load
                await page.wait_for_selector('input[type="password"]', timeout=10000)
                
                # Fill password fields
                password_inputs = await page.locator('input[type="password"]').all()
                for inp in password_inputs:
                    await inp.fill(account_password)
                    await asyncio.sleep(0.3)
                
                # Submit the form
                submit_btn = page.locator('button[type="submit"]')
                if await submit_btn.count() > 0:
                    await submit_btn.first.click()
                    log("  ✅ Password set, waiting for redirect...")
                    await asyncio.sleep(5)
                else:
                    # Try pressing Enter
                    await password_inputs[-1].press("Enter")
                    await asyncio.sleep(5)
            except Exception as e:
                log(f"  ⚠️ Password form interaction failed: {e}")

        # Extract the auth cookie
        context = page.context
        token = await get_auth_cookie_from_context(context, page)
        if token and is_token_valid(token):
            log("  ✅ Got verified auth token from cookie!")
            return token

        # Sometimes the page needs more time or does a JS redirect
        for _ in range(10):
            await asyncio.sleep(2)
            token = await get_auth_cookie_from_context(context, page)
            if token and is_token_valid(token):
                log("  ✅ Got verified auth token from cookie (delayed)!")
                return token

        # Last resort: check if the URL has token info
        current_url = page.url
        log(f"  ⚠️ Final URL: {current_url[:100]}")

        # Check if there's a hash fragment with tokens (Supabase PKCE flow)
        if "#" in current_url:
            fragment = current_url.split("#", 1)[1]
            params = dict(p.split("=", 1) for p in fragment.split("&") if "=" in p)
            access_token = params.get("access_token", "")
            refresh_token = params.get("refresh_token", "")
            if access_token and refresh_token:
                expires_in = int(params.get("expires_in", 3600))
                session = {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + expires_in,
                    "expires_in": expires_in,
                    "token_type": "bearer",
                }
                raw = json.dumps(session, separators=(",", ":")).encode("utf-8")
                b64 = base64.b64encode(raw).decode("utf-8").rstrip("=")
                token = "base64-" + b64
                if is_token_valid(token):
                    log("  ✅ Got verified auth token from URL fragment!")
                    return token

        log("  ❌ Could not extract token after following magic link")
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
    use_ipv6: bool = True,
    verified: bool = False,
) -> list[str]:
    """Create N accounts and return list of tokens."""
    tokens: list[str] = []
    rotator: Optional[IPRotator] = None
    duck_service: Optional[DuckEmailService] = None
    inbox: Optional[MailTmInbox] = None

    mode_str = "verified (email)" if verified else "anonymous"
    log(f"🚀 Starting batch creation of {count} {mode_str} account(s)")

    # Setup email services for verified mode
    if verified:
        config = load_config()
        ddg_token = config.get("ddg_email_token", "").strip()
        mailtm_email = config.get("mailtm_email", "").strip()
        mailtm_password = config.get("mailtm_password", "").strip()

        if not ddg_token:
            log("  ❌ ddg_email_token not found in config.json!")
            log("     Add: \"ddg_email_token\": \"your-duckduckgo-token\"")
            return []
        if not mailtm_email or not mailtm_password:
            log("  ❌ mailtm_email / mailtm_password not found in config.json!")
            log("     Add: \"mailtm_email\": \"your@mail.tm\", \"mailtm_password\": \"pass\"")
            return []

        duck_service = DuckEmailService(token=ddg_token)
        inbox = MailTmInbox(email=mailtm_email, password=mailtm_password)

        # Test inbox login
        log("  🔑 Testing mail.tm login...")
        if not await inbox.login():
            log("  ❌ Cannot connect to mail.tm inbox")
            return []
        log("  ✅ Mail.tm connected")

    # Setup IPv6 rotation
    if use_ipv6:
        rotator = IPRotator(port=40000)
        log("  🌐 Iniciando rotação de IPv6 residencial...")
        ok = await rotator.start()
        if ok:
            log(f"  ✅ IPv6 ativo: {rotator.current_ipv6}")
            log(f"  🔌 Proxy: {rotator.proxy_url}")
        else:
            log("  ⚠️ IPv6 indisponível, continuando sem rotação")
            rotator = None
    log("")

    try:
        for i in range(count):
            log(f"━━━ Account {i+1}/{count} ({mode_str}) ━━━")

            # Rotate IPv6 for each account (except first, already rotated on start)
            if rotator and i > 0:
                log(f"  🎲 Rotacionando IPv6...")
                await rotator.rotate()
                log(f"  🌐 Novo IPv6: {rotator.current_ipv6}")

            proxy_url = rotator.proxy_url if rotator else None

            try:
                if verified:
                    token = await create_one_verified_account(
                        proxy_url=proxy_url,
                        duck_email_service=duck_service,
                        inbox=inbox,
                    )
                else:
                    token = await create_one_account(proxy_url=proxy_url)

                if token:
                    tokens.append(token)
                    add_token_to_config(token)
                    creds = _last_account_credentials.copy() if verified else {}
                    save_account(
                        token, f"{'verified' if verified else 'anon'}-{i+1}",
                        email=creds.get("email", ""),
                        password=creds.get("password", ""),
                    )
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
    finally:
        if rotator:
            log("🧹 Limpando IPv6 adicionados...")
            await rotator.stop()
            log("  ✅ Cleanup completo")

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
    parser.add_argument("--no-ipv6", action="store_true", help="Disable IPv6 rotation (use direct IP)")
    parser.add_argument("--verified", "-v", action="store_true",
                        help="Create email-verified accounts via @duck.com + magic link")

    args = parser.parse_args()

    mode = "Email-Verified (@duck.com)" if args.verified else "Anonymous"
    print(f"""
╔══════════════════════════════════════════╗
║     LMArena Account Creator              ║
║     Mode: {mode:<30}║
╚══════════════════════════════════════════╝
""")

    log(f"Config: count={args.count}, delay={args.delay}s, ipv6={'off' if args.no_ipv6 else 'on'}, verified={args.verified}")
    if args.verified:
        log("  📋 Requires in config.json: ddg_email_token, mailtm_email, mailtm_password")
    log("")

    try:
        tokens = asyncio.run(create_accounts(
            count=args.count,
            delay_seconds=args.delay,
            use_ipv6=not args.no_ipv6,
            verified=args.verified,
        ))
    except KeyboardInterrupt:
        log("\n⚠️ Interrupted by user")
        tokens = []
    except (asyncio.CancelledError, SystemExit):
        tokens = []

    sys.exit(0 if tokens else 1)


if __name__ == "__main__":
    main()
