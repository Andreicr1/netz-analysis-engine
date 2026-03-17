"""Evidence Pack — frozen evidence surface for DD Report chapter generation.

Gathers fund identity, strategy documents, performance data, risk metrics,
fees, and manager profile into an immutable dataclass. Each chapter receives
a filtered view of the evidence pack.

Intentional improvement over credit's dict-based evidence: frozen dataclass
ensures thread safety and audit clarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """Immutable evidence surface for DD Report generation.

    Built once from DB + RAG retrieval + quant metrics, then passed
    to all chapters. Thread-safe for asyncio.to_thread().
    """

    # Fund identity
    instrument_id: str = ""
    fund_name: str = ""
    isin: str | None = None
    ticker: str | None = None
    fund_type: str | None = None
    geography: str | None = None
    asset_class: str | None = None
    manager_name: str | None = None
    currency: str | None = None
    domicile: str | None = None
    inception_date: str | None = None
    aum_usd: float | None = None

    # Retrieved documents (from RAG)
    documents: list[dict[str, Any]] = field(default_factory=list)

    # Quant metrics (from quant_engine)
    quant_profile: dict[str, Any] = field(default_factory=dict)

    # Risk metrics
    risk_metrics: dict[str, Any] = field(default_factory=dict)

    # Scoring data
    scoring_data: dict[str, Any] = field(default_factory=dict)

    # Macro context
    macro_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> dict[str, Any]:
        """Convert to template context dict for Jinja2 rendering."""
        return {
            "instrument_id": self.instrument_id,
            "fund_name": self.fund_name,
            "isin": self.isin,
            "ticker": self.ticker,
            "fund_type": self.fund_type,
            "geography": self.geography,
            "asset_class": self.asset_class,
            "manager_name": self.manager_name,
            "currency": self.currency,
            "domicile": self.domicile,
            "inception_date": self.inception_date,
            "aum_usd": self.aum_usd,
            "documents": self.documents,
            "quant_profile": self.quant_profile,
            "risk_metrics": self.risk_metrics,
            "scoring_data": self.scoring_data,
            "macro_snapshot": self.macro_snapshot,
        }

    def filter_for_chapter(self, chapter_tag: str) -> dict[str, Any]:
        """Return a filtered context dict for a specific chapter.

        Each chapter gets the full fund identity but only relevant
        evidence subsets to reduce token consumption.
        """
        ctx = self.to_context()

        # All chapters get fund identity
        # Filter documents by relevance to chapter
        if chapter_tag == "recommendation":
            # Recommendation gets no documents — synthesis only
            ctx["documents"] = []
        elif chapter_tag in ("performance_analysis", "risk_framework"):
            # Heavy quant chapters get full metrics
            pass
        elif chapter_tag == "fee_analysis":
            # Fee chapter gets document extracts but minimal quant
            ctx["quant_profile"] = {}
            ctx["risk_metrics"] = {}

        return ctx


def build_evidence_pack(
    *,
    fund_data: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
    quant_profile: dict[str, Any] | None = None,
    risk_metrics: dict[str, Any] | None = None,
    scoring_data: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
) -> EvidencePack:
    """Build a frozen evidence pack from gathered data.

    Parameters
    ----------
    fund_data : dict
        Fund identity fields from DB.
    documents : list[dict]
        RAG-retrieved document chunks.
    quant_profile : dict
        Quant engine metrics (CVaR, Sharpe, etc.).
    risk_metrics : dict
        Fund risk metrics from DB.
    scoring_data : dict
        Manager scoring data.
    macro_snapshot : dict
        Macro context (FRED indicators, regime).

    Returns
    -------
    EvidencePack
        Frozen, thread-safe evidence surface.
    """
    logger.info("building_evidence_pack", instrument_id=fund_data.get("instrument_id"))

    return EvidencePack(
        instrument_id=str(fund_data.get("instrument_id", "")),
        fund_name=fund_data.get("name", ""),
        isin=fund_data.get("isin"),
        ticker=fund_data.get("ticker"),
        fund_type=fund_data.get("fund_type"),
        geography=fund_data.get("geography"),
        asset_class=fund_data.get("asset_class"),
        manager_name=fund_data.get("manager_name"),
        currency=fund_data.get("currency"),
        domicile=fund_data.get("domicile"),
        inception_date=str(fund_data["inception_date"]) if fund_data.get("inception_date") else None,
        aum_usd=float(fund_data["aum_usd"]) if fund_data.get("aum_usd") else None,
        documents=documents or [],
        quant_profile=quant_profile or {},
        risk_metrics=risk_metrics or {},
        scoring_data=scoring_data or {},
        macro_snapshot=macro_snapshot or {},
    )
