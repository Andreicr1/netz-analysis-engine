---
status: pending
priority: p2
issue_id: "086"
tags: [code-review, correctness, rls]
dependencies: []
---

# Health Routes Use RLS Session for Cross-Tenant Queries

## Problem Statement
`backend/app/domains/admin/routes/health.py` uses `get_db_with_rls` but `get_tenant_usage` queries `vertical_config_overrides` grouped by `organization_id` — a cross-tenant aggregation. RLS filters to a single org, so this query returns only the admin's own org data, not all tenants.

## Findings
- **Source:** Kieran Python Reviewer (MEDIUM), Learnings Researcher (known RLS pattern)
- **Known pattern:** docs/solutions/architecture-patterns/parallel-agent-batch-code-review-resolution-20260316.md

## Proposed Solutions
### Solution A: Use non-RLS session for health routes (Recommended)
Import `async_session_factory` directly (like the existing asset serving endpoint does) for cross-tenant admin queries.
- **Effort:** Small (30 min)

## Acceptance Criteria
- [ ] `get_tenant_usage` returns data for ALL tenants, not just admin's org
- [ ] Worker and pipeline stats are not affected by RLS
