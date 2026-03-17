---
id: 167
status: pending
priority: p2
tags: [code-review, performance, credit]
created: 2026-03-17
---

# FRED AbortController dead code — race condition

## Problem Statement

The credit dashboard creates a `fredAbortController` and calls `.abort()` on it, but the signal is never passed to `api.get()`. This means the abort has no effect, and stale FRED search results can overwrite newer ones when a user types quickly.

## Findings

- **File:** `frontends/credit/src/routes/(team)/dashboard/+page.svelte` lines 47-70
- An `AbortController` is instantiated and `.abort()` is called on the previous controller before each new FRED search request
- However, the `signal` property is never passed to the underlying `api.get()` call, so the abort is a no-op
- On fast typing, earlier requests that resolve after later ones will overwrite the displayed results with stale data (classic race condition)

## Proposed Solutions

**Option A — Pass signal through API client:**
- Thread `fredAbortController.signal` into `api.get()` options so the browser actually cancels in-flight requests

**Option B — Sequence counter pattern:**
- Increment a counter on each request; when the response arrives, discard it if the counter has advanced past the request's sequence number
- Simpler if the API client abstraction does not support AbortSignal

## Acceptance Criteria

- [ ] FRED search requests are actually cancelled (or their results discarded) when a newer search is triggered
- [ ] Fast typing in the FRED search field always shows results for the most recent query
- [ ] No dead AbortController code remains
