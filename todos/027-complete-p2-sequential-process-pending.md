---
status: pending
priority: p2
issue_id: "027"
tags: [code-review, performance, async]
dependencies: []
---

## Problem Statement

`ingest.py` process_pending route processes documents sequentially in a for loop. With limit=50 and 30s per doc, this results in a 25-minute HTTP request. This will timeout on reverse proxies and blocks the uvicorn worker for the entire duration.

Additionally, there is an N+1 query issue: a separate select per version for each Document instead of using eager loading.

## Findings

- The `process_pending` route iterates over documents one-by-one in a `for` loop, awaiting each document's full pipeline processing before moving to the next.
- With the maximum limit of 50 documents and ~30 seconds per document, the total request time can reach ~25 minutes.
- Reverse proxies (nginx, Azure Front Door) will timeout long before this completes.
- The single uvicorn worker thread is blocked for the entire duration.
- Each iteration issues a separate SELECT to fetch the DocumentVersion for each Document, creating an N+1 query pattern.

## Proposed Solutions

**Short-term (a):** Add `asyncio.Semaphore(3)` with `asyncio.gather()` for bounded parallel processing. This reduces wall-clock time by ~3x while preventing resource exhaustion.

**Long-term (b):** Move document processing to a background job with Redis dispatch. The HTTP route should only enqueue the work and return a job_id. Progress is reported via SSE.

**N+1 fix:** Add `selectinload(Document.versions)` to the query that fetches pending documents.

## Technical Details

- File: `backend/app/domains/credit/documents/routes/ingest.py` lines 189-256
- The semaphore must be created inside the async function (not at module level) per CLAUDE.md rules.
- `asyncio.gather(*tasks, return_exceptions=True)` should be used to prevent one failure from cancelling all others.

## Acceptance Criteria

- Documents are processed concurrently with bounded parallelism (semaphore).
- N+1 query is eliminated via eager loading.
- Total request time scales as `ceil(n / concurrency) * per_doc_time` instead of `n * per_doc_time`.
