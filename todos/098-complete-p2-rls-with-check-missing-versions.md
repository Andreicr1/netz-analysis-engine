---
status: complete
priority: p2
issue_id: "098"
tags: [code-review, security, database, rls]
dependencies: []
---

# prompt_override_versions RLS policy missing WITH CHECK clause

## Problem Statement

Migration 0009 creates a `parent_isolation` policy on `prompt_override_versions` with only a `USING` clause (read path) but no `WITH CHECK` clause (write path). Since `FORCE ROW LEVEL SECURITY` is enabled, INSERTs to this table will be rejected by PostgreSQL because no write policy exists.

## Findings

- `backend/app/core/db/migrations/versions/0009_admin_infrastructure.py:192-201`
- Policy has `USING (...)` but no `WITH CHECK (...)`
- `tenant_assets` and `prompt_overrides` correctly have both `USING` and `WITH CHECK`
- Impact: Cannot insert prompt override versions when RLS is active

**Source:** Architecture Strategist agent

## Proposed Solutions

### Option 1: Add WITH CHECK clause in follow-up migration

**Approach:** Migration 0010 adds `WITH CHECK` matching the `USING` clause.

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `backend/app/core/db/migrations/versions/0009_admin_infrastructure.py:192-201`
- New migration needed

## Acceptance Criteria

- [ ] `prompt_override_versions` has both USING and WITH CHECK in RLS policy
- [ ] Version inserts succeed with RLS active

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Architecture Strategist (ce:review PRs #37-#45)

## Resources

- **PR:** #37 (Phase A)
