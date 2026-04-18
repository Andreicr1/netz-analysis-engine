"""Institutional nomenclature sanitation layer — Wealth response schemas.

Governance: Risk Methodology v3. This module is the **single backend
source of truth** for translating raw quant jargon (CVaR, GARCH, DTW,
EWMA, CFNAI, regime enums) into the institutional phrasing that
user-facing Wealth API consumers receive. Any schema that surfaces
those metrics must route through the helpers or mixins here before
its response reaches the API boundary.

Design choices
--------------
1.  **Contract-breaking, not versioned.** The sanitised label replaces
    the jargon value in place (e.g. `global_regime: "RISK_ON"` becomes
    `global_regime: "Expansion"`). There is no `/v2/` split — the
    engine is still monorepo-wide and the frontend adapts in the same
    PR wave (Onda 1). This removes the "pay jargon debt twice" trap.

2.  **Keys stay stable where they are field identifiers.** Field
    names on stable schemas (`FundRiskRead.cvar_95_1m`) are left
    alone: renaming them would cascade through every ORM mapping,
    worker, test fixture, and existing client. Instead, we sanitise
    *values* and *dict keys in free-form payloads* (`score_components`,
    `quant_data`, `report_json`). This is the highest-leverage point
    in the pipeline — an institutional allocator never sees the raw
    enum, and the internal engine keeps its stable names.

3.  **Fallthrough on unknown input.** `humanize_metric()` and
    `humanize_regime()` return the raw string on unknown keys so an
    ad-hoc metric from a new chapter prompt remains visible rather
    than silently dropped. Add new mappings to the constants below.

4.  **Mirror — not import — of the frontend dictionary.**
    `frontends/wealth/src/lib/i18n/quant-labels.ts` carries the same
    mapping. A future test (`test_sanitized_mirrors_frontend.py`)
    will diff the two files to prevent drift. We duplicate on purpose
    because importing across the Python/TypeScript boundary is worse
    than a short two-location mirror with a guard test.

Consumers in this commit
------------------------
    GlobalRegimeRead       — model_validator humanizes raw_regime
    CVaRStatus             — inherits SanitizedRegimeFieldMixin
    RegimeHistoryPoint     — inherits SanitizedRegimeFieldMixin
    MacroReviewRead        — model validator walks report_json
    DDChapterRead          — model validator walks quant_data
    FundRiskRead           — model validator sanitises score_components
    FundScoreRead          — model validator sanitises score_components

Adding a new consumer
---------------------
    1. Import the relevant mixin or helper here.
    2. Either inherit the mixin or add a `@model_validator(mode="after")`
       that calls the helper.
    3. Add a unit test in `backend/tests/wealth/schemas/test_sanitized.py`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── PR-A19.1 Section C — cascade-aware operator signal ───────────────
#
# ``winner_status`` on the optimizer result only distinguishes
# ``optimal`` from ``degraded``, which conflates two very different
# operator actions: "Phase 3 min-CVaR won because target was infeasible"
# (raise the CVaR target) vs "Phase 2 robust won under uncertainty"
# (accept the robustness premium). ``WinnerSignal`` is an additive
# enum — ``winner_status`` is kept for backwards compatibility and
# frontend fallback.


class WinnerSignal(str, Enum):
    OPTIMAL = "optimal"
    # phase_3_min_cvar winner — CVaR target is below what any portfolio
    # in the universe can achieve. Operator remedy: raise the CVaR
    # target OR expand the universe with lower-tail-risk instruments.
    CVAR_INFEASIBLE_MIN_VAR = "cvar_infeasible_min_var"
    # phase_2_ru_robust winner — Phase 1 infeasible / unavailable and
    # the robust SOCP carries a μ-uncertainty premium. Healthy fallback.
    ROBUSTNESS_FALLBACK = "robustness_fallback"
    # Catch-all for degraded winners we haven't classified (e.g.
    # phase_3 win where CVaR is within limit but operator still sees
    # degraded — atypical).
    DEGRADED_OTHER = "degraded_other"
    # No winner at all: empty universe, PSD violation, polytope empty.
    PRE_SOLVE_FAILURE = "pre_solve_failure"
    # PR-A22 — cascade aborted before the optimizer ran because one or
    # more blocks in the profile's StrategicAllocation have zero
    # approved candidates in ``instruments_org``. Operator remedy:
    # expand the approved universe for those blocks or zero their
    # target_weight explicitly.
    BLOCK_COVERAGE_INSUFFICIENT = "block_coverage_insufficient"
    # PR-A25 — cascade aborted because the ``(organization_id, profile)``
    # pair is missing one or more canonical ``allocation_blocks`` rows.
    # Structural failure that indicates the migration 0153 trigger did
    # not run, not an operator misconfiguration. Handled upstream of the
    # coverage gate so the stricter failure surfaces first.
    TEMPLATE_INCOMPLETE = "template_incomplete"


def compute_winner_signal(
    *,
    winning_phase: str | None,
    cvar_within_limit: bool,
    cvar_limit: float | None,
    min_achievable_cvar: float | None,
) -> WinnerSignal:
    """Classify a cascade outcome into a ``WinnerSignal``.

    Inputs are the same fields ``construction_run_executor`` already
    has on hand. Pure function — safe to unit test without touching
    the solver.
    """
    if winning_phase is None:
        return WinnerSignal.PRE_SOLVE_FAILURE
    if winning_phase == "phase_1_ru_max_return" and cvar_within_limit:
        return WinnerSignal.OPTIMAL
    if (
        winning_phase == "phase_3_min_cvar"
        and cvar_limit is not None
        and min_achievable_cvar is not None
        and min_achievable_cvar > cvar_limit
    ):
        return WinnerSignal.CVAR_INFEASIBLE_MIN_VAR
    if winning_phase == "phase_2_ru_robust":
        return WinnerSignal.ROBUSTNESS_FALLBACK
    return WinnerSignal.DEGRADED_OTHER


def build_operator_message(
    *,
    signal: WinnerSignal,
    cvar_limit: float | None,
    min_achievable_cvar: float | None,
    expected_return: float | None,
) -> dict[str, Any] | None:
    """Backend-owned copy for non-``optimal`` signals.

    Frontend renders the string verbatim — smart-backend/dumb-frontend
    principle (``CLAUDE.md`` "Frontend formatter discipline"). Returns
    None for ``OPTIMAL`` so consumers can guard on truthiness.
    """
    if signal is WinnerSignal.OPTIMAL:
        return None
    if signal is WinnerSignal.CVAR_INFEASIBLE_MIN_VAR:
        cvar_pct = (cvar_limit or 0.0) * 100
        min_pct = (min_achievable_cvar or 0.0) * 100
        er_pct = (expected_return or 0.0) * 100
        return {
            "title": "CVaR target infeasible with current universe",
            "body": (
                f"Your CVaR target of {cvar_pct:.1f}% cannot be achieved "
                f"by any portfolio in the current universe. The minimum "
                f"achievable CVaR is {min_pct:.2f}%. The delivered "
                f"allocation is the minimum-variance portfolio "
                f"(expected return {er_pct:.2f}%). To improve expected "
                f"return, either (a) raise the CVaR target to at least "
                f"{min_pct:.2f}%, or (b) expand the universe with "
                f"lower-tail-risk instruments (IG credit, Treasuries)."
            ),
            "severity": "warning",
            "action_hint": "raise_cvar_or_expand_universe",
        }
    if signal is WinnerSignal.ROBUSTNESS_FALLBACK:
        return {
            "title": "Robust allocation selected",
            "body": (
                "Phase 1 was unavailable or infeasible; the delivered "
                "allocation is from the robust SOCP (Phase 2), which "
                "applies an uncertainty premium on expected returns. "
                "Expected return may be below the unconstrained "
                "optimum — this is the cost of the robustness margin."
            ),
            "severity": "info",
            "action_hint": "review_robust_margin",
        }
    if signal is WinnerSignal.DEGRADED_OTHER:
        return {
            "title": "Construction degraded",
            "body": (
                "The cascade completed outside the optimal phase. "
                "Review cascade telemetry for the winning phase and "
                "infeasibility reasons."
            ),
            "severity": "warning",
            "action_hint": "review_cascade_telemetry",
        }
    # PRE_SOLVE_FAILURE
    return {
        "title": "Construction failed before solve",
        "body": (
            "The optimizer could not run: either the universe was "
            "empty, the covariance matrix failed PSD validation, or "
            "the block constraints were unsatisfiable. Check data "
            "quality and block bands."
        ),
        "severity": "error",
        "action_hint": "inspect_universe_and_blocks",
    }

# ── Canonical mapping — Risk Methodology v3 ───────────────────────

METRIC_LABELS: dict[str, str] = {
    # CVaR / Expected Shortfall family
    "cvar": "Conditional Tail Risk (CVaR 95%)",
    "cvar_95": "Conditional Tail Risk (CVaR 95%)",
    "expected_shortfall": "Conditional Tail Risk (CVaR 95%)",
    "es": "Conditional Tail Risk (CVaR 95%)",
    "cvar_95_1m": "Conditional Tail Risk (CVaR 95%) — 1M",
    "cvar_95_3m": "Conditional Tail Risk (CVaR 95%) — 3M",
    "cvar_95_6m": "Conditional Tail Risk (CVaR 95%) — 6M",
    "cvar_95_12m": "Conditional Tail Risk (CVaR 95%) — 12M",
    "cvar_95_conditional": "Conditional Tail Risk (CVaR 95%) — Regime-conditioned",
    # Regime
    "regime": "Market Regime",
    "market_regime": "Market Regime",
    # Volatility models
    "garch": "Conditional Volatility",
    "garch_vol": "Conditional Volatility",
    "garch_volatility": "Conditional Volatility",
    "volatility_garch": "Conditional Volatility",
    "ewma": "Conditional Volatility",
    "ewma_vol": "Conditional Volatility",
    "ewma_volatility": "Conditional Volatility",
    # Macro composite
    "cfnai": "Real Economy Activity Index",
    "macro_score": "Real Economy Activity Index",
    "macroscore": "Real Economy Activity Index",
    # Drawdown
    "drawdown": "Maximum Drawdown",
    "max_drawdown": "Maximum Drawdown",
    "maxdrawdown": "Maximum Drawdown",
    "maximum_drawdown": "Maximum Drawdown",
    "max_drawdown_1y": "Maximum Drawdown (1Y)",
    "max_drawdown_3y": "Maximum Drawdown (3Y)",
    # Strategy drift
    "dtw_drift_score": "Strategy Deviation Score",
    "dtw_drift": "Strategy Deviation Score",
}

# Backend emits SCREAMING_SNAKE enums; the institutional reading is
# the three-state Expansion / Cautious / Stress phrasing.
REGIME_LABELS: dict[str, str] = {
    "RISK_ON": "Expansion",
    "EXPANSION": "Expansion",
    "NEUTRAL": "Cautious",
    "RISK_OFF": "Cautious",
    "CAUTIOUS": "Cautious",
    "CRISIS": "Stress",
    "STRESS": "Stress",
}

# Event-type labels used by construction_run_executor and any other
# SSE-publishing worker. Raw internal names (e.g. "optimizer_started")
# get translated to institutional phrasing before emission. Anything
# not in this dict passes through unchanged so a new event type added
# by a worker remains visible on the wire until a label is registered.
EVENT_TYPE_LABELS: dict[str, str] = {
    # Lifecycle
    "run_started": "Construction started",
    "run_cancelled": "Construction cancelled",
    "run_succeeded": "Construction succeeded",
    "run_failed": "Construction failed",
    # Universe pre-filter (PR-A8 — Layer 3 correlation dedup)
    "prefilter_dedup_completed": "Universe pre-filter completed",
    # Optimizer cascade
    "optimizer_started": "Optimizer started",
    "optimizer_phase_start": "Optimizer phase started",
    "optimizer_phase_complete": "Optimizer phase completed",
    "optimizer_phase_completed": "Optimizer phase completed",
    "optimizer_cascade_completed": "Optimizer cascade completed",
    # PR-A11 — cascade telemetry (sanitized operator-facing event)
    "cascade_telemetry_completed": "Optimizer cascade summary",
    # Stress suite
    "stress_started": "Stress tests started",
    "stress_scenario_completed": "Stress scenario completed",
    "stress_completed": "Stress tests completed",
    # Advisor
    "advisor_started": "Advisor started",
    "advisor_completed": "Advisor completed",
    # Validation gate
    "validation_started": "Validation gate started",
    "validation_passed": "Validation gate passed",
    "validation_failed": "Validation gate failed",
    # Narrative
    "narrative_started": "Narrative generation started",
    "narrative_completed": "Narrative generation completed",
}


def humanize_event_type(raw: str) -> str:
    """Translate a raw internal event type to its public label.

    Pass-through for unknown event types — a worker that emits a new
    event type remains visible until its label is added here.
    """
    if not isinstance(raw, str):
        return raw
    return EVENT_TYPE_LABELS.get(raw, raw)


def sanitize_payload(raw: Any) -> Any:
    """Walk an arbitrary payload recursively, translating jargon.

    - Dict keys matching ``METRIC_LABELS`` are translated to institutional
      labels.
    - String values matching ``REGIME_LABELS`` are translated to the
      tri-state phrasing (Expansion / Cautious / Stress).
    - Lists are walked element-by-element.
    - Anything else passes through unchanged (numbers, booleans, None,
      unrecognised strings).

    The transformation is non-mutating — the caller's original payload
    is never touched. Used by construction_run_executor to sanitise
    every SSE event before it crosses the wire AND before it lands in
    ``portfolio_construction_runs.event_log``.
    """
    if isinstance(raw, dict):
        out: dict[str, Any] = {}
        for k, v in raw.items():
            public_key = humanize_metric(k) if isinstance(k, str) else k
            out[public_key] = sanitize_payload(v)
        return out
    if isinstance(raw, list):
        return [sanitize_payload(item) for item in raw]
    if isinstance(raw, str):
        return humanize_regime(raw)
    return raw


def _normalise_metric_key(raw: str) -> str:
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def humanize_metric(raw: Any) -> Any:
    """Translate a quant metric key to its institutional label.

    Pass-through on non-string input and on unknown keys — the caller
    never loses data, only gains a nicer label when one is defined.
    """
    if not isinstance(raw, str):
        return raw
    return METRIC_LABELS.get(_normalise_metric_key(raw), raw)


def humanize_regime(value: Any) -> Any:
    """Translate a regime enum value to institutional tri-state.

    Unknown enums pass through unchanged so a new backend state (e.g.
    `STAGFLATION`) remains visible in the API response.
    """
    if value is None or not isinstance(value, str):
        return value
    return REGIME_LABELS.get(value.strip().upper(), value)


def sanitize_dict_keys(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a new dict with jargon keys translated to institutional labels.

    Values are untouched. Key collisions after translation (e.g. two
    aliases mapping to the same label) resolve in iteration order —
    the last wins. Add explicit aliases to METRIC_LABELS when the
    collision is intentional.
    """
    if raw is None:
        return None
    return {humanize_metric(k): v for k, v in raw.items()}


def sanitize_regime_dict(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Translate every string value in a regime dict, recursively.

    Handles the common `{global: "RISK_ON", regional: {US: "RISK_OFF", ...}}`
    shape without assuming depth.
    """
    if raw is None:
        return None
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, str):
            out[k] = humanize_regime(v)
        elif isinstance(v, dict):
            out[k] = sanitize_regime_dict(v)
        else:
            out[k] = v
    return out


def sanitize_report_json(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Walk a free-form committee report_json and sanitise jargon branches.

    Touches:
      * `report["regime"]["global"]` and nested `regional.*`
      * `report["score_components"]` dict keys
      * `report["metrics"]` dict keys (if present)

    Unknown branches are preserved byte-for-byte. A shallow copy
    protects the caller from mutation; inner dicts are rebuilt only
    when they contain jargon.
    """
    if raw is None:
        return None
    out = dict(raw)
    if isinstance(out.get("regime"), dict):
        out["regime"] = sanitize_regime_dict(out["regime"])
    if isinstance(out.get("score_components"), dict):
        out["score_components"] = sanitize_dict_keys(out["score_components"])
    if isinstance(out.get("metrics"), dict):
        out["metrics"] = sanitize_dict_keys(out["metrics"])
    return out


# ── Pydantic mixins ──────────────────────────────────────────────


class SanitizedRegimeFieldMixin(BaseModel):
    """For schemas with a single `regime: str | None` field.

    Inherit *in addition to* BaseModel (or chain with ConfigDict base).
    The after-validator fires once at construction and replaces the
    stored value in-place so `model_dump()` already emits the
    institutional label.
    """

    @model_validator(mode="after")
    def _sanitize_regime_field(self) -> "SanitizedRegimeFieldMixin":
        current = getattr(self, "regime", None)
        if isinstance(current, str):
            object.__setattr__(self, "regime", humanize_regime(current))
        return self


class SanitizedScoreComponentsMixin(BaseModel):
    """For schemas with a `score_components: dict[str, Any]` free-form field.

    Used by `FundRiskRead`, `FundScoreRead`, and similar schemas where
    the dict keys are raw metric identifiers that reach the UI.
    """

    @model_validator(mode="after")
    def _sanitize_score_components(self) -> "SanitizedScoreComponentsMixin":
        sc = getattr(self, "score_components", None)
        if isinstance(sc, dict):
            object.__setattr__(self, "score_components", sanitize_dict_keys(sc))
        return self


# ── Wealth Library response models (Phase 2) ─────────────────────
#
# These schemas form the API boundary between the database
# (`wealth_library_index` + `wealth_library_pins`) and the Svelte
# Library shell. They follow the smart-backend / polished-frontend
# rule from CLAUDE.md and the spec §4.8:
#
#   * Internal columns that the UI never needs are excluded — most
#     notably ``storage_path`` (only the detail and bundle endpoints
#     emit it) and the source-table FKs (``source_table`` /
#     ``source_id``) are kept on the detail view but never on listings.
#   * Free-form ``metadata`` is sanitised through ``sanitize_report_json``
#     so any quant jargon embedded in source-specific fields gets
#     translated before reaching the client.
#   * Field names are intentionally human — ``confidence`` instead of
#     ``confidence_score``, ``language`` instead of ``pdf_language``.
#
# All models are immutable in the API direction (frozen=True) so the
# router cannot accidentally mutate them after construction.


class _LibraryBaseModel(BaseModel):
    """Common config for Library response models — frozen, ORM-compatible."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


LibraryNodeKind = Literal["folder", "file"]
LibraryPinType = Literal["pinned", "starred", "recent"]


class LibraryNode(_LibraryBaseModel):
    """Discriminated union element of a Library tree.

    A node is either a *folder* (an aggregation of children grouped by
    a path segment) or a *file* (a single ``wealth_library_index`` row
    rendered as an openable document).

    Folder nodes carry a ``path`` (the materialised ``folder_path``
    array joined into a URL-safe string) and a child count; file nodes
    carry the index id, kind, status and the timestamps the UI needs
    to sort and badge them.
    """

    node_type: LibraryNodeKind
    path: str = Field(
        ...,
        description=(
            "URL-safe joined folder path. For files, the path of the "
            "containing folder; for folders, the folder itself."
        ),
    )
    label: str

    # Folder-only
    child_count: int | None = None
    last_updated_at: datetime | None = None

    # File-only — populated when node_type == 'file'
    id: UUID | None = None
    kind: str | None = None
    title: str | None = None
    subtitle: str | None = None
    status: str | None = None
    language: str | None = None
    version: int | None = None
    is_current: bool | None = None
    entity_kind: str | None = None
    entity_label: str | None = None
    entity_slug: str | None = None
    confidence: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LibraryTree(_LibraryBaseModel):
    """Tree of L1 + L2 folders for the landing render.

    Pages of children below L2 are fetched lazily via
    ``GET /library/folders/{path}/children``.
    """

    roots: list[LibraryNode]
    generated_at: datetime


class LibraryNodePage(_LibraryBaseModel):
    """Cursor-paginated page of nodes inside a folder."""

    items: list[LibraryNode]
    next_cursor: str | None = None
    total_estimate: int | None = None


class LibrarySearchResult(_LibraryBaseModel):
    """Search hit list — same shape as the folder children for symmetry."""

    items: list[LibraryNode]
    next_cursor: str | None = None
    total_estimate: int | None = None
    query: str | None = None


class LibraryPin(_LibraryBaseModel):
    """A single pin row exposed to the client.

    The library_index_id is the navigation target; ``library_path``
    and ``label`` are denormalised so the UI can render the pin badge
    without a second round-trip.
    """

    id: UUID
    pin_type: LibraryPinType
    library_index_id: UUID
    library_path: str
    label: str
    kind: str | None = None
    created_at: datetime
    last_accessed_at: datetime
    position: int | None = None


class LibraryPinsResponse(_LibraryBaseModel):
    """Three pin lists in a single payload — pinned / starred / recent."""

    pinned: list[LibraryPin]
    starred: list[LibraryPin]
    recent: list[LibraryPin]


class LibraryDocumentDetail(_LibraryBaseModel):
    """Full detail view of a Library entry.

    Returned by ``GET /library/documents/{id}``. ``storage_path`` is
    intentionally exposed here (and only here) so the preview pane can
    request a presigned download URL via the existing reader endpoints.
    Free-form ``metadata`` is sanitised by ``sanitize_report_json``
    before construction.
    """

    id: UUID
    source_table: str
    source_id: UUID
    kind: str
    title: str
    subtitle: str | None = None
    status: str
    language: str | None = None
    version: int | None = None
    is_current: bool
    entity_kind: str | None = None
    entity_id: UUID | None = None
    entity_slug: str | None = None
    entity_label: str | None = None
    folder_path: list[str]
    author_id: str | None = None
    approver_id: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    confidence: float | None = None
    decision_anchor: str | None = None
    storage_path: str | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _sanitize_metadata(self) -> "LibraryDocumentDetail":
        meta = self.metadata
        if isinstance(meta, dict):
            object.__setattr__(self, "metadata", sanitize_report_json(meta))
        return self


class LibraryBundleAccepted(_LibraryBaseModel):
    """202 response from ``POST /library/bundle``."""

    bundle_id: UUID
    job_id: str
    sse_channel: str
    item_count: int


class LibraryPinCreate(BaseModel):
    """Request body for ``POST /library/pins``."""

    library_index_id: UUID
    pin_type: LibraryPinType = "pinned"
    position: int | None = None
