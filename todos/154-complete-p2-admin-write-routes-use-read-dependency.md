---
status: pending
priority: p2
issue_id: "154"
tags: [code-review, architecture, admin]
---

# Admin write routes use `get_db_admin_read` instead of `get_db_for_tenant`

## Problem Statement
All admin write endpoints (PUT, POST, DELETE) use `get_db_admin_read()` which is named as a read-only dependency. `get_db_for_tenant(org_id)` exists but is never used. Misleading naming and missing org context for tenant-scoped writes.

## Findings
- `backend/app/domains/admin/routes/configs.py`: PUT/DELETE use `get_db_admin_read`
- `backend/app/domains/admin/routes/tenants.py`: POST upload, seed use `get_db_admin_read`
- `get_db_for_tenant()` in `admin_middleware.py` is defined but unused

## Proposed Solutions
1. Rename `get_db_admin_read` to `get_db_admin` and use for all admin ops
2. Use `get_db_for_tenant(org_id)` for tenant-scoped writes, keep `get_db_admin_read` for cross-tenant reads
