# FI Classification Hotfix — CASE Precedence Fix

**Date:** 2026-04-12
**Branch:** `feat/fi-classification-hotfix`
**Scope:** 1 code commit + 2 operational steps (re-sync + re-calc)
**Estimated duration:** 1 hour concentrated Opus session
**Priority:** BLOCKING — must ship before FI Quant Session 3

## Problem

`universe_sync.py` classifies funds via SQL CASE statements with ILIKE keyword matching. Three keyword precedence bugs cause misclassification:

1. `%income%` matches "Equity Income", "Dividend Income", "Real Estate Income", "Growth & Income" → `fixed_income` (WRONG — these are equity funds)
2. `%credit%` matches "Private Credit", "Credit Hedge" → `fixed_income` (WRONG — these are alternatives)
3. The `alternatives` check (Real Estate, REIT, Commodities) comes AFTER `fixed_income`, so funds captured by `%income%` never reach the alternatives bucket

Consequence: ~100-200 funds receive FI scoring (duration, credit beta) instead of equity scoring, corrupting composite_score and ELITE rankings.

## READ FIRST

1. `backend/app/domains/wealth/workers/universe_sync.py` — READ FULLY. Find the 4 CASE statements at lines ~151-155, ~232-237, ~283-288, ~382-387. Understand the current keyword lists per bucket.
2. `docs/plans/2026-04-12-fi-classification-audit-prompt.md` — the audit that identified the root cause

## Deliverable — 1 commit

### Fix the CASE statement keyword precedence in ALL 4 phases

The pattern is the same across phases. For each CASE statement:

**Step 1 — Reorder: cash FIRST, then alternatives, then fixed_income, then equity as ELSE**

```sql
CASE
  -- Cash (most specific, check first)
  WHEN strategy_label ILIKE ANY(ARRAY[
    '%money market%', '%cash%', '%liquidity%', '%ultra short%'
  ]) THEN 'cash'

  -- Alternatives (before fixed_income to catch Real Estate, Private Credit)
  WHEN strategy_label ILIKE ANY(ARRAY[
    '%real estate%', '%reit%', '%commodity%', '%commodities%',
    '%infrastructure%', '%private credit%', '%private equity%',
    '%venture capital%', '%hedge%', '%long/short%', '%long short%',
    '%market neutral%', '%event driven%', '%merger arbitrage%',
    '%multi-strategy%', '%managed futures%', '%convertible%'
  ]) THEN 'alternatives'

  -- Fixed Income (specific patterns only — NO %income%, NO %credit%)
  WHEN strategy_label ILIKE ANY(ARRAY[
    '%bond%', '%fixed income%', '%treasury%', '%government bond%',
    '%aggregate bond%', '%municipal%', '%muni %', '%investment grade%',
    '%high yield%', '%corporate bond%', '%sovereign%',
    '%mortgage%', '%structured%', '%securitized%',
    '%inflation protected%', '%tips%', '%floating rate%',
    '%bank loan%', '%loan%'
  ]) THEN 'fixed_income'

  -- Everything else defaults to equity
  ELSE 'equity'
END
```

**Step 2 — Critical keyword removals from fixed_income bucket:**

- REMOVE `%income%` — too broad, captures "Equity Income", "Dividend Income", "Real Estate Income"
- REMOVE `%credit%` — too broad, captures "Private Credit" (alternatives) and "Credit Hedge" (alternatives)

**Step 3 — Critical keyword additions to alternatives bucket:**

- ADD `%private credit%` — was captured by `%credit%` in FI, belongs in alternatives
- ADD `%convertible%` — hybrid equity/debt, better classified as alternatives than FI
- ADD `%long/short%`, `%long short%` — clearly equity strategy, but if captured by other patterns first, should be alternatives. Actually these are equity — add to an explicit equity check BEFORE alternatives if needed.

**Wait — long/short is equity, not alternatives.** Revise:

If there are strategy labels like "Long/Short Equity" that should be equity (not alternatives), add an explicit equity check BEFORE alternatives:

```sql
CASE
  -- Cash
  WHEN ... THEN 'cash'

  -- Explicit equity patterns (before alternatives catches them)
  WHEN strategy_label ILIKE ANY(ARRAY[
    '%equity income%', '%dividend income%', '%growth & income%',
    '%growth and income%', '%balanced%', '%allocation%',
    '%long/short equity%', '%long short equity%'
  ]) THEN 'equity'

  -- Alternatives
  WHEN ... THEN 'alternatives'

  -- Fixed Income
  WHEN ... THEN 'fixed_income'

  -- Default
  ELSE 'equity'
END
```

This explicitly routes "Equity Income", "Dividend Income", "Growth & Income" to equity BEFORE the alternatives or FI checks.

### Apply the SAME fix to ALL 4 phases

The CASE statement appears in:
- `_sync_sec_etfs` (Phase 1, ~line 151-155)
- `_sync_sec_mf_series` (Phase 2, ~line 232-237)
- `_sync_sec_registered` (Phase 3, ~line 283-288)
- `_sync_esma_funds` (Phase 4, ~line 382-387)

**All 4 must use the SAME keyword order and lists.** Copy-paste the fixed CASE across all 4. If possible, extract the CASE into a shared SQL fragment or Python constant to avoid drift:

```python
_ASSET_CLASS_CASE_SQL = """
CASE
  WHEN strategy_label ILIKE ANY(%(cash_patterns)s) THEN 'cash'
  WHEN strategy_label ILIKE ANY(%(equity_explicit_patterns)s) THEN 'equity'
  WHEN strategy_label ILIKE ANY(%(alternatives_patterns)s) THEN 'alternatives'
  WHEN strategy_label ILIKE ANY(%(fi_patterns)s) THEN 'fixed_income'
  ELSE 'equity'
END
"""

_CASH_PATTERNS = ["%money market%", "%cash%", "%liquidity%", "%ultra short%"]
_EQUITY_EXPLICIT_PATTERNS = [
    "%equity income%", "%dividend income%", "%growth & income%",
    "%growth and income%", "%balanced%", "%allocation%",
    "%long/short equity%", "%long short equity%",
]
_ALTERNATIVES_PATTERNS = [
    "%real estate%", "%reit%", "%commodity%", "%commodities%",
    "%infrastructure%", "%private credit%", "%private equity%",
    "%venture capital%", "%hedge%", "%long/short%", "%long short%",
    "%market neutral%", "%event driven%", "%merger arbitrage%",
    "%multi-strategy%", "%managed futures%", "%convertible%",
]
_FI_PATTERNS = [
    "%bond%", "%fixed income%", "%treasury%", "%government bond%",
    "%aggregate bond%", "%municipal%", "%muni %", "%investment grade%",
    "%high yield%", "%corporate bond%", "%sovereign%",
    "%mortgage%", "%structured%", "%securitized%",
    "%inflation protected%", "%tips%", "%floating rate%",
    "%bank loan%", "%loan%",
]
```

Then each phase references the shared constants. This is the centralized logic the audit recommended.

**Caution with `%long/short%` and `%long short%` in alternatives:** these patterns could match "Long/Short Equity" which should be equity. The explicit equity check handles "Long/Short Equity" specifically. The alternatives patterns only catch bare "Long/Short" (without "Equity") and "Long Short" (hedge fund style). If there's ambiguity, the explicit equity check wins because it's evaluated FIRST.

### Verification queries (run BEFORE and AFTER the fix)

**Before fix — capture current state:**

```sql
-- Snapshot current classification
CREATE TEMP TABLE asset_class_before AS
SELECT id, external_id, name, strategy_label, asset_class
FROM instruments_universe;
```

**After fix — run universe_sync, then diff:**

```sql
-- Diff: what changed?
SELECT
  b.external_id,
  b.name,
  b.strategy_label,
  b.asset_class AS before_class,
  a.asset_class AS after_class
FROM asset_class_before b
JOIN instruments_universe a ON a.id = b.id
WHERE b.asset_class != a.asset_class
ORDER BY b.asset_class, a.asset_class, b.name;
```

**Validate known misclassifications are fixed:**

```sql
-- These should NOT be fixed_income anymore
SELECT external_id, name, strategy_label, asset_class
FROM instruments_universe
WHERE strategy_label ILIKE ANY(ARRAY[
  '%equity income%', '%dividend income%', '%real estate income%',
  '%growth & income%', '%private credit%', '%credit hedge%'
])
ORDER BY strategy_label;
-- Expected: all should be 'equity' or 'alternatives', ZERO 'fixed_income'
```

**Validate FI classification is still correct for real FI funds:**

```sql
-- These SHOULD still be fixed_income
SELECT external_id, name, strategy_label, asset_class
FROM instruments_universe
WHERE strategy_label ILIKE ANY(ARRAY[
  '%bond%', '%fixed income%', '%treasury%', '%high yield%',
  '%aggregate bond%', '%municipal%'
])
AND asset_class != 'fixed_income'
ORDER BY strategy_label;
-- Expected: ZERO rows (no real FI fund lost its classification)
```

## Operational steps (after commit merges)

### Step 2 — Re-run universe_sync

```bash
# The worker to run depends on how universe_sync is triggered
# It might be a standalone script or part of the worker registry
cd backend
python -c "
import asyncio
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.').parent / '.env')
import sys; sys.path.insert(0, '.')
from app.domains.wealth.workers.universe_sync import run_universe_sync
result = asyncio.run(run_universe_sync())
print(f'Result: {result}')
"
```

If `run_universe_sync` doesn't exist as a single callable, find the correct entrypoint by reading the worker registry. The goal is to re-run the 4 sync phases so the CASE statements re-evaluate.

### Step 3 — Re-run risk_calc

```bash
cd backend
python scripts/run_global_risk_metrics.py
```

This recalculates scores with corrected `asset_class` assignments. Funds that changed from `fixed_income` to `equity` or `alternatives` will get the correct scoring model applied.

### Step 4 — Validate

Run the diff query from the verification section. Report:
- How many funds changed classification
- The before→after distribution
- Specific funds that were misclassified (GURCX should now be `alternatives` or `equity`)

## Gate

- [ ] `ruff check` on `universe_sync.py` → clean
- [ ] `make test` → green (no tests should break — the CASE change is data-only)
- [ ] `lint-imports` → 31 contracts, 0 broken
- [ ] Verification queries: zero known-misclassified funds remain as `fixed_income`
- [ ] Verification queries: zero real FI funds lost their classification
- [ ] universe_sync re-run completes without error
- [ ] risk_calc re-run completes: ELITE = 300, FI fund scores shift

## Commit template

```
fix(universe_sync): CASE precedence fix for asset_class classification

Root cause (audit 2026-04-12): SQL CASE statements in universe_sync.py
used overly broad keywords (%income%, %credit%) for the fixed_income
bucket, capturing equity and alternatives funds:
- "Equity Income", "Dividend Income", "Real Estate Income" → FI (WRONG)
- "Private Credit", "Credit Hedge" → FI (WRONG)
- Alternatives check came AFTER FI, never catching captured funds

Fix: reorder CASE buckets (cash → explicit equity → alternatives → FI
→ ELSE equity), remove %income% and %credit% from FI keywords, use
specific patterns (%bond%, %fixed income%, %treasury%, %municipal%,
etc.), centralize patterns as Python constants shared across all 4
sync phases.

Explicit equity patterns added: "Equity Income", "Dividend Income",
"Growth & Income", "Balanced", "Allocation", "Long/Short Equity"
routed to equity BEFORE alternatives check.

Alternatives patterns expanded: "Private Credit", "Convertible",
"Long/Short" (non-equity), "Managed Futures" routed to alternatives.

<N> funds reclassified after universe_sync re-run:
- <X> fixed_income → equity (Equity Income, Dividend Income, etc.)
- <Y> fixed_income → alternatives (Real Estate, Private Credit, etc.)
- <Z> equity → alternatives (if any)
Zero real FI funds lost classification (verified via bond/treasury query).

risk_calc re-run: ELITE 300 maintained, FI scoring model now applied
only to genuine fixed income funds.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## Escape hatches

1. The 4 CASE statements have DIFFERENT keyword lists across phases (ETF vs MF vs registered vs ESMA) — unify them using the shared Python constants, but preserve any phase-specific patterns that are intentionally different (e.g., ESMA might have EU-specific strategy labels). Report differences.
2. Some strategy_labels don't match ANY pattern and fall through to ELSE 'equity' — that's CORRECT default behavior. Don't add patterns just to avoid the default.
3. After re-running universe_sync, some funds that were correctly classified as FI might change to equity because the new patterns are more specific — verify via the "real FI funds" query. If a real bond fund lost its FI classification, the FI keyword list needs that pattern added.
4. `universe_sync` has a lock (900_070) — if it's already running, wait. Don't force.

## Not valid escape hatches

- "I'll just add the fixes to the FI keywords without reordering" → NO, order matters in CASE. Alternatives MUST come before FI.
- "I'll skip the centralization and just fix each CASE inline" → NO, 4 copies of the same logic will drift. Centralize as constants.
- "The diff is too large to review" → run the verification queries, they prove correctness. The diff count IS the report.
