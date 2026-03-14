"""Routes for IC Committee e-signature voting via Adobe Sign."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_fund_access, require_role
from app.domains.credit.modules.adobe_sign.schemas import (
    SendToCommitteeRequest,
    SendToCommitteeResponse,
)

router = APIRouter(
    tags=["IC Memos – Committee Voting"], dependencies=[Depends(require_fund_access())]
)


@router.post(
    "/funds/{fund_id}/ic-memos/{memo_id}/send-to-committee",
    response_model=SendToCommitteeResponse,
)
def send_to_committee(
    fund_id: uuid.UUID,
    memo_id: uuid.UUID,
    payload: SendToCommitteeRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "INVESTMENT_TEAM", "GP"])),
) -> SendToCommitteeResponse:
    """Send an IC Memo to committee members for voting via Adobe Sign.

    Each committee member receives the memo PDF with Approve/Refuse
    checkboxes and a signature field.  Majority rule applies (2+ of 3).
    """
    from app.domains.credit.modules.adobe_sign import service as adobe_service

    return adobe_service.send_ic_memo_to_committee(
        db,
        memo_id=memo_id,
        committee_member_emails=payload.committee_member_emails,
        actor=actor,
        message=payload.message,
    )
