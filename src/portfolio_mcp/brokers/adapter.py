"""
Abstract base class for broker adapters.

To add a new broker, subclass BrokerAdapter and implement the three
abstract methods below.  Everything else (retry logic, portfolio
assembly, error detection) is handled here.

Minimal new-broker checklist
─────────────────────────────
1.  Add a value to Broker enum in schemas.py  (e.g. Broker.ZERODHA = "zerodha")
2.  Add env keys to .env + config.py          (e.g. ZERODHA_API_KEY / ZERODHA_ACCESS_TOKEN)
3.  Create brokers/zerodha.py implementing:
        _fetch_holdings()  →  list of raw API rows
        _normalise(raw)    →  Holding
        reauthenticate()   →  OAuth flow + update_env_key(...)
4.  Register in router.py _get_adapter()
5.  (Optional) Override AUTH_ERROR_HINTS if the broker uses non-standard error text.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from portfolio_mcp.schemas import Broker, Holding, Portfolio

logger = logging.getLogger(__name__)


class BrokerAdapter(ABC):
    """
    Template-method base.  Subclasses only implement the three abstract
    methods; all boilerplate lives here.
    """

    # Override in subclass if the broker uses different error text.
    AUTH_ERROR_HINTS: tuple[str, ...] = (
        "401", "token", "unauthorized", "expired", "invalid",
    )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_holdings(self) -> Portfolio:
        """
        Fetch holdings, auto-retrying once after a re-auth if the token
        appears to be expired.
        """
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self._fetch_holdings)
        except Exception as exc:
            if self._is_auth_error(exc):
                logger.info("%s token expired — starting re-auth flow.", type(self).__name__)
                await self.reauthenticate()
                raw = await loop.run_in_executor(None, self._fetch_holdings)
            else:
                raise
        holdings = [self._normalise(row) for row in raw]
        return self._build_portfolio(holdings)

    @abstractmethod
    async def reauthenticate(self) -> None:
        """Run the broker's OAuth flow and persist the new token."""
        ...

    # ── Methods subclasses must implement ─────────────────────────────────────

    @abstractmethod
    def _fetch_holdings(self) -> list:
        """Synchronous call to the broker API.  Returns raw rows."""
        ...

    @abstractmethod
    def _normalise(self, raw) -> Holding:
        """Map one raw API row to the canonical Holding schema."""
        ...

    # ── Helpers subclasses may override ───────────────────────────────────────

    def _is_auth_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(hint.lower() in msg for hint in self.AUTH_ERROR_HINTS)

    # ── Shared implementation (not overridable) ────────────────────────────────

    def _build_portfolio(self, holdings: list[Holding]) -> Portfolio:
        """Assemble a Portfolio from a list of normalised Holdings."""
        total_invested = sum(h.avg_cost * h.quantity for h in holdings)
        total_current  = sum(h.current_value for h in holdings)
        pnl_absolute   = total_current - total_invested
        pnl_percent    = (pnl_absolute / total_invested * 100) if total_invested else 0.0

        # Derive brokers from holdings so we don't need to hard-code it.
        brokers: list[Broker] = list({h.broker for h in holdings})

        return Portfolio(
            holdings            = holdings,
            total_invested      = round(total_invested, 2),
            total_current_value = round(total_current, 2),
            total_pnl_absolute  = round(pnl_absolute, 2),
            total_pnl_percent   = round(pnl_percent, 2),
            brokers             = brokers,
        )
