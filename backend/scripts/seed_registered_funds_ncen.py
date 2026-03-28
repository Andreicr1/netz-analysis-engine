"""Enrich sec_registered_funds with N-CEN operational data.

Scans multiple N-CEN quarterly directories (newest first), keeping the most
recent filing per registrant CIK. Filters non-ETF/non-MMF rows and updates
existing sec_registered_funds with fees, performance, AUM, NAV, classification
flags, and operational metadata.

Supports two modes:
  --ncen-dir <single_quarter>    Single quarter directory (has FUND_REPORTED_INFO.tsv)
  --ncen-dir <parent_directory>  Parent with multiple *_ncen* subdirectories

Usage:
    python -m scripts.seed_registered_funds_ncen \
        --ncen-dir "C:/Users/Andrei/Desktop/EDGAR FILES/ncen"
    python -m scripts.seed_registered_funds_ncen \
        --ncen-dir "C:/Users/Andrei/Desktop/EDGAR FILES/ncen" \
        --extra-dir "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_ncen (1)"
    python -m scripts.seed_registered_funds_ncen --ncen-dir ... --dsn "postgresql://..."
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import structlog

logger = structlog.get_logger()

POOL_SIZE = 12


# ── TSV Parsing ──────────────────────────────────────────────────────

def _parse_single_dir(ncen_dir: Path) -> list[dict]:
    """Parse FUND_REPORTED_INFO.tsv from a single quarter directory."""
    path = ncen_dir / "FUND_REPORTED_INFO.tsv"
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            row = {k.strip(): (v.strip() if v else None) for k, v in r.items()}
            if row.get("IS_ETF") == "Y" or row.get("IS_MONEY_MARKET") == "Y":
                continue
            rows.append(row)
    return rows


def _discover_dirs(ncen_dir: Path, extra_dirs: list[Path] | None = None) -> list[Path]:
    """Discover N-CEN directories, ordered newest-first."""
    dirs: list[Path] = []

    # If the dir itself has FUND_REPORTED_INFO.tsv, it's a single quarter
    if (ncen_dir / "FUND_REPORTED_INFO.tsv").exists():
        dirs.append(ncen_dir)
    else:
        # Parent directory with subdirectories
        dirs.extend(sorted(ncen_dir.glob("*ncen*"), reverse=True))

    # Extra dirs (e.g. Q4 2025 in a different location)
    if extra_dirs:
        for d in extra_dirs:
            if d.exists() and d not in dirs:
                dirs.insert(0, d)  # Most recent first

    return dirs


def _parse_all_quarters(dirs: list[Path]) -> dict[str, dict]:
    """Parse all quarters in parallel, keep latest row per CIK (stripped)."""
    t0 = time.time()

    # Parse all directories in parallel using threads (I/O bound, NVMe)
    with ThreadPoolExecutor(max_workers=min(len(dirs), 16)) as pool:
        futures = {pool.submit(_parse_single_dir, d): d for d in dirs}
        results = [(dirs.index(futures[f]), futures[f].name, f.result()) for f in futures]

    # Sort by directory order (newest first) to ensure latest-wins
    results.sort(key=lambda x: x[0])

    latest_by_cik: dict[str, dict] = {}
    total_parsed = 0
    for _, dirname, rows in results:
        total_parsed += len(rows)
        for r in rows:
            fid = r.get("FUND_ID", "")
            parts = fid.split("_")
            cik = parts[1].lstrip("0") if len(parts) >= 3 else None
            if cik and cik not in latest_by_cik:
                latest_by_cik[cik] = r

    logger.info("all_quarters_parsed",
                quarters=len(dirs), total_rows=total_parsed,
                unique_ciks=len(latest_by_cik),
                elapsed=f"{time.time()-t0:.2f}s")
    return latest_by_cik


def _safe_decimal(val: str | None) -> str | None:
    if val is None or val == "":
        return None
    try:
        float(val)
        return val
    except (ValueError, TypeError):
        return None


def _yn_bool(val: str | None) -> bool | None:
    if val is None or val == "":
        return None
    return val.upper() == "Y"


# ── DB Update ────────────────────────────────────────────────────────

_UPDATE_SQL = """
UPDATE sec_registered_funds SET
    is_index = COALESCE($3, is_index),
    is_non_diversified = COALESCE($4, is_non_diversified),
    is_target_date = COALESCE($5, is_target_date),
    is_fund_of_fund = COALESCE($6, is_fund_of_fund),
    is_master_feeder = COALESCE($7, is_master_feeder),
    lei = COALESCE($8, lei),
    management_fee = COALESCE($9, management_fee),
    net_operating_expenses = COALESCE($10, net_operating_expenses),
    has_expense_limit = COALESCE($11, has_expense_limit),
    has_expense_waived = COALESCE($12, has_expense_waived),
    return_before_fees = COALESCE($13, return_before_fees),
    return_after_fees = COALESCE($14, return_after_fees),
    return_stdv_before_fees = COALESCE($15, return_stdv_before_fees),
    return_stdv_after_fees = COALESCE($16, return_stdv_after_fees),
    monthly_avg_net_assets = COALESCE($17, monthly_avg_net_assets),
    daily_avg_net_assets = COALESCE($18, daily_avg_net_assets),
    nav_per_share = COALESCE($19, nav_per_share),
    market_price_per_share = COALESCE($20, market_price_per_share),
    is_sec_lending_authorized = COALESCE($21, is_sec_lending_authorized),
    did_lend_securities = COALESCE($22, did_lend_securities),
    has_line_of_credit = COALESCE($23, has_line_of_credit),
    has_interfund_borrowing = COALESCE($24, has_interfund_borrowing),
    has_swing_pricing = COALESCE($25, has_swing_pricing),
    did_pay_broker_research = COALESCE($26, did_pay_broker_research),
    ncen_accession_number = COALESCE($27, ncen_accession_number),
    ncen_fund_id = COALESCE($28, ncen_fund_id)
WHERE series_id = $1 OR ltrim(cik, '0') = $2
"""


async def _update_all(dsn: str, latest_by_cik: dict[str, dict], dry_run: bool = False) -> None:
    import asyncpg

    # Build tuples
    rows = []
    for cik, r in latest_by_cik.items():
        series_id = r.get("SERIES_ID")
        fund_id_raw = r.get("FUND_ID", "")
        parts = fund_id_raw.split("_")
        accession = parts[0] if parts else None

        rows.append((
            series_id, cik,
            _yn_bool(r.get("IS_INDEX")),
            _yn_bool(r.get("IS_NON_DIVERSIFIED")),
            _yn_bool(r.get("IS_TARGET_DATE")),
            _yn_bool(r.get("IS_FUND_OF_FUND")),
            _yn_bool(r.get("IS_MASTER_FEEDER")),
            r.get("LEI"),
            _safe_decimal(r.get("MANAGEMENT_FEE")),
            _safe_decimal(r.get("NET_OPERATING_EXPENSES")),
            _yn_bool(r.get("HAS_EXP_LIMIT")),
            _yn_bool(r.get("HAS_EXP_REDUCED_WAIVED")),
            _safe_decimal(r.get("RETURN_B4_FEES_AND_EXPENSES")),
            _safe_decimal(r.get("RETURN_AFTR_FEES_AND_EXPENSES")),
            _safe_decimal(r.get("STDV_B4_FEES_AND_EXPENSES")),
            _safe_decimal(r.get("STDV_AFTR_FEES_AND_EXPENSES")),
            _safe_decimal(r.get("MONTHLY_AVG_NET_ASSETS")),
            _safe_decimal(r.get("DAILY_AVG_NET_ASSETS")),
            _safe_decimal(r.get("NAV_PER_SHARE")),
            _safe_decimal(r.get("MARKET_PRICE_PER_SHARE")),
            _yn_bool(r.get("IS_SEC_LENDING_AUTHORIZED")),
            _yn_bool(r.get("DID_LEND_SECURITIES")),
            _yn_bool(r.get("HAS_LINE_OF_CREDIT")),
            _yn_bool(r.get("HAS_INTERFUND_BORROWING")),
            _yn_bool(r.get("HAS_SWING_PRICING")),
            _yn_bool(r.get("DID_PAY_BROKER_RESEARCH")),
            accession,
            fund_id_raw or None,
        ))

    logger.info("update_rows_built", count=len(rows))

    if dry_run:
        logger.info("dry_run_skip_db", rows=len(rows))
        return

    t0 = time.time()
    conn = await asyncpg.connect(dsn, ssl="require")

    # Sequential execution to avoid deadlocks on same table
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        await conn.executemany(_UPDATE_SQL, batch)
        logger.info("batch_done", batch=i // batch_size, rows=len(batch),
                     elapsed=f"{time.time()-t0:.1f}s")

    # Validation
    stats = await conn.fetch("""
        SELECT fund_type, count(*) total,
               count(management_fee) has_fee,
               count(return_after_fees) has_return,
               count(monthly_avg_net_assets) has_aum,
               count(ncen_accession_number) has_ncen,
               count(lei) has_lei,
               round(count(ncen_accession_number)::numeric / count(*) * 100, 1) pct
        FROM sec_registered_funds GROUP BY fund_type ORDER BY fund_type
    """)
    for r in stats:
        logger.info("enrichment_coverage", **dict(r))

    await conn.close()
    logger.info("update_complete", rows=len(rows), elapsed=f"{time.time()-t0:.2f}s")


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich sec_registered_funds from N-CEN")
    parser.add_argument("--ncen-dir", type=str, required=True,
                        help="Single quarter dir or parent with *_ncen* subdirs")
    parser.add_argument("--extra-dir", type=str, action="append", default=[],
                        help="Additional N-CEN quarter directories (repeatable)")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    args = parser.parse_args()

    ncen_dir = Path(args.ncen_dir)
    extra_dirs = [Path(d) for d in args.extra_dir] if args.extra_dir else None
    dsn = _resolve_dsn(args.dsn)
    if not dsn and not args.dry_run:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    t0 = time.time()
    dirs = _discover_dirs(ncen_dir, extra_dirs)
    logger.info("discovered_dirs", count=len(dirs), dirs=[d.name for d in dirs])

    latest_by_cik = _parse_all_quarters(dirs)
    asyncio.run(_update_all(dsn, latest_by_cik, dry_run=args.dry_run))
    logger.info("seed_registered_funds_ncen_done", total_elapsed=f"{time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
