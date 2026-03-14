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
      credit/       ← from netz-private-credit-os (112 tables, 10 modules)
      wealth/       ← from netz-wealth-os (12 tables, 7 services)
    shared/         ← enums, exceptions, middleware
  ai_engine/        ← IC memos, extraction, ingestion, validation, prompts
  quant_engine/     ← CVaR, regime, optimizer, scoring, drift, rebalance
  worker_app/       ← Azure Functions + CLI workers
profiles/           ← YAML analysis profiles (private_credit, liquid_funds)
calibration/        ← YAML quant configs (blocks, limits, scoring)
packages/ui/        ← @netz/ui (Tailwind tokens, shadcn-svelte, layouts)
frontends/
  credit/           ← SvelteKit "netz-credit-intelligence"
  wealth/           ← SvelteKit "netz-wealth-os"
```

**Database:** PostgreSQL 16 + TimescaleDB + Redis 7. Migrations via Alembic (sync psycopg). App uses async asyncpg.

**Auth:** Clerk JWT v2. `organization_id` from `o.id` claim. RLS via `SET LOCAL app.current_organization_id`. Dev bypass: `X-DEV-ACTOR` header.

**SSE:** `sse-starlette` EventSourceResponse. Redis pub/sub for worker→SSE bridging. Frontend uses `fetch()` + `ReadableStream` (not EventSource — auth headers needed).

## Critical Rules

- **Async-first:** All DB operations use `AsyncSession`. Never use sync `Session` in route handlers.
- **expire_on_commit=False:** Always. Prevents implicit I/O in async context.
- **lazy="raise":** Set on ALL relationships. Forces explicit `selectinload()`/`joinedload()`.
- **RLS subselect:** All RLS policies must use `(SELECT current_setting(...))` not bare `current_setting()`. Without subselect, per-row evaluation causes 1000x slowdown.
- **Global tables:** `macro_data`, `allocation_blocks` have NO `organization_id`, NO RLS. They are shared across all tenants.
- **No module-level asyncio primitives:** Create `Semaphore`, `Lock`, `Event` lazily inside async functions. Module-level causes "attached to different event loop" errors.
- **ORM thread safety:** Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped). `SET` leaks across pooled connections.
- **Frontends never cross-import:** `frontends/credit/` and `frontends/wealth/` share only via `@netz/ui` and the backend API.

## Clerk SvelteKit SDK Note

No official Clerk SvelteKit SDK exists. Use community packages: `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). These may lag behind Clerk API changes. Fallback: manual JWT verification on server (`clerk_auth.py`) + `svelte-clerk` for UI only.

## Origins

- **Brainstorm:** `docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md`
- **Plan:** `docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md`
- **Private Credit OS:** `C:\Users\andre\projetos\Netz-Private-Credit-OS` (archived after data migration)
- **Wealth OS:** `C:\Users\andre\projetos\netz-wealth-os` (archived after migration)
