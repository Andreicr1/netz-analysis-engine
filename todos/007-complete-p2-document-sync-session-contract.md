---
status: pending
priority: p2
issue_id: "007"
tags: [code-review, architecture]
dependencies: []
---

# BaseAnalyzer uses sync Session without documenting the contract

## Problem Statement
`BaseAnalyzer` accepts sync `sqlalchemy.orm.Session` (not `AsyncSession`). This is intentional for credit legacy code, but undocumented. A future contributor will pass `AsyncSession` and get runtime errors.

## Proposed Solutions
Add a class-level docstring note:
```
Note: Methods accept sync Session because vertical engine business logic
runs in sync context (via asyncio.to_thread). Callers in async route
handlers must dispatch via executor or use a sync session.
```

## Acceptance Criteria
- [ ] Docstring documents the sync/async boundary contract
