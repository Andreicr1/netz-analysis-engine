"""Model Portfolio Pydantic schemas for API serialization.

Phase 1 Task 1.4 (2026-04-08) added the lifecycle state machine fields
to ``ModelPortfolioRead``: ``state``, ``state_metadata``,
``state_changed_at``, ``state_changed_by``, and ``allowed_actions``.

The frontend MUST consume ``allowed_actions`` to render buttons —
zero ``if state === "validated"`` conditionals in Svelte (DL3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = structlog.get_logger()


# Canonical state set — kept in sync with the CHECK constraint in
# migration 0098 and ``state_machine.TRANSITIONS``. Using a Literal
# here gives the OpenAPI schema a typed enum and lets the SvelteKit
# type generator emit the same union on the frontend.
PortfolioState = Literal[
    "draft",
    "constructed",
    "validated",
    "approved",
    "live",
    "paused",
    "archived",
    "rejected",
]


class ModelPortfolioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    profile: str
    display_name: str
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None
    inception_nav: Decimal
    status: str
    # ── State machine (migration 0098, Phase 1 Task 1.4) ──────────
    state: PortfolioState = "draft"
    state_metadata: dict[str, Any] = Field(default_factory=dict)
    state_changed_at: datetime | None = None
    state_changed_by: str | None = None
    #: Allowed actions for the current state, computed by
    #: ``state_machine.compute_allowed_actions``. Populated by the
    #: route handler before serialization — never read from the DB.
    #: Empty list means the portfolio is in a terminal state.
    allowed_actions: list[str] = Field(default_factory=list)

    fund_selection_schema: dict[str, Any] | None = None
    backtest_result: dict[str, Any] | None = None
    stress_result: dict[str, Any] | None = None
    created_at: datetime
    created_by: str | None = None
    weight_warning: bool = False

    @model_validator(mode="after")
    def _check_fund_weights(self) -> ModelPortfolioRead:
        """Flag when fund_selection_schema weights are outside [0.98, 1.02].

        Does NOT reject the payload (drafts are legitimate), but sets
        ``weight_warning=True`` so the frontend can surface a badge.
        """
        schema = self.fund_selection_schema
        if not schema or not isinstance(schema, dict):
            return self
        funds = schema.get("funds")
        if not funds:
            return self
        total = sum(float(f.get("weight", 0)) for f in funds)
        if total < 0.98 or total > 1.02:
            self.weight_warning = True
            logger.warning(
                "fund_weight_sum_anomaly",
                portfolio_id=str(self.id),
                total_weight=round(total, 6),
                status=self.status,
            )
        return self


class PortfolioTransitionRequest(BaseModel):
    """Body for ``POST /{portfolio_id}/transitions`` (Phase 5 Task 5.2).

    The Builder action bar dispatches every state-machine action through
    a single route so the frontend has one canonical mutation point. The
    ``action`` field is one of the strings the backend's
    ``compute_allowed_actions`` returned for the current state — the
    server validates the edge against ``state_machine.TRANSITIONS`` and
    raises 409 on illegal moves (DL3).

    ``reason`` is captured into the ``portfolio_state_transitions``
    audit row. ``self_approved`` (OD-6) and ``override_validation``
    (OD-5) flow through the optional ``metadata`` blob.
    """

    model_config = ConfigDict(extra="ignore")

    action: Literal[
        "validate",
        "approve",
        "activate",
        "pause",
        "resume",
        "archive",
        "reject",
        "rebuild_draft",
    ]
    reason: str | None = None
    metadata: dict[str, Any] | None = None


class ModelPortfolioCreate(BaseModel):
    """Phase 5 Task 5.1 — Builder ``NewPortfolioDialog`` create payload.

    The optional ``copy_from`` field clones the calibration row + the
    fund_selection_schema (composition seed) from an existing portfolio
    so PMs can fork an existing model without re-doing the 63-input
    calibration setup. ``mandate`` is captured here for the calibration
    row's Basic tier; the Pydantic schema field name remains ``profile``
    for backward compatibility but the dialog labels it ``Mandate``.
    """

    model_config = ConfigDict(extra="ignore")

    profile: str
    display_name: str
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None
    #: Optional source portfolio to clone calibration + composition from.
    copy_from: uuid.UUID | None = None


class ModelPortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None


# ── Portfolio Calibration (Phase 4 — Builder CalibrationPanel spine) ───────


class PortfolioCalibrationRead(BaseModel):
    """Full calibration surface for the Builder's CalibrationPanel.

    The 5 Basic tier columns + 10 Advanced tier columns are exposed as
    typed fields so the frontend can bind them to paired slider/number
    inputs (OD-2). The remaining Expert tier lives in
    ``expert_overrides`` as an untyped JSONB blob — CalibrationPanel
    renders it via an accordion of key/value rows and ships any edits
    back verbatim.

    ``schema_version`` lets the backend evolve the surface without
    breaking older frontends. DL5 explicit.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    portfolio_id: uuid.UUID
    schema_version: int

    # ── Basic tier (5) ──
    mandate: str
    cvar_limit: Decimal
    max_single_fund_weight: Decimal
    turnover_cap: Decimal | None = None
    stress_scenarios_active: list[str]

    # ── Advanced tier (10) ──
    regime_override: str | None = None
    bl_enabled: bool
    bl_view_confidence_default: Decimal
    garch_enabled: bool
    turnover_lambda: Decimal | None = None
    stress_severity_multiplier: Decimal
    advisor_enabled: bool
    cvar_level: Decimal
    lambda_risk_aversion: Decimal | None = None
    shrinkage_intensity_override: Decimal | None = None

    # ── Expert tier (48 inputs) ──
    expert_overrides: dict[str, Any]

    # ── Audit ──
    created_at: datetime
    updated_at: datetime
    updated_by: str | None = None


class PortfolioCalibrationUpdate(BaseModel):
    """Apply payload for PUT /{portfolio_id}/calibration.

    Every field is optional so the frontend can send partial updates —
    the route merges the body into the existing row and returns the
    post-update snapshot. Unknown fields are ignored (``extra="ignore"``)
    because the Expert tier sends arbitrary knobs via
    ``expert_overrides``.
    """

    model_config = ConfigDict(extra="ignore")

    # Basic tier
    mandate: str | None = None
    cvar_limit: Decimal | None = None
    max_single_fund_weight: Decimal | None = None
    turnover_cap: Decimal | None = None
    stress_scenarios_active: list[str] | None = None
    # Advanced tier
    regime_override: str | None = None
    bl_enabled: bool | None = None
    bl_view_confidence_default: Decimal | None = None
    garch_enabled: bool | None = None
    turnover_lambda: Decimal | None = None
    stress_severity_multiplier: Decimal | None = None
    advisor_enabled: bool | None = None
    cvar_level: Decimal | None = None
    lambda_risk_aversion: Decimal | None = None
    shrinkage_intensity_override: Decimal | None = None
    # Expert tier — merged into the JSONB column on write
    expert_overrides: dict[str, Any] | None = None


# ── Construction Run (Phase 3 — Job-or-Stream) ─────────────────────────────


class ConstructRunAccepted(BaseModel):
    """202 response for POST /{portfolio_id}/construct.

    The client polls the SSE stream at ``stream_url`` for progress
    events and retrieves the completed run via ``run_url``. DL18 P2
    Job-or-Stream contract.
    """

    run_id: uuid.UUID
    portfolio_id: uuid.UUID
    status: Literal["running", "succeeded", "failed", "cached"]
    job_id: str
    stream_url: str
    run_url: str


# ── PR-A26.1 — Propose Mode ──────────────────────────────────────────


class ProposedBand(BaseModel):
    """One block's proposed strategic anchor + drift band.

    Emitted by the propose-mode optimizer for every block in the
    canonical template (excluded blocks have ``target_weight = 0`` and
    ``drift_min = drift_max = 0``). Drift band is the hybrid
    ``max(0.02, 0.15 * target)`` derivation per A26.1 spec.
    """

    block_id: str
    target_weight: float
    drift_min: float
    drift_max: float
    rationale: str | None = None


class ProposalMetrics(BaseModel):
    """Headline ex-ante metrics for the propose-mode allocation.

    ``cvar_feasible`` is False when the cascade fell through to the
    Phase 3 min-CVaR fallback (universe floor exceeds the operator's
    target); the bands are still returned so the operator can decide
    whether to raise the limit or expand the universe.
    """

    expected_return: float | None = None
    expected_cvar: float | None = None
    expected_sharpe: float | None = None
    target_cvar: float | None = None
    cvar_feasible: bool


class LatestProposalResponse(BaseModel):
    """Response for ``GET /portfolio/profiles/{profile}/latest-proposal``."""

    run_id: uuid.UUID
    requested_at: datetime
    winner_signal: str
    proposed_bands: list[ProposedBand]
    proposal_metrics: ProposalMetrics


class JobCreatedResponse(BaseModel):
    """Generic 202 response for async propose-mode dispatch."""

    job_id: str
    sse_url: str
    run_id: uuid.UUID


# ── PR-A26.2 — Approval flow + overrides ────────────────────────────


class ApproveProposalRequest(BaseModel):
    """Body for ``POST /portfolio/profiles/{profile}/approve-proposal/{run_id}``.

    ``confirm_cvar_infeasible=True`` is required when approving a run
    that completed with ``winner_signal = 'proposal_cvar_infeasible'``
    — the operator is explicitly accepting a Strategic IPS whose bands
    cannot meet the configured CVaR target. ``operator_message`` lands
    on ``allocation_approvals.operator_message`` for audit.
    """

    confirm_cvar_infeasible: bool = False
    operator_message: str | None = Field(default=None, max_length=5000)


class StrategicAllocationRow(BaseModel):
    """Single strategic_allocation row after approval (Section C)."""

    block_id: str
    target_weight: float | None = None
    drift_min: float | None = None
    drift_max: float | None = None
    override_min: float | None = None
    override_max: float | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    excluded_from_portfolio: bool = False


class ApprovalResponse(BaseModel):
    """Response for ``POST /portfolio/profiles/{profile}/approve-proposal/{run_id}``.

    ``strategic_snapshot`` carries one entry per canonical block — the
    post-approval state of the 18 ``strategic_allocation`` rows that
    make up the Strategic IPS anchor. The frontend renders this as
    confirmation before wiring up the realize-mode CTA.
    """

    approval_id: uuid.UUID
    run_id: uuid.UUID
    organization_id: uuid.UUID
    profile: str
    approved_at: datetime
    approved_by: str
    cvar_feasible_at_approval: bool
    strategic_snapshot: list[StrategicAllocationRow]


class SetOverrideRequest(BaseModel):
    """Body for ``POST /portfolio/profiles/{profile}/set-override``.

    Either bound may be ``None`` — set just one side (e.g. only
    ``override_max``) or both, or clear both by passing ``None``.
    """

    block_id: str
    override_min: float | None = Field(default=None, ge=0.0, le=1.0)
    override_max: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def _validate_override_bounds(self) -> SetOverrideRequest:
        if (
            self.override_min is not None
            and self.override_max is not None
            and self.override_min > self.override_max
        ):
            raise ValueError("override_min must be <= override_max when both set")
        return self


# ── PR-A26.3 — Allocation page read endpoints ──────────────────────


class StrategicAllocationBlock(BaseModel):
    """One canonical block row on the allocation page (Section A / C).

    Extends :class:`StrategicAllocationRow` with ``block_name`` for the
    frontend (humanized label) plus ``approved_from_run_id`` for
    provenance tracing. ``target_weight`` / ``drift_*`` / ``approved_*``
    are ``None`` when the block has never been approved.
    """

    block_id: str
    block_name: str
    target_weight: float | None = None
    drift_min: float | None = None
    drift_max: float | None = None
    override_min: float | None = None
    override_max: float | None = None
    excluded_from_portfolio: bool = False
    approved_from_run_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None


class StrategicAllocationResponse(BaseModel):
    """Response for ``GET /portfolio/profiles/{profile}/strategic-allocation``.

    ``cvar_limit`` is resolved from the active ``portfolio_calibration``
    row for the profile's live/paused model portfolio; it falls back to
    the institutional default (per-profile) when no portfolio exists
    yet. ``has_active_approval`` is True iff at least one block row
    carries a non-NULL ``approved_at`` — i.e. the Strategic IPS has
    been snapshotted at least once for this (org, profile) pair.
    """

    organization_id: uuid.UUID
    profile: str
    cvar_limit: float
    has_active_approval: bool
    last_approved_at: datetime | None = None
    last_approved_by: str | None = None
    blocks: list[StrategicAllocationBlock]


class ApprovalHistoryEntry(BaseModel):
    """One row of the approval history table (Section G).

    ``is_active`` mirrors ``superseded_at IS NULL`` — useful on the
    frontend so the Active badge can be computed without re-checking
    the superseded timestamp.
    """

    approval_id: uuid.UUID
    run_id: uuid.UUID
    approved_by: str
    approved_at: datetime
    superseded_at: datetime | None = None
    cvar_at_approval: float | None = None
    expected_return_at_approval: float | None = None
    cvar_feasible_at_approval: bool
    operator_message: str | None = None
    is_active: bool


class ApprovalHistoryResponse(BaseModel):
    """Response for ``GET /portfolio/profiles/{profile}/approval-history``.

    Pagination is offset-based; ``total`` reflects the full count for
    the (org, profile) pair regardless of limit/offset.
    """

    organization_id: uuid.UUID
    profile: str
    total: int
    entries: list[ApprovalHistoryEntry]


class StressScenarioCatalogEntry(BaseModel):
    """One entry in the stress catalog returned by GET /portfolio/stress-test/scenarios."""

    scenario_id: str
    display_name: str
    description: str
    shock_components: dict[str, float]
    kind: Literal["preset", "user_defined"] = "preset"


class StressScenarioCatalog(BaseModel):
    """Catalog of stress scenarios (DL7 — 4 canonical presets)."""

    as_of: date
    scenarios: list[StressScenarioCatalogEntry]


# ── Regime (Phase 3 Task 3.6) ──────────────────────────────────────────────


class RegimeCurrentRead(BaseModel):
    """Response for GET /portfolio/regime/current.

    ``client_safe_label`` applies the OD-22 translation table so the
    frontend can surface jargon-free text without re-implementing the
    mapping (smart-backend / dumb-frontend).
    """

    regime: str
    """Raw regime enum: NORMAL | RISK_ON | RISK_OFF | CRISIS | INFLATION."""

    client_safe_label: str
    """OD-22 translation: Balanced | Expansion | Defensive | Stress | Inflation."""

    as_of_date: date | None = None
    reasons: dict[str, str] | None = None
    source: Literal["fred", "caller_fallback", "override"] = "fred"


# ── Parametric Stress Test ──────────────────────────────────────────────────


class StressTestRequest(BaseModel):
    """Request body for POST /{portfolio_id}/stress-test."""

    scenario_name: Literal[
        "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps", "custom"
    ] = "custom"
    shocks: dict[str, float] | None = None


class StressTestResponse(BaseModel):
    """Response body for POST /{portfolio_id}/stress-test."""

    portfolio_id: str
    scenario_name: str
    nav_impact_pct: float
    cvar_stressed: float | None = None
    block_impacts: dict[str, float]
    worst_block: str | None = None
    best_block: str | None = None


# ── Holdings Overlap ──────────────────────────────────────────────────────


class CusipExposureRead(BaseModel):
    cusip: str
    issuer_name: str | None = None
    total_exposure_pct: float
    funds_holding: list[str]
    is_breach: bool


class SectorExposureRead(BaseModel):
    sector: str
    total_exposure_pct: float
    cusip_count: int


class OverlapResultRead(BaseModel):
    portfolio_id: str
    computed_at: datetime
    limit_pct: float
    total_holdings: int
    funds_analyzed: int
    funds_without_data: int
    top_cusip_exposures: list[CusipExposureRead]
    sector_exposures: list[SectorExposureRead]
    breaches: list[CusipExposureRead]
    has_sufficient_data: bool
    data_warning: str | None = None


# ── Construction Advisor ──────────────────────────────────────────────────


class BlockGapRead(BaseModel):
    block_id: str
    display_name: str
    asset_class: str
    target_weight: float
    current_weight: float
    gap_weight: float
    priority: int
    reason: str


class CoverageAnalysisRead(BaseModel):
    total_blocks: int
    covered_blocks: int
    covered_pct: float
    block_gaps: list[BlockGapRead] = []


class CandidateFundRead(BaseModel):
    block_id: str
    instrument_id: str
    name: str
    ticker: str | None = None
    strategy_label: str | None = None
    volatility_1y: float | None = None
    correlation_with_portfolio: float
    overlap_pct: float
    projected_cvar_95: float | None = None
    cvar_improvement: float
    in_universe: bool
    external_id: str
    has_holdings_data: bool = True


class MinimumViableSetRead(BaseModel):
    funds: list[str]
    projected_cvar_95: float
    projected_within_limit: bool
    blocks_filled: list[str]
    search_method: str


class AlternativeProfileRead(BaseModel):
    profile: str
    cvar_limit: float
    current_cvar_would_pass: bool


# ── Rebalance Preview ──────────────────────────────────────────────────────


class HoldingInput(BaseModel):
    """A single current holding in the client's account (external input)."""

    instrument_id: uuid.UUID
    quantity: float
    current_price: float


class RebalancePreviewRequest(BaseModel):
    """Request body for POST /{portfolio_id}/rebalance/preview."""

    total_aum: float | None = None  # If omitted, computed from holdings + cash
    cash_available: float = 0.0
    current_holdings: list[HoldingInput]


class SuggestedTrade(BaseModel):
    """A single trade suggestion: BUY, SELL, or HOLD."""

    instrument_id: str
    fund_name: str
    block_id: str
    action: Literal["BUY", "SELL", "HOLD"]
    current_weight: float
    target_weight: float
    delta_weight: float  # target - current (percentage points)
    current_value: float
    target_value: float
    trade_value: float  # positive = buy, negative = sell
    estimated_quantity: float


class WeightDelta(BaseModel):
    """Block-level weight comparison: current vs target."""

    block_id: str
    current_weight: float
    target_weight: float
    delta_pp: float  # delta in percentage points


class RebalancePreviewResponse(BaseModel):
    """Response body for POST /{portfolio_id}/rebalance/preview."""

    portfolio_id: str
    portfolio_name: str
    profile: str
    total_aum: float
    cash_available: float
    total_trades: int
    estimated_turnover_pct: float
    trades: list[SuggestedTrade]
    weight_comparison: list[WeightDelta]
    cvar_95_projected: float | None = None
    cvar_limit: float | None = None
    cvar_warning: bool = False


# ── Construction Advisor ──────────────────────────────────────────────────


class ConstructionAdviceRead(BaseModel):
    portfolio_id: str
    profile: str
    current_cvar_95: float
    cvar_limit: float
    cvar_gap: float
    coverage: CoverageAnalysisRead
    candidates: list[CandidateFundRead] = []
    minimum_viable_set: MinimumViableSetRead | None = None
    alternative_profiles: list[AlternativeProfileRead] = []
    projected_cvar_is_heuristic: bool = True


# ── Construction Run Diff (Session C commit 4) ───────────────────────────
#
# Backing store: ``mv_construction_run_diff`` materialized view (shipped
# in Session 2.B commit 0118). One row per successful construction run
# that has a previous run. Consumed by Phase 4 Builder's "Compare to
# previous run" analytics panel.
#
# Sanitisation posture: primary jargon stripping happens upstream when
# construction_run_executor writes ``ex_ante_metrics`` and the diff view
# is computed over those already-clean JSONB keys. We still run every
# response body through ``sanitize_dict_keys`` at model-validator time
# as a belt-and-suspenders guard against future upstream regressions.


class ConstructionRunWeightDelta(BaseModel):
    """Per-instrument weight comparison between two construction runs.

    ``from_weight`` and ``to_weight`` are absolute portfolio weights
    (0.0 - 1.0). ``delta`` is ``to_weight - from_weight``; positive
    means the instrument gained weight in the newer run.
    """

    from_weight: float = Field(alias="from")
    to_weight: float = Field(alias="to")
    delta: float

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ConstructionRunMetricDelta(BaseModel):
    """Per-metric before/after/delta triple.

    ``from_value`` and ``to_value`` are the raw ex-ante metric values
    (e.g. expected return, portfolio volatility). ``delta`` is the
    numeric subtraction when both sides are numeric, otherwise ``None``
    (the MV computes the delta only for numeric metrics).
    """

    from_value: float | None = Field(default=None, alias="from")
    to_value: float | None = Field(default=None, alias="to")
    delta: float | None = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ConstructionRunDiffOut(BaseModel):
    """Response body for ``GET /{portfolio_id}/construction/runs/{run_id}/diff``.

    Reads directly from ``mv_construction_run_diff``. 404 when the
    requested ``(portfolio_id, run_id)`` pair has no row, which means
    either the run has not completed yet or the materialized view is
    stale — in both cases the caller should refresh the view or wait
    for the run to finish.
    """

    portfolio_id: uuid.UUID
    run_id: uuid.UUID
    previous_run_id: uuid.UUID | None
    requested_at: datetime | None
    weight_delta: dict[str, ConstructionRunWeightDelta]
    metrics_delta: dict[str, ConstructionRunMetricDelta]
    status_delta_text: str

    @model_validator(mode="after")
    def _sanitize_metrics_delta(self) -> "ConstructionRunDiffOut":
        """Belt-and-suspenders jargon stripping on metrics_delta keys.

        Primary sanitisation happens upstream in
        ``construction_run_executor`` (Session C commit 1) — by the
        time values land in the MV, keys are already in institutional
        phrasing. This validator translates any residual raw keys
        through ``METRIC_LABELS`` so a future upstream regression
        does not leak jargon through this endpoint. Values (the
        ``ConstructionRunMetricDelta`` triples) are preserved
        unchanged; only the outer dict keys are rewritten.
        """
        from app.domains.wealth.schemas.sanitized import humanize_metric

        md = self.metrics_delta
        if md:
            translated: dict[str, ConstructionRunMetricDelta] = {
                humanize_metric(k): v for k, v in md.items()
            }
            object.__setattr__(self, "metrics_delta", translated)
        return self
