"""Bulk load N-PORT holdings from DERA TSV into sec_nport_holdings.

Reads FUND_REPORTED_HOLDING.tsv + SUBMISSION.tsv + REGISTRANT.tsv + FUND_REPORTED_INFO.tsv,
joins them by ACCESSION_NUMBER, filters to catalog CIKs and top 50 holdings per fund/quarter,
and upserts into sec_nport_holdings with series_id.

Usage:
    cd backend
    # Single quarter:
    python scripts/bulk_load_nport_holdings.py --dir "C:/path/to/2025q4_nport"

    # All quarters (parent dir with subdirs like 2020q1_nport, 2020q2_nport, ...):
    python scripts/bulk_load_nport_holdings.py --parent "C:/path/to/nport" --extra "C:/path/to/2025q4_nport"

    # Options:
    python scripts/bulk_load_nport_holdings.py --parent ... --workers 20 --batch 5000 --top 50 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Ensure backend/ is on sys.path
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_WORKERS = 20
DEFAULT_BATCH = 5000
DEFAULT_TOP_N = 50
UPSERT_SQL = """
    INSERT INTO sec_nport_holdings
        (report_date, cik, cusip, isin, issuer_name, asset_class, sector,
         market_value, quantity, currency, pct_of_nav, is_restricted,
         fair_value_level, series_id)
    VALUES
        (:report_date, :cik, :cusip, :isin, :issuer_name, :asset_class, :sector,
         :market_value, :quantity, :currency, :pct_of_nav, :is_restricted,
         :fair_value_level, :series_id)
    ON CONFLICT (report_date, cik, cusip) DO UPDATE SET
        isin = EXCLUDED.isin,
        issuer_name = EXCLUDED.issuer_name,
        asset_class = EXCLUDED.asset_class,
        sector = EXCLUDED.sector,
        market_value = EXCLUDED.market_value,
        quantity = EXCLUDED.quantity,
        currency = EXCLUDED.currency,
        pct_of_nav = EXCLUDED.pct_of_nav,
        is_restricted = EXCLUDED.is_restricted,
        fair_value_level = EXCLUDED.fair_value_level,
        series_id = EXCLUDED.series_id
"""


# ── Fetch catalog CIKs from DB ───────────────────────────────────────


def fetch_catalog_ciks() -> set[str]:
    """Fetch CIKs of active instruments from instruments_universe."""
    import asyncio

    from sqlalchemy import text

    from app.core.db.engine import async_session_factory

    async def _fetch():
        async with async_session_factory() as db:
            result = await db.execute(text("""
                SELECT DISTINCT attributes->>'sec_cik' AS cik
                FROM instruments_universe
                WHERE is_active = true
                  AND attributes->>'sec_cik' IS NOT NULL
            """))
            return {r[0] for r in result.all()}

    raw_ciks = asyncio.run(_fetch())
    # Normalize: strip leading zeros for matching, but also keep zero-padded
    normalized: set[str] = set()
    for cik in raw_ciks:
        normalized.add(cik)
        normalized.add(cik.lstrip("0") or "0")
        normalized.add(cik.zfill(10))
    print(f"Catalog CIKs loaded: {len(raw_ciks)} unique ({len(normalized)} with variants)")
    return normalized


# ── Phase 1: Parse lookup tables ──────────────────────────────────────


def build_lookups(nport_dir: str, catalog_ciks: set[str]) -> dict:
    """Build accession_number → metadata lookups, filtered to catalog CIKs."""
    t0 = time.monotonic()

    # REGISTRANT: accession → cik (only catalog CIKs)
    cik_map: dict[str, str] = {}
    valid_accessions: set[str] = set()
    with open(f"{nport_dir}/REGISTRANT.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            cik = r["CIK"]
            acc = r["ACCESSION_NUMBER"]
            # Check if this CIK is in our catalog (any normalization)
            if cik in catalog_ciks or cik.lstrip("0") in catalog_ciks:
                cik_map[acc] = cik
                valid_accessions.add(acc)

    # SUBMISSION: accession → report_date (only valid accessions)
    date_map: dict[str, str] = {}
    with open(f"{nport_dir}/SUBMISSION.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            acc = r["ACCESSION_NUMBER"]
            if acc in valid_accessions:
                date_map[acc] = r["REPORT_ENDING_PERIOD"]

    # FUND_REPORTED_INFO: accession → series_id (only valid accessions)
    series_map: dict[str, str] = {}
    with open(f"{nport_dir}/FUND_REPORTED_INFO.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            acc = r["ACCESSION_NUMBER"]
            if acc in valid_accessions:
                series_map[acc] = r.get("SERIES_ID", "")

    # IDENTIFIERS: holding_id → isin (only load if file not too large)
    isin_map: dict[str, str] = {}
    isin_path = f"{nport_dir}/IDENTIFIERS.tsv"
    if os.path.exists(isin_path):
        with open(isin_path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                isin_val = (r.get("IDENTIFIER_ISIN") or "").strip()
                if isin_val:
                    isin_map[r["HOLDING_ID"]] = isin_val

    elapsed = time.monotonic() - t0
    print(f"  Lookups: {len(cik_map)} accessions (from {len(valid_accessions)} catalog matches) "
          f"in {elapsed:.1f}s")

    return {
        "cik": cik_map,
        "date": date_map,
        "series": series_map,
        "isin": isin_map,
        "valid_accessions": valid_accessions,
    }


# ── Phase 2: Parse holdings in parallel ───────────────────────────────


def _parse_date(raw: str) -> str | None:
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _safe_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


def _safe_int(val: str | None) -> int | None:
    f = _safe_float(val)
    return int(f) if f is not None else None


def parse_chunk(args: tuple) -> list[dict]:
    """Parse a chunk of holdings lines, filtered to valid accessions."""
    lines, header, cik_map, date_map, series_map, isin_map, valid_accessions = args

    rows = []
    for line in lines:
        fields = line.rstrip("\n").split("\t")
        if len(fields) < len(header):
            fields.extend([""] * (len(header) - len(fields)))
        r = dict(zip(header, fields))

        acc = r.get("ACCESSION_NUMBER", "")
        if acc not in valid_accessions:
            continue

        cik = cik_map.get(acc)
        report_date_raw = date_map.get(acc)
        series_id = series_map.get(acc)

        if not cik or not report_date_raw:
            continue

        report_date = _parse_date(report_date_raw)
        if not report_date:
            continue

        cusip = (r.get("ISSUER_CUSIP") or "").strip()
        if not cusip or cusip == "000000000":
            continue

        holding_id = r.get("HOLDING_ID", "")
        isin = isin_map.get(holding_id)
        pct = _safe_float(r.get("PERCENTAGE"))

        rows.append({
            "report_date": report_date,
            "cik": cik.lstrip("0") or "0",
            "cusip": cusip,
            "isin": isin,
            "issuer_name": (r.get("ISSUER_NAME") or "")[:255],
            "asset_class": (r.get("ASSET_CAT") or "")[:50] or None,
            "sector": (r.get("ISSUER_TYPE") or "")[:50] or None,
            "market_value": _safe_int(r.get("CURRENCY_VALUE")),
            "quantity": _safe_float(r.get("BALANCE")),
            "currency": (r.get("CURRENCY_CODE") or "USD")[:3],
            "pct_of_nav": pct,
            "is_restricted": r.get("IS_RESTRICTED_SECURITY", "").upper() == "Y",
            "fair_value_level": (r.get("FAIR_VALUE_LEVEL") or "")[:10] or None,
            "series_id": series_id,
            # For top-N sorting
            "_sort_key": (cik.lstrip("0"), report_date, series_id or ""),
            "_pct": abs(pct) if pct else 0,
        })

    return rows


def parse_and_filter(
    nport_dir: str,
    lookups: dict,
    workers: int = DEFAULT_WORKERS,
    top_n: int = DEFAULT_TOP_N,
    chunk_lines: int = 100_000,
) -> list[dict]:
    """Parse holdings, filter to catalog CIKs, keep top N per fund/quarter."""
    t0 = time.monotonic()
    holdings_path = f"{nport_dir}/FUND_REPORTED_HOLDING.tsv"

    if not os.path.exists(holdings_path):
        print(f"  SKIP: {holdings_path} not found")
        return []

    with open(holdings_path, encoding="utf-8") as f:
        header_line = f.readline().rstrip("\n")
        header = header_line.split("\t")
        all_lines = f.readlines()

    total_lines = len(all_lines)

    # Split into chunks
    chunks = []
    for i in range(0, total_lines, chunk_lines):
        chunk = all_lines[i:i + chunk_lines]
        chunks.append((
            chunk, header,
            lookups["cik"], lookups["date"],
            lookups["series"], lookups["isin"],
            lookups["valid_accessions"],
        ))
    del all_lines

    # Parse in parallel
    all_rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(parse_chunk, c): i for i, c in enumerate(chunks)}
        for future in as_completed(futures):
            try:
                all_rows.extend(future.result())
            except Exception as e:
                print(f"  chunk FAILED: {e}")

    parse_time = time.monotonic() - t0

    # Top N filter: group by (cik, report_date, series_id), keep top N by pct_of_nav
    if top_n and all_rows:
        from collections import defaultdict
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for row in all_rows:
            key = row.pop("_sort_key")
            pct = row.pop("_pct")
            row["_pct"] = pct
            groups[key].append(row)

        filtered = []
        for key, group in groups.items():
            group.sort(key=lambda r: r["_pct"], reverse=True)
            for r in group[:top_n]:
                r.pop("_pct", None)
                filtered.append(r)
        all_rows = filtered

    # Clean temp keys from non-filtered rows
    for row in all_rows:
        row.pop("_sort_key", None)
        row.pop("_pct", None)

    elapsed = time.monotonic() - t0
    print(f"  Parsed {total_lines:,} lines -> {len(all_rows):,} rows "
          f"(top {top_n}/fund) in {elapsed:.1f}s")
    return all_rows


# ── Phase 3: Batch upsert to DB ──────────────────────────────────────


def upsert_to_db(rows: list[dict], batch_size: int = DEFAULT_BATCH) -> int:
    """Upsert rows into sec_nport_holdings."""
    import asyncio

    from sqlalchemy import text

    from app.core.db.engine import async_session_factory

    total_upserted = 0

    async def _do_upsert():
        nonlocal total_upserted
        async with async_session_factory() as db:
            for i in range(0, len(rows), batch_size):
                chunk = rows[i:i + batch_size]
                try:
                    await db.execute(text(UPSERT_SQL), chunk)
                    await db.commit()
                    total_upserted += len(chunk)
                    if (i // batch_size + 1) % 50 == 0:
                        print(f"    upserted {total_upserted:,} / {len(rows):,}")
                except Exception as e:
                    print(f"    batch {i // batch_size} failed: {str(e)[:200]}")
                    await db.rollback()

    asyncio.run(_do_upsert())
    return total_upserted


# ── Discover quarter directories ──────────────────────────────────────


def discover_quarters(parent_dir: str, extra_dirs: list[str] | None = None) -> list[str]:
    """Find all quarter directories under parent, sorted chronologically."""
    dirs = []
    if parent_dir and os.path.isdir(parent_dir):
        for name in sorted(os.listdir(parent_dir)):
            full = os.path.join(parent_dir, name)
            if os.path.isdir(full) and "nport" in name.lower():
                dirs.append(full)
    for d in (extra_dirs or []):
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    return dirs


# ── Main ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Bulk load N-PORT holdings from DERA TSV")
    parser.add_argument("--dir", help="Single quarter directory")
    parser.add_argument("--parent", help="Parent dir with quarter subdirs (2020q1_nport, ...)")
    parser.add_argument("--extra", nargs="*", help="Additional quarter directories")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="CPU workers for parsing")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="DB upsert batch size")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="Top N holdings per fund/quarter")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB write")
    args = parser.parse_args()

    # Discover directories
    if args.dir:
        quarter_dirs = [args.dir]
    elif args.parent:
        quarter_dirs = discover_quarters(args.parent, args.extra)
    else:
        print("ERROR: specify --dir or --parent")
        sys.exit(1)

    if not quarter_dirs:
        print("ERROR: no quarter directories found")
        sys.exit(1)

    print(f"{'=' * 70}")
    print(f"  N-PORT Bulk Holdings Loader")
    print(f"  Quarters: {len(quarter_dirs)} | Workers: {args.workers} | "
          f"Top: {args.top}/fund | Batch: {args.batch}")
    print(f"{'=' * 70}")

    # Load catalog CIKs once
    catalog_ciks = fetch_catalog_ciks()

    grand_total = 0
    grand_upserted = 0
    t_start = time.monotonic()

    for qi, qdir in enumerate(quarter_dirs, 1):
        qname = os.path.basename(qdir)
        print(f"\n[{qi}/{len(quarter_dirs)}] {qname}")
        print(f"{'-' * 50}")

        # Phase 1: Build lookups (filtered to catalog CIKs)
        lookups = build_lookups(qdir, catalog_ciks)
        if not lookups["valid_accessions"]:
            print(f"  SKIP: no catalog CIKs found in this quarter")
            continue

        # Phase 2: Parse + filter top N
        rows = parse_and_filter(qdir, lookups, workers=args.workers, top_n=args.top)
        grand_total += len(rows)

        if not rows:
            print(f"  SKIP: no holdings after filtering")
            continue

        if args.dry_run:
            print(f"  DRY RUN: {len(rows):,} rows")
            for r in rows[:2]:
                print(f"    {r['report_date']} | CIK {r['cik']} | {r['series_id']} | "
                      f"{r['cusip']} | {r['issuer_name'][:35]} | {r['pct_of_nav']}%")
            continue

        # Phase 3: Upsert
        upserted = upsert_to_db(rows, batch_size=args.batch)
        grand_upserted += upserted
        print(f"  Upserted: {upserted:,} rows")

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 70}")
    print(f"  COMPLETE — {len(quarter_dirs)} quarters")
    print(f"  Total parsed: {grand_total:,} rows")
    if not args.dry_run:
        print(f"  Total upserted: {grand_upserted:,} rows")
    print(f"  Time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
