---
status: pending
priority: p3
issue_id: "032"
tags: [code-review, quality, pydantic]
dependencies: []
---

## Problem Statement

The `process_pending` and `create_root_folder` routes accept bare `dict` payloads instead of Pydantic schemas. This violates the CLAUDE.md rule: "All routes use response_model= and return via model_validate(). No inline dict serialization." Additionally, `datetime.now()` is called without a timezone at line 238.

## Findings

- `process_pending` route accepts parameters without a Pydantic request model, using raw dict access instead.
- `create_root_folder` route similarly lacks a Pydantic request schema.
- Neither route specifies `response_model=` on the route decorator.
- `datetime.now()` at line 238 creates a naive datetime without timezone, which can cause comparison issues with timezone-aware datetimes elsewhere in the system.

## Proposed Solutions

1. Define `ProcessPendingRequest`:
   ```python
   class ProcessPendingRequest(BaseModel):
       limit: int = Field(default=10, ge=1, le=50)
   ```

2. Define `CreateRootFolderRequest`:
   ```python
   class CreateRootFolderRequest(BaseModel):
       name: str
   ```

3. Define corresponding response models and add `response_model=` to both route decorators.

4. Fix `datetime.now()` to `datetime.now(UTC)` (using `datetime.UTC` from Python 3.11+).

## Technical Details

- File: `backend/app/domains/credit/documents/routes/ingest.py`
- The request models should be defined in the appropriate schemas file for the documents domain.
- Response models should use `model_validate()` for serialization.
- All `datetime.now()` calls should use `datetime.now(UTC)` for consistency.

## Acceptance Criteria

- Both `process_pending` and `create_root_folder` routes use Pydantic request schemas.
- Both routes specify `response_model=` on the decorator.
- All `datetime.now()` calls include timezone (`UTC`).
- No bare dict payloads in route handlers.
