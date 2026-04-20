---
pr_id: PR-Q6
title: "feat(quant/g4): EVT extreme risk via POT + GPD fit"
branch: feat/quant-g4-evt-gpd
sprint: S4
dependencies: []
loc_estimate: 620
reviewer: quant
---

# Opus Prompt — PR-Q6: G4 EVT Extreme Risk

## Goal

Ship Peaks-Over-Threshold + Generalized Pareto Distribution tail-risk estimator as a new method in `cvar_service.py`. Compute extreme VaR/CVaR at 99%, 99.5%, 99.9% quantiles. Surface only in DD ch.5; NOT in scoring.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §4 (POT+GPD theory, fit, threshold selection, stability, integration)
- `CLAUDE.md` §Quant Upgrade

## Files to create

1. `quant_engine/evt/__init__.py`
2. `quant_engine/evt/pot_gpd.py` — POT fit, GPD MLE (`scipy.stats.genpareto.fit`), L-moments fallback (`lmoments3` lib), threshold selection, extreme VaR/CVaR formulas
3. `quant_engine/evt/diagnostics.py` — mean excess plot data + Hill estimator (for the `/analytics/evt-diagnostic` endpoint; endpoint wiring itself is separate PR)
4. `backend/alembic/versions/XXXX_add_cvar_evt_cols.py` — adds `cvar_99_evt`, `cvar_999_evt`, `evt_xi_shape` (NUMERIC nullable) to `fund_risk_metrics`
5. `backend/tests/quant_engine/test_evt_pot_gpd.py` — ≥18 tests

## Files to modify

1. `quant_engine/cvar_service.py` — add `method="evt_pot"` to `compute_cvar()` signature. Route to `evt.pot_gpd.extreme_var_evt()` internally.
2. `backend/app/domains/wealth/workers/global_risk_metrics.py` — populate the 3 new columns for each instrument ALWAYS.
3. `pyproject.toml` — add `lmoments3` dependency (pin version).
4. `vertical_engines/wealth/dd_report/chapters/ch5_risk.py` (verify path) — render tail-heaviness indicator (qualitative Light/Normal/Heavy/Extreme from ξ shape parameter). NEVER expose raw ξ, u, β values in copy.

## Implementation hints

### Fit flow

```python
@dataclass(frozen=True)
class GPDFit:
    xi: float          # shape
    beta: float        # scale
    u: float           # threshold
    n_exceedances: int
    method: Literal["mle", "lmoments"]
    converged: bool

@dataclass(frozen=True)
class ExtremeVaRResult:
    var_99: float
    var_995: float
    var_999: float
    cvar_99: float
    cvar_995: float
    cvar_999: float
    fit: GPDFit
    degraded: bool
    degraded_reason: str | None

def extreme_var_evt(
    returns: np.ndarray,
    quantiles: tuple[float, ...] = (0.99, 0.995, 0.999),
    threshold_method: Literal["quantile_90", "quantile_85"] = "quantile_90",
) -> ExtremeVaRResult: ...
```

### Threshold automatic selection

1. Work with losses: `losses = -returns[returns < 0]` (or negative-returns convention; document clearly)
2. Default threshold: `u = np.quantile(losses, 0.90)`
3. `excesses = losses[losses > u] - u`
4. If `len(excesses) < 20`: try `quantile_85`
5. If still `< 15`: degraded, fallback parametric VaR normal

### GPD MLE

```python
from scipy.stats import genpareto
params = genpareto.fit(excesses, floc=0)  # fix location at 0
xi, _, beta = params
```

If `xi >= 1`: infinite-mean tail → CVaR undefined → NaN + degraded reason="infinite_mean_tail".

### L-moments fallback

```python
import lmoments3 as lm
from lmoments3 import distr
paras = distr.gpa.lmom_fit(excesses)  # xi, beta
```

Trigger when MLE does not converge OR CI of ξ crosses 1 (bootstrap 200 samples for CI).

### Hill estimator sanity check

```python
top_k = int(0.10 * len(losses))
top_losses = np.sort(losses)[-top_k:]
xi_hill = np.mean(np.log(top_losses / top_losses[0]))
if abs(xi_hill - xi_mle) > 2 * abs(xi_mle):
    # diverge — degraded
```

### Extreme VaR/CVaR formulas

Per quant-math spec §4.4. Use the formulas given; do not re-derive.

## Tests (minimum 18)

1. GPD synthetic ξ=0.3, β=0.02, T=2000: recover params within 1.96×SE (MLE)
2. GPD synthetic ξ=0 (exponential tail): ξ_hat ≈ 0 (within 0.1)
3. Infinite-mean ξ=1.1 synthetic → CVaR=NaN + degraded
4. N=15 excessos → degraded
5. Exactly 20 excessos → boundary OK
6. Ground truth: R `evir` package on fixture data, tolerance 5% VaR 99.9%
7. MLE convergence failure path → L-moments fallback invoked
8. Both fallback fails → parametric normal VaR reported + strong flag
9. Hill sanity triggers when ξ_MLE far from ξ_Hill
10. Threshold 90% default, switch to 85% when <20 excess
11. Returns contain NaN → stripped before fit
12. All positive returns (no losses) → degraded reason="no_tail"
13. Monotonic quantiles: `var_99 < var_995 < var_999`
14. CVaR ≥ VaR at same quantile
15. Tail heaviness qualitative mapping: ξ<0 → "Light", 0≤ξ<0.15 → "Normal", 0.15≤ξ<0.5 → "Heavy", ξ≥0.5 → "Extreme"
16. `global_risk_metrics` worker populates 3 new cols (integration test)
17. Idempotence: same returns → same result
18. Fit object serializable (dataclass to dict)

## Acceptance gates

- `make check` green
- `lmoments3` added to `pyproject.toml` + lockfile
- Migration reversible
- Worker populates cols for fixture instruments
- DD ch.5 renders qualitative tail-heaviness; invariant scanner finds zero raw ξ/β/u values in rendered copy
- Performance: `extreme_var_evt()` completes in <200ms for 10-year daily returns (≈2520 obs)

## Non-goals

- Do NOT add EVT to scoring components
- Do NOT build the `/analytics/evt-diagnostic` endpoint (separate PR)
- Do NOT implement block-maxima GEV (POT only)
- Do NOT expose mean-excess plot data to UI in this PR

## Branch + commit

```
feat/quant-g4-evt-gpd
```

PR title: `feat(quant/g4): EVT extreme risk via POT + GPD fit`
