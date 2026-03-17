---
status: pending
priority: p3
issue_id: "146"
tags: [code-review, python, deprecation]
dependencies: []
---

# asyncio.get_event_loop() deprecated in Python 3.12+

## Problem Statement

`benchmark_ingest.py` uses `asyncio.get_event_loop()` which emits a deprecation warning in Python 3.12+ when called from a coroutine. Should use `asyncio.get_running_loop()`.

## Findings

- Found by: architecture-strategist, kieran-python-reviewer (2 agents)
- `backend/app/domains/wealth/workers/benchmark_ingest.py` line 126

## Proposed Solutions

### Option 1: Replace with get_running_loop (Recommended)

**Approach:** One-line change: `loop = asyncio.get_running_loop()`

**Effort:** 2 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/app/domains/wealth/workers/benchmark_ingest.py` line 126

## Acceptance Criteria

- [ ] No deprecation warning in Python 3.12+
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
