from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.base import AuditEvent
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import (
    get_actor,
    require_readonly_allowed,
    require_roles,
)
from app.domains.credit.compliance.services.evidence_gap import AI_GAP_PREFIX
from app.domains.credit.modules.compliance import service
from app.domains.credit.modules.compliance.models import Obligation
from app.domains.credit.modules.compliance.schemas import (
    ActorMeOut,
    AuditEventOut,
    ComplianceSnapshotOut,
    ObligationCreate,
    ObligationEvidenceLinkIn,
    ObligationEvidenceOut,
    ObligationOut,
    ObligationRequirementCreate,
    ObligationRequirementOut,
    ObligationStatusOut,
    ObligationWorkflowOut,
    Page,
)
from app.shared.enums import Role

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("/snapshot", response_model=ComplianceSnapshotOut)
def snapshot(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> ComplianceSnapshotOut:
    obligations = list(
        db.execute(select(Obligation.id).where(Obligation.fund_id == fund_id))
        .scalars()
        .all(),
    )
    wf = service.get_workflow_status_map(
        db, fund_id=fund_id, obligation_ids=obligations,
    )

    total_open = 0
    for oid in obligations:
        if wf.get(oid, "OPEN") != "CLOSED":
            total_open += 1

    total_gaps = db.execute(
        select(sa_func.count()).select_from(Obligation).where(
            Obligation.fund_id == fund_id, Obligation.name.like(f"{AI_GAP_PREFIX}%"),
        ),
    ).scalar_one()

    since = datetime.now(UTC) - timedelta(days=30)
    closed_ids = list(
        db.execute(
            select(AuditEvent.entity_id)
            .distinct()
            .where(
                AuditEvent.fund_id == fund_id,
                AuditEvent.entity_type == "obligation",
                AuditEvent.action == service.AUDIT_ACTION_CLOSED,
                AuditEvent.created_at >= since,
            ),
        )
        .scalars()
        .all(),
    )

    return ComplianceSnapshotOut(
        generated_at_utc=datetime.now(UTC),
        total_open_obligations=total_open,
        total_ai_gaps=total_gaps,
        closed_obligations_last_30_days=len(closed_ids),
    )


def _limit(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(0, ge=0, le=10_000)) -> int:
    return offset


@router.get("/me", response_model=ActorMeOut)
def me(
    fund_id: uuid.UUID,
    actor: Actor = Depends(get_actor),
) -> ActorMeOut:
    # Backend is authoritative for roles; UI can use this for deterministic gating.
    roles = [r.value if hasattr(r, "value") else str(r) for r in (actor.roles or [])]
    # EPIC 9: Director signature workflow removed as DIRECTOR is now a distinct role.
    return ActorMeOut(actor_id=actor.actor_id, roles=roles)


@router.get("/obligations", response_model=Page[ObligationWorkflowOut])
def list_obligations(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    view: str = Query(default="active", pattern="^(active|closed|all)$"),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> Page[ObligationWorkflowOut]:
    items, wf, total = service.list_obligations(
        db, fund_id=fund_id, limit=limit, offset=offset, view=view,
    )

    out: list[ObligationWorkflowOut] = []
    for o in items:
        ow = ObligationWorkflowOut.model_validate(o)
        ow.workflow_status = wf.get(o.id, "OPEN")
        ow.display_status = service.compute_display_status(
            ow.workflow_status, o.next_due_date,
        )
        out.append(ow)

    return Page(items=out, total=total, limit=limit, offset=offset)


@router.get("/obligations/{obligation_id}", response_model=ObligationWorkflowOut)
def get_obligation(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> ObligationWorkflowOut:
    try:
        ob = service.get_obligation(db, fund_id=fund_id, obligation_id=obligation_id)
        wf = service.get_workflow_status_map(
            db, fund_id=fund_id, obligation_ids=[ob.id],
        )
        out = ObligationWorkflowOut.model_validate(ob)
        out.workflow_status = wf.get(ob.id, "OPEN")
        out.display_status = service.compute_display_status(
            out.workflow_status, ob.next_due_date,
        )
        return out
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/obligations/{obligation_id}/evidence", response_model=list[ObligationEvidenceOut],
)
def list_evidence(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> list[ObligationEvidenceOut]:
    try:
        events = service.list_linked_evidence(
            db, fund_id=fund_id, obligation_id=obligation_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    out: list[ObligationEvidenceOut] = []
    for ev in events:
        after = ev.after or {}
        out.append(
            ObligationEvidenceOut(
                document_id=uuid.UUID(after.get("document_id")),
                version_id=uuid.UUID(after["version_id"])
                if after.get("version_id")
                else None,
                title=str(after.get("document_title") or ""),
                root_folder=after.get("root_folder"),
                folder_path=after.get("folder_path"),
                linked_at=ev.created_at,
                linked_by=ev.actor_id,
            ),
        )
    return out


@router.post(
    "/obligations/{obligation_id}/evidence/link", status_code=status.HTTP_201_CREATED,
)
def link_evidence(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    payload: ObligationEvidenceLinkIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> dict:
    try:
        service.link_evidence_document(
            db,
            fund_id=fund_id,
            actor=actor,
            obligation_id=obligation_id,
            document_id=payload.document_id,
            version_id=payload.version_id,
        )
        return {"status": "linked"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/obligations/{obligation_id}/workflow/mark-in-progress")
def mark_in_progress(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> dict:
    try:
        service.mark_in_progress(
            db, fund_id=fund_id, actor=actor, obligation_id=obligation_id,
        )
        return {"status": "in_progress"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/obligations/{obligation_id}/workflow/close")
def close_obligation(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> dict:
    try:
        service.close_obligation(
            db, fund_id=fund_id, actor=actor, obligation_id=obligation_id,
        )
        return {"status": "closed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/obligations/{obligation_id}/workflow/reopen")
def reopen_obligation(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> dict:
    try:
        service.reopen_obligation(
            db, fund_id=fund_id, actor=actor, obligation_id=obligation_id,
        )
        return {"status": "reopened"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/obligations/{obligation_id}/audit", response_model=list[AuditEventOut])
def obligation_audit(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> list[AuditEventOut]:
    try:
        items = service.get_obligation_audit(
            db, fund_id=fund_id, obligation_id=obligation_id,
        )
        return [AuditEventOut.model_validate(item) for item in items]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/obligations", response_model=ObligationOut, status_code=status.HTTP_201_CREATED,
)
def create_obligation(
    fund_id: uuid.UUID,
    payload: ObligationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> ObligationOut:
    obligation = service.create_obligation(
        db, fund_id=fund_id, actor=actor, payload=payload,
    )
    return ObligationOut.model_validate(obligation)


@router.post("/obligations/extract")
def extract_obligations(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
):
    """Extract obligations from fund-data-index using LLM analysis."""
    import logging
    logger = logging.getLogger(__name__)
    from ai_engine.extraction.compliance_extractor import extract_obligations_from_index

    try:
        created = extract_obligations_from_index(db, fund_id=fund_id, actor=actor)
    except Exception as exc:
        logger.error("compliance extract endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {type(exc).__name__}: {exc}",
        )
    return {
        "created": len(created),
        "obligations": [{"id": str(o.id), "name": o.name} for o in created],
    }


@router.get("/obligation-status", response_model=Page[ObligationStatusOut])
def get_obligation_status(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> Page[ObligationStatusOut]:
    items = service.list_obligation_status(
        db, fund_id=fund_id, limit=limit, offset=offset,
    )
    return Page(
        items=[ObligationStatusOut.model_validate(item) for item in items],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.post("/obligation-status/recompute", response_model=Page[ObligationStatusOut])
def recompute_obligation_status(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> Page[ObligationStatusOut]:
    items = service.recompute_obligation_status(db, fund_id=fund_id, actor=actor)
    return Page(
        items=[ObligationStatusOut.model_validate(item) for item in items],
        total=len(items),
        limit=len(items),
        offset=0,
    )


@router.post("/gaps/recompute", response_model=Page[ObligationOut])
def recompute_gaps(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> Page[ObligationOut]:
    # Minimal v1: gaps are represented as AI-created obligations (prefix).
    items = list(
        db.execute(
            select(Obligation).where(
                Obligation.fund_id == fund_id, Obligation.name.like(f"{AI_GAP_PREFIX}%"),
            ),
        )
        .scalars()
        .all(),
    )
    return Page(
        items=[ObligationOut.model_validate(item) for item in items],
        total=len(items),
        limit=len(items),
        offset=0,
    )


@router.get("/gaps", response_model=Page[ObligationOut])
def list_gaps(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> Page[ObligationOut]:
    stmt = (
        select(Obligation)
        .where(Obligation.fund_id == fund_id, Obligation.name.like(f"{AI_GAP_PREFIX}%"))
        .offset(offset)
        .limit(limit)
    )
    items = list(db.execute(stmt).scalars().all())
    total = db.execute(
        select(sa_func.count()).select_from(Obligation).where(
            Obligation.fund_id == fund_id, Obligation.name.like(f"{AI_GAP_PREFIX}%"),
        ),
    ).scalar_one()
    return Page(
        items=[ObligationOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── ObligationRequirement CRUD endpoints ─────────────────────────────


@router.get(
    "/obligations/{obligation_id}/requirements",
    response_model=list[ObligationRequirementOut],
)
def list_requirements(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles([Role.COMPLIANCE, Role.ADMIN, Role.AUDITOR, Role.INVESTMENT_TEAM]),
    ),
) -> list[ObligationRequirementOut]:
    try:
        items = service.list_requirements(
            db, fund_id=fund_id, obligation_id=obligation_id,
        )
        return [ObligationRequirementOut.model_validate(item) for item in items]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/obligations/{obligation_id}/requirements",
    response_model=ObligationRequirementOut,
    status_code=status.HTTP_201_CREATED,
)
def add_requirement(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    payload: ObligationRequirementCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
) -> ObligationRequirementOut:
    try:
        requirement = service.add_requirement(
            db,
            fund_id=fund_id,
            actor=actor,
            obligation_id=obligation_id,
            payload=payload,
        )
        return ObligationRequirementOut.model_validate(requirement)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/obligations/{obligation_id}/requirements/{req_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_requirement(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    req_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.COMPLIANCE, Role.ADMIN])),
):
    try:
        service.delete_requirement(
            db,
            fund_id=fund_id,
            actor=actor,
            obligation_id=obligation_id,
            requirement_id=req_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
