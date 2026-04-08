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


class ModelPortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: str
    display_name: str
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None


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
