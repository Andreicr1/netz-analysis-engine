---
status: pending
priority: p1
issue_id: "164"
tags: [code-review, performance, wealth, ux-bug]
dependencies: []
---

# Content Polling Fires Only Once — "Generating..." Appears Stuck

## Problem Statement

`frontends/wealth/src/routes/(team)/content/+page.svelte` uses `setTimeout` inside `$effect`, but after the first 10s tick fires and `invalidateAll()` runs, the `$effect` only re-runs if its dependencies change. If `hasGenerating` is still `true` (items still generating), Svelte 5 will NOT re-run the `$effect` because the dependency value did not change.

## Findings

- **Source:** performance-oracle agent
- **Evidence:** Lines 112-121 — `$effect` with `setTimeout` (single fire), not `setInterval`
- **Impact:** Content items show "Generating..." indefinitely after the first 10s poll. Users must manually refresh.

## Proposed Solutions

### Option A: Use incrementing counter to force $effect re-trigger (Recommended)
- **Effort:** Small (10 min)
- Add `let pollTick = $state(0)` and read it inside the `$effect`. After `invalidateAll()`, increment `pollTick++` to force the effect to re-run.

### Option B: Use setInterval instead of setTimeout
- **Effort:** Small (10 min)
- Replace `setTimeout` with `setInterval`. Cleanup via `clearInterval` in return.

## Acceptance Criteria

- [ ] Content list auto-refreshes every 10s while any item has status "generating"
- [ ] Polling stops when all items have terminal status

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-17 | Created from code review | Svelte 5 $effect only re-runs when dependency VALUES change, not just when code runs |
