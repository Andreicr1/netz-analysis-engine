"""SEC continuous aggregate refresh worker — refreshes 13F aggregates and caches per-manager stats.

Usage:
    python -m app.domains.wealth.workers.sec_refresh

Refreshes TimescaleDB continuous aggregates (sec_13f_holdings_agg, sec_13f_drift_agg)
and writes per-manager summary stats to Redis for the manager screener.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_016.
"""

import asyncio
import json
import random

import redis.asyncio as aioredis
import structlog
from sqlalchemy import func, select, text

from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.tracker import get_redis_pool
from app.domains.wealth.queries.manager_screener_sql import (
    drift_agg,
    holdings_agg,
    sec_managers,
)

logger = structlog.get_logger()
SEC_REFRESH_LOCK_ID = 900_016

# Redis cache TTL: 24h with ±1h jitter to prevent thundering herd
_BASE_TTL = 86400
_JITTER_RANGE = 3600


async def run_sec_refresh() -> dict:
    """Refresh SEC continuous aggregates and cache per-manager stats in Redis."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SEC_REFRESH_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("SEC refresh already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # ── Step 1a: Refresh continuous aggregates ───────────────
            logger.info("Refreshing sec_13f_holdings_agg continuous aggregate")
            await db.execute(
                text("CALL refresh_continuous_aggregate('sec_13f_holdings_agg', NULL, NULL)"),
            )
            logger.info("Refreshing sec_13f_drift_agg continuous aggregate")
            await db.execute(
                text("CALL refresh_continuous_aggregate('sec_13f_drift_agg', NULL, NULL)"),
            )
            await db.commit()
            logger.info("Continuous aggregates refreshed")

            # ── Step 1b: Refresh plain materialized view ─────────────
            # sec_13f_manager_sector_latest is a plain MV (not a continuous
            # aggregate) — requires explicit REFRESH after each ingestion.
            try:
                logger.info("Refreshing sec_13f_manager_sector_latest materialized view")
                await db.execute(
                    text(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY "
                        "sec_13f_manager_sector_latest"
                    ),
                )
                await db.commit()
                logger.info("sec_13f_manager_sector_latest refreshed")
            except Exception:
                await db.rollback()
                logger.warning(
                    "sec_13f_manager_sector_latest refresh failed — "
                    "retrying without CONCURRENTLY",
                    exc_info=True,
                )
                try:
                    await db.execute(
                        text(
                            "REFRESH MATERIALIZED VIEW "
                            "sec_13f_manager_sector_latest"
                        ),
                    )
                    await db.commit()
                    logger.info(
                        "sec_13f_manager_sector_latest refreshed (non-concurrent)"
                    )
                except Exception:
                    await db.rollback()
                    logger.error(
                        "sec_13f_manager_sector_latest refresh failed permanently",
                        exc_info=True,
                    )

            # ── Step 2: Compute per-manager aggregates in bulk ───────

            # Subquery: latest quarter per CIK from holdings_agg
            latest_quarter_sub = (
                select(
                    holdings_agg.c.cik,
                    func.max(holdings_agg.c.quarter).label("latest_quarter"),
                )
                .group_by(holdings_agg.c.cik)
                .subquery("latest_q")
            )

            # Holdings aggregates for the latest quarter per CIK:
            # top_sector, HHI, position_count, portfolio_value
            holdings_query = (
                select(
                    holdings_agg.c.cik,
                    func.sum(holdings_agg.c.sector_value).label("portfolio_value"),
                    func.sum(holdings_agg.c.position_count).label("position_count"),
                    # Top sector by value
                    func.max(holdings_agg.c.sector).filter(
                        holdings_agg.c.sector_value
                        == select(func.max(holdings_agg.c.sector_value))
                        .where(holdings_agg.c.cik == holdings_agg.c.cik)
                        .where(holdings_agg.c.quarter == latest_quarter_sub.c.latest_quarter)
                        .correlate(holdings_agg)
                        .scalar_subquery(),
                    ).label("top_sector"),
                )
                .join(
                    latest_quarter_sub,
                    (holdings_agg.c.cik == latest_quarter_sub.c.cik)
                    & (holdings_agg.c.quarter == latest_quarter_sub.c.latest_quarter),
                )
                .group_by(holdings_agg.c.cik)
            )

            holdings_result = await db.execute(holdings_query)
            holdings_rows = holdings_result.all()

            # Build holdings lookup by CIK
            holdings_by_cik: dict[str, dict] = {}
            for row in holdings_rows:
                holdings_by_cik[row.cik] = {
                    "portfolio_value": int(row.portfolio_value or 0),
                    "position_count": int(row.position_count or 0),
                    "top_sector": row.top_sector or "Unknown",
                }

            # HHI per CIK: need sector weights for the latest quarter
            # HHI = sum of squared sector weight fractions
            hhi_query = (
                select(
                    holdings_agg.c.cik,
                    holdings_agg.c.sector_value,
                )
                .join(
                    latest_quarter_sub,
                    (holdings_agg.c.cik == latest_quarter_sub.c.cik)
                    & (holdings_agg.c.quarter == latest_quarter_sub.c.latest_quarter),
                )
            )
            hhi_result = await db.execute(hhi_query)
            hhi_rows = hhi_result.all()

            # Accumulate sector values per CIK for HHI calculation
            sector_values_by_cik: dict[str, list[int]] = {}
            for row in hhi_rows:
                cik = row.cik
                if cik not in sector_values_by_cik:
                    sector_values_by_cik[cik] = []
                sector_values_by_cik[cik].append(int(row.sector_value or 0))

            hhi_by_cik: dict[str, float] = {}
            for cik, values in sector_values_by_cik.items():
                total = sum(values)
                if total > 0:
                    hhi_by_cik[cik] = round(
                        sum((v / total) ** 2 for v in values), 6,
                    )
                else:
                    hhi_by_cik[cik] = 0.0

            # Drift aggregates: most recent quarter per CIK
            latest_drift_quarter_sub = (
                select(
                    drift_agg.c.cik,
                    func.max(drift_agg.c.quarter).label("latest_quarter"),
                )
                .group_by(drift_agg.c.cik)
                .subquery("latest_drift_q")
            )

            drift_query = (
                select(
                    drift_agg.c.cik,
                    drift_agg.c.churn_count,
                    drift_agg.c.total_changes,
                )
                .join(
                    latest_drift_quarter_sub,
                    (drift_agg.c.cik == latest_drift_quarter_sub.c.cik)
                    & (drift_agg.c.quarter == latest_drift_quarter_sub.c.latest_quarter),
                )
            )

            drift_result = await db.execute(drift_query)
            drift_rows = drift_result.all()

            drift_by_cik: dict[str, dict] = {}
            for row in drift_rows:
                total_changes = int(row.total_changes or 0)
                churn_count = int(row.churn_count or 0)
                turnover = round(churn_count / total_changes, 4) if total_changes > 0 else 0.0
                drift_by_cik[row.cik] = {
                    "turnover": turnover,
                    "style_drift_detected": turnover > 0.3,
                }

            # ── Step 3: Get all managers and build Redis payloads ────
            managers_result = await db.execute(
                select(sec_managers.c.crd_number, sec_managers.c.cik),
            )
            managers = managers_result.all()

            payloads: dict[str, str] = {}
            for mgr in managers:
                cik = mgr.cik
                holdings = holdings_by_cik.get(cik, {})
                hhi = hhi_by_cik.get(cik, 0.0)
                drift = drift_by_cik.get(cik, {"turnover": 0.0, "style_drift_detected": False})

                payload = {
                    "top_sector": holdings.get("top_sector", "Unknown"),
                    "hhi": hhi,
                    "position_count": holdings.get("position_count", 0),
                    "portfolio_value": holdings.get("portfolio_value", 0),
                    "turnover": drift["turnover"],
                    "style_drift_detected": drift["style_drift_detected"],
                }
                payloads[f"screener:agg:{mgr.crd_number}"] = json.dumps(payload)

            # ── Step 4: Write to Redis in a pipeline (best-effort) ──
            redis_written = 0
            if payloads:
                try:
                    r = aioredis.Redis(connection_pool=get_redis_pool())
                    pipe = r.pipeline(transaction=False)
                    for key, value in payloads.items():
                        ttl = _BASE_TTL + random.randint(-_JITTER_RANGE, _JITTER_RANGE)
                        pipe.set(key, value, ex=ttl)
                    await pipe.execute()
                    redis_written = len(payloads)
                    logger.info("Redis cache updated", keys_written=redis_written)
                except Exception:
                    logger.warning(
                        "Redis cache update failed — continuous aggregates still refreshed",
                        exc_info=True,
                    )

            summary = {
                "status": "completed",
                "managers_processed": len(managers),
                "holdings_aggregated": len(holdings_by_cik),
                "drift_aggregated": len(drift_by_cik),
                "redis_keys_written": redis_written,
            }
            logger.info("SEC refresh complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SEC_REFRESH_LOCK_ID})"),
            )


if __name__ == "__main__":
    asyncio.run(run_sec_refresh())
