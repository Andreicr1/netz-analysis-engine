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


@dataclass(frozen=True, slots=True)
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

            # ── Vector search (event-relevant macro review chunks) ────
            context["documents"] = self._gather_vector_context(
                event_description=context.get("event_description", ""),
                organization_id=organization_id,
            )

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
        """Render flash report content as PDF (ReportLab, sync)."""
        from vertical_engines.wealth.content_pdf import render_content_pdf

        labels = LABELS[language]
        return render_content_pdf(
            content_md,
            title=labels["flash_report_title"],
            language=language,
        )

    async def render_pdf_async(self, content_md: str, *, language: Language = "pt") -> bytes:
        """Render flash report content as PDF via Playwright (async)."""
        from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
        from vertical_engines.wealth.pdf.templates.content_report import render_content_report

        labels = LABELS[language]
        html_str = render_content_report(
            content_md,
            title=labels["flash_report_title"],
            language=language,
        )
        return await html_to_pdf(html_str, print_background=True)

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
        """Gather macro context with real indicator values for flash report."""
        from sqlalchemy import select

        from app.domains.wealth.models.macro_committee import MacroReview
        from app.shared.models import MacroData, MacroRegionalSnapshot

        try:
            # 1. MacroReview report_json (scores and deltas)
            review = (
                db.query(MacroReview)
                .filter(MacroReview.organization_id == organization_id)
                .order_by(MacroReview.created_at.desc())
                .first()
            )
            report_json = review.report_json if review and review.report_json else {}

            # 2. MacroRegionalSnapshot (dimensions breakdown per region)
            snapshot = (
                db.query(MacroRegionalSnapshot)
                .order_by(MacroRegionalSnapshot.as_of_date.desc())
                .first()
            )
            raw = snapshot.data_json if snapshot else {}
            snapshot_data = raw if isinstance(raw, dict) else {}

            # 3. Real FRED indicator values
            series_to_fetch = [
                "VIXCLS", "YIELD_CURVE_10Y2Y", "CPI_YOY", "DFF",
                "SAHMREALTIME", "BAMLH0A0HYM2", "BAMLHE00EHYIOAS", "BAMLEMCBPIOAS",
            ]
            fred_rows = db.execute(
                select(MacroData.series_id, MacroData.value, MacroData.obs_date)
                .where(MacroData.series_id.in_(series_to_fetch))
                .distinct(MacroData.series_id)
                .order_by(MacroData.series_id, MacroData.obs_date.desc())
            ).all()

            fred_values: dict[str, dict[str, Any]] = {}
            for series_id, value, obs_date in fred_rows:
                fred_values[series_id] = {
                    "value": float(value) if value is not None else None,
                    "obs_date": str(obs_date),
                }

            return {
                "report_json": report_json,
                "snapshot_data": snapshot_data,
                "fred_values": fred_values,
            }
        except Exception:
            logger.warning("gather_macro_context_failed", organization_id=organization_id)
            return {"report_json": {}, "snapshot_data": {}, "fred_values": {}}

    def _gather_vector_context(
        self,
        *,
        event_description: str,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve semantically relevant macro review chunks for the event."""
        if not event_description:
            return []

        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
        )

        try:
            embed_result = generate_embeddings([event_description])
            if not embed_result.vectors:
                return []
            return search_fund_analysis_sync(
                organization_id=organization_id,
                query_vector=embed_result.vectors[0],
                source_type="macro_review",
                top=10,
            )
        except Exception:
            logger.warning("vector_search_failed_for_flash_report")
            return []

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
        """Build user message from event context with real indicators."""
        parts: list[str] = []

        # ── Primary: Event description ────────────────────────────────────
        event = context.get("event_description", "Market event requiring analysis")
        parts.append(f"## EVENT\n{event}")

        # ── Secondary: Real economic indicators ──────────────────────────
        macro = context.get("macro_snapshot", {})
        fred = macro.get("fred_values", {})

        if fred:
            parts.append("\n## MARKET CONDITIONS AT EVENT TIME (Real Values)")

            vix = fred.get("VIXCLS", {})
            if vix.get("value") is not None:
                vix_interp = (
                    "elevated stress" if vix["value"] > 25
                    else "moderate caution" if vix["value"] > 18
                    else "complacency / low volatility"
                )
                parts.append(f"- VIX: {vix['value']:.1f} ({vix_interp})")

            yc = fred.get("YIELD_CURVE_10Y2Y", {})
            if yc.get("value") is not None:
                yc_interp = "inverted (recession signal)" if yc["value"] < 0 else "positive (normal)"
                parts.append(f"- Yield Curve 10Y-2Y: {yc['value']:+.2f}% ({yc_interp})")

            cpi = fred.get("CPI_YOY", {})
            if cpi.get("value") is not None:
                parts.append(f"- CPI YoY: {cpi['value']:.1f}%")

            dff = fred.get("DFF", {})
            if dff.get("value") is not None:
                parts.append(f"- Fed Funds Rate: {dff['value']:.2f}%")

            us_hy = fred.get("BAMLH0A0HYM2", {})
            if us_hy.get("value") is not None:
                us_hy_interp = "stress" if us_hy["value"] > 600 else "caution" if us_hy["value"] > 400 else "benign"
                parts.append(f"- US HY Spreads (OAS): {us_hy['value']:.0f}bps ({us_hy_interp})")

            eu_hy = fred.get("BAMLHE00EHYIOAS", {})
            if eu_hy.get("value") is not None:
                parts.append(f"- Euro HY Spreads (OAS): {eu_hy['value']:.0f}bps")

            em_oas = fred.get("BAMLEMCBPIOAS", {})
            if em_oas.get("value") is not None:
                parts.append(f"- EM Corp Spreads (OAS): {em_oas['value']:.0f}bps")

        # ── Regional scores ──────────────────────────────────────────────
        snapshot_data = macro.get("snapshot_data", {})
        regions = snapshot_data.get("regions", {})
        if regions:
            parts.append("\n## REGIONAL MACRO SCORES")
            for region in ("US", "EUROPE", "ASIA", "EM"):
                rdata = regions.get(region, {})
                score = rdata.get("composite_score")
                if score is not None:
                    parts.append(f"- {region}: {score:.1f}/100")

        # ── Score deltas ─────────────────────────────────────────────────
        report_json = macro.get("report_json", {})
        score_deltas = report_json.get("score_deltas", [])
        if score_deltas:
            parts.append("\n## WEEK-OVER-WEEK CHANGES")
            for sd in score_deltas:
                if isinstance(sd, dict):
                    delta = sd.get("delta", 0)
                    flagged = sd.get("flagged", False)
                    flag_marker = " !! MATERIAL" if flagged else ""
                    parts.append(
                        f"- {sd.get('region', '?')}: {delta:+.1f} pts{flag_marker}"
                    )

        # ── Historical context ───────────────────────────────────────────
        docs = context.get("documents", [])
        if docs:
            parts.append(f"\n## HISTORICAL MACRO CONTEXT ({len(docs)} prior analyses)")
            for i, doc in enumerate(docs[:10]):
                text = doc.get("content", doc.get("text", ""))[:1500]
                source = doc.get("source_type", doc.get("section", f"doc_{i}"))
                parts.append(f"\n### Prior Analysis [{source}]\n{text}")

        return "\n".join(parts)
