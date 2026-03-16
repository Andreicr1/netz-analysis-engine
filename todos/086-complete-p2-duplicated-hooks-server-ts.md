---
status: complete
priority: p2
issue_id: "086"
tags: [code-review, architecture, duplication, frontend]
dependencies: ["083"]
---

# hooks.server.ts duplicated identically across credit and wealth frontends

## Problem Statement

`frontends/credit/src/hooks.server.ts` and `frontends/wealth/src/hooks.server.ts` are **byte-for-byte identical** (103 lines). The `Actor` interface is also duplicated in each file instead of being imported from `@netz/ui`. This violates the architecture principle that shared code lives in `@netz/ui`.

When JWT verification is implemented (todo #083), changes must be made in 2+ places.

## Findings

- Credit hooks: `frontends/credit/src/hooks.server.ts` — 103 lines
- Wealth hooks: `frontends/wealth/src/hooks.server.ts` — 103 lines
- Both define identical: `Actor`, `parseDevActor`, `decodeJwtPayload`, `actorFromClaims`, `handle`
- `@netz/ui/utils/auth.ts` has `createClerkHook()` stub that was INTENDED for this but never used
- `Actor` type should be exported from `@netz/ui` as the canonical definition

## Proposed Solutions

### Option 1: Implement createClerkHook in @netz/ui, use in both frontends

**Approach:** Complete the `createClerkHook()` stub in `@netz/ui/utils/auth.ts`. Both frontends import and use it.

**Pros:**
- Single source of auth logic
- Changes propagate to all frontends
- Matches original design intent

**Cons:**
- Need to handle per-frontend config differences (if any)

**Effort:** 2-3 hours (combine with todo #083)

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/hooks.server.ts` — to be replaced with shared import
- `frontends/wealth/src/hooks.server.ts` — to be replaced with shared import
- `packages/ui/src/lib/utils/auth.ts` — implement createClerkHook

## Acceptance Criteria

- [ ] Auth hook logic exists in exactly one place (@netz/ui)
- [ ] Actor type exported from @netz/ui
- [ ] Both frontends import and configure the shared hook

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #39, #41 (Phases B, C)
