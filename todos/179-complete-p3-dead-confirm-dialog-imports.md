---
id: 179
status: pending
priority: p3
tags: [code-review, quality, cleanup]
created: 2026-03-17
---

# Dead ConfirmDialog Imports in 3 Files

## Problem Statement

Multiple page components import `ConfirmDialog` but never render it in their template. These dead imports add unnecessary bundle weight and clutter the code.

## Findings

- `frontends/wealth/src/routes/(team)/content/+page.svelte` — imports `ConfirmDialog` but never uses `<ConfirmDialog>` in the markup
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte` — imports `ConfirmDialog` but never renders it
- These imports likely remained after a refactor that removed the confirmation dialog from the UI flow
- Tree-shaking may not eliminate the import if the component has side effects at module level

## Proposed Solution

1. Remove the unused `ConfirmDialog` import from each affected file
2. Verify no associated state variables (e.g., `showConfirm`, `confirmOpen`) are also dead code and remove those too
3. Run `make check-all` to confirm no build errors

## Acceptance Criteria

- [ ] No unused `ConfirmDialog` imports remain in any page component
- [ ] Any orphaned state variables related to the removed dialog are also cleaned up
- [ ] All frontend builds pass without errors
