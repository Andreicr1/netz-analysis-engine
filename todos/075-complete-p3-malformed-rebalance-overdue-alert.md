---
status: pending
priority: p3
issue_id: "075"
tags: [code-review, bug]
---

# 075: Malformed alert detail when no rebalance exists

## Problem Statement

alert_engine.py `_check_rebalance_overdue()` sets `days_since = "never"` (string) then interpolates it as `"last rebalanced never days ago"`. Grammatically broken output.

## Findings

- `alert_engine.py:208-224` — when no rebalance record exists, `days_since` is set to the string `"never"`
- The detail string template always uses `f"last rebalanced {days_since} days ago"`
- Result: `"last rebalanced never days ago"` — nonsensical

## Proposed Solutions

Use conditional string formatting:
- No rebalance: `"has never been rebalanced"`
- Has rebalance: `f"last rebalanced {days_since} days ago"`

## Acceptance Criteria

- [ ] Alert detail reads `"has never been rebalanced"` when no rebalance record exists
- [ ] Alert detail reads `"last rebalanced N days ago"` when a rebalance record exists
- [ ] Unit test covers both branches
