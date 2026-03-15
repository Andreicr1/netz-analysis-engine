"""Pipeline monitoring and alert generation.

Implements run_pipeline_monitoring() — reads profiles and flags,
generates alerts for risk band changes, legal risks, target return drops,
and track record inconsistencies.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DealICBrief,
    DealIntelligenceProfile,
    DealRiskFlag,
    PipelineAlert,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal

logger = structlog.get_logger()


def _extract_target_return(anchors: list) -> str | None:
    """Extract target return percentage from knowledge anchors."""
    for anchor in anchors:
        if anchor.anchor_type in {"EFFECTIVE_DATE", "FUND_NAME", "PROVIDER_NAME"}:
            continue
        match = re.search(r"(\d{1,2}(?:\.\d{1,2})?\s?%)", anchor.anchor_value or "")
        if match:
            return match.group(1).replace(" ", "")
    return None


def _strategy_from_docs(doc_types: list[str]) -> str:
    """Infer investment strategy from document types."""
    normalized = " ".join(doc_types).lower()
    if "memo" in normalized:
        return "Direct Lending"
    if "marketing" in normalized:
        return "LP Investment"
    if "term sheet" in normalized:
        return "Equity SPV"
    return "GP Stakes"


def _risk_band_from_flags(flags: list[dict]) -> str:
    """Derive risk band from risk flags."""
    from vertical_engines.credit.pipeline.models import RISK_ORDER

    if not flags:
        return "MODERATE"
    max_sev = max((RISK_ORDER.get(f["severity"], 1) for f in flags), default=1)
    if max_sev <= 1:
        return "LOW"
    if max_sev == 2:
        return "MODERATE"
    high_count = sum(1 for f in flags if f["severity"] == "HIGH")
    return "SPECULATIVE" if high_count >= 2 else "HIGH"


def _infer_risk_flags_for_deal(
    deal: Deal,
    anchors: list,
    docs: list,
) -> list[dict]:
    """Infer risk flags from knowledge anchors and documents."""
    flags: list[dict] = []

    for anchor in anchors:
        value = (anchor.anchor_value or "").lower()
        snippet = anchor.source_snippet or anchor.anchor_value or ""
        source_document = anchor.page_reference or None

        if "liquidity" in value:
            flags.append({"risk_type": "LIQUIDITY", "severity": "MEDIUM", "reasoning": f"Liquidity signal detected: {snippet}", "source_document": source_document})
        if "legal" in value or "agreement" in value:
            flags.append({"risk_type": "LEGAL", "severity": "HIGH", "reasoning": f"Legal exposure indicator: {snippet}", "source_document": source_document})
        if "track" in value and "record" in value:
            flags.append({"risk_type": "TRACK_RECORD", "severity": "MEDIUM", "reasoning": f"Track record caveat: {snippet}", "source_document": source_document})
        if "leverage" in value:
            flags.append({"risk_type": "LEVERAGE", "severity": "HIGH", "reasoning": f"Leverage mention requires review: {snippet}", "source_document": source_document})
        if "concentration" in value:
            flags.append({"risk_type": "CONCENTRATION", "severity": "MEDIUM", "reasoning": f"Concentration signal: {snippet}", "source_document": source_document})

    if not flags:
        for doc in docs:
            if "Legal" in doc.doc_type:
                flags.append(
                    {
                        "risk_type": "LEGAL",
                        "severity": "MEDIUM",
                        "reasoning": "Legal draft detected in pipeline; review terms before IC.",
                        "source_document": str(doc.doc_id),
                    },
                )
                break

    return flags[:24]


def build_deal_intelligence_profiles(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DealIntelligenceProfile]:
    """DEPRECATED — DealIntelligenceProfile is now owned by deep_review.

    Retained as a no-op stub for backward compatibility.
    """
    return []


def build_ic_briefs(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DealICBrief]:
    """DEPRECATED — DealICBrief is now owned by deep_review.

    Retained as a no-op stub for backward compatibility.
    """
    return []


def run_pipeline_monitoring(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[PipelineAlert]:
    """Generate pipeline monitoring alerts."""
    alerts: list[PipelineAlert] = []

    deals = list(
        db.execute(
            select(Deal).where(
                Deal.fund_id == fund_id,
                Deal.deal_folder_path.is_not(None),
            ),
        ).scalars().all(),
    )

    all_profiles = list(
        db.execute(
            select(DealIntelligenceProfile).where(
                DealIntelligenceProfile.fund_id == fund_id,
            ),
        ).scalars().all(),
    )
    profiles_by_deal = {p.deal_id: p for p in all_profiles}

    all_flags = list(
        db.execute(
            select(DealRiskFlag).where(DealRiskFlag.fund_id == fund_id),
        ).scalars().all(),
    )
    flags_by_deal: dict[uuid.UUID, list[DealRiskFlag]] = defaultdict(list)
    for f in all_flags:
        flags_by_deal[f.deal_id].append(f)

    all_open_alerts = list(
        db.execute(
            select(PipelineAlert).where(
                PipelineAlert.fund_id == fund_id,
                PipelineAlert.resolved_flag.is_(False),
            ),
        ).scalars().all(),
    )
    open_alerts_set: set[tuple] = {
        (a.deal_id, a.alert_type) for a in all_open_alerts
    }

    for deal in deals:
        profile = profiles_by_deal.get(deal.id)
        flags = flags_by_deal.get(deal.id, [])

        new_alerts: list[tuple[str, str, str]] = []
        if profile and profile.risk_band in {"HIGH", "SPECULATIVE"}:
            new_alerts.append(("RISK_BAND_CHANGE", "HIGH", f"Risk band for {deal.deal_name or deal.title} is {profile.risk_band}."))

        legal_high = any(flag.risk_type == "LEGAL" and flag.severity == "HIGH" for flag in flags)
        if legal_high:
            new_alerts.append(("LEGAL_RISK_DETECTED", "HIGH", f"High legal risk detected for {deal.deal_name or deal.title}."))

        target_return_value = profile.target_return if profile and profile.target_return else None
        target_return_match = (
            re.search(r"(\d+(?:\.\d+)?)", target_return_value)
            if target_return_value
            else None
        )
        if target_return_match:
            value = float(target_return_match.group(1))
            if value < 8.0:
                new_alerts.append(("TARGET_RETURN_DROP", "MEDIUM", f"Target return dropped to {target_return_value} for {deal.deal_name or deal.title}."))

        track_record_flag = any(flag.risk_type == "TRACK_RECORD" and flag.severity in {"MEDIUM", "HIGH"} for flag in flags)
        if track_record_flag:
            new_alerts.append(("TRACK_RECORD_INCONSISTENCY", "MEDIUM", f"Track record inconsistency signal for {deal.deal_name or deal.title}."))

        for alert_type, severity, description in new_alerts:
            if (deal.id, alert_type) in open_alerts_set:
                continue
            alert = PipelineAlert(
                fund_id=fund_id,
                access_level="internal",
                deal_id=deal.id,
                alert_type=alert_type,
                severity=severity,
                description=description,
                resolved_flag=False,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(alert)
            db.flush()
            alerts.append(alert)

    db.commit()
    return alerts
