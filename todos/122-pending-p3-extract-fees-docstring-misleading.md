---
status: pending
priority: p3
issue_id: "122"
tags: [code-review, fee-drag, documentation]
dependencies: []
---

# _extract_fees docstring misleading — implies type-exclusive fees

## Problem Statement

The `compute_fee_drag` docstring says "fund: management_fee_pct, performance_fee_pct / bond: bid_ask_spread_pct / equity: brokerage_fee_pct" — implying bonds/equities only have their type-specific fee. But the code always reads `management_fee_pct` and `performance_fee_pct` for ALL types, with the type-specific fee as an addition.

## Proposed Solutions

Update docstring to clarify: mgmt+perf fees are universal, other_fees varies by type.

- **Effort:** Small (5 min)

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |
