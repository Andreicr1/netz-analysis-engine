# Netz Analysis Engine — Quantitative Infrastructure & Due Diligence Report Reference

**Version:** 1.0
**Date:** 2026-03-24
**Audience:** Institutional investors, compliance officers, portfolio managers, auditors
**Purpose:** Transparent, code-traceable documentation of every computation, threshold, and method in the Netz quantitative stack

---

## Table of Contents

1. [Quant Engine Architecture](#1-quant-engine-architecture)
2. [Risk Metrics Pipeline](#2-risk-metrics-pipeline)
3. [Regime Detection](#3-regime-detection)
4. [Portfolio Evaluation](#4-portfolio-evaluation)
5. [Drift Monitoring](#5-drift-monitoring)
6. [Walk-Forward Backtesting](#6-walk-forward-backtesting)
7. [Portfolio Optimization](#7-portfolio-optimization)
8. [Rebalancing Engine](#8-rebalancing-engine)
9. [Attribution (Brinson-Fachler)](#9-attribution-brinson-fachler)
10. [Correlation & Denoising](#10-correlation--denoising)
11. [Screening Pipeline](#11-screening-pipeline)
12. [Macro Intelligence Coverage](#12-macro-intelligence-coverage)
13. [Due Diligence Report Engine](#13-due-diligence-report-engine)
14. [SEC Data Integration](#14-sec-data-integration)
15. [Fund Analysis (Top-Down Investment Chain)](#15-fund-analysis-top-down-investment-chain)
16. [External Data Ingestion Workers](#16-external-data-ingestion-workers)
17. [Continuous Aggregates & Pre-computation](#17-continuous-aggregates--pre-computation)
18. [Alerting & Automated Actions](#18-alerting--automated-actions)
19. [Computational Capacity & Performance](#19-computational-capacity--performance)

---

## 1. Quant Engine Architecture

### 1.1 High-Level Pipeline

```
External Data Sources          Workers (Background)           Hypertables (TimescaleDB)
─────────────────────          ────────────────────           ─────────────────────────
FRED API (~65 series)    ───►  macro_ingestion (lock 43)  ──► macro_data
US Treasury Fiscal API   ───►  treasury_ingestion (900_011)─► treasury_data
OFR Hedge Fund API       ───►  ofr_ingestion (900_012)    ──► ofr_hedge_fund_data
Yahoo Finance            ───►  benchmark_ingest (900_004) ──► benchmark_nav
Yahoo Finance            ───►  instrument_ingestion (910) ──► nav_timeseries
SEC EDGAR 13F-HR         ───►  sec_13f_ingestion (900_021)─► sec_13f_holdings, sec_13f_diffs
SEC FOIA bulk CSV        ───►  sec_adv_ingestion (900_022)─► sec_managers, sec_manager_funds
SEC EDGAR N-PORT         ───►  nport_ingestion (900_018)  ──► sec_nport_holdings
BIS SDMX API             ───►  bis_ingestion (900_014)    ──► bis_statistics
IMF DataMapper API       ───►  imf_ingestion (900_015)    ──► imf_weo_forecasts

                         Computed Workers
                         ────────────────
nav_timeseries       ──► risk_calc (900_007)           ──► fund_risk_metrics
fund_risk_metrics    ──► portfolio_eval (900_008)      ──► portfolio_snapshots
nav_timeseries       ──► drift_check (42)              ──► strategy_drift_alerts

                         Continuous Aggregates (Pre-computed)
                         ─────────────────────────────────────
nav_timeseries       ──► nav_monthly_returns_agg        (daily refresh)
benchmark_nav        ──► benchmark_monthly_returns_agg  (daily refresh)
sec_13f_holdings     ──► sec_13f_holdings_agg           (daily refresh)
sec_13f_diffs        ──► sec_13f_drift_agg              (daily refresh)

                         User-Facing Consumption
                         ─────────────────────
                         Routes read ONLY from DB / pre-computed tables
                         Zero external API calls in request path
```

### 1.2 Thread/Async Model

All route handlers are `async def` using `AsyncSession` (asyncpg). Computationally intensive synchronous operations are offloaded via `asyncio.to_thread()`:

- **DD Report generation** — sync `DDReportEngine.generate()` called via `asyncio.to_thread()`
- **Content engines** (Flash Report, Investment Outlook, Manager Spotlight) — sync, designed for `asyncio.to_thread()`
- **Portfolio optimization** — `cvxpy` solver dispatched via `asyncio.to_thread()`
- **Walk-forward backtesting** — `ThreadPoolExecutor(max_workers=min(n_splits, 4))` for fold parallelism

Workers run as background tasks within the FastAPI process, using `pg_try_advisory_lock(ID)` for coordination (non-blocking — skips gracefully if lock held).

### 1.3 Config Injection Pattern

All quant services receive configuration as a parameter — no YAML loading or `@lru_cache` at module level.

```
ConfigService.get(vertical, config_type, org_id)   # async, one DB query
    │
    ▼
config: dict  ──────►  quant_engine.cvar_service.resolve_cvar_config(config)
                        quant_engine.scoring_service.resolve_scoring_weights(config)
                        quant_engine.regime_service.resolve_regime_thresholds(config)
                        quant_engine.drift_service.resolve_drift_thresholds(config)
```

**Reference:** `backend/quant_engine/__init__.py:1-9`

Config resolution happens once at the async entry point (worker or route handler), then the resolved dict is passed down to all sync computation functions. This ensures deterministic, testable behavior with no hidden state.

---

## 2. Risk Metrics Pipeline

### 2.1 Overview

The `risk_calc` worker computes and stores all per-instrument risk metrics daily. Routes read pre-computed values — no in-request computation.

- **Worker:** `backend/app/domains/wealth/workers/risk_calc.py`
- **Lock ID:** `900_007`
- **Frequency:** Daily
- **Storage:** `fund_risk_metrics` hypertable (upsert on `instrument_id, calc_date`)

### 2.2 Risk-Free Rate

**Source:** FRED DFF (Federal Funds Effective Rate) from `macro_data` hypertable.

$$r_f = \frac{\text{DFF}_{\text{latest}}}{100}$$

**Fallback:** 0.04 (4%) if DFF unavailable.

**Reference:** `risk_calc.py:45` — `get_risk_free_rate()`

### 2.3 Return Windows

All metrics are computed over configurable windows:

| Window | Trading Days | Reference |
|--------|-------------|-----------|
| 1 month | 21 | `risk_calc.py:26` |
| 3 months | 63 | `risk_calc.py:26` |
| 6 months | 126 | `risk_calc.py:26` |
| 12 months | 252 | `risk_calc.py:26` |

**Minimum data requirement:** 21 observations (1 month) to compute any metric.

**Reference:** `risk_calc.py:316` — `_compute_metrics_from_returns()`

### 2.4 Cumulative Return

$$R_{\text{cum}}(T) = \prod_{t=1}^{T} (1 + r_t) - 1$$

Computed for 1m, 3m, 6m, 12m windows.

**Annualized return** (3-year):

$$R_{\text{ann}} = (1 + R_{\text{cum,3y}})^{1/3} - 1$$

**Reference:** `risk_calc.py:71-87`

### 2.5 Volatility

$$\sigma_{\text{ann}} = \text{std}(r_1, \ldots, r_T; \text{ddof}=1) \times \sqrt{252}$$

Computed for 1-year window. Uses Bessel correction (`ddof=1`).

**Reference:** `risk_calc.py:89-95`

### 2.6 Maximum Drawdown

$$\text{MDD}(T) = \min_{t \in [1,T]} \left( \frac{C_t - \max_{s \leq t} C_s}{\max_{s \leq t} C_s} \right)$$

where $C_t = \prod_{i=1}^{t}(1 + r_i)$ is the cumulative wealth index.

Computed for 1-year and 3-year windows using `numpy.maximum.accumulate`.

**Reference:** `risk_calc.py:97-106`

### 2.7 Sharpe Ratio

$$\text{Sharpe} = \frac{\bar{r}_{\text{excess}}}{\sigma_{\text{excess}}} \times \sqrt{252}$$

where $\bar{r}_{\text{excess}} = \bar{r} - r_f/252$ and $\sigma_{\text{excess}} = \text{std}(r_t - r_f/252; \text{ddof}=1)$.

Computed for 1-year and 3-year windows.

**Reference:** `risk_calc.py:108-118`

### 2.8 Sortino Ratio

$$\text{Sortino} = \frac{\bar{r} - r_f/252}{\sigma_{\text{downside}}} \times \sqrt{252}$$

where $\sigma_{\text{downside}} = \text{std}(\{r_t : r_t < r_f/252\}; \text{ddof}=1)$.

Only downside returns (below risk-free rate) contribute to the denominator. Returns `None` if no downside returns exist.

**Reference:** `risk_calc.py:120-133`

### 2.9 Conditional Value at Risk (CVaR)

**Method:** Historical simulation (non-parametric).

$$\text{VaR}_\alpha = r_{(\lfloor n(1-\alpha) \rfloor)}$$

$$\text{CVaR}_\alpha = \frac{1}{\lfloor n(1-\alpha) \rfloor} \sum_{i=1}^{\lfloor n(1-\alpha) \rfloor} r_{(i)}$$

where $r_{(i)}$ denotes the $i$-th sorted return (ascending) and $\alpha$ is the confidence level.

**Cutoff:** $\text{cutoff\_idx} = \max(\lfloor n \times (1 - \alpha) \rfloor, 1)$

**Default confidence:** 0.95 (from profile config).

**Minimum data:** 5 observations. Returns `(0.0, 0.0)` if fewer.

Both CVaR and VaR are returned as negative numbers (representing losses).

Computed for each return window (1m, 3m, 6m, 12m) with the profile-specific confidence level.

**Profile-specific CVaR configuration:**

| Profile | Window | Confidence | Limit | Warning | Breach Days |
|---------|--------|-----------|-------|---------|------------|
| Conservative | 12 months | 95% | -8.0% | 80% | 5 |
| Moderate | 3 months | 95% | -6.0% | 80% | 3 |
| Growth | 6 months | 95% | -12.0% | 80% | 5 |

**Reference:** `cvar_service.py:33-55` (defaults), `cvar_service.py:95-115` (formula)

### 2.10 Momentum Signals

#### RSI (Relative Strength Index)

$$\text{RSI}_{14} = \text{talib.RSI}(\text{close}, \text{timeperiod}=14)$$

Normalized to $[0, 1]$: $\text{rsi\_norm} = \text{RSI}_{14} / 100$.

Stored as percentage: $\text{rsi\_14} = \text{rsi\_norm} \times 100$.

**Reference:** `talib_momentum_service.py:45`

#### Bollinger Band Position

$$\text{BB}_{20,2} = \text{talib.BBANDS}(\text{close}, \text{timeperiod}=20, \text{nbdevup}=2, \text{nbdevdn}=2)$$

$$\text{bb\_pos} = \frac{\text{close} - \text{lower}}{\text{upper} - \text{lower}}$$

Returns 0.5 if `upper == lower`. Stored as percentage: $\text{bb\_position} = \text{bb\_pos} \times 100$.

**Reference:** `talib_momentum_service.py:50-58`

#### NAV Momentum Score

$$\text{nav\_momentum\_score} = (0.5 \times \text{rsi\_norm} + 0.5 \times \text{bb\_pos}) \times 100$$

**Reference:** `talib_momentum_service.py:62`

#### Flow Momentum (OBV Analog)

Accumulates fund net flows directionally based on NAV movement:

$$\text{OBV}_t = \begin{cases} \text{OBV}_{t-1} + \text{net\_flow}_t & \text{if } \text{NAV}_t > \text{NAV}_{t-1} \\ \text{OBV}_{t-1} - \text{net\_flow}_t & \text{if } \text{NAV}_t < \text{NAV}_{t-1} \\ \text{OBV}_{t-1} & \text{otherwise} \end{cases}$$

Slope computed via linear regression over last 21 days:

$$\text{slope} = \text{polyfit}([0, 1, \ldots, 20], \text{OBV}_{\text{tail}}, \deg=1)[0]$$

Normalized via hyperbolic tangent:

$$\text{flow\_momentum\_score} = 50 + \tanh\left(\frac{\text{slope}}{10^6}\right) \times 50$$

- 50 = neutral
- < 50 = distribution (outflows dominating during NAV declines)
- \> 50 = accumulation (inflows during NAV increases)

**Reference:** `talib_momentum_service.py:71-120`

#### Blended Momentum Score

$$\text{blended\_momentum\_score} = 0.5 \times \text{nav\_momentum\_score} + 0.5 \times \text{flow\_momentum\_score}$$

**Reference:** `risk_calc.py:275` — `_compute_momentum_from_nav()`

**Minimum data:** 30 NAV observations for any momentum signal. Returns neutral (50.0) if ta-lib not installed.

### 2.11 Manager Composite Score

$$\text{score} = \sum_{k} w_k \times C_k$$

| Component $k$ | Weight $w_k$ | Normalization Range | Reference |
|---------------|-------------|-------------------|-----------|
| `return_consistency` | 0.20 | return\_1y in $[-0.20, 0.40]$ | `scoring_service.py:82` |
| `risk_adjusted_return` | 0.25 | sharpe\_1y in $[-1.0, 3.0]$ | `scoring_service.py:85` |
| `drawdown_control` | 0.20 | max\_drawdown\_1y in $[-0.50, 0.0]$ | `scoring_service.py:88` |
| `information_ratio` | 0.15 | info\_ratio\_1y in $[-1.0, 2.0]$ | `scoring_service.py:91` |
| `flows_momentum` | 0.10 | passed through (0-100) | `scoring_service.py:93` |
| `lipper_rating` | 0.10 | passed through (0-100) | `scoring_service.py:94` |
| `fee_drag` | opt-in | $100 - \text{ER}\% \times 50$ (2% ER → 0) | `scoring_service.py:101` |
| `insider_sentiment` | opt-in | passed through (0-100), from Form 345 | `scoring_service.py:106` |

**Optional components:** `fee_drag` and `insider_sentiment` are activated only when the config dict includes their weight key with value > 0. When absent (default), behavior is unchanged.

**Insider sentiment score:** Computed from `sec_insider_sentiment` materialized view. Score = `buy_value / (buy_value + sell_value) * 100`. Excludes sole 10% Owners (`TenPercentOwner`). Uses only informative codes P (purchase) and S (sale). Default 4-quarter lookback. Score of 50.0 = neutral/no data. Reference: `insider_queries.py`.

**Normalization formula:**

$$\text{normalize}(v, \text{min}, \text{max}) = \max\left(0, \min\left(100, \frac{v - \text{min}}{\text{max} - \text{min}} \times 100\right)\right)$$

Returns 50.0 for `None` values or zero-range.

**Reference:** `scoring_service.py:56-114`

### 2.12 DTW Drift Score (Per-Block)

Computed during `risk_calc` Pass 2. For each allocation block with 2+ funds:

1. Fetch returns for all funds in block (last 63 days)
2. Compute equal-weight block benchmark
3. Run batch derivative DTW against benchmark

See [Section 5.3](#53-dtw-drift-detection) for formula details.

**Reference:** `risk_calc.py:452-528` — `_compute_block_dtw_scores()`

### 2.13 Stored Columns in `fund_risk_metrics`

The following columns are upserted per `(instrument_id, calc_date)`:

| Column | Source | Description |
|--------|--------|------------|
| `return_1m` | Cumulative | 21-day cumulative return |
| `return_3m` | Cumulative | 63-day cumulative return |
| `return_6m` | Cumulative | 126-day cumulative return |
| `return_1y` | Cumulative | 252-day cumulative return |
| `return_3y_ann` | Annualized | 3-year annualized return |
| `volatility_1y` | Std * sqrt(252) | 252-day annualized volatility |
| `max_drawdown_1y` | Running max | 252-day maximum drawdown |
| `max_drawdown_3y` | Running max | 3-year maximum drawdown |
| `sharpe_1y` | Excess/vol | 252-day Sharpe ratio |
| `sharpe_3y` | Excess/vol | 3-year Sharpe ratio |
| `sortino_1y` | Downside | 252-day Sortino ratio |
| `cvar_95_1m` | Historical | 21-day CVaR at 95% |
| `cvar_95_3m` | Historical | 63-day CVaR at 95% |
| `cvar_95_6m` | Historical | 126-day CVaR at 95% |
| `cvar_95_1y` | Historical | 252-day CVaR at 95% |
| `var_95_1m` | Historical | 21-day VaR at 95% |
| `var_95_3m` | Historical | 63-day VaR at 95% |
| `var_95_6m` | Historical | 126-day VaR at 95% |
| `var_95_1y` | Historical | 252-day VaR at 95% |
| `rsi_14` | TA-Lib | RSI(14) as percentage |
| `bb_position` | TA-Lib | Bollinger Band position as percentage |
| `nav_momentum_score` | Composite | 0.5*RSI + 0.5*BB position |
| `flow_momentum_score` | OBV slope | Normalized flow momentum |
| `blended_momentum_score` | Composite | 0.5*NAV + 0.5*flow |
| `manager_score` | Weighted composite | Manager composite score (0-100) |
| `score_components` | JSONB | Per-component breakdown |
| `dtw_drift_score` | Derivative DTW | Strategy drift vs block benchmark |

### 2.14 Redis Cache (Post-Computation)

After `risk_calc` completes:

1. **Correlation refresh marker** — key with 24h TTL signaling that correlation cache should be refreshed
2. **Scoring leaderboard** — top 50 funds by `sharpe_1y`, 24h TTL

**Reference:** `risk_calc.py:530-578` — `_write_risk_cache()`

---

## 3. Regime Detection

### 3.1 Overview

The regime detection system classifies current market conditions into one of four states. It operates at three levels: global (macro signals), regional (per-geography), and portfolio-level (fallback from volatility).

**Reference:** `backend/quant_engine/regime_service.py`

### 3.2 Regime States

| Regime | Severity | Description |
|--------|---------|-------------|
| `RISK_ON` | 0 | Normal market conditions |
| `RISK_OFF` | 1 | Elevated uncertainty, defensive positioning |
| `INFLATION` | 2 | Inflationary pressure dominant |
| `CRISIS` | 3 | Severe market stress |

**Reference:** `regime_service.py:69-74`

### 3.3 Global Multi-Signal Classification

**Priority hierarchy** (first match wins):

1. VIX $\geq$ `vix_extreme` (35) → **CRISIS**
2. CPI YoY $\geq$ `cpi_yoy_high` (4.0%) → **INFLATION**
3. VIX $\geq$ `vix_risk_off` (25) → **RISK_OFF**
4. Otherwise → **RISK_ON**

**Informational signals** (logged but do not override regime):
- Yield curve inversion: $\text{2s10s spread} < -0.10$ → "Yield curve inverted"
- Sahm Rule: $\text{unemployment rise} \geq 0.50$ → "Sahm rule active"

**Reference:** `regime_service.py:141-197`

### 3.4 Default Thresholds

| Parameter | Default | Unit | Reference |
|-----------|---------|------|-----------|
| `vix_risk_off` | 25 | VIX index | `regime_service.py:60` |
| `vix_extreme` | 35 | VIX index | `regime_service.py:60` |
| `yield_curve_inversion` | -0.10 | percentage points | `regime_service.py:62` |
| `cpi_yoy_high` | 4.0 | percent | `regime_service.py:63` |
| `cpi_yoy_normal` | 2.5 | percent | `regime_service.py:63` |
| `sahm_rule_recession` | 0.50 | percentage points | `regime_service.py:65` |

### 3.5 Plausibility Bounds

Before classification, all inputs are validated against plausibility ranges. Values outside bounds are discarded:

| Signal | Min | Max | Reference |
|--------|-----|-----|-----------|
| VIX | 0 | 200 | `regime_service.py:81` |
| CPI YoY | -10 | 30 | `regime_service.py:82` |
| Yield curve | -10 | 10 | `regime_service.py:83` |
| Sahm rule | -1 | 5 | `regime_service.py:84` |

### 3.6 Staleness Detection

Macro data can become stale if ingestion fails. The system rejects stale values:

| Frequency | Max Staleness | Reference |
|-----------|-------------|-----------|
| Daily (VIX, DFF) | 3 days | `regime_service.py:77` |
| Monthly (CPI, Sahm) | 45 days | `regime_service.py:78` |

### 3.7 Regional Regime Classification

Each region uses region-specific signals:

| Region | Primary Signal | Secondary Signal | Reference |
|--------|---------------|-----------------|-----------|
| US | VIX | HY OAS | `regime_service.py:256` |
| Europe | Euro HY OAS | — | `regime_service.py:257` |
| Asia | Asia EM Corp OAS | — | `regime_service.py:258` |
| EM | EM Corp OAS | — | `regime_service.py:259` |

**OAS thresholds:**

| Level | Threshold | Reference |
|-------|----------|-----------|
| RISK_OFF | ≥ 550 bps | `regime_service.py:264` |
| CRISIS | ≥ 800 bps | `regime_service.py:265` |

CPI YoY serves as an inflation override for all regions.

**Reference:** `regime_service.py:337-425`

### 3.8 Global Regime Composition

Regional regimes are aggregated into a global regime using GDP weights:

| Region | GDP Weight | Reference |
|--------|-----------|-----------|
| US | 0.25 | `regime_service.py:277` |
| Europe | 0.22 | `regime_service.py:278` |
| Asia | 0.28 | `regime_service.py:279` |
| EM | 0.25 | `regime_service.py:280` |

**Pessimistic overrides:**
- 2+ regions in CRISIS → global CRISIS (regardless of weights)
- Any region with weight ≥ 0.20 in CRISIS → global minimum RISK_OFF

**GDP-weighted severity mapping:**

$$\text{avg\_severity} = \sum_r w_r \times S_r$$

| avg_severity | Global Regime |
|-------------|--------------|
| ≥ 2.5 | CRISIS |
| ≥ 1.5 | INFLATION |
| ≥ 0.5 | RISK_OFF |
| < 0.5 | RISK_ON |

**Reference:** `regime_service.py:428-503`

### 3.9 Portfolio-Level Regime (Fallback)

When macro data is unavailable, regime is inferred from portfolio volatility:

$$\sigma_{\text{ann}} = \text{std}(r_1, \ldots, r_T) \times \sqrt{252}$$

$$\text{vol\_pct} = \sigma_{\text{ann}} \times 100$$

Classification uses VIX thresholds as proxy:
- $\text{vol\_pct} \geq 35$ → CRISIS
- $\text{vol\_pct} \geq 25$ → RISK_OFF
- Otherwise → RISK_ON

**Minimum data:** 10 return observations. Returns default regime if fewer.

**Reference:** `regime_service.py:200-246`

### 3.10 Data Sources

Queries `macro_data` hypertable (global, no RLS) for 9 series:
- `VIXCLS` — VIX index (daily)
- `YIELD_CURVE_10Y2Y` — 10Y-2Y spread (daily)
- `CPI_YOY` — Consumer Price Index year-over-year (monthly)
- `DFF` — Federal Funds Rate (daily)
- `SAHMREALTIME` — Sahm Rule indicator (monthly)
- 4 regional OAS spreads (daily)

**Reference:** `regime_service.py:506-556`

---

## 4. Portfolio Evaluation

### 4.1 Overview

The `portfolio_eval` worker computes portfolio-level metrics daily for each of 3 investment profiles, producing portfolio snapshots with breach status and regime context.

- **Worker:** `backend/app/domains/wealth/workers/portfolio_eval.py`
- **Lock ID:** `900_008`
- **Frequency:** Daily
- **Storage:** `portfolio_snapshots` hypertable (upsert on `organization_id, profile, snapshot_date`)
- **Profiles:** `conservative`, `moderate`, `growth`

### 4.2 Computation Steps

For each profile:

1. **Load config** — queries `VerticalConfigDefault` for `liquid_funds`/`portfolio_profiles`
2. **Get strategic weights** — queries `StrategicAllocation` for current block weights
3. **Get fund returns** — one representative fund per block, lookback = `window_months * 30` days
4. **Build portfolio returns** — weighted sum across blocks
5. **Compute CVaR** — `compute_cvar_from_returns(portfolio_returns, confidence)` per Section 2.9
6. **Detect regime** — `detect_regime(portfolio_returns)` per Section 3.9
7. **Check breach status** — compares CVaR against limits with consecutive day tracking
8. **Publish alert** — Redis channel `wealth:alerts:{profile}` on warning/breach

**Reference:** `portfolio_eval.py:169-246` — `evaluate_profile()`

### 4.3 CVaR Breach Status

$$\text{utilization} = \left|\frac{\text{CVaR}_{\text{current}}}{\text{CVaR}_{\text{limit}}}\right| \times 100$$

| Condition | Status |
|-----------|--------|
| utilization ≥ 100% AND consecutive_days ≥ breach_days | `breach` |
| utilization ≥ warning_pct × 100 | `warning` |
| Otherwise | `ok` |

**Consecutive day tracking:** Increments if utilization ≥ 100%, resets to 0 otherwise. Previous value loaded from most recent `PortfolioSnapshot`.

**Reference:** `cvar_service.py:118-186`

### 4.4 Stored Snapshot Fields

Each `PortfolioSnapshot` record contains:
- `organization_id`, `profile`, `snapshot_date`
- `cvar_current`, `cvar_limit`, `cvar_utilized_pct`
- `trigger_status` (ok/warning/breach)
- `consecutive_breach_days`
- `regime` (RISK_ON/RISK_OFF/INFLATION/CRISIS)
- `portfolio_returns` (serialized)

---

## 5. Drift Monitoring

### 5.1 Block-Level Allocation Drift

Compares current portfolio weights against strategic target weights:

$$\text{abs\_drift}_i = w_{\text{current},i} - w_{\text{target},i}$$

$$\text{rel\_drift}_i = \frac{\text{abs\_drift}_i}{w_{\text{target},i}} \quad (\text{if } w_{\text{target},i} > 0)$$

**Status classification:**

| Condition | Status | Reference |
|-----------|--------|-----------|
| $|\text{abs\_drift}| \geq$ `urgent_trigger` | `urgent` | `drift_service.py:148` |
| $|\text{abs\_drift}| \geq$ `maintenance_trigger` | `maintenance` | `drift_service.py:150` |
| Otherwise | `ok` | `drift_service.py:152` |

**Default thresholds:**

| Threshold | Default | Reference |
|-----------|---------|-----------|
| `maintenance_trigger` | 0.05 (5%) | `drift_service.py:89` |
| `urgent_trigger` | 0.10 (10%) | `drift_service.py:89` |

**Reference:** `drift_service.py:125-160`

### 5.2 Drift Check Worker

- **Worker:** `backend/app/domains/wealth/workers/drift_check.py`
- **Lock ID:** `42`
- **Frequency:** Daily
- **Profiles:** `conservative`, `moderate`, `growth`

For each profile, if rebalance is recommended, creates a `drift_rebalance` event with:
- Top 3 drifted blocks
- Maximum drift percentage
- Estimated turnover

### 5.3 DTW Drift Detection (Strategy Drift)

Uses **derivative Dynamic Time Warping (dDTW)** to detect style drift between a fund's returns and its block benchmark.

**Algorithm:**

1. Truncate to last `max_lookback_days` (504) observations
2. Window to last `window` (63) days
3. Compute dDTW distance using `aeon.distances.ddtw_distance`

$$\text{raw} = \text{ddtw\_distance}(f, b, \text{window}=0.1)$$

$$\text{score} = \frac{\text{raw}}{\max(\text{len}(f), 1)}$$

**Minimum data:** 10 observations. Returns `degraded` status if fewer.

**DTW drift thresholds:**

| Threshold | Default | Reference |
|-----------|---------|-----------|
| Warning | 0.40 | `drift_service.py:111` |
| Critical | 0.90 | `drift_service.py:111` |

**Reference:** `drift_service.py:168-224`

### 5.4 Batch DTW (Vectorized)

For computing DTW across all funds in a block simultaneously:

Uses `aeon.distances.pairwise_distance(metric="ddtw")` to compute all pairwise distances in one call. Each fund's score is extracted from `distance_matrix[-1, :-1]` (last row = benchmark vs all funds) divided by window length.

**Reference:** `drift_service.py:227-287`

### 5.5 Strategy Drift Scanner (Z-Score Based)

Monitors 7 risk metrics for regime shifts using z-score detection:

**Tracked metrics:** `volatility_1y`, `max_drawdown_1y`, `sharpe_1y`, `sortino_1y`, `alpha_1y`, `beta_1y`, `tracking_error_1y`

**Formula:**

$$z_k = \frac{\mu_{\text{recent},k} - \mu_{\text{baseline},k}}{\sigma_{\text{baseline},k}}$$

**Defaults:**

| Parameter | Default | Reference |
|-----------|---------|-----------|
| Recent window | 90 days | `strategy_drift_scanner.py` |
| Baseline window | 360 days | `strategy_drift_scanner.py` |
| Z threshold | 2.0 (strict >) | `strategy_drift_scanner.py` |
| Min baseline points | 20 | `strategy_drift_scanner.py` |
| Min recent points | 5 | `strategy_drift_scanner.py` |

**Severity:**
- ≥ 3 anomalous metrics → `severe`
- ≥ 1 anomalous metric → `moderate`
- 0 → `none`

**Reference:** `backend/vertical_engines/wealth/monitoring/strategy_drift_scanner.py`

---

## 6. Walk-Forward Backtesting

### 6.1 Overview

Provides out-of-sample validation of portfolio weights using expanding-window time series cross-validation. Designed for liquid funds with daily dealing.

**Reference:** `backend/quant_engine/backtest_service.py`

### 6.2 Method

Uses `sklearn.model_selection.TimeSeriesSplit` with expanding training window:

| Parameter | Default | Rationale | Reference |
|-----------|---------|-----------|-----------|
| `n_splits` | 5 | Number of folds | `backtest_service.py:53` |
| `gap` | 2 | Trading days gap (daily-dealing funds) | `backtest_service.py:53` |
| `min_train_size` | 252 | 1 year minimum training | `backtest_service.py:53` |
| `test_size` | 63 | ~3 months test window | `backtest_service.py:53` |

For illiquid funds: `gap=21` (1 month).

### 6.3 Per-Fold Metrics

**Portfolio returns per fold:**

$$r_{\text{port},t} = \mathbf{w}^\top \mathbf{r}_t$$

where $\mathbf{w}$ is the weight vector and $\mathbf{r}_t$ is the cross-sectional return vector at time $t$.

**Sharpe ratio:**

$$\text{Sharpe}_k = \frac{\bar{r}_k - r_f/252}{\sigma_k} \times \sqrt{252}$$

Risk-free rate default: $r_f = 0.04$ (4%).

**CVaR at 95%:**

$$\text{CVaR}_{95,k} = -\text{mean}(r_{(1)}, \ldots, r_{(\lfloor 0.05n \rfloor)})$$

Note: returned as positive number (loss magnitude).

**Maximum drawdown:** Same formula as Section 2.6.

**Reference:** `backtest_service.py:24-50`

### 6.4 Parallelization

Folds computed in parallel via `ThreadPoolExecutor(max_workers=min(n_splits, 4))`.

**Reference:** `backtest_service.py:85`

### 6.5 Fold Consistency

Reports `positive_folds` = count of folds with positive Sharpe ratio. Expressed as ratio N/5. Does **not** compute p-values (per Finucane 2004 — p-values on 5 folds are misleading).

**Reference:** `backtest_service.py:117-123`

### 6.6 Output Structure

```python
{
    "folds": [{"sharpe": float, "cvar_95": float, "max_drawdown": float, "n_days": int}, ...],
    "mean_sharpe": float,
    "std_sharpe": float,
    "positive_folds": int,
    "n_splits_computed": int,
}
```

---

## 7. Portfolio Optimization

### 7.1 Overview

Two optimization modes: single-objective (CLARABEL convex solver) and multi-objective (NSGA-II evolutionary).

**Reference:** `backend/quant_engine/optimizer_service.py`

### 7.2 Single-Objective Optimization (CLARABEL)

**Solver:** CLARABEL primary, SCS fallback.

**Objectives:**

| Objective | Formulation | Reference |
|-----------|------------|-----------|
| `min_variance` | $\min \mathbf{w}^\top \Sigma \mathbf{w}$ | `optimizer_service.py:229` |
| `max_sharpe` | $\max (\mathbf{w}^\top \boldsymbol{\mu} - \lambda \times \mathbf{w}^\top \Sigma \mathbf{w})$ with $\lambda = 2.0$ | `optimizer_service.py:237` |

**Constraints:**

$$\sum_i w_i = 1, \quad w_i \geq 0, \quad w_{i,\min} \leq w_i \leq w_{i,\max}$$

**Default maximum single fund weight:** 0.15 (15%).

**Post-processing:** Clips negative weights to 0, renormalizes to sum = 1.

**Execution:** Dispatched to thread via `asyncio.to_thread()`.

**Reference:** `optimizer_service.py:177-287`

### 7.3 Multi-Objective Optimization (NSGA-II via pymoo)

**Algorithm:** NSGA-II (Non-dominated Sorting Genetic Algorithm II)

**Objectives (bi-objective by default):**
1. Minimize $-\text{Sharpe}$ (maximize Sharpe)
2. Minimize $\text{CVaR}_{95}$

Optional tri-objective with ESG score.

**Cornish-Fisher Adjusted Parametric CVaR:**

$$z = \Phi^{-1}(\alpha)$$

$$z_{CF} = z + \frac{z^2 - 1}{6} \gamma_3 + \frac{z^3 - 3z}{24} \gamma_4 - \frac{2z^3 - 5z}{36} \gamma_3^2$$

$$\text{CVaR}_{CF} = -(\mu_p + \sigma_p \cdot z_{CF}) + \sigma_p \cdot \frac{\phi(z_{CF})}{\alpha}$$

where $\gamma_3$ = portfolio skewness, $\gamma_4$ = portfolio excess kurtosis, $\Phi^{-1}$ = inverse normal CDF, $\phi$ = normal PDF.

**Reference:** `optimizer_service.py:46-75`

**Parameters:**

| Parameter | Default | Reference |
|-----------|---------|-----------|
| `pop_size` | 100 | `optimizer_service.py:290` |
| `n_gen` | 200 | `optimizer_service.py:290` |
| Constraint | CVaR ≤ `cvar_limit` (default 0.15) | `optimizer_service.py:441` |

**Portfolio Weight Repair:** Clips to bounds, zeros below 1e-4, normalizes to sum = 1.

**Reference:** `optimizer_service.py:97-108`

**Recommended Solution Selection:**
- Max Sharpe among feasible solutions (CVaR ≤ limit)
- If no feasible solution: min CVaR

**Reference:** `optimizer_service.py:457-464`

**Seed:** Deterministic from `derive_seed(profile, calc_date)` for reproducibility.

**Execution time:** 45-135 seconds. WEEKLY/ON-DEMAND only.

**Caching:** Redis SHA-256 of inputs (including date), 1h TTL. Pareto optimization returns 202 immediately with SSE progress stream.

### 7.4 Dependencies

- `cvxpy` — convex optimization (required)
- `pymoo` — multi-objective evolutionary (optional, falls back to CLARABEL)
- `scipy.stats` — normal distribution for Cornish-Fisher

---

## 8. Rebalancing Engine

### 8.1 Overview

Triggers rebalancing based on drift thresholds, regime changes, or calendar schedules. Computes proposed weight adjustments with impact analysis.

**References:**
- `backend/quant_engine/rebalance_service.py` — cascade logic
- `backend/vertical_engines/wealth/rebalancing/service.py` — orchestration
- `backend/vertical_engines/wealth/rebalancing/weight_proposer.py` — weight computation

### 8.2 Rebalance Triggers

| Trigger | Detection Method | Reference |
|---------|-----------------|-----------|
| Drift threshold | Block-level drift ≥ urgent_trigger | `drift_check.py` |
| Regime change | N consecutive stress/crisis snapshots | `rebalancing/service.py:112` |
| Calendar | User-initiated | Route handler |
| Deactivation | Fund removed from universe | `rebalancing/service.py:48` |

### 8.3 Regime Trigger Detection

Uses `CROSS JOIN LATERAL` SQL to get latest N snapshots per profile:

```sql
SELECT * FROM portfolio_snapshots ps
CROSS JOIN LATERAL (
    SELECT * FROM portfolio_snapshots sub
    WHERE sub.profile = ps.profile
    ORDER BY sub.snapshot_date DESC
    LIMIT :threshold
) latest
```

Triggers if all N snapshots have regime in `{"stress", "crisis"}`.

**Default:** `regime_consecutive_threshold = 2`

**Reference:** `rebalancing/service.py:112`

### 8.4 Weight Proposal Algorithm

**Iterative proportional redistribution** (max 10 iterations):

1. Remove excluded instrument, renormalize remaining weights
2. Clamp to `[min_weight, max_weight]` bounds from `StrategicAllocation`
3. Freeze clamped blocks, redistribute remaining budget proportionally
4. Repeat until convergence
5. Feasibility check: $|\sum w - 1| > 0.01$ → infeasible (returns `None`)
6. Round to 6 decimal places

**Reference:** `weight_proposer.py:24-85`

### 8.5 State Machine

Rebalance events follow a strict transition graph:

```
pending → approved → executed
pending → rejected (terminal)
pending → cancelled (terminal)
```

**Reference:** `rebalance_service.py:22-27`

### 8.6 Cascade Actions

When CVaR breach status changes:

| Transition | Action | Reference |
|-----------|--------|-----------|
| ok → warning or breach | `cvar_breach` event created | `rebalance_service.py:55` |
| warning → ok | `cvar_breach` event created (recovery notification) | `rebalance_service.py:59` |
| ok → ok | No action | `rebalance_service.py:68` |

**Reference:** `rebalance_service.py:39-72`

---

## 9. Attribution (Brinson-Fachler)

### 9.1 Overview

Decomposes portfolio performance relative to a policy benchmark into allocation, selection, and interaction effects per sector/block.

**References:**
- `backend/quant_engine/attribution_service.py` — core formulas
- `backend/vertical_engines/wealth/attribution/service.py` — portfolio integration

### 9.2 Single-Period Brinson-Fachler Decomposition

For each sector $i$:

$$\text{Allocation Effect}_i = (w_{p,i} - w_{b,i}) \times (r_{b,i} - R_b)$$

$$\text{Selection Effect}_i = w_{b,i} \times (r_{p,i} - r_{b,i})$$

$$\text{Interaction Effect}_i = (w_{p,i} - w_{b,i}) \times (r_{p,i} - r_{b,i})$$

where:
- $w_{p,i}$ = portfolio weight in sector $i$
- $w_{b,i}$ = benchmark weight in sector $i$
- $r_{p,i}$ = portfolio return in sector $i$
- $r_{b,i}$ = benchmark return in sector $i$
- $R_b = \sum_i w_{b,i} \times r_{b,i}$ = total benchmark return

**Note:** The Fachler adjustment uses $(r_{b,i} - R_b)$ instead of $r_{b,i}$ in the allocation effect, ensuring total effects sum correctly.

**Reference:** `attribution_service.py:119-128`

### 9.3 Cash Residual Block

If portfolio weights do not sum to 1.0 (within tolerance 1e-4), a `cash_residual` block is added with zero return to capture the allocation effect of holding cash.

**Reference:** `attribution/service.py:75-92`

### 9.4 Multi-Period Linking (Carino Method)

For linking attribution across multiple periods:

**Carino factor:**

$$k(r) = \begin{cases} \frac{\ln(1 + r)}{r} & \text{if } |r| \geq 10^{-10} \\ 1.0 & \text{otherwise} \end{cases}$$

**Scaling:**

$$\text{scale}_t = \frac{k(r_t)}{k(R_{\text{total}})}$$

where $R_{\text{total}} = \prod_t (1 + r_t) - 1$ is the compound total return.

**Clamping:** Carino factor clamped to $[-10, 10]$ to prevent divergence near zero returns.

**Fallback:** If total excess return $< 10^{-10}$, uses simple average linking across periods.

**Reference:** `attribution_service.py:157-232`, `attribution/service.py:119-170`

### 9.5 Current Limitations

- **Deferred:** Requires benchmark constituent data (no Bloomberg/Morningstar feed currently connected). The framework is complete and tested but awaits data integration.
- **Granularity:** Monthly, quarterly.

---

## 10. Correlation & Denoising

### 10.1 Overview

Analyzes portfolio correlation structure with noise reduction and systemic risk detection.

**References:**
- `backend/quant_engine/correlation_regime_service.py` — core computation
- `backend/vertical_engines/wealth/correlation/service.py` — portfolio integration

### 10.2 Default Parameters

| Parameter | Default | Reference |
|-----------|---------|-----------|
| Rolling window | 60 days | `correlation_regime_service.py:18` |
| Baseline window | 504 days (~2 years) | `correlation_regime_service.py:19` |
| Contagion threshold | 0.3 | `correlation_regime_service.py:20` |
| Concentration moderate | 0.6 | `correlation_regime_service.py:21` |
| Concentration high | 0.8 | `correlation_regime_service.py:22` |
| DR alert threshold | 1.2 | `correlation_regime_service.py:23` |
| Min observations | 45 | `correlation_regime_service.py:24` |
| Absorption warning | 0.80 | `correlation_regime_service.py:25` |
| Absorption critical | 0.90 | `correlation_regime_service.py:26` |

### 10.3 Covariance Estimation

Uses **Ledoit-Wolf shrinkage** (via `sklearn.covariance.LedoitWolf`) when available. Falls back to sample covariance.

**Reference:** `correlation_regime_service.py:196-349` (around line 230)

### 10.4 Marchenko-Pastur Denoising

Removes noise eigenvalues from the correlation matrix using Random Matrix Theory:

$$\lambda_{\max}^{MP} = (1 + \sqrt{q})^2$$

where $q = T/N$ (observations / assets ratio).

**Algorithm:**
1. Eigendecompose correlation matrix
2. Identify noise eigenvalues: $\lambda_i < \lambda_{\max}^{MP}$
3. Replace noise eigenvalues with their average
4. Reconstruct correlation matrix: $C' = V \Lambda' V^\top$
5. Normalize diagonal to 1.0

**Reference:** `correlation_regime_service.py:88-119`

### 10.5 Concentration Analysis (Eigenvalue-Based)

**First eigenvalue ratio:**

$$\rho_1 = \frac{\lambda_1}{\sum_i \lambda_i}$$

| $\rho_1$ | Status |
|----------|--------|
| > 0.8 | `high_concentration` |
| > 0.6 | `moderate_concentration` |
| ≤ 0.6 | `low_concentration` |

**Reference:** `correlation_regime_service.py:142-148`

### 10.6 Absorption Ratio (Kritzman & Li, 2010)

$$AR = \frac{\sum_{i=1}^{k} \lambda_i}{\sum_{i=1}^{N} \lambda_i}$$

where $k = \max(1, \lfloor N/5 \rfloor)$.

| AR | Status |
|----|--------|
| > 0.90 | `critical` |
| > 0.80 | `warning` |
| ≤ 0.80 | `healthy` |

**Reference:** `correlation_regime_service.py:159-162`

### 10.7 Diversification Ratio (Choueifaty)

$$DR = \frac{\sum_i w_i \sigma_i}{\sigma_p}$$

where $\sigma_i$ = individual asset volatility, $\sigma_p = \sqrt{\mathbf{w}^\top \Sigma \mathbf{w}}$.

$DR < 1.2$ triggers an alert (portfolio poorly diversified).

**Reference:** `correlation_regime_service.py:183-193`

### 10.8 Contagion Detection

For each asset pair, compares rolling window correlation to baseline:

$$\text{contagion if: } |\text{corr}_{\text{current}} - \text{corr}_{\text{baseline}}| > 0.3 \text{ AND } \text{corr}_{\text{current}} > 0.7$$

**Reference:** `correlation_regime_service.py:298-300`

### 10.9 Regime Shift Detection

$$\text{regime shift if: } (\bar{\rho}_{\text{current}} - \bar{\rho}_{\text{baseline}}) > 0.3$$

where $\bar{\rho}$ = average pairwise correlation.

**Reference:** `correlation_regime_service.py:331`

---

## 11. Screening Pipeline

### 11.1 Overview

Three-layer deterministic screening pipeline. No ML or LLM — all rules are explicit and auditable.

**References:**
- `backend/vertical_engines/wealth/screener/service.py`
- `backend/vertical_engines/wealth/screener/models.py`

### 11.2 Layer 1: Eliminatory Filters (Hard Constraints)

Hard pass/fail criteria. Any failure → `FAIL` (screening stops).

Criteria are evaluated by `LayerEvaluator(config_layer1)` against instrument attributes. Examples include:
- Minimum AUM
- Domicile restrictions
- Track record length requirements
- Regulatory status

Each criterion returns a `CriterionResult`: criterion name, expected value, actual value, passed (bool), layer (1).

**Reference:** `screener/service.py:72-82`

### 11.3 Layer 2: Mandate Fit Scoring

Softer criteria with a **10% watchlist margin**: instruments that fail Layer 2 by ≤ 10% get `WATCHLIST` instead of `FAIL`.

**Reference:** `screener/service.py:84-95`, `screener/service.py:252-270` — `_within_watchlist_margin()`

### 11.4 Layer 3: Quantitative Ranking

Computes composite score from quantitative metrics and peer comparison values.

Final status determination with **hysteresis** (previous status influences threshold):
- New instruments use standard thresholds
- Existing `PASS` instruments have slightly relaxed thresholds (prevent churn)

**Score computation:** delegates to `composite_score()` from `scoring_metrics` module. Differentiates between bond instruments (`bond_brief` analysis) and fund/equity instruments (`dd_report` analysis).

**Reference:** `screener/service.py:97-120`, `screener/service.py:213-250`

### 11.5 Output Status Values

| Status | Meaning |
|--------|---------|
| `PASS` | Passed all 3 layers |
| `FAIL` | Failed at Layer 1 or Layer 2 (beyond margin) |
| `WATCHLIST` | Failed Layer 2 within 10% margin |

### 11.6 Batch Screening

`screen_universe()` evaluates all instruments in a single run, producing `ScreeningRunResult` with `run_id`, timestamp, config hash (SHA-256), and per-instrument results.

**Reference:** `screener/service.py:162-210`

---

## 12. Macro Intelligence Coverage

### 12.1 Weekly Macro Committee Reports

Pure synchronous computation from pre-built regional snapshots. No LLM calls — produces structured data for committee review.

**Reference:** `backend/vertical_engines/wealth/macro_committee_engine.py`

#### Regional Score Computation

Scores are computed per region via `score_region()` in `regional_macro_service.py`:

**Dimension weights:**

| Dimension | Weight | Reference |
|-----------|--------|-----------|
| Growth | 0.20 | `regional_macro_service.py:48` |
| Inflation | 0.20 | `regional_macro_service.py:49` |
| Monetary | 0.15 | `regional_macro_service.py:50` |
| Financial conditions | 0.20 | `regional_macro_service.py:51` |
| Labor | 0.15 | `regional_macro_service.py:52` |
| Sentiment | 0.10 | `regional_macro_service.py:53` |
| Credit cycle | 0.10 | Added by `enrich_region_score()` |

**Percentile-rank normalization:**

$$\text{score}(x, H) = \frac{|\{h \in H : h \leq x\}|}{|H|} \times 100$$

Returns 50.0 (neutral) if $|H| < 60$. Inverted for counter-cyclical indicators.

**Reference:** `regional_macro_service.py:364-384`

**Minimum coverage:** Score returns neutral 50.0 if dimension coverage < 50%.

#### Staleness-Weighted Scoring

Each data series has a staleness weight based on its publication frequency:

| Frequency | Fresh (days) | Max useful (days) | Floor weight |
|-----------|-------------|-------------------|-------------|
| Daily | 3 | 10 | 0.30 |
| Weekly | 10 | 30 | 0.40 |
| Monthly | 45 | 90 | 0.50 |
| Quarterly | 100 | 180 | 0.50 |

**Decay formula:**

$$w = \max\left(\text{floor}, 1.0 - \frac{d - d_{\text{fresh}}}{d_{\text{max}} - d_{\text{fresh}}} \times (1.0 - \text{floor})\right)$$

where $d$ = days since last observation.

**Reference:** `regional_macro_service.py:387-434`

#### Credit Cycle Score (BIS Enrichment)

$$\text{credit\_score} = 0.5 \times (50 - 4 \times \text{gap}) + 0.3 \times (120 - 4 \times \text{DSR}) + 0.2 \times f(\text{property})$$

where gap = credit-to-GDP gap, DSR = debt service ratio, property = property prices YoY.

**Reference:** `regional_macro_service.py:655-726`

#### IMF Growth Blending

$$\text{growth\_blended} = 0.70 \times \text{FRED\_growth\_score} + 0.30 \times \text{IMF\_GDP\_forecast\_score}$$

IMF score: $35.0 + \text{avg\_forecast} \times 7.5$

**Reference:** `regional_macro_service.py:729-768`

#### Weekly Report Thresholds

| Parameter | Default | Reference |
|-----------|---------|-----------|
| Score delta threshold | 5.0 points | `macro_committee_engine.py:44` |
| Emergency cooldown | 24 hours | `macro_committee_engine.py:171` |

**Material change detection:** Any flagged score delta OR any regime transition OR any global indicator delta > threshold.

**Regions covered:** US, Europe, Asia, EM (+ global indicators)

**Global indicators tracked:** geopolitical risk score, energy stress, commodity stress, USD strength

**Reference:** `macro_committee_engine.py:44-142`

#### FRED Series Coverage

| Region | Series Count | Examples |
|--------|-------------|---------|
| US | 14 | VIX, CPI, unemployment, consumer sentiment, NFCI |
| Europe | 6 | Euro HY OAS, EURIBOR, CPI |
| Asia | 7 | Asia EM Corp OAS, Japan CPI, China PMI |
| EM | 7 | EM Corp OAS, Brazil SELIC, India CPI |
| Global | 11 | GPR, EPU, oil, gas, reserves, copper, gold, fertilizer, USD |
| Credit | 40+ | Rates, real estate, mortgage, delinquency, 20 Case-Shiller metros |

**Total:** ~65 FRED series ingested daily

**Reference:** `regional_macro_service.py:112-242`

### 12.2 Flash Reports

Event-driven market flash reports with mandatory cooldown.

**Reference:** `backend/vertical_engines/wealth/flash_report.py`

| Parameter | Value | Reference |
|-----------|-------|-----------|
| Max tokens | 3,000 | `flash_report.py:32` |
| Cooldown | 48 hours | `flash_report.py:33` |
| Template | `content/flash_report.j2` | `flash_report.py:31` |

**Sections:** Market event, market impact, portfolio positioning, recommended actions, key risks.

**Data sources:** `WealthContent` (cooldown check), `MacroReview` (macro context).

**Status values:** `completed`, `failed`, `cooldown` (suppressed within 48h).

### 12.3 Investment Outlook

Quarterly macro narrative with investment positioning guidance.

**Reference:** `backend/vertical_engines/wealth/investment_outlook.py`

| Parameter | Value | Reference |
|-----------|-------|-----------|
| Max tokens | 4,000 | `investment_outlook.py:30` |
| Template | `content/investment_outlook.j2` | `investment_outlook.py:29` |

**Sections:** Global macro summary, regional outlook, asset class views, portfolio positioning, key risks.

**No cooldown** — generated on-demand, typically quarterly.

### 12.4 Manager Spotlight

Deep-dive single fund manager analysis combining quantitative metrics with LLM narrative.

**Reference:** `backend/vertical_engines/wealth/manager_spotlight.py`

| Parameter | Value | Reference |
|-----------|-------|-----------|
| Max tokens | 4,000 | `manager_spotlight.py:33` |
| Template | `content/manager_spotlight.j2` | `manager_spotlight.py:32` |

**Sections:** Fund overview, quant analysis, peer comparison, key risks.

**Data gathered:** Fund identity (name, ISIN, manager, type, geography, asset class, AUM) + quant metrics + risk metrics from `fund_risk_metrics`.

---

## 13. Due Diligence Report Engine

### 13.1 Overview

Generates 8-chapter institutional due diligence reports with evidence-backed analysis, adversarial critic review, and confidence scoring.

**Reference:** `backend/vertical_engines/wealth/dd_report/`

### 13.2 Chapter Structure

| # | Tag | Type | Max Tokens | Reference |
|---|-----|------|-----------|-----------|
| 1 | `executive_summary` | ANALYTICAL | 3,000 | `dd_report/models.py:15` |
| 2 | `investment_strategy` | DESCRIPTIVE | 2,500 | `dd_report/models.py:16` |
| 3 | `manager_assessment` | ANALYTICAL | 4,000 | `dd_report/models.py:17` |
| 4 | `performance_analysis` | ANALYTICAL | 4,000 | `dd_report/models.py:18` |
| 5 | `risk_framework` | ANALYTICAL | 4,000 | `dd_report/models.py:19` |
| 6 | `fee_analysis` | DESCRIPTIVE | 2,500 | `dd_report/models.py:20` |
| 7 | `operational_dd` | DESCRIPTIVE | 2,500 | `dd_report/models.py:21` |
| 8 | `recommendation` | ANALYTICAL | 4,000 | `dd_report/models.py:22` |

**Total max tokens:** 26,500 across all chapters.

### 13.3 Generation Pipeline

```
1. Ensure report record (idempotent, versioned)
2. Build evidence pack (Fund + quant + risk + SEC 13F + SEC ADV)
3. Generate chapters 1-7 in parallel (ThreadPoolExecutor, max_workers=5)
4. Generate chapter 8 sequentially (requires chapters 1-7 summaries)
5. Compute confidence score
6. Derive decision anchor
7. Persist to DB
```

**Reference:** `dd_report/dd_report_engine.py:81-200`

### 13.4 Resume Safety

If generation is interrupted, cached chapters (stored in DB with `is_current=True`) are reused on retry when `force=False`. Only missing chapters are regenerated.

**Minimum chapters for recommendation:** 5 completed chapters required before chapter 8 can be generated.

**Reference:** `dd_report/dd_report_engine.py:328-370`, `dd_report/models.py:25-26`

### 13.5 Parallelization

Chapters 1-7 run in `ThreadPoolExecutor(max_workers=5)` (configurable via `_DEFAULT_LLM_CONCURRENCY`). Chapter 8 is sequential because it requires summaries from all prior chapters.

**Reference:** `dd_report/dd_report_engine.py:328` (parallel), `dd_report/dd_report_engine.py:370` (sequential)

### 13.6 Evidence Pack

A frozen dataclass containing all evidence for the report:

| Category | Fields | Source |
|----------|--------|--------|
| Fund identity | name, isin, ticker, fund_type, geography, asset_class, manager_name, currency, domicile, inception_date, aum_usd | `Fund` model |
| Documents | Up to 20 chunks, text capped at 2,000 chars | Document pipeline |
| Quant profile | 22 metrics (CVaR windows, returns, volatility, Sharpe, Sortino, alpha, beta, IR, tracking error, manager_score, score_components, dtw_drift_score) | `fund_risk_metrics` |
| Risk metrics | Nested CVaR/VaR windows, max drawdown | `fund_risk_metrics` |
| Scoring data | manager_score, components | `fund_risk_metrics` |
| Macro snapshot | Region scores | `macro_regional_snapshots` |
| SEC 13F | thirteenf_available, sector_weights, drift_detected, drift_quarters | `sec_13f_holdings` |
| SEC ADV | compliance_disclosures, aum_history, fee_structure, funds, team | `sec_managers`, `sec_manager_funds`, `sec_manager_team` |
| SEC ADV Brochure | adv_brochure_sections (item_5, item_8, item_9, item_10) | `sec_manager_brochure_text` |
| SEC Fund Enrichment | insider_sentiment_score, insider_summary (buy/sell counts + values) | `sec_insider_sentiment` MV |
| SEC N-PORT Insider | portfolio_insider_sentiment (weighted avg from top 20 holdings) | `sec_insider_sentiment` via N-PORT holdings |

**Chapter-specific filtering:** Each chapter receives only relevant evidence fields. Recommendation chapter gets no documents. Fee analysis gets no quant/risk metrics.

**Source metadata:** Each chapter receives metadata about data availability: `structured_data_complete`, `structured_data_partial`, `structured_data_absent`, available/missing fields, primary data provider.

**Reference:** `dd_report/evidence_pack.py:22-280`

### 13.7 SEC Data Injection

#### 13F Holdings

Resolves manager name to CIK (case-insensitive match on `sec_managers.firm_name`). Queries last 8 quarters of `sec_13f_holdings`. Computes sector weights for latest 2 dates. Detects sector drift.

**Drift threshold:** 5 percentage points shift in any sector = drift detected.

**Reference:** `dd_report/sec_injection.py:27-100`

#### ADV Manager Data

Resolves manager name to CRD number. Returns:
- `compliance_disclosures` — Item 11 disclosure flag
- `adv_aum_history` — total, discretionary, non-discretionary AUM; total accounts
- `adv_fee_structure` — fee types
- `adv_funds` — list of fund names, types, GAV, investor counts
- `adv_team` — name, title, role, education, certifications, experience, bio summary
- `crd_number` — resolved CRD (used downstream by brochure injection)

**Reference:** `dd_report/sec_injection.py:101-215`

#### ADV Part 2A Brochure Injection

`gather_sec_adv_brochure(db, crd_number)` fetches narrative text from `sec_manager_brochure_text` (17,837 sections across 2,157 managers). Returns `dict[str, str]` keyed by section name. Latest `filing_date` wins per section. Never raises — returns `{}` on error.

**Default sections (4):**
- `item_8` — Methods of Analysis, Investment Strategies, Risk of Loss (truncated to 2,000 chars in template)
- `item_5` — Fees and Compensation (truncated to 1,000 chars)
- `item_9` — Disciplinary Information (truncated to 500 chars)
- `item_10` — Other Financial Industry Activities and Affiliations (truncated to 500 chars)

**Total brochure budget:** ~4,000 chars max, within `manager_assessment` chapter token budget (4,000 tokens).

**Template:** `manager_assessment.j2` renders brochure sections when present, silent when absent. LLM instruction cites items by number (e.g., "Per Item 8 of the ADV Part 2A…").

**Reference:** `dd_report/sec_injection.py:214-265`

#### Form 345 Insider Sentiment

Two integration points inject insider sentiment into DD reports:

**1. Fund-level (via `gather_fund_enrichment`):** For registered US funds, queries `sec_insider_sentiment` materialized view using the fund's `issuer_cik`. Returns `insider_sentiment_score` (0-100) and `insider_summary` (buy_count, sell_count, buy_value, sell_value, unique_buyers, unique_sellers). Neutral score (50.0) is not included.

**2. Portfolio-level (via `gather_sec_nport_data`):** For funds with N-PORT holdings, computes a weighted portfolio-level insider sentiment from the top 20 holdings by `pct_of_nav`. Each holding is matched via CUSIP prefix to `sec_insider_sentiment`. Holdings with neutral scores (50.0) are excluded. Result is NAV-weighted average stored as `portfolio_insider_sentiment`.

**Score formula:** `score = buy_value / (buy_value + sell_value) * 100`
- Excludes sole 10% Owners (portfolio trading, not conviction signals)
- Uses only P (purchase) and S (sale) codes — excludes awards, exercises, gifts, etc.
- Default lookback: 4 quarters

**Data source:** `sec_insider_transactions` table (59,677 rows Q4 2025), aggregated in `sec_insider_sentiment` materialized view (2,956 issuer-quarters). Worker: `form345_ingestion` (lock 900_051, quarterly).

**Query service:** `insider_queries.py` provides `get_insider_sentiment_score()` and `get_insider_summary()` — sync functions matching DD report `asyncio.to_thread()` context.

**Reference:** `dd_report/sec_injection.py:392-415` (fund-level), `dd_report/sec_injection.py:230-270` (portfolio-level), `domains/wealth/services/insider_queries.py`

### 13.8 Confidence Scoring

$$\text{confidence} = \sum_{k} w_k \times S_k$$

| Component $k$ | Weight $w_k$ | Computation |
|---------------|-------------|-------------|
| Chapter completeness | 0.30 | completed / total × 100 |
| Evidence coverage | 0.25 | present keys / 5 expected × 100 |
| Quant data quality | 0.25 | present metrics / 5 expected × 100 |
| Critic outcome | 0.20 | accepted / total × 100, penalized -30 per escalation ratio |

**Expected evidence keys (5):** documents, quant_profile, risk_metrics, scoring_data, macro_snapshot

**Expected quant metrics (5):** cvar_95_3m, sharpe_1y, return_1y, volatility_1y, manager_score

**Score range:** 0.0 to 100.0

**Reference:** `dd_report/confidence_scoring.py:27-96`

### 13.9 Decision Anchor

Derived from confidence score and recommendation chapter content:

1. **Primary:** Parse recommendation chapter for keywords APPROVE/CONDITIONAL/REJECT
2. **Fallback (if parsing fails):**
   - confidence ≥ 70 → `APPROVE`
   - confidence ≥ 40 → `CONDITIONAL`
   - confidence > 0 → `REJECT`

**Reference:** `dd_report/confidence_scoring.py:98-125`

### 13.10 Critic Engine

Adversarial review of generated chapters. Each ANALYTICAL chapter undergoes critic evaluation with a circuit-breaker pattern:

- **Timeout:** 3 minutes per chapter
- **Max iterations:** Configurable
- **Status values:** `pending`, `accepted`, `escalated`

Critic iterations and status are stored per chapter in `ChapterResult`.

### 13.11 Peer Context Injection

Optional peer group comparison injected into relevant chapters:

- Calls `PeerGroupService().compute_rankings()` for the target instrument
- Returns: peer_group_key, peer_count, fallback_level, composite_percentile, annotations

Never fails the chapter — returns empty dict on error.

**Reference:** `dd_report/peer_injection.py:22`

### 13.12 Report Persistence

- Creates/updates `DDReport` record with incremented version
- Batch persists all `DDChapter` records
- Sets status to `pending_approval` if all chapters completed, else `draft`

**Reference:** `dd_report/dd_report_engine.py:472`

---

## 14. SEC Data Integration

### 14.1 Architecture

Three services covering different SEC filing types:

| Service | Filing Type | DB Tables | Reference |
|---------|------------|-----------|-----------|
| `ThirteenFService` | 13F-HR | `sec_13f_holdings`, `sec_13f_diffs` | `data_providers/sec/thirteenf_service.py` |
| `AdvService` | Form ADV | `sec_managers`, `sec_manager_funds`, `sec_manager_team`, `sec_manager_brochure_text` (`crd_number`, `section`, `filing_date`, `content`) | `data_providers/sec/adv_service.py` |
| `InstitutionalService` | 13F-HR (reverse) | `sec_institutional_allocations` | `data_providers/sec/institutional_service.py` |
| `insider_queries` | Form 3/4/5 | `sec_insider_transactions`, `sec_insider_sentiment` (MV) | `domains/wealth/services/insider_queries.py` |

**Critical rule:** Routes and DD reports use ONLY DB-reading methods. EDGAR API calls are restricted to background workers.

### 14.2 13F Holdings Service

#### DB-Only Methods (Safe for Hot Path)

| Method | Description | Reference |
|--------|------------|-----------|
| `read_holdings(cik, quarters=8)` | Last N quarters of holdings | `thirteenf_service.py:72` |
| `read_holdings_for_date(cik, report_date)` | Holdings for specific date | `thirteenf_service.py:87` |
| `get_sector_aggregation(cik, report_date)` | Sector weight breakdown | `thirteenf_service.py:217` |
| `get_concentration_metrics(cik, report_date)` | HHI, top-10, position count | `thirteenf_service.py:262` |
| `compute_diffs(cik, quarter_from, quarter_to)` | Quarter-over-quarter changes | `thirteenf_service.py:167` |

#### Sector Aggregation

Excludes CALL/PUT options (derivative overlays distort sector composition).

$$w_{\text{sector}} = \frac{\sum_{\text{holdings in sector}} \text{market\_value}}{\sum_{\text{all equity holdings}} \text{market\_value}}$$

**Reference:** `thirteenf_service.py:217`

#### Concentration Metrics

$$\text{HHI} = \sum_{i=1}^{N} w_i^2$$

$$\text{Top-10} = \sum_{i=1}^{10} w_{(i)}$$

where $w_{(i)}$ are weights sorted descending.

**Reference:** `thirteenf_service.py:262`

#### Diff Computation

Compares CUSIP-level positions between two quarters:

| Action | Condition |
|--------|-----------|
| `NEW_POSITION` | CUSIP in Q2 only |
| `EXITED` | CUSIP in Q1 only |
| `INCREASED` | Shares increased |
| `DECREASED` | Shares decreased |
| `UNCHANGED` | Same shares |

Weight computation: $w = \text{value} / \text{total\_value}$ per quarter.

**Reference:** `thirteenf_service.py:529`

#### EDGAR Parsing (Workers Only)

- Source: `edgartools` library (`Company(cik).get_filings(form="13F-HR").head(quarters)`)
- Deduplicates by report period (amendments: takes first/latest)
- Max holdings per filing: 15,000 (cap for memory safety — Vanguard has 24K+)
- Upsert chunk size: 2,000 rows
- Staleness TTL: 45 days (appropriate for quarterly filings)
- Rate limit: 8 req/s shared EDGAR limiter

**Reference:** `thirteenf_service.py:99`, `thirteenf_service.py:371`

### 14.3 ADV Manager Service

#### DB-Only Methods (Safe for Hot Path)

| Method | Description | Reference |
|--------|------------|-----------|
| `fetch_manager(crd)` | Manager identity + AUM | `adv_service.py:505` |
| `fetch_manager_funds(crd)` | Fund list | `adv_service.py:561` |
| `fetch_manager_team(crd)` | Team members + bios | `adv_service.py:598` |
| `search_brochure_text(query)` | Full-text search on `content` field (tsvector GIN index) — 17,837 sections across 2,157 managers | `adv_service.py:718` |

#### Data Sources

| Source | Method | Frequency |
|--------|--------|-----------|
| IAPD Search API | `search_managers()` | On-demand (2 req/s) |
| SEC FOIA bulk CSV | `ingest_bulk_adv()` | Monthly |
| Part 2A PDF brochures | `extract_brochure()` | On-demand |

#### CSV Column Mapping (Form ADV)

| Column | Meaning | Reference |
|--------|---------|-----------|
| `Q5F2A` | Discretionary AUM | `adv_service.py:416` |
| `Q5F2B` | Non-discretionary AUM | `adv_service.py:416` |
| `Q5F2C` | Total AUM (fallback: disc + non_disc) | `adv_service.py:416` |
| `Q5F2(f)` | Total accounts | `adv_service.py:416` |
| `Q11` | Compliance disclosures | `adv_service.py:416` |

#### Brochure Section Classification

17 patterns mapping ADV Part 2A Item headings to stable keys (Items 4-18 + non-numbered sections). Used for structured extraction of investment philosophy, fees, disciplinary history, and ESG integration.

**Reference:** `adv_service.py:47-67`

#### Team Extraction

Extracts from Part 2B supplement:
- Person name + title/role via regex
- Certifications: CFA, CFP, CAIA, CPA, FRM, CIPM
- Years of experience
- Bio summary: ~300 chars after name match, truncated at paragraph break

**Reference:** `adv_service.py:70-80`

### 14.4 Institutional Ownership Service

#### DB-Only Method (Safe for Hot Path)

| Method | Description | Reference |
|--------|------------|-----------|
| `read_investors_in_manager(manager_cik)` | Institutional holders from DB | `institutional_service.py:127` |

#### 3-Way Coverage Detection

| Coverage | Meaning | Reference |
|----------|---------|-----------|
| `NO_PUBLIC_SECURITIES` | Manager has no 13F filings on EDGAR | `institutional_service.py:276` |
| `PUBLIC_SECURITIES_NO_HOLDERS` | Manager has filings but no institutional holders found | `institutional_service.py:276` |
| `FOUND` | Institutional holders discovered | `institutional_service.py:276` |

#### Feeder-Master Look-Through

For offshore fund structures:
1. Detect feeder fund suffixes: `offshore`, `cayman`, `ltd`, `limited`, `international`
2. Strip suffixes to derive base entity name (min 3 chars)
3. Resolve CIK for potential US master fund
4. Query institutional holders of the master

**Reference:** `institutional_service.py:425`

#### EFTS Discovery (Workers Only)

Queries SEC EFTS search index with keywords: `endowment`, `pension`, `foundation`, `sovereign`, `insurance`.

- Form filter: `13F-HR`
- Start date: 2020-01-01
- Filer type classified from entity name via regex

**Reference:** `institutional_service.py:525`

---

## 15. Fund Analysis (Top-Down Investment Chain)

### 15.1 Complete Investment Pipeline

```
Stage 1: MACRO INTELLIGENCE
    macro_ingestion → macro_data → regional_macro_service → macro_regional_snapshots
    │
    ├─ Weekly macro committee reports (score deltas, regime transitions)
    ├─ Flash reports (event-driven, 48h cooldown)
    └─ Investment outlook (quarterly narrative)

Stage 2: ALLOCATION
    portfolio_eval → portfolio_snapshots (CVaR, regime, breach status per profile)
    optimizer_service → optimal weights (CLARABEL / NSGA-II Pareto)

Stage 3: SCREENING
    screener_service → 3-layer pipeline (eliminatory → mandate fit → quant ranking)
    │
    ├─ Layer 1: Hard constraints (AUM, domicile, track record)
    ├─ Layer 2: Mandate fit (with 10% watchlist margin)
    └─ Layer 3: Quantitative composite score

Stage 4: DUE DILIGENCE
    dd_report_engine → 8-chapter report (evidence-backed, critic-reviewed)
    │
    ├─ Evidence: quant metrics + risk metrics + SEC 13F + SEC ADV + documents
    ├─ Confidence scoring (0-100)
    └─ Decision anchor (APPROVE / CONDITIONAL / REJECT)

Stage 5: INVESTMENT COMMITTEE
    fund_analyzer → orchestrates DD + quant analysis
    manager_spotlight → deep-dive single manager report
    quant_analyzer → CVaR + scoring + peer comparison

Stage 6: UNIVERSE MANAGEMENT
    asset_universe → fund approval workflow
    watchlist_service → PASS→FAIL transition detection

Stage 7: MODEL PORTFOLIOS
    model_portfolio → portfolio builder + stress scenarios
    rebalancing_service → weight proposals + impact analysis

Stage 8: REBALANCING
    drift_check → block-level drift monitoring
    rebalance_service → cascade actions (CVaR breach triggers)
    weight_proposer → iterative proportional redistribution

Stage 9: MONITORING & ALERTS
    risk_calc → daily risk metrics + momentum signals
    strategy_drift_scanner → z-score anomaly detection (7 metrics)
    drift_monitor → DTW style drift + universe removal impact
    alert_engine → DD expiry (12mo) + rebalance overdue (90d)
    fee_drag_service → fee efficiency analysis
```

### 15.2 Data Flow Between Stages

| From | To | Data Passed |
|------|-----|------------|
| Macro intelligence | Allocation | Regime state, regional scores |
| Allocation | Screening | Profile constraints, block weights |
| Screening | Due diligence | Eligible instruments, required analysis type |
| Due diligence | IC | Confidence score, decision anchor, chapter content |
| IC | Universe | Approval/rejection decisions |
| Universe | Model portfolios | Approved fund list |
| Model portfolios | Rebalancing | Target weights, current weights |
| Rebalancing | Monitoring | Rebalance events, drift thresholds |
| Monitoring | Alerting | Drift scores, breach status |

### 15.3 Orchestrator: FundAnalyzer

Implements `BaseAnalyzer` ABC for the `liquid_funds` profile:

| Method | Delegates To | Reference |
|--------|-------------|-----------|
| `run_deal_analysis()` | `DDReportEngine.generate()` | `fund_analyzer.py:27` |
| `run_portfolio_analysis()` | `QuantAnalyzer.analyze_portfolio()` | `fund_analyzer.py:72` |

**Reference:** `backend/vertical_engines/wealth/fund_analyzer.py`

---

## 16. External Data Ingestion Workers

### 16.1 Complete Worker Inventory

| Worker | Lock ID | Scope | Hypertable | Source | Frequency |
|--------|---------|-------|-----------|--------|-----------|
| `macro_ingestion` | 43 | global | `macro_data` (1mo chunks) | FRED API (~65 series) | Daily |
| `treasury_ingestion` | 900_011 | global | `treasury_data` (1mo chunks) | US Treasury Fiscal Data API | Daily |
| `ofr_ingestion` | 900_012 | global | `ofr_hedge_fund_data` (3mo chunks) | OFR API | Weekly |
| `benchmark_ingest` | 900_004 | global | `benchmark_nav` (1mo chunks) | Yahoo Finance | Daily |
| `instrument_ingestion` | 900_010 | org | `nav_timeseries` | Yahoo Finance | Daily |
| `risk_calc` | 900_007 | org | `fund_risk_metrics` | Computed | Daily |
| `portfolio_eval` | 900_008 | org | `portfolio_snapshots` | Computed | Daily |
| `nport_ingestion` | 900_018 | global | `sec_nport_holdings` (3mo chunks) | SEC EDGAR N-PORT XML | Weekly |
| `sec_13f_ingestion` | 900_021 | global | `sec_13f_holdings`, `sec_13f_diffs` | SEC EDGAR 13F-HR | Weekly |
| `sec_adv_ingestion` | 900_022 | global | `sec_managers`, `sec_manager_funds` | SEC FOIA bulk CSV | Monthly |
| `bis_ingestion` | 900_014 | global | `bis_statistics` (1yr chunks) | BIS SDMX API | Quarterly |
| `imf_ingestion` | 900_015 | global | `imf_weo_forecasts` (1yr chunks) | IMF DataMapper API | Quarterly |
| `drift_check` | 42 | org | `strategy_drift_alerts` | Computed | Daily |
| `form345_ingestion` | 900_051 | global | `sec_insider_transactions`, `sec_insider_sentiment` (MV) | SEC EDGAR Form 345 bulk TSV | Quarterly |

### 16.2 Worker Patterns

All workers follow the same pattern:

1. **Advisory lock:** `pg_try_advisory_lock(LOCK_ID)` — non-blocking, skips if already held
2. **Deterministic lock IDs:** Integer constants, never `hash()` (which is non-deterministic in Python 3.3+)
3. **Unlock in `finally`:** Always releases lock even on error
4. **Chunked upserts:** 200-2,000 rows per statement (asyncpg parameter limit)
5. **Natural key upserts:** `ON CONFLICT DO UPDATE` on natural composite keys
6. **Never raise:** Workers log errors and return partial results

### 16.3 Worker Details

#### Macro Ingestion

- FRED series fetched via `FredService.fetch_batch_concurrent()` with 5 domain threads
- Rate limiter: token bucket at 2 req/s (FRED's limit is 120 req/60s)
- BIS enrichment: reads from `bis_statistics` hypertable (last 180 days)
- IMF enrichment: reads from `imf_weo_forecasts` hypertable (current year - 1)
- Builds regional snapshot via `build_regional_snapshot()` (percentile-rank normalization)
- Writes Redis cache per geography + full dashboard widget (24h TTL)

#### Benchmark Ingest

- Downloads via `yf.download()` in 2-thread pool with retry (3 attempts: 1s/4s/16s backoff)
- Data quality: rejects all-NaN, >5% NaN ratio, zero/negative prices
- Log returns: $r_t = \ln(\text{close}_t / \text{close}_{t-1})$
- Extreme return warning: >50% in a single day
- Staleness warning: latest data >7 business days old
- One ticker maps to multiple blocks (deduplication handled)

#### Treasury Ingestion

- 5 endpoints fetched concurrently via `asyncio.gather`
- Series ID patterns: `RATE_*`, `DEBT_*`, `AUCTION_*`, `FX_*`, `INTEREST_*`
- Deduplication by `(obs_date, series_id)`

---

## 17. Continuous Aggregates & Pre-computation

### 17.1 nav_monthly_returns_agg

**Source:** `nav_timeseries` hypertable (tenant-scoped)

```sql
SELECT
    instrument_id,
    organization_id,
    time_bucket('1 month', nav_date) AS month,
    SUM(return_1d) AS compound_log_return,
    (EXP(SUM(return_1d)) - 1) AS compound_return,
    COUNT(*) AS trading_days,
    MIN(nav) AS min_nav,
    MAX(nav) AS max_nav
FROM nav_timeseries
WHERE return_1d IS NOT NULL
GROUP BY instrument_id, organization_id, time_bucket('1 month', nav_date)
```

**Refresh policy:** Daily, `start_offset` = 3 months, `end_offset` = 1 day
**Index:** `(instrument_id, month DESC)`
**Migration:** `0049_wealth_continuous_aggregates`
**Used by:** Attribution, correlation, performance analytics

### 17.2 benchmark_monthly_returns_agg

**Source:** `benchmark_nav` hypertable (global, no `organization_id`)

```sql
SELECT
    block_id,
    time_bucket('1 month', nav_date) AS month,
    SUM(return_1d) AS compound_log_return,
    (EXP(SUM(return_1d)) - 1) AS compound_return,
    COUNT(*) AS trading_days
FROM benchmark_nav
WHERE return_1d IS NOT NULL
GROUP BY block_id, time_bucket('1 month', nav_date)
```

**Refresh policy:** Daily, `start_offset` = 3 months, `end_offset` = 1 day
**Index:** `(block_id, month DESC)`
**Migration:** `0049_wealth_continuous_aggregates`
**Used by:** Brinson-Fachler attribution (benchmark returns per block)

### 17.3 sec_13f_holdings_agg

**Source:** `sec_13f_holdings` hypertable (global)

```sql
SELECT
    cik,
    time_bucket('3 months', report_date) AS quarter,
    sector,
    SUM(market_value) AS sector_value,
    COUNT(DISTINCT cusip) AS position_count
FROM sec_13f_holdings
WHERE asset_class = 'Shares'
GROUP BY cik, time_bucket('3 months', report_date), sector
```

**Refresh policy:** Daily, `start_offset` = 2 years, `end_offset` = 1 day
**Options:** `materialized_only = true` (SEC 13F data is quarterly — no real-time aggregation needed)
**Index:** `(cik, quarter DESC)`
**Migration:** `0038_manager_screener_indexes_continuous_aggs`
**Used by:** Sector allocation charts over time

### 17.4 sec_13f_drift_agg

**Source:** `sec_13f_diffs` hypertable (global)

```sql
SELECT
    cik,
    time_bucket('3 months', quarter_to) AS quarter,
    COUNT(*) FILTER (WHERE action IN ('NEW_POSITION', 'EXITED')) AS churn_count,
    COUNT(*) AS total_changes
FROM sec_13f_diffs
GROUP BY cik, time_bucket('3 months', quarter_to)
```

**Churn ratio** = `churn_count / total_changes` (computed at query time, not stored).

**Refresh policy:** Daily, `start_offset` = 2 years, `end_offset` = 1 day
**Options:** `materialized_only = true`
**Index:** `(cik, quarter DESC)`
**Migration:** `0038_manager_screener_indexes_continuous_aggs`
**Used by:** Manager screening on portfolio stability

### 17.5 sec_13f_latest_quarter

**Source:** `sec_13f_holdings` hypertable (global)

```sql
SELECT
    cik,
    time_bucket('3 months', report_date) AS quarter,
    SUM(market_value) FILTER (WHERE asset_class = 'Shares') AS total_equity_value,
    COUNT(DISTINCT cusip) FILTER (WHERE asset_class = 'Shares') AS position_count
FROM sec_13f_holdings
GROUP BY cik, time_bucket('3 months', report_date)
```

**Refresh policy:** Daily, `start_offset` = 9 months, `end_offset` = 1 day
**Migration:** `0025_convert_sec_13f_holdings_to_hypertable`
**Used by:** Manager screener (latest AUM, portfolio size)

### 17.6 sec_13f_manager_sector_latest (Materialized View)

**Note:** This is a plain `MATERIALIZED VIEW`, not a continuous aggregate. Refresh is manual (after each 13F ingestion batch).

Computes the top sector by market value for each CIK from the most recent filing. Uses `DISTINCT ON (cik)` + `ORDER BY sector_value DESC`.

**Unique index:** `(cik)`
**Migration:** `0025_convert_sec_13f_holdings_to_hypertable`
**Used by:** Screener display of "top sector" per manager

### 17.7 Refresh Schedule Summary

| Aggregate | Schedule | Start Offset | End Offset | Materialized Only |
|-----------|---------|-------------|------------|-------------------|
| `nav_monthly_returns_agg` | Daily | 3 months | 1 day | No (real-time) |
| `benchmark_monthly_returns_agg` | Daily | 3 months | 1 day | No (real-time) |
| `sec_13f_holdings_agg` | Daily | 2 years | 1 day | Yes |
| `sec_13f_drift_agg` | Daily | 2 years | 1 day | Yes |
| `sec_13f_latest_quarter` | Daily | 9 months | 1 day | No (real-time) |
| `sec_13f_manager_sector_latest` | Manual | — | — | N/A (plain view) |

---

## 18. Alerting & Automated Actions

### 18.1 Strategy Drift Alerts (DTW-Based)

**Source:** `risk_calc` worker computes DTW drift per fund, stored in `fund_risk_metrics.dtw_drift_score`.

**Monitoring:** `drift_monitor.py` scans all funds, flags `dtw_drift_score > 0.15`.

**Alert types:**
- `style_drift` — DTW score exceeds threshold
- `universe_removal` — Deactivated fund still in live portfolio
- `tracking_error` — Implied by strategy drift scanner z-scores

**Reference:** `backend/vertical_engines/wealth/monitoring/drift_monitor.py`

### 18.2 Portfolio Breach Alerts

**Source:** `portfolio_eval` worker computes CVaR utilization per profile.

**Published to:** Redis channel `wealth:alerts:{profile}` on warning/breach transitions.

**Alert content:**
- Profile name
- CVaR current vs limit
- Utilization percentage
- Consecutive breach days
- Trigger status (warning/breach)

**Reference:** `portfolio_eval.py:138`

### 18.3 Watchlist PASS→FAIL Transitions

**Source:** `WatchlistService.check_transitions()` re-screens instruments against current criteria and compares to previous outcomes.

**Transitions detected:**
- PASS → FAIL
- PASS → WATCHLIST
- WATCHLIST → FAIL
- FAIL → PASS (recovery)

Stable transitions (no change) are filtered out.

**Reference:** `backend/vertical_engines/wealth/watchlist/service.py`

### 18.4 Fee Drag Alerts

**Threshold:** Total fee drag ratio > 50% of gross expected return.

$$\text{drag\_ratio} = \frac{\text{total\_fees}}{\text{gross\_expected\_return}}$$

Fee breakdown includes: management fee, performance fee, and instrument-specific costs (bid-ask spread for bonds, brokerage fee for equities).

**Reference:** `backend/vertical_engines/wealth/fee_drag/service.py`

### 18.5 DD Expiry Alerts

Flags funds with:
- No DD report ever generated → `critical`
- DD report older than 12 months → `warning`

Single LEFT JOIN query: `Fund OUTER JOIN DDReport WHERE is_current = true`.

**Reference:** `backend/vertical_engines/wealth/monitoring/alert_engine.py:74`

### 18.6 Rebalance Overdue Alerts

Flags portfolios with:
- No rebalance ever executed → `warning`
- Last rebalance > 90 days ago → `warning`

**Reference:** `backend/vertical_engines/wealth/monitoring/alert_engine.py:129`

### 18.7 Flash Report Triggers

Event-driven with 48-hour cooldown. Requires human review before distribution.

**Cooldown check:** Queries `WealthContent` for most recent `flash_report` per organization. Suppressed if within 48h.

**Reference:** `flash_report.py:33`

---

## 19. Computational Capacity & Performance

### 19.1 ThreadPoolExecutor Usage

| Context | Max Workers | Purpose | Reference |
|---------|-----------|---------|-----------|
| DD Report chapters 1-7 | 5 | Parallel LLM calls | `dd_report_engine.py:328` |
| Walk-forward backtest folds | min(n_splits, 4) | Parallel fold computation | `backtest_service.py:85` |
| FRED batch fetch | 4 | Concurrent API calls | `fred_service.py:347` |
| Benchmark download | 2 | Yahoo Finance retry | `benchmark_ingest.py` |

### 19.2 Batch Operations

| Operation | Batch Size | Purpose | Reference |
|-----------|-----------|---------|-----------|
| pgvector INSERT | 2,000 | Asyncpg parameter limit | Multiple workers |
| DTW batch | Full block matrix | `pairwise_distance(metric="ddtw")` | `drift_service.py:227` |
| Risk metric upsert | Single commit all funds | `pg_insert.on_conflict_do_update` | `risk_calc.py:580` |
| 13F holdings upsert | 2,000 | Chunked INSERT ON CONFLICT | `thirteenf_service.py:706` |
| Benchmark NAV upsert | 200 | Chunked per commit | `benchmark_ingest.py` |
| Macro data upsert | 2,000 | Chunked INSERT ON CONFLICT | `macro_ingestion.py` |

### 19.3 Redis Caching Layer

| Cache Key Pattern | TTL | Triggered By | Reference |
|-------------------|-----|-------------|-----------|
| Optimization result (SHA-256) | 1 hour | `POST /analytics/optimize` | Route-level |
| Correlation refresh marker | 24 hours | `risk_calc` completion | `risk_calc.py:530` |
| Scoring leaderboard (top 50) | 24 hours | `risk_calc` completion | `risk_calc.py:530` |
| Macro dashboard (per-geography) | 24 hours | `macro_ingestion` completion | `macro_ingestion.py` |
| Route cache (various) | 300 seconds | `@route_cache(ttl=300)` | Route decorators |

### 19.4 TimescaleDB Continuous Aggregates

Pre-computed monthly returns eliminate expensive runtime aggregation:

| Aggregate | Rows Aggregated | Query Speedup |
|-----------|----------------|--------------|
| `nav_monthly_returns_agg` | ~252 daily → 12 monthly per year per fund | ~21x fewer rows |
| `benchmark_monthly_returns_agg` | ~252 daily → 12 monthly per year per block | ~21x fewer rows |
| `sec_13f_holdings_agg` | Thousands of positions → quarterly sector totals | Orders of magnitude |
| `sec_13f_drift_agg` | All diffs → quarterly churn counts | Orders of magnitude |

### 19.5 Advisory Locks for Worker Coordination

All workers use PostgreSQL advisory locks with deterministic integer IDs to prevent duplicate computation:

- `pg_try_advisory_lock(ID)` — non-blocking, returns immediately
- If lock not acquired: worker skips gracefully (another instance is running)
- Unlock in `finally` block — never leaked
- IDs are integer constants — never `hash()` (non-deterministic in Python)

### 19.6 Index Strategy (Migration 0048)

11 indexes optimized for wealth analytics workloads:

**Standard indexes (4):**
- `model_portfolios(profile)` filtered `WHERE status = 'live'`
- `strategic_allocation(profile, effective_from, effective_to)`
- `dd_reports(instrument_id, organization_id)` filtered `WHERE is_current = true`
- `dd_chapters(dd_report_id, chapter_order)`

**Hypertable indexes (7):**
- `nav_timeseries(instrument_id, nav_date) INCLUDE (return_1d)` — covering index for correlation/attribution (index-only scan)
- `nav_timeseries(organization_id, instrument_id)` — RLS optimization
- `fund_risk_metrics(instrument_id, calc_date DESC)` — DISTINCT ON optimization for latest metric
- `fund_risk_metrics(organization_id, instrument_id, calc_date DESC)` — RLS + instrument + latest
- `fund_risk_metrics(manager_score DESC NULLS LAST)` filtered `WHERE manager_score IS NOT NULL` — scoring ranking
- `benchmark_nav(block_id, nav_date)` — attribution block date range
- Continuous aggregate indexes: `(instrument_id, month DESC)`, `(block_id, month DESC)`, `(cik, quarter DESC)` × 2

**Reference:** `backend/app/core/db/migrations/versions/0048_wealth_analytics_indexes.py`

### 19.7 Compression Policies

TimescaleDB hypertable compression:

| Table | Chunk Size | Compress After | Segment By |
|-------|-----------|---------------|-----------|
| `macro_data` | 1 month | — | `series_id` |
| `treasury_data` | 1 month | — | `series_id` |
| `ofr_hedge_fund_data` | 3 months | — | `series_id` |
| `benchmark_nav` | 1 month | — | `block_id` |
| `nav_timeseries` | — | — | `organization_id` |
| `fund_risk_metrics` | — | — | `organization_id` |
| `sec_13f_holdings` | 3 months | 6 months | `cik` |
| `sec_13f_diffs` | 3 months | 6 months | `cik` |
| `sec_institutional_allocations` | 3 months | 6 months | `filer_cik` |
| `bis_statistics` | 1 year | — | `series_id` |
| `imf_weo_forecasts` | 1 year | — | `series_id` |

---

## Appendix A: Stress Severity Engine

### A.1 Overview

Computes a composite stress severity score from macro indicators for credit risk assessment.

**Reference:** `backend/quant_engine/stress_severity_service.py`

### A.2 Grade Scale

| Score Range | Grade |
|------------|-------|
| 0-15 | none |
| 16-35 | mild |
| 36-65 | moderate |
| 66-100 | severe |

### A.3 Dimensions (Credit Default)

| Dimension | Indicators | Max Points |
|-----------|-----------|-----------|
| Recession | Recession flag | 40 |
| Financial conditions | NFCI | 25 |
| Yield curve | 2s10s spread | 20 |
| Rate stress | Baa spread, HY spread | 35 |
| Real estate stress | National HPI YoY, mortgage delinquency | 35 |
| Credit stress | Overall loan delinquency | 10 |

**Total score capped at 100.**

**Inverted metrics:** Yield curve 2s10s and National HPI YoY. For these, `value < threshold` indicates stress (below-zero = inverted curve, negative HPI = price decline).

**Reference:** `stress_severity_service.py:75-133`

---

## Appendix B: Portfolio Metrics Service

### B.1 Overview

Aggregates portfolio-level risk metrics from a returns array.

**Reference:** `backend/quant_engine/portfolio_metrics_service.py`

### B.2 Formulas

| Metric | Formula | Reference |
|--------|---------|-----------|
| Annualized return | $\bar{r} \times 252$ | `portfolio_metrics_service.py:62` |
| Annualized volatility | $\sigma \times \sqrt{252}$ (ddof=1) | `portfolio_metrics_service.py:63` |
| Sharpe ratio | $\frac{\bar{r} - r_f/252}{\sigma} \times \sqrt{252}$ | `portfolio_metrics_service.py:66` |
| Sortino ratio | $\frac{\bar{r} - r_f/252}{\sigma_{\text{downside}}} \times \sqrt{252}$ | `portfolio_metrics_service.py:69-75` |
| Max drawdown | $\min\left(\frac{C_t - \max_{s \leq t} C_s}{\max_{s \leq t} C_s}\right)$ | `portfolio_metrics_service.py:78-81` |
| Information ratio | $\frac{\bar{r}_{\text{excess}}}{\sigma_{\text{excess}}} \times \sqrt{252}$ | `portfolio_metrics_service.py:84-89` |

Default risk-free rate: 0.04 (4%).

---

## Appendix C: External Data Service APIs

### C.1 FRED Service

**Class:** `FredService` in `backend/quant_engine/fred_service.py`

- Synchronous (called from `asyncio.to_thread()`)
- Rate limiter: token bucket, 10 burst / 2 tokens per second
- Retry: exponential backoff, $\min(2^a \times 2, 30)$ seconds, max 3 attempts
- Error classification: 429/503/5xx = retry, 400 = skip, 401/403 = fail
- Missing values: `.`, `#N/A`, empty, `NaN`
- Transforms: `yoy_pct`, `yoy_pct_cpi` (needs 13 observations), `mom_delta`
- Trend detection: 3-observation recent average vs full average. >1.02x = rising, <0.98x = falling

### C.2 Treasury Fiscal Data Service

**Class:** `FiscalDataService` in `backend/quant_engine/fiscal_data_service.py`

- Async (native)
- Rate limiter: async token bucket, 5 burst / 5 tokens per second
- Base URL: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service`
- No API key required
- 5 endpoints: rates, debt-to-penny, auctions, exchange rates, interest expense
- Paginated: 10,000 rows per page

### C.3 OFR Hedge Fund Service

**Class:** `OFRHedgeFundService` in `backend/quant_engine/ofr_hedge_fund_service.py`

- Async (native)
- Base URL: `https://data.financialresearch.gov/hf/v1`
- No API key required
- 9 strategy classifications: EQUITY, CREDIT, MACRO, MULTI, RV, EVENT, FOF, FUTURES, OTHER
- 7 data categories: leverage (3 cohorts), industry size (GAV/NAV/count), strategy breakdown, counterparty concentration, repo volumes, risk scenarios, series search

### C.4 Data Commons Service

**Class:** `DataCommonsService` in `backend/quant_engine/data_commons_service.py`

- Async wrapper around sync `datacommons_client` library
- Endpoints: economic indicators, demographic profiles, entity resolution, geographic hierarchy
- Default variables: Count_Person, Median_Age_Person, Median_Income_Household, UnemploymentRate_Person

---

## Appendix D: Peer Group Analysis

### D.1 Overview

Hierarchical peer matching and composite ranking for fund comparison.

**Reference:** `backend/vertical_engines/wealth/peer_group/service.py`

### D.2 Peer Matching

Hierarchical matching with minimum 20 members:
1. Same instrument type + asset class + geography
2. Relaxes geography if insufficient peers
3. Further relaxation as needed

### D.3 Composite Score Weights

**Fund weights:**
| Metric | Weight |
|--------|--------|
| Sharpe ratio | 0.30 |
| Max drawdown | 0.20 |
| 1-year return | 0.25 |
| Volatility | 0.15 |
| Positive months ratio | 0.10 |

**Bond weights:**
| Metric | Weight |
|--------|--------|
| Spread | 0.40 |
| Liquidity | 0.30 |
| Duration efficiency | 0.30 |

### D.4 Ranking Method

- **Winsorization:** 1st and 99th percentile tails
- **Percentile:** `scipy.stats.percentileofscore(kind="rank")`
- **Inversion:** Applied for LOWER_IS_BETTER metrics (max_drawdown, volatility, PE ratio, debt-to-equity)
- **Composite:** Weighted sum of percentiles

**Reference:** `peer_group/service.py:264`

---

## Appendix E: Mandate Fit Evaluation

### E.1 Overview

Evaluates instrument suitability against client mandate constraints.

**Reference:** `backend/vertical_engines/wealth/mandate_fit/service.py`

### E.2 Constraint Evaluators

5 evaluators run per instrument:

| Evaluator | Checks |
|-----------|--------|
| `risk_bucket` | Risk profile compatibility |
| `esg` | ESG score requirements |
| `domicile` | Geographic domicile restrictions |
| `liquidity` | Minimum liquidity constraints |
| `currency` | Currency denomination requirements |

Each evaluator returns pass/fail with suitability contribution. Overall `suitability_score` is the composite.

**Pure logic, no DB access.**

---

## Appendix F: Glossary

| Term | Definition |
|------|-----------|
| **CVaR** | Conditional Value at Risk — expected loss beyond VaR threshold |
| **VaR** | Value at Risk — maximum loss at a given confidence level |
| **dDTW** | Derivative Dynamic Time Warping — distance metric on first derivatives of time series |
| **HHI** | Herfindahl-Hirschman Index — concentration measure, sum of squared weights |
| **OAS** | Option-Adjusted Spread — yield spread over risk-free rate after adjusting for embedded options |
| **Sahm Rule** | Recession indicator based on 3-month moving average of unemployment rate |
| **NFCI** | National Financial Conditions Index (Chicago Fed) |
| **Brinson-Fachler** | Performance attribution decomposition with benchmark-relative adjustment |
| **Carino** | Multi-period linking method for attribution that handles compounding |
| **Marchenko-Pastur** | Random matrix theory law giving the distribution of eigenvalues of random correlation matrices |
| **Absorption Ratio** | Fraction of total variance explained by top eigenvalues (Kritzman & Li, 2010) |
| **Cornish-Fisher** | VaR/CVaR expansion adjusting for non-normality via skewness and kurtosis |
| **NSGA-II** | Non-dominated Sorting Genetic Algorithm II — multi-objective evolutionary optimizer |
| **CLARABEL** | Interior point conic solver for convex optimization |
| **RLS** | Row-Level Security — PostgreSQL policy restricting queries to tenant data |
| **SSE** | Server-Sent Events — unidirectional server-to-client streaming |
