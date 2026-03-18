---
status: complete
priority: p2
issue_id: "183"
tags: [code-review, performance, frontend]
dependencies: []
---

# SSE registry not enforced in createSSEStream

## Problem Statement

The SSE registry (`packages/ui/src/lib/utils/sse-registry.svelte.ts`) exposes `canOpenSSE()`, `registerSSE()`, and `unregisterSSE()` to enforce a 4-connection-per-tab limit. However, `createSSEStream()` in `sse-client.svelte.ts` never calls any of these functions. The 4-connection limit is completely unenforced.

## Findings

- `packages/ui/src/lib/utils/sse-registry.svelte.ts` — registry exists with correct logic
- `packages/ui/src/lib/utils/sse-client.svelte.ts` — `createSSEStream()` never calls registry
- Consumers: dashboard SSE, ingestion progress, IC memo streaming, worker log feed — all bypass registry
- HTTP/1.1 has 6-per-origin limit; exhausting it blocks API calls entirely

## Proposed Solutions

### Option 1: Integrate registry into createSSEStream

**Approach:** Call `registerSSE()` in `connect()` and `unregisterSSE()` in `disconnect()`. If `registerSSE()` returns false, queue or fall back to polling.

**Pros:**
- 10-line change, centralized enforcement
- Prevents connection exhaustion

**Cons:**
- Consumers exceeding limit need fallback behavior

**Effort:** 1 hour

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `packages/ui/src/lib/utils/sse-client.svelte.ts`
- `packages/ui/src/lib/utils/sse-registry.svelte.ts`

## Acceptance Criteria

- [ ] `createSSEStream().connect()` calls `registerSSE()` before opening
- [ ] `disconnect()` calls `unregisterSSE()`
- [ ] Connection refused gracefully when at limit
- [ ] Existing SSE consumers still work

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
