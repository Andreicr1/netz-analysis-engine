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
      wealth/       ← models, routes, schemas, workers (28 tables, 17 workers, 17 route modules)
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
  quant_engine/     ← CVaR, regime, optimizer (CLARABEL 4-phase cascade + robust SOCP), Black-Litterman, factor model (PCA), GARCH, scoring, drift, rebalance, FRED, Treasury, OFR, regional macro, stress severity, momentum
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
    wealth/         ← 15 modular packages + 6 standalone engines:
      dd_report/    ← 8-chapter DD report engine (evidence, confidence scoring, critic)
      long_form_report/ ← multi-chapter long-form DD report (SSE streaming, Semaphore(2))
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
data_providers/
  sec/              ← SEC EDGAR data providers (adv_service, thirteenf_service, nport_service, iapd_xml_parser)
frontends/
  credit/           ← SvelteKit "netz-credit-intelligence"
  wealth/           ← SvelteKit "netz-wealth-os"
```

**Database:** PostgreSQL 16 + TimescaleDB + pgvector. Managed via Timescale Cloud (prod) or docker-compose (dev). Redis 7 via Upstash (prod) or docker-compose (dev). Migrations via Alembic. App uses async asyncpg. Current migration head: `0173_factor_model_fits`.

**Auth:** Clerk JWT v2. `organization_id` from `o.id` claim. RLS via `SET LOCAL app.current_organization_id`. Dev bypass: `X-DEV-ACTOR` header. **Tenant and user management is 100% via Clerk Dashboard** — no custom admin UI. Organizations, user invites, and role assignment (`ADMIN`, `INVESTMENT_TEAM`, `investor`) are all managed in Clerk. `ConfigService` defaults mean new tenants work immediately without provisioning.

**SSE:** `sse-starlette` EventSourceResponse. Redis pub/sub for worker→SSE bridging. Frontend uses `fetch()` + `ReadableStream` (not EventSource — auth headers needed).

**Data Lake:** Three-tier storage abstraction with priority R2 > ADLS > LocalStorage. `LocalStorageClient` (filesystem at `.data/lake/`) is default for dev. `R2StorageClient` (Cloudflare R2 via S3-compatible API) is production target (`FEATURE_R2_ENABLED`). `ADLSStorageClient` is deprecated (2026-03-18), kept for rollback. Bronze/silver/gold hierarchy with `{organization_id}/{vertical}/` as path prefix. Path routing via `ai_engine/pipeline/storage_routing.py`. DuckDB queries LocalStorage filesystem for analytics.

**Unified Pipeline:** Single ingestion path for all sources (UI, batch, API). Stages: pre-filter → OCR → [gate] → classify → [gate] → governance → chunk → [gate] → extract metadata → [gate] → embed → [gate] → storage (StorageClient) → index (pgvector). Dual-write: StorageClient is source of truth, pgvector is derived index. pgvector index can be rebuilt from silver layer Parquet via `search_rebuild.py` without reprocessing PDFs.

**Classification:** Three-layer hybrid classifier (no external ML APIs). Layer 1: filename + keyword rules (~60% of docs). Layer 2: TF-IDF + cosine similarity (~30%). Layer 3: LLM fallback (~10%). Cross-encoder local reranker for IC memo evidence (replaced Cohere).

**3176+ tests.** All passing. Enforced by `make check` (lint + typecheck + test). CI: GitHub Actions (`pip install -e ".[dev,ai,quant]"`).

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

## Stability Guardrails

> Em gestão institucional de patrimônio, imprevisibilidade é risco operacional inaceitável.

Six non-negotiable principles enforced across the stack: **P1 Bounded**, **P2 Batched**, **P3 Isolated**, **P4 Lifecycle**, **P5 Idempotent**, **P6 Fault-Tolerant**. Primitives live in `backend/app/core/runtime/` and `packages/investintell-ui/src/lib/runtime/`. Full charter: **`docs/reference/stability-guardrails.md`**. PR checklist: `.github/PULL_REQUEST_TEMPLATE.md`.

**Mandatory patterns (charter §3):**
- WebSocket fan-out → `RateLimitedBroadcaster` + `ConnectionId` UUID (never `id(ws)`)
- Routes with expected p95 > 500ms → **Job-or-Stream** (202 + `/jobs/{id}/stream` SSE)
- External HTTP → `ExternalProviderGate` (interactive 30s / bulk 5min variants for SEC)
- Detail pages → `RouteData<T>` load contract (never `throw error()`) + `<svelte:boundary>` + `PanelErrorState`
- High-frequency client events (> 10/s) → `createTickBuffer<T>` (never `$state` spreads)
- Mutating routes → `@idempotent` decorator + triple-layer dedup (Redis + SingleFlightLock + `pg_advisory_xact_lock`)
- Advisory lock keys → **`zlib.crc32`**, never Python built-in `hash()` (non-deterministic across processes)

## Critical Rules

- **Async-first:** All route handlers use `async def` + `AsyncSession` from `get_db_with_rls`. Never use sync `Session`.
- **Pydantic schemas:** All routes use `response_model=` and return via `model_validate()`. No inline dict serialization.
- **expire_on_commit=False:** Always. Prevents implicit I/O in async context.
- **lazy="raise":** Set on ALL relationships. Forces explicit `selectinload()`/`joinedload()`.
- **RLS subselect:** All RLS policies must use `(SELECT current_setting(...))` not bare `current_setting()`. Without subselect, per-row evaluation causes 1000x slowdown.
- **Global tables:** `macro_data`, `allocation_blocks`, `vertical_config_defaults`, `benchmark_nav`, `macro_regional_snapshots`, `treasury_data`, `ofr_hedge_fund_data`, `bis_statistics`, `imf_weo_forecasts`, `sec_*` tables, `sec_insider_transactions`, `esma_funds`, `esma_managers`, `instruments_universe`, `nav_timeseries`, `sec_fund_prospectus_returns`, `sec_fund_prospectus_stats`, `fund_risk_metrics` have NO `organization_id`, NO RLS. They are shared across all tenants.
- **`fund_risk_metrics`** is GLOBAL — pre-computed by `global_risk_metrics` worker (lock 900_071) for ALL active instruments in `instruments_universe`, including DTW drift (by strategy_label), 5Y/10Y annualized returns. `organization_id` column is nullable (NULL for global rows). RLS is disabled (hypertable compression incompatible). All tenants see the same risk metrics. Org-scoped `risk_calc` (lock 900_007) computes org-specific overrides (no DTW — handled globally). Routes must NOT filter by `organization_id` when reading risk metrics.
- **`instruments_universe`** is a GLOBAL catalog (no RLS). Org-scoped instrument selection is via `instruments_org` (has RLS, `organization_id`, `block_id`, `approval_status`). The `Instrument` model has NO `organization_id`, `block_id`, or `approval_status` — those live on `InstrumentOrg`. All queries needing org-scoped instruments must JOIN `instruments_org`.
- **`nav_timeseries`** is GLOBAL (no RLS, no `organization_id`). Prices are market data shared across all tenants. Org-scoping for NAV queries is via JOIN `instruments_org`.
- **No module-level asyncio primitives:** Create `Semaphore`, `Lock`, `Event` lazily inside async functions. Module-level causes "attached to different event loop" errors.
- **ORM thread safety:** Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped). `SET` leaks across pooled connections.
- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API.
- **No custom tenant/user admin UI:** Tenant (Organization) and user management is 100% Clerk Dashboard. Do not build CRUD screens for creating tenants, inviting users, or assigning roles. `ConfigService` defaults handle new tenants automatically.
- **ConfigService for all config:** Never read `calibration/` or `profiles/` YAML at runtime. Use `ConfigService.get(vertical, config_type, org_id)`. YAML files are seed data only.
- **Prompts are Netz IP:** Never expose prompt content in client-facing API responses. Use `CLIENT_VISIBLE_TYPES` allowlist in ConfigService. Use `jinja2.SandboxedEnvironment` for all prompt rendering.
- **StorageClient for all storage:** Never call R2/ADLS SDK directly. Use `StorageClient` abstraction (`create_storage_client()` resolves R2 > ADLS > LocalStorage based on feature flags).
- **Dual-write ordering:** StorageClient write (source of truth) BEFORE pgvector upsert (derived index). If storage write fails, pipeline continues with warning. If pgvector upsert fails, data is safe in storage and can be rebuilt via `search_rebuild.py`.
- **Path routing via `storage_routing.py`:** Never build storage paths with f-strings in callers. Use `bronze_document_path()`, `silver_chunks_path()`, `silver_metadata_path()`, `gold_memo_path()`. All paths validated with `_SAFE_PATH_SEGMENT_RE`.
- **Parquet schema must include embedding metadata:** All silver layer Parquet files must have `embedding_model` and `embedding_dim` columns. `search_rebuild.py` validates dimension match before upserting — prevents silent corruption on model upgrade.
- **`organization_id` in vector search:** Credit `vector_chunks`: all queries MUST include `WHERE organization_id = :org_id`. Wealth `wealth_vector_chunks`: org-scoped queries use `WHERE organization_id = :org_id`; global queries (brochure, ESMA) do NOT filter by org_id (data is shared, org_id is NULL). All Parquet DuckDB queries MUST include `WHERE organization_id = ?`. Never query without tenant filter on tenant-scoped data.
- **No Cohere dependency:** Hybrid classifier (rules → cosine_similarity → LLM) replaced Cohere Rerank. Cross-encoder reranker (`local_reranker.py`) replaced Cohere for IC memo evidence. Zero external ML API calls for classification.
- **DB-first for external data:** All time-series external data (FRED, Treasury, OFR, Yahoo Finance, SEC EDGAR) is ingested by background workers into TimescaleDB hypertables. Routes and vertical engines read from DB only — never call external APIs in user-facing requests. Workers use `pg_try_advisory_lock(ID)` with deterministic lock IDs (never `hash()`), unlock in `finally`.
- **SEC data providers — DB-only in hot path:** `data_providers/sec/` services expose both DB-only reads and EDGAR API calls. Routes and DD reports must use ONLY DB-only methods: `ThirteenFService.read_holdings()`, `read_holdings_for_date()`, `get_sector_aggregation()`, `get_concentration_metrics()`, `compute_diffs()`; `AdvService.fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()`; `InstitutionalService.read_investors_in_manager()`. NEVER call `fetch_holdings()` (triggers EDGAR) or `discover_institutional_filers()` (triggers EFTS) from user-facing code — those are for `sec_13f_ingestion` and `sec_adv_ingestion` workers only.
- **Frontend formatter discipline:** All number/date/currency formatting MUST use formatters from `@netz/ui` (`formatNumber`, `formatCurrency`, `formatPercent`, `formatDate`, `formatDateTime`, `formatShortDate`, etc.). Never use `.toFixed()`, `.toLocaleString()`, or inline `new Intl.NumberFormat`/`Intl.DateTimeFormat` in frontend code. Enforced by `frontends/eslint.config.js`.

## Vertical Engines

Two-layer architecture: universal core (`ai_engine/`) + vertical specializations (`vertical_engines/`).

- `ai_engine/` — domain-agnostic: unified pipeline, hybrid classification, extraction, chunking, embedding, OCR, governance, validation, storage routing, search rebuild. Never modified per vertical.
- `vertical_engines/{vertical}/` — domain-specific: analysis logic, prompts, scoring. One directory per asset class.
- `vertical_engines/credit/` — 12 modular packages (Wave 1 complete, PR #9-#19). Each package has `models.py`, `service.py`, and domain helpers. `service.py` is the entry point; helpers must NOT import from `service.py` (enforced by import-linter).
- `vertical_engines/wealth/` — 15 modular packages (dd_report, long_form_report, fact_sheet, screener, correlation, attribution, fee_drag, monitoring, watchlist, mandate_fit, peer_group, rebalancing, asset_universe, model_portfolio, critic) + 6 standalone engines (fund_analyzer, macro_committee_engine, quant_analyzer, flash_report, investment_outlook, manager_spotlight). Each package follows same structure as credit: `models.py`, `service.py`, domain helpers.
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
| `instrument_ingestion` | 900_010 | global | `nav_timeseries` | Yahoo Finance (or pluggable provider) | Daily |
| `global_risk_metrics` | 900_071 | global | `fund_risk_metrics` | Computed (CVaR, Sharpe, volatility, momentum, scoring, DTW drift by strategy_label, 5Y/10Y returns) for ALL instruments_universe | Daily |
| `risk_calc` | 900_007 | org | `fund_risk_metrics` | Org-specific metric overrides for instruments in instruments_org (no DTW — handled globally) | Daily |
| `portfolio_eval` | 900_008 | org | `portfolio_snapshots` | Computed (breach status, regime, cascade) | Daily |
| `nport_ingestion` | 900_018 | global | `sec_nport_holdings` (3mo chunks) | SEC EDGAR N-PORT XML | Weekly |
| `sec_13f_ingestion` | 900_021 | global | `sec_13f_holdings`, `sec_13f_diffs` | SEC EDGAR 13F-HR (edgartools) | Weekly |
| `sec_adv_ingestion` | 900_022 | global | `sec_managers`, `sec_manager_funds` | SEC FOIA bulk CSV | Monthly |
| `bis_ingestion` | 900_014 | global | `bis_statistics` (1yr chunks) | BIS SDMX API (credit gap, DSR, property) | Quarterly |
| `imf_ingestion` | 900_015 | global | `imf_weo_forecasts` (1yr chunks) | IMF DataMapper API (GDP, inflation, fiscal) | Quarterly |
| `drift_check` | 42 | org | `strategy_drift_alerts` | Computed (DTW drift) | Daily |
| `portfolio_nav_synthesizer` | 900_030 | org | `model_portfolio_nav` (1mo chunks) | Computed (weighted NAV from nav_timeseries) | Daily |
| `nport_fund_discovery` | 900_024 | global | `sec_registered_funds`, `sec_fund_classes` | SEC EDGAR N-PORT headers | Weekly |
| `esma_ingestion` | — | global | `esma_funds`, `esma_managers` | ESMA Fund Register | Weekly |
| `wealth_embedding` | 900_041 | global | `wealth_vector_chunks` | OpenAI text-embedding-3-large (12 sources) | Daily |
| `sec_bulk_ingestion` | 900_050 | global | sec_etfs, sec_bdcs, sec_money_market_funds, sec_mmf_metrics, sec_registered_funds, strategy_label | SEC DERA bulk ZIPs (N-CEN, N-MFP, N-PORT, BDC) | Quarterly |
| `form345_ingestion` | 900_051 | global | `sec_insider_transactions`, `sec_insider_sentiment` (MV) | SEC EDGAR Form 345 bulk TSV (insider buys/sells) | Quarterly |
| `sec_xbrl_facts_ingestion` | 900_060 | global | `sec_xbrl_facts` | SEC XBRL Company Facts bulk (local) | On-demand (local dev) |
| ~~`equity_characteristics_compute`~~ | ~~900_091~~ | global | `equity_characteristics_monthly` | _Removed — Tiingo worker deprecated. XBRL × nav replacement tracked in #286 (PR-Q8)._ | _pending_ |
| `ipca_estimation` | 900_092 | global | `factor_model_fits` | Computed (Kelly-Pruitt-Su IPCA model on 6 chars) | Quarterly |
| `universe_sync` | 900_070 | global | `instruments_universe` | SEC/ESMA catalog (auto-fetches company_tickers_mf.json) | Weekly |
| `library_index_rebuild` | 900_080 | org | `wealth_library_index` | Self-heal cross-check via EXCEPT/MINUS vs source tables | Nightly |
| `library_pins_ttl` | 900_081 | org | `wealth_library_pins` | Prune `recent` pins > 20 per user | 6h |
| `library_bundle_builder` | 900_082 | org | `wealth_library_index`, R2 storage | On-demand Committee Pack ZIP + manifest + SSE emit | On-demand |
| `live_price_poll` | 900_100 | org | Redis `live:px:v1` hash (TTL 180s) | Yahoo Finance batch quote (≤250 symbols/call) for instruments held by `live`/`paused` portfolios; emits `price_staleness` alerts | 60s |
| `construction_run_executor` | 900_101 | org | `portfolio_construction_runs`, `portfolio_stress_results` | Computed (optimizer cascade + stress + advisor + validation + Jinja2 narrative); bound at 120s | On-demand |
| `alert_sweeper` | 900_102 | org | `portfolio_alerts` | Auto-dismiss stale open alerts past `auto_dismiss_at`; keeps the partial index small | Hourly |

**Materialized views** (migration 0078-0079): `mv_unified_funds` (6-universe fund catalog with prospectus stats), `mv_unified_assets` (global instrument search), `mv_macro_latest` (latest macro indicator values), `mv_macro_regional_summary` (regional macro aggregation). Refreshed by `view_refresh.py` (screener views, after universe_sync) and `macro_view_refresh.py` (macro views, after macro/treasury ingestion). Workers call refresh after data ingestion.

**Credit market_data** reads all macro data from `macro_data` hypertable (zero FRED API calls at runtime, `fred_client.py` eliminated). Regional Case-Shiller (20 metros) also from `macro_data`.

**Momentum signals** (RSI, Bollinger, OBV flow) are pre-computed by `global_risk_metrics` worker into `fund_risk_metrics` columns (`rsi_14`, `bb_position`, `nav_momentum_score`, `flow_momentum_score`, `blended_momentum_score`). Scoring route reads pre-computed values — no in-request TA-Lib computation. Risk metrics are GLOBAL — all tenants see the same pre-computed scores for any fund in the catalog, without needing to import it first.

**Analytics caching:** `POST /analytics/optimize` results cached in Redis (SHA-256 of inputs including date, 1h TTL). `POST /analytics/optimize/pareto` runs as background job with SSE progress (returns 202 immediately).

## Fund-Centric Model (Three-Universe Architecture)

The engine is organized around **funds as the primary analytical entity**. Three heterogeneous data sources are unified into a single polymorphic catalog:

| Universe | Source | PK | Table | Holdings | NAV |
|----------|--------|-----|-------|----------|-----|
| `registered_us` | SEC N-PORT | CIK | `sec_registered_funds` | N-PORT quarterly | Yahoo Finance via ticker |
| `etf` | SEC N-CEN | series_id | `sec_etfs` | N-PORT quarterly | Yahoo Finance via ticker |
| `bdc` | SEC N-CEN | series_id | `sec_bdcs` | N-PORT quarterly | Yahoo Finance via ticker |
| `money_market` | SEC N-MFP | series_id | `sec_money_market_funds` | N-MFP monthly | Stable NAV |
| `private_us` | ADV Schedule D | UUID | `sec_manager_funds` | None | None |
| `ucits_eu` | ESMA Register | ISIN | `esma_funds` | None | Yahoo Finance via ticker |

**Catalog query:** Reads from `mv_unified_funds` materialized view (migration 0078). The view consolidates 6 universe branches (registered, ETF, BDC, private, UCITS, MMF) with prospectus stats and share class data into a single pre-computed layer. `catalog_sql.py` applies filters/pagination on top of the view. `mv_unified_assets` provides global instrument search across instruments_universe, ESMA, and SEC CUSIP map. Both views refreshed by `view_refresh.py` service.

**Share classes:** `sec_fund_classes` (CIK → series_id → class_id → ticker). One fund CIK can have multiple series, each with multiple share classes.

**DisclosureMatrix:** Computed at SQL level per-universe branch. Frontend checks `disclosure.has_holdings` (not `universe === "registered_us"`). Drives all conditional rendering.

**Fund lifecycle:** Discovery (workers) → Catalog browsing (`instruments_universe`, global) → Import to org (`instruments_org`, org-scoped) → 3-layer screening → DD Report (8 chapters) → Universe approval → Portfolio construction.

**Identifier architecture:** Fund CIK ≠ Adviser CIK. `crd_number` links them. `instrument.attributes.sec_cik` and `instrument.attributes.sec_crd` bridge tenant-scoped instruments to global SEC tables.

**Private fund classification (`sec_manager_funds`):** Two-column taxonomy:
- `fund_type` — SEC Form ADV Q10 categories (7 values: Hedge Fund, Private Equity Fund, Venture Capital Fund, Real Estate Fund, Securitized Asset Fund, Liquidity Fund, Other Private Fund). Extracted via **checkbox image xref detection** in ADV Part 1 PDFs (checked checkbox uses a different JPEG xref than unchecked).
- `strategy_label` — 37 granular strategy categories (Private Credit, Infrastructure, Multi-Strategy, Long/Short Equity, Growth Equity, Buyout, etc.). Derived by 3-layer keyword classifier: (1) fund name regex, (2) hedge sub-strategy refinement, (3) brochure content enrichment. Script: `backend/scripts/backfill_strategy_label.py` (idempotent).
- **AUM floor:** Embedding worker (`_embed_sec_private_funds`) only processes managers with combined GAV ≥ $1B (2,087 managers, 45,942 funds).

**Dedicated vehicle tables (migration 0064):** `sec_etfs` (985, PK series_id), `sec_bdcs` (196, PK series_id, default strategy='Private Credit'), `sec_money_market_funds` (373, PK series_id, mmf_category CHECK), `sec_mmf_metrics` (hypertable, 20k daily metrics). `sec_registered_funds` now only mutual_fund/closed_end/interval_fund. Seed scripts in `scripts/seed_*.py`.

**N-CEN enrichment (migration 0065):** 27 new columns on `sec_registered_funds` from N-CEN filings (flags, LEI, fees, AUM). 2,232/3,652 MFs (61.1%). N-CEN `MANAGEMENT_FEE` only for closed-end/interval — open-end expense ratios from XBRL.

**XBRL fee enrichment (migration 0066):** 11 new columns on `sec_fund_classes` from N-CSR XBRL (OEF taxonomy): `expense_ratio_pct`, `advisory_fees_paid`, `avg_annual_return_pct`, `net_assets`, `holdings_count`, `portfolio_turnover_pct`, `perf_inception_date`, etc.

**Fund enrichment at import:** `import_sec_security()` enriches attributes with N-CEN flags + XBRL fees via multi-table lookup (SecRegisteredFund → SecFundClass → SecEtf → SecBdc → SecMMF). Attributes: `strategy_label`, `is_index`, `is_target_date`, `is_fund_of_fund`, `expense_ratio_pct`, `holdings_count`, `portfolio_turnover_pct`, `sec_crd`, `fund_inception_date`. Flows into screening/scoring/DD/fee_drag. Layer 1 can add eliminatory rules on enriched attributes without code changes.

**Fund scoring model (6 default components, sum = 1.0):** `quant_engine/scoring_service.py`. Lipper removed (provider never contracted). `fee_efficiency` is a default component (weight 0.10). `insider_sentiment` is opt-in (add weight > 0 in scoring config to activate). Formula: `fee_efficiency = max(0, 100 - expense_ratio_pct * 50)` — 0% ER → 100, 2% ER → 0, None → 50 (neutral). Components: `return_consistency` (0.20), `risk_adjusted_return` (0.25), `drawdown_control` (0.20), `information_ratio` (0.15), `flows_momentum` (0.10), `fee_efficiency` (0.10).

## Quant Upgrade (Sprints 1-3, 2026-03-27)

Portfolio construction is an 11-step pipeline with CLARABEL 4-phase cascade optimizer:

- **Black-Litterman** expected returns (prior + IC views from `portfolio_views` table)
- **Ledoit-Wolf shrinkage** on covariance matrix
- **Regime-conditioned covariance** (short window in stress, long in normality)
- **Robust optimization** (Phase 1.5 — ellipsoidal uncertainty sets, SOCP)
- **Regime CVaR multipliers** (RISK_OFF=0.85, CRISIS=0.70)
- **Turnover penalty** (L1 slack variables)
- **PCA factor decomposition** (`factor_model_service.py`)
- **GARCH(1,1)** conditional volatility per fund (`garch_service.py`, `arch>=7.0`)
- **Stress testing** — 4 parametric scenarios (GFC, COVID, Taper, Rate Shock) via `POST /stress-test`

**Optimizer cascade:** Phase 1 (max risk-adj return) → Phase 1.5 (robust SOCP) → Phase 2 (variance-capped) → Phase 3 (min-variance) → heuristic fallback. CLARABEL → SCS solver fallback per phase.

**New columns in `fund_risk_metrics`** (migration 0058): `volatility_garch`, `cvar_95_conditional`.

**Reference docs:** `docs/reference/portfolio-construction-reference-v2-post-quant-upgrade.md`, `docs/reference/institutional-portfolio-lifecycle-reference.md`.

## Wealth Vector Embedding (2026-03-27)

Separate vector table `wealth_vector_chunks` for fund-centric RAG (distinct from credit's deal-centric `vector_chunks`).

**16 embedding sources:** Global `"firm"`: ADV brochures, SEC manager profiles, 13F summaries, private funds (GAV ≥ $1B). Global `"fund"`: SEC fund profiles (N-CEN+XBRL), ESMA funds, ETFs, BDCs, MMFs, prospectus stats/returns, N-PORT holdings, share classes. Org-scoped: DD chapters (`"fund"`), macro reviews (`"macro"`).

**entity_type values:** `"firm"` (RIA/ManCo), `"fund"` (instrument), `"macro"` (review). NEVER `"manager"` — manager = PM individual in the system.

**Search functions** in `pgvector_search_service.py`:
- `search_fund_firm_context_sync()` — firm context via `sec_crd` or `esma_manager_id`
- `search_esma_funds_sync()` — semantic UCITS fund search
- `search_fund_analysis_sync()` — org-scoped DD chapters + macro reviews

**Worker:** `wealth_embedding_worker` (lock 900_041, daily 03:00 UTC). Incremental — processes only pending rows.

**No RLS on table** — `organization_id` nullable (global SEC/ESMA data). WHERE-clause filtering in all queries.

**Reference docs:** `docs/reference/wealth-vector-embedding-reference.md`, `docs/reference/wealth-vector-embedding-spec.md`.

## Environment Variables

`DATABASE_URL`, `REDIS_URL`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-large`, `MISTRAL_API_KEY`, `FEATURE_R2_ENABLED`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_ENDPOINT_URL`. All Azure env vars deprecated (2026-03-18) — replaced by OpenAI direct, pgvector, R2, Railway secrets, Redis, structlog.

## Clerk SvelteKit SDK Note

No official Clerk SvelteKit SDK exists. Use community packages: `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). These may lag behind Clerk API changes. Fallback: manual JWT verification on server (`clerk_auth.py`) + `svelte-clerk` for UI only.

## Skills

Custom skills live in `.claude/skills/`. Each subfolder contains a `SKILL.md` with frontmatter (`name`, `description`) that describes when to use it. **Do not maintain a hardcoded list here.** To discover available skills, glob `.claude/skills/**/SKILL.md` and read the frontmatter to find the best match for the current task. Invoke via the `Skill` tool or `/skill-name`.

## Infrastructure (Milestone 2 — up to 50 tenants)

Simplified stack (2026-03-18), ~$100-200/month:
- **Timescale Cloud** — managed PostgreSQL 16 (pgvector + TimescaleDB nativo)
- **Railway** — container hosting (FastAPI backend + 2 SvelteKit frontends)
- **Upstash** — serverless Redis (SSE pub/sub, job tracking, worker idempotency, advisory locks)
- **OpenAI API** (direct, with retry backoff) — LLM + embeddings
- **Mistral** — OCR
- **Clerk** — auth (JWT v2)
- **StorageClient** — LocalStorageClient (dev, filesystem at `.data/lake/`), R2StorageClient (prod target, Cloudflare R2 S3-compatible)

Azure services deprecated (2026-03-18, files kept for rollback): Key Vault → Railway secrets, Service Bus → Redis, App Insights → structlog, Azure OpenAI → OpenAI direct, AI Search → pgvector, ADLS → R2. Scale triggers (>50 tenants): Vault for SOC2, Redis Streams for guaranteed delivery, APM for distributed tracing, Qdrant if pgvector bottlenecks at 10M+ chunks.

## Deployment

- **Backend:** `railway.toml` at repo root. Health check: `/health` and `/api/health`. Production: `api.investintell.com` (Railway Pro).
- **Frontend Wealth:** Production: `wealth.investintell.com` (Railway Pro).
- **Frontend Credit:** Railway (SvelteKit `adapter-node`).
- **Database:** Timescale Cloud managed PostgreSQL 16 with pgvector + TimescaleDB. Alembic uses `DIRECT_DATABASE_URL` (port 5432, not pooler).
- **Local dev:** `docker-compose up` (PostgreSQL 16 + TimescaleDB + pgvector + Redis 7).
- **Deploy checklist:** `docs/reference/deploy-checklist.md` — full validation sequence for Railway Pro + Timescale Cloud.

## Origins

Plans in `docs/plans/`, brainstorms in `docs/brainstorms/`, references in `docs/reference/`. Key docs: `fund-centric-model-reference.md`, `portfolio-construction-reference-v2-post-quant-upgrade.md`, `institutional-portfolio-lifecycle-reference.md`, `wealth-vector-embedding-reference.md`, `deploy-checklist.md`. Archived repos: `Netz-Private-Credit-OS`, `netz-wealth-os` (both in `C:\Users\andre\projetos\`).


## Svelte MCP

When working on any SvelteKit frontend (`frontends/credit/` or `frontends/wealth/`), the Svelte MCP server is available for documentation lookup and code validation.

Remote: `https://mcp.svelte.dev/mcp`. Local: `npx @sveltejs/mcp {list-sections|get-documentation|svelte-autofixer}`. Rules: run `list-sections` first, run `svelte-autofixer` before finalizing components, use `fetch()+ReadableStream` for SSE (never EventSource), Svelte 5 runes (`$state`, `$derived`, `$effect`) — escape `$` as `\$` in terminal.

## UX Sprint 7 — Scope Decisions (2026-03-19)

### C.3 — Portfolio deal-level fields: NOT IMPLEMENTED
Portfolio is asset-centric post-conversion. Tenor/basis/covenant are deal-level (`deal_context.json`), NOT asset attributes. Do not add them to portfolio view — use "Source Deal" link instead.

### C.4 — Kanban: IMPLEMENTED
`PipelineKanban.svelte` with `svelte-dnd-action@^0.9.0`. 8 stages, drag-drop + ConsequenceDialog, PATCH `/pipeline/deals/{deal_id}/stage`.

## Audit Trail

Immutable audit logging via `write_audit_event()` in `backend/app/core/db/audit.py`. Records CREATE/UPDATE/DELETE with before/after JSONB snapshots, correlated via `request_id`. Model: `AuditEvent` in `backend/app/core/db/models.py` (RLS-scoped). Used across 17+ modules for entity-level change tracking.
