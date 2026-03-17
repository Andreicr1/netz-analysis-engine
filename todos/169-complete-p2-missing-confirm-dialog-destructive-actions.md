---
id: 169
status: pending
priority: p2
tags: [code-review, quality, ux-consistency]
created: 2026-03-17
---

# Missing ConfirmDialog on 3 destructive actions

## Problem Statement

Three destructive actions across wealth and credit frontends fire immediately without a confirmation step, violating the established UX pattern of using `ConfirmDialog` with a destructive variant for irreversible or high-consequence operations.

## Findings

- **File:** `frontends/wealth/src/routes/(team)/macro/+page.svelte`
  - `rejectReview()` fires directly with no confirmation dialog
  - Rejecting a macro review is a consequential action that should require explicit confirmation

- **File:** `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`
  - `updateObligationStatus(id, "WAIVED")` fires directly
  - Waiving a portfolio obligation is irreversible and should require confirmation

- **File:** `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`
  - Deal rejection uses a generic `Dialog` but not the `ConfirmDialog` component with the `destructive` variant
  - Inconsistent with the pattern used elsewhere for destructive actions

## Proposed Solutions

1. Wrap `rejectReview()` in a `ConfirmDialog` with `confirmVariant="destructive"` and appropriate warning text
2. Wrap `updateObligationStatus(id, "WAIVED")` in a `ConfirmDialog` with `confirmVariant="destructive"`
3. Replace the generic `Dialog` on deal rejection with `ConfirmDialog` using `confirmVariant="destructive"`

## Acceptance Criteria

- [ ] All three destructive actions require explicit confirmation before executing
- [ ] Each uses the `ConfirmDialog` component with `confirmVariant="destructive"`
- [ ] Confirmation text clearly describes the consequence of the action
- [ ] Cancel button returns to previous state without side effects
