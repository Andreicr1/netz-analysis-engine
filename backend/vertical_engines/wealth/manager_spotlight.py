"""Manager Spotlight — deep-dive on single fund manager.

Standalone content production file (not a package). Uses DD Report data +
quant metrics + peer comparison for comprehensive manager analysis.

Usage (from async route via asyncio.to_thread)::

    engine = ManagerSpotlight(config=config, call_openai_fn=call_fn)
    result = engine.generate(db, fund_id=fund_id, organization_id=org_id, actor_id=user_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ai_engine.governance.output_safety import sanitize_llm_text
from ai_engine.prompts.registry import get_prompt_registry
from vertical_engines.wealth.dd_report.quant_injection import (
    gather_quant_metrics,
    gather_risk_metrics,
)
from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language
from vertical_engines.wealth.shared_protocols import CallOpenAiFn

logger = structlog.get_logger()

_TEMPLATE = "content/manager_spotlight.j2"
_MAX_TOKENS = 4000


@dataclass(frozen=True, slots=True)
class SpotlightResult:
    """Result of manager spotlight generation."""

    content_md: str | None
    title: str
    language: Language
    instrument_id: str
    status: str  # completed | failed
    error: str | None = None


class ManagerSpotlight:
    """Generates deep-dive manager spotlight reports."""

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
        instrument_id: str,
        organization_id: str,
        actor_id: str,
        language: Language = "pt",
    ) -> SpotlightResult:
        """Generate manager spotlight. Never raises — returns result with status.

        Designed to run inside asyncio.to_thread().
        """
        labels = LABELS[language]
        title = labels["manager_spotlight_title"]

        if not self._call_openai_fn:
            return SpotlightResult(
                content_md=None, title=title, language=language,
                instrument_id=instrument_id, status="failed",
                error="No LLM call function provided",
            )

        try:
            fund_data = self._gather_fund_data(db, instrument_id, organization_id)
            quant_profile = gather_quant_metrics(db, instrument_id=instrument_id, organization_id=organization_id)
            risk_metrics = gather_risk_metrics(db, instrument_id=instrument_id, organization_id=organization_id)

            # ── Vector search (firm context + org-scoped analysis) ────
            documents = self._gather_vector_context(
                fund_data=fund_data,
                instrument_id=instrument_id,
                organization_id=organization_id,
            )

            content_md = self._generate_narrative(
                fund_data=fund_data,
                quant_profile=quant_profile,
                risk_metrics=risk_metrics,
                documents=documents,
                language=language,
            )

            logger.info(
                "manager_spotlight_generated",
                instrument_id=instrument_id,
                organization_id=organization_id,
                language=language,
                content_length=len(content_md) if content_md else 0,
            )

            return SpotlightResult(
                content_md=content_md, title=title,
                language=language, instrument_id=instrument_id,
                status="completed",
            )
        except Exception as exc:
            logger.exception("manager_spotlight_failed", instrument_id=instrument_id)
            return SpotlightResult(
                content_md=None, title=title, language=language,
                instrument_id=instrument_id, status="failed", error=str(exc),
            )

    def render_pdf(self, content_md: str, *, language: Language = "pt", fund_name: str = "") -> BytesIO:
        """Render manager spotlight content as PDF."""
        from vertical_engines.wealth.content_pdf import render_content_pdf

        labels = LABELS[language]
        return render_content_pdf(
            content_md,
            title=labels["manager_spotlight_title"],
            subtitle=fund_name or "Fund Manager Analysis",
            language=language,
        )

    def _gather_fund_data(self, db: Session, instrument_id: str, organization_id: str) -> dict[str, Any]:
        """Gather fund identity from instruments_universe."""
        from app.domains.wealth.models.instrument import Instrument

        instrument = (
            db.query(Instrument)
            .filter(
                Instrument.instrument_id == instrument_id,
                Instrument.organization_id == organization_id,
            )
            .first()
        )
        if not instrument:
            return {"instrument_id": instrument_id, "name": "Unknown Fund"}

        attrs = instrument.attributes or {}
        fund_data: dict[str, Any] = {
            "instrument_id": str(instrument.instrument_id),
            "name": instrument.name,
            "isin": instrument.isin,
            "ticker": instrument.ticker,
            "fund_type": attrs.get("fund_type") or instrument.asset_class,
            "geography": instrument.geography,
            "asset_class": instrument.asset_class,
            "manager_name": attrs.get("manager_name"),
            "currency": instrument.currency,
            "domicile": attrs.get("domicile"),
            "inception_date": attrs.get("inception_date"),
            "aum_usd": float(attrs["aum_usd"]) if attrs.get("aum_usd") else None,
            "sec_crd": attrs.get("sec_crd"),
        }

        # Enrich with SEC fund data if available
        fund_cik = attrs.get("sec_cik")
        if fund_cik:
            from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

            enrichment = gather_fund_enrichment(
                db, fund_cik=fund_cik, sec_universe=attrs.get("sec_universe"),
            )
            if enrichment.get("enrichment_available"):
                fund_data["strategy_label"] = enrichment.get("strategy_label")
                share_classes = enrichment.get("share_classes", [])
                if share_classes:
                    fund_data["expense_ratio_pct"] = share_classes[0].get("expense_ratio_pct")
                fund_data["classification"] = enrichment.get("classification", {})

        return fund_data

    def _gather_vector_context(
        self,
        *,
        fund_data: dict[str, Any],
        instrument_id: str,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve firm context + fund analysis chunks from pgvector."""
        from ai_engine.extraction.embedding_service import generate_embeddings
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
            search_fund_firm_context_sync,
        )

        try:
            query_text = "investment philosophy strategy risk management team"
            embed_result = generate_embeddings([query_text])
            if not embed_result.vectors:
                return []

            qvec = embed_result.vectors[0]
            sec_crd = fund_data.get("sec_crd")

            firm_chunks = search_fund_firm_context_sync(
                query_vector=qvec,
                sec_crd=sec_crd or None,
                top=15,
            )
            analysis_chunks = search_fund_analysis_sync(
                organization_id=organization_id,
                query_vector=qvec,
                instrument_id=instrument_id,
                top=10,
            )
            return firm_chunks + analysis_chunks
        except Exception:
            logger.warning("vector_search_failed_for_spotlight", instrument_id=instrument_id)
            return []

    def _generate_narrative(
        self,
        *,
        fund_data: dict[str, Any],
        quant_profile: dict[str, Any],
        risk_metrics: dict[str, Any],
        documents: list[dict[str, Any]] | None = None,
        language: Language,
    ) -> str | None:
        """Generate LLM narrative for manager spotlight."""
        assert self._call_openai_fn is not None

        labels = LABELS[language]
        registry = get_prompt_registry()

        ctx = {
            "language": language,
            "fund_overview_label": labels["fund_overview"],
            "quant_analysis_label": labels["quant_analysis"],
            "peer_comparison_label": labels["peer_comparison"],
            "key_risks_label": labels["key_risks"],
        }

        if registry.has_template(_TEMPLATE):
            system_prompt = registry.render(_TEMPLATE, **ctx)
        else:
            system_prompt = (
                "You are a senior fund analyst. Write a deep-dive Manager Spotlight "
                "report on the specified fund manager."
            )

        user_content = self._build_user_content(fund_data, quant_profile, risk_metrics, documents or [])

        response = self._call_openai_fn(
            system_prompt, user_content, max_tokens=_MAX_TOKENS,
        )

        raw = response.get("content") or response.get("text") or ""
        return sanitize_llm_text(raw) if raw else None

    def _build_user_content(
        self,
        fund_data: dict[str, Any],
        quant_profile: dict[str, Any],
        risk_metrics: dict[str, Any],
        documents: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build user message from fund data + quant metrics + documents."""
        parts: list[str] = []

        parts.append("## Fund Identity")
        parts.append(f"- Name: {fund_data.get('name', 'Unknown')}")
        if fund_data.get("isin"):
            parts.append(f"- ISIN: {fund_data['isin']}")
        if fund_data.get("manager_name"):
            parts.append(f"- Manager: {fund_data['manager_name']}")
        if fund_data.get("fund_type"):
            parts.append(f"- Type: {fund_data['fund_type']}")
        if fund_data.get("geography"):
            parts.append(f"- Geography: {fund_data['geography']}")
        if fund_data.get("asset_class"):
            parts.append(f"- Asset Class: {fund_data['asset_class']}")
        if fund_data.get("aum_usd"):
            parts.append(f"- AUM (USD): {fund_data['aum_usd']:,.0f}")
        if fund_data.get("strategy_label"):
            parts.append(f"- Strategy: {fund_data['strategy_label']}")
        if fund_data.get("expense_ratio_pct") is not None:
            parts.append(f"- Expense Ratio: {fund_data['expense_ratio_pct']}%")
        classification = fund_data.get("classification", {})
        flags = [k for k, v in classification.items() if v]
        if flags:
            parts.append(f"- Fund Flags: {', '.join(flags)}")

        if quant_profile:
            parts.append("\n## Quantitative Metrics")
            for key, val in quant_profile.items():
                if val is not None and key != "score_components":
                    parts.append(f"- {key}: {val}")

        if risk_metrics:
            parts.append("\n## Risk Metrics")
            for key, val in risk_metrics.items():
                if val is not None:
                    parts.append(f"- {key}: {val}")

        if documents:
            parts.append(f"\n## Document Evidence ({len(documents)} chunks)")
            for i, doc in enumerate(documents[:20]):
                text = doc.get("content", doc.get("text", ""))[:2000]
                source = doc.get("source_type", doc.get("section", f"doc_{i}"))
                parts.append(f"\n### [{source}]\n{text}")

        return "\n".join(parts)
