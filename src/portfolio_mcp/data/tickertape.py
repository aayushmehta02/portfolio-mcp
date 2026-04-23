"""
Tickertape fallback scraper.
Used when Screener returns incomplete data.
Tickertape is JS-rendered so we use their internal API endpoints.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from portfolio_mcp.data.screener import ScreenerData

logger = logging.getLogger(__name__)

TT_BASE = "https://api.tickertape.in"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Origin":     "https://www.tickertape.in",
    "Referer":    "https://www.tickertape.in/",
}


async def get_fundamentals(ticker: str) -> Optional[ScreenerData]:
    """
    Fetch fundamental data from Tickertape's internal API.
    Returns a ScreenerData (same shape) for easy merging with the pipeline.
    """
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
            # Step 1: Resolve ticker to Tickertape's internal SID
            search_resp = await client.get(
                f"{TT_BASE}/stocks/search",
                params={"text": ticker, "type": "stock"},
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("data", {}).get("stocks", [])
            if not results:
                return None

            # Pick the closest match (first NSE result)
            sid = next(
                (r["sid"] for r in results if r.get("exchange") == "NSE"),
                results[0]["sid"],
            )

            # Step 2: Fetch ratios
            ratios_resp = await client.get(
                f"{TT_BASE}/stocks/{sid}/ratios",
            )
            ratios_resp.raise_for_status()
            ratios = ratios_resp.json().get("data", {})

    except Exception as e:
        logger.warning("Tickertape fetch failed for %s: %s", ticker, e)
        return None

    return _parse_ratios(ticker, ratios)


def _parse_ratios(ticker: str, ratios: dict) -> ScreenerData:
    data = ScreenerData(ticker=ticker)

    def _f(key: str) -> Optional[float]:
        val = ratios.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    data.pe_ratio             = _f("peRatio") or _f("pe")
    data.pb_ratio             = _f("pbRatio") or _f("pb")
    data.market_cap           = _f("mktCap")
    data.eps                  = _f("eps")
    data.roe                  = _f("roe")
    data.roce                 = _f("roce")
    data.debt_to_equity       = _f("debtEquity") or _f("de")
    data.operating_margin     = _f("opm")
    data.promoter_holding_pct = _f("promoterHolding")
    data.revenue_growth_yoy   = _f("revenueGrowth1Y")
    data.earnings_growth_yoy  = _f("profitGrowth1Y")

    return data
