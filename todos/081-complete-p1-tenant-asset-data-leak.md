---
status: complete
priority: p1
issue_id: "081"
tags: [code-review, security, tenant-isolation, data-leak]
dependencies: []
---

# Tenant asset endpoint ignores org_slug — returns first match from any tenant

## Problem Statement

`assets.py:65-76` queries `tenant_assets` without filtering by tenant. The `org_slug` path parameter is **completely ignored**. Since this endpoint uses `async_session_factory()` directly (no RLS), the query `WHERE asset_type == asset_type` returns the **first asset row** regardless of which organization uploaded it. In a multi-tenant deployment, Tenant B's logo could appear on Tenant A's portal.

## Findings

- `backend/app/domains/admin/routes/assets.py:65-76` — Query has NO tenant filtering
- Line 52-53: Uses `async_session_factory()` (no RLS) — intentionally public endpoint
- Line 73: Comment acknowledges the issue: `# TODO: Add org_slug column to tenant_assets or create organizations table`
- The `org_slug` URL parameter is received but never used in the query
- `tenant_assets` table has `organization_id` column and RLS policy, but RLS is bypassed here
- Impact: Cross-tenant asset leakage (logo, favicon) — reputational/branding issue

## Proposed Solutions

### Option 1: Add org_slug column to tenant_assets, filter by it

**Approach:** Add `org_slug` to `tenant_assets` table (set during upload from Clerk org claim), filter in the public query.

**Pros:**
- Clean solution, no external dependency
- Public endpoint remains unauthenticated
- Slug is safe to expose in URLs

**Cons:**
- Requires migration
- Must sync slug if org renames in Clerk

**Effort:** 2-3 hours

**Risk:** Low

---

### Option 2: Create organizations table, join against it

**Approach:** Create a lightweight `organizations` table with `id` and `slug`, populate from Clerk webhook or on first auth.

**Pros:**
- Solves the problem properly for future use
- Single source of org metadata

**Cons:**
- More infrastructure (webhook listener or sync)
- Overkill for just asset serving

**Effort:** 6-8 hours

**Risk:** Medium

---

### Option 3: Pass organization_id via branding API, use signed asset URLs

**Approach:** Branding endpoint (authenticated) returns signed/tokenized asset URLs that encode the org_id. Asset endpoint validates the token.

**Pros:**
- No DB schema change
- Cryptographically secure

**Cons:**
- More complex
- Breaks cacheability unless token is long-lived

**Effort:** 3-4 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `backend/app/domains/admin/routes/assets.py:65-76` — Missing tenant filter
- `backend/app/core/db/migrations/versions/0009_admin_infrastructure.py` — tenant_assets schema

**Database changes:**
- Option 1: Migration to add `org_slug` column to `tenant_assets`
- Option 2: New `organizations` table + migration

## Acceptance Criteria

- [ ] Asset endpoint only returns assets belonging to the requested tenant
- [ ] No cross-tenant asset leakage verified by test with 2+ tenants
- [ ] Default logo still returned for unknown slugs (prevent enumeration)
- [ ] Backend test covering multi-tenant asset isolation

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

**Actions:**
- Read assets.py and found org_slug parameter is completely unused
- Verified query returns first row from any tenant
- Noted TODO comment acknowledging the gap
- Classified as P1 — cross-tenant data leakage

## Resources

- **PRs:** #37 (Phase A)
- **File:** `backend/app/domains/admin/routes/assets.py`
