---
status: pending
priority: p3
issue_id: "149"
tags: [code-review, quality, config]
dependencies: []
---

# Hardcoded 0.7 contagion "currently high" threshold

## Problem Statement

In `correlation_regime_service.py`, the contagion detection uses `curr > 0.7` as a hardcoded threshold for "currently high correlation". The `contagion_threshold` (change amount) is configurable, but the absolute level is not. This breaks the "ConfigService for all thresholds" convention.

## Findings

- Found by: kieran-python-reviewer
- `backend/quant_engine/correlation_regime_service.py` line 289

## Proposed Solutions

### Option 1: Add config parameter (Recommended)

**Approach:** Add `contagion_current_min: 0.7` to the config defaults and use `cfg["contagion_current_min"]` in the comparison.

**Effort:** 10 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/quant_engine/correlation_regime_service.py`

## Acceptance Criteria

- [ ] Threshold configurable via config parameter
- [ ] Default value preserved at 0.7
- [ ] Tests pass

## Work Log

### 2026-03-17 - Code Review Discovery

**By:** Claude Code (ce:review)
