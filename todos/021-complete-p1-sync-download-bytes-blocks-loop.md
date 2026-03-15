---
status: pending
priority: p1
issue_id: "021"
tags: [code-review, performance, async]
dependencies: []
---

## Problem Statement

`unified_pipeline.py:127` calls `download_bytes()` synchronously inside `async def process()`. For large PDFs (up to 100MB), this blocks the event loop for seconds. The embed and upsert calls are correctly wrapped in `asyncio.to_thread()`, but download is not. Known pattern from docs/solutions: "No sync I/O inside async def without asyncio.to_thread()".

## Findings

- `download_bytes()` is a synchronous call at line 127 inside an `async def` function.
- Large PDFs (up to 100MB) will block the event loop for the entire download duration.
- Other async operations (embed, upsert) are already correctly wrapped in `asyncio.to_thread()`, making this an inconsistency.
- The `pdf_bytes` buffer is not explicitly released after OCR, holding potentially 100MB in memory longer than necessary.

## Proposed Solutions

1. Wrap the call in `asyncio.to_thread`: `pdf_bytes = await asyncio.to_thread(download_bytes, blob_uri=request.blob_uri)`
2. Add `del pdf_bytes` after the OCR stage to release memory immediately.

## Technical Details

- **File:** `backend/ai_engine/pipeline/unified_pipeline.py` line 127
- **Current:** `pdf_bytes = download_bytes(blob_uri=request.blob_uri)`
- **Fixed:** `pdf_bytes = await asyncio.to_thread(download_bytes, blob_uri=request.blob_uri)`
- Add `del pdf_bytes` after OCR processing is complete.

## Acceptance Criteria

- [ ] `download_bytes` wrapped in `asyncio.to_thread()`
- [ ] `del pdf_bytes` added after OCR stage
- [ ] Event loop no longer blocked during PDF download
