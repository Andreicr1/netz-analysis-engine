"""Shadow OMS models — Phase 9 Block D.

Two models supporting the Live Workbench's drift analysis and trade
execution workflow:

- ``PortfolioActualHoldings`` — one row per live portfolio, mutable
  JSONB of actual weights. Updated transactionally on trade execution.
- ``TradeTicket`` — append-only log of executed BUY/SELL instructions.

Both tables are org-scoped. RLS enabled in migration 0107.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class PortfolioActualHoldings(OrganizationScopedMixin, Base):
    """Actual (post-drift) holdings for a live portfolio.

    PK is ``portfolio_id`` itself — one row per portfolio, mutable.
    The ``holdings`` JSONB mirrors the ``fund_selection_schema.funds``
    array schema but with actual weights instead of target weights.
    """

    __tablename__ = "portfolio_actual_holdings"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True,
    )
    holdings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )
    last_rebalanced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TradeTicket(OrganizationScopedMixin, Base):
    """Append-only log of executed trade instructions.

    Each ``POST /model-portfolios/{id}/execute-trades`` inserts one
    row per trade in a single transaction.
    """

    __tablename__ = "trade_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False,
    )
    instrument_id: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(10), nullable=False,
    )
    delta_weight: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False,
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    executed_by: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
