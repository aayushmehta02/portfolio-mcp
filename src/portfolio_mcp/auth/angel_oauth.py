"""
Angel One SmartAPI OAuth flow.

Publisher login flow:
  1. Open https://smartapi.angelone.in/publisher-login?api_key=<key>
  2. User logs in with client code + password + TOTP on the Angel One page
  3. Browser redirects to redirect_uri with ?auth_token=<token>
  4. We capture auth_token and store it as the access token

Register your redirect URI as http://127.0.0.1:8888 in the SmartAPI developer console.
"""
from __future__ import annotations

import webbrowser
from portfolio_mcp.auth.local_callback import wait_for_code

_LOGIN_URL = "https://smartapi.angelone.in/publisher-login"
_CALLBACK_PORT = 8888


async def do_oauth_flow(api_key: str) -> str:
    """
    Open the Angel One publisher login page, wait for the auth_token callback.
    Returns the access token string.
    """
    login_url = f"{_LOGIN_URL}?api_key={api_key}"
    webbrowser.open(login_url)

    # Angel One redirects back with ?auth_token=... (captured as "code" generically)
    token = await wait_for_code(
        port=_CALLBACK_PORT,
        success_url="",
        error_url="",
    )
    return token
