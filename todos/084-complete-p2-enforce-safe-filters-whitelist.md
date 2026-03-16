---
status: pending
priority: p2
issue_id: "084"
tags: [code-review, security, ssti]
dependencies: []
---

# _SAFE_FILTERS Whitelist Defined But Never Enforced

## Problem Statement
`backend/app/core/prompts/prompt_service.py` defines `_SAFE_FILTERS` (lines 47-54) and `_RENDER_TIMEOUT` (line 57) but neither is enforced. The `AdminSandboxedEnvironment` only overrides `is_safe_attribute`. Non-whitelisted filters remain available. No render timeout prevents DoS via `{% for i in range(10**9) %}`.

## Findings
- **Source:** Kieran Python Reviewer (MEDIUM), Security Sentinel (H2)

## Proposed Solutions
### Solution A: Enforce filter whitelist + add timeout (Recommended)
Override `call_filter` in `AdminSandboxedEnvironment` to enforce `_SAFE_FILTERS`. Add `signal.alarm` or `asyncio.wait_for` timeout for preview renders.
- **Effort:** Small-Medium (1 hour)

### Solution B: Remove dead code
Remove `_SAFE_FILTERS` and `_RENDER_TIMEOUT` since they provide false sense of security.
- **Effort:** Small (15 min)

## Acceptance Criteria
- [ ] Non-whitelisted Jinja2 filters are blocked in preview/validate
- [ ] Template rendering has a timeout (5s) for preview endpoint
- [ ] Or: dead code is removed
