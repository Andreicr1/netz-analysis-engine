"""BIS statistics ingestion worker — credit-to-GDP gap, DSR, property prices.

Advisory lock ID = 900_014 (deterministic).
Scope: global. Frequency: quarterly.
Upserts into bis_statistics hypertable.
"""

import asyncio
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import BisStatistics
from data_providers.bis.service import BisIndicator, fetch_all_bis_data

logger = structlog.get_logger()

BIS_INGESTION_LOCK_ID = 900_014


def _bis_to_rows(indicators: list[BisIndicator]) -> list[dict]:
    """Convert BisIndicator dataclasses to upsert-ready dicts."""
    rows: list[dict] = []
    for ind in indicators:
        try:
            val = Decimal(str(ind.value))
        except (InvalidOperation, ValueError):
            continue
        rows.append({
            "country_code": ind.country_code,
            "indicator": ind.indicator,
            "period": ind.period,
            "value": val,
            "dataset": ind.dataset,
        })
    return rows


async def run_bis_ingestion() -> dict:
    """Fetch BIS statistics and upsert into bis_statistics hypertable.

    Returns summary dict with status and row counts.
    """
    logger.info("Starting BIS ingestion")

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({BIS_INGESTION_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.warning("BIS ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            indicators = await fetch_all_bis_data()

            if not indicators:
                logger.warning("No BIS data returned")
                return {"status": "completed", "rows": 0}

            rows = _bis_to_rows(indicators)
            if not rows:
                logger.warning("No valid BIS rows after conversion")
                return {"status": "completed", "rows": 0}

            # Deduplicate by PK
            seen: dict[tuple, dict] = {}
            for r in rows:
                seen[(r["country_code"], r["indicator"], r["period"])] = r
            rows = list(seen.values())

            # Batch upsert in chunks of 2000
            chunk_size = 2000
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                stmt = pg_insert(BisStatistics).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["country_code", "indicator", "period"],
                    set_={
                        "value": stmt.excluded.value,
                        "dataset": stmt.excluded.dataset,
                    },
                )
                await db.execute(stmt)

            await db.commit()

            # Refresh Materialized Views for macro performance layer
            from app.domains.wealth.services.macro_view_refresh import refresh_macro_views
            await refresh_macro_views(db)

            logger.info(
                "BIS ingestion complete",
                total_rows=len(rows),
                datasets=len({r["dataset"] for r in rows}),
                countries=len({r["country_code"] for r in rows}),
            )

            return {
                "status": "completed",
                "rows": len(rows),
                "datasets": list({r["dataset"] for r in rows}),
                "countries": len({r["country_code"] for r in rows}),
            }

        except Exception:
            await db.rollback()
            raise
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({BIS_INGESTION_LOCK_ID})"),
                )
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(run_bis_ingestion())
