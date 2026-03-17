---
status: complete
priority: p2
issue_id: "187"
tags: [code-review, security, admin, frontend]
dependencies: []
---

# Admin route params (vertical, orgId) passed unsanitized to API paths

## Problem Statement

Route parameters `params.vertical` and `params.orgId` in the admin frontend are interpolated directly into API URL paths without validation. A crafted `vertical` parameter with `../` could traverse API paths if backend routing is permissive. SvelteKit supports `params` matchers for validation but none are configured.

## Findings

- `frontends/admin/src/routes/(admin)/prompts/[vertical]/+page.server.ts` — `api.get(/admin/prompts/${params.vertical})`
- `frontends/admin/src/routes/(admin)/config/[vertical]/+page.server.ts` — same pattern
- `frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.server.ts` — same pattern
- No `src/params/` directory exists in admin frontend

## Proposed Solutions

### Option 1: Add SvelteKit param matchers

**Approach:** Create `src/params/vertical.ts` (allowlist: `private_credit`, `liquid_funds`) and `src/params/orgId.ts` (UUID format). Reference in route names: `[vertical=vertical]`, `[orgId=orgId]`.

**Pros:**
- Validates at routing layer, returns 404 for invalid params

**Cons:**
- Minor route directory renaming

**Effort:** 1 hour

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/admin/src/params/vertical.ts` (new)
- `frontends/admin/src/params/orgId.ts` (new)
- Route directories need `=matcher` suffix

## Acceptance Criteria

- [ ] `[vertical=vertical]` matcher rejects non-allowlisted values
- [ ] `[orgId=orgId]` matcher validates UUID format
- [ ] Invalid params return 404

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — security-sentinel agent)
