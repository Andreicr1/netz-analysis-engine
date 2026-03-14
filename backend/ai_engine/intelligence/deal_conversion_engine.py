"""Pipeline → Portfolio Deal Conversion Engine.

This is a controlled domain transition.  A pipeline deal (research /
due-diligence) is approved and converted into:

1. A **Portfolio Deal** (``deals`` table) — the operational identity.
2. An **ActiveInvestment** wrapper (``active_investments``) — the
   monitoring entity.
3. A **DealConversionEvent** audit record.
4. Azure Search metadata merge (``domain`` → ``portfolio``).

The conversion is:
- **Idempotent** — double-approval is rejected.
- **Gated** — requires ``intelligence_status == READY``.
- **Transactional** — full rollback on failure.
- **Auditable** — every step is logged.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Result DTO ────────────────────────────────────────────────────────


@dataclass
class ConversionResult:
    portfolio_deal_id: uuid.UUID
    active_investment_id: uuid.UUID
    pipeline_deal_id: uuid.UUID
    status: str = "converted"


# ── Helpers ───────────────────────────────────────────────────────────


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _normalize_amount(val: object | None) -> float | None:
    """Best-effort parse of a monetary string (e.g. '$10M', '10,000,000')."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).replace(",", "").replace("$", "").strip()
    match = re.search(r"([\d.]+)\s*(k|m|mm|b|bn)?", text, re.IGNORECASE)
    if not match:
        return None
    num = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multipliers = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
    return num * multipliers.get(suffix, 1.0)


def _title_case_strategy(value: str | None) -> str | None:
    """Normalize strategy_type to Title Case (e.g. 'ASSET_BACKED' → 'Asset Backed')."""
    if not value:
        return value
    return " ".join(w.capitalize() for w in value.replace("_", " ").split())


def _derive_deal_type(research_output: dict | None) -> str:
    """Derive DealType enum value from research_output.deal_overview.instrument."""
    overview = (research_output or {}).get("deal_overview", {})
    instrument = (overview.get("instrument") or "").lower()
    if any(w in instrument for w in ("loan", "credit", "debt", "lending", "facility")):
        return "DIRECT_LOAN"
    if "fund" in instrument:
        return "FUND_INVESTMENT"
    if any(w in instrument for w in ("equity", "preferred", "stock")):
        return "EQUITY_STAKE"
    if any(w in instrument for w in ("note", "spv", "structured")):
        return "SPV_NOTE"
    return "DIRECT_LOAN"


# ── Main Conversion Function ─────────────────────────────────────────


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
        )
    ).scalar_one_or_none()
    if deal is None:
        raise ValueError("Pipeline deal not found")

    if deal.approved_deal_id is not None:
        raise ValueError("Deal already converted — idempotent guard")

    if deal.intelligence_status != "READY":
        raise ValueError(
            f"Intelligence status must be READY (current: {deal.intelligence_status}). "
            "Run AI review first."
        )

    if not deal.research_output:
        raise ValueError(
            "research_output is empty — run AI intelligence pipeline first"
        )

    ro = deal.research_output or {}
    overview = ro.get("deal_overview", {})

    # ── Step 2: Create Portfolio Deal ─────────────────────────────
    deal_type_str = deal_type_override or _derive_deal_type(ro)
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

    commitment = _normalize_amount(overview.get("ticket_size"))
    if commitment is None:
        commitment = _normalize_amount(overview.get("commitment"))
    if commitment is None:
        commitment = _normalize_amount(deal.requested_amount)

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
        "Created portfolio deal %s for pipeline deal %s",
        portfolio_deal.id,
        deal.id,
    )

    # ── Step 3: Create ActiveInvestment ───────────────────────────
    active_inv = ActiveInvestment(
        fund_id=fund_id,
        access_level="internal",
        deal_id=portfolio_deal.id,  # anchored to deals.id (portfolio)
        investment_name=deal.deal_name or deal.title,
        manager_name=sponsor,
        lifecycle_status="ACTIVE",
        source_container="portfolio-active-investments",
        source_folder=f"portfolio-active-investments/{deal.deal_name or deal.title}",
        strategy_type=_title_case_strategy(
            overview.get("strategy_type") or overview.get("sector")
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
        "Created active investment %s → portfolio deal %s",
        active_inv.id,
        portfolio_deal.id,
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
    _search_merge_count = 0
    try:
        from app.domains.credit.modules.deals.doc_reclassification import reclassify_vector_chunks

        _search_merge_count = reclassify_vector_chunks(
            pipeline_deal_id=deal.id,
            portfolio_deal_id=portfolio_deal.id,
            fund_id=fund_id,
        )
        logger.info(
            "Reclassified %d vector chunks pipeline→portfolio for deal %s",
            _search_merge_count,
            deal.id,
        )
    except Exception:
        logger.warning(
            "Azure Search reclassification deferred for pipeline_deal=%s",
            deal.id,
            exc_info=True,
        )

    db.flush()

    return ConversionResult(
        portfolio_deal_id=portfolio_deal.id,
        active_investment_id=active_inv.id,
        pipeline_deal_id=deal.id,
    )
