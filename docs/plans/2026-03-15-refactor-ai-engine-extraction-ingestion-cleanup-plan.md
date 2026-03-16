---
title: "refactor: ai_engine extraction/ingestion cleanup"
type: refactor
status: completed
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-ai-engine-extraction-ingestion-cleanup-brainstorm.md
---

# refactor: ai_engine extraction/ingestion cleanup

## Enhancement Summary

**Deepened on:** 2026-03-15  |  **Re-deepened:** 2026-03-16 (12 parallel agents, 8 critical/high findings)
**Review agents (round 1):** architecture-strategist, data-migration-expert, code-simplicity-reviewer, kieran-python-reviewer, security-sentinel, performance-oracle, learnings-researcher
**Review agents (round 2 — 12 parallel):** architecture-strategist, data-migration-expert, code-simplicity-reviewer, kieran-python-reviewer, security-sentinel, performance-oracle, learnings-researcher, spec-flow-analyzer, pattern-recognition-specialist, best-practices-researcher (×2: Pydantic v2, Alembic CHECK), framework-docs-researcher (Pydantic v2.12.5)

### Critical Issues Discovered (round 2)

11. **CRITICAL: CHECK constraint drops `macro_intelligence`** — Migration 0005 already added `macro_intelligence` to the CHECK constraint. The plan's 0007 migration omits it, which would **fail on any real database** where the 0005 seed row exists. Must include all 11 values: `calibration, scoring, blocks, chapters, portfolio_profiles, prompts, model_routing, tone, evaluation, macro_intelligence, governance_policy`. _(data-migration-expert, pattern-recognition)_
12. **CRITICAL: `ON CONFLICT DO NOTHING` + rowcount assertion contradiction** — `ON CONFLICT DO NOTHING` returns rowcount=0 when row pre-exists, triggering the RuntimeError. This makes the migration NOT idempotent despite the ON CONFLICT clause. **Fix:** Remove rowcount assertion (match 0004/0005 pattern) OR remove ON CONFLICT. _(data-migration-expert)_
13. **HIGH: Downgrade missing DELETE from overrides table** — If any org has a governance_policy override, the restored CHECK constraint will fail. Downgrade must DELETE from `vertical_config_overrides` before restoring constraints. _(data-migration-expert, spec-flow-analyzer)_
14. **HIGH: Pydantic defaults must use `Field(default_factory=lambda: ...)`** — While Pydantic v2 deep-copies class-level defaults, `Field(default_factory=...)` is the idiomatic v2 pattern and avoids 18 ThresholdEntry constructions at import time. _(kieran-python-reviewer, best-practices-researcher, framework-docs-researcher)_
15. **HIGH: `if not config:` catches empty dict `{}`** — `bool({})` is False. ConfigService returning `{}` (valid: "no governance policy exists") would skip `raw_policy` assignment. **Fix:** Use `if config is None:` for the guard. _(kieran-python-reviewer, spec-flow-analyzer)_
16. **MEDIUM: Validate list-type field elements are strings** — An org override with `board_override_triggers: [{"__import__": "os"}]` would crash `_check_board_override()` (unhashable dict in `trigger_map.get()`). Add `[x for x in val if isinstance(x, str)]` validation. _(security-sentinel)_
17. **MEDIUM: `ThresholdEntry.value` typed as `Any`** — Should be `float | list[str]` for Pydantic validation. _(kieran-python-reviewer)_
18. **MEDIUM: Tenant-keyed cache needed before Sprint 3** — Without it, Sprint 3's ConfigService wiring causes 3× redundant Search/LLM overlay per deep review (15-45s wasted). Add `_tenant_cache: dict[str, tuple[float, PolicyThresholds]]` keyed by org_id, TTL 300s. _(performance-oracle)_

### Issues from Round 1 (preserved)

1. **SQL injection in migration** — f-string interpolation replaced with parameterized query
2. **Cache key ignores config param** — tenant isolation bug fixed by bypassing cache when config is provided
3. **CLIENT_VISIBLE_TYPES exposure** — `governance_policy` as separate config_type (Option B), NOT inside `calibration`

### Architectural Decision (2026-03-16): Schema-Free Calibration

**All calibration config is schema-free JSONB.** This applies to governance_policy and
retroactively to the entire `calibration/` system. Seeds are examples, not canonical schemas.

**Before:** calibration = fixed schema with predefined fields, PolicyThresholds = rigid dataclass
**After:** calibration = free-form JSONB per org, PolicyThresholds = Pydantic BaseModel(extra="allow")

Key implications:
- `PolicyThresholds` dataclass → Pydantic `BaseModel` with `ConfigDict(extra="allow")`
- Known fields (single_manager_pct etc.) keep type hints for current consumers
- Unknown fields accepted without error — any fund can have any structure
- `resolve_governance_policy()` reads flat JSONB, does NOT map field-by-field to fixed schema
- YAML seeds are examples for Netz Private Credit Fund, not canonical schemas
- `VerticalConfigOverride` accepts any JSONB structure per org_id
- Migration 0007 inserts opaque JSONB — no field validation in migration

### Code Quality Improvements

4. Simplified resolver — single loop with `isinstance` check instead of scalar/list split
5. `float(bool)` guard — `float(True)` silently returns 1.0
6. Removed `warnings.warn` on extraction_orchestrator — docstring-only for internal codebase
7. Type hint `dict` → `dict[str, Any]` for mypy strict
8. Migration rowcount assertion — fail loudly if target row missing
9. Removed `logger.warning` for missing governance_policy key — normal state, not actionable
10. Test count reduced from 8 → 6 focused cases

---

## Overview

Structural cleanup of `ai_engine/extraction/` and `ai_engine/ingestion/` post-pipeline-refactor, plus ConfigService alignment for `governance/policy_loader.py`. Three sequential PRs with decreasing risk. No behavioral changes.

## Problem Statement

After the pipeline refactor (PRs #20-#22), two systems coexist without clarity:

1. `ai_engine/pipeline/` — new, clean orchestration layer
2. `ai_engine/extraction/` + `ai_engine/ingestion/` — legacy directories with unclear roles

Additionally, `policy_loader.py` has 14 hardcoded Investment Policy thresholds (`_DEFAULTS`) that should flow through ConfigService, violating the architectural decision that all runtime config comes from PostgreSQL via ConfigService (see brainstorm: Decision 4).

## Proposed Solution

Three PRs in sequence (see brainstorm: Prioritization):

- **P1** — policy_loader ConfigService migration (config alignment)
- **P2** — Deprecation markers + boundary documentation (structural clarity)
- **P3** — Minor `__init__.py` docstring cleanups (polish)

## Technical Approach

### Prerequisite

All PRs start after Phase 3 PR C (#27) merges to `main`. ✅ Merged.

### Codebase Review (2026-03-16)

**Confirmed accurate:** _DEFAULTS (18 fields), YAML path, migration sequence (0006→0007),
line numbers for callers (329, 1372, 1486), SEARCH_ENDPOINT/SEARCH_API_KEY exports.

**Adjustment 1 — Defer caller wiring (Option A):**
`async_run_deal_deep_review_v4` receives `db: Session` (sync), NOT `AsyncSession`.
ConfigService requires `AsyncSession`. All callers (`worker_app/function_app.py`,
`pipeline_dispatch.py`) create sync sessions via `get_session_local()()`.
**Decision:** Keep ALL callers at `config=None` (no behavioral change). Add
`# TODO(Sprint 3): wire ConfigService when async session migration lands` at each
call site. The `resolve_governance_policy()` function, migration, YAML seed, and tests
are the deliverable — caller wiring is Sprint 3 scope.

**Adjustment 2 — `local_reranker.py` deleted:**
Removed in dead code audit (commit `d0cfe76`). Must be removed from PR 2 Step 2.2
extraction `__init__.py` docstring.

**Adjustment 3 — Existing `__init__.py` docstrings:**
`pipeline/__init__.py`, `classification/__init__.py`, `prompts/__init__.py` already have
reasonable docstrings with exports. Only update in PR 3 if the new version is strictly better.

---

### PR 1: policy_loader ConfigService migration (schema-free)

**Branch:** `refactor/policy-loader-configservice`

> **Architectural decision (2026-03-16):** Option B + schema-free JSONB.
> governance_policy is a separate config_type (not inside calibration),
> NOT in CLIENT_VISIBLE_TYPES. The JSONB is free-form — any fund can
> have any structure in its Investment Policy. Seeds are examples only.

#### Step 1.1 — PolicyThresholds: dataclass → Pydantic BaseModel(extra="allow")

**File:** `backend/ai_engine/governance/policy_loader.py`

Replace `PolicyThresholds` dataclass with a Pydantic `BaseModel` that:
- Keeps known fields typed as `ThresholdEntry` for current consumers
- Accepts arbitrary extra fields via `ConfigDict(extra="allow")`
- Stores the raw policy dict for LLM-based evaluation
- Preserves `.summary()`, `.hard_limits_dict()`, `.to_dict()` methods

```python
from pydantic import BaseModel, ConfigDict, Field

class ThresholdEntry(BaseModel):
    """A single policy threshold with full audit trail."""
    value: float | list[str]   # NOT Any — enables Pydantic validation (round 2: kieran-python)
    source: str = "DEFAULT"
    document: str = ""
    chunk_id: str = ""
    rationale: str = ""
    extracted_by: str = "DEFAULT"


class PolicyThresholds(BaseModel):
    """Governance policy thresholds.

    Known fields have type hints for current consumers
    (concentration_engine, deep_review/policy). Unknown fields from
    any fund's Investment Policy Statement are accepted via extra="allow".

    The raw_policy dict is passed to LLM-based policy evaluation
    (deep review compliance stage) as opaque context — the LLM reads
    whatever fields the fund's IPS defines, not just the known ones.
    """
    model_config = ConfigDict(extra="allow")

    # Use Field(default_factory=lambda: ...) — idiomatic Pydantic v2 pattern.
    # Avoids 18 ThresholdEntry constructions at import time.
    # Pydantic deep-copies defaults per instance (verified on v2.12.5).

    # Concentration limits — hard limits (Investment Policy s.4)
    single_manager_pct:    ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_manager_pct"]))
    single_investment_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_investment_pct"]))
    single_sector_pct:     ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_sector_pct"]))
    single_geography_pct:  ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["single_geography_pct"]))
    top3_names_pct:        ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["top3_names_pct"]))

    # Allocation constraints — hard limits
    non_usd_unhedged_pct:       ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["non_usd_unhedged_pct"]))
    min_commingled_pct:         ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_commingled_pct"]))
    max_hard_lockup_pct:        ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_hard_lockup_pct"]))
    max_lockup_years:           ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_lockup_years"]))
    min_quarterly_liquidity_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_quarterly_liquidity_pct"]))

    # Soft limits
    max_leverage_underlying_pct:    ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_leverage_underlying_pct"]))
    min_manager_track_record_years: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_manager_track_record_years"]))
    min_manager_aum_usd:            ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["min_manager_aum_usd"]))
    max_manager_default_rate_pct:   ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["max_manager_default_rate_pct"]))

    # Governance rules
    board_override_triggers:        ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["board_override_triggers"]))
    watchlist_triggers:             ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["watchlist_triggers"]))
    ic_approval_required_above_pct: ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["ic_approval_required_above_pct"]))
    review_frequency_days:          ThresholdEntry = Field(default_factory=lambda: ThresholdEntry(**_DEFAULTS["review_frequency_days"]))

    # Metadata
    loaded_at: float = Field(default_factory=time.time)
    load_errors: list[str] = Field(default_factory=list)
    raw_policy: dict[str, Any] = Field(default_factory=dict)
```

### Research Insights: Pydantic v2 Migration (round 2)

**Empirically verified on Pydantic v2.12.5** (project's installed version):

- **Deep-copy safety:** Pydantic v2 deep-copies unhashable defaults per instance. Both `Field(default_factory=lambda: ...)` and direct `ThresholdEntry(...)` are safe. Factory is preferred to avoid import-time cost.
- **`setattr()` works** on Pydantic v2 BaseModel instances. Without `validate_assignment`, stores raw values (no coercion). Since resolver constructs `ThresholdEntry` objects before `setattr`, values are already correct types. Alternative: build overrides dict, construct once via `PolicyThresholds(**overrides)`.
- **`model_dump()` includes extra fields** when `extra="allow"`. Recursive serialization of nested Pydantic models is handled by the Rust serializer — **faster** than `asdict()` (no `copy.deepcopy`).
- **`from __future__ import annotations`** is safe with Pydantic v2.12.5. No known issues for standard usage.
- **`model_fields`** (class attribute) replaces `__dataclass_fields__`. Returns `dict[str, FieldInfo]`.
- **First `extra="allow"` model in codebase.** Current convention: Pydantic for API schemas, dataclass for domain objects. This is a justified precedent for schema-free config objects. _(pattern-recognition)_
- **Performance:** Construction overhead ~15-40µs (Pydantic v2) vs ~5-10µs (dataclass). Irrelevant — cached for 3600s, dominated by 5-15s Search/LLM I/O. `model_dump()` is actually 2x faster than `asdict()`. _(performance-oracle)_

**Consumer compatibility analysis (confirmed 2026-03-16):**

| Consumer | Access pattern | Compatible? | Notes |
|---|---|---|---|
| `concentration_engine.py` | `policy.single_manager_pct.value` (8 fields) | Yes | ThresholdEntry interface preserved |
| `deep_review/policy.py` | `policy.single_manager_pct.value` (4 fields) | Yes | Same interface |
| `deep_review/service.py` | Passes `policy` to above | Yes | No direct field access |
| `_check_board_override()` | `policy.board_override_triggers.value` | Yes | ThresholdEntry preserved |
| `policy.summary()` | Iterates known fields | Needs update | `__dataclass_fields__` → `model_fields` |
| `policy.to_dict()` | `__dataclass_fields__` + `asdict()` | Needs update | → `model_dump()` |
| `policy.hard_limits_dict()` | Direct field access | Yes | No change needed |
| `_apply_extracted()` | `setattr()` + `getattr()` | Yes | Pydantic supports setattr |

**Method migrations:**

```python
def to_dict(self) -> dict:
    return self.model_dump()

def summary(self) -> dict:
    """Compact summary for logging and memo injection."""
    fields = [
        "single_manager_pct", "single_investment_pct",
        "single_sector_pct", "single_geography_pct", "top3_names_pct",
        "non_usd_unhedged_pct", "max_hard_lockup_pct", "max_lockup_years",
        "min_quarterly_liquidity_pct", "board_override_triggers",
        "review_frequency_days",
    ]
    return {
        f: {"limit": getattr(self, f).value, "source": getattr(self, f).source}
        for f in fields
        if hasattr(self, f)
    }

def hard_limits_dict(self) -> dict[str, float]:
    """Flat {field: value} for breach checking in concentration engine."""
    return {
        "single_manager_pct":    self.single_manager_pct.value,
        "single_investment_pct": self.single_investment_pct.value,
        "single_sector_pct":     self.single_sector_pct.value,
        "single_geography_pct":  self.single_geography_pct.value,
        "top3_names_pct":        self.top3_names_pct.value,
        "non_usd_unhedged_pct":  self.non_usd_unhedged_pct.value,
        "max_hard_lockup_pct":   self.max_hard_lockup_pct.value,
        "max_lockup_years":      self.max_lockup_years.value,
    }
```

#### Step 1.2 — Create governance_policy.yaml seed file (example, not schema)

**File:** `calibration/seeds/private_credit/governance_policy.yaml` (NEW — separate from calibration.yaml)

```yaml
# SEED DATA ONLY — loaded by migration 0007. Runtime config is in PostgreSQL.
# Example seed for Netz Private Credit Fund. Other funds will have different
# structures. All fields are optional. The JSONB is schema-free — any key/value
# pair can be added per fund via VerticalConfigOverride without migrations.
#
# Values should be bare scalars or lists of strings — NOT nested ThresholdEntry
# dicts (e.g., use `single_manager_pct: 35.0`, not `{value: 35.0, source: ...}`).
#
# MERGE BEHAVIOR: List fields (board_override_triggers, watchlist_triggers) are
# REPLACED by VerticalConfigOverride, not appended. To add a trigger, include
# ALL existing triggers plus the new one in the override.
#
# Sources: Investment Policy s.4, Credit Policy s.7.
# NOT in CLIENT_VISIBLE_TYPES — never exposed via client-facing API.

# Hard limits — Investment Policy s.4
single_manager_pct: 35.0
single_investment_pct: 35.0
non_usd_unhedged_pct: 20.0
min_commingled_pct: 35.0
max_hard_lockup_pct: 10.0
max_lockup_years: 2.0
min_quarterly_liquidity_pct: 20.0

# Concentration limits
single_sector_pct: 35.0
single_geography_pct: 40.0
top3_names_pct: 75.0

# Governance rules
board_override_triggers:
  - single_manager
  - single_investment
  - hard_lockup
  - non_usd_unhedged
watchlist_triggers:
  - covenant_breach
  - payment_delay
  - cashflow_deterioration
  - valuation_markdown
  - legal_regulatory_event
  - structural_change_underlying
ic_approval_required_above_pct: 35.0
review_frequency_days: 90

# Soft limits — Investment Policy s.5
max_leverage_underlying_pct: 300.0
min_manager_track_record_years: 2.0
min_manager_aum_usd: 100000000.0
max_manager_default_rate_pct: 10.0
```

#### Step 1.3 — Migration 0007: governance_policy as separate config_type (Option B)

**File:** `backend/app/core/db/migrations/versions/0007_governance_policy_seed.py`

Separate config_type = "governance_policy":
- ALTER CHECK constraints on BOTH tables to add `'governance_policy'`
- INSERT new row in `vertical_config_defaults`
- NOT in `CLIENT_VISIBLE_TYPES` — never exposed via API
- JSONB is opaque — no field validation in migration

```python
"""Seed governance_policy as separate config_type for private_credit.

Adds 'governance_policy' to CHECK constraints on both config tables,
then inserts a new row in vertical_config_defaults. This config_type
is NOT in CLIENT_VISIBLE_TYPES — never exposed via client-facing API.

The JSONB is schema-free. The seed below is an example for the Netz
Private Credit Fund. Other funds will have different structures via
VerticalConfigOverride. No field validation in migration.
"""

import json
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# ── CHECK constraint values (round 2: DRY constant) ──────────────
# V1 = 0005 state (includes macro_intelligence from 0005)
# V2 = 0007 state (adds governance_policy)
_CONFIG_TYPES_V2 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', "
    "'tone', 'evaluation', 'macro_intelligence', 'governance_policy'"
)
_CONFIG_TYPES_V1 = (
    "'calibration', 'scoring', 'blocks', 'chapters', "
    "'portfolio_profiles', 'prompts', 'model_routing', "
    "'tone', 'evaluation', 'macro_intelligence'"
)

# ── Seed data (flat JSONB, matches governance_policy.yaml) ────────
_GOVERNANCE_POLICY_SEED = {
    "single_manager_pct": 35.0,
    # ... (all 18 fields matching _DEFAULTS and YAML seed) ...
}

def upgrade() -> None:
    # ── 1. Expand CHECK constraints (DRY loop for both tables) ──
    for table, prefix in [
        ("vertical_config_defaults", "defaults"),
        ("vertical_config_overrides", "overrides"),
    ]:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{prefix}_config_type")
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT ck_{prefix}_config_type
            CHECK (config_type IN ({_CONFIG_TYPES_V2}))
        """)

    # ── 2. Insert governance_policy row (opaque JSONB) ──
    config_json = json.dumps(_GOVERNANCE_POLICY_SEED)
    op.get_bind().execute(
        sa.text("""
            INSERT INTO vertical_config_defaults
                (id, vertical, config_type, config, description, created_by)
            VALUES
                (gen_random_uuid(), 'private_credit', 'governance_policy',
                 :config, :description, 'migration:0007')
            ON CONFLICT (vertical, config_type) DO NOTHING
        """),
        {
            "config": config_json,
            "description": (
                "Investment Policy hard/soft limits and governance rules "
                "(IP-protected, not client-visible). Schema-free — "
                "structure varies per fund."
            ),
        },
    )

def downgrade() -> None:
    # ── 1. Delete governance_policy rows from BOTH tables ──
    # Must delete overrides FIRST (round 2: data-migration-expert)
    op.execute(sa.text(
        "DELETE FROM vertical_config_overrides "
        "WHERE config_type = 'governance_policy'"
    ))
    op.execute(sa.text(
        "DELETE FROM vertical_config_defaults "
        "WHERE vertical = 'private_credit' AND config_type = 'governance_policy'"
    ))
    # ── 2. Restore 0005-era CHECK constraints (V1) ──
    for table, prefix in [
        ("vertical_config_defaults", "defaults"),
        ("vertical_config_overrides", "overrides"),
    ]:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{prefix}_config_type")
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT ck_{prefix}_config_type
            CHECK (config_type IN ({_CONFIG_TYPES_V1}))
        """)
```

**Conventions** (from migration 0004/0005 pattern): sync ops, `sa.text()` with bind parameters, simple revision strings, DRY loop for both tables.

> **Round 2 critical fixes:**
>
> - **(data-migration-expert, pattern-recognition — CRITICAL):** CHECK constraint list must include `macro_intelligence` (added by migration 0005). Original plan omitted it, which would fail on any real database.
> - **(data-migration-expert):** Removed rowcount assertion. `ON CONFLICT DO NOTHING` + rowcount assertion is contradictory — matches 0004/0005 pattern of silent skip.
> - **(data-migration-expert):** Downgrade now deletes from `vertical_config_overrides` BEFORE restoring CHECK constraints. Without this, any org with a governance_policy override would block the downgrade.
> - **(Alembic-research):** Added `branch_labels = None; depends_on = None` for consistency with 0004/0005.
> - **(Alembic-research):** DRY loop for both tables eliminates duplication within the migration. `_CONFIG_TYPES_V1`/`V2` constants at top of file for readability.
> - **(Alembic-research):** `_GOVERNANCE_POLICY_SEED` defined as module-level constant (not inline dict) matching 0004's `_SEEDS` pattern.

**Idempotency:** ON CONFLICT DO NOTHING — safe for re-runs. No rowcount assertion.

**Transaction safety:** All ops (DROP, ADD, INSERT, DELETE) execute in a single Alembic transaction on PostgreSQL. If any statement fails, the entire migration rolls back atomically. ACCESS EXCLUSIVE lock on these small config tables (~10 rows) is sub-millisecond — no production impact. _(Alembic-research)_

#### Step 1.4 — Add _YAML_FALLBACK_MAP entry + resolver in config_service.py

**File:** `backend/app/core/config/config_service.py`

Add fallback entry:
```python
("private_credit", "governance_policy"): "calibration/seeds/private_credit/governance_policy.yaml",
```

`governance_policy` is NOT added to `CLIENT_VISIBLE_TYPES`. Any API route that lists/returns config will NOT expose governance_policy values to clients.

#### Step 1.5 — Add resolve_governance_policy() to policy_loader.py

**File:** `backend/ai_engine/governance/policy_loader.py`

The resolver reads the flat JSONB from ConfigService. With Option B (separate
config_type), the config dict IS the governance policy — no sub-key nesting.

For known fields, it wraps values in ThresholdEntry (audit trail for consumers).
The full JSONB is stored as `raw_policy` for LLM-based evaluation.
Unknown fields in the JSONB are preserved on the Pydantic model via extra="allow".

```python
def resolve_governance_policy(config: dict[str, Any] | None = None) -> PolicyThresholds:
    """Build PolicyThresholds from ConfigService JSONB or _DEFAULTS.

    The config dict is the flat governance_policy JSONB from ConfigService.
    Known fields are wrapped in ThresholdEntry for consumer audit trail.
    The full dict is stored as raw_policy for LLM-based policy evaluation.
    Unknown fields are accepted via Pydantic extra="allow".

    Precedence chain (documented per spec-flow-analyzer round 2):
      ConfigService override > ConfigService default > Search extraction > _DEFAULTS
    """
    if config is None:           # round 2 fix: `is None` not `not config`
        return PolicyThresholds()

    # Build overrides dict, construct once (round 2: kieran-python, best-practices)
    overrides: dict[str, Any] = {"raw_policy": config}

    for field_name, default in _DEFAULTS.items():
        val = config.get(field_name)
        if val is None:
            continue
        try:
            if isinstance(val, bool):
                raise TypeError(f"boolean not accepted for {field_name}")
            # Validate list elements are strings (round 2: security-sentinel)
            if isinstance(val, list):
                coerced = [x for x in val if isinstance(x, str)]
            else:
                coerced = float(val)
            overrides[field_name] = ThresholdEntry(
                value=coerced,
                source="ConfigService",
                rationale=default["rationale"],
            )
        except (KeyError, TypeError, ValueError) as e:   # KeyError added (round 2: pattern-recognition)
            logger.error("POLICY_RESOLVE_BAD_VALUE",
                         extra={"field": field_name, "value": val, "error": str(e)})

    return PolicyThresholds(**overrides)
```

> **Round 2 review findings incorporated:**
>
> - **(kieran-python-reviewer):** `if config is None:` instead of `if not config:` — empty dict `{}` is falsy, would skip `raw_policy` assignment.
> - **(kieran-python-reviewer, best-practices-researcher):** Build overrides dict, construct `PolicyThresholds(**overrides)` once — idiomatic Pydantic v2 pattern, avoids post-construction `setattr`.
> - **(security-sentinel):** Validate list-type field elements are strings — unhashable dicts in `board_override_triggers` would crash `_check_board_override()`.
> - **(pattern-recognition):** Add `KeyError` to except clause — all 6 existing `quant_engine/` resolvers catch it for defensive consistency.
> - **(spec-flow-analyzer):** Document the precedence chain in docstring.

**Design decisions (updated 2026-03-16):**

| Question | Decision | Rationale |
|---|---|---|
| Config format? | **Flat JSONB, schema-free** | Any fund can have any structure. Seeds are examples. |
| ThresholdEntry? | **Preserved for known fields** | Audit trail (.value, .source) required by concentration_engine + deep_review/policy |
| Unknown fields? | **Accepted via extra="allow"** | Fund-specific IPS fields stored without migration |
| Raw policy dict? | **Stored as raw_policy** | LLM compliance evaluation reads full policy, not just mapped fields |
| Return type? | **Pydantic BaseModel** | extra="allow" + ThresholdEntry audit + model_dump() |

#### Step 1.6 — Wire resolve into load_policy_thresholds()

**File:** `backend/ai_engine/governance/policy_loader.py`

Unchanged from original plan — add `config: dict[str, Any] | None = None` parameter,
bypass cache when config provided, use `resolve_governance_policy(config)` for initial
thresholds. Search/LLM overlay still runs on top.

```python
def load_policy_thresholds(
    *, force_reload: bool = False, config: dict[str, Any] | None = None,
) -> PolicyThresholds:
    # ... (same as original plan — cache bypass, resolve, Search/LLM overlay)
    # Only cache when config is None
    if config is None:
        _cache = thresholds
    return thresholds
```

> **Cache bypass rationale (performance-oracle):** ConfigService has its own TTLCache (60s).
> Module-level cache (3600s) is only for config=None fallback path (Azure Search + LLM).

**Tenant-keyed cache (round 2: performance-oracle — add in this PR):**

Without tenant-keyed caching, Sprint 3's ConfigService wiring causes 3 calls to
`load_policy_thresholds(config=X)` per deep review (lines 329, 1372, 1486), each
bypassing the module-level cache and re-running the full Search/LLM overlay (5-15s).
Total: 15-45s wasted per review.

```python
_tenant_cache: dict[str, tuple[float, PolicyThresholds]] = {}
_TENANT_CACHE_TTL = 300  # 5 minutes

def load_policy_thresholds(
    *, force_reload: bool = False, config: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> PolicyThresholds:
    global _cache

    # Path 1: No config — existing global cache (backward compat)
    if config is None and not force_reload and _cache is not None:
        if time.time() - _cache.loaded_at < _CACHE_TTL_SECONDS:
            return _cache

    # Path 2: Config provided — tenant-keyed cache
    if config is not None and org_id and not force_reload:
        cached = _tenant_cache.get(org_id)
        if cached and (time.time() - cached[0]) < _TENANT_CACHE_TTL:
            return cached[1]

    thresholds = resolve_governance_policy(config)
    # ... Search/LLM overlay ...

    # Cache by path
    if config is None:
        _cache = thresholds
    elif org_id:
        _tenant_cache[org_id] = (time.time(), thresholds)
    return thresholds

def invalidate_cache() -> None:
    global _cache
    _cache = None
    _tenant_cache.clear()
```

Memory: ~2-4 KB per tenant. 100 tenants = 200-400 KB. ConfigService TTLCache (60s) handles
DB query caching upstream. The 300s tenant cache collapses the 3× Search/LLM redundancy.

#### Step 1.7 — Add TODO comments at caller sites (defer wiring)

**No behavioral changes to any caller.** Same as original plan — 3 TODO comments
at `deep_review/service.py` lines 329, 1372, 1486. Wiring deferred to Sprint 3
async migration.

#### Step 1.8 — Tests

**New test file:** `backend/tests/test_governance_policy_config.py`

```python
# 1. resolve_governance_policy(None) returns PolicyThresholds with _DEFAULTS
# 2. resolve_governance_policy(valid_config) returns ConfigService values
#    + raw_policy stores full dict
# 3. resolve_governance_policy(partial_config) merges config + _DEFAULTS per field
# 4. resolve_governance_policy(bad_value + bool) logs error, falls back per field
# 5. resolve_governance_policy(config_with_unknown_fields) preserves extra fields
#    on raw_policy (schema-free contract)
# 6. load_policy_thresholds(config=X) bypasses module-level cache (tenant isolation)
# 7. YAML seed values match _DEFAULTS values exactly (regression guard)
# 8. PolicyThresholds.to_dict() / summary() / hard_limits_dict() work with Pydantic
```

#### Step 1.9 — Verification

```bash
make check  # lint + typecheck + tests + import-linter
make migrate  # verify migration applies cleanly
```

---

### PR 2: Deprecation markers + boundary documentation

**Branch:** `refactor/ai-engine-boundary-docs`

#### Step 2.1 — extraction_orchestrator.py deprecation docstring

**File:** `backend/ai_engine/extraction/extraction_orchestrator.py`

Replace module docstring with comprehensive deprecation notice:

```python
"""Extraction Orchestrator — DEPRECATED.

This module is the legacy batch pipeline tied to the pre-ADLS Azure Blob
Storage model. It will be DELETED when legacy Azure resources are replaced
by ADLS Gen2.

Legacy model (this file):
    Azure Blob containers → download → process → Azure Blob → Search Indexer (pull)

New model (unified_pipeline.py):
    bronze/{org_id}/credit/documents/ → unified_pipeline
        → silver/{org_id}/credit/chunks/ → Azure Search upsert (push)

SOURCE_CONFIG below maps to legacy Azure Blob containers and Search indexers.
These will cease to exist when the new Azure Resource Group is provisioned.

Migration path:
    - Per-document ingestion: ai_engine.pipeline.unified_pipeline.process()
    - Batch orchestration: ai_engine.ingestion.pipeline_ingest_runner
    - Storage routing: ai_engine.pipeline.storage_routing

Do NOT simplify or refactor this file. It will be deleted entirely.
"""
```

> **Review finding (code-simplicity-reviewer):** Removed `warnings.warn` from entry point. For an internal codebase with a single team, a docstring saying "DEPRECATED" plus grep-able text is sufficient. `warnings.warn` adds runtime overhead, requires test coverage, and nobody is running with `-W error` in CI. The module will be deleted, not gradually phased out.

#### Step 2.2 — extraction/**init**.py classification docstring

**File:** `backend/ai_engine/extraction/__init__.py`

```python
"""AI Engine Extraction — document processing components.

This package contains two categories of modules:

**Pipeline stage components** (called by unified_pipeline.py):
    skip_filter          — pre-filter compliance forms before OCR
    mistral_ocr          — Mistral API OCR provider
    governance_detector  — governance-critical flag detection
    semantic_chunker     — section-aware chunking with breadcrumbs
    document_intelligence — LLM metadata extraction + summarization
    embed_chunks         — OpenAI embedding batch
    search_upsert_service — Azure Search dual-write upsert

**Autonomous utilities** (independent callers):
    entity_bootstrap     — fund context extraction via LLM
    fund_data_bootstrap  — fund governance document bootstrap
    market_data_bootstrap — market/research data bootstrap
    deals_enrichment     — deal chunk LLM enrichment
    fund_data_enrichment — fund chunk LLM enrichment
    obligation_extractor — obligation register parsing
    kb_schema            — Azure Search schema definitions
    azure_kb_adapter     — Azure Search query adapter
    text_extraction      — PDF/DOCX text extraction wrapper
    embedding_service    — OpenAI embedding client wrapper

**Deprecated:**
    extraction_orchestrator — legacy Azure Blob model (see its docstring)
"""
```

#### Step 2.3 — ingestion/**init**.py role docstring

**File:** `backend/ai_engine/ingestion/__init__.py`

```python
"""AI Engine Ingestion — batch orchestration and document discovery.

Modules:
    pipeline_ingest_runner — canonical batch orchestrator
        5-stage lifecycle: scan → discover deals → entity bootstrap
        → bridge registry → deep review. Creates PipelineIngestJob audit trail.
    document_scanner       — blob inventory → DocumentRegistry rows
    registry_bridge        — DocumentRegistry → DealDocument mapping (idempotent)
    monitoring             — daily cycle: classification + obligation extraction + alerts
"""
```

#### Step 2.4 — Verification

```bash
make check  # lint + typecheck + tests + import-linter
```

---

### PR 3: Minor **init**.py docstring cleanups

**Branch:** `refactor/ai-engine-init-docstrings`

#### Step 3.1 — Audit and update ai_engine sub-package **init**.py files

Check each `__init__.py` in `ai_engine/` sub-packages. Add or improve docstrings where missing or insufficient:

| Package                                | Current docstring                                          | Action                                                                                                                                                                                                                    |
| -------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ai_engine/extraction/__init__.py`     | Updated in PR 2                                            | Skip                                                                                                                                                                                                                      |
| `ai_engine/ingestion/__init__.py`      | Updated in PR 2                                            | Skip                                                                                                                                                                                                                      |
| `ai_engine/pipeline/__init__.py`       | ✅ Has docstring + exports (IngestRequest, process, etc.)  | Keep existing — already has good docstring with exports                                                                                                                                                                   |
| `ai_engine/classification/__init__.py` | ✅ Has docstring + exports (classify)                       | Keep existing — already documents hybrid three-layer pipeline                                                                                                                                                              |
| `ai_engine/validation/__init__.py`     | Minimal one-liner                                          | **Replace:** Add 10-module inventory with dead code audit results. All modules ACTIVE. Tech debt: stdlib logging → structlog (low priority). Dead code: 6 guard functions in `vector_integrity_guard.py` (~200 LOC).     |
| `ai_engine/knowledge/__init__.py`      | Minimal one-liner                                          | **Replace:** Add tech debt notice: knowledge_builder.py, knowledge_anchor_extractor.py, and linker.py use sqlalchemy.orm.Session (sync, legacy). Migrate to session injection in Sprint 3.                                |
| `ai_engine/governance/__init__.py`     | Minimal one-liner                                          | **Replace:** Add module inventory: policy loading, evidence throttle, output safety, token budget                                                                                                                         |
| `ai_engine/prompts/__init__.py`        | ✅ Has docstring + exports (PromptRegistry, etc.)          | Keep existing — already documents Jinja2 template engine with exports                                                                                                                                                     |
| `ai_engine/portfolio/__init__.py`      | Minimal one-liner                                          | **Replace:** Add module description: concentration engine                                                                                                                                                                 |

**Docstring content for knowledge/**init**.py:**

```python
"""AI Engine Knowledge — knowledge graph construction and entity linking.

Modules:
    knowledge_builder         — builds ManagerProfile entities from document corpus
    knowledge_anchor_extractor — extracts knowledge anchors from classified documents
    linker                    — links knowledge entities across documents

Tech debt: All 3 modules use sqlalchemy.orm.Session (sync, legacy pattern).
Migrate to session injection in Sprint 3 alongside general ai_engine
async migration. See CLAUDE.md: "async migration safety net" section.
"""
```

**Docstring content for validation/**init**.py:**

> **Dead code audit (2026-03-15):** All 10 modules are ACTIVE with production callers.
> `deep_review_comparator`, `deep_review_validation_runner`, and `delta_metrics` are
> NOT dead — they serve the `/pipeline/deep-review/validate` and `/evaluate` API routes.
> Only dead code: 6 guard functions in `vector_integrity_guard.py` (~200 LOC) — constants
> (`EMBEDDING_MODEL_NAME`, `EMBEDDING_DIMENSIONS`) are actively imported by
> `openai_client.py`, `unified_pipeline.py`, and `search_rebuild.py`.

```python
"""AI Engine Validation — 4-layer evaluation framework for IC memo quality.

Modules:
    eval_runner                    — end-to-end IC memo evaluation harness
                                     (entry point: run_ic_memo_eval)
    eval_metrics                   — Layers 1-3: decision integrity, retrieval, grounding
    eval_judge                     — Layer 4: LLM judge for coherence/consistency/tone
    validation_schema              — Pydantic schemas for eval framework + delta reports
    citation_formatter             — citation normalization for RAG (global_agent)
    evidence_quality               — evidence coverage + confidence scoring (global_agent)
    vector_integrity_guard         — EMBEDDING_MODEL_NAME/EMBEDDING_DIMENSIONS constants
                                     (guard functions are dead — delete or integrate)
    deep_review_comparator         — V3-vs-V4 deterministic delta computation
    deep_review_validation_runner  — V3-vs-V4 benchmark harness
                                     (entry point: run_deep_review_validation_sample)
    delta_metrics                  — engine quality scoring from delta reports

Tech debt:
    - All modules use stdlib logging instead of structlog (low priority).
    - vector_integrity_guard: 6 guard functions never called (~200 LOC dead).
      Constants are active. Delete guard functions or integrate into app startup.
"""
```

#### Step 3.2 — Verification

```bash
make check  # lint + typecheck + tests + import-linter
```

---

## Acceptance Criteria

### PR 1

**Schema-free architecture:**
- [x] `PolicyThresholds` is a Pydantic `BaseModel` with `ConfigDict(extra="allow")`
- [x] `ThresholdEntry` is a Pydantic `BaseModel` with `value: float | list[str]` (not `Any`)
- [x] All 18 fields use `Field(default_factory=lambda: ThresholdEntry(...))`
- [x] Known fields typed as `ThresholdEntry` — `.value`/`.source` access preserved
- [x] Unknown fields accepted without error via `extra="allow"`
- [x] `raw_policy: dict[str, Any]` stores full JSONB for LLM evaluation
- [x] `to_dict()` uses `model_dump()`, `summary()` uses `model_fields`

**Option B — separate config_type:**
- [x] `calibration/seeds/private_credit/governance_policy.yaml` exists (separate file)
- [x] YAML header documents: "example seed, schema-free, all fields optional"
- [x] YAML header documents: list fields (triggers) are REPLACED, not merged, by overrides
- [x] Migration `0007` CHECK constraint includes ALL 11 values (including `macro_intelligence` from 0005)
- [x] Migration `0007` uses DRY loop for both tables
- [x] Migration `0007` INSERTs with ON CONFLICT DO NOTHING (no rowcount assertion)
- [x] Migration `0007` downgrade DELETEs from BOTH tables (overrides + defaults)
- [x] Migration `0007` has `branch_labels = None; depends_on = None`
- [x] `governance_policy` NOT in `CLIENT_VISIBLE_TYPES`
- [x] `_YAML_FALLBACK_MAP` has `("private_credit", "governance_policy")` entry

**Resolver + cache:**
- [x] `resolve_governance_policy` uses `if config is None:` guard (not `if not config:`)
- [x] Resolver builds overrides dict, constructs `PolicyThresholds(**overrides)` once
- [x] Resolver validates list elements are strings: `[x for x in val if isinstance(x, str)]`
- [x] Resolver catches `(KeyError, TypeError, ValueError)` — includes `KeyError`
- [x] Resolver handles `float(True)` by rejecting booleans explicitly
- [x] `load_policy_thresholds(config=None)` behavior identical to today (regression test)
- [x] `load_policy_thresholds(config=X)` bypasses module-level cache (tenant isolation)
- [x] `load_policy_thresholds(config=X, org_id=Y)` uses tenant-keyed cache (TTL 300s)
- [x] `invalidate_cache()` clears both `_cache` and `_tenant_cache`
- [x] `SEARCH_ENDPOINT` and `SEARCH_API_KEY` still exported from `policy_loader.py`

**Callers + tests:**
- [x] `deep_review/service.py` has TODO comments at all 3 call sites for Sprint 3
- [x] All existing consumers (`concentration_engine.py`, `deep_review/policy.py`) work unchanged
- [x] YAML ↔ `_DEFAULTS` parity test passes
- [x] Schema-free test: unknown fields preserved on `raw_policy`
- [x] `make check` passes (lint + typecheck + tests + import-linter)

### PR 2

- [x] `extraction_orchestrator.py` has deprecation docstring (no `warnings.warn`)
- [x] `extraction/__init__.py` classifies stage components vs autonomous utilities
- [x] `ingestion/__init__.py` documents batch orchestration role
- [x] `make check` passes

### PR 3

- [x] All `ai_engine/` sub-package `__init__.py` files have descriptive docstrings
- [x] `make check` passes

## System-Wide Impact

**Interaction graph:** `resolve_governance_policy()` is called by `load_policy_thresholds()`, which is called by `deep_review/service.py` (3 call sites), `deep_review/policy.py` (1 path), and `concentration_engine.py` (1 path). No new ConfigService calls in this PR — all callers remain at `config=None` (deferred to Sprint 3 async migration).

**Data model change:** `PolicyThresholds` migrates from `dataclass` to Pydantic `BaseModel(extra="allow")`. `ThresholdEntry` also becomes Pydantic. Consumer access pattern (`policy.field.value`, `policy.field.source`) is preserved. `to_dict()` migrates from `asdict()` to `model_dump()`. `summary()` migrates from `__dataclass_fields__` to `model_fields`.

**Schema-free philosophy:** All `calibration/` seeds (including existing calibration.yaml, scoring.yaml, blocks.yaml, limits.yaml) are examples for the Netz Private Credit Fund — not canonical schemas. Any fund can have any structure via `VerticalConfigOverride`. No future migrations needed for new policy fields.

**Error propagation:** `resolve_governance_policy` catches `TypeError`/`ValueError` per known field and falls back to `_DEFAULTS`. Unknown fields from JSONB pass through without validation. No new exception types propagate to callers.

**State lifecycle risks:** Migration 0007 is an INSERT of a new row (not UPDATE). Downgrade DELETEs the row and restores CHECK constraints. No orphaned state.

**API surface parity:** No API changes. `governance_policy` is NOT in `CLIENT_VISIBLE_TYPES` — invisible to client-facing API. No new endpoints.

**Tenant isolation:** Cache bypassed when config is provided — prevents cross-tenant threshold leakage. ConfigService has its own RLS + TTLCache for upstream caching. `VerticalConfigOverride` allows per-org governance policies with full tenant isolation via RLS.

> **Review finding (learnings-researcher):** Phase 3 StorageClient pattern confirms extraction_orchestrator routes through unified_pipeline.process() which enforces ADLS-before-Search ordering. RLS subselect pattern is already correctly applied in ConfigService queries — no action needed.

## Dependencies & Risks

| Risk                                               | Mitigation                                                                         | Source |
| -------------------------------------------------- | ---------------------------------------------------------------------------------- | ------ |
| YAML seed ↔ DB seed divergence                     | Blocking CI test comparing YAML values vs \_DEFAULTS values                        | round 1 |
| Sync callers can't access ConfigService            | They keep config=None fallback — identical to today                                | round 1 |
| deep_review/service.py SEARCH imports break        | SEARCH_ENDPOINT/SEARCH_API_KEY preserved as module-level exports                   | round 1 |
| Migration 0007 runs on DB without 0004 tables      | ON CONFLICT DO NOTHING — silent skip if pre-exists                                 | round 2: data-migration |
| Cache returns wrong tenant's thresholds            | Cache bypassed when config is provided; only caches config=None path               | round 1 |
| governance_policy exposed via CLIENT_VISIBLE_TYPES | **Resolved:** Option B — separate config_type, NOT in CLIENT_VISIBLE_TYPES         | round 1 |
| float(True) → silent 1.0                           | Explicit isinstance(val, bool) guard before float()                                | round 1 |
| PolicyThresholds dataclass → Pydantic breaks callers | **Verified:** `.value`/`.source` preserved. `Field(default_factory=...)` pattern    | round 2: best-practices |
| Unknown JSONB fields cause validation errors       | Pydantic `extra="allow"` accepts any field. `raw_policy` stores full dict          | round 1 |
| CHECK constraint ALTER fails on existing data      | DROP + re-ADD safe — sub-ms ACCESS EXCLUSIVE lock on small tables                  | round 2: Alembic-research |
| **CHECK constraint drops `macro_intelligence`**    | **FIXED:** Include all 11 values in constraint (0005 added `macro_intelligence`)   | round 2: CRITICAL |
| **ON CONFLICT + rowcount contradiction**           | **FIXED:** Removed rowcount assertion — matches 0004/0005 pattern                  | round 2: data-migration |
| **Downgrade leaves orphaned overrides**            | **FIXED:** Downgrade DELETEs from both overrides + defaults tables                 | round 2: data-migration |
| **`if not config:` catches empty dict**            | **FIXED:** `if config is None:` guard                                              | round 2: kieran-python |
| **List fields with non-string elements**           | **FIXED:** `[x for x in val if isinstance(x, str)]` validation in resolver        | round 2: security |
| raw_policy prompt injection via JSONB              | Future risk — add sanitizer before wiring into LLM prompts (Sprint 3)              | round 2: security |
| Sprint 3: 3x redundant Search/LLM per deep review | TODO: Add tenant-keyed cache (`_tenant_cache` keyed by org_id, TTL 300s)           | round 2: performance |
| `_apply_extracted` has no bool guard               | TODO: Add `isinstance(val, bool)` guard for consistency with resolver              | round 2: spec-flow |
| RLS missing WITH CHECK on overrides table          | Pre-existing (0004). Add explicit `WITH CHECK` in future migration                 | round 2: security |

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-ai-engine-extraction-ingestion-cleanup-brainstorm.md](docs/brainstorms/2026-03-15-ai-engine-extraction-ingestion-cleanup-brainstorm.md)
  - Key decisions: no file moves (Decision 1), deprecate don't simplify orchestrator (Decision 3), ConfigService migration via resolve pattern (Decision 4), what NOT to migrate (Decision 5)

### Internal References

- ConfigService: `backend/app/core/config/config_service.py` — cascade: TTLCache → DB override → DB default → YAML fallback
- ConfigService models: `backend/app/core/config/models.py` — `VerticalConfigDefault`, `VerticalConfigOverride`
- CLIENT_VISIBLE_TYPES: `backend/app/core/config/config_service.py:63-65` — `frozenset({"calibration", "scoring", "blocks", "portfolio_profiles"})`
- Reference pattern: `backend/quant_engine/regime_service.py:89-112` — `resolve_regime_thresholds(config: dict | None)`
- policy_loader.py: `backend/ai_engine/governance/policy_loader.py` — `_DEFAULTS`, `PolicyThresholds`, `load_policy_thresholds()`
- Migration pattern: `backend/app/core/db/migrations/versions/0004_vertical_configs.py` — parameterized SQL with bind parameters
- YAML fallback map: `backend/app/core/config/config_service.py:40-50` — `("private_credit", "calibration")` already mapped
- Callers: `backend/ai_engine/portfolio/concentration_engine.py:17`, `backend/vertical_engines/credit/deep_review/service.py:329,1372,1486`, `backend/vertical_engines/credit/deep_review/policy.py:176`

### Institutional Learnings

- Dead code audit (`docs/solutions/architecture-patterns/dead-code-audit-ai-engine-legacy-cleanup-20260315.md`): grep ALL callers, don't rely on documentation. Lazy imports hide ImportError from tests.
- Alembic FK/RLS patterns (`docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md`): migration conventions, parameterized SQL, phased operations.
- Phase 3 StorageClient (`docs/solutions/architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md`): ADLS-before-Search dual-write ordering. Extraction_orchestrator bypasses this — another reason to deprecate it.
- RLS subselect (`docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md`): ConfigService override queries use RLS — subselect pattern already applied.
- Wave 2 modularization (`docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md`): Deletion over deprecation principle — extraction_orchestrator will be deleted when ADLS infra is provisioned, not gradually phased out.

### Review Agent Findings Summary

| Agent                    | Key Finding                                                  | Action Taken                                        |
| ------------------------ | ------------------------------------------------------------ | --------------------------------------------------- |
| data-migration-expert    | SQL injection via f-string; silent no-op if row missing      | Parameterized query + rowcount assertion             |
| performance-oracle       | Cache ignores config param — tenant isolation bug            | Bypass cache when config provided                    |
| security-sentinel        | governance_policy inside CLIENT_VISIBLE calibration type     | **Resolved:** Option B — separate config_type        |
| kieran-python-reviewer   | float(bool) silent coercion; dict type hint too loose        | bool guard + dict[str, Any]                          |
| code-simplicity-reviewer | Scalar/list split unnecessary; warnings.warn YAGNI           | Single loop; docstring-only deprecation              |
| architecture-strategist  | Pattern consistent with quant_engine; DAG compliant          | Confirmed; schema-free extension aligned             |
| learnings-researcher     | Phase 3 dual-write, RLS subselect, Wave 2 deletion principle | Incorporated into learnings section                  |

### Architectural Decision Record (2026-03-16)

**Decision:** Schema-free calibration + Option B (separate config_type for governance_policy)

**Context:** The original plan assumed calibration configs have fixed schemas with predefined
fields. In practice, each fund has a unique Investment Policy Statement (IPS) with different
structures. Netz Private Credit Fund has specific concentration limits, but a real estate debt
fund might have LTV limits, and a venture debt fund might have revenue-milestone triggers.

**Consequences:**
1. `PolicyThresholds` dataclass → Pydantic `BaseModel(extra="allow")`
2. `ThresholdEntry` dataclass → Pydantic `BaseModel` with `value: float | list[str]` (not `Any`)
3. All `calibration/` YAML seeds are examples, not canonical schemas
4. `resolve_governance_policy()` reads flat JSONB, stores full dict as `raw_policy`
5. `VerticalConfigOverride` accepts any JSONB per org_id — no schema enforcement
6. LLM-based policy evaluation receives `raw_policy` as opaque context
7. No future migrations needed for new policy fields — JSONB handles extensibility

**Round 2 refinements:**
8. First `extra="allow"` model in codebase — sets precedent for schema-free config objects _(pattern-recognition)_
9. `guardrails` column on `VerticalConfigDefault` exists but is not populated — add in Sprint 3 when admin write API ships _(architecture-strategist)_
10. List fields (`board_override_triggers`, `watchlist_triggers`) are REPLACED by deep_merge, not appended — document in YAML seed _(architecture-strategist, spec-flow-analyzer)_
11. Consider plausibility bounds for known numeric fields (e.g., single_manager_pct: 0-100) similar to `quant_engine/regime_service.py`'s `_PLAUSIBILITY` dict — prevents admin typos _(architecture-strategist)_
12. Search/LLM overlay still runs when config is provided. When ConfigService provides all 18 fields, the overlay executes but `_apply_extracted` skips every field (source != "DEFAULT"). Sprint 3 optimization: short-circuit overlay when all known fields have non-DEFAULT sources _(spec-flow-analyzer, performance-oracle)_

**Simplicity trade-off (code-simplicity-reviewer):** `extra="allow"` is never exercised by the
resolver — unknowns go to `raw_policy` dict, not Pydantic extra attributes. The user's
architectural decision to keep `extra="allow"` is for forward compatibility: future code may
construct `PolicyThresholds(**config)` directly for fund types where all fields are dynamic.
The `raw_policy` dict serves a different purpose — opaque LLM context.
