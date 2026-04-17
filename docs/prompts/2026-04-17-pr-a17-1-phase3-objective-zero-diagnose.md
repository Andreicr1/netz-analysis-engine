# PR-A17.1 — Diagnose & Fix: Phase 3 min-CVaR LP Returns objective=0.0 → upstream_heuristic Fallback

**Branch:** `feat/pr-a17-1-phase3-objective-zero-diagnose` (cut from `main` post-PR-A17 at commit `55166f69`).
**Estimated effort:** ~2-3h Opus (diagnose-first; fix ~30min once root cause confirmed).
**Predecessor:** PR-A17 #200 (geography + FI classifier).
**Blocks:** All production construction. Post-A17 ALL 3 canonical portfolios degrade to `upstream_heuristic` — construction pipeline is effectively down.

---

## Section A — Problem statement (empirical evidence)

Post-A17 the coverage improvements landed correctly (Conservative 94%, Balanced 80%, Growth 74%), but a regression surfaced: **every construction run ends in `cascade_summary=upstream_heuristic` with zero weights delivered.**

### A.1 What the event_log shows for all 3 portfolios

```
seq 4  Optimizer phase completed  phase=phase_2_ru_robust status=skipped
seq 5  Optimizer phase completed  phase=phase_3_min_cvar  status=succeeded  objective_value=0.0
seq 6  Optimizer cascade summary  cascade_summary=upstream_heuristic
                                   operator_signal.kind=upstream_data_missing
                                   operator_signal.binding=returns_quality
                                   operator_signal.message_key=statistical_inputs_unavailable
seq 7  Stress tests started       (runs on empty/invalid weights)
seq 11 Construction succeeded     status=degraded  wall_ms≈11400
```

**Contradiction:** Phase 3 LP solver returned `status=succeeded` with `objective_value=0.0`, yet the cascade summary decided the run is `upstream_heuristic` (the pre-flight bailout path — meant for "cascade never ran"). Phase 3 clearly DID run. The routing is broken.

### A.2 Pre-flight state is healthy (ruled-out causes)

| Check | Result |
|---|---|
| NAV coverage for all funds | 100% (3,184/3,184 instruments_org rows) |
| NAV depth ≥ 5Y (1,260 obs) | 100% across every block |
| Dedup outcome | n_input 380-465 → n_kept 136-147 (healthy — up from 92-95 pre-A17) |
| Strategic allocation feasibility | sum(min_weight) = 0.50-0.56, sum(max_weight) = 1.51-1.57 — ample slack |
| Universe coverage | 74-94% (well above A14's 20% hard-fail threshold) |

Data is NOT the problem. The problem is downstream of data loading, inside the optimizer cascade math or its winner-selection gate.

### A.3 Why pre-A17 worked

Pre-A17 the universe was ~90-95 funds post-dedup, concentrated in 7 block_ids (54% na_equity_large). Post-A17 it's 136-147 funds spread across 12-13 block_ids with broader international + FI sub-classification. The LP is solving the SAME mathematical formulation, but on a larger, more diverse universe. Something in the LP construction or its post-solve gate handles the larger universe incorrectly.

---

## Section B — Candidate root causes (ranked)

### B.1 Phase 3 LP returns degenerate solution (HIGH likelihood — Pattern A)

`prob3.value = 0.0` means the min-CVaR LP's objective evaluates to zero at its "optimal" point. Two legitimate reasons:

- **(B.1.a) Degenerate weights.** Solver returned status=optimal but `opt_w3` is all-zeros or sums to ~0. CLARABEL occasionally returns degenerate solutions for tight box-constrained LPs when primal-dual residuals hit the tolerance floor at a near-origin point. Downstream `_extract_weights(w3)` may return `None` or a zero vector that fails usability checks.
- **(B.1.b) Numerical precision collapse at scale.** The RU LP has (N + T + 1) variables — for N=147 funds and T=937 scenarios, that's 1,085 decision variables plus ~1,100 constraints. CLARABEL in its default tolerance (≈1e-8) may report primal-dual gap < tol but solution quality is still poor.

**If confirmed:** fix is either tighter solver config (eps_abs/eps_rel), explicit degenerate-solution detection (`if opt_w3.sum() < 1e-6: fall through`), or switch to SCS with tighter tolerance for large N.

### B.2 Min-CVaR objective ≈ 0 is genuine — gate is too strict (MEDIUM)

With a 136-fund universe spanning EM equity + DM Europe/Asia + treasury + TIPS + aggregate + HY credit + REITs + gold + cash, min-CVaR can mathematically collapse toward zero via cross-asset hedging (diversification). In that case `objective=0.0` is legitimate — the universe genuinely allows a near-zero-tail-risk portfolio.

If so, the downstream gate `_phase3_usable` (or equivalent A12.4-era check) rejects this as degenerate. Check patterns:

- Does the gate require `min_achievable_cvar > epsilon` for some epsilon?
- Does it compare `cvar_95` against a positive floor and reject if below?
- Does `realized_cvar_from_weights(weights, scenarios, alpha)` return exactly 0 (empirical, not LP-reported), confirming weights ARE hedged?

**If confirmed:** fix is relaxing the usability check — a low achievable CVaR is a WIN for the operator, not a failure. Cascade should accept and proceed with Phase 3 weights, reporting `cascade_summary=phase_3_min_cvar_within_limit`.

### B.3 `_run_construction_async` fallback path mis-routing (LOW but verifiable)

A12.3/A12.4 reworked the winning-phase logic. There may be a hold-over branch in `model_portfolios.py` that catches "Phase 3 usable but suspicious" conditions and builds a heuristic composition, then downstream maps that to `upstream_heuristic`. Grep for `solver="heuristic_fallback"` assignments post-Phase-3 success.

### B.4 Block constraints after A17 expansion + PR-A7 renormalization (LOW, already partially ruled out)

Section A.2 showed `sum(min_weight)` is 0.50-0.56 — feasible. But the interaction between PR-A7's `max_weight × 1/target_sum` rescaling and the now-higher `target_sum` (0.94 vs 0.61) compresses the per-block upper bounds. Could make the box-constrained LP region tighter but shouldn't produce `objective=0`.

---

## Section C — Investigation protocol (mandatory — no fix before diagnosis posted)

Same discipline as PR-A12.3 rounds 2-3. STOP before writing any fix. Post the instrumentation output to the PR draft, consultant confirms pattern, THEN proceed to Section D.

### C.1 Instrument Phase 3 post-solve (inside `optimize_fund_portfolio`)

Immediately after `opt_w3 = _extract_weights(w3)` returns, add:

```python
logger.info(
    "phase_3_post_solve_inspection",
    prob_status=str(prob3.status),
    prob_value=float(prob3.value) if prob3.value is not None else None,
    extracted_is_none=(opt_w3 is None),
    weights_sum=float(opt_w3.sum()) if opt_w3 is not None else None,
    weights_max=float(opt_w3.max()) if opt_w3 is not None else None,
    weights_nonzero_count=int((opt_w3 > 1e-6).sum()) if opt_w3 is not None else None,
    realized_cvar_daily=(
        float(realized_cvar_from_weights(opt_w3, returns_scenarios, cvar_alpha))
        if opt_w3 is not None else None
    ),
    realized_cvar_annual=(
        float(realized_cvar_from_weights(opt_w3, returns_scenarios, cvar_alpha) * SQRT_252)
        if opt_w3 is not None else None
    ),
)
```

### C.2 Instrument the usability gate that rejects Phase 3

Locate the winner-selection logic added in PR-A12.4 (in `optimize_fund_portfolio` after all 3 phases solve). The section that computes `_phase1_usable`, `_phase2_usable`, and should also handle Phase 3. Add:

```python
logger.info(
    "phase_winner_selection_trace",
    phase1_usable=_phase1_usable,
    phase1_weights_valid=(phase1_weights is not None),
    phase2_usable=_phase2_usable if "phase2_usable" in locals() else None,
    phase3_weights_valid=(phase3_weights is not None),
    phase3_realized_annual=(phase3_realized_annual if "phase3_realized_annual" in locals() else None),
    effective_cvar_limit=effective_cvar_limit,
    chosen_winning_phase=winning_phase,
    chosen_cascade_summary=cascade_summary,
)
```

### C.3 Instrument the `_run_construction_async` heuristic fallback branch

In `backend/app/domains/wealth/routes/model_portfolios.py`, locate the `except ValueError` / `except IllConditionedCovarianceError` / `composition is None` block that assigns `solver="heuristic_fallback"`. Add:

```python
logger.info(
    "construction_fell_to_heuristic_fallback",
    portfolio_id=str(portfolio_id),
    reason_type=type(e).__name__ if "e" in locals() else "composition_was_none",
    reason_msg=str(e) if "e" in locals() else None,
    fund_result_solver=fund_result.status if "fund_result" in locals() else None,
    fund_result_weights_count=len(fund_result.weights) if "fund_result" in locals() and hasattr(fund_result, "weights") else None,
)
```

### C.4 Run the 3 canonical smokes + attach logs

Trigger Conservative + Balanced + Growth builds (via the existing smoke harness or direct POST). Capture uvicorn stdout for all 3 runs. Identify which of B.1.a / B.1.b / B.2 / B.3 matches the observed data:

| Pattern match | Evidence in logs |
|---|---|
| B.1.a degenerate weights | `phase_3_post_solve_inspection.weights_sum ≈ 0` AND `weights_nonzero_count < 2` |
| B.1.b numerical collapse | `prob_status="optimal_inaccurate"` OR `weights_sum ≈ 1` but `realized_cvar_daily ≈ 0` with 0 meaningful weights |
| B.2 genuine near-zero CVaR | `weights_sum ≈ 1` AND `weights_nonzero_count >= 10` AND `realized_cvar_annual < 0.005` (legitimate small CVaR from diversification) |
| B.3 fallback mis-routing | `construction_fell_to_heuristic_fallback` log fires with a specific exception type |

### C.5 Report findings + confirmed pattern

**STOP before fix.** Post to the PR draft:
- The 3 sets of `phase_3_post_solve_inspection` logs (one per portfolio)
- The 3 sets of `phase_winner_selection_trace` logs
- The `construction_fell_to_heuristic_fallback` log if it fired
- Your pattern identification (B.1.a / B.1.b / B.2 / B.3) with evidence

Consultant confirms before Section D proceeds.

---

## Section D — Implementation (branches by pattern)

### Path D.1 — Pattern B.1.a: degenerate solver output

Detect and reject degenerate weights explicitly in `optimize_fund_portfolio`:

```python
if opt_w3 is not None and opt_w3.sum() < 1e-4:
    logger.warning("phase_3_degenerate_solution_rejected",
                   weights_sum=float(opt_w3.sum()))
    opt_w3 = None  # treat as infeasible
```

Upstream fallback then fires correctly. Separately, investigate WHY the LP returned degenerate — may be a missing `sum(w) == 1` constraint or wrong `cp.Variable` bounds.

### Path D.2 — Pattern B.1.b: numerical precision

Tighten solver config:

```python
prob3.solve(
    solver=cp.CLARABEL,
    eps_abs=1e-9,
    eps_rel=1e-9,
    max_iter=500,
)
```

If CLARABEL still can't converge cleanly, fall back to SCS with tight tolerance. Add a post-solve sanity check (`weights_sum > 0.99` required) and escalate to heuristic if unmet.

### Path D.3 — Pattern B.2: gate too strict

Remove or relax the usability check. The correct semantic is: "Phase 3 succeeds if it returns valid weights (sum ≈ 1, non-trivial), regardless of how low the CVaR is." Near-zero CVaR is a good outcome.

Specifically, the gate should be:

```python
_phase3_usable = (
    phase3_weights is not None
    and abs(phase3_weights.sum() - 1.0) < 1e-3
    and (phase3_weights > 1e-6).sum() >= 2  # at least 2 non-trivial positions
)
# NO min_achievable_cvar > epsilon check — any non-negative CVaR is valid
```

Post-fix, Phase 3 delivers a diversified near-zero-CVaR portfolio and cascade_summary becomes `phase_3_min_cvar_within_limit`.

### Path D.4 — Pattern B.3: fallback mis-routing

Fix the `_run_construction_async` branch that builds `heuristic_fallback` composition when Phase 3 actually succeeded. Ensure that when `fund_result.status` is successful and weights are valid, the composition is built from the fund_result, NOT from the heuristic path.

### Combined path

If multiple patterns apply, fix all in this PR. Do NOT split — production construction is blocked.

---

## Section E — Tests

### E.1 Regression test (mandatory)

Add to `backend/tests/quant_engine/test_phase_winner_invariant.py` (created in PR-A12.4):

```python
async def test_phase_3_accepts_near_zero_cvar_when_weights_valid(seeded_portfolio):
    """PR-A17.1 regression: a diversified universe with natural near-zero min-CVaR
    must NOT be treated as degenerate. Phase 3 should succeed with
    cascade_summary=phase_3_min_cvar_within_limit when weights sum ~1 and
    have >= 2 non-trivial positions, even if min_achievable_cvar is very small."""
    # Seed a universe with 50+ funds across 10+ blocks so cross-asset hedging is possible
    portfolio = await seeded_portfolio(profile="conservative", universe_size=50)
    result = await _run_construction_async(db, "conservative", org_id, portfolio.id)
    assert result["cascade_telemetry"]["cascade_summary"] in (
        "phase_1_succeeded",
        "phase_3_min_cvar_within_limit",
        "phase_3_min_cvar_above_limit",
    ), f"Unexpected summary: {result['cascade_telemetry']['cascade_summary']}"
    assert result["cascade_telemetry"]["cascade_summary"] != "upstream_heuristic", (
        "Phase 3 valid weights MUST NOT route to upstream_heuristic"
    )
    weights_sum = sum(result["weights_proposed"].values())
    assert abs(weights_sum - 1.0) < 1e-3, f"weights sum {weights_sum} != 1"
```

Parametrize across the 3 profiles. Test MUST fail on current main and pass post-fix.

### E.2 Integration smoke

Re-run `backend/tests/integration/test_construction_cvar_invariant.py`. Expect:
- All 3 portfolios: `cascade_summary in ("phase_1_succeeded", "phase_3_min_cvar_within_limit", "phase_3_min_cvar_above_limit")`
- NONE with `cascade_summary == "upstream_heuristic"`
- `sum(weights_proposed.values()) ≈ 1.0` for all 3

### E.3 Do NOT weaken existing A12.4 invariants

`test_phase_winner_invariant` from A12.4 already asserts "Phase 1 winner implies delivered cvar ≤ limit". Keep that. The A17.1 fix only affects Phase 3's usability gate, not Phase 1/2.

---

## Section F — Pass criteria

| # | Criterion | Evidence |
|---|---|---|
| 1 | Root cause pattern identified + posted to PR draft | manual review by consultant |
| 2 | Regression test E.1 fails pre-fix, passes post-fix | pytest |
| 3 | All 3 canonical portfolios live smoke: `cascade_summary != "upstream_heuristic"` | SQL query |
| 4 | `sum(weights_proposed.values()) ≈ 1.0` for all 3 | live smoke |
| 5 | `ex_ante_metrics.cvar_95 != null` and is a real number for all 3 | live smoke |
| 6 | At least one profile (Conservative, likely) flips to `phase_3_min_cvar_within_limit` (universe floor now below 2.5% after universe expansion) | live smoke comparison |
| 7 | A12.4 existing regression tests still green | pytest |
| 8 | Full suite 380/380 or better | CI |

Per `feedback_dev_first_ci_later.md`: live-DB smoke is the merge gate.

---

## Section G — Out of scope (explicit)

- Factor equity sub-classification (na_equity_value / na_equity_growth) — PR-A17.2
- Commodity ETF routing (alt_commodities) — PR-A17.2
- XBRL / N-CEN richer FI classification — PR-A17.3
- Factor returns dedup — PR-A15
- Attribution log spam + taa_bands — PR-A16
- μ prior calibration — separate sprint
- Any change to Phase 1 or Phase 2 logic (they're correct post-A12.4)
- Tightening SCS solver tolerance globally — only apply to Phase 3 if Pattern B.1.b confirmed
- Changing the RU LP math — only the usability gate or solver config

---

## Section H — Commit & PR

**Branch:** `feat/pr-a17-1-phase3-objective-zero-diagnose`

**Commit message skeleton (fill after pattern confirmed):**

```
fix(quant): Phase 3 min-CVaR accepts low objective as valid (PR-A17.1)

Post-A17, the richer universe (136-147 funds / 12-13 blocks) pushed
min-achievable CVaR to near-zero for the 3 canonical portfolios — a
legitimate outcome of cross-asset hedging over EM equity + DM Europe/Asia
+ treasury + TIPS + aggregate + HY. The winner-selection gate
(PR-A12.4 pattern) rejected this as degenerate and routed all runs to
upstream_heuristic, blocking production construction.

Root cause (Pattern <X>): <diagnosis>

Fix: <specific change to gate / solver / LP>

Regression test test_phase_3_accepts_near_zero_cvar_when_weights_valid
added to catch future gate over-rejection. Asserts Phase 3 with
sum(w) ≈ 1 and >= 2 non-trivial positions must be accepted regardless
of min_achievable_cvar magnitude.

Post-fix smoke (3 canonical portfolios):
  Conservative: cascade_summary=<result>  cvar_95=<value>
  Balanced:     cascade_summary=<result>  cvar_95=<value>
  Growth:       cascade_summary=<result>  cvar_95=<value>

Unblocks production construction. All 3 portfolios deliver valid
weights + ex_ante metrics again.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Section I — Operating rules

1. **Diagnose before fix.** Post instrumentation logs + confirmed pattern BEFORE modifying any code beyond the logger calls. Consultant blocks fix-merge if diagnosis is incomplete.
2. **Brutal honesty.** If instrumentation reveals a pattern not in B.1-B.4, STOP and escalate. Do not force-fit a hypothesis.
3. **One fix per confirmed pattern.** If multiple patterns are true, fix all in this PR — do not split.
4. **Regression test must fail pre-fix.** If `test_phase_3_accepts_near_zero_cvar` passes without a fix on current main, the test doesn't reproduce the bug — redesign it.
5. **Integration smoke harness run mandatory.** `tests/integration/test_construction_cvar_invariant.py` must green post-fix. This is the guardrail that would have caught this regression in A17 itself.
6. **Preserve PR-A14 coverage signal.** Secondary signal still fires for profiles below 85% coverage — that's correct and unchanged.

---

**End of spec. Execute exactly. Production construction pipeline is blocked — this PR is the unblock. No delay for housekeeping; this merges as soon as smoke shows all 3 portfolios delivering valid weights again.**
