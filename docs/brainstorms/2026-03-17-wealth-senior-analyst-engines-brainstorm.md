---
date: 2026-03-17
topic: wealth-senior-analyst-engines
---

# Wealth Senior Analyst Engines — Brainstorm

## Context

The screener suite (Sprints 1-5) automates junior analyst work: filtering, ranking, watchlist alerts, fee analysis, regime detection. What's missing is the **diagnostic layer** — the work senior analysts and IC committees actually spend time on: understanding *why* performance happened, detecting behavioral changes, and assessing portfolio-level risk dynamics.

## What Already Exists (Keep)

| Capability | Engine | Status |
|---|---|---|
| 3-layer screening | `screener/service.py` | Complete |
| Peer ranking with percentiles | `peer_group/service.py` | Complete |
| Watchlist with transitions | `watchlist/service.py` | Complete |
| Fee drag analysis | `fee_drag/service.py` | Complete |
| Regime detection + CVaR | `regime_service.py` + `cvar_service.py` | Complete |
| Portfolio drift (block weights) | `drift_service.py` | Complete |
| DTW drift (fund vs benchmark) | `drift_monitor.py` + `FundRiskMetrics.dtw_drift_score` | Complete |
| Brinson-Fachler attribution | `attribution_service.py` | Code complete, **blocked on benchmark data** |

## Five New Engines Evaluated

### 1. Attribution Analysis (highest IC impact, data-blocked)

**Gap:** `attribution_service.py` has full Brinson-Fachler + Carino multi-period linking. Returns empty when `benchmark_weights is None or benchmark_returns is None`. The blocker is **data, not code**.

**Decision:** Unblock via `benchmark_data_ingestor.py`:
- `allocation_blocks.benchmark_ticker` already exists
- Ingestor populates `NavTimeseries` with benchmark returns via yfinance
- ~80 lines. Zero changes to attribution engine.
- Attribution starts working immediately at block level.

**Factor attribution (Fama-French)** is a separate future engine — complementary to Brinson, not a replacement. Data sources: NEFIN (Brazil factors), Kenneth French Data Library (global). Similar to FRED integration pattern.

### 2. Strategy Drift Detection (implementable now)

**What it answers:** "Did this fund change its behavior vs. its own history?" — a third question distinct from:
- `drift_service.py` = portfolio weights vs strategic/tactical targets
- `drift_monitor.py` = fund vs benchmark via DTW

**Location:** `vertical_engines/wealth/monitoring/strategy_drift_detector.py` (alongside `drift_monitor.py`).

**Approach:** z-score comparison of FundRiskMetrics across time windows.
- Compare 90d rolling metrics vs 360d baseline
- Metrics: volatility, max_drawdown, sharpe, sortino, alpha, beta, tracking_error
- If N metrics exceed z-score threshold → "behavior change detected"
- No LLM, no NLP, no holdings data — purely quantitative

**Why z-score, not KS-test:** FundRiskMetrics stores scalar aggregates (sharpe_1y = 0.82), not return distributions. z-score gives auditable answers: "volatility 2.3 std above historical mean". KS-test reserved for Correlation Monitor (NavTimeseries return vectors).

**Data dependency:** Need multiple `calc_date` entries per instrument in `fund_risk_metrics`. Diagnostic query required:
```sql
SELECT instrument_id, COUNT(DISTINCT calc_date) AS data_points,
       MIN(calc_date) AS oldest, MAX(calc_date) AS latest
FROM fund_risk_metrics
GROUP BY instrument_id
HAVING COUNT(DISTINCT calc_date) >= 90
ORDER BY data_points ASC;
```
If daily/weekly calc_dates exist → works directly. If single snapshot → fall back to NavTimeseries for rolling recalculation.

### 3. Correlation Regime Monitor (competitive differentiator)

**What it answers:** "Which instruments in this portfolio lost diversification during stress?"

**Scope decision:** Correlation only within portfolio instruments (15-40 typically), NOT full universe (would be O(n^2) with 200+ instruments).

**Approach:**
1. Rolling correlation matrix (60d window) from `NavTimeseries.return_1d`
2. Eigenvalue analysis — first eigenvalue dominance = concentration
3. Alert: "diversification ratio dropped below threshold"
4. Compare correlation matrix in current regime vs historical normal → "correlation contagion score"

**Data:** Already available in NavTimeseries. Pure numpy.

### 4. Liquidity Stress Testing (simplified model)

**What it answers:** "If we need to liquidate X% in Y days, which instruments are bottlenecks?"

**Simplified model using available data:**
- `attributes.redemption_days` → liquidation timeline
- `aum_usd` + portfolio weight → concentration risk (our position as % of fund AUM)
- Score instruments by liquidation difficulty

**NOT modeling (data unavailable):** bid-ask impact by position size, redemption gates, lockup periods. Can be added incrementally when data becomes available.

### 5. Regime Sensitivity Score (not "Conviction Score")

**Renamed deliberately:** "Conviction" implies prediction → liability. "Regime Sensitivity" is descriptive and auditable.

**Approach:** Conditional beta per instrument by regime.
- Measure how each instrument performed in RISK_OFF vs RISK_ON historical periods
- Given current regime, rank instruments by exposure
- Not prediction — "given where we are, who's most exposed"

**Deferred:** Requires long return history per regime. Most complex to calibrate correctly. Sprint 3+ territory.

## What to Simplify/Defer (Not Invest Further)

- **Mandate fit ESG + domicile** — risk_bucket + liquidity + currency cover 95% of Brazilian WM use cases. Keep existing, don't expand.
- **performance_fee_pct flat deduction** — documented limitation. Hurdle rate + HWM modeling is future sprint.

## Priority (Ordered by Data Availability + Impact)

| # | Engine | Effort | Data Available? | Impact |
|---|---|---|---|---|
| 1 | Benchmark Data Ingestor | ~80 lines | N/A (creates data) | Unblocks Attribution |
| 2 | Strategy Drift Detection | ~1 sprint | Yes (FundRiskMetrics, pending depth check) | High — fraud/mandate change |
| 3 | Attribution Analysis | Zero (already done) | Yes, after ingestor | Highest — IC decision support |
| 4 | Correlation Regime Monitor | ~1 sprint | Yes (NavTimeseries) | High — competitive differentiator |
| 5 | Liquidity Stress (simplified) | < 1 sprint | Partial | Medium — committee question |
| 6 | Regime Sensitivity Score | ~2 sprints | Partial (needs history) | High but risky to miscalibrate |

## Immediate Actions

1. Run diagnostic query on `fund_risk_metrics` to confirm calc_date depth
2. Build `benchmark_data_ingestor.py` (yfinance → NavTimeseries via benchmark_ticker)
3. Build `strategy_drift_detector.py` in `monitoring/`
4. Attribution starts working automatically after step 2

## Next Steps

→ `/ce:plan` for Sprint 6 (engines #1-3 above: ingestor + drift detector + attribution activation)
