---
status: complete
priority: p3
issue_id: "194"
tags: [code-review, performance, wealth, frontend]
dependencies: []
---

# Screener table renders all results without virtualization

## Problem Statement

The screener page renders `filteredResults` in a plain `{#each}` loop. With 200-500+ instruments, all rows render to the DOM simultaneously. Each row has 9 columns with reactive StatusBadge components and click handlers. `@tanstack/svelte-virtual` is already in devDependencies but unused.

## Findings

- `frontends/wealth/src/routes/(team)/screener/+page.svelte` — plain `{#each}` for results
- 9 columns per row, each with event handlers
- At 500+ instruments: 4500+ DOM nodes in table body
- `@tanstack/svelte-virtual` already available in `@netz/ui`

## Proposed Solutions

### Option 1: Virtualize with @tanstack/svelte-virtual

**Approach:** Use TanStack Virtual to render only visible rows.

**Effort:** 2-3 hours

**Risk:** Low

## Technical Details

**Affected files:**
- `frontends/wealth/src/routes/(team)/screener/+page.svelte`

## Acceptance Criteria

- [ ] Only visible rows rendered to DOM
- [ ] Scrolling performance smooth at 500+ items
- [ ] Click handlers and detail panel still work

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
