"""Cross-vertical ORM models for global (non-tenant-scoped) tables.

GLOBAL TABLES: No organization_id, no RLS.
These tables store publicly available data shared across all tenants.
See CLAUDE.md: "macro_data, allocation_blocks, vertical_config_defaults
have NO organization_id, NO RLS."

Import direction: app.shared → app.core (safe, verified).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import AuditMetaMixin, Base, IdMixin


class MacroData(Base, AuditMetaMixin):
    """FRED macroeconomic time-series observations.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by obs_date (1-month chunks).
    Compression: 3 months. segmentby: series_id.
    Always include obs_date filter in queries for chunk pruning.

    Stores raw FRED observations (VIX, Treasury rates, CPI, Fed Funds)
    and derived series (yield curve spread, CPI YoY).
    """

    __tablename__ = "macro_data"

    series_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    obs_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    source: Mapped[str | None] = mapped_column(String(30), server_default="fred")
    is_derived: Mapped[bool] = mapped_column(Boolean, server_default="false")


class MacroRegionalSnapshot(Base, IdMixin, AuditMetaMixin):
    """Regional macro scoring snapshot — one row per calendar day.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by as_of_date (1-month chunks).
    Compression: 3 months. segmentby: none.
    Always include as_of_date filter in queries for chunk pruning.

    Populated by macro_ingestion worker.  Uses JSONB (supports GIN indexes)
    — intentional difference from credit's macro_snapshots which uses JSON.
    Stores composite scores for US/Europe/Asia/EM + global indicators.
    """

    __tablename__ = "macro_regional_snapshots"

    as_of_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, unique=True, index=True,
    )
    data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MacroSnapshot(Base, IdMixin, AuditMetaMixin):
    """Daily FRED macro data snapshot — one row per calendar day.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by as_of_date (1-month chunks).
    Compression: 3 months. segmentby: none.
    Always include as_of_date filter in queries for chunk pruning.

    Populated by market_data_engine.py. Immutable once stored.
    Global: macro conditions are the same for all funds/tenants.
    """

    __tablename__ = "macro_snapshots"

    as_of_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, unique=True, index=True,
    )
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  SEC Data Providers — Global Tables (no organization_id, no RLS)
# ═══════════════════════════════════════════════════════════════════════════


class SecManager(Base):
    """Form ADV manager catalog.

    GLOBAL TABLE: No organization_id, no RLS.
    Natural PK on crd_number (SEC CRD identifier).
    """

    __tablename__ = "sec_managers"

    crd_number: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[str | None] = mapped_column(Text)
    firm_name: Mapped[str] = mapped_column(Text, nullable=False)
    sec_number: Mapped[str | None] = mapped_column(Text)
    registration_status: Mapped[str | None] = mapped_column(Text)
    aum_total: Mapped[int | None] = mapped_column(BigInteger)
    aum_discretionary: Mapped[int | None] = mapped_column(BigInteger)
    aum_non_discretionary: Mapped[int | None] = mapped_column(BigInteger)
    total_accounts: Mapped[int | None] = mapped_column(Integer)
    fee_types: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    client_types: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    state: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    compliance_disclosures: Mapped[int | None] = mapped_column(Integer)
    # Fund counts from Form ADV Section 7B
    private_fund_count: Mapped[int | None] = mapped_column(Integer)
    hedge_fund_count: Mapped[int | None] = mapped_column(Integer)
    pe_fund_count: Mapped[int | None] = mapped_column(Integer)
    vc_fund_count: Mapped[int | None] = mapped_column(Integer)
    real_estate_fund_count: Mapped[int | None] = mapped_column(Integer)
    securitized_fund_count: Mapped[int | None] = mapped_column(Integer)
    liquidity_fund_count: Mapped[int | None] = mapped_column(Integer)
    other_fund_count: Mapped[int | None] = mapped_column(Integer)
    total_private_fund_assets: Mapped[int | None] = mapped_column(BigInteger)
    last_adv_filed_at: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    funds: Mapped[list[SecManagerFund]] = relationship(
        back_populates="manager", lazy="raise", cascade="all, delete-orphan",
    )
    team: Mapped[list[SecManagerTeam]] = relationship(
        back_populates="manager", lazy="raise", cascade="all, delete-orphan",
    )
    brochure_sections: Mapped[list[SecManagerBrochureText]] = relationship(
        lazy="raise", cascade="all, delete-orphan",
    )


class SecManagerFund(Base, IdMixin):
    """ADV Schedule D private funds.

    GLOBAL TABLE: No organization_id, no RLS.
    FK to sec_managers on crd_number.
    """

    __tablename__ = "sec_manager_funds"

    crd_number: Mapped[str] = mapped_column(
        Text, ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False,
    )
    fund_name: Mapped[str] = mapped_column(Text, nullable=False)
    fund_id: Mapped[str | None] = mapped_column(Text)
    gross_asset_value: Mapped[int | None] = mapped_column(BigInteger)
    fund_type: Mapped[str | None] = mapped_column(Text)
    strategy_label: Mapped[str | None] = mapped_column(Text)
    is_fund_of_funds: Mapped[bool | None] = mapped_column(Boolean)
    investor_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    manager: Mapped[SecManager] = relationship(back_populates="funds", lazy="raise")


class SecManagerTeam(Base, IdMixin):
    """ADV Part 2A team bios.

    GLOBAL TABLE: No organization_id, no RLS.
    FK to sec_managers on crd_number.
    """

    __tablename__ = "sec_manager_team"

    crd_number: Mapped[str] = mapped_column(
        Text, ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False,
    )
    person_name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    education: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    certifications: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    years_experience: Mapped[int | None] = mapped_column(Integer)
    bio_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    manager: Mapped[SecManager] = relationship(back_populates="team", lazy="raise")


class SecManagerBrochureText(Base):
    """ADV Part 2A brochure text sections for full-text search.

    GLOBAL TABLE: No organization_id, no RLS.
    Composite PK on (crd_number, section, filing_date).
    GIN index on tsvector(content) for full-text search.
    """

    __tablename__ = "sec_manager_brochure_text"

    crd_number: Mapped[str] = mapped_column(
        Text,
        ForeignKey("sec_managers.crd_number", ondelete="CASCADE"),
        primary_key=True,
    )
    section: Mapped[str] = mapped_column(Text, primary_key=True)
    filing_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecEntityLink(Base):
    """Maps Registered advisers to related SEC entities (parent 13F filers, managed funds).

    GLOBAL TABLE: No organization_id, no RLS.
    The critical linkage that connects RIAs to their holdings data.
    RIAs file ADV with one CIK; parent holding companies file 13F with a different CIK.
    """

    __tablename__ = "sec_entity_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_crd: Mapped[str] = mapped_column(
        Text, ForeignKey("sec_managers.crd_number", ondelete="CASCADE"), nullable=False,
    )
    related_cik: Mapped[str] = mapped_column(Text, nullable=False)
    relationship: Mapped[str] = mapped_column(Text, nullable=False)  # parent_13f, subsidiary, managed_fund
    related_name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # name_match, foia_umbrella, manual
    confidence: Mapped[float | None] = mapped_column(Float)  # 0.0-1.0 for fuzzy matches
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class Sec13fHolding(Base):
    """13F quarterly holdings.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by report_date (3-month chunks).
    Compression enabled for chunks older than 6 months (segmentby=cik).
    Full historical depth: EDGAR data available from 1999 (100+ quarters).
    Use time-bounded queries — always include report_date filter for performance.

    market_value stored in USD (edgartools already converts from thousands to dollars).
    PK is (report_date, cik, cusip) — no surrogate id column (hypertable requirement).
    """

    __tablename__ = "sec_13f_holdings"

    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    cik: Mapped[str] = mapped_column(Text, primary_key=True)
    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    filing_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    accession_number: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    asset_class: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    market_value: Mapped[int | None] = mapped_column(BigInteger)
    discretion: Mapped[str | None] = mapped_column(Text)
    voting_sole: Mapped[int | None] = mapped_column(BigInteger)
    voting_shared: Mapped[int | None] = mapped_column(BigInteger)
    voting_none: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class Sec13fDiff(Base):
    """Quarter-over-quarter 13F changes.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by quarter_to (3-month chunks).
    Compression enabled for chunks older than 6 months (segmentby=cik).
    Use time-bounded queries — always include quarter_to filter for performance.

    action is one of: NEW_POSITION, INCREASED, DECREASED, EXITED, UNCHANGED.
    PK is (quarter_to, cik, cusip, quarter_from) — no surrogate id column.
    """

    __tablename__ = "sec_13f_diffs"

    quarter_to: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    cik: Mapped[str] = mapped_column(Text, primary_key=True)
    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    quarter_from: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    shares_before: Mapped[int | None] = mapped_column(BigInteger)
    shares_after: Mapped[int | None] = mapped_column(BigInteger)
    shares_delta: Mapped[int | None] = mapped_column(BigInteger)
    value_before: Mapped[int | None] = mapped_column(BigInteger)
    value_after: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    weight_before: Mapped[float | None] = mapped_column(Float)
    weight_after: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecCusipTickerMap(Base):
    """CUSIP → Ticker mapping via OpenFIGI batch API.

    GLOBAL TABLE: No organization_id, no RLS.
    Enables real-time YFinance price lookups for 13F holdings.
    Populated by sec seed Phase 6. Refreshed monthly (M2 worker scope).
    """

    __tablename__ = "sec_cusip_ticker_map"

    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str | None] = mapped_column(Text)
    issuer_name: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    security_type: Mapped[str | None] = mapped_column(Text)
    figi: Mapped[str | None] = mapped_column(Text)
    composite_figi: Mapped[str | None] = mapped_column(Text)
    resolved_via: Mapped[str] = mapped_column(Text, nullable=False)
    is_tradeable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_verified_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TreasuryData(Base):
    """US Treasury fiscal data time-series.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by obs_date (1-month chunks).
    Compression: 3 months. segmentby: series_id.
    Always include obs_date filter in queries for chunk pruning.

    Stores rates (by security_desc), debt snapshots, auction results,
    exchange rates, and interest expense from the Treasury Fiscal Data API.
    """

    __tablename__ = "treasury_data"

    obs_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    source: Mapped[str] = mapped_column(String(40), server_default="treasury_api")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class OfrHedgeFundData(Base):
    """OFR Hedge Fund Monitor time-series.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by obs_date (3-month chunks).
    Compression: 6 months. segmentby: series_id.
    Always include obs_date filter in queries for chunk pruning.

    Stores leverage ratios, industry AUM, strategy breakdowns, repo volumes,
    counterparty metrics, and stress scenarios from the OFR API.
    """

    __tablename__ = "ofr_hedge_fund_data"

    obs_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    source: Mapped[str] = mapped_column(String(40), server_default="ofr_api")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  ESMA Data Providers — Global Tables (no organization_id, no RLS)
# ═══════════════════════════════════════════════════════════════════════════


class EsmaManager(Base):
    """European fund manager from ESMA Register.

    GLOBAL TABLE: No organization_id, no RLS.
    Natural PK on esma_id (ESMA management company identifier).
    """

    __tablename__ = "esma_managers"

    esma_id: Mapped[str] = mapped_column(Text, primary_key=True)
    lei: Mapped[str | None] = mapped_column(Text)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    authorization_status: Mapped[str | None] = mapped_column(Text)
    fund_count: Mapped[int | None] = mapped_column(Integer)
    sec_crd_number: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    funds: Mapped[list[EsmaFund]] = relationship(
        back_populates="manager", lazy="raise", cascade="all, delete-orphan",
    )


class EsmaFund(Base):
    """UCITS fund entry from ESMA Register.

    GLOBAL TABLE: No organization_id, no RLS.
    Natural PK on ISIN (unique identifier for securities).
    FK to esma_managers on esma_manager_id.
    """

    __tablename__ = "esma_funds"

    isin: Mapped[str] = mapped_column(Text, primary_key=True)
    fund_name: Mapped[str] = mapped_column(Text, nullable=False)
    esma_manager_id: Mapped[str] = mapped_column(
        Text, ForeignKey("esma_managers.esma_id", ondelete="CASCADE"), nullable=False,
    )
    domicile: Mapped[str | None] = mapped_column(Text)
    fund_type: Mapped[str | None] = mapped_column(Text)
    strategy_label: Mapped[str | None] = mapped_column(Text)
    host_member_states: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    yahoo_ticker: Mapped[str | None] = mapped_column(Text)
    ticker_resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    manager: Mapped[EsmaManager] = relationship(back_populates="funds", lazy="raise")


class EsmaIsinTickerMap(Base):
    """ISIN → Yahoo Finance ticker mapping via OpenFIGI batch API.

    GLOBAL TABLE: No organization_id, no RLS.
    Enables YFinance NAV lookups for ESMA-registered UCITS funds.
    Populated by ESMA seed Phase 2. Refreshed periodically.
    """

    __tablename__ = "esma_isin_ticker_map"

    isin: Mapped[str] = mapped_column(Text, primary_key=True)
    fund_lei: Mapped[str | None] = mapped_column(Text, index=True)
    yahoo_ticker: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    resolved_via: Mapped[str] = mapped_column(Text, nullable=False)
    is_tradeable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    last_verified_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecNportHolding(Base):
    """N-PORT monthly portfolio holdings for US mutual funds.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by report_date (3-month chunks).
    Compression: 3 months. segmentby: cik.
    Always include report_date filter in queries for chunk pruning.

    PK is (report_date, cik, cusip) — no surrogate id column.
    """

    __tablename__ = "sec_nport_holdings"

    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    cik: Mapped[str] = mapped_column(Text, primary_key=True)
    cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    isin: Mapped[str | None] = mapped_column(Text)
    issuer_name: Mapped[str | None] = mapped_column(Text)
    asset_class: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    market_value: Mapped[int | None] = mapped_column(BigInteger)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str | None] = mapped_column(Text)
    pct_of_nav: Mapped[Decimal | None] = mapped_column(Numeric)
    is_restricted: Mapped[bool | None] = mapped_column(Boolean)
    fair_value_level: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecRegisteredFund(Base):
    """Registered fund catalog — mutual funds, ETFs, closed-end, interval.

    GLOBAL TABLE: No organization_id, no RLS.
    Populated by nport_fund_discovery worker from EDGAR N-PORT headers.
    PK is CIK (fund-level, not adviser-level).
    """

    __tablename__ = "sec_registered_funds"

    cik: Mapped[str] = mapped_column(Text, primary_key=True)
    crd_number: Mapped[str | None] = mapped_column(
        Text, ForeignKey("sec_managers.crd_number", ondelete="SET NULL"),
    )
    fund_name: Mapped[str] = mapped_column(Text, nullable=False)
    fund_type: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_label: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)
    series_id: Mapped[str | None] = mapped_column(Text)
    class_id: Mapped[str | None] = mapped_column(Text)
    total_assets: Mapped[int | None] = mapped_column(BigInteger)
    total_shareholder_accounts: Mapped[int | None] = mapped_column(Integer)
    inception_date: Mapped[dt.date | None] = mapped_column(Date)
    fiscal_year_end: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    domicile: Mapped[str] = mapped_column(Text, nullable=False, server_default="US")
    last_nport_date: Mapped[dt.date | None] = mapped_column(Date)
    aum_below_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # N-CEN classification flags
    is_index: Mapped[bool | None] = mapped_column(Boolean)
    is_non_diversified: Mapped[bool | None] = mapped_column(Boolean)
    is_target_date: Mapped[bool | None] = mapped_column(Boolean)
    is_fund_of_fund: Mapped[bool | None] = mapped_column(Boolean)
    is_master_feeder: Mapped[bool | None] = mapped_column(Boolean)
    lei: Mapped[str | None] = mapped_column(String)

    # Costs
    management_fee: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    net_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    has_expense_limit: Mapped[bool | None] = mapped_column(Boolean)
    has_expense_waived: Mapped[bool | None] = mapped_column(Boolean)

    # Performance (annual, from N-CEN filing period)
    return_before_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_after_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_stdv_before_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_stdv_after_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    # AUM & NAV
    monthly_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    nav_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    market_price_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    # Operational
    is_sec_lending_authorized: Mapped[bool | None] = mapped_column(Boolean)
    did_lend_securities: Mapped[bool | None] = mapped_column(Boolean)
    has_line_of_credit: Mapped[bool | None] = mapped_column(Boolean)
    has_interfund_borrowing: Mapped[bool | None] = mapped_column(Boolean)
    has_swing_pricing: Mapped[bool | None] = mapped_column(Boolean)
    did_pay_broker_research: Mapped[bool | None] = mapped_column(Boolean)

    # N-CEN metadata
    ncen_accession_number: Mapped[str | None] = mapped_column(String)
    ncen_report_date: Mapped[dt.date | None] = mapped_column(Date)
    ncen_fund_id: Mapped[str | None] = mapped_column(String)


class SecEtf(Base):
    """ETF catalog derived from N-CEN filings.

    GLOBAL TABLE: No organization_id, no RLS.
    PK is series_id (S000xxxxx).  Seeded from EDGAR N-CEN datasets.
    """

    __tablename__ = "sec_etfs"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, nullable=False)
    fund_id: Mapped[str | None] = mapped_column(String)
    fund_name: Mapped[str] = mapped_column(String, nullable=False)
    lei: Mapped[str | None] = mapped_column(String)
    ticker: Mapped[str | None] = mapped_column(String)
    isin: Mapped[str | None] = mapped_column(String)

    strategy_label: Mapped[str | None] = mapped_column(String)
    asset_class: Mapped[str | None] = mapped_column(String)
    index_tracked: Mapped[str | None] = mapped_column(String)
    is_index: Mapped[bool | None] = mapped_column(Boolean, server_default="true")
    is_in_kind_etf: Mapped[bool | None] = mapped_column(Boolean)

    creation_unit_size: Mapped[int | None] = mapped_column(Integer)
    pct_in_kind_creation: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pct_in_kind_redemption: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    tracking_difference_gross: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    tracking_difference_net: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    management_fee: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    net_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_before_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_after_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    monthly_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    nav_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    market_price_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    is_sec_lending_authorized: Mapped[bool | None] = mapped_column(Boolean)
    did_lend_securities: Mapped[bool | None] = mapped_column(Boolean)
    has_expense_limit: Mapped[bool | None] = mapped_column(Boolean)

    ncen_report_date: Mapped[dt.date | None] = mapped_column(Date)
    domicile: Mapped[str] = mapped_column(String(2), nullable=False, server_default="US")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    inception_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecBdc(Base):
    """BDC (Business Development Company) catalog from N-CEN filings.

    GLOBAL TABLE: No organization_id, no RLS.
    PK is series_id (S000xxxxx or CIK fallback).
    """

    __tablename__ = "sec_bdcs"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, nullable=False)
    fund_id: Mapped[str | None] = mapped_column(String)
    fund_name: Mapped[str] = mapped_column(String, nullable=False)
    lei: Mapped[str | None] = mapped_column(String)
    ticker: Mapped[str | None] = mapped_column(String)
    isin: Mapped[str | None] = mapped_column(String)

    strategy_label: Mapped[str | None] = mapped_column(String, server_default="Private Credit")
    investment_focus: Mapped[str | None] = mapped_column(String)

    management_fee: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    net_operating_expenses: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_before_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_after_fees: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    monthly_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_avg_net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    nav_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    market_price_per_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    is_externally_managed: Mapped[bool | None] = mapped_column(Boolean)
    is_sec_lending_authorized: Mapped[bool | None] = mapped_column(Boolean)
    has_line_of_credit: Mapped[bool | None] = mapped_column(Boolean)
    has_interfund_borrowing: Mapped[bool | None] = mapped_column(Boolean)

    ncen_report_date: Mapped[dt.date | None] = mapped_column(Date)
    domicile: Mapped[str] = mapped_column(String(2), nullable=False, server_default="US")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    inception_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecMoneyMarketFund(Base):
    """Money Market Fund catalog from N-MFP filings.

    GLOBAL TABLE: No organization_id, no RLS.
    PK is series_id (S000xxxxx).
    """

    __tablename__ = "sec_money_market_funds"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, nullable=False)
    accession_number: Mapped[str | None] = mapped_column(String)
    fund_name: Mapped[str] = mapped_column(String, nullable=False)
    lei_series: Mapped[str | None] = mapped_column(String)
    lei_registrant: Mapped[str | None] = mapped_column(String)

    mmf_category: Mapped[str] = mapped_column(String, nullable=False)
    strategy_label: Mapped[str | None] = mapped_column(String)
    is_govt_fund: Mapped[bool | None] = mapped_column(Boolean)
    is_retail: Mapped[bool | None] = mapped_column(Boolean)
    is_exempt_retail: Mapped[bool | None] = mapped_column(Boolean)

    weighted_avg_maturity: Mapped[int | None] = mapped_column(Integer)
    weighted_avg_life: Mapped[int | None] = mapped_column(Integer)
    seven_day_gross_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    shares_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    total_portfolio_securities: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    cash: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))

    pct_daily_liquid_latest: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pct_weekly_liquid_latest: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    seeks_stable_nav: Mapped[bool | None] = mapped_column(Boolean)
    stable_nav_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))

    reporting_period: Mapped[dt.date | None] = mapped_column(Date)
    investment_adviser: Mapped[str | None] = mapped_column(String)
    domicile: Mapped[str] = mapped_column(String(2), nullable=False, server_default="US")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    metrics: Mapped[list[SecMmfMetric]] = relationship(
        "SecMmfMetric", back_populates="fund", lazy="raise",
    )


class SecMmfMetric(Base):
    """Daily MMF metrics time-series from N-MFP filings.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by metric_date (1-month chunks).
    Compression: 3 months. segmentby: series_id, class_id.
    """

    __tablename__ = "sec_mmf_metrics"

    metric_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    series_id: Mapped[str] = mapped_column(
        String, ForeignKey("sec_money_market_funds.series_id"), primary_key=True,
    )
    class_id: Mapped[str] = mapped_column(String, primary_key=True)
    accession_number: Mapped[str] = mapped_column(String, nullable=False)

    seven_day_net_yield: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    daily_gross_subscriptions: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    daily_gross_redemptions: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))

    pct_daily_liquid: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    pct_weekly_liquid: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    total_daily_liquid_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    total_weekly_liquid_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))

    fund: Mapped[SecMoneyMarketFund] = relationship(
        "SecMoneyMarketFund", back_populates="metrics", lazy="raise",
    )


class SecFundClass(Base):
    """Share class within a registered fund series.

    GLOBAL TABLE: No organization_id, no RLS.
    Populated by nport_fund_discovery worker from EDGAR filing header SGML.
    Composite PK: (cik, series_id, class_id).
    """

    __tablename__ = "sec_fund_classes"

    cik: Mapped[str] = mapped_column(
        Text, ForeignKey("sec_registered_funds.cik", ondelete="CASCADE"), primary_key=True,
    )
    series_id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_name: Mapped[str | None] = mapped_column(Text)
    class_name: Mapped[str | None] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # OEF XBRL data (from N-CSR inline XBRL — per share class)
    expense_ratio_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    advisory_fees_paid: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    expenses_paid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    avg_annual_return_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    net_assets: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    holdings_count: Mapped[int | None] = mapped_column(Integer)
    portfolio_turnover_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    fund_name: Mapped[str | None] = mapped_column(String)
    perf_inception_date: Mapped[dt.date | None] = mapped_column(Date)
    xbrl_accession: Mapped[str | None] = mapped_column(String)
    xbrl_period_end: Mapped[dt.date | None] = mapped_column(Date)


class SecFundStyleSnapshot(Base):
    """Quarterly style classification derived from N-PORT holdings.

    GLOBAL TABLE: No organization_id, no RLS.
    Computed by nport_ingestion worker via quant_engine/style_analysis.py.
    PK is (cik, report_date).
    """

    __tablename__ = "sec_fund_style_snapshots"

    cik: Mapped[str] = mapped_column(Text, primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    style_label: Mapped[str] = mapped_column(Text, nullable=False)
    growth_tilt: Mapped[float] = mapped_column(Float, nullable=False)
    sector_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    equity_pct: Mapped[float | None] = mapped_column(Float)
    fixed_income_pct: Mapped[float | None] = mapped_column(Float)
    cash_pct: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


# ═══════════════════════════════════════════════════════════════════════════
#  BIS + IMF Data Providers — Global Tables (no organization_id, no RLS)
# ═══════════════════════════════════════════════════════════════════════════


class BisStatistics(Base):
    """BIS credit-to-GDP gap, debt service ratio, and property prices.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by period (1-year chunks).
    Compression: 1 year. segmentby: country_code.
    Always include period filter in queries for chunk pruning.

    Datasets: WS_CREDIT_GAP, WS_DSR, WS_SPP.
    """

    __tablename__ = "bis_statistics"

    country_code: Mapped[str] = mapped_column(Text, primary_key=True)
    indicator: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class ImfWeoForecast(Base):
    """IMF World Economic Outlook 5-year forward forecasts.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by period (1-year chunks).
    Compression: 1 year. segmentby: country_code.
    Always include period filter in queries for chunk pruning.

    Indicators: NGDP_RPCH (GDP growth), PCPIPCH (inflation),
    GGXCNL_NGDP (fiscal balance), GGXWDG_NGDP (govt debt).
    """

    __tablename__ = "imf_weo_forecasts"

    country_code: Mapped[str] = mapped_column(Text, primary_key=True)
    indicator: Mapped[str] = mapped_column(Text, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    edition: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class SecInstitutionalAllocation(Base):
    """Institutional 13F reverse lookup — who holds what.

    GLOBAL TABLE: No organization_id, no RLS.
    TimescaleDB hypertable partitioned by report_date (3-month chunks).
    Compression: 6 months. segmentby: filer_cik.
    Always include report_date filter in queries for chunk pruning.

    PK is (report_date, filer_cik, target_cusip) — no surrogate id column.
    """

    __tablename__ = "sec_institutional_allocations"

    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    filer_cik: Mapped[str] = mapped_column(Text, primary_key=True)
    target_cusip: Mapped[str] = mapped_column(Text, primary_key=True)
    filer_name: Mapped[str] = mapped_column(Text, nullable=False)
    filer_type: Mapped[str | None] = mapped_column(Text)
    target_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    market_value: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
