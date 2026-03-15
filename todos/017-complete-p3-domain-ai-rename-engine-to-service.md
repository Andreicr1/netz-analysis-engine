---
status: complete
priority: p3
issue_id: "017"
tags: [code-review, architecture, consistency]
dependencies: []
---

# Rename domain_ai/engine.py to service.py for consistency

## Problem Statement

All 10 packages with an orchestrator name it `service.py`. `domain_ai` is the only package using `engine.py` as its main module, breaking the naming convention.

## Findings

- `domain_ai/engine.py` is the sole orchestrator module
- All other packages: critic/service.py, sponsor/service.py, kyc/service.py, pipeline/service.py, quant/service.py, market_data/service.py, portfolio/service.py, deal_conversion/service.py, memo/service.py
- Found by: pattern-recognition-specialist

## Proposed Solutions

### Option 1: Rename to service.py

**Approach:** Rename `engine.py` to `service.py`, update `__init__.py` import.

**Effort:** 10 minutes
**Risk:** Low (single internal caller in __init__.py)

### Option 2: Document the exception

**Approach:** Add a note in the `__init__.py` docstring explaining why engine.py was kept.

**Effort:** 5 minutes
**Risk:** None

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/domain_ai/engine.py` → `service.py`
- `backend/vertical_engines/credit/domain_ai/__init__.py`

## Acceptance Criteria

- [ ] Module renamed or exception documented
- [ ] `make check` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
