---
status: pending
priority: p2
issue_id: "069"
tags: [code-review, security]
---

# Worker endpoints lack role authorization

## Problem Statement

`backend/app/domains/wealth/routes/workers.py` endpoints (run-ingestion, run-risk-calc, run-portfolio-eval, run-macro-ingestion, run-fact-sheet-gen) only require basic auth via `get_current_user` but no role check. Any authenticated user including read-only analysts can trigger resource-intensive background workers.

## Findings

- 5 worker trigger endpoints use only `get_current_user` for authentication
- No role-based authorization is enforced
- Read-only analysts can trigger expensive background workers
- Affected endpoints: run-ingestion, run-risk-calc, run-portfolio-eval, run-macro-ingestion, run-fact-sheet-gen

## Proposed Solutions

Add `require_role(Role.ADMIN, Role.INVESTMENT_TEAM)` as dependency on worker trigger endpoints.

## Technical Details

- Affected file: `workers.py:36-126`
- Add role dependency: `require_role(Role.ADMIN, Role.INVESTMENT_TEAM)`
- Check existing role enforcement patterns in credit domain routes for consistency
- Ensure 403 response is returned for unauthorized users with clear error message

## Acceptance Criteria

- [ ] All 5 worker endpoints require ADMIN or INVESTMENT_TEAM role
- [ ] Read-only users receive 403 Forbidden when attempting to trigger workers
- [ ] Role check uses the same pattern as other protected endpoints in the codebase
- [ ] All existing tests pass (update test fixtures to include required roles)
- [ ] API documentation reflects the role requirement

## Work Log

(none yet)
