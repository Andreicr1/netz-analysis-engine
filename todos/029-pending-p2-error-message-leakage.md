---
status: pending
priority: p2
issue_id: "029"
tags: [code-review, security, error-handling]
dependencies: []
---

## Problem Statement

Raw exception `repr()` strings are stored in the warnings list and in `version.ingest_error` dict. Exception strings can contain file paths, API URLs, and credential-adjacent information. The ingest route also returns `type(e).__name__` in HTTP 500 detail, leaking internal implementation details to clients.

## Findings

- Lines 302 and 315 of `unified_pipeline.py` store raw exception representations in `PipelineStageResult.warnings`.
- `DocumentVersion.ingest_error` receives unfiltered exception data that persists in the database and may be returned to clients.
- The ingest route (line 60) returns `type(e).__name__` in the HTTP 500 detail field, exposing internal class names.
- Exception messages from third-party libraries (OpenAI, Azure, httpx) frequently contain URLs, request headers, and partial credentials.

## Proposed Solutions

1. Define an `ErrorCode` enum with generic error codes (e.g., `EXTRACTION_FAILED`, `CLASSIFICATION_FAILED`, `EMBEDDING_FAILED`).
2. Map exception types to error codes using a mapping function.
3. Never store raw exception strings in client-facing fields (`warnings`, `ingest_error`, HTTP responses).
4. Use structured error dicts: `{"error_code": "EXTRACTION_FAILED", "stage": "extraction", "timestamp": "..."}`.
5. Log the full exception server-side for debugging, but sanitize what is persisted or returned.

## Technical Details

- File: `backend/ai_engine/pipeline/unified_pipeline.py` lines 302, 315
- File: `backend/app/domains/credit/documents/routes/ingest.py` line 60
- The `warnings` field in `PipelineStageResult` should contain only sanitized, generic messages.
- `DocumentVersion.ingest_error` should use the structured error dict format.

## Acceptance Criteria

- No raw exception strings appear in `PipelineStageResult.warnings`.
- No raw exception strings appear in `DocumentVersion.ingest_error`.
- HTTP error responses use generic error codes, not exception class names.
- Full exception details are logged server-side at ERROR level for debugging.
