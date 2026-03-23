# Brainstorm: Netz Analysis Engine Platform Transformation

**Date:** 2026-03-14
**Status:** Draft — Revised after `netz-wealth-os` review
**Author:** Claude (Compound Engineering Brainstorm)
**Scope:** Create a unified multi-tenant B2B SaaS Analysis Engine from two existing products

---

## STRATEGIC EVOLUTION

> **v1 (original):** Refactor `netz-private-credit-os` monorepo into engine + frontend.
>
> **v2 (post Wealth OS review):** Create NEW `netz-analysis-engine` merging both backends, Wealth OS stack as foundation. Two separate SvelteKit frontends.
>
> **v3 (current — focus decision):** Same unified backend, but **one product at a time**. `netz-wealth-os` is **archived** — backend migrates to engine, frontend is rebuilt from scratch inside the engine repo. No parallel development on legacy repos. All energy goes to `netz-analysis-engine`.
>
> **Rationale:** Maintaining two products in parallel with weak frontends in both = fragmented energy. Focus on one product, deliver it well. The Wealth frontend is rebuilt correctly from day one with `@netz/ui`, not upgraded from a legacy codebase.

---

## What We're Building

A **single active repo** with two vertical frontends built inside it:

1. **`netz-analysis-engine`** — THE repo. Unified backend + both vertical frontends + shared UI package.
2. **`netz-private-credit-os`** — ARCHIVED after data migration. Stays running as read-only fallback.
3. **`netz-wealth-os`** — ARCHIVED. Backend + calibration migrated. Frontend rebuilt from scratch.

```
netz-analysis-engine/                    ← THE REPO (one repo, concentrated energy)
├─ backend/
│  ├─ app/
│  │  ├─ core/                           ← shared: auth (Clerk), tenancy (RLS), DB, config
│  │  ├─ domains/
│  │  │  ├─ credit/                      ← migrated from netz-private-credit-os
│  │  │  ├─ wealth/                      ← migrated from netz-wealth-os
│  │  │  ├─ documents/                   ← shared document pipeline
│  │  │  └─ compliance/                  ← shared compliance
│  │  └─ modules/                        ← shared: signatures, reporting, etc.
│  ├─ ai_engine/                         ← from private-credit-os (IC memos, extraction, prompts)
│  └─ quant_engine/                      ← from wealth-os (CVaR, regime, optimizer, scoring)
├─ profiles/                             ← vertical analysis configs (YAML)
├─ calibration/                          ← from wealth-os (blocks, limits, scoring YAML)
├─ worker_app/                           ← Azure Functions + CLI workers
├─ infra/bicep/                          ← unified infra (PG 16 + TimescaleDB + Redis 7)
│
├─ packages/ui/                          ← @netz/ui — shared design system
│  ├─ tokens/                            ← CSS variables (brand colors, typography)
│  ├─ components/                        ← shadcn-svelte customized
│  └─ layouts/                           ← FCL, dashboard shell, sidebar
│
├─ frontends/credit/                     ← netz-credit-intelligence (SvelteKit)
│  ├─ imports @netz/ui
│  ├─ routes/(team)/                     ← IC team: dashboard, deals, portfolio, compliance...
│  ├─ routes/(investor)/                 ← Investor portal: overview, documents, performance
│  └─ brand: Netz Credit tokens
│
└─ frontends/wealth/                     ← netz-wealth-os frontend (SvelteKit, built from scratch)
   ├─ imports @netz/ui
   ├─ routes: dashboard, funds, allocation, risk, backtest
   └─ brand: Netz Wealth tokens
```

## Why This Approach

- **Concentrated energy:** One active repo. No parallel development on legacy repos. One team, one backlog, one CI pipeline.
- **Better foundation:** Wealth OS stack is objectively superior — PG 16, TimescaleDB, asyncpg (3x faster), Redis SSE, Python 3.12, fully async, YAML-driven config.
- **Core IP preserved:** AI engine (14-chapter IC memo) migrates intact. Quant engine (CVaR, regime, optimizer) migrates intact.
- **Wealth frontend rebuilt correctly:** No "upgrade" of a weak frontend. Built from scratch with `@netz/ui` from the first component. Every view designed for the unified engine.
- **Zero legacy drift:** No risk of Wealth OS frontend evolving in the wrong direction. No weekly API contract sync needed. No two backends active simultaneously.

---

## Foundation: Wealth OS Stack Superiority

| Aspect | Private Credit OS (current) | Wealth OS (foundation) | Winner |
|---|---|---|---|
| PostgreSQL | 15 | **16** | Wealth |
| Time-series | Standard tables | **TimescaleDB hypertables** (90%+ compression) | Wealth |
| Async driver | psycopg3 (sync-first) | **asyncpg** (native async, ~3x faster) | Wealth |
| ORM | SQLAlchemy 2.x (mixed sync/async) | **SQLAlchemy 2.0 fully async** | Wealth |
| Cache/Pub-Sub | None | **Redis 7** (SSE, CVaR cache) | Wealth |
| Python | 3.11 | **3.12** (10-15% faster) | Wealth |
| Frontend | SAP UI5 (legacy) | **SvelteKit 2 + Tailwind 4 + shadcn-svelte** | Wealth |
| Config | Hardcoded + env vars | **YAML externalized** (profiles, limits, scoring) | Wealth |
| Auth | Entra ID + MSAL (known bugs) | **Entra ID + JWKS caching** (cleaner) | Wealth |
| Type checking | Pyright | **mypy strict** + SQLAlchemy plugin | Wealth |
| Streaming | 5s polling | **SSE native** via Redis pub/sub | Wealth |
| DB constraints | Few CHECK constraints | **CHECK constraints** on all enums | Wealth |
| AI/LLM pipeline | **14-chapter IC memo, OCR, embeddings, 4-layer eval** | None | Credit |
| Domain richness | **112 tables, 25+ domain modules, RBAC** | 12 tables, 7 services | Credit |
| Workers | **Azure Functions v4** (Service Bus) | CLI scripts | Credit |

**Conclusion:** Wealth OS provides the **infrastructure foundation**. Private Credit provides the **domain richness and AI engine**. The new repo takes the best of both.

---

## A. Repository Split Map (REVISED — Migration, Not Refactoring)

### What MIGRATES from `netz-private-credit-os` → `netz-analysis-engine`

| Source | What Migrates | Destination in `netz-analysis-engine` |
|---|---|---|
| `backend/ai_engine/` | **Entire AI engine** — IC memos, extraction, ingestion, validation, prompts | `backend/ai_engine/` |
| `backend/app/domain/` | All 10 domain modules: deals, portfolio, cash, compliance, documents, reporting, signatures, actions, dataroom, dashboard, global_agent | `backend/app/domains/credit/` |
| `backend/app/modules/` | Route handlers: ai, deals, compliance, documents, signatures, adobe_sign | `backend/app/domains/credit/modules/` |
| `backend/app/core/security/rbac.py` | RBAC roles + fund access | `backend/app/core/security/` (adapted for Clerk) |
| `worker_app/function_app.py` | Azure Functions workers (Service Bus) | `backend/worker_app/` |
| `infra/bicep/` | Azure IaC templates | `infra/bicep/` (extended with TimescaleDB + Redis) |
| `backend/app/core/db/migrations/` | Alembic history (0001-0051) | Fresh chain references legacy as baseline |

### What MIGRATES from `netz-wealth-os` → `netz-analysis-engine`

| Source | What Migrates | Destination in `netz-analysis-engine` |
|---|---|---|
| `backend/app/services/` | CVaR, regime, optimizer, scoring, drift, rebalance, momentum, Lipper, backtest | `backend/quant_engine/` |
| `backend/app/models/` | 12 tables: funds, NAV, risk, portfolio, allocation, rebalance, macro, Lipper, backtest | `backend/app/domains/wealth/models/` |
| `backend/app/routers/` | 26 API endpoints | `backend/app/domains/wealth/routes/` |
| `backend/app/workers/` | 7 workers: ingestion, risk calc, portfolio eval, drift, Bayesian CVaR, regime fit, FRED | `backend/worker_app/` (unified with credit workers) |
| `backend/app/database.py` | **Async SQLAlchemy + asyncpg** — becomes foundation | `backend/app/core/db/` |
| `backend/app/auth/` | JWT + JWKS caching pattern | `backend/app/core/security/` (adapted for Clerk) |
| `backend/app/config.py` | Pydantic Settings + feature flags | `backend/app/core/config/` (merged) |
| `calibration/config/` | blocks.yaml, profiles.yaml, limits.yaml, scoring.yaml | `calibration/` |
| `docker-compose.yml` | PG 16 + TimescaleDB + Redis 7 | `docker-compose.yml` |

### What STAYS UNTOUCHED

| Repo | Status | Sunset Timeline |
|---|---|---|
| `netz-private-credit-os` | **Remains in production** — zero changes | Until `netz-analysis-engine` credit routes are validated |
| `netz-wealth-os` | **Remains in production** — frontend evolves | Backend deprecated when wealth routes in engine are validated |

### NEW files in `netz-analysis-engine`

| File | Purpose |
|---|---|
| `backend/app/core/tenancy/middleware.py` | Multi-tenancy: org_id from Clerk JWT → PG RLS |
| `backend/app/core/security/clerk_auth.py` | Clerk JWT verification |
| `backend/app/core/jobs/tracker.py` | Job progress via Redis pub/sub |
| `backend/app/core/jobs/sse.py` | SSE stream generator |
| `profiles/private_credit/profile.yaml` | IC memo chapters (extracted from hardcoded Python) |
| `profiles/private_credit/prompts/*.j2` | Prompts (moved from ai_engine/prompts/intelligence/) |
| `profiles/liquid_funds/profile.yaml` | Wealth DD profile (draft) |
| `packages/netz-ui/` | `@netz/ui` shared design system |

---

## B. Impact Map per Transformation (REVISED)

> **Note:** Since we are building a NEW repo, most "transformations" become **construction tasks** rather than refactoring tasks. The risk profile is fundamentally different — we are building new, not breaking existing.

### Construction Phase 1 — Unified Core (foundation)

| What | Action | Detail |
|---|---|---|
| `backend/app/core/db/` | BUILD | asyncpg + SQLAlchemy 2.0 async (from Wealth OS pattern) + TimescaleDB |
| `backend/app/core/config/` | BUILD | Merged Pydantic Settings from both projects + YAML config loading |
| `backend/app/core/security/clerk_auth.py` | BUILD | Clerk JWT verification + org membership extraction |
| `backend/app/core/tenancy/middleware.py` | BUILD | RLS middleware: set `app.organization_id` per request |
| `backend/app/core/jobs/` | BUILD | Redis pub/sub job tracker + SSE stream |
| `docker-compose.yml` | BUILD | PG 16 + TimescaleDB + Redis 7 (from Wealth OS) |
| `Makefile` | BUILD | Unified dev commands |

### Construction Phase 2 — Domain Migration

| What | Action | Detail |
|---|---|---|
| `backend/app/domains/credit/` | MIGRATE | All 112 credit tables + routes, adapted to async + org_id |
| `backend/app/domains/wealth/` | MIGRATE | All 12 wealth tables + routes, add org_id |
| `backend/ai_engine/` | MIGRATE | Intact from Private Credit OS |
| `backend/quant_engine/` | MIGRATE | From Wealth OS services/ |
| `backend/worker_app/` | BUILD | Unified: Azure Functions (credit) + CLI workers (wealth) |
| `profiles/` | BUILD | YAML profiles extracted from both codebases |
| `calibration/` | MIGRATE | From Wealth OS calibration/ |

**Tables requiring `organization_id` (112 total):**
- 106 already have `fund_id` (via `FundScopedMixin`) — organization_id added alongside
- 6 without `fund_id`: `users`, `funds`, `ic_memos`, `deal_qualifications`, `macro_snapshots`, `report_pack_sections` — these need org_id added directly
- 3 linked via FK only: `counterparty_bank_accounts`, `counterparty_documents`, `bank_account_changes` — access org via parent FK

**Hardcoded UUID to remove:**
- `CANONICAL_FUND_ID = uuid.UUID("aaaa0001-0001-4000-a000-000000000001")` in `settings.py`
- Fallback zero UUID in `compliance/routes/obligation_engine.py`

### Transformation 2 — Auth Migration (Entra ID → Clerk)

| File | Action | Detail |
|---|---|---|
| `backend/app/core/security/auth.py` | REPLACE | Replace Entra JWT verification with Clerk JWT verification |
| `backend/app/core/security/clerk_auth.py` | NEW | Clerk-specific JWT decode, JWKS fetch, org membership extraction |
| `backend/app/core/security/dependencies.py` | EXTEND | Adapt `get_actor()` to use Clerk claims |
| `backend/app/core/config/settings.py` | EXTEND | Replace `oidc_*` vars with `CLERK_*` vars |
| `backend/app/core/db/models.py` (User model) | EXTEND | Map `external_id` to Clerk user ID |
| `frontend/ui5app/webapp/service/ApiClient.js` | DELETE | Replaced by SvelteKit API client |
| `advisor-portal/src/lib/auth.ts` | DELETE | Replaced by Clerk SDK in SvelteKit |
| `advisor-portal/src/lib/api.ts` | DELETE | Replaced by SvelteKit API client |

**Backend files touching token validation (all need changes):**
1. `backend/app/core/security/auth.py` — Primary: `_verify_entra_jwt()`, `_decode_swa_client_principal()`, `actor_from_request()`
2. `backend/app/core/security/dependencies.py` — `get_actor()`, `require_fund_access()`
3. `backend/app/core/config/settings.py` — `oidc_audience`, `oidc_issuer`, `oidc_jwks_url`
4. `backend/tests/conftest.py` — Test fixtures (X-DEV-ACTOR stays, but Clerk test mode added)

**Frontend files using MSAL/Auth (all replaced by Clerk SDK):**
1. `frontend/ui5app/webapp/service/ApiClient.js` — `/.auth/me`, `X-NETZ-PRINCIPAL-*` headers
2. `advisor-portal/src/lib/auth.ts` — Auth helpers
3. `advisor-portal/src/lib/api.ts` — API client with auth headers

**RBAC role mapping (Entra → Clerk):**

| Current Role | Clerk Equivalent |
|---|---|
| `ADMIN` | Clerk org role: `org:admin` |
| `INVESTMENT_TEAM` | Clerk org role: `org:investment_team` |
| `GP` | Clerk org role: `org:gp` |
| `DIRECTOR` | Clerk org role: `org:director` |
| `COMPLIANCE` | Clerk org role: `org:compliance` |
| `AUDITOR` | Clerk org role: `org:auditor` |
| `INVESTOR` | Clerk org role: `org:investor` |
| `ADVISOR` | Clerk org role: `org:advisor` |

### Transformation 3 — Reliable Upload Architecture (SAS URL + SSE)

| File | Action | Detail |
|---|---|---|
| `backend/app/domain/documents/routes/ingest.py` | EXTEND | Add `POST /documents/upload-url` (SAS generation), `POST /documents/upload-complete` |
| `backend/app/core/jobs/__init__.py` | NEW | Job tracking module |
| `backend/app/core/jobs/models.py` | NEW | `JobProgress` model (id, type, status, events, created_at) |
| `backend/app/core/jobs/tracker.py` | NEW | `JobTracker` — write progress events to Redis pub/sub or PG NOTIFY |
| `backend/app/core/jobs/sse.py` | NEW | SSE stream generator (reads from Redis/PG NOTIFY) |
| `backend/app/modules/jobs/routes.py` | NEW | `GET /api/v1/jobs/{job_id}/stream` (SSE endpoint) |
| `backend/app/core/db/migrations/versions/0055_job_progress.py` | NEW | Job progress table |
| `worker_app/function_app.py` | EXTEND | Emit progress events from extraction/ingest/memo workers |
| `backend/app/services/azure/blob_client.py` | EXTEND | Add `generate_sas_url()` method |

**New endpoints:**
1. `POST /api/v1/documents/upload-url` → `{ sas_url, blob_path, upload_id }`
2. `POST /api/v1/documents/upload-complete` → `{ job_id }` (enqueues to Service Bus)
3. `GET /api/v1/jobs/{job_id}/stream` → SSE event stream

**Progress event flow:**
```
Worker (Azure Functions) → Redis PUBLISH job:{job_id} → SSE endpoint reads → Frontend EventSource
```
Redis chosen over PG NOTIFY because: (a) workers may not share the same PG connection pool, (b) Redis pub/sub is fire-and-forget with no persistence needed. **Note:** Azure Cache for Redis must be added to `infra/bicep/main.bicep` — not yet provisioned. Fallback to PG NOTIFY if Redis provisioning is delayed.

### Transformation 4 — Frontend Migration (SAP UI5 → SvelteKit)

| UI5 View/Controller | Svelte Route | Migration Type |
|---|---|---|
| `Dashboard.view.xml` + `Dashboard.controller.js` (47KB ctrl, 33KB view) | `routes/dashboard/+page.svelte` | **DESIGN DECISION** — full redesign (Transformation 5) |
| `DealsPipeline.view.xml` + `DealsPipeline.controller.js` (89KB ctrl, 28KB view) | `routes/deals/+page.svelte` | **DESIGN DECISION** — FCL equivalent needed, complex controller |
| `pipeline/PipelineDealDetail.view.xml` + controller | `routes/deals/[dealId]/+page.svelte` | **DESIGN DECISION** — SSE streaming for memo generation |
| `Portfolio.view.xml` + `Portfolio.controller.js` (40KB ctrl, 36KB view) | `routes/portfolio/+page.svelte` | Mechanical — table + FCL layout |
| `portfolio/PortfolioDealDetail.view.xml` + controller | `routes/portfolio/[investmentId]/+page.svelte` | Mechanical — Object Page equivalent |
| `Signatures.view.xml` + `Signatures.controller.js` (45KB ctrl, 20KB view) | `routes/signatures/+page.svelte` | Mechanical — table + status workflow |
| `Compliance.view.xml` + `Compliance.controller.js` (64KB ctrl, 40KB view) | `routes/compliance/+page.svelte` | **DESIGN DECISION** — complex multi-tab layout |
| `CashManagement.view.xml` + `CashManagement.controller.js` (37KB ctrl, 31KB view) | `routes/cash/+page.svelte` | Mechanical — forms + tables |
| `Reporting.view.xml` + `Reporting.controller.js` (83KB ctrl, 34KB view) | `routes/reporting/+page.svelte` | **DESIGN DECISION** — FCL 3-column with PDF preview |
| `DocumentReviews.view.xml` + `DocumentReviews.controller.js` (17KB ctrl, 10KB view) | `routes/reviews/+page.svelte` | Mechanical — simple list + detail |
| `Counterparties.view.xml` + `Counterparties.controller.js` (6KB ctrl, 10KB view) | `routes/counterparties/+page.svelte` | Mechanical — simple CRUD |
| *(no UI5 equivalent)* | `routes/analysis/[dealId]/+page.svelte` | **NEW** — Deep Review AI with SSE streaming |
| *(no UI5 equivalent)* | `routes/copilot/+page.svelte` | **NEW** — Fund Copilot chat |

**Views requiring design decisions (cannot migrate mechanically):**
1. **Dashboard** — full redesign per Transformation 5
2. **Deals Pipeline + Detail** — FCL three-column equivalent + SSE streaming for IC memo
3. **Compliance** — complex 4-tab Object Page with obligation engine
4. **Reporting** — FCL 3-column with inline PDF preview (Begin: filter, Mid: chapters, End: PDF)
5. **Deep Review (AI)** — token streaming per chapter, progress indicators, real-time updates

**Views that can migrate mechanically (table/form patterns):**
1. Portfolio + Detail — standard list→detail
2. Signatures — table with status badges
3. Cash Management — form inputs + transaction tables
4. Document Reviews — simple list with detail panel
5. Counterparties — basic CRUD

### Transformation 5 — Dashboard Redesign

| File | Action | Detail |
|---|---|---|
| `frontend/ui5app/webapp/view/Dashboard.view.xml` | DELETE | Replaced by Svelte dashboard |
| `frontend/ui5app/webapp/controller/Dashboard.controller.js` | DELETE | Replaced by Svelte dashboard |
| `backend/app/domain/dashboard/` | EXTEND | New aggregation endpoints for action queue, stage breakdown |

**Pipeline deal stages (actual enum values from codebase):**

| DB Value | Display Stage | Source |
|---|---|---|
| `SCREENING` | Screening | `pipeline_intelligence.py` — default stage on creation |
| `QUALIFIED` | Qualified | `deals/enums.py` + stage transitions |
| `IC_REVIEW` | Deep Review | Mapped from DealStage enum |
| `CONDITIONAL` | IC Ready | Mapped from DealStage enum |
| `APPROVED` | Approved | Stage transition service |
| `REJECTED` | Rejected | Stage transition service |
| `ACTIVE` | Active (Portfolio) | `document_scanner.py` — lifecycle_stage for converted deals |
| `ARCHIVED` | Archived | Stage transition service |

**Note:** The `pipeline_deals` table uses **string** `stage` field (not an enum). The `deals` table (portfolio) uses `DealStage` enum with values: `INTAKE`, `QUALIFIED`, `IC_REVIEW`, `CONDITIONAL`, `APPROVED`, `CONVERTED_TO_ASSET`, `REJECTED`, `CLOSED`. The dashboard must query BOTH tables and unify the stages.

**Dashboard visual mapping:**
```
Tier 1 — Command
  Action Queue: COUNT(pipeline_deals WHERE stage IN ('CONDITIONAL','APPROVED') AND no IC decision)
              + COUNT(document_reviews WHERE status='SUBMITTED')
              + COUNT(signature_queue_items WHERE status='PENDING')

Tier 2 — Analytical
  Pipeline Funnel: GROUP BY stage on pipeline_deals
    Intake(SCREENING) → Qualified → Deep Review(IC_REVIEW) → IC Ready(CONDITIONAL) → Approved → Rejected
  AUM: SUM(fund_investments.committed_amount) WHERE active
  AI Confidence: AVG(deal_intelligence_profiles.confidence_score) across active reviews

Tier 3 — Operational
  Risk vs Return: scatter from deal_intelligence_profiles (risk_score, expected_return)
  Macro: macro_snapshots (latest, 12-month window)
  Activity: audit_events ORDER BY created_at DESC LIMIT 5
```

### Transformation 6 — Analysis Engine: Vertical Profiles

| File | Action | Detail |
|---|---|---|
| `profiles/` | NEW | Root directory for vertical profiles |
| `profiles/private_credit/profile.yaml` | NEW | 14-chapter definitions extracted from `memo_chapter_engine.py` |
| `profiles/private_credit/prompts/ch01_exec.j2` … `ch14_governance_stress.j2` | MIGRATE | Move from `ai_engine/prompts/intelligence/` |
| `profiles/private_credit/prompts/evidence_law.j2` | MIGRATE | Move from `ai_engine/prompts/intelligence/` |
| `profiles/private_credit/output_schema.json` | NEW | Formalize the IC memo JSON schema |
| `profiles/private_credit/evaluation_criteria.yaml` | NEW | Extract from `ai_engine/validation/` configs |
| `profiles/liquid_funds/profile.yaml` | NEW | 7-chapter fund manager DD profile |
| `profiles/liquid_funds/prompts/*.j2` | NEW | New prompts for wealth management |
| `backend/ai_engine/intelligence/deep_review.py` | EXTEND | Load chapter config from profile YAML instead of hardcoded `_CHAPTER_TAGS` |
| `backend/ai_engine/intelligence/memo_chapter_engine.py` | EXTEND | Read from profile, dynamic `_CHAPTER_TAGS` |
| `backend/ai_engine/intelligence/memo_chapter_prompts.py` | EXTEND | Budgets/affinity move to profile YAML |
| `backend/ai_engine/prompts/registry.py` | EXTEND | Add profile-aware search path: `profiles/{profile}/prompts/` |
| `backend/ai_engine/model_config.py` | EXTEND | Support profile-prefixed stages: `{profile}.ch01` |
| `backend/ai_engine/intelligence/deep_review_prompts.py` | EXTEND | `_pre_classify_from_corpus()` becomes profile-aware |
| `backend/ai_engine/intelligence/ic_critic_engine.py` | EXTEND | `INSTRUMENT_TYPE_PROFILES` → profile YAML |

---

## C. Dependency Graph

```
Transformation 0 (Repo Separation)
    ├── Can start IMMEDIATELY (rename + .gitignore frontend)
    │
    ├─── Transformation 1 (Multi-tenancy) ──────────┐
    │        ↓ (hard dependency)                     │
    │    Transformation 2 (Auth → Clerk)             │ These three are
    │        ↓ (hard dependency)                     │ SEQUENTIAL
    │    Clerk org membership provides org_id ───────┘
    │
    ├─── Transformation 3 (Upload SAS + SSE) ── can run IN PARALLEL with T1/T2
    │        ↓ (soft dependency on T4 for SSE consumption)
    │
    ├─── Transformation 6 (Vertical Profiles) ── can run IN PARALLEL with T1/T2/T3
    │        No dependency on auth or tenancy
    │
    └─── Transformation 4 (UI5 → SvelteKit) ── DEPENDS ON T2 (Clerk SDK) + T3 (SSE)
             ↓ (includes)
         Transformation 5 (Dashboard Redesign) ── part of T4
```

**Execution order with rationale:**

1. **T0 (Repo Separation)** — First. Architectural prerequisite. Low risk, zero code changes.
2. **T6 (Vertical Profiles)** — Second. Can start immediately, no dependencies. Backend-only refactor. Enables demo with `liquid_funds` profile.
3. **T1 (Multi-tenancy)** — Third. Database-level change. Additive migrations (nullable first). Must complete before T2.
4. **T3 (Upload SAS + SSE)** — Can run in PARALLEL with T1. Backend-only. Enables upload progress demo.
5. **T2 (Auth → Clerk)** — After T1. Depends on organization_id being in the schema. Clerk provides org membership.
6. **T4+T5 (Frontend + Dashboard)** — Last. Depends on T2 (Clerk SDK for Svelte) and T3 (SSE for streaming). Most effort, least risk to backend.

**What breaks if executed out of order:**
- T2 before T1: Clerk org claims have no `organization_id` column to map to
- T4 before T2: SvelteKit has no auth provider
- T4 before T3: No SSE endpoints for streaming
- T6 at any time: Safe — profiles are additive, fallback to hardcoded defaults

**What can run in parallel:**
- T1 + T3 (multi-tenancy migrations + upload architecture — different code paths)
- T1 + T6 (multi-tenancy + profile extraction — different code paths)
- T3 + T6 (upload architecture + profile extraction — fully independent)

---

## D. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **Credit domain migration underestimated (112 tables → async)** | H | H | Split into 2 sprints: models+routes first, AI engine profile-agnostic second. Each model adapted individually with async session. Integration tests per domain module. |
| 2 | **IC memo pipeline breaks during profile extraction** | M | H | Extract profiles as additive layer with fallback to hardcoded defaults. Run both paths in parallel during transition. Existing tests must stay green at every commit. |
| 3 | **Data migration from Private Credit OS to Analysis Engine** | H | H | Dedicated sprint for data migration tooling. Scripts read from Private Credit DB → write to Analysis Engine with `organization_id`. Idempotent, rerunnable. Test against production snapshot BEFORE cutover. See Section J. |
| 4 | **Redis infra blocks SSE development** | M | M | Redis available via docker-compose from Sprint 0 (local dev). Azure Cache for Redis provisioned in Bicep by Sprint 8. SSE development is never blocked — only production deployment waits for Azure. |
| 6 | **Clerk SSO enterprise pricing surprise** | L | M | Clerk Pro (<500 MAU) is sufficient for Netz. **But:** SAML SSO requires Clerk Enterprise tier (significantly higher cost). Document this before first enterprise client conversation. Not a blocker for Netz. |
| 7 | **Auth regression during Clerk migration** | M | H | Dual auth path: Clerk primary, Entra fallback. Feature flag `AUTH_PROVIDER=clerk\|entra`. `X-DEV-ACTOR` bypass preserved unchanged. |
| 8 | **SSE reliability on Azure Container Apps** | M | M | Add heartbeat event every 15s. Client reconnects with `Last-Event-ID`. Fallback to polling if SSE fails 3 times. |
| 9 | **Frontend scope creep** | H | M | Migrate views in priority order. Each view is a separate PR. Mechanical views first (Portfolio, Signatures, Cash). Design-decision views last (Dashboard, AI streaming). |
| 10 | **Performance degradation from RLS** | M | M | Index `organization_id` on every table. Test query plans with EXPLAIN ANALYZE. RLS policies use session variable (`SET app.organization_id`) which PG optimizes. |
| 11 | **Service Bus topic names break workers** | L | H | Non-negotiable: `document-pipeline`, `compliance-pipeline`, `memo-generation` never change. |
| 12 | **Four-eyes bank account constraint lost** | L | H | Constraint is domain logic (`counterparties/routes.py`), not auth layer. Clerk JWT provides `actor_id` — same enforcement. Integration test verifies four-eyes rejection. |
| 13 | **Blob Storage + AI Search vector migration** | M | H | Documents in Azure Blob and vectors in AI Search belong to the Private Credit OS deployment. Data migration tooling must handle blob URI remapping and search index recreation. Plan in Sprint dedicated to data migration. |

---

## E. Sprint Plan (FINAL — 10 sprints, one product, concentrated energy)

> **Principle:** One repo, one backlog, one CI pipeline. Zero development on legacy repos.
> Both `netz-private-credit-os` and `netz-wealth-os` are archived after their content migrates.

### Sprint 0 — Foundation (Week 1-2)

**Goal:** Create `netz-analysis-engine` with Wealth OS stack. Docker-compose running. Core infrastructure operational.

**Key deliverables:**
- New GitHub repo `netz-analysis-engine`
- `docker-compose.yml` (PG 16 + TimescaleDB + Redis 7 — from Wealth OS)
- `backend/app/core/db/` — async SQLAlchemy + asyncpg
- `backend/app/core/config/` — merged Pydantic Settings + YAML config loading
- `backend/app/core/tenancy/middleware.py` — `organization_id` on all tables from day one
- `backend/app/core/security/clerk_auth.py` — Clerk JWT + dev token bypass
- `backend/app/core/jobs/` — Redis pub/sub SSE job tracker
- `Makefile`, `pyproject.toml`, CI/CD scaffold

**Acceptance criteria:**
- [ ] `docker-compose up` starts PG 16 + TimescaleDB + Redis 7
- [ ] FastAPI app starts with health endpoint
- [ ] Clerk JWT verification works (dev token mode)
- [ ] `organization_id` RLS context set per request
- [ ] SSE endpoint streams test events via Redis pub/sub
- [ ] `make check` passes

**CE cycle:** Plan → Work → Review

---

### Sprint 1 — Wealth Domain + Quant Engine (Week 3-4)

**Goal:** Migrate Wealth OS backend entirely into the engine.

**Key deliverables:**
- `backend/app/domains/wealth/models/` — 12 tables with `organization_id`
- `backend/quant_engine/` — CVaR, regime, optimizer, scoring, drift, rebalance, momentum, Lipper, backtest
- `backend/app/domains/wealth/routes/` — 26 endpoints
- `backend/worker_app/wealth/` — 7 CLI workers (ingestion, risk calc, portfolio eval, FRED, Bayesian CVaR, regime fit, drift)
- `calibration/` — blocks.yaml, profiles.yaml, limits.yaml, scoring.yaml
- Alembic migration `0001_wealth_domain.py`

**Acceptance criteria:**
- [ ] All 26 Wealth API endpoints functional
- [ ] TimescaleDB hypertables created (nav_timeseries, fund_risk_metrics)
- [ ] `make pipeline` runs full daily pipeline
- [ ] SSE risk stream works via Redis pub/sub
- [ ] All Wealth OS tests passing

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 2 — Credit Domain: Models & Routes (Week 5-6)

**Goal:** Migrate Private Credit OS domain models and routes. 112 tables adapted to async + `organization_id`.

**Key deliverables:**
- `backend/app/domains/credit/` — all 10 domain modules
- 112 tables: `FundScopedMixin` + `OrganizationScopedMixin`, psycopg → asyncpg
- Route handlers adapted to async session
- `require_fund_access()` extended with org_id check
- Alembic migration `0002_credit_domain.py`

**Acceptance criteria:**
- [ ] All credit CRUD endpoints functional
- [ ] RBAC roles enforced
- [ ] Four-eyes bank account constraint verified
- [ ] Document upload works (sync, not yet SAS)
- [ ] `make check` passes

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 3 — AI Engine + Profile Extraction (Week 7-8)

**Goal:** Migrate AI engine. Make it profile-agnostic. Build upload architecture.

**Key deliverables:**
- `backend/ai_engine/` — deep_review, extraction, ingestion, validation, governance, prompts
- `profiles/private_credit/profile.yaml` — 14 chapters, budgets, affinity, model routing
- `profiles/private_credit/prompts/*.j2` — all chapter prompts
- `ProfileLoader` class + dynamic chapter iteration
- Upload: SAS URL + upload-complete → Service Bus → SSE job stream
- Workers: extraction, ingest, compliance, memo generation

**Acceptance criteria:**
- [ ] `generate_ic_memo(profile="private_credit")` produces identical output
- [ ] Zero private-credit-specific logic in deep_review or memo_chapter_engine
- [ ] SAS URL upload + SSE progress stream end-to-end
- [ ] Workers emit progress events visible via SSE

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 4 — @netz/ui + Credit Frontend Core (Week 9-10)

**Goal:** Shared design system + credit frontend scaffold with Clerk auth.

**Key deliverables:**
- `packages/ui/` — @netz/ui: Tailwind tokens, shadcn-svelte components, FCL layout, sidebar
- `frontends/credit/` — SvelteKit 2 + TypeScript + Vite
- Clerk SDK integration (sign-in, sign-out, org switching)
- Typed API client matching engine endpoints
- paraglide-js i18n (880+ keys ported)
- `routes/(investor)/` — investor portal (overview, documents, performance, tax FAQ)

**Acceptance criteria:**
- [ ] SvelteKit app builds and authenticates via Clerk
- [ ] FCL layout renders (three columns, responsive)
- [ ] API calls work against engine backend
- [ ] Investor routes gated by INVESTOR role
- [ ] i18n keys ported (CI check)

**CE cycle:** Plan → Work → Review

---

### Sprint 5 — Credit Frontend: Mechanical Views (Week 11-12)

**Goal:** All standard table/form pattern views.

**Key deliverables:**
- `routes/portfolio/` + `routes/portfolio/[investmentId]/`
- `routes/signatures/`
- `routes/cash/`
- `routes/reviews/`
- `routes/counterparties/`
- `routes/compliance/`

**Acceptance criteria:**
- [ ] 6 views render with real API data
- [ ] WCAG 2.1 AA, responsive, shadcn-svelte consistent

**CE cycle:** Work → Review

---

### Sprint 6 — Credit Frontend: Dashboard + AI Streaming (Week 13-14) — DEMO-READY

**Goal:** Dashboard redesign + Deals Pipeline + IC Memo streaming + Copilot. **Product is demo-ready after this sprint.**

**Key deliverables:**
- `routes/dashboard/` — action queue, pipeline funnel by stage, AUM, macro
- `routes/deals/` + `routes/deals/[dealId]/` — FCL pipeline + deal detail
- `routes/analysis/[dealId]/` — Deep Review with SSE sentence-fragment streaming
- `routes/copilot/` — Fund Copilot chat
- `routes/reporting/` — FCL 3-column with PDF preview

**Acceptance criteria:**
- [ ] Dashboard shows action queue, pipeline funnel by real stage, AUM
- [ ] IC memo streams sentence fragments per chapter via SSE
- [ ] Upload shows progress bar via SSE
- [ ] All views responsive and accessible
- [ ] **Full investor demo possible**

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 7 — Wealth Frontend (Week 15-16) — BUILT FROM SCRATCH

**Goal:** Build Wealth OS frontend from scratch inside `netz-analysis-engine`, using `@netz/ui` from the first component. No legacy upgrade — clean build.

**Key deliverables:**
- `frontends/wealth/` — SvelteKit 2 + TypeScript + Vite
- `routes/dashboard/` — 3 portfolio cards (conservative/moderate/growth), CVaR gauge, regime chip
- `routes/funds/` — Universe table, scoring columns, expandable detail rows
- `routes/allocation/` — Strategic + tactical weight editors, band indicators
- `routes/risk/` — CVaR timeline (ECharts), regime bands, SSE live updates
- `routes/backtest/` — Async results with polling
- Clerk auth, @netz/ui tokens, Netz Wealth brand

**Acceptance criteria:**
- [ ] All 5 Wealth views functional with real API data
- [ ] SSE risk stream works
- [ ] Clerk auth with org switching
- [ ] Responsive, WCAG 2.1 AA
- [ ] @netz/ui components shared with credit frontend

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 8 — Data Migration Tooling (Week 17-18)

**Goal:** Scripts to migrate production data from Private Credit OS to Analysis Engine.

**Key deliverables:**
- `scripts/migrate_credit_data.py` — FK-ordered, idempotent, checksummed
- Blob Storage URI handling (shared account or remapping)
- Azure AI Search reindexing
- Dry-run mode + full validation report
- Rollback documentation

**Acceptance criteria:**
- [ ] Dry-run against production snapshot: zero errors
- [ ] Full staging migration: all data, all FKs intact
- [ ] IC memo generation works on migrated data
- [ ] AI Search queries return same results

**CE cycle:** Plan → Work → Review → Compound

---

### Sprint 9 — Production Cutover (Week 19-20)

**Goal:** Switch production to unified engine. Archive legacy repos.

**Actions:**
- Maintenance window: freeze writes on Private Credit OS
- Run data migration (execute + verify checksums)
- Deploy engine to Azure Container Apps
- Deploy credit frontend to Azure SWA
- Deploy wealth frontend to Azure SWA
- DNS switch + 48h monitoring
- Archive `netz-private-credit-os` (read-only)
- Archive `netz-wealth-os` (read-only)

**Acceptance criteria:**
- [ ] All users on new system
- [ ] IC memos, uploads, compliance, cash, signatures all functional
- [ ] Wealth dashboard, risk monitor, allocation editor all functional
- [ ] Zero data loss (row counts + checksums)
- [ ] Rollback tested (DNS revert to archived repos)

**CE cycle:** Work → Review → Compound

---

## F. Do Not Touch List

| File/Directory | Reason |
|---|---|
| `backend/ai_engine/extraction/semantic_chunker.py` | Recently fixed critical bug — stable, tested |
| `backend/ai_engine/validation/` | 4-layer evaluation framework — core IP, no changes unless profile extraction |
| `backend/app/core/db/migrations/versions/` (existing files) | Alembic history is immutable — never modify existing migrations |
| `backend/ai_engine/model_config.py` — `get_model()` function signature | Routing logic is stable; extend MODELS dict, don't change resolution function |
| `infra/bicep/main.bicep` | Azure IaC — changes only via explicit infra tickets |
| Service Bus topic names: `document-pipeline`, `compliance-pipeline`, queue `memo-generation` | Workers depend on exact names |
| `backend/ai_engine/openai_client.py` — `create_completion()` / `create_embedding()` | Provider abstraction — stable interface |
| `backend/ai_engine/intelligence/ic_critic_engine.py` — critic loop logic | Adversarial review is calibrated and tested |
| `backend/ai_engine/governance/` | Token budget management — stable |
| `backend/app/domain/counterparties/` — four-eyes bank account logic | Regulatory requirement — preserve exactly |

---

## G. Demo Readiness Checklist

Ordered by impact-to-effort ratio (highest first):

| # | Demo Moment | Required Changes | Effort | Impact |
|---|---|---|---|---|
| 1 | **Dashboard with real deal stages** | Backend: new aggregation endpoint GROUP BY `stage`. Frontend: replace flat "Pipeline" with funnel chart. | Low (1-2 days) | High — shows system intelligence |
| 2 | **Branding: Netz logo + colors** | SvelteKit: Tailwind config with Netz CSS custom properties (`--netzBrand*`). Logo in nav. | Low (0.5 day) | High — professional impression |
| 3 | **FCL navigation: list → detail → preview** | SvelteKit: `+layout.svelte` with CSS Grid three-column. Deals list → deal detail → PDF preview. | Medium (3-4 days) | High — institutional UX |
| 4 | **Generate IC memo → streaming tokens** | Backend: SSE endpoint for memo generation. Frontend: EventSource consuming token stream per chapter. | Medium (3-5 days) | High — "wow" moment for investors |
| 5 | **Upload pitch deck → progress → indexed** | Backend: SAS URL + SSE progress. Frontend: drag-drop upload with progress bar showing chunking/embedding stages. | Medium (3-5 days) | High — demonstrates full pipeline |

**Minimum viable demo (items 1-5): ~2 weeks of focused work.**

**Quick wins that enhance the demo (optional):**
- Action queue banner ("3 deals awaiting IC decision") — 0.5 day
- AI Confidence badge on each deal card — 0.5 day
- Pipeline funnel animation (ECharts) — 1 day

---

## H. Profile Extraction Plan (Transformation 6 Detail)

### Step 1: Define `profile.yaml` schema

```yaml
# profiles/private_credit/profile.yaml
name: private_credit
display_name: "Private Credit IC Memo"
version: 1

chapters:
  - id: ch01_exec
    title: "Executive Summary"
    type: ANALYTICAL
    max_tokens: 4000
    chunk_budget: [20, 4000]
    model_stage: ch01_exec
  - id: ch02_macro
    title: "Macro & Market Context"
    type: ANALYTICAL
    max_tokens: 3000
    chunk_budget: [10, 3000]
    model_stage: ch02_macro
  # ... (all 14 chapters with their current config)
  - id: ch14_governance_stress
    title: "Governance Stress"
    type: ANALYTICAL
    max_tokens: 6000
    chunk_budget: [30, 8000]
    model_stage: ch14_governance_stress

tone_normalization:
  descriptive_max_chars: 10000
  analytical_min_chars: 6000

recommendation_chapter: ch13_recommendation
evidence_law_template: evidence_law.j2
evidence_law_ch13_template: evidence_law_ch13.j2
```

### Step 2: Move prompts (non-breaking)

1. **Copy** (not move) `ai_engine/prompts/intelligence/ch*.j2` → `profiles/private_credit/prompts/`
2. Update `PromptRegistry` to check `profiles/{profile}/prompts/` BEFORE `ai_engine/prompts/intelligence/`
3. Existing templates remain as fallback — zero breakage risk
4. Once verified, delete originals and update search path

### Step 3: Create `ProfileLoader`

```python
# ai_engine/intelligence/profile_loader.py
class ProfileLoader:
    def load(self, profile_name: str) -> AnalysisProfile:
        """Load profile from profiles/{name}/profile.yaml"""
        # Returns dataclass with chapters, prompts_dir, output_schema, etc.

    def get_chapter_tags(self, profile: AnalysisProfile) -> tuple[str, ...]:
        """Return ordered chapter tags from profile config."""

    def get_chapter_budget(self, profile: AnalysisProfile, chapter_tag: str) -> tuple[int, int]:
        """Return (max_chunks, max_chars_per_chunk) from profile config."""
```

### Step 4: Refactor `memo_chapter_engine.py`

**Before:**
```python
_CHAPTER_TAGS = ("ch01_exec", "ch02_macro", ..., "ch14_governance_stress")  # hardcoded
```

**After:**
```python
def get_chapter_tags(profile: AnalysisProfile | None = None) -> tuple[str, ...]:
    if profile:
        return tuple(ch.id for ch in profile.chapters)
    return _DEFAULT_CHAPTER_TAGS  # fallback for backward compat
```

### Step 5: Refactor `deep_review.py`

**Current:** `async_run_deal_deep_review_v4()` hardcodes 14 chapters.
**New parameter:** `profile_name: str = "private_credit"` (default preserves behavior).
**Change:** Load profile → iterate profile.chapters instead of hardcoded list.

### Step 6: Extend `model_config.py`

Support profile-prefixed stages:
```python
def get_model(stage: str, profile: str | None = None) -> str:
    if profile:
        # Check NETZ_MODEL_{PROFILE}_{STAGE} first
        env_key = f"NETZ_MODEL_{profile.upper()}_{stage.upper()}"
        # Then check profile-specific MODELS dict
        # Then fall through to default MODELS dict
    ...
```

### Step 7: Keep tests green

- All existing tests call `run_deal_deep_review_v4()` without `profile_name` → default = `private_credit`
- Add new tests for `profile_name="liquid_funds"` with 7-chapter output
- Profile loader has its own unit tests

### Migration safety: At every step, the existing pipeline must produce identical output. The profile is additive — never subtractive.

---

## I. API Contract for Engine ↔ Frontend

### Authentication

All requests include:
```
Authorization: Bearer <clerk_jwt>
```
JWT contains: `org_id` (maps to `organization_id`), `sub` (user ID), `org_role` (maps to RBAC Role).

Dev bypass preserved:
```
X-DEV-ACTOR: {"actor_id": "dev", "roles": ["ADMIN"], "fund_ids": ["..."], "org_id": "..."}
```

### Tenant Context

`organization_id` is extracted from JWT `org_id` claim by middleware. Never passed explicitly in URL or body.
`fund_id` remains in URL path: `/funds/{fund_id}/...`

### Upload Flow

```
POST /api/v1/documents/upload-url
  Body: { fund_id, filename, content_type, root_folder, subfolder_path? }
  Response: { upload_id, sas_url, blob_path, expires_at }

PUT {sas_url}
  (Direct to Azure Blob Storage — browser XHR with progress events)
  Headers: x-ms-blob-type: BlockBlob, Content-Type: {content_type}

POST /api/v1/documents/upload-complete
  Body: { upload_id, blob_path, fund_id }
  Response: { job_id, document_id, version_id }

GET /api/v1/jobs/{job_id}/stream
  Response: text/event-stream
  Events:
    event: chunking_started\ndata: {"document_id": "...", "file_name": "..."}\n\n
    event: ocr_complete\ndata: {"pages": 47}\n\n
    event: chunks_created\ndata: {"count": 312}\n\n
    event: embeddings_progress\ndata: {"pct": 60}\n\n
    event: search_indexed\ndata: {"vectors": 312}\n\n
    event: ingestion_complete\ndata: {"deal_id": "...", "chunks": 312}\n\n
    event: error\ndata: {"stage": "ocr", "message": "..."}\n\n
    event: heartbeat\ndata: {}\n\n  (every 15s)
```

### Profile-Aware Analysis

```
POST /api/v1/funds/{fund_id}/deals/{deal_id}/deep-review
  Body: { force?: bool, profile?: "private_credit" | "liquid_funds" }
  Response: { job_id }
  (Enqueues to memo-generation Service Bus queue)

GET /api/v1/jobs/{job_id}/stream
  Events:
    event: chapter_started\ndata: {"chapter": 1, "tag": "ch01_exec", "title": "Executive Summary"}\n\n
    event: chapter_token\ndata: {"chapter": 1, "delta": "The "}\n\n
    event: chapter_token\ndata: {"chapter": 1, "delta": "proposed "}\n\n
    event: chapter_complete\ndata: {"chapter": 1, "chars": 8500}\n\n
    event: critic_started\ndata: {}\n\n
    event: critic_complete\ndata: {"fatal_flaws": 0, "gaps": 2}\n\n
    event: memo_complete\ndata: {"memo_id": "...", "recommendation": "INVEST", "confidence": "HIGH"}\n\n
```

### Existing Endpoints (preserved, paths unchanged)

All current `/funds/{fund_id}/...` and `/api/...` endpoints remain unchanged per constraint. Key endpoints consumed by frontend:

```
GET  /api/v1/funds/{fund_id}/pipeline-deals          → list pipeline deals
GET  /api/v1/funds/{fund_id}/pipeline-deals/{id}      → deal detail
GET  /api/v1/funds/{fund_id}/portfolio/assets          → list assets
GET  /api/v1/funds/{fund_id}/portfolio/fund-investments → list fund investments
GET  /api/v1/funds/{fund_id}/compliance/obligations    → list obligations
GET  /api/v1/funds/{fund_id}/cash/transactions         → list transactions
GET  /api/v1/funds/{fund_id}/signatures/queue          → signature queue
GET  /api/v1/funds/{fund_id}/reporting/packs           → report packs
GET  /api/v1/funds/{fund_id}/document-reviews          → document reviews
GET  /api/v1/funds/{fund_id}/dashboard/summary         → dashboard aggregation
POST /api/v1/funds/{fund_id}/agent/query               → Fund Copilot
```

### New Endpoints (added for platform)

```
GET  /api/v1/organizations/current                     → current org profile + config
GET  /api/v1/profiles                                  → list available analysis profiles
GET  /api/v1/profiles/{profile_name}                   → profile metadata (chapters, schema)
POST /api/v1/documents/upload-url                      → SAS URL generation
POST /api/v1/documents/upload-complete                 → confirm upload + enqueue
GET  /api/v1/jobs/{job_id}/stream                      → SSE job progress
GET  /api/v1/funds/{fund_id}/dashboard/action-queue    → pending actions count
GET  /api/v1/funds/{fund_id}/dashboard/pipeline-funnel → deals grouped by stage
```

---

## Key Decisions

1. **One product, concentrated energy** — No parallel development on legacy repos. `netz-wealth-os` archived (backend migrates, frontend rebuilt from scratch). `netz-private-credit-os` archived after data migration. Everything in `netz-analysis-engine`.
2. **Wealth OS stack as foundation** — PG 16 + TimescaleDB + asyncpg + Redis 7 + Python 3.12. Objectively superior. Private Credit contributes domain richness + AI engine.
3. **Wealth frontend rebuilt, not upgraded** — The existing Wealth OS SvelteKit frontend is archived. A new `frontends/wealth/` is built from scratch with `@netz/ui` from the first component. No legacy debt.
4. **Monorepo with vertical frontends** — Both frontends live inside `netz-analysis-engine` (`frontends/credit/`, `frontends/wealth/`). One CI, one backlog, one `make check`.
5. **Redis in docker-compose from Sprint 0** — Never block SSE development. Local Redis immediately; Azure Cache for Redis provisioned for production.
6. **Clerk over Entra ID** — native multi-org, Svelte SDK, <500 MAU Pro tier. Note: SAML SSO requires Enterprise tier for future enterprise clients.
7. **Profile as YAML + Jinja2** — Editable by non-developers. `liquid_funds` chapters are draft; engine supports adding/removing chapters without code changes.
8. **Sentence-fragment streaming** — IC memo streams buffered phrases (~50-100 chars per event, ~2-5 events/sec).
9. **Multi-tenancy from day one** — `organization_id` on all tables from the first Alembic revision, **except global reference tables** (`macro_data`, `allocation_blocks`) where data is shared across all tenants.
10. **Async-first architecture** — All DB operations use asyncpg. Private Credit models adapted to fully async on migration.
11. **Advisor portal as routes** — Integrated into credit frontend under `routes/(investor)/`, gated by INVESTOR role.
12. **Dedicated data migration sprint** — Sprint 8. Scripts, dry-runs, checksums. Not an afterthought.
13. **Credit domain split into 2 sprints** — Sprint 2 (models + routes) and Sprint 3 (AI engine + profiles).

## J. Data Migration Strategy

> **This section was added based on stakeholder review. Data migration is the hardest problem in this transformation — plan it now, not at the end.**

### What needs to migrate from `netz-private-credit-os` production

| Data Source | Volume | Migration Approach |
|---|---|---|
| PostgreSQL (112 tables, 51 migrations of history) | ~100K-1M rows | `scripts/migrate_credit_data.py` — reads source DB, writes to engine DB with `organization_id` |
| Azure Blob Storage (dataroom, evidence, monthly-reports containers) | ~10-100 GB | Option A: Share storage account (zero migration, just remap URIs). Option B: Copy to new account (clean separation). |
| Azure AI Search (global-vector-chunks-v4 index) | ~500K vectors | Reindex from migrated DB using existing embedding pipeline. Vectors are reproducible from chunk text. |
| Alembic migration history | 51 versions | New repo starts fresh (`0001_*`). Legacy history preserved in old repo. No history merge. |

### Migration script design principles

1. **Dependency-ordered:** Tables migrated in FK dependency order (parents before children)
2. **Idempotent:** Safe to rerun — uses UPSERT (ON CONFLICT DO UPDATE), not INSERT
3. **Organization-injected:** Every row gets `organization_id = '<netz-org-uuid>'`
4. **Checksummed:** Row count + checksum comparison per table (source vs destination)
5. **Dry-run mode:** `--dry-run` validates all data without writing
6. **Blob URI mapping:** Configurable: same storage account (URI unchanged) or new account (prefix rewrite)
7. **Resumable:** Tracks last-migrated ID per table in a state file

### Migration sequence (maintenance window)

```
1. Freeze writes on Private Credit OS (read-only mode)
2. Run migrate_credit_data.py --dry-run (validate)
3. Run migrate_credit_data.py (execute)
4. Verify checksums (automated)
5. Reindex Azure AI Search from migrated DB
6. Smoke test: generate IC memo on migrated deal
7. Switch DNS to netz-analysis-engine
8. Monitor 48h
9. If rollback needed: switch DNS back (old system was never touched)
```

### Advisor Portal Decision

**Decision:** The advisor portal (currently `advisor-portal/` in Private Credit OS, Next.js) is **integrated as routes within `netz-credit-intelligence`** under `routes/(investor)/`, gated by the `INVESTOR` role in Clerk.

**Rationale:** The advisor portal serves a different audience (investors/LPs, not IC team) but consumes the same API. Separate deployment means separate auth, separate hosting, separate CI — unnecessary overhead. Role-based routing within one SvelteKit app is simpler:

```
netz-credit-intelligence/
├─ routes/(team)/              ← IC team views (ADMIN, GP, INVESTMENT_TEAM, COMPLIANCE)
│  ├─ dashboard/
│  ├─ deals/
│  ├─ portfolio/
│  ├─ compliance/
│  └─ ...
├─ routes/(investor)/          ← Investor views (INVESTOR, ADVISOR roles)
│  ├─ overview/               ← Portfolio summary
│  ├─ documents/              ← Fund docs access
│  ├─ performance/            ← NAV, returns
│  └─ tax-faq/                ← Tax information
└─ +layout.svelte             ← Clerk auth, role-based sidebar menu
```

---

## Resolved Questions

1. **Redis provisioning** — Azure Cache for Redis is **not yet provisioned**. Must be added to `infra/bicep/main.bicep` as part of Sprint 2. This is a new infrastructure dependency.
2. **Clerk pricing** — Expected scale is **under 500 MAU**. Clerk Pro tier is more than sufficient. Pricing is not a blocker for the auth migration.
3. **Wealth OS profile** — The 7 chapters for `liquid_funds` are **draft and may change**. Sprint 4 should focus on making the engine profile-agnostic with `private_credit` only. Build the profile system to be flexible — don't lock in `liquid_funds` chapter list yet. Add it as a second profile once the Wealth OS product design stabilizes.
4. **Token streaming granularity** — Decision: **sentence fragments** (~2-5 events/sec, buffered at ~50-100 chars or sentence boundaries). Smooth phrase-by-phrase streaming that still feels real-time. Simpler frontend than token-level, still impressive for demos.
5. **Existing UI5 deployment timeline** — **No timeline decided yet**. UI5 remains operational until confidence in SvelteKit is high. Sprint 8 (cutover) timing will be determined based on SvelteKit stability. Plan for the possibility of extended parallel running.

---

## Executive Summary

Two existing Netz products — Private Credit OS (AI-powered deal underwriting) and Wealth OS (quantitative portfolio analytics) — are being unified into a single multi-tenant B2B SaaS platform called the **Netz Analysis Engine**. A new repository is built using the Wealth OS's superior technical foundation (PostgreSQL 16, TimescaleDB, async Python 3.12, Redis) while incorporating Private Credit's AI engine (14-chapter IC memo pipeline, document extraction, 4-layer evaluation) and domain models (112 tables across 10+ modules). Both legacy repositories are archived — no parallel development, all energy concentrated in one repo, one backlog, one CI pipeline. Two vertical frontends (credit and wealth) live inside the same repo, sharing a `@netz/ui` design system built on SvelteKit 2, Tailwind CSS 4, and shadcn-svelte. The Wealth frontend is rebuilt from scratch — not upgraded from the existing codebase — ensuring every component is designed for the unified engine from day one. The platform supports multi-tenant organizations via Clerk authentication and PostgreSQL row-level security, with each organization accessing credit and/or wealth analysis verticals via YAML-driven configurable profiles. The credit vertical is demo-ready after Sprint 6 (~14 weeks), the wealth vertical completes in Sprint 7 (~16 weeks), and production cutover happens in Sprint 9 (~20 weeks). A dedicated data migration sprint (Sprint 8) ensures production data moves cleanly with idempotent scripts, checksums, and dry-run validation before any cutover.
