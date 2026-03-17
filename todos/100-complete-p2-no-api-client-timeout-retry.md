---
status: complete
priority: p2
issue_id: "100"
tags: [code-review, performance, resilience, frontend]
dependencies: []
---

# NetzApiClient has no fetch timeout or retry logic

## Problem Statement

`NetzApiClient` in `@netz/ui/utils/api-client.ts` calls `fetch()` with no `AbortSignal` timeout and no retry logic. A slow backend response blocks the SvelteKit server-side load function indefinitely. Server-side rendering is especially vulnerable since it blocks the entire page response.

## Findings

- `packages/ui/src/lib/utils/api-client.ts:161-191` — no timeout, no retry
- SvelteKit server-side load functions (`+page.server.ts`) use this client
- One slow query cascades into a hung page for the user

**Source:** Performance Oracle agent

## Proposed Solutions

### Option 1: Add AbortSignal.timeout + retry for GET requests

**Approach:** Add `signal: AbortSignal.timeout(15000)` to all fetch calls. Add 1 retry with backoff for idempotent GET requests.

**Effort:** 1-2 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/api-client.ts`

## Acceptance Criteria

- [ ] All fetch calls have a timeout (configurable, default 15s)
- [ ] GET requests retry once on timeout/network error
- [ ] Non-idempotent requests (POST, PATCH, DELETE) do not retry

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Performance Oracle (ce:review PRs #37-#45)

## Resources

- **PR:** #38 (Phase A.11)
