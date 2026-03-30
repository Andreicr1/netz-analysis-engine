"""Seed sec_mmf_metrics from N-MFP daily datasets.

Joins SEVENDAYNETYIELD + DLYSHAREHOLDERFLOWREPORT + LIQUIDASSETSDETAILS
via SUBMISSION to resolve series_id. Parallel parsing (4 cores) + async batch upsert.

Usage:
    python -m scripts.seed_mmf_metrics --nmfp-dir "C:/Users/Andrei/Desktop/EDGAR FILES/20260209-20260306_nmfp"
    python -m scripts.seed_mmf_metrics --nmfp-dir ... --dsn "postgresql://..."
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import structlog

logger = structlog.get_logger()

BATCH_SIZE = 500
POOL_SIZE = 12


# ── TSV Parsing (multiprocessing) ────────────────────────────────────

def _parse_tsv(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append({k.strip(): v.strip() if v else None for k, v in row.items()})
    return rows


def _parse_all(nmfp_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    paths = [
        nmfp_dir / "NMFP_SUBMISSION.tsv",
        nmfp_dir / "NMFP_SEVENDAYNETYIELD.tsv",
        nmfp_dir / "NMFP_DLYSHAREHOLDERFLOWREPORT.tsv",
        nmfp_dir / "NMFP_LIQUIDASSETSDETAILS.tsv",
    ]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Missing: {p}")

    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_parse_tsv, p) for p in paths]
        submission, yields, flows, liquidity = [f.result() for f in futures]
    return submission, yields, flows, liquidity


def _parse_date(val: str | None) -> str | None:
    """Parse DD-MON-YYYY (e.g. 25-FEB-2026) to YYYY-MM-DD."""
    if not val:
        return None
    try:
        return datetime.datetime.strptime(val, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _safe_decimal(val: str | None) -> str | None:
    if val is None or val == "":
        return None
    try:
        float(val)
        return val
    except (ValueError, TypeError):
        return None


def _build_metrics(
    submission: list[dict],
    yields: list[dict],
    flows: list[dict],
    liquidity: list[dict],
) -> list[tuple]:
    """Build (metric_date, series_id, class_id, accession_number, ...) tuples."""
    t0 = time.time()

    # Map ACCESSION_NUMBER → SERIESID from submission
    acc_to_series = {
        r["ACCESSION_NUMBER"]: r["SERIESID"]
        for r in submission
        if r.get("ACCESSION_NUMBER") and r.get("SERIESID")
    }

    # Also collect valid series_ids that exist in the catalog (will be filtered at DB level via FK)

    # Yield data: keyed by (date, class_id) → yield value
    # Each row has ACCESSION_NUMBER, CLASSESID, SEVENDAYNETYIELDVALUE, SEVENDAYNETYIELDDATE
    yield_data: dict[tuple[str, str, str], dict] = {}
    for r in yields:
        acc = r.get("ACCESSION_NUMBER")
        series_id = acc_to_series.get(acc)
        if not series_id:
            continue
        date_str = _parse_date(r.get("SEVENDAYNETYIELDDATE"))
        class_id = r.get("CLASSESID")
        if not date_str or not class_id:
            continue
        key = (date_str, series_id, class_id)
        yield_data[key] = {
            "accession_number": acc,
            "seven_day_net_yield": _safe_decimal(r.get("SEVENDAYNETYIELDVALUE")),
        }

    # Flow data: keyed by (date, class_id)
    flow_data: dict[tuple[str, str, str], dict] = {}
    for r in flows:
        acc = r.get("ACCESSION_NUMBER")
        series_id = acc_to_series.get(acc)
        if not series_id:
            continue
        date_str = _parse_date(r.get("DAILYSHAREHOLDERFLOWDATE"))
        class_id = r.get("CLASSESID")
        if not date_str or not class_id:
            continue
        key = (date_str, series_id, class_id)
        flow_data[key] = {
            "accession_number": acc,
            "daily_gross_subscriptions": _safe_decimal(r.get("DAILYGROSSSUBSCRIPTIONS")),
            "daily_gross_redemptions": _safe_decimal(r.get("DAILYGROSSREDEMPTIONS")),
        }

    # Liquidity data: keyed by (date, series_id) — series-level, not class-level
    liq_data: dict[tuple[str, str], dict] = {}
    for r in liquidity:
        acc = r.get("ACCESSION_NUMBER")
        series_id = acc_to_series.get(acc)
        if not series_id:
            continue
        date_str = _parse_date(r.get("TOTLIQUIDASSETSNEARPCTDATE"))
        if not date_str:
            continue
        key = (date_str, series_id)
        liq_data[key] = {
            "accession_number": acc,
            "pct_daily_liquid": _safe_decimal(r.get("PCTDAILYLIQUIDASSETS")),
            "pct_weekly_liquid": _safe_decimal(r.get("PCTWEEKLYLIQUIDASSETS")),
            "total_daily_liquid_assets": _safe_decimal(r.get("TOTVALUEDAILYLIQUIDASSETS")),
            "total_weekly_liquid_assets": _safe_decimal(r.get("TOTVALUEWEEKLYLIQUIDASSETS")),
        }

    # Merge all keys
    all_keys: set[tuple[str, str, str]] = set()
    all_keys.update(yield_data.keys())
    all_keys.update(flow_data.keys())
    # Expand liquidity (series-level) to class-level keys
    for (date, sid, cid) in list(all_keys):
        pass  # already covered
    # Add flow keys that have liquidity data available
    for (date, sid) in liq_data:
        # Find all class_ids for this series+date
        for k in list(all_keys):
            if k[0] == date and k[1] == sid:
                break
        else:
            # If no class-level data, we can't insert (need class_id for PK)
            pass

    rows = []
    for key in sorted(all_keys):
        date_str, series_id, class_id = key
        y = yield_data.get(key, {})
        f = flow_data.get(key, {})
        l = liq_data.get((date_str, series_id), {})

        acc = y.get("accession_number") or f.get("accession_number") or l.get("accession_number")
        if not acc:
            continue

        rows.append((
            date_str,                               # metric_date
            series_id,                              # series_id
            class_id,                               # class_id
            acc,                                    # accession_number
            y.get("seven_day_net_yield"),            # seven_day_net_yield
            f.get("daily_gross_subscriptions"),      # daily_gross_subscriptions
            f.get("daily_gross_redemptions"),        # daily_gross_redemptions
            l.get("pct_daily_liquid"),               # pct_daily_liquid
            l.get("pct_weekly_liquid"),              # pct_weekly_liquid
            l.get("total_daily_liquid_assets"),      # total_daily_liquid_assets
            l.get("total_weekly_liquid_assets"),     # total_weekly_liquid_assets
        ))

    logger.info("metrics_rows_built", count=len(rows), elapsed=f"{time.time()-t0:.2f}s")
    return rows


# ── DB Upsert ────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO sec_mmf_metrics (
    metric_date, series_id, class_id, accession_number,
    seven_day_net_yield,
    daily_gross_subscriptions, daily_gross_redemptions,
    pct_daily_liquid, pct_weekly_liquid,
    total_daily_liquid_assets, total_weekly_liquid_assets
) VALUES (
    $1::date, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
) ON CONFLICT (metric_date, series_id, class_id) DO UPDATE SET
    accession_number = EXCLUDED.accession_number,
    seven_day_net_yield = COALESCE(EXCLUDED.seven_day_net_yield, sec_mmf_metrics.seven_day_net_yield),
    daily_gross_subscriptions = COALESCE(EXCLUDED.daily_gross_subscriptions, sec_mmf_metrics.daily_gross_subscriptions),
    daily_gross_redemptions = COALESCE(EXCLUDED.daily_gross_redemptions, sec_mmf_metrics.daily_gross_redemptions),
    pct_daily_liquid = COALESCE(EXCLUDED.pct_daily_liquid, sec_mmf_metrics.pct_daily_liquid),
    pct_weekly_liquid = COALESCE(EXCLUDED.pct_weekly_liquid, sec_mmf_metrics.pct_weekly_liquid),
    total_daily_liquid_assets = COALESCE(EXCLUDED.total_daily_liquid_assets, sec_mmf_metrics.total_daily_liquid_assets),
    total_weekly_liquid_assets = COALESCE(EXCLUDED.total_weekly_liquid_assets, sec_mmf_metrics.total_weekly_liquid_assets)
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
    logger.info("mmf_metrics_upsert_complete", rows=total, elapsed=f"{time.time()-t0:.2f}s")


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sec_mmf_metrics from N-MFP daily data")
    parser.add_argument("--nmfp-dir", type=str, required=True, help="Path to N-MFP directory")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    args = parser.parse_args()

    nmfp_dir = Path(args.nmfp_dir)
    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    t0 = time.time()
    submission, yields, flows, liquidity = _parse_all(nmfp_dir)
    logger.info("tsv_parsed", submission=len(submission), yields=len(yields),
                flows=len(flows), liquidity=len(liquidity))

    rows = _build_metrics(submission, yields, flows, liquidity)
    asyncio.run(_upsert_all(dsn, rows))
    logger.info("seed_mmf_metrics_done", total_elapsed=f"{time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
