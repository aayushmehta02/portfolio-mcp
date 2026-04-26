"""
Fyers OAuth flow (API v3).

Same browser-based experience as Upstox:
  1. Browser opens to the Fyers login page.
  2. User logs in normally.
  3. Fyers redirects to the Vercel callback page with ?code=...&state=localhost
  4. Vercel page forwards to the local server.
  5. Code is exchanged for an access token.

Fyers token exchange requires: SHA256(app_id:secret_key) as appIdHash.
"""
from __future__ import annotations

import hashlib
import webbrowser
from urllib.parse import urlencode

import httpx

from portfolio_mcp.auth.local_callback import DEFAULT_PORT, wait_for_code

REDIRECT_URI   = f"http://localhost:{DEFAULT_PORT}/callback"
SUCCESS_URL    = "https://web-portfolio-amber-one.vercel.app/connected"
AUTH_URL       = "https://api-t1.fyers.in/api/v3/generate-authcode"
TOKEN_URL      = "https://api-t1.fyers.in/api/v3/validate-authcode"


def _app_id_hash(app_id: str, secret_key: str) -> str:
    """Fyers requires SHA256(app_id:secret_key) for token exchange."""
    raw = f"{app_id}:{secret_key}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def do_oauth_flow(app_id: str, secret_key: str) -> str:
    """
    Full browser OAuth flow for Fyers.
    Opens browser → waits for callback → exchanges code → returns access token.
    The returned token should be stored as FYERS_ACCESS_TOKEN in .env.
    """
    auth_url = AUTH_URL + "?" + urlencode({
        "client_id":     app_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
    })

    webbrowser.open(auth_url)

    code = await wait_for_code(
        port=DEFAULT_PORT,
        success_url=SUCCESS_URL,
        error_url=SUCCESS_URL,
    )

    resp = httpx.post(
        TOKEN_URL,
        json={
            "grant_type":  "authorization_code",
            "appIdHash":   _app_id_hash(app_id, secret_key),
            "code":        code,
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Fyers token exchange failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in Fyers response: {data}")

    return token
