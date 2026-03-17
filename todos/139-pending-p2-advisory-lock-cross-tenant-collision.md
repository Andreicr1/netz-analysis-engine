---
status: pending
priority: p2
issue_id: "139"
tags: [code-review, security, multi-tenancy]
dependencies: []
---

# Advisory lock cross-tenant collision in drift scan

## Problem Statement

The drift scan uses `pg_try_advisory_lock(900_005)` with a fixed global lock ID. This is a database-wide session-level lock. If Org A triggers a scan, Org B receives a 409 Conflict even though they operate on completely separate data. This is a multi-tenant isolation issue.

## Findings

- Found by: security-sentinel, performance-oracle, data-integrity-guardian, architecture-strategist (4 agents)
- `backend/app/domains/wealth/routes/strategy_drift.py` line 34, 162-174
- Lock ID `900_005` is a global constant, not org-scoped
- Benchmark ingest (`900_004`) correctly uses a global lock since `benchmark_nav` is a global table

## Proposed Solutions

### Option 1: Two-argument advisory lock with org hash (Recommended)

**Approach:** Use `pg_try_advisory_lock(900005, hash_of_org_id)` to scope per org.

**Pros:** Allows concurrent cross-org scans, simple change

**Cons:** Need to hash UUID to int32

**Effort:** 30 minutes
**Risk:** Low

### Option 2: Use pg_try_advisory_xact_lock

**Approach:** Transaction-scoped lock auto-released on commit/rollback.

**Pros:** No explicit unlock needed, crash-safe

**Cons:** Released on commit — only works if single commit per scan

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/strategy_drift.py` lines 34, 162-174

## Acceptance Criteria

- [ ] Org A can scan while Org B is scanning
- [ ] Same org concurrent scans still serialized
- [ ] Advisory lock properly released on error

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
