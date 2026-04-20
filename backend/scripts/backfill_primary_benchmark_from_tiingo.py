"""Production backfill of ``sec_registered_funds.primary_benchmark`` from
``instruments_universe.attributes->'tiingo_description'`` via regex +
canonical-map resolution.

Zero external API calls. All source data is already in TimescaleDB
(seeded by the tiingo CUSIP enrichment worker, PR-Q4/Q5 Fase 2.1).

Usage:
    python -m scripts.backfill_primary_benchmark_from_tiingo [--dry-run]
        [--force] [--limit N]

Flags:
    --dry-run   Compute the plan and print counts without persisting.
    --force     Overwrite rows that already have primary_benchmark set.
                Default skips them (idempotent re-run).
    --limit N   Cap scanned instruments at N (useful for smoke tests).

Operational notes:
- Processes rows in batches of 500 inside a single async session; each
  batch commits separately so a late failure doesn't blow away earlier
  progress.
- Emits one row per CIK into primary_benchmark_backfill_log with action
  ∈ (inserted, skipped_existing, unresolvable, no_match). ON CONFLICT
  on (cik, source) updates instead of inserting so re-runs stay clean.
- Regex patterns live in ``explore_tiingo_benchmarks`` (shared single
  source of truth). Source tag ``tiingo_description_regex_v1`` travels
  with every row for later version tracking.

PR-Q5.1 Phase A2.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import text

from app.core.db.engine import async_session_factory
from scripts.explore_tiingo_benchmarks import extract as _regex_extract

_SOURCE_TAG = "tiingo_description_regex_v1"
_BATCH_SIZE = 500


def _norm(value: str) -> str:
    """Canonical-map lookup key: strip symbols, collapse whitespace, lower."""
    value = (
        value
        .replace("®", "")
        .replace("™", "")
        .replace("\u2122", "")
        .replace("\u00ae", "")
    )
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


@dataclass(frozen=True)
class _Candidate:
    cik: str
    ticker: str | None
    description: str
    extracted_raw: str | None
    pattern_id: str | None
    resolved_canonical: str | None


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
        lookup[_norm(canonical)] = canonical
        for alias in aliases or []:
            lookup[_norm(alias)] = canonical
    return lookup


async def _load_existing_registered_ciks(
    session,
) -> dict[str, tuple[str, bool]]:
    """Return ``normalized_cik → (raw_cik_in_db, has_primary_benchmark)``.

    CIK padding differs across SEC tables (some 10-digit zero-padded,
    some unpadded). We key the dict on the unpadded form so matches
    survive the mismatch, but carry the DB's literal value so the
    UPDATE clause does not need to pad either side.
    """
    r = await session.execute(
        text("""
            SELECT cik, (primary_benchmark IS NOT NULL) AS has_benchmark
              FROM sec_registered_funds
        """)
    )
    out: dict[str, tuple[str, bool]] = {}
    for cik, has in r.fetchall():
        key = _normalize_cik(cik) or ""
        # If multiple rows share the normalized CIK (shouldn't in
        # registered_funds since CIK is PK, but defensive) prefer the
        # one already with a benchmark.
        prev = out.get(key)
        if prev is None or (not prev[1] and has):
            out[key] = (str(cik), bool(has))
    return out


def _normalize_cik(cik: str | None) -> str | None:
    if cik is None:
        return None
    stripped = str(cik).lstrip("0")
    return stripped or "0"


def candidate_key(candidate: _Candidate) -> str:
    return _normalize_cik(candidate.cik) or candidate.cik


async def _load_candidates(session, limit: int | None) -> list[_Candidate]:
    sql = """
        SELECT
            attributes->>'sec_cik'           AS cik,
            ticker                           AS ticker,
            attributes->>'tiingo_description' AS description
        FROM instruments_universe
        WHERE attributes->>'tiingo_description' IS NOT NULL
          AND attributes->>'sec_cik' IS NOT NULL
    """
    if limit:
        sql += f"\n        LIMIT {int(limit)}"
    r = await session.execute(text(sql))
    return [_Candidate(
        cik=_normalize_cik(row["cik"]) or "",
        ticker=row["ticker"],
        description=row["description"] or "",
        extracted_raw=None,
        pattern_id=None,
        resolved_canonical=None,
    ) for row in r.mappings().all() if row["cik"]]


def _classify(
    candidate: _Candidate,
    alias_lookup: dict[str, str],
    registered_funds: dict[str, tuple[str, bool]],
    force: bool,
) -> tuple[str, _Candidate]:
    # Always run the regex so the audit log records what the extractor
    # found, even for non-registered CIKs (ETF / BDC / MMF / private).
    pid, extracted = _regex_extract(candidate.description)
    canonical = alias_lookup.get(_norm(extracted)) if extracted else None

    registered_entry = registered_funds.get(candidate.cik)
    # Use the literal DB value for the subsequent UPDATE so padding
    # differences do not bite.
    db_cik = registered_entry[0] if registered_entry else candidate.cik
    has_existing = registered_entry[1] if registered_entry else False

    enriched = _Candidate(
        cik=db_cik,
        ticker=candidate.ticker,
        description=candidate.description,
        extracted_raw=extracted,
        pattern_id=pid,
        resolved_canonical=canonical,
    )

    # Only sec_registered_funds (mutual_fund + closed_end) has the
    # primary_benchmark column. Anything else stays a no_match — its
    # extraction is logged for future use but nothing is written.
    if registered_entry is None:
        return "no_match", enriched
    if extracted is None:
        return "no_match", enriched
    if canonical is None:
        return "unresolvable", enriched
    if has_existing and not force:
        return "skipped_existing", enriched
    return "inserted", enriched


async def _apply_batch(
    session,
    action: str,
    rows: list[_Candidate],
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
        for c in rows:
            await session.execute(
                update_sql,
                {"canonical": c.resolved_canonical, "cik": c.cik, "force": force},
            )

    log_sql = text("""
        INSERT INTO primary_benchmark_backfill_log (
            cik, ticker, description_snippet, extracted_raw,
            resolved_canonical, pattern_id, source, action
        ) VALUES (
            :cik, :ticker, :snippet, :extracted,
            :canonical, :pattern, :source, :action
        )
        ON CONFLICT (cik, source) DO UPDATE
            SET ticker              = EXCLUDED.ticker,
                description_snippet = EXCLUDED.description_snippet,
                extracted_raw       = EXCLUDED.extracted_raw,
                resolved_canonical  = EXCLUDED.resolved_canonical,
                pattern_id          = EXCLUDED.pattern_id,
                action              = EXCLUDED.action,
                created_at          = now()
    """)
    for c in rows:
        snippet = (c.description or "")[:400].replace("\x00", "")
        await session.execute(
            log_sql,
            {
                "cik": c.cik,
                "ticker": c.ticker,
                "snippet": snippet,
                "extracted": c.extracted_raw,
                "canonical": c.resolved_canonical,
                "pattern": c.pattern_id,
                "source": _SOURCE_TAG,
                "action": action,
            },
        )


async def run(*, dry_run: bool, force: bool, limit: int | None) -> int:
    async with async_session_factory() as session:
        alias_lookup = await _load_alias_lookup(session)
        registered = await _load_existing_registered_ciks(session)
        candidates = await _load_candidates(session, limit)

    existing_benchmark_count = sum(1 for _cik, has in registered.values() if has)
    print(f"alias lookup entries    : {len(alias_lookup)}")
    print(f"registered funds loaded : {len(registered)}"
          f"  (with benchmark: {existing_benchmark_count})")
    print(f"candidate rows (share classes) : {len(candidates)}")

    # Dedupe by normalized CIK. Multiple share classes of a fund each
    # have their own instruments_universe row + tiingo_description; we
    # only UPDATE sec_registered_funds once per CIK and only emit one
    # audit-log row per CIK. Priority: inserted > skipped_existing >
    # unresolvable > no_match (collapse on the "best" outcome so the
    # audit log reflects the strongest signal available for that CIK).
    by_cik: dict[str, tuple[str, _Candidate]] = {}
    _priority = {"inserted": 0, "skipped_existing": 1, "unresolvable": 2, "no_match": 3}
    for cand in candidates:
        action, enriched = _classify(cand, alias_lookup, registered, force)
        prev = by_cik.get(candidate_key(cand))
        if prev is None or _priority[action] < _priority[prev[0]]:
            by_cik[candidate_key(cand)] = (action, enriched)

    planned: dict[str, list[_Candidate]] = {
        "inserted": [], "skipped_existing": [],
        "unresolvable": [], "no_match": [],
    }
    for action, enriched in by_cik.values():
        planned[action].append(enriched)
    print(f"unique CIKs after dedupe       : {len(by_cik)}")

    action_counts = Counter({k: len(v) for k, v in planned.items()})
    print("\nplanned actions:")
    for k in ("inserted", "skipped_existing", "unresolvable", "no_match"):
        print(f"  {k:<18} {action_counts[k]:>6}")

    pattern_counts = Counter(
        c.pattern_id for c in planned["inserted"] if c.pattern_id
    )
    if pattern_counts:
        print("\npattern_id breakdown (inserted):")
        for pid, cnt in pattern_counts.most_common():
            print(f"  {pid:<20} {cnt:>5}")

    canonical_counts = Counter(
        c.resolved_canonical for c in planned["inserted"] if c.resolved_canonical
    )
    if canonical_counts:
        print("\ntop canonical benchmarks (inserted):")
        for name, cnt in canonical_counts.most_common(15):
            print(f"  {cnt:>4}  {name}")

    if dry_run:
        print("\n[dry-run] no writes performed.")
        return 0

    # Persist in batches. Each action-group committed separately.
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

    print("\nbackfill complete.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without persisting.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing primary_benchmark values.")
    p.add_argument("--limit", type=int, default=0,
                   help="Scan only N candidates (0 = all).")
    args = p.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    return asyncio.run(run(
        dry_run=args.dry_run,
        force=args.force,
        limit=args.limit if args.limit > 0 else None,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
