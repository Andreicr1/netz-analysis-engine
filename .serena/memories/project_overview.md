# Netz Analysis Engine - Project Overview

Netz Analysis Engine is a unified multi-tenant institutional investment analysis engine for asset/wealth management and private credit workflows. The project should be approached as a high-end asset/wealth management engineering system: correctness, auditability, tenant isolation, deterministic analytics, and operational safety matter.

Product scope is analytical only: credit deals/portfolio/documents/reporting/dashboard/global agent and wealth analytics/portfolio construction/screener/research. Operational modules such as cash management, signatures, counterparties, bank reconciliation, and tenant/user CRUD are intentionally out of scope and should not be reintroduced.

Primary stack:
- Python 3.12 backend with FastAPI, async SQLAlchemy/asyncpg, Pydantic v2, Alembic, structlog, Redis, SSE via `sse-starlette`.
- PostgreSQL 16 + TimescaleDB + pgvector; local dev via docker-compose, production via Timescale Cloud. Redis local via Docker, production via Upstash.
- Quant stack includes pandas, scipy, cvxpy, statsmodels, arch, aeon, IPCA, lmoments3, matplotlib, reportlab.
- AI/data pipeline stack includes OpenAI, Jinja2 prompts, pgvector, DuckDB/Parquet, SEC EDGAR providers, local fallback providers.
- Frontend monorepo uses pnpm 10.28.1, Turborepo v2, SvelteKit 2/Svelte 5/Vite 6/TypeScript/Tailwind 4, Playwright, Vitest, ESLint.

Important concepts:
- Auth is Clerk JWT v2. `organization_id` comes from `o.id`; dev bypass uses `X-DEV-ACTOR` / dev token. Tenant/user management is handled in Clerk Dashboard, not custom UI.
- Runtime config comes from DB via ConfigService. `profiles/` and `calibration/` YAML are seed data only, not runtime config sources.
- External time-series and SEC/market data are DB-first: workers ingest into TimescaleDB/global tables; user-facing routes and vertical engines should read DB-only methods, not call external APIs in hot paths.
- Data lake writes go through StorageClient abstraction. Local dev defaults to `.data/lake/`; production target is Cloudflare R2. ADLS is deprecated and kept only for compatibility/rollback.
- Prompts are Netz IP and must not be exposed via client-facing API responses.

Repository state at onboarding: worktree had pre-existing modifications/untracked docs and `.serena/`; do not revert unrelated user changes.