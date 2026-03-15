"""Pipeline deal discovery and document aggregation.

Implements discover_pipeline_deals() and aggregate_deal_documents()
(from pipeline_intelligence.py).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DealDocumentIntelligence,
    DocumentRegistry,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal
from vertical_engines.credit.pipeline.models import (
    DOC_TYPE_MAP,
    PIPELINE_CONTAINER,
)

logger = structlog.get_logger()


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _folder_from_blob(blob_path: str) -> str | None:
    parts = [p for p in (blob_path or "").split("/") if p]
    if not parts:
        return None
    return parts[0]


def discover_pipeline_deals(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[Deal]:
    """Discover pipeline deals from blob folder structure."""
    now = _now_utc()
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PIPELINE_CONTAINER,
            ),
        ).scalars().all(),
    )

    grouped: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for doc in docs:
        folder = _folder_from_blob(doc.blob_path)
        if not folder:
            continue
        grouped[folder].append(doc)

    all_deals = {
        d.deal_folder_path: d
        for d in db.execute(
            select(Deal).where(Deal.fund_id == fund_id),
        ).scalars().all()
        if d.deal_folder_path
    }

    saved: list[Deal] = []
    for folder_name, folder_docs in grouped.items():
        folder_path = f"{PIPELINE_CONTAINER}/{folder_name}"
        existing = all_deals.get(folder_path)

        first_detected = min((d.last_ingested_at for d in folder_docs), default=now)
        last_updated = max((d.last_ingested_at for d in folder_docs), default=now)

        if existing is None:
            deal = Deal(
                fund_id=fund_id,
                access_level="internal",
                deal_name=folder_name,
                sponsor_name=folder_name,
                lifecycle_stage="SCREENING",
                first_detected_at=first_detected,
                last_updated_at=last_updated,
                deal_folder_path=folder_path,
                transition_target_container="portfolio-active-investments",
                intelligence_history={"authority": "INTELLIGENCE", "sourceContainer": PIPELINE_CONTAINER},
                title=folder_name,
                borrower_name=folder_name,
                stage="SCREENING",
                is_archived=False,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(deal)
            db.flush()
            saved.append(deal)
            continue

        existing.deal_name = folder_name
        existing.sponsor_name = folder_name
        normalized_stage = existing.lifecycle_stage or existing.stage or "SCREENING"
        existing.lifecycle_stage = normalized_stage
        existing.stage = normalized_stage
        existing.last_updated_at = last_updated
        existing.deal_folder_path = folder_path
        existing.transition_target_container = existing.transition_target_container or "portfolio-active-investments"
        existing.intelligence_history = existing.intelligence_history or {"authority": "INTELLIGENCE", "sourceContainer": PIPELINE_CONTAINER}
        existing.updated_by = actor_id
        db.flush()
        saved.append(existing)

    db.commit()
    return saved


def aggregate_deal_documents(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DealDocumentIntelligence]:
    """Aggregate documents per deal from document registry."""
    deals = list(
        db.execute(
            select(Deal).where(
                Deal.fund_id == fund_id,
                Deal.deal_folder_path.is_not(None),
            ),
        ).scalars().all(),
    )
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PIPELINE_CONTAINER,
            ),
        ).scalars().all(),
    )

    all_ddi = list(
        db.execute(
            select(DealDocumentIntelligence).where(
                DealDocumentIntelligence.fund_id == fund_id,
            ),
        ).scalars().all(),
    )
    ddi_lookup: dict[tuple, DealDocumentIntelligence] = {
        (row.deal_id, row.doc_id): row for row in all_ddi
    }

    docs_by_folder: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for d in docs:
        folder = _folder_from_blob(d.blob_path or "")
        if folder:
            docs_by_folder[folder.lower()].append(d)

    saved: list[DealDocumentIntelligence] = []
    for deal in deals:
        folder_name = (deal.deal_name or "").strip().lower()
        matched_docs = docs_by_folder.get(folder_name, [])

        for doc in matched_docs:
            doc_type, confidence = DOC_TYPE_MAP.get(doc.detected_doc_type or "OTHER", ("Term Sheet", 60))
            existing = ddi_lookup.get((deal.id, doc.id))

            payload = {
                "fund_id": fund_id,
                "access_level": "internal",
                "deal_id": deal.id,
                "doc_id": doc.id,
                "doc_type": doc_type,
                "confidence_score": int(confidence),
                "created_by": actor_id,
                "updated_by": actor_id,
            }

            if existing is None:
                row = DealDocumentIntelligence(**payload)
                db.add(row)
                db.flush()
            else:
                for key, value in payload.items():
                    if key == "created_by":
                        continue
                    setattr(existing, key, value)
                db.flush()
                row = existing
            saved.append(row)

    db.commit()
    return saved
