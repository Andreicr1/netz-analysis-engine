# PR-A25 — Canonical Allocation Template Schema + Taxonomy Normalization

**Date**: 2026-04-18
**Status**: P0 STRUCTURAL — introduces the canonical 18-block template that all profiles must share. Unblocks PR-A26 (propose-then-approve optimizer flow).
**Branch**: `feat/pr-a25-canonical-template-schema`
**Predecessors merged**: PR-A21 (#207), PR-A22 (#209), PR-A23 (#210), PR-A24 (#212), #211 (cleanup script).

---

## Context — product decision

Per product owner (Andrei, 2026-04-18):
> "Profiles devem ter exatamente os mesmos blocks — não é classe de ativo que define se o profile é mais ou menos conservador, mas o limite de risco."

Today the three profiles (`conservative`, `moderate`, `growth`) have **different block sets**: Conservative has 11 blocks, Moderate/Growth have 14. This is wrong — it conflates *risk tolerance* (profile) with *asset-class universe* (block set). The optimizer produces non-comparable outputs across profiles, attribution/drift/rebalance can't share taxonomy, and operator gaps propagate silently.

**The new architecture:**
- One canonical set of allocation blocks defined system-wide.
- Every `(org, profile)` must have `strategic_allocation` rows for every canonical block.
- Profiles differ only in `(target_weight, min_weight, max_weight, risk_budget)` per block, plus the profile-level CVaR limit stored in `portfolio_calibration`.
- Operator may set `excluded_from_portfolio = true` on a row to force zero exposure, without breaking template completeness.
- PR-A26 will add the propose-then-approve flow where the optimizer outputs bands given only CVaR + exclusions. This PR prepares the schema foundation.

---

## Canonical block set (18 blocks)

| Group | block_id | Notes |
|---|---|---|
| Equity US | `na_equity_large` | |
| | `na_equity_growth` | |
| | `na_equity_value` | |
| | `na_equity_small` | |
| Equity DM | `dm_europe_equity` | |
| | `dm_asia_equity` | |
| Equity EM | `em_equity` | |
| FI US | `fi_us_aggregate` | |
| | `fi_us_treasury` | |
| | **`fi_us_short_term`** | **NEW** (rename target of `fi_short_term`) |
| | `fi_us_high_yield` | |
| | `fi_us_tips` | **KEPT** — inflation hedge, portfolio sophistication |
| FI other | `fi_ig_corporate` | |
| | `fi_em_debt` | |
| Alt | `alt_real_estate` | |
| | `alt_gold` | |
| | `alt_commodities` | |
| Cash | `cash` | Money Market / Liquidity Fund only |

`fi_short_term` is renamed to `fi_us_short_term` (consistency with `fi_us_*` pattern, same refactor pattern as A21's `fi_govt → fi_us_treasury`). `fi_govt` (A21) remains retired.

Existing non-canonical block IDs in `allocation_blocks` (if any remain post-A21) must be flagged `is_canonical = false` and preserved for historical rows.

---

## Scope

**In scope:**
- `allocation_blocks.is_canonical` boolean column (default false). Seed migration marks the 18 canonical blocks.
- Rename `fi_short_term → fi_us_short_term` across all FK-dependent tables (`strategic_allocation`, `instruments_org`, `benchmark_nav`, `funds_universe`, `tactical_positions`, `blended_benchmark_components`, etc.). Same pattern as A21 migration 0149.
- `strategic_allocation.excluded_from_portfolio` boolean column (default false).
- `strategic_allocation` completeness: every `(org, profile)` must have rows for all canonical blocks. Backfill seed for canonical org `403d8392-...` with `(target=NULL, min=NULL, max=NULL, excluded_from_portfolio=false)` for missing rows.
- Postgres trigger `enforce_strategic_allocation_template`: fires on INSERT to `strategic_allocation` when a new `(org, profile)` combo appears, auto-inserts rows for every canonical block not yet present. Also fires on UPDATE of `allocation_blocks.is_canonical` to true, inserting rows for that block across all existing `(org, profile)` combos. Every auto-insert logs a row to a new `allocation_template_audit` table (`triggered_at, trigger_reason, organization_id, profile, block_id, action`).
- `validate_template_completeness(db, organization_id, profile) -> TemplateReport`: pure function in `backend/quant_engine/allocation_template_service.py`. Called in `construction_run_executor` **before** the A22 coverage gate. Fails the run with `winner_signal = 'template_incomplete'` if any canonical block is missing.
- `block_mapping.py` extensions: `Commodities`, `Commodities / Energy`, `Mid Growth`, `Mid Value`, `Short Government → fi_us_short_term`, `Ultrashort Bond → fi_us_short_term`. Keep `Inflation-Protected Bond → fi_us_tips`.
- `effective_to` bit-rot fix: migration sets `effective_to = NULL` on all existing `strategic_allocation` rows (12-day-stale seed in dev DB caused A22 validator to see empty allocation).
- `WinnerSignal.TEMPLATE_INCOMPLETE` enum value.
- Integration into coverage report payload: if template incomplete, gate short-circuits before coverage computation.
- Tests for trigger behavior, rename, completeness validator, excluded flag semantics, audit log population.

**Out of scope:**
- Do NOT implement the propose-then-approve flow. That is PR-A26.
- Do NOT compute or seed default `(target, min, max)` values per block — bands remain NULL until operator sets or optimizer proposes. This PR is schema-only.
- Do NOT modify the optimizer cascade. It will continue to read `(min, target, max)` and treat NULLs per its existing semantics (which may need A26-era adjustment, but not here).
- Do NOT touch `instruments_universe` ingestion, classifier, or N-PORT pipeline.
- Do NOT change `allocation_blocks` rows beyond adding `fi_us_short_term` and setting `is_canonical`. Old rows (fi_us_tips, etc.) stay — flagging only.
- Do NOT rename the profile values (`conservative`, `moderate`, `growth`). Product wording separate.

---

## Execution Spec

### Section A — Alembic migration 0153: canonical template schema

**File:** `backend/app/core/db/migrations/versions/0153_canonical_allocation_template.py`

Down_revision: `0152_exclude_muni_auto_import`.

Transactional. Steps in order:

1. **Add columns:**
   - `ALTER TABLE allocation_blocks ADD COLUMN is_canonical BOOLEAN NOT NULL DEFAULT false`.
   - `ALTER TABLE strategic_allocation ADD COLUMN excluded_from_portfolio BOOLEAN NOT NULL DEFAULT false`.

2. **Rename `fi_short_term → fi_us_short_term`:**
   Mirror the A21 pattern (migration 0149 `fi_govt → fi_us_treasury`):
   - If `allocation_blocks` has `fi_us_short_term` already, abort with clear error ("fi_us_short_term already exists as distinct block — manual reconciliation required"). Otherwise:
   - `UPDATE allocation_blocks SET block_id = 'fi_us_short_term' WHERE block_id = 'fi_short_term'` — but FK-dependent tables refer to the old id. Better pattern:
     1. `INSERT INTO allocation_blocks (block_id, ...) SELECT 'fi_us_short_term', ... FROM allocation_blocks WHERE block_id = 'fi_short_term'` — duplicate the row with new id.
     2. For each referencing table (`strategic_allocation`, `instruments_org`, `benchmark_nav`, `funds_universe`, `tactical_positions`, `blended_benchmark_components`, and any others surfaced by the referenced-by check at migration time), `UPDATE ... SET block_id = 'fi_us_short_term' WHERE block_id = 'fi_short_term'`. Log row counts per table.
     3. `DELETE FROM allocation_blocks WHERE block_id = 'fi_short_term'`.
   Use the same FK-discovery pattern as migration 0149 so any future tables are covered.

3. **Mark canonical set:**
   ```sql
   UPDATE allocation_blocks SET is_canonical = true
    WHERE block_id IN (
     'na_equity_large','na_equity_growth','na_equity_value','na_equity_small',
     'dm_europe_equity','dm_asia_equity','em_equity',
     'fi_us_aggregate','fi_us_treasury','fi_us_short_term','fi_us_high_yield','fi_us_tips',
     'fi_ig_corporate','fi_em_debt',
     'alt_real_estate','alt_gold','alt_commodities',
     'cash'
   );
   ```
   Assertion: `SELECT COUNT(*) FROM allocation_blocks WHERE is_canonical = true` must equal 18. If not, abort with list of missing IDs — means `allocation_blocks` is missing a canonical row that should be inserted inside this migration too.

4. **Fix effective_to bit-rot:**
   ```sql
   UPDATE strategic_allocation SET effective_to = NULL WHERE effective_to IS NOT NULL;
   ```
   Log row count affected.

5. **Create `allocation_template_audit` table:**
   ```sql
   CREATE TABLE allocation_template_audit (
     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
     triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
     trigger_reason TEXT NOT NULL,  -- 'new_profile_created', 'block_marked_canonical', 'manual_backfill'
     organization_id UUID NOT NULL,
     profile VARCHAR(20) NOT NULL,
     block_id VARCHAR(80) NOT NULL,
     action VARCHAR(20) NOT NULL,  -- 'inserted', 'skipped_existing'
     details JSONB NOT NULL DEFAULT '{}'::jsonb
   );
   CREATE INDEX ix_alloc_template_audit_org_profile
     ON allocation_template_audit (organization_id, profile, triggered_at DESC);
   ```
   Global table (no RLS — audit log for admin visibility).

6. **Backfill missing canonical blocks into `strategic_allocation`:**
   For each existing distinct `(organization_id, profile)` combo, INSERT rows for every canonical block_id not yet present:
   ```sql
   INSERT INTO strategic_allocation
     (allocation_id, organization_id, profile, block_id, target_weight, min_weight, max_weight,
      risk_budget, rationale, approved_by, effective_from, effective_to, actor_source, excluded_from_portfolio)
   SELECT gen_random_uuid(), combo.organization_id, combo.profile, blk.block_id,
          NULL, NULL, NULL, NULL,
          'Auto-backfilled by migration 0153 for template completeness',
          'system', CURRENT_DATE, NULL, 'migration_0153', false
     FROM (SELECT DISTINCT organization_id, profile FROM strategic_allocation) combo
     CROSS JOIN (SELECT block_id FROM allocation_blocks WHERE is_canonical = true) blk
     LEFT JOIN strategic_allocation sa
       ON sa.organization_id = combo.organization_id
      AND sa.profile = combo.profile
      AND sa.block_id = blk.block_id
    WHERE sa.allocation_id IS NULL;
   ```
   Log row count inserted. Also insert matching rows into `allocation_template_audit` with `trigger_reason = 'manual_backfill'`, `action = 'inserted'`.

   **Note on `target_weight NOT NULL`:** `strategic_allocation.target_weight` is currently NOT NULL. Migration must first `ALTER COLUMN target_weight DROP NOT NULL` (and similarly `min_weight`, `max_weight`) to permit the NULL backfill. Same for the migration to be clean.

7. **Create trigger `enforce_strategic_allocation_template`:**

   ```sql
   CREATE OR REPLACE FUNCTION fn_enforce_allocation_template()
   RETURNS TRIGGER AS $$
   DECLARE
     missing_block RECORD;
     audit_reason TEXT;
   BEGIN
     -- Determine reason based on operation + context
     IF TG_OP = 'INSERT' AND TG_TABLE_NAME = 'strategic_allocation' THEN
       audit_reason := 'new_profile_created';
       -- Check if this is the first row for this (org, profile). If yes, backfill.
       IF (SELECT COUNT(*) FROM strategic_allocation
            WHERE organization_id = NEW.organization_id AND profile = NEW.profile) = 1 THEN
         FOR missing_block IN
           SELECT block_id FROM allocation_blocks
            WHERE is_canonical = true AND block_id <> NEW.block_id
         LOOP
           INSERT INTO strategic_allocation
             (allocation_id, organization_id, profile, block_id,
              target_weight, min_weight, max_weight, risk_budget,
              rationale, approved_by, effective_from, effective_to,
              actor_source, excluded_from_portfolio)
           VALUES
             (gen_random_uuid(), NEW.organization_id, NEW.profile, missing_block.block_id,
              NULL, NULL, NULL, NULL,
              'Auto-inserted by enforce_allocation_template trigger',
              'system', CURRENT_DATE, NULL, 'trigger_enforce', false);
           INSERT INTO allocation_template_audit
             (trigger_reason, organization_id, profile, block_id, action,
              details)
           VALUES
             (audit_reason, NEW.organization_id, NEW.profile, missing_block.block_id,
              'inserted',
              jsonb_build_object('source_row_id', NEW.allocation_id));
         END LOOP;
       END IF;
     END IF;
     RETURN NEW;
   END;
   $$ LANGUAGE plpgsql SECURITY DEFINER;

   CREATE TRIGGER trg_enforce_allocation_template_sa
     AFTER INSERT ON strategic_allocation
     FOR EACH ROW EXECUTE FUNCTION fn_enforce_allocation_template();
   ```

   A sibling trigger on `allocation_blocks` for when `is_canonical` flips to true — inserts rows into `strategic_allocation` for every existing `(org, profile)` combo for the newly-canonical block, logging each to audit.

   Triggers MUST log every action (insert OR skip) to `allocation_template_audit` so operators can trace any auto-insertion.

8. **Down-migration:** reverse in reverse order. Triggers dropped. `allocation_template_audit` dropped. Backfilled rows deleted (identified via `actor_source IN ('migration_0153','trigger_enforce')`). `fi_us_short_term` renamed back to `fi_short_term`. Columns dropped. Assertion that NOT NULL can be restored (requires target_weight values to exist for all rows — abort with clear error if any NULL weight remains post-reversal).

**Acceptance:**
- `make migrate` clean, `make migrate downgrade -1` clean.
- Post-migration: `SELECT organization_id, profile, COUNT(*) FROM strategic_allocation GROUP BY 1,2` returns 18 rows for every `(org, profile)`.
- Audit table populated with the migration backfill rows.
- `fi_us_short_term` exists as canonical block; no FK references to `fi_short_term` remain.
- `effective_to IS NULL` on 100% of `strategic_allocation` rows.

### Section B — `block_mapping.py` label extensions

**File:** `backend/vertical_engines/wealth/model_portfolio/block_mapping.py`

Extend `STRATEGY_LABEL_TO_BLOCKS`:
```python
# Commodities — catalog uses short-form label alongside Morningstar full form
"Commodities": ["alt_commodities"],
"Commodities / Energy": ["alt_commodities"],
# Mid-cap equity — catalog uses space-form, mapping had hyphen-form only
"Mid Growth": ["na_equity_small", "na_equity_growth"],
"Mid Value": ["na_equity_small", "na_equity_value"],
# Short-term FI — remap under new canonical block_id
"Short Government": ["fi_us_short_term"],   # was ["fi_us_treasury", "cash"]
"Ultrashort Bond": ["fi_us_short_term"],    # was ["cash"]
```

Do NOT remove the hyphen-form keys (`Mid-Cap Growth`, `Mid-Cap Value`) — kept for backward compatibility with any existing rows that still carry that exact label.

**Acceptance:** `strategy_labels_for_block('alt_commodities')` returns a list including both `"Commodities Broad Basket"` and `"Commodities"`. `strategy_labels_for_block('fi_us_short_term')` returns `["Short Government", "Ultrashort Bond"]`.

### Section C — Template completeness validator

**File:** `backend/quant_engine/allocation_template_service.py` (new).

Pure function, same shape pattern as `block_coverage_service.py`. Schema:
```python
class TemplateGap(BaseModel):
    block_id: str

class TemplateReport(BaseModel):
    organization_id: UUID
    profile: str
    is_complete: bool
    missing_canonical_blocks: list[str]
    extra_non_canonical_blocks: list[str]  # non-canonical blocks present in the allocation; informational, not a failure
```

Queries:
```sql
-- missing canonical blocks
SELECT ab.block_id
  FROM allocation_blocks ab
  LEFT JOIN strategic_allocation sa
    ON sa.block_id = ab.block_id
   AND sa.organization_id = :organization_id
   AND sa.profile = :profile
 WHERE ab.is_canonical = true
   AND sa.allocation_id IS NULL;

-- extra non-canonical blocks (historical drift)
SELECT DISTINCT sa.block_id
  FROM strategic_allocation sa
  JOIN allocation_blocks ab ON ab.block_id = sa.block_id
 WHERE sa.organization_id = :organization_id
   AND sa.profile = :profile
   AND ab.is_canonical = false;
```

Acceptance: unit tests covering complete/missing/extra scenarios. Uses existing conftest fixtures — do not invent new ones.

### Section D — Wire into construction run

**File:** `backend/app/domains/wealth/workers/construction_run_executor.py`

Add as FIRST gate, BEFORE `validate_block_coverage` (currently at line ~1206):

```python
template = await validate_template_completeness(db, organization_id, profile)
if not template.is_complete:
    raise TemplateIncompleteError(template)
```

`TemplateIncompleteError` handled in the outer try/except the same way as `CoverageInsufficientError` — persists `winner_signal = 'template_incomplete'`, operator message listing the missing canonical blocks, and the full `TemplateReport` under `cascade_telemetry.template_report`.

Operator message template:
```
Portfolio construction aborted: profile '{profile}' is missing {N} canonical
allocation block(s). Expected 18 blocks per profile per the institutional
template; {N} are absent.

Missing blocks: {comma-separated block_ids}

Action: this should never happen post-migration 0153. Contact engineering
if you see this message — it indicates the template trigger failed.
```

Wire a matching branch in the frontend component that renders `winner_signal === 'template_incomplete'` (use the same `CoverageGapPanel.svelte` as scaffold or add a sibling `TemplateIncompletePanel.svelte`).

### Section E — Enum + schema updates

Add `WinnerSignal.TEMPLATE_INCOMPLETE = "template_incomplete"` wherever the enum lives (grep confirms it's in the wealth schemas). No migration needed if `winner_signal` is free-form JSONB — document the decision in migration 0153 header.

### Section F — Integration tests

**Files:**
- `backend/tests/quant_engine/test_allocation_template_service.py`: complete/missing/extra scenarios for the validator.
- `backend/tests/wealth/test_construction_run_template_gate.py`: mirror `test_construction_run_coverage_gate.py` — seed an incomplete template, dispatch run, assert `status='failed'`, `winner_signal='template_incomplete'`, optimizer + coverage gate never invoked.
- `backend/tests/db/test_allocation_template_trigger.py`: insert a new `(org, profile)` combo via a single row, assert trigger creates the remaining 17 rows + matching audit entries.

Tests must run clean against the Docker Postgres used in CI.

---

## Ordering inside this PR

A → B → C → D → E → F. One commit per Section.

## Global guardrails

- `CLAUDE.md` rules. Async-first, RLS via `SET LOCAL`, `expire_on_commit=False`, `lazy="raise"`.
- No new Python dependencies.
- `make check` green (tolerating pre-existing lint hygiene issues that are not introduced by this PR — noted in `feedback_dev_first_ci_later.md`).
- One commit per Section.
- Do NOT touch: optimizer cascade, candidate_screener, `block_coverage_service.py` beyond integration callsite, classifier, fixtures for other tests.

## Final report format

1. Dev DB post-migration state:
   - `SELECT organization_id, profile, COUNT(*) FROM strategic_allocation GROUP BY 1,2` — every row shows 18.
   - `SELECT COUNT(*) FROM allocation_blocks WHERE is_canonical = true` = 18.
   - `SELECT COUNT(*) FROM allocation_template_audit` ≥ (number of rows backfilled by migration 0153).
   - No FK references to `fi_short_term`.
2. Migration up + downgrade round-trip verified (up → down → up clean).
3. Test output (pytest -v for all three new test files + smoke re-run of A22/A23 tests to confirm no regression).
4. Construction smoke re-run against org `403d8392-...` for all 3 profiles. Expected:
   - All 3 abort with `winner_signal = 'block_coverage_insufficient'` (A22 gate triggers after template completeness passes).
   - Coverage report shows gaps for growth/value/commodities blocks where `catalog_candidates_available` is now non-zero thanks to the Section B mapping updates — operator has candidates to import.
5. Confirmation that trigger fired at least once during the test suite with a matching audit log entry.
6. List any deviations from spec discovered during implementation.
