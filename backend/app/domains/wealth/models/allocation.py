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
    # PR-A26.2 (migration 0155): optimizer-bound ``min_weight`` /
    # ``max_weight`` columns were dropped. ``target_weight`` persists as
    # the "approved anchor" — NULL until the propose-then-approve flow
    # snapshots a propose run into the row. Operator overrides and the
    # drift band now own the optimizer-facing semantics.
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    # Drift band around the approved target. Populated atomically by the
    # approve-proposal endpoint; NULL when the block has never been
    # approved. Realize-mode BlockConstraint reads these two columns.
    drift_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    drift_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    # Operator-set propose-mode overrides. Persist across approvals;
    # cleared only via ``POST /set-override`` with explicit NULL. Have
    # no effect on realize-mode runs.
    override_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    override_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    # Provenance back to the propose run that seeded the approved snapshot.
    approved_from_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class AllocationApproval(Base):
    """PR-A26.2 — audit log of approved propose-mode allocations.

    GLOBAL table (no RLS) — admin-visible audit history. Queries that
    want org scope must still filter by ``organization_id`` explicitly.

    At most one row per ``(organization_id, profile)`` carries
    ``superseded_at IS NULL`` at any given time; the approve-proposal
    endpoint supersedes the prior active row before inserting the new
    one (single transaction).
    """

    __tablename__ = "allocation_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # No FK — historical runs can be purged independently. Integrity
    # comes from the (run_id, organization_id, profile) triple plus
    # the superseded_at lifecycle.
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cvar_at_approval: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    expected_return_at_approval: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 6),
    )
    cvar_feasible_at_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    operator_message: Mapped[str | None] = mapped_column(Text)


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
