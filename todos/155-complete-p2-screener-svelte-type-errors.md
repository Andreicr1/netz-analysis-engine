---
status: complete
priority: p2
issue_id: "155"
tags: [frontend, typescript, svelte5, wealth]
dependencies: []
---

# Fix pre-existing type errors in wealth screener

## Problem Statement

`frontends/wealth/src/routes/(team)/screener/+page.svelte` had 3 errors:

1. `SectionCard` not found in `@netz/ui` — component exists but was used without required `title` prop (should be `Card`)
2. `$types` module not found — generated types missing (transient, resolves on dev server restart)
3. `{@const}` invalid placement — Svelte 5 does not allow `{@const}` as direct child of `<td>`

## Fixes Applied

1. Replaced `SectionCard` import/usage with `Card` (no title prop required)
2. `$types` — transient issue, no code change needed
3. Inlined `layerDotStatus()` calls instead of `{@const}` bindings in `<td>` (3 locations)

## Acceptance Criteria

- [x] Zero type errors on `screener/+page.svelte`
- [x] No behavioral change

## Work Log

### 2026-03-17 - Fix applied

**By:** Claude Code

**Actions:**
- `SectionCard` → `Card` in import and template
- Removed 3x `{@const}` from `<td>` elements, inlined function calls
- Pre-existing errors, fixed during PR #53 review at user request
