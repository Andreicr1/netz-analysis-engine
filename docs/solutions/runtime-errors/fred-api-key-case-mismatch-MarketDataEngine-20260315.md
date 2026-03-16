---
module: MarketDataEngine
date: 2026-03-15
problem_type: runtime_error
component: service_object
symptoms:
  - "FRED API calls silently return no data — no error raised"
  - "Empty _FRED_API_KEY despite FRED_API_KEY env var being set"
  - "FredService raises ValueError('FRED API key must be provided') or returns empty observations"
root_cause: config_error
resolution_type: code_fix
severity: high
tags: [pydantic-settings, case-mismatch, getattr, silent-failure, fred-api]
---

# Troubleshooting: FRED API Key Case Mismatch — getattr() vs Pydantic Settings

## Problem

FRED macro data fetches silently returned empty results. The `_FRED_API_KEY` module constant was always empty despite the `FRED_API_KEY` environment variable being correctly set in `.env`.

## Environment

- Module: `vertical_engines/credit/market_data_engine.py`
- Python: 3.12+, Pydantic Settings v2
- Affected Component: MarketDataEngine (quant pipeline FRED data source)
- Date: 2026-03-15
- PR: #4 (Credit Engine Quant Architecture Parity)
- Commit: `acbdcbf`

## Symptoms

- FRED API calls silently return no data — no explicit error raised in normal flow
- `_FRED_API_KEY` evaluates to `""` at module level despite env var being set
- Downstream `FredService` either raises `ValueError` (when strict) or returns empty observation lists
- Quant engine macro snapshot has missing indicators, degrading regime detection accuracy

## What Didn't Work

**Direct solution:** The problem was identified during code review (Phase A review agents). The `getattr()` pattern masked the failure.

## Solution

**Code changes:**

```python
# Before (broken):
# market_data_engine.py:50-51
_FRED_BASE_URL = getattr(settings, "FRED_BASE_URL", None) or "https://api.stlouisfed.org/fred"
_FRED_API_KEY  = getattr(settings, "FRED_API_KEY", None) or ""

# After (fixed):
# market_data_engine.py:50-55
_FRED_BASE_URL = "https://api.stlouisfed.org/fred"
_FRED_API_KEY  = settings.fred_api_key or ""

# FRED rate limit: 120 requests per 60 seconds (2 req/s).
# 0.5s matches fred_ingestion.py MIN_REQUEST_INTERVAL.
_FRED_SLEEP_BETWEEN_CALLS = 0.5
```

The settings definition in `backend/app/core/config/settings.py:63`:
```python
fred_api_key: str = ""  # snake_case — Pydantic convention
```

## Why This Works

1. **Root cause:** Pydantic `BaseSettings` converts environment variables to snake_case attributes during initialization. `FRED_API_KEY` env var becomes `settings.fred_api_key`. The code used `getattr(settings, "FRED_API_KEY", None)` — uppercase attribute that doesn't exist.
2. **Why it was silent:** `getattr(settings, "FRED_API_KEY", None)` returns `None` (default), then `or ""` converts to empty string. No exception raised — the defensive fallback masked the bug.
3. **The fix** uses `settings.fred_api_key` directly (snake_case), which mypy and IDE autocomplete can validate.

**Bonus fix in same commit:** Rate limit sleep changed from `0.1s` to `0.5s` to match FRED's documented 120 req/60s limit (2 req/s).

## Prevention

- **Never use `getattr()` with Pydantic Settings.** Access attributes directly (`settings.fred_api_key`) so mypy catches typos at type-check time.
- **Never use `or ""` fallback on config values.** If a key is required, let it fail loudly. If optional, use `Optional[str] = None` in the settings model.
- **Add a startup smoke test** that asserts critical API keys are non-empty when their feature is enabled.
- **`make typecheck` catches this** — `getattr()` returns `object`, bypassing type narrowing.

## Related Issues

- See also: [Thread-unsafe TokenBucketRateLimiter](thread-unsafe-rate-limiter-FredService-20260315.md) — fixed in same PR, same service
- See also: [Monolith to Modular Package](../architecture-patterns/monolith-to-modular-package-with-library-migration.md) — EDGAR upgrade that consumes FRED data
