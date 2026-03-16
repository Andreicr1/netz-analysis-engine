"""Deal intelligence repository — idempotent DealDocument creation and AI output persistence.

Functions:
    register_deal_document()  — idempotent insert of DealDocument for a blob
    update_deal_ai_output()   — write AI summary/risk/terms to PipelineDeal
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.deals.models import DealDocument, PipelineDeal


def register_deal_document(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    blob_container: str,
    blob_path: str,
    doc_type: str,
    authority: str = "INTELLIGENCE",
    filename: str = "",
    actor_id: str = "ai-engine",
) -> DealDocument:
    """Create a DealDocument row if (deal_id, blob_path) does not exist.

    Idempotent: returns the existing row if already present.
    The unique constraint ``uq_deal_doc_blob_path`` on
    ``(deal_id, blob_path)`` enforces uniqueness at the DB level.
    """
    existing = db.execute(
        select(DealDocument).where(
            DealDocument.deal_id == deal_id,
            DealDocument.blob_path == blob_path,
        ),
    ).scalar_one_or_none()

    if existing is not None:
        return existing

    doc = DealDocument(
        fund_id=fund_id,
        deal_id=deal_id,
        blob_container=blob_container,
        blob_path=blob_path,
        document_type=doc_type,
        authority=authority,
        filename=filename or blob_path.rsplit("/", 1)[-1],
        status="registered",
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(doc)
    db.flush()
    return doc


def update_deal_ai_output(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    summary: str,
    risk_flags: list,
    key_terms: dict,
) -> None:
    """Write AI-generated screening output to PipelineDeal columns.

    Updates: ai_summary, ai_risk_flags, ai_key_terms.
    These are screening-layer outputs only — authoritative IC
    recommendation is set by Deep Review V4.
    """
    deal = db.execute(
        select(PipelineDeal).where(
            PipelineDeal.id == deal_id,
            PipelineDeal.fund_id == fund_id,
        ),
    ).scalar_one_or_none()

    if deal is None:
        return

    deal.ai_summary = summary
    deal.ai_risk_flags = risk_flags
    deal.ai_key_terms = key_terms
    db.flush()
