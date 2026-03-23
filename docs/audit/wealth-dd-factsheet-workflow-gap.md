# Wealth DD Report & Fact Sheet Workflow — Gap Analysis

**Date:** 2026-03-19
**Scope:** DD Reports, Fact Sheets, Content Approval, Investor Portal Delivery

---

## Current State Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        TEAM WORKFLOW                            │
│                                                                 │
│  DD Reports:                                                    │
│    Fund Selector → Trigger Generation → SSE Progress →          │
│    Chapter View → Regenerate Chapters → Download PDF            │
│    Status: draft → generating → completed/partial/failed        │
│    ⚠ No approve/reject step — auto-completes                   │
│                                                                 │
│  Fact Sheets:                                                   │
│    (No team UI — investor-only trigger)                         │
│    Generate → Store PDF in gold layer → List via storage scan   │
│    ⚠ No DB model, no version tracking, no approval             │
│                                                                 │
│  Content (Outlooks/Flash/Spotlights):                           │
│    ⚠ No trigger UI (endpoints exist, frontend disconnected)     │
│    draft → review → approved → published                        │
│    Approval requires different user (self-approval blocked)     │
│    Download gated on status >= approved                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      INVESTOR PORTAL                            │
│                                                                 │
│  (investor)/fact-sheets    → List & download model portfolio    │
│                               fact sheets from gold layer       │
│  (investor)/inv-documents  → Download approved content PDFs     │
│  (investor)/reports        → List approved content items        │
│  (investor)/inv-portfolios → View model portfolios              │
│                                                                 │
│  ⚠ DD Reports have NO investor-facing route                    │
│  ⚠ No "published" gate on DD report download                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Backend Endpoints Inventory

### DD Reports (`/api/v1/dd-reports`)

| Method | Path | Frontend | Status |
|--------|------|----------|--------|
| POST | `/funds/{fund_id}` | ✅ Team trigger | CONNECTED |
| GET | `/funds/{fund_id}` | ✅ Team list | CONNECTED |
| GET | `/{report_id}` | ✅ Team detail | CONNECTED |
| POST | `/{report_id}/regenerate` | ✅ Team regenerate | CONNECTED |
| GET | `/{report_id}/stream` | ✅ SSE progress | CONNECTED |

### Fact Sheets (`/api/v1/fact-sheets`)

| Method | Path | Frontend | Status |
|--------|------|----------|--------|
| POST | `/model-portfolios/{portfolio_id}` | ✅ Investor trigger | CONNECTED |
| GET | `/model-portfolios/{portfolio_id}` | ✅ Investor list | CONNECTED |
| GET | `/{path}/download` | ✅ Investor download | CONNECTED |
| GET | `/dd-reports/{report_id}/download` | ✅ Team DD PDF | CONNECTED |

### Content (`/api/v1/content`)

| Method | Path | Frontend | Status |
|--------|------|----------|--------|
| POST | `/outlooks` | ❌ No team UI | DISCONNECTED |
| POST | `/flash-reports` | ❌ No team UI | DISCONNECTED |
| POST | `/spotlights` | ❌ No team UI | DISCONNECTED |
| GET | `/` | ✅ Investor reports list | CONNECTED |
| POST | `/{content_id}/approve` | ✅ Team approval | CONNECTED |
| GET | `/{content_id}/download` | ✅ Investor download | CONNECTED |

---

## Identified Gaps

### GAP-1: DD Reports lack approval workflow (HIGH)

**Current:** DD Reports go `draft → generating → completed` automatically. No `pending_approval` → `approved` transition exists despite `pending_approval` being a valid status value in the model.

**Impact:** Generated DD reports are immediately accessible. No IC review gate before investor distribution.

**Fix:** Wire the `pending_approval` status into the generation flow. Add `POST /dd-reports/{report_id}/approve` and `POST /dd-reports/{report_id}/reject` endpoints mirroring the content approval pattern.

### GAP-2: DD Reports have no investor-facing route (HIGH)

**Current:** DD reports can only be viewed/downloaded from team routes. No `(investor)/dd-reports` page exists.

**Impact:** Investors cannot access DD reports through the portal even if approved.

**Fix:** Add investor DD report route that lists only `status=approved|published` DD reports for funds the investor has access to.

### GAP-3: Content generation triggers have no team UI (MEDIUM)

**Current:** `POST /content/outlooks`, `/flash-reports`, `/spotlights` endpoints exist with full generation logic, but no frontend page lets the team trigger them.

**Impact:** Content generation can only be triggered via API/curl. Approval workflow works but is unreachable for non-technical users.

**Fix:** Add team content generation page at `(team)/content/+page.svelte` with trigger buttons and status tracking.

### GAP-4: Fact sheets have no DB model or version history (MEDIUM)

**Current:** Fact sheets are stored as files in gold layer. Listed via `storage.list_files()` filesystem scan. No database record, no version tracking, no approval status.

**Impact:** Cannot track who generated which version, cannot enforce approval before investor access, cannot query fact sheet history efficiently.

**Fix:** Add `WealthFactSheet` model mirroring `DDReport` pattern (status, version, approved_by, storage_path). Persist record on generation, update on approval.

### GAP-5: Bond brief report type not implemented (LOW)

**Current:** `DDReport.report_type` field supports "bond_brief" but engine always generates 8 chapters regardless.

**Impact:** Bonds get the same DD report template as funds. No specialized 2-chapter bond brief.

**Fix:** Add `report_type` parameter to generation trigger. When "bond_brief", generate only executive_summary + recommendation chapters.

### GAP-6: DD Report PDF download goes through fact-sheet route (LOW)

**Current:** Frontend calls `GET /fact-sheets/dd-reports/{report_id}/download` for DD report PDFs — routed through the fact sheet controller.

**Impact:** Confusing route ownership. Works correctly but semantically wrong.

**Fix:** Consider adding `GET /dd-reports/{report_id}/download` as a dedicated endpoint (or accept the current routing as intentional).

---

## Recommended Implementation Plan

### Priority 1 — DD Report Approval Cycle (GAP-1 + GAP-2)

1. Add `POST /dd-reports/{report_id}/approve` endpoint (requires IC role, self-approval blocked)
2. Add `POST /dd-reports/{report_id}/reject` endpoint (sets status back to draft)
3. Modify generation flow: completed → pending_approval (not completed directly)
4. Add approval UI to team DD report detail page (approve/reject buttons)
5. Add `(investor)/dd-reports/+page.svelte` showing only approved reports
6. Gate DD report PDF download on `status >= approved` for investor routes

### Priority 2 — Content Generation UI (GAP-3)

1. Add `(team)/content/+page.svelte` with type selector (outlook/flash/spotlight)
2. Wire trigger buttons to existing POST endpoints
3. Show generation progress via SSE
4. Show content list with status badges and approve/reject actions

### Priority 3 — Fact Sheet Persistence (GAP-4)

1. Create `WealthFactSheet` model with status, version, approved_by fields
2. Migration to add `wealth_fact_sheets` table
3. Modify generation to persist DB record alongside file storage
4. Add approval endpoints for fact sheets
5. Gate investor download on approved status

### Priority 4 — Bond Brief (GAP-5)

1. Add `report_type` parameter to DD report trigger endpoint
2. Define 2-chapter template for bond briefs
3. Modify `DDReportEngine` to select chapter set based on report_type
