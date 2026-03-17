---
id: 180
status: complete
priority: p3
tags: [code-review, performance, wealth]
created: 2026-03-17
---

# Risk Store Fetch Guard — Prevent Duplicate Concurrent Requests

## Problem Statement

The risk store in the Wealth frontend can issue overlapping fetch requests when the layout calls `fetchAll()` followed by `startPolling()`. If the initial fetch is slow, the first polling tick fires while the fetch is still in flight, causing duplicate concurrent API calls.

## Findings

- **File:** `frontends/wealth/src/lib/stores/risk-store.svelte.ts`
- The layout component calls `fetchAll()` to load initial data, then immediately calls `startPolling()` to begin periodic refreshes
- `fetchAll()` is async but there is no guard to prevent re-entry
- If network latency is high, the polling interval can elapse before `fetchAll()` completes, triggering a second concurrent fetch
- This results in duplicate API requests, wasted bandwidth, and potential race conditions where stale data overwrites fresh data

## Proposed Solution

1. Add a `let fetching = false` guard variable inside the store
2. At the start of `fetchAll()`, check if `fetching` is true — if so, return early
3. Set `fetching = true` at the start and `fetching = false` in a `finally` block
4. Alternatively, the polling logic can check the guard before scheduling a new fetch

```typescript
let fetching = false;

async function fetchAll() {
  if (fetching) return;
  fetching = true;
  try {
    // ... existing fetch logic
  } finally {
    fetching = false;
  }
}
```

## Acceptance Criteria

- [ ] Concurrent calls to `fetchAll()` are prevented by a guard
- [ ] Polling does not trigger a fetch while one is already in flight
- [ ] The guard is properly released in error/exception paths (finally block)
- [ ] No functional regression in risk data loading or polling behavior
