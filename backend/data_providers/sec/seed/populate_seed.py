"""SEC Manager Seed Population Script.

One-time job to populate sec_* tables with a curated universe of
investment managers. Resumable via checkpoint file. Run from backend/:

    python -m data_providers.sec.seed.populate_seed [--resume] [--dry-run]
    python -m data_providers.sec.seed.populate_seed --only-adv
    python -m data_providers.sec.seed.populate_seed --only-holdings
    python -m data_providers.sec.seed.populate_seed --only-ticker-map
    python -m data_providers.sec.seed.populate_seed --manager BX
    python -m data_providers.sec.seed.populate_seed --from-quarter 2020-01-01
    python -m data_providers.sec.seed.populate_seed --recent-only

Phases (run in order):
    Phase 1: ADV bulk CSV ingest (all managers at once via FOIA download)
    Phase 2: 13F holdings per manager (most recent first, then historical)
    Phase 3: 13F diffs computation (after holdings complete)
    Phase 4: Sector enrichment (after holdings, uses Redis cache)
    Phase 5: Institutional discovery (endowments/pensions already in list)
    Phase 6: CUSIP → Ticker mapping via OpenFIGI batch API
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from data_providers.sec.seed.manager_seed_list import (
    INSTITUTIONAL_KEYWORDS,
    SEED_MANAGERS,
)
from data_providers.sec.shared import resolve_cik, run_in_sec_thread

logger = structlog.get_logger()

# ── Checkpoint ──────────────────────────────────────────────────────

CHECKPOINT_FILE = Path(".sec_seed_checkpoint.json")


def _load_checkpoint() -> dict[str, Any]:
    """Load checkpoint from disk. Returns fresh state if missing."""
    if CHECKPOINT_FILE.exists():
        try:
            raw = json.loads(CHECKPOINT_FILE.read_text())
            raw.setdefault("completed", [])
            raw.setdefault("failed", {})
            raw["completed"] = set(raw["completed"])
            return raw
        except Exception as exc:
            logger.warning("checkpoint_load_failed", error=str(exc))
    return {"completed": set(), "failed": {}}


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Persist checkpoint to disk."""
    serializable = {
        "completed": sorted(checkpoint["completed"]),
        "failed": checkpoint["failed"],
    }
    CHECKPOINT_FILE.write_text(json.dumps(serializable, indent=2))


# ── CIK Resolution for seed list ───────────────────────────────────


async def _resolve_cik_for_seed(
    name: str,
    ticker: str | None,
) -> str | None:
    """Resolve CIK for a seed manager entry. Returns zero-padded 10-digit CIK."""
    resolution = await run_in_sec_thread(resolve_cik, name, ticker)
    if resolution.cik:
        return resolution.cik
    return None


# ── DB Session Factory ──────────────────────────────────────────────


def _get_db_session_factory() -> Any:
    """Import and return the async session factory.

    Lazy import to avoid loading the full app on --help.
    """
    from app.core.db.engine import async_session_factory
    return async_session_factory


# ── Phase 1: ADV Bulk CSV ──────────────────────────────────────────


async def phase1_adv_ingest(*, dry_run: bool = False) -> dict[str, int]:
    """Download monthly ADV bulk CSV from SEC FOIA. Upserts all managers."""
    from data_providers.sec.adv_service import AdvService

    stats = {"total": len(SEED_MANAGERS), "upserted": 0, "not_found": 0, "errors": 0}

    if dry_run:
        logger.info("phase1.dry_run", total_managers=stats["total"])
        return stats

    db_factory = _get_db_session_factory()
    adv_service = AdvService(db_session_factory=db_factory)

    try:
        count = await adv_service.ingest_bulk_adv()
        stats["upserted"] = count
        logger.info("phase1.bulk_ingest_complete", managers_upserted=count)
    except Exception as exc:
        logger.error("phase1.bulk_ingest_failed", error=str(exc))
        stats["errors"] = 1
        return stats

    # Verify seed managers are in DB
    for name, _ticker, crd, _notes in SEED_MANAGERS:
        if crd:
            manager = await adv_service.fetch_manager(crd)
            if not manager:
                logger.warning("phase1.seed_not_found", crd=crd, name=name)
                stats["not_found"] += 1

    _print_phase_summary("Phase 1 — ADV Ingest", stats)
    return stats


# ── Phase 2: 13F Holdings ──────────────────────────────────────────


async def phase2_thirteenf_holdings(
    *,
    priority_quarters: int = 8,
    full_quarters: int = 100,
    recent_only: bool = False,
    single_manager_ticker: str | None = None,
    from_quarter: date | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Two-pass 13F ingestion: recent quarters first, then full history."""
    from data_providers.sec.thirteenf_service import ThirteenFService

    stats = {
        "managers_processed": 0,
        "holdings_ingested": 0,
        "no_13f": 0,
        "failed": 0,
        "skipped": 0,
    }

    # Filter seed list if --manager specified
    managers = list(SEED_MANAGERS)
    if single_manager_ticker:
        managers = [
            m for m in managers
            if m[1] and m[1].upper() == single_manager_ticker.upper()
        ]
        if not managers:
            # Try matching by CRD
            managers = [
                m for m in SEED_MANAGERS
                if m[2] == single_manager_ticker
            ]
        if not managers:
            logger.error("phase2.manager_not_found", filter=single_manager_ticker)
            return stats

    if dry_run:
        logger.info(
            "phase2.dry_run",
            managers=len(managers),
            priority_quarters=priority_quarters,
            recent_only=recent_only,
        )
        # Resolve CIKs for plan display
        for name, ticker, crd, notes in managers:
            resolution = await _resolve_cik_for_seed(name, ticker)
            logger.info(
                "phase2.plan",
                name=name,
                ticker=ticker,
                crd=crd,
                cik=resolution,
                notes=notes,
            )
        return stats

    db_factory = _get_db_session_factory()
    thirteenf = ThirteenFService(db_session_factory=db_factory)
    checkpoint = _load_checkpoint()

    # Pass 1: Recent quarters for all managers
    logger.info(
        "phase2.pass1_start",
        managers=len(managers),
        quarters=priority_quarters,
    )
    for name, ticker, crd, notes in managers:
        cik = await _resolve_cik_for_seed(name, ticker)
        if not cik:
            logger.warning("phase2.cik_not_resolved", name=name, crd=crd)
            stats["no_13f"] += 1
            continue

        checkpoint_key = f"{cik}:recent"
        if checkpoint_key in checkpoint["completed"]:
            logger.info("phase2.skip_already_done", cik=cik, name=name)
            stats["skipped"] += 1
            continue

        try:
            holdings = await thirteenf.fetch_holdings(
                cik,
                quarters=priority_quarters,
                force_refresh=False,
            )
            count = len(holdings)
            stats["managers_processed"] += 1
            stats["holdings_ingested"] += count

            if count == 0:
                stats["no_13f"] += 1
                logger.info("phase2.no_holdings", cik=cik, name=name)
            else:
                logger.info(
                    "phase2.holdings_ingested",
                    cik=cik,
                    name=name,
                    positions=count,
                )

            checkpoint["completed"].add(checkpoint_key)
            _save_checkpoint(checkpoint)

        except Exception as exc:
            logger.error("phase2.holdings_failed", cik=cik, name=name, error=str(exc))
            checkpoint["failed"][cik] = str(exc)
            _save_checkpoint(checkpoint)
            stats["failed"] += 1
            continue

        await asyncio.sleep(2.0)

    _print_phase_summary("Phase 2 — 13F Holdings (Pass 1: Recent)", stats)

    # Pass 2: Full history (remaining quarters)
    if recent_only:
        logger.info("phase2.pass2_skipped_recent_only")
        return stats

    logger.info("phase2.pass2_start", managers=len(managers), quarters=full_quarters)
    pass2_stats = {"computed": 0, "failed": 0}

    for name, ticker, crd, notes in managers:
        cik = await _resolve_cik_for_seed(name, ticker)
        if not cik:
            continue

        checkpoint_key = f"{cik}:full"
        if checkpoint_key in checkpoint["completed"]:
            continue

        try:
            holdings = await thirteenf.fetch_holdings(
                cik,
                quarters=full_quarters,
                force_refresh=False,
            )
            pass2_stats["computed"] += 1
            logger.info(
                "phase2.full_history_complete",
                cik=cik,
                name=name,
                positions=len(holdings),
            )
            checkpoint["completed"].add(checkpoint_key)
            _save_checkpoint(checkpoint)
        except Exception as exc:
            logger.error(
                "phase2.full_history_failed",
                cik=cik,
                name=name,
                error=str(exc),
            )
            pass2_stats["failed"] += 1
            continue

        await asyncio.sleep(2.0)

    logger.info("phase2.pass2_complete", **pass2_stats)
    return stats


# ── Phase 3: Diffs ─────────────────────────────────────────────────


async def phase3_compute_diffs(*, dry_run: bool = False) -> dict[str, int]:
    """Compute quarter-over-quarter diffs for all managers with >= 2 quarters."""
    from sqlalchemy import text

    from data_providers.sec.thirteenf_service import ThirteenFService

    stats = {"manager_quarter_pairs": 0, "diffs_computed": 0, "already_existed": 0, "failed": 0}

    db_factory = _get_db_session_factory()

    # Find all managers with multiple quarters
    async with db_factory() as session:
        result = await session.execute(text(
            "SELECT cik, array_agg(DISTINCT report_date ORDER BY report_date) "
            "FROM sec_13f_holdings "
            "GROUP BY cik "
            "HAVING COUNT(DISTINCT report_date) >= 2"
        ))
        managers_with_history = result.fetchall()

    total_pairs = sum(len(quarters) - 1 for _, quarters in managers_with_history)
    stats["manager_quarter_pairs"] = total_pairs

    if dry_run:
        logger.info(
            "phase3.dry_run",
            managers=len(managers_with_history),
            pairs=total_pairs,
        )
        return stats

    thirteenf = ThirteenFService(db_session_factory=db_factory)

    for cik, quarters in managers_with_history:
        for i in range(len(quarters) - 1):
            quarter_from = quarters[i]
            quarter_to = quarters[i + 1]

            # Check if diff already exists
            async with db_factory() as session:
                existing = await session.execute(text(
                    "SELECT 1 FROM sec_13f_diffs "
                    "WHERE cik = :cik AND quarter_from = :qf AND quarter_to = :qt "
                    "LIMIT 1"
                ), {"cik": cik, "qf": quarter_from, "qt": quarter_to})
                if existing.scalar_one_or_none() is not None:
                    stats["already_existed"] += 1
                    continue

            try:
                diffs = await thirteenf.compute_diffs(cik, quarter_from, quarter_to)
                stats["diffs_computed"] += len(diffs)
                logger.info(
                    "phase3.diffs_computed",
                    cik=cik,
                    quarter_from=quarter_from.isoformat(),
                    quarter_to=quarter_to.isoformat(),
                    changes=len(diffs),
                )
            except Exception as exc:
                logger.error(
                    "phase3.diff_failed",
                    cik=cik,
                    quarter_from=quarter_from.isoformat(),
                    quarter_to=quarter_to.isoformat(),
                    error=str(exc),
                )
                stats["failed"] += 1

    _print_phase_summary("Phase 3 — Diffs", stats)
    return stats


# ── Phase 4: Sector Enrichment ─────────────────────────────────────


async def phase4_sector_enrichment(*, dry_run: bool = False) -> dict[str, int]:
    """Enrich all holdings with sector data. Redis cache deduplicates CUSIPs."""
    from sqlalchemy import text

    from data_providers.sec.thirteenf_service import ThirteenFService

    stats = {"managers_to_enrich": 0, "enriched": 0, "failed": 0}

    db_factory = _get_db_session_factory()

    # Find managers with un-enriched holdings
    async with db_factory() as session:
        result = await session.execute(text(
            "SELECT DISTINCT cik FROM sec_13f_holdings "
            "WHERE sector IS NULL ORDER BY cik"
        ))
        unenriched_ciks = [row[0] for row in result.fetchall()]

    stats["managers_to_enrich"] = len(unenriched_ciks)

    if dry_run:
        logger.info("phase4.dry_run", managers_to_enrich=len(unenriched_ciks))
        return stats

    logger.info("phase4.start", managers_to_enrich=len(unenriched_ciks))
    thirteenf = ThirteenFService(db_session_factory=db_factory)

    for cik in unenriched_ciks:
        # Get latest quarter for this manager
        async with db_factory() as session:
            result = await session.execute(text(
                "SELECT MAX(report_date) FROM sec_13f_holdings WHERE cik = :cik"
            ), {"cik": cik})
            latest_quarter = result.scalar()

        if not latest_quarter:
            continue

        try:
            enriched_count = await thirteenf.enrich_holdings_with_sectors(
                cik, latest_quarter,
            )
            stats["enriched"] += enriched_count
            logger.info(
                "phase4.enriched",
                cik=cik,
                enriched=enriched_count,
            )
        except Exception as exc:
            logger.error(
                "phase4.enrich_failed",
                cik=cik,
                error=str(exc),
            )
            stats["failed"] += 1

        await asyncio.sleep(0.5)

    _print_phase_summary("Phase 4 — Sector Enrichment", stats)
    return stats


# ── Phase 5: Institutional Allocations ─────────────────────────────


async def phase5_institutional(*, dry_run: bool = False) -> dict[str, int]:
    """Fetch holdings for institutional filers (endowments, pensions, sovereigns)."""
    from data_providers.sec.institutional_service import InstitutionalService
    from data_providers.sec.thirteenf_service import ThirteenFService

    stats = {"filers": 0, "holdings_ingested": 0, "failed": 0}

    # Filter seed list for institutional filers
    institutional_entries = [
        (name, ticker, crd, notes)
        for name, ticker, crd, notes in SEED_MANAGERS
        if any(kw in notes.lower() for kw in INSTITUTIONAL_KEYWORDS)
    ]
    stats["filers"] = len(institutional_entries)

    if dry_run:
        logger.info("phase5.dry_run", filers=len(institutional_entries))
        for name, _ticker, _crd, notes in institutional_entries:
            logger.info("phase5.plan", name=name, notes=notes)
        return stats

    db_factory = _get_db_session_factory()
    thirteenf = ThirteenFService(db_session_factory=db_factory)
    institutional = InstitutionalService(
        thirteenf_service=thirteenf,
        db_session_factory=db_factory,
    )

    for name, ticker, crd, notes in institutional_entries:
        cik = await _resolve_cik_for_seed(name, ticker)
        if not cik:
            logger.warning("phase5.cik_not_resolved", name=name)
            continue

        # Classify filer type from notes
        filer_type = "unknown"
        for kw in INSTITUTIONAL_KEYWORDS:
            if kw in notes.lower():
                filer_type = kw
                break

        try:
            allocations = await institutional.fetch_allocations(
                filer_cik=cik,
                filer_name=name,
                filer_type=filer_type,
                quarters=8,
                force_refresh=False,
            )
            stats["holdings_ingested"] += len(allocations)
            logger.info(
                "phase5.allocations_fetched",
                cik=cik,
                name=name,
                allocations=len(allocations),
            )
        except Exception as exc:
            logger.error(
                "phase5.fetch_failed",
                cik=cik,
                name=name,
                error=str(exc),
            )
            stats["failed"] += 1

        await asyncio.sleep(2.0)

    _print_phase_summary("Phase 5 — Institutional Allocations", stats)
    return stats


# ── Phase 6: CUSIP → Ticker Mapping ────────────────────────────────


async def phase6_cusip_ticker_mapping(
    *,
    api_key: str | None = None,
    force_retry_unresolved: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve CUSIPs to tickers via OpenFIGI batch API. Persists to sec_cusip_ticker_map."""
    from sqlalchemy import text

    from data_providers.sec.shared import (
        OPENFIGI_BATCH_SIZE,
        resolve_cusip_to_ticker_batch,
    )

    stats = {
        "total_cusips": 0,
        "resolved": 0,
        "tradeable": 0,
        "unresolved": 0,
        "batches": 0,
    }

    db_factory = _get_db_session_factory()

    # Get all unique CUSIPs not yet resolved (or unresolved if retry)
    async with db_factory() as session:
        if force_retry_unresolved:
            result = await session.execute(text(
                "SELECT DISTINCT h.cusip, h.issuer_name "
                "FROM sec_13f_holdings h "
                "LEFT JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip "
                "WHERE m.cusip IS NULL "
                "   OR m.resolved_via = 'unresolved' "
                "ORDER BY h.cusip"
            ))
        else:
            result = await session.execute(text(
                "SELECT DISTINCT h.cusip, h.issuer_name "
                "FROM sec_13f_holdings h "
                "LEFT JOIN sec_cusip_ticker_map m ON h.cusip = m.cusip "
                "WHERE m.cusip IS NULL "
                "ORDER BY h.cusip"
            ))
        unresolved_rows = result.fetchall()

    stats["total_cusips"] = len(unresolved_rows)

    if dry_run:
        logger.info("phase6.dry_run", total_cusips=len(unresolved_rows))
        _print_phase_summary("Phase 6 — CUSIP Ticker Mapping (dry run)", stats)
        return stats

    if not unresolved_rows:
        logger.info("phase6.nothing_to_do")
        _print_phase_summary("Phase 6 — CUSIP Ticker Mapping", stats)
        return stats

    # Build batches of 100
    batches: list[list[tuple[str, str]]] = []
    for i in range(0, len(unresolved_rows), OPENFIGI_BATCH_SIZE):
        batches.append(unresolved_rows[i : i + OPENFIGI_BATCH_SIZE])

    sleep_between = 0.25 if api_key else 2.4
    logger.info(
        "phase6.start",
        total_cusips=len(unresolved_rows),
        batches=len(batches),
        rate_mode="api_key" if api_key else "free_tier",
        sleep_between=sleep_between,
    )

    import httpx
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.shared.models import SecCusipTickerMap

    async with httpx.AsyncClient() as http_client:
        for batch_num, batch in enumerate(batches, 1):
            cusips = [row[0] for row in batch]

            results = await resolve_cusip_to_ticker_batch(
                cusips,
                http_client=http_client,
                api_key=api_key,
            )

            # Upsert to sec_cusip_ticker_map
            now = datetime.now(timezone.utc)
            rows = [
                {
                    "cusip": r.cusip,
                    "ticker": r.ticker,
                    "issuer_name": r.issuer_name,
                    "exchange": r.exchange,
                    "security_type": r.security_type,
                    "figi": r.figi,
                    "composite_figi": r.composite_figi,
                    "resolved_via": r.resolved_via,
                    "is_tradeable": r.is_tradeable,
                    "last_verified_at": now,
                }
                for r in results
            ]

            async with db_factory() as session, session.begin():
                stmt = pg_insert(SecCusipTickerMap).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cusip"],
                    set_={
                        "ticker": stmt.excluded.ticker,
                        "issuer_name": stmt.excluded.issuer_name,
                        "exchange": stmt.excluded.exchange,
                        "security_type": stmt.excluded.security_type,
                        "figi": stmt.excluded.figi,
                        "composite_figi": stmt.excluded.composite_figi,
                        "resolved_via": stmt.excluded.resolved_via,
                        "is_tradeable": stmt.excluded.is_tradeable,
                        "last_verified_at": stmt.excluded.last_verified_at,
                    },
                    where=(
                        (SecCusipTickerMap.resolved_via == "unresolved")
                        | (stmt.excluded.resolved_via != "unresolved")
                    ),
                )
                await session.execute(stmt)

            batch_tradeable = sum(1 for r in results if r.is_tradeable)
            batch_unresolved = sum(1 for r in results if r.resolved_via == "unresolved")
            batch_resolved = len(results) - batch_unresolved
            stats["resolved"] += batch_resolved
            stats["tradeable"] += batch_tradeable
            stats["unresolved"] += batch_unresolved
            stats["batches"] += 1

            logger.info(
                "phase6.batch_complete",
                batch=batch_num,
                total_batches=len(batches),
                resolved=batch_resolved,
                tradeable=batch_tradeable,
                unresolved=batch_unresolved,
            )

            await asyncio.sleep(sleep_between)

    _print_phase_summary("Phase 6 — CUSIP Ticker Mapping", stats)
    return stats


# ── Summary Printer ─────────────────────────────────────────────────


def _print_phase_summary(title: str, stats: dict[str, int]) -> None:
    """Print a formatted summary table for a phase."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    max_key_len = max(len(k) for k in stats) if stats else 0
    for key, value in stats.items():
        label = key.replace("_", " ").title()
        print(f"  {label:<{max_key_len + 10}} {value:>10,}")
    print(f"{'=' * 60}\n")


# ── Main ────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SEC Manager Seed Population Script",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint (skips completed managers)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve CIKs and print plan without DB writes",
    )
    parser.add_argument(
        "--only-adv", action="store_true",
        help="Only run Phase 1 (ADV bulk CSV ingest)",
    )
    parser.add_argument(
        "--only-holdings", action="store_true",
        help="Only run Phase 2 (13F holdings)",
    )
    parser.add_argument(
        "--manager",
        help="Only process a single manager by ticker or CRD",
    )
    parser.add_argument(
        "--from-quarter",
        help="Start from specific quarter (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--recent-only", action="store_true",
        help="Only ingest recent 8 quarters (Pass 1 only)",
    )
    parser.add_argument(
        "--openfigi-key",
        help="OpenFIGI API key (free at openfigi.com/api). "
             "Without key: 25 req/min. With key: 250 req/min.",
        default=os.environ.get("OPENFIGI_API_KEY"),
    )
    parser.add_argument(
        "--only-ticker-map", action="store_true",
        help="Run Phase 6 only (CUSIP ticker mapping)",
    )
    parser.add_argument(
        "--retry-unresolved", action="store_true",
        help="Re-attempt previously unresolved CUSIPs in Phase 6",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()

    # edgartools requires identity before any API call
    import edgar
    edgar.set_identity("Netz Analysis Engine contact@nexvest.ai")

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    from_quarter: date | None = None
    if args.from_quarter:
        from_quarter = date.fromisoformat(args.from_quarter)

    start = time.monotonic()

    print(f"\nSEC Seed Population — {len(SEED_MANAGERS)} managers")
    print(f"Dry run: {args.dry_run}")
    print(f"Resume: {args.resume}")
    if args.manager:
        print(f"Single manager: {args.manager}")
    print()

    # Clear checkpoint if not resuming
    if not args.resume and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("checkpoint_cleared")

    if args.only_adv:
        await phase1_adv_ingest(dry_run=args.dry_run)
    elif args.only_holdings:
        await phase2_thirteenf_holdings(
            recent_only=args.recent_only,
            single_manager_ticker=args.manager,
            from_quarter=from_quarter,
            dry_run=args.dry_run,
        )
    elif args.only_ticker_map:
        await phase6_cusip_ticker_mapping(
            api_key=args.openfigi_key,
            force_retry_unresolved=args.retry_unresolved,
            dry_run=args.dry_run,
        )
    else:
        # Full pipeline: all 6 phases in order
        await phase1_adv_ingest(dry_run=args.dry_run)
        await phase2_thirteenf_holdings(
            recent_only=args.recent_only,
            single_manager_ticker=args.manager,
            from_quarter=from_quarter,
            dry_run=args.dry_run,
        )
        await phase3_compute_diffs(dry_run=args.dry_run)
        await phase4_sector_enrichment(dry_run=args.dry_run)
        await phase5_institutional(dry_run=args.dry_run)
        await phase6_cusip_ticker_mapping(
            api_key=args.openfigi_key,
            force_retry_unresolved=args.retry_unresolved,
            dry_run=args.dry_run,
        )

    elapsed = time.monotonic() - start
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    if CHECKPOINT_FILE.exists():
        checkpoint = _load_checkpoint()
        completed = len(checkpoint["completed"])
        failed = len(checkpoint["failed"])
        print(f"Checkpoint: {completed} completed, {failed} failed")


if __name__ == "__main__":
    asyncio.run(_main())
