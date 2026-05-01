"""
Multi-broker router.

Manages adapter instances and merges portfolios from multiple brokers
into a single combined Portfolio.
"""
from __future__ import annotations

import asyncio
import logging

from portfolio_mcp.brokers.adapter import BrokerAdapter
from portfolio_mcp.config import get_settings
from portfolio_mcp.schemas import Broker, Portfolio

logger = logging.getLogger(__name__)

# ── Lazy singletons ────────────────────────────────────────────────────────────

_adapters: dict[Broker, BrokerAdapter] = {}


def _get_adapter(broker: Broker) -> BrokerAdapter:
    if broker not in _adapters:
        if broker == Broker.UPSTOX:
            from portfolio_mcp.brokers.upstox import UpstoxAdapter
            _adapters[broker] = UpstoxAdapter()
        elif broker == Broker.FYERS:
            from portfolio_mcp.brokers.fyers import FyersAdapter
            _adapters[broker] = FyersAdapter()
        elif broker == Broker.ANGEL_ONE:
            from portfolio_mcp.brokers.angel_one import AngelOneAdapter
            _adapters[broker] = AngelOneAdapter()
        elif broker == Broker.DHAN:
            from portfolio_mcp.brokers.dhan import DhanAdapter
            _adapters[broker] = DhanAdapter()
        elif broker == Broker.ICICI_DIRECT:
            from portfolio_mcp.brokers.icici_direct import ICICIDirectAdapter
            _adapters[broker] = ICICIDirectAdapter()
        else:
            raise ValueError(f"Unknown broker: {broker}")
    return _adapters[broker]


# ── Active broker resolution ───────────────────────────────────────────────────

def get_active_brokers() -> list[Broker]:
    """Return the list of brokers the user has selected via set_active_brokers."""
    raw = get_settings().active_brokers.strip()
    if not raw:
        return []
    result = []
    for name in raw.split(","):
        name = name.strip().lower()
        try:
            result.append(Broker(name))
        except ValueError:
            logger.warning("Unknown broker in ACTIVE_BROKERS: %s — skipping", name)
    return result


def get_all_supported_brokers() -> list[Broker]:
    return list(Broker)


# ── Portfolio fetching ─────────────────────────────────────────────────────────

async def get_combined_portfolio(brokers: list[Broker] | None = None) -> Portfolio:
    """
    Fetch holdings from all specified brokers (or active brokers if None)
    and merge them into a single Portfolio.
    """
    if brokers is None:
        brokers = get_active_brokers()

    if not brokers:
        raise ValueError(
            "No brokers selected. Ask the user which brokers to use, "
            "then call set_active_brokers."
        )

    # Fetch from all brokers concurrently
    tasks = [_get_adapter(b).get_holdings() for b in brokers]
    portfolios = await asyncio.gather(*tasks)

    # Merge holdings
    all_holdings = []
    for p in portfolios:
        all_holdings.extend(p.holdings)

    total_invested = sum(h.avg_cost * h.quantity for h in all_holdings)
    total_current  = sum(h.current_value for h in all_holdings)
    pnl_absolute   = total_current - total_invested
    pnl_percent    = (pnl_absolute / total_invested * 100) if total_invested else 0.0

    return Portfolio(
        holdings            = all_holdings,
        total_invested      = round(total_invested, 2),
        total_current_value = round(total_current, 2),
        total_pnl_absolute  = round(pnl_absolute, 2),
        total_pnl_percent   = round(pnl_percent, 2),
        brokers             = brokers,
    )


# ── Kept for backward compat ───────────────────────────────────────────────────

def get_adapter() -> BrokerAdapter:
    """Legacy single-adapter getter. Returns the first active broker's adapter."""
    active = get_active_brokers()
    if not active:
        return _get_adapter(Broker.UPSTOX)
    return _get_adapter(active[0])
