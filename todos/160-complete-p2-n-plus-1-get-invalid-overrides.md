---
status: pending
priority: p2
issue_id: "160"
tags: [code-review, performance, admin]
---

# N+1 query in `get_invalid_overrides()`

## Problem Statement
`ConfigService.get_invalid_overrides()` executes one query per (vertical, config_type) pair that has guardrails. Grows linearly with config types.

## Findings
- `backend/app/core/config/config_service.py`: sequential queries per default row

## Proposed Solution
Rewrite as single JOIN query: `SELECT d.*, o.* FROM defaults d JOIN overrides o ON ... WHERE d.guardrails IS NOT NULL`.
