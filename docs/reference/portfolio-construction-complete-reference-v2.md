# Portfolio Construction — Complete Technical Reference

> Unified reference for the Netz Wealth OS portfolio construction pipeline.
> Covers every stage from macro regime detection through fund-level optimization,
> construction advisor, validation, and activation.

**Last updated:** 2026-04-06 (v2.1: Quantitative Fast-Track approval flow + automated eviction worker)
**Supersedes:** Partial coverage in `portfolio-construction-reference-v2-post-quant-upgrade.md` (optimizer detail) and `institutional-portfolio-lifecycle-reference.md` (lifecycle overview).

**Changelog:**
- **2026-04-06** — Added §5.4 (Tiered Due Diligence: Quantitative Fast-Track), §5.5 (Automated Eviction), §12.5 (Fast-Track Eviction Worker). Documented `UniverseDecision.revoked` enum value, lock ID `900_009`, and the new `POST /screener/fast-track-approval` endpoint feeding `_load_universe_funds()`.
- **2026-04-05** — fee_efficiency formula clarified, momentum components documented.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Pipeline Stages](#2-pipeline-stages)
3. [Stage 1 — Regime Detection](#3-stage-1--regime-detection)
4. [Stage 2 — Strategic Allocation](#4-stage-2--strategic-allocation)
5. [Stage 3 — Universe Loading](#5-stage-3--universe-loading)
   - [5.4 Tiered Due Diligence — Quantitative Fast-Track](#54-tiered-due-diligence--quantitative-fast-track)
   - [5.5 Automated Eviction (Fast-Track Governance)](#55-automated-eviction-fast-track-governance)
6. [Stage 4 — Statistical Inputs](#6-stage-4--statistical-inputs)
7. [Stage 5 — CLARABEL Optimizer Cascade](#7-stage-5--clarabel-optimizer-cascade)
8. [Stage 6 — Portfolio Composition](#8-stage-6--portfolio-composition)
9. [Stage 7 — Construction Advisor](#9-stage-7--construction-advisor)
10. [Stage 8 — Validation (Backtest + Stress)](#10-stage-8--validation-backtest--stress)
11. [Stage 9 — Activation](#11-stage-9--activation)
12. [Stage 10 — Monitoring](#12-stage-10--monitoring)
13. [Data Model](#13-data-model)
14. [API Endpoints](#14-api-endpoints)
15. [Configuration Reference](#15-configuration-reference)
16. [Error Handling & Fallbacks](#16-error-handling--fallbacks)
17. [Frontend Implementation](#17-frontend-implementation)
18. [Glossary](#18-glossary)

---

## 1. Architecture Overview

Portfolio construction is an **11-stage pipeline** that transforms macro signals, strategic allocation targets, and a fund universe into an optimized, risk-compliant portfolio.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  1. Regime   │───▶│  2. Strate-  │───▶│  3. Universe │
│  Detection   │    │  gic Alloc   │    │  Loading     │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
┌──────────────┐    ┌──────────────┐    ┌──────▼───────┐
│  6. Portfo-  │◀───│  5. CLARABEL │◀───│  4. Statis-  │
│  lio Compo-  │    │  Optimizer   │    │  tical Inputs│
│  sition      │    │  Cascade     │    │              │
└──────┬───────┘    └──────────────┘    └──────────────┘
       │
       ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  7. Construc-│───▶│  8. Valida-  │───▶│  9. Activa-  │
│  tion Advisor│    │  tion        │    │  tion        │
│  (if needed) │    │  BT + Stress │    │              │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                                        ┌──────▼───────┐
                                        │ 10. Monitor- │
                                        │  ing & Drift │
                                        └──────────────┘
```

**Key invariants:**
- All configuration resolved via `ConfigService` at async entry point, passed as plain dicts/dataclasses downstream.
- CPU-bound computation (numpy, scipy, CLARABEL) runs in `asyncio.to_thread()`.
- ORM objects are extracted into frozen dataclasses before crossing the async/thread boundary.
- No module-level mutable state (`Semaphore`, `Lock`, `lru_cache`) in any engine module.

**Key files:**

| Concern | File |
|---------|------|
| Route orchestrator | `app/domains/wealth/routes/model_portfolios.py` |
| Fund-level input prep | `app/domains/wealth/services/quant_queries.py` |
| CLARABEL optimizer | `quant_engine/optimizer_service.py` |
| Portfolio builder | `vertical_engines/wealth/model_portfolio/portfolio_builder.py` |
| Construction advisor | `vertical_engines/wealth/model_portfolio/construction_advisor.py` |
| Candidate screener I/O | `app/domains/wealth/services/candidate_screener.py` |
| Block mapping | `vertical_engines/wealth/model_portfolio/block_mapping.py` |
| Regime service | `quant_engine/regime_service.py` |
| CVaR service | `quant_engine/cvar_service.py` |
| Black-Litterman | `quant_engine/black_litterman_service.py` |
| Factor model | `quant_engine/factor_model_service.py` |
| GARCH | `quant_engine/garch_service.py` |
| Scoring | `quant_engine/scoring_service.py` |
| Allocation proposals | `quant_engine/allocation_proposal_service.py` |
| Stress scenarios | `vertical_engines/wealth/model_portfolio/stress_engine.py` |
| Backtest engine | `vertical_engines/wealth/model_portfolio/backtest_engine.py` |

---

## 2. Pipeline Stages

The pipeline runs when a user clicks **"Construct Portfolio"** on the Model Portfolio Workbench. The backend entry point is:

```
POST /api/v1/model-portfolios/{portfolio_id}/construct
```

This triggers `_run_construction_async()` which orchestrates all stages sequentially.

| Stage | Name | I/O | Duration |
|-------|------|-----|----------|
| 1 | Regime Detection | DB read (macro_data) | ~50ms |
| 2 | Strategic Allocation | DB read (strategic_allocation) | ~20ms |
| 3 | Universe Loading | DB read (instruments + risk metrics) | ~100ms |
| 4 | Statistical Inputs | DB read (nav_timeseries) + numpy | ~200ms |
| 5 | Optimizer Cascade | CPU (CLARABEL/SCS) | ~50-200ms |
| 6 | Portfolio Composition | Pure function | ~1ms |
| 7 | Construction Advisor | CPU (numpy) — only if CVaR fails | ~1-3s |
| 8 | Validation | CPU (backtest/stress) — user-triggered | ~500ms |
| 9 | Activation | DB write (status update) — user-triggered | ~20ms |
| 10 | Monitoring | Background worker (daily) | continuous |

---

## 3. Stage 1 — Regime Detection

**Service:** `quant_engine/regime_service.py`

Classifies the current market environment into one of four regimes, used to condition covariance estimation and CVaR limits.

### 3.1 Multi-Signal Classification

```python
classify_regime_multi_signal(
    vix: float | None,
    yield_curve_spread: float | None,
    cpi_yoy: float | None,
    sahm_rule: float | None,
) -> tuple[str, dict[str, str]]
```

**Priority hierarchy (first match wins):**

| Priority | Regime | Trigger |
|----------|--------|---------|
| 1 | `CRISIS` | VIX >= 35 |
| 2 | `INFLATION` | CPI YoY >= 4.0% |
| 3 | `RISK_OFF` | VIX >= 25 |
| 4 | `RISK_ON` | Default |

**Data source:** All signals read from `macro_data` hypertable (FRED series ingested by `macro_ingestion` worker). Zero external API calls at runtime.

### 3.2 Regional Regime Classification

Each geographic region gets an independent regime based on ICE BofA credit spreads (OAS):

| Region | Signal | Risk-Off Threshold | Crisis Threshold |
|--------|--------|-------------------|------------------|
| US | VIX + OAS | OAS >= 550bp | OAS >= 800bp |
| Europe | OAS | OAS >= 550bp | OAS >= 800bp |
| Asia | OAS | OAS >= 550bp | OAS >= 800bp |
| EM | OAS | OAS >= 550bp | OAS >= 800bp |

### 3.3 Global Regime Composition

Regional regimes are composed into a single global regime via GDP-weighted voting:

```
US: 25%  |  Europe: 22%  |  Asia: 28%  |  EM: 25%
```

**Pessimistic override:** If 2+ regions are in `CRISIS`, global regime = `CRISIS` regardless of weighted score.

### 3.4 Regime CVaR Multipliers

The detected regime tightens or loosens CVaR constraints:

| Regime | Multiplier | Effect |
|--------|-----------|--------|
| `RISK_ON` | 1.00 | No adjustment |
| `RISK_OFF` | 0.85 | 15% tighter CVaR limit |
| `CRISIS` | 0.70 | 30% tighter CVaR limit |
| `INFLATION` | 0.90 | 10% tighter CVaR limit |

Applied at Phase 1 CVaR check in the optimizer: `effective_limit = cvar_limit * multiplier`.

---

## 4. Stage 2 — Strategic Allocation

**Service:** `quant_engine/allocation_proposal_service.py`
**Model:** `app/domains/wealth/models/allocation.py`

### 4.1 Data Model

The `strategic_allocation` table stores per-profile, per-block weight targets:

| Column | Type | Description |
|--------|------|-------------|
| `profile` | str | `conservative`, `moderate`, `growth` |
| `block_id` | str | FK to `allocation_blocks` (e.g., `na_equity_large`) |
| `target_weight` | Decimal(6,4) | Neutral allocation (e.g., 0.2000) |
| `min_weight` | Decimal(6,4) | Floor constraint |
| `max_weight` | Decimal(6,4) | Ceiling constraint |
| `risk_budget` | Decimal(6,4) | Optional CVaR budget per block |
| `effective_from` | date | Version start date |
| `effective_to` | date | Version end date (NULL = ongoing) |

**Query logic:** Filter by `profile` + `effective_from <= today <= effective_to`, deduplicate by `block_id` (latest `effective_from` wins).

### 4.2 Allocation Blocks

The `allocation_blocks` table defines the asset class taxonomy (global, no RLS):

| block_id | asset_class | geography | Example benchmark |
|----------|-------------|-----------|-------------------|
| `na_equity_large` | Equity | US | SPY |
| `na_equity_growth` | Equity | US | QQQ |
| `na_equity_value` | Equity | US | IWD |
| `na_equity_small` | Equity | US | IWM |
| `dm_europe_equity` | Equity | Europe | VGK |
| `dm_asia_equity` | Equity | Asia | EWJ |
| `em_equity` | Equity | EM | EEM |
| `fi_us_aggregate` | Fixed Income | US | AGG |
| `fi_us_treasury` | Fixed Income | US | IEF |
| `fi_us_tips` | Fixed Income | US | TIP |
| `fi_us_high_yield` | Fixed Income | US | HYG |
| `fi_em_debt` | Fixed Income | EM | EMB |
| `alt_real_estate` | Alternatives | Global | VNQ |
| `alt_commodities` | Alternatives | Global | DJP |
| `alt_gold` | Alternatives | Global | GLD |
| `cash` | Cash | US | SHV |

### 4.3 Regime-Tilted Allocation

`compute_regime_tilted_weights()` applies regime-based tilts to the neutral strategic allocation:

**Tilt direction by regime:**

| Regime | Equity | Fixed Income | Alternatives | Cash |
|--------|--------|-------------|-------------|------|
| RISK_ON | +30% of room to max | -15% toward min | +10% | -20% |
| RISK_OFF | -25% toward min | +25% to max | +5% | +15% |
| INFLATION | -10% | -20% (nominal bonds suffer) | +30% (real assets) | +10% |
| CRISIS | -50% toward min | +20% | -10% | +40% |

**"Room" formula:**
```
if tilt_factor >= 0:  room = max_weight - target_weight
if tilt_factor <  0:  room = target_weight - min_weight
delta = tilt_factor * room
proposed = clamp(target + delta, min_weight, max_weight)
```

**Renormalization:** Residual from rounding is absorbed first by cash, then proportionally across all blocks.

### 4.4 Regional Tilts (Equity Only)

For equity blocks, regional macro scores (0-100) create an additional tilt:

```
score_deviation = regional_score - 50  (neutral = 50)
regional_delta = score_deviation * 0.003 * room
```

Example: US score = 65, room = 0.08 → `+0.36%` additional tilt to US equity blocks.

---

## 5. Stage 3 — Universe Loading

**Function:** `_load_universe_funds()` in `model_portfolios.py`

### 5.1 Approved Universe Query

The optimizer only considers funds that are:
1. `Instrument.is_active = True`
2. `InstrumentOrg.block_id IS NOT NULL` (assigned to a strategic block)
3. `UniverseApproval.is_current = True AND decision = 'approved'`

**Join chain:**
```sql
Instrument
  JOIN instruments_org ON instrument_id (org-scoped via RLS)
  JOIN universe_approvals ON instrument_id (is_current = true, decision = 'approved')
  LEFT JOIN fund_risk_metrics ON instrument_id (latest calc_date)
```

### 5.2 Output

List of dicts per fund:

```python
{
    "instrument_id": str(UUID),
    "fund_name": str,
    "block_id": str,          # from InstrumentOrg
    "manager_score": float,   # from FundRiskMetrics (composite 0-100)
    "instrument_type": str,   # mutual_fund, etf, bdc, etc.
}
```

### 5.3 Fund Scoring Model

**Service:** `quant_engine/scoring_service.py`

The `manager_score` (0-100) is a composite of 6 components:

| Component | Weight | Normalization Range | Source |
|-----------|--------|-------------------|--------|
| Return consistency | 0.20 | [-20%, +40%] → [0, 100] | `fund_risk_metrics.return_1y` |
| Risk-adjusted return | 0.25 | [-1.0, 3.0] Sharpe → [0, 100] | `fund_risk_metrics.sharpe_1y` |
| Drawdown control | 0.20 | [-50%, 0%] → [0, 100] | `fund_risk_metrics.max_drawdown_1y` |
| Information ratio | 0.15 | [-1.0, 2.0] → [0, 100] | `fund_risk_metrics.information_ratio_1y` |
| Flows momentum | 0.10 | [0, 100] direct | `fund_risk_metrics.blended_momentum_score` (combinacao de RSI-14, Bollinger position, NAV momentum e flow momentum — pre-computados pelo risk_calc worker) |
| Fee efficiency | 0.10 | `max(0, 100 - ER_human_pct * 50)` onde ER_human_pct = expense_ratio_pct × 100 | `instrument.attributes.expense_ratio_pct` (0% ER → 100, 1% → 50, 2% → 0, None → 50 neutral) |

**Optional component:** `insider_sentiment` (opt-in via config weight > 0).

Pre-computed by the `risk_calc` worker (daily at 03:00 UTC).

### 5.4 Tiered Due Diligence — Quantitative Fast-Track

Approved Universe entries can reach `UniverseApproval.decision = 'approved'` via two paths:

| Path | Trigger | Eligible types | Audit | DD Report required |
|---|---|---|---|---|
| **Full DD** | `POST /universe/funds/{id}/approve` after a completed `dd_reports` chapter set | All instrument types (incl. private, BDC, hedge funds) | `universe.approve` | Yes (`analysis_report_id` set) |
| **Fast-Track** | `POST /screener/fast-track-approval` (bulk, list of `instrument_ids`) | ETFs, Mutual Funds, Money Market, UCITS | `universe.fast_track_approval` | No (`analysis_report_id = NULL`) |

**Fast-Track endpoint** ([backend/app/domains/wealth/routes/screener.py](backend/app/domains/wealth/routes/screener.py)):

- **Eligibility check** reads `Instrument.attributes` JSONB:
  - `attributes.sec_universe ∈ {registered_us, etf, money_market}` → eligible
  - `attributes.source == 'esma'` → UCITS → eligible
  - BDC, private (`source == 'sec_manager'`), closed-end → **rejected** with reason
- **Persistence** (per eligible instrument):
  1. Mark previous `UniverseApproval` row `is_current = False`
  2. Insert `UniverseApproval(decision='approved', rationale='Auto-approved via Quantitative Fast-Track', is_current=True, analysis_report_id=NULL)`
  3. `UPDATE InstrumentOrg SET approval_status='approved'`
- **Audit:** single `universe.fast_track_approval` event per batch (lists all approved IDs)
- **Auth:** `INVESTMENT_TEAM` or `ADMIN`. Self-approval prevention does **not** apply (system-grade quant check, not human discretion).
- **Batch limit:** 100 instruments per request.

**Why this matters for portfolio construction:** the fast-track rationale is the discriminator used by the eviction worker (§5.5) to distinguish quant-only approvals from human-vetted DD approvals. `_load_universe_funds()` itself is unaware of the path — it only consumes the canonical `(is_current=True, decision='approved')` predicate.

### 5.5 Automated Eviction (Fast-Track Governance)

Funds approved via Fast-Track bypass qualitative review, so they require **continuous quantitative governance**. A daily worker revokes any fast-tracked approval whose composite `manager_score` deteriorates below the eviction threshold.

**Service:** `vertical_engines/wealth/asset_universe/eviction_service.py` — `process_fast_track_evictions(db, org_id) -> int`

**Eviction state machine** (per instrument):

```
fast_track_approved
        │
        │  daily sweep: latest manager_score < EVICTION_SCORE_THRESHOLD (40.0)
        ▼
1. UniverseApproval (old).is_current  = False
2. UniverseApproval (new).decision    = 'revoked'
   .rationale  = 'Automated eviction: manager_score dropped below 40.0'
   .is_current = True
   .decided_by = 'system:fast_track_eviction'
3. InstrumentOrg.approval_status      = 'revoked'
4. AuditEvent  action='universe.automated_eviction'
5. StrategyDriftAlert(severity='high', status='active',
                     metric_details.trigger='fast_track_eviction')
```

**Key invariants:**

| Invariant | Rationale |
|---|---|
| `EVICTION_SCORE_THRESHOLD = 40.0` (strict `<`) | Constant in `eviction_service.py`; conservative — boundary funds (40.0 exactly) survive. |
| Identification by `rationale ILIKE '%Fast-Track%'` | Mirrors the literal string written by the fast-track endpoint. Full-DD approvals are immune to automated eviction. |
| `fund_risk_metrics` joined globally (no `organization_id` filter) | Table is GLOBAL per CLAUDE.md; latest score per instrument selected via `DISTINCT ON (instrument_id) ORDER BY calc_date DESC`. |
| Funds with **no** score row are skipped | Eviction must be evidence-based — newly fast-tracked funds get a grace period until `global_risk_metrics` populates a score. |
| Per-instrument try/except inside the org sweep | A failure on one fund logs and continues; never aborts the org. |
| Per-org isolation (one transaction per org) | A poisoned tenant cannot block the rest of the fleet. |
| `UniverseDecision.revoked` enum value | Added 2026-04-06. Distinct from `rejected` (human pre-approval refusal). |

**Downstream impact on construction:**

`_load_universe_funds()` filters on `decision = 'approved'`, so a revoked fund is **immediately invisible** to the optimizer on the next `POST /model-portfolios/{id}/construct` call. Portfolio Managers are notified via the `StrategyDriftAlert` row (severity `high`) which surfaces in the monitoring UI. Existing active portfolios that hold the revoked fund continue to run, but the **next rebalance** will exclude it — that is by design: drift toward the new universe is the rebalancing trigger, not a forced sell.

---

## 6. Stage 4 — Statistical Inputs

**Function:** `compute_fund_level_inputs()` in `quant_queries.py`

Transforms raw NAV time series into the covariance matrix, expected returns, and higher moments required by the optimizer.

### 6.1 Returns Fetching

```sql
SELECT instrument_id, nav_date, return_1d
FROM nav_timeseries
WHERE instrument_id IN (:fund_ids)
  AND nav_date >= :date_floor        -- lookback_days from today
  AND return_1d IS NOT NULL
```

**Return type preference:** Log returns → arithmetic returns (never mixed).
**Date alignment:** Intersection of all fund observation dates. Minimum 120 trading days required.

### 6.2 Covariance Matrix

**Step 1: Daily covariance** from the returns matrix `R` (T × N):

```
Method A (default): Ledoit-Wolf shrinkage estimator (sklearn)
Method B (optional): Sample covariance: Σ_daily = cov(R)
```

**Step 2: Annualization:**
```
Σ_annual = Σ_daily × 252
```

**Step 3: PSD adjustment** (guarantees positive semi-definiteness):
```python
eigvals, eigvecs = np.linalg.eigh(Σ_annual)
if min(eigvals) < -1e-10:
    eigvals = np.maximum(eigvals, 1e-10)
    Σ_annual = eigvecs @ np.diag(eigvals) @ eigvecs.T
```

### 6.3 Regime-Conditioned Covariance (Optional)

If regime probabilities are available (from `PortfolioSnapshot.regime_probs` or VIX proxy):

```
current_regime_prob = mean(regime_probs[-21:])

if current_regime_prob > 0.6:   # Stress regime
    Use short window (63d) with observation weighting by regime probability
    Σ = (R_demeaned.T * weights) @ R_demeaned / (Σweights - 1)
else:                            # Normal regime
    Use long window (252d) standard estimation
```

### 6.4 Expected Returns

**Base case:** Annualized mean of daily returns:
```
μ_annual = mean(R, axis=0) × 252
```

**Black-Litterman posterior (if IC views exist):**

```python
compute_bl_returns(
    sigma=Σ,           # N×N covariance
    w_market=w_mkt,    # N-vector market weights (from strategic allocation)
    views=views,       # IC views from PortfolioView table
    risk_aversion=2.5, # λ
    tau=0.05,          # uncertainty on prior
) -> np.ndarray       # N-vector posterior expected returns
```

**BL formula:**
```
π = λ Σ w_mkt                           (equilibrium returns)
M = (τΣ)⁻¹ + Pᵀ Ω⁻¹ P                 (precision matrix)
μ_BL = M⁻¹ ((τΣ)⁻¹ π + Pᵀ Ω⁻¹ Q)     (posterior)
```

Where:
- `P` (K × N): view pick matrix — each row selects asset(s) involved in a view
- `Q` (K,): view return expectations
- `Ω` (K × K): view uncertainty diagonal (Idzorek method: `ω_k = pₖᵀ τΣ pₖ / confidence`)

**View types from `PortfolioView` table:**
- **Absolute:** "Fund X will return 8%" → `P[k, asset_idx] = 1`
- **Relative:** "Fund X will outperform Fund Y by 2%" → `P[k, long_idx] = +1, P[k, short_idx] = -1`

### 6.5 Fee Adjustment (Optional)

If `config["fee_adjustment"]["enabled"]`:
```
μ[i] -= expense_ratio_pct[i] / 100
```

### 6.6 Higher Moments

For Cornish-Fisher CVaR:
```
skewness = scipy.stats.skew(R, axis=0)         # (N,)
excess_kurtosis = scipy.stats.kurtosis(R, axis=0, fisher=True)  # (N,)
```

### 6.7 Output

```python
(
    Σ_annual,          # np.ndarray (N × N) — annualized covariance
    μ,                 # dict[str, float] — {fund_id → annualized return}
    available_ids,     # list[str] — fund IDs with sufficient data
    skewness,          # np.ndarray (N,)
    excess_kurtosis,   # np.ndarray (N,)
)
```

---

## 7. Stage 5 — CLARABEL Optimizer Cascade

**Function:** `optimize_fund_portfolio()` in `optimizer_service.py`

### 7.1 Function Signature

```python
async def optimize_fund_portfolio(
    fund_ids: list[str],
    fund_blocks: dict[str, str],           # fund_id → block_id
    expected_returns: dict[str, float],     # fund_id → μ
    cov_matrix: np.ndarray,                # N × N
    constraints: ProfileConstraints,
    risk_free_rate: float = 0.04,
    skewness: np.ndarray | None = None,
    excess_kurtosis: np.ndarray | None = None,
    current_weights: np.ndarray | None = None,
    turnover_cost: float = 0.0,
    robust: bool = False,
    uncertainty_level: float = 0.5,
    regime_cvar_multiplier: float = 1.0,
) -> FundOptimizationResult
```

### 7.2 Constraint Architecture

All phases share the same base constraints:

```
1. Fully invested:     Σ wᵢ = 1
2. Long-only:          wᵢ ≥ 0  ∀i
3. Concentration:      wᵢ ≤ max_single_fund_weight  ∀i
4. Block bounds:       min_b ≤ Σᵢ∈block(b) wᵢ ≤ max_b  ∀b
```

**Partial universe handling:** If the approved universe doesn't cover all strategic blocks, the orchestrator rescales `min_weight` / `max_weight` proportionally so constraints sum to 1.0 and remain feasible.

### 7.3 Four-Phase Cascade

The optimizer attempts each phase in sequence. If a phase produces a CVaR-compliant solution, it returns immediately. Otherwise, it falls through to the next phase.

#### Phase 1: Max Risk-Adjusted Return

```
maximize   μᵀw - λ wᵀΣw        (λ = 2.0)
subject to base constraints + turnover penalty
```

**Turnover penalty** (if `current_weights` provided):
```
maximize   μᵀw - λ wᵀΣw - τ Σ|wᵢ - wᵢ_current|
```
Implemented via L1 slack variables `t`: `t ≥ w - w_current`, `t ≥ w_current - w`.

**CVaR post-check:** Cornish-Fisher parametric CVaR evaluated on the result. If `CVaR ≥ effective_limit` → return `status = "optimal"`. Otherwise → Phase 1.5 or Phase 2.

#### Phase 1.5: Robust Optimization (SOCP)

Only runs if `robust=True` and Phase 1 CVaR violated.

```
maximize   μᵀw - κ ‖Lᵀw‖₂ - λ wᵀΣw
subject to base constraints
```

Where:
- `L` = Cholesky factor of Σ (with eigenvalue floor for near-singular matrices)
- `κ = uncertainty_level × √N` (scales ellipsoidal uncertainty set)
- `‖Lᵀw‖₂` = Second-Order Cone constraint — penalizes weights sensitive to covariance perturbation

If CVaR now passes → return `status = "optimal:robust"`.

#### Phase 2: Variance-Cap CVaR Enforcement

Derives a maximum allowable variance from the CVaR limit using the normal approximation:

```
CVaR_α ≈ μ + σ × (-z_α + φ(z_α)/α)
       = μ + σ × 3.71                  (for α = 0.05)

∴ σ_max = |CVaR_limit| / 3.71
  σ²_max = (|CVaR_limit| / 3.71)²
```

```
maximize   μᵀw
subject to wᵀΣw ≤ σ²_max
           base constraints
```

If solved → return `status = "optimal:cvar_constrained"`.

#### Phase 3: Minimum Variance Fallback

```
minimize   wᵀΣw
subject to base constraints
```

Finds the safest possible portfolio within block bounds. Ignores expected return entirely.

If solved → return `status = "optimal:min_variance_fallback"`.

#### Heuristic Fallback

If all phases fail (block constraints incompatible with CVaR limit), returns the Phase 1 result with `status = "optimal:cvar_violated"`.

### 7.4 Solver Cascade

Each phase uses CLARABEL as primary solver with SCS as fallback:

```python
try:
    prob.solve(solver=cp.CLARABEL)
    if prob.status not in ("optimal", "optimal_inaccurate"):
        prob.solve(solver=cp.SCS, eps=1e-5, max_iters=10000)
except cp.SolverError:
    prob.solve(solver=cp.SCS, eps=1e-5, max_iters=10000)
```

### 7.5 CVaR Computation — Cornish-Fisher

**Function:** `parametric_cvar_cf()` in `optimizer_service.py`

```python
def parametric_cvar_cf(
    weights, mu, cov, skewness, excess_kurtosis, alpha=0.05
) -> float:  # positive loss value
```

**Algorithm:**
```
μ_p = wᵀμ                              # portfolio expected return
σ_p = √(wᵀΣw)                         # portfolio std dev
γ₁ = wᵀskewness                        # portfolio skewness
γ₂ = wᵀexcess_kurtosis                 # portfolio excess kurtosis

z = Φ⁻¹(α)                             # ≈ -1.645 for α=0.05

# Cornish-Fisher expansion
z_cf = z + (z²-1)γ₁/6 + (z³-3z)γ₂/24 - (2z³-5z)γ₁²/36

# CVaR
φ(z_cf) = standard normal PDF at z_cf
CVaR = -(μ_p + σ_p × z_cf) + σ_p × φ(z_cf) / α
```

**Validity bounds:** |γ₁| > 2.5 or |γ₂| > 12 → CF expansion unreliable. The construction advisor (Stage 7) uses historical simulation CVaR instead.

**GARCH fallback behavior:** `garch_service.py` returns `None` if `arch` library not installed or if fewer than 100 observations. Returns `GarchResult(converged=False)` if model fails to converge — upstream computation falls back to sample volatility (`volatility_1y`). This graceful degradation ensures the optimizer always has volatility estimates even when GARCH is unavailable.

### 7.6 Output: FundOptimizationResult

```python
@dataclass
class FundOptimizationResult:
    weights: dict[str, float]        # fund_id → weight
    block_weights: dict[str, float]  # block_id → aggregate weight
    expected_return: float           # annualized
    portfolio_volatility: float      # annualized
    sharpe_ratio: float              # (ret - rf) / vol
    cvar_95: float | None            # negative = loss
    cvar_limit: float | None
    cvar_within_limit: bool
    status: str                      # "optimal", "optimal:robust", etc.
    solver_info: str | None          # "CLARABEL", "SCS"
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `optimal` | Phase 1 succeeded, CVaR within limit |
| `optimal:robust` | Phase 1.5 SOCP succeeded |
| `optimal:cvar_constrained` | Phase 2 variance-cap succeeded |
| `optimal:min_variance_fallback` | Phase 3 min-variance |
| `optimal:cvar_violated` | All phases failed, Phase 1 result returned |

---

## 8. Stage 6 — Portfolio Composition

**Function:** `construct_from_optimizer()` in `portfolio_builder.py`

### 8.1 Primary Path (Optimizer Success)

Converts optimizer output to the `fund_selection_schema` JSONB:

```python
def construct_from_optimizer(
    profile: str,
    fund_weights: dict[str, float],
    fund_info: dict[str, dict],
    optimization_meta: OptimizationMeta,
) -> PortfolioComposition
```

1. Filter weights < 1e-6 (near-zero)
2. Look up fund metadata (name, block_id, score)
3. Sort by (block_id, weight descending)
4. Build `PortfolioComposition(profile, funds, total_weight, optimization)`

### 8.2 Heuristic Fallback

If optimizer fails (< 2 funds with data, < 120 aligned days):

```python
def construct(
    profile: str,
    universe_funds: list[dict],
    block_weights: dict[str, float],
) -> PortfolioComposition
```

1. Group funds by `block_id`
2. Select top 3 per block by `manager_score`
3. Allocate within block proportionally to score: `w_fund = w_block × (score / Σscores)`
4. Normalize all weights to sum to 1.0

### 8.3 PCA Factor Decomposition (Optional, Best-Effort)

**Function:** `decompose_factors()` in `factor_model_service.py`

After optimizer success, decomposes the portfolio into latent factors:

```python
def decompose_factors(
    returns_matrix: np.ndarray,     # T × N
    macro_proxies: dict | None,     # VIX, DGS10, etc.
    portfolio_weights: np.ndarray,  # N-vector
    n_factors: int = 3,
) -> FactorModelResult
```

- SVD-based PCA extraction
- Factor labeling via correlation with macro proxies (VIX, rates, etc.)
- Output: `{factor_label: portfolio_exposure}` stored in `optimization.factor_exposures`
- Requires >= 60 observations, >= 3 funds

### 8.4 Day-0 Snapshot

After composition is built, `_create_day0_snapshot()` persists a `PortfolioSnapshot`:

```python
PortfolioSnapshot(
    profile=portfolio.profile,
    snapshot_date=date.today(),
    weights=block_weights,           # {block_id → float}
    fund_selection=fund_selection,   # Full JSONB
    cvar_current=Decimal(cvar_95),
    cvar_limit=Decimal(cvar_limit),
    cvar_utilized_pct=abs(cvar/limit) * 100,
    trigger_status="ok" | "maintenance" | "urgent",
    consecutive_breach_days=0,
)
```

### 8.5 fund_selection_schema Structure

Stored as JSONB on `ModelPortfolio.fund_selection_schema`:

```json
{
  "profile": "moderate",
  "total_weight": 1.0,
  "funds": [
    {
      "instrument_id": "uuid-string",
      "fund_name": "Vanguard Total Stock Market",
      "block_id": "na_equity_large",
      "weight": 0.25,
      "score": 78.5,
      "instrument_type": "mutual_fund"
    }
  ],
  "optimization": {
    "expected_return": 0.082,
    "portfolio_volatility": 0.142,
    "sharpe_ratio": 0.296,
    "cvar_95": -0.052,
    "cvar_limit": -0.06,
    "cvar_within_limit": true,
    "solver": "CLARABEL",
    "status": "optimal",
    "factor_exposures": {
      "VIX_inv": 0.45,
      "DGS10": -0.22,
      "factor_3": 0.08
    }
  }
}
```

---

## 9. Stage 7 — Construction Advisor

**Service:** `vertical_engines/wealth/model_portfolio/construction_advisor.py`
**I/O Layer:** `app/domains/wealth/services/candidate_screener.py`

When the optimizer returns `cvar_within_limit: false`, the frontend auto-calls the construction advisor endpoint. This diagnoses *why* CVaR failed and recommends *what to add*.

### 9.1 Endpoint

```
POST /api/v1/model-portfolios/{portfolio_id}/construction-advice
```

**Redis cache:** SHA-256 of `(portfolio_id, updated_at, date.today())`, 10-minute TTL, fail-open.

### 9.2 Pipeline

```
1. Block Gap Analysis
   Input:  optimizer block_weights + strategic_targets
   Output: which blocks are uncovered/underweight, by how much

2. Candidate Discovery (I/O)
   Input:  gap block IDs
   Output: up to 20 funds per block from instruments_universe
           (via strategy_label → block_id mapping)

3. Data Fetching (parallel asyncio.gather)
   - Portfolio daily returns (T × N) + weights
   - Candidate daily returns (date floor, min 126 days)
   - Portfolio CUSIP holdings (N-PORT)
   - Candidate CUSIP holdings (N-PORT)

4. Candidate Ranking (CPU, in thread)
   Score = 0.40 × (1 - norm_vol)
         + 0.35 × (1 - norm_corr)
         + 0.15 × (1 - overlap_pct)
         + 0.10 × norm_sharpe

5. CVaR Impact Projection (CPU, in thread)
   Historical simulation CVaR per candidate
   (not CF — reliable at extreme levels)

6. Minimum Viable Set Search (CPU, in thread)
   Brute-force if ≤15 candidates, greedy+swap otherwise

7. Alternative Profile Check
   Compare current CVaR against other profile limits
```

### 9.3 Block Gap Analysis

```python
def analyze_block_gaps(
    block_weights: dict[str, float],
    strategic_targets: dict[str, float],
    block_metadata: dict[str, BlockInfo],
    max_gaps: int = 5,
) -> CoverageAnalysis
```

- A block is "covered" if `current_weight > 0`
- Gap = `target - current` for each block
- Priority sort by `gap_weight × diversification_value`:
  - `fixed_income = 4.0`, `alternatives = 3.0`, `cash = 2.0`, `equity = 1.0`
- Gaps < 0.5% are ignored (threshold)

### 9.4 Strategy-to-Block Mapping

**File:** `vertical_engines/wealth/model_portfolio/block_mapping.py`

Hand-coded mapping of ~37 strategy labels to 16 allocation blocks. Used to discover candidates from the global `instruments_universe` catalog when querying for gap blocks.

```python
blocks_for_strategy_label("Large Blend")     → ["na_equity_large"]
blocks_for_strategy_label("Fixed Income")    → ["fi_us_aggregate"]
strategy_labels_for_block("fi_us_aggregate") → ["Fixed Income", "Intermediate Core Bond", ...]
```

### 9.5 Historical Simulation CVaR

**Why not Cornish-Fisher?** At extreme CVaR levels (e.g., -84% for a concentrated equity portfolio), the CF expansion diverges when |skewness| > 2.5 or |kurtosis| > 12. The advisor evaluates only ~15 candidates — historical simulation is fast enough and always correct.

```python
def project_cvar_historical(
    portfolio_daily_returns: np.ndarray,  # (T, N)
    candidate_returns: np.ndarray,        # (T,)
    current_weights: np.ndarray,          # (N,)
    candidate_target_weight: float,
    alpha: float = 0.05,
) -> float | None:
```

**Algorithm:**
```
scaled_weights = current_weights × (1 - c_weight)
new_weights = [scaled_weights..., c_weight]
combined_returns = [portfolio_daily_returns | candidate_returns]  # (T, N+1)
portfolio_returns = combined_returns @ new_weights                # (T,)
sorted = sort(portfolio_returns)
cutoff = max(int(T × α), 1)
daily_cvar = -mean(sorted[:cutoff])
annual_cvar = daily_cvar × √252
return -annual_cvar  # negative (loss convention)
```

### 9.6 Minimum Viable Set

```python
def find_minimum_viable_set(
    candidates, portfolio_daily_returns, candidate_returns_map,
    current_weights, strategic_targets, cvar_limit,
) -> MinimumViableSet | None
```

**Brute-force (≤ 15 candidates):**
- Enumerate `C(n, k)` for k = 1..5
- `C(15,1) + C(15,2) + C(15,3) + C(15,4) + C(15,5) = 4,943` evaluations
- Each evaluation: one `historical_cvar()` call (~microseconds)
- Total: < 50ms

**Greedy + swap (> 15 candidates):**
1. Iteratively pick best single fund (most CVaR improvement)
2. Stop when CVaR passes limit or k = 5
3. Swap pass: try replacing each selected fund with each unused candidate
4. Return best set found

**Why not pure greedy?** CVaR minimization is proven non-submodular (Wilder, 2018). Greedy has no (1-1/e) approximation guarantee. Brute-force is trivial for small candidate sets.

### 9.7 Response Schema

```json
{
  "portfolio_id": "uuid",
  "profile": "moderate",
  "current_cvar_95": -0.8405,
  "cvar_limit": -0.06,
  "cvar_gap": -0.7805,
  "coverage": {
    "total_blocks": 14,
    "covered_blocks": 2,
    "covered_pct": 0.143,
    "block_gaps": [
      {
        "block_id": "fi_us_aggregate",
        "display_name": "US Aggregate Bond",
        "asset_class": "fixed_income",
        "target_weight": 0.20,
        "current_weight": 0.0,
        "gap_weight": 0.20,
        "priority": 1,
        "reason": "Largest weight gap, negative equity correlation"
      }
    ]
  },
  "candidates": [
    {
      "block_id": "fi_us_aggregate",
      "instrument_id": "uuid",
      "name": "Vanguard Total Bond Market",
      "ticker": "VBTLX",
      "volatility_1y": 0.042,
      "correlation_with_portfolio": -0.15,
      "overlap_pct": 0.0,
      "projected_cvar_95": -0.18,
      "cvar_improvement": 0.66,
      "in_universe": false,
      "external_id": "CIK-123",
      "has_holdings_data": true
    }
  ],
  "minimum_viable_set": {
    "funds": ["uuid-1", "uuid-2"],
    "projected_cvar_95": -0.052,
    "projected_within_limit": true,
    "blocks_filled": ["fi_us_aggregate", "alt_gold"],
    "search_method": "brute_force"
  },
  "alternative_profiles": [
    {
      "profile": "growth",
      "cvar_limit": -0.12,
      "current_cvar_would_pass": true
    }
  ],
  "projected_cvar_is_heuristic": true
}
```

### 9.8 Frontend UX Flow

When CVaR fails:

1. Construction Result section always shows metrics (return, vol, Sharpe, CVaR, status)
2. Block allocation bars show weight distribution per block
3. **Advisor panel** appears below with:
   - Coverage bar (X% blocks covered)
   - Block-grouped accordion table with ranked candidates per gap
   - Per-candidate: vol, correlation, overlap, projected CVaR, "Add" button
   - Sticky footer: "Add [MVS funds] & Re-construct" (batch action)
   - Alternative profile suggestion (if current CVaR passes a different profile)

**Actions:**
- **Single "Add":** Import fund if not in universe → assign to block → strike-through row
- **"Add All & Re-construct":** ConsequenceDialog → import batch → auto-triggers `POST /construct`
- After re-construct, if CVaR now passes → "Activate" button becomes enabled

---

## 10. Stage 8 — Validation (Backtest + Stress)

User-triggered validation before activation.

### 10.1 Walk-Forward Backtest

```
POST /api/v1/model-portfolios/{portfolio_id}/backtest
```

Walk-forward cross-validation with expanding window. Each fold:
- Train on [0, t]
- Test on [t, t+252]
- Compute Sharpe, CVaR, max drawdown per fold

**Output:** `BacktestResult` with `mean_sharpe`, `std_sharpe`, `positive_folds/total_folds`, per-fold metrics.

### 10.2 Historical Stress Scenarios

```
POST /api/v1/model-portfolios/{portfolio_id}/stress
```

Replays 4 historical scenarios:

| Scenario | Period | Typical Equity Impact |
|----------|--------|----------------------|
| GFC 2008 | 2007-10 to 2009-03 | -55% |
| COVID 2020 | 2020-02 to 2020-03 | -34% |
| Taper 2013 | 2013-05 to 2013-09 | -6% |
| Rate Shock | 2022-01 to 2022-10 | -25% |

**Output:** Per-scenario `portfolio_return`, `max_drawdown`, `recovery_days`.

### 10.3 Parametric Stress

```
POST /api/v1/model-portfolios/{portfolio_id}/stress-test
```

User-defined block-level shocks (or preset scenarios). Computes NAV impact, CVaR under stress, per-block impact, worst/best block.

```json
{
  "scenario_name": "custom",
  "shocks": {
    "na_equity_large": -0.38,
    "fi_us_aggregate": 0.05,
    "alt_gold": 0.15
  }
}
```

---

## 11. Stage 9 — Activation

```
POST /api/v1/model-portfolios/{portfolio_id}/activate
```

Transitions portfolio from `draft` → `active`.

**Preconditions:**
1. `fund_selection_schema` exists with funds
2. `optimization.cvar_within_limit == true`

**Guard:** Returns HTTP 409 CONFLICT if CVaR exceeds limit.

**Frontend — Activation Confirmation:**

- "Activate" button visible only for draft portfolios. Disabled with tooltip "CVaR exceeds profile limit" when `cvar_within_limit` is false.
- Clicking "Activate" opens a `ConsequenceDialog` (not a raw confirm) with:
  - Impact summary: "This portfolio will move from Draft to Active and become available for monitoring and rebalancing. This action cannot be reversed."
  - Metadata grid: Profile, Solver, CVaR 95%, Sharpe, Funds count, Status
  - Required rationale (20-char minimum) for audit trail
  - Action button: "Activate Portfolio" (primary color, NOT red — activation is irreversible but not destructive)
- Double-submission prevention: button disabled on click + loading state; backend state machine rejects duplicates.

**Frontend — Wizard CVaR Guard Fix:**

The creation wizard (Step 5) uses `POST /activate` — NOT `PATCH` with `status: "approved"`. The PATCH endpoint has no CVaR guard and would bypass the safety check. The wizard flow is:
1. `PATCH /model-portfolios/{id}` — metadata only (display_name, inception_date, NO status field)
2. `POST /model-portfolios/{id}/activate` — enforces CVaR guard, returns 409 if limit exceeded
3. Batch activation: single `ConsequenceDialog` for all 3 profiles (avoids confirmation fatigue)

### Portfolio Status Lifecycle

```
draft ──── construct ──── (cvar passes) ──── activate ──── active
  │                            │
  │                     (cvar fails)
  │                            │
  │                      advisor panel
  │                      add funds
  │                      re-construct ────── (cvar passes) ──── activate
```

---

## 12. Stage 10 — Monitoring

After activation, background workers monitor the portfolio daily.

### 12.1 Risk Calc Worker (daily 03:00 UTC)

Lock ID: `900_007`. Per-fund metrics persisted to `fund_risk_metrics`:
- Volatility (1Y, GARCH), CVaR 95% (conditional)
- Sharpe, Sortino, Information Ratio
- Max drawdown
- Momentum: RSI-14, Bollinger position, OBV flow, blended momentum score
- Manager composite score (6-component weighted)

### 12.2 Portfolio Eval Worker (daily)

Lock ID: `900_008`. Per-portfolio:
- Recomputes CVaR utilization against profile limit
- Updates `consecutive_breach_days`
- Sets `trigger_status`: `ok` / `maintenance` / `urgent`
- Persists `PortfolioSnapshot`

### 12.3 Drift Check Worker (daily)

Lock ID: `42`. Detects strategy drift via DTW (Dynamic Time Warping):
- Compares current block weights against strategic targets
- Generates `strategy_drift_alerts` if drift exceeds threshold

### 12.4 NAV Synthesizer Worker (daily)

Lock ID: `900_030`. Computes synthetic portfolio NAV:
- Weights × NAV per fund → portfolio NAV
- Persisted to `model_portfolio_nav` hypertable (1-month chunks)

### 12.5 Fast-Track Eviction Worker (daily)

**Lock ID:** `900_009` (global, non-blocking advisory).
**Worker:** [backend/app/domains/wealth/workers/fast_track_eviction.py](backend/app/domains/wealth/workers/fast_track_eviction.py)
**Service:** [backend/vertical_engines/wealth/asset_universe/eviction_service.py](backend/vertical_engines/wealth/asset_universe/eviction_service.py)
**Dispatch:** `python -m app.workers.cli fast_track_eviction` (registered as `global` scope, `_LIGHT` 5-min timeout).

Sweeps every active organization (discovered via `vertical_config_overrides ∪ tenant_assets`) and revokes fast-tracked Universe approvals whose latest `manager_score` is **strictly below 40.0**. See §5.5 for the full state machine.

**Scheduling constraint:** Must run **after** `global_risk_metrics` (lock `900_071`) so the latest scores are persisted before the eviction sweep reads them. Recommended cron order:

```
03:00 UTC — global_risk_metrics  (lock 900_071)
03:30 UTC — risk_calc            (lock 900_007, per-org DTW drift)
04:00 UTC — fast_track_eviction  (lock 900_009)  ← reads scores written above
```

**Per-org isolation:** each org runs in its own `AsyncSession` with its own `set_rls_context()` and its own commit/rollback boundary. A failure on one org increments `orgs_failed` and is logged with `logger.exception(...)`, but the sweep continues.

**Observability:** structured logs via `structlog` — `fast_track_eviction.start`, `.org_count`, `.scan`, `.revoked`, `.org_failed`, `.summary`. The summary payload includes `orgs_scanned`, `orgs_failed`, `total_revoked`, and a `per_org` map.

---

## 13. Data Model

### 13.1 Core Tables

| Table | Scope | Purpose |
|-------|-------|---------|
| `model_portfolios` | Org (RLS) | Portfolio definition + fund_selection_schema JSONB |
| `strategic_allocation` | Org (RLS) | Per-profile, per-block weight targets |
| `allocation_blocks` | Global | Block taxonomy (16 blocks) |
| `portfolio_snapshots` | Org (RLS) | Daily CVaR, weights, trigger status |
| `portfolio_views` | Org (RLS) | IC views for Black-Litterman |
| `tactical_positions` | Org (RLS) | Short-term tilts on top of strategic base |

### 13.2 Fund Data Tables

| Table | Scope | Purpose |
|-------|-------|---------|
| `instruments_universe` | Global | Fund catalog (5,400+ active instruments) |
| `instruments_org` | Org (RLS) | Org-scoped fund selection (block_id, approval_status) |
| `nav_timeseries` | Global | Daily NAV + returns (market data) |
| `fund_risk_metrics` | Org (RLS) | Pre-computed risk metrics per fund |
| `model_portfolio_nav` | Org (RLS) | Synthetic portfolio NAV (hypertable) |

### 13.3 Market Data Tables

| Table | Scope | Purpose |
|-------|-------|---------|
| `macro_data` | Global | FRED series (VIX, rates, CPI, Case-Shiller) |
| `treasury_data` | Global | US Treasury rates, debt, auctions |
| `benchmark_nav` | Global | Benchmark index NAV (SPY, AGG, etc.) |
| `sec_nport_holdings` | Global | Quarterly fund holdings (for overlap) |

---

## 14. API Endpoints

All endpoints require Clerk JWT authentication. IC role (`investment_team`, `director`, `admin`) required for mutation endpoints.

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| POST | `/model-portfolios` | Create portfolio | IC |
| GET | `/model-portfolios` | List portfolios | Any |
| GET | `/model-portfolios/{id}` | Get portfolio detail | Any |
| POST | `/model-portfolios/{id}/construct` | Run optimizer | IC |
| POST | `/model-portfolios/{id}/construction-advice` | Get advisor recommendations | IC |
| POST | `/model-portfolios/{id}/activate` | Transition draft → active | IC |
| POST | `/model-portfolios/{id}/backtest` | Run walk-forward backtest | IC |
| POST | `/model-portfolios/{id}/stress` | Run historical stress scenarios | IC |
| POST | `/model-portfolios/{id}/stress-test` | Run parametric stress test | IC |
| GET | `/model-portfolios/{id}/overlap` | Holdings overlap analysis | Any |
| GET | `/model-portfolios/{id}/track-record` | Get backtest + stress results | Any |
| GET | `/model-portfolios/{id}/views` | List IC views | Any |
| POST | `/model-portfolios/{id}/views` | Create IC view (BL) | IC |

### 14.1 Universe-feeding endpoints

These do not live under `/model-portfolios` but they directly mutate the set of funds returned by `_load_universe_funds()`.

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| POST | `/universe/funds/{instrument_id}/approve` | Full-DD approval (requires DD report) | IC |
| POST | `/universe/funds/{instrument_id}/reject` | Reject with rationale | IC |
| POST | `/screener/fast-track-approval` | Bulk quant fast-track (ETF/MF/MMF/UCITS only) | IC |
| GET | `/universe` | List currently approved funds | Any |
| GET | `/universe/funds/{instrument_id}/audit-trail` | Full approve/revoke history | IC |

---

## 15. Configuration Reference

All config resolved via `ConfigService.get("liquid_funds", config_type, org_id)`.

### 15.1 Portfolio Profiles

```yaml
portfolio_profiles:
  profiles:
    conservative:
      cvar:
        limit: -0.08
        confidence: 0.95
        window_months: 12
      max_single_fund_weight: 0.10
    moderate:
      cvar:
        limit: -0.06
        confidence: 0.95
        window_months: 3
      max_single_fund_weight: 0.12
    growth:
      cvar:
        limit: -0.12
        confidence: 0.95
        window_months: 6
      max_single_fund_weight: 0.15
```

### 15.2 Optimizer Config

```yaml
optimizer:
  apply_shrinkage: true       # Ledoit-Wolf (default true)
  risk_aversion: 2.0          # λ in quadratic objective
  turnover_cost: 0.0          # L1 penalty (0 = no penalty)
  robust: false               # Enable Phase 1.5 SOCP
  uncertainty_level: 0.5      # κ scaling for robust
fee_adjustment:
  enabled: false              # Subtract expense ratios from μ
```

### 15.3 Regime Thresholds

```yaml
regime:
  vix_risk_off: 25
  vix_extreme: 35
  yield_curve_inversion: -0.10
  cpi_high: 4.0
  cpi_normal: 2.5
  sahm_rule: 0.50
  oas_risk_off: 550          # bp
  oas_crisis: 800             # bp
```

### 15.4 Advisor Scoring Weights

```yaml
advisor_scoring_weights:
  low_volatility: 0.40
  low_correlation: 0.35
  low_overlap: 0.15
  high_sharpe: 0.10
```

---

## 16. Error Handling & Fallbacks

| Scenario | Behavior | Status |
|----------|----------|--------|
| < 2 funds with NAV data | Heuristic fallback (score-proportional) | `fallback:insufficient_fund_data` |
| < 120 aligned trading days | Heuristic fallback | `fallback:insufficient_fund_data` |
| CLARABEL infeasible | SCS solver fallback | Same status |
| All 4 phases fail CVaR | Return Phase 1 result | `optimal:cvar_violated` |
| Sparse universe (missing blocks) | Rescale constraints proportionally | Normal |
| Infeasible rescaled constraints | Relax all block min=0, max=1.0 | Normal |
| Regime data unavailable | Use standard covariance (no conditioning) | Normal |
| BL views unavailable | Use historical mean returns | Normal |
| Fee data missing | Skip fee adjustment | Normal |
| Factor decomposition fails | Omit from output | Normal |
| Turnover penalty infeasible | Retry Phase 1 without penalty | Normal |
| Advisor: no candidates for a block | Empty block, "Browse Catalog" hint | Normal |
| Advisor: MVS impossible | Return `null` with coverage analysis | Normal |
| Advisor: Redis unavailable | Compute fresh (fail-open) | Normal |
| CF CVaR invalid (extreme moments) | Advisor uses historical simulation | Normal |
| Activation: CVaR exceeds limit | HTTP 409 CONFLICT | Rejected |

---

## 17. Frontend Implementation

All paths relative to `frontends/wealth/src/lib/` unless noted otherwise.

### 17.1 Chart Components (ECharts 5.6)

All charts use `ChartContainer` from `@investintell/ui/charts` with the `ii-theme`. Options are built reactively via `$derived.by()`.

| Component | File | Data Source | Key ECharts Features |
|-----------|------|-------------|---------------------|
| **CVaR History** | `components/charts/CVaRHistoryChart.svelte` | `riskStore.cvarHistoryByProfile[profile]` (SSE-updated) | Dual Y-axis (CVaR % + utilization %), `visualMap` piecewise coloring (green/amber/red), `markArea` for breach periods, `markLine` at 80%/100% thresholds, `filterMode: 'weakFilter'` on DataZoom |
| **Portfolio NAV** | `components/charts/PortfolioNAVChart.svelte` | `trackRecord.nav_series` (SSR-loaded) | Area gradient fill (3-stop `LinearGradient`), daily return bars (green/red), `sampling: 'lttb'`, inception `markLine`, `boundaryGap: false` |
| **Backtest Equity Curve** | `components/charts/BacktestEquityCurve.svelte` | `trackRecord.backtest.folds` (SSR-loaded) | Horizontal bar chart of Sharpe per fold, 4-tier color coding (dark green/light green/orange/red), reduced opacity for low-observation folds, KPI summary row above chart |
| **Regime Timeline** | `components/charts/RegimeTimeline.svelte` | `riskStore.regimeHistory` (SSE-updated) | **Pure CSS** (no ECharts) — flex strip with `flex-grow` proportional to segment duration, `min-width: 2px`, hover expand 8→24px, `--ii-regime-*` tokens |

**Chart performance patterns:**
- `replaceMerge: ['series']` instead of `notMerge: true` — preserves DataZoom position on data refresh
- `sampling: 'lttb'` (Largest-Triangle-Three-Buckets) on time-series with >100 points
- `AriaComponent` imported in `echarts-setup.ts` for screen reader support

### 17.2 UI Components

| Component | File | Purpose |
|-----------|------|---------|
| **ConnectionStatus** | `components/ConnectionStatus.svelte` | SSE connection indicator (dot + label) in topbar. Green pulsing = live, yellow static = delayed (polling), red static = offline. `role="status"` + `aria-live="polite"` |
| **MacroIndicatorStrip** | `components/MacroIndicatorStrip.svelte` | 4 KPI chips (VIX, 10Y-2Y yield curve, CPI YoY, Fed Funds rate). VIX color-coded (green < 20, yellow 20-30, red > 30). Yield curve red if inverted. Data date as tooltip |
| **ScoreBreakdownPopover** | `components/model-portfolio/ScoreBreakdownPopover.svelte` | Click-to-expand score decomposition per fund. Lazy-loads `GET /instruments/{id}/risk-metrics`. Shows 6 components (return consistency, risk-adj return, drawdown, IR, momentum, fee efficiency) with weights and weighted contributions |

### 17.3 Constants & Types

| File | Content |
|------|---------|
| `constants/blocks.ts` | `BLOCK_LABELS` (16 blocks), `blockLabel()` helper, `BLOCK_GROUPS` (Equities/FI/Alts/Cash) — single source of truth for block display names |
| `constants/regime.ts` | `regimeLabels`, `regimeColors`, `REGIME_CVAR_MULTIPLIER` (RISK_ON=1.00, RISK_OFF=0.85, CRISIS=0.70, INFLATION=0.90), `regimeMultiplierLabel()` |
| `types/model-portfolio.ts` | `scenarioLabel()` (5 scenarios), `optimizerStatusLabel()` (6 statuses with severity), `InstrumentWeight.instrument_type` (full universe union: mutual_fund, etf, bdc, money_market, closed_end, interval_fund, ucits, private), `profileColor()` |

### 17.4 Risk Store Extensions

**File:** `stores/risk-store.svelte.ts`

The `CVaRPoint` type was extended beyond the simple `{ date, cvar }` to include fields from the backend response:

```ts
export interface CVaRPoint {
  date: string;
  cvar: number;                      // cvar_current from backend
  cvar_limit: number | null;         // limit for the profile
  cvar_utilized_pct: number | null;  // utilization percentage
  trigger_status: string | null;     // "ok" | "warning" | "breach" | "hard_stop"
}
```

The `applyUpdate()` normalizer maps all fields from the backend `GET /risk/{profile}/cvar/history` response. The `CVaRHistoryChart` component uses the store's normalized shape — never the raw backend response.

**Other store state used by new components:**
- `regimeHistory: Array<{ date: string; regime: string }>` — used by RegimeTimeline
- `macroIndicators: Record<string, unknown>` — used by MacroIndicatorStrip (typed at component boundary)
- `connectionQuality: "live" | "degraded" | "offline"` — used by ConnectionStatus

### 17.5 Page Integration Map

| Page | Components Added | Phase |
|------|-----------------|-------|
| **Dashboard** (`routes/(app)/dashboard/+page.svelte`) | MacroIndicatorStrip, RegimeTimeline, regime multiplier label, clickable portfolio cards (`<a>` with hover effects + `data-sveltekit-preload-data`) | P1, P2 |
| **Portfolio Workbench** (`routes/(app)/portfolios/[profile]/+page.svelte`) | CVaRHistoryChart, RegimeTimeline, regime multiplier in header, cross-link to Model Portfolio | P0, P1, P2 |
| **Model Portfolio Workbench** (`routes/(app)/model-portfolios/[portfolioId]/+page.svelte`) | CVaRHistoryChart, PortfolioNAVChart, BacktestEquityCurve (with youngest fund warning), ConsequenceDialog on activation, optimizer status labels, ScoreBreakdownPopover, cross-link to Portfolio Monitoring | P0, P1, P2 |
| **Creation Wizard** (`routes/(app)/model-portfolios/create/+page.svelte`) | CVaR guard fix (POST /activate), batch ConsequenceDialog, block labels from constants, optimizer status labels | P0, P1 |
| **App Layout** (`routes/(app)/+layout.svelte`) | ConnectionStatus in topbar | P2 |

### 17.6 Backend Gaps (Blocked Frontend Items)

Two frontend items require backend work before implementation:

| Item | Endpoint Needed | Current State |
|------|----------------|---------------|
| **IC View Edit** (in-place editing in ICViewsPanel) | `PATCH /model-portfolios/{id}/views/{view_id}` | Only POST (create) and DELETE exist. Need partial update endpoint with audit event |
| **Deactivation Flow** (archive active portfolio) | `POST /model-portfolios/{id}/deactivate` | No `archived` status in model. Need migration to add status value + endpoint with IC role guard |

---

## 18. Glossary

| Term | Definition |
|------|-----------|
| **CVaR (Conditional Value at Risk)** | Expected loss beyond the VaR threshold. At 95% confidence, CVaR₉₅ is the average loss in the worst 5% of scenarios. Expressed as negative number (loss convention). |
| **CLARABEL** | Interior-point conic solver for quadratic + SOCP programs. Primary solver for all optimization phases. |
| **SCS** | Splitting Conic Solver. Fallback solver when CLARABEL fails. Slower but more robust to numerical issues. |
| **Cornish-Fisher (CF)** | Expansion that adjusts the normal quantile for skewness and kurtosis. Used for fast parametric CVaR in the optimizer. Unreliable at extreme levels. |
| **Ledoit-Wolf** | Shrinkage estimator for covariance matrices. Pulls sample covariance toward a structured target (identity × trace). More stable with small T relative to N. |
| **Black-Litterman (BL)** | Bayesian framework combining market equilibrium returns with investor views. Produces more stable expected returns than raw historical means. |
| **SOCP** | Second-Order Cone Program. Phase 1.5 uses SOCP to penalize weights sensitive to covariance estimation error (robust optimization). |
| **PSD** | Positive Semi-Definite. Required property for covariance matrices. Optimizer enforces via eigenvalue floor if numerical error produces negative eigenvalues. |
| **GARCH(1,1)** | Generalized Autoregressive Conditional Heteroskedasticity. Models time-varying volatility. Conditional vol forecast stored in `fund_risk_metrics.volatility_garch`. |
| **Regime** | Market state classification: RISK_ON, RISK_OFF, INFLATION, CRISIS. Derived from VIX, yield curve, CPI, credit spreads. |
| **Strategic allocation** | Long-term neutral block weights per profile. Stored in `strategic_allocation` table with effective date versioning. |
| **Tactical position** | Short-term tilts overlaid on strategic allocation. Stored in `tactical_positions` table. |
| **Block** | Asset class bucket (e.g., `na_equity_large`, `fi_us_aggregate`). Defined in `allocation_blocks` table. Funds assigned to blocks via `instruments_org.block_id`. |
| **MVS (Minimum Viable Set)** | Smallest set of candidate funds whose addition brings portfolio CVaR within the profile limit. Found by brute-force (≤15 candidates) or greedy+swap. |
| **Manager score** | Composite quality score (0-100) per fund. Weighted sum of return, Sharpe, drawdown, IR, momentum, fee efficiency. |
| **Heuristic fallback** | Score-proportional fund selection when optimizer is unavailable. Top 3 funds per block, weights proportional to manager_score. |
| **N-PORT** | SEC quarterly filing with mutual fund holdings at CUSIP level. Used for holdings overlap analysis between funds. |
| **DTW (Dynamic Time Warping)** | Distance metric for time series comparison. Used by drift detection to measure divergence between actual and target weights. |
