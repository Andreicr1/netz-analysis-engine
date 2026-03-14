"""Document Intelligence Layer — LLM-powered classification, extraction, and summarisation.

Replaces the legacy keyword-only classifier with a 3-component pipeline run
at ingest time (before chunking/embedding) to enrich every document with:

  1. **Smart Classification** (gpt-4.1)
     Canonical ``doc_type`` aligned with retrieval governance + chapter
     affinity, plus ``governance_criticality`` flag.

  2. **Metadata Extraction** (gpt-5.1)
     Structured JSON with entities, counterparties, financial figures,
     dates, deal/vehicle structure, and governance flags.  This is the
     layer that catches "fund-of-funds via Side Letter" patterns that
     keyword classifiers miss entirely.

  3. **Document Summary** (gpt-4.1)
     200-word narrative summary + key_findings list.  Stored alongside
     chunks to enable summary-first retrieval and corpus-level reasoning.

Cost estimate: ~$0.08-0.12 per document.  For a typical 88-doc deal room
this is ~$7-10 one-time — trivial vs the downstream quality improvement.

Model rationale (user directive: "não se preocupe tanto com budget"):
  • Classification uses gpt-4.1 — reliable structured output, deterministic.
  • Metadata extraction uses gpt-5.1 — needs deep understanding of complex
    legal/financial documents (this is where Side Letter → fund-of-funds
    structure would be captured).
  • Summary uses gpt-4.1 — good comprehension, clean narrative.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ai_engine.model_config import get_model
from ai_engine.prompt_safety import sanitize_user_input
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Canonical Document Type Taxonomy
# ═══════════════════════════════════════════════════════════════════════
#
#  Designed to be the SINGLE source of truth, consumed by:
#    • Azure Search index ``doc_type`` field (retrieval governance filters)
#    • _CHAPTER_DOC_AFFINITY (memo book generator evidence selection)
#    • CRITICAL_DOC_TYPES (corpus inclusion guarantee)
#    • Document registry (Postgres)
#
#  Convention: lower_snake_case, matching retrieval governance OData filters.

CANONICAL_DOC_TYPES: tuple[str, ...] = (
    # ── Legal ─────────────────────────────────────────────────────────
    "legal_lpa",                # Limited Partnership Agreement / Fund Constitution / Offering Memo
    "legal_side_letter",        # Side Letter Agreement — governance-critical
    "legal_subscription",       # Subscription Agreement / Application Form
    "legal_agreement",          # Admin agreements, service agreements, engagement letters
    "legal_amendment",          # Amendments to existing agreements
    "legal_poa",                # Power of Attorney
    "legal_term_sheet",         # Term Sheet, LOI, indicative terms, fee letter
    "legal_credit_agreement",   # Credit Agreement, Facility Agreement, Loan Agreement
    "legal_security",           # Security Agreement, Pledge, Guarantee, Collateral
    "legal_intercreditor",      # Intercreditor Agreement

    # ── Financial ─────────────────────────────────────────────────────
    "financial_statements",     # Audited/unaudited financial statements
    "financial_nav",            # NAV reports, valuations, performance
    "financial_projections",    # Financial models, projections, scenarios

    # ── Regulatory ────────────────────────────────────────────────────
    "regulatory_cima",          # CIMA filings, licenses, registrations
    "regulatory_compliance",    # Compliance manuals, AML/KYC policies, procedures
    "regulatory_qdd",           # QDD documentation, tax compliance

    # ── Fund Structure / Profile ──────────────────────────────────────
    "fund_structure",           # Fund org docs, org charts, vehicle diagrams
    "fund_profile",             # Fund profile, strategy description
    "fund_presentation",        # Fund presentations, marketing decks, pitchbooks
    "fund_policy",              # Investment / credit / risk policies
    "strategy_profile",         # Strategy overview, mandate description

    # ── Capital & Operations ──────────────────────────────────────────
    "capital_raising",          # Capital raising materials, DDQ, commitments
    "credit_policy",            # Credit/lending policies, underwriting standards

    # ── Operational ───────────────────────────────────────────────────
    "operational_service",      # Service provider agreements (admin, custodian, auditor)
    "operational_insurance",    # Insurance policies, coverage
    "operational_monitoring",   # Portfolio monitoring, watchlist, covenant compliance

    # ── Analysis ──────────────────────────────────────────────────────
    "investment_memo",          # IC memos, investment memos, committee presentations
    "risk_assessment",          # Risk assessments, due diligence reports

    # ── General ───────────────────────────────────────────────────────
    "org_chart",                # Organizational charts
    "attachment",               # General attachments, exhibits, annexes
    "other",                    # Unclassified
)

# Lookup set for validation
_VALID_DOC_TYPES: frozenset[str] = frozenset(CANONICAL_DOC_TYPES)


# ── Affinity mapping: canonical doc_type → chapter affinity tags ──────
#
# The memo book generator's _CHAPTER_DOC_AFFINITY uses UPPER_CASE tags.
# This maps each canonical type to the set of affinity tags it should match.
# Updated _CHAPTER_DOC_AFFINITY in memo_book_generator.py will use
# canonical types directly, but this bridge ensures backward compat.

CANONICAL_TO_AFFINITY: dict[str, frozenset[str]] = {
    "legal_lpa":                frozenset({"LEGAL", "FUND_CONSTITUTION", "FUND_POLICY"}),
    "legal_side_letter":        frozenset({"SIDE_LETTER", "LEGAL_SIDE_LETTER", "LEGAL"}),
    "legal_subscription":       frozenset({"SUBSCRIPTION_AGREEMENT", "LEGAL"}),
    "legal_agreement":          frozenset({"LEGAL", "SERVICE_AGREEMENT"}),
    "legal_amendment":          frozenset({"LEGAL"}),
    "legal_poa":                frozenset({"LEGAL"}),
    "legal_term_sheet":         frozenset({"TERM_SHEET", "LEGAL"}),
    "legal_credit_agreement":   frozenset({"CREDIT_AGREEMENT", "FACILITY_AGREEMENT", "LOAN_AGREEMENT", "LEGAL"}),
    "legal_security":           frozenset({"SECURITY_AGREEMENT", "GUARANTEE", "PLEDGE", "LEGAL"}),
    "legal_intercreditor":      frozenset({"INTERCREDITOR", "LEGAL"}),
    "financial_statements":     frozenset({"FINANCIAL", "FINANCIAL_STATEMENTS"}),
    "financial_nav":            frozenset({"FINANCIAL", "FINANCIAL_STATEMENTS"}),
    "financial_projections":    frozenset({"FINANCIAL"}),
    "regulatory_cima":          frozenset({"REGULATORY", "COMPLIANCE"}),
    "regulatory_compliance":    frozenset({"REGULATORY", "COMPLIANCE"}),
    "regulatory_qdd":           frozenset({"REGULATORY"}),
    "fund_structure":           frozenset({"FUND_CONSTITUTION", "FUND_POLICY"}),
    "fund_profile":             frozenset({"FUND_POLICY"}),
    "fund_presentation":        frozenset({"FINANCIAL", "FUND_POLICY"}),
    "fund_policy":              frozenset({"FUND_POLICY", "FUND_CONSTITUTION"}),
    "strategy_profile":         frozenset({"FUND_POLICY"}),
    "capital_raising":          frozenset({"FINANCIAL"}),
    "credit_policy":            frozenset({"FUND_POLICY", "COVENANT_COMPLIANCE"}),
    "operational_service":      frozenset({"SERVICE_AGREEMENT"}),
    "operational_insurance":    frozenset({"INSURANCE"}),
    "operational_monitoring":   frozenset({"MONITORING", "COVENANT_COMPLIANCE", "WATCHLIST"}),
    "investment_memo":          frozenset({"RISK_ASSESSMENT"}),
    "risk_assessment":          frozenset({"RISK_ASSESSMENT"}),
    "org_chart":                frozenset(),
    "attachment":               frozenset(),
    "other":                    frozenset(),
}


def doc_type_matches_affinity(doc_type: str, affinity_tags: frozenset[str]) -> bool:
    """Check if a canonical doc_type matches any tag in an affinity set.

    Used by memo_book_generator to score evidence chunks.
    """
    mapped = CANONICAL_TO_AFFINITY.get(doc_type, frozenset())
    # Match on canonical type directly OR via affinity tag mapping
    return doc_type in affinity_tags or bool(mapped & affinity_tags)


# ═══════════════════════════════════════════════════════════════════════
#  Result Types
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ClassificationResult:
    """LLM classification output."""
    doc_type: str
    sub_type: str = ""
    confidence: int = 0
    governance_critical: bool = False
    reasoning: str = ""


@dataclass
class MetadataResult:
    """LLM metadata extraction output."""
    entities: dict[str, list[str]] = field(default_factory=dict)
    financial_figures: dict[str, Any] = field(default_factory=dict)
    dates: dict[str, str] = field(default_factory=dict)
    deal_structure: dict[str, Any] = field(default_factory=dict)
    governance_flags: list[str] = field(default_factory=list)
    counterparties: list[dict[str, str]] = field(default_factory=list)
    jurisdictions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SummaryResult:
    """LLM summary output."""
    summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    deal_relevance_score: int = 0


@dataclass
class DocumentIntelligenceResult:
    """Combined result from all 3 components."""
    classification: ClassificationResult
    metadata: MetadataResult
    summary: SummaryResult
    success: bool = True
    error: str | None = None


# ═══════════════════════════════════════════════════════════════════════
#  Component 1: Smart Classification (gpt-4.1)
# ═══════════════════════════════════════════════════════════════════════


def classify_document(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
    max_content_chars: int = 6_000,
) -> ClassificationResult:
    """Classify a document using gpt-4.1.

    Thin sync wrapper — delegates to ``async_classify_document``.
    """
    import asyncio

    return asyncio.run(async_classify_document(
        title=title, filename=filename, container=container,
        content=content, max_content_chars=max_content_chars,
    ))


# ═══════════════════════════════════════════════════════════════════════
#  Component 2: Metadata Extraction (gpt-5.1)
# ═══════════════════════════════════════════════════════════════════════


def extract_metadata(
    *,
    title: str,
    doc_type: str,
    content: str,
    max_content_chars: int = 12_000,
) -> MetadataResult:
    """Extract structured metadata using gpt-5.1.

    Thin sync wrapper — delegates to ``async_extract_metadata``.
    """
    import asyncio

    return asyncio.run(async_extract_metadata(
        title=title, doc_type=doc_type, content=content,
        max_content_chars=max_content_chars,
    ))


# ═══════════════════════════════════════════════════════════════════════
#  Component 3: Document Summary (gpt-4.1)
# ═══════════════════════════════════════════════════════════════════════


def summarize_document(
    *,
    title: str,
    doc_type: str,
    content: str,
    max_content_chars: int = 10_000,
) -> SummaryResult:
    """Generate a 200-word summary + key findings.

    Thin sync wrapper — delegates to ``async_summarize_document``.
    """
    import asyncio

    return asyncio.run(async_summarize_document(
        title=title, doc_type=doc_type, content=content,
        max_content_chars=max_content_chars,
    ))


# ═══════════════════════════════════════════════════════════════════════
#  Orchestrator — runs all 3 components in sequence
# ═══════════════════════════════════════════════════════════════════════

def run_document_intelligence(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
) -> DocumentIntelligenceResult:
    """Run the full Document Intelligence pipeline on a single document.

    Thin sync wrapper — delegates to ``async_run_document_intelligence``.
    """
    import asyncio

    return asyncio.run(async_run_document_intelligence(
        title=title, filename=filename, container=container,
        content=content,
    ))


# ═══════════════════════════════════════════════════════════════════════
#  Batch processor (for re-processing existing documents)
# ═══════════════════════════════════════════════════════════════════════

def run_batch_intelligence(
    documents: list[dict[str, str]],
) -> list[DocumentIntelligenceResult]:
    """Process a batch of documents through document intelligence.

    Each dict must have: title, filename, container, content.

    Returns results in the same order as input.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(documents)
    results_map: dict[int, DocumentIntelligenceResult] = {}

    def _run_one(idx: int, doc: dict):
        logger.info("DOC_INTELLIGENCE_BATCH %d/%d: %s", idx, total, doc.get("title", "?"))
        return idx, run_document_intelligence(
            title=doc.get("title", ""),
            filename=doc.get("filename", ""),
            container=doc.get("container", ""),
            content=doc.get("content", ""),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_run_one, i, doc): i
            for i, doc in enumerate(documents, 1)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                returned_idx, result = future.result()
                results_map[returned_idx] = result
            except Exception as exc:
                logger.error("Batch item %d failed: %s", idx, exc, exc_info=True)
                results_map[idx] = DocumentIntelligenceResult(
                    classification=ClassificationResult(doc_type="other"),
                    metadata=MetadataResult(),
                    summary=SummaryResult(),
                    success=False,
                    error=str(exc),
                )

    results = [results_map[i] for i in sorted(results_map)]

    logger.info(
        "DOC_INTELLIGENCE_BATCH_COMPLETE total=%d succeeded=%d",
        total, sum(1 for r in results if r.success),
    )
    return results


# ═══════════════════════════════════════════════════════════════════════
#  Async Components — native async using async_create_completion()
# ═══════════════════════════════════════════════════════════════════════

import asyncio


async def async_classify_document(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
    max_content_chars: int = 6_000,
) -> ClassificationResult:
    """Async version of ``classify_document``."""
    truncated = sanitize_user_input(content, max_length=max_content_chars) if content else ""

    doc_types_str = "\n".join(f"  • {dt}" for dt in CANONICAL_DOC_TYPES)
    system = prompt_registry.render(
        "extraction/classification_system.j2",
        doc_types=doc_types_str,
    )
    user = prompt_registry.render(
        "extraction/classification_user.j2",
        title=title or "Unknown",
        filename=filename or "Unknown",
        container=container or "Unknown",
        content=truncated or "(no content available)",
    )

    try:
        from ai_engine.openai_client import async_create_completion

        result = await async_create_completion(
            system_prompt=system,
            user_prompt=user,
            model=get_model("classification"),
            temperature=0.0,
            max_tokens=512,
            response_format={"type": "json_object"},
            stage="classification",
        )
        data = json.loads(result.text)

        doc_type = data.get("doc_type", "other")
        if doc_type not in _VALID_DOC_TYPES:
            logger.warning(
                "LLM returned invalid doc_type '%s' for '%s' — falling back to 'other'",
                doc_type, title,
            )
            doc_type = "other"

        return ClassificationResult(
            doc_type=doc_type,
            sub_type=data.get("sub_type", ""),
            confidence=min(100, max(0, int(data.get("confidence", 75)))),
            governance_critical=bool(data.get("governance_critical", False)),
            reasoning=data.get("reasoning", ""),
        )

    except Exception as exc:
        logger.error("Async document classification failed for '%s': %s", title, exc, exc_info=True)
        return ClassificationResult(
            doc_type="other",
            confidence=0,
            reasoning=f"Classification failed: {exc}",
        )


async def async_extract_metadata(
    *,
    title: str,
    doc_type: str,
    content: str,
    max_content_chars: int = 12_000,
) -> MetadataResult:
    """Async version of ``extract_metadata``."""
    truncated = sanitize_user_input(content, max_length=max_content_chars) if content else ""

    system = prompt_registry.render("extraction/extraction_system.j2")
    user = prompt_registry.render(
        "extraction/extraction_user.j2",
        doc_type=doc_type,
        title=title or "Unknown",
        content=truncated or "(no content available)",
    )
    try:
        from ai_engine.openai_client import async_create_completion

        result = await async_create_completion(
            system_prompt=system,
            user_prompt=user,
            model=get_model("extraction"),
            temperature=0.1,
            max_tokens=2048,
            response_format={"type": "json_object"},
            stage="extraction",
        )
        data = json.loads(result.text)

        return MetadataResult(
            entities=data.get("entities", {}),
            financial_figures=data.get("financial_figures", {}),
            dates=data.get("dates", {}),
            deal_structure=data.get("deal_structure", {}),
            governance_flags=data.get("governance_flags", []),
            counterparties=data.get("counterparties", []),
            jurisdictions=data.get("jurisdictions", []),
            raw=data,
        )

    except Exception as exc:
        logger.error("Async metadata extraction failed for '%s': %s", title, exc, exc_info=True)
        return MetadataResult()


async def async_summarize_document(
    *,
    title: str,
    doc_type: str,
    content: str,
    max_content_chars: int = 10_000,
) -> SummaryResult:
    """Async version of ``summarize_document``."""
    truncated = sanitize_user_input(content, max_length=max_content_chars) if content else ""

    system = prompt_registry.render("extraction/summary_system.j2")
    user = prompt_registry.render(
        "extraction/summary_user.j2",
        doc_type=doc_type,
        title=title or "Unknown",
        content=truncated or "(no content available)",
    )
    try:
        from ai_engine.openai_client import async_create_completion

        result = await async_create_completion(
            system_prompt=system,
            user_prompt=user,
            model=get_model("doc_summary"),
            temperature=0.2,
            max_tokens=1024,
            response_format={"type": "json_object"},
            stage="doc_summary",
        )
        data = json.loads(result.text)

        return SummaryResult(
            summary=data.get("summary", ""),
            key_findings=data.get("key_findings", []),
            deal_relevance_score=min(10, max(0, int(data.get("deal_relevance_score", 5)))),
        )

    except Exception as exc:
        logger.error("Async document summarization failed for '%s': %s", title, exc, exc_info=True)
        return SummaryResult()


async def async_run_document_intelligence(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
) -> DocumentIntelligenceResult:
    """Async version of ``run_document_intelligence``.

    1. Classify (async) → canonical doc_type
    2. Extract metadata + Summarize (parallel via asyncio.gather)
    """
    logger.info(
        "ASYNC_DOC_INTELLIGENCE_START title='%s' filename='%s'",
        title, filename,
    )

    # 1. Classification must complete first (metadata+summary depend on doc_type)
    classification = await async_classify_document(
        title=title,
        filename=filename,
        container=container,
        content=content,
    )
    logger.info(
        "ASYNC_DOC_INTELLIGENCE_CLASSIFIED title='%s' doc_type=%s confidence=%d",
        title, classification.doc_type, classification.confidence,
    )

    # 2 + 3. Metadata extraction & summary run concurrently (native async)
    metadata, summary = await asyncio.gather(
        async_extract_metadata(
            title=title,
            doc_type=classification.doc_type,
            content=content,
        ),
        async_summarize_document(
            title=title,
            doc_type=classification.doc_type,
            content=content,
        ),
    )

    logger.info(
        "ASYNC_DOC_INTELLIGENCE_COMPLETE title='%s' doc_type=%s relevance=%d findings=%d",
        title, classification.doc_type,
        summary.deal_relevance_score,
        len(summary.key_findings),
    )

    return DocumentIntelligenceResult(
        classification=classification,
        metadata=metadata,
        summary=summary,
    )


# ═══════════════════════════════════════════════════════════════════════
#  Full Intelligence — Cohere Rerank + Governance + Metadata + Summary
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FullIntelligenceResult:
    """Combined result from Cohere classification + governance + LLM extraction."""
    doc_type: str
    doc_type_score: float
    vehicle_type: str
    vehicle_type_score: float
    governance_critical: bool
    governance_flags: list[str]
    metadata: MetadataResult
    summary: SummaryResult
    classification_source: str = "cohere"  # "cohere" | "llm_fallback"


async def async_run_full_intelligence(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
    fund_context: object | None = None,
) -> FullIntelligenceResult:
    """Hybrid intelligence: Cohere Rerank classification + governance regex + LLM extraction.

    Pipeline:
    1. Cohere Rerank doc_type (sequential — resolves doc_type first)
    2. If Cohere doc_type score < threshold → fallback to LLM classification
    3. LLM metadata extraction + summarization in parallel (with resolved doc_type)
    4. Governance regex detection (instant, zero-cost)
    5. Cohere Rerank vehicle_type (after doc_type resolved)

    Falls back to full LLM pipeline if Cohere is unavailable.
    """
    from ai_engine.extraction.cohere_rerank import (
        async_classify_doc_type,
        async_classify_vehicle_type,
    )
    from ai_engine.extraction.governance_detector import detect_governance

    logger.info(
        "FULL_INTELLIGENCE_START title='%s' filename='%s'",
        title, filename,
    )

    # Check if Cohere is configured
    cohere_available = False
    try:
        from app.core.config.settings import settings
        cohere_available = bool(settings.COHERE_RERANK_KEY)
        fallback_threshold = settings.COHERE_FALLBACK_THRESHOLD
    except Exception:
        fallback_threshold = 0.35

    classification_source = "cohere"

    if cohere_available:
        # Step 1: Classify first (fast Cohere call) to get resolved doc_type
        try:
            doc_type_result = await async_classify_doc_type(content, filename)

            doc_type = doc_type_result.doc_type
            doc_type_score = doc_type_result.score

            # Validate against canonical types
            if doc_type not in _VALID_DOC_TYPES:
                logger.warning("Cohere returned invalid doc_type '%s' — falling back to 'other'", doc_type)
                doc_type = "other"

            # Fallback to LLM classification if score too low
            if doc_type_score < fallback_threshold:
                logger.info(
                    "Cohere score %.3f < %.3f for '%s' — using LLM fallback",
                    doc_type_score, fallback_threshold, filename,
                )
                llm_classification = await async_classify_document(
                    title=title, filename=filename, container=container, content=content,
                )
                doc_type = llm_classification.doc_type
                doc_type_score = llm_classification.confidence / 100.0
                classification_source = "llm_fallback"

            # Step 2: Run metadata + summary in parallel with the resolved doc_type
            # Enrich content with fund aliases from entity bootstrap (Stage 2.5)
            meta_content = content
            if fund_context and hasattr(fund_context, "aliases") and fund_context.aliases:
                alias_lines = ", ".join(
                    f"{k} = {v}" for k, v in fund_context.aliases.items()
                )
                meta_content = (
                    f"[Fund entity aliases: {alias_lines}]\n\n{content}"
                )

            metadata, summary = await asyncio.gather(
                async_extract_metadata(title=title, doc_type=doc_type, content=meta_content),
                async_summarize_document(title=title, doc_type=doc_type, content=content),
            )

        except Exception:
            logger.warning(
                "Cohere classification failed — full LLM fallback: %s",
                filename, exc_info=True,
            )
            # Full LLM fallback
            di_result = await async_run_document_intelligence(
                title=title, filename=filename, container=container, content=content,
            )
            doc_type = di_result.classification.doc_type
            doc_type_score = di_result.classification.confidence / 100.0
            metadata = di_result.metadata
            summary = di_result.summary
            classification_source = "llm_fallback"
    else:
        # No Cohere — full LLM pipeline
        di_result = await async_run_document_intelligence(
            title=title, filename=filename, container=container, content=content,
        )
        doc_type = di_result.classification.doc_type
        doc_type_score = di_result.classification.confidence / 100.0
        metadata = di_result.metadata
        summary = di_result.summary
        classification_source = "llm_fallback"

    # Governance detection (sync, instant, zero-cost)
    gov = detect_governance(content)

    # Vehicle type classification
    # Extract bootstrap vehicle hint (highest confidence from Stage 2.5)
    _bootstrap_vehicle_hint: str | None = None
    if fund_context and hasattr(fund_context, "vehicles") and fund_context.vehicles:
        best_v = max(
            fund_context.vehicles.values(),
            key=lambda v: v.get("confidence", 0) if isinstance(v, dict) else 0,
            default=None,
        )
        if best_v and isinstance(best_v, dict) and best_v.get("confidence", 0) > 0.8:
            _bootstrap_vehicle_hint = best_v.get("vehicle_type")

    if cohere_available:
        try:
            vehicle_result = await async_classify_vehicle_type(
                content, filename, doc_type,
            )
            vehicle_type = vehicle_result.vehicle_type
            vehicle_type_score = vehicle_result.score

            # Use bootstrap hint as tiebreaker for borderline Cohere scores
            if (
                _bootstrap_vehicle_hint
                and vehicle_type_score < fallback_threshold
                and vehicle_type in ("other", "unknown")
            ):
                logger.info(
                    "Vehicle type using bootstrap hint '%s' (Cohere score %.3f < %.3f)",
                    _bootstrap_vehicle_hint, vehicle_type_score, fallback_threshold,
                )
                vehicle_type = _bootstrap_vehicle_hint
                vehicle_type_score = 0.75  # bootstrap-derived confidence

        except Exception:
            logger.warning("Vehicle type classification failed: %s", filename, exc_info=True)
            vehicle_type = _bootstrap_vehicle_hint or "other"
            vehicle_type_score = 0.75 if _bootstrap_vehicle_hint else 0.0
    else:
        if _bootstrap_vehicle_hint:
            vehicle_type = _bootstrap_vehicle_hint
            vehicle_type_score = 0.75
        else:
            vehicle_type = metadata.deal_structure.get("vehicle_type", "other") if metadata.deal_structure else "other"
            vehicle_type_score = 0.5

    logger.info(
        "FULL_INTELLIGENCE_COMPLETE title='%s' doc_type=%s(%.2f) vehicle=%s(%.2f) "
        "gov_critical=%s gov_flags=%d source=%s",
        title, doc_type, doc_type_score, vehicle_type, vehicle_type_score,
        gov.governance_critical, len(gov.governance_flags), classification_source,
    )

    return FullIntelligenceResult(
        doc_type=doc_type,
        doc_type_score=doc_type_score,
        vehicle_type=vehicle_type,
        vehicle_type_score=vehicle_type_score,
        governance_critical=gov.governance_critical,
        governance_flags=gov.governance_flags,
        metadata=metadata,
        summary=summary,
        classification_source=classification_source,
    )
