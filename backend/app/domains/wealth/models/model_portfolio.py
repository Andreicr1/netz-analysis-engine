"""Model Portfolio ORM model.

Represents constructed model portfolios per risk profile. Fund selection
schema stored as JSONB. No schema_version (YAGNI — fix #34).

Phase 1 (2026-04-08) added the backend-authoritative state machine
columns (``state``, ``state_metadata``, ``state_changed_at``,
``state_changed_by``) plus the ``PortfolioStateTransition`` audit model.
The legacy ``status`` column is intentionally kept (OD-19 deferred drop)
for backward compat with the 3-profile CVaR monitor.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class ModelPortfolio(OrganizationScopedMixin, Base):
    __tablename__ = "model_portfolios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    benchmark_composite: Mapped[str | None] = mapped_column(String(255))
    inception_date: Mapped[date | None] = mapped_column(Date)
    backtest_start_date: Mapped[date | None] = mapped_column(Date)
    inception_nav: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="1000.0",
    )
    # Legacy status column — DO NOT REMOVE (OD-19 deferred to a 01xx
    # cleanup migration). The 3-profile CVaR monitor still reads this.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft",
    )
    # ── State machine columns (migration 0098) ──────────────────────
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="draft",
    )
    state_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    state_changed_by: Mapped[str | None] = mapped_column(String(128))

    fund_selection_schema: Mapped[dict | None] = mapped_column(JSONB)
    backtest_result: Mapped[dict | None] = mapped_column(JSONB)
    stress_result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(128))


# ── PR-A18 — CVaR defaults recalibrated to institutional-realistic ──────
# Post-A15 empirical universe floors (7.33/7.44/10.08% for
# conservative/balanced/growth) showed A12.2's aspirational defaults
# (2.5/5/8) forced all 3 profiles into phase_3_min_cvar_above_limit
# permanently. Recalibrated to 5/7.5/10/12.5 to reflect achievable
# tail-risk band for the current catalog + leave operator headroom
# to tighten downward once A17.2 NEW (Tiingo catalog) adds bond depth.
_CVAR_DEFAULT_BY_PROFILE: dict[str, Decimal] = {
    "conservative": Decimal("0.0500"),  # PR-A18: was 0.0250 (A12.2)
    "moderate": Decimal("0.0750"),      # PR-A18: was 0.0500
    "growth": Decimal("0.1000"),        # PR-A18: was 0.0800
    "aggressive": Decimal("0.1250"),    # PR-A18: was 0.1000
}


def default_cvar_limit_for_profile(profile: str | None) -> Decimal:
    """Return the institutional CVaR_95 starting default for ``profile``.

    Falls back to ``Decimal("0.0750")`` (moderate, PR-A18) for None /
    unknown values so code paths without a resolved profile (legacy
    fixtures, future profiles not yet calibrated) get a safe value
    rather than KeyError. Lookup is case-insensitive.
    """
    if profile is None:
        return Decimal("0.0750")
    return _CVAR_DEFAULT_BY_PROFILE.get(profile.lower(), Decimal("0.0750"))


class PortfolioCalibration(OrganizationScopedMixin, Base):
    """Tiered calibration surface for the Builder's CalibrationPanel.

    One row per portfolio (UNIQUE on ``portfolio_id``) — mutated in
    place via Preview/Apply on the Builder. Historical calibration
    state for any past ``/construct`` run is preserved via the
    ``calibration_snapshot`` JSONB column on
    ``portfolio_construction_runs``.

    Tiered input surface (DL5 — locked 2026-04-08):

    - **Basic (5 typed columns)** — mandate, cvar_limit,
      max_single_fund_weight, turnover_cap, stress_scenarios_active.
      80% of PM use cases live here.
    - **Advanced (10 typed columns)** — regime_override, bl_enabled,
      bl_view_confidence_default, garch_enabled, turnover_lambda,
      stress_severity_multiplier, advisor_enabled, cvar_level,
      lambda_risk_aversion, shrinkage_intensity_override.
    - **Expert (48 inputs)** — ``expert_overrides`` JSONB blob for
      knobs that have not graduated to typed columns.

    ``updated_at`` is maintained by the ``set_updated_at()`` trigger
    (migration 0100). The ORM does NOT need to set it on UPDATE.
    """

    __tablename__ = "portfolio_calibration"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, unique=True,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1",
    )

    # ── Basic tier (5) ──────────────────────────────────────────
    mandate: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="balanced",
    )
    cvar_limit: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0.05",
    )
    max_single_fund_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="0.10",
    )
    turnover_cap: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    stress_scenarios_active: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default="{gfc_2008,covid_2020,taper_2013,rate_shock_200bps}",
    )

    # ── Advanced tier (10) ──────────────────────────────────────
    regime_override: Mapped[str | None] = mapped_column(String(32))
    bl_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    bl_view_confidence_default: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="1.0",
    )
    garch_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    turnover_lambda: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    stress_severity_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, server_default="1.0",
    )
    advisor_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    cvar_level: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default="0.95",
    )
    lambda_risk_aversion: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    shrinkage_intensity_override: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    # ── Expert tier (48 inputs) ─────────────────────────────────
    expert_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )

    # ── Audit ───────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_by: Mapped[str | None] = mapped_column(String(128))


class PortfolioConstructionRun(OrganizationScopedMixin, Base):
    """One row per ``/construct`` invocation.

    Created and finalized by the ``construction_run_executor`` worker
    (Phase 3 Task 3.4, lock 900_101). Carries the full optimizer trace,
    binding constraints, regime context, ex-ante metrics, factor
    exposure, advisor advice, validation gate result, narrative output,
    and per-instrument rationale (DL4).

    Status enum mirrors the CHECK constraint in migration 0099:
    ``running`` → ``succeeded`` | ``failed`` | ``superseded``.

    The ``calibration_id`` FK is added in migration 0105 once
    ``portfolio_calibration`` exists. Until then, callers may write
    NULL or rely on ``calibration_hash`` for cache key resolution.
    """

    __tablename__ = "portfolio_construction_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )

    # Cache-key + idempotency
    calibration_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    calibration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    universe_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Run lifecycle
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # PR-A26.1 — 'realize' (default, IPS-anchored) vs 'propose' (optimizer
    # explores freely under CVaR + exclusions only). CHECK constraint in
    # migration 0154.
    run_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="realize",
    )
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wall_clock_ms: Mapped[int | None] = mapped_column()
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Quant outputs (all JSONB; defaults applied at the DB layer)
    optimizer_trace: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    binding_constraints: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )
    # PR-A11 — cascade telemetry: per-phase audit trail + operator signal.
    # Shape: {phase_attempts: [...], cascade_summary: str, phase2_max_var,
    # min_achievable_variance, feasibility_gap_pct, operator_signal}.
    # Legacy rows transparently carry the ``{}`` default.
    cascade_telemetry: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    regime_context: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    statistical_inputs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    ex_ante_metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    ex_ante_vs_previous: Mapped[dict | None] = mapped_column(JSONB)
    factor_exposure: Mapped[dict | None] = mapped_column(JSONB)
    stress_results: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )
    advisor: Mapped[dict | None] = mapped_column(JSONB)
    validation: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    narrative: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    rationale_per_weight: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )
    weights_proposed: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )

    # ── SSE event log (migration 0111) ──────────────────────────
    # Append-only JSONB array of {seq, type, ts, payload} entries
    # emitted by construction_run_executor during the run. Feeds the
    # Builder SSE late-subscriber replay and mv_construction_run_diff.
    event_log: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )


class PortfolioWeightSnapshot(Base):
    """Strategic / tactical / effective weight triples per day.

    TimescaleDB hypertable (7-day chunks, ``segmentby portfolio_id``,
    compression after 14 days). Keyed on ``(organization_id,
    portfolio_id, instrument_id, as_of)``.

    **No RLS on this table.** The composite PK places
    ``organization_id`` first, and the compressed hypertable pattern
    (shared with audit_events, fund_risk_metrics, macro_data)
    forbids enabling RLS. Every query MUST include
    ``WHERE organization_id = :org_id`` explicitly — enforced via
    the application-layer helper, code review, and load tests.

    Does NOT extend ``OrganizationScopedMixin`` because the mixin's
    implicit ``index=True`` on ``organization_id`` conflicts with
    the hypertable PK. The column is declared inline and
    ``organization_id`` is the first PK column.
    """

    __tablename__ = "portfolio_weight_snapshots"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, primary_key=True,
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, primary_key=True,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, primary_key=True,
    )
    as_of: Mapped[date] = mapped_column(
        Date, nullable=False, primary_key=True,
    )
    weight_strategic: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    weight_tactical: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    weight_effective: Mapped[Decimal | None] = mapped_column(Numeric(10, 8))
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="eod",
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PortfolioStressResult(OrganizationScopedMixin, Base):
    """One row per ``(construction_run_id, scenario)`` — stress output.

    Created by the stress suite that runs as part of
    ``_run_construction_async`` (Phase 3 Task 3.3). The UNIQUE
    constraint on ``(construction_run_id, scenario)`` is the P5
    idempotency contract (DL18): re-running stress for the same
    run can upsert via ``INSERT ... ON CONFLICT DO UPDATE`` safely.

    Scenario taxonomy (DL7):
    - ``scenario_kind='preset'`` — one of the 4 canonical keys
      (``gfc_2008``, ``covid_2020``, ``taper_2013``,
      ``rate_shock_200bps``)
    - ``scenario_kind='user_defined'`` — free-form inline custom
      (OD-9: catalog table deferred to v1.1)
    """

    __tablename__ = "portfolio_stress_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    construction_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )

    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_label: Mapped[str | None] = mapped_column(String(128))
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Top-line metrics (frontend matrix view)
    nav_impact_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cvar_impact_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    portfolio_loss_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_drawdown_implied: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    recovery_days_estimate: Mapped[int | None] = mapped_column(Integer)

    # Decomposition
    per_block_impact: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )
    per_instrument_impact: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]",
    )
    shock_params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )


class PortfolioAlert(OrganizationScopedMixin, Base):
    """Unified alerts feed — one row per worker emission.

    Replaces the fire-and-forget ``_publish_alert`` pattern in
    ``portfolio_eval.py`` with a durable row. Workers write here
    first, then Redis PUBLISH for the SSE bridge. Postgres is the
    source of truth; Redis is ephemeral.

    OD-23 is materialized: ``dedupe_key`` is a NOT NULL text column
    with a partial UNIQUE index on
    ``(portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL``.
    """

    __tablename__ = "portfolio_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
    )

    source_worker: Mapped[str] = mapped_column(String(64), nullable=False)
    source_lock_id: Mapped[int | None] = mapped_column(Integer)

    # OD-23: materialized dedupe key
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(128))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_by: Mapped[str | None] = mapped_column(String(128))
    auto_dismiss_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortfolioStateTransition(OrganizationScopedMixin, Base):
    """Immutable audit row for every state machine transition.

    One row per call to
    ``vertical_engines.wealth.model_portfolio.state_machine.transition()``.
    Records the source state, target state, actor, optional reason, and
    optional metadata. The ``portfolio_id`` FK has ``ON DELETE CASCADE``
    so archived portfolios drop their transition history together.

    RLS enabled in migration 0098 via the project-standard subselect.
    """

    __tablename__ = "portfolio_state_transitions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    state_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
