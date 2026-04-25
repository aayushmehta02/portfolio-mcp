"""
Data enrichment pipeline.

For each holding:
  1. Screener.in   → rich fundamentals (primary, cached 6 h)
  2. Tickertape    → fallback if Screener returns incomplete data
  3. NSE/BSE       → corporate actions + recent filings

All three run in parallel; results are merged into FundamentalData.
Partial data is flagged via sources_used so Claude can reflect on
what is available vs. missing.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from portfolio_mcp.data import (
    cache as cache_store,
    nse_bse,
    screener as screener_src,
    tickertape as tt_src,
)
from portfolio_mcp.schemas import FundamentalData, Holding

logger = logging.getLogger(__name__)

# Minimum fields needed to consider Screener data "sufficient"
_SCREENER_REQUIRED = {"pe_ratio", "debt_to_equity", "promoter_holding_pct"}


async def enrich(holding: Holding) -> FundamentalData:
    """
    Enrich a single holding with fundamental + corporate-action data.
    Uses the cache for Screener to avoid hammering the site.
    """
    ticker = holding.ticker
    data   = FundamentalData(ticker=ticker)

    # ── Screener (with cache) ─────────────────────────────────────────────
    screener_data = await _screener_with_cache(ticker)

    # ── NSE/BSE runs in parallel with the (potentially async) screener ────
    corp_actions, filings = await asyncio.gather(
        nse_bse.get_corporate_actions(ticker),
        nse_bse.get_filings(ticker),
    )

    # Apply NSE/BSE data
    data.corporate_actions = corp_actions
    data.recent_filings    = filings
    if corp_actions or filings:
        data.sources_used.append("nse_bse")

    # Apply Screener data
    if screener_data is not None:
        _merge_screener(data, screener_data)
        data.sources_used.append("screener")

    # Tickertape fallback if key fields are still missing
    if not _is_sufficient(data):
        logger.info("Screener data incomplete for %s — trying Tickertape", ticker)
        tt_data = await tt_src.get_fundamentals(ticker)
        if tt_data is not None:
            _merge_fallback(data, tt_data)
            data.sources_used.append("tickertape")

    return data


async def enrich_portfolio(holdings: list[Holding]) -> list[Holding]:
    """Enrich all holdings concurrently (max 5 at a time to be polite to sources)."""
    semaphore = asyncio.Semaphore(5)

    async def _bounded(h: Holding) -> Holding:
        async with semaphore:
            try:
                h.enriched = await enrich(h)
            except Exception as e:
                logger.error("Enrichment failed for %s: %s", h.ticker, e)
        return h

    return list(await asyncio.gather(*[_bounded(h) for h in holdings]))


# ---------------------------------------------------------------------------
# Cache-aware Screener fetch
# ---------------------------------------------------------------------------

async def _screener_with_cache(ticker: str):
    """
    Return ScreenerData for ticker, using the SQLite cache when fresh.
    Falls through to a live fetch on cache miss / expiry.
    """
    cached = cache_store.get_cached(ticker)
    if cached is not None:
        try:
            return screener_src.ScreenerData(**cached)
        except Exception:
            pass  # corrupt cache entry — fall through to live fetch

    live = await screener_src.get_fundamentals(ticker)
    if live is not None:
        cache_store.set_cached(ticker, live.model_dump())

    return live


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

_SCREENER_FIELDS = (
    "company_name", "pe_ratio", "pb_ratio", "market_cap", "book_value",
    "face_value", "dividend_yield", "eps", "roe", "roce",
    "operating_margin", "net_margin", "debt_to_equity", "interest_coverage",
    "current_ratio", "promoter_holding_pct", "promoter_pledge_pct",
    "fii_holding_pct", "dii_holding_pct", "public_holding_pct",
    "revenue_growth_yoy", "earnings_growth_yoy",
    "sales_cagr_3yr", "sales_cagr_5yr",
    "profit_cagr_3yr", "profit_cagr_5yr",
    "stock_cagr_3yr", "stock_cagr_5yr", "roe_3yr_avg",
    "annual_years", "annual_pnl", "quarterly_periods", "quarterly_pnl",
)


def _merge_screener(target: FundamentalData, src) -> None:
    """Copy Screener fields into FundamentalData, skipping already-set fields."""
    for field in _SCREENER_FIELDS:
        src_val = getattr(src, field, None)
        tgt_val = getattr(target, field, None)
        # For list/dict fields, treat empty as "not set"
        empty = tgt_val is None or tgt_val == [] or tgt_val == {}
        if src_val and empty:
            setattr(target, field, src_val)


def _merge_fallback(target: FundamentalData, src) -> None:
    """Tickertape fallback — fills only the simple scalar gaps."""
    simple_fields = (
        "company_name", "pe_ratio", "pb_ratio", "market_cap", "eps",
        "roe", "roce", "debt_to_equity", "operating_margin",
        "promoter_holding_pct", "revenue_growth_yoy", "earnings_growth_yoy",
    )
    for field in simple_fields:
        if getattr(target, field) is None:
            val = getattr(src, field, None)
            if val is not None:
                setattr(target, field, val)


def _is_sufficient(data: FundamentalData) -> bool:
    return all(getattr(data, f) is not None for f in _SCREENER_REQUIRED)
