---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, performance, architecture]
dependencies: []
---

# ADLSStorageClient blocks event loop with sync SDK calls

## Problem Statement
`ADLSStorageClient` declares all methods as `async def` but calls the synchronous `azure-storage-file-datalake` SDK directly. Operations like `upload_data()`, `download_file().readall()`, `get_file_properties()` will block the asyncio event loop for 20-200ms per call in production, causing request starvation.

**Why it matters:** Under 50+ concurrent users, storage operations alone can saturate the event loop. This violates the project's async-first rule (CLAUDE.md).

## Findings
- **Python reviewer:** CRITICAL — all ADLS methods block the event loop
- **Performance reviewer:** CRITICAL — confirms 20-200ms per network call blocking
- **Architecture reviewer:** HIGH — production blocker before enabling FEATURE_ADLS_ENABLED
- **Pattern reviewer:** MEDIUM — confirms sync SDK used, not the `aio` variant
- **Simplicity reviewer:** flags as a real bug, not just complexity

**Affected file:** `backend/app/services/storage_client.py` lines 129-215

## Proposed Solutions

### Option A: Switch to async Azure SDK (Recommended)
Replace `azure.storage.filedatalake.DataLakeServiceClient` with `azure.storage.filedatalake.aio.DataLakeServiceClient`. All methods naturally become `await`-able.
- **Pros:** Native async, best performance, clean code
- **Cons:** Different API surface to learn, async context manager lifecycle
- **Effort:** Medium
- **Risk:** Low

### Option B: Wrap with asyncio.to_thread()
Keep sync SDK but wrap every call with `await asyncio.to_thread(...)`.
- **Pros:** Minimal code change, quick fix
- **Cons:** Thread pool overhead, not truly async
- **Effort:** Small
- **Risk:** Low

## Recommended Action
<!-- To be filled during triage -->

## Technical Details
- **Affected files:** `backend/app/services/storage_client.py`
- **Components:** ADLSStorageClient (all 7 public methods)
- **Currently safe:** FEATURE_ADLS_ENABLED defaults to false — only blocks when enabled

## Acceptance Criteria
- [ ] All ADLSStorageClient methods are non-blocking
- [ ] Event loop remains responsive during ADLS operations
- [ ] Existing tests pass

## Work Log
| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-15 | Identified by 5/8 review agents | Consensus critical finding |

## Resources
- [azure-storage-file-datalake aio docs](https://learn.microsoft.com/en-us/python/api/azure-storage-file-datalake/azure.storage.filedatalake.aio)
- CLAUDE.md: "Async-first: All route handlers use async def"
