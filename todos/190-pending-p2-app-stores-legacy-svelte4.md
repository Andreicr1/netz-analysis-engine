---
status: complete
priority: p2
issue_id: "190"
tags: [code-review, architecture, frontend, svelte5]
dependencies: []
---

# Legacy $app/stores usage instead of Svelte 5 $app/state

## Problem Statement

Wealth and Admin frontends import from `$app/stores` (Svelte 4 legacy) while Credit correctly uses `$app/state` (Svelte 5). Both work but `$app/stores` is the legacy API. This creates a competing pattern across the codebase.

## Findings

- `frontends/credit/src/routes/+error.svelte` — `$app/state` (correct Svelte 5)
- `frontends/wealth/src/routes/+error.svelte` — `$app/stores` (legacy)
- `frontends/admin/src/routes/+error.svelte` — `$app/stores` (legacy)
- Additional: wealth `exposure/`, `model-portfolios/`; credit `dataroom/`
- Usage: `$page.status` (stores) vs `page.status` (state)

## Proposed Solutions

### Option 1: Migrate all to $app/state

**Approach:** Replace `import { page } from "$app/stores"` with `import { page } from "$app/state"` and `$page.` to `page.` in all files.

**Effort:** 30 minutes

**Risk:** Low — drop-in replacement

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/wealth/src/routes/+error.svelte`
- `frontends/admin/src/routes/+error.svelte`
- `frontends/admin/src/routes/auth/sign-in/+page.svelte`
- `frontends/wealth/src/routes/(team)/exposure/+page.svelte`
- `frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/dataroom/+page.svelte`

## Acceptance Criteria

- [ ] All `$app/stores` imports replaced with `$app/state`
- [ ] All `$page.` replaced with `page.`
- [ ] Pages render correctly

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — pattern-recognition-specialist agent)
