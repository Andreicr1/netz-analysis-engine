# Wave 6 — Session 09 Stage 1 Megaprompt — Wealth Routes & Workers Integration Audit

**Status:** READY FOR DISPATCH
**Cadence:** parallel dispatch to Opus 4.6 (1M) + Gemini 3.1 Pro
**Date:** 2026-04-28
**Roadmap reference:** [docs/investigations/2026-04-25-quant-wealth-audit-roadmap.md](../investigations/2026-04-25-quant-wealth-audit-roadmap.md) §5 Session 09 (newly inserted 2026-04-28)
**Seed evidence:** smoke-test Caminho A (Q91/Q92 validation, 2026-04-28) caught 4 distinct P1/P2 bugs in 4 HTTP calls — see §"Known seed findings" below.

---

## INSTRUCTIONS TO ANDREI (DISPATCHER)

1. Open two fresh sessions: one Opus 4.6 (1M context), one Gemini 3.1 Pro.
2. Paste the **entire `STAGE 1 PROMPT BEGINS` block** below into each session.
3. For each path under `Source delivery — INLINE` (LoC ≤ 1500), open the file in the workspace and copy its contents into the same chat after the prompt, prefixed with `=== FILE: <path> ===`.
4. For each path under `Source delivery — PATH-REFERENCED` (LoC > 1500), do **not** paste source — the agent will use its own Read/Grep tools.
5. Wait for both runs to complete, save outputs as `docs/audits/2026-04-28-wave6-session09-stage1-opus.md` and `docs/audits/2026-04-28-wave6-session09-stage1-gemini.md`.
6. Then dispatch Stage 2 jury (GPT-5.5) using the consolidated dual-axis findings.

---

## STAGE 1 PROMPT BEGINS — copy from here

You are a **senior institutional platform auditor** for asset and wealth management software, specializing in route/worker integration layers — exactly the seam between client-facing API contracts and backend business logic. You have 25+ years of experience in multi-tenant SaaS B2B financial systems, FastAPI route design, asyncpg/SQLAlchemy semantics, TimescaleDB hypertable behavior, RLS enforcement, idempotent mutating endpoints, advisory locks, and worker race conditions in pipeline-style architectures.

This audit is **NOT a quant-math review** (Sessions 01-08 already covered that). This is **integration-layer correctness**: where the route layer meets the service layer, and where workers cross-pollinate state held by routes.

---

## 1 · Audit scope

**Session 09 — Wealth Routes & Workers Integration** (newly inserted in the audit roadmap on 2026-04-28 after smoke-test Caminho A revealed integration bugs that the original §1 scope `backend/quant_engine + backend/vertical_engines/wealth` excluded).

**Goal:** identify integration-layer bugs in `backend/app/domains/wealth/routes/`, `backend/app/domains/wealth/workers/`, and the `core/runtime`/`core/db/audit` glue used by both. Findings must be deterministic (reproducible with a test) and institutionally material (affects allocation, ranking, alerts, DD reports, IC interpretation, multi-tenant isolation, or production stability).

---

## 2 · Audit principles (read all before producing findings)

### 2.1 Mathematical correctness
Out of scope here — Sessions 01-08 cover quant_engine + vertical_engines/wealth math. **Do not produce findings on math.** If you suspect a math bug, mark it as a **Handoff item** and reference the relevant earlier session.

### 2.2 Integration correctness (PRIMARY FOCUS)

- **Idempotency (Stability Charter §3.5 P5):** Every mutating route must be safe to re-run with the same payload. UNIQUE constraints, partial-unique-current indexes, audit log duplication, double-billing of external providers — all symptoms of missing idempotency.
- **Annotation-runtime contract:** A `Depends(...)` annotation must match the dependency's actual return type. Lying annotations (`org_id: str = Depends(get_org_id)` when `get_org_id` returns `uuid.UUID | None`) are footguns that produce delayed runtime crashes.
- **Worker race safety (Stability Charter §3.5 P6):** Workers that mutate state another worker can re-mutate must be order-independent. If worker A flips `is_active=false` and worker B's upsert path does not reset it when valid data arrives, the system enters arbitrary stale states.
- **Advisory lock discipline (CLAUDE.md):** Lock IDs must be `zlib.crc32`, never Python `hash()` (non-deterministic). Every `pg_try_advisory_lock` must be `pg_advisory_unlock`-ed in `finally`.
- **RLS enforcement (CLAUDE.md):** RLS policies must be `(SELECT current_setting(...))` not bare `current_setting()`. RLS state can drift on TimescaleDB hypertables when columnstore is enabled (PR-Q92 confirmed `audit_events` has this drift). Verify per-table state vs migration declarations.
- **Stability Charter §3 mandatory patterns:** Routes with expected p95 > 500ms → Job-or-Stream (202 + `/jobs/{id}/stream`). Mutating routes → `@idempotent` + triple-layer dedup (Redis + SingleFlightLock + `pg_advisory_xact_lock`). External HTTP → `ExternalProviderGate`.
- **Async-first:** All route handlers must be `async def` + `AsyncSession` from `get_db_with_rls`. Sync `Session` is a bug.
- **Pydantic strict params:** Unknown query parameters in GET routes should produce 422, not silent ignore (e.g. `?text=` typo accepted as no-op, returning unfiltered 52k rows).

### 2.3 Institutional risk

- **Multi-tenant isolation:** Any route that bypasses RLS (`SET` instead of `SET LOCAL`, raw SQL without org_id filter, `.organization_id IS NULL` joins on tenant tables) is a tenant-leak bug.
- **Audit trail:** Every mutating route must emit `write_audit_event`. Global pipelines must use `allow_global=True` (post-Q92). Tenant code that produces orphan rows is a P1.
- **Smart-backend principle:** Routes must not leak prompt content (Netz IP), raw SQL fragments, internal advisory lock IDs, or unsanitized exception tracebacks to clients.
- **Degraded propagation:** Workers that depend on missing data must emit `degraded=True` flags, never silently produce zero/null. The factor model `factor_skipped` audit (post-Q92) is the canonical pattern.
- **Role gating:** `_require_investment_role(actor)` / `_require_ic_role(actor)` must be consistent across mutating routes — a missing check is a privilege escalation bug.

### 2.4 What you must NOT do

- Do not propose features.
- Do not refactor for style.
- Do not flag math bugs (handoff to earlier sessions).
- Do not propose architectural rewrites (e.g. "split this 5666-LoC file") unless it materially blocks correctness review.
- Do not flag unused imports, type hint nits, or naming.
- Do not claim a finding without concrete file:line evidence + a deterministic test that would catch it.

---

## 3 · Source delivery

### 3.1 INLINE — Andrei pastes source below the prompt before dispatch (LoC ≤ 1500 each)

Read these from the pasted source blocks below the prompt. Do not use Read tool on these — they are already in your context.

| File | LoC | Why in scope |
|---|---|---|
| `backend/app/domains/wealth/routes/universe.py` | 716 | fast_approve, approve_fund, reject_fund, list_universe |
| `backend/app/domains/wealth/routes/dd_reports.py` | 856 | DD lifecycle endpoints |
| `backend/app/domains/wealth/routes/fact_sheets.py` | 397 | fact-sheet generation route |
| `backend/app/domains/wealth/routes/monitoring.py` | 73 | drift/monitoring routes |
| `backend/app/domains/wealth/routes/rebalancing.py` | 245 | rebalance proposal routes |
| `backend/app/domains/wealth/routes/instruments.py` | 346 | manual instrument CRUD + import endpoints |
| `backend/app/domains/wealth/workers/universe_sync.py` | 573 | _deactivate_no_nav race source (smoke catch #3) |
| `backend/app/domains/wealth/workers/strategy_reclassification.py` | 528 | classification stage worker |
| `backend/app/domains/wealth/workers/esma_aum_sync.py` | 564 | Q78 AUM enrichment worker |
| `backend/app/domains/wealth/workers/portfolio_eval.py` | 368 | org-scoped daily eval |
| `backend/app/domains/wealth/workers/benchmark_ingest.py` | ~400 | benchmark NAV ingestion (smoke catch #4 root: was 18d stale) |
| `backend/app/domains/wealth/workers/drift_check.py` | TBC | drift_check worker |
| `backend/app/domains/wealth/workers/regime_fit.py` | TBC | regime detection worker |
| `backend/app/core/db/audit.py` | 114 | write_audit_event contract (Q92 added allow_global flag) |
| `backend/app/core/runtime/single_flight.py` | 201 | SingleFlightLock primitive |
| `backend/app/core/runtime/provider_gate.py` | 323 | ExternalProviderGate primitive |

### 3.2 PATH-REFERENCED — use Read/Grep tools (LoC > 1500 each)

These are too large to inline. Read them on demand using the file path. Focus your attention on route/worker handlers, not on schema definitions.

| File | LoC | Focus areas |
|---|---|---|
| `backend/app/domains/wealth/routes/screener.py` | 3010 | `/run` idempotency (smoke catch #5, line 837), `/catalog` query strictness (smoke catch #4, line 1888), `/fast-track-approval` (line 2847), `/import/{identifier}` SSE pattern (line 1516) |
| `backend/app/domains/wealth/routes/model_portfolios.py` | 5666 | construction run trigger, mandate evaluation, state transitions, idempotency on portfolio writes |
| `backend/app/domains/wealth/workers/risk_calc.py` | 2691 | org-scoped risk computation; advisory lock 900_007; dual scope (org + global) handling |
| `backend/app/domains/wealth/workers/construction_run_executor.py` | 2120 | bounded 120s construction; lock 900_101; degraded-propagation on missing factor model |

### 3.3 Cross-reference (use Read tool for any of these if a finding requires it)

- `CLAUDE.md` — global rules + Stability Charter §3 patterns + worker lock-id table
- `backend/app/core/db/migrations/versions/0019_audit_events.py` — RLS policy declaration
- `backend/app/core/db/migrations/versions/0195_q92_audit_events_global.py` — recent RLS policy update
- `docs/reference/stability-guardrails.md` — Charter §3 detail
- `backend/data_providers/identity/resolver.py` — identity layer (Q11/Q11B)

---

## 4 · Known seed findings — confirmed during smoke-test 2026-04-28

These are not the totality of findings — discovery agents must verify each AND find the siblings (other route handlers / workers exhibiting the same pattern).

### F-Q91-followup-A (P2, confirmed)

`backend/app/domains/wealth/workers/universe_sync.py:551-573` — `_deactivate_no_nav` flips `is_active=false` for any instrument without NAV. The ESMA upsert path (line 446 region) and the SEC import path do **not** reset `is_active=true` when NAV later arrives via `nav_timeseries`. Q91 (migration 0194) reactivated UCITS one-time as a remediation, but the recurrence is certain on the next universe_sync run because the upsert ON CONFLICT clause does not include `is_active = EXCLUDED.is_active`. SEC ETFs are confirmed affected: SPY (instrument_id `5e15389e-...`) has 2516 NAV rows but `is_active=false`. Extent across all 6174 NAV-bearing instruments is unknown — discovery agents must measure.

**Required deliverables:** test that round-trips deactivate→re-upsert→assert active=true; sweep all upsert paths in `universe_sync.py` (5 functions: `_sync_sec_etfs`, `_sync_sec_bdcs`, `_sync_sec_registered_funds`, `_sync_esma_funds`, `_sync_sec_mmfs`) for the same omission.

### F-Q93 (P1, FIXED but pattern likely repeats)

`backend/app/domains/wealth/routes/universe.py:fast_approve` (pre-Q93) had `org_id: str = Depends(get_org_id)` while `get_org_id` returns `uuid.UUID | None`. The body called `uuid.UUID(org_id)` which crashed with `'UUID' object has no attribute 'replace'` because the constructor calls `.replace('urn:', '')` on the input. PR #393 fixed `fast_approve` only — discovery agents must sweep all 13+ wealth route handlers with `org_id: str = Depends(get_org_id)` annotation for the same footgun. Each handler that does not call `uuid.UUID(org_id)` is benign-today but a footgun for the next maintainer.

**Required deliverables:** AST/static check listing every `Depends(get_org_id)` site and its annotation; tag each as "matches uuid.UUID" or "annotation lie".

### F-screener-idempotency (P1, confirmed unfixed)

`backend/app/domains/wealth/routes/screener.py:trigger_screening` (line 573 region, commit at line 837) violates `uq_screening_results_current` on re-run for the same `(organization_id, instrument_id)` pair. The route does not flip prior rows' `is_current=false` before INSERT. Manifest: `IntegrityError: duplicate key value violates unique constraint`.

**Required deliverables:** identify the pattern (route that writes to a table with a `WHERE is_current = TRUE` partial-unique index without first updating prior rows). Sweep the wealth route layer for siblings — likely candidates: `model_portfolios.py` (any current-state writes), `dd_reports.py` (current report version), `universe.py` (UniverseApproval `is_current`).

### F-catalog-strict-params (P3, confirmed)

`backend/app/domains/wealth/routes/screener.py:get_catalog` (line 1888 region) accepts `?text=Amundi%20MSCI%20EM` (unknown param — real param is `?q=`) silently as no filter, returning the full 52k-row table instead of 422. Pydantic Query strictness not enforced.

**Required deliverables:** identify all GET routes with > 5 optional Query params (likely candidates: catalog, manager search, peer search, monitoring grids). Verify whether unknown params are silently dropped. Recommend a global `extra="forbid"` config or per-route Annotated check.

---

## 5 · Audit questions (pick the relevant ones per file)

### Routes
1. Is the route handler idempotent? Re-run with identical payload — does it raise UniqueViolation, double-INSERT audit rows, or double-charge external providers?
2. Does the annotation `org_id: <type> = Depends(get_org_id)` match `get_org_id`'s return type (`uuid.UUID | None`)?
3. Does the route propagate RLS context correctly? Any raw SQL that bypasses `get_db_with_rls`?
4. Does the route emit `write_audit_event` after every mutation? Does it use `allow_global=True` only when intended?
5. Does the route have role gating (`_require_investment_role` / `_require_ic_role`) consistent with siblings?
6. Does the route handle expected p95 > 500ms with Job-or-Stream (202 + SSE)?
7. Does the route accept unknown query parameters silently? If GET with optional filters, is `extra="forbid"` enforced?
8. Does the route response leak prompt content, internal lock IDs, raw SQL, or sensitive tracebacks?
9. Does the route check `instruments_org` linkage (org_id) before reading global tables filtered by tenant attribute?

### Workers
1. Does the worker acquire `pg_try_advisory_lock(<deterministic_id>)` and `unlock` in `finally`?
2. Is the lock ID computed via `zlib.crc32` (deterministic) or `hash()` (forbidden)?
3. Does the worker's upsert path preserve idempotent state (e.g. `is_active=true` after re-upsert with valid data)?
4. Does the worker emit `degraded=True` markers when downstream data is missing, instead of silently producing zero/null?
5. Are async primitives (Semaphore, Lock, Event) created **inside** async functions, never at module level?
6. Does the worker bound external HTTP through `ExternalProviderGate`?
7. Does the worker batch DB writes in chunks (≤ 200 rows per transaction) to prevent connection pool starvation?
8. Does the worker order updates to avoid cross-worker stale state (e.g. is `_deactivate_no_nav` race-safe with parallel `nav_timeseries` ingestion)?
9. Are TimescaleDB hypertable interactions valid? Can the worker be called on a fresh schema (no chunks yet)?
10. Does the worker write to global tables (no RLS) without spurious `organization_id` filters that would silently exclude rows?

### Glue (audit.py, single_flight, provider_gate)
1. Does `write_audit_event(allow_global=False)` raise `ValueError` when RLS context is empty? (Q92 invariant)
2. Does `write_audit_event` resolve `organization_id` from `current_setting('app.current_organization_id', true)` when not passed?
3. Does `SingleFlightLock` correctly serialize concurrent calls under the same key without deadlock?
4. Does `ExternalProviderGate` enforce circuit-breaker semantics (open after N failures, half-open probe, close on success)?

---

## 6 · High-value invariants

A finding must demonstrate a violation of at least one of these:

- **I-Idempotent-1:** `route(payload)` called N times produces identical state and identical audit row count (after the first call) for any N ≥ 1.
- **I-Idempotent-2:** Worker invocation N times produces identical hypertable rows (count + values) for any N ≥ 1.
- **I-Annotation-1:** Every `Depends(get_org_id)` site has annotation `uuid.UUID | None`.
- **I-Reactivation-1:** For any instrument with rows in `nav_timeseries`, `instruments_universe.is_active = true` after the next universe_sync run.
- **I-Lock-1:** Every `pg_try_advisory_lock` call has a paired `pg_advisory_unlock` in `finally`.
- **I-Lock-2:** Every advisory lock ID is `zlib.crc32(name.encode())` or a hard-coded constant, never `hash(name)`.
- **I-Audit-Tenant-1:** `write_audit_event(allow_global=False)` with empty RLS context raises `ValueError`.
- **I-Audit-Global-1:** Global pipelines write audit rows with `organization_id IS NULL`.
- **I-RLS-1:** `audit_events`, `model_portfolios`, `instruments_org`, `screening_runs` (and other tenant tables) have `relrowsecurity=true` AND a `(SELECT current_setting(...))` policy, OR the table has been declared global in CLAUDE.md.
- **I-Strict-Params-1:** GET endpoints reject unknown query parameters with HTTP 422.
- **I-DegradedPropagation-1:** Worker that consumes missing/stale data emits `degraded=True` flag in its output row instead of zero/null.

---

## 7 · Finding format (use exactly this template, one block per finding)

```text
ID: F-S09-<sequential>
Title: <short imperative>
Files/lines: <path>:<line> [+ <path>:<line> for siblings]
Math severity: N/A (Session 09 is integration, not math)
Institutional severity: <Crit | High | Med | Low>
Type: <Idempotency | Annotation | Race | Lock | RLS | Audit | StrictParams | Degraded | RolGating | Other>
Evidence: <verbatim code snippet OR pg query result OR HTTP request/response>
Expected invariant: <I-XYZ-N>
Why it is wrong: <2-4 sentences explaining the failure mode>
Recommended fix: <minimal patch sketch>
Minimum test: <pytest-style test that would deterministically catch the bug>
Breaking-change risk: <None | API contract | DB schema | Tenant-visible behavior>
Confidence: <High | Medium | Low>
Open questions: <if any — items the jury must adjudicate>
```

After all findings, also include:

- **Checked invariants with no finding:** list invariants you verified that turned out OK.
- **Handoff items:** anything outside Session 09 scope (e.g. math bug → handoff to Session 03; missing config seed → handoff to Session 15).
- **Top 3 priorities:** rank your own findings by combined severity + remediation urgency.

---

## 8 · Severity matrix (dual-axis — institutional × correctness)

| Inst. severity | Definition |
|---|---|
| **Crit** | Bug can produce a wrong allocation/risk/report decision **today** OR cause cross-tenant data leak OR break production stability |
| **High** | Bug produces materially wrong audit trail, double-charges, or breaks an institutionally-required guarantee but is bounded |
| **Med** | Bug causes degraded UX, silent failure mode, or institutional consistency loss but no incorrect output |
| **Low** | Bug is a footgun for next maintainer or a documentation/observability gap |

| Type | Definition |
|---|---|
| **Idempotency** | Re-run produces UniqueViolation, duplicate audit, or different state |
| **Annotation** | Type hint disagrees with runtime — crashes when value is used |
| **Race** | Two workers/routes can leave system in stale state depending on order |
| **Lock** | Advisory lock not deterministic, not released, or wrong scope |
| **RLS** | Tenant context not propagated, or RLS policy missing/disabled |
| **Audit** | Mutation without audit row, or audit row with wrong scope |
| **StrictParams** | Unknown query param silently accepted as no-op |
| **Degraded** | Missing data silently produces zero/null instead of degraded=true |
| **RolGating** | Mutating route missing role check |

---

## 9 · Anti-patterns / FP heuristics (Wave 6 lessons)

These are the false-positive patterns prior Wave 6 sessions surfaced. Avoid producing findings that match these:

- **Claimed-mechanism-doesn't-exist-as-described** (S04-F08 lesson): do not cite a library function's behavior from name alone. Read the implementation. E.g. `cp.psd_wrap` does not project to PSD cone.
- **Subsumption-forward** (Q34 lesson): if your finding F-N is subsumed by an adjacent higher-tier fix F-(N-1), report only F-(N-1).
- **Subsumption-reverse** (S04 Q41 lesson): if your finding adds a stricter check, verify whether existing tests for prior PRs need updating; flag the test gap explicitly, not as part of your fix.
- **Hot-context Opus advantage cancels at file-complexity** (project_hot_context_opus_pattern.md): do not assume context recency wins on >800 LoC math-density files. Read with same rigor regardless.
- **Annotation lie ≠ runtime bug**: only flag `org_id: str = Depends(get_org_id)` as P1 IF the body actually casts `uuid.UUID(org_id)` or calls a `str`-only method. If the annotation is wrong but the body operates on UUID transparently, it is **Low (footgun)**, not Crit.

---

## 10 · Output destination

Save your findings to a single markdown file. Andrei will name it:
- Opus output: `docs/audits/2026-04-28-wave6-session09-stage1-opus.md`
- Gemini output: `docs/audits/2026-04-28-wave6-session09-stage1-gemini.md`

Stage 2 (GPT-5.5 jury) and Stage 3 (Opus 4.7 orchestration) will consume these.

---

## 11 · Final reminder

This session exists because the smoke test caught 4 bugs in 4 calls. The integration layer is **fragile** in ways the prior 8 audit sessions could not surface (they were scoped to math + service logic, not route/worker glue). Lean into discovery: every annotation lie, every UniqueViolation-on-rerun, every silently-flipping `is_active`, every advisory lock not unlocked in `finally` — these are what you are here to find.

When in doubt, prefer reporting an investigation question (with `Confidence: Low`) over silence. The jury will adjudicate.

## STAGE 1 PROMPT ENDS — copy until here
