---
status: complete
priority: p2
issue_id: "184"
tags: [code-review, architecture, admin, frontend]
dependencies: []
---

# Admin frontend missing Tailwind @source directive and @tailwindcss/vite plugin

## Problem Statement

The admin frontend's `app.css` lacks the `@source` directive pointing to `packages/ui/src/**/*.{svelte,ts}` and its `vite.config.ts` lacks the `@tailwindcss/vite` plugin. Credit and wealth both have these. Without `@source`, Tailwind may not generate utility classes for `@netz/ui` components when used in admin, causing missing styles at runtime.

## Findings

- `frontends/admin/src/app.css` — missing `@source "../../../packages/ui/src/**/*.{svelte,ts}"`
- `frontends/admin/vite.config.ts` — missing `@tailwindcss/vite` plugin
- `frontends/admin/vite.config.ts` — also missing `ssr.noExternal: ["@tanstack/svelte-table"]`
- Credit and wealth configs serve as correct reference

## Proposed Solutions

### Option 1: Align admin config with credit/wealth

**Approach:** Copy the `@source`, `@theme`, and vite plugin config from credit/wealth.

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/admin/src/app.css`
- `frontends/admin/vite.config.ts`

## Acceptance Criteria

- [ ] `@source` directive added to admin app.css
- [ ] `@tailwindcss/vite` plugin added to admin vite.config.ts
- [ ] All @netz/ui components render correctly in admin

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — architecture-strategist agent)
