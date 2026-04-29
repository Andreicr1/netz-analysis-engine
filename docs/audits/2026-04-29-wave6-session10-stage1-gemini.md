# Session 10 — Wealth Model Portfolio Lifecycle Audit

## Findings

```text
ID: F-S10-1
Title: CVaR improvement calculation flips sign and recommends worst funds
Files/lines: backend/vertical_engines/wealth/model_portfolio/construction_advisor.py:339
Math severity: Crit
Institutional severity: High
Type: Math
Evidence:
improvement = round((current_cvar - projected) / abs(current_cvar), 4)
Expected invariant: Math correctness
Why it is wrong: CVaR follows a negative-loss convention (e.g., `-0.08` is an 8% loss). If a candidate improves CVaR to `-0.06`, `current_cvar - projected` evaluates to `-0.08 - (-0.06) = -0.02`. The resulting `improvement` is negative. Conversely, a candidate that worsens CVaR to `-0.10` yields a positive improvement (`+0.02`). The sorting then ranks candidates by `cvar_improvement` descending, meaning the advisor will proactively recommend the funds that inflict the maximum risk damage to the portfolio.
Recommended fix: Reverse the subtraction order: `improvement = round((projected - current_cvar) / abs(current_cvar), 4)`.
Minimum test:
def test_cvar_improvement_sign():
    # current_cvar = -0.08, projected = -0.06 (better) -> improvement must be positive
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-2
Title: Historical stress test silently imputes 0% return for missing history
Files/lines: backend/vertical_engines/wealth/model_portfolio/track_record.py:183
Math severity: Crit
Institutional severity: High
Type: TrackRecord
Evidence:
for fid, w in zip(fund_ids, weights, strict=False):
    r = returns_lookup.get((fid, d), 0.0)
    day_return += w * r
Expected invariant: I-Track-Record-1
Why it is wrong: When computing the historical stress impact of a scenario (like the 2008 GFC), any fund in the portfolio that did not exist at that time will have `returns_lookup.get(..., 0.0)` silently return exactly 0.0% per day. This treats young funds as 0% volatility cash during the crisis, artificially dampening the portfolio's max drawdown. A portfolio primarily holding funds incepted after 2010 will incorrectly report near-zero losses for the GFC.
Recommended fix: Track the percentage of the portfolio weight that has valid data on each day. If coverage drops below a threshold (e.g., 80%), degrade the scenario result (e.g., return `None` or append a `partial_data` warning flag) or map missing funds to a benchmark proxy.
Minimum test:
def test_historical_stress_handles_missing_funds():
    # A portfolio with 100% in a fund incepted in 2015 should NOT report a 0% max drawdown for the 2008 GFC.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-3
Title: OD-5 soft block override crashes state machine due to missing edge
Files/lines: backend/vertical_engines/wealth/model_portfolio/state_machine.py:80 + backend/vertical_engines/wealth/model_portfolio/state_machine.py:126
Math severity: N/A
Institutional severity: Crit
Type: StateMachine
Evidence:
TRANSITIONS: Final[dict[State, set[State]]] = {
    ...
    "constructed": {"validated", "rejected", "draft"},
}
# Later in compute_allowed_actions:
if validation.passed or not policy.require_construction_for_approve:
    actions.append(ACTION_APPROVE)
Expected invariant: I-State-2
Why it is wrong: The action mapping explicitly allows `ACTION_APPROVE` from the `constructed` state under the OD-5 soft-block policy (when validation fails but an override is allowed). However, the backend-authoritative `TRANSITIONS` graph does not have an edge from `constructed` to `approved`. When the route layer attempts this transition via `transition(to_state="approved")`, it will raise `InvalidStateTransition`, completely breaking the OD-5 override workflow.
Recommended fix: Add `"approved"` to the set of allowed transitions from `"constructed"` in the `TRANSITIONS` dictionary.
Minimum test:
async def test_od5_soft_block_override_transition():
    # With require_construction_for_approve=False, transitioning constructed -> approved should succeed.
    pass
Breaking-change risk: API contract
Confidence: High
Open questions: None
```

```text
ID: F-S10-4
Title: State machine bypasses centralized audit log system
Files/lines: backend/vertical_engines/wealth/model_portfolio/state_machine.py:257
Math severity: N/A
Institutional severity: Crit
Type: Audit
Evidence:
transition_row = PortfolioStateTransition(...)
db.add(transition_row)
Expected invariant: I-State-1
Why it is wrong: The state machine writes a Django/SQLAlchemy model `PortfolioStateTransition` directly to the database but fails to call the core `write_audit_event` function mandated by the Stability Charter (Q92). This bypasses the centralized immutable audit log system, meaning state transitions will not appear in the tenant's unified audit feed, breaking institutional audit trail integrity.
Recommended fix: Import `write_audit_event` from `app.core.db.audit` and call it within the `transition` transaction, passing `allow_global=False` to ensure tenant scoping.
Minimum test:
@patch("vertical_engines.wealth.model_portfolio.state_machine.write_audit_event")
async def test_transition_writes_audit_event(mock_audit, db_session):
    # Verify write_audit_event is called with allow_global=False
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-5
Title: CVaR stress shift smears cumulative impact over arbitrary daily sample
Files/lines: backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:228
Math severity: Crit
Institutional severity: High
Type: StressScale
Evidence:
if historical_returns is not None and len(historical_returns) >= 30:
    shifted = historical_returns + nav_impact / len(historical_returns)
    cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)
Expected invariant: I-Stress-Scale-1
Why it is wrong: `nav_impact` is a *cumulative* scenario return (e.g., -38% for the 1.5-year GFC). Dividing a cumulative shock by the length of an arbitrary historical array (which could be 5 or 10 years of *daily* returns) produces a mathematically meaningless daily shift. The magnitude of the stress applied to CVaR becomes an inverse function of the historical window length, understating the risk proportionally to how much data is provided.
Recommended fix: Convert the cumulative `nav_impact` to a daily equivalent shock based on the *scenario length* (e.g., 252 days for a 1-year shock), or apply the stress to the expected return parameter rather than shifting every historical daily return point.
Minimum test:
def test_stress_cvar_shift_invariant_to_history_length():
    # Passing 1000 days vs 2000 days of the same distribution should yield the same stressed CVaR.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-6
Title: Silent dropping of empty allocation blocks silently alters strategic targets
Files/lines: backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py:98
Math severity: High
Institutional severity: Crit
Type: BlockMap
Evidence:
block_funds = funds_by_block.get(block_id, [])
if not block_funds:
    logger.warning("portfolio_block_empty", ...)
    continue
...
if total_allocated > 0 and abs(total_allocated - 1.0) > 1e-6:
    factor = 1.0 / total_allocated
Expected invariant: I-Block-Map-1
Why it is wrong: If an allocation block (e.g., Fixed Income) has no approved funds in the universe (e.g., due to mandate filtering), the builder silently skips the block. It then normalizes the remaining weights to 1.0. This silently overrides the strategic asset allocation (e.g., a 60/40 Equity/Bond target becomes 100% Equity if bonds are missing), exposing the client to unintended risk profiles without an explicit failure or approval blocker.
Recommended fix: Raise an exception (e.g., `ValueError(f"No approved funds for block {block_id}")`) instead of silently continuing, so the construction run fails loudly and the user must address the gap.
Minimum test:
def test_construct_fails_on_empty_block():
    # Constructing a portfolio where a target block has 0 valid funds must raise an exception.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-7
Title: Stale NAV check ignores staleness threshold entirely
Files/lines: backend/vertical_engines/wealth/model_portfolio/validation_gate.py:126
Math severity: N/A
Institutional severity: High
Type: Approval
Evidence:
for iid in instrument_ids:
    latest = db.nav_latest_date.get(iid)
    if latest is None:
        stale_count += 1
Expected invariant: I-Approval-1
Why it is wrong: The check claims to verify that NAV data is not older than `db.nav_staleness_threshold_days`, but it ONLY increments `stale_count` if `latest is None` (i.e., missing entirely). It performs no date arithmetic against `as_of_date` or the current date. A fund with NAV data from 5 years ago will pass this "stale NAV" check, potentially allowing an approved portfolio to use dangerously outdated prices for risk/return metrics.
Recommended fix: Parse the `latest` date and compare it against `as_of_date`. Increment `stale_count` if the difference in days exceeds `db.nav_staleness_threshold_days`.
Minimum test:
def test_stale_nav_fails_on_old_date():
    # A fund with latest NAV 30 days ago must fail the 10-day threshold check.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-8
Title: Idiosyncratic stress dispersion uses constant seed, eliminating randomness
Files/lines: backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:171
Math severity: High
Institutional severity: Med
Type: Math
Evidence:
# Inside run_stress_scenario_fund_level loop:
fund_shock = apply_idiosyncratic_dispersion(..., seed=seed)
# Inside apply_idiosyncratic_dispersion:
rng = np.random.default_rng(seed)
residual = float(rng.normal(0.0, residual_sigma))
Expected invariant: Math correctness
Why it is wrong: By passing the same static `seed` (e.g., 42) into `apply_idiosyncratic_dispersion` for every fund, a fresh random number generator is initialized with the identical seed on each iteration. The "random" standard normal draw will therefore be the exact same scalar value for every fund. This causes all funds within a block that have the same volatility to receive the *exact same* simulated shock, completely defeating the purpose of adding idiosyncratic cross-sectional dispersion.
Recommended fix: Initialize `rng = np.random.default_rng(seed)` *once* outside the loop, and pass the `rng` instance into the dispersion function, or mix the fund's UUID into the seed (e.g., `seed ^ hash(fund_id)`) to ensure independent draws while preserving determinism.
Minimum test:
def test_dispersion_is_cross_sectionally_independent():
    # Two funds in the same block with identical vol should get different shocks.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

```text
ID: F-S10-9
Title: Mandate fit evaluator treats all client preferences as hard constraints
Files/lines: backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py:84 + backend/vertical_engines/wealth/mandate_fit/service.py:65
Math severity: N/A
Institutional severity: High
Type: HardSoftConstraint
Evidence:
disqualifying = tuple(r.reason for r in results if not r.passed)
eligible = len(disqualifying) == 0
Expected invariant: I-Hard-Soft-2
Why it is wrong: The `MandateFitService` provides no explicit separation between hard regulatory constraints (e.g., restricted domicile, liquidity caps) and soft client preferences (e.g., ESG tilt). Every evaluated constraint returns `passed=False` on a mismatch, which the service aggregates into `eligible=False` if *any* single check fails. This means a soft preference miss will incorrectly disqualify an otherwise optimal instrument, artificially shrinking the universe and blocking portfolio construction.
Recommended fix: Update `ConstraintResult` to include a `severity` field (`hard` vs `soft`). Soft constraint misses should decrease the `suitability_score` and generate warnings but should not append to `disqualifying_reasons` or force `eligible=False`.
Minimum test:
def test_soft_preference_does_not_disqualify():
    # A soft preference miss (e.g. ESG) should leave eligible=True but drop score < 1.0.
    pass
Breaking-change risk: None
Confidence: High
Open questions: None
```

## Checked invariants with no finding

- **I-Stress-Sign-1**: Stress display label and validation threshold use the same sign convention. Verified: `worst >= -0.40` correctly validates against negative total return shocks in the scenarios.
- **I-Approval-2**: Portfolio cannot enter `approved` state without `validation_gate.evaluate() == PASS`. Verified: Without the OD-5 override, the action computer strictly enforces this.
- **I-Mandate-Scale-1**: Mandate constraint thresholds use fractional convention. Verified: `compute_suitability_score` uses proper ratios, and risk comparisons use deterministic integer ranking.

## Handoff items

- The fallback logic in `_evaluate_set` when `total_new_weight >= 1.0` scales down candidate target weights relative to the portfolio implicitly. While this works as a brute-force heuristic, it may warrant review by the quant team (Session 04/05) for theoretical robustness.

## Top 3 priorities

1. **F-S10-1**: CVaR improvement calculation flips sign and recommends worst funds (Crit/High) — actively malicious recommendations.
2. **F-S10-3**: OD-5 soft block override crashes state machine (N/A/Crit) — broken critical workflow path.
3. **F-S10-2**: Historical stress test silently imputes 0% return for missing history (Crit/High) — wildly inaccurate risk optics.
