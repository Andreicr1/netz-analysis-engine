# Construction Engine Upgrade — Phase A

**Date:** 2026-04-14
**Branch:** `feat/construction-engine-phase-a`
**Priority:** CRITICAL — current 1Y-only estimator is institutionally substandard
**Sessions:** 4 PRs, ~2 weeks
**Author of decisions:** Andrei + wealth-portfolio-quant-architect (design doc 2026-04-14)

---

## Context

Greenfield environment. No real capital at risk yet. No shadow-mode / feature-flag overhead required — build the definitive estimator straight into production, with the saved engineering time reallocated to **adversarial static tests that stress the solver math before the UI plugs in**.

The current `compute_fund_level_inputs()` (in `backend/app/domains/wealth/services/quant_queries.py:462`) runs a **single 1Y rectangular window** for covariance, expected returns, and higher moments. With the expanded data (`return_5y_ann` at 82% coverage, `return_10y_ann` at 47%, 60% of 6,164 instruments with 10Y+ NAV history, GARCH at 100%, DTW globalized at 93.5%), the pipeline is ready for a multi-horizon Bayesian-factor estimator.

This sprint delivers **Phase A of the quant architect's design doc** — the high-ROI vertical slice that replaces the point estimator with:

- **5Y EWMA covariance** (λ=0.97, half-life 23d)
- **Three-Horizon Bayesian Blend (THBB)** for expected returns (10Y CAGR + 5Y CAGR + implied equilibrium as prior; 1Y mean as view)
- **Hybrid factor model** (fundamental factors for covariance structure, PCA on residuals only for diagnostic)
- **3Y window for higher moments** (skew/kurt)
- **κ(Σ) condition-number guardrail** as a first-class, fail-loud constraint

Phase A.2 (stress replay redesign) is deferred. Phase B (DCC-GARCH, regime-mixture cov, GARCH higher moments) is deferred. Phase C (point-in-time snapshots, tail copulas, Stambaugh MLE) is deferred.

---

## Locked-in decisions (do NOT re-open)

| # | Decision | Rationale |
|---|---|---|
| 1 | No shadow mode, no feature flags, no rollback automation | Greenfield; saved effort goes into adversarial solver tests |
| 2 | Legacy `POST /portfolios/{id}/construct` and legacy parametric stress route **frozen**; new engine wired to the brutalist terminal only | Legacy UI is read-only "fluff" for bankers; serious allocation happens in the terminal |
| 3 | `γ` (risk aversion) **fixed at 2.5** — documented institutional default, overridable ONLY via ConfigService with audit trail | Avoids whipsaw de-risking at market trough; keeps attribution clean. If IC mandates change (e.g., "increase risk aversion for defensive sleeve"), the change goes through `ConfigService.get("wealth", "construction", org_id)["risk_aversion"]` with `AuditEvent` write. Never hardcode a second value. |
| 4 | Survivorship bias **accepted** in Phase A, but **flagged explicitly** in `inputs_metadata` | Prove architecture first; CRSP/Morningstar cost not justified yet. Quantified impact: +50-150bps/year upward bias on expected returns estimated from surviving-fund 10Y CAGR. Flag `survivorship_bias_accepted: true` + `estimated_bias_bps_annual: [50, 150]` in JSONB. IC must see this on every run. |
| 5 | Hybrid factor model: **fundamental factors for covariance, PCA strictly on residuals for diagnostic** | Explicability to IC first, statistical optimality second |
| 6 | κ(Σ) monitoring **embedded in PR-A1** — not a later add-on | Backend must fail loudly before optimizer produces extreme weights |
| 7 | Phase A.2 (stress replay) deferred to post-A1-A4 merge | Keeps the 2-week vertical slice tight |
| 8 | Legacy parametric stress (`POST /stress-test`) **untouched** | Frozen for banker read-only UI |

---

## Architecture — Phase A target state

### 1. Covariance

```
Σ_annual = B · F · B' + D          (factor-augmented, N ≥ 20)
Σ_annual = Σ_EWMA_shrunk            (single-index fallback, N < 20)

where:
  F = 5Y EWMA cov of K=8 fundamental factor returns
  B = N×K fundamental factor loadings (5Y OLS with LW shrinkage)
  D = diagonal GARCH-filtered idiosyncratic variance
```

Factor set (K=8 fundamental factors from `benchmark_nav` + `macro_data`):

| # | Factor | Proxy series | Source |
|---|---|---|---|
| 1 | US equity beta | SPY return (daily) | `benchmark_nav` |
| 2 | Duration | IEF (7-10Y Treasury) daily return | `benchmark_nav` |
| 3 | Credit spread | HYG return − IEF return (carry-neutralized) | `benchmark_nav` |
| 4 | USD strength | DXY / DTWEXBGS daily return | `macro_data` |
| 5 | Commodity | DCOILWTICO daily return | `macro_data` |
| 6 | Size | IWM return − SPY return | `benchmark_nav` |
| 7 | Value | IWD return − IWF return | `benchmark_nav` |
| 8 | International | EFA return − SPY return | `benchmark_nav` |

If a factor proxy is missing from `benchmark_nav`, the fallback list is in PR-A3 §3.2.

### 2. Expected returns (THBB)

```
μ₀ (prior) = w_10 · return_10y_ann + w_5 · return_5y_ann + w_eq · π_implied

  where π_implied = γ · Σ · w_benchmark    (He-Litterman 1999 reverse optimization)
        γ = 2.5 (fixed)
        w_benchmark = strategic weights for profile (from mandate)

  Weight schedule (availability-conditional, renormalized to 1.0):
    10Y + 5Y + eq available:     w_10=0.5,  w_5=0.3,  w_eq=0.2
    5Y + eq only:                w_10=0.0,  w_5=0.7,  w_eq=0.3
    1Y only or eq only:          w_10=0.0,  w_5=0.0,  w_eq=1.0   (pure equilibrium)

μ̂_1Y (view) = annualized 1Y daily mean, with Ω_ii = σ_i² (standard error of the mean)
IC views    = existing `portfolio_views` table, each with its own Ω from `confidence`

μ_posterior = BL(μ₀, Σ, views=[data_view, *ic_views], τ=0.05, γ=2.5)

μ_net = μ_posterior − expense_ratio_pct / 100
```

### 3. Higher moments

```
skewness_i       = scipy.stats.skew(r_i[-756:], bias=False)              # 3Y
excess_kurtosis_i = scipy.stats.kurtosis(r_i[-756:], fisher=True)         # 3Y

with winsorization at 1%/99% before estimation
```

### 4. κ(Σ) guardrail

```
κ(Σ) = np.linalg.cond(Σ_annual)

if κ > 1e4:
    raise IllConditionedCovarianceError(κ, N, T, ...)
elif κ > 1e3:
    logger.warning("construction.covariance_poorly_conditioned", κ=κ, ...)
    # MUST force robust=True in the caller to optimize_fund_portfolio().
    # Phase 1.5 (robust SOCP, ellipsoidal uncertainty set) exists at
    # optimizer_service.py:545 but is GATED BY the `robust` param — there is
    # no automatic fallback today. The `inputs_metadata.kappa_warning_triggered`
    # flag MUST be consumed by the route/worker and passed as `robust=True`
    # to the optimizer. Do NOT silently degrade.
```

`κ`, `N`, `T`, and factor-model summary all written to `portfolio_construction_runs.inputs_metadata` JSONB.

**Verified pre-existing capability (2026-04-14, by Andrei):**
- `optimize_fund_portfolio()` at `optimizer_service.py:545` implements Ben-Tal/Nemirovski robust counterpart with χ²_{0.95, n}-calibrated κ. Activated by `robust=True` kwarg. Cholesky fallback to eigenvalue-clipped `L` handles near-PSD matrices. Works today.

---

## PR sequence

### PR-A1: Core estimator + κ(Σ) guardrail + adversarial solver tests

**Goal:** replace the point estimator with the multi-horizon Bayesian-factor core and embed the κ(Σ) fail-loud rule. Adversarial tests land in this PR so no UI can be wired until the math is proven on pathological matrices.

**Files to touch:**

- `backend/app/domains/wealth/services/quant_queries.py`
  - `compute_fund_level_inputs()` — new signature:
    ```python
    async def compute_fund_level_inputs(
        db: AsyncSession,
        instrument_ids: list[uuid.UUID],
        *,
        cov_lookback_days: int = 1260,          # 5Y
        higher_moments_window: int = 756,       # 3Y
        ewma_lambda: float = 0.97,
        mu_prior: Literal["thbb", "historical_1y", "equilibrium"] = "thbb",
        as_of_date: date | None = None,
        config: dict[str, Any] | None = None,
        portfolio_id: uuid.UUID | None = None,
        profile: str | None = None,
    ) -> FundLevelInputs:  # frozen dataclass — see below
    ```
  - Return a **frozen dataclass** `FundLevelInputs` (not a tuple) with:
    ```python
    @dataclass(frozen=True)
    class FundLevelInputs:
        cov_matrix: np.ndarray
        expected_returns: dict[str, float]
        available_ids: list[str]
        skewness: np.ndarray
        excess_kurtosis: np.ndarray
        condition_number: float
        factor_loadings: np.ndarray | None  # (N, K) or None if N < 20
        factor_names: list[str] | None
        residual_variance: np.ndarray | None  # D diagonal
        prior_weights_used: dict[str, float]  # {"10y": 0.5, "5y": 0.3, "eq": 0.2}
        n_funds_by_history: dict[str, int]    # {"10y+": 30, "5y+": 45, "1y_only": 5}
        regime_probability_at_calc: float | None
        used_return_type: str                 # "log" or "arithmetic"
        lookback_start_date: date
        lookback_end_date: date
    ```
  - New helper `_compute_ewma_covariance(returns_matrix, lambda_=0.97)` — weights decay by `λ^(T-t)`.
  - New helper `_build_thbb_prior(instruments, fund_risk_metrics_rows, Σ, γ, w_benchmark)` — assembles the 10Y/5Y/equilibrium blend per availability.
  - New helper `_build_data_view(returns_matrix, available_ids)` — returns `(P, Q, Ω)` for BL.
  - New helper `_compute_condition_number(Σ)` — returns `np.linalg.cond(Σ)`.
  - New exception `IllConditionedCovarianceError(Exception)` raised when `κ > 1e4`.
  - The 3Y higher-moments slice must be taken from the tail of the 5Y returns matrix — no separate DB round-trip.

- `backend/app/domains/wealth/services/quant_queries.py`
  - Keep `compute_inputs_from_nav()` (block-level proxy) **unchanged** for the legacy route.

- `backend/quant_engine/black_litterman_service.py`
  - Keep existing `compute_bl_returns()` signature. Add a new entry point for multi-view stacking in PR-A2 (not here).

- `backend/tests/quant_engine/test_construction_adversarial.py` (NEW)
  - Test `IllConditionedCovarianceError` raises when:
    1. **Singular matrix:** N funds > T obs (e.g., N=50, T=40) — must raise with clear message naming `κ = inf`.
    2. **Near-singular (κ ≈ 1e5):** two fully-collinear funds — must raise.
    3. **Non-PSD input:** inject a matrix with one negative eigenvalue `-1e-4` post-shrinkage — PSD-repair path must clamp it and log, not raise.
    4. **NaN/Inf in returns:** must be detected pre-estimation, fund excluded with audit log.
    5. **Zero-variance fund:** std=0 in window — excluded with audit log.
  - Test `compute_fund_level_inputs` on a **known analytic case**: synthetic 3-fund universe with known μ, Σ, and return_10y_ann. Assert:
    - `condition_number < 100` (well-conditioned)
    - THBB prior weights = {"10y": 0.5, "5y": 0.3, "eq": 0.2} when all three available
    - Fallback to eq-only when only 1Y data exists
    - `used_return_type` honors the DB `return_type` column
  - Test `_compute_ewma_covariance`:
    - λ=1.0 must equal sample covariance exactly (up to 1e-10)
    - λ=0.94 (RiskMetrics) gives documented half-life
    - Weights sum to 1.0 within 1e-10
  - Test κ > 1e3 warning → `robust_mode_activated` flag:
    - Construct a near-singular Σ (κ ≈ 5e3)
    - Assert `inputs_metadata.kappa_warning_triggered == True`
    - Assert the route/worker calls `optimize_fund_portfolio(..., robust=True)` — verify via mock spy
    - Assert `inputs_metadata.robust_mode_activated == True`
  - Test γ sourcing:
    - Default run → `inputs_metadata.risk_aversion_source == "institutional_default"`, `risk_aversion_gamma == 2.5`
    - ConfigService override (mocked with `org_id` having `{"risk_aversion": 3.5}`) → `risk_aversion_source == "config_override"`, `risk_aversion_gamma == 3.5`, + `AuditEvent` written with before/after
    - Test assertion: every γ change produces an `AuditEvent` row — no silent override

- `backend/tests/quant_engine/test_construction_integration.py` (NEW)
  - End-to-end on a real 20-fund selection from `instruments_universe` with sufficient history. Assert:
    - `FundLevelInputs.factor_loadings` shape `(N, 8)`
    - `FundLevelInputs.condition_number < 1e3` on realistic market data
    - No exception raised
    - Residual variance (`D`) is strictly positive

**Acceptance criteria:**
- `make check` passes
- Adversarial test file has **≥ 15 test cases** covering all pathological inputs
- `FundLevelInputs` dataclass is `frozen=True` (thread-safe across async boundary)
- `IllConditionedCovarianceError` message includes `κ`, `N`, `T`, sample of worst-conditioned eigenvalues
- Audit event written on every κ > 1e3 (warning) and κ > 1e4 (error)
- Zero imports of the old tuple-return signature remain

---

### PR-A2: Black-Litterman multi-view + THBB prior

**Goal:** extend BL to accept stacked views (data view + IC views) and consume the THBB prior instead of historical 1Y mean.

**Files to touch:**

- `backend/quant_engine/black_litterman_service.py`
  - Add:
    ```python
    @dataclass(frozen=True)
    class View:
        P: np.ndarray             # (m, N) picking matrix (m views)
        Q: np.ndarray             # (m,) view expected returns
        Omega: np.ndarray         # (m, m) view uncertainty
        source: Literal["data_view", "ic_view"]
        confidence: float | None  # for ic_view provenance
    ```
  - Add `compute_bl_posterior_multi_view(mu_prior, sigma, views: list[View], tau: float = 0.05) -> np.ndarray`:
    - Stack: `P = vstack([v.P for v in views])`, `Q = concat`, `Ω = block_diag`
    - Standard BL posterior formula
    - Keep existing `compute_bl_returns()` (single-view) as a thin wrapper for backward compatibility
  - τ is a float parameter (fixed 0.05 default) — no regime conditioning in Phase A.
  - **Ω regularization (critical — Ω singular crashes `solve`):**
    - Before any `np.linalg.solve(Ω, ...)` or `np.linalg.inv(P @ τΣ @ P.T + Ω)`, enforce:
      ```python
      eps = 1e-8 * np.trace(Omega) / max(Omega.shape[0], 1)
      Omega_reg = Omega + eps * np.eye(Omega.shape[0])
      ```
    - Alternative: use `np.linalg.pinv(Omega)` directly (Moore-Penrose pseudoinverse) if regularization causes condition-number issues downstream.
    - A confidence=1.0 IC view (`Ω_ii → 0`) must produce a posterior that respects the view without raising `LinAlgError`.
    - Test this edge case explicitly in `test_black_litterman_multi_view.py`: IC view with confidence=0.999 and confidence=1.0 — both must converge numerically.

- `backend/app/domains/wealth/services/quant_queries.py`
  - `_build_thbb_prior()` implementation:
    - Query `fund_risk_metrics` once for `return_10y_ann`, `return_5y_ann` per instrument_id at `as_of_date`
    - Query `mandate_strategic_weights` (or reuse `fetch_strategic_weights_for_funds` if it already pulls by profile)
    - Compute `π = γ * Σ * w_benchmark` (use Σ from factor model — PR-A3 delivery — or 5Y EWMA for PR-A2)
    - Per-instrument availability-conditional weights → blend → return μ₀ vector ordered as `available_ids`
  - `_build_data_view()` implementation:
    - `P = I_N` (identity, each fund has its own view of its own mean)
    - `Q = annualized_daily_mean_1Y`
    - `Ω = diag(σ_i² / N_obs)` where `σ_i` is 1Y daily stdev × √252
  - `_build_ic_views(portfolio_id, available_ids)`:
    - Pull `portfolio_views` rows
    - Map `confidence` ∈ [0,1] to `Ω` via `Ω_ii = (1 - confidence) / confidence * σ_prior_i²` (standard BL interpretation)

- `backend/tests/quant_engine/test_black_litterman_multi_view.py` (NEW)
  - Test that single `View` in the list yields identical result to legacy `compute_bl_returns()`
  - Test that two stacked views (data + IC) combine correctly — posterior lies between prior and both views
  - Test edge case: IC view with very high confidence (Ω → 0) — posterior for that fund should match the IC view
  - Test edge case: data view with very high Ω (low confidence) — posterior stays near prior

**Acceptance criteria:**
- `make check` passes
- THBB prior weights respect the availability schedule
- Multi-view BL produces mathematically consistent results on analytic test cases
- τ=0.05 fixed, documented in code that regime-conditional τ is Phase B

---

### PR-A3: Hybrid factor model (fundamental + PCA residual)

**Goal:** replace single-shrinkage-target Ledoit-Wolf with fundamental-factor-decomposed covariance. PCA kept strictly as a residual diagnostic, never as the primary estimator.

**Files to touch:**

- `backend/quant_engine/factor_model_service.py`
  - Add `build_fundamental_factor_returns(db, start_date, end_date) -> pd.DataFrame`:
    - Pulls the 8 factor proxies from `benchmark_nav` + `macro_data`
    - Returns aligned daily returns DataFrame indexed by date, columns = factor names
    - Forward-fill limit 3 days (matches fund return policy)
  - Add `fit_fundamental_loadings(fund_returns_matrix, factor_returns, ewma_lambda=0.97) -> FundamentalFactorFit`:
    - Per-fund OLS regression on 5Y daily with EWMA weights
    - Ledoit-Wolf shrinkage applied to `F` (the 8×8 factor cov), not to `B`
    - Residual series returned for PCA diagnostic
  - Add `FundamentalFactorFit` dataclass:
    ```python
    @dataclass(frozen=True)
    class FundamentalFactorFit:
        loadings: np.ndarray           # B: (N, K=8)
        factor_cov: np.ndarray         # F: (K, K) annualized
        residual_variance: np.ndarray  # D diagonal: (N,)
        factor_names: list[str]
        residual_series: np.ndarray    # (T, N) for PCA diagnostic
        r_squared_per_fund: np.ndarray # (N,) — explained variance per fund
    ```
  - `assemble_factor_covariance(fit: FundamentalFactorFit) -> np.ndarray`:
    - Returns `Σ = B · F · B' + diag(D)`
    - Applies PSD enforcement (eigenvalue clamp at `max(1e-10, 1e-8 * trace(Σ)/N)`)
    - **Type signature enforcement:** this function's signature takes `FundamentalFactorFit` **only**. It MUST NOT accept `PCADiagnostic` or any residual-PCA type as a parameter. This is checked by the type system (mypy) at `make check`, not by runtime grep.
  - Keep existing PCA function untouched. Add `compute_residual_pca(residual_series, n_components=3) -> PCADiagnostic` — **diagnostic only**, writes to `portfolio_construction_runs.inputs_metadata.residual_pca` for audit. Never feeds back into `Σ`.
  - `PCADiagnostic` is a separate frozen dataclass whose only consumer is the JSONB audit writer. It is never imported by `assemble_factor_covariance`, `compute_fund_level_inputs`, or any optimizer code. Enforce via explicit import hygiene: `assemble_factor_covariance`'s module MUST NOT `from factor_model_service import PCADiagnostic`.

- `backend/app/domains/wealth/services/quant_queries.py`
  - Modify `compute_fund_level_inputs()` to call `factor_model_service` when `N ≥ 20`, else fall back to 5Y EWMA + LW single-index shrinkage (keep existing LW path, retarget from constant-correlation to single-index).
  - Populate `FundLevelInputs.factor_loadings` and `residual_variance` accordingly.

- `backend/tests/quant_engine/test_fundamental_factor_model.py` (NEW)
  - Test `build_fundamental_factor_returns` returns all 8 factors on a date range where all proxies exist
  - Test fallback behavior when one proxy is missing (documented in §3.2 below)
  - Test `fit_fundamental_loadings` on synthetic data:
    - Known β → recovered β within noise tolerance
    - EWMA weights yield documented effective window
  - Test `assemble_factor_covariance` output is:
    - PSD (all eigenvalues ≥ 1e-10)
    - Symmetric (up to 1e-12)
    - Diagonal dominated by B F B' + D decomposition
  - Test residual PCA **is not fed back** into Σ (regression check — a grep or mock assertion)

**Factor proxy fallback list (§3.2) — NEVER substitute a level change where a total return is specified. Level changes and total returns are not interchangeable and introduce systematic bias.**

| Primary | Fallback 1 | Fallback 2 |
|---|---|---|
| SPY | `benchmark_nav` SPX total-return composite | **skip**, reduce to K=7 |
| IEF | 7-10Y Treasury total return from benchmark_nav | **skip Duration factor** — do NOT synthesize from DGS10/DGS2 level changes (yield changes ≠ bond returns without duration multiplier + convexity adjustment). Reduce to K-1. |
| HYG | benchmark_nav HY total return | **skip Credit factor** — do NOT use `BAMLH0A0HYM2` OAS level change. OAS is a spread level, not a return; differencing it produces a bp-change time series with wrong units, wrong variance structure, and zero carry. Reduce to K-1. |
| DXY | DTWEXBGS from macro_data | skip factor, reduce to K=7 |
| DCOILWTICO | direct from macro_data | skip factor, reduce to K=7 |
| IWM | `benchmark_nav` small-cap total return | skip Size factor |
| IWD / IWF | Value / Growth total return indices | skip Value factor |
| EFA | `benchmark_nav` MSCI EAFE total return | skip International factor |

When a factor is skipped, log audit event (`factor_skipped` with reason), reduce K accordingly, never inject synthetic data or proxies with incompatible units. Record skipped factors in `inputs_metadata.factor_model.factors_skipped`.

**Acceptance criteria:**
- `make check` passes
- Factor loadings recovered within 1% on synthetic data
- `Σ` always PSD, symmetric, non-singular
- Residual PCA written to audit JSONB but has zero feedback into primary estimation
- Fallback schedule for missing factors documented and tested

---

### PR-A4: Persistence + terminal API + brutalist UI integration

**Goal:** wire the new engine end-to-end into the brutalist terminal. Legacy routes untouched.

**Files to touch:**

- `backend/app/core/db/migrations/versions/0133_construction_inputs_metadata.py` (NEW)
  - Revision `0133_construction_inputs_metadata`, `down_revision = "0132_merge_0110_heads"`.
  - 0132 is the merge migration that reconciled the two 0110 heads (signal_breakdown vs compress_segmentby_fix). See `scripts/reconcile_0110_heads.py` and `0132_merge_0110_heads.py` docstring for the historical context. Current alembic state has a single head at 0132; this migration descends from it.
  - Add JSONB column to `portfolio_construction_runs`:
    ```python
    op.add_column("portfolio_construction_runs",
        sa.Column("inputs_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    ```
  - Schema of `inputs_metadata` (documented in code, not enforced by DB):
    ```json
    {
      "engine_version": "phase_a_v1",
      "cov_lookback_days": 1260,
      "ewma_lambda": 0.97,
      "higher_moments_window": 756,
      "risk_aversion_gamma": 2.5,
      "risk_aversion_source": "institutional_default",
      "tau_prior_confidence": 0.05,
      "condition_number": 123.4,
      "prior_weights": {"10y": 0.5, "5y": 0.3, "eq": 0.2},
      "n_funds_by_history": {"10y+": 30, "5y+": 45, "1y_only": 5},
      "regime_probability_at_calc": 0.35,
      "factor_model": {
        "used": true,
        "k_factors": 8,
        "k_factors_effective": 8,
        "factor_names": [...],
        "factors_skipped": [],
        "r_squared_mean": 0.72,
        "r_squared_p25": 0.48,
        "residual_pca_top3_explained": [0.12, 0.08, 0.05]
      },
      "used_return_type": "log",
      "lookback_start_date": "2021-04-14",
      "lookback_end_date": "2026-04-14",
      "kappa_warning_triggered": false,
      "kappa_error_triggered": false,
      "robust_mode_activated": false,
      "survivorship_bias_accepted": true,
      "estimated_survivorship_bias_bps_annual": [50, 150],
      "omega_regularization_epsilon": 1.2e-10
    }
    ```
  - **`kappa_warning_triggered: true`** MUST cause the route/worker to call `optimize_fund_portfolio(..., robust=True)`. Set `robust_mode_activated: true` in metadata when this gating fires.
  - **`survivorship_bias_accepted: true`** MUST be surfaced in the terminal UI (PR-A5 scope) as a visible provenance badge. IC must not be able to ignore this flag.

- `backend/app/domains/wealth/routes/model_portfolios.py`
  - **Do not touch** the existing `/construct` route — frozen for banker UI.
  - Add new route `POST /portfolios/{id}/construct/v2`:
    - Uses `compute_fund_level_inputs()` new signature with THBB default
    - Writes full `inputs_metadata` JSONB to `portfolio_construction_runs.inputs_metadata`
    - Returns response including `ConstructionInputsMetadataRead` for terminal consumption
    - Same auth, RLS, idempotency pattern as legacy route
  - Add `GET /portfolios/{id}/construction-runs/{run_id}/metadata` to read back metadata for the terminal.

- `backend/app/domains/wealth/schemas/model_portfolio.py`
  - New Pydantic schema `ConstructionInputsMetadataRead` mirroring the JSONB shape
  - Add to `ConstructionRunRead` response as optional field

- `backend/app/domains/wealth/workers/construction_run_executor.py`
  - Background job variant of `/construct/v2` — same estimator, async SSE progress
  - Writes `inputs_metadata` identically

- `frontends/wealth/src/routes/(terminal)/portfolios/[id]/construct/+page.svelte` (NEW or extended)
  - Brutalist-style panels displaying:
    - **Estimator provenance:** engine_version, cov_lookback_days, ewma_lambda, regime_probability
    - **Prior breakdown:** bar chart of 10y/5y/eq weights used (formatters from `@netz/ui`)
    - **Factor diagnostics:** r² distribution (p25/mean/p75), top-3 residual PCA explained variance
    - **κ(Σ) status:** numeric value, status badge (OK / WARN / ERROR with hard fallback shown)
    - **Fund history coverage:** counts of 10Y+/5Y+/1Y-only
  - SSE stream from `construction_run_executor` shows estimator stage transitions
  - All numbers through `@netz/ui` formatters (`formatNumber`, `formatPercent`, `formatDate`)
  - No `localStorage`, no `EventSource` (use `fetch()+ReadableStream` per CLAUDE.md)
  - Svelte 5 runes only (`$state`, `$derived`, `$effect`)

- `backend/tests/wealth/routes/test_construct_v2.py` (NEW)
  - Route test: happy-path construct on a 30-fund portfolio returns 200 with full metadata
  - Route test: ill-conditioned portfolio (3 collinear funds) returns 422 with `IllConditionedCovarianceError` details
  - Route test: legacy `/construct` still works unchanged
  - Route test: RLS enforced (cannot construct for another org's portfolio)

- `backend/tests/wealth/workers/test_construction_run_executor_v2.py` (NEW)
  - Background job completes, writes inputs_metadata, SSE events fire
  - Job cancellation mid-estimation is clean (no partial DB writes)

**Frontend acceptance criteria:**
- Terminal page renders κ(Σ), prior breakdown, factor r² on a real portfolio construction
- Failure mode (κ > 1e4) shows a brutalist error state with the exact exception message — no silent fallback
- All numbers formatted via `@netz/ui`
- Visual validation in browser (per `feedback_visual_validation.md`)

**Backend acceptance criteria:**
- `make check` passes
- New route lives alongside legacy — zero changes to legacy behavior
- Migration reversible (downgrade drops the JSONB column cleanly)
- Audit log entry per construction run

---

## Testing strategy (κ guardrail is the keystone)

The adversarial solver tests in PR-A1 are **the reason** we can skip shadow mode. They must prove the math breaks loudly on:

| Pathology | Expected behavior |
|---|---|
| Singular Σ (N > T) | `IllConditionedCovarianceError`, no solver call |
| Near-singular (κ ≈ 1e5) | `IllConditionedCovarianceError` |
| Non-PSD input | PSD repair clamps + logs; no exception |
| NaN/Inf in returns | Fund excluded pre-estimation with audit |
| Zero-variance fund | Fund excluded pre-estimation with audit |
| All-equal returns (degenerate) | Excluded via MIN_OBSERVATIONS + variance check |
| < MIN_OBSERVATIONS (120) aligned | `ValueError` with fund count message |
| Factor fit fails (rank deficient factor panel) | Fall back to single-index LW with audit |
| `return_10y_ann` all-missing for block | Prior weights renormalize to 5Y + eq |
| `return_5y_ann` + `return_10y_ann` both missing | Prior degenerates to pure equilibrium — must be flagged in audit |
| Empty IC views | Data view alone drives posterior |
| IC view with confidence=1.0 | Ω→0 edge case handled numerically |

Each pathology has its own test case. No UI plugs in until all of these are green.

---

## Out of scope (explicit deferrals)

- **Phase A.2 — Stress replay redesign.** Four historical windows (GFC/Euro/COVID/2022) + two parametric overlays. Separate sprint post A1-A4 merge. Legacy `/stress-test` stays frozen until then.
- **Phase B.** DCC-GARCH on factor returns, regime-mixture covariance, GARCH-implied higher moments. Separate sprint.
- **Phase C.** Point-in-time `risk_metrics_snapshots` table, tail copula CVaR, Stambaugh partial-sample MLE for unequal histories, survivorship correction via CRSP/Morningstar.
- **Shadow mode / feature flags / rollback automation.** Not built.
- **Changes to legacy banker UI.** Frozen.
- **Regime-conditional γ, regime-conditional τ, regime-conditional λ.** γ fixed at 2.5, τ fixed at 0.05, λ fixed at 0.97 in Phase A.
- **`compute_inputs_from_nav` (block-level proxy).** Untouched — legacy code path.

---

## Prerequisites (already in place — do not re-verify)

- `return_5y_ann` and `return_10y_ann` columns exist in `fund_risk_metrics` (migration 0131, applied)
- `dtw_drift_score` populated globally at 93.5% (previous sprint)
- `macro_data` has ICSA, TOTBKCR, PERMIT for regime signals (previous sprint)
- `benchmark_nav` has 22 tickers covering 1993-2026
- `nav_timeseries` has 20M rows, 60% of instruments with 10Y+ history
- GARCH(1,1) fits at 100% coverage in `fund_risk_metrics.volatility_garch`
- Regime classifier uses Profile A 40/60 weights with dynamic amplification

---

## Order of operations

1. PR-A1 (core estimator + κ + adversarial tests) merges. **Do not proceed to A2 until all adversarial tests green.**
2. PR-A2 (BL multi-view + THBB) merges. Verify BL math on analytic tests.
3. PR-A3 (fundamental factor model) merges. Verify Σ assembly + PSD on real portfolios.
4. PR-A4 (persistence + terminal API + UI) merges. Visual validation in browser.
5. Post-merge: run `run_global_risk_metrics` to confirm no regression. Run one construction on a test portfolio, inspect `inputs_metadata` JSONB manually.

---

## Definition of Done

- All 4 PRs merged into `main`
- `make check` green on main
- Terminal displays κ(Σ), prior breakdown, factor r² on a real construction
- A deliberately ill-conditioned test portfolio produces a loud backend error (not extreme weights)
- `portfolio_construction_runs.inputs_metadata` populated for every new run
- Zero regression on legacy `/construct` and legacy `/stress-test` routes
- Phase A.2 planning doc drafted in `docs/prompts/` for the next sprint

---

## References

- Architect design doc: this conversation, 2026-04-14
- Ledoit & Wolf (2003), "Honey, I Shrunk the Sample Covariance Matrix"
- He & Litterman (1999), "The Intuition Behind Black-Litterman Model Portfolios"
- Meucci (2005), *Risk and Asset Allocation*, Springer
- Michaud (1989), "The Markowitz Optimization Enigma"
- JPMorgan RiskMetrics (1996), λ calibration
- Current code: `backend/app/domains/wealth/services/quant_queries.py:462`, `backend/quant_engine/black_litterman_service.py`, `backend/quant_engine/factor_model_service.py`, `backend/quant_engine/correlation_regime_service.py`
