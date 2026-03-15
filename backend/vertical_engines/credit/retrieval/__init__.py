"""IC-Grade Retrieval Governance Engine — Underwriting Standard v2.

Public API:
    gather_chapter_evidence()       — per-chapter retrieval pipeline
    build_ic_corpus()               — IC-grade corpus assembly
    enforce_evidence_saturation()   — per-chapter minimum thresholds
    build_retrieval_audit()         — structured audit artifact
    retrieve_market_benchmarks()    — market benchmark data from market-data-index
    build_chapter_query_map()       — chapter-specialized query expansion
    ic_coverage_rerank()            — coverage-governed reranking
    validate_provenance()           — chunk provenance integrity gate

Error contract: never-raises (orchestration engine called during deep review).
Returns result dicts with warnings/status fields on failure.
Exception classes (EvidenceGapError, RetrievalScopeError, ProvenanceError) are
kept in models.py for backward compat during Wave 1; deprecate in Wave 2.
"""
from vertical_engines.credit.retrieval.benchmarks import retrieve_market_benchmarks
from vertical_engines.credit.retrieval.corpus import (
    build_ic_corpus,
    ic_coverage_rerank,
)
from vertical_engines.credit.retrieval.evidence import (
    gather_chapter_evidence,
    validate_provenance,
)
from vertical_engines.credit.retrieval.models import (
    CHAPTER_DOC_TYPE_FILTERS,
    RETRIEVAL_POLICY_NAME,
    ChapterEvidenceThreshold,
    EvidenceGapError,
    ProvenanceError,
    RetrievalScopeError,
)
from vertical_engines.credit.retrieval.query_map import build_chapter_query_map
from vertical_engines.credit.retrieval.saturation import (
    build_retrieval_audit,
    enforce_evidence_saturation,
)

__all__ = [
    "gather_chapter_evidence",
    "build_ic_corpus",
    "enforce_evidence_saturation",
    "build_retrieval_audit",
    "retrieve_market_benchmarks",
    "build_chapter_query_map",
    "ic_coverage_rerank",
    "validate_provenance",
    # Models / exceptions (backward compat — Wave 1)
    "CHAPTER_DOC_TYPE_FILTERS",
    "ChapterEvidenceThreshold",
    "EvidenceGapError",
    "ProvenanceError",
    "RETRIEVAL_POLICY_NAME",
    "RetrievalScopeError",
]
