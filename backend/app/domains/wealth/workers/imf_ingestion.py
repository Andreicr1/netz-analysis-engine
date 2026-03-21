"""IMF WEO ingestion worker — GDP, inflation, fiscal, debt forecasts.

Advisory lock ID = 900_015 (deterministic).
Scope: global. Frequency: quarterly (WEO published April + October).
Upserts into imf_weo_forecasts hypertable.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import ImfWeoForecast
from data_providers.imf.service import ImfForecast, fetch_all_imf_data

logger = structlog.get_logger()

IMF_INGESTION_LOCK_ID = 900_015


def _imf_to_rows(forecasts: list[ImfForecast]) -> list[dict]:
    """Convert ImfForecast dataclasses to upsert-ready dicts."""
    now = datetime.now(tz=timezone.utc)
    rows: list[dict] = []
    for fc in forecasts:
        try:
            val = Decimal(str(fc.value))
        except (InvalidOperation, ValueError):
            continue
        rows.append({
            "country_code": fc.country_code,
            "indicator": fc.indicator,
            "year": fc.year,
            "period": now,  # publication timestamp
            "value": val,
            "edition": fc.edition,
        })
    return rows


async def run_imf_ingestion() -> dict:
    """Fetch IMF WEO forecasts and upsert into imf_weo_forecasts hypertable.

    Returns summary dict with status and row counts.
    """
    logger.info("Starting IMF WEO ingestion")

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({IMF_INGESTION_LOCK_ID})")
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.warning("IMF ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            forecasts = await fetch_all_imf_data()

            if not forecasts:
                logger.warning("No IMF data returned")
                return {"status": "completed", "rows": 0}

            rows = _imf_to_rows(forecasts)
            if not rows:
                logger.warning("No valid IMF rows after conversion")
                return {"status": "completed", "rows": 0}

            # Batch upsert in chunks of 2000
            chunk_size = 2000
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                stmt = pg_insert(ImfWeoForecast).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["country_code", "indicator", "year", "period"],
                    set_={
                        "value": stmt.excluded.value,
                        "edition": stmt.excluded.edition,
                    },
                )
                await db.execute(stmt)

            await db.commit()

            logger.info(
                "IMF WEO ingestion complete",
                total_rows=len(rows),
                indicators=len({r["indicator"] for r in rows}),
                countries=len({r["country_code"] for r in rows}),
            )

            return {
                "status": "completed",
                "rows": len(rows),
                "indicators": list({r["indicator"] for r in rows}),
                "countries": len({r["country_code"] for r in rows}),
            }

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({IMF_INGESTION_LOCK_ID})")
            )


if __name__ == "__main__":
    asyncio.run(run_imf_ingestion())
