"""
Compliance Obligation Engine — Unified (DB-backed).

MIGRATION NOTE (2026-03-07): This router previously used a JSON file store.
It now delegates to the DB-backed compliance service, making PostgreSQL the
single source of truth for all compliance obligations.

Prefix: /compliance/engine  (kept for backward compatibility with frontend)

Endpoints:
  GET    /compliance/engine/obligations
  POST   /compliance/engine/obligations
  PATCH  /compliance/engine/obligations/{obligation_id}/status
  POST   /compliance/engine/seed
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.modules.compliance.models import Obligation
from app.domains.credit.modules.compliance.schemas import ObligationCreate
from app.domains.credit.modules.compliance.service import (
    close_obligation,
    mark_in_progress,
    reopen_obligation,
)
from app.domains.credit.modules.compliance.service import (
    create_obligation as db_create_obligation,
)
from app.shared.enums import Role
from app.shared.utils import sa_model_to_dict


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(prefix="/compliance/engine", tags=["compliance-engine"])


class CreateObligationRequest(BaseModel):
    title: str
    description: str = ""
    sourceType: str = "CIMA"
    documentReference: str = ""
    legalBasis: str | None = None
    frequency: str = "ANNUAL"
    responsibleParty: str | None = None
    nextDueDate: str | None = None
    riskLevel: str = "MEDIUM"


class UpdateStatusRequest(BaseModel):
    status: str


@router.get("/obligations", summary="List all canonical obligations")
def list_obligations(
    fund_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
) -> dict[str, Any]:
    stmt = select(Obligation)
    if fund_id:
        stmt = stmt.where(Obligation.fund_id == fund_id)
    obligations = list(
        db.execute(
            stmt.order_by(Obligation.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
    )
    # sa_model_to_dict is the codebase-wide serialization pattern (20+ modules);
    # a Pydantic response_model would add coupling for minimal gain here.
    return {
        "count": len(obligations),
        "obligations": [sa_model_to_dict(o) for o in obligations],
    }


@router.post("/obligations", status_code=201, summary="Create a new obligation")
def create_obligation(
    req: CreateObligationRequest,
    fund_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> dict[str, Any]:
    payload = ObligationCreate(
        name=req.title,
        description=req.description,
        regulator=req.sourceType,
        source_type=req.sourceType,
        frequency=req.frequency,
        risk_level=req.riskLevel,
        responsible_party=req.responsibleParty,
        document_reference=req.documentReference,
        legal_basis=req.legalBasis,
    )
    obligation = db_create_obligation(
        db=db, fund_id=fund_id or uuid.UUID("00000000-0000-0000-0000-000000000000"),
        payload=payload, actor=actor,
    )
    db.commit()
    return {"obligation_id": str(obligation.id), "title": obligation.name}


@router.patch(
    "/obligations/{obligation_id}/status",
    summary="Update the status of an obligation",
)
def update_obligation_status(
    obligation_id: uuid.UUID,
    req: UpdateStatusRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> dict[str, Any]:
    target_status = req.status.upper()

    if target_status == "IN_PROGRESS":
        mark_in_progress(db=db, obligation_id=obligation_id, actor=actor)
    elif target_status in ("COMPLETED", "CLOSED"):
        close_obligation(db=db, obligation_id=obligation_id, actor=actor)
    elif target_status in ("PENDING", "OPEN"):
        reopen_obligation(db=db, obligation_id=obligation_id, actor=actor)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown status: {req.status}")

    db.commit()
    return {"obligation_id": str(obligation_id), "status": target_status}


@router.post("/seed", summary="Seed canonical obligations (creates in DB if empty)")
def seed_obligations(
    fund_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> dict[str, Any]:
    effective_fund_id = fund_id or uuid.UUID("00000000-0000-0000-0000-000000000000")

    existing = db.execute(
        select(Obligation).where(Obligation.fund_id == effective_fund_id).limit(1)
    ).scalar_one_or_none()

    if existing:
        return {"seeded": 0, "message": "Obligations already exist for this fund"}

    seeds = [
        {"name": "Annual CIMA Regulatory Filing", "regulator": "CIMA", "source_type": "CIMA",
         "frequency": "ANNUAL", "risk_level": "HIGH", "responsible_party": "Compliance Officer",
         "document_reference": "CIMA Mutual Funds Act", "legal_basis": "Section 4(3) MFA"},
        {"name": "AML/KYC Policy Annual Review", "regulator": "CIMA", "source_type": "CIMA",
         "frequency": "ANNUAL", "risk_level": "HIGH", "responsible_party": "MLRO",
         "document_reference": "AML Regulations 2020", "legal_basis": "Regulation 15"},
        {"name": "Investment Management Agreement Review", "regulator": "IMA", "source_type": "IMA",
         "frequency": "ANNUAL", "risk_level": "MEDIUM", "responsible_party": "Fund Manager",
         "document_reference": "IMA Schedule 3", "legal_basis": "Clause 12.1"},
        {"name": "Fund Administrator Oversight", "regulator": "SERVICE_CONTRACT", "source_type": "SERVICE_CONTRACT",
         "frequency": "QUARTERLY", "risk_level": "MEDIUM", "responsible_party": "Operations",
         "document_reference": "Administration Agreement", "legal_basis": "Section 8"},
        {"name": "Director Registration Renewal", "regulator": "CIMA", "source_type": "CIMA",
         "frequency": "ANNUAL", "risk_level": "HIGH", "responsible_party": "Company Secretary",
         "document_reference": "Directors Registration Act", "legal_basis": "Section 5"},
    ]

    for seed in seeds:
        ob = Obligation(fund_id=effective_fund_id, **seed)
        db.add(ob)

    db.flush()
    db.commit()
    return {"seeded": len(seeds), "fund_id": str(effective_fund_id)}
