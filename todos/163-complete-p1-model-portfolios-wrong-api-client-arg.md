---
status: pending
priority: p1
issue_id: "163"
tags: [code-review, architecture, wealth, runtime-crash]
dependencies: []
---

# Model Portfolios Wrong API Client Argument — Runtime Crash

## Problem Statement

`frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte` line 51 passes `data.token` (a string) to `createClientApiClient()` which expects `getToken: () => Promise<string>` (a function). This will crash at runtime when the API client tries to `await this.getToken()` on a string value.

## Findings

- **Source:** architecture-strategist agent
- **Evidence:** Line 51: `const api = createClientApiClient(token)` where `token = data.token` (string)
- **Impact:** Track-record loading for model portfolios will throw TypeError. Backtest, allocate, and rebalance buttons will also crash.

## Proposed Solutions

### Option A: Use getToken from context (Recommended)
- **Effort:** Small (5 min)
- Change line 51 from `createClientApiClient(token)` to `createClientApiClient(getToken)` — the `getToken` function is already available from context (line 17 pattern used by all other wealth pages).

## Acceptance Criteria

- [ ] Model portfolio track-record loads without error
- [ ] Backtest, allocate, rebalance buttons work

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-17 | Created from code review | Copy-paste from admin pattern (uses data.token) into wealth context (uses getToken) |
