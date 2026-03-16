---
status: pending
priority: p3
issue_id: "090"
tags: [code-review, duplication, frontend]
dependencies: ["086"]
---

# Root layout (+layout.svelte) duplicated across credit and wealth

## Problem Statement

`frontends/credit/src/routes/+layout.svelte` and `frontends/wealth/src/routes/+layout.svelte` are nearly identical (~120 lines each). They share: branding CSS injection, session expiry monitor, conflict handler registration, AppShell/Sidebar structure, expiry warning modal. Only differences are navigation items and app name.

## Findings

- Both layouts: identical $effect blocks, identical session expiry modal, identical conflict toast
- Difference: `navItems` array and logo fallback text ("Netz Credit" vs "Netz Wealth")
- Pattern: create a shared `AppLayout` component in @netz/ui that accepts `navItems` and `appName` as props

## Proposed Solutions

### Option 1: Extract shared AppLayout to @netz/ui

**Approach:** Create `AppLayout.svelte` in @netz/ui that accepts navItems, appName, branding, token. Frontends just configure and render.

**Effort:** 2-3 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/+layout.svelte`
- `frontends/wealth/src/routes/+layout.svelte`
- `packages/ui/` — new AppLayout component

## Acceptance Criteria

- [ ] Shared layout component in @netz/ui
- [ ] Both frontends use the shared component
- [ ] Per-frontend customization via props only

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PRs:** #39, #41 (Phases B, C)
