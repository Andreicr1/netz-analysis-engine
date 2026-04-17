# PR-A12.3 — Diagnose & Fix: RU CVaR Constraint Delivering CVaR > Limit

**Branch:** `feat/pr-a12-3-cvar-constraint-diagnose` (cut from `main` at commit `0ccadbc7` post-PR-A13).
**Estimated effort:** ~3-5h Opus (diagnose-first, then fix; test harness must prove correctness).
**Predecessors:** PR-A12 (RU cascade), PR-A13 (static band panel).
**Blocks:** PR-A13.1 (preview endpoint) + PR-A13.2 (live drag preview) — the preview serves a band that is currently mathematically wrong.

---

## Section A — Problem statement (empirical evidence)

A production build of Conservative Preservation (org `403d8392-ebfa-5890-b740-45da49c556eb`, portfolio `3945cee6-f85d-4903-a2dd-cf6a51e1c6a5`) on 2026-04-17 09:51 produced a **mathematically impossible** result under PR-A12's "always-solvable RU CVaR cascade" design: the optimizer declared Phase 1 `status=optimal:cvar_constrained` but the delivered CVaR is **2.36× the operator's limit**.

**Evidence from production log `docs/ux/logs.txt`:**

```
Line 251: fund_portfolio_optimized
  band_lower=0.095612 band_upper=0.306207
  cvar_95=-0.188869
  cvar_limit=0.08
  min_achievable_cvar=0.004109
  n_funds=94  sharpe=1.9644  solver=CLARABEL
  status=optimal  winning_phase=phase_1_ru_max_return

Line 252: fund_level_optimizer_succeeded
  cvar_95=-0.188869
  cvar_limit=-0.08          ← sign inconsistency with line 251
  cvar_within_limit=False   ← contradicts winning_phase=phase_1_ru_max_return
  n_funds=94  profile=conservative
```

**The violation:** Phase 1 of the A12 cascade is defined as

```
maximize   μᵀw
subject to CVaR_α(w) ≤ L,   base constraints
```

With `L = 0.08` (8%) and α = 0.95, a Phase 1 `optimal` status **requires** `CVaR_95 ≤ 0.08` at the solution. The log shows `|cvar_95| = 0.189` — 2.36× the limit. Either the constraint is mis-specified in the LP, or the verifier reports a different CVaR than the one the solver is actually enforcing.

**Downstream impact:** A13's `achievable_return_band` panel shows `upper = 30.62% at cvar_limit = 0.08` — the operator believes this return comes at 8% CVaR, but the realized tail loss is 18.9%. A13.1 (preview endpoint) would propagate the same lie in real time. **PR-A12.3 MUST ship before A13.1 / A13.2.**

**Secondary anomaly (possibly related):** `cvar_limit` is rendered as `0.08` on line 251 and `-0.08` on line 252 for the same run. This points to an inconsistent sign convention between the optimizer service and the route-level logger.

---

## Section B — Candidate root causes (ranked by likelihood)

Each hypothesis below can be true alone or in combination. Opus must investigate all four and report which one(s) actually cause the observation.

### B.1 Alpha convention mismatch (HIGH likelihood)

CVaR_95 in finance commonly uses two conventions:
- **Tail probability α = 0.05** — "the expected loss in the worst 5% of outcomes"
- **Confidence level α = 0.95** — same quantity, dual parameterization

Rockafellar-Uryasev's LP formulation uses the tail probability (1−β in their paper, where β is the confidence). The helper `build_ru_cvar_constraints(w, R, alpha, cvar_limit)` in `backend/quant_engine/ru_cvar_lp.py` accepts `alpha` — **verify which convention it expects** by reading the function signature, docstring, and the mathematical expression `ζ + (1/((1-α)·T)) · Σ u_i`. If `alpha=0.95` is passed where the formula expects the tail probability (0.05), the denominator becomes `(1 - 0.95)·T = 0.05·T` vs the correct `(1 - 0.05)·T = 0.95·T` — a **19× scaling error** that would under-constrain CVaR dramatically, exactly the pattern observed (2.36× over-shoot).

Check every caller of `build_ru_cvar_constraints` and `realized_cvar_from_weights`: do they pass the SAME alpha, with the SAME convention? Mixed conventions (constraint using 0.95 as "confidence", verifier using 0.05 as "tail prob") also produce silent disagreement.

### B.2 Annualized vs daily scaling mismatch (HIGH likelihood)

The scenario matrix `returns_scenarios` is daily log returns (5Y daily per PR-A12 Section A.2). The RU LP constraint operates on this matrix directly — the CVaR computed is therefore **daily** CVaR_95.

The operator's `cvar_limit = 0.08` is institutional-grade language for an **annualized** tail loss. A daily CVaR_95 of 0.008 (0.8%) is typical; annualized via √252 scaling it becomes ~12-13%.

If the constraint enforces `daily_CVaR_95 ≤ 0.08` but the verifier reports `annualized_CVaR_95`, or vice versa, the log could show `cvar_95 = -0.189` (annualized) while the constraint was actually satisfied at daily scale.

**Verify:**
- What window does the constraint in `build_ru_cvar_constraints` enforce? Read the function.
- What window does `realized_cvar_from_weights` report? Read that function.
- What window does `cvar_limit = 0.08` represent in `portfolio_calibration.cvar_limit`? Read the column docstring + how it was originally seeded.
- Does the executor multiply/divide by √252 anywhere in the Phase 1 call path?

**If this is the bug, the fix is canonicalization:** pick one window (annualized is the institutional convention; matches how operators think about the slider in PR-A13). Scale scenarios appropriately before passing into the LP, OR scale the limit to match the scenario window, AND keep the verifier consistent.

### B.3 Loss convention inconsistency (MEDIUM likelihood)

Rockafellar-Uryasev defines loss as `L_i = -r_i · w` (positive-is-loss). The constraint is `ζ + (1/((1-α)T)) · Σ max(L_i - ζ, 0) ≤ L`.

If `build_ru_cvar_constraints` passes returns directly as `R` and internally negates, but `realized_cvar_from_weights` either (a) negates a second time, or (b) does not negate at all, the sign conventions diverge. The evidence `cvar_limit=0.08` on line 251 vs `cvar_limit=-0.08` on line 252 is consistent with such a divergence — one branch treats CVaR as positive loss, the other as negative P/L.

**Verify:** trace the sign of the loss variable `L_i` and the ζ threshold through BOTH functions. Make one canonical convention (recommend: `cvar_limit` stored and processed as a positive number representing loss magnitude; output `cvar_95` reported as the negative of that magnitude to match P/L convention). Document the convention in the module docstring so future PRs don't re-introduce the bug.

### B.4 Scenario matrix shape mismatch (LOW likelihood but verifiable)

`optimize_fund_portfolio` receives `returns_scenarios: np.ndarray` with shape `(T, N)`. The RU LP iterates over T rows as scenarios. If a caller accidentally passes the transpose, the LP minimizes over the wrong axis and the constraint becomes meaningless.

**Verify:** in `_run_construction_async` (model_portfolios.py:1818), the `sub_returns_scenarios` sliced from `_fli.returns_scenarios` — confirm shape `(T, N)` where T is observations and N is fund count. PR-A12 added `returns_scenarios` to `FundLevelInputs`; verify its shape contract is enforced with a runtime assertion.

### B.5 Other considerations (check, but lower priority)

- **Universe sub-coverage at 61% (line 250):** `target_sum=0.6103` — only 6 of 11 strategic blocks have funds. If Phase 1 is constrained to sum(w) = 0.61 instead of 1.0 (leaving 39% unallocated), the CVaR is computed on only 61% of notional — this could inflate or deflate reported CVaR depending on which path the tests take. **Out of scope for A12.3 (separate PR-A14), but note for the investigation: does the reported `cvar_95` scale with the deployed notional, and is the limit checked against a normalized or a raw value?**
- **Factor model skipped (lines 245-246):** `factor_returns_fetch_failed`. Unrelated to CVaR math (factor-cov is a fallback; A12.3's build uses sample cov) but confirms the kappa diagnostics were correct — universe falls back correctly. Not on the critical path.

---

## Section C — Investigation protocol (must run BEFORE writing any fix)

### C.1 Minimal repro harness

Write a standalone unit test `backend/tests/quant_engine/test_cvar_constraint_regression.py` that:

1. Loads a deterministic 5-fund universe with synthetic daily returns (seed=42, T=1260)
2. Sets `cvar_limit = 0.05` (annualized 5%)
3. Calls `optimize_fund_portfolio(...)` the SAME WAY `_run_construction_async` does
4. Asserts the returned result has `cvar_95 <= cvar_limit + 1e-3` (tolerance for solver inaccuracy)
5. ALSO asserts via direct empirical computation on scenarios: `realized_cvar_from_weights(result.weights, returns_scenarios, alpha) <= cvar_limit + 1e-3`

If either assertion fails, the bug is reproducible in isolation. If both pass in isolation but the production build fails, the bug is in the call-site (scenario source, alpha/window mismatch at the boundary, not inside the LP). Either path leads to a tighter diagnose.

### C.2 Instrumentation (keep or remove post-diagnosis)

Temporarily add structured logging at 4 points:

```python
# build_ru_cvar_constraints entry
logger.info("ru_cvar_constraint_built",
    T=int(R.shape[0]), N=int(R.shape[1]),
    alpha=alpha, cvar_limit=cvar_limit,
    R_mean=float(R.mean()), R_std=float(R.std()),
    loss_sign_convention="L_i = -R_i @ w",
)

# Immediately after solver returns in optimize_fund_portfolio, for Phase 1 specifically:
realized = realized_cvar_from_weights(w_solution, R, alpha)
logger.info("phase_1_post_solve_cvar_check",
    cvar_limit_input=cvar_limit,
    cvar_realized_empirical=realized,
    cvar_reported_by_solver=float(result.cvar_95),
    delta_vs_limit=realized - cvar_limit,
)
```

Re-run the 3 canonical portfolios. Compare the `cvar_realized_empirical` (computed fresh on the exact weights) to `cvar_reported_by_solver` and to `cvar_limit_input`. The gap pattern is the smoking gun:

- Empirical == solver report, both > limit → constraint is mis-specified in LP
- Empirical > solver report → verifier and constraint disagree (convention mismatch)
- Empirical < limit but reported > limit → verifier uses wrong window
- Both == limit but log line 252 shows otherwise → logging bug (cheapest path — write once, forget)

### C.3 Report findings first

**STOP before writing a fix.** Post the empirical log output from C.1 + C.2 to the PR description. The consultant (this session) verifies the root cause identification before Opus proceeds to Section D.

---

## Section D — Implementation (choose ONE path based on C's findings)

### Path D.1 — Alpha convention fix

If B.1 confirmed: unify all call sites to pass `alpha=0.05` (tail probability) OR pass `confidence=0.95` and have the RU LP compute `tail = 1 - confidence` internally. Recommend the second (confidence-is-input) because it matches the institutional vocabulary in PR-A13 translations (`t("risk_budget.description") = "Maximum tail loss (95% confidence)"`).

Update `build_ru_cvar_constraints` signature and body. Update every caller. Update `realized_cvar_from_weights`. Add a unit test that explicitly verifies both conventions produce identical results for a known synthetic case.

### Path D.2 — Windowing fix

If B.2 confirmed: pick annualized as the canonical window (matches operator mental model + A13 slider default ranges). Inside the RU LP, scale by √252 BEFORE passing scenarios into the constraint. Verify with the empirical harness that `daily_cvar * √252 ≈ annualized_cvar` within 1-2bp tolerance.

Document in `optimizer_service.py` module docstring: "All CVaR inputs and outputs are annualized; scenarios are scaled internally."

### Path D.3 — Sign/loss convention fix

If B.3 confirmed: enforce one convention throughout. Recommend positive `cvar_limit`, positive `cvar_95` in all internal variables; negate only at the SSE / UI serialization boundary (operator sees "delivered CVaR −3.58%" consistent with P/L reporting elsewhere). Update `vertical_engines/wealth/model_portfolio/models.py:OptimizationMeta.cvar_95` docstring to make the convention explicit.

### Path D.4 — Scenario shape fix

If B.4 confirmed: add runtime assertion `assert R.ndim == 2 and R.shape[0] >= 252 and R.shape[1] == n_funds` to `build_ru_cvar_constraints`. Add a unit test that feeds a transposed matrix and confirms it raises.

### Combined path

If multiple hypotheses are confirmed, fix all of them in this PR. Do NOT split — the empirical verification in F.1 only holds if every violation is closed.

---

## Section E — Tests

### E.1 Regression unit test (mandatory regardless of path)

`test_phase_1_delivered_cvar_within_limit`: parametrize over 5 synthetic universes × 3 `cvar_limit` values × 3 `alpha` values; assert the hard invariant:

```python
assert abs(result.cvar_95) <= cvar_limit + 1e-3, (
    f"Phase 1 status={result.status} but delivered |CVaR|={abs(result.cvar_95):.4f} > "
    f"limit={cvar_limit:.4f} (violation={abs(result.cvar_95) - cvar_limit:.4f})"
)
```

This test MUST fail before the fix is applied (proves the repro harness catches the bug) and MUST pass after (proves the fix).

### E.2 Empirical consistency test

`test_realized_cvar_matches_solver_report`: for every Phase 1 run, the independently-computed `realized_cvar_from_weights(w, R, alpha)` must agree with `result.cvar_95` within 1e-4. This catches the "verifier uses different convention than constraint" class of bug.

### E.3 Sign convention test

`test_cvar_sign_convention`: assert `cvar_95` is reported with consistent sign across `fund_portfolio_optimized` log, `cascade_telemetry.phase_attempts[0].cvar_at_solution`, and the API response schema. Use a single golden example (Conservative synthetic) and snapshot-test the sign.

### E.4 Full regression

After the fix, re-run the A12 cascade tests (`pytest backend/tests/quant_engine/test_always_solvable_cascade.py`), the A11 telemetry tests, and the full wealth+quant sweep. All must remain green.

---

## Section F — Pass criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | Root cause identified empirically and reported in PR description | manual review by consultant before fix proceeds |
| 2 | Minimal repro test exists and fails pre-fix, passes post-fix | `pytest -v test_phase_1_delivered_cvar_within_limit` |
| 3 | All 3 canonical portfolios re-smoke with `cvar_within_limit=True` | live DB query of new `portfolio_construction_runs` rows |
| 4 | `cvar_95` sign consistent between log line `fund_portfolio_optimized` and `fund_level_optimizer_succeeded` | grep + visual |
| 5 | `realized_cvar_from_weights(w, R, α) ≈ result.cvar_95` within 1e-4 | E.2 test |
| 6 | A13 band upper bound truly reflects return at chosen CVaR (not at a larger unchecked CVaR) | live build, compare `band.upper_at_cvar` to `result.cvar_95` — must match within 1e-3 |
| 7 | No regression in A11/A12 existing tests | full sweep |
| 8 | Line 250 log spam pattern does not change (this PR does not touch attribution/coverage — those are P1 in separate PR) | expected — not a regression |

Per `feedback_dev_first_ci_later.md`: live-DB smoke on the 3 portfolios is the merge gate. CI green is not.

---

## Section G — Out of scope (explicit)

- Universe sub-coverage (line 250 `target_sum=0.6103`) — PR-A14 (Universe Coverage Gate)
- Factor returns dedup (line 245) — PR-A15 (factor fallback revival)
- Attribution log spam (lines 1-236) — PR-A16 (observability cleanup)
- Config miss taa_bands (line 244) — PR-A16
- Frontend preview endpoint `POST /preview-cvar` — PR-A13.1 (blocked until this PR merges)
- Frontend live drag preview — PR-A13.2 (blocked until A13.1)
- Changing the RU LP mathematical formulation — only fix the convention bug, not redesign the optimizer
- Changing `cvar_limit` default values (those were set by PR-A12.2; any further tuning is separate)

---

## Section H — Commit & PR

**Branch:** `feat/pr-a12-3-cvar-constraint-diagnose`

**Commit message (skeleton — fill in after root cause confirmed):**

```
fix(quant): RU CVaR constraint delivering CVaR > limit (PR-A12.3)

Conservative Preservation build on 2026-04-17 declared Phase 1 optimal
with CVaR delivered 2.36× the operator's limit (cvar_95=-0.189 vs
cvar_limit=0.08). Violates the always-solvable cascade's central
guarantee: Phase 1 success must imply CVaR ≤ L.

Root cause: <FILL IN — one of alpha convention, windowing, sign, shape>

Fix: <FILL IN — specific change>

Added test_phase_1_delivered_cvar_within_limit as a mandatory
parametrized regression (5 universes × 3 limits × 3 alphas). Added
test_realized_cvar_matches_solver_report to catch future convention
drift.

Empirical smoke (all 3 canonical portfolios post-fix):
  - Conservative: cvar_95=-0.0X within limit 0.025
  - Balanced: cvar_95=-0.0X within limit 0.05
  - Dynamic: cvar_95=-0.0X within limit 0.08

Unblocks PR-A13.1 (preview endpoint) and PR-A13.2 (live drag preview) —
neither can serve a trustworthy band until this lands.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `fix(quant): RU CVaR constraint delivering CVaR > limit (PR-A12.3)`

**PR body:** include the empirical investigation log (Section C.2 output), the identified root cause with line-number pointers, the diff of the fix, and the post-fix smoke results table showing all 3 portfolios with `cvar_within_limit=True`.

---

## Section I — Operating rules

1. **Diagnose before fix.** Post the Section C.2 log output and proposed root cause to the PR draft BEFORE modifying any optimizer code. Consultant (this session) must confirm the diagnosis matches the evidence.

2. **Brutal honesty:** if the instrumentation shows NONE of B.1-B.4 explains the observation, STOP and report. Do not fabricate a hypothesis — investigate further or escalate.

3. **One fix per hypothesis confirmed.** If multiple are confirmed, fix all in this PR (they compound). Do NOT split into separate PRs — A13.1 is blocked on the FULL fix.

4. **Preserve the sign/window convention choice in the module docstring.** Future PRs must not re-introduce the same ambiguity.

5. **The repro test must fail on the current main before the fix is applied.** If it passes without a fix, the test is not reproducing the production bug — redesign the test.

---

**End of spec. Execute exactly. The production build's `cvar_within_limit=False` alongside `status=optimal` is a correctness violation that invalidates every band shown in PR-A13's panel — this PR is the unblock for the whole A13.x cascade.**
