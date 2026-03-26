# Backend System Map v2 — Netz Analysis Engine

> Generated: 2026-03-26
> Profile: `netz-backend`
> Scope: `backend/app/`, `backend/ai_engine/`, `backend/vertical_engines/`, `backend/quant_engine/`, `infra/`

---

## 1. Architecture Overview

### 1.1 Runtime Boundaries

| Boundary | Technology | Entry Point |
|----------|-----------|-------------|
| **API** | FastAPI (uvicorn, 4 workers prod) | `backend/app/main.py:app` |
| **Workers** | FastAPI BackgroundTasks + Redis idempotency | `backend/app/domains/wealth/workers/*.py` (24 files) |
| **Scheduler** | Cloudflare Cron Worker | `infra/cloudflare/cron/src/index.ts` |
| **Database** | PostgreSQL 16 + TimescaleDB + pgvector | `backend/app/core/db/engine.py` (asyncpg pool) |
| **Cache / PubSub** | Redis 7 (Upstash prod) | `backend/app/core/jobs/tracker.py` |
| **Storage** | StorageClient (R2 prod, LocalStorage dev) | `backend/app/services/storage_client.py` |
| **Auth** | Clerk JWT v2 | `backend/app/core/security/clerk_auth.py` |

### 1.2 Subsystem Responsibilities

| Subsystem | Responsibility |
|-----------|---------------|
| `backend/app/core/` | Auth, tenancy (RLS), DB sessions, config (ConfigService), jobs (SSE), audit |
| `backend/app/domains/` | Route handlers, schemas, domain models, workers |
| `backend/ai_engine/` | Domain-agnostic: unified pipeline, hybrid classification, OCR, chunking, embedding, governance, validation, storage routing, search rebuild |
| `backend/vertical_engines/` | Domain-specific: analysis logic, prompts, scoring. One directory per vertical |
| `backend/quant_engine/` | Universal quant services: CVaR, regime, optimizer, scoring, drift, attribution, macro |
| `backend/app/services/` | Cross-cutting: StorageClient, DuckDB, text extraction |

### 1.3 Request Flow (Simplified)

```
Client → Clerk JWT → get_actor() → get_db_with_rls() → SET LOCAL org_id
  → Router → Domain Service → Vertical Engine → (AI Engine | Quant Engine)
  → Persistence (PostgreSQL + StorageClient + pgvector)
  → SSE (Redis pub/sub → EventSourceResponse)
```

---

## 2. Canonical Backend Flows

### 2.1 Document Ingestion (Unified Pipeline)

**Entry point:** `backend/ai_engine/pipeline/unified_pipeline.py:process()`
**Orchestrator:** `process(request: IngestRequest, *, db, actor_id, skip_index)` → `PipelineStageResult`

| Stage | Module | Function | Persistence |
|-------|--------|----------|-------------|
| 1. Pre-filter | `unified_pipeline.py` | `should_skip_document(filename)` | — |
| 2. OCR | `extraction/mistral_ocr.py` | `async_extract_pdf_with_mistral()` | OCR cache (SHA256, in-memory) |
| **Gate 1** | `pipeline/validation.py` | `validate_ocr_output()` — min 100 chars, max 30% non-printable | Halts on fail |
| 3. Classification | `classification/hybrid_classifier.py` | `classify(text, filename)` — 3-layer (rules→cosine→LLM) | — |
| **Gate 2** | `pipeline/validation.py` | `validate_classification()` — canonical doc_type check | Halts on invalid type |
| 4. Governance | `extraction/governance_detector.py` | `detect_governance(text)` — 15 regex patterns, zero-cost | — |
| 5. Chunking | `extraction/semantic_chunker.py` | `chunk_document()` — adaptive by doc_type (400–2000 chars) | — |
| **Gate 3** | `pipeline/validation.py` | `validate_chunks()` — count > 0, loss < 25% | Halts on fail |
| 6. Metadata extraction | `extraction/document_intelligence.py` | `async_run_document_intelligence()` — gpt-4.1/5.1 | — |
| 7. Embedding | `extraction/embedding_service.py` | `async_generate_embeddings()` — text-embedding-3-large (3072 dims) | — |
| **Gate 4** | `pipeline/validation.py` | `validate_embeddings()` — count match, no NaN, dim 3072 | Halts on fail |
| 8. Storage write | `app/services/storage_client.py` | `StorageClient.write()` | Bronze JSON, Silver Parquet+metadata |
| 9. Vector index | `extraction/pgvector_search_service.py` | `upsert_chunks()` | pgvector `vector_chunks` table |

**Dual-write ordering:** StorageClient FIRST (source of truth) → pgvector SECOND (derived index).
**SSE:** `_emit(version_id, event_type, data)` via Redis pub/sub throughout stages.
**Tenant boundary:** `IngestRequest.org_id` from JWT; all storage paths include `{org_id}/{vertical}/`; pgvector queries include `WHERE organization_id = :org_id`.

### 2.2 Batch Pipeline Ingest

**Entry point:** `backend/ai_engine/ingestion/pipeline_ingest_runner.py:run_full_pipeline_ingest()`

| Stage | Module | Purpose |
|-------|--------|---------|
| 1. Document scan | `document_scanner.py` | Blob containers → `DocumentRegistry` rows |
| 2. Deal discovery | `vertical_engines/credit/pipeline/` | Extract deal folder structure → `PipelineDeal` rows |
| 3. Registry bridge | `registry_bridge.py` | Connect `DocumentRegistry` → `DealDocument` (idempotent) |
| 4. Per-document ingest | `unified_pipeline.process()` | 9-stage pipeline per document |
| 5. Deep review | Deep review orchestrator | IC memo generation + validation |

**Tracking:** `PipelineIngestJob` row (status RUNNING → COMPLETED/FAILED) with counters.

### 2.3 Credit Deep Review (IC Memo)

**Entry point:** `backend/vertical_engines/credit/deep_review/service.py:run_deal_deep_review_v4()`
**Route:** `POST /api/v1/ai/deep-review/process`

13 stages: Deal validation → RAG context → structured analysis → macro injection → quant profile → concentration → hard policy → soft policy → critique → memo generation → evidence saturation → confidence scoring → decision anchor → persistence.

**Key dependencies:**
- `retrieval/` — IC-grade evidence governance, per-chapter retrieval with saturation enforcement
- `market_data/` — cached macro snapshot from `macro_data` hypertable (zero FRED API)
- `quant/` — deterministic quant profile (maturity, rates, scenarios, sensitivity)
- `critic/` — adversarial review with circuit-breaker + 3-min timeout
- `memo/` — 14-chapter memo book with batch OpenAI submission
- `sponsor/` — sponsor & key person analysis (LLM-driven)
- `edgar/` — SEC EDGAR financials, ratios, going concern, insider signals
- `kyc/` — KYC Spider screening (never-raises)

**Error contract:** Never raises at service level — returns dict with status.
**Persistence:** Gold layer memo JSON via StorageClient + pgvector evidence index + audit trail.

### 2.4 Wealth DD Report

**Entry point:** `backend/vertical_engines/wealth/dd_report/dd_report_engine.py:DDReportEngine.generate()`
**Route:** `POST /api/v1/dd-reports`

8-chapter report: chapters 1-7 parallel (ThreadPoolExecutor, max_workers=5), chapter 8 (recommendation) sequential.

**Injections:** `quant_injection.py` (risk metrics from DB), `sec_injection.py` (13F, ADV, NPORT), `peer_injection.py` (peer comparison).
**Error contract:** Never raises — returns `DDReportResult(status='failed')`.
**Thread safety:** Frozen dataclasses (`ChapterResult`, `DDReportResult`, `EvidencePack`) cross thread boundaries.

### 2.5 Wealth Screening

**Entry point:** `backend/vertical_engines/wealth/screener/service.py:ScreenerService.screen_instrument()`
**Route:** `POST /api/v1/screener`

3-layer deterministic (no LLM): eliminatory → mandate fit → quant scoring.
**Batch worker:** `screening_batch.py` — runs per-org with advisory lock, chunked commits (200 per batch).

### 2.6 Worker Orchestration

**Entry point:** `backend/app/domains/admin/routes/worker_registry.py:get_worker_registry()`
**Dispatch:** `POST /internal/workers/dispatch` (Cloudflare Cron) or `POST /api/v1/workers/run-{name}` (admin UI)

**Lifecycle:**
1. Cloudflare Cron fires → POST to `/internal/workers/dispatch` with `X-Worker-Secret`
2. Backend resolves workers from registry (21 workers: 7 global + 14 org-scoped)
3. Idempotency check: Redis `worker:{name}:{scope}:status`
4. Advisory lock: `pg_try_advisory_lock(LOCK_ID)` (non-blocking)
5. Execute in `BackgroundTasks.add_task(idempotent_worker_wrapper, ...)`
6. Timeout: `asyncio.wait_for()` (300-600s per worker)
7. Terminal state: Redis `mark_worker_completed/failed()`

### 2.7 SSE Job Streaming

**Entry point:** `backend/app/core/jobs/sse.py:create_job_stream()`
**Route:** `GET /api/v1/jobs/{job_id}/stream`

**Lifecycle:**
1. `register_job_owner(job_id, org_id)` — Redis key with 3600s TTL
2. Workers call `publish_event(job_id, event_type, data)` via Redis pub/sub channel `job:{id}:events`
3. SSE endpoint subscribes to channel, streams events with 15s heartbeat
4. Terminal events: `done`, `error`, `ingestion_complete`, `memo_complete`, `report_completed`, `report_failed`
5. `persist_job_state()` caches terminal result; `GET /api/v1/jobs/{job_id}/status` serves fallback

### 2.8 Search Rebuild

**Entry point:** `backend/ai_engine/pipeline/search_rebuild.py:rebuild_search_index()`

Reads silver Parquet from StorageClient, validates `embedding_model` + `embedding_dim`, upserts to pgvector. No OCR/LLM calls. Advisory lock via Redis key.

---

## 3. Package Boundary Map

### 3.1 `backend/app/core/` — Infrastructure Layer

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `security/clerk_auth.py` | Clerk JWT v2 verification, Actor model, role guards | `get_actor()`, `require_role()`, `require_fund_access()`, `clerk_org_to_uuid()` | Canonical |
| `tenancy/middleware.py` | RLS context via `SET LOCAL` | `get_db_with_rls()`, `set_rls_context()` | Canonical |
| `db/engine.py` | Async session factory (asyncpg pool: 20+10 overflow) | `async_session_factory`, `sync_session_factory` | Canonical |
| `db/audit.py` | Immutable audit trail (JSONB before/after) | `write_audit_event()`, `get_audit_log()` | Canonical |
| `db/base.py` | ORM mixins: `IdMixin`, `OrganizationScopedMixin`, `FundScopedMixin`, `AuditMetaMixin` | All mixins | Canonical |
| `config/config_service.py` | 4-tier config: TTLCache → DB override → DB default → YAML fallback | `ConfigService.get()`, `.deep_merge()`, `.invalidate()` | Canonical |
| `config/registry.py` | Config domain registry with IP protection | `ConfigRegistry.get()`, `.client_visible_types()` | Canonical |
| `config/pg_notify.py` | PgNotifier for cache invalidation on DB changes | Lifespan listener | Canonical |
| `jobs/tracker.py` | Redis pub/sub job tracking + ownership | `register_job_owner()`, `publish_event()`, `subscribe_job()`, `persist_job_state()` | Canonical |
| `jobs/sse.py` | SSE endpoint with heartbeat | `create_job_stream()` → `EventSourceResponse` | Canonical |
| `jobs/worker_idempotency.py` | Redis-based worker state machine | `check_worker_status()`, `mark_worker_running/completed/failed()`, `idempotent_worker_wrapper()` | Canonical |
| `middleware/rate_limit.py` | Rate limiting middleware | `RateLimitMiddleware` | Canonical |

### 3.2 `backend/app/domains/` — Domain Layer

| Package | Routes | Models | Workers | Status |
|---------|--------|--------|---------|--------|
| `admin/` | 8 routers (branding, assets, configs, tenants, prompts, health, audit, inspect) + internal dispatch | `models.py` | — | Canonical |
| `credit/` | 25 routers (deals, portfolio, documents, reporting, dashboard, actions, AI modules) | Per-module models | — | Canonical |
| `credit/modules/ai/` | Router assembly: 8 sub-modules (copilot, documents, compliance, pipeline_deals, extraction, portfolio, deep_review, memo_chapters, artifacts) | `models.py` | — | Canonical |
| `wealth/` | 20+ routers, 25 models, 20+ schemas, 18 workers | 25 model files | 24 worker files | Canonical |

**Structural note:** Credit is modular (package-per-feature with sub-modules). Wealth is flat (single-level routes/models/schemas/workers).

### 3.3 `backend/ai_engine/` — Domain-Agnostic AI Core

| Package | Purpose | Key Files | Status |
|---------|---------|-----------|--------|
| `pipeline/` | Unified 9-stage pipeline + 4 gates | `unified_pipeline.py`, `models.py`, `validation.py`, `storage_routing.py`, `search_rebuild.py` | Canonical |
| `classification/` | 3-layer hybrid classifier (rules→cosine→LLM) | `hybrid_classifier.py` | Canonical |
| `extraction/` | OCR, chunking, embedding, entity bootstrap, reranker, governance, document intelligence | `mistral_ocr.py`, `local_vlm_ocr.py`, `semantic_chunker.py`, `embedding_service.py`, `entity_bootstrap.py`, `local_reranker.py`, `governance_detector.py`, `document_intelligence.py`, `pgvector_search_service.py` | Canonical |
| `ingestion/` | Batch pipeline orchestration | `pipeline_ingest_runner.py`, `document_scanner.py`, `registry_bridge.py`, `monitoring.py` | Canonical |
| `validation/` | Vector integrity, deep review validation, eval runner | `vector_integrity_guard.py`, `deep_review_validation_runner.py`, `eval_runner.py` | Canonical |
| `prompts/` | Jinja2 templates (Netz IP) | Classification, extraction, compliance templates | Canonical |
| `cache/` | OCR dedup cache (SHA256, in-memory) | `provider_cache.py` | Canonical |
| `openai_client.py` | OpenAI Responses API + Azure AI Foundry fallback | `create_completion()`, `create_embedding()` | Canonical |

### 3.4 `backend/vertical_engines/credit/` — Credit Vertical (14 packages)

| Package | Purpose | Entry Point | Error Contract | Status |
|---------|---------|-------------|----------------|--------|
| `critic/` | Adversarial IC review | `critique_intelligence()` | Never raises | Canonical |
| `deal_conversion/` | Pipeline → Portfolio | `convert_pipeline_to_portfolio()` | Raises on failure | Canonical |
| `deep_review/` | 13-stage IC memo V4 | `run_deal_deep_review_v4()` | Never raises | Canonical, Core |
| `domain_ai/` | Hybrid retrieval + analysis | Internal to deep_review | Never raises | Canonical |
| `edgar/` | SEC EDGAR financials | `fetch_edgar_data()`, `fetch_edgar_multi_entity()` | Never raises | Canonical |
| `kyc/` | KYC Spider screening | `run_kyc_screenings()` | Never raises | Canonical |
| `market_data/` | Macro snapshot (DB-only) | `get_macro_snapshot()` | Never raises | Canonical |
| `memo/` | 14-chapter memo book | `generate_memo_book()` | Never raises | Canonical |
| `pipeline/` | Deal discovery & monitoring | `run_pipeline_ingest()` | Never raises | Canonical |
| `portfolio/` | Portfolio monitoring | `run_portfolio_ingest()` | Never raises | Canonical |
| `quant/` | Deterministic quant profile | `compute_quant_profile()` | Raises on failure | Canonical |
| `retrieval/` | IC-grade evidence governance | `gather_chapter_evidence()`, `build_ic_corpus()`, `enforce_evidence_saturation()` | Never raises | Canonical |
| `sponsor/` | Sponsor & key person analysis | `analyze_sponsor()` | Never raises | Canonical |
| `underwriting/` | Underwriting artifacts | Support module | — | Canonical |

**Import rules (enforced by import-linter):**
- `models.py` → leaf node, zero sibling imports
- Helpers → import from models, NOT from `service.py`
- `service.py` → sole orchestrator, imports all siblings + external engines
- Credit ↔ Wealth — zero cross-imports

### 3.5 `backend/vertical_engines/wealth/` — Wealth Vertical (14 packages + 6 engines)

| Package | Purpose | Entry Point | Status |
|---------|---------|-------------|--------|
| `dd_report/` | 8-chapter DD report | `DDReportEngine.generate()` | Canonical, Core |
| `screener/` | 3-layer deterministic screening | `ScreenerService.screen_instrument()` | Canonical |
| `mandate_fit/` | Constraint evaluator | `MandateFitService.evaluate_instrument()` | Canonical |
| `peer_group/` | Peer matching & ranking | `PeerGroupService` | Canonical |
| `correlation/` | Rolling correlation, MP denoising | `CorrelationService` | Canonical |
| `attribution/` | Brinson-Fachler attribution | `AttributionService.compute_portfolio_attribution()` | Canonical |
| `fee_drag/` | Fee drag ratio | `FeeAnalysis` | Canonical |
| `asset_universe/` | Fund universe governance | `UniverseService` | Canonical |
| `watchlist/` | PASS→FAIL transition detection | `WatchlistService.check_transitions()` | Canonical |
| `rebalancing/` | Rebalance impact & weight proposer | `RebalancingService.compute_rebalance_impact()` | Canonical |
| `model_portfolio/` | Portfolio construction | `ModelPortfolio` | Canonical |
| `monitoring/` | Drift + alert engine | `scan_drift()`, `AlertEngine` | Canonical |
| `critic/` | Adversarial DD chapter review | `critique_dd_report()` | Canonical |
| `fact_sheet/` | PDF renderers (PT/EN i18n) | `fact_sheet_engine.py` | Canonical |

**Standalone engines:**

| File | Class | Purpose | Status |
|------|-------|---------|--------|
| `fund_analyzer.py` | `FundAnalyzer` | `BaseAnalyzer` implementation (orchestrator) | Canonical |
| `quant_analyzer.py` | `QuantAnalyzer` | CVaR, scoring, peer comparison | Canonical |
| `macro_committee_engine.py` | `MacroCommitteeEngine` | Weekly regional macro reports | Canonical |
| `flash_report.py` | `FlashReport` | Event-driven market flash (48h cooldown) | Canonical |
| `investment_outlook.py` | `InvestmentOutlook` | Quarterly macro narrative | Canonical |
| `manager_spotlight.py` | `ManagerSpotlight` | Deep-dive fund manager analysis | Canonical |

### 3.6 `backend/quant_engine/` — Universal Quant Services (21 modules)

| Module | Scope | Key Entry Points | Status |
|--------|-------|-----------------|--------|
| `cvar_service.py` | Wealth portfolio | `compute_rolling_cvar()`, `check_breach_status()` | Canonical |
| `regime_service.py` | Macro signals | `classify_regime()`, `get_current_regime()` | Canonical |
| `scoring_service.py` | Wealth DD | `compute_fund_score()` | Canonical |
| `portfolio_metrics_service.py` | Wealth portfolio | `aggregate()` → Sharpe, Sortino, max drawdown | Canonical |
| `drift_service.py` | Wealth monitoring | `compute_dtw_drift()`, `classify_drift_status()` | Canonical |
| `attribution_service.py` | Wealth attribution | `compute_attribution()`, `compute_multi_period_attribution()` | Canonical |
| `optimizer_service.py` | Wealth construction | `optimize_portfolio()` — cvxpy + CLARABEL | Canonical |
| `rebalance_service.py` | Wealth monitoring | `determine_cascade_action()` — state machine | Canonical |
| `peer_comparison_service.py` | Wealth comparison | Type definitions | Canonical |
| `talib_momentum_service.py` | Credit context | Pre-computed RSI, Bollinger, OBV | Canonical |
| `macro_snapshot_builder.py` | Credit context | Macro assembly from hypertables | Canonical |
| `regional_macro_service.py` | Macro context | Regional Case-Shiller, ICE spreads | Canonical |
| `fiscal_data_service.py` | Macro context | Treasury/debt from hypertable | Canonical |
| `ofr_hedge_fund_service.py` | Macro context | OFR leverage/AUM from hypertable | Canonical |
| `stress_severity_service.py` | Macro context | Aggregated stress index | Canonical |
| `correlation_regime_service.py` | Wealth | Correlation + regime awareness | Canonical |
| `backtest_service.py` | Credit backtest | Historical scenario evaluation | Canonical |
| `style_analysis.py` | Wealth analysis | Style/factor decomposition | Canonical |

**Pattern:** Config resolved once at async entry point via `ConfigService.get()`, passed as parameter to sync functions. No YAML loading, no `@lru_cache`.

---

## 4. Legacy / Transitional Map

### 4.1 Deprecated Azure Services (Files Retained for Rollback)

| Service | Replacement | Evidence |
|---------|-------------|---------|
| Azure Key Vault | Railway env vars | `CLAUDE.md` env var section |
| Azure Service Bus | Redis + BackgroundTasks | Worker dispatch via `worker_registry.py` |
| Application Insights | structlog → stdout | No Azure SDK imports in active code |
| Azure OpenAI | OpenAI direct (Responses API) | `openai_client.py` uses `/v1/responses` |
| Azure AI Search | pgvector | `pgvector_search_service.py` (commit 497df51) |
| ADLS Gen2 | R2StorageClient | `storage_client.py` — `create_storage_client()` checks `FEATURE_R2_ENABLED` |

**ADLSStorageClient:** Kept in `storage_client.py` but never instantiated when `FEATURE_R2_ENABLED=true`. Rollback path only.

### 4.2 Eliminated Modules (Clean)

| Module | Status | Evidence |
|--------|--------|---------|
| `cash_management/` | Removed (operational) | Not found in codebase |
| `compliance/` (operational) | Removed | Only AI governance patterns remain (in-scope) |
| `signatures/` | Removed | Not found |
| `counterparties/` | Removed | Not found |
| `adobe_sign/` | Removed | Not found |

**Note:** `modules/deals/cashflow_service.py` is IN SCOPE (analytical: disbursements, MOIC, IRR).

### 4.3 Legacy Quant References

| File | Status |
|------|--------|
| `quant_engine/fred_service.py` | Deprecated in hot path — workers only. Routes read from `macro_data` hypertable |

### 4.4 Transitional Patterns

| Pattern | Location | Status |
|---------|----------|--------|
| Wealth `funds` router | `wealth/routes/funds.py` | DEPRECATED — backward compat (line 360 in main.py) |
| `credit/dashboard/fred_client.py` | Dashboard module | Legacy — should read from `macro_data` hypertable like `market_data/` |

---

## 5. State, Config, and Runtime Policy Map

### 5.1 Configuration Resolution

**Canonical path:** `ConfigService.get(vertical, config_type, org_id)`

```
1. TTLCache (60s, in-process) → cache hit
2. DB: VerticalConfigOverride (RLS-scoped to org) → org-specific override
3. DB: VerticalConfigDefault (no RLS) → global default
4. YAML fallback (emergency, logged as ERROR) → profiles/ or calibration/
```

**Source of truth:** PostgreSQL (`vertical_config_defaults` + `vertical_config_overrides` tables).
**YAML files:** Seed data only — `profiles/` and `calibration/` directories.
**Cache invalidation:** PgNotifier (LISTEN/NOTIFY on config changes) → `ConfigService.invalidate()`.

### 5.2 Config Registry

**File:** `backend/app/core/config/registry.py`

Registers all valid `(vertical, config_type)` pairs as `ConfigDomain` dataclasses with:
- `ownership`: "config_service" or "prompt_service"
- `client_visible`: IP protection flag
- `required`: whether config must exist

**IP protection:** `CLIENT_VISIBLE_TYPES` allowlist — prompts, chapters, governance_policy are never returned to clients.

### 5.3 Environment Variables

**Core runtime:**
- `DATABASE_URL` — asyncpg connection (Timescale Cloud prod, docker-compose dev)
- `REDIS_URL` — pub/sub, idempotency, job tracking
- `CLERK_SECRET_KEY` / `CLERK_JWKS_URL` — JWT verification
- `OPENAI_API_KEY` / `OPENAI_EMBEDDING_MODEL` — LLM + embeddings
- `MISTRAL_API_KEY` — OCR
- `FEATURE_R2_ENABLED` / `R2_*` — production storage

**Feature flags:**
- `FEATURE_R2_ENABLED` — switches StorageClient from LocalStorage to R2

### 5.4 Tenant-Specific Behavior

| Mechanism | Location | Scope |
|-----------|----------|-------|
| RLS (`SET LOCAL app.current_organization_id`) | `tenancy/middleware.py` | All tenant-scoped queries |
| `VerticalConfigOverride` | `config_service.py` | Org-specific config |
| Worker dispatch per org | `internal.py:_get_active_org_ids()` | Org-scoped workers |
| Storage paths | `storage_routing.py` | `{org_id}/{vertical}/` prefix |
| pgvector queries | `pgvector_search_service.py` | `WHERE organization_id = :org_id` |
| DuckDB queries | Callers | `WHERE organization_id = ?` |
| Audit events | `audit.py` | `organization_id` column |

### 5.5 Global (No-Tenant) Tables

```
macro_data, allocation_blocks, vertical_config_defaults, benchmark_nav,
macro_regional_snapshots, treasury_data, ofr_hedge_fund_data, bis_statistics,
imf_weo_forecasts, sec_nport_holdings, sec_13f_holdings, sec_13f_diffs,
sec_managers, sec_manager_funds
```

No `organization_id`, no RLS. Shared across all tenants. Populated by global workers.

---

## 6. Auditability / Operator Visibility Map

### 6.1 Audit Trail

**File:** `backend/app/core/db/audit.py`
**Function:** `write_audit_event(db, fund_id, actor_id, actor_roles, action, entity_type, entity_id, before, after, request_id, organization_id)`
**Model:** `AuditEvent` — TimescaleDB hypertable (1-week chunks, compression at 1 month, segmentby: organization_id)
**Usage:** 17+ modules for entity-level change tracking (CREATE/UPDATE/DELETE with JSONB snapshots).
**Retrieval:** `get_audit_log()` — RLS-scoped, ordered by `created_at DESC`, limit 200.

### 6.2 Job Tracking

| Mechanism | Storage | TTL |
|-----------|---------|-----|
| Worker idempotency | Redis `worker:{name}:{scope}:status` | Running: 3600s, Completed: 300s, Failed: 1800s |
| Job ownership | Redis `job:{id}:org` | 3600s (refresh available) |
| Job terminal state | Redis `job:{id}:state` | 3600s |
| Pipeline ingest job | PostgreSQL `PipelineIngestJob` | Permanent |

### 6.3 SSE Progress Streaming

**Flow:** Worker → `publish_event()` → Redis channel `job:{id}:events` → `EventSourceResponse` → Client
**Heartbeat:** 15s (prevents Azure/Cloudflare idle timeout at 30s)
**Fallback:** `GET /api/v1/jobs/{job_id}/status` polls terminal state from Redis
**Frontend:** `fetch()` + `ReadableStream` (not EventSource — auth headers required)

### 6.4 Structured Failure Handling

| Component | Failure Behavior |
|-----------|-----------------|
| Unified pipeline gates | Halt pipeline, return `PipelineStageResult(success=False)` |
| StorageClient write failure | Pipeline stops (source of truth unavailable) |
| pgvector upsert failure | Warning logged, data safe in storage, rebuild via `search_rebuild.py` |
| Worker advisory lock contention | Skip with `{"status": "skipped"}`, no retry |
| Worker timeout | `asyncio.wait_for()` raises `TimeoutError`, marked failed in Redis |
| Vertical engine orchestrators | Never-raises pattern — return status dict with warnings |
| Quant pure-computation | Raises on failure — math errors should propagate |
| LLM API failures | Exponential backoff (base 2.0, max 5 attempts, jitter ±10%) |
| OCR failure | Fallback: Mistral → Local VLM → PyMuPDF |

### 6.5 Structured Logging

All services use `structlog` → stdout. No Application Insights dependency. Worker execution logged with:
- `worker_name`, `scope`, `lock_id`, `elapsed_seconds`
- `status` (completed/skipped/failed), `error` (on failure)
- `rows_processed`, `chunks_upserted` (where applicable)

---

## 7. Worker Infrastructure

### 7.1 Worker Registry (21 Workers)

**File:** `backend/app/domains/admin/routes/worker_registry.py`

**Global workers (15):**

| Worker | Lock ID | Hypertable | Source | Frequency |
|--------|---------|-----------|--------|-----------|
| `macro_ingestion` | 43 | `macro_data` | FRED API (~65 series) | Daily 6am |
| `benchmark_ingest` | 900_004 | `benchmark_nav` | Yahoo Finance | Daily 6am |
| `treasury_ingestion` | 900_011 | `treasury_data` | US Treasury API | Daily 6am |
| `ofr_ingestion` | 900_012 | `ofr_hedge_fund_data` | OFR API | Weekly Mon 8am |
| `bis_ingestion` | 900_014 | `bis_statistics` | BIS SDMX API | Quarterly |
| `imf_ingestion` | 900_015 | `imf_weo_forecasts` | IMF DataMapper | Quarterly |
| `nport_ingestion` | 900_018 | `sec_nport_holdings` | SEC EDGAR N-PORT | Quarterly |
| `sec_13f_ingestion` | 900_021 | `sec_13f_holdings`, `sec_13f_diffs` | SEC EDGAR 13F-HR | Weekly |
| `sec_adv_ingestion` | 900_022 | `sec_managers`, `sec_manager_funds` | SEC FOIA CSV | Monthly |
| `sec_refresh` | 900_016 | Continuous aggregates | Computed | Quarterly |
| `brochure_download` | 900_019 | — | ADV brochure PDF | On-demand |
| `brochure_extract` | 900_020 | — | Text extraction | On-demand |
| `esma_ingestion` | 900_023 | — | ESMA UCITS universe | On-demand |
| `nport_fund_discovery` | 900_024 | — | SEC EDGAR N-PORT | On-demand |
| `nport_ticker_resolution` | 900_025 | — | OpenFIGI | On-demand |

**Org-scoped workers (6):**

| Worker | Lock ID | Target | Frequency |
|--------|---------|--------|-----------|
| `ingestion` | 900_006 | NAV ingestion | Daily 6:30am |
| `instrument_ingestion` | 900_010 | `nav_timeseries` | Daily 6:30am |
| `risk_calc` | 900_007 | `fund_risk_metrics` | Daily 7am |
| `portfolio_eval` | 900_008 | `portfolio_snapshots` | Daily 7:30am |
| `screening_batch` | 900_002 | Screening results | Daily 8am |
| `watchlist_batch` | 900_003 | Transition alerts | Daily 8am |

### 7.2 Cron Schedule

**File:** `infra/cloudflare/cron/wrangler.toml`

```
0 6 * * *    → macro_ingestion, benchmark_ingest, treasury_ingestion
0 6:30 * * * → ingestion, instrument_ingestion
0 7 * * *    → risk_calc
0 7:30 * * * → portfolio_eval, drift_check, regime_fit
0 8 * * *    → screening_batch, watchlist_batch
0 8 * * 1    → ofr_ingestion (Monday only)
0 5 1 */3 *  → sec_refresh, nport_ingestion, bis_ingestion, imf_ingestion (quarterly)
```

### 7.3 Seed Script

**File:** `backend/scripts/run_workers_seed.py`
Runs global ingestion workers sequentially for initial data population: macro → treasury → benchmark → OFR → BIS → IMF.

---

## 8. Router Registration Map

### 8.1 API Structure

**File:** `backend/app/main.py`

```
FastAPI App (app.main:app)
├── Middleware: CORSMiddleware (outer) + RateLimitMiddleware (inner)
├── Global exception handler → CORS-safe 500 JSONResponse
├── /health, /api/health — dual mount (Cloudflare gateway compat)
├── /internal/* — Cloudflare Cron Worker (root level, X-Worker-Secret auth)
└── /api/v1/ (53 domain routers)
    ├── Admin (8): branding, assets, configs, tenants, prompts, health, audit, inspect
    ├── Wealth (20+): funds†, instruments, allocation, analytics, portfolios, risk,
    │   macro, workers, dd-reports, documents, universe, model-portfolios, fact-sheets,
    │   content, screener, manager-screener, strategy-drift, attribution,
    │   correlation-regime, esma, exposure, blended-benchmark, sec-analysis, sec-funds
    ├── Credit (25):
    │   ├── Deals: deals, ic-memos, provenance, convert
    │   ├── Portfolio: assets, alerts, obligations, actions, investments
    │   ├── Documents: uploads, upload-url, review, evidence, auditor, ingest
    │   ├── Reporting: report-packs, investor-portal, evidence-packs, reports, schedules
    │   ├── Dashboard: dashboard, task-inbox
    │   └── Modules: ai (aggregated), pipeline-deals, documents
    └── Core: jobs/{id}/stream (SSE), jobs/{id}/status, test/sse (dev)
```

† `funds` router is DEPRECATED (backward compat).

---

## 9. Data Contracts Summary

### 9.1 Pipeline Data Contracts

**File:** `backend/ai_engine/pipeline/models.py`

| Dataclass | Purpose | Frozen |
|-----------|---------|--------|
| `IngestRequest` | Request envelope (source, org_id, vertical, document_id, blob_uri, filename) | Yes |
| `HybridClassificationResult` | Classification output (doc_type, vehicle_type, confidence, layer) | Yes |
| `PipelineStageResult` | Stage/gate result (stage, success, data, metrics, warnings, errors) | Yes |

**Canonical types:**
- `CANONICAL_DOC_TYPES` — 31 types (frozenset)
- `CANONICAL_VEHICLE_TYPES` — 11 types (frozenset)

### 9.2 Storage Path Contracts

**File:** `backend/ai_engine/pipeline/storage_routing.py`

| Function | Path Pattern |
|----------|-------------|
| `bronze_upload_blob_path()` | `bronze/{org_id}/{fund_id}/documents/{version_id}/{filename}` |
| `bronze_document_path()` | `bronze/{org_id}/{vertical}/documents/{doc_id}.json` |
| `silver_chunks_path()` | `silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet` |
| `silver_metadata_path()` | `silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json` |
| `gold_memo_path()` | `gold/{org_id}/{vertical}/memos/{memo_id}.json` |
| `gold_fact_sheet_path()` | `gold/{org_id}/{vertical}/fact_sheets/{portfolio_id}/{date}/{lang}/{file}` |
| `gold_content_path()` | `gold/{org_id}/{vertical}/content/{type}/{id}/{lang}/report.pdf` |
| `global_reference_path()` | `_global/{data_type}/{filename}` |

Path validation: `^[a-zA-Z0-9][a-zA-Z0-9._\-]*$` per segment. Prevents path traversal.

### 9.3 Parquet Schema Requirements

All silver Parquet files must include:
- `embedding_model` column (e.g., "text-embedding-3-large")
- `embedding_dim` column (e.g., 3072)
- zstd compression
- `organization_id` as column AND path segment

`search_rebuild.py` validates dimension match before upserting — prevents silent corruption on model upgrade.

---

## 10. Structural Risks

> These are architecture-level observations, not remediation recommendations.

### 10.1 Wealth Domain Flat Structure

Wealth domain (`app/domains/wealth/`) uses a flat file structure (25 model files, 20+ route files, 24 worker files at the same level) vs credit's modular package-per-feature pattern. As wealth grows, this may become harder to navigate and maintain. No import boundary enforcement within the wealth domain beyond the vertical engine level.

### 10.2 Credit Dashboard fred_client.py

`backend/app/domains/credit/dashboard/fred_client.py` exists alongside the DB-first pattern established for all macro data. All other credit modules read from `macro_data` hypertable. This file may be stale or represent an inconsistent access pattern.

### 10.3 Worker Count vs Dispatch Complexity

21 workers with independent advisory locks, Redis idempotency, and Cloudflare Cron scheduling. The worker registry (`worker_registry.py`) uses lazy imports to avoid circular dependencies. Growth in worker count increases the surface area for lock contention diagnostics and schedule collision analysis.

### 10.4 OCR Cache Scope

OCR cache (`provider_cache.py`) is process-scoped (in-memory). With 4 uvicorn workers in production, cache is not shared across processes. Duplicate OCR calls possible if the same PDF is processed by different workers. Not a correctness issue (idempotent), but a cost issue for paid Mistral OCR.

### 10.5 Sync/Async Boundary in Vertical Engines

Vertical engines use sync `Session` (passed by caller), but are invoked from async route handlers via `asyncio.to_thread()` or direct session injection. The boundary is well-managed with frozen dataclasses for thread safety, but requires discipline — any new vertical engine code must follow the same pattern.

### 10.6 Single OpenAI Provider

OpenAI Responses API is the primary LLM provider with Azure AI Foundry as fallback for serverless models only (DeepSeek-R1, Mistral). No automatic failover between providers for the main gpt-4.1/5.1 models. Retry logic (exponential backoff, 5 attempts) mitigates transient failures but not sustained outages.

### 10.7 Advisory Lock ID Management

22 hardcoded lock IDs across 24 worker files. IDs are documented in CLAUDE.md but there's no centralized registry in code to prevent ID collisions. Current IDs are well-separated (42, 43, 900_002–900_025) but growth requires manual coordination.

---

## Appendix A: LLM Model Routing

| Model | Use Case | Files |
|-------|----------|-------|
| `gpt-5.1` | IC memo narrative, metadata extraction | `document_intelligence.py`, `deep_review/`, `memo/` |
| `gpt-4.1` | Classification, structured JSON, summaries | `hybrid_classifier.py`, `document_intelligence.py` |
| `gpt-4.1-mini` | LLM classification fallback, entity bootstrap | `hybrid_classifier.py`, `entity_bootstrap.py` |
| `o4-mini` | Critic escalation | `critic/` |
| `text-embedding-3-large` | Embeddings (3072 dims) | `embedding_service.py`, `openai_client.py` |
| `mistral-ocr-latest` | OCR | `mistral_ocr.py` |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Local reranker (~80MB, CPU) | `local_reranker.py` |

## Appendix B: Database Tables by Scope

### Tenant-Scoped (RLS)
Deals, DealContext, Portfolio, Asset, Obligation, DocumentVersion, VectorChunk, ReviewComment, IC Memos, PipelineDeal, DealDocument, Fund, Instrument, NAV, Risk, ScreeningResult, DDReport, PortfolioSnapshot, StrategyDriftAlert, UniverseApproval, AuditEvent, VerticalConfigOverride, BrandingConfig.

### Global (No RLS)
`macro_data`, `treasury_data`, `ofr_hedge_fund_data`, `benchmark_nav`, `bis_statistics`, `imf_weo_forecasts`, `sec_nport_holdings`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_managers`, `sec_manager_funds`, `allocation_blocks`, `vertical_config_defaults`, `macro_regional_snapshots`.

### TimescaleDB Hypertables
- Tenant-scoped: `nav_timeseries`, `fund_risk_metrics`, `portfolio_snapshots`, `audit_events`, `strategy_drift_alerts`
- Global: `macro_data` (1mo), `treasury_data` (1mo), `ofr_hedge_fund_data` (3mo), `benchmark_nav` (1mo), `bis_statistics` (1yr), `imf_weo_forecasts` (1yr), `sec_nport_holdings` (3mo), `sec_13f_holdings` (3mo)

---

*End of Backend System Map v2*
