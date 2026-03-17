---
status: pending
priority: p2
issue_id: "141"
tags: [code-review, performance, database]
dependencies: []
---

# Strategy drift alert upsert: per-row INSERT instead of batch

## Problem Statement

The drift scan route inserts alerts one at a time in a Python loop (lines 260-276). For 200 instruments, this executes 200 individual round-trips to PostgreSQL.

## Findings

- Found by: performance-oracle (OPT-4)
- `backend/app/domains/wealth/routes/strategy_drift.py` lines 260-276
- Each iteration builds and executes a separate `pg_insert().on_conflict_do_update()` statement

## Proposed Solutions

### Option 1: Batch insert with list of values

**Approach:** Use `pg_insert(StrategyDriftAlert).values(alert_dicts)` with a single on_conflict clause. If partial index constraint creates issues, chunk into groups of 50-100.

**Pros:** 200 round-trips → 1-4 round-trips

**Cons:** Need to verify on_conflict works with batch values and partial unique index

**Effort:** 30 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/routes/strategy_drift.py` lines 258-276

## Acceptance Criteria

- [ ] Single batch INSERT instead of per-row loop
- [ ] on_conflict_do_update still works correctly
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
