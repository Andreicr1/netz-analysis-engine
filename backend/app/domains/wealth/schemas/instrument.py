"""Instrument schemas — Pydantic models for instruments_universe.

Includes per-fund-type ExtendedData schemas for the fact sheet endpoint.
All ``_pct`` fields store **pure decimal fractions** (0.015 = 1.5 %).
The frontend ``formatPercent()`` (Intl.NumberFormat style:"percent")
handles the ×100 conversion for display.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag


class InstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    instrument_id: uuid.UUID
    organization_id: uuid.UUID
    instrument_type: str
    name: str
    isin: str | None = None
    ticker: str | None = None
    bloomberg_ticker: str | None = None
    asset_class: str
    geography: str
    currency: str
    block_id: str | None = None
    is_active: bool
    approval_status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class InstrumentCreate(BaseModel):
    instrument_type: str = Field(pattern=r"^(fund|bond|equity)$")
    name: str = Field(min_length=1, max_length=255)
    isin: str | None = None
    ticker: str | None = None
    bloomberg_ticker: str | None = None
    asset_class: str
    geography: str
    currency: str = "USD"
    block_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class InstrumentUpdate(BaseModel):
    """Partial update for an instrument."""

    name: str | None = None
    block_id: str | None = None
    asset_class: str | None = None
    geography: str | None = None
    currency: str | None = None
    is_active: bool | None = None


class InstrumentRiskMetricsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    instrument_id: uuid.UUID
    score_components: dict[str, float] | None = None
    manager_score: float | None = None
    sharpe_1y: float | None = None
    volatility_1y: float | None = None
    max_drawdown_1y: float | None = None
    cvar_95_1m: float | None = None

    # Return metrics
    return_1y: float | None = None
    return_3y_ann: float | None = None

    # Risk metrics (additional)
    sortino_1y: float | None = None
    max_drawdown_3y: float | None = None

    # Relative metrics
    alpha_1y: float | None = None
    beta_1y: float | None = None
    information_ratio_1y: float | None = None
    tracking_error_1y: float | None = None

    # Momentum
    blended_momentum_score: float | None = None

    # GARCH
    volatility_garch: float | None = None


class InstrumentImportYahoo(BaseModel):
    """Request to import instruments via Yahoo Finance ticker(s)."""

    tickers: list[str] = Field(min_length=1, max_length=50)


class InstrumentImportCsvResponse(BaseModel):
    """Response from CSV import."""

    imported: int
    skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
#  Per-Fund-Type Extended Data (Phase 5 — Column Organization)
#
#  All _pct fields are PURE DECIMAL FRACTIONS:
#    0.0003 = 0.03%  |  0.0150 = 1.50%  |  0.1636 = 16.36%
#  Frontend formatPercent() (Intl.NumberFormat style:"percent") handles ×100.
# ═══════════════════════════════════════════════════════════════════════════


class _ExtendedBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class MutualFundExtendedData(_ExtendedBase):
    """Registered US mutual fund / closed-end / interval fund attributes.

    Sources: sec_registered_funds (N-CEN) + sec_fund_classes (XBRL) +
    sec_fund_prospectus_stats (RR1).
    """

    fund_type_label: Literal["mutual_fund"] = "mutual_fund"

    # N-CEN classification
    is_index: bool | None = None
    is_non_diversified: bool | None = None
    is_target_date: bool | None = None
    is_fund_of_fund: bool | None = None
    is_master_feeder: bool | None = None
    lei: str | None = None

    # Costs (decimal fractions)
    management_fee_pct: float | None = None
    net_operating_expenses_pct: float | None = None
    has_expense_limit: bool | None = None
    has_expense_waived: bool | None = None

    # Performance — N-CEN filing period (decimal fractions)
    return_before_fees_pct: float | None = None
    return_after_fees_pct: float | None = None
    return_stdv_before_fees_pct: float | None = None
    return_stdv_after_fees_pct: float | None = None

    # AUM & NAV
    monthly_avg_net_assets: float | None = None
    daily_avg_net_assets: float | None = None
    nav_per_share: float | None = None
    market_price_per_share: float | None = None

    # Operational flags
    is_sec_lending_authorized: bool | None = None
    did_lend_securities: bool | None = None
    has_line_of_credit: bool | None = None
    has_interfund_borrowing: bool | None = None
    has_swing_pricing: bool | None = None
    did_pay_broker_research: bool | None = None

    # Prospectus RR1 fee breakdown (decimal fractions)
    fee_waiver_pct: float | None = None
    distribution_12b1_pct: float | None = None
    acquired_fund_fees_pct: float | None = None
    other_expenses_pct: float | None = None
    portfolio_turnover_pct: float | None = None

    # Prospectus expense examples (USD, hypothetical $10k)
    expense_example_1y: float | None = None
    expense_example_3y: float | None = None
    expense_example_5y: float | None = None
    expense_example_10y: float | None = None

    # Prospectus bar chart (decimal fractions)
    bar_chart_best_qtr_pct: float | None = None
    bar_chart_worst_qtr_pct: float | None = None

    # Accounts
    total_shareholder_accounts: int | None = None

    # N-CEN metadata
    ncen_report_date: date | None = None


class ETFExtendedData(_ExtendedBase):
    """Exchange-Traded Fund attributes.

    Sources: sec_etfs (N-CEN).
    """

    fund_type_label: Literal["etf"] = "etf"

    # Tracking
    index_tracked: str | None = None
    tracking_difference_gross_pct: float | None = None
    tracking_difference_net_pct: float | None = None
    is_index: bool | None = None
    asset_class: str | None = None

    # Creation / redemption
    creation_unit_size: int | None = None
    is_in_kind_etf: bool | None = None
    pct_in_kind_creation: float | None = None
    pct_in_kind_redemption: float | None = None

    # Costs (decimal fractions)
    management_fee_pct: float | None = None
    net_operating_expenses_pct: float | None = None

    # Performance (decimal fractions)
    return_before_fees_pct: float | None = None
    return_after_fees_pct: float | None = None

    # AUM & NAV
    monthly_avg_net_assets: float | None = None
    daily_avg_net_assets: float | None = None
    nav_per_share: float | None = None
    market_price_per_share: float | None = None

    # Operational flags
    is_sec_lending_authorized: bool | None = None
    did_lend_securities: bool | None = None
    has_expense_limit: bool | None = None

    # N-CEN metadata
    ncen_report_date: date | None = None


class BDCExtendedData(_ExtendedBase):
    """Business Development Company attributes.

    Sources: sec_bdcs (N-CEN).
    """

    fund_type_label: Literal["bdc"] = "bdc"

    # Strategy
    investment_focus: str | None = None

    # Management
    is_externally_managed: bool | None = None

    # Costs (decimal fractions)
    management_fee_pct: float | None = None
    net_operating_expenses_pct: float | None = None

    # Performance (decimal fractions)
    return_before_fees_pct: float | None = None
    return_after_fees_pct: float | None = None

    # AUM & NAV
    monthly_avg_net_assets: float | None = None
    daily_avg_net_assets: float | None = None
    nav_per_share: float | None = None
    market_price_per_share: float | None = None

    # Operational flags
    is_sec_lending_authorized: bool | None = None
    has_line_of_credit: bool | None = None
    has_interfund_borrowing: bool | None = None

    # N-CEN metadata
    ncen_report_date: date | None = None


class MMFExtendedData(_ExtendedBase):
    """Money Market Fund attributes.

    Sources: sec_money_market_funds (N-MFP) + sec_mmf_metrics (time-series).
    """

    fund_type_label: Literal["money_market"] = "money_market"

    # Classification
    mmf_category: str | None = None
    is_govt_fund: bool | None = None
    is_retail: bool | None = None
    is_exempt_retail: bool | None = None

    # Portfolio risk
    weighted_avg_maturity: int | None = None
    weighted_avg_life: int | None = None

    # Yield (decimal fractions)
    seven_day_gross_yield_pct: float | None = None

    # AUM
    net_assets: float | None = None
    shares_outstanding: float | None = None
    total_portfolio_securities: float | None = None
    cash: float | None = None

    # Liquidity (decimal fractions)
    pct_daily_liquid: float | None = None
    pct_weekly_liquid: float | None = None

    # NAV policy
    seeks_stable_nav: bool | None = None
    stable_nav_price: float | None = None

    # Reporting
    reporting_period: date | None = None
    investment_adviser: str | None = None


class PrivateFundExtendedData(_ExtendedBase):
    """Private fund attributes (Hedge / PE / VC / RE / etc).

    Sources: sec_manager_funds (ADV Schedule D).
    """

    fund_type_label: Literal["private_fund"] = "private_fund"

    # Two-column SEC taxonomy
    sec_fund_type: str | None = None
    strategy_label: str | None = None

    # Fund characteristics
    gross_asset_value: int | None = None
    investor_count: int | None = None
    vintage_year: int | None = None
    is_fund_of_funds: bool | None = None


class UCITSExtendedData(_ExtendedBase):
    """UCITS European fund attributes.

    Sources: esma_funds (ESMA Register).
    """

    fund_type_label: Literal["ucits"] = "ucits"

    # Jurisdiction
    domicile: str | None = None
    host_member_states: list[str] = Field(default_factory=list)

    # Classification
    fund_type: str | None = None
    strategy_label: str | None = None

    # NAV resolution
    yahoo_ticker: str | None = None


def _get_extended_discriminator(v: Any) -> str:
    """Resolve discriminator tag from fund_type_label."""
    if isinstance(v, dict):
        return str(v.get("fund_type_label", "mutual_fund"))
    return str(getattr(v, "fund_type_label", "mutual_fund"))


FundExtendedData = Annotated[
    Union[
        Annotated[MutualFundExtendedData, Tag("mutual_fund")],
        Annotated[ETFExtendedData, Tag("etf")],
        Annotated[BDCExtendedData, Tag("bdc")],
        Annotated[MMFExtendedData, Tag("money_market")],
        Annotated[PrivateFundExtendedData, Tag("private_fund")],
        Annotated[UCITSExtendedData, Tag("ucits")],
    ],
    Discriminator(_get_extended_discriminator),
]
