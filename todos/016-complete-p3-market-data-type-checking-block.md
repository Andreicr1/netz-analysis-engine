---
status: complete
priority: p3
issue_id: "016"
tags: [code-review, quality, typing]
dependencies: []
---

# Add TYPE_CHECKING block to market_data/__init__.py

## Problem Statement

`market_data/__init__.py` uses PEP 562 lazy imports but lacks `TYPE_CHECKING` guards. Static analysis tools (mypy, pyright) cannot resolve `get_macro_snapshot`, `compute_macro_stress_severity`, etc. Both `edgar/__init__.py` and `memo/__init__.py` have the pattern correctly.

## Findings

- `market_data/__init__.py` — PEP 562 `__getattr__` present, no TYPE_CHECKING block
- `edgar/__init__.py` — has TYPE_CHECKING block (correct)
- `memo/__init__.py` — has TYPE_CHECKING block (correct)
- Found by: pattern-recognition-specialist, kieran-python-reviewer

## Proposed Solutions

### Option 1: Add TYPE_CHECKING imports

**Approach:** Add `if TYPE_CHECKING:` block with `from vertical_engines.credit.market_data.service import ...` etc.

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/market_data/__init__.py`

## Acceptance Criteria

- [ ] TYPE_CHECKING block added matching edgar/memo pattern
- [ ] mypy can resolve market_data exports

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
