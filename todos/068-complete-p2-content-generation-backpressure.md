---
status: pending
priority: p2
issue_id: "068"
tags: [code-review, performance, reliability]
---

# Add backpressure to content generation tasks

## Problem Statement

All 3 content trigger endpoints use `asyncio.create_task()` with no backpressure. Each spawns asyncio.to_thread() holding a sync DB connection for 30-120s (LLM generation duration). With 10 concurrent users, this exhausts the connection pool. No cancellation on shutdown — content records stuck in "draft" forever.

## Findings

- 3 content trigger endpoints all use `asyncio.create_task()` without limits
- Each task holds a sync DB connection for 30-120 seconds during LLM generation
- No upper bound on concurrent tasks — 10 concurrent users can exhaust the pool
- No graceful shutdown handling — tasks are abandoned, leaving records in "draft" status

## Proposed Solutions

Add a bounded semaphore (lazily created per CLAUDE.md rules) limiting concurrent content generation to 3-5 tasks. For production, migrate to Redis job queue.

## Technical Details

- Affected file: `content.py:86,132,194` (three trigger endpoints)
- Semaphore must be created lazily inside an async function (CLAUDE.md rule: no module-level asyncio primitives)
- Semaphore limit: 3-5 concurrent content generation tasks
- Consider adding shutdown hook to cancel pending tasks and update stuck "draft" records
- Production path: migrate to Redis job queue for proper backpressure and persistence

## Acceptance Criteria

- [ ] Bounded semaphore limits concurrent content generation tasks
- [ ] Semaphore is lazily created (not at module level)
- [ ] Requests beyond the limit return 429 or queue with feedback
- [ ] Graceful shutdown cancels pending tasks and cleans up "draft" records
- [ ] All existing tests pass
- [ ] Load test confirms connection pool is not exhausted with concurrent requests

## Work Log

(none yet)
