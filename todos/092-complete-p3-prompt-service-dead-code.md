---
status: pending
priority: p3
issue_id: "092"
tags: [code-review, quality, dead-code]
dependencies: []
---

# PromptService Dead Code: _RENDER_TIMEOUT, snapshot_prompts

## Problem Statement
`backend/app/core/prompts/prompt_service.py`:
- `_RENDER_TIMEOUT = 5` (line 57) defined but never used
- `snapshot_prompts()` (lines 386-395) is a static method with zero callers in the codebase
- Tests use `PromptService.__new__()` to skip `__init__` — brittle pattern

## Findings
- **Source:** Kieran Python Reviewer (MEDIUM for _RENDER_TIMEOUT, LOW for __new__), Code Simplicity Reviewer

## Proposed Solutions
Remove `_RENDER_TIMEOUT`. Keep `snapshot_prompts` if jobs will use it soon, otherwise remove. Make `preview()` and `validate()` `@staticmethod` since they don't use `self._db`.
- **Effort:** Small (15 min)

## Acceptance Criteria
- [ ] No unused constants in prompt_service.py
- [ ] Tests don't use __new__ hack
