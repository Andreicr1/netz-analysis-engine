---
status: pending
priority: p2
issue_id: "103"
tags: [code-review, performance, peer-group]
dependencies: []
---

# compute_rankings_batch() repeats universe query for every instrument

## Problem Statement

`compute_rankings_batch()` calls `compute_rankings()` in a loop, and each call independently invokes `find_peers()` which queries the entire `instruments_universe` table. For N instruments in the same org, this performs N identical DB queries to load the full universe, plus N identical queries to load the target instrument.

## Findings

- `service.py:156-174` — sequential loop calling `compute_rankings()` per instrument
- `service.py:75-135` — `find_peers()` does 2 DB queries: target lookup + full universe load
- For 100 instruments: 200 DB queries + 100 match_peers() computations (each O(universe_size))
- All instruments are in the same org, so the universe query returns identical results each time
- `_load_peer_metrics()` also repeated per instrument (though peer groups may differ)

## Proposed Solutions

### Option 1: Cache universe in batch method

**Approach:** Load the universe once, pass it to a lower-level method that skips the DB query.

**Pros:**
- Reduces DB queries from 2N to 2 (1 universe + 1 metrics batch)
- Simple refactor

**Cons:**
- Adds a private `_find_peers_from_universe()` method

**Effort:** 1 hour

**Risk:** Low

### Option 2: Keep current design (acceptable for Sprint 2)

**Approach:** Leave as-is. Batch is not called with large lists in Sprint 2.

**Pros:**
- No code change
- Batch is currently only used in tests

**Cons:**
- Technical debt if batch becomes a hot path in Sprint 3+

**Effort:** 0

**Risk:** Low (for now)

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/peer_group/service.py:156-174`

## Resources

- **PR:** #48

## Acceptance Criteria

- [ ] Batch with 100 instruments completes in acceptable time
- [ ] Universe is queried at most once per batch call
- [ ] Tests continue to pass

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Identified repeated universe query in batch loop
- Estimated N=100 → 200 extra queries
- Assessed as P2 since batch is not yet on a hot path
