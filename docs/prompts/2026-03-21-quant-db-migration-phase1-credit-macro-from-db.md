# Phase 1 — Credit Market Data: Read from macro_data Instead of FRED API

**Status:** Ready
**Estimated scope:** ~200 lines changed
**Risk:** Low (refactor only, no new tables)

---

## Context

The credit vertical's `market_data` service calls FRED API directly via `vertical_engines/credit/market_data/fred_client.py`, building a `macro_snapshots` cache in PostgreSQL. Meanwhile, the wealth `macro_ingestion` worker already fetches ~45 FRED series daily and stores them in the `macro_data` hypertable (global table, no RLS).

The credit service uses ~32 FRED series (defined in `FRED_SERIES_REGISTRY` in `vertical_engines/credit/market_data/models.py`). Most overlap with what `macro_ingestion` already ingests. Some credit-specific series (real estate, mortgage, banking) are NOT in the wealth worker yet.

**Goal:** Eliminate the direct FRED API calls from `credit/market_data`. Read everything from `macro_data`. Expand the `macro_ingestion` worker to cover the missing credit series.

---

## Step 1: Identify Missing Series

Compare `FRED_SERIES_REGISTRY` (32 series in `backend/vertical_engines/credit/market_data/models.py`) against the series the wealth `macro_ingestion` worker fetches (defined in `REGION_SERIES` + `GLOBAL_SERIES` in `backend/quant_engine/regional_macro_service.py`).

**Already in macro_data (via wealth worker):** DGS10, DGS2, CPIAUCSL, A191RL1Q225SBEA, UNRATE, USREC(?), NFCI, UMCSENT, PAYEMS, VIXCLS, DFF

**NOT in macro_data (credit-only series):** BAA10Y, BAMLH0A0HYM2, SOFR, CSUSHPINSA, MSPUS, HOUST, PERMIT, EXHOSLUSM495S, MSACSR, MORTGAGE30US, MORTGAGE15US, OBMMIFHA30YF, DRCCLACBS, DRSFRMACBS, DRHMACBS, DRALACBN, NETCIBAL, CCLACBW027SBOG, DRCILNFNQ, TOTLL, DPSACBW027SBOG, STLFSI4, WRMFSL

**Action:** Add these missing series to the macro_ingestion worker as a new "CREDIT" domain batch.

## Step 2: Add Credit Series to macro_ingestion

File: `backend/quant_engine/regional_macro_service.py`

Add a new constant `CREDIT_SERIES` (similar to `REGION_SERIES` but for credit-specific macro data):

```python
CREDIT_SERIES: list[SeriesSpec] = [
    # Rates & Spreads
    SeriesSpec("BAA10Y", "credit_spreads", "Baa Corporate Spread (Moody's)", "daily"),
    SeriesSpec("BAMLH0A0HYM2", "credit_spreads", "ICE BofA HY Spread (OAS)", "daily"),
    SeriesSpec("SOFR", "rates", "SOFR Overnight Rate", "daily"),
    # Real Estate
    SeriesSpec("CSUSHPINSA", "real_estate", "Case-Shiller National HPI (NSA)", "monthly"),
    SeriesSpec("MSPUS", "real_estate", "Median Sales Price of Houses Sold", "quarterly"),
    SeriesSpec("HOUST", "real_estate", "Housing Starts (Total, SAAR)", "monthly"),
    SeriesSpec("PERMIT", "real_estate", "Building Permits (Total, SAAR)", "monthly"),
    SeriesSpec("EXHOSLUSM495S", "real_estate", "Existing Home Sales", "monthly"),
    SeriesSpec("MSACSR", "real_estate", "Monthly Supply of Houses", "monthly"),
    # Mortgage
    SeriesSpec("MORTGAGE30US", "mortgage", "30-Year Fixed Mortgage Rate", "weekly"),
    SeriesSpec("MORTGAGE15US", "mortgage", "15-Year Fixed Mortgage Rate", "weekly"),
    SeriesSpec("OBMMIFHA30YF", "mortgage", "FHA 30-Year Fixed Mortgage Rate", "weekly"),
    SeriesSpec("DRCCLACBS", "delinquency", "Credit Card Delinquency Rate", "quarterly"),
    SeriesSpec("DRSFRMACBS", "delinquency", "Single-Family Mortgage Delinquency Rate", "quarterly"),
    SeriesSpec("DRHMACBS", "delinquency", "Home Equity Loan Delinquency Rate", "quarterly"),
    # Credit Quality
    SeriesSpec("DRALACBN", "credit_quality", "Delinquency Rate — All Loans", "quarterly"),
    SeriesSpec("NETCIBAL", "credit_quality", "Net Charge-Off Rate — All Loans", "quarterly"),
    SeriesSpec("CCLACBW027SBOG", "credit_quality", "CRE Loans (commercial banks)", "weekly"),
    SeriesSpec("DRCILNFNQ", "credit_quality", "Delinquency Rate — C&I Loans", "quarterly"),
    # Banking Activity
    SeriesSpec("TOTLL", "banking", "Total Loans & Leases", "weekly"),
    SeriesSpec("DPSACBW027SBOG", "banking", "Total Deposits", "weekly"),
    SeriesSpec("STLFSI4", "banking", "St. Louis Fed Financial Stress Index", "weekly"),
    SeriesSpec("WRMFSL", "banking", "Money Market Fund Assets (retail)", "weekly"),
]
```

Update `get_all_series_ids()` and `build_fetch_configs()` to include these credit series as a 5th domain batch named `"CREDIT"`.

## Step 3: Rewrite credit/market_data/snapshot.py to Read from DB

File: `backend/vertical_engines/credit/market_data/snapshot.py`

The current `_build_macro_snapshot_expanded()` iterates `FRED_SERIES_REGISTRY`, calls `_fetch_fred_series()` for each, then calls `apply_transform()`. This must change to:

1. Accept a `db: Session` parameter (sync session — credit deep review uses sync context)
2. Query `macro_data` for all needed series in ONE batch query:
   ```python
   from sqlalchemy import select, func
   from app.shared.models import MacroData

   # Get latest N observations per series, ordered desc
   series_ids = list(FRED_SERIES_REGISTRY.keys())
   # Use a window function or subquery to get latest N per series
   ```
3. Convert the DB rows to the same `list[dict]` format that `apply_transform()` expects: `[{"date": "2026-03-20", "value": "4.25"}, ...]`
4. Apply the same transforms (`apply_transform` from `quant_engine.fred_service`)
5. Keep the same output structure (backward compatible)

**Key insight:** `apply_transform()` in `quant_engine/fred_service.py` expects observations as `list[dict]` with `date` and `value` keys, sorted descending. The DB query just needs to return the same shape.

## Step 4: Update credit/market_data/service.py

File: `backend/vertical_engines/credit/market_data/service.py`

The `get_macro_snapshot()` function currently calls `_build_macro_snapshot()` which hits FRED API. After Step 3, it needs to pass `db` to the builder:

```python
snapshot = _build_macro_snapshot(db=db, deal_geography=None)
```

The `db: Session` parameter is already available in the service (passed by caller). The function signature already receives `db: Session`.

## Step 5: Keep Regional Case-Shiller as API Call

The regional Case-Shiller fetch (`fetch_regional_case_shiller` in `regional.py`) is deal-specific — it fetches a metro-level series based on `deal_geography`. There are ~20 possible metros. Two options:

**Option A (recommended for now):** Keep as API call. It's only called when `deal_geography` is provided, which is per-deal during deep review. Low volume.

**Option B (future):** Add all 20 Case-Shiller metro series to `CREDIT_SERIES` and ingest daily. Overkill for now.

## Step 6: Update/Remove fred_client.py

After the migration, `backend/vertical_engines/credit/market_data/fred_client.py` will have no callers (except possibly regional.py for Case-Shiller metros). If regional.py still uses it, keep it. Otherwise delete.

## Step 7: Tests

- Run `make test ARGS="-k market_data"` to find existing tests
- Update tests that mock FRED API calls to instead seed `macro_data` rows
- Verify `_build_macro_snapshot_expanded()` produces identical output from DB as from API
- Verify `get_macro_snapshot()` still caches in `macro_snapshots` table

## Validation

```bash
make check  # All 1405+ tests must pass
```

The credit deep review E2E should produce identical macro snapshots since the data source (FRED) is the same — just read from DB instead of API.

---

## Files to Modify

| File | Action |
|---|---|
| `backend/quant_engine/regional_macro_service.py` | Add `CREDIT_SERIES`, update `get_all_series_ids()` and `build_fetch_configs()` |
| `backend/vertical_engines/credit/market_data/snapshot.py` | Rewrite `_build_macro_snapshot_expanded()` to read from `macro_data` table |
| `backend/vertical_engines/credit/market_data/service.py` | Pass `db` to builder |
| `backend/vertical_engines/credit/market_data/fred_client.py` | Remove or reduce to Case-Shiller only |
| Tests referencing `_fetch_fred_series` | Update mocks to seed DB |
