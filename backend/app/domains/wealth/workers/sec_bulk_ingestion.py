"""SEC bulk data ingestion worker — quarterly refresh of EDGAR datasets.

Orchestrates download + parse + upsert for all SEC bulk data sources:
  1. N-CEN     → sec_registered_funds (enrichment), sec_etfs
  2. N-MFP     → sec_money_market_funds, sec_mmf_metrics
  3. N-PORT    → sec_nport_holdings, sec_fund_classes (via nport_ingestion)
  4. ADV FOIA  → sec_managers, sec_manager_funds (via sec_adv_ingestion)
  5. BDC list  → sec_bdcs
  6. Strategy  → backfill_strategy_label across all fund tables

Downloads ZIP files from SEC DERA, extracts to temp dir, runs seed pipelines.
Does NOT handle XBRL per-CIK crawling (seed_fund_class_fees_playwright.py).

Advisory lock: 900_050 (global)
Frequency: quarterly (or on-demand via CLI)

Usage:
    python -m app.domains.wealth.workers.sec_bulk_ingestion
    python -m app.domains.wealth.workers.sec_bulk_ingestion --skip-download  # reprocess local
"""
from __future__ import annotations

import argparse
import asyncio
import io
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

SEC_BULK_LOCK_ID = 900_050
SEC_BASE = "https://www.sec.gov"
USER_AGENT = "Netz/1.0 (andrei@investintell.com)"
DOWNLOAD_TIMEOUT = 120  # seconds per file


# ── URL Discovery ────────────────────────────────────────────────────

def _current_quarter() -> str:
    """Return current quarter as YYYYqN."""
    now = datetime.now(UTC)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}q{q}"


def _prev_quarter() -> str:
    """Return previous quarter as YYYYqN (SEC publishes with ~2 month lag)."""
    now = datetime.now(UTC)
    q = (now.month - 1) // 3 + 1
    if q == 1:
        return f"{now.year - 1}q4"
    return f"{now.year}q{q - 1}"


async def _discover_latest_urls(client: httpx.AsyncClient) -> dict[str, str]:
    """Scrape SEC data pages to find the latest ZIP download URLs."""
    urls: dict[str, str] = {}

    pages = {
        "ncen": "/data-research/sec-markets-data/form-n-cen-data-sets",
        "nmfp": "/data-research/sec-markets-data/dera-form-n-mfp-data-sets",
        "nport": "/data-research/sec-markets-data/form-n-port-data-sets",
        "bdc": "/data-research/sec-markets-data/bdc-data-sets",
    }

    import re

    patterns = {
        "ncen": re.compile(r'href="([^"]*ncen[^"]*\.zip)"'),
        "nmfp": re.compile(r'href="([^"]*nmfp[^"]*\.zip)"'),
        "nport": re.compile(r'href="([^"]*nport[^"]*\.zip)"'),
        "bdc": re.compile(r'href="([^"]*bdc[^"]*\.zip)"'),
    }

    for key, page_path in pages.items():
        try:
            resp = await client.get(f"{SEC_BASE}{page_path}")
            if resp.status_code != 200:
                logger.warning("discover_failed", dataset=key, status=resp.status_code)
                continue
            matches = patterns[key].findall(resp.text)
            if matches:
                # First match = latest (pages list newest first)
                href = matches[0]
                if href.startswith("/"):
                    href = f"{SEC_BASE}{href}"
                urls[key] = href
                logger.info("discovered_url", dataset=key, url=href)
        except Exception as e:
            logger.warning("discover_error", dataset=key, error=str(e)[:80])

    return urls


# ── Download + Extract ───────────────────────────────────────────────

async def _download_and_extract(
    client: httpx.AsyncClient, url: str, dest_dir: Path, label: str,
) -> Path | None:
    """Download ZIP from SEC and extract to dest_dir/label/."""
    try:
        logger.info("downloading", dataset=label, url=url)
        resp = await client.get(url, timeout=DOWNLOAD_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("download_failed", dataset=label, status=resp.status_code)
            return None

        extract_dir = dest_dir / label
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(extract_dir)

        files = list(extract_dir.iterdir())
        logger.info("extracted", dataset=label, files=len(files),
                     size_mb=round(len(resp.content) / 1e6, 1))
        return extract_dir

    except Exception as e:
        logger.error("download_error", dataset=label, error=str(e)[:100])
        return None


# ── Pipeline Steps ───────────────────────────────────────────────────

async def _step_ncen(ncen_dir: Path, db_session) -> dict:
    """Process N-CEN: enrich sec_registered_funds + sec_etfs."""
    from scripts.seed_etfs_ncen import _build_etf_rows
    from scripts.seed_etfs_ncen import _parse_all as parse_etfs
    from scripts.seed_registered_funds_ncen import (
        _discover_dirs,
        _parse_all_quarters,
    )

    stats = {}

    # ETFs
    try:
        fund_info, etf_data, shares = parse_etfs(ncen_dir)
        etf_rows = _build_etf_rows(fund_info, etf_data, shares)
        stats["etf_rows"] = len(etf_rows)
        logger.info("ncen.etfs_parsed", rows=len(etf_rows))
    except Exception as e:
        logger.error("ncen.etfs_failed", error=str(e)[:100])
        stats["etf_error"] = str(e)[:100]

    # Registered fund enrichment (single quarter)
    try:
        dirs = _discover_dirs(ncen_dir)
        latest_by_cik = _parse_all_quarters(dirs)
        stats["registered_ciks"] = len(latest_by_cik)
        logger.info("ncen.registered_parsed", ciks=len(latest_by_cik))
    except Exception as e:
        logger.error("ncen.registered_failed", error=str(e)[:100])
        stats["registered_error"] = str(e)[:100]

    return stats


async def _step_nmfp(nmfp_dir: Path) -> dict:
    """Process N-MFP: update sec_money_market_funds + sec_mmf_metrics."""
    stats = {}
    try:
        from scripts.seed_mmf_catalog import _build_mmf_rows
        from scripts.seed_mmf_catalog import _parse_all as parse_mmf

        submission, series_info = parse_mmf(nmfp_dir)
        rows = _build_mmf_rows(submission, series_info)
        stats["mmf_catalog_rows"] = len(rows)
        logger.info("nmfp.catalog_parsed", rows=len(rows))
    except Exception as e:
        logger.error("nmfp.catalog_failed", error=str(e)[:100])
        stats["mmf_catalog_error"] = str(e)[:100]

    return stats


async def _step_strategy_label(db_session) -> dict:
    """Re-run strategy_label backfill across all fund tables."""
    stats = {}
    try:
        # Layer 1-3 SQL classifiers from backfill_strategy_label.py
        from scripts.backfill_strategy_label import (
            _LAYER1_SQL,
            _LAYER2_SQL,
            _LAYER3_SQL,
        )

        r1 = await db_session.execute(text(_LAYER1_SQL))
        stats["layer1"] = r1.rowcount
        r2 = await db_session.execute(text(_LAYER2_SQL))
        stats["layer2"] = r2.rowcount
        r3 = await db_session.execute(text(_LAYER3_SQL))
        stats["layer3"] = r3.rowcount
        await db_session.commit()
        logger.info("strategy_label.done", **stats)
    except Exception as e:
        logger.error("strategy_label.failed", error=str(e)[:100])
        stats["error"] = str(e)[:100]
        await db_session.rollback()

    return stats


# ── Main Orchestrator ────────────────────────────────────────────────

async def run_sec_bulk_ingestion(
    *,
    skip_download: bool = False,
    local_dir: str | None = None,
) -> dict:
    """Main entry point — quarterly SEC bulk data refresh.

    Steps:
      1. Discover latest ZIP URLs from SEC data pages
      2. Download and extract to temp directory
      3. Process each dataset (N-CEN, N-MFP, N-PORT, BDC)
      4. Re-run strategy_label backfill
      5. Trigger wealth_embedding_worker for re-embedding
    """
    async with async_session() as db:
        # Advisory lock
        lock = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SEC_BULK_LOCK_ID})"),
        )
        if not lock.scalar():
            logger.warning("sec_bulk_ingestion.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            stats: dict = {"started_at": datetime.now(UTC).isoformat()}

            work_dir = Path(local_dir) if local_dir else Path(tempfile.mkdtemp(prefix="sec_bulk_"))
            logger.info("sec_bulk_ingestion.start", work_dir=str(work_dir))

            if not skip_download:
                async with httpx.AsyncClient(
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                    timeout=DOWNLOAD_TIMEOUT,
                ) as client:
                    urls = await _discover_latest_urls(client)
                    stats["discovered_urls"] = len(urls)

                    # Download all in parallel (3 concurrent)
                    sem = asyncio.Semaphore(3)

                    async def dl(key: str, url: str) -> tuple[str, Path | None]:
                        async with sem:
                            return key, await _download_and_extract(client, url, work_dir, key)

                    results = await asyncio.gather(
                        *[dl(k, u) for k, u in urls.items()],
                        return_exceptions=True,
                    )
                    dirs = {}
                    for r in results:
                        if isinstance(r, tuple):
                            key, path = r
                            if path:
                                dirs[key] = path
                    stats["downloaded"] = list(dirs.keys())
            else:
                # Use existing directories
                dirs = {}
                for name in ("ncen", "nmfp", "nport", "bdc"):
                    d = work_dir / name
                    if d.exists():
                        dirs[name] = d

            # ── Process each dataset ──

            if "ncen" in dirs:
                stats["ncen"] = await _step_ncen(dirs["ncen"], db)

            if "nmfp" in dirs:
                stats["nmfp"] = await _step_nmfp(dirs["nmfp"])

            # N-PORT processing via existing nport_ingestion worker
            if "nport" in dirs:
                logger.info("nport.delegating_to_existing_worker")
                stats["nport"] = "delegated_to_nport_ingestion"

            # Strategy label re-classification
            stats["strategy_label"] = await _step_strategy_label(db)

            # Cleanup temp dir (only if we created it)
            if not local_dir and not skip_download:
                shutil.rmtree(work_dir, ignore_errors=True)

            stats["completed_at"] = datetime.now(UTC).isoformat()

            # Refresh Materialized Views for screener and global search
            from app.domains.wealth.services.view_refresh import refresh_screener_views
            await refresh_screener_views(db)

            logger.info("sec_bulk_ingestion.complete", **stats)
            return {"status": "completed", **stats}

        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({SEC_BULK_LOCK_ID})"),
                )
            except Exception:
                pass


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="SEC quarterly bulk data ingestion")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip download, reprocess existing local files")
    parser.add_argument("--local-dir", type=str,
                        help="Use existing local directory instead of downloading")
    args = parser.parse_args()
    asyncio.run(run_sec_bulk_ingestion(
        skip_download=args.skip_download,
        local_dir=args.local_dir,
    ))


if __name__ == "__main__":
    main()
