"""
Reusable local HTTP callback server for broker OAuth flows.

Starts a temporary HTTP server on localhost, waits for the browser to redirect
to it with ?code=..., then shuts down and returns the captured code.
"""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT  = 8888
TIMEOUT_SECS  = 180  # 3 minutes


def _make_handler(success_url: str, error_base_url: str):
    """Return a request handler class wired to the given redirect URLs."""

    class _Handler(BaseHTTPRequestHandler):
        received_code:  str | None = None
        received_error: str | None = None

        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            # Different brokers use different param names:
            # Fyers → auth_code, Upstox/Dhan → code, Angel One → auth_token,
            # ICICI Breeze → RequestToken, Dhan OAuth → tokenId
            # Check auth_code FIRST — Fyers also sends code=200 (HTTP status) which is not the auth code
            code = (
                qs.get("auth_code") or qs.get("auth_token") or
                qs.get("RequestToken") or qs.get("tokenId") or qs.get("code")
                or [None]
            )[0]
            if code:
                _Handler.received_code = code
                body = b"""<!DOCTYPE html><html><head><meta charset=UTF-8>
                <style>body{font-family:system-ui;display:flex;align-items:center;
                justify-content:center;height:100vh;margin:0;background:#f9fafb;}
                .card{text-align:center;padding:48px 40px;background:white;
                border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);}
                h2{color:#10b981;margin:0 0 8px;}p{color:#6b7280;margin:0;}</style>
                </head><body><div class="card"><div style="font-size:3rem">&#x2705;</div>
                <h2>You're connected!</h2>
                <p>You can close this tab and return to Claude.</p>
                </div></body></html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                error = qs.get("error", ["unknown"])[0]
                _Handler.received_error = error
                body = f"<html><body><h2>Connection failed: {error}</h2><p>Please try again from Claude.</p></body></html>".encode()
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *_):
            pass  # silence request logs

    return _Handler


async def wait_for_code(
    port: int,
    success_url: str,
    error_url: str,
    timeout: int = TIMEOUT_SECS,
) -> str:
    """
    Start a local server on `port`, wait for a ?code= callback, return the code.
    Redirects the browser to `success_url` on success or `error_url` on failure.
    Raises RuntimeError on timeout or auth denial.
    """
    Handler = _make_handler(success_url, error_url)
    Handler.received_code  = None
    Handler.received_error = None

    class _ReusableServer(HTTPServer):
        allow_reuse_address = True

    server = _ReusableServer(("127.0.0.1", port), Handler)
    server.timeout = 1  # poll in 1-second ticks

    loop = asyncio.get_event_loop()

    def _poll():
        import time
        deadline = time.time() + timeout
        while Handler.received_code is None and Handler.received_error is None:
            server.handle_request()
            if time.time() > deadline:
                break
        server.server_close()

    await loop.run_in_executor(None, _poll)

    if Handler.received_error:
        raise RuntimeError(f"OAuth denied by broker: {Handler.received_error}")
    if not Handler.received_code:
        raise RuntimeError(
            f"Authentication timed out after {timeout // 60} minutes. Please try again."
        )

    return Handler.received_code
