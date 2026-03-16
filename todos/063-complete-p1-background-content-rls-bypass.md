---
status: pending
priority: p1
issue_id: "063"
tags: [code-review, security]
---

# TODO 063: Background content generation bypasses RLS

## Problem Statement

In `backend/app/domains/wealth/routes/content.py` lines 376-386, `_run_content_generation` uses `async_session_factory()` without setting RLS context via `SET LOCAL app.current_organization_id`. This means:

- If RLS is enforced (`FORCE ROW LEVEL SECURITY`), the query returns zero rows and content is never updated
- If RLS is not enforced for the app role, this is a cross-tenant data access risk

## Findings

- **Source:** Code review of PRs #32-#36 (Wealth Vertical Modularization)
- **File:** `backend/app/domains/wealth/routes/content.py:376-386`
- **Severity:** P1 — security (cross-tenant data access) and correctness (silent no-op under strict RLS)
- **Pattern violation:** All database access must go through RLS-scoped sessions. Background tasks that create their own sessions must explicitly set `SET LOCAL app.current_organization_id`.
- **Contrast:** `dd_reports.py` correctly handles RLS in background tasks — this file does not follow that pattern.

## Proposed Solutions

**Solution A (preferred):** Pass `org_id` to the background task and execute `SET LOCAL app.current_organization_id` before any query:

```python
async def _run_content_generation(content_id: int, org_id: str):
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL app.current_organization_id = :org_id"), {"org_id": org_id})
        # ... rest of the function
```

**Solution B:** Use the sync session factory inside `asyncio.to_thread()` (matching the `dd_reports.py` pattern) with proper RLS context.

## Technical Details

- The background task is spawned from a route handler that has access to the authenticated `org_id`
- The `org_id` must be captured at spawn time and passed into the background function
- `SET LOCAL` is transaction-scoped, so it must be called within the same transaction as the queries
- Using `SET` (without `LOCAL`) would leak across pooled connections — never do this

### Affected files

- `backend/app/domains/wealth/routes/content.py:376-386`

## Acceptance Criteria

- [ ] Background content update uses RLS-scoped session
- [ ] Content record updates correctly after generation
- [ ] No cross-tenant data access possible

## Work Log

_(empty — work not yet started)_
