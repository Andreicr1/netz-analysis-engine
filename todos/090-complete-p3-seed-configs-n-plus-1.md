---
status: pending
priority: p3
issue_id: "090"
tags: [code-review, performance]
dependencies: []
---

# _seed_configs N+1 Query Pattern

## Problem Statement
`backend/app/domains/admin/routes/tenants.py` `_seed_configs` (lines 173-215) runs a separate SELECT per default config to check if override exists. With 2 verticals and 10 config types each, that's 20 extra queries.

## Findings
- **Source:** Performance Oracle (P3), Pattern Recognition (Low)

## Proposed Solutions
Pre-fetch all existing overrides in one query, then check against the set in memory.
- **Effort:** Small (20 min)

## Acceptance Criteria
- [ ] _seed_configs executes at most 1+V queries (V = number of verticals)
