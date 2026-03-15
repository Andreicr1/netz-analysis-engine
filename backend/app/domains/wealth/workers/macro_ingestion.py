"""Macro intelligence ingestion worker — regional FRED data + scoring.

Usage:
    python -m app.domains.wealth.workers.macro_ingestion

Fetches ~45 FRED series across 4 regions (US, Europe, Asia, EM) and global
indicators using concurrent domain batching.  Computes regional macro scores
via percentile-rank normalization.  Stores snapshot in macro_regional_snapshots
and upserts individual series to macro_data for backward compatibility with
regime_service.get_latest_macro_values().

Advisory lock ID = 43 (separate from drift_check's 42).

REPLACES fred_ingestion.py (superset: 45 series vs 10).
See fred_ingestion.py header for cutover sequence.
DO NOT run both workers simultaneously.
"""

import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.shared.models import MacroData, MacroRegionalSnapshot
from quant_engine.fred_service import FredObservation, FredService
from quant_engine.macro_snapshot_builder import build_regional_snapshot
from quant_engine.regional_macro_service import (
    build_fetch_configs,
    get_all_series_ids,
)

# Suppress httpx DEBUG logs that would expose FRED API key in URL parameters
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = structlog.get_logger()

MACRO_INGESTION_LOCK_ID = 43


def _obs_to_macro_data_rows(
    raw_observations: dict[str, list[FredObservation]],
) -> list[dict]:
    """Convert FredObservation dicts to macro_data upsert rows."""
    rows: list[dict] = []
    for series_id, obs_list in raw_observations.items():
        for obs in obs_list:
            if obs.value is None:
                continue
            try:
                val = Decimal(str(obs.value))
            except (InvalidOperation, ValueError):
                continue
            rows.append({
                "series_id": series_id,
                "obs_date": obs.date,
                "value": val,
                "source": "fred",
                "is_derived": False,
            })
    return rows


async def run_macro_ingestion(
    lookback_years: int = 10,
) -> dict:
    """Fetch all FRED series, compute regional scores, store snapshot.

    Returns summary dict with series counts and snapshot status.
    """
    api_key = settings.fred_api_key
    if not api_key:
        logger.error(
            "FRED_API_KEY not set — skipping macro ingestion. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
        return {"status": "skipped", "reason": "no_api_key"}

    today = date.today()
    observation_start = str(today - timedelta(days=lookback_years * 365))

    logger.info(
        "Starting macro ingestion",
        lookback_years=lookback_years,
        observation_start=observation_start,
        total_series=len(get_all_series_ids()),
    )

    # ── Acquire advisory lock ──────────────────────────────────
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({MACRO_INGESTION_LOCK_ID})")
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.warning("Macro ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # ── Fetch FRED data (concurrent domain batching) ──
            domain_batches = build_fetch_configs(observation_start)

            with FredService(api_key) as fred:
                raw_observations = await asyncio.to_thread(
                    fred.fetch_batch_concurrent,
                    domain_batches,
                    observation_start=observation_start,
                    max_workers=5,  # US, EUROPE, ASIA, EM, GLOBAL
                )

            series_counts = {
                sid: len(obs)
                for sid, obs in raw_observations.items()
            }
            total_obs = sum(series_counts.values())
            logger.info("FRED fetch complete", total_observations=total_obs, series=len(series_counts))

            if total_obs == 0:
                logger.error("No FRED data returned — aborting snapshot")
                return {"status": "failed", "reason": "no_data"}

            # ── Build snapshot (pure computation) ──────────────
            snapshot_data = await asyncio.to_thread(
                build_regional_snapshot,
                raw_observations,
                as_of=today,
            )

            # ── Persist snapshot ───────────────────────────────
            snapshot_stmt = pg_insert(MacroRegionalSnapshot).values(
                as_of_date=today,
                data_json=snapshot_data,
                created_by="worker:macro_ingestion",
            )
            snapshot_stmt = snapshot_stmt.on_conflict_do_update(
                index_elements=["as_of_date"],
                set_={
                    "data_json": snapshot_stmt.excluded.data_json,
                    "updated_by": "worker:macro_ingestion",
                },
            )
            await db.execute(snapshot_stmt)

            # ── Upsert to macro_data (backward compat) ────────
            macro_rows = _obs_to_macro_data_rows(raw_observations)
            if macro_rows:
                # Batch in chunks to avoid oversized statements
                chunk_size = 2000
                for i in range(0, len(macro_rows), chunk_size):
                    chunk = macro_rows[i : i + chunk_size]
                    stmt = pg_insert(MacroData).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["series_id", "obs_date"],
                        set_={
                            "value": stmt.excluded.value,
                            "source": stmt.excluded.source,
                            "is_derived": stmt.excluded.is_derived,
                        },
                    )
                    await db.execute(stmt)

            await db.commit()

            logger.info(
                "Macro ingestion complete",
                snapshot_date=str(today),
                total_observations=total_obs,
                macro_data_rows=len(macro_rows),
                regions=list(snapshot_data.get("regions", {}).keys()),
            )

            return {
                "status": "completed",
                "snapshot_date": str(today),
                "series_counts": series_counts,
                "total_observations": total_obs,
                "macro_data_rows": len(macro_rows),
            }

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({MACRO_INGESTION_LOCK_ID})")
            )


if __name__ == "__main__":
    asyncio.run(run_macro_ingestion())
