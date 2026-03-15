---
status: complete
priority: p2
issue_id: "012"
tags: [code-review, quality, typing]
dependencies: []
---

# Fix type annotation gaps in memo/chapters.py

## Problem Statement

Three functions in `memo/chapters.py` have weak type annotations for `call_openai_fn`. The `CallOpenAiFn` Protocol exists in `models.py` specifically for this purpose and is correctly used in `service.py`, but `chapters.py` uses `Any` or no annotation at all. This defeats the purpose of having the Protocol.

## Findings

- `generate_chapter()` line 258: `call_openai_fn: Any` — should be `CallOpenAiFn`
- `generate_recommendation_chapter()` line 490: `call_openai_fn: Any` — same
- `regenerate_chapter_with_critic()` line 690: `call_openai_fn` has NO annotation, and `evidence_pack: dict` is missing type params (should be `dict[str, Any]`)
- Found by: kieran-python-reviewer

## Proposed Solutions

### Option 1: Add proper type annotations

**Approach:** Import `CallOpenAiFn` from `models.py` and use it in all three function signatures. Fix `evidence_pack: dict` to `evidence_pack: dict[str, Any]`.

**Pros:**
- Static analysis catches signature mismatches
- Consistent with service.py usage
- 4-line change

**Cons:**
- None

**Effort:** 15 minutes
**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/credit/memo/chapters.py` lines 258, 490, 690

## Resources

- **PR:** #19
- **Review agent:** kieran-python-reviewer

## Acceptance Criteria

- [ ] All three functions use `CallOpenAiFn` Protocol for `call_openai_fn` parameter
- [ ] `evidence_pack: dict` changed to `dict[str, Any]` in `regenerate_chapter_with_critic`
- [ ] `make check` passes

## Work Log

### 2026-03-15 - Code Review Discovery

**By:** Claude Code (ce:review)
**Actions:** Identified type annotation gaps during Wave 1 review
