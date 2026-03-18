# Backend System Map v1

> Generated 2026-03-17. Mapping only — no audit, no recommendations.

---

## 1. Architecture Overview

### 1.1 Main Runtime Boundaries

| Boundary | Technology | Role |
|----------|-----------|------|
| **HTTP API** | FastAPI + Uvicorn | Async request handling, dual-mount (`/` + `/api` for Azure SWA proxy) |
| **Database** | PostgreSQL 16 + TimescaleDB | RLS-enforced tenant isolation, async via asyncpg |
| **Cache / Pub-Sub** | Redis 7 | Job event pub/sub (SSE bridging), config invalidation |
| **Data Lake** | ADLS Gen2 / LocalStorageClient | Bronze/silver/gold document hierarchy |
| **Search Index** | Azure AI Search | Vector + keyword index, derived from silver Parquet |
| **LLM** | OpenAI (direct) / Azure OpenAI (fallback) | Responses API, multi-model routing |
| **OCR** | Mistral (mistral-ocr-latest) | PDF → markdown, token-bucket rate limited |

### 1.2 AI Engine Responsibilities (`ai_engine/`)

Domain-agnostic universal core. Never modified per vertical.

- **Unified Pipeline** — single ingestion path: pre-filter → OCR → classify → governance → chunk → extract → embed → store → index
- **Hybrid Classification** — three-layer (rules → TF-IDF cosine → LLM fallback), zero external ML APIs
- **Extraction** — OCR (Mistral), semantic chunking, entity bootstrap, metadata extraction, summarization
- **Governance** — 15-pattern regex detector, prompt safety, output safety, token budgets
- **Validation** — pipeline gates, vector integrity guard, eval framework, deep review validation
- **Prompts** — Jinja2 SandboxedEnvironment registry with multi-path resolution (base + vertical overlays)
- **PDF Generation** — memo, deep review, DD report, fact sheet, periodic review PDFs
- **Profile Loader** — connects ConfigService → vertical engines via `AnalysisProfile` resolution
- **LLM Client** — OpenAI Responses API with retry, model routing, embedding service

### 1.3 Pipeline Responsibilities (`ai_engine/pipeline/`)

Single canonical ingestion path for all document sources (UI upload, batch, API).

- **Orchestrator**: `unified_pipeline.process(request, db, actor_id)`
- **Data Contracts**: `IngestRequest` (frozen), `PipelineStageResult` (frozen), `HybridClassificationResult`
- **Validation Gates**: 5 gates between stages (OCR, classification, chunks, embeddings, storage)
- **Storage Routing**: deterministic path builders (`bronze_document_path()`, `silver_chunks_path()`, etc.)
- **Dual-Write**: ADLS (source of truth) before Azure Search (derived index)
- **Search Rebuild**: reconstruct index from silver Parquet without OCR/LLM

### 1.4 Worker / Job Orchestration

No separate worker process. Workers are **background tasks** within the FastAPI process:

| Pattern | Mechanism | Example |
|---------|-----------|---------|
| Route-triggered background task | `BackgroundTasks.add_task()` | Deep review V4, macro ingestion, screening batch |
| SSE progress streaming | Redis pub/sub → `sse-starlette` EventSourceResponse | Real-time pipeline/memo progress |
| Job ownership | `register_job_owner(job_id, org_id)` in Redis (TTL 1h) | Tenant-scoped SSE authorization |
| Heartbeat | 15s ping (Azure idle timeout = 30s) | Keeps SSE alive |

**Job Lifecycle**: `register_job_owner()` → worker publishes events via `publish_event(job_id, event_type, data)` → SSE endpoint streams via `subscribe_job(job_id)` → terminal events: `done`, `error`, `ingestion_complete`, `memo_complete`

### 1.5 Config / Governance Boundaries

**ConfigService** is the single source of truth for all runtime configuration:

```
Resolution cascade:
  In-process TTLCache (60s) → DB override (per-org, RLS) → DB default (global) → YAML fallback (seed data)
```

- **DB tables**: `vertical_config_defaults` (global, no RLS) + `vertical_config_overrides` (tenant-scoped)
- **Cache invalidation**: PostgreSQL NOTIFY → PgNotifier → `ConfigService.invalidate()`
- **IP protection**: `CLIENT_VISIBLE_TYPES` allowlist; prompts/chapters are admin-only
- **Guardrails**: admin API validates overrides against guardrails schema

### 1.6 Storage / Indexing Boundaries

**StorageClient abstraction** — `LocalStorageClient` (dev, `.data/lake/`) or `ADLSStorageClient` (prod):

```
bronze/{org_id}/{vertical}/documents/{doc_id}.json          — raw OCR output
silver/{org_id}/{vertical}/chunks/{doc_id}/chunks.parquet    — embedded chunks (with embedding_model + embedding_dim)
silver/{org_id}/{vertical}/documents/{doc_id}/metadata.json  — classification + governance + extraction
gold/{org_id}/{vertical}/memos/{memo_id}.json               — IC memos
gold/{org_id}/{vertical}/fact_sheets/...                     — fact sheets
gold/{org_id}/{vertical}/dd_reports/...                      — DD reports
gold/_global/{dataset}/{filename}                            — FRED, ETF benchmarks (no tenant)
```

**Azure AI Search**: `global-vector-chunks-v2` (env-prefixed), all documents include `organization_id`, all RAG queries filtered by `$filter=organization_id eq '{org_id}'`.

---

## 2. Canonical Backend Flows

### 2.1 Document Ingestion (Unified Pipeline)

```
Entry point:    ai_engine/pipeline/unified_pipeline.process(IngestRequest, db, actor_id)
Triggered by:   POST /api/v1/credit/modules/ai/documents/ingest (route)
                ai_engine/ingestion/pipeline_ingest_runner.run_ingest() (batch)
```

| # | Stage | Module | Persistence | Event |
|---|-------|--------|-------------|-------|
| 1 | Pre-filter | `extraction/skip_filter.py` | — | — |
| 2 | OCR | `extraction/mistral_ocr.py` | bronze/{org}/{vertical}/documents/{doc_id}.json | `ocr_complete` |
| 3 | Gate: OCR quality | `pipeline/validation.py` | — | halt on fail |
| 4 | Classification | `classification/hybrid_classifier.py` | — | `classification_complete` |
| 5 | Gate: Classification | `pipeline/validation.py` | — | halt on fail |
| 6 | Governance detection | `extraction/governance_detector.py` | — | — |
| 7 | Semantic chunking | `extraction/semantic_chunker.py` | — | `chunking_complete` |
| 8 | Gate: Chunk quality | `pipeline/validation.py` | — | halt on fail |
| 9 | Extraction + Summarization | `extraction/document_intelligence.py` | — | `extraction_complete` |
| 10 | Embedding | `extraction/embedding_service.py` | — | — |
| 11 | Gate: Embedding quality | `pipeline/validation.py` | — | halt on fail |
| 12 | ADLS write (dual-write) | `pipeline/storage_routing.py` + StorageClient | silver chunks Parquet + metadata JSON | `storage_complete` |
| 13 | Search upsert | `extraction/search_upsert_service.py` | Azure AI Search index | `indexing_complete` |

**Tenant boundary**: `IngestRequest.organization_id` from JWT → embedded in ADLS paths + search documents + Parquet columns.

**Return**: `PipelineStageResult(success, data, metrics, warnings, errors)` — frozen dataclass.

### 2.2 Classification (Hybrid Three-Layer)

```
Entry point:    ai_engine/classification/hybrid_classifier.classify(text, filename)
Called by:       unified_pipeline stage 4
```

| Layer | Coverage | Method | Module |
|-------|----------|--------|--------|
| 1 — Rules | ~60% | Filename patterns + first-500-chars keywords | `hybrid_classifier.py` |
| 2 — TF-IDF | ~30% | Cosine similarity against synthetic exemplars (50+ pages of DOC_TYPE_DESCRIPTIONS) | `hybrid_classifier.py` |
| 3 — LLM | ~10% | gpt-4.1-mini via `document_intelligence.py` | `extraction/document_intelligence.py` |

**Output**: `HybridClassificationResult(doc_type, vehicle_type, confidence, layer)` — 30+ canonical doc types, 6 vehicle types.

### 2.3 Governance Detection

```
Entry point:    ai_engine/extraction/governance_detector.detect_governance(text)
Called by:       unified_pipeline stage 6
```

15 regex patterns. 7 are critical (trigger `governance_critical` flag): side_letter, most_favored_nation, key_person_clause, clawback, carried_interest, gating_provision, fund_of_funds_structure.

**Output**: `GovernanceResult(governance_critical: bool, governance_flags: list[str])`

### 2.4 Deep Review (Credit IC Memo — 13-Chapter Pipeline)

```
Entry point:    vertical_engines/credit/deep_review/service.run_deal_deep_review_v4(db, fund_id, deal_id, org_id)
Triggered by:   POST /api/v1/credit/modules/ai/pipeline/deals/{deal_id}/deep-review-v4
                ai_engine/ingestion/pipeline_ingest_runner (batch)
```

| # | Stage | Module |
|---|-------|--------|
| 1 | Validation | `deep_review/service.py` |
| 2 | RAG extraction | `deep_review/corpus.py` → `retrieval/service.py` |
| 3 | Structured analysis | `deep_review/decision.py` |
| 4 | Macro injection | `market_data/service.py` |
| 5 | Quant injection | `quant/service.py` |
| 6 | Concentration analysis | `ai_engine/portfolio/concentration_engine.py` |
| 7 | Hard policy checks | `deep_review/policy.py` |
| 8 | Policy compliance | `deep_review/policy.py` |
| 9 | Sponsor/key person | `sponsor/service.py` |
| 10 | Evidence pack assembly | `memo/evidence.py` |
| 11 | IC critic loop | `critic/service.py` |
| 12 | 13-chapter generation (gpt-5.1) | `memo/chapters.py` via `ai_engine/prompts/registry.py` |
| 13 | Atomic persist | `deep_review/persist.py` → DB + ADLS gold + search index |

**Persistence**: IC memo → PostgreSQL `ic_memos` table + ADLS `gold/{org}/{vertical}/memos/{memo_id}.json` + chapter citations indexed in Azure Search.

**SSE events**: `processing`, `corpus_ready`, `analysis_complete`, `chapters_generating`, `chapter_N_complete`, `memo_complete`.

### 2.5 Pipeline Ingest (Batch Orchestration)

```
Entry point:    ai_engine/ingestion/pipeline_ingest_runner.run_ingest(db, fund_id, actor_id)
                ai_engine/__init__.run_pipeline_ingest() delegates to vertical_engines/credit/pipeline/service.py
```

| # | Stage | Module |
|---|-------|--------|
| 1 | Scan blob containers | `ingestion/document_scanner.py` |
| 2 | Discover pipeline deals | `vertical_engines/credit/pipeline/discovery.py` |
| 3 | Bridge DocumentRegistry → DealDocument | `ingestion/registry_bridge.py` |
| 4 | Deep review all deals | `vertical_engines/credit/deep_review/service.py` |

**Audit**: `PipelineIngestJob` row records status + timing + structured error payloads.

### 2.6 Search Index Rebuild

```
Entry point:    ai_engine/pipeline/search_rebuild.rebuild_search_index(org_id, vertical, doc_ids, deal_id, fund_id)
```

Reads silver layer Parquet → validates embedding dimension match → upserts to Azure AI Search. No OCR/LLM calls. Use case: schema migration, embedding model upgrade, index corruption recovery.

### 2.7 Wealth DD Report Generation

```
Entry point:    vertical_engines/wealth/dd_report/dd_report_engine.generate_dd_report(fund, org_id, config)
Triggered by:   POST /api/v1/wealth/dd-reports/generate
```

| # | Stage |
|---|-------|
| 1 | Evidence pack assembly (fund docs + market data + peer benchmarks) |
| 2 | Parallel chapter generation: ch1-7 (executive_summary, strategy, manager, performance, risk, fees, operational) |
| 3 | Sequential chapter 8 (recommendation) — depends on ch1-7 |
| 4 | Quant injection (CVaR, Sharpe, drawdown via quant_engine) |
| 5 | Peer injection |
| 6 | Confidence scoring |
| 7 | PDF generation |
| 8 | ADLS gold write |

### 2.8 Macro Ingestion (Wealth Worker)

```
Entry point:    domains/wealth/workers/macro_ingestion.py
Triggered by:   POST /api/v1/wealth/analytics/macro/ingest
```

- Fetches 45 FRED series + regional benchmarks concurrently
- Computes derived series: YIELD_CURVE_10Y2Y, CPI_YOY, Sahm Rule
- Stores to `macro_data` table (global, no RLS)
- Stores to `macro_regional_snapshots` (tenant-scoped)
- Publishes SSE progress events

---

## 3. Package Boundary Map

### 3.1 App Core (`backend/app/core/`)

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `core/security/clerk_auth.py` | Clerk JWT v2 auth + RBAC | `Actor`, `get_actor()`, `require_role()`, `require_fund_access()` | **Canonical** |
| `core/db/engine.py` | Async engine + session factory | `engine`, `async_session_factory`, `get_db()` | **Canonical** |
| `core/db/base.py` | ORM mixins | `IdMixin`, `OrganizationScopedMixin`, `FundScopedMixin`, `AuditMetaMixin` | **Canonical** |
| `core/tenancy/middleware.py` | RLS context | `get_db_with_rls()` | **Canonical** |
| `core/tenancy/admin_middleware.py` | Cross-tenant access | `get_db_admin()`, `get_db_for_tenant()` | **Canonical** |
| `core/config/config_service.py` | Config resolution | `ConfigService.get()`, `.list_configs()`, `.invalidate()` | **Canonical** |
| `core/config/pg_notify.py` | Cache invalidation | `PgNotifier` (subscribes to `config_changed` channel) | **Canonical** |
| `core/config/models.py` | Config DB models | `VerticalConfigDefault`, `VerticalConfigOverride` | **Canonical** |
| `core/jobs/tracker.py` | Redis pub/sub job tracking | `register_job_owner()`, `publish_event()`, `subscribe_job()` | **Canonical** |
| `core/jobs/sse.py` | SSE streaming | `stream_job()` endpoint, EventSourceResponse | **Canonical** |

`get_actor()` resolves authentication in this order:

1. `X-DEV-ACTOR` header when `settings.is_development` is enabled
2. static development bearer token when `settings.is_development` is enabled
3. Clerk JWT bearer token

Production deployments must not rely on the development-only header or static development token paths.

### 3.2 App Domains

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `domains/credit/deals/` | Deal CRUD, qualification, staging | Routes, models, services | **Canonical** |
| `domains/credit/documents/` | Upload, ingestion, evidence | Routes (uploads, review, evidence, ingest) | **Canonical** |
| `domains/credit/portfolio/` | Holdings, obligations, alerts | Routes (assets, obligations, alerts, actions) | **Canonical** |
| `domains/credit/reporting/` | NAV, report packs, investor | Routes (report_packs, reports, schedules, investor_portal) | **Canonical** |
| `domains/credit/dashboard/` | Deal dashboard | Routes | **Canonical** |
| `domains/credit/dataroom/` | Folder governance | Routes | **Canonical** |
| `domains/credit/global_agent/` | Fund Copilot RAG | `agent.py`, `intent_router.py`, `pipeline_kb_adapter.py` | **Canonical** |
| `domains/credit/modules/ai/` | AI module router (lazy assembly) | Sub-routers: deep_review, memo_chapters, extraction, copilot, etc. | **Canonical** |
| `domains/wealth/` | Wealth routes, models, schemas, workers | 18+ route files, 12+ model files, 11+ worker files | **Canonical** |
| `domains/admin/` | Admin config CRUD, branding, tenants | Routes (configs, prompts, branding, assets, tenants, health) | **Canonical** |

### 3.3 App Services

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `services/storage_client.py` | ADLS abstraction | `StorageClient` ABC, `LocalStorageClient`, `ADLSStorageClient` | **Canonical** |
| `services/azure/blob_client.py` | Azure Blob wrapper | Blob operations | **Canonical** |
| `services/azure/search_client.py` | Azure AI Search wrapper | Vector + keyword search | **Canonical** |
| `services/azure/pipeline_dispatch.py` | Background task dispatch | `dispatch_deep_review()` | **Canonical** |
| `services/azure/keyvault_client.py` | Azure Key Vault | Secret retrieval | **Canonical** |
| `services/azure/graph_client.py` | Microsoft Graph | — | **Utility** |
| `services/azure/servicebus_client.py` | Azure Service Bus | Messaging | **Utility** |
| `services/azure/foundry_responses_client.py` | Foundry data adapter | — | **Utility** |
| `services/providers/yahoo_finance_provider.py` | Yahoo Finance data | Market data fetch | **Canonical** |
| `services/providers/csv_import_adapter.py` | CSV import | Bulk data import | **Utility** |
| `services/blob_storage.py` | — | — | **Legacy stub** |

### 3.4 AI Engine

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `ai_engine/pipeline/unified_pipeline.py` | Document processing orchestrator | `process(IngestRequest, db, actor_id)` | **Canonical** |
| `ai_engine/pipeline/models.py` | Pipeline data contracts | `IngestRequest`, `PipelineStageResult`, `HybridClassificationResult`, `CANONICAL_DOC_TYPES` | **Canonical** |
| `ai_engine/pipeline/validation.py` | Pipeline gates | `validate_ocr_output()`, `validate_classification()`, `validate_chunks()`, `validate_embeddings()` | **Canonical** |
| `ai_engine/pipeline/storage_routing.py` | ADLS path builders | `bronze_document_path()`, `silver_chunks_path()`, `gold_memo_path()`, etc. | **Canonical** |
| `ai_engine/pipeline/search_rebuild.py` | Index reconstruction | `rebuild_search_index()` | **Canonical** |
| `ai_engine/classification/hybrid_classifier.py` | 3-layer classifier | `classify(text, filename)` | **Canonical** |
| `ai_engine/extraction/mistral_ocr.py` | OCR | `async_extract_pdf_with_mistral()` | **Canonical** |
| `ai_engine/extraction/semantic_chunker.py` | Markdown-aware chunking | Structure-aware, adaptive sizes by doc_type | **Canonical** |
| `ai_engine/extraction/document_intelligence.py` | Metadata + summary | `async_extract_metadata()`, `async_summarize_document()` | **Canonical** |
| `ai_engine/extraction/embedding_service.py` | Embeddings | `generate_embeddings()`, `async_generate_embeddings()` | **Canonical** |
| `ai_engine/extraction/entity_bootstrap.py` | Entity extraction | 5-stage: OCR → embedding filter → regex → LLM fallback → validation | **Canonical** |
| `ai_engine/extraction/search_upsert_service.py` | Search indexing | `build_search_document()`, `upsert_chunks()` | **Canonical** |
| `ai_engine/extraction/governance_detector.py` | Governance patterns | `detect_governance()` | **Canonical** |
| `ai_engine/extraction/skip_filter.py` | Pre-filter | `should_skip_document()` | **Canonical** |
| `ai_engine/extraction/embed_chunks.py` | Chunk embedding prep | `build_embed_text()`, `embed_batch()` | **Canonical** |
| `ai_engine/extraction/kb_schema.py` | KB chunk schema | Knowledge base format | **Canonical** |
| `ai_engine/extraction/azure_kb_adapter.py` | KB adapter for Copilot RAG | — | **Canonical** |
| `ai_engine/extraction/text_extraction.py` | Non-PDF text extraction | — | **Utility** |
| `ai_engine/extraction/deals_enrichment.py` | — | — | **Legacy** (deprecated) |
| `ai_engine/extraction/fund_data_bootstrap.py` | — | — | **Legacy** (deprecated) |
| `ai_engine/extraction/fund_data_enrichment.py` | — | — | **Legacy** (deprecated) |
| `ai_engine/extraction/extraction_orchestrator.py` | — | — | **Legacy** (deprecated, superseded by unified_pipeline) |
| `ai_engine/extraction/obligation_extractor.py` | Covenant extraction | — | **Utility** |
| `ai_engine/governance/` | Governance suite | `policy_loader`, `prompt_safety`, `output_safety`, `token_budget`, `authority_resolver`, `artifact_cache` | **Canonical** |
| `ai_engine/validation/` | Validation suite | `vector_integrity_guard`, `eval_runner`, `eval_metrics`, `eval_judge`, `deep_review_validation_runner`, `evidence_quality` | **Canonical** |
| `ai_engine/ingestion/pipeline_ingest_runner.py` | Batch ingestion orchestrator | `run_ingest()` | **Canonical** |
| `ai_engine/ingestion/document_scanner.py` | Blob container scanner | `run_documents_ingest_pipeline()` | **Canonical** |
| `ai_engine/ingestion/registry_bridge.py` | DocumentRegistry → DealDocument | — | **Canonical** |
| `ai_engine/ingestion/monitoring.py` | Daily cycle | `run_daily_cycle()` | **Canonical** |
| `ai_engine/prompts/registry.py` | Jinja2 prompt management | `PromptRegistry`, `render()`, `render_pair()` | **Canonical** |
| `ai_engine/pdf/` | PDF generation suite | memo, deep review, DD report, fact sheet, periodic review PDFs | **Canonical** |
| `ai_engine/portfolio/concentration_engine.py` | HHI concentration | — | **Canonical** |
| `ai_engine/knowledge/` | Knowledge graph | `knowledge_builder`, `knowledge_anchor_extractor`, `linker` | **Canonical** |
| `ai_engine/openai_client.py` | LLM client | `create_completion()`, `async_create_completion()`, `create_embedding()` | **Canonical** |
| `ai_engine/model_config.py` | Model routing | Chapter → gpt-5.1, structured → gpt-4.1, lightweight → gpt-4.1-mini, reasoning → o4-mini | **Canonical** |
| `ai_engine/profile_loader.py` | Config → vertical bridge | `ProfileLoader.load()` | **Canonical** |
| `ai_engine/llm/call_openai.py` | Direct OpenAI calls | — | **Legacy** (mostly deprecated) |

### 3.5 Vertical Engines

| Package | Purpose | Public Surface | Status |
|---------|---------|---------------|--------|
| `vertical_engines/base/base_analyzer.py` | ABC interface | `BaseAnalyzer.analyze()` | **Canonical** |
| `vertical_engines/credit/critic/` | IC critic engine | `run_ic_critic()` | **Canonical** |
| `vertical_engines/credit/deal_conversion/` | Deal → Asset conversion | `service.py` | **Canonical** |
| `vertical_engines/credit/deep_review/` | 13-chapter IC memo pipeline | `run_deal_deep_review_v4()` | **Canonical** |
| `vertical_engines/credit/domain_ai/` | Domain AI workflows | `service.py` | **Canonical** |
| `vertical_engines/credit/edgar/` | SEC EDGAR integration | CIK resolver, financials, going concern, insider signals | **Canonical** |
| `vertical_engines/credit/kyc/` | KYC screening | Screening, entity extraction, persistence | **Canonical** |
| `vertical_engines/credit/market_data/` | Market data engine | FRED, regional, stress, snapshot | **Canonical** |
| `vertical_engines/credit/memo/` | IC memo book generator | `run_deal_memo_book()`, chapters, evidence, tone | **Canonical** |
| `vertical_engines/credit/pipeline/` | Pipeline discovery + intelligence | `run_pipeline_ingest()`, discovery, monitoring | **Canonical** |
| `vertical_engines/credit/portfolio/` | Portfolio intelligence | `run_portfolio_ingest()`, covenants, drift, risk | **Canonical** |
| `vertical_engines/credit/quant/` | IC quant engine | Scenarios, sensitivity, backtest | **Canonical** |
| `vertical_engines/credit/retrieval/` | Retrieval governance (RAG) | Corpus, evidence, saturation, query_map | **Canonical** |
| `vertical_engines/credit/sponsor/` | Sponsor profiling | Person extraction | **Canonical** |
| `vertical_engines/credit/underwriting/` | Underwriting artifacts | Derivation, persistence | **Canonical** |
| `vertical_engines/wealth/fund_analyzer.py` | BaseAnalyzer impl | `FundAnalyzer` | **Canonical** |
| `vertical_engines/wealth/dd_report/` | DD report engine (8 chapters) | `generate_dd_report()` | **Canonical** |
| `vertical_engines/wealth/fact_sheet/` | Fact sheet generator | Multi-language, institutional + executive | **Canonical** |
| `vertical_engines/wealth/macro_committee_engine.py` | Macro committee narrative | — | **Canonical** |
| `vertical_engines/wealth/investment_outlook.py` | Quarterly outlook | — | **Canonical** |
| `vertical_engines/wealth/flash_report.py` | Event-driven flash reports | — | **Canonical** |
| `vertical_engines/wealth/manager_spotlight.py` | Manager deep-dive | — | **Canonical** |
| `vertical_engines/wealth/monitoring/` | Alert + drift detection | `alert_engine`, `drift_monitor`, `strategy_drift_scanner` | **Canonical** |
| `vertical_engines/wealth/screener/` | 6-engine screener suite | `service`, `layer_evaluator`, `quant_metrics` | **Canonical** |
| `vertical_engines/wealth/watchlist/` | Dynamic watchlist | `service`, `transition_detector` | **Canonical** |
| `vertical_engines/wealth/asset_universe/` | Approved fund universe | `universe_service`, `fund_approval` | **Canonical** |
| `vertical_engines/wealth/model_portfolio/` | Model portfolio construction | `portfolio_builder`, `track_record`, `stress_scenarios` | **Canonical** |
| `vertical_engines/wealth/quant_analyzer.py` | quant_engine bridge | Orchestrates quant services for wealth | **Canonical** |
| `vertical_engines/wealth/rebalancing/` | Rebalancing analysis | `service`, `weight_proposer`, `impact_analyzer` | **Canonical** |
| `vertical_engines/wealth/correlation/` | Cross-fund correlation | `service` | **Canonical** |
| `vertical_engines/wealth/attribution/` | Performance attribution | `service` | **Canonical** |
| `vertical_engines/wealth/mandate_fit/` | Mandate compliance | `service`, `constraint_evaluator` | **Canonical** |
| `vertical_engines/wealth/peer_group/` | Peer group construction | `service`, `peer_matcher` | **Canonical** |
| `vertical_engines/wealth/fee_drag/` | Fee impact analysis | `service` | **Canonical** |
| `vertical_engines/wealth/critic/` | Wealth critic (adversarial review) | `service`, `parser`, `classifier` | **Canonical** |

### 3.6 Quant Engine (`quant_engine/`)

All pure sync functions, config injected as parameter, no `@lru_cache`.

| Module | Purpose | Status |
|--------|---------|--------|
| `regime_service.py` | Market regime detection (RISK_ON/OFF/INFLATION/CRISIS) | **Canonical** |
| `cvar_service.py` | CVaR + VaR + breach status | **Canonical** |
| `fred_service.py` | FRED macro data fetch + cache | **Canonical** |
| `correlation_regime_service.py` | Correlation + regime analysis | **Canonical** |
| `attribution_service.py` | Brinson/Fachler attribution | **Canonical** |
| `peer_comparison_service.py` | Peer group statistics | **Canonical** |
| `portfolio_metrics_service.py` | Portfolio-level aggregate metrics | **Canonical** |
| `drift_service.py` | Strategy drift detection | **Canonical** |
| `optimizer_service.py` | Mean-variance optimizer | **Canonical** |
| `scoring_service.py` | Composite scoring/ranking | **Canonical** |
| `stress_severity_service.py` | Stress scenario impacts | **Canonical** |
| `rebalance_service.py` | Rebalancing trades | **Canonical** |
| `backtest_service.py` | Historical backtesting | **Canonical** |
| `lipper_service.py` | Lipper fund benchmarks | **Canonical** |
| `talib_momentum_service.py` | RSI, MACD, Bollinger (TA-Lib) | **Canonical** |
| `regional_macro_service.py` | Geographic allocation signals | **Canonical** |
| `macro_snapshot_builder.py` | Macro snapshot construction | **Canonical** |

---

## 4. Legacy / Transitional Map

### 4.1 Modules Superseded by Unified Pipeline

| Module | Superseded By | Reason Still Present |
|--------|--------------|---------------------|
| `ai_engine/extraction/extraction_orchestrator.py` | `ai_engine/pipeline/unified_pipeline.py` | Legacy batch orchestration; may still be referenced by older batch paths |
| `ai_engine/extraction/deals_enrichment.py` | Unified pipeline + `vertical_engines/credit/market_data/` | Legacy batch enrichment |
| `ai_engine/extraction/fund_data_bootstrap.py` | `ai_engine/extraction/entity_bootstrap.py` | Legacy entity extraction |
| `ai_engine/extraction/fund_data_enrichment.py` | Unified pipeline extraction stages | Legacy enrichment |
| `ai_engine/extraction/market_data_bootstrap.py` | `vertical_engines/credit/market_data/service.py` | Legacy market data |
| `ai_engine/llm/call_openai.py` | `ai_engine/openai_client.py` | Legacy direct LLM calls; some modules may still import |

### 4.2 Modules Remaining for Batch / Migration Reasons

| Module | Purpose | Note |
|--------|---------|------|
| `ai_engine/ingestion/pipeline_ingest_runner.py` | Batch orchestration (scan → discover → bridge → deep review) | Active, wraps unified pipeline for batch use |
| `ai_engine/ingestion/document_scanner.py` | Blob container scanning | Active, feeds pipeline_ingest_runner |
| `ai_engine/ingestion/registry_bridge.py` | DocumentRegistry → DealDocument linking | Active, bridges storage registry to domain model |
| `domains/wealth/workers/fred_ingestion.py` | FRED ingestion | **Deprecated** — use `macro_ingestion.py` |

### 4.3 Modules with Unclear Ownership

| Module | Observation |
|--------|------------|
| `services/blob_storage.py` | Stub marked "Sprint 2b" — unclear if StorageClient fully replaced it |
| `services/azure/foundry_responses_client.py` | Foundry adapter — unclear usage context |
| `services/azure/servicebus_client.py` | Service Bus client — no clear caller in current codebase |

### 4.4 Architecturally Suspect Areas

| Area | Concern |
|------|---------|
| `ai_engine/__init__.py` re-exports | Delegates `run_pipeline_ingest()` and `run_portfolio_ingest()` to vertical_engines.credit — ties the "universal" engine to a specific vertical at the package level |
| `domains/credit/modules/ai/__init__.py` lazy assembly | Try/except imports to handle ai_engine availability — fragile coupling pattern |

---

## 5. State, Config, and Runtime Policy Map

### 5.1 How Runtime Configuration Is Loaded

```
Request arrives
  → get_actor() extracts org_id from JWT
  → Route handler calls ConfigService.get(vertical, config_type, org_id)
  → ConfigService checks:
      1. In-process TTLCache (60s TTL)
      2. DB: vertical_config_overrides WHERE org_id = ? AND vertical = ? AND config_type = ?
      3. DB: vertical_config_defaults WHERE vertical = ? AND config_type = ?
      4. YAML fallback via _YAML_FALLBACK_MAP
  → Returns deep_merge(default, override)
```

### 5.2 ConfigService Source of Truth

| Config Type | Source | Notes |
|-------------|--------|-------|
| `chapters` | ConfigService → DB/YAML | IC memo chapter structure |
| `calibration` | ConfigService → DB/YAML | Quant thresholds, limits |
| `scoring` | ConfigService → DB/YAML | Scoring weights |
| `blocks` | ConfigService → DB/YAML | Allocation block definitions |
| `portfolio_profiles` | ConfigService → DB/YAML | Portfolio risk profiles |
| `governance_policy` | ConfigService → DB/migration seed | Governance policy rules |
| `prompts` | ConfigService (admin-only) | LLM prompts (IP protected) |

### 5.3 Where Defaults / YAML / Hardcoded Values Still Exist

| Location | Type | Description |
|----------|------|-------------|
| `profiles/*.yaml` | YAML seed | Analysis profile definitions — fallback only |
| `calibration/*.yaml` | YAML seed | Quant calibration — fallback only |
| `ai_engine/pipeline/validation.py` | Hardcoded | `MIN_OCR_CHARS=100`, `MAX_NON_PRINTABLE_RATIO=0.30`, `MAX_CONTENT_LOSS_RATIO=0.25` |
| `ai_engine/pipeline/models.py` | Hardcoded | `CANONICAL_DOC_TYPES` (30+), `CANONICAL_VEHICLE_TYPES` (6) |
| `ai_engine/validation/vector_integrity_guard.py` | Hardcoded | `EMBEDDING_MODEL_NAME`, `EMBEDDING_DIMENSIONS=3072` |
| `ai_engine/classification/hybrid_classifier.py` | Hardcoded | `MIN_SIMILARITY=0.05`, `MIN_RATIO=1.3` |
| `ai_engine/extraction/entity_bootstrap.py` | Hardcoded | Similarity threshold=0.72, MIN_REGEX_ENTITIES=3 |
| `ai_engine/model_config.py` | Hardcoded + env override | Model routing map (overridable via `NETZ_MODEL_{STAGE}`) |
| `quant_engine/cvar_service.py` | Config param | Per-profile CVaR limits (conservative=-8%, moderate=-6%, growth=-12%) |
| `quant_engine/regime_service.py` | Config param | VIX/yield/CPI thresholds |

### 5.4 Where Tenant-Specific Behavior Enters

| Entry Point | Mechanism |
|-------------|-----------|
| RLS on all tenant-scoped tables | `SET LOCAL app.current_organization_id` via `get_db_with_rls()` |
| Config overrides per org | `vertical_config_overrides` table (org_id scoped) |
| ADLS path isolation | `{org_id}/{vertical}/` prefix enforced by `storage_routing.py` |
| Search index filtering | `$filter=organization_id eq '{org_id}'` on all RAG queries |
| Fund access control | `Actor.fund_ids` from JWT + `require_fund_access()` dependency |
| Role-based visibility | `require_role()`, `require_readonly_allowed()`, `require_ic_member()` |
| Parquet columns | `organization_id` column in all silver Parquet files + DuckDB `WHERE organization_id = ?` |
| TimescaleDB compression | `compress_segmentby = 'organization_id'` on hypertables |

---

## 6. Auditability / Operator Visibility Map

### 6.1 Audit Trail Mechanisms

| Mechanism | Location | What It Tracks |
|-----------|----------|---------------|
| `AuditMetaMixin` | All tenant-scoped ORM models | `created_at`, `updated_at`, `created_by`, `updated_by` |
| `PipelineIngestJob` | `ai_engine/ingestion/` | Batch job status, timing, structured error payloads |
| `write_audit_event()` | Called after pipeline gates + major stages | Stage transitions, validation results |
| Config version tracking | `VerticalConfigDefault.version`, `VerticalConfigOverride.version` | Optimistic locking on config writes |
| Deal stage transitions | `deals/services/stage_transition.py` | `VALID_TRANSITIONS` enforcement, audit events |
| IC memo status | `ic_memos` model | `MemoStatus` enum tracking memo lifecycle |
| DealQualification records | `deals/models/qualification.py` | Qualification decisions with rejection codes |

### 6.2 Job Tracking

| Component | Purpose |
|-----------|---------|
| `core/jobs/tracker.py` | Redis-based job registration + event publishing |
| `register_job_owner(job_id, org_id, ttl=3600)` | Associates job with tenant (1h TTL) |
| `verify_job_owner(job_id, org_id)` | Tenant authorization before SSE streaming |
| `publish_event(job_id, event_type, data)` | Workers emit progress events to Redis channel |
| `subscribe_job(job_id)` | Async generator yields events from Redis pub/sub |

### 6.3 Structured Failure Handling

| Layer | Pattern |
|-------|---------|
| Pipeline gates | `PipelineStageResult(success=False, errors=[...])` — halt pipeline, return structured error |
| LLM client | Exponential backoff (max 5 attempts) with jitter for 429/5xx |
| OCR | Token-bucket rate limiter, 180s timeout, max 1000 pages / 250MB |
| Config invalidation | PgNotifier reconnects on connection loss |
| Storage dual-write | ADLS failure → warning (pipeline continues); Search failure → data safe in ADLS |

### 6.4 SSE / Streaming Progress

| Event | Emitted By | Terminal? |
|-------|-----------|-----------|
| `processing` | Pipeline start | No |
| `ocr_complete` | OCR stage | No |
| `classification_complete` | Classification stage | No |
| `chunking_complete` | Chunking stage | No |
| `extraction_complete` | Extraction stage | No |
| `storage_complete` | ADLS write | No |
| `indexing_complete` | Search upsert | No |
| `ingestion_complete` | Pipeline end | **Yes** |
| `corpus_ready` | Deep review | No |
| `analysis_complete` | Deep review | No |
| `chapters_generating` | Deep review | No |
| `chapter_N_complete` | Deep review | No |
| `memo_complete` | Deep review | **Yes** |
| `done` | Any worker | **Yes** |
| `error` | Any failure | **Yes** |
| heartbeat (15s ping) | SSE endpoint | No (keep-alive) |

### 6.5 Where Partial Failures Are Surfaced vs Swallowed

| Scenario | Behavior |
|----------|----------|
| ADLS write fails | **Warning** — pipeline continues (degraded mode) |
| Search upsert fails | **Warning** — data safe in ADLS, can rebuild later |
| Classification confidence < 0.3 | **Warning** — not a halt, just flagged |
| OCR fails gate | **Halt** — `PipelineStageResult(success=False)` |
| Chunk count = 0 | **Halt** — `PipelineStageResult(success=False)` |
| Embedding NaN detected | **Halt** — `PipelineStageResult(success=False)` |
| LLM extraction fails | **Retry** (5 attempts) then **error event** |
| Config PgNotify disconnection | **Silent reconnect** |
| Lazy module import failure | **Swallowed** (try/except in modules/ai/__init__.py) |

---

## 7. Structural Risks (Mapping Only)

| # | Risk | Location | Observation |
|---|------|----------|-------------|
| 1 | **Universal engine coupled to credit vertical** | `ai_engine/__init__.py` | Re-exports `run_pipeline_ingest()` and `run_portfolio_ingest()` delegating directly to `vertical_engines.credit`. The "universal" ai_engine has a hard dependency on credit at package level. |
| 2 | **No separate worker process** | `domains/wealth/workers/`, `app/services/azure/pipeline_dispatch.py` | All workers run as FastAPI background tasks in the same process. CPU-bound quant work (CVaR, optimization, backtesting) shares the async event loop thread pool. |
| 3 | **Lazy assembly with swallowed errors** | `domains/credit/modules/ai/__init__.py` | Try/except on module imports means missing or broken ai_engine dependencies fail silently — routes may 404 without clear error. |
| 4 | **Legacy extraction modules still present** | `ai_engine/extraction/` | 4 deprecated modules (`deals_enrichment`, `fund_data_bootstrap`, `fund_data_enrichment`, `extraction_orchestrator`) — potential confusion about canonical path. |
| 5 | **Hardcoded pipeline thresholds** | `ai_engine/pipeline/validation.py`, `hybrid_classifier.py`, `entity_bootstrap.py` | Validation gate thresholds are hardcoded constants, not in ConfigService. Cannot be tuned per-tenant or per-environment without code change. |
| 6 | **CANONICAL_DOC_TYPES / CANONICAL_VEHICLE_TYPES hardcoded** | `ai_engine/pipeline/models.py` | Document type taxonomy is hardcoded in Python. Adding new doc types requires a code change + deployment. |
| 7 | **Redis job TTL = 1h** | `core/jobs/tracker.py` | Job ownership expires after 1 hour. Long-running batch jobs (deep review of large portfolios) could lose SSE authorization mid-stream. |
| 8 | **Dual-write degraded mode** | `ai_engine/pipeline/unified_pipeline.py` | ADLS failure produces a warning but pipeline continues. If ADLS write fails, the bronze source of truth is lost, making search rebuild impossible for that document. |
| 9 | **Single embedding model assumption** | `ai_engine/validation/vector_integrity_guard.py` | `EMBEDDING_DIMENSIONS=3072` hardcoded. Search rebuild validates against this constant. Model upgrade requires coordinated code + data migration. |
| 10 | **Deprecated FRED worker not removed** | `domains/wealth/workers/fred_ingestion.py` | Marked deprecated in favor of `macro_ingestion.py` but still present — potential for accidental invocation. |
| 11 | **Stub service file** | `services/blob_storage.py` | Marked "Sprint 2b" — unclear relationship to StorageClient abstraction. |
| 12 | **Azure service clients with unclear usage** | `services/azure/servicebus_client.py`, `foundry_responses_client.py` | Present but no clear callers in current codebase. |
| 13 | **Global tables have no access control** | `macro_data`, `allocation_blocks`, `vertical_config_defaults` | No RLS, no org_id. Any authenticated user can read/write. Admin middleware (`get_db_admin()`) is the only protection. |

---

## Appendix A: Database Migrations

| Migration | Content |
|-----------|---------|
| `0001_foundation` | Base infrastructure, auth, org tables |
| `0002_wealth_domain` | Wealth models (Fund, Portfolio, NavTimeseries, etc.) |
| `0003_credit_domain` | Credit models (Deal, Document, IcMemo, etc.) |
| `0004_vertical_configs` | VerticalConfigDefault, VerticalConfigOverride + seed data |
| `0005_macro_regional_snapshots` | MacroRegionalSnapshot |
| `0006_macro_reviews` | Macro review tracking |
| `0007_governance_policy_seed` | Governance policy seed data |
| `0008_wealth_analytical_models` | Screening, Watchlist, etc. |
| `0009_admin_infrastructure` | Admin-specific tables |

Current head: `0009_admin_infrastructure`.

## Appendix B: Multi-Model Routing

| Use Case | Model | Notes |
|----------|-------|-------|
| IC memo chapters (ch01-14) | gpt-5.1 | IC-grade narrative |
| Critic | gpt-4.1 | Structured analysis |
| Critic escalation | o4-mini | Reasoning model (no temperature) |
| Concentration analysis | gpt-4.1-mini | Lightweight |
| XBRL extraction | gpt-4.1-mini | Lightweight |
| Document classification (L3) | gpt-4.1-mini | LLM fallback only |
| Metadata extraction | gpt-4.1 | Structured/JSON |
| Document summary | gpt-4.1-mini | Lightweight |
| Override | `NETZ_MODEL_{STAGE}` env var | Uppercase, hyphens → underscores |

## Appendix C: Import Architecture (import-linter)

Enforced contracts (in `pyproject.toml`):

1. `vertical_engines.credit` ↔ `vertical_engines.wealth` — **independent** (no cross-import)
2. `vertical_engines.credit.*.models` → `vertical_engines.credit.*.service` — **forbidden**
3. Within each credit package: helpers → `service.py` — **forbidden** (service imports helpers, not reverse)
4. `quant_engine.regime_service` / `quant_engine.cvar_service` → `app.domains.wealth` — **forbidden** (vertical-agnostic)

## Appendix D: Test Structure

```
backend/tests/
├── admin/              # Admin routes
├── ai_engine/          # AI engine units
│   └── prompts/        # Prompt template tests
├── conftest.py         # Pytest fixtures
└── test_*.py           # Route/service tests
```

324 tests, all passing. Enforced by `make check` (lint + typecheck + architecture + test).
