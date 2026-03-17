---
id: 177
status: pending
priority: p3
tags: [code-review, quality, consistency]
created: 2026-03-17
---

# EmptyState Prop Inconsistency — message vs description

## Problem Statement

The `EmptyState` component is used across approximately 60 files but with inconsistent prop naming. Some pages pass a `description=` prop while others pass a `message=` prop. Both appear to work (likely due to a fallback or aliasing in the component), but the inconsistency makes the codebase harder to maintain and grep.

## Findings

- Some pages use `<EmptyState description="No items found" />`
- Other pages use `<EmptyState message="No items found" />`
- The inconsistency spans all three frontends (credit, wealth, admin)
- No single canonical prop name is documented or enforced
- This likely arose from the component evolving over time or being copied with different conventions

## Proposed Solution

1. Audit the `EmptyState` component definition in `packages/ui/` to determine the canonical prop name
2. Pick one prop name (recommend `description` as it is more descriptive) and deprecate the other
3. Update all ~60 usages across all frontends to use the canonical prop name
4. Remove the aliased/fallback prop from the component definition

## Acceptance Criteria

- [ ] All EmptyState usages use a single consistent prop name
- [ ] The EmptyState component accepts only the canonical prop (no alias)
- [ ] No TypeScript warnings or runtime regressions from the prop rename
- [ ] A quick grep confirms zero remaining usages of the deprecated prop name
