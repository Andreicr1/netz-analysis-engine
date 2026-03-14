from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.domains.credit.deals.enums import DealStage
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.services.stage_transition import transition_deal_stage
from app.domains.credit.portfolio.enums import AssetType, Strategy
from app.domains.credit.portfolio.models.assets import PortfolioAsset


def convert_deal_to_asset(
    db: Session,
    deal: Deal,
    *,
    actor_id: str,
    fund_id: uuid.UUID,
) -> PortfolioAsset:
    """Approved deals become canonical PortfolioAssets.

    This service:
      1. Maps ``deal.deal_type`` → ``AssetType``
      2. Creates the ``PortfolioAsset``
      3. Links ``deal.asset_id`` to the new asset
      4. Transitions the deal stage from APPROVED → CONVERTED_TO_ASSET
         via ``transition_deal_stage`` (which validates and audits)

    The caller is responsible for ``db.commit()``.
    """

    try:
        asset_type = AssetType[deal.deal_type.value]
    except Exception as e:
        raise ValueError(f"Unsupported deal_type for conversion: {deal.deal_type}") from e

    asset = PortfolioAsset(
        fund_id=deal.fund_id,
        asset_type=asset_type,
        strategy=Strategy.CORE_DIRECT_LENDING,
        name=deal.name,
    )

    db.add(asset)
    db.flush()
    db.refresh(asset)

    deal.asset_id = asset.id

    transition_deal_stage(
        db,
        deal,
        DealStage.CONVERTED_TO_ASSET,
        actor_id=actor_id,
        fund_id=fund_id,
        extra_audit={"asset_id": str(asset.id)},
    )

    return asset

