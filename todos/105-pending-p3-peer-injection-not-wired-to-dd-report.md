---
status: pending
priority: p3
issue_id: "105"
tags: [code-review, integration, peer-group]
dependencies: []
---

# peer_injection.py exists but is not wired into DD Report chapters

## Problem Statement

`gather_peer_context()` in `peer_injection.py` is a complete bridge function but is never called from `chapters.py` or `dd_report_engine.py`. The DD Report performance_analysis chapter does not yet consume peer rankings. The function exists as a ready-to-integrate building block.

## Findings

- `peer_injection.py` — complete function with error handling and annotation formatting
- `dd_report/chapters.py` — generates chapters but does not call `gather_peer_context()`
- `dd_report/quant_injection.py` — `gather_quant_metrics()` IS called from chapters, peer equivalent is not
- Plan states: "extend quant_injection to inject peer rankings when available"
- This is expected — Sprint 2 delivers the engine, integration into chapters is a follow-up

## Proposed Solutions

### Option 1: Wire into chapters.py in a follow-up PR

**Approach:** In the performance_analysis chapter generation, call `gather_peer_context()` and include annotations in the evidence pack.

**Effort:** 30 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/dd_report/chapters.py` — add peer context call
- `backend/vertical_engines/wealth/dd_report/peer_injection.py` — already complete

## Resources

- **PR:** #48

## Acceptance Criteria

- [ ] DD Report performance_analysis chapter includes peer percentile annotations when available
- [ ] Chapter generation does not fail when peer group is unavailable

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Verified peer_injection.py is not imported anywhere outside tests
- Confirmed this is by design for Sprint 2 scope
