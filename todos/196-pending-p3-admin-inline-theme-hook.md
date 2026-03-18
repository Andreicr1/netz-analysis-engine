---
status: complete
priority: p3
issue_id: "196"
tags: [code-review, architecture, admin, frontend]
dependencies: []
---

# Admin duplicates theme hook instead of using createThemeHook

## Problem Statement

The admin `hooks.server.ts` implements its own inline `themeHook` instead of using `createThemeHook` from `@netz/ui/utils`, which credit and wealth both use. The logic is identical — unnecessary duplication.

## Findings

- `frontends/admin/src/hooks.server.ts` lines ~32-42 — inline themeHook
- `frontends/credit/src/hooks.server.ts` — uses `createThemeHook()` from `@netz/ui/utils`
- `frontends/wealth/src/hooks.server.ts` — uses `createThemeHook()` from `@netz/ui/utils`

## Proposed Solutions

### Option 1: Replace with createThemeHook

**Approach:** `import { createThemeHook } from "@netz/ui/utils"`, use `createThemeHook({ defaultTheme: "light" })`.

**Effort:** 15 minutes

**Risk:** None

## Technical Details

**Affected files:**
- `frontends/admin/src/hooks.server.ts`

## Acceptance Criteria

- [ ] Inline themeHook replaced with createThemeHook
- [ ] Theme still defaults to light in admin

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — pattern-recognition-specialist agent)
