"""ESMA UCITS Seed Population Script.

5-phase resumable pipeline to populate esma_* tables with European
UCITS fund data. Run from backend/:

    python -m data_providers.esma.seed.populate_seed [--resume] [--dry-run]
    python -m data_providers.esma.seed.populate_seed --only-register
    python -m data_providers.esma.seed.populate_seed --only-firds
    python -m data_providers.esma.seed.populate_seed --only-resolve
    python -m data_providers.esma.seed.populate_seed --only-nav
    python -m data_providers.esma.seed.populate_seed --only-crossref

Phases (run in order):
    Phase 1:   ESMA Solr API → esma_managers + esma_funds (LEI as PK)
    Phase 1.5: FIRDS FULINS_C → esma_isin_ticker_map (real ISINs linked to LEIs)
    Phase 2:   ISIN resolution via OpenFIGI → esma_isin_ticker_map (yahoo tickers)
    Phase 3:   NAV backfill via Tiingo → nav_timeseries
    Phase 4:   SEC cross-reference via fuzzy match → esma_managers.sec_crd_number
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv

load_dotenv()  # Load .env before any os.environ.get() calls

logger = structlog.get_logger()

# ── Checkpoint ──────────────────────────────────────────────────────

CHECKPOINT_FILE = Path(".esma_seed_checkpoint.json")


def _load_checkpoint() -> dict[str, Any]:
    """Load checkpoint from disk. Returns fresh state if missing."""
    if CHECKPOINT_FILE.exists():
        try:
            raw = json.loads(CHECKPOINT_FILE.read_text())
            raw.setdefault("phase1_complete", False)
            raw.setdefault("phase1_5_complete", False)
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
        "phase1_5_complete": False,
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
    from data_providers.esma.register_service import RegisterService

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
                    "data_fetched_at": datetime.now(UTC),
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
                "data_fetched_at": datetime.now(UTC),
            })

            # Flush in batches
            if len(funds_batch) >= batch_size:
                deduped = _dedupe_by_isin(funds_batch)
                await _flush_phase1_batch(db_factory, managers, deduped, stats)
                funds_batch.clear()

    # Flush remaining
    if funds_batch:
        deduped = _dedupe_by_isin(funds_batch)
        await _flush_phase1_batch(db_factory, managers, deduped, stats)

    logger.info(
        "phase1.complete",
        managers=stats["managers"],
        funds=stats["funds"],
        errors=stats["errors"],
    )
    return stats


def _dedupe_by_isin(funds_batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate funds by ISIN, keeping last occurrence.

    Multiple ESMA Solr documents can share the same funds_lei (LEI ≠ ISIN).
    PostgreSQL ON CONFLICT DO UPDATE cannot affect the same row twice in one statement.
    """
    seen: dict[str, dict[str, Any]] = {}
    for f in funds_batch:
        seen[f["isin"]] = f
    return list(seen.values())


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
                mgr_stmt = pg_insert(EsmaManager).values(mgr_rows)
                mgr_stmt = mgr_stmt.on_conflict_do_update(
                    index_elements=["esma_id"],
                    set_={
                        "company_name": mgr_stmt.excluded.company_name,
                        "fund_count": mgr_stmt.excluded.fund_count,
                        "data_fetched_at": mgr_stmt.excluded.data_fetched_at,
                    },
                )
                await session.execute(mgr_stmt)
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


# ── Phase 1.5: FIRDS FULINS_C → real ISINs ────────────────────────


async def phase1_5_firds_isin_mapping(
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Download FIRDS FULINS_C and map real ISINs to fund LEIs.

    ESMA Register Solr returns LEIs (not ISINs). FIRDS contains the
    ISIN ↔ LEI mapping for all EU collective investment instruments.
    This phase populates esma_isin_ticker_map with real ISINs linked
    to fund LEIs, enabling Phase 2 (OpenFIGI) to resolve actual ISINs.
    """
    from sqlalchemy import text as sa_text

    from data_providers.esma.firds_service import FirdsService

    stats = {"total_instruments": 0, "matched": 0, "unmatched": 0, "errors": 0}

    db_factory = _get_db_session_factory()

    # Fetch all fund LEIs from esma_funds
    async with db_factory() as session:
        result = await session.execute(
            sa_text("SELECT lei FROM esma_funds ORDER BY lei"),
        )
        fund_leis = {row[0] for row in result.fetchall()}

    logger.info("phase1_5.fund_leis_loaded", count=len(fund_leis))

    if dry_run:
        logger.info("phase1_5.dry_run", fund_leis=len(fund_leis))
        return stats

    # Download and parse FIRDS FULINS_C
    async with FirdsService() as svc:
        url = await svc.find_latest_fulins_c_url()
        zip_data = await svc.download_zip(url)

        # Parse XML, filtering to only LEIs we know about
        isin_rows: list[dict[str, Any]] = []
        seen_isins: set[str] = set()

        for instrument in svc.parse_xml(zip_data, lei_filter=fund_leis):
            stats["total_instruments"] += 1

            if instrument.isin in seen_isins:
                continue
            seen_isins.add(instrument.isin)

            isin_rows.append({
                "isin": instrument.isin,
                "fund_lei": instrument.lei,
                "resolved_via": "firds",
                "is_tradeable": False,  # will be updated by Phase 2
                "last_verified_at": datetime.now(UTC),
            })

            # Flush in batches of 2000
            if len(isin_rows) >= 2000:
                matched = await _flush_firds_batch(db_factory, isin_rows, stats)
                isin_rows.clear()

        # Flush remaining
        if isin_rows:
            await _flush_firds_batch(db_factory, isin_rows, stats)

    stats["matched"] = len(seen_isins)

    logger.info(
        "phase1_5.complete",
        total_instruments=stats["total_instruments"],
        unique_isins=len(seen_isins),
        fund_leis=len(fund_leis),
        errors=stats["errors"],
    )
    return stats


async def _flush_firds_batch(
    db_factory: Any,
    rows: list[dict[str, Any]],
    stats: dict[str, int],
) -> int:
    """Upsert a batch of FIRDS ISIN→LEI mappings to esma_isin_ticker_map."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.shared.models import EsmaIsinTickerMap

    async with db_factory() as session:
        try:
            stmt = pg_insert(EsmaIsinTickerMap).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["isin"],
                set_={
                    "fund_lei": stmt.excluded.fund_lei,
                    "resolved_via": stmt.excluded.resolved_via,
                    "last_verified_at": stmt.excluded.last_verified_at,
                },
            )
            await session.execute(stmt)
            await session.commit()
            return len(rows)
        except Exception as exc:
            await session.rollback()
            stats["errors"] += 1
            logger.error("phase1_5.batch_upsert_failed", error=str(exc))
            return 0


# ── Phase 2: ISIN → Ticker Resolution ──────────────────────────────


async def phase2_isin_resolution(
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Resolve real ISINs from esma_isin_ticker_map to Yahoo Finance tickers via OpenFIGI.

    Phase 1.5 (FIRDS) must run first to populate esma_isin_ticker_map with
    real ISINs linked to fund LEIs. This phase resolves those ISINs to
    Yahoo Finance tickers.
    """
    from sqlalchemy import text as sa_text

    from data_providers.esma.ticker_resolver import TickerResolver

    stats = {"total": 0, "resolved": 0, "unresolved": 0, "errors": 0}

    checkpoint = _load_checkpoint()
    already_resolved = set(checkpoint.get("phase2_resolved", []))

    db_factory = _get_db_session_factory()

    # Fetch real ISINs from esma_isin_ticker_map that haven't been resolved yet
    async with db_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT isin FROM esma_isin_ticker_map "
                "WHERE yahoo_ticker IS NULL "
                "ORDER BY isin",
            ),
        )
        all_isins = [row[0] for row in result.fetchall()]

    # Filter out already-resolved from checkpoint
    pending_isins = [i for i in all_isins if i not in already_resolved]
    stats["total"] = len(pending_isins)

    if not pending_isins:
        logger.info(
            "phase2.no_pending_isins",
            message="No real ISINs to resolve. Run Phase 1.5 (FIRDS) first.",
        )
        return stats

    if dry_run:
        logger.info("phase2.dry_run", total_pending=len(pending_isins))
        return stats

    logger.info("phase2.starting", total_pending=len(pending_isins))

    async with TickerResolver(api_key=api_key) as resolver:
        batch_size = 50
        for i in range(0, len(pending_isins), batch_size):
            batch = pending_isins[i : i + batch_size]

            try:
                results = await resolver.resolve_batch(batch)
            except Exception as exc:
                stats["errors"] += 1
                logger.error("phase2.batch_failed", error=str(exc))
                continue

            async with db_factory() as session:
                try:
                    # Update esma_isin_ticker_map with resolved tickers
                    for r in results:
                        await session.execute(
                            sa_text(
                                "UPDATE esma_isin_ticker_map "
                                "SET yahoo_ticker = :ticker, "
                                "    exchange = :exchange, "
                                "    resolved_via = :resolved_via, "
                                "    is_tradeable = :is_tradeable, "
                                "    last_verified_at = :last_verified_at "
                                "WHERE isin = :isin",
                            ),
                            {
                                "ticker": r.yahoo_ticker,
                                "exchange": r.exchange,
                                "resolved_via": r.resolved_via,
                                "is_tradeable": r.is_tradeable,
                                "last_verified_at": datetime.now(UTC),
                                "isin": r.isin,
                            },
                        )
                        if r.yahoo_ticker:
                            stats["resolved"] += 1
                        else:
                            stats["unresolved"] += 1

                    # Propagate resolved tickers back to esma_funds via LEI join
                    await session.execute(
                        sa_text(
                            "UPDATE esma_funds f "
                            "SET yahoo_ticker = m.yahoo_ticker, "
                            "    ticker_resolved_at = m.last_verified_at "
                            "FROM esma_isin_ticker_map m "
                            "WHERE f.isin = m.fund_lei "
                            "  AND m.yahoo_ticker IS NOT NULL "
                            "  AND m.isin = ANY(:isins)",
                        ),
                        {"isins": [r.isin for r in results]},
                    )

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
                "ORDER BY isin",
            ),
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

    from sqlalchemy import text as sa_text

    def _download() -> list[tuple[str, float]]:
        from app.services.providers.tiingo_instrument_provider import (
            TiingoInstrumentProvider,
        )

        provider = TiingoInstrumentProvider()
        period = f"{years}y" if years <= 10 else "10y"
        history = provider.fetch_batch_history([ticker], period=period)
        df = history.get(ticker)
        if df is None or df.empty:
            return []
        col = "close" if "close" in df.columns else "Close"
        if col not in df.columns:
            return []
        series = df[col].dropna()
        return [
            (idx.date() if hasattr(idx, "date") else idx, float(val))
            for idx, val in series.items()
            if val == val  # skip NaN
        ]

    rows = await asyncio.to_thread(_download)
    if not rows:
        return 0

    async with db_factory() as session:
        # Batch upsert to esma_nav_history (global, no org_id)
        for nav_date, nav_value in rows:
            await session.execute(
                sa_text(
                    "INSERT INTO esma_nav_history (isin, yahoo_ticker, nav_date, nav_value) "
                    "VALUES (:isin, :ticker, :nav_date, :nav_value) "
                    "ON CONFLICT (isin, nav_date) DO UPDATE "
                    "SET nav_value = EXCLUDED.nav_value",
                ),
                {"isin": isin, "ticker": ticker, "nav_date": nav_date, "nav_value": nav_value},
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
                "ORDER BY esma_id",
            ),
        )
        esma_managers = [
            {"esma_id": row[0], "company_name": row[1], "lei": row[2]}
            for row in esma_result.fetchall()
        ]

        # Fetch SEC managers for matching
        sec_result = await session.execute(
            sa_text("SELECT crd_number, firm_name FROM sec_managers"),
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
                            "WHERE esma_id = :esma_id",
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
        "--only-firds", action="store_true",
        help="Only run Phase 1.5 (FIRDS ISIN mapping)",
    )
    parser.add_argument(
        "--only-resolve", action="store_true",
        help="Only run Phase 2 (ISIN ticker resolution via OpenFIGI)",
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
             "Without key: 25 req/min × 10 jobs = 250 jobs/min. "
             "With key: 250 req/min × 100 jobs = 25,000 jobs/min (100× faster).",
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
    elif args.only_firds:
        await phase1_5_firds_isin_mapping(dry_run=args.dry_run)
    elif args.only_resolve:
        await phase2_isin_resolution(api_key=args.openfigi_key, dry_run=args.dry_run)
    elif args.only_nav:
        await phase3_nav_backfill(years=args.nav_years, dry_run=args.dry_run)
    elif args.only_crossref:
        await phase4_sec_crossref(
            min_score=args.min_match_score, dry_run=args.dry_run,
        )
    else:
        # Full pipeline: all 5 phases in order
        if not checkpoint.get("phase1_complete"):
            await phase1_register_ingest(
                max_pages=args.max_pages, dry_run=args.dry_run,
            )
            if not args.dry_run:
                checkpoint["phase1_complete"] = True
                _save_checkpoint(checkpoint)

        if not checkpoint.get("phase1_5_complete"):
            await phase1_5_firds_isin_mapping(dry_run=args.dry_run)
            if not args.dry_run:
                checkpoint["phase1_5_complete"] = True
                _save_checkpoint(checkpoint)

        await phase2_isin_resolution(
            api_key=args.openfigi_key, dry_run=args.dry_run,
        )
        await phase3_nav_backfill(
            years=args.nav_years, dry_run=args.dry_run,
        )

        if not checkpoint.get("phase4_complete"):
            await phase4_sec_crossref(
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
