---
status: pending
priority: p2
issue_id: "120"
tags: [code-review, fee-drag, data-quality]
dependencies: ["117"]
---

# Negative fee values not rejected in fee drag

## Problem Statement

`_extract_fees` does not validate that fee percentages are non-negative. An instrument with `management_fee_pct: -5.0` produces negative `total_fee_pct`, inflating `net_expected_return` above gross. This makes a high-fee instrument appear more attractive than it is.

## Findings

**Flagged by:** Security Sentinel, Python Reviewer

**Evidence:**
- `backend/vertical_engines/wealth/fee_drag/service.py` lines 166-179

## Proposed Solutions

### Option A: Clamp to max(0.0, val) in _safe_float or _extract_fees
- Apply after the `_safe_float` fix (#117)
- **Effort:** Small (5 min)

## Acceptance Criteria

- [ ] Negative fee values clamped to 0.0
- [ ] Test added: `management_fee_pct: -1.0` treated as 0.0

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
