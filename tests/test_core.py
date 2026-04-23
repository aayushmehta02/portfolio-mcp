"""
Unit tests — no network calls, no broker credentials needed.
Tests cover: holding normalisation, pipeline merge logic, prompt builder.
"""
import pytest
from datetime import datetime, timedelta

from portfolio_mcp.schemas import (
    Broker, Exchange, Holding, Portfolio, FundamentalData,
    UserProfile, RiskTolerance, InvestmentGoal, ExperienceLevel,
)
from portfolio_mcp.brokers.upstox import UpstoxAdapter
from portfolio_mcp.data.pipeline import _is_sufficient, _merge_screener
from portfolio_mcp.data.screener import ScreenerData
from portfolio_mcp.assessment.prompts import build_assessment_prompt


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

def make_holding(**kwargs) -> Holding:
    defaults = dict(
        ticker="RELIANCE",
        isin="INE002A01018",
        exchange=Exchange.NSE,
        quantity=10,
        avg_cost=2400.0,
        current_price=2600.0,
        current_value=26000.0,
        pnl_absolute=2000.0,
        pnl_percent=8.33,
        broker=Broker.UPSTOX,
    )
    defaults.update(kwargs)
    return Holding(**defaults)


def make_portfolio(holdings=None) -> Portfolio:
    h = holdings or [make_holding()]
    return Portfolio(
        holdings=h,
        total_invested=24000.0,
        total_current_value=26000.0,
        total_pnl_absolute=2000.0,
        total_pnl_percent=8.33,
        broker=Broker.UPSTOX,
    )


# ------------------------------------------------------------------
# Upstox normaliser
# ------------------------------------------------------------------

class TestUpstoxNormaliser:
    adapter = UpstoxAdapter()

    def test_basic_normalisation(self):
        raw = {
            "trading_symbol": "TCS",
            "isin": "INE467B01029",
            "exchange": "NSE_EQ",
            "quantity": "5",
            "average_price": "3500.0",
            "last_price": "3800.0",
        }
        h = self.adapter._normalise(raw)
        assert h.ticker == "TCS"
        assert h.exchange == Exchange.NSE
        assert h.quantity == 5
        assert h.current_value == pytest.approx(19000.0)
        assert h.pnl_absolute == pytest.approx(1500.0)
        assert h.pnl_percent == pytest.approx(8.57, abs=0.1)
        assert h.broker == Broker.UPSTOX

    def test_bse_exchange_detection(self):
        raw = {
            "trading_symbol": "WIPRO",
            "isin": "INE075A01022",
            "exchange": "BSE_EQ",
            "quantity": "10",
            "average_price": "400.0",
            "last_price": "420.0",
        }
        h = self.adapter._normalise(raw)
        assert h.exchange == Exchange.BSE

    def test_zero_quantity_pnl(self):
        raw = {
            "trading_symbol": "INFY",
            "isin": "INE009A01021",
            "exchange": "NSE_EQ",
            "quantity": "0",
            "average_price": "0.0",
            "last_price": "1500.0",
        }
        h = self.adapter._normalise(raw)
        assert h.pnl_percent == 0.0

    def test_portfolio_totals(self):
        holdings = [
            make_holding(ticker="RELIANCE", quantity=10, avg_cost=2400, current_price=2600,
                         current_value=26000, pnl_absolute=2000, pnl_percent=8.33),
            make_holding(ticker="TCS", quantity=5, avg_cost=3500, current_price=3800,
                         current_value=19000, pnl_absolute=1500, pnl_percent=8.57),
        ]
        portfolio = self.adapter._build_portfolio(holdings)
        assert portfolio.total_invested == pytest.approx(41500.0)
        assert portfolio.total_current_value == pytest.approx(45000.0)
        assert portfolio.total_pnl_absolute == pytest.approx(3500.0)


# ------------------------------------------------------------------
# Data pipeline merge logic
# ------------------------------------------------------------------

class TestPipelineMerge:

    def test_sufficient_data_passes(self):
        data = FundamentalData(
            ticker="RELIANCE",
            pe_ratio=24.5,
            debt_to_equity=0.4,
            promoter_holding_pct=50.2,
        )
        assert _is_sufficient(data) is True

    def test_insufficient_data_fails(self):
        data = FundamentalData(ticker="RELIANCE", pe_ratio=24.5)
        assert _is_sufficient(data) is False

    def test_merge_fills_gaps(self):
        target = FundamentalData(ticker="RELIANCE", pe_ratio=24.5)
        src = ScreenerData(
            ticker="RELIANCE",
            pe_ratio=99.9,          # should NOT overwrite existing
            debt_to_equity=0.4,     # should fill
            promoter_holding_pct=50.2,
            roe=18.5,
        )
        _merge_screener(target, src)
        assert target.pe_ratio == pytest.approx(24.5)     # existing preserved
        assert target.debt_to_equity == pytest.approx(0.4)
        assert target.promoter_holding_pct == pytest.approx(50.2)
        assert target.roe == pytest.approx(18.5)

    def test_merge_does_not_overwrite_with_none(self):
        target = FundamentalData(ticker="RELIANCE", roe=20.0)
        src = ScreenerData(ticker="RELIANCE", roe=None)
        _merge_screener(target, src)
        assert target.roe == pytest.approx(20.0)


# ------------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------------

class TestPromptBuilder:

    def test_prompt_contains_ticker(self):
        portfolio = make_portfolio()
        prompt = build_assessment_prompt(portfolio)
        assert "RELIANCE" in prompt

    def test_prompt_contains_profile_when_provided(self):
        portfolio = make_portfolio()
        profile = UserProfile(
            user_id="u1",
            risk_tolerance=RiskTolerance.AGGRESSIVE,
            investment_goal=InvestmentGoal.GROWTH,
            experience_level=ExperienceLevel.INTERMEDIATE,
        )
        prompt = build_assessment_prompt(portfolio, profile)
        assert "aggressive" in prompt.lower()
        assert "growth" in prompt.lower()

    def test_prompt_includes_enriched_data(self):
        h = make_holding()
        h.enriched = FundamentalData(
            ticker="RELIANCE",
            pe_ratio=24.5,
            debt_to_equity=0.4,
            promoter_holding_pct=50.2,
            sources_used=["screener"],
        )
        portfolio = make_portfolio(holdings=[h])
        prompt = build_assessment_prompt(portfolio)
        assert "pe_ratio" in prompt
        assert "24.5" in prompt

    def test_prompt_without_profile(self):
        portfolio = make_portfolio()
        prompt = build_assessment_prompt(portfolio, profile=None)
        assert "USER PROFILE" not in prompt
        assert "PORTFOLIO SUMMARY" in prompt


# ------------------------------------------------------------------
# SessionToken expiry
# ------------------------------------------------------------------

class TestSessionToken:
    def test_expired_token(self):
        from portfolio_mcp.schemas import SessionToken
        token = SessionToken(
            broker=Broker.UPSTOX,
            access_token="abc",
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        assert token.is_expired() is True

    def test_valid_token(self):
        from portfolio_mcp.schemas import SessionToken
        token = SessionToken(
            broker=Broker.UPSTOX,
            access_token="abc",
            expires_at=datetime.utcnow() + timedelta(hours=22),
        )
        assert token.is_expired() is False

    def test_no_expiry_never_expired(self):
        from portfolio_mcp.schemas import SessionToken
        token = SessionToken(broker=Broker.UPSTOX, access_token="abc")
        assert token.is_expired() is False
