"""
Dhan OAuth flow.

  1. Call DhanLogin.generate_login_session(app_id, app_secret) → consent_id
  2. Open https://login.dhan.co/login/<consent_id>
  3. User logs in on Dhan's page
  4. Browser redirects to redirect_uri with ?tokenId=<token_id>
  5. Call DhanLogin.consume_token_id(token_id, app_id, app_secret) → access_token

Register your redirect URI as http://127.0.0.1:8888 in the Dhan developer console.
"""
from __future__ import annotations

import webbrowser
import httpx
from portfolio_mcp.auth.local_callback import wait_for_code

_DHAN_BASE    = "https://login.dhan.co"
_CALLBACK_PORT = 8888


async def do_oauth_flow(client_id: str, app_id: str, app_secret: str) -> str:
    """
    Run the Dhan OAuth flow. Returns the access token string.
    """
    # Step 1: create a consent session
    resp = httpx.post(
        "https://api.dhan.co/v2/token",
        json={"clientId": client_id, "partnerClientId": app_id, "partnerSecret": app_secret},
        timeout=15,
    )
    data = resp.json()
    consent_id = data.get("consentId") or data.get("consent_id")
    if not consent_id:
        raise RuntimeError(f"Dhan: failed to create consent session — {data}")

    # Step 2: open browser
    login_url = f"{_DHAN_BASE}/login/{consent_id}"
    webbrowser.open(login_url)

    # Step 3: capture tokenId from redirect (arrives as ?tokenId=... or ?code=...)
    token_id = await wait_for_code(
        port=_CALLBACK_PORT,
        success_url="",
        error_url="",
    )

    # Step 4: exchange tokenId for access token
    resp2 = httpx.post(
        "https://api.dhan.co/v2/token/generate",
        json={"tokenId": token_id, "partnerClientId": app_id, "partnerSecret": app_secret},
        timeout=15,
    )
    data2 = resp2.json()
    access_token = data2.get("accessToken") or data2.get("access_token")
    if not access_token:
        raise RuntimeError(f"Dhan: failed to exchange tokenId for access token — {data2}")

    return access_token
