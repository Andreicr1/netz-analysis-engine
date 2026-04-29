# Wave 6 Session 10 Stage 1 — Opus Audit

**Auditor:** Claude Opus 4.6 (1M context)
**Date:** 2026-04-29
**Scope:** Wealth Model Portfolio, Mandate Fit, Validation Gate
**Files audited:** 9 primary + 4 cross-reference (construction_run_executor, model_portfolio ORM, audit.py, routes/model_portfolios.py)
**Total LoC audited:** ~5,800

---

## Findings

---

```
ID: F-S10-01
Title: Validation gate bypass — approve reachable without gate check
Files/lines: state_machine.py:57-66 + state_machine.py:175-189 + routes/model_portfolios.py:403-412
Math severity: N/A
Institutional severity: Crit
Type: Approval
Evidence:
  TRANSITIONS dict (state_machine.py:57-66):
    "constructed": {"validated", "rejected", "draft"}     # "approved" NOT here
    "validated":   {"approved", "draft"}

  compute_allowed_actions("constructed") (state_machine.py:175-184):
    actions.append(ACTION_VALIDATE)  # always available
    if validation.passed or not policy.require_construction_for_approve:
        actions.append(ACTION_APPROVE)  # offered when gate passes

  _ACTION_TO_TARGET_STATE (routes/model_portfolios.py:403-412):
    ACTION_APPROVE: "approved"        # maps to "approved" state
    ACTION_VALIDATE: "validated"      # maps to "validated" state

  Two consequences:
  A) ACTION_APPROVE from "constructed" is dead code: route calls
     transition(to_state="approved") but TRANSITIONS["constructed"]
     does NOT include "approved" → InvalidStateTransition → HTTP 409.
     The validation.passed check (the ONLY gate check) guards a path
     that can never succeed.

  B) The ACTUAL path to approval has NO gate check:
     1. Portfolio in "constructed" with validation_gate.passed=False
     2. User clicks Validate → ACTION_VALIDATE always available from
        "constructed" (line 177, unconditional)
     3. Route calls transition(to_state="validated") → succeeds
        (TRANSITIONS["constructed"] includes "validated")
     4. Portfolio now in "validated"
     5. compute_allowed_actions("validated") (line 186-189):
        Always returns ACTION_APPROVE — no validation check
     6. User clicks Approve → route calls transition(to_state="approved")
        → succeeds (TRANSITIONS["validated"] includes "approved")
     7. Portfolio reaches "approved" despite FAILED validation gate

Expected invariant: I-Approval-1, I-Approval-2
Why it is wrong:
  The validation_gate.passed check exists (state_machine.py:181) but
  guards a dead-code path. The live path (constructed → validated →
  approved) bypasses the check entirely. A portfolio with any number
  of block-severity failures (CVaR breach, banned instruments, weight
  violations) can reach "approved" in two clicks. This is an approval
  bypass of the hard constraint validation system.
Recommended fix:
  Option A (preferred): Add gate check to the "validated" state's
  allowed_actions — only offer ACTION_APPROVE when validation.passed:
    elif state == "validated":
        if validation is not None and validation.passed:
            actions.append(ACTION_APPROVE)
        actions.append(ACTION_REBUILD_DRAFT)
  Option B: Remove ACTION_APPROVE from "constructed" state entirely
  (it's dead code) and add gate check as above.
Minimum test:
  def test_approve_blocked_when_validation_failed():
      actions = compute_allowed_actions(
          "validated",
          validation=ValidationStatus(has_run=True, passed=False),
      )
      assert ACTION_APPROVE not in actions

  def test_approve_from_constructed_raises():
      # Verify the dead-code path actually fails
      with pytest.raises(InvalidStateTransition):
          await transition(db, portfolio_id=pid, to_state="approved", actor_id="x")
      # (where portfolio.state == "constructed")
Breaking-change risk: API contract (allowed_actions response shape changes)
Confidence: High
Open questions: None — the TRANSITIONS dict and action mapping are explicit.
```

---

```
ID: F-S10-02
Title: Construction executor passes empty ValidationDbContext — 6 of 16 checks disabled
Files/lines: construction_run_executor.py:2037-2038
Math severity: N/A
Institutional severity: Crit
Type: Approval
Evidence:
  validation_result = validate_construction(
      validation_payload, ValidationDbContext(),  # default empty context
  )

  ValidationDbContext() defaults:
    banned_instrument_ids = frozenset()        → check 9 always passes
    approved_instrument_ids = frozenset()      → check 10 downgrades to warn, "skipped"
    strategic_targets = {}                     → (not directly used by checks)
    block_constraints = {}                     → checks 7, 8, 16 iterate empty dict, pass vacuously
    nav_latest_date = {}                       → check 2 would flag all instruments...
                                                 BUT validation_payload has no "as_of_date" key
                                                 (lines 2023-2036), so the guard `if as_of_date:`
                                                 is False and stale_count stays 0 → passes

  Net result: checks 2, 7, 8, 9, 10, 16 are ALL vacuously passing.
  That's 6 of 16 checks disabled, including:
    - Block min/max weight enforcement (checks 7-8)
    - Banned instrument detection (check 9)
    - Approved universe verification (check 10)
    - NAV staleness (check 2)
    - TAA bands vs IPS (check 16)

  The test suite (test_validation_gate.py) creates a properly populated
  _base_db_context() — confirming the checks WORK when context is
  provided. The executor simply never populates it.

Expected invariant: I-Block-Map-1, I-Approval-2
Why it is wrong:
  The validation gate was designed as a 16-check panel (docstring
  validation_gate.py:1-46). Tests prove all 16 checks function when
  given proper context. But in production, the executor runs with
  empty context, disabling all org-specific guardrails. A portfolio
  containing banned instruments, unapproved instruments, or breaching
  block weight constraints would pass the gate.
Recommended fix:
  Populate ValidationDbContext in the executor before calling
  validate_construction. The executor already has the DB session and
  organization_id — fetch the org's banned list, approved universe,
  block constraints, and latest NAV dates. Also add "as_of_date" to
  the validation_payload.
Minimum test:
  def test_executor_populates_validation_db_context():
      """Executor must pass non-empty ValidationDbContext to validate_construction."""
      # Integration test: run execute_construction_run with a known org
      # that has banned instruments → verify the validation result
      # shows check 9 (no_banned_instruments) as FAILED, not PASSED.
Breaking-change risk: None (internal worker behavior)
Confidence: High
Open questions: None — the empty constructor call is verbatim at line 2038.
```

---

```
ID: F-S10-03
Title: Block-severity check exception silently demoted to warn — fails open
Files/lines: validation_gate.py:772-783
Math severity: N/A
Institutional severity: High
Type: Approval
Evidence:
  for _check_id, check_fn in CHECKS:
      try:
          result = check_fn(run_payload, db_context)
      except Exception as exc:  # noqa: BLE001
          # A check that raises is a warn-level failure — never a
          # block — so a bug in one check can't strand activation.
          result = ValidationCheck(
              id=_check_id,
              label=_check_id.replace("_", " ").capitalize(),
              severity="warn",   # <-- ALWAYS warn, regardless of check's intended severity
              passed=False,
              value=None,
              threshold=None,
              explanation=f"Check raised: {type(exc).__name__}: {exc}",
          )

  Example scenario: _check_cvar_within_limit receives a payload where
  calibration_snapshot.cvar_limit is a string "0.05" instead of float.
  float("0.05") works, so this particular case is fine. But if the
  payload has cvar_limit=None and the -abs() call hits TypeError:
    limit_f = -abs(float(limit))  # TypeError: float() arg must be...
  Wait — the None case IS handled (line 199-208). But a deeper
  corruption (e.g., limit="N/A") would cause float("N/A") → ValueError
  → caught at line 772 → demoted to warn.

  Block-severity checks that could be silenced this way:
  - weights_sum_to_one (check 1)
  - no_stale_nav (check 2)
  - cvar_within_limit (check 3)
  - min_diversification_count (check 5)
  - max_single_fund_weight (check 6)
  - all_block_min/max_weights (checks 7-8)
  - no_banned_instruments (check 9)
  - all_instruments_approved (check 10)
  - taa_bands_within_ips (check 16)

Expected invariant: I-Approval-1
Why it is wrong:
  The "fail-soft" design (documented in the code and test suite) is
  intentional to prevent activation lock-out from a check bug. However,
  institutional convention for hard constraints is fail-CLOSED: if the
  CVaR check cannot compute, the portfolio must NOT pass — the unknown
  state should be treated as a breach. The current design silently
  converts any block failure caused by corrupted input into a non-
  blocking warning, making the gate permeable to data quality issues.
Recommended fix:
  Preserve the check's declared severity when catching exceptions:
    except Exception as exc:
        original_check = check_fn.__name__
        # Infer intended severity from the check's code
        result = ValidationCheck(
            id=_check_id,
            severity=_INTENDED_SEVERITY.get(_check_id, "block"),
            passed=False,
            ...
        )
  Or simpler: maintain a registry of which checks are block-severity
  and use that in the except handler.
Minimum test:
  def test_block_check_exception_stays_block_severity():
      """An exception in a block-severity check must NOT pass the gate."""
      payload = {"weights_proposed": {"a": "not_a_number"}}
      result = validate_construction(payload, ValidationDbContext())
      # weights_sum_to_one should fail as block, not warn
      wst = next(c for c in result.checks if c.id == "weights_sum_to_one")
      assert wst.severity == "block"
      assert not result.passed
Breaking-change risk: Tenant-visible behavior (portfolios that previously
  passed despite a check exception will now fail)
Confidence: High
Open questions: The code comments explicitly call this a "feature" — the
  jury should adjudicate whether fail-open or fail-closed is the correct
  institutional default for block-severity checks.
```

---

```
ID: F-S10-04
Title: Stressed CVaR shift divided by T renders it negligible
Files/lines: stress_scenarios.py:247 + stress_scenarios.py:308
Math severity: Crit
Institutional severity: High
Type: StressScale
Evidence:
  Line 308 (run_stress_scenario):
    shifted = historical_returns + nav_impact / len(historical_returns)
    cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)

  Line 247 (run_stress_scenario_fund_level):
    shifted = historical_returns + nav_impact / len(historical_returns)
    cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)

  Concrete example:
  - nav_impact = -0.38 (GFC scenario: 38% portfolio loss)
  - historical_returns has T = 252 daily observations
  - Per-day shift = -0.38 / 252 = -0.00151
  - Daily returns typically ±0.01 (1%), so the shift is 15% of
    typical daily vol — barely visible in the distribution
  - If unstressed CVaR_95 = -0.08 (8% loss), the shift moves CVaR
    by approximately -0.0015, giving stressed CVaR ≈ -0.0815
  - That's a 1.9% relative change from a 38% stress event

  The formula treats nav_impact as a total-period loss and spreads it
  uniformly across T daily observations. This is a mean-shift approach,
  but the magnitude is wrong: dividing by T converts a period shock
  into a negligible daily shift. The stressed CVaR is practically
  identical to the unstressed CVaR for all 4 preset scenarios.

Expected invariant: I-Stress-Scale-1
Why it is wrong:
  The validation gate's check 11 (stress_within_tolerance, line 454-488)
  uses nav_impact_pct (the total portfolio loss) correctly for its
  threshold comparison. But cvar_stressed — the field intended to show
  how CVaR changes under stress — is meaningless due to the 1/T
  dilution. IC relying on cvar_stressed for stressed risk assessment
  would see essentially unstressed numbers.
Recommended fix:
  Apply the shock as a single extreme observation appended to the
  return series, not as a uniform shift:
    shock_day = np.array([nav_impact])  # single-day equivalent
    shifted = np.concatenate([historical_returns, shock_day])
    cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)
  Or use the stress scenario's historical window (which
  compute_stress() in track_record.py already does correctly for
  the 3 named scenarios).
Minimum test:
  def test_stressed_cvar_materially_different_from_unstressed():
      returns = np.random.normal(0.0004, 0.01, 252)  # typical daily
      from quant_engine.cvar_service import compute_cvar_from_returns
      base_cvar, _ = compute_cvar_from_returns(returns)
      result = run_stress_scenario(
          {"equity": 1.0}, {"equity": -0.38}, returns, "gfc"
      )
      # Stressed CVaR should be materially worse
      assert result.cvar_stressed is not None
      assert result.cvar_stressed < base_cvar * 1.10  # at least 10% worse
Breaking-change risk: Tenant-visible behavior (cvar_stressed values
  in stress_results JSONB will change materially)
Confidence: High
Open questions: None — arithmetic is deterministic.
```

---

```
ID: F-S10-05
Title: Same RNG seed for all funds defeats idiosyncratic dispersion
Files/lines: stress_scenarios.py:222-232 + stress_scenarios.py:79-123
Math severity: High
Institutional severity: Med
Type: StressSign
Evidence:
  run_stress_scenario_fund_level (line 222-232):
    for fund_id, weight in fund_weights.items():
        block_shock = shocks.get(block_id, 0.0)
        fund_shock = apply_idiosyncratic_dispersion(
            block_shock=block_shock,
            fund_volatility=fund_volatilities.get(fund_id),
            fund_beta=fund_betas.get(fund_id),
            seed=seed,       # <-- same seed=42 for every fund
        )

  apply_idiosyncratic_dispersion (line 119-121):
    rng = np.random.default_rng(seed)   # fresh RNG each call
    residual_sigma = dispersion_scale * float(fund_volatility)
    residual = float(rng.normal(0.0, residual_sigma))

  Each call creates a FRESH RNG from seed=42, draws exactly ONE
  normal variate. Since the RNG state is identical for each fund,
  the normalized draw (before sigma scaling) is identical:
    rng.normal(0, 1) with seed=42 → same value every time

  For two funds in the same block with different volatilities:
    Fund A (vol=0.15): residual = σ_A × Z where Z = fixed_value
    Fund B (vol=0.20): residual = σ_B × Z where Z = same_fixed_value

  The residuals differ only because σ differs, not because of random
  variation. Two funds with IDENTICAL volatility get IDENTICAL shocks.
  This defeats the stated purpose: "so two funds in the same block
  do not realise identical losses" (docstring line 191-194).

Expected invariant: I-Stress-Sign-1 (stress correctness)
Why it is wrong:
  The S5-J dispersion feature was added specifically to differentiate
  fund-level shocks within a block. With identical seeds, funds in the
  same block with similar volatilities get near-identical shocks,
  making the feature no-op. The docstring's own example ("during the
  GFC, two large-cap US equity funds realised -32% and -47%") cannot
  be reproduced with this implementation.
Recommended fix:
  Derive a per-fund seed from the base seed and fund_id:
    import hashlib
    fund_seed = seed + int(hashlib.md5(fund_id.encode()).hexdigest()[:8], 16)
    fund_shock = apply_idiosyncratic_dispersion(
        ..., seed=fund_seed, ...
    )
Minimum test:
  def test_dispersion_produces_different_shocks_per_fund():
      shocks_by_fund = {}
      for fid in ["fund_a", "fund_b", "fund_c"]:
          shock = apply_idiosyncratic_dispersion(
              block_shock=-0.38, fund_volatility=0.15, seed=42,
          )
          shocks_by_fund[fid] = shock
      # All shocks are identical — this test SHOULD fail (proving the bug)
      assert len(set(shocks_by_fund.values())) > 1, "Dispersion produced identical shocks"
Breaking-change risk: Tenant-visible behavior (stress results will change)
Confidence: High
Open questions: None — RNG mechanics are deterministic.
```

---

```
ID: F-S10-06
Title: Construction executor bypasses state_machine.transition() — no audit row
Files/lines: construction_run_executor.py:2094-2099
Math severity: N/A
Institutional severity: High
Type: Audit
Evidence:
  Line 2094-2099:
    portfolio.fund_selection_schema = _jsonb_safe(base_result)
    portfolio.status = "backtesting"
    if portfolio.state in {"draft", "rejected"}:
        portfolio.state = "constructed"
        portfolio.state_changed_by = run.requested_by
        portfolio.state_changed_at = datetime.now(tz=timezone.utc)

  The state_machine.transition() function (state_machine.py:246-359):
  - Takes SELECT FOR UPDATE row lock
  - Validates the edge against TRANSITIONS
  - Creates a PortfolioStateTransition row (audit)
  - Logs via structlog

  The executor does NONE of this. It directly mutates the ORM object.
  There is also NO write_audit_event() call anywhere in the executor
  (confirmed via grep — zero matches).

  The PortfolioStateTransition table docstring (model_portfolio.py:448-451):
  "One row per call to state_machine.transition(). Records the source
  state, target state, actor, optional reason, and optional metadata."

  But the draft→constructed transition — arguably the most important
  transition in the lifecycle — has NO row in this table.

Expected invariant: I-State-1
Why it is wrong:
  Every OTHER state transition goes through state_machine.transition()
  (via the routes/model_portfolios.py dispatcher). But the construction
  transition is handled by the worker, which bypasses the state machine.
  An auditor querying portfolio_state_transitions for the complete
  lifecycle of a portfolio would find a gap: no record of when or by
  whom the portfolio was constructed.
Recommended fix:
  Replace the direct mutation with a call to state_machine.transition():
    from vertical_engines.wealth.model_portfolio.state_machine import transition
    if portfolio.state in {"draft", "rejected"}:
        await transition(
            db,
            portfolio_id=portfolio_id,
            to_state="constructed",
            actor_id=run.requested_by,
            reason=f"Construction run {run.id}",
        )
Minimum test:
  async def test_construction_creates_transition_audit_row():
      """The draft→constructed transition must create a PortfolioStateTransition."""
      run = await execute_construction_run(db, portfolio_id=pid, ...)
      transitions = await db.execute(
          select(PortfolioStateTransition)
          .where(PortfolioStateTransition.portfolio_id == pid)
          .where(PortfolioStateTransition.to_state == "constructed")
      )
      rows = transitions.scalars().all()
      assert len(rows) == 1
      assert rows[0].from_state == "draft"
Breaking-change risk: None (adds audit rows that should already exist)
Confidence: High
Open questions: None.
```

---

```
ID: F-S10-07
Title: NAV staleness check verifies presence only — threshold_days unused
Files/lines: validation_gate.py:163-188
Math severity: N/A
Institutional severity: High
Type: Other
Evidence:
  def _check_no_stale_nav(run_payload, db):
      weights = run_payload.get("weights_proposed") or {}
      instrument_ids = [str(iid) for iid in weights]
      as_of_date = run_payload.get("as_of_date")
      stale_count = 0
      if as_of_date:
          for iid in instrument_ids:
              latest = db.nav_latest_date.get(iid)
              if latest is None:           # <-- only checks presence
                  stale_count += 1
      passed = stale_count == 0

  The check counts instruments where latest is None (missing from dict).
  It NEVER compares dates:
    expected: as_of_date - latest_date > nav_staleness_threshold_days
    actual: latest is None

  The nav_staleness_threshold_days field on ValidationDbContext
  (line 122) defaults to 10 but is NEVER READ by any check function.
  An instrument with NAV data from 30 days ago would pass the check
  as long as it appears in the nav_latest_date dict.

Expected invariant: I-Approval-2 (data quality for construction)
Why it is wrong:
  A portfolio constructed with 30-day-old NAV data has stale covariance
  and CVaR estimates. The check exists to catch this but doesn't
  actually compare dates. The threshold_days parameter is dead code.
  Combined with F-S10-02 (empty context), this check is doubly
  ineffective: the context has no dates AND the check doesn't compare.
Recommended fix:
  from datetime import date, timedelta
  if as_of_date:
      as_of = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
      cutoff = as_of - timedelta(days=db.nav_staleness_threshold_days)
      for iid in instrument_ids:
          latest = db.nav_latest_date.get(iid)
          if latest is None:
              stale_count += 1
          elif date.fromisoformat(latest) < cutoff:
              stale_count += 1
Minimum test:
  def test_stale_nav_detects_old_dates():
      payload = _base_payload()
      db = ValidationDbContext(
          nav_latest_date={
              "11111111-...": "2026-03-01",  # 38 days old
              "22222222-...": "2026-04-07",  # 1 day old
              ...
          },
          nav_staleness_threshold_days=10,
      )
      result = validate_construction(payload, db)
      nav_check = next(c for c in result.checks if c.id == "no_stale_nav")
      assert not nav_check.passed  # instrument with 38-day-old data should fail
Breaking-change risk: Tenant-visible behavior (existing portfolios with
  stale NAV may start failing the check)
Confidence: High
Open questions: None — the threshold_days field is never referenced.
```

---

```
ID: F-S10-08
Title: CVaR annualization in advisor uses sqrt(252) — understates tail risk
Files/lines: construction_advisor.py:349-354
Math severity: Med
Institutional severity: Low
Type: Other
Evidence:
  Line 349-354 (project_cvar_historical):
    daily_cvar = float(-np.mean(sorted_ret[:cutoff]))
    annual_cvar = daily_cvar * np.sqrt(252)
    return float(round(-annual_cvar, 6))

  sqrt(T) scaling is appropriate for standard deviation (volatility)
  under i.i.d. assumptions. For CVaR / Expected Shortfall:
  - Under normality: CVaR_T = μ*T + σ*sqrt(T)*φ(Φ^{-1}(α))/(1-α)
    The sqrt(T) only applies to the σ term, not the full CVaR.
  - Under fat tails: the tail index α controls the scaling exponent,
    which is typically > 0.5 (i.e., CVaR scales faster than sqrt(T))

  Magnitude: for a daily CVaR of 2%, the sqrt(252) approach gives
  annual CVaR = 2% × 15.87 = 31.7%. The linear approach (252 ×
  daily CVaR) gives 504% — clearly wrong in the other direction.
  The truth is between sqrt and linear, depending on distribution.

Expected invariant: I-Stress-Scale-1 (advisory CVaR accuracy)
Why it is wrong:
  The advisor's CVaR projection is used for candidate ranking and MVS
  (minimum viable set) search. Understating annual CVaR means
  candidates appear to have lower risk than reality, potentially
  recommending higher-risk funds. However, the function is explicitly
  labeled as "heuristic" and the output carries
  projected_cvar_is_heuristic=True, limiting the institutional impact.
Recommended fix:
  Use proper T-period CVaR scaling. For the historical simulation
  approach, compute CVaR directly on T-period rolling returns instead
  of annualizing daily CVaR:
    # Compute overlapping 252-day returns
    rolling_annual = np.convolve(port_daily, np.ones(252), 'valid')
    sorted_annual = np.sort(rolling_annual)
    cutoff = max(int(len(sorted_annual) * alpha), 1)
    annual_cvar = float(-np.mean(sorted_annual[:cutoff]))
Minimum test:
  def test_cvar_annualization_uses_rolling_returns():
      # A test that verifies the annualized CVaR is computed from
      # rolling 252-day returns, not from sqrt(252) * daily CVaR
      ...
Breaking-change risk: None (advisory output, labeled heuristic)
Confidence: Medium
Open questions: The heuristic label reduces urgency. Jury should decide
  if the advisor's CVaR accuracy matters for candidate ranking.
```

---

## Checked invariants with no finding

| Invariant | Status | Evidence |
|---|---|---|
| **I-Hard-Soft-1** (hard breach blocks approval) | **VIOLATED** — see F-S10-01 | The live approval path (validate→approve) has no gate check |
| **I-Hard-Soft-2** (soft constraint doesn't block) | OK | validation_gate.py aggregation: `passed = len(blocks) == 0` only counts block-severity failures. Warn failures don't affect `passed`. |
| **I-Stress-Sign-1** (sign convention consistent) | OK | Preset shocks use negative = loss (`-0.38` for GFC). `nav_impact_pct` is the weighted sum (negative). Validation gate check 11 (`_check_stress_within_tolerance`) compares `worst >= _STRESS_NAV_IMPACT_THRESHOLD` where threshold is `-0.40` — consistent sign (both negative, less-negative = better). |
| **I-Block-Map-1** (weights sum to 1.0) | OK (primary path) | `construct_from_optimizer` (portfolio_builder.py:60-86): accumulates total and rounds. Fallback `construct()` (line 159-174): normalizes to exactly 1.0 when `abs(total - 1.0) > 1e-6`. Validation gate check 1 enforces `abs(total - 1.0) <= 1e-4`. |
| **I-Mandate-Scale-1** (fraction vs percentage) | OK | `cvar_limit` in PortfolioCalibration is `Numeric(6,4)` with default `0.05` (fraction). Validation gate `_check_cvar_within_limit` applies `-abs(float(limit))` which handles both conventions. Mandate fit constraints use risk_bucket strings, not numeric thresholds. Block weights are fractions throughout. No mixed conventions found. |
| **I-Audit-Tenant-1** (allow_global=False) | N/A | Neither the executor nor the routes call `write_audit_event` at all. The state machine uses `PortfolioStateTransition` (which has RLS via OrganizationScopedMixin) instead of the generic audit table. The invariant is satisfied by the absence of `write_audit_event` calls (no risk of accidental `allow_global=True`). |
| **I-State-2** (forward-only / explicit reverse) | OK | `TRANSITIONS` (state_machine.py:57-66): `archived → set()` is terminal. Reverse paths (e.g., `constructed → draft`, `approved → draft`) are explicit via `ACTION_REBUILD_DRAFT`. All reverse edges are declared, and `transition()` validates against the adjacency list. No implicit fall-through. |
| **I-Idempotency** (validation gate) | OK | `validate_construction` is a pure function (no side effects, no state mutation). Same `run_payload` + same `db_context` → same `ValidationResult`. Frozen dataclasses throughout. |
| **Concurrent state transitions** | OK | `transition()` (state_machine.py:304-308) uses `SELECT ... FOR UPDATE` row lock. Two concurrent transitions would serialize at the DB level — the second would see the first's committed state and fail with `InvalidStateTransition` if the edge is no longer valid. |
| **Block mapping coverage** (missing block) | OK (fallback path) | `portfolio_builder.construct()` (line 128-135): empty block logs a warning and `continue`s. The block's weight is silently dropped, but the normalization at line 159-174 redistributes to 1.0. The validation gate check 7 would catch the underweight IF ValidationDbContext were populated (see F-S10-02). |
| **Track record paused intervals** | OK | `compute_live_nav` (track_record.py:147-149): missing return data defaults to `0.0` → `nav = previous_nav * 1.0` = flat NAV. Paused intervals produce flat lines, not gaps, which is the correct institutional convention for synthetic NAV during pause. |
| **Mandate fit constraint scaling** | OK | Mandate fit uses categorical comparisons (risk_bucket, ESG boolean, domicile set membership, currency set membership) and integer days for liquidity. No fractional threshold confusion possible. |

---

## Handoff items

| Item | Target session | Description |
|---|---|---|
| CLARABEL cascade output shape | Session 04/05 | `construct_from_optimizer` trusts the optimizer's weight dict without verifying internal constraints (CVaR, block-group sums). The optimizer is Session 04/05 scope. |
| Drift monitor paused portfolio handling | Session 11 | Does the drift monitor skip paused portfolios? If not, it could fire alerts on stale weights. |
| Brinson-Fachler attribution math | Session 12 | `track_record.py` computes scenario returns but no factor/sector attribution — that's the attribution engine's job. |
| Route dispatcher compound transition | Session 09 (integration) | The `_ACTION_TO_TARGET_STATE` mapping is a route concern. F-S10-01 identifies the state machine mismatch; the route fix is Session 09 scope. However, the fix in Option A (add gate check to compute_allowed_actions for "validated" state) is purely in the state machine and does not require route changes. |
| Dead code in `_evaluate_set` | N/A (cleanup) | construction_advisor.py:459-465 computes `all_weights` and `all_returns` that are immediately overwritten at lines 467-477. The expression at line 464 is mathematically wrong (`tw² / total_new_weight`), but since it's dead code, it has zero runtime impact. Low-priority cleanup. |

---

## Top 3 priorities

1. **F-S10-01 (Crit)** — Approval bypass via validate→approve path. This is the highest-urgency finding because it allows a portfolio with ANY number of hard constraint violations to reach "approved" state. The fix is a 3-line change in `compute_allowed_actions`.

2. **F-S10-02 (Crit)** — Empty ValidationDbContext disables 6 of 16 checks. Even if F-S10-01 is fixed (gate check added to validated→approved), the gate itself is running with blind context. The two findings compound: F-S10-01 removes the gate entirely, F-S10-02 makes the gate porous when present.

3. **F-S10-04 (Crit math)** — Stressed CVaR divided by T. This affects IC decision quality: the stressed CVaR field in every construction run is essentially identical to unstressed CVaR, providing no additional risk information during stress scenarios. F-S10-05 (same seed) is also important but lower urgency since dispersion is a refinement on top of the block-level shock.
