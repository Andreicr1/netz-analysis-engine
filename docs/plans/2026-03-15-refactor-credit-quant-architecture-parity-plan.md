---
title: "refactor: Credit Engine Quant Architecture Parity (Phase A)"
type: refactor
status: completed
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md
deepened: 2026-03-15
---

# refactor: Credit Engine Quant Architecture Parity (Phase A)

## Enhancement Summary

**Deepened on:** 2026-03-15
**Review agents used:** architecture-strategist, pattern-recognition-specialist, performance-oracle, kieran-python-reviewer, code-simplicity-reviewer, security-sentinel, best-practices-researcher, FRED skill, scikit-learn skill, statsmodels skill, pymoo skill

### Critical Changes from Review

1. **Move `credit_backtest_service.py` to `vertical_engines/credit/`** — PD/LGD is credit-specific; placing it in universal `quant_engine/` violates the plan's own principle (architecture + pattern + YAGNI reviewers agree)
2. **Fix FRED rate limit: 120 req/min (2 req/s), NOT 10 req/s** — `time.sleep(0.12)` will trigger HTTP 429. Use token bucket at 2 req/s or `time.sleep(0.5)` (FRED skill + performance oracle)
3. **Fix existing bug: `settings.FRED_API_KEY` should be `settings.fred_api_key`** (security sentinel found case mismatch in market_data_engine.py:51)
4. **Simplify: skip generic N-dim grid runner and scenario framework** — the actual sensitivity grid is a 20-line nested loop with credit-specific math. Extract as plain functions, not Protocol+generic wrapper (YAGNI reviewer)
5. **Backtest: use `StratifiedKFold`, not `TimeSeriesSplit`** — rare defaults need stratification. Minimum 100 obs with ≥10 defaults. Pipeline with StandardScaler mandatory (scikit-learn skill)
6. **Type properly: `eval_fn: Callable` → `Callable[[dict[str, float]], float]]`; `params: dict` → `Mapping[str, Any]`; `vintage_cohorts: dict` → `dict[int, dict[str, float]]`** (Python reviewer)

### Design Decisions Revised After Review

| Original Decision | Revised Decision | Rationale |
|---|---|---|
| Protocol + generic grid runner + credit implementation (3-layer) | Plain function extraction to `credit_sensitivity.py` (1-layer) | Only credit implements; WM uses NAV-based concepts. Add Protocol when 2nd vertical needs it |
| `@dataclass(frozen=True)` on all result types | `@dataclass` (mutable) to match existing convention | All 7 existing quant_engine dataclasses are mutable. Frozen with mutable fields (dict, ndarray) is misleading |
| `stress_severity_service.py` with registration pattern | `stress_severity_service.py` with config-dict dimensions | Registration is YAGNI; config-dict is stateless and testable |
| `credit_backtest_service.py` in `quant_engine/` | `credit_backtest.py` in `vertical_engines/credit/` | PD/LGD is credit-specific; `backtest_service.py` (wealth) has no vertical prefix |
| `time.sleep(0.12)` for FRED | Token bucket rate limiter at 2 req/s (120 req/min) | 0.12s = 8.3 req/s, will be rate-limited immediately |
| 6 implementation phases | 4 consolidated phases | Combine model move + golden tests; combine integration tests + cleanup |
| Status values: `"COMPLETE"`, `"INSUFFICIENT_DATA"` | Lowercase: `"complete"`, `"insufficient_data"` | Existing services use lowercase ("ok", "optimal", "warning") |

---

## Overview

Refactor the Credit vertical engine's quantitative infrastructure to achieve architectural parity with the Wealth Management engine. This is Phase A of a 4-phase analytical upgrade (see brainstorm: `docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md`).

**Core problem:** The Credit engine evolved organically from Private Credit OS with monolithic modules (`ic_quant_engine.py` ~1297 LOC, `market_data_engine.py` ~1100 LOC) while the Wealth engine was designed with modular, parameter-injected services in `quant_engine/`. Additionally, the entire `quant_engine/` package is coupled to `app.domains.wealth.models`, preventing cross-vertical reuse.

**Key insight from SpecFlow + YAGNI analysis:** The scenario/sensitivity functions in `ic_quant_engine.py` use credit-specific concepts (default_rate, recovery_rate, concentration adjustment) and are NOT truly universal. A generic N-dimensional grid runner would wrap a 20-line nested loop in 400 LOC of framework. Instead, we extract credit functions as **plain modules** in the vertical, and defer Protocol interfaces until a second vertical needs parameter sweeps.

## Problem Statement

| Issue | Impact |
|-------|--------|
| `ic_quant_engine.py` is monolithic (1297 LOC) | Hard to test, understand, and extend |
| `quant_engine/` imports `app.domains.wealth.models` in all 8 services | Cannot be used by credit vertical without circular coupling |
| Two parallel FRED data paths (`macro_data` table vs `MacroSnapshot` direct fetching) | Inconsistent macro data between verticals |
| `compute_macro_stress_severity()` conflated with regime detection | Credit loses granular stress scoring if replaced by regime labels |
| Zero test coverage for `ic_quant_engine` and `market_data_engine` | No safety net for refactoring |
| FRED API key case mismatch bug (`FRED_API_KEY` vs `fred_api_key`) | Credit engine may not be picking up FRED key at all |
| FRED rate limit misconfigured (0.1s sleep = 10 req/s vs actual limit 2 req/s) | Will trigger HTTP 429 on batch fetches |

## Proposed Solution

### Architecture After Refactor

```
quant_engine/                          ← UNIVERSAL (no domain imports)
  fred_service.py                      ← NEW: universal FRED fetching + transforms + token bucket
  stress_severity_service.py           ← NEW: configurable stress scoring (config-dict dimensions)
  regime_service.py                    ← DECOUPLED: no wealth model imports
  cvar_service.py                      ← DECOUPLED: no wealth model imports
  ...existing services...              ← drift/scoring/etc stay (some retain wealth deps with docstring)

app/shared/
  models.py                            ← NEW: MacroData + MacroSnapshot (global tables, no RLS)
  schemas.py                           ← NEW: RegimeRead + StressSeverityResult

vertical_engines/credit/
  ic_quant_engine.py                   ← REFACTORED: delegates to extracted modules
  market_data_engine.py                ← REFACTORED: uses fred_service + stress_severity_service
  credit_sensitivity.py                ← NEW: plain functions extracted from ic_quant_engine
  credit_scenarios.py                  ← NEW: plain functions extracted from ic_quant_engine
  credit_backtest.py                   ← NEW: PD/LGD model validation (credit-specific)
```

### Key Design Decisions

1. **Plain function extraction, not Protocol abstraction** (revised from brainstorm after YAGNI review)
   - Extract `_build_sensitivity_2d/3d` and `_build_deterministic_scenarios` as plain functions to new credit modules
   - No `protocols.py`, no generic grid runner, no scenario framework
   - When a second vertical needs parameter sweeps, extract the shared pattern then
   - **Why revised:** Only credit implements today. WM uses NAV/Sharpe/drawdown, not default/recovery grids. Creating a Protocol with one implementor is premature abstraction

2. **Systemic decoupling of macro/regime infrastructure from wealth models** (SpecFlow Gap #4)
   - Move `MacroData` to `app/shared/models.py` (global table, no RLS — CLAUDE.md confirms)
   - Move `RegimeRead` to `app/shared/schemas.py`
   - `PortfolioSnapshot` stays in wealth; regime_service accepts pre-fetched macro values
   - **Scope honesty:** After this phase, `regime_service` and `cvar_service` will be decoupled. 5 of 8 quant_engine services will still import wealth models (drift, scoring, rebalance, optimizer, backtest). These retain imports with docstring noting vertical-specific dependency. Full decoupling via Protocol pattern is a future phase.

3. **Unify FRED data paths** (SpecFlow Gap #10)
   - `fred_service.py` is the single FRED fetching interface
   - Token bucket rate limiter at 2 req/s (120 req/min actual FRED limit)
   - Use FRED server-side transforms (`units="pc1"` for YoY%) to eliminate ~60 lines of client-side math
   - Cache: snapshot-level `MacroSnapshot` check first, fallback to live API
   - Handle FRED 200-with-error-body responses
   - Add `observation_end` parameter to signature
   - Fix `settings.fred_api_key` case mismatch

4. **Stress severity stays credit-enriched with config-dict dimensions** (revised from registration pattern)
   - Extract scoring framework to `quant_engine/stress_severity_service.py`
   - Sub-dimensions passed as `list[StressDimension]` config parameter (TypedDict), not via registration
   - Credit caller provides credit-specific dimensions; service is stateless and testable

5. **FRED service: class pattern with singleton lifecycle**
   - `FredService` class with `__init__(api_key, base_url)` — justified by stateful requirements (API key, rate limiter instance)
   - All existing quant_engine services use module-level functions; this is documented as intentional deviation
   - **Lifecycle:** Instantiate ONCE in FastAPI `lifespan()` (or at worker startup), NOT per-request. The `TokenBucketRateLimiter` must be shared across calls within a worker run to correctly enforce rate limits. Store as `app.state.fred_service` and inject via dependency.
   - For credit `market_data_engine.py` (sync context within `to_thread()`): receive the pre-instantiated `FredService` as a parameter from the async caller that holds the reference

6. **`get_current_regime()` fallback strategy** (architecture review finding)
   - Current: falls back to `PortfolioSnapshot.regime` when FRED data unavailable
   - After refactor: fallback moves to callers. Each vertical provides its own fallback:
     - Wealth: pre-fetches from PortfolioSnapshot, passes as `fallback_regime` parameter
     - Credit: uses `stress_severity` level as fallback (or defaults to `"risk_on"`)

## Technical Approach

### Implementation Phases

#### Phase 1: Foundation — Shared Models + Golden Tests + Bug Fix (~250 LOC)

**Goal:** Create shared model layer, capture regression baselines, fix FRED API key bug.

**Tasks:**

1. Create `backend/app/shared/models.py` (single file, not package — only 2 models)
   - Move `MacroData` from `app.domains.wealth.models.macro`
   - Move `MacroSnapshot` from `app.domains.credit.modules.ai.models`
   - Add comment: `# GLOBAL TABLE: No organization_id, no RLS. See CLAUDE.md.`
   - Leave backward-compatible re-exports at old locations

2. Create `backend/app/shared/schemas.py` (single file)
   - Move `RegimeRead` from `app.schemas.risk` (note: actual import path, not `app.domains.wealth.schemas.risk`)
   - Define `StressSeverityResult` dataclass (mutable, matching existing convention)

3. Fix FRED API key bug in `market_data_engine.py:51`:
   - Change `getattr(settings, "FRED_API_KEY", None)` to `settings.fred_api_key`

4. Write golden-value tests:
   - `test_ic_quant_golden.py` — capture exact outputs of `_build_sensitivity_2d()`, `_build_sensitivity_3d_summary()`, `_build_deterministic_scenarios()` for 3+ diverse inputs (normal, PROXY_MODE, INSUFFICIENT_DATA edge cases)
   - `test_market_data_golden.py` — capture exact output of `compute_macro_stress_severity()` for 2 known macro snapshots
   - Use `numpy.testing.assert_allclose(rtol=1e-6)` for financial calculations
   - Use exact string match for regime/stress level classifications

**Research insights for golden tests:**
- Use `numpy.random.default_rng(seed=42)` for deterministic fixtures
- Consider `hypothesis` property tests for invariants: "CVaR ≤ VaR", "regime always returns valid label"
- Differential testing pattern: keep old `_build_*` functions as `_original` during refactor, compare new vs old on 100 seeded inputs

**Files:**
- `backend/app/shared/models.py` (new — MacroData + MacroSnapshot)
- `backend/app/shared/schemas.py` (new — RegimeRead + StressSeverityResult)
- `backend/vertical_engines/credit/market_data_engine.py` (edit — fix FRED_API_KEY → fred_api_key)
- `backend/tests/test_ic_quant_golden.py` (new)
- `backend/tests/test_market_data_golden.py` (new)

**Validation:** `make check` passes. Old import paths work via re-exports. FRED key resolves correctly.

#### Phase 2: Decouple quant_engine/ + Extract Credit Functions (~400 LOC)

**Goal:** Decouple macro/regime from wealth models AND extract credit functions into focused modules.

**Tasks:**

1. Update `regime_service.py`:
   - Import `MacroData` from `app.shared.models`
   - Import `RegimeRead` from `app.shared.schemas`
   - `get_current_regime()` accepts pre-fetched macro dict + optional `fallback_regime: str = "risk_on"`. Remove PortfolioSnapshot fallback from service; callers provide their own
   - Add plausibility bounds on inputs: reject VIX < 0 or > 200, CPI < -10 or > 30 (security review finding)

2. Update `cvar_service.py`:
   - `check_breach_status()` accepts `consecutive_breach_days: int` parameter
   - Caller (wealth portfolio_eval) pre-fetches from PortfolioSnapshot and passes

3. Update remaining services where applicable:
   - Services with wealth-specific model deps (drift, scoring, rebalance, optimizer, backtest, lipper) keep imports but add docstring: `"""Note: imports {Model} from app.domains.wealth — vertical-specific dependency."""`

4. Update wealth callers:
   - `app/domains/wealth/routes/risk.py` — pre-fetch macro values, pass to `get_current_regime()`, provide PortfolioSnapshot regime as `fallback_regime`
   - `app/domains/wealth/services/portfolio_eval.py` — pre-fetch breach_days, pass to `check_breach_status()`

5. Extract credit sensitivity functions to `vertical_engines/credit/credit_sensitivity.py`:
   - Move `_build_sensitivity_2d()` and `_build_sensitivity_3d_summary()` as public functions
   - Keep `_build_sensitivity_matrix()` (deprecated 1D legacy) in `ic_quant_engine.py`
   - Use `itertools.product` for grid iteration (not generic framework)
   - Keep break-even finder as linear scan (48 elements too small for binary search)
   - Accept axis values as parameters with hardcoded defaults (configurable via ConfigService in future)
   - Add `structlog.get_logger()` for logging

6. Extract credit scenario functions to `vertical_engines/credit/credit_scenarios.py`:
   - Move `_build_deterministic_scenarios()` as public function
   - Keep `_SCENARIO_PROXY` multipliers and `_CONCENTRATION_LOSS_ADJ_PP` in this module
   - Accepts `structured_analysis` v2 dict, `macro_snapshot`, `concentration_profile`

7. Refactor `ic_quant_engine.py`:
   - Import and delegate to `credit_sensitivity` and `credit_scenarios`
   - `compute_quant_profile()` signature: **UNCHANGED**
   - All credit-specific logic stays: rate decomposition, covenant quant, risk-adjusted return, liquidity hooks

**Files:**
- `backend/quant_engine/regime_service.py` (edit)
- `backend/quant_engine/cvar_service.py` (edit)
- `backend/quant_engine/drift_service.py` (edit — docstring only)
- `backend/quant_engine/scoring_service.py` (edit — docstring only)
- `backend/quant_engine/rebalance_service.py` (edit — docstring only)
- `backend/app/domains/wealth/routes/risk.py` (edit)
- `backend/app/domains/wealth/services/portfolio_eval.py` (edit)
- `backend/vertical_engines/credit/credit_sensitivity.py` (new)
- `backend/vertical_engines/credit/credit_scenarios.py` (new)
- `backend/vertical_engines/credit/ic_quant_engine.py` (edit — delegate)

**Validation:** `make check` passes. Golden tests pass with IDENTICAL outputs. Wealth routes return correct data.

#### Phase 3: FRED Service + Stress Severity Service (~500 LOC)

**Goal:** Unify FRED data paths and extract configurable stress scoring.

**Tasks:**

1. Create `backend/quant_engine/fred_service.py`:

```python
"""Universal FRED API fetching service.

Sync service — called from within to_thread() context.
Intentional class pattern (not module functions) due to stateful
requirements: API key, rate limiter, base URL.

FRED rate limit: 120 requests per 60 seconds (2 req/s).
"""
import structlog
from dataclasses import dataclass

logger = structlog.get_logger()

@dataclass
class FredObservation:
    series_id: str
    date: str
    value: float | None
    units: str

class FredService:
    def __init__(self, api_key: str, base_url: str = "https://api.stlouisfed.org/fred"):
        if not api_key:
            raise ValueError("FRED API key must be provided")
        self._api_key = api_key
        self._base_url = base_url
        self._rate_limiter = TokenBucketRateLimiter(
            max_tokens=10, refill_rate=2.0  # 120 req/min
        )

    def fetch_series(
        self,
        series_id: str,
        *,
        observation_start: str | None = None,
        observation_end: str | None = None,
        units: str = "lin",           # lin, pch, pc1, ch1, pca, cch, cca, log
        frequency: str | None = None,  # d, w, m, q, a
        aggregation_method: str = "avg",
    ) -> list[FredObservation]: ...

    def fetch_batch(
        self,
        series_configs: list[dict],
        *,
        observation_start: str | None = None,
    ) -> dict[str, list[FredObservation]]: ...
```

   - Token bucket rate limiter (burst capacity 10, refill 2/s)
   - Use FRED server-side transforms: `units="pc1"` for YoY%, `units="chg"` for MoM delta — eliminates `_compute_yoy_pct()`, `_compute_mom_delta()`, `_compute_yoy_pct_cpi()` (~60 LOC)
   - Handle FRED 200-with-error-body: check for `"error_code"` in response JSON
   - Error classification: 429 → retry with exponential backoff, 401 → raise (bad key), 400 → skip (bad series), 503 → retry
   - Parse `"."`, `"#N/A"`, `""`, `"NaN"` as missing values; check `math.isfinite()`
   - Cache: check snapshot-level `MacroSnapshot` first (daily granularity), fall back to API
   - Never log API key; never include API key in error messages (URLs contain it)
   - Instantiate at async entry point: `FredService(settings.fred_api_key)` — not module-level

**Research insights for FRED service:**
- Keep derived series client-side: yield curve (DGS10 - DGS2) and CPI YoY require cross-series computation
- Revision windows per series: daily/weekly = immutable; monthly (CPI, UNRATE) = 60-day revision window; quarterly (GDP) = 90 days. MacroSnapshot daily cache is correct for operational use
- `fred_ingestion.py` worker already uses correct `settings.fred_api_key` and `MIN_REQUEST_INTERVAL = 0.5` — align `fred_service.py` with this pattern

2. Create `backend/quant_engine/stress_severity_service.py`:

```python
"""Configurable macro stress severity scoring.

Sync service — pure computation, no I/O.
Sub-dimensions provided as config parameter, not via registration.
"""
from typing import TypedDict

class StressDimension(TypedDict):
    name: str
    indicators: list[str]
    thresholds: dict[str, float]
    weight: float

class StressSeverityConfig(TypedDict, total=False):
    dimensions: list[StressDimension]
    grade_boundaries: list[tuple[int, str]]  # [(15, "none"), (35, "mild"), ...]

_DEFAULT_STRESS_CONFIG: StressSeverityConfig = { ... }

def resolve_stress_config(config: dict | None) -> StressSeverityConfig: ...

def compute_stress_severity(
    snapshot: dict[str, float | None],
    *,
    config: dict | None = None,
) -> StressSeverityResult: ...
```

   - Configurable via `resolve_stress_config()` + TypedDict (standard pattern)
   - Sub-dimensions as config parameter: credit caller provides `[{"name": "real_estate_stress", ...}, ...]`
   - No registration mechanism, no module-level mutable state
   - Returns `StressSeverityResult` (score: float, level: str, triggers: list[str], sub_dimensions: dict)
   - Status values lowercase: `"none"`, `"mild"`, `"moderate"`, `"severe"`

3. Refactor `market_data_engine.py`:
   - Replace internal FRED fetching with `fred_service` calls
   - Replace `compute_macro_stress_severity()` with `stress_severity_service.compute_stress_severity()` + credit dimension config
   - Keep credit-specific series registry (`CASE_SHILLER_METRO_MAP`, `GEOGRAPHY_TO_METRO`)
   - Keep `MacroSnapshot` caching logic (now using shared model from `app.shared.models`)
   - `get_macro_snapshot()` public API: **UNCHANGED**

**Files:**
- `backend/quant_engine/fred_service.py` (new)
- `backend/quant_engine/stress_severity_service.py` (new)
- `backend/vertical_engines/credit/market_data_engine.py` (edit — use new services)

**Validation:** Golden tests pass. FRED caching works. Stress scoring produces identical grades. `make check` passes.

#### Phase 4: Credit Backtest + Tests + Cleanup (~400 LOC)

**Goal:** Add credit-specific PD/LGD validation and comprehensive test coverage.

**Tasks:**

1. Create `backend/vertical_engines/credit/credit_backtest.py`:

```python
"""Credit PD/LGD model validation via cross-validated backtesting.

Credit-specific: uses default_labels, recovery_rates, vintage_years.
Lives in vertical_engines/credit/ (not quant_engine/) because
PD/LGD concepts are credit-domain-specific.

Sync service — pure computation, dispatched via to_thread().
"""
from dataclasses import dataclass
from enum import Enum
import numpy as np

class CVStrategy(str, Enum):
    STRATIFIED = "stratified"              # Default: StratifiedKFold
    TEMPORAL = "temporal"                  # TimeSeriesSplit (expanding window)
    TEMPORAL_STRATIFIED = "temporal_stratified"

MAX_OBSERVATIONS = 50_000
MAX_FEATURES = 100

@dataclass
class BacktestInput:
    features: np.ndarray                   # (N, F) financial ratios
    default_labels: np.ndarray             # (N,) 0/1 default indicator
    recovery_rates: np.ndarray             # (N,) realized LGD (0-1)
    vintage_years: np.ndarray              # (N,) origination year
    cv_strategy: CVStrategy = CVStrategy.STRATIFIED
    n_splits: int = 5

@dataclass
class CreditBacktestResult:
    pd_auc_roc: float
    pd_auc_std: float                      # std across folds
    pd_brier: float
    lgd_mae: float
    vintage_cohorts: dict[int, dict[str, float]]
    cv_folds: int
    cv_strategy: str
    sample_size: int
    n_defaults: int
    status: str                            # "complete" | "insufficient_data"
```

   - **Default CV: `StratifiedKFold`**, not `TimeSeriesSplit` — rare defaults (1-5% PD) need stratification to ensure every fold has ≥1 default
   - **Minimum: 100 observations with ≥10 defaults** (raised from 50). Adaptive fold count: `min(5, n_defaults // 2)`
   - **Pipeline: `StandardScaler` + `LogisticRegression(class_weight='balanced')`** — prevents data leakage, handles feature scale differences (leverage 0-10x vs margins 0-1), auto-adjusts for class imbalance
   - **Use `cross_val_predict` for AUC + Brier** — single pass OOF predictions, more stable than averaging per-fold AUCs
   - **Input validation:** reject `n_obs > MAX_OBSERVATIONS`, `n_feat > MAX_FEATURES`, NaN/Inf in features, non-binary labels, recovery_rates outside [0,1]
   - **Status lowercase:** `"complete"`, `"insufficient_data"`

2. Write integration tests:
   - `test_credit_sensitivity_integration.py` — verify `credit_sensitivity` produces same output as old `_build_sensitivity_2d/3d` (differential testing)
   - `test_credit_scenarios_integration.py` — verify `credit_scenarios` produces same output as old `_build_deterministic_scenarios`
   - `test_fred_service.py` — mock FRED API, verify caching, rate limiting, error handling (429, 200-with-error-body)
   - `test_stress_severity.py` — verify configurable thresholds produce expected grades
   - `test_regime_decoupled.py` — verify regime_service works with shared models, plausibility bounds reject bad inputs
   - `test_credit_backtest.py` — synthetic data, verify AUC > 0.5 sanity, verify insufficient_data below threshold

3. Remove backward-compatible re-exports (after grep confirms zero external callers):
   - Remove `MacroData` re-export from `app.domains.wealth.models.macro`
   - Remove `MacroSnapshot` re-export from `app.domains.credit.modules.ai.models`
   - Remove `RegimeRead` re-export from old location

4. Update `backend/quant_engine/__init__.py` with public API exports

**Files:**
- `backend/vertical_engines/credit/credit_backtest.py` (new)
- `backend/tests/test_credit_sensitivity_integration.py` (new)
- `backend/tests/test_fred_service.py` (new)
- `backend/tests/test_stress_severity.py` (new)
- `backend/tests/test_credit_backtest.py` (new)
- Old model/schema files (edit — remove re-exports)
- `backend/quant_engine/__init__.py` (edit)

**Validation:** Full `make check` passes. All golden tests pass. All new tests pass.

## System-Wide Impact

### Interaction Graph

```
Deep Review (deep_review.py)
  └→ compute_quant_profile() [ic_quant_engine.py — UNCHANGED signature]
       ├→ build_sensitivity_2d() [credit_sensitivity.py — plain function]
       ├→ build_sensitivity_3d() [credit_sensitivity.py — plain function]
       ├→ build_deterministic_scenarios() [credit_scenarios.py — plain function]
       └→ (rate decomp, covenant quant — unchanged, in-place)
  └→ get_macro_snapshot() [market_data_engine.py — UNCHANGED signature]
       ├→ FredService.fetch_batch() [quant_engine/fred_service.py]
       │    └→ MacroSnapshot cache [app.shared.models]
       └→ compute_stress_severity() [quant_engine/stress_severity_service.py]
            └→ credit dimensions via config param

Wealth Portfolio Eval (portfolio_eval.py)
  └→ regime_service.get_current_regime() [quant_engine/]
       └→ MacroData [app.shared.models] ← was app.domains.wealth
       └→ fallback_regime from caller ← was PortfolioSnapshot query
  └→ cvar_service.check_breach_status() [quant_engine/]
       └→ consecutive_breach_days param ← was PortfolioSnapshot query
```

### Error & Failure Propagation

- **FRED API failure:** `fred_service` checks `MacroSnapshot` cache first (returns stale but valid data). If no cache, returns `None` values. `stress_severity_service` degrades to `"none"` stress level. Deep Review continues with `macro_snapshot=None` (existing handler at deep_review.py:1799).
- **FRED 429 rate limit:** Token bucket prevents hitting this. If hit anyway, exponential backoff (2s, 4s, 8s, cap 30s) with 3 retries.
- **FRED 200-with-error-body:** Detect `"error_code"` in JSON, log warning, return `None` for that series.
- **Sensitivity grid failure:** `credit_sensitivity` catches computation errors, returns dict with `status: "insufficient_data"`. `ic_quant_engine` handles this (existing pattern at line 1258).
- **Regime service failure:** Returns `(fallback_regime, {"decision": "fallback"})`. Default fallback is `"risk_on"`.

### State Lifecycle Risks

- **MacroSnapshot/MacroData table move:** No Alembic migration — we move ORM model definitions, tables stay in-place.
- **Re-export removal (Phase 4):** Only after grep confirms zero external callers. Staged through Phases 1-3.
- **FRED path unification:** After refactor, `fred_service.py` is the single FRED interface. `market_data_engine.py` no longer calls FRED directly. `macro_data` table (worker-populated) remains separate from `MacroSnapshot` (on-demand cache).

### API Surface Parity

- `compute_quant_profile()` signature: **UNCHANGED**
- `get_macro_snapshot()` signature: **UNCHANGED**
- `get_current_regime()` signature: **CHANGED** — adds `fallback_regime: str = "risk_on"` param, accepts pre-fetched macro dict
- `check_breach_status()` signature: **CHANGED** — adds `consecutive_breach_days: int` param
- Wealth routes: updated to pre-fetch and pass data (2 route files)

## Acceptance Criteria

### Functional Requirements

- [ ] `compute_quant_profile()` returns IDENTICAL output for same inputs (golden test with `rtol=1e-6`)
- [ ] `get_macro_snapshot()` returns IDENTICAL output for same inputs (golden test)
- [ ] `regime_service` works from both credit and wealth callers
- [ ] `regime_service` rejects implausible inputs (VIX > 200, CPI > 30)
- [ ] `fred_service` caches in `MacroSnapshot` and respects 120 req/min rate limit
- [ ] `fred_service` handles FRED errors: 429 (retry), 401 (raise), 200-with-error-body (skip)
- [ ] `stress_severity_service` returns configurable 0-100 scores with config-dict sub-dimensions
- [ ] `credit_backtest` returns AUC-ROC, MAE, Brier using StratifiedKFold with balanced class weights
- [ ] `credit_backtest` rejects inputs > 50k observations, non-binary labels, NaN features
- [ ] All existing Deep Review flow unchanged (public API signatures preserved)

### Non-Functional Requirements

- [ ] No `app.domains.wealth` imports in `regime_service.py` and `cvar_service.py`
- [ ] Other quant_engine services document remaining wealth imports in module docstrings
- [ ] All new services follow parameter-injection pattern (no YAML, no @lru_cache)
- [ ] All new services have TypedDict config shapes with hardcoded defaults
- [ ] All new services include `logger = structlog.get_logger()`
- [ ] `FredService` class pattern documented as intentional deviation from module-function convention
- [ ] Dataclasses use `@dataclass` (mutable) to match existing quant_engine convention
- [ ] Status values use lowercase: `"complete"`, `"insufficient_data"`, `"none"`, `"mild"`, `"moderate"`, `"severe"`

### Quality Gates

- [ ] `make check` passes (lint + typecheck + test)
- [ ] Golden-value tests pass for all refactored functions
- [ ] New unit tests for all new modules (sensitivity, scenarios, fred, stress, backtest)
- [ ] Zero regressions in existing test suite

## Dependencies & Prerequisites

- **No new Python packages required** — uses existing numpy, scipy, sklearn, httpx
- **No Alembic migration required** — ORM model definitions move, tables don't
- **No frontend changes** — all changes are backend-internal
- **Prerequisite:** Sprint 4 complete (it is — PR #3 open)

## Risk Analysis & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Golden tests don't capture all edge cases | Medium | Regression in Deep Review output | Write golden tests for 3+ inputs including PROXY_MODE, INSUFFICIENT_DATA; add hypothesis invariant tests |
| Wealth routes break after regime/cvar signature change | Low | Wealth vertical regression | Update wealth routes in same PR; test with existing suite |
| FRED token bucket misconfigured | Low | 429 errors or overly conservative fetching | Match `fred_ingestion.py` pattern (0.5s sleep); token bucket refill at 2.0/s |
| Import cycle between `app.shared` and `app.domains` | Medium | App fails to boot | `app.shared.models` imports only from `app.core.database` (Base); domains import shared, never reverse |
| Re-export removal breaks undiscovered caller | Low | ImportError | Grep before removal; keep re-exports for 1 sprint |
| `app.shared.models` → `app.core.database` circular with `app.core` → `app.shared.enums` | **Eliminated** | ~~Import error~~ | **VERIFIED:** `app.shared/` has zero imports from `app.core`. Only `clerk_auth.py` imports `Role` from `app.shared.enums`. `app.core.db.base` imports nothing from `app.shared`. Direction is `app.shared ← app.core ← app.domains` — strictly unidirectional. Safe. |

## Future Work (Not In This Phase)

| Item | Phase | Trigger |
|------|-------|---------|
| **EDGAR upgrade with edgartools** | **Phase B — NEXT** | Replace `ic_edgar_engine.py` (1561 LOC hand-rolled HTTP) with `edgartools` library. Structured financials (income/balance/CF multi-period), Form 4 insider trading signals, built-in CIK resolution. See brainstorm Phase B. **Research done:** current engine has 4-tier CIK resolution + manual XBRL; deep_review consumes via `edgar_public_filings` text in evidence pack (all 13 chapters); edgartools not in pyproject.toml yet; no existing EDGAR tests. Key files: `ic_edgar_engine.py` (1561L), `deep_review.py` (consumes at L514-566 sync, L1974-1980 async), `evidence_law.j2` (attribution rules L121-137). Multi-entity orchestration (8 entity roles) must be preserved. Non-fatal design must be maintained. |
| FRED parallel fetching with ThreadPoolExecutor | **Phase B** | Cold-start with token bucket at 2 req/s and 40+ séries = ~20s. Perceptível no SSE do Deep Review enquanto o usuário assiste o progresso. Usar `ThreadPoolExecutor(max_workers=5)` com critical séries sequenciais, non-critical em paralelo — reduz para ~6s |
| Protocol interfaces for SensitivityEngine/ScenarioRunner | Phase C+ | When a second vertical needs parameter sweeps |
| Full quant_engine decoupling (drift, scoring, rebalance, optimizer) | Phase C+ | When these services need cross-vertical reuse |
| FRED revision window awareness per series | Phase C | When backtesting needs point-in-time macro data |
| SALib Sobol indices for multi-dimensional sensitivity | Phase C | When 6+ parameter dimensions are needed |
| Statsmodels PD/LGD models (Logit, GLM Binomial, SARIMAX) | Phase C | Statistical modeling phase |
| Pymoo reverse stress testing | Phase C+ | "Find minimum shock that breaches CVaR limit" |
| ScoringEngine with per-dimension Protocol classes | Phase D | When stress scoring needs full plug-in architecture |

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md](docs/brainstorms/2026-03-15-credit-engine-analytical-upgrade-brainstorm.md) — Key decisions: (1) extract universal to quant_engine/, keep credit-specific in vertical, (2) regime service becomes universal, (3) credit backtesting for PD/LGD validation

### Internal References

- `backend/quant_engine/cvar_service.py` — reference service pattern (config injection, TypedDict, pure functions, mutable dataclass)
- `backend/quant_engine/regime_service.py:23-25` — wealth coupling to decouple
- `backend/vertical_engines/credit/ic_quant_engine.py:929-1038` — sensitivity functions to extract
- `backend/vertical_engines/credit/ic_quant_engine.py:827-918` — scenario function to extract
- `backend/vertical_engines/credit/market_data_engine.py:51` — FRED API key case mismatch bug
- `backend/vertical_engines/credit/market_data_engine.py:676-800` — stress severity to extract
- `backend/vertical_engines/base/base_analyzer.py` — sync Session contract
- `backend/app/domains/wealth/workers/fred_ingestion.py:40` — correct FRED rate limit (MIN_REQUEST_INTERVAL=0.5)
- `docs/solutions/architecture-patterns/vertical-engine-extraction-patterns.md` — extraction learnings
- `docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md` — model migration patterns

### Review Agent Findings Applied

- **Architecture strategist:** Move credit_backtest to vertical; resolve regime fallback explicitly; typed result dataclasses
- **Pattern recognition:** Match existing `@dataclass` (not frozen); lowercase status values; document FredService class deviation
- **Performance oracle:** FRED rate limit correction (120/min not 10/s); keep break-even as linear scan; no performance concern with delegation chain
- **Python reviewer:** Type `eval_fn: Callable[[dict[str, float]], float]`; use `Mapping[str, Any]` for read-only params; full typing on vintage_cohorts
- **YAGNI reviewer:** Kill Protocol layer (1 implementor); skip generic grid/scenario runners; flatten shared models to single files; defer backtest to credit vertical
- **Security sentinel:** Fix FRED key case mismatch; add input validation on backtest arrays; add plausibility bounds on regime inputs; never log API key
- **FRED skill:** Token bucket rate limiter; server-side transforms; handle 200-with-error-body; add observation_end; revision windows
- **scikit-learn skill:** StratifiedKFold default; minimum 100 obs with ≥10 defaults; Pipeline(StandardScaler, LogisticRegression(class_weight='balanced')); cross_val_predict for OOF
- **Statsmodels skill:** Logit for PD, GLM(Binomial) for LGD, SARIMAX for covenant breach — deferred to Phase C
- **Pymoo skill:** Not for sensitivity analysis; SALib for future Sobol indices; consider reverse stress testing in Phase C+

### Institutional Learnings Applied

- **Parameter injection pattern:** Config resolved once at async entry point via `ConfigService.get()`, passed to sync functions
- **Lazy re-exports:** Leave backward-compatible imports at old paths during migration
- **Sync/async boundary:** Document in module docstrings, dispatch via `asyncio.to_thread()`
- **No module-level asyncio primitives:** Create inside async functions; FredService rate limiter uses lazy init
- **RLS subselect:** `(SELECT current_setting(...))` for any tenant-scoped queries
