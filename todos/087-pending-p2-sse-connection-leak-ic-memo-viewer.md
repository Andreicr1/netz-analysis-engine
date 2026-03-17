---
status: pending
priority: p2
issue_id: "087"
tags: [code-review, performance, memory-leak, frontend]
dependencies: []
---

# SSE connection never cleaned up in ICMemoViewer

## Problem Statement

`ICMemoViewer.svelte:42-56` creates an SSE connection via `createSSEStream()` but never calls `sse.disconnect()` on component unmount. The SSE connection persists after navigating away, consuming a server connection slot and potentially causing errors when events arrive for a destroyed component.

## Findings

- `frontends/credit/src/lib/components/ICMemoViewer.svelte:42-56` — SSE created in `generateMemo()` callback
- No `$effect()` cleanup or `onDestroy` to call `sse.disconnect()`
- The `sse` variable is local to the callback — not accessible for cleanup
- Each memo generation creates a new SSE connection that's never closed
- The SSE client (`sse-client.svelte.ts`) has proper `disconnect()` method, it's just never called

## Proposed Solutions

### Option 1: Store SSE reference in component state, clean up with $effect

**Approach:** Store `sse` in `$state`, add `$effect` that returns cleanup function calling `disconnect()`.

**Effort:** 30 minutes

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `frontends/credit/src/lib/components/ICMemoViewer.svelte:42-56`

## Acceptance Criteria

- [ ] SSE connection disconnected on component unmount
- [ ] No leaked connections after navigating away from IC memo page

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

## Resources

- **PR:** #39 (Phase B)
