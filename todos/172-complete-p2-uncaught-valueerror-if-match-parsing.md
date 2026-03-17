---
id: 172
status: pending
priority: p2
tags: [code-review, security, admin, backend]
created: 2026-03-17
---

# Uncaught ValueError on If-Match parsing

## Problem Statement

The admin config update endpoint parses the `If-Match` header as an integer without error handling. A non-numeric value causes an unhandled `ValueError`, resulting in a 500 response with a stack trace that may leak internal implementation details.

## Findings

- **File:** `backend/app/domains/admin/routes/configs.py` line 88
  - `version = int(if_match)` with no try/except
  - Any non-numeric `If-Match` header value (e.g., `"abc"`, `"v2"`, `""`) triggers an unhandled `ValueError`

- **Impact:**
  - Returns HTTP 500 instead of a proper 400 Bad Request
  - Stack trace in the response may reveal file paths, function names, or framework internals
  - Violates the principle of returning clear client errors for malformed input

## Proposed Solutions

```python
try:
    version = int(if_match)
except (ValueError, TypeError):
    raise HTTPException(
        status_code=400,
        detail="If-Match must be a valid integer version"
    )
```

## Acceptance Criteria

- [ ] Non-numeric `If-Match` header returns HTTP 400 with a clear error message
- [ ] No stack trace is exposed in the response
- [ ] Valid numeric `If-Match` values continue to work as before
- [ ] Edge cases handled: empty string, float string, negative numbers
