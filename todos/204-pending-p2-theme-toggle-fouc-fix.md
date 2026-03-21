---
status: done
priority: p2
issue_id: "204"
tags: [bug, frontend, ui, theme]
dependencies: []
---

# Fix ThemeToggle FOUC: sync cookie + localStorage

## Problem Statement

`ThemeToggle.svelte` writes theme preference only to a cookie, but the FOUC prevention script in `app.html` reads from `localStorage`. On first load after toggling, the theme flickers because localStorage is stale.

## Proposed Solution

### Approach

In `packages/ui/src/lib/components/ThemeToggle.svelte`, add `localStorage.setItem("netz-theme", theme)` inside the `toggle()` function alongside the existing cookie write. This ensures both persistence mechanisms stay in sync.

## Technical Details

**Affected files:**
- `packages/ui/src/lib/components/ThemeToggle.svelte` — add `localStorage.setItem("netz-theme", theme)` in toggle handler

**Constraints:**
- Guard `localStorage` access with `typeof window !== 'undefined'` for SSR safety
- Do not change the FOUC script in `app.html` — it already reads localStorage correctly

## Acceptance Criteria

- [ ] `toggle()` writes to both cookie and `localStorage`
- [ ] No FOUC on page reload after toggling theme
- [ ] SSR-safe (no `localStorage` access during server render)
- [ ] `make check-all` passes
