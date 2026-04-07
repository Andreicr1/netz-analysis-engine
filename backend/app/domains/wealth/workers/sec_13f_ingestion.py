"""SEC 13F ingestion worker — quarterly institutional holdings from EDGAR.

Usage:
    python -m app.domains.wealth.workers.sec_13f_ingestion

Iterates REGISTERED investment managers with AUM >= $100M (the SEC 13F-HR
filing threshold), fetches 13F-HR filings via edgartools, upserts holdings
into sec_13f_holdings hypertable, computes quarter-over-quarter diffs into
sec_13f_diffs, and enriches missing sectors.

Only targets managers likely to file 13F-HR — filters out RIAs, brokers,
and other financial services that don't file institutional holdings.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_021.
"""

import asyncio
from datetime import date

import structlog
from sqlalchemy import select, text

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import SecManager

logger = structlog.get_logger()
SEC_13F_LOCK_ID = 900_021

# SEC 13F-HR filing threshold: institutional investment managers with
# >= $100M in qualifying assets must file quarterly.
_13F_AUM_THRESHOLD = 100_000_000


async def run_sec_13f_ingestion(
    *,
    quarters: int = 8,
    enrich_sectors: bool = True,
    aum_min: int = _13F_AUM_THRESHOLD,
    target_ciks: list[str] | None = None,
) -> dict:
    """Fetch 13F holdings for registered investment managers and upsert.

    Targets only managers with registration_status='Registered' and
    AUM >= $100M (the 13F filing threshold). Pass ``target_ciks`` to
    override with a specific CIK list.

    Steps per CIK:
    1. fetch_holdings(force_refresh=True) — EDGAR API → sec_13f_holdings
    2. compute_diffs for last 2 quarters   — DB read  → sec_13f_diffs
    3. enrich_holdings_with_sectors         — OpenFIGI/yfinance → DB update
    """
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SEC_13F_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("sec_13f_ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            if target_ciks:
                ciks = target_ciks
            else:
                # Only registered investment managers above 13F threshold
                result = await db.execute(
                    select(SecManager.cik)
                    .where(
                        SecManager.cik.isnot(None),
                        SecManager.registration_status == "Registered",
                        SecManager.aum_total >= aum_min,
                    )
                    .order_by(SecManager.aum_total.desc()),
                )
                ciks = [row[0] for row in result.all() if row[0]]

            if not ciks:
                logger.info("sec_13f_no_managers_with_cik")
                return {"status": "completed", "managers": 0, "holdings": 0}

            logger.info("sec_13f_ingestion_start", managers=len(ciks))

            # edgartools requires identity before any EDGAR API call
            import edgar
            edgar.set_identity("Netz Analysis Engine tech@netzco.com")

            from data_providers.sec.thirteenf_service import ThirteenFService

            service = ThirteenFService(db_session_factory=async_session)

            total_holdings = 0
            total_diffs = 0
            total_enriched = 0
            errors = 0

            for cik in ciks:
                try:
                    # 1. Fetch and persist holdings from EDGAR
                    holdings = await service.fetch_holdings(
                        cik, quarters=quarters, force_refresh=True,
                    )
                    total_holdings += len(holdings)

                    if not holdings:
                        continue

                    # 2. Compute diffs for the two most recent quarters
                    report_dates = sorted(
                        {h.report_date for h in holdings}, reverse=True,
                    )
                    if len(report_dates) >= 2:
                        q_to = date.fromisoformat(report_dates[0])
                        q_from = date.fromisoformat(report_dates[1])
                        diffs = await service.compute_diffs(cik, q_from, q_to)
                        total_diffs += len(diffs)

                    # 3. Enrich sectors (best-effort)
                    if enrich_sectors:
                        latest_date = date.fromisoformat(report_dates[0])
                        enriched = await service.enrich_holdings_with_sectors(
                            cik, latest_date,
                        )
                        total_enriched += enriched

                    logger.debug(
                        "sec_13f_cik_complete",
                        cik=cik,
                        holdings=len(holdings),
                    )
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "sec_13f_cik_failed",
                        cik=cik,
                        error=str(exc),
                    )

            # Post-ingestion: refresh sec_13f_manager_sector_latest MV
            mv_refreshed = False
            try:
                logger.info("sec_13f_refreshing_sector_mv")
                await db.execute(
                    text(
                        "REFRESH MATERIALIZED VIEW CONCURRENTLY "
                        "sec_13f_manager_sector_latest"
                    ),
                )
                await db.commit()
                mv_refreshed = True
                logger.info("sec_13f_sector_mv_refreshed")
            except Exception:
                await db.rollback()
                # Fallback: non-concurrent refresh (slower but always works)
                try:
                    await db.execute(
                        text(
                            "REFRESH MATERIALIZED VIEW "
                            "sec_13f_manager_sector_latest"
                        ),
                    )
                    await db.commit()
                    mv_refreshed = True
                except Exception as mv_exc:
                    await db.rollback()
                    logger.warning(
                        "sec_13f_sector_mv_refresh_failed",
                        error=str(mv_exc),
                    )

            summary = {
                "status": "completed",
                "managers": len(ciks),
                "holdings": total_holdings,
                "diffs": total_diffs,
                "sectors_enriched": total_enriched,
                "errors": errors,
                "mv_sector_latest_refreshed": mv_refreshed,
            }
            logger.info("sec_13f_ingestion_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SEC_13F_LOCK_ID})"),
            )


if __name__ == "__main__":
    asyncio.run(run_sec_13f_ingestion())
