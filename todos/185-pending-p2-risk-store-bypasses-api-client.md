---
status: complete
priority: p2
issue_id: "185"
tags: [code-review, architecture, wealth, frontend]
dependencies: []
---

# Wealth risk store bypasses NetzApiClient, uses raw fetch()

## Problem Statement

The risk store (`frontends/wealth/src/lib/stores/risk-store.svelte.ts`) constructs raw `fetch()` calls with manual header injection instead of using the shared `NetzApiClient`. This means no typed error handling (401 redirect, 409 conflict), no timeout protection, no retry on GET. If a 401 occurs during polling, no redirect fires.

Distinct from todo #180 (duplicate fetch guard). This finding is about the API client pattern, not concurrency.

## Findings

- Lines ~108-121: raw `fetch()` with manual `Authorization: Bearer ${token}` header
- Misses `AuthError` redirect gate, `ConflictError` handling, timeout, retry
- Same pattern in `FundDetailPanel.svelte` for DD report SSE streaming

## Proposed Solutions

### Option 1: Accept NetzApiClient instance via constructor

**Approach:** Refactor risk store to accept `createClientApiClient(getToken)` and use `api.get()`.

**Pros:**
- Gains all error handling, timeout, retry

**Cons:**
- Small refactor of store initialization

**Effort:** 2 hours

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/wealth/src/lib/stores/risk-store.svelte.ts`
- `frontends/wealth/src/lib/components/FundDetailPanel.svelte`

## Acceptance Criteria

- [ ] Risk store uses NetzApiClient for all API calls
- [ ] FundDetailPanel uses createSSEStream instead of raw fetch
- [ ] 401 during polling triggers redirect

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — architecture-strategist + pattern-recognition agents)
