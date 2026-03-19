# Wealth DD Report & Fact Sheet Approval Workflow — Implementation Prompt

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Context

Gap analysis at `docs/audit/wealth-dd-factsheet-workflow-gap.md` identifies 6 gaps in the DD Report and Fact Sheet approval lifecycle. This prompt closes Priority 1 (DD Report approval cycle) and Priority 2 (Content generation UI).

---

## Phase 1: DD Report Approval Endpoints

### 1.1 Add approve/reject endpoints

**File:** `backend/app/domains/wealth/routes/dd_reports.py`

Add two new endpoints after the existing `regenerate_dd_report()`:

```python
@router.post("/{report_id}/approve", response_model=DDReportResponse)
async def approve_dd_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: dict = Depends(require_role("ic_member")),
):
    """Approve a DD report for investor distribution. Requires IC role. Self-approval blocked."""
```

Logic:
- Load report with `selectinload(DDReport.chapters)`
- Validate `status == "pending_approval"` — else 409
- Validate `actor["user_id"] != report.created_by` — else 403 (self-approval blocked, mirror content.py:288-292)
- Set `status = "approved"`, `approved_by = actor["user_id"]`, `approved_at = utcnow()`
- Return updated report

```python
@router.post("/{report_id}/reject", response_model=DDReportResponse)
async def reject_dd_report(
    report_id: UUID,
    body: DDReportRejectRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: dict = Depends(require_role("ic_member")),
):
    """Reject a DD report back to draft with rationale."""
```

Logic:
- Validate `status == "pending_approval"` — else 409
- Set `status = "draft"`, `rejection_reason = body.reason`
- Return updated report

### 1.2 Add schema for rejection

**File:** `backend/app/domains/wealth/schemas/dd_report.py`

```python
class DDReportRejectRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)
```

### 1.3 Add model fields

**File:** `backend/app/domains/wealth/models/dd_report.py`

Add to `DDReport`:
```python
approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### 1.4 Create migration

```bash
make migration MSG="add_dd_report_approval_fields"
```

Adds 3 columns: `approved_by`, `approved_at`, `rejection_reason` to `wealth_dd_reports`.

### 1.5 Modify generation flow

**File:** `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`

In the completion logic (around line 170), change the final status from `completed` to `pending_approval` when all chapters succeed:

```python
# Before: report.status = "completed"
# After:
report.status = "pending_approval"
```

Keep `partial` and `failed` statuses unchanged.

### 1.6 Gate investor download

**File:** `backend/app/domains/wealth/routes/fact_sheets.py`

In `download_dd_report_pdf()` (the endpoint that generates PDF from DD report chapters), add a status check:

```python
if report.status not in ("approved", "published"):
    raise HTTPException(403, "Report not yet approved for distribution")
```

This only applies to investor-context requests. Team members should still be able to preview PDFs. Differentiate by checking actor role or add a separate team preview endpoint.

---

## Phase 2: DD Report Approval Frontend (Team)

### 2.1 Add approval UI to report detail page

**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

Add an approval bar at the top of the report detail view:

- Show status badge: `pending_approval` → yellow "Awaiting IC Approval"
- If user has IC role and is NOT the report creator:
  - Show "Approve" button (green) → `POST /dd-reports/{reportId}/approve`
  - Show "Reject" button (red) → opens modal with reason textarea → `POST /dd-reports/{reportId}/reject`
- On approve: `invalidateAll()`, show success toast
- On reject: `invalidateAll()`, show info toast with rejection reason echoed

### 2.2 Status badges in report list

**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/+page.svelte`

Add color-coded status badges to each report row:
- `draft` → gray
- `generating` → blue pulse
- `pending_approval` → yellow
- `approved` → green
- `completed` → green (legacy, treat as approved)
- `partial` → orange
- `failed` → red

---

## Phase 3: Investor DD Report Page

### 3.1 Create investor DD report route

**Files:**
- `frontends/wealth/src/routes/(investor)/dd-reports/+page.svelte`
- `frontends/wealth/src/routes/(investor)/dd-reports/+page.server.ts` (if SSR load needed)

Page shows:
- List of DD reports with `status in ("approved", "published")` for funds the investor has access to
- Each row: fund name, report version, date, confidence score, decision anchor
- Download PDF button per report
- Uses `GET /dd-reports/funds/{fund_id}` filtered client-side by status (or add `?status=approved` query param to backend)

### 3.2 Add status filter to list endpoint

**File:** `backend/app/domains/wealth/routes/dd_reports.py`

Add optional `status` query parameter to `list_dd_reports()`:

```python
async def list_dd_reports(
    fund_id: UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
):
```

Filter: `if status: query = query.where(DDReport.status == status)`

---

## Phase 4: Content Generation Team UI

### 4.1 Create content management page

**File:** `frontends/wealth/src/routes/(team)/content/+page.svelte`

Page layout:
- Tab bar: All | Outlooks | Flash Reports | Spotlights
- "Generate" dropdown button with 3 options:
  - Investment Outlook → opens modal with date range + context fields → `POST /content/outlooks`
  - Flash Report → opens modal with topic field → `POST /content/flash-reports`
  - Manager Spotlight → opens modal with manager/fund selector → `POST /content/spotlights`
- Content list table: type, title, status badge, created date, approved by, actions
- Actions per row:
  - View (navigate to detail)
  - Approve (if pending_approval, user is IC, not creator)
  - Download PDF (if approved)

### 4.2 Create content detail page

**File:** `frontends/wealth/src/routes/(team)/content/[contentId]/+page.svelte`

Shows:
- Rendered markdown content
- Metadata sidebar (type, status, creator, dates)
- Approve/Reject buttons (same logic as DD report)
- Download PDF button

---

## Verification Checklist

After implementation, verify:

1. `make check` passes (lint + typecheck + test)
2. `pnpm check` in `frontends/wealth/` — 0 errors
3. DD Report generation now results in `pending_approval` status
4. Approve endpoint transitions to `approved`, sets `approved_by`/`approved_at`
5. Reject endpoint transitions to `draft`, stores rejection reason
6. Self-approval returns 403
7. Investor DD report page only shows approved reports
8. Content generation triggers work from team UI
9. Content approval flow works end-to-end
10. All new endpoints appear in `docs/audit/endpoint-frontend-coverage-audit.md` update

---

## Files Modified

| File | Change |
|------|--------|
| `backend/app/domains/wealth/routes/dd_reports.py` | +approve, +reject endpoints, +status filter |
| `backend/app/domains/wealth/models/dd_report.py` | +approved_by, +approved_at, +rejection_reason |
| `backend/app/domains/wealth/schemas/dd_report.py` | +DDReportRejectRequest |
| `backend/vertical_engines/wealth/dd_report/dd_report_engine.py` | completed → pending_approval |
| `backend/app/domains/wealth/routes/fact_sheets.py` | +approval gate on investor download |
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` | +approval bar |
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/+page.svelte` | +status badges |
| `frontends/wealth/src/routes/(investor)/dd-reports/+page.svelte` | NEW — investor DD reports |
| `frontends/wealth/src/routes/(team)/content/+page.svelte` | NEW — content management |
| `frontends/wealth/src/routes/(team)/content/[contentId]/+page.svelte` | NEW — content detail |
| Migration | +3 columns on wealth_dd_reports |

## Tests to Add

| Test | File |
|------|------|
| Approve DD report happy path | `tests/domains/wealth/test_dd_report_approval.py` |
| Reject DD report with reason | same |
| Self-approval blocked (403) | same |
| Wrong status approve attempt (409) | same |
| Investor download gated on approval | `tests/domains/wealth/test_fact_sheet_download_gate.py` |
| Status filter on list endpoint | `tests/domains/wealth/test_dd_report_list_filter.py` |
