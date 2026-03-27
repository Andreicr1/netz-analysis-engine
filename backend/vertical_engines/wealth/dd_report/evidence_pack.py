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

# Per-chapter field expectations: which fields each chapter needs,
# which data providers supply them, and the primary provider.
_CHAPTER_FIELD_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "fee_analysis": {
        "fields": ["fund_name", "fund_type", "currency"],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    "investment_strategy": {
        "fields": [
            "fund_name", "fund_type", "geography", "asset_class",
            "holdings_source",
            "nport_available", "nport_sector_weights", "nport_asset_allocation",
            "thirteenf_available", "sector_weights",
        ],
        "providers": ["YFinance", "SEC EDGAR N-PORT", "SEC EDGAR 13F"],
        "primary_provider": "SEC EDGAR N-PORT",
    },
    "operational_dd": {
        "fields": ["fund_name", "manager_name", "domicile", "compliance_disclosures"],
        "providers": ["YFinance", "SEC EDGAR ADV"],
        "primary_provider": "YFinance",
    },
    "manager_assessment": {
        # ADV fields for firm context; N-PORT fund_style for fund-level context
        "fields": [
            "fund_name", "manager_name",
            "adv_aum_history", "adv_compliance_disclosures", "adv_team",
            "adv_brochure_sections",
            "nport_available", "fund_style",
        ],
        "providers": ["YFinance", "SEC EDGAR ADV", "SEC EDGAR N-PORT"],
        "primary_provider": "SEC EDGAR ADV",
    },
    "performance_analysis": {
        "fields": [
            "quant_profile.sharpe_1y", "quant_profile.return_1y",
            "quant_profile.return_3m", "quant_profile.return_1m",
            "quant_profile.cvar_95_3m", "quant_profile.max_drawdown_1y",
        ],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    "risk_framework": {
        "fields": [
            "quant_profile.cvar_95_1m", "quant_profile.cvar_95_3m",
            "quant_profile.cvar_95_12m", "quant_profile.volatility_1y",
            "quant_profile.beta_1y",
            "risk_metrics",
        ],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    "executive_summary": {
        "fields": [
            "fund_name", "fund_type", "geography", "asset_class",
            "quant_profile.sharpe_1y", "quant_profile.return_1y",
            "quant_profile.cvar_95_3m",
        ],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    "recommendation": {
        # Synthesis chapter — needs identity + quant + risk
        "fields": [
            "fund_name", "fund_type",
            "quant_profile.sharpe_1y", "quant_profile.return_1y",
            "quant_profile.cvar_95_3m",
            "risk_metrics",
        ],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
}


def _resolve_field(pack: EvidencePack, field_path: str) -> Any:
    """Resolve a dotted field path against the evidence pack.

    Supports top-level attributes and one-level dict nesting:
      "fund_name"              → pack.fund_name
      "quant_profile.sharpe_1y" → pack.quant_profile.get("sharpe_1y")
      "risk_metrics"           → pack.risk_metrics (checks non-empty dict)
    """
    if "." in field_path:
        parent, child = field_path.split(".", 1)
        parent_val = getattr(pack, parent, None)
        if isinstance(parent_val, dict):
            return parent_val.get(child)
        return None
    return getattr(pack, field_path, None)


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

    # Holdings source resolution (DisclosureMatrix-aware)
    holdings_source: str | None = None  # "nport" | "13f" | None

    # SEC N-PORT data — fund-level (investment_strategy + manager_assessment)
    nport_available: bool = False
    nport_holdings_count: int = 0
    nport_sector_weights: dict[str, float] = field(default_factory=dict)
    nport_asset_allocation: dict[str, float] = field(default_factory=dict)
    nport_top_holdings: list[dict[str, Any]] = field(default_factory=list)
    nport_report_date: str | None = None
    fund_style: dict[str, Any] = field(default_factory=dict)
    fund_style_drift_detected: bool = False

    # SEC 13F data — firm-level overlay (supplementary context)
    thirteenf_available: bool = False
    sector_weights: dict[str, float] = field(default_factory=dict)
    drift_detected: bool = False
    drift_quarters: int = 0

    # SEC ADV data (manager_assessment + operational_dd chapters)
    compliance_disclosures: int | None = None
    adv_aum_history: dict[str, Any] = field(default_factory=dict)
    adv_fee_structure: list[str] = field(default_factory=list)
    adv_funds: list[dict[str, Any]] = field(default_factory=list)
    adv_team: list[dict[str, Any]] = field(default_factory=list)
    adv_brochure_sections: dict[str, str] = field(default_factory=dict)

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
            "holdings_source": self.holdings_source,
            "nport_available": self.nport_available,
            "nport_holdings_count": self.nport_holdings_count,
            "nport_sector_weights": self.nport_sector_weights,
            "nport_asset_allocation": self.nport_asset_allocation,
            "nport_top_holdings": self.nport_top_holdings,
            "nport_report_date": self.nport_report_date,
            "fund_style": self.fund_style,
            "fund_style_drift_detected": self.fund_style_drift_detected,
            "thirteenf_available": self.thirteenf_available,
            "sector_weights": self.sector_weights,
            "drift_detected": self.drift_detected,
            "drift_quarters": self.drift_quarters,
            "compliance_disclosures": self.compliance_disclosures,
            "adv_aum_history": self.adv_aum_history,
            "adv_fee_structure": self.adv_fee_structure,
            "adv_funds": self.adv_funds,
            "adv_team": self.adv_team,
            "adv_brochure_sections": self.adv_brochure_sections,
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

    def compute_source_metadata(self, chapter_tag: str) -> dict[str, Any]:
        """Compute data availability metadata for a chapter.

        Returns structured info about which fields are present/missing
        so templates can render source-aware preambles instead of hedging.
        """
        expectations = _CHAPTER_FIELD_EXPECTATIONS.get(chapter_tag, {})
        expected_fields: list[str] = expectations.get("fields", [])
        primary_provider: str = expectations.get("primary_provider", "YFinance")
        providers: list[str] = list(expectations.get("providers", ["YFinance"]))

        if not expected_fields:
            return {
                "structured_data_complete": False,
                "structured_data_partial": False,
                "structured_data_absent": True,
                "data_providers": providers,
                "available_fields": [],
                "missing_fields": [],
                "primary_provider": primary_provider,
            }

        available: list[str] = []
        missing: list[str] = []

        for f in expected_fields:
            val = _resolve_field(self, f)
            if val is not None and val != "" and val != {} and val != []:
                available.append(f)
            else:
                missing.append(f)

        all_present = len(missing) == 0
        none_present = len(available) == 0

        return {
            "structured_data_complete": all_present,
            "structured_data_partial": not all_present and not none_present,
            "structured_data_absent": none_present,
            "data_providers": providers,
            "available_fields": available,
            "missing_fields": missing,
            "primary_provider": primary_provider,
        }


def build_evidence_pack(
    *,
    fund_data: dict[str, Any],
    documents: list[dict[str, Any]] | None = None,
    quant_profile: dict[str, Any] | None = None,
    risk_metrics: dict[str, Any] | None = None,
    scoring_data: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
    sec_13f_data: dict[str, Any] | None = None,
    sec_nport_data: dict[str, Any] | None = None,
    sec_adv_data: dict[str, Any] | None = None,
    adv_brochure_sections: dict[str, str] | None = None,
    holdings_source: str | None = None,
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
    sec_13f_data : dict
        SEC 13F holdings data (sector weights, drift) — firm-level overlay.
    sec_nport_data : dict
        SEC N-PORT fund-level holdings (sector weights, asset allocation, top holdings).
    sec_adv_data : dict
        SEC ADV manager profile data (AUM, compliance, team).
    adv_brochure_sections : dict
        ADV Part 2A brochure narrative sections.
    holdings_source : str | None
        "nport" for registered funds, None for private/UCITS.

    Returns
    -------
    EvidencePack
        Frozen, thread-safe evidence surface.

    """
    logger.info("building_evidence_pack", instrument_id=fund_data.get("instrument_id"))

    _13f = sec_13f_data or {}
    _nport = sec_nport_data or {}
    _adv = sec_adv_data or {}

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
        # Holdings source resolution
        holdings_source=holdings_source,
        # SEC N-PORT (fund-level)
        nport_available=bool(_nport),
        nport_holdings_count=_nport.get("holdings_count", 0),
        nport_sector_weights=_nport.get("sector_weights", {}),
        nport_asset_allocation=_nport.get("asset_allocation", {}),
        nport_top_holdings=_nport.get("top_holdings", []),
        nport_report_date=_nport.get("report_date"),
        fund_style=_nport.get("fund_style", {}),
        fund_style_drift_detected=_nport.get("style_drift_detected", False),
        # SEC 13F (firm-level overlay)
        thirteenf_available=_13f.get("thirteenf_available", False),
        sector_weights=_13f.get("sector_weights", {}),
        drift_detected=_13f.get("drift_detected", False),
        drift_quarters=_13f.get("drift_quarters", 0),
        # SEC ADV
        compliance_disclosures=_adv.get("compliance_disclosures"),
        adv_aum_history=_adv.get("adv_aum_history", {}),
        adv_fee_structure=_adv.get("adv_fee_structure", []),
        adv_funds=_adv.get("adv_funds", []),
        adv_team=_adv.get("adv_team", []),
        adv_brochure_sections=adv_brochure_sections or {},
    )
