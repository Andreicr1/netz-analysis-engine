"""Backfill macro_regime_history from full VIX history in macro_data.

One-time script — run after deploying migration 0061 to populate historical
regime classifications. Uses the same HMM logic as regime_fit worker.

Usage:
    python -m scripts.backfill_regime_history
"""

import asyncio
from datetime import date

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.workers.regime_fit import (
    MIN_VIX_OBS,
    _fit_markov_regime,
    _persist_regime_history,
)

logger = structlog.get_logger()


async def _fetch_full_vix_history(db: AsyncSession) -> list[tuple[date, float]]:
    """Fetch entire VIX history from macro_data, ascending by date."""
    stmt = (
        select(MacroData.obs_date, MacroData.value)
        .where(
            MacroData.series_id == "VIXCLS",
            MacroData.value.is_not(None),
        )
        .order_by(MacroData.obs_date)
    )
    result = await db.execute(stmt)
    return [(row[0], float(row[1])) for row in result.all()]


async def main() -> None:
    logger.info("Starting regime history backfill")

    async with async_session() as db:
        vix_with_dates = await _fetch_full_vix_history(db)

    n_obs = len(vix_with_dates)
    logger.info("Full VIX history fetched", n_obs=n_obs)

    if n_obs < MIN_VIX_OBS:
        logger.error(
            "Insufficient VIX history for Markov fit",
            n_obs=n_obs,
            min_required=MIN_VIX_OBS,
        )
        return

    dates_list = [d for d, _ in vix_with_dates]
    vix_values = [v for _, v in vix_with_dates]

    high_vol_probs = _fit_markov_regime(vix_values)
    if high_vol_probs is None:
        logger.error("Markov fitting failed — cannot backfill")
        return

    p_high_vol_series = high_vol_probs
    p_low_vol_series = [1.0 - p for p in p_high_vol_series]
    vix_or_none: list[float | None] = vix_values

    logger.info("HMM fit complete, persisting regime history", n_obs=n_obs)

    async with async_session() as db:
        n_persisted = await _persist_regime_history(
            db, dates_list, p_low_vol_series, p_high_vol_series, vix_or_none,
        )

    # Log regime distribution
    async with async_session() as db:
        from sqlalchemy import text

        result = await db.execute(text(
            "SELECT classified_regime, count(*) FROM macro_regime_history GROUP BY 1 ORDER BY 1"
        ))
        dist = {row[0]: row[1] for row in result.all()}

    logger.info(
        "Backfill complete",
        rows_persisted=n_persisted,
        regime_distribution=dist,
    )


if __name__ == "__main__":
    asyncio.run(main())
