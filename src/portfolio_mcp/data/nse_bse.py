"""
NSE/BSE direct data source.
Uses NSE India's unofficial JSON endpoints (no auth needed) for:
  - Corporate actions (dividends, splits, buybacks, bonus)
  - Recent exchange filings / announcements
"""
from __future__ import annotations

import logging
from contextlib import aclosing
from datetime import datetime

import httpx

from portfolio_mcp.schemas import CorporateAction, Filing

logger = logging.getLogger(__name__)

NSE_BASE    = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.nseindia.com/",
}


async def _get_nse_client() -> httpx.AsyncClient:
    """Returns a client with NSE cookies primed (required to avoid 403)."""
    client = httpx.AsyncClient(headers=NSE_HEADERS, timeout=15, follow_redirects=True)
    # Prime the session cookie by hitting the homepage first
    try:
        await client.get(NSE_BASE)
    except Exception:
        pass
    return client


async def get_corporate_actions(ticker: str) -> list[CorporateAction]:
    """Fetch upcoming and recent corporate actions for a ticker from NSE."""
    actions: list[CorporateAction] = []
    try:
        client = await _get_nse_client()
        async with aclosing(client):
            resp = await client.get(
                f"{NSE_BASE}/api/corporates-corporateActions",
                params={"index": "equities", "symbol": ticker},
            )
            resp.raise_for_status()
            data = resp.json()

        for item in data:
            try:
                actions.append(CorporateAction(
                    action_type       = item.get("subject", "").lower(),
                    announcement_date = _parse_nse_date(item.get("exDate") or item.get("recDate", "")),
                    details           = item.get("subject", ""),
                ))
            except Exception:
                continue

    except Exception as e:
        logger.warning("NSE corporate actions fetch failed for %s: %s", ticker, e)

    return actions


async def get_filings(ticker: str, limit: int = 10) -> list[Filing]:
    """Fetch recent exchange filings / announcements for a ticker from NSE."""
    filings: list[Filing] = []
    try:
        client = await _get_nse_client()
        async with aclosing(client):
            resp = await client.get(
                f"{NSE_BASE}/api/quote-equity",
                params={"symbol": ticker, "section": "announcements"},
            )
            resp.raise_for_status()
            data = resp.json()

        announcements = data.get("announcements", [])[:limit]
        for item in announcements:
            try:
                filings.append(Filing(
                    filing_type = _classify_filing(item.get("desc", "")),
                    filed_at    = _parse_nse_date(item.get("an_dt", "")),
                    title       = item.get("desc", ""),
                    url         = item.get("attchmntFile"),
                ))
            except Exception:
                continue

    except Exception as e:
        logger.warning("NSE filings fetch failed for %s: %s", ticker, e)

    return filings


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_nse_date(date_str: str) -> datetime:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _classify_filing(description: str) -> str:
    desc = description.lower()
    if any(k in desc for k in ("result", "earnings", "profit", "loss", "quarterly")):
        return "earnings"
    if any(k in desc for k in ("pledge", "pledg")):
        return "pledging"
    if any(k in desc for k in ("board meeting", "board of directors")):
        return "board_meeting"
    if any(k in desc for k in ("dividend", "interim dividend")):
        return "dividend"
    if any(k in desc for k in ("buyback", "buy back")):
        return "buyback"
    if any(k in desc for k in ("split", "subdivision")):
        return "split"
    return "announcement"
