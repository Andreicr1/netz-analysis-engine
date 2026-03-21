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
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
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
    last_adv_filed_at: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    funds: Mapped[list["SecManagerFund"]] = relationship(
        back_populates="manager", lazy="raise", cascade="all, delete-orphan",
    )
    team: Mapped[list["SecManagerTeam"]] = relationship(
        back_populates="manager", lazy="raise", cascade="all, delete-orphan",
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
    is_fund_of_funds: Mapped[bool | None] = mapped_column(Boolean)
    investor_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    data_fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    manager: Mapped["SecManager"] = relationship(back_populates="funds", lazy="raise")


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

    manager: Mapped["SecManager"] = relationship(back_populates="team", lazy="raise")


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
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
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
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(40), server_default="ofr_api")
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
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
