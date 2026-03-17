---
status: pending
priority: p3
issue_id: "124"
tags: [code-review, fee-drag, documentation, financial-calculation]
dependencies: []
---

# performance_fee_pct semantics unclear — flat deduction vs % of alpha

## Problem Statement

`performance_fee_pct` is treated as a flat percentage deducted from gross return. A "2-and-20" fund (2% mgmt, 20% performance) stores `performance_fee_pct=20.0` which gets subtracted directly, yielding -10% net on a 12% gross return. In reality, 20% performance fee means 20% of profits above hurdle, not 20 percentage points.

This is a product/design decision. The current model is a simplified linear approximation that may surprise downstream consumers.

## Proposed Solutions

Add a docstring clarifying that `performance_fee_pct` means "annualized estimated fee drag from performance fees in percentage points" — not the headline performance fee rate.

- **Effort:** Small (5 min)

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
