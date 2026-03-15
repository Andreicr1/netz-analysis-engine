---
status: pending
priority: p2
issue_id: "004"
tags: [code-review, security]
dependencies: []
---

# Raw exception details leak via SSE events and database

## Problem Statement
`ingestion_worker.py` stores `str(e)` in `ingest_error["detail"]` and publishes it via SSE. Python exceptions can contain file paths, connection strings, and internal module paths.

## Findings
- **Security reviewer:** MEDIUM (M2)
- **Performance reviewer:** also flagged the `except Exception: failed += 1` in the batch loop that silently discards exceptions

## Proposed Solutions
Log full exception server-side, send sanitized classification to client:
```python
logger.exception("Ingestion failed for version %s", version.id)
version.ingest_error = {"reason": "processing_error"}
await _emit(job_id, "error", {"reason": "processing_error"})
```

## Acceptance Criteria
- [ ] No raw exception strings in SSE events or DB records
- [ ] Full exception logged server-side for debugging
- [ ] Batch loop logs individual failures instead of silently discarding
