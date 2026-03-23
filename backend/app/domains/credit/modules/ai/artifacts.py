"""AI Artifacts sub-router — evidence governance, underwriting, fact sheets, marketing presentations."""
from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.pipeline.storage_routing import gold_artifact_path
from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.ai._helpers import _utcnow
from app.domains.credit.modules.ai.models import DealUnderwritingArtifact
from app.domains.credit.modules.ai.schemas import (
    CriticalGapItem,
    CriticalGapsResponse,
    FactSheetPdfResponse,
    MarketingPresentationPdfResponse,
)
from app.domains.credit.modules.deals.models import Deal
from app.services.storage_client import StorageClient, get_storage_client
from app.shared.enums import Role

router = APIRouter()


@router.get("/pipeline/deals/{deal_id}/evidence-governance")
def get_deal_evidence_governance(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Return evidence governance summary for a pipeline deal."""
    import json as _json

    deal = db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    ).scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    try:
        ro = deal.research_output
        if isinstance(ro, str):
            try:
                ro = _json.loads(ro)
            except Exception:
                ro = {}
        if not isinstance(ro, dict):
            ro = {}

        risk_map = ro.get("risk_map") or {}
        key_risks = risk_map.get("key_risks") if isinstance(risk_map, dict) else []
        if not isinstance(key_risks, list):
            key_risks = []

        citations = ro.get("citations")
        if not isinstance(citations, list):
            citations = []

        return {
            "deal_id": str(deal_id),
            "deal_name": deal.deal_name or deal.title,
            "intelligence_status": deal.intelligence_status,
            "data_room_completeness": ro.get("data_room_completeness") or {},
            "issuer_summary": ro.get("issuer_summary") or {},
            "missing_documents": ro.get("missing_documents") or [],
            "confidence_score": ro.get("confidence_score"),
            "confidence_rationale": ro.get("confidence_rationale", ""),
            "confidence_adjustment": ro.get("confidence_adjustment", ""),
            "citations_count": len(citations),
            "risk_count": len(key_risks),
        }
    except Exception as exc:
        import logging
        logging.getLogger("ai.evidence_governance").warning(
            "evidence-governance failed for deal_id=%s: %s", deal_id, exc, exc_info=True,
        )
        return {
            "deal_id": str(deal_id),
            "deal_name": getattr(deal, "deal_name", None) or getattr(deal, "title", ""),
            "intelligence_status": getattr(deal, "intelligence_status", "PENDING"),
            "data_room_completeness": {},
            "issuer_summary": {},
            "missing_documents": [],
            "confidence_score": None,
            "confidence_rationale": "",
            "confidence_adjustment": "",
            "citations_count": 0,
            "risk_count": 0,
        }


@router.get("/pipeline/deals/{deal_id}/underwriting-artifact")
def get_deal_underwriting_artifact(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Return the active unified underwriting artifact for a pipeline deal."""
    artifact = db.execute(
        select(DealUnderwritingArtifact).where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    if not artifact:
        return {"icReady": False}

    return {
        "icReady": True,
        "recommendation": artifact.recommendation,
        "confidenceLevel": artifact.confidence_level,
        "riskBand": artifact.risk_band,
        "missingDocuments": artifact.missing_documents,
        "criticFindings": artifact.critic_findings,
        "policyBreaches": artifact.policy_breaches,
        "chaptersCompleted": artifact.chapters_completed,
        "modelVersion": artifact.model_version,
        "generatedAt": artifact.generated_at.isoformat() if artifact.generated_at else None,
        "versionNumber": artifact.version_number,
        "evidencePackHash": artifact.evidence_pack_hash,
    }


@router.get("/pipeline/deals/{deal_id}/underwriting-artifact/history")
def get_deal_underwriting_artifact_history(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.AUDITOR])),
):
    """Return all underwriting artifact versions for audit trail."""
    rows = list(
        db.execute(
            select(DealUnderwritingArtifact)
            .where(
                DealUnderwritingArtifact.fund_id == fund_id,
                DealUnderwritingArtifact.deal_id == deal_id,
            )
            .order_by(DealUnderwritingArtifact.version_number.desc()),
        ).scalars().all(),
    )
    return {
        "dealId": str(deal_id),
        "totalVersions": len(rows),
        "artifacts": [
            {
                "versionNumber": a.version_number,
                "isActive": a.is_active,
                "recommendation": a.recommendation,
                "confidenceLevel": a.confidence_level,
                "riskBand": a.risk_band,
                "chaptersCompleted": a.chapters_completed,
                "modelVersion": a.model_version,
                "generatedAt": a.generated_at.isoformat() if a.generated_at else None,
                "evidencePackHash": a.evidence_pack_hash,
            }
            for a in rows
        ],
    }


@router.get(
    "/pipeline/deals/{deal_id}/critical-gaps",
    response_model=CriticalGapsResponse,
)
def get_deal_critical_gaps(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> CriticalGapsResponse:
    """Return structured critical_gaps (approval-blocking data gaps) for a pipeline deal.

    Critical gaps are flagged during IC Memo generation and stored in the active
    underwriting artifact's critic_findings. These represent data gaps that must be
    resolved before an investment can be approved.
    """
    import logging

    log = logging.getLogger("ai.critical_gaps")

    from app.domains.credit.modules.ai._helpers import _utcnow

    artifact = db.execute(
        select(DealUnderwritingArtifact).where(
            DealUnderwritingArtifact.fund_id == fund_id,
            DealUnderwritingArtifact.deal_id == deal_id,
            DealUnderwritingArtifact.is_active == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    if not artifact:
        return CriticalGapsResponse(
            asOf=_utcnow(),
            dataLatency=None,
            dataQuality="OK",
            dealId=str(deal_id),
            totalGaps=0,
            gaps=[],
        )

    raw_gaps: list[dict] = []
    try:
        findings = artifact.critic_findings or {}
        if isinstance(findings, dict):
            raw_gaps = findings.get("critical_gaps", [])
            if not isinstance(raw_gaps, list):
                raw_gaps = []
    except Exception as exc:
        log.warning("critical-gaps parse error deal_id=%s: %s", deal_id, exc)
        raw_gaps = []

    gap_items: list[CriticalGapItem] = []
    for entry in raw_gaps:
        if not isinstance(entry, dict):
            continue
        gap_text = entry.get("gap", "")
        if not gap_text:
            continue
        gap_items.append(
            CriticalGapItem(
                chapter_tag=entry.get("chapter_tag", ""),
                chapter_num=int(entry.get("chapter_num", 0)),
                chapter_title=entry.get("chapter_title", ""),
                gap=gap_text,
            ),
        )

    log.info(
        "CRITICAL_GAPS deal_id=%s total=%d artifact_version=%d",
        deal_id,
        len(gap_items),
        artifact.version_number,
    )

    return CriticalGapsResponse(
        asOf=_utcnow(),
        dataLatency=None,
        dataQuality="OK",
        dealId=str(deal_id),
        totalGaps=len(gap_items),
        gaps=gap_items,
        artifactVersion=artifact.version_number,
        generatedAt=artifact.generated_at,
    )


@router.post(
    "/pipeline/fact-sheet/generate",
    response_model=FactSheetPdfResponse,
)
async def generate_fact_sheet(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    storage: StorageClient = Depends(get_storage_client),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP])),
) -> FactSheetPdfResponse:
    """Generate a fund-level Fact Sheet PPTX."""
    import logging
    import pathlib
    from datetime import date as _date
    from datetime import datetime as _dt

    log = logging.getLogger("ai.fact_sheet")

    generated_at = _dt.now(UTC)
    version_tag = f"fact-sheet-{generated_at.strftime('%Y%m%dT%H%M%S')}"
    model_version = "pptx-rag-v1"

    from app.services.presentation_builder import PresentationBuilder
    from app.services.presentation_data import build_presentation_data

    nav = _date.today()
    data = build_presentation_data(
        str(fund_id), nav, db,
        use_llm_thesis=True,
        use_llm_fund_data=True,
    )

    local_cache_dir = pathlib.Path("public/fact-sheets") / str(fund_id)
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = str(local_cache_dir / f"{version_tag}.pptx")

    try:
        builder = PresentationBuilder(data)
        builder.generate_fact_sheet(pptx_path)
    except Exception as exc:
        log.error("Fact Sheet PPTX generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Fact Sheet generation failed: {exc}")

    filename = f"{version_tag}.pptx"
    org_id = actor.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organization context required")
    path = gold_artifact_path(org_id, str(fund_id), filename)

    with open(pptx_path, "rb") as f:
        pptx_bytes = f.read()

    if not await storage.exists(path):
        await storage.write(
            path,
            pptx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        log.info("Fact Sheet uploaded: %s", path)

    signed_url = await storage.generate_read_url(path)
    return FactSheetPdfResponse(
        signedPdfUrl=signed_url,
        versionTag=version_tag,
        generatedAt=generated_at,
        modelVersion=model_version,
    )


@router.get(
    "/pipeline/fact-sheet/pdf",
    response_model=FactSheetPdfResponse,
)
async def get_fact_sheet_pdf(
    fund_id: uuid.UUID,
    actor: Actor = Depends(get_actor),
    storage: StorageClient = Depends(get_storage_client),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> FactSheetPdfResponse:
    """Return a signed URL for the latest Fact Sheet PPTX (if it exists)."""
    import logging

    log = logging.getLogger("ai.fact_sheet")

    org_id = actor.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organization context required")

    prefix = gold_artifact_path(org_id, str(fund_id), "fact-sheet-")
    try:
        files = await storage.list_files(prefix)
        if not files:
            raise HTTPException(status_code=404, detail="No Fact Sheet found. Generate one first.")

        files.sort(reverse=True)
        latest_path = files[0]

        signed_url = await storage.generate_read_url(latest_path)
        filename = latest_path.rsplit("/", 1)[-1] if "/" in latest_path else latest_path
        vtag = filename.replace(".pptx", "").replace(".pdf", "") if filename else "unknown"
        return FactSheetPdfResponse(
            signedPdfUrl=signed_url,
            versionTag=vtag,
            generatedAt=_utcnow(),
            modelVersion="pptx-rag-v1",
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Fact Sheet retrieval failed: %s", exc)
        raise HTTPException(status_code=404, detail="Fact Sheet not available.")


@router.post(
    "/pipeline/marketing-presentation/generate",
    response_model=MarketingPresentationPdfResponse,
)
async def generate_marketing_presentation(
    fund_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    actor: Actor = Depends(get_actor),
    storage: StorageClient = Depends(get_storage_client),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP])),
) -> MarketingPresentationPdfResponse:
    """Generate a fund-level Marketing Presentation PPTX."""
    import logging
    import pathlib
    from datetime import date as _date
    from datetime import datetime as _dt

    log = logging.getLogger("ai.marketing_pres")

    generated_at = _dt.now(UTC)
    version_tag = f"marketing-pres-{generated_at.strftime('%Y%m%dT%H%M%S')}"
    model_version = "pptx-rag-v1"

    from app.services.presentation_builder import PresentationBuilder
    from app.services.presentation_data import build_presentation_data

    nav = _date.today()
    data = build_presentation_data(
        str(fund_id), nav, db,
        use_llm_thesis=True,
        use_llm_fund_data=True,
    )

    local_cache_dir = pathlib.Path("public/marketing-presentations") / str(fund_id)
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = str(local_cache_dir / f"{version_tag}.pptx")

    try:
        builder = PresentationBuilder(data)
        builder.generate_marketing(pptx_path)
    except Exception as exc:
        log.error("Marketing Presentation PPTX generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Marketing Presentation generation failed: {exc}")

    filename = f"{version_tag}.pptx"
    org_id = actor.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organization context required")
    path = gold_artifact_path(org_id, str(fund_id), filename)

    with open(pptx_path, "rb") as f:
        pptx_bytes = f.read()

    if not await storage.exists(path):
        await storage.write(
            path,
            pptx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        log.info("Marketing Presentation uploaded: %s", path)

    signed_url = await storage.generate_read_url(path)
    return MarketingPresentationPdfResponse(
        signedPdfUrl=signed_url,
        versionTag=version_tag,
        generatedAt=generated_at,
        modelVersion=model_version,
    )


@router.get(
    "/pipeline/marketing-presentation/pdf",
    response_model=MarketingPresentationPdfResponse,
)
async def get_marketing_presentation_pdf(
    fund_id: uuid.UUID,
    actor: Actor = Depends(get_actor),
    storage: StorageClient = Depends(get_storage_client),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> MarketingPresentationPdfResponse:
    """Return a signed URL for the latest Marketing Presentation PPTX (if it exists)."""
    import logging

    log = logging.getLogger("ai.marketing_pres")

    org_id = actor.organization_id
    if org_id is None:
        raise HTTPException(status_code=400, detail="Organization context required")

    prefix = gold_artifact_path(org_id, str(fund_id), "marketing-pres-")
    try:
        files = await storage.list_files(prefix)
        if not files:
            raise HTTPException(status_code=404, detail="No Marketing Presentation found. Generate one first.")

        files.sort(reverse=True)
        latest_path = files[0]

        signed_url = await storage.generate_read_url(latest_path)
        filename = latest_path.rsplit("/", 1)[-1] if "/" in latest_path else latest_path
        vtag = filename.replace(".pptx", "").replace(".pdf", "") if filename else "unknown"
        return MarketingPresentationPdfResponse(
            signedPdfUrl=signed_url,
            versionTag=vtag,
            generatedAt=_utcnow(),
            modelVersion="pptx-rag-v1",
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Marketing Presentation retrieval failed: %s", exc)
        raise HTTPException(status_code=404, detail="Marketing Presentation not available.")
