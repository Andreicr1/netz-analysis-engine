"""Portfolio discovery — discover active investments from document registry."""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.deals.models.deals import Deal as PortfolioDeal
from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    DealIntelligenceProfile,
    DocumentRegistry,
)
from app.domains.credit.modules.deals.models import Deal as PipelineDeal
from vertical_engines.credit.portfolio.models import PORTFOLIO_CONTAINER

logger = structlog.get_logger()


def _folder_from_blob(blob_path: str | None) -> str | None:
    parts = [p for p in (blob_path or "").split("/") if p]
    return parts[0] if parts else None


def discover_active_investments(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[ActiveInvestment]:
    logger.info("discover_active_investments.start", fund_id=str(fund_id))

    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == PORTFOLIO_CONTAINER,
            ),
        ).scalars().all(),
    )

    grouped: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for doc in docs:
        folder = _folder_from_blob(doc.blob_path)
        if folder:
            grouped[folder].append(doc)

    # Load pipeline deals for name-matching + intelligence profiles
    p_deals = list(db.execute(select(PipelineDeal).where(PipelineDeal.fund_id == fund_id)).scalars().all())
    p_deals_by_name = {(d.deal_name or d.title or "").strip().lower(): d for d in p_deals}

    # Batch pre-load intelligence profiles for all pipeline deals
    all_profiles = list(
        db.execute(
            select(DealIntelligenceProfile).where(DealIntelligenceProfile.fund_id == fund_id),
        ).scalars().all(),
    )
    profiles_by_deal = {p.deal_id: p for p in all_profiles}

    # Batch pre-load existing active investments for the fund
    all_active_invs = list(
        db.execute(
            select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id),
        ).scalars().all(),
    )
    active_inv_by_folder = {inv.source_folder: inv for inv in all_active_invs if inv.source_folder}

    # Load portfolio deals — active_investments now FK → deals.id
    port_deals = list(db.execute(select(PortfolioDeal).where(PortfolioDeal.fund_id == fund_id)).scalars().all())
    port_by_name = {(d.name or "").strip().lower(): d for d in port_deals}
    # Also index by pipeline_deal_id for lookup after pipeline match
    port_by_pipeline = {d.pipeline_deal_id: d for d in port_deals if d.pipeline_deal_id}

    saved: list[ActiveInvestment] = []
    for folder_name, folder_docs in grouped.items():
        key = folder_name.strip().lower()
        p_deal = p_deals_by_name.get(key)           # pipeline deal (history)
        port_deal = port_by_name.get(key)            # portfolio deal (identity)

        # If we matched a pipeline deal but not a portfolio deal, try via approved_deal_id
        if p_deal and not port_deal:
            if p_deal.approved_deal_id:
                port_deal = next(
                    (d for d in port_deals if d.id == p_deal.approved_deal_id), None,
                )
            elif p_deal.id in port_by_pipeline:
                port_deal = port_by_pipeline[p_deal.id]

        source_folder = f"{PORTFOLIO_CONTAINER}/{folder_name}"
        primary_doc = max(folder_docs, key=lambda d: d.last_ingested_at)
        manager_name = (p_deal.sponsor_name if p_deal else None) or folder_name
        lifecycle = "ACTIVE"
        lifecycle_stage = p_deal.lifecycle_stage if p_deal and p_deal.lifecycle_stage else None
        if lifecycle_stage and lifecycle_stage.upper() in {"APPROVED", "DEPLOYED", "MONITORING"}:
            lifecycle = lifecycle_stage.upper()

        profile = profiles_by_deal.get(p_deal.id) if p_deal is not None else None

        existing = active_inv_by_folder.get(source_folder)

        target_return = profile.target_return if profile else None
        strategy = profile.strategy_type if profile else None

        transition_log: list[dict] = []
        if existing and existing.transition_log:
            transition_log = list(existing.transition_log)

        if existing and existing.lifecycle_status != lifecycle:
            transition_log.append(
                {
                    "from": existing.lifecycle_status,
                    "to": lifecycle,
                    "at": as_of.isoformat(),
                    "reason": "daily_monitoring_reclassification",
                },
            )

        # deal_id now points to portfolio deals.id (not pipeline_deals.id)
        payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "deal_id": port_deal.id if port_deal else None,
            "primary_document_id": primary_doc.id,
            "investment_name": folder_name,
            "manager_name": manager_name,
            "lifecycle_status": lifecycle,
            "source_container": PORTFOLIO_CONTAINER,
            "source_folder": source_folder,
            "strategy_type": strategy,
            "target_return": target_return,
            "last_monitoring_at": as_of,
            "transition_log": transition_log,
            "as_of": as_of,
            "data_latency": None,
            "data_quality": "OK",
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        if existing is None:
            row = ActiveInvestment(**payload)
            db.add(row)
            db.flush()
        else:
            for key_name, value in payload.items():
                if key_name == "created_by":
                    continue
                setattr(existing, key_name, value)
            db.flush()
            row = existing

        saved.append(row)

    db.flush()
    logger.info("discover_active_investments.done", fund_id=str(fund_id), count=len(saved))
    return saved
