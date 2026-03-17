---
status: pending
priority: p2
issue_id: "142"
tags: [code-review, performance, database]
dependencies: []
---

# Benchmark ingest staleness check is N+1

## Problem Statement

The staleness check in `benchmark_ingest.py` runs one query per block in a loop. With 20 allocation blocks, that's 20 sequential queries when a single GROUP BY query would suffice.

## Findings

- Found by: performance-oracle (CRITICAL-3)
- `backend/app/domains/wealth/workers/benchmark_ingest.py` lines 289-303
- Each iteration: `select(BenchmarkNav.nav_date).where(block_id == X).order_by(desc).limit(1)`

## Proposed Solutions

### Option 1: Single GROUP BY query (Recommended)

**Approach:** `SELECT block_id, MAX(nav_date) FROM benchmark_nav WHERE block_id IN (...) GROUP BY block_id`

**Pros:** 20 queries → 1 query

**Cons:** None

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/workers/benchmark_ingest.py` lines 289-303

## Acceptance Criteria

- [ ] Single query replaces N individual queries
- [ ] Staleness detection still correct
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
