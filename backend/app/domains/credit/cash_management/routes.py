from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_role
from app.domains.credit.cash_management.enums import (
    CashTransactionDirection,
    CashTransactionStatus,
    ReconciliationStatus,
)
from app.domains.credit.cash_management.models.bank_statements import (
    BankStatementLine,
    BankStatementUpload,
)
from app.domains.credit.cash_management.models.cash import CashTransaction, CashTransactionApproval
from app.domains.credit.cash_management.models.reconciliation_matches import ReconciliationMatch
from app.domains.credit.cash_management.service import (
    approve,
    create_transaction,
    generate_instructions,
    mark_executed,
    mark_sent_to_admin,
    reject_transaction,
    submit_transaction,
)
from app.domains.credit.cash_management.services.reconciliation import (
    add_statement_line,
    detect_missing_transactions,
    detect_unexplained_outflows,
    match_statement_lines,
    upload_bank_statement,
)
from app.services.blob_storage import upload_bytes_idempotent


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(prefix="/funds/{fund_id}/cash", tags=["Cash Management"])


@router.get("/snapshot")
def snapshot(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    _require_fund_access(fund_id, actor)

    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

    tx_stats = db.execute(
        select(
            func.coalesce(func.sum(case(
                (CashTransaction.direction == CashTransactionDirection.INFLOW, CashTransaction.amount),
            )), 0).label("inflows"),
            func.coalesce(func.sum(case(
                (CashTransaction.direction == CashTransactionDirection.OUTFLOW, CashTransaction.amount),
            )), 0).label("outflows"),
            func.count(case((
                CashTransaction.status.in_([
                    CashTransactionStatus.PENDING_APPROVAL,
                    CashTransactionStatus.APPROVED,
                    CashTransactionStatus.SENT_TO_ADMIN,
                ]), 1,
            ))).label("pending"),
            func.count(case((
                (CashTransaction.status == CashTransactionStatus.EXECUTED)
                & CashTransaction.execution_confirmed_at.isnot(None)
                & (CashTransaction.execution_confirmed_at >= month_start), 1,
            ))).label("executed_month"),
        )
        .select_from(CashTransaction)
        .where(CashTransaction.fund_id == fund_id, CashTransaction.currency == "USD"),
    ).one()

    recon_stats = db.execute(
        select(
            func.count(case((
                BankStatementLine.reconciliation_status == ReconciliationStatus.UNMATCHED, 1,
            ))).label("unreconciled"),
            func.max(case((
                BankStatementLine.reconciliation_status.in_([ReconciliationStatus.MATCHED, ReconciliationStatus.DISCREPANCY]),
                BankStatementLine.reconciled_at,
            ))).label("last_recon"),
        )
        .select_from(BankStatementLine)
        .where(BankStatementLine.fund_id == fund_id),
    ).one()

    return {
        "generated_at_utc": now.isoformat(),
        "total_inflows_usd": float(tx_stats.inflows),
        "total_outflows_usd": float(tx_stats.outflows),
        "pending_signatures": int(tx_stats.pending or 0),
        "executed_transactions_month": int(tx_stats.executed_month or 0),
        "unreconciled_bank_lines": int(recon_stats.unreconciled or 0),
        "last_reconciliation_date": recon_stats.last_recon.isoformat() if recon_stats.last_recon else None,
    }


def _justification(tx: CashTransaction) -> tuple[str | None, str | None]:
    if tx.investment_memo_document_id:
        return "INVESTMENT_MEMO", str(tx.investment_memo_document_id)

    basis = tx.policy_basis or []
    if isinstance(basis, list):
        for item in basis:
            if isinstance(item, dict) and item.get("document_id"):
                return "OM_CLAUSE", str(item.get("document_id"))
    return None, None


def _api_type(tx: CashTransaction) -> str:
    t = tx.type.value
    if t in ("FUND_EXPENSE", "EXPENSE"):
        return "EXPENSE"
    if t == "INVESTMENT":
        return "INVESTMENT"
    if t in ("BANK_FEE", "FEE"):
        return "FEE"
    if t in ("LP_SUBSCRIPTION", "CAPITAL_CALL"):
        return "INCOME"
    return "OTHER"


def _api_status(tx: CashTransaction) -> str:
    if getattr(tx, "reconciled_at", None):
        return "RECONCILED"
    if tx.status == CashTransactionStatus.DRAFT:
        return "DRAFT"
    if tx.status == CashTransactionStatus.PENDING_APPROVAL:
        return "PENDING_SIGNATURE"
    if tx.status in (CashTransactionStatus.APPROVED, CashTransactionStatus.SENT_TO_ADMIN):
        return "SIGNED"
    if tx.status == CashTransactionStatus.EXECUTED:
        return "EXECUTED"
    return tx.status.value


def _get_director_count(db: Session, fund_id: uuid.UUID, tx_id: uuid.UUID) -> int:
    """Count distinct director approvers for a transaction in a single DB query."""
    return db.execute(
        select(func.count(func.distinct(CashTransactionApproval.approver_name)))
        .where(
            CashTransactionApproval.fund_id == fund_id,
            CashTransactionApproval.transaction_id == tx_id,
            CashTransactionApproval.approver_role == "DIRECTOR",
        ),
    ).scalar_one()


def _tx_out(tx: CashTransaction, *, director_signatures_count: int | None = None) -> dict:
    j_type, j_doc = _justification(tx)
    return {
        # EPIC 10 canonical fields
        "id": str(tx.id),
        "fund_id": str(tx.fund_id),
        "type": _api_type(tx),
        "direction": tx.direction.value,
        "amount_usd": float(tx.amount),
        "counterparty": tx.beneficiary_name,
        "justification_type": j_type,
        "justification_document_id": j_doc,
        "status": _api_status(tx),
        "signature_status": {
            "required": 2,
            "current": director_signatures_count,
        },
        "reconciled": bool(getattr(tx, "reconciled_at", None)),
        "reconciled_at": tx.reconciled_at.isoformat() if getattr(tx, "reconciled_at", None) else None,
        "reconciled_by": getattr(tx, "reconciled_by", None),

        # Legacy / extended details (kept for backward compatibility)
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
        "value_date": tx.value_date.isoformat() if tx.value_date else None,
        "type_raw": tx.type.value,
        "amount": float(tx.amount),
        "currency": tx.currency,
        "status_raw": tx.status.value,
        "reference_code": tx.reference_code,
        "beneficiary_name": tx.beneficiary_name,
        "beneficiary_bank": tx.beneficiary_bank,
        "beneficiary_account": tx.beneficiary_account,
        "payment_reference": tx.payment_reference,
        "justification_text": tx.justification_text,
        "policy_basis": tx.policy_basis,
        "investment_memo_document_id": str(tx.investment_memo_document_id) if tx.investment_memo_document_id else None,
        "ic_approvals_count": int(tx.ic_approvals_count or 0),
        "sent_to_admin_at": tx.sent_to_admin_at.isoformat() if tx.sent_to_admin_at else None,
        "admin_contact": tx.admin_contact,
        "execution_confirmed_at": tx.execution_confirmed_at.isoformat() if tx.execution_confirmed_at else None,
        "bank_reference": tx.bank_reference,
        "notes": tx.notes,
        "instructions_blob_uri": tx.instructions_blob_uri,
        "evidence_bundle_blob_uri": tx.evidence_bundle_blob_uri,
        "evidence_bundle_sha256": tx.evidence_bundle_sha256,
    }


def _statement_out(s: BankStatementUpload) -> dict:
    return {
        "id": str(s.id),
        "fund_id": str(s.fund_id),
        "period_start": s.period_start.isoformat(),
        "period_end": s.period_end.isoformat(),
        "uploaded_by": s.uploaded_by,
        "uploaded_at": s.uploaded_at.isoformat(),
        "blob_path": s.blob_path,
        "original_filename": s.original_filename,
        "sha256": s.sha256,
        "notes": s.notes,
    }


def _line_out(line: BankStatementLine) -> dict:
    return {
        "id": str(line.id),
        "statement_id": str(line.statement_id),
        "value_date": line.value_date.isoformat(),
        "description": line.description,
        "amount_usd": float(line.amount_usd),
        "direction": line.direction.value,
        "matched_transaction_id": str(line.matched_transaction_id) if line.matched_transaction_id else None,
        "reconciliation_status": line.reconciliation_status.value,
        "reconciled_at": line.reconciled_at.isoformat() if line.reconciled_at else None,
        "reconciled_by": line.reconciled_by,
        "reconciliation_notes": line.reconciliation_notes,
    }


@router.post("/reconciliation/match")
def manual_match(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    """Manually match (or flag discrepancy) for a statement line.

    Payload:
      - statement_line_id: UUID
      - transaction_id: UUID (optional if discrepancy)
      - reconciliation_status: MATCHED | DISCREPANCY (optional, default MATCHED)
      - notes: optional
    """
    _require_fund_access(fund_id, actor)

    if "statement_line_id" not in payload:
        raise HTTPException(status_code=400, detail="statement_line_id is required")

    line_id = uuid.UUID(str(payload["statement_line_id"]))
    line = db.execute(
        select(BankStatementLine).where(
            BankStatementLine.fund_id == fund_id,
            BankStatementLine.id == line_id,
        ),
    ).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=404, detail="Statement line not found")

    if line.reconciliation_status != ReconciliationStatus.UNMATCHED:
        raise HTTPException(status_code=400, detail="Statement line is already reconciled")

    status_raw = payload.get("reconciliation_status") or ReconciliationStatus.MATCHED.value
    try:
        new_status = ReconciliationStatus(status_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid reconciliation_status")

    if new_status not in (ReconciliationStatus.MATCHED, ReconciliationStatus.DISCREPANCY):
        raise HTTPException(status_code=400, detail="Invalid reconciliation_status")

    tx_id_raw = payload.get("transaction_id")
    tx_id: uuid.UUID | None = uuid.UUID(str(tx_id_raw)) if tx_id_raw else None
    tx: CashTransaction | None = None
    if new_status == ReconciliationStatus.MATCHED:
        if not tx_id:
            raise HTTPException(status_code=400, detail="transaction_id is required for MATCHED")
        tx = db.execute(
            select(CashTransaction).where(
                CashTransaction.fund_id == fund_id,
                CashTransaction.id == tx_id,
            ),
        ).scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
    else:
        if tx_id:
            raise HTTPException(status_code=400, detail="transaction_id must be omitted for DISCREPANCY")

    before = _line_out(line)
    line.matched_transaction_id = tx.id if tx else None
    line.reconciliation_status = new_status
    line.reconciled_at = datetime.now(UTC)
    line.reconciled_by = actor.actor_id
    line.reconciliation_notes = payload.get("notes")
    line.updated_by = actor.actor_id

    # Append-only evidence of the reconciliation decision.
    existing_match = db.execute(
        select(ReconciliationMatch).where(ReconciliationMatch.fund_id == fund_id, ReconciliationMatch.bank_line_id == line.id),
    ).scalar_one_or_none()
    if existing_match:
        raise HTTPException(status_code=400, detail="Statement line already has a reconciliation match record")

    match_row = ReconciliationMatch(
        fund_id=fund_id,
        access_level="internal",
        bank_line_id=line.id,
        cash_transaction_id=(tx.id if tx else None),
        matched_by=actor.actor_id,
        matched_at=line.reconciled_at,
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(match_row)
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="BANK_LINE_MATCHED",
        entity_type="bank_statement_line",
        entity_id=line.id,
        before=before,
        after=_line_out(line),
    )

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="BANK_LINE_MATCHED",
        entity_type="reconciliation_match",
        entity_id=match_row.id,
        before=None,
        after={
            "bank_line_id": str(line.id),
            "cash_transaction_id": str(tx.id) if tx else None,
            "matched_by": actor.actor_id,
            "matched_at": line.reconciled_at.isoformat() if line.reconciled_at else None,
            "status": new_status.value,
        },
    )

    db.commit()
    db.refresh(line)
    return {"line": _line_out(line)}


@router.get("/transactions")
def list_transactions(
    fund_id: uuid.UUID,
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "DIRECTOR", "GP", "ADMIN", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    _require_fund_access(fund_id, actor)

    stmt = select(CashTransaction).where(CashTransaction.fund_id == fund_id)
    if status:
        try:
            st = CashTransactionStatus(status)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid status")
        stmt = stmt.where(CashTransaction.status == st)
    stmt = stmt.order_by(CashTransaction.created_at.desc()).limit(limit).offset(offset)

    txs = list(db.execute(stmt).scalars().all())
    if not txs:
        return {"items": []}

    tx_ids = [tx.id for tx in txs]
    director_counts_stmt = (
        select(
            CashTransactionApproval.transaction_id,
            func.count(func.distinct(CashTransactionApproval.approver_name)),
        )
        .where(
            CashTransactionApproval.fund_id == fund_id,
            CashTransactionApproval.transaction_id.in_(tx_ids),
            CashTransactionApproval.approver_role == "DIRECTOR",
        )
        .group_by(CashTransactionApproval.transaction_id)
    )
    director_map: dict[uuid.UUID, int] = dict(db.execute(director_counts_stmt).all())

    items = [_tx_out(tx, director_signatures_count=director_map.get(tx.id, 0)) for tx in txs]
    return {"items": items}


def _require_fund_access(fund_id: uuid.UUID, actor) -> None:
    if settings.AUTHZ_BYPASS_ENABLED:
        return
    if not actor.can_access_fund(fund_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this fund")


@router.get("/transactions/{tx_id}")
def get_transaction(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "DIRECTOR", "GP", "ADMIN", "AUDITOR"])),
):
    _require_fund_access(fund_id, actor)
    tx = db.execute(select(CashTransaction).where(CashTransaction.fund_id == fund_id, CashTransaction.id == tx_id)).scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return _tx_out(tx, director_signatures_count=_get_director_count(db, fund_id, tx.id))


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
def create_tx(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)

    api_type = str(payload.get("type") or "").strip().upper()
    api_direction = str(payload.get("direction") or "").strip().upper()
    amount_usd = payload.get("amount_usd")
    counterparty = payload.get("counterparty")
    justification_type = str(payload.get("justification_type") or "").strip().upper()
    justification_document_id = payload.get("justification_document_id")

    if api_type not in ("EXPENSE", "INVESTMENT", "INCOME", "FEE", "OTHER"):
        raise HTTPException(status_code=400, detail="type must be EXPENSE|INVESTMENT|INCOME|FEE|OTHER")
    if api_direction not in ("INFLOW", "OUTFLOW"):
        raise HTTPException(status_code=400, detail="direction must be INFLOW|OUTFLOW")
    if amount_usd is None:
        raise HTTPException(status_code=400, detail="amount_usd is required")
    if not counterparty:
        raise HTTPException(status_code=400, detail="counterparty is required")
    if justification_type not in ("OM_CLAUSE", "INVESTMENT_MEMO"):
        raise HTTPException(status_code=400, detail="justification_type must be OM_CLAUSE|INVESTMENT_MEMO")
    if not justification_document_id:
        raise HTTPException(status_code=400, detail="justification_document_id is required")

    type_map = {
        "EXPENSE": "FUND_EXPENSE",
        "INVESTMENT": "INVESTMENT",
        "INCOME": "CAPITAL_CALL",
        "FEE": "BANK_FEE",
        "OTHER": "OTHER",
    }

    svc_payload: dict = {
        "type": type_map[api_type],
        "direction": api_direction,
        "amount": float(amount_usd),
        "value_date": payload.get("value_date") or date.today().isoformat(),
        "beneficiary_name": str(counterparty),
        "payment_reference": payload.get("notes") or payload.get("reference"),
        "justification_text": payload.get("notes"),
        "notes": payload.get("notes"),
    }

    if justification_type == "INVESTMENT_MEMO":
        svc_payload["investment_memo_document_id"] = str(justification_document_id)
    else:
        svc_payload["policy_basis"] = [{"document_id": str(justification_document_id), "section": None, "excerpt": None}]

    try:
        tx = create_transaction(db, fund_id=fund_id, actor=actor, payload=svc_payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _tx_out(tx, director_signatures_count=0)


@router.post("/transactions/{tx_id}/submit")
def submit(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx = submit_transaction(db, fund_id=fund_id, actor=actor, tx_id=tx_id)
        return {"transaction_id": str(tx.id), "status": tx.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/transactions/{tx_id}/submit-signature")
def submit_signature(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)

    tx = db.execute(select(CashTransaction).where(CashTransaction.fund_id == fund_id, CashTransaction.id == tx_id)).scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    _, doc_id = _justification(tx)
    if not doc_id:
        raise HTTPException(status_code=400, detail="Cannot submit transaction without evidence document_id")

    if tx.type.value == "INVESTMENT" and int(tx.ic_approvals_count or 0) < 2:
        raise HTTPException(status_code=409, detail="Investment requires >=2 IC approvals before director signatures")

    before = _tx_out(tx, director_signatures_count=None)
    try:
        tx = submit_transaction(db, fund_id=fund_id, actor=actor, tx_id=tx_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="CASH_TRANSACTION_SUBMITTED_FOR_SIGNATURE",
        entity_type="cash_transaction",
        entity_id=tx.id,
        before=before,
        after={"transaction_id": str(tx.id), "status": tx.status.value},
    )
    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="SIGNATURE_REQUEST_CREATED",
        entity_type="signature_request",
        entity_id=tx.id,
        before=None,
        after={"transaction_id": str(tx.id)},
    )

    db.commit()
    db.refresh(tx)
    return _tx_out(tx, director_signatures_count=_get_director_count(db, fund_id, tx.id))


@router.patch("/transactions/{tx_id}/mark-executed")
def mark_executed_patch(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)

    try:
        tx = mark_executed(
            db,
            fund_id=fund_id,
            actor=actor,
            tx_id=tx_id,
            bank_reference=payload.get("bank_reference"),
            notes=payload.get("notes"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="CASH_TRANSACTION_EXECUTED_CONFIRMED",
        entity_type="cash_transaction",
        entity_id=tx.id,
        before=None,
        after={
            "transaction_id": str(tx.id),
            "bank_reference": tx.bank_reference,
            "executed_at": tx.execution_confirmed_at.isoformat() if tx.execution_confirmed_at else None,
        },
    )

    db.commit()
    db.refresh(tx)
    return _tx_out(tx, director_signatures_count=_get_director_count(db, fund_id, tx.id))


@router.patch("/transactions/{tx_id}/mark-reconciled")
def mark_reconciled(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)

    tx = db.execute(select(CashTransaction).where(CashTransaction.fund_id == fund_id, CashTransaction.id == tx_id)).scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.status != CashTransactionStatus.EXECUTED:
        raise HTTPException(status_code=409, detail="Only EXECUTED transactions can be marked reconciled")

    has_match = db.execute(
        select(func.count()).select_from(BankStatementLine).where(
            BankStatementLine.fund_id == fund_id,
            BankStatementLine.matched_transaction_id == tx.id,
            BankStatementLine.reconciliation_status == ReconciliationStatus.MATCHED,
        ),
    ).scalar_one()
    if int(has_match or 0) < 1:
        raise HTTPException(status_code=409, detail="Cannot mark reconciled without a matched bank statement line")

    before = _tx_out(tx, director_signatures_count=None)
    tx.reconciled_at = datetime.now(UTC)
    tx.reconciled_by = actor.actor_id
    tx.updated_by = actor.actor_id

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="TRANSACTION_RECONCILED",
        entity_type="cash_transaction",
        entity_id=tx.id,
        before=before,
        after={
            "transaction_id": str(tx.id),
            "reconciled_at": tx.reconciled_at.isoformat() if tx.reconciled_at else None,
            "reconciled_by": tx.reconciled_by,
        },
    )

    db.commit()
    db.refresh(tx)
    return _tx_out(tx, director_signatures_count=_get_director_count(db, fund_id, tx.id))


@router.post("/transactions/{tx_id}/approve/director")
def approve_director(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx, appr = approve(
            db,
            fund_id=fund_id,
            actor=actor,
            tx_id=tx_id,
            approver_role="DIRECTOR",
            approver_name=str(payload.get("approver_name") or actor.actor_id),
            comment=payload.get("comment"),
            evidence_blob_uri=payload.get("evidence_blob_url") or payload.get("evidence_blob_uri"),
        )
        return {"transaction_id": str(tx.id), "status": tx.status.value, "approval_id": str(appr.id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/approve/ic")
def approve_ic(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx, appr = approve(
            db,
            fund_id=fund_id,
            actor=actor,
            tx_id=tx_id,
            approver_role="IC_MEMBER",
            approver_name=str(payload.get("approver_name") or actor.actor_id),
            comment=payload.get("comment"),
            evidence_blob_uri=payload.get("evidence_blob_url") or payload.get("evidence_blob_uri"),
        )
        return {
            "transaction_id": str(tx.id),
            "status": tx.status.value,
            "ic_approvals_count": int(tx.ic_approvals_count),
            "approval_id": str(appr.id),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/approve")
def approve_any(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "GP", "ADMIN"])),
):
    """Unified approval endpoint.

    Payload:
      - approver_role: DIRECTOR | IC_MEMBER
      - approver_name: optional (defaults to actor_id)
      - comment: optional
      - evidence_blob_uri: optional
    """
    _require_fund_access(fund_id, actor)

    role = payload.get("approver_role") or payload.get("role")
    if role not in ("DIRECTOR", "IC_MEMBER"):
        raise HTTPException(status_code=400, detail="approver_role must be DIRECTOR or IC_MEMBER")

    actor_roles = set(getattr(actor, "roles", []) or [])
    if role == "DIRECTOR" and not ("GP" in actor_roles or "ADMIN" in actor_roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if role == "IC_MEMBER" and not ("INVESTMENT_TEAM" in actor_roles or "ADMIN" in actor_roles):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    try:
        tx, appr = approve(
            db,
            fund_id=fund_id,
            actor=actor,
            tx_id=tx_id,
            approver_role=role,
            approver_name=str(payload.get("approver_name") or actor.actor_id),
            comment=payload.get("comment"),
            evidence_blob_uri=payload.get("evidence_blob_url") or payload.get("evidence_blob_uri"),
        )
        out = {"transaction_id": str(tx.id), "status": tx.status.value, "approval_id": str(appr.id)}
        if role == "IC_MEMBER":
            out["ic_approvals_count"] = int(tx.ic_approvals_count)
        return out
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/reject")
def reject(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx = reject_transaction(db, fund_id=fund_id, actor=actor, tx_id=tx_id, comment=payload.get("comment"))
        return {"transaction_id": str(tx.id), "status": tx.status.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/generate-instructions")
def gen_instructions(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx = generate_instructions(db, fund_id=fund_id, actor=actor, tx_id=tx_id)
        return {"transaction_id": str(tx.id), "instructions_blob_uri": tx.instructions_blob_uri}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/mark-sent")
def mark_sent(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx = mark_sent_to_admin(db, fund_id=fund_id, actor=actor, tx_id=tx_id, admin_contact=payload.get("admin_contact"))
        return {"transaction_id": str(tx.id), "status": tx.status.value, "sent_to_admin_at": tx.sent_to_admin_at.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/transactions/{tx_id}/mark-executed")
def mark_exec(
    fund_id: uuid.UUID,
    tx_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    _require_fund_access(fund_id, actor)
    try:
        tx = mark_executed(
            db,
            fund_id=fund_id,
            actor=actor,
            tx_id=tx_id,
            bank_reference=payload.get("bank_reference"),
            notes=payload.get("notes"),
        )
        return {"transaction_id": str(tx.id), "status": tx.status.value, "executed_at": tx.execution_confirmed_at.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Bank Statement Reconciliation Endpoints


@router.post("/statements/upload")
async def upload_statement(
    fund_id: uuid.UUID,
    period_start: str = Form(...),
    period_end: str = Form(...),
    file: UploadFile = File(...),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    """Upload a bank statement for reconciliation.
    Stores statement metadata in registry and persists the file in blob storage (append-only evidence).
    """
    _require_fund_access(fund_id, actor)

    filename = (file.filename or "statement").strip()
    lower = filename.lower()
    allowed_ext = (".pdf", ".csv", ".xls", ".xlsx")
    if not any(lower.endswith(ext) for ext in allowed_ext):
        raise HTTPException(status_code=400, detail="Only PDF/CSV/XLS/XLSX files are allowed")

    try:
        ps = date.fromisoformat(period_start)
        pe = date.fromisoformat(period_end)

        data = await file.read()
        sha = hashlib.sha256(data).hexdigest()

        parsed_lines: list[dict] = []
        if lower.endswith(".csv"):
            # CSV v1 contract (strict): headers must exist exactly.
            # Required columns: value_date, direction, description, amount_usd
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("utf-8")

            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                raise HTTPException(status_code=400, detail="CSV has no header row")
            required = {"value_date", "direction", "description", "amount_usd"}
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise HTTPException(status_code=400, detail=f"CSV missing required columns: {', '.join(missing)}")

            for idx, row in enumerate(reader, start=2):
                try:
                    value_date = date.fromisoformat(str(row["value_date"]).strip())
                    direction = CashTransactionDirection(str(row["direction"]).strip().upper())
                    description = str(row["description"]).strip()
                    amount_usd = float(str(row["amount_usd"]).strip())
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid CSV row {idx}: {e}")

                if not description:
                    raise HTTPException(status_code=400, detail=f"Invalid CSV row {idx}: description is empty")
                if amount_usd <= 0:
                    raise HTTPException(status_code=400, detail=f"Invalid CSV row {idx}: amount_usd must be > 0")

                parsed_lines.append(
                    {
                        "value_date": value_date,
                        "direction": direction,
                        "description": description,
                        "amount_usd": amount_usd,
                    },
                )

        safe = "".join(c for c in filename if c.isalnum() or c in ("-", "_", "."))
        safe = safe or "statement"
        blob_name = f"{fund_id}/cash/statements/{sha}/{safe}"

        write_res = upload_bytes_idempotent(
            container=settings.AZURE_STORAGE_EVIDENCE_CONTAINER,
            blob_name=blob_name,
            data=data,
            content_type=file.content_type,
            metadata={"fund_id": str(fund_id), "sha256": sha, "source": "bank_statement"},
        )

        # Register upload and parsed lines atomically.
        upload = upload_bank_statement(
            db,
            fund_id=fund_id,
            actor=actor,
            period_start=ps,
            period_end=pe,
            blob_path=write_res.blob_uri,
            original_filename=filename,
            sha256=sha,
            notes=notes,
            commit=False,
        )

        created_line_ids: list[str] = []
        for pl in parsed_lines:
            line = add_statement_line(
                db,
                fund_id=fund_id,
                actor=actor,
                statement_id=upload.id,
                value_date=pl["value_date"],
                description=pl["description"],
                amount_usd=pl["amount_usd"],
                direction=pl["direction"],
                commit=False,
            )
            created_line_ids.append(str(line.id))

        db.commit()
        db.refresh(upload)

        return {
            "statement_id": str(upload.id),
            "period_start": upload.period_start.isoformat(),
            "period_end": upload.period_end.isoformat(),
            "blob_path": upload.blob_path,
            "lines_created": len(created_line_ids),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reconciliation/unmatched")
def list_unmatched_bank_lines(
    fund_id: uuid.UUID,
    statement_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    """List bank statement lines with reconciliation_status=UNMATCHED (optionally filtered by statement)."""
    _require_fund_access(fund_id, actor)
    stmt = select(BankStatementLine).where(
        BankStatementLine.fund_id == fund_id,
        BankStatementLine.reconciliation_status == ReconciliationStatus.UNMATCHED,
    )
    if statement_id:
        stmt = stmt.where(BankStatementLine.statement_id == statement_id)
    stmt = stmt.order_by(BankStatementLine.value_date.asc()).limit(limit).offset(offset)
    lines = list(db.execute(stmt).scalars().all())
    return {"items": [_line_out(l) for l in lines], "count": len(lines)}


@router.get("/statements")
def list_statements(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    _require_fund_access(fund_id, actor)
    stmt = (
        select(BankStatementUpload)
        .where(BankStatementUpload.fund_id == fund_id)
        .order_by(BankStatementUpload.uploaded_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = list(db.execute(stmt).scalars().all())
    return {"items": [_statement_out(s) for s in items]}


@router.get("/statements/{statement_id}/lines")
def list_statement_lines(
    fund_id: uuid.UUID,
    statement_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    _require_fund_access(fund_id, actor)
    stmt = (
        select(BankStatementLine)
        .where(BankStatementLine.fund_id == fund_id, BankStatementLine.statement_id == statement_id)
        .order_by(BankStatementLine.value_date.asc())
        .limit(limit)
        .offset(offset)
    )
    lines = list(db.execute(stmt).scalars().all())
    return {"items": [_line_out(l) for l in lines]}


@router.post("/statements/{statement_id}/lines")
def add_line(
    fund_id: uuid.UUID,
    statement_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    """Add a manual statement line for reconciliation.
    """
    _require_fund_access(fund_id, actor)
    
    try:
        value_date = date.fromisoformat(payload["value_date"])
        direction = CashTransactionDirection(payload["direction"])
        
        line = add_statement_line(
            db,
            fund_id=fund_id,
            actor=actor,
            statement_id=statement_id,
            value_date=value_date,
            description=payload["description"],
            amount_usd=float(payload["amount_usd"]),
            direction=direction,
        )
        return {
            "line_id": str(line.id),
            "value_date": line.value_date.isoformat(),
            "amount_usd": float(line.amount_usd),
            "direction": line.direction.value,
            "reconciliation_status": line.reconciliation_status.value,
        }
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reconcile")
def reconcile(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    """Run reconciliation engine to match bank statement lines with transactions.
    """
    _require_fund_access(fund_id, actor)
    
    try:
        statement_id = uuid.UUID(payload["statement_id"]) if "statement_id" in payload else None
        date_tolerance_days = int(payload.get("date_tolerance_days", 5))
        
        result = match_statement_lines(
            db,
            fund_id=fund_id,
            actor=actor,
            statement_id=statement_id,
            date_tolerance_days=date_tolerance_days,
        )
        return result
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reconciliation/report")
def reconciliation_report(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["COMPLIANCE", "GP", "ADMIN"])),
):
    """Get reconciliation report showing unmatched lines and unexplained transactions.
    """
    _require_fund_access(fund_id, actor)
    
    try:
        missing_tx = detect_missing_transactions(db, fund_id=fund_id)
        unexplained_outflows = detect_unexplained_outflows(db, fund_id=fund_id)
        
        return {
            "fund_id": str(fund_id),
            "unmatched_bank_lines": missing_tx,
            "unexplained_outflows": unexplained_outflows,
            "discrepancies_count": len(missing_tx) + len(unexplained_outflows),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

