"""Backfill ``sec_registered_funds.primary_benchmark`` from the full
SEC FSDS RR-1 historical archive.

Scales Q5.1.3's single-quarter backfill to walk a directory tree of
``YYYYQQ_rr1/`` folders, each containing ``sub.tsv`` + ``lab.tsv``.
Labels are aggregated per normalized CIK across all quarters and
resolved once against the expanded ``benchmark_etf_canonical_map``.

Design rationale:
- A fund that changed benchmark (e.g. Bloomberg -> S&P) will surface
  both in the aggregated set. Resolution order (shortest-first inside
  sorted) picks the cleanest canonical match.
- Older prospectuses use pre-rebrand aliases (e.g. "Barclays US Agg"
  before 2016, "Bloomberg US Agg" after). Alias map already handles
  both; aggregation lets either quarter win.
- Labels observed in a later quarter take precedence indirectly: once
  the canonical resolver picks any match, the winning canonical name
  is used. Ties broken by length/lex order for determinism.

Usage::

    python -m scripts.backfill_primary_benchmark_from_fsds_history \
        [--dry-run] [--force] [--root PATH] [--quarters PATTERN]

Flags:
    --dry-run      Print plan without writes.
    --force        Overwrite rows with existing primary_benchmark.
    --root PATH    Directory containing ``YYYYQQ_rr1`` subdirs.
                   Default ``E:\\EDGAR FILES\\RR1``.
    --quarters     Glob over quarter directory names (default ``*_rr1``).

Inputs (zero API calls):
    <root>/2016q4_rr1/sub.tsv + lab.tsv
    <root>/2017q1_rr1/sub.tsv + lab.tsv
    ... through whatever the operator's mirror has ...

PR-Q5.2.
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

_SOURCE_TAG = "fsds_history_v1"
_DEFAULT_ROOT = Path(r"E:\EDGAR FILES\RR1")
_BATCH_SIZE = 500

_PROVIDER_RE = re.compile(
    r"\b(S&P|Russell|MSCI|Bloomberg|FTSE|Nasdaq|Dow Jones|Wilshire|CRSP|"
    r"ICE|BofA|Barclays|Citigroup|JPMorgan|JP Morgan|NASDAQ|NYSE|LBMA|"
    r"BBG|STOXX|NIKKEI|TOPIX|Lipper|Morningstar|Refinitiv|Reuters)\b",
    re.IGNORECASE,
)
_FUND_RE = re.compile(r"\bFund\b", re.IGNORECASE)
_INDEX_RE = re.compile(r"\bindex\b", re.IGNORECASE)


def _clean_label(label: str) -> str:
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
    value = (
        value
        .replace("\u00ae", "")
        .replace("\u2122", "")
        .replace("\u00a0", " ")
    )
    # Strip SEC disclosure boilerplate in *any* parenthetical form.
    # Observed variants across 2016-2025 RR-1 slices:
    #   "(reflects no deduction for fees ...)"
    #   "(no deduction for fees, expenses or taxes)"
    #   "(index reflects no deduction ...)"
    #   "(returns do not reflect deductions ...)"
    #   "Index Return (reflects no deduction ...)"
    value = re.sub(
        r"\s*\((?:index\s+)?(?:reflects\s+)?no\s+deduct(?:ions?|s)\s+for[^)]*\)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\s*\(returns\s+do\s+not\s+reflect[^)]*\)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s*\(net\s+of[^)]+\)", "", value, flags=re.IGNORECASE)
    # Trailing "Index Return" / "Total Return Index" collapses to "Index"
    # for lookup purposes only.
    value = re.sub(r"\bindex\s+return\b", "index", value, flags=re.IGNORECASE)
    value = re.sub(r"\btotal\s+return\s+index\b", "index", value,
                   flags=re.IGNORECASE)
    value = re.sub(r"\b-?nr\b", "", value, flags=re.IGNORECASE)
    # Space-separated "U S" / "US" / "U.S." all collapse to "us".
    value = re.sub(r"\bu\s*\.?\s*s\s*\.?\b", "us", value, flags=re.IGNORECASE)
    # "Bloomberg Barclays" was the name pre-Aug-2021; treat as plain
    # Bloomberg for lookup purposes so pre-rebrand prospectuses resolve.
    value = re.sub(r"\bbloomberg\s+barclays\b", "bloomberg",
                   value, flags=re.IGNORECASE)
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


def _parse_sub_tsv(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
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
    except (OSError, ValueError) as exc:
        print(f"  [warn] {path}: {exc}", file=sys.stderr)
    return mapping


def _scan_lab_tsv(
    path: Path,
    adsh_to_cik: dict[str, str],
    accumulator: dict[str, set[str]],
) -> tuple[int, int]:
    """Append benchmark labels into ``accumulator`` in-place.

    Returns ``(total_members_scanned, benchmark_hits)`` for this file.
    """
    total_members = 0
    benchmark_hits = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            _header = f.readline()
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
                for idx in (3, 4, 5):
                    if idx >= len(parts):
                        continue
                    label = parts[idx]
                    if _is_benchmark_label(tag, label):
                        accumulator[cik].add(_clean_label(label))
                        benchmark_hits += 1
                        break
    except (OSError, ValueError) as exc:
        print(f"  [warn] {path}: {exc}", file=sys.stderr)
    return total_members, benchmark_hits


def _ingest_history(
    root: Path, pattern: str
) -> tuple[dict[str, set[str]], list[dict[str, int | str]]]:
    """Walk ``<root>/<pattern>/`` and aggregate benchmark labels per CIK."""
    cik_to_benchmarks: dict[str, set[str]] = defaultdict(set)
    per_quarter: list[dict[str, int | str]] = []

    quarter_dirs = sorted(p for p in root.glob(pattern) if p.is_dir())
    if not quarter_dirs:
        print(f"[fsds-history] no quarter dirs matched {root / pattern}",
              file=sys.stderr)
        return cik_to_benchmarks, per_quarter

    print(f"[fsds-history] processing {len(quarter_dirs)} quarter(s)")
    for qdir in quarter_dirs:
        sub_path = qdir / "sub.tsv"
        lab_path = qdir / "lab.tsv"
        if not (sub_path.exists() and lab_path.exists()):
            print(f"  [skip] {qdir.name}: missing sub.tsv or lab.tsv")
            continue
        adsh_to_cik = _parse_sub_tsv(sub_path)
        members, hits = _scan_lab_tsv(lab_path, adsh_to_cik, cik_to_benchmarks)
        per_quarter.append({
            "quarter": qdir.name,
            "filings": len(adsh_to_cik),
            "members": members,
            "hits": hits,
        })
        print(
            f"  {qdir.name:<15} filings={len(adsh_to_cik):>5,}  "
            f"members={members:>7,}  hits={hits:>6,}"
        )

    return cik_to_benchmarks, per_quarter


async def _load_alias_lookup(session) -> dict[str, str]:
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
    r = await session.execute(
        text("""
            SELECT cik, (primary_benchmark IS NOT NULL) AS has_benchmark
              FROM sec_registered_funds
             WHERE fund_type = 'mutual_fund'
        """)
    )
    out: dict[str, tuple[str, bool]] = {}
    for cik, has in r.fetchall():
        key = _normalize_cik(cik) or ""
        prev = out.get(key)
        if prev is None or (not prev[1] and has):
            out[key] = (str(cik), bool(has))
    return out


def _resolve(
    cik_to_benchmarks: dict[str, set[str]],
    alias_lookup: dict[str, str],
    registered: dict[str, tuple[str, bool]],
) -> tuple[list[_Resolution], Counter[str]]:
    """Returns ``(resolutions, unresolvable_label_freq)``.

    ``unresolvable_label_freq`` aggregates labels that parsed as a
    benchmark but did not match any canonical alias — primary input for
    the next canonical_map expansion sprint.
    """
    resolutions: list[_Resolution] = []
    unresolvable: Counter[str] = Counter()
    for cik, labels in cik_to_benchmarks.items():
        reg = registered.get(cik)
        if reg is None:
            continue
        db_cik, has_existing = reg
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
        if best_canonical is None:
            for label in labels:
                unresolvable[_clean_label(label)] += 1
    return resolutions, unresolvable


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
            await session.execute(update_sql, {
                "canonical": r.resolved_canonical,
                "cik": r.db_cik,
                "force": force,
            })

    log_sql = text("""
        INSERT INTO primary_benchmark_backfill_log (
            cik, ticker, description_snippet, extracted_raw,
            resolved_canonical, pattern_id, source, action
        ) VALUES (
            :cik, NULL, NULL, :extracted,
            :canonical, 'fsds_history_member', :source, :action
        )
        ON CONFLICT (cik, source) DO UPDATE
            SET extracted_raw      = EXCLUDED.extracted_raw,
                resolved_canonical = EXCLUDED.resolved_canonical,
                pattern_id         = EXCLUDED.pattern_id,
                action             = EXCLUDED.action,
                created_at         = now()
    """)
    for r in rows:
        await session.execute(log_sql, {
            "cik": r.db_cik,
            "extracted": (r.raw_label or "")[:400],
            "canonical": r.resolved_canonical,
            "source": _SOURCE_TAG,
            "action": action,
        })


def _dump_unresolvable(path: Path, freq: Counter[str], top: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("count,label\n")
        for label, cnt in freq.most_common(top):
            safe = label.replace('"', '""')
            f.write(f'{cnt},"{safe}"\n')


async def run(
    *,
    dry_run: bool,
    force: bool,
    root: Path,
    pattern: str,
    unresolvable_dump: Path | None,
) -> int:
    if not root.exists():
        print(f"root not found: {root}", file=sys.stderr)
        return 2

    cik_to_benchmarks, per_quarter = _ingest_history(root, pattern)
    if not cik_to_benchmarks:
        print("no benchmarks extracted; aborting", file=sys.stderr)
        return 1

    print(f"\n[fsds-history] aggregated unique CIKs with benchmark labels: "
          f"{len(cik_to_benchmarks):,}")
    total_labels = sum(len(v) for v in cik_to_benchmarks.values())
    print(f"[fsds-history] total distinct (cik,label) tuples: {total_labels:,}")

    async with async_session_factory() as session:
        alias_lookup = await _load_alias_lookup(session)
        registered = await _load_registered_ciks(session)

    mf_total = len(registered)
    mf_with_bench_pre = sum(1 for _cik, has in registered.values() if has)
    print(f"[fsds-history] MF registered funds: {mf_total:,}")
    print(f"[fsds-history] with benchmark (pre): {mf_with_bench_pre:,} "
          f"({100 * mf_with_bench_pre / mf_total:.2f}%)")
    print(f"[fsds-history] alias lookup entries: {len(alias_lookup):,}")

    resolutions, unresolvable_freq = _resolve(
        cik_to_benchmarks, alias_lookup, registered
    )
    print(f"[fsds-history] MF CIKs covered by FSDS labels: {len(resolutions):,}")

    planned: dict[str, list[_Resolution]] = {
        "inserted": [], "skipped_existing": [], "unresolvable": [],
    }
    for r in resolutions:
        planned[_classify(r, force)].append(r)

    counts = Counter({k: len(v) for k, v in planned.items()})
    print("\nplanned actions:")
    for k in ("inserted", "skipped_existing", "unresolvable"):
        print(f"  {k:<18} {counts[k]:>6}")

    top_canon = Counter(
        r.resolved_canonical for r in planned["inserted"] if r.resolved_canonical
    )
    print("\ntop canonicals (inserted):")
    for name, cnt in top_canon.most_common(20):
        print(f"  {cnt:>5}  {name}")

    projected = mf_with_bench_pre + counts["inserted"]
    print(
        f"\nprojected MF coverage: {projected:,}/{mf_total:,} "
        f"= {100 * projected / mf_total:.2f}%"
    )

    if unresolvable_dump is not None and unresolvable_freq:
        _dump_unresolvable(unresolvable_dump, unresolvable_freq, top=500)
        print(f"[fsds-history] unresolvable labels dumped -> {unresolvable_dump}")

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

    async with async_session_factory() as session:
        coverage_result = await session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE primary_benchmark IS NOT NULL),
                COUNT(*)
              FROM sec_registered_funds
             WHERE fund_type = 'mutual_fund'
        """))
        row = coverage_result.fetchone()
        assert row is not None
        with_bench, total = row
    print(
        f"\npost-apply MF coverage: {with_bench:,}/{total:,} "
        f"= {100 * with_bench / total:.2f}%"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    p.add_argument("--quarters", default="*_rr1",
                   help="Glob over quarter subdirs (default '*_rr1').")
    p.add_argument("--dump-unresolvable", type=Path, default=None,
                   help="CSV path to dump top-500 unresolvable labels "
                        "(feeds the next canonical_map expansion).")
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    return asyncio.run(run(
        dry_run=args.dry_run,
        force=args.force,
        root=args.root,
        pattern=args.quarters,
        unresolvable_dump=args.dump_unresolvable,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
