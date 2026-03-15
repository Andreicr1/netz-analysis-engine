---
status: pending
priority: p1
issue_id: "025"
tags: [code-review, security, data-integrity]
dependencies: []
---

## Problem Statement

`unified_pipeline.py:379` uses `fund_id=request.fund_id or request.org_id` as fallback. `fund_id` and `org_id` are semantically different — a fund belongs to an org. When `fund_id` is `None` (batch), `org_id` is used as `fund_id` in the search index, which would return cross-fund results for any query filtered by that `org_id` as if it were a fund.

## Findings

- Line 379 uses `fund_id=request.fund_id or request.org_id` — silently substituting org_id when fund_id is missing.
- `fund_id` and `org_id` are semantically distinct: an organization can have multiple funds.
- Using `org_id` as `fund_id` means all documents without a fund_id get the same "fund" identifier.
- Search queries filtered by `fund_id` would incorrectly return documents from all funds belonging to that org.
- This is a data integrity issue that could surface confidential cross-fund information.

## Proposed Solutions

1. Make `fund_id` required for indexing — add explicit check before indexing stage:
   ```python
   if not request.fund_id:
       raise ValueError("fund_id required for search indexing")
   ```
2. Or pass `fund_id=None` and let `build_search_document` handle it (skip fund-level indexing when fund_id is absent).

## Technical Details

- **File:** `backend/ai_engine/pipeline/unified_pipeline.py` line 379
- **Current:** `fund_id=request.fund_id or request.org_id`
- **Risk:** Cross-fund data leakage in search results
- Related to issue #024 (nil UUID org_id in batch)

## Acceptance Criteria

- [ ] `fund_id` is never silently substituted with `org_id`
- [ ] Clear error raised if `fund_id` not available at indexing time
- [ ] Search index does not contain documents where `fund_id` equals an `org_id`
