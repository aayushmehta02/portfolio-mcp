from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class Broker(str, Enum):
    UPSTOX      = "upstox"
    FYERS       = "fyers"
    ANGEL_ONE   = "angel_one"
    DHAN        = "dhan"
    ICICI_DIRECT = "icici_direct"


class RiskTolerance(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class InvestmentGoal(str, Enum):
    WEALTH_PRESERVATION = "wealth_preservation"
    GROWTH = "growth"
    INCOME = "income"


class ExperienceLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


# ---------------------------------------------------------------------------
# Holdings — normalised schema all brokers map into
# ---------------------------------------------------------------------------

class Holding(BaseModel):
    ticker: str                         # NSE/BSE symbol e.g. "RELIANCE"
    isin: str
    exchange: Exchange
    quantity: int
    avg_cost: float                     # average buy price per share
    current_price: float
    current_value: float                # quantity × current_price
    pnl_absolute: float                 # current_value − (quantity × avg_cost)
    pnl_percent: float
    broker: Broker
    enriched: Optional[FundamentalData] = None  # filled by data pipeline


class Portfolio(BaseModel):
    holdings: list[Holding]
    total_invested: float
    total_current_value: float
    total_pnl_absolute: float
    total_pnl_percent: float
    brokers: list[Broker] = []          # all brokers contributing to this portfolio
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Fundamental data — merged output of the enrichment pipeline
# ---------------------------------------------------------------------------

class CorporateAction(BaseModel):
    action_type: str            # "dividend", "split", "buyback", "bonus"
    announcement_date: datetime
    effective_date: Optional[datetime] = None
    details: str


class Filing(BaseModel):
    filing_type: str            # "earnings", "pledging", "board_meeting", etc.
    filed_at: datetime
    title: str
    url: Optional[str] = None


class FundamentalData(BaseModel):
    ticker: str
    company_name: Optional[str] = None

    # ── Valuation ────────────────────────────────────────────────────────
    pe_ratio:       Optional[float] = None
    pb_ratio:       Optional[float] = None
    ev_ebitda:      Optional[float] = None
    market_cap:     Optional[float] = None   # Cr
    book_value:     Optional[float] = None
    face_value:     Optional[float] = None
    dividend_yield: Optional[float] = None

    # ── Profitability ────────────────────────────────────────────────────
    eps:              Optional[float] = None
    roe:              Optional[float] = None
    roce:             Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin:       Optional[float] = None

    # ── Leverage / liquidity ─────────────────────────────────────────────
    debt_to_equity:   Optional[float] = None
    interest_coverage: Optional[float] = None
    current_ratio:    Optional[float] = None

    # ── Cash flow ────────────────────────────────────────────────────────
    cfo: Optional[float] = None          # operating cash flow (latest annual, Cr)

    # ── Shareholding ─────────────────────────────────────────────────────
    promoter_holding_pct:  Optional[float] = None
    promoter_pledge_pct:   Optional[float] = None
    fii_holding_pct:       Optional[float] = None
    dii_holding_pct:       Optional[float] = None
    public_holding_pct:    Optional[float] = None

    # ── YoY growth ───────────────────────────────────────────────────────
    revenue_growth_yoy:  Optional[float] = None  # %
    earnings_growth_yoy: Optional[float] = None  # %

    # ── Compounded growth rates ──────────────────────────────────────────
    sales_cagr_3yr:   Optional[float] = None
    sales_cagr_5yr:   Optional[float] = None
    profit_cagr_3yr:  Optional[float] = None
    profit_cagr_5yr:  Optional[float] = None
    stock_cagr_3yr:   Optional[float] = None
    stock_cagr_5yr:   Optional[float] = None
    roe_3yr_avg:      Optional[float] = None

    # ── Time-series tables (from Screener) ───────────────────────────────
    annual_years:      list[str]                             = []
    annual_pnl:        dict[str, list[Optional[float]]]      = {}
    quarterly_periods: list[str]                             = []
    quarterly_pnl:     dict[str, list[Optional[float]]]      = {}

    # ── Corporate actions & filings ──────────────────────────────────────
    corporate_actions: list[CorporateAction] = []
    recent_filings:    list[Filing]          = []

    # ── Metadata ─────────────────────────────────────────────────────────
    sources_used: list[str] = []         # e.g. ["screener", "nse_bse"]
    enriched_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Assessment output
# ---------------------------------------------------------------------------

class Flag(BaseModel):
    ticker: str
    flag_type: str                      # "red" | "green"
    category: str                       # "promoter", "debt", "earnings", etc.
    signal: str                         # human-readable signal name
    detail: str                         # explanation
    severity: Optional[str] = None      # "critical" | "major" | "minor"


class AssessmentResult(BaseModel):
    flags: list[Flag]
    concentration_analysis: str         # free-text narrative
    sector_exposure: dict[str, float]   # sector → weight %
    health_score: str                   # narrative, NOT a number
    assessed_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    user_id: str
    risk_tolerance: RiskTolerance = RiskTolerance.MODERATE
    investment_horizon_years: Optional[int] = None
    investment_goal: InvestmentGoal = InvestmentGoal.GROWTH
    preferred_sectors: list[str] = []
    avoided_sectors: list[str] = []
    experience_level: ExperienceLevel = ExperienceLevel.INTERMEDIATE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
