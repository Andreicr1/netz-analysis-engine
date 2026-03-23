---
title: "Multi-Agent Review Catches 5 Critical Production Bugs in Admin Frontend"
date: 2026-03-17
module: backend/app/core + backend/app/domains/admin + frontends/admin
severity: P1-critical
tags:
  - admin-panel
  - rls-bypass
  - ssti-hardening
  - pg-notify
  - multi-agent-review
  - postgresql-triggers
  - cross-tenant
  - security
findings_total: 13
findings_p1: 5
findings_p2: 8
branch: feat/admin-frontend
review_agents:
  - security-sentinel
  - architecture-strategist
  - performance-oracle
  - data-integrity-guardian
  - learnings-researcher
---

# Multi-Agent Review Catches 5 Critical Production Bugs in Admin Frontend

## Context

Built a cross-tenant admin panel from scratch (7 phases, 59 files, ~4,200 lines). Multi-agent code review with 5 specialized agents found 13 issues — **5 were P1 critical bugs that would have caused production failures**. All fixed before merge.

The admin panel adds RLS bypass for cross-tenant access, SSTI-hardened prompt editing, pg_notify cache invalidation, 26 API endpoints, and a SvelteKit frontend. None of the 5 P1 bugs would have been caught by unit tests alone.

## The 5 Critical Bugs

### 1. Missing RLS Bypass on `vertical_config_overrides`

**Symptom:** All admin config operations (read, write, delete, diff, list tenants) would silently return zero rows.

**Root cause:** Migration 0015 added `admin_mode` bypass to `tenant_assets`, `prompt_overrides`, and `prompt_override_versions` but missed `vertical_config_overrides` — the primary table for config management. Since that table has `FORCE ROW LEVEL SECURITY`, the admin session (which sets `admin_mode=true` but no `organization_id`) sees nothing.

**Pattern:** When adding a cross-cutting RLS change, audit ALL tables with `FORCE ROW LEVEL SECURITY`, not just tables created in the current migration. Use:
```sql
SELECT schemaname, tablename, policyname
FROM pg_policies WHERE qual LIKE '%current_setting%'
ORDER BY tablename;
```

**Fix:**
```sql
DROP POLICY IF EXISTS org_isolation ON vertical_config_overrides;
CREATE POLICY org_isolation ON vertical_config_overrides
    USING (
        organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
        OR (SELECT current_setting('app.admin_mode', true)) = 'true'
    )
    WITH CHECK (
        organization_id = (SELECT current_setting('app.current_organization_id', true))::uuid
        OR (SELECT current_setting('app.admin_mode', true)) = 'true'
    );
```

**Found by:** Data Integrity Guardian + Architecture Strategist (both flagged independently)

---

### 2. Admin Routes Not Mounted in `main.py`

**Symptom:** All 26 admin API endpoints return 404.

**Root cause:** 4 route modules (`configs.py`, `health.py`, `prompts.py`, `tenants.py`) were created with valid handlers but never `include_router()` in `main.py`. The imports and mount calls were missing entirely.

**Pattern:** Every `APIRouter` module must have a corresponding `include_router()` call. After creating route files, verify mounting:
```bash
python -c "from app.main import app; [print(r.path) for r in app.routes]"
```

**Fix:**
```python
from app.domains.admin.routes.configs import router as admin_configs_router
from app.domains.admin.routes.health import router as admin_health_router
from app.domains.admin.routes.prompts import router as admin_prompts_router
from app.domains.admin.routes.tenants import router as admin_tenants_router

api_v1.include_router(admin_configs_router)
api_v1.include_router(admin_tenants_router)
api_v1.include_router(admin_prompts_router)
api_v1.include_router(admin_health_router)
```

**Found by:** Security Sentinel + Architecture Strategist

---

### 3. pg_notify Trigger Crashes on DELETE

**Symptom:** Deleting a config override crashes the PostgreSQL trigger, preventing cache invalidation.

**Root cause:** The trigger used `COALESCE(NEW.vertical, OLD.vertical)`. On DELETE, PostgreSQL sets the entire `NEW` record to NULL (not individual fields), so `NEW.vertical` raises `ERROR: record "new" is not assigned yet`. Additionally, `RETURN NEW` on a DELETE trigger returns NULL, which suppresses the delete.

**Pattern:** Always use `TG_OP` dispatch in triggers. Never use `COALESCE(NEW.field, OLD.field)` as a shortcut.

**Fix:**
```sql
CREATE OR REPLACE FUNCTION notify_config_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM pg_notify('config_changed', json_build_object(
            'vertical', OLD.vertical,
            'config_type', OLD.config_type,
            'organization_id', OLD.organization_id::text
        )::text);
        RETURN OLD;  -- DELETE must RETURN OLD, not NEW
    ELSE
        PERFORM pg_notify('config_changed', json_build_object(
            'vertical', NEW.vertical,
            'config_type', NEW.config_type,
            'organization_id', NEW.organization_id::text
        )::text);
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;
```

**Found by:** Data Integrity Guardian

---

### 4. RLS `admin_mode` Uses Bare `current_setting()` — 1000x Slowdown

**Symptom:** Admin cross-tenant queries run 1000x slower than expected on large tables.

**Root cause:** The `organization_id` check correctly used `(SELECT current_setting(...))` subselect, but the newly added `admin_mode` check did not:
```sql
-- WRONG: bare call, evaluated per-row (VOLATILE)
OR current_setting('app.admin_mode', true) = 'true'

-- CORRECT: subselect, evaluated once
OR (SELECT current_setting('app.admin_mode', true)) = 'true'
```

PostgreSQL treats bare `current_setting()` as VOLATILE, causing per-row evaluation instead of once-per-query. The inconsistency within the same policy (one wrapped, one not) made it easy to miss.

**Pattern:** ALL `current_setting()` calls in RLS policies MUST be wrapped in `(SELECT ...)`. This is already a CLAUDE.md critical rule but was violated in the new code.

**Found by:** Security Sentinel (cross-referenced with existing docs/solutions/performance-issues/rls-subselect-1000x-slowdown)

---

### 5. Jinja2 `safe` Filter Enables XSS via `{@html}`

**Symptom:** Stored XSS — admin-injected `<script>` tags execute in other users' browsers via prompt preview.

**Root cause:** `HardenedPromptEnvironment` defined `_ALLOWED_FILTERS` including `safe`. The `safe` filter marks content as "do not escape", completely defeating `autoescape=True`. When rendered output is displayed via Svelte's `{@html preview}`, this creates a stored XSS vector.

**Pattern:** Never include `safe` in a sandboxed Jinja2 environment's filter allowlist. If `autoescape=True` is set for security, `safe` is a bypass.

**Fix:** One-line removal:
```python
# BEFORE (vulnerable)
_ALLOWED_FILTERS = frozenset({"default", "upper", ..., "safe", "string", "list"})

# AFTER (safe)
_ALLOWED_FILTERS = frozenset({"default", "upper", ..., "string", "list"})
```

**Found by:** Security Sentinel + Performance Oracle (both flagged the `{@html}` + `safe` combination)

---

## Prevention Strategies

### CI Gate Additions

| # | Check | What it catches |
|---|-------|----------------|
| 1 | `test_rls_coverage.py` — verify all RLS tables have admin bypass | Missing RLS policy on new tables |
| 2 | Route mounting grep — every `APIRouter()` has `include_router()` | Unreachable endpoints |
| 3 | Trigger audit — no `NEW.` references in DELETE branches | Trigger crashes on DELETE |
| 4 | `test_rls_subselect.py` — grep migration files for bare `current_setting` | 1000x RLS slowdown |
| 5 | Template scan — no `\|safe` in .j2 files or sandbox allowlist | XSS bypass in sandbox |

### CLAUDE.md Rule Additions

```
- **RLS coverage invariant:** When adding RLS policies or admin bypass, verify ALL tables with
  FORCE ROW LEVEL SECURITY have matching policies. Use pg_policies catalog to audit.
- **Trigger record references:** NEW is NULL on DELETE, OLD is NULL on INSERT. Always guard
  with IF TG_OP dispatch. DELETE triggers must RETURN OLD, not NEW.
- **No |safe in Jinja2 sandbox:** Remove safe from filter allowlist after construction.
  It bypasses autoescape and creates XSS vectors with {@html} rendering.
```

## Related Documentation

- [RLS Subselect 1000x Slowdown](../performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md) — the foundational rule violated by Bug #4
- [FastAPI Route Shadowing](../logic-errors/fastapi-route-shadowing-and-sql-limit-bias-multi-instrument-20260317.md) — route ordering discipline
- [Wealth Frontend Multi-Agent Review Patterns](../architecture-patterns/wealth-os-design-refresh-multi-agent-review-patterns.md) — prior multi-agent review session
- [Azure Search Tenant Isolation](../security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md) — cross-tenant isolation patterns
- [LLM Output Sanitization](../security-issues/llm-output-sanitization-nh3-persist-boundary-PipelineStorage-20260315.md) — XSS prevention at persist boundary

## Key Insight

None of these 5 bugs would have been caught by unit tests. They are all integration-level or cross-cutting concerns:
- Bug 1 requires tenant-aware DB integration tests with RLS enabled
- Bug 2 requires app-level route introspection (not module-level)
- Bug 3 requires actually executing a DELETE on a table with the trigger
- Bug 4 requires EXPLAIN ANALYZE on a large table (performance, not correctness)
- Bug 5 requires cross-layer analysis (backend filter allowlist + frontend rendering)

**Multi-agent review with specialized agents (Security, Architecture, Performance, Data Integrity) is the safety net for cross-cutting bugs that unit tests miss.**
