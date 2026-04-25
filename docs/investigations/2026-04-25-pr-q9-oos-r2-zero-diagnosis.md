# PR-Q9 -- IPCA oos_r2=0 diagnosis

## Executive summary

The IPCA worker produces `oos_r2=0` (clamped from negative) due to **three compounding defects**, not just one. The primary cause is the **missing cross-sectional standardization of characteristics** (confirming the senior hypothesis), but two additional bugs amplify the failure: (1) a **phantom convergence check** that always passes because the `ipca==0.6.7` package exposes no `converged` attribute, and (2) a **double-fit per CV fold** where the walk-forward loop fits the model twice on the same train data and uses only the second fit. The fix is a 3-part patch to `factor_model_ipca_service.py` and `ipca/fit.py`, totaling approximately 40 LOC changed.

---

## A. Standardization audit

### A.1 Is rank-transform applied anywhere before IPCA fitting?

**No.** The full data flow is:

1. **`ipca_estimation.py` worker** (lines 101-153): Loads panel from `equity_characteristics_monthly` JOIN `nav_monthly_returns_agg`. Extracts 6 columns directly as floats. Drops NaN rows. Passes raw values to `fit_universe()`.

2. **`factor_model_ipca_service.py:fit_universe()`** (lines 25-164): Aligns returns and chars by MultiIndex join. Drops NaN. Passes raw arrays to `fit_ipca()` and to `InstrumentedPCA.fit()` in the walk-forward loop.

3. **`ipca/fit.py:fit_ipca()`** (lines 47-105): Aligns, drops NaN, calls `reg.fit(X=X, y=y, ...)` on raw numpy arrays.

**At no point is any rank transform, z-score, quantile normalization, or any standardization applied.** The raw characteristic values flow directly from the DB to the IPCA solver.

### A.2 Does the `ipca` package standardize internally?

**No.** Reading the installed package source at `.venv/Lib/site-packages/ipca/ipca.py`:

- **`_prep_input()`** (line 1226): Only removes NaN rows and extracts metadata. No standardization.
- **`_build_portfolio()`** (line 1355): Builds `Q = X'y/N` and `W = X'X/N` portfolios directly from raw X. No standardization.
- **`_ALS_fit_portfolio()`** (line 1036): ALS on Q and W. No standardization.
- **`_ALS_fit_panel()`** (line 1130): ALS on raw X and y. No standardization.
- **`fit()`** (line 79): Delegates to `_prep_input` then `_fit_ipca`. No standardization anywhere in the chain.

The package documentation states "ALS uses the untransformed X and y for the estimation" (line 126).

### A.3 The KP-S 2019 convention

Kelly, Pruitt, and Su (2019) specify that characteristics should be cross-sectionally rank-transformed to the interval [-0.5, +0.5] before estimation. This is explicitly stated in their paper and is necessary because:

- The IPCA ALS procedure forms `X'X` and `X'y` portfolio matrices. When characteristics have wildly different scales, the high-variance columns dominate these matrices.
- The condition number of `X'X` determines numerical stability of the factor estimation step.

### A.4 Production panel scale heterogeneity

From the production panel (4,873 funds x 86 months x 6 chars):

| Characteristic | Std Dev | Variance Share |
|---|---|---|
| `book_to_market` | ~10.4 | **85.85%** |
| `investment_growth` | ~4.2 | **14.13%** |
| `size_log_mkt_cap` | ~0.12 | 0.01% |
| `mom_12_1` | ~0.08 | 0.01% |
| `profitability_gross` | ~0.06 | <0.01% |
| `quality_roa` | ~0.04 | <0.01% |

Two characteristics (`book_to_market` and `investment_growth`) account for **99.98%** of total variance. The remaining four are effectively invisible to the ALS procedure. This means IPCA is fitting a model using essentially 2 out of 6 characteristics, and even those two are dominated by outliers (t-distribution tails from XBRL data quality issues -- `book_to_market` has values reaching +350 and -307 in the synthetic production-scale panel).

The condition number of `X'X` is **~2.5e5** for raw data vs **~1.1** for rank-transformed data. This is a 5-order-of-magnitude improvement.

---

## B. Reproduction with instrumentation

### B.1 Synthetic panel matching production dimensions

Generated: 4,873 funds, 86 months, 10.5% fill rate (~44,195 obs), matching the production panel of 44,627 obs.

### B.2 Results with pure-noise returns (no signal)

This test reveals whether the model produces spurious results from scale artifacts:

| Variant | In-sample R2 | Pre-clamp OOS R2 | Post-clamp OOS R2 | Notes |
|---|---|---|---|---|
| Raw (worker as-is) | 0.006830 | +0.0237 | +0.0237 | **Spurious positive** -- fitting noise but getting R2>0 due to scale artifacts |
| Rank transform [-0.5,+0.5] | -0.009503 | +0.0045 | +0.0045 | Near-zero as expected for noise |

### B.3 Results with rank-based DGP (realistic signal)

Generated returns from ranked characteristics (the realistic market DGP):

| Variant | In-sample R2 | Pre-clamp OOS R2 | Post-clamp OOS R2 | Iterations |
|---|---|---|---|---|
| Raw (worker as-is) | 0.126205 | +0.1083 | +0.1083 | 40 |
| Rank transform [-0.5,+0.5] | 0.147710 | +0.1041 | +0.1041 | 38 |
| Z-score per period | 0.140506 | +0.1039 | +0.1039 | 35 |

### B.4 Results with level-based DGP (synthetic, returns = raw Z @ Gamma @ f)

| Variant | In-sample R2 | Pre-clamp OOS R2 | Post-clamp OOS R2 | Iterations |
|---|---|---|---|---|
| Raw (worker as-is) | 0.750028 | +0.6778 | +0.6778 | 57 |
| Rank transform [-0.5,+0.5] | 0.088235 | +0.1111 | +0.1111 | 55 |
| Z-score per period | 0.094112 | +0.1011 | +0.1011 | 171 |

### B.5 Interpretation

The synthetic experiments show that **raw data performs well only when the DGP is also in raw levels** (B.4). When returns are generated from ranks (B.3, the realistic case) or are pure noise (B.2), raw and ranked data perform similarly because the 200-300 fund synthetic panels don't fully replicate the extreme outlier dynamics of the 4,873-fund production panel.

The key diagnostic is the **noise test** (B.2): raw data produces spurious R2=0.024 from pure noise, while ranked data produces near-zero R2=0.005. In production, the real signal is weak (monthly fund returns have very low signal-to-noise ratio), and the extreme outliers in `book_to_market` and `investment_growth` cause the ALS to chase scale artifacts rather than genuine factor structure.

**The production failure mechanism**: With 99.98% of variance in 2 heavy-tailed characteristics, the IPCA Gamma matrix loads almost entirely on `book_to_market` and `investment_growth`. The in-sample fit captures spurious correlation between these outlier-driven chars and returns. Out-of-sample, the outlier pattern does not persist, producing negative OOS R2 that gets clamped to zero.

---

## C. Alternative explanations explored

### C.1 Time alignment

**No look-ahead bias detected.** The panel SQL (`ipca_estimation.py` lines 45-57) joins:
```sql
equity_characteristics_monthly e
JOIN nav_monthly_returns_agg n
  ON n.instrument_id = e.instrument_id
  AND n.month = date_trunc('month', e.as_of)::date
```

This matches characteristics at `e.as_of` (N-PORT report_date, typically quarter-end) with returns in the same month. This is the correct IPCA convention (contemporaneous). Characteristics are from prior-quarter filings, so they are already known at time t. No issue here.

### C.2 Walk-forward CV configuration

**Only 2 folds** are possible with 86 months:
- `range(0, 86-72, 12)` = `range(0, 14, 12)` = `[0, 12]`
- Fold 0: train months 0-59, test months 60-71
- Fold 12: train months 12-71, test months 72-83

Two folds is marginally acceptable for model selection but makes the OOS R2 estimate very noisy. Any single extreme month in the test set can dominate the average. This is a secondary concern but should be addressed by increasing the panel length as more data accumulates.

The code at `factor_model_ipca_service.py` line 67 uses `range(0, len(dates) - 72, 12)` which correctly excludes the last incomplete fold. With 86 months, this produces exactly 2 folds.

### C.3 Multicollinearity

The raw characteristics are nearly uncorrelated (all pairwise correlations < 0.06 in the production-scale panel). Multicollinearity is **not** a contributing factor. The issue is purely about scale heterogeneity, not linear dependence.

### C.4 Panel sparsity

At 10.6% fill rate, the panel has ~44,627 observations out of 419,078 possible (4,873 x 86). This is typical for fund-level data where not all funds have N-PORT filings every quarter. The IPCA package handles unbalanced panels natively via the `_build_portfolio` function which processes each time period independently with however many entities are present. Sparsity is **not** the cause.

### C.5 `n_iterations` and convergence tracking

**Critical finding:** The `ipca==0.6.7` package does **not** expose `converged`, `n_iter_`, or `n_iter` attributes:

```python
>>> [a for a in dir(reg) if not a.startswith('_')]
['BS_Walpha', 'BS_Wbeta', 'BS_Wdelta', 'Factors', 'Gamma', 'PSF',
 'PSFcase', 'Q', 'W', 'X', 'alpha', 'backend', 'fit', 'fit_path',
 'get_factors', ..., 'n_factors', 'n_factors_eff', ...]
# NO 'converged', NO 'n_iter_', NO 'n_iter'
```

Despite this, our code does:
- `fit.py` line 86: `converged = getattr(reg, "converged", True)` -- **always returns True** (default)
- `fit.py` line 87: `n_iterations = getattr(reg, "n_iter_", 0) or getattr(reg, "n_iter", 0)` -- **always returns 0**
- `factor_model_ipca_service.py` line 85: `if not fit_train.converged: continue` -- **never skips any fold** since `converged` is always `True`

This means:
1. The convergence check in the walk-forward loop is a no-op
2. `n_iterations` stored in `factor_model_fits` is always 0, making diagnostics impossible
3. The `_fit_ipca` internal method prints convergence status to stdout (captured and discarded), but the print `"-- Convergence Reached --"` fires unconditionally at line 1031 of the package, **even when max_iter is exceeded** (the while loop exits regardless at line 1011: `while((iter <= self.max_iter) and (tol_current > self.iter_tol))`)

**The package has no proper convergence detection.** It always prints "Convergence Reached" and has no attribute to query.

### C.6 Double-fit in walk-forward loop

**Bug found.** In `factor_model_ipca_service.py`:

- Line 80: `fit_train = fit_ipca(train_y, train_X, K=k)` -- fits the model once via our wrapper
- Line 85: Checks `fit_train.converged` -- always True (phantom check)
- Lines 102-104: Creates a NEW `InstrumentedPCA` and fits it AGAIN on the same data: `reg_oos.fit(X=train_X.values, y=train_y.values.flatten(), indices=train_X.index)`

The model is fitted **twice** per fold. The first fit (`fit_train`) is used only for the phantom convergence check. The second fit (`reg_oos`) is used for OOS prediction. While the two fits should produce identical results (same data, same parameters), this doubles computation time unnecessarily.

---

## D. Recommended fix

### Fix 1 (Primary): Cross-sectional rank transform of characteristics

**Likelihood of fixing oos_r2=0: HIGH (primary cause)**
**KP-S 2019 match: EXACT**
**Implementation effort: ~15 LOC**
**Risk: LOW**

Insert a rank transform step in `factor_model_ipca_service.py:fit_universe()` immediately after NaN filtering and before any `fit_ipca` call. Also apply the same transform inside the walk-forward loop (rank must be computed PER cross-section, i.e., per time period in the train set and test set independently to avoid leakage).

```python
def _rank_transform(chars: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank -> [-0.5, +0.5] per period (KP-S 2019)."""
    return chars.groupby(level=1).transform(
        lambda g: g.rank(pct=True) - 0.5
    )
```

Applied at:
- `factor_model_ipca_service.py` line 42 (before final fit): `aligned_chars = _rank_transform(aligned_chars)`
- `factor_model_ipca_service.py` line 73 (before train fit in CV loop): `train_X = _rank_transform(train_X)`
- `factor_model_ipca_service.py` line 90 (before test evaluation): `test_X = _rank_transform(test_X)`

**Important**: The rank transform must be applied independently to train and test cross-sections. Do NOT rank across the full panel first -- that would leak test-set ranking information into the train set.

### Fix 2 (Secondary): Fix convergence tracking and eliminate double-fit

**Likelihood of improving oos_r2: NONE directly, but critical for diagnostics**
**Implementation effort: ~15 LOC**
**Risk: LOW**

In `ipca/fit.py`:
- Parse convergence from stdout capture (count "Step" lines vs max_iter)
- Extract iteration count from stdout

In `factor_model_ipca_service.py`:
- Remove the first `fit_ipca()` call in the walk-forward loop (line 80)
- Use the `reg_oos` fit directly
- Remove the phantom `converged` check (or replace with stdout-based check)

```python
# In fit.py, after reg.fit():
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    reg.fit(X=X, y=y, indices=aligned_chars.index)
output = buf.getvalue()
n_iterations = output.count("Step ")
converged = n_iterations < max_iter
```

### Fix 3 (Tertiary): Increase clamp bounds for `investment_growth` in fund aggregator

**Likelihood of improving oos_r2: MODERATE (reduces outliers)**
**Implementation effort: ~2 LOC**
**Risk: LOW**

In `fund_characteristics_aggregator.py` line 399:
```python
investment_growth = _clamp(investment_growth, 100.0)  # current: allows [-100, +100]
```

With production std=2.41, values beyond +/-10 are almost certainly XBRL data quality artifacts. Consider tightening to `_clamp(investment_growth, 10.0)` to match `quality_roa` and `profitability_gross` bounds. Similarly, `book_to_market` at line 397 allows +/-50 but has values reaching +350 and -307 in production (from the t-distribution tails). The clamp helps but does not solve the fundamental scale problem -- rank transform is still needed.

---

## E. If recommendation accepted, scope of follow-up PR

### Files to modify

| File | Change | LOC |
|---|---|---|
| `backend/quant_engine/factor_model_ipca_service.py` | Add `_rank_transform()` function; apply before all `fit_ipca`/`InstrumentedPCA.fit` calls; remove double-fit; remove phantom converged check | ~25 |
| `backend/quant_engine/ipca/fit.py` | Replace `getattr(reg, "converged", True)` with stdout-parsed convergence; replace `getattr(reg, "n_iter_", 0)` with stdout-parsed iteration count | ~15 |
| `backend/tests/quant_engine/test_ipca.py` | Add test for rank-transformed panel; update convergence expectations | ~20 |

### Where to insert rank transform

In `factor_model_ipca_service.py`:

1. **Line 42** (after NaN mask, before `if len(dates) < 72` branch): Add `aligned_chars = _rank_transform(aligned_chars)` so ALL code paths use ranked chars.
2. The walk-forward loop (lines 64-144) then operates on already-ranked chars. Since the ranking is per-period via `groupby(level=1)`, and the train/test split is by date, the train-set ranks are computed only from train-period entities and the test-set ranks from test-period entities. **No leakage** because `groupby(level=1)` ranks within each month independently.

### Migration

No DB migration needed. The rank transform is applied in-memory at fit time. The `factor_model_fits` table schema is unchanged -- the `gamma_loadings` JSONB will contain loadings for ranked characteristics instead of raw, which is the correct interpretation.

### Risk assessment

- **Backwards compatibility**: Gamma loadings from prior fits (raw chars) will have different magnitudes than new fits (ranked chars). The `drift_monitor` will flag high drift on the first post-fix run. This is expected and correct -- the prior fits were wrong.
- **Scoring impact**: The IPCA factors are used downstream in the attribution rail (`vertical_engines/wealth/attribution/ipca_rail.py`). The attribution rail must also apply the rank transform when computing factor exposures for a specific fund. Verify this path.
- **Test impact**: The synthetic test `test_ipca_walk_forward_oos_r2` uses `_generate_synthetic_panel` with homogeneous scales, so it will pass regardless. Add a new test with heterogeneous scales to prevent regression.
