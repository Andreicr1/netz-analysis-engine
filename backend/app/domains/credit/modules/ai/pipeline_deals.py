"""AI Pipeline Deals sub-router — list, detail, alerts."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.clerk_auth import Actor, require_roles
from app.domains.credit.modules.ai._helpers import (
    _limit,
    _normalize_chapter_content,
    _offset,
    _utcnow,
)
from app.domains.credit.modules.ai.models import (
    DealDocumentIntelligence,
    DealICBrief,
    DealIntelligenceProfile,
    DealRiskFlag,
    DealUnderwritingArtifact,
    DocumentRegistry,
    MacroSnapshot,
    PipelineAlert,
)
from app.domains.credit.modules.ai.schemas import (
    PipelineAlertOut,
    PipelineAlertsResponse,
    PipelineDealDetailResponse,
    PipelineDealItem,
    PipelineDealsResponse,
    PipelineICBriefOut,
    PipelineRiskFlagOut,
    UnderwritingArtifactOut,
)
from app.domains.credit.modules.deals.models import Deal
from app.shared.enums import Role

router = APIRouter()


@router.get("/pipeline/deals", response_model=PipelineDealsResponse)
def list_pipeline_deals(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PipelineDealsResponse:
    deals = list(
        db.execute(
            select(Deal)
            .where(Deal.fund_id == fund_id)
            .order_by(Deal.last_updated_at.desc().nullslast(), Deal.updated_at.desc())
            .limit(limit)
            .offset(offset),
        ).scalars().all(),
    )
    deal_ids = [d.id for d in deals]

    profiles = list(db.execute(select(DealIntelligenceProfile).where(DealIntelligenceProfile.fund_id == fund_id, DealIntelligenceProfile.deal_id.in_(deal_ids))).scalars().all()) if deal_ids else []
    by_deal = {profile.deal_id: profile for profile in profiles}

    briefs = list(db.execute(select(DealICBrief).where(DealICBrief.fund_id == fund_id, DealICBrief.deal_id.in_(deal_ids))).scalars().all()) if deal_ids else []
    brief_by_deal = {b.deal_id: b for b in briefs}

    artifacts = list(
        db.execute(
            select(DealUnderwritingArtifact).where(
                DealUnderwritingArtifact.fund_id == fund_id,
                DealUnderwritingArtifact.deal_id.in_(deal_ids),
                DealUnderwritingArtifact.is_active == True,  # noqa: E712
            ),
        ).scalars().all(),
    ) if deal_ids else []
    artifact_by_deal = {a.deal_id: a for a in artifacts}

    from sqlalchemy import func as sa_func

    from app.domains.credit.modules.deals.models import DealDocument
    doc_counts_q = (
        db.execute(
            select(DealDocument.deal_id, sa_func.count(DealDocument.id))
            .where(DealDocument.fund_id == fund_id)
            .group_by(DealDocument.deal_id),
        ).all()
    )
    doc_count_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in doc_counts_q}

    from app.domains.credit.modules.ai.models import MemoChapter
    chapter_counts_q = (
        db.execute(
            select(MemoChapter.deal_id, sa_func.count(MemoChapter.id), sa_func.max(MemoChapter.generated_at))
            .where(MemoChapter.fund_id == fund_id, MemoChapter.is_current == True)  # noqa: E712
            .group_by(MemoChapter.deal_id),
        ).all()
    )
    chapter_count_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in chapter_counts_q}
    chapter_last_gen_map: dict[uuid.UUID, dt.datetime | None] = {row[0]: row[2] for row in chapter_counts_q}

    items: list[PipelineDealItem] = []
    for deal in deals:
        profile = by_deal.get(deal.id)
        brief = brief_by_deal.get(deal.id)
        art = artifact_by_deal.get(deal.id)
        items.append(
            PipelineDealItem(
                dealId=deal.id,
                dealName=deal.deal_name or deal.title,
                sponsorName=deal.sponsor_name,
                lifecycleStage=deal.lifecycle_stage or deal.stage or "SCREENING",
                riskBand=art.risk_band if art else (profile.risk_band if profile else None),
                strategyType=profile.strategy_type if profile else None,
                recommendationSignal=(
                    art.recommendation if art else (brief.recommendation_signal if brief else None)
                ),
                asOf=profile.last_ai_refresh if profile else (deal.last_updated_at or deal.updated_at),
                documentCount=doc_count_map.get(deal.id, 0),
                intelligenceStatus=deal.intelligence_status,
                dealFolderPath=deal.deal_folder_path,
                chaptersCompleted=chapter_count_map.get(deal.id, 0),
                lastGenerated=chapter_last_gen_map.get(deal.id) or deal.intelligence_generated_at,
            ),
        )

    as_of = max((item.asOf for item in items), default=_utcnow())
    return PipelineDealsResponse(asOf=as_of, dataLatency=None, dataQuality="OK", items=items)


@router.get("/pipeline/deals/{deal_id}", response_model=PipelineDealDetailResponse)
def get_pipeline_deal_detail(
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PipelineDealDetailResponse:
    deal = db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id, Deal.deal_folder_path.is_not(None)),
    ).scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Pipeline deal not found")

    profile = db.execute(
        select(DealIntelligenceProfile).where(DealIntelligenceProfile.fund_id == fund_id, DealIntelligenceProfile.deal_id == deal_id),
    ).scalar_one_or_none()
    risk_flags = list(
        db.execute(
            select(DealRiskFlag)
            .where(DealRiskFlag.fund_id == fund_id, DealRiskFlag.deal_id == deal_id)
            .order_by(DealRiskFlag.created_at.desc()),
        ).scalars().all(),
    )
    brief = db.execute(select(DealICBrief).where(DealICBrief.fund_id == fund_id, DealICBrief.deal_id == deal_id)).scalar_one_or_none()

    risk_out = [
        PipelineRiskFlagOut(
            riskType=flag.risk_type,
            severity=flag.severity,
            reasoning=flag.reasoning,
            sourceDocument=flag.source_document,
        )
        for flag in risk_flags
    ]

    from app.domains.credit.modules.ai.models import MemoChapter

    _BRIEF_CHAPTER_MAP = {
        "executiveSummary":     1,
        "opportunityOverview":  2,
        "returnProfile":        8,
        "downsideCase":         9,
        "riskSummary":         11,
        "comparisonPeerFunds": 12,
    }

    brief_chapters: dict[int, str] = {}
    for row in db.execute(
        select(MemoChapter).where(
            MemoChapter.deal_id == deal_id,
            MemoChapter.fund_id == fund_id,
            MemoChapter.is_current == True,  # noqa: E712
            MemoChapter.chapter_number.in_(list(_BRIEF_CHAPTER_MAP.values())),
        ),
    ).scalars().all():
        content = _normalize_chapter_content(
            row.content_md, row.chapter_number, row.chapter_title or "",
        )
        brief_chapters[row.chapter_number] = content

    def _resolve_brief_field(field_name: str, brief_val: str | None) -> str | None:
        ch_num = _BRIEF_CHAPTER_MAP.get(field_name)
        ch_content = brief_chapters.get(ch_num) if ch_num else None
        if ch_content:
            return ch_content
        return brief_val

    brief_out: PipelineICBriefOut | None = None
    if brief or brief_chapters:
        rec_signal = brief.recommendation_signal if brief else None
        brief_out = PipelineICBriefOut(
            executiveSummary=_resolve_brief_field("executiveSummary", brief.executive_summary if brief else None),
            opportunityOverview=_resolve_brief_field("opportunityOverview", brief.opportunity_overview if brief else None),
            returnProfile=_resolve_brief_field("returnProfile", brief.return_profile if brief else None),
            downsideCase=_resolve_brief_field("downsideCase", brief.downside_case if brief else None),
            riskSummary=_resolve_brief_field("riskSummary", brief.risk_summary if brief else None),
            comparisonPeerFunds=_resolve_brief_field("comparisonPeerFunds", brief.comparison_peer_funds if brief else None),
            recommendationSignal=rec_signal,
        )

    artifact = db.execute(
        select(DealUnderwritingArtifact).where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    if brief_out and artifact:
        brief_out.recommendationSignal = artifact.recommendation

    ic_ready = artifact is not None
    artifact_out = None
    if artifact:
        artifact_out = UnderwritingArtifactOut(
            recommendation=artifact.recommendation,
            confidenceLevel=artifact.confidence_level,
            riskBand=artifact.risk_band,
            missingDocuments=artifact.missing_documents,
            criticFindings=artifact.critic_findings,
            policyBreaches=artifact.policy_breaches,
            chaptersCompleted=artifact.chapters_completed,
            modelVersion=artifact.model_version,
            generatedAt=artifact.generated_at,
            versionNumber=artifact.version_number,
            evidencePackHash=artifact.evidence_pack_hash,
        )

    research_output = None
    try:
        ro_row = db.execute(
            select(Deal.research_output).where(Deal.id == deal_id),
        ).scalar_one_or_none()
        if ro_row and isinstance(ro_row, (dict, list)):
            research_output = ro_row
        elif ro_row and isinstance(ro_row, str):
            import json as _json
            research_output = _json.loads(ro_row)
    except Exception:
        research_output = None

    if isinstance(research_output, dict) and "macro_context" not in research_output:
        _macro_injected = False

        if profile and profile.metadata_json:
            pm = profile.metadata_json
            macro_snap = pm.get("macro_snapshot")
            macro_flag = pm.get("macro_stress_flag")
            if macro_snap is not None or macro_flag is not None:
                research_output["macro_context"] = {
                    "macro_stress_flag": bool(macro_flag) if macro_flag is not None else False,
                    "as_of_date": macro_snap.get("as_of_date") if isinstance(macro_snap, dict) else None,
                    "stress_level": pm.get("stress_level")
                        or (("MODERATE" if macro_flag else "NONE") if macro_flag is not None else None),
                    "treasury_10y": macro_snap.get("risk_free_10y") if isinstance(macro_snap, dict) else None,
                    "baa_spread": macro_snap.get("baa_spread") if isinstance(macro_snap, dict) else None,
                    "yield_curve_2s10s": macro_snap.get("yield_curve_2s10s") if isinstance(macro_snap, dict) else None,
                    "nfci": macro_snap.get("financial_conditions_index") if isinstance(macro_snap, dict) else None,
                }
                research_output["macro_stress_flag"] = bool(macro_flag) if macro_flag is not None else False
                _macro_injected = True

        if not _macro_injected:
            try:
                from app.domains.credit.dashboard.routes import _stress_level_from_snapshot
                _today = dt.date.today()
                _snap_row = db.execute(
                    select(MacroSnapshot).where(MacroSnapshot.as_of_date == _today),
                ).scalar_one_or_none()
                if _snap_row is None:
                    _snap_row = db.execute(
                        select(MacroSnapshot).order_by(MacroSnapshot.as_of_date.desc()).limit(1),
                    ).scalar_one_or_none()
                if _snap_row:
                    _sd = _snap_row.data_json or {}
                    _stress_lvl = _sd.get("stress_severity", {}).get("level") if isinstance(_sd.get("stress_severity"), dict) else None
                    if not _stress_lvl:
                        _stress_lvl = _stress_level_from_snapshot(_sd)
                    _flag = _stress_lvl in ("MODERATE", "SEVERE")
                    research_output["macro_context"] = {
                        "macro_stress_flag": _flag,
                        "as_of_date": _snap_row.as_of_date.isoformat() if _snap_row.as_of_date else None,
                        "stress_level": _stress_lvl,
                        "treasury_10y": _sd.get("risk_free_10y"),
                        "baa_spread": _sd.get("baa_spread"),
                        "yield_curve_2s10s": _sd.get("yield_curve_2s10s"),
                        "nfci": _sd.get("financial_conditions_index"),
                    }
                    research_output["macro_stress_flag"] = _flag
            except Exception:
                pass

    documents_out: list[dict] = []
    try:
        doc_rows = list(
            db.execute(
                select(
                    DocumentRegistry.title,
                    DocumentRegistry.detected_doc_type,
                    DocumentRegistry.blob_path,
                    DocumentRegistry.last_ingested_at,
                )
                .join(DealDocumentIntelligence, DealDocumentIntelligence.doc_id == DocumentRegistry.id)
                .where(DealDocumentIntelligence.deal_id == deal_id)
                .order_by(DocumentRegistry.last_ingested_at.desc()),
            ).all(),
        )
        for doc in doc_rows:
            documents_out.append({
                "title": doc[0] or doc[2] or "Untitled",
                "doc_type": doc[1] or "unknown",
                "blob_path": doc[2] or "",
                "uploaded_at": str(doc[3]) if doc[3] else "",
            })
    except Exception:
        documents_out = []

    resolved_target_return: str | None = None
    if profile:
        raw_tr = profile.target_return or ""
        if raw_tr.startswith("See Chapter") or not raw_tr:
            try:
                import re as _re_tr

                from app.domains.credit.modules.ai.models import MemoChapter

                ch8_content = db.execute(
                    select(MemoChapter.content_md).where(
                        MemoChapter.deal_id == deal_id,
                        MemoChapter.chapter_number == 8,
                        MemoChapter.is_current == True,  # noqa: E712
                    ),
                ).scalar_one_or_none()
                if ch8_content:
                    _irr_patterns = [
                        _re_tr.compile(
                            r"(?:base\s*case\s*(?:net\s*)?irr|target\s*(?:net\s*)?irr|net\s*irr)"
                            r"\s*(?:of\s*)?(?:approximately?\s*)?(\d+[\.\d]*\s*%)",
                            _re_tr.IGNORECASE,
                        ),
                        _re_tr.compile(
                            r"(\d+[\.\d]*\s*%)\s*(?:base\s*case\s*net\s*irr|target\s*(?:net\s*)?irr|net\s*irr)",
                            _re_tr.IGNORECASE,
                        ),
                        _re_tr.compile(
                            r"(\d+[\.\d]*\s*%)\s*target\s*net",
                            _re_tr.IGNORECASE,
                        ),
                    ]
                    for pat in _irr_patterns:
                        m = pat.search(ch8_content)
                        if m:
                            resolved_target_return = "~" + m.group(1).strip() + " Net IRR"
                            break
                    if not resolved_target_return:
                        for line in ch8_content.split("\n"):
                            if "base case" in line.lower():
                                m2 = _re_tr.search(r"(\d+[\.\d]*)\s*%", line)
                                if m2:
                                    resolved_target_return = "~" + m2.group(1) + "% Net IRR"
                                    break
                    if not resolved_target_return:
                        _broader = _re_tr.compile(
                            r"(?:target\s*return|expected\s*return|gross\s*irr|net\s*yield|target\s*yield)"
                            r"\s*(?:of\s*)?(?:approximately?\s*)?(\d+[\.\d]*)\s*%",
                            _re_tr.IGNORECASE,
                        )
                        m3 = _broader.search(ch8_content)
                        if m3:
                            resolved_target_return = "~" + m3.group(1) + "%"
                    if not resolved_target_return:
                        m4 = _re_tr.search(
                            r"Base\s*Rate\s*\(current\).*?(\d+[\.\d]*)\s*%\s*IRR",
                            ch8_content,
                            _re_tr.IGNORECASE,
                        )
                        if m4:
                            resolved_target_return = "~" + m4.group(1) + "% IRR"
                    if not resolved_target_return:
                        m5 = _re_tr.search(
                            r"median\s*(?:net\s*)?irr.*?(\d+[\.\d]*)\s*%",
                            ch8_content,
                            _re_tr.IGNORECASE,
                        )
                        if m5:
                            resolved_target_return = "~" + m5.group(1) + "% (Benchmark)"
            except Exception:
                pass
            if not resolved_target_return:
                resolved_target_return = raw_tr
        else:
            resolved_target_return = raw_tr

    return PipelineDealDetailResponse(
        asOf=profile.last_ai_refresh if profile else (deal.last_updated_at or deal.updated_at),
        dataLatency=None,
        dataQuality="OK",
        dealId=deal.id,
        dealName=deal.deal_name or deal.title,
        sponsorName=deal.sponsor_name,
        lifecycleStage=deal.lifecycle_stage or deal.stage or "SCREENING",
        intelligenceStatus=deal.intelligence_status,
        dealFolderPath=deal.deal_folder_path,
        approvedDealId=deal.approved_deal_id,
        profile={
            "strategyType": profile.strategy_type,
            "geography": profile.geography,
            "sectorFocus": profile.sector_focus,
            "targetReturn": resolved_target_return,
            "riskBand": artifact.risk_band if artifact else profile.risk_band,
            "liquidityProfile": profile.liquidity_profile,
            "capitalStructureType": profile.capital_structure_type,
            "keyRisks": profile.key_risks,
            "differentiators": profile.differentiators,
            "summaryIcReady": profile.summary_ic_ready,
            "lastAiRefresh": profile.last_ai_refresh,
        }
        if profile
        else None,
        riskFlags=risk_out,
        icBrief=brief_out,
        researchOutput=research_output,
        documents=documents_out if documents_out else None,
        icReady=ic_ready,
        underwritingArtifact=artifact_out,
    )


@router.get("/pipeline/alerts", response_model=PipelineAlertsResponse)
def get_pipeline_alerts(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> PipelineAlertsResponse:
    rows = list(
        db.execute(
            select(PipelineAlert)
            .where(PipelineAlert.fund_id == fund_id)
            .order_by(PipelineAlert.created_at.desc())
            .limit(300),
        ).scalars().all(),
    )

    items = [
        PipelineAlertOut(
            alertId=row.id,
            dealId=row.deal_id,
            alertType=row.alert_type,
            severity=row.severity,
            description=row.description,
            createdAt=row.created_at,
            resolvedFlag=row.resolved_flag,
        )
        for row in rows
    ]

    as_of = max((item.createdAt for item in items), default=_utcnow())
    return PipelineAlertsResponse(asOf=as_of, dataLatency=None, dataQuality="OK", items=items)
