# Wave 6 — Session 09 Stage 2 Jury Output

**Model:** GPT-5.5
**Date:** 2026-04-28
**Findings adjudicated:** 15

## Summary table

| Canonical | Title (truncated) | Verdict | Final severity | Notes |
|---|---|---|---|---|
| C-01 | universe_sync omits is_active | CONFIRMED | Crit | PR #391 only one-time-reactivates UCITS; upsert race remains. |
| C-02 | trigger_screening current rows | CONFIRMED | Crit | Core investment-team workflow; violates documented retry/idempotency contract. |
| C-03 | uuid.UUID(org_id) crashes | CONFIRMED | Crit | PR #393 only fixes `universe.py:689`; other reachable sites remain. |
| C-04 | regime_fit dead lock ID | CONFIRMED | High | `LOCK_ID` is defined but never acquired. |
| C-05 | drift_check no RLS/org scope | CONFIRMED-ESCALATED | Crit | Multi-tenant RLS bypass risk. |
| C-06 | drift_check lock leak | CONFIRMED-DOWNGRADED | High | Bug exists; lock leak is at least High, not automatically Crit here. |
| C-07 | approve_dd_report current approval | CONFIRMED | High | Gemini missed `UniverseApproval` insert path. |
| C-08 | apply_rebalance no role gate | CONFIRMED-ESCALATED | Crit | Privilege escalation on portfolio mutation. |
| C-09 | audit NULL organization_id | REFUTED | N/A | Already fixed in in-flight PR #392. |
| C-10 | benchmark_ingest bypasses gate | CONFIRMED | Med | Manual retry loop bypasses ExternalProviderGate. |
| C-11 | approve/reject split audit tx | CONFIRMED | Med | State mutation and audit commit in separate sessions. |
| C-12 | catalog ignores unknown params | CONFIRMED | Med | FastAPI route uses loose query params. |
| C-13 | DD trigger role gap | CONFIRMED-ESCALATED | High | Unbounded LLM spend/record creation by lower-privilege users. |
| C-14 | strategy_reclassification ESMA column | CONFIRMED | Med | Post-Q11B migrations rename `isin` to `legacy_isin_misnamed`. |
| C-15 | org_id annotation lie | CONFIRMED | Low | Footgun only; no broad current runtime crash. |

## Per-finding adjudication

### C-01 — universe_sync ON CONFLICT omits is_active

**Verdict:** CONFIRMED  
**Final severity:** Crit  
**Reasoning:** The five upserts at `backend/app/domains/wealth/workers/universe_sync.py:219-222`, `296-299`, `392-395`, `465-468`, and `539-543` update names/attributes/timestamps but never restore `is_active`. The later deactivation step sets `is_active=false` for instruments without NAV at `universe_sync.py:561-569`, while the docstring at `557-559` explicitly promises reactivation on the next upsert. PR #391 is only a partial one-time UCITS recovery; it does not fix the recurring ON CONFLICT behavior. This is permanent catalog-state corruption until manual data repair, so Crit is appropriate.  
**Override of Stage 1?** No; scope noted as reduced by PR #391 only.  
**Test still required?** Yes.  
**Confidence:** High

### C-02 — trigger_screening inserts is_current=True without clearing prior rows

**Verdict:** CONFIRMED  
**Final severity:** Crit  
**Reasoning:** `trigger_screening` is the on-demand screening route at `backend/app/domains/wealth/routes/screener.py:573-585`, gated to investment-team users, not administrator-only. It locks current rows at `screener.py:809-818` but does not set them `is_current=False` before inserting new `is_current=True` rows at `822-833` and committing at `837`. The partial unique index `uq_screening_results_current` is defined on `(organization_id, instrument_id) WHERE is_current = true` in `backend/app/core/db/migrations/versions/0012_instruments_universe_additive.py:208-215`. Because the stability guardrail P5 says mutations must tolerate retry, and this is the core screener workflow rather than a manual admin-only operation, the Opus Crit rating wins the tie-break.  
**Override of Stage 1?** No; Gemini’s High is escalated to Crit by workflow context.  
**Test still required?** Yes.  
**Confidence:** High

### C-03 — uuid.UUID(org_id) crashes at sites where org_id is already UUID

**Verdict:** CONFIRMED  
**Final severity:** Crit  
**Reasoning:** `get_org_id` returns `uuid.UUID | None` at `backend/app/core/tenancy/middleware.py:38-40`. Current reachable casts include `backend/app/domains/wealth/routes/instruments.py:209-229` and `backend/app/domains/wealth/routes/content.py:400-404` plus the failure path at `content.py:440-444`; these call `uuid.UUID(org_id)` on an object that is already a UUID. `backend/app/domains/wealth/routes/universe.py:687-690` is the PR #393-covered site, but the other sites remain in `main`. The builder worker calls may receive stringified IDs depending on caller path, but the route-level and background content sites are enough to confirm production crash impact.  
**Override of Stage 1?** No; scope reduced because PR #393 covers only `universe.py:689`.  
**Test still required?** Yes.  
**Confidence:** High

### C-04 — regime_fit defines LOCK_ID=900_026 but never acquires it

**Verdict:** CONFIRMED  
**Final severity:** High  
**Reasoning:** `backend/app/domains/wealth/workers/regime_fit.py:43` defines `LOCK_ID = 900_026`, but `run_regime_fit` at `267-317` opens sessions and performs fetch, fit, persist, and snapshot update with no `pg_try_advisory_lock` or `pg_advisory_unlock`. The finding’s mechanism is simple dead locking discipline rather than a speculative library behavior, and the code read confirms it. High is appropriate for a worker race that can concurrently write derived regime state.  
**Override of Stage 1?** No.  
**Test still required?** Yes.  
**Confidence:** High

### C-05 — drift_check runs without org_id/RLS context

**Verdict:** CONFIRMED-ESCALATED  
**Final severity:** Crit  
**Reasoning:** `run_drift_check` takes no `org_id` at `backend/app/domains/wealth/workers/drift_check.py:25` and opens `async_session()` directly at `34` without `set_rls_context`. It reads via `compute_drift` at `60`, which queries `PortfolioSnapshot` at `backend/app/domains/wealth/services/quant_queries.py:2236-2243`; that model is `OrganizationScopedMixin` at `backend/app/domains/wealth/models/portfolio.py:13`. It then creates a `RebalanceEvent` at `drift_check.py:78-90`, while `RebalanceEvent` is also org-scoped at `backend/app/domains/wealth/models/rebalance.py:13`. Multi-tenant read/write ambiguity is always Crit under institutional convention.  
**Override of Stage 1?** Escalated from High to Crit.  
**Test still required?** Yes.  
**Confidence:** High

### C-06 — drift_check advisory lock acquired outside immediate try/finally

**Verdict:** CONFIRMED-DOWNGRADED  
**Final severity:** High  
**Reasoning:** The lock is acquired at `backend/app/domains/wealth/workers/drift_check.py:36-40`, but the first `try/finally` that unlocks it only starts at `58` and unlocks at `99-100`. A cancellation between lines `42-56` can bypass the unlock. The mechanism is valid and independent from C-05, but the prompt’s convention says lock leaks requiring DB restart are at least High; this finding does not establish a guaranteed every-call production crash or data leak. High is the defensible final severity.  
**Override of Stage 1?** Downgraded from Gemini Crit to High.  
**Test still required?** Yes.  
**Confidence:** High

### C-07 — approve_dd_report creates UniverseApproval without clearing prior is_current

**Verdict:** CONFIRMED  
**Final severity:** High  
**Reasoning:** Gemini’s checked invariant is wrong for the `UniverseApproval` branch. `approve_dd_report` creates a new `UniverseApproval` at `backend/app/domains/wealth/routes/dd_reports.py:572-583` and there is no preceding query/update that clears prior current approvals in the function body at `502-583`. The model default is `is_current=true` at `backend/app/domains/wealth/models/universe_approval.py:46-48`, and the migration documents a unique current-approval index at `backend/app/core/db/migrations/versions/0008_wealth_analytical_models.py:300-306`. This supports Opus’s idempotency bug and a High severity crash/duplicate-current risk.  
**Override of Stage 1?** Confirms Opus; refutes Gemini’s sibling verification.  
**Test still required?** Yes.  
**Confidence:** High

### C-08 — apply_rebalance_proposal has no role gate

**Verdict:** CONFIRMED-ESCALATED  
**Final severity:** Crit  
**Reasoning:** `apply_rebalance_proposal` depends only on `get_current_user`, `get_actor`, and `get_org_id` at `backend/app/domains/wealth/routes/rebalancing.py:47-53`; there is no `require_role` or local role helper. The body mutates model portfolio selection at `rebalancing.py:106-114`, creates a new `PortfolioSnapshot` at `121-132`, writes a NAV breakpoint at `139-152`, and marks the proposal applied at `154-168`. This is a mutating route that changes IC-level portfolio allocation, so missing role enforcement is a privilege escalation and always Crit.  
**Override of Stage 1?** Escalated from High to Crit.  
**Test still required?** Yes.  
**Confidence:** High

### C-09 — write_audit_event silently accepts NULL organization_id

**Verdict:** REFUTED  
**Final severity:** N/A  
**Reasoning:** Current `main` still shows the issue: `backend/app/core/db/audit.py:59-66` resolves org from RLS if available, then creates the event at `68-84` without raising on null. However, the consolidation explicitly records PR #392 as already implementing the exact `allow_global=False` flag and `ValueError` behavior requested. Under the Stage 2 rules, an already fixed in-flight PR is REFUTED, not re-confirmed from `main`.  
**Override of Stage 1?** Yes; refuted by PR #392 subsumption.  
**Test still required?** No because subsumed by PR #392, assuming that PR’s tests cover the guard.  
**Confidence:** High

### C-10 — benchmark_ingest bypasses ExternalProviderGate

**Verdict:** CONFIRMED  
**Final severity:** Med  
**Reasoning:** `backend/app/domains/wealth/workers/benchmark_ingest.py:117-137` performs a manual retry loop around `_fetch_via_tiingo` through `run_in_executor`. There is no `ExternalProviderGate` wrapping this call in the cited code path, so timeout/circuit-breaker behavior from the Stability Charter is bypassed. The direct consequence shown is degraded external-provider behavior and worker blocking risk, not lower-privilege unbounded spend or a whole-pipeline deadlock. Med is appropriate.  
**Override of Stage 1?** No.  
**Test still required?** Yes.  
**Confidence:** High

### C-11 — approve_fund/reject_fund split mutation and audit across transactions

**Verdict:** CONFIRMED  
**Final severity:** Med  
**Reasoning:** In `approve_fund`, the state mutation runs inside a synchronous `sync_db.begin()` block at `backend/app/domains/wealth/routes/universe.py:404-455`, returns at `457`, then writes audit with the async session at `458-467`. `reject_fund` repeats the same pattern at `universe.py:502-558`. If the second transaction fails, the fund decision is already committed without its audit row. This is a real audit atomicity bug, but Stage 1 did not show a routinely reachable silent audit loss on every mutation, so Med is retained.  
**Override of Stage 1?** No.  
**Test still required?** Yes.  
**Confidence:** High

### C-12 — GET /catalog silently accepts unknown query params

**Verdict:** CONFIRMED  
**Final severity:** Med  
**Reasoning:** `get_catalog` exposes many independent `Query` parameters at `backend/app/domains/wealth/routes/screener.py:1894-1927`, and sibling catalog routes use the same loose pattern at `2131-2140` and `2224-2232`. There is no Pydantic query model with `extra="forbid"` in that route signature. Under institutional convention, strict-params silent ignore on user-facing GET routes is at least Med.  
**Override of Stage 1?** No.  
**Test still required?** Yes.  
**Confidence:** High

### C-13 — trigger_dd_report and regenerate_dd_report missing IC role check

**Verdict:** CONFIRMED-ESCALATED  
**Final severity:** High  
**Reasoning:** `trigger_dd_report` at `backend/app/domains/wealth/routes/dd_reports.py:248-254` and `regenerate_dd_report` at `439-445` require `get_current_user`/RLS org context but not `require_role`. In the same file, approval and rejection require `Role.INVESTMENT_TEAM` at `dd_reports.py:502-507` and `653-658`, showing the intended privilege boundary for DD lifecycle mutations. Because DD generation creates records and consumes LLM credits, this is unbounded external API spend by lower-privilege users, which is at least High. It is not Crit because the action is generation, not final IC-state approval.  
**Override of Stage 1?** Escalated from Med to High.  
**Test still required?** Yes.  
**Confidence:** High

### C-14 — strategy_reclassification references pre-Q11B esma_funds.isin

**Verdict:** CONFIRMED  
**Final severity:** Med  
**Reasoning:** `_read_esma_funds` selects and orders by `isin` at `backend/app/domains/wealth/workers/strategy_reclassification.py:441-452`. Q11B migration `backend/app/core/db/migrations/versions/0182_switch_esma_funds_pk_to_lei.py:26-28` changes the primary key to `lei` and renames `isin` to `legacy_isin_misnamed`; later migration SQL also reads UCITS rows via `ef.legacy_isin_misnamed` in `0183_mv_unified_funds_ucits_share_classes.py:347-350`. `fund_type` and `is_institutional` exist in the post-migration schema, so the confirmed break is specifically the stale `isin` reference. Med is appropriate for a source-specific worker crash/partial loss.  
**Override of Stage 1?** No, with narrowed mechanism to the `isin` rename.  
**Test still required?** Yes.  
**Confidence:** High

### C-15 — org_id: str annotation lie at 30+ route sites

**Verdict:** CONFIRMED  
**Final severity:** Low  
**Reasoning:** `get_org_id` returns `uuid.UUID | None` at `backend/app/core/tenancy/middleware.py:38-40`, while `rg` finds many route parameters annotated `org_id: str = Depends(get_org_id)`, including `backend/app/domains/wealth/routes/dd_reports.py:253`, `rebalancing.py:52`, `instruments.py:214`, and numerous `model_portfolios.py` sites. Most of these pass the value through or stringify defensively, so this is not the same as C-03’s current crash sites. Per institutional convention, an annotation lie without current runtime impact is a footgun, and Low matches the Stage 1 rating.  
**Override of Stage 1?** No.  
**Test still required?** Yes, static coverage is sufficient.  
**Confidence:** High

## Cross-cutting observations

The strongest pattern is tenant-boundary inconsistency: C-05 lacks RLS context in a worker, C-08 lacks role gating before a portfolio mutation, and C-13 lacks role gating before costly DD generation. These should not be batched as one fix because the enforcement points differ, but they share the same institutional control weakness.

The idempotency failures split into durable state reactivation (C-01), partial-unique current-row collisions (C-02/C-07), and audit atomicity gaps (C-11). PR #391 and PR #393 reduce the blast radius of C-01 and C-03 respectively, but neither removes the underlying canonical finding.

## Appendix — unsolicited hypotheses

None.
