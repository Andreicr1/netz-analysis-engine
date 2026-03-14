---
title: "feat: Netz Analysis Engine — Unified Multi-Tenant Platform"
type: feat
status: active
date: 2026-03-14
deepened: 2026-03-14
origin: docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md
---

# Netz Analysis Engine — Unified Multi-Tenant Platform

## Enhancement Summary

**Deepened on:** 2026-03-14
**Research agents used:** 6 (asyncpg migration, Clerk+SvelteKit, TimescaleDB+RLS, SSE+Redis, monorepo+migration, documented learnings)

### Key Improvements from Research
1. **RLS performance:** Must use `(SELECT current_setting(...))` subselect pattern in all policies — without it, per-row evaluation causes 1000x slowdown on large tables
2. **asyncpg migration:** Set `lazy="raise"` on ALL relationships as migration safety net — converts silent lazy-load errors into loud exceptions during testing
3. **SSE architecture:** Use `sse-starlette` library (not raw StreamingResponse) + `ChannelBroadcaster` for fan-out — reduces Redis connections from N-per-client to 1-per-channel
4. **Clerk JWT v2:** Organization data is in compact `o` claim (`o.id`, `o.rol`, `o.slg`) — must use API version 2025-04-10+
5. **TimescaleDB + RLS limitation:** Compressed chunks don't fully support RLS — must always include explicit `WHERE fund_id = :fid` on hypertable queries (defense in depth)
6. **Institutional learnings:** Three-phase session pattern (pre-fetch → async compute → post-write) proven in project; module-level `asyncio.Semaphore` causes event loop errors

### Critical Anti-Patterns to Avoid (from research)
| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| Lazy loading in async | `MissingGreenlet` error | `lazy="raise"` + explicit `selectinload()` |
| `current_setting()` without subselect | Per-row RLS evaluation, 1000x slower | `(SELECT current_setting(...))` |
| `SET` instead of `SET LOCAL` for RLS | Tenant context leaks across pooled connections | Always `SET LOCAL` in transaction |
| Missing `FORCE ROW LEVEL SECURITY` | Table owner bypasses all policies | Always `ALTER TABLE ... FORCE` |
| One Redis connection per SSE client | Pool exhaustion at 100+ clients | `ChannelBroadcaster` with in-process fan-out |
| Browser `EventSource` for SSE | Cannot send auth headers | `fetch()` + `ReadableStream` |
| Module-level `asyncio.Semaphore` | "attached to different event loop" error | Create lazily inside async functions |
| ORM objects crossing thread boundaries | `DetachedInstanceError` | Extract to frozen dataclasses before crossing |
| `expire_on_commit=True` (default) | Attribute access after commit fails in async | `expire_on_commit=False` always |

---

## Overview

Create `netz-analysis-engine` — a unified multi-tenant B2B SaaS backend merging two existing products (Netz Private Credit OS + Netz Wealth OS) into a single monorepo with two vertical SvelteKit frontends and a shared design system. Uses Wealth OS's superior tech stack as foundation (PG 16 + TimescaleDB + asyncpg + Redis 7 + Python 3.12). Both legacy repos are archived after migration.

**Origin:** See [brainstorm](../brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md) for full strategic context, risk register, and resolved questions.

## Problem Statement

Two separate products serve adjacent institutional investment verticals but share no infrastructure, no auth, no UI patterns. Maintaining them in parallel fragments engineering energy. The AI engine (Private Credit) and the quant engine (Wealth) are complementary but siloed. A commercial B2B SaaS opportunity requires multi-tenancy, which neither product supports.

## Proposed Solution

One monorepo. One backend. Two frontends. Monorepo during development (one CI, one backlog, one `make check`); frontends structured for trivial `git subtree split` when commercial contracts require isolation.

```
netz-analysis-engine/
├── backend/
│   ├── app/
│   │   ├── core/           ← auth (Clerk), tenancy (RLS), DB (asyncpg), config, jobs (SSE)
│   │   ├── domains/
│   │   │   ├── credit/     ← 112 tables, 10 domain modules (from Private Credit OS)
│   │   │   └── wealth/     ← 12 tables, 7 services (from Wealth OS)
│   │   └── shared/         ← exceptions, enums, middleware
│   ├── ai_engine/          ← IC memos, extraction, ingestion, validation, prompts
│   ├── quant_engine/       ← CVaR, regime, optimizer, scoring, drift, rebalance
│   └── worker_app/         ← Azure Functions (credit) + CLI workers (wealth)
├── profiles/               ← YAML analysis profiles (private_credit, liquid_funds)
├── calibration/            ← YAML quant configs (blocks, limits, scoring)
├── packages/ui/            ← @netz/ui (Tailwind tokens, shadcn-svelte, layouts)
├── frontends/
│   ├── credit/             ← SvelteKit (package.json name: "netz-credit-intelligence")
│   └── wealth/             ← SvelteKit (package.json name: "netz-wealth-os")
├── scripts/                ← data migration tooling
├── infra/bicep/            ← Azure IaC (PG 16 + TimescaleDB + Redis 7)
├── docker-compose.yml      ← local dev (PG 16 + TimescaleDB + Redis 7)
├── Makefile                ← make check runs everything
└── pyproject.toml          ← Python 3.12, ruff, mypy strict
```

## Technical Approach

### Architecture

**Database:** PostgreSQL 16 + TimescaleDB extension + Redis 7
- Standard tables for transactional data (deals, documents, compliance, allocations)
- TimescaleDB hypertables for time-series (nav_timeseries, fund_risk_metrics, audit_events)
- Redis for SSE pub/sub (job progress, risk streaming) and CVaR cache
- All tables have `organization_id UUID NOT NULL` from first migration (multi-tenancy from day one)
- Row-Level Security (RLS) policies enforce tenant isolation at DB level

**RLS Implementation (from research — critical performance patterns):**
```sql
-- MUST use subselect wrapper — without it, current_setting() evaluates per-row (1000x slower)
CREATE POLICY org_isolation ON deals
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
  WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));

-- MUST force RLS on table owner too
ALTER TABLE deals FORCE ROW LEVEL SECURITY;

-- Fail-closed guard function
CREATE OR REPLACE FUNCTION current_org_id() RETURNS uuid AS $$
BEGIN
  IF current_setting('app.current_organization_id', true) IS NULL THEN
    RAISE EXCEPTION 'Tenant context not set — aborting query';
  END IF;
  RETURN current_setting('app.current_organization_id')::uuid;
END;
$$ LANGUAGE plpgsql STABLE;
```

**RLS + TimescaleDB limitation:** Compressed hypertable chunks don't fully support RLS. Defense in depth: always include explicit `WHERE organization_id = :oid` in application queries on hypertables, plus `compress_segmentby = 'organization_id'` for efficient segment pruning on compressed data.

**Connection roles:** Alembic runs as DB owner (bypasses RLS). Application connects as `app_user` with `NOSUPERUSER NOBYPASSRLS`. `SET LOCAL app.current_organization_id` scoped to transaction only (safe for connection pooling).

**Global tables (NO RLS, NO organization_id):**
- `macro_data` — FRED indicators (VIX, yield curve, CPI) are global market data, identical for all tenants. Adding org_id would create unnecessary duplication and complex queries. RLS simply does not apply.
- `allocation_blocks` — Geography × asset class reference data, shared across all orgs.
- Any future reference/lookup tables with globally shared data follow this pattern.

**ORM:** SQLAlchemy 2.0 fully async + asyncpg
- `create_async_engine` with `postgresql+asyncpg://` (from Wealth OS `database.py:7-12`)
- `async_sessionmaker(expire_on_commit=False)` — **CRITICAL: must be False** to avoid implicit I/O after commit in async
- Dual connection strings: async (`postgresql+asyncpg://`) for app, sync (`postgresql+psycopg://`) for Alembic
- All `Mapped[]` + `mapped_column()` style (SA 2.0, no legacy `Column()`)

**Async migration safety net (from research):**
```python
# Set lazy="raise" on ALL relationships during migration
# Converts silent lazy-load errors into loud exceptions
class Deal(Base):
    fund = relationship("Fund", lazy="raise")        # Forces explicit loading
    documents = relationship("Document", lazy="raise")

# Every query that needs related data must use explicit eager loading
result = await session.execute(
    select(Deal).options(selectinload(Deal.fund), selectinload(Deal.documents))
)
```

**Pool configuration (from research + project learnings):**
```python
engine = create_async_engine(
    "postgresql+asyncpg://app_user@host/db",
    pool_size=20,          # Sizing: concurrent_requests_per_worker
    max_overflow=10,       # Burst capacity
    pool_pre_ping=True,    # CRITICAL for Azure (kills idle connections > 10 min)
    pool_recycle=300,       # Recycle every 5 min (Azure idle timeout)
    pool_timeout=30,
)
# Total connections per worker = pool_size + max_overflow = 30
# With 4 Uvicorn workers: 120 total connections (stay under PG max_connections=100+)
```

**Institutional learning (from `async-dag-orchestrator` solution):** Module-level `asyncio.Semaphore` causes "attached to different event loop" errors. All asyncio primitives must be created lazily inside async functions. ORM objects crossing thread boundaries cause `DetachedInstanceError` — extract scalar attributes into frozen dataclasses before crossing any async/thread boundary.

**Auth:** Clerk (replaces Azure Entra ID)
- Clerk JWT v2 (API version 2025-04-10+): org data in compact `o` claim
  ```json
  { "sub": "user_xxx", "o": { "id": "org_xxx", "rol": "org:admin", "slg": "acme-corp" } }
  ```
- JWKS caching via `PyJWKClient(cache_keys=True)` + manual `kid` rotation retry (adapted from Wealth OS `auth/dependencies.py:32-93`)
- `organization_id` = `decoded["o"]["id"]`, role = `decoded["o"]["rol"]`
- Server-side: `clerk-sveltekit` for route protection hooks; client-side: `svelte-clerk` for UI components (`<OrganizationSwitcher />`, `<UserButton />`)
- `X-DEV-ACTOR` dev bypass preserved
- Under 500 MAU — Clerk Pro tier (note: SAML SSO requires Enterprise tier for future clients)
- **No official Clerk SvelteKit SDK** — use community `clerk-sveltekit` (server hooks) + `svelte-clerk` (UI components). **Stability warning:** community packages may lag behind Clerk API changes or break on Svelte updates. If integration problems arise in Sprint 4, fallback: manual JWT verification on server (`clerk_auth.py` already handles this) + `svelte-clerk` for UI only. Document this in the engine repo's CLAUDE.md.

**SSE Streaming:** Redis pub/sub → `sse-starlette` EventSourceResponse
- Use `sse-starlette` library (NOT raw `StreamingResponse`) — handles event framing, id fields, retry hints, keepalive automatically
- `EventSourceResponse(generator, ping=15)` sends comment-line heartbeats every 15s (Azure Container Apps idle timeout = 30s)
- `ChannelBroadcaster` pattern for high fan-out: 1 Redis subscriber per unique channel per process, in-process `asyncio.Queue` fan-out to N clients (avoids N Redis connections)
- Frontend uses `fetch()` + `ReadableStream` (not `EventSource`) — `EventSource` cannot send `Authorization` headers (WHATWG spec limitation)
- IC memo streaming: sentence fragments buffered at ~50-100 chars or sentence boundaries (~2-5 events/sec)
- For `Last-Event-ID` replay: store events in Redis Streams (`XADD/XREAD`), not pub/sub (fire-and-forget)
- **Azure Container Apps gotcha:** Set `X-Accel-Buffering: no` header; if behind Azure API Management, disable `validate-content` policy on SSE endpoints

**Frontends:** SvelteKit 2 + TypeScript + Vite
- `@netz/ui` shared package: Tailwind CSS 4 tokens, shadcn-svelte components, FCL layout, sidebar
- Each frontend has own `package.json` with definitive name (enables future `git subtree split`)
- Frontends NEVER cross-import; share only via `@netz/ui` and backend API
- paraglide-js for compile-time i18n (credit frontend ports 880+ keys from UI5)

### Implementation Phases

---

#### Phase 1: Foundation (Sprint 0 — Week 1-2)

**Goal:** Repo scaffold with core infrastructure operational.

##### Tasks

- [ ] Create GitHub repo `netz-analysis-engine`
- [ ] **`docker-compose.yml`** — PG 16 (`timescale/timescaledb:latest-pg16`), Redis 7 (`redis:7-alpine`), healthchecks, named volume
  - Pattern: copy from `netz-wealth-os/docker-compose.yml`
- [ ] **`backend/app/core/db/engine.py`** — async SQLAlchemy engine factory
  ```python
  # Pattern from netz-wealth-os/backend/app/database.py:7-24
  engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=15)
  async_session = async_sessionmaker(engine, expire_on_commit=False)
  async def get_db() -> AsyncGenerator[AsyncSession, None]: ...
  ```
- [ ] **`backend/app/core/db/base.py`** — unified mixins
  ```python
  class IdMixin:           # UUID PK (from Private Credit base.py:19-25)
  class OrganizationScopedMixin:  # organization_id UUID NOT NULL (NEW)
  class FundScopedMixin:   # fund_id UUID + access_level (from Private Credit base.py:28-34)
  class AuditMetaMixin:    # created_at, updated_at, created_by, updated_by (from Private Credit base.py:37-51)
  ```
- [ ] **`backend/app/core/config/settings.py`** — merged Pydantic Settings
  - Combine Private Credit settings (Azure, OpenAI, Service Bus, etc.) + Wealth OS settings (feature flags, calibration path)
  - Add `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`
  - Remove `CANONICAL_FUND_ID`, `oidc_*` Entra vars
- [ ] **`backend/app/core/security/clerk_auth.py`** — Clerk JWT verification
  ```python
  # JWT v2 claim structure (API version 2025-04-10+)
  CLERK_JWKS_URL = "https://{domain}/.well-known/jwks.json"
  jwks_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True)

  async def verify_clerk_token(token: str) -> dict:
      signing_key = jwks_client.get_signing_key_from_jwt(token)
      decoded = jwt.decode(token, signing_key.key, algorithms=["RS256"],
                           options={"verify_aud": False})  # Clerk doesn't use aud
      org = decoded.get("o", {})
      return {
          "user_id": decoded["sub"],
          "org_id": org.get("id"),          # organization_id
          "org_role": org.get("rol"),        # "org:admin", "org:investment_team"
          "org_slug": org.get("slg"),
      }

  CLERK_TO_ROLE = {
      "org:admin": Role.ADMIN,
      "org:investment_team": Role.INVESTMENT_TEAM,
      "org:gp": Role.GP, "org:director": Role.DIRECTOR,
      "org:compliance": Role.COMPLIANCE, "org:auditor": Role.AUDITOR,
      "org:investor": Role.INVESTOR, "org:advisor": Role.ADVISOR,
  }
  ```
  - JWKS key rotation: 2-attempt loop (try cached → invalidate → retry)
  - Preserve `X-DEV-ACTOR` JSON header bypass for dev
- [ ] **`backend/app/core/tenancy/middleware.py`** — RLS context injection
  ```python
  # FastAPI dependency: SET LOCAL (transaction-scoped, safe for pooling)
  async def get_db_with_rls(
      org_id: uuid.UUID = Depends(get_org_id_from_clerk),
  ) -> AsyncGenerator[AsyncSession, None]:
      async with async_session_factory() as session:
          async with session.begin():
              await session.execute(
                  text("SET LOCAL app.current_organization_id = :oid"),
                  {"oid": str(org_id)},
              )
              yield session
  # RLS policy (use subselect for performance):
  # CREATE POLICY org_isolation ON {table}
  #   USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
  ```
- [ ] **`backend/app/core/jobs/tracker.py`** — Redis pub/sub job tracker
  - `publish_event(job_id, event_type, data)` → `PUBLISH job:{job_id} {json}`
- [ ] **`backend/app/core/jobs/sse.py`** — SSE stream generator
  - Pattern from Wealth OS `routers/risk.py:179-232`: subscribe, yield, heartbeat 15s
- [ ] **`backend/app/main.py`** — FastAPI app factory with lifespan
  - Health endpoint at `/health` and `/api/health`
  - Dual mount pattern: root + `/api` prefix (from Private Credit `main.py:301-328`)
- [ ] **`Makefile`** — `make check` (lint + typecheck + test), `make serve`, `make migrate`
- [ ] **`pyproject.toml`** — Python 3.12, ruff, mypy strict, pytest-asyncio
- [ ] **`.github/workflows/ci.yml`** — test against PG 16 + TimescaleDB service container
- [ ] **`profiles/private_credit/profile.yaml`** — initial schema (chapter definitions only)

##### Acceptance Criteria

- [ ] `docker-compose up` starts PG 16 + TimescaleDB + Redis 7
- [ ] `make serve` starts FastAPI on :8000, health endpoint responds
- [ ] Clerk JWT verification works (dev token mode)
- [ ] `organization_id` RLS context set per request
- [ ] SSE test endpoint streams events via Redis pub/sub
- [ ] `make check` passes (lint + typecheck + test)

##### Key Files

| File | Source | Notes |
|------|--------|-------|
| `docker-compose.yml` | `netz-wealth-os/docker-compose.yml` | Add TimescaleDB extension creation |
| `backend/app/core/db/engine.py` | `netz-wealth-os/backend/app/database.py` | Adapt for dual conn strings |
| `backend/app/core/db/base.py` | `netz-private-credit-os/backend/app/core/db/base.py` | Add OrganizationScopedMixin |
| `backend/app/core/security/clerk_auth.py` | `netz-wealth-os/backend/app/auth/dependencies.py` | Replace Entra with Clerk |
| `backend/app/core/config/settings.py` | Both projects merged | Remove Entra, add Clerk |

---

#### Phase 2: Wealth Domain Migration (Sprint 1 — Week 3-4)

**Goal:** All Wealth OS backend functionality operational in the unified engine.

##### Tasks

- [ ] **`backend/app/domains/wealth/models/`** — migrate all 12 tables
  - `fund.py` → `Fund` (funds_universe) + `organization_id`
  - `nav.py` → `NavTimeseries` (hypertable) + `organization_id`
  - `risk.py` → `FundRiskMetrics` (hypertable) + `organization_id`
  - `portfolio.py` → `PortfolioSnapshot` + `organization_id`
  - `allocation.py` → `StrategicAllocation`, `TacticalPosition` + `organization_id`
  - `block.py` → `AllocationBlock` + `organization_id`
  - `rebalance.py` → `RebalanceEvent` + `organization_id`
  - `macro.py` → `MacroData` + `organization_id`
  - `lipper.py` → `LipperRating` + `organization_id`
  - `backtest.py` → `BacktestRun` + `organization_id`
  - All models use unified `IdMixin`, `OrganizationScopedMixin`, `AuditMetaMixin`
- [ ] **`backend/quant_engine/`** — migrate 7 services
  - `cvar_service.py`, `regime_service.py`, `optimizer_service.py`, `scoring_service.py`
  - `drift_service.py`, `rebalance_service.py`, `talib_momentum_service.py`
  - All receive `AsyncSession` as parameter (pattern from `cvar_service.py:158`)
  - Pure functions separated from DB functions (pattern from `cvar_service.py:106`)
- [ ] **`backend/app/domains/wealth/routes/`** — 26 endpoints
  - funds, portfolios, allocation, risk (inc. SSE), analytics, workers
  - All routes get `organization_id` context from tenancy middleware
- [ ] **`backend/worker_app/wealth/`** — 7 CLI workers
  - ingestion, fred_ingestion, risk_calc, portfolio_eval, drift_check, bayesian_cvar, regime_fit
  - Entry: `asyncio.run()` with direct `async_session()` (pattern from `risk_calc.py:434`)
  - Also HTTP-triggered via workers router (pattern from Wealth OS `routers/workers.py`)
- [ ] **`calibration/`** — copy YAML configs from `netz-wealth-os/calibration/config/`
- [ ] **Alembic migration `0001_wealth_domain.py`**
  - Create all 12 tables with `organization_id`
  - Enable TimescaleDB extension
  - Create hypertables for nav_timeseries, fund_risk_metrics
  - CHECK constraints on all enums (profile, status, return_type)
- [ ] **Tests** — port Wealth OS tests, adapt for unified conftest
  - Use `httpx.AsyncClient` + `ASGITransport` (pattern from Wealth OS `conftest.py:7-11`)
  - PG 16 test database (NOT SQLite — asyncpg requires real PG)

##### Acceptance Criteria

- [ ] All 26 Wealth API endpoints return correct data
- [ ] TimescaleDB hypertables created and queryable
- [ ] `make pipeline` runs full daily pipeline (ingest → fred → risk → eval)
- [ ] SSE risk stream delivers CVaR updates via Redis
- [ ] All Wealth tests passing
- [ ] `make check` passes

---

#### Phase 3: Credit Domain Migration (Sprint 2 — Week 5-6)

**Goal:** All Private Credit OS domain models and routes operational, adapted to async + `organization_id`.

##### Critical Migration Notes

- **112 tables → async:** Every `Session` becomes `AsyncSession`, every `db.query()` becomes `await db.execute(select(...))`. SA 2.x already eliminated `db.query()` in Private Credit, but all handlers must become `async def`.
- **Mixin inconsistency:** Not all Private Credit models use mixins consistently (e.g., `Deal` defines its own `id`/`fund_id` — see research). Harmonize ALL models to use unified mixins.
- **Model imports in 3 places:** Private Credit has model imports manually maintained in `session.py`, `env.py`, and `conftest.py`. Consolidate to a single `models/__init__.py` that re-exports all.
- **JSONB columns:** Work natively with asyncpg + PG 16 (no SQLite workaround needed since tests use real PG).

##### Research-Grounded Migration Strategy

**Step 1: Set `lazy="raise"` on ALL relationships** as a migration safety net. This converts silent lazy-load failures into loud `InvalidRequestError` exceptions. Every missed eager load becomes immediately visible during testing. Remove `lazy="raise"` only after confirming explicit `selectinload()`/`joinedload()` is in place.

**Step 2: Convert one domain at a time, in dependency order:**
1. `shared/` (enums, exceptions) — no DB, just Python
2. `documents/` — most isolated, fewer FK deps
3. `deals/` — depends on documents, funds
4. `portfolio/` — depends on deals
5. `cash_management/` — depends on portfolio, counterparties
6. `compliance/` — depends on deals, documents
7. `reporting/` — depends on everything (last)

**Step 3: Three-Phase Session Pattern** (from project's proven `async-ingestion-pipeline` solution):
```
Phase 1 (Pre-fetch, Session A): Fetch all needed data, extract into frozen dataclasses, close session
Phase 2 (Async compute, no DB): Run all parallel I/O with zero DB access
Phase 3 (Post-write, Session B): Write results back, single atomic commit
```
This pattern avoids ORM objects crossing thread/coroutine boundaries. Apply to all complex service functions.

**Step 4: LLM output type guards** (from `llm-output-type-mismatch` learning): All AI-extracted fields must use Pydantic models with `@field_validator` coercion. Fields like `critical_gaps` can return as `list[str]` or `list[dict]` non-deterministically. Normalize at accumulation boundary AND guard at consumption site.

##### Tasks

- [ ] **`backend/app/domains/credit/`** — migrate all 10 domain modules
  - `deals/` — PipelineDeal, Deal, ICMemo, DealQualification, stage history, decisions, events
  - `portfolio/` — PortfolioAsset, FundInvestment, Obligation, Alert, Action, Covenant, etc.
  - `cash_management/` — CashAccount, Transaction, Approval, BankStatement, CapitalCall, etc.
  - `compliance/` — KYCScreening, Obligation, ObligationRequirement
  - `documents/` — Document, DocumentVersion, DocumentChunk, DocumentReview, Evidence, etc.
  - `reporting/` — NavSnapshot, InvestorStatement, ReportPack, Schedule, etc.
  - `signatures/` — SignatureQueueItem
  - `actions/` — ExecutionAction, Evidence, Comments, Reviews
  - `dataroom/` — folder governance
  - `dashboard/` — aggregation endpoints
  - `counterparties/` — Counterparty, BankAccount, BankAccountChange (four-eyes preserved)
  - `global_agent/` — Fund Copilot (multi-index RAG)
  - ALL models adapted: add `OrganizationScopedMixin`, convert to SA 2.0 `Mapped[]` if not already
- [ ] **`backend/app/domains/credit/modules/`** — route handlers
  - All `def endpoint(db: Session)` → `async def endpoint(db: AsyncSession)`
  - `require_fund_access()` extended: checks `organization_id` from tenancy middleware
  - Dual mount preserved: root + `/api` prefix
  - `require_role()` preserved with Clerk role mapping
- [ ] **Alembic migration `0002_credit_domain.py`**
  - Create all 112 tables with `organization_id NOT NULL`
  - Preserve all existing indexes, unique constraints, FK relationships
  - NO migration from Private Credit's 51-version history — fresh schema definition
- [ ] **Shared modules**
  - `backend/app/shared/enums.py` — Role, AccessLevel, DealStage, DocumentDomain, etc.
  - `backend/app/shared/exceptions.py` — AppError hierarchy (NotAuthorized, NotFound, ValidationError)
- [ ] **Tests** — adapt Private Credit test patterns
  - Replace SQLite test DB with PG 16 test database (container or docker-compose service)
  - Replace massive `sys.modules` stubbing with proper fixtures
  - Remove `JSONB→JSON` compiler override (unnecessary with real PG)

##### Acceptance Criteria

- [ ] All credit CRUD endpoints functional and returning correct data
- [ ] RBAC roles enforced (ADMIN short-circuit, INVESTOR/AUDITOR read-only)
- [ ] Four-eyes bank account constraint: integration test proves requester ≠ approver
- [ ] Document upload works (sync path, not yet SAS)
- [ ] Fund Copilot query endpoint responds
- [ ] `make check` passes (all tests — wealth + credit)

---

#### Phase 4: AI Engine + Profile Extraction (Sprint 3 — Week 7-8)

**Goal:** AI engine migrated intact and made profile-agnostic. Upload architecture with SSE.

##### Tasks

- [ ] **`backend/ai_engine/`** — migrate entire pipeline from Private Credit OS
  - `intelligence/` — deep_review, memo_chapter_engine, critic, sponsor, quant engines
  - `extraction/` — OCR, chunking, embedding, classification (semantic_chunker.py preserved exactly)
  - `ingestion/` — domain ingest orchestrator
  - `validation/` — 4-layer evaluation framework (preserved exactly)
  - `governance/` — token budget, evidence throttle, artifact cache
  - `prompts/` — Jinja2 registry (extended for profile search path)
  - `pdf/` — ReportLab generation
  - `model_config.py` — model routing (preserved, extended for profile-prefixed stages)
  - `openai_client.py` — dual provider (preserved exactly)
  - Convert sync `_call_openai` to async `_async_call_openai` (already exists in Private Credit)
  - DB calls via `asyncio.to_thread()` for sync-heavy paths (pattern from Private Credit `async-dag-orchestrator` solution)
- [ ] **Profile extraction** (see brainstorm Section H)
  - `profiles/private_credit/profile.yaml` — 14 chapters with budgets, affinity, model routing
  - `profiles/private_credit/prompts/*.j2` — copy from `ai_engine/prompts/intelligence/`
  - `profiles/private_credit/output_schema.json` — formalize IC memo JSON schema
  - `profiles/private_credit/evaluation_criteria.yaml` — extract from validation configs
  - `backend/ai_engine/intelligence/profile_loader.py` — `ProfileLoader.load("private_credit")`
  - `memo_chapter_engine.py` — dynamic `_CHAPTER_TAGS` from profile (fallback to hardcoded)
  - `deep_review.py` — `profile_name` parameter (default: `"private_credit"`)
  - `model_config.py` — support `get_model("private_credit.ch01_exec")`
  - `prompts/registry.py` — add `profiles/{profile}/prompts/` to Jinja2 search path
- [ ] **Upload architecture** (see brainstorm Section I)
  - `POST /api/v1/documents/upload-url` → generate SAS URL + `upload_id`
  - `POST /api/v1/documents/upload-complete` → enqueue to Service Bus, return `job_id`
  - `GET /api/v1/jobs/{job_id}/stream` → SSE events (chunking, OCR, embeddings, indexed, complete)
  - Workers emit progress: `tracker.publish_event(job_id, "ocr_complete", {"pages": 47})`
- [ ] **Worker unification**
  - `backend/worker_app/function_app.py` — Azure Functions: extraction, ingest, compliance, memo
  - Workers import from `backend/ai_engine/` and `backend/app/domains/credit/`
  - Progress events emitted to Redis pub/sub → SSE endpoint picks up

##### Acceptance Criteria

- [ ] `generate_ic_memo(profile="private_credit")` produces identical output to current production
- [ ] Zero private-credit-specific logic in `deep_review.py` or `memo_chapter_engine.py`
- [ ] Profile loader correctly resolves chapters, prompts, budgets from YAML
- [ ] `POST /documents/upload-url` returns valid SAS URL
- [ ] Full upload flow: SAS URL → upload → complete → SSE progress → indexed
- [ ] Memo generation streams sentence fragments via SSE
- [ ] `make check` passes

---

#### Phase 5: @netz/ui + Credit Frontend Core (Sprint 4 — Week 9-10)

**Goal:** Shared design system + credit frontend authenticated and navigable.

##### Tasks

- [ ] **`packages/ui/`** — @netz/ui shared design system
  - `tokens/` — CSS custom properties (`--netz-brand-*`, `--netz-surface-*`, typography, spacing)
  - `components/` — shadcn-svelte customized (Button, Card, Table, Badge, Dialog, Sheet, Tabs)
  - `layouts/` — FCL three-column (`+layout.svelte` with CSS Grid + `transition:slide`), sidebar nav, dashboard shell
  - **Build with `@sveltejs/package`** → outputs to `dist/` with proper svelte exports
  - `package.json`:
    ```json
    { "name": "@netz/ui", "svelte": "./dist/index.js", "types": "./dist/index.d.ts",
      "exports": { ".": { "types": "./dist/index.d.ts", "svelte": "./dist/index.js" } },
      "scripts": { "build": "svelte-kit sync && svelte-package -o dist" },
      "peerDependencies": { "svelte": "^5.0.0" } }
    ```
  - Apps consume via `"@netz/ui": "workspace:*"` (pnpm workspace protocol)
- [ ] **`pnpm-workspace.yaml`** — workspace config
  ```yaml
  packages:
    - "packages/*"
    - "frontends/*"
  ```
- [ ] **CI path filtering** — `dorny/paths-filter@v3` for selective builds (70-90% CI speedup)
  - Backend changes → run Python tests only
  - Frontend changes → build @netz/ui first, then affected frontends
- [ ] **`frontends/credit/`** — SvelteKit scaffold
  - `package.json` — `name: "netz-credit-intelligence"`, imports `@netz/ui`
  - SvelteKit 2 + TypeScript + Vite + adapter-static (SPA mode)
  - `src/lib/api/client.ts` — typed fetch wrappers (pattern from Wealth OS `client.ts:14-25`)
  - `src/lib/auth/` — Clerk SDK for Svelte (sign-in, sign-out, org switching)
  - `src/lib/stores/` — Svelte writable stores (deals, portfolio, documents, risk, jobs)
  - `src/lib/i18n/` — paraglide-js setup, 880+ keys ported from `i18n.properties`
  - `src/routes/+layout.svelte` — Clerk provider, sidebar nav, responsive
  - `src/routes/(team)/` — IC team routes (gated by non-INVESTOR roles)
  - `src/routes/(investor)/` — investor portal routes (INVESTOR/ADVISOR roles only)
    - `overview/`, `documents/`, `performance/`, `tax-faq/`
  - `tailwind.config.ts` — imports @netz/ui tokens, Netz Credit brand overrides
  - `svelte.config.js` — adapter-static, prerender disabled
- [ ] **ECharts setup** — `svelte-echarts` for all charts (pipeline funnel, CVaR timeline, risk scatter)

##### Acceptance Criteria

- [ ] `@netz/ui` builds and exports components correctly
- [ ] Credit frontend builds and authenticates via Clerk
- [ ] FCL three-column layout renders (responsive: desktop, tablet, mobile)
- [ ] API calls work against engine backend with Clerk JWT
- [ ] Investor routes accessible only with INVESTOR role, team routes hidden
- [ ] i18n keys ported — CI check: all 880+ keys present

---

#### Phase 6: Credit Frontend — Mechanical Views (Sprint 5 — Week 11-12)

**Goal:** Standard table/form views operational.

##### Tasks

- [ ] `routes/(team)/portfolio/+page.svelte` + `[investmentId]/+page.svelte` — FCL list→detail
- [ ] `routes/(team)/signatures/+page.svelte` — signature queue with status badges
- [ ] `routes/(team)/cash/+page.svelte` — transaction tables + forms
- [ ] `routes/(team)/reviews/+page.svelte` — document review list + detail panel
- [ ] `routes/(team)/counterparties/+page.svelte` — CRUD with four-eyes bank account UI
- [ ] `routes/(team)/compliance/+page.svelte` — multi-tab ObjectPage equivalent (obligations, KYC, monitoring)

##### Acceptance Criteria

- [ ] 6 views render with real API data
- [ ] WCAG 2.1 AA compliance (labelFor, contrast, keyboard nav)
- [ ] Responsive layout at 4 breakpoints (1024, 768, 600px)
- [ ] shadcn-svelte components from @netz/ui used consistently
- [ ] Empty states with illustrated messages

---

#### Phase 7: Credit Frontend — Dashboard + AI Streaming (Sprint 6 — Week 13-14) 🎯 DEMO-READY

**Goal:** Dashboard redesign + AI streaming views. **Product is demo-ready after this sprint.**

##### Tasks

- [ ] **`routes/(team)/dashboard/+page.svelte`** — three-tier dashboard
  - Tier 1 (Command): action queue (deals awaiting IC, docs pending review, signatures pending), alert banner
  - Tier 2 (Analytical): pipeline funnel by ACTUAL stage (ECharts), AUM + deployment progress, AI confidence distribution
  - Tier 3 (Operational): risk vs return scatter, macro stress (FRED, 12-month), activity feed
- [ ] **`routes/(team)/deals/+page.svelte`** + `[dealId]/+page.svelte` — FCL pipeline navigation
  - Pipeline list with stage badges
  - Deal detail with tabs: overview, documents, IC memo, compliance
- [ ] **`routes/(team)/analysis/[dealId]/+page.svelte`** — Deep Review AI view
  - IC memo generation trigger → SSE job stream
  - Sentence-fragment streaming per chapter via `fetch()` + `ReadableStream` (NOT `EventSource` — cannot send auth headers)
  - **SSE event protocol:**
    ```
    event: chapter_start\ndata: {"chapter": 3, "title": "Financial Analysis"}\n\n
    event: chunk\ndata: {"chapter": 3, "text": "The borrower's EBITDA margin..."}\n\n
    event: chapter_complete\ndata: {"chapter": 3}\n\n
    event: progress\ndata: {"completed": 3, "total": 14, "pct": 21}\n\n
    event: done\ndata: {"job_id": "abc-123"}\n\n
    ```
  - **Svelte store pattern:** `createJobStream(jobId, token)` returns writable store with `chapters` map, `connect()`/`disconnect()`, exponential backoff reconnection (1s→30s, max 5 retries)
  - Chapter progress indicators (started, streaming, complete)
  - Critic findings display after all chapters
  - **Token buffering (worker side):** Buffer LLM tokens until ~50 chars + sentence boundary, then `redis.publish(channel, json.dumps({"event": "chunk", "chapter": n, "text": fragment}))`
- [ ] **`routes/(team)/copilot/+page.svelte`** — Fund Copilot chat
  - Message input + response streaming
  - Citation display with source links
- [ ] **`routes/(team)/reporting/+page.svelte`** — FCL 3-column
  - Begin: filter + deal list
  - Mid: chapters + config
  - End: PDF preview (iframe)

##### Acceptance Criteria

- [ ] Dashboard shows action queue with real counts, pipeline funnel by actual deal stage
- [ ] IC memo generation streams sentence fragments per chapter via SSE
- [ ] Upload a pitch deck → progress bar → "N chunks indexed" (full SAS + SSE flow)
- [ ] FCL three-column navigation functional on deals + reporting
- [ ] **Full investor demo possible:** upload → index → generate memo → stream → view PDF

---

#### Phase 8: Wealth Frontend — From Scratch (Sprint 7 — Week 15-16)

**Goal:** Wealth OS frontend rebuilt correctly with @netz/ui. No legacy code.

##### Tasks

- [ ] **`frontends/wealth/`** — SvelteKit scaffold
  - `package.json` — `name: "netz-wealth-os"`, imports `@netz/ui`
  - Clerk auth integration
  - Typed API client matching wealth endpoints
- [ ] **`routes/dashboard/+page.svelte`** — 3 portfolio cards (conservative/moderate/growth)
  - CVaR gauge per profile (ECharts gauge)
  - Status badge (ok/warning/breach)
  - Regime chip (RISK_ON/RISK_OFF/INFLATION/CRISIS)
- [ ] **`routes/funds/+page.svelte`** — Fund universe table
  - Sortable, filterable by block/geography/asset_class
  - Scoring columns (manager_score, return consistency, drawdown control)
  - Expandable row detail with full metrics
- [ ] **`routes/allocation/+page.svelte`** — Weight editors
  - Strategic allocation: sliders with min/max band indicators
  - Tactical positions: overweight inputs with conviction score
  - IC approval gate (require `ic_member` role for strategic edits)
- [ ] **`routes/risk/+page.svelte`** — Risk monitor
  - CVaR timeline (ECharts line chart with limit lines)
  - Regime timeline (color-coded band chart)
  - SSE live updates via fetch + ReadableStream
- [ ] **`routes/backtest/+page.svelte`** — Backtest results
  - Async run trigger + polling on status
  - Performance attribution visualization

##### Acceptance Criteria

- [ ] All 5 wealth views functional with real API data
- [ ] SSE risk stream delivers live CVaR updates
- [ ] Clerk auth with org switching
- [ ] Responsive, WCAG 2.1 AA
- [ ] @netz/ui components shared with credit frontend (visual consistency)

---

#### Phase 9: Data Migration Tooling (Sprint 8 — Week 17-18)

**Goal:** Production data migration from Private Credit OS → Analysis Engine.

##### Tasks

- [ ] **`scripts/migrate_credit_data.py`** — main migration script
  - Reads from Private Credit OS PostgreSQL (source)
  - Writes to Analysis Engine PostgreSQL (destination) with `organization_id = '<netz-uuid>'`
  - FK dependency order: organizations → funds → deals → documents → ... (topological sort)
  - Uses `pg_insert().on_conflict_do_update()` for idempotent upserts (pattern from Wealth OS `risk_calc.py:485-489`)
  - Checksum verification: row count + MD5 per table
  - `--dry-run` mode: validate without writing
  - `--resume` mode: tracks last-migrated ID per table in state file
  - Blob Storage: configurable (shared account = no migration needed, new account = copy + remap URIs)
- [ ] **`scripts/reindex_search.py`** — Azure AI Search reindexing
  - Read document_chunks from migrated DB
  - Recreate search index with new org_id-aware schema
  - Verify: same query returns same results
- [ ] **`scripts/validate_migration.py`** — post-migration validation
  - Row count comparison (source vs destination)
  - Checksum comparison per table
  - FK integrity verification
  - IC memo generation test on migrated deal (output comparison)
- [ ] **Infra:** `infra/bicep/main.bicep` — add Azure Cache for Redis, update PG to 16 + TimescaleDB
  - **Azure PG Flexible Server with TimescaleDB requires TWO config resources:**
    1. `azure.extensions` → `'TIMESCALEDB,UUID-OSSP,PGCRYPTO'` (allowlist)
    2. `shared_preload_libraries` → `'timescaledb'` (with `dependsOn` on extensions)
  - Then `CREATE EXTENSION IF NOT EXISTS timescaledb;` post-deploy
  - **Azure Cache for Redis:** Standard C1 (1GB), TLS 1.2 only, private endpoint, `notify-keyspace-events: 'KEA'` for pub/sub
  - **IMPORTANT: Deploy and test Bicep to staging environment in Sprint 1, not Sprint 8.** Azure PG Flexible Server + TimescaleDB has specific extension application ordering that can surprise. Discovering Bicep issues during cutover week is unacceptable. The staging environment validates: extension creation order, `shared_preload_libraries` restart behavior, Redis private endpoint connectivity, and PG 16 compatibility.
- [ ] **Migration FK ordering:** Use `information_schema.table_constraints` query to auto-derive topological sort (parents before children). Don't hardcode table order.
- [ ] **Blob URIs:** If sharing storage account, `replace(blob_uri, old_prefix, new_prefix)`. Strip SAS tokens: `split_part(blob_uri, '?', 1)`
- [ ] **AI Search:** Export index schema → recreate on target → recreate data source → recreate indexer → run full reindex (high-water mark resets with new indexer)

##### Acceptance Criteria

- [ ] Dry-run against production snapshot: zero errors
- [ ] Full staging migration: all data, all FKs intact
- [ ] IC memo generation works identically on migrated data
- [ ] Azure AI Search queries return same results post-migration
- [ ] Blob URIs resolve correctly (shared account or remapped)

---

#### Phase 10: Production Cutover (Sprint 9 — Week 19-20)

**Goal:** Switch production to unified engine. Archive legacy repos.

##### Tasks

- [ ] Maintenance window: set Private Credit OS to read-only
- [ ] Execute `scripts/migrate_credit_data.py` (production)
- [ ] Execute `scripts/validate_migration.py` (verify checksums)
- [ ] Execute `scripts/reindex_search.py` (recreate search index)
- [ ] Deploy `netz-analysis-engine` backend to Azure Container Apps
- [ ] Deploy `frontends/credit/` to Azure Static Web Apps
- [ ] Deploy `frontends/wealth/` to Azure Static Web Apps
- [ ] DNS switch: update Azure SWA proxy + API gateway
- [ ] Smoke test all critical flows:
  - IC memo generation (end-to-end)
  - Document upload + SSE progress
  - Deal CRUD + RBAC
  - Wealth risk stream + portfolio eval
  - Investor portal access
- [ ] Monitor 48h before declaring success
- [ ] Archive `netz-private-credit-os` (read-only, GitHub archive)
- [ ] Archive `netz-wealth-os` (read-only, GitHub archive)
- [ ] Rollback plan: DNS revert to archived repos (tested before cutover)

##### Acceptance Criteria

- [ ] All production users on new system
- [ ] IC memos, uploads, compliance, cash, signatures all functional
- [ ] Wealth dashboard, risk monitor, allocation editor all functional
- [ ] Zero data loss (row counts + checksums verified)
- [ ] Rollback tested: DNS revert completes in < 5 minutes

---

## System-Wide Impact

### Interaction Graph

```
Clerk JWT → tenancy middleware (set org_id) → RLS policy (filter all queries)
                                            → auth dependency (extract roles, fund access)
                                            → route handler → domain service → AsyncSession → PG 16

Upload flow:
  Frontend → POST /upload-url → SAS URL generation → Frontend XHR to Azure Blob
  Frontend → POST /upload-complete → Service Bus enqueue → Worker picks up
  Worker → extraction pipeline → Redis PUBLISH job:{id} progress events
  Frontend → GET /jobs/{id}/stream → SSE reads from Redis → renders progress

IC Memo flow:
  Frontend → POST /deals/{id}/deep-review → Service Bus enqueue
  Worker → ProfileLoader("private_credit") → 14 chapters → Redis PUBLISH chapter events
  Frontend → GET /jobs/{id}/stream → SSE sentence fragments → renders per-chapter
```

### Error & Failure Propagation

- **RLS violation:** PG returns empty result set (not error) → application sees "not found" → 404
- **Clerk JWT expired:** 401 → frontend redirects to Clerk sign-in
- **SSE disconnect:** Frontend reconnects with exponential backoff (1s → 30s, max 10 retries)
- **Worker failure:** Service Bus handles retry / DLQ (maxDeliveryCount=10)
- **AI provider failure:** `openai_client.py` has 5-attempt retry with exponential backoff + jitter

### State Lifecycle Risks

- **Partial upload:** `upload-url` creates record, but `upload-complete` never called → orphaned blob. Mitigation: daily cleanup job for uploads older than 24h without completion.
- **Partial migration:** Script crashes mid-table → resumable via `--resume` flag + state file.
- **Multi-tenant RLS misconfiguration:** If `app.organization_id` not set, RLS returns nothing. Mitigation: middleware ALWAYS sets it; 500 error if JWT has no `org_id`.

---

## Alternative Approaches Considered

| Approach | Why Rejected | See Brainstorm |
|----------|-------------|----------------|
| Refactor Private Credit OS in-place | Too risky on production system. 112 tables + live users. | v1 → v2 pivot |
| Separate backends, shared library | 3 repos to maintain, version sync headaches | Section: "What We're Building" |
| API gateway only (no merge) | No shared DB, no cross-domain queries, duplicate auth | Section: "What We're Building" |
| Keep Wealth OS frontend, upgrade | Fragmented energy, legacy drift risk | v2 → v3 pivot |
| Next.js instead of SvelteKit | Heavier runtime, worse SSE support, React overhead | Key Decision #5 in brainstorm v1 |
| Auth0 instead of Clerk | No native multi-org, more complex Svelte integration | Key Decision #6 |
| PG NOTIFY instead of Redis | Workers in separate Azure Functions host can't share PG connection | Key Decision #3 |

---

## Dependencies & Prerequisites

| Dependency | Required By | Status |
|-----------|-------------|--------|
| Clerk account + API keys | Sprint 0 | Not yet provisioned |
| Azure Cache for Redis | Sprint 8 (production) | Not yet in Bicep (docker-compose for dev) |
| PG 16 + TimescaleDB on Azure | Sprint 8 (production) | Need to upgrade from PG 15 |
| Service Bus (existing topics) | Sprint 3 | Already provisioned (`document-pipeline`, `compliance-pipeline`, `memo-generation`) |
| Azure Blob Storage | Sprint 3 | Already provisioned (shared account decision) |
| Azure AI Search | Sprint 3 | Already provisioned (reindex needed post-migration) |
| OpenAI API keys | Sprint 3 | Already configured in Key Vault |

---

## Risk Analysis & Mitigation

See [brainstorm Section D](../brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md) for complete risk register (13 risks with L/M/H ratings).

Top 3 risks:
1. **Credit domain migration underestimated (H/H):** Split into 2 sprints. Each model adapted individually. Integration tests per module.
2. **Data migration from production (H/H):** Dedicated sprint. Idempotent scripts, checksums, dry-run. Rollback = DNS revert.
3. **IC memo pipeline breaks during profile extraction (M/H):** Additive layer with fallback to hardcoded defaults. Identical output verification.

---

## Do Not Touch List

(See brainstorm Section F — preserved in migration)

| Component | Reason |
|-----------|--------|
| `ai_engine/extraction/semantic_chunker.py` | Recently fixed critical bug |
| `ai_engine/validation/` | 4-layer evaluation — core IP |
| `ai_engine/openai_client.py` interface | Stable provider abstraction |
| `ai_engine/intelligence/ic_critic_engine.py` logic | Calibrated adversarial review |
| `ai_engine/governance/` | Token budget management |
| `counterparties/` four-eyes logic | Regulatory requirement |
| Service Bus topic names | Workers depend on exact names |

---

## Success Metrics

| Metric | Target | Measured By |
|--------|--------|-------------|
| Credit frontend demo-ready | Sprint 6 (week 14) | Can demo: upload → index → IC memo stream → PDF |
| Wealth frontend operational | Sprint 7 (week 16) | All 5 views functional with real data |
| Production cutover | Sprint 9 (week 20) | All users on new system, zero data loss |
| IC memo output parity | 100% identical | Side-by-side comparison on same deal |
| API endpoint count | ≥52 (26 wealth + 26 credit) | Automated endpoint count in CI |
| Test coverage | ≥80% lines | pytest-cov report |
| Lighthouse accessibility | ≥90 | Both frontends |

---

## Sources & References

### Origin

- **Brainstorm:** [docs/brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md](../brainstorms/2026-03-14-analysis-engine-platform-brainstorm.md)
  - Key decisions: monorepo with split-ready structure, Wealth OS stack as foundation, Clerk auth, sentence-fragment streaming, multi-tenancy from day one, Wealth frontend rebuilt from scratch

### Internal References (Private Credit OS)

- DB base classes: `backend/app/core/db/base.py:19-51`
- Route mounting: `backend/app/main.py:301-328`
- Session management: `backend/app/core/db/session.py:111-157`
- Auth system: `backend/app/core/security/auth.py:1-293`
- Model config: `backend/ai_engine/model_config.py:38-83`
- Settings: `backend/app/core/config/settings.py:1-257`
- Deep review: `backend/ai_engine/intelligence/deep_review.py:1-100`
- Memo chapters: `backend/ai_engine/intelligence/memo_chapter_engine.py:22-26`
- Async lessons: `docs/solutions/performance-issues/async-dag-orchestrator-deep-review-pipeline.md`

### Internal References (Wealth OS)

- Async engine: `backend/app/database.py:7-24`
- JWKS auth: `backend/app/auth/dependencies.py:32-93`
- SSE pattern: `backend/app/routers/risk.py:179-232`
- Service pattern: `backend/app/services/cvar_service.py:106-158`
- Worker pattern: `backend/app/workers/risk_calc.py:434-508`
- Frontend SSE: `frontend/src/lib/api/client.ts:193-265`
- Svelte stores: `frontend/src/lib/stores/risk.ts:1-78`
- Docker: `docker-compose.yml:1-31`

### External References

- Clerk Svelte SDK: https://clerk.com/docs/quickstarts/svelte
- TimescaleDB hypertables: https://docs.timescale.com/use-timescale/latest/hypertables/
- asyncpg: https://magicstack.github.io/asyncpg/
- shadcn-svelte: https://www.shadcn-svelte.com/
- paraglide-js: https://inlang.com/m/gerre34r/library-inlang-paraglideJs
