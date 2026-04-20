"""Backfill ``sec_registered_funds.primary_benchmark`` from SEC Financial
Statement Data Sets (FSDS) RR-1 Q1 2025 slice.

Reads two local TSVs from the operator's EDGAR mirror:

    E:\\EDGAR FILES\\Tickers\\sub.tsv   (adsh -> cik mapping)
    E:\\EDGAR FILES\\Tickers\\lab.tsv   (XBRL Member labels per filing)

Benchmark Member rows (dimensional labels referencing a benchmark
provider) are parsed, normalized, and resolved against
``benchmark_etf_canonical_map`` (expanded by migration 0168 to 92 rows /
700+ aliases). Matched CIKs whose ``primary_benchmark`` is NULL get
populated; every row processed lands in
``primary_benchmark_backfill_log`` with source tag
``fsds_q1_2025_rr1_v1``.

Zero external API calls. Single-pass streaming read of lab.tsv
(~1.5M lines) with bounded memory via dict-of-set aggregation keyed on
normalized CIK.

Usage::

    python -m scripts.backfill_primary_benchmark_from_rr1 [--dry-run]
        [--force] [--labels-dir PATH]

Flags:
    --dry-run     Compute the plan and print counts without persisting.
    --force       Overwrite rows that already have primary_benchmark set.
                  Default is idempotent (skipped_existing).
    --labels-dir  Override the default RR-1 TSV directory.

PR-Q5.1.3 Phase B.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from app.core.db.engine import async_session_factory

_SOURCE_TAG = "fsds_q1_2025_rr1_v1"
_DEFAULT_LABELS_DIR = Path(r"E:\EDGAR FILES\Tickers")
_BATCH_SIZE = 500

# Matches any benchmark provider token. Restricted to institutional
# providers to keep false-positive rate low — informal or fund-family
# indices are deliberately excluded.
_PROVIDER_RE = re.compile(
    r"\b(S&P|Russell|MSCI|Bloomberg|FTSE|Nasdaq|Dow Jones|Wilshire|CRSP|"
    r"ICE|BofA|Barclays|Citigroup|JPMorgan|JP Morgan|NASDAQ|NYSE|LBMA|"
    r"BBG|STOXX|NIKKEI|TOPIX|Lipper|Morningstar|Refinitiv|Reuters)\b",
    re.IGNORECASE,
)
_FUND_RE = re.compile(r"\bFund\b", re.IGNORECASE)
_INDEX_RE = re.compile(r"\bindex\b", re.IGNORECASE)


def _clean_label(label: str) -> str:
    """Strip XBRL decorators like ``[Member]`` and collapse whitespace."""
    label = re.sub(r"\[[^\]]+\]", "", label).strip()
    label = re.sub(r"\s+", " ", label)
    return label


def _is_benchmark_label(tag: str, label: str) -> bool:
    if not label or len(label) < 10 or len(label) > 250:
        return False
    if "Member" not in tag:
        return False
    if not _PROVIDER_RE.search(label):
        return False
    if not _INDEX_RE.search(label):
        return False
    if _FUND_RE.search(label):
        return False
    return True


def _norm_lookup(value: str) -> str:
    """Canonical-map lookup key: strip symbols, collapse whitespace, lower."""
    value = (
        value
        .replace("\u00ae", "")
        .replace("\u2122", "")
        .replace("\u00a0", " ")
    )
    # Collapse SEC disclosure boilerplate that varies across prospectuses.
    value = re.sub(
        r"\s*\(reflects\s+no\s+deduct(?:ions?|s)\s+for[^)]*\)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s*\(net of[^)]+\)", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def _normalize_cik(cik: str | None) -> str | None:
    if cik is None:
        return None
    stripped = str(cik).lstrip("0")
    return stripped or "0"


@dataclass(frozen=True)
class _Resolution:
    cik: str
    db_cik: str
    raw_label: str
    resolved_canonical: str | None
    has_existing_benchmark: bool


async def _load_alias_lookup(session) -> dict[str, str]:
    """Build ``normalized_alias -> canonical_name`` from the full map."""
    r = await session.execute(
        text("""
            SELECT benchmark_name_canonical, benchmark_name_aliases
              FROM benchmark_etf_canonical_map
             WHERE effective_to = '9999-12-31'
        """)
    )
    lookup: dict[str, str] = {}
    for canonical, aliases in r.fetchall():
        lookup[_norm_lookup(canonical)] = canonical
        for alias in aliases or []:
            lookup[_norm_lookup(alias)] = canonical
    return lookup


async def _load_registered_ciks(session) -> dict[str, tuple[str, bool]]:
    """Return ``normalized_cik -> (db_raw_cik, has_primary_benchmark)``."""
    r = await session.execute(
        text("""
            SELECT cik, (primary_benchmark IS NOT NULL) AS has_benchmark
              FROM sec_registered_funds
        """)
    )
    out: dict[str, tuple[str, bool]] = {}
    for cik, has in r.fetchall():
        key = _normalize_cik(cik) or ""
        prev = out.get(key)
        if prev is None or (not prev[1] and has):
            out[key] = (str(cik), bool(has))
    return out


def _parse_sub_tsv(path: Path) -> dict[str, str]:
    """Parse ``sub.tsv`` -> ``adsh -> normalized_cik`` mapping."""
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        adsh_idx = header.index("adsh")
        cik_idx = header.index("cik")
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(adsh_idx, cik_idx):
                continue
            adsh = parts[adsh_idx]
            cik = parts[cik_idx]
            if adsh and cik:
                mapping[adsh] = _normalize_cik(cik) or ""
    return mapping


def _scan_lab_tsv(
    path: Path, adsh_to_cik: dict[str, str]
) -> tuple[dict[str, set[str]], int, int]:
    """Stream-scan ``lab.tsv`` -> ``cik -> {raw_benchmark_label}``.

    Returns ``(cik_to_benchmarks, total_members_scanned, benchmark_hits)``.
    """
    cik_to_benchmarks: dict[str, set[str]] = defaultdict(set)
    total_members = 0
    benchmark_hits = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        _header = f.readline()
        # Fixed column order (SEC FSDS schema):
        #   adsh tag version std terse verbose total negated negatedTerse
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            adsh = parts[0]
            tag = parts[1]
            if "Member" not in tag:
                continue
            total_members += 1
            cik = adsh_to_cik.get(adsh)
            if not cik:
                continue
            # Try std -> terse -> verbose, take first matching label.
            for idx in (3, 4, 5):
                if idx >= len(parts):
                    continue
                label = parts[idx]
                if _is_benchmark_label(tag, label):
                    cleaned = _clean_label(label)
                    cik_to_benchmarks[cik].add(cleaned)
                    benchmark_hits += 1
                    break
    return cik_to_benchmarks, total_members, benchmark_hits


def _resolve(
    cik_to_benchmarks: dict[str, set[str]],
    alias_lookup: dict[str, str],
    registered: dict[str, tuple[str, bool]],
) -> list[_Resolution]:
    """For each CIK, pick the best resolvable benchmark (first wins by
    sort order for determinism). Non-registered CIKs are dropped — this
    script writes only to ``sec_registered_funds``.
    """
    resolutions: list[_Resolution] = []
    for cik, labels in cik_to_benchmarks.items():
        reg = registered.get(cik)
        if reg is None:
            continue
        db_cik, has_existing = reg
        # Deterministic order: shortest-first inside sorted, so the
        # cleanest label wins when multiple resolve to the same canonical.
        best_canonical: str | None = None
        best_raw: str | None = None
        for label in sorted(labels, key=lambda s: (len(s), s)):
            canonical = alias_lookup.get(_norm_lookup(label))
            if canonical is not None:
                best_canonical = canonical
                best_raw = label
                break
        resolutions.append(_Resolution(
            cik=cik,
            db_cik=db_cik,
            raw_label=best_raw or (sorted(labels)[0] if labels else ""),
            resolved_canonical=best_canonical,
            has_existing_benchmark=has_existing,
        ))
    return resolutions


def _classify(resolution: _Resolution, force: bool) -> str:
    if resolution.resolved_canonical is None:
        return "unresolvable"
    if resolution.has_existing_benchmark and not force:
        return "skipped_existing"
    return "inserted"


async def _apply_batch(
    session,
    action: str,
    rows: list[_Resolution],
    *,
    force: bool,
) -> None:
    if not rows:
        return
    if action == "inserted":
        update_sql = text("""
            UPDATE sec_registered_funds
               SET primary_benchmark = :canonical
             WHERE cik = :cik
               AND (:force OR primary_benchmark IS NULL)
        """)
        for r in rows:
            await session.execute(
                update_sql,
                {
                    "canonical": r.resolved_canonical,
                    "cik": r.db_cik,
                    "force": force,
                },
            )

    log_sql = text("""
        INSERT INTO primary_benchmark_backfill_log (
            cik, ticker, description_snippet, extracted_raw,
            resolved_canonical, pattern_id, source, action
        ) VALUES (
            :cik, NULL, NULL, :extracted,
            :canonical, 'fsds_rr1_member', :source, :action
        )
        ON CONFLICT (cik, source) DO UPDATE
            SET extracted_raw      = EXCLUDED.extracted_raw,
                resolved_canonical = EXCLUDED.resolved_canonical,
                pattern_id         = EXCLUDED.pattern_id,
                action             = EXCLUDED.action,
                created_at         = now()
    """)
    for r in rows:
        await session.execute(
            log_sql,
            {
                "cik": r.db_cik,
                "extracted": (r.raw_label or "")[:400],
                "canonical": r.resolved_canonical,
                "source": _SOURCE_TAG,
                "action": action,
            },
        )


async def run(
    *,
    dry_run: bool,
    force: bool,
    labels_dir: Path,
) -> int:
    sub_path = labels_dir / "sub.tsv"
    lab_path = labels_dir / "lab.tsv"
    if not sub_path.exists():
        print(f"missing input file: {sub_path}", file=sys.stderr)
        return 2
    if not lab_path.exists():
        print(f"missing input file: {lab_path}", file=sys.stderr)
        return 2

    print(f"[rr1] reading {sub_path} ...")
    adsh_to_cik = _parse_sub_tsv(sub_path)
    print(f"  filings (adsh -> cik) : {len(adsh_to_cik):,}")

    print(f"[rr1] streaming {lab_path} ...")
    cik_to_benchmarks, total_members, hits = _scan_lab_tsv(lab_path, adsh_to_cik)
    print(f"  *Member rows scanned  : {total_members:,}")
    print(f"  benchmark label hits  : {hits:,}")
    print(f"  unique CIKs with bench: {len(cik_to_benchmarks):,}")

    async with async_session_factory() as session:
        alias_lookup = await _load_alias_lookup(session)
        registered = await _load_registered_ciks(session)

    mf_total = len(registered)
    mf_with_bench_pre = sum(1 for _cik, has in registered.values() if has)
    print(f"  registered funds      : {mf_total:,}")
    print(f"  with benchmark (pre)  : {mf_with_bench_pre:,} "
          f"({100 * mf_with_bench_pre / mf_total:.1f}%)")
    print(f"  alias lookup entries  : {len(alias_lookup):,}")

    resolutions = _resolve(cik_to_benchmarks, alias_lookup, registered)
    print(f"  resolvable against DB : {len(resolutions):,}")

    planned: dict[str, list[_Resolution]] = {
        "inserted": [], "skipped_existing": [], "unresolvable": [],
    }
    for r in resolutions:
        planned[_classify(r, force)].append(r)

    counts = Counter({k: len(v) for k, v in planned.items()})
    print("\nplanned actions:")
    for k in ("inserted", "skipped_existing", "unresolvable"):
        print(f"  {k:<18} {counts[k]:>6}")

    top_canonicals = Counter(
        r.resolved_canonical for r in planned["inserted"] if r.resolved_canonical
    )
    if top_canonicals:
        print("\ntop canonicals (inserted):")
        for name, cnt in top_canonicals.most_common(15):
            print(f"  {cnt:>4}  {name}")

    projected = mf_with_bench_pre + counts["inserted"]
    print(
        f"\nprojected post-backfill MF coverage: {projected:,}/{mf_total:,} "
        f"= {100 * projected / mf_total:.2f}%"
    )

    if dry_run:
        print("\n[dry-run] no writes performed.")
        return 0

    async with async_session_factory() as session:
        for action, rows in planned.items():
            for start in range(0, len(rows), _BATCH_SIZE):
                chunk = rows[start:start + _BATCH_SIZE]
                try:
                    await _apply_batch(session, action, chunk, force=force)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                print(f"  persisted {action:<18} "
                      f"{min(start + len(chunk), len(rows)):>6} / {len(rows)}")

    # Post-apply coverage verification.
    async with async_session_factory() as session:
        r = await session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE primary_benchmark IS NOT NULL),
                COUNT(*)
              FROM sec_registered_funds
        """))
        with_bench, total = r.fetchone()
    print(
        f"\npost-apply DB coverage: {with_bench:,}/{total:,} "
        f"= {100 * with_bench / total:.2f}%"
    )

    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without persisting.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing primary_benchmark values.")
    p.add_argument("--labels-dir", type=Path, default=_DEFAULT_LABELS_DIR,
                   help="Directory containing sub.tsv and lab.tsv.")
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    return asyncio.run(run(
        dry_run=args.dry_run,
        force=args.force,
        labels_dir=args.labels_dir,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
