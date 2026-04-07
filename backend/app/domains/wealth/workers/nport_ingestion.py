"""N-PORT ingestion worker — fetches monthly mutual fund holdings from SEC EDGAR.

Usage:
    python -m app.domains.wealth.workers.nport_ingestion

Fetches N-PORT filings for active registered funds from sec_registered_funds
(dynamic, AUM-filtered), parses holdings from XML, upserts into
sec_nport_holdings hypertable, and updates last_nport_date.

Falls back to sec_managers CIKs if sec_registered_funds is empty (bootstrap).

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_018.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import SecManager

logger = structlog.get_logger()
NPORT_LOCK_ID = 900_018
_DYNAMIC_BATCH_LIMIT = 200


async def run_nport_ingestion(months: int = 12) -> dict[str, Any]:
    """Fetch N-PORT holdings for active funds and upsert to hypertable."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NPORT_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("N-PORT ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # Dynamic CIK source: sec_registered_funds (preferred)
            ciks = await _get_ciks_from_registered_funds(db)

            if not ciks:
                # Fallback: sec_managers (bootstrap, before discovery runs)
                result = await db.execute(
                    select(SecManager.cik).where(SecManager.cik.isnot(None)),
                )
                ciks = [row[0] for row in result.all() if row[0]]
                logger.info("nport_fallback_to_sec_managers", count=len(ciks))

            if not ciks:
                logger.info("nport_no_ciks_to_process")
                return {"status": "completed", "managers": 0, "holdings": 0}

            logger.info("nport_ingestion_start", managers=len(ciks))

            from data_providers.sec.nport_service import NportService

            service = NportService(db_session_factory=async_session)

            total_holdings = 0
            errors = 0

            for cik in ciks:
                try:
                    holdings = await service.fetch_holdings(
                        cik, months=months, force_refresh=True,
                    )
                    total_holdings += len(holdings)

                    # Update last_nport_date in sec_registered_funds
                    if holdings:
                        latest_date = max(h.report_date for h in holdings)
                        await _update_last_nport_date(db, cik, latest_date)

                    logger.debug(
                        "nport_cik_complete",
                        cik=cik,
                        holdings=len(holdings),
                    )
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "nport_cik_failed",
                        cik=cik,
                        error=str(exc),
                    )

            # Best-effort GICS sector enrichment for equity holdings
            enriched = await _enrich_nport_sectors(db)

            summary = {
                "status": "completed",
                "managers": len(ciks),
                "holdings": total_holdings,
                "errors": errors,
                "sectors_enriched": enriched,
            }
            logger.info("nport_ingestion_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({NPORT_LOCK_ID})"),
            )


async def _get_ciks_from_registered_funds(db: AsyncSession) -> list[str]:
    """Get CIKs from sec_registered_funds that need N-PORT refresh."""
    try:
        result = await db.execute(
            text("""
                SELECT cik FROM sec_registered_funds
                WHERE aum_below_threshold = FALSE
                  AND (last_nport_date IS NULL
                       OR last_nport_date < now() - INTERVAL '35 days')
                ORDER BY total_assets DESC NULLS LAST
                LIMIT :limit
            """),
            {"limit": _DYNAMIC_BATCH_LIMIT},
        )
        return [row[0] for row in result.all()]
    except Exception as exc:
        # Table may not exist yet (pre-migration)
        logger.debug("sec_registered_funds_query_failed", error=str(exc))
        return []


_EQUITY_ASSET_CATS = {"EC", "EP"}
_ENRICHMENT_BATCH = 500


async def _enrich_nport_sectors(db: AsyncSession) -> int:
    """Best-effort GICS sector enrichment for equity holdings without sector.

    Uses the same 3-tier resolve_sector() cascade as 13F (SIC → OpenFIGI →
    keyword heuristic).  Only processes equity holdings (EC/EP) whose
    ``sector`` is still a raw issuerCat code (CORP, RF, etc.) rather than
    an enriched GICS sector.  Capped at ``_ENRICHMENT_BATCH`` CUSIPs per run
    to respect external API rate limits.
    """
    try:
        from data_providers.sec.shared import resolve_sector, run_in_sec_thread

        # Find distinct equity CUSIPs with only raw issuerCat codes
        result = await db.execute(
            text("""
                SELECT DISTINCT cusip, issuer_name
                FROM sec_nport_holdings
                WHERE asset_class IN ('EC', 'EP')
                  AND (sector IS NULL
                       OR sector IN ('CORP', 'UST', 'USGA', 'USGSE', 'NUSS',
                                     'MUN', 'RF', 'PF', 'OTHER', 'EC', 'OT'))
                LIMIT :lim
            """),
            {"lim": _ENRICHMENT_BATCH},
        )
        to_resolve = [(r[0], r[1] or "") for r in result.all()]

        if not to_resolve:
            return 0

        enriched = 0
        for cusip, issuer_name in to_resolve:
            sector = await run_in_sec_thread(resolve_sector, cusip, issuer_name)
            if not sector:
                continue

            await db.execute(
                text("""
                    UPDATE sec_nport_holdings
                    SET sector = :sector
                    WHERE cusip = :cusip
                      AND asset_class IN ('EC', 'EP')
                      AND (sector IS NULL
                           OR sector IN ('CORP', 'UST', 'USGA', 'USGSE', 'NUSS',
                                         'MUN', 'RF', 'PF', 'OTHER', 'EC', 'OT'))
                """),
                {"cusip": cusip, "sector": sector},
            )
            enriched += 1

        await db.commit()
        logger.info("nport_sector_enrichment_complete", enriched=enriched, attempted=len(to_resolve))
        return enriched

    except Exception as exc:
        logger.warning("nport_sector_enrichment_failed", error=str(exc))
        return 0


async def _update_last_nport_date(db: AsyncSession, cik: str, report_date: str) -> None:
    """Update last_nport_date for a fund after successful ingestion."""
    try:
        await db.execute(
            text("""
                UPDATE sec_registered_funds
                SET last_nport_date = :report_date
                WHERE cik = :cik
            """),
            {"cik": cik, "report_date": report_date},
        )
        await db.commit()
    except Exception as exc:
        logger.debug("last_nport_date_update_failed", cik=cik, error=str(exc))


if __name__ == "__main__":
    asyncio.run(run_nport_ingestion())
