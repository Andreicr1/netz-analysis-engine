---
status: complete
priority: p1
issue_id: "094"
tags: [code-review, bug, frontend, credit]
dependencies: []
---

# EmptyState uses wrong prop name — all empty states in credit show no description

## Problem Statement

The `EmptyState` component in `@netz/ui` accepts a `message` prop, but the **credit** frontend consistently passes `description=` instead. Since `description` is not a defined prop, Svelte silently ignores it — resulting in all EmptyState components across the entire credit frontend rendering without any description text. This is a **functional bug** affecting ~15 component usages.

The **wealth** frontend correctly uses `message=` everywhere.

## Findings

- `packages/ui/src/lib/components/EmptyState.svelte` — accepts `message` prop
- Credit frontend uses `description=` in: dashboard, funds, documents, pipeline, portfolio, reporting, investor pages (~15 instances)
- Wealth frontend correctly uses `message=` everywhere
- Impact: Every empty state in the credit frontend shows only the title — no description text renders

**Source:** Pattern Recognition agent

## Proposed Solutions

### Option 1: Rename all `description=` to `message=` in credit frontend

**Effort:** 30 minutes (find/replace)

**Risk:** Low

### Option 2: Add `description` as an alias prop in EmptyState component

**Effort:** 10 minutes

**Risk:** Low — but masks the inconsistency

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/(team)/dashboard/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`
- `frontends/credit/src/routes/(investor)/*.svelte` (multiple)

## Acceptance Criteria

- [ ] All EmptyState usages pass `message=` (or component accepts both)
- [ ] Description text renders in all credit frontend empty states

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Pattern Recognition agent (ce:review PRs #37-#45)

## Resources

- **PRs:** #39 (Phase B)
