---
status: pending
priority: p1
issue_id: "081"
tags: [code-review, correctness, caching]
dependencies: []
---

# Cache Invalidation Happens Before Transaction Commit

## Problem Statement
In `backend/app/core/config/config_writer.py`, `_invalidate_cache()` and `_notify()` are called inside `put()` and `delete()`, but the DB transaction has not committed yet (session is managed by FastAPI dependency injection). This creates a race:
1. Cache is invalidated immediately
2. Another request reads stale DB value (uncommitted transaction) and re-populates cache
3. Original transaction commits — cache now holds stale data until TTL expires

## Findings
- **Source:** Kieran Python Reviewer (CRITICAL)
- **Evidence:** Lines 112-117 in config_writer.py — `_invalidate_cache` called before session commit
- **Note:** pg_notify IS transactional (delivered after commit), but in-process `_invalidate_cache` is not

## Proposed Solutions

### Solution A: Remove in-process invalidation, rely solely on pg_notify (Recommended)
Remove `_invalidate_cache` calls from ConfigWriter. Let the pg_notify callback (which fires after commit) be the sole invalidation mechanism. The same-process instance will also receive the pg_notify event.
- **Pros:** Correct ordering guaranteed, simpler code
- **Cons:** Slight delay (pg_notify round-trip) for same-process invalidation
- **Effort:** Small (30 min)
- **Risk:** Low — TTL provides backstop

### Solution B: Post-commit hook
Register a SQLAlchemy `after_commit` event on the session to trigger cache invalidation.
- **Pros:** In-process invalidation with correct ordering
- **Cons:** More complex, requires session event registration
- **Effort:** Medium (1-2 hours)
- **Risk:** Medium — event registration complexity

## Recommended Action
<!-- Filled during triage -->

## Technical Details
- **Affected files:** `backend/app/core/config/config_writer.py`
- **Methods:** `put()`, `delete()`, `put_default()`

## Acceptance Criteria
- [ ] Cache is never invalidated before the writing transaction commits
- [ ] Stale reads during the commit window do not re-populate cache with old data
- [ ] pg_notify remains the cross-process invalidation mechanism

## Work Log
| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from code review | Kieran CRITICAL finding |

## Resources
- PR #43: https://github.com/Andreicr1/netz-analysis-engine/pull/43
