---
status: pending
priority: p2
issue_id: "113"
tags: [code-review, performance, rebalancing]
dependencies: []
---

# impact_analyzer loads all portfolios and filters JSONB in Python

## Problem Statement

`impact_analyzer.py` loads ALL active model portfolios for a tenant and iterates their JSONB `fund_selection_schema` in Python to find which contain the removed instrument. At 1000 portfolios with 20 funds each = 20,000 string comparisons after transferring megabytes of JSONB from PostgreSQL.

## Proposed Solutions

### Option A: Push filtering into PostgreSQL with jsonb_array_elements (RECOMMENDED)
```sql
SELECT mp.id, fund_entry->>'weight'
FROM model_portfolios mp,
     jsonb_array_elements(mp.fund_selection_schema->'funds') AS fund_entry
WHERE mp.organization_id = :org_id AND mp.status = 'active'
  AND fund_entry->>'instrument_id' = :instrument_id
```
Add GIN index on fund_selection_schema for sub-millisecond lookups.
- **Effort**: Small
- **Risk**: Low

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/rebalancing/impact_analyzer.py`

## Acceptance Criteria

- [ ] JSONB filtering happens in PostgreSQL, not Python
- [ ] Only matching rows transferred to application

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 performance review | |
