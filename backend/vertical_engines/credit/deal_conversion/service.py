"""Deal conversion service — pipeline → portfolio deal transition.

Error contract: raises-on-failure (transactional engine).
Raises ValueError on validation gates:
- Deal not found
- Deal already converted (idempotent guard)
- Intelligence status not READY
- research_output empty
"""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vertical_engines.credit.deal_conversion.models import ConversionResult
from vertical_engines.credit.deal_conversion.normalization import (
    derive_deal_type,
    normalize_amount,
    title_case_strategy,
)

logger = structlog.get_logger()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def convert_pipeline_to_portfolio(
    db: Session,
    *,
    pipeline_deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    approved_by: str,
    notes: str | None = None,
    deal_type_override: str | None = None,
    rationale_override: str | None = None,
    sponsor_override: str | None = None,
    description_override: str | None = None,
) -> ConversionResult:
    """Convert a pipeline deal into a portfolio deal.

    Returns a ``ConversionResult`` with IDs for the new portfolio deal
    and active investment.

    Raises ``ValueError`` if any validation gate fails.
    """
    from app.domains.credit.deals.enums import DealStage as PortfolioDealStage
    from app.domains.credit.deals.enums import DealType as DomainDealType
    from app.domains.credit.deals.models.deals import Deal as PortfolioDeal
    from app.domains.credit.modules.ai.models import ActiveInvestment
    from app.domains.credit.modules.deals.models import (
        Deal as PipelineDeal,
    )
    from app.domains.credit.modules.deals.models import (
        DealConversionEvent,
        DealEvent,
        DealStageHistory,
    )

    now = _utcnow()

    # ── Step 1: Validation (Hard Gate) ────────────────────────────
    deal = db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.id == pipeline_deal_id,
        ),
    ).scalar_one_or_none()
    if deal is None:
        raise ValueError("Pipeline deal not found")

    if deal.approved_deal_id is not None:
        raise ValueError("Deal already converted — idempotent guard")

    if deal.intelligence_status != "READY":
        raise ValueError(
            f"Intelligence status must be READY (current: {deal.intelligence_status}). "
            "Run AI review first.",
        )

    if not deal.research_output:
        raise ValueError(
            "research_output is empty — run AI intelligence pipeline first",
        )

    ro = deal.research_output or {}
    overview = ro.get("deal_overview", {})

    # ── Step 2: Create Portfolio Deal ─────────────────────────────
    deal_type_str = deal_type_override or derive_deal_type(ro)
    deal_type = DomainDealType(deal_type_str)

    sponsor = (
        sponsor_override
        or overview.get("sponsor")
        or deal.sponsor_name
        or deal.borrower_name
    )
    description = (
        description_override or overview.get("strategy_summary") or deal.ai_summary
    )

    commitment = normalize_amount(overview.get("ticket_size"))
    if commitment is None:
        commitment = normalize_amount(overview.get("commitment"))
    if commitment is None:
        commitment = normalize_amount(deal.requested_amount)

    portfolio_deal = PortfolioDeal(
        fund_id=fund_id,
        deal_type=deal_type,
        stage=PortfolioDealStage.APPROVED,
        name=deal.deal_name or deal.title,
        sponsor_name=sponsor,
        description=description,
        pipeline_deal_id=deal.id,
    )
    db.add(portfolio_deal)
    db.flush()

    logger.info(
        "convert_pipeline_to_portfolio.portfolio_deal_created",
        portfolio_deal_id=str(portfolio_deal.id),
        pipeline_deal_id=str(deal.id),
    )

    # ── Step 3: Create ActiveInvestment ───────────────────────────
    active_inv = ActiveInvestment(
        fund_id=fund_id,
        access_level="internal",
        deal_id=portfolio_deal.id,
        investment_name=deal.deal_name or deal.title,
        manager_name=sponsor,
        lifecycle_status="ACTIVE",
        source_container="portfolio-active-investments",
        source_folder=f"portfolio-active-investments/{deal.deal_name or deal.title}",
        strategy_type=title_case_strategy(
            overview.get("strategy_type") or overview.get("sector"),
        ),
        target_return=overview.get("yield") or overview.get("target_return"),
        committed_capital_usd=commitment,
        deployed_capital_usd=0.0,
        current_nav_usd=None,
        as_of=now,
        data_quality="OK",
        created_by=approved_by,
        updated_by=approved_by,
    )
    db.add(active_inv)
    db.flush()

    logger.info(
        "convert_pipeline_to_portfolio.active_investment_created",
        active_investment_id=str(active_inv.id),
        portfolio_deal_id=str(portfolio_deal.id),
    )

    # ── Step 4: Mark Pipeline Deal as Approved ────────────────────
    from_stage = deal.stage
    deal.approved_deal_id = portfolio_deal.id
    deal.approved_at = now
    deal.approved_by = approved_by
    deal.approval_notes = notes
    deal.stage = "Execution"
    deal.updated_by = approved_by

    # Stage history
    hist = DealStageHistory(
        fund_id=fund_id,
        deal_id=deal.id,
        from_stage=from_stage,
        to_stage="Execution",
        rationale=f"IC approved → portfolio deal {portfolio_deal.id}",
        created_by=approved_by,
        updated_by=approved_by,
    )
    db.add(hist)
    db.flush()

    # Deal event
    evt = DealEvent(
        deal_id=portfolio_deal.id,
        pipeline_deal_id=deal.id,
        fund_id=fund_id,
        event_type="IC_APPROVED",
        actor_id=approved_by,
        payload={
            "deal_type": deal_type.value,
            "rationale": rationale_override or notes or "IC approved",
            "portfolio_deal_id": str(portfolio_deal.id),
            "pipeline_deal_id": str(deal.id),
            "active_investment_id": str(active_inv.id),
            "commitment": commitment,
        },
    )
    db.add(evt)

    # Reset last_indexed_at on pipeline deal documents (for reclassification)
    for doc in deal.documents:
        doc.last_indexed_at = None
    db.flush()

    # ── Step 5: DealConversionEvent (audit) ───────────────────────
    conversion_event = DealConversionEvent(
        fund_id=fund_id,
        pipeline_deal_id=deal.id,
        portfolio_deal_id=portfolio_deal.id,
        active_investment_id=active_inv.id,
        approved_by=approved_by,
        approval_notes=notes,
        conversion_metadata={
            "deal_type": deal_type.value,
            "sponsor": sponsor,
            "instrument": overview.get("instrument"),
            "commitment": commitment,
            "intelligence_status": deal.intelligence_status,
            "research_output_keys": list(ro.keys()),
        },
    )
    db.add(conversion_event)
    db.flush()

    # ── Step 6: Azure Search metadata transition (best-effort) ────
    try:
        from app.domains.credit.modules.deals.doc_reclassification import reclassify_vector_chunks

        search_merge_count = reclassify_vector_chunks(
            pipeline_deal_id=deal.id,
            portfolio_deal_id=portfolio_deal.id,
            fund_id=fund_id,
        )
        logger.info(
            "convert_pipeline_to_portfolio.vector_chunks_reclassified",
            count=search_merge_count,
            pipeline_deal_id=str(deal.id),
        )
    except Exception:
        logger.warning(
            "convert_pipeline_to_portfolio.vector_reclassification_deferred",
            pipeline_deal_id=str(deal.id),
            exc_info=True,
        )

    db.flush()

    return ConversionResult(
        portfolio_deal_id=portfolio_deal.id,
        active_investment_id=active_inv.id,
        pipeline_deal_id=deal.id,
    )
