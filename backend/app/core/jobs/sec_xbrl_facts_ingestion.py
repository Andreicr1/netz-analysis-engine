import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.core.jobs._sec_xbrl_parser import iter_facts_from_file

_log = logging.getLogger(__name__)

LOCK_ID = 900_060


async def ingest_sec_xbrl_facts(ciks: list[str] | None = None, limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Ingest SEC XBRL Company Facts from local filesystem into TimescaleDB."""
    companyfacts_dir = settings.companyfacts_dir
    if not companyfacts_dir:
        _log.error("COMPANYFACTS_DIR is not set in environment.")
        return {"error": "COMPANYFACTS_DIR not set"}

    dir_path = Path(companyfacts_dir)
    if not dir_path.is_dir():
        _log.error(f"COMPANYFACTS_DIR {dir_path} is not a directory.")
        return {"error": "COMPANYFACTS_DIR invalid"}

    async with async_session() as db:
        # Acquire advisory lock
        lock_result = await db.execute(text(f"SELECT pg_try_advisory_lock({LOCK_ID})"))
        if not lock_result.scalar():
            _log.info(f"Lock {LOCK_ID} already held by another process. Skipping sec_xbrl_facts_ingestion.")
            return {"error": "lock held", "files_processed": 0, "rows_inserted": 0}

        try:
            _log.info(f"Starting sec_xbrl_facts_ingestion (dry_run={dry_run}, limit={limit})")
            start_time = time.monotonic()
            
            initial_count = await db.scalar(text("SELECT COUNT(*) FROM sec_xbrl_facts"))

            # Resolve universe
            if ciks:
                files = []
                for cik in ciks:
                    # CIK files are typically zero-padded to 10 digits
                    padded_cik = cik.zfill(10)
                    file_path = dir_path / f"CIK{padded_cik}.json"
                    if file_path.exists():
                        files.append(file_path)
                    else:
                        _log.warning(f"File for CIK {cik} not found at {file_path}")
            else:
                files = sorted(dir_path.glob("CIK*.json"))
                
            if limit:
                files = files[:limit]

            total_files = len(files)
            files_processed = 0
            files_failed = 0
            total_rows_inserted = 0

            # Process files
            batch = []
            batch_size = 10_000

            for i, file_path in enumerate(files):
                try:
                    current_cik = None
                    for fact in iter_facts_from_file(file_path):
                        if current_cik is None:
                            current_cik = fact.cik
                        batch.append({
                            "cik": fact.cik,
                            "taxonomy": fact.taxonomy,
                            "concept": fact.concept,
                            "unit": fact.unit,
                            "period_end": fact.period_end,
                            "period_start": fact.period_start,
                            "val": fact.val,
                            "val_text": fact.val_text,
                            "accn": fact.accn,
                            "fy": fact.fy,
                            "fp": fact.fp,
                            "form": fact.form,
                            "filed": fact.filed
                        })

                        if len(batch) >= batch_size:
                            if not dry_run:
                                await _flush_batch(db, batch)
                            total_rows_inserted += len(batch)
                            batch.clear()
                            
                    files_processed += 1
                    
                    if files_processed % 500 == 0 or i == 0 or i == total_files - 1:
                        _log.info(f"Progress: {files_processed}/{total_files} files done (cik={current_cik}). Total inserted: {total_rows_inserted}")
                        
                except Exception as e:
                    _log.error(f"Failed to parse {file_path}: {e}")
                    files_failed += 1

            if batch:
                if not dry_run:
                    await _flush_batch(db, batch)
                total_rows_inserted += len(batch)
                batch.clear()

            final_count = await db.scalar(text("SELECT COUNT(*) FROM sec_xbrl_facts"))
            actual_inserted = final_count - initial_count if initial_count is not None and final_count is not None else 0

            elapsed = time.monotonic() - start_time
            _log.info(f"Finished sec_xbrl_facts_ingestion. Processed {files_processed}, failed {files_failed}, actual inserted {actual_inserted} in {elapsed:.1f}s.")
            return {
                "files_processed": files_processed,
                "files_failed": files_failed,
                "rows_inserted": 0 if dry_run else actual_inserted,
                "rows_would_insert": total_rows_inserted if dry_run else 0,
                "elapsed_sec": elapsed,
            }

        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))


async def _flush_batch(db: AsyncSession, batch: list[dict[str, Any]]) -> None:
    stmt = text("""
        INSERT INTO sec_xbrl_facts (
            cik, taxonomy, concept, unit, period_end, period_start, 
            val, val_text, accn, fy, fp, form, filed
        )
        VALUES (
            :cik, :taxonomy, :concept, :unit, :period_end, :period_start, 
            :val, :val_text, :accn, :fy, :fp, :form, :filed
        )
        ON CONFLICT (cik, taxonomy, concept, unit, period_end, accn) DO NOTHING
    """)
    await db.execute(stmt, batch)
    await db.commit()
