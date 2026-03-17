---
title: "feat: Admin Frontend — Cross-Tenant Dashboard from Scratch"
type: feat
status: active
date: 2026-03-17
deepened: 2026-03-17
origin: docs/brainstorms/2026-03-17-admin-frontend-brainstorm.md
---

# Admin Frontend — Cross-Tenant Dashboard from Scratch

## Enhancement Summary

**Deepened on:** 2026-03-17
**Research agents used:** 9 (Security Sentinel, Architecture Strategist, Performance Oracle, Pattern Recognition, Data Integrity Guardian, Best Practices Researcher, Framework Docs Researcher, Learnings Researcher, SpecFlow Analyzer)

### Critical Findings (must resolve before implementation)

1. **`FORCE ROW LEVEL SECURITY` blocks admin cross-tenant queries.** Migration 0009 enables `FORCE ROW LEVEL SECURITY` on `tenant_assets`, `prompt_overrides`, and `prompt_override_versions`. Without an admin-mode RLS policy, `get_db()` without `SET LOCAL` returns zero rows because `current_setting('app.current_organization_id', true)` returns empty string → NULL comparison fails. **Resolution:** Add admin-mode RLS policies: `OR current_setting('app.admin_mode', true) = 'true'` to existing policies, and add `SET LOCAL app.admin_mode = 'true'` in admin session dependencies.

2. **Super-admin role must be distinct from org-admin.** Clerk's `org:admin` is per-organization. A tenant's org-admin should NOT access the platform admin panel. **Resolution:** Use Clerk user-level custom claim (`publicMetadata.platform_admin: true`) or require membership in a specific "Netz" organization whose `org:admin` maps to `Role.SUPER_ADMIN`. Backend: new `require_super_admin` dependency checks `Role.SUPER_ADMIN`, not `Role.ADMIN`.

3. **`BrandingResponse` uses `extra="allow"` — CSS injection vector.** Any key-value pair in config override passes through to the frontend as CSS custom properties. **Resolution:** Change to `extra="forbid"`. Add JSON Schema guardrails for branding config type: hex regex for colors, enum for fonts, length limits for text.

4. **`adminGuardHook` must skip `publicPrefixes`.** Without this, unauthenticated users cannot reach `/auth/sign-in` (authHook sets no actor for public paths, adminGuardHook rejects undefined actor). **Resolution:** Add path check before role check in adminGuardHook.

5. **Admin session dependencies do not exist.** Need two new FastAPI dependencies: `get_db_admin_read()` (sets `admin_mode=true`, no org RLS) for cross-tenant lists, and `get_db_for_tenant(org_id)` (sets both `admin_mode=true` and `current_organization_id`) for per-tenant writes.

### Key Improvements from Research

6. **Config editor upgrade:** CodeMirror 6 + `codemirror-json-schema` (~150KB bundle) replaces plain textarea. Provides JSON syntax highlighting, schema-driven validation, and autocompletion. Much better than Monaco (~5MB) and far more useful than textarea.
7. **Health polling fix:** Replace `invalidateAll()` (triggers full SSR round trip every 30s) with client-side `$effect` + direct API fetch. SSR only for initial load.
8. **SSE backpressure:** Bounded asyncio.Queue (maxsize=500) on worker log SSE, max 10 concurrent streams (429 if exceeded), client-side ring buffer of 1,000 lines.
9. **PgNotifier with DB trigger:** Use `CREATE TRIGGER config_override_notify AFTER INSERT OR UPDATE OR DELETE` on `vertical_config_overrides` instead of manual `NOTIFY` in ConfigWriter. Guarantees notification on every change including direct SQL.
10. **pg_notify reconnection safety:** Flush entire config cache on reconnection (not just continue). Prevents up to 90s stale data during reconnect window.
11. **SSTI hardened sandbox:** `HardenedPromptEnvironment` with `_BLOCKED_ATTRS` frozenset (13 dangerous attrs), `is_safe_callable` override, and parametric SSTI bypass test suite.
12. **Audit logging:** New `admin_audit_log` table for all admin write operations (config, prompt, tenant, asset changes) with `actor_id`, `action`, `resource_type`, `resource_id`, `before_hash`, `after_hash`, `timestamp`.
13. **Tenant detail as server-routed sub-pages:** `/tenants/[orgId]/branding`, `/tenants/[orgId]/config`, `/tenants/[orgId]/prompts` instead of client-side tabs. Enables deep linking and separate data loading.
14. **Guardrail schema drift handling:** Validate at read time — if merged config violates current guardrails, log WARNING and return default. Add `GET /admin/configs/invalid` endpoint listing all stale overrides.

### Critical Anti-Patterns to Avoid (from research)

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| `get_db()` without admin RLS policy | Zero rows returned due to FORCE ROW LEVEL SECURITY | `get_db_admin_read()` with `SET LOCAL app.admin_mode = 'true'` |
| `org:admin` Clerk role for platform admin | Any tenant's org-admin accesses admin panel | `Role.SUPER_ADMIN` from dedicated Netz org or user metadata claim |
| `BrandingResponse(extra="allow")` | Arbitrary CSS injection via config override fields | `extra="forbid"` + JSON Schema guardrails with hex regex |
| `invalidateAll()` for health polling | Full SSR round trip every 30s (SvelteKit → FastAPI → DB → back) | Client-side `$effect` + direct fetch, SSR only for initial load |
| `adminGuardHook` without public path check | Blocks access to `/auth/sign-in` for unauthenticated visitors | Check `publicPrefixes` before role assertion |
| Stock `SandboxedEnvironment` without dunder blocking | SSTI bypass via `__class__.__mro__` or `lipsum.__globals__` | `HardenedPromptEnvironment` with blocked attrs + callable blocking |
| Unbounded SSE worker log stream | Server memory leak + DOM bloat in long sessions | Bounded queue (500), max connections (10), client ring buffer (1000) |
| Literal routes after parameterized routes | FastAPI route shadowing — `/tenants/health` matched by `/{org_id}` | Register literal routes BEFORE parameterized routes in router |
| Manual `NOTIFY` in ConfigWriter only | Direct SQL changes bypass notification | DB trigger on `vertical_config_overrides` fires `pg_notify` automatically |

### Missing Files Discovered

| File | Purpose | Phase |
|---|---|---|
| `src/app.d.ts` | TypeScript `App.Locals` declaration (actor, token) | 2.1 |
| `src/lib/types.ts` | Admin-specific TypeScript types | 2.1 |
| `vite.config.ts` with port `5175` | Avoid collision with wealth (5174) | 2.1 |
| `backend/app/core/tenancy/admin_middleware.py` | `get_db_admin_read()` + `get_db_for_tenant()` | 1.0 |
| `backend/app/core/security/admin_auth.py` | `require_super_admin` dependency | 1.0 |
| `backend/app/domains/admin/validators.py` | Branding hex/font validation, upload magic bytes | 1.3 |

---

## Overview

Build the admin frontend (`frontends/admin/`) from scratch — the third and final SvelteKit frontend in the monorepo. The admin panel is a super-admin-only cross-tenant dashboard for managing tenants, editing configs/branding/prompts, and monitoring system health. Unlike Wealth and Credit (which were redesigned from existing code), admin has no `src/` directory and starts empty.

**Key differences from Wealth/Credit:**
- **Auth:** ADMIN role required (not org-scoped — cross-tenant access)
- **Theme:** Light default (admin panel, not product)
- **Data:** Configuration and metadata, not financial data
- **Scope:** Cross-tenant (no RLS on admin reads)

## Problem Statement

The Netz platform has no UI for super-admins. Config changes, tenant management, prompt editing, and system health monitoring all require code changes or direct DB access. The admin backend APIs (Phase E from the original platform plan) are partially implemented — migration 0009, asset serving, and branding endpoints exist, but ConfigWriter, PromptService, and most admin routes are missing.

## Proposed Solution

Seven phases — security infrastructure first (Phase 1.0, reviewed before continuing), then backend APIs + scaffold in parallel, then four independent frontend sections (Phases 3-6), then tests (Phase 7).

```
Phase 1.0 → Admin Security Infrastructure (RLS bypass, SUPER_ADMIN, validators)
Phase 1.1 → ConfigWriter + PgNotify (after 1.0 review)
Phase 1.2 → PromptService (after 1.0 review, parallel with 1.1)
Phase 1.3 → Admin Routes + Schemas
Phase 1.4 → Admin Backend Tests
Phase 2   → SvelteKit Scaffold + Auth + Layout (parallel with 1.0)
Phase 3   → Health Dashboard (/health)
Phase 4   → Tenant Management (/tenants, /tenants/[orgId])
Phase 5   → Config Editor (/config/[vertical])
Phase 6   → Prompt Editor (/prompts/[vertical])
Phase 7   → Integration Tests
```

## Technical Approach

### Architecture

```
frontends/admin/
  src/
    app.html                    ← data-theme="light" (admin default)
    app.css                     ← @import "@netz/ui/styles"
    hooks.server.ts             ← Clerk auth + ADMIN role guard + theme hook
    routes/
      +layout.server.ts         ← auth check, pass Actor to client
      +layout.svelte            ← AppLayout with TopNav
      +error.svelte             ← ErrorBoundary
      auth/sign-in/+page.svelte ← Clerk sign-in
      (admin)/
        +layout.svelte          ← admin section layout
        health/                 ← system health dashboard
        tenants/                ← tenant list
        tenants/[orgId]/        ← tenant detail (tabs: overview, branding, config, prompts)
        config/[vertical]/      ← config editor (global defaults)
        prompts/[vertical]/     ← prompt editor (global defaults)
    lib/
      api/client.ts             ← admin API client (createServerApiClient + createClientApiClient)
      types.ts                  ← admin-specific TypeScript types
      components/               ← admin-specific components (7 total)
```

### Backend Status (What Exists vs What's Missing)

| Component | Status | Notes |
|---|---|---|
| Migration 0009 (tenant_assets, prompt_overrides, prompt_override_versions) | DONE | Applied, tables exist |
| `TenantAsset` model + `BrandingResponse` schema | DONE | `backend/app/domains/admin/models.py` |
| `GET /api/v1/branding` | DONE | `backend/app/domains/admin/routes/branding.py` |
| `GET /api/v1/assets/tenant/{org_slug}/{asset_type}` | DONE | `backend/app/domains/admin/routes/assets.py` |
| `ConfigWriter` (write + guardrails + optimistic lock) | MISSING | Phase 1 |
| `PgNotifyListener` (cache invalidation) | MISSING | Phase 1 |
| `PromptService` (cascade resolution + preview + validate) | MISSING | Phase 1 |
| Admin routes (configs, tenants, prompts, health) | MISSING | Phase 1 |
| Admin backend tests | MISSING | Phase 1 |

### Navigation Architecture (see brainstorm: D1)

- **TopNav** — always visible, horizontal. Sections: Health, Tenants, Config, Prompts
- **ContextSidebar** — only inside `/tenants/[orgId]` detail pages. Tabs: Overview, Branding, Config, Prompts
- No OrgSwitcher in admin TopNav — admin is cross-tenant. Org context only when drilling into a specific tenant.

### Auth Model

```
hooks.server.ts:
  1. Clerk JWT verification (JWKS)
  2. Extract role from JWT claims — check for SUPER_ADMIN (not just ADMIN)
  3. adminGuardHook: skip publicPrefixes, then reject non-SUPER_ADMIN → redirect
  4. No organization_id context (cross-tenant)

Backend dependencies (NEW):
  require_super_admin(actor)     → 403 if not Role.SUPER_ADMIN
  get_db_admin_read()            → SET LOCAL app.admin_mode = 'true' (no org RLS)
  get_db_for_tenant(org_id)      → SET LOCAL admin_mode + current_organization_id

Per-tenant operations:
  - Backend receives org_id as path param
  - Uses get_db_for_tenant(org_id) which sets both admin_mode and org context
  - RLS policies allow access when admin_mode = 'true'
```

#### Research Insights: Admin Auth

**Super-admin role (from Security Sentinel + SpecFlow):**
- Clerk's `org:admin` is per-organization — a tenant's org-admin must NOT access the admin panel
- Use Clerk user-level `publicMetadata.platform_admin: true` or membership in a dedicated "Netz" organization
- Backend maps this to `Role.SUPER_ADMIN` (new enum value), distinct from `Role.ADMIN`
- `require_super_admin` dependency at `backend/app/core/security/admin_auth.py`

**RLS bypass (from Data Integrity Guardian — CRITICAL):**
- Migration 0009 uses `FORCE ROW LEVEL SECURITY` on admin tables
- Without special handling, even the table owner role is subject to RLS
- `get_db()` alone returns zero rows because `current_setting('app.current_organization_id', true)` returns empty → NULL comparison fails
- Solution: Add `OR current_setting('app.admin_mode', true) = 'true'` to RLS policies on `tenant_assets`, `prompt_overrides`, `prompt_override_versions`
- New migration (Phase 1.0) updates RLS policies to include admin bypass

**Admin session dependencies (from Architecture Strategist):**
```python
# backend/app/core/tenancy/admin_middleware.py

async def get_db_admin_read() -> AsyncGenerator[AsyncSession, None]:
    """Cross-tenant reads. Sets admin_mode but no org context."""
    async with async_session_factory() as session, session.begin():
        await session.execute(text("SET LOCAL app.admin_mode = 'true'"))
        yield session

async def get_db_for_tenant(org_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """Per-tenant writes. Sets admin_mode + org context for RLS."""
    async with async_session_factory() as session, session.begin():
        await session.execute(text("SET LOCAL app.admin_mode = 'true'"))
        await session.execute(
            text(f"SET LOCAL app.current_organization_id = '{org_id}'")
        )
        yield session
```

---

## Implementation Phases

### Phase 1: Admin Backend APIs

**Goal:** All backend endpoints required by the admin frontend. Completes E2-E5 from the original platform plan.

**Prerequisite:** None (backend already has migration 0009 + models).

#### 1.0: Admin Security Infrastructure (isolated for early review — from deepening)

**Risk isolation:** This sub-phase concentrates all security-critical changes (RLS bypass, SUPER_ADMIN, branding validation). Implemented and reviewed BEFORE 1.1/1.2 to catch P1 security issues early without blocking business logic review.

##### Files

```
backend/app/core/db/migrations/versions/XXXX_admin_rls_bypass.py  ← new migration (verify head before numbering!)
backend/app/core/tenancy/admin_middleware.py                      ← new
backend/app/core/security/admin_auth.py                           ← new
backend/app/domains/admin/validators.py                           ← new
backend/app/shared/enums.py                                       ← extend Role enum
```

##### Tasks

- [ ] **CRITICAL: Verify migration head before numbering.** Sprint 6 created 0013 + 0014. If Sprint 6 PR is not yet merged when implementation starts, the agent may see an older head and generate a conflicting migration number. Run `ls backend/app/core/db/migrations/versions/` and use `down_revision` matching the actual latest file.
- [ ] **Migration XXXX** — Update RLS policies on `tenant_assets`, `prompt_overrides`, `prompt_override_versions` to include admin bypass:
  ```sql
  -- For each admin table:
  DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};
  CREATE POLICY {table}_tenant_isolation ON {table}
    USING (
      organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
      OR current_setting('app.admin_mode', true) = 'true'
    );
  ```
- [ ] **Migration XXXX** — Add `admin_audit_log` table (from Security review):
  ```sql
  CREATE TABLE admin_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id text NOT NULL,
    action text NOT NULL,           -- 'config.update', 'prompt.update', 'tenant.create', 'asset.upload'
    resource_type text NOT NULL,    -- 'config', 'prompt', 'tenant', 'asset'
    resource_id text NOT NULL,
    target_org_id uuid,
    before_hash text,               -- sha256 of previous value (not full content)
    after_hash text,
    created_at timestamptz DEFAULT now()
  );
  -- NO RLS — admin-only table, cross-tenant by design
  ```
- [ ] Add `Role.SUPER_ADMIN` to `backend/app/shared/enums.py`
- [ ] `admin_auth.py` — `require_super_admin` dependency:
  - Check `Role.SUPER_ADMIN in actor.roles`
  - Return 403 if not super-admin
  - For destructive ops (tenant delete, prompt edit): additionally verify `actor.organization_slug in ("netz", "netz-capital")`
- [ ] `admin_middleware.py` — `get_db_admin_read()` and `get_db_for_tenant(org_id)` dependencies (see Auth Model section)
- [ ] `validators.py` — Branding validation:
  - `_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")` for all color fields
  - `_CURATED_FONTS` frozenset for font fields (no free-text)
  - `validate_branding_tokens(data)` — validates all fields, rejects CSS injection chars `{};<>`
  - `validate_image_magic_bytes(data, content_type)` — PNG (`\x89PNG`), JPEG (`\xff\xd8\xff`), ICO (`\x00\x00\x01\x00`)
  - `strip_exif(data)` — strip EXIF metadata from JPEG uploads (via Pillow if available)

##### Acceptance Criteria

- [ ] RLS policies allow admin-mode bypass
- [ ] `require_super_admin` rejects org-level admins
- [ ] Branding validators reject CSS injection
- [ ] `make check` passes

#### 1.1: ConfigWriter + PgNotify

##### Files

```
backend/app/core/config/config_writer.py     ← new
backend/app/core/config/pg_notify.py         ← new
backend/app/core/config/config_service.py    ← extend with invalidate()
backend/app/main.py                          ← register PgNotifyListener in lifespan
```

##### Tasks

- [ ] `config_writer.py` — `ConfigWriter` class:
  - `async put(vertical, config_type, org_id, config, version)` — upsert override. Validate against `VerticalConfigDefault.guardrails` (JSON Schema via `jsonschema.validate()`). For branding config_type, additionally run `validate_branding_tokens()`. Optimistic lock: single atomic UPDATE:
    ```sql
    UPDATE vertical_config_overrides
    SET config = :config, version = version + 1, updated_at = now()
    WHERE vertical = :vertical AND config_type = :type
      AND organization_id = :org_id AND version = :expected
    ```
    If `rowcount == 0`, return 409. For first override (INSERT path): `INSERT ... ON CONFLICT DO UPDATE` with version check. Audit log write after success.
  - `async delete(vertical, config_type, org_id)` — remove override (fallback to default). Audit log.
  - `async put_default(vertical, config_type, config)` — update global default (super-admin only). Audit log.
  - `async diff(vertical, config_type, org_id)` — return `{default, override, merged, changed_keys}` (changed_keys simplifies frontend diff rendering)
  - `async validate_override(vertical, config_type, config)` — dry-run guardrail validation, return errors without persisting
- [ ] `pg_notify.py` — `PgNotifier` class (from best practices research):
  - Dedicated `asyncpg.connect()` (NOT from pool — pool drops listeners on release)
  - TCP keepalives instead of `SELECT 1` health polling: `keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3`
  - `subscribe(channel, handler)` API — register handlers before `start()`
  - `LISTEN config_changed` on startup (triggered by DB trigger, not manual NOTIFY)
  - On notification: invalidate specific TTLCache key `(vertical, config_type, org_id)`
  - **On reconnection: flush entire `_config_cache`** (prevents up to 90s stale data during reconnect window)
  - Exponential backoff reconnect (1s → 30s cap)
  - Graceful shutdown: cancel listener task in lifespan teardown `yield` block
- [ ] **DB trigger** (in migration 0015) — auto-fires `pg_notify` on every config change:
  ```sql
  CREATE OR REPLACE FUNCTION notify_config_change() RETURNS trigger AS $$
  BEGIN
    PERFORM pg_notify('config_changed', json_build_object(
      'vertical', COALESCE(NEW.vertical, OLD.vertical),
      'config_type', COALESCE(NEW.config_type, OLD.config_type),
      'organization_id', COALESCE(NEW.organization_id, OLD.organization_id)::text
    )::text);
    RETURN NEW;
  END;
  $$ LANGUAGE plpgsql;

  CREATE TRIGGER config_override_notify
    AFTER INSERT OR UPDATE OR DELETE ON vertical_config_overrides
    FOR EACH ROW EXECUTE FUNCTION notify_config_change();
  ```
- [ ] Extend `ConfigService` with `invalidate(vertical, config_type, org_id)` method
- [ ] Increase `TTLCache(maxsize=2048)` (from 128) — prevents cache thrashing with multi-tenant config writes
- [ ] Add `max_depth=20` guard to `deep_merge()` — prevents recursion bomb from deeply nested overrides
- [ ] Register `PgNotifier` in FastAPI lifespan (`main.py`) with graceful shutdown
- [ ] **Guardrail schema drift** (from Data Integrity review): when `ConfigService.get()` returns merged config, validate against current guardrails. If invalid, log WARNING and return default config (ignoring stale override). Add `GET /admin/configs/invalid` endpoint listing all overrides failing current guardrails.

##### Acceptance Criteria

- [ ] Config write validates against guardrails (422 on invalid)
- [ ] Optimistic lock rejects stale writes (409) — both UPDATE and INSERT paths
- [ ] DB trigger fires `pg_notify` on every config change (including direct SQL)
- [ ] PgNotifier reconnection flushes entire cache
- [ ] PgNotifier graceful shutdown in lifespan teardown
- [ ] Stale overrides detected and reported via `/admin/configs/invalid`
- [ ] `make check` passes

#### 1.2: PromptService

##### Files

```
backend/app/core/prompts/prompt_service.py    ← new
backend/app/core/prompts/schemas.py           ← new
backend/app/core/prompts/__init__.py          ← new
```

##### Tasks

- [ ] `PromptService` with cascade resolution:
  1. `prompt_overrides` WHERE `organization_id = org_id` (org-specific)
  2. `prompt_overrides` WHERE `organization_id IS NULL` (global override)
  3. Filesystem `.j2` via `PromptRegistry` (fallback)
- [ ] `async get(vertical, template_name, org_id)` → `{content, source_level, version}`
- [ ] `async put(vertical, template_name, org_id, content, updated_by)` → write override, bump version, write history row
- [ ] `async list_templates(vertical)` → all templates with override status per org
- [ ] `async preview(vertical, template_name, content, sample_data)` → render with `HardenedPromptEnvironment`:
  - `_BLOCKED_ATTRS` frozenset: `__subclasses__`, `__bases__`, `__mro__`, `__base__`, `__globals__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`, `__code__`, `__func__`, `gi_frame`, `gi_code`, `f_globals`, `f_builtins`, `co_consts`, `co_names`
  - Override `is_safe_attribute()` to block all attrs in `_BLOCKED_ATTRS`
  - Override `is_safe_callable()` to return `False` for all callables
  - Block string `%` operator in `call_binop()` (format string exploitation)
  - Filter whitelist only (`default`, `upper`, `lower`, `title`, `trim`, `round`, `int`, `float`, `length`, `join`, `sort`, `reverse`)
  - Render timeout: 5s via `concurrent.futures.ThreadPoolExecutor` with timeout (not `signal.alarm` — Windows compat)
  - `sample_data` validation: recursive check all values are JSON-primitive types (str, int, float, bool, None, list, dict). Max depth 5, max total size 64KB. Reject objects with methods.
  - `content` max length: 50KB (reject larger templates with 422)
- [ ] `async validate(content)` → parse Jinja2 template, return syntax errors. Also pre-save regex check for dangerous patterns: `__`, `import`, `os.`, `subprocess`, `eval`, `exec`, `getattr`, `lipsum`
- [ ] `snapshot_prompts(vertical, org_id, template_names)` → resolve all prompts at job start, return frozen dict
- [ ] **PromptService/PromptRegistry composition** (from Architecture review): `PromptService.get()` resolves content via DB cascade, falls back to `PromptRegistry.has_template()` + raw source read. Production rendering still goes through `PromptRegistry.render()`. Admin preview uses separate `HardenedPromptEnvironment`. Never duplicate rendering logic.
- [ ] **Prompt preview sample data** (from SpecFlow): Each template type has hardcoded sample data fixtures in `ai_engine/prompts/samples/{template_name}.json`. Preview endpoint loads these when no custom `sample_data` provided. Admin can also supply custom sample data.
- [ ] **Prompt version history pagination** (from Performance review): `GET /versions` defaults to last 50 versions with `LIMIT 50`. Return `has_more` flag for cursor pagination.

##### Acceptance Criteria

- [ ] Cascade resolution: org override > global override > filesystem
- [ ] Preview renders with `HardenedPromptEnvironment`
- [ ] SSTI bypass test suite passes (13 known payloads blocked):
  - `{{ ''.__class__.__mro__[1].__subclasses__() }}`
  - `{{ ''.__class__.__base__.__subclasses__() }}`
  - `{{ config.__class__.__init__.__globals__ }}`
  - `{{ request|attr('__class__') }}`
  - `{{ lipsum.__globals__['os'].popen('id').read() }}`
  - `{{ self._TemplateReference__context }}`
  - `{{ ''|attr('\x5f\x5fclass\x5f\x5f') }}` (hex-encoded dunder)
- [ ] Pre-save regex validation blocks dangerous patterns
- [ ] `sample_data` recursive JSON-primitive validation works
- [ ] Template max length (50KB) enforced
- [ ] Version history paginated (50 per page)
- [ ] `make check` passes

#### 1.3: Admin Routes

##### Files

```
backend/app/domains/admin/routes/configs.py     ← new
backend/app/domains/admin/routes/tenants.py     ← new
backend/app/domains/admin/routes/prompts.py     ← new
backend/app/domains/admin/routes/health.py      ← new
backend/app/domains/admin/schemas.py            ← extend
backend/app/main.py                             ← register new routers
```

##### Tasks

- [ ] All admin routes require `require_super_admin` dependency (NOT `is_admin` — see Phase 1.0)
- [ ] **Route ordering** (from Learnings — FastAPI route shadowing): register literal routes BEFORE parameterized routes at the same path depth. E.g., `/tenants/health` before `/{org_id}`
- [ ] **Config routes** (`/api/v1/admin/configs/`):
  - `GET /` — list all config types with override status
  - `GET /{vertical}/{type}` — get merged config
  - `PUT /{vertical}/{type}` — update override (requires `If-Match: {version}` header, returns 409 if stale)
  - `DELETE /{vertical}/{type}` — remove override
  - `GET /{vertical}/{type}/diff` — show override vs default
  - `PUT /defaults/{vertical}/{type}` — update global default
- [ ] **Tenant routes** (`/api/v1/admin/tenants/`):
  - `GET /` — list all tenants (cross-tenant read, no RLS)
  - `GET /{org_id}` — tenant detail (configs, assets, usage)
  - `POST /` — create tenant (Clerk org + seed configs in DB transaction)
  - `PATCH /{org_id}` — update metadata
  - `POST /{org_id}/seed` — re-seed default configs
  - `POST /{org_id}/assets` — upload logo/favicon (multipart, 512KB max, PNG/JPEG/ICO only — validate via magic bytes, not Content-Type header)
  - `DELETE /{org_id}/assets/{asset_type}` — remove asset
- [ ] **Prompt routes** (`/api/v1/admin/prompts/`):
  - `GET /{vertical}` — list all templates with override status
  - `GET /{vertical}/{name}` — get resolved content + source level
  - `PUT /{vertical}/{name}` — update override (auto-version, history)
  - `POST /{vertical}/{name}/preview` — render with sample data (sandboxed)
  - `POST /{vertical}/{name}/validate` — Jinja2 syntax check
  - `GET /{vertical}/{name}/versions` — version history
  - `POST /{vertical}/{name}/revert/{version}` — revert to specific version
- [ ] **Health routes** (`/api/v1/admin/health/`):
  - `GET /services` — service status (PostgreSQL, Redis, ADLS, Azure Search — connection check + latency)
  - `GET /workers` — worker status (last run, duration, errors from Redis)
  - `GET /pipelines` — pipeline stats (docs processed, queue depth)
  - `GET /usage` — per-tenant usage (API calls, storage)
  - `GET /workers/logs` — SSE stream of worker logs (Redis pub/sub → EventSourceResponse)

##### Schemas to add

```python
# backend/app/domains/admin/schemas.py — additions
# ALL new schemas use extra="forbid" (institutional learning)

class ConfigListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vertical: str
    config_type: str
    has_override: bool
    version: int | None
    updated_at: datetime | None

class ConfigDiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: dict
    override: dict | None
    merged: dict
    changed_keys: list[str]  # from Performance review — simplifies frontend diff

class TenantListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    org_name: str
    org_slug: str
    vertical: str
    config_count: int
    asset_count: int
    created_at: datetime

class TenantDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: uuid.UUID
    org_name: str
    org_slug: str
    configs: list[ConfigListItemResponse]
    assets: list[TenantAssetResponse]

class PromptListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_name: str
    description: str
    source_level: str  # "org" | "global" | "filesystem"
    version: int | None
    has_override: bool

class PromptDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_name: str
    content: str
    source_level: str
    version: int | None

class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=51200)  # 50KB max (from Performance review)
    sample_data: dict  # validated recursively for JSON-primitive types

class PromptPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rendered: str
    errors: list[str]

class ServiceHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: str  # "ok" | "degraded" | "down"
    latency_ms: float | None
    error: str | None

class WorkerStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    last_run: datetime | None
    duration_ms: float | None
    status: str
    error_count: int

class InvalidConfigResponse(BaseModel):
    """Override that fails current guardrails (from Data Integrity review)."""
    model_config = ConfigDict(extra="forbid")
    vertical: str
    config_type: str
    organization_id: uuid.UUID | None
    validation_errors: list[str]
```

##### Acceptance Criteria

- [ ] All admin routes reject non-ADMIN users (403)
- [ ] Config writes validate against guardrails (422)
- [ ] Tenant creation seeds configs atomically
- [ ] Logo upload enforces 512KB + valid content types (magic bytes)
- [ ] Health SSE endpoint streams worker logs
- [ ] `make check` passes

#### 1.4: Admin Backend Tests

##### Files

```
backend/tests/admin/test_config_writer.py
backend/tests/admin/test_prompt_service.py
backend/tests/admin/test_admin_routes.py
```

##### Tasks

- [ ] Test config write + guardrail validation + optimistic lock (409) — both INSERT and UPDATE paths
- [ ] Test prompt cascade resolution (org > global > filesystem)
- [ ] Test prompt preview with `HardenedPromptEnvironment`
- [ ] **SSTI bypass test suite** (parametric — 13 known payloads, all must raise `SecurityError` or `UndefinedError`)
- [ ] Test tenant creation atomicity (Clerk success + DB fail → retryable via `/seed`)
- [ ] Test seed endpoint idempotency (`ON CONFLICT DO NOTHING`)
- [ ] Test asset upload: size limit (512KB), content type validation (magic bytes), EXIF stripping
- [ ] Test health endpoints return correct structure
- [ ] Test `require_super_admin` rejects org-level admins (403)
- [ ] Test `get_db_admin_read()` returns cross-tenant data
- [ ] Test `get_db_for_tenant(org_id)` sets correct RLS context
- [ ] Test branding token validation (hex colors, curated fonts, CSS injection chars rejected)
- [ ] Test route ordering — literal routes not shadowed by parameterized routes
- [ ] Test audit log entries written for all admin write operations
- [ ] Test guardrail schema drift detection (`/admin/configs/invalid` endpoint)

##### Acceptance Criteria

- [ ] All tests pass
- [ ] `make check` passes (all existing 700+ tests + new admin tests)
- [ ] SSTI test suite covers all 13 known bypass vectors

---

### Phase 2: SvelteKit Scaffold + Auth + Layout

**Goal:** Working SvelteKit app with Clerk auth, ADMIN guard, AppLayout, and empty route stubs.

**Prerequisite:** None (can run in parallel with Phase 1 — uses mocked API data initially).

#### 2.1: Package Scaffold

##### Files

```
frontends/admin/package.json
frontends/admin/svelte.config.js
frontends/admin/vite.config.ts
frontends/admin/tsconfig.json
frontends/admin/src/app.html
frontends/admin/src/app.css
frontends/admin/src/app.d.ts         ← MISSING from original plan (Pattern review)
frontends/admin/src/lib/types.ts     ← admin-specific TypeScript types
```

##### Tasks

- [ ] `app.d.ts` — TypeScript `App.Locals` declaration (from Pattern review — both wealth and credit have this):
  ```typescript
  declare global {
    namespace App {
      interface Locals {
        actor: import("@netz/ui/utils").Actor;
        token: string;
      }
    }
  }
  export {};
  ```
- [ ] `package.json` — name: `netz-admin`, same dependency pattern as wealth:
  ```json
  {
    "name": "netz-admin",
    "version": "0.1.0",
    "private": true,
    "type": "module",
    "scripts": {
      "dev": "vite dev",
      "build": "vite build",
      "preview": "vite preview",
      "check": "svelte-check --tsconfig ./tsconfig.json"
    },
    "dependencies": {
      "@netz/ui": "workspace:*"
    },
    "devDependencies": {
      "@fontsource-variable/inter": "^5.0.0",
      "@sveltejs/adapter-node": "^5.0.0",
      "@sveltejs/kit": "^2.0.0",
      "@sveltejs/vite-plugin-svelte": "^5.0.0",
      "svelte": "^5.0.0",
      "svelte-check": "^4.0.0",
      "tailwindcss": "^4.0.0",
      "typescript": "^5.5.0",
      "vite": "^6.0.0"
    }
  }
  ```
- [ ] `svelte.config.js` — adapter-node, alias `$lib: "src/lib"`
- [ ] `vite.config.ts` — same pattern as wealth but port `5175` (wealth uses `5174`, avoids collision)
- [ ] `tsconfig.json` — strict mode
- [ ] `app.html` — `data-theme="light"` (admin default), FOUC prevention script (validates "dark"|"light", defaults to "light")
- [ ] `app.css` — `@import "@netz/ui/styles"`
- [ ] Add Makefile targets: `dev:admin`, `build:admin`

##### Acceptance Criteria

- [ ] `pnpm install` resolves workspace deps
- [ ] `pnpm --filter netz-admin dev` starts without errors

#### 2.2: Auth + Hooks

##### Files

```
frontends/admin/src/hooks.server.ts
frontends/admin/src/routes/+layout.server.ts
frontends/admin/src/routes/+layout.svelte
frontends/admin/src/routes/+error.svelte
frontends/admin/src/routes/auth/sign-in/+page.svelte
frontends/admin/src/lib/api/client.ts
```

##### Tasks

- [ ] `hooks.server.ts`:
  - `authHook` via `createClerkHook()` from `@netz/ui/utils` — same pattern as wealth
  - `adminGuardHook` — **MUST skip `publicPrefixes` paths first** (from Pattern review — without this, unauthenticated users cannot reach `/auth/sign-in`):
    ```typescript
    const PUBLIC_PREFIXES = ["/auth/", "/health"];
    const adminGuard: Handle = async ({ event, resolve }) => {
      if (PUBLIC_PREFIXES.some(p => event.url.pathname.startsWith(p))) {
        return resolve(event);
      }
      const actor = event.locals.actor;
      if (!actor?.roles?.includes("SUPER_ADMIN")) {
        throw redirect(303, "/auth/sign-in?error=unauthorized");
      }
      return resolve(event);
    };
    ```
  - `themeHook` — **extract `createThemeHook()` to `@netz/ui/utils` FIRST** (from Andrei's review — this is the third frontend copying the same 20 lines with only `defaultTheme` differing). Factory signature: `createThemeHook({ defaultTheme: "light" | "dark" })`. Update wealth and credit hooks to use the factory. Then admin uses:
    ```typescript
    const themeHook = createThemeHook({ defaultTheme: "light" });
    ```
  - `sequence(authHook, adminGuardHook, themeHook)`
- [ ] `+layout.server.ts` — pass Actor to client (same pattern as wealth). Fallback to `defaultLightBranding` (verify exists in `@netz/ui/utils`, create if missing — from Pattern review)
- [ ] `+layout.svelte` — AppLayout with TopNav, nav items: Health, Tenants, Config, Prompts
- [ ] `+error.svelte` — Status-code-based error display (match wealth pattern): `BackendUnavailable` for 5xx, inline HTML for 403/404
- [ ] `auth/sign-in/+page.svelte` — Clerk SignIn component
- [ ] `client.ts` — `createServerApiClient` + `createClientApiClient` from `@netz/ui/utils` (NOT `createApiClient` — from Pattern review, that function does not exist) with admin base URL, single-flight 401 gate

##### Acceptance Criteria

- [ ] Non-admin users see redirect to sign-in
- [ ] Admin users see AppLayout with TopNav
- [ ] Theme toggle works (light default, dark supported)
- [ ] `svelte-check` passes with zero errors

#### 2.3: Route Stubs

##### Files

```
frontends/admin/src/routes/(admin)/+layout.svelte
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/routes/(admin)/tenants/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/+page.svelte
frontends/admin/src/routes/(admin)/config/[vertical]/+page.svelte
frontends/admin/src/routes/(admin)/prompts/[vertical]/+page.svelte
```

##### Tasks

- [ ] `(admin)/+layout.svelte` — wrapper for admin pages (optional: breadcrumbs)
- [ ] `(admin)/+page.svelte` — redirect to `/health` (admin landing page — from SpecFlow)
- [ ] Stub each route with `SectionCard` title + `EmptyState` placeholder
- [ ] `/tenants/[orgId]/+layout.svelte` — ContextSidebar with navigation links (server-routed sub-pages, NOT client-side tabs — from SpecFlow, enables deep linking and separate data loading):
  - `/tenants/[orgId]` → Overview
  - `/tenants/[orgId]/branding` → Branding
  - `/tenants/[orgId]/config` → Config
  - `/tenants/[orgId]/prompts` → Prompts

##### Acceptance Criteria

- [ ] All routes render stubs without errors
- [ ] TopNav highlights active section
- [ ] Tenant detail shows ContextSidebar

---

### Phase 3: Health Dashboard

**Goal:** System health monitoring with live worker logs.

**Prerequisite:** Phase 2 (scaffold), Phase 1.3 (health routes).

#### Files

```
frontends/admin/src/routes/(admin)/health/+page.server.ts
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/lib/components/ServiceHealthCard.svelte
frontends/admin/src/lib/components/WorkerLogFeed.svelte
```

#### Tasks

- [ ] `+page.server.ts` — load service health + worker status + pipeline stats from admin health API
- [ ] `ServiceHealthCard.svelte` — card showing service name, status (ok/degraded/down via `StatusBadge`), latency, error message. Uses `MetricCard` layout with semantic status colors (`--netz-success`, `--netz-warning`, `--netz-danger`)
- [ ] Service health grid — 4 cards: PostgreSQL, Redis, ADLS, Azure Search
- [ ] Worker status section — `DataTable` with worker name, last run, duration, status badge, error count
- [ ] Pipeline stats — `MetricCard` row: docs processed, queue depth, error rate
- [ ] `WorkerLogFeed.svelte` — SSE feed of worker logs:
  - Uses `fetch()` + `ReadableStream` (NOT `EventSource` — auth headers needed)
  - Connects to `GET /api/v1/admin/health/workers/logs`
  - Scrollable log feed with auto-scroll (pinned to bottom unless user scrolls up)
  - **Client-side ring buffer cap: 1,000 lines** (from Performance review — prevents DOM bloat in long sessions)
  - Reconnect with 3s delay (admin panels have few concurrent users)
  - **Backend SSE constraints** (from Performance review):
    - Bounded `asyncio.Queue(maxsize=500)` between Redis subscriber and SSE generator (drops oldest on overflow)
    - Max 10 concurrent SSE connections (429 if exceeded)
    - Structured log schema only: `timestamp`, `worker_name`, `level`, `message` (sanitized — never raw tracebacks, from Security review)
    - Periodic JWT re-validation every 60s on the SSE connection (close if expired, from Security review)
    - `Cache-Control: no-store` on SSE responses
  - Cleanup: `onDestroy()` calls `stop()` to prevent leaked connections on page navigation
- [ ] **Auto-refresh: client-side `$effect` + direct API fetch** (from Performance review — NOT `invalidateAll()` which triggers full SSR round trip):
  ```typescript
  let healthData = $state(data.health); // initial SSR data
  $effect(() => {
    const interval = setInterval(async () => {
      const res = await apiClient.get('/admin/health/services');
      healthData = await res.json();
    }, 30_000);
    return () => clearInterval(interval);
  });
  ```
  SSR only for initial page load (auth security + first paint). Subsequent refreshes go client-direct.

#### Acceptance Criteria

- [ ] Service status cards show correct state with semantic colors
- [ ] Worker logs stream in real-time via SSE
- [ ] Log feed auto-scrolls but respects manual scroll position
- [ ] Auto-refresh updates health data every 30s
- [ ] `svelte-check` passes

---

### Phase 4: Tenant Management

**Goal:** CRUD for tenants with branding editor.

**Prerequisite:** Phase 2 (scaffold), Phase 1.3 (tenant routes).

#### 4.1: Tenant List

##### Files

```
frontends/admin/src/routes/(admin)/tenants/+page.server.ts
frontends/admin/src/routes/(admin)/tenants/+page.svelte
frontends/admin/src/lib/components/TenantCard.svelte
```

##### Tasks

- [ ] `+page.server.ts` — load tenant list from `GET /api/v1/admin/tenants/`
- [ ] `TenantCard.svelte` — compact card: org name, slug, vertical badge, config count, asset count. Clickable → navigates to `/tenants/[orgId]`
- [ ] Tenant list page — grid of `TenantCard` components
- [ ] "Create Tenant" button → `Dialog` with form: org name, slug, vertical selection (`Select`). Calls `POST /api/v1/admin/tenants/`. On success: toast + navigate to new tenant detail
- [ ] `EmptyState` when no tenants exist

##### Acceptance Criteria

- [ ] Tenant list loads and displays cards
- [ ] Create tenant works end-to-end (Clerk org + DB seed)
- [ ] Navigation to tenant detail works

#### 4.2: Tenant Detail

##### Files

```
frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.server.ts
frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/branding/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/branding/+page.server.ts
frontends/admin/src/routes/(admin)/tenants/[orgId]/config/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/config/+page.server.ts
frontends/admin/src/routes/(admin)/tenants/[orgId]/prompts/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/prompts/+page.server.ts
frontends/admin/src/lib/components/BrandingEditor.svelte
```

##### Tasks

- [ ] `+layout.server.ts` — load tenant detail from `GET /api/v1/admin/tenants/{org_id}`
- [ ] `+layout.svelte` — ContextSidebar with navigation: Overview, Branding, Config, Prompts
- [ ] **Overview tab** (`+page.svelte`):
  - Org name, slug, vertical, creation date
  - Config override count, asset status
  - "Re-seed Configs" button (calls `POST /tenants/{org_id}/seed` with Dialog confirmation)
- [ ] **Branding tab** (`branding/+page.svelte`):
  - `BrandingEditor.svelte`:
    - Color pickers for brand tokens (primary, secondary, accent, highlight, surface, border, text). Each color picker has BOTH visual picker AND text input for hex (accessibility — from SpecFlow). Validate hex: `^#[0-9a-fA-F]{6}$` — no CSS injection. No alpha (`#RRGGBBAA`) — only 6-char hex.
    - Font selector — curated list only (Inter, JetBrains Mono, etc.), not free-text. Uses `Select` component.
    - Logo upload: drag-and-drop or file input. Accept PNG/JPEG/ICO only. **Client-side validation** (from SpecFlow): check file size < 512KB BEFORE upload, show error immediately if exceeded. Validate extension client-side + magic bytes server-side. Show preview immediately via `URL.createObjectURL()`. Recommended dimensions note: "200x60px for logo, 32x32px for favicon"
    - Live preview panel: shows how TopNav + SectionCard + MetricCard look with the tenant's branding. **Preview updates at 50ms debounce** (from Performance review — not 500ms, CSS property changes are instant with no network call). Inject via `element.style.setProperty(cssVar, value)` on an isolated `<div>`. Show both light and dark theme previews with a toggle (from SpecFlow — Wealth uses dark, Credit uses light)
    - Logo deletion shows Netz default logo (not the 1x1 transparent PNG placeholder — from SpecFlow)
    - Save calls `PUT /api/v1/admin/configs/{vertical}/branding` (optimistic lock). On 409: persistent toast with "Refresh" action button. **Server-side branding validation** via `validate_branding_tokens()` in `validators.py` (Phase 1.0) — hex regex, curated fonts, CSS injection chars rejected
- [ ] **Config tab** → delegates to Phase 5 ConfigEditor with org_id context
- [ ] **Prompts tab** → delegates to Phase 6 PromptEditor with org_id context

##### Acceptance Criteria

- [ ] Tenant detail loads with ContextSidebar navigation
- [ ] Branding editor shows live preview of changes
- [ ] Color picker validates hex format (no CSS injection)
- [ ] Logo upload enforces PNG/JPEG/ICO + 512KB limit client-side
- [ ] Save with 409 handling works correctly
- [ ] `svelte-check` passes

---

### Phase 5: Config Editor

**Goal:** JSON config editor with guardrail validation and diff viewer.

**Prerequisite:** Phase 2 (scaffold), Phase 1.1 (ConfigWriter), Phase 1.3 (config routes).

#### Files

```
frontends/admin/src/routes/(admin)/config/[vertical]/+page.server.ts
frontends/admin/src/routes/(admin)/config/[vertical]/+page.svelte
frontends/admin/src/lib/components/ConfigEditor.svelte
frontends/admin/src/lib/components/ConfigDiffViewer.svelte
```

#### Tasks

- [ ] `+page.server.ts` — load config list for vertical from `GET /api/v1/admin/configs/`
- [ ] Config list page — grouped by config_type, showing override status (`StatusBadge`), version, last updated
- [ ] `ConfigEditor.svelte`:
  - **CodeMirror 6 + `codemirror-json-schema`** (from Best Practices research — ~150KB bundle vs Monaco's 5MB, with schema-driven validation and autocompletion. Better than textarea while avoiding Monaco's SSR issues):
    - `@codemirror/lang-json` for syntax highlighting
    - `codemirror-json-schema` for JSON Schema validation + autocompletion (loaded from `guardrails` column via config GET response)
    - `@codemirror/lint` + `lintGutter()` for inline error display
    - `EditorState.readOnly.of(true)` for read-only mode (viewing defaults)
    - Dynamic `import()` for CodeMirror (zero cost on non-editor pages)
  - JSON syntax validation via CodeMirror's built-in linter — green/red indicator
  - **Guardrail schema included in config GET response** (from SpecFlow — avoids separate fetch): `GET /admin/configs/{vertical}/{type}` returns `{config, guardrails_schema, version}`
  - Guardrail validation before save — dry-run via `POST /admin/configs/validate` endpoint, handle 422 inline (show validation errors below editor)
  - Shows current merged values (default + override)
  - Override indicator: "Editing override" vs "Viewing default (read-only)"
  - Save button with optimistic lock (`If-Match: {version}` header). On 409: toast "Config was modified by another admin" with action button "Refresh" (persistent toast, not auto-dismiss). NOT a blocking modal.
  - "Reset to default" button: calls `DELETE` to remove override (with Dialog confirmation showing "This will affect all users of this tenant")
  - **Keyboard accessibility** (from SpecFlow): Escape exits CodeMirror editor to allow Tab-based focus navigation
- [ ] `ConfigDiffViewer.svelte`:
  - Side-by-side view: default (left, dimmed) vs override (right)
  - Highlighted differences (changed keys in `--netz-warning` background)
  - Loaded from `GET /api/v1/admin/configs/{vertical}/{type}/diff`
- [ ] Support both contexts:
  - Global defaults at `/config/[vertical]` (no org_id)
  - Per-tenant overrides at `/tenants/[orgId]/config` (with org_id param)

#### Acceptance Criteria

- [ ] JSON editor validates syntax on keystroke
- [ ] Guardrail validation prevents invalid saves (422 shown inline)
- [ ] Diff viewer shows default vs override with highlights
- [ ] Optimistic lock works (409 → toast + reload)
- [ ] Reset to default removes override
- [ ] Works in both global and per-tenant contexts
- [ ] `svelte-check` passes

---

### Phase 6: Prompt Editor

**Goal:** Jinja2 template editor with live preview and version history.

**Prerequisite:** Phase 2 (scaffold), Phase 1.2 (PromptService), Phase 1.3 (prompt routes).

#### Files

```
frontends/admin/src/routes/(admin)/prompts/[vertical]/+page.server.ts
frontends/admin/src/routes/(admin)/prompts/[vertical]/+page.svelte
frontends/admin/src/lib/components/PromptEditor.svelte
```

#### Tasks

- [ ] `+page.server.ts` — load prompt list from `GET /api/v1/admin/prompts/{vertical}`
- [ ] Prompt list page — `DataTable` with template name, description, source level (`StatusBadge`: org/global/filesystem), version, has_override indicator
- [ ] `PromptEditor.svelte` — split pane:
  - **Left:** `<textarea>` with monospace font for Jinja2 template editing (MVP — no Monaco/CodeMirror)
  - **Right:** Live preview panel (calls `POST /api/v1/admin/prompts/{vertical}/{name}/preview` on debounced keystrokes, 500ms delay). Shows rendered HTML or error message
  - Syntax validation indicator (green/red dot) via `POST /validate` on debounced keystrokes
  - Source level indicator: "Editing org override" / "Editing global override" / "Viewing filesystem template (read-only)"
  - Save button: auto-bumps version, writes history
  - "Revert" button: `DELETE` override → falls back to next cascade level (with Dialog confirmation)
- [ ] Version history dropdown:
  - Loaded from `GET /api/v1/admin/prompts/{vertical}/{name}/versions`
  - View previous versions (read-only in textarea)
  - "Restore this version" button → calls revert endpoint
- [ ] Support both contexts:
  - Global prompts at `/prompts/[vertical]` (no org_id)
  - Per-tenant overrides at `/tenants/[orgId]/prompts` (with org_id param)
- [ ] **Security:** Never show raw prompt content in any client-visible API outside admin routes. Admin routes enforce ADMIN role.

#### Acceptance Criteria

- [ ] Prompt list shows all templates with source level
- [ ] Live preview updates on keystroke (debounced)
- [ ] Syntax errors shown inline
- [ ] Version history accessible, previous versions viewable
- [ ] Revert falls back to next cascade level
- [ ] Read-only mode for filesystem-level templates
- [ ] Works in both global and per-tenant contexts
- [ ] `svelte-check` passes

---

### Phase 7: Integration Tests

**Goal:** End-to-end validation of admin frontend flows.

**Prerequisite:** Phases 2-6 complete.

#### Files

```
frontends/admin/tests/e2e/auth.spec.ts
frontends/admin/tests/e2e/tenants.spec.ts
frontends/admin/tests/e2e/config.spec.ts
frontends/admin/tests/e2e/prompts.spec.ts
frontends/admin/tests/e2e/health.spec.ts
```

#### Tasks

- [ ] Auth: non-admin rejected → redirect; admin sees dashboard
- [ ] Tenants: create tenant → appears in list → detail loads → branding upload works
- [ ] Config: edit config → save → optimistic lock → diff viewer shows changes
- [ ] Prompts: edit prompt → preview renders → save → version history shows new entry
- [ ] Health: service cards render, worker logs stream

#### Acceptance Criteria

- [ ] All E2E tests pass against running backend + admin frontend
- [ ] `make check` passes (backend lint + typecheck + test)
- [ ] `pnpm --filter netz-admin check` passes (svelte-check)

---

## System-Wide Impact

### Interaction Graph

```
Admin saves branding → PUT /admin/configs/{v}/branding → DB write → pg_notify
  → ConfigService cache invalidation (all API processes)
  → Next GET /branding returns new values
  → Tenant's frontend SSR re-renders with new CSS vars
  → PDF generation picks up new styles via token_generator.py
```

```
Admin saves prompt → PUT /admin/prompts/{v}/{name} → prompt_overrides DB write + history
  → Next IC memo/DD report generation resolves new prompt
  → Active jobs use snapshot (unaffected)
  → New jobs get updated prompt
```

```
Admin creates tenant → POST /admin/tenants/ → Clerk org + DB seed (atomic)
  → Default configs seeded for all verticals
  → Tenant immediately usable via Wealth/Credit frontend
```

### Error & Failure Propagation

- Admin frontend SSR fails → `+error.svelte` renders `BackendUnavailable`
- API returns 401 → single-flight redirect to `/auth/sign-in`
- API returns 403 → "Not authorized" inline error (non-admin somehow reached admin page)
- API returns 409 → `Toast` "Updated by another user" + `invalidateAll()` (config/prompt writes)
- API returns 422 → inline validation errors below form fields (guardrail/schema violations)
- SSE connection fails after 5 retries → `ConnectionLost` banner stays visible on health page
- Tenant creation partial failure (Clerk success, DB fail) → error toast + "Retry Seed" button

### State Lifecycle Risks

- **Config write during active request:** Acceptable — eventual consistency with TTL ≤ 60s. `pg_notify` reduces to milliseconds.
- **Prompt change during active generation:** Mitigated by snapshot-at-job-start pattern.
- **Logo change during cached period:** Mitigated by `?v={hash}` cache-buster in branding config.
- **Tenant creation partial failure:** DB transaction for seed. Clerk org creation is the only external call — if DB seed fails, admin retries via `/seed` endpoint.
- **Two admins editing same config:** Optimistic lock via `version` column. Second admin gets 409 + toast + auto-refresh.

### API Surface Parity

- Admin frontend is the SOLE location for cross-tenant configuration
- Wealth and Credit frontends consume branding via `GET /api/v1/branding` (read-only)
- Admin writes propagate to other frontends via `pg_notify` → `ConfigService` cache invalidation
- No direct cross-frontend imports (enforced by monorepo structure)

---

## Acceptance Criteria

### Functional Requirements

- [ ] Admins can: view system health, manage tenants, edit configs/branding/prompts, monitor workers
- [ ] Non-admin users cannot access any admin page (redirect to sign-in)
- [ ] Config edits validate against guardrails before save
- [ ] Branding changes propagate to tenant frontends (via cache invalidation)
- [ ] Prompt edits versioned with history and rollback
- [ ] Tenant creation works end-to-end (Clerk + DB seed)

### Non-Functional Requirements

- [ ] Light theme by default, dark theme supported (D2)
- [ ] All CSS tokens declared in `tokens.css` (D4)
- [ ] No hardcoded hex values in components — semantic tokens only (D5)
- [ ] TypeScript strict mode with zero errors
- [ ] Responsive at standard breakpoints (≥1280, 1024, 768, <600px)
- [ ] SSE reconnection with exponential backoff for worker logs

### Quality Gates

- [ ] `make check` passes (backend lint + typecheck + test)
- [ ] `pnpm --filter netz-admin check` passes (svelte-check)
- [ ] No TypeScript `any` types in production code
- [ ] All admin routes require ADMIN role

## Dependencies & Prerequisites

```
Phase 1.0 → Admin Security Infrastructure (RLS bypass, SUPER_ADMIN, validators) — REVIEW FIRST
Phase 1.1 → ConfigWriter + PgNotify (can start after 1.0 review passes)
Phase 1.2 → PromptService (can start after 1.0 review passes, parallel with 1.1)
Phase 1.3 → Admin Routes + Schemas (requires 1.1 + 1.2)
Phase 1.4 → Admin Backend Tests (requires 1.3)
Phase 2   → SvelteKit Scaffold (can start in parallel with Phase 1.0)
Phase 3   → Health Dashboard (requires Phase 2 scaffold + Phase 1.3 health routes)
Phase 4   → Tenant Management (requires Phase 2 scaffold + Phase 1.3 tenant routes)
Phase 5   → Config Editor (requires Phase 2 + Phase 1.1 ConfigWriter + Phase 1.3 config routes)
Phase 6   → Prompt Editor (requires Phase 2 + Phase 1.2 PromptService + Phase 1.3 prompt routes)
Phase 7   → Integration Tests (requires Phases 2-6 complete)
```

**Parallel execution:**
- **Phase 1.0** (security) and **Phase 2** (scaffold) start in parallel.
- **Phase 1.0 is reviewed** before 1.1/1.2 start — isolates security P1 risk from business logic.
- After 1.0 review passes, **1.1 and 1.2 run in parallel**.
- After Phase 1 and Phase 2 complete, **Phases 3/4/5/6 run in parallel** (independent routes).
- Phase 7 runs last.

**External dependencies:**
- `@netz/ui` (workspace:*) — already complete with 49+ exports
- Clerk JWT auth — already working in Wealth/Credit frontends
- PostgreSQL + Redis — already running via docker-compose

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RLS blocks admin cross-tenant queries | **Certain** | Critical | Migration 0015: add `admin_mode` to RLS policies. `get_db_admin_read()` dependency |
| Org-admin accesses admin panel | High | Critical | `Role.SUPER_ADMIN` distinct from `Role.ADMIN`. Clerk user-level claim or dedicated Netz org |
| `BrandingResponse` CSS injection | High | Critical | Change to `extra="forbid"`. Server-side `validate_branding_tokens()`. JSON Schema guardrails |
| SVG XSS via logo upload | High | Critical | Reject SVG entirely. Accept PNG/JPEG/ICO only. Validate magic bytes server-side. Strip EXIF |
| SSTI via prompt editor | Medium | Critical | `HardenedPromptEnvironment` with 13 blocked attrs + callable blocking + render timeout 5s. SSTI bypass test suite |
| CSS injection via branding color picker | Medium | High | Strict hex regex server-side (`validators.py`). Font from curated list only. Reject `{};<>` chars |
| SSE log stream leaks secrets | Medium | High | Structured log schema only. Never raw tracebacks. JWT re-validation every 60s |
| Two admins editing same config | Medium | Low | Optimistic lock (version column). 409 → persistent toast with "Refresh" action |
| pg_notify listener dropped | Medium | High | Dedicated asyncpg connection. TCP keepalives. Full cache flush on reconnect. Graceful shutdown |
| Guardrail schema drift | Medium | High | Validate at read time. Log WARNING, return default. `/admin/configs/invalid` endpoint |
| Large prompt templates | Low | Medium | 50KB max_length. Render timeout 5s. Bounded `sample_data` (64KB, depth 5) |
| Tenant creation duplicate Clerk org | Low | Medium | Check existing slug before Clerk API call. Seed endpoint idempotent (`ON CONFLICT DO NOTHING`) |
| Admin API abuse (no rate limit) | Low | High | Rate limiting: 60 req/min reads, 10/min writes, 5/min tenant creation, 10/min prompt preview |

## Admin-Specific Components Summary

| Component | Location | @netz/ui deps |
|---|---|---|
| `ServiceHealthCard.svelte` | `src/lib/components/` | MetricCard, StatusBadge |
| `WorkerLogFeed.svelte` | `src/lib/components/` | SectionCard |
| `TenantCard.svelte` | `src/lib/components/` | Card, Badge |
| `BrandingEditor.svelte` | `src/lib/components/` | SectionCard, Input, Select, Button, Dialog, Toast |
| `ConfigEditor.svelte` | `src/lib/components/` | SectionCard, Button, Dialog, Toast, StatusBadge |
| `ConfigDiffViewer.svelte` | `src/lib/components/` | SectionCard |
| `PromptEditor.svelte` | `src/lib/components/` | SectionCard, Button, Dialog, Toast, StatusBadge, Select |

All 7 components are admin-specific and live in `frontends/admin/src/lib/components/` (NOT in `@netz/ui`).

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-17-admin-frontend-brainstorm.md](../brainstorms/2026-03-17-admin-frontend-brainstorm.md) — Key decisions: light theme default, TopNav global + ContextSidebar in tenant detail, textarea for MVP (no Monaco), cross-tenant auth, 6 admin-specific components, use @netz/ui for everything else
- **Original platform plan (Phases E+F):** [docs/plans/2026-03-16-feat-frontend-admin-platform-plan.md](2026-03-16-feat-frontend-admin-platform-plan.md) — Carried forward: all Phase E/F tasks, security hardening, pg_notify patterns, SpecFlow gap resolutions
- **Design decisions D1-D9:** [docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md](../solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md) — Applied: D1 (nav arch), D2 (dark+light), D4 (no undeclared tokens), D5 (admin-configurable tokens)

### Internal References

- Wealth hooks pattern: `frontends/wealth/src/hooks.server.ts`
- Wealth scaffold: `frontends/wealth/package.json`, `frontends/wealth/svelte.config.js`
- Branding route: `backend/app/domains/admin/routes/branding.py`
- Asset route: `backend/app/domains/admin/routes/assets.py`
- Admin models: `backend/app/domains/admin/models.py`
- ConfigService: `backend/app/core/config/config_service.py`
- Prompt registry: `backend/ai_engine/prompts/registry.py`
- Token system: `packages/ui/src/lib/styles/tokens.css`

### Institutional Learnings Applied

- Lock contracts (tokens, routes, types) BEFORE component work (from `docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md`)
- RLS subselect pattern for all new tables (from `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md`)
- Organization ID in search filters (from `docs/solutions/security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md`)
- Pydantic `extra="forbid"` on ALL new admin response schemas — applied to all 11 new schemas (from `docs/solutions/architecture-patterns/pydantic-migration-review-findings-PolicyThresholds-20260316.md`)
- FastAPI route shadowing prevention — literal routes before parameterized routes (from `docs/solutions/logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md`)
- PromptRegistry integration — PromptService composes with PromptRegistry, does not replace it (from `docs/solutions/architecture-patterns/prompt-registry-distributed-search-paths-PromptRelocation-20260315.md`)
- SSE wiring validation — explicitly verify end-to-end SSE pipeline (from `docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md`)
- Token validation — write to canonical token names only, not aliases like `--netz-primary` (from `docs/solutions/architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md`)

### Deepening Research (9 agents, 2026-03-17)

- **Security Sentinel:** 4 critical (SSTI, admin role, BrandingResponse, RLS bypass), 5 high (asset slug, SSE auth, prompt preview, tenant idempotency, rate limiting), 6 medium
- **Architecture Strategist:** 7 issues — admin session dependencies, PgNotifyListener lifecycle, PromptService/PromptRegistry composition, route prefix consistency
- **Performance Oracle:** 13 findings — `invalidateAll()` replacement (P1), SSE backpressure (P1), pg_notify cache flush (P2), TTLCache maxsize, deep_merge depth limit
- **Pattern Recognition:** 12 findings — adminGuardHook path check (HIGH), missing app.d.ts, Vite port, defaultLightBranding, API client function names, schema conventions
- **Data Integrity Guardian:** 9 findings — FORCE ROW LEVEL SECURITY blocks admin (CRITICAL), ConfigWriter INSERT vs UPDATE paths, guardrail schema drift, seed idempotency
- **Best Practices Researcher:** CodeMirror 6 + codemirror-json-schema, PgNotifier class with DB trigger, HardenedPromptEnvironment, multi-channel SSE pattern
- **Framework Docs Researcher:** SvelteKit hooks.server.ts patterns, asyncpg LISTEN/NOTIFY, Jinja2 ImmutableSandboxedEnvironment
- **Learnings Researcher:** 5 highly relevant solutions applied (route shadowing, PromptRegistry, wealth design refresh patterns, RLS subselect, tenant isolation)
- **SpecFlow Analyzer:** 36 flow gaps — admin auth model, tenant detail tabs, prompt sample data, config editor tenant scope, version history, audit logging, Users tab deferred
