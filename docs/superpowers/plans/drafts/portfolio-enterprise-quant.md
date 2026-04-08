# Portfolio Enterprise Quant Layer — Design Document

> **Scope:** Quant layer ONLY. No DB schema, no chart rendering, no frontend Svelte. This document defines the calibration input surface, the Run Construct narrative payload, advisor surfacing, stress scenario alignment, validation gate, regime visibility, live monitoring math, rebalancing surface, scoring breakdown, and gaps. Sibling documents will own DB tables and frontend rendering.
>
> **Audience:** Backend quant engineers + product engineers consuming the route contracts. Sophisticated readers — institutional vocabulary is preserved in the technical sections, with a dedicated translation layer (Section B.5) for end-user copy.
>
> **Bound by:** `CLAUDE.md` (DB-first, ConfigService for runtime config, async-first, smart-backend/dumb-frontend, no inline number formatting on the frontend).

## Executive Summary

The current calibration UI exposes **2 inputs** (CVaR limit slider, max single fund weight slider). The quant engine accepts **63 distinct calibration inputs** across the 11-stage pipeline (Section A). Run Construct returns a single sanitized JSONB blob without phase trace, regime context, validation, advisor, or stress — Andrei's "opaque black box" complaint is empirically correct.

**Construction Advisor exists fully** at `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` (789 lines) with a complete dataflow: `analyze_block_gaps` → `rank_candidates` → `compute_holdings_overlap` → `project_cvar_historical` → `find_minimum_viable_set` → `build_advice`. It is wired to `POST /model-portfolios/{id}/construction-advice` (route line 563) but is **not folded into Run Construct**, so it requires a second API call the UI never makes.

**Validation gate is essentially missing.** Only `Composition.validate_weights()` (sum-to-1 check) exists. There is no structured pass/fail with checks for stale NAV, CVaR within limit, turnover cap, diversification floor, banned instruments, or universe approval status. The 11-stage pipeline reference document calls for it but the code does not implement it. This is a Sprint-1 deliverable.

**Stress scenarios in code:** Backend has 4 preset scenarios (`gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps`) in `stress_scenarios.PRESET_SCENARIOS` plus `custom`. The UI exposing different names is a frontend bug — the `POST /portfolio/{id}/stress-test` route already returns the canonical 4. Add a `GET /stress-test/scenarios` enumeration endpoint to make this self-describing.

**Regime visibility:** `regime_fit.py` worker (lock 900_026) persists `p_high_vol` and classified regime to `portfolio_snapshots.regime_probs` JSONB. There is no read endpoint for the calibration UI to surface "you are constructing under RISK_OFF, CVaR multiplier 0.85". Section F defines `GET /portfolio/regime/current`.

---

## Part A — Full calibration input surface (63 inputs across 16 categories)

This is the empirical audit of every parameter the 11-stage pipeline accepts, derived by reading `quant_engine/optimizer_service.py`, `regime_service.py`, `cvar_service.py`, `black_litterman_service.py`, `garch_service.py`, `factor_model_service.py`, `scoring_service.py`, `construction_advisor.py`, `stress_scenarios.py`, plus `calibration/config/profiles.yaml`, `limits.yaml`, `scoring.yaml`.

**Tier convention:**
- **Basic** (5 inputs): exposed by default to portfolio managers and IC users. Safe semantics, monotone behavior, well-understood by non-quants.
- **Advanced** (10 inputs): exposed in an "Advanced calibration" drawer for quant analysts and IC chair. May produce non-monotone outcomes; require disclaimer.
- **Expert** (48 inputs): hidden behind a feature-flagged "Quant lab" surface for the head of quantitative research. Misuse can produce silently unrealistic portfolios.

### A.1 — Optimizer Phase 1 (max risk-adjusted return)

| # | Input | Type | Range | Default | Stage | Mathematical role | Tier |
|---|---|---|---|---|---|---|---|
| 1 | `risk_free_rate` | float | [0.0, 0.20] | 0.04 | 5 | Anchor for Sharpe; subtracted from `mu` in objective | Advanced |
| 2 | `lambda_risk_aversion` | float | [0.5, 10.0] | resolved from `mandate` via `mandate_risk_aversion.resolve_risk_aversion` (Conservative≈4, Moderate≈2, Aggressive≈1) | 5 | Coefficient on `cp.quad_form(w, Σ)`. Mandate-bound — IC must override consciously | Advanced |
| 3 | `mandate` | enum | conservative \| moderate \| aggressive | from portfolio profile | 5 | Source of `lambda_risk_aversion` and `cvar_limit` defaults | Basic |
| 4 | `solver_max_iters` | int | [1000, 100000] | CLARABEL default | 5 | Solver wall-clock cap; rarely tuned | Expert |
| 5 | `solver_eps` | float | [1e-9, 1e-3] | CLARABEL default | 5 | KKT residual tolerance | Expert |

### A.2 — Optimizer Phase 1.5 (robust SOCP, ellipsoidal uncertainty)

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 6 | `robust_enabled` | bool | true \| false | false | 5 | Toggle Phase 1.5 on. Currently only fires when CVaR Phase 1 violates | Advanced |
| 7 | `robust_uncertainty_radius` | float | [0.0, 1.0] | None → χ²(0.95, n) (~4.0 at n=10) | 5 | κ scaling on the `‖L'w‖₂` penalty. Legacy callers passing 0.5 are rescaled to preserve behavior | Expert |
| 8 | `robust_confidence` | float | (0.50, 0.99) | 0.95 | 5 | Confidence (1-α) of the Gaussian uncertainty set; drives κ via `√χ²_{1-α, n}` | Expert |

### A.3 — Optimizer Phase 2 (variance-capped CVaR enforcement)

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 9 | `phase2_cf_normal_ratio_floor` | float | [1.05, 2.5] | 1.30 (literature) | 5 | Floor for the CF/Normal coefficient ratio used to derive σ_max from `cvar_limit`. See `optimizer_service` lines 660-666 | Expert |
| 10 | `cvar_alpha` | float | [0.01, 0.10] | 0.05 | 5 | Tail probability for parametric CVaR (95% → α=0.05). Also used in Cornish-Fisher | Advanced |

### A.4 — Optimizer Phase 3 (min-variance fallback)

No new tunable inputs — inherits position constraints from base. Only fires when Phases 1, 1.5, 2 all fail.

### A.5 — Turnover penalty (L1 slack)

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 11 | `turnover_cap` | float | [0.0, 1.0] | 0.25 | 5, 11 | Hard ceiling on `Σ|w_new − w_current|`. Not currently a hard constraint — only soft penalty | Basic |
| 12 | `turnover_lambda` | float | [0.0, 5.0] | 0.0 (off) | 5 | L1 weight `−λ·Σtᵢ` where `tᵢ ≥ |wᵢ−wᵢ_curr|`. When > 0 and infeasible, optimizer auto-retries without penalty (line 494) | Advanced |
| 13 | `dead_band_pct` | float | [0.001, 0.05] | 0.005 | 11 | Trade suppression threshold below which weight changes are ignored. Lives in `weight_proposer.apply_dead_band` | Advanced |

### A.6 — Position constraints

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 14 | `max_single_fund_weight` | float | [0.02, 0.50] | profile-derived (0.10 conservative / 0.12 moderate / 0.15 growth) | 5, 6 | Per-instrument concentration cap. `ProfileConstraints.max_single_fund_weight` | Basic |
| 15 | `min_single_fund_weight` | float | [0.0, 0.05] | 0.0 (long-only floor) | 5 | Minimum non-zero weight; below this the cleaner zeroes out (line 285) | Advanced |
| 16 | `block_min_weight[block_id]` | dict[str,float] | [0.0, 1.0] | from `StrategicAllocation.min_weight` | 2, 5 | Per-block floor. Defines `BlockConstraint(min_weight=…)` | Advanced |
| 17 | `block_max_weight[block_id]` | dict[str,float] | [0.0, 1.0] | from `StrategicAllocation.max_weight` | 2, 5 | Per-block ceiling | Advanced |
| 18 | `min_diversification_count` | int | [1, 50] | not enforced today | 6, 8 | Minimum non-zero positions. **GAP** — needs validation gate | Advanced |
| 19 | `max_sector_weight` | dict[str,float] | [0.0, 1.0] | not enforced today | 5, 6 | Sector concentration. **GAP** — sector mapping exists but not wired into optimizer | Expert |
| 20 | `max_geography_weight` | dict[str,float] | [0.0, 1.0] | not enforced today | 5, 6 | **GAP** | Expert |

### A.7 — CVaR

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 21 | `cvar_level` | float | {0.95, 0.99} | 0.95 | 4, 5, 8 | Tail confidence for `compute_cvar_from_returns` | Advanced |
| 22 | `cvar_limit` | float | (-0.30, 0.0) | profile-derived (-0.08 conservative / -0.06 moderate / -0.12 growth) | 4, 5, 8 | Upper bound on portfolio CVaR loss. Negative = loss convention | Basic |
| 23 | `cvar_warning_threshold_pct` | float | [0.50, 1.0] | 0.80 | 8, 10 | Utilization % above which `BreachStatus.trigger_status="warning"` | Advanced |
| 24 | `cvar_breach_consecutive_days` | int | [1, 30] | 3-5 (profile-derived) | 8, 10 | Days of utilization ≥100% before transitioning to `breach` | Advanced |
| 25 | `cvar_window_months` | int | [3, 36] | 3-12 (profile-derived) | 4, 8 | Lookback for empirical CVaR | Advanced |

### A.8 — Regime

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 26 | `regime_override` | enum | RISK_ON \| NORMAL \| RISK_OFF \| CRISIS \| INFLATION \| auto | auto | 1, 5 | Force a regime for what-if analysis. Bypasses `regime_service.detect_regime` | Advanced |
| 27 | `cvar_multiplier_risk_on` | float | [0.90, 1.10] | 1.00 | 1, 5 | Multiplier on `cvar_limit` when regime=RISK_ON | Expert |
| 28 | `cvar_multiplier_risk_off` | float | [0.70, 1.00] | 0.85 | 1, 5 | Multiplier when regime=RISK_OFF | Expert |
| 29 | `cvar_multiplier_crisis` | float | [0.50, 0.90] | 0.70 | 1, 5 | Multiplier when regime=CRISIS | Expert |
| 30 | `vix_risk_off_threshold` | float | [15, 40] | 25 | 1 | `regime_service.classify_regime_multi_signal` switch | Expert |
| 31 | `vix_extreme_threshold` | float | [25, 60] | 35 | 1 | CRISIS trigger | Expert |
| 32 | `markov_high_vol_threshold` | float | [0.50, 0.90] | 0.65 | 1 | `P(high_vol_state)` cutoff for Markov regime classification | Expert |
| 33 | `markov_lookback_days` | int | [252, 1260] | 504 | 1 | Expanding-window cap for Markov fit (`regime_fit.py`) | Expert |

### A.9 — Black-Litterman

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 34 | `bl_enabled` | bool | true \| false | true | 4 | Toggle BL prior; off → use historical mean returns | Advanced |
| 35 | `bl_tau` | float | (0.0, 1.0] | adaptive `1/T` (fallback 0.05) | 4 | Scalar uncertainty on equilibrium prior. He & Litterman 1999 §3.2 | Expert |
| 36 | `bl_prior_source` | enum | equilibrium \| equal_weight \| market_cap \| mean_reversion | equilibrium | 4 | π = λΣw_market — what `w_market` is | Expert |
| 37 | `bl_view_confidence_default` | float | (0.0, 1.0) | 0.5 | 4 | Default confidence when an IC view in `portfolio_views` omits it. Idzorek mapping ω = prior_var·(1−c)/c | Advanced |
| 38 | `bl_he_litterman_check_sigma` | float | [2.0, 5.0] | 3.0 | 4 | Threshold for "view fighting equilibrium" warning | Expert |

### A.10 — Ledoit-Wolf shrinkage

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 39 | `lw_enabled` | bool | true \| false | true | 4 | Toggle covariance shrinkage. Off → sample covariance (dangerous when N > T) | Expert |
| 40 | `lw_shrinkage_intensity` | float | [0.0, 1.0] or "auto" | "auto" (Ledoit-Wolf optimal) | 4 | Blend `(1−δ)·S + δ·F` where F is structured target. Manual override only for stress testing | Expert |
| 41 | `lw_target_structure` | enum | identity \| constant_correlation \| single_factor | constant_correlation | 4 | Shrinkage target F | Expert |

### A.11 — GARCH(1,1)

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 42 | `garch_enabled` | bool | true \| false | true | 4 | Use `volatility_garch` (1-step conditional) when computing per-fund vol; falls back to sample vol | Advanced |
| 43 | `garch_horizon` | enum | conditional_1step \| long_run | long_run for strategic, conditional_1step for VaR reports | 4 | `GarchResult.volatility_garch` vs `volatility_long_run = √(ω/(1−α−β))` | Expert |
| 44 | `garch_min_observations` | int | [60, 500] | 100 | 4 | Below this, GARCH is skipped | Expert |

### A.12 — Regime-conditioned covariance

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 45 | `cov_short_window_stress_days` | int | [21, 126] | 63 | 1, 4 | Short lookback used when regime ∈ {RISK_OFF, CRISIS} | Expert |
| 46 | `cov_long_window_normal_days` | int | [252, 1260] | 504 | 1, 4 | Long lookback used when regime ∈ {RISK_ON, NORMAL} | Expert |
| 47 | `cov_blend_weight_in_transition` | float | [0.0, 1.0] | 0.5 | 4 | Blending factor when regime is transitioning (probability between thresholds) | Expert |

### A.13 — Stress test

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 48 | `stress_scenarios_active` | list[str] | subset of {gfc_2008, covid_2020, taper_2013, rate_shock_200bps, custom} | all 4 | 8 | Which scenarios to run during validation | Basic |
| 49 | `stress_severity_multiplier` | float | [0.5, 3.0] | 1.0 | 8 | Multiplier on shock vectors. >1 = harsher than historical | Advanced |
| 50 | `stress_idiosyncratic_dispersion` | float | [0.0, 1.0] | 0.5 | 8 | `stress_scenarios.DEFAULT_DISPERSION_SCALE` — residual sigma scale on fund-level dispersion | Expert |
| 51 | `stress_seed` | int | any | 42 | 8 | Determinism for fund-level Gaussian residual | Expert |
| 52 | `stress_custom_shocks` | dict[block_id, float] | per-block | None | 8 | Bespoke shock vector for custom scenario | Advanced |

### A.14 — Factor model (PCA)

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 53 | `pca_n_factors` | int | [1, 10] | 3 | 4 | Number of latent factors extracted via SVD | Expert |
| 54 | `pca_explained_variance_target` | float | [0.60, 0.95] | None (count-based) | 4 | Alternative to fixed `n_factors`: pick K so `Σλᵢ/Σλ ≥ target` | Expert |
| 55 | `pca_macro_proxies_enabled` | bool | true \| false | true | 4 | Label PCA factors by max correlation with macro_data series (VIX, DGS10, DXY, …) | Expert |

### A.15 — Scoring weights (6 components, must sum to 1.0)

These are tuned per-tenant via ConfigService, not per-construction. **Recommendation: do NOT expose at construction time** — they live in admin config (Vertical Configs page) because per-run tweaks would invalidate cached `fund_risk_metrics` rankings.

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 56 | `score_w_return_consistency` | float | [0.0, 1.0] | 0.20 | 6 | Weight on `return_1y` normalized | Admin only |
| 57 | `score_w_risk_adjusted_return` | float | [0.0, 1.0] | 0.30 | 6 | Sharpe component | Admin only |
| 58 | `score_w_drawdown_control` | float | [0.0, 1.0] | 0.20 | 6 | Max DD component | Admin only |
| 59 | `score_w_information_ratio` | float | [0.0, 1.0] | 0.15 | 6 | IR component | Admin only |
| 60 | `score_w_flows_momentum` | float | [0.0, 1.0] | 0.05 | 6 | Flow momentum | Admin only |
| 61 | `score_w_fee_efficiency` | float | [0.0, 1.0] | 0.10 | 6 | `max(0, 100 − ER%·50)` | Admin only |

> **Note:** CLAUDE.md states defaults `0.20/0.25/0.20/0.15/0.10/0.10`. Source code (`scoring_service.py:36`) shows `0.20/0.30/0.20/0.15/0.05/0.10` (flows reduced from 0.10 → 0.05 with the diff redistributed to risk_adjusted_return). **Reconcile in CLAUDE.md.**

### A.16 — Construction Advisor

| # | Input | Type | Range | Default | Stage | Role | Tier |
|---|---|---|---|---|---|---|---|
| 62 | `advisor_enabled` | bool | true \| false | true | 7 | Run advisor as part of Construct response (today: separate endpoint) | Basic |
| 63 | `advisor_max_set_size` | int | [3, 10] | 5 | 7 | `_MAX_SET_SIZE` for `find_minimum_viable_set` | Expert |

### Tiered exposure recommendation

**Basic (5):** `mandate` (#3), `cvar_limit` (#22), `max_single_fund_weight` (#14), `turnover_cap` (#11), `stress_scenarios_active` (#48), `advisor_enabled` (#62) → 6 actually, but `advisor_enabled` is a toggle not a knob.

**Advanced (10):** `risk_free_rate` (#1), `lambda_risk_aversion` (#2), `cvar_level` (#21), `cvar_window_months` (#25), `regime_override` (#26), `bl_enabled` (#34), `bl_view_confidence_default` (#37), `garch_enabled` (#42), `turnover_lambda` (#12), `stress_severity_multiplier` (#49), `cvar_warning_threshold_pct` (#23) → 11.

**Expert (everything else):** 47 inputs.

**Justification:** A portfolio manager should be able to (a) pick a mandate, (b) set max position concentration, (c) cap turnover, (d) lower the CVaR limit if they want to be more conservative than the mandate default, (e) choose which stress scenarios run. That is the institutional minimum. A quant analyst additionally needs to test what-if regime overrides, BL view sensitivity, and GARCH on/off. Everything else is research-grade calibration that should never appear in a production calibration dialog.

---

## Part B — Run Construct narrative payload contract

### B.1 — Current state

`POST /model-portfolios/{id}/construct` returns a `ModelPortfolioRead` Pydantic model. The optimizer trace, regime, advisor, validation, and stress are NOT in the response. The route stores `fund_selection_schema` JSONB containing `optimization` metadata (`expected_return`, `portfolio_volatility`, `sharpe_ratio`, `solver`, `status`, `cvar_95`, `cvar_limit`, `cvar_within_limit`) — but only one phase, no trace, no narrative, no advisor, no stress.

### B.2 — Proposed contract: `POST /model-portfolios/{id}/construct`

Returns `ConstructionRunResponse`:

```json
{
  "run_id": "uuid",
  "portfolio_id": "uuid",
  "created_at": "2026-04-08T14:32:11Z",
  "actor_id": "user_xxx",
  "calibration_snapshot": {
    "schema_version": 1,
    "mandate": "moderate",
    "lambda_risk_aversion": 2.0,
    "cvar_limit": -0.06,
    "cvar_level": 0.95,
    "max_single_fund_weight": 0.12,
    "turnover_cap": 0.25,
    "turnover_lambda": 1.5,
    "regime_override": null,
    "bl_enabled": true,
    "bl_view_confidence_default": 0.5,
    "garch_enabled": true,
    "stress_scenarios_active": ["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps"],
    "stress_severity_multiplier": 1.0,
    "advisor_enabled": true,
    "_overrides": {}
  },

  "regime_context": {
    "regime": "RISK_OFF",
    "regime_source": "markov_filtered",
    "p_high_vol": 0.72,
    "p_low_vol": 0.28,
    "regime_since": "2026-03-14",
    "cvar_multiplier_applied": 0.85,
    "effective_cvar_limit": -0.051,
    "dominant_signals": [
      {"signal": "vix_percentile", "value": 28.4, "weight_in_score": 0.20},
      {"signal": "yield_curve_inversion", "value": -0.18, "weight_in_score": 0.10},
      {"signal": "hy_oas", "value": 5.4, "weight_in_score": 0.15}
    ],
    "transition_warning": null
  },

  "universe_summary": {
    "total_eligible": 142,
    "blocks_covered": 9,
    "blocks_uncovered": 2,
    "uncovered_block_ids": ["alt_commodities", "fi_us_tips"],
    "approval_filter": "approved_only",
    "stale_nav_excluded": 4
  },

  "statistical_inputs": {
    "covariance_method": "ledoit_wolf",
    "lw_shrinkage_intensity": 0.327,
    "covariance_window_days": 504,
    "covariance_window_reason": "regime=RISK_OFF, blended 0.5 long/0.5 short",
    "expected_returns_method": "black_litterman",
    "bl_prior": "equilibrium",
    "bl_views_count": 3,
    "bl_views_inconsistent_with_prior": 0,
    "bl_posterior_shift_l2": 0.023,
    "garch_fitted_count": 38,
    "garch_failed_count": 4,
    "factor_model": {
      "n_factors": 3,
      "r_squared": 0.74,
      "factor_labels": ["VIXCLS_inv", "DGS10", "DXY"]
    }
  },

  "optimizer_trace": [
    {
      "phase": "1_max_risk_adj",
      "status": "optimal",
      "solver": "CLARABEL",
      "iterations": 47,
      "wall_clock_ms": 89,
      "objective_value": 0.094,
      "cvar_check": {"value": -0.058, "limit": -0.051, "within_limit": false},
      "binding_constraints": ["max_single_fund_weight on FundX (8.0%)"],
      "outcome": "advanced_to_phase_1.5"
    },
    {
      "phase": "1.5_robust_socp",
      "status": "optimal",
      "solver": "CLARABEL",
      "iterations": 62,
      "wall_clock_ms": 134,
      "kappa": 4.12,
      "kappa_source": "chi2_95",
      "cvar_check": {"value": -0.049, "limit": -0.051, "within_limit": true},
      "outcome": "accepted"
    }
  ],
  "solver_fallbacks": [],
  "final_phase": "1.5_robust_socp",

  "weights": {
    "proposed": [
      {
        "instrument_id": "uuid",
        "ticker": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "block_id": "na_equity_large",
        "weight": 0.085,
        "previous_weight": 0.072,
        "delta": 0.013,
        "score": 78.4,
        "rationale": "Top-ranked in na_equity_large by composite score; binding at max_single_fund_weight"
      }
    ],
    "previous": [...],
    "delta": [...],
    "turnover_l1": 0.117,
    "turnover_within_cap": true,
    "n_positions": 18,
    "n_positions_changed": 12,
    "n_new_positions": 3,
    "n_dropped_positions": 2
  },

  "ex_ante_metrics": {
    "expected_return_annual": 0.072,
    "volatility_annual": 0.118,
    "sharpe_ratio": 0.271,
    "cvar_95": -0.049,
    "cvar_99": -0.067,
    "max_drawdown_expected": -0.187,
    "beta_vs_benchmark": 0.89,
    "tracking_error": 0.036,
    "information_ratio": 0.44,
    "diversification_ratio": 1.38,
    "effective_n": 14.2
  },
  "ex_ante_vs_previous": {
    "delta_sharpe": 0.018,
    "delta_cvar_95": 0.007,
    "delta_volatility": -0.004,
    "delta_max_drawdown_expected": 0.009
  },

  "factor_exposure": {
    "factors": [
      {"label": "VIXCLS_inv", "exposure": 0.82, "pct_contribution_to_variance": 41.2},
      {"label": "DGS10", "exposure": -0.31, "pct_contribution_to_variance": 18.7},
      {"label": "DXY", "exposure": 0.12, "pct_contribution_to_variance": 9.4}
    ],
    "systematic_risk_pct": 69.3,
    "specific_risk_pct": 30.7
  },

  "stress_results": [
    {
      "scenario": "gfc_2008",
      "scenario_label": "Global Financial Crisis (2007-2009)",
      "nav_impact_pct": -0.312,
      "cvar_stressed": -0.094,
      "block_impacts": {"na_equity_large": -0.094, "fi_treasury": 0.018, "...": 0},
      "worst_block": "intl_equity_em",
      "best_block": "fi_treasury",
      "worst_holding": {"instrument_id": "uuid", "ticker": "...", "loss": -0.62},
      "days_to_recovery_estimate": 420
    }
  ],

  "advisor": {
    "enabled": true,
    "current_cvar_95": -0.049,
    "cvar_limit": -0.051,
    "cvar_gap": 0.002,
    "coverage": {
      "total_blocks": 11,
      "covered_blocks": 9,
      "covered_pct": 0.818,
      "block_gaps": [
        {
          "block_id": "fi_us_tips",
          "display_name": "US TIPS",
          "asset_class": "fixed_income",
          "target_weight": 0.05,
          "current_weight": 0.0,
          "gap_weight": 0.05,
          "priority": 1,
          "reason": "No allocation to US TIPS (target 5%)"
        }
      ]
    },
    "candidates": [
      {
        "block_id": "fi_us_tips",
        "instrument_id": "uuid",
        "name": "Schwab US TIPS ETF",
        "ticker": "SCHP",
        "volatility_1y": 0.071,
        "correlation_with_portfolio": 0.18,
        "overlap_pct": 0.02,
        "projected_cvar_95": -0.047,
        "cvar_improvement": 0.041,
        "in_universe": true
      }
    ],
    "minimum_viable_set": {
      "funds": ["uuid1", "uuid2"],
      "projected_cvar_95": -0.046,
      "projected_within_limit": true,
      "blocks_filled": ["fi_us_tips", "alt_commodities"],
      "search_method": "brute_force"
    },
    "alternative_profiles": [
      {"profile": "growth", "cvar_limit": -0.12, "current_cvar_would_pass": true}
    ],
    "projected_cvar_is_heuristic": true
  },

  "validation": {
    "passed": true,
    "checks": [
      {"check": "weights_sum_to_one", "passed": true, "actual": 1.000001, "tolerance": 0.001},
      {"check": "no_stale_nav", "passed": true, "stale_count": 0, "max_staleness_days": 5},
      {"check": "cvar_within_effective_limit", "passed": true, "actual": -0.049, "limit": -0.051},
      {"check": "turnover_within_cap", "passed": true, "actual": 0.117, "limit": 0.25},
      {"check": "min_diversification_count", "passed": true, "actual": 18, "limit": 8},
      {"check": "max_single_fund_weight", "passed": true, "max_observed": 0.085, "limit": 0.12},
      {"check": "all_block_min_weights_satisfied", "passed": true},
      {"check": "all_block_max_weights_satisfied", "passed": true},
      {"check": "no_banned_instruments", "passed": true, "banned_count": 0},
      {"check": "all_instruments_approved", "passed": true},
      {"check": "stress_gfc_2008_within_tolerance", "passed": true, "loss": -0.312, "tolerance": -0.40},
      {"check": "stress_covid_2020_within_tolerance", "passed": true, "loss": -0.241, "tolerance": -0.35},
      {"check": "no_unrealistic_expected_return", "passed": true, "max_observed": 0.142, "limit": 0.30}
    ]
  },

  "narrative": {
    "headline": "Portfolio constructed under RISK_OFF regime with CVaR multiplier 0.85 applied (effective limit -5.1%).",
    "key_points": [
      "Phase 1 hit CVaR -5.8% — exceeded the regime-tightened limit of -5.1%.",
      "Robust SOCP (Phase 1.5) recovered with CVaR -4.9% by penalizing mean-uncertainty exposure.",
      "Turnover at 11.7%, well under the 25% cap.",
      "Two strategic blocks remain uncovered (fi_us_tips, alt_commodities) — advisor proposes a 2-fund minimum viable set."
    ],
    "constraint_story": "Binding: max_single_fund_weight at 12% on Vanguard Total Stock Market (VTI). Robust uncertainty radius κ=4.12 (χ² 95% calibration).",
    "holding_changes": [
      {
        "instrument_id": "uuid",
        "ticker": "VTI",
        "action": "increase",
        "from_weight": 0.072,
        "to_weight": 0.085,
        "delta_bps": 130,
        "reason_bullets": [
          "Top quartile composite score (78.4)",
          "Block target of na_equity_large is 20%; allocation rebalances toward target"
        ]
      }
    ]
  }
}
```

### B.3 — Required new computations (not currently produced)

Marked **NEW** when implementation is missing today:

1. **NEW** — `optimizer_trace`: today the optimizer logs each phase via `structlog` but does not return them. Refactor `optimize_fund_portfolio` to return `(FundOptimizationResult, list[PhaseTrace])`. Each `PhaseTrace` carries `phase`, `status`, `solver`, `iterations`, `wall_clock_ms`, `objective_value`, `binding_constraints`, `cvar_check`, `outcome`. **Critical** — this is the single highest-value enrichment. Without it, "Run Construct is opaque" stays true.
2. **NEW** — `binding_constraints` detection: post-solve, scan dual variables and identify which constraints are tight (within solver tolerance). CVXPY exposes `constraint.dual_value` after solve; iterate and threshold.
3. **NEW** — `regime_context.dominant_signals`: `regime_service.classify_regime_multi_signal` already produces a `reasons` dict. Surface it explicitly with weights from the documented stress score (VIX 20%, HY OAS 15%, …).
4. **NEW** — `statistical_inputs.lw_shrinkage_intensity`: `sklearn.covariance.LedoitWolf.shrinkage_` is computed but not currently returned upstream. Surface it.
5. **NEW** — `factor_exposure` and `factor_contributions`: `factor_model_service.decompose_factors` exists and is unused in the construct path. Wire it in and serialize.
6. **NEW** — `ex_ante_vs_previous`: requires fetching the previous active `ConstructionRunResponse` and computing deltas.
7. **NEW** — `validation.checks`: see Section E.
8. **NEW** — Stress integration into Construct response: today `/stress` and `/stress-test` are separate endpoints and the construct route does not call them. Wire `stress_scenarios.run_stress_scenario_fund_level` into `_run_construction_async` once per active scenario.
9. **NEW** — `advisor` integration into Construct response: see Section C.
10. **NEW** — `narrative` synthesis: a deterministic templater (Jinja2 SandboxedEnvironment, since prompts are Netz IP) that consumes the structured payload above and produces `headline`, `key_points`, `constraint_story`, `holding_changes`. **Pure templater, not LLM** — narrative must be reproducible for audit and fast for sub-second response.

### B.4 — Caching contract

`POST /model-portfolios/{id}/construct` is heavy (Phase 1+1.5+2+stress+advisor+factor model can take 3-8 seconds). Apply existing analytics cache pattern from CLAUDE.md:

- Hash key: `sha256(portfolio_id + calibration_snapshot_canonical_json + universe_version + nav_freshness_token)`
- TTL: 1h
- Storage: Redis
- On miss: run synchronously if estimated wall clock < 2s (small portfolios), otherwise enqueue as background job and return 202 + `/jobs/{id}/stream` SSE. Reuse the existing job pattern from `/analytics/optimize/pareto`.

### B.5 — Translation layer (smart-backend / dumb-frontend)

Per the `feedback_smart_backend_dumb_frontend` memory: end-user surfaces (PM dashboard, client report) cannot show "CVaR 95% conditional regime multiplier 0.85". The narrative payload includes BOTH technical (`headline`, `constraint_story`) and translated copy (`narrative.client_safe`). Add a sibling block:

```json
"narrative": {
  ...technical...,
  "client_safe": {
    "headline": "Portfolio rebuilt for the current cautious market.",
    "summary": "We tightened the maximum potential loss tolerance because volatility indicators are elevated. The largest position is held to 8.5% of assets. Transaction turnover is low at 12%.",
    "regime_label": "Cautious",
    "stress_summary": "In a 2008-style crisis, this portfolio is estimated to lose around 31% of value — within the moderate mandate's tolerance."
  }
}
```

Sophisticated users (IC chair, head of quant) toggle a "Quant lab view" to see the technical block. End clients only see `client_safe`. Same payload, two surfaces — frontend selects based on user role. The translation table is deterministic (regime → label, magnitude → adjective), no LLM at runtime.

---

## Part C — Construction Advisor surfacing

### C.1 — Current state (verified empirically)

| Question | Answer |
|---|---|
| Where is it implemented? | `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py` (789 lines) |
| Inputs | `portfolio_id`, `profile`, `current_cvar_95`, `cvar_limit`, `block_weights`, `strategic_targets`, `block_metadata`, `candidates` (FundCandidate list pre-fetched), `portfolio_returns`, `portfolio_daily_returns`, `candidate_returns`, `current_weights`, `candidate_holdings`, `portfolio_holdings`, `alternative_cvar_limits`, `scoring_weights` |
| Outputs | `ConstructionAdvice` dataclass with `coverage` (CoverageAnalysis with BlockGap list), `candidates` (ranked CandidateFund list with projected CVaR + improvement), `minimum_viable_set` (MinimumViableSet via brute-force ≤15 or greedy+swap), `alternative_profiles` (AlternativeProfile list), `cvar_gap`, `projected_cvar_is_heuristic=True` |
| When does it fire? | Stage 7 in the 11-stage pipeline (between Composition and Validation). Currently fires ONLY when the user manually calls `POST /model-portfolios/{id}/construction-advice` AFTER the construct call has completed. |
| Why invisible? | The construct response (`ModelPortfolioRead`) does not embed advisor output. The UI never calls the second endpoint. There is no UI surface for `ConstructionAdvice`. |

### C.2 — Recommendation: fold into Run Construct

**Single endpoint, single response.** The advisor is mathematically downstream of the optimizer (it consumes optimizer block weights to identify gaps) and upstream of validation (gaps are an input to the validation gate). Splitting it across two HTTP calls is an artifact of incremental development, not a domain requirement.

**Implementation:**

1. In `_run_construction_async` (model_portfolios.py:1247), after `construct_from_optimizer` succeeds, check `calibration_snapshot.advisor_enabled`.
2. If true, call `build_advice` in a worker thread (it is pure numpy, CPU-bound, already designed for `asyncio.to_thread`).
3. Pass the result into the new `ConstructionRunResponse.advisor` field defined in B.2.
4. Keep `POST /model-portfolios/{id}/construction-advice` as a standalone endpoint for backward compat AND for "re-run advisor with different scoring weights" what-if analysis (which is a legitimate use case — IC may want to ask "what if I cared more about correlation than overlap?").

**Cost:** `build_advice` is ~200-800ms for a 50-fund portfolio. Tolerable inside the 1h-cached construct response. Skip when `advisor_enabled=false`.

### C.3 — When advisor must NOT auto-run

- If optimizer fell through to `min_variance_fallback` or `cvar_violated` — the gaps are systemic, not addressable by adding 2-3 funds. Surface the optimizer failure, not the advisor.
- If universe has < 20 candidates outside the current selection — there's nothing meaningful to recommend. Return `advisor.coverage` only, skip `candidates` and `minimum_viable_set`.

---

## Part D — Stress test coverage alignment

### D.1 — Backend canonical scenarios

From `vertical_engines/wealth/model_portfolio/stress_scenarios.py:PRESET_SCENARIOS`:

| Scenario key | Display label | Description | Block shocks (representative) |
|---|---|---|---|
| `gfc_2008` | Global Financial Crisis (2007-2009) | Subprime collapse, Lehman failure, equity drawdown ~50% | na_equity_large -38%, intl_equity_em -50%, fi_treasury +6%, fi_credit_hy -26%, alt_reits -38% |
| `covid_2020` | COVID-19 Crash (Feb-Apr 2020) | Pandemic shutdown, rapid selloff and recovery | na_equity_large -34%, fi_treasury +8%, alt_reits -25%, fi_credit_hy -12% |
| `taper_2013` | Taper Tantrum (2013) | Bernanke taper announcement, gold and EM drawdown | em_equity -15%, alt_gold -28%, fi_treasury -5% |
| `rate_shock_200bps` | Rate Shock +200bps | Sudden 200bps parallel curve shift | fi_treasury -12%, alt_reits -15%, na_equity_large -10% |
| `custom` | User-defined | Bespoke shock vector via API | per-block dict from request |

The backend route `POST /model-portfolios/{id}/stress-test` (line 374) ALREADY accepts these 4 + custom and returns the standard `StressTestResponse`. **The UI mismatch is a frontend bug, not a backend gap.**

### D.2 — New endpoint: `GET /portfolio/stress-test/scenarios`

Self-describing scenario enumeration so the frontend stops hardcoding. Returns:

```json
{
  "scenarios": [
    {
      "key": "gfc_2008",
      "label": "Global Financial Crisis (2007-2009)",
      "description": "Subprime mortgage collapse, Lehman failure, equity drawdown ~50%",
      "historical_window": {"start": "2007-10-01", "end": "2009-03-31"},
      "severity_anchors": {
        "na_equity_large_loss": -0.38,
        "fi_treasury_gain": 0.06,
        "alt_reits_loss": -0.38
      },
      "blocks_covered": ["na_equity_large", "na_equity_small", "intl_equity_dm", "intl_equity_em", "fi_treasury", "fi_credit_ig", "fi_credit_hy", "alt_gold", "alt_reits"],
      "supports_severity_multiplier": true,
      "supports_idiosyncratic_dispersion": true
    },
    {...covid_2020...},
    {...taper_2013...},
    {...rate_shock_200bps...},
    {
      "key": "custom",
      "label": "Custom scenario",
      "description": "User-defined block shocks",
      "supports_severity_multiplier": false,
      "supports_idiosyncratic_dispersion": true,
      "schema": "dict[block_id, float] in shock-return convention"
    }
  ]
}
```

Implementation: trivial — read `PRESET_SCENARIOS.keys()` + a metadata dict held in `stress_scenarios.py`. No DB.

### D.3 — Stress test contract: `POST /portfolio/{id}/stress-test`

Already exists. Refine the response to also include fund-level breakdown (the engine supports it via `run_stress_scenario_fund_level` but the route currently only calls block-level). Wire fund-level when `body.fund_level=true`.

```json
{
  "portfolio_id": "uuid",
  "scenario_name": "gfc_2008",
  "scenario_label": "Global Financial Crisis (2007-2009)",
  "severity_multiplier_applied": 1.0,
  "nav_impact_pct": -0.312,
  "cvar_stressed": -0.094,
  "block_impacts": [...],
  "fund_impacts": [
    {"instrument_id": "uuid", "ticker": "VTI", "weight": 0.085, "shock": -0.376, "contribution": -0.0320}
  ],
  "worst_block": "intl_equity_em",
  "best_block": "fi_treasury",
  "computed_at": "2026-04-08T14:32:11Z"
}
```

---

## Part E — Validation gate explainability

### E.1 — Current state

There is no formal validation engine. The only validation today is `Composition.validate_weights()` (sums-to-1 check). The 11-stage pipeline reference document calls for stage 8 to produce structured pass/fail — that code does not exist.

### E.2 — Required checks

| # | Check | Severity | Computation | Source |
|---|---|---|---|---|
| 1 | `weights_sum_to_one` | block | `\|Σwᵢ − 1\| ≤ 1e-3` | Cleaned weights |
| 2 | `no_stale_nav` | block | All instruments in portfolio have NAV within last `staleness_threshold_days` (default 5 business days) | `nav_timeseries.MAX(nav_date)` JOIN per fund |
| 3 | `cvar_within_effective_limit` | block | `cvar_95 ≥ effective_cvar_limit` (negative comparison) | optimizer result + regime multiplier |
| 4 | `turnover_within_cap` | block | `Σ\|wₙₑw − w_curr\| ≤ turnover_cap` | weights_proposed vs previous_active |
| 5 | `min_diversification_count` | block | `count(wᵢ > 0.001) ≥ min_diversification_count` (default 8) | weights |
| 6 | `max_single_fund_weight` | block | `max(wᵢ) ≤ max_single_fund_weight` | weights |
| 7 | `all_block_min_weights_satisfied` | block | per block: `Σ_{i ∈ block} wᵢ ≥ block_min` | weights + `StrategicAllocation` |
| 8 | `all_block_max_weights_satisfied` | block | per block: `Σ_{i ∈ block} wᵢ ≤ block_max` | weights + `StrategicAllocation` |
| 9 | `no_banned_instruments` | block | None of the proposed instruments has `instruments_org.approval_status='banned'` | `instruments_org` |
| 10 | `all_instruments_approved` | block | All proposed have `approval_status='approved'` | `instruments_org` |
| 11 | `stress_<scenario>_within_tolerance` | warn | per active scenario: `nav_impact_pct ≥ profile_stress_tolerance[scenario]` | stress_results |
| 12 | `no_unrealistic_expected_return` | warn | `max(expected_returns) ≤ 0.30` (sanity bound — reject obvious calibration error) | `mu` vector |
| 13 | `bl_views_consistent_with_prior` | warn | No view flagged by He-Litterman 3σ test | BL diagnostic |
| 14 | `garch_convergence_rate` | warn | `garch_failed_count / total ≤ 0.20` | GARCH fits |
| 15 | `factor_model_r_squared` | warn | `factor_model.r_squared ≥ 0.50` | PCA result |

**Severity:**
- `block` → `validation.passed = false`, portfolio cannot be activated, UI shows red
- `warn` → `validation.passed` stays true, UI surfaces yellow note in `validation.warnings[]`

### E.3 — Implementation location

New module: `backend/vertical_engines/wealth/model_portfolio/validation_gate.py`. Pure function `validate_construction(run_payload, db_context) -> ValidationResult`. Called from `_run_construction_async` after stress + advisor complete.

### E.4 — Activation gate

`POST /model-portfolios/{id}/activate` (already exists at line 1100) MUST consult the latest run's validation result and refuse activation if any `block`-severity check failed. Return 409 Conflict with the failed checks list.

---

## Part F — Regime context visibility

### F.1 — Regime payload contract: `GET /portfolio/regime/current`

```json
{
  "as_of": "2026-04-08",
  "regime": "RISK_OFF",
  "regime_source": "markov_filtered",
  "p_low_vol": 0.28,
  "p_high_vol": 0.72,
  "regime_since": "2026-03-14",
  "days_in_current_regime": 25,
  "vix_latest": 28.4,
  "vix_percentile_1y": 0.78,

  "cvar_multiplier_table": {
    "RISK_ON": 1.00,
    "RISK_OFF": 0.85,
    "CRISIS": 0.70,
    "INFLATION": 0.90
  },
  "cvar_multiplier_active": 0.85,

  "dominant_signals": [
    {"signal": "VIX", "value": 28.4, "threshold_risk_off": 25.0, "threshold_extreme": 35.0, "weight_in_score": 0.20},
    {"signal": "HY_OAS", "value": 5.4, "weight_in_score": 0.15},
    {"signal": "yield_curve_10y2y", "value": -0.18, "weight_in_score": 0.10},
    {"signal": "DXY_zscore", "value": 1.7, "weight_in_score": 0.10}
  ],
  "stress_score_composite": 47.3,

  "transition_warning": {
    "active": false,
    "trend": "stable"
  },

  "client_safe": {
    "label": "Cautious",
    "explanation": "Volatility is elevated and credit spreads have widened. The portfolio is being constructed with tighter loss tolerances than normal."
  }
}
```

### F.2 — Refresh cadence

- **Source of truth:** `portfolio_snapshots.regime_probs` JSONB, written by `regime_fit.py` worker (lock 900_026) AFTER `portfolio_eval` (lock 900_008). Daily at ~03:00 UTC.
- **Read pattern:** Route `GET /portfolio/regime/current` reads the latest snapshot row across all profiles (regime is global, not profile-specific). Sub-millisecond — single indexed query.
- **Cache:** Redis 5min TTL. Invalidated when `regime_fit.py` worker completes (publish `wealth:regime:updated` event).
- **Live override:** When the user is calibrating, the route accepts `?regime_override=CRISIS` and returns the same payload with that regime forced — gives instant what-if without re-running the worker.

### F.3 — Data contract for the frontend banner

The frontend specialist will design the banner. From the quant side, the contract guarantees:
1. `regime` + `cvar_multiplier_active` + `client_safe.label` are always non-null.
2. `dominant_signals` always has at least 1 entry.
3. `as_of` is no more than 36h stale (worker SLA). If stale, return 503 with `stale_since` so the UI can show a degraded state.

---

## Part G — Live portfolio monitoring math

### G.1 — Daily (existing, `portfolio_eval` lock 900_008)

| Input | Computation | Output | Persisted to |
|---|---|---|---|
| `StrategicAllocation` per profile, `nav_timeseries` 3-12 month window | Block-weighted portfolio returns → `compute_cvar_from_returns(0.95)` → `check_breach_status` | CVaR current, utilization %, trigger status (`ok`/`warning`/`breach`), regime | `portfolio_snapshots` |

Already wired. No changes.

### G.2 — Daily (existing, `regime_fit` lock 900_026)

VIX history → 2-state Markov filter → `p_high_vol` series → classified regime → enrich today's snapshots. Already wired.

### G.3 — Intraday (NEW — proposed)

| Trigger | Computation | Output | Persistence |
|---|---|---|---|
| Cron every 15min during US market hours | For each active model portfolio: pull latest intraday NAV from Yahoo Finance feed (already ingested by `instrument_ingestion`) → compute portfolio NAV via current weights → compute drift vs prior close → compute VaR_intraday | `portfolio_intraday_state` row | New `portfolio_intraday` table (out of scope here — DB specialist decides) |

**Mathematical content:** Pure linear. `nav_t = Σ wᵢ · navᵢ_t`. Drift = `(nav_t / nav_open) − 1`. Intraday VaR = `−1.65 · σ_intraday · √(remaining_hours/6.5)` using the 1h conditional vol from GARCH.

**Cadence rationale:** 15min is the right balance — sub-minute is overkill for institutional wealth (we are not HFT), 1h misses material moves during NFP / FOMC.

### G.4 — Event-driven

| Event | Computation | Output |
|---|---|---|
| Regime transition (RISK_ON → RISK_OFF) | Recompute `effective_cvar_limit` for all active portfolios; flag any whose ex-ante CVaR now exceeds the new effective limit | Alert via Redis pub/sub `wealth:alerts:regime_transition` |
| Limit breach (`cvar_utilized_pct ≥ 100`) | Already handled by `portfolio_eval` | `BreachStatus.trigger_status='breach'`, alert published |
| Drift > 5% (maintenance) or > 10% (urgent) | `drift_check.py` worker (lock 42) compares current weights vs target, applies DTW distance | `strategy_drift_alerts` row + watchlist update |
| User clicks "Suggest Rebalance" | Section H | `RebalanceProposal` |

### G.5 — On-demand

Section H + Section B (Run Construct as the canonical recompute).

---

## Part H — Rebalancing engine surface

### H.1 — Current state

`vertical_engines/wealth/rebalancing/`:
- `weight_proposer.py` — `propose_weights()` redistributes proportionally within `StrategicAllocation` bounds when an instrument is removed. Uses `_redistribute_proportionally` (clamp + renormalize iteration). Applies `apply_dead_band` (default 0.005). Returns `WeightProposal` with `feasible` flag.
- `impact_analyzer.py` — `compute_impact()` scans all active model portfolios for an instrument and reports affected portfolio IDs + total weight gap.
- `service.py` — orchestration (not read here, but exists per directory listing).

These are **deactivation-driven** (instrument is being removed and we need to fix every portfolio holding it). They are NOT a general-purpose "suggest a rebalance" engine. The general-purpose path goes through Run Construct.

### H.2 — Proposed: `POST /model-portfolios/{id}/rebalance/suggest`

```json
{
  "trigger": "drift_breach" | "regime_transition" | "user_initiated" | "scheduled",
  "calibration_overrides": {
    "turnover_cap": 0.10,
    "preserve_positions": ["uuid1", "uuid2"]
  }
}
```

Returns `RebalanceProposal`:

```json
{
  "proposal_id": "uuid",
  "portfolio_id": "uuid",
  "trigger": "drift_breach",
  "computed_at": "...",
  "current_weights": [...],
  "proposed_weights": [...],
  "trades": [
    {"instrument_id": "uuid", "ticker": "VTI", "action": "increase", "from_weight": 0.072, "to_weight": 0.085, "delta_bps": 130}
  ],
  "turnover_l1": 0.08,
  "ex_ante_metrics_before": {...},
  "ex_ante_metrics_after": {...},
  "metric_deltas": {
    "delta_sharpe": 0.012,
    "delta_cvar_95": 0.004,
    "delta_volatility": -0.003
  },
  "stress_results_after": [...],
  "validation": {"passed": true, "checks": [...]},
  "rationale": [
    "na_equity_large drifted to 24.1% vs target 20% (4pp above)",
    "Proposed reduction restores band compliance",
    "Turnover 8.0% well under 10% override cap"
  ],
  "expires_at": "..."
}
```

**Mechanics:** Internally calls `_run_construction_async` with the user's calibration overrides applied on top of the portfolio's baseline calibration, plus `current_weights` passed as the `previous` baseline so turnover penalty is meaningful. The proposal is NOT persisted to the active portfolio — it's a transient proposal the user reviews and either accepts (POST `/model-portfolios/{id}/rebalance/accept/{proposal_id}`) or discards. Cache for 1h.

### H.3 — Deactivation path (existing)

Keep `propose_weights` and `compute_impact` for the deactivation flow. Surface them via `POST /instruments/{id}/deactivate/preview` which returns `RebalanceImpact` + a per-affected-portfolio `WeightProposal`. Already wired in the rebalancing route.

---

## Part I — Scoring breakdown visibility

### I.1 — `GET /instruments/{id}/score-breakdown`

Returns the live decomposition of any fund's score. Pulled from `fund_risk_metrics` (which already stores the inputs) — no recomputation in the request hot path.

```json
{
  "instrument_id": "uuid",
  "ticker": "VTI",
  "name": "Vanguard Total Stock Market ETF",
  "computed_at": "2026-04-08T03:14:00Z",
  "scoring_config": {
    "schema_version": 1,
    "weights": {
      "return_consistency": 0.20,
      "risk_adjusted_return": 0.30,
      "drawdown_control": 0.20,
      "information_ratio": 0.15,
      "flows_momentum": 0.05,
      "fee_efficiency": 0.10
    }
  },
  "components": [
    {
      "name": "return_consistency",
      "raw_metric": {"return_1y": 0.142},
      "normalized_score": 78.4,
      "weight": 0.20,
      "contribution": 15.68,
      "peer_median": 65.0,
      "rank_pct_in_strategy": 0.72
    },
    {
      "name": "risk_adjusted_return",
      "raw_metric": {"sharpe_1y": 1.12},
      "normalized_score": 82.7,
      "weight": 0.30,
      "contribution": 24.81,
      "peer_median": 70.0,
      "rank_pct_in_strategy": 0.81
    },
    {
      "name": "drawdown_control",
      "raw_metric": {"max_drawdown_1y": -0.08},
      "normalized_score": 84.0,
      "weight": 0.20,
      "contribution": 16.80
    },
    {
      "name": "information_ratio",
      "raw_metric": {"information_ratio_1y": 0.44},
      "normalized_score": 68.0,
      "weight": 0.15,
      "contribution": 10.20
    },
    {
      "name": "flows_momentum",
      "raw_metric": {"flow_momentum_score": 50.0},
      "normalized_score": 50.0,
      "weight": 0.05,
      "contribution": 2.50
    },
    {
      "name": "fee_efficiency",
      "raw_metric": {"expense_ratio_pct": 0.03},
      "normalized_score": 98.5,
      "weight": 0.10,
      "contribution": 9.85
    }
  ],
  "composite_score": 79.84,
  "missing_data_penalty_applied": false
}
```

**Implementation:** `scoring_service.compute_fund_score` already returns `(score, components)`. Just need a route that fetches `FundRiskMetrics` for the instrument, calls `compute_fund_score`, and serializes both inputs and outputs. Add peer median lookup from cached strategy peers. Pure read, no compute beyond a single function call. Cache 6h (recomputed daily by `global_risk_metrics`).

---

## Part J — Gaps, decisions, risks

### J.1 — Andrei product decisions required

1. **Tiered exposure default state.** Should the calibration UI default to Basic with an "Advanced" expand toggle, or default to Advanced with a "Show Expert" toggle? Recommendation: **Basic by default**, given that 80% of users are PMs not quants.
2. **Narrative templater vs LLM.** Recommendation: **deterministic Jinja2 templater** for narrative. LLM is too slow, non-reproducible, and creates audit trail problems for fiduciary defensibility. Andrei: confirm.
3. **Activation gate strictness.** Should `block`-severity validation failures be HARD blocks (cannot activate, period) or SOFT blocks (IC chair can override with reason)? Recommendation: **soft with audit log** — institutional reality is that IC may override on documented judgment.
4. **Intraday cadence.** 15min vs 1h vs market-event-only. Recommendation: 15min during US market hours, event-only outside.
5. **Scoring weights configurability at construction time.** Recommendation: **no** — scoring is a fund-level cache, not a per-construction knob. Tweaking it per-run breaks all caching and creates incoherent IC discussions.

### J.2 — New quant implementation (does not exist)

| # | Feature | Estimated effort | Owner |
|---|---|---|---|
| 1 | `optimizer_trace` capture (return phase metadata from `optimize_fund_portfolio`) | M | Quant |
| 2 | `binding_constraints` extraction from CVXPY dual values | S | Quant |
| 3 | `LedoitWolf.shrinkage_` surfacing | XS | Quant |
| 4 | `validation_gate.py` module + 15 checks | M | Quant + Domain |
| 5 | `narrative` templater (Jinja2 SandboxedEnvironment) | S | Quant + Product |
| 6 | `client_safe` translation table | XS | Product |
| 7 | `GET /portfolio/regime/current` route | XS | Quant |
| 8 | `GET /portfolio/stress-test/scenarios` route | XS | Quant |
| 9 | `POST /model-portfolios/{id}/rebalance/suggest` route | M | Quant |
| 10 | `GET /instruments/{id}/score-breakdown` route | XS | Quant |
| 11 | Wire stress + advisor + factor model into Construct response | M | Quant |
| 12 | Intraday portfolio state worker | M | Quant + Worker infra |
| 13 | Sector / geography concentration constraints (#19, #20) | M | Quant |
| 14 | Min diversification count enforcement (#18) | S | Quant |
| 15 | `previous_run` lookup for `ex_ante_vs_previous` | S | Quant |

### J.3 — Reference doc reconciliation

- **CLAUDE.md vs scoring_service.py:** CLAUDE.md says weights are `0.20/0.25/0.20/0.15/0.10/0.10`. Code says `0.20/0.30/0.20/0.15/0.05/0.10` (with the comment that flows was reduced from 0.10 → 0.05 and the diff went to risk_adjusted_return). Update CLAUDE.md to match code.
- **`portfolio-construction-reference-v2-post-quant-upgrade.md`** describes the 11-stage pipeline including formal Validation. The validation gate code is missing — this design closes that gap.
- **`institutional-portfolio-lifecycle-reference.md`** describes the IC decision flow. The narrative payload (B.2) is the bridge between the quant engine and that lifecycle's "what was decided and why" requirement.

### J.4 — Risks

1. **Caching invalidation.** `calibration_snapshot` becomes a hash key. If we forget to canonicalize JSON ordering, identical calibrations will miss cache. Use `json.dumps(sort_keys=True)` for the hash input.
2. **Construct response payload size.** The full payload above is ~30-80 KB. Acceptable for institutional users but enable gzip on the route.
3. **`optimizer_trace` schema drift.** As we add Phase 2/3 telemetry over time, frontend consumers will break. Wrap traces in `schema_version` and validate frontend handles missing fields gracefully.
4. **Advisor + Validation race.** Advisor consumes block_weights from optimizer; Validation consumes weights AND advisor output. Order: optimizer → factor_model → stress → advisor → validation → narrative. Enforce in `_run_construction_async`.
5. **Regime override leakage.** When IC overrides regime for what-if, the cache key MUST include the override or two users will see each other's results. Include `regime_override` in the calibration snapshot.
6. **Concurrency on Run Construct.** Two IC users hitting Construct on the same portfolio simultaneously is real. Apply the existing `SingleFlightLock` pattern from CLAUDE.md guardrails P5/P6 and return 409 + the in-flight `run_id` to the second caller.
7. **`portfolio_eval` worker uses stale `regime_service.detect_regime`** with empty array fallback (line 213, 216). Sanity check this still produces sensible regimes when run on small portfolios. Likely orthogonal to this design but flag for the engine optimization backlog.
