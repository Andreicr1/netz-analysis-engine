"""PR-A23 — classifier audit (read-only).

Identifies three classes of classifier defects without mutating data:

* **D1** — ``strategy_label`` mismatches in ``instruments_universe`` for
  the tickers listed in ``CANONICAL_REFERENCE``.
* **D2** — ``block_id`` mismatches in ``instruments_org`` for those same
  tickers (rows where the stored block differs from the canonical one).
* **D3** — fallback bucket contamination: rows living in
  ``fi_us_aggregate`` / ``na_equity_large`` whose canonical block is
  different (e.g. VTEB that should be muni, EFA that should be foreign
  developed equity).

Emits a JSON report on stdout and a human-readable summary on stderr.
Always exits 0 — safe to chain into CI without gating.

Usage::

    python -m backend.scripts.pr_a23_classifier_audit
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts._pr_a23_canonical_reference import CANONICAL_REFERENCE


_STRATEGY_MISMATCH_SQL = text(
    """
    SELECT iu.ticker,
           iu.attributes->>'strategy_label' AS current_label,
           COUNT(*) AS n_rows_in_universe
      FROM instruments_universe iu
     WHERE iu.ticker = ANY(:tickers)
     GROUP BY iu.ticker, iu.attributes->>'strategy_label'
     ORDER BY iu.ticker
    """
)

_BLOCK_MISMATCH_SQL = text(
    """
    SELECT io.organization_id::text AS organization_id,
           iu.ticker,
           io.block_id AS current_block_id
      FROM instruments_org io
      JOIN instruments_universe iu USING (instrument_id)
     WHERE iu.ticker = ANY(:tickers)
     ORDER BY iu.ticker, io.organization_id
    """
)


async def _run() -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    tickers = sorted(CANONICAL_REFERENCE.keys())

    async with engine.connect() as conn:
        strategy_rows = (
            await conn.execute(_STRATEGY_MISMATCH_SQL, {"tickers": tickers})
        ).mappings().all()
        block_rows = (
            await conn.execute(_BLOCK_MISMATCH_SQL, {"tickers": tickers})
        ).mappings().all()

    await engine.dispose()

    strategy_mismatches: list[dict[str, Any]] = []
    universe_seen: dict[str, str | None] = {}
    for r in strategy_rows:
        ticker = r["ticker"]
        canonical_label, _ = CANONICAL_REFERENCE[ticker]
        current_label = r["current_label"]
        universe_seen[ticker] = current_label
        if current_label != canonical_label:
            strategy_mismatches.append({
                "ticker": ticker,
                "current_label": current_label,
                "canonical_label": canonical_label,
                "n_rows_in_universe": int(r["n_rows_in_universe"]),
            })

    tickers_missing_from_universe = [
        t for t in tickers if t not in universe_seen
    ]

    block_mismatches: list[dict[str, Any]] = []
    contamination: dict[str, list[dict[str, Any]]] = {}
    for r in block_rows:
        ticker = r["ticker"]
        current_block = r["current_block_id"]
        _, canonical_block = CANONICAL_REFERENCE[ticker]
        if current_block == canonical_block:
            continue
        entry = {
            "ticker": ticker,
            "organization_id": r["organization_id"],
            "current_block_id": current_block,
            "canonical_block_id": (
                canonical_block if canonical_block is not None else "needs_review"
            ),
        }
        block_mismatches.append(entry)
        # Aggregate contamination by the CURRENT (wrong) bucket.
        if current_block is not None:
            contamination.setdefault(current_block, []).append({
                "ticker": ticker,
                "canonical_block": (
                    canonical_block if canonical_block is not None
                    else "needs_review (muni unresolved)"
                ),
            })

    return {
        "canonical_reference_size": len(CANONICAL_REFERENCE),
        "strategy_label_mismatches": strategy_mismatches,
        "tickers_missing_from_instruments_universe": tickers_missing_from_universe,
        "block_id_mismatches_in_instruments_org": block_mismatches,
        "fallback_bucket_contamination": contamination,
        "summary": {
            "strategy_mismatches": len(strategy_mismatches),
            "block_mismatches": len(block_mismatches),
            "tickers_missing": len(tickers_missing_from_universe),
            "contaminated_buckets": list(contamination.keys()),
        },
    }


def _print_human_summary(report: dict[str, Any]) -> None:
    s = report["summary"]
    print("── PR-A23 classifier audit ──", file=sys.stderr)
    print(
        f"  canonical tickers checked: {report['canonical_reference_size']}",
        file=sys.stderr,
    )
    print(
        f"  strategy_label mismatches: {s['strategy_mismatches']}",
        file=sys.stderr,
    )
    print(f"  block_id mismatches:       {s['block_mismatches']}", file=sys.stderr)
    print(f"  tickers missing:           {s['tickers_missing']}", file=sys.stderr)
    if s["contaminated_buckets"]:
        print(
            f"  contaminated buckets:      {', '.join(s['contaminated_buckets'])}",
            file=sys.stderr,
        )


def main() -> int:
    report = asyncio.run(_run())
    print(json.dumps(report, indent=2, default=str))
    _print_human_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
