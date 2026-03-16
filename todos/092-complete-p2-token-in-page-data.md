---
status: complete
priority: p2
issue_id: "092"
tags: [code-review, security, authentication, frontend]
dependencies: []
---

# JWT token passed in page data from server to client

## Problem Statement

`+layout.server.ts:22-26` returns the raw JWT `token` in the page data payload. SvelteKit serializes this into the `__data.json` response visible in the HTML. While intentional (needed for client-side API calls and session expiry monitoring), this means:

1. The JWT is visible in the HTML source/network tab
2. If CDN/edge caching is misconfigured, another user's JWT could be served
3. The token persists in browser memory via SvelteKit's data store

This affects both credit and wealth frontends.

## Findings

- `frontends/credit/src/routes/+layout.server.ts:25` — `token` returned in load data
- `frontends/wealth/src/routes/+layout.server.ts` — same pattern
- Token used by: client-side API client, SSE connections, session expiry monitor
- Risk is low IF caching headers are correct (no-store for authenticated pages)
- Alternative: use HTTP-only cookie for API auth, or Clerk's `getToken()` on client side

## Proposed Solutions

### Option 1: Use Clerk's client-side getToken() instead of passing from server

**Approach:** On client side, use `svelte-clerk`'s `getToken()` instead of receiving token from server. Remove token from page data.

**Effort:** 2-3 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/+layout.server.ts`
- `frontends/wealth/src/routes/+layout.server.ts`

## Acceptance Criteria

- [ ] JWT not serialized into page data HTML
- [ ] Client-side API calls still authenticated
- [ ] Cache-Control headers verified for authenticated pages

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #39, #41
