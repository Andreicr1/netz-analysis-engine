# Phase 1b — Eliminar FRED API de Regional Case-Shiller (ler de macro_data)

**Status:** Ready
**Depends on:** Phase 1 (credit macro from DB) — must be completed first
**Estimated scope:** ~80 lines changed + 1 file deleted
**Risk:** Low (same pattern as Phase 1, smaller scope)

---

## Context

After Phase 1, `snapshot.py` reads all macro data from `macro_data` hypertable. But `regional.py` still calls FRED API directly via `fred_client.py` to fetch one of 20 Case-Shiller metro series during deep review. This adds ~500ms latency per deal analysis and is the **last remaining FRED API dependency** in the credit vertical.

The 20 metro series are static and defined in `CASE_SHILLER_METRO_MAP` in `backend/vertical_engines/credit/market_data/models.py`. Once added to the macro_ingestion worker, they'll be in `macro_data` and `regional.py` can read from DB.

**Goal:** Zero FRED API calls from credit vertical. Delete `fred_client.py`.

---

## Step 1: Add 20 Case-Shiller Metro Series to CREDIT_SERIES

**File:** `backend/quant_engine/regional_macro_service.py`

Append to `CREDIT_SERIES` list (created in Phase 1). The series IDs come from `CASE_SHILLER_METRO_MAP` in `backend/vertical_engines/credit/market_data/models.py`:

```python
# Regional Case-Shiller metros (all monthly, used by credit deep review)
SeriesSpec("NYXRSA", "real_estate_regional", "Case-Shiller New York", "monthly"),
SeriesSpec("LXXRSA", "real_estate_regional", "Case-Shiller Los Angeles", "monthly"),
SeriesSpec("MFHXRSA", "real_estate_regional", "Case-Shiller Miami", "monthly"),
SeriesSpec("CHXRSA", "real_estate_regional", "Case-Shiller Chicago", "monthly"),
SeriesSpec("DAXRSA", "real_estate_regional", "Case-Shiller Dallas", "monthly"),
SeriesSpec("HIOXRSA", "real_estate_regional", "Case-Shiller Houston", "monthly"),
SeriesSpec("WDXRSA", "real_estate_regional", "Case-Shiller Washington DC", "monthly"),
SeriesSpec("BOXRSA", "real_estate_regional", "Case-Shiller Boston", "monthly"),
SeriesSpec("ATXRSA", "real_estate_regional", "Case-Shiller Atlanta", "monthly"),
SeriesSpec("SEXRSA", "real_estate_regional", "Case-Shiller Seattle", "monthly"),
SeriesSpec("PHXRSA", "real_estate_regional", "Case-Shiller Phoenix", "monthly"),
SeriesSpec("DNXRSA", "real_estate_regional", "Case-Shiller Denver", "monthly"),
SeriesSpec("SFXRSA", "real_estate_regional", "Case-Shiller San Francisco", "monthly"),
SeriesSpec("TPXRSA", "real_estate_regional", "Case-Shiller Tampa", "monthly"),
SeriesSpec("CRXRSA", "real_estate_regional", "Case-Shiller Charlotte", "monthly"),
SeriesSpec("MNXRSA", "real_estate_regional", "Case-Shiller Minneapolis", "monthly"),
SeriesSpec("POXRSA", "real_estate_regional", "Case-Shiller Portland", "monthly"),
SeriesSpec("SDXRSA", "real_estate_regional", "Case-Shiller San Diego", "monthly"),
SeriesSpec("DEXRSA", "real_estate_regional", "Case-Shiller Detroit", "monthly"),
SeriesSpec("CLXRSA", "real_estate_regional", "Case-Shiller Cleveland", "monthly"),
```

`get_all_series_ids()` and `build_fetch_configs()` already handle CREDIT_SERIES with deduplication (Phase 1), so these will be picked up automatically by the macro_ingestion worker.

---

## Step 2: Rewrite regional.py to Read from DB

**File:** `backend/vertical_engines/credit/market_data/regional.py`

Replace the entire file. The function `fetch_regional_case_shiller()` must:
1. Accept `db: Session` as first parameter
2. Use `_fetch_series_from_db()` from `snapshot.py` (created in Phase 1) instead of `_fetch_fred_series()` from `fred_client.py`
3. Keep `resolve_metro_key()` unchanged (pure logic, no I/O)

```python
"""Regional Case-Shiller: read from macro_data hypertable.

Imports models.py and snapshot.py (for DB reader).
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from quant_engine.fred_service import apply_transform
from vertical_engines.credit.market_data.models import (
    CASE_SHILLER_METRO_MAP,
    GEOGRAPHY_TO_METRO,
)
from vertical_engines.credit.market_data.snapshot import _fetch_series_from_db

logger = structlog.get_logger()


def resolve_metro_key(deal_geography: str | None) -> str | None:
    """Resolve a free-form deal geography string to a Case-Shiller metro key.

    Uses substring matching against GEOGRAPHY_TO_METRO.
    Returns metro key (e.g. "miami") or None if unresolvable.
    """
    if not deal_geography:
        return None
    geo_lower = deal_geography.lower()
    for pattern, metro in GEOGRAPHY_TO_METRO.items():
        if pattern in geo_lower:
            return metro
    return None


def fetch_regional_case_shiller(
    db: Session,
    deal_geography: str | None,
    *,
    observations: int = 24,
) -> dict[str, Any] | None:
    """Read regional Case-Shiller HPI from macro_data hypertable.

    Returns dict with metro_key, fred_series, label + apply_transform output.
    Returns None if geography unresolvable or no data in DB.
    """
    metro_key = resolve_metro_key(deal_geography)
    if not metro_key:
        logger.info("case_shiller_regional_no_match", geography=deal_geography)
        return None

    fred_series = CASE_SHILLER_METRO_MAP.get(metro_key)
    if not fred_series:
        return None

    try:
        series_data = _fetch_series_from_db(db, [fred_series], limit=observations)
        obs = series_data.get(fred_series, [])
        if not obs:
            logger.warning(
                "case_shiller_regional_no_db_data",
                metro=metro_key,
                series=fred_series,
            )
            return None

        result: dict[str, Any] = apply_transform(fred_series, obs, transform="yoy_pct")
        result["metro_key"] = metro_key
        result["fred_series"] = fred_series
        result["label"] = f"Case-Shiller HPI — {metro_key.replace('_', ' ').title()}"
        logger.info(
            "case_shiller_regional_ok",
            metro=metro_key,
            series=fred_series,
            latest=result.get("latest"),
            trend=result.get("trend_direction"),
            source="macro_data",
        )
        return result
    except Exception as exc:
        logger.warning(
            "case_shiller_regional_failed",
            metro=metro_key,
            series=fred_series,
            error=str(exc),
        )
        return None
```

---

## Step 3: Update All Callers of fetch_regional_case_shiller

The function signature changed: `db: Session` is now the first parameter.

**File:** `backend/vertical_engines/credit/market_data/snapshot.py`

Find every call to `fetch_regional_case_shiller(deal_geography, ...)` and add `db` as first arg. The `db` parameter is already available in `_build_macro_snapshot_expanded()` (added in Phase 1).

```python
# BEFORE:
regional = fetch_regional_case_shiller(deal_geography, observations=24)

# AFTER:
regional = fetch_regional_case_shiller(db, deal_geography, observations=24)
```

**File:** `backend/vertical_engines/credit/market_data/service.py`

Same change. There are TWO call sites in `get_macro_snapshot()`:
- Line ~79 (cache hit path, when `deal_geography` is provided)
- Line ~144 (fresh fetch path, when `deal_geography` is provided)

Both need `db` as first argument. The `db: Session` parameter is already in `get_macro_snapshot()` signature.

```python
# BEFORE (both occurrences):
regional = fetch_regional_case_shiller(deal_geography, observations=24)

# AFTER (both occurrences):
regional = fetch_regional_case_shiller(db, deal_geography, observations=24)
```

---

## Step 4: Delete fred_client.py

**File:** `backend/vertical_engines/credit/market_data/fred_client.py`

After Steps 2-3, this file has zero callers. Delete it entirely.

**Verify no remaining imports:**
```bash
grep -r "fred_client" backend/
# Should return ZERO results
```

Also verify no remaining direct FRED API calls from credit:
```bash
grep -r "_fetch_fred_series" backend/
# Should return ZERO results (function was defined in fred_client.py, now deleted)
```

---

## Step 5: Update Tests

Search for tests that reference `fred_client`, `_fetch_fred_series`, or mock FRED API calls for regional Case-Shiller:

```bash
grep -r "fred_client\|_fetch_fred_series\|fetch_regional_case_shiller" backend/tests/
```

For each test found:
1. Replace FRED API mocks with `macro_data` table seeding (insert rows directly into the test DB)
2. Update `fetch_regional_case_shiller()` calls to include `db` parameter
3. If the test mocks `_fetch_fred_series` via `@patch`, change to seed the `MacroData` table instead

**Example test pattern:**
```python
def test_regional_case_shiller_from_db(db_session):
    """Case-Shiller regional reads from macro_data, not FRED API."""
    # Seed macro_data with Miami Case-Shiller observations
    for i in range(24):
        obs_date = date(2024, 1, 1) + timedelta(days=30 * i)
        db_session.add(MacroData(
            series_id="MFHXRSA",
            obs_date=obs_date,
            value=Decimal(str(300 + i * 2)),
            source="fred",
            is_derived=False,
        ))
    db_session.flush()

    result = fetch_regional_case_shiller(db_session, "Miami, FL", observations=24)
    assert result is not None
    assert result["metro_key"] == "miami"
    assert result["fred_series"] == "MFHXRSA"
    assert result["latest"] is not None
```

---

## Step 6: Update test_regional_macro_service.py

The tests updated in Phase 1 (`test_get_all_series_ids`, `test_build_fetch_configs`) will need the count adjusted again since we added 20 more series. Update the expected total to include the new Case-Shiller series (with deduplication).

---

## Validation

```bash
make check  # All tests pass

# Verify zero FRED API dependencies in credit vertical:
grep -r "fred_client" backend/                    # ZERO results
grep -r "_fetch_fred_series" backend/             # ZERO results
grep -r "httpx.get" backend/vertical_engines/credit/market_data/  # ZERO results (only regional.py used it via fred_client)
```

**Result:** The entire credit vertical's macro data comes from `macro_data` hypertable. Zero runtime FRED API calls. The `macro_ingestion` worker (wealth domain, runs daily) is the single source of all FRED data for both verticals.

---

## Files to Modify

| File | Action |
|---|---|
| `backend/quant_engine/regional_macro_service.py` | Add 20 Case-Shiller series to `CREDIT_SERIES` |
| `backend/vertical_engines/credit/market_data/regional.py` | Rewrite to read from DB via `_fetch_series_from_db()` |
| `backend/vertical_engines/credit/market_data/snapshot.py` | Update `fetch_regional_case_shiller()` calls to pass `db` |
| `backend/vertical_engines/credit/market_data/service.py` | Update `fetch_regional_case_shiller()` calls to pass `db` (2 sites) |
| `backend/vertical_engines/credit/market_data/fred_client.py` | **DELETE** |
| `backend/tests/test_regional_macro_service.py` | Update series count expectations |
| Any tests mocking `_fetch_fred_series` for regional | Rewrite to seed `macro_data` table |
