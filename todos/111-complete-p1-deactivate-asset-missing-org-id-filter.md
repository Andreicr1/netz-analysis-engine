---
status: pending
priority: p1
issue_id: "111"
tags: [code-review, security, multi-tenancy, rebalancing]
dependencies: []
---

# deactivate_asset() Fund query missing organization_id filter

## Problem Statement

`universe_service.py` line 186 queries Fund by `fund_id` only, with no `organization_id` filter:

```python
fund = db.execute(
    select(Fund).where(Fund.fund_id == instrument_id).with_for_update()
).scalar_one_or_none()
```

This is a pre-existing issue amplified by this PR — deactivation now triggers downstream rebalancing scoped to the caller's org, not the fund's org. A user from org-A could theoretically deactivate org-B's fund.

Additionally, `organization_id` is optional (`str | None = None`), allowing unscoped deactivation with rebalancing silently skipped.

## Findings

- **Security Sentinel**: CRITICAL — cross-tenant fund deactivation possible
- **Agent-Native**: organization_id=None silently skips rebalancing with no indication
- **Known Pattern**: docs/solutions/performance-issues/rls-subselect-1000x-slowdown — RLS may mitigate at DB level but defense-in-depth requires app-layer filtering

## Proposed Solutions

### Option A: Add org_id filter + make parameter required (RECOMMENDED)
- Add `Fund.organization_id == organization_id` to the query
- Change `organization_id: str | None = None` to `organization_id: str` (required)
- Add org_id filter to the UniverseApproval query too
- **Effort**: Small
- **Risk**: Low — no current callers pass without org_id

### Option B: Keep optional but log warning
- Log warning when rebalance_needed=True but organization_id is None
- **Effort**: Small
- **Risk**: Medium — still allows unscoped deactivation

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/asset_universe/universe_service.py`
- **Lines**: 178, 186-188, 197-203

## Acceptance Criteria

- [ ] Fund query filters by organization_id
- [ ] UniverseApproval query filters by organization_id
- [ ] organization_id parameter is required (not optional)
- [ ] Tests updated to always pass organization_id

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 security review | Pre-existing issue amplified by rebalancing trigger |

## Resources

- PR: #49
- docs/solutions/security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md
