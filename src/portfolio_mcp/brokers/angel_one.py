"""Angel One SmartAPI broker adapter."""
from __future__ import annotations

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings, update_env_key
from portfolio_mcp.schemas import Broker, Exchange, Holding

_BASE = "https://apiconnect.angelone.in"


def _headers() -> dict:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.angel_access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-PrivateKey": s.angel_api_key,
    }


class AngelOneAdapter(BrokerAdapter):

    AUTH_ERROR_HINTS = ("401", "token", "unauthorized", "expired", "invalid", "TokenException")

    def _fetch_holdings(self) -> list:
        import httpx
        resp = httpx.get(
            f"{_BASE}/rest/secure/angelbroking/portfolio/v1/getAllHolding",
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()
        if not data.get("status"):
            raise RuntimeError(f"Angel One API error: {data.get('message', data)}")
        # getAllHolding nests holdings under data.holdingList
        return (data.get("data") or {}).get("holdingList") or []

    def _normalise(self, raw: dict) -> Holding:
        quantity      = int(raw.get("quantity", 0) or 0)
        avg_cost      = float(raw.get("averageprice", 0) or 0)
        current_price = float(raw.get("ltp", 0) or raw.get("close", 0) or 0)
        current_value = quantity * current_price
        cost_basis    = quantity * avg_cost
        pnl_absolute  = current_value - cost_basis
        pnl_percent   = (pnl_absolute / cost_basis * 100) if cost_basis else 0.0

        exchange_str  = str(raw.get("exchange", "NSE")).upper()
        exchange      = Exchange.BSE if exchange_str.startswith("BSE") else Exchange.NSE

        return Holding(
            ticker        = raw.get("tradingsymbol", ""),
            isin          = raw.get("isin", ""),
            exchange      = exchange,
            quantity      = quantity,
            avg_cost      = avg_cost,
            current_price = current_price,
            current_value = round(current_value, 2),
            pnl_absolute  = round(pnl_absolute, 2),
            pnl_percent   = round(pnl_percent, 2),
            broker        = Broker.ANGEL_ONE,
        )

    async def reauthenticate(self) -> None:
        from portfolio_mcp.auth.angel_oauth import do_oauth_flow
        s = get_settings()
        new_token = await do_oauth_flow(s.angel_api_key)
        update_env_key("ANGEL_ACCESS_TOKEN", new_token)
