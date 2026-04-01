---
title: "feat: eVestment Analytics & Risk Completeness"
type: feat
status: active
date: 2026-04-01
origin: docs/reference/evestment-reference.md
---

# eVestment Analytics & Risk Completeness

## Overview

Close the gap between our current analytics/risk infrastructure and the eVestment Investment Statistics Guide. An audit of 80 institutional metrics found: **11 OK (14%), 16 backend-only (20%), 4 partial (5%), 48 missing (60%)**. The single largest frontend gap is that `GET /analytics/entity/{entity_id}` already returns 5 metric groups (~20 metrics) but NO frontend page consumes this data.

This plan is structured in **5 phases**, each independently deployable and testable:

| Phase | Scope | Backend | Frontend | New Metrics |
|-------|-------|---------|----------|-------------|
| 1 | Entity Analytics Page | 0 changes | New `/analytics/[entityId]` page | 0 (wire existing) |
| 2 | P1 Metric Expansion | 3 new quant services + schema extensions | Extend entity page | +17 metrics |
| 3 | Tail Risk & Distribution | 2 new quant services + schema extensions | New Tail Risk panel | +7 metrics |
| 4 | Risk Budgeting & Factor Analysis | 2 new quant services + new routes | New Risk Budget panel | +8 metrics |
| 5 | Monte Carlo, Peer Group, Active Share | 3 new quant services + migration | New panels + /risk enhancements | +10 metrics |

**Out of scope:** Private Equity metrics (IRR, TVPI, PME) — wealth vertical only. Peer Share / Peer Share Efficiency — requires peer universe construction.

---

## Phase 1: Entity Analytics Frontend Page (P0 — Zero Backend Work)

**Goal:** Surface the existing 5-group `EntityAnalyticsResponse` in a dedicated page. This instantly makes ~20 backend-computed metrics visible to users.

### 1.1 TypeScript Types

**File:** `frontends/wealth/src/lib/types/entity-analytics.ts` (NEW)

```typescript
export interface RiskStatistics {
  annualized_return: number | null;
  annualized_volatility: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  max_drawdown: number | null;
  alpha: number | null;
  beta: number | null;
  tracking_error: number | null;
  information_ratio: number | null;
  n_observations: number;
}

export interface DrawdownPeriod {
  start_date: string;
  trough_date: string;
  end_date: string | null;
  depth: number;
  duration_days: number;
  recovery_days: number | null;
}

export interface DrawdownAnalysis {
  dates: string[];
  values: number[];
  max_drawdown: number | null;
  current_drawdown: number | null;
  longest_duration_days: number | null;
  avg_recovery_days: number | null;
  worst_periods: DrawdownPeriod[];
}

export interface CaptureRatios {
  up_capture: number | null;
  down_capture: number | null;
  up_number_ratio: number | null;
  down_number_ratio: number | null;
  up_periods: number;
  down_periods: number;
  benchmark_source: string;
  benchmark_label: string;
}

export interface RollingSeries {
  window_label: string;
  dates: string[];
  values: number[];
}

export interface RollingReturns {
  series: RollingSeries[];
}

export interface ReturnDistribution {
  bin_edges: number[];
  bin_counts: number[];
  mean: number | null;
  std: number | null;
  skewness: number | null;
  kurtosis: number | null;
  var_95: number | null;
  cvar_95: number | null;
}

export interface EntityAnalyticsResponse {
  entity_id: string;
  entity_type: "instrument" | "model_portfolio";
  entity_name: string;
  as_of_date: string;
  window: string;
  risk_statistics: RiskStatistics;
  drawdown: DrawdownAnalysis;
  capture: CaptureRatios;
  rolling_returns: RollingReturns;
  distribution: ReturnDistribution;
}
```

### 1.2 Page Route

**File:** `frontends/wealth/src/routes/(app)/analytics/[entityId]/+page.server.ts` (NEW)

- Fetch `GET /analytics/entity/{entityId}?window={window}&benchmark_id={benchmarkId}`
- Accept `window` query param (default `1y`, options: `3m|6m|1y|3y|5y`)
- Accept optional `benchmark_id` query param
- Return typed `EntityAnalyticsResponse` to page

**File:** `frontends/wealth/src/routes/(app)/analytics/[entityId]/+page.svelte` (NEW)

Layout — 5 sections matching the 5 metric groups:

```
┌─────────────────────────────────────────────────────────┐
│ PageHeader: Entity Name | Window Selector (3m-5y)       │
├────────────┬────────────┬────────────┬──────────────────┤
│ Return     │ Volatility │ Sharpe     │ Sortino          │  ← MetricCard row
│ Calmar     │ Alpha      │ Beta       │ Info Ratio       │
│ Track Error│ Max DD     │ N obs      │                  │
├────────────┴────────────┴────────────┴──────────────────┤
│ Drawdown Chart (ECharts area chart, underwater style)   │
│ + Worst Periods table below                             │
├────────────────────────┬────────────────────────────────┤
│ Capture Ratios Panel   │ Rolling Returns Chart          │
│ (4 metrics + benchmark)│ (multi-series line chart)      │
├────────────────────────┴────────────────────────────────┤
│ Return Distribution (histogram + moments + VaR/CVaR)    │
└─────────────────────────────────────────────────────────┘
```

### 1.3 Components (NEW)

| Component | Path | Purpose |
|-----------|------|---------|
| `RiskStatisticsGrid.svelte` | `components/analytics/entity/` | 10-metric card grid (MetricCard from @investintell/ui) |
| `DrawdownChart.svelte` | `components/analytics/entity/` | ECharts area chart (underwater) + worst periods table |
| `CaptureRatiosPanel.svelte` | `components/analytics/entity/` | 4 capture metrics + benchmark label |
| `RollingReturnsChart.svelte` | `components/analytics/entity/` | Multi-series line chart (1M/3M/6M/1Y overlaid) |
| `ReturnDistributionChart.svelte` | `components/analytics/entity/` | Histogram + normal overlay + moments sidebar |

### 1.4 Navigation Entry Point

Add link to entity analytics from:
- Screener `CatalogDetailPanel.svelte` → "Analytics" action button → `/analytics/{instrument_id}`
- Model Portfolio detail page → "Analytics" tab → `/analytics/{portfolio_id}`

### 1.5 Acceptance Criteria

- [ ] `/analytics/{entityId}` renders all 5 groups from backend
- [ ] Window selector (3m/6m/1y/3y/5y) re-fetches data
- [ ] All numbers use `@investintell/ui` formatters (formatPercent, formatNumber, formatBps)
- [ ] All charts use `ChartContainer` wrapper
- [ ] Graceful empty states when metrics are null
- [ ] Works for both `instrument` and `model_portfolio` entity types
- [ ] Navigable from screener detail panel and model portfolio page

---

## Phase 2: P1 Metric Expansion (Pure Math — No External Data)

**Goal:** Add 17 missing eVestment metrics that are pure math from existing return series. No new data sources needed.

### 2.1 New Quant Service: `return_statistics_service.py`

**File:** `backend/quant_engine/return_statistics_service.py` (NEW)

Computes all absolute return/risk measures from return array:

```python
@dataclass(frozen=True, slots=True)
class ReturnStatisticsResult:
    # Absolute Return Measures
    arithmetic_mean_monthly: float | None = None
    geometric_mean_monthly: float | None = None
    avg_monthly_gain: float | None = None
    avg_monthly_loss: float | None = None
    gain_loss_ratio: float | None = None

    # Absolute Risk Measures
    gain_std_dev: float | None = None
    loss_std_dev: float | None = None
    downside_deviation: float | None = None  # MAR-based
    semi_deviation: float | None = None

    # Risk-Adjusted
    sterling_ratio: float | None = None
    omega_ratio: float | None = None  # MAR-based
    treynor_ratio: float | None = None  # requires beta
    jensen_alpha: float | None = None  # requires alpha, beta, Rm

    # Proficiency Ratios (relative)
    up_percentage_ratio: float | None = None
    down_percentage_ratio: float | None = None

    # Regression
    r_squared: float | None = None


def compute_return_statistics(
    daily_returns: np.ndarray,
    benchmark_returns: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    mar: float = 0.0,
    config: dict | None = None,
) -> ReturnStatisticsResult:
    """Compute eVestment Sections I-V return statistics."""
    ...
```

**Formulas (from eVestment Appendix I):**

| Metric | Formula | Notes |
|--------|---------|-------|
| Gain Mean | `mean(R[R >= 0])` | Only positive-return periods |
| Loss Mean | `mean(R[R < 0])` | Only negative-return periods |
| Gain/Loss Ratio | `abs(gain_mean / loss_mean)` | |
| Gain Std Dev | `std(R[R >= 0])` | Upside volatility |
| Loss Std Dev | `std(R[R < 0])` | Downside volatility |
| Downside Deviation | `sqrt(mean(min(R - MAR, 0)²))` | N denominator, not N-1 |
| Semi Deviation | `sqrt(mean(min(R - mean(R), 0)²))` | Uses mean as threshold |
| Sterling Ratio | `ann_return / abs(avg_yearly_max_dd - 10%)` | 3-year, avg of annual max DDs |
| Omega Ratio | `sum(max(R - MAR, 0)) / sum(abs(min(R - MAR, 0)))` | Threshold-dependent |
| Treynor Ratio | `(ann_return - Rf) / beta` | Requires beta |
| Jensen Alpha | `mean(R) - Rf - beta * (mean(Rm) - Rf)` | Requires alpha, beta, Rm |
| Up Pct Ratio | `count(R > Rm when Rm >= 0) / count(Rm >= 0)` | Proficiency ratio |
| Down Pct Ratio | `count(R > Rm when Rm < 0) / count(Rm < 0)` | Proficiency ratio |
| R² | `correlation(R, Rm)²` | Coefficient of determination |

### 2.2 New Quant Service: `tail_var_service.py`

**File:** `backend/quant_engine/tail_var_service.py` (NEW)

Computes parametric and modified VaR/ETL using Cornish-Fisher:

```python
@dataclass(frozen=True, slots=True)
class TailRiskResult:
    # Parametric VaR (Normal distribution)
    var_parametric_90: float | None = None
    var_parametric_95: float | None = None
    var_parametric_99: float | None = None

    # Modified VaR (Cornish-Fisher adjustment)
    var_modified_95: float | None = None
    var_modified_99: float | None = None

    # ETL / CVaR
    etl_95: float | None = None       # Expected Tail Loss (same as CVaR)
    etl_modified_95: float | None = None  # Modified ETL using mVaR

    # ETR (right tail)
    etr_95: float | None = None       # Expected Tail Return

    # Normality tests
    jarque_bera_stat: float | None = None
    jarque_bera_pvalue: float | None = None
    is_normal: bool | None = None     # p > 0.05


def compute_tail_risk(
    daily_returns: np.ndarray,
    confidence_levels: list[float] | None = None,
) -> TailRiskResult:
    """Compute eVestment Section VII tail risk measures."""
    ...
```

**Formulas:**

| Metric | Formula |
|--------|---------|
| Parametric VaR | `E(R) + Z_c * σ` where Z_c is normal quantile |
| Modified VaR | Cornish-Fisher: `VaR + (z² - 1)/6 * S + (z³ - 3z)/24 * K - (2z³ - 5z)/36 * S²` |
| ETL | `mean(R[R <= VaR])` |
| Modified ETL | `mean(R[R <= mVaR])` |
| ETR | `mean(R[R >= upper_quantile])` |
| Jarque-Bera | `n * [S²/6 + (K-3)²/24]` |

### 2.3 Extend Entity Analytics Schema

**File:** `backend/app/domains/wealth/schemas/entity_analytics.py` (MODIFY)

Add two new groups to `EntityAnalyticsResponse`:

```python
# ── 6. Return Statistics (eVestment Sections I-V) ─────────────────────

class ReturnStatistics(BaseModel):
    arithmetic_mean_monthly: float | None = None
    geometric_mean_monthly: float | None = None
    avg_monthly_gain: float | None = None
    avg_monthly_loss: float | None = None
    gain_loss_ratio: float | None = None
    gain_std_dev: float | None = None
    loss_std_dev: float | None = None
    downside_deviation: float | None = None
    semi_deviation: float | None = None
    sterling_ratio: float | None = None
    omega_ratio: float | None = None
    treynor_ratio: float | None = None
    jensen_alpha: float | None = None
    up_percentage_ratio: float | None = None
    down_percentage_ratio: float | None = None
    r_squared: float | None = None


# ── 7. Tail Risk (eVestment Section VII) ──────────────────────────────

class TailRiskMetrics(BaseModel):
    var_parametric_90: float | None = None
    var_parametric_95: float | None = None
    var_parametric_99: float | None = None
    var_modified_95: float | None = None
    var_modified_99: float | None = None
    etl_95: float | None = None
    etl_modified_95: float | None = None
    etr_95: float | None = None
    jarque_bera_stat: float | None = None
    jarque_bera_pvalue: float | None = None
    is_normal: bool | None = None


# ── Updated Response ──────────────────────────────────────────────────

class EntityAnalyticsResponse(BaseModel):
    # ... existing fields ...
    return_statistics: ReturnStatistics | None = None      # Group 6
    tail_risk: TailRiskMetrics | None = None               # Group 7
```

**Backward compatibility:** New groups default to `None` — existing consumers unaffected.

### 2.4 Wire in Entity Analytics Route

**File:** `backend/app/domains/wealth/routes/entity_analytics.py` (MODIFY)

After existing Group 5 (distribution) computation, add:

```python
from quant_engine.return_statistics_service import compute_return_statistics
from quant_engine.tail_var_service import compute_tail_risk

# ── 6. Return Statistics ─────────────────────────────────────────
monthly_rets = _monthly_returns_from_daily(daily_returns, nav_dates)
return_stats = compute_return_statistics(
    daily_returns=daily_returns,
    benchmark_returns=bench_returns,
    risk_free_rate=risk_free_daily * 252,
    mar=0.0,
)

# ── 7. Tail Risk ─────────────────────────────────────────────────
tail = compute_tail_risk(daily_returns=daily_returns)
```

### 2.5 Extend Frontend Entity Page

Add two new sections below the existing 5:

```
┌─────────────────────────────────────────────────────────┐
│ [existing 5 sections from Phase 1]                      │
├────────────────────────┬────────────────────────────────┤
│ Return Statistics      │ Relative Metrics               │
│ (Gain/Loss, DD dev,   │ (Treynor, Jensen, R²,          │
│  Semi dev, Omega,     │  Proficiency ratios)            │
│  Sterling)            │                                  │
├────────────────────────┴────────────────────────────────┤
│ Tail Risk Panel                                          │
│ VaR comparison (Parametric vs Modified vs Historical)   │
│ ETL/ETR bar chart | Jarque-Bera normality badge         │
└─────────────────────────────────────────────────────────┘
```

**New Components:**

| Component | Purpose |
|-----------|---------|
| `ReturnStatisticsPanel.svelte` | 16-metric grid: gain/loss means, deviations, ratios |
| `TailRiskPanel.svelte` | VaR comparison chart + ETL/ETR bars + normality indicator |

### 2.6 Acceptance Criteria

- [ ] `return_statistics_service.py` passes unit tests for all 16 formulas against eVestment reference values
- [ ] `tail_var_service.py` passes unit tests for parametric VaR, modified VaR (CF), ETL, ETR, Jarque-Bera
- [ ] Entity analytics endpoint returns 7 groups (backward compatible — Groups 6-7 nullable)
- [ ] Frontend renders Return Statistics and Tail Risk panels
- [ ] Omega Ratio uses MAR=0% default (configurable via query param)
- [ ] Modified VaR matches Cornish-Fisher formula from eVestment p.71

---

## Phase 3: Risk-Adjusted Tail Metrics (STARR, Rachev)

**Goal:** Add advanced tail-risk-adjusted performance metrics from eVestment Section VI.

### 3.1 Extend `tail_var_service.py`

Add to existing service:

```python
@dataclass(frozen=True, slots=True)
class TailRiskAdjustedResult:
    starr_ratio: float | None = None      # E(R - Rf) / ETL
    rachev_ratio: float | None = None     # ETR / ETL
```

**Formulas:**

| Metric | Formula | eVestment Page |
|--------|---------|----------------|
| STARR | `(E(R) - Rf) / ETL_95` | p.72 |
| Rachev | `ETR_α / ETL_β` where α=β=5% | p.72 |

### 3.2 Extend Entity Analytics Schema

Add `starr_ratio` and `rachev_ratio` to `TailRiskMetrics` model.

### 3.3 Extend Frontend Tail Risk Panel

Add STARR and Rachev to the tail risk visualization as additional MetricCards.

### 3.4 Acceptance Criteria

- [ ] STARR computed as excess return / ETL
- [ ] Rachev computed as ETR / ETL at matching confidence levels
- [ ] Both display in Tail Risk panel with eVestment-consistent formatting

---

## Phase 4: Risk Budgeting & Factor Analysis

**Goal:** Implement eVestment's most advanced portfolio analytics — risk budgeting (MCTR, PCTR, implied returns) and factor decomposition.

### 4.1 New Quant Service: `risk_budgeting_service.py`

**File:** `backend/quant_engine/risk_budgeting_service.py` (NEW)

```python
@dataclass(frozen=True, slots=True)
class FundRiskBudget:
    instrument_id: str
    instrument_name: str
    weight_pct: float
    mean_return: float
    implied_return_vol: float | None = None   # via volatility risk measure
    implied_return_etl: float | None = None   # via ETL risk measure
    difference_vol: float | None = None       # mean - implied (vol)
    difference_etl: float | None = None       # mean - implied (etl)
    mctr: float | None = None                 # Marginal Contribution to Risk (σ)
    mcetl: float | None = None                # Marginal Contribution to ETL
    pctr: float | None = None                 # Percentage Contribution to Risk (σ)
    pcetl: float | None = None                # Percentage Contribution to ETL

@dataclass(frozen=True, slots=True)
class RiskBudgetResult:
    portfolio_volatility: float
    portfolio_etl: float
    portfolio_starr: float | None = None      # STARR optimal reference
    funds: list[FundRiskBudget]


def compute_risk_budget(
    weights: np.ndarray,
    returns_matrix: np.ndarray,     # (n_periods, n_funds)
    fund_ids: list[str],
    fund_names: list[str],
    risk_free_rate: float = 0.04,
    confidence: float = 0.95,
) -> RiskBudgetResult:
    """Compute eVestment risk budgeting metrics.

    MCTR = ∂σ_portfolio / ∂w_i = (Σ @ w)_i / σ_portfolio
    PCTR = w_i * MCTR_i / σ_portfolio  (sums to 100%)
    MCETL = Euler decomposition of portfolio ETL
    Implied Return = STARR_optimal * MCETL_i
    """
    ...
```

**Formulas (eVestment p.43-44):**

| Metric | Formula |
|--------|---------|
| MCTR | `(Σ @ w)_i / σ_p` where Σ is covariance matrix |
| PCTR | `w_i * MCTR_i / σ_p` — sums to 100% |
| MCETL | Euler decomposition: `∂ETL/∂w_i` via finite difference or Tasche method |
| PCETL | `w_i * MCETL_i / ETL_p` — sums to 100% |
| Implied Return (ETL) | `STARR_optimal * MCETL_i` |
| Difference | `mean_return_i - implied_return_i` — positive = increase allocation |

### 4.2 New Route: `POST /analytics/risk-budget/{profile}`

**File:** `backend/app/domains/wealth/routes/analytics.py` (MODIFY — add endpoint)

- Reads current portfolio composition (weights from `allocation_blocks`)
- Fetches returns matrix for all instruments in profile
- Calls `compute_risk_budget()`
- Returns `RiskBudgetResponse` with per-fund breakdown

### 4.3 Extend Factor Analysis Exposure

**File:** `backend/quant_engine/factor_model_service.py` (MODIFY)

Add to existing PCA output:

```python
@dataclass(frozen=True, slots=True)
class FactorContributionResult:
    systematic_risk_pct: float          # % of total variance from factors
    specific_risk_pct: float            # % of total variance idiosyncratic
    factor_contributions: list[dict]    # [{factor_label, pct_contribution}]
    r_squared: float                    # Overall model fit
```

### 4.4 New Route: `GET /analytics/factor-analysis/{profile}`

Returns factor exposures, systematic vs specific risk split, R² per fund, and factor contribution chart data.

### 4.5 Frontend: Risk Budget Panel

**New Components:**

| Component | Purpose |
|-----------|---------|
| `RiskBudgetTable.svelte` | Table: fund, weight, mean, implied, difference, MCTR, PCTR, MCETL, PCETL |
| `RiskBudgetScatter.svelte` | ECharts scatter: Mean Return vs Implied Return with STARR diagonal line |
| `FactorContributionChart.svelte` | Horizontal bar: factor contributions + specific risk (stacked) |

**Page Location:** New tab/section on `/analytics` page (portfolio-level analytics).

### 4.6 Acceptance Criteria

- [ ] MCTR sums verify: `Σ(w_i * MCTR_i) = σ_portfolio`
- [ ] PCTR sums to 100% (±0.01% tolerance)
- [ ] PCETL sums to 100% (±0.01% tolerance)
- [ ] Implied return scatter matches eVestment Figure p.44 (STARR line is diagonal)
- [ ] Factor R² displayed per fund
- [ ] Systematic vs Specific risk stacked bar chart matches eVestment p.46

---

## Phase 5: Monte Carlo, Peer Group, Active Share

**Goal:** Complete the remaining advanced analytics from the eVestment guide.

### 5.1 New Quant Service: `monte_carlo_service.py`

**File:** `backend/quant_engine/monte_carlo_service.py` (NEW)

```python
@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    n_simulations: int
    statistic: str                    # "max_drawdown" | "return" | "sharpe"
    percentiles: dict[str, float]     # {"1st": x, "5th": x, ..., "99th": x}
    mean: float
    median: float
    std: float
    historical_value: float
    confidence_bars: list[dict]       # [{horizon: "1Y", pct_10: x, min_prior: x}]


def run_monte_carlo(
    daily_returns: np.ndarray,
    n_simulations: int = 10_000,
    horizons: list[int] | None = None,  # [252, 756, 1260, 1764, 2520] for 1-10Y
    statistic: str = "max_drawdown",
) -> MonteCarloResult:
    """Bootstrapped Monte Carlo preserving skewness and kurtosis.

    Uses block bootstrap (block_size=21 trading days) to preserve
    autocorrelation structure. Does NOT assume normal distribution.
    """
    ...
```

**eVestment Reference:** Figures 7, 8, 35, 36 — percentile distribution of simulated max drawdown and confidence level bars across horizons.

### 5.2 New Route: `POST /analytics/monte-carlo`

- Accepts `entity_id`, `n_simulations` (default 10,000), `statistic`, `horizons`
- Returns percentile table + confidence bars
- Runs as background job with SSE progress (similar pattern to Pareto optimization)
- Redis cache with 1h TTL (keyed on entity + params hash)

### 5.3 New Quant Service: `peer_group_service.py`

**File:** `backend/quant_engine/peer_group_service.py` (NEW)

```python
@dataclass(frozen=True, slots=True)
class PeerRanking:
    metric_name: str
    value: float | None
    percentile: float             # 0-100 (higher = better)
    quartile: int                 # 1-4
    peer_count: int
    peer_median: float
    peer_p25: float
    peer_p75: float


@dataclass(frozen=True, slots=True)
class PeerGroupResult:
    strategy_label: str
    peer_count: int
    rankings: list[PeerRanking]   # One per metric


def compute_peer_rankings(
    fund_metrics: dict,                        # Fund's metrics dict
    peer_metrics: list[dict],                  # All peer fund metrics
    metrics_to_rank: list[str] | None = None,  # Default: sharpe, sortino, max_dd, return
    higher_is_better: dict[str, bool] | None = None,
) -> PeerGroupResult:
    """Rank fund against strategy-matched peers (eVestment Section IV)."""
    ...
```

**Data source:** `fund_risk_metrics` table joined with `instruments_universe.strategy_label` for peer cohort selection.

### 5.4 New Route: `GET /analytics/peer-group/{entity_id}`

- Resolves fund's `strategy_label` from `instruments_universe` or `sec_manager_funds`
- Queries all funds with matching `strategy_label` from `fund_risk_metrics`
- Computes percentile rank for configurable metric set
- Returns quartile performance + peer comparison

### 5.5 New Quant Service: `active_share_service.py`

**File:** `backend/quant_engine/active_share_service.py` (NEW)

```python
@dataclass(frozen=True, slots=True)
class ActiveShareResult:
    active_share: float               # 0-100
    overlap: float                    # 0-100 (complement of active share for 2 portfolios)
    active_share_efficiency: float | None  # excess_return / active_share
    n_portfolio_positions: int
    n_benchmark_positions: int
    n_common_positions: int


def compute_active_share(
    portfolio_weights: dict[str, float],    # {cusip: weight}
    benchmark_weights: dict[str, float],    # {cusip: weight}
    excess_return: float | None = None,     # For efficiency calc
) -> ActiveShareResult:
    """Active Share = 0.5 * Σ|w_fund,i - w_index,i| (eVestment p.73)."""
    ...
```

**Data source:** Fund holdings from `sec_nport_holdings` (N-PORT quarterly). Benchmark holdings from a reference index (e.g., SPY constituents from 13F or a static benchmark table).

### 5.6 Database Migration

**Migration:** `0071_add_peer_percentile_columns.py`

Add to `fund_risk_metrics`:
```sql
ALTER TABLE fund_risk_metrics
    ADD COLUMN peer_strategy_label TEXT,
    ADD COLUMN peer_sharpe_pctl NUMERIC(5,2),
    ADD COLUMN peer_sortino_pctl NUMERIC(5,2),
    ADD COLUMN peer_return_pctl NUMERIC(5,2),
    ADD COLUMN peer_drawdown_pctl NUMERIC(5,2),
    ADD COLUMN peer_count INTEGER;
```

Pre-compute in `risk_calc` worker daily so peer rankings are instant-read.

### 5.7 Frontend Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `MonteCarloPanel.svelte` | `/analytics/[entityId]` | Percentile distribution table + confidence bar chart |
| `PeerGroupPanel.svelte` | `/analytics/[entityId]` | Quartile box plots (trailing periods) + peer rank table |
| `ActiveSharePanel.svelte` | `/analytics/[entityId]` | Active share metric + overlap + efficiency |
| `MonteCarloSection.svelte` | `/analytics` (portfolio) | Portfolio-level MC simulation with SSE progress |

### 5.8 Enhance Existing /risk Page

Add to the risk page:
- **Peer Group Summary:** Per-profile peer percentile cards (from pre-computed worker data)
- **Monte Carlo Quick View:** 95th percentile max drawdown indicator with "Run Full Simulation" button

### 5.9 Acceptance Criteria

- [ ] Monte Carlo uses block bootstrap (21-day blocks), NOT normal assumption
- [ ] 10,000 simulations complete in < 30s (numpy vectorized)
- [ ] Peer group uses `strategy_label` for cohort — minimum 10 peers or falls back to broader category
- [ ] Peer percentile pre-computed in risk_calc worker (no in-request N+1 queries)
- [ ] Active Share requires N-PORT holdings data — graceful "No holdings data" when unavailable
- [ ] Alembic migration is reversible (downgrade drops columns)

---

## System-Wide Impact

### Interaction Graph

```
User clicks fund in screener
  → navigates to /analytics/[entityId]
    → +page.server.ts fetches GET /analytics/entity/{id}?window=1y
      → entity_analytics.py resolves entity type (polymorphic)
        → nav_reader fetches NAV from nav_timeseries
        → quant_engine services compute 7+ metric groups
      → returns EntityAnalyticsResponse (JSON)
    → Svelte page renders 7+ sections with ECharts

POST /analytics/risk-budget/{profile}
  → reads weights from allocation_blocks
  → fetches returns matrix from nav_timeseries
  → quant_engine.risk_budgeting_service computes MCTR/PCTR/MCETL/PCETL
  → returns RiskBudgetResponse

POST /analytics/monte-carlo
  → enqueues background job (Redis)
  → worker runs block bootstrap simulation
  → SSE streams progress to frontend
  → returns MonteCarloResult
```

### Error Propagation

- All new quant services return `None` for metrics with insufficient data (< 12 data points)
- Entity analytics route wraps each group computation in try/except — individual group failure doesn't kill entire response
- Monte Carlo background job uses standard SSE error pattern (job status = "failed", error message in stream)
- Peer group falls back to broader strategy category if exact `strategy_label` cohort < 10 funds

### State Lifecycle Risks

- **No new tables** in Phases 1-4 (only new columns in Phase 5 migration)
- Phase 5 migration adds nullable columns — no data loss risk
- Monte Carlo cache uses Redis (1h TTL) — stale cache is acceptable (not financial-critical)
- Risk budgeting is stateless computation — no persistence concerns

### API Surface Parity

New endpoints must follow existing patterns:
- `response_model=` on all routes
- `model_validate()` for returns
- `get_db_with_rls` + `get_current_user` dependencies
- Standard error handling (`HTTPException(404)` for entity not found)

---

## Testing Strategy

### Unit Tests (per phase)

| Phase | Test File | Coverage |
|-------|-----------|----------|
| 1 | N/A (frontend only) | Manual + Playwright |
| 2 | `tests/quant_engine/test_return_statistics_service.py` | All 16 formulas vs eVestment reference values |
| 2 | `tests/quant_engine/test_tail_var_service.py` | Parametric VaR, mVaR (CF), ETL, ETR, JB |
| 3 | Extend `test_tail_var_service.py` | STARR, Rachev |
| 4 | `tests/quant_engine/test_risk_budgeting_service.py` | MCTR/PCTR sum invariants, implied return |
| 4 | Extend `tests/quant_engine/test_factor_model_service.py` | R², systematic/specific split |
| 5 | `tests/quant_engine/test_monte_carlo_service.py` | Percentile ordering, bootstrap block size |
| 5 | `tests/quant_engine/test_peer_group_service.py` | Percentile accuracy, quartile assignment |
| 5 | `tests/quant_engine/test_active_share_service.py` | Known portfolio vs index, edge cases |

### Integration Tests

| Phase | Test | What It Validates |
|-------|------|-------------------|
| 2 | `tests/domains/wealth/test_entity_analytics_route.py` | 7-group response, backward compat |
| 4 | `tests/domains/wealth/test_risk_budget_route.py` | PCTR sums to 100%, PCETL sums to 100% |
| 5 | `tests/domains/wealth/test_peer_group_route.py` | Strategy matching, minimum peer threshold |

### Validation Against eVestment Reference

Create a fixture with known return data (e.g., S&P 500 Jan 1975–Jun 2011 monthly returns from eVestment guide) and validate:
- Sharpe, Sortino, Calmar match Table in Figure 19 (p.23)
- VaR/mVaR/ETL match Table in Figure 19 (p.23)
- Omega ratio rankings match Figure 13a/13b (p.17)
- STARR and Rachev match expected tail behavior

---

## File Inventory

### New Files

| File | Phase | Type |
|------|-------|------|
| `backend/quant_engine/return_statistics_service.py` | 2 | Service |
| `backend/quant_engine/tail_var_service.py` | 2 | Service |
| `backend/quant_engine/risk_budgeting_service.py` | 4 | Service |
| `backend/quant_engine/monte_carlo_service.py` | 5 | Service |
| `backend/quant_engine/peer_group_service.py` | 5 | Service |
| `backend/quant_engine/active_share_service.py` | 5 | Service |
| `frontends/wealth/src/lib/types/entity-analytics.ts` | 1 | Types |
| `frontends/wealth/src/routes/(app)/analytics/[entityId]/+page.svelte` | 1 | Page |
| `frontends/wealth/src/routes/(app)/analytics/[entityId]/+page.server.ts` | 1 | Server |
| `frontends/wealth/src/lib/components/analytics/entity/RiskStatisticsGrid.svelte` | 1 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/DrawdownChart.svelte` | 1 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/CaptureRatiosPanel.svelte` | 1 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/RollingReturnsChart.svelte` | 1 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/ReturnDistributionChart.svelte` | 1 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/ReturnStatisticsPanel.svelte` | 2 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/TailRiskPanel.svelte` | 2 | Component |
| `frontends/wealth/src/lib/components/analytics/RiskBudgetTable.svelte` | 4 | Component |
| `frontends/wealth/src/lib/components/analytics/RiskBudgetScatter.svelte` | 4 | Component |
| `frontends/wealth/src/lib/components/analytics/FactorContributionChart.svelte` | 4 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/MonteCarloPanel.svelte` | 5 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/PeerGroupPanel.svelte` | 5 | Component |
| `frontends/wealth/src/lib/components/analytics/entity/ActiveSharePanel.svelte` | 5 | Component |
| `tests/quant_engine/test_return_statistics_service.py` | 2 | Test |
| `tests/quant_engine/test_tail_var_service.py` | 2 | Test |
| `tests/quant_engine/test_risk_budgeting_service.py` | 4 | Test |
| `tests/quant_engine/test_monte_carlo_service.py` | 5 | Test |
| `tests/quant_engine/test_peer_group_service.py` | 5 | Test |
| `tests/quant_engine/test_active_share_service.py` | 5 | Test |

### Modified Files

| File | Phase | Change |
|------|-------|--------|
| `backend/app/domains/wealth/schemas/entity_analytics.py` | 2, 3 | Add Groups 6-7 schemas |
| `backend/app/domains/wealth/routes/entity_analytics.py` | 2, 3 | Wire new quant services |
| `backend/app/domains/wealth/routes/analytics.py` | 4, 5 | Add risk-budget, factor-analysis, monte-carlo, peer-group endpoints |
| `backend/app/domains/wealth/schemas/analytics.py` | 4, 5 | Add risk budget, MC, peer group schemas |
| `backend/quant_engine/factor_model_service.py` | 4 | Add factor contribution decomposition |
| `backend/app/domains/wealth/workers/risk_calc.py` | 5 | Add peer percentile pre-computation |
| `backend/app/domains/wealth/models/risk.py` | 5 | Add peer percentile columns |
| `frontends/wealth/src/lib/types/analytics.ts` | 4, 5 | Add risk budget, MC, peer group types |
| `frontends/wealth/src/routes/(app)/analytics/+page.svelte` | 4, 5 | Add Risk Budget + MC sections |
| `frontends/wealth/src/routes/(app)/analytics/[entityId]/+page.svelte` | 2, 3, 5 | Extend with new panels |
| `frontends/wealth/src/routes/(app)/risk/+page.svelte` | 5 | Add peer summary + MC quick view |
| Navigation sidebar / CatalogDetailPanel.svelte | 1 | Add entity analytics link |

### Migration

| Migration | Phase | Description |
|-----------|-------|-------------|
| `0071_add_peer_percentile_columns.py` | 5 | Add peer_strategy_label, peer_*_pctl, peer_count to fund_risk_metrics |

---

## Dependencies & Prerequisites

- **Phase 1:** No dependencies — can start immediately
- **Phase 2:** Phase 1 frontend page must exist (to display new metrics)
- **Phase 3:** Phase 2 `tail_var_service.py` must exist (extends it)
- **Phase 4:** Independent of Phases 2-3 (portfolio-level, not entity-level)
- **Phase 5 Monte Carlo:** Independent (new service + route)
- **Phase 5 Peer Group:** Requires `strategy_label` populated on `instruments_universe` (already done via `universe_sync` worker)
- **Phase 5 Active Share:** Requires N-PORT holdings data in `sec_nport_holdings` (already ingested by `nport_ingestion` worker)

**Parallelization opportunity:** Phase 4 can run in parallel with Phase 2+3 (different scope: portfolio-level vs entity-level).

---

## Sources & References

### Origin

- **Reference document:** [docs/reference/evestment-reference.md](docs/reference/evestment-reference.md) — eVestment Investment Statistics Guide (80 metrics audited)
- **Audit conversation:** Gap analysis comparing 80 eVestment metrics against current backend/frontend state

### Internal References

- Entity analytics schema: [backend/app/domains/wealth/schemas/entity_analytics.py](backend/app/domains/wealth/schemas/entity_analytics.py)
- Entity analytics route: [backend/app/domains/wealth/routes/entity_analytics.py](backend/app/domains/wealth/routes/entity_analytics.py)
- Drawdown service pattern: [backend/quant_engine/drawdown_service.py](backend/quant_engine/drawdown_service.py)
- Risk calc worker: [backend/app/domains/wealth/workers/risk_calc.py](backend/app/domains/wealth/workers/risk_calc.py)
- Factor model service: [backend/quant_engine/factor_model_service.py](backend/quant_engine/factor_model_service.py)
- Optimizer (Cornish-Fisher reference): [backend/quant_engine/optimizer_service.py](backend/quant_engine/optimizer_service.py)

### External References

- eVestment Investment Statistics Guide (PDF) — formulas in Appendix I (p.54-76)
- Cornish-Fisher VaR expansion: standard 4-moment adjustment
- Tasche (2002) — Euler decomposition for ETL marginal contributions
- Kaplan & Schoar (2005) — PME Ratio methodology (deferred to future phase)
