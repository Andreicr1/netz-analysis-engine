"""Worker: geography_enrichment — populate investment_geography on instruments_universe.

Advisory lock: 900_060 (deterministic)
Frequency: on-demand + after universe_sync
Idempotent: updates NULL rows (or all if recalculate=True)
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.services.geography_classifier import classify_geography

logger = structlog.get_logger()

GEOGRAPHY_ENRICHMENT_LOCK_ID = 900_060
_BATCH_SIZE = 500


async def run_geography_enrichment(recalculate: bool = False) -> dict:
    """Populate instruments_universe.investment_geography using 3-layer classifier."""
    logger.info("geography_enrichment.start", recalculate=recalculate)

    async with async_session() as db:
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({GEOGRAPHY_ENRICHMENT_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("geography_enrichment.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            stats = await _enrich(db, recalculate=recalculate)
            logger.info("geography_enrichment.done", **stats)
            return stats
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({GEOGRAPHY_ENRICHMENT_LOCK_ID})"),
            )


async def _enrich(db: AsyncSession, *, recalculate: bool) -> dict:
    """Core enrichment logic."""

    # 1. Fetch instruments needing classification
    where_clause = "" if recalculate else "WHERE iu.investment_geography IS NULL"
    rows = await db.execute(text(f"""
        SELECT
            iu.instrument_id,
            iu.name,
            iu.attributes->>'strategy_label' as strategy_label,
            iu.attributes->>'fund_subtype' as fund_subtype,
            iu.attributes->>'sec_universe' as sec_universe,
            iu.attributes->>'domicile' as domicile,
            iu.attributes->>'sec_cik' as sec_cik,
            iu.geography as block_geography
        FROM instruments_universe iu
        {where_clause}
        AND iu.is_active = true
    """))
    instruments = rows.mappings().all()

    if not instruments:
        return {"computed": 0, "skipped": 0, "total_active": 0}

    # 2. Batch-fetch N-PORT country allocations for instruments with sec_cik
    cik_set = {r["sec_cik"] for r in instruments if r["sec_cik"]}
    nport_allocations = await _fetch_nport_country_allocations(db, cik_set) if cik_set else {}

    # 3. Classify and collect updates
    updates: list[tuple[str, str]] = []  # (instrument_id, geography)
    for r in instruments:
        cik = r["sec_cik"]
        country_allocs = nport_allocations.get(cik) if cik else None

        # Determine universe_type from attributes
        sec_universe = r["sec_universe"]
        fund_subtype = r["fund_subtype"]
        if sec_universe in ("ucits", "esma"):
            universe_type = "esma"
        elif fund_subtype in ("etf", "bdc"):
            universe_type = "registered_us"
        else:
            universe_type = sec_universe

        geo = classify_geography(
            fund_type=fund_subtype,
            universe_type=universe_type,
            domicile=r["domicile"],
            strategy_label=r["strategy_label"],
            fund_name=r["name"],
            nport_country_allocations=country_allocs,
        )
        updates.append((str(r["instrument_id"]), geo))

    # 4. Batch UPDATE
    computed = 0
    for i in range(0, len(updates), _BATCH_SIZE):
        batch = updates[i : i + _BATCH_SIZE]
        # Build VALUES list for bulk update
        values_parts = []
        params: dict = {}
        for j, (iid, geo) in enumerate(batch):
            params[f"id_{j}"] = iid
            params[f"geo_{j}"] = geo
            values_parts.append(f"(:id_{j}::uuid, :geo_{j})")

        values_sql = ", ".join(values_parts)
        await db.execute(text(f"""
            UPDATE instruments_universe iu
            SET investment_geography = v.geo,
                updated_at = now()
            FROM (VALUES {values_sql}) AS v(id, geo)
            WHERE iu.instrument_id = v.id
        """), params)
        await db.commit()
        computed += len(batch)

    return {"computed": computed, "skipped": 0, "total_active": len(instruments)}


async def _fetch_nport_country_allocations(
    db: AsyncSession,
    cik_set: set[str],
) -> dict[str, dict[str, float]]:
    """Fetch latest N-PORT country allocations grouped by CIK.

    Returns: {cik: {country_code: pct_of_nav_total}}
    """
    if not cik_set:
        return {}

    cik_list = list(cik_set)
    result = await db.execute(text("""
        WITH latest_dates AS (
            SELECT cik, MAX(report_date) as max_date
            FROM sec_nport_holdings
            WHERE cik = ANY(:ciks)
            GROUP BY cik
        )
        SELECT
            h.cik,
            LEFT(h.isin, 2) as country_code,
            SUM(h.pct_of_nav) as total_pct
        FROM sec_nport_holdings h
        JOIN latest_dates ld ON h.cik = ld.cik AND h.report_date = ld.max_date
        WHERE h.isin IS NOT NULL
          AND LENGTH(h.isin) >= 2
        GROUP BY h.cik, LEFT(h.isin, 2)
    """), {"ciks": cik_list})

    allocations: dict[str, dict[str, float]] = {}
    for row in result.mappings().all():
        cik = row["cik"]
        country = row["country_code"]
        pct = float(row["total_pct"]) if row["total_pct"] else 0.0
        allocations.setdefault(cik, {})[country] = pct

    return allocations
