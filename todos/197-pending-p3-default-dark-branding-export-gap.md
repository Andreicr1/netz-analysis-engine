---
status: complete
priority: p3
issue_id: "197"
tags: [code-review, architecture, frontend]
dependencies: []
---

# defaultDarkBranding missing from @netz/ui/utils barrel export

## Problem Statement

`defaultDarkBranding` is exported from the main barrel (`packages/ui/src/lib/index.ts`) but missing from the `@netz/ui/utils` sub-path barrel (`packages/ui/src/lib/utils/index.ts`). The wealth frontend imports it from `@netz/ui/utils` — it works via module resolution chain but is architecturally inconsistent.

## Findings

- `packages/ui/src/lib/index.ts:103` — exports `defaultDarkBranding`
- `packages/ui/src/lib/utils/index.ts` — exports `defaultBranding` but NOT `defaultDarkBranding`
- `frontends/wealth/src/routes/+layout.server.ts:7` — `import { defaultDarkBranding } from "@netz/ui/utils"`

## Proposed Solutions

### Option 1: Add to utils barrel export

**Approach:** Add `defaultDarkBranding` alongside `defaultBranding` in utils/index.ts.

**Effort:** 5 minutes

**Risk:** None

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/index.ts`

## Acceptance Criteria

- [ ] `defaultDarkBranding` exported from `@netz/ui/utils`
- [ ] Wealth import resolves correctly

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — architecture-strategist agent)
