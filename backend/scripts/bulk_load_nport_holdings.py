"""Bulk parse N-PORT holdings from DERA TSV → local CSV files.

Step 1 (this script): Parse + filter → save CSV per quarter to output dir
Step 2 (Tiger CLI or psql): COPY/INSERT from CSVs into sec_nport_holdings

Usage:
    cd backend
    python scripts/bulk_load_nport_holdings.py \
        --parent "C:/Users/Andrei/Desktop/EDGAR FILES/nport" \
        --extra "C:/Users/Andrei/Desktop/EDGAR FILES/2025q4_nport" \
        --out "C:/Users/Andrei/Desktop/EDGAR FILES/nport_parsed" \
        --workers 20 --top 50
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Ensure backend/ is on sys.path
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

DEFAULT_WORKERS = 20
DEFAULT_TOP_N = 50

CSV_COLUMNS = [
    "report_date", "cik", "cusip", "isin", "issuer_name", "asset_class",
    "sector", "market_value", "quantity", "currency", "pct_of_nav",
    "is_restricted", "fair_value_level", "series_id",
]


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

    cik_map: dict[str, str] = {}
    valid_accessions: set[str] = set()
    with open(f"{nport_dir}/REGISTRANT.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            cik = r["CIK"]
            acc = r["ACCESSION_NUMBER"]
            if cik in catalog_ciks or cik.lstrip("0") in catalog_ciks:
                cik_map[acc] = cik
                valid_accessions.add(acc)

    date_map: dict[str, str] = {}
    with open(f"{nport_dir}/SUBMISSION.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            acc = r["ACCESSION_NUMBER"]
            if acc in valid_accessions:
                date_map[acc] = r["REPORT_ENDING_PERIOD"]

    series_map: dict[str, str] = {}
    with open(f"{nport_dir}/FUND_REPORTED_INFO.tsv", encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            acc = r["ACCESSION_NUMBER"]
            if acc in valid_accessions:
                series_map[acc] = r.get("SERIES_ID", "")

    isin_map: dict[str, str] = {}
    isin_path = f"{nport_dir}/IDENTIFIERS.tsv"
    if os.path.exists(isin_path):
        with open(isin_path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                isin_val = (r.get("IDENTIFIER_ISIN") or "").strip()
                if isin_val:
                    isin_map[r["HOLDING_ID"]] = isin_val

    elapsed = time.monotonic() - t0
    print(f"  Lookups: {len(cik_map)} accessions in {elapsed:.1f}s")

    return {
        "cik": cik_map, "date": date_map, "series": series_map,
        "isin": isin_map, "valid_accessions": valid_accessions,
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
            "isin": isin or "",
            "issuer_name": (r.get("ISSUER_NAME") or "")[:255],
            "asset_class": (r.get("ASSET_CAT") or "")[:50],
            "sector": (r.get("ISSUER_TYPE") or "")[:50],
            "market_value": _safe_int(r.get("CURRENCY_VALUE")) or 0,
            "quantity": _safe_float(r.get("BALANCE")) or 0,
            "currency": (r.get("CURRENCY_CODE") or "USD")[:3],
            "pct_of_nav": pct or 0,
            "is_restricted": "t" if r.get("IS_RESTRICTED_SECURITY", "").upper() == "Y" else "f",
            "fair_value_level": (r.get("FAIR_VALUE_LEVEL") or "")[:10],
            "series_id": series_id or "",
            "_sort_key": (cik.lstrip("0"), report_date, series_id or ""),
            "_abs_pct": abs(pct) if pct else 0,
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

    all_rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(parse_chunk, c): i for i, c in enumerate(chunks)}
        for future in as_completed(futures):
            try:
                all_rows.extend(future.result())
            except Exception as e:
                print(f"  chunk FAILED: {e}")

    # Top N filter
    if top_n and all_rows:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for row in all_rows:
            key = row.pop("_sort_key")
            abs_pct = row.pop("_abs_pct")
            row["_abs_pct"] = abs_pct
            groups[key].append(row)

        filtered = []
        for group in groups.values():
            group.sort(key=lambda r: r["_abs_pct"], reverse=True)
            for r in group[:top_n]:
                r.pop("_abs_pct", None)
                filtered.append(r)
        all_rows = filtered

    for row in all_rows:
        row.pop("_sort_key", None)
        row.pop("_abs_pct", None)

    elapsed = time.monotonic() - t0
    print(f"  Parsed {total_lines:,} lines -> {len(all_rows):,} rows "
          f"(top {top_n}/fund) in {elapsed:.1f}s")
    return all_rows


# ── Write CSV ─────────────────────────────────────────────────────────


def write_csv(rows: list[dict], out_path: str) -> int:
    """Write parsed rows to CSV file."""
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# ── Discover quarter directories ──────────────────────────────────────


def discover_quarters(parent_dir: str, extra_dirs: list[str] | None = None) -> list[str]:
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
    parser = argparse.ArgumentParser(description="Parse N-PORT holdings → CSV files")
    parser.add_argument("--dir", help="Single quarter directory")
    parser.add_argument("--parent", help="Parent dir with quarter subdirs")
    parser.add_argument("--extra", nargs="*", help="Additional quarter directories")
    parser.add_argument("--out", required=True, help="Output directory for CSV files")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()

    if args.dir:
        quarter_dirs = [args.dir]
    elif args.parent:
        quarter_dirs = discover_quarters(args.parent, args.extra)
    else:
        print("ERROR: specify --dir or --parent")
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)

    print(f"{'=' * 70}")
    print(f"  N-PORT Holdings Parser → CSV")
    print(f"  Quarters: {len(quarter_dirs)} | Workers: {args.workers} | Top: {args.top}/fund")
    print(f"  Output: {args.out}")
    print(f"{'=' * 70}")

    catalog_ciks = fetch_catalog_ciks()

    grand_total = 0
    t_start = time.monotonic()

    for qi, qdir in enumerate(quarter_dirs, 1):
        qname = os.path.basename(qdir)
        print(f"\n[{qi}/{len(quarter_dirs)}] {qname}")
        print(f"{'-' * 50}")

        lookups = build_lookups(qdir, catalog_ciks)
        if not lookups["valid_accessions"]:
            print(f"  SKIP: no catalog CIKs")
            continue

        rows = parse_and_filter(qdir, lookups, workers=args.workers, top_n=args.top)
        if not rows:
            print(f"  SKIP: no rows")
            continue

        csv_path = os.path.join(args.out, f"{qname}.csv")
        count = write_csv(rows, csv_path)
        grand_total += count
        print(f"  Saved: {csv_path} ({count:,} rows)")

    elapsed = time.monotonic() - t_start
    print(f"\n{'=' * 70}")
    print(f"  COMPLETE — {len(quarter_dirs)} quarters")
    print(f"  Total rows: {grand_total:,}")
    print(f"  Time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print(f"  Output: {args.out}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
