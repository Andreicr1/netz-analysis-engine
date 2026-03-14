from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import (
    get_actor,
    require_readonly_allowed,
    require_roles,
)
from app.domains.credit.cash_management.models.cash import CashTransaction
from app.domains.credit.modules.adobe_sign.schemas import (
    SendForESignatureRequest,
    SendForESignatureResponse,
)
from app.domains.credit.modules.signatures import service
from app.domains.credit.modules.signatures.schemas import (
    Page,
    RejectRequestIn,
    SignatureRequestDetailOut,
    SignatureRequestOut,
    SignRequestIn,
)
from app.shared.enums import Role

router = APIRouter(prefix="/signatures", tags=["signatures"])


def _limit(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(0, ge=0, le=10_000)) -> int:
    return offset


@router.get("", response_model=Page[SignatureRequestOut])
def list_signature_requests(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    _role_guard: Actor = Depends(
        require_roles(
            [
                Role.DIRECTOR,
                Role.GP,
                Role.COMPLIANCE,
                Role.INVESTMENT_TEAM,
                Role.AUDITOR,
                Role.ADMIN,
            ]
        )
    ),
) -> Page[SignatureRequestOut]:
    items = service.list_requests(db, fund_id=fund_id, limit=limit, offset=offset)
    return Page(items=items, limit=limit, offset=offset)


@router.get("/{request_id}", response_model=SignatureRequestDetailOut)
def get_signature_request(
    fund_id: uuid.UUID,
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(
        require_roles(
            [
                Role.DIRECTOR,
                Role.GP,
                Role.COMPLIANCE,
                Role.INVESTMENT_TEAM,
                Role.AUDITOR,
                Role.ADMIN,
            ]
        )
    ),
) -> SignatureRequestDetailOut:
    tx = db.execute(
        select(CashTransaction).where(
            CashTransaction.fund_id == fund_id, CashTransaction.id == request_id
        )
    ).scalar_one_or_none()
    if not tx:
        # Keep error consistent with service.sign/reject
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Signature request not found"
        )

    out = service.build_detail(db, fund_id=fund_id, tx=tx)
    return SignatureRequestDetailOut(**out)


@router.post("/{request_id}/sign", response_model=SignatureRequestDetailOut)
def sign_request(
    fund_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: SignRequestIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.DIRECTOR, Role.ADMIN])),
) -> SignatureRequestDetailOut:
    out = service.sign(
        db, fund_id=fund_id, actor=actor, tx_id=request_id, comment=payload.comment
    )
    return SignatureRequestDetailOut(**out)


@router.post("/{request_id}/reject", response_model=SignatureRequestDetailOut)
def reject_request(
    fund_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: RejectRequestIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.DIRECTOR, Role.ADMIN])),
) -> SignatureRequestDetailOut:
    out = service.reject(
        db, fund_id=fund_id, actor=actor, tx_id=request_id, reason=payload.reason
    )
    return SignatureRequestDetailOut(**out)


@router.post("/{request_id}/execution-pack")
def execution_pack(
    fund_id: uuid.UUID,
    request_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(
        require_roles([Role.DIRECTOR, Role.GP, Role.COMPLIANCE, Role.ADMIN])
    ),
) -> dict:
    return service.generate_execution_pack(
        db, fund_id=fund_id, actor=actor, tx_id=request_id
    )


@router.post(
    "/{request_id}/send-for-esignature", response_model=SendForESignatureResponse
)
def send_for_esignature(
    fund_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: SendForESignatureRequest | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
    _role_guard: Actor = Depends(require_roles([Role.DIRECTOR, Role.GP, Role.ADMIN])),
) -> SendForESignatureResponse:
    """Send a transfer order to Adobe Sign for e-signature by fund directors."""
    from app.domains.credit.modules.adobe_sign import service as adobe_service

    return adobe_service.send_transfer_order_for_esignature(
        db,
        fund_id=fund_id,
        tx_id=request_id,
        actor=actor,
        message=payload.message if payload else None,
    )
