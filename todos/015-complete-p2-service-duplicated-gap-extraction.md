---
status: complete
priority: p2
issue_id: "015"
tags: [code-review, quality, duplication]
dependencies: []
---

# Extract duplicated gap-text logic in memo/service.py

## Problem Statement

The same 3-line gap-text extraction pattern is copy-pasted 4 times in `memo/service.py`. The `or`/`if` chain has ambiguous operator precedence without parentheses, creating a latent bug risk.

## Findings

- Lines 261, 373, 438, 656-660 all contain:
  ```python
  gap_text = gap.get("description") or gap.get("gap") or str(gap) if isinstance(gap, dict) else str(gap or "")
  ```
- The `if isinstance(gap, dict)` applies only to `str(gap)` due to operator precedence, not to the entire expression. This is likely correct by accident but misleading.
- Found by: code-simplicity-reviewer

## Proposed Solutions

### Option 1: Extract helper function with explicit parentheses

**Approach:** Create `_extract_gap_text(gap)` helper at module scope, call it 4 times.

**Pros:**
- Removes duplication (-9 LOC net)
- Fixes operator precedence ambiguity with explicit parentheses
- Single point of change for future updates

**Cons:**
- None

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/memo/service.py` — 4 call sites

## Resources

- **PR:** #19
- **Review agent:** code-simplicity-reviewer

## Acceptance Criteria

- [ ] Gap-text extraction is a single helper function
- [ ] Operator precedence is explicitly parenthesized
- [ ] `make check` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified duplicated logic during simplicity review
