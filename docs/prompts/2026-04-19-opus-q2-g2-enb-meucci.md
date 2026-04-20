---
pr_id: PR-Q2
title: "feat(quant/g2): effective number of bets (Meucci 2009 + Minimum Torsion 2013)"
branch: feat/quant-g2-enb-meucci
sprint: S1
parallel_with: [PR-Q1, PR-Q3]
dependencies: []
loc_estimate: 220
reviewer: quant
---

# Opus Prompt — PR-Q2: G2 ENB Meucci

## Goal

Ship Effective Number of Bets (Meucci 2009 entropy-based) and Minimum Torsion Bets (Meucci 2013) as a new pure-function service consumable by DD ch.5 and construction dashboards. Do not modify `factor_model_service.py` — derive factor covariance internally from `decompose_portfolio()` output.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §2 (G2 ENB Meucci — formulas, API, compat with factor_model_service, sanitized UI copy)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §4 (G2 non-conflict with G1)

## Files to create

1. `quant_engine/diversification_service.py` — pure functions:
   - `effective_number_of_bets(weights, factor_loadings, factor_cov, method="both") -> ENBResult`
   - Internal helpers: `_entropy_enb(risk_contributions)`, `_minimum_torsion(B, Sigma_f)`, `_risk_contributions(weights, B, Sigma_f)`
2. `backend/tests/quant_engine/test_diversification.py` — ≥8 unit tests per §2 validation list.

## Files NOT to modify

- `quant_engine/factor_model_service.py` — derive factor_cov internally via `np.cov(factor_returns.T)` inside `diversification_service`. If `factor_returns` is not readily available at caller site, accept `factor_cov` as parameter and let caller compute it.
- Any scoring or optimizer code — G2 is a leaf service with no hot-path callers in this PR.

## Implementation hints

### ENB entropy (Meucci 2009)
```
p_f = B.T @ w                    # factor exposures, shape (K,)
var_p = p_f @ Sigma_f @ p_f      # portfolio variance
contrib = p_f * (Sigma_f @ p_f)  # elementwise
rc = contrib / var_p             # risk contributions sum to 1
enb_entropy = np.exp(-np.sum(rc * np.log(rc + 1e-12)))
```
Handle RC close to 0 with epsilon in log.

### Minimum Torsion (Meucci 2013)
Solve rotation T orthogonal s.t. `T' Σ_f T = I` minimizing `||T - B||_F`. Closed-form via Schur decomposition of `Σ_f^(1/2)`:
```
L = sqrt Sigma_f (symmetric via eigendecomp, clamp eigenvalues ≥ 0)
torsion = L^{-1} @ B @ (B.T @ Sigma_f @ B)^{-1/2}
```
See Meucci 2013 §4 for derivation. Alternative: use `scipy.linalg.sqrtm` for matrix square root.

### API

```python
@dataclass(frozen=True)
class ENBResult:
    enb_entropy: float
    enb_minimum_torsion: float | None
    risk_contributions: np.ndarray  # shape (K,)
    factor_exposures: np.ndarray    # shape (K,)
    method: Literal["entropy", "minimum_torsion", "both"]
    n_factors: int
    degraded: bool
```

Degraded triggers: non-PSD `Sigma_f` (eig min < -1e-8), singular B'ΣB, var_p ≤ 0, any NaN in outputs.

## Tests (minimum 8)

1. Uniform RC: build `Sigma_f = I_K`, `B` such that `p_f = 1_K / sqrt(K)` → `N_ent = K` exact (tol 1e-6)
2. Degenerate: `w` puts all mass on one asset loading on one factor → `N_ent → 1`
3. MT ≥ entropy: for any valid (w, B, Sigma_f) with correlated factors, `enb_minimum_torsion ≥ enb_entropy` (Meucci property)
4. Shape coverage: (N,K) = (100,5), (10,5), (5,20)
5. Non-PSD Sigma_f → degraded=True
6. NaN in weights → degraded=True
7. K=1 edge → ENB = 1.0
8. method="entropy" returns None for `enb_minimum_torsion`; "minimum_torsion" returns float; "both" returns both floats

## Acceptance gates

- `make check` green
- Zero modifications to `factor_model_service.py`
- Pure function — no I/O, no DB, no async, no module-level state
- Deterministic for same inputs (set random seed nowhere; function is closed-form)

## Non-goals

- Do NOT wire G2 into scoring or optimizer in this PR — it's consumed by DD ch.5 (separate PR for wiring) and construction dashboard (after PR-Q9 integration)
- Do NOT add sanitized UI copy to any frontend file — frontend wiring is follow-up
- Do NOT build a CLI or admin tool

## Branch + commit

```
feat/quant-g2-enb-meucci
```

PR title: `feat(quant/g2): effective number of bets (Meucci 2009 + Minimum Torsion 2013)`
