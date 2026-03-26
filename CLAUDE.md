# CLAUDE.md — Netz Analysis Engine

Unified multi-tenant analysis engine for institutional investment verticals.

## Commands

```bash
make check              # Full gate: lint + architecture + typecheck + test
make test               # pytest backend/tests/
make test ARGS="-k foo" # Run a single test or subset
make lint               # ruff check
make typecheck          # mypy
make architecture       # import-linter DAG enforcement
make serve              # uvicorn on :8000
make migrate            # alembic upgrade head
make migration MSG="…"  # Generate new migration
make up                 # docker-compose up -d (PG 16 + TimescaleDB + Redis 7)
make down               # docker-compose down

# Frontend (pnpm + Turborepo)
make dev-credit         # Credit frontend dev server
make dev-wealth         # Wealth frontend dev server
make dev-admin          # Admin frontend dev server
make dev-all            # All packages in parallel (Turborepo)
make build-all          # Build all packages (topological order)
make check-all          # Check all frontend packages
make types              # Generate TS types from OpenAPI schema (requires running backend)
```

## Architecture

```
backend/
  app/
    core/           ← auth (Clerk), tenancy (RLS), DB (asyncpg), config (ConfigService), jobs (SSE)
    domains/
      credit/       ← analytical modules only (deals, portfolio, documents, reporting, dashboard, dataroom, actions, global_agent)
        modules/ai/ ← IC memos, deep review, extraction, pipeline deals, copilot, compliance
      wealth/       ← models, routes, schemas, workers (26 tables, 15 workers, 18 route modules)
    services/
      storage_client.py ← StorageClient abstraction (LocalStorage dev, R2 prod, ADLS deprecated)
    shared/         ← enums, exceptions
  ai_engine/
    classification/ ← hybrid_classifier (rules → cosine_similarity → LLM)
    pipeline/       ← unified_pipeline, validation gates, models, storage_routing, search_rebuild
    extraction/     ← OCR (Mistral), semantic chunking, embedding, entity bootstrap, search upsert, local reranker, governance detector
    ingestion/      ← pipeline_ingest_runner, document_scanner, registry_bridge, monitoring
    validation/     ← vector_integrity_guard, deep_review validation, eval runner, evidence quality
    prompts/        ← Jinja2 templates (Netz IP — never expose to clients)
  quant_engine/     ← CVaR, regime, optimizer, scoring, drift, rebalance, FRED, Treasury, OFR, regional macro, stress severity, momentum
  vertical_engines/
    base/           ← BaseAnalyzer ABC — shared interface all verticals implement
    credit/         ← 12 modular packages (Wave 1 complete):
      critic/       ← IC critic engine
      deal_conversion/ ← deal conversion engine
      domain_ai/    ← domain AI engine
      edgar/        ← SEC EDGAR integration (edgartools)
      kyc/          ← KYC pipeline screening
      market_data/  ← market data engine (reads from macro_data hypertable, zero FRED API calls)
      memo/         ← memo book generator, chapter engine, chapter prompts, evidence pack, tone normalizer, batch client
      pipeline/     ← pipeline engine + pipeline intelligence
      portfolio/    ← portfolio intelligence
      quant/        ← IC quant engine, credit scenarios, credit sensitivity, credit backtest
      retrieval/    ← retrieval governance
      sponsor/      ← sponsor engine
      underwriting/ ← underwriting artifact
    wealth/         ← 14 modular packages + 6 standalone engines:
      dd_report/    ← 8-chapter DD report engine (evidence, confidence scoring, critic)
      fact_sheet/   ← PDF renderers (Executive/Institutional, PT/EN i18n)
      screener/     ← 3-layer deterministic screening (eliminatory → mandate fit → quant)
      correlation/  ← rolling correlation, Marchenko-Pastur denoising, absorption ratio
      attribution/  ← Brinson-Fachler policy benchmark attribution
      fee_drag/     ← fee drag ratio, efficiency analysis
      monitoring/   ← drift monitor, strategy drift scanner, alert engine
      watchlist/    ← PASS→FAIL transition detection
      mandate_fit/  ← constraint evaluator for client mandates
      peer_group/   ← peer matcher for fund comparison
      rebalancing/  ← weight proposer, impact analyzer
      asset_universe/ ← fund universe management, approval workflow
      model_portfolio/ ← portfolio builder, stress scenarios, track record
      critic/       ← adversarial chapter review (circuit-breaker, 3min timeout)
      fund_analyzer.py       ← BaseAnalyzer implementation (orchestrator)
      macro_committee_engine.py ← weekly regional macro reports
      quant_analyzer.py      ← CVaR, scoring, peer comparison
      flash_report.py        ← event-driven market flash (48h cooldown)
      investment_outlook.py  ← quarterly macro narrative
      manager_spotlight.py   ← deep-dive single fund manager analysis
profiles/           ← YAML analysis profiles — SEED DATA ONLY (runtime config in PostgreSQL)
calibration/        ← YAML quant configs — SEED DATA ONLY (runtime config in PostgreSQL)
packages/ui/        ← @netz/ui (Tailwind tokens, shadcn-svelte, layouts)
frontends/
  credit/           ← SvelteKit "netz-credit-intelligence"
  wealth/           ← SvelteKit "netz-wealth-os"
```

**Database:** PostgreSQL 16 + TimescaleDB + pgvector. Managed via Timescale Cloud (prod) or docker-compose (dev). Redis 7 via Upstash (prod) or docker-compose (dev). Migrations via Alembic. App uses async asyncpg. Current migration head: `0055_model_portfolio_nav`.

**Auth:** Clerk JWT v2. `organization_id` from `o.id` claim. RLS via `SET LOCAL app.current_organization_id`. Dev bypass: `X-DEV-ACTOR` header.

**SSE:** `sse-starlette` EventSourceResponse. Redis pub/sub for worker→SSE bridging. Frontend uses `fetch()` + `ReadableStream` (not EventSource — auth headers needed).

**Data Lake:** Three-tier storage abstraction with priority R2 > ADLS > LocalStorage. `LocalStorageClient` (filesystem at `.data/lake/`) is default for dev. `R2StorageClient` (Cloudflare R2 via S3-compatible API) is production target (`FEATURE_R2_ENABLED`). `ADLSStorageClient` is deprecated (2026-03-18), kept for rollback. Bronze/silver/gold hierarchy with `{organization_id}/{vertical}/` as path prefix. Path routing via `ai_engine/pipeline/storage_routing.py`. DuckDB queries LocalStorage filesystem for analytics.

**Unified Pipeline:** Single ingestion path for all sources (UI, batch, API). Stages: pre-filter → OCR → [gate] → classify → [gate] → governance → chunk → [gate] → extract metadata → [gate] → embed → [gate] → storage (StorageClient) → index (pgvector). Dual-write: StorageClient is source of truth, pgvector is derived index. pgvector index can be rebuilt from silver layer Parquet via `search_rebuild.py` without reprocessing PDFs.

**Classification:** Three-layer hybrid classifier (no external ML APIs). Layer 1: filename + keyword rules (~60% of docs). Layer 2: TF-IDF + cosine similarity (~30%). Layer 3: LLM fallback (~10%). Cross-encoder local reranker for IC memo evidence (replaced Cohere).

**1439+ tests.** All passing. Enforced by `make check` (lint + typecheck + test). CI: GitHub Actions (`pip install -e ".[dev,ai,quant]"`).

## Product Scope — Analytical Core Only

The engine contains only analytical domains. Operational modules were intentionally removed and will be developed as separate acoplable add-ons:

| In scope (analysis engine) | Out of scope (future add-on modules) |
|---|---|
| deals/ — pipeline, qualification, IC memos | cash_management/ — accounts, transactions, reconciliation |
| portfolio/ — assets, obligations, alerts, actions | compliance/ — KYC, obligation engine |
| documents/ — upload, review, evidence, ingestion | signatures/ — Adobe Sign, queue |
| reporting/ — NAV, report packs, investor statements | counterparties/ — CRUD, bank accounts, four-eyes |
| dashboard/ — aggregation | |
| global_agent/ — Fund Copilot RAG | |
| modules/ai/ — IC memos, deep review, extraction | |
| dataroom/ — folder governance | |

**Do not re-add operational modules.** If you see references to `cash_management`, `compliance`, `signatures`, `counterparties`, or `adobe_sign` in existing code, they are stale and should be removed.

**Critical distinction — cashflow vs cash_management:**
- `cash_management/` (OUT OF SCOPE): gestora's bank accounts, transaction reconciliation, fund transfers — operational
- `modules/deals/cashflow_service.py` (IN SCOPE): deal cashflow analytics — disbursements, repayments, MOIC, IRR, cash-to-cash — analytical credit module. These are NOT the same thing.

## Critical Rules

- **Async-first:** All route handlers use `async def` + `AsyncSession` from `get_db_with_rls`. Never use sync `Session`.
- **Pydantic schemas:** All routes use `response_model=` and return via `model_validate()`. No inline dict serialization.
- **expire_on_commit=False:** Always. Prevents implicit I/O in async context.
- **lazy="raise":** Set on ALL relationships. Forces explicit `selectinload()`/`joinedload()`.
- **RLS subselect:** All RLS policies must use `(SELECT current_setting(...))` not bare `current_setting()`. Without subselect, per-row evaluation causes 1000x slowdown.
- **Global tables:** `macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav`, `macro_regional_snapshots`, `treasury_data`, `ofr_hedge_fund_data`, `bis_statistics`, `imf_weo_forecasts`, `sec_*` tables have NO `organization_id`, NO RLS. They are shared across all tenants.
- **No module-level asyncio primitives:** Create `Semaphore`, `Lock`, `Event` lazily inside async functions. Module-level causes "attached to different event loop" errors.
- **ORM thread safety:** Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped). `SET` leaks across pooled connections.
- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API.
- **ConfigService for all config:** Never read `calibration/` or `profiles/` YAML at runtime. Use `ConfigService.get(vertical, config_type, org_id)`. YAML files are seed data only.
- **Prompts are Netz IP:** Never expose prompt content in client-facing API responses. Use `CLIENT_VISIBLE_TYPES` allowlist in ConfigService. Use `jinja2.SandboxedEnvironment` for all prompt rendering.
- **StorageClient for all storage:** Never call R2/ADLS SDK directly. Use `StorageClient` abstraction (`create_storage_client()` resolves R2 > ADLS > LocalStorage based on feature flags).
- **Dual-write ordering:** StorageClient write (source of truth) BEFORE pgvector upsert (derived index). If storage write fails, pipeline continues with warning. If pgvector upsert fails, data is safe in storage and can be rebuilt via `search_rebuild.py`.
- **Path routing via `storage_routing.py`:** Never build storage paths with f-strings in callers. Use `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`. All paths validated with `_SAFE_PATH_SEGMENT_RE`.
- **Parquet schema must include embedding metadata:** All silver layer Parquet files must have `embedding_model` and `embedding_dim` columns. `search_rebuild.py` validates dimension match before upserting — prevents silent corruption on model upgrade.
- **`organization_id` in vector search:** All pgvector queries MUST include `WHERE organization_id = :org_id` (SQL parameterized). All Parquet DuckDB queries MUST include `WHERE organization_id = ?`. Never query without tenant filter. (Azure Search files deprecated — `$filter=organization_id eq '{org_id}'` pattern no longer applies.)
- **No Cohere dependency:** Hybrid classifier (rules → cosine_similarity → LLM) replaced Cohere Rerank. Cross-encoder reranker (`local_reranker.py`) replaced Cohere for IC memo evidence. Zero external ML API calls for classification.
- **DB-first for external data:** All time-series external data (FRED, Treasury, OFR, Yahoo Finance, SEC EDGAR) is ingested by background workers into TimescaleDB hypertables. Routes and vertical engines read from DB only — never call external APIs in user-facing requests. Workers use `pg_try_advisory_lock(ID)` with deterministic lock IDs (never `hash()`), unlock in `finally`.
- **SEC data providers — DB-only in hot path:** `data_providers/sec/` services expose both DB-only reads and EDGAR API calls. Routes and DD reports must use ONLY DB-only methods: `ThirteenFService.read_holdings()`, `read_holdings_for_date()`, `get_sector_aggregation()`, `get_concentration_metrics()`, `compute_diffs()`; `AdvService.fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()`; `InstitutionalService.read_investors_in_manager()`. NEVER call `fetch_holdings()` (triggers EDGAR) or `discover_institutional_filers()` (triggers EFTS) from user-facing code — those are for `sec_13f_ingestion` and `sec_adv_ingestion` workers only.
- **Frontend formatter discipline:** All number/date/currency formatting MUST use formatters from `@netz/ui` (`formatNumber`, `formatCurrency`, `formatPercent`, `formatDate`, `formatDateTime`, `formatShortDate`, etc.). Never use `.toFixed()`, `.toLocaleString()`, or inline `new Intl.NumberFormat`/`Intl.DateTimeFormat` in frontend code. Enforced by `frontends/eslint.config.js`.

## Vertical Engines

Two-layer architecture: universal core (`ai_engine/`) + vertical specializations (`vertical_engines/`).

- `ai_engine/` — domain-agnostic: unified pipeline, hybrid classification, extraction, chunking, embedding, OCR, governance, validation, storage routing, search rebuild. Never modified per vertical.
- `vertical_engines/{vertical}/` — domain-specific: analysis logic, prompts, scoring. One directory per asset class.
- `vertical_engines/credit/` — 12 modular packages (Wave 1 complete, PR #9-#19). Each package has `models.py`, `service.py`, and domain helpers. `service.py` is the entry point; helpers must NOT import from `service.py` (enforced by import-linter).
- `vertical_engines/wealth/` — 14 modular packages (dd_report, fact_sheet, screener, correlation, attribution, fee_drag, monitoring, watchlist, mandate_fit, peer_group, rebalancing, asset_universe, model_portfolio, critic) + 6 standalone engines (fund_analyzer, macro_committee_engine, quant_analyzer, flash_report, investment_outlook, manager_spotlight). Each package follows same structure as credit: `models.py`, `service.py`, domain helpers.
- `ProfileLoader` connects `profiles/` YAML config to `vertical_engines/` code via `ConfigService`.
- **Do not rewrite vertical_engines/credit/ business logic.** Only session injection allowed (caller provides `db: Session`).
- `quant_engine/` services receive config as parameter (no YAML loading, no `@lru_cache`). Config resolved once at async entry point via `ConfigService.get()`, passed down to sync functions.

## Import Architecture (import-linter)

Enforced via `import-linter` in `make check`. Contracts in `pyproject.toml`:

1. **Verticals must not import each other:** `vertical_engines.credit` ↔ `vertical_engines.wealth` are independent.
2. **Models must not import service:** `vertical_engines.credit.*.models` → `vertical_engines.credit.*.service` is forbidden. Prevents circular dependencies.
3. **Helpers must not import service:** Within each credit package, helpers (parser, classifier, prompts) must not import from `service.py`. `service.py` imports helpers, not the reverse.
4. **Vertical-agnostic quant services:** `quant_engine.regime_service` and `quant_engine.cvar_service` must not import from `app.domains.wealth`.

## Data Lake Rules

1. `{organization_id}/{vertical}/` is ALWAYS the path prefix under `bronze/` and `silver/` — enforced by `storage_routing.py`
2. `_global/` is for data with no tenant context — FRED macro, ETF benchmarks — via `global_reference_path()`
3. `macro_data` PostgreSQL table = operational use (regime detection, daily pipeline)
4. `gold/_global/fred_indicators/` = analytics use (backtesting, cross-fund correlation)
5. All workers must write Parquet with `organization_id` as a column AND as a path segment
6. DuckDB queries must always include `WHERE organization_id = ?` even when path already isolates
7. TimescaleDB hypertables: `compress_segmentby = 'organization_id'` on tenant-scoped hypertables; `compress_segmentby = 'series_id'` (or `cik`, `filer_cik`) on global hypertables
8. Pipeline writes: OCR → `bronze/.../documents/{doc_id}.json`, chunks → `silver/.../chunks/{doc_id}/chunks.parquet`, metadata → `silver/.../documents/{doc_id}/metadata.json`
9. Parquet files must use zstd compression and include `embedding_model` + `embedding_dim` columns for rebuild validation
10. `search_rebuild.py` can reconstruct pgvector `vector_chunks` table from silver Parquet — no OCR/LLM calls needed. (Azure Search index rebuild is deprecated — Azure Search files kept for rollback only.)

## Data Ingestion Workers (DB-First Pattern)

Background workers ingest all external time-series data into hypertables. Routes and vertical engines read from DB only.

| Worker | Lock ID | Scope | Hypertable | Source | Frequency |
|--------|---------|-------|-----------|--------|-----------|
| `macro_ingestion` | 43 | global | `macro_data` (1mo chunks) | FRED API (~65 series: 4 regions + global + credit + 20 Case-Shiller metros) | Daily |
| `treasury_ingestion` | 900_011 | global | `treasury_data` (1mo chunks) | US Treasury API (rates, debt, auctions, FX, interest) | Daily |
| `ofr_ingestion` | 900_012 | global | `ofr_hedge_fund_data` (3mo chunks) | OFR API (leverage, AUM, strategy, repo, stress) | Weekly |
| `benchmark_ingest` | 900_004 | global | `benchmark_nav` (1mo chunks) | Yahoo Finance | Daily |
| `instrument_ingestion` | 900_010 | org | `nav_timeseries` | Yahoo Finance (or pluggable provider) | Daily |
| `risk_calc` | 900_007 | org | `fund_risk_metrics` | Computed (CVaR, Sharpe, volatility, momentum: RSI, Bollinger, OBV) | Daily |
| `portfolio_eval` | 900_008 | org | `portfolio_snapshots` | Computed (breach status, regime, cascade) | Daily |
| `nport_ingestion` | 900_018 | global | `sec_nport_holdings` (3mo chunks) | SEC EDGAR N-PORT XML | Weekly |
| `sec_13f_ingestion` | 900_021 | global | `sec_13f_holdings`, `sec_13f_diffs` | SEC EDGAR 13F-HR (edgartools) | Weekly |
| `sec_adv_ingestion` | 900_022 | global | `sec_managers`, `sec_manager_funds` | SEC FOIA bulk CSV | Monthly |
| `bis_ingestion` | 900_014 | global | `bis_statistics` (1yr chunks) | BIS SDMX API (credit gap, DSR, property) | Quarterly |
| `imf_ingestion` | 900_015 | global | `imf_weo_forecasts` (1yr chunks) | IMF DataMapper API (GDP, inflation, fiscal) | Quarterly |
| `drift_check` | 42 | org | `strategy_drift_alerts` | Computed (DTW drift) | Daily |
| `portfolio_nav_synthesizer` | 900_030 | org | `model_portfolio_nav` (1mo chunks) | Computed (weighted NAV from nav_timeseries) | Daily |

**Credit market_data** reads all macro data from `macro_data` hypertable (zero FRED API calls at runtime, `fred_client.py` eliminated). Regional Case-Shiller (20 metros) also from `macro_data`.

**Momentum signals** (RSI, Bollinger, OBV flow) are pre-computed by `risk_calc` worker into `fund_risk_metrics` columns (`rsi_14`, `bb_position`, `nav_momentum_score`, `flow_momentum_score`, `blended_momentum_score`). Scoring route reads pre-computed values — no in-request TA-Lib computation.

**Analytics caching:** `POST /analytics/optimize` results cached in Redis (SHA-256 of inputs including date, 1h TTL). `POST /analytics/optimize/pareto` runs as background job with SSE progress (returns 202 immediately).

## Environment Variables

```bash
# Core
DATABASE_URL=postgresql+asyncpg://...  # Timescale Cloud (prod), docker-compose (dev)
REDIS_URL=redis://localhost:6379/0     # Upstash (prod), docker-compose (dev)

# Auth
CLERK_SECRET_KEY=
CLERK_JWKS_URL=

# AI
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-large

# Mistral (OCR)
MISTRAL_API_KEY=

# Storage (LocalStorageClient at .data/lake/ in dev; R2StorageClient in prod)
FEATURE_R2_ENABLED=false          # Cloudflare R2 (production target)
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_ENDPOINT_URL=

# ── DEPRECATED (Azure services eliminated — Milestone 2 simplification, 2026-03-18) ──
# FEATURE_ADLS_ENABLED=false    # replaced by FEATURE_R2_ENABLED (R2StorageClient)
# AZURE_OPENAI_ENDPOINT=        # replaced by OpenAI direct with retry backoff
# AZURE_OPENAI_KEY=             # replaced by OpenAI direct with retry backoff
# AZURE_SEARCH_ENDPOINT=        # replaced by pgvector (commit 497df51)
# AZURE_SEARCH_KEY=             # replaced by pgvector
# SEARCH_CHUNKS_INDEX_NAME=     # replaced by pgvector
# NETZ_ENV=                     # search index prefixing no longer needed
# KEYVAULT_URL=                 # replaced by platform env vars (Railway secrets)
# SERVICE_BUS_NAMESPACE=        # replaced by Redis pub/sub + BackgroundTasks
# APPLICATIONINSIGHTS_CONNECTION_STRING=  # replaced by structlog → stdout
# ADLS_ACCOUNT_NAME=            # replaced by R2StorageClient
# ADLS_ACCOUNT_KEY=
# ADLS_CONTAINER_NAME=
# ADLS_CONNECTION_STRING=
```

## Clerk SvelteKit SDK Note

No official Clerk SvelteKit SDK exists. Use community packages: `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). These may lag behind Clerk API changes. Fallback: manual JWT verification on server (`clerk_auth.py`) + `svelte-clerk` for UI only.

## Skills

Custom skills live in `.claude/skills/`. Each subfolder contains a `SKILL.md` with frontmatter (`name`, `description`) that describes when to use it. **Do not maintain a hardcoded list here.** To discover available skills, glob `.claude/skills/**/SKILL.md` and read the frontmatter to find the best match for the current task. Invoke via the `Skill` tool or `/skill-name`.

## Infrastructure (Milestone 2 — up to 50 tenants)

Simplified stack (2026-03-18), ~$100-200/month:
- **Timescale Cloud** — managed PostgreSQL 16 (pgvector + TimescaleDB nativo)
- **Railway** — container hosting (FastAPI backend + 3 SvelteKit frontends)
- **Upstash** — serverless Redis (SSE pub/sub, job tracking, worker idempotency, advisory locks)
- **OpenAI API** (direct, with retry backoff) — LLM + embeddings
- **Mistral** — OCR
- **Clerk** — auth (JWT v2)
- **StorageClient** — LocalStorageClient (dev, filesystem at `.data/lake/`), R2StorageClient (prod target, Cloudflare R2 S3-compatible)

Deprecated Azure services (files kept for rollback, not actively used):
- Azure Key Vault → platform env vars (Railway secrets)
- Azure Service Bus → Redis + BackgroundTasks
- Application Insights → structlog → stdout
- Azure OpenAI → OpenAI direct (retry replaces fallback)
- Azure AI Search → pgvector (commit 497df51)
- ADLS Gen2 → R2StorageClient (ADLSStorageClient kept for rollback)

Scale triggers for re-adding services (Milestone 3+, >50 tenants):
- **Key Vault / HashiCorp Vault:** regulatory requirement for secret rotation audit trail (SOC2)
- **Redis Streams:** guaranteed delivery needed for financial transactions
- **Application Insights:** distributed tracing across microservices (if/when decomposed)
- **Qdrant or Weaviate:** only if pgvector HNSW performance becomes bottleneck at scale (unlikely before 10M+ chunks)

## Deployment

- **Backend:** `railway.toml` at repo root. Health check: `/api/v1/admin/health`.
- **Frontends:** Railway or Vercel/Cloudflare Pages with SvelteKit adapter.
- **Database:** Timescale Cloud managed PostgreSQL 16 with pgvector + TimescaleDB.
- **Local dev:** `docker-compose up` (PostgreSQL 16 + TimescaleDB + pgvector + Redis 7).

## Origins

- **Platform Plan:** `docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md`
- **Platform Brainstorm:** `docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md`
- **ProductConfig Plan:** `docs/plans/2026-03-14-feat-customizable-vertical-config-plan.md` (deepened with 7 review agents)
- **ProductConfig Brainstorm:** `docs/brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md`
- **Pipeline Refactor Plan:** `docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md` (3 phases, all complete — PRs #20, #21, #22)
- **Pipeline Refactor Brainstorm:** `docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md`
- **Credit Modularization Plan:** `docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md` (Wave 2 — deep review modules)
- **Wealth Modularization Plan:** `docs/plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md`
- **Infrastructure Completion Plan:** `docs/plans/2026-03-18-feat-duckdb-data-lake-inspection-layer-plan.md`
- **Private Credit OS:** `C:\Users\andre\projetos\Netz-Private-Credit-OS` (archived after data migration)
- **Wealth OS:** `C:\Users\andre\projetos\netz-wealth-os` (archived after migration)


## Svelte MCP

When working on any SvelteKit frontend (`frontends/credit/` or `frontends/wealth/`), the Svelte MCP server is available for documentation lookup and code validation.

**Remote MCP (recommended):**
```json
{
  "mcpServers": {
    "svelte": {
      "type": "http",
      "url": "https://mcp.svelte.dev/mcp"
    }
  }
}
```

**Local MCP (alternative):**
```bash
npx @sveltejs/mcp list-sections
npx @sveltejs/mcp get-documentation "<section1>,<section2>"
npx @sveltejs/mcp svelte-autofixer ./src/lib/Component.svelte
```

**Rules for Svelte work:**
- ALWAYS run `list-sections` first to find relevant documentation sections
- ALWAYS run `svelte-autofixer` before finalizing any `.svelte` component
- Use `fetch()` + `ReadableStream` for SSE — NEVER `EventSource` (cannot send auth headers)
- Svelte 5 runes syntax (`$state`, `$derived`, `$effect`) — escape `$` as `\$` in terminal

## UX Sprint 7 — Scope Decisions (2026-03-19)

### C.3 — Portfolio deal-level contract fields: NOT IMPLEMENTED (architecture decision)

The portfolio view (`frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`) is asset-centric post-conversion. Assets are identified by name, type, and strategy with tabs for obligations, alerts, and actions. Fields like tenor, basis, and covenant are deal-level contract fields that live in `deal_context.json` on the deal entity — NOT on portfolio assets. Displaying them per asset row would cross the deal/asset boundary and create misleading attribution (one deal can map to one asset, but deal terms do not become asset attributes post-conversion). Do not add tenor/basis/covenant to the portfolio asset view. If deal-level contract terms need to be visible post-conversion, add a "Source Deal" link from the asset to the originating deal's detail page.

### C.4 — Kanban pipeline board: IMPLEMENTED

`PipelineKanban.svelte` component with `svelte-dnd-action@^0.9.0`. 8 stage columns, drag-drop with ConsequenceDialog + rationale, PATCH to `/pipeline/deals/{deal_id}/stage`. Toggle between list/kanban view modes in PageHeader.

## Audit Trail

Immutable audit logging via `write_audit_event()` in `backend/app/core/db/audit.py`. Records CREATE/UPDATE/DELETE with before/after JSONB snapshots, correlated via `request_id`. Model: `AuditEvent` in `backend/app/core/db/models.py` (RLS-scoped). Used across 17+ modules for entity-level change tracking.
