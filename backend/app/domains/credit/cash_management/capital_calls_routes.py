"""Capital Call and Distribution routes."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_fund_access, require_role
from app.domains.credit.cash_management.models.capital_calls import (
    CapitalCall,
    CapitalCallAllocation,
    Distribution,
)

router = APIRouter(
    prefix="/funds/{fund_id}/cash",
    tags=["Capital Calls"],
    dependencies=[Depends(require_fund_access())],
)


class CapitalCallCreate(BaseModel):
    call_date: date
    due_date: date
    total_amount: float
    purpose: str
    purpose_detail: str | None = None
    deal_id: uuid.UUID | None = None
    notes: str | None = None


class AllocationCreate(BaseModel):
    investor_name: str
    investor_id: str | None = None
    commitment_amount: float
    pro_rata_pct: float
    called_amount: float


class PaymentRecord(BaseModel):
    paid_amount: float
    paid_date: date
    bank_reference: str | None = None


class DistributionCreate(BaseModel):
    distribution_date: date
    total_amount: float
    distribution_type: str
    source_description: str | None = None
    notes: str | None = None
    allocations: list[dict] | None = None


@router.get("/capital-calls")
def list_capital_calls(
    fund_id: uuid.UUID,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    stmt = select(CapitalCall).where(CapitalCall.fund_id == fund_id)
    if status:
        stmt = stmt.where(CapitalCall.status == status)
    stmt = stmt.order_by(CapitalCall.call_date.desc())

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = list(db.execute(stmt.limit(limit).offset(offset)).scalars().all())

    return {
        "total": total,
        "capitalCalls": [_call_to_dict(c) for c in rows],
    }


@router.post("/capital-calls")
def create_capital_call(
    fund_id: uuid.UUID,
    payload: CapitalCallCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    last_num = db.execute(
        select(func.max(CapitalCall.call_number)).where(CapitalCall.fund_id == fund_id),
    ).scalar() or 0

    call = CapitalCall(
        fund_id=fund_id,
        call_number=last_num + 1,
        **payload.model_dump(),
    )
    db.add(call)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="capital_call.created",
        entity_type="CapitalCall",
        entity_id=str(call.id),
        before=None,
        after=payload.model_dump(mode="json"),
    )

    db.commit()
    return _call_to_dict(call)


@router.get("/capital-calls/{call_id}")
def get_capital_call(
    fund_id: uuid.UUID,
    call_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    call = db.execute(
        select(CapitalCall).where(CapitalCall.id == call_id, CapitalCall.fund_id == fund_id),
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Capital call not found")

    allocations = list(
        db.execute(
            select(CapitalCallAllocation)
            .where(CapitalCallAllocation.capital_call_id == call_id)
            .order_by(CapitalCallAllocation.investor_name),
        ).scalars().all(),
    )

    result = _call_to_dict(call)
    result["allocations"] = [
        {
            "id": str(a.id),
            "investorName": a.investor_name,
            "investorId": a.investor_id,
            "commitmentAmount": float(a.commitment_amount),
            "proRataPct": float(a.pro_rata_pct),
            "calledAmount": float(a.called_amount),
            "paidAmount": float(a.paid_amount),
            "paidDate": a.paid_date.isoformat() if a.paid_date else None,
            "isPaid": a.is_paid,
            "bankReference": a.bank_reference,
        }
        for a in allocations
    ]
    return result


@router.post("/capital-calls/{call_id}/allocations")
def add_allocations(
    fund_id: uuid.UUID,
    call_id: uuid.UUID,
    allocations: list[AllocationCreate],
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    call = db.execute(
        select(CapitalCall).where(CapitalCall.id == call_id, CapitalCall.fund_id == fund_id),
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Capital call not found")

    created = []
    for alloc in allocations:
        allocation = CapitalCallAllocation(
            fund_id=fund_id,
            capital_call_id=call_id,
            **alloc.model_dump(),
        )
        db.add(allocation)
        created.append(allocation)

    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="capital_call.allocations_added",
        entity_type="CapitalCall",
        entity_id=str(call_id),
        before=None,
        after={"count": len(created), "total_called": sum(float(a.called_amount) for a in created)},
    )

    db.commit()
    return {"callId": str(call_id), "allocationsAdded": len(created)}


@router.post("/capital-calls/{call_id}/issue")
def issue_capital_call(
    fund_id: uuid.UUID,
    call_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    """Transition capital call from DRAFT to ISSUED."""
    call = db.execute(
        select(CapitalCall).where(CapitalCall.id == call_id, CapitalCall.fund_id == fund_id),
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Capital call not found")
    if call.status != "DRAFT":
        raise HTTPException(status_code=409, detail=f"Cannot issue: current status is {call.status}")

    alloc_count = db.execute(
        select(func.count(CapitalCallAllocation.id))
        .where(CapitalCallAllocation.capital_call_id == call_id),
    ).scalar() or 0
    if alloc_count == 0:
        raise HTTPException(status_code=400, detail="Cannot issue without allocations")

    call.status = "ISSUED"
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="capital_call.issued",
        entity_type="CapitalCall",
        entity_id=str(call_id),
        before={"status": "DRAFT"},
        after={"status": "ISSUED"},
    )

    db.commit()
    return {"callId": str(call_id), "status": "ISSUED"}


@router.post("/capital-calls/{call_id}/allocations/{alloc_id}/payment")
def record_payment(
    fund_id: uuid.UUID,
    call_id: uuid.UUID,
    alloc_id: uuid.UUID,
    payload: PaymentRecord,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM"])),
) -> dict[str, Any]:
    """Record an investor payment against a capital call allocation."""
    alloc = db.execute(
        select(CapitalCallAllocation).where(
            CapitalCallAllocation.id == alloc_id,
            CapitalCallAllocation.capital_call_id == call_id,
            CapitalCallAllocation.fund_id == fund_id,
        ),
    ).scalar_one_or_none()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")

    alloc.paid_amount = payload.paid_amount
    alloc.paid_date = payload.paid_date
    alloc.bank_reference = payload.bank_reference
    alloc.is_paid = payload.paid_amount >= float(alloc.called_amount)
    db.flush()

    call = db.execute(select(CapitalCall).where(CapitalCall.id == call_id)).scalar_one()
    total_paid = db.execute(
        select(func.sum(CapitalCallAllocation.paid_amount))
        .where(CapitalCallAllocation.capital_call_id == call_id),
    ).scalar() or 0

    call.total_received = float(total_paid)
    if float(total_paid) >= float(call.total_amount):
        call.status = "FULLY_FUNDED"
    elif float(total_paid) > 0:
        call.status = "PARTIALLY_FUNDED"
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="capital_call.payment_recorded",
        entity_type="CapitalCallAllocation",
        entity_id=str(alloc_id),
        before=None,
        after={"paid_amount": payload.paid_amount, "call_status": call.status},
    )

    db.commit()
    return {
        "allocationId": str(alloc_id),
        "isPaid": alloc.is_paid,
        "callStatus": call.status,
        "totalReceived": float(call.total_received),
    }


@router.get("/distributions")
def list_distributions(
    fund_id: uuid.UUID,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    stmt = select(Distribution).where(Distribution.fund_id == fund_id)
    if status:
        stmt = stmt.where(Distribution.status == status)
    rows = list(
        db.execute(stmt.order_by(Distribution.distribution_date.desc()).limit(limit)).scalars().all(),
    )
    return {
        "count": len(rows),
        "distributions": [_dist_to_dict(d) for d in rows],
    }


@router.post("/distributions")
def create_distribution(
    fund_id: uuid.UUID,
    payload: DistributionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    last_num = db.execute(
        select(func.max(Distribution.distribution_number)).where(Distribution.fund_id == fund_id),
    ).scalar() or 0

    dist = Distribution(
        fund_id=fund_id,
        distribution_number=last_num + 1,
        **payload.model_dump(),
    )
    db.add(dist)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="distribution.created",
        entity_type="Distribution",
        entity_id=str(dist.id),
        before=None,
        after=payload.model_dump(mode="json"),
    )

    db.commit()
    return _dist_to_dict(dist)


def _call_to_dict(call: CapitalCall) -> dict[str, Any]:
    return {
        "id": str(call.id),
        "callNumber": call.call_number,
        "callDate": call.call_date.isoformat(),
        "dueDate": call.due_date.isoformat(),
        "totalAmount": float(call.total_amount),
        "currency": call.currency,
        "purpose": call.purpose,
        "status": call.status,
        "totalReceived": float(call.total_received),
        "fundingPct": round(float(call.total_received) / float(call.total_amount) * 100, 1)
        if call.total_amount
        else 0,
        "dealId": str(call.deal_id) if call.deal_id else None,
        "notes": call.notes,
        "createdAt": call.created_at.isoformat() if call.created_at else None,
    }


def _dist_to_dict(distribution: Distribution) -> dict[str, Any]:
    return {
        "id": str(distribution.id),
        "distributionNumber": distribution.distribution_number,
        "distributionDate": distribution.distribution_date.isoformat(),
        "totalAmount": float(distribution.total_amount),
        "currency": distribution.currency,
        "distributionType": distribution.distribution_type,
        "status": distribution.status,
        "sourceDescription": distribution.source_description,
        "notes": distribution.notes,
        "allocations": distribution.allocations,
        "createdAt": distribution.created_at.isoformat() if distribution.created_at else None,
    }
