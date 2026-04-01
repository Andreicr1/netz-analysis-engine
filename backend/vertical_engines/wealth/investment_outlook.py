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
        """Render investment outlook content as PDF (ReportLab, sync)."""
        from vertical_engines.wealth.content_pdf import render_content_pdf

        labels = LABELS[language]
        return render_content_pdf(
            content_md,
            title=labels["investment_outlook_title"],
            language=language,
        )

    async def render_pdf_async(self, content_md: str, *, language: Language = "pt") -> bytes:
        """Render investment outlook content as PDF via Playwright (async)."""
        from vertical_engines.wealth.pdf.html_renderer import html_to_pdf
        from vertical_engines.wealth.pdf.templates.content_report import render_content_report

        labels = LABELS[language]
        html_str = render_content_report(
            content_md,
            title=labels["investment_outlook_title"],
            language=language,
        )
        return await html_to_pdf(html_str, print_background=True)

    def _gather_macro_data(self, db: Session, organization_id: str) -> dict[str, Any]:
        """Gather latest macro snapshot + real indicator values for outlook generation."""
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

            # 3. Real FRED indicator values (absolute numbers)
            series_to_fetch = [
                "VIXCLS",             # VIX (volatility)
                "YIELD_CURVE_10Y2Y",  # Yield curve 10Y-2Y spread
                "CPI_YOY",           # CPI year-over-year
                "DFF",               # Fed Funds rate
                "SAHMREALTIME",      # Sahm rule (recession)
                "BAMLH0A0HYM2",      # US HY OAS (credit spreads)
                "BAMLHE00EHYIOAS",   # Euro HY OAS
                "BAMLEMCBPIOAS",     # EM Corp OAS
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
            logger.warning("gather_macro_data_failed", organization_id=organization_id)
            return {"report_json": {}, "snapshot_data": {}, "fred_values": {}}

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
        """Build rich user message with real indicators, scores, and dimensions."""
        report_json = macro_data.get("report_json", {})
        snapshot_data = macro_data.get("snapshot_data", {})
        fred = macro_data.get("fred_values", {})
        parts: list[str] = []

        # ── Section 1: Real economic indicators ───────────────────────────
        parts.append("## MARKET CONDITIONS (Real Values)")

        vix = fred.get("VIXCLS", {})
        yc = fred.get("YIELD_CURVE_10Y2Y", {})
        cpi = fred.get("CPI_YOY", {})
        dff = fred.get("DFF", {})
        sahm = fred.get("SAHMREALTIME", {})
        us_hy = fred.get("BAMLH0A0HYM2", {})
        eu_hy = fred.get("BAMLHE00EHYIOAS", {})
        em_oas = fred.get("BAMLEMCBPIOAS", {})

        if vix.get("value") is not None:
            vix_interp = (
                "elevated stress" if vix["value"] > 25
                else "moderate caution" if vix["value"] > 18
                else "complacency / low volatility"
            )
            parts.append(f"- VIX: {vix['value']:.1f} ({vix_interp})")

        if yc.get("value") is not None:
            yc_interp = "inverted (recession signal)" if yc["value"] < 0 else "positive (normal)"
            parts.append(f"- Yield Curve 10Y-2Y: {yc['value']:+.2f}% ({yc_interp})")

        if cpi.get("value") is not None:
            cpi_interp = (
                "well above target (hawkish risk)" if cpi["value"] > 3.5
                else "above target (Fed vigilant)" if cpi["value"] > 2.5
                else "near target (easing possible)"
            )
            parts.append(f"- CPI YoY: {cpi['value']:.1f}% ({cpi_interp})")

        if dff.get("value") is not None:
            parts.append(f"- Fed Funds Rate: {dff['value']:.2f}%")

        if sahm.get("value") is not None:
            sahm_interp = (
                "recession triggered" if sahm["value"] >= 0.5
                else f"{sahm['value']:.2f} (below threshold)"
            )
            parts.append(f"- Sahm Rule: {sahm_interp}")

        if us_hy.get("value") is not None:
            us_hy_interp = "stress" if us_hy["value"] > 600 else "caution" if us_hy["value"] > 400 else "benign"
            parts.append(f"- US HY Spreads (OAS): {us_hy['value']:.0f}bps ({us_hy_interp})")

        if eu_hy.get("value") is not None:
            parts.append(f"- Euro HY Spreads (OAS): {eu_hy['value']:.0f}bps")

        if em_oas.get("value") is not None:
            parts.append(f"- EM Corp Spreads (OAS): {em_oas['value']:.0f}bps")

        # ── Section 2: Regional scores with dimensions ────────────────────
        parts.append(
            "\n## REGIONAL MACRO SCORES "
            "(0-100 scale: <30=deteriorating, 30-45=caution, "
            "45-55=neutral, 55-70=expansion, >70=overheating)"
        )

        regions = snapshot_data.get("regions", {})
        for region in ("US", "EUROPE", "ASIA", "EM"):
            rdata = regions.get(region, {})
            score = rdata.get("composite_score")
            if score is None:
                continue
            parts.append(f"\n### {region}: {score:.1f}/100")
            dims = rdata.get("dimensions", {})
            for dim_name, dim_data in dims.items():
                if isinstance(dim_data, dict):
                    dim_score = dim_data.get("score")
                    if dim_score is not None:
                        parts.append(f"  - {dim_name.replace('_', ' ').title()}: {dim_score:.0f}/100")

        # ── Section 3: Week-over-week material changes ────────────────────
        score_deltas = report_json.get("score_deltas", [])
        if score_deltas:
            parts.append("\n## WEEK-OVER-WEEK CHANGES")
            for sd in score_deltas:
                if isinstance(sd, dict):
                    delta = sd.get("delta", 0)
                    flagged = sd.get("flagged", False)
                    flag_marker = " !! MATERIAL" if flagged else ""
                    prev = sd.get("previous_score", "?")
                    curr = sd.get("current_score", "?")
                    prev_str = f"{prev:.1f}" if isinstance(prev, (int, float)) else str(prev)
                    curr_str = f"{curr:.1f}" if isinstance(curr, (int, float)) else str(curr)
                    parts.append(
                        f"- {sd.get('region', '?')}: {delta:+.1f} pts "
                        f"({prev_str} -> {curr_str})"
                        f"{flag_marker}"
                    )

        # ── Section 4: Global stress indicators ──────────────────────────
        gi = report_json.get("global_indicators_delta") or snapshot_data.get("global_indicators", {})
        if gi:
            parts.append("\n## GLOBAL STRESS INDICATORS")
            label_map = {
                "geopolitical_risk_score": "Geopolitical Risk",
                "energy_stress": "Energy Stress",
                "commodity_stress": "Commodity Stress",
                "usd_strength": "USD Strength",
            }
            for key, label in label_map.items():
                val = gi.get(key)
                if val is not None:
                    parts.append(f"- {label}: {val:+.2f}")

        # ── Section 5: Historical context (vector search) ─────────────────
        if documents:
            parts.append(f"\n## HISTORICAL MACRO CONTEXT ({len(documents)} prior analyses)")
            for i, doc in enumerate(documents[:10]):
                text = doc.get("content", doc.get("text", ""))[:1500]
                source = doc.get("source_type", doc.get("section", f"doc_{i}"))
                parts.append(f"\n### Prior Analysis [{source}]\n{text}")

        return "\n".join(parts)
