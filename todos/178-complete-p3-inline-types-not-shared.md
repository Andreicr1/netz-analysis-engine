---
id: 178
status: pending
priority: p3
tags: [code-review, quality, typescript]
created: 2026-03-17
---

# Inline Type Definitions Instead of Shared Imports

## Problem Statement

Several frontend pages define TypeScript types inline rather than importing them from a shared types module. This leads to type duplication, drift risk, and missed reuse opportunities.

## Findings

- `frontends/wealth/src/routes/(team)/instruments/+page.svelte` — defines `type Instrument` inline
- `frontends/wealth/src/routes/(team)/content/+page.svelte` — defines `type ContentSummary` inline
- `frontends/wealth/src/routes/(team)/macro/+page.svelte` — defines `type MacroScores` and `type MacroReview` inline
- These types mirror API response shapes that should live in `$lib/types/api.ts` (or a similar shared location)
- If the API shape changes, each inline definition must be updated independently — easy to miss one
- Other pages in the same frontend already import shared types correctly

## Proposed Solution

1. Move inline type definitions to `frontends/wealth/src/lib/types/api.ts`
2. Export them as named types
3. Replace inline definitions in each page with imports from `$lib/types/api.ts`
4. Verify that auto-generated types from `make types` (OpenAPI schema) cover these shapes; if so, import from the generated file instead

## Acceptance Criteria

- [ ] No inline `type` definitions in page components for API response shapes
- [ ] All moved types are exported from a single shared module
- [ ] Pages import types instead of defining them locally
- [ ] TypeScript compilation passes with no type errors
