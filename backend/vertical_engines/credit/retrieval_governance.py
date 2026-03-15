"""IC-Grade Retrieval Governance Engine — Underwriting Standard v2.

Implements the Netz Retrieval Governance Framework as defined in
``docs/architecture/underwriting-standard.md``.

Design principles:
    1. Semantic reranker score is the PRIMARY ranking authority.
    2. Vector score is used ONLY for candidate generation.
    3. No heuristic may override semantic relevance.
    4. Coverage acts as a CORRECTIVE mechanism, never dominant.
    5. Chapter-specialized retrieval — no global generic queries.
    6. Evidence saturation enforcement per chapter.
    7. Full provenance on every chunk — discard if missing.
    8. Structured audit artifact for compliance.

Modules:
    - ``CHAPTER_QUERY_MAP``         — chapter-specialized query expansion
    - ``CHAPTER_DOC_TYPE_FILTERS``  — per-chapter doc_type scoping (v2)
    - ``ic_coverage_rerank()``      — IC-grade coverage-governed reranking
    - ``validate_provenance()``     — chunk provenance integrity gate
    - ``enforce_evidence_saturation()`` — per-chapter minimum thresholds
    - ``gather_chapter_evidence()`` — per-chapter retrieval pipeline
    - ``build_ic_corpus()``         — IC-grade corpus assembly
    - ``build_retrieval_audit()``   — structured audit artifact

Changelog v2:
    - Added ``CHAPTER_DOC_TYPE_FILTERS`` — maps each chapter to the
      appropriate doc_type filter expression, implementing the three
      institutional retrieval modes:
        • Pipeline Screening Mode  (ch01, ch02, ch04)
        • Legal Pack Mode          (ch05, ch06)
        • Underwriting Mode        (ch07, ch08, ch09, ch10)
      Chapters ch03, ch12, ch13 use IC Grade Mode (no filter — full corpus).
    - ``gather_chapter_evidence()`` accepts and propagates doc_type_filter
      to ``searcher.search_institutional_hybrid()``.
    - ``build_retrieval_audit()`` records the active filter per chapter.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Retrieval Governance Exceptions ────────────────────────────────

class EvidenceGapError(RuntimeError):
    """Chapter evidence saturation threshold not met.

    Raised when a chapter cannot assemble enough evidence to meet
    institutional underwriting minimums.
    """


class RetrievalScopeError(ValueError):
    """Mandatory institutional scoping constraint violated.

    Raised if fund_id is missing — global retrieval is forbidden.
    """


class ProvenanceError(ValueError):
    """Chunk provenance is incomplete — chunk must be discarded."""


# ── IC-Grade Coverage Constants ────────────────────────────────────

DEPTH_FREE: int = 4
"""Number of chunks from the same document allowed before coverage
bonus kicks in. Per underwriting-standard.md Stage 5."""

LAMBDA: float = 0.25
"""Marginal coverage bonus coefficient. Governs how aggressively
under-represented documents are boosted after DEPTH_FREE is exceeded."""

RETRIEVAL_POLICY_NAME: str = "IC_GRADE_V2"
"""Official policy identifier for audit artifacts."""


def _shared_auxiliary_fund_ids() -> set[str]:
    """Return configured shared auxiliary scope ids allowed across deals.

    These are global/shared evidence domains such as fund constitution,
    regulatory libraries, and service-provider materials. They are not
    deal-specific and must survive the last-line contamination filter.
    """
    raw = getattr(settings, "SEARCH_AUXILIARY_INDEXES", None) or ""
    allowed: set[str] = set()
    for entry in raw.split(","):
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) >= 2 and parts[1]:
            allowed.add(parts[1].lower())
    return allowed


# ── Chapter Search Tiers (top, k) ─────────────────────────────────
# Critical chapters (legal, terms, capital structure, governance stress)
# get full retrieval depth.  All other chapters use a reduced tier to
# avoid over-fetching from Azure AI Search while preserving recall
# where it matters most for IC-grade underwriting.

_CHAPTER_SEARCH_TIERS: dict[str, tuple[int, int]] = {
    "ch05_legal":             (200, 300),
    "ch06_terms":             (200, 300),
    "ch07_capital":           (200, 300),
    "ch14_governance_stress": (200, 300),
}
_DEFAULT_SEARCH_TIER: tuple[int, int] = (80, 150)


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
of reranker score.  These contain governance-critical information
(e.g. fund-of-funds structure, side letter arrangements) that may have
low semantic scores against standard queries but carry material weight
for investment committee decisions.

Rationale: a Side Letter revealing that the fund operates through an
intermediary vehicle (e.g. Netz → NG Credit Fund → NELI US LP / II LP)
is structurally decisive for the IC memo, even though its reranker
score (1.87) placed it at position #37/62 in ch05_legal, outside the
top-65 global budget cutoff.  Forcing inclusion ensures such documents
are never silently dropped."""


# ── Chapter Query Map (Stage 1 — Specialized Multi-Query) ──────────

def build_chapter_query_map(deal_name: str) -> dict[str, list[str]]:
    """Build chapter-specialized query expansion per IC-Grade standard.

    Each chapter receives its own query set. Generic global queries are
    prohibited. Every query includes the deal name for scope anchoring.

    Returns
    -------
    dict[str, list[str]]
        Mapping from chapter_key → list of specialized retrieval queries.

    """
    dn = deal_name  # shorthand

    return {
        "ch01_exec": [
            f"{dn} investment opportunity fund structure overview executive summary",
            f"{dn} fund profile strategy asset class target return",
            f"{dn} key investment highlights risk reward summary",
            "fund constitution governance board resolution investment policy overview",
            f"{dn} side letter agreement fund vehicle capital allocation structure",
        ],
        "ch02_macro": [
            f"{dn} market context private credit macro environment",
            f"{dn} industry sector competitive landscape market positioning",
            f"{dn} interest rate environment credit cycle outlook",
            "CIMA regulatory framework Cayman Islands mutual funds obligations reporting",
        ],
        "ch03_exit": [
            f"{dn} exit environment liquidity redemption secondary market",
            f"{dn} macro regime stress scenario economic downturn",
            f"{dn} interest rate sensitivity duration portfolio maturity",
        ],
        "ch04_sponsor": [
            f"{dn} sponsor management team track record key person biography",
            f"{dn} organizational chart governance board committee oversight",
            f"{dn} sponsor AUM assets under management investment history",
            "service provider administrator custodian auditor counterparty arrangement",
            "fund constitution board composition quorum amendment delegated authority",
            "CIMA regulatory responsible party compliance officer obligations",
        ],
        "ch05_legal": [
            f"{dn} LPA subscription agreement side letter legal terms",
            f"{dn} fund constitution prospectus offering memorandum",
            f"{dn} jurisdiction enforcement litigation regulatory filings",
            "offering memorandum share class amendment threshold quorum reserved matters",
            "board approved liberality policy override concentration exception waiver",
            "CIMA filing obligations AML KYC compliance penalties non-compliance",
        ],
        "ch06_terms": [
            f"{dn} investment terms fees management performance carried interest",
            f"{dn} covenants restrictions concentration limits leverage cap",
            f"{dn} waterfall distributions hurdle rate clawback",
            "offering memorandum fee schedule hurdle rate lock-up redemption terms",
            "service provider fee arrangement administrator custodian auditor costs",
        ],
        "ch07_capital": [
            f"{dn} capital structure leverage borrowing facility senior subordinated",
            f"{dn} financial statements balance sheet NAV AUM",
            f"{dn} capital raising presentation investor commitments",
            "fund constitution capital call leverage limit borrowing policy",
        ],
        "ch08_returns": [
            f"{dn} financial statements returns NAV performance AUM audited",
            f"{dn} historical returns net IRR MOIC yield track record",
            f"{dn} cash flow distributions income revenue EBITDA DSCR",
            "offering memorandum hurdle rate preferred return waterfall carried interest performance allocation",
        ],
        "ch09_downside": [
            f"{dn} risk assessment credit risk concentration default covenant",
            f"{dn} downside scenario stress test loss given default",
            f"{dn} worst case scenario portfolio deterioration recovery",
            "CIMA regulatory enforcement licence suspension wind-down penalty",
            "service provider termination resignation transition contingency",
            "offering memorandum lock-up redemption gate suspension side pocket",
        ],
        "ch10_covenants": [
            f"{dn} covenant compliance monitoring breach waiver amendment",
            f"{dn} credit policy lending standards limits covenants underwriting",
            f"{dn} financial covenants DSCR leverage ratio interest coverage",
            "investment policy concentration limit single-name sector geography board approved exception",
            "CIMA regulatory obligation audit delivery NAV reporting filing deadline",
        ],
        "ch11_risks": [
            f"{dn} risk assessment operational risk key person dependency",
            f"{dn} compliance AML KYC regulatory policies procedures anti-money",
            f"{dn} IT policy disaster recovery business continuity cybersecurity",
            "CIMA filing deadline penalty regulatory change obligation revision",
            "service provider termination liability cap jurisdiction mismatch concentration",
            "fund constitution governance quorum amendment conflict of interest related party",
        ],
        "ch12_peers": [
            f"{dn} peer comparison benchmark private credit market",
            f"{dn} competitive analysis similar funds strategy positioning",
            f"{dn} due diligence questionnaire DDQ ANBIMA operational risk",
        ],
        "ch13_recommendation": [
            f"{dn} employee handbook HR policies code of ethics professional conduct",
            f"{dn} code of ethics professional conduct business integrity",
        ],
        "ch14_governance_stress": [
            f"{dn} suspension redemption gate NAV determination valuation sole discretion board",
            f"{dn} investment manager removal cause without cause notice period transition successor",
            f"{dn} board directors composition removal appointment regulatory override adverse event",
            f"{dn} side letter enforceability conflict MFN priority queue adverse event investor rights",
            f"{dn} credit policy concentration limits borrower breach disclosure obligation single name",
            "CIMA intervention powers director substitution regulatory enforcement fund wind-down",
            f"{dn} management fee performance fee suspension NAV decline reset high water mark",
            f"{dn} liquidity gate threshold pro-rata mechanics suspension trigger condition cash reserve",
            f"{dn} financial statements NAV leverage yield default stress scenario impairment recovery",
            f"{dn} auditor appointment independence related party transactions conflict of interest",
        ],
    }


# ── Chapter Doc-Type Filters (v2 — Retrieval Modes) ────────────────

# Each chapter is assigned to one of four institutional retrieval modes:
#
#   Pipeline Screening Mode
#     Purpose : broad overview of the opportunity — fund decks, strategy docs
#     Chapters: ch01_exec, ch02_macro, ch04_sponsor
#     Filter  : fund_presentation | strategy_profile | fund_profile | org_chart
#
#   Legal Pack Mode
#     Purpose : legal and structural analysis — governing documents
#     Chapters: ch05_legal, ch06_terms
#     Filter  : legal_lpa | legal_side_letter | legal_agreement |
#               legal_amendment | legal_subscription | legal_term_sheet |
#               fund_presentation (terms often in decks too)
#
#   Underwriting Mode
#     Purpose : credit and financial analysis — hard data only
#     Chapters: ch07_capital, ch08_returns, ch09_downside, ch10_covenants
#     Filter  : credit_policy | financial_statements | financial_nav |
#               fund_presentation (performance data in decks)
#
#   IC Grade Mode (no filter — full corpus)
#     Purpose : macro, exit, peers, final recommendation — needs everything
#     Chapters: ch03_exit, ch11_risks, ch12_peers, ch13_recommendation
#     Filter  : None
#
# Rationale: restricting retrieval to relevant doc_types eliminates noise
# from unrelated document classes, improving precision without sacrificing
# recall for chapters where the evidence naturally concentrates in known types.

# FALLBACK_THRESHOLD: if filtered retrieval returns fewer unique chunks than
# this value, gather_chapter_evidence automatically re-runs without the
# doc_type filter (IC_GRADE mode) and merges the results.
FILTER_FALLBACK_THRESHOLD: int = 6

# ALL_DOC_TYPES: union of every doc_type known to exist in the v4 index.
# Used as the broadest possible filter — equivalent to no filter but explicit.
# Attachment (161 chunks) is included everywhere — it contains capital raising
# presentations, financial exhibits, and annexes with real investment content.
# ── doc_type OData filter atoms — aligned with CU analyzer enum (31 values) ──
_ATTACHMENT  = "doc_type eq 'attachment'"
_REG_COMPL   = "doc_type eq 'regulatory_compliance'"
_REG_CIMA    = "doc_type eq 'regulatory_cima'"
_REG_QDD     = "doc_type eq 'regulatory_qdd'"
_FUND_STRUCT = "doc_type eq 'fund_structure'"
_FUND_PROF   = "doc_type eq 'fund_profile'"
_FUND_PRES   = "doc_type eq 'fund_presentation'"
_FUND_POLICY = "doc_type eq 'fund_policy'"
_STRATEGY    = "doc_type eq 'strategy_profile'"
_CAP_RAISING = "doc_type eq 'capital_raising'"
_FIN_STMT    = "doc_type eq 'financial_statements'"
_FIN_NAV     = "doc_type eq 'financial_nav'"
_FIN_PROJ    = "doc_type eq 'financial_projections'"
_CREDIT_POL  = "doc_type eq 'credit_policy'"
_LPA         = "doc_type eq 'legal_lpa'"
_SIDE_LTR    = "doc_type eq 'legal_side_letter'"
_AGREEMENT   = "doc_type eq 'legal_agreement'"
_AMENDMENT   = "doc_type eq 'legal_amendment'"
_SUBSCRIPT   = "doc_type eq 'legal_subscription'"
_TERM_SHEET  = "doc_type eq 'legal_term_sheet'"
_CREDIT_AGR  = "doc_type eq 'legal_credit_agreement'"
_SECURITY    = "doc_type eq 'legal_security'"
_INTERCRED   = "doc_type eq 'legal_intercreditor'"
_POA         = "doc_type eq 'legal_poa'"
_ORG_CHART   = "doc_type eq 'org_chart'"
_OP_SERVICE  = "doc_type eq 'operational_service'"
_OP_INSUR    = "doc_type eq 'operational_insurance'"
_OP_MONITOR  = "doc_type eq 'operational_monitoring'"
_INV_MEMO    = "doc_type eq 'investment_memo'"
_RISK_ASSESS = "doc_type eq 'risk_assessment'"


def _f(*parts: str) -> str:
    """Join doc_type filter parts with OR."""
    return " or ".join(parts)


CHAPTER_DOC_TYPE_FILTERS: dict[str, str | None] = {

    # ── Pipeline Screening Mode ─────────────────────────────────────
    # Aligned with _CHAPTER_DOC_AFFINITY — includes every canonical type
    # that carries evidence for each chapter.
    "ch01_exec": _f(
        _LPA, _SIDE_LTR, _TERM_SHEET,
        _FUND_STRUCT, _FUND_PROF, _FUND_PRES, _FUND_POLICY,
        _STRATEGY, _CAP_RAISING, _INV_MEMO, _ATTACHMENT,
    ),
    "ch02_macro": _f(
        _FUND_PRES, _STRATEGY, _FUND_PROF, _FUND_STRUCT,
        _CAP_RAISING, _REG_CIMA, _REG_COMPL, _ATTACHMENT,
    ),
    "ch04_sponsor": _f(
        _FUND_PRES, _STRATEGY, _FUND_PROF, _FUND_STRUCT,
        _ORG_CHART, _CAP_RAISING, _FUND_POLICY,
        _LPA, _SIDE_LTR, _AGREEMENT, _SUBSCRIPT, _SECURITY,
        _REG_COMPL, _OP_SERVICE, _OP_MONITOR,
        _RISK_ASSESS, _ATTACHMENT,
    ),

    # ── Legal Pack Mode ─────────────────────────────────────────────
    # Now includes credit_agreement, security, intercreditor, regulatory_cima
    "ch05_legal": _f(
        _LPA, _SIDE_LTR, _AGREEMENT, _AMENDMENT,
        _SUBSCRIPT, _POA, _TERM_SHEET,
        _CREDIT_AGR, _SECURITY, _INTERCRED,
        _REG_CIMA, _ATTACHMENT,
    ),
    "ch06_terms": _f(
        _LPA, _TERM_SHEET, _AMENDMENT, _AGREEMENT,
        _CREDIT_AGR, _OP_SERVICE,
        _FUND_PRES, _STRATEGY, _ATTACHMENT,
    ),

    # ── Underwriting Mode ───────────────────────────────────────────
    # Now includes financial_projections, legal refs, and operational types
    "ch07_capital": _f(
        _FIN_STMT, _FIN_NAV, _FIN_PROJ, _TERM_SHEET, _LPA,
        _FUND_PRES, _STRATEGY, _FUND_PROF,
        _CAP_RAISING, _ATTACHMENT,
    ),
    "ch08_returns": _f(
        _FIN_STMT, _FIN_NAV, _FIN_PROJ, _TERM_SHEET, _LPA,
        _STRATEGY, _FUND_PRES, _FUND_PROF,
        _CAP_RAISING, _ATTACHMENT,
    ),
    "ch09_downside": _f(
        _RISK_ASSESS, _CREDIT_POL, _FIN_STMT, _FIN_NAV,
        _REG_CIMA, _REG_COMPL,
        _OP_SERVICE, _OP_MONITOR, _LPA,
        _FUND_PRES, _ATTACHMENT,
    ),
    "ch10_covenants": _f(
        _CREDIT_POL, _CREDIT_AGR, _LPA, _AGREEMENT, _AMENDMENT,
        _REG_CIMA, _REG_COMPL, _REG_QDD,
        _OP_MONITOR, _ATTACHMENT,
    ),

    # ── Governance Stress Mode (Legal Pack + Underwriting combined) ─────
    # Full legal, credit, regulatory, and financial corpus for adverse-event
    # and downside stress analysis
    "ch14_governance_stress": _f(
        _LPA, _SIDE_LTR, _AGREEMENT, _AMENDMENT, _CREDIT_AGR, _TERM_SHEET,
        _CREDIT_POL, _FIN_STMT, _FIN_NAV,
        _REG_CIMA, _REG_COMPL,
        _RISK_ASSESS, _FUND_POLICY, _ORG_CHART, _ATTACHMENT,
    ),

    # ── IC Grade Mode (full corpus — no doc_type restriction) ───────
    # These chapters already search everything; None = no OData filter at all
    "ch03_exit":           None,
    "ch11_risks":          None,
    "ch12_peers":          None,
    "ch13_recommendation": None,
}

# Human-readable mode labels for audit artifacts
CHAPTER_RETRIEVAL_MODE: dict[str, str] = {
    "ch01_exec":           "PIPELINE_SCREENING",
    "ch02_macro":          "PIPELINE_SCREENING",
    "ch04_sponsor":        "PIPELINE_SCREENING",
    "ch05_legal":          "LEGAL_PACK",
    "ch06_terms":          "LEGAL_PACK",
    "ch07_capital":        "UNDERWRITING",
    "ch08_returns":        "UNDERWRITING",
    "ch09_downside":       "UNDERWRITING",
    "ch10_covenants":      "UNDERWRITING",
    "ch03_exit":           "IC_GRADE",
    "ch11_risks":          "IC_GRADE",
    "ch12_peers":          "IC_GRADE",
    "ch13_recommendation": "IC_GRADE",
    "ch14_governance_stress": "GOVERNANCE_STRESS",
}


# ── Evidence Saturation Thresholds ─────────────────────────────────

@dataclass(frozen=True)
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
    "ch01_exec":           ChapterEvidenceThreshold(min_chunks=8,  min_docs=3),
    "ch02_macro":          ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch03_exit":           ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch04_sponsor":        ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch05_legal":          ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch06_terms":          ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch07_capital":        ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch08_returns":        ChapterEvidenceThreshold(min_chunks=8,  min_docs=3),
    "ch09_downside":       ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch10_covenants":      ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch11_risks":          ChapterEvidenceThreshold(min_chunks=6,  min_docs=2),
    "ch12_peers":          ChapterEvidenceThreshold(min_chunks=4,  min_docs=2),
    "ch13_recommendation": ChapterEvidenceThreshold(min_chunks=0,  min_docs=0),
    "ch14_governance_stress": ChapterEvidenceThreshold(min_chunks=10, min_docs=4),
}

# ── Coverage-status labels ─────────────────────────────────────────

COVERAGE_SATURATED = "SATURATED"
COVERAGE_PARTIAL   = "PARTIAL"
COVERAGE_MISSING   = "MISSING_EVIDENCE"


# ── Provenance Validation (Stage 5 — chunk integrity) ──────────────

_REQUIRED_PROVENANCE_FIELDS = (
    "blob_name", "content", "chunk_index",
)

_DESIRED_PROVENANCE_FIELDS = (
    "doc_type", "authority", "page_start", "page_end",
    "container_name",
)


def validate_provenance(chunk: dict) -> bool:
    """Validate that a chunk has sufficient provenance for IC-grade use.

    Hard requirement: blob_name, content, chunk_index must be present.
    Soft requirement: doc_type, authority, page_start, page_end,
        container_name are expected but not fatal if absent.

    Returns True if chunk passes, False if it should be discarded.
    """
    for f in _REQUIRED_PROVENANCE_FIELDS:
        val = chunk.get(f)
        if val is None or (isinstance(val, str) and not val.strip()):
            logger.warning(
                "PROVENANCE_REJECTED chunk=%s missing_field=%s",
                chunk.get("chunk_id", "?"), f,
            )
            return False

    missing_soft = [f for f in _DESIRED_PROVENANCE_FIELDS if not chunk.get(f)]
    if missing_soft:
        logger.debug(
            "PROVENANCE_SOFT_MISSING chunk=%s fields=%s",
            chunk.get("chunk_id", "?"), missing_soft,
        )

    return True


# ── IC-Grade Coverage Reranking (Stage 5) ──────────────────────────

def ic_coverage_rerank(chunks: list[dict]) -> list[dict]:
    """Apply IC-Grade coverage-aware reranking.

    Policy (from underwriting-standard.md Stage 5):
        - First DEPTH_FREE chunks from any document: bonus = 0
          (pure semantic ordering preserved).
        - After DEPTH_FREE: bonus = LAMBDA / sqrt(freq - DEPTH_FREE + 1)
          (marginal correction for diversity, not dominance).

    The semantic_score (reranker_score) remains the PRIMARY authority.
    Coverage bonus is a small corrective additive term.
    """
    if not chunks:
        return chunks

    doc_counter = Counter(
        c.get("blob_name", c.get("title", "unknown")) for c in chunks
    )

    for chunk in chunks:
        blob = chunk.get("blob_name", chunk.get("title", "unknown"))
        freq = doc_counter.get(blob, 1)

        if freq <= DEPTH_FREE:
            coverage_bonus = 0.0
        else:  # override_filter=True — use caller-provided doc_type_filter
            coverage_bonus = LAMBDA / sqrt(freq - DEPTH_FREE + 1)

        semantic = chunk.get("reranker_score") or chunk.get("score") or 0.0
        chunk["_coverage_bonus"]  = round(coverage_bonus, 6)
        chunk["_semantic_score"]  = round(semantic, 6)
        chunk["_final_score"]     = round(semantic + coverage_bonus, 6)

    chunks.sort(key=lambda c: c.get("_final_score", 0.0), reverse=True)
    return chunks


# ── Per-Chapter Evidence Retrieval ─────────────────────────────────

def gather_chapter_evidence(
    *,
    chapter_key: str,
    deal_name: str,
    fund_id: str,
    deal_id: str | None = None,
    searcher: Any,  # AzureSearchChunksClient
    global_dedup: dict[str, dict] | None = None,  # kept for API compat, no longer used
    doc_type_filter: str | None = None,
    override_filter: bool = False,
    scope_mode: str = "STRICT",
) -> dict[str, Any]:
    """Retrieve evidence for a single chapter using specialized queries.

    Fires all queries in the CHAPTER_QUERY_MAP for this chapter,
    deduplicates by (blob_name, chunk_index), validates provenance,
    and returns the chapter's evidence corpus.

    Parameters
    ----------
    chapter_key : str
        e.g. "ch01_exec", "ch08_returns"
    deal_name : str
        Deal name for query anchoring.
    fund_id : str
        Mandatory fund scope.
    deal_id : str
        Deal ID for scoping.
    searcher : AzureSearchChunksClient
        Configured retrieval client.
    global_dedup : dict, optional
        Shared dedup dict across chapters.
    doc_type_filter : str | None, optional
        OData filter expression for doc_type scoping.
        Defaults to the value in CHAPTER_DOC_TYPE_FILTERS for this chapter.
        Pass None explicitly to use IC Grade Mode (full corpus).
        Pass a custom string to override.

    Returns
    -------
    dict with keys:
        "chunks"          — deduplicated, provenance-validated chunks
        "queries"         — list of queries fired
        "coverage_status" — SATURATED | PARTIAL | MISSING_EVIDENCE
        "retrieval_mode"  — PIPELINE_SCREENING | LEGAL_PACK | UNDERWRITING | IC_GRADE
        "doc_type_filter" — the OData filter string used (or None)
        "stats"           — {chunk_count, unique_docs, doc_types}

    """
    query_map = build_chapter_query_map(deal_name)
    queries   = query_map.get(chapter_key, [])

    if not queries:
        return {
            "chunks":          [],
            "queries":         [],
            "coverage_status": COVERAGE_MISSING,
            "retrieval_mode":  CHAPTER_RETRIEVAL_MODE.get(chapter_key, "IC_GRADE"),
            "doc_type_filter": None,
            "stats":           {"chunk_count": 0, "unique_docs": 0, "doc_types": []},
        }

    # Resolve doc_type_filter — use map default unless override_filter=True
    if not override_filter:
        active_filter = CHAPTER_DOC_TYPE_FILTERS.get(chapter_key)
    else:  # override_filter=True — use caller-provided doc_type_filter
        active_filter = doc_type_filter

    retrieval_mode = CHAPTER_RETRIEVAL_MODE.get(chapter_key, "IC_GRADE")

    # Chapter-local pool only — global dedup is done in build_ic_corpus.
    # Rationale: cross-chapter dedup with resolved scope caused corpus
    # collapse (37K chars) because identical dedup_keys were correctly
    # deduplicated across chapters, drastically reducing the pool.
    # Solution: each chapter builds its own full pool; build_ic_corpus
    # merges them keeping the highest-score copy of each chunk.
    chapter_hits: dict[str, dict] = {}

    _tier_top, _tier_k = _CHAPTER_SEARCH_TIERS.get(chapter_key, _DEFAULT_SEARCH_TIER)

    per_query_counts: list[int] = [0] * len(queries)

    def _execute_query(q_idx: int, query: str) -> tuple[int, list[dict]]:
        """Execute a single search query — thread-safe (no shared mutable state)."""
        hits_data: list[dict] = []
        try:
            hits = searcher.search_institutional_hybrid(
                query=query,
                fund_id=fund_id,
                deal_id=deal_id,
                top=_tier_top,
                k=_tier_k,
                doc_type_filter=active_filter,
                scope_mode=scope_mode,
            )
            for hit in hits:
                title      = hit.title or hit.blob_name or ""
                chunk_idx  = hit.chunk_index or 0
                new_score  = hit.reranker_score or hit.score or 0.0
                hits_data.append({
                    "chunk_id":            hit.chunk_id,
                    "title":               title,
                    "blob_name":           hit.blob_name or title,
                    "doc_type":            hit.doc_type or "unknown",
                    "authority":           hit.authority or "",
                    "page_start":          hit.page_start or 0,
                    "page_end":            hit.page_end or 0,
                    "chunk_index":         chunk_idx,
                    "content":             hit.content_text or "",
                    "score":               hit.score or 0.0,
                    "reranker_score":      hit.reranker_score or 0.0,
                    "_best_score":         new_score,
                    "_query_origin":       query[:80],
                    "_chapter_key":        chapter_key,
                    "_retrieval_mode":     retrieval_mode,
                    "container_name":      hit.container_name or "",
                    "retrieval_timestamp": hit.retrieval_timestamp or "",
                    "fund_id":             hit.fund_id or "",
                    "deal_id":             hit.deal_id or "",
                    "section_type":        getattr(hit, "section_type", None),
                    "vehicle_type":        getattr(hit, "vehicle_type", None),
                    "governance_critical": getattr(hit, "governance_critical", False),
                    "governance_flags":    getattr(hit, "governance_flags", []) or [],
                    "breadcrumb":          getattr(hit, "breadcrumb", None),
                })
            logger.info(
                "CHAPTER_RETRIEVAL ch=%s mode=%s q=%d/%d query='%s' "
                "hits=%d filter=%s",
                chapter_key, retrieval_mode,
                q_idx + 1, len(queries), query[:60],
                len(hits),
                f"'{active_filter[:60]}'" if active_filter else "NONE",
            )
        except Exception:
            logger.warning(
                "CHAPTER_RETRIEVAL_FAILED ch=%s q=%d query='%s'",
                chapter_key, q_idx, query[:60], exc_info=True,
            )
        return q_idx, hits_data

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_execute_query, q_idx, query)
            for q_idx, query in enumerate(queries)
        ]
        for future in futures:
            q_idx, hits_data = future.result()
            query_hit_count = 0
            for chunk_data in hits_data:
                dedup_key = f"{chunk_data['title']}::{chunk_data['chunk_index']}"
                new_score = chunk_data["_best_score"]
                existing_local = chapter_hits.get(dedup_key)
                if (existing_local is None
                        or new_score > existing_local.get("_best_score", 0.0)):
                    chapter_hits[dedup_key] = chunk_data
                    query_hit_count += 1
            per_query_counts[q_idx] = query_hit_count

    # Provenance validation
    valid_chunks = [
        c for c in chapter_hits.values()
        if validate_provenance(c)
    ]

    # ── Automatic filter broadening (v3.1 — smart per-query fallback) ──
    # If a filtered chapter returns fewer chunks than FILTER_FALLBACK_THRESHOLD,
    # re-run ONLY the underperforming queries (< 3 unique hits) without the
    # doc_type filter (IC_GRADE mode) and merge. Queries that already returned
    # sufficient results are skipped to avoid redundant search calls.
    _QUERY_FALLBACK_MIN = 3
    if active_filter is not None and len(valid_chunks) < FILTER_FALLBACK_THRESHOLD:
        queries_to_retry = [
            i for i, cnt in enumerate(per_query_counts)
            if cnt < _QUERY_FALLBACK_MIN
        ]
        logger.warning(
            "FILTER_FALLBACK_TRIGGERED ch=%s filtered_chunks=%d threshold=%d "
            "— re-running %d/%d underperforming queries without doc_type filter",
            chapter_key, len(valid_chunks), FILTER_FALLBACK_THRESHOLD,
            len(queries_to_retry), len(queries),
        )
        for q_idx in queries_to_retry:
            query = queries[q_idx]
            try:
                fallback_hits = searcher.search_institutional_hybrid(
                    query=query,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    top=_tier_top,
                    k=_tier_k,
                    doc_type_filter=None,  # IC_GRADE — no filter
                    scope_mode=scope_mode,
                )
                for hit in fallback_hits:
                    title     = hit.title or hit.blob_name or ""
                    chunk_idx = hit.chunk_index or 0
                    dedup_key = f"{title}::{chunk_idx}"
                    new_score = hit.reranker_score or hit.score or 0.0
                    if dedup_key not in chapter_hits:
                        chapter_hits[dedup_key] = {
                            "chunk_id":            hit.chunk_id,
                            "title":               title,
                            "blob_name":           hit.blob_name or title,
                            "doc_type":            hit.doc_type or "unknown",
                            "authority":           hit.authority or "",
                            "page_start":          hit.page_start or 0,
                            "page_end":            hit.page_end or 0,
                            "chunk_index":         chunk_idx,
                            "content":             hit.content_text or "",
                            "score":               hit.score or 0.0,
                            "reranker_score":      hit.reranker_score or 0.0,
                            "_best_score":         new_score,
                            "_query_origin":       query[:80],
                            "_chapter_key":        chapter_key,
                            "_retrieval_mode":     "IC_GRADE_FALLBACK",
                            "_fallback":           True,
                            "container_name":      hit.container_name or "",
                            "retrieval_timestamp": hit.retrieval_timestamp or "",
                            # Scope provenance — used for cross-deal contamination detection
                            "fund_id":             hit.fund_id or "",
                            "deal_id":             hit.deal_id or "",
                            # v4 CU pipeline enrichment fields
                            "section_type":        getattr(hit, "section_type", None),
                            "vehicle_type":        getattr(hit, "vehicle_type", None),
                            "governance_critical": getattr(hit, "governance_critical", False),
                            "governance_flags":    getattr(hit, "governance_flags", []) or [],
                            "breadcrumb":          getattr(hit, "breadcrumb", None),
                        }
            except Exception:
                logger.warning(
                    "FILTER_FALLBACK_FAILED ch=%s q=%d", chapter_key, q_idx,
                    exc_info=True,
                )

        # Re-validate with fallback chunks merged in
        valid_chunks = [
            c for c in chapter_hits.values()
            if validate_provenance(c)
        ]
        logger.info(
            "FILTER_FALLBACK_RESULT ch=%s chunks_after_fallback=%d",
            chapter_key, len(valid_chunks),
        )

    # Coverage stats
    # ── Cross-deal contamination detection ──────────────────────────
    # If deal_name is provided and chunks have deal_id metadata, filter out
    # any chunk whose deal_id doesn't match the requested deal. This is the
    # LAST LINE OF DEFENSE against cross-deal contamination.
    if deal_name:
        clean_chunks: list[dict] = []
        contaminated_count = 0
        shared_aux_ids = _shared_auxiliary_fund_ids()
        for c in valid_chunks:
            chunk_deal = c.get("deal_id", "")
            chunk_fund = str(c.get("fund_id", "") or "").lower()
            # Allow: empty deal_id (legacy/untagged), matching deal_id
            # Also allow: configured shared auxiliary corpora (fund constitution,
            # regulatory libraries, service providers), which are global by design.
            if (
                not chunk_deal
                or chunk_deal.lower() == deal_name.lower()
                or chunk_fund in shared_aux_ids
            ):
                clean_chunks.append(c)
            else:
                contaminated_count += 1
                logger.error(
                    "CROSS_DEAL_CONTAMINATION_BLOCKED ch=%s deal=%s "
                    "chunk_deal_id=%s chunk_id=%s blob=%s fund_id=%s",
                    chapter_key, deal_name, chunk_deal,
                    c.get("chunk_id", "?"), c.get("blob_name", "?"),
                    c.get("fund_id", "?"),
                )
        if contaminated_count > 0:
            logger.critical(
                "CONTAMINATION_SUMMARY ch=%s deal=%s blocked=%d kept=%d — "
                "cross-deal chunks removed from evidence corpus",
                chapter_key, deal_name, contaminated_count, len(clean_chunks),
            )
        valid_chunks = clean_chunks

    unique_docs = len({c["blob_name"] for c in valid_chunks})
    doc_types   = list({c.get("doc_type", "unknown") for c in valid_chunks})
    chunk_count = len(valid_chunks)
    fallback_count = sum(1 for c in valid_chunks if c.get("_fallback"))

    threshold = CHAPTER_EVIDENCE_THRESHOLDS.get(
        chapter_key,
        ChapterEvidenceThreshold(min_chunks=4, min_docs=2),
    )

    if threshold.is_satisfied(chunk_count, unique_docs, set(doc_types)):
        coverage_status = COVERAGE_SATURATED
    elif chunk_count > 0:
        coverage_status = COVERAGE_PARTIAL
    else:
        coverage_status = COVERAGE_MISSING

    return {
        "chunks":          valid_chunks,
        "queries":         queries,
        "coverage_status": coverage_status,
        "retrieval_mode":  retrieval_mode,
        "doc_type_filter": active_filter,
        "stats": {
            "chunk_count":    chunk_count,
            "unique_docs":    unique_docs,
            "doc_types":      doc_types,
            "fallback_count": fallback_count,
        },
    }


# ── IC-Grade Corpus Assembly ───────────────────────────────────────

def build_ic_corpus(
    chapter_evidence: dict[str, dict],
) -> dict[str, Any]:
    """Build IC-grade corpus from per-chapter evidence.

    Merges all chapter chunks, applies IC-grade coverage reranking,
    and assembles the final corpus with provenance headers.
    """
    all_chunks:    dict[str, dict] = {}
    chapter_stats: dict[str, dict] = {}

    for ch_key, ch_data in chapter_evidence.items():
        chapter_stats[ch_key] = {
            "queries":         ch_data.get("queries", []),
            "coverage_status": ch_data.get("coverage_status", COVERAGE_MISSING),
            "retrieval_mode":  ch_data.get("retrieval_mode", "IC_GRADE"),
            "doc_type_filter": ch_data.get("doc_type_filter"),
            "stats":           ch_data.get("stats", {}),
        }

        for chunk in ch_data.get("chunks", []):
            blob      = chunk.get("blob_name", chunk.get("title", ""))
            chunk_idx = chunk.get("chunk_index", 0)
            dedup_key = f"{blob}::{chunk_idx}"
            existing  = all_chunks.get(dedup_key)
            new_score = chunk.get("_best_score", 0.0)
            if existing is None or new_score > existing.get("_best_score", 0.0):
                all_chunks[dedup_key] = chunk

    merged = list(all_chunks.values())
    ranked = ic_coverage_rerank(merged)

    # ── Critical document type forced inclusion ───────────────────
    # Partition into critical (governance-decisive) and standard chunks.
    # Critical chunks are inserted FIRST, ensuring they are never dropped
    # by the budget cutoff regardless of reranker score.
    critical:  list[dict] = []
    standard:  list[dict] = []
    for chunk in ranked:
        dt = (chunk.get("doc_type") or "").lower()
        if dt in CRITICAL_DOC_TYPES:
            critical.append(chunk)
        else:
            standard.append(chunk)

    if critical:
        logger.info(
            "IC_CORPUS_CRITICAL_DOCS forced=%d doc_types=%s",
            len(critical),
            list({c.get("doc_type", "?") for c in critical}),
        )

    # Process critical chunks first, then standard
    ordered = critical + standard

    max_chars = TOTAL_BUDGET_CHARS
    consumed  = 0
    parts:         list[str]  = []
    evidence_map:  list[dict] = []
    raw_chunks:    list[dict] = []

    for chunk in ordered:
        content = chunk.get("content", "")
        if not content:
            continue
        remaining = max_chars - consumed
        if remaining <= 0:
            break
        snippet = content[:remaining]

        blob_name = chunk.get("blob_name", chunk.get("title", ""))
        chunk_id  = chunk.get(
            "chunk_id",
            chunk.get("id", f"{blob_name}::p{chunk.get('page_start', 0)}"),
        )

        header = (
            f"--- [{blob_name}] "
            f"pages {chunk.get('page_start', '?')}-{chunk.get('page_end', '?')} "
            f"| mode={chunk.get('_retrieval_mode', '?')} "
            f"semantic={chunk.get('_semantic_score', 0):.3f} "
            f"cvg_bonus={chunk.get('_coverage_bonus', 0):.3f} "
            f"final={chunk.get('_final_score', 0):.3f} ---"
        )
        parts.append(f"{header}\n{snippet}")
        consumed += len(snippet) + len(header) + 1

        evidence_map.append({
            "blob_name":           blob_name,
            "chunk_index":         chunk.get("chunk_index", 0),
            "page_start":          chunk.get("page_start", 0),
            "page_end":            chunk.get("page_end", 0),
            "doc_type":            chunk.get("doc_type", "unknown"),
            "authority":           chunk.get("authority", ""),
            "container_name":      chunk.get("container_name", ""),
            "chunk_id":            chunk_id,
            "query_origin":        chunk.get("_query_origin", ""),
            "chapter_key":         chunk.get("_chapter_key", ""),
            "retrieval_mode":      chunk.get("_retrieval_mode", ""),
            "retrieval_timestamp": chunk.get("retrieval_timestamp", ""),
        })

        raw_chunks.append({
            "chunk_id":       chunk_id,
            "blob_name":      blob_name,
            "doc_type":       chunk.get("doc_type", "unknown"),
            "authority":      chunk.get("authority", ""),
            "page_start":     chunk.get("page_start", 0),
            "page_end":       chunk.get("page_end", 0),
            "content":        snippet,
            "semantic_score": chunk.get("_semantic_score", 0),
            "coverage_bonus": chunk.get("_coverage_bonus", 0),
            "final_score":    chunk.get("_final_score", 0),
            "query_origin":   chunk.get("_query_origin", ""),
            "chapter_key":    chunk.get("_chapter_key", ""),
            "retrieval_mode": chunk.get("_retrieval_mode", ""),
        })

    corpus = "\n\n".join(parts)

    # Word-count overflow guard
    word_count = len(corpus.split())
    max_words  = max_chars // 5
    if word_count > max_words:
        words  = corpus.split()
        corpus = " ".join(words[:max_words])
        logger.warning(
            "IC_CORPUS_TRUNCATED original_words=%d truncated_to=%d",
            word_count, max_words,
        )

    unique_docs = len({c["blob_name"] for c in raw_chunks})

    global_stats = {
        "unique_docs":      unique_docs,
        "total_chunks":     len(raw_chunks),
        "corpus_chars":     len(corpus),
        "retrieval_policy": RETRIEVAL_POLICY_NAME,
    }

    logger.info(
        "IC_CORPUS_BUILT chunks=%d unique_docs=%d corpus_chars=%d policy=%s",
        len(raw_chunks), unique_docs, len(corpus), RETRIEVAL_POLICY_NAME,
    )

    return {
        "corpus_text":  corpus,
        "evidence_map": evidence_map,
        "raw_chunks":   raw_chunks,
        "chapter_stats": chapter_stats,
        "global_stats":  global_stats,
    }


# ── Evidence Saturation Enforcement ────────────────────────────────

def enforce_evidence_saturation(
    chapter_stats: dict[str, dict],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Enforce evidence saturation thresholds per chapter."""
    gaps:                    list[dict] = []
    missing_document_classes: list[str] = []

    for ch_key, ch_data in chapter_stats.items():
        status = ch_data.get("coverage_status", COVERAGE_MISSING)
        stats  = ch_data.get("stats", {})

        if status == COVERAGE_MISSING:
            reason = (
                f"Chapter {ch_key}: NO evidence retrieved. "
                f"chunks={stats.get('chunk_count', 0)} "
                f"docs={stats.get('unique_docs', 0)} "
                f"mode={ch_data.get('retrieval_mode', '?')} "
                f"filter={ch_data.get('doc_type_filter', 'NONE')}"
            )
            gaps.append({"chapter": ch_key, "status": status, "reason": reason})
            logger.warning("EVIDENCE_GAP %s", reason)

            if ch_key in ("ch08_returns", "ch07_capital"):
                missing_document_classes.append("MISSING_FINANCIAL_DISCLOSURE")
            elif ch_key in ("ch05_legal", "ch06_terms"):
                missing_document_classes.append("NO_LPA_FOUND")

            if strict:
                raise EvidenceGapError(reason)

        elif status == COVERAGE_PARTIAL:
            threshold = CHAPTER_EVIDENCE_THRESHOLDS.get(ch_key)
            reason = (
                f"Chapter {ch_key}: PARTIAL evidence. "
                f"chunks={stats.get('chunk_count', 0)} "
                f"(min={threshold.min_chunks if threshold else '?'}) "
                f"docs={stats.get('unique_docs', 0)} "
                f"(min={threshold.min_docs if threshold else '?'}) "
                f"mode={ch_data.get('retrieval_mode', '?')}"
            )
            gaps.append({"chapter": ch_key, "status": status, "reason": reason})
            logger.info("EVIDENCE_PARTIAL %s", reason)

    all_saturated = len(gaps) == 0

    if missing_document_classes:
        logger.warning(
            "MISSING_DOCUMENT_CLASSES classes=%s", missing_document_classes,
        )

    return {
        "gaps":                    gaps,
        "missing_document_classes": list(set(missing_document_classes)),
        "all_saturated":           all_saturated,
    }


# ── Structured Retrieval Audit Artifact ────────────────────────────

def build_retrieval_audit(
    *,
    fund_id: str,
    deal_id: str,
    chapter_evidence: dict[str, dict],
    corpus_result: dict[str, Any],
    saturation_report: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured, serializable audit artifact.

    v2 additions: retrieval_mode and doc_type_filter recorded per chapter.
    """
    global_stats  = corpus_result.get("global_stats", {})
    chapter_stats = corpus_result.get("chapter_stats", {})

    unique_docs   = global_stats.get("unique_docs", 0)
    total_chunks  = global_stats.get("total_chunks", 0)
    all_saturated = saturation_report.get("all_saturated", False)
    missing_classes = saturation_report.get("missing_document_classes", [])

    if all_saturated and unique_docs >= 15 and total_chunks >= 80:
        evidence_confidence = "VERY_HIGH"
    elif unique_docs >= 10 and total_chunks >= 40:
        evidence_confidence = "HIGH"
    elif unique_docs >= 5 and total_chunks >= 20:
        evidence_confidence = "MEDIUM"
    else:  # override_filter=True — use caller-provided doc_type_filter
        evidence_confidence = "LOW"

    chapters_audit: dict[str, dict] = {}
    for ch_key, ch_info in chapter_stats.items():
        stats = ch_info.get("stats", {})
        chapters_audit[ch_key] = {
            "queries":         ch_info.get("queries", []),
            "retrieval_mode":  ch_info.get("retrieval_mode", "IC_GRADE"),
            "doc_type_filter": ch_info.get("doc_type_filter"),
            "chunk_count":     stats.get("chunk_count", 0),
            "unique_docs":     stats.get("unique_docs", 0),
            "coverage_status": ch_info.get("coverage_status", COVERAGE_MISSING),
            "doc_types":       stats.get("doc_types", []),
        }

    audit = {
        "retrieval_policy": RETRIEVAL_POLICY_NAME,
        "fund_id":   fund_id,
        "deal_id":   deal_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "chapters":  chapters_audit,
        "global_stats": {
            **global_stats,
            "evidence_confidence": evidence_confidence,
        },
        "saturation_report":      saturation_report,
        "missing_document_classes": missing_classes,
    }

    logger.info(
        "RETRIEVAL_AUDIT_BUILT policy=%s docs=%d chunks=%d confidence=%s gaps=%d",
        RETRIEVAL_POLICY_NAME, unique_docs, total_chunks,
        evidence_confidence, len(saturation_report.get("gaps", [])),
    )

    return audit


# ── Market Benchmark Retrieval (market-data-index) ─────────────────────────
#
# Retrieves structured benchmark data from the market-data-index, which is
# populated by the market-data pipeline (market_data_bootstrap.py + market-data-indexer).
# Used to ground ch08 (Return Modeling) and ch12 (Peer Comparison) with
# authoritative third-party benchmark data (PitchBook, Preqin, Bloomberg).

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


def retrieve_market_benchmarks(
    chapter_id: str,
    *,
    search_endpoint: str,
    search_api_key: str = "",
    asset_class_filter: str | None = None,
    top_k: int = 15,
    source_type_filter: str = "BENCHMARK",
) -> list[dict[str, Any]]:
    """Retrieve market benchmark chunks from market-data-index for a given chapter.

    Parameters
    ----------
    chapter_id : str
        One of the keys in CHAPTER_MARKET_DATA_QUERIES (e.g. "ch08_returns").
    search_endpoint : str
        Full Azure AI Search endpoint URL.
    search_api_key : str
        Azure AI Search admin or query key.
    asset_class_filter : str | None
        Optional OData filter value for the ``asset_class`` field
        (e.g. "private_credit").  If provided, restricts results.
    top_k : int
        Total chunks to return across all queries for this chapter.
    source_type_filter : str
        OData filter value for the ``source_type`` field (default "BENCHMARK").

    Returns
    -------
    list[dict]
        List of raw search result dicts from market-data-index, each containing
        content + structured benchmark fields (publisher, reference_date,
        asset_class, sub_strategy, vintage_year, metric_type, etc.).
        Returns [] if chapter_id is unknown or search fails.

    """
    import httpx as _httpx

    queries = CHAPTER_MARKET_DATA_QUERIES.get(chapter_id, [])
    if not queries:
        logger.warning(
            "retrieve_market_benchmarks: no queries for chapter %s", chapter_id,
        )
        return []

    index_name = "market-data-index"
    url = (
        f"{search_endpoint.rstrip('/')}/indexes/{index_name}"
        f"/docs/search?api-version=2024-05-01-preview"
    )

    # Build OData filter
    filter_parts = [f"source_type eq '{source_type_filter}'"]
    if asset_class_filter:
        filter_parts.append(f"asset_class eq '{asset_class_filter}'")
    odata_filter = " and ".join(filter_parts)

    per_query_top = max(3, top_k // len(queries))
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    # Resolve auth headers once before the query loop
    if search_api_key:
        _auth_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "api-key": search_api_key,
        }
    else:
        try:
            from azure.identity import DefaultAzureCredential as _DAC
            _token = _DAC().get_token("https://search.azure.com/.default")
            _auth_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token.token}",
            }
        except Exception as _auth_exc:
            logger.warning(
                "retrieve_market_benchmarks: AAD auth failed for %s — %s",
                chapter_id, _auth_exc,
            )
            return []

    for query in queries:
        if len(results) >= top_k:
            break
        body: dict[str, Any] = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "market-semantic",
            "top": per_query_top,
            "filter": odata_filter,
            "select": (
                "chunk_id,content,blob_name,doc_type,"
                "source_type,publisher,reference_date,"
                "asset_class,sub_strategy,vintage_year,metric_type,geography"
            ),
        }
        try:
            resp = _httpx.post(
                url,
                headers=_auth_headers,
                json=body,
                timeout=15.0,
            )
            resp.raise_for_status()
            for hit in resp.json().get("value", []):
                cid = hit.get("chunk_id") or hit.get("id", "")
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    results.append(hit)
                    if len(results) >= top_k:
                        break
        except Exception as exc:
            logger.warning(
                "retrieve_market_benchmarks: query failed for %s — %s",
                chapter_id, exc,
            )

    logger.info(
        "MARKET_BENCHMARKS_RETRIEVED chapter=%s chunks=%d",
        chapter_id, len(results),
    )
    return results[:top_k]
