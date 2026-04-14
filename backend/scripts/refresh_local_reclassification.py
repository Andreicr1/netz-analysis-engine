"""Refresh local fund reclassification without re-running ingestion.

Usage
-----
    python backend/scripts/refresh_local_reclassification.py

Prerequisites
-------------
- PR #169 (classifier patches round 1) merged.
- Local DB populated (no SEC/ESMA/Tiingo ingestion required).
- Tiingo enrichment already run (``instruments_universe.attributes
  ->> 'tiingo_description'`` populated).

Output
------
- New ``run_id`` written to ``strategy_reclassification_stage``.
- Structured stdout report: per-source counts, cascade layer
  distribution, diff-severity distribution, PR #169 patch validation
  counts, top 20 proposed labels, and random samples of ``lost_class``
  and ``fallback`` rows for manual review.

Writes are staging-only — production ``strategy_label`` columns are
never touched.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.workers import strategy_reclassification

log = logging.getLogger(__name__)

# Reference only — reported in commentary. Comes from a Cloud run that
# predates the local DB refresh, so numbers are not directly comparable.
PREVIOUS_CLOUD_RUN_ID = UUID("3a966438-5b32-42f7-8556-f4b8d119ef11")

SOURCE_TABLES: tuple[str, ...] = (
    "instruments_universe",
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "esma_funds",
)


async def _count_table(db: Any, table: str) -> int:
    # Table name is validated against SOURCE_TABLES whitelist, safe to inline.
    r = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
    return int(r.scalar() or 0)


async def _layer_distribution(db: Any, run_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT source_table,
               classification_source,
               confidence,
               COUNT(*) AS n
          FROM strategy_reclassification_stage
         WHERE run_id = :run_id
      GROUP BY source_table, classification_source, confidence
      ORDER BY source_table, classification_source, confidence
        """
    )
    r = await db.execute(stmt, {"run_id": run_id})
    return [dict(row._mapping) for row in r]


async def _severity_distribution(db: Any, run_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT source_table,
               COUNT(*) FILTER (
                   WHERE current_strategy_label IS NOT DISTINCT FROM proposed_strategy_label
               ) AS unchanged,
               COUNT(*) FILTER (
                   WHERE current_strategy_label IS NULL
                     AND proposed_strategy_label IS NOT NULL
               ) AS new_classification,
               COUNT(*) FILTER (
                   WHERE current_strategy_label IS NOT NULL
                     AND proposed_strategy_label IS NULL
               ) AS lost_class,
               COUNT(*) FILTER (
                   WHERE current_strategy_label IS NOT NULL
                     AND proposed_strategy_label IS NOT NULL
                     AND current_strategy_label <> proposed_strategy_label
               ) AS changed,
               COUNT(*) AS total
          FROM strategy_reclassification_stage
         WHERE run_id = :run_id
      GROUP BY source_table
      ORDER BY source_table
        """
    )
    r = await db.execute(stmt, {"run_id": run_id})
    return [dict(row._mapping) for row in r]


async def _top_proposed_labels(
    db: Any, run_id: UUID, limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT proposed_strategy_label,
               COUNT(*) AS n
          FROM strategy_reclassification_stage
         WHERE run_id = :run_id
           AND proposed_strategy_label IS NOT NULL
      GROUP BY proposed_strategy_label
      ORDER BY n DESC
         LIMIT :limit
        """
    )
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def _patch_specific_counts(db: Any, run_id: UUID) -> dict[str, int]:
    stmt = text(
        """
        SELECT COUNT(*) FILTER (WHERE proposed_strategy_label = 'Municipal Bond')
                 AS municipal,
               COUNT(*) FILTER (WHERE proposed_strategy_label = 'Government Bond')
                 AS government,
               COUNT(*) FILTER (WHERE proposed_strategy_label = 'Structured Credit')
                 AS structured_credit,
               COUNT(*) FILTER (WHERE proposed_strategy_label = 'Infrastructure')
                 AS infrastructure,
               COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_secondaries%')
                 AS pe_secondaries,
               COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_coinvest%')
                 AS pe_coinvest,
               COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_growth%')
                 AS pe_growth,
               COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_infra%')
                 AS pe_infra,
               COUNT(*) FILTER (WHERE matched_pattern LIKE '%style_only%')
                 AS style_only_defaults,
               COUNT(*) FILTER (WHERE matched_pattern = 'name:hedge_generic')
                 AS hedge_generic,
               COUNT(*) FILTER (WHERE proposed_strategy_label IS NOT NULL)
                 AS total_classified
          FROM strategy_reclassification_stage
         WHERE run_id = :run_id
        """
    )
    r = await db.execute(stmt, {"run_id": run_id})
    row = r.one()
    return {k: int(v or 0) for k, v in row._mapping.items()}


async def _lost_class_samples(
    db: Any, run_id: UUID, limit: int = 30,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT source_table,
               source_pk,
               fund_name,
               current_strategy_label,
               classification_source
          FROM strategy_reclassification_stage
         WHERE run_id = :run_id
           AND current_strategy_label IS NOT NULL
           AND proposed_strategy_label IS NULL
      ORDER BY RANDOM()
         LIMIT :limit
        """
    )
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def _fallback_samples(
    db: Any, run_id: UUID, limit: int = 30,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT s.source_table,
               s.source_pk,
               s.fund_name,
               s.fund_type,
               LEFT(
                   COALESCE(
                       (
                           SELECT iu.attributes ->> 'tiingo_description'
                             FROM instruments_universe iu
                            WHERE iu.instrument_id::text = s.source_pk
                            LIMIT 1
                       ),
                       ''
                   ),
                   200
               ) AS tiingo_desc_sample
          FROM strategy_reclassification_stage s
         WHERE s.run_id = :run_id
           AND s.classification_source = 'fallback'
      ORDER BY RANDOM()
         LIMIT :limit
        """
    )
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def _most_recent_run_id(db: Any) -> UUID | None:
    stmt = text(
        """
        SELECT run_id
          FROM strategy_reclassification_stage
      GROUP BY run_id
      ORDER BY MAX(classified_at) DESC
         LIMIT 1
        """
    )
    r = await db.execute(stmt)
    row = r.first()
    return row[0] if row else None


async def main() -> None:
    started = datetime.now(UTC)
    print(f"\n=== LOCAL RECLASSIFICATION REFRESH ({started.isoformat()}) ===\n")

    # Step 1 — baseline source counts.
    print("STEP 1 — Baseline source table counts")
    async with async_session() as db:
        baseline = {t: await _count_table(db, t) for t in SOURCE_TABLES}
    for t, n in baseline.items():
        print(f"  {t:<25} {n:>10,}")
    print(f"  {'TOTAL':<25} {sum(baseline.values()):>10,}\n")

    # Step 2 — run the classifier worker.
    print("STEP 2 — Running strategy_reclassification worker")
    result = await strategy_reclassification.run_strategy_reclassification()
    totals = result.get("totals", {})
    print(
        f"  candidates={totals.get('candidates', 0):,}  "
        f"staged={totals.get('staged', 0):,}  "
        f"fallback={totals.get('fallback', 0):,}"
    )
    print(f"  run_id={result.get('run_id')}\n")

    # Step 3 — confirm run_id via stage table.
    async with async_session() as db:
        new_run_id = await _most_recent_run_id(db)
    if new_run_id is None:
        print("ERROR: no run_id found in stage table after worker run")
        sys.exit(1)
    print(f"STEP 3 — Authoritative run_id: {new_run_id}")
    print(f"         Previous Cloud run_id (reference): {PREVIOUS_CLOUD_RUN_ID}\n")

    # Step 4 — cascade layer distribution.
    print("STEP 4 — Cascade layer distribution per source")
    async with async_session() as db:
        layers = await _layer_distribution(db, new_run_id)
    print(
        f"  {'source_table':<25} {'classification_source':<22} "
        f"{'confidence':<10} {'n':>10}"
    )
    for row in layers:
        print(
            f"  {row['source_table']:<25} "
            f"{row['classification_source']:<22} "
            f"{row['confidence']:<10} "
            f"{row['n']:>10,}"
        )
    print()

    # Step 5 — diff severity distribution.
    print("STEP 5 — Diff severity distribution per source")
    print(
        f"  {'source_table':<25} {'unchanged':>10} {'new':>10} "
        f"{'lost':>10} {'changed':>10} {'total':>10}"
    )
    async with async_session() as db:
        severities = await _severity_distribution(db, new_run_id)
    total_lost = total_new = total_changed = total_unchanged = total_rows = 0
    for row in severities:
        print(
            f"  {row['source_table']:<25} "
            f"{row['unchanged']:>10,} "
            f"{row['new_classification']:>10,} "
            f"{row['lost_class']:>10,} "
            f"{row['changed']:>10,} "
            f"{row['total']:>10,}"
        )
        total_unchanged += row["unchanged"]
        total_new += row["new_classification"]
        total_lost += row["lost_class"]
        total_changed += row["changed"]
        total_rows += row["total"]
    print(
        f"  {'TOTAL':<25} "
        f"{total_unchanged:>10,} "
        f"{total_new:>10,} "
        f"{total_lost:>10,} "
        f"{total_changed:>10,} "
        f"{total_rows:>10,}"
    )
    print(
        "  (Cloud baseline lost_class was 14,178 — reference only, "
        "different DB snapshot.)\n"
    )

    # Step 6 — PR #169 patch validation.
    print("STEP 6 — PR #169 patch validation")
    async with async_session() as db:
        patches = await _patch_specific_counts(db, new_run_id)
    for k, v in patches.items():
        print(f"  {k:<22} {v:>10,}")
    print()

    # Step 7 — top proposed labels.
    print("STEP 7 — Top 20 proposed labels")
    async with async_session() as db:
        tops = await _top_proposed_labels(db, new_run_id)
    for row in tops:
        print(f"  {row['proposed_strategy_label']:<30} {row['n']:>10,}")
    print()

    # Step 8 — lost_class samples.
    print("STEP 8 — Random sample of lost_class funds (current → NULL)")
    async with async_session() as db:
        lost = await _lost_class_samples(db, new_run_id)
    for row in lost[:15]:
        name = (row.get("fund_name") or "?")[:60]
        print(
            f"  [{row['source_table']:<22}] {name:<60} "
            f"was: {row['current_strategy_label']}"
        )
    if len(lost) > 15:
        print(f"  (... {len(lost) - 15} more samples available)\n")
    else:
        print()

    # Step 9 — fallback samples.
    print("STEP 9 — Random sample of fallback funds (round 2 / Phase 4 candidates)")
    async with async_session() as db:
        fallback = await _fallback_samples(db, new_run_id)
    for row in fallback[:15]:
        name = (row.get("fund_name") or "?")[:50]
        desc = (row.get("tiingo_desc_sample") or "").strip()
        desc_hint = f" | desc: {desc[:80]}" if desc else ""
        print(
            f"  [{row['source_table']:<22}] {name:<50} "
            f"type: {row.get('fund_type') or '?'}{desc_hint}"
        )
    if len(fallback) > 15:
        print(f"  (... {len(fallback) - 15} more samples available)\n")
    else:
        print()

    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"=== REFRESH COMPLETE in {elapsed:.1f}s ===\n")
    print("Next steps:")
    print(
        "  1. Inspect stage table: "
        f"SELECT * FROM strategy_reclassification_stage "
        f"WHERE run_id = '{new_run_id}' LIMIT 100;"
    )
    print("  2. If numbers calibrated, proceed to Session B (apply gate).")
    print("  3. If regressions remain, identify patterns → round 2 patches.")


if __name__ == "__main__":
    # Windows consoles default to cp1252 which cannot encode em-dashes or
    # arrows used in the report headers. Force UTF-8 on stdout/stderr.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
