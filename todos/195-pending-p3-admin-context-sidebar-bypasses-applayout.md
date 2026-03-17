---
status: complete
priority: p3
issue_id: "195"
tags: [code-review, architecture, admin, frontend]
dependencies: []
---

# Admin ContextSidebar bypasses AppLayout prop

## Problem Statement

Admin manages ContextSidebar directly in `(admin)/tenants/[orgId]/+layout.svelte` by rendering `<ContextSidebar>` manually in a flex container, bypassing AppLayout's `contextNav` prop. Credit uses the correct pattern via `context-nav.svelte.ts` module with `initContextNav()`/`useContextNav()`.

## Findings

- `frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.svelte` — manual ContextSidebar rendering
- `frontends/credit/src/lib/state/context-nav.svelte.ts` — correct pattern via Svelte context
- Admin's approach creates layout-within-layout that won't scale to more detail views

## Proposed Solutions

### Option 1: Adopt credit's context-nav pattern

**Approach:** Create `context-nav.svelte.ts` in admin, pass `contextNav` via AppLayout prop.

**Effort:** 2 hours

**Risk:** Low

## Technical Details

**Affected files:**
- `frontends/admin/src/routes/(admin)/tenants/[orgId]/+layout.svelte`
- `frontends/admin/src/lib/state/context-nav.svelte.ts` (new)
- `frontends/admin/src/routes/+layout.svelte` (add contextNav prop)

## Acceptance Criteria

- [ ] ContextSidebar rendered via AppLayout, not manually
- [ ] Navigation within tenant detail works correctly

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — pattern-recognition-specialist agent)
