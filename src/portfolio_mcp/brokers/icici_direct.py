"""ICICI Direct Breeze broker adapter."""
from __future__ import annotations

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings, update_env_key
from portfolio_mcp.schemas import Broker, Exchange, Holding


def _make_breeze():
    from breeze_connect import BreezeConnect
    s = get_settings()
    breeze = BreezeConnect(api_key=s.icici_api_key)
    breeze.generate_session(api_secret=s.icici_api_secret, session_token=s.icici_access_token)
    return breeze


class ICICIDirectAdapter(BrokerAdapter):

    AUTH_ERROR_HINTS = ("401", "token", "unauthorized", "expired", "invalid", "session")

    def _fetch_holdings(self) -> list:
        breeze = _make_breeze()
        resp = breeze.get_portfolio_holdings(exchange_code="NSE")
        # Breeze returns {"Success": [...], "Status": 200} or {"Error": "...", "Status": ...}
        if resp.get("Error"):
            raise RuntimeError(f"ICICI Breeze error: {resp['Error']}")
        holdings = resp.get("Success") or []

        # Also fetch BSE holdings and merge
        resp_bse = breeze.get_portfolio_holdings(exchange_code="BSE")
        if not resp_bse.get("Error"):
            holdings += resp_bse.get("Success") or []

        return holdings

    def _normalise(self, raw: dict) -> Holding:
        quantity      = int(float(raw.get("quantity", 0) or 0))
        avg_cost      = float(raw.get("average_cost", 0) or 0)
        current_price = float(raw.get("last_close_price", 0) or 0)
        current_value = quantity * current_price
        cost_basis    = quantity * avg_cost
        pnl_absolute  = current_value - cost_basis
        pnl_percent   = (pnl_absolute / cost_basis * 100) if cost_basis else 0.0

        exchange_str  = str(raw.get("exchange_code", "NSE")).upper()
        exchange      = Exchange.BSE if exchange_str == "BSE" else Exchange.NSE

        return Holding(
            ticker        = raw.get("stock_code", ""),
            isin          = raw.get("isin_code", ""),
            exchange      = exchange,
            quantity      = quantity,
            avg_cost      = avg_cost,
            current_price = current_price,
            current_value = round(current_value, 2),
            pnl_absolute  = round(pnl_absolute, 2),
            pnl_percent   = round(pnl_percent, 2),
            broker        = Broker.ICICI_DIRECT,
        )

    async def reauthenticate(self) -> None:
        from portfolio_mcp.auth.icici_oauth import do_oauth_flow
        s = get_settings()
        new_token = await do_oauth_flow(s.icici_api_key, s.icici_api_secret)
        update_env_key("ICICI_ACCESS_TOKEN", new_token)
