"""Dhan broker adapter."""
from __future__ import annotations

import httpx

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings, update_env_key
from portfolio_mcp.schemas import Broker, Exchange, Holding

_BASE = "https://api.dhan.co/v2"


def _headers() -> dict:
    s = get_settings()
    return {
        "access-token": s.dhan_access_token,
        "client-id": s.dhan_client_id,
        "Content-Type": "application/json",
    }


class DhanAdapter(BrokerAdapter):

    AUTH_ERROR_HINTS = ("401", "token", "unauthorized", "expired", "invalid", "UNAUTHORIZED")

    def _fetch_holdings(self) -> list:
        resp = httpx.get(
            f"{_BASE}/holdings",
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()
        # Dhan returns a list directly, or {"status": "failure", ...} on error
        if isinstance(data, dict) and data.get("status") == "failure":
            raise RuntimeError(f"Dhan API error: {data.get('remarks', data)}")
        return data if isinstance(data, list) else (data.get("data") or [])

    def _normalise(self, raw: dict) -> Holding:
        quantity      = int(raw.get("totalQty", 0) or 0)
        avg_cost      = float(raw.get("avgCostPrice", 0) or 0)
        current_price = float(raw.get("lastTradedPrice", 0) or 0)
        current_value = quantity * current_price
        cost_basis    = quantity * avg_cost
        pnl_absolute  = current_value - cost_basis
        pnl_percent   = (pnl_absolute / cost_basis * 100) if cost_basis else 0.0

        exchange_str  = str(raw.get("exchangeSegment", "NSE_EQ")).upper()
        exchange      = Exchange.BSE if "BSE" in exchange_str else Exchange.NSE

        return Holding(
            ticker        = raw.get("tradingSymbol", ""),
            isin          = raw.get("isinCode", ""),
            exchange      = exchange,
            quantity      = quantity,
            avg_cost      = avg_cost,
            current_price = current_price,
            current_value = round(current_value, 2),
            pnl_absolute  = round(pnl_absolute, 2),
            pnl_percent   = round(pnl_percent, 2),
            broker        = Broker.DHAN,
        )

    async def reauthenticate(self) -> None:
        from portfolio_mcp.auth.dhan_oauth import do_oauth_flow
        s = get_settings()
        new_token = await do_oauth_flow(s.dhan_client_id, s.dhan_app_id, s.dhan_app_secret)
        update_env_key("DHAN_ACCESS_TOKEN", new_token)
