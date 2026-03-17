---
status: pending
priority: p2
issue_id: "119"
tags: [code-review, mandate-fit, naming]
dependencies: []
---

# min_liquidity_days naming is semantically inverted

## Problem Statement

`ClientProfile.min_liquidity_days` is named as a minimum but is used as a maximum. The comment says "max acceptable redemption days" and the evaluator checks `redemption_days <= min_liquidity_days`. The field should be `max_redemption_days` to match actual semantics.

This is a new model with zero existing callers — renaming now is cheap, renaming after callers exist is expensive.

## Findings

**Flagged by:** Python Reviewer

**Evidence:**
- `backend/vertical_engines/wealth/mandate_fit/models.py` line 20: `min_liquidity_days: int | None  # max acceptable redemption days`
- `backend/vertical_engines/wealth/mandate_fit/constraint_evaluator.py` line 136: `if int(redemption_days) <= profile.min_liquidity_days`

## Proposed Solutions

### Option A: Rename to `max_redemption_days` (Recommended)
- Rename field, update evaluator, update tests
- **Effort:** Small (10 min)

## Acceptance Criteria

- [ ] Field renamed to `max_redemption_days`
- [ ] All references in evaluator and tests updated
- [ ] Tests still pass

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
