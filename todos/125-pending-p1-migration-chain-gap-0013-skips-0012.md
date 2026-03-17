---
status: pending
priority: p1
issue_id: 125
tags: [code-review, database, migration]
---

# Problem Statement

Migration 0013 declares `down_revision = "0011"` but migration 0012 already exists with `down_revision = "0010"`, creating parallel branches in the Alembic revision chain. Running `alembic upgrade head` will fail with "multiple heads detected" error in environments where both 0012 and 0013 exist.

# Findings

- `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` line 19 sets `down_revision = "0011"`.
- Migration 0012 exists and is a child of 0011 (its `down_revision = "0010"`).
- This creates a fork: both 0012 and 0013 claim 0011 as their parent, producing two heads.
- Alembic requires a linear chain (or explicit merge migration) to run `upgrade head`.
- Any environment that applied 0012 before 0013 was added will fail on the next `alembic upgrade head`.

# Proposed Solutions

Change `down_revision` in `0013_benchmark_nav.py` from `"0011"` to `"0012"` to restore a linear chain:

```
0010 → 0011 → 0012 → 0013 → 0014
```

If 0012 and 0013 are genuinely independent branches, create a merge migration with:
```bash
alembic merge 0012 0013 -m "merge_benchmark_nav_into_chain"
```

The simpler fix (repoint `down_revision`) is preferred since the tables are in the same vertical and there is no real schema independence between them.

# Technical Details

- **File:** `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` line 19
- **Current value:** `down_revision = "0011"`
- **Correct value:** `down_revision = "0012"`
- **Detection command:** `alembic heads` — if it prints two revision hashes, the branch exists.
- **Source:** data-integrity-guardian
