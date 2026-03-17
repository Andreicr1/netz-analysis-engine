---
status: complete
priority: p2
issue_id: "151"
tags: [code-review, frontend, deduplication, svelte]
dependencies: []
---

# Extract `createThemeHook()` to `@netz/ui/utils`

## Problem Statement

Both `frontends/credit/src/hooks.server.ts` and `frontends/wealth/src/hooks.server.ts` contain identical `themeHook` logic — the only difference is the default theme value (`"light"` vs `"dark"`). This duplication parallels the already-extracted `createClerkHook()` pattern.

## Findings

- Credit `hooks.server.ts:23-29`: themeHook with `"light"` default
- Wealth `hooks.server.ts:22-29`: themeHook with `"dark"` default
- Both use identical VALID_THEMES Set, identical cookie name `"netz-theme"`, identical `transformPageChunk` pattern
- `createClerkHook()` already exists in `@netz/ui/utils` as precedent for shared hook factories
- Plan explicitly tracks this as follow-up in "Future Considerations" section #1

## Proposed Solutions

### Option 1: Factory function in `@netz/ui/utils`

**Approach:** Add `createThemeHook({ defaultTheme })` to `packages/ui/src/lib/utils/theme.ts`, re-export from `@netz/ui/utils`.

**Pros:**
- Eliminates duplication
- Matches `createClerkHook()` pattern
- Single place to update cookie name, validation logic

**Cons:**
- Minor: touches `@netz/ui` package (rebuild needed)

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

*To be filled during triage.*

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/theme.ts` (NEW)
- `packages/ui/src/lib/utils/index.ts` (re-export)
- `frontends/credit/src/hooks.server.ts` (simplify)
- `frontends/wealth/src/hooks.server.ts` (simplify)

## Resources

- **PR:** #53
- **Plan reference:** `docs/plans/2026-03-17-feat-credit-frontend-design-refresh-plan.md` — Future Considerations #1

## Acceptance Criteria

- [ ] `createThemeHook({ defaultTheme })` exported from `@netz/ui/utils`
- [ ] Credit hooks.server.ts uses `createThemeHook({ defaultTheme: "light" })`
- [ ] Wealth hooks.server.ts uses `createThemeHook({ defaultTheme: "dark" })`
- [ ] `pnpm --filter @netz/ui build` passes
- [ ] Both frontends build successfully

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code

**Actions:**
- Identified duplication during PR #53 review
- Confirmed pattern matches existing `createClerkHook()` factory
- Already documented in plan's Future Considerations

**Learnings:**
- Plan anticipated this — was deferred to keep PR scope focused
