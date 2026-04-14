# Local Fund Reclassification Refresh — Opcao C (no external ingestion)

**Date:** 2026-04-14
**Branch:** `fix/local-reclassification-refresh`
**Sessions:** 1
**Depends on:** PR #169 merged (classifier patches round 1)

---

## Context

The previous staging run_id (`3a966438-5b32-42f7-8556-f4b8d119ef11`) came from Timescale Cloud which is outdated vs the local dev DB. That run showed `lost_class = 14,178` against a stale snapshot. Local DB is currently well-populated and is the authoritative snapshot for iterating on classifier quality.

We do NOT want to run the external-facing workers now (sec_bulk_ingestion, sec_adv_ingestion, esma_ingestion) — they depend on SEC/ESMA APIs and take 1-1.5h combined. Local DB already has the data needed.

We do NOT need to re-run tiingo_enrichment — it already completed (99.96% coverage in `instruments_universe.attributes.tiingo_description`).

The only action needed is re-running `run_strategy_reclassification()` with the PR #169 patches applied. This writes a new run_id to the staging table and becomes the authoritative "local baseline" for Session B.

---

## OBJECTIVE

1. Run `run_strategy_reclassification()` against the local DB with PR #169 patches applied.
2. Generate a validation report comparing the new run_id against the previous Cloud-based run_id, isolating patch impact vs data-source differences.
3. Produce a concrete severity distribution to calibrate Session B's apply gate.

---

## CONSTRAINTS

- **No ingestion workers run.** No SEC, ESMA, Tiingo, or other external-facing fetches.
- **Read-only on production columns.** Worker writes to `strategy_reclassification_stage` only; zero writes to `strategy_label` on source tables.
- **Preserve historical run_ids.** The old Cloud run_id stays in the staging table as a reference. New run_id is created fresh.
- **Pure validation.** No schema changes, no new tables, no new workers.

---

## DELIVERABLES

### 1. Create `backend/scripts/refresh_local_reclassification.py`

A script that:
1. Captures baseline counts from all 5 source tables
2. Runs `run_strategy_reclassification()` to generate new run_id
3. Queries the stage table for per-source layer distribution
4. Queries the stage table for severity distribution
5. Compares against the old Cloud run_id (`3a966438-5b32-42f7-8556-f4b8d119ef11`) where possible
6. Emits a structured report to stdout

```python
"""Refresh local fund reclassification without re-running ingestion.

Usage:
    python backend/scripts/refresh_local_reclassification.py

Prerequisites:
    - PR #169 (classifier patches round 1) merged
    - Local DB populated (no ingestion needed)
    - Tiingo enrichment already run (tiingo_description populated)

Output:
    - New run_id written to strategy_reclassification_stage
    - Structured report: layer distribution, severity distribution, 
      comparison to previous Cloud run_id.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.db import async_session
from app.domains.wealth.workers import strategy_reclassification

log = logging.getLogger(__name__)

PREVIOUS_CLOUD_RUN_ID = UUID("3a966438-5b32-42f7-8556-f4b8d119ef11")

SOURCE_TABLES = [
    "instruments_universe",
    "sec_manager_funds",
    "sec_registered_funds",
    "sec_etfs",
    "esma_funds",
]


async def _count_table(db, table: str) -> int:
    r = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
    return r.scalar() or 0


async def _layer_distribution(db, run_id: UUID) -> list[dict[str, Any]]:
    """Per-source cascade layer hit rates."""
    stmt = text("""
        SELECT 
            source_table,
            classification_source,
            confidence,
            COUNT(*) AS n
        FROM strategy_reclassification_stage
        WHERE run_id = :run_id
        GROUP BY source_table, classification_source, confidence
        ORDER BY source_table, classification_source
    """)
    r = await db.execute(stmt, {"run_id": run_id})
    return [dict(row._mapping) for row in r]


async def _severity_distribution(db, run_id: UUID) -> list[dict[str, Any]]:
    """Diff severity per source.

    Categories:
      - unchanged: current == proposed (or both NULL)
      - new_classification: current IS NULL, proposed IS NOT NULL
      - lost_class: current IS NOT NULL, proposed IS NULL
      - changed: both non-null, different
    """
    stmt = text("""
        SELECT
            source_table,
            COUNT(*) FILTER (WHERE 
                current_strategy_label IS NOT DISTINCT FROM proposed_strategy_label
            ) AS unchanged,
            COUNT(*) FILTER (WHERE 
                current_strategy_label IS NULL AND proposed_strategy_label IS NOT NULL
            ) AS new_classification,
            COUNT(*) FILTER (WHERE 
                current_strategy_label IS NOT NULL AND proposed_strategy_label IS NULL
            ) AS lost_class,
            COUNT(*) FILTER (WHERE 
                current_strategy_label IS NOT NULL 
                AND proposed_strategy_label IS NOT NULL
                AND current_strategy_label != proposed_strategy_label
            ) AS changed,
            COUNT(*) AS total
        FROM strategy_reclassification_stage
        WHERE run_id = :run_id
        GROUP BY source_table
        ORDER BY source_table
    """)
    r = await db.execute(stmt, {"run_id": run_id})
    return [dict(row._mapping) for row in r]


async def _top_proposed_labels(db, run_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
    stmt = text("""
        SELECT 
            proposed_strategy_label, 
            COUNT(*) AS n
        FROM strategy_reclassification_stage
        WHERE run_id = :run_id
          AND proposed_strategy_label IS NOT NULL
        GROUP BY proposed_strategy_label
        ORDER BY n DESC
        LIMIT :limit
    """)
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def _patch_specific_counts(db, run_id: UUID) -> dict[str, int]:
    """Counts that validate PR #169 patches.

    - Municipal Bond (should increase with tax-free pattern)
    - Government Bond (should increase with expanded pattern)
    - Structured Credit (new label, expect > 0)
    - PE with lineage pe_secondaries/pe_coinvest/pe_growth/pe_infra
    """
    stmt = text("""
        SELECT 
            COUNT(*) FILTER (WHERE proposed_strategy_label = 'Municipal Bond') AS municipal,
            COUNT(*) FILTER (WHERE proposed_strategy_label = 'Government Bond') AS government,
            COUNT(*) FILTER (WHERE proposed_strategy_label = 'Structured Credit') AS structured_credit,
            COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_secondaries%') AS pe_secondaries,
            COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_coinvest%') AS pe_coinvest,
            COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_growth%') AS pe_growth,
            COUNT(*) FILTER (WHERE matched_pattern LIKE '%pe_infra%') AS pe_infra,
            COUNT(*) FILTER (WHERE matched_pattern LIKE '%style_only%') AS style_only_defaults,
            COUNT(*) FILTER (WHERE proposed_strategy_label IS NOT NULL) AS total_classified
        FROM strategy_reclassification_stage
        WHERE run_id = :run_id
    """)
    r = await db.execute(stmt, {"run_id": run_id})
    row = r.one()
    return dict(row._mapping)


async def _lost_class_samples(db, run_id: UUID, limit: int = 30) -> list[dict[str, Any]]:
    """Sample funds that LOST their label (current non-null → proposed NULL).

    These are the highest-severity diffs and need manual review.
    """
    stmt = text("""
        SELECT 
            source_table,
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
    """)
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def _fallback_samples(db, run_id: UUID, limit: int = 30) -> list[dict[str, Any]]:
    """Sample funds still in fallback (classification_source = 'fallback').

    Candidates for round 2 patches or Phase 4 N-PORT holdings classifier.
    """
    stmt = text("""
        SELECT 
            source_table,
            source_pk,
            fund_name,
            fund_type,
            LEFT(
                COALESCE(
                    (SELECT attributes->>'tiingo_description' 
                     FROM instruments_universe 
                     WHERE instrument_id::text = source_pk 
                     LIMIT 1), 
                    ''
                ), 
                200
            ) AS tiingo_desc_sample
        FROM strategy_reclassification_stage
        WHERE run_id = :run_id
          AND classification_source = 'fallback'
        ORDER BY RANDOM()
        LIMIT :limit
    """)
    r = await db.execute(stmt, {"run_id": run_id, "limit": limit})
    return [dict(row._mapping) for row in r]


async def main() -> None:
    started = datetime.now(timezone.utc)
    print(f"\n=== LOCAL RECLASSIFICATION REFRESH ({started.isoformat()}) ===\n")

    # Step 1: Baseline counts
    print("STEP 1 — Baseline source table counts")
    async with async_session() as db:
        baseline = {t: await _count_table(db, t) for t in SOURCE_TABLES}
    for t, n in baseline.items():
        print(f"  {t}: {n:,}")
    total = sum(baseline.values())
    print(f"  TOTAL: {total:,}\n")

    # Step 2: Run reclassification (generates new run_id)
    print("STEP 2 — Running strategy_reclassification worker")
    result = await strategy_reclassification.run_strategy_reclassification()
    print(f"  Result: {result}\n")

    # Step 3: Find the new run_id (most recent)
    async with async_session() as db:
        stmt = text("""
            SELECT run_id, MAX(classified_at) AS latest
            FROM strategy_reclassification_stage
            GROUP BY run_id
            ORDER BY latest DESC
            LIMIT 2
        """)
        r = await db.execute(stmt)
        runs = list(r)
    if not runs:
        print("ERROR: No run_id found in stage table after worker run")
        sys.exit(1)
    new_run_id = runs[0][0]
    print(f"STEP 3 — New run_id: {new_run_id}\n")

    # Step 4: Layer distribution
    print("STEP 4 — Cascade layer distribution per source")
    async with async_session() as db:
        layers = await _layer_distribution(db, new_run_id)
    for row in layers:
        print(f"  {row['source_table']:<25} {row['classification_source']:<25} "
              f"{row['confidence']:<10} {row['n']:>8,}")
    print()

    # Step 5: Severity distribution
    print("STEP 5 — Diff severity distribution per source")
    print(f"  {'source_table':<25} {'unchanged':>10} {'new':>10} {'lost':>10} "
          f"{'changed':>10} {'total':>10}")
    async with async_session() as db:
        severities = await _severity_distribution(db, new_run_id)
    total_lost = 0
    total_new = 0
    total_changed = 0
    for row in severities:
        print(f"  {row['source_table']:<25} {row['unchanged']:>10,} "
              f"{row['new_classification']:>10,} {row['lost_class']:>10,} "
              f"{row['changed']:>10,} {row['total']:>10,}")
        total_lost += row["lost_class"]
        total_new += row["new_classification"]
        total_changed += row["changed"]
    print(f"\n  TOTAL lost_class:         {total_lost:,}")
    print(f"  TOTAL new_classification: {total_new:,}")
    print(f"  TOTAL changed:            {total_changed:,}")
    print(f"  (Previous Cloud baseline lost_class: 14,178 — for reference, not comparable)\n")

    # Step 6: Patch-specific counts
    print("STEP 6 — PR #169 patch validation")
    async with async_session() as db:
        patches = await _patch_specific_counts(db, new_run_id)
    for k, v in patches.items():
        print(f"  {k}: {v:,}")
    print()

    # Step 7: Top proposed labels
    print("STEP 7 — Top 20 proposed labels (sanity check)")
    async with async_session() as db:
        tops = await _top_proposed_labels(db, new_run_id)
    for row in tops:
        print(f"  {row['proposed_strategy_label']:<30} {row['n']:>8,}")
    print()

    # Step 8: Lost-class samples
    print("STEP 8 — Random sample of lost_class funds (current → NULL)")
    async with async_session() as db:
        lost = await _lost_class_samples(db, new_run_id)
    for row in lost[:15]:  # Show 15 for readability
        print(f"  [{row['source_table']}] {row['fund_name'][:60]:<60} "
              f"was: {row['current_strategy_label']}")
    print(f"  (... {len(lost)-15} more in DB)\n" if len(lost) > 15 else "")

    # Step 9: Fallback samples
    print("STEP 9 — Random sample of fallback funds (candidates for round 2)")
    async with async_session() as db:
        fallback = await _fallback_samples(db, new_run_id)
    for row in fallback[:15]:
        desc = (row.get("tiingo_desc_sample") or "").strip()
        desc_hint = f" | desc: {desc[:80]}" if desc else ""
        print(f"  [{row['source_table']}] {(row['fund_name'] or '?')[:50]:<50} "
              f"type: {row.get('fund_type') or '?'}{desc_hint}")
    print(f"  (... {len(fallback)-15} more in DB)\n" if len(fallback) > 15 else "")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\n=== REFRESH COMPLETE in {elapsed:.1f}s ===")
    print(f"\nNext steps:")
    print(f"  1. Inspect the full stage table with:")
    print(f"     SELECT * FROM strategy_reclassification_stage WHERE run_id = '{new_run_id}' LIMIT 100;")
    print(f"  2. If numbers look calibrated, proceed to Session B (diff gate + apply script)")
    print(f"  3. If regressions remain, identify patterns and do round 2 patches")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(main())
```

### 2. Add entry to `backend/Makefile` or document the invocation

Optional: add a Make target for repeatability:

```makefile
# Refresh local reclassification stage (no external ingestion)
.PHONY: refresh-reclass
refresh-reclass:
	cd backend && python scripts/refresh_local_reclassification.py
```

---

## VERIFICATION

1. `make lint` passes.
2. `make typecheck` passes.
3. Script runs to completion with no exceptions.
4. New run_id exists in `strategy_reclassification_stage`.
5. Old Cloud run_id (`3a966438-5b32-42f7-8556-f4b8d119ef11`) preserved.
6. Structured Credit count > 0 (validates Patch 7).
7. Municipal Bond count increased vs baseline (validates Patch 2 — tax-free).
8. Government Bond count increased vs baseline (validates Patch 3).
9. `lost_class` count decreased vs 14,178 Cloud baseline (validates Patch 5 — hedge fallback).
10. `style_only_defaults` > 0 (validates Patch 6).

---

## INTERPRETING THE OUTPUT

**If `lost_class` is still > 5,000:**
- Investigate fallback samples to find common patterns
- Likely candidates for round 2: sector equity, ESG fixed income, more international variations

**If Structured Credit count is 0:**
- Check if local DB has CLO funds (query `sec_manager_funds` for `fund_name ILIKE '%clo%'`)
- If yes but classifier missed them, debug the pattern

**If Municipal Bond count did NOT increase vs baseline:**
- Check if tax-free funds exist in DB (query `WHERE fund_name ILIKE '%tax-free%'`)
- Possible explanation: local DB does not have as many tax-free funds as Cloud

**If `new_classification` (NULL → specific) dominates:**
- Great outcome. These are safe to auto-apply in Session B with no review.
- Define the auto-apply filter in Session B: `severity = 'new_classification' AND confidence IN ('high', 'medium')`.

**If `changed` (x → y) dominates:**
- Session B severity matrix becomes critical
- `asset_class_change` subset requires manual review per fund
- `style_refinement` subset (same family, e.g., Large Blend → Large Growth) can be auto-applied

---

## OUT OF SCOPE

- Running any external-facing ingestion worker (sec_bulk, sec_adv, esma, tiingo, benchmark, etc.)
- Modifying `strategy_classifier.py` (patches already in PR #169)
- Writing Session B apply script (that's the next sprint after this validation)
- Touching any production `strategy_label` column
- Schema changes

---

## AFTER THIS RUNS

The output of this script directly feeds into Session B's design:
- **Severity matrix calibration:** counts of new_classification vs lost_class vs changed inform the default `--severity` filter
- **Auto-apply threshold:** if high-confidence new_classification is safe and large, it becomes the default apply target
- **Round 2 patches:** fallback samples reveal the next iteration priorities
- **Taxonomy additions:** if many specific labels are missing (e.g., Structured Credit was added in this round), similar gaps may emerge

Report back with the script's output and we calibrate Session B's apply gate accordingly.
