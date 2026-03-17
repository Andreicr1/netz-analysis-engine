---
status: pending
priority: p3
issue_id: "148"
tags: [code-review, quality, duplication]
dependencies: []
---

# Duplicate fund_selection_schema parsing in attribution + correlation routes

## Problem Statement

Both `attribution.py` (lines 141-149) and `correlation_regime.py` (lines 62-76) independently parse `fund_selection_schema` JSONB with identical isinstance-checking logic to extract instrument IDs. This ~15-line pattern is duplicated and will likely appear in future routes.

## Findings

- Found by: kieran-python-reviewer, code-simplicity-reviewer (2 agents)
- `backend/app/domains/wealth/routes/attribution.py` lines 141-149
- `backend/app/domains/wealth/routes/correlation_regime.py` lines 62-76

## Proposed Solutions

### Option 1: Extract shared helper (Recommended)

**Approach:** Create `extract_instrument_ids_from_fund_selection(schema: dict) -> dict[str, list[str]]` in a shared module (e.g., `routes/common.py`).

**Effort:** 20 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/attribution.py`
- `backend/app/domains/wealth/routes/correlation_regime.py`
- New: `backend/app/domains/wealth/routes/common.py` (or add to existing)

## Acceptance Criteria

- [ ] Single source of truth for fund_selection parsing
- [ ] Both routes use the shared helper
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
