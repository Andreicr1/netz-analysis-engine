---
module: Wealth Ingestion
date: 2026-03-19
problem_type: integration_issue
component: background_job
symptoms:
  - "import_from_yahoo() instantiates YahooFinanceProvider() directly instead of using get_instrument_provider() factory"
  - "run_ingestion() worker uses deprecated Fund model and calls yfinance directly"
  - "No background worker exists to fetch NAV history for instruments_universe"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [provider-factory, instrument-ingestion, legacy-worker, nav-timeseries, wealth]
---

# Troubleshooting: Legacy NAV Worker Bypasses Provider Factory and Uses Deprecated Fund Model

## Problem
The wealth vertical's NAV ingestion had two related issues: (1) the import endpoint (`import_from_yahoo`) directly instantiated `YahooFinanceProvider()` instead of using the `get_instrument_provider()` factory, and (2) the legacy `run_ingestion()` worker queried the deprecated `Fund` model and called yfinance directly, completely bypassing the `InstrumentDataProvider` protocol. No worker existed to fetch NAV history for the new `instruments_universe` table.

## Environment
- Module: Wealth Ingestion Workers
- Stack: Python 3.11, FastAPI, SQLAlchemy (async), PostgreSQL 16
- Affected Component: `workers/ingestion.py`, `routes/instruments.py`, `workers/` (missing new worker)
- Date: 2026-03-19

## Symptoms
- `import_from_yahoo()` in `routes/instruments.py:139` imported `YahooFinanceProvider` directly — would not switch to FEFundInfo when `feature_fefundinfo_enabled=true`
- `run_ingestion()` in `workers/ingestion.py` used `select(Fund)` instead of `select(Instrument)` — Fund model is deprecated
- `run_ingestion()` called `yf.download()` directly instead of using provider's `fetch_batch_history()`
- No worker endpoint existed to populate `nav_timeseries` for the `instruments_universe` table

## What Didn't Work

**Direct solution:** The problem was identified through architecture analysis and fixed on the first attempt. The provider factory pattern was already established (`get_instrument_provider()` in `app/services/providers/__init__.py`) but not consistently used.

## Solution

**Three coordinated changes:**

### 1. Fix import endpoint to use factory

```python
# Before (broken) — routes/instruments.py:139
from app.services.providers.yahoo_finance_provider import YahooFinanceProvider

provider = YahooFinanceProvider()
raw_data = await asyncio.to_thread(provider.fetch_batch, body.tickers)

# After (fixed):
from app.services.providers import get_instrument_provider

provider = get_instrument_provider()
raw_data = await asyncio.to_thread(provider.fetch_batch, body.tickers)
```

### 2. Create new instrument ingestion worker

New file: `backend/app/domains/wealth/workers/instrument_ingestion.py`

Key design decisions following `benchmark_ingest.py` pattern:
- Advisory lock `900_010` (unique, non-colliding)
- Provider factory `get_instrument_provider()` — never direct yfinance
- `run_in_executor()` with dedicated `ThreadPoolExecutor` for blocking provider calls
- Data validation: NaN ratio > 5%, zero/negative prices, empty DataFrames
- Log return computation: `math.log(close / prev_close)`
- Chunked upserts: `UPSERT_CHUNK = 5000` to prevent WAL bloat
- Conflict resolution: `ON CONFLICT (instrument_id, nav_date) DO UPDATE`
- Period mapping: `{30: "1mo", 90: "3mo", 365: "1y", 730: "2y", 1095: "3y"}`

```python
async def run_instrument_ingestion(
    db: AsyncSession,
    org_id: uuid.UUID,
    lookback_days: int = 30,
) -> dict[str, int | list[str]]:
    # 1. Query instruments_universe for active instruments with ticker
    # 2. Batch fetch via get_instrument_provider().fetch_batch_history()
    # 3. Validate data quality (NaN ratio, zero prices)
    # 4. Compute log returns
    # 5. Chunked upsert to nav_timeseries
```

### 3. Register worker route

```python
@router.post("/run-instrument-ingestion")
async def trigger_run_instrument_ingestion(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(default=30, ge=1, le=1095),
    ...
) -> WorkerScheduledResponse:
```

### 4. Deprecate legacy worker (not removed)

```python
# workers/ingestion.py — added at entry point
logger.warning("run_ingestion is deprecated — use run_instrument_ingestion instead")
```

## Why This Works

1. **Root cause:** The codebase had two provider usage patterns — the old direct-instantiation pattern and the new factory pattern. The factory (`get_instrument_provider()`) dynamically returns `YahooFinanceProvider` or `FEFundInfoProvider` based on the `feature_fefundinfo_enabled` setting. Direct instantiation bypasses this entirely.

2. **The factory solves provider switching:** When the feature flag changes, all callers using the factory automatically get the new provider. Direct instantiation would require finding and updating every call site.

3. **Model migration:** The `Fund` model maps to the deprecated `funds_universe` table. The `Instrument` model maps to the current `instruments_universe` table. The legacy worker wrote `instrument_id: fund.fund_id` which only worked because the column names aligned by coincidence — it would break if the tables diverged.

4. **Worker signature matches existing patterns:** The new worker follows the exact `benchmark_ingest.py` pattern (advisory lock, retry, thread executor, chunked upsert, data validation) ensuring consistency across the worker fleet.

## Prevention

- **Always use `get_instrument_provider()`** — never import `YahooFinanceProvider` directly in route/worker code. The only place `YahooFinanceProvider` should be directly referenced is inside the factory itself.
- **Never use `select(Fund)`** in new code — `Fund` is deprecated. Use `Instrument` from `instruments_universe`.
- **Follow the worker template:** New workers should mirror `benchmark_ingest.py` (advisory lock, dedicated executor, chunked upsert, data validation).
- **Lock ID uniqueness:** Check existing `LOCK_ID` values in all workers before assigning a new one. Current range: 900_002 through 900_010.

## Related Issues

No related issues documented yet.
