---
pr_id: PR-Q9
title: "feat(quant/g5): IPCA production (Kelly-Pruitt-Su, 6 chars) + 4th attribution rail"
branch: feat/quant-g5-ipca-prod
sprint: S5
dependencies: [PR-Q4, PR-Q5, PR-Q8]
loc_estimate: 1100
reviewer: quant
---

# Opus Prompt — PR-Q9: G5 IPCA Production (Option A)

## Goal

Ship Instrumented Principal Component Analysis (Kelly-Pruitt-Su 2019) as a production factor model, fit quarterly on the 6-char equity characteristics panel from PR-Q8, and wire as the 4th rail in the attribution cascade. This is the academic differentiator vs static PCA.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §5 (IPCA model, library choice, panel, architecture), §6 (4th-rail attribution formula)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-strategy.md` §6 (confidence badge enum, dispatcher priority)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §8 (timeline)
- Kelly, Pruitt, Su 2019 JFE paper (for formulas; do not re-derive)
- `github.com/bkelly-lab/ipca` — library to adopt

## Files to create

1. `quant_engine/factor_model_ipca_service.py` — production service with same interface as `factor_model_service.py`:
   - `decompose_portfolio(returns_matrix, config: IPCAConfig) -> FactorDecomposition`
   - `fit_universe(panel, characteristics, K) -> IPCAFit`
2. `quant_engine/ipca/__init__.py`
3. `quant_engine/ipca/fit.py` — wraps `bkelly-lab/ipca` IPCARegressor for fitting, handles convergence diagnostics
4. `quant_engine/ipca/drift_monitor.py` — computes Γ drift across refits; raises alert if `||Γ_new - Γ_old||_F / ||Γ_old||_F > 0.25`
5. `backend/app/core/jobs/ipca_estimation.py` — worker with lock 900_092. Quarterly fit + persist.
6. `backend/alembic/versions/0136_factor_model_fits.py` — table `factor_model_fits` (fit_id PK, engine 'pca'|'ipca', fit_date, universe_hash, K, gamma_loadings JSONB, factor_returns JSONB, oos_r_squared NUMERIC, converged BOOL, n_iterations INT).
7. `vertical_engines/wealth/attribution/ipca_rail.py` — 4th rail implementation.
8. `backend/tests/quant_engine/test_ipca.py` — ≥20 tests
9. `backend/tests/vertical_engines/wealth/test_attribution_ipca_rail.py` — ≥5 dispatcher tests

## Files to modify

1. `pyproject.toml` — add `ipca` (from `bkelly-lab/ipca`) dependency. Pin exact version.
2. `vertical_engines/wealth/attribution/service.py` — update dispatcher priority: HOLDINGS → IPCA → PROXY → RETURNS → NONE. IPCA only enters if `FactorModelFit` exists for fund's asset class AND OOS R² ≥ 0.50.
3. `vertical_engines/wealth/attribution/models.py` — add `IPCAResult` with `factor_exposures`, `factor_returns_contribution`, `alpha`, `confidence`, `factor_names`.
4. `vertical_engines/wealth/dd_report/chapters/ch4_performance.py` — render IPCA exposure table ("Style exposures: Value X%, Momentum Y%, Quality Z%, ...") with badge `MEDIUM-HIGH CONFIDENCE — factor model`. Zero raw β values in copy.
5. `CLAUDE.md` Data Ingestion Workers table — add worker 900_092.

## Implementation hints

### Fit flow

```python
from ipca import InstrumentedPCA

def fit_ipca(
    panel_returns: pd.DataFrame,       # MultiIndex (instrument_id, month), column 'return'
    characteristics: pd.DataFrame,     # MultiIndex (instrument_id, month), columns = 6 chars
    K: int,
    intercept: bool = False,           # unrestricted vs restricted
    max_iter: int = 200,
    tolerance: float = 1e-6,
) -> IPCAFit:
    reg = InstrumentedPCA(n_factors=K, intercept=intercept,
                          max_iter=max_iter, iter_tol=tolerance)
    reg.fit(X=characteristics.values, y=panel_returns.values,
            indices=characteristics.index)
    gamma = reg.Gamma                  # L×K (Γ_β) or (L+1)×K with intercept
    factor_returns = reg.Factors       # K×T
    r_squared_total, r_squared_predictive = reg.score()
    return IPCAFit(
        gamma=gamma, factor_returns=factor_returns, K=K,
        intercept=intercept, r_squared=r_squared_total,
        oos_r_squared=None,            # computed separately via walk-forward
        converged=reg.converged,
        n_iterations=reg.n_iter,
    )
```

### K selection

Walk-forward cross-validation: train 60-month window, test 12-month. Slide annually. For K ∈ {1..6}, pick K maximizing average OOS R². Store chosen K and OOS R² on `factor_model_fits`.

### Attribution via IPCA (4th rail)

```python
async def run_ipca_rail(request: AttributionRequest) -> IPCAResult | None:
    fit = await load_latest_ipca_fit(asset_class=request.fund_asset_class)
    if not fit or fit.oos_r_squared < 0.50:
        return None

    # For the fund, compute its exposure vector β = Γ' z_fund where z_fund is latest characteristics snapshot
    fund_chars = await load_fund_characteristics(request.fund_instrument_id, request.period_end)
    if fund_chars is None:
        return None
    beta = fit.gamma.T @ fund_chars           # shape (K,)
    factor_returns_period = fit.factor_returns_for_period(request.period_start, request.period_end)
    contribution_per_factor = beta * factor_returns_period.mean(axis=1)  # elementwise
    alpha = await estimate_alpha(request.fund_cik, fit)

    return IPCAResult(
        factor_names=["Size", "Value", "Momentum", "Quality", "Investment", "Profitability"][:fit.K],
        factor_exposures=beta.tolist(),
        factor_returns_contribution=contribution_per_factor.tolist(),
        alpha=alpha,
        confidence=fit.oos_r_squared,
    )
```

Note: funds in the cascade are not necessarily the equities in the fit panel. The fit produces factor returns $f_t$ per period; the fund's exposure β can be estimated by time-series regression of fund returns on $f_t$. Choose one of:
- **Option A (simpler):** time-series regression `r_fund_t = α + β' f_t + ε_t`, report β and α directly
- **Option B (instrumented):** assume fund inherits weighted-average characteristics of its top-10 N-PORT holdings; use IPCA's implied-β formula

Ship Option A in this PR; Option B is follow-up.

### Worker

Lock 900_092. Quarterly (last day of March/June/Sep/Dec, 06:00 UTC). Refits for each asset class with panel ≥ 300 instrument-months. Persists to `factor_model_fits`. Drift monitor compares `gamma` matrices and alerts if drift > 0.25.

### Dispatcher priority (final)

```
HOLDINGS → IPCA → PROXY → RETURNS → NONE
```

IPCA slots between HOLDINGS and PROXY because:
- IPCA gives cross-sectional factor attribution even when N-PORT is stale — more insightful than proxy ETF tracking error
- IPCA confidence is OOS R², genuinely calibrated

## Tests

### IPCA unit tests (≥20)
1. Synthetic K=3 fit: recover Γ within `||Γ_hat - Γ_true||_F < 0.05`
2. Convergence in ≤100 iter on synthetic panel
3. Non-convergence path: max_iter reached → converged=False, logged
4. K=1 edge: single latent factor fit succeeds
5. K=6 edge: matches number of characteristics
6. Missing characteristic column → raises explicit error
7. Unbalanced panel (some instrument-months missing) → library handles or raises clearly
8. Restricted (α=0) vs unrestricted — both work, different Γ shapes
9. Walk-forward OOS R²: test on 100-month fixture panel; OOS ≥ PCA baseline
10. Drift monitor: two identical Γs → drift = 0
11. Drift monitor: Γ scaled by 2 → drift ≈ 1
12. `factor_model_fits` row persisted with correct JSONB shape
13. Multiple asset classes: separate fits per class
14. Determinism: same panel → same Γ (seed)
15. FactorDecomposition output compatible with existing `factor_model_service` consumers
16. Time-series β estimation for fund: regression-based
17. α estimation: constant term in time-series regression
18. IPCA confidence mapped from OOS R²
19. Fallback: if IPCA fit absent for asset class, service returns None (not crash)
20. Fit serialization round-trip (JSONB encode/decode)

### Dispatcher tests (≥5)
1. IPCA rail wins when OOS R² ≥ 0.50 and HOLDINGS unavailable
2. IPCA rail skipped when OOS R² < 0.50
3. Priority order: HOLDINGS → IPCA → PROXY → RETURNS
4. Badge correctly set to RAIL_IPCA
5. Fund with no characteristics → rail returns None, dispatcher falls through

## Acceptance gates

- `make check` green
- `ipca` package added with exact pin
- Migration 0136 reversible
- Walk-forward OOS R² on 500-equity panel ≥ static PCA baseline in ≥70% of quarterly windows — documented in PR description as benchmark table
- DD ch.4 renders IPCA exposure table with sanitized factor names; invariant scanner finds zero raw β values
- Drift monitor produces non-spurious alerts (test with stable Γ → no alert)
- Worker completes fit for 500-equity × 120-month panel in <15min
- P5 idempotent worker

## Non-goals

- Do NOT expand universe beyond 500 — separate sprint
- Do NOT implement Option B (N-PORT-weighted characteristics inheritance) — follow-up
- Do NOT add Bayesian posteriors over Γ (paper appendix, 10× compute cost)
- Do NOT auto-flip Global factor model engine from PCA to IPCA — engine choice stays per-tenant ConfigService flag (`factor_model.engine`), default "pca"
- Do NOT re-estimate alpha with Jegadeesh-Titman corrections in this PR
- Do NOT remove `factor_model_service.py` (PCA) — both coexist

## Branch + commit

```
feat/quant-g5-ipca-prod
```

PR title: `feat(quant/g5): IPCA production (Kelly-Pruitt-Su 6 chars) + 4th attribution rail`

PR description must include: benchmark table (IPCA vs PCA walk-forward OOS R² over 10 years), one-paragraph summary of K selection, link to Kelly-Pruitt-Su 2019 paper.
