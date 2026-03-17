---
status: pending
priority: p2
issue_id: "159"
tags: [code-review, performance, admin]
---

# Tenant list endpoint has no pagination

## Problem Statement
`GET /admin/tenants/` returns all tenants in a single response with no LIMIT/OFFSET. Breaks at 1000+ tenants.

## Findings
- `backend/app/domains/admin/routes/tenants.py`: `list_tenants` has no pagination

## Proposed Solution
Add `limit`/`offset` query params with default page size of 50.
