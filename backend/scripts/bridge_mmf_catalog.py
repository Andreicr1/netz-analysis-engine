"""PR-A26.3.3 Section C — fuzzy bridge ``instruments_universe`` rows to
``sec_money_market_funds`` by tokenized fund-name similarity.

The A26.3.2 authoritative-first refresh bridges MMFs via
``attributes->>'series_id'``; only 44 of ~373 SEC MMFs have that bridge
populated. This script closes the gap using deterministic fuzzy matching
(see :mod:`app.domains.wealth.services.fuzzy_bridge`).

Tiers:

* score ≥ 0.85 **AND** :func:`verify_auto_match` passes → ``auto_applied``
  — writes ``sec_cik`` + ``sec_series_id`` into
  ``instruments_universe.attributes``; inserts audit row with
  ``applied_at = now()``.
* 0.70 ≤ score < 0.85 (or auto-match verification fails) →
  ``needs_review`` — insert audit row only; no catalog change.
* score < 0.70 → discard.

Pre-filter: only iu rows whose lowercased ``name`` contains one of
``money market | cash management | liquidity | government money |
prime obligations | tax-exempt | tax exempt`` are considered. Avoids
O(N×M) over the full catalog.

Idempotency: iu rows whose ``attributes->>'series_id'`` is already
populated AND maps to a real ``sec_money_market_funds.series_id`` are
excluded from the candidate set. Re-running the script after apply
produces zero new writes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.fuzzy_bridge import score, verify_auto_match

logger = logging.getLogger("bridge_mmf_catalog")

DEFAULT_AUTO_THRESHOLD = 0.85
DEFAULT_REVIEW_THRESHOLD = 0.70

# SQL ILIKE clauses for the pre-filter. Kept as a list so new patterns
# can be added without reshaping the query.
_MMF_NAME_HINTS: tuple[str, ...] = (
    "%money market%",
    "%cash management%",
    "%liquidity%",
    "%government money%",
    "%prime obligations%",
    "%tax-exempt%",
    "%tax exempt%",
    "%treasury only%",
    "%federal money%",
)


@dataclass(frozen=True)
class IuCandidate:
    instrument_id: str
    name: str
    current_series_id: str | None


@dataclass(frozen=True)
class SecMmfRow:
    series_id: str
    cik: str
    fund_name: str
    mmf_category: str


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


async def _load_iu_candidates(db: Any) -> list[IuCandidate]:
    hints = " OR ".join([f"name ILIKE :hint_{i}" for i in range(len(_MMF_NAME_HINTS))])
    params: dict[str, Any] = {
        f"hint_{i}": pattern for i, pattern in enumerate(_MMF_NAME_HINTS)
    }
    sql = text(
        f"""
        SELECT iu.instrument_id::text AS instrument_id,
               iu.name AS name,
               iu.attributes->>'series_id' AS series_id
        FROM instruments_universe AS iu
        WHERE iu.is_active = true
          AND iu.name IS NOT NULL
          AND ({hints})
          AND NOT EXISTS (
              SELECT 1 FROM sec_money_market_funds AS mmf
              WHERE mmf.series_id = iu.attributes->>'series_id'
          )
        """
    )
    result = await db.execute(sql, params)
    return [
        IuCandidate(
            instrument_id=row.instrument_id,
            name=row.name,
            current_series_id=row.series_id,
        )
        for row in result
    ]


async def _load_sec_mmfs(db: Any) -> list[SecMmfRow]:
    result = await db.execute(
        text(
            "SELECT series_id, cik, fund_name, mmf_category "
            "FROM sec_money_market_funds "
            "WHERE series_id IS NOT NULL AND fund_name IS NOT NULL"
        )
    )
    return [
        SecMmfRow(
            series_id=row.series_id,
            cik=row.cik,
            fund_name=row.fund_name,
            mmf_category=row.mmf_category or "",
        )
        for row in result
    ]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    iu: IuCandidate
    mmf: SecMmfRow
    score: float
    tier: str  # 'auto_applied' | 'needs_review'


def _classify_best(
    iu: IuCandidate,
    mmfs: list[SecMmfRow],
    *,
    auto_threshold: float,
    review_threshold: float,
) -> Match | None:
    best_score = 0.0
    best: SecMmfRow | None = None
    for mmf in mmfs:
        s = score(iu.name, mmf.fund_name)
        if s > best_score:
            best_score = s
            best = mmf
    if best is None or best_score < review_threshold:
        return None

    tier = "needs_review"
    if best_score >= auto_threshold:
        ok, _reason = verify_auto_match(iu.name, best.fund_name, best_score)
        tier = "auto_applied" if ok else "needs_review"
    return Match(iu=iu, mmf=best, score=best_score, tier=tier)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


_AUDIT_INSERT = text(
    """
    INSERT INTO sec_mmf_bridge_candidates (
        instrument_id, instrument_name,
        matched_cik, matched_series_id, matched_fund_name,
        score, match_tier, applied_at
    ) VALUES (
        :instrument_id, :instrument_name,
        :matched_cik, :matched_series_id, :matched_fund_name,
        :score, :match_tier, :applied_at
    )
    """
)

_IU_ATTRS_UPDATE = text(
    """
    UPDATE instruments_universe
    SET attributes = COALESCE(attributes, '{}'::jsonb) || jsonb_build_object(
        'sec_cik', CAST(:cik AS text),
        'sec_series_id', CAST(:series_id AS text),
        'series_id', CAST(:series_id AS text),
        'mmf_bridge_source', 'fuzzy_name_v1',
        'mmf_bridge_score', CAST(:score AS numeric),
        'mmf_bridge_at', CAST(:ts AS text)
    )
    WHERE instrument_id::text = :instrument_id
    """
)


async def _persist_match(
    db: Any, *, match: Match, apply: bool, ts: datetime,
) -> None:
    applied_at = ts if (apply and match.tier == "auto_applied") else None
    await db.execute(
        _AUDIT_INSERT,
        {
            "instrument_id": match.iu.instrument_id,
            "instrument_name": match.iu.name,
            "matched_cik": match.mmf.cik,
            "matched_series_id": match.mmf.series_id,
            "matched_fund_name": match.mmf.fund_name,
            "score": match.score,
            "match_tier": match.tier,
            "applied_at": applied_at,
        },
    )
    if apply and match.tier == "auto_applied":
        await db.execute(
            _IU_ATTRS_UPDATE,
            {
                "cik": match.mmf.cik,
                "series_id": match.mmf.series_id,
                "score": match.score,
                "ts": ts.isoformat(),
                "instrument_id": match.iu.instrument_id,
            },
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def run(
    *, apply: bool,
    auto_threshold: float = DEFAULT_AUTO_THRESHOLD,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
) -> dict[str, Any]:
    run_id = uuid4()
    ts = datetime.now(timezone.utc)
    counters: Counter[str] = Counter()
    auto_samples: list[dict[str, Any]] = []
    review_samples: list[dict[str, Any]] = []

    async with async_session_factory() as db:
        async with db.begin():
            iu_candidates = await _load_iu_candidates(db)
            mmfs = await _load_sec_mmfs(db)
            logger.info(
                "loaded iu_candidates=%d sec_mmfs=%d", len(iu_candidates), len(mmfs),
            )

            matches: list[Match] = []
            for iu in iu_candidates:
                m = _classify_best(
                    iu, mmfs,
                    auto_threshold=auto_threshold,
                    review_threshold=review_threshold,
                )
                if m is not None:
                    matches.append(m)
                    counters[m.tier] += 1

            for m in sorted(matches, key=lambda x: x.score, reverse=True):
                row = {
                    "iu_name": m.iu.name,
                    "sec_name": m.mmf.fund_name,
                    "series_id": m.mmf.series_id,
                    "cik": m.mmf.cik,
                    "score": m.score,
                }
                if m.tier == "auto_applied" and len(auto_samples) < 10:
                    auto_samples.append(row)
                elif m.tier == "needs_review" and len(review_samples) < 10:
                    review_samples.append(row)
                await _persist_match(db, match=m, apply=apply, ts=ts)

            if not apply:
                # Roll back any audit inserts performed during dry-run so
                # the table only reflects apply runs.
                await db.rollback()

    report = {
        "run_id": str(run_id),
        "dry_run": not apply,
        "candidates_scanned": len(iu_candidates),
        "sec_mmfs_loaded": len(mmfs),
        "auto_applied": counters["auto_applied"],
        "needs_review": counters["needs_review"],
        "auto_samples_top_10": auto_samples,
        "review_samples_top_10": review_samples,
    }
    return report


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 70)
    print(f"bridge_mmf_catalog — run_id={report['run_id']}")
    print(f"  dry_run={report['dry_run']}")
    print(f"  iu_candidates={report['candidates_scanned']}  "
          f"sec_mmfs={report['sec_mmfs_loaded']}")
    print(f"  auto_applied={report['auto_applied']}  "
          f"needs_review={report['needs_review']}")
    print()
    print("Top auto_applied matches:")
    for s in report["auto_samples_top_10"]:
        print(f"  [{s['score']:.3f}] {s['iu_name']!r} -> "
              f"{s['sec_name']!r}  ({s['series_id']})")
    print()
    print("Top needs_review matches:")
    for s in report["review_samples_top_10"]:
        print(f"  [{s['score']:.3f}] {s['iu_name']!r} -> "
              f"{s['sec_name']!r}  ({s['series_id']})")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run.")
    parser.add_argument(
        "--min-auto-score", type=float, default=DEFAULT_AUTO_THRESHOLD,
        help=f"Combined score needed for auto-apply (default {DEFAULT_AUTO_THRESHOLD}).",
    )
    parser.add_argument(
        "--min-review-score", type=float, default=DEFAULT_REVIEW_THRESHOLD,
        help=f"Combined score needed for needs_review tier (default {DEFAULT_REVIEW_THRESHOLD}).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the full JSON report in addition to summary.",
    )
    args = parser.parse_args()

    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = asyncio.run(
        run(
            apply=args.apply,
            auto_threshold=args.min_auto_score,
            review_threshold=args.min_review_score,
        )
    )
    _print_summary(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
