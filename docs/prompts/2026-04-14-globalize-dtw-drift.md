# Globalize DTW Drift Score

**Date:** 2026-04-14
**Branch:** `feat/globalize-dtw-drift`
**Priority:** MEDIUM — unblocks dtw_drift_score for all 5,385 instruments (currently 0% coverage)
**Sessions:** 1

---

## Problem

`dtw_drift_score` in `fund_risk_metrics` is **100% empty** (0/5,385 rows) because it's only computed by the org-scoped `risk_calc` worker (lock 900_007), which requires instruments imported into `instruments_org` + assigned to `allocation_blocks`.

The global worker `run_global_risk_metrics` (lock 900_071) explicitly sets `dtw_drift_score = None` for all 5,385+ instruments it computes.

This made sense when DTW drift was a portfolio-context metric (drift vs your allocation block peers). But the model has evolved:

1. **The optimizer uses the full catalog** (all instruments_universe except private funds and BDCs) — not just org-imported instruments.
2. **Scoring, screening, and DD reports** read from `fund_risk_metrics` globally — they expect `dtw_drift_score` to be populated.
3. **DTW drift is an intrinsic fund property** — it measures how much a fund's recent return pattern has diverged from its peer group average. The peer group is defined by `strategy_label`, which is a global catalog attribute, not an org-scoped one.

Current architecture:
```
global_risk_metrics (900_071)  →  computes everything EXCEPT dtw_drift  →  org_id = NULL
risk_calc (900_007, org)       →  overwrites with dtw_drift per block   →  org_id = {org}
```

Target architecture:
```
global_risk_metrics (900_071)  →  computes everything INCLUDING dtw_drift by strategy  →  org_id = NULL
risk_calc (900_007, org)       →  no longer needed for dtw_drift (may still exist for org-specific overrides)
```

---

## Solution

### 1. Add `_compute_global_dtw_scores()` to `risk_calc.py`

New function near `_compute_block_dtw_scores()` (~line 740). Reuses the same `compute_dtw_drift_batch()` from `quant_engine/drift_service.py`.

```python
async def _compute_global_dtw_scores(
    db: AsyncSession,
    computed: list[tuple[_FundSnapshot, dict]],
    as_of_date: date,
    strategy_map: dict[str, str | None],  # instrument_id → strategy_label
    dtw_window: int = 252,
) -> dict[str, DtwDriftResult]:
    """Compute DTW drift scores grouped by strategy_label (global).

    Instead of allocation blocks (org-scoped), groups funds by their
    strategy_label from mv_unified_funds. Each strategy group uses its
    equal-weight average as the benchmark.

    Funds with no strategy_label are grouped under "__unclassified__".
    Groups with < 2 funds get degraded status (no peer comparison possible).
    """
```

Key differences from `_compute_block_dtw_scores()`:
- Groups by `strategy_label` instead of `block_id`
- No dependency on `instruments_org` or `allocation_blocks`
- Uses `mv_unified_funds.strategy_label` (already available in global context)
- Same `compute_dtw_drift_batch()` call, same DTW window (252 days)

### 2. Wire into `run_global_risk_metrics()`

In `run_global_risk_metrics()`, after Pass 1 (metric computation) and before the upsert:

```python
# Build strategy_label map from mv_unified_funds
strategy_stmt = text("""
    SELECT ticker, strategy_label FROM mv_unified_funds
    WHERE ticker IS NOT NULL AND strategy_label IS NOT NULL
""")
strategy_rows = (await db.execute(strategy_stmt)).all()
ticker_to_strategy = {r[0]: r[1] for r in strategy_rows}

# Map instrument_id → strategy_label via ticker
strategy_map = {}
for fund in all_funds:
    if fund.ticker and fund.ticker in ticker_to_strategy:
        strategy_map[str(fund.instrument_id)] = ticker_to_strategy[fund.ticker]

# Compute global DTW drift
dtw_scores = await _compute_global_dtw_scores(
    db, computed, eval_date, strategy_map,
)
```

Then in the upsert loop, replace:
```python
metrics["dtw_drift_score"] = None  # ← current (line 2015)
```
With:
```python
dtw_result = dtw_scores.get(
    str(fund.instrument_id),
    DtwDriftResult(score=None, status=DtwDriftStatus.degraded, reason="not in dtw batch"),
)
metrics["dtw_drift_score"] = round(dtw_result.score_or_default(0.0), 6) if dtw_result.is_usable else None
```

### 3. Update `run_risk_calc()` (org-scoped)

The org-scoped worker no longer needs to compute DTW drift. Two options:

**Option A (recommended):** Remove DTW drift from `run_risk_calc()` entirely. The global worker handles it. The org worker still exists for org-specific overrides (future: custom scoring weights per tenant).

**Option B:** Keep DTW in org worker but use allocation blocks as before. Org-scoped DTW would overwrite the global strategy-based DTW with a block-specific one. This adds complexity for marginal value — only do this if tenants need block-level drift distinct from strategy-level drift.

Go with Option A.

### 4. Batch processing for DTW

DTW is O(n^2) per group. Strategy groups can be large (e.g., "Long/Short Equity" might have 500+ funds). Process in sub-batches if needed:

- Groups with > 500 funds: split into sub-batches of 200, use the full group mean as benchmark for all sub-batches
- Groups with 2-500 funds: process as-is
- Groups with < 2 funds: degraded status

### 5. Update docstring and CLAUDE.md

- `run_global_risk_metrics` docstring: remove "no DTW drift" caveat
- CLAUDE.md worker table: note that `global_risk_metrics` now includes DTW drift
- Remove the statement "Org-scoped `risk_calc` (lock 900_007) can overwrite rows with DTW drift" — no longer accurate

---

## Also: Add return_5y and return_10y

While touching `run_global_risk_metrics`, add two return columns. The NAV history supports it (60% of instruments have 10Y+ data).

### 1. Migration

```python
# Add columns to fund_risk_metrics
op.add_column("fund_risk_metrics", sa.Column("return_5y_ann", sa.Numeric(12, 8), nullable=True))
op.add_column("fund_risk_metrics", sa.Column("return_10y_ann", sa.Numeric(12, 8), nullable=True))
```

### 2. Computation in `_compute_single_fund_metrics()`

Find where `return_3y_ann` is computed (uses `compute_annualized_return()` from `return_statistics_service.py`). Add:

```python
# 5Y annualized return (requires 1825+ days of NAV)
if len(returns) >= 1260:  # ~5Y trading days
    metrics["return_5y_ann"] = compute_annualized_return(returns[-1260:], periods_per_year=252)

# 10Y annualized return (requires 3650+ days of NAV)
if len(returns) >= 2520:  # ~10Y trading days
    metrics["return_10y_ann"] = compute_annualized_return(returns[-2520:], periods_per_year=252)
```

### 3. Update start_date in `run_global_risk_metrics()`

Current: `start_date = eval_date - timedelta(days=3 * 365 + 30)` (line 1799)

Change to: `start_date = eval_date - timedelta(days=10 * 365 + 60)` to fetch enough NAV history for 10Y returns.

**Impact:** larger NAV query per batch. Mitigate by only fetching 10Y for funds that have data (check `min(nav_date)` in the batch).

### 4. Schema + route updates

- Add `return_5y_ann` and `return_10y_ann` to `FundRiskMetricsRead` schema
- Add to screener sort options
- Add to scoring service if desired (not mandatory — scoring currently uses 1Y/3Y only)

---

## Constraints

- Do NOT change the `compute_dtw_drift_batch()` function in `drift_service.py` — it's correct
- Do NOT change DTW threshold or scoring interpretation — just the grouping mechanism
- Do NOT remove `risk_calc` worker entirely — it may still serve org-specific overrides
- Do NOT change `fund_risk_metrics` table PK or unique constraint — the NULLS NOT DISTINCT index (migration 0093) handles global vs org-scoped rows
- Must pass `make check` (lint + typecheck + test)
- Run `run_global_risk_metrics` after deployment to populate the new columns

## Verification

1. `dtw_drift_score` has >80% coverage after global worker runs (vs 0% today)
2. `return_5y_ann` populated for ~82% of instruments (those with 5Y+ NAV)
3. `return_10y_ann` populated for ~60% of instruments (those with 10Y+ NAV)
4. Screener and scoring routes serve the new data without regression
5. Existing org-scoped `risk_calc` still works (just no longer writes DTW)
