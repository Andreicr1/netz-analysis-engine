---
status: complete
priority: p2
issue_id: "014"
tags: [code-review, quality, dead-code]
dependencies: []
---

# Delete compress_to_budget dead code

## Problem Statement

`compress_to_budget()` in `memo/evidence.py` is a no-op function that returns its input unchanged. It has zero callers anywhere in the codebase. It is exported in `__init__.py` and listed in `__all__`, adding misleading API surface.

## Findings

- `evidence.py` lines 242-253: no-op function, docstring says "Legacy API — returns pack unchanged"
- Zero callers confirmed via codebase grep
- Exported in `__init__.py` `__all__` (line 88) and `__getattr__` dispatcher (line 115)
- Also has TYPE_CHECKING import (lines 52-53)
- Found by: code-simplicity-reviewer

## Proposed Solutions

### Option 1: Delete entirely

**Approach:** Remove function from evidence.py, remove from `__init__.py` `__all__`, `__getattr__`, and TYPE_CHECKING block.

**Pros:**
- Removes dead code and misleading API surface
- ~15 LOC reduction

**Cons:**
- None (zero callers)

**Effort:** 10 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/memo/evidence.py` — delete function
- `backend/vertical_engines/credit/memo/__init__.py` — remove from `__all__`, `__getattr__`, TYPE_CHECKING

## Resources

- **PR:** #19
- **Review agent:** code-simplicity-reviewer

## Acceptance Criteria

- [ ] `compress_to_budget` deleted from evidence.py
- [ ] Removed from __init__.py exports
- [ ] `make check` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified dead code during simplicity review
