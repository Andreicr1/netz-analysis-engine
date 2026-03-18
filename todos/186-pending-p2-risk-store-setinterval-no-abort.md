---
status: complete
priority: p2
issue_id: "186"
tags: [code-review, performance, wealth, frontend]
dependencies: ["180"]
---

# Risk store polling uses setInterval without AbortController

## Problem Statement

The risk store fires 10 parallel fetch calls every 30 seconds via `setInterval`. No `AbortController` is used — when the user navigates away, in-flight fetches continue and update stale reactive state. `setInterval` does not wait for `fetchAll()` to complete; overlapping requests occur if the server is slow.

## Findings

- `frontends/wealth/src/lib/stores/risk-store.svelte.ts` — `setInterval` with `fetchAll()`
- 10 parallel requests per tick (3 profiles x 2 + 4 shared endpoints)
- No `AbortController` for cleanup on navigation
- `createPoller` utility already exists in `@netz/ui` with proper self-scheduling and maxDuration

## Proposed Solutions

### Option 1: Replace setInterval with createPoller

**Approach:** Use the existing `createPoller` utility which handles self-scheduling (setTimeout), abort on stop, and max duration.

**Pros:**
- Already exists, prevents overlap

**Cons:**
- Requires adapting store interface slightly

**Effort:** 1-2 hours

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/wealth/src/lib/stores/risk-store.svelte.ts`

## Acceptance Criteria

- [ ] Polling uses self-scheduling timeout (not setInterval)
- [ ] AbortController aborts in-flight requests on stopPolling()
- [ ] No overlapping fetch batches

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
