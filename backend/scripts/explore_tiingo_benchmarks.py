"""Phase A0 discovery: regex-extract primary benchmark strings from
``instruments_universe.attributes->'tiingo_description'``.

Dry-run only. Does not modify any row. Emits a stratified CSV to
``docs/diagnostics/{date}-tiingo-benchmark-discovery.csv`` plus a stdout
summary (pattern counts, fund-type counts, coverage projection) and a
50-sample stratified print (10 per pattern_id) for human QA.

Usage:
    python -m scripts.explore_tiingo_benchmarks \
        [--limit N] [--out PATH]

PR-Q5.1 Phase A0.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.db.engine import async_session_factory

# Every capture MUST start with a recognized index provider — the only
# reliable way to reject generic filler ("the Index", "its benchmark index",
# "parent index") that the A0 v1 patterns produced. Context clauses
# ("seeks to track", "designed to track") only *rank* confidence; the
# capture shape is identical across all five rails.
_PROVIDER = (
    r"(?:S&P|Russell|MSCI|Bloomberg|Barclays|FTSE|Dow\s+Jones|"
    r"NASDAQ|Nasdaq|Wilshire|ICE\s+BofA|ICE|CRSP|Morningstar|"
    r"Solactive|STOXX|Stoxx|Nikkei|TOPIX|Hang\s+Seng|Euro\s+Stoxx|"
    r"Alerian|JPMorgan|J\.?P\.?\s*Morgan|Markit|Citi|BofA|"
    r"Deutsche\s+B[oö]rse|Nomura|S&P/TSX|S&P/ASX|S&P/BMV|Hartford|"
    r"Nyse|NYSE|Dow\s+Jones\s+U\.S\.|Bloomberg\s+Barclays)"
)
# Trailing "Index" / "Total Return Index" / "Bond Index" required. Limit
# interior chars to 100 so we don't gobble a sentence boundary.
_TAIL = (
    r"[\w\s\.\-&®™()/,:]{3,100}?"
    r"(?:Total\s+Return\s+Index|Bond\s+Index|Composite\s+Index|Index)"
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "etf_canonical",
        re.compile(
            r"seeks\s+to\s+(?:track|replicate|measure)"
            r"(?:\s+the\s+investment\s+results\s+of)?"
            r"(?:\s+the\s+performance\s+of)?"
            r"(?:\s+the)?\s+"
            rf"({_PROVIDER}{_TAIL})",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "etf_variant",
        re.compile(
            r"(?:designed\s+to|attempts?\s+to|intended\s+to)\s+"
            r"(?:track|replicate|correspond\s+to|measure)"
            r"(?:\s+the\s+performance\s+of)?"
            r"(?:\s+the)?\s+"
            rf"({_PROVIDER}{_TAIL})",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "mf_benchmark",
        re.compile(
            r"(?:benchmark(?:s|ed)?\s+(?:against|is|to|=)|"
            r"compared\s+to|benchmark\s*:\s*)"
            r"(?:\s+the)?\s+"
            rf"({_PROVIDER}{_TAIL})",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "mf_outperform",
        re.compile(
            r"(?:outperform|exceed|beat)"
            r"(?:\s+the(?:\s+performance\s+of\s+the)?)?\s+"
            rf"({_PROVIDER}{_TAIL})",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "provider_keyword",
        re.compile(
            rf"({_PROVIDER}{_TAIL})",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
]

# Denylist for post-extraction rejects. These phrases pass provider
# keyword check but are not actual index names.
_DENY_SUBSTRINGS = (
    "underlying index",
    "benchmark index",
    "performance benchmark",
    "the following index",
    "its index",
    "their index",
)

# Heuristic cleanup applied to every extracted raw string before the
# audit CSV is written. Keeps the downstream canonical-map resolver
# comparing apples-to-apples.
_CLEAN_WS = re.compile(r"\s+")


def _clean(raw: str) -> str:
    cleaned = raw.strip().strip(",.;:()\"'")
    cleaned = _CLEAN_WS.sub(" ", cleaned)
    # Drop leading articles/connectors that slipped past the lookbehind.
    cleaned = re.sub(r"^(the|a|an|to)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def extract(description: str) -> tuple[str | None, str | None]:
    """Apply patterns in priority order; return (pattern_id, benchmark).

    Every candidate is length-gated, denylist-gated, and required to
    contain a recognized provider keyword (baked into the regex). This is
    the A0-v2 tightened version — v1 captured generic "the Index" noise.
    """
    if not description:
        return None, None
    for pid, rx in PATTERNS:
        for m in rx.finditer(description):
            cand = _clean(m.group(1))
            low = cand.lower()
            if len(cand) < 8 or len(cand) > 110:
                continue
            if any(bad in low for bad in _DENY_SUBSTRINGS):
                continue
            return pid, cand
    return None, None


async def _fetch_rows(limit: int | None) -> list[dict]:
    sql = """
        SELECT
            isin,
            ticker,
            attributes->>'sec_cik'           AS cik,
            attributes->>'fund_type'         AS fund_type,
            attributes->>'tiingo_description' AS description
        FROM instruments_universe
        WHERE attributes->>'tiingo_description' IS NOT NULL
          AND attributes->>'sec_cik' IS NOT NULL
    """
    if limit:
        sql += f"\n        LIMIT {int(limit)}"
    async with async_session_factory() as s:
        r = await s.execute(text(sql))
        return [dict(row) for row in r.mappings().all()]


async def run(*, limit: int | None, out_path: Path) -> int:
    rows = await _fetch_rows(limit)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pattern_counts: Counter[str] = Counter()
    fund_type_counts: Counter[str] = Counter()
    fund_type_hit_counts: Counter[str] = Counter()
    stratified: dict[str, list[dict]] = defaultdict(list)
    csv_rows: list[dict] = []

    for row in rows:
        fund_type = row.get("fund_type") or "unknown"
        fund_type_counts[fund_type] += 1
        pid, extracted = extract(row["description"] or "")
        if pid:
            pattern_counts[pid] += 1
            fund_type_hit_counts[fund_type] += 1
            stratified[pid].append({
                "ticker": row.get("ticker"),
                "cik": row.get("cik"),
                "desc": (row["description"] or "")[:300],
                "extracted": extracted,
            })
        csv_rows.append({
            "cik": row.get("cik") or "",
            "ticker": row.get("ticker") or "",
            "fund_type": fund_type,
            "description_first_200": (row["description"] or "")[:200]
                .replace("\n", " ").replace("\r", " "),
            "extracted_benchmark_raw": extracted or "",
            "pattern_id": pid or "",
            "pattern_confidence": _confidence_for(pid),
        })

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else [
            "cik", "ticker", "fund_type", "description_first_200",
            "extracted_benchmark_raw", "pattern_id", "pattern_confidence",
        ])
        w.writeheader()
        for r in csv_rows:
            w.writerow(r)

    _print_summary(
        total=len(rows),
        pattern_counts=pattern_counts,
        fund_type_counts=fund_type_counts,
        fund_type_hit_counts=fund_type_hit_counts,
        out_path=out_path,
    )
    _print_stratified(stratified)
    return 0


def _confidence_for(pid: str | None) -> str:
    if not pid:
        return ""
    return {
        "etf_canonical": "high",
        "etf_variant": "high",
        "mf_benchmark": "medium",
        "mf_outperform": "medium",
        "provider_keyword": "low",
    }.get(pid, "unknown")


def _print_summary(
    *,
    total: int,
    pattern_counts: Counter,
    fund_type_counts: Counter,
    fund_type_hit_counts: Counter,
    out_path: Path,
) -> None:
    total_hits = sum(pattern_counts.values())
    print("=" * 72)
    print(f"PR-Q5.1 Phase A0 discovery — {out_path}")
    print("=" * 72)
    print(f"descriptions scanned             : {total}")
    print(f"extractions (any pattern)        : {total_hits}"
          f" ({100 * total_hits / max(total, 1):.1f}%)")
    print()
    print("hits per pattern_id (priority order):")
    for pid, _ in PATTERNS:
        c = pattern_counts.get(pid, 0)
        print(f"  {pid:<20} {c:>6}  ({100 * c / max(total, 1):.1f}%)")
    print()
    print("coverage by fund_type:")
    for ft, tot in fund_type_counts.most_common():
        hits = fund_type_hit_counts.get(ft, 0)
        pct = 100 * hits / max(tot, 1)
        print(f"  {ft:<16} total={tot:>5}  hits={hits:>5}  ({pct:5.1f}%)")
    print()


def _print_stratified(stratified: dict[str, list[dict]]) -> None:
    print("=" * 72)
    print("50-sample stratified human review (10 per pattern_id)")
    print("=" * 72)
    rng = random.Random(42)
    for pid, _ in PATTERNS:
        bucket = stratified.get(pid) or []
        sample = rng.sample(bucket, min(10, len(bucket))) if bucket else []
        print(f"\n--- pattern={pid}  (pool={len(bucket)})")
        for i, row in enumerate(sample, 1):
            print(f"  [{i}] {row['ticker']:<10} cik={row['cik']}")
            print(f"      extracted = {row['extracted']!r}")
            snippet = row["desc"].replace("\n", " ")[:220]
            try:
                print(f"      desc      = {snippet!r}")
            except UnicodeEncodeError:
                print("      desc      = <unicode>  (see CSV)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0,
                   help="Only scan the first N rows (0 = all).")
    p.add_argument("--out", type=str, default=None,
                   help="Output CSV path.")
    args = p.parse_args()

    # Repo root = this file's grandparent (backend/scripts/ → repo root).
    repo_root = Path(__file__).resolve().parents[2]
    default_out = (
        repo_root / "docs" / "diagnostics"
        / f"{date.today().isoformat()}-tiingo-benchmark-discovery.csv"
    )
    out_path = Path(args.out) if args.out else default_out
    limit = args.limit if args.limit > 0 else None

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    return asyncio.run(run(limit=limit, out_path=out_path))


if __name__ == "__main__":
    raise SystemExit(main())
