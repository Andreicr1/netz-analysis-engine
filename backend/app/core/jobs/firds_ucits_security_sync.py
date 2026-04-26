"""FIRDS UCITS Security Sync — populates esma_securities from FIRDS FULINS_C.

PR-Q11B Phase 1.3. Downloads the ESMA FIRDS daily file, stream-parses XML,
and upserts share-class ISINs linked to ``esma_funds.lei``.

Lock: zlib.crc32(b"netz.wealth.esma.firds.sync") & 0x7FFFFFFF.
Frequency: daily (03:30 UTC) + on-demand after esma_ingestion.

Flow:
  1. pg_try_advisory_lock; skip if busy.
  2. Load known_leis from esma_funds.
  3. ExternalProviderGate("firds") — download + parse FIRDS FULINS_C.
  4. Batch upsert into esma_securities (1000 rows per batch).
  5. Mark rows not seen in this run as is_active=false (staleness gate).
  6. Release lock in finally.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import ExternalProviderGate, GateConfig
from data_providers.esma.firds_service import FirdsInstrument, FirdsService

logger = structlog.get_logger(__name__)

# Deterministic crc32 of stable identifier per charter §3.
LOCK_ID = zlib.crc32(b"netz.wealth.esma.firds.sync") & 0x7FFFFFFF

_FIRDS_GATE_CONFIG = GateConfig(
    name="firds",
    timeout_s=600.0,  # 10 min — large file download
    failure_threshold=3,
    recovery_after_s=60.0,
)

_BATCH_SIZE = 1000

_UPSERT_SQL = text("""
    INSERT INTO esma_securities (
        isin, fund_lei, full_name, cfi_code, currency,
        mic, firds_file_url, firds_publication_date,
        last_seen_at, data_fetched_at, is_active
    ) VALUES (
        :isin, :fund_lei, :full_name, :cfi_code, :currency,
        :mic, :firds_file_url, :firds_publication_date,
        now(), now(), true
    )
    ON CONFLICT (isin) DO UPDATE SET
        fund_lei = EXCLUDED.fund_lei,
        full_name = EXCLUDED.full_name,
        cfi_code = EXCLUDED.cfi_code,
        currency = EXCLUDED.currency,
        mic = EXCLUDED.mic,
        firds_file_url = EXCLUDED.firds_file_url,
        firds_publication_date = EXCLUDED.firds_publication_date,
        last_seen_at = now(),
        data_fetched_at = now(),
        is_active = true
""")


@dataclass
class FirdsSyncResult:
    status: str
    files_processed: int = 0
    rows_upserted: int = 0
    rows_deactivated: int = 0
    known_leis: int = 0
    error: str | None = None


async def run_firds_ucits_security_sync(
    db: AsyncSession,
    *,
    target_date: date | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Run the FIRDS UCITS security sync worker."""
    run_started_at = datetime.now(timezone.utc)

    # 1. Advisory lock
    lock_result = await db.execute(
        text("SELECT pg_try_advisory_lock(:lock_id)"),
        {"lock_id": LOCK_ID},
    )
    acquired = lock_result.scalar()
    if not acquired:
        logger.info("firds_sync.skipped_lock_busy")
        return {"status": "skipped", "reason": "lock_busy"}

    try:
        # 2. Load known LEIs
        lei_rows = await db.execute(text("SELECT lei FROM esma_funds"))
        known_leis: set[str] = {row.lei for row in lei_rows.fetchall()}
        logger.info("firds_sync.known_leis_loaded", count=len(known_leis))

        if not known_leis:
            logger.warning("firds_sync.no_esma_funds")
            return {"status": "skipped", "reason": "no_esma_funds"}

        # 3. Download and parse via ExternalProviderGate
        gate = ExternalProviderGate(_FIRDS_GATE_CONFIG)

        async with FirdsService() as svc:
            # Discover URL
            firds_url = await gate.call(
                "firds_url_discovery",
                lambda: svc.find_latest_fulins_c_url(),
            )
            logger.info("firds_sync.url_resolved", url=firds_url)

            # Download ZIP
            zip_data = await gate.call(
                "firds_download",
                lambda: svc.download_zip(firds_url),
            )

        # 4. Parse and batch upsert
        svc_parser = FirdsService()
        batch: list[dict[str, object]] = []
        rows_upserted = 0
        parse_date = target_date or date.today()

        for instrument in svc_parser.parse_xml(zip_data, lei_filter=known_leis):
            if dry_run:
                rows_upserted += 1
                continue

            batch.append(_instrument_to_params(instrument, firds_url, parse_date))

            if len(batch) >= _BATCH_SIZE:
                await _flush_batch(db, batch)
                rows_upserted += len(batch)
                batch.clear()

        # Flush remaining
        if batch and not dry_run:
            await _flush_batch(db, batch)
            rows_upserted += len(batch)
            batch.clear()

        logger.info("firds_sync.upsert_complete", rows_upserted=rows_upserted)

        # 5. Staleness gate — only after successful full parse
        rows_deactivated = 0
        if not dry_run and rows_upserted > 0:
            deactivate_result = await db.execute(
                text("""
                    UPDATE esma_securities SET is_active = false
                    WHERE last_seen_at < :run_started_at
                      AND fund_lei IN (SELECT lei FROM esma_funds)
                      AND is_active = true
                """),
                {"run_started_at": run_started_at},
            )
            rows_deactivated = deactivate_result.rowcount  # type: ignore[assignment]
            logger.info("firds_sync.staleness_applied", deactivated=rows_deactivated)

        await db.commit()

        return {
            "status": "dry_run" if dry_run else "success",
            "files_processed": 1,
            "rows_upserted": rows_upserted,
            "rows_deactivated": rows_deactivated,
            "known_leis": len(known_leis),
        }

    except Exception as e:
        logger.error("firds_sync.failed", error=str(e)[:300])
        await db.rollback()
        return {"status": "error", "error": str(e)[:300]}

    finally:
        await db.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": LOCK_ID},
        )


def _instrument_to_params(
    inst: FirdsInstrument,
    firds_url: str,
    pub_date: date,
) -> dict[str, object]:
    return {
        "isin": inst.isin,
        "fund_lei": inst.lei,
        "full_name": inst.full_name or "",
        "cfi_code": inst.cfi_code,
        "currency": inst.currency,
        "mic": inst.mic,
        "firds_file_url": firds_url,
        "firds_publication_date": pub_date,
    }


async def _flush_batch(db: AsyncSession, batch: list[dict[str, object]]) -> None:
    for params in batch:
        await db.execute(_UPSERT_SQL, params)
