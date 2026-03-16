---
status: pending
priority: p3
issue_id: "091"
tags: [code-review, quality, logging]
dependencies: []
---

# Health Routes Use logger.debug Instead of logger.warning

## Problem Statement
`backend/app/domains/admin/routes/health.py` uses `logger.debug(...)` in except blocks (lines 87, 125, 165) for Redis/DB failures. In production, debug logs are suppressed, so these failures would be invisible.

## Findings
- **Source:** Pattern Recognition (Low-Medium)

## Proposed Solutions
Change `logger.debug` to `logger.warning` in all health route except blocks.
- **Effort:** Small (5 min)

## Acceptance Criteria
- [ ] Health endpoint failures logged at WARNING level
