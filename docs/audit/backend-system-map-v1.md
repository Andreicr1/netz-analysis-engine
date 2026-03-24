# Backend System Map — Netz Analysis Engine v1

**Data:** 2026-03-23
**Branch:** `main`
**Profile:** `netz-backend`
**Scope:** `backend/app/core/`, `backend/ai_engine/`, `backend/app/domains/`, `backend/vertical_engines/`, `backend/quant_engine/`, `backend/data_providers/`

---

## 1. Architecture Overview

### 1.1 Runtime Boundaries

The backend is a single FastAPI process (`backend/app/main.py:220`) serving all verticals (Credit, Wealth, Admin) under a unified `/api/v1` prefix. No microservice decomposition — all domains share the same process, database pool, and Redis connection.

| Boundary | Technology | Purpose |
|----------|-----------|---------|
| **API Server** | FastAPI + Uvicorn (2 workers prod) | HTTP request handling, SSE streaming |
| **Database** | PostgreSQL 16 + TimescaleDB + pgvector (asyncpg) | Persistence, RLS tenant isolation, vector search, hypertable time-series |
| **Cache / Pub-Sub** | Redis 7 (Upstash prod) | Job tracking, SSE bridging, worker idempotency, config invalidation |
| **Storage** | StorageClient (R2 prod, LocalStorage dev) | Data lake: bronze/silver/gold Parquet + JSON |
| **LLM** | OpenAI API (direct, retry backoff) | Classification fallback, extraction, memo generation |
| **OCR** | Mistral API / Local VLM / PyMuPDF | Document text extraction |
| **Embedding** | OpenAI text-embedding-3-large (3072 dim) | Semantic search vectors |

### 1.2 Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  FastAPI Routes (53 routers)                                        │
│  ├─ Admin (8 routers)                                               │
│  ├─ Wealth (22 routers, 144 endpoints)                              │
│  ├─ Credit (23 routers, 75 endpoints)                               │
│  └─ Internal (1 router, not under /api/v1)                          │
├─────────────────────────────────────────────────────────────────────┤
│  app/core/ — Infrastructure                                         │
│  ├─ security/clerk_auth.py     → Clerk JWT v2, Actor, RLS           │
│  ├─ tenancy/middleware.py      → SET LOCAL, get_db_with_rls()       │
│  ├─ config/config_service.py   → DB > YAML cascade, IP protection   │
│  ├─ jobs/{tracker,sse,worker_idempotency}.py → Redis pub/sub + SSE  │
│  ├─ db/{engine,audit,base}.py  → asyncpg pool, audit trail, mixins  │
│  └─ prompts/prompt_service.py  → Jinja2 sandbox, SSTI hardening     │
├─────────────────────────────────────────────────────────────────────┤
│  app/domains/ — Domain Routes & Schemas                             │
│  ├─ credit/ (deals, portfolio, documents, reporting, dashboard,     │
│  │          dataroom, actions, modules/ai)                          │
│  ├─ wealth/ (routes, models, schemas, workers, services, queries)   │
│  └─ admin/  (configs, tenants, prompts, health, audit, inspect)     │
├─────────────────────────────────────────────────────────────────────┤
│  ai_engine/ — Domain-Agnostic Intelligence                          │
│  ├─ pipeline/unified_pipeline.py → 12-stage ingestion orchestrator  │
│  ├─ classification/hybrid_classifier.py → 3-layer (rules→TF-IDF→LLM)│
│  ├─ extraction/ → OCR, chunking, embedding, pgvector, reranker      │
│  ├─ governance/ → token budget, output safety, prompt safety         │
│  ├─ prompts/ → Jinja2 templates (Netz IP)                           │
│  └─ validation/ → vector integrity, evidence quality, eval runner   │
├─────────────────────────────────────────────────────────────────────┤
│  vertical_engines/ — Domain-Specific Analysis                       │
│  ├─ base/base_analyzer.py  → BaseAnalyzer ABC                       │
│  ├─ credit/ (12 packages)  → deep_review, memo, edgar, kyc, etc.   │
│  └─ wealth/ (14 packages + 6 engines) → dd_report, screener, etc.  │
├─────────────────────────────────────────────────────────────────────┤
│  quant_engine/ (19 modules) — Quantitative Services                 │
│  ├─ cvar, regime, optimizer, scoring, drift, rebalance              │
│  ├─ fred, treasury, ofr, regional_macro, bis, imf                   │
│  └─ correlation, attribution, peer_comparison, backtest, momentum   │
├─────────────────────────────────────────────────────────────────────┤
│  data_providers/ — External Data Integration                        │
│  ├─ sec/ (13F, ADV, N-PORT, institutional)                          │
│  ├─ esma/ (FIRDS, register, ticker resolver)                        │
│  ├─ bis/ (credit gap, DSR, property)                                │
│  └─ imf/ (GDP, inflation, fiscal forecasts)                         │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Request Flow

```
Client → CORSMiddleware → RateLimitMiddleware (Redis, 2 tiers)
  → Route Handler
    → Depends(get_actor)         [Clerk JWT decode → Actor]
    → Depends(get_db_with_rls)   [SET LOCAL org_id → AsyncSession]
    → Business logic (vertical_engines / ai_engine / quant_engine)
  → Response (X-RateLimit-Limit, X-RateLimit-Remaining headers)
```

**Rate limit tiers** (`backend/app/core/middleware/rate_limit.py`):
- **Standard:** 100 RPM (default)
- **Compute:** 10 RPM (paths: `/api/v1/ai/`, `/api/v1/dd-reports/`, `/ic-memo`, `/deep-review`, `/document-reviews`)
- **Exempt:** `/health`, `/api/health`, `/api/v1/admin/`

---

## 2. Canonical Backend Flows

### 2.1 Document Ingestion Pipeline

**Entry:** `ai_engine/pipeline/unified_pipeline.py:491` — `async def process()`
**Trigger:** Upload routes or `pipeline_ingest_runner.py`

```
Stage 1:  Pre-filter           → skip_filter.should_skip_document()
Stage 2:  OCR                  → mistral_ocr / local_vlm_ocr / pymupdf (cached)
Stage 3:  OCR Validation Gate  → min 100 chars, max 30% non-printable
Stage 4:  Classification       → hybrid_classifier.classify() [3-layer]
Stage 5:  Classification Gate  → min 0.3 confidence, canonical doc_type
Stage 6:  Governance Detection → governance_detector.detect_governance() [15 regex]
Stage 7:  Chunking             → semantic_chunker.chunk_document() [doc_type-specific sizing]
Stage 8:  Chunking Gate        → max 25% content loss, chunk_count > 0
Stage 9:  Metadata Extraction  → async_extract_metadata() + async_summarize_document() [LLM]
Stage 10: Embedding            → embed_chunks.embed_batch() [text-embedding-3-large, 3072 dim]
Stage 11: Embedding Gate       → dimension validation (3072 expected)
Stage 12: Storage Write        → StorageClient (bronze JSON, silver Parquet, silver metadata)
Stage 13: pgvector Index       → pgvector_search_service.upsert_chunks()
```

**Dual-write ordering:** Storage (source of truth) BEFORE pgvector (derived index). Storage failure → skip index. Index failure → data safe, rebuild via `search_rebuild.py`.

**Tenant isolation:** `{organization_id}/{vertical}/` path prefix enforced by `storage_routing.py`. All pgvector queries include `WHERE organization_id = :org_id`.

**Terminal states:** `success`, `degraded` (partial chunks indexed), `failed`.

### 2.2 Hybrid Classification

**Entry:** `ai_engine/classification/hybrid_classifier.py:709` — `async def classify()`

| Layer | Coverage | Mechanism | Confidence |
|-------|----------|-----------|------------|
| **1 — Rules** | ~60% | Filename patterns + content keyword patterns (first 500 chars) | 1.0 (deterministic) |
| **2 — TF-IDF** | ~30% | sklearn TfidfVectorizer + cosine_similarity on 40+ doc type exemplars | 0.0–1.0 (escalate to L3 if < 0.05 or ratio < 1.3) |
| **3 — LLM** | ~10% | gpt-4.1-mini via Jinja2 templates | LLM-derived |

Zero external ML API calls (Cohere eliminated). Cross-encoder reranker (`local_reranker.py`, `ms-marco-MiniLM-L-6-v2`) for IC memo evidence.

### 2.3 Credit Deep Review (IC Memorandum)

**Entry:** `vertical_engines/credit/deep_review/service.py` — `run_deal_deep_review_v4()`
**13-stage pipeline:**

1. Deal lookup + validation
2. RAG corpus extraction (pgvector search via `retrieval/query_map.py` — deal-anchored queries)
3. Local reranking (cross-encoder)
4. EDGAR data fetch (10-K, 13-F, ADV — DB reads in hot path, EDGAR API in workers only)
5. Market data context (macro_data hypertable, zero FRED API calls)
6. Quant injection (CVaR, scenarios, sensitivity)
7. Concentration analysis
8. Policy compliance checks (deterministic)
9. 13-chapter memo generation (LLM via OpenAI Batch API — 50% cost discount)
10. Tone normalization
11. Critic loop (adversarial review, 3-min timeout circuit breaker)
12. Evidence pack assembly (frozen dataclass)
13. Atomic persist (storage + pgvector + DB)

**Dependencies:** imports from `ai_engine.*`, `quant_engine.*`, `credit/{critic,edgar,quant,market_data,memo,retrieval}`.

### 2.4 Wealth DD Report

**Entry:** `vertical_engines/wealth/dd_report/` — `DDReportEngine.generate()`
**8-chapter sequential generation:**

1. Executive Summary
2. Macro Context
3. Exit Environment
4. Sponsor/Team
5. Legal Terms
6. Investment Terms
7. Capital Structure
8. Recommendation (generated after ch1-7 complete)

**Features:** Evidence pack (frozen dataclass), confidence scoring, quant injection, SEC injection (13F/ADV DB reads), peer injection. Critic review with circuit breaker.

### 2.5 Worker Execution Flow

**Entry:** `backend/app/domains/wealth/routes/workers.py` — 20 `POST /workers/run-*` endpoints
**Dispatch mechanism** (lines 50-139):

```
HTTP POST /workers/run-{name}
  → check_worker_status(name, scope) via Redis
    → 409 if running or recently completed
  → mark_worker_running(name, scope) [Redis, 1h TTL]
  → BackgroundTasks.add_task(
      idempotent_worker_wrapper(        # Track completion
        _run_worker_with_timeout(       # asyncio.wait_for
          worker_coro_func              # Actual work
        )
      )
    )
  → 202 ACCEPTED (immediate)
```

**No external job queue.** Uses FastAPI `BackgroundTasks` (in-memory) + Redis for coordination.

**Advisory locks:** All workers acquire `pg_try_advisory_lock(LOCK_ID)` (non-blocking), unlock in `finally`. 19 unique lock IDs.

**Timeout tiers:** Heavy (600s/10min): ingestion, risk calc, macro. Light (300s/5min): screening, watchlist, portfolio eval.

### 2.6 SSE Job Progress Streaming

**Entry:** `GET /api/v1/jobs/{job_id}/stream` (`backend/app/main.py:275`)

```
Worker publishes → Redis channel job:{job_id}:events
  → subscribe_job() async generator
    → create_job_stream() → EventSourceResponse
      → Client (fetch + ReadableStream, NOT EventSource)
```

**Job ownership:** `register_job_owner(job_id, org_id)` with 1h TTL. `verify_job_owner()` before streaming (deny-by-default). Grace TTL 120s after terminal event for reconnects.

**Terminal events:** `done`, `error`, `ingestion_complete`, `memo_complete`, `report_completed`, `report_failed`.

**Fallback:** `GET /api/v1/jobs/{job_id}/status` for polling (persist_job_state with 24h TTL).

---

## 3. Package Boundary Map

### 3.1 `backend/app/core/` — Infrastructure (CANONICAL)

| Package | Purpose | Public Surface | Key Dependencies |
|---------|---------|----------------|------------------|
| `security/clerk_auth.py` | Clerk JWT v2 decode, Actor model, fund membership | `get_actor()`, `require_role()`, `require_fund_access()`, `Actor` | PyJWKClient, fund_memberships table |
| `tenancy/middleware.py` | RLS context injection | `get_db_with_rls()`, `set_rls_context()` | async_session_factory |
| `tenancy/admin_middleware.py` | Cross-tenant admin access | `get_db_admin()`, `get_db_for_tenant()` | async_session_factory |
| `db/engine.py` | Async engine pool (size=20, overflow=10) | `engine`, `async_session_factory`, `get_db()` | asyncpg, SQLAlchemy |
| `db/session.py` | Sync engine for workers | `sync_engine`, `sync_session_factory`, `get_sync_db_with_rls()` | psycopg |
| `db/audit.py` | Immutable audit trail | `write_audit_event()`, `get_audit_log()` | AuditEvent model (TimescaleDB hypertable, 1-week chunks) |
| `db/base.py` | ORM mixins | `IdMixin`, `OrganizationScopedMixin`, `FundScopedMixin`, `AuditMetaMixin` | SQLAlchemy declarative |
| `config/config_service.py` | Config cascade (DB > YAML) | `ConfigService.get()`, `.list_configs()`, `.invalidate()`, `.deep_merge()` | TTLCache (60s), VerticalConfigOverride, VerticalConfigDefault |
| `config/settings.py` | Environment variables | `Settings` class, `validate_production_secrets()` | pydantic-settings |
| `jobs/tracker.py` | Redis pub/sub job tracking | `register_job_owner()`, `publish_event()`, `publish_terminal_event()`, `subscribe_job()` | Redis (max 100 connections) |
| `jobs/sse.py` | SSE streaming | `create_job_stream()` | sse-starlette, tracker |
| `jobs/worker_idempotency.py` | Worker duplicate prevention | `check_worker_status()`, `mark_worker_running()`, `idempotent_worker_wrapper()` | Redis |
| `prompts/prompt_service.py` | Prompt management + SSTI hardening | `PromptService`, `HardenedPromptEnvironment` | Jinja2 SandboxedEnvironment |
| `middleware/rate_limit.py` | Redis-backed rate limiting | `RateLimitMiddleware` | Redis |

### 3.2 `backend/ai_engine/` — Domain-Agnostic Intelligence (CANONICAL)

| Package | Purpose | Public Surface | Status |
|---------|---------|----------------|--------|
| `pipeline/unified_pipeline.py` | 12-stage ingestion orchestrator | `process()` | Canonical |
| `pipeline/validation.py` | Inter-stage validation gates | `validate_ocr_output()`, `validate_classification()`, `validate_chunks()`, `validate_embeddings()` | Canonical |
| `pipeline/storage_routing.py` | Path builders (bronze/silver/gold) | `bronze_document_path()`, `silver_chunks_path()`, `gold_memo_path()`, `global_reference_path()`, +12 more | Canonical |
| `pipeline/search_rebuild.py` | Rebuild pgvector from silver Parquet | `rebuild_search_index()` | Canonical |
| `pipeline/models.py` | Pipeline data models | `IngestRequest`, `PipelineStageResult` | Canonical |
| `classification/hybrid_classifier.py` | 3-layer doc type classifier | `classify()`, `classify_vehicle_rules()` | Canonical |
| `extraction/semantic_chunker.py` | Doc-type-aware chunking | `chunk_document()` | Canonical |
| `extraction/embed_chunks.py` | Batch embedding | `embed_batch()`, `build_embed_text()` | Canonical |
| `extraction/pgvector_search_service.py` | Vector upsert + search | `upsert_chunks()`, `pgvector_search()`, `build_search_document()` | Canonical |
| `extraction/local_reranker.py` | Cross-encoder reranking | `rerank()` (ms-marco-MiniLM-L-6-v2) | Canonical |
| `extraction/governance_detector.py` | Governance flag detection | `detect_governance()` (15 regex patterns) | Canonical |
| `extraction/document_intelligence.py` | LLM-powered extraction | `async_extract_metadata()`, `async_summarize_document()` | Canonical |
| `extraction/mistral_ocr.py` | Mistral OCR API | `async_extract_pdf_with_mistral()` | Canonical |
| `extraction/local_vlm_ocr.py` | Local VLM OCR (zero API cost) | `async_extract_pdf_with_local_vlm()` | Canonical |
| `ingestion/pipeline_ingest_runner.py` | Full pipeline ingest orchestrator | `run_full_pipeline_ingest()` | Canonical |
| `ingestion/document_scanner.py` | Document classification by folder | `classify_documents()` | Canonical |
| `prompts/registry.py` | Jinja2 template registry | `PromptRegistry.render()`, `.render_pair()` | Canonical |
| `governance/` | Token budget, output safety, prompt safety | `TokenBudgetTracker`, `sanitize_llm_text()` | Canonical |
| `validation/` | Post-pipeline validation | `vector_integrity_guard`, `evidence_quality`, `eval_runner` | Canonical |
| `cache/provider_cache.py` | OCR result caching | `ocr_cache.get()`, `.put()` | Canonical |
| `llm/call_openai.py` | Central LLM provider | `call_openai()`, `create_completion()` | Canonical |
| `profile_loader.py` | Config → vertical engine resolver | `ProfileLoader.load()`, `.get_engine_module()` | Canonical |
| `vertical_registry.py` | Vertical module registry | `get_vertical_entry()`, `import_vertical_module()` | Canonical |
| `pdf/` | PDF renderers | `memo_md_to_pdf`, `generate_dd_report_pdf`, `pipeline_memo_pdf` | Canonical |

### 3.3 `backend/vertical_engines/credit/` — 12 Packages (CANONICAL)

| Package | Entry Point | Purpose | Status |
|---------|-------------|---------|--------|
| `critic/` | `critique_intelligence()` | Adversarial IC critique (never raises, returns CriticVerdict) | Canonical |
| `deal_conversion/` | `convert_pipeline_to_portfolio()` | Deal → portfolio asset (transactional, hard gates) | Canonical |
| `deep_review/` | `run_deal_deep_review_v4()` | 13-stage IC memorandum pipeline | Canonical |
| `domain_ai/` | (minimal) | Placeholder for domain AI orchestration | Transitional (sparse) |
| `edgar/` | `fetch_edgar_data()`, `fetch_edgar_multi_entity()` | SEC EDGAR data (10-K, 13-F, ADV) — sync, never raises | Canonical |
| `kyc/` | `run_kyc_screening()` | KYC pipeline screening (entities + sanctions) | Canonical |
| `market_data/` | `fetch_market_data_context()` | macro_data hypertable reads (zero FRED API) | Canonical |
| `memo/` | `generate_chapter_requests()`, `submit_chapter_batch()` | OpenAI Batch API memo book (50% cost discount) | Canonical |
| `pipeline/` | `run_pipeline_ingest()` | Credit pipeline orchestration | Canonical |
| `portfolio/` | (multiple service functions) | Post-conversion covenant tracking, drift, alerts | Canonical |
| `quant/` | `compute_credit_scenarios()` | Credit-specific scenarios, sensitivity, backtest | Canonical |
| `retrieval/` | `build_chapter_query_map()` | Chapter-specialized RAG queries (deal-anchored) | Canonical |
| `sponsor/` | (minimal) | Sponsor/key person extraction | Canonical |

### 3.4 `backend/vertical_engines/wealth/` — 14 Packages + 6 Engines (CANONICAL)

| Package | Entry Point | Purpose | Status |
|---------|-------------|---------|--------|
| `dd_report/` | `DDReportEngine.generate()` | 8-chapter fund DD report | Canonical |
| `fact_sheet/` | (model-driven renderers) | PDF: Executive/Institutional, PT/EN i18n | Canonical |
| `screener/` | `ScreenerService.screen_instrument()` | 3-layer deterministic screening (no LLM) | Canonical |
| `correlation/` | `compute_correlation()` | Rolling correlation + Marchenko-Pastur denoising | Canonical |
| `attribution/` | `compute_brinson_attribution()` | Brinson-Fachler policy benchmark attribution | Canonical |
| `fee_drag/` | `compute_fee_drag()` | Fee drag ratio + efficiency analysis | Canonical |
| `monitoring/` | `scan_drift()` | Bridge to quant_engine drift + universe awareness | Canonical |
| `watchlist/` | `WatchlistService.check_transitions()` | PASS→FAIL transition detection (pure logic) | Canonical |
| `mandate_fit/` | `evaluate_mandate_constraints()` | Client mandate constraint evaluator | Canonical |
| `peer_group/` | (peer matching) | Fund comparison within block | Canonical |
| `rebalancing/` | (weight proposer) | Impact analyzer, cascade state machine | Canonical |
| `asset_universe/` | (universe management) | Fund universe + approval workflow | Canonical |
| `model_portfolio/` | (portfolio builder) | Stress scenarios + track record | Canonical |
| `critic/` | (adversarial review) | Wealth critic (3-min timeout, circuit breaker) | Canonical |

**Standalone engines:**

| Engine | Purpose | Status |
|--------|---------|--------|
| `fund_analyzer.py` | BaseAnalyzer impl — orchestrator for liquid_funds | Canonical |
| `macro_committee_engine.py` | Weekly regional macro reports + emergency workflow | Canonical |
| `quant_analyzer.py` | Portfolio-level CVaR, scoring, peer comparison | Canonical |
| `flash_report.py` | Event-driven market flash (48h cooldown) | Canonical |
| `investment_outlook.py` | Quarterly macro narrative | Canonical |
| `manager_spotlight.py` | Deep-dive single fund manager analysis | Canonical |

### 3.5 `backend/quant_engine/` — 19 Modules (CANONICAL)

| Module | Purpose | Config Pattern |
|--------|---------|---------------|
| `cvar_service.py` | CVaR computation + breach detection | `ConfigService.get("liquid_funds", "portfolio_profiles")` |
| `regime_service.py` | Market regime classification (CRISIS > INFLATION > RISK_OFF > RISK_ON) | `ConfigService.get("liquid_funds", "calibration")` |
| `optimizer_service.py` | Portfolio optimization (cvxpy + CLARABEL, NSGA-II for Pareto) | Allocation blocks config |
| `scoring_service.py` | Fund manager scoring (0-100, 6 components) | `ConfigService.get("liquid_funds", "scoring")` |
| `drift_service.py` | DTW portfolio drift monitoring | `ConfigService.get("liquid_funds", "calibration")` |
| `rebalance_service.py` | Cascade state machine (ok → warning → breach → hard_stop) | `ConfigService.get("liquid_funds", "portfolio_profiles")` |
| `fred_service.py` | FRED API client (rate-limited, used by workers only) | API key from settings |
| `regional_macro_service.py` | Regional macro scoring (6 dimensions, percentile-rank) | `ConfigService.get("liquid_funds", "calibration")` |
| `stress_severity_service.py` | Market stress scenario quantification | Config param |
| `correlation_regime_service.py` | Marchenko-Pastur denoising + absorption ratio | Config param |
| `attribution_service.py` | Brinson-Fachler attribution | Config param |
| `peer_comparison_service.py` | Peer ranking within group | Config param |
| `portfolio_metrics_service.py` | Fund→portfolio metric aggregation | Config param |
| `backtest_service.py` | Strategy backtesting | Config param |
| `talib_momentum_service.py` | RSI-14, Bollinger, OBV (pre-computed by risk_calc worker) | Config param |
| `fiscal_data_service.py` | US Treasury, debt, auctions, FX | Config param |
| `ofr_hedge_fund_service.py` | OFR hedge fund data | Config param |
| `macro_snapshot_builder.py` | Point-in-time macro snapshot assembly | Config param |
| `data_commons_service.py` | Shared data access utilities | Config param |

**Design pattern:** All sync pure functions. Config resolved once at async entry point via `ConfigService.get()`, passed down as dict parameter. No YAML reads, no `@lru_cache`, no module-level asyncio primitives.

### 3.6 `backend/data_providers/` — External Data Integration (CANONICAL)

| Provider | Services | Hot-Path Pattern | Worker Pattern |
|----------|----------|------------------|----------------|
| **SEC** | `thirteenf_service.py`, `adv_service.py`, `nport_service.py`, `institutional_service.py` | DB-only reads: `read_holdings()`, `fetch_manager()`, `read_investors_in_manager()` | EDGAR API: `fetch_holdings()`, `discover_institutional_filers()` |
| **ESMA** | `firds_service.py`, `register_service.py`, `ticker_resolver.py` | DB reads | ESMA API calls |
| **BIS** | `service.py` | DB reads from `bis_statistics` hypertable | BIS SDMX API |
| **IMF** | `service.py` | DB reads from `imf_weo_forecasts` hypertable | IMF DataMapper API |

### 3.7 `backend/app/domains/` — Domain Routes & Schemas (CANONICAL)

| Domain | Route Files | Models | Endpoints | Vertical Engine Integration |
|--------|------------|--------|-----------|----------------------------|
| **Credit** | 28 files | 22 models | ~75 | `modules/ai/` bridges to `vertical_engines/credit/` |
| **Wealth** | 24 files | 26 models | ~144 | Routes import `vertical_engines/wealth/` services directly |
| **Admin** | 8 files | ~5 models | ~34 | Cross-tenant via `get_db_admin()` / `get_db_for_tenant()` |

### 3.8 `backend/app/services/storage_client.py` — Storage Abstraction (CANONICAL)

| Backend | Class | Activation | I/O Pattern |
|---------|-------|-----------|-------------|
| **R2** (prod) | `R2StorageClient` | `FEATURE_R2_ENABLED=true` | boto3 S3 via `asyncio.to_thread()` |
| **LocalStorage** (dev) | `LocalStorageClient` | Default | sync `pathlib.Path` I/O |

**Factory:** `create_storage_client()` — R2 > LocalStorage. Singleton via `get_storage_client()`.

**Path convention:** `{tier}/{organization_id}/{vertical}/...` (tenant-scoped), `{tier}/_global/...` (global data).

---

## 4. Legacy / Transitional Map

### 4.1 Confirmed Legacy (kept for rollback, not actively used)

| Module/Pattern | Evidence | Replacement |
|----------------|----------|-------------|
| `ADLSStorageClient` | `storage_client.py` — class exists but `FEATURE_ADLS_ENABLED` deprecated 2026-03-18 | R2StorageClient |
| Azure env vars | `settings.py` — `azure_openai_endpoint`, `azure_search_endpoint`, etc. commented/deprecated | OpenAI direct, pgvector |
| `fred_client.py` in credit dashboard | `domains/credit/dashboard/fred_client.py` — eliminated, market_data reads from hypertable | `market_data` package (macro_data hypertable) |
| Azure Search files | Replaced by pgvector (commit 497df51) | `pgvector_search_service.py` |
| Cohere Rerank | Eliminated entirely | `local_reranker.py` (cross-encoder) |
| `_legacy_routes/` in wealth frontend | `frontends/wealth/src/_legacy_routes/` | New `(app)/` route group |

### 4.2 Transitional (active but evolving)

| Module | Status | Notes |
|--------|--------|-------|
| `credit/domain_ai/` | Sparse — placeholder | Most logic delegated to sibling engines |
| `credit/dataroom/` | Stub (0 endpoints) | Folder governance not yet implemented |
| `sync_session_factory` in `db/session.py` | Legacy sync engine for workers | Workers mostly async now, sync kept for vertical_engines |
| `BackgroundTasks` dispatch | In-memory FIFO | May evolve to Redis Streams for guaranteed delivery (Milestone 3+) |
| `ConfigService` L2 Redis cache | Not yet implemented | Planned Sprint 5-6, currently TTLCache (60s) + DB |

### 4.3 Modules with Unclear Ownership

None identified. All packages have clear ownership within their vertical.

---

## 5. State, Config, and Runtime Policy Map

### 5.1 Configuration Cascade

```
ConfigService.get(vertical, config_type, org_id)
  ↓
  1. In-process TTLCache (60s, maxsize=2048)
  2. DB: VerticalConfigOverride (RLS-scoped if org_id)
  3. DB: VerticalConfigDefault (no RLS)
  4. YAML fallback (_YAML_FALLBACK_MAP) — emergency only, logged as ERROR
  5. ConfigMissError (required) or ConfigResult(MISSING_OPTIONAL)
```

**Source of truth:** PostgreSQL (defaults + org overrides). YAML is seed data only.

**Cache invalidation:** `PgNotifier` subscribes to `config_changed` LISTEN channel (startup in `main.py:200-209`). Calls `ConfigService.invalidate()` to clear TTLCache.

**IP Protection:** `CLIENT_VISIBLE_TYPES = {"calibration", "scoring", "blocks", "portfolio_profiles"}`. Prompts, chapters, governance_policy never exposed to clients.

### 5.2 YAML Fallback Map (Emergency Only)

| Vertical | Config Type | YAML Path |
|----------|-------------|-----------|
| `liquid_funds` | `calibration` | `calibration/config/limits.yaml` |
| `liquid_funds` | `portfolio_profiles` | `calibration/config/profiles.yaml` |
| `liquid_funds` | `scoring` | `calibration/config/scoring.yaml` |
| `liquid_funds` | `blocks` | `calibration/config/blocks.yaml` |
| `liquid_funds` | `chapters` | `profiles/liquid_funds/profile.yaml` |
| `liquid_funds` | `macro_intelligence` | `calibration/seeds/liquid_funds/macro_intelligence.yaml` |
| `private_credit` | `chapters` | `profiles/private_credit/profile.yaml` |
| `private_credit` | `calibration` | `calibration/seeds/private_credit/calibration.yaml` |
| `private_credit` | `governance_policy` | `calibration/seeds/private_credit/governance_policy.yaml` |

### 5.3 Tenant-Specific Behavior Entry Points

| Layer | Mechanism | Evidence |
|-------|-----------|---------|
| **Request auth** | Clerk JWT `o.id` claim → `Actor.organization_id` | `clerk_auth.py:163-167` |
| **DB session** | `SET LOCAL app.current_organization_id` (transaction-scoped) | `middleware.py:43` |
| **RLS policies** | `(SELECT current_setting('app.current_organization_id')::uuid)` subselect | All RLS-scoped tables |
| **Config overrides** | `VerticalConfigOverride WHERE organization_id = :org_id` | `config_service.py:129-138` |
| **Storage paths** | `{tier}/{organization_id}/{vertical}/...` | `storage_routing.py` |
| **pgvector queries** | `WHERE organization_id = :org_id` (parameterized) | `pgvector_search_service.py` |
| **DuckDB queries** | `WHERE organization_id = ?` | All Parquet analytics |
| **Worker dispatch** | org-scoped workers use `set_rls_context(db, org_id)` | `workers.py`, individual worker files |
| **Job ownership** | `job:{job_id}:org = organization_id` in Redis | `tracker.py:75-86` |
| **Audit events** | `organization_id` from RLS context | `audit.py:60-66` |

### 5.4 Global Tables (No RLS, No organization_id)

`macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav`, `macro_regional_snapshots`, `treasury_data`, `ofr_hedge_fund_data`, `bis_statistics`, `imf_weo_forecasts`, `sec_nport_holdings`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_managers`, `sec_manager_funds`.

---

## 6. Auditability / Operator Visibility Map

### 6.1 Audit Trail

**Mechanism:** `write_audit_event()` in `backend/app/core/db/audit.py`
**Model:** `AuditEvent` — TimescaleDB hypertable (1-week chunks, compression 1-month, segmentby=organization_id)
**Fields:** `fund_id`, `actor_id`, `actor_roles`, `request_id`, `action` (CREATE/UPDATE/DELETE), `entity_type`, `entity_id`, `before_state` (JSONB), `after_state` (JSONB)
**Coverage:** 17+ modules, entity-level change tracking.

### 6.2 Job Tracking

| Key Pattern | TTL | Purpose |
|-------------|-----|---------|
| `worker:{name}:{scope}:status` | RUNNING=1h, COMPLETED=5m, FAILED=30m | Worker idempotency + status |
| `job:{job_id}:org` | 1h (120s grace after terminal) | SSE tenant authorization |
| `job:{job_id}:events` | Channel | Pub/sub progress events |
| `job:{job_id}:state` | 24h | Terminal state persistence |

### 6.3 Structured Failure Handling

| Pattern | Location | Behavior |
|---------|----------|----------|
| **Pipeline degraded state** | `unified_pipeline.py` | Partial storage success → continue to indexing with warning |
| **Worker timeout** | `workers.py` | `asyncio.wait_for(timeout)` → mark failed, log traceback |
| **Advisory lock miss** | All workers | `pg_try_advisory_lock` returns false → skip (log "another instance running") |
| **Critic circuit breaker** | `critic/service.py` | 3-min timeout → return NOT_ASSESSED (never raises) |
| **EDGAR fetch failure** | `edgar/service.py` | Never raises → errors captured in warnings list |
| **ConfigService YAML fallback** | `config_service.py` | Logged as ERROR (indicates missing seed data) |

### 6.4 SSE / Streaming Progress

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GET /api/v1/jobs/{job_id}/stream` | Job progress (pipeline, memo, reports) | Clerk JWT + job ownership |
| `GET /api/v1/jobs/{job_id}/status` | Polling fallback | Clerk JWT + job ownership |
| `GET /admin/health/stream-worker-logs` | Worker log streaming | Super-admin only |
| `POST /api/v1/test/sse/{job_id}/emit` | Dev-only test emitter | Dev mode |

### 6.5 Partial Failure Surfacing

- **Pipeline:** `PipelineStageResult` includes `terminal_state` (success/degraded/failed), `errors` list, per-stage metrics.
- **Workers:** `mark_worker_failed()` stores error + traceback in Redis (30m TTL). Admin health endpoint can inspect.
- **DD Reports / Deep Review:** Return structured results with confidence scores, warnings, critic verdict. Never silently swallow errors.
- **Job state:** `persist_job_state()` stores `{terminal_state, chunks, errors}` for post-mortem.

---

## 7. Structural Risks

### 7.1 In-Memory Job Queue

Workers use FastAPI `BackgroundTasks` (in-memory FIFO). Process crash loses all in-flight jobs. Redis status keys have 1h TTL safety net for crash recovery, but no guaranteed delivery. **Impact:** Acceptable for current scale (<50 tenants). Scale trigger: Redis Streams for guaranteed delivery (Milestone 3+).

### 7.2 Single Process, All Verticals

All domains (Credit, Wealth, Admin) share one FastAPI process. A CPU-heavy vertical engine computation in one vertical can starve others. **Impact:** Mitigated by `asyncio.to_thread()` for sync vertical engines and worker timeouts. True isolation requires process-per-vertical (Milestone 3+).

### 7.3 ConfigService L2 Cache Missing

Only in-process TTLCache (60s). No Redis L2. Process restart cold-starts all config from DB. Multi-worker deployments may see stale config for up to 60s. **Impact:** Acceptable at 2 workers. PgNotifier invalidation partially mitigates.

### 7.4 Sync Session Still Present

`db/session.py` maintains sync engine (`sync_session_factory`) for legacy worker patterns. Most vertical engines are sync (CPU-bound), dispatched via `asyncio.to_thread()`. Not a bug, but creates two session patterns to maintain.

### 7.5 Advisory Lock ID Namespace

19 hardcoded lock IDs across worker files. No central registry — collision risk if new workers added without checking. Lock IDs range from 42-43 (legacy) to 900_004-900_023 (structured).

### 7.6 Rate Limit Tier Classification

Compute tier paths are hardcoded strings in `rate_limit.py`. New LLM-heavy endpoints must be manually added to the compute tier list. No automatic detection.

### 7.7 ESMA/SEC Ingestion Worker Growth

23 wealth workers already. Each new external data source adds another worker + lock ID + dispatch endpoint. Worker surface area growing linearly.

---

## 8. Worker Network (Complete)

| Worker | Lock ID | Scope | Hypertable/Target | Source | Frequency |
|--------|---------|-------|-------------------|--------|-----------|
| `macro_ingestion` | 43 | global | `macro_data` | FRED API | Daily |
| `treasury_ingestion` | 900_011 | global | `treasury_data` | US Treasury API | Daily |
| `ofr_ingestion` | 900_012 | global | `ofr_hedge_fund_data` | OFR API | Weekly |
| `benchmark_ingest` | 900_004 | global | `benchmark_nav` | Yahoo Finance | Daily |
| `instrument_ingestion` | 900_010 | org | `nav_timeseries` | Yahoo Finance | Daily |
| `risk_calc` | 900_007 | org | `fund_risk_metrics` | Computed | Daily |
| `portfolio_eval` | 900_008 | org | `portfolio_snapshots` | Computed | Daily |
| `nport_ingestion` | 900_018 | global | `sec_nport_holdings` | SEC EDGAR N-PORT | Weekly |
| `sec_13f_ingestion` | 900_021 | global | `sec_13f_holdings`, `sec_13f_diffs` | SEC EDGAR 13F-HR | Weekly |
| `sec_adv_ingestion` | 900_022 | global | `sec_managers`, `sec_manager_funds` | SEC FOIA bulk CSV | Monthly |
| `bis_ingestion` | 900_014 | global | `bis_statistics` | BIS SDMX API | Quarterly |
| `imf_ingestion` | 900_015 | global | `imf_weo_forecasts` | IMF DataMapper API | Quarterly |
| `drift_check` | 42 | org | `strategy_drift_alerts` | Computed (DTW) | Daily |
| `screening_batch` | 900_002 | org | `screening_results` | Computed | On-demand |
| `watchlist_batch` | 900_003 | org | Alerts | Computed | On-demand |
| `brochure_download` | 900_019 | global | Brochure files | SEC EDGAR | On-demand |
| `brochure_extract` | 900_020 | global | Brochure text | OCR pipeline | On-demand |
| `esma_ingestion` | 900_023 | global | ESMA tables | ESMA API | Scheduled |
| `sec_refresh` | 900_016 | global | SEC tables | SEC EDGAR | Manual |
| `fact_sheet_gen` | varies | org | Gold PDF files | Computed | On-demand |

---

## 9. Key Constants & Thresholds

### Pipeline

| Constant | Value | Location |
|----------|-------|----------|
| `MIN_OCR_CHARS` | 100 | `validation.py` |
| `MAX_NON_PRINTABLE_RATIO` | 0.30 | `validation.py` |
| `MIN_CLASSIFICATION_CONFIDENCE` | 0.3 | `validation.py` |
| `MAX_CONTENT_LOSS_RATIO` | 0.25 | `validation.py` |
| `EXPECTED_EMBEDDING_DIM` | 3072 | `vector_integrity_guard.py` |
| `EMBED_MAX_CHARS` | 30,000 | `embed_chunks.py` |
| `BATCH_SIZE` (embedding) | 500 | `embed_chunks.py` |
| `_MIN_SIMILARITY` (TF-IDF) | 0.05 | `hybrid_classifier.py` |
| `_MIN_RATIO` (TF-IDF) | 1.3 | `hybrid_classifier.py` |
| Reranker passage truncation | 2,000 chars | `local_reranker.py` |

### Workers

| Constant | Value | Location |
|----------|-------|----------|
| `_HEAVY_WORKER_TIMEOUT` | 600s (10 min) | `workers.py` |
| `_LIGHT_WORKER_TIMEOUT` | 300s (5 min) | `workers.py` |
| `RUNNING_TTL` | 3600s (1h) | `worker_idempotency.py` |
| `COMPLETED_TTL` | 300s (5m) | `worker_idempotency.py` |
| `FAILED_TTL` | 1800s (30m) | `worker_idempotency.py` |
| `DEFAULT_OWNERSHIP_TTL` | 3600s (1h) | `tracker.py` |
| `TERMINAL_CLEANUP_TTL` | 120s | `tracker.py` |

### Infrastructure

| Constant | Value | Location |
|----------|-------|----------|
| DB pool size | 20 (+10 overflow) | `engine.py` |
| Redis max connections | 100 | `tracker.py` |
| ConfigService TTLCache | 60s, maxsize=2048 | `config_service.py` |
| Rate limit standard | 100 RPM | `rate_limit.py` |
| Rate limit compute | 10 RPM | `rate_limit.py` |
| SSE heartbeat | 15s | `sse.py` |
| Prompt template LRU cache | maxsize=128 | `registry.py` |

---

*Generated 2026-03-23 from repository evidence. This document serves as the baseline for subsequent validation and contradiction audits.*
