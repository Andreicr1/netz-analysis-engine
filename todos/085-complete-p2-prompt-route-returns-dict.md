---
status: pending
priority: p2
issue_id: "085"
tags: [code-review, quality, pydantic]
dependencies: []
---

# Prompt Update Route Returns dict Instead of Pydantic Schema

## Problem Statement
`backend/app/domains/admin/routes/prompts.py` line 70 uses `response_model=dict` for `update_prompt`. CLAUDE.md rule: "All routes use response_model= and return via model_validate(). No inline dict serialization."

## Findings
- **Source:** Kieran Python Reviewer (HIGH), Pattern Recognition (Medium)

## Proposed Solutions
Create `PromptWriteResponse` schema with `version: int` and `message: str`. Replace `response_model=dict` and `return dict(...)`.
- **Effort:** Small (15 min)

## Acceptance Criteria
- [ ] `update_prompt` uses a typed Pydantic response_model
- [ ] No `response_model=dict` in admin routes
