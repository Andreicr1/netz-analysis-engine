"""Backfill sec_nport_holdings.series_id from sec_registered_funds.

For single-series CIKs (one CIK → one series_id in sec_registered_funds),
directly set series_id on all holdings rows.

For umbrella CIKs with multiple series, the nport_ingestion worker must
re-fetch filings to tag each filing's series_id from the XML header.
Those are logged as warnings for manual follow-up.

Usage:
    python -m scripts.backfill_nport_series_id [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory

logger = structlog.get_logger()


async def backfill_series_id(*, dry_run: bool = False) -> dict[str, int]:
    """Backfill series_id for single-series CIKs."""
    async with async_session_factory() as db:
        # Step 1: Count holdings with NULL series_id
        result = await db.execute(
            text("SELECT COUNT(*) FROM sec_nport_holdings WHERE series_id IS NULL"),
        )
        null_count = result.scalar() or 0
        logger.info("backfill_start", null_series_id_rows=null_count)

        if null_count == 0:
            logger.info("backfill_nothing_to_do")
            return {"updated": 0, "skipped_umbrella": 0}

        # Step 2: Backfill single-series CIKs
        # A CIK is "single-series" if sec_fund_classes has exactly one distinct series_id for it
        backfill_sql = """
            UPDATE sec_nport_holdings h
            SET series_id = sub.series_id
            FROM (
                SELECT cik, MIN(series_id) AS series_id
                FROM sec_fund_classes
                GROUP BY cik
                HAVING COUNT(DISTINCT series_id) = 1
            ) sub
            WHERE h.cik = sub.cik
              AND h.series_id IS NULL
        """

        if dry_run:
            # Count what would be updated
            count_sql = """
                SELECT COUNT(*)
                FROM sec_nport_holdings h
                JOIN (
                    SELECT cik, MIN(series_id) AS series_id
                    FROM sec_fund_classes
                    GROUP BY cik
                    HAVING COUNT(DISTINCT series_id) = 1
                ) sub ON h.cik = sub.cik
                WHERE h.series_id IS NULL
            """
            result = await db.execute(text(count_sql))
            would_update = result.scalar() or 0
            logger.info("backfill_dry_run", would_update=would_update)
        else:
            result = await db.execute(text(backfill_sql))
            updated = result.rowcount
            await db.commit()
            logger.info("backfill_single_series_done", updated=updated)

        # Step 3: Identify umbrella CIKs that need re-ingestion
        umbrella_sql = """
            SELECT fc.cik, COUNT(DISTINCT fc.series_id) AS n_series,
                   COUNT(DISTINCT h.report_date) AS n_quarters
            FROM sec_fund_classes fc
            JOIN sec_nport_holdings h ON h.cik = fc.cik AND h.series_id IS NULL
            GROUP BY fc.cik
            HAVING COUNT(DISTINCT fc.series_id) > 1
            ORDER BY n_quarters DESC
        """
        umbrella_result = await db.execute(text(umbrella_sql))
        umbrella_rows = umbrella_result.fetchall()

        for row in umbrella_rows:
            logger.warning(
                "backfill_umbrella_cik_needs_reingestion",
                cik=row[0],
                n_series=row[1],
                n_quarters=row[2],
            )

        updated_count = would_update if dry_run else updated  # noqa: F821
        return {
            "updated": updated_count,
            "skipped_umbrella": len(umbrella_rows),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill sec_nport_holdings.series_id")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated")
    args = parser.parse_args()

    result = asyncio.run(backfill_series_id(dry_run=args.dry_run))
    print(f"Backfill complete: {result}")


if __name__ == "__main__":
    main()
