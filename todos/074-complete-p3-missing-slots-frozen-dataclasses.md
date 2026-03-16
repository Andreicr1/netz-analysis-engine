---
status: pending
priority: p3
issue_id: "074"
tags: [code-review, quality]
---

# 074: Missing slots=True on frozen dataclasses

## Problem Statement

dd_report/ uses `@dataclass(frozen=True, slots=True)` but several other wealth modules omit `slots=True`. Inconsistent memory optimization across the codebase.

## Findings

- `dd_report/` — correctly uses `@dataclass(frozen=True, slots=True)`
- `fact_sheet/models.py` — missing `slots=True`
- `model_portfolio/models.py` — missing `slots=True`
- `monitoring/*.py` — missing `slots=True`
- `investment_outlook.py` — missing `slots=True`
- `flash_report.py` — missing `slots=True`
- `manager_spotlight.py` — missing `slots=True`

## Proposed Solutions

Add `slots=True` to all frozen dataclass decorators across wealth engines. This reduces per-instance memory and improves attribute access speed.

## Acceptance Criteria

- [ ] All `@dataclass(frozen=True)` decorators in wealth engines include `slots=True`
- [ ] No regressions in tests
