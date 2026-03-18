# Backend System Map v3

**Generated:** 2026-03-18
**Profile:** netz-backend
**Scope:** `backend/` — API, AI engine, vertical engines, quant engine, workers
**Evidence source:** Live repository code (primary), docs/plans (secondary context only)

---

## 1. Architecture Overview

### 1.1 Runtime Boundaries

| Boundary | Entry Point | Technology |
|----------|-------------|------------|
| **ASGI API** | `backend/app/main.py` → `app.main:app` | FastAPI + Uvicorn (port 8000) |
| **Background Workers** | `POST /api/v1/workers/run-*` | FastAPI `BackgroundTasks` (in-process, no Celery) |
| **SSE Streaming** | `GET /api/v1/jobs/{job_id}/stream` | `sse-starlette` + Redis pub/sub |
| **Config Cache** | Lifespan `PgNotifier` | PostgreSQL LISTEN/NOTIFY → in-process TTLCache |

No external task queue (Celery, RQ). All background work dispatched via FastAPI `BackgroundTasks` within the same ASGI process.

### 1.2 Subsystem Responsibilities

| Subsystem | Location | Responsibility |
|-----------|----------|----------------|
| **Core** | `app/core/` | Auth (Clerk JWT v2), tenancy (RLS), DB (asyncpg), config (ConfigService), jobs (SSE/Redis) |
| **Domains** | `app/domains/` | REST API surface — admin, credit, wealth route handlers + ORM models + schemas |
| **AI Engine** | `ai_engine/` | Domain-agnostic document processing — OCR, classification, chunking, embedding, storage, indexing |
| **Vertical Engines** | `vertical_engines/` | Domain-specific analytical logic — credit (12 packages), wealth (20+ packages) |
| **Quant Engine** | `quant_engine/` | Shared quantitative services — CVaR, regime, optimizer, drift, scoring, FRED, backtest |
| **Services** | `app/services/` | Cross-cutting abstractions — StorageClient (ADLS/local), blob storage, search index |

### 1.3 Layered Architecture

```
┌─────────────────────────────────────────────────┐
│  FastAPI Routes (app/domains/*)                  │  ← HTTP boundary, auth, RLS
├─────────────────────────────────────────────────┤
│  Domain Services (app/domains/*/services/)       │  ← Business logic orchestration
├─────────────────────────────────────────────────┤
│  AI Engine (ai_engine/*)                         │  ← Domain-agnostic doc processing
│  Vertical Engines (vertical_engines/*)           │  ← Domain-specific analysis
│  Quant Engine (quant_engine/*)                   │  ← Shared computation
├─────────────────────────────────────────────────┤
│  Core (app/core/*)                               │  ← Auth, DB, config, jobs
│  Services (app/services/*)                       │  ← Storage, search, providers
├─────────────────────────────────────────────────┤
│  PostgreSQL 16 + TimescaleDB │ Redis 7 │ ADLS   │  ← Persistence
└─────────────────────────────────────────────────┘
```

---

## 2. Canonical Backend Flows

### 2.1 Document Ingestion (Unified Pipeline)

**Entry point:** `ai_engine/pipeline/unified_pipeline.py::process()`
**Orchestrator:** Single function, 10 sequential stages with 5 validation gates
**Request envelope:** `IngestRequest` frozen dataclass (source, org_id, vertical, document_id, blob_uri, filename, fund_id, deal_id, version_id, fund_context)

**Stage sequence:**

| Stage | Module | Purpose | Gate |
|-------|--------|---------|------|
| 0 | `ai_engine/pipeline/skip_filter.py` | Pre-filter compliance forms | — |
| 1 | `ai_engine/extraction/mistral_ocr.py` | Mistral OCR (table=HTML) | MIN_OCR_CHARS=100, MAX_NONPRINTABLE=30% |
| 2 | `ai_engine/classification/hybrid_classifier.py` | 3-layer classification | doc_type ∈ CANONICAL, confidence ≥ 0.3 (warn) |
| 3 | `ai_engine/extraction/governance_detector.py` | 15-pattern regex governance scan | — |
| 4 | `ai_engine/extraction/semantic_chunker.py` | Semantic markdown chunking | chunk_count > 0, content_loss < 25% |
| 5 | `ai_engine/extraction/document_intelligence.py` | Metadata + summary (parallel) | — (degraded quality OK) |
| 6 | `ai_engine/extraction/embed_chunks.py` | text-embedding-3-large (3072-dim) | dim match, no NaN |
| 7 | `ai_engine/pipeline/storage_routing.py` | ADLS dual-write (bronze + silver) | — (partial failure warns) |
| 8 | `ai_engine/extraction/search_upsert_service.py` | Azure Search upsert | — |
| 9 | unified_pipeline.py | Terminal state + audit | — |

**Persistence points:**
- Bronze: `bronze/{org_id}/{vertical}/documents/{doc_id}.json` (raw OCR)
- Silver chunks: `silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet` (zstd, includes embedding_model + embedding_dim)
- Silver metadata: `silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json`
- Azure Search: `global-vector-chunks-v2` index (all chunks with organization_id filter field)
- Redis: Job ownership + terminal event (ASYNC-01 grace TTL cleanup)
- PostgreSQL: `audit_events` table (per-stage audit trail)

**SSE events emitted:** ocr_complete → classification_complete → chunking_complete → extraction_complete → storage_complete → indexing_complete → ingestion_complete (terminal)

**Tenant boundary:** org_id from JWT only (never user input). All ADLS paths scoped by `{org_id}/{vertical}/`. All search documents include `organization_id` field.

### 2.2 Hybrid Classification

**Entry point:** `ai_engine/classification/hybrid_classifier.py::classify()`
**Three layers (cost escalation):**

| Layer | Method | Coverage | Cost |
|-------|--------|----------|------|
| 1 | 28 filename patterns + 13 content regex | ~60% | Free |
| 2 | TF-IDF cosine similarity (38 synthetic exemplars) | ~30% | Free (sklearn) |
| 3 | LLM fallback (gpt-4-1-mini) | ~10% | API call |

Output: `HybridClassificationResult(doc_type, vehicle_type, confidence, layer)` — frozen dataclass.
31 canonical doc types, 6 vehicle types. No external ML APIs (Cohere removed).

### 2.3 Batch Pipeline Orchestration

**Entry point:** `ai_engine/ingestion/pipeline_ingest_runner.py::run_full_pipeline_ingest()`
**Five stages:**

1. **Document Registry Scan** (`document_scanner.py`) — discovers PDFs in blob containers
2. **Pipeline Deal Discovery** (`vertical_engines/credit/pipeline/`) — parses folder structure
3. **Entity Bootstrap** (`extraction/entity_bootstrap.py`) — extracts deal context from up to 5 PDFs per deal (Semaphore(5))
4. **Registry→DealDocument Bridge** (`ingestion/registry_bridge.py`) — maps blobs to deals
5. **Deep Review** (`vertical_engines/credit/deep_review/`) — 13-stage IC memo generation

Per-stage persistence via `PipelineIngestJob` row (counters, timing, errors).

### 2.4 Search Rebuild

**Entry point:** `ai_engine/pipeline/search_rebuild.py::rebuild_search_index()`
**Flow:** Advisory lock → list silver Parquet → validate embedding dimensions → build search docs → upsert to Azure Search → release lock.
**Key invariant:** No OCR/LLM calls. Purely data movement from ADLS silver layer. Embedding dimension mismatch rejects entire document (prevents silent corruption on model upgrade).

### 2.5 Wealth Worker Flows

**Entry point:** `POST /api/v1/workers/run-*` (8 worker endpoints)
**Orchestrator:** `app/domains/wealth/routes/workers.py` → FastAPI BackgroundTasks

| Worker | Source | Persistence |
|--------|--------|-------------|
| `ingestion` | Yahoo Finance NAV | `nav_timeseries` |
| `risk_calc` | Rolling CVaR/VaR/vol/Sharpe | `fund_risk_metrics` |
| `portfolio_eval` | Daily CVaR eval + breach + regime | `portfolio_snapshots` |
| `macro_ingestion` | 45 FRED series + regional scores | `macro_data` + `macro_regional_snapshots` |
| `fact_sheet_gen` | Monthly PDF generation | Gold layer ADLS |
| `watchlist_batch` | Re-screen watchlisted instruments | Alerts |
| `screening_batch` | 3-layer deterministic screening | Screening results |
| `benchmark_ingest` | Benchmark index data | `benchmark_nav` (global) |

All require `Role.INVESTMENT_TEAM` or `Role.ADMIN`. Workers use async sessions + thread pools for I/O isolation.

### 2.6 IC Memo Generation (Deep Review)

**Entry point:** `vertical_engines/credit/deep_review/service.py`
**Orchestrator:** 13-stage pipeline culminating in 14-chapter memo book

Key stages: Document collection → Evidence curation (retrieval governance) → Structured analysis → Quant profile → EDGAR multi-entity → KYC screening → Sponsor analysis → Critic review → 14-chapter memo generation (parallel via asyncio.TaskGroup) → Policy compliance → Decision synthesis

**Evidence pack:** Frozen `EvidencePack` dataclass — immutable snapshot shared across chapters for thread safety.
**Resume safety:** Cached chapters skipped on re-run.
**Batch mode:** Optional OpenAI Batch API (falls back to sequential).

### 2.7 Fund Copilot RAG

**Entry point:** `app/domains/credit/global_agent/agent.py`
**Flow:** Intent classification → Knowledge base retrieval (Azure Search + BM25) → GPT response generation
**Tenant isolation:** All search queries include `$filter=organization_id eq '{org_id}'`

---

## 3. Package Boundary Map

### 3.1 Core Packages

| Package | Purpose | Public Surface | Key Dependencies | Status |
|---------|---------|----------------|-----------------|--------|
| `app/core/security/` | Clerk JWT v2 auth, Actor resolution, fund access | `get_actor()`, `Actor`, `require_admin()` | jwt, PyJWKClient, Clerk JWKS | Canonical |
| `app/core/tenancy/` | RLS context via SET LOCAL | `get_db_with_rls()`, `get_org_id()` | SQLAlchemy AsyncSession | Canonical |
| `app/core/db/` | Engine, session, base classes, migrations | `get_engine()`, `Base`, mixins, `write_audit_event()` | SQLAlchemy, Alembic, asyncpg | Canonical |
| `app/core/config/` | ConfigService cascade (cache→DB→YAML) | `ConfigService.get()`, `ConfigWriter`, `PgNotifier` | cachetools, SQLAlchemy, pg_notify | Canonical |
| `app/core/jobs/` | SSE streaming + Redis pub/sub job tracking | `create_job_stream()`, `publish_event()`, `register_job_owner()` | sse-starlette, Redis | Canonical |
| `app/core/prompts/` | Admin prompt management, Jinja2 sandbox | `PromptService`, `HardenedPromptEnvironment` | Jinja2 SandboxedEnvironment | Canonical |
| `app/core/middleware/` | Audit logging, rate limiting | `AuditMiddleware`, `RateLimitMiddleware` | — | Canonical |

### 3.2 AI Engine Packages

| Package | Purpose | Public Surface | Key Dependencies | Status |
|---------|---------|----------------|-----------------|--------|
| `ai_engine/pipeline/` | Unified ingestion orchestrator | `process()`, `IngestRequest`, storage routing, search rebuild | All extraction modules | Canonical |
| `ai_engine/classification/` | 3-layer hybrid classifier | `classify()` → `HybridClassificationResult` | sklearn (TF-IDF), OpenAI (L3 fallback) | Canonical |
| `ai_engine/extraction/` | OCR, chunking, embedding, governance, search upsert | Individual stage functions | Mistral API, OpenAI, Azure Search | Canonical |
| `ai_engine/ingestion/` | Batch orchestration, document scanner, registry bridge | `run_full_pipeline_ingest()` | Pipeline + extraction modules | Canonical |
| `ai_engine/validation/` | Vector integrity, deep review validation, eval runner | Validation functions | — | Canonical |
| `ai_engine/prompts/` | Jinja2 templates (extraction/) | Template files (.j2) | Jinja2 | Canonical |

### 3.3 Vertical Engine Packages — Credit (12 packages)

| Package | Purpose | Entry Point | Error Contract | Status |
|---------|---------|-------------|----------------|--------|
| `critic/` | Adversarial IC review | `critique_intelligence()` → `CriticVerdict` | Never-raises | Canonical |
| `deal_conversion/` | Pipeline → Portfolio transition | `convert_pipeline_to_portfolio()` → `ConversionResult` | Raises on validation | Canonical |
| `domain_ai/` | Context retrieval + GPT analysis | `run_deal_ai_analysis()` | Never-raises | Canonical |
| `edgar/` | SEC EDGAR integration | `fetch_edgar_data()`, `fetch_edgar_multi_entity()` | Never-raises | Canonical |
| `kyc/` | KYC Spider screening | `run_kyc_screenings()` | Never-raises | Canonical |
| `market_data/` | Daily macro snapshot (45 FRED series) | `get_macro_snapshot()` | Never-raises (fallback) | Canonical |
| `memo/` | 14-chapter IC memo generator | `generate_memo_book()` | Never-raises | Canonical |
| `pipeline/` | Pipeline ingest orchestrator | `run_pipeline_ingest()` | Never-raises | Canonical |
| `portfolio/` | Portfolio monitoring + ingestion | `run_portfolio_ingest()` | Never-raises | Canonical |
| `quant/` | Deterministic credit quant profile | `compute_quant_profile()` → `QuantProfile` | Raises on math error | Canonical |
| `retrieval/` | Evidence saturation + IC-grade corpus | Evidence curation functions | Never-raises | Canonical |
| `sponsor/` | Sponsor & key person analysis | `analyze_sponsor()` | Never-raises | Canonical |

All follow the same structure: `models.py` (leaf, zero sibling imports) + `service.py` (entry point, imports helpers). Import-linter enforces DAG.

### 3.4 Vertical Engine Packages — Wealth (20+ packages)

| Package | Purpose | Entry Point | Status |
|---------|---------|-------------|--------|
| `fund_analyzer.py` | BaseAnalyzer impl (delegates to DD/Quant) | `run_deal_analysis()`, `run_portfolio_analysis()` | Canonical |
| `dd_report/` | 8-chapter fund DD report | `DDReportEngine.generate()` | Canonical |
| `critic/` | Fund critique (parallel to credit critic) | `critique_intelligence()` | Canonical |
| `fact_sheet/` | Monthly fact sheet PDF | `FactSheetEngine.generate()` | Canonical |
| `screener/` | 3-layer instrument screening | `ScreenerService.screen()` | Canonical |
| `asset_universe/` | Fund approval + universe management | `UniverseService` | Canonical |
| `peer_group/` | Peer matching algorithms | `PeerGroupService` | Canonical |
| `model_portfolio/` | Strategic + tactical allocations | `PortfolioBuilder` | Canonical |
| `watchlist/` | Monitoring + transition detection | `WatchlistService` | Canonical |
| `rebalancing/` | Impact analysis + weight proposal | `RebalancingService` | Canonical |
| `monitoring/` | Strategy drift scanner | `StrategyDriftScanner` | Canonical |
| `correlation/` | Regime-dependent correlation | `CorrelationService` | Canonical |
| `attribution/` | Performance attribution | `AttributionService` | Canonical |
| `mandate_fit/` | Mandate constraint evaluation | `MandateFitService` | Canonical |
| `fee_drag/` | Fee drag analysis | `FeeDragService` | Canonical |
| `macro_committee_engine.py` | Weekly macro reports + emergency workflow | Sync functions | Canonical |
| `quant_analyzer.py` | Portfolio-level quant analysis | Delegates to quant_engine | Canonical |

### 3.5 Quant Engine Services

| Service | Purpose | Config Pattern | Status |
|---------|---------|----------------|--------|
| `cvar_service.py` | Rolling CVaR with breach detection | Parameter-injected (profiles: conservative, moderate, growth) | Canonical |
| `regime_service.py` | Market regime classification (RISK_ON/OFF/INFLATION/CRISIS) | Parameter-injected | Canonical |
| `optimizer_service.py` | Portfolio optimization (cvxpy + CLARABEL) | Parameter-injected | Canonical |
| `drift_service.py` | Drift monitoring (DTW behavioral detection) | Parameter-injected | Canonical |
| `fred_service.py` | FRED API client (TokenBucket rate limiter) | Class-based (API key + rate limiter) | Canonical |
| `scoring_service.py` | Fund scoring (weighted composite 0-100) | Parameter-injected | Canonical |
| `backtest_service.py` | Walk-forward backtesting (sklearn TimeSeriesSplit) | None (algorithmic) | Canonical |
| `stress_severity_service.py` | Stress testing framework | Parameter-injected | Canonical |
| `rebalance_service.py` | Rebalancing logic | Parameter-injected | Canonical |
| `portfolio_metrics_service.py` | Aggregate portfolio stats | Parameter-injected | Canonical |
| `peer_comparison_service.py` | Peer benchmarking | Parameter-injected | Canonical |
| `correlation_regime_service.py` | Regime-dependent correlation | Parameter-injected | Canonical |
| `attribution_service.py` | Performance attribution | Parameter-injected | Canonical |
| `regional_macro_service.py` | Geographic macro analysis | Parameter-injected | Canonical |
| `macro_snapshot_builder.py` | Multi-series aggregation | Parameter-injected | Canonical |
| `lipper_service.py` | Lipper universe integration | Parameter-injected | Canonical |
| `talib_momentum_service.py` | Technical momentum indicators | Parameter-injected | Canonical |

**Key invariant:** All services accept config as parameter (no YAML loading, no `@lru_cache`). Config resolved once at async entry point via `ConfigService.get()`.

### 3.6 Domain Route Packages

| Domain | Router Count | Prefix Pattern | Key Models |
|--------|-------------|----------------|------------|
| **Admin** | 7 | `/admin/*` | VerticalConfigDefault, VerticalConfigOverride, AuditEvent |
| **Credit** | 25+ | `/funds/{fund_id}/*`, `/pipeline/*`, `/ai/*`, `/dashboard/*`, `/documents/*` | Deal, IcMemo, Document, Asset, Obligation, Alert, NavSnapshot, ReportPack |
| **Wealth** | 18 | `/instruments/*`, `/portfolios/*`, `/risk/*`, `/macro/*`, `/screener/*`, `/workers/*` | Instrument (polymorphic), NAV, Portfolio, Risk, Allocation, Macro |

**Total registered routers:** 47 (7 admin + 25 credit + 15 wealth) plus 9 dynamically loaded AI sub-routers.

---

## 4. Legacy / Transitional Map

### 4.1 Deprecated Modules (Retained for Compatibility)

| Module | Replaced By | Status | Evidence |
|--------|-------------|--------|----------|
| `app/domains/wealth/routes/funds.py` | `instruments.py` | DEPRECATED — kept for backward compatibility | File header: "DEPRECATED: Fund CRUD routes" |
| `app/domains/wealth/schemas/fund.py` | `instrument.py` schemas | DEPRECATED — kept for backward compatibility | File header: "DEPRECATED: Fund schemas" |
| `app/domains/wealth/models/fund.py` | `instrument.py` (polymorphic) | DEPRECATED — will be removed | instrument.py header: "This replaces Fund (fund.py)" |
| `app/domains/wealth/workers/fred_ingestion.py` | `macro_ingestion.py` (45-series superset) | DEPRECATED 2026-03-15 | File header with cutover sequence |

### 4.2 Legacy Sync Path

| Module | Purpose | Status |
|--------|---------|--------|
| `app/core/db/session.py` | Sync SQLAlchemy session | Legacy — used by background workers and some sync handlers. Not deprecated, but secondary to async path. |
| `app/domains/credit/modules/ai/extraction.py` | `/pipeline/ingest` sync endpoint | Contains deprecation warning: "DEPRECATED: use /pipeline/ingest/full for canonical pipeline dispatch" |

### 4.3 Stale References (Out-of-Scope Modules)

The following operational module names appear in 18 files (prompts, templates, migration comments) but have NO corresponding code:

| Module Name | Context | Action |
|-------------|---------|--------|
| `cash_management` | Prompt templates, migration comments | Stale references — module removed per product scope |
| `compliance` | Prompt templates | Stale reference — KYC screening retained in `vertical_engines/credit/kyc/` |
| `signatures` / `adobe_sign` | Prompt templates, migration comments | Stale references — module removed |
| `counterparties` | Prompt templates | Stale reference — module removed |

These appear in `ai_engine/prompts/`, `vertical_engines/credit/prompts/`, and `vertical_engines/credit/deep_review/templates/` as context mentions, not as imports or functional code.

### 4.4 Transitional Zones

| Area | Description | Evidence |
|------|-------------|----------|
| Fund → Instrument migration | Wealth domain has dual model paths (Fund + Instrument). Routes coexist. | `funds.py` routes DEPRECATED, `instruments.py` canonical |
| Azure Pipeline Dispatch | `app/services/azure/pipeline_dispatch.py` contains `legacy_path_invoked: False` flag | Suggests legacy dispatch path exists but is disabled |

---

## 5. State, Config, and Runtime Policy Map

### 5.1 Configuration Resolution

**Source of truth:** PostgreSQL (`vertical_config_defaults` + `vertical_config_overrides` tables)
**YAML files:** Seed data only (`profiles/`, `calibration/`). Never read at runtime.

**ConfigService Cascade:**
```
Request → TTLCache (60s) → DB Override (RLS-scoped) → DB Default (global) → YAML fallback (ERROR logged)
```

**Key properties:**
- `deep_merge()`: Recursive override merge (lists REPLACED, not appended)
- `CLIENT_VISIBLE_TYPES`: {calibration, scoring, blocks, portfolio_profiles} — non-admin callers filtered
- `PgNotifier`: PostgreSQL LISTEN/NOTIFY invalidates cache on config writes (no polling)
- Config resolved ONCE at async entry point, passed as parameter to sync vertical/quant engines

### 5.2 Environment Variables

| Category | Key Variables | Notes |
|----------|---------------|-------|
| Core | `DATABASE_URL`, `REDIS_URL`, `APP_ENV`, `LOG_LEVEL` | — |
| Auth | `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `CLERK_PUBLISHABLE_KEY` | Dev bypass: `X-DEV-ACTOR` |
| AI/LLM | `OPENAI_API_KEY`, `AZURE_OPENAI_*` | — |
| Search | `SEARCH_CHUNKS_INDEX_NAME`, `NETZ_ENV` (prefixes indexes) | — |
| Embedding | `OPENAI_EMBEDDING_MODEL=text-embedding-3-large` | — |
| ADLS | `FEATURE_ADLS_ENABLED=false`, `ADLS_*` | Feature flag: local dev uses LocalStorageClient |
| Feature Flags | `FEATURE_LIPPER_ENABLED`, `FEATURE_WEALTH_FACT_SHEETS`, etc. | Boolean flags |

**Validation:** `validate_production_secrets()` runs at startup — prevents dev bypass in production with real secrets.

### 5.3 Tenant-Specific Behavior

| Mechanism | Scope | Implementation |
|-----------|-------|----------------|
| **RLS (Row-Level Security)** | All tenant-scoped tables | `SET LOCAL app.current_organization_id` via `get_db_with_rls()` |
| **Config Overrides** | Per-organization config | `VerticalConfigOverride` WHERE `organization_id = ?` (sparse overrides) |
| **ADLS Path Scoping** | All storage operations | `{tier}/{organization_id}/{vertical}/` enforced by `storage_routing.py` |
| **Search Filtering** | All RAG queries | `$filter=organization_id eq '{org_id}'` on every Azure Search call |
| **Branding** | Tenant logos, themes | `admin/branding` routes + tenant assets |
| **Prompt Overrides** | Per-organization prompt customization | `PromptOverride` WHERE `organization_id = ?` |

**Global tables (no RLS):** `macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav`

---

## 6. Auditability / Operator Visibility Map

### 6.1 Audit Trail

| Mechanism | Location | Granularity |
|-----------|----------|-------------|
| `AuditEvent` table | `app/core/db/models.py` + `audit.py` | Per-action (create/update/delete + actor_id + fund_id + before/after state) |
| Pipeline audit events | `unified_pipeline.py` → `write_audit_event()` | Per-stage (OCR, classify, chunk, index, terminal) |
| `PipelineIngestJob` table | `ai_engine/ingestion/` | Per-batch-run (counters, timing, errors) |
| Admin audit routes | `app/domains/admin/routes/audit.py` | Query interface for audit logs |

### 6.2 Job Tracking (SSE + Redis)

| Component | Purpose |
|-----------|---------|
| `register_job_owner()` | Associates job_id with organization_id (tenant isolation) |
| `publish_event()` | Real-time progress via Redis pub/sub channel `job:{id}:events` |
| `publish_terminal_event()` | Terminal state + cleanup (ASYNC-01: reduces TTL to 120s grace) |
| `verify_job_owner()` | SSE auth check — prevents cross-tenant job stream access |
| SSE heartbeat | Every 15s (Azure idle timeout = 30s) |

### 6.3 Structured Failure Handling

| Pattern | Scope | Behavior |
|---------|-------|----------|
| **Validation gates** | Unified pipeline | Halts pipeline on hard failures (OCR too short, invalid doc_type, zero chunks, embedding mismatch) |
| **Degraded quality markers** | Extraction/summary | `extraction_quality: DEGRADED_*` — pipeline continues, marker persisted in search index |
| **Terminal states** | Pipeline | `success` / `degraded` / `failed` — persisted to Redis + audit table |
| **Never-raises pattern** | Vertical engines | Returns `{"status": "NOT_ASSESSED"}` on failure (logs with `exc_info=True`) |
| **Dual-write resilience** | ADLS → Search | Partial ADLS failure warns but continues. Total ADLS failure skips Search. |
| **UpsertResult** | Search indexing | Tracks attempted/successful/failed/retryable per batch |

### 6.4 Logging

| Pattern | Example |
|---------|---------|
| Pipeline single-line summary | `[pipeline] SUCCESS <filename> → <doc_type> (L2) | 47 chunks | 45/50 indexed | 3422ms` |
| Config miss | `[CFG-01] Required config miss: vertical=private_credit, type=chapters` |
| YAML fallback | `[ERROR] ConfigService falling back to YAML for ...` |
| Worker completion | Per-worker logging with timing + error counts |

---

## 7. Structural Risks

### 7.1 In-Process Worker Model

All 8 wealth workers and all document ingestion run as `BackgroundTasks` within the ASGI process. No Celery, no external queue. A long-running worker (e.g., `fact_sheet_gen` generating PDFs) competes for the same event loop and thread pool as API request handling. No worker isolation, no retry queue, no dead-letter handling beyond in-process try/except.

**Evidence:** `app/domains/wealth/routes/workers.py` — all workers dispatched via `background_tasks.add_task()`.

### 7.2 Stale Operational Module References

18 files reference removed operational modules (`cash_management`, `signatures`, `counterparties`, `compliance`) in prompt templates and migration comments. While not functional imports, they create false context in IC memo generation if prompt templates reference non-existent capabilities.

**Evidence:** Grep for `cash_management|counterparties|adobe_sign|signatures` across `backend/` returns 18 file matches.

### 7.3 Dual Model Path (Fund vs Instrument)

Wealth domain maintains both `Fund` (deprecated) and `Instrument` (canonical polymorphic) models with parallel route files. Dual paths increase surface area for inconsistency until Fund removal is complete.

**Evidence:** `app/domains/wealth/models/fund.py` ("DEPRECATED"), `app/domains/wealth/routes/funds.py` ("DEPRECATED: kept for backward compatibility"), coexisting with `instruments.py`.

### 7.4 Fred Ingestion Worker Overlap Risk

Deprecated `fred_ingestion.py` and canonical `macro_ingestion.py` both write to `macro_data` with the same series IDs. Concurrent execution causes non-deterministic staleness in `regime_service`. Cutover sequence documented but not enforced programmatically.

**Evidence:** `app/domains/wealth/workers/fred_ingestion.py` header: "DO NOT run both workers simultaneously".

### 7.5 Search Index as Single Point of Failure for RAG

Azure Search is the sole retrieval path for RAG queries (Fund Copilot, IC memo evidence). While `search_rebuild.py` can reconstruct from ADLS silver Parquet, there is no automatic failover or degraded-mode retrieval if Search is unavailable.

**Evidence:** `ai_engine/pipeline/search_rebuild.py` exists as manual recovery. No circuit breaker or fallback path in `global_agent/` or evidence retrieval.

### 7.6 Advisory Lock Scope for Search Rebuild

`search_rebuild.py` uses Redis advisory lock to prevent concurrent rebuilds. If the process crashes during rebuild, lock may not be released (depends on Redis key TTL configuration).

**Evidence:** `ai_engine/pipeline/search_rebuild.py` — advisory lock acquisition without documented TTL.

### 7.7 Import-Linter Coverage Gaps

Import-linter enforces 35+ contracts across credit and wealth verticals. However, `quant_engine` services beyond `regime_service`, `cvar_service`, and `correlation_regime_service` are NOT covered by vertical-agnosticism contracts. Other quant services could develop accidental wealth domain imports without detection.

**Evidence:** `pyproject.toml` — only 3 of 17 quant services have explicit vertical-isolation contracts.

---

## 8. Router Registration Map

### 8.1 Admin Domain (7 routers)

| Router | Prefix | Auth |
|--------|--------|------|
| `admin_branding_router` | `/admin/branding` | Standard |
| `admin_assets_router` | `/assets/tenant/{org_slug}/{asset_type}` | Unauthenticated |
| `admin_configs_router` | `/admin/configs` | Super-admin |
| `admin_tenants_router` | `/admin/tenants` | Super-admin |
| `admin_prompts_router` | `/admin/prompts` | Super-admin |
| `admin_health_router` | `/admin/health` | Standard |
| `admin_audit_router` | `/admin/audit` | Super-admin |

### 8.2 Credit Domain (25+ routers)

**Deals:** 3 routers (`/funds/{fund_id}/deals`, `/funds/{fund_id}/deals/{deal_id}/ic-memo`, `/pipeline/deals/{deal_id}/convert`)
**Portfolio:** 5 routers (`/funds/{fund_id}/assets`, `/alerts`, `/obligations`, `/portfolio-actions`, `/fund-investments`)
**Documents:** 6 routers (`/funds/{fund_id}/documents`, `/evidence/upload-request`, `/documents/{doc_id}/review`, `/evidence`, `/audit`, `/documents`)
**Reporting:** 5 routers (`/reports/packs`, `/investor-portal`, `/evidence-packs`, `/reports`, `/schedules`)
**Dashboard:** 2 routers (`/dashboard`, `/dashboard/task-inbox`)
**Dataroom:** 2 routers (`/funds/{fund_id}/dataroom`, `/funds/{fund_id}/data-room`)
**Actions:** 1 router (`/funds/{fund_id}/actions`)
**AI Modules:** 9 dynamically loaded sub-routers under `/ai/*` (copilot, documents, compliance, pipeline_deals, extraction, portfolio, deep_review, memo_chapters, artifacts)
**Pipeline Deals:** 1 router (`/pipeline/deals`)
**Module Documents:** 1 router (`/documents`)

### 8.3 Wealth Domain (18 routers)

| Router | Prefix | Notes |
|--------|--------|-------|
| `wealth_instruments_router` | `/instruments` | Canonical (replaces funds) |
| `wealth_funds_router` | `/funds` | DEPRECATED |
| `wealth_allocation_router` | `/allocation` | |
| `wealth_analytics_router` | `/analytics` | |
| `wealth_portfolios_router` | `/portfolios` | |
| `wealth_risk_router` | `/risk` | |
| `wealth_macro_router` | `/macro` | |
| `wealth_workers_router` | `/workers` | Background task triggers |
| `wealth_dd_reports_router` | `/dd-reports` | |
| `wealth_universe_router` | `/universe` | |
| `wealth_model_portfolios_router` | `/model-portfolios` | |
| `wealth_fact_sheets_router` | `/fact-sheets` | |
| `wealth_content_router` | `/content` | |
| `wealth_screener_router` | `/screener` | |
| `wealth_strategy_drift_router` | `/strategy-drift` | |
| `wealth_attribution_router` | `/attribution` | |
| `wealth_correlation_regime_router` | `/correlation-regime` | |
| `wealth_exposure_router` | `/exposure` | |

### 8.4 Utility Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health status + AI router diagnostics |
| `GET /api/health` | Dual-mount for Azure SWA proxy |
| `GET /api/v1/` | API root info |
| `GET /api/v1/jobs/{job_id}/stream` | SSE streaming (auth required) |
| `POST /api/v1/test/sse/{job_id}/emit` | Dev-only test event |

---

## 9. Import Architecture (import-linter)

**Root packages:** `vertical_engines`, `quant_engine`, `app`
**Total contracts:** 35+

### 9.1 Structural Contracts

| Contract | Type | Scope |
|----------|------|-------|
| Verticals must not import each other | Independence | `vertical_engines.credit` ↔ `vertical_engines.wealth` |
| Engine models must not import service | Forbidden | All credit packages |
| Domain helpers must not import service | Forbidden | All credit packages (allows indirect) |
| Deep review internal DAG | Layers | 5-tier: models → helpers → domain → persist → portfolio → service |

### 9.2 Vertical-Agnostic Contracts

| Contract | Enforced On |
|----------|-------------|
| Must not import `app.domains.wealth` | `quant_engine.regime_service`, `quant_engine.cvar_service`, `quant_engine.correlation_regime_service` |

### 9.3 Wealth Vertical Contracts

Mirror credit contracts for all 20+ wealth packages: models → service forbidden, helpers → service forbidden, per-package.

---

## 10. Data Model Summary

### 10.1 Tenant-Scoped Tables (RLS Active)

**Credit:** Deal, DealQualification, IcMemo, Document, DocumentReview, EvidenceDocument, Asset, Obligation, Alert, Action, FundInvestment, NavSnapshot, ReportPack, InvestorStatement, AssetValuationSnapshot, PipelineDeal, PipelineIngestJob, DocumentRegistry, DealDocument, AuditEvent

**Wealth:** Instrument (polymorphic: fund, bond, equity), NAV timeseries, Portfolio holdings, Risk metrics, Allocation, Rebalance, DD Report, Content, Screening results, Watchlist, Macro Regional Snapshots

### 10.2 Global Tables (No RLS)

`macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav`

### 10.3 Config Tables

`vertical_config_defaults` (no RLS, Netz-managed), `vertical_config_overrides` (RLS on organization_id)

### 10.4 Latest Migration Head

`0019_audit_events` (19 migrations total)

---

## 11. Middleware Stack

Applied in order:
1. **CORS** — Origins from `settings.cors_origins`
2. **Rate Limiting** — `RateLimitMiddleware` (configurable RPM per role)
3. **Auth** — Clerk JWT v2 via `get_actor()` dependency
4. **Tenancy** — `get_db_with_rls()` dependency (SET LOCAL)
5. **Audit** — `AuditMiddleware` (request/response logging)

---

*This system map is intended as a baseline for validation and contradiction audits. All claims are tied to repository evidence (file paths, imports, module headers). Sections labeled "DEPRECATED" or "legacy" reflect explicit markers in the source code, not editorial judgment.*
