# Terminal API Contract Fix — 6 Breaks + 5 Formatter Violations

## Context

A full API contract audit of the terminal frontend (36 endpoints) found 6 breaks
and 5 formatter violations. 25 endpoints are correctly wired. This prompt fixes all
11 issues in a single consolidated sprint.

## Branch

`fix/terminal-api-contract-wiring` (already created from main)

## MANDATORY: Read these files to understand the actual backend contracts

1. `backend/app/domains/wealth/routes/market_data.py` — lines 781-830: `GET /historical/{ticker}`, read `HistoricalResponse` response_model and the actual return shape
2. `backend/app/domains/wealth/routes/model_portfolios.py` — search for: `nav-history` (response shape), `execute-trades` (exact path), `construct`, `activate`
3. `backend/app/domains/wealth/routes/correlation_regime.py` — lines 48-59: the `WHERE status == "live"` filter
4. `backend/app/domains/wealth/routes/allocation.py` — lines 389-400: regime-bands handler
5. `backend/app/domains/wealth/schemas/model_portfolio.py` — nav-history response schema
6. `backend/app/domains/wealth/workers/risk_calc.py` — lines 1745-1758: TAA computation call
7. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — find ALL `/market-data/quote/` calls
8. `frontends/wealth/src/lib/components/terminal/live/Watchlist.svelte` — find `/quote/` call for ticker search
9. `frontends/wealth/src/lib/components/terminal/live/RebalanceFocusMode.svelte` — find execute path
10. `frontends/wealth/src/lib/components/terminal/live/MacroRegimePanel.svelte` — find formatter violations
11. `frontends/wealth/src/lib/components/terminal/live/NewsFeed.svelte` — find formatter violations
12. `frontends/wealth/src/lib/components/terminal/live/TradeLog.svelte` — find formatter violations
13. `frontends/wealth/src/lib/components/terminal/live/AlertStreamPanel.svelte` — find formatter violations
14. `frontends/wealth/src/routes/(terminal)/alerts/+page.svelte` — find formatter violations

## FIXES (11 items, ordered by severity)

### Fix 1: CRITICAL — `/market-data/quote/{ticker}` → `/market-data/historical/{ticker}`

**Files to modify:**
- `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`
- `frontends/wealth/src/lib/components/terminal/live/Watchlist.svelte`

**What to do:**
1. Find ALL occurrences of `/market-data/quote/` in both files
2. Replace with `/market-data/historical/`
3. Read the `HistoricalResponse` schema from the backend to understand the return shape
4. The backend likely returns OHLCV bars with fields like `{ date, open, high, low, close, volume }`
5. The frontend expects `{ time: number, value: number }` for lightweight-charts
6. Add a mapping function that converts the backend response:
```typescript
function mapHistoricalBars(response: any): BarData[] {
    // Read the actual response shape from the backend and map accordingly
    // Likely: response.bars or response.data → map each to { time: unix_timestamp, value: close_price }
    // The date field may be ISO string — convert to Unix seconds
}
```
7. Apply this mapping everywhere historical bars are consumed

**For Watchlist ticker search validation:** The search currently calls `/market-data/quote/{ticker}`
to check if a ticker exists. Change to `/market-data/historical/{ticker}?period=1D` (minimal
data request). If 404, ticker doesn't exist. If 200, ticker is valid — extract the latest
price from the response.

### Fix 2: CRITICAL — nav-history response shape mismatch

**File:** `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte`

**Problem:** Frontend expects `nav_series: [{ date, nav }]` but the backend
`GET /model-portfolios/{id}/nav-history` returns `{ dates: string[], nav_series: number[], ... }`.

**What to do:**
1. Read the EXACT response from the backend endpoint (check the route handler and response model)
2. Find the frontend code that consumes the nav-history response (search for `nav-history` or `nav_series`)
3. Fix the mapping to match the actual backend shape

The backend (added in Session 3) returns:
```json
{
    "dates": ["2021-01-04", ...],
    "nav_series": [100.0, 100.12, ...],
    "drawdown_series": [0.0, -0.0012, ...],
    "metrics": { "sharpe": 1.23, "max_dd": -0.15, "ann_return": 0.082, "calmar": 0.55 }
}
```

The frontend mapping should iterate `dates` and `nav_series` in parallel:
```typescript
portfolioNavBars = data.dates.map((d: string, i: number) => ({
    time: Math.floor(new Date(d).getTime() / 1000),
    value: data.nav_series[i],
}));
```

### Fix 3: CRITICAL — execute-trades wrong path

**File:** `frontends/wealth/src/lib/components/terminal/live/RebalanceFocusMode.svelte`

**Problem:** Frontend calls `/model-portfolios/{id}/rebalance/execute` but the
backend route is `/model-portfolios/{id}/execute-trades`.

**What to do:**
1. Find the fetch call in RebalanceFocusMode.svelte (search for `execute` or `rebalance/execute`)
2. Change the path to `/model-portfolios/${portfolioId}/execute-trades`
3. Verify the request body matches `ExecuteTradesRequest` schema from the backend:
```python
class ExecuteTradesRequest(BaseModel):
    tickets: list[TradeTicketCreate]
    expected_version: int
```

### Fix 4: CRITICAL — correlation-regime filter bug

**File:** `backend/app/domains/wealth/routes/correlation_regime.py`

**Problem:** Line 51 filters `ModelPortfolio.status == "live"` but the model portfolio
state machine may use a different field name or value. Check the `ModelPortfolio` model
to verify:
- Is the field called `status` or `state`?
- What are the valid values? (`"draft"`, `"backtesting"`, `"active"`, `"live"`, `"paused"`)
- Does `activate_portfolio()` set status to `"active"` or `"live"`?

**What to do:**
1. Read `backend/app/domains/wealth/models/model_portfolio.py` — find the status/state field
2. Read the `activate_portfolio` handler in `routes/model_portfolios.py` — what value does it set?
3. Fix the filter in `correlation_regime.py:51` to match the actual value set by activation
4. If the field is `status` and activation sets `"active"` (not `"live"`), change the filter

### Fix 5: HIGH — Populate taa_regime_state

**What to do:**
Run the risk_calc worker for the org that owns the model portfolios. The TAA computation
is inside `_compute_and_persist_taa_state()` (risk_calc.py:1750-1754).

```python
cd backend
python -c "
import asyncio, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('..') / '.env')
sys.path.insert(0, '.')

async def main():
    from app.core.db.engine import engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text

    async with AsyncSession(engine, expire_on_commit=False) as db:
        r = await db.execute(text('SELECT DISTINCT organization_id FROM model_portfolios LIMIT 1'))
        org_id = r.scalar()
        print(f'Running risk_calc for org: {org_id}')

    from app.domains.wealth.workers.risk_calc import run_risk_calc
    result = await run_risk_calc(org_id)
    print(f'Result: {result}')
    await engine.dispose()

asyncio.run(main())
"
```

After running, verify:
```sql
SELECT profile, as_of_date, raw_regime, stress_score
FROM taa_regime_state ORDER BY as_of_date DESC LIMIT 10;
```

If `_compute_and_persist_taa_state` fails silently (caught at line 1753-1754), check the
exception and fix the root cause. Common issues:
- Missing macro_data for regime detection
- Missing allocation_blocks config
- Missing TaaConfig in vertical_config_defaults

### Fix 6: HIGH — taa-history same root cause as #5

Once Fix 5 populates `taa_regime_state`, the history endpoint should also work since
it reads from the same table. Verify after Fix 5.

### Fix 7-11: Formatter violations

**Replace ALL instances of `.toFixed()`, `.toLocaleTimeString()`, and manual
`.substring()` for date/time formatting** with `@investintell/ui` formatters.

**Files to fix:**
- `frontends/wealth/src/lib/components/terminal/live/MacroRegimePanel.svelte`
- `frontends/wealth/src/lib/components/terminal/live/NewsFeed.svelte`
- `frontends/wealth/src/lib/components/terminal/live/TradeLog.svelte`
- `frontends/wealth/src/lib/components/terminal/live/AlertStreamPanel.svelte`
- `frontends/wealth/src/routes/(terminal)/alerts/+page.svelte`

**What to search for and replace:**

| Find | Replace with |
|---|---|
| `.toFixed(N)` | `formatNumber(value, N)` or `formatPercent(value, N)` |
| `.toLocaleTimeString()` | `formatDateTime(value)` or `formatShortDate(value)` |
| `new Date(x).toISOString().substring(11, 16)` | `formatDateTime(x)` |
| `new Date(x).toLocaleDateString()` | `formatDate(x)` |
| `new Intl.NumberFormat(...)` | `formatNumber(value)` or `formatCurrency(value)` |

Import from `@investintell/ui`:
```typescript
import { formatNumber, formatPercent, formatDate, formatDateTime, formatShortDate, formatCurrency } from "@investintell/ui";
```

## RULES

- Do NOT modify any backend route handlers except `correlation_regime.py` (Fix 4)
- Do NOT modify portfolio-workspace.svelte.ts unless absolutely necessary for a fix
- Do NOT create new endpoints — use existing ones
- Zero hex color values. All terminal tokens.
- Do NOT change component layout or styling — only fix API wiring and formatters

## GATE

1. No 404 errors in browser console when loading `/portfolio/live` and selecting a portfolio
2. No 404 errors when loading `/portfolio/builder` and selecting a portfolio
3. Chart loads historical bars via `/market-data/historical/{ticker}`
4. Portfolio NAV overlay renders correctly (shape mapping fixed)
5. RebalanceFocusMode execute-trades call uses correct path
6. `taa_regime_state` has rows for all profiles (after running risk_calc)
7. `GET /allocation/moderate/regime-bands` returns 200
8. `GET /analytics/correlation-regime/moderate` returns 200 (after status fix)
9. Zero `.toFixed()`, `.toLocaleTimeString()`, or inline `new Intl` in any terminal component
10. `svelte-check` — zero errors
11. `pnpm build` — clean
12. `make test` — green (correlation_regime.py change)

## COMMIT

```
fix(terminal): API contract wiring — 6 breaks + 5 formatter violations

Fix 1: /market-data/quote/ → /market-data/historical/ + OHLCV mapping
Fix 2: nav-history response shape (dates[]+nav_series[] not [{date,nav}])
Fix 3: execute-trades path (not rebalance/execute)
Fix 4: correlation-regime status filter aligned with model state machine
Fix 5-6: taa_regime_state populated via risk_calc worker
Fix 7-11: .toFixed()/.toLocaleTimeString() → @investintell/ui formatters

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Push to origin/fix/terminal-api-contract-wiring.
