---
status: pending
priority: p2
issue_id: "118"
tags: [code-review, mandate-fit, data-quality]
dependencies: []
---

# int() coercion in evaluate_liquidity raises on bad data

## Problem Statement

`evaluate_liquidity` calls `int(redemption_days)` on raw JSONB attribute values. If `redemption_days` is `"N/A"`, `None`, or `3.5`, this raises `ValueError`/`TypeError`. The exception is swallowed by the bare `except Exception` in `evaluate_universe`, silently dropping the instrument from results with no indication of data quality issues.

## Findings

**Flagged by:** Security Sentinel, Python Reviewer, Learnings Researcher

**Evidence:**
- `backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py` line 136

## Proposed Solutions

### Option A: Defensive cast with fallback ConstraintResult (Recommended)
```python
try:
    days = int(redemption_days)
except (TypeError, ValueError):
    return ConstraintResult(
        constraint="liquidity",
        passed=True,
        reason=f"Invalid redemption data '{redemption_days}' — assumed liquid",
    )
```
- **Effort:** Small (10 min)

## Acceptance Criteria

- [ ] Non-numeric `redemption_days` returns a ConstraintResult instead of raising
- [ ] Test added: `{"redemption_days": "N/A"}` returns passed=True with reason

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
