"""Holdings drift alert model — global, keyed on CIK.

Persists composition-drift detection results from
``style_drift_worker`` (lock 900_064). Drift is a property of the fund
itself (its composition has shifted vs its 8-quarter mean), not of an
org's view, so the table is GLOBAL — no organization_id, no RLS.
Pattern mirrors ``fund_risk_metrics``.

Distinct from ``StrategyDriftAlert`` which captures *performance*
drift (volatility/Sharpe/drawdown z-scores) and is org-scoped.
The two are complementary signals on the same fund.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class HoldingsDriftAlert(Base):
    """Composition drift result for a fund (CIK)."""

    __tablename__ = "holdings_drift_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    cik: Mapped[str] = mapped_column(Text, nullable=False)
    fund_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_report_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    historical_window_quarters: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )

    composite_drift: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    asset_mix_drift: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    fi_subtype_drift: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    geography_drift: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    issuer_category_drift: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False,
    )

    status: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    drivers: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb",
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    detected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
