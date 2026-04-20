---
pr_id: PR-Q1
title: "feat(quant/g1): robust Sharpe with Cornish-Fisher + Opdyke CI"
branch: feat/quant-g1-robust-sharpe
sprint: S1
parallel_with: [PR-Q2, PR-Q3]
dependencies: []
loc_estimate: 280
reviewer: quant
---

# Opus Prompt — PR-Q1: G1 Robust Sharpe

You are Opus executing a bounded implementation task for the Netz Analysis Engine. Follow the specs; do not improvise design decisions.

## Goal

Ship Robust Sharpe Ratio (Cornish-Fisher adjusted + Opdyke 95% CI) as a new scoring component, gated by feature flag, populated in `fund_risk_metrics` by the existing `global_risk_metrics` worker. Must not change any production scoring behavior until the flag is flipped.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §1 (G1 Robust Sharpe — formulas, API, edge cases, validation)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §3 (G1 Feature Flag Design, backfill sequence)
- `CLAUDE.md` §Quant Upgrade, §Critical Rules (async-first, ORM thread safety, SET LOCAL)

## Files to create

1. `quant_engine/scoring_components/robust_sharpe.py` — pure function `robust_sharpe(returns, rf_rate, ci_method, alpha_cf)` returning `RobustSharpeResult` dataclass. Implement Cornish-Fisher adjusted Sharpe + Opdyke closed-form IID CI + jackknife fallback. Edge cases per §1.3 of quant-math spec.
2. `backend/alembic/versions/XXXX_add_sharpe_cf_cols.py` — migration adding 5 nullable columns to `fund_risk_metrics`: `sharpe_cf`, `sharpe_cf_skew`, `sharpe_cf_kurt`, `sharpe_cf_ci_lower`, `sharpe_cf_ci_upper` (all NUMERIC). Pick the next available revision number at merge time (rebase if needed).
3. `backend/tests/quant_engine/test_robust_sharpe.py` — ≥12 unit tests per §1.5 validation list.

## Files to modify

1. `quant_engine/scoring_service.py` — branch `risk_adjusted_return` component on `ScoringConfig.use_robust_sharpe`. When flag on, read `fund_risk_metrics.sharpe_cf`; fallback `sharpe_ratio` with `logger.warning` if NULL. When flag off, identical pre-PR behavior. **Do not change any other component.**
2. `backend/app/domains/wealth/workers/global_risk_metrics.py` — compute `sharpe_cf` and populate the 5 new columns ALWAYS (independent of feature flag). Use `robust_sharpe()` on the existing monthly return series per instrument.
3. `calibration/wealth_scoring.yaml` — add `use_robust_sharpe: false` under scoring config (seed data only; runtime config via ConfigService).

## Implementation hints

- `scipy.stats.skew(returns, bias=False)` and `scipy.stats.kurtosis(returns, bias=False, fisher=True)` for sample moments
- Cornish-Fisher quantile adjustment: see formula in §1.1 of quant-math spec. `z = scipy.stats.norm.ppf(alpha_cf)`.
- Opdyke closed-form CI: $\text{Var}(\widehat{SR}) = \frac{1}{T}(1 + \tfrac{1}{2}SR^2 - S \cdot SR + \tfrac{K-3}{4}SR^2)$, then $SR \pm 1.96 \sqrt{\text{Var}}$
- Jackknife trigger: `T < 60` or `|S| > 1.5`. Leave-one-out T resamples; SE = `np.sqrt((T-1)/T * np.var(resamples, ddof=0))`
- Degraded flags per §1.3: T<36, σ=0, all-NaN, z_CF positive

## Tests (minimum 12)

Per §1.5 of quant-math spec:
1. Gaussian T=240 μ=0.01 σ=0.04 → `|SR_CF - SR| < 0.02`, CI contains true SR 95% over 1000 replications
2. Skew=-1.5, kurt_excess=3 (mixture) → `SR_CF < SR` strict
3. Scale invariance: `robust_sharpe(λr, λrf)` == `robust_sharpe(r, rf)` for λ∈{0.5, 2, 10}
4. T=12 → degraded=True, CF/CI=NaN, traditional populated
5. T=35 → degraded=True (boundary)
6. all-NaN input → degraded=True, reason
7. σ=0 edge → SR=inf signed, degraded=True, reason="zero_volatility"
8. rf_rate=None → treated as 0 (not inferred)
9. z_CF positive edge (extreme skew) → clamped, degraded, reason="cornish_fisher_non_monotonic"
10. Jackknife triggered when T<60 — method field == "jackknife"
11. Property: `robust_sharpe(-r)` has sign-flipped SR_traditional
12. Ground truth: R `PerformanceAnalytics::SharpeRatio.modified` — golden data file `tests/fixtures/r_performance_analytics_sharpe.csv`, tolerance 1e-4

## Acceptance gates

- `make check` green (lint + import-linter + mypy + pytest)
- Migration reversible (`downgrade()` drops 5 cols cleanly)
- Flag default `false` in seed — no scoring behavior change post-merge
- `global_risk_metrics` worker populates `sharpe_cf` for all active instruments (test with 5 fixture instruments)
- Stability Guardrails P5 idempotent: re-running worker on same instrument produces same `sharpe_cf` value
- No new module-level asyncio primitives (P3)

## Non-goals

- Do NOT change weights of the 6 scoring components
- Do NOT add `sharpe_cf` to scoring components list beyond the flag-gated substitution inside `risk_adjusted_return`
- Do NOT flip the flag anywhere in code or seed; flag flip is operational, post-backfill
- Do NOT touch G2 (ENB) or G3 (attribution) files — different PRs

## Branch + commit

```
feat/quant-g1-robust-sharpe
```

PR title: `feat(quant/g1): robust Sharpe with Cornish-Fisher + Opdyke CI`

PR description must tick Stability Guardrails P1-P6 checklist from `.github/PULL_REQUEST_TEMPLATE.md` and link to spec files.
