"""Regional Case-Shiller: read from macro_data hypertable.

Imports models.py and snapshot.py (for DB reader).
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from quant_engine.fred_service import apply_transform
from vertical_engines.credit.market_data.models import (
    CASE_SHILLER_METRO_MAP,
    GEOGRAPHY_TO_METRO,
)
from vertical_engines.credit.market_data.snapshot import _fetch_series_from_db

logger = structlog.get_logger()


def resolve_metro_key(deal_geography: str | None) -> str | None:
    """Resolve a free-form deal geography string to a Case-Shiller metro key.

    Uses substring matching against GEOGRAPHY_TO_METRO.
    Returns metro key (e.g. "miami") or None if unresolvable.
    """
    if not deal_geography:
        return None
    geo_lower = deal_geography.lower()
    for pattern, metro in GEOGRAPHY_TO_METRO.items():
        if pattern in geo_lower:
            return metro
    return None


def fetch_regional_case_shiller(
    db: Session,
    deal_geography: str | None,
    *,
    observations: int = 24,
) -> dict[str, Any] | None:
    """Read regional Case-Shiller HPI from macro_data hypertable.

    Returns dict with metro_key, fred_series, label + apply_transform output.
    Returns None if geography unresolvable or no data in DB.
    """
    metro_key = resolve_metro_key(deal_geography)
    if not metro_key:
        logger.info("case_shiller_regional_no_match", geography=deal_geography)
        return None

    fred_series = CASE_SHILLER_METRO_MAP.get(metro_key)
    if not fred_series:
        return None

    try:
        series_data = _fetch_series_from_db(db, [fred_series], max_observations=observations)
        obs = series_data.get(fred_series, [])
        if not obs:
            logger.warning(
                "case_shiller_regional_no_db_data",
                metro=metro_key,
                series=fred_series,
            )
            return None

        result: dict[str, Any] = apply_transform(fred_series, obs, transform="yoy_pct")
        result["metro_key"] = metro_key
        result["fred_series"] = fred_series
        result["label"] = f"Case-Shiller HPI — {metro_key.replace('_', ' ').title()}"
        logger.info(
            "case_shiller_regional_ok",
            metro=metro_key,
            series=fred_series,
            latest=result.get("latest"),
            trend=result.get("trend_direction"),
            source="macro_data",
        )
        return result
    except Exception as exc:
        logger.warning(
            "case_shiller_regional_failed",
            metro=metro_key,
            series=fred_series,
            error=str(exc),
        )
        return None
