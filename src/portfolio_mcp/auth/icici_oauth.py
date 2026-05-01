"""
ICICI Direct Breeze OAuth flow.

  1. Open https://api.icicidirect.com/apiuser/login?AppKey=<api_key>
  2. User logs in with their ICICI Direct credentials
  3. Browser redirects to redirect_uri with ?RequestToken=<token>
  4. Call breeze.generate_session(api_secret, session_token) to activate session
  5. The session's access_token is what we store

Register your redirect URI as http://127.0.0.1:8888 in the ICICI Direct developer portal.
"""
from __future__ import annotations

import webbrowser
from portfolio_mcp.auth.local_callback import wait_for_code

_LOGIN_URL     = "https://api.icicidirect.com/apiuser/login"
_CALLBACK_PORT = 8888


async def do_oauth_flow(api_key: str, api_secret: str) -> str:
    """
    Run the ICICI Breeze OAuth flow.
    Returns the session token string to be stored as ICICI_ACCESS_TOKEN.
    """
    from breeze_connect import BreezeConnect

    login_url = f"{_LOGIN_URL}?AppKey={api_key}"
    webbrowser.open(login_url)

    # ICICI redirects with ?RequestToken=<token>
    request_token = await wait_for_code(
        port=_CALLBACK_PORT,
        success_url="",
        error_url="",
    )

    # Exchange request token for a session
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=request_token)

    # The session token IS the access token we need to persist
    return request_token
