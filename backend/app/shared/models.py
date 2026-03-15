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

from sqlalchemy import JSON, Boolean, Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin


class MacroData(Base, AuditMetaMixin):
    """FRED macroeconomic time-series observations.

    GLOBAL TABLE: No organization_id, no RLS.
    Stores raw FRED observations (VIX, Treasury rates, CPI, Fed Funds)
    and derived series (yield curve spread, CPI YoY).
    Regular PostgreSQL table — not a TimescaleDB hypertable, since
    only ~5 series at daily/monthly frequency produce ~12,500 rows/decade.
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
