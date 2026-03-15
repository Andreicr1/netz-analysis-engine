# CLAUDE.md — Netz Analysis Engine

Unified multi-tenant analysis engine for institutional investment verticals.

## Commands

```bash
make check              # Full gate: lint + typecheck + test
make test               # pytest backend/tests/
make test ARGS="-k foo" # Run a single test or subset
make lint               # ruff check
make typecheck          # mypy
make serve              # uvicorn on :8000
make migrate            # alembic upgrade head
make migration MSG="…"  # Generate new migration
make up                 # docker-compose up -d (PG 16 + TimescaleDB + Redis 7)
make down               # docker-compose down
```

## Architecture

```
backend/
  app/
    core/           ← auth (Clerk), tenancy (RLS), DB (asyncpg), config, jobs (SSE)
    domains/
      credit/       ← analytical modules only (deals, portfolio, documents, reporting, dashboard, dataroom, actions, global_agent)
      wealth/       ← from netz-wealth-os (12 tables, 7 services)
    shared/         ← enums, exceptions
  ai_engine/        ← IC memos, extraction, ingestion, validation, prompts, governance
  quant_engine/     ← CVaR, regime, optimizer, scoring, drift, rebalance
  worker_app/       ← Azure Functions + CLI workers + knowledge_aggregator + outcome_recorder
profiles/           ← YAML analysis profiles (private_credit, liquid_funds)
calibration/        ← YAML quant configs (blocks, limits, scoring)
packages/ui/        ← @netz/ui (Tailwind tokens, shadcn-svelte, layouts)
frontends/
  credit/           ← SvelteKit "netz-credit-intelligence"
  wealth/           ← SvelteKit "netz-wealth-os"
```

**Database:** PostgreSQL 16 + TimescaleDB + Redis 7. Migrations via Alembic. App uses async asyncpg. Current migration head: `0002_wealth_domain` (0003_credit_domain pending).

**Auth:** Clerk JWT v2. `organization_id` from `o.id` claim. RLS via `SET LOCAL app.current_organization_id`. Dev bypass: `X-DEV-ACTOR` header.

**SSE:** `sse-starlette` EventSourceResponse. Redis pub/sub for worker→SSE bridging. Frontend uses `fetch()` + `ReadableStream` (not EventSource — auth headers needed).

**Data Lake (ADLS Gen2):** Feature-flagged (`FEATURE_ADLS_ENABLED=false`). Bronze/silver/gold hierarchy with `{organization_id}/` as first path segment. DuckDB queries ADLS directly for analytics. Local dev uses PostgreSQL only.

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
- **Global tables:** `macro_data`, `allocation_blocks` have NO `organization_id`, NO RLS. They are shared across all tenants.
- **No module-level asyncio primitives:** Create `Semaphore`, `Lock`, `Event` lazily inside async functions. Module-level causes "attached to different event loop" errors.
- **ORM thread safety:** Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped). `SET` leaks across pooled connections.
- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API.

## Data Lake Rules (ADLS Gen2)

1. `{organization_id}/` is ALWAYS the first path segment under `bronze/` and `silver/`
2. `_global/` is for data with no tenant context — FRED macro, ETF benchmarks
3. `macro_data` PostgreSQL table = operational use (regime detection, daily pipeline)
4. `gold/_global/fred_indicators/` = analytics use (backtesting, cross-fund correlation)
5. All workers must write Parquet with `organization_id` as a column AND as a path segment
6. DuckDB queries must always include `WHERE organization_id = ?` even when path already isolates
7. TimescaleDB hypertables: `compress_segmentby = 'organization_id'` on all hypertables

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
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=

# Data Lake (disabled by default — local dev uses PG only)
FEATURE_ADLS_ENABLED=false
ADLS_ACCOUNT_NAME=
ADLS_ACCOUNT_KEY=
ADLS_CONTAINER_NAME=netz-analysis
ADLS_CONNECTION_STRING=
```

## Clerk SvelteKit SDK Note

No official Clerk SvelteKit SDK exists. Use community packages: `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). These may lag behind Clerk API changes. Fallback: manual JWT verification on server (`clerk_auth.py`) + `svelte-clerk` for UI only.

## Origins

- **Plan:** `docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md`
- **Brainstorm:** `docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md`
- **Private Credit OS:** `C:\Users\andre\projetos\Netz-Private-Credit-OS` (archived after data migration)
- **Wealth OS:** `C:\Users\andre\projetos\netz-wealth-os` (archived after migration)
