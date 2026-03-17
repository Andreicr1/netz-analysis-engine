---
status: pending
priority: p1
issue_id: "110"
tags: [code-review, performance, architecture, rebalancing]
dependencies: []
---

# Asyncio bridge in weight_proposer.py will crash under async callers

## Problem Statement

`weight_proposer.py` (lines 148-167) uses a fragile async-to-sync bridge pattern that will fail when called from any async context (FastAPI route handler via `asyncio.to_thread`):

```python
try:
    opt_result = asyncio.get_event_loop().run_until_complete(optimize_portfolio(...))
except RuntimeError:
    opt_result = asyncio.run(optimize_portfolio(...))
```

- `get_event_loop().run_until_complete()` fails if a loop is already running
- `asyncio.run()` also fails inside a running loop on Python 3.10+
- This code only works in tests (no running loop)

Every review agent (6 of 7) flagged this as the highest-severity issue.

## Findings

- **Performance Oracle**: CRITICAL-2 — deadlock risk under load, event loop nesting
- **Architecture Strategist**: Must fix before merge — async-first rule violation
- **Code Simplicity**: Most problematic code in the PR
- **Pattern Recognition**: HIGH severity — peer_matcher has no async calls, this introduces fragile bridge
- **Agent-Native**: Fragile — only works from sync context
- **Known Pattern**: docs/solutions/runtime-errors/ documents thread-safety issues in quant_engine

## Proposed Solutions

### Option A: Replace optimizer with proportional redistribution (RECOMMENDED)
- **Pros**: Eliminates asyncio bridge entirely, removes numpy import, faster (~1ms vs 50-200ms), honest about the fake covariance data
- **Cons**: Less "correct" than optimizer, but identity covariance makes optimizer meaningless anyway
- **Effort**: Small (rewrite ~40 lines in weight_proposer.py)
- **Risk**: Low

### Option B: Make propose_weights async
- **Pros**: Clean async chain, aligns with async-first rule
- **Cons**: Propagates async through service.py and universe_service.py, larger change surface
- **Effort**: Medium
- **Risk**: Low

### Option C: Use asyncio.run() unconditionally
- **Pros**: Minimal change — works when called from sync thread (via asyncio.to_thread)
- **Cons**: Still fails if ever called directly from async context, masks the real issue
- **Effort**: Small (delete try/except, keep asyncio.run())
- **Risk**: Medium — fragile assumption about call context

## Recommended Action

Option A — the identity covariance matrix makes the optimizer call meaningless anyway. Replace with proportional redistribution within allocation bounds.

## Technical Details

- **Affected files**: `backend/vertical_engines/wealth/rebalancing/weight_proposer.py`
- **Components**: RebalancingService, weight_proposer
- **Database changes**: None

## Acceptance Criteria

- [ ] No `asyncio.get_event_loop()` or `asyncio.run()` in weight_proposer.py
- [ ] propose_weights works when called from async route handler
- [ ] Tests pass without mocking the async bridge
- [ ] Weight proposals produce reasonable redistributions

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-16 | Created from PR #49 code review | 6/7 agents flagged this as highest priority |

## Resources

- PR: #49
- CLAUDE.md: "No module-level asyncio primitives" rule
- docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md
