"""
Upstox token refresher — normal login flow.

Usage:
    python refresh_token.py

Flow:
  1. Opens Upstox login in your browser (same login you always use)
  2. After you approve, your browser lands on the redirect URL with ?code=...
  3. Paste that URL here — script extracts the code automatically
  4. Exchanges code for a fresh access token and writes it to .env
  5. Restart Claude desktop app — done.
"""

from __future__ import annotations

import re
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from dotenv import dotenv_values

# ── Config ─────────────────────────────────────────────────────────────────────

REDIRECT_URI = "https://web-portfolio-amber-one.vercel.app/"
AUTH_URL     = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL    = "https://api.upstox.com/v2/login/authorization/token"
ENV_FILE     = Path(__file__).parent / ".env"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        sys.exit(f"ERROR: .env not found at {ENV_FILE}")
    return dotenv_values(ENV_FILE)


def _update_token_in_env(new_token: str) -> None:
    text = ENV_FILE.read_text()
    if re.search(r"^UPSTOX_ACCESS_TOKEN\s*=", text, re.MULTILINE):
        text = re.sub(
            r"^(UPSTOX_ACCESS_TOKEN\s*=).*$",
            f"UPSTOX_ACCESS_TOKEN={new_token}",
            text,
            flags=re.MULTILINE,
        )
    else:
        text = text.rstrip("\n") + f"\nUPSTOX_ACCESS_TOKEN={new_token}\n"
    ENV_FILE.write_text(text)


def _extract_code(raw: str) -> str | None:
    """Extract ?code= from a full URL or a bare code string."""
    raw = raw.strip()
    if raw.startswith("http"):
        qs = parse_qs(urlparse(raw).query)
        codes = qs.get("code")
        return codes[0] if codes else None
    # user pasted just the code itself
    return raw if raw else None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    env = _read_env()
    api_key    = env.get("UPSTOX_API_KEY", "").strip()
    api_secret = env.get("UPSTOX_API_SECRET", "").strip()

    if not api_key or not api_secret:
        sys.exit("ERROR: UPSTOX_API_KEY and UPSTOX_API_SECRET must be set in .env")

    # Step 1 — open browser to normal Upstox login
    login_url = (
        AUTH_URL + "?" +
        urlencode({
            "response_type": "code",
            "client_id":     api_key,
            "redirect_uri":  REDIRECT_URI,
        })
    )

    print("\n── Upstox Token Refresh ──────────────────────────────────")
    print("Opening Upstox login in your browser...")
    print("Log in as you normally would.\n")
    webbrowser.open(login_url)

    # Step 2 — user pastes the redirect URL
    print("After you approve, your browser will land on your redirect page.")
    print("The URL will look like:")
    print(f"  {REDIRECT_URI}?code=XXXXXX...\n")
    print("Paste that full URL (or just the code) below and press Enter:")

    raw = input("  → ").strip()
    code = _extract_code(raw)

    if not code:
        sys.exit("ERROR: Could not find a code in what you pasted. Try again.")

    # Step 3 — exchange code for token
    print("\nExchanging code for access token...")
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
        sys.exit(f"ERROR: Token exchange failed ({resp.status_code}):\n{resp.text}")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        sys.exit(f"ERROR: No access_token in response:\n{data}")

    # Step 4 — write to .env
    _update_token_in_env(access_token)
    print("\n✓ .env updated with your new access token.")
    print("Restart the Claude desktop app and you're good to go.\n")


if __name__ == "__main__":
    main()
