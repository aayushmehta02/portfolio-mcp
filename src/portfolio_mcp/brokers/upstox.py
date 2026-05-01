"""Upstox v2 broker adapter."""
from __future__ import annotations

import upstox_client

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings, update_env_key
from portfolio_mcp.schemas import Broker, Exchange, Holding


def _make_api_client() -> upstox_client.ApiClient:
    config = upstox_client.Configuration()
    config.access_token = get_settings().upstox_access_token
    return upstox_client.ApiClient(config)


class UpstoxAdapter(BrokerAdapter):

    def _fetch_holdings(self) -> list:
        api = upstox_client.PortfolioApi(_make_api_client())
        resp = api.get_holdings(api_version="2.0")
        return resp.data or []

    def _normalise(self, raw) -> Holding:
        quantity      = int(raw.quantity or 0)
        avg_cost      = float(raw.average_price or 0)
        current_price = float(raw.last_price or 0)
        current_value = quantity * current_price
        cost_basis    = quantity * avg_cost
        pnl_absolute  = current_value - cost_basis
        pnl_percent   = (pnl_absolute / cost_basis * 100) if cost_basis else 0.0

        exchange_raw = str(raw.exchange or "NSE_EQ")
        exchange = Exchange.BSE if exchange_raw.startswith("BSE") else Exchange.NSE

        return Holding(
            ticker        = raw.trading_symbol or "",
            isin          = raw.isin or "",
            exchange      = exchange,
            quantity      = quantity,
            avg_cost      = avg_cost,
            current_price = current_price,
            current_value = round(current_value, 2),
            pnl_absolute  = round(pnl_absolute, 2),
            pnl_percent   = round(pnl_percent, 2),
            broker        = Broker.UPSTOX,
        )

    async def reauthenticate(self) -> None:
        from portfolio_mcp.auth.upstox_oauth import do_oauth_flow
        s = get_settings()
        new_token = await do_oauth_flow(s.upstox_api_key, s.upstox_api_secret)
        update_env_key("UPSTOX_ACCESS_TOKEN", new_token)
