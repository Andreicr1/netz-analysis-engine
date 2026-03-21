---
status: done
priority: p3
issue_id: "206"
tags: [backend, cache, redis, cross-vertical]
dependencies: ["205"]
---

# Cross-vertical Redis caching (macro, correlation, leaderboard)

## Problem Statement

Several hot paths across both verticals repeatedly compute the same aggregations: credit deep review reads macro snapshot (~50 DB reads), correlation heatmap recalculates from hypertable, and screener Layer 3 recomputes leaderboard. Pre-caching these in Redis eliminates redundant computation.

## Proposed Solution

### Approach

Add Redis caching for 4 cross-vertical keys:

| Cache Key | TTL | Source | Impact |
|-----------|-----|--------|--------|
| `credit:macro_snapshot:{geography}:{date}` | 24h | `macro_data` hypertable | Deep review stage 5: 50 DB reads → 1 Redis GET |
| `macro:dashboard_widget` | Until next ingestion | `macro_data` + `macro_regional_snapshots` | Both dashboards: <10ms load |
| `correlation:{org_id}:{profile}:{date}` | 24h | Pre-computed in `risk_calc` | Correlation heatmap: instant render |
| `scoring:leaderboard:{org_id}:{profile}` | 24h | Pre-computed in `risk_calc` | Screener Layer 3: O(1) lookup |

1. **Macro snapshot cache:** Populate in `macro_ingestion` worker after ingestion. Read in credit deep review and wealth macro committee engine.
2. **Dashboard widget cache:** Populate in `macro_ingestion` worker. Read in both dashboard routes.
3. **Correlation cache:** Populate in `risk_calc` worker after computation. Read in correlation route.
4. **Leaderboard cache:** Populate in `risk_calc` worker. Read in screener route Layer 3.

All caches are best-effort: Redis miss falls back to live DB query.

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/workers/macro_ingestion.py` — add cache writes after ingestion
- `backend/app/domains/wealth/workers/risk_calc.py` — add cache writes for correlation + leaderboard
- Routes that read these values — add cache-first reads with fallback

**Constraints:**
- Never raise on Redis failure
- Use `json.dumps`/`json.loads` for serialization (consistent with codebase)
- Invalidation is worker-driven (no `KEYS *`, no keyspace notifications)
- org-scoped keys include `org_id` in key name

## Acceptance Criteria

- [ ] All 4 cache keys populated by respective workers
- [ ] Routes read from cache first, fall back to DB on miss
- [ ] Redis unavailability does not break any route
- [ ] `make check` passes (lint + typecheck + test)
