---
status: complete
priority: p2
issue_id: "097"
tags: [code-review, performance, memory-leak, frontend]
dependencies: []
---

# SSE events array grows unbounded — memory leak for long-lived connections

## Problem Statement

In `createSSEStream()`, every parsed event is pushed to the `events` array and never trimmed. For long-lived SSE connections (IC memo generation ~3min, ingestion pipelines multi-stage), this array grows without bound. With streaming chapters or pipeline events, could reach thousands of entries.

## Findings

- `packages/ui/src/lib/utils/sse-client.svelte.ts:118` — `events.push(parsed)` with no cap
- Consumers already handle events via `onEvent` callback — the `events` array is redundant
- `createSSEWithSnapshot` variant clears its buffer but inner `createSSEStream` still accumulates

**Source:** Performance Oracle agent

## Proposed Solutions

### Option 1: Remove events accumulation, use only onEvent callback

**Effort:** 30 minutes

**Risk:** Low

### Option 2: Cap events to rolling window (e.g., last 100)

**Effort:** 15 minutes

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/sse-client.svelte.ts`

## Acceptance Criteria

- [ ] SSE events array does not grow unbounded
- [ ] Long-lived SSE connections don't cause memory issues

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Performance Oracle (ce:review PRs #37-#45)

## Resources

- **PRs:** #38 (Phase A.11)
