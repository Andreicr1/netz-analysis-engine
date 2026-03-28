"""Investment Outlook — quarterly macro narrative extending WeeklyReportData.

Standalone content production file (not a package). Generates structured
LLM narrative with PDF output. Extends macro_committee_engine structured
data with investment-grade prose.

Usage (from async route via asyncio.to_thread)::

    engine = InvestmentOutlook(config=config, call_openai_fn=call_fn)
    result = engine.generate(db, organization_id=org_id, actor_id=user_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ai_engine.governance.output_safety import sanitize_llm_text
from ai_engine.prompts.registry import get_prompt_registry
from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

_TEMPLATE = "content/investment_outlook.j2"
_MAX_TOKENS = 4000


@dataclass(frozen=True, slots=True)
class OutlookResult:
    """Result of investment outlook generation."""

    content_md: str | None
    title: str
    language: Language
    status: str  # completed | failed
    error: str | None = None


class InvestmentOutlook:
    """Generates quarterly investment outlook from macro data + LLM narrative."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        call_openai_fn: CallOpenAiFn | None = None,
    ) -> None:
        self._config = config or {}
        self._call_openai_fn = call_openai_fn

    def generate(
        self,
        db: Session,
        *,
        organization_id: str,
        actor_id: str,
        language: Language = "pt",
    ) -> OutlookResult:
        """Generate investment outlook. Never raises — returns result with status.

        Designed to run inside asyncio.to_thread().
        """
        labels = LABELS[language]
        title = labels["investment_outlook_title"]

        if not self._call_openai_fn:
            return OutlookResult(
                content_md=None, title=title, language=language,
                status="failed", error="No LLM call function provided",
            )

        try:
            macro_data = self._gather_macro_data(db, organization_id)

            # ── Vector search (macro review chunks for context depth) ─
            documents = self._gather_vector_context(organization_id)

            content_md = self._generate_narrative(macro_data, documents=documents, language=language)

            logger.info(
                "investment_outlook_generated",
                organization_id=organization_id,
                language=language,
                content_length=len(content_md) if content_md else 0,
            )

            return OutlookResult(
                content_md=content_md, title=title,
                language=language, status="completed",
            )
        except Exception as exc:
            logger.exception("investment_outlook_failed", organization_id=organization_id)
            return OutlookResult(
                content_md=None, title=title, language=language,
                status="failed", error=str(exc),
            )

    def render_pdf(self, content_md: str, *, language: Language = "pt") -> BytesIO:
        """Render investment outlook content as PDF."""
        from vertical_engines.wealth.content_pdf import render_content_pdf

        labels = LABELS[language]
        return render_content_pdf(
            content_md,
            title=labels["investment_outlook_title"],
            language=language,
        )

    def _gather_macro_data(self, db: Session, organization_id: str) -> dict[str, Any]:
        """Gather latest macro snapshot data for outlook generation."""
        from app.domains.wealth.models.macro_committee import MacroReview

        review = (
            db.query(MacroReview)
            .filter(MacroReview.organization_id == organization_id)
            .order_by(MacroReview.created_at.desc())
            .first()
        )

        if review and review.report_json:
            return review.report_json

        return {"regions": {}, "global_indicators": {}, "note": "No macro data available"}

    def _gather_vector_context(self, organization_id: str) -> list[dict[str, Any]]:
        """Retrieve macro review chunks from pgvector for historical depth."""
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
        )

        try:
            query_text = "macro economic outlook regional growth inflation monetary policy"
            embed_result = generate_embeddings([query_text])
            if not embed_result.vectors:
                return []
            return search_fund_analysis_sync(
                organization_id=organization_id,
                query_vector=embed_result.vectors[0],
                source_type="macro_review",
                top=10,
            )
        except Exception:
            logger.warning("vector_search_failed_for_outlook")
            return []

    def _generate_narrative(
        self,
        macro_data: dict[str, Any],
        *,
        documents: list[dict[str, Any]] | None = None,
        language: Language,
    ) -> str | None:
        """Generate LLM narrative from macro data."""
        assert self._call_openai_fn is not None

        labels = LABELS[language]
        registry = get_prompt_registry()

        ctx = {
            "language": language,
            "global_macro_summary_label": labels["global_macro_summary"],
            "regional_outlook_label": labels["regional_outlook"],
            "asset_class_views_label": labels["asset_class_views"],
            "portfolio_positioning_label": labels["portfolio_positioning"],
            "key_risks_label": labels["key_risks"],
        }

        if registry.has_template(_TEMPLATE):
            system_prompt = registry.render(_TEMPLATE, **ctx)
        else:
            system_prompt = (
                "You are a senior investment strategist. Write a comprehensive "
                "Investment Outlook report based on the macro data provided."
            )

        user_content = self._build_user_content(macro_data, documents or [])

        response = self._call_openai_fn(
            system_prompt, user_content, max_tokens=_MAX_TOKENS,
        )

        raw = response.get("content") or response.get("text") or ""
        return sanitize_llm_text(raw) if raw else None

    def _build_user_content(
        self,
        macro_data: dict[str, Any],
        documents: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build user message from macro data + document chunks."""
        parts: list[str] = ["## Macro Data Snapshot"]

        regions = macro_data.get("regions", {})
        for region, data in regions.items():
            score = data.get("composite_score", "N/A") if isinstance(data, dict) else "N/A"
            parts.append(f"- {region}: composite_score={score}")

        gi = macro_data.get("global_indicators", {})
        if gi:
            parts.append("\n## Global Indicators")
            for key, val in gi.items():
                parts.append(f"- {key}: {val}")

        score_deltas = macro_data.get("score_deltas", [])
        if score_deltas:
            parts.append("\n## Recent Score Changes")
            for sd in score_deltas:
                if isinstance(sd, dict):
                    parts.append(
                        f"- {sd.get('region', '?')}: {sd.get('delta', 0):+.1f} "
                        f"({sd.get('previous_score', '?')} → {sd.get('current_score', '?')})",
                    )

        if documents:
            parts.append(f"\n## Historical Macro Analysis ({len(documents)} chunks)")
            for i, doc in enumerate(documents[:15]):
                text = doc.get("content", doc.get("text", ""))[:2000]
                source = doc.get("source_type", doc.get("section", f"doc_{i}"))
                parts.append(f"\n### [{source}]\n{text}")

        return "\n".join(parts)
