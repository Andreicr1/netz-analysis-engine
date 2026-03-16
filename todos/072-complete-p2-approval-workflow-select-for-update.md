---
status: pending
priority: p2
issue_id: "072"
tags: [code-review, security]
---

# Approval workflow missing SELECT FOR UPDATE

## Problem Statement

The content approval endpoint in `content.py` reads the content record with a plain SELECT, then updates status to "approved". Concurrent requests could both read status="review" and both succeed, creating a race condition. Per docs/solutions/wealth-macro-intelligence-suite.md, approval state transitions need `with_for_update()`.

## Findings

- Content approval endpoint reads status with a plain SELECT
- Two concurrent approval requests can both read status="review"
- Both proceed to update status to "approved", creating a race condition
- Project documentation specifies that approval state transitions require `with_for_update()`

## Proposed Solutions

Add `.with_for_update()` to the SELECT in `approve_content()` endpoint.

## Technical Details

- Affected file: `content.py:260-268`
- Add `.with_for_update()` to the SQLAlchemy select statement
- This acquires a row-level lock, ensuring only one concurrent request can read and update
- The second request will block until the first commits, then see the updated status
- Pattern: `select(ContentRecord).where(...).with_for_update()`

## Acceptance Criteria

- [ ] `approve_content()` uses `with_for_update()` on the SELECT query
- [ ] Concurrent approval requests are serialized (second sees updated status)
- [ ] Invalid state transitions return appropriate error (e.g., 409 Conflict)
- [ ] All existing tests pass
- [ ] Add test for concurrent approval race condition

## Work Log

(none yet)
