from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import require_role
from app.domains.credit.counterparties.schemas import (
    BankAccountChangeRead,
    BankAccountChangeRequest,
    BankAccountChangeReview,
    BankAccountRead,
    CounterpartyCreate,
    CounterpartyDocumentLink,
    CounterpartyDocumentRead,
    CounterpartyListResponse,
    CounterpartyRead,
    CounterpartyUpdate,
)
from app.domains.credit.counterparties.service import (
    approve_bank_account_change,
    archive_counterparty,
    create_counterparty,
    get_counterparty,
    link_document,
    list_bank_accounts,
    list_counterparties,
    list_documents,
    list_pending_changes,
    request_bank_account_change,
    unlink_document,
    update_counterparty,
)

router = APIRouter(
    prefix="/counterparties",
    tags=["Counterparty Registry"],
)


def _require_fund_access(fund_id: uuid.UUID, actor: Actor) -> None:
    if settings.AUTHZ_BYPASS_ENABLED:
        return
    if not actor.can_access_fund(fund_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden for this fund",
        )


# ── Counterparty CRUD ────────────────────────────────────────────────


@router.get("", response_model=CounterpartyListResponse)
def list_counterparties_route(
    fund_id: uuid.UUID,
    entity_type: str | None = Query(default=None),
    counterparty_status: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR", "DIRECTOR"])),
):
    _require_fund_access(fund_id, actor)
    rows, total = list_counterparties(
        db,
        fund_id=fund_id,
        entity_type=entity_type,
        status=counterparty_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [CounterpartyRead.model_validate(r) for r in rows],
        "total": total,
    }


@router.get("/{counterparty_id}", response_model=CounterpartyRead)
def get_counterparty_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR", "DIRECTOR"])),
):
    _require_fund_access(fund_id, actor)
    cpty = get_counterparty(db, fund_id=fund_id, counterparty_id=counterparty_id)
    if not cpty:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    return CounterpartyRead.model_validate(cpty)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CounterpartyRead)
def create_counterparty_route(
    fund_id: uuid.UUID,
    payload: CounterpartyCreate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    cpty = create_counterparty(db, fund_id=fund_id, actor=actor, payload=payload)
    db.commit()
    return CounterpartyRead.model_validate(cpty)


@router.patch("/{counterparty_id}", response_model=CounterpartyRead)
def update_counterparty_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    payload: CounterpartyUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        cpty = update_counterparty(
            db, fund_id=fund_id, actor=actor, counterparty_id=counterparty_id, payload=payload,
        )
        db.commit()
        return CounterpartyRead.model_validate(cpty)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{counterparty_id}/archive", response_model=CounterpartyRead)
def archive_counterparty_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        cpty = archive_counterparty(
            db, fund_id=fund_id, actor=actor, counterparty_id=counterparty_id,
        )
        db.commit()
        return CounterpartyRead.model_validate(cpty)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── Bank Account Changes (four-eyes) ────────────────────────────────


@router.get("/{counterparty_id}/bank-accounts", response_model=list[BankAccountRead])
def list_bank_accounts_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR", "DIRECTOR"])),
):
    _require_fund_access(fund_id, actor)
    accounts = list_bank_accounts(db, fund_id=fund_id, counterparty_id=counterparty_id, include_inactive=include_inactive)
    return [BankAccountRead.model_validate(a) for a in accounts]


@router.post("/{counterparty_id}/bank-account-changes", status_code=status.HTTP_201_CREATED, response_model=BankAccountChangeRead)
def request_bank_account_change_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    payload: BankAccountChangeRequest,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        change = request_bank_account_change(
            db, fund_id=fund_id, actor=actor, counterparty_id=counterparty_id, payload=payload,
        )
        db.commit()
        return BankAccountChangeRead.model_validate(change)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{counterparty_id}/bank-account-changes", response_model=list[BankAccountChangeRead])
def list_pending_changes_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    changes = list_pending_changes(db, fund_id=fund_id, counterparty_id=counterparty_id)
    return [BankAccountChangeRead.model_validate(c) for c in changes]


@router.post("/bank-account-changes/{change_id}/review", response_model=BankAccountChangeRead)
def review_bank_account_change_route(
    fund_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: BankAccountChangeReview,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        change, _account = approve_bank_account_change(
            db, fund_id=fund_id, actor=actor, change_id=change_id, review=payload,
        )
        db.commit()
        return BankAccountChangeRead.model_validate(change)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── Document Links ───────────────────────────────────────────────────


@router.get("/{counterparty_id}/documents", response_model=list[CounterpartyDocumentRead])
def list_documents_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR", "DIRECTOR"])),
):
    _require_fund_access(fund_id, actor)
    docs = list_documents(db, fund_id=fund_id, counterparty_id=counterparty_id)
    return [CounterpartyDocumentRead.model_validate(d) for d in docs]


@router.post("/{counterparty_id}/documents", status_code=status.HTTP_201_CREATED, response_model=CounterpartyDocumentRead)
def link_document_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    payload: CounterpartyDocumentLink,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        link = link_document(
            db, fund_id=fund_id, actor=actor, counterparty_id=counterparty_id, payload=payload,
        )
        db.commit()
        return CounterpartyDocumentRead.model_validate(link)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{counterparty_id}/documents/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_document_route(
    fund_id: uuid.UUID,
    counterparty_id: uuid.UUID,
    link_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        unlink_document(db, fund_id=fund_id, actor=actor, counterparty_id=counterparty_id, link_id=link_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
