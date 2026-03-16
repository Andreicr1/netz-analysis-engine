---
status: pending
priority: p2
issue_id: "084"
tags: [code-review, security, authentication, frontend]
dependencies: []
---

# Hardcoded "dev-token" in client-side components bypasses auth

## Problem Statement

Multiple client-side components use `() => Promise.resolve("dev-token")` as the token provider for API clients and SSE connections. These will fail silently in production (backend will reject the token) and indicate incomplete auth integration for client-side API calls.

## Findings

- `frontends/credit/src/lib/components/ICMemoViewer.svelte:37` — `createClientApiClient(() => Promise.resolve("dev-token"))`
- `frontends/credit/src/lib/components/ICMemoViewer.svelte:44` — `getToken: () => Promise.resolve("dev-token")` for SSE
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte:42` — same pattern
- These components need the real Clerk token from the auth context

## Proposed Solutions

### Option 1: Pass getToken via component props or Svelte context

**Approach:** Root layout provides `getToken` function via Svelte context. Components retrieve it via `getContext()`.

**Pros:**
- Clean dependency injection
- Single source of auth token

**Cons:**
- Need to set up context in layout

**Effort:** 1-2 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/lib/components/ICMemoViewer.svelte:37,44`
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte:42`

## Acceptance Criteria

- [ ] No hardcoded "dev-token" strings in production client code
- [ ] Client-side API calls use real Clerk token
- [ ] SSE connections use real Clerk token

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #39 (Phase B)
