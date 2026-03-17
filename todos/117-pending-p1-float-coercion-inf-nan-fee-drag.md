---
status: pending
priority: p1
issue_id: "117"
tags: [code-review, security, fee-drag, financial-calculation]
dependencies: []
---

# Float coercion in _extract_fees accepts inf/nan — poisons portfolio aggregation

## Problem Statement

`FeeDragService._extract_fees` uses bare `float()` on untrusted JSONB `attributes` values. This accepts `"inf"`, `"nan"`, non-numeric strings (raises `ValueError`), and `None` (raises `TypeError`). A single poisoned instrument with `management_fee_pct: "inf"` propagates `inf` through all weighted calculations in `compute_portfolio_fee_drag`, making the entire portfolio result meaningless.

The single-instrument path `compute_fee_drag` has NO try/except, so bad data raises unhandled exceptions to the caller.

## Findings

**Flagged by:** Security Sentinel, Performance Oracle

**Evidence:**
- `backend/vertical_engines/wealth/fee_drag/service.py` lines 166-168: bare `float()` calls
- `backend/vertical_engines/wealth/fee_drag/service.py` line 62: `gross = float(attributes.get("expected_return_pct", 0.0))`
- Same pattern: 5 bare `float()` calls total in the fee drag hot path

## Proposed Solutions

### Option A: Add `_safe_float` helper (Recommended)
```python
import math

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f
```
- **Pros:** Defensive, handles all edge cases, zero overhead
- **Cons:** None
- **Effort:** Small (15 min)
- **Risk:** None

### Option B: Validate at service boundary
- Add type checks in `compute_fee_drag` before passing to `_extract_fees`
- **Pros:** Explicit
- **Cons:** Duplicated validation
- **Effort:** Small

## Acceptance Criteria

- [ ] All `float()` casts in `_extract_fees` and `compute_fee_drag` use safe coercion
- [ ] `inf`, `nan`, `None`, and non-numeric strings default to 0.0
- [ ] Test added: instrument with `management_fee_pct: "inf"` does not poison portfolio
- [ ] Test added: instrument with `management_fee_pct: "N/A"` returns 0.0 fee

## Work Log

| Date | Action |
|------|--------|
| 2026-03-16 | Created from PR #51 code review |

## Resources

- PR #51: https://github.com/Andreicr1/netz-analysis-engine/pull/51
- File: `backend/vertical_engines/wealth/fee_drag/service.py`
