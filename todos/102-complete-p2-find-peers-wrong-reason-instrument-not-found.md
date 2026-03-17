---
status: pending
priority: p2
issue_id: "102"
tags: [code-review, quality, peer-group]
dependencies: []
---

# find_peers() returns misleading reason when instrument not found

## Problem Statement

When `find_peers()` cannot find the target instrument in the database (line 98-102 of `service.py`), it returns `reason="no_block_assigned"` which is factually incorrect. The instrument may not exist, may belong to a different org, or may be inactive. This misleads callers and makes debugging harder.

## Findings

- `service.py:98-102` — `target is None` could mean: instrument doesn't exist, wrong org_id, or instrument is inactive
- The reason `"no_block_assigned"` is only correct for `service.py:104-108` (instrument exists but has no block)
- `PeerGroupNotFound.reason` is documented as: `"insufficient_peers" | "no_block_assigned" | "no_metrics"` — no `"instrument_not_found"` variant exists
- Downstream consumers (like `peer_injection.py`) log this reason for debugging

## Proposed Solutions

### Option 1: Add "instrument_not_found" reason

**Approach:** Return `reason="instrument_not_found"` when `target is None`.

**Pros:**
- Accurate error reporting
- Easy to debug

**Cons:**
- Adds a new reason variant (minor)

**Effort:** 15 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/peer_group/service.py:98-102`
- `backend/vertical_engines/wealth/peer_group/models.py:54` (update reason docstring)

## Resources

- **PR:** #48

## Acceptance Criteria

- [ ] `find_peers()` returns `reason="instrument_not_found"` when instrument not in DB
- [ ] `reason="no_block_assigned"` only used when instrument exists but has no block
- [ ] Tests updated to cover both cases

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Identified misleading error reason in find_peers()
- Traced impact to peer_injection.py logging
