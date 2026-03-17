---
status: complete
priority: p1
issue_id: "137"
tags: [code-review, security, api]
dependencies: []
---

# Route ordering: /alerts shadowed by /{instrument_id}

## Problem Statement

The `GET /{instrument_id}` route in `strategy_drift.py` is registered BEFORE `GET /alerts`. FastAPI matches routes in registration order. Any request to `/analytics/strategy-drift/alerts` will be captured by `/{instrument_id}`, which attempts `uuid.UUID("alerts")` and raises a 422 validation error instead of routing to the `/alerts` endpoint. **The /alerts endpoint is currently unreachable.**

## Findings

- Found by: security-sentinel, kieran-python-reviewer, pattern-recognition-specialist (3 agents)
- `strategy_drift.py` line 78: `@router.get("/{instrument_id}", ...)` registered first
- `strategy_drift.py` line 315: `@router.get("/alerts", ...)` registered second
- FastAPI evaluates routes top-to-bottom — the parameterized route captures "alerts" as an invalid UUID

## Proposed Solutions

### Option 1: Reorder route definitions (Recommended)

**Approach:** Move `/alerts` and `/scan` definitions BEFORE `/{instrument_id}` in the file.

**Pros:**
- Simple, 0 logic changes
- Fixes the bug immediately

**Cons:**
- None

**Effort:** 10 minutes
**Risk:** Low

## Recommended Action

Reorder route definitions: `/alerts` and `/scan` before `/{instrument_id}`.

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/strategy_drift.py`

## Acceptance Criteria

- [ ] GET /analytics/strategy-drift/alerts returns 200 (not 422)
- [ ] GET /analytics/strategy-drift/{uuid} still works
- [ ] POST /analytics/strategy-drift/scan still works
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified route shadowing via security, python, and pattern agents.
