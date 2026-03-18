# Backend Architecture Audit v3

**Audited document:** `docs/audit/backend-system-map-v3.md`
**Date:** 2026-03-18
**Method:** 6-pass pipeline — claims extraction → runtime anchors → scoped validation (4 domains) → contradictions → hidden complexity → structural risks
**Evidence source:** Live repository code only

---

## 1. Section-by-Section Validation

### 1.1 Pipeline & AI Engine (12 claims)

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | 10 stages + 5 validation gates | **VALIDATED** | `unified_pipeline.py` — 10 stages confirmed, 5 gates confirmed. Stages are sequential; internal parallelism within stages only (extraction gather, ADLS writes). |
| 2 | IngestRequest is frozen dataclass | **VALIDATED** | `ai_engine/pipeline/models.py:73` — `@dataclass(frozen=True)` |
| 3 | 3-layer classifier: 28 filename + 13 content + 38 exemplars + gpt-4-1-mini | **PARTIALLY VALIDATED** | 26 filename patterns (not 28), 13 content regex (correct), 37 exemplars (not 38), LLM model is `gpt-4.1` (not gpt-4-1-mini) |
| 4 | HybridClassificationResult frozen dataclass | **VALIDATED** | `models.py:59` — frozen, 4 fields match |
| 5 | 31 canonical doc types, 6 vehicle types | **VALIDATED** | `models.py:16-31` — exact counts confirmed |
| 6 | Dual-write: ADLS first, Search second; total ADLS failure skips Search | **VALIDATED** | `unified_pipeline.py:787-832` — asyncio.gather for ADLS writes, conditional skip_index on total failure |
| 7 | Search rebuild uses Redis advisory lock | **VALIDATED** | `search_rebuild.py:68-76` — `SET NX EX 3600`. Degrades open if Redis unavailable. |
| 8 | 15 governance patterns | **VALIDATED** | `governance_detector.py:17-33` — 15 tuples |
| 9 | Adaptive chunk sizing by doc_type | **VALIDATED** | `semantic_chunker.py:42-89` — per-type (min, target, max) tuples |
| 10 | Mistral OCR with table=HTML | **VALIDATED** | `mistral_ocr.py:22,110-119` — `table_format: "html"` |
| 11 | text-embedding-3-large, 3072-dim, batch=500 | **VALIDATED** | `vector_integrity_guard.py:14-16`, `embed_chunks.py:26` |
| 12 | 7 SSE events in sequence | **VALIDATED** | All 7 events confirmed in order |

### 1.2 Core Infrastructure & Auth (13 claims)

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | RLS uses SET LOCAL | **VALIDATED** | `tenancy/middleware.py:42-48` |
| 2 | ConfigService cascade: TTLCache(60s)→DB Override→DB Default→YAML(ERROR) | **VALIDATED** | `config_service.py:33,82-86,421` |
| 3 | PgNotifier invalidates cache on config_changed | **PARTIALLY VALIDATED** | PgNotifier is generic (channel name injected via `subscribe()`), not hardcoded to "config_changed". Functionally correct. |
| 4 | expire_on_commit=False on all sessions | **VALIDATED** | `engine.py:37`, `session.py:34` |
| 5 | Clerk JWT v2, org_id from `o.id` claim | **VALIDATED** | `clerk_auth.py:162-175` |
| 6 | Dev bypass via X-DEV-ACTOR, blocked in prod | **VALIDATED** | `clerk_auth.py:129-133`, `settings.py:133-154` — RuntimeError on prod secrets + dev mode |
| 7 | CLIENT_VISIBLE_TYPES = {calibration, scoring, blocks, portfolio_profiles} | **VALIDATED** | `config_service.py:67-69` — frozenset match |
| 8 | HardenedPromptEnvironment blocks dangerous attrs | **VALIDATED** | `prompt_service.py:57-87` — 14 blocked attrs + callable blocking + % operator blocking |
| 9 | Rate limiting per role | **PARTIALLY VALIDATED** | Rate limiting is per **endpoint tier** (compute vs standard), not per role. `rate_limit.py:34-64` |
| 10 | AuditEvent with before/after state | **VALIDATED** | `core/db/models.py:54-59` — JSONB columns |
| 11 | Pool: size=20, overflow=10, pre_ping=True, recycle=300 | **VALIDATED** | `engine.py:27-31` — exact values + bonus pool_timeout=30 |
| 12 | SSE heartbeat 15s | **VALIDATED** | `sse.py:46-50` — `ping=15` |
| 13 | Job TTL=3600s, grace=120s | **VALIDATED** | `tracker.py:31,46` |

### 1.3 Workers & Tenant Isolation (12 claims)

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | 8 wealth worker endpoints, all BackgroundTasks | **VALIDATED** | `workers.py` — 8 POST endpoints, all via `background_tasks.add_task()` |
| 2 | All workers require INVESTMENT_TEAM or ADMIN | **VALIDATED** | `_require_admin_role()` enforced on all 8 |
| 3 | fred_ingestion registered in workers.py | **INVALID** | fred_ingestion.py exists but is NOT imported or referenced in workers.py. Dead code. |
| 4 | Storage routing: {tier}/{org_id}/{vertical}/ | **VALIDATED** | `storage_routing.py:48-84` — all path functions enforce format |
| 5 | Two StorageClient implementations | **VALIDATED** | `storage_client.py` — LocalStorageClient + ADLSStorageClient with path validation |
| 6 | Search documents include organization_id | **VALIDATED** | `search_upsert_service.py:196-200` — Security F4 comment |
| 7 | RAG queries always include $filter=organization_id | **VALIDATED** | `pipeline_kb_adapter.py:73-86`, `agent.py:257-259` — refuses search without org_id |
| 8 | Global tables: no RLS on macro_data, allocation_blocks, vertical_config_defaults, benchmark_nav | **VALIDATED** | All 4 confirmed: no OrganizationScopedMixin, no organization_id column |
| 9 | Instruments polymorphic (fund/bond/equity) | **VALIDATED** | `instrument.py:22-53` — instrument_type + JSONB attributes |
| 10 | 47 routers (7+25+15) | **INVALID** | Actual: 7 admin + 26 credit + 18 wealth = **51 routers**. Credit undercounted by 1, wealth undercounted by 3. |
| 11 | AI router loads 9 sub-routers | **PARTIALLY VALIDATED** | 9 specs defined, but 7 required + 2 optional (extraction, portfolio can degrade) |
| 12 | admin_assets_router unauthenticated | **VALIDATED** | `assets.py` — no auth dependency, public endpoint, returns default PNG for unknown tenants |

### 1.4 Import Architecture & Structure (10 claims)

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | 35+ import-linter contracts | **INVALID** | Actual: **30 contracts** in pyproject.toml |
| 2 | Only 3/17 quant services have vertical-isolation contracts | **VALIDATED** | regime_service, cvar_service, correlation_regime_service only |
| 3 | All 12 credit packages: models.py + service.py | **PARTIALLY VALIDATED** | 10 of 13 packages have both. domain_ai lacks models.py. sponsor lacks models.py. underwriting has neither service.py nor models.py (only derivation.py + persistence.py). |
| 4 | Deep review 5-tier layers | **INVALID** | Contract defines **6 tiers**: models → helpers → corpus\|prompts\|policy\|decision\|confidence → persist → portfolio → service |
| 5 | No @lru_cache in quant_engine | **VALIDATED** | Zero @lru_cache or YAML imports found |
| 6 | YAML fallback logged as ERROR | **VALIDATED** | `config_service.py:421` — `logger.error()` |
| 7 | 19 migrations, head 0019_audit_events | **PARTIALLY VALIDATED** | **18 migration files** (0001-0019, but no 0000). Head IS 0019_audit_events. |
| 8 | Underwriting package exists | **PARTIALLY VALIDATED** | Directory exists with 3 files, but minimal (no service.py, no models.py) |
| 9 | BaseAnalyzer has 3 methods | **VALIDATED** | `base_analyzer.py` — run_deal_analysis (abstract), run_portfolio_analysis (abstract), run_pipeline_analysis (default) |
| 10 | FundAnalyzer vertical='liquid_funds' | **VALIDATED** | `fund_analyzer.py:22,25` |

---

## 2. Contradictions

| # | Map Claim | Actual Implementation | Severity |
|---|-----------|----------------------|----------|
| C-1 | "28 filename patterns" | 26 filename patterns in hybrid_classifier.py | Low |
| C-2 | "38 synthetic exemplars" | 37 total (31 doc_type + 6 vehicle) | Low |
| C-3 | "LLM fallback uses gpt-4-1-mini" | Uses `gpt-4.1` | Medium — affects cost/latency expectations |
| C-4 | "47 routers (7+25+15)" | 51 routers (7+26+18). Wealth undercounted by 3, credit by 1 | Medium — API surface is larger than documented |
| C-5 | "35+ import-linter contracts" | 30 contracts | Low |
| C-6 | "Deep review 5-tier layers" | 6 tiers | Low |
| C-7 | "19 migrations" | 18 migration files | Low |
| C-8 | "Rate limiting per role" | Per endpoint tier (compute vs standard), not role | Medium — operational understanding |
| C-9 | "All 12 credit packages: models.py + service.py" | 10 of 13 follow pattern (domain_ai, sponsor, underwriting deviate) | Low — structural description imprecise |
| C-10 | "fred_ingestion in workers.py" (implied by system map listing) | NOT registered. Dead code, fully disconnected. | Low — correctly identified as deprecated but map implies it's routed |

---

## 3. Hidden Complexity

### HC-1: Worker Tenant Context Bypass (CRITICAL)

**6 of 8 wealth workers create sessions via `async_session_factory()` without calling `SET LOCAL app.current_organization_id`:**

- `risk_calc.py` — queries `nav_timeseries` (tenant-scoped) without RLS context
- `ingestion.py` — queries `Fund`/`NavTimeseries` without RLS context
- `portfolio_eval.py` — queries `StrategicAllocation`/`NavTimeseries` without RLS context
- `macro_ingestion.py` — writes to global `macro_data` (no impact, but defensive gap)
- `screening_batch.py` — receives org_id parameter but unclear if SET LOCAL is called
- `watchlist_batch.py` — receives org_id parameter but unclear if SET LOCAL is called

**Impact:** Workers process ALL organizations' data in a single session. Currently "works" because workers are fleet-wide batch operations, but violates the stated RLS-everywhere architecture. If any worker queries a tenant-scoped table with RLS policies, results are unpredictable (depends on whether PostgreSQL RLS defaults to deny-all or allow-all when `current_setting` is empty).

**Evidence:** `workers/risk_calc.py:20-28`, `workers/ingestion.py:62-73`

### HC-2: Upload URL Path Bypasses storage_routing.py (HIGH)

**`app/domains/credit/documents/routes/upload_url.py:110`** constructs ADLS paths via f-string:
```python
blob_path = f"bronze/{actor.organization_id}/{payload.fund_id}/documents/{res.version.id}/{safe_filename}"
```

Violates CLAUDE.md rule: "Never build ADLS paths with f-strings in callers." Path format happens to be correct but bypasses centralized validation and will diverge silently on routing changes.

### HC-3: Config YAML Fallback Masks DB Seed Failure (MEDIUM)

ConfigService YAML fallback (14 registered keys in `_YAML_FALLBACK_MAP`) provides operational resilience but can mask database migration failures. If `0004_vertical_configs` migration failed to seed defaults, the system continues running on YAML with ERROR logs but no hard failure. No boot-time assertion verifies DB config presence.

**Evidence:** `config_service.py:43-54,354-437`

### HC-4: SSE Publish Failures Silently Swallowed (MEDIUM)

`unified_pipeline.py` catches ALL exceptions in `_emit()`, `_emit_terminal()`, and `_audit()` helper functions. SSE publish failure → frontend appears hung while backend succeeds. Terminal state IS persisted to Redis as backup, but frontend polling isn't documented as a fallback.

**Evidence:** `unified_pipeline.py:325-326,340-341,371-372`

### HC-5: Lazy Semaphore Race Condition (LOW)

`vertical_engines/credit/memo/tone.py:48-52` uses a global `_LLM_SEMAPHORE = None` with lazy initialization. If two async tasks call `_get_llm_semaphore()` concurrently before initialization, two semaphores could be created (race on `if _LLM_SEMAPHORE is None`). In practice, the GIL prevents true races in CPython, but this is fragile under future async runtimes.

### HC-6: Deep Review Cascading Degradation (LOW)

`deep_review/service.py` uses never-raises contracts on ALL engine integrations (quant, sponsor, critic, KYC, EDGAR). If multiple engines fail simultaneously, the final IC memo is generated with minimal signal. No circuit breaker prevents memo generation when >N engines are degraded.

---

## 4. False-Confidence Areas

| Area | Why Confidence Is Misleading |
|------|------------------------------|
| **"All routes use RLS"** | True for HTTP route handlers, but 6/8 workers bypass RLS entirely (HC-1). The system map's tenant isolation picture is incomplete. |
| **"Single unified pipeline"** | True — all 3 entry points delegate to `unified_pipeline.process()`. But `upload_url.py` bypasses storage_routing.py for upload path generation (HC-2). |
| **"No external ML APIs"** | True for classification (Cohere removed). But extraction stage still calls OpenAI for metadata/summary (gpt-4.1), and OCR calls Mistral. "No external ML APIs" applies only to classification layer. |
| **"12 credit packages with uniform structure"** | 10 of 13 follow models.py + service.py. 3 deviate (domain_ai, sponsor, underwriting). |
| **"35+ import-linter contracts"** | 30 contracts. Strong but fewer than claimed. More critically, only 3/17 quant services are covered by vertical-isolation contracts — the other 14 could silently import wealth domain models. |

---

## 5. Missing Critical Elements

| # | Missing Element | Impact |
|---|----------------|--------|
| M-1 | **Worker RLS context enforcement** — no infrastructure ensures workers call SET LOCAL before tenant queries | Cross-tenant data exposure in batch operations |
| M-2 | **Boot-time config presence assertion** — no check that DB has ≥1 config default per vertical | Silent YAML degradation on migration failure |
| M-3 | **Import-linter coverage for quant_engine** — 14/17 services lack vertical-isolation contracts | Accidental wealth→quant coupling undetected |
| M-4 | **SSE failure recovery** — no documented frontend fallback when SSE publish fails silently | UI hangs on successful backend operations |
| M-5 | **Deep review circuit breaker** — no threshold for "too many engines degraded, abort memo" | Low-quality memos generated without signal |
| M-6 | **Worker idempotency guarantees** — workers use advisory locks for mutual exclusion but no dead-letter or retry queue | Failed workers must be manually re-triggered |

---

## 6. Structural Risks

### SR-1: In-Process Worker Model (from system map — CONFIRMED)
All workers compete for the ASGI event loop. No isolation, no retry queue, no DLQ. Confirmed by audit.

### SR-2: Worker Tenant Context Bypass (NEW — CRITICAL)
6 of 8 workers bypass RLS. Fleet-wide batch pattern currently masks the issue, but architecture claims RLS-everywhere.

### SR-3: Stale Operational References (from system map — CONFIRMED)
18 files reference removed modules. Low-severity but adds noise to IC memo prompts.

### SR-4: Dual Model Path Fund/Instrument (from system map — CONFIRMED)
Deprecated Fund model + routes coexist with Instrument. Increases surface area.

### SR-5: Fred Ingestion Dead Code (from system map — CONFIRMED but upgraded)
Not just deprecated — fully disconnected. No route, no import. Pure dead code.

### SR-6: Search Index SPOF for RAG (from system map — CONFIRMED)
No automatic failover. search_rebuild.py exists as manual recovery only.

### SR-7: Advisory Lock TTL (from system map — RESOLVED)
System map flagged missing TTL. Audit found: `ex=3600` (1 hour TTL) with degrade-open fallback. This risk is **adequately mitigated**.

### SR-8: Import-Linter Coverage Gap (from system map — CONFIRMED)
3/17 quant services covered. 14 uncovered services could develop wealth domain dependencies without detection.

### SR-9: Upload URL Path Construction (NEW — HIGH)
f-string ADLS path in `upload_url.py` bypasses `storage_routing.py`. Violates CLAUDE.md rule.

---

## Validation Score Summary

| Domain | Claims | Validated | Partially | Invalid |
|--------|--------|-----------|-----------|---------|
| Pipeline & AI Engine | 12 | 11 | 1 | 0 |
| Core Infrastructure | 13 | 11 | 2 | 0 |
| Workers & Isolation | 12 | 9 | 1 | 2 |
| Import & Structure | 10 | 5 | 3 | 2 |
| **TOTAL** | **47** | **36 (77%)** | **7 (15%)** | **4 (8%)** |

---

## Priority Fix Order

1. **CRITICAL** — HC-1: Add `SET LOCAL` to 6 wealth workers (tenant isolation)
2. **HIGH** — HC-2: Replace f-string path in `upload_url.py` with `storage_routing` helper
3. **MEDIUM** — M-3: Add import-linter vertical-isolation contracts for remaining 14 quant services
4. **MEDIUM** — HC-3: Add boot-time assertion for DB config presence
5. **LOW** — Fix system map numerical inaccuracies (C-1 through C-10)

---

## 7. Remediation Log

All findings from sections 3, 5, and 6 were remediated on **2026-03-18**.

### HC-1: Worker Tenant Context Bypass (CRITICAL) — FIXED

Added `set_rls_context()` reusable helper to `core/tenancy/middleware.py`. 5 wealth workers now receive `org_id` and call `SET LOCAL` at session start and after each `commit()` (SET LOCAL is transaction-scoped). Router `routes/workers.py` passes `user.organization_id` to ingestion, risk_calc, and portfolio_eval. `macro_ingestion` unchanged — only touches global tables.

**Files changed:** `core/tenancy/middleware.py`, `workers/risk_calc.py`, `workers/ingestion.py`, `workers/portfolio_eval.py`, `workers/screening_batch.py`, `workers/watchlist_batch.py`, `routes/workers.py`

### HC-2: Upload URL Path Bypasses storage_routing.py (HIGH) — FIXED

Added `bronze_upload_blob_path()` to `ai_engine/pipeline/storage_routing.py` with `_validate_segment()` checks on fund_id, version_id, and filename. `upload_url.py` now calls this helper instead of constructing paths via f-string.

**Files changed:** `ai_engine/pipeline/storage_routing.py`, `app/domains/credit/documents/routes/upload_url.py`

### HC-3: Config YAML Fallback Masks DB Seed Failure (MEDIUM) — FIXED

`_verify_config_completeness()` in `app/main.py` now raises `RuntimeError` in production if any config defaults are missing from DB. Expected pairs synced with `_YAML_FALLBACK_MAP` (7 → 10 keys). Dev mode continues with warning.

**Files changed:** `app/main.py`

### HC-5: Lazy Semaphore Race Condition (LOW) — FIXED

`_get_llm_semaphore()` in `vertical_engines/credit/memo/tone.py` converted to `async def` with double-checked locking via `asyncio.Lock`. Race-free under any async runtime.

**Files changed:** `vertical_engines/credit/memo/tone.py`

### HC-6: Deep Review Cascading Degradation (LOW) — FIXED

Circuit breaker added to both sync and async pipelines in `deep_review/service.py`. Returns structured error dict when ≥2 degradable engines (EDGAR, KYC) fail simultaneously, preventing low-quality memo generation.

**Files changed:** `vertical_engines/credit/deep_review/service.py`

### M-3: Import-Linter Coverage Gap (MEDIUM) — FIXED

Coverage expanded from **3/16 → 16/16** quant services enforced by vertical-isolation contracts.

**Phase 1:** Added 6 already-clean services (`attribution`, `fred`, `portfolio_metrics`, `regional_macro`, `stress_severity`, `talib_momentum`) to the existing forbidden contract.

**Phase 2:** Extracted DB query functions from 7 remaining services into `app/domains/wealth/services/quant_queries.py`. Pure computation stays in `quant_engine/`; DB access lives in the wealth domain layer. `scoring_service.py` replaced ORM import with `typing.Protocol`.

**Files changed:** `pyproject.toml`, `app/domains/wealth/services/quant_queries.py` (new), `quant_engine/scoring_service.py`, `quant_engine/backtest_service.py`, `quant_engine/optimizer_service.py`, `quant_engine/drift_service.py`, `quant_engine/peer_comparison_service.py`, `quant_engine/rebalance_service.py`, `quant_engine/lipper_service.py`, `app/domains/wealth/routes/analytics.py`, `app/domains/wealth/workers/drift_check.py`, `vertical_engines/wealth/quant_analyzer.py`

### SR-5: Fred Ingestion Dead Code (LOW) — FIXED

`app/domains/wealth/workers/fred_ingestion.py` deleted. Zero imports confirmed — fully disconnected since `macro_ingestion.py` superseded it. Test allowlist references removed from `tests/test_global_table_isolation.py`.

**Files changed:** `app/domains/wealth/workers/fred_ingestion.py` (deleted), `tests/test_global_table_isolation.py`

### HC-4: SSE Publish Failures Silently Swallowed (MEDIUM) — FIXED

`tracker.py:publish_event()` already had structured `logger.warning` with `exc_info=True`. Verified `_emit()`, `_emit_terminal()`, and `_audit()` in `unified_pipeline.py` all log failures. Terminal state is persisted to Redis BEFORE SSE publish (line 936 vs 948), so polling fallback always has data.

Added `GET /api/v1/jobs/{job_id}/status` polling endpoint in `app/main.py` — reads persisted terminal state from Redis via `get_job_state()`. Enforces tenant isolation via `verify_job_owner()`. Returns 404 if job hasn't reached terminal state.

**Files changed:** `app/main.py`, `manifests/routes.json`

### M-4: SSE Failure Recovery (MEDIUM) — FIXED

See HC-4 — the new `/api/v1/jobs/{job_id}/status` polling endpoint provides the documented frontend fallback. Frontends can poll this endpoint when SSE connections drop before receiving a terminal event.

### M-6: Worker Idempotency (MEDIUM) — FIXED

New `app/core/jobs/worker_idempotency.py` provides lightweight Redis-based idempotency guard. Redis key pattern: `worker:{worker_name}:{scope}:status`. All 8 worker endpoints in `routes/workers.py` now check idempotency before dispatch — returns 409 Conflict if already running or recently completed. Failed workers allow immediate re-trigger. TTLs: running=3600s (safety net), completed=300s (cooldown), failed=1800s (visibility). 11 new tests in `test_worker_idempotency.py`.

**Files changed:** `app/core/jobs/worker_idempotency.py` (new), `app/domains/wealth/routes/workers.py`, `tests/test_worker_idempotency.py` (new)

### SR-1: In-Process Worker Model (MEDIUM) — MITIGATED

Added `_run_worker_with_timeout()` wrapper with `asyncio.wait_for()` on all 8 worker dispatches. Two timeout tiers: heavy workers (ingestion, risk calc, macro, fact-sheet, benchmark) = 600s, light workers (screening, watchlist, portfolio eval) = 300s. Structured logging via structlog: `worker.started`, `worker.completed`, `worker.timeout`, `worker.failed` with duration_seconds and org_id. Composes with M-6 idempotency wrapper.

**Files changed:** `app/domains/wealth/routes/workers.py`

### SR-3: Stale Operational References (LOW) — FIXED

Cleaned 13 files referencing removed modules (`compliance` domain, not the legitimate KYC/regulatory usage). Removed stale docstring provenance comments, dead module references in comments, and replaced "compliance" with "governance" or "regulatory" where appropriate. Preserved legitimate uses: `Role.COMPLIANCE` enum, `compliance.py` AI subrouter, `regulatory_compliance` doc type, `covenant_compliance` fields, `adobe_sign_agreement_id` in migration (DB compat).

**Files changed:** `ai_engine/validation/evidence_quality.py`, `ai_engine/validation/citation_formatter.py`, `ai_engine/extraction/kb_schema.py`, `ai_engine/extraction/azure_kb_adapter.py`, `ai_engine/extraction/__init__.py`, `app/core/middleware/rate_limit.py`, `app/domains/credit/modules/ai/copilot.py`, `app/domains/credit/global_agent/intent_router.py`, `app/domains/credit/global_agent/prompt_templates.py`, `app/domains/credit/global_agent/pipeline_kb_adapter.py`, `vertical_engines/credit/kyc/models.py`, `vertical_engines/credit/retrieval/saturation.py`, `vertical_engines/credit/deep_review/corpus.py`

### SR-4: Dual Model Path Fund/Instrument (LOW) — MITIGATED

Fund model and routes marked as deprecated with migration path to Instrument. `fund.py` emits `DeprecationWarning` on import. All 5 Fund route handlers have `deprecated=True` (OpenAPI strikethrough), `[DEPRECATED]` summaries, RFC 8594 `Deprecation` + `Sunset: 2026-06-30` + `Link: rel=successor-version` headers. Router tag changed to `"funds (deprecated)"`. No code deleted — Fund model still imported by ~17 files.

**Files changed:** `app/domains/wealth/models/fund.py`, `app/domains/wealth/routes/funds.py`, `app/domains/wealth/schemas/fund.py`, `app/domains/wealth/models/__init__.py`, `app/main.py`

### SR-6: Search Index SPOF for RAG (MEDIUM) — FIXED

Added graceful degradation to all 3 search query paths. Connection errors and timeouts now return empty results with `SEARCH_INDEX_UNAVAILABLE` structured warning logs instead of raising 500s. Global agent returns `search_degraded: bool` and `search_degraded_domains: list[str]` in response — frontend can display "Search temporarily unavailable" messaging. 9 new tests in `test_search_rag_degradation.py`.

**Files changed:** `app/domains/credit/global_agent/pipeline_kb_adapter.py`, `ai_engine/extraction/azure_kb_adapter.py`, `app/services/search_index.py`, `app/domains/credit/global_agent/agent.py`, `tests/test_search_rag_degradation.py` (new)

### C-1→C-10: System Map Numerical Inaccuracies (LOW) — FIXED

All 10 corrections applied to `docs/audit/backend-system-map-v3.md`: filename patterns 28→26, exemplars 38→37, LLM model gpt-4-1-mini→gpt-4.1, routers 47→51, contracts 35+→30, deep review tiers 5→6, migrations 19→18, rate limiting per-role→per-tier, credit packages 12→13 with deviations noted, fred_ingestion marked DELETED. Also updated quant isolation contracts 3/17→16/16 per M-3 fix.

**Files changed:** `docs/audit/backend-system-map-v3.md`

### All Findings Status

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| HC-1 | Worker tenant context bypass | Critical | **Resolved** |
| HC-2 | Upload URL path bypass | High | **Resolved** |
| HC-3 | Config YAML fallback masks DB failure | Medium | **Resolved** |
| HC-4 | SSE publish failures silently swallowed | Medium | **Resolved** |
| HC-5 | Lazy semaphore race condition | Low | **Resolved** |
| HC-6 | Deep review cascading degradation | Low | **Resolved** |
| M-3 | Import-linter coverage gap | Medium | **Resolved** |
| M-4 | SSE failure recovery — no frontend fallback | Medium | **Resolved** (see HC-4) |
| M-6 | Worker idempotency — no DLQ or retry queue | Medium | **Resolved** |
| SR-1 | In-process worker model — no isolation | Medium | **Mitigated** (timeouts + observability) |
| SR-2 | Worker tenant context bypass | Critical | **Resolved** (see HC-1) |
| SR-3 | Stale operational references | Low | **Resolved** |
| SR-4 | Dual model path Fund/Instrument | Low | **Mitigated** (deprecated, sunset 2026-06-30) |
| SR-5 | Fred ingestion dead code | Low | **Resolved** |
| SR-6 | Search index SPOF for RAG | Medium | **Resolved** |
| SR-7 | Advisory lock TTL | Medium | **Already mitigated** |
| SR-8 | Import-linter coverage gap | Medium | **Resolved** (see M-3) |
| SR-9 | Upload URL path construction | High | **Resolved** (see HC-2) |
| C-1→C-10 | System map numerical inaccuracies | Low | **Resolved** |
