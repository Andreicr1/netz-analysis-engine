---
status: pending
priority: p2
issue_id: "088"
tags: [code-review, quality, duplication]
dependencies: []
---

# Duplicated POST/PUT Config Endpoints

## Problem Statement
`backend/app/domains/admin/routes/configs.py` has `create_config_override` (POST) and `update_config_override` (PUT) that both call `writer.put()` with identical error handling (~40 lines duplicated). The PUT also ignores `payload.vertical` and `payload.config_type` in favor of path params, creating confusing API contract.

## Findings
- **Source:** Code Simplicity Reviewer, Pattern Recognition (Medium)

## Proposed Solutions
### Solution A: Remove POST, keep PUT as upsert (Recommended)
Since `ConfigWriter.put()` is already an upsert, the POST endpoint adds no semantic value. Keep only PUT `/{vertical}/{config_type}`.
- **Effort:** Small (30 min)

### Solution B: Extract shared helper
Keep both endpoints but extract the try/except block into `_handle_config_write()`.
- **Effort:** Small (30 min)

## Acceptance Criteria
- [ ] No duplicated error handling code in config routes
- [ ] Config write API contract is clear (single upsert endpoint or deduplicated)
