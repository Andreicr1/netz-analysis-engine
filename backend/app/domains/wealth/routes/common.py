"""Shared utilities for API routers."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.portfolio import PortfolioSnapshot

VALID_PROFILES = {"conservative", "moderate", "growth"}


def validate_profile(profile: str) -> str:
    """Validate that profile is one of the allowed values."""
    if profile not in VALID_PROFILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid profile. Must be one of: {', '.join(sorted(VALID_PROFILES))}",
        )
    return profile


async def get_latest_snapshot(
    db: AsyncSession, profile: str,
) -> PortfolioSnapshot | None:
    """Get the latest portfolio snapshot for a profile."""
    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
