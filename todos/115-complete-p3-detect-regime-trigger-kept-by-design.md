---
status: pending
priority: p3
issue_id: "115"
tags: [code-review, simplicity, rebalancing]
dependencies: []
---

# detect_regime_trigger has no consumer — YAGNI

## Problem Statement

`detect_regime_trigger()` is 55 lines of production code with 70 lines of tests, but no route, worker, or scheduler calls it. It returns `RebalanceResult` objects with `proposals=()` and a nil UUID — no actionable output.

## Proposed Solutions

Remove entirely and add when a consumer exists (likely Sprint 4-5). Saves ~125 lines total.

## Technical Details

- **Affected files**: `service.py` lines 107-175, `test_rebalancing.py` TestRegimeChangeDetection class

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 simplicity review | |
