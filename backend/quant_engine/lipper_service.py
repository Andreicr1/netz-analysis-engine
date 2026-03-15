"""Lipper fund ratings service.

Gated behind FEATURE_LIPPER_ENABLED. When disabled, returns neutral scores.
When enabled, queries lipper_ratings table for the latest rating.

The concrete API ingestion will be implemented when the Lipper/LSEG API
key and documentation are available. This service defines the consumer
interface so scoring_service.py can call it regardless of the flag state.

Note: imports LipperRating from app.domains.wealth — wealth-vertical-specific dependency (lazy import).
"""

from datetime import date
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings

logger = structlog.get_logger()

# Lipper Leader ratings: 1-5 scale (5 = best)
# Normalized to 0-100: (rating - 1) / 4 * 100
LIPPER_SCORE_FIELDS = [
    "overall_rating",
    "consistent_return",
    "preservation",
    "total_return",
]


async def get_fund_lipper_score(
    db: AsyncSession,
    fund_id: UUID,
    as_of_date: date | None = None,
) -> float:
    """Get normalized Lipper score for a fund (0-100).

    Returns 50.0 (neutral) when FEATURE_LIPPER_ENABLED=false
    or when no Lipper data exists for the fund.
    """
    if not settings.feature_lipper_enabled:
        return 50.0

    from app.domains.wealth.models.lipper import LipperRating

    stmt = (
        select(LipperRating)
        .where(LipperRating.fund_id == fund_id)
        .order_by(LipperRating.rating_date.desc())
        .limit(1)
    )
    if as_of_date:
        stmt = stmt.where(LipperRating.rating_date <= as_of_date)

    result = await db.execute(stmt)
    rating = result.scalar_one_or_none()

    if rating is None:
        return 50.0

    # Average available Lipper Leader scores, normalize 1-5 -> 0-100
    scores = []
    for field_name in LIPPER_SCORE_FIELDS:
        val = getattr(rating, field_name, None)
        if val is not None:
            scores.append((val - 1) / 4 * 100)

    return round(sum(scores) / len(scores), 2) if scores else 50.0
