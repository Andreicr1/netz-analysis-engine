# Brainstorm: Credit Engine Analytical Upgrade

**Date:** 2026-03-15
**Status:** Draft
**Scope:** Upgrade Credit AI Engine from organically-evolved state to Wealth-parity + differentiated analytical capabilities

---

## What We're Building

A progressive, 4-phase upgrade of the Credit vertical engine that:

1. **Refactors** the monolithic `ic_quant_engine.py` into modular, universal services in `quant_engine/`
2. **Unifies** FRED/macro regime detection across verticals (Credit inherits WM's multi-signal sophistication)
3. **Upgrades** SEC EDGAR integration from basic CIK/filings to structured financials + insider signals via `edgartools`
4. **Adds** statistical modeling (PD/LGD, covenant breach prediction) that enriches IC memo chapters AND portfolio analytics
5. **Integrates** new data sources (OFR hedge fund monitor, US Fiscal Data, Data Commons demographics, UMAP clustering)

### Why Now

The Credit engine was migrated from Private Credit OS as an organic evolution. When building the Wealth Management `quant_engine/`, we designed it properly from the start — modular services, parameter injection, batch optimization, multi-signal regime detection. The gap between engines is significant:

- **Credit `ic_quant_engine.py`**: ~57KB monolithic, deterministic arithmetic, no statistical modeling
- **Wealth `quant_engine/`**: 10 modular services (~2,500 LOC), CVaR, regime detection, DTW drift, Cornish-Fisher, NSGA-II optimization

The Credit engine needs the same architectural quality PLUS credit-specific analytical depth that differentiates Netz as an institutional platform.

---

## Why This Approach

**Progressive over big-bang** — Each phase delivers independently valuable, testable capabilities. No phase depends on another to be useful.

**Universal core + vertical specialization** — Follows the existing two-layer architecture (`quant_engine/` universal + `vertical_engines/credit/` domain-specific). Credit-specific logic (rate decomposition, covenant quant, fee stacking) stays in the vertical. Universal logic (sensitivity grids, scenario runners, regime detection, backtesting) goes to `quant_engine/`.

**Data source diversity** — Institutional credit analysis requires multiple data layers: macro (FRED), public filings (EDGAR), counterparty risk (OFR), fiscal stress (Treasury), demographics (Data Commons), and portfolio segmentation (UMAP). Each layer independently enriches the IC memo and portfolio monitoring.

---

## Key Decisions

### 1. Quant Architecture: Extract to `quant_engine/` universal

**Decision:** Move truly universal quantitative functions from `ic_quant_engine.py` to `quant_engine/` services. Keep credit-specific logic in `vertical_engines/credit/`.

**What moves to `quant_engine/`:**
- `sensitivity_service.py` — 2D/3D sensitivity grid generation (default_rate × recovery_rate × rate_shock)
- `scenario_service.py` — Multi-scenario runner (base/downside/severe) with configurable multipliers
- `stress_test_service.py` — Stress severity scoring, macro-calibrated scenario parameters
- `backtest_service.py` — Already exists for WM; extend with credit-specific validation (PD/LGD model backtest)

**What stays in `vertical_engines/credit/`:**
- Rate decomposition (coupon, spread, floor, base rate, fee stack, PIK)
- Covenant quantification (DSCR, ICR, leverage, LTV thresholds)
- Duration/maturity bucketing (credit-specific tenor semantics)
- Risk-adjusted return haircut model (credit, liquidity, refinancing risks)
- Liquidity quant hooks (notice period, gate, lockup, suspension)

**Why:** Rate decomposition and covenant logic are pure credit domain — no other vertical needs `coupon + spread_bps + floor_bps`. But sensitivity grids and scenario runners are universal patterns that WM could also use.

### 2. FRED/Macro: Regime Service Becomes Universal

**Decision:** Promote `regime_service.py` from WM-specific to `quant_engine/` universal. Credit vertical adds credit-specific FRED series as overlay.

**Universal regime detection (already in WM):**
- VIX (VIXCLS): risk sentiment
- Yield curve (10Y-2Y): recession signal
- CPI YoY: inflation regime
- Sahm Rule: recession confirmation
- Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON
- Staleness awareness (3 business days daily, 45 days monthly)

**Credit overlay series (from current `market_data_engine.py`):**
- HY spreads (BAMLH0A0HYM2): credit cycle signal
- All-loan delinquency (DRALACBN): credit quality deterioration
- Mortgage delinquency (DRSFRMACBS): real estate stress
- Case-Shiller regional: collateral value stress
- Credit card delinquency (TERMCBCCALLNS): consumer stress proxy
- Bank lending (BOGZ1L31109000Q): liquidity conditions

**Architecture:** `regime_service.py` returns base regime. `market_data_engine.py` consumes regime + adds credit-specific stress overlay. Both feed into IC memo chapters (Ch2 Macro, Ch9 Downside).

### 3. EDGAR: Upgrade to edgartools

**Decision:** Replace `ic_edgar_engine.py` (basic CIK + filings) with `edgartools`-powered service. Scope: structured financials + insider trading signals.

**New capabilities:**
- **Structured financials:** Income statement, balance sheet, cash flow — multi-period (3-5 years) with automatic ratio calculation
- **Insider trading (Form 4):** Early warning signals — insider selling patterns before credit events
- **CIK resolution:** edgartools has built-in fuzzy matching (better than current offline index approach)

**Not in scope (future):**
- 13F institutional holdings (useful but lower priority for credit)
- 8-K event monitoring (real-time alerts would need worker infrastructure)

**IC memo impact:** Enriches Ch4 (Sponsor), Ch10 (Covenants/Financial Metrics), Ch12 (Peers) with actual public financials instead of extracted-from-PDF approximations.

### 4. Statistical Modeling: Dual-Use (Deal + Portfolio)

**Decision:** Implement statsmodels-based models for both deal-level IC memo enrichment AND portfolio-level analytics.

**Deal-level (IC memo enrichment):**
- **PD estimation:** Logistic regression on financial ratios → probability of default with confidence intervals
- **LGD modeling:** Beta regression on collateral coverage, seniority, jurisdiction → loss given default
- **Covenant breach prediction:** Time-series analysis of DSCR/ICR trends → probability of breach in N months
- **Feeds into:** Ch8 (Returns — calibrated default/recovery), Ch9 (Downside — statistical confidence on stress scenarios), Ch11 (Risks — quantified probability vs. current qualitative assessment)

**Portfolio-level analytics:**
- **Default correlation:** Pairwise and sectoral default correlation across portfolio
- **Vintage analysis:** Cohort performance regression by origination year
- **Sector concentration risk:** Factor regression identifying sector-specific risk drivers
- **Trend decomposition:** ARIMA/SARIMAX on portfolio-level metrics (NAV, MOIC, IRR)

**Diagnostics:** Full statsmodels diagnostic suite — heteroskedasticity tests, VIF for multicollinearity, residual normality, influence/outlier detection. Publication-quality output for investor reports.

### 5. New Data Sources: Parallel Implementation

**Decision:** All four new data sources implemented as independent ingestion workers in the same phase. They're independent — no cross-dependencies.

**OFR Hedge Fund Monitor:**
- Counterparty risk monitoring: hedge fund leverage ratios, borrowing patterns
- Systemic risk indicators: concentration, stress test results
- **IC memo impact:** Ch4 (Sponsor — if hedge fund counterparty), Ch11 (Risks — systemic exposure)

**US Fiscal Data (Treasury API):**
- National debt metrics, Treasury auction results, interest expense
- Exchange rates for multi-currency funds
- **IC memo impact:** Ch2 (Macro — fiscal stress context), Ch9 (Downside — sovereign risk scenarios)

**Data Commons:**
- Demographics by geography: population, income, unemployment, age distribution
- **IC memo impact:** Ch2 (Macro — regional economic context for borrower's geography)

**UMAP (dimensionality reduction):**
- Portfolio segmentation: cluster borrowers by multi-factor profile
- Anomaly detection: identify outlier credit profiles requiring deeper review
- Visualization: 2D/3D portfolio maps for investor presentations
- **IC memo impact:** Ch12 (Peers — visual peer positioning)

### 6. Credit Backtesting

**Decision:** Add backtesting adapted for credit context. Not walk-forward NAV (WM pattern) but PD/LGD model validation against historical defaults.

**Approach:**
- Extend existing `backtest_service.py` or create `credit_backtest_service.py` in `quant_engine/`
- Cross-validation of PD model on historical deal outcomes (default/no-default)
- LGD model validation against realized recovery rates
- Vintage cohort backtesting (origination year → performance trajectory)
- **Metrics:** AUC-ROC for PD, MAE for LGD, Brier score for calibration

---

## Phase Roadmap

### Phase A: Quant Architecture Refactor + Regime Unification

**Goal:** Architectural parity with WM engine quality.

**Deliverables:**
1. Extract `sensitivity_service.py` to `quant_engine/` (2D/3D grid generation)
2. Extract `scenario_service.py` to `quant_engine/` (configurable multi-scenario runner)
3. Promote `regime_service.py` to universal (move from WM-specific to `quant_engine/`)
4. Refactor `market_data_engine.py` to consume universal regime + add credit overlay
5. Add `credit_backtest_service.py` to `quant_engine/` (PD/LGD validation)
6. Refactor `ic_quant_engine.py` to delegate to universal services (keep credit-specific logic in-place)
7. Ensure all extracted services follow parameter-injection pattern (no YAML, no @lru_cache)

**Validation:** All existing Deep Review tests pass unchanged. New unit tests for extracted services.

### Phase B: EDGAR Upgrade (edgartools)

**Goal:** Structured public company data for credit analysis.

**Deliverables:**
1. Replace `ic_edgar_engine.py` with edgartools-powered `edgar_service.py`
2. Structured financials extraction (income/balance/CF, 3-5 year history)
3. Insider trading signal detection (Form 4 selling patterns)
4. Financial ratio auto-calculation from structured data
5. Update IC memo chapters (Ch4, Ch10, Ch12) to consume structured EDGAR data
6. Rate-limit compliance maintained (SEC 10 req/s)

**Validation:** Side-by-side comparison: old vs. new EDGAR output for 5 test companies.

### Phase C: Statistical Modeling (statsmodels)

**Goal:** Quantified risk metrics with statistical rigor.

**Deliverables:**
1. PD estimation service (logistic regression on financial ratios)
2. LGD modeling service (beta regression on collateral/seniority)
3. Covenant breach prediction (time-series trend analysis)
4. Portfolio-level regression analytics (default correlation, vintage analysis)
5. IC memo chapter enrichment (Ch8, Ch9, Ch11 with confidence intervals)
6. Full diagnostic suite (heteroskedasticity, VIF, normality, influence)
7. Credit backtesting integration (validate models against historical data)

**Validation:** Model diagnostics pass all assumption checks. Backtest AUC-ROC > 0.7.

### Phase D: New Data Sources

**Goal:** Multi-dimensional data enrichment for credit analysis.

**Deliverables:**
1. OFR hedge fund monitor ingestion worker
2. US Fiscal Data ingestion worker
3. Data Commons demographic data worker
4. UMAP clustering service for portfolio segmentation
5. IC memo chapter enrichment (Ch2, Ch4, Ch11, Ch12)
6. Portfolio visualization (2D/3D cluster maps)

**Validation:** Each worker independently produces valid data. IC memo quality improves measurably.

---

## Resolved Questions

1. **Where does credit-specific quant logic live?** → Stays in `vertical_engines/credit/`. Only universal functions extracted to `quant_engine/`.
2. **How to handle FRED unification?** → Regime service becomes universal. Credit adds overlay series.
3. **EDGAR scope?** → Structured financials + insider trading. 13F and 8-K deferred.
4. **Statsmodels primary use?** → Both deal-level (IC memo) and portfolio-level (regression analytics).
5. **Data source priority?** → All in same phase (parallel independent workers).
6. **Backtesting for credit?** → Yes, adapted: PD/LGD model validation, not NAV walk-forward.

## Open Questions

None — all questions resolved.

## Additionally Resolved Questions

7. **Training data for PD/LGD models:** → Hybrid bootstrapping. Start with public defaults from EDGAR + FRED macro signals. Calibrate with internal deal outcomes as volume grows. No licensing cost. Architect the service to accept any data source.
8. **UMAP visualization delivery:** → Frontend interactive. Cluster maps served as interactive dashboard visualizations (zoom, hover, filter by cluster). Not static PDF charts.
9. **OFR data freshness:** → OFR quarterly + real-time supplementary signals. Add CDS spreads (daily) + news sentiment for early detection of counterparty stress. OFR provides structural baseline, real-time signals provide early warning.
