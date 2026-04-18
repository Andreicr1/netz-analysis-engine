# PR-A26.0 — Block Coverage Validator: Query by `strategy_label`, not `block_id`

**Date**: 2026-04-18
**Status**: P0 BUG FIX — pre-requisite for PR-A26.1 (propose mode). Very small, no schema, no migration.
**Branch**: `feat/pr-a26-0-coverage-validator-fix`
**Predecessors merged**: A21 #207, A22 #209, A23 #210, A24 #212, A25 #213.
**Downstream blocker:** PR #214 (A26.1 draft, paused) — will resume after this merges.

---

## Context — the bug

A22's `validate_block_coverage` produces false-negative gaps. Dev DB evidence (org `403d8392-...`, 2026-04-18):

| Block | Validator reports | Actually approved in org |
|---|---|---|
| `na_equity_growth` | 0 | **77** (65 Large Growth + 12 Mid Growth) |
| `na_equity_value` | 0 | **46** (37 Large Value + 9 Mid Value) |
| `alt_commodities` | 0 | **50** ("Commodities" label) |

**Root cause.** The validator queries `instruments_org.block_id = :block_id` to count candidates. But `instruments_org.block_id` is a **lossy single-block cache** produced by the classifier at import time: each instrument gets ONE block_id even when its strategy label maps to multiple blocks. Example: VUG has `strategy_label = 'Large Growth'`, which `block_mapping.py` maps to `['na_equity_large', 'na_equity_growth']`. The classifier picks the first — `na_equity_large` — and writes that to `instruments_org`. VUG is now invisible to the validator when counting `na_equity_growth` candidates, even though it's a perfectly valid candidate for that block.

`candidate_screener.py` (used at composition/realize) already handles this correctly: it queries `instruments_universe` filtered by `strategy_label IN (labels for block)`. The validator is the only consumer still reading the lossy `block_id` cache as source of truth.

**Consequence.** Operator sees false blockers. A22 gate fires `block_coverage_insufficient` on profiles that actually have full coverage. PR-A26.1 propose mode would inherit the same false negative — propose runs would abort before the optimizer ever sees the problem.

---

## Scope

**In scope:**
- Rewrite `_APPROVED_COUNT_SQL` in `backend/quant_engine/block_coverage_service.py` to count via strategy_label join instead of block_id equality.
- Match the exact query pattern already used by `candidate_screener.py` (which is the source-of-truth consumer at composition time).
- Update the 6 existing unit tests in `backend/tests/quant_engine/test_block_coverage_service.py` so their fixtures seed instruments via strategy_label rather than block_id.
- Add one new integration test that reproduces the dev-DB scenario: create instruments with "Commodities" label classified into `na_equity_large` (wrong block_id) in `instruments_org`, assert validator correctly surfaces them as `alt_commodities` candidates.

**Out of scope:**
- Do NOT touch `instruments_org.block_id` — leave it as a (now officially) derived/advisory field. PR-A26.1 + A26.2 will evolve its role further; this PR only fixes the validator consumer.
- Do NOT run the A23 reclassification script. The block_id drift will persist in DB; the validator just stops trusting it.
- Do NOT modify `candidate_screener.py`, `block_mapping.py`, optimizer, or any other module.
- Do NOT add a migration — no schema change.
- Do NOT extend `BlockCoverageGap` / `CoverageReport` schemas.
- Do NOT touch the frontend.

---

## Execution Spec

### Section A — Validator query fix

**File:** `backend/quant_engine/block_coverage_service.py`

Current `_APPROVED_COUNT_SQL`:
```sql
SELECT COUNT(*)
  FROM instruments_org
 WHERE organization_id = :organization_id
   AND block_id = :block_id
   AND approval_status = 'approved'
```

Replace with:
```sql
SELECT COUNT(*)
  FROM instruments_org io
  JOIN instruments_universe iu
    ON iu.instrument_id = io.instrument_id
 WHERE io.organization_id = :organization_id
   AND io.approval_status = 'approved'
   AND iu.is_active = TRUE
   AND iu.attributes->>'strategy_label' = ANY(CAST(:labels AS text[]))
```

The `is_active` filter matches `_CATALOG_COUNT_SQL`'s filter — org-approved but inactive (delisted) instruments should not count as coverage.

The query uses `:labels` now. Update `_count_approved()` signature:
```python
async def _count_approved(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    labels: list[str],
) -> int:
    if not labels:
        return 0
    row = await db.execute(
        _APPROVED_COUNT_SQL,
        {"organization_id": organization_id, "labels": labels},
    )
    return int(row.scalar_one() or 0)
```

Update `validate_block_coverage()` to compute `labels = strategy_labels_for_block(block_id)` ONCE per iteration, pass to both `_count_approved` and `_catalog_snapshot`. If `labels` is empty (block has no label mapping — rare edge case), treat as 0 candidates (same as catalog helper).

**Preserve semantics:**
- Return shape unchanged (`CoverageReport` + `BlockCoverageGap` unchanged).
- "Is sufficient" logic unchanged — still based on per-block `n_candidates > 0`.
- Rationale / example_tickers / catalog_candidates_available fields unchanged.

### Section B — Update existing unit tests

**File:** `backend/tests/quant_engine/test_block_coverage_service.py`

Current tests seed rows directly with `block_id`. Update each fixture to seed via `instruments_universe.attributes.strategy_label` + a matching `instruments_org` row (with any `block_id` or NULL — no longer the source of truth).

6 tests to update:
1. `test_all_blocks_covered_returns_sufficient` — seed ≥1 instrument per canonical block via strategy_label.
2. `test_uncovered_block_with_catalog_candidates` — seed catalog instruments with label X, do NOT add them to instruments_org for the target org. Validator reports gap + catalog_candidates_available matching seed count.
3. `test_uncovered_block_with_no_catalog_candidates` — no instruments in catalog with the block's labels. Gap reported, catalog_candidates_available=0, example_tickers=[].
4. `test_multiple_blocks_mixed_coverage` — mixed: some blocks have approved instruments (via label), some don't. Validator reports only the missing ones.
5. `test_empty_strategic_allocation_is_sufficient` — unchanged semantics: no allocation → is_sufficient=True.
6. `test_build_coverage_operator_message_shape` — unchanged semantics; fixture adjustments only.

Each test must assert the validator's output count matches the underlying strategy_label-based data, not the block_id.

### Section C — New regression test

**File:** same test file, add one new test:

```python
async def test_block_id_drift_does_not_hide_candidates(async_session):
    """Instruments classified into a wrong block_id due to classifier
    single-pick are still correctly counted when their strategy_label
    maps to the expected block. Reproduces the dev-DB Commodities-in-
    na_equity_large case.
    """
    ...
```

Seed:
- 3 instruments in `instruments_universe` with `strategy_label = 'Commodities'`, `is_active = true`, `is_institutional = true`.
- Seed all 3 in `instruments_org` for the target org with `block_id = 'na_equity_large'` (wrong!) and `approval_status = 'approved'`.
- Seed `strategic_allocation` for the profile with `block_id = 'alt_commodities'`, `target_weight = 0.05`.

Assert:
- `validate_block_coverage(...).is_sufficient == True` for alt_commodities (the 3 instruments are correctly surfaced via label despite the wrong block_id cache).
- No gap reported for `alt_commodities`.

### Global guardrails

- `CLAUDE.md` rules. Async-first, RLS via `SET LOCAL`, `expire_on_commit=False`, `lazy="raise"`.
- No new Python dependencies. No new migration. No schema change.
- `make check` green (tolerate pre-existing lint per `feedback_dev_first_ci_later.md`).
- 3 commits: A (SQL + function signature), B (existing test updates), C (new regression test).
- Keep the change SMALL — this is a surgical fix, not a refactor. If you find yourself touching >30 lines in `block_coverage_service.py`, stop and narrow the scope.

## Final report format

1. Diff summary: `block_coverage_service.py` lines changed, tests lines changed.
2. Unit test output (`pytest backend/tests/quant_engine/test_block_coverage_service.py -v`): all 7 tests pass (6 updated + 1 new).
3. Dev DB smoke validator output:
   - Run `validate_block_coverage(db, org_id='403d8392-...', profile='moderate')` against local dev DB.
   - Expected post-fix: `is_sufficient=True` OR much smaller `total_target_weight_at_risk` than the 19.79% reported pre-fix. Paste the full CoverageReport JSON.
4. Regression: run A22 integration test (`test_construction_run_coverage_gate.py`) — expect no regression.
5. Regression: run A25 template test — expect no regression.
6. List deviations from spec (should be none for a query fix this small).
