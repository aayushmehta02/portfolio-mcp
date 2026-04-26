"""
Upstox OAuth flow.

Opens the browser to the normal Upstox login page.
After the user logs in, Upstox redirects to the Vercel callback page which
forwards the auth code to the local server via the `state` parameter.
"""
from __future__ import annotations

import webbrowser
from urllib.parse import urlencode

import httpx

from portfolio_mcp.auth.local_callback import DEFAULT_PORT, wait_for_code

REDIRECT_URI  = "https://web-portfolio-amber-one.vercel.app/"
LOCAL_CALLBACK = f"http://localhost:{DEFAULT_PORT}/callback"
SUCCESS_URL    = "https://web-portfolio-amber-one.vercel.app/connected"
AUTH_URL       = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL      = "https://api.upstox.com/v2/login/authorization/token"


async def do_oauth_flow(api_key: str, api_secret: str) -> str:
    """
    Full browser OAuth flow for Upstox.
    Opens browser → waits for callback → exchanges code → returns access token.
    """
    auth_url = AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id":     api_key,
        "redirect_uri":  REDIRECT_URI,
        "state":         LOCAL_CALLBACK,
    })

    webbrowser.open(auth_url)

    code = await wait_for_code(
        port=DEFAULT_PORT,
        success_url=SUCCESS_URL,
        error_url=SUCCESS_URL,
    )

    resp = httpx.post(
        TOKEN_URL,
        data={
            "code":          code,
            "client_id":     api_key,
            "client_secret": api_secret,
            "redirect_uri":  REDIRECT_URI,
            "grant_type":    "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Upstox token exchange failed ({resp.status_code}): {resp.text}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in Upstox response: {data}")

    return token
