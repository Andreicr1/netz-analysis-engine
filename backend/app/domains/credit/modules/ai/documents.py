"""AI Documents sub-router — classification, index, detail, ingest."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_engine.classification.classifier import classify_documents
from ai_engine.ingestion.document_scanner import run_documents_ingest_pipeline
from ai_engine.ingestion.monitoring import run_daily_cycle
from ai_engine.knowledge.knowledge_builder import build_manager_profiles
from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.ai.models import (
    DocumentClassification,
    DocumentGovernanceProfile,
    DocumentRegistry,
    GovernanceAlert,
    KnowledgeAnchor,
    ManagerProfile,
)
from app.domains.credit.modules.ai.routes._helpers import (
    _envelope_from_rows,
    _limit,
    _offset,
    _utcnow,
)
from app.domains.credit.modules.ai.schemas import (
    DailyCycleRunResponse,
    DocumentClassificationItem,
    DocumentClassificationResponse,
    DocumentDetailResponse,
    DocumentIndexItem,
    DocumentIndexResponse,
    DocumentsIngestResponse,
    GovernanceAlertItem,
    GovernanceAlertsResponse,
    KnowledgeAnchorOut,
    ManagerProfileItem,
    ManagerProfileResponse,
)
from app.shared.enums import Role

router = APIRouter()


@router.get("/documents/classification", response_model=DocumentClassificationResponse)
def get_documents_classification(
    fund_id: uuid.UUID,
    path: str | None = Query(default=None),
    refresh: bool = Query(default=False, description="When true, triggers AI re-classification instead of returning cached results"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
) -> DocumentClassificationResponse:
    """Return document classifications for a fund."""
    if not refresh:
        stmt = select(DocumentRegistry).where(DocumentRegistry.fund_id == fund_id)
        if path:
            stmt = stmt.where(DocumentRegistry.blob_path.ilike(f"{path.strip().lower()}%"))
        stmt = stmt.order_by(DocumentRegistry.last_ingested_at.desc()).limit(limit).offset(offset)
        existing = list(db.execute(stmt).scalars().all())
        if existing:
            as_of, data_latency, data_quality = _envelope_from_rows(existing)
            items = [DocumentClassificationItem.model_validate(row) for row in existing]
            return DocumentClassificationResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)

    rows = classify_documents(db, fund_id=fund_id, path=path, actor_id=actor.actor_id)
    as_of, data_latency, data_quality = _envelope_from_rows(rows)
    items = [DocumentClassificationItem.model_validate(row) for row in rows]
    return DocumentClassificationResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)


@router.get("/managers/profile", response_model=ManagerProfileResponse)
def get_manager_profile(
    fund_id: uuid.UUID,
    manager: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> ManagerProfileResponse:
    build_manager_profiles(db, fund_id=fund_id, manager=manager, actor_id=actor.actor_id)
    row = db.execute(
        select(ManagerProfile).where(
            ManagerProfile.fund_id == fund_id,
            func.lower(ManagerProfile.name) == manager.strip().lower(),
        ),
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Manager profile not found")

    as_of, data_latency, data_quality = _envelope_from_rows([row])
    return ManagerProfileResponse(
        asOf=as_of,
        dataLatency=data_latency,
        dataQuality=data_quality,
        item=ManagerProfileItem.model_validate(row),
    )


@router.get("/alerts/daily", response_model=GovernanceAlertsResponse)
def get_daily_alerts(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> GovernanceAlertsResponse:
    rows = list(
        db.execute(
            select(GovernanceAlert)
            .where(GovernanceAlert.fund_id == fund_id)
            .order_by(GovernanceAlert.as_of.desc())
            .limit(200),
        ).scalars().all(),
    )
    as_of, data_latency, data_quality = _envelope_from_rows(rows)
    items = [GovernanceAlertItem.model_validate(row) for row in rows]
    return GovernanceAlertsResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)


@router.post("/run-daily-cycle", response_model=DailyCycleRunResponse)
def run_ai_daily_cycle(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN])),
) -> DailyCycleRunResponse:
    result = run_daily_cycle(db, fund_id=fund_id, actor_id=actor.actor_id)
    as_of = dt.datetime.fromisoformat(str(result["asOf"]))
    return DailyCycleRunResponse(
        asOf=as_of,
        classifiedDocuments=int(result["classifiedDocuments"]),
        managerProfiles=int(result["managerProfiles"]),
        obligations=int(result["obligations"]),
        alerts=int(result["alerts"]),
    )


@router.post("/documents/ingest", response_model=DocumentsIngestResponse)
def ingest_documents_index(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.GP])),
) -> DocumentsIngestResponse:
    result = run_documents_ingest_pipeline(db, fund_id=fund_id, actor_id=actor.actor_id)
    now = _utcnow()
    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="AI2_DOCUMENT_INGEST_PIPELINE",
        entity_type="fund",
        entity_id=str(fund_id),
        before=None,
        after=result,
    )
    db.commit()
    return DocumentsIngestResponse(
        asOf=now,
        documentsScanned=int(result["documentsScanned"]),
        documentsClassified=int(result["documentsClassified"]),
        governanceProfiles=int(result["governanceProfiles"]),
        knowledgeAnchors=int(result["knowledgeAnchors"]),
    )


@router.get("/documents/index", response_model=DocumentIndexResponse)
def get_documents_index(
    fund_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.GP, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> DocumentIndexResponse:
    docs = list(
        db.execute(
            select(DocumentRegistry)
            .where(DocumentRegistry.fund_id == fund_id)
            .order_by(DocumentRegistry.last_ingested_at.desc())
            .limit(limit)
            .offset(offset),
        ).scalars().all(),
    )

    if not docs:
        return DocumentIndexResponse(asOf=_utcnow(), dataLatency=0, dataQuality="OK", items=[])

    doc_ids = [doc.id for doc in docs]

    classifications = list(
        db.execute(
            select(DocumentClassification).where(
                DocumentClassification.fund_id == fund_id,
                DocumentClassification.doc_id.in_(doc_ids),
            ),
        ).scalars().all(),
    )
    governance_profiles = list(
        db.execute(
            select(DocumentGovernanceProfile).where(
                DocumentGovernanceProfile.fund_id == fund_id,
                DocumentGovernanceProfile.doc_id.in_(doc_ids),
            ),
        ).scalars().all(),
    )
    anchors = list(
        db.execute(
            select(KnowledgeAnchor.doc_id, func.count())
            .where(
                KnowledgeAnchor.fund_id == fund_id,
                KnowledgeAnchor.doc_id.in_(doc_ids),
            )
            .group_by(KnowledgeAnchor.doc_id),
        ).all(),
    )

    by_doc_classification = {row.doc_id: row for row in classifications}
    by_doc_profile = {row.doc_id: row for row in governance_profiles}
    anchors_count = {doc_id: int(count or 0) for doc_id, count in anchors}

    items: list[DocumentIndexItem] = []
    for doc in docs:
        classification = by_doc_classification.get(doc.id)
        profile = by_doc_profile.get(doc.id)
        items.append(
            DocumentIndexItem(
                docId=doc.id,
                blobPath=doc.blob_path,
                containerName=doc.container_name,
                domainTag=doc.domain_tag,
                lifecycleStage=doc.lifecycle_stage,
                detectedDocType=classification.doc_type if classification else doc.detected_doc_type,
                resolvedAuthority=profile.resolved_authority if profile else None,
                shareability=doc.shareability,
                auditReady=bool(classification and profile and anchors_count.get(doc.id, 0) > 0),
                lastIngestedAt=doc.last_ingested_at,
            ),
        )

    as_of, data_latency, data_quality = _envelope_from_rows(docs)
    return DocumentIndexResponse(asOf=as_of, dataLatency=data_latency, dataQuality=data_quality, items=items)


@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    doc_id: uuid.UUID,
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.GP, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> DocumentDetailResponse:
    doc = db.execute(
        select(DocumentRegistry).where(DocumentRegistry.fund_id == fund_id, DocumentRegistry.id == doc_id),
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    classification = db.execute(
        select(DocumentClassification).where(DocumentClassification.fund_id == fund_id, DocumentClassification.doc_id == doc_id),
    ).scalar_one_or_none()
    governance_profile = db.execute(
        select(DocumentGovernanceProfile).where(DocumentGovernanceProfile.fund_id == fund_id, DocumentGovernanceProfile.doc_id == doc_id),
    ).scalar_one_or_none()
    anchors = list(
        db.execute(
            select(KnowledgeAnchor)
            .where(KnowledgeAnchor.fund_id == fund_id, KnowledgeAnchor.doc_id == doc_id)
            .order_by(KnowledgeAnchor.anchor_type.asc()),
        ).scalars().all(),
    )

    anchor_out = [
        KnowledgeAnchorOut(
            anchorType=anchor.anchor_type,
            anchorValue=anchor.anchor_value,
            sourceSnippet=anchor.source_snippet,
            pageReference=anchor.page_reference,
        )
        for anchor in anchors
    ]

    return DocumentDetailResponse(
        asOf=doc.as_of,
        dataLatency=doc.data_latency,
        dataQuality=doc.data_quality,
        docId=doc.id,
        blobPath=doc.blob_path,
        containerName=doc.container_name,
        domainTag=doc.domain_tag,
        lifecycleStage=doc.lifecycle_stage,
        classification={
            "docType": classification.doc_type if classification else None,
            "confidenceScore": classification.confidence_score if classification else None,
            "classificationBasis": classification.classification_basis if classification else None,
        },
        governanceProfile={
            "resolvedAuthority": governance_profile.resolved_authority,
            "bindingScope": governance_profile.binding_scope,
            "shareabilityFinal": governance_profile.shareability_final,
            "jurisdiction": governance_profile.jurisdiction,
        }
        if governance_profile
        else None,
        anchors=anchor_out,
    )
