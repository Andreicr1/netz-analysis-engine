---
status: pending
priority: p1
issue_id: "165"
tags: [code-review, performance, wealth, memory-leak]
dependencies: []
---

# Backtest Polling Leaks on Navigation — No Cleanup

## Problem Statement

`frontends/wealth/src/routes/(team)/analytics/+page.svelte` `pollBacktestResult()` uses a `for` loop with `await setTimeout` to poll every 5s for up to 60s. If the user navigates away, there is no AbortController or cancellation mechanism — the loop continues making API calls against a destroyed component.

## Findings

- **Source:** performance-oracle agent
- **Evidence:** Lines 211-227 — manual for loop with no abort signal
- **Impact:** Up to 12 orphaned API calls after navigation. Multiple backtest triggers + navigation = stacked orphan loops.

## Proposed Solutions

### Option A: Use createPoller utility (Recommended)
- **Effort:** Small (15 min)
- The `createPoller` utility at `packages/ui/src/lib/utils/poller.svelte.ts` already has proper `stop()`, max duration, and `shouldStop` callbacks. Wire cleanup into `$effect` return or `onDestroy`.

### Option B: AbortController with signal check
- **Effort:** Small (15 min)
- Create a component-scoped `AbortController`, check `signal.aborted` inside the loop, abort in `onDestroy`.

## Acceptance Criteria

- [ ] Navigating away from analytics page cancels in-flight backtest polling
- [ ] No orphaned fetch calls visible in Network tab after navigation

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-17 | Created from code review | Manual polling loops need explicit cleanup — use createPoller utility |
