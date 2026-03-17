---
status: complete
priority: p1
issue_id: "082"
tags: [code-review, security, data-exposure, investor-portal]
dependencies: []
---

# Investor portal exposes internal blob_path and blob_uri to external users

## Problem Statement

`investor_portal.py:114` exposes `blob_path` (internal ADLS storage path) and line 153 exposes `blob_uri` (internal storage URI) in API responses to investor-role users. These internal storage paths reveal infrastructure details (storage account names, container structure, tenant org IDs embedded in paths) to external users who should only see document metadata.

Per CLAUDE.md: path routing uses `{organization_id}/{vertical}/` as prefix — exposing `blob_path` leaks `organization_id` UUIDs and internal storage topology.

## Findings

- `backend/app/domains/credit/reporting/routes/investor_portal.py:114` — `"blob_path": r.blob_path` exposed to investors
- `backend/app/domains/credit/reporting/routes/investor_portal.py:153` — `"blob_uri": r.blob_uri` exposed to investors
- These paths contain: org UUID, vertical name, document ID, internal storage structure
- Investor roles are EXTERNAL users (LPs, advisors) — not internal team
- Impact: Information disclosure of internal infrastructure to external users

## Proposed Solutions

### Option 1: Remove blob_path/blob_uri, add download endpoint

**Approach:** Remove internal paths from investor response. Add a `/funds/{fund_id}/investor/documents/{doc_id}/download` endpoint that streams the file through the backend.

**Pros:**
- No internal paths exposed
- Backend controls access and audit
- Can add download tracking

**Cons:**
- Backend becomes a proxy for file downloads
- Higher bandwidth cost on backend

**Effort:** 2-3 hours

**Risk:** Low

---

### Option 2: Generate time-limited SAS URLs

**Approach:** Replace blob_path with a short-lived SAS URL generated on demand, valid for ~15 minutes.

**Pros:**
- Direct download from storage (no proxy)
- Time-limited access
- No internal paths exposed

**Cons:**
- Requires ADLS integration in investor portal
- SAS URL generation overhead

**Effort:** 3-4 hours

**Risk:** Low

## Recommended Action

**To be filled during triage.**

## Technical Details

**Affected files:**
- `backend/app/domains/credit/reporting/routes/investor_portal.py:114,153`

## Acceptance Criteria

- [ ] No `blob_path` or `blob_uri` in investor API responses
- [ ] Investors can still download/access documents
- [ ] Internal storage topology not exposed in any investor-facing response

## Work Log

### 2026-03-16 - Code Review Discovery

**By:** Claude Code (ce:review PRs #37-#45)

**Actions:**
- Found blob_path and blob_uri exposed in investor endpoints
- Verified these contain internal org UUIDs and storage paths
- Classified as P1 — information disclosure to external users

## Resources

- **PR:** #40 (Phase B+)
