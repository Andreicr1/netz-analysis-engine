"""Registry Bridge — connects DocumentRegistry to DealDocument.

DocumentRegistry (populated by document_scanner) tracks every blob in Azure
Storage.  DealDocument (consumed by domain_ingest_orchestrator) tracks which
blobs still need chunking + embedding.

This module bridges the gap: for every DocumentRegistry entry in the
``investment-pipeline-intelligence`` container that belongs to a known
PipelineDeal, it creates (idempotently) a corresponding DealDocument row
so the orchestrator can pick it up.

Idempotent: relies on ``register_deal_document`` which checks
``(deal_id, blob_path)`` uniqueness before insert.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import DocumentRegistry
from app.domains.credit.modules.deals.deal_intelligence_repo import register_deal_document
from app.domains.credit.modules.deals.models import PipelineDeal

logger = logging.getLogger(__name__)

PIPELINE_CONTAINER = "investment-pipeline-intelligence"


@dataclass
class BridgeResult:
    """Summary of a registry-bridge run."""

    registry_rows_scanned: int = 0
    documents_created: int = 0
    documents_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _folder_from_blob(blob_path: str) -> str | None:
    """Extract the top-level folder name from a blob path."""
    parts = [p for p in (blob_path or "").split("/") if p]
    return parts[0] if parts else None


def bridge_registry_to_deal_documents(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None = None,
    actor_id: str = "registry-bridge",
) -> BridgeResult:
    """Create DealDocument rows for DocumentRegistry entries that belong to
    known PipelineDeals but have not yet been registered in the
    ``pipeline_deal_documents`` table.

    If *deal_ids* is provided (non-empty list), only documents belonging to
    those deals are bridged — avoiding unnecessary bridging of all existing
    deals when only specific new deals need processing.

    Steps:
    1. Load all DocumentRegistry rows from the pipeline container.
    2. Load all PipelineDeals (with ``deal_folder_path``).
    3. Match by folder name (top-level folder in blob path).
    4. Call ``register_deal_document`` for each match (idempotent).

    Returns a BridgeResult summarising created / skipped / errors.
    """
    result = BridgeResult()

    # 1. Fetch registry rows for the pipeline container
    registry_rows = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PIPELINE_CONTAINER,
            ),
        )
        .scalars()
        .all(),
    )
    result.registry_rows_scanned = len(registry_rows)

    if not registry_rows:
        logger.info("No DocumentRegistry rows for container=%s, fund=%s", PIPELINE_CONTAINER, fund_id)
        return result

    # 2. Build folder → PipelineDeal lookup
    deals_stmt = select(PipelineDeal).where(
        PipelineDeal.fund_id == fund_id,
        PipelineDeal.deal_folder_path.isnot(None),
    )
    if deal_ids:
        deals_stmt = deals_stmt.where(PipelineDeal.id.in_(deal_ids))
        logger.info("Bridge scoped to %d deal(s)", len(deal_ids))

    deals = list(db.execute(deals_stmt).scalars().all())
    logger.info("Bridge matching %d deal(s) against %d registry rows", len(deals), len(registry_rows))

    folder_to_deal: dict[str, PipelineDeal] = {}
    for deal in deals:
        # deal_folder_path = "investment-pipeline-intelligence/FolderName"
        folder_name = (deal.deal_folder_path or "").split("/")[-1].strip().lower()
        if folder_name:
            folder_to_deal[folder_name] = deal

    if not folder_to_deal:
        logger.warning("No PipelineDeals with deal_folder_path for fund %s — run discover_pipeline_deals first", fund_id)
        return result

    # 3. Match and register
    for reg in registry_rows:
        folder = _folder_from_blob(reg.blob_path)
        if not folder:
            result.documents_skipped += 1
            continue

        deal = folder_to_deal.get(folder.lower())
        if deal is None:
            result.documents_skipped += 1
            continue

        # Derive doc_type from detected_doc_type or fall back to domain_tag
        doc_type = reg.detected_doc_type or reg.domain_tag or "OTHER"

        try:
            doc = register_deal_document(
                db,
                fund_id=fund_id,
                deal_id=deal.id,
                blob_container=reg.container_name,
                blob_path=reg.blob_path,
                doc_type=doc_type,
                authority=reg.authority or "INTELLIGENCE",
                filename=reg.title or reg.blob_path.rsplit("/", 1)[-1],
                actor_id=actor_id,
            )
            # register_deal_document returns existing row if already present
            if doc.last_indexed_at is None:
                result.documents_created += 1
            else:
                result.documents_skipped += 1
        except Exception as exc:
            error_msg = f"Failed to bridge registry {reg.id} → deal {deal.id}: {exc}"
            logger.error(error_msg, exc_info=True)
            result.errors.append(error_msg)

    logger.info(
        "Registry bridge complete: scanned=%d, created=%d, skipped=%d, errors=%d",
        result.registry_rows_scanned,
        result.documents_created,
        result.documents_skipped,
        len(result.errors),
    )
    return result
