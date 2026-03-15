---
status: pending
priority: p1
issue_id: "023"
tags: [code-review, performance, async, event-loop]
dependencies: []
---

## Problem Statement

`extraction_orchestrator.py:468` uses `asyncio.run(run_pipeline(request))` per PDF in a sync loop. This creates and destroys an event loop per document, will raise `RuntimeError` if ever called from an async context, and provides no concurrency — 20 PDFs at 30s each = 10 minutes sequential.

## Findings

- `asyncio.run()` is called once per PDF inside a synchronous loop at line 468.
- Each call creates a new event loop, runs the coroutine, then tears the loop down — significant overhead per document.
- If the orchestrator is ever invoked from an async context (e.g., a FastAPI route), `asyncio.run()` will raise `RuntimeError: This event loop is already running`.
- No concurrency: documents are processed strictly sequentially.
- 20 PDFs at ~30s each = ~10 minutes total processing time with no parallelism.

## Proposed Solutions

**(a) Short-term:** Add a comment documenting the sync-only constraint and the sequential processing limitation.

**(b) Medium-term:** Convert `run_item` to async, use a single event loop with `asyncio.Semaphore(8)` + `asyncio.gather()` for batch concurrency. This would process 20 PDFs in ~90s instead of ~10 minutes.

## Technical Details

- **File:** `backend/ai_engine/extraction/extraction_orchestrator.py` line 468
- **Current pattern:** `asyncio.run(run_pipeline(request))` inside sync `for` loop
- **Target pattern:** Single event loop, `asyncio.gather(*tasks)` with `Semaphore(8)` gating

## Acceptance Criteria

- [ ] At minimum, a comment documenting the sync-only constraint
- [ ] Ideally, async conversion with semaphore-gated concurrency
- [ ] No `RuntimeError` risk if called from async context
