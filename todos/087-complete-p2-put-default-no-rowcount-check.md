---
status: pending
priority: p2
issue_id: "087"
tags: [code-review, correctness, optimistic-locking]
dependencies: []
---

# put_default() Silently Succeeds on Concurrent Update

## Problem Statement
`backend/app/core/config/config_writer.py` `put_default()` method reads the row, increments version, and updates WHERE version = row.version. But there is no rowcount check after the UPDATE. If concurrent update races, the method returns the new version number even though no row was updated.

## Findings
- **Source:** Kieran Python Reviewer (MEDIUM)

## Proposed Solutions
Add `if result.rowcount == 0: raise StaleVersionError(current_version=row.version)` after the UPDATE.
- **Effort:** Small (15 min)

## Acceptance Criteria
- [ ] Concurrent `put_default` raises StaleVersionError on race
