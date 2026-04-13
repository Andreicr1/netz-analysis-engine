# Data Pipeline Population — Fix Empty taa_regime_state + Attribution Fund Returns

## Problem

The local development database has data gaps that cause 404s and attribution failures:

1. **`taa_regime_state` is EMPTY** — the TAA regime computation inside `risk_calc` worker
   never ran. This causes 404 on `GET /allocation/{profile}/regime-bands` for all profiles.
2. **Attribution shows `has_fund_return=False`** for all blocks — even though `nav_timeseries`
   has data for all 56 portfolio funds. This is likely a JOIN issue in the attribution service.

## Current DB State (verified)

- `nav_timeseries`: 20M rows, 6,164 instruments
- `benchmark_nav`: 22 blocks populated (8,356 rows for na_equity_large)
- `model_portfolio_nav`: 7,539 rows
- `taa_regime_state`: **EMPTY**
- 3 model portfolios: Balanced Growth (moderate, 56 funds), Aggressive Growth (growth, 46 funds), Conservative Income (conservative, 56 funds, status=live)
- All 56 funds in Balanced Growth have NAV data in nav_timeseries

## Branch

`fix/live-workbench-api-wiring` (already exists)

## MANDATORY: Read these files FIRST

1. `backend/app/domains/wealth/workers/risk_calc.py` — lines 1232-1455 (`_compute_and_persist_taa_state`) and lines 1745-1758 (where TAA is called inside the risk_calc main loop)
2. `backend/quant_engine/taa_band_service.py` — `resolve_effective_bands()`, `smooth_regime_centers()`
3. `backend/app/domains/wealth/routes/allocation.py` — `get_regime_bands()` handler (line 389) to understand what it queries
4. `backend/vertical_engines/wealth/attribution/service.py` — search for `attribution_block_excluded` log message to understand the JOIN that fails

## DELIVERABLES (3 items)

### 1. Run the risk_calc worker to populate taa_regime_state

The TAA computation is inside the `risk_calc` worker (`_compute_and_persist_taa_state`).
It computes regime detection from macro indicators, classifies the regime, applies EMA
smoothing, and upserts to `taa_regime_state`.

Run it for the org that owns the portfolios:

```python
import asyncio, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('..') / '.env')
sys.path.insert(0, '.')

from app.domains.wealth.workers.risk_calc import run_risk_calc

# Find the org_id from model_portfolios
async def main():
    from app.core.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text
    
    async with AsyncSession(engine, expire_on_commit=False) as db:
        r = await db.execute(text("SELECT DISTINCT organization_id FROM model_portfolios LIMIT 1"))
        org_id = r.scalar()
        print(f"Org ID: {org_id}")
    
    if org_id:
        result = await run_risk_calc(org_id)
        print(f"Result: {result}")
    
    await engine.dispose()

asyncio.run(main())
```

**Important:** The risk_calc worker uses `pg_advisory_lock(900071)` — make sure no
other instance is running. If the lock is held, the worker will skip.

After running, verify:
```sql
SELECT profile, as_of_date, raw_regime, stress_score 
FROM taa_regime_state 
ORDER BY as_of_date DESC;
```

This should show rows for each profile (moderate, growth, conservative).

### 2. Diagnose and fix the attribution fund return JOIN

The attribution service logs `attribution_block_excluded block_id=X has_benchmark_return=True has_fund_return=False`.

Read the attribution service to find where it computes `has_fund_return`. The issue is
that benchmarks have returns in `benchmark_nav` but the fund returns lookup fails.

**Likely causes:**
- The attribution service looks for fund returns in a different table than `nav_timeseries`
  (maybe `nav_monthly_returns_agg` or similar)
- The JOIN key is wrong (e.g., uses `block_id` to look up fund returns instead of
  iterating through the portfolio's fund_selection_schema)
- The attribution needs `instruments_org` (org-scoped) but the funds are only in
  `instruments_universe` (global)

Read the code at the log site, trace the data flow, and fix the JOIN or data source.
If the fix requires running another worker (e.g., a monthly aggregation), document
which worker and add it to the pipeline sequence.

### 3. Verify end-to-end after fixes

After running risk_calc and fixing attribution, verify:

```bash
# 1. Regime bands should return data
curl -s http://localhost:8000/api/v1/allocation/moderate/regime-bands \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -20

# 2. Attribution should succeed
curl -s http://localhost:8000/api/v1/attribution/moderate \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -20

# 3. Correlation regime should find live portfolio
curl -s http://localhost:8000/api/v1/analytics/correlation-regime/moderate \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -20
```

If correlation-regime still 404s, it's because the portfolio has `status=backtesting`
not `status=live`. The `get_correlation_regime` handler (correlation_regime.py:48-59)
queries `WHERE status == "live"`. Check if the portfolio status needs to be updated.

## Gate

1. `taa_regime_state` has rows for all 3 profiles
2. `GET /allocation/moderate/regime-bands` returns 200 with real regime data
3. `GET /allocation/growth/regime-bands` returns 200
4. Attribution logs no longer show `has_fund_return=False` for populated blocks
5. The Live Workbench Builder loads without 404 errors in the console
6. `make test` passes (if modified any code)

## Commit

```
fix(data): populate taa_regime_state + fix attribution fund return JOIN

Ran risk_calc to compute and persist TAA regime state for all profiles.
Fixed attribution fund return lookup [describe actual fix here].

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
