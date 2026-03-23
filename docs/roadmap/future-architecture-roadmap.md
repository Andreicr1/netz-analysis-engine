# Future Architecture Roadmap — Netz Analysis Engine

## Status

- **Type:** Strategic roadmap (non-binding)
- **Source:** Brainstorms + architectural direction from Andrei
- **Not validated against runtime**
- **Last updated:** 2026-03-18

---

## Purpose

Capture **future system directions** without contaminating:

- current system map (`docs/audit/`)
- correction plans (`docs/plans/backend-correction-plan-v1.md`)
- validated architecture

---

## Critical Separation (MANDATORY)

| Layer | Description | Location |
|-------|-------------|----------|
| Current System | What exists in code | `docs/audit/` system maps |
| Correction Plan | What is being fixed | `docs/plans/backend-correction-plan-v1.md` |
| Future Roadmap | What may exist later | **This document** |

Future components must:
- NEVER appear in system maps as "existing"
- ALWAYS be explicitly marked as **FUTURE**

---

# 1. Infrastructure Simplification — Milestone 2 (2026-03-18)

### Decision

Replaced Azure enterprise stack (~$1,500/month) with lean Milestone 2 stack (~$100-200/month).

### Stack

| Layer | Service | Why |
|-------|---------|-----|
| Database | Timescale Cloud (PostgreSQL 16 + pgvector + TimescaleDB) | Native TimescaleDB + pgvector, managed |
| Compute | Railway | Simple DX, persistent volumes, container-native |
| Cache | Upstash Redis | Serverless, free tier for Milestone 1 |
| Storage | LocalStorageClient (filesystem, persistent volume) | Data lake < 10GB |
| Future Storage | Cloudflare R2 | S3-compatible, zero egress, when > 100GB |

### What Was Eliminated

| Service | Replacement | Reason |
|---------|-------------|--------|
| Azure AI Search | pgvector (PostgreSQL) | RLS-native, hybrid queries, no OData filters |
| Azure OpenAI fallback | OpenAI direct + retry backoff | Single provider + retry sufficient |
| Azure Key Vault | Platform env vars (Railway secrets) | No rotation audit trail requirement yet |
| Azure Service Bus | Redis pub/sub + BackgroundTasks | No guaranteed delivery requirement yet |
| Application Insights | structlog → stdout | Railway log aggregation sufficient |
| ADLS Gen2 | LocalStorageClient (filesystem) | Data lake < 10GB |

### Scale Triggers (Milestone 3+, >50 tenants)

| Trigger | Service |
|---------|---------|
| SOC2 secret rotation audit | HashiCorp Vault or Key Vault |
| Data lake > 1TB or data residency | Cloudflare R2 or ADLS Gen2 |
| Financial transaction guaranteed delivery | Redis Streams |
| pgvector > 500K chunks, p99 > 200ms | Qdrant or Weaviate |

### Current State (2026-03-18)

- `StorageClient` abstraction complete: `LocalStorageClient` (dev + prod) + `ADLSStorageClient` (Milestone 3)
- `FEATURE_ADLS_ENABLED=false` by default — writes to `.data/lake/` (persistent volume in prod)
- `storage_routing.py` enforces `{tier}/{org_id}/{vertical}/` path hierarchy
- All pipeline writes routed through `StorageClient` (HC-2 fixed f-string paths)
- Silver Parquet includes `embedding_model` + `embedding_dim` columns for rebuild validation
- pgvector replaces Azure Search for all vector operations (commit 497df51)

### Remaining Work

- Migrate remaining direct Azure Blob SDK calls to `StorageClient`
- Bronze/silver/gold hierarchy not yet enforced on all write paths (some legacy flows)

### Key Principle

> **LocalStorage/ADLS = source of truth**
> **pgvector = derived index (rebuildable from silver Parquet)**
> **Everything else = stateless compute**

### References

- Pipeline Alignment Refactor: [`docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md`](../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md)
- Extraction/Ingestion Cleanup: [`docs/plans/2026-03-15-refactor-ai-engine-extraction-ingestion-cleanup-plan.md`](../plans/2026-03-15-refactor-ai-engine-extraction-ingestion-cleanup-plan.md)
- DuckDB Data Lake Inspection: [`docs/plans/2026-03-18-feat-duckdb-data-lake-inspection-layer-plan.md`](../plans/2026-03-18-feat-duckdb-data-lake-inspection-layer-plan.md)

---

# 2. Unified Analytical Stack

### Components

| Layer | Role |
|-------|------|
| LocalStorage/ADLS Gen2 | Persistent data (bronze/silver/gold) |
| pgvector | Vector search index (derived, rebuildable) |
| DuckDB | Query layer — analytics directly on Parquet |
| `quant_engine/` | Quantitative analytics (CVaR, regime, optimizer) |
| `ai_engine/` | Reasoning (classification, extraction, embedding) |

### Goal

Eliminate:
- Duplicated data paths (PostgreSQL vs ADLS vs in-memory)
- In-memory-only analytics that can't be reproduced
- Non-reproducible results (all inputs must be traceable to ADLS artifacts)

### Current State (2026-03-18)

- DuckDB is **NOT yet implemented** — zero imports, zero code, not in `pyproject.toml`
- Quant analytics currently use in-memory pandas/numpy/scipy
- ADLS Parquet files exist (silver layer) but no query layer reads them directly

### Future: DuckDB Query Layer

- DuckDB reads directly from silver/gold Parquet in ADLS
- Replaces ad-hoc pandas aggregations
- Enables cross-fund correlation, backtesting, time-series analytics
- Path: `gold/_global/` for cross-tenant aggregates, `gold/{org_id}/{vertical}/` for tenant-specific

### Trigger

Implement when: (a) cross-fund analytics are needed, (b) in-memory pandas cannot scale to tenant data volume, or (c) backtesting requires historical Parquet scans.

---

# 3. Wealth Vertical — Full Institutional Stack

### Current State

- `quant_engine/` exists (CVaR, regime, optimizer, scoring, drift, rebalance)
- `vertical_engines/wealth/` modularized (fund_analyzer, dd_report_engine, macro_committee_engine, quant_analyzer)
- Screener suite complete (6 engines, polymorphic instruments)
- Senior analyst engines in progress (attribution, drift, correlation, liquidity)

### Missing Layers (FUTURE)

- **DD Report Engine v2:** LLM + RAG + critic loop (current is template-based)
- **Asset Universe governance:** Approval workflows for instrument inclusion/exclusion
- **Fact-sheet generation:** Automated fund fact sheets from gold-layer data
- **Content production pipeline:** Investor letters, quarterly reports, commentary

### References

- Wealth Modularization: [`docs/plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md`](../plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md)
- Screener Suite: [`docs/plans/2026-03-16-feat-wealth-instrument-screener-suite-plan.md`](../plans/2026-03-16-feat-wealth-instrument-screener-suite-plan.md)
- Senior Analyst: [`docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md`](../plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md)

---

# 4. Instrument-Centric Architecture

### Shift

| From | To |
|------|----|
| Fund-only model | Polymorphic instrument model |
| `funds` table | `instruments_universe` (JSONB-based) |
| Single asset class | Multi-asset (equity, FI, alternatives, derivatives) |

### Core Component

- `instruments_universe` table with JSONB `attributes` column
- Type discriminator for asset-class-specific behavior
- Shared screening/filtering/comparison across all instrument types

### Impact

- Enables universal screening (not just funds)
- Enables multi-asset portfolios
- Simplifies portfolio construction (instruments are fungible)
- Unblocks watchlist, alerts, and cross-asset analytics

### Reference

- Screener Suite: [`docs/brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md`](../brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md)

---

# 5. Deterministic Pipeline + LLM Hybrid

### Direction

- LLM only where genuinely necessary (~10% of documents)
- Deterministic everywhere else (~90%)

### Architecture (Partially Complete)

| Layer | Method | Coverage | Status |
|-------|--------|----------|--------|
| 1 | Filename + keyword rules | ~60% | DONE |
| 2 | TF-IDF + cosine similarity | ~30% | DONE |
| 3 | LLM fallback | ~10% | DONE |
| Cross-encoder reranker | Local model (replaced Cohere) | IC evidence | DONE |
| Validation gates | Between each pipeline stage | All stages | DONE |

### Remaining (FUTURE)

- Confidence calibration (threshold tuning per document type)
- Feedback loop: user corrections feed back to rules layer
- A/B evaluation framework for classifier improvements

### Reference

- Pipeline Alignment: [`docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md`](../plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md)

---

# 6. Senior Analyst Layer (Diagnostics)

### Gap

| Current | Missing |
|---------|---------|
| Explains **WHAT** (metrics, scores) | Explains **WHY** (attribution, causality) |

### New Engines

| Engine | Purpose | Dependency |
|--------|---------|------------|
| Attribution | Performance decomposition by factor | Benchmark ingestion |
| Strategy Drift Detection | Detect style drift from stated mandate | Historical holdings |
| Correlation Regime Monitor | Cross-asset regime shifts | `quant_engine/regime_service` |
| Liquidity Stress Analysis | Redemption capacity under stress | NAV + flow data |

### Role

Support **IC-level decisions**, not just data processing. The system should help analysts understand causality, not just present numbers.

### Reference

- Senior Analyst Engines: [`docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md`](../plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md)

---

# 7. Macro Intelligence Layer

### Gap

- No top-down allocation logic
- No systematic macro regime integration into portfolio decisions

### Target

- FRED data ingestion (daily) into `macro_data` + ADLS gold layer
- Regime detection (expansion/contraction/crisis) via `regime_service`
- Committee-driven allocation proposals (not automatic execution)
- Macro overlay on fund-level analytics

### Governance

- **Committee-driven** (not automatic)
- System generates **proposals**, humans approve execution
- All proposals logged with rationale for audit trail

### Reference

- Macro Intelligence Suite: [`docs/plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md`](../plans/2026-03-15-feat-wealth-macro-intelligence-suite-plan.md)

---

# 8. Frontend Admin Control Plane

### Role

- System configuration (verticals, tenants, feature flags)
- Tenant management (onboarding, RLS verification)
- Prompt control (view/edit Jinja2 templates, IP protection)
- Pipeline monitoring (ingestion status, error rates)

### Key Principle

> **Admin = control plane**
> **Not product UI**

Admin frontend is for Netz operators, not end-users. Different design language, different auth (super-admin only).

### Reference

- Admin Frontend: [`docs/plans/2026-03-17-feat-admin-frontend-plan.md`](../plans/2026-03-17-feat-admin-frontend-plan.md)

---

# 9. Credit Vertical Structural Alignment

### Goal

- Unify architecture via modular packages (same pattern as wealth)
- Enforce EDGAR pattern (`edgartools` integration)
- 12 modular packages (Wave 1 complete)
- Deep review modularization (Wave 2)

### Current State

Wave 1 (12 packages) is DONE. Wave 2 (deep review) is planned.

### Future

- Wave 3: Cross-vertical patterns (shared scoring, shared retrieval governance)
- IC memo generation v2 (multi-chapter with evidence packs)

### References

- Credit Modular Alignment Wave 1: [`docs/plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md`](../plans/2026-03-15-refactor-credit-vertical-modular-alignment-wave1-plan.md)
- Credit Deep Review Wave 2: [`docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md`](../plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md)
- EDGAR Upgrade: [`docs/plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md`](../plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md)

---

# 10. Worker Infrastructure Evolution

### Current State (2026-03-18)

All 8 wealth workers run in-process via `BackgroundTasks`. Mitigations applied:

| Mitigation | Status |
|------------|--------|
| RLS context (`SET LOCAL`) on all tenant-scoped workers | DONE (HC-1) |
| `asyncio.wait_for()` timeouts — 600s heavy, 300s light | DONE (SR-1) |
| Redis idempotency guard — 409 on duplicates, TTL safety nets | DONE (M-6) |
| Structured logging — start/complete/timeout/fail with duration | DONE (SR-1) |

### Remaining Limitations

- **No process isolation:** A stuck worker blocks the ASGI event loop (timeout mitigates but doesn't isolate)
- **No DLQ/retry:** Failed workers require manual re-trigger (idempotency guard makes failure visible, not recoverable)
- **No backpressure:** No limit on concurrent workers per tenant

### Target Direction (FUTURE)

- Migrate to **ARQ** (async Redis queue) or **Celery** when worker volume justifies
- Process isolation via separate worker dyno/container
- Dead-letter queue for failed jobs with configurable retry policy
- Per-tenant concurrency limits

### Trigger

Move to external queue when: (a) workers routinely timeout, (b) >10 concurrent worker requests, or (c) worker failures need auto-retry.

---

# 11. Search Resilience

### Current State (2026-03-18)

pgvector (PostgreSQL) is the sole RAG query backend, replacing Azure Search (commit 497df51). Mitigations applied:

| Mitigation | Status |
|------------|--------|
| Graceful degradation — empty results + warning on connection errors | DONE (SR-6) |
| `search_degraded` flag in agent responses for frontend messaging | DONE (SR-6) |
| `search_rebuild.py` — manual index reconstruction from silver Parquet | EXISTS |
| pgvector health check in `/admin/health/services` | DONE (Milestone 2) |

### Remaining Limitations

- **No automatic failover:** If PostgreSQL is down, RAG returns empty results (not errors, but no data)
- **No read replica:** Single PostgreSQL instance (Timescale Cloud)
- **Manual rebuild only:** `search_rebuild.py` requires operator intervention

### Target Direction (FUTURE)

- Read replica (Timescale Cloud supports replicas) for failover
- Automated health check + rebuild trigger on sustained failures
- Dedicated vector database (Qdrant, Weaviate) if pgvector HNSW becomes bottleneck (>10M chunks)

### Trigger

Move to redundant search when: (a) SLA requires >99.9% RAG availability, or (b) pgvector query latency p99 > 200ms at scale.

---

# 12. Fund Model Sunset

### Current State (2026-03-18)

Deprecated `Fund` model coexists with polymorphic `Instrument` model. Deprecation markers applied:

| Marker | Status |
|--------|--------|
| `DeprecationWarning` on Fund model import | DONE (SR-4) |
| OpenAPI `deprecated=true` on all 5 Fund routes | DONE (SR-4) |
| RFC 8594 `Sunset: 2026-06-30` + `Link: rel=successor-version` headers | DONE (SR-4) |
| Router tag `"funds (deprecated)"` | DONE (SR-4) |

### Sunset Plan

1. **2026-04 → 2026-05:** Migrate all Fund consumers to Instrument queries
2. **2026-06-01:** Remove Fund routes from frontend code
3. **2026-06-30:** Delete Fund model, routes, schemas, and migration

### Dependencies

- All ~17 files importing Fund must be migrated to Instrument
- Frontend fund list/detail pages must use Instrument endpoints
- Data migration: existing `funds` rows → `instruments_universe` entries

---

# 13. TimescaleDB Compression & Optimization

### Current State (2026-03-18)

Two hypertables exist (migration `0002`):

| Hypertable | Time Dimension | RLS Index |
|------------|---------------|-----------|
| `nav_timeseries` | `nav_date` | `organization_id` |
| `fund_risk_metrics` | `calc_date` | `organization_id` |

### Missing Configuration

- **`compress_segmentby = 'organization_id'`** — CLAUDE.md mandates this on all hypertables, but **no compression policies are configured** in any migration
- **Chunk interval tuning** — default TimescaleDB chunk intervals, not optimized for query patterns
- **Continuous aggregates** — no materialized views for common time-series rollups (daily → weekly → monthly)

### Target Direction (FUTURE)

- Add compression policies via migration: `ALTER TABLE ... SET (timescaledb.compress, timescaledb.compress_segmentby = 'organization_id')`
- Schedule compression: `SELECT add_compression_policy('nav_timeseries', INTERVAL '30 days')`
- Evaluate continuous aggregates for NAV rollups and risk metric summaries
- Monitor chunk sizes and adjust intervals based on query patterns

### Trigger

Implement when: (a) `nav_timeseries` exceeds 10M rows, or (b) time-series query latency degrades.

---

# 14. Pipeline Concurrency & Queueing

### Current State (2026-03-18)

- Extraction orchestration uses sync `run_item()` loop — TODO in code for `async + Semaphore(8) + gather`
- Document upload processing runs inline in request handler — TODO for Azure Service Bus queueing
- Deep review ConfigService integration still uses sync patterns — TODO for async session migration

### Target Direction (FUTURE)

| Component | Current | Target |
|-----------|---------|--------|
| Extraction orchestrator | Sync loop | `asyncio.Semaphore(8) + gather` |
| Document upload | Inline processing | Redis queue or ARQ |
| Deep review config | Sync ConfigService calls | Async session with `await ConfigService.get()` |

### Trigger

Implement when: (a) pipeline throughput is bottlenecked by sequential extraction, or (b) upload latency exceeds acceptable UX threshold.

---

# 15. Operational Add-On Modules

### Context

The analysis engine intentionally excludes operational modules. These will be developed as **separate acoplable add-ons** that connect via API:

| Module | Purpose | Status |
|--------|---------|--------|
| Cash Management | Accounts, transactions, reconciliation | FUTURE — separate service |
| Compliance Engine | KYC obligation engine, AML workflows | FUTURE — separate service |
| Signatures | Adobe Sign integration, queue | FUTURE — separate service |
| Counterparties | CRUD, bank accounts, four-eyes approval | FUTURE — separate service |

### Architecture Principle

> **Analysis engine = read-heavy, compute-heavy**
> **Operational modules = write-heavy, workflow-heavy**
> **Never co-deploy** — different scaling profiles, different SLA requirements.

Each add-on connects to the analysis engine via:
- REST API for data reads (portfolio state, risk metrics, fund data)
- Webhooks or events for state change notifications
- Shared PostgreSQL for tenant context (same Clerk JWT, same RLS)

---

# 16. Legacy Cleanup Inventory

Items that exist in code but should be replaced or removed:

| Legacy Pattern | Target | Priority | Status |
|----------------|--------|----------|--------|
| Direct Azure Blob SDK calls | StorageClient abstraction | HIGH | Open (blob_client.py deprecated 2026-03-18) |
| Cohere API references | Local cross-encoder reranker | MEDIUM | **Resolved** (zero references remain) |
| `cash_management/` references | Remove (out of scope) | LOW | **Resolved** (SR-3, 2026-03-18) |
| `compliance/` domain references | Remove (out of scope) | LOW | **Resolved** (SR-3, 2026-03-18) |
| `signatures/` references | Remove (out of scope) | LOW | No references found |
| `counterparties/` references | Remove (out of scope) | LOW | No references found |
| Inline f-string ADLS paths | `storage_routing.py` functions | HIGH | **Resolved** (HC-2, 2026-03-18) |
| `profiles/` YAML direct reads | `ConfigService.get()` | MEDIUM | Open |
| `fred_ingestion.py` dead code | Delete | LOW | **Resolved** (SR-5, 2026-03-18) |
| Fund model + routes | Instrument model | LOW | **Deprecated** (SR-4, sunset 2026-06-30) |

---

# Summary

This roadmap defines:
- **Infrastructure evolution** (ADLS migration, DuckDB query layer, TimescaleDB compression, worker queue, search resilience)
- **Pipeline maturity** (extraction concurrency, upload queueing, async config)
- **Analytical expansion** (senior analyst, macro intelligence, content production)
- **Architectural convergence** (instrument-centric, Fund sunset, cross-vertical patterns)
- **Operational add-ons** (cash management, compliance, signatures, counterparties — separate services)

### Backend Health Snapshot (2026-03-18)

| Metric | Value |
|--------|-------|
| Tests | 1304 passing |
| Import-linter contracts | 30 (16/16 quant services covered) |
| Audit v3 findings | 0 open (17 resolved, 2 mitigated) |
| Migrations | 18 files (head: `0019_audit_events`) |
| Routers | 51 (7 admin + 26 credit + 18 wealth) |
| Vertical engines | credit (13 packages) + wealth (4 modules) |

> **This is NOT a commitment.**
> **It is a directional map** for decisions that haven't been scheduled yet.
> When an item moves to execution, it gets a brainstorm + plan in `docs/plans/` and a feature branch.
