"""
Screener.in scraper — BeautifulSoup-based, borrowing patterns from agentic-fund-manager.

Fetches per ticker:
  - Top ratios  (PE, PB, ROE, ROCE, D/E, Market Cap, OPM, Book Value, …)
  - Profit & Loss table   (last 5 annual columns + TTM)
  - Quarterly results     (last 6 quarters)
  - Compounded growth     (Sales/Profit/Stock CAGR 3yr & 5yr, ROE 3yr avg)
  - Shareholding pattern  (Promoter, FII, DII, Public, Pledge %)

No JS required — Screener renders server-side HTML.
Consolidated page is tried first; standalone is the fallback.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SCREENER_BASE = "https://www.screener.in"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",
    "Cache-Control": "max-age=0",
}

_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class ScreenerData(BaseModel):
    ticker: str
    company_name: Optional[str] = None

    # ── Valuation / top-ratios ────────────────────────────────────────────
    pe_ratio:           Optional[float] = None
    pb_ratio:           Optional[float] = None
    market_cap:         Optional[float] = None   # Cr
    book_value:         Optional[float] = None
    eps:                Optional[float] = None
    face_value:         Optional[float] = None
    dividend_yield:     Optional[float] = None

    # ── Profitability ─────────────────────────────────────────────────────
    roe:                Optional[float] = None
    roce:               Optional[float] = None
    operating_margin:   Optional[float] = None   # OPM %
    net_margin:         Optional[float] = None

    # ── Leverage / liquidity ──────────────────────────────────────────────
    debt_to_equity:     Optional[float] = None
    current_ratio:      Optional[float] = None

    # ── Shareholding ──────────────────────────────────────────────────────
    promoter_holding_pct:  Optional[float] = None
    promoter_pledge_pct:   Optional[float] = None
    fii_holding_pct:       Optional[float] = None
    dii_holding_pct:       Optional[float] = None
    public_holding_pct:    Optional[float] = None

    # ── YoY growth (derived from P&L table) ───────────────────────────────
    revenue_growth_yoy:    Optional[float] = None   # %
    earnings_growth_yoy:   Optional[float] = None   # %

    # ── Compounded growth rates ───────────────────────────────────────────
    sales_cagr_3yr:    Optional[float] = None
    sales_cagr_5yr:    Optional[float] = None
    profit_cagr_3yr:   Optional[float] = None
    profit_cagr_5yr:   Optional[float] = None
    stock_cagr_3yr:    Optional[float] = None
    stock_cagr_5yr:    Optional[float] = None
    roe_3yr_avg:       Optional[float] = None

    # ── Time-series tables ────────────────────────────────────────────────
    # { "Sales": [v1, v2, …], "Net Profit": […], … }  for annual years
    annual_years:  list[str]                             = []
    annual_pnl:    dict[str, list[Optional[float]]]      = {}

    # Quarterly
    quarterly_periods: list[str]                         = []
    quarterly_pnl:     dict[str, list[Optional[float]]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_fundamentals(ticker: str) -> Optional[ScreenerData]:
    """
    Async entry point.  Tries consolidated page first, falls back to standalone.
    Returns None on any failure so the pipeline can degrade gracefully.
    """
    html = await _fetch_html(ticker)
    if html is None:
        return None
    try:
        return _parse_html(ticker, html)
    except Exception as exc:
        logger.error("Screener parse error for %s: %s", ticker, exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

async def _fetch_html(ticker: str) -> Optional[str]:
    urls = [
        f"{SCREENER_BASE}/company/{ticker}/consolidated/",
        f"{SCREENER_BASE}/company/{ticker}/",
    ]
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=20, follow_redirects=True
    ) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                logger.info("Screener fetched %s from %s", ticker, url)
                return resp.text
            except Exception as exc:
                logger.warning("Screener fetch failed (%s): %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_number(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = text.replace(",", "").replace("%", "").replace("Cr", "").strip()
    m = _NUM_RE.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_table(
    table,
    max_cols: Optional[int] = None,
) -> tuple[list[str], dict[str, list[Optional[float]]]]:
    """
    Parse a Screener `data-table` element.
    Returns (column_headers, {metric_name: [values…]}).
    """
    if table is None:
        return [], {}

    rows = table.find_all("tr")
    if not rows:
        return [], {}

    # Header — first <tr>, skip the row-label cell
    header_cells = rows[0].find_all(["th", "td"])
    headers: list[str] = [h.get_text(strip=True) for h in header_cells[1:]]

    if max_cols and len(headers) > max_cols:
        headers = headers[-max_cols:]

    data: dict[str, list[Optional[float]]] = {}
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        metric = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip()
        if not metric:
            continue
        vals: list[Optional[float]] = [
            _parse_number(c.get_text(" ", strip=True)) for c in cells[1:]
        ]
        if max_cols and len(vals) > max_cols:
            vals = vals[-max_cols:]
        data[metric] = vals

    return headers, data


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def _parse_html(ticker: str, html: str) -> ScreenerData:
    soup = BeautifulSoup(html, "lxml")
    d = ScreenerData(ticker=ticker)

    # ── Company name ──────────────────────────────────────────────────────
    h1 = soup.find("h1", class_=lambda c: c and "company-name" in c)
    if h1:
        d.company_name = h1.get_text(strip=True)

    # ── Top ratios ────────────────────────────────────────────────────────
    top_ratios_ul = soup.select_one("#top-ratios")
    if top_ratios_ul:
        for li in top_ratios_ul.find_all("li"):
            name_el = li.find(class_="name")
            val_el  = li.find(class_="value")
            if not name_el or not val_el:
                continue
            label = name_el.get_text(strip=True)
            # Screener nests the primary number in <span class="number">
            num_span = val_el.find("span", class_="number")
            raw_val  = (num_span or val_el).get_text(strip=True)
            value    = _parse_number(raw_val)
            ll = label.lower()

            if "stock p/e" in ll or ll == "p/e":
                d.pe_ratio = value
            elif "price to book" in ll or ll == "p/b":
                d.pb_ratio = value
            elif "market cap" in ll:
                d.market_cap = value
            elif "book value" in ll:
                d.book_value = value
            elif "dividend yield" in ll:
                d.dividend_yield = value
            elif ll == "roce":
                d.roce = value
            elif ll == "roe":
                d.roe = value
            elif "debt / equity" in ll or "debt/equity" in ll:
                d.debt_to_equity = value
            elif ll == "opm" or "operating profit" in ll:
                d.operating_margin = value
            elif "current ratio" in ll:
                d.current_ratio = value
            elif "face value" in ll:
                d.face_value = value
            elif ll == "eps":
                d.eps = value

    # ── Profit & Loss (annual, last 5+TTM cols) ───────────────────────────
    pl_section = soup.select_one("#profit-loss")
    if pl_section:
        pl_table = pl_section.select_one("table.data-table")
        years, pnl = _parse_table(pl_table, max_cols=6)   # last 5 annual + TTM
        d.annual_years = years
        d.annual_pnl   = pnl

    # ── Quarterly (last 6 quarters) ───────────────────────────────────────
    q_section = soup.select_one("#quarters")
    if q_section:
        q_table = q_section.select_one("table.data-table")
        periods, q_data = _parse_table(q_table, max_cols=6)
        d.quarterly_periods = periods
        d.quarterly_pnl     = q_data

    # ── Compounded growth rates ───────────────────────────────────────────
    # Screener renders this as a section with id="compounded-table" or similar
    cagr_section = (
        soup.find(id=re.compile(r"compounded", re.I))
        or _find_section_by_heading(soup, "compounded")
    )
    if cagr_section:
        for row in cagr_section.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            vals  = [_parse_number(c.get_text(strip=True)) for c in cells[1:]]

            if "sales" in label:
                if len(vals) >= 1: d.sales_cagr_3yr = vals[0]
                if len(vals) >= 2: d.sales_cagr_5yr = vals[1]
            elif "profit" in label:
                if len(vals) >= 1: d.profit_cagr_3yr = vals[0]
                if len(vals) >= 2: d.profit_cagr_5yr = vals[1]
            elif "stock price" in label:
                if len(vals) >= 1: d.stock_cagr_3yr = vals[0]
                if len(vals) >= 2: d.stock_cagr_5yr = vals[1]
            elif "roe" in label:
                if vals: d.roe_3yr_avg = vals[0]

    # ── Shareholding pattern ──────────────────────────────────────────────
    sh_section = soup.select_one("#shareholding")
    if sh_section:
        sh_table = sh_section.select_one("table")
        if sh_table:
            for row in sh_table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label   = cells[0].get_text(strip=True).lower()
                # Use the most recent (last) column value
                latest  = _parse_number(cells[-1].get_text(strip=True))
                if "promoter" in label and "pledge" not in label:
                    d.promoter_holding_pct = latest
                elif "pledge" in label:
                    d.promoter_pledge_pct = latest
                elif "fii" in label or "foreign" in label:
                    d.fii_holding_pct = latest
                elif "dii" in label or "domestic" in label:
                    d.dii_holding_pct = latest
                elif "public" in label:
                    d.public_holding_pct = latest

    # ── Derive YoY growth from P&L table ─────────────────────────────────
    if d.annual_pnl:
        d.revenue_growth_yoy  = _derive_yoy(d.annual_pnl, ("sales", "revenue"))
        d.earnings_growth_yoy = _derive_yoy(d.annual_pnl, ("net profit", "profit"))

    logger.info(
        "Screener parsed %s: pe=%.1f roe=%.1f de=%.2f promo=%.1f%%",
        ticker,
        d.pe_ratio or 0, d.roe or 0, d.debt_to_equity or 0,
        d.promoter_holding_pct or 0,
    )
    return d


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _find_section_by_heading(soup: BeautifulSoup, keyword: str):
    """Fallback: locate a section whose <h2> contains `keyword`."""
    for section in soup.find_all("section"):
        h2 = section.find(["h2", "h3"])
        if h2 and keyword.lower() in h2.get_text(strip=True).lower():
            return section
    return None


def _derive_yoy(
    pnl: dict[str, list[Optional[float]]],
    keywords: tuple[str, ...],
) -> Optional[float]:
    """Return (last – prev) / |prev| × 100 for the first matching metric row."""
    key = next(
        (k for k in pnl if any(kw in k.lower() for kw in keywords)),
        None,
    )
    if key is None:
        return None
    vals = [v for v in pnl[key] if v is not None]
    if len(vals) < 2 or vals[-2] == 0:
        return None
    return round((vals[-1] - vals[-2]) / abs(vals[-2]) * 100, 2)
