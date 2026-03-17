"""Impact analyzer — identifies portfolios affected by instrument removal.

Pure computation: queries DB for affected portfolios, computes weight gap.
Must NOT import from service.py (enforced by import-linter).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vertical_engines.wealth.rebalancing.models import RebalanceImpact

logger = structlog.get_logger()


def compute_impact(
    db: Session,
    instrument_id: uuid.UUID,
    organization_id: str,
    trigger: str = "deactivation",
) -> RebalanceImpact:
    """Identify model portfolios affected by instrument removal.

    Scans ModelPortfolio.fund_selection_schema JSONB for entries
    containing the removed instrument_id. Computes the weight gap
    (total weight allocated to the removed instrument).

    Args:
        db: Sync session (caller manages transaction).
        instrument_id: The instrument being removed.
        organization_id: Tenant scope.
        trigger: "deactivation" or "regime_change".

    Returns:
        RebalanceImpact with affected portfolio IDs and weight gap.
    """
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

    # Get all active model portfolios for this org
    portfolios = db.execute(
        select(ModelPortfolio).where(
            ModelPortfolio.organization_id == organization_id,
            ModelPortfolio.status == "active",
            ModelPortfolio.fund_selection_schema.isnot(None),
        )
    ).scalars().all()

    affected_ids: list[uuid.UUID] = []
    total_weight_gap = 0.0
    instrument_str = str(instrument_id)

    for portfolio in portfolios:
        schema = portfolio.fund_selection_schema or {}
        funds = schema.get("funds", [])
        for fund_entry in funds:
            if fund_entry.get("instrument_id") == instrument_str:
                affected_ids.append(portfolio.id)
                total_weight_gap += float(fund_entry.get("weight", 0.0))
                break

    logger.info(
        "rebalance_impact_computed",
        instrument_id=instrument_str,
        affected_count=len(affected_ids),
        weight_gap=round(total_weight_gap, 6),
        trigger=trigger,
    )

    return RebalanceImpact(
        instrument_id=instrument_id,
        affected_portfolios=tuple(affected_ids),
        weight_gap=round(total_weight_gap, 6),
        trigger=trigger,
    )
