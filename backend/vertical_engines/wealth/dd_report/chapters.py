"""Chapter generation — per-chapter LLM calls for DD Reports.

Generates individual chapters using evidence pack context + Jinja2 prompts.
Each chapter call is bounded by per-chapter timeout (30s default).
Sanitizes all LLM output before returning.
"""

from __future__ import annotations

from typing import Any

import structlog

from ai_engine.governance.output_safety import sanitize_llm_text
from ai_engine.prompts.registry import get_prompt_registry
from vertical_engines.wealth.dd_report.evidence_pack import EvidencePack
from vertical_engines.wealth.dd_report.models import CHAPTER_REGISTRY, ChapterResult
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

# Template subdirectory for DD chapter prompts
_TEMPLATE_PREFIX = "dd_chapters"


def _get_chapter_def(tag: str) -> dict[str, Any] | None:
    """Look up chapter definition by tag."""
    return next((ch for ch in CHAPTER_REGISTRY if ch["tag"] == tag), None)


def generate_chapter(
    call_openai_fn: CallOpenAiFn,
    *,
    chapter_tag: str,
    evidence_context: dict[str, Any],
    chapter_summaries: dict[str, str] | None = None,
    evidence_pack: EvidencePack | None = None,
) -> ChapterResult:
    """Generate a single DD Report chapter via LLM.

    Never raises — returns a ChapterResult with status='failed' on error.

    Parameters
    ----------
    call_openai_fn : CallOpenAiFn
        Injected LLM call function.
    chapter_tag : str
        Chapter identifier (e.g., 'executive_summary').
    evidence_context : dict
        Filtered evidence pack context for this chapter.
    chapter_summaries : dict
        For recommendation chapter: summaries of chapters 1-7.

    Returns
    -------
    ChapterResult
        Generated chapter content (frozen dataclass).
    """
    ch_def = _get_chapter_def(chapter_tag)
    if not ch_def:
        return ChapterResult(
            tag=chapter_tag, order=0, title="Unknown",
            content_md=None, status="failed",
            error=f"Unknown chapter tag: {chapter_tag}",
        )

    try:
        registry = get_prompt_registry()
        template_name = f"{_TEMPLATE_PREFIX}/{chapter_tag}.j2"

        # Build template context
        ctx = {**evidence_context}
        if chapter_summaries:
            ctx["chapter_summaries"] = chapter_summaries

        # Inject source-aware metadata for template preambles
        if evidence_pack is not None:
            ctx.update(evidence_pack.compute_source_metadata(chapter_tag))

        # Render prompt
        if registry.has_template(template_name):
            system_prompt = registry.render(template_name, **ctx)
        else:
            # Fallback: basic prompt if template not yet registered
            system_prompt = (
                f"You are a senior investment analyst writing the "
                f"'{ch_def['title']}' chapter of a fund due diligence report.\n\n"
                f"Write a thorough, institutional-quality analysis in markdown."
            )

        user_content = _build_user_content(chapter_tag, evidence_context)

        # Call LLM
        response = call_openai_fn(
            system_prompt,
            user_content,
            max_tokens=ch_def["max_tokens"],
        )

        raw_content = response.get("content") or response.get("text") or ""

        # Sanitize LLM output (6-stage pipeline)
        content_md = sanitize_llm_text(raw_content) if raw_content else None

        logger.info(
            "chapter_generated",
            chapter_tag=chapter_tag,
            content_length=len(content_md) if content_md else 0,
        )

        return ChapterResult(
            tag=chapter_tag,
            order=ch_def["order"],
            title=ch_def["title"],
            content_md=content_md,
            evidence_refs={"documents_used": len(evidence_context.get("documents", []))},
            quant_data=evidence_context.get("quant_profile", {}),
            status="completed",
        )

    except Exception as exc:
        logger.exception("chapter_generation_failed", chapter_tag=chapter_tag)
        return ChapterResult(
            tag=chapter_tag,
            order=ch_def["order"],
            title=ch_def["title"],
            content_md=None,
            status="failed",
            error=str(exc),
        )


def _build_user_content(
    chapter_tag: str,
    evidence_context: dict[str, Any],
) -> str:
    """Build the user message content from evidence context."""
    parts: list[str] = []

    # Fund identity
    parts.append(f"Fund: {evidence_context.get('fund_name', 'Unknown')}")
    if evidence_context.get("isin"):
        parts.append(f"ISIN: {evidence_context['isin']}")
    if evidence_context.get("manager_name"):
        parts.append(f"Manager: {evidence_context['manager_name']}")

    # Quant metrics for relevant chapters
    quant = evidence_context.get("quant_profile", {})
    if quant and chapter_tag in (
        "executive_summary", "performance_analysis", "risk_framework", "recommendation"
    ):
        parts.append("\n## Quantitative Metrics")
        for key, val in quant.items():
            if val is not None and key != "score_components":
                parts.append(f"- {key}: {val}")

    # Risk metrics for risk chapter
    risk = evidence_context.get("risk_metrics", {})
    if risk and chapter_tag == "risk_framework":
        parts.append("\n## Risk Metrics")
        for key, val in risk.items():
            if val is not None:
                parts.append(f"- {key}: {val}")

    # SEC 13F data for investment_strategy
    if chapter_tag == "investment_strategy" and evidence_context.get("thirteenf_available"):
        parts.append("\n## SEC 13F Holdings Data")
        sector_weights = evidence_context.get("sector_weights", {})
        if sector_weights:
            parts.append("Sector allocation (most recent quarter):")
            for sector, weight in sector_weights.items():
                parts.append(f"- {sector}: {weight * 100:.1f}%")
        if evidence_context.get("drift_detected"):
            parts.append("⚠ Sector drift detected between recent quarters")
        parts.append(f"Quarters of 13F data available: {evidence_context.get('drift_quarters', 0)}")

    # SEC ADV data for manager_assessment
    if chapter_tag == "manager_assessment":
        adv_aum = evidence_context.get("adv_aum_history", {})
        if adv_aum:
            parts.append("\n## SEC ADV — Regulatory AUM")
            for key, val in adv_aum.items():
                parts.append(f"- {key}: {val}")
        adv_team = evidence_context.get("adv_team", [])
        if adv_team:
            parts.append(f"\n## SEC ADV — Team ({len(adv_team)} members)")
            for member in adv_team:
                line = f"- {member.get('person_name', 'Unknown')}"
                if member.get("title"):
                    line += f" ({member['title']})"
                parts.append(line)

    # Compliance disclosures for operational_dd
    if chapter_tag == "operational_dd":
        disclosures = evidence_context.get("compliance_disclosures")
        if disclosures is not None:
            parts.append(f"\n## SEC Compliance Disclosures: {disclosures}")

    # Document excerpts
    docs = evidence_context.get("documents", [])
    if docs:
        parts.append(f"\n## Document Evidence ({len(docs)} chunks)")
        for i, doc in enumerate(docs[:20]):  # Cap at 20 chunks
            text = doc.get("text", doc.get("content", ""))[:2000]
            source = doc.get("source", doc.get("title", f"doc_{i}"))
            parts.append(f"\n### [{source}]\n{text}")

    # Chapter summaries (for recommendation chapter)
    summaries = evidence_context.get("chapter_summaries", {})
    if summaries:
        parts.append("\n## Previous Chapter Summaries")
        for tag, summary in summaries.items():
            parts.append(f"\n### {tag}\n{summary[:500]}")

    return "\n".join(parts)
