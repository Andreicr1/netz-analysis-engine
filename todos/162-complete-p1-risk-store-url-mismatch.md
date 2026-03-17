---
status: pending
priority: p1
issue_id: "162"
tags: [code-review, architecture, wealth, runtime-crash]
dependencies: []
---

# Risk Store URL Mismatch — CVaR Fetches Will 404

## Problem Statement

The risk store in `frontends/wealth/src/lib/stores/risk-store.svelte.ts` constructs API URLs with path segments in the wrong order. The backend has profile BEFORE `cvar`, the frontend has `cvar` BEFORE profile. All CVaR data will silently fail to load (swallowed by `r.ok ? r.json() : null`).

Additionally, the store fetches `/macro/snapshot` but no such backend endpoint exists — the backend has `/risk/macro`.

## Findings

- **Source:** architecture-strategist agent
- **Evidence:** Lines 110-118 of `risk-store.svelte.ts`
  - Frontend: `/risk/cvar/${p}/status` → Backend expects: `/risk/${p}/cvar`
  - Frontend: `/risk/cvar/${p}/history` → Backend expects: `/risk/${p}/cvar/history`
  - Frontend: `/macro/snapshot` → Backend has: `/risk/macro`
- **Impact:** Portfolio detail page, risk page, and dashboard will show no CVaR data. Store will be permanently in "loading" or "error" state.

## Proposed Solutions

### Option A: Fix URL paths (Recommended)
- **Effort:** Small (10 min)
- **Pros:** Direct fix, no API changes needed
- **Cons:** None
- **Risk:** Low

Fix in `risk-store.svelte.ts`:
- Line 110: `/risk/cvar/${p}/status` → `/risk/${p}/cvar`
- Line 113: `/risk/cvar/${p}/history` → `/risk/${p}/cvar/history`
- Line 118: `/macro/snapshot` → `/risk/macro`

## Acceptance Criteria

- [ ] CVaR data loads for all 3 profiles on portfolio detail page
- [ ] Macro indicators load on dashboard
- [ ] No 404 errors in browser console on wealth frontend

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-17 | Created from code review | Frontend-backend URL contract must be verified against actual route definitions |
