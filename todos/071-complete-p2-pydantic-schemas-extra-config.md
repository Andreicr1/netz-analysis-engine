---
status: pending
priority: p2
issue_id: "071"
tags: [code-review, architecture]
---

# Pydantic schemas missing explicit extra config

## Problem Statement

CLAUDE.md requires `extra="ignore"` or `extra="forbid"` on all Pydantic BaseModel configs. Multiple wealth schemas only set `from_attributes=True` without declaring `extra`. Per docs/solutions/pydantic-migration-review-findings, this should be explicit.

## Findings

- CLAUDE.md rule: Use `extra="ignore"` or `extra="forbid"` on Pydantic BaseModel configs. Never `extra="allow"` unless documented.
- Multiple wealth schemas have `ConfigDict(from_attributes=True)` without explicit `extra` setting
- 8+ schema files in the wealth domain are affected
- Implicit default (`extra="ignore"` in Pydantic v2) should be made explicit per project standards

## Proposed Solutions

Add `extra="ignore"` to all `ConfigDict` declarations in wealth schemas (content.py, dd_report.py, universe.py, model_portfolio.py, fact_sheet.py, fund.py, etc.).

## Technical Details

- Affected files (8+ schema files):
  - `backend/app/domains/wealth/schemas/content.py`
  - `backend/app/domains/wealth/schemas/dd_report.py`
  - `backend/app/domains/wealth/schemas/universe.py`
  - `backend/app/domains/wealth/schemas/model_portfolio.py`
  - `backend/app/domains/wealth/schemas/fact_sheet.py`
  - `backend/app/domains/wealth/schemas/fund.py`
  - (and others in the same directory)
- Change: `model_config = ConfigDict(from_attributes=True)` -> `model_config = ConfigDict(from_attributes=True, extra="ignore")`
- Reference: `docs/solutions/architecture-patterns/pydantic-migration-review-findings-PolicyThresholds-20260316.md`

## Acceptance Criteria

- [ ] All Pydantic schemas in wealth domain have explicit `extra="ignore"` or `extra="forbid"`
- [ ] No schema uses implicit extra behavior
- [ ] All existing tests pass
- [ ] Consistent with patterns in credit domain schemas

## Work Log

(none yet)
