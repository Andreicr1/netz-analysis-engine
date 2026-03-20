"""Retrieval governance models and constants (LEAF — zero sibling imports).

All data structures and constants used across the retrieval package.
This module has NO imports from sibling modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Evidence Saturation Result ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SaturationResult:
    """Evidence saturation assessment. Replaces EvidenceGapError exception.

    Field names align with enforce_evidence_saturation() dict keys.
    Callers check `all_saturated` instead of catching exceptions.
    Follows PipelineStageResult pattern (frozen dataclass with to_dict).
    """

    all_saturated: bool
    coverage_score: float
    gaps: list[dict[str, Any]] = field(default_factory=list)
    missing_document_classes: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """API boundary serialization (Wave 1 convention #3)."""
        return {
            "all_saturated": self.all_saturated,
            "coverage_score": self.coverage_score,
            "gaps": self.gaps,
            "missing_document_classes": self.missing_document_classes,
            "reason": self.reason,
        }


# ── IC-Grade Coverage Constants ────────────────────────────────────

DEPTH_FREE: int = 4
"""Number of chunks from the same document allowed before coverage
bonus kicks in. Per underwriting-standard.md Stage 5."""

LAMBDA: float = 0.25
"""Marginal coverage bonus coefficient. Governs how aggressively
under-represented documents are boosted after DEPTH_FREE is exceeded."""

RETRIEVAL_POLICY_NAME: str = "IC_GRADE_V2"
"""Official policy identifier for audit artifacts."""

# ── Search Tiers (top, k) ─────────────────────────────────────────

DEFAULT_SEARCH_TIER: tuple[int, int] = (100, 150)
EXPANDED_SEARCH_TIER: tuple[int, int] = (200, 300)

# ── Total Corpus Budget ────────────────────────────────────────────

TOTAL_BUDGET_CHARS: int = 300_000
"""Hard character limit for the global corpus."""

# ── Critical Document Types (guaranteed inclusion) ─────────────────

CRITICAL_DOC_TYPES: frozenset[str] = frozenset({
    "legal_side_letter",
    "side_letter",
    "fund_structure",
    "legal_lpa",
    "legal_agreement",
})
"""Document types that are ALWAYS included in the IC corpus regardless
of reranker score."""

# ── Filter fallback threshold ──────────────────────────────────────

FILTER_FALLBACK_THRESHOLD: int = 6

# Human-readable mode labels for audit artifacts
CHAPTER_RETRIEVAL_MODE: dict[str, str] = {
    "ch01_exec":              "PIPELINE_SCREENING",
    "ch02_macro":             "PIPELINE_SCREENING",
    "ch04_sponsor":           "PIPELINE_SCREENING",
    "ch05_legal":             "LEGAL_PACK",
    "ch06_terms":             "LEGAL_PACK",
    "ch07_capital":           "UNDERWRITING",
    "ch08_returns":           "UNDERWRITING",
    "ch09_downside":          "UNDERWRITING",
    "ch10_covenants":         "UNDERWRITING",
    "ch03_exit":              "IC_GRADE",
    "ch11_risks":             "IC_GRADE",
    "ch12_peers":             "IC_GRADE",
    "ch13_recommendation":    "IC_GRADE",
    "ch14_governance_stress": "GOVERNANCE_STRESS",
}

# ── Evidence Saturation Thresholds ─────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChapterEvidenceThreshold:
    """Minimum evidence requirements for an IC-grade chapter."""

    min_chunks: int
    min_docs: int
    required_doc_types: frozenset[str] = frozenset()

    def is_satisfied(
        self,
        chunk_count: int,
        doc_count: int,
        doc_types_present: set[str],
    ) -> bool:
        if chunk_count < self.min_chunks:
            return False
        if doc_count < self.min_docs:
            return False
        for rdt in self.required_doc_types:
            if rdt not in doc_types_present:
                return False
        return True


CHAPTER_EVIDENCE_THRESHOLDS: dict[str, ChapterEvidenceThreshold] = {
    "ch01_exec":              ChapterEvidenceThreshold(min_chunks=8,  min_docs=3),
    "ch02_macro":             ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch03_exit":              ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch04_sponsor":           ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch05_legal":             ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch06_terms":             ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch07_capital":           ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch08_returns":           ChapterEvidenceThreshold(min_chunks=8,  min_docs=3),
    "ch09_downside":          ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch10_covenants":         ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch11_risks":             ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch12_peers":             ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch13_recommendation":    ChapterEvidenceThreshold(min_chunks=0,  min_docs=0),
    "ch14_governance_stress": ChapterEvidenceThreshold(min_chunks=10, min_docs=4),
}

# ── Coverage-status labels ─────────────────────────────────────────

COVERAGE_SATURATED  = "SATURATED"
COVERAGE_PARTIAL    = "PARTIAL"
COVERAGE_MISSING    = "MISSING_EVIDENCE"
COVERAGE_CONTESTED  = "EVIDENCE_CONTESTED"

# ── Provenance validation fields ───────────────────────────────────

REQUIRED_PROVENANCE_FIELDS = (
    "blob_name", "content", "chunk_index",
)

DESIRED_PROVENANCE_FIELDS = (
    "doc_type", "authority", "page_start", "page_end",
    "container_name",
)

# ── Market benchmark queries ───────────────────────────────────────

CHAPTER_MARKET_DATA_QUERIES: dict[str, list[str]] = {
    "ch08_returns": [
        "private credit fund IRR net return quarterly performance track record",
        "direct lending yield spread senior secured net IRR benchmark",
        "private credit median IRR top quartile decile vintage year performance",
        "private debt fund return distribution hurdle rate preferred return",
    ],
    "ch12_peers": [
        "private credit peer comparison benchmark fund strategy size AUM",
        "direct lending fund LTV leverage target yield peer universe",
        "private debt comparable fund gate lock-up redemption terms market standard",
        "private credit market positioning relative value quartile peer group",
    ],
    "ch09_downside": [
        "private credit default rate stress scenario historical loss given default",
        "private debt downside recovery rate stress period 2008 2020 performance",
        "senior secured loan default loss stress test market benchmark",
    ],
    "ch03_exit": [
        "private credit exit environment secondary market liquidity benchmark",
        "private debt redemption secondary transaction pricing market data",
        "private credit fund IRR exit multiple realized return distribution vintage",
        "private debt fund liquidity window redemption gate secondary pricing NAV discount",
        "private credit open-ended fund exit environment secondary market conditions 2024 2025",
    ],
}
