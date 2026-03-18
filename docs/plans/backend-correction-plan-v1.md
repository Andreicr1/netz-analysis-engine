# Backend Correction Execution Backlog

## Global Deployment Guardrails

- [ ] No high-risk task reaches full production rollout before staging validation, production canary, and rollback verification are complete.
- [ ] All route, worker, config, schema, and search-index changes must be protected by checked-in tests and a deploy-time manifest or audit script.
- [ ] Legacy-path deletion is blocked until production telemetry shows zero live traffic on the deprecated path for at least 14 consecutive days.
- [ ] Search and pipeline cutovers must use canary promotion with environment-scoped configuration so rollback is a configuration change first and a code revert second.
- [ ] Any task that changes failure semantics from silent fallback to explicit degraded or failed state must run in shadow-observe mode first when feasible, so downstream breakage is measured before enforcement.

## Global Observability Checkpoints

- [ ] Job lifecycle telemetry exists for `queued`, `running`, `success`, `degraded`, `failed`, and `abandoned` states with `job_id`, `dispatch_mode`, `pipeline_name`, and `duration_ms`.
- [ ] Search telemetry exists for resolved index name, attempted chunk count, successful chunk count, failed chunk count, and ingestion-to-search freshness lag.
- [ ] Authorization telemetry exists for actor type, fund access decision, route family, and denial reason without leaking sensitive identities.
- [ ] Configuration telemetry exists for config type, source chain, resolved source, missing state, and parse-failure reason.
- [ ] Startup telemetry exists for loaded route manifests, worker manifests, optional-module degradation, and selected runtime backends.

## Workstream: canonical-path

- [x] `CP-01` Align route and worker manifests with the mounted runtime surface _(deps now satisfied: AUTH-01 ✓, CP-02 ✓, SRCH-01 ✓)_
  **Description:** Replace hand-maintained route and worker descriptions with canonical manifests generated from FastAPI startup and worker registration. Update the system map only after runtime surfaces are stable so route, worker, and topology documentation match deployed code exactly.
  **Files/modules:** `backend/app/main.py`, `backend/app/domains/admin/routes/*.py`, `backend/app/domains/credit/*/routes/*.py`, `backend/app/domains/wealth/routes/workers.py`, `backend/app/domains/wealth/workers/*.py`, `docs/audit/backend-system-map-v1.md`
  **Dependencies:** `AUTH-01`, `CP-02`, `SRCH-01`
  **Acceptance criteria (testable):**
  1. CI-generated route inventory is byte-for-byte equal to the checked-in route manifest.
  2. CI-generated worker inventory is byte-for-byte equal to the checked-in worker manifest.
  3. No documented admin, credit, or worker path exists without a mounted handler, and no mounted handler is absent from the manifests.
  4. `/run-cvar` is absent from the runtime worker manifest unless intentionally implemented and tested.
  **Rollback strategy:** Revert only the manifest and documentation commit; do not revert runtime behavior. If manifest generation blocks deployment unexpectedly, temporarily gate the doc-contract check while preserving the generated artifact for investigation.
  **Deployment guardrails:** Run manifest generation in CI and staging before merging documentation updates. Block production deploy if manifests differ from runtime inventory.
  **Observability checkpoints:** Startup log includes manifest hash, route count, worker count, and selected dispatch topology. Alert on manifest hash drift between staging and production for the same release candidate.
  **Risk level:** Medium

- [x] `CP-02` Retire `extraction_orchestrator` from production dispatch and standardize on `unified_pipeline`
  **Description:** Remove the deprecated extraction orchestrator from all production dispatch paths so extraction, persistence, and indexing run only through the canonical `unified_pipeline` path. Keep legacy code unreachable before physical deletion.
  **Files/modules:** `backend/app/services/azure/pipeline_dispatch.py`, `backend/ai_engine/extraction/extraction_orchestrator.py`, `backend/ai_engine/pipeline/unified_pipeline.py`
  **Dependencies:** `CP-03`
  **Acceptance criteria (testable):**
  1. Integration tests covering all supported extraction dispatch entrypoints prove that production dispatch invokes `unified_pipeline` and never invokes `extraction_orchestrator`.
  2. Production runtime code contains no reachable import or call edge from dispatch code to `extraction_orchestrator`.
  3. Canary extraction jobs persist artifacts to the canonical ADLS path and search documents to the env-prefixed canonical index path only.
  4. A static import guard fails CI if `extraction_orchestrator` becomes reachable from a production module.
  **Rollback strategy:** Re-enable the previous dispatch target behind an environment flag if canonical pipeline execution regresses in canary. Preserve the legacy module and deployment switch until 14 days of zero production legacy invocations are observed.
  **Deployment guardrails:** Roll out behind a configuration gate in staging first, then canary only for low-volume extraction jobs. Do not delete the legacy module or its config until rollback has been exercised successfully in non-production.
  **Observability checkpoints:** Emit per-job `pipeline_name`, `dispatch_mode`, `storage_target`, `search_index_name`, and `legacy_path_invoked`. Alert immediately on any production event indicating `legacy_path_invoked=true`.
  **Risk level:** High

- [x] `CP-03` Remove credit-specific import-time coupling from `ai_engine`
  **Description:** Refactor `backend/ai_engine` so core package imports do not hard-bind to `vertical_engines.credit` at import time. Vertical resolution must be explicit through a registry or selector layer.
  **Files/modules:** `backend/ai_engine/__init__.py`, `backend/ai_engine/profile_loader.py`, `backend/vertical_engines/*`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Importing `backend.ai_engine` without loading credit-specific runtime dependencies does not fail.
  2. Vertical selection occurs only through an explicit registry or selector exercised by unit tests for valid and invalid vertical identifiers.
  3. Import-time side effects do not initialize credit-specific services unless the selector requests them.
  **Rollback strategy:** Revert the registry wiring to the previous import path if package import regressions appear, while keeping the new import tests to localize the failure. Do not combine this rollback with pipeline cutover rollback unless the selector change is the root cause.
  **Deployment guardrails:** Ship this refactor before `CP-02`. Block pipeline cutover if registry or import tests fail in staging.
  **Observability checkpoints:** Startup log reports selected vertical registry entries and selector resolution failures. Alert on import-time exceptions or selector fallthrough.
  **Risk level:** Medium

- [x] `CP-04` Consolidate deep review lifecycle state transitions into one coherent orchestration path _(dep satisfied: FAIL-01 ✓)_
  **Description:** Refactor deep review dispatch so execution, success finalization, and failure finalization use deterministic lifecycle semantics with explicit transactional boundaries instead of unrelated DB sessions that can leave stale state.
  **Files/modules:** `backend/app/services/azure/pipeline_dispatch.py`, `backend/vertical_engines/credit/deep_review/service.py`, `backend/app/core/db/session.py`
  **Dependencies:** `FAIL-01`
  **Acceptance criteria (testable):**
  1. Failure injection after artifact persistence but before status publication cannot leave the job in a stale-running state.
  2. Success path writes exactly one terminal success state with completion timestamp and no ambiguous later overwrite.
  3. Failure path writes exactly one terminal failed or degraded state with preserved reason code.
  4. Integration tests cover success, failure, and retry boundaries using the refactored lifecycle.
  **Rollback strategy:** Revert the lifecycle refactor and restore prior dispatch behavior if final-state publication breaks critical deep review workflows. Preserve the new failure-injection tests to confirm the original bug before reattempting.
  **Deployment guardrails:** Deploy only after job-state reconciliation tests and canary deep review runs complete successfully. Block rollout if stale-running jobs or duplicate terminal writes are detected in staging.
  **Observability checkpoints:** Emit transition events with transaction stage, prior status, next status, and reconciliation outcome. Alert on terminal-state rewrites, stale-running age threshold breaches, and artifact/status mismatches.
  **Risk level:** Medium

## Workstream: search

- [x] `SRCH-01` Cut ingestion, rebuild, and Copilot retrieval to one env-prefixed canonical index
  **Description:** Eliminate the live split between canonical ingestion and retrieval by resolving ingestion, rebuild, and Copilot paths to one environment-scoped index contract. Retain the legacy v4 index only as a rollback target until cutover is proven stable.
  **Files/modules:** `backend/ai_engine/extraction/search_upsert_service.py`, `backend/app/services/azure/pipeline_kb_adapter.py`, `backend/ai_engine/pipeline/search_rebuild.py`, `backend/app/core/config/settings.py`
  **Dependencies:** `CP-02`
  **Acceptance criteria (testable):**
  1. Ingestion, rebuild, and Copilot retrieval resolve to the same env-prefixed index name in integration tests and startup diagnostics.
  2. Static checks and runtime config inspection confirm that no production code path contains a hardcoded v4 index reference.
  3. A canary document ingested through the canonical path becomes retrievable through Copilot from the canonical index within the documented freshness window.
  4. Read/write index divergence tests fail CI if any path resolves a non-canonical index name.
  **Rollback strategy:** Switch retrieval and rebuild resolution back to the previously active index configuration while preserving canonical writes if partial rollback is required. Keep the legacy v4 index populated until production read/write telemetry is clean for 14 consecutive days.
  **Deployment guardrails:** Perform staging shadow reads comparing canonical and legacy retrieval results before canary. Do not delete or repurpose the legacy index until rollback verification and freshness validation are complete.
  **Observability checkpoints:** Emit resolved index name on every ingestion, rebuild, and retrieval operation; track freshness lag and divergence counts. Alert on any production v4 read/write after cutover begins.
  **Risk level:** High

- [x] `SRCH-02` Remove or replace live stub usage of `AzureSearchMetadataClient`
  **Description:** Eliminate production paths that call the unimplemented metadata client. Either implement supported metadata access against the canonical search client or remove the dependent routes and workers from the live surface.
  **Files/modules:** `backend/app/services/azure/search_client.py`, `document_scanner.py`, `obligation_extractor.py`, `knowledge_builder.py`
  **Dependencies:** `SRCH-01`
  **Acceptance criteria (testable):**
  1. No enabled production route, worker, or pipeline path imports or invokes an unimplemented `AzureSearchMetadataClient`.
  2. Every retained metadata-dependent caller passes integration tests against the supported canonical search client.
  3. Static reference checks fail CI if a production path reintroduces stub-only metadata behavior.
  **Rollback strategy:** If a supported implementation regresses, disable only the affected metadata-dependent surface and leave the rest of search cutover intact. If removal causes unacceptable feature loss, revert the route or worker removal and restore the prior caller set temporarily.
  **Deployment guardrails:** Enumerate current live callers before any code change. Do not merge a partial migration that leaves mixed stub and supported implementations in production.
  **Observability checkpoints:** Emit caller-level metrics for metadata lookup attempts, successes, failures, and backend client selection. Alert on any runtime call into the stub implementation.
  **Risk level:** Medium

- [ ] `SRCH-03` Convert partial indexing failure into an explicit degraded terminal state
  **Description:** Stop treating chunk-level search write failures as log-only events. Persist degraded or failed terminal state with enough retry and rebuild metadata for operators and clients to distinguish full success from partial persistence.
  **Files/modules:** `backend/ai_engine/extraction/search_upsert_service.py`, `backend/app/core/jobs/tracker.py`, pipeline status and event publishers
  **Dependencies:** `CP-04`
  **Acceptance criteria (testable):**
  1. Any batch upload exception or partial chunk failure yields terminal job state `degraded` or `failed`, never `success`.
  2. Persisted job state and emitted events include `attempted_chunk_count`, `successful_chunk_count`, `failed_chunk_count`, and retryability.
  3. Failure-injection tests prove that clients can distinguish full persistence from partial persistence without inspecting logs.
  **Rollback strategy:** Revert the status-model change if downstream consumers cannot yet handle degraded states, but keep failure telemetry and shadow emission enabled so compatibility gaps are visible before the next rollout attempt.
  **Deployment guardrails:** Introduce degraded-state handling behind a compatibility flag if external consumers assume binary success or failure. Block rollout if consumers crash on `degraded`.
  **Observability checkpoints:** Emit chunk-level write counters and terminal status counts; alert on any `success` event with `failed_chunk_count > 0`.
  **Risk level:** Medium

## Workstream: failure-semantics

- [x] `FAIL-01` Make AI router assembly fail fast or enter explicit degraded startup
  **Description:** Replace broad exception swallowing during AI sub-router assembly with strict handling for required modules and explicit degraded startup reporting for truly optional modules.
  **Files/modules:** `backend/app/domains/credit/modules/ai/__init__.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Injecting an import failure into a required AI sub-router causes startup failure or explicit degraded health status naming the missing module.
  2. Startup diagnostics expose the loaded AI sub-router set, and tests fail if it silently shrinks.
  3. No required router can disappear while startup still reports fully healthy status.
  **Rollback strategy:** Revert to the prior assembly code only if strict startup behavior blocks emergency operations, but retain structured degraded logging in the rollback branch so silent disappearance does not return unobserved.
  **Deployment guardrails:** Deploy first to staging with synthetic import-failure tests. Block production rollout if startup health, route inventory, and router-load report disagree.
  **Observability checkpoints:** Emit module-load report listing required, optional, and degraded modules. Alert on missing required modules or unexpected route-count reduction.
  **Risk level:** Medium

- [ ] `FAIL-02` Introduce typed degraded states for classification, extraction, summary, and OCR fallback paths
  **Description:** Ensure upstream outages and low-quality fallback paths remain distinguishable from legitimate empty or low-signal business outputs throughout persistence, indexing, and retrieval.
  **Files/modules:** `backend/ai_engine/extraction/document_intelligence.py`, `backend/ai_engine/extraction/text_extraction.py`
  **Dependencies:** `SRCH-03`
  **Acceptance criteria (testable):**
  1. Persisted extraction metadata and job events contain typed reason codes for service outage, parse failure, summary failure, OCR fallback, and legitimately empty document.
  2. Downstream indexing can exclude degraded outputs or include them only with an explicit degraded marker.
  3. Pipeline tests prove degraded extraction outputs cannot be stored as indistinguishable normal-success records.
  **Rollback strategy:** If downstream features cannot yet consume degraded markers, fall back to shadow-only degraded emission while preserving the previous external payload shape. Do not remove the reason-code instrumentation during rollback.
  **Deployment guardrails:** Enable in shadow mode first for production workloads and review degraded-rate impact before making the new semantics externally authoritative.
  **Observability checkpoints:** Emit reason-coded counters for classifier failures, metadata failures, summary failures, OCR fallback usage, and degraded document suppression or admission. Alert on degraded outputs entering the searchable corpus without markers.
  **Risk level:** Medium

- [x] `FAIL-03` Stop encoding quant drift computation failures as neutral values
  **Description:** Replace `0.0` and zero-filled sentinel outputs on DTW failure with explicit failure or degraded semantics so downstream consumers cannot confuse computation failure with valid low-risk output.
  **Files/modules:** `backend/quant_engine/drift_service.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Forced DTW failure returns a typed failure or degraded result and never serializes as `0.0` or a zero-filled vector.
  2. Consumer tests prove computed zero drift and computation failure are distinguishable by schema or status field.
  3. Failure-path tests cover API, service, and dashboard-facing adapters.
  **Rollback strategy:** Revert only the external contract change if a downstream consumer cannot parse degraded results, but keep internal failure metrics and a compatibility adapter until consumer remediation lands.
  **Deployment guardrails:** Inventory all downstream consumers before rollout. Block production release if any consumer hard-requires unconditional numeric output and lacks fallback handling.
  **Observability checkpoints:** Emit drift computation attempts, failures, degraded returns, and consumer adaptation errors. Alert on any neutral numeric sentinel emitted after an internal computation exception.
  **Risk level:** Medium

## Workstream: authorization

- [x] `AUTH-01` Harden global admin surfaces and publish the exact actor-resolution contract
  **Description:** Enforce `require_super_admin` on branding and assets endpoints and make the three-path actor-resolution order explicit in code-adjacent documentation and tests.
  **Files/modules:** `backend/app/domains/admin/routes/branding.py`, `backend/app/domains/admin/routes/assets.py`, `backend/app/core/security/admin_auth.py`, `backend/app/core/security/clerk_auth.py`, `docs/audit/backend-system-map-v1.md`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Anonymous requests receive auth failure and authenticated non-super-admin requests receive insufficient-privilege failure for every branding and assets route.
  2. Super-admin requests retain the expected success status codes and payload shapes.
  3. Unit tests prove actor-resolution precedence is exactly `X-DEV-ACTOR`, static development token, then Clerk JWT.
  4. Production deployment guidance marks development-only actor paths as unsupported outside development.
  **Rollback strategy:** Revert the router dependency change if internal operational tooling is blocked unexpectedly, while preserving the auth test matrix and documentation update. If precedence documentation is wrong, revert documentation only, not runtime auth order.
  **Deployment guardrails:** Run auth matrix tests for anonymous, non-admin, admin, and super-admin actors before merge. Require sign-off from owners of internal tooling that uses branding or assets routes.
  **Observability checkpoints:** Emit authorization-denial counts by route family and actor class. Alert on sharp increase in denied requests for branding or assets after rollout.
  **Risk level:** Medium

- [x] `AUTH-02` Resolve authoritative fund membership into `Actor.fund_ids`
  **Description:** Populate actor fund scope from the authoritative membership source before authorization checks so non-admin fund access is enforced based on real membership rather than an always-empty list.
  **Files/modules:** `backend/app/core/security/clerk_auth.py`, consumers of `require_fund_access()`, authoritative membership persistence layer
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Actor resolution populates `fund_ids` whenever a non-admin actor has valid fund membership.
  2. Integration tests for representative fund-scoped routes prove success for authorized fund `A` and denial for unauthorized fund `B`.
  3. Role-matrix tests prove admin and super-admin bypass remains explicit and not inferred from empty memberships.
  **Rollback strategy:** Disable the new membership enforcement path behind a feature flag if production denial rates spike unexpectedly, while keeping membership resolution telemetry active. Preserve the previous authorization behavior temporarily only for rollback; do not delete the new membership source integration.
  **Deployment guardrails:** Run in observe-only mode first by computing and logging expected membership decisions without enforcing them. Promote to enforcement only after staging and canary denial rates match expectations.
  **Observability checkpoints:** Emit membership resolution hit rate, empty-membership rate, allow or deny counts by route family, and denial reason. Alert on sudden denial-rate increase for non-admin fund users after enforcement.
  **Risk level:** High

- [x] `AUTH-03` Enforce global-table isolation beyond route-level discipline _(dep satisfied: AUTH-01 ✓)_
  **Description:** Prevent accidental read or write access to global-effect tables through tenant-scoped dependencies by adding explicit privileged data-path controls, guardrails, and tests.
  **Files/modules:** `backend/app/core/tenancy/admin_middleware.py`, `backend/app/core/tenancy/middleware.py`, `backend/app/core/db/migrations/versions/*.py`, consumers of `macro_data`, `allocation_blocks`, and `vertical_config_defaults`
  **Dependencies:** `AUTH-01`
  **Acceptance criteria (testable):**
  1. Integration tests prove tenant-scoped authenticated sessions using non-admin dependencies cannot read or write the identified global tables.
  2. Explicit admin-mode paths retain the minimum required access and continue to pass integration coverage.
  3. CI fails if a route or repository path introduces global-table access through a non-admin dependency without explicit allowlisting.
  **Rollback strategy:** Revert the restrictive guard or migration if a critical admin workflow is blocked unexpectedly, but preserve the misuse detection tests so the access gap remains visible. Restore only the minimum path required to recover operations.
  **Deployment guardrails:** Validate with staging admin workflows and negative tenant-access tests before rollout. Block deployment if any privileged workflow lacks a verified access path after hardening.
  **Observability checkpoints:** Emit global-table access attempts with caller mode and table name. Alert on non-admin access attempts and denied writes to global tables.
  **Risk level:** Medium

- [x] `AUTH-04` Normalize tenant-table RLS policy coverage and audit it continuously
  **Description:** Remove historical ambiguity around partial RLS policy coverage by auditing every tenant-scoped table for complete `USING` and `WITH CHECK` semantics on both fresh and upgraded schemas.
  **Files/modules:** `backend/app/core/db/migrations/versions/0001_foundation.py`, `backend/app/core/db/migrations/versions/0010_tenant_asset_slug_rls_fix.py`, `backend/app/core/db/migrations/versions/0015_admin_rls_bypass.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. A repeatable schema audit script confirms RLS enabled plus expected `USING` and `WITH CHECK` coverage for every tenant-scoped table on a fresh migration build.
  2. The same audit script passes on an upgraded schema built from historical migrations.
  3. CI fails if any tenant-scoped table is missing expected policy coverage.
  **Rollback strategy:** Revert only the latest migration or policy change if the audit exposes incompatibility in production-like data. Keep the audit in CI so rollback does not reintroduce silent policy drift.
  **Deployment guardrails:** Run migration rehearsal on a production-like snapshot before deploy. Block rollout if the audit differs between fresh and upgraded databases.
  **Observability checkpoints:** Emit migration-audit results and table counts at deploy time. Alert on policy-audit failures in staging or production migration rehearsal.
  **Risk level:** Medium

## Workstream: async-runtime

- [ ] `ASYNC-01` Preserve SSE ownership and reconnect authorization for long-running jobs
  **Description:** Refresh or redesign job ownership lifecycle so long-running jobs remain stream-authorizable beyond the current one-hour TTL while preserving cleanup after completion or abandonment.
  **Files/modules:** `backend/app/core/jobs/tracker.py`, `backend/app/core/jobs/sse.py`, job-producing dispatchers
  **Dependencies:** `CP-04`
  **Acceptance criteria (testable):**
  1. A time-travel or integration test proves that a job running longer than one hour remains stream-authorizable across reconnect attempts until terminal state.
  2. Active jobs refresh ownership TTL before expiration and terminal jobs clear ownership state within the bounded cleanup window.
  3. Reconnect attempts after the original TTL boundary succeed for active jobs and fail for terminal jobs.
  **Rollback strategy:** Revert TTL-refresh behavior if it causes runaway ownership retention, but keep reconnect authorization metrics enabled. If needed, reduce refresh cadence or cap renewal duration rather than reverting to fixed one-hour expiry immediately.
  **Deployment guardrails:** Deploy after synthetic long-running job tests and canary deep review runs. Block rollout if owner-key cleanup fails or stale ownership count grows in staging.
  **Observability checkpoints:** Emit owner-key TTL refresh count, refresh failures, reconnect denials, running-job age, and orphaned ownership count. Alert when active jobs approach expiry without successful refresh.
  **Risk level:** Medium

- [x] `ASYNC-02` Remove blocking HTTP from async FRED handlers
  **Description:** Replace synchronous `requests.get()` calls inside async request handlers with async HTTP client usage or explicit thread offload plus bounded timeout and cancellation semantics.
  **Files/modules:** `backend/app/domains/credit/dashboard/routes.py`, shared FRED client abstraction
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Concurrency tests with deliberately slow upstream FRED responses prove unrelated async requests complete within the normal latency budget.
  2. Static inspection and tests confirm no direct blocking HTTP call remains inside the async handler body.
  3. Timeout and cancellation behavior are explicit and covered by tests.
  **Rollback strategy:** Revert to the prior HTTP client path if the async integration introduces correctness regressions, but retain the concurrency benchmark to measure the regression before reattempting.
  **Deployment guardrails:** Verify connection pooling, timeouts, and cancellation semantics in staging under load before production rollout.
  **Observability checkpoints:** Emit upstream latency, timeout count, cancellation count, and event-loop blocking warnings. Alert on request-starvation patterns under slow upstream conditions.
  **Risk level:** Low

- [x] `ASYNC-03` Align DD report concurrency contract with actual implementation
  **Description:** Resolve the mismatch between documented parallel chapter generation and actual sequential execution by either implementing safe bounded parallelism or correcting the documented contract to sequential behavior.
  **Files/modules:** `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Implementation, docstrings, and runbook all declare the same chapter-generation mode.
  2. If sequential mode is retained, tests prove only one chapter-generation task is in flight at a time.
  3. If parallel mode is implemented, tests prove bounded concurrency and deterministic output ordering.
  **Rollback strategy:** If a new parallel implementation introduces nondeterminism, revert to explicit sequential execution and update documentation immediately. If documentation-only alignment proves insufficient, schedule performance work separately.
  **Deployment guardrails:** Do not combine a new concurrency model with unrelated report-generation changes in the same release.
  **Observability checkpoints:** Emit chapter-generation duration, concurrent task count, and output ordering validation failures. Alert on concurrency above the configured cap.
  **Risk level:** Low

- [x] `ASYNC-04` Normalize `PgNotifier` callback execution for sync and async handlers
  **Description:** Make notification dispatch explicit and deterministic for both sync and async handlers so future async callbacks do not create unawaited coroutines or silent invalidation failures.
  **Files/modules:** `backend/app/core/config/pg_notify.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Unit tests with sync and async handlers prove each notification invokes the handler exactly once with the expected payload.
  2. Test execution produces no unawaited-coroutine warnings.
  3. Handler failure semantics are explicit and surfaced to logs or metrics rather than silently ignored.
  **Rollback strategy:** Revert to sync-only callback dispatch if async handler support destabilizes notification processing, while keeping the warning and failure telemetry in place.
  **Deployment guardrails:** Validate with synthetic sync and async handlers in staging before enabling broader callback usage.
  **Observability checkpoints:** Emit notification count, handler duration, handler failure count, and coroutine-warning count. Alert on dropped notification processing.
  **Risk level:** Low

## Workstream: config

- [x] `CFG-01` Distinguish required config miss from valid empty config _(deps now satisfied: CFG-03 ✓, CFG-04 ✓)_
  **Description:** Replace the current `{}`-on-miss behavior with explicit required-versus-optional config semantics so missing required configuration fails deterministically and optional config misses remain modeled intentionally.
  **Files/modules:** `backend/app/core/config/config_service.py`, `backend/ai_engine/profile_loader.py`, config consumers across engines
  **Dependencies:** `CFG-03`, `CFG-04`
  **Acceptance criteria (testable):**
  1. For every required config type, combined DB miss and YAML miss yields typed configuration failure and blocks normal success execution.
  2. For every optional config type, miss behavior is represented explicitly as optional or missing state and emits structured warning telemetry.
  3. No required-config caller can receive a plain `{}` that is indistinguishable from a valid empty config.
  **Rollback strategy:** Downgrade required-config failures to shadow-only error emission if production reveals unmanaged config gaps, but keep missing-config telemetry and per-caller inventory active. Restore permissive behavior only temporarily and only for the affected config types.
  **Deployment guardrails:** Run in observe-only mode first by logging required-config misses without enforcing failure. Promote to enforcement only after staging and canary show no unexpected required-config gaps.
  **Observability checkpoints:** Emit `config_type`, `lookup_sources_attempted`, `resolved_source`, and `result_state` for every lookup. Alert on required-config misses and callers continuing after required-config failure.
  **Risk level:** High

- [x] `CFG-02` Eliminate module-level capture of runtime-critical environment variables
  **Description:** Move environment-derived runtime configuration out of module globals and into `Settings` or explicit initialization boundaries so configuration changes are governed by documented process restart semantics.
  **Files/modules:** `backend/ai_engine/governance/policy_loader.py`, `backend/ai_engine/extraction/extraction_orchestrator.py`, `backend/ai_engine/prompts/registry.py`, `backend/vertical_engines/credit/deep_review/models.py`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Static inspection finds no runtime-critical env var captured into module-level globals in the listed modules.
  2. Tests prove configuration is resolved through `Settings` or documented initialization boundaries rather than import order.
  3. Restart requirements for changed settings are documented and match verified behavior.
  **Rollback strategy:** Revert individual module refactors if a module-specific initialization path breaks, without undoing the broader settings contract. Keep the static inspection rule in place for unaffected modules.
  **Deployment guardrails:** Ship module refactors incrementally rather than in one large sweep. Block rollout if startup behavior differs between cold boot and reload in staging.
  **Observability checkpoints:** Emit startup config-source summary and initialization-boundary diagnostics. Alert on module import exceptions or inconsistent settings resolution between workers.
  **Risk level:** Low

- [x] `CFG-03` Make YAML fallback an explicit runtime contract with telemetry
  **Description:** Either support YAML fallback as a first-class runtime source with explicit documentation and observability or prepare it for later retirement; do not leave it as an undocumented live dependency.
  **Files/modules:** `backend/app/core/config/config_service.py`, `backend/ai_engine/prompts/registry.py`, `docs/audit/backend-system-map-v1.md`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. Documentation states the exact runtime config-source hierarchy in the same order verified by tests for DB hit, DB miss with YAML fallback, and total miss.
  2. Every YAML fallback event emits structured logs and metrics containing config or prompt key, resolved source, and fallback reason.
  3. Prompt metadata parse or YAML-read failure produces typed degraded or error signal and is never converted into silent empty metadata.
  **Rollback strategy:** If explicit fallback handling breaks prompt or config retrieval, revert only the enforcement aspect and retain source-chain telemetry. Do not revert the documentation and instrumentation that reveal fallback dependence.
  **Deployment guardrails:** Identify environments that still depend on YAML before rollout. Block removal-oriented follow-up work until fallback usage is measured and accepted.
  **Observability checkpoints:** Emit fallback usage counters, parse-failure counters, and per-key resolution-source metrics. Alert on repeated fallback dependence in DB-backed production environments.
  **Risk level:** Medium

- [x] `CFG-04` Publish a canonical config type registry and ownership model
  **Description:** Replace incomplete or misleading config inventory descriptions with a checked-in registry that enumerates supported config domains, including `macro_intelligence`, and separates ConfigService-managed types from prompt override types.
  **Files/modules:** `backend/app/core/config/config_service.py`, `backend/app/domains/admin/routes/prompts.py`, `docs/audit/backend-system-map-v1.md`
  **Dependencies:** None
  **Acceptance criteria (testable):**
  1. A checked-in canonical config registry enumerates every supported config domain and its ownership model.
  2. Documentation and admin-route behavior both reference the same registry and agree on retrieval path and persistence model for each domain.
  3. Static checks fail if a consumer or admin route requests an unregistered or misclassified config type.
  **Rollback strategy:** Revert the registry enforcement if a hidden config type is discovered unexpectedly, but preserve the registry artifact and failing check as a tracked gap until the missing type is modeled explicitly.
  **Deployment guardrails:** Generate the registry before changing config enforcement behavior in `CFG-01`. Block rollout of new config types unless they are added to the registry in the same change.
  **Observability checkpoints:** Emit registry version hash at startup and config-type lookup failures at runtime. Alert on unknown config-type requests.
  **Risk level:** Low
