# Wave 6 — Session 10 Stage 3 — Remediation PR Prompts

**Status:** READY FOR DISPATCH (12 PR prompts)
**Stage:** 3 (Opus 4.7 orchestration output)
**Date:** 2026-04-29
**Source:** Stage 2 jury verdict ([docs/audits/2026-04-29-wave6-session10-stage2-jury.md](../audits/2026-04-29-wave6-session10-stage2-jury.md))
**Triage outcome:** 14 CONFIRMED (1 DOWNGRADED), 0 REFUTED — all findings ship to remediation

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

Each section below is a self-contained PR remediation prompt. Dispatch sequentially or in parallel to fresh Opus 4.7 (1M) sessions. Do NOT batch unrelated PRs.

**Recommended dispatch order:**

| Sprint | PR | Findings | Severity |
|---|---|---|---|
| **P0 Crit** | Q110 | C-01 + C-02 (state machine bundle) | Crit |
| **P0 Crit** | Q111 | C-03 (CVaR sign flip) | Crit |
| **P0 Crit** | Q112 | C-05 (stressed CVaR / T) | Crit |
| **P0 Crit** | Q113 | C-06 (missing history → 0%) | Crit |
| **P0 Crit** | Q114 | C-07 (empty block dropping) | Crit |
| **P0 Crit** | Q115 | C-11 (state_machine no write_audit_event) | Crit |
| **P1 High** | Q116 | C-04 (empty ValidationDbContext) | High |
| **P1 High** | Q117 | C-09 (fail-open block-severity) | High |
| **P1 High** | Q118 | C-10 (executor bypasses state_machine) | High |
| **P1 High** | Q119 | C-12 (NAV staleness threshold unused) | High |
| **P1 High** | Q120 | C-08 (mandate fit hard/soft) | High |
| **P2/P3** | Q121 | C-13 + C-14 (RNG seed + CVaR sqrt batch) | Med + Low |

12 PRs total. Q110 and Q121 are intentional bundles per coherent technical scope.

---

## PR-Q110 — C-01 + C-02 state machine bundle (Crit)

```text
You are implementing PR-Q110, a narrow remediation for two related Wave 6 Session 10 findings (C-01 + C-02). Both touch state_machine.py with surgical fixes. Bundling because the architecture review covers them together; either fix without the other leaves a known-bad state.

FINDING C-01 — Validation gate bypass via validated→approved path

File/lines: backend/vertical_engines/wealth/model_portfolio/state_machine.py:175-189
Severity: Crit (institutional convention §3.1 — approval bypass of hard validation)

Mechanism: compute_allowed_actions("validated") always exposes ACTION_APPROVE without re-checking ValidationStatus.passed. The route maps that action to "approved" and transition() validates only graph membership, not validation-gate status. A portfolio with validation_gate.passed=False can reach approved in 2 clicks (constructed→validated, then validated→approved).

Fix: Add `validation.passed` check to the "validated" state's allowed_actions:
  elif state == "validated":
      if validation is not None and validation.passed:
          actions.append(ACTION_APPROVE)
      actions.append(ACTION_REBUILD_DRAFT)

FINDING C-02 — TRANSITIONS missing constructed→approved edge

File/lines: backend/vertical_engines/wealth/model_portfolio/state_machine.py:57-66
Severity: Crit (production critical-workflow transition crash)

Mechanism: TRANSITIONS["constructed"] = {"validated", "rejected", "draft"} — does NOT include "approved". When OD-5 override (require_construction_for_approve=False) attempts the constructed→approved transition, transition() raises InvalidStateTransition (state_machine.py:313-315), and the route returns 409. The OD-5 workflow is broken on every such call.

Fix: Add "approved" to TRANSITIONS["constructed"]:
  "constructed": {"validated", "rejected", "draft", "approved"}

CONSTRAINTS
- Both fixes must land together; partial fix leaves the system in a known-bad state.
- Do NOT change other state's allowed actions.
- Do NOT remove ACTION_REBUILD_DRAFT or other validated-state actions.
- Audit every callsite of compute_allowed_actions("validated") to confirm the new check doesn't break existing tests.

REQUIRED TESTS
- test_approve_blocked_when_validation_failed (validated state, validation.passed=False → ACTION_APPROVE not in actions)
- test_approve_allowed_when_validation_passed (validated state, validation.passed=True → ACTION_APPROVE in actions)
- test_od5_override_constructed_to_approved (constructed state with require_construction_for_approve=False → transition succeeds, no InvalidStateTransition)
- test_existing_constructed_to_validated_still_works (regression for existing edge)

ACCEPTANCE
- 4 tests pass
- Existing state machine tests still pass
- Lint clean

PR DESCRIPTION
Title: fix(wealth): PR-Q110 — Wave 6 S10 C-01+C-02 — state machine bundle (Crit)
Body: cite jury verdict; explain the architectural relationship (permissive bypass + restrictive omission both fixed).

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q111 — C-03 CVaR improvement sign flip (Crit)

```text
You are implementing PR-Q111, remediation for Wave 6 S10 C-03.

FINDING — CVaR improvement sign flip — advisor recommends WORST funds

File/lines: backend/vertical_engines/wealth/model_portfolio/construction_advisor.py:403-405 (improvement formula) + 415-416 (sort)
Severity: Crit (institutional convention §3.1 — math error producing wrong recommendation)

Mechanism: project_cvar_historical returns negative-loss CVaR values (e.g., -0.08 = 8% loss). The improvement formula `(current_cvar - projected) / abs(current_cvar)` produces NEGATIVE values when CVaR improves (current=-0.08, projected=-0.06 → result=-0.02) and POSITIVE values when it worsens (projected=-0.10 → result=+0.02). The `sorted(..., reverse=True)` then ranks WORST candidates first.

Fix: Reverse the subtraction order:
  improvement = round((projected - current_cvar) / abs(current_cvar), 4)

This produces positive values when CVaR improves (less-negative projected) and negative when it worsens.

CONSTRAINTS
- Single-line change in the improvement formula.
- Do NOT change the sort direction (reverse=True is correct after the fix).
- Verify all consumers of `cvar_improvement` use it as "higher is better" semantically.

REQUIRED TEST
def test_cvar_improvement_sign():
    # current_cvar = -0.08, projected = -0.06 (better) → improvement positive
    improvement = compute_improvement(current=-0.08, projected=-0.06)
    assert improvement > 0
    # projected = -0.10 (worse) → improvement negative
    improvement2 = compute_improvement(current=-0.08, projected=-0.10)
    assert improvement2 < 0

ACCEPTANCE
- 1 line changed
- 1 test added
- Lint clean

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q112 — C-05 stressed CVaR shift normalization (Crit)

```text
You are implementing PR-Q112, remediation for Wave 6 S10 C-05.

FINDING — Stressed CVaR shift / T renders it negligible

File/lines:
- backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:243-249 (run_stress_scenario_fund_level)
- backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:302-310 (run_stress_scenario)
Severity: Crit (institutional convention §3.1 — stress magnitude wrong by 10x+)

Mechanism: Both functions apply nav_impact (a cumulative scenario return like -0.38 for GFC) as a uniform shift across daily returns:
  shifted = historical_returns + nav_impact / len(historical_returns)
For T=252, this dilutes a 38% shock to -0.0015/day, producing stressed CVaR ≈ unstressed CVaR. The output is meaningless for IC stress assessment.

Fix: Apply the shock as a single extreme observation appended to the return series:
  shock_obs = np.array([nav_impact])
  shifted = np.concatenate([historical_returns, shock_obs])
  cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)

This treats the cumulative scenario shock as one extreme tail event, properly impacting the CVaR_95 calculation.

Alternative (deeper but more correct): convert nav_impact to scenario-horizon-specific daily equivalent based on the documented scenario length (252 days for 1y, 504 for 2y), THEN concatenate. The simple append is acceptable for now.

CONSTRAINTS
- Apply the same fix at both sites (run_stress_scenario AND run_stress_scenario_fund_level).
- Do NOT change nav_impact semantics or scenario presets.
- Do NOT change compute_cvar_from_returns.

REQUIRED TEST
def test_stressed_cvar_materially_different_from_unstressed():
    returns = np.random.normal(0.0004, 0.01, 252)
    base_cvar, _ = compute_cvar_from_returns(returns)
    result = run_stress_scenario(
        {"equity": 1.0}, {"equity": -0.38}, returns, "gfc"
    )
    # Stressed CVaR should be materially worse (at least 10% different)
    assert result.cvar_stressed < base_cvar * 1.10

ACCEPTANCE
- 2 sites patched (both functions)
- 1 test confirms material magnitude change
- Existing stress tests still pass

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q113 — C-06 historical stress missing fund history (Crit)

```text
You are implementing PR-Q113, remediation for Wave 6 S10 C-06.

FINDING — Historical stress imputes 0% return for missing fund history

File/lines: backend/vertical_engines/wealth/model_portfolio/track_record.py:198-203 (lookup build) + 221-230 (replay)
Severity: Crit (institutional convention §3.1 — missing data treated as zero in stress = young funds "GFC immune")

Mechanism: Returns lookup is built from available NAV rows. During scenario replay (e.g., GFC 2008 dates), `returns_lookup.get((fund_id, date), 0.0)` defaults to 0.0% per day for funds that didn't exist at that date. A portfolio holding only post-2010 funds reports near-zero loss for the GFC.

Fix: Track per-day coverage. Drop or degrade scenarios where coverage falls below threshold:

  COVERAGE_THRESHOLD = 0.80  # 80% portfolio weight must have valid data

  for d in scenario_dates:
      day_return = 0.0
      day_coverage = 0.0
      for fid, w in zip(fund_ids, weights, strict=False):
          r = returns_lookup.get((fid, d))
          if r is not None:
              day_return += w * r
              day_coverage += w
      if day_coverage < COVERAGE_THRESHOLD:
          # Mark scenario as degraded — return None or partial flag
          return ScenarioResult(
              max_drawdown=None,
              degraded=True,
              degraded_reason=f"Coverage {day_coverage:.0%} < {COVERAGE_THRESHOLD:.0%} on {d}",
          )
      # Optionally rescale day_return by day_coverage to normalize partial coverage

CONSTRAINTS
- Do NOT silently skip dates with low coverage.
- Surface degraded=True flag to consumers.
- Do NOT introduce new dependencies (numpy/pandas already available).

REQUIRED TEST
def test_historical_stress_handles_missing_funds():
    # Portfolio with 100% in fund incepted 2015; replay 2008 GFC scenario
    result = compute_stress(
        portfolio={"young_fund_2015": 1.0},
        scenario_id="gfc_2008",
        returns_lookup={...},  # fund has zero rows for 2008 dates
    )
    assert result.degraded is True
    assert result.max_drawdown is None or result.degraded_reason is not None

ACCEPTANCE
- Coverage threshold enforced
- Degraded flag surfaced
- 1 test added
- Existing stress tests still pass with full-coverage data

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q114 — C-07 empty block fail-loud (Crit)

```text
You are implementing PR-Q114, remediation for Wave 6 S10 C-07.

FINDING — Silent dropping of empty allocation block breaks strategic targets

File/lines: backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py:127-136 (skip empty) + 159-174 (renormalize)
Severity: Crit (institutional convention §3.1 — strategic asset allocation silently overridden)

Mechanism: When fund-level optimizer can't run, the fallback builder (construct()) iterates target blocks. Empty blocks log a warning and `continue`. Remaining weights are renormalized to 1.0. A 60/40 strategic target with empty fixed-income block becomes 100/0 silently.

Fix: Replace `continue` on empty block with explicit failure:

  if not block_funds:
      logger.error(
          "portfolio_construction_empty_block",
          block_id=block_id,
          target_weight=target_weight,
      )
      raise ValueError(
          f"No approved funds for block {block_id} (target weight {target_weight}). "
          f"Strategic allocation cannot be honored. Add approved funds to "
          f"instruments_org for this block before constructing."
      )

This forces construction to fail loudly. The caller (executor or route) receives the exception and surfaces it to IC for remediation (add approved funds OR adjust strategic target).

CONSTRAINTS
- Do NOT silently fall back to renormalization.
- Do NOT raise on populated blocks (current behavior is correct there).
- Verify route layer handles ValueError → 422 or appropriate user-facing error (not 500).

REQUIRED TEST
def test_construct_raises_on_empty_block():
    targets = {"equity": 0.6, "fixed_income": 0.4}
    funds_by_block = {"equity": [...]}  # fixed_income missing
    with pytest.raises(ValueError, match="No approved funds for block fixed_income"):
        construct(targets, funds_by_block)

def test_construct_with_full_blocks_still_works():
    # Regression — populated blocks must succeed
    ...

ACCEPTANCE
- continue → raise ValueError
- 2 tests
- Route handles the exception gracefully
- Lint clean

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q115 — C-11 state_machine.transition() write_audit_event (Crit)

```text
You are implementing PR-Q115, remediation for Wave 6 S10 C-11.

FINDING — state_machine.transition() bypasses write_audit_event (Q92 invariant)

File/lines: backend/vertical_engines/wealth/model_portfolio/state_machine.py:328-339 (PortfolioStateTransition insert path)
Severity: Crit (institutional convention §3.1 — silent loss of audit trail)

Mechanism: transition() writes a PortfolioStateTransition row but never calls write_audit_event. The Session 10 audit invariant I-State-1 / I-Audit-Tenant-1 explicitly requires write_audit_event on every state change. Q92 created allow_global=False default to enforce tenant scoping. The domain table is useful but does not replace the unified audit feed.

Fix: After inserting PortfolioStateTransition, call write_audit_event with allow_global=False:

  from app.core.db.audit import write_audit_event

  # ... existing PortfolioStateTransition insert ...
  db.add(transition_row)

  # PR-Q115: emit unified audit event in addition to domain-specific
  # state-transition row. Required by Session 10 I-Audit-Tenant-1.
  await write_audit_event(
      db,
      action="model_portfolio.state_transition",
      entity_type="ModelPortfolio",
      entity_id=str(portfolio_id),
      before={"state": from_state},
      after={
          "state": to_state,
          "actor_id": actor_id,
          "reason": reason,
      },
      allow_global=False,  # tenant-scoped
  )

CONSTRAINTS
- Do NOT remove the PortfolioStateTransition insert (still needed for domain queries).
- Use allow_global=False explicitly (Q92 contract).
- Match the action / entity_type naming conventions used in other domains.

REQUIRED TEST
async def test_transition_writes_audit_event(db_session):
    # Mock write_audit_event, verify it's called with correct kwargs
    with patch("vertical_engines.wealth.model_portfolio.state_machine.write_audit_event") as mock:
        await transition(db, portfolio_id=pid, to_state="constructed", actor_id="x")
        mock.assert_called_once()
        kwargs = mock.call_args.kwargs
        assert kwargs["action"] == "model_portfolio.state_transition"
        assert kwargs["entity_id"] == str(pid)
        assert kwargs["allow_global"] is False

async def test_transition_writes_both_domain_and_audit_rows(db_session):
    # End-to-end: assert PortfolioStateTransition AND audit_events row both created
    ...

ACCEPTANCE
- write_audit_event call added
- 2 tests
- Existing transition tests still pass
- Lint clean

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q116 — C-04 ValidationDbContext population (High)

```text
You are implementing PR-Q116, remediation for Wave 6 S10 C-04.

FINDING — Empty ValidationDbContext disables 5 of 16 hard checks

File/lines: backend/app/domains/wealth/workers/construction_run_executor.py:2037-2039
Severity: High (jury downgraded from Crit because as_of_date now present invalidates Opus's NAV subclaim; remaining checks still empty)

Mechanism: Executor calls validate_construction(payload, ValidationDbContext()) with default empty context. Block-max checks iterate empty constraint map (validation_gate.py:369-372), banned-instrument checks see empty set (397-399), approved-universe downgrades to warn (421-428), TAA/IPS checks have no targets (702-707). Five hard checks effectively disabled.

Fix: Populate ValidationDbContext from DB before calling validate_construction:

  from app.domains.wealth.queries import (
      get_org_banned_instruments,
      get_org_approved_universe,
      get_org_block_constraints,
      get_org_taa_ips_targets,
  )

  banned = await get_org_banned_instruments(db, organization_id)
  approved = await get_org_approved_universe(db, organization_id)
  block_constraints = await get_org_block_constraints(db, organization_id)
  taa_targets = await get_org_taa_ips_targets(db, organization_id)
  nav_latest = await get_nav_latest_dates(db, instrument_ids)  # for completeness

  validation_context = ValidationDbContext(
      banned_instrument_ids=banned,
      approved_instrument_ids=approved,
      block_constraints=block_constraints,
      taa_ips_targets=taa_targets,
      nav_latest_date=nav_latest,
      nav_staleness_threshold_days=10,
  )

  validation_result = validate_construction(validation_payload, validation_context)

CONSTRAINTS
- The DB query helpers may not exist yet — create them in app/domains/wealth/queries/ (or appropriate module).
- Do NOT block on missing helpers — write inline SQL if necessary, but mark with TODO for refactor.
- Reuse existing patterns (e.g., how routes load similar data).
- Tenant-scoped: all queries respect RLS via the active session.

REQUIRED TEST
async def test_executor_populates_validation_db_context(db_session, sample_org):
    # Setup: create banned + approved + block constraints in DB
    # Run execute_construction_run
    # Verify validation_result has check 9 (no_banned_instruments) FAILED if banned present
    # Verify check 10 (all_instruments_approved) PASSED if approved set populated

ACCEPTANCE
- ValidationDbContext populated with at least 4 fields (banned, approved, blocks, taa)
- 1 integration test confirms the gate now sees real data
- Existing executor tests still pass
- Lint clean

PR scope: Med (queries + integration). If query helpers don't exist, inline SQL acceptable.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q117 — C-09 fail-closed for block-severity checks (High)

```text
You are implementing PR-Q117, remediation for Wave 6 S10 C-09.

FINDING — Block-severity check exception silently demoted to warn

File/lines: backend/vertical_engines/wealth/model_portfolio/validation_gate.py:769-783 (exception handler) + 786-790 (aggregation)
Severity: High (institutional convention §3.2 — hard checks must fail closed)

Mechanism: validate_construction catches any check exception and constructs ValidationCheck with severity="warn" regardless of the check's intended severity. Block-severity checks (weights_sum_to_one, no_stale_nav, cvar_within_limit, etc.) raised on malformed input become non-blocking warnings. Aggregation only blocks on `severity="block" AND not passed` — exceptions never block.

Fix: Maintain a registry of intended severity per check, preserve it in the exception path:

  # At the top of validation_gate.py, alongside CHECKS:
  _INTENDED_SEVERITY = {
      "weights_sum_to_one": "block",
      "no_stale_nav": "block",
      "cvar_within_limit": "block",
      "min_diversification_count": "block",
      "max_single_fund_weight": "block",
      "all_block_min_weights": "block",
      "all_block_max_weights": "block",
      "no_banned_instruments": "block",
      "all_instruments_approved": "warn",  # warn-severity per existing design
      "stress_within_tolerance": "warn",
      # ... etc.
      "taa_bands_within_ips": "block",
  }

  # In the exception handler:
  except Exception as exc:
      result = ValidationCheck(
          id=_check_id,
          label=_check_id.replace("_", " ").capitalize(),
          severity=_INTENDED_SEVERITY.get(_check_id, "block"),  # default to block
          passed=False,
          value=None,
          threshold=None,
          explanation=f"Check raised: {type(exc).__name__}: {exc}",
      )

CONSTRAINTS
- The default severity for unknown check IDs MUST be "block" (fail-closed default).
- Do NOT change individual check function bodies.
- The registry must list ALL 16 checks with their canonical severity.
- Update the docstring (validation_gate.py:1-46) to clarify fail-closed behavior on exceptions.

REQUIRED TEST
def test_block_check_exception_stays_block_severity():
    # Inject malformed payload that causes weights_sum_to_one to raise
    payload = {"weights_proposed": {"a": "not_a_number"}}
    result = validate_construction(payload, ValidationDbContext())
    wst = next(c for c in result.checks if c.id == "weights_sum_to_one")
    assert wst.severity == "block"
    assert not result.passed

def test_warn_check_exception_stays_warn_severity():
    # Inject malformed payload causing a warn-severity check to raise
    ...
    assert check.severity == "warn"
    assert result.passed  # warn doesn't block

ACCEPTANCE
- _INTENDED_SEVERITY registry added with all 16 checks
- 2 tests confirm severity preservation
- Existing tests still pass (some may need adjustment if they relied on the buggy behavior)
- Lint clean

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q118 — C-10 executor uses state_machine.transition() (High)

```text
You are implementing PR-Q118, remediation for Wave 6 S10 C-10.

FINDING — Construction executor mutates portfolio.state directly, bypasses state_machine

File/lines: backend/app/domains/wealth/workers/construction_run_executor.py:2093-2099
Severity: High (institutional convention §3.2 — incomplete lifecycle audit trail)

Mechanism: Executor materializes accepted construction results and directly assigns:
  portfolio.state = "constructed"
  portfolio.state_changed_by = run.requested_by
  portfolio.state_changed_at = datetime.now(...)

This bypasses state_machine.transition() which row-locks, validates the graph edge, AND inserts a PortfolioStateTransition row (and after PR-Q115, also writes write_audit_event). The draft/rejected→constructed transition has no audit row.

Fix: Replace the direct mutation with a call to state_machine.transition():

  from vertical_engines.wealth.model_portfolio.state_machine import transition

  if portfolio.state in {"draft", "rejected"}:
      await transition(
          db,
          portfolio_id=portfolio.id,
          to_state="constructed",
          actor_id=run.requested_by,
          reason=f"Construction run {run.id}",
      )

CONSTRAINTS
- This fix DEPENDS on PR-Q115 (write_audit_event call inside transition()). Q115 should land first OR this PR should be stacked on Q115.
- Do NOT skip the state check (`portfolio.state in {"draft", "rejected"}`); transition() will raise InvalidStateTransition for other source states, which is correct.
- After this fix, every construction run produces 1 PortfolioStateTransition + 1 audit_events row.

REQUIRED TEST
async def test_construction_creates_transition_audit_row(db_session):
    run = await execute_construction_run(db, portfolio_id=pid, ...)
    transitions = (await db.execute(
        select(PortfolioStateTransition)
        .where(PortfolioStateTransition.portfolio_id == pid)
        .where(PortfolioStateTransition.to_state == "constructed")
    )).scalars().all()
    assert len(transitions) == 1
    assert transitions[0].from_state == "draft"

async def test_construction_creates_audit_event_row(db_session):
    # After Q115 lands, executor → transition() → write_audit_event
    # Verify audit_events table has the model_portfolio.state_transition entry
    ...

ACCEPTANCE
- Direct portfolio.state mutation replaced with transition() call
- 2 tests
- Existing executor tests still pass
- Stack-aware: if Q115 not yet merged, mark PR with "Depends on PR-Q115"

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q119 — C-12 NAV staleness threshold enforcement (High)

```text
You are implementing PR-Q119, remediation for Wave 6 S10 C-12.

FINDING — NAV staleness check verifies presence only — threshold_days unused

File/lines: backend/vertical_engines/wealth/model_portfolio/validation_gate.py:163-188 (_check_no_stale_nav)
Severity: High (institutional convention §3.2 — data quality gate ineffective)

Mechanism: ValidationDbContext defines `nav_staleness_threshold_days: int = 10`. _check_no_stale_nav increments stale_count only when latest is None (missing entirely from dict) — never compares latest_date to as_of_date or to the threshold. A fund with 30-day-old NAV passes the check.

Fix: Compare latest_date against as_of_date - threshold_days:

  from datetime import date, timedelta

  def _check_no_stale_nav(run_payload, db_context):
      weights = run_payload.get("weights_proposed") or {}
      instrument_ids = [str(iid) for iid in weights]
      as_of_date_raw = run_payload.get("as_of_date")
      if not as_of_date_raw:
          # No as_of_date → can't evaluate staleness; pass with explanation
          return ValidationCheck(
              id="no_stale_nav",
              passed=True,
              severity="block",
              explanation="as_of_date missing from payload; staleness check skipped",
              ...
          )

      as_of = (
          date.fromisoformat(as_of_date_raw)
          if isinstance(as_of_date_raw, str)
          else as_of_date_raw
      )
      cutoff = as_of - timedelta(days=db_context.nav_staleness_threshold_days)

      stale_count = 0
      stale_instruments: list[str] = []
      for iid in instrument_ids:
          latest = db_context.nav_latest_date.get(iid)
          if latest is None:
              stale_count += 1
              stale_instruments.append(iid)
              continue
          latest_date = (
              date.fromisoformat(latest) if isinstance(latest, str) else latest
          )
          if latest_date < cutoff:
              stale_count += 1
              stale_instruments.append(iid)

      passed = stale_count == 0
      return ValidationCheck(
          id="no_stale_nav",
          passed=passed,
          severity="block",
          value=stale_count,
          threshold=db_context.nav_staleness_threshold_days,
          explanation=(
              f"{stale_count} instruments with NAV older than "
              f"{db_context.nav_staleness_threshold_days}d as of {as_of}"
              if not passed
              else "All NAV data within staleness threshold"
          ),
      )

CONSTRAINTS
- Date arithmetic must handle both str and date instances (latest can be either).
- Default threshold_days=10 already in ValidationDbContext.
- Do NOT change the check ID or severity semantics.
- The check still passes when as_of_date is absent (graceful degradation).

REQUIRED TEST
def test_stale_nav_detects_old_dates():
    payload = _base_payload()
    payload["as_of_date"] = "2026-04-09"
    db = ValidationDbContext(
        nav_latest_date={
            "fund_a": "2026-03-01",  # 39 days old → stale
            "fund_b": "2026-04-07",  # 2 days old → ok
        },
        nav_staleness_threshold_days=10,
    )
    result = validate_construction(payload, db)
    nav_check = next(c for c in result.checks if c.id == "no_stale_nav")
    assert not nav_check.passed
    assert "fund_a" in nav_check.explanation or nav_check.value == 1

def test_stale_nav_passes_when_all_recent():
    ...
    assert nav_check.passed

ACCEPTANCE
- threshold_days actually used
- 2 tests
- Existing tests still pass
- Lint clean

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q120 — C-08 mandate fit hard/soft severity field (High)

```text
You are implementing PR-Q120, remediation for Wave 6 S10 C-08.

FINDING — Mandate fit treats all client preferences as hard constraints

File/lines:
- backend/vertical_engines/wealth/mandate_fit/models.py:24-31 (ConstraintResult)
- backend/vertical_engines/wealth/mandate_fit/service.py:62-80 (evaluate_instrument)
- backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py:84+ (evaluation calls)
Severity: High (institutional convention §3.2 — hard/soft discipline blurred)

Mechanism: ConstraintResult has only constraint, passed, reason — no severity channel. evaluate_instrument aggregates every failed constraint into `disqualifying` and sets `eligible = len(disqualifying) == 0`. A soft preference miss (e.g., ESG mismatch) disqualifies an otherwise compliant instrument.

Fix: Add severity field, separate hard from soft in aggregation:

  # mandate_fit/models.py
  from typing import Literal

  @dataclass(frozen=True)
  class ConstraintResult:
      constraint: str
      passed: bool
      reason: str | None = None
      severity: Literal["hard", "soft"] = "hard"  # default hard for backwards compat

  # mandate_fit/service.py
  results = constraint_evaluator.evaluate(instrument, mandate)

  hard_failures = [r for r in results if not r.passed and r.severity == "hard"]
  soft_failures = [r for r in results if not r.passed and r.severity == "soft"]

  eligible = len(hard_failures) == 0  # soft failures don't disqualify
  disqualifying_reasons = [r.reason for r in hard_failures]
  warnings = [r.reason for r in soft_failures]
  suitability_score = compute_suitability_score(results)  # already exists; ensure it accounts for soft

  return MandateFitResult(
      eligible=eligible,
      disqualifying_reasons=disqualifying_reasons,
      warnings=warnings,  # NEW field — surface soft misses without blocking
      suitability_score=suitability_score,
  )

  # mandate_fit/constraint_evaluator.py — tag each constraint at construction:
  # Hard: regulatory restrictions, liquidity caps, leverage limits
  # Soft: ESG preferences, currency tilts, factor exposures
  return ConstraintResult(
      constraint="esg_score_minimum",
      passed=instrument.esg_score >= mandate.esg_min,
      reason=f"ESG {instrument.esg_score} < {mandate.esg_min}" if not passed else None,
      severity="soft",  # explicit
  )

  # And for hard:
  return ConstraintResult(
      constraint="domicile_restriction",
      passed=instrument.domicile in mandate.allowed_domiciles,
      reason="..." if not passed else None,
      severity="hard",
  )

CONSTRAINTS
- ConstraintResult.severity must default to "hard" (institutional convention: presumption is hard unless explicitly tagged soft).
- MandateFitResult must add a "warnings" field for soft misses — IC needs visibility.
- Audit every existing constraint in constraint_evaluator.py and tag each as hard or soft. Document the rationale in code comments.
- Update suitability_score logic if necessary so that a hard PASS always scores higher than soft PASS.

REQUIRED TESTS
def test_soft_preference_does_not_disqualify():
    instrument = Instrument(esg_score=4, ...)
    mandate = Mandate(esg_min=5, ...)
    result = service.evaluate_instrument(instrument, mandate)
    assert result.eligible is True  # soft miss — eligible
    assert "esg" in result.warnings[0].lower()
    assert result.suitability_score < 1.0

def test_hard_constraint_disqualifies():
    instrument = Instrument(domicile="restricted", ...)
    mandate = Mandate(allowed_domiciles=["US", "EU"], ...)
    result = service.evaluate_instrument(instrument, mandate)
    assert result.eligible is False
    assert "domicile" in result.disqualifying_reasons[0].lower()

ACCEPTANCE
- ConstraintResult.severity field added with "hard" default
- MandateFitResult.warnings field added
- All existing constraints tagged hard/soft explicitly
- 2+ tests added
- Existing tests adjusted if they relied on the old "all-failures-disqualify" behavior
- Lint clean

PR scope: Med (model change + evaluation refactor). Tier 1 institutional contract change.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q121 — C-13 + C-14 batch (Med + Low)

```text
You are implementing PR-Q121, a batched remediation for two small Wave 6 S10 findings.

FINDING C-13 — Same RNG seed for all funds defeats idiosyncratic dispersion (Med)

File/lines: backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:222-232 + 119-121
Mechanism: run_stress_scenario_fund_level passes the same `seed` (e.g., 42) into apply_idiosyncratic_dispersion for every fund. Each call creates a fresh RNG from that seed and draws ONE residual — identical across funds.

Fix: Derive a per-fund seed from the base seed and fund_id:
  import hashlib
  fund_seed = (seed + int(hashlib.md5(fund_id.encode()).hexdigest()[:8], 16)) & 0xFFFFFFFF
  fund_shock = apply_idiosyncratic_dispersion(
      block_shock=block_shock,
      fund_volatility=fund_volatilities.get(fund_id),
      fund_beta=fund_betas.get(fund_id),
      seed=fund_seed,
  )

Test:
def test_dispersion_produces_different_shocks_per_fund():
    shocks = {}
    for fid in ["fund_a", "fund_b", "fund_c"]:
        # ... call apply_idiosyncratic_dispersion with derived seed ...
        shocks[fid] = result
    assert len(set(shocks.values())) == 3  # all distinct

FINDING C-14 — CVaR annualization uses sqrt(252) — heuristic (Low)

File/lines: backend/vertical_engines/wealth/model_portfolio/construction_advisor.py:349-354
Mechanism: project_cvar_historical computes daily CVaR and multiplies by sqrt(252). sqrt(T) scaling is appropriate for volatility, not CVaR. The output is labeled `projected_cvar_is_heuristic=True` so consumers are warned, but the value is still misleading.

Fix: Use rolling-sum approach when sufficient data:
  if len(daily_returns) >= 252:
      # Compute annual CVaR from rolling 252-day cumulative returns
      annual_returns = np.convolve(daily_returns, np.ones(252), mode="valid")
      sorted_annual = np.sort(annual_returns)
      cutoff = max(int(len(sorted_annual) * alpha), 1)
      annual_cvar = float(-np.mean(sorted_annual[:cutoff]))
      return float(round(-annual_cvar, 6))
  else:
      # Fallback: existing sqrt(252) heuristic with explicit flag
      daily_cvar = float(-np.mean(sorted_ret[:cutoff]))
      annual_cvar = daily_cvar * np.sqrt(252)
      return float(round(-annual_cvar, 6))

Test:
def test_cvar_uses_rolling_when_sufficient_data():
    # Verify rolling path for 500 days; sqrt fallback for 100 days
    ...

CONSTRAINTS (both)
- Each fix in a separate commit within this PR (2 commits).
- Each fix has its own test.
- If either fix exceeds ~30 LoC, split off into PR-Q121a/b immediately.

ACCEPTANCE
- 2 fixes applied
- 2 tests pass
- Lint clean
- Each commit is standalone-revertable

PR DESCRIPTION
Title: chore(wealth): PR-Q121 — Wave 6 S10 batch (RNG seed dispersion + CVaR sqrt heuristic)
Body: cite both findings; explain the batch rationale (small scope, P2/P3 cleanup wave).

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## Stage 4 reminder

Codex Auto Review will trigger on each PR. P1 catches → standalone hotfix immediately. P2 catches → bundle into adjacent PR or terminus cleanup. Memory: `feedback_codex_review_integration.md`.

For PRs touching the validation gate, state machine, or stress scenarios, expect Codex to flag any remaining edge cases (lock semantics, idempotency, RLS context propagation). The Q104→Q109 chain on Session 09 was the canonical example of Codex catching a fix-of-fix-of-fix loop.
