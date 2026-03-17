---
status: pending
priority: p3
issue_id: "145"
tags: [code-review, security, input-validation]
dependencies: []
---

# Profile path parameter lacks validation constraint

## Problem Statement

The `profile` path parameter in attribution and correlation routes is an unbounded string. While used safely in parameterized queries, it's echoed in error messages and responses. An attacker could supply extremely long strings (log pollution) or inject content.

## Findings

- Found by: security-sentinel (Finding 4)
- `backend/app/domains/wealth/routes/attribution.py` line 66: `profile: str`
- `backend/app/domains/wealth/routes/correlation_regime.py` lines 41, 208

## Proposed Solutions

### Option 1: Add Path constraint (Recommended)

**Approach:** `profile: str = Path(..., min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")`

**Effort:** 10 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/attribution.py`
- `backend/app/domains/wealth/routes/correlation_regime.py`

## Acceptance Criteria

- [ ] Profile parameter validated with length + pattern
- [ ] Error messages don't echo unbounded user input

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
