# Portfolio Construction — State Reference (2026-04-05)

Status snapshot of the Portfolio Builder system: backend routes, quant engine, vertical engine, frontend workspace, workers, and integration gaps.

---

## 1. Backend Routes — `model_portfolios.py`

All routes prefixed `/model-portfolios`. Auth: `_require_ic_role(actor)` unless noted.

| # | Method | Path | Body | Response | Persist | Line |
|---|--------|------|------|----------|---------|------|
| 1 | POST | `/` | `ModelPortfolioCreate` | `ModelPortfolioRead` | INSERT `model_portfolios` (status=draft) | 60 |
| 2 | GET | `/` | — | `List[ModelPortfolioRead]` | Read-only | 93 |
| 3 | GET | `/{id}` | — | `ModelPortfolioRead` | Read-only | 109 |
| 4 | PATCH | `/{id}` | `ModelPortfolioUpdate` | `ModelPortfolioRead` | UPDATE metadata fields | 132 |
| 5 | POST | `/{id}/construct` | None | `ModelPortfolioRead` | `fund_selection_schema` JSONB, status→backtesting, day-0 snapshot | 160 |
| 6 | GET | `/{id}/track-record` | — | Dict (nav_series, backtest, stress) | Read-only (joins `model_portfolio_nav`) | 207 |
| 7 | POST | `/{id}/backtest` | None | Dict (backtest metrics) | `backtest_result` JSONB | 256 |
| 8 | POST | `/{id}/stress` | None | Dict (scenario metrics) | `stress_result` JSONB | 310 |
| 9 | POST | `/{id}/stress-test` | `StressTestRequest` | `StressTestResponse` | Ephemeral (no DB write) | 364 |
| 10 | GET | `/{id}/overlap` | `?limit_pct=0.05` | `OverlapResultRead` | Read-only (queries N-PORT holdings) | 444 |
| 11 | POST | `/{id}/construction-advice` | None | `ConstructionAdviceRead` | Redis cache (10min TTL) | 553 |
| 12 | POST | `/{id}/activate` | None | `ModelPortfolioRead` | status→active (requires `cvar_within_limit`) | 747 |

### Analytics Routes — `analytics.py`

| # | Method | Path | Body | Response | Persist |
|---|--------|------|------|----------|---------|
| 1 | POST | `/analytics/backtest` | `BacktestRequest` (profile, cv, gap, n_splits) | `BacktestRunRead` | INSERT `backtest_runs` |
| 2 | GET | `/analytics/backtest/{run_id}` | — | `BacktestRunRead` | Read-only |
| 3 | POST | `/analytics/optimize` | OptimizeRequest | OptimizeResult | Redis cache (1h, SHA-256) |
| 4 | POST | `/analytics/optimize/pareto` | ParetoRequest | 202 + SSE | Background job, Redis cache |

---

## 2. Pydantic Schemas — `schemas/model_portfolio.py`

### ModelPortfolioRead
```python
id: UUID
profile: str                         # "conservative" | "moderate" | "growth"
display_name: str
description: str | None
benchmark_composite: str | None
inception_date: date | None
backtest_start_date: date | None
inception_nav: Decimal               # default 1000.0
status: str                          # "draft" → "backtesting" → "active" → "live"
fund_selection_schema: dict | None   # JSONB (see structure below)
backtest_result: dict | None         # JSONB (see structure below)
stress_result: dict | None           # JSONB (see structure below)
created_at: datetime
created_by: str | None
```

### fund_selection_schema JSONB
```json
{
  "profile": "moderate",
  "total_weight": 1.0,
  "funds": [
    {
      "instrument_id": "uuid",
      "fund_name": "Vanguard 500 Index",
      "block_id": "na_equity_large",
      "weight": 0.25,
      "score": 85.0
    }
  ],
  "optimization": {
    "expected_return": 0.07,
    "portfolio_volatility": 0.10,
    "sharpe_ratio": 0.65,
    "solver": "CLARABEL",
    "status": "optimal",
    "cvar_95": -0.065,
    "cvar_limit": -0.06,
    "cvar_within_limit": true,
    "factor_exposures": { "factor_1": 0.45 }
  }
}
```

### backtest_result JSONB
```json
{
  "mean_sharpe": 0.72,
  "std_sharpe": 0.15,
  "positive_folds": 4,
  "total_folds": 5,
  "youngest_fund_start": "2018-03-15",
  "folds": [
    { "fold": 1, "sharpe": 0.65, "cvar_95": -0.042, "max_drawdown": -0.08, "n_obs": 63 }
  ]
}
```

### stress_result JSONB (historical, from POST /stress)
```json
{
  "scenarios": [
    { "name": "2008_gfc", "start_date": "2007-10-01", "end_date": "2009-03-31", "portfolio_return": -0.28, "max_drawdown": -0.35, "recovery_days": null }
  ]
}
```

### StressTestRequest / StressTestResponse (parametric, from POST /stress-test)
```python
# Request
scenario_name: Literal["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps", "custom"]
shocks: dict[str, float] | None     # Required for "custom": {block_id: shock_decimal}

# Response
portfolio_id: str
scenario_name: str
nav_impact_pct: float               # Decimal (e.g., -0.12 = -12%)
cvar_stressed: float | None
block_impacts: dict[str, float]     # {block_id: impact_decimal}
worst_block: str | None
best_block: str | None
```

### ConstructionAdviceRead
```python
portfolio_id: str
profile: str
current_cvar_95: float
cvar_limit: float
cvar_gap: float                     # current - limit
coverage: CoverageAnalysisRead      # block_gaps[]
candidates: list[CandidateFundRead] # ranked by composite score
minimum_viable_set: MinimumViableSetRead | None
alternative_profiles: list[AlternativeProfileRead]
projected_cvar_is_heuristic: bool
```

---

## 3. Database Models

### model_portfolios
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| organization_id | UUID | RLS |
| profile | VARCHAR(20) | NOT NULL |
| display_name | VARCHAR(255) | NOT NULL |
| fund_selection_schema | JSONB | CLARABEL output |
| backtest_result | JSONB | Walk-forward metrics |
| stress_result | JSONB | Historical scenarios |
| status | VARCHAR(20) | draft → backtesting → active → live |
| inception_nav | NUMERIC(12,4) | Default 1000.0 |

### model_portfolio_nav (TimescaleDB hypertable candidate)
| Column | Type | Notes |
|--------|------|-------|
| portfolio_id | UUID | FK → model_portfolios, PK compound |
| nav_date | DATE | PK compound |
| nav | NUMERIC(18,6) | Synthesized daily |
| daily_return | NUMERIC(12,8) | |
| organization_id | UUID | RLS |

### strategic_allocation
| Column | Type | Notes |
|--------|------|-------|
| allocation_id | UUID | PK |
| profile | VARCHAR(20) | conservative/moderate/growth |
| block_id | VARCHAR(80) | FK → allocation_blocks |
| target_weight | NUMERIC(6,4) | |
| min_weight / max_weight | NUMERIC(6,4) | Block bounds for optimizer |
| actor_source | VARCHAR(20) | "macro_proposal" or "manual" |

### portfolio_snapshots (TimescaleDB hypertable, 1-month chunks)
| Column | Type | Notes |
|--------|------|-------|
| snapshot_id | UUID | PK |
| profile | VARCHAR(20) | |
| snapshot_date | DATE | Partitioned |
| weights | JSONB | {block_id: weight} |
| cvar_current / cvar_limit | NUMERIC(10,6) | |
| trigger_status | VARCHAR(20) | ok/warning/breach |
| consecutive_breach_days | INT | |

### backtest_runs
| Column | Type | Notes |
|--------|------|-------|
| run_id | UUID | PK |
| profile | VARCHAR(20) | |
| params | JSONB | Construction params |
| status | VARCHAR(20) | pending/completed/failed |
| cv_metrics | JSONB | Cross-validation results |

---

## 4. Quant Engine Services

### CLARABEL 4-Phase Cascade (`optimizer_service.py`)

```
Phase 1   → max risk-adjusted return (Sharpe)
Phase 1.5 → robust SOCP (ellipsoidal uncertainty sets)
Phase 2   → variance-capped (CVaR binding)
Phase 3   → min-variance
Fallback  → block-level heuristic (score-proportional)
```

Each phase: CLARABEL solver → SCS fallback. Fund-level concentration enforced via `max_single_fund_weight`.

**Cornish-Fisher CVaR** (`parametric_cvar_cf`): adjusts Normal quantile for portfolio skewness and excess kurtosis (fat-tail correction at 95% confidence).

### CVaR Service (`cvar_service.py`)

- `compute_cvar_from_returns(returns, confidence=0.95)` → historical simulation
- `compute_regime_cvar()` → conditional CVaR (stress regime subset)
- `check_breach_status(profile, cvar_current, consecutive_days)` → ok/warning/breach

**Thresholds:** warning ≥ 80% utilization, breach ≥ 100% + 5 consecutive days.

### Factor Model (`factor_model_service.py`)

- `decompose_factors(returns_matrix, macro_proxies, weights, n_factors=3)` → PCA via SVD
- Labels factors by correlation with macro proxies (VIX, DGS10, DXY, HYG-IEF spread)
- Returns: factor_exposures, r_squared, systematic vs specific risk %

### GARCH (`garch_service.py`)

- `fit_garch(returns, trading_days=252)` → GARCH(1,1) via `arch` library
- Requires ≥ 100 observations
- Returns: annualized conditional volatility, persistence (α + β)

### Scoring Model (`scoring_service.py`)

6 default components (sum = 1.0):
| Component | Weight | Description |
|-----------|--------|-------------|
| return_consistency | 0.20 | Stability of returns |
| risk_adjusted_return | 0.25 | Sharpe ratio |
| drawdown_control | 0.20 | Max drawdown severity |
| information_ratio | 0.15 | Alpha vs benchmark |
| flows_momentum | 0.10 | Blended momentum (RSI, Bollinger, OBV) |
| fee_efficiency | 0.10 | max(0, 100 - ER × 50) |

---

## 5. Vertical Engine — `model_portfolio/`

### Construction Flow
```
POST /construct
  → _run_construction_async()
    → _load_universe_funds()              # InstrumentOrg (approved, with manager_score)
    → _resolve_cvar_limit()               # StrategicAllocation → profile CVaR
    → compute_fund_level_inputs()          # Cov matrix, returns, skewness, kurtosis (504d)
    → optimize_fund_portfolio()            # CLARABEL 4-phase cascade
      → parametric_cvar_cf()              # Cornish-Fisher CVaR
    → construct_from_optimizer()           # PortfolioComposition
    → [fallback] construct()              # Score-proportional heuristic
    → _compute_factor_exposures()          # PCA (best-effort, failure is silent)
    → _create_day0_snapshot()              # PortfolioSnapshot record
```

### Stress Scenarios (`stress_scenarios.py`)

4 preset scenarios with per-block shocks (all in decimals):

| Scenario | Equity Impact | FI Impact | Alt Impact |
|----------|--------------|-----------|------------|
| gfc_2008 | -38% to -50% | Treasury +6%, HY -26% | Gold +5%, REITs -38% |
| covid_2020 | -30% to -40% | Treasury +8%, HY -12% | Gold +3%, REITs -25% |
| taper_2013 | -6% to -15% | Treasury -5%, HY -4% | Gold -28%, REITs -4% |
| rate_shock_200bps | -8% to -12% | Treasury -12%, HY -6% | Gold +2%, REITs -15% |

**Block IDs used as shock keys:** `na_equity_large`, `na_equity_small`, `intl_equity_dm`, `intl_equity_em`, `fi_treasury`, `fi_credit_ig`, `fi_credit_hy`, `alt_gold`, `alt_reits`.

### Construction Advisor (`construction_advisor.py`)

- `analyze_block_gaps()` — identifies underweight blocks (gap > 0.5%)
- `rank_candidates()` — composite score: low_vol(0.40) + low_corr(0.35) + low_overlap(0.15) + high_sharpe(0.10)
- `find_minimum_viable_set()` — brute-force (≤15 candidates) or greedy+swap
- Cached in Redis (10min TTL)

---

## 6. Workers

### portfolio_nav_synthesizer (Lock 900_030, daily)

Synthesizes daily NAV for all portfolios with `fund_selection_schema` and status ∈ {backtesting, active, live}.

```
NAV_t = NAV_{t-1} × (1 + Σ(w_i × r_i_t) / active_weight)
```

- Fetches fund returns from `nav_timeseries` (504d lookback)
- Upserts to `model_portfolio_nav` (500-row batches)
- Renormalizes weights if some funds are missing for a given date

### portfolio_eval (Lock 900_008, daily)

Evaluates portfolio health:
- Computes CVaR from synthesized NAV returns
- Checks breach status (ok/warning/breach)
- Creates daily `PortfolioSnapshot` records

---

## 7. Frontend — Portfolio Builder Workspace

### Component Tree
```
+page.svelte (Portfolio Builder — App-in-App)
├── PageHeader [Construct] [Stress Test]
├── Left Sidebar (col-span-4)
│   ├── ModelListPanel        → workspace.selectPortfolio()
│   ├── UniversePanel         → DnD source (workspace.universe)
│   └── PolicyPanel           → CVaR limit + max concentration sliders
└── Right Workspace (col-span-8)
    ├── MainPortfolioChart    → NAV line chart (dummy until NAV series wired)
    └── Tabs
        ├── PortfolioOverview → Fund Selection table (DnD drop targets)
        ├── FactorAnalysisPanel → PCA factor exposures (reads optimization.factor_exposures)
        ├── StressTestPanel   → Parametric stress (equity/rates/credit → API)
        └── OverlapScannerPanel → Holdings overlap (reads from /overlap API)
```

### Workspace State (`portfolio-workspace.svelte.ts`)

**Wired to real API (Phase 9 complete):**
- `constructPortfolio()` → `POST /model-portfolios/{id}/construct` (60s timeout)
- `runStressTest()` → `POST /model-portfolios/{id}/stress-test` (30s timeout)

**Macro Shock → Block Shock Mapping:**
```
Equity Shock (%):  -20% → divide by 100 → apply beta weights
                   na_equity_large (1.0), small (1.2), DM (0.9), EM (1.3), REITs (0.7)

Rates Shock (bps): 200bps → divide by 10000
                   fi_treasury (-1.0), fi_credit_ig (-0.6), fi_credit_hy (-0.3), alt_gold (+0.2)

Credit Spread (bps): 150bps → divide by 10000
                   fi_credit_ig (-0.5), fi_credit_hy (-1.0)
```

Blocks appearing in multiple categories sum their effects (e.g., `fi_credit_ig` gets rates + credit contribution).

### Integration Status

| Feature | Status | Notes |
|---------|--------|-------|
| Portfolio list/select | Wired | SSR load via `+page.server.ts` |
| Construct | Wired | POST /construct, no body, updates portfolio $state |
| Parametric Stress | Wired | POST /stress-test with mapped block shocks |
| Historical Stress | Not wired | POST /stress exists, frontend doesn't call it yet |
| Backtest | Not wired | POST /backtest exists, frontend doesn't call it yet |
| Track Record NAV | Not wired | GET /track-record exists, chart uses dummy data |
| Construction Advisor | Not wired | POST /construction-advice exists, no frontend panel |
| Holdings Overlap | Not wired | GET /overlap exists, OverlapScannerPanel is placeholder |
| Factor Analysis | Partial | Reads `optimization.factor_exposures` from construct result |
| Universe DnD | Local only | `workspace.universe` is empty array, needs API load |
| Policy sliders | Local only | Backend reads from `StrategicAllocation` table, not from UI |
| Activate | Not wired | POST /activate exists, no frontend button |
| Error handling | Wired | Toast notification for construct/stress failures |

---

## 8. Key Architectural Decisions

1. **No body on construct/backtest/stress** — backend reads universe, allocations, and constraints from DB. Frontend only triggers the computation.

2. **Ephemeral vs persisted stress** — parametric `/stress-test` is ephemeral (what-if analysis). Historical `/stress` persists to `stress_result` JSONB (portfolio record).

3. **Async boundary** — route handlers are async; CPU-heavy work (optimizer, backtest, advisor) runs via `asyncio.to_thread()`.

4. **CVaR gate for activation** — `POST /activate` requires `optimization.cvar_within_limit == True`. Portfolios that exceeded CVaR in all optimizer phases cannot be activated.

5. **NAV synthesis is daily** — `portfolio_nav_synthesizer` worker synthesizes weighted returns daily. No real-time NAV updates. Track record chart reads from `model_portfolio_nav`.

6. **Construction advisor is cached** — Redis 10min TTL. Deterministic hash: `portfolio_id + updated_at + date`.

7. **Block IDs are the universal key** — allocation blocks (`allocation_blocks` table) are the join key between strategic allocation, optimizer constraints, stress shocks, and portfolio composition.

8. **Frontend is "burro"** — no CVaR/regime/optimization logic runs client-side. The macro shock → block shock mapping is the only computation in the frontend (pure linear transformation with calibrated betas).
