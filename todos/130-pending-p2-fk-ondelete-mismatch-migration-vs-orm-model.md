---
status: pending
priority: p2
issue_id: 130
tags: [code-review, database]
---

# Problem Statement

Migration 0013 creates a foreign key constraint without an `ondelete` clause, defaulting to `NO ACTION` at the database level. The corresponding ORM model declares `ondelete="RESTRICT"`. While `NO ACTION` and `RESTRICT` are functionally similar in most cases, the divergence means database DDL and ORM intent are out of sync, which can cause subtle behavioral differences and makes the schema misleading to future engineers.

# Findings

- `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` line 30 creates the FK with no `ondelete` clause → database enforces `NO ACTION`.
- `backend/app/domains/wealth/models/benchmark_nav.py` line 23 declares `ondelete="RESTRICT"` in the ORM relationship/column definition.
- `NO ACTION` defers constraint checking to the end of the statement in some PostgreSQL contexts; `RESTRICT` checks immediately. The difference can surface in multi-row delete operations or deferred constraint scenarios.
- The mismatch will also cause Alembic autogenerate to emit spurious migration diffs, polluting future `alembic revision --autogenerate` output.

# Proposed Solutions

Add `ondelete="RESTRICT"` to the FK definition in the migration to match the ORM model:

```python
sa.ForeignKeyConstraint(
    ["allocation_block_id"],
    ["allocation_blocks.id"],
    ondelete="RESTRICT",   # add this
),
```

If `CASCADE` or `SET NULL` is the actual intended behavior, update both the migration and the ORM model to match. The key requirement is that migration DDL and ORM declaration agree.

# Technical Details

- **Files:**
  - `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` line 30
  - `backend/app/domains/wealth/models/benchmark_nav.py` line 23
- **Behavioral difference:** `RESTRICT` prevents delete if referencing rows exist, checked immediately. `NO ACTION` does the same but deferred to end-of-statement (PostgreSQL default behavior is identical in practice for most cases, but semantics differ for deferred constraints).
- **Autogenerate impact:** Alembic will flag this diff in every subsequent `--autogenerate` run until fixed.
- **Source:** data-integrity-guardian
