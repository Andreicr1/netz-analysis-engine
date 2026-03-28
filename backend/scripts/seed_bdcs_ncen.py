"""Seed sec_bdcs from SEC BDC registry XML + optional N-CEN enrichment.

The SEC BDC XML (business-development-company-YYYY.xml) is the authoritative
whitelist of registered BDCs. N-CEN data enriches with financial metrics
when available (overlap is currently 0 but future-proofed).

Usage:
    python -m scripts.seed_bdcs_ncen \
        --bdc-xml "C:/Users/Andrei/Desktop/EDGAR FILES/business-development-company-2025.xml" \
        [--ncen-dir "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_ncen (1)"] \
        [--dsn "postgresql://..."]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import structlog

logger = structlog.get_logger()

BATCH_SIZE = 100
POOL_SIZE = 8


# ── XML + TSV Parsing ────────────────────────────────────────────────

def _parse_bdc_xml(path: Path) -> dict[str, dict]:
    """Parse BDC XML whitelist. Returns {cik_stripped: {fields...}}."""
    tree = ET.parse(path)
    root = tree.getroot()
    result = {}
    for company in root.findall("company"):
        cik_raw = company.findtext("cik", "").strip()
        cik = cik_raw.lstrip("0")
        if not cik:
            continue
        result[cik] = {
            "cik": cik,
            "registrant_name": company.findtext("registrant_name", "").strip() or None,
            "file_number": company.findtext("file_number", "").strip() or None,
            "city": company.findtext("city", "").strip() or None,
            "state": company.findtext("state", "").strip() or None,
            "zip_code": company.findtext("zip_code", "").strip() or None,
            "last_filing_date": company.findtext("last_filling_date", "").strip() or None,
            "last_filing_type": company.findtext("last_filling_type", "").strip() or None,
        }
    return result


def _parse_ncen_fund_info(ncen_dir: Path) -> dict[str, dict]:
    """Parse N-CEN FUND_REPORTED_INFO.tsv, index by CIK."""
    path = ncen_dir / "FUND_REPORTED_INFO.tsv"
    if not path.exists():
        return {}
    result: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            row = {k.strip(): (v.strip() if v else None) for k, v in r.items()}
            fund_id = row.get("FUND_ID", "")
            parts = fund_id.split("_")
            cik = parts[1] if len(parts) >= 3 else None
            if cik and cik not in result:
                result[cik] = row
    return result


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


def _build_bdc_rows(
    bdc_whitelist: dict[str, dict],
    ncen_data: dict[str, dict],
) -> list[tuple]:
    """Build upsert tuples. XML is authority; N-CEN enriches."""
    t0 = time.time()
    rows = []

    for cik, bdc in bdc_whitelist.items():
        ncen = ncen_data.get(cik, {})
        series_id = ncen.get("SERIES_ID") or cik
        fund_name = bdc["registrant_name"] or ncen.get("FUND_NAME") or "Unknown"

        rows.append((
            series_id,                                              # series_id (PK)
            cik,                                                    # cik
            ncen.get("FUND_ID"),                                    # fund_id
            fund_name,                                              # fund_name
            ncen.get("LEI"),                                        # lei
            None,                                                   # ticker (BDCs traded on exchange, but not in N-CEN)
            None,                                                   # isin
            "Private Credit",                                       # strategy_label (default for BDCs)
            None,                                                   # investment_focus
            _safe_decimal(ncen.get("MANAGEMENT_FEE")),              # management_fee
            _safe_decimal(ncen.get("NET_OPERATING_EXPENSES")),      # net_operating_expenses
            _safe_decimal(ncen.get("RETURN_B4_FEES_AND_EXPENSES")), # return_before_fees
            _safe_decimal(ncen.get("RETURN_AFTR_FEES_AND_EXPENSES")),# return_after_fees
            _safe_decimal(ncen.get("MONTHLY_AVG_NET_ASSETS")),      # monthly_avg_net_assets
            _safe_decimal(ncen.get("DAILY_AVG_NET_ASSETS")),        # daily_avg_net_assets
            _safe_decimal(ncen.get("NAV_PER_SHARE")),               # nav_per_share
            _safe_decimal(ncen.get("MARKET_PRICE_PER_SHARE")),      # market_price_per_share
            None,                                                   # is_externally_managed
            _yn_bool(ncen.get("IS_SEC_LENDING_AUTHORIZED")),        # is_sec_lending_authorized
            _yn_bool(ncen.get("HAS_LINE_OF_CREDIT")) if ncen else None,  # has_line_of_credit
            _yn_bool(ncen.get("HAS_INTERFUND_BORROWING")) if ncen else None,  # has_interfund_borrowing
        ))

    logger.info("bdc_rows_built", count=len(rows), with_ncen=sum(1 for c in bdc_whitelist if c in ncen_data), elapsed=f"{time.time()-t0:.2f}s")
    return rows


# ── DB Upsert ────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO sec_bdcs (
    series_id, cik, fund_id, fund_name, lei, ticker, isin,
    strategy_label, investment_focus,
    management_fee, net_operating_expenses, return_before_fees, return_after_fees,
    monthly_avg_net_assets, daily_avg_net_assets, nav_per_share, market_price_per_share,
    is_externally_managed, is_sec_lending_authorized, has_line_of_credit, has_interfund_borrowing
) VALUES (
    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21
) ON CONFLICT (series_id) DO UPDATE SET
    cik = EXCLUDED.cik,
    fund_id = COALESCE(EXCLUDED.fund_id, sec_bdcs.fund_id),
    fund_name = EXCLUDED.fund_name,
    lei = COALESCE(EXCLUDED.lei, sec_bdcs.lei),
    strategy_label = COALESCE(sec_bdcs.strategy_label, EXCLUDED.strategy_label),
    management_fee = COALESCE(EXCLUDED.management_fee, sec_bdcs.management_fee),
    net_operating_expenses = COALESCE(EXCLUDED.net_operating_expenses, sec_bdcs.net_operating_expenses),
    return_before_fees = COALESCE(EXCLUDED.return_before_fees, sec_bdcs.return_before_fees),
    return_after_fees = COALESCE(EXCLUDED.return_after_fees, sec_bdcs.return_after_fees),
    monthly_avg_net_assets = COALESCE(EXCLUDED.monthly_avg_net_assets, sec_bdcs.monthly_avg_net_assets),
    daily_avg_net_assets = COALESCE(EXCLUDED.daily_avg_net_assets, sec_bdcs.daily_avg_net_assets),
    nav_per_share = COALESCE(EXCLUDED.nav_per_share, sec_bdcs.nav_per_share),
    market_price_per_share = COALESCE(EXCLUDED.market_price_per_share, sec_bdcs.market_price_per_share),
    is_sec_lending_authorized = COALESCE(EXCLUDED.is_sec_lending_authorized, sec_bdcs.is_sec_lending_authorized),
    has_line_of_credit = COALESCE(EXCLUDED.has_line_of_credit, sec_bdcs.has_line_of_credit),
    has_interfund_borrowing = COALESCE(EXCLUDED.has_interfund_borrowing, sec_bdcs.has_interfund_borrowing),
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
    logger.info("bdc_upsert_complete", rows=total, elapsed=f"{time.time()-t0:.2f}s")


# ── Entrypoint ───────────────────────────────────────────────────────

def _resolve_dsn(dsn: str | None) -> str:
    if dsn:
        return dsn
    raw = os.environ.get("DATABASE_URL", "")
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql://", 1)
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sec_bdcs from SEC BDC XML + optional N-CEN")
    parser.add_argument("--bdc-xml", type=str, required=True, help="Path to BDC registry XML")
    parser.add_argument("--ncen-dir", type=str, help="Path to N-CEN directory (optional enrichment)")
    parser.add_argument("--dsn", type=str, help="Direct PostgreSQL DSN")
    args = parser.parse_args()

    bdc_xml_path = Path(args.bdc_xml)
    if not bdc_xml_path.exists():
        raise FileNotFoundError(f"BDC XML not found: {bdc_xml_path}")

    dsn = _resolve_dsn(args.dsn)
    if not dsn:
        raise ValueError("No DSN provided and DATABASE_URL not set")

    t0 = time.time()

    # Parse in parallel (XML + optional N-CEN)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_xml = pool.submit(_parse_bdc_xml, bdc_xml_path)
        if args.ncen_dir:
            f_ncen = pool.submit(_parse_ncen_fund_info, Path(args.ncen_dir))
            ncen_data = f_ncen.result()
        else:
            ncen_data = {}
        bdc_whitelist = f_xml.result()

    logger.info("parsed", bdc_xml=len(bdc_whitelist), ncen_funds=len(ncen_data))

    rows = _build_bdc_rows(bdc_whitelist, ncen_data)
    asyncio.run(_upsert_all(dsn, rows))
    logger.info("seed_bdcs_done", total_elapsed=f"{time.time()-t0:.2f}s")


if __name__ == "__main__":
    main()
