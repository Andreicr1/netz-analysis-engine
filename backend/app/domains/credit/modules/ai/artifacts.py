"""AI Artifacts sub-router — evidence governance, underwriting, fact sheets, marketing presentations."""
from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.ai.models import DealUnderwritingArtifact
from app.domains.credit.modules.ai.routes._helpers import _utcnow
from app.domains.credit.modules.ai.schemas import (
    CriticalGapItem,
    CriticalGapsResponse,
    FactSheetPdfResponse,
    MarketingPresentationPdfResponse,
)
from app.domains.credit.modules.deals.models import Deal
from app.shared.enums import Role

router = APIRouter()

_FACT_SHEET_CONTAINER = "netz-fund-artifacts"
_MARKETING_PRES_CONTAINER = "netz-fund-artifacts"


@router.get("/pipeline/deals/{deal_id}/evidence-governance")
def get_deal_evidence_governance(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> CriticalGapsResponse:
    """Return structured critical_gaps (approval-blocking data gaps) for a pipeline deal.

    Critical gaps are flagged during IC Memo generation and stored in the active
    underwriting artifact's critic_findings. These represent data gaps that must be
    resolved before an investment can be approved.
    """
    import logging

    log = logging.getLogger("ai.critical_gaps")

    from app.domains.credit.modules.ai.routes._helpers import _utcnow

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
def generate_fact_sheet(
    fund_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
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

    try:
        from app.services.blob_storage import (
            ensure_container,
            generate_read_link,
            upload_bytes_idempotent,
        )
        from app.services.blob_storage import (
            exists as blob_exists,
        )

        with open(pptx_path, "rb") as f:
            pptx_bytes = f.read()

        container = _FACT_SHEET_CONTAINER
        ensure_container(container)
        blob_name = f"fact-sheets/{fund_id}/{version_tag}.pptx"

        if not blob_exists(container=container, blob_name=blob_name):
            upload_bytes_idempotent(
                container=container,
                blob_name=blob_name,
                data=pptx_bytes,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                metadata={
                    "fund_id": str(fund_id),
                    "document_type": "FACT_SHEET",
                    "version_tag": version_tag,
                    "generated_by": actor.actor_id,
                },
            )
            log.info("Fact Sheet uploaded: %s/%s", container, blob_name)

        signed_url = generate_read_link(container=container, blob_name=blob_name, ttl_minutes=30)
        return FactSheetPdfResponse(
            signedPdfUrl=signed_url,
            versionTag=version_tag,
            generatedAt=generated_at,
            modelVersion=model_version,
        )
    except Exception as blob_err:
        log.warning("Blob storage unavailable (%s), falling back to local.", blob_err)

    base_url = str(request.base_url).rstrip("/")
    local_url = f"{base_url}/public/fact-sheets/{fund_id}/{version_tag}.pptx"
    return FactSheetPdfResponse(
        signedPdfUrl=local_url,
        versionTag=version_tag,
        generatedAt=generated_at,
        modelVersion=model_version,
    )


@router.get(
    "/pipeline/fact-sheet/pdf",
    response_model=FactSheetPdfResponse,
)
def get_fact_sheet_pdf(
    fund_id: uuid.UUID,
    request: Request,
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> FactSheetPdfResponse:
    """Return a signed URL for the latest Fact Sheet PPTX (if it exists)."""
    import logging

    log = logging.getLogger("ai.fact_sheet")

    try:
        from app.services.blob_storage import generate_read_link, list_blobs

        container = _FACT_SHEET_CONTAINER
        prefix = f"fact-sheets/{fund_id}/"
        blobs = list_blobs(container=container, name_starts_with=prefix)
        if not blobs:
            raise HTTPException(status_code=404, detail="No Fact Sheet found. Generate one first.")

        blobs.sort(key=lambda b: b.name, reverse=True)
        blob_name = blobs[0].name

        signed_url = generate_read_link(container=container, blob_name=blob_name, ttl_minutes=30)
        filename = blob_name.rsplit("/", 1)[-1] if "/" in blob_name else blob_name
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
def generate_marketing_presentation(
    fund_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
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

    try:
        from app.services.blob_storage import (
            ensure_container,
            generate_read_link,
            upload_bytes_idempotent,
        )
        from app.services.blob_storage import (
            exists as blob_exists,
        )

        with open(pptx_path, "rb") as f:
            pptx_bytes = f.read()

        container = _MARKETING_PRES_CONTAINER
        ensure_container(container)
        blob_name = f"marketing-presentations/{fund_id}/{version_tag}.pptx"

        if not blob_exists(container=container, blob_name=blob_name):
            upload_bytes_idempotent(
                container=container,
                blob_name=blob_name,
                data=pptx_bytes,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                metadata={
                    "fund_id": str(fund_id),
                    "document_type": "MARKETING_PRESENTATION",
                    "version_tag": version_tag,
                    "generated_by": actor.actor_id,
                },
            )
            log.info("Marketing Presentation uploaded: %s/%s", container, blob_name)

        signed_url = generate_read_link(container=container, blob_name=blob_name, ttl_minutes=30)
        return MarketingPresentationPdfResponse(
            signedPdfUrl=signed_url,
            versionTag=version_tag,
            generatedAt=generated_at,
            modelVersion=model_version,
        )
    except Exception as blob_err:
        log.warning("Blob storage unavailable (%s), falling back to local.", blob_err)

    base_url = str(request.base_url).rstrip("/")
    local_url = f"{base_url}/public/marketing-presentations/{fund_id}/{version_tag}.pptx"
    return MarketingPresentationPdfResponse(
        signedPdfUrl=local_url,
        versionTag=version_tag,
        generatedAt=generated_at,
        modelVersion=model_version,
    )


@router.get(
    "/pipeline/marketing-presentation/pdf",
    response_model=MarketingPresentationPdfResponse,
)
def get_marketing_presentation_pdf(
    fund_id: uuid.UUID,
    request: Request,
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> MarketingPresentationPdfResponse:
    """Return a signed URL for the latest Marketing Presentation PPTX (if it exists)."""
    import logging

    log = logging.getLogger("ai.marketing_pres")

    try:
        from app.services.blob_storage import generate_read_link, list_blobs

        container = _MARKETING_PRES_CONTAINER
        prefix = f"marketing-presentations/{fund_id}/"
        blobs = list_blobs(container=container, name_starts_with=prefix)
        if not blobs:
            raise HTTPException(status_code=404, detail="No Marketing Presentation found. Generate one first.")

        blobs.sort(key=lambda b: b.name, reverse=True)
        blob_name = blobs[0].name

        signed_url = generate_read_link(container=container, blob_name=blob_name, ttl_minutes=30)
        filename = blob_name.rsplit("/", 1)[-1] if "/" in blob_name else blob_name
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
