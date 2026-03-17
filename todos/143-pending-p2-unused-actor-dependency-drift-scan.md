---
status: pending
priority: p2
issue_id: "143"
tags: [code-review, security, auth]
dependencies: []
---

# Unused actor dependency in drift scan POST — missing role check

## Problem Statement

The `trigger_drift_scan` POST endpoint injects `actor: Actor = Depends(get_actor)` but never uses it. The screener's equivalent `trigger_screening` POST enforces `_require_investment_role(actor)`. Either a role check is missing (security gap) or the dependency is dead code.

## Findings

- Found by: pattern-recognition-specialist, kieran-python-reviewer (2 agents)
- `backend/app/domains/wealth/routes/strategy_drift.py` line 159
- Screener reference: `backend/app/domains/wealth/routes/screener.py` uses `_require_investment_role(actor)`

## Proposed Solutions

### Option 1: Add role check (Recommended)

**Approach:** Add `_require_admin_role(actor)` or `_require_investment_role(actor)` to enforce authorization.

**Effort:** 5 minutes
**Risk:** Low

### Option 2: Remove unused dependency

**Approach:** Remove `actor: Actor = Depends(get_actor)` if no role check needed.

**Effort:** 2 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/strategy_drift.py` line 159

## Acceptance Criteria

- [ ] Either role check added or unused dependency removed
- [ ] Consistent with screener pattern

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
