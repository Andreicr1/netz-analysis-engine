---
status: pending
priority: p3
issue_id: "101"
tags: [code-review, simplicity, yagni, frontend]
dependencies: []
---

# ~607 LOC of unused components and utilities in @netz/ui

## Problem Statement

The @netz/ui package exports 7 components and 5+ utility functions that are never imported by any frontend. This is premature abstraction / YAGNI violation that increases bundle size and maintenance surface.

## Findings

**Unused components (~343 LOC):**
- `DataTableColumnHeader.svelte` (56 LOC) — DataTable has this inline
- `DataTablePagination.svelte` (73 LOC) — DataTable has this inline
- `LanguageToggle.svelte` (42 LOC) — InvestorShell has inline toggle
- `ConnectionLost.svelte` (48 LOC) — never imported
- `Sheet.svelte` (95 LOC) — ContextPanel used instead
- `Tooltip.svelte` (29 LOC) — never imported

**Unused utilities (~264 LOC):**
- `createClerkHook` + `createRootLayoutLoader` stubs (40 LOC)
- `createSSEWithSnapshot` (93 LOC)
- `getBrandingFromCSS` + `injectBranding` (30 LOC)
- `formatDateRange`, `formatISIN`, `formatCompact` (43 LOC)
- Duplicate barrel exports in `utils/index.ts` (52 LOC)

**Source:** Code Simplicity Reviewer agent

## Proposed Solutions

### Option 1: Delete all unused code

**Effort:** 1-2 hours

**Risk:** Low — re-add when actually needed

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:** See list above

## Acceptance Criteria

- [ ] No unused components exported from @netz/ui
- [ ] No unused utility functions exported
- [ ] All remaining exports have at least one consumer

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Code Simplicity Reviewer (ce:review PRs #37-#45)

## Resources

- **PRs:** #37, #38 (Phases A, A.11)
