---
status: pending
priority: p1
issue_id: "002"
tags: [code-review, security]
dependencies: []
---

# Unsanitized filename in upload-url blob path construction

## Problem Statement
`upload_url.py` line 102 constructs a blob path using `payload.filename` from user input with no sanitization. A malicious filename like `../../silver/other-org/secrets.pdf` could write to arbitrary paths in ADLS. The `LocalStorageClient` has path traversal protection but `ADLSStorageClient` does not.

**Why it matters:** An authenticated user with upload permissions could overwrite other organizations' data in the ADLS container.

## Findings
- **Security reviewer:** HIGH (H1) — path traversal via user-controlled filename
- The `service.py` file already has `PATH_SEGMENT_RE = re.compile(r"^[^\\\\/:*?\"<>|]+$")` that could be reused

**Affected file:** `backend/app/domains/credit/documents/routes/upload_url.py` line 102

## Proposed Solutions

### Option A: Validate filename with PATH_SEGMENT_RE (Recommended)
Apply existing `PATH_SEGMENT_RE` to `payload.filename` before constructing blob path. Also add path validation to `ADLSStorageClient` base class.
- **Pros:** Reuses existing pattern, defense in depth
- **Cons:** None
- **Effort:** Small
- **Risk:** Low

### Option B: Strip path separators from filename
Replace `/`, `\`, `..` from filename before use.
- **Pros:** Simple
- **Cons:** Less strict than regex validation
- **Effort:** Small
- **Risk:** Low

## Technical Details
- **Affected files:** `backend/app/domains/credit/documents/routes/upload_url.py`, `backend/app/services/storage_client.py`
- Also add `_validate_path()` to `ADLSStorageClient` or the base `StorageClient` class

## Acceptance Criteria
- [ ] Filenames with path traversal characters are rejected with 400
- [ ] ADLSStorageClient validates paths before passing to Azure SDK
- [ ] Tests cover malicious filename patterns

## Work Log
| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-15 | Identified by security reviewer | PATH_SEGMENT_RE already exists in service.py |
