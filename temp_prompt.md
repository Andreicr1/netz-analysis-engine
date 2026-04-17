# PR-A3 Execution Brief — Hybrid Factor Model (Fundamental + PCA Residual)

**Branch:** `feat/construction-engine-pr-a3`
**Base:** `main` @ `5d3f7cec` (PR-A2 merged)
**Parent spec:** `docs/prompts/2026-04-14-construction-engine-phase-a.md` §PR-A3
**Date:** 2026-04-14
**Role for executor:** Implement exactly what is specified in §PR-A3 of the parent spec. This brief adds the environment-verified constraints the parent could not assume.

---

## Pre-execution findings (VERIFIED 2026-04-14 against local DB)

The parent spec assumes `benchmark_nav` stores tickers directly. **It does not.** `benchmark_nav` is keyed by `block_id` (FK to `allocation_blocks.block_id`), and the ticker is resolved via `allocation_blocks.benchmark_ticker`. Your factor loader MUST query the join, not a non-existent `ticker` column on `benchmark_nav`.

Confirmed availability at HEAD:

| Factor (K=8 set) | Primary ticker | Resolves in `allocation_blocks` via `benchmark_ticker` | block_id | Action for PR-A3 |
|---|---|---|---|---|
| 1. US equity beta | SPY | yes | `na_equity_large` | use |
| 2. Duration | IEF | yes | `fi_us_treasury` | use |
| 3. Credit spread | HYG (− IEF) | yes | `fi_us_high_yield` (prefer) / `fi_high_yield` | use. If both present, prefer `fi_us_high_yield`. |
| 4. USD strength | DTWEXBGS | `macro_data.series_id` | — | use |
| 5. Commodity | DCOILWTICO | `macro_data.series_id` | — | use |
| 6. Size | IWM (− SPY) | yes | `na_equity_small` | use |
| 7. Value | IWD (− **IWF**) | IWD yes (`na_equity_value`); **IWF absent** | — | **Skip Value factor** per §3.2. Do not substitute QQQ/`na_equity_growth` for IWF — QQQ is Nasdaq-100, not Russell-1000 Growth; the IWD-IWF value spread is not replaceable without introducing sector bias. Log `factor_skipped="value"` with reason `"IWF proxy absent from allocation_blocks"` and reduce K to 7. |
| 8. International | EFA (− SPY) | **EFA absent** | — | **Skip International factor** per §3.2. Do not substitute VGK (Europe only) or VGK+EWJ composite — composite would require weighting assumptions that inject arbitrary structure. Log `factor_skipped="international"` with reason `"EFA proxy absent from allocation_blocks"` and reduce K accordingly. |

**Effective K at build time on current data: K=6** (US equity, Duration, Credit, USD, Commodity, Size).

This is the live state of the estimator and MUST be handled by your code path — not by backfilling IWF/EFA into `benchmark_nav`. That is a data-engineering task outside this PR.

---

## What PR-A3 must deliver (unchanged from parent spec §PR-A3)

Implement everything enumerated under "PR-A3: Hybrid factor model" in `docs/prompts/2026-04-14-construction-engine-phase-a.md` (lines 290–359). The specific functions, dataclasses, fallback ordering, PSD requirements, and test coverage are all defined there and are not repeated here to avoid drift.

Key constraints to re-state in-line so nothing is missed:

1. `build_fundamental_factor_returns(db, start_date, end_date)` joins `benchmark_nav → allocation_blocks` on `block_id` and filters by `benchmark_ticker IN (...)`. It does NOT reference a `ticker` column on `benchmark_nav`.
2. Forward-fill limit **3 days** on daily returns before alignment — match the fund return policy already used in PR-A1.
3. `fit_fundamental_loadings` uses **per-fund OLS** with **EWMA weights λ=0.97** over 5Y daily. Ledoit-Wolf shrinkage on `F` (K×K), never on `B`.
4. `assemble_factor_covariance(fit: FundamentalFactorFit) -> np.ndarray` returns `B·F·Bᵀ + diag(D)`, eigenvalue-clamps to PSD at `max(1e-10, 1e-8·trace(Σ)/N)`. **Its parameter type annotation is `FundamentalFactorFit` only. mypy must reject `PCADiagnostic`.**
5. `compute_residual_pca` writes to `inputs_metadata.residual_pca` JSONB for audit. Never feeds `Σ`. The module containing `assemble_factor_covariance` MUST NOT import `PCADiagnostic`.
6. `compute_fund_level_inputs()` in `backend/app/domains/wealth/services/quant_queries.py`:
   - When `N ≥ 20` → factor path via `factor_model_service`.
   - When `N < 20` → retain 5Y EWMA + LW single-index shrinkage fallback (retarget the existing LW path from constant-correlation to single-index as part of this PR).
   - Populate `FundLevelInputs.factor_loadings`, `factor_names`, `residual_variance` accordingly.
7. Audit log `factor_skipped` event (one per skipped factor) with reason string and current effective K. Record skipped factors in `inputs_metadata.factor_model.factors_skipped` as a list of `{name, reason}` objects. Populate `inputs_metadata.factor_model.k_factors` (design=8) and `k_factors_effective` (runtime, currently 6).
8. **Never substitute a level change for a total return** (OAS differencing for HY, DGS10/DGS2 differencing for Duration). The parent spec §3.2 is explicit and this is the #1 silent-bias failure mode — guard with code comments and a unit test that rejects any attempt.

---

## Tests you MUST write (additive to parent spec)

Files: `backend/tests/quant_engine/test_fundamental_factor_model.py` (new).

Parent spec enumerates the synthetic-data tests. Add these environment-specific cases:

| # | Test | Why |
|---|---|---|
| T1 | `test_build_fundamental_factor_returns_joins_allocation_blocks` — assert the SQL joins through `allocation_blocks` and returns a DataFrame with as many columns as effective factors present. | Prevents regression to the broken `benchmark_nav.ticker` assumption. |
| T2 | `test_iwf_absent_triggers_value_factor_skip` — seed fixture with SPY/IEF/HYG/IWM/IWD/DTWEXBGS/DCOILWTICO but no IWF. Assert `factors_skipped` contains `{"name": "value", "reason": ...}`, `k_factors_effective == 7`, no `ValueError`. | Exercises the fallback path on the live shape. |
| T3 | `test_efa_absent_triggers_international_factor_skip` — same pattern, EFA absent. K drops to 6 when both IWF and EFA absent. | The current-prod shape. |
| T4 | `test_k_equals_six_end_to_end` — realistic 25-fund portfolio, current DB shape. `assemble_factor_covariance` returns PSD 25×25 Σ; `FundLevelInputs.factor_loadings.shape == (25, 6)`; `condition_number < 1e3`. | Prove the end-to-end works on the shape the terminal will actually hit. |
| T5 | `test_assemble_factor_covariance_rejects_pca_diagnostic_at_type_level` — passing a `PCADiagnostic` instance raises `TypeError` (runtime) AND mypy errors on an adjacent type-test file (`test_assemble_factor_covariance_types.py` run through `make typecheck`). | §PR-A3 requirement for type-level enforcement. |
| T6 | `test_oas_level_is_never_used_as_credit_return` — explicit test: if someone replaces the HYG-IEF computation with `BAMLH0A0HYM2` level differencing, the test fails. Parameterize on a mock input labelled `"BAMLH0A0HYM2"` and assert `ValueError` with a message naming "OAS level is not a total return". | Defensive — prevents the silent-bias failure mode that is the #1 risk in credit factor modeling. |
| T7 | `test_residual_pca_not_fed_back_into_sigma` — regression check (mock spy on `assemble_factor_covariance`'s import graph, or a source-level assertion that `PCADiagnostic` is not imported in its module). | §PR-A3 requirement. |
| T8 | `test_single_index_fallback_when_n_less_than_20` — N=15 universe. Assert `FundLevelInputs.factor_loadings is None`, `factor_names is None`, but Σ is still populated via retargeted LW single-index shrinkage, and `condition_number < 1e3`. | §PR-A3 fallback branch. |

All tests run under `pytest backend/tests/quant_engine/test_fundamental_factor_model.py -v`. `make check` must pass.

---

## Out of scope for PR-A3 (do NOT do)

- Backfilling IWF/EFA into `benchmark_nav` or `allocation_blocks`. That's a separate data-engineering ticket.
- Any change to `black_litterman_service.py` (PR-A2 already delivered).
- Any new migration (0133 is PR-A4's responsibility).
- Any route or frontend change (PR-A4).
- Touching legacy `compute_inputs_from_nav` or legacy `/construct`.

---

## Acceptance gate (must all be green before merging)

1. `make check` passes (lint + architecture + typecheck + test).
2. New test file has all T1-T8 cases plus the parent-spec synthetic tests — ≥ 12 cases total.
3. A `make test ARGS="-k test_k_equals_six_end_to_end"` run against the docker-compose DB returns green (not just synthetic data).
4. `grep -n "benchmark_nav.ticker" backend/quant_engine/factor_model_service.py` returns zero matches (there is no such column).
5. `grep -n "PCADiagnostic" backend/quant_engine/factor_model_service.py` shows `PCADiagnostic` defined and used by `compute_residual_pca` but NOT imported in the module containing `assemble_factor_covariance` (if same module, assert the function body has no `PCADiagnostic` reference).
6. Audit events emitted on factor skips are visible in `AuditEvent` rows after running one construction on a test portfolio.
7. No regression in `test_construction_adversarial.py` or `test_construction_integration.py` from PR-A1.
8. Commit message: `feat(wealth): Phase A hybrid factor model — fundamental + PCA residual (PR-A3)`. Co-author line per repo convention.

---

## Executor protocol

1. Branch from `main` → `feat/construction-engine-pr-a3`.
2. Read `docs/prompts/2026-04-14-construction-engine-phase-a.md` lines 290–359 (§PR-A3) in full before writing code.
3. Read the current contents of `backend/quant_engine/factor_model_service.py` and `backend/app/domains/wealth/services/quant_queries.py::compute_fund_level_inputs` so you know exactly what PR-A1 and PR-A2 already built. Do not duplicate.
4. Implement in order: `build_fundamental_factor_returns` → `fit_fundamental_loadings` → `assemble_factor_covariance` → `compute_residual_pca` → wire into `compute_fund_level_inputs` → single-index LW fallback retarget.
5. Tests land in the same PR. Do not split.
6. Run `make check` locally. Iterate until green (per mandate: install deps, iterate as needed, no shortcuts).
7. Open PR targeting `main`. Title: `feat(wealth): Phase A hybrid factor model (PR-A3)`. Body references this brief and the parent spec.
8. Do NOT auto-merge. Report PR URL and acceptance-gate status to Andrei for review. (PR-A4 is next in sequence and depends on A3 landing cleanly.)
