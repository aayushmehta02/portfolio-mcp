"""Fyers API v3 broker adapter."""
from __future__ import annotations

import httpx

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings, update_env_key
from portfolio_mcp.schemas import Broker, Exchange, Holding

_FYERS_BASE = "https://api-t1.fyers.in/api/v3"


def _auth_header() -> str:
    s = get_settings()
    return f"{s.fyers_app_id}:{s.fyers_access_token}"


class FyersAdapter(BrokerAdapter):

    AUTH_ERROR_HINTS = ("401", "token", "unauthorized", "expired", "invalid", "access denied")

    def _fetch_holdings(self) -> list:
        resp = httpx.get(
            f"{_FYERS_BASE}/holdings",
            headers={"Authorization": _auth_header()},
            timeout=15,
        )
        data = resp.json()
        if data.get("s") == "error" or data.get("code") not in (200, None):
            raise RuntimeError(f"Fyers API error: {data.get('message', data)}")
        return data.get("holdings") or []

    def _normalise(self, raw: dict) -> Holding:
        # Symbol format: "NSE:RELIANCE-EQ" → exchange="NSE", ticker="RELIANCE"
        symbol_full  = raw.get("symbol", "")
        parts        = symbol_full.split(":")
        exchange_str = parts[0] if len(parts) == 2 else "NSE"
        ticker       = parts[1].split("-")[0] if len(parts) == 2 else symbol_full

        quantity      = int(raw.get("qty", 0) or 0)
        avg_cost      = float(raw.get("buyAvgPrice", 0) or 0)
        current_price = float(raw.get("ltp", 0) or 0)
        current_value = quantity * current_price
        cost_basis    = quantity * avg_cost
        pnl_absolute  = current_value - cost_basis
        pnl_percent   = (pnl_absolute / cost_basis * 100) if cost_basis else 0.0

        return Holding(
            ticker        = ticker,
            isin          = raw.get("isin", ""),
            exchange      = Exchange.BSE if exchange_str.upper() == "BSE" else Exchange.NSE,
            quantity      = quantity,
            avg_cost      = avg_cost,
            current_price = current_price,
            current_value = round(current_value, 2),
            pnl_absolute  = round(pnl_absolute, 2),
            pnl_percent   = round(pnl_percent, 2),
            broker        = Broker.FYERS,
        )

    async def reauthenticate(self) -> None:
        from portfolio_mcp.auth.fyers_oauth import do_oauth_flow
        s = get_settings()
        new_token = await do_oauth_flow(s.fyers_app_id, s.fyers_secret_key)
        update_env_key("FYERS_ACCESS_TOKEN", new_token)
