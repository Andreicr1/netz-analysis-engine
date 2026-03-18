---
status: complete
priority: p2
issue_id: "188"
tags: [code-review, security, credit, frontend]
dependencies: []
---

# Credit document upload has no file size limit or magic-byte validation

## Problem Statement

The credit document upload page sends file metadata to get a SAS URL, then uploads directly to Azure Blob. There is no client-side file size validation or magic-byte content verification. Unlike the admin branding upload (which validates magic bytes), the document upload has no content-type verification beyond the bypassable `accept` attribute.

## Findings

- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte` — no file size check
- Only `accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"` (client-side, bypassable)
- No magic-byte validation
- Could allow multi-hundred-MB uploads without user feedback

## Proposed Solutions

### Option 1: Add client-side size limit + magic-byte validation

**Approach:** Add 50MB file size limit with feedback. Add magic-byte validation for PDF/Office formats similar to admin branding upload.

**Effort:** 1-2 hours

**Risk:** Low

## Recommended Action

## Technical Details

**Affected files:**
- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte`

## Acceptance Criteria

- [ ] File size validated before upload (max 50MB with error message)
- [ ] Magic-byte validation for PDF and Office formats
- [ ] User feedback for rejected files

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — security-sentinel agent)
