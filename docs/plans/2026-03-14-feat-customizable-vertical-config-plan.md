---
title: "feat: Customizable Vertical Configuration System (ProductConfig)"
type: feat
status: active
date: 2026-03-14
deepened: 2026-03-14
origin: docs/brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md
parent_plan: docs/plans/2026-03-14-feat-netz-analysis-engine-platform-plan.md
---

# Customizable Vertical Configuration System (ProductConfig)

## Enhancement Summary

**Deepened on:** 2026-03-14
**Review agents used:** 7 (SpecFlow analyzer, architecture strategist, security sentinel, performance oracle, data integrity guardian, code simplicity reviewer, best practices researcher)

### Key Improvements from Research

1. **Sprint 3 YAGNI reduction (~40%):** Drop Redis cache, audit triggers, guardrails validation, and write methods from Sprint 3. ConfigService becomes read-only with in-process TTL cache. Build write infrastructure when first consumer arrives (Sprint 5-6).
2. **Single DB session:** Use `get_db_with_rls` for ConfigService (defaults table has no RLS, so zero impact). Eliminates dual-session ambiguity and connection pool exhaustion risk.
3. **pg_notify for cache invalidation (Sprint 5-6):** Use PostgreSQL LISTEN/NOTIFY instead of Redis pub/sub — fires from DB trigger, transactional (only on commit), zero write-path application code.
4. **Deep merge safety:** Block None-deletion in client self-service API (only Netz admin can delete keys). Validate merged result against per-type schema before serving.
5. **Audit trigger must include DELETE:** CASCADE deletes leave no trace without it. Add `operation TEXT` column to distinguish INSERT/UPDATE/DELETE.
6. **Seed idempotency:** Use `INSERT ... ON CONFLICT DO NOTHING`. Set `created_by = 'migration:0004'` for provenance.
7. **CHECK constraints on vertical/config_type:** Prevent typos like `'Liquid_Funds'` vs `'liquid_funds'`. Deliberate friction.
8. **Optimistic concurrency (Sprint 5-6):** Add `version` column + `WHERE version = :expected` on update. Prevents silent overwrite when two admins edit simultaneously.
9. **ON DELETE RESTRICT (not CASCADE):** Organization deletion should not silently destroy calibration. Force explicit cleanup.

### Critical Decisions from Reviews

| Decision | Source | Impact |
|---|---|---|
| Sprint 3 = read-only ConfigService + in-process cache | Simplicity + Performance | ~40% scope reduction, no Redis dependency on read path |
| Use `get_db_with_rls` for all ConfigService queries | Architecture + Performance | Single session, no connection pool risk |
| Defer audit triggers to Sprint 5-6 | Simplicity | Migration file is audit trail for seed data |
| Defer guardrails validation to Sprint 7 | Simplicity | No client self-service until then |
| Sync quant functions receive config as parameter | SpecFlow + Architecture | Config resolved once at async entry point, passed down |
| `list_configs()` filters out prompts/model_routing for non-admin | SpecFlow + Security | Prevents IP exposure even in metadata |
| Remove `chapters` from CLIENT_VISIBLE_TYPES | Security + IP | Chapter structure (which chapters, ordering) is analytical methodology IP — clients get the output, not the structure |
| Credit calibration seed = engine quality upgrade | Product | Institutional defaults (Moody's, S&P, Basel III) replace hardcoded values — direct analytical improvement |
| NETZ_ADMIN provisioned via Clerk Dashboard/Backend API only | Security | `publicMetadata` is server-side only by design — cannot be self-assigned via client SDK |
| **OPEN (Sprint 5-6):** `portfolio_profiles` client visibility | IP review | Profile structure (CVaR limits, allocations) may be methodology IP like chapters — deliberate before client self-service UI |
| Add CHECK constraints on TEXT columns | Data Integrity | Prevents config orphaning via typos |

### Security Findings (from security sentinel)

| Finding | Severity | Remediation |
|---|---|---|
| No `NETZ_ADMIN` role exists — `org:admin` would grant admin API to ALL tenants | CRITICAL | Define `NETZ_ADMIN` via Clerk `publicMetadata` (server-side only, cannot be self-assigned). Prerequisite for Sprint 5-6 admin API. |
| Prompts in no-RLS table accessible to any DB session | HIGH | `CLIENT_VISIBLE_TYPES = frozenset({"calibration", "scoring", "blocks"})` checked in `get()` and `list_configs()` |
| Jinja2 SSTI risk in admin-editable prompt templates | HIGH | Use `jinja2.SandboxedEnvironment`, disable `__` attribute access, validate templates at write time |
| Guardrail validation must be inside `set_override()`, not separate | HIGH | Enforce architecturally — `set_override()` calls `validate_guardrails()` internally before DB write |
| Dev bypass (`X-DEV-ACTOR`) could grant admin access | HIGH | Ensure `is_development` never true in production; verify `validate_production_secrets()` called at startup |
| Audit table allows UPDATE/DELETE by app user | MEDIUM | `REVOKE UPDATE, DELETE ON vertical_config_audit FROM app_user` |
| Validate `vertical`/`config_type` path params with Pydantic `Literal` | MEDIUM | Prevents cache key pollution and unexpected DB queries |

### Anti-Patterns Discovered

| Anti-Pattern | Source | Correct Pattern |
|---|---|---|
| Two DB sessions per cache miss | Performance | Single `get_db_with_rls` session for both queries |
| Redis pub/sub per worker for config invalidation | Performance | Single shared listener per process (Sprint 5-6) |
| `None` = delete in client API | Data Integrity + Security | Block None-deletion for clients; only Netz admin can delete via `_DELETE` sentinel |
| `ON DELETE CASCADE` on config overrides | Data Integrity | `ON DELETE RESTRICT` — force explicit cleanup |
| GIN index on JSONB config column | Performance | Not needed — queries filter by composite key, never by JSONB content |
| Module-level `PROFILE_CVAR_CONFIG` constant | Architecture | Remove completely; all callers pass config as parameter |
| Using `org:admin` for Netz admin API | Security | Define `NETZ_ADMIN` via Clerk `publicMetadata` — cannot be self-assigned by tenants |
| Default Jinja2 Environment for prompt rendering | Security | Use `SandboxedEnvironment` — prevents SSTI attacks from compromised admin accounts |

## Overview

Replace the static YAML-based configuration system (`calibration/` + `profiles/`) with a database-backed, multi-tenant, multi-vertical configuration system. Each vertical (private credit, liquid funds, venture capital, etc.) gets its own calibration parameters, and each tenant can customize calibration within guardrails defined by Netz.

**This is the product differentiator.** No competitor offers calibration customizability at this level. The configuration IS the product.

**Origin:** See [brainstorm](../brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md) for full design rationale, resolved questions, and credit calibration best practices.

## Problem Statement

Two separate config systems exist, both global/shared:
- `calibration/config/` (4 YAMLs) — wealth-only quant parameters, loaded via `@lru_cache` + `yaml.safe_load()` with hardcoded fallback. No per-tenant override. No per-vertical separation.
- `profiles/private_credit/profile.yaml` — IC memo chapter definitions, not yet loaded by engine (chapter engine still reads from Python constants in `memo_chapter_prompts.py`).

This is architecturally wrong for a multi-vertical, multi-tenant B2B SaaS:
1. Credit calibration (LTV, DSCR, covenants) is fundamentally different from wealth calibration (CVaR, regime, drift).
2. Each client has different risk appetite — one wants LTV < 55%, another accepts LTV < 65%.
3. Config changes require code deploy (YAML in repo, `@lru_cache` at process level).

## Proposed Solution

### Architecture

Two PostgreSQL tables + Redis cache + ConfigService + Admin API + Client self-service UI.

**Access model (see brainstorm D3, D5):**

| Config type | Client access | Netz access |
|---|---|---|
| `calibration`, `scoring`, `blocks`, `portfolio_profiles` | Self-service within guardrails | Full CRUD + guardrail definition |
| `chapters`, `tone`, `evaluation` | **Not visible** (chapters expose memo structure = IP) | Full CRUD per client request |
| `prompts` | **Never visible** (proprietary IP) | Full CRUD by prompt engineers |
| `model_routing` | Not visible | Full CRUD per vertical |

> **Decision (2026-03-14):** `chapters` removed from client-visible set. Chapter definitions expose the IC memo structure (which chapters exist, their purpose, ordering) — this is analytical methodology IP. Clients benefit from the output, not the structure. `CLIENT_VISIBLE_TYPES = {"calibration", "scoring", "blocks", "portfolio_profiles"}`.

### Table Schema (see brainstorm RQ1)

Defense-in-depth: two tables to prevent tenant config leakage.

```sql
-- Defaults: NO RLS, NO organization_id. Netz-managed. Visible to all tenants.
-- Same pattern as macro_data and allocation_blocks.
CREATE TABLE vertical_config_defaults (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vertical TEXT NOT NULL CHECK (vertical IN ('private_credit', 'liquid_funds')),
    config_type TEXT NOT NULL CHECK (config_type IN ('calibration', 'scoring', 'blocks',
                                    'chapters', 'portfolio_profiles', 'prompts',
                                    'model_routing', 'tone', 'evaluation')),
    config JSONB NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    guardrails JSONB,                -- allowed ranges for client self-service (NULL = not client-editable)
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,  -- optimistic concurrency control (Sprint 5-6)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    updated_by TEXT,
    UNIQUE (vertical, config_type)
);

-- Overrides: WITH RLS on organization_id. Tenant-specific.
CREATE TABLE vertical_config_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,   -- FK added after organizations table exists (ON DELETE RESTRICT)
    vertical TEXT NOT NULL CHECK (vertical IN ('private_credit', 'liquid_funds')),
    config_type TEXT NOT NULL CHECK (config_type IN ('calibration', 'scoring', 'blocks',
                                    'chapters', 'portfolio_profiles', 'prompts',
                                    'model_routing', 'tone', 'evaluation')),
    config JSONB NOT NULL,           -- sparse: only changed fields (deep-merged with default)
    version INTEGER NOT NULL DEFAULT 1,  -- optimistic concurrency control (Sprint 5-6)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    updated_by TEXT,
    UNIQUE (organization_id, vertical, config_type)
);

ALTER TABLE vertical_config_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE vertical_config_overrides FORCE ROW LEVEL SECURITY;

-- MUST use subselect pattern (see CLAUDE.md: "RLS subselect" rule)
CREATE POLICY org_isolation ON vertical_config_overrides
    USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));

CREATE INDEX idx_config_overrides_lookup
    ON vertical_config_overrides (vertical, config_type, organization_id);

-- Audit trail: DB trigger captures every change automatically (see brainstorm RQ2)
-- DEFERRED to Sprint 5-6: create audit table + triggers when Admin API enables writes.
-- In Sprint 3, the migration file itself IS the audit trail (only seed inserts happen).
--
-- Sprint 5-6 migration will create:
--
-- CREATE TABLE vertical_config_audit (
--     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--     operation TEXT NOT NULL,        -- 'INSERT', 'UPDATE', 'DELETE'
--     table_name TEXT NOT NULL,
--     record_id UUID NOT NULL,
--     organization_id UUID,
--     vertical TEXT NOT NULL,
--     config_type TEXT NOT NULL,
--     old_config JSONB,              -- NULL on INSERT
--     new_config JSONB,              -- NULL on DELETE
--     old_version INTEGER,
--     new_version INTEGER,
--     changed_by TEXT,
--     changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
-- );
--
-- Trigger function handles INSERT, UPDATE, AND DELETE:
-- - On DELETE: references OLD (NEW is NULL)
-- - On INSERT: references NEW (OLD is NULL)
-- - On UPDATE: auto-increments version, captures both old/new
-- - Fires pg_notify('config_changed', ...) for cache invalidation
```

### ConfigService

**Sprint 3 scope (read-only):** Only `get()`, `list_configs()`, and `deep_merge()`. Write methods, guardrails validation, and Redis cache deferred to Sprint 5-6 (YAGNI — zero writers in Sprint 3).

**Sprint 5-6 scope (full):** Add `set_default()`, `set_override()`, `validate_guardrails()`, Redis cache with pg_notify invalidation, optimistic concurrency control.

```python
# backend/app/core/config/config_service.py

class ConfigService:
    """
    Resolves configuration for a given vertical + config_type + optional org_id.
    Cascade: in-process cache → DB override (RLS) → DB default → YAML fallback.

    Sprint 3: read-only with cachetools.TTLCache (in-process, 60s).
    Sprint 5-6: add Redis L2 cache + pg_notify invalidation + write methods.
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        # In-process cache — no Redis dependency in Sprint 3
        # Replaced with Redis L2 in Sprint 5-6 when admin API enables writes

    async def get(self, vertical: str, config_type: str,
                  org_id: UUID | None = None) -> dict:
        """
        Returns deep_merge(default, override). Override wins on conflicts.
        Single DB session (get_db_with_rls) for both queries.
        """
        ...

    # IP protection: prompts, chapters, and internal config types never returned to clients.
    # Chapters expose IC memo structure (which chapters exist, ordering) — analytical methodology IP.
    CLIENT_VISIBLE_TYPES: ClassVar[frozenset] = frozenset({
        "calibration", "scoring", "blocks", "portfolio_profiles"
    })

    async def list_configs(self, vertical: str,
                           org_id: UUID | None = None,
                           is_admin: bool = False) -> list[ConfigEntry]:
        """
        Lists all config_types for a vertical, with override status.
        Non-admin callers: filters to CLIENT_VISIBLE_TYPES only (IP protection).
        """
        ...

    @staticmethod
    def deep_merge(base: dict, override: dict) -> dict:
        """
        Recursive merge. Override values win on scalars.
        Dicts are recursively merged. Lists are REPLACED (not appended).
        None values in override DELETE the key (Netz admin only — blocked for clients).
        """
        ...

    # --- Sprint 5-6 additions (not implemented in Sprint 3) ---

    async def set_default(self, vertical: str, config_type: str,
                          config: dict, guardrails: dict | None = None,
                          actor: str = None) -> None:
        """Netz super-admin sets vertical default. Validates schema. Optimistic lock via version."""
        ...

    async def set_override(self, vertical: str, config_type: str,
                           config: dict, org_id: UUID,
                           actor: str = None,
                           expected_version: int | None = None) -> None:
        """
        Set tenant-specific override. Validates against guardrails.
        Validates merged result against per-type schema (prevents accidental key deletion).
        Optimistic concurrency via version column.
        """
        ...

    async def validate_guardrails(self, vertical: str, config_type: str,
                                   proposed: dict, org_id: UUID) -> list[str]:
        """Returns list of violation descriptions. Empty = valid. Rejects unknown dot-paths."""
        ...

    async def get_with_guardrails(self, vertical: str, config_type: str,
                                   org_id: UUID) -> ConfigWithGuardrails:
        """Returns merged config + guardrail ranges for UI rendering."""
        ...
```

**FastAPI dependency:**

```python
# backend/app/core/config/dependencies.py

async def get_config_service(
    db: AsyncSession = Depends(get_db_with_rls),  # Single session for both defaults + overrides
) -> ConfigService:
    return ConfigService(db=db)
    # Note: defaults table has NO RLS, so SET LOCAL has zero effect on it.
    # Overrides table has RLS, so the same session works correctly for both.
```

### Cache Strategy (phased)

**Sprint 3 — In-process TTL cache:**
```python
from cachetools import TTLCache

# Module-level cache (safe — not an asyncio primitive)
_config_cache = TTLCache(maxsize=128, ttl=60)  # 60-second TTL

# ConfigService.get() checks _config_cache first, then DB.
# No Redis dependency. No invalidation logic. Max 60s staleness.
# Acceptable because config changes don't exist in Sprint 3.
```

**Sprint 5-6 — Add Redis L2 + pg_notify invalidation:**
```python
# When admin API enables writes, add:
# 1. Redis as L2 cache (5min TTL) behind in-process L1 (30s TTL)
# 2. pg_notify from DB trigger → asyncpg LISTEN → evict L1 + L2
# 3. pg_notify is transactional — notification sent only on commit
# 4. Single shared LISTEN connection per process (not per worker)
#
# Cache key: "config:{vertical}:{config_type}:{org_id or 'default'}"
# Invalidation: pg_notify('config_changed', '{"vertical":...,"config_type":...}')
#   → asyncpg listener → Redis DEL + L1 evict
```

### Seed Data Strategy

Current YAML files become seed data loaded by migration `0004`:

| YAML file | → | vertical | config_type |
|---|---|---|---|
| `calibration/config/limits.yaml` | → | `liquid_funds` | `calibration` |
| `calibration/config/profiles.yaml` | → | `liquid_funds` | `portfolio_profiles` |
| `calibration/config/scoring.yaml` | → | `liquid_funds` | `scoring` |
| `calibration/config/blocks.yaml` | → | `liquid_funds` | `blocks` |
| `profiles/private_credit/profile.yaml` | → | `private_credit` | `chapters` |
| (NEW — from best practices research) | → | `private_credit` | `calibration` |
| (NEW — from best practices research) | → | `private_credit` | `scoring` |

**After seed:** YAML files remain in repo as documentation/reference but are never read at runtime. `@lru_cache` loaders in quant_engine are replaced with `ConfigService.get()` calls.

## Technical Approach

### How quant_engine services change

**Before (current):**
```python
# cvar_service.py:66-89
@lru_cache(maxsize=1)
def get_profile_cvar_config():
    path = get_calibration_path() / "profiles.yaml"
    data = yaml.safe_load(path.read_text())
    return data["profiles"]
```

**After:**
```python
# cvar_service.py — receives config as parameter (like optimizer_service.py already does)
async def calculate_cvar(
    nav_data: pd.DataFrame,
    profile_name: str,
    config: dict,  # injected by caller via ConfigService.get("liquid_funds", "calibration")
) -> CVaRResult:
    cvar_config = config["cvar_limits"][profile_name]
    ...
```

**Pattern:** Follow `optimizer_service.py` which already receives `ProfileConstraints` as parameter (no YAML loading). Extend this pattern to all quant services.

### How ai_engine changes

**ProfileLoader** uses ConfigService instead of filesystem:

```python
# ai_engine/profile_loader.py
class ProfileLoader:
    def __init__(self, config_service: ConfigService):
        self._config = config_service

    async def load(self, profile_name: str, org_id: UUID | None = None) -> AnalysisProfile:
        chapters = await self._config.get(profile_name, "chapters", org_id)
        calibration = await self._config.get(profile_name, "calibration", org_id)
        model_routing = await self._config.get(profile_name, "model_routing", org_id)
        engine = self._load_engine(profile_name)
        return AnalysisProfile(
            chapters=chapters, calibration=calibration,
            model_routing=model_routing, engine=engine
        )
```

### How model_config.py changes

**Before:**
```python
# model_config.py:113-146 — hardcoded MODELS dict + env var override
MODELS = {"ch01_exec": "gpt-4.1", "ch05_legal": "claude-sonnet-4-5-20250514", ...}
def get_model(stage: str) -> str:
    env = os.environ.get(f"NETZ_MODEL_{stage.upper()}")
    return env or MODELS.get(stage, _DEFAULT_MODEL)
```

**After:**
```python
# model_config.py — ConfigService-backed with env var override preserved
async def get_model(stage: str, config_service: ConfigService,
                     vertical: str, org_id: UUID | None = None) -> str:
    # Env var still wins (for A/B testing, debugging)
    env = os.environ.get(f"NETZ_MODEL_{stage.upper()}")
    if env:
        return env
    # DB config
    routing = await config_service.get(vertical, "model_routing", org_id)
    return routing.get(stage, _DEFAULT_MODEL)
```

### Deep Merge Semantics

```python
_DELETE = object()  # sentinel — only used internally by Netz admin API

def deep_merge(base: dict, override: dict) -> dict:
    """
    Recursive merge. Override values win on scalar conflicts.
    Dicts are recursively merged. Lists are REPLACED (not appended).
    _DELETE sentinel removes key (Netz admin only — client API strips None before merge).
    """
    result = base.copy()
    for key, value in override.items():
        if value is _DELETE:
            result.pop(key, None)  # explicit deletion — admin only
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

**Safety:** Client self-service API strips `None` values from payload before calling `deep_merge`. Only Netz admin API can use `_DELETE` sentinel. After merge, the result is validated against a per-type Pydantic schema to ensure no required fields were removed.

**Example — client overrides LTV limit only:**

Default:
```json
{"leverage_limits": {"senior_secured": {"max_total_leverage": 5.0, "warning": 4.5}},
 "ltv_limits": {"senior_secured_ltv": {"max_hard": 0.65, "warning": 0.60}}}
```

Override (sparse):
```json
{"ltv_limits": {"senior_secured_ltv": {"max_hard": 0.55}}}
```

Merged result:
```json
{"leverage_limits": {"senior_secured": {"max_total_leverage": 5.0, "warning": 4.5}},
 "ltv_limits": {"senior_secured_ltv": {"max_hard": 0.55, "warning": 0.60}}}
```

### Guardrails Validation

```python
# Guardrails JSONB schema (stored on vertical_config_defaults)
{
    "ltv_limits.senior_secured_ltv.max_hard": {"min": 0.40, "max": 0.75, "type": "float"},
    "leverage_limits.senior_secured.max_total_leverage": {"min": 3.0, "max": 7.0, "type": "float"},
    "cvar_limits.conservative.limit": {"min": -15.0, "max": -3.0, "type": "float"},
    "scoring_weights.credit_quality": {"min": 0.10, "max": 0.40, "type": "float"}
}
```

Validation walks the proposed override's dot-paths, checks each against guardrails. Unknown paths (not in guardrails) are rejected. This prevents clients from injecting arbitrary keys.

### Prompt Slot System (see brainstorm RQ3)

Prompts are Netz IP — never visible to clients. Internally, prompt engineers use a **template + slots** pattern:

```python
# The Jinja2 template (stored in vertical_config_defaults, config_type='prompts')
# References calibration values dynamically:
"""
Analyze the credit structure focusing on: {{ slots.emphasis | join(', ') }}.

Apply the following thresholds:
- Maximum LTV: {{ calibration.ltv_limits.senior_secured_ltv.max_hard * 100 }}%
- Minimum DSCR: {{ calibration.coverage_ratios.dscr.minimum_hard }}x

Tone: {{ slots.tone }}
{% if slots.additional_instructions %}
Additional: {{ slots.additional_instructions }}
{% endif %}
"""
```

When a client changes their calibration (e.g., LTV from 65% to 55%), the prompt **automatically reflects the new threshold** without the client ever seeing the prompt.

## System-Wide Impact

### Interaction Graph

```
Client UI → PUT /api/v1/configs/{vertical}/calibration
  → ConfigService.validate_guardrails() → OK/reject
  → ConfigService.set_override() → DB write + audit trigger + cache invalidate
  → Redis PUBLISH config:invalidated → all service instances evict cache
  → Next analysis request → ConfigService.get() → cache miss → DB read → cache set
  → ProfileLoader.load() → vertical engine receives new config → analysis uses updated thresholds
```

### Error & Failure Propagation

- **Redis cache down:** ConfigService falls through to DB query. Performance degrades but correctness maintained. TTL-based cache means no stale data risk — just slower.
- **DB config missing:** YAML seed fallback (emergency). Logged as WARNING. Should never happen after migration.
- **Guardrail violation:** `GuardrailViolation` exception → 422 response with specific violations list.
- **Concurrent writes:** `ON CONFLICT (organization_id, vertical, config_type) DO UPDATE` ensures last-write-wins. Audit table captures both writes.
- **Migration rollback:** `downgrade()` drops the three tables. Config reverts to YAML loading (quant_engine fallback pattern already handles this).

### State Lifecycle Risks

- **Orphaned overrides:** If a tenant is deleted, `ON DELETE CASCADE` from `organizations` FK removes overrides.
- **Guardrail tightening:** If Netz tightens a guardrail after a client already has an override outside the new range, the existing override continues to work (DB doesn't validate retroactively). ConfigService should flag this on `list_configs()` as `guardrail_violation: true` so Netz admin can negotiate with the client.
- **Stale cache after pub/sub failure:** Max staleness = TTL (5 minutes). Acceptable for calibration changes which are infrequent.

## Implementation Phases

### Phase 1: Backend Foundation (Sprint 3 — alongside vertical engines)

**Goal:** Read-only ConfigService operational. All quant_engine and ai_engine services use ConfigService instead of YAML. No write API, no Redis, no audit triggers, no guardrails validation (YAGNI — zero writers in Sprint 3).

#### Tasks

- [x] **Migration `0004_vertical_configs.py`**
  - Create `vertical_config_defaults` table (no RLS, CHECK constraints on vertical/config_type)
  - Create `vertical_config_overrides` table (with RLS, subselect pattern, CHECK constraints)
  - Create index on overrides lookup
  - Seed `vertical_config_defaults` using `INSERT ... ON CONFLICT DO NOTHING` (idempotent):
    - `calibration/config/limits.yaml` → `(liquid_funds, calibration)`
    - `calibration/config/profiles.yaml` → `(liquid_funds, portfolio_profiles)`
    - `calibration/config/scoring.yaml` → `(liquid_funds, scoring)`
    - `calibration/config/blocks.yaml` → `(liquid_funds, blocks)`
    - `profiles/private_credit/profile.yaml` → `(private_credit, chapters)`
    - NEW `calibration/seeds/private_credit/calibration.yaml` → `(private_credit, calibration)`
    - NEW `calibration/seeds/private_credit/scoring.yaml` → `(private_credit, scoring)`
  - Set `created_by = 'migration:0004'` on all seed rows (provenance)
  - Add `guardrails JSONB` column (populated but NOT validated until Sprint 7)
  - `downgrade()`: drop both tables + index. WARNING comment: destroys all config data.
  - **Deferred to Sprint 5-6:** audit table, trigger function, pg_notify

- [x] **`backend/app/core/config/config_service.py`** — ConfigService (read-only for Sprint 3)
  - `get()` with cascade: in-process TTLCache → DB override → DB default → YAML fallback (logged as ERROR)
  - `list_configs()` — all config_types for a vertical (filters prompts/model_routing for non-admin)
  - `deep_merge()` static method — recursive, lists replaced, _DELETE sentinel (admin only)
  - In-process cache: `cachetools.TTLCache(maxsize=128, ttl=60)`
  - Single session (`get_db_with_rls`) for both defaults + overrides queries
  - **Deferred to Sprint 5-6:** `set_default()`, `set_override()`, `validate_guardrails()`, `get_with_guardrails()`, Redis L2 cache, pg_notify invalidation

- [x] **`backend/app/core/config/dependencies.py`** — FastAPI dependency
  - `get_config_service(db = Depends(get_db_with_rls))` — single session
  - **No `get_redis()` dependency in Sprint 3**

- [x] **`backend/app/core/config/schemas.py`** — Pydantic schemas (Sprint 3 subset)
  - `ConfigEntry` — vertical, config_type, has_override
  - **Deferred to Sprint 5-6:** `ConfigWithGuardrails`, `ConfigUpdate`, `GuardrailViolation`

- [x] **`backend/app/core/config/models.py`** — SQLAlchemy models
  - `VerticalConfigDefault` — `Base + IdMixin + AuditMetaMixin` (no OrganizationScopedMixin)
  - `VerticalConfigOverride` — `Base + IdMixin + OrganizationScopedMixin + AuditMetaMixin`
  - **Deferred to Sprint 5-6:** `VerticalConfigAudit`

- [x] **Refactor `quant_engine/` services** — remove YAML loading, receive config as parameter
  - `cvar_service.py` — remove `@lru_cache` + `get_profile_cvar_config()` + module-level `PROFILE_CVAR_CONFIG` constant. Add `config: dict` parameter. Update all callers of `check_breach_status`.
  - `regime_service.py` — remove `@lru_cache` + `get_regime_thresholds()`, add `config: dict` parameter
  - `scoring_service.py` — remove `@lru_cache` + `get_scoring_weights()`, add `config: dict` parameter
  - `drift_service.py` — if loads YAML, same treatment
  - Keep hardcoded fallback defaults inside each service for backward compatibility during transition
  - **Pattern:** follow `optimizer_service.py` which already receives config as parameter

- [x] **Update wealth domain routes** — inject ConfigService into routes that call quant_engine
  - Config resolved once at async entry point, passed as parameter to sync functions:
    ```python
    @router.get(...)
    async def get_risk(
        config_service: ConfigService = Depends(get_config_service),
        actor: Actor = Depends(get_actor),
    ):
        config = await config_service.get("liquid_funds", "calibration", actor.organization_id)
        result = calculate_cvar(nav_data, profile, config)  # sync function, config as param
    ```

- [ ] **`ai_engine/profile_loader.py`** — update to use ConfigService
  - `ProfileLoader.__init__(config_service)` instead of filesystem loading
  - `load(profile_name, org_id)` → queries chapters, calibration from ConfigService
  - Instantiates correct vertical engine class from registry
  - **model_routing stays as env vars** (deferred to Sprint 5-6 — env vars work fine)

- [x] **Credit calibration seed YAML** — create from best practices research
  - `calibration/seeds/private_credit/calibration.yaml` — leverage limits, coverage ratios, LTV, concentration, tenor, regime, scenarios, monitoring triggers
  - `calibration/seeds/private_credit/scoring.yaml` — credit deal scoring weights
  - These are seed files only — loaded by migration 0004, never read at runtime
  - Add header comment: `# SEED DATA ONLY — loaded by migration 0004. Runtime config is in PostgreSQL.`
  - **NOTE: This is an engine improvement, not just infrastructure.** These values (sourced from Moody's Annual Default Study, S&P Recovery Reports, Basel III, Ares Capital/Blue Owl filings) will feed `ic_critic_engine` and `ic_quant_engine` as DB-backed defaults — likely better calibrated than the hardcoded values in the original Private Credit OS. The migration from hardcoded → DB-backed institutional defaults is a direct analytical quality upgrade.

- [x] **Startup health check** — verify config completeness
  - On app startup, query `vertical_config_defaults` and verify all expected `(vertical, config_type)` pairs exist
  - Log ERROR if any are missing (indicates migration failure)

- [x] **Security hardening (Sprint 3)**
  - `CLIENT_VISIBLE_TYPES` allowlist enforced in `get()` and `list_configs()` for non-admin callers
  - `vertical` and `config_type` validated via Pydantic `Literal` in all route path parameters
  - `ConfigService.get()` adds explicit `WHERE organization_id = :org_id` as secondary guard on override queries (belt-and-suspenders with RLS)
  - YAML fallback logged as ERROR (not WARNING) — indicates config system degraded

- [x] **Tests**
  - `test_config_service.py` — unit tests for `get()` cascade, `deep_merge()`, `list_configs()`
  - `test_config_migration.py` — verify seed data loaded correctly, verify idempotency
  - `test_config_integration.py` — ConfigService with real DB (test override → merged result)
  - `test_config_ip_protection.py` — verify `list_configs()` never returns `prompts` for non-admin
  - Verify quant_engine services work with injected config (same output as YAML)

##### Acceptance Criteria

- [ ] `ConfigService.get("liquid_funds", "calibration")` returns same values as current YAML
- [ ] `ConfigService.get("private_credit", "calibration")` returns credit-specific thresholds
- [ ] Tenant override merges correctly with default (deep merge, sparse override)
- [ ] In-process cache hit on second call within 60s TTL
- [ ] All existing quant_engine tests pass with injected config
- [ ] Startup health check logs OK for all seeded config_types
- [ ] Migration is idempotent (running twice does not fail or duplicate)
- [ ] `make check` passes

##### Key Files

| File | Action | Notes |
|------|--------|-------|
| `core/config/config_service.py` | NEW | Read-only service — cascade, TTL cache, merge |
| `core/config/dependencies.py` | NEW | FastAPI DI — get_config_service (single session) |
| `core/config/schemas.py` | NEW | Pydantic schemas (ConfigEntry only for Sprint 3) |
| `core/config/models.py` | NEW | SA models for config tables |
| `core/db/migrations/versions/0004_vertical_configs.py` | NEW | Tables + triggers + seed data |
| `quant_engine/cvar_service.py` | MODIFY | Remove YAML loading, add config param |
| `quant_engine/regime_service.py` | MODIFY | Remove YAML loading, add config param |
| `quant_engine/scoring_service.py` | MODIFY | Remove YAML loading, add config param |
| `ai_engine/profile_loader.py` | MODIFY | Use ConfigService instead of filesystem |
| `calibration/seeds/private_credit/calibration.yaml` | NEW | Seed data |
| `calibration/seeds/private_credit/scoring.yaml` | NEW | Seed data |

---

### Phase 2: Admin API + Write Infrastructure (Sprint 5-6 — alongside frontend development)

**Goal:** Netz super-admin can manage all configs via API. Add write methods, audit trail, Redis L2 cache, pg_notify invalidation, optimistic concurrency.

> **Open deliberation for Sprint 5-6:** Re-evaluate whether `portfolio_profiles` belongs in `CLIENT_VISIBLE_TYPES`. In wealth management, portfolio profile parameters (Conservative/Moderate/Growth with CVaR limits, strategic allocations, core/satellite weights) define the analytical methodology — comparable to how `chapters` defines IC memo structure in credit. Both describe *how* the engine analyzes, not just threshold calibration. If the client shouldn't see the chapter structure, should they see the profile structure? Sprint 3 ships with `portfolio_profiles` client-visible (safe — read-only, no write API). Revisit when building the client self-service UI (Sprint 7).

#### Tasks

- [ ] **Migration `0005_config_audit_triggers.py`** — deferred from Sprint 3
  - Create `vertical_config_audit` table (with `operation TEXT` column)
  - Create `audit_config_change()` trigger function (handles INSERT/UPDATE/DELETE)
  - Attach trigger to both defaults and overrides tables
  - Add `pg_notify('config_changed', ...)` in trigger function for cache invalidation

- [ ] **ConfigService write methods** — add to existing `config_service.py`
  - `set_default()` with Pydantic schema validation + optimistic locking (`WHERE version = :expected`)
  - `set_override()` with guardrail validation + merged result schema validation
  - `validate_guardrails()` — dot-path walk + range check + reject unknown paths
  - `get_with_guardrails()` — merged config + guardrail ranges for UI

- [ ] **Redis L2 cache + pg_notify invalidation**
  - Add Redis as L2 cache behind in-process L1 (upgrade TTLCache to two-tier)
  - Single shared asyncpg LISTEN connection per process for `config_changed` channel
  - On notification: evict L1 + DEL Redis key
  - Wire listener start/stop into FastAPI lifespan

- [ ] **`backend/app/domains/admin/routes/configs.py`** — Admin config API
  - `GET /api/v1/admin/configs/{vertical}` — list all config_types with override status
  - `GET /api/v1/admin/configs/{vertical}/{config_type}` — get default config + guardrails
  - `PUT /api/v1/admin/configs/{vertical}/{config_type}` — update default
  - `GET /api/v1/admin/configs/{vertical}/{config_type}/overrides` — list all tenant overrides
  - `GET /api/v1/admin/configs/{vertical}/{config_type}/overrides/{org_id}` — get specific override
  - `PUT /api/v1/admin/configs/{vertical}/{config_type}/overrides/{org_id}` — set override (bypasses guardrails for admin)
  - `DELETE /api/v1/admin/configs/{vertical}/{config_type}/overrides/{org_id}` — reset to default
  - `GET /api/v1/admin/configs/{vertical}/{config_type}/audit` — audit history

- [ ] **Admin role gate** — `require_netz_admin()` dependency (SECURITY CRITICAL)
  - Must NOT use existing `org:admin` role — every tenant has org:admin
  - Use Clerk `publicMetadata.netz_admin: true` (server-side only, cannot be self-assigned by tenants)
  - 403 for non-Netz users on all `/api/v1/admin/` endpoints
  - Admin routes NOT mounted under normal API prefix — separate `/api/v1/admin/` mount
  - Verify `validate_production_secrets()` is called at startup (prevents dev bypass in production)
  - **Provisioning:** First Netz admin account must be created via Clerk Dashboard or Clerk Backend API (`users.updateUser(userId, { publicMetadata: { netz_admin: true } })`). This CANNOT be done via Clerk client SDK or frontend — `publicMetadata` is server-side only by design. Document this in runbook/onboarding docs.

- [ ] **Jinja2 security** — use `SandboxedEnvironment` for all prompt rendering
  - Disable `__` attribute access (prevents SSTI attacks)
  - Validate template syntax at write time before storing in DB
  - Never return template content or rendering errors to client API responses

- [ ] **Audit table immutability**
  - `REVOKE UPDATE, DELETE ON vertical_config_audit FROM app_user`
  - Audit records are write-once — only the trigger can INSERT

- [ ] **Config diff/preview endpoint**
  - `POST /api/v1/admin/configs/{vertical}/{config_type}/preview` — accepts proposed override, returns merged result without saving (dry-run)
  - Useful for prompt engineers to preview effect of changes

- [ ] **Prompt management endpoints** (Netz prompt engineers only)
  - `GET /api/v1/admin/configs/{vertical}/prompts` — list all chapter prompts
  - `PUT /api/v1/admin/configs/{vertical}/prompts` — update prompts
  - `POST /api/v1/admin/configs/{vertical}/prompts/render` — render a prompt with sample data (preview)
  - These endpoints NEVER exposed to client roles

- [ ] **Tests** — admin API auth, CRUD operations, audit trail verification

##### Acceptance Criteria

- [ ] Netz admin can CRUD all config types via API
- [ ] Non-admin users get 403 on admin endpoints
- [ ] Config preview shows merged result without saving
- [ ] Prompt render preview works with sample data
- [ ] Audit history shows all changes with who/when/what

---

### Phase 3: Client Self-Service UI (Sprint 7+ — alongside wealth frontend)

**Goal:** Clients can view and edit their calibration within guardrails.

#### Tasks

- [ ] **Client config API** (subset of admin API, guardrail-enforced)
  - `GET /api/v1/configs/{vertical}/calibration` — get merged config + guardrails for current org
  - `PUT /api/v1/configs/{vertical}/calibration` — update calibration (validates guardrails)
  - `GET /api/v1/configs/{vertical}/scoring` — get merged scoring + guardrails
  - `PUT /api/v1/configs/{vertical}/scoring` — update scoring (validates guardrails)
  - `GET /api/v1/configs/{vertical}/blocks` — get blocks + guardrails (if applicable)
  - **NO endpoints for:** prompts, chapters, model_routing, tone, evaluation (not client-accessible)

- [ ] **Frontend component** — Calibration editor
  - Renders each editable field with current value, min/max guardrail, slider/input
  - Shows "Default" badge for values that match vertical default
  - "Reset to default" button per field
  - Save → validates → shows success or violation errors
  - Audit log view (read-only) — who changed what when

- [ ] **Guardrail UI rendering**
  - `ConfigWithGuardrails` response includes guardrails + current merged config
  - Frontend renders: value slider with min/max stops, input field with validation
  - Visual indicator: green (within range), yellow (near boundary), red (at limit)

##### Acceptance Criteria

- [ ] Client can view their calibration with guardrail ranges
- [ ] Client can edit calibration within guardrails, save, see instant effect on next analysis
- [ ] Client cannot access prompts, chapters, model routing
- [ ] Reset to default works per-field
- [ ] Audit log shows change history

## Credit Calibration Seed Data

Based on best practices research (see brainstorm: "Private Credit Calibration — Best Practices Research"). Sourced from Moody's Annual Default Study, S&P Recovery Reports, Basel III, Ares Capital/Blue Owl public filings.

### `calibration/seeds/private_credit/calibration.yaml`

```yaml
# Private Credit Calibration Defaults
# Sources: Moody's, S&P, Basel III, institutional practice

leverage_limits:
  senior_secured:
    max_total_leverage: 5.0
    warning_threshold: 4.5
    preferred_range: [2.5, 4.0]
  unitranche:
    max_total_leverage: 5.5
    warning_threshold: 5.0
  second_lien:
    max_total_leverage: 6.5
    warning_threshold: 6.0

coverage_ratios:
  dscr:
    minimum_hard: 1.10
    warning: 1.25
    comfortable: 1.50
    strong: 2.00
  interest_coverage:
    minimum_hard: 1.50
    warning: 1.75
    comfortable: 2.50
    strong: 4.00
  fixed_charge_coverage:
    minimum_hard: 1.00
    warning: 1.15
    comfortable: 1.30

ltv_limits:
  senior_secured_ltv:
    max_hard: 0.65
    warning: 0.60
    preferred_range: [0.40, 0.55]
  unitranche_ltv:
    max_hard: 0.70
    warning: 0.65
  second_lien_ltv:
    max_hard: 0.80
    warning: 0.75
  tev_stress_haircut_pct: 25.0

portfolio_concentration:
  single_obligor_max_pct: 10.0
  single_obligor_warning_pct: 7.5
  top5_obligors_max_pct: 40.0
  single_sector_max_pct: 25.0
  single_country_max_pct: 40.0
  emerging_markets_max_pct: 15.0
  second_lien_max_pct: 20.0
  pik_max_pct: 15.0

tenor_limits:
  max_weighted_avg_life_years: 5.0
  max_single_deal_tenor_years: 7.0
  preferred_tenor_range: [3.0, 5.0]

credit_regime_thresholds:
  hy_oas_normal: 350
  hy_oas_cautious: 500
  hy_oas_stress: 700
  hy_oas_crisis: 1000
  default_rate_normal: 2.0
  default_rate_elevated: 4.0
  default_rate_stress: 6.0
  default_rate_crisis: 10.0
  default_regime: NORMAL

credit_regime_definitions:
  NORMAL:
    new_deal_adjustment: 0.0
    spread_premium_bps: 0
    max_leverage_adj: 0.0
  CAUTIOUS:
    new_deal_adjustment: -0.20
    spread_premium_bps: 50
    max_leverage_adj: -0.5
  STRESS:
    new_deal_adjustment: -0.50
    spread_premium_bps: 150
    max_leverage_adj: -1.0
    covenant_requirement: FULL_MAINTENANCE
  CRISIS:
    new_deal_adjustment: -0.80
    spread_premium_bps: 300
    max_leverage_adj: -1.5
    covenant_requirement: FULL_MAINTENANCE

scenario_calibration:
  base:
    default_rate_pct: 2.0
    recovery_rate_pct: 67.0
    revenue_growth_pct: 3.0
    ebitda_margin_change_bps: 0
    rate_shock_bps: 0
  downside:
    default_rate_pct: 5.0
    recovery_rate_pct: 50.0
    revenue_decline_pct: -10.0
    ebitda_margin_compression_bps: -200
    rate_shock_bps: 100
  severe:
    default_rate_pct: 10.0
    recovery_rate_pct: 35.0
    revenue_decline_pct: -25.0
    ebitda_margin_compression_bps: -500
    rate_shock_bps: 200
  tail:
    default_rate_pct: 15.0
    recovery_rate_pct: 25.0
    revenue_decline_pct: -40.0
    ebitda_margin_compression_bps: -800
    rate_shock_bps: -200

return_requirements:
  min_spread_bps:
    core_senior_secured: 450
    unitranche: 550
    second_lien: 750
    venture_debt: 800
    distressed: 1000
  net_irr_targets:
    core_direct_lending: [8.0, 12.0]
    opportunistic: [12.0, 16.0]
    distressed: [15.0, 20.0]

monitoring_triggers:
  leverage_deterioration:
    warning: 0.5
    critical: 1.0
  dscr_deterioration:
    warning: -0.15
    critical: -0.30
  revenue_decline:
    warning_pct: -10.0
    critical_pct: -20.0
  payment_delay_days:
    grace_period: 5
    watchlist: 15
    default_event: 30
  nav_markdown:
    warning_pct: 5.0
    critical_pct: 15.0
  covenant_headroom:
    comfortable_pct: 25.0
    tight_pct: 10.0
    critical_pct: 5.0
```

### `calibration/seeds/private_credit/scoring.yaml`

```yaml
# Credit Deal Scoring Weights
credit_scoring_weights:
  credit_quality: 0.25
  return_adequacy: 0.20
  structural_protection: 0.15
  sponsor_quality: 0.15
  business_quality: 0.10
  documentation_completeness: 0.10
  liquidity_profile: 0.05
```

## Do Not Touch List Additions

| Component | Reason |
|---|---|
| `ConfigService.deep_merge()` semantics | All consumers depend on merge behavior |
| `vertical_config_audit` trigger | Audit trail integrity |
| Guardrail validation logic | Client trust — guardrails must be enforced consistently |

## Anti-Patterns

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| Reading YAML at runtime after migration | Two sources of truth, stale data | Always use `ConfigService.get()` |
| Exposing prompts in client API responses | IP leakage | Prompt endpoints restricted to Netz admin role only |
| `@lru_cache` on config loading | No per-tenant override, no invalidation | ConfigService with Redis cache + pub/sub |
| Guardrails without validation on write | Client can set dangerous values | Always `validate_guardrails()` before `set_override()` |
| RLS policy without subselect on overrides | 1000x slowdown per-row evaluation | `(SELECT current_setting(...))` pattern |

## Dependencies & Prerequisites

| Dependency | Required By | Status |
|---|---|---|
| PostgreSQL 16 + TimescaleDB | Sprint 3 | Available (docker-compose) |
| Redis 7 | Sprint 3 | Available (docker-compose) |
| Migration 0003 (credit domain) | Before 0004 | Done |
| Vertical engines architecture | Sprint 3 | Planned (same sprint) |
| Clerk admin roles (`publicMetadata.netz_admin`) | Sprint 5-6 | SECURITY CRITICAL — must NOT use `org:admin`. Define via Clerk dashboard/API (server-side only). |

## Success Metrics

| Metric | Target | Measured By |
|---|---|---|
| Config cascade correctness | 100% — override wins, default fallback works | Integration tests |
| Cache hit rate | > 95% after warm-up | Redis monitoring |
| Guardrail enforcement | 100% — no out-of-range overrides saved | Unit tests + API tests |
| Audit completeness | 100% — every change captured | DB trigger + test verification |
| Zero YAML reads at runtime | 0 calls to `yaml.safe_load` in hot path | grep + code review |
| Prompt IP protection | 0 prompt content in client API responses | Security audit |

## Sources & References

### Origin

- **Brainstorm:** [docs/brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md](../brainstorms/2026-03-14-customizable-vertical-config-brainstorm.md) — Key decisions: DB-backed config (D1), cascade resolution (D2), client self-service calibration only (D3), per-vertical schemas (D4), prompts as Netz IP (D5), phased implementation (D6), two tables for defense in depth (RQ1), audit via DB trigger (RQ2), template slots for prompts (RQ3).

### Internal References

- YAML loading pattern: `backend/quant_engine/cvar_service.py:66-89`
- Config path resolution: `backend/app/core/config/settings.py:90-94`
- FastAPI DI chain: `backend/app/core/tenancy/middleware.py:28-48`
- Redis pub/sub pattern: `backend/app/core/jobs/tracker.py:26-84`
- Migration pattern: `backend/app/core/db/migrations/versions/0003_credit_domain.py`
- RLS policy pattern: same file, `_RLS_TABLES` loop
- Mixins: `backend/app/core/db/base.py:21-83`
- Model routing: `backend/ai_engine/model_config.py:113-146`

### Institutional Learnings

- RLS subselect performance: `docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md`
- Async safety: module-level asyncio primitives cause event loop errors (CLAUDE.md)
- Three-phase session pattern: pre-fetch → async compute → post-write (CLAUDE.md)
