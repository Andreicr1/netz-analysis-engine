---
status: pending
priority: p3
issue_id: "109"
tags: [code-review, quality, yagni, peer-group]
dependencies: []
---

# Remove dead code: build_peer_group_key() has no production caller

## Problem Statement

`build_peer_group_key()` in `peer_matcher.py:139-146` is a convenience wrapper that returns `build_key_levels(...)[0]`. It has zero production callers — only called in one test. Classic YAGNI.

## Findings

- Code Simplicity Reviewer flagged this as dead code
- Function exists at `peer_matcher.py:139-146` (8 LOC)
- Test at `test_peer_group.py:225-227` (3 LOC)
- `match_peers()` uses `build_key_levels()` directly

## Proposed Solutions

### Option 1: Remove function and its test

**Approach:** Delete `build_peer_group_key()` and `test_build_peer_group_key_returns_level0`.

**Effort:** 5 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/peer_group/peer_matcher.py:139-146`
- `backend/tests/test_peer_group.py:225-227`

## Acceptance Criteria

- [ ] `build_peer_group_key` removed from peer_matcher.py
- [ ] Corresponding test removed
- [ ] All remaining tests pass

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (Code Simplicity Reviewer agent)
