# Instrument Universe Ingestion Worker — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

The wealth vertical has an `Instrument` model (`instruments_universe` table) and a `NavTimeseries` model (`nav_timeseries` table). Instruments can be imported manually via `POST /api/v1/wealth/instruments/import/yahoo`, but there is **no background worker** that automatically fetches NAV history for the instrument universe.

The legacy `run_ingestion()` worker in `backend/app/domains/wealth/workers/ingestion.py` fetches NAV data using the deprecated `Fund` model and calls `yfinance` directly instead of using the `InstrumentDataProvider` protocol. This worker must be refactored.

There is also a minor issue: the import endpoint (`import_from_yahoo` in `routes/instruments.py`) instantiates `YahooFinanceProvider()` directly instead of using `get_instrument_provider()` factory. This must be fixed.

## Reference Files (read these first)

```
# Provider protocol and factory
backend/app/services/providers/protocol.py              # InstrumentDataProvider protocol + RawInstrumentData
backend/app/services/providers/__init__.py              # get_instrument_provider() factory
backend/app/services/providers/yahoo_finance_provider.py # Current provider (dev)

# Models
backend/app/domains/wealth/models/instrument.py         # Instrument model (instruments_universe)
backend/app/domains/wealth/models/nav.py                # NavTimeseries model (nav_timeseries)
backend/app/domains/wealth/models/__init__.py           # Model exports

# Existing workers (PATTERNS TO FOLLOW)
backend/app/domains/wealth/workers/ingestion.py         # Legacy NAV worker (refactor target)
backend/app/domains/wealth/workers/benchmark_ingest.py  # Reference pattern for new worker

# Worker routes
backend/app/domains/wealth/routes/workers.py            # Worker endpoint registration + _dispatch_worker()

# Import endpoint (fix target)
backend/app/domains/wealth/routes/instruments.py        # import_from_yahoo() at ~line 129

# Schemas
backend/app/domains/wealth/schemas/instrument.py        # InstrumentRead, InstrumentImportYahoo
```

## Architecture Decision

The legacy `Fund` model is deprecated. All new ingestion must use `Instrument` from `instruments_universe`. The provider factory (`get_instrument_provider()`) must be used everywhere — never instantiate providers directly.

```
Current (broken):
  import_from_yahoo() → YahooFinanceProvider() directly
  run_ingestion()     → yfinance directly, queries Fund model

Target:
  import_from_yahoo() → get_instrument_provider().fetch_batch()
  run_instrument_ingestion() → get_instrument_provider().fetch_batch_history()
                             → upsert nav_timeseries for all active Instruments
```

---

## Implementation Steps

### Step 1: Fix import endpoint to use factory

In `backend/app/domains/wealth/routes/instruments.py`, change `import_from_yahoo()`:

**Before:**
```python
provider = YahooFinanceProvider()
raw_data = await asyncio.to_thread(provider.fetch_batch, body.tickers)
```

**After:**
```python
from app.services.providers import get_instrument_provider

provider = get_instrument_provider()
raw_data = await asyncio.to_thread(provider.fetch_batch, body.tickers)
```

Remove the direct `YahooFinanceProvider` import if no longer needed.

### Step 2: Create instrument ingestion worker

Create `backend/app/domains/wealth/workers/instrument_ingestion.py`:

```python
async def run_instrument_ingestion(
    db: AsyncSession,
    org_id: uuid.UUID,
    lookback_days: int = 30,
) -> dict[str, int | list[str]]:
    """Fetch NAV history for all active instruments in the universe.

    1. Query instruments_universe for active instruments with ticker
    2. Batch fetch history via get_instrument_provider().fetch_batch_history()
    3. Compute 1d log returns
    4. Upsert to nav_timeseries with org_id scoping
    5. Return counts: instruments_processed, rows_upserted, skipped, errors
    """
```

**Follow the `benchmark_ingest.py` pattern exactly:**

- Advisory lock: use a unique lock ID (e.g., `900_010`) — check existing lock IDs in `workers.py` to avoid collisions
- RLS context: `await set_rls_context(db, org_id)` before queries and after commit
- Batch download: use `asyncio.get_event_loop().run_in_executor()` with a dedicated `ThreadPoolExecutor` for the blocking `provider.fetch_batch_history()` call
- Data validation: reject tickers with empty DataFrames, NaN ratio > 5%, or zero/negative Close prices
- Return computation: calculate log returns from Close prices (`np.log(close / close.shift(1))`)
- Chunked upserts: use `pg_insert(NavTimeseries).values(chunk).on_conflict_do_update()` with `CHUNK_SIZE = 5000`
- Conflict resolution: on conflict `(instrument_id, nav_date)` → update `nav`, `return_1d`, `source`, `currency`
- Source field: `"yahoo"` (will automatically become `"fefundinfo"` when provider switches)

**NavTimeseries row mapping:**
```python
{
    "organization_id": org_id,
    "instrument_id": instrument.instrument_id,
    "nav_date": nav_date,
    "nav": round(close_price, 6),
    "return_1d": round(return_1d, 8) if return_1d is not None else None,
    "return_type": "log",
    "currency": instrument.currency or "USD",
    "source": provider_source,  # from RawInstrumentData.source or "yahoo"
}
```

**Query for instruments:**
```python
stmt = (
    select(Instrument)
    .where(Instrument.is_active == True)
    .where(Instrument.ticker.isnot(None))
    .where(Instrument.ticker != "")
)
result = await db.execute(stmt)
instruments = result.scalars().all()
```

**Period logic:**
- `lookback_days=30` → `period="1mo"` for daily refreshes
- `lookback_days=365` → `period="1y"` for backfills
- `lookback_days=1095` → `period="3y"` for initial population
- Map to yfinance period strings: `{30: "1mo", 90: "3mo", 365: "1y", 730: "2y", 1095: "3y"}`

### Step 3: Register worker route

Add to `backend/app/domains/wealth/routes/workers.py`:

```python
@router.post("/run-instrument-ingestion")
async def run_instrument_ingestion_endpoint(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(default=30, ge=1, le=1095),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> WorkerScheduledResponse:
    """Fetch NAV history for all active instruments in the universe."""
    _require_investment_role(actor)
    return await _dispatch_worker(
        background_tasks,
        worker_name="instrument_ingestion",
        scope=str(org_id),
        coro_func=run_instrument_ingestion,
        db, org_id, lookback_days,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,
        org_id=org_id,
    )
```

Use `_HEAVY_WORKER_TIMEOUT` (600s) — this is a data-heavy worker.

### Step 4: Update route manifest

Add the new endpoint to `backend/manifests/routes.json`.

### Step 5: Deprecate legacy worker (optional, low priority)

In `run_ingestion()` in `workers/ingestion.py`, add a deprecation log:
```python
logger.warning("run_ingestion is deprecated — use run_instrument_ingestion instead")
```

Do NOT remove `run_ingestion` — it may still be called by existing cron jobs. Just mark it deprecated.

### Step 6: Tests

Create `backend/tests/test_instrument_ingestion.py`:

1. `test_queries_active_instruments_only` — only instruments with `is_active=True` and `ticker IS NOT NULL` are fetched
2. `test_uses_provider_factory` — calls `get_instrument_provider()`, not direct `YahooFinanceProvider()`
3. `test_upserts_nav_timeseries` — correct row mapping (instrument_id, nav_date, nav, return_1d, source)
4. `test_computes_log_returns` — verifies return calculation from Close prices
5. `test_skips_empty_tickers` — instruments with no ticker are skipped
6. `test_handles_api_error_gracefully` — provider failure doesn't crash the batch
7. `test_chunked_upsert` — verifies chunking for large batches (>5000 rows)
8. `test_idempotent_upsert` — running twice with same data doesn't duplicate rows
9. `test_import_endpoint_uses_factory` — verify `import_from_yahoo` uses `get_instrument_provider()`

Mock all provider calls — do not call real Yahoo Finance in tests. Use `unittest.mock.patch` on `get_instrument_provider`.

### Step 7: Verify

```bash
make check  # Must pass: lint + typecheck + architecture + all tests
```

---

## Critical Rules (from CLAUDE.md)

- `async def` + `AsyncSession` from `get_db_with_rls()` on all routes/workers
- `expire_on_commit=False` always
- `lazy="raise"` on ALL relationships — use `selectinload()` if needed
- `SET LOCAL` for RLS context (transaction-scoped)
- Advisory lock IDs must be unique — check `workers.py` for existing IDs before picking one
- Chunked upserts to prevent WAL bloat — CHUNK_SIZE = 5000 for NAV data
- Never-raises pattern for batch items — log warning per instrument, continue with next
- Provider factory `get_instrument_provider()` — never instantiate providers directly
- `asyncio.to_thread()` or `run_in_executor()` for blocking provider calls — never block the event loop

## What NOT to Do

- Do not modify `protocol.py` or `yahoo_finance_provider.py`
- Do not delete `run_ingestion()` — deprecate it, don't remove
- Do not add new models or migrations — use existing `Instrument` and `NavTimeseries`
- Do not add feature flags — the provider factory already handles provider selection
- Do not call yfinance directly — always go through the provider protocol
- Do not skip data validation — reject NaN-heavy tickers, log warnings for stale data
- Do not use `select(Fund)` anywhere in new code — `Fund` is deprecated, use `Instrument`
