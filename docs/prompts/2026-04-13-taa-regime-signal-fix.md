# TAA Regime Signal Fix — 3 Missing Signals + Staleness Check

**Date:** 2026-04-13
**Branch:** `fix/taa-regime-signals` (off `main`)
**Scope:** Backend only — zero migrations, zero frontend changes
**Risk:** LOW — fixes data-fetching gap, no schema changes
**Priority:** HIGH — current RISK_ON classification may be wrong (35% signal surface invisible)

---

## Problem Statement

The `_fetch_regime_inputs()` function in `risk_calc.py` (lines 1150-1224) supplies only **7 of 10 signals** to `classify_regime_multi_signal()`. Three signals worth **35% of total weight** are never fetched:

| Missing Signal | Weight | series_id | Computation |
|---|---|---|---|
| DXY Z-score | 10% | `DTWEXBGS` | 1Y rolling Z-score via `_compute_series_zscore(db, "DTWEXBGS", 252)` |
| Energy Shock | 10% | `DCOILWTICO` | `max(_ramp(crude_z, 0.5, 3.0), _ramp(crude_roc, 0.0, 50.0))` |
| CFNAI | 15% | `CFNAI` | Direct read from `macro_data` |

All three series ARE ingested by `macro_ingestion` worker (confirmed in `regional_macro_service.py` lines 127, 173, 181). The data exists in `macro_data` — it's just not being queried.

The **root cause** is code duplication: `get_current_regime()` in `regime_service.py` (line 795) uses helper functions (`_compute_dxy_zscore`, `_compute_series_zscore`, `_compute_series_roc`) and passes all 10 signals. But `_fetch_regime_inputs()` in `risk_calc.py` hand-rolled its own SQL queries and missed 3 signals. Two implementations of the same logic = divergence bug.

**Secondary issue:** `_fetch_regime_inputs()` performs no staleness check on macro data. `get_latest_macro_values()` in `regime_service.py` (line 625) already has staleness logic with `STALENESS_DAILY=5` / `STALENESS_MONTHLY=45`. The risk_calc path silently classifies on arbitrarily stale data.

---

## Solution: Single Authoritative Signal Builder

Create ONE public function in `regime_service.py` that builds the full 10-signal input dict. Both call sites use it. `_fetch_regime_inputs()` in `risk_calc.py` is deleted.

### Step 1 — New function in `regime_service.py`

Create `build_regime_inputs(db: AsyncSession, as_of_date: date | None = None) -> dict[str, float | None]`:

```
Location: backend/quant_engine/regime_service.py
Insert after: _compute_dxy_zscore() at line ~793
```

This function:

1. Fetches latest values for ALL regime-relevant series from `macro_data`, respecting `as_of_date` ceiling (if provided, filter `obs_date <= as_of_date`; if None, use latest available).
2. Applies staleness checks using the existing `STALENESS_DAILY` / `STALENESS_MONTHLY` constants. If a series is stale, log warning and return `None` for that signal (matches `get_latest_macro_values` behavior).
3. Computes derived signals:
   - `yield_curve_spread` = DGS10 - DGS2
   - `cpi_yoy` = (CPI_current / CPI_12m_ago - 1) * 100
   - `fed_funds_delta_6m` = DFF_current - DFF_6m_ago
   - `dxy_zscore` = Z-score of `DTWEXBGS` vs 1Y rolling mean (reuse `_compute_series_zscore`)
   - `energy_shock` = `max(_ramp(crude_z, 0.5, 3.0), _ramp(crude_roc, 0.0, 50.0))` where crude_z = Z-score of `DCOILWTICO` (1Y) and crude_roc = RoC of `DCOILWTICO` (3m) (reuse `_compute_series_zscore` and `_compute_series_roc`)
   - `cfnai` = direct value from `CFNAI` series
4. Returns dict with keys: `vix`, `yield_curve_spread`, `cpi_yoy`, `sahm_rule`, `hy_oas`, `baa_spread`, `fed_funds_delta_6m`, `dxy_zscore`, `energy_shock`, `cfnai`

**Important nuance for `as_of_date`:** The existing `_compute_series_zscore` and `_compute_series_roc` functions query for the latest data globally (no date ceiling). The new function must thread `as_of_date` through these calls. If `as_of_date` is provided, add `WHERE obs_date <= :as_of` to the Z-score and RoC queries. This matters for backfill correctness (worker runs with `eval_date = date.today()`, but historical recalcs need point-in-time accuracy).

The cleanest approach: make `_compute_series_zscore` and `_compute_series_roc` accept an optional `as_of_date: date | None = None` parameter. If provided, add the filter. If None, behavior is unchanged (latest available). Do the same for `_compute_ff_delta_6m` and `_compute_dxy_zscore`.

**Staleness integration:** The series_ids and their staleness thresholds:

```python
REGIME_SERIES_STALENESS = {
    "VIXCLS": STALENESS_DAILY,           # VIX
    "DGS10": STALENESS_DAILY,            # 10Y yield
    "DGS2": STALENESS_DAILY,             # 2Y yield
    "CPIAUCSL": STALENESS_MONTHLY,       # CPI
    "SAHMREALTIME": STALENESS_MONTHLY,   # Sahm Rule
    "BAMLH0A0HYM2": STALENESS_DAILY,    # HY OAS
    "BAA10Y": STALENESS_DAILY,           # BAA spread
    "DFF": STALENESS_DAILY,              # Fed Funds
    "DTWEXBGS": STALENESS_DAILY,         # DXY
    "DCOILWTICO": STALENESS_DAILY,       # WTI Crude
    "CFNAI": 75,                          # Monthly, ~1mo publication lag
}
```

If `(today - obs_date).days > threshold`, that signal returns `None` and a warning is logged. `classify_regime_multi_signal` already handles None signals gracefully (excludes from weighted sum).

### Step 2 — Refactor `get_current_regime()` in `regime_service.py`

Refactor `get_current_regime()` (lines 795-866) to call `build_regime_inputs(db)` instead of manually computing each signal. This eliminates the second implementation. The function currently:
- Calls `get_latest_macro_values(db)` for base series
- Calls `_compute_ff_delta_6m(db)` for fed funds delta
- Calls `_compute_dxy_zscore(db)` for DXY Z-score
- Computes energy shock inline from crude Z + RoC
- Reads CFNAI from macro dict

After refactor, it should:
```python
async def get_current_regime(db, config=None, *, fallback_regime="RISK_ON"):
    inputs = await build_regime_inputs(db)
    # Check if we have enough data to classify
    if inputs.get("vix") is not None or inputs.get("hy_oas") is not None or inputs.get("energy_shock") is not None:
        regime, reasons = classify_regime_multi_signal(**inputs, config=config)
        # ... build RegimeRead with as_of from latest macro_data obs_date
    else:
        return RegimeRead(regime=fallback_regime, ...)
```

### Step 3 — Refactor `_compute_and_persist_taa_state()` in `risk_calc.py`

File: `backend/app/domains/wealth/workers/risk_calc.py`

**Delete** `_fetch_regime_inputs()` entirely (lines 1150-1224).

**Modify** `_compute_and_persist_taa_state()` (line 1249-1259) to:
```python
# ── 1. Fetch macro inputs and classify regime (once, global) ──
from quant_engine.regime_service import build_regime_inputs
inputs = await build_regime_inputs(db, as_of_date=eval_date)
regime, reasons = classify_regime_multi_signal(**inputs)
```

This is the ONLY change in risk_calc.py. Everything below line 1259 stays identical.

### Step 4 — Tests

**File:** `backend/tests/quant_engine/test_regime_signal_completeness.py` (new)

Test 1 — `test_build_regime_inputs_returns_all_10_keys`:
- Mock `macro_data` with values for all 11 raw series (VIXCLS, DGS10, DGS2, CPIAUCSL, SAHMREALTIME, BAMLH0A0HYM2, BAA10Y, DFF, DTWEXBGS, DCOILWTICO, CFNAI)
- Call `build_regime_inputs(db)`
- Assert returned dict has exactly 10 keys: `vix`, `yield_curve_spread`, `cpi_yoy`, `sahm_rule`, `hy_oas`, `baa_spread`, `fed_funds_delta_6m`, `dxy_zscore`, `energy_shock`, `cfnai`
- Assert none are None when all data is fresh

Test 2 — `test_10_signals_vs_7_signals_score_differs`:
- Call `classify_regime_multi_signal` with 7 signals (old behavior: dxy_zscore=None, energy_shock=None, cfnai=None)
- Call again with 10 signals (add moderate stress values: dxy_zscore=1.2, energy_shock=45, cfnai=-0.5)
- Assert composite stress scores differ
- Assert the 10-signal version produces a higher stress score (these values indicate stress)

Test 3 — `test_staleness_nullifies_signal`:
- Mock a series with `obs_date` older than its staleness threshold
- Call `build_regime_inputs(db)`
- Assert the corresponding signal returns None

Test 4 — `test_as_of_date_ceiling`:
- Insert macro_data rows with dates before and after a cutoff
- Call `build_regime_inputs(db, as_of_date=cutoff)`
- Assert only pre-cutoff data is used

**File:** `backend/tests/quant_engine/test_regime_service.py` (existing — add test)

Test 5 — `test_classify_regime_all_signals_stressed`:
- Feed all 10 signals at their panic thresholds: vix=35, hy_oas=6.0, dxy_zscore=2.0, energy_shock=100, cfnai=-0.7, yield_curve=-0.5, baa_spread=2.5, fed_funds_delta_6m=1.5, sahm_rule=0.5, cpi_yoy=3.0 (below inflation override)
- Assert regime = "CRISIS"
- Assert stress_score >= 75

Test 6 — `test_classify_regime_all_signals_calm`:
- Feed all 10 at calm: vix=15, hy_oas=2.0, dxy_zscore=-0.5, energy_shock=0, cfnai=0.3, yield_curve=1.5, baa_spread=1.0, fed_funds_delta_6m=-0.25, sahm_rule=0.1, cpi_yoy=2.0
- Assert regime = "RISK_ON"
- Assert stress_score < 15

---

## Files Modified

| File | Action |
|---|---|
| `backend/quant_engine/regime_service.py` | ADD `build_regime_inputs()`, ADD `REGIME_SERIES_STALENESS` dict, MODIFY `_compute_series_zscore` / `_compute_series_roc` / `_compute_ff_delta_6m` / `_compute_dxy_zscore` to accept optional `as_of_date`, REFACTOR `get_current_regime()` to use `build_regime_inputs` |
| `backend/app/domains/wealth/workers/risk_calc.py` | DELETE `_fetch_regime_inputs()` (lines 1150-1224), MODIFY `_compute_and_persist_taa_state()` line 1250 to call `build_regime_inputs` |
| `backend/tests/quant_engine/test_regime_signal_completeness.py` | NEW — 4 tests |
| `backend/tests/quant_engine/test_regime_service.py` | ADD 2 tests |

## Files NOT Modified

- `allocation.py` (model) — no schema changes
- `allocation.py` (routes) — no route changes
- Frontend — zero changes
- Migrations — zero new migrations

---

## Validation Sequence

```bash
# 1. Type check
make typecheck

# 2. Run new tests
make test ARGS="-k test_regime_signal_completeness -v"
make test ARGS="-k test_classify_regime_all_signals -v"

# 3. Run existing regime tests (regression)
make test ARGS="-k regime -v"

# 4. Full gate
make check

# 5. Manual verification (if local DB available):
#    Run risk_calc worker, check logs for:
#    - "taa_regime_classified" with all 10 signals in reasons dict
#    - Presence of dxy, energy_shock, cfnai keys in reasons
#    - stress_score potentially different from 18.2
```

---

## What This Does NOT Fix (follow-up prompt)

- **Org-scoped regime (Problem 2):** `taa_regime_state` remains org-scoped. Raw regime is still computed per-org (redundantly). This requires a migration + new global table — separate PR.
- **Global regime endpoint:** No new `GET /allocation/regime` endpoint. Requires Problem 2 fix first.
- **Threshold recalibration:** Thresholds (25/50) stay as-is. After this fix, observe the full 10-signal composite for a few days before deciding if thresholds need adjustment.

---

## Commit Message

```
fix(quant): align TAA regime inputs — 3 missing signals (35% weight)

_fetch_regime_inputs() in risk_calc.py supplied only 7/10 signals to
classify_regime_multi_signal(). DXY Z-score (10%), energy shock (10%),
and CFNAI (15%) were never fetched despite data being available in
macro_data. Created build_regime_inputs() as single authoritative
signal builder in regime_service.py, eliminated duplication.

Added staleness checks on macro inputs (STALENESS_DAILY/MONTHLY).
Added as_of_date threading through Z-score/RoC helpers for backfill
correctness.
```
