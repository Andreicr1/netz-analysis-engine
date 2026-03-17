---
status: pending
priority: p2
issue_id: "104"
tags: [code-review, performance, peer-group]
dependencies: []
---

# match_peers() rebuilds keys for every instrument at every fallback level

## Problem Statement

In `peer_matcher.py:182-217`, `match_peers()` iterates through the entire universe for each fallback level, calling `build_key_levels()` for every instrument at every level. For a universe of 2000 instruments and 3 fallback levels, this computes 6000 key sets (each involving string formatting and bucket lookups). Keys could be precomputed once.

## Findings

- `peer_matcher.py:185-200` — inner loop rebuilds keys per instrument per fallback level
- `build_key_levels()` does string formatting + bucket classification (cheap individually, expensive at scale)
- For worst case (fallback to level 2): 3 * 2000 = 6000 key computations
- Keys are deterministic — same input always produces same output

## Proposed Solutions

### Option 1: Precompute keys once, group by key at each level

**Approach:** Build all keys once in a `{level: {key: [instrument_ids]}}` dict, then look up at each fallback level.

**Pros:**
- O(U) key computations instead of O(U * F)
- Lookup becomes O(1) per level

**Cons:**
- Slightly more memory (dict of lists)
- Minor refactor

**Effort:** 30 minutes

**Risk:** Low

### Option 2: Leave as-is (acceptable for current scale)

**Approach:** Current implementation is O(U * F) which is fine for U < 5000.

**Effort:** 0

**Risk:** Low (string ops are fast, this is not the bottleneck)

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/peer_group/peer_matcher.py:149-227`

## Resources

- **PR:** #48

## Acceptance Criteria

- [ ] Keys computed at most once per instrument in match_peers()
- [ ] All existing tests pass
- [ ] Performance acceptable for U=5000

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Analyzed match_peers() algorithmic complexity
- Assessed as P2 since string operations are fast and universe is typically < 5000
