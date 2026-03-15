---
status: pending
priority: p1
issue_id: "022"
tags: [code-review, type-safety, python]
dependencies: []
---

## Problem Statement

`unified_pipeline.py:88` and `_audit()` use `db: Any | None` which erases all type safety. Should be `AsyncSession | None` using a `TYPE_CHECKING` guard.

## Findings

- Lines 54 and 88 in `unified_pipeline.py` declare `db` parameter as `Any | None`.
- This erases all type checking — mypy cannot verify correct usage of the session object.
- The file already has `from __future__ import annotations`, so string annotations are available.
- A `TYPE_CHECKING` guard import is the standard pattern for avoiding runtime import of heavy modules while preserving type safety.

## Proposed Solutions

Add a `TYPE_CHECKING` guard import and change the type annotation:

```python
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
```

Then change `db: Any | None` to `db: AsyncSession | None` at lines 54 and 88.

## Technical Details

- **File:** `backend/ai_engine/pipeline/unified_pipeline.py` lines 54, 88
- `from __future__ import annotations` is already present (string annotations at runtime).
- `TYPE_CHECKING` guard ensures `AsyncSession` is only imported during static analysis, not at runtime.

## Acceptance Criteria

- [ ] `db` parameter typed as `AsyncSession | None` (not `Any | None`)
- [ ] `TYPE_CHECKING` guard import added for `AsyncSession`
- [ ] mypy recognizes the type and catches incorrect session usage
