import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class StrategicAllocation(OrganizationScopedMixin, Base):
    __tablename__ = "strategic_allocation"

    allocation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    block_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("allocation_blocks.block_id"), nullable=False,
    )
    # PR-A25 (migration 0153): weights relaxed to nullable so the canonical
    # 18-block template can be seeded before the operator or PR-A26's
    # propose-then-approve flow fills the bands.
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    min_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    max_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    risk_budget: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    rationale: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    actor_source: Mapped[str | None] = mapped_column(String(20))
    # PR-A25 — operator may mark a canonical block as intentionally excluded
    # (forces zero exposure) without breaking template completeness. NULL
    # weights + excluded_from_portfolio = true means "operator decided out".
    excluded_from_portfolio: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=sa_false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class MacroRegimeSnapshot(Base):
    """Global daily regime snapshot. One row per date, no org_id, no RLS.

    Computed by regime_detection worker. Read by risk_calc for TAA band
    computation and by GET /allocation/regime for global regime display.
    """

    __tablename__ = "macro_regime_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    raw_regime: Mapped[str] = mapped_column(String(20), nullable=False)
    stress_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    signal_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signal_breakdown: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TaaRegimeState(OrganizationScopedMixin, Base):
    """Daily snapshot of smoothed TAA regime centers + effective bands.

    One row per (organization_id, profile, as_of_date). Updated by
    ``risk_calc`` worker after computing fund-level risk metrics.
    Read by ``_run_construction_async`` to resolve dynamic optimizer bands.

    When no row exists for the current org+profile, the construction
    pipeline falls back to static IPS bounds (identical to pre-TAA behavior).
    """

    __tablename__ = "taa_regime_state"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "profile", "as_of_date",
            name="uq_taa_regime_state_org_profile_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    raw_regime: Mapped[str] = mapped_column(String(20), nullable=False)
    stress_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    smoothed_centers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_bands: Mapped[dict] = mapped_column(JSONB, nullable=False)
    transition_velocity: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TacticalPosition(OrganizationScopedMixin, Base):
    __tablename__ = "tactical_positions"

    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    block_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("allocation_blocks.block_id"), nullable=False,
    )
    overweight: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    conviction_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    signal_source: Mapped[str | None] = mapped_column(String(50))
    rationale: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    actor_source: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(
        String(20), server_default="ic_manual",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
