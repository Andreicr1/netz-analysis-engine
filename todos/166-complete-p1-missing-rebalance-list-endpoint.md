---
status: pending
priority: p1
issue_id: "166"
tags: [code-review, architecture, wealth, missing-endpoint, agent-native]
dependencies: []
---

# Missing GET /portfolios/{profile}/rebalance List Endpoint

## Problem Statement

`frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte` line 137 calls `api.get('/portfolios/${profile}/rebalance')` to list rebalance events, but the backend only defines `POST /{profile}/rebalance` (trigger) and `GET /{profile}/rebalance/{event_id}` (single detail). There is no list endpoint.

## Findings

- **Source:** agent-native-reviewer agent
- **Evidence:** `portfolios.py` has no `GET /{profile}/rebalance` route. Frontend will receive 405 Method Not Allowed.
- **Impact:** Rebalance events section on portfolio detail page will always show empty. Agents cannot list rebalance events.

## Proposed Solutions

### Option A: Add backend list endpoint (Recommended)
- **Effort:** Medium (30 min)
- Add `GET /{profile}/rebalance` route to `portfolios.py` returning `list[RebalanceEventRead]` with optional status filter and pagination.

### Option B: Frontend uses individual event IDs from another source
- **Effort:** Large — requires reworking the frontend to not need a list endpoint
- Not recommended.

## Acceptance Criteria

- [ ] `GET /portfolios/{profile}/rebalance` returns list of events
- [ ] Portfolio detail page shows rebalance events
- [ ] Agents can list rebalance events via API

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-17 | Created from code review | Frontend-backend contract must be verified — UI can call endpoints that don't exist yet |
