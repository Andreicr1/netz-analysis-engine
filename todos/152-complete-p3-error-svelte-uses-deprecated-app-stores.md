---
status: complete
priority: p3
issue_id: "152"
tags: [code-review, frontend, svelte5, consistency]
dependencies: []
---

# `+error.svelte` uses deprecated `$app/stores` instead of `$app/state`

## Problem Statement

`frontends/credit/src/routes/+error.svelte` imports `{ page } from "$app/stores"` and uses `$page.status`. The `[fundId]/+layout.svelte` was upgraded to use `{ page } from "$app/state"` (Svelte 5 runes-based) in the same PR. This inconsistency is cosmetic — both work in Svelte 5 — but `$app/stores` is positioned for eventual deprecation.

## Findings

- `+error.svelte:5`: `import { page } from "$app/stores"` — uses reactive store syntax (`$page.status`)
- `[fundId]/+layout.svelte:5`: `import { page } from "$app/state"` — uses runes syntax (`page.url.pathname`)
- Both work correctly in Svelte 5; `$app/stores` is not yet removed
- The error page wasn't a focus of this PR's Svelte 5 cleanup

## Proposed Solutions

### Option 1: Update to `$app/state`

**Approach:** Change import to `$app/state`, replace `$page.status` with `page.status`, `$page.error` with `page.error`.

**Effort:** 5 minutes

**Risk:** Low

## Recommended Action

*To be filled during triage.*

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/+error.svelte`

## Resources

- **PR:** #53

## Acceptance Criteria

- [ ] `+error.svelte` uses `import { page } from "$app/state"`
- [ ] All `$page.` references replaced with `page.`
- [ ] `pnpm --filter netz-credit-intelligence check` passes

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code

**Actions:**
- Identified inconsistency during PR #53 deep review
- Confirmed both patterns work in Svelte 5 — cosmetic only
