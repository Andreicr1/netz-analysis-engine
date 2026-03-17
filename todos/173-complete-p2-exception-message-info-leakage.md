---
id: 173
status: pending
priority: p2
tags: [code-review, security, wealth, backend]
created: 2026-03-17
---

# Exception message stored as error_message — info leakage

## Problem Statement

Raw Python exception strings are stored in the database as `error_message` and rendered directly in the frontend. These strings may contain API keys, internal hostnames, database connection details, or stack fragments that should never be exposed to end users.

## Findings

- **Backend:** `backend/app/domains/wealth/routes/content.py` line 429
  - `"error_message": str(exc)` stores the raw exception string
  - Exception messages from HTTP clients, database drivers, or cloud SDKs often include URLs with credentials, internal IPs, or verbose stack information

- **Frontend:** Wealth content page line 163
  - Renders `{item.error_message}` directly in the UI
  - Any sensitive data in the exception string is visible to the end user

- **Risk:** Information disclosure — internal infrastructure details, partial credentials, or API endpoint URLs could be exposed through error messages

## Proposed Solutions

1. Replace `str(exc)` with a generic, user-friendly message: `"Content processing failed. Please try again or contact support."`
2. Log the full exception (including traceback) to structured logs with appropriate severity
3. Optionally store a sanitized error code (e.g., `"PROCESSING_FAILED"`, `"EXTERNAL_SERVICE_ERROR"`) in the database for debugging without exposing internals
4. Audit other `str(exc)` usages across the codebase for the same pattern

## Acceptance Criteria

- [ ] `error_message` field never contains raw exception strings
- [ ] Full exception details are logged server-side for debugging
- [ ] Frontend displays a user-friendly error message, not raw exception text
- [ ] Existing error messages in the database are not retroactively changed (backward compatible)
