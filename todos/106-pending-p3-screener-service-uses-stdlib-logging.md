---
status: pending
priority: p3
issue_id: "106"
tags: [code-review, quality, pattern-consistency]
dependencies: []
---

# Screener service.py uses stdlib logging instead of structlog

## Problem Statement

The existing `screener/service.py` uses `import logging` + `logging.getLogger(__name__)` while the new `peer_group/service.py` correctly uses `structlog.get_logger()`. The project standard (per CLAUDE.md) is structlog. This inconsistency pre-dates PR #48 but was discovered during review.

## Findings

- `screener/service.py:17` — `import logging` + `logger = logging.getLogger(__name__)`
- `peer_group/service.py:17` — `import structlog` + `logger = structlog.get_logger()` (correct)
- `peer_matcher.py:14` — uses structlog (correct)
- `peer_injection.py:16` — uses structlog (correct)
- CLAUDE.md: "structlog for all logging (not print/logging)"

## Proposed Solutions

### Option 1: Fix screener/service.py in a separate PR

**Approach:** Replace `import logging` with `import structlog` in screener/service.py.

**Effort:** 5 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `backend/vertical_engines/wealth/screener/service.py:17,33`

## Resources

- **PR:** #48 (discovered during review, pre-existing issue)

## Acceptance Criteria

- [ ] All service.py files in vertical_engines/wealth/ use structlog

## Work Log

### 2026-03-16 - Initial Discovery

**By:** Claude Code (code review of PR #48)

**Actions:**
- Identified logging inconsistency between screener and peer_group
