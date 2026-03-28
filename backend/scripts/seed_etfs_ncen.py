"""Seed sec_etfs from N-CEN quarterly datasets (ETF.tsv + FUND_REPORTED_INFO.tsv + SHARES_OUTSTANDING.tsv).

Parses TSVs with multiprocessing, upserts via asyncpg with parallel batches.

Usage:
    python -m scripts.seed_etfs_ncen --ncen-dir "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_ncen (1)"
    python -m scripts.seed_etfs_ncen --ncen-dir ... --dsn "postgresql://..."
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import structlog

logger = structlog.get_logger()

BATCH_SIZE = 100
POOL_SIZE = 12


# ── TSV Parsing (CPU-bound, multiprocessing) ────────────────────────

def _parse_tsv(path: Path) -> list[dict]:
    """Parse a TSV file into list of dicts. Runs in subprocess."""
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            # Strip whitespace from all values
            rows.append({k.strip(): v.strip() if v else None for k, v in row.items()})
    return rows


def _parse_all(ncen_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse all 3 TSVs in parallel using 3 cores."""
    paths = [
        ncen_dir / "FUND_REPORTED_INFO.tsv",
        ncen_dir / "ETF.tsv",
        ncen_dir / "SHARES_OUTSTANDING.tsv",
    ]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Missing: {p}")

    with ProcessPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_parse_tsv, p) for p in paths]
        fund_info, etf_data, shares = [f.result() for f in futures]

    return fund_info, etf_data, shares


def _safe_decimal(val: str | None) -> str | None:
    if val is None or val == "":
        return None
    try:
        float(val)
        return val
    except (ValueError, TypeError):
        return None


def _safe_int(val: str | None) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _yn_bool(val: str | None) -> bool | None:
    if val is None or val == "":
        return None
    return val.upper() == "Y"


def _build_etf_rows(
    fund_info: list[dict], etf_data: list[dict], shares: list[dict],
) -> list[tuple]:
    """Join 3 datasets and build upsert tuples."""
    t0 = time.time()

    # Filter ETFs from FUND_REPORTED_INFO
    etf_funds = {r["SERIES_ID"]: r for r in fund_info if r.get("IS_ETF") == "Y" and r.get("SERIES_ID")}

    # Index ETF.tsv by SERIES_ID
    etf_by_series = {r["SERIES_ID"]: r for r in etf_data if r.get("SERIES_ID")}

    # First ticker per SERIES_ID from SHARES_OUTSTANDING
    ticker_by_series: dict[str, str] = {}
    for r in shares:
        ticker = r.get("TICKER")
        # Extract SERIES_ID from FUND_ID (format: accession_cik_seriesid)
        fund_id = r.get("FUND_ID", "")
        parts = fund_id.rsplit("_", 1)
        sid = parts[-1] if len(parts) > 1 and parts[-1].startswith("S") else None
        if sid and ticker and sid not in ticker_by_series:
            ticker_by_series[sid] = ticker

    rows = []
    for sid, fi in etf_funds.items():
        etf = etf_by_series.get(sid, {})
        # Extract CIK from FUND_ID field (format: accession_CIK_seriesid)
        fund_id_raw = fi.get("FUND_ID", "")
        parts = fund_id_raw.split("_")
        cik = parts[1] if len(parts) >= 3 else None
        if not cik:
            continue

        rows.append((
            sid,                                                    # series_id
            cik,                                                    # cik
            fund_id_raw,                                            # fund_id
            fi.get("FUND_NAME") or "Unknown",                      # fund_name
            fi.get("LEI"),                                          # lei
            ticker_by_series.get(sid),                              # ticker
            None,                                                   # isin
            None,                                                   # strategy_label
            None,                                                   # asset_class
            None,                                                   # index_tracked
            _yn_bool(fi.get("IS_INDEX")),                           # is_index
            _yn_bool(etf.get("IS_FUND_IN_KIND_ETF")),              # is_in_kind_etf
            _safe_int(etf.get("NUM_SHARES_PER_CREATION_UNIT")),     # creation_unit_size
            _safe_decimal(etf.get("PURCHASED_AVG_PCT_NON_CASH")),   # pct_in_kind_creation
            _safe_decimal(etf.get("REDEEMED_AVG_PCT_NON_CASH")),    # pct_in_kind_redemption
            _safe_decimal(etf.get("ANNUAL_DIFF_B4_FEE_EXPENSE")),   # tracking_difference_gross
            _safe_decimal(etf.get("ANNUAL_DIFF_AFTER_FEE_EXPENSE")),# tracking_difference_net
            _safe_decimal(fi.get("MANAGEMENT_FEE")),                # management_fee
            _safe_decimal(fi.get("NET_OPERATING_EXPENSES")),        # net_operating_expenses
            _safe_decimal(fi.get("RETURN_B4_FEES_AND_EXPENSES")),   # return_before_fees
            _safe_decimal(fi.get("RETURN_AFTR_FEES_AND_EXPENSES")), # return_after_fees
            _safe_decimal(fi.get("MONTHLY_AVG_NET_ASSETS")),        # monthly_avg_net_assets
            _safe_decimal(fi.get("DAILY_AVG_NET_ASSETS")),          # daily_avg_net_assets
            _safe_decimal(fi.get("NAV_PER_SHARE")),                 # nav_per_share
            _safe_decimal(fi.get("MARKET_PRICE_PER_SHARE")),        # market_price_per_share
            _yn_bool(fi.get("IS_SEC_LENDING_AUTHORIZED")),          # is_sec_lending_authorized
            _yn_bool(fi.get("DID_LEND_SECURITIES")),                # did_lend_securities
            _yn_bool(fi.get("HAS_EXP_LIMIT")),                     # has_expense_limit
        ))

    logger.info("etf_rows_built", count=len(rows), elapsed=f"{time.time()-t0:.2f}s")
    return rows


# ── DB Upsert (async, parallel connections) ──────────────────────────

_UPSERT_SQL = """
INSERT INTO sec_etfs (
    series_id, cik, fund_id, fund_name, lei, ticker, isin,
    strategy_label, asset_class, index_tracked, is_index, is_in_kind_etf,
    creation_unit_size, pct_in_kind_creation, pct_in_kind_redemption,
    tracking_difference_gross, tracking_difference_net,
    management_fee, net_operating_expenses, return_before_fees, return_after_fees,
    monthly_avg_net_assets, daily_avg_net_assets, nav_per_share, market_price_per_share,
    is_sec_lending_authorized, did_lend_securities, has_expense_limit
) VALUES (
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28
) ON CONFLICT (series_id) DO UPDATE SET
    cik = EXCLUDED.cik,
    fund_id = EXCLUDED.fund_id,
    fund_name = EXCLUDED.fund_name,
    lei = EXCLUDED.lei,
    ticker = COALESCE(EXCLUDED.ticker, sec_etfs.ticker),
    management_fee = COALESCE(EXCLUDED.management_fee, sec_etfs.management_fee),
    net_operating_expenses = COALESCE(EXCLUDED.net_operating_expenses, sec_etfs.net_operating_expenses),
    return_before_fees = EXCLUDED.return_before_fees,
    return_after_fees = EXCLUDED.return_after_fees,
    monthly_avg_net_assets = EXCLUDED.monthly_avg_net_assets,
    daily_avg_net_assets = EXCLUDED.daily_avg_net_assets,
    nav_per_share = EXCLUDED.nav_per_share,
    market_price_per_share = EXCLUDED.market_price_per_share,
    is_index = EXCLUDED.is_index,
    is_in_kind_etf = EXCLUDED.is_in_kind_etf,
    creation_unit_size = EXCLUDED.creation_unit_size,
    pct_in_kind_creation = EXCLUDED.pct_in_kind_creation,
    pct_in_kind_redemption = EXCLUDED.pct_in_kind_redemption,
    tracking_difference_gross = EXCLUDED.tracking_difference_gross,
    tracking_difference_net = EXCLUDED.tracking_difference_net,
    is_sec_lending_authorized = EXCLUDED.is_sec_lending_authorized,
    did_lend_securities = EXCLUDED.did_lend_securities,
    has_expense_limit = EXCLUDED.has_expense_limit,
    updated_at = NOW()
"""


async def _upsert_batch(pool, batch: list[tuple]) -> int:
    async with pool.acquire() as conn:
        await conn.executemany(_UPSERT_SQL, batch)
    return len(batch)


async def _upsert_all(dsn: str, rows: list[tuple]) -> None:
    import asyncpg

    t0 = time.time()
    pool = await asyncpg.create_pool(dsn, min_size=POOL_SIZE, max_size=POOL_SIZE, ssl="require")

    batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    results = await asyncio.gather(*[_upsert_batch(pool, b) for b in batches])
    total = sum(results)

    await pool.close()
    logger.info("etf_upsert_complete", rows=total, elapsed=f"{time.time()-t0:.2f}s")


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sec_etfs from N-CEN datasets")
    parser.add_argument("--ncen-dir", type=str, required=True, help="Path to N-CEN directory")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    args = parser.parse_args()

    ncen_dir = Path(args.ncen_dir)
    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    t0 = time.time()
    fund_info, etf_data, shares = _parse_all(ncen_dir)
    logger.info("tsv_parsed", fund_info=len(fund_info), etf=len(etf_data), shares=len(shares))

    rows = _build_etf_rows(fund_info, etf_data, shares)
    asyncio.run(_upsert_all(dsn, rows))
    logger.info("seed_etfs_done", total_elapsed=f"{time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
