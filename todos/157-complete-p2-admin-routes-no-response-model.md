---
status: pending
priority: p2
issue_id: "157"
tags: [code-review, architecture, admin]
---

# Admin routes return raw dicts instead of `response_model=`

## Problem Statement
CLAUDE.md requires all routes to use `response_model=` and return via `model_validate()`. All 26 admin endpoints return inline dicts bypassing Pydantic response validation.

## Findings
- Schemas exist in `schemas.py` and `prompts/schemas.py` but are unused
- Routes in configs.py, tenants.py, prompts.py, health.py all return raw dicts

## Proposed Solution
Add `response_model=` to all admin routes using existing schemas. Create missing response schemas where needed.
