# Backend System Map v2

> Generated 2026-03-18. Mapping only — no audit, no recommendations.
> Supersedes v1 (2026-03-17) with full canonical flow tracing, package classification, and config/tenant/audit boundary mapping.

---

## 1. Architecture Overview

### 1.1 Main Runtime Boundaries

| Boundary | Technology | Role |
|----------|-----------|------|
| **HTTP API** | FastAPI + Uvicorn | Async request handling, 30+ routers (admin 6, wealth 18, credit 22) |
| **Database** | PostgreSQL 16 + TimescaleDB | RLS-enforced tenant isolation, async via asyncpg, 17 migrations (head: `0017_fund_membership`) |
| **Cache / Pub-Sub** | Redis 7 | Job event pub/sub (SSE bridging), config invalidation, job ownership TTL |
| **Data Lake** | ADLS Gen2 / LocalStorageClient | Bronze/silver/gold document hierarchy with `{org_id}/{vertical}/` prefix |
| **Search Index** | Azure AI Search | Vector + keyword index, derived from silver Parquet, env-prefixed (`{NETZ_ENV}-global-vector-chunks-v2`) |
| **LLM** | OpenAI (direct) / Azure OpenAI (fallback) / Azure AI Foundry | Structured JSON output, temperature 0.2, 600s timeout |
| **OCR** | Mistral (mistral-ocr-latest) | PDF → markdown extraction |
| **SEC Filings** | edgartools | EDGAR integration with Redis-based distributed rate limiting (8 req/s) |

### 1.2 AI Engine Responsibilities (`ai_engine/`)

Domain-agnostic universal core. Never modified per vertical.

- **Unified Pipeline** (`pipeline/unified_pipeline.py`) — single ingestion path: pre-filter → OCR → classify → governance → chunk → extract → embed → store → index. Each stage returns `PipelineStageResult` with success/failure/degradation.
- **Hybrid Classification** (`classification/hybrid_classifier.py`) — three-layer (rules → TF-IDF cosine → LLM fallback), zero external ML APIs.
- **Extraction** (`extraction/`) — OCR (Mistral), semantic chunking, entity bootstrap, metadata extraction, summarization.
- **Governance** (`governance/`) — governance policy detection, compliance checks.
- **Validation** (`validation/`) — pipeline gates, vector integrity guard (`EMBEDDING_DIMENSIONS` enforcement), deep review validation.
- **Prompts** (`prompts/`) — Jinja2 `SandboxedEnvironment` with SSTI protection, multi-path resolution (base + vertical overlays). Prompt content is Netz IP — never exposed in client-facing responses.
- **Ingestion** (`ingestion/`) — `pipeline_ingest_runner.py` orchestrates full lifecycle (scan → discover → bridge → ingest → deep review).

### 1.3 Pipeline Responsibilities

The unified pipeline is the **single ingestion path** for all document sources (UI upload, batch API, pipeline discovery). Stages use validation gates that can halt or degrade the pipeline. Dual-write pattern ensures ADLS is source of truth; Azure Search is derived and rebuildable.

### 1.4 Worker / Job Orchestration Boundaries

- **Wealth workers** (`app/domains/wealth/routes/workers.py`) — 8 background tasks (ingestion, risk calc, portfolio eval, macro, DD reports, benchmarks, drift check, fact sheets). All return 202 Accepted with `BackgroundTasks`.
- **Credit pipeline** — Long-running jobs tracked via Redis pub/sub + SSE (`app/core/jobs/`). Frontend consumes via `fetch()` + `ReadableStream` (not EventSource — auth headers needed).
- **Job ownership** (`tracker.py`) — Redis keys `job:{id}:org` with TTL, refresh for long-running jobs (ASYNC-01), grace period cleanup after terminal events.

### 1.5 Config / Governance Boundaries

- **ConfigService** (`app/core/config/config_service.py`) — single source of truth. Resolution: TTLCache (60s) → resolve base (DB default or YAML fallback) → deep-merge org override on top if org_id provided → cache result.
- **ConfigRegistry** (`app/core/config/registry.py`) — 14+ registered `(vertical, config_type)` pairs. Client visibility via `CLIENT_VISIBLE_TYPES` allowlist.
- **PgNotifier** (`app/core/config/pg_notify.py`) — PostgreSQL LISTEN/NOTIFY for cache invalidation. Dedicated asyncpg connection (not from pool). Exponential backoff reconnect.

### 1.6 Storage / Indexing Boundaries

- **StorageClient** (`app/services/storage_client.py`) — abstract base with `LocalStorageClient` (dev) and `ADLSStorageClient` (prod). Feature-flagged via `FEATURE_ADLS_ENABLED`.
- **Path routing** (`ai_engine/pipeline/storage_routing.py`) — deterministic path builders: `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`, `global_reference_path()`. Validated with `_SAFE_PATH_SEGMENT_RE`.
- **Azure Search** (`app/services/azure/search_client.py`) — credential resolution (key or DefaultAzureCredential), index name scoping, health check.

---

## 2. Runtime Anchors

### 2.1 API App Bootstrap

**File:** `backend/app/main.py`

**Lifespan startup sequence** (lines 150-207):
1. `settings.validate_production_secrets()` — validates auth & storage creds
2. `set_identity()` (edgartools) — SEC EDGAR user-agent registration
3. `describe_chunks_index_contract()` — Azure Search chunks index contract resolution
4. `_verify_config_completeness()` — validates migration 0004 seeded all expected defaults
5. `PgNotifier` initialization — PostgreSQL NOTIFY listener for config cache invalidation
6. `ConfigService` cache invalidation callback registration

**Lifespan shutdown:**
1. `pg_notifier.stop()` — graceful listener shutdown
2. `engine.dispose()` — async SQLAlchemy engine cleanup
3. `close_redis_pool()` — Redis connection pool closure

### 2.2 Router Registration

**Health:** `GET /health` and `GET /api/health` — basic health check with AI router diagnostics.

**API v1 root:** `APIRouter(prefix="/api/v1")`

| Group | Router Count | Prefix | Auth |
|-------|-------------|--------|------|
| **SSE** | 1 | `/api/v1/jobs/{job_id}/stream` | Actor + job ownership |
| **Admin** | 6 | `/api/v1/admin/` | X-Netz-Admin-Key |
| **Wealth** | 18 | `/api/v1/wealth/` | Clerk JWT |
| **Credit** | 22 | `/api/v1/credit/` | Clerk JWT |
| **AI Modules** | 9 subrouters | `/api/v1/credit/ai/` | Clerk JWT |

**AI Router Assembly** (`app/domains/credit/modules/ai/__init__.py`):
Dynamic loading of 9 subrouters in `_assemble()`: copilot, documents, compliance, pipeline_deals, extraction (optional), portfolio (optional), deep_review, memo_chapters, artifacts. Failure triggers startup error with diagnostic output.

### 2.3 Authentication & Tenant Context

**Clerk JWT v2** (`app/core/security/clerk_auth.py`):
- `_verify_clerk_jwt()` — decode JWT, auto-refresh keys on rotation
- Claims: `sub` (user ID), `o.id` (org ID), `o.rol` (role), `o.slg` (slug)
- `Actor` dataclass: `actor_id`, `name`, `email`, `roles`, `organization_id`, `organization_slug`, `fund_ids`

**RLS Enforcement** (`app/core/tenancy/middleware.py`):
- `get_db_with_rls()` — `SET LOCAL app.current_organization_id = :oid` (transaction-scoped)
- RLS policies use subselect: `(SELECT current_setting(...))::uuid` — **critical** for performance (1000x without)
- `SET LOCAL` (not `SET`) — safe for connection pooling

**Dev bypass:** `X-DEV-ACTOR` header with `dev_token` — no JWT verification.

**Admin bypass:** `get_db_admin()` — `SET LOCAL app.admin_mode = 'true'` for cross-tenant queries.

### 2.4 Database & Session Management

**File:** `backend/app/core/db/engine.py`

- Async engine: `postgresql+asyncpg://...`, pool_size=20, max_overflow=10, pool_pre_ping=True
- `expire_on_commit=False` — **critical** for async/ORM safety
- `lazy="raise"` — enforced on all relationships (forces explicit eager loading)
- Session factories: async (`async_sessionmaker`) and sync (`sessionmaker`) — both expire_on_commit=False
- FastAPI deps: `get_db()` (plain), `get_db_with_rls()` (tenant-scoped), `get_db_admin()` (cross-tenant)

**Alembic:** 17 migrations (0001_foundation → 0017_fund_membership). Sync driver `postgresql+psycopg://` for migrations. Extensions: TimescaleDB, uuid-ossp, pgcrypto.

### 2.5 Redis & Job Tracking

**File:** `backend/app/core/jobs/tracker.py`

**Connection:** Lazy init via `get_redis_pool()`, max_connections=100, decode_responses=True.

**Job ownership lifecycle (ASYNC-01):**
- `register_job_owner(job_id, org_id, ttl=3600)` → `SET job:{id}:org {org_id} EX 3600`
- `refresh_job_owner_ttl(job_id)` → extend TTL for long-running jobs
- `verify_job_owner(job_id, org_id)` → auth check before SSE stream
- `clear_job_owner(job_id, grace_ttl=120)` → short grace before expiry

**Event publishing:**
- `publish_event(job_id, event_type, data)` → Redis PUBLISH `job:{id}:events`
- `publish_terminal_event()` → atomic publish + ownership cleanup
- Terminal types: `{done, error, ingestion_complete, memo_complete, report_completed, report_failed}`

**Job state persistence:**
- `persist_job_state(job_id, terminal_state, counts, errors)` → `SET job:{id}:state {json} EX 86400`
- Terminal states: success, degraded, failed

**SSE stream** (`app/core/jobs/sse.py`):
- `create_job_stream(request, job_id)` → `EventSourceResponse`
- Heartbeat: ping every 15s (Azure Container Apps 30s timeout)

### 2.6 LLM Orchestration

**File:** `backend/ai_engine/openai_client.py`

- Singleton `_get_client()` with provider priority: OpenAI direct → Azure OpenAI → Azure AI Foundry
- `call_openai()` wrapper (`ai_engine/llm/call_openai.py`): sync, temperature=0.2, response_format=json_object, retry once on parse failure
- Model resolution via `model_config.get_model("structured")`

---

## 3. Canonical Backend Flows

### 3.1 Document Ingestion (Unified Pipeline)

**Entry point:** `POST /documents/ingestion/process-pending` (or upload routes) → `unified_pipeline.process()`

**Orchestrator:** `ai_engine/pipeline/unified_pipeline.py`

**Stages:**
1. **Pre-filter** — exclude standard compliance forms (skip_filter)
2. **OCR** — `mistral_ocr.async_extract_pdf_with_mistral(pdf_bytes)` → PageBlock list
3. **OCR validation gate**
4. **Classification** — `hybrid_classifier.classify(text, filename)` → HybridClassificationResult
5. **Classification validation gate**
6. **Governance detection** — `governance_detector.detect_governance(ocr_text)` → GovernanceResult
7. **Chunking** — `semantic_chunker.chunk_document(ocr_markdown, doc_id, doc_type, metadata)` → chunk list
8. **Chunk validation gate**
9. **Metadata extraction** (parallel) — `document_intelligence.async_extract_metadata()` + `async_summarize_document()`
10. **Embedding** — `embed_chunks.embed_batch(texts)` via `asyncio.to_thread()` (OpenAI text-embedding-3-large)
11. **Embedding validation gate**
12. **ADLS storage** (dual-write step 1) — bronze doc JSON, silver chunks Parquet (zstd, includes `embedding_model` + `embedding_dim`), silver metadata JSON
13. **Azure Search indexing** (dual-write step 2) — `search_upsert_service.upsert_chunks()` (100 per batch)
14. **Terminal state determination** — success / degraded / failed

**Persistence:**
| Layer | Path | Content |
|-------|------|---------|
| Bronze (ADLS) | `bronze/{org}/{vertical}/documents/{doc_id}.json` | Raw OCR text + page count |
| Silver chunks (ADLS) | `silver/{org}/{vertical}/chunks/{doc_id}/chunks.parquet` | Chunks + embeddings + dims |
| Silver metadata (ADLS) | `silver/{org}/{vertical}/documents/{doc_id}/metadata.json` | Classification + governance + extraction quality |
| Azure Search | Chunks index | Searchable chunks + vectors + `organization_id` |

**Events:** `publish_event()` at each stage transition → `publish_terminal_event()` at completion.

**Tenant boundary:** `org_id` in all ADLS paths, all Azure Search documents, Redis job ownership.

### 3.2 Pipeline Ingest Lifecycle

**Entry point:** `async_run_full_pipeline_ingest()` in `ai_engine/ingestion/pipeline_ingest_runner.py`
**CLI:** `python -m ai_engine.ingestion.pipeline_ingest_runner --fund-id <UUID>`

**Stages:**
1. **Scan** — `document_scanner.scan_document_registry()` → DocumentRegistry rows
2. **Discover** — `pipeline/discovery.discover_pipeline_deals()` → PipelineDeal rows from folder structure
3. **Bridge** — `registry_bridge.bridge_registry_to_deal_documents()` → DealDocument rows
4. **Ingest** — per-document via unified pipeline (or skipped if already processed)
5. **Deep Review** — `run_all_deals_deep_review_v4()` for all deals

**Persistence:** `PipelineIngestJob` row with counters (scanned, discovered, bridged, ingested, reviewed), timing, errors.

### 3.3 Hybrid Classification

**Orchestrator:** `ai_engine/classification/hybrid_classifier.py`

**Three layers (no external ML APIs):**
1. **Layer 1 — Rules** (~60%): filename + keyword matching
2. **Layer 2 — TF-IDF** (~30%): cosine similarity against reference corpus
3. **Layer 3 — LLM** (~10%): GPT-4 classification fallback

**Output:** `HybridClassificationResult` with `doc_type`, `vehicle_type`, `confidence`, `layer`.

### 3.4 Deep Review V4 (IC Investment Memorandum)

**Entry point:** `run_deal_deep_review_v4(db, fund_id, deal_id, organization_id, full_mode)` in `vertical_engines/credit/deep_review/service.py`

**13-stage pipeline:**
1. Cache check → `artifact_exists_v4()` / `load_cached_artifact_v4()`
2. RAG context extraction → `_gather_deal_texts()` (reuses V3 corpus)
3. Structured deal analysis (LLM)
4. Macro context injection → FRED Market Data Engine (deterministic)
5. Quant engine injection → `compute_quant_profile()` (deterministic)
6. Concentration engine injection → `compute_concentration()` (deterministic)
7. Hard policy checks → `_run_hard_policy_checks()` (deterministic)
8. Policy compliance assessment (LLM)
9. Sponsor & Key Person engine (LLM) → `analyze_sponsor()`
10. Evidence Pack generation → `build_evidence_pack()` (freeze truth surface)
11. IC Critic loop → `critique_intelligence()` (adversarial review)
12. 13-Chapter Memo Book → `generate_memo_book()` (per-chapter bounded context)
13. Atomic versioned persist → chapters + evidence pack + metadata

**Token budget governance:** Full mode unlocks higher ceilings (structured 6000, sponsor 8000, memo 10000, critic 10000, escalation 16000).

**Persistence:** Gold layer `{org_id}/{vertical}/memo/{deal_id}/`, DB ICMemo versioning.

### 3.5 Global Agent / Fund Copilot

**Entry point:** `/copilot/answer` → `NetzGlobalAgent.answer()`

**Pipeline:**
1. Intent routing → `IntentRouter.detect_domains(question, deal_folder)` → PIPELINE, REGULATORY, CONSTITUTION, SERVICE_PROVIDER
2. Parallel retrieval from 4 indexes (pipeline chunks, fund constitution, regulatory, service providers)
3. RBAC scope filtering
4. Evidence merge with deal-context injection
5. LLM generation → cross-validate, confidence scoring, citation formatting

**Search scope:** All queries include `$filter=organization_id eq '{org_id}'`.

### 3.6 IC Memo Generation & Versioning

**Entry point:** `POST /funds/{fund_id}/deals/{deal_id}/ic-memo` → `generate_memo_book()`

**Services:** `vertical_engines/credit/memo/` — chapter generation, tone normalization, evidence indexing, batch processing.

**Persistence:** ICMemo table with auto-increment versioning, gold layer memo chapters as JSON.

### 3.7 Search Rebuild

**Entry point:** `rebuild_search_index(org_id, vertical, doc_ids, deal_id, fund_id)` in `ai_engine/pipeline/search_rebuild.py`

**Process:**
1. List all `silver/{org}/{vertical}/chunks/*/chunks.parquet` files
2. Validate embedding dimensions against `vector_integrity_guard.EMBEDDING_DIMENSIONS`
3. Reconstruct search documents
4. Upsert to Azure Search — **no OCR, no LLM calls needed**

### 3.8 Quant Engine Flows

**18 vertical-agnostic services** (`backend/quant_engine/`), all sync, config as parameter:

| Service | Purpose |
|---------|---------|
| `fred_service` | FRED indicator fetch (rate-limited 120 req/60s) |
| `cvar_service` | Conditional Value at Risk |
| `regime_service` | Market regime classification (bull/bear/neutral) |
| `correlation_regime_service` | Cross-asset correlation regimes |
| `scoring_service` | Fund scoring (performance-based ranking) |
| `optimizer_service` | Mean-Variance Optimizer (CVXPY) |
| `attribution_service` | Brinson-Fachler attribution |
| `rebalance_service` | Rebalancing trade recommendations |
| `drift_service` | Tracking error + style drift |
| `backtest_service` | Historical stress validation |
| `stress_severity_service` | Scenario severity ranking |
| `talib_momentum_service` | TA-Lib momentum signals |
| `peer_comparison_service` | Peer group analysis |
| `portfolio_metrics_service` | Sharpe, Sortino, etc. |
| `regional_macro_service` | Regional macro snapshot |
| `macro_snapshot_builder` | Macro aggregation helper |

**Config pattern:** Sync functions receive config as parameter. No YAML loading, no `@lru_cache`. Config resolved once at async entry point via `ConfigService.get()`.

### 3.9 KYC Screening

**Entry point:** `run_kyc_screenings()` in `vertical_engines/credit/kyc/service.py`

**Process:** Extract persons (max 30) + organizations (max 15) → parallel screening via `KYCSpiderClient` with `ThreadPoolExecutor(max_workers=3)`.

**Never-raises contract:** Returns dict with `summary.skipped=True` on failure.

### 3.10 EDGAR Integration

**Entry point:** `fetch_edgar_multi_entity()` in `vertical_engines/credit/edgar/service.py`

**Process:** CIK resolution → parallel fetches (3 workers) → parse financials → compute ratios → going concern check → insider signals.

**SEC compliance:** User-Agent `"Netz Analysis Engine tech@netzco.com"`, distributed rate limit 8 req/s (Redis sliding window).

**Never-raises contract:** Returns `EdgarEntityResult` with status; all errors in warnings list.

### 3.11 Wealth Background Workers

**Entry point:** `POST /wealth/workers/run-{task}` → 202 Accepted + `BackgroundTasks`

| Worker | Purpose |
|--------|---------|
| `run-ingestion` | NAV ingestion from Yahoo Finance (yfinance, retry 3x, ThreadPoolExecutor) |
| `run-risk-calc` | CVaR/VaR/returns/volatility/drawdown/Sharpe |
| `run-portfolio-eval` | CVaR status, breach days, regime, daily snapshots |
| `run-macro-ingestion` | Macro indicator ingestion |
| `run-dd-reports` | Due diligence report generation |
| `run-benchmark-ingest` | Benchmark data ingestion |
| `run-drift-check` | Strategy drift monitoring |
| `run-fact-sheet-gen` | Fact sheet PDF generation |

Auth: Admin/INVESTMENT_TEAM role required.

### 3.12 Deal Conversion

**Entry point:** `POST /funds/{fund_id}/deals/{deal_id}/convert` → `convert_deal_to_asset()`

**Preconditions:** Deal.stage == APPROVED, Deal.asset_id == None.

**Output:** Creates Asset row linked to Deal + audit trail.

---

## 4. Package Boundary Map

### 4.1 Core Infrastructure (`app/core/`)

| Package | Classification | Purpose | Key Exports |
|---------|---------------|---------|-------------|
| `config/` | **Canonical** | Vertical config cascade (DB + YAML), registry, cache invalidation | `ConfigService`, `ConfigRegistry`, `PgNotifier` |
| `db/` | **Canonical** | Async engine, RLS enforcement, audit trail, migrations | `async_session_factory`, `Base`, `OrganizationScopedMixin` |
| `jobs/` | **Canonical** | SSE streaming, Redis pub/sub, job ownership TTL | `create_job_stream()`, `publish_event()`, `register_job_owner()` |
| `security/` | **Canonical** | Clerk JWT v2 verification, dev bypass, admin auth | `get_actor()`, `Actor`, `verify_admin_key()` |
| `tenancy/` | **Canonical** | RLS context setup (SET LOCAL per transaction) | `get_db_with_rls()`, `get_db_admin()` |
| `prompts/` | **Canonical** | Prompt template registry (SandboxedEnvironment), override tracking | `PromptService` |
| `middleware/` | **Utility** | Request-scoped logging, audit middleware | `AuditMiddleware` |

### 4.2 Domains (`app/domains/`)

#### Admin (`app/domains/admin/`)

| Module | Classification | Purpose |
|--------|---------------|---------|
| `routes/configs.py` | Canonical | Config override writes with guardrail validation |
| `routes/tenants.py` | Canonical | Org CRUD, RLS inspection |
| `routes/health.py` | Canonical | Config health, invalid override detection |
| `routes/prompts.py` | Canonical | Prompt upload/override |
| `routes/branding.py` | Canonical | Tenant branding |
| `routes/assets.py` | Canonical | Asset repository |
| `services/config_writer.py` | Canonical | Config write + guardrail validation |

#### Credit (`app/domains/credit/`)

| Sub-module | Classification | Route Count | Purpose |
|------------|---------------|-------------|---------|
| `deals/` | Canonical | 3 routers | Deal CRUD, IC memo generation, conversion |
| `documents/` | Canonical | 6 routers | Upload, OCR, review, evidence, audit, ingestion |
| `portfolio/` | Canonical | 5 routers | Assets, obligations, alerts, actions, fund investments |
| `reporting/` | Canonical | 5 routers | Reports, report packs, schedules, evidence packs, investor portal |
| `dashboard/` | Canonical | 1 router | Executive dashboard aggregation |
| `dataroom/` | Canonical | 1 router | Folder access control, document governance |
| `actions/` | Canonical | 1 router | Fund-level actions (review triggers, escalations) |
| `modules/ai/` | **Transitional** | 9 subrouters | AI module assembly (copilot, deep_review, memo_chapters, etc.) |
| `modules/deals/` | **Transitional** | — | Legacy deal routes (prefer `deals/`) |
| `modules/documents/` | **Transitional** | — | Legacy document routes (prefer `documents/`) |

#### Wealth (`app/domains/wealth/`)

| Module | Classification | Purpose |
|--------|---------------|---------|
| `routes/funds.py` | Canonical | Fund CRUD |
| `routes/instruments.py` | Canonical | Asset universe |
| `routes/dd_reports.py` | Canonical | DD report generation (async → SSE) |
| `routes/fact_sheets.py` | Canonical | Fact sheet generation |
| `routes/analytics.py` | Canonical | Portfolio analytics |
| `routes/exposure.py` | Canonical | Asset allocation breakdown |
| `routes/portfolio.py` | Canonical | Portfolio CRUD |
| `routes/model_portfolios.py` | Canonical | Model portfolio construction |
| `routes/screener.py` | Canonical | Fund screener (3-layer) |
| `routes/universe.py` | Canonical | Approved fund universe |
| `routes/allocation.py` | Canonical | Allocation blocks |
| `routes/macro.py` | Canonical | Macro snapshot |
| `routes/risk.py` | Canonical | Risk analytics |
| `routes/content.py` | Canonical | Investment outlook, flash report, manager spotlight |
| `routes/attribution.py` | Canonical | Brinson attribution |
| `routes/correlation_regime.py` | Canonical | Regime-aware correlation |
| `routes/strategy_drift.py` | Canonical | Strategy drift alerts |
| `routes/workers.py` | Canonical | Background job dispatch |
| `workers/ingestion.py` | Canonical | NAV ingestion worker (yfinance, retry 3x) |

### 4.3 AI Engine (`ai_engine/`)

| Package | Classification | Purpose | Key Dependencies |
|---------|---------------|---------|------------------|
| `classification/` | **Canonical** | Hybrid 3-layer classifier | scikit-learn TF-IDF, OpenAI LLM fallback |
| `pipeline/` | **Canonical** | Unified ingestion orchestrator | StorageClient, SearchClient, all extraction modules |
| `extraction/` | **Canonical** | OCR, chunking, embedding, entity bootstrap | Mistral API, OpenAI embeddings |
| `governance/` | **Canonical** | Policy detection | ConfigService |
| `ingestion/` | **Canonical** | Pipeline lifecycle (scan, discover, bridge) | Database, StorageClient |
| `validation/` | **Canonical** | Pipeline gates, vector integrity | — |
| `prompts/` | **Canonical** | Jinja2 templates (Netz IP) | — |
| `llm/` | **Canonical** | LLM call wrapper | OpenAI client |
| `profile_loader.py` | **Canonical** | Vertical profile resolution | ConfigService, vertical_registry |
| `vertical_registry.py` | **Canonical** | Vertical module resolver | — |
| `openai_client.py` | **Canonical** | OpenAI/Azure singleton | — |
| `model_config.py` | **Canonical** | Model name resolution | Settings |

### 4.4 Vertical Engines — Credit (`vertical_engines/credit/`)

12 modular packages (Wave 1 complete, PRs #9-#19):

| Package | Classification | Purpose | Import Rule |
|---------|---------------|---------|-------------|
| `critic/` | Canonical | IC memo analysis (confidence scoring, risk flags) | models → helpers → service |
| `deal_conversion/` | Canonical | Pipeline deal → portfolio deal | models → service |
| `deep_review/` | Canonical | 13-chapter IC memo generation | 5-tier DAG enforced |
| `domain_ai/` | Canonical | LLM classifications, entity extraction | models → service |
| `edgar/` | Canonical | SEC EDGAR integration (edgartools) | Thin wrapper |
| `kyc/` | Canonical | KYC pipeline screening | models → service |
| `market_data/` | Canonical | Market data enrichment (yfinance) | Thin wrapper |
| `memo/` | Canonical | Memo book generation | models → service |
| `pipeline/` | Canonical | Deal discovery + aggregation | models → service |
| `portfolio/` | Canonical | Portfolio intelligence | models → service |
| `quant/` | Canonical | Credit quant (spread, leverage, coverage) | models → service |
| `retrieval/` | Canonical | Retrieval governance, local cross-encoder reranking | — |
| `sponsor/` | Canonical | Sponsor/GP analysis | models → service |
| `underwriting/` | Canonical | Underwriting artifact generation | models → service |

### 4.5 Vertical Engines — Wealth (`vertical_engines/wealth/`)

| Package | Classification | Purpose |
|---------|---------------|---------|
| `dd_report/` | Canonical | 8-chapter DD report (critic + quant injection) |
| `critic/` | Canonical | Adversarial fund critic |
| `fact_sheet/` | Canonical | Fact sheet generation (PDF, multi-language) |
| `asset_universe/` | Canonical | Fund approval workflow |
| `model_portfolio/` | Canonical | Portfolio construction (MVO, CPT) |
| `screener/` | Canonical | 3-layer fund screener |
| `peer_group/` | Canonical | Peer group analytics |
| `rebalancing/` | Canonical | Rebalancing engine |
| `watchlist/` | Canonical | Watchlist + transition detection |
| `mandate_fit/` | Canonical | Portfolio-fund mandate fit |
| `fee_drag/` | Canonical | Fee drag impact analysis |
| `attribution/` | Canonical | Brinson attribution |
| `correlation/` | Canonical | Correlation matrix + regime weighting |
| `monitoring/` | Canonical | Strategy drift detection |
| `fund_analyzer.py` | Canonical | BaseAnalyzer impl for liquid_funds |
| `quant_analyzer.py` | Canonical | Portfolio-level quant dispatcher |
| `macro_committee_engine.py` | Canonical | Quarterly macro narrative |
| `investment_outlook.py` | Canonical | Investment outlook report |
| `flash_report.py` | Canonical | Event-driven market flash |
| `manager_spotlight.py` | Canonical | Fund manager deep-dive |
| `content_pdf.py` | Canonical | PDF rendering helper |

### 4.6 Quant Engine (`quant_engine/`)

| Service | Classification | Vertical Constraint |
|---------|---------------|---------------------|
| `regime_service.py` | Canonical | Must NOT import `app.domains.wealth` |
| `cvar_service.py` | Canonical | Must NOT import `app.domains.wealth` |
| `correlation_regime_service.py` | Canonical | Must NOT import `app.domains.wealth` |
| `fred_service.py` | Canonical | Global reference data |
| `regional_macro_service.py` | Canonical | Global reference data |
| `drift_service.py` | Canonical | Wealth-specific (acceptable) |
| `optimizer_service.py` | Canonical | Wealth-specific |
| `attribution_service.py` | Canonical | Wealth-specific |
| `backtest_service.py` | Canonical | Wealth-specific |
| `scoring_service.py` | Canonical | — |
| `rebalance_service.py` | Canonical | Wealth-specific |
| `stress_severity_service.py` | Canonical | Wealth-specific |
| `peer_comparison_service.py` | Canonical | Wealth-specific |
| `portfolio_metrics_service.py` | Canonical | Wealth-specific |
| `talib_momentum_service.py` | Utility | Thin TA-Lib wrapper |
| `lipper_service.py` | Utility | Thin data wrapper |
| `macro_snapshot_builder.py` | Utility | Helper |

### 4.7 Services (`app/services/`)

| Module | Classification | Purpose |
|--------|---------------|---------|
| `storage_client.py` | **Canonical** | ADLS/LocalFS abstraction |
| `azure/search_client.py` | **Canonical** | Azure Search client factory |

### 4.8 Seed Data

| Directory | Classification | Runtime Access |
|-----------|---------------|---------------|
| `profiles/` | Seed data only | Via ConfigService (DB default) |
| `calibration/` | Seed data only | Via ConfigService (DB default) |

**Never read YAML at runtime.** ConfigService checks DB first; YAML fallback logs ERROR.

---

## 5. Legacy / Transitional Map

### 5.1 Intentionally Removed (DO NOT RE-ADD)

These operational modules were removed by design. Stale references should be deleted:

- `cash_management/` — accounts, transactions, reconciliation
- `compliance/` — KYC, obligation engine
- `signatures/` — Adobe Sign, queue
- `counterparties/` — CRUD, bank accounts
- `adobe_sign/` — signature workflows

**Rationale:** Analytical engine scope only. Operational modules developed as separate add-ons.

### 5.2 Transitional Modules

| Module | Status | Reason | Migration Path |
|--------|--------|--------|---------------|
| `app/domains/credit/modules/ai/` | Transitional | Dynamic AI subrouter assembly (copilot context negotiation) | Awaiting copilot feature maturity |
| `app/domains/credit/modules/deals/` | Transitional | Legacy deal routes | Prefer `app/domains/credit/deals/` |
| `app/domains/credit/modules/documents/` | Transitional | Legacy document routes | Prefer `app/domains/credit/documents/` |

### 5.3 Modules with Unclear Ownership

None identified. All packages have clear ownership within vertical boundaries.

---

## 6. State, Config, and Runtime Policy Map

### 6.1 Configuration Resolution (Merge-on-Top)

ConfigService uses a **merge-on-top** pattern, not a priority waterfall. The DB override is not an alternative to the default -- it is deep-merged on top of it.

```
Request → Route handler
           ↓
    ConfigService.get(vertical, config_type, org_id)
           ↓
    1. TTLCache (60s, maxsize=2048) ────── hit → return cached result
           ↓ miss
    2. Resolve BASE config:
       ├─ VerticalConfigDefault (DB, no RLS) ── found → use as base
       └─ YAML fallback (_YAML_FALLBACK_MAP) ── found → use as base (ERROR logged)
           ↓ neither found → ConfigMissError (required) or MISSING_OPTIONAL
    3. If org_id provided:
       ├─ VerticalConfigOverride (DB, RLS-scoped) ── found → deep_merge(base, override)
       └─ No override → use base as-is
           ↓
    4. Cache merged result → return
```

**deep_merge semantics:** Recursive dict merge. Override scalars win. Dicts recurse. Lists replace (not append). `_DELETE` sentinel removes keys (admin-only). Max depth 20.

**Invalidation:** Admin writes → `pg_notify config_changed` → `PgNotifier` → `ConfigService.invalidate()` → cache eviction. On PgNotifier reconnect: full cache flush.

### 6.2 Registered Config Domains

14+ registered `(vertical, config_type)` pairs in `ConfigRegistry`:

**liquid_funds:** calibration, portfolio_profiles, scoring, blocks, chapters, macro_intelligence, screening_layer1, screening_layer2, screening_layer3

**private_credit:** chapters, calibration, scoring, governance_policy

**Client-visible types:** calibration, scoring, blocks, portfolio_profiles

**IP-protected types (never sent to clients):** chapters, macro_intelligence, governance_policy

### 6.3 Tenant-Specific Behavior

- **RLS policies** on all tenant-scoped tables via `organization_id = (SELECT current_setting('app.current_organization_id'))::uuid`
- **Config overrides** per `organization_id` in `VerticalConfigOverride`
- **ADLS paths** prefixed with `{org_id}/{vertical}/`
- **Azure Search** documents include `organization_id` field; all RAG queries filtered
- **Redis job ownership** tied to `org_id`
- **Prompt overrides** per `organization_id` in `prompt_overrides` table

### 6.4 Global (No Tenant) Data

| Table/Path | Purpose | RLS |
|-----------|---------|-----|
| `macro_data` | FRED indicators, regional snapshots | None (shared) |
| `allocation_blocks` | Investment universe blocks | None (shared) |
| `vertical_config_defaults` | Config seed data | None (shared) |
| `gold/_global/fred_indicators/` | Analytics (backtesting, correlation) | None |
| `gold/_global/etf_benchmarks/` | Benchmark universe | None |

### 6.5 Hardcoded Values Still Present

- `pool_size=20, max_overflow=10` in engine.py
- `TTLCache(maxsize=2048, ttl=60)` in config_service.py
- `max_connections=100` in Redis pool
- `grace_ttl=120` for job ownership
- `job_ttl=3600` default
- `state_ttl=86400` for job state persistence

---

## 7. Auditability / Operator Visibility Map

### 7.1 Audit Trail Mechanisms

| Mechanism | File | Coverage | Status |
|-----------|------|----------|--------|
| `write_audit_event()` | `app/core/db/audit.py` | Entity mutations (deals, documents, config) | Implemented |
| Structured logging | `app/core/middleware/` | Request-scoped (actor, action, fund, duration) | Active |
| Admin action log | `app/domains/admin/routes/` | Config writes, tenant CRUD, prompt uploads | Active |
| RLS audit | `app/core/db/rls_audit.py` | RLS policy compliance diagnostics | Diagnostic tool |
| AI router diagnostics | `app/domains/credit/modules/ai/__init__.py` | Subrouter load status, degradation, failure details | Exposed on `/health` |

### 7.2 Job Tracking

- **SSE real-time:** Redis pub/sub → `EventSourceResponse` with 15s heartbeat
- **Job state persistence:** Redis with 24h TTL for post-disconnect queries
- **Terminal states:** success, degraded, failed — with chunk counts and error summaries
- **Ownership lifecycle:** register → refresh → terminal → grace → expire

### 7.3 Structured Failure Handling

**Three-tier model:**

1. **Route-level** (422) — Pydantic validation, domain invariants
2. **Business logic** (4xx/5xx) — `ConfigMissError`, `NotAuthorized`, `NotFound`, `ValidationError`
3. **Pipeline partial failures** — gates can skip chunks; `terminal_state="degraded"` signals partial success

**Degradation types (FAIL-02):**
- `extraction` — some chunks failed OCR → continue with partial
- `ocr` — file unreadable → skip, mark degraded
- `embedding` — some chunks failed → requeue
- `search` — index upsert failed → warning (ADLS has data)

### 7.4 Where Partial Failures Are Surfaced vs Swallowed

| Failure | Surfaced? | Mechanism |
|---------|-----------|-----------|
| OCR failure | Yes | `terminal_state=degraded`, SSE event |
| Classification failure | Yes | Pipeline halts (gate), SSE error event |
| Embedding partial failure | Yes | `terminal_state=degraded`, chunk counts |
| ADLS write failure | Yes | Pipeline error, SSE error event |
| Azure Search failure | **Warning only** | Log warning, `terminal_state=degraded` (ADLS has data) |
| KYC screening failure | **Swallowed** | Returns `summary.skipped=True` (never-raises contract) |
| EDGAR failure | **Swallowed** | Returns status + warnings list (never-raises contract) |
| Config miss (optional) | **Swallowed** | Returns `MISSING_OPTIONAL`, logged |
| Config miss (required) | Yes | `ConfigMissError` (500), pipeline halts |

---

## 8. Structural Risks

> Architecture-level red flags observed during mapping. No remediation advice.

1. **Transitional AI module assembly** — `app/domains/credit/modules/ai/__init__.py` uses dynamic `_assemble()` with try/except that can silently degrade subrouter availability. Assembly happens at module import time (not startup). Failure diagnostics only visible via `/health` endpoint.

2. **Dual route paths for credit deals and documents** — Both `app/domains/credit/deals/` and `app/domains/credit/modules/deals/` exist. Both `app/domains/credit/documents/` and `app/domains/credit/modules/documents/` exist. Unclear which is canonical from routing alone; main.py mounts both.

3. **In-memory job tracking limit** — `unified_pipeline.py` maintains `_EXTRACTION_JOBS` dict with 50-job FIFO limit. No persistence beyond Redis. Process restart loses in-flight job state.

4. **Sync session in vertical engines** — `BaseAnalyzer` methods use sync `Session` (CPU-bound justification). Callers must bridge async→sync via `asyncio.to_thread()`. Thread safety depends on extracting ORM attributes before crossing boundaries.

5. **Redis as sole job state store** — Job ownership and state exist only in Redis with TTL. No database backup for job tracking. Redis restart loses all active job state.

6. **YAML fallback as error path** — ConfigService falls back to YAML when DB lookups fail. This is logged as ERROR but continues serving. A DB outage would silently switch to potentially stale YAML configs.

7. **No explicit rate limiting on API endpoints** — Rate limiting exists for external APIs (FRED, EDGAR) but not for client-facing FastAPI routes.

8. **PgNotifier single-connection dependency** — Uses a dedicated asyncpg connection outside the pool. If this connection drops and reconnect fails, config cache serves stale data until TTL expiry (60s).

9. **Hardcoded pool sizes and TTLs** — Database pool (20+10), Redis (100), cache TTL (60s), job TTL (3600s) are hardcoded rather than configurable. May need tuning per deployment.

10. **AuditEvent model partial** — `write_audit_event()` exists but the full AuditEvent database model and query surface are noted as pending in `db/audit.py`.

---

## 9. Import Architecture (Enforced by import-linter)

Contracts in `pyproject.toml`, verified by `make check`:

1. **Vertical independence:** `vertical_engines.credit` ⊥ `vertical_engines.wealth`
2. **Models are leaf nodes:** `*.models` → `*.service` forbidden (prevents circular deps)
3. **Helpers are acyclic:** Within each credit package, helpers must not import from `service.py`
4. **Deep review 5-tier DAG:** models → domain → helpers → portfolio → persist → service
5. **Quant vertical-agnostic:** `regime_service`, `cvar_service`, `correlation_regime_service` must NOT import `app.domains.wealth`

---

## 10. Test Coverage

- **324+ tests** passing across 67+ test files
- **Enforced by** `make check` (ruff + mypy + import-linter + pytest)
- **Coverage areas:** config service, pipeline stages, classification layers, RLS enforcement, storage routing, job tracking, vertical engine outputs

---

*Report generated: 2026-03-18*
*Profile: netz-backend*
*Scope: Full backend — runtime anchors, canonical flows, package classification, config/tenant/audit boundaries, structural risks*
