# PR-A12 — Always-Solvable Construction Cascade (Rockafellar-Uryasev CVaR-as-Constraint)

**Date:** 2026-04-16
**Executor:** Opus 4.6 (1M)
**Branch:** `feat/pr-a12-always-solvable-cascade` (cut from `main` HEAD post PR-A11 squash-merge)
**Scope:** Rewrite the optimizer cascade so the construction engine is **mathematically always-solvable** AND **always CVaR-aware**. The current 4-phase cascade silently degrades to pure min-variance (loses CVaR intent) when the variance proxy `σ_max = (cvar_limit / 3.71)²` rejects feasible CVaR-compliant portfolios. PR-A12 replaces phases 2 + 3 with a Rockafellar-Uryasev linear-programming formulation: Phase 1 maximizes return subject to **CVaR-as-constraint via RU LP** (no proxy, no infeasibility from approximation error); Phase 2 (optional robust) keeps PR-A3's ellipsoidal uncertainty wrapped around the same RU constraint; Phase 3 minimizes CVaR (always feasible — the constraint set is always non-empty) and surfaces the universe's tail-risk floor to the operator. The cascade NEVER returns `failed` for solver/feasibility reasons — only for upstream data failures (no universe, missing returns matrix). When the operator's CVaR limit sits below the universe floor, status is `degraded`, the operator is shown "Your CVaR limit X% is below universe floor Y%", and PR-A13 renders the achievable-return band so the operator can decide to relax.

## Foundational principle (durable, `memory/feedback_optimizer_always_solvable.md`)

> The construction engine cascade must NEVER be infeasible. CVaR is the operator-set constraint; return is the resultant. If the operator's CVaR limit is below the universe's minimum achievable CVaR, the optimizer returns the **min-CVaR portfolio** with its emergent return — and the run is flagged informationally (not as failure). The frontend renders "Your CVaR limit X% → achievable return band [Y, Z]%". Infeasibility is a quant abstraction the operator must never see.

## Empirical evidence (live local DB, 2026-04-17 00:12 UTC, post PR-A9.1)

Three canonical model_portfolios share `cvar_limit=0.05`, `cvar_level=0.95`, `max_single_fund_weight=0.10`, no turnover_cap. Return target is **not** a configurable field (emergent only). Source: `feedback_optimizer_always_solvable.md` + Andrei's `mp.config_overrides` audit at 2026-04-17 00:12.

| Portfolio | profile | strategic_allocation | Phase 2 (current) | Final solver | Delivered E[r] | Delivered CVaR_95 |
|---|---|---|---|---|---|---|
| Conservative Preservation | conservative | 50% FI / 23% equity / 11% alt / 9% cash | INFEASIBLE | min_variance_fallback | 9.97% | -3.58% |
| Balanced Income | moderate | 30% FI / 47% equity / 12% alt / 2% cash | INFEASIBLE | min_variance_fallback | 10.43% | -4.10% |
| Dynamic Growth | growth | 11% FI / 67% equity / 10% alt / 0% cash | succeeded | CLARABEL Phase 2 | 13.20% | -4.31% |

**The critical observation:** Conservative + Balanced *delivered CVaR ≤ 5%* (-3.58% and -4.10%) under min-variance fallback — proving the universe CAN satisfy the constraint. The variance proxy at `σ_max ≈ 1.75-2.27%` falsely rejected those candidates. The proxy is the bug, not the universe.

## Mandates

1. **`mandate_high_end_no_shortcuts.md`** — RU LP construction must be mathematically rigorous; no rule-of-thumb approximations dressed as constraints
2. **`feedback_smart_backend_dumb_frontend.md`** — backend persists structured numeric truth; SSE emits operator vocabulary only; no "RU LP infeasible", no "Phase 3 min-CVaR LP" jargon ever crosses the boundary
3. **`feedback_optimizer_always_solvable.md`** — the cascade NEVER produces `failed` for feasibility/solver reasons; min-CVaR is the universal floor
4. **Preserve PR-A11 cascade_telemetry shape (Andrei Option B)** — extend the JSONB content additively; do NOT break field names that A11's executor and SSE event already wrote
5. **No optimizer math regression for PR-A3/A8/A9** — Black-Litterman μ stays as PR-A2; Σ shrinkage and dedup stay as PR-A8; κ-ladder stays as PR-A9; CLARABEL/SCS solver fallback stays
6. **No new column / no new migration** — `cascade_telemetry JSONB` from PR-A11 (migration 0142) accommodates the new fields under additive sub-keys

## Section A — Quant Foundation & Decisions

### A.1 — Why the variance proxy fails

The current Phase 2 derives a variance ceiling from the CVaR limit assuming portfolio CVaR is `c · σ - μ` under (Cornish-Fisher-relaxed) Normal:

```
σ_max = |cvar_limit| / (cvar_coeff_normal / cf_relaxation_factor)
      ≈ 0.05 / (3.71 / 1.3) ≈ 1.75%
```

This is a **sufficient** condition for `CVaR_CF(w) ≤ L`, not necessary. Any portfolio with σ ≤ σ_max satisfies the CVaR limit, but portfolios with σ > σ_max may also satisfy it — particularly when:

- The universe has high block-level intra-correlation (FI funds clustered ⇒ block contributes σ even when CVaR is contained because losses don't compound)
- Expected return μ is non-trivial relative to σ · c (μ shifts the loss distribution rightward; the proxy ignores this)
- Block bounds already pin weights into corners where σ exceeds σ_max but the loss-distribution tail is still below L

**Empirical proof:** Conservative's min-variance fallback solution achieved CVaR_95 = -3.58% with σ = 2.95%. The Phase 2 ceiling rejected any candidate with σ > 2.27% — including all candidates that would have satisfied CVaR ≤ 5% with higher μ. The proxy is the bug.

### A.2 — Rockafellar-Uryasev LP formulation

Canonical RU formulation (Uryasev 2000, *"Optimization of Conditional Value-at-Risk"*, Journal of Risk 2(3):21-41) for CVaR-as-constraint:

```
maximize    μᵀ w
subject to  ζ + (1 / ((1-α) · T)) · Σ_i u_i  ≤  L      [RU CVaR ≤ L]
            u_i ≥ -returns_scenarios[i, :] @ w - ζ      ∀ i ∈ {1..T}
            u_i ≥ 0                                     ∀ i ∈ {1..T}
            sum(w) = 1
            block_min_b ≤ Σ_{i ∈ block_b} w_i ≤ block_max_b   ∀ blocks
            0 ≤ w_i ≤ max_single_weight                 ∀ i
```

Where:
- `w ∈ ℝ_+^N` — fund weights
- `ζ ∈ ℝ` — auxiliary VaR variable (free sign per RU theorem; CLARABEL handles unbounded)
- `u ∈ ℝ_+^T` — auxiliary slack per scenario
- `α` — confidence level (0.95 for CVaR_95)
- `L` — operator-set CVaR limit (positive number; `L = abs(constraints.cvar_limit)`)
- `returns_scenarios ∈ ℝ^{T × N}` — historical scenario matrix (loss = `-returns_scenarios @ w`)
- `T` — number of scenarios

This is a **pure LP** (linear in `w, ζ, u`). CLARABEL solves LPs natively with high stability. Constraints scale O(T + N + #blocks); for T=1260 (5Y daily) and N≈92 (post-PR-A8 dedup), problem dimension is ~1352 — well within CLARABEL's comfort zone (sub-200ms expected).

**The RU constraint is exact, not approximate.** It computes empirical CVaR at the LP solution directly from the scenario matrix. There is no "Cornish-Fisher relaxation factor" because there is no parametric assumption to relax. This is the mathematical reason the cascade becomes always-solvable: the proxy that produced false infeasibility is gone.

### A.3 — Scenario source (LOCKED)

**Decision: 5Y daily returns, equal-weighted scenarios, no EWMA.** Reasoning:

- **5Y window (T = 1260 trading days):** matches PR-A1's risk window for Σ. Using a different window for μ-vs-CVaR than for Σ would reintroduce calibration mismatch. Justified by 5Y being long enough to include one full credit cycle for FI-heavy mandates.
- **Equal-weighted (no EWMA):** RU CVaR is conditional on the *unconditional* scenario distribution. EWMA-weighting scenarios in the LP requires reformulating as a weighted sample (`u_i / w_i_ewma`) and risks numerical instability when weights span 3+ orders of magnitude. PR-A1's GARCH already conditions Σ for regime-aware risk; double-conditioning the LP would over-tighten in stress regimes. Lock equal-weighted; revisit only if PR-A14 shows backtested CVaR breach rates > 7% (vs. nominal 5%).
- **Source:** the same returns matrix `quant_queries.compute_fund_level_inputs` already builds for sample covariance. If `FundLevelInputs` does not currently expose the raw returns matrix (only the covariance), surface it as a new field `returns_scenarios: np.ndarray` (shape `(T, N)`).

**Edge cases the implementer MUST handle:**

1. **Funds with shorter history than T:** today the covariance pipeline forward-fills or imputes. For RU LP, NaN scenarios produce NaN `u_i` and CLARABEL crashes. Decision: **forward-fill from first observation, then drop scenarios where all funds have NaN at i** (effectively shrinks T to common-window length). Log the effective T; warn if T < 504 (2Y); fail upstream if T < 252 (1Y minimum).
2. **All-zero scenario row:** legal (CLARABEL handles), but skews CVaR upward. No special handling.
3. **Constant returns (zero variance) for a fund:** legal in LP; the fund will be over-allocated. PR-A8's dedup already removes degenerate columns. Trust the upstream.

### A.4 — New cascade design (3 phases, always-solvable)

Replace the 4-phase cascade with a **3-phase always-solvable sequence**:

#### Phase 1 — RU CVaR-constrained max return

```
maximize    μᵀ w  -  λ · turnover_penalty  (when current_weights provided)
s.t.        RU CVaR(w) ≤ L
            base constraints (sum=1, blocks, max_single, long-only)
```

- If status ∈ {`optimal`, `optimal_inaccurate`}: return weights, `cascade_summary="phase_1_succeeded"`, run.status=`succeeded`
- If `infeasible` / `solver_error`: continue to Phase 2

**Note:** the legacy "Phase 1 with mean-variance utility surrogate `μᵀw - λ_risk·wᵀΣw`" is REPLACED. RU LP is a pure linear objective `μᵀw`. λ_risk no longer enters Phase 1. Risk control is via the CVaR constraint, period. This is the correct formulation per the foundational principle (return is resultant). `resolve_risk_aversion` callsite at `optimizer_service.py:583` is removed for Phase 1; keep the import for the robust phase only.

#### Phase 2 — Robust RU (ellipsoidal uncertainty on μ) — KEEP if `robust=True`

```
maximize    μᵀ w  -  κ · ‖Lᵀ w‖₂          [PR-A3 ellipsoidal]
s.t.        RU CVaR(w) ≤ L
            base constraints
```

- κ derived per PR-A9 ladder
- If succeeds: return, `cascade_summary="phase_2_robust_succeeded"`, status=`succeeded`
- If infeasible: continue to Phase 3

**Decision: keep Phase 2 as the robust wrapper** rather than fold robust into Phase 1. Reasoning: most operators run with `robust=False` (Phase 2 skipped); the few who enable robust accept the ellipsoidal penalty as opt-in conservatism. Folding robust into Phase 1 would penalize default users.

#### Phase 3 — Min-CVaR (ALWAYS feasible)

```
minimize    ζ + (1 / ((1-α) · T)) · Σ_i u_i      [pure CVaR objective]
s.t.        u_i ≥ -returns_scenarios[i, :] @ w - ζ,  u_i ≥ 0
            base constraints (NO CVaR upper bound, NO return target)
```

- This LP is feasible for any non-empty constraint polytope (sum=1 + block bounds + max_single weights — always non-empty for the canonical portfolios)
- The result is the universe's minimum achievable CVaR portfolio
- If achieved CVaR ≤ L: status=`succeeded`, `cascade_summary="phase_3_min_cvar_within_limit"` (rare — would mean Phase 1 numerical hiccup; instrument why)
- If achieved CVaR > L: status=`degraded` (informational, NOT failure), `cascade_summary="phase_3_min_cvar_above_limit"`, telemetry surfaces `min_achievable_cvar` so frontend renders the gap

**Removed:** `min_variance_fallback`, `heuristic_fallback`. Both lose CVaR intent. The min-variance fallback at `optimizer_service.py:937-979` is deleted. The heuristic fallback at `optimizer_service.py:982-987` is deleted. No new code path can produce a result without populating CVaR-aware weights.

**Why this is non-negotiable:** Conservative's Phase 3 result would now be the universe's minimum-CVaR portfolio (CVaR ≈ -3.0 to -3.5%), which is *lower tail risk* than today's min-variance fallback (-3.58%) AND honors the operator's intent (minimize tail loss). The min-variance objective is only a coincidental match for tail control under specific covariance structures — RU is exact.

### A.5 — Always-run Phase 3 (LOCKED for telemetry)

**Decision: ALWAYS run Phase 3, even when Phase 1 succeeds.** Reasoning:

- PR-A13's Builder UI renders "Your CVaR limit X% → achievable return band [Y, Z]%"
- Lower bound `Z_min` = return at min-CVaR portfolio (Phase 3 result)
- Upper bound `Z_max` = return at user-set CVaR limit (Phase 1 result, or Phase 3 if Phase 1 failed)
- Without always-running Phase 3, the band collapses to a point on success and the operator gets no feedback on how much return they're sacrificing for tail control

Cost: ~50-150ms additional LP per construction run (one extra LP of the same dimension). Acceptable given construction is bounded at 120s and runs on-demand. The 50-150ms estimate is empirically grounded by Conservative's current Phase 3 wall_ms of 89.

Implementation: run Phase 3 in parallel (asyncio.gather) with Phase 1 when both will execute, OR sequentially after Phase 1 if Phase 1's status is still pending. Lock **sequential** for v1 (parallelism complicates failure attribution; revisit if p95 wall > 5s).

### A.6 — Compatibility with PR-A11 cascade_telemetry shape

A11 introduced `cascade_telemetry JSONB` (migration 0142). A12 keeps the column and the existing top-level keys but updates the **enumerated values** and adds **two new sub-keys**.

**Phase keys in `phase_attempts[*].phase`:** A11 uses `primary | robust | variance_capped | min_variance | heuristic`. A12 maps as:

| A11 key | A12 key | Why renamed |
|---|---|---|
| `primary` | `phase_1_ru_max_return` | makes the RU formulation explicit; downstream A10/A13 read this string |
| `robust` | `phase_2_ru_robust` | numbering aligns with new cascade order |
| `variance_capped` | *(removed)* | proxy phase no longer exists |
| `min_variance` | *(removed)* | replaced by min-CVaR |
| *(new)* | `phase_3_min_cvar` | always present; runs even when Phase 1 wins |
| `heuristic` | *(removed)* | heuristic fallback eliminated |

**`cascade_summary` values:**

| A11 value | A12 value | Run status |
|---|---|---|
| `phase_1_succeeded` | `phase_1_succeeded` | `succeeded` |
| `phase_1_5_robust_succeeded` | `phase_2_robust_succeeded` | `succeeded` |
| `phase_2_succeeded` | *(removed — was variance-cap)* | — |
| `phase_3_fallback` | *(removed — was min-var)* | — |
| `heuristic_fallback` | *(removed)* | — |
| *(new)* | `phase_3_min_cvar_within_limit` | `succeeded` (rare) |
| *(new)* | `phase_3_min_cvar_above_limit` | `degraded` |
| `cascade_exhausted` | *(removed — A12 cannot exhaust)* | — |

**`operator_signal.kind` values:**

| A11 value | A12 value |
|---|---|
| `null` (Phase 1/2 win) | `null` (Phase 1/2 win) |
| `constraint_binding` (Phase 3 fallback fired) | `cvar_limit_below_universe_floor` (Phase 3 above limit) |
| `cascade_failure` | *(removed)* |

**Renames are breaking for any A10/A13 consumer that pattern-matches the old strings.** PR-A13 has not shipped yet, but PR-A10 has. Audit `frontends/wealth/src/lib/portfolios/cascade-panel/` and `metric-translators.ts` for hard-coded strings BEFORE merging A12 — update the mapping table in lockstep. If A10 mapping is missing values, they render as raw strings and operators see internals.

**New sub-keys in `cascade_telemetry`:**

```json
{
  "min_achievable_cvar": 0.0635,
  "achievable_return_band": {
    "lower": 0.0998,
    "upper": 0.0998,
    "lower_at_cvar": 0.0635,
    "upper_at_cvar": 0.0635
  }
}
```

`min_achievable_cvar` is always populated (Phase 3 result). `achievable_return_band` is always populated (collapses when limit < universe floor). Both feed PR-A13 directly.

**Removed sub-keys:** `phase2_max_var`, `min_achievable_variance`, `feasibility_gap_pct` (all variance-proxy artifacts). PR-A12 stops writing them. PR-A10's cascade panel must drop the variance-gap row in lockstep.

## Section B — Scope (estimated ~5-7h Opus work)

### B.1 — Files that change

| File | Lines (approx.) | Change |
|---|---|---|
| `backend/quant_engine/optimizer_service.py` | 363-987 | Replace `optimize_fund_portfolio` cascade. Phase 1 becomes RU LP max-return. Phase 1.5 becomes Phase 2 robust-RU. Phases 2 (variance-capped) + 3 (min-var) + heuristic fallback DELETED. New Phase 3 (min-CVaR LP) added. Always-run Phase 3 even on Phase 1 success. Helper `_build_ru_cvar_constraints` factored out (see B.2). |
| `backend/quant_engine/optimizer_service.py` | 24-50 (new), 310-360 | Extend `FundOptimizationResult` with `min_achievable_cvar: float | None`, `achievable_return_band: dict | None`. `PhaseAttempt.phase` Literal-update — leave as `str` (matches A11 dataclass discipline) but ensure all writers emit the new keys. |
| `backend/quant_engine/ru_cvar_lp.py` | NEW (~80 lines) | Helper module exposing `build_ru_cvar_constraints(w_var, returns_scenarios, alpha, limit_or_none) -> tuple[list[Constraint], cvxpy.Variable, cvxpy.Variable]` returning constraints + `ζ` var + `u` vector. When `limit_or_none is None`, returns CVaR-objective expression instead (overload via two functions: `build_ru_cvar_constraints` and `build_ru_cvar_objective`). Decision: **two functions, not overload**, for clarity. |
| `backend/app/domains/wealth/services/quant_queries.py` | wherever `FundLevelInputs` is built + returned | Surface `returns_scenarios: np.ndarray` (shape `(T, N)`) on `FundLevelInputs`. Verify if a raw-returns array exists already (probably built en route to sample covariance); if not, retain it from the source. Document T-handling per A.3. |
| `backend/app/domains/wealth/routes/model_portfolios.py` | `_run_construction_async` (around 2194-2289) | Pass `returns_scenarios` from `FundLevelInputs` into `optimize_fund_portfolio`. Capture `min_achievable_cvar`, `achievable_return_band` from result. Add to result dict. |
| `backend/app/domains/wealth/workers/construction_run_executor.py` | `_build_cascade_telemetry` + persistence site | Update `_SUMMARY_BY_WINNING_PHASE` map (A.6 table). Update `_STATUS_BY_SUMMARY` map. Drop `phase2_max_var`/`min_achievable_variance`/`feasibility_gap_pct` writes. Add `min_achievable_cvar` + `achievable_return_band` writes. Update `operator_signal` derivation per A.6. Update SSE event payload to include `achievable_return_band` (sanitized — just numbers). |
| `frontends/wealth/src/lib/portfolios/cascade-panel/metric-translators.ts` | enum mapping | Add new `cascade_summary` + `operator_signal.kind` values. Drop removed values (or alias to the closest A12 value with a one-release deprecation). |
| `backend/tests/quant_engine/test_always_solvable_cascade.py` | NEW | Tests per Section E. |

**No new migration.** A11's `cascade_telemetry JSONB` accommodates the new shape. Confirm by re-reading `0142_construction_cascade_telemetry.py` — the column is untyped JSONB with `DEFAULT '{}'::jsonb`, so additive sub-keys work without DDL.

**No `cf_relaxation_factor` config cleanup in this PR** (per Section G). The optimizer parameter becomes dead but stays in the signature for one release; remove in a follow-up.

### B.2 — `ru_cvar_lp.py` — helper module

```python
"""Rockafellar-Uryasev CVaR LP formulation helpers (PR-A12).

Implements the auxiliary-variable linearization from Uryasev (2000):
    CVaR_α(L) = min_ζ { ζ + (1/(1-α)) E[(L - ζ)⁺] }

where L is the loss random variable. For a portfolio with weights w and
historical scenarios `returns_scenarios` (shape (T, N)), the loss in
scenario i is L_i = -returns_scenarios[i, :] @ w. The expectation is
replaced by the empirical mean (1/T) Σ_i max(L_i - ζ, 0), and the max is
linearized via slack variables u_i ≥ 0, u_i ≥ L_i - ζ.
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np


def build_ru_cvar_constraints(
    w_var: cp.Variable,
    returns_scenarios: np.ndarray,    # (T, N)
    alpha: float,                     # 0.95 for CVaR_95
    cvar_limit: float,                # positive number, e.g. 0.05
) -> tuple[list[cp.constraints.Constraint], cp.Variable, cp.Variable]:
    """Return (constraints, ζ, u) for CVaR_α(w) ≤ cvar_limit.

    The loss-distribution convention: cvar_limit > 0 is the maximum tail
    loss the operator will tolerate (e.g. 0.05 = 5% loss). Internally:
        L_i = -returns_scenarios[i, :] @ w_var       (loss = negative return)
        CVaR = ζ + (1/((1-α)·T)) Σ u_i ≤ cvar_limit
    """
    T, N = returns_scenarios.shape
    assert w_var.shape == (N,), f"w_var shape {w_var.shape} != ({N},)"
    assert 0.0 < alpha < 1.0
    assert cvar_limit > 0.0

    zeta = cp.Variable()                  # free sign per RU theorem
    u = cp.Variable(T, nonneg=True)
    losses = -returns_scenarios @ w_var   # (T,) — affine in w_var

    cvar_expr = zeta + (1.0 / ((1.0 - alpha) * T)) * cp.sum(u)
    constraints = [
        u >= losses - zeta,
        cvar_expr <= cvar_limit,
    ]
    return constraints, zeta, u


def build_ru_cvar_objective(
    w_var: cp.Variable,
    returns_scenarios: np.ndarray,
    alpha: float,
) -> tuple[cp.Expression, list[cp.constraints.Constraint], cp.Variable, cp.Variable]:
    """Return (cvar_expr, slack_constraints, ζ, u) for min-CVaR objective.

    Use `cp.Problem(cp.Minimize(cvar_expr), slack_constraints + base_constraints)`.
    """
    T, N = returns_scenarios.shape
    assert w_var.shape == (N,)
    assert 0.0 < alpha < 1.0

    zeta = cp.Variable()
    u = cp.Variable(T, nonneg=True)
    losses = -returns_scenarios @ w_var
    cvar_expr = zeta + (1.0 / ((1.0 - alpha) * T)) * cp.sum(u)
    slack_constraints = [u >= losses - zeta]
    return cvar_expr, slack_constraints, zeta, u
```

Two separate functions (not an overload) per the docstring rationale. Both return `(ζ, u)` so callers can introspect the CVaR variable post-solve via `float(zeta.value + (1/((1-alpha)*T)) * sum(u.value))` if needed for telemetry parity.

## Section C — Implementation guidance

### C.1 — Phase 1 rewrite (`optimizer_service.py:579-686`)

Replace the entire Phase 1 block. New structure:

```python
# ── Phase 1: RU CVaR-constrained max return ──
from quant_engine.ru_cvar_lp import build_ru_cvar_constraints

w1 = cp.Variable(n, nonneg=True)
phase1_constraints = _build_base_constraints(w1)

# RU CVaR-as-constraint (replaces the variance proxy entirely)
effective_cvar_limit = (
    abs(cvar_limit) * regime_cvar_multiplier
    if cvar_limit is not None
    else None
)
zeta1 = u1 = None
if effective_cvar_limit is not None:
    ru_cs, zeta1, u1 = build_ru_cvar_constraints(
        w_var=w1,
        returns_scenarios=returns_scenarios,
        alpha=cvar_alpha,                     # 0.95
        cvar_limit=effective_cvar_limit,
    )
    phase1_constraints.extend(ru_cs)

# Pure return objective (NO mean-variance utility surrogate). Risk control
# is via the RU constraint above.
objective_expr = mu @ w1

# Turnover penalty kept as L1 slack (PR-A2 semantics).
if current_weights is not None and turnover_cost > 0:
    t1 = cp.Variable(n, nonneg=True)
    phase1_constraints += [t1 >= w1 - current_weights, t1 >= current_weights - w1]
    objective_expr = objective_expr - turnover_cost * cp.sum(t1)

prob1 = cp.Problem(cp.Maximize(objective_expr), phase1_constraints)
_t_p1 = time.perf_counter()
status1 = await _solve_problem(prob1)
_wall_p1 = int((time.perf_counter() - _t_p1) * 1000)
```

After solve:

- If `status1 ∈ ("optimal", "optimal_inaccurate")`: extract weights, compute realized CVaR via either `_compute_cvar(opt_w)` (Cornish-Fisher) for backwards-compat reporting OR via the RU LP value `float(zeta1.value + sum(u1.value)/((1-cvar_alpha)*T))` (RU-empirical). **Decision: report BOTH** — `cvar_at_solution` = RU-empirical (the constraint-bound value), `cvar_at_solution_cf` = Cornish-Fisher (legacy comparator). The RU value is what the LP enforced; CF stays for downstream metrics that haven't migrated.
- If `status1 ∈ {infeasible, infeasible_inaccurate, solver_error}`: append PhaseAttempt with status `infeasible`/`solver_failed`, then **continue** to Phase 2 (do NOT return). Do NOT retry without turnover penalty (PR-A11's retry path is removed — RU LP is harder to make infeasible than the variance proxy was; retry is dead code).

`resolve_risk_aversion` import stays — used in Phase 2 robust below. The `lambda_risk` variable is no longer used in Phase 1 objective (formerly at line 583-584). Remove it from Phase 1; it lives only in Phase 2.

### C.2 — Phase 2 robust rewrite (`optimizer_service.py:687-810`)

Replace Phase 1.5 robust with Phase 2 robust-RU. Wrap the RU CVaR constraint around the existing PR-A3 ellipsoidal SOCP penalty. Skeleton:

```python
# ── Phase 2: Robust RU (ellipsoidal uncertainty on μ) ──
if not robust:
    attempts.append(PhaseAttempt(
        phase="phase_2_ru_robust", status="skipped", solver=None,
        objective_value=None, wall_ms=0, infeasibility_reason=None,
    ))
else:
    try:
        from scipy.stats import chi2 as sp_chi2
        kappa_95 = float(np.sqrt(sp_chi2.ppf(0.95, df=max(n, 1))))
        kappa = kappa_95 if uncertainty_level is None else (
            float(uncertainty_level) * (kappa_95 / 0.5) * 0.5
        )
        try:
            L_chol = np.linalg.cholesky(cov_matrix)
        except np.linalg.LinAlgError:
            eigvals, eigvecs = np.linalg.eigh(cov_matrix)
            eigvals = np.maximum(eigvals, 1e-8)
            L_chol = eigvecs @ np.diag(np.sqrt(eigvals))

        w2 = cp.Variable(n, nonneg=True)
        constraints2 = _build_base_constraints(w2)
        if effective_cvar_limit is not None:
            ru_cs2, _, _ = build_ru_cvar_constraints(
                w2, returns_scenarios, cvar_alpha, effective_cvar_limit,
            )
            constraints2.extend(ru_cs2)
        robust_obj = cp.Maximize(mu @ w2 - kappa * cp.norm(L_chol.T @ w2, 2))
        prob2 = cp.Problem(robust_obj, constraints2)

        _t_p2 = time.perf_counter()
        status2 = await _solve_problem(prob2)
        _wall_p2 = int((time.perf_counter() - _t_p2) * 1000)

        if status2 in ("optimal", "optimal_inaccurate"):
            opt_w2 = _extract_weights(w2)
            if opt_w2 is not None:
                # ... append PhaseAttempt + return _build_result(...) with winning_phase="phase_2_ru_robust"
                pass
        # else: append infeasible PhaseAttempt, fall through to Phase 3
    except Exception as e:
        attempts.append(PhaseAttempt(
            phase="phase_2_ru_robust", status="solver_failed",
            solver=None, objective_value=None, wall_ms=0,
            infeasibility_reason=str(e),
        ))
```

Note: when `robust=False` AND Phase 1 succeeded, Phase 2 records `skipped` and Phase 1's return path STILL runs Phase 3 in the background (per A.5). The "skip Phase 2" decision applies only to whether Phase 2 is ATTEMPTED, not whether the cascade short-circuits. The short-circuit happens after Phase 1 succeeds AND Phase 3 telemetry completes.

### C.3 — Phase 3 rewrite — min-CVaR (`optimizer_service.py:934-987`)

**Replace** the min-variance fallback with min-CVaR. ALWAYS run, even when Phase 1/2 succeeded (per A.5). Pseudo-code:

```python
# ── Phase 3: Min-CVaR (always feasible, always run for telemetry band) ──
from quant_engine.ru_cvar_lp import build_ru_cvar_objective

w3 = cp.Variable(n, nonneg=True)
cvar_expr, slack_cs, zeta3, u3 = build_ru_cvar_objective(
    w3, returns_scenarios, cvar_alpha,
)
constraints3 = _build_base_constraints(w3) + slack_cs
prob3 = cp.Problem(cp.Minimize(cvar_expr), constraints3)

_t_p3 = time.perf_counter()
status3 = await _solve_problem(prob3)
_wall_p3 = int((time.perf_counter() - _t_p3) * 1000)

if status3 not in ("optimal", "optimal_inaccurate"):
    # This should be effectively impossible for a non-empty constraint
    # polytope. If it happens, the constraint set is malformed (e.g.
    # block bands sum > 1). Log loudly and report status="cascade_failure"
    # (the ONLY failure mode in PR-A12).
    attempts.append(PhaseAttempt(
        phase="phase_3_min_cvar", status="solver_failed",
        solver="CLARABEL", objective_value=None, wall_ms=_wall_p3,
        infeasibility_reason=str(status3),
    ))
    return _empty_result("constraint_polytope_empty", "CLARABEL")

opt_w3 = _extract_weights(w3)
assert opt_w3 is not None, "min-CVaR LP returned non-extractable weights"

min_cvar = float(prob3.value)   # the minimized CVaR value
min_cvar_return = float(mu @ opt_w3)

attempts.append(PhaseAttempt(
    phase="phase_3_min_cvar", status="succeeded", solver="CLARABEL",
    objective_value=round(min_cvar, 6), wall_ms=_wall_p3,
    infeasibility_reason=None,
    cvar_at_solution=round(min_cvar, 6),
    cvar_limit_effective=effective_cvar_limit,
    cvar_within_limit=(min_cvar <= effective_cvar_limit if effective_cvar_limit else True),
))
```

Then decide which weights to return based on which phase won, and ALWAYS attach `min_achievable_cvar=min_cvar` + `achievable_return_band` to the result:

```python
# Decide winner (Phase 1 > Phase 2 > Phase 3)
if phase_1_weights is not None:
    winner_w, winner_phase, winner_status = phase_1_weights, "phase_1_ru_max_return", "succeeded"
elif phase_2_weights is not None:
    winner_w, winner_phase, winner_status = phase_2_weights, "phase_2_ru_robust", "succeeded"
else:
    # Phase 3 is the winner — degraded if above limit, succeeded if within
    within = (min_cvar <= effective_cvar_limit) if effective_cvar_limit is not None else True
    winner_w = opt_w3
    winner_phase = "phase_3_min_cvar"
    winner_status = "succeeded" if within else "degraded"

# Achievable return band — populated regardless of winner
upper = float(mu @ winner_w) if winner_phase != "phase_3_min_cvar" else min_cvar_return
band = {
    "lower": round(min_cvar_return, 6),
    "upper": round(upper, 6),
    "lower_at_cvar": round(min_cvar, 6),
    "upper_at_cvar": round(_compute_realized_cvar_ru(winner_w), 6),
}

return _build_result(
    winner_w, "CLARABEL", "optimal" if winner_status == "succeeded" else "degraded",
    winning_phase=winner_phase,
    min_achievable_cvar=round(min_cvar, 6),
    achievable_return_band=band,
)
```

`_build_result` signature gains two kwargs: `min_achievable_cvar`, `achievable_return_band`. They flow into `FundOptimizationResult`. The executor reads them.

### C.4 — Executor: extend `cascade_telemetry`

In `construction_run_executor.py::_build_cascade_telemetry`:

- Update `_SUMMARY_BY_WINNING_PHASE` per A.6 table
- Update `_STATUS_BY_SUMMARY`:
  ```python
  _STATUS_BY_SUMMARY = {
      "phase_1_succeeded": "succeeded",
      "phase_2_robust_succeeded": "succeeded",
      "phase_3_min_cvar_within_limit": "succeeded",
      "phase_3_min_cvar_above_limit": "degraded",
  }
  ```
- Stop writing `phase2_max_var`, `min_achievable_variance`, `feasibility_gap_pct`
- Start writing `min_achievable_cvar` (from `fund_result.min_achievable_cvar`) and `achievable_return_band` (from `fund_result.achievable_return_band`)
- Update `operator_signal` derivation:
  ```python
  if cascade_summary == "phase_3_min_cvar_above_limit":
      operator_signal = {
          "kind": "cvar_limit_below_universe_floor",
          "binding": "tail_risk_floor",
          "message_key": "cvar_limit_below_universe_floor",
          "min_achievable_cvar": min_achievable_cvar,
          "user_cvar_limit": calibration_snapshot.get("cvar_limit"),
      }
  else:
      operator_signal = None  # Phase 1/2 succeeded cleanly
  ```

### C.5 — SSE event `cascade_completed` payload

Extend the SSE payload (still `cascade_telemetry_completed` event for A11 backward compat) to include the band. Sanitized:

```python
{
    "cascade_summary": cascade_telemetry["cascade_summary"],
    "operator_signal": cascade_telemetry["operator_signal"],
    "achievable_return_band": cascade_telemetry["achievable_return_band"],
    "min_achievable_cvar": cascade_telemetry["min_achievable_cvar"],
}
```

Allowed vocabulary unchanged: `cascade_summary` enum, `operator_signal.kind` enum, numeric values. NEVER solver names, phase keys, math jargon.

### C.6 — Realistic example payload (post-A12 Conservative case)

```json
"cascade_telemetry": {
  "phase_attempts": [
    {"phase": "phase_1_ru_max_return", "status": "infeasible", "wall_ms": 312,
     "infeasibility_reason": "PRIMAL_INFEASIBLE",
     "cvar_at_solution": null, "objective_value": null,
     "cvar_limit_effective": 0.05},
    {"phase": "phase_2_ru_robust", "status": "skipped", "wall_ms": 0, ...},
    {"phase": "phase_3_min_cvar", "status": "succeeded", "wall_ms": 89,
     "cvar_at_solution": 0.0635, "objective_value": 0.0635,
     "cvar_limit_effective": 0.05, "cvar_within_limit": false}
  ],
  "cascade_summary": "phase_3_min_cvar_above_limit",
  "min_achievable_cvar": 0.0635,
  "achievable_return_band": {
    "lower": 0.0998, "upper": 0.0998,
    "lower_at_cvar": 0.0635, "upper_at_cvar": 0.0635
  },
  "operator_signal": {
    "kind": "cvar_limit_below_universe_floor",
    "binding": "tail_risk_floor",
    "message_key": "cvar_limit_below_universe_floor",
    "min_achievable_cvar": 0.0635,
    "user_cvar_limit": 0.05
  }
}
```

For a successful Conservative case (post-A12 with the fixed RU LP, where the universe genuinely can hit CVaR ≤ 5%):

```json
"cascade_telemetry": {
  "phase_attempts": [
    {"phase": "phase_1_ru_max_return", "status": "succeeded", "wall_ms": 287,
     "cvar_at_solution": 0.0470, "objective_value": 0.1085,
     "cvar_limit_effective": 0.05, "cvar_within_limit": true},
    {"phase": "phase_2_ru_robust", "status": "skipped", "wall_ms": 0, ...},
    {"phase": "phase_3_min_cvar", "status": "succeeded", "wall_ms": 91,
     "cvar_at_solution": 0.0352, "objective_value": 0.0352,
     "cvar_within_limit": true}
  ],
  "cascade_summary": "phase_1_succeeded",
  "min_achievable_cvar": 0.0352,
  "achievable_return_band": {
    "lower": 0.0975, "upper": 0.1085,
    "lower_at_cvar": 0.0352, "upper_at_cvar": 0.0470
  },
  "operator_signal": null
}
```

The band `[9.75%, 10.85%]` tells the operator: "If you tighten CVaR to the floor (3.52%), expect 9.75% return; at your set limit (5%), you get 10.85%."

## Section D — Smart-backend / dumb-frontend translation

PR-A13's Builder UI consumes:

- `cascade_summary` enum → icon + color
- `operator_signal.kind` enum → top-line message
- `achievable_return_band` → slider feedback panel
- `min_achievable_cvar` → "your CVaR limit X% is below universe floor Y%" warning

`metric-translators.ts` mapping (PR-A13 will own):

| Backend value | Operator copy |
|---|---|
| `phase_1_succeeded` | "Optimized to maximize return within your tail-risk budget." |
| `phase_2_robust_succeeded` | "Optimized with conservative robust adjustment." |
| `phase_3_min_cvar_within_limit` | "Constructed minimum tail-risk allocation within your budget." |
| `phase_3_min_cvar_above_limit` | "Your tail-loss limit is below what this universe can deliver. Showing minimum-tail-risk allocation." |
| `cvar_limit_below_universe_floor` | (drives the warning panel; uses `min_achievable_cvar` and `user_cvar_limit` numbers) |

Allowed SSE vocabulary: cascade_summary enum values, operator_signal.kind enum values, numeric values. Forbidden: "Rockafellar-Uryasev", "LP", "CLARABEL", "Phase N", "infeasible", "ζ", "u_i", "α", "scenario matrix", "Cornish-Fisher", "min-CVaR".

## Section E — Tests

Mandatory test cases in `backend/tests/quant_engine/test_always_solvable_cascade.py`:

### E.1 — `test_phase_1_succeeds_within_cvar_limit`
3-fund universe, well-conditioned cov, T=252 daily scenarios, cvar_limit=0.10 (loose). Assert:
- `result.status == "optimal"`
- `result.winning_phase == "phase_1_ru_max_return"`
- `result.achievable_return_band.upper >= result.achievable_return_band.lower`
- `result.min_achievable_cvar > 0` and `<= 0.10`

### E.2 — `test_phase_3_above_limit_returns_min_cvar`
Same universe, cvar_limit=0.005 (impossibly tight). Assert:
- `result.status == "degraded"`
- `result.winning_phase == "phase_3_min_cvar"`
- `len(result.weights) > 0` (always-solvable invariant)
- `result.min_achievable_cvar > 0.005`
- `result.achievable_return_band.lower == result.achievable_return_band.upper` (band collapses)

### E.3 — `test_always_solvable_invariant` (property test)
Hypothesis-style: generate random (n, cvar_limit, max_single_weight, block_bounds) where the constraint polytope is non-empty. For every input, assert:
- `result.status in {"optimal", "degraded"}`
- `len(result.weights) > 0`
- `sum(result.weights.values()) ≈ 1.0` within 1e-6
- Result NEVER has `status == "failed"` for solver/feasibility reasons
Run 50 random configurations.

### E.4 — `test_achievable_band_monotonic`
Same universe, run with `cvar_limit ∈ [0.10, 0.07, 0.05, 0.03, 0.01]`. Assert:
- `band.upper` is monotonically non-increasing as cvar_limit decreases
- `band.lower == band.upper` at cvar_limit < min_achievable_cvar

### E.5 — `test_phase_3_runs_even_on_phase_1_success`
Universe + loose cvar_limit (Phase 1 wins). Assert `phase_attempts[2].phase == "phase_3_min_cvar"` and `phase_attempts[2].status == "succeeded"`. The min-CVaR LP must run unconditionally for telemetry.

### E.6 — `test_ru_cvar_constraint_matches_empirical`
Construct a known scenario matrix (T=10, N=2). Solve Phase 1 with cvar_limit=0.04. Compute realized CVaR_95 from the optimized weights via empirical quantile. Assert `realized_cvar <= cvar_limit + 1e-3` (RU LP enforces empirical CVaR exactly, modulo solver tolerance).

### E.7 — `test_polytope_empty_returns_cascade_failure`
Pathological: block_min sum > 1 (constraint polytope is empty). Assert `result.status == "constraint_polytope_empty"`. This is the ONLY failure mode allowed in A12.

### E.8 — Live DB smoke (the F.1 verification)
Not in test file — see Section F.

Run: `pytest backend/tests/quant_engine/test_always_solvable_cascade.py -v` → all 7 green. Plus full sweep `pytest backend/tests/quant_engine/ backend/tests/wealth/ -q` green (PR-A11's tests must still pass — assert the renamed enum values are also handled in A11's `test_cascade_telemetry.py` consumer expectations, which means a small in-lockstep update to that file).

## Section F — Pass criteria & verification

### F.1 — Live smoke against the 3 canonical portfolios

Run `POST /portfolios/{id}/construct` for the 3 canonical IDs after merging. Then:

```sql
SELECT mp.display_name, pcr.status,
       pcr.cascade_telemetry->>'cascade_summary'                    AS summary,
       (pcr.cascade_telemetry->>'min_achievable_cvar')::float       AS min_cvar,
       (pcr.cascade_telemetry->'achievable_return_band'->>'lower')::float AS band_lower,
       (pcr.cascade_telemetry->'achievable_return_band'->>'upper')::float AS band_upper,
       pcr.cascade_telemetry->'operator_signal'->>'kind'            AS sig_kind,
       (SELECT COUNT(*) FROM jsonb_object_keys(pcr.weights_proposed)) AS n_w,
       pcr.wall_clock_ms
FROM portfolio_construction_runs pcr
JOIN model_portfolios mp ON mp.id = pcr.portfolio_id
WHERE pcr.portfolio_id IN (
    '3945cee6-f85d-4903-a2dd-cf6a51e1c6a5',
    'e5892474-7438-4ac5-85da-217abcf99932',
    '3163d72b-3f8c-427e-9cd2-bead6377b59c'
)
  AND pcr.requested_at > NOW() - INTERVAL '30 minutes'
ORDER BY mp.display_name, pcr.requested_at DESC;
```

### F.2 — Pass criteria table

| Criterion | Pass condition |
|---|---|
| All 3 runs `status` ∈ {`succeeded`, `degraded`} | NEVER `failed` |
| All 3 runs have non-empty `weights_proposed` (n_w >= 5) | optimizer always returns weights |
| All 3 runs have populated `cascade_telemetry.achievable_return_band` (lower + upper non-null) | UI inputs ready |
| All 3 runs have `min_achievable_cvar > 0` | Phase 3 always ran |
| Conservative + Balanced now hit `phase_1_succeeded` (post-A12 with cvar_limit=0.05) | RU LP fixed the false-infeasibility |
| Synthetic test with `cvar_limit=0.001` produces `status=degraded`, `cascade_summary="phase_3_min_cvar_above_limit"`, `len(weights) > 0` | always-solvable invariant proven |
| `pytest backend/tests/quant_engine/test_always_solvable_cascade.py` 100% green | unit coverage |
| `pytest backend/tests/quant_engine/ backend/tests/wealth/ -q` 100% green | no regression |
| `make lint` clean, `make typecheck` clean | code quality |
| PR-A11's `test_cascade_telemetry.py` updated to new enum values, still green | A11 consumer in lockstep |

Per `feedback_dev_first_ci_later.md`: live-DB smoke is the merge gate, not GitHub CI.

### F.3 — Expected outcome (empirical prediction)

Post-A12, the F.1 query produces:

```
display_name              | status     | summary             | min_cvar | band_lower | band_upper | sig_kind                          | n_w
--------------------------+------------+---------------------+----------+------------+------------+-----------------------------------+-----
Conservative Preservation | succeeded  | phase_1_succeeded   | ~0.030   | ~0.095     | ~0.108     | null                              | 13+
Balanced Income           | succeeded  | phase_1_succeeded   | ~0.035   | ~0.100     | ~0.115     | null                              | 10+
Dynamic Growth            | succeeded  | phase_1_succeeded   | ~0.040   | ~0.115     | ~0.135     | null                              | 8+
```

**The big result:** Conservative and Balanced flip from `min_variance_fallback` (CVaR-blind) to `phase_1_succeeded` (CVaR-aware). The variance proxy was the bug. Andrei's principle is preserved: cascade is always-solvable AND always CVaR-aware.

## Section G — Out of scope

- Frontend Builder slider + feedback panel (PR-A13)
- Profile-differentiated CVaR defaults (separate small migration; spec lives in `memory/project_cvar_profile_differentiation.md`)
- Migration to add columns (A11's JSONB column is sufficient)
- Changing Phase 1's expected return prior — Black-Litterman stays as PR-A2 designed
- Replacing CLARABEL with a different solver (CLARABEL → SCS fallback retained per phase)
- Cleaning up `cf_relaxation_factor` parameter (dead but stays for one release)
- EWMA-weighted scenarios in the RU LP (A.3 locks equal-weighted)
- Removing the legacy Cornish-Fisher CVaR computation (`parametric_cvar_cf`) — used elsewhere for reporting; PR-A12 only stops Phase 2 from depending on it
- Running Phase 1 + Phase 3 in parallel (A.5 locks sequential for v1)
- Re-tightening CVaR enforcement when `regime_cvar_multiplier != 1.0` for the robust phase (semantics already encoded in `effective_cvar_limit`; verify in tests)

## Section H — Operating notes for the implementer

1. **Read first, then code.** Open `optimizer_service.py:579-987` end-to-end before deleting anything. Open `quant_queries.py` to verify whether `returns_scenarios` is already produced (likely yes — Σ requires it). Open A11's `test_cascade_telemetry.py` to know exactly which strings need updating in lockstep.
2. **The infeasibility retry path at lines 607-633 (without turnover penalty) is dead code in A12** — RU LP doesn't suffer from turnover-induced infeasibility because slacks are unbounded. Remove the retry. If you keep it for safety, justify in the commit message.
3. **The `psd_violation` early-return at lines 432-448 stays.** Σ still gets PSD-checked because Phase 2 robust uses Cholesky. PR-A8/A9 dedup + factor-fallback should make this rare.
4. **Open question — block-band feasibility:** if block_min sums > 1 OR block_max sums < 1, the polytope is empty and even Phase 3 fails. Decide: validate upstream in `construction_run_executor` (preferred) OR treat Phase 3 failure as `cascade_failure` (fallback). LOCK: validate upstream — add a polytope sanity check in `_run_construction_async` BEFORE invoking the optimizer. If it fails, write `cascade_telemetry.operator_signal.kind = "constraint_polytope_empty"` with `binding = "block_bands"`.
5. **Open question — when `cvar_limit is None`:** Phase 1 RU constraint is skipped (max return with no CVaR cap). Phase 3 still runs (informational). `achievable_return_band.upper = float(mu @ phase_1_w)`, `achievable_return_band.lower = float(mu @ phase_3_w)`. Document in the optimizer docstring.
6. **Numerical detail:** `ζ` is a free variable. CLARABEL handles unbounded variables, but if the implementer encounters numerical issues, add `ζ_lower_bound = -10.0` and `ζ_upper_bound = 10.0` (loss bounds in absolute return units — a 1000% loss is impossible for a long-only portfolio). This is a band-aid; only apply if CLARABEL complains.

## Section I — Commit & PR template

Branch: `feat/pr-a12-always-solvable-cascade`. PR body matches PR-A11 #189 style:

```
## Summary
- Replace variance-proxy CVaR enforcement with Rockafellar-Uryasev LP — Phase 1 maximizes return s.t. exact empirical CVaR ≤ limit, no more false infeasibility from CF approximation.
- Replace min-variance fallback with min-CVaR LP (Phase 3) — always-feasible, always CVaR-aware. The cascade NEVER produces `failed` for solver/feasibility reasons.
- Always run Phase 3 (even when Phase 1 succeeds) to populate `achievable_return_band` for the upcoming Builder slider feedback (PR-A13).
- Drop heuristic_fallback and min_variance_fallback paths — both lost the operator's CVaR intent.

## Schema
- No new column or migration. PR-A11's `cascade_telemetry JSONB` extended additively with `min_achievable_cvar` and `achievable_return_band`.
- `cascade_summary` enum updated: phase_1_succeeded, phase_2_robust_succeeded, phase_3_min_cvar_within_limit, phase_3_min_cvar_above_limit. Old values (variance_capped, min_variance fallback, heuristic) removed.

## Empirical smoke (live local DB, org_id 403d8392-...)

| Portfolio | status | summary | min_cvar | band_lower | band_upper | n_w |
|---|---|---|---|---|---|---|
| Conservative Preservation | succeeded | phase_1_succeeded | <X> | <Y> | <Z> | <N> |
| Balanced Income           | succeeded | phase_1_succeeded | <X> | <Y> | <Z> | <N> |
| Dynamic Growth            | succeeded | phase_1_succeeded | <X> | <Y> | <Z> | <N> |

Always-solvable invariant verified via property test (E.3): 50 random configurations, status ∈ {succeeded, degraded}, never failed.

## Tests
- 7 new unit tests (E.1-E.7) green
- PR-A11's test_cascade_telemetry.py updated to new enum values, still green
- Full wealth + quant_engine sweep green
- `make lint` + `make typecheck` clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

**End of spec. Execute end-to-end. Report with the F.1 SQL output, test counts, and commit SHA. Do NOT commit until F.2 pass criteria are verified on live DB.**
