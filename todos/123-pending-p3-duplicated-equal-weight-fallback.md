---
status: pending
priority: p3
issue_id: "123"
tags: [code-review, fee-drag, simplification]
dependencies: []
---

# Duplicated equal-weight fallback in compute_portfolio_fee_drag

## Problem Statement

When `weights` is provided but `total_weight == 0`, the code falls back to equal-weight averaging — same as the `else` branch. Lines 142-143 duplicate lines 145-146.

## Proposed Solutions

Normalize weights to `None` when `total_weight == 0`, then use single code path.

- **Effort:** Small (5 min)

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
