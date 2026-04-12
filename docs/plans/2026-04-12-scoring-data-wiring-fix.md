# Scoring Data Wiring Fix — SPY Benchmark + MMF Catalog Sync

**Date:** 2026-04-12
**Branch:** `feat/scoring-data-wiring-fix`
**Scope:** 2 code fixes + 3 operational steps
**Priority:** BLOCKING — Alt and Cash scores are meaningless without real data flowing

## Problem 1: Alternatives avg_score 41.7 — SPY benchmark missing

The alternatives analytics pass computes equity_correlation_252d, downside/upside capture, and crisis_alpha against SPY returns fetched via `benchmark_nav WHERE block_id = 'na_equity_large'`. This block does NOT exist in `allocation_blocks`. Without SPY returns, ALL alt-specific metrics are NULL, triggering penalty defaults (~40 per component).

Existing blocks include `na_equity_growth` (QQQ), `na_equity_value` (IWD), `na_equity_small` (IWM) — but NOT `na_equity_large` (SPY).

**Fix:** Seed `na_equity_large` allocation block with `benchmark_ticker = 'SPY'`. Run `benchmark_ingest` to populate NAV data.

## Problem 2: Cash avg_score 38.7 — MMFs not in catalog

`universe_sync.py` has 4 phases (ETFs, MFs, Registered, ESMA) but NO phase for `sec_money_market_funds`. The 236 "cash" funds in `instruments_universe` are ETFs/MFs whose `strategy_label` matches cash keywords (`%%money market%%`, `%%ultra short%%`). They are NOT the 373 actual MMFs in `sec_money_market_funds`.

The cash analytics pass tries to JOIN via `series_id` against `sec_money_market_funds` — returns ZERO rows because the populations are disjoint.

**Fix:** Add Phase 5 `_sync_sec_mmfs()` to `universe_sync.py` that upserts `sec_money_market_funds` into `instruments_universe` with `asset_class = 'cash'`.

## READ FIRST

1. `backend/app/domains/wealth/workers/universe_sync.py` — understand the 4 existing phases and the _asset_class_case helper. Phase 5 follows the same pattern.
2. `backend/app/domains/wealth/workers/risk_calc.py` — find `_batch_fetch_mmf_data()` (~line 897-932) to understand the JOIN key (`fund.attributes.get("series_id")` → `sec_money_market_funds.series_id`). Find the alt analytics pass to understand SPY benchmark lookup (`benchmark_nav WHERE block_id = 'na_equity_large'`).
3. `backend/app/domains/wealth/models/` — `SecMoneyMarketFund` model to understand columns available for the sync phase.
4. `calibration/config/blocks.yaml` — existing block definitions. Add `na_equity_large` here.
5. `backend/app/core/db/migrations/versions/0122_add_fi_benchmark_blocks.py` — reference for how FI benchmark blocks were seeded.

## Deliverable — 2 commits

### Commit 1: Seed `na_equity_large` block + Phase 5 MMF sync

**1a. Add `na_equity_large` to blocks.yaml:**

```yaml
na_equity_large:
  asset_class: equity
  benchmark_ticker: SPY
  display_name: US Large Cap Equity
  is_active: true
```

If blocks.yaml is read by a seed script or migration, ensure this block gets into `allocation_blocks` table. If blocks.yaml is only reference and the actual seed is via migration, add an INSERT in a new migration:

```sql
INSERT INTO allocation_blocks (block_id, asset_class, benchmark_ticker, display_name, is_active)
VALUES ('na_equity_large', 'equity', 'SPY', 'US Large Cap Equity', true)
ON CONFLICT (block_id) DO NOTHING;
```

**1b. Add Phase 5 `_sync_sec_mmfs()` to `universe_sync.py`:**

Follow the pattern of existing phases (Phase 1 `_sync_sec_etfs`, etc.). The new phase upserts `sec_money_market_funds` into `instruments_universe`:

```python
async def _sync_sec_mmfs(db: AsyncSession) -> int:
    """Phase 5: Sync SEC Money Market Funds into instruments_universe.
    
    These are the actual MMFs from sec_money_market_funds table (373 funds),
    distinct from ETFs/MFs that happen to have cash-like strategy_labels.
    The series_id link allows _batch_fetch_mmf_data() in risk_calc to JOIN
    successfully against sec_money_market_funds + sec_mmf_metrics.
    """
    result = await db.execute(text("""
        INSERT INTO instruments_universe (
            name, ticker, asset_class, instrument_type, universe,
            is_active, attributes
        )
        SELECT
            m.fund_name,
            m.ticker,
            'cash' AS asset_class,
            'fund' AS instrument_type,
            'money_market' AS universe,
            true AS is_active,
            jsonb_build_object(
                'series_id', m.series_id,
                'mmf_category', m.mmf_category,
                'manager_name', m.manager_name,
                'fund_subtype', 'mmf'
            ) AS attributes
        FROM sec_money_market_funds m
        WHERE m.ticker IS NOT NULL
          AND m.is_active = true
        ON CONFLICT (ticker) DO UPDATE SET
            asset_class = 'cash',
            attributes = instruments_universe.attributes || 
                jsonb_build_object(
                    'series_id', EXCLUDED.attributes->>'series_id',
                    'mmf_category', EXCLUDED.attributes->>'mmf_category',
                    'fund_subtype', 'mmf'
                ),
            updated_at = now()
    """))
    count = result.rowcount
    logger.info("universe_sync.sec_mmfs", upserted=count)
    return count
```

**Adapt this SQL** based on:
- The actual column names in `sec_money_market_funds` (read the model first)
- The actual UNIQUE constraint on `instruments_universe` (might be `ticker`, `(ticker, universe)`, or `instrument_id`)
- Whether `instruments_universe` has an `instrument_id` UUID primary key that needs to be generated
- The existing ON CONFLICT pattern used by other phases

**Call the new phase** in `run_universe_sync()` after Phase 4 (ESMA):

```python
# Phase 5: Money Market Funds
mmf_count = await _sync_sec_mmfs(db)
result["sec_mmfs"] = {"upserted": mmf_count}
```

### Commit 2: Defensive fix for existing cash funds without MMF data

The 236 existing "cash" funds (ultra-short ETFs, cash management MFs) will NEVER have MMF-specific data. The scoring model should handle NULL MMF metrics gracefully:

In `risk_calc.py` cash analytics pass: if a cash fund has no matching `sec_money_market_funds` row, skip MMF-specific metrics and score with whatever is available (fee_efficiency + NAV-based metrics only). Don't penalty-default ALL 5 components — at least compute `fee_efficiency` and any NAV-based metric that doesn't require MMF data.

Alternatively, in `_score_metrics`: if `asset_class == "cash"` and the fund has `attributes.fund_subtype != "mmf"`, use a simplified cash scoring that doesn't penalize missing MMF fields. These funds are "cash-like" but not actual MMFs.

**The exact implementation depends on what you find in the code.** Read `_batch_fetch_mmf_data()` and `_compute_cash_score()` to understand the penalty cascade, then fix the most impactful NULL path.

## Operational steps (after commits merge)

### Step 1: Run benchmark_ingest (populates SPY NAV)

```bash
cd backend
python -c "
import asyncio
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path('.').parent / '.env')
import sys; sys.path.insert(0, '.')
from app.domains.wealth.workers.benchmark_ingest import run_benchmark_ingest
result = asyncio.run(run_benchmark_ingest())
print(f'Result: {result}')
"
```

Verify SPY populated:
```sql
SELECT block_id, COUNT(*), MIN(nav_date), MAX(nav_date)
FROM benchmark_nav
WHERE block_id = 'na_equity_large'
GROUP BY 1;
```

### Step 2: Run universe_sync (brings 373 MMFs into catalog)

```bash
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

Verify MMFs entered:
```sql
SELECT asset_class, COUNT(*),
       COUNT(*) FILTER (WHERE attributes->>'fund_subtype' = 'mmf') AS actual_mmfs
FROM instruments_universe
WHERE asset_class = 'cash' AND is_active = true
GROUP BY 1;
```

### Step 3: Run risk_calc (recomputes with real data)

```bash
python scripts/run_global_risk_metrics.py
```

### Step 4: Validate

```sql
-- Alt scores should improve significantly (SPY data now available)
SELECT scoring_model, COUNT(*) AS total,
       ROUND(AVG(manager_score)::numeric, 1) AS avg_score,
       COUNT(*) FILTER (WHERE elite_flag) AS elite
FROM fund_risk_metrics
WHERE calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics)
GROUP BY scoring_model ORDER BY scoring_model;

-- Cash funds with actual MMF data should score higher
SELECT 
  CASE WHEN seven_day_net_yield IS NOT NULL THEN 'with_mmf_data' ELSE 'without' END AS data_status,
  COUNT(*), ROUND(AVG(manager_score)::numeric, 1) AS avg_score
FROM fund_risk_metrics
WHERE scoring_model = 'cash'
  AND calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics)
GROUP BY 1;

-- Alt metrics should now be populated
SELECT
  COUNT(*) AS total_alt,
  COUNT(equity_correlation_252d) AS with_corr,
  COUNT(crisis_alpha_score) AS with_crisis,
  COUNT(inflation_beta) AS with_inflation
FROM fund_risk_metrics
WHERE scoring_model = 'alternatives'
  AND calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics);
```

## Gate

- [ ] `ruff check` on modified files → clean
- [ ] `make test` → green
- [ ] `benchmark_nav` has SPY data for `na_equity_large` block
- [ ] `instruments_universe` has MMF funds with `fund_subtype = 'mmf'` in attributes
- [ ] Alt avg_score improved from 41.7 (target: >55)
- [ ] Cash funds with MMF data have meaningful scores (target: >50)
- [ ] ELITE = 300 maintained
- [ ] Zero MissingGreenlet errors in risk_calc

## Escape hatches

1. `sec_money_market_funds` doesn't have a `ticker` column → use `series_id` as the key and build the ticker from share class mapping (`sec_fund_classes`)
2. `allocation_blocks` table doesn't accept direct INSERT (managed by ConfigService) → use ConfigService API or seed via the existing blocks.yaml workflow
3. ON CONFLICT in Phase 5 clashes with existing cash-classified funds that have the same ticker → the DO UPDATE SET ensures the `fund_subtype='mmf'` flag is added to existing rows rather than creating duplicates
4. SPY ticker already exists in `instruments_universe` as an equity ETF → that's fine, SPY in instruments_universe is for screening; SPY in benchmark_nav (via na_equity_large block) is the benchmark reference. Different tables, different purposes.
