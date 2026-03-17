---
status: pending
priority: p2
issue_id: "112"
tags: [code-review, performance, rebalancing]
dependencies: ["110"]
---

# In-band rebalancing on deactivate_asset() blocks HTTP request

## Problem Statement

`deactivate_asset()` now synchronously runs the full rebalancing pipeline (impact scan + N optimizer solves) inside the HTTP request path. With 10 affected portfolios at 50-200ms per solve, request time = 0.5-2s. At 50 portfolios: 2.5-10s. This holds a DB connection and transaction for the entire duration.

## Findings

- **Performance Oracle**: CRITICAL-3 — will exhaust connection pool under load at ~100 portfolios
- **Architecture Strategist**: Recommends background worker via Redis pub/sub (existing SSE infra)

## Proposed Solutions

### Option A: Move rebalancing to background worker (RECOMMENDED)
- deactivate_asset() publishes REBALANCE_REQUESTED event to Redis
- Background worker picks up event, runs rebalancing asynchronously
- API returns immediately with rebalance_needed=true
- **Effort**: Medium (but infra already exists per CLAUDE.md SSE/worker pattern)
- **Risk**: Low

### Option B: Keep in-band but add timeout guard
- Set a max affected portfolios threshold (e.g., 10), skip rebalancing above that
- **Effort**: Small
- **Risk**: Medium — silent degradation at scale

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/asset_universe/universe_service.py`
- **Components**: deactivate_asset, RebalancingService

## Acceptance Criteria

- [ ] deactivate_asset() returns within 500ms regardless of portfolio count
- [ ] Rebalancing computation happens asynchronously
- [ ] Result accessible via SSE or polling

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 performance review | |
