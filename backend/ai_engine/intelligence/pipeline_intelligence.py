from __future__ import annotations

import datetime as dt
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DealDocumentIntelligence,
    DealICBrief,
    DealIntelligenceProfile,
    DealRiskFlag,
    DocumentRegistry,
    KnowledgeAnchor,
    PipelineAlert,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal  # pipeline domain

PIPELINE_CONTAINER = "investment-pipeline-intelligence"

RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
RISK_BAND_ORDER = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "SPECULATIVE": 4}

DOC_TYPE_MAP: dict[str, tuple[str, int]] = {
    "INVESTMENT_MEMO": ("Investment Memo", 92),
    "DEAL_MARKETING": ("Marketing Deck", 82),
    "FUND_CONSTITUTIONAL": ("Legal Draft", 76),
    "SERVICE_PROVIDER_CONTRACT": ("Legal Draft", 84),
    "AUDIT_EVIDENCE": ("Due Diligence Report", 80),
    "REGULATORY_CIMA": ("Legal Draft", 70),
    "OTHER": ("Term Sheet", 60),
}


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _folder_from_blob(blob_path: str) -> str | None:
    parts = [p for p in (blob_path or "").split("/") if p]
    if not parts:
        return None
    return parts[0]


def discover_pipeline_deals(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> list[Deal]:
    now = _now_utc()
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PIPELINE_CONTAINER,
            )
        ).scalars().all()
    )

    grouped: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for doc in docs:
        folder = _folder_from_blob(doc.blob_path)
        if not folder:
            continue
        grouped[folder].append(doc)

    all_deals = {
        d.deal_folder_path: d
        for d in db.execute(
            select(Deal).where(Deal.fund_id == fund_id)
        ).scalars().all()
        if d.deal_folder_path
    }

    saved: list[Deal] = []
    for folder_name, folder_docs in grouped.items():
        folder_path = f"{PIPELINE_CONTAINER}/{folder_name}"
        existing = all_deals.get(folder_path)

        first_detected = min((d.last_ingested_at for d in folder_docs), default=now)
        last_updated = max((d.last_ingested_at for d in folder_docs), default=now)

        if existing is None:
            deal = Deal(
                fund_id=fund_id,
                access_level="internal",
                deal_name=folder_name,
                sponsor_name=folder_name,
                lifecycle_stage="SCREENING",
                first_detected_at=first_detected,
                last_updated_at=last_updated,
                deal_folder_path=folder_path,
                transition_target_container="portfolio-active-investments",
                intelligence_history={"authority": "INTELLIGENCE", "sourceContainer": PIPELINE_CONTAINER},
                title=folder_name,
                borrower_name=folder_name,
                stage="SCREENING",
                is_archived=False,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(deal)
            db.flush()
            saved.append(deal)
            continue

        existing.deal_name = folder_name
        existing.sponsor_name = folder_name
        normalized_stage = existing.lifecycle_stage or existing.stage or "SCREENING"
        existing.lifecycle_stage = normalized_stage
        existing.stage = normalized_stage
        existing.last_updated_at = last_updated
        existing.deal_folder_path = folder_path
        existing.transition_target_container = existing.transition_target_container or "portfolio-active-investments"
        existing.intelligence_history = existing.intelligence_history or {"authority": "INTELLIGENCE", "sourceContainer": PIPELINE_CONTAINER}
        existing.updated_by = actor_id
        db.flush()
        saved.append(existing)

    db.commit()
    return saved


def aggregate_deal_documents(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> list[DealDocumentIntelligence]:
    deals = list(db.execute(select(Deal).where(Deal.fund_id == fund_id, Deal.deal_folder_path.is_not(None))).scalars().all())
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PIPELINE_CONTAINER,
            )
        ).scalars().all()
    )

    all_ddi = list(
        db.execute(
            select(DealDocumentIntelligence).where(
                DealDocumentIntelligence.fund_id == fund_id,
            )
        ).scalars().all()
    )
    ddi_lookup: dict[tuple, DealDocumentIntelligence] = {
        (row.deal_id, row.doc_id): row for row in all_ddi
    }

    docs_by_folder: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for d in docs:
        folder = _folder_from_blob(d.blob_path or "")
        if folder:
            docs_by_folder[folder.lower()].append(d)

    saved: list[DealDocumentIntelligence] = []
    for deal in deals:
        folder_name = (deal.deal_name or "").strip().lower()
        matched_docs = docs_by_folder.get(folder_name, [])

        for doc in matched_docs:
            doc_type, confidence = DOC_TYPE_MAP.get(doc.detected_doc_type or "OTHER", ("Term Sheet", 60))
            existing = ddi_lookup.get((deal.id, doc.id))

            payload = {
                "fund_id": fund_id,
                "access_level": "internal",
                "deal_id": deal.id,
                "doc_id": doc.id,
                "doc_type": doc_type,
                "confidence_score": int(confidence),
                "created_by": actor_id,
                "updated_by": actor_id,
            }

            if existing is None:
                row = DealDocumentIntelligence(**payload)
                db.add(row)
                db.flush()
            else:
                for key, value in payload.items():
                    if key == "created_by":
                        continue
                    setattr(existing, key, value)
                db.flush()
                row = existing
            saved.append(row)

    db.commit()
    return saved


def _extract_target_return(anchors: list[KnowledgeAnchor]) -> str | None:
    for anchor in anchors:
        if anchor.anchor_type in {"EFFECTIVE_DATE", "FUND_NAME", "PROVIDER_NAME"}:
            continue
        match = re.search(r"(\d{1,2}(?:\.\d{1,2})?\s?%)", anchor.anchor_value or "")
        if match:
            return match.group(1).replace(" ", "")
    return None


def _strategy_from_docs(doc_types: list[str]) -> str:
    normalized = " ".join(doc_types).lower()
    if "memo" in normalized:
        return "Direct Lending"
    if "marketing" in normalized:
        return "LP Investment"
    if "term sheet" in normalized:
        return "Equity SPV"
    return "GP Stakes"


def _risk_band_from_flags(flags: list[dict]) -> str:
    if not flags:
        return "MODERATE"
    max_sev = max((RISK_ORDER.get(f["severity"], 1) for f in flags), default=1)
    if max_sev <= 1:
        return "LOW"
    if max_sev == 2:
        return "MODERATE"
    high_count = sum(1 for f in flags if f["severity"] == "HIGH")
    return "SPECULATIVE" if high_count >= 2 else "HIGH"


def _infer_risk_flags_for_deal(deal: Deal, anchors: list[KnowledgeAnchor], docs: list[DealDocumentIntelligence]) -> list[dict]:
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
                    }
                )
                break

    return flags[:24]


# ── OWNERSHIP BOUNDARY ────────────────────────────────────────────
# REFACTOR (Phase 1, Step 3): build_deal_intelligence_profiles() REMOVED.
#
# DealIntelligenceProfile, DealRiskFlag, DealICBrief are now exclusively
# owned and written by deep_review.py.  This module retains ONLY:
#   • discover_pipeline_deals()   — deal registration from blob folders
#   • aggregate_deal_documents()  — document intelligence mapping
#   • run_pipeline_monitoring()   — alert generation (reads profiles, never writes)
#   • run_pipeline_ingest()       — orchestrator for above
#
# The heuristic helpers (_extract_target_return, _strategy_from_docs, etc.)
# are preserved as they may be used by monitoring or future engines.
# ──────────────────────────────────────────────────────────────────


def build_deal_intelligence_profiles(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> list[DealIntelligenceProfile]:
    """DEPRECATED — DealIntelligenceProfile is now owned by deep_review.

    Retained as a no-op stub for backward compatibility.
    """
    return []


def build_ic_briefs(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> list[DealICBrief]:
    """DEPRECATED — DealICBrief is now owned by deep_review.

    Retained as a no-op stub for backward compatibility.
    """
    return []


def run_pipeline_monitoring(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> list[PipelineAlert]:
    alerts: list[PipelineAlert] = []

    deals = list(db.execute(select(Deal).where(Deal.fund_id == fund_id, Deal.deal_folder_path.is_not(None))).scalars().all())

    all_profiles = list(
        db.execute(
            select(DealIntelligenceProfile).where(DealIntelligenceProfile.fund_id == fund_id)
        ).scalars().all()
    )
    profiles_by_deal = {p.deal_id: p for p in all_profiles}

    all_flags = list(
        db.execute(
            select(DealRiskFlag).where(DealRiskFlag.fund_id == fund_id)
        ).scalars().all()
    )
    flags_by_deal: dict[uuid.UUID, list[DealRiskFlag]] = defaultdict(list)
    for f in all_flags:
        flags_by_deal[f.deal_id].append(f)

    all_open_alerts = list(
        db.execute(
            select(PipelineAlert).where(
                PipelineAlert.fund_id == fund_id,
                PipelineAlert.resolved_flag.is_(False),
            )
        ).scalars().all()
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


def run_pipeline_ingest(db: Session, *, fund_id: uuid.UUID, actor_id: str = "ai-engine") -> dict[str, int | str]:
    deals = discover_pipeline_deals(db, fund_id=fund_id, actor_id=actor_id)
    deal_docs = aggregate_deal_documents(db, fund_id=fund_id, actor_id=actor_id)
    profiles = build_deal_intelligence_profiles(db, fund_id=fund_id, actor_id=actor_id)
    briefs = build_ic_briefs(db, fund_id=fund_id, actor_id=actor_id)
    alerts = run_pipeline_monitoring(db, fund_id=fund_id, actor_id=actor_id)

    return {
        "asOf": _now_utc().isoformat(),
        "deals": len(deals),
        "dealDocuments": len(deal_docs),
        "profiles": len(profiles),
        "briefs": len(briefs),
        "alerts": len(alerts),
    }
