"""Flash Report — event-driven market flash reports.

Standalone content production file (not a package). Triggered manually or
by regime change. 48h cooldown enforced. Requires human review before
distribution — download endpoint checks status == 'approved' before serving.

Usage (from async route via asyncio.to_thread)::

    engine = FlashReport(config=config, call_openai_fn=call_fn)
    result = engine.generate(db, organization_id=org_id, actor_id=user_id, event_context={...})
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
from vertical_engines.wealth.macro_committee_engine import check_emergency_cooldown
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

_TEMPLATE = "content/flash_report.j2"
_MAX_TOKENS = 3000
_COOLDOWN_HOURS = 48


@dataclass(frozen=True)
class FlashReportResult:
    """Result of flash report generation."""

    content_md: str | None
    title: str
    language: Language
    status: str  # completed | failed | cooldown
    error: str | None = None


class FlashReport:
    """Generates event-driven market flash reports with cooldown enforcement."""

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
        event_context: dict[str, Any] | None = None,
        language: Language = "pt",
    ) -> FlashReportResult:
        """Generate flash report. Never raises — returns result with status.

        Enforces 48h cooldown between flash reports for the same org.
        Designed to run inside asyncio.to_thread().
        """
        labels = LABELS[language]
        title = labels["flash_report_title"]

        if not self._call_openai_fn:
            return FlashReportResult(
                content_md=None, title=title, language=language,
                status="failed", error="No LLM call function provided",
            )

        try:
            # Check cooldown
            last_flash_at = self._get_last_flash_report_time(db, organization_id)
            if not check_emergency_cooldown(last_flash_at, cooldown_hours=_COOLDOWN_HOURS):
                logger.info(
                    "flash_report_cooldown_active",
                    organization_id=organization_id,
                    last_flash_at=str(last_flash_at),
                )
                return FlashReportResult(
                    content_md=None, title=title, language=language,
                    status="cooldown",
                    error=f"Flash report cooldown active ({_COOLDOWN_HOURS}h). "
                          f"Last report: {last_flash_at}",
                )

            context = event_context or {}
            macro_data = self._gather_macro_context(db, organization_id)
            context["macro_snapshot"] = macro_data

            content_md = self._generate_narrative(context, language=language)

            logger.info(
                "flash_report_generated",
                organization_id=organization_id,
                language=language,
                content_length=len(content_md) if content_md else 0,
            )

            return FlashReportResult(
                content_md=content_md, title=title,
                language=language, status="completed",
            )
        except Exception as exc:
            logger.exception("flash_report_failed", organization_id=organization_id)
            return FlashReportResult(
                content_md=None, title=title, language=language,
                status="failed", error=str(exc),
            )

    def render_pdf(self, content_md: str, *, language: Language = "pt") -> BytesIO:
        """Render flash report content as PDF."""
        from datetime import date

        from reportlab.lib.units import mm
        from reportlab.platypus import HRFlowable, Paragraph, Spacer

        from ai_engine.pdf.pdf_base import (
            ORANGE,
            build_netz_styles,
            create_netz_document,
            netz_header_footer,
            safe_text,
        )
        from vertical_engines.wealth.fact_sheet.i18n import format_date

        labels = LABELS[language]
        title = labels["flash_report_title"]
        styles = build_netz_styles()
        buf = BytesIO()
        doc = create_netz_document(buf, title=title)
        story: list[Any] = []

        # Cover
        story.append(Paragraph(title, styles["cover_title"]))
        story.append(Spacer(1, 3 * mm))
        story.append(HRFlowable(width="45%", thickness=2, color=ORANGE, spaceAfter=5 * mm, hAlign="CENTER"))
        story.append(Paragraph(format_date(date.today(), language), styles["cover_meta"]))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(labels["confidential"], styles["cover_confidential"]))
        story.append(Spacer(1, 6 * mm))

        # Content
        for line in content_md.split("\n"):
            line = line.strip()
            if not line:
                story.append(Spacer(1, 2 * mm))
            elif line.startswith("## "):
                story.append(Paragraph(safe_text(line[3:]), styles["section_heading"]))
            elif line.startswith("# "):
                story.append(Paragraph(safe_text(line[2:]), styles["cover_subtitle"]))
            else:
                story.append(Paragraph(safe_text(line), styles["body"]))

        # Disclaimer
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(labels["content_disclaimer"], styles["disclaimer"]))

        def _on_page(canvas: Any, doc_obj: Any) -> None:
            netz_header_footer(
                canvas, doc_obj, report_title=title,
                confidentiality=labels["confidential"],
            )

        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
        buf.seek(0)
        return buf

    def _get_last_flash_report_time(self, db: Session, organization_id: str) -> Any:
        """Get timestamp of last flash report for cooldown check."""
        from app.domains.wealth.models.content import WealthContent

        last = (
            db.query(WealthContent.created_at)
            .filter(
                WealthContent.organization_id == organization_id,
                WealthContent.content_type == "flash_report",
            )
            .order_by(WealthContent.created_at.desc())
            .first()
        )
        return last[0] if last else None

    def _gather_macro_context(self, db: Session, organization_id: str) -> dict[str, Any]:
        """Gather macro context for flash report."""
        from app.domains.wealth.models.macro_committee import MacroReview

        review = (
            db.query(MacroReview)
            .filter(MacroReview.organization_id == organization_id)
            .order_by(MacroReview.created_at.desc())
            .first()
        )

        if review and review.report_json:
            return review.report_json

        return {"note": "No macro context available"}

    def _generate_narrative(
        self,
        context: dict[str, Any],
        *,
        language: Language,
    ) -> str | None:
        """Generate LLM narrative for flash report."""
        assert self._call_openai_fn is not None

        labels = LABELS[language]
        registry = get_prompt_registry()

        ctx = {
            "language": language,
            "market_event_label": labels["market_event"],
            "market_impact_label": labels["market_impact"],
            "portfolio_positioning_label": labels["portfolio_positioning"],
            "recommended_actions_label": labels["recommended_actions"],
            "key_risks_label": labels["key_risks"],
        }

        if registry.has_template(_TEMPLATE):
            system_prompt = registry.render(_TEMPLATE, **ctx)
        else:
            system_prompt = (
                "You are a senior market analyst. Write a concise Flash Report "
                "analyzing a significant market event."
            )

        user_content = self._build_user_content(context)

        response = self._call_openai_fn(
            system_prompt, user_content, max_tokens=_MAX_TOKENS,
        )

        raw = response.get("content") or response.get("text") or ""
        return sanitize_llm_text(raw) if raw else None

    def _build_user_content(self, context: dict[str, Any]) -> str:
        """Build user message from event context."""
        parts: list[str] = []

        event = context.get("event_description", "Market event requiring analysis")
        parts.append(f"## Event\n{event}")

        macro = context.get("macro_snapshot", {})
        if macro:
            parts.append("\n## Current Macro Context")
            regions = macro.get("regions", {})
            for region, data in regions.items():
                if isinstance(data, dict):
                    score = data.get("composite_score", "N/A")
                    parts.append(f"- {region}: composite_score={score}")

        return "\n".join(parts)
