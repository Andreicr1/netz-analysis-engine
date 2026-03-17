---
status: pending
priority: p3
issue_id: "144"
tags: [code-review, database, migration]
dependencies: []
---

# FK ondelete mismatch: migration 0013 vs ORM model

## Problem Statement

Migration `0013_benchmark_nav.py` creates the FK without `ondelete`, defaulting to `NO ACTION`. The ORM model `benchmark_nav.py` declares `ondelete="RESTRICT"`. While functionally equivalent in most cases, they differ with deferred constraints.

## Findings

- Found by: data-integrity-guardian (Issue A)
- `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` line 30: `sa.ForeignKey("allocation_blocks.block_id")` — no ondelete
- `backend/app/domains/wealth/models/benchmark_nav.py` line 23: `ondelete="RESTRICT"`

## Proposed Solutions

### Option 1: Add ondelete to migration (Recommended)

**Approach:** New migration to add `ON DELETE RESTRICT` to the FK. Or note as acceptable divergence.

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/core/db/migrations/versions/0013_benchmark_nav.py`

## Acceptance Criteria

- [ ] Migration FK matches ORM model ondelete behavior

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
