# Wave 6 — Session 09 Stage 3 — Remediation PR Prompts

**Status:** READY FOR DISPATCH (10 PR prompts)
**Stage:** 3 (Opus 4.7 orchestration output)
**Date:** 2026-04-28
**Source:** Stage 2 jury verdict ([docs/audits/2026-04-28-wave6-session09-stage2-jury.md](../audits/2026-04-28-wave6-session09-stage2-jury.md))
**Triage outcome:** 14 CONFIRMED + 1 REFUTED (C-09 subsumed by Q92)

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

Each section below is a self-contained PR remediation prompt. Dispatch sequentially or in parallel to fresh Opus 4.7 (1M) sessions per `feedback_delegation_model.md`. Do NOT batch unrelated PRs; each prompt = one PR.

**Recommended dispatch order** (P0 first, mergeable independently after Codex Auto Review):

| Tier | PR | Findings | Severity |
|---|---|---|---|
| **P0** (production blockers) | Q94 | C-01 | Crit |
| **P0** | Q95 | C-02 | Crit |
| **P0** | Q96 | C-03 | Crit |
| **P0** | Q97 | C-05 + C-06 | Crit + High |
| **P0** | Q98 | C-08 | Crit |
| **P1** | Q99 | C-04 | High |
| **P1** | Q100 | C-07 | High |
| **P1** | Q101 | C-13 | High |
| **P2** | Q102 | C-10 + C-11 + C-12 + C-14 | Med batch |
| **P3** | Q103 | C-15 | Low |

PRs do not have hard dependencies between them, but all 10 stack on `main`. After Q91-Q93 land, rebase. Consider running Codex Auto Review (Stage 4) on each before merging.

---

## PR-Q94 — C-01 universe_sync ON CONFLICT omits is_active reactivation (Crit)

```text
You are implementing PR-Q94, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-01).

FINDING

Title: universe_sync ON CONFLICT omits is_active reactivation across all 5 sync phases
Files/lines:
  backend/app/domains/wealth/workers/universe_sync.py:219-222 (_sync_sec_etfs)
  backend/app/domains/wealth/workers/universe_sync.py:296-299 (_sync_sec_bdcs)
  backend/app/domains/wealth/workers/universe_sync.py:392-395 (_sync_sec_registered)
  backend/app/domains/wealth/workers/universe_sync.py:465-468 (_sync_esma_funds)
  backend/app/domains/wealth/workers/universe_sync.py:539-543 (_sync_sec_mmfs)
  backend/app/domains/wealth/workers/universe_sync.py:561-569 (_deactivate_no_nav, contextual)

Severity: Crit (institutional convention §3.1 — permanent state corruption requiring manual SQL repair)
Verdict: CONFIRMED by Stage 2 jury

Mechanism: _deactivate_no_nav flips is_active=false for any instrument lacking nav_timeseries rows.
The 5 ON CONFLICT DO UPDATE SET clauses update name/attributes/timestamps but NEVER include
`is_active = EXCLUDED.is_active` or `is_active = true`. When NAV later arrives (Tiingo / Yahoo /
N-PORT etc.), the next universe_sync run upserts the row, but is_active stays false. Result:
permanently silenced funds despite valid data.

Empirical evidence (smoke 2026-04-28):
  SPY (instrument_id 5e15389e-...) — 2516 NAV rows, is_active=false
  All 6174 NAV-bearing instruments are vulnerable
  PR-Q91 (#391, in main) reactivated UCITS one-time but did NOT patch this race

CONSTRAINTS

- Keep changes scoped to universe_sync.py and one new test file.
- Add `is_active = EXCLUDED.is_active` to all 5 ON CONFLICT DO UPDATE SET clauses.
- For _sync_sec_registered (uses ON CONFLICT DO NOTHING per current pattern), verify whether
  changing to DO UPDATE SET is_active = true is safe; if pattern was DO NOTHING for a reason,
  explain in PR description and choose appropriate fix.
- Update the docstring at universe_sync.py:557-559 — "Idempotent — if a ticker gains NAV later,
  next universe_sync re-inserts with is_active=true via ON CONFLICT UPDATE." — keep claim true.
- Do NOT also patch the upsert to clear is_active=false from other code paths; scope is limited
  to making the documented re-activation work.
- Do NOT touch _deactivate_no_nav itself.

REQUIRED TEST

Add backend/tests/wealth/workers/test_universe_sync_reactivation.py:

  @pytest.mark.asyncio
  async def test_sec_etf_reactivation_after_deactivate(db_session):
      # Arrange: insert SEC ETF row with is_active=True
      # Run _deactivate_no_nav → is_active=false (no nav_timeseries rows)
      # Insert one nav_timeseries row for the instrument
      # Re-run _sync_sec_etfs with the same ticker payload
      # Assert: instruments_universe.is_active == True

  Repeat the same pattern for _sync_sec_bdcs, _sync_esma_funds, _sync_sec_mmfs.
  _sync_sec_registered: explicit assertion based on chosen DO NOTHING vs DO UPDATE decision.

ACCEPTANCE

- 5 SQL clauses patched
- 5 reactivation tests added (one per sync function, parametrize if convenient)
- Docstring at line 557-559 still accurate post-fix
- Lint clean
- Manual reproduction:
    docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c \
      "UPDATE instruments_universe SET is_active=false WHERE ticker='SPY';"
    cd backend && ../.venv/Scripts/python.exe -m app.domains.wealth.workers.universe_sync
    docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c \
      "SELECT is_active FROM instruments_universe WHERE ticker='SPY';"
  Expected: t

PR DESCRIPTION

Title: fix(wealth): PR-Q94 — universe_sync ON CONFLICT omits is_active reactivation (Crit)
Body: cite Wave 6 Session 09 C-01 verdict; explain reduced scope post-Q91 (Q91 was one-time
reactivation, this PR fixes the recurring race); list the 5 patched clauses; reference the
empirical SPY repro.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q95 — C-02 trigger_screening idempotency (Crit)

```text
You are implementing PR-Q95, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-02).

FINDING

Title: trigger_screening inserts is_current=True without clearing prior rows
Files/lines: backend/app/domains/wealth/routes/screener.py:573-585 (handler) + 810-818 (lock loop) + 822-833 (insert) + 837 (commit)
Severity: Crit (jury upgraded from Gemini High via §3.2 idempotency on documented retry contract)
Verdict: CONFIRMED

Mechanism: The handler locks existing rows with SELECT ... FOR UPDATE but never executes
`UPDATE ScreeningResult SET is_current=False WHERE ...` before INSERT. The partial unique
index `uq_screening_results_current` on `(organization_id, instrument_id) WHERE is_current=true`
(migration 0012:208-215) collides → IntegrityError on every re-run for the same pair.

Reference correct pattern: screener.py:2949-2950 (fast_track_approval) — `if existing: existing.is_current = False`.

CONSTRAINTS

- Add an UPDATE statement BEFORE the INSERT, in the same transaction.
- Use SQLAlchemy update() with WHERE clauses on (instrument_id, organization_id implicit via RLS,
  is_current.is_(True)) and SET is_current=False.
- Place the UPDATE inside the same `for inst_dict in instrument_dicts:` loop OR as a single
  bulk UPDATE before the loop — choose what minimizes round-trips.
- Do NOT change the INSERT logic, the SELECT FOR UPDATE lock acquisition, or the partial-unique
  index. Scope is the missing UPDATE.
- Do NOT touch other screener routes (fast_track_approval already correct).

REQUIRED TEST

Add backend/tests/wealth/routes/test_trigger_screening_idempotent.py:

  @pytest.mark.asyncio
  async def test_screening_rerun_no_integrity_error(client, db_session):
      # Setup: 1 instrument linked to org via instruments_org
      # Call trigger_screening for that instrument → 200 OK
      # Call trigger_screening for that instrument again → 200 OK (no IntegrityError)
      # Assert: exactly 1 row with is_current=True for that (org, instrument)
      # Assert: at least 1 row with is_current=False (the prior current)

  @pytest.mark.asyncio
  async def test_screening_concurrent_runs_serialized(client, db_session):
      # Two concurrent trigger_screening calls for same instrument
      # Both succeed (advisory lock or transaction serialization handles it)
      # Final state: exactly 1 is_current=True row

ACCEPTANCE

- UPDATE inserted before INSERT
- Both tests pass
- Lint clean
- Manual reproduction via curl confirms 200 on second call

PR DESCRIPTION

Title: fix(wealth): PR-Q95 — trigger_screening idempotency (Crit, smoke catch)
Body: cite Wave 6 Session 09 C-02 verdict and Stability Charter §3.5 P5; reference
screener.py:2949 as the correct sibling pattern.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q96 — C-03 sweep 5 remaining UUID cast sites (Crit)

```text
You are implementing PR-Q96, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-03).

FINDING

Title: uuid.UUID(org_id) crashes at 5 sites where org_id is already UUID
Files/lines:
  backend/app/domains/wealth/routes/instruments.py:229
  backend/app/domains/wealth/routes/content.py:403
  backend/app/domains/wealth/routes/content.py:443
  backend/app/domains/wealth/routes/portfolios/builder.py:121
  backend/app/domains/wealth/routes/portfolios/builder.py:220
Severity: Crit (production endpoints crash on every call)
Verdict: CONFIRMED

Background: PR-Q93 (#393) already fixed `routes/universe.py:689` (fast_approve). The same
pattern exists at 5 other reachable sites. `get_org_id` returns `uuid.UUID | None`; all 5 sites
annotate `org_id: str = Depends(get_org_id)` and call `uuid.UUID(org_id)` which crashes with
`AttributeError: 'UUID' object has no attribute 'replace'` because the constructor calls
`.replace('urn:', '')` on the already-UUID input.

CONSTRAINTS

- At each of the 5 sites: change annotation `org_id: str` → `org_id: uuid.UUID` and remove the
  `uuid.UUID(org_id)` cast.
- For sites passing org_id to a sync thread (content.py background tasks at 403, 443): if the
  callee expects str, use `str(org_id)` AT THE BOUNDARY, not at the source.
- Do NOT touch the 30+ other sites with the wrong annotation but no cast (those are C-15 / Q103 scope).
- Verify each site's body for additional `org_id`-as-string assumptions (e.g. .split, .startswith).
  If any exist, fix or wrap with str(org_id) explicitly.

REQUIRED TEST

Add backend/tests/wealth/routes/test_uuid_cast_sites_no_crash.py:

  Parametrize over the 5 affected route handlers. For each:
  @pytest.mark.asyncio
  async def test_<route_name>_does_not_crash_on_uuid_org(client_with_dev_actor):
      # Make the minimal valid request to the route
      # Assert response.status_code != 500 (don't depend on 200; some may legitimately return 4xx
      # for missing entities, but 500 with AttributeError is the bug)

ACCEPTANCE

- 5 annotations changed
- 5 casts removed
- 5 smoke tests pass
- Manual repro: any of the 5 affected routes return non-500 status

PR DESCRIPTION

Title: fix(wealth): PR-Q96 — sweep 5 UUID cast crash sites (Crit, post-Q93)
Body: enumerate the 5 sites; cite Wave 6 Session 09 C-03 verdict; note PR-Q93 was the first site
fixed but the pattern was a footgun (annotation lie + str-only constructor call).

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q97 — C-05 + C-06 drift_check RLS context + lock try/finally (Crit + High, batch)

```text
You are implementing PR-Q97, a narrow remediation for two accepted Wave 6 Session 09 findings on the same file (C-05 + C-06). Batched because both touch drift_check.py and the test surface overlaps.

FINDINGS

C-05 — drift_check runs without org_id / RLS context (Crit, ESCALATED from High)
  File: backend/app/domains/wealth/workers/drift_check.py:25-103
  Mechanism: run_drift_check has no org_id parameter and opens async_session() at line 34
  without set_rls_context. Reads org-scoped PortfolioSnapshot at compute_drift, creates
  org-scoped RebalanceEvent at line 78. Multi-tenant data leak risk.

C-06 — Advisory lock acquired outside try/finally (High, DOWNGRADED from Crit)
  File: backend/app/domains/wealth/workers/drift_check.py:36-100
  Mechanism: pg_try_advisory_lock(PIPELINE_LOCK_ID) at line 36-40, but the try/finally that
  unlocks it only starts at line 58. Lines 42-56 (config load) can asyncio.CancelledError
  before the try, leaking the lock perpetually.

CONSTRAINTS

- Refactor run_drift_check to accept `org_id: uuid.UUID` parameter (mirroring portfolio_eval.py:276).
- Caller layer (scheduler / job runner) must iterate active orgs and call run_drift_check(org_id) per org.
  If the caller is not in this PR's scope, document the API change clearly in PR description and
  open a follow-up ticket.
- Inside the function: after opening async_session, call `await set_rls_context(db, org_id)` BEFORE
  any query.
- Wrap the entire body after pg_try_advisory_lock acquisition (line 36 onwards) in a single
  try/finally. Move the existing inner try/finally inside the outer one.
- Keep the lock ID constant and deterministic; do NOT change lock_id derivation.
- Do NOT alter compute_drift's math logic — that's Session 03 territory.

REQUIRED TESTS

Add backend/tests/wealth/workers/test_drift_check_rls_and_lock.py:

  @pytest.mark.asyncio
  async def test_drift_check_requires_org_id():
      # Call run_drift_check() without org_id → TypeError
      # Call run_drift_check(org_id=uuid.uuid4()) → no error (returns dict)

  @pytest.mark.asyncio
  async def test_drift_check_sets_rls_context(db_session):
      # Create snapshots for org_A and org_B with different drift values
      # Call run_drift_check(org_id=org_A)
      # Assert: rebalance events created only for org_A

  @pytest.mark.asyncio
  async def test_drift_check_lock_released_on_cancellation():
      # Mock VerticalConfigDefault.config to raise asyncio.CancelledError
      # Wrap run_drift_check in asyncio.shield + cancel
      # Assert: pg_advisory_unlock(PIPELINE_LOCK_ID) was called (lock released)

ACCEPTANCE

- run_drift_check signature accepts org_id
- Outer try/finally wraps everything after lock acquisition
- All 3 tests pass
- Lint clean

PR DESCRIPTION

Title: fix(wealth): PR-Q97 — drift_check RLS context + lock try/finally (Crit + High)
Body: cite Wave 6 Session 09 C-05 + C-06 verdicts; explain why batch (same file, overlapping
test fixtures); document scheduler API change.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q98 — C-08 apply_rebalance_proposal role gate (Crit)

```text
You are implementing PR-Q98, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-08).

FINDING

Title: apply_rebalance_proposal has no role gate — privilege escalation
File/line: backend/app/domains/wealth/routes/rebalancing.py:47-53
Severity: Crit (institutional convention §3.1 — privilege escalation on portfolio mutation)
Verdict: CONFIRMED-ESCALATED (from High to Crit)

Mechanism: apply_rebalance_proposal handler depends only on get_current_user, get_actor,
get_org_id. No _require_investment_role(actor) or _require_ic_role(actor) call. Body mutates
model portfolio selection at 106-114, creates PortfolioSnapshot at 121-132, writes NAV breakpoint
at 139-152, marks proposal applied at 154-168. Investor-role users (read-only intent) can apply
a rebalance, changing entire portfolio allocation.

CONSTRAINTS

- Add `_require_ic_role(actor)` as the first body statement of the handler.
- Do NOT change other rebalancing routes in this PR — verify they have appropriate gates as a
  pre-flight check; if any siblings ALSO lack gates, mention as follow-up but do not fix here.
- Do NOT change the rebalance business logic.

REQUIRED TEST

Add backend/tests/wealth/routes/test_apply_rebalance_role_gate.py:

  @pytest.mark.asyncio
  async def test_apply_rebalance_rejects_investor_role(client_investor_role, sample_proposal):
      resp = await client_investor_role.post(
          f"/api/v1/rebalancing/proposals/{sample_proposal.id}/apply"
      )
      assert resp.status_code == 403

  @pytest.mark.asyncio
  async def test_apply_rebalance_accepts_ic_role(client_ic_role, sample_proposal):
      resp = await client_ic_role.post(
          f"/api/v1/rebalancing/proposals/{sample_proposal.id}/apply"
      )
      assert resp.status_code in (200, 202)

ACCEPTANCE

- 1-line role check added
- 2 tests pass
- Pre-flight verification of sibling rebalancing routes documented in PR description (without fixing)
- Lint clean

PR DESCRIPTION

Title: fix(wealth): PR-Q98 — apply_rebalance_proposal role gate (Crit)
Body: cite Wave 6 Session 09 C-08 verdict; this is a privilege-escalation P0; tenant-visible
behavior change (investors get 403, was 200).

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q99 — C-04 regime_fit dead lock (High)

```text
You are implementing PR-Q99, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-04).

FINDING

Title: regime_fit defines LOCK_ID=900_026 but never acquires it
File/lines: backend/app/domains/wealth/workers/regime_fit.py:43 (LOCK_ID definition) + 267-317 (run_regime_fit body)
Severity: High (jury §3.2 — worker race that can deadlock or produce stale derived state)
Verdict: CONFIRMED

Mechanism: LOCK_ID = 900_026 is defined at line 43 but never acquired or released. run_regime_fit
opens 3 separate async sessions at lines 267-317 with no advisory lock. Two concurrent invocations
race on macro_regime_history INSERT ON CONFLICT (idempotent at history table level) and on
PortfolioSnapshot UPDATE (potentially stale p_high_vol from earlier run committed after later run).

CONSTRAINTS

- Wrap run_regime_fit body in pg_try_advisory_lock(LOCK_ID) → unlock in finally.
- Pattern reference: backend/app/domains/wealth/workers/benchmark_ingest.py:67-79 (lines
  acquiring + finally-unlocking lock 900_004).
- Use a single async_session for the lock acquisition+release, even if internal queries open
  more sessions for fetching/persisting (lock is a separate connection's coordination).
- If lock not acquired (already held), return `{"status": "skipped", "reason": "lock_held"}`
  matching benchmark_ingest behavior.

REQUIRED TEST

Add backend/tests/wealth/workers/test_regime_fit_lock.py:

  @pytest.mark.asyncio
  async def test_regime_fit_skips_when_lock_held(db_session):
      # Manually acquire lock 900_026 in test session
      # Call run_regime_fit
      # Assert: returns {"status": "skipped", "reason": "lock_held"}
      # Release lock

  @pytest.mark.asyncio
  async def test_regime_fit_releases_lock_on_exception():
      # Mock _fetch_vix_series_with_dates to raise
      # Call run_regime_fit → expect exception
      # Assert: lock 900_026 is now releasable (no longer held)

ACCEPTANCE

- run_regime_fit body wrapped in try/finally + lock acquire/release
- "skipped" branch returns expected dict
- 2 tests pass
- Lint clean

PR DESCRIPTION

Title: fix(wealth): PR-Q99 — regime_fit advisory lock acquire/release (High)
Body: cite Wave 6 Session 09 C-04 verdict; LOCK_ID was dead since the worker was written.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q100 — C-07 approve_dd_report idempotency (High)

```text
You are implementing PR-Q100, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-07).

FINDING

Title: approve_dd_report creates UniverseApproval without clearing prior is_current
File/lines: backend/app/domains/wealth/routes/dd_reports.py:572-583 (UniverseApproval creation)
Severity: High (jury verdict; institutional convention §3.2 idempotency violation on documented retry contract)
Verdict: CONFIRMED — Opus right, Gemini's invariant check missed this code path.

Mechanism: When a DD report is approved, the handler creates UniverseApproval with
is_current=True (model default at universe_approval.py:46-48). No prior query/UPDATE clears
existing UniverseApproval rows where is_current=True for the same instrument. Migration
0008:300-306 documents a partial unique index on (organization_id, instrument_id) WHERE
is_current=true. Re-approval after reject → regenerate produces IntegrityError or duplicate
"current" rows depending on schema version.

Reference correct sibling pattern: screener.py:2936-2950 (fast_track_approval).

CONSTRAINTS

- BEFORE `db.add(approval)` at line 583, query existing UniverseApproval rows for the same
  (organization_id, instrument_id) where is_current=True, set them is_current=False.
- Use SQLAlchemy select() + bulk update or for-loop, mirroring fast_track_approval pattern.
- Do NOT change UniverseApproval model defaults.
- Do NOT touch the screener.fast_track_approval path.
- Do NOT propose the partial-unique index (it already exists per migration 0008).

REQUIRED TEST

Add backend/tests/wealth/routes/test_dd_approve_idempotent.py:

  @pytest.mark.asyncio
  async def test_dd_approve_clears_prior_current_approval(client_ic_role, db_session, instrument_id):
      # Setup: existing UniverseApproval with is_current=True for the instrument
      # Create DD report for the same instrument
      # Call approve endpoint
      # Assert: 200 OK
      # Assert: exactly 1 row has is_current=True for this (org, instrument)
      # Assert: prior approval has is_current=False

  @pytest.mark.asyncio
  async def test_dd_approve_after_reject_regenerate_cycle(client_ic_role, db_session):
      # Setup: instrument with prior approval (is_current=True)
      # Reject → regenerate → approve (second time)
      # Assert: 200 OK on all calls
      # Assert: only 1 is_current=True row, latest

ACCEPTANCE

- UPDATE before INSERT in approve_dd_report
- 2 tests pass
- No regression in existing dd_reports tests
- Lint clean

PR DESCRIPTION

Title: fix(wealth): PR-Q100 — approve_dd_report idempotency (High)
Body: cite Wave 6 Session 09 C-07 verdict + jury direct contradiction adjudication; reference
fast_track_approval as the correct sibling pattern.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q101 — C-13 DD trigger/regenerate IC role gate (High)

```text
You are implementing PR-Q101, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-13).

FINDING

Title: trigger_dd_report and regenerate_dd_report missing IC role check
File/lines: backend/app/domains/wealth/routes/dd_reports.py:248-254 (trigger) + 439-445 (regenerate)
Severity: High (jury §3.2 — unbounded external API spend by lower-privilege users)
Verdict: CONFIRMED-ESCALATED (from Med to High)

Mechanism: Both handlers depend on get_current_user / get_actor / get_org_id but lack
require_role or _require_ic_role. Approve/reject routes in same file (lines 506, 657) DO require
Role.INVESTMENT_TEAM, showing intended privilege boundary. DD trigger consumes OpenAI credits
(LLM calls per chapter via deep_review pipeline) and creates permanent DB records.

CONSTRAINTS

- Add `_require_investment_role(actor)` (preferred — lower bar than IC) OR
  `actor: Actor = Depends(require_role(Role.INVESTMENT_TEAM))` (matches sibling pattern).
- Choose ONE based on what protects equally vs the same file's approve/reject (which use
  require_role(Role.INVESTMENT_TEAM)).
- Apply to BOTH trigger_dd_report and regenerate_dd_report; do not split into 2 PRs.
- Do NOT touch list_dd_reports / get_dd_report (read-only routes).
- Verify: if any sibling DD route besides approve/reject/trigger/regenerate is also a mutation,
  mention as follow-up but don't fix here.

REQUIRED TEST

Add backend/tests/wealth/routes/test_dd_trigger_role_gate.py:

  @pytest.mark.asyncio
  async def test_trigger_dd_report_rejects_investor_role(client_investor_role, fund_id):
      resp = await client_investor_role.post(f"/api/v1/dd-reports/funds/{fund_id}")
      assert resp.status_code == 403

  @pytest.mark.asyncio
  async def test_regenerate_dd_report_rejects_investor_role(client_investor_role, report_id):
      resp = await client_investor_role.post(f"/api/v1/dd-reports/{report_id}/regenerate")
      assert resp.status_code == 403

  @pytest.mark.asyncio
  async def test_trigger_dd_report_accepts_investment_team(client_investment_team, fund_id):
      resp = await client_investment_team.post(f"/api/v1/dd-reports/funds/{fund_id}")
      assert resp.status_code in (200, 202)

ACCEPTANCE

- 2 role gates added (1 per handler)
- 3 tests pass
- Lint clean
- Document tenant-visible behavior change in PR description

PR DESCRIPTION

Title: fix(wealth): PR-Q101 — DD trigger/regenerate IC role gate (High)
Body: cite Wave 6 Session 09 C-13 verdict; tenant-visible behavior change (investor users
who could trigger get 403); rationale: unbounded LLM spend.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q102 — Med batch (C-10 + C-11 + C-12 + C-14)

```text
You are implementing PR-Q102, a batched remediation for 4 accepted Wave 6 Session 09 Med-severity findings. They are batched because each is small (≤30 LoC) and they cluster as a P2 cleanup wave. If any of them grows unexpectedly during implementation, split off into a standalone PR.

FINDING C-10 — benchmark_ingest bypasses ExternalProviderGate
  File/lines: backend/app/domains/wealth/workers/benchmark_ingest.py:117-138
  Mechanism: Manual retry loop with 4^attempt backoff but no ExternalProviderGate, no circuit
  breaker, no hard timeout. esma_aum_sync.py uses _yahoo_gate correctly — mirror that pattern.
  Fix: Wrap _fetch_via_tiingo in ExternalProviderGate(GateConfig(name="tiingo_benchmark",
  timeout_s=60.0, failure_threshold=3, recovery_after_s=300)). Remove manual retry loop.

FINDING C-11 — approve_fund / reject_fund split mutation+audit across 2 transactions
  File/lines: backend/app/domains/wealth/routes/universe.py:404-467 (approve) + 502-558 (reject)
  Mechanism: state mutation in sync session block (T1, committed), audit write in async session
  (T2, separate commit). If T2 fails, mutation persists without audit row.
  Fix: Move write_audit_event into the sync session BEFORE the implicit commit at sync_db.begin
  context exit. Use sync write_audit_event variant if needed; if no sync variant exists, refactor
  to an outer async session that wraps both.
  Constraint: Approve and reject must be fixed together (same pattern, same file).

FINDING C-12 — GET /catalog silently accepts unknown query params
  File/lines: backend/app/domains/wealth/routes/screener.py:1894-1927 (catalog) + 2131-2140 (managers) + 2224-2232 (facets)
  Mechanism: 28 explicit Query() params, FastAPI silently drops unknowns.
  Fix: Create a Pydantic model with model_config = ConfigDict(extra="forbid"). Use Annotated[Model, Query()]
  pattern OR move to a dedicated CatalogQueryParams class via Depends(). Apply to all 3 routes.

FINDING C-14 — strategy_reclassification _read_esma_funds references pre-Q11B esma_funds.isin
  File/lines: backend/app/domains/wealth/workers/strategy_reclassification.py:441-464
  Mechanism: SELECT isin AS pk + ORDER BY isin. Q11B (migration 0182, in main) renamed isin to
  legacy_isin_misnamed and changed PK to lei.
  Fix: SELECT lei AS pk + ORDER BY lei. Do NOT touch fund_type or is_institutional (jury verified
  these still exist post-Q11B).

CONSTRAINTS

- Each fix in a separate commit within this PR (4 commits total).
- Each fix has its own test under backend/tests/wealth/.
- If any fix exceeds ~50 LoC during implementation, split off into PR-Q102a/b/c/d immediately.

REQUIRED TESTS

Per finding, minimum:

C-10: test that benchmark_ingest with mocked Tiingo timeout returns degraded marker (not raise).
C-11: test that approve_fund failing audit write rolls back the approval (mock write_audit_event to raise).
C-12: GET /screener/catalog?unknown_param=1 returns 422.
C-14: run_strategy_reclassification(sources=["esma_funds"], limit_per_source=5) returns ≥1 candidate.

ACCEPTANCE

- 4 fixes applied
- 4 tests pass
- Lint clean
- Each fix is standalone-revertable (separate commits)

PR DESCRIPTION

Title: fix(wealth): PR-Q102 — Wave 6 S09 Med batch (4 findings)
Body: cite each finding with verdict + reasoning; explain the batch rationale (small scope,
P2 wave); list the 4 commits.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## PR-Q103 — C-15 org_id annotation cleanup (Low)

```text
You are implementing PR-Q103, a narrow remediation for an accepted Wave 6 Session 09 audit finding (C-15).

FINDING

Title: org_id: str annotation lie at 30+ route sites — footgun for next maintainer
Files/lines:
  universe.py:155, 325, 390, 482, 628
  dd_reports.py:253, 444, 720
  fact_sheets.py:64, 159, 206, 311
  monitoring.py:35
  rebalancing.py:52
  instruments.py:214
  model_portfolios.py:203, 323, 428, 587, 764, 797, 1215, 3460, 3522, 3597, 4863, 4934, 5059, 5292, 5413, 5576
  content.py:81, 131, 183, 352
  analytics.py:139
  research.py:334
  portfolio_views.py:70
  search.py:185
  screener.py:2856
Severity: Low (footgun only — no current runtime crash at these sites; PR-Q96 already fixed the 5 sites that DO crash)
Verdict: CONFIRMED

Mechanism: get_org_id returns uuid.UUID | None; these 30+ sites annotate org_id: str. Most
either pass org_id transparently or already wrap defensively with uuid.UUID(str(org_id)).
This is annotation hygiene, not a runtime bug.

CONSTRAINTS

- Bulk annotation rename: `org_id: str = Depends(get_org_id)` → `org_id: uuid.UUID = Depends(get_org_id)`.
- Where the body has redundant `uuid.UUID(str(org_id))` casts (e.g. model_portfolios.py:222, 5140,
  5351, 5444, 5599), simplify to direct usage.
- Do NOT change route paths, response models, or any business logic.
- Do NOT touch sites already fixed by PR-Q93 / PR-Q96.
- If a site uses `Optional[str]` because the org may be None, change to `uuid.UUID | None`.

REQUIRED TEST

Add backend/tests/static/test_no_org_id_str_annotation.py:

  import ast
  from pathlib import Path

  def test_no_org_id_str_lying_annotation():
      """Static check: no route handler annotates `org_id: str = Depends(get_org_id)`."""
      offenders = []
      for path in Path("backend/app/domains").rglob("*.py"):
          tree = ast.parse(path.read_text())
          for node in ast.walk(tree):
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                  for arg in node.args.args + node.args.kwonlyargs:
                      if arg.arg == "org_id" and arg.annotation:
                          ann = ast.unparse(arg.annotation)
                          if ann == "str":
                              # Look at default — is it Depends(get_org_id)?
                              # Static check is approximate; flag any org_id: str
                              offenders.append(f"{path}:{arg.lineno}")
      assert not offenders, f"org_id: str annotation lies remain: {offenders}"

ACCEPTANCE

- All 30+ sites renamed
- Static test passes (0 offenders)
- Lint clean
- No runtime regressions (existing tests still pass)

PR DESCRIPTION

Title: chore(wealth): PR-Q103 — sweep org_id: str annotation lies (Low cleanup)
Body: cite Wave 6 Session 09 C-15 verdict; this is annotation hygiene, not behavioral; static
test guards against re-introduction.

Use Conventional Commits + Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>.
```

---

## Stage 4 Codex Auto Review reminder

After each PR is merged-ready (CI green + manual QA), Codex Auto Review triggers automatically. P1 catches → standalone hotfix immediately. P2 catches → bundle into the next adjacent PR or terminus cleanup. Memory: `feedback_codex_review_integration.md` + `feedback_orchestrator_consumer_audit_gap.md`.
