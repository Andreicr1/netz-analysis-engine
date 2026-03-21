"""ESMA UCITS Seed Population Script.

4-phase resumable pipeline to populate esma_* tables with European
UCITS fund data. Run from backend/:

    python -m data_providers.esma.seed.populate_seed [--resume] [--dry-run]
    python -m data_providers.esma.seed.populate_seed --only-register
    python -m data_providers.esma.seed.populate_seed --only-resolve
    python -m data_providers.esma.seed.populate_seed --only-nav
    python -m data_providers.esma.seed.populate_seed --only-crossref

Phases (run in order):
    Phase 1: ESMA Solr API → esma_managers + esma_funds
    Phase 2: ISIN resolution via OpenFIGI → esma_isin_ticker_map
    Phase 3: NAV backfill via yfinance → nav_timeseries
    Phase 4: SEC cross-reference via fuzzy match → esma_managers.sec_crd_number
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# ── Checkpoint ──────────────────────────────────────────────────────

CHECKPOINT_FILE = Path(".esma_seed_checkpoint.json")


def _load_checkpoint() -> dict[str, Any]:
    """Load checkpoint from disk. Returns fresh state if missing."""
    if CHECKPOINT_FILE.exists():
        try:
            raw = json.loads(CHECKPOINT_FILE.read_text())
            raw.setdefault("phase1_complete", False)
            raw.setdefault("phase2_resolved", [])
            raw.setdefault("phase3_backfilled", [])
            raw.setdefault("phase4_complete", False)
            raw.setdefault("failed", {})
            result: dict[str, Any] = raw
            return result
        except Exception as exc:
            logger.warning("checkpoint_load_failed", error=str(exc))
    return {
        "phase1_complete": False,
        "phase2_resolved": [],
        "phase3_backfilled": [],
        "phase4_complete": False,
        "failed": {},
    }


def _save_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Persist checkpoint to disk."""
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2))


# ── DB Session Factory ──────────────────────────────────────────────


def _get_db_session_factory() -> Any:
    """Import and return the async session factory. Lazy to avoid loading app on --help."""
    from app.core.db.engine import async_session_factory
    return async_session_factory


# ── Phase 1: ESMA Register → esma_managers + esma_funds ───────────


async def phase1_register_ingest(
    *,
    max_pages: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch UCITS fund data from ESMA Solr API. Upserts managers and funds."""
    from sqlalchemy import text as sa_text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from data_providers.esma.register_service import RegisterService, parse_manager_from_doc

    stats = {"managers": 0, "funds": 0, "skipped": 0, "errors": 0}

    if dry_run:
        async with RegisterService() as svc:
            total = await svc.get_total_count()
            logger.info("phase1.dry_run", total_ucits=total)
            stats["funds"] = total
        return stats

    db_factory = _get_db_session_factory()

    # Collect all funds and derive managers
    managers: dict[str, dict[str, Any]] = {}
    funds_batch: list[dict[str, Any]] = []
    batch_size = 2000

    async with RegisterService() as svc:
        total = await svc.get_total_count()
        logger.info("phase1.starting", total_ucits=total, max_pages=max_pages)

        page_num = 0
        async for fund in svc.iter_ucits_funds(max_pages=max_pages):
            # Track manager
            mid = fund.esma_manager_id
            if mid not in managers:
                managers[mid] = {
                    "esma_id": mid,
                    "company_name": f"Manager {mid}",  # placeholder
                    "fund_count": 0,
                }
            managers[mid]["fund_count"] = managers[mid].get("fund_count", 0) + 1

            # Buffer fund
            funds_batch.append({
                "isin": fund.isin,
                "fund_name": fund.fund_name,
                "esma_manager_id": fund.esma_manager_id,
                "domicile": fund.domicile,
                "fund_type": fund.fund_type,
                "host_member_states": fund.host_member_states or None,
                "data_fetched_at": datetime.now(timezone.utc),
            })

            # Flush in batches
            if len(funds_batch) >= batch_size:
                await _flush_phase1_batch(db_factory, managers, funds_batch, stats)
                funds_batch.clear()

    # Flush remaining
    if funds_batch:
        await _flush_phase1_batch(db_factory, managers, funds_batch, stats)

    logger.info(
        "phase1.complete",
        managers=stats["managers"],
        funds=stats["funds"],
        errors=stats["errors"],
    )
    return stats


async def _flush_phase1_batch(
    db_factory: Any,
    managers: dict[str, dict[str, Any]],
    funds_batch: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    """Upsert a batch of managers + funds to the database."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.shared.models import EsmaFund, EsmaManager

    async with db_factory() as session:
        try:
            # Upsert managers referenced by this batch
            manager_ids_in_batch = {f["esma_manager_id"] for f in funds_batch}
            mgr_rows = [
                managers[mid] for mid in manager_ids_in_batch if mid in managers
            ]
            if mgr_rows:
                stmt = pg_insert(EsmaManager).values(mgr_rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["esma_id"],
                    set_={
                        "company_name": stmt.excluded.company_name,
                        "fund_count": stmt.excluded.fund_count,
                        "data_fetched_at": stmt.excluded.data_fetched_at,
                    },
                )
                await session.execute(stmt)
                stats["managers"] = len(managers)

            # Upsert funds
            stmt = pg_insert(EsmaFund).values(funds_batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["isin"],
                set_={
                    "fund_name": stmt.excluded.fund_name,
                    "esma_manager_id": stmt.excluded.esma_manager_id,
                    "domicile": stmt.excluded.domicile,
                    "fund_type": stmt.excluded.fund_type,
                    "host_member_states": stmt.excluded.host_member_states,
                    "data_fetched_at": stmt.excluded.data_fetched_at,
                },
            )
            await session.execute(stmt)
            stats["funds"] += len(funds_batch)

            await session.commit()
        except Exception as exc:
            await session.rollback()
            stats["errors"] += 1
            logger.error("phase1.batch_upsert_failed", error=str(exc))


# ── Phase 2: ISIN → Ticker Resolution ──────────────────────────────


async def phase2_isin_resolution(
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve ISINs from esma_funds to Yahoo Finance tickers via OpenFIGI."""
    from sqlalchemy import text as sa_text
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.shared.models import EsmaFund, EsmaIsinTickerMap
    from data_providers.esma.ticker_resolver import TickerResolver

    stats = {"total": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    checkpoint = _load_checkpoint()
    already_resolved = set(checkpoint.get("phase2_resolved", []))

    db_factory = _get_db_session_factory()

    # Fetch all ISINs from esma_funds that haven't been resolved yet
    async with db_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT isin FROM esma_funds "
                "WHERE yahoo_ticker IS NULL "
                "ORDER BY isin"
            )
        )
        all_isins = [row[0] for row in result.fetchall()]

    # Filter out already-resolved from checkpoint
    pending_isins = [i for i in all_isins if i not in already_resolved]
    stats["total"] = len(pending_isins)

    if dry_run:
        logger.info("phase2.dry_run", total_pending=len(pending_isins))
        return stats

    logger.info("phase2.starting", total_pending=len(pending_isins))

    async with TickerResolver(api_key=api_key) as resolver:
        batch_size = 100
        for i in range(0, len(pending_isins), batch_size):
            batch = pending_isins[i : i + batch_size]

            try:
                results = await resolver.resolve_batch(batch)
            except Exception as exc:
                stats["errors"] += 1
                logger.error("phase2.batch_failed", error=str(exc))
                continue

            # Upsert to esma_isin_ticker_map
            rows = [
                {
                    "isin": r.isin,
                    "yahoo_ticker": r.yahoo_ticker,
                    "exchange": r.exchange,
                    "resolved_via": r.resolved_via,
                    "is_tradeable": r.is_tradeable,
                    "last_verified_at": datetime.now(timezone.utc),
                }
                for r in results
            ]

            async with db_factory() as session:
                try:
                    stmt = pg_insert(EsmaIsinTickerMap).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["isin"],
                        set_={
                            "yahoo_ticker": stmt.excluded.yahoo_ticker,
                            "exchange": stmt.excluded.exchange,
                            "resolved_via": stmt.excluded.resolved_via,
                            "is_tradeable": stmt.excluded.is_tradeable,
                            "last_verified_at": stmt.excluded.last_verified_at,
                        },
                    )
                    await session.execute(stmt)

                    # Update esma_funds with resolved tickers
                    for r in results:
                        if r.yahoo_ticker:
                            await session.execute(
                                sa_text(
                                    "UPDATE esma_funds SET yahoo_ticker = :ticker, "
                                    "ticker_resolved_at = :ts WHERE isin = :isin"
                                ),
                                {
                                    "ticker": r.yahoo_ticker,
                                    "ts": datetime.now(timezone.utc),
                                    "isin": r.isin,
                                },
                            )
                            stats["resolved"] += 1
                        else:
                            stats["unresolved"] += 1

                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    stats["errors"] += 1
                    logger.error("phase2.upsert_failed", error=str(exc))
                    continue

            # Update checkpoint
            checkpoint["phase2_resolved"].extend([r.isin for r in results])
            _save_checkpoint(checkpoint)

    logger.info(
        "phase2.complete",
        resolved=stats["resolved"],
        unresolved=stats["unresolved"],
        errors=stats["errors"],
    )
    return stats


# ── Phase 3: NAV Backfill ───────────────────────────────────────────


async def phase3_nav_backfill(
    *,
    years: int = 3,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill NAV data for resolved ESMA tickers into nav_timeseries."""
    from sqlalchemy import text as sa_text

    stats = {"total": 0, "backfilled": 0, "skipped": 0, "errors": 0}

    checkpoint = _load_checkpoint()
    already_backfilled = set(checkpoint.get("phase3_backfilled", []))

    db_factory = _get_db_session_factory()

    # Get tradeable ISINs with tickers
    async with db_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT isin, yahoo_ticker FROM esma_isin_ticker_map "
                "WHERE is_tradeable = true AND yahoo_ticker IS NOT NULL "
                "ORDER BY isin"
            )
        )
        ticker_map = {row[0]: row[1] for row in result.fetchall()}

    pending = {k: v for k, v in ticker_map.items() if k not in already_backfilled}
    stats["total"] = len(pending)

    if dry_run:
        logger.info("phase3.dry_run", total_pending=len(pending))
        return stats

    logger.info("phase3.starting", total_pending=len(pending))

    for isin, ticker in pending.items():
        try:
            count = await _backfill_single_ticker(db_factory, isin, ticker, years)
            if count > 0:
                stats["backfilled"] += 1
            else:
                stats["skipped"] += 1

            checkpoint["phase3_backfilled"].append(isin)
            _save_checkpoint(checkpoint)
        except Exception as exc:
            stats["errors"] += 1
            logger.warning(
                "phase3.ticker_failed",
                isin=isin,
                ticker=ticker,
                error=str(exc),
            )

    logger.info(
        "phase3.complete",
        backfilled=stats["backfilled"],
        skipped=stats["skipped"],
        errors=stats["errors"],
    )
    return stats


async def _backfill_single_ticker(
    db_factory: Any,
    isin: str,
    ticker: str,
    years: int,
) -> int:
    """Download NAV history for a single ticker and upsert to nav_timeseries."""
    import asyncio
    from datetime import date, timedelta

    from sqlalchemy import text as sa_text

    def _download() -> list[tuple[str, float]]:
        import yfinance as yf

        end = date.today()
        start = end - timedelta(days=years * 365)
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
        )
        if df.empty:
            return []
        # Use Adj Close if available, else Close
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        return [
            (idx.strftime("%Y-%m-%d"), float(val))
            for idx, val in df[col].items()
            if val == val  # skip NaN
        ]

    rows = await asyncio.to_thread(_download)
    if not rows:
        return 0

    async with db_factory() as session:
        # Batch upsert — use raw SQL for nav_timeseries
        for nav_date, nav_value in rows:
            await session.execute(
                sa_text(
                    "INSERT INTO nav_timeseries (ticker, nav_date, nav_value, source) "
                    "VALUES (:ticker, :nav_date, :nav_value, 'esma_seed') "
                    "ON CONFLICT (ticker, nav_date) DO UPDATE "
                    "SET nav_value = EXCLUDED.nav_value"
                ),
                {"ticker": ticker, "nav_date": nav_date, "nav_value": nav_value},
            )
        await session.commit()

    return len(rows)


# ── Phase 4: SEC Cross-Reference ────────────────────────────────────


async def phase4_sec_crossref(
    *,
    min_score: float = 0.85,
    dry_run: bool = False,
) -> dict[str, int]:
    """Cross-reference ESMA managers with SEC managers via fuzzy name match."""
    from sqlalchemy import text as sa_text

    stats = {"total": 0, "matched": 0, "unmatched": 0, "errors": 0}

    db_factory = _get_db_session_factory()

    # Fetch ESMA managers without SEC cross-reference
    async with db_factory() as session:
        esma_result = await session.execute(
            sa_text(
                "SELECT esma_id, company_name, lei FROM esma_managers "
                "WHERE sec_crd_number IS NULL "
                "ORDER BY esma_id"
            )
        )
        esma_managers = [
            {"esma_id": row[0], "company_name": row[1], "lei": row[2]}
            for row in esma_result.fetchall()
        ]

        # Fetch SEC managers for matching
        sec_result = await session.execute(
            sa_text("SELECT crd_number, firm_name FROM sec_managers")
        )
        sec_managers = [
            {"crd_number": row[0], "firm_name": row[1]}
            for row in sec_result.fetchall()
        ]

    stats["total"] = len(esma_managers)

    if dry_run:
        logger.info(
            "phase4.dry_run",
            esma_managers=len(esma_managers),
            sec_managers=len(sec_managers),
        )
        return stats

    if not sec_managers:
        logger.info("phase4.no_sec_managers", message="SEC managers table empty")
        return stats

    logger.info(
        "phase4.starting",
        esma_managers=len(esma_managers),
        sec_managers=len(sec_managers),
    )

    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.error("phase4.rapidfuzz_not_installed")
        stats["errors"] = len(esma_managers)
        return stats

    # Build SEC name index for matching
    sec_names = [(m["crd_number"], m["firm_name"]) for m in sec_managers]

    async with db_factory() as session:
        for esma_mgr in esma_managers:
            best_score = 0.0
            best_crd: str | None = None

            esma_name = esma_mgr["company_name"].upper()
            for crd, sec_name in sec_names:
                score = fuzz.token_sort_ratio(esma_name, sec_name.upper())
                if score > best_score:
                    best_score = score
                    best_crd = crd

            if best_score >= min_score * 100 and best_crd:
                try:
                    await session.execute(
                        sa_text(
                            "UPDATE esma_managers SET sec_crd_number = :crd "
                            "WHERE esma_id = :esma_id"
                        ),
                        {"crd": best_crd, "esma_id": esma_mgr["esma_id"]},
                    )
                    stats["matched"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning(
                        "phase4.update_failed",
                        esma_id=esma_mgr["esma_id"],
                        error=str(exc),
                    )
            else:
                stats["unmatched"] += 1

        await session.commit()

    logger.info(
        "phase4.complete",
        matched=stats["matched"],
        unmatched=stats["unmatched"],
        errors=stats["errors"],
    )
    return stats


# ── CLI ─────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ESMA UCITS Seed Population (4 phases)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan without DB writes",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint",
    )
    parser.add_argument(
        "--only-register", action="store_true",
        help="Only run Phase 1 (ESMA Register ingest)",
    )
    parser.add_argument(
        "--only-resolve", action="store_true",
        help="Only run Phase 2 (ISIN ticker resolution)",
    )
    parser.add_argument(
        "--only-nav", action="store_true",
        help="Only run Phase 3 (NAV backfill)",
    )
    parser.add_argument(
        "--only-crossref", action="store_true",
        help="Only run Phase 4 (SEC cross-reference)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Limit Phase 1 to N pages (for testing)",
    )
    parser.add_argument(
        "--nav-years", type=int, default=3,
        help="Years of NAV history to backfill (default: 3)",
    )
    parser.add_argument(
        "--openfigi-key",
        help="OpenFIGI API key (free at openfigi.com/api). "
             "Without key: 25 req/min. With key: 250 req/min.",
        default=os.environ.get("OPENFIGI_API_KEY"),
    )
    parser.add_argument(
        "--min-match-score", type=float, default=0.85,
        help="Minimum fuzzy match score for SEC cross-reference (default: 0.85)",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    start = time.monotonic()

    print("\nESMA UCITS Seed Population — 4 phases")
    print(f"Dry run: {args.dry_run}")
    print(f"Resume: {args.resume}")
    if args.max_pages:
        print(f"Max pages: {args.max_pages}")
    print()

    # Clear checkpoint if not resuming
    if not args.resume and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("checkpoint_cleared")

    checkpoint = _load_checkpoint()

    if args.only_register:
        await phase1_register_ingest(max_pages=args.max_pages, dry_run=args.dry_run)
    elif args.only_resolve:
        await phase2_isin_resolution(api_key=args.openfigi_key, dry_run=args.dry_run)
    elif args.only_nav:
        await phase3_nav_backfill(years=args.nav_years, dry_run=args.dry_run)
    elif args.only_crossref:
        await phase4_sec_crossref(
            min_score=args.min_match_score, dry_run=args.dry_run,
        )
    else:
        # Full pipeline: all 4 phases in order
        if not checkpoint.get("phase1_complete"):
            result = await phase1_register_ingest(
                max_pages=args.max_pages, dry_run=args.dry_run,
            )
            if not args.dry_run:
                checkpoint["phase1_complete"] = True
                _save_checkpoint(checkpoint)

        await phase2_isin_resolution(
            api_key=args.openfigi_key, dry_run=args.dry_run,
        )
        await phase3_nav_backfill(
            years=args.nav_years, dry_run=args.dry_run,
        )

        if not checkpoint.get("phase4_complete"):
            result = await phase4_sec_crossref(
                min_score=args.min_match_score, dry_run=args.dry_run,
            )
            if not args.dry_run:
                checkpoint["phase4_complete"] = True
                _save_checkpoint(checkpoint)

    elapsed = time.monotonic() - start
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    if CHECKPOINT_FILE.exists():
        cp = _load_checkpoint()
        resolved_count = len(cp.get("phase2_resolved", []))
        backfilled_count = len(cp.get("phase3_backfilled", []))
        print(f"Checkpoint: phase1={'done' if cp.get('phase1_complete') else 'pending'}, "
              f"resolved={resolved_count}, backfilled={backfilled_count}, "
              f"phase4={'done' if cp.get('phase4_complete') else 'pending'}")


if __name__ == "__main__":
    asyncio.run(_main())
