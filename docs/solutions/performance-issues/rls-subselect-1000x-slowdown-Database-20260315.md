---
module: Database
date: 2026-03-15
problem_type: performance_issue
component: database
symptoms:
  - "RLS-enabled queries 1000x slower on large tables (100k+ rows)"
  - "PostgreSQL EXPLAIN shows per-row function evaluation of current_setting()"
  - "Query time scales linearly with table size instead of being constant"
root_cause: missing_index
resolution_type: code_fix
severity: critical
tags: [rls, postgresql, current-setting, subselect, multi-tenant, performance, row-level-security]
---

# Troubleshooting: RLS current_setting() Without Subselect — 1000x Query Slowdown

## Problem

PostgreSQL Row-Level Security (RLS) policies using bare `current_setting('app.current_organization_id')` cause the function to be evaluated **per-row** instead of once per query. On a table with 100k rows, this means 100k function calls per query — a 1000x performance degradation compared to the correct subselect pattern.

## Environment

- Module: Database (RLS policies across all tenant-scoped tables)
- PostgreSQL: 16 + TimescaleDB
- Affected Component: All 55+ RLS policies on tenant-scoped tables
- Date: 2026-03-15
- PRs: #1 (Sprint 2b), #2 (Sprint 3)
- Migrations: `0001_foundation.py`, `0003_credit_domain.py`, `0004_vertical_configs.py`

## Symptoms

- RLS-enabled queries become progressively slower as table size grows
- `EXPLAIN ANALYZE` shows `Filter: (organization_id = current_setting(...)` with per-row evaluation
- Query time on 100k-row table: ~2-5 seconds (should be <50ms with proper index scan)
- CPU spikes during simple SELECT queries on large tenant-scoped tables

## What Didn't Work

**Direct solution:** This was identified during architecture research (March 14, 2026) and implemented correctly from the start. The pattern was documented as a CLAUDE.md critical rule to prevent regression. This doc exists to explain **why** the subselect matters, since the failure mode is non-obvious.

## Solution

**WRONG pattern (bare function call — per-row evaluation):**

```sql
CREATE POLICY org_isolation ON some_table
  USING (organization_id = current_setting('app.current_organization_id')::uuid)
  WITH CHECK (organization_id = current_setting('app.current_organization_id')::uuid);
```

**CORRECT pattern (subselect wrapper — evaluates once):**

```sql
CREATE POLICY org_isolation ON some_table
  USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
  WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));
```

**Implementation in migration 0003:**

```python
# 0003_credit_domain.py:988-995
_RLS_TABLES = [
    "audit_events", "funds_universe", "nav_timeseries",  # from 0001/0002
    "deals", "pipeline_deals", "documents",               # from 0003
    # ... 55+ tables total
]

for t in _RLS_TABLES:
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY org_isolation ON {t} "
        f"USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid)) "
        f"WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))"
    )
```

**Companion: SET LOCAL for connection pool safety:**

```python
# backend/app/core/tenancy/middleware.py:42-47
async with async_session_factory() as session, session.begin():
    if actor.organization_id is not None:
        await session.execute(
            text("SET LOCAL app.current_organization_id = :oid"),
            {"oid": str(actor.organization_id)},
        )
    yield session
```

## Why This Works

1. **Root cause — PostgreSQL optimizer behavior:**
   - Bare `current_setting()` is marked as `VOLATILE` in PostgreSQL's function catalog
   - The optimizer treats volatile functions as potentially returning different values per row
   - Therefore it evaluates the USING clause **for every row** in the table
   - For 100k rows: 100k × (`current_setting()` call + `::uuid` cast + comparison) = seconds

2. **Why the subselect fixes it:**
   - `(SELECT current_setting(...))` is a **scalar subquery**
   - PostgreSQL recognizes it has no table dependencies (no correlation to outer query)
   - The optimizer evaluates it **exactly once** before scanning the table
   - The constant UUID value is then used as a filter predicate
   - With a btree index on `organization_id`, this becomes an index scan: O(log n) not O(n)

3. **SET LOCAL vs SET:**
   - `SET LOCAL` scopes the variable to the current **transaction** — safe for connection pooling
   - Plain `SET` persists across the connection lifetime — if the connection returns to the pool, the next request inherits the previous tenant's context (data leak)
   - Comment in `middleware.py:11-12`: "The subselect wrapper is CRITICAL for performance — without it, current_setting() evaluates per-row instead of once per query (1000x slower on large tables)."

## Prevention

- **CLAUDE.md critical rule:** "RLS subselect: All RLS policies must use `(SELECT current_setting(...))` not bare `current_setting()`. Without subselect, per-row evaluation causes 1000x slowdown."
- **Migration 0004 comment (line 164):** `# MUST use subselect pattern — see CLAUDE.md "RLS subselect" rule`
- **Review checklist:** Every PR that adds or modifies RLS policies must verify the `(SELECT ...)` wrapper is present.
- **Automated guard:** A `pygrep` pre-commit hook can block bare `current_setting()` in migration files:
  ```yaml
  - id: rls-subselect
    name: RLS must use subselect
    entry: 'current_setting\([^)]+\)(?!\))'  # Matches bare call without outer parens
    language: pygrep
    files: 'migrations/.*\.py$'
  ```
- **Test:** Query `pg_policies` and verify every policy's `qual` column contains `SubPlan` (subquery indicator).

## Related Issues

- See also: [Alembic Monorepo Migration](../database-issues/alembic-monorepo-migration-fk-rls-ordering.md) — first documentation of this pattern, includes RLS test examples
- See also: [Vertical Engine Extraction Patterns](../architecture-patterns/vertical-engine-extraction-patterns.md) — global tables (no RLS) vs tenant-scoped tables
