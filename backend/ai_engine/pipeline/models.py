"""Pipeline data contracts.

Frozen dataclasses used across all pipeline stages.  Designed to be safe
for crossing async / thread boundaries (per CLAUDE.md rules).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

# ── Canonical type sets ──────────────────────────────────────────────
# Single source of truth — all classifier layers + validation gates
# import from here.

CANONICAL_DOC_TYPES: frozenset[str] = frozenset({
    "legal_lpa", "legal_side_letter", "legal_subscription", "legal_agreement",
    "legal_amendment", "legal_poa", "legal_term_sheet", "legal_credit_agreement",
    "legal_security", "legal_intercreditor",
    "financial_statements", "financial_nav", "financial_projections",
    "regulatory_cima", "regulatory_compliance", "regulatory_qdd",
    "fund_structure", "fund_profile", "fund_presentation", "fund_policy",
    "strategy_profile", "capital_raising", "credit_policy",
    "operational_service", "operational_insurance", "operational_monitoring",
    "investment_memo", "risk_assessment", "org_chart", "attachment", "other",
})

CANONICAL_VEHICLE_TYPES: frozenset[str] = frozenset({
    "standalone_fund", "fund_of_funds", "feeder_master",
    "direct_investment", "spv", "other",
})

# doc_types where vehicle_type is not applicable — force "other".
NO_VEHICLE_DOC_TYPES: frozenset[str] = frozenset({
    "strategy_profile", "org_chart", "attachment",
    "credit_policy", "operational_service", "operational_insurance",
    "risk_assessment", "regulatory_cima", "regulatory_compliance",
    "regulatory_qdd", "other", "legal_side_letter", "capital_raising",
    "fund_structure", "fund_profile", "fund_policy", "legal_agreement",
})


# ── Result types ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PipelineStageResult:
    """Result from a single pipeline stage or validation gate.

    ``data`` is ``None`` on failure — callers MUST check ``success`` first.
    """
    stage: str                    # "ocr", "classification", "chunking", "extraction", "embedding"
    success: bool
    data: Any                     # Stage output payload
    metrics: dict[str, Any]       # char_count, chunk_count, confidence, duration_ms, etc.
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HybridClassificationResult:
    """Classification output from the hybrid classifier.

    Named ``HybridClassificationResult`` to avoid collision with the existing
    ``document_intelligence.ClassificationResult`` (which uses int confidence 0-100).
    """
    doc_type: str
    vehicle_type: str
    confidence: float             # 0.0–1.0 unified scale
    layer: int                    # 1=rules, 2=cosine_similarity, 3=LLM
    model_name: str               # e.g. "rules", "embedding-v2", "gpt-4.1-mini"


@dataclass(frozen=True)
class IngestRequest:
    """Frozen request envelope for the unified pipeline.

    SECURITY: ``org_id`` MUST be derived from ``actor.organization_id``
    (JWT claim), NEVER from request body.  Use factory helpers
    ``for_ui_upload()`` / ``for_batch()`` to enforce this binding.

    The ``fund_context`` dict carries entity-bootstrap aliases that
    ``prepare_pdfs_full.py`` stored as global mutable state
    (``_CONTEXT_DEAL_NAME``, ``_FUND_ALIASES``).  Populated by the batch
    wrapper (``extraction_orchestrator.py``) after running entity
    bootstrap, or from the fund record in the DB for UI uploads.
    If ``None``, metadata extraction proceeds without alias enrichment
    (degraded but functional).
    """
    source: Literal["ui", "batch", "api"]
    org_id: UUID                  # FROM JWT actor.organization_id ONLY
    vertical: str                 # "credit" | "wealth"
    document_id: UUID
    blob_uri: str
    filename: str
    fund_id: UUID | None = None
    deal_id: UUID | None = None
    version_id: UUID | None = None  # For SSE channel (UI source only)
    fund_context: dict | None = None

    def __post_init__(self) -> None:
        if self.vertical not in {"credit", "wealth"}:
            raise ValueError(f"Invalid vertical: {self.vertical!r}")
        if ".." in self.blob_uri or self.blob_uri.startswith("/"):
            raise ValueError(f"Invalid blob_uri: path traversal detected in {self.blob_uri!r}")
