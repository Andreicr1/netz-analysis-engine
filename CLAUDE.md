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
make dev:credit         # Credit frontend dev server
make dev:wealth         # Wealth frontend dev server
make dev:admin          # Admin frontend dev server
make dev:all            # All packages in parallel (Turborepo)
make build:all          # Build all packages (topological order)
make check:all          # Check all frontend packages
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
      wealth/       ← models, routes, schemas, workers (12 tables, 7 services)
    services/
      storage_client.py ← ADLS abstraction (LocalStorageClient dev, ADLSStorageClient prod)
    shared/         ← enums, exceptions
  ai_engine/
    classification/ ← hybrid_classifier (rules → cosine_similarity → LLM)
    pipeline/       ← unified_pipeline, validation gates, models, storage_routing, search_rebuild
    extraction/     ← OCR (Mistral), semantic chunking, embedding, entity bootstrap, search upsert, local reranker, governance detector
    ingestion/      ← pipeline_ingest_runner, document_scanner, registry_bridge, monitoring
    validation/     ← vector_integrity_guard, deep_review validation, eval runner, evidence quality
    prompts/        ← Jinja2 templates (Netz IP — never expose to clients)
  quant_engine/     ← CVaR, regime, optimizer, scoring, drift, rebalance, FRED, regional macro, stress severity, momentum
  vertical_engines/
    base/           ← BaseAnalyzer ABC — shared interface all verticals implement
    credit/         ← 12 modular packages (Wave 1 complete):
      critic/       ← IC critic engine
      deal_conversion/ ← deal conversion engine
      domain_ai/    ← domain AI engine
      edgar/        ← SEC EDGAR integration (edgartools)
      kyc/          ← KYC pipeline screening
      market_data/  ← market data engine
      memo/         ← memo book generator, chapter engine, chapter prompts, evidence pack, tone normalizer, batch client
      pipeline/     ← pipeline engine + pipeline intelligence
      portfolio/    ← portfolio intelligence
      quant/        ← IC quant engine, credit scenarios, credit sensitivity, credit backtest
      retrieval/    ← retrieval governance
      sponsor/      ← sponsor engine
      underwriting/ ← underwriting artifact
    wealth/         ← fund_analyzer, dd_report_engine, macro_committee_engine, quant_analyzer
profiles/           ← YAML analysis profiles — SEED DATA ONLY (runtime config in PostgreSQL)
calibration/        ← YAML quant configs — SEED DATA ONLY (runtime config in PostgreSQL)
packages/ui/        ← @netz/ui (Tailwind tokens, shadcn-svelte, layouts)
frontends/
  credit/           ← SvelteKit "netz-credit-intelligence"
  wealth/           ← SvelteKit "netz-wealth-os"
```

**Database:** PostgreSQL 16 + TimescaleDB + Redis 7. Migrations via Alembic. App uses async asyncpg. Current migration head: `0004_vertical_configs`.

**Auth:** Clerk JWT v2. `organization_id` from `o.id` claim. RLS via `SET LOCAL app.current_organization_id`. Dev bypass: `X-DEV-ACTOR` header.

**SSE:** `sse-starlette` EventSourceResponse. Redis pub/sub for worker→SSE bridging. Frontend uses `fetch()` + `ReadableStream` (not EventSource — auth headers needed).

**Data Lake (LocalStorage/ADLS Gen2):** Feature-flagged (`FEATURE_ADLS_ENABLED=false` — LocalStorageClient in dev and production until Milestone 3). Bronze/silver/gold hierarchy with `{organization_id}/{vertical}/` as path prefix. Path routing via `ai_engine/pipeline/storage_routing.py`. DuckDB queries LocalStorage filesystem for analytics (Phase 1). When `FEATURE_ADLS_ENABLED=true`, DuckDB will query ADLS directly (Phase 3 — requires `ADLSStorageClient.get_duckdb_path()` implementation).

**Unified Pipeline:** Single ingestion path for all sources (UI, batch, API). Stages: pre-filter → OCR → [gate] → classify → [gate] → governance → chunk → [gate] → extract metadata → [gate] → embed → [gate] → storage (LocalStorage/ADLS) → index (pgvector). Dual-write: LocalStorage/ADLS is source of truth, pgvector is derived index. pgvector index can be rebuilt from silver layer Parquet via `search_rebuild.py` without reprocessing PDFs.

**Classification:** Three-layer hybrid classifier (no external ML APIs). Layer 1: filename + keyword rules (~60% of docs). Layer 2: TF-IDF + cosine similarity (~30%). Layer 3: LLM fallback (~10%). Cross-encoder local reranker for IC memo evidence (replaced Cohere).

**324 tests.** All passing. Enforced by `make check` (lint + typecheck + test).

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

## Critical Rules

- **Async-first:** All route handlers use `async def` + `AsyncSession` from `get_db_with_rls`. Never use sync `Session`.
- **Pydantic schemas:** All routes use `response_model=` and return via `model_validate()`. No inline dict serialization.
- **expire_on_commit=False:** Always. Prevents implicit I/O in async context.
- **lazy="raise":** Set on ALL relationships. Forces explicit `selectinload()`/`joinedload()`.
- **RLS subselect:** All RLS policies must use `(SELECT current_setting(...))` not bare `current_setting()`. Without subselect, per-row evaluation causes 1000x slowdown.
- **Global tables:** `macro_data`, `allocation_blocks`, `vertical_config_defaults` have NO `organization_id`, NO RLS. They are shared across all tenants.
- **No module-level asyncio primitives:** Create `Semaphore`, `Lock`, `Event` lazily inside async functions. Module-level causes "attached to different event loop" errors.
- **ORM thread safety:** Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped). `SET` leaks across pooled connections.
- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API.
- **ConfigService for all config:** Never read `calibration/` or `profiles/` YAML at runtime. Use `ConfigService.get(vertical, config_type, org_id)`. YAML files are seed data only.
- **Prompts are Netz IP:** Never expose prompt content in client-facing API responses. Use `CLIENT_VISIBLE_TYPES` allowlist in ConfigService. Use `jinja2.SandboxedEnvironment` for all prompt rendering.
- **StorageClient for all storage:** Never call ADLS SDK directly. Use `StorageClient` abstraction (local filesystem when `FEATURE_ADLS_ENABLED=false`).
- **Dual-write ordering:** ADLS write (source of truth) BEFORE pgvector upsert (derived index). If ADLS fails, pipeline continues with warning. If pgvector upsert fails, data is safe in ADLS/LocalStorage and can be rebuilt via `search_rebuild.py`. Azure Search files kept as deprecated fallback — see `feat/pgvector-replace-azure-search` branch.
- **Path routing via `storage_routing.py`:** Never build ADLS paths with f-strings in callers. Use `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`. All paths validated with `_SAFE_PATH_SEGMENT_RE`.
- **Parquet schema must include embedding metadata:** All silver layer Parquet files must have `embedding_model` and `embedding_dim` columns. `search_rebuild.py` validates dimension match before upserting — prevents silent corruption on model upgrade.
- **`organization_id` in vector search:** All pgvector queries MUST include `WHERE organization_id = :org_id` (SQL parameterized). All Parquet DuckDB queries MUST include `WHERE organization_id = ?`. Never query without tenant filter. (Azure Search files deprecated — `$filter=organization_id eq '{org_id}'` pattern no longer applies.)
- **No Cohere dependency:** Hybrid classifier (rules → cosine_similarity → LLM) replaced Cohere Rerank. Cross-encoder reranker (`local_reranker.py`) replaced Cohere for IC memo evidence. Zero external ML API calls for classification.

## Vertical Engines

Two-layer architecture: universal core (`ai_engine/`) + vertical specializations (`vertical_engines/`).

- `ai_engine/` — domain-agnostic: unified pipeline, hybrid classification, extraction, chunking, embedding, OCR, governance, validation, storage routing, search rebuild. Never modified per vertical.
- `vertical_engines/{vertical}/` — domain-specific: analysis logic, prompts, scoring. One directory per asset class.
- `vertical_engines/credit/` — 12 modular packages (Wave 1 complete, PR #9-#19). Each package has `models.py`, `service.py`, and domain helpers. `service.py` is the entry point; helpers must NOT import from `service.py` (enforced by import-linter).
- `vertical_engines/wealth/` — `fund_analyzer.py` (implements `BaseAnalyzer`), `dd_report_engine.py`, `macro_committee_engine.py`, `quant_analyzer.py`.
- `ProfileLoader` connects `profiles/` YAML config to `vertical_engines/` code via `ConfigService`.
- **Do not rewrite vertical_engines/credit/ business logic.** Only session injection allowed (caller provides `db: Session`).
- `quant_engine/` services receive config as parameter (no YAML loading, no `@lru_cache`). Config resolved once at async entry point via `ConfigService.get()`, passed down to sync functions.

## Import Architecture (import-linter)

Enforced via `import-linter` in `make check`. Contracts in `pyproject.toml`:

1. **Verticals must not import each other:** `vertical_engines.credit` ↔ `vertical_engines.wealth` are independent.
2. **Models must not import service:** `vertical_engines.credit.*.models` → `vertical_engines.credit.*.service` is forbidden. Prevents circular dependencies.
3. **Helpers must not import service:** Within each credit package, helpers (parser, classifier, prompts) must not import from `service.py`. `service.py` imports helpers, not the reverse.
4. **Vertical-agnostic quant services:** `quant_engine.regime_service` and `quant_engine.cvar_service` must not import from `app.domains.wealth`.

## Data Lake Rules (ADLS Gen2)

1. `{organization_id}/{vertical}/` is ALWAYS the path prefix under `bronze/` and `silver/` — enforced by `storage_routing.py`
2. `_global/` is for data with no tenant context — FRED macro, ETF benchmarks — via `global_reference_path()`
3. `macro_data` PostgreSQL table = operational use (regime detection, daily pipeline)
4. `gold/_global/fred_indicators/` = analytics use (backtesting, cross-fund correlation)
5. All workers must write Parquet with `organization_id` as a column AND as a path segment
6. DuckDB queries must always include `WHERE organization_id = ?` even when path already isolates
7. TimescaleDB hypertables: `compress_segmentby = 'organization_id'` on all hypertables
8. Pipeline writes: OCR → `bronze/.../documents/{doc_id}.json`, chunks → `silver/.../chunks/{doc_id}/chunks.parquet`, metadata → `silver/.../documents/{doc_id}/metadata.json`
9. Parquet files must use zstd compression and include `embedding_model` + `embedding_dim` columns for rebuild validation
10. `search_rebuild.py` can reconstruct pgvector `vector_chunks` table from silver Parquet — no OCR/LLM calls needed. (Azure Search index rebuild is deprecated — Azure Search files kept for rollback only.)

## Environment Variables

```bash
# Core
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://localhost:6379/0

# Auth
CLERK_SECRET_KEY=
CLERK_JWKS_URL=

# AI
OPENAI_API_KEY=
OPENAI_EMBEDDING_MODEL=text-embedding-3-large

# Mistral (OCR)
MISTRAL_API_KEY=

# Data Lake (disabled by default — LocalStorageClient at .data/lake/ in dev and production until Milestone 3)
FEATURE_ADLS_ENABLED=false
ADLS_ACCOUNT_NAME=
ADLS_ACCOUNT_KEY=
ADLS_CONTAINER_NAME=netz-analysis
ADLS_CONNECTION_STRING=

# ── DEPRECATED (Azure services eliminated — Milestone 2 simplification, 2026-03-18) ──
# AZURE_OPENAI_ENDPOINT=        # replaced by OpenAI direct with retry backoff
# AZURE_OPENAI_API_KEY=         # replaced by OpenAI direct with retry backoff
# SEARCH_CHUNKS_INDEX_NAME=     # replaced by pgvector (feat/pgvector-replace-azure-search)
# NETZ_ENV=                     # search index prefixing no longer needed
# KEYVAULT_URL=                 # replaced by platform env vars
# SERVICE_BUS_NAMESPACE=        # replaced by Redis pub/sub + BackgroundTasks
# APPLICATIONINSIGHTS_CONNECTION_STRING=  # replaced by structlog → stdout
```

## Clerk SvelteKit SDK Note

No official Clerk SvelteKit SDK exists. Use community packages: `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). These may lag behind Clerk API changes. Fallback: manual JWT verification on server (`clerk_auth.py`) + `svelte-clerk` for UI only.

## Skills

Custom skills live in `.claude/skills/`. Each subfolder contains a `SKILL.md` with frontmatter (`name`, `description`) that describes when to use it. **Do not maintain a hardcoded list here.** To discover available skills, glob `.claude/skills/**/SKILL.md` and read the frontmatter to find the best match for the current task. Invoke via the `Skill` tool or `/skill-name`.

## Infrastructure (Milestone 2 — up to 50 tenants)

Simplified stack (2026-03-18):
- **PostgreSQL** (pgvector + TimescaleDB) — vector search, time-series, RLS, all data
- **Redis** — SSE pub/sub, job tracking, worker idempotency, advisory locks
- **OpenAI API** (direct, with retry backoff) — LLM + embeddings
- **Mistral** — OCR
- **Clerk** — auth (JWT v2)
- **LocalStorageClient** (filesystem with persistent volume) — data lake (bronze/silver/gold Parquet)

Deprecated Azure services (files kept for rollback, not actively used):
- Azure Key Vault → platform env vars
- Azure Service Bus → Redis + BackgroundTasks
- Application Insights → structlog → stdout
- Azure OpenAI → OpenAI direct (retry replaces fallback)
- Azure AI Search → pgvector (migration in `feat/pgvector-replace-azure-search` branch)
- ADLS Gen2 → LocalStorageClient with persistent volume (re-enables at Milestone 3)

Scale triggers for re-adding services (Milestone 3+, >50 tenants):
- **Key Vault:** regulatory requirement for secret rotation audit trail (SOC2)
- **ADLS:** data lake > 1TB or data residency requirements
- **Service Bus:** guaranteed delivery needed for financial transactions
- **Application Insights:** distributed tracing across microservices (if/when decomposed)
- **Azure AI Search:** only if pgvector HNSW performance becomes bottleneck at scale (unlikely before 10M+ chunks)

## Origins

- **Platform Plan:** `docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md`
- **Platform Brainstorm:** `docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md`
- **ProductConfig Plan:** `docs/plans/2026-03-14-feat-customizable-vertical-config-plan.md` (deepened with 7 review agents)
- **ProductConfig Brainstorm:** `docs/brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md`
- **Pipeline Refactor Plan:** `docs/plans/2026-03-15-refactor-pipeline-llm-deterministic-alignment-plan.md` (3 phases, all complete — PRs #20, #21, #22)
- **Pipeline Refactor Brainstorm:** `docs/brainstorms/2026-03-15-pipeline-llm-deterministic-alignment-brainstorm.md`
- **Credit Modularization Plan:** `docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md` (Wave 2 — deep review modules)
- **Wealth Modularization Plan:** `docs/plans/2026-03-15-feat-wealth-vertical-complete-modularization-plan.md`
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
