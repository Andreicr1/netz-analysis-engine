# Wave 6 — Session 10 Stage 2 Jury Output

**Model:** GPT-5.5
**Date:** 2026-04-29
**Findings adjudicated:** 14

## Summary table

| Canonical | Title (truncated) | Verdict | Final severity | Notes |
|---|---|---|---|---|
| C-01 | Validation gate bypass via validated→approved | CONFIRMED | Crit | Live approval path has no validation gate check. |
| C-02 | TRANSITIONS missing constructed→approved | CONFIRMED | Crit | OD-5/approved-from-constructed action is exposed but graph rejects it. |
| C-03 | CVaR improvement sign flip | CONFIRMED | Crit | Negative-loss convention is ranked backward. |
| C-04 | Empty ValidationDbContext disables checks | CONFIRMED-DOWNGRADED | High | Empty DB context is real; NAV subclaim is stale because `as_of_date` is now present. |
| C-05 | Stressed CVaR shift divided by T | CONFIRMED | Crit | Scenario magnitude is diluted by arbitrary history length. |
| C-06 | Missing stress history imputed as 0% | CONFIRMED | Crit | Young funds become stress-immune cash. |
| C-07 | Empty block dropped and weights renormalized | CONFIRMED | Crit | Strategic allocation can be silently overridden. |
| C-08 | Mandate fit hard/soft fusion | CONFIRMED | High | No severity channel; any failed constraint makes the instrument ineligible. |
| C-09 | Block check exception fail-open | CONFIRMED | High | Intentional fail-soft conflicts with hard-constraint convention. |
| C-10 | Executor bypasses state_machine.transition | CONFIRMED | High | Draft/rejected→constructed has no transition audit row. |
| C-11 | State machine bypasses write_audit_event | CONFIRMED | Crit | Domain transition row is not a substitute for the unified audit feed. |
| C-12 | NAV staleness threshold unused | CONFIRMED | High | Check tests presence, not staleness age. |
| C-13 | Same RNG seed for all funds | CONFIRMED | Med | Idiosyncratic dispersion collapses for equal-vol funds. |
| C-14 | Heuristic CVaR sqrt annualization | CONFIRMED | Low | Heuristic flag is present; no hard-gate consumer found. |

## Per-finding adjudication

### C-01 — Validation gate bypass via validated→approved (no gate check)

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** `TRANSITIONS` permits `constructed -> validated` and `validated -> approved` at `backend/vertical_engines/wealth/model_portfolio/state_machine.py:57-60`. `compute_allowed_actions` always exposes `validate` from `constructed` at `state_machine.py:175-177`, while the `validated` branch always exposes `approve` at `state_machine.py:186-189` without rechecking `ValidationStatus.passed`. The route maps those actions to `validated` and `approved` at `backend/app/domains/wealth/routes/model_portfolios.py:403-405`, then calls `transition()` at `model_portfolios.py:537-545`; `transition()` validates only graph membership at `state_machine.py:313-315`, not validation-gate status. This is an approval bypass of hard validation, which is Always Crit by the institutional convention. C-01 and C-02 are related state-machine defects but require different fixes: C-01 needs a gate check on the `validated` action path, while C-02 needs a graph edge.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-02 — TRANSITIONS missing constructed→approved edge breaks OD-5 override

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** The graph omits `approved` from `TRANSITIONS["constructed"]` at `backend/vertical_engines/wealth/model_portfolio/state_machine.py:57-60`. The same state exposes `ACTION_APPROVE` when validation passed or `require_construction_for_approve` is false at `state_machine.py:178-182`, and the route maps that action to `"approved"` at `backend/app/domains/wealth/routes/model_portfolios.py:403-405`. When invoked, `transition()` rejects the missing edge at `state_machine.py:313-315`, and the route returns a 409 at `model_portfolios.py:546-552`. This breaks the OD-5 approval/override workflow on every such call, matching the Crit convention for a production critical-workflow transition crash. Fixing C-01 alone would not add this edge, so C-02 remains a separate confirmed defect.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-03 — CVaR improvement sign flip — advisor recommends WORST funds

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** `project_cvar_historical` returns negative CVaR values under the codebase's negative-loss convention at `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py:349-354`. Candidate improvement is computed as `(current_cvar - projected) / abs(current_cvar)` at `construction_advisor.py:403-405`, so improving from `-0.08` to `-0.06` produces a negative score while worsening to `-0.10` produces a positive score. Candidates are then sorted descending by that value at `construction_advisor.py:415-416`. This is a math sign error that inverts recommendations, which is Always Crit under the institutional convention.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-04 — Empty ValidationDbContext disables 6 of 16 checks

**Verdict:** CONFIRMED-DOWNGRADED
**Final severity:** High
**Reasoning:** The executor still calls `validate_construction(validation_payload, ValidationDbContext())` at `backend/app/domains/wealth/workers/construction_run_executor.py:2037-2039`, and `ValidationDbContext` defaults all DB-backed guardrail inputs to empty at `backend/vertical_engines/wealth/model_portfolio/validation_gate.py:117-122`. That emptiness makes block max checks iterate an empty constraint map at `validation_gate.py:369-372`, banned-instrument checks see an empty ban set at `validation_gate.py:397-399`, approved-universe checks downgrade to a warning pass at `validation_gate.py:421-428`, and TAA/IPS checks depend on absent context at `validation_gate.py:702-707`. However, Opus's NAV-specific evidence is stale: the current payload includes `"as_of_date"` at `construction_run_executor.py:2025-2027`, and `_check_no_stale_nav` increments missing NAV rows when `as_of_date` is present at `validation_gate.py:171-176`. The bug is therefore a validation gate running blind for several hard checks, but not the full "6 of 16 all pass" Crit claim as currently stated; institutional convention makes this at least High.
**Override of Stage 1?** Yes. Downgraded from Crit to High because one cited bypass mechanism is no longer true in current code.
**Test still required?** Yes.
**Confidence:** High

### C-05 — Stressed CVaR shift / T renders it negligible

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** Fund-level stress CVaR shifts daily history by `nav_impact / len(historical_returns)` at `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:243-249`. Block-level stress repeats the same operation at `stress_scenarios.py:302-310`. Since preset scenario shocks are total-return shocks, as documented at `stress_scenarios.py:126-128`, dividing by an arbitrary return-history length dilutes a GFC-scale loss into a tiny daily mean shift. This makes stressed CVaR magnitude wrong by much more than 10x for normal daily histories, and it feeds IC-facing stress output, supporting the Stage 1 Crit severity.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-06 — Historical stress imputes 0% for missing fund history

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** `compute_stress` builds a returns lookup from available NAV rows at `backend/vertical_engines/wealth/model_portfolio/track_record.py:198-203`. During scenario replay it uses `returns_lookup.get((fid, d), 0.0)` at `track_record.py:223-227`, so a missing fund/date observation contributes exactly 0% return for that day. There is no per-day coverage threshold, degraded flag, or proxy fallback before portfolio returns are accumulated at `track_record.py:221-230`. The institutional convention explicitly classifies missing data treated as zero in stress scenarios as Always Crit.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-07 — Silent dropping of empty allocation block breaks strategic targets

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** The fallback builder states it is used when the fund-level optimizer cannot run at `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py:96-99`, so it remains a production construction path. For each target block, missing funds produce only a warning and `continue` at `portfolio_builder.py:127-136`. Remaining fund weights are then normalized back to 1.0 at `portfolio_builder.py:159-174`. A 60/40 target can therefore become 100/0 if the fixed-income block is empty, which is a silent strategic asset allocation override and Always Crit under the institutional convention.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-08 — Mandate fit treats all client preferences as hard constraints

**Verdict:** CONFIRMED
**Final severity:** High
**Reasoning:** `ConstraintResult` has only `constraint`, `passed`, and `reason` at `backend/vertical_engines/wealth/mandate_fit/models.py:24-31`; it has no hard/soft severity channel. `MandateFitService.evaluate_instrument` aggregates every failed constraint into `disqualifying` and sets `eligible = len(disqualifying) == 0` at `backend/vertical_engines/wealth/mandate_fit/service.py:62-80`. The evaluator separately computes a partial suitability score at `backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py:184-193`, but that score cannot keep a soft miss eligible once any `passed=False` exists. This confirms hard/soft discipline is blurred, which is at least High; I do not escalate to Crit because the current model names several inputs as restrictions or requirements and Stage 1 did not show a concrete final client approval decision being inverted.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** Medium

### C-09 — Block-severity check exception silently demoted to warn

**Verdict:** CONFIRMED
**Final severity:** High
**Reasoning:** `validate_construction` catches any check exception and constructs a `ValidationCheck` with `severity="warn"` at `backend/vertical_engines/wealth/model_portfolio/validation_gate.py:769-783`. Aggregation only blocks on failed checks whose severity remains `"block"` at `validation_gate.py:786-790`, so an exception inside a hard block check becomes non-blocking. The code comment at `validation_gate.py:772-774` frames this as intentional fail-soft behavior, but institutional convention §3.2 requires hard-constraint checks to fail closed. I found no upstream guard that makes malformed block-check inputs impossible; the executor assembles raw JSON-like payloads and passes them into the gate at `backend/app/domains/wealth/workers/construction_run_executor.py:2025-2039`.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-10 — Construction executor mutates portfolio.state directly, bypasses state_machine.transition()

**Verdict:** CONFIRMED
**Final severity:** High
**Reasoning:** The executor materializes accepted construction results and directly assigns `portfolio.state = "constructed"` at `backend/app/domains/wealth/workers/construction_run_executor.py:2093-2099`. The canonical state-machine transition function row-locks the portfolio at `backend/vertical_engines/wealth/model_portfolio/state_machine.py:303-309`, validates the graph edge at `state_machine.py:313-315`, and inserts a `PortfolioStateTransition` row at `state_machine.py:328-339`. The direct executor mutation does none of those things, so the draft/rejected→constructed lifecycle transition is missing from the domain transition audit table. This matches the convention for an incomplete lifecycle audit trail, which is at least High.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-11 — state_machine.transition() bypasses write_audit_event

**Verdict:** CONFIRMED
**Final severity:** Crit
**Reasoning:** `transition()` inserts `PortfolioStateTransition` at `backend/vertical_engines/wealth/model_portfolio/state_machine.py:328-339`, but it never calls `write_audit_event`. The domain table is real and RLS-scoped, as its model documents at `backend/app/domains/wealth/models/model_portfolio.py:447-457`, but CLAUDE.md defines immutable entity-level audit logging through `write_audit_event()` and `AuditEvent` at `CLAUDE.md:387-389`. The Session 10 audit protocol explicitly required `write_audit_event` on every state change at `docs/prompts/2026-04-29-session-10-model-portfolio-mandate-fit-stage1-dispatch.md:65` and made it invariant I-State-1/I-Audit-Tenant-1 at `docs/prompts/2026-04-29-session-10-model-portfolio-mandate-fit-stage1-dispatch.md:181-190`. Q92's `allow_global=False` guard is implemented in `backend/app/core/db/audit.py:38-53` and enforced at `audit.py:75-80`; that controls how audit events are scoped when written, not whether model-portfolio state mutations may skip the unified audit feed. I therefore reject Opus's "domain table replaces audit_events" interpretation for this institutional audit.
**Override of Stage 1?** Yes. Gemini's finding is confirmed over Opus's checked-invariant note.
**Test still required?** Yes.
**Confidence:** High

### C-12 — NAV staleness check verifies presence only — threshold_days unused

**Verdict:** CONFIRMED
**Final severity:** High
**Reasoning:** `ValidationDbContext` defines `nav_staleness_threshold_days` at `backend/vertical_engines/wealth/model_portfolio/validation_gate.py:117-122`. `_check_no_stale_nav` only checks whether `latest` is `None` when `as_of_date` is present at `validation_gate.py:169-176`. It never parses `latest`, compares it to `as_of_date`, or uses the threshold except in the explanation string at `validation_gate.py:184-187`. This is a confirmed data-quality gate defect with institutional High severity.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-13 — Same RNG seed for all funds defeats idiosyncratic dispersion

**Verdict:** CONFIRMED
**Final severity:** Med
**Reasoning:** `run_stress_scenario_fund_level` passes the same `seed` into `apply_idiosyncratic_dispersion` for every fund at `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py:222-232`. The dispersion helper creates a fresh RNG from that seed on each call at `stress_scenarios.py:119-121`, then draws one residual. Equal-volatility funds in the same block therefore receive identical residuals, directly contradicting the docstring goal of manager-level differentiation at `stress_scenarios.py:89-94`. Institutional convention puts broken idiosyncratic dispersion at least Med, and no stronger direct approval or risk-limit flip is shown.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** High

### C-14 — CVaR annualization uses sqrt(252) — heuristic but understates tail risk

**Verdict:** CONFIRMED
**Final severity:** Low
**Reasoning:** `project_cvar_historical` computes daily historical CVaR and annualizes it with `np.sqrt(252)` at `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py:346-354`. That is a volatility-style scaling heuristic rather than a proper horizon CVaR calculation. The top-level advice object explicitly carries `projected_cvar_is_heuristic=True` at `construction_advisor.py:780-789`, and I found no evidence in the canonical claim that this value is consumed as a hard approval gate. Per the institutional convention, explicitly labeled advisory heuristics are at most Low.
**Override of Stage 1?** No.
**Test still required?** Yes.
**Confidence:** Medium

## Cross-cutting observations

The two state-machine findings are architecturally related but not duplicative. C-01 is a permissive gate-bypass on the `validated -> approved` path; C-02 is a restrictive graph omission on the `constructed -> approved` action path. Either fix can land without fixing the other.

The validation layer has both missing context and fail-open semantics. C-04 means several DB-backed checks do not have the data needed to decide; C-09 means exceptions inside hard checks are intentionally converted into warnings. Those should be remediated separately because one is a context-population defect and the other is an aggregation/severity contract defect.

The audit findings are layered. C-10 says the executor bypasses the domain state machine entirely; C-11 says even the domain state machine does not emit the unified `audit_events` record required by the Session 10/Q92 audit invariant. `PortfolioStateTransition` remains useful as a domain transition ledger, but it is not enough for the tenant-wide immutable audit feed.

## Appendix — unsolicited hypotheses

None.
