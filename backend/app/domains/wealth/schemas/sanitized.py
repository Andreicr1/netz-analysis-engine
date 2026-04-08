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
    RegimeHierarchyRead    — inherits SanitizedRegimeHierarchyMixin
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
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SanitizedRegimeHierarchyMixin(BaseModel):
    """For schemas with `global_regime` + `regional_regimes: dict[str, str]`.

    Used by `RegimeHierarchyRead` where the full regime tree is
    exposed. Both levels are translated.
    """

    @model_validator(mode="after")
    def _sanitize_regime_hierarchy(self) -> "SanitizedRegimeHierarchyMixin":
        gr = getattr(self, "global_regime", None)
        if isinstance(gr, str):
            object.__setattr__(self, "global_regime", humanize_regime(gr))
        rr = getattr(self, "regional_regimes", None)
        if isinstance(rr, dict):
            object.__setattr__(
                self,
                "regional_regimes",
                {k: humanize_regime(v) if isinstance(v, str) else v for k, v in rr.items()},
            )
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
