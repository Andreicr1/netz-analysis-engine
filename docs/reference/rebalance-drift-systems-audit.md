# Rebalance & Drift Systems — Codebase Audit

> **Date:** 2026-04-05
> **Branch:** `refactor/factsheet-executive-snapshot`
> **Purpose:** Deep audit of existing rebalancing and drift calculation infrastructure before implementing the Portfolio Drift Analysis & Rebalance Proposals frontend integration.
> **Conclusion:** ~90% of math and persistence is built. Work is 2-3 new REST endpoints + Svelte 5 wiring.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Existing Assets Inventory](#2-existing-assets-inventory)
   - 2.1 [SQLAlchemy Models](#21-sqlalchemy-models)
   - 2.2 [Vertical Engine Packages](#22-vertical-engine-packages)
   - 2.3 [Quant Engine Services](#23-quant-engine-services)
   - 2.4 [REST Endpoints](#24-rest-endpoints)
   - 2.5 [Background Workers](#25-background-workers)
   - 2.6 [Pydantic Schemas](#26-pydantic-schemas)
3. [Algorithm Deep-Dive](#3-algorithm-deep-dive)
   - 3.1 [Allocation Drift (Block-Level)](#31-allocation-drift-block-level)
   - 3.2 [Strategy Drift (Fund-Level Z-Score)](#32-strategy-drift-fund-level-z-score)
   - 3.3 [DTW Behavioral Drift](#33-dtw-behavioral-drift)
   - 3.4 [Proportional Weight Redistribution](#34-proportional-weight-redistribution)
   - 3.5 [Rebalance Preview (Stateless Delta Engine)](#35-rebalance-preview-stateless-delta-engine)
   - 3.6 [Rebalance Cascade State Machine](#36-rebalance-cascade-state-machine)
4. [Data Flow Diagrams](#4-data-flow-diagrams)
5. [Gap Analysis](#5-gap-analysis)
6. [Integration Plan](#6-integration-plan)
7. [Configuration & Thresholds](#7-configuration--thresholds)
8. [Known Issues & Technical Debt](#8-known-issues--technical-debt)

---

## 1. Executive Summary

The Netz Analysis Engine already contains a **mature, production-grade** rebalancing and drift detection system spanning 7 SQLAlchemy models, 2 vertical engine packages (14 sub-modules), 4 quant engine services, 8 REST endpoints, and 2 background workers.

**What exists:**
- Full allocation drift computation (block-level, maintenance/urgent thresholds)
- Strategy drift detection (7-metric Z-score anomaly detection)
- DTW behavioral drift (derivative Dynamic Time Warping via `aeon`)
- Rebalance impact analysis (instrument deactivation -> affected portfolios)
- Weight proposal engine (proportional redistribution with iterative bound-clamping)
- Stateless rebalance preview (target vs current -> BUY/SELL/HOLD trade list, cash-neutral)
- Rebalance cascade state machine (ok -> warning -> breach -> hard_stop)
- CLARABEL 3-phase optimizer + NSGA-II Pareto frontier
- Monitoring alerts (DD expiry 360d, rebalance overdue 90d, universe removal)

**What is missing:**
- REST endpoint for on-demand `DriftReport` (block-level allocation drift)
- REST endpoint for **live-weight drift** using real-time NAV prices
- REST endpoint for monitoring alerts (`AlertBatch`)
- Frontend Svelte 5 components wired to the above

**No new algorithms are needed.** The integration work is purely plumbing: expose existing pure functions via REST and wire them to the Svelte 5 `PortfolioAnalyticsStore`.

---

## 2. Existing Assets Inventory

### 2.1 SQLAlchemy Models

| Model | Table | File | Key Fields |
|-------|-------|------|------------|
| `RebalanceEvent` | `rebalance_events` | `backend/app/domains/wealth/models/rebalance.py` | `event_type` (`cvar_breach`, `drift_rebalance`, `tactical_update`), `weights_before/after` (JSONB), `cvar_before/after`, `status` (pending/applied/rejected/cancelled) |
| `PortfolioSnapshot` | `portfolio_snapshots` (TimescaleDB hypertable, 1mo chunks) | `backend/app/domains/wealth/models/portfolio.py` | `weights` (JSONB: block_id -> weight), `fund_selection` (JSONB), `cvar_current/limit`, `cvar_utilized_pct`, `trigger_status` (ok/warning/breach), `regime`, `regime_probs`, `cvar_lower_5/upper_95` |
| `ModelPortfolio` | `model_portfolios` | `backend/app/domains/wealth/models/model_portfolio.py` | `fund_selection_schema` (JSONB: the **target composition**), `status` (draft/backtesting/active/archived), `inception_nav` |
| `StrategicAllocation` | `strategic_allocations` | `backend/app/domains/wealth/models/allocation.py` | `profile`, `block_id`, `target_weight`, `min_weight`, `max_weight`, `risk_budget`, `effective_from/to` |
| `TacticalPosition` | `tactical_positions` | `backend/app/domains/wealth/models/allocation.py` | `profile`, `block_id`, `overweight` (tilt from strategic), `conviction_score`, `signal_source`, `valid_from/to` |
| `StrategyDriftAlert` | `strategy_drift_alerts` (TimescaleDB hypertable, 1mo chunks, segmentby: instrument_id) | `backend/app/domains/wealth/models/strategy_drift_alert.py` | `severity` (none/moderate/severe), `anomalous_count`, `total_metrics`, `metric_details` (JSONB), `is_current` (flag pattern), `rebalance_triggered` |
| `FundRiskMetrics` | `fund_risk_metrics` | `backend/app/domains/wealth/models/risk.py` | `dtw_drift_score`, 7 risk metrics (volatility_1y, max_drawdown_1y, sharpe_1y, sortino_1y, alpha_1y, beta_1y, tracking_error_1y), `manager_score`, momentum signals (rsi_14, bb_position, nav/flow/blended_momentum_score), `volatility_garch`, `cvar_95_conditional` |

### 2.2 Vertical Engine Packages

#### `vertical_engines/wealth/rebalancing/`

| File | Key Exports | Purpose |
|------|-------------|---------|
| `models.py` | `RebalanceImpact`, `WeightProposal`, `RebalanceResult` (frozen dataclasses) | Domain models for rebalance computation results |
| `impact_analyzer.py` | `compute_impact(db, instrument_id, organization_id, trigger)` -> `RebalanceImpact` | Scans all active `ModelPortfolio.fund_selection_schema` (JSONB) to find portfolios containing a removed instrument; computes `weight_gap` |
| `weight_proposer.py` | `propose_weights(db, portfolio_id, removed_instrument_id, organization_id, config)` -> `WeightProposal` | Proportional redistribution with iterative bound-clamping; dead-band suppression (0.5%); returns feasibility flag |
| `preview_service.py` | `compute_rebalance_preview(portfolio_id, portfolio_name, profile, fund_selection_schema, current_holdings, cash_available, total_aum_override)` -> `dict` | **Stateless delta engine**: target vs current -> BUY/SELL/HOLD trades, cash-neutral, turnover estimate. Pure function, no DB writes. |
| `service.py` | `RebalancingService` with `compute_rebalance_impact()`, `detect_regime_trigger()` | Orchestrator: calls impact_analyzer + weight_proposer for each affected portfolio |

#### `vertical_engines/wealth/monitoring/`

| File | Key Exports | Purpose |
|------|-------------|---------|
| `drift_monitor.py` | `scan_drift(db, organization_id, drift_threshold=0.15)` -> `DriftScanResult` | Universe-aware drift scan: combines DTW style drift + deactivation detection; builds inverted index fund_id -> portfolio_names |
| `strategy_drift_scanner.py` | `scan_strategy_drift()`, `scan_all_strategy_drift()` | Z-score anomaly detection on 7 risk metrics with baseline/recent window split |
| `strategy_drift_models.py` | `MetricDrift`, `StrategyDriftResult`, `StrategyDriftScanResult` (frozen dataclasses) | Domain models for strategy drift results |
| `alert_engine.py` | `scan_alerts(db, organization_id)` -> `AlertBatch` | DD report expiry (360d) + rebalance overdue (90d) alerts |
| `overlap_scanner.py` | `compute_overlap(holdings, limit_pct=0.05)` -> `OverlapResult` | CUSIP/sector concentration breach detection |

### 2.3 Quant Engine Services

| Service | File | Key Functions |
|---------|------|---------------|
| **Drift Service** | `backend/quant_engine/drift_service.py` | `compute_block_drifts(current_weights, target_weights, maintenance_trigger, urgent_trigger)` -> `list[BlockDrift]`; `compute_dtw_drift(fund_returns, benchmark_returns, window=63)` -> `DtwDriftResult`; `compute_dtw_drift_batch()` (vectorized); `resolve_drift_thresholds(config)` |
| **Optimizer Service** | `backend/quant_engine/optimizer_service.py` | `optimize_fund_portfolio()` (CLARABEL 3-phase cascade); `optimize_portfolio_pareto()` (NSGA-II); `parametric_cvar_cf()` (Cornish-Fisher CVaR) |
| **Rebalance Service** | `backend/quant_engine/rebalance_service.py` | `determine_cascade_action(trigger_status, previous_status, cvar_utilized_pct, ...)` -> state transition; `validate_status_transition()` |
| **Allocation Proposal** | `backend/quant_engine/allocation_proposal_service.py` | `BlockProposal`, `AllocationProposalResult` — Black-Litterman regime tilts with regional scores |
| **Scoring Service** | `backend/quant_engine/scoring_service.py` | `compute_fund_score(metrics, ...)` — 6-component weighted composite (return_consistency 0.20, risk_adjusted 0.25, drawdown 0.20, IR 0.15, flows 0.10, fee_efficiency 0.10) |

### 2.4 REST Endpoints

| Method | Path | Handler | File | Status |
|--------|------|---------|------|--------|
| `POST` | `/model-portfolios/{id}/rebalance/preview` | `rebalance_preview()` | `backend/app/domains/wealth/routes/model_portfolios.py` | **EXISTS** |
| `POST` | `/rebalancing/proposals/{id}/apply` | `apply_rebalance_proposal()` | `backend/app/domains/wealth/routes/rebalancing.py` | **EXISTS** |
| `POST` | `/analytics/strategy-drift/scan` | Full org-wide scan (advisory lock) | `backend/app/domains/wealth/routes/strategy_drift.py` | **EXISTS** |
| `GET` | `/analytics/strategy-drift/alerts` | Current drift alerts (filter by severity) | `backend/app/domains/wealth/routes/strategy_drift.py` | **EXISTS** |
| `GET` | `/analytics/strategy-drift/{instrument_id}` | Single instrument on-demand scan | `backend/app/domains/wealth/routes/strategy_drift.py` | **EXISTS** |
| `GET` | `/analytics/strategy-drift/{instrument_id}/history` | Alert history (date range + severity filter) | `backend/app/domains/wealth/routes/strategy_drift.py` | **EXISTS** |
| `GET` | `/analytics/strategy-drift/{instrument_id}/export` | CSV/JSON export of drift history | `backend/app/domains/wealth/routes/strategy_drift.py` | **EXISTS** |
| `GET` | `/model-portfolios/{id}/holdings` | Positions + latest prices + intraday PnL | `backend/app/domains/wealth/routes/model_portfolios.py` | **EXISTS** |
| `GET` | `/model-portfolios/{id}/drift` | Block-level allocation drift report | — | **MISSING** |
| `GET` | `/model-portfolios/{id}/drift/live` | Live-weight drift (real-time NAV) | — | **MISSING** |
| `GET` | `/monitoring/alerts` | DD expiry + rebalance overdue alerts | — | **MISSING** |

### 2.5 Background Workers

| Worker | Lock ID | Frequency | File | Purpose |
|--------|---------|-----------|------|---------|
| `drift_check` | 42 | Daily | `backend/app/domains/wealth/workers/drift_check.py` | Runs `compute_drift(db, profile)` for 3 profiles (conservative, moderate, growth); auto-creates `RebalanceEvent` with `event_type="drift_rebalance"` if recommended |
| `portfolio_eval` | 900_008 | Daily | `backend/app/domains/wealth/workers/portfolio_eval.py` | Computes CVaR from return distribution, detects regime (normal/low_vol/stress/crisis), creates daily `PortfolioSnapshot`, publishes breach alerts via Redis pub/sub |

### 2.6 Pydantic Schemas

Located in `backend/app/domains/wealth/schemas/portfolio.py`:

| Schema | Key Fields | Used By |
|--------|-----------|---------|
| `PortfolioSummary` | `profile`, `cvar_current/limit/utilized_pct`, `trigger_status`, `regime`, `core_weight/satellite_weight` | Dashboard summary |
| `PortfolioSnapshotRead` | Full snapshot including `regime_probs`, `cvar_lower_5/upper_95` | Snapshot detail |
| `RebalanceRequest` | `trigger_reason` (max 5000 chars) | Manual rebalance trigger |
| `RebalanceEventRead` | `event_id`, `event_type`, `weights_before/after`, `cvar_before/after`, `status` | Rebalance history |
| `RebalanceApproveRequest` | `notes` (max 5000 chars) | Approval flow |
| `PositionDetail` | `instrument_id`, `ticker`, `weight`, `block_id`, `last_price`, `previous_close`, `position_value`, `intraday_pnl/pnl_pct` | Holdings view |
| `PerformancePoint` | `nav_date`, `nav`, `daily_return`, `cumulative_return`, `benchmark_nav/cumulative_return` | Performance chart |

---

## 3. Algorithm Deep-Dive

### 3.1 Allocation Drift (Block-Level)

**File:** `backend/quant_engine/drift_service.py`
**Function:** `compute_block_drifts(current_weights, target_weights, maintenance_trigger=0.05, urgent_trigger=0.10)`

```
target = strategic_target + tactical_overweight
absolute_drift = current_weight - target
relative_drift = absolute_drift / target (if target > 0)

Status:
  |absolute_drift| >= urgent_trigger (10%)  -> "urgent"
  |absolute_drift| >= maintenance_trigger (5%) -> "maintenance"
  otherwise -> "ok"

Rebalance recommended when:
  overall_status != "ok" AND estimated_turnover >= 1%
  estimated_turnover = sum(meaningful_trades) / 2
  meaningful_trade = |drift| >= min_trade_threshold (0.5%)
```

**Data access layer:** `backend/app/domains/wealth/services/quant_queries.py` -> `compute_drift(db, profile, as_of_date, config)`
1. Loads latest `PortfolioSnapshot` for profile
2. Extracts `current_weights` from `snapshot.weights` (JSONB)
3. Loads effective `StrategicAllocation` + `TacticalPosition`
4. Combines: `target = strategic + tactical`
5. Calls pure `compute_block_drifts()` (no DB access)

### 3.2 Strategy Drift (Fund-Level Z-Score)

**File:** `backend/vertical_engines/wealth/monitoring/strategy_drift_scanner.py`
**Function:** `scan_strategy_drift(metrics_history, instrument_id, instrument_name, config)`

```
Metrics checked (7):
  volatility_1y, max_drawdown_1y, sharpe_1y, sortino_1y,
  alpha_1y, beta_1y, tracking_error_1y

Windows:
  Baseline: 360 days (configurable, min 20 data points)
  Recent:   90 days  (configurable, min 5 data points)

Per metric:
  z = (mean_recent - mean_baseline) / std_baseline
  is_anomalous = |z| > 2.0 (STRICT greater-than; z=2.0 exactly is NOT anomalous)
  Skip if std_baseline < 1e-10 (constant series)

Severity grading:
  anomalous_count >= 3 -> "severe"
  anomalous_count >= 1 -> "moderate"
  anomalous_count == 0 -> "none"
```

### 3.3 DTW Behavioral Drift

**File:** `backend/quant_engine/drift_service.py`
**Function:** `compute_dtw_drift(fund_returns, benchmark_returns, window=63, max_lookback_days=504)`

- Uses **Derivative Dynamic Time Warping** (DDTW) from `aeon` library
- Scale-invariant distance metric
- Length-normalized: `score = raw_ddtw_distance / max(window_len, 1)`
- Returns typed `DtwDriftResult` (never silent 0.0 on failure — `degraded`/`failed` status)
- Guard: < 10 data points -> `degraded` status
- Thresholds: warning=0.40, critical=0.90 (configurable)

**Batch variant:** `compute_dtw_drift_batch()` uses `aeon.distances.pairwise_distance(method="ddtw")` for vectorized computation.

### 3.4 Proportional Weight Redistribution

**File:** `backend/vertical_engines/wealth/rebalancing/weight_proposer.py`
**Function:** `propose_weights(db, portfolio_id, removed_instrument_id, organization_id, config)`

```
Algorithm (iterative bound-clamping, max 10 iterations):
  1. Normalize current weights to sum=1
  2. For each iteration:
     a. Check each unfrozen block against StrategicAllocation bounds
     b. Clamp blocks that violate min/max -> freeze them at bound value
     c. Renormalize unfrozen blocks to fill remaining budget
     d. Repeat until convergence or max iterations
  3. Apply dead-band suppression (0.5%) to prevent micro-trades
  4. Return None if infeasible (sum_of_mins > 1.0 or sum_of_maxes < 1.0)

Invariant: sum(weights) == 1.0 always, or infeasible flag raised
```

### 3.5 Rebalance Preview (Stateless Delta Engine)

**File:** `backend/vertical_engines/wealth/rebalancing/preview_service.py`
**Function:** `compute_rebalance_preview(...)`

```
Input:
  fund_selection_schema (target weights)
  current_holdings [{instrument_id, quantity, price}]
  cash_available, total_aum_override

Algorithm:
  1. Inject cash as synthetic holding (CASH_INSTRUMENT_ID = 00000000-...-000000000000, price=1.0)
  2. Build current map: instrument_id -> {quantity, price, value}
  3. Build target map: instrument_id -> {weight}; cash_target = max(1 - sum_of_fund_weights, 0)
  4. Per instrument (union of current + target):
     current_weight = current_value / total_aum
     target_weight  = target_map[iid]["weight"]
     delta_weight   = target_weight - current_weight
     trade_value    = (target_weight * total_aum) - current_value
     action = BUY (>0) | SELL (<0) | HOLD (|delta| < 1e-6)
  5. Cash sweep: cash_trade = -sum(non_cash_trades)
     Validate: |sum(all_trades)| < 0.01 (cash-neutral invariant)
  6. Sort: sells -> buys -> cash

Output:
  trades[], weight_comparison (per block), estimated_turnover_pct
  Invariant: sum(trade_value) == 0
```

### 3.6 Rebalance Cascade State Machine

**File:** `backend/quant_engine/rebalance_service.py`
**Function:** `determine_cascade_action(trigger_status, previous_status, cvar_utilized_pct, consecutive_breach_days, profile, config)`

```
State transitions:
  ok          -> (no action)
  ok -> warning   -> Create RebalanceEvent {event_type: "cvar_breach"}
  * -> breach     -> Create RebalanceEvent {event_type: "cvar_breach", consecutive info}

RebalanceEvent status lifecycle:
  pending -> approved | rejected | cancelled | applied
  approved -> executed
  rejected, cancelled, executed -> terminal (no further transitions)
```

---

## 4. Data Flow Diagrams

### 4.1 Daily Portfolio Evaluation & Drift Check

```
portfolio_eval worker (lock 900_008)
  |
  +-- For each profile (conservative, moderate, growth):
  |     |
  |     +-- Load StrategicAllocation block weights
  |     +-- Fetch active fund returns by block
  |     +-- Compute CVaR from return distribution
  |     +-- Check breach status (ok/warning/breach)
  |     +-- Detect regime (normal/low_vol/stress/crisis)
  |     +-- Create PortfolioSnapshot
  |     +-- Publish breach alert via Redis pub/sub (if triggered)
  |
  v
drift_check worker (lock 42)
  |
  +-- For each profile:
  |     |
  |     +-- compute_drift(db, profile)
  |     |     +-- Load latest PortfolioSnapshot.weights (current)
  |     |     +-- Load StrategicAllocation + TacticalPosition (target)
  |     |     +-- compute_block_drifts() (pure function)
  |     |
  |     +-- If rebalance_recommended:
  |           +-- Create RebalanceEvent (event_type="drift_rebalance", actor_source="system")
  |           +-- Log top 3 drifted blocks
  |
  v
Strategy Drift Scan (on-demand via POST /analytics/strategy-drift/scan)
  |
  +-- Advisory lock (per-org serialization)
  +-- Load all active Instruments
  +-- Batch-load FundRiskMetrics (single IN query)
  +-- Group metrics by instrument_id
  +-- asyncio.to_thread(scan_all_strategy_drift(...))
  |     +-- Per instrument: Z-score on 7 metrics
  |     +-- Severity grading: severe (3+) | moderate (1+) | none
  +-- Mark previous StrategyDriftAlert.is_current = false
  +-- Batch INSERT new alerts
```

### 4.2 Rebalance Impact Flow (Instrument Deactivation)

```
Instrument deactivated
  |
  v
RebalancingService.compute_rebalance_impact()
  |
  +-- compute_impact(db, instrument_id, organization_id)
  |     +-- Query all active ModelPortfolios
  |     +-- Scan fund_selection_schema JSONB for instrument_id match
  |     +-- Return: affected_portfolios[], weight_gap
  |
  +-- For each affected portfolio:
  |     +-- propose_weights(db, portfolio_id, removed_id)
  |           +-- Load latest PortfolioSnapshot (current block weights)
  |           +-- Load StrategicAllocation bounds (min/max)
  |           +-- _redistribute_proportionally() with iterative clamping
  |           +-- Apply dead-band (0.5%)
  |           +-- Return WeightProposal (feasible flag, new_weights)
  |
  v
RebalanceEvent created (status="pending")
  |
  v
Manual approval (POST /rebalancing/proposals/{id}/apply)
  |
  +-- Update ModelPortfolio.fund_selection_schema
  +-- Create PortfolioSnapshot (trigger_status="rebalance_apply")
  +-- Insert ModelPortfolioNav breakpoint (daily_return=0.0)
  +-- Mark event as "applied"
  +-- portfolio_nav_synthesizer detects breakpoint -> reprocesses NAV
```

### 4.3 Rebalance Preview Flow (Stateless)

```
Frontend PortfolioAnalyticsStore (live prices)
  |
  v
POST /model-portfolios/{id}/rebalance/preview
  |
  +-- Input: fund_selection_schema (target) + current_holdings + cash_available
  |
  +-- compute_rebalance_preview() [pure function, no DB]
  |     +-- Normalize cash as synthetic holding
  |     +-- Build current map: iid -> {qty, price, value}
  |     +-- Build target map: iid -> {weight}
  |     +-- Compute trades: delta = target_weight - current_weight
  |     +-- Cash sweep: enforce sum(trade_value) == 0
  |
  v
Response: trades[], weight_comparison[], turnover_pct
```

---

## 5. Gap Analysis

### Exists vs Missing

| Capability | Backend Status | Frontend Status | Gap |
|------------|---------------|-----------------|-----|
| **Allocation drift (block-level)** | `compute_block_drifts()` works, `compute_drift()` queries DB | No frontend component | **Missing REST endpoint** `GET /model-portfolios/{id}/drift` |
| **Live-weight drift** | Math exists in `compute_block_drifts()` | `PortfolioAnalyticsStore` has live prices via WebSocket | **Missing REST endpoint** that computes current weights from live NAV instead of stale snapshot |
| **Strategy drift alerts** | Full CRUD + scan endpoints exist | No frontend component wired | **Routing prefix mismatch** (TODO #127): frontend calls `/wealth/analytics/...`, backend serves `/api/v1/analytics/...` |
| **Rebalance preview (trade list)** | `POST /model-portfolios/{id}/rebalance/preview` exists | No frontend component | **Missing UI** — endpoint requires `current_holdings` in request body; frontend store has live prices but needs to build the payload |
| **Rebalance apply** | `POST /rebalancing/proposals/{id}/apply` exists | No frontend component | **Missing UI** for approval flow |
| **Monitoring alerts (DD expiry, rebalance overdue)** | `scan_alerts()` in `alert_engine.py` works | No frontend component | **Missing REST endpoint** — function is internal, no route handler |
| **DTW drift per fund** | Pre-computed in `fund_risk_metrics.dtw_drift_score` | Available via holdings endpoint | **Needs surfacing** in fund detail UI |
| **Overlap scanner** | `POST /model-portfolios/{id}/overlap` exists | No frontend component | **Missing UI** for CUSIP/sector concentration view |

### Critical Missing Endpoints

1. **`GET /model-portfolios/{id}/drift`** — The `DriftReport` (block-level allocation drift with maintenance/urgent status) has no REST surface. `compute_drift()` in `quant_queries.py` does the DB queries but is only called by the `drift_check` worker.

2. **`GET /model-portfolios/{id}/drift/live`** — Nothing computes current weights from live WebSocket prices. The daily `PortfolioSnapshot.weights` are stale by definition. The math is trivial (live_value / total_aum per block), but needs a new endpoint.

3. **`GET /monitoring/alerts`** — `alert_engine.scan_alerts()` returns `AlertBatch` (DD expiry + rebalance overdue) but has no route handler.

### Non-Gaps (Already Solved)

- Rebalance preview math: `preview_service.py` is complete and stateless
- Strategy drift scan + alert persistence: full CRUD exists
- Weight redistribution on deactivation: `weight_proposer.py` handles it
- Rebalance cascade state machine: `rebalance_service.py` validates transitions
- CLARABEL optimization: 3-phase cascade with CVaR enforcement is production-ready
- Cornish-Fisher CVaR: fat-tail adjusted, not Normal assumption

---

## 6. Integration Plan

### Step 1: `GET /model-portfolios/{id}/drift` (New Endpoint)

**What:** Expose existing `compute_drift()` from `quant_queries.py` as REST.

**Implementation:**
- Add handler in `backend/app/domains/wealth/routes/model_portfolios.py`
- Call `compute_drift(db, portfolio.profile, date.today(), config=config)`
- Create `DriftReportRead` Pydantic schema mirroring `DriftReport` dataclass:
  ```python
  class BlockDriftRead(BaseModel):
      block_id: str
      current_weight: float
      target_weight: float
      absolute_drift: float
      relative_drift: float
      status: str  # "ok" | "maintenance" | "urgent"

  class DriftReportRead(BaseModel):
      profile: str
      as_of_date: date
      blocks: list[BlockDriftRead]
      max_drift_pct: float
      overall_status: str
      rebalance_recommended: bool
      estimated_turnover: float
  ```

**Import-linter compliance:** `route -> quant_queries (domain service) -> drift_service (quant engine)` — no new cross-vertical imports.

### Step 2: `GET /model-portfolios/{id}/drift/live` (New Endpoint)

**What:** Compute drift using real-time NAV prices from `nav_timeseries` (latest row) instead of stale snapshot.

**Implementation:**
- Load `fund_selection_schema` (targets) from `ModelPortfolio`
- Load `StrategicAllocation` + `TacticalPosition` (block targets)
- Query latest `nav_timeseries` price per instrument in the portfolio
- Compute live position values: `weight_from_schema * latest_nav`
- Normalize to current block weights
- Pass to existing `compute_block_drifts()` — **zero new math**
- This is the endpoint the Svelte 5 `PortfolioAnalyticsStore` will poll (every 30s or on WS price update)

### Step 3: `GET /monitoring/alerts` (New Endpoint)

**What:** Expose `alert_engine.scan_alerts()` as REST.

**Implementation:**
- New handler in monitoring routes or `model_portfolios.py`
- Call `scan_alerts(db, organization_id)` -> return `AlertBatchRead` schema
- Fix TODO #075 ("never days ago" grammatical error) while adding the route

### Step 4: Wire Rebalance Preview to Frontend

**What:** The `POST /model-portfolios/{id}/rebalance/preview` already exists. Frontend needs to call it.

**Implementation:**
- Frontend `PortfolioAnalyticsStore` has live prices per instrument
- Build `current_holdings` array: `[{instrument_id, quantity, price}]` from store state
- POST to preview endpoint -> receive trade list (BUY/SELL/HOLD + turnover)
- Render in a `RebalancePreview.svelte` component

### Step 5: Svelte 5 Components

| Component | Data Source | Purpose |
|-----------|-----------|---------|
| `DriftGauge.svelte` | `GET /drift/live` (polled every 30s) | Block-level drift bars: ok (green), maintenance (amber), urgent (red) |
| `RebalancePreview.svelte` | `POST /rebalance/preview` (on-demand) | Trade list table: instrument, action (BUY/SELL/HOLD), delta_weight, trade_value, turnover |
| `StrategyDriftAlerts.svelte` | `GET /analytics/strategy-drift/alerts` | Card list: fund name, severity badge, anomalous metrics count, z-scores |
| `MonitoringAlerts.svelte` | `GET /monitoring/alerts` | DD expiry + rebalance overdue warnings |

### Import-Linter DAG Compliance

```
Routes (model_portfolios.py)
  |-- calls --> Domain Services (quant_queries.py)
  |               |-- calls --> Quant Engine (drift_service.py)  [pure functions, no DB]
  |
  |-- calls --> Vertical Engines (rebalancing/preview_service.py)  [pure functions, no DB]
  |
  |-- calls --> Vertical Engines (monitoring/alert_engine.py)  [DB read-only]
```

No new cross-vertical imports. No wealth<->credit coupling. All new routes stay in `backend/app/domains/wealth/routes/`.

---

## 7. Configuration & Thresholds

| Parameter | Default | Config Path | Used By |
|-----------|---------|-------------|---------|
| Allocation Drift — Maintenance Trigger | 5.0% | `drift_bands.maintenance_trigger` | `compute_block_drifts()` |
| Allocation Drift — Urgent Trigger | 10.0% | `drift_bands.urgent_trigger` | `compute_block_drifts()` |
| Strategy Drift — Z-Score Threshold | 2.0 | `z_threshold` | `scan_strategy_drift()` |
| Strategy Drift — Recent Window | 90 days | `recent_window_days` | `scan_strategy_drift()` |
| Strategy Drift — Baseline Window | 360 days | `baseline_window_days` | `scan_strategy_drift()` |
| Strategy Drift — Min Baseline Points | 20 | `min_baseline_points` | `scan_strategy_drift()` |
| Strategy Drift — Min Recent Points | 5 | `min_recent_points` | `scan_strategy_drift()` |
| Strategy Drift — Severity Severe | 3+ anomalous metrics | hardcoded | `scan_strategy_drift()` |
| DTW Drift — Window | 63 days (~3 months) | `window` parameter | `compute_dtw_drift()` |
| DTW Drift — Max Lookback | 504 days (~2 years) | `max_lookback_days` | `compute_dtw_drift()` |
| DTW Drift — Warning Threshold | 0.40 | `dtw.dtw_divergence_warning` | `drift_monitor.py` |
| DTW Drift — Critical Threshold | 0.90 | `dtw.dtw_divergence_critical` | `drift_monitor.py` |
| Rebalance — Regime Trigger | 2 consecutive evals | `regime_consecutive_threshold` | `detect_regime_trigger()` |
| Rebalance — Min Trade Threshold | 0.5% | `min_trade_threshold` | `compute_drift()` |
| Rebalance — Turnover for Recommendation | 1.0% | hardcoded | `compute_drift()` |
| Rebalance — Dead Band | 0.5% | `dead_band_pct` | `propose_weights()` |
| Preview — Hold Threshold | 0.0001% | `_HOLD_THRESHOLD` | `compute_rebalance_preview()` |
| Preview — Cash Instrument ID | `00000000-0000-0000-0000-000000000000` | `CASH_INSTRUMENT_ID` | `compute_rebalance_preview()` |
| DD Expiry Alert | 360 days | hardcoded | `alert_engine._check_dd_expiry()` |
| Rebalance Overdue Alert | 90 days | hardcoded | `alert_engine._check_rebalance_overdue()` |
| CVaR Limit — Conservative | -0.08 | ConfigService per-profile | `portfolio_eval` worker |
| CVaR Limit — Moderate | -0.06 | ConfigService per-profile | `portfolio_eval` worker |
| CVaR Limit — Growth | -0.12 | ConfigService per-profile | `portfolio_eval` worker |

---

## 8. Known Issues & Technical Debt

| ID | Priority | Status | File | Description |
|----|----------|--------|------|-------------|
| TODO #075 | P3 | pending | `alert_engine.py` | Alert detail reads "never days ago" when no rebalance exists (grammatical error) |
| TODO #127 | P1 | pending | Frontend routing | Frontend calls `/wealth/analytics/strategy-drift/alerts` but backend route is `/api/v1/analytics/strategy-drift/alerts` (prefix mismatch -> silent 404) |
| TODO #140 | P2 | complete | `strategy_drift.py` | Double computation: `scan_all_strategy_drift()` processes all instruments, then route re-computes stable/insufficient counts |
| TODO #141 | P2 | complete | `strategy_drift.py` | Per-row INSERT instead of batch: 200 round-trips for 200 alerts |
| — | P3 | noted | `preview_service.py` | Uses `float` throughout, not `Decimal`. Acceptable for computation but frontend receives floats. |
| — | P3 | noted | `weight_proposer.py` | `cvar_after` is a placeholder in `WeightProposal` (always 0.0) — real CVaR recalculated in daily pipeline |

---

## Appendix: File Index

```
backend/
  app/domains/wealth/
    models/
      allocation.py         <- StrategicAllocation, TacticalPosition
      model_portfolio.py    <- ModelPortfolio (fund_selection_schema = target)
      portfolio.py          <- PortfolioSnapshot (weights = current, hypertable)
      rebalance.py          <- RebalanceEvent (pending/applied lifecycle)
      risk.py               <- FundRiskMetrics (dtw_drift_score, 7 risk metrics)
      strategy_drift_alert.py <- StrategyDriftAlert (hypertable, is_current pattern)
    routes/
      model_portfolios.py   <- /rebalance/preview, /holdings, /construct, /overlap
      rebalancing.py        <- /proposals/{id}/apply
      strategy_drift.py     <- /scan, /alerts, /{id}, /{id}/history, /{id}/export
    schemas/
      portfolio.py          <- PositionDetail, RebalanceEventRead, DriftReportRead (TODO)
    services/
      quant_queries.py      <- compute_drift() (data access -> drift_service)
    workers/
      drift_check.py        <- Daily drift check (lock 42)
      portfolio_eval.py     <- Daily portfolio evaluation (lock 900_008)

  quant_engine/
    drift_service.py        <- compute_block_drifts(), compute_dtw_drift(), DtwDriftResult
    optimizer_service.py    <- CLARABEL 3-phase cascade, NSGA-II Pareto, Cornish-Fisher CVaR
    rebalance_service.py    <- Cascade state machine (ok->warning->breach->hard_stop)
    allocation_proposal_service.py <- Black-Litterman regime tilts
    scoring_service.py      <- 6-component fund scoring

  vertical_engines/wealth/
    rebalancing/
      models.py             <- RebalanceImpact, WeightProposal, RebalanceResult
      impact_analyzer.py    <- compute_impact() (affected portfolios)
      weight_proposer.py    <- propose_weights() (proportional redistribution)
      preview_service.py    <- compute_rebalance_preview() (stateless delta engine)
      service.py            <- RebalancingService (orchestrator)
    monitoring/
      drift_monitor.py      <- scan_drift() (DTW + deactivation)
      strategy_drift_scanner.py <- scan_strategy_drift() (Z-score anomaly)
      strategy_drift_models.py  <- MetricDrift, StrategyDriftResult
      alert_engine.py       <- scan_alerts() (DD expiry, rebalance overdue)
      overlap_scanner.py    <- compute_overlap() (CUSIP/sector concentration)
```
