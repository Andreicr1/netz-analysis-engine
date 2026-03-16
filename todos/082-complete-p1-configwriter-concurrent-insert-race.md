---
status: pending
priority: p1
issue_id: "082"
tags: [code-review, correctness, race-condition]
dependencies: []
---

# Race Condition on Concurrent INSERT in ConfigWriter.put()

## Problem Statement
In `backend/app/core/config/config_writer.py`, the `put()` method does SELECT → check if exists → INSERT or UPDATE. Two concurrent callers that both see `row is None` will both attempt INSERT with `version=1`. One gets a raw `IntegrityError` (duplicate key on unique constraint) instead of a meaningful `StaleVersionError`.

## Findings
- **Source:** Kieran Python Reviewer (CRITICAL)
- **Evidence:** Lines 74-110 — SELECT then INSERT without conflict handling

## Proposed Solutions

### Solution A: Use INSERT...ON CONFLICT DO UPDATE (Recommended)
Replace the SELECT + conditional INSERT/UPDATE with PostgreSQL upsert:
```python
stmt = pg_insert(VerticalConfigOverride).values(...)
stmt = stmt.on_conflict_do_update(
    constraint="uq_overrides_org_vertical_type",
    set_={"config": stmt.excluded.config, "version": VerticalConfigOverride.version + 1},
    where=(VerticalConfigOverride.version == expected_version) if expected_version else sa.true(),
)
```
- **Pros:** Atomic, no race window
- **Cons:** Slightly more complex SQL
- **Effort:** Medium (1-2 hours)
- **Risk:** Low

### Solution B: Wrap INSERT in try/except IntegrityError
Catch `IntegrityError` on the insert path and convert to `StaleVersionError`.
- **Pros:** Simple fix
- **Cons:** Still has a race window (just handles it gracefully)
- **Effort:** Small (30 min)
- **Risk:** Low

## Recommended Action
<!-- Filled during triage -->

## Technical Details
- **Affected files:** `backend/app/core/config/config_writer.py`
- **Method:** `put()` lines 74-110
- **Unique constraint:** `uq_overrides_org_vertical_type`

## Acceptance Criteria
- [ ] Two concurrent INSERTs for the same (vertical, config_type, org_id) do not produce IntegrityError
- [ ] Second writer gets StaleVersionError or silently loses (upsert semantics)
- [ ] Test added for concurrent insert scenario

## Work Log
| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from code review | Kieran CRITICAL finding |

## Resources
- PR #43: https://github.com/Andreicr1/netz-analysis-engine/pull/43
