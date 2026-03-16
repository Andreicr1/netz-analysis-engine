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
from ai_engine.pipeline.models import CANONICAL_DOC_TYPES
from ai_engine.prompt_safety import sanitize_user_input
from ai_engine.prompts import prompt_registry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  Canonical Document Type Taxonomy
# ═══════════════════════════════════════════════════════════════════════
#
#  Single source of truth: ``ai_engine.pipeline.models.CANONICAL_DOC_TYPES``
#  (imported at the top of this module).  Do NOT redefine here.


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
    """Classify a document using LLM (async)."""
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
        if doc_type not in CANONICAL_DOC_TYPES:
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
    """Extract structured metadata from document content (async)."""
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
    """Generate a 200-word summary + key findings (async)."""
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
    """Run the full Document Intelligence pipeline on a single document (async).

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
#  Full Intelligence — Hybrid Classifier + Governance + Metadata + Summary
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FullIntelligenceResult:
    """Combined result from hybrid classification + governance + LLM extraction."""
    doc_type: str
    doc_type_score: float
    vehicle_type: str
    vehicle_type_score: float
    governance_critical: bool
    governance_flags: list[str]
    metadata: MetadataResult
    summary: SummaryResult
    classification_source: str = "hybrid_layer1"  # "hybrid_layer1" | "hybrid_layer2" | "hybrid_layer3"


async def async_run_full_intelligence(
    *,
    title: str,
    filename: str,
    container: str,
    content: str,
    fund_context: object | None = None,
) -> FullIntelligenceResult:
    """Hybrid intelligence: hybrid classifier + governance regex + LLM extraction.

    Pipeline:
    1. Hybrid classifier (Layer 1 rules → Layer 2 TF-IDF → Layer 3 LLM)
       resolves doc_type + vehicle_type in a single call.
    2. LLM metadata extraction + summarization in parallel (with resolved doc_type)
    3. Governance regex detection (instant, zero-cost)
    """
    from ai_engine.classification.hybrid_classifier import classify as hybrid_classify
    from ai_engine.extraction.governance_detector import detect_governance

    logger.info(
        "FULL_INTELLIGENCE_START title='%s' filename='%s'",
        title, filename,
    )

    # Step 1: Hybrid classification (handles its own escalation internally)
    classification = await hybrid_classify(
        content, filename, title=title, container=container,
    )
    doc_type = classification.doc_type
    doc_type_score = classification.confidence
    vehicle_type = classification.vehicle_type
    vehicle_type_score = classification.confidence
    classification_source = f"hybrid_layer{classification.layer}"

    # Step 2: Run metadata + summary in parallel with the resolved doc_type
    # Enrich content with fund aliases from entity bootstrap
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

    # Governance detection (sync, instant, zero-cost)
    gov = detect_governance(content)

    # Bootstrap vehicle hint override (highest confidence from Stage 2.5)
    if fund_context and hasattr(fund_context, "vehicles") and fund_context.vehicles:
        best_v = max(
            fund_context.vehicles.values(),
            key=lambda v: v.get("confidence", 0) if isinstance(v, dict) else 0,
            default=None,
        )
        if (
            best_v
            and isinstance(best_v, dict)
            and best_v.get("confidence", 0) > 0.8
            and vehicle_type == "other"
        ):
            vehicle_type = best_v.get("vehicle_type", "other")
            vehicle_type_score = 0.75

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
