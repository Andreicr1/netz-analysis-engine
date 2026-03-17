---
status: pending
priority: p1
issue_id: 127
tags: [code-review, routing]
---

# Problem Statement

`risk/+page.server.ts` calls `api.get("/wealth/analytics/strategy-drift/alerts")` but `strategy_drift_router` is mounted in `main.py` without a `/wealth` prefix. The actual endpoint resolves to `/api/v1/analytics/strategy-drift/alerts`. The frontend is calling a path that does not exist, causing silent 404s on the risk page.

# Findings

- `frontends/wealth/src/routes/(team)/risk/+page.server.ts` line 16 calls `/wealth/analytics/strategy-drift/alerts`.
- `strategy_drift_router` in `backend/app/main.py` is mounted without a `/wealth` prefix in `main.py`, so the route resolves to `/api/v1/analytics/strategy-drift/alerts`.
- The `/wealth/` segment in the frontend URL has no corresponding mount-time prefix in the backend.
- This is the inverse of issue #126: one router has a double-prefix; this one is missing the prefix on the frontend side.
- The risk page data loader silently returns no alerts rather than raising an error, masking the bug.

# Proposed Solutions

Two valid fixes — pick whichever aligns with the decision made in issue #126:

1. **Fix the frontend URL:** Change the frontend call from `/wealth/analytics/strategy-drift/alerts` to `/analytics/strategy-drift/alerts` to match the actual mount path.
2. **Fix the backend mount:** Add `prefix="/wealth"` to the `strategy_drift_router` mount in `main.py` and strip the prefix from the router's own declaration so it resolves to `/api/v1/wealth/analytics/strategy-drift/alerts`.

Option 2 is preferred if the decision from #126 is to namespace all wealth routes under `/api/v1/wealth/`.

Both issues (#126 and #127) should be resolved together in a single routing audit pass.

# Technical Details

- **Files:**
  - `frontends/wealth/src/routes/(team)/risk/+page.server.ts` line 16
  - `backend/app/main.py` (strategy_drift_router mount)
  - `backend/app/domains/wealth/routes/strategy_drift.py`
- **Related issue:** #126 (exposure router double-prefix)
- **Source:** pattern-recognition
