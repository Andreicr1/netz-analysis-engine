"""Seed sec_money_market_funds from N-MFP datasets (SUBMISSION + SERIESLEVELINFO).

Usage:
    python -m scripts.seed_mmf_catalog --nmfp-dir "C:/Users/Andrei/Desktop/EDGAR FILES/20260209-20260306_nmfp"
    python -m scripts.seed_mmf_catalog --nmfp-dir ... --dsn "postgresql://..."
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
POOL_SIZE = 8


# ── TSV Parsing ──────────────────────────────────────────────────────

def _parse_tsv(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append({k.strip(): v.strip() if v else None for k, v in row.items()})
    return rows


def _parse_all(nmfp_dir: Path) -> tuple[list[dict], list[dict]]:
    paths = [
        nmfp_dir / "NMFP_SUBMISSION.tsv",
        nmfp_dir / "NMFP_SERIESLEVELINFO.tsv",
    ]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Missing: {p}")

    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_parse_tsv, p) for p in paths]
        submission, series_info = [f.result() for f in futures]
    return submission, series_info


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
    return val.upper() in ("Y", "TRUE", "1")


def _parse_date(val: str | None) -> str | None:
    """Parse DD-MON-YYYY to YYYY-MM-DD."""
    if not val:
        return None
    import datetime
    try:
        return datetime.datetime.strptime(val, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _strategy_from_category(cat: str | None) -> str | None:
    if not cat:
        return None
    cat_lower = cat.lower()
    if "government" in cat_lower:
        return "Government Money Market"
    if "prime" in cat_lower:
        return "Prime Money Market"
    if "tax" in cat_lower or "exempt" in cat_lower:
        return "Tax-Exempt Money Market"
    if "single state" in cat_lower:
        return "Single State Money Market"
    return "Prime Money Market"


def _build_mmf_rows(submission: list[dict], series_info: list[dict]) -> list[tuple]:
    t0 = time.time()

    # Index series_info by ACCESSION_NUMBER
    info_by_acc = {r["ACCESSION_NUMBER"]: r for r in series_info if r.get("ACCESSION_NUMBER")}

    rows = []
    seen_series: set[str] = set()
    for sub in submission:
        sid = sub.get("SERIESID")
        acc = sub.get("ACCESSION_NUMBER")
        if not sid or not acc:
            continue
        # Deduplicate by series_id (keep first / latest filing)
        if sid in seen_series:
            continue
        seen_series.add(sid)

        info = info_by_acc.get(acc, {})
        mmf_cat = info.get("MONEYMARKETFUNDCATEGORY") or "Prime"

        rows.append((
            sid,                                                    # series_id
            sub.get("CIK") or sub.get("FILER_CIK"),                # cik
            acc,                                                    # accession_number
            sub.get("NAMEOFSERIES") or sub.get("SERIES_NAME") or "Unknown",  # fund_name
            sub.get("LEIOFSERIES"),                                 # lei_series
            sub.get("REGISTRANTLEIID"),                             # lei_registrant
            mmf_cat,                                                # mmf_category
            _strategy_from_category(mmf_cat),                       # strategy_label
            _yn_bool(info.get("GOVMONEYMRKTFUNDFLAG")),             # is_govt_fund
            _yn_bool(info.get("FUNDRETAILMONEYMARKETFLAG")),        # is_retail
            _yn_bool(info.get("FUNDEXEMPTRETAILFLAG")),             # is_exempt_retail
            _safe_int(info.get("AVERAGEPORTFOLIOMATURITY")),        # weighted_avg_maturity
            _safe_int(info.get("AVERAGELIFEMATURITY")),             # weighted_avg_life
            _safe_decimal(info.get("SEVENDAYGROSSYIELD")),          # seven_day_gross_yield
            _safe_decimal(info.get("NETASSETOFSERIES")),            # net_assets
            _safe_decimal(info.get("NUMBEROFSHARESOUTSTANDING")),   # shares_outstanding
            _safe_decimal(info.get("TOTALVALUEPORTFOLIOSECURITIES")),# total_portfolio_securities
            _safe_decimal(info.get("CASH")),                        # cash
            _safe_decimal(info.get("PCTDLYLIQUIDASSETFRIDAYWEEK5")),# pct_daily_liquid_latest
            _safe_decimal(info.get("PCTWKLYLIQUIDASSETFRIDAYWEEK5")),# pct_weekly_liquid_latest
            _yn_bool(info.get("SEEKSTABLEPRICEPERSHARE")),          # seeks_stable_nav
            _safe_decimal(info.get("STABLEPRICEPERSHARE")),         # stable_nav_price
            _parse_date(sub.get("REPORTDATE")),                     # reporting_period
            sub.get("REGISTRANT") or sub.get("REGISTRANTFULLNAME"), # investment_adviser
        ))

    logger.info("mmf_rows_built", count=len(rows), elapsed=f"{time.time()-t0:.2f}s")
    return rows


# ── DB Upsert ────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO sec_money_market_funds (
    series_id, cik, accession_number, fund_name, lei_series, lei_registrant,
    mmf_category, strategy_label, is_govt_fund, is_retail, is_exempt_retail,
    weighted_avg_maturity, weighted_avg_life, seven_day_gross_yield,
    net_assets, shares_outstanding, total_portfolio_securities, cash,
    pct_daily_liquid_latest, pct_weekly_liquid_latest,
    seeks_stable_nav, stable_nav_price, reporting_period, investment_adviser
) VALUES (
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23::date,$24
) ON CONFLICT (series_id) DO UPDATE SET
    cik = EXCLUDED.cik,
    accession_number = EXCLUDED.accession_number,
    fund_name = EXCLUDED.fund_name,
    lei_series = COALESCE(EXCLUDED.lei_series, sec_money_market_funds.lei_series),
    lei_registrant = COALESCE(EXCLUDED.lei_registrant, sec_money_market_funds.lei_registrant),
    mmf_category = EXCLUDED.mmf_category,
    strategy_label = EXCLUDED.strategy_label,
    is_govt_fund = EXCLUDED.is_govt_fund,
    is_retail = EXCLUDED.is_retail,
    is_exempt_retail = EXCLUDED.is_exempt_retail,
    weighted_avg_maturity = EXCLUDED.weighted_avg_maturity,
    weighted_avg_life = EXCLUDED.weighted_avg_life,
    seven_day_gross_yield = EXCLUDED.seven_day_gross_yield,
    net_assets = EXCLUDED.net_assets,
    shares_outstanding = EXCLUDED.shares_outstanding,
    total_portfolio_securities = EXCLUDED.total_portfolio_securities,
    cash = EXCLUDED.cash,
    pct_daily_liquid_latest = EXCLUDED.pct_daily_liquid_latest,
    pct_weekly_liquid_latest = EXCLUDED.pct_weekly_liquid_latest,
    seeks_stable_nav = EXCLUDED.seeks_stable_nav,
    stable_nav_price = EXCLUDED.stable_nav_price,
    reporting_period = EXCLUDED.reporting_period,
    investment_adviser = EXCLUDED.investment_adviser,
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
    logger.info("mmf_catalog_upsert_complete", rows=total, elapsed=f"{time.time()-t0:.2f}s")


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sec_money_market_funds from N-MFP")
    parser.add_argument("--nmfp-dir", type=str, required=True, help="Path to N-MFP directory")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    args = parser.parse_args()

    nmfp_dir = Path(args.nmfp_dir)
    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    t0 = time.time()
    submission, series_info = _parse_all(nmfp_dir)
    logger.info("tsv_parsed", submission=len(submission), series_info=len(series_info))

    rows = _build_mmf_rows(submission, series_info)
    asyncio.run(_upsert_all(dsn, rows))
    logger.info("seed_mmf_catalog_done", total_elapsed=f"{time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
