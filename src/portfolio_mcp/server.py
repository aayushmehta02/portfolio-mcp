"""
Portfolio MCP server — powered by FastMCP.

Tools available to Claude:
  broker_status()             – which brokers are configured & connected
  set_active_brokers(brokers) – choose which brokers to pull data from
  connect_upstox()            – browser OAuth for Upstox
  connect_fyers()             – browser OAuth for Fyers
  get_holdings()              – raw holdings (all active brokers, merged)
  get_enriched_holdings()     – holdings + Screener fundamentals (cached)
  get_stock_fundamentals(ticker) – deep single-stock data from Screener
  assess_portfolio()          – full enriched dataset formatted for assessment
  get_user_profile(user_id)   – saved investor profile
  upsert_user_profile(…)      – create / update investor profile

Design principle:
  The MCP server supplies DATA.  Claude does all analysis and reasoning.
  No LLM calls happen inside this process.
"""
from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from portfolio_mcp.brokers.router import get_active_brokers, get_combined_portfolio
from portfolio_mcp.data.cache import invalidate as invalidate_cache
from portfolio_mcp.data.pipeline import _screener_with_cache, enrich_portfolio
from portfolio_mcp.profile.store import get_profile_store
from portfolio_mcp.schemas import (
    Broker,
    ExperienceLevel,
    InvestmentGoal,
    RiskTolerance,
    UserProfile,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("portfolio-mcp")


# ---------------------------------------------------------------------------
# Tool 0a – broker status
# ---------------------------------------------------------------------------

@mcp.tool()
async def broker_status() -> str:
    """
    Show which brokers are configured, connected, and currently active.

    Use this to check the setup before fetching holdings.
    Configured = API credentials are present in .env
    Connected  = a valid access token is present
    Active     = currently selected to contribute to portfolio data
    """
    from portfolio_mcp.config import get_settings

    s       = get_settings()
    active  = [b.value for b in get_active_brokers()]

    status = {
        "upstox": {
            "configured": bool(s.upstox_api_key and s.upstox_api_secret),
            "connected":  bool(s.upstox_access_token),
            "active":     "upstox" in active,
        },
        "fyers": {
            "configured": bool(s.fyers_app_id and s.fyers_secret_key),
            "connected":  bool(s.fyers_access_token),
            "active":     "fyers" in active,
        },
        "angel_one": {
            "configured": bool(s.angel_api_key),
            "connected":  bool(s.angel_access_token),
            "active":     "angel_one" in active,
        },
        "dhan": {
            "configured": bool(s.dhan_client_id and s.dhan_app_id),
            "connected":  bool(s.dhan_access_token),
            "active":     "dhan" in active,
        },
        "icici_direct": {
            "configured": bool(s.icici_api_key and s.icici_api_secret),
            "connected":  bool(s.icici_access_token),
            "active":     "icici_direct" in active,
        },
        "active_brokers": active or "none — call set_active_brokers first",
        "supported_brokers": [b.value for b in Broker],
    }
    return json.dumps(status, indent=2)


# ---------------------------------------------------------------------------
# Tool 0b – set active brokers (multiselect)
# ---------------------------------------------------------------------------

@mcp.tool()
async def set_active_brokers(brokers: list[str]) -> str:
    """
    Choose which brokers to pull portfolio data from.

    Pass a list of broker names — supported values: "upstox", "fyers", "angel_one", "dhan", "icici_direct"
    You can select one or both. Holdings will be merged across all active brokers.

    Example: set_active_brokers(["upstox", "fyers"])
    """
    from portfolio_mcp.config import update_env_key

    supported = {b.value for b in Broker}
    chosen, unknown = [], []
    for b in brokers:
        b = b.strip().lower()
        if b in supported:
            chosen.append(b)
        else:
            unknown.append(b)

    if unknown:
        return f"Unknown broker(s): {', '.join(unknown)}. Supported: {', '.join(supported)}"
    if not chosen:
        return "Please provide at least one broker name."

    update_env_key("ACTIVE_BROKERS", ",".join(chosen))
    return f"✓ Active brokers set to: {', '.join(chosen)}"


# ---------------------------------------------------------------------------
# Tool 0c – connect Upstox (browser OAuth)
# ---------------------------------------------------------------------------

@mcp.tool()
async def connect_upstox() -> str:
    """
    Connect or reconnect your Upstox account.

    Opens your browser to the normal Upstox login page.
    Just log in as you usually would — the token is saved automatically.
    Call this once on first setup, or any time your session has expired.
    """
    import asyncio
    import webbrowser
    from urllib.parse import urlencode
    from portfolio_mcp.config import get_settings, update_env_key

    settings = get_settings()
    if not settings.upstox_api_key or not settings.upstox_api_secret:
        return (
            "Missing credentials. Please set UPSTOX_API_KEY and UPSTOX_API_SECRET "
            "in your .env file, then call connect_upstox again."
        )

    REDIRECT_URI = "https://web-portfolio-amber-one.vercel.app/"
    LOCAL_CB     = "http://localhost:8888/callback"
    auth_url = "https://api.upstox.com/v2/login/authorization/dialog?" + urlencode({
        "response_type": "code",
        "client_id":     settings.upstox_api_key,
        "redirect_uri":  REDIRECT_URI,
        "state":         LOCAL_CB,
    })
    webbrowser.open(auth_url)

    async def _background():
        from portfolio_mcp.auth.local_callback import wait_for_code
        import httpx
        try:
            code = await wait_for_code(8888,
                "https://web-portfolio-amber-one.vercel.app/connected",
                "https://web-portfolio-amber-one.vercel.app/connected",
                timeout=300)
            resp = httpx.post(
                "https://api.upstox.com/v2/login/authorization/token",
                data={"code": code, "client_id": settings.upstox_api_key,
                      "client_secret": settings.upstox_api_secret,
                      "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"},
                headers={"Accept": "application/json"}, timeout=15)
            token = resp.json().get("access_token")
            if token:
                update_env_key("UPSTOX_ACCESS_TOKEN", token)
                logger.info("Upstox token saved successfully.")
        except Exception as e:
            logger.error("Upstox background auth failed: %s", e)

    asyncio.create_task(_background())
    return (
        "✓ Upstox login page opened in your browser. "
        "Log in as usual — your token will be saved automatically once you're done. "
        "Then just ask me to fetch your holdings."
    )


# ---------------------------------------------------------------------------
# Tool 0d – connect Fyers (browser OAuth)
# ---------------------------------------------------------------------------

@mcp.tool()
async def connect_fyers() -> str:
    """
    Connect or reconnect your Fyers account.

    Opens your browser to the normal Fyers login page.
    Just log in as you usually would — the token is saved automatically.
    Call this once on first setup, or any time your session has expired.
    """
    import asyncio
    import hashlib
    import webbrowser
    from urllib.parse import urlencode
    from portfolio_mcp.config import get_settings, update_env_key

    settings = get_settings()
    if not settings.fyers_app_id or not settings.fyers_secret_key:
        return (
            "Missing credentials. Please set FYERS_APP_ID and FYERS_SECRET_KEY "
            "in your .env file, then call connect_fyers again."
        )

    REDIRECT_URI = "http://localhost:8888/callback"
    auth_url = "https://api-t1.fyers.in/api/v3/generate-authcode?" + urlencode({
        "client_id":     settings.fyers_app_id,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
    })
    webbrowser.open(auth_url)

    async def _background():
        from portfolio_mcp.auth.local_callback import wait_for_code
        import httpx
        try:
            code = await wait_for_code(8888, REDIRECT_URI, REDIRECT_URI, timeout=300)
            app_id_hash = hashlib.sha256(
                f"{settings.fyers_app_id}:{settings.fyers_secret_key}".encode()
            ).hexdigest()
            resp = httpx.post(
                "https://api-t1.fyers.in/api/v3/validate-authcode",
                json={"grant_type": "authorization_code",
                      "appIdHash": app_id_hash, "code": code},
                headers={"Content-Type": "application/json"}, timeout=15)
            token = resp.json().get("access_token")
            if token:
                update_env_key("FYERS_ACCESS_TOKEN", token)
                logger.info("Fyers token saved successfully.")
        except Exception as e:
            logger.error("Fyers background auth failed: %s", e)

    asyncio.create_task(_background())
    return (
        "✓ Fyers login page opened in your browser. "
        "Log in as usual — your token will be saved automatically once you're done. "
        "Then just ask me to fetch your holdings."
    )


# ---------------------------------------------------------------------------
# Tool 0e – connect Angel One (browser OAuth)
# ---------------------------------------------------------------------------

@mcp.tool()
async def connect_angel_one() -> str:
    """
    Connect or reconnect your Angel One account via SmartAPI.

    Opens the Angel One publisher login page in your browser.
    Log in with your client code, password, and TOTP — token is saved automatically.
    Call this once on first setup, or any time your session has expired.

    Prerequisites: ANGEL_API_KEY must be set in .env
    Get your API key at: https://smartapi.angelone.in
    """
    import asyncio
    import webbrowser
    from portfolio_mcp.config import get_settings, update_env_key

    settings = get_settings()
    if not settings.angel_api_key:
        return (
            "Missing credentials. Please set ANGEL_API_KEY in your .env file, "
            "then call connect_angel_one again.\n\n"
            "Get your free API key at: https://smartapi.angelone.in"
        )

    login_url = f"https://smartapi.angelone.in/publisher-login?api_key={settings.angel_api_key}"
    webbrowser.open(login_url)

    async def _background():
        from portfolio_mcp.auth.local_callback import wait_for_code
        try:
            token = await wait_for_code(8888, "", "", timeout=300)
            if token:
                update_env_key("ANGEL_ACCESS_TOKEN", token)
                logger.info("Angel One token saved successfully.")
        except Exception as e:
            logger.error("Angel One background auth failed: %s", e)

    asyncio.create_task(_background())
    return (
        "✓ Angel One login page opened in your browser. "
        "Log in with your client code, password, and TOTP — "
        "your token will be saved automatically. "
        "Then just ask me to fetch your holdings."
    )


# ---------------------------------------------------------------------------
# Tool 0f – connect Dhan (browser OAuth)
# ---------------------------------------------------------------------------

@mcp.tool()
async def connect_dhan() -> str:
    """
    Connect or reconnect your Dhan account.

    Opens the Dhan login page in your browser.
    Log in as usual — the token is saved automatically.
    Call this once on first setup, or any time your session has expired.

    Prerequisites: DHAN_CLIENT_ID, DHAN_APP_ID, DHAN_APP_SECRET must be set in .env
    Get your free API credentials at: https://dhanhq.co/developer
    """
    import asyncio
    import webbrowser
    import httpx
    from portfolio_mcp.config import get_settings, update_env_key

    settings = get_settings()
    if not settings.dhan_client_id or not settings.dhan_app_id or not settings.dhan_app_secret:
        return (
            "Missing credentials. Please set DHAN_CLIENT_ID, DHAN_APP_ID, and DHAN_APP_SECRET "
            "in your .env file, then call connect_dhan again.\n\n"
            "Get your free API credentials at: https://dhanhq.co/developer"
        )

    # Create consent session to get the login URL
    try:
        resp = httpx.post(
            "https://api.dhan.co/v2/token",
            json={
                "clientId":      settings.dhan_client_id,
                "partnerClientId": settings.dhan_app_id,
                "partnerSecret": settings.dhan_app_secret,
            },
            timeout=15,
        )
        data = resp.json()
        consent_id = data.get("consentId") or data.get("consent_id")
    except Exception as e:
        return f"Failed to create Dhan consent session: {e}"

    if not consent_id:
        return f"Dhan returned an unexpected response: {data}"

    login_url = f"https://login.dhan.co/login/{consent_id}"
    webbrowser.open(login_url)

    async def _background():
        from portfolio_mcp.auth.local_callback import wait_for_code
        try:
            token_id = await wait_for_code(8888, "", "", timeout=300)
            resp2 = httpx.post(
                "https://api.dhan.co/v2/token/generate",
                json={
                    "tokenId":       token_id,
                    "partnerClientId": settings.dhan_app_id,
                    "partnerSecret": settings.dhan_app_secret,
                },
                timeout=15,
            )
            access_token = resp2.json().get("accessToken") or resp2.json().get("access_token")
            if access_token:
                update_env_key("DHAN_ACCESS_TOKEN", access_token)
                logger.info("Dhan token saved successfully.")
        except Exception as e:
            logger.error("Dhan background auth failed: %s", e)

    asyncio.create_task(_background())
    return (
        "✓ Dhan login page opened in your browser. "
        "Log in as usual — your token will be saved automatically. "
        "Then just ask me to fetch your holdings."
    )


# ---------------------------------------------------------------------------
# Tool 0g – connect ICICI Direct (browser OAuth)
# ---------------------------------------------------------------------------

@mcp.tool()
async def connect_icici_direct() -> str:
    """
    Connect or reconnect your ICICI Direct account via Breeze API.

    Opens the ICICI Direct login page in your browser.
    Log in with your ICICI Direct credentials — token is saved automatically.
    Call this once on first setup, or any time your session has expired.

    Prerequisites: ICICI_API_KEY and ICICI_API_SECRET must be set in .env
    Get your free API key at: https://api.icicidirect.com
    """
    import asyncio
    import webbrowser
    from portfolio_mcp.config import get_settings, update_env_key

    settings = get_settings()
    if not settings.icici_api_key or not settings.icici_api_secret:
        return (
            "Missing credentials. Please set ICICI_API_KEY and ICICI_API_SECRET "
            "in your .env file, then call connect_icici_direct again.\n\n"
            "Get your free API key at: https://api.icicidirect.com"
        )

    login_url = f"https://api.icicidirect.com/apiuser/login?AppKey={settings.icici_api_key}"
    webbrowser.open(login_url)

    async def _background():
        from portfolio_mcp.auth.local_callback import wait_for_code
        from breeze_connect import BreezeConnect
        try:
            request_token = await wait_for_code(8888, "", "", timeout=300)
            breeze = BreezeConnect(api_key=settings.icici_api_key)
            breeze.generate_session(
                api_secret=settings.icici_api_secret,
                session_token=request_token,
            )
            update_env_key("ICICI_ACCESS_TOKEN", request_token)
            logger.info("ICICI Direct token saved successfully.")
        except Exception as e:
            logger.error("ICICI Direct background auth failed: %s", e)

    asyncio.create_task(_background())
    return (
        "✓ ICICI Direct login page opened in your browser. "
        "Log in with your ICICI Direct credentials — "
        "your token will be saved automatically. "
        "Then just ask me to fetch your holdings."
    )


# ---------------------------------------------------------------------------
# Helper: serialise a FundamentalData object to a clean dict
# ---------------------------------------------------------------------------

def _fundamentals_dict(e) -> dict:
    return {
        "company_name":         e.company_name,
        # Valuation
        "pe_ratio":             e.pe_ratio,
        "pb_ratio":             e.pb_ratio,
        "market_cap_cr":        e.market_cap,
        "book_value":           e.book_value,
        "face_value":           e.face_value,
        "dividend_yield_pct":   e.dividend_yield,
        "eps":                  e.eps,
        # Profitability
        "roe_pct":              e.roe,
        "roce_pct":             e.roce,
        "operating_margin_pct": e.operating_margin,
        "net_margin_pct":       e.net_margin,
        # Leverage
        "debt_to_equity":       e.debt_to_equity,
        "current_ratio":        e.current_ratio,
        # Shareholding
        "promoter_holding_pct": e.promoter_holding_pct,
        "promoter_pledge_pct":  e.promoter_pledge_pct,
        "fii_holding_pct":      e.fii_holding_pct,
        "dii_holding_pct":      e.dii_holding_pct,
        "public_holding_pct":   e.public_holding_pct,
        # Growth
        "revenue_growth_yoy_pct":  e.revenue_growth_yoy,
        "earnings_growth_yoy_pct": e.earnings_growth_yoy,
        # CAGR
        "sales_cagr_3yr_pct":   e.sales_cagr_3yr,
        "sales_cagr_5yr_pct":   e.sales_cagr_5yr,
        "profit_cagr_3yr_pct":  e.profit_cagr_3yr,
        "profit_cagr_5yr_pct":  e.profit_cagr_5yr,
        "stock_cagr_3yr_pct":   e.stock_cagr_3yr,
        "stock_cagr_5yr_pct":   e.stock_cagr_5yr,
        "roe_3yr_avg_pct":      e.roe_3yr_avg,
        # Time-series
        "annual_years":         e.annual_years,
        "annual_pnl":           e.annual_pnl,
        "quarterly_periods":    e.quarterly_periods,
        "quarterly_pnl":        e.quarterly_pnl,
        # Corporate actions & filings
        "corporate_actions": [
            {
                "type":              a.action_type,
                "announcement_date": a.announcement_date.isoformat(),
                "details":           a.details,
            }
            for a in e.corporate_actions
        ],
        "recent_filings": [
            {
                "type":    f.filing_type,
                "filed_at": f.filed_at.isoformat(),
                "title":    f.title,
                "url":      f.url,
            }
            for f in e.recent_filings
        ],
        "sources_used": e.sources_used,
        "enriched_at":  e.enriched_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Tool 1 – raw holdings
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_holdings() -> str:
    """
    Fetch current long-term holdings from Upstox.

    Returns:
      - Portfolio summary: total invested, current value, overall P&L
      - Per-holding: ticker, ISIN, exchange, quantity, avg cost, current price, P&L
    """
    portfolio = await get_combined_portfolio()
    result = {
        "summary": {
            "total_invested":      portfolio.total_invested,
            "total_current_value": portfolio.total_current_value,
            "total_pnl_absolute":  portfolio.total_pnl_absolute,
            "total_pnl_percent":   portfolio.total_pnl_percent,
        },
        "holdings": [
            {
                "ticker":        h.ticker,
                "isin":          h.isin,
                "exchange":      h.exchange.value,
                "quantity":      h.quantity,
                "avg_cost":      h.avg_cost,
                "current_price": h.current_price,
                "current_value": h.current_value,
                "pnl_absolute":  h.pnl_absolute,
                "pnl_percent":   h.pnl_percent,
            }
            for h in portfolio.holdings
        ],
    }
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tool 2 – enriched holdings
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_enriched_holdings() -> str:
    """
    Fetch holdings from Upstox and enrich each with fundamental data from
    Screener.in (PE, PB, ROE, ROCE, debt/equity, promoter holding, CAGR,
    P&L time-series, quarterly results, shareholding, etc.).

    Screener data is cached for 6 hours so repeated calls are fast.
    Returns the full dataset ready for portfolio analysis.
    """
    portfolio = await get_combined_portfolio()
    portfolio.holdings = await enrich_portfolio(portfolio.holdings)

    holdings_out = []
    for h in portfolio.holdings:
        entry: dict = {
            "ticker":        h.ticker,
            "isin":          h.isin,
            "exchange":      h.exchange.value,
            "broker":        h.broker.value,
            "quantity":      h.quantity,
            "avg_cost":      h.avg_cost,
            "current_price": h.current_price,
            "current_value": h.current_value,
            "pnl_absolute":  h.pnl_absolute,
            "pnl_percent":   h.pnl_percent,
            "portfolio_weight_pct": round(
                h.current_value / portfolio.total_current_value * 100, 2
            ) if portfolio.total_current_value else 0,
        }
        if h.enriched:
            entry["fundamentals"] = _fundamentals_dict(h.enriched)
        holdings_out.append(entry)

    result = {
        "summary": {
            "total_invested":      portfolio.total_invested,
            "total_current_value": portfolio.total_current_value,
            "total_pnl_absolute":  portfolio.total_pnl_absolute,
            "total_pnl_percent":   portfolio.total_pnl_percent,
            "holdings_count":      len(holdings_out),
        },
        "holdings": holdings_out,
    }
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 3 – single-stock deep dive
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_stock_fundamentals(
    ticker: str,
    force_refresh: bool = False,
) -> str:
    """
    Fetch deep fundamental data for a single NSE/BSE ticker from Screener.in.

    Use this when you want to analyse one stock in isolation — e.g. before
    adding it to the portfolio, or to revisit a holding in detail.

    Args:
      ticker:        NSE symbol, e.g. "RELIANCE", "INFY", "HDFCBANK"
      force_refresh: If True, bypass the 6-hour cache and fetch live data.

    Returns a rich snapshot: valuation, profitability, leverage, shareholding,
    compounded growth rates, 5-year P&L table, and last 6 quarters.
    """
    ticker = ticker.strip().upper()

    if force_refresh:
        invalidate_cache(ticker)
        logger.info("Cache invalidated for %s (force_refresh=True)", ticker)

    screener_data = await _screener_with_cache(ticker)

    if screener_data is None:
        return json.dumps(
            {"error": f"Could not fetch data for '{ticker}'. "
                      "Check that the symbol is listed on NSE/BSE and "
                      "matches Screener.in's ticker convention."},
            indent=2,
        )

    result = {
        "ticker": ticker,
        "source": "screener.in",
        **screener_data.model_dump(exclude={"ticker"}),
    }
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 4 – full portfolio assessment package
# ---------------------------------------------------------------------------

@mcp.tool()
async def assess_portfolio() -> str:
    """
    Return a fully enriched, assessment-ready snapshot of the portfolio.

    This is the primary tool for portfolio health assessment.  It packages:
      - Portfolio-level summary (P&L, weights, diversification metrics)
      - Per-holding fundamentals (valuation, profitability, leverage, growth)
      - Concentration metrics (top-5 holdings by weight)
      - Red-flag pre-checks: high D/E, promoter pledge, negative growth,
        heavy concentration, underwater positions
      - Raw time-series for trend analysis

    Claude should use this output to:
      1. Assess each holding on quality (valuation, profitability, leverage)
      2. Flag risks (pledge, debt, declining earnings, thin margins)
      3. Assess portfolio-level risks (concentration, sector overlap)
      4. Provide an overall portfolio health narrative
      5. Suggest watchlist items or rebalancing ideas
    """
    portfolio = await get_combined_portfolio()
    portfolio.holdings = await enrich_portfolio(portfolio.holdings)

    total_value = portfolio.total_current_value or 1  # avoid div/0

    # ── Per-holding enriched data ─────────────────────────────────────────
    holdings_out = []
    for h in portfolio.holdings:
        weight = round(h.current_value / total_value * 100, 2)
        entry: dict = {
            "ticker":                 h.ticker,
            "exchange":               h.exchange.value,
            "quantity":               h.quantity,
            "avg_cost":               h.avg_cost,
            "current_price":          h.current_price,
            "current_value":          h.current_value,
            "pnl_absolute":           h.pnl_absolute,
            "pnl_percent":            h.pnl_percent,
            "portfolio_weight_pct":   weight,
        }
        if h.enriched:
            entry["fundamentals"] = _fundamentals_dict(h.enriched)
        holdings_out.append(entry)

    # Sort by portfolio weight desc
    holdings_out.sort(key=lambda x: x["portfolio_weight_pct"], reverse=True)

    # ── Concentration ─────────────────────────────────────────────────────
    top5 = holdings_out[:5]
    top5_weight = sum(h["portfolio_weight_pct"] for h in top5)

    # ── Pre-computed red-flag signals ─────────────────────────────────────
    red_flags: list[dict] = []
    green_flags: list[dict] = []

    for h in holdings_out:
        t   = h["ticker"]
        f   = h.get("fundamentals", {})
        w   = h["portfolio_weight_pct"]
        pnl = h["pnl_percent"]

        # Concentration
        if w > 20:
            red_flags.append({"ticker": t, "flag": "HIGH_CONCENTRATION",
                               "detail": f"{w:.1f}% of portfolio in one stock"})
        elif w > 15:
            red_flags.append({"ticker": t, "flag": "ELEVATED_CONCENTRATION",
                               "detail": f"{w:.1f}% of portfolio"})

        # Promoter pledge
        pledge = f.get("promoter_pledge_pct")
        if pledge and pledge > 20:
            red_flags.append({"ticker": t, "flag": "HIGH_PROMOTER_PLEDGE",
                               "detail": f"Promoter pledge {pledge:.1f}%"})

        # Debt
        de = f.get("debt_to_equity")
        if de and de > 2:
            red_flags.append({"ticker": t, "flag": "HIGH_DEBT",
                               "detail": f"D/E ratio {de:.2f}x"})

        # Declining earnings
        eg = f.get("earnings_growth_yoy_pct")
        if eg is not None and eg < -10:
            red_flags.append({"ticker": t, "flag": "EARNINGS_DECLINE",
                               "detail": f"YoY earnings growth {eg:.1f}%"})

        # Deeply underwater
        if pnl < -30:
            red_flags.append({"ticker": t, "flag": "DEEPLY_UNDERWATER",
                               "detail": f"P&L {pnl:.1f}%"})

        # Green flags
        roe = f.get("roe_pct")
        roce = f.get("roce_pct")
        promo = f.get("promoter_holding_pct")
        if roe and roe > 20 and de and de < 0.5:
            green_flags.append({"ticker": t, "flag": "HIGH_ROE_LOW_DEBT",
                                 "detail": f"ROE {roe:.1f}%, D/E {de:.2f}x"})
        if promo and promo > 60:
            green_flags.append({"ticker": t, "flag": "STRONG_PROMOTER_HOLDING",
                                 "detail": f"Promoter holding {promo:.1f}%"})
        if pnl > 50:
            green_flags.append({"ticker": t, "flag": "STRONG_PERFORMER",
                                 "detail": f"P&L +{pnl:.1f}%"})

    # ── Portfolio-level P&L breakdown ─────────────────────────────────────
    winners   = [h for h in holdings_out if h["pnl_percent"] > 0]
    losers    = [h for h in holdings_out if h["pnl_percent"] <= 0]

    result = {
        # ── Summary ───────────────────────────────────────────────────
        "portfolio_summary": {
            "total_invested":      portfolio.total_invested,
            "total_current_value": portfolio.total_current_value,
            "total_pnl_absolute":  portfolio.total_pnl_absolute,
            "total_pnl_percent":   portfolio.total_pnl_percent,
            "holdings_count":      len(holdings_out),
            "winners_count":       len(winners),
            "losers_count":        len(losers),
        },

        # ── Concentration ─────────────────────────────────────────────
        "concentration": {
            "top5_holdings": [
                {"ticker": h["ticker"], "weight_pct": h["portfolio_weight_pct"]}
                for h in top5
            ],
            "top5_combined_weight_pct": round(top5_weight, 2),
            "note": (
                "Concentrated (>60% in top-5)" if top5_weight > 60
                else "Moderately diversified (40-60% in top-5)" if top5_weight > 40
                else "Well diversified (<40% in top-5)"
            ),
        },

        # ── Pre-computed signals ───────────────────────────────────────
        "pre_computed_signals": {
            "red_flags":   red_flags,
            "green_flags": green_flags,
        },

        # ── Full holdings with fundamentals ───────────────────────────
        "holdings": holdings_out,

        # ── Assessment guidance ───────────────────────────────────────
        "_assessment_guidance": (
            "Analyse each holding using: pe_ratio vs sector norm, "
            "roe_pct & roce_pct vs cost of capital (~12%), "
            "debt_to_equity (<1 preferred), promoter_holding_pct (>50% positive), "
            "promoter_pledge_pct (<5% preferred), revenue/earnings growth trends, "
            "annual_pnl for multi-year trajectory. "
            "Flag any holding that fails 2+ criteria as a WATCH or EXIT candidate. "
            "Comment on portfolio concentration, sector diversity, and overall health."
        ),
    }

    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 5 – user profile (read)
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_user_profile(user_id: str) -> str:
    """Retrieve the saved investment profile for a user."""
    profile = get_profile_store().load(user_id)
    if profile is None:
        return f"No profile found for user '{user_id}'."
    return profile.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# Tool 6 – user profile (write)
# ---------------------------------------------------------------------------

@mcp.tool()
async def upsert_user_profile(
    user_id: str,
    risk_tolerance: str = "",
    investment_goal: str = "",
    investment_horizon_years: int = 0,
    experience_level: str = "",
    preferred_sectors: list[str] | None = None,
    avoided_sectors: list[str] | None = None,
) -> str:
    """
    Create or update the investment profile for a user.

    risk_tolerance:         conservative | moderate | aggressive
    investment_goal:        wealth_preservation | growth | income
    experience_level:       beginner | intermediate | advanced
    investment_horizon_years: years the investor plans to stay invested
    preferred_sectors:      list of sector names the investor likes
    avoided_sectors:        list of sector names the investor wants to skip
    """
    store    = get_profile_store()
    existing = store.load(user_id) or UserProfile(user_id=user_id)

    if risk_tolerance:
        existing.risk_tolerance = RiskTolerance(risk_tolerance)
    if investment_goal:
        existing.investment_goal = InvestmentGoal(investment_goal)
    if investment_horizon_years:
        existing.investment_horizon_years = investment_horizon_years
    if experience_level:
        existing.experience_level = ExperienceLevel(experience_level)
    if preferred_sectors is not None:
        existing.preferred_sectors = preferred_sectors
    if avoided_sectors is not None:
        existing.avoided_sectors = avoided_sectors

    store.save(existing)
    return f"Profile saved for '{user_id}'."
