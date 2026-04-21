import concurrent.futures as cf
import logging
import time
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import asyncpg

from app.core.config.settings import settings
from app.core.jobs._sec_xbrl_parser import iter_facts_from_file


def get_direct_database_url() -> str:
    """Return the direct Timescale connection string for asyncpg."""
    url = settings.database_url
    if "pgbouncer" in url:
        # Simplistic fallback if pgbouncer is used in standard database_url
        url = url.replace("5432", "5434")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url

_log = logging.getLogger(__name__)

LOCK_ID = 900_060
COPY_COLUMNS = [
    "cik", "taxonomy", "concept", "unit", "period_end", "period_start",
    "val", "val_text", "accn", "fy", "fp", "form", "filed"
]


def _parse_file_chunk(paths: list[Path]) -> list[dict[str, Any]]:
    """Worker function: parse N files, return flat list of record dicts.
    Runs in child process. No DB access here."""
    records = []
    for p in paths:
        try:
            for fact in iter_facts_from_file(p):
                records.append({
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
                    "filed": fact.filed,
                })
        except Exception as exc:
            # Return sentinel; main process logs + counts failure
            records.append({"_error": str(exc), "_path": str(p)})
    return records


async def _build_asyncpg_pool(size: int) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn=get_direct_database_url(),
        min_size=2,
        max_size=size + 2,
    )


async def _copy_batch_to_db(pool: asyncpg.Pool, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    # Convert dicts to tuple records in COPY_COLUMNS order
    rows = [tuple(r.get(c) for c in COPY_COLUMNS) for r in records]
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Create temp staging with same schema
            await conn.execute("""
                CREATE TEMP TABLE _xbrl_stage (LIKE sec_xbrl_facts INCLUDING DEFAULTS) 
                ON COMMIT DROP;
            """)
            # COPY into staging
            await conn.copy_records_to_table(
                "_xbrl_stage", records=rows, columns=COPY_COLUMNS
            )
            # INSERT SELECT with ON CONFLICT preserves idempotency
            await conn.execute("""
                INSERT INTO sec_xbrl_facts (""" + ",".join(COPY_COLUMNS) + """)
                SELECT """ + ",".join(COPY_COLUMNS) + """ FROM _xbrl_stage
                ON CONFLICT (cik, taxonomy, concept, unit, period_end, accn) DO NOTHING
            """)
    return len(rows)


async def ingest_sec_xbrl_facts(
    ciks: list[str] | None = None, 
    limit: int | None = None, 
    dry_run: bool = False,
    workers: int = 16
) -> dict[str, Any]:
    """Ingest SEC XBRL Company Facts from local filesystem into TimescaleDB using parallel processes."""
    companyfacts_dir = settings.companyfacts_dir
    if not companyfacts_dir:
        _log.error("COMPANYFACTS_DIR is not set in environment.")
        return {"error": "COMPANYFACTS_DIR not set"}

    dir_path = Path(companyfacts_dir)
    if not dir_path.is_dir():
        _log.error(f"COMPANYFACTS_DIR {dir_path} is not a directory.")
        return {"error": "COMPANYFACTS_DIR invalid"}

    pool = await _build_asyncpg_pool(size=workers)
    try:
        async with pool.acquire() as conn:
            # Acquire advisory lock
            lock_result = await conn.fetchval(f"SELECT pg_try_advisory_lock({LOCK_ID})")
            if not lock_result:
                _log.info(f"Lock {LOCK_ID} already held by another process. Skipping sec_xbrl_facts_ingestion.")
                return {"error": "lock held", "files_processed": 0, "rows_inserted": 0}

            try:
                _log.info(f"Starting sec_xbrl_facts_ingestion (dry_run={dry_run}, limit={limit}, workers={workers})")
                start_time = time.monotonic()
                
                initial_count = await conn.fetchval("SELECT COUNT(*) FROM sec_xbrl_facts")

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

                ctx = get_context("spawn")
                with cf.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as proc_pool:
                    chunk_size = 20
                    chunks = [files[i:i+chunk_size] for i in range(0, len(files), chunk_size)]
                    max_in_flight = workers * 2

                    pending: set[cf.Future] = set()
                    chunk_iter = iter(enumerate(chunks))

                    def submit_next() -> bool:
                        try:
                            idx, chunk = next(chunk_iter)
                            fut = proc_pool.submit(_parse_file_chunk, chunk)
                            fut._chunk = chunk  # type: ignore[attr-defined]
                            pending.add(fut)
                            return True
                        except StopIteration:
                            return False

                    # Seed initial batch
                    for _ in range(min(max_in_flight, len(chunks))):
                        submit_next()

                    while pending:
                        done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                        for fut in done:
                            chunk = fut._chunk  # type: ignore[attr-defined]
                            try:
                                records = fut.result()
                                errors = [r for r in records if "_error" in r]
                                real_records = [r for r in records if "_error" not in r]

                                files_failed += len(errors)
                                for e in errors:
                                    _log.error(f"Failed to parse {e['_path']}: {e['_error']}")

                                if real_records:
                                    if not dry_run:
                                        sub_batch_size = 20_000
                                        for i in range(0, len(real_records), sub_batch_size):
                                            await _copy_batch_to_db(pool, real_records[i:i+sub_batch_size])
                                    total_rows_inserted += len(real_records)

                                files_processed += len(chunk) - len(errors)
                                del records, real_records

                                if files_processed % 500 < chunk_size or files_processed == total_files:
                                    _log.info(f"Progress: {files_processed}/{total_files} files done. Total inserted: {total_rows_inserted}")

                            except Exception:
                                _log.exception("Future error processing chunk of %d files", len(chunk))

                        # Refill pending up to max_in_flight
                        while len(pending) < max_in_flight:
                            if not submit_next():
                                break

                final_count = await conn.fetchval("SELECT COUNT(*) FROM sec_xbrl_facts")
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
                await conn.execute(f"SELECT pg_advisory_unlock({LOCK_ID})")
    finally:
        await pool.close()
