# Analytical Capabilities Reference (v3)

> Audited and Updated: 2026-04-08 (v3: Structural audit passed. Clarified async exceptions in quant_engine. Corrected worker filenames.)

Comprehensive reference of the Netz Analysis Engine's quantitative, risk, and performance analytics stack. Covers 30 quant services, 9 vertical engines, 31 background workers, and 5 report engines — totaling ~9,000 lines of analytics code.

---

## Architecture Overview

```
                 ┌───────────────────────────────────────────────────────┐
                 │                   Frontend (SvelteKit)                │
                 │  /analytics (portfolio)  │  /analytics/[entityId]    │
                 │  /risk (real-time SSE)   │  /screener                │
                 └───────────────────┬──────┴────────────┬──────────────┘
                                    │  REST/SSE          │
                 ┌──────────────────▼────────────────────▼──────────────┐
                 │              FastAPI Routes (async)                   │
                 │  analytics.py  │  entity_analytics.py  │  risk.py    │
                 └───────┬────────┴────────────┬──────────┴─────────────┘
                         │                     │
        ┌────────────────▼──────────┐  ┌───────▼─────────────────┐
        │    quant_engine/ (sync*)  │  │ vertical_engines/wealth/ │
        │  Math, zero I/O           │  │ Domain orchestrators     │
        │  Frozen dataclass results │  │ DB session injection     │
        └────────────────┬──────────┘  └───────┬─────────────────┘
                         │                     │
        ┌────────────────▼─────────────────────▼────────────────────┐
        │          Background Workers (async, advisory locks)       │
        │  risk_calc  │  portfolio_eval  │  drift_check  │  ...     │
        └──────────────────────┬────────────────────────────────────┘
                               │
        ┌──────────────────────▼────────────────────────────────────┐
        │        PostgreSQL 16 + TimescaleDB + pgvector             │
        │  nav_timeseries │ fund_risk_metrics │ macro_data │ ...    │
        └───────────────────────────────────────────────────────────┘
```

**Key invariants:**
- Most `quant_engine/` services are **pure sync computation** (e.g. `cvar_service`, `tail_var_service`, `attribution_service`) — no I/O, no DB, no ORM. Input: numpy arrays. Output: frozen dataclasses.
- *Exception:* Some `quant_engine/` modules (`optimizer_service.py`, `regime_service.py`, and data ingestion helpers like `ofr_hedge_fund_service.py` and `fiscal_data_service.py`) contain `async def` methods for executing complex multi-step optimizations or fetching data from DB/external APIs.
- `vertical_engines/wealth/` services receive `AsyncSession` via injection. They orchestrate quant services + DB queries.
- All results use `@dataclass(frozen=True, slots=True)` — immutable, thread-safe.

---

## 1. Risk & Volatility

### 1.1 CVaR / VaR

**Service:** `quant_engine/cvar_service.py`

| Metric | Formula | Notes |
|--------|---------|-------|
| Historical VaR (95%) | `percentile(returns, 5)` | 5th percentile of return distribution |
| Historical CVaR (95%) | `mean(returns[returns <= VaR])` | Expected Shortfall — average of tail losses |
| Regime-Conditional CVaR | CVaR filtered to stress-period returns | Tighter in RISK_OFF/CRISIS regimes |

**Config:** Per-profile CVaR limits (conservative: -8%, moderate: -6%, growth: -12%).

**Breach cascade:** OK → Warning → Breach → Hard Stop.

### 1.2 Parametric & Modified VaR (eVestment Section VII)

**Service:** `quant_engine/tail_var_service.py`

| Metric | Formula | eVestment Ref |
|--------|---------|---------------|
| Parametric VaR | `E(R) + Z_c * sigma` | Normal assumption |
| Modified VaR | Cornish-Fisher: `VaR + (z^2-1)/6 * S + (z^3-3z)/24 * K - (2z^3-5z)/36 * S^2` | p.71 — adjusts for skew/kurtosis |
| ETL (CVaR) | `mean(R[R <= VaR])` | Historical expected tail loss |
| Modified ETL | `mean(R[R <= mVaR])` | Using CF-adjusted threshold |
| ETR | `mean(R[R >= upper_quantile])` | Right-tail expected return |
| STARR Ratio | `(E(R) - Rf) / \|ETL\|` | p.72 — tail-risk-adjusted return |
| Rachev Ratio | `ETR_alpha / \|ETL_beta\|` | p.72 — right/left tail ratio |
| Jarque-Bera | `n * [S^2/6 + (K-3)^2/24]` | Normality test (p > 0.05 = normal) |

**Confidence levels:** 90%, 95%, 99% (parametric); 95%, 99% (modified).

### 1.3 GARCH(1,1) Conditional Volatility

**Service:** `quant_engine/garch_service.py`

| Output | Description |
|--------|-------------|
| `volatility_garch` | 1-step-ahead annualized forecast |
| `omega`, `alpha`, `beta` | GARCH(1,1) parameters |
| `persistence` | `alpha + beta` (< 1 for stationarity) |

**Requirements:** `arch>=7.0`, minimum 100 observations. Falls back to sample volatility if arch unavailable.

### 1.4 Stress Severity Scoring

**Service:** `quant_engine/stress_severity_service.py`

Scores macro stress on 0-100 scale across 6 dimensions:

| Dimension | Indicators | Threshold Examples |
|-----------|-----------|-------------------|
| Recession | NBER flag | Binary |
| Financial Conditions | NFCI | > 0 = tightening |
| Yield Curve | 2s10s spread | < 0 = inversion |
| Rate Stress | Baa/HY spreads | > 500bps = stress |
| Real Estate | HPI YoY, mortgage delinquency | HPI < -5% |
| Credit Stress | Loan delinquency | > historical P75 |

**Grading:** 0-15 = None, 16-35 = Mild, 36-65 = Moderate, 66+ = Severe.

---

## 2. Portfolio Optimization

### 2.1 CLARABEL 4-Phase Cascade

**Service:** `quant_engine/optimizer_service.py`

```
Phase 1: Max risk-adjusted return (Sharpe objective)
    ↓ if CVaR breached
Phase 1.5: Robust SOCP (ellipsoidal uncertainty sets)
    ↓ if still infeasible
Phase 2: Variance-capped (derived from CVaR limit)
    ↓ if still infeasible
Phase 3: Minimum variance
    ↓ if still infeasible
Heuristic fallback (equal weight within constraints)
```

**Solver:** CLARABEL (primary) → SCS (fallback per phase).

**Features:**
- Regime CVaR multipliers: RISK_OFF = 0.85, CRISIS = 0.70
- Turnover penalty: L1 slack variables penalizing |w_new - w_old|
- Block-group sum constraints (strategic allocation bands)
- Single-fund ceiling (default 25%)

### 2.2 Black-Litterman Expected Returns

**Service:** `quant_engine/black_litterman_service.py`

| Step | Formula |
|------|---------|
| Market-implied returns | `pi = lambda * Sigma * w_mkt` |
| View incorporation | Idzorek confidence-to-omega mapping |
| Posterior returns | `mu_BL = inv(inv(tau*Sigma) + P'*Omega^-1*P) * (inv(tau*Sigma)*pi + P'*Omega^-1*Q)` |

**Inputs:** Market equilibrium weights, covariance matrix, IC views (absolute or relative with confidence), risk aversion (lambda), tau.

### 2.3 Multi-Objective Pareto Optimization

**Service:** `quant_engine/optimizer_service.py` (`optimize_portfolio_pareto`)

NSGA-II multi-objective optimization producing Sharpe vs CVaR Pareto front. Weekly/on-demand only (45-135s). Returns 202 immediately with SSE streaming for progress.

### 2.4 Walk-Forward Backtest

**Service:** `quant_engine/backtest_service.py`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gap` | 2 | Trading days between train/test (T+1 NAV + buffer) |
| `n_splits` | 5 | TimeSeriesSplit folds |
| `test_size` | 63 | 3-month fixed test periods |

Per-fold metrics: Sharpe, CVaR, max drawdown, n_obs.

---

## 3. Return & Performance Analysis

### 3.1 Return Statistics (eVestment Sections I-V)

**Service:** `quant_engine/return_statistics_service.py` — 16 metrics

| Category | Metrics |
|----------|---------|
| Absolute Return | Arithmetic mean (monthly), geometric mean (monthly), avg gain, avg loss, gain/loss ratio |
| Absolute Risk | Gain std dev, loss std dev, downside deviation (MAR-based, N denominator), semi-deviation |
| Risk-Adjusted | Sterling ratio, omega ratio (MAR-based), Treynor ratio, Jensen alpha |
| Proficiency | Up percentage ratio, down percentage ratio |
| Regression | R-squared |

**Input:** Daily returns + optional benchmark. Internally aggregates to monthly (21-day blocks).

### 3.2 Rolling Returns

**Service:** `quant_engine/rolling_service.py`

Windows: 1M (21d), 3M (63d), 6M (126d), 1Y (252d). Annualized returns per rolling window.

### 3.3 Drawdown Analysis

**Service:** `quant_engine/drawdown_service.py`

| Output | Description |
|--------|-------------|
| `series` | Full drawdown time series (NAV - running_max) / running_max |
| `max_drawdown` | Worst peak-to-trough decline |
| `current_drawdown` | Current distance from all-time high |
| `worst_periods` | Top N worst drawdown periods with start/trough/end dates, depth, duration, recovery |
| `longest_duration_days` | Longest time spent in drawdown |
| `avg_recovery_days` | Average recovery time across all periods |

### 3.4 Portfolio Metrics

**Service:** `quant_engine/portfolio_metrics_service.py`

| Metric | Formula |
|--------|---------|
| Sharpe | `(mean_daily - rf_daily) / std * sqrt(252)` |
| Sortino | `(mean_daily - rf_daily) / downside_std * sqrt(252)` |
| Information Ratio | `mean(excess) / std(excess) * sqrt(252)` |
| Calmar | `annualized_return / \|max_drawdown\|` |

### 3.5 Up/Down Capture Ratios

Computed in `entity_analytics.py` from monthly returns vs benchmark:

| Metric | Formula |
|--------|---------|
| Up Capture | `mean(R_fund[bm>0]) / mean(R_bm[bm>0]) * 100` |
| Down Capture | `mean(R_fund[bm<0]) / mean(R_bm[bm<0]) * 100` |
| Up Number Ratio | `count(R_fund>0 when bm>0) / count(bm>0) * 100` |
| Down Number Ratio | `count(R_fund>R_bm when bm<0) / count(bm<0) * 100` |

---

## 4. Attribution, Factors & Correlation

### 4.1 Brinson-Fachler Attribution

**Service:** `quant_engine/attribution_service.py`

| Effect | Formula |
|--------|---------|
| Allocation | `(w_p - w_b) * (R_b_sector - R_b_total)` |
| Selection | `w_b * (R_p_sector - R_b_sector)` |
| Interaction | `(w_p - w_b) * (R_p_sector - R_b_sector)` |

Multi-period linking via Carino smoothing factors: `ln(1+R) / R`.

**Policy benchmark approach (CFA CIPM):** Benchmark weights = strategic allocation targets. Benchmark returns = per-block benchmark ticker returns from `benchmark_nav`.

### 4.2 PCA Factor Decomposition

**Service:** `quant_engine/factor_model_service.py`

| Output | Description |
|--------|-------------|
| Factor returns | PCA-extracted latent factors (T x K) |
| Factor loadings | Per-fund exposure to each factor (N x K) |
| Portfolio factor exposures | `loadings^T * weights` |
| R-squared | Overall model fit |
| Systematic risk % | Variance explained by factors / total variance |
| Specific risk % | 100% - systematic risk % |
| Factor contributions | Per-factor % contribution to portfolio variance |

Optional macro labeling: correlates PCA factors with VIX, DGS10, CPI, etc.

### 4.3 Correlation & Concentration

**Service:** `quant_engine/correlation_regime_service.py`

| Metric | Description |
|--------|-------------|
| Correlation matrix | Pearson correlation (recent window) |
| Eigenvalue concentration | Marchenko-Pastur denoised eigenvalues |
| Absorption ratio | Kritzman & Li — fraction of variance explained by top N eigenvectors |
| Diversification ratio | Choueifaty — weighted avg vol / portfolio vol |
| Contagion flags | Correlation change > threshold AND currently > 0.7 |
| Regime shift detection | Baseline vs recent window divergence |

**Denoising:** Marchenko-Pastur eigenvalue clipping. **Shrinkage:** Ledoit-Wolf covariance estimation.

### 4.4 Risk Budgeting (eVestment p.43-44)

**Service:** `quant_engine/risk_budgeting_service.py`

| Metric | Formula | Invariant |
|--------|---------|-----------|
| MCTR | `(Sigma * w)_i / sigma_p` | `sum(w_i * MCTR_i) = sigma_p` |
| PCTR | `w_i * MCTR_i / sigma_p` | Sums to 100% |
| MCETL | `d(ETL)/d(w_i)` via finite difference | Euler decomposition |
| PCETL | `w_i * MCETL_i / ETL_p` | Sums to 100% |
| Implied Return (vol) | `STARR * MCTR_i` | STARR-optimal reference |
| Implied Return (ETL) | `STARR * MCETL_i` | |
| Difference | `mean_return_i - implied_return_i` | Positive = increase allocation |

---

## 5. Peer Analysis & Scoring

### 5.1 Peer Group Rankings (eVestment Section IV)

**Service:** `quant_engine/peer_group_service.py`

**Methodology:**
1. Match peers by `strategy_label` (37 granular categories)
2. Compute percentile rank (0-100) per metric
3. Assign quartile (Q1=best, Q4=worst)
4. Falls back to broader cohort if exact match < 10 peers

**Default metrics ranked:** `sharpe_1y`, `sortino_1y`, `return_1y`, `max_drawdown_1y`, `volatility_1y`, `alpha_1y`, `manager_score`.

**Direction-aware:** Higher is better for Sharpe, return, alpha. Lower is better for volatility, tracking error. Less negative is better for max drawdown.

### 5.2 Composite Fund Scoring (0-100)

**Service:** `quant_engine/scoring_service.py`

| Component | Weight | Range | Scoring |
|-----------|--------|-------|---------|
| Return Consistency | 0.20 | -20% to +40% | Linear normalization |
| Risk-Adjusted Return | 0.25 | Sharpe -1.0 to 3.0 | Linear normalization |
| Drawdown Control | 0.20 | Max DD -50% to 0% | Linear normalization |
| Information Ratio | 0.15 | IR -1.0 to 2.0 | Linear normalization |
| Flows Momentum | 0.10 | 0-100 scale | Pre-computed signal |
| Fee Efficiency | 0.10 | `max(0, 100 - ER*50)` | 0% ER → 100, 2% → 0 |
| Insider Sentiment | opt-in | Depends on Form 345 data | Only if config weight > 0 |

### 5.3 Active Share (eVestment p.73)

**Service:** `quant_engine/active_share_service.py`

| Metric | Formula |
|--------|---------|
| Active Share | `0.5 * sum(\|w_fund_i - w_index_i\|)` over union of positions |
| Overlap | `100 - Active Share` |
| Efficiency | `excess_return / (active_share / 100)` |

**Classification:** >= 80% = Stock Picker, >= 60% = Active, >= 30% = Moderately Active, < 30% = Closet Indexer.

**Data source:** Fund holdings from `sec_nport_holdings` (N-PORT quarterly). Benchmark index from static reference (e.g., S&P 500, MSCI World). 13F manager-level holdings may serve as supplementary context, NOT as benchmark.

### 5.4 N-PORT vs 13F Holdings

O Netz Analysis Engine usa DUAS fontes de holdings SEC distintas:

| Dimensao | N-PORT (Fund-Level) | 13F (Manager-Level) |
|----------|-------------------|-------------------|
| **Filer** | Registered investment companies (fundos) | Institutional investment managers (gestoras) |
| **Escopo** | Portfolio do fundo individual | Posicoes agregadas da gestora |
| **Frequencia** | Trimestral (N-PORT-X, N-PORT-EX) | Trimestral (13F-HR) |
| **Uso no DD Report** | **PRIMARY** para registered US funds | **SUPPLEMENTARY** ou proxy se N-PORT indisponivel |
| **Holdings** | Securities + alternatives + cash | Equity + options apenas |
| **Classificacao setorial** | `issuerCat` (tipo de emissor) + GICS enriched | GICS padrao |
| **Disponibilidade** | ~2000 registered funds (+ ETFs, BDCs) | ~8500 managers |
| **Tabela** | `sec_nport_holdings` | `sec_13f_holdings` |

**Regra de priorizacao no DD Report:**
1. Se `sec_universe == "registered_us"` e `fund_cik` disponivel → N-PORT como fonte primaria (`holdings_source = "nport"`)
2. 13F serve como overlay suplementar ("Manager Firm Context") quando N-PORT disponivel
3. 13F serve como proxy ("proxy — no fund-level N-PORT available") quando N-PORT indisponivel (fundos privados, UCITS)

**Active Share computation:** Usa N-PORT fund holdings vs benchmark estatico (nao 13F).

**Fund sector analysis:** Usa N-PORT sector weights (mapeamento asset-class-aware via `label_nport_sector()`).

**Manager firm context:** Usa 13F sector weights (perspectiva suplementar).

**Reference:** `dd_report/sec_injection.py:160-361` (N-PORT), `dd_report/sec_injection.py:85-158` (13F), `dd_report/dd_report_engine.py:343-400` (resolucao)

---

## 6. Simulation & Forward-Looking

### 6.1 Monte Carlo (Block Bootstrap)

**Service:** `quant_engine/monte_carlo_service.py`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `n_simulations` | 10,000 | Number of paths |
| `block_size` | 21 | Trading days per block (preserves autocorrelation) |
| `horizons` | [252, 756, 1260, 1764, 2520] | 1Y-10Y |
| `statistic` | `max_drawdown` | Also: `return`, `sharpe` |

**Does NOT assume normal distribution.** Block bootstrap preserves the empirical skewness and kurtosis of the return series.

**Output:**
- Percentile distribution (1st, 5th, 10th, 25th, 50th, 75th, 90th, 95th, 99th)
- Confidence bars across horizons (5th-95th range)
- Historical value for comparison
- Seed for reproducibility

### 6.2 Stress Testing

**Service:** `quant_engine/stress_severity_service.py` + optimizer integration

4 parametric scenarios applied to portfolio:

| Scenario | Methodology |
|----------|------------|
| GFC (2008) | Correlation spike + volatility multiplier |
| COVID (2020) | Sharp drawdown + rapid recovery |
| Taper Tantrum (2013) | Bond sell-off, equity resilience |
| Rate Shock | Parallel yield curve shift |

Available via `POST /stress-test` with portfolio weights.

---

## 7. Market Regime Detection

### 7.1 Regime Classification

**Service:** `quant_engine/regime_service.py`

| Regime | Trigger Signals |
|--------|----------------|
| CRISIS | VIX >= 35 |
| INFLATION | CPI YoY > threshold |
| RISK_OFF | VIX >= 25 (below CRISIS threshold) |
| RISK_ON | Default (no stress signals) |

**Priority cascade:** CRISIS > INFLATION > RISK_OFF > RISK_ON.

**Hysteresis:** Asymmetric — immediate CRISIS entry, slow RISK_ON recovery.

### 7.2 Regime-Conditioned Analytics

Regime detection feeds into:
- **CVaR limits:** Multiplied by regime factor (RISK_OFF=0.85, CRISIS=0.70)
- **Covariance estimation:** Short window in stress, long in normality
- **Portfolio evaluation:** Daily regime classification in `portfolio_snapshots`
- **Rebalancing triggers:** Sustained regime switch triggers rebalance cascade

---

## 8. Drift & Monitoring

### 8.1 Strategy Drift Detection

**Service:** `quant_engine/drift_service.py` + `vertical_engines/wealth/monitoring/`

| Signal | Methodology |
|--------|------------|
| Weight drift | `\|current_weight - target_weight\|` per block |
| DTW drift | Dynamic Time Warping distance vs block benchmark (derivative, length-normalized) |
| Metric anomalies | Z-score of rolling metrics vs 1Y baseline |

**Severity:** None (0 anomalous metrics), Moderate (1-2), Severe (3+).

**Thresholds:** Maintenance drift = 5%, Urgent = 10%. Breaches create `rebalance_events`.

### 8.2 Momentum Signals

**Service:** `quant_engine/talib_momentum_service.py`

Pre-computed by `risk_calc` worker into `fund_risk_metrics`:

| Signal | Formula | Range |
|--------|---------|-------|
| RSI(14) | Relative Strength Index, 14-period | 0-100 |
| Bollinger Position | `(price - lower) / (upper - lower)` | 0-1 |
| NAV Momentum Score | Composite NAV trend | 0-100 |
| Flow Momentum Score | AUM/flow trend | 0-100 |
| Blended Momentum | Weighted combination | 0-100 |

---

## 9. Screening Pipeline

### 9.1 Three-Layer Deterministic Screening

**Service:** `vertical_engines/wealth/screener/service.py`

```
Layer 1: Eliminatory (hard rules)
  ↓ PASS only
Layer 2: Mandate Fit (client constraints)
  ↓ PASS only
Layer 3: Quant Scoring (percentile rank)
  → Final score + pass/fail
```

| Layer | Criteria Examples | Result |
|-------|------------------|--------|
| 1 — Eliminatory | Min AUM, max expense ratio, excluded fund types (target date, index), domicile restrictions | PASS/FAIL (binary) |
| 2 — Mandate Fit | Risk bucket, ESG threshold, liquidity requirements, currency matching, geography | PASS/FAIL with suitability score |
| 3 — Quant Scoring | Peer-relative percentile rank on Sharpe, drawdown, return, volatility | Score 0-100 |

**Config-driven:** No LLM, no ML. Rules from `ConfigService`. Enriched attributes (expense_ratio, is_index, is_target_date) flow from SEC N-CEN + XBRL at import time.

---

## 10. Data Ingestion Workers

### 10.1 Market Data

| Worker | Lock ID | Frequency | Source | Target Table |
|--------|---------|-----------|--------|-------------|
| `instrument_ingestion` | 900_010 | Daily | Yahoo Finance | `nav_timeseries` (global) |
| `benchmark_ingest` | 900_004 | Weekly | Yahoo Finance | `benchmark_nav` (global) |
| `portfolio_nav_synthesizer` | 900_030 | Daily | Computed | `model_portfolio_nav` |

### 10.2 Macroeconomic Data

| Worker | Lock ID | Frequency | Source | Target Table |
|--------|---------|-----------|--------|-------------|
| `macro_ingestion` | 43 | Daily | FRED API (~65 series, 4 regions) | `macro_data` (hypertable) |
| `treasury_ingestion` | 900_011 | Daily | US Treasury API | `treasury_data` (hypertable) |
| `ofr_ingestion` | 900_012 | Weekly | OFR API | `ofr_hedge_fund_data` |
| `bis_ingestion` | 900_014 | Quarterly | BIS SDMX | `bis_statistics` (hypertable) |
| `imf_ingestion` | 900_015 | Quarterly | IMF DataMapper | `imf_weo_forecasts` (hypertable) |

### 10.3 SEC EDGAR Data

| Worker | Lock ID | Frequency | Source | Target Table |
|--------|---------|-----------|--------|-------------|
| `nport_ingestion` | 900_018 | Weekly | N-PORT XML | `sec_nport_holdings` (hypertable) |
| `sec_13f_ingestion` | 900_021 | Weekly | 13F-HR (edgartools) | `sec_13f_holdings`, `sec_13f_diffs` |
| `sec_adv_ingestion` | 900_022 | Monthly | FOIA bulk CSV | `sec_managers`, `sec_manager_funds` |
| `sec_bulk_ingestion` | 900_050 | Quarterly | DERA bulk ZIPs | `sec_etfs`, `sec_bdcs`, `sec_money_market_funds` |
| `form345_ingestion` | 900_051 | Quarterly | Form 345 bulk TSV | `sec_insider_transactions` |
| `nport_fund_discovery` | 900_024 | Weekly | N-PORT headers | `sec_registered_funds` |
| `universe_sync` | 900_070 | Weekly | SEC/ESMA catalog | `instruments_universe` |

### 10.4 European Data

| Worker | Lock ID | Frequency | Source | Target Table |
|--------|---------|-----------|--------|-------------|
| `esma_ingestion` | 900_023 | Weekly | ESMA Fund Register | `esma_funds`, `esma_managers` |

### 10.5 Computation Workers

| Worker | Lock ID | Frequency | What It Computes |
|--------|---------|-----------|-----------------|
| `risk_calc` | 900_007 | Daily | CVaR, VaR, returns, volatility, Sharpe, Sortino, alpha, beta, GARCH, momentum (RSI/BB), DTW drift, manager score, peer percentiles |
| `portfolio_eval` | 900_008 | Daily | Portfolio CVaR status, breach detection, regime classification for all 3 profiles |
| `drift_check` | 42 | Daily | Allocation drift vs target, rebalance events when thresholds breached |
| `regime_fit` | 900_026 | Daily | 2-state HMM on VIX, RISK_ON/RISK_OFF/CRISIS classification |
| `screening_batch` | 900_002 | Weekly | Re-screen all active instruments through 3-layer pipeline |
| `watchlist_batch` | 900_003 | Weekly | Re-evaluate watchlist instruments, detect PASS→FAIL transitions |
| `wealth_embedding_worker` | 900_041 | Daily | OpenAI embeddings for 16 sources into `wealth_vector_chunks` |

---

## 11. Report Engines

### 11.1 DD Report (8 Chapters)

**Engine:** `vertical_engines/wealth/dd_report/dd_report_engine.py`

Parallel execution: chapters 1-7 run concurrently (ThreadPoolExecutor, max_workers=5), chapter 8 sequential (consumes summaries from 1-7).

| Chapter | Content |
|---------|---------|
| 1 | Manager & Firm Overview |
| 2 | Investment Process & Philosophy |
| 3 | Performance Analysis (quant metrics, peer comparison) |
| 4 | Risk Analysis (VaR, drawdown, factor exposure) |
| 5 | Operational Due Diligence |
| 6 | Fee & Cost Analysis |
| 7 | ESG & Governance |
| 8 | Recommendation (synthesizes 1-7) |

**Evidence Pack:** Frozen dataclass combining SEC data, risk metrics, quant analysis, peer rankings, geographic/ESG attributes. Assembled once, passed to all chapters.

### 11.2 Other Report Engines

| Engine | Location | Output |
|--------|----------|--------|
| Fact Sheet | `vertical_engines/wealth/fact_sheet/` | 1-page institutional PDF (Executive/Institutional, PT/EN i18n) |
| Long Form Report | `vertical_engines/wealth/long_form_report/` | Multi-chapter narrative DD (SSE streaming, Semaphore(2)) |
| Flash Report | `vertical_engines/wealth/flash_report.py` | Event-driven market flash (48h cooldown) |
| Investment Outlook | `vertical_engines/wealth/investment_outlook.py` | Quarterly macro narrative |
| Manager Spotlight | `vertical_engines/wealth/manager_spotlight.py` | Deep-dive single manager analysis |
| Macro Committee | `vertical_engines/wealth/macro_committee_engine.py` | Weekly regional macro reports |

---

## 12. Entity Analytics Vitrine

**Route:** `GET /analytics/entity/{entity_id}?window={3m|6m|1y|3y|5y}&benchmark_id={id}`

Polymorphic — works for both funds (`instrument`) and model portfolios. Returns 7 metric groups in a single response:

| Group | Metrics | Source Service |
|-------|---------|---------------|
| 1. Risk Statistics | Return, volatility, Sharpe, Sortino, Calmar, max DD, alpha, beta, TE, IR | `portfolio_metrics_service` |
| 2. Drawdown | Series, max/current DD, worst periods, duration, recovery | `drawdown_service` |
| 3. Capture Ratios | Up/down capture, up/down number ratio vs benchmark | Inline computation |
| 4. Rolling Returns | 1M/3M/6M/1Y annualized rolling returns | `rolling_service` |
| 5. Distribution | Histogram (Freedman-Diaconis), mean, std, skew, kurtosis, VaR, CVaR | `cvar_service` |
| 6. Return Statistics | 16 eVestment I-V metrics (gain/loss, deviations, ratios) | `return_statistics_service` |
| 7. Tail Risk | Parametric/modified VaR, ETL, ETR, STARR, Rachev, Jarque-Bera | `tail_var_service` |

**Benchmark resolution priority:** Explicit param > entity's block benchmark > SPY fallback.

**Additional entity-level endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /analytics/peer-group/{entity_id}` | Peer rankings by strategy_label |
| `POST /analytics/monte-carlo` | Block bootstrap simulation (client-triggered) |

---

## 13. Portfolio Analytics Endpoints

**Router:** `/analytics/`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analytics/backtest` | POST | Walk-forward cross-validation |
| `/analytics/optimize` | POST | CLARABEL portfolio optimization (cached) |
| `/analytics/optimize/pareto` | POST | NSGA-II multi-objective (async, SSE) |
| `/analytics/optimize/pareto/{job_id}/stream` | GET | SSE progress stream |
| `/analytics/correlation` | GET | Correlation matrix across blocks |
| `/analytics/rolling-correlation` | GET | Pairwise rolling Pearson correlation |
| `/analytics/risk-budget/{profile}` | POST | MCTR/PCTR/MCETL/PCETL decomposition |
| `/analytics/factor-analysis/{profile}` | GET | PCA factor contributions + R-squared |
| `/analytics/monte-carlo` | POST | Block bootstrap Monte Carlo |
| `/analytics/peer-group/{entity_id}` | GET | Strategy-matched peer rankings |
| `/analytics/correlation-regime/{profile}` | GET | Regime-conditioned correlation matrix com Marchenko-Pastur denoising |
| `/analytics/correlation-regime/{profile}/pair/{a}/{b}` | GET | Rolling pairwise correlation com regime overlay |
| `/analytics/active-share/{entity_id}` | GET | Active Share vs benchmark (requer benchmark_id query param) |

All endpoints use Redis caching (SHA-256 input hash, 1h TTL) where applicable.

---

## 14. Frontend Visualization

### 14.1 Entity Analytics Page (`/analytics/[entityId]`)

11 panels rendered from 7 backend metric groups + 4 additional endpoints:

| Panel | Component | Data Source |
|-------|-----------|------------|
| Risk Statistics Grid | `RiskStatisticsGrid.svelte` | Group 1 |
| Drawdown Chart | `DrawdownChart.svelte` | Group 2 (ECharts area, underwater style) |
| Capture Ratios | `CaptureRatiosPanel.svelte` | Group 3 (bar chart + metrics) |
| Rolling Returns | `RollingReturnsChart.svelte` | Group 4 (multi-series line) |
| Return Distribution | `ReturnDistributionChart.svelte` | Group 5 (histogram + normal overlay) |
| Return Statistics | `ReturnStatisticsPanel.svelte` | Group 6 (16-metric grid, absolute/relative split) |
| Tail Risk | `TailRiskPanel.svelte` | Group 7 (VaR bar chart + normality badge) |
| Peer Group | `PeerGroupPanel.svelte` | `/peer-group/{id}` (quartile table, Q1-Q4 badges) |
| Monte Carlo | `MonteCarloPanel.svelte` | `/monte-carlo` (client-triggered, percentile table + confidence bars) |
| Active Share | `ActiveSharePanel.svelte` | `/analytics/active-share/{entity_id}` — benchmark_id obrigatório via URL param. Hero metric: active share %, classification badge (Stock Picker/Active/Moderately Active/Closet Indexer), overlap %, efficiency com sinal explícito, position counts. Empty state quando benchmark_id ausente. |

### 14.2 Portfolio Analytics Page (`/analytics`)

| Section | Component | Backend Endpoint |
|---------|-----------|-----------------|
| Attribution | Master/detail Brinson-Fachler | `/analytics/attribution/{profile}` |
| Strategy Drift | Anomaly alerts with severity | `/analytics/strategy-drift/alerts` |
| Correlation | Heatmap + eigenvalue decomposition | `/analytics/correlation` |
| Rolling Correlation | Drill-down by instrument pair | `/analytics/rolling-correlation` |
| Pareto Optimization | SSE-streamed multi-objective | `/analytics/optimize/pareto` |
| Walk-Forward Backtest | Fold metrics table | `/analytics/backtest` |
| Risk Budget | Table + scatter (mean vs implied) | `/analytics/risk-budget/{profile}` |
| Factor Analysis | Systematic/specific stacked bar | `/analytics/factor-analysis/{profile}` |
| Correlation Regime | `CorrelationRegimePanel.svelte` | `/analytics/correlation-regime/{profile}` — heatmap divergente RdBu, Marchenko-Pastur eigenvalue decomposition, contagion pairs, regime shift badge. Drill-down pairwise via RegimeChart ao clicar célula do heatmap. |
| Screening | `ScreeningRunPanel.svelte` | `POST /screener/run`, `GET /screener/runs`, `GET /screener/results` — trigger de batch screening 3-layer, histórico de runs, tabela de resultados correntes com PASS/FAIL/WATCHLIST badges e layer breakdown expandível. |

### 14.3 Risk Monitor Page (`/risk`)

Real-time SSE connection with:
- Aggregate risk summary (profiles, worst utilization, breaches)
- Market regime (crisis/stress/low_vol/normal with confidence)
- CVaR by profile (utilization, trigger status, sparkline)
- Drift alerts (DTW + behavior change)

### 14.4 Screener Page (`/screener`)

Dois modos via tabs controladas por URL param `?tab=`:

| Tab | Componentes | Endpoints |
|-----|-------------|-----------|
| Catalog (`?tab=catalog`) | `CatalogTable`, `CatalogFacets`, `CatalogDetailPanel` | `GET /screener/catalog`, `GET /screener/catalog/facets`, `GET /screener/catalog/{id}/detail` |
| Screening (`?tab=screening`) | `ScreeningRunPanel` | `POST /screener/run` (202 fire-and-forget), `GET /screener/runs`, `GET /screener/results`, `GET /screener/facets` |

**Screener Managers** (`/screener/managers`):
- Listagem paginada de RIA managers com filtros (text search, AUM, paginação)
- Checkboxes para selecionar até 3 managers → `POST /manager-screener/managers/compare`
- Compare result em ContextPanel side-by-side (AUM, disclosures, funds, holdings overlap)
- Navega para `/screener/managers/{crd}` para detalhe individual (já existia)

### 14.5 Novos componentes de chart (2026-04-01)

Criados neste sprint — todos em `frontends/wealth/src/lib/components/`:

| Componente | Localização | Descrição |
|-----------|------------|-----------|
| `CorrelationHeatmap.svelte` | `charts/` | Heatmap divergente RdBu 7-stop. Paleta via `visualMap`, click handler via `echarts.getInstanceByDom()`, dark mode neutral via `getComputedStyle`. `$state.raw()` para dados. |
| `EigenvalueChart.svelte` | `charts/` | Barras Marchenko-Pastur: azul (signal) / cinza (noise). `markLine` dashed no threshold. Labels λ1, λ2, ... |
| `CorrelationRegimePanel.svelte` | `entity-analytics/` | Orquestrador: badge de regime shift, 4 KPI MetricCards, contagion pairs clicáveis, heatmap, eigenvalue chart, lazy-fetch de pair drill-down. |
| `ActiveSharePanel.svelte` | `entity-analytics/` | 3 estados: empty (sem benchmark), erro (sem N-PORT data), dados (hero metric + classification badge). Lazy-load de instruments para selector. |
| `ScreeningRunPanel.svelte` | `screener/` | 3 sub-seções: trigger dialog (POST 202 + toast), run history table, resultados correntes com expandable layer detail. |

---

## 15. Pre-Computed Metrics (fund_risk_metrics)

The `risk_calc` worker computes and upserts daily into `fund_risk_metrics` (PK: `instrument_id`, `calc_date`):

| Category | Columns |
|----------|---------|
| CVaR (95%) | `cvar_95_1m`, `cvar_95_3m`, `cvar_95_6m`, `cvar_95_12m` |
| VaR (95%) | `var_95_1m`, `var_95_3m`, `var_95_6m`, `var_95_12m` |
| Returns | `return_1m`, `return_3m`, `return_6m`, `return_1y`, `return_3y_ann` |
| Risk | `volatility_1y`, `max_drawdown_1y`, `max_drawdown_3y`, `sharpe_1y`, `sharpe_3y`, `sortino_1y` |
| Relative | `alpha_1y`, `beta_1y`, `information_ratio_1y`, `tracking_error_1y` |
| Scoring | `manager_score` (0-100), `score_components` (JSONB) |
| Momentum | `rsi_14`, `bb_position`, `nav_momentum_score`, `flow_momentum_score`, `blended_momentum_score` |
| Conditional | `volatility_garch` (GARCH 1-step), `cvar_95_conditional` (regime-adjusted) |
| Drift | `dtw_drift_score` (DTW vs benchmark) |
| Peer | `peer_strategy_label`, `peer_sharpe_pctl`, `peer_sortino_pctl`, `peer_return_pctl`, `peer_drawdown_pctl`, `peer_count` |

---

## 16. eVestment Coverage Summary

Audit of 80 institutional metrics from the eVestment Investment Statistics Guide:

| Section | Metrics | Status |
|---------|---------|--------|
| I. Absolute Return | Arithmetic/geometric mean, gain/loss means | Implemented |
| II. Absolute Risk | Gain/loss std dev, downside deviation, semi-deviation | Implemented |
| III. Risk-Adjusted | Sharpe, Sortino, Calmar, Sterling, Omega, Treynor, Jensen | Implemented |
| IV. Proficiency | Up/down percentage ratios, peer percentile rankings | Implemented |
| V. Regression | R-squared, alpha, beta, tracking error | Implemented |
| VI. Tail-Risk-Adjusted | STARR ratio, Rachev ratio | Implemented |
| VII. Tail Risk | Parametric VaR, modified VaR (CF), ETL, ETR, Jarque-Bera | Implemented |
| Risk Budgeting | MCTR, PCTR, MCETL, PCETL, implied returns | Implemented |
| Factor Analysis | PCA decomposition, systematic/specific risk, R-squared | Implemented |
| Monte Carlo | Block bootstrap, percentile distribution, confidence bars | Implemented |
| Peer Group | Strategy-matched rankings, quartile classification | Implemented |
| Active Share | Holdings-based overlap, efficiency | Implemented |

**Out of scope:** Private Equity metrics (IRR, TVPI, PME) — wealth vertical only.

---

## 17. Configuration & Extensibility

All analytics are configurable via `ConfigService` (DB-backed, not YAML at runtime):

| Config Type | Examples |
|-------------|---------|
| CVaR limits | Per-profile thresholds (conservative: -8%, growth: -12%) |
| Scoring weights | Component weights (Sharpe 25%, drawdown 20%, etc.) |
| Screening rules | Eliminatory criteria, mandate constraints |
| Regime thresholds | VIX levels, yield curve inversion triggers |
| Stress dimensions | Per-dimension scoring weights and thresholds |
| Drift tolerances | Maintenance (5%), urgent (10%) |

**Tenant isolation:** All per-org config via `ConfigService.get(vertical, config_type, org_id)`. New tenants work immediately with defaults.