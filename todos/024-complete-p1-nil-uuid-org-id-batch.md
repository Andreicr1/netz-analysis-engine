---
status: pending
priority: p1
issue_id: "024"
tags: [code-review, security, tenant-isolation]
dependencies: []
---

## Problem Statement

`extraction_orchestrator.py:458` uses `org_id=uuid.UUID(int=0)` (nil UUID) for batch `IngestRequest`. This violates the `IngestRequest` docstring: "org_id MUST be derived from actor.organization_id (JWT), NEVER from request body." The nil UUID flows to the search index as a `fund_id` fallback (line 379), polluting search with tenant-less documents.

## Findings

- Line 458 constructs `IngestRequest` with `org_id=uuid.UUID(int=0)` — the nil UUID `00000000-0000-0000-0000-000000000000`.
- This violates the explicit contract documented in `IngestRequest`'s docstring.
- The nil UUID propagates to `build_search_document()` at line 379 where it becomes `fund_id` via the `fund_id or org_id` fallback.
- Documents indexed with nil UUID are not tenant-isolated — they exist outside the RLS boundary.
- Any search query could potentially surface these orphaned documents.

## Proposed Solutions

1. Resolve real `org_id` from blob context or container metadata instead of using nil UUID.
2. Add `__post_init__` validation to `IngestRequest` that rejects nil UUID for non-batch sources.
3. Fix `fund_id`/`org_id` fallback in `unified_pipeline.py` line 379 — require `fund_id` explicitly or raise.

## Technical Details

- **Files:**
  - `backend/ai_engine/extraction/extraction_orchestrator.py` line 458
  - `backend/ai_engine/pipeline/unified_pipeline.py` line 379
- Nil UUID: `uuid.UUID(int=0)` = `00000000-0000-0000-0000-000000000000`
- Related to issue #025 (fund_id/org_id fallback)

## Acceptance Criteria

- [ ] No nil UUID in search index
- [ ] `fund_id` always set explicitly when reaching the indexing stage
- [ ] `IngestRequest` validates that `org_id` is not nil UUID (or documents the exception for batch)
