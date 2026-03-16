---
status: pending
priority: p1
issue_id: "062"
tags: [code-review, architecture]
---

# TODO 062: Cross-vertical import from credit in content route

## Problem Statement

`backend/app/domains/wealth/routes/content.py` line 416 imports `_call_openai` from `vertical_engines.credit.deep_review.helpers`. This creates a runtime dependency from wealth to credit, violating the vertical independence principle. The underscore prefix signals it's a private helper. While import-linter doesn't catch it (source is `app.domains.wealth`, not `vertical_engines.wealth`), it's an architectural violation.

## Findings

- **Source:** Code review of PRs #32-#36 (Wealth Vertical Modularization)
- **File:** `backend/app/domains/wealth/routes/content.py:416`
- **Severity:** P1 — violates vertical independence, a core architectural invariant
- **Why import-linter misses it:** The importing module is `app.domains.wealth`, not `vertical_engines.wealth`. Import-linter contracts only enforce `vertical_engines.credit` <-> `vertical_engines.wealth` independence.
- **Risk:** If credit's `_call_openai` signature changes or the module is refactored, wealth content generation breaks silently.

## Proposed Solutions

**Option A (preferred):** Extract `_call_openai` to a shared location like `ai_engine/llm/call_openai.py`. Both credit and wealth import from the shared module.

**Option B:** Duplicate the ~30-line wrapper into a wealth-specific helpers module (e.g., `backend/app/domains/wealth/helpers/llm.py`). Acceptable if the wrapper is small and unlikely to diverge.

## Technical Details

- `_call_openai` is a thin wrapper around the OpenAI client with retry/timeout logic
- The function is ~30 lines and has no credit-specific logic
- Moving it to `ai_engine/llm/` makes it available to all verticals without cross-imports
- The credit deep_review helpers module would then also import from the shared location

### Affected files

- `backend/app/domains/wealth/routes/content.py:416`
- `backend/vertical_engines/credit/deep_review/helpers.py`

## Acceptance Criteria

- [ ] No imports from `vertical_engines.credit` in wealth domain code
- [ ] LLM call wrapper in shared location or wealth-specific module
- [ ] `make check` passes

## Work Log

_(empty — work not yet started)_
