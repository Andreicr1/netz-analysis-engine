---
status: done
priority: p3
issue_id: "205"
tags: [backend, worker, wealth, cache, manager-screener]
dependencies: ["198", "201"]
---

# SEC refresh worker + Redis aggregation cache (Phase 2)

## Problem Statement

The main screener query joins 4 global tables with computed aggregates on every request. A daily worker should pre-compute per-manager aggregates into Redis, reducing screener latency to a simple `sec_managers` scan + `MGET`.

## Proposed Solution

### Approach

1. **New worker:** `backend/app/domains/wealth/workers/sec_refresh.py`
   - Advisory lock ID: **900_016** (deterministic, not `hash()`)
   - Scope: global
   - Frequency: daily (after SEC ingestion)
   - Refreshes continuous aggregates via `CALL refresh_continuous_aggregate()`
   - Computes per-manager aggregates (top sector, HHI, position count, portfolio value, turnover, drift signal, institutional holders count, last 13F date)
   - Writes to Redis keys: `screener:agg:{crd_number}` with 24h TTL (±1h jitter for stampede prevention)

2. **Update screener route** to read from Redis MGET first, fall back to live SQL for cache misses.
   - Batch reads via `MGET` (single round-trip)
   - Best-effort backfill on cache miss
   - Redis unavailable → transparent fallback to full SQL (never raise)

3. **Register worker** in worker dispatch (`workers.py`).

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/workers/sec_refresh.py` — new
- `backend/app/domains/wealth/routes/manager_screener.py` — add MGET + fallback logic
- `backend/app/domains/wealth/routes/workers.py` — register dispatch

**Constraints:**
- Advisory lock ID: 900_016 (deterministic)
- Unlock in `finally` block
- Redis key format: `screener:agg:{crd_number}` — JSON payload ~200 bytes
- TTL: `86400 ± 3600` seconds (jitter)
- Total Redis memory: ~4MB for 5000 managers
- Never raise on Redis failure — always fall back to SQL

## Acceptance Criteria

- [ ] Worker uses `pg_try_advisory_lock(900016)` with unlock in `finally`
- [ ] Continuous aggregates refreshed before computing cache
- [ ] Redis keys populated with correct JSON structure and TTL
- [ ] Screener route uses MGET for cached managers, falls back for misses
- [ ] Redis unavailability does not break screener (transparent fallback)
- [ ] `make check` passes (lint + typecheck + test)
