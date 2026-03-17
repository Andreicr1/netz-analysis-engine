---
status: pending
priority: p2
issue_id: 128
tags: [code-review, security, multi-tenancy]
---

# Problem Statement

`POST /strategy-drift/scan` acquires a PostgreSQL advisory lock using a hardcoded global lock ID (`900005`). Because the lock ID is not scoped to `organization_id`, one tenant's drift scan blocks all other tenants' scans for the entire duration. In a multi-tenant SaaS context this is a cross-tenant resource contention bug and a potential denial-of-service vector.

# Findings

- `backend/app/domains/wealth/routes/strategy_drift.py` lines 161-174 call `pg_try_advisory_lock(900005)` with a literal constant.
- Advisory locks in PostgreSQL are session-scoped globals — there is no built-in tenant isolation.
- Org A acquiring lock 900005 blocks Org B's scan request entirely until Org A's transaction completes.
- Under load (multiple orgs scanning simultaneously), queuing behavior degrades to serial execution across all tenants.
- The lock was presumably added to prevent duplicate scans within a single org, but its current scope is cluster-wide.

# Proposed Solutions

**Option 1 (recommended): Hash org_id into lock ID.**
Derive a stable integer from `organization_id` using a hash and combine with the base constant:
```python
import hashlib
org_hash = int(hashlib.sha256(org_id.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
lock_id = 900000 + (org_hash % 10000)
```
This gives per-org lock IDs with extremely low collision probability (10,000 buckets).

**Option 2: Use `pg_try_advisory_xact_lock`.**
Transaction-scoped advisory locks auto-release on commit/rollback — no explicit unlock needed. Reduces lock leak risk. Still requires org-scoped ID.

**Option 3: Accept global serialization.**
Document explicitly that drift scans are globally serialized. Acceptable only for very low scan frequency (< 1 scan/minute across all orgs combined).

**Recommendation:** Option 1 + Option 2 combined: per-org hash ID with transaction-scoped lock.

# Technical Details

- **File:** `backend/app/domains/wealth/routes/strategy_drift.py` lines 161-174
- **Lock call:** `SELECT pg_try_advisory_lock(900005)`
- **Tenant isolation requirement:** All per-org operations must not interfere with other orgs (CLAUDE.md multi-tenancy rules).
- **Source:** security-sentinel
