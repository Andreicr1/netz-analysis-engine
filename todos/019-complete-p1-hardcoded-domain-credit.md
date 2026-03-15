---
status: pending
priority: p1
issue_id: "019"
tags: [code-review, architecture, multi-vertical]
dependencies: []
---

## Problem Statement

`unified_pipeline.py:380` hardcodes `domain="credit"` in `build_search_document()`. Should use `request.vertical`. When the wealth vertical is onboarded, all wealth documents will be tagged as credit in the search index.

## Findings

- `build_search_document()` call at line 380 passes `domain="credit"` as a literal string.
- The `IngestRequest` already carries a `vertical` field that holds the correct value.
- Every document indexed through the unified pipeline will be labeled as credit regardless of its actual vertical.
- This will cause incorrect search results when wealth (or any future vertical) documents are ingested.

## Proposed Solutions

Replace `domain="credit"` with `domain=request.vertical` (1-line fix).

## Technical Details

- **File:** `backend/ai_engine/pipeline/unified_pipeline.py` line 380
- **Current code:** `domain="credit"`
- **Fixed code:** `domain=request.vertical`

## Acceptance Criteria

- [ ] `domain` field in search documents matches `IngestRequest.vertical`
- [ ] No hardcoded `"credit"` string in `build_search_document()` call
- [ ] Existing tests updated to verify domain is derived from request
