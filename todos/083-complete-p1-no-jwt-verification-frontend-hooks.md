---
status: complete
priority: p1
issue_id: "083"
tags: [code-review, security, authentication, frontend]
dependencies: []
---

# Frontend hooks.server.ts only decodes JWT — no signature verification

## Problem Statement

Both `frontends/credit/src/hooks.server.ts:95` and `frontends/wealth/src/hooks.server.ts:95` call `decodeJwtPayload()` which only base64-decodes the JWT payload without verifying the signature. The `createClerkHook()` in `@netz/ui/utils/auth.ts:67-73` is a **stub** that passes through without validation.

An attacker can craft a forged JWT with any `organization_id` and access SvelteKit server-rendered pages (SSR). While the backend re-verifies JWTs for API calls (so data access is protected), an attacker could:
1. See page structure/layout for any organization
2. Receive SSR-rendered page shells with org-specific navigation
3. Bypass client-side role checks (seeing admin UI they shouldn't)

The comment on line 93 says "Clerk's middleware would verify" but no Clerk middleware is configured.

## Findings

- `frontends/credit/src/hooks.server.ts:95` — `decodeJwtPayload(token)` only decodes, no verification
- `frontends/wealth/src/hooks.server.ts:95` — identical issue
- `packages/ui/src/lib/utils/auth.ts:67-73` — `createClerkHook()` is a stub (pass-through)
- JWT verification comment is aspirational, not implemented
- Backend `clerk_auth.py` DOES verify JWTs — so API data is protected
- Impact: UI-level access control bypass, SSR page structure exposure

## Proposed Solutions

### Option 1: Implement Clerk JWT verification using JWKS

**Approach:** Use Clerk's JWKS endpoint to verify JWT signature in `hooks.server.ts`. Use `jose` npm package for JWKS verification.

**Pros:**
- Full JWT verification matching backend security
- Prevents forged JWT access to SSR pages
- Industry-standard approach

**Cons:**
- Requires JWKS endpoint URL in env vars
- Adds ~50ms latency for JWKS key fetch (cached)
- Need to handle key rotation

**Effort:** 3-4 hours

**Risk:** Low

---

### Option 2: Implement createClerkHook stub with clerk-sveltekit

**Approach:** Install `clerk-sveltekit` package, implement the hook properly.

**Pros:**
- Community-maintained Clerk integration
- Handles edge cases (key rotation, clock skew)

**Cons:**
- Community package may lag behind Clerk API changes (noted in CLAUDE.md)
- Additional dependency

**Effort:** 2-3 hours

**Risk:** Medium (community package stability)

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/hooks.server.ts:38-42,92-100`
- `frontends/wealth/src/hooks.server.ts:38-42,92-100`
- `packages/ui/src/lib/utils/auth.ts:67-73` — stub

## Acceptance Criteria

- [ ] JWT signature verified before extracting claims in hooks.server.ts
- [ ] Invalid/expired JWTs redirect to sign-in
- [ ] Forged JWTs cannot access SSR pages
- [ ] Dev mode bypass still works (import.meta.env.DEV)
- [ ] Backend JWT verification remains independent (defense in depth)

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

**Actions:**
- Identified JWT decode-without-verify in both frontend hooks
- Confirmed createClerkHook is a stub
- Verified backend does verify (defense in depth exists, but incomplete)

## Resources

- **PRs:** #39, #41 (Phases B, C)
- **CLAUDE.md:** Clerk SvelteKit SDK Note section
