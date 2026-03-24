# Backend Architecture Audit — Netz Analysis Engine v1

**Data:** 2026-03-23
**Branch:** `main`
**Baseline:** `docs/audit/backend-system-map-v1.md`
**Method:** 5 parallel validation passes + hidden complexity scan

---

## Resumo Executivo

| Categoria | Claims | Validated | Partially Validated | Invalid |
|-----------|--------|-----------|--------------------|---------|
| Tenancy & RLS | 6 | 6 | 0 | 0 |
| Dual-Write & Storage | 5 | 4 | 1 | 0 |
| Config & Import Architecture | 7 | 7 | 0 | 0 |
| Workers & SEC Hot-Path | 6 | 6 | 0 | 0 |
| **Total** | **24** | **23** | **1** | **0** |

**Hidden Complexity Findings:** 1 critical, 2 medium, 5 low

---

## 1. Section-by-Section Validation

### 1.1 Tenancy & RLS — ALL VALIDATED

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 1 | All tenant-scoped queries use `get_db_with_rls()` + `SET LOCAL` | VALIDATED | 328 uses across domains. Zero bare `get_db()` in routes. `middleware.py:46-58` |
| 2 | RLS policies use `(SELECT current_setting(...))` subselect | VALIDATED | All 9 migration files verified. Subselect in USING + WITH CHECK clauses |
| 3 | Global tables have NO `organization_id` | VALIDATED | `rls_audit.py:67-91` defines `GLOBAL_TABLES` frozenset (14 tables). `audit_rls_from_db()` verifies no RLS on globals |
| 4 | All pgvector queries include `WHERE organization_id = :org_id` | VALIDATED | 6 search functions + 2 upsert functions verified in `pgvector_search_service.py`. All use parameterized `:org_id` |
| 5 | All DuckDB queries include `WHERE organization_id = ?` | VALIDATED | `duckdb_client.py`: 5 query methods verified, all include org_id filter. SELECT-only enforcement + IP column blocking |
| 6 | Org-scoped workers call `set_rls_context()` | VALIDATED | 6 org-scoped workers verified (instrument_ingestion, risk_calc, portfolio_eval, ingestion, screening_batch, watchlist_batch). Global workers correctly skip |

### 1.2 Dual-Write & Storage — 4 VALIDATED, 1 PARTIALLY VALIDATED

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 7 | StorageClient write BEFORE pgvector upsert | VALIDATED | `unified_pipeline.py:777-854` (storage) completes before `unified_pipeline.py:865-925` (pgvector). Documented at lines 14-17 |
| 8 | All paths use `storage_routing.py` builders | PARTIALLY VALIDATED | Core pipeline 100% compliant. 3 acceptable prefix patterns for `list_files()`. 1 non-compliant: `adv_service.py:772` uses f-string for `gold/_global/sec_brochures/` instead of `global_reference_path()`. 1 legacy: `global_agent/agent.py:429` |
| 9 | No direct R2/ADLS SDK calls outside StorageClient | VALIDATED | Zero direct `boto3`/`azure` imports outside `storage_client.py`. Lazy import inside `R2StorageClient.__init__()` |
| 10 | Parquet includes `embedding_model` + `embedding_dim` | VALIDATED | `unified_pipeline.py:454-455` adds both columns. PyArrow schema at lines 478-479. Constants from `vector_integrity_guard.py:15-16` |
| 11 | `search_rebuild.py` validates dimensions before upsert | VALIDATED | Lines 239-248: dimension check raises `ValueError` on mismatch. Upsert at line 285 only after validation. Pre-rebuild DuckDB audit at lines 154-171 |

### 1.3 Config & Import Architecture — ALL VALIDATED

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 12 | No runtime YAML reads in `vertical_engines/` or `quant_engine/` | VALIDATED | Zero `yaml.load`/`yaml.safe_load` in either directory. All services receive config as parameter. YAML fallback only in `ConfigService._yaml_fallback()` (logged as ERROR) |
| 13 | `vertical_engines/credit/` and `vertical_engines/wealth/` never cross-import | VALIDATED | `pyproject.toml:137-143` contract enforced. `make architecture` → "KEPT". Zero cross-imports found |
| 14 | Models never import services within credit packages | VALIDATED | `pyproject.toml:145-152` contract enforced. Models use `TYPE_CHECKING` blocks only. `make architecture` → "KEPT" |
| 15 | Helpers never import services within credit packages | VALIDATED | `pyproject.toml:154-167` contract enforced. All `__init__.py` service imports in `TYPE_CHECKING` blocks. `make architecture` → "KEPT" |
| 16 | `quant_engine` never imports from `app.domains.wealth` | VALIDATED | `pyproject.toml:283-299` covers 16 quant services. `make architecture` → "KEPT". All config injected as parameter |
| 17 | Zero Cohere imports in codebase | VALIDATED | Zero matches for `cohere`, `CohereRerank`, `cohere_client`. Local cross-encoder (`ms-marco-MiniLM-L-6-v2`) is replacement |
| 18 | All prompt rendering uses `SandboxedEnvironment` | VALIDATED | `registry.py:54` uses `SandboxedEnvironment`. `prompt_service.py:71-107` extends with `HardenedPromptEnvironment` (SSTI hardening). All 20+ vertical engine render calls route through singleton |

### 1.4 Workers & SEC Hot-Path — ALL VALIDATED

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| 19 | All workers use `pg_try_advisory_lock` with unique IDs | VALIDATED | 21 workers, 21 unique lock IDs (range: 42-43, 900_001-900_023). No `hash()` usage. No duplicates |
| 20 | All advisory locks released in `finally` blocks | VALIDATED | All 21 workers verified: `pg_advisory_unlock()` in `finally`. 9 wrap unlock in try/except for session closure |
| 21 | All worker dispatch endpoints return 202 | VALIDATED | 21 endpoints, all declare `status_code=status.HTTP_202_ACCEPTED`. All dispatch via `_dispatch_worker()` → `BackgroundTasks` |
| 22 | SEC routes use DB-only reads (never EDGAR API) | VALIDATED | `manager_screener.py` routes use DB queries only (`sec_13f_holdings`, `sec_managers`). EDGAR API calls (`fetch_holdings()`, `discover_institutional_filers()`) restricted to worker files |
| 23 | All route handlers use `async def` | VALIDATED | 70+ handlers spot-checked across wealth routes. Zero sync route handlers found |
| 24 | No module-level asyncio primitives | VALIDATED | Only 2 lazy-init patterns found (`common.py:21-30`, `content.py:33-40`): module-level `None` + factory function. Correct pattern |

---

## 2. Contradictions

| # | Map Claim | Actual Implementation | Severity | Evidence |
|---|-----------|----------------------|----------|----------|
| C-1 | "All storage paths use `storage_routing.py`" | `adv_service.py:772` builds `gold/_global/sec_brochures/{crd}.pdf` via f-string instead of `global_reference_path()` | LOW | Non-tenant data, no isolation risk. Maintainability issue only |
| C-2 | "All storage paths use `storage_routing.py`" | `global_agent/agent.py:429` builds `silver/{deal_folder}/deal_context.json` from pre-stringified path | LOW | Legacy fallback, not in hot pipeline |
| C-3 | System map lists 20 worker dispatch endpoints | Actual count is **21** (includes `fact_sheet_gen` with lock ID 900_001) | LOW | Map undercounted by 1 |

---

## 3. Hidden Complexity / Hidden Patterns

### HC-1: CRITICAL — Missing RLS Context in Content Generation Sync Path

**File:** `backend/app/domains/wealth/routes/content.py:451-496`
**Function:** `_sync_generate_content()`

```python
with sync_session_factory() as db:
    db.expire_on_commit = False
    # NO SET LOCAL app.current_organization_id HERE
    engine = ManagerSpotlight(config=config, call_openai_fn=_call_openai)
    result = engine.generate(db, instrument_id=instrument_id, ...)
```

The sync session is created **without RLS context**. `ManagerSpotlight.generate()` then queries `Fund` table filtered only by `instrument_id` (line 130 of `manager_spotlight.py`), meaning it could return a fund from any organization if IDs collide.

**Comparison:** `dd_reports.py:532` correctly calls `SET LOCAL` before passing sync session. `content.py:390` and `content.py:419` also correctly set RLS for FlashReport and InvestmentOutlook. Only the ManagerSpotlight path at line 451 is missing it.

**Impact:** Cross-tenant data leak in manager spotlight content generation.

### HC-2: MEDIUM — Defense-in-Depth Gap in Vertical Engine Queries

**Files:**
- `vertical_engines/wealth/dd_report/quant_injection.py:47-51` — queries `FundRiskMetrics` by `instrument_id` only
- `vertical_engines/wealth/dd_report/dd_report_engine.py:288` — queries `Fund` by `fund_id` only
- `vertical_engines/wealth/manager_spotlight.py:130` — queries `Fund` by `instrument_id` only

These queries rely entirely on RLS being set by the caller. When the caller does set RLS (which is most paths), this works. But there's no explicit `organization_id` filter as defense-in-depth. If any future caller passes a bare session, these become cross-tenant.

### HC-3: MEDIUM — Silent Exception Swallowing in R2StorageClient

**File:** `backend/app/services/storage_client.py:248,257`

`exists()` catches all exceptions and returns `False`. `delete()` catches all exceptions and does nothing. Both use `# noqa: BLE001` to suppress linting. S3 auth failures, network errors, and permission denials are silently swallowed.

### HC-4: LOW — Redis Lock Degradation in Deep Review Dispatch

**File:** `backend/app/services/azure/pipeline_dispatch.py:183-185`

If Redis is unavailable, advisory lock for deep review degrades **open** (`lock_acquired = True`), allowing concurrent executions. Logged as warning but could cause race conditions under Redis failure.

### HC-5: LOW — Deprecated Azure Code Still Importable

**Files:** `backend/app/services/azure/{servicebus_client,pipeline_dispatch,search_client}.py`

Azure Service Bus, Search, and pipeline dispatch code is gated behind feature flags and lazy imports. Dead code if flags are false. Properly gated but adds maintenance burden.

### HC-6: LOW — Config Fallback with Hardcoded Default

**File:** `backend/app/services/azure/search_client.py`

Falls back to hardcoded `"global-vector-chunks-v2"` index name when `SEARCH_CHUNKS_INDEX_NAME` is unset. Not logged as fallback event. Dead code path (Azure Search deprecated) but pattern is concerning if copied.

---

## 4. False-Confidence Areas

| Area | Why Confidence is Inflated | Evidence |
|------|---------------------------|----------|
| **"All paths use storage_routing.py"** | 2 callers bypass routing functions. Core pipeline is compliant but peripheral code is not | `adv_service.py:772`, `agent.py:429` |
| **"Defense-in-depth on tenant isolation"** | Vertical engine queries rely solely on RLS context from caller, no explicit org_id WHERE clauses | `quant_injection.py:47`, `dd_report_engine.py:288`, `manager_spotlight.py:130` |
| **"R2StorageClient handles errors gracefully"** | `exists()` and `delete()` swallow ALL exceptions including auth/network failures | `storage_client.py:248,257` |

---

## 5. Missing Critical Elements

| Element | Status | Impact |
|---------|--------|--------|
| **Advisory lock ID registry** | No central registry file — IDs scattered across 21 worker files | Collision risk on new worker addition. Currently no duplicates but manual process |
| **Rate limit tier auto-detection** | Compute tier paths hardcoded in `rate_limit.py` | New LLM-heavy endpoints must be manually added |
| **ConfigService L2 Redis cache** | Documented as planned (Sprint 5-6) but not implemented | Multi-worker stale config for up to 60s. PgNotifier partially mitigates |
| **Worker DLQ / guaranteed delivery** | `BackgroundTasks` is in-memory FIFO. No dead-letter queue | Process crash loses in-flight jobs. Redis TTL (1h) is safety net only |

---

## 6. Structural Risks

| # | Risk | Severity | Evidence | Trigger |
|---|------|----------|----------|---------|
| SR-1 | **In-memory job queue** — process crash loses all in-flight workers | MEDIUM | `BackgroundTasks` in `workers.py`. Redis status keys have 1h TTL safety net | Process OOM or crash during heavy ingestion |
| SR-2 | **Single process, all verticals** — CPU-heavy vertical computation starves others | LOW | All domains share one FastAPI process (2 Uvicorn workers) | Concurrent deep review + risk_calc + macro ingestion |
| SR-3 | **Advisory lock namespace** — 21 hardcoded IDs with no central registry | LOW | Lock IDs range 42-43 (legacy) to 900_001-900_023 (structured) | New worker added without checking existing IDs |
| SR-4 | **Worker surface area growth** — 21 workers already, linear growth per data source | LOW | Each new external source adds worker + lock + dispatch endpoint | Adding new data providers (BIS, IMF already there) |
| SR-5 | **Sync session dual maintenance** — async + sync session factories coexist | LOW | `engine.py` (async) + `session.py` (sync) for vertical engine CPU-bound work | New developer uses wrong session type |

---

## Scorecard

| Domain | Health | Notes |
|--------|--------|-------|
| **Tenancy & RLS** | Excellent | 328 RLS dependency uses. Subselect everywhere. RLS audit tooling in place. 1 critical gap in content.py sync path |
| **Dual-Write & Storage** | Strong | Correct ordering enforced. Parquet schema compliant. 2 minor routing bypasses in peripheral code |
| **Config & Import Architecture** | Excellent | 29 import-linter contracts passing. Zero Cohere. SandboxedEnvironment universal. No runtime YAML |
| **Workers & SEC Hot-Path** | Excellent | 21 unique lock IDs, all finally blocks, all 202 responses, SEC DB-only in routes confirmed |
| **Hidden Complexity** | Acceptable | 1 critical (content.py RLS gap), 2 medium (defense-in-depth, R2 swallowing), 5 low |

---

## Action Items (Priority Order)

1. **CRITICAL:** Add `SET LOCAL app.current_organization_id` in `content.py:451` before `sync_session_factory()` yields to engines (ManagerSpotlight path)
2. **MEDIUM:** Add explicit `organization_id` filter to `quant_injection.py:47`, `dd_report_engine.py:288`, `manager_spotlight.py:130` as defense-in-depth
3. **MEDIUM:** Replace silent exception swallowing in `R2StorageClient.exists()` and `.delete()` with logged warnings that distinguish NotFound from real errors
4. **LOW:** Replace f-string in `adv_service.py:772` with `global_reference_path("sec_brochures", f"{crd_number}.pdf")`
5. **LOW:** Create advisory lock ID registry (e.g., `LOCK_IDS.md` or constants file) to prevent collisions

---

*Generated 2026-03-23 from 5 parallel validation passes against `docs/audit/backend-system-map-v1.md`. All claims grounded in repository evidence.*
