---
pr_id: PR-Q3
title: "feat(wealth/g3-fase1): returns-based style attribution"
branch: feat/wealth-g3-returns-based
sprint: S1
parallel_with: [PR-Q1, PR-Q2]
dependencies: []
loc_estimate: 480
reviewer: wealth
---

# Opus Prompt — PR-Q3: G3 Fase 1 Returns-Based Style Attribution

## Goal

Ship the first rail of the attribution cascade: Sharpe 1992 returns-based style analysis. Unlocks DD ch.4 for ALL funds with ≥36 months of NAV history. This is the most visible deliverable of S1 — the chapter currently shows empty content.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §3.1 (Returns-based formulation, solver, confidence)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §4.1 (Query pattern monthly alignment, nav_timeseries + benchmark_nav)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-strategy.md` §4, §5, §6 (Integration, sanitization, confidence badges)

## Files to create

1. `vertical_engines/wealth/attribution/__init__.py`
2. `vertical_engines/wealth/attribution/models.py` — dataclasses `AttributionRequest`, `AttributionResult`, `ReturnsBasedResult`, `StyleExposure`, `RailBadge` enum (`RAIL_HOLDINGS`, `RAIL_IPCA`, `RAIL_PROXY`, `RAIL_RETURNS`, `RAIL_NONE`)
3. `vertical_engines/wealth/attribution/service.py` — dispatcher that decides which rail to run. For this PR, only returns-based is implemented; other rails return `RAIL_NONE` placeholder.
4. `vertical_engines/wealth/attribution/returns_based.py` — implements Sharpe 1992 QP via cvxpy/CLARABEL
5. `backend/tests/vertical_engines/wealth/test_attribution_service.py` — ≥8 dispatcher tests
6. `backend/tests/vertical_engines/wealth/test_attribution_returns.py` — ≥12 returns-based tests

## Files to modify

1. `vertical_engines/wealth/dd_report/chapters/ch4_performance.py` (verify exact path — could be under `backend/app/domains/wealth/`) — wire `attribution_service.compute()` result and render rail badge. If only `RAIL_RETURNS` available, render style exposures table + R² + TE + badge "LOW-MEDIUM CONFIDENCE — style regression".

## Implementation hints

### Returns-based QP

```python
import cvxpy as cp

def fit_style(r_fund: np.ndarray, r_styles: np.ndarray) -> ReturnsBasedResult:
    """
    r_fund: shape (T,)
    r_styles: shape (T, M) where M = #styles
    """
    M = r_styles.shape[1]
    w = cp.Variable(M)
    constraints = [cp.sum(w) == 1, w >= 0]
    objective = cp.Minimize(cp.sum_squares(r_fund - r_styles @ w))
    prob = cp.Problem(objective, constraints)
    prob.solve(solver=cp.CLARABEL, verbose=False)
    if prob.status != "optimal":
        return ReturnsBasedResult(degraded=True, degraded_reason=prob.status, ...)
    weights = w.value
    residuals = r_fund - r_styles @ weights
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((r_fund - r_fund.mean())**2)
    r_squared = 1 - ss_res/ss_tot if ss_tot > 0 else 0.0
    te_annualized = float(np.std(residuals) * np.sqrt(12))
    confidence = max(0.0, r_squared)
    return ReturnsBasedResult(weights=weights, r_squared=r_squared,
                              tracking_error_annualized=te_annualized,
                              confidence=confidence, degraded=False)
```

### Default style basket

7 ETFs: SPY, IWM, EFA, EEM, AGG, HYG, LQD. All in `benchmark_nav`. Configurable via `AttributionConfig.style_tickers` (ConfigService).

### Data fetch

Use the SQL pattern in data-layer spec §4.1 (monthly alignment via `time_bucket('1 month', ts)` + `last(nav, ts)`). Convert to async via asyncpg. Drop rows with NaN in any ETF or fund return. Require ≥36 aligned months after dropping.

### Dispatcher for this PR

```python
async def compute(request: AttributionRequest) -> AttributionResult:
    returns_result = await run_returns_based_rail(request)
    if returns_result.degraded:
        return AttributionResult(badge=RailBadge.RAIL_NONE, ...)
    if returns_result.n_months < 36:
        return AttributionResult(badge=RailBadge.RAIL_NONE,
                                 reason="insufficient_history", ...)
    return AttributionResult(
        badge=RailBadge.RAIL_RETURNS,
        returns_based=returns_result,
        holdings_based=None, proxy=None, ipca=None,
    )
```

PR-Q4 and PR-Q5 will extend the dispatcher to try rails in priority order.

## Tests (minimum 20 combined)

### Service tests (≥8)
- Dispatcher returns RAIL_RETURNS when returns rail succeeds
- Dispatcher returns RAIL_NONE when <36 months available
- Dispatcher returns RAIL_NONE when fund not in nav_timeseries
- Badge enum stored on result.metadata serializes cleanly
- `AttributionConfig.style_tickers` override is respected
- Default config reads 7 ETFs
- Concurrent dispatcher calls are isolated (no shared state)
- Idempotent: same (fund_id, asof) produces same result

### Returns-based tests (≥12)
1. Golden 60/40: synthetic `r_fund = 0.6*SPY + 0.4*AGG + N(0, 0.001)` → exposures (0.60, 0.40) tol 0.02
2. Constraint: `sum(w) == 1` within 1e-6
3. Constraint: `all(w >= 0)` within 1e-9
4. R² > 0.99 on synthetic exact linear combo
5. R² ≈ 0 on pure noise
6. TE annualized matches `sqrt(12) * std(residuals)` tol 1e-6
7. `confidence = max(0, r_squared)` in all cases
8. <36 months → degraded with reason
9. CVXPY solver failure → degraded with status
10. NaN in fund returns → drop and proceed if enough remaining
11. All-zero styles matrix → degraded (no identifiable solution)
12. Ill-conditioned styles (rank-deficient) → degraded or reduced R²

## Acceptance gates

- `make check` green
- DD ch.4 rendering integration test: seed a fund with 60 months of synthetic NAV, render ch.4, assert rail badge == RAIL_RETURNS and style table has 7 rows
- Invariant scanner: no occurrences of "cornish-fisher", "meucci", "brinson-fachler", "ipca", "cvar" in copy strings rendered by ch.4
- Performance: dispatcher completes in <1s for 1 fund × 7 styles × 10 years monthly
- P3 isolation: no module-level asyncio primitives
- P5 idempotent: caching via Redis keyed on `sha256(fund_id || asof || style_basket)` with 24h TTL

## Non-goals

- Do NOT implement holdings-based, proxy, or IPCA rails — those are PR-Q4, PR-Q5, PR-Q9
- Do NOT refactor `brinson_fachler.py` — that's PR-Q5 scope
- Do NOT expose raw R², TE to frontend UI literals — sanitize in DD chapter renderer
- Do NOT add Fund Copilot integration — deferred to hardening sprint

## Branch + commit

```
feat/wealth-g3-returns-based
```

PR title: `feat(wealth/g3-fase1): returns-based style attribution`

PR description must state: "Unblocks DD ch.4 Performance chapter for funds with ≥36m NAV history. Other 3 rails land in PR-Q4/Q5/Q9."
