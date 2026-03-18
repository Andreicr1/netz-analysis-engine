# Backend Architecture Audit v2

> Validation audit of `backend-system-map-v2.md` against actual repository code.
> Generated 2026-03-18. No remediation advice unless explicitly requested.

---

## 1. Section-by-Section Validation

### 1.1 Auth & Tenancy

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| A1 | All routes use `get_db_with_rls()` with `SET LOCAL` | **PARTIALLY VALIDATED** | `middleware.py:46` correctly uses `SET LOCAL`. However, **65+ credit module routes** in `app/domains/credit/modules/` import `get_db` from `engine.py` instead, skipping RLS context entirely. Affected: `extraction.py`, `copilot.py`, `documents.py`, `artifacts.py`, `compliance.py`, `pipeline_deals.py`, `deep_review.py`, `memo_chapters.py`, `portfolio.py`, `modules/deals/routes.py`. PostgreSQL RLS policies still enforce isolation (the `require_org_context()` function from migration 0001 would raise on null context), so these routes would **error at runtime** rather than silently leak data — but they are broken for multi-tenant use. Wealth routes and credit canonical routes (`dashboard/`, `dataroom/`, `reporting/`) correctly use `get_db_with_rls()`. |
| A2 | RLS subselect `(SELECT current_setting(...))` in all migration policies | **VALIDATED** | Every RLS USING/WITH CHECK clause in migrations 0003-0016 uses the subselect wrapper. The only bare `current_setting` is in the `require_org_context()` PL/pgSQL function body (0001), which is not a policy expression. |
| A3 | Admin bypass uses `SET LOCAL app.admin_mode = 'true'` | **VALIDATED** | `admin_middleware.py:17` sets the flag. Migration 0015 adds `OR (SELECT current_setting('app.admin_mode', true)) = 'true'` to RLS policies, providing genuine DB-level bypass. Transaction-scoped via `SET LOCAL`. |
| A4 | Dev bypass via `X-DEV-ACTOR` guarded by environment | **VALIDATED** | `clerk_auth.py:130-133` checks `settings.is_development`. Guard returns True only when `app_env == "development"` (`settings.py:107-108`). **Caveat:** `app_env` defaults to `"development"` (`settings.py:38`); `validate_production_secrets()` does NOT verify `app_env != "development"`. Production deployments must explicitly set `APP_ENV`. |
| A5 | `expire_on_commit=False` on all session factories | **VALIDATED** | Async (`engine.py:37`) and sync (`session.py:28`) both confirmed. |
| A6 | `lazy="raise"` on ALL relationships | **VALIDATED** | All 8 `relationship()` declarations in the codebase include `lazy="raise"`. |

### 1.2 Config & Registry

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| B1 | ConfigService cascade: TTLCache → DB override → DB default → YAML fallback | **PARTIALLY VALIDATED** | The cache and YAML fallback are confirmed. However, the actual resolution is **not a waterfall** — it is a **merge-on-top** pattern: DB default is fetched first as base, then DB override is deep-merged on top (if org_id provided). The system map description ("override → default → YAML") implies a priority waterfall which is misleading. Actual order: TTLCache → (DB default or YAML fallback as base) → DB override merged on top. |
| B2 | PgNotifier invalidates cache on config write | **VALIDATED** | Migration 0015 creates PostgreSQL trigger `notify_config_change()` on `vertical_config_overrides` table. PgNotifier listens via dedicated asyncpg connection. ConfigService.invalidate() pops cache keys. **Caveat:** Trigger only covers `vertical_config_overrides`, NOT `vertical_config_defaults`. Admin writes to defaults via `put_default()` do NOT trigger cache invalidation. |
| B3 | 14+ registered config domains | **VALIDATED** | Exactly 14 `ConfigDomain` entries in `registry.py:34-140`. CLIENT_VISIBLE_TYPES enforced at `config_service.py:67-69` (frozenset of 4 types). |
| B4 | YAML files never read at runtime (except fallback) | **PARTIALLY VALIDATED** | ConfigService YAML fallback confirmed with ERROR logging. `ai_engine/prompts/registry.py:153` does call `yaml.safe_load()` at runtime — but on `.j2` template frontmatter, not standalone YAML config files. Spirit of the claim holds; letter is technically violated. |

### 1.3 Pipeline & Storage

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| C1 | Unified pipeline is single ingestion path | **PARTIALLY VALIDATED** | `unified_pipeline.process()` is the canonical path. However, **3 alternative paths bypass it**: (1) `POST /ai/pipeline/ingest` calls `run_pipeline_ingest()` directly with sync Session, (2) `POST /ai/pipeline/deals/{id}/reanalyze` calls `run_deal_ai_analysis` directly with its own session, (3) `POST /ai/pipeline/deals/{id}/bootstrap` calls `async_bootstrap_deal()` via `asyncio.run()` in BackgroundTask. Paths 1-3 bypass unified pipeline's validation gates, governance checks, and storage routing. A deprecated `extraction_orchestrator.py` also exists (marked for deletion). |
| C2 | Dual-write: ADLS first, then Azure Search | **PARTIALLY VALIDATED** | Ordering confirmed: ADLS at stage 8, Search at stage 9. **However:** ADLS failure does NOT halt the pipeline — it continues to Search upsert. This means Search can have data that ADLS does not, contradicting "ADLS is source of truth" principle. Search rebuild from ADLS would then lose that document. |
| C3 | Parquet includes `embedding_model` + `embedding_dim` | **VALIDATED** | `unified_pipeline.py:421-482` writes both columns with zstd compression. `search_rebuild.py:164-173` validates `embedding_dim` on read. **Note:** Rebuild validates dimensions but not model name; legacy Parquet without the column silently passes via `if "embedding_dim" in table.column_names`. |
| C4 | All Azure Search documents include `organization_id` | **PARTIALLY VALIDATED** | Unified pipeline path includes it (`unified_pipeline.py:853`, `search_upsert_service.py:199-200`). **Three auxiliary paths omit it:** `document_scanner.py:207-218`, `knowledge_builder.py:227-238`, `obligation_extractor.py:184-195` — these build search docs without `organization_id`, creating tenant isolation gaps in the search index. |

### 1.4 Jobs & SSE

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| D1 | Job ownership with TTL + refresh | **VALIDATED** | All four lifecycle functions exist in `tracker.py:75-144`. `verify_job_owner()` is called before SSE stream in `main.py:267` and `dd_reports.py:268`. |
| D2 | Terminal event types match listed set | **VALIDATED** | `tracker.py:35-42` defines `TERMINAL_EVENT_TYPES` frozenset with exactly the 6 listed values. `done` and `memo_complete` are defined but no production callers found yet. |
| D3 | SSE heartbeat 15s | **VALIDATED** | `sse.py:48` — `ping=15`. Comment explains Azure Container Apps 30s idle timeout rationale. |

### 1.5 Import Architecture

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| E1 | Verticals independent (import-linter) | **VALIDATED** | `pyproject.toml:121-127` — independence contract. Zero cross-imports found. |
| E2 | Models never import service | **VALIDATED** | `pyproject.toml:132-136` (credit wildcard) + `pyproject.toml:269-301` (wealth, 13 explicit modules). Zero violations. |
| E3 | Quant services don't import app.domains.wealth | **VALIDATED** | `pyproject.toml:263-267` (regime, cvar) + `pyproject.toml:432-436` (correlation_regime). Zero violations. Other quant services (backtest, drift, optimizer, etc.) DO import wealth — acknowledged as "subsequent phases." |

### 1.6 Storage

| # | Claim | Status | Evidence |
|---|-------|--------|----------|
| F1 | StorageClient abstract base, feature-flagged | **VALIDATED** | `storage_client.py:35` — ABC with 7 abstract methods. `create_storage_client()` factory at line 260-264 uses `settings.feature_adls_enabled`. Lazy singleton via `get_storage_client()`. |
| F2 | Path validation with `_SAFE_PATH_SEGMENT_RE` | **VALIDATED** | `storage_routing.py:18` — regex `^[a-zA-Z0-9][a-zA-Z0-9._\-]*$`. Applied in all 8 path builder functions. |

---

## 2. Contradictions

| # | Map Claim | Actual Behavior | Severity |
|---|-----------|-----------------|----------|
| C-1 | "All routes use `get_db_with_rls()`" | 65+ credit module routes use bare `get_db()` without RLS context. PostgreSQL `require_org_context()` would raise, so these routes **fail at runtime** rather than leak data — but they are broken. | **HIGH** |
| C-2 | "ConfigService cascade: override → default → YAML" | Actual cascade is **merge-on-top**: DB default (or YAML) as base, then override deep-merged. Not a priority waterfall. | **MEDIUM** |
| C-3 | "ADLS is source of truth; if ADLS fails, pipeline continues with warning" | Pipeline continues to Azure Search upsert even after ADLS failure. Search can then contain data that ADLS does not. Search rebuild from ADLS would lose that document. | **MEDIUM** |
| C-4 | "All Azure Search documents include organization_id" | Three auxiliary paths (`document_scanner`, `knowledge_builder`, `obligation_extractor`) omit `organization_id` in search documents. | **HIGH** |
| C-5 | "Unified pipeline is single ingestion path" | At least 3 alternative paths bypass unified pipeline: `/ai/pipeline/ingest` (direct sync call), `deals/{id}/reanalyze` (direct session), `deals/{id}/bootstrap` (asyncio.run in BackgroundTask). | **HIGH** |
| C-6 | "PgNotifier invalidates cache on config write" | Trigger only covers `vertical_config_overrides`, NOT `vertical_config_defaults`. Admin writes to defaults are NOT invalidated via pg_notify. | **LOW** |

---

## 3. Hidden Complexity

### 3.1 Broad Exception Swallowing

**STATUS:** FOUND — **HIGH**

~200 instances of `except Exception` across backend/. Worst offenders:
- `pipeline_ingest_runner.py`: 18 catch-all handlers
- `deep_review/service.py`: 14 catch-all handlers
- `unified_pipeline.py`: 7 catch-all handlers
- Several bare `except Exception:` without variable capture (`knowledge_builder.py:242`, `sponsor/service.py:62`, `domain_ai/service.py:49,62,174,222,270`)

Pipeline dispatch handlers (`pipeline_dispatch.py:148,212`) catch Exception in BackgroundTask `_run()` — the HTTP caller already received 202 and has no way to know the pipeline crashed except by polling job status.

### 3.2 Duplicate Orchestration Paths

**STATUS:** FOUND — **HIGH**

Four distinct document processing entry points:
1. `POST /ai/pipeline/ingest` — direct sync call to `run_pipeline_ingest()`, bypasses unified pipeline
2. `POST /ai/pipeline/ingest/full` — dispatches through `pipeline_dispatch.dispatch_ingest()`
3. `POST /ai/pipeline/deals/{id}/reanalyze` — creates own session via `async_session_factory()`, calls `run_deal_ai_analysis` directly
4. `POST /ai/pipeline/deals/{id}/bootstrap` — calls `async_bootstrap_deal()` via `asyncio.run()` in BackgroundTask

Paths 1, 3, 4 bypass validation gates, governance checks, and storage routing.

### 3.3 Missing Idempotency Guards

**STATUS:** FOUND — **HIGH**

Workers **with** advisory locks: `fact_sheet_gen` (900_005), `watchlist_batch` (900_003), `screening_batch` (900_002), `benchmark_ingest` (900_004), `drift_check` (900_001), `macro_ingestion` (900_100).

Workers **without** advisory locks:
- `run_ingestion` — concurrent runs duplicate Yahoo Finance API calls
- `run_risk_calc` — concurrent runs could produce inconsistent snapshots
- `run_portfolio_eval` — same risk as risk_calc
- `search_rebuild.py` — no concurrency guard, concurrent rebuilds race on upserts
- Credit `deep_review` dispatch — no guard against concurrent reviews for same deal
- Unified pipeline — no deduplication for same document submitted twice

### 3.4 Worker-Only Paths Not Documented

**STATUS:** FOUND — **MEDIUM**

4-5 wealth workers have no HTTP trigger endpoint:
- `drift_check.py` — has advisory lock but no route
- `regime_fit.py` — PyMC-guarded, no route
- `bayesian_cvar.py` — PyMC-guarded, no route
- `fred_ingestion.py` — separate from macro_ingestion, no route

These are only callable programmatically or via external scheduling. No documentation explains scheduling requirements.

### 3.5 PgNotifier Failure Silencing

**STATUS:** FOUND — **MEDIUM**

`pg_notify.py` has 5 bare `except Exception:` handlers (lines 54, 68, 101, 119, 128) that swallow connection errors. If PgNotifier fails to connect or reconnects fail, cache invalidation stops working — stale config served until TTL expiry (60s). No health check or metric exposes this state.

### 3.6 Lazy-Import Failure Masking

**STATUS:** PARTIAL — **MEDIUM**

`_assemble()` in `credit/modules/ai/__init__.py:92-146` catches all `Exception` types (line 105), not just `ImportError`. For required modules, it properly raises `RuntimeError` (good). For optional modules (extraction, portfolio), failures silently degrade. A syntax error in an optional sub-module would be treated as an import failure.

### 3.7 Sync/Async Boundary Issue

**STATUS:** PARTIAL — **LOW**

`extraction.py:299` uses `async_session_factory()` as a sync context manager — semantically wrong (should be `sync_session_factory`). May work due to Python fallback but is a latent bug.

---

## 4. False-Confidence Areas

| Area | System Map Says | Reality |
|------|----------------|---------|
| **Credit module tenant isolation** | "RLS enforced on all routes" | 65+ credit module routes skip `get_db_with_rls()`. DB-level RLS catches it (routes error), but the application layer does not set context. |
| **Single ingestion path** | "Unified pipeline is the single ingestion path" | 3+ alternative entry points bypass the pipeline's gates. |
| **Search tenant isolation** | "All search documents include organization_id" | 3 auxiliary upsert paths omit it. |
| **Config invalidation** | "PgNotifier invalidates on write" | Only covers overrides table, not defaults. PgNotifier failures are silently swallowed. |
| **ADLS source of truth** | "ADLS write failure = pipeline continues with warning" | Search index can be updated without ADLS having the data. |

---

## 5. Missing Critical Elements

| Element | Status | Notes |
|---------|--------|-------|
| **AuditEvent DB model** | Incomplete | `write_audit_event()` exists but full AuditEvent table/query surface is pending per `db/audit.py` |
| **API rate limiting** | Missing | Rate limiting for external APIs (FRED, EDGAR) exists, but no rate limiting on client-facing FastAPI endpoints |
| **APP_ENV production guard** | Missing | `validate_production_secrets()` does not verify `app_env != "development"`. Dev bypass available if `APP_ENV` not set. |
| **Config defaults invalidation** | Missing | No pg_notify trigger on `vertical_config_defaults` table — admin changes to defaults are not cache-invalidated |
| **Advisory locks for 3 workers** | Missing | `run_ingestion`, `run_risk_calc`, `run_portfolio_eval` lack concurrency guards |

---

## 6. Structural Risks

| # | Risk | Severity | Evidence |
|---|------|----------|----------|
| SR-1 | **Credit module RLS gap** — 65+ routes use `get_db()` instead of `get_db_with_rls()`. Routes error at runtime (safe) but are broken for multi-tenant use. | **HIGH** | `credit/modules/ai/*.py`, `credit/modules/deals/routes.py` all import from `engine.py` |
| SR-2 | **Search tenant leak paths** — 3 auxiliary search document builders omit `organization_id`. Documents in Azure Search are not filterable by tenant. | **HIGH** | `document_scanner.py:207-218`, `knowledge_builder.py:227-238`, `obligation_extractor.py:184-195` |
| SR-3 | **Pipeline bypass routes** — 3+ entry points skip unified pipeline gates (validation, governance, storage routing). | **HIGH** | `extraction.py:20-37,206-268,271-317` |
| SR-4 | **Missing worker idempotency** — `run_ingestion`, `run_risk_calc`, `run_portfolio_eval`, and deep review dispatch have no advisory locks. Concurrent invocations produce duplicate work or inconsistent state. | **HIGH** | `workers/ingestion.py`, `workers/risk_calc.py`, `workers/portfolio_eval.py` |
| SR-5 | **Broad exception swallowing** — ~200 catch-all handlers across pipeline code. Several bare `except Exception:` without variable capture. Pipeline failures after 202 response are invisible to callers. | **MEDIUM** | `pipeline_ingest_runner.py` (18), `deep_review/service.py` (14), `unified_pipeline.py` (7) |
| SR-6 | **ADLS/Search consistency gap** — Pipeline continues to Search upsert after ADLS write failure. Violates source-of-truth principle. | **MEDIUM** | `unified_pipeline.py:798-803,811-860` |
| SR-7 | **PgNotifier silent failure** — 5 bare exception handlers swallow connection errors. No health metric exposes notification subsystem state. | **MEDIUM** | `pg_notify.py:54,68,101,119,128` |
| SR-8 | **Dev bypass default-enabled** — `app_env` defaults to `"development"`. Production guard (`validate_production_secrets()`) does not check `app_env`. If `APP_ENV` env var unset, dev auth bypass is available. | **MEDIUM** | `settings.py:38,126-138`, `clerk_auth.py:130-133` |
| SR-9 | **Stale adobe_sign references** — 4 vestigial references (`settings.py:76`, `0003_credit_domain.py:173`, `deals/schemas/deals.py:73`, `ic_memos.py:68`) to removed operational module. | **LOW** | Settings field, DB column, schema field, ORM column |
| SR-10 | **Undocumented worker scheduling** — 4-5 wealth workers (`drift_check`, `regime_fit`, `bayesian_cvar`, `fred_ingestion`) have no HTTP trigger and require external scheduling with no documentation. | **LOW** | `workers/drift_check.py`, `workers/regime_fit.py`, `workers/bayesian_cvar.py`, `workers/fred_ingestion.py` |

---

## Validation Summary

| Category | VALIDATED | PARTIALLY VALIDATED | INVALID | Total |
|----------|-----------|-------------------|---------|-------|
| Auth & Tenancy | 5 | 1 | 0 | 6 |
| Config & Registry | 2 | 2 | 0 | 4 |
| Pipeline & Storage | 2 | 2 | 0 | 4 |
| Jobs & SSE | 3 | 0 | 0 | 3 |
| Import Architecture | 3 | 0 | 0 | 3 |
| Storage | 2 | 0 | 0 | 2 |
| **Total** | **17** | **5** | **0** | **22** |

**Contradictions found:** 6 (3 HIGH, 2 MEDIUM, 1 LOW)
**Hidden complexity patterns:** 7 (3 HIGH, 3 MEDIUM, 1 LOW)
**Structural risks:** 10 (4 HIGH, 4 MEDIUM, 2 LOW)

---

*Audit generated: 2026-03-18*
*Baseline document: `docs/audit/backend-system-map-v2.md`*
*Method: Staged pipeline — claims extraction → parallel scoped validation (4 agents) → assembly*
