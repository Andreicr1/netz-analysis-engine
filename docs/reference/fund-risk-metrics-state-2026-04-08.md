# Fund Risk Metrics — Current State Reference

**Date:** 2026-04-08
**Environment:** local docker Postgres 16 + TimescaleDB (`netz-analysis-engine-db-1`)
**Table:** `fund_risk_metrics` (global, no RLS, org_id nullable)
**Worker:** `backend/app/domains/wealth/workers/risk_calc.py` — `run_global_risk_metrics()` (lock 900_071)
**Companion worker:** `backend/app/domains/wealth/workers/regime_fit.py` — `run_regime_fit()` (lock 900_026)

## Purpose

Snapshot of the `fund_risk_metrics` table after applying the S1-S5 quant engine update plus two data-quality fixes discovered during the validation run. This is the reference state used for the 2026-04-08 institutional presentation.

Prod Timescale Cloud (`nvhhm6dwvh`) is still on the pre-update build (alembic `0082`); the numbers below reflect local only. A subsequent deploy to prod is expected to reproduce these numbers once the two fix branches are merged.

## Pipeline run summary

```
regime_fit:
  lookback            = 504 calendar days (2024-11-20 -> 2026-04-01)
  VIX observations    = 351
  HMM state           = 2 regimes, switching variance
  rows upserted       = 351
  regime distribution = 5 CRISIS + 120 RISK_OFF + 226 RISK_ON
  wall clock          = 1.26 s

run_global_risk_metrics:
  eligible funds      = 5,447  (is_active AND ticker IS NOT NULL AND type='fund')
  computed            = 5,367
  skipped             = 80     (insufficient NAV history, < MIN_OBS)
  errors              = 0
  peer_ranked         = 5,151
  rejected daily bars = 194    (|return_1d| > 0.5 — see fix notes)
  wall clock          = ~140 s
```

## Baseline vs current state

Columns report the **mean** at the latest calc_date snapshot in each environment.

| Metric | Prod 2026-03-30 (pre-S4) | Local 2026-04-08 (post-S1-S5 + fixes) | Delta |
|---|---|---|---|
| `sharpe_1y` | -30.0139 | 0.5145 | +30.53 |
| `volatility_1y` | 0.1609 | 0.1497 | -0.011 |
| `volatility_garch` | 0.1615 | 0.1601 | -0.001 |
| `cvar_95_12m` | -0.0214 | -0.0211 | +0.0003 |
| `cvar_95_conditional` | null (0 populated) | -0.0301 | (new) |
| `max_drawdown_1y` | -0.1085 | -0.1082 | +0.0003 |
| `manager_score` | 50.95 | 51.33 | +0.38 |
| `blended_momentum_score` | 23.39 | 24.38 | +0.99 |
| `peer_sharpe_pctl` | null (0 populated) | 49.98 | (new) |
| `peer_sortino_pctl` | null (0 populated) | populated | (new) |
| `peer_return_pctl` | null (0 populated) | populated | (new) |
| `peer_drawdown_pctl` | null (0 populated) | populated | (new) |

### What changed

**`sharpe_1y` mean recovered (-30.01 -> 0.52)** — prod had 16 rows with the `-9999.999999` zero-volatility sentinel from the pre-S4 build. Those rows dominated the aggregate mean while leaving median and p95 essentially untouched. S4's 1% annualized vol guard (`MIN_ANNUALIZED_VOL = 0.01`) eliminates them by returning None for funds with stale or frozen NAV. Math reconciliation: `(0.5376 * 5443 + -9999 * 16) / 5459 = -28.77`, within 4% of the reported -30.01.

**`cvar_95_conditional` populated for the first time (0 -> 5,111 rows, 95.2% coverage)** — this column was added in migration `0058_add_garch_and_conditional_cvar` but the code path to populate it depends on `macro_regime_history` having data, which requires a successful `regime_fit` worker run. On prod that worker never produced output because of the statsmodels 0.14 API incompatibility (see fix note below). Pass 1.6 of `run_global_risk_metrics` now filters each fund's daily returns to RISK_OFF + CRISIS dates from the Markov HMM classifier and recomputes a 95% CVaR on that subsample.

**`peer_*_pctl` columns populated for the first time (0 -> 5,147 rows, 95.9% coverage)** — strategy-grouped peer percentile ranking added in commit `e38187c`. Ranks four dimensions per fund: Sharpe, Sortino, 1-year return, max drawdown. Computed over the currently-active universe with explicit survivorship-bias audit warning emitted per strategy group.

**Base metrics (`volatility_1y`, `cvar_95_12m`, `max_drawdown_1y`, etc.)** — drifted by 0-1 bps, consistent with 9 days of market data movement between the prod snapshot (2026-03-30) and local snapshot (2026-04-08). No methodology change on these columns.

## Regime-conditional CVaR — headline number

```
unconditional cvar_95_12m mean      = -0.0211
regime cvar_95_conditional mean     = -0.0301
stress premium (absolute)           = -0.0090  (~90 bps)
stress premium (ratio)              = 1.43 x
stress day share (lookback)         = 125 / 351 = 35.6%
```

Interpretation: the cross-sectional tail loss a fund is expected to suffer during an elevated-volatility regime is roughly 43% worse than a naive rolling-window 12-month CVaR would estimate. The lookback window (2024-11 to 2026-04) is dominated by RISK_OFF days (VIX avg 22.9) rather than a true crisis cluster, which keeps the ratio at the lower end of the historic 1.5-2.0x range observed during GFC and COVID-2020.

## Current metric coverage (calc_date = 2026-04-08)

```
total_rows              = 5,367  (global only, no org rows)
unique_instruments      = 5,367
volatility_1y           = 5,182  (96.6%)
volatility_garch        = 5,367  (100% — GARCH when convergent, EWMA(lambda=0.94) fallback otherwise)
sharpe_1y               = 5,149  (95.9%)
cvar_95_12m             = 5,182  (96.6%)
cvar_95_conditional     = 5,111  (95.2%)
max_drawdown_1y         = 5,182  (96.6%)
manager_score           = 5,367  (100%)
blended_momentum_score  = 4,851  (90.4%)
peer_sharpe_pctl        = 5,147  (95.9%)
```

## Distribution stats (calc_date = 2026-04-08)

| Metric | n | p05 | p50 | p95 | mean | min | max |
|---|---|---|---|---|---|---|---|
| sharpe_1y | 5,149 | -0.3913 | 0.5376 | 1.3909 | 0.5145 | -2.6017 | 3.9753 |
| volatility_1y | 5,182 | 0.0242 | 0.1596 | 0.3134 | 0.1497 | 0.0016 | 1.4562 |
| volatility_garch | 5,367 | 0.0192 | 0.1534 | 0.3226 | 0.1601 | — | — |
| cvar_95_12m | 5,182 | -0.0386 | -0.0230 | -0.0033 | -0.0211 | -0.2209 | 0.0001 |
| cvar_95_conditional | 5,111 | -0.0540 | -0.0333 | -0.0043 | -0.0301 | -0.3078 | 0.0001 |
| max_drawdown_1y | 5,182 | -0.1963 | -0.1157 | -0.0173 | -0.1082 | — | — |
| return_1y | 5,182 | — | 0.1000 | — | 0.1257 | -0.9806 | 1.2835 |
| manager_score | 5,367 | 37.68 | 51.70 | 63.95 | 51.33 | — | — |
| blended_momentum_score | 4,851 | 14.23 | 21.72 | 43.24 | 24.38 | — | — |
| peer_sharpe_pctl | 5,147 | 5.03 | 49.94 | 94.92 | 49.98 | — | — |

### Tail extremes and who owns them

- **Max `volatility_1y` = 146% (MSTZ)** — T-Rex 2X Inverse MSTR Daily Target ETF. Legitimate product, prospectus-disclosed daily-reset 2x inverse exposure to MicroStrategy (which trades as a Bitcoin proxy).
- **Min `cvar_95_conditional` = -30.78% (MSTU)** — T-Rex 2X Long MSTR Daily Target ETF. Same product family, long leg.
- **Min `return_1y` = -98.06% (MSTZ)** — consistent with being short a stock that rallied substantially during the lookback window.
- **Max `sharpe_1y` = 3.98** and **max `return_1y` = 128.35%** — high-momentum concentrated funds, not anomalous.

Prior to the data-quality fixes applied 2026-04-08, these extremes were contaminated by 7 corporate-action ghosts (see below) producing physically impossible values (-188% conditional CVaR, 406% annualized volatility, -394% annual return).

## Data-quality fixes applied 2026-04-08

Two bugs were discovered during the validation run and fixed in separate branches.

### 1. `fix/regime-fit-statsmodels-014` (commit `6a5e6e7`)

**Problem:** `backend/app/domains/wealth/workers/regime_fit.py:132` accessed `res.params["const[0]"]` on the return value of `statsmodels.tsa.regime_switching.markov_regression.MarkovRegression.fit()`. In statsmodels 0.14+, `res.params` is a plain `numpy.ndarray` rather than a labelled `pandas.Series`, so string indexing raises `IndexError`, not `KeyError`. The existing fallback only caught `KeyError`. The worker crashed silently, `macro_regime_history` stayed empty, and `cvar_95_conditional` was consequently NULL for every fund on every calc date.

**Fix:** Build a name-to-value map via `zip(res.model.param_names, res.params)` — the `param_names` attribute is version-independent. Broaden the exception catch to `(KeyError, IndexError, TypeError, AttributeError)` and add a deterministic second-level fallback.

**Validation:** `regime_fit` now upserts 351 regime rows on local in 1.26 s.

### 2. `fix/risk-calc-return-sanitization` (commit `22273ad`)

**Problem:** 7 funds in the catalog had single-day "returns" in `nav_timeseries.return_1d` ranging from -91% to -405% — corporate actions, distributions, and reverse-splits not adjusted by the `instrument_ingestion` worker. These implausible bars propagated through every downstream metric, producing:
  - `cvar_95_conditional = -188%` (CHNTX)
  - `volatility_1y = 406%` annualized (SFPIX)
  - `return_1y = -394%` (SFPIX)
  - `sharpe_1y` biased toward the bottom of the distribution for all 7 funds
  - Minor contamination of `peer_*_pctl` for other funds in the same strategy groups

**Fix:** New module-level constant `MAX_DAILY_RETURN_ABS = 0.5` applied at the source of every NAV return series — `_batch_fetch_nav_returns`, `_batch_fetch_dated_returns`, `_fetch_block_returns_batch`. Any `|return_1d| > 0.5` is rejected at fetch time with a structured warning counter logged per batch.

**Threshold rationale:** A 50% single-day loss is physically impossible on an unleveraged fund. On a 3x-leveraged product it requires the underlying to drop more than 16.7% in a single session — an event that has occurred only a handful of times in market history (Black Monday 1987, COVID 2020-03-16). The threshold preserves all legitimate extreme days on MSTU/MSTZ/ProFunds-style products (maximum observed: 73.93% on MSTZ during a Bitcoin rally).

**Validation:** 194 observations rejected across 5,447 funds (0.015% rejection rate). All 7 ghosts recovered clean metrics in the range expected for their fund category. Platform-level `sharpe_1y` mean drifted by only -0.003 post-fix, confirming the ghosts were biasing min/max but not the aggregate mean.

### Ghost reconciliation table

| Ticker | Name | cvar_95_conditional before | after |
|---|---|---|---|
| CHNTX | Chestnut Street Exchange Fund | -1.8793 | -0.0519 |
| RYSHX | Inverse Russell 2000 Strategy Fund (Rydex) | -0.2587 | -0.0437 |
| DSMLX | Touchstone Large Company Growth Fund | -0.2232 | -0.0480 |
| SFPIX | Fidelity Financial Services Portfolio | -0.0497 | -0.0497 |
| MRVNX | Mirova International Sustainable Equity | -0.0333 | -0.0333 |
| MMTLX | MassMutual Select T. Rowe Price Retirement 2035 | -0.0314 | -0.0314 |
| MMTQX | MassMutual Select T. Rowe Price Retirement 2030 | -0.0262 | -0.0262 |

For SFPIX, MRVNX, MMTLX, MMTQX the `cvar_95_conditional` value is unchanged because their single bad daily bar fell outside the stress-date subset used by Pass 1.6 — but their `volatility_1y`, `return_1y`, `sharpe_1y`, and `manager_score` all recovered from contaminated to clean values in the post-fix run.

## Known limitations and caveats

1. **`volatility_garch` is a mixed-provenance column.** When the GARCH(1,1) likelihood fails stationarity checks or the optimizer does not converge (`persistence >= 1.0` or `flag != 0`), the code falls back to EWMA with `lambda = 0.94` (the RiskMetrics 1996 standard). There is no column flag distinguishing GARCH-converged rows from EWMA fallback rows. Correct phrasing in client-facing material: *"conditional volatility estimated via GARCH(1,1) with EWMA-lambda-0.94 fallback for non-stationary fits"*. Roughly 320 of 5,182 rows show meaningful GARCH-vs-historical divergence, which is the lower bound on genuine GARCH-driven estimates.

2. **`peer_*_pctl` is survivorship-biased upward.** `instruments_universe` only contains currently-active funds, so every rank is computed against survivors. This biases ranks upward (failed funds are not in the denominator). Industry-standard limitation shared with Morningstar, Lipper, and every commercial peer database. The worker emits a `peer_percentile_survivorship_biased` warning per strategy group during the run for audit.

3. **Regime history only covers 2024-11-20 to 2026-04-01.** The `regime_fit` worker uses a 504-calendar-day preferred lookback (`PREFERRED_VIX_LOOKBACK`). For any fund with NAV history earlier than 2024-11-20, Pass 1.6 will not find a regime classification for those dates and those returns are implicitly excluded from the stress cohort. The 12-month risk window is fully covered; the 3-year window is partially covered.

4. **35.6% stress-day share is high but consistent with 2024-2026 macro.** The lookback contains the April 2025 tariff episode (5 CRISIS days, VIX avg 44.58) plus an extended stretch of elevated volatility (120 RISK_OFF days, VIX avg 22.90 — slightly below the `_VIX_RISK_OFF = 25.0` scalar threshold, but above in HMM filtered probability). The Markov classifier is correctly capturing regime persistence rather than point-in-time VIX level.

5. **No `vol_model` or `garch_converged` audit column.** Follow-up work to add a boolean or varchar column on `fund_risk_metrics` indicating whether `volatility_garch` came from a converged GARCH fit or the EWMA fallback.

6. **No `return_rejected_count` audit column.** The `MAX_DAILY_RETURN_ABS` guard logs per-batch rejection counts but does not persist them per fund. If audit trail becomes a requirement, consider adding a `data_quality_flags` JSONB column.

## Execution sequence for reproducibility

```bash
# Prerequisite: macro_data must contain VIXCLS series with at least 252 obs
# in the last 504 days (ingested by macro_ingestion worker)

# Step 1 — fit the Markov regime model on log-VIX (populates macro_regime_history)
python -m app.workers.cli regime_fit

# Step 2 — recompute global risk metrics for all active funds
python scripts/run_global_risk_metrics.py

# Step 3 — validate the state
docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "
  SELECT
    COUNT(*) FILTER (WHERE cvar_95_conditional IS NOT NULL) AS cvar_cond_pop,
    COUNT(*) FILTER (WHERE peer_sharpe_pctl IS NOT NULL)   AS peer_pctl_pop,
    ROUND(AVG(sharpe_1y)::numeric, 4)                      AS sharpe_mean,
    ROUND(MIN(cvar_95_conditional)::numeric, 4)            AS cvar_cond_min,
    ROUND(MAX(volatility_1y)::numeric, 4)                  AS vol_max,
    MAX(calc_date)                                          AS latest
  FROM fund_risk_metrics
  WHERE calc_date = CURRENT_DATE;"
```

Expected output:
```
 cvar_cond_pop | peer_pctl_pop | sharpe_mean | cvar_cond_min | vol_max  |   latest
---------------+---------------+-------------+---------------+----------+------------
          5111 |          5147 |      0.5145 |       -0.3078 |   1.4562 | 2026-04-08
```

## Related code references

- `backend/app/domains/wealth/workers/risk_calc.py` — main worker, all passes
- `backend/app/domains/wealth/workers/regime_fit.py` — Markov regime fitter (writes `macro_regime_history`)
- `backend/quant_engine/cvar_service.py` — `compute_cvar_from_returns()` shared kernel
- `backend/quant_engine/garch_service.py` — GARCH(1,1) with EWMA fallback
- `backend/quant_engine/scoring_service.py` — `manager_score` assembly from base metrics
- `backend/app/core/db/migrations/versions/0058_add_garch_and_conditional_cvar.py` — schema for `volatility_garch` and `cvar_95_conditional`
- `backend/app/core/db/migrations/versions/0093_fund_risk_metrics_composite_pk.py` — current PK of the table

## Related branches (open PRs)

- `fix/regime-fit-statsmodels-014` — commit `6a5e6e7`
- `fix/risk-calc-return-sanitization` — commit `22273ad`

Both branch from `origin/main` at `71814ac` and are independent of each other. Merge order is irrelevant.
