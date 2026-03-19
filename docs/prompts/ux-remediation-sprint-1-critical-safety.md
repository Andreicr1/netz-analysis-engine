# UX Remediation Sprint 1 — Critical Safety (P0)

## Context

You are executing Sprint 1 of the Premium UX Remediation effort for the Netz Analysis Engine — a multi-tenant institutional investment platform with Credit and Wealth verticals.

Read these files before starting any work:
- `CLAUDE.md` — full project rules, architecture, critical constraints
- `docs/ux/premium-ux-remediation-execution-backlog.md` — full backlog (you are executing Phase 1)

This sprint covers **BL-01 through BL-05** — all P0 Critical Risk items. These are bugs, missing friction on investor-facing actions, and a silent-default security issue. They must ship before any other UX remediation work.

---

## What you are fixing

The Wealth vertical has five critical safety gaps in its approval/rejection workflows:

1. **DD report approval is a single click with no dialog.** The approve button directly POSTs to `/dd-reports/{report_id}/approve` with an empty body `{}`. No confirmation, no rationale, no consequence display. The backend endpoint also accepts no body — it needs a schema change to accept rationale.

2. **DD report rejection dialog works but lacks consequence communication.** It uses a custom `Dialog` with `FormField` textarea (sends `{ reason }` to `POST /{report_id}/reject`). It should use `ConsequenceDialog` for gravity parity with Credit.

3. **Universe rejection rationale is broken.** `rejectRationale` state is declared and sent to API, but the `ConfirmDialog` has no textarea. Rationale is always empty. This is a functional bug.

4. **Universe approval has no rationale capture.** Frontend sends `{ decision: "approved" }` with no rationale field. The backend accept optional `rationale` but the frontend never sends it.

5. **Universe decision validation falls back to "approved" silently.** `universe.py` line ~125: `decision = body.decision if body.decision in ("approved", "watchlist") else "approved"`. Invalid values don't fail — they approve.

---

## Execution strategy — parallel agents

Use `model: sonnet` for all agents. These are surgical edits on a well-specified prompt — Sonnet is sufficient.

### Phase 1 — Backend (2 agents in parallel)

Launch these two agents simultaneously:

**Agent A — BL-03: Universe validation fix**
- Files: `backend/app/domains/wealth/routes/universe.py`
- Standalone, no dependencies

**Agent B — BL-01 backend: DD report approve schema + route**
- Files: `backend/app/domains/wealth/schemas/dd_report.py`, `backend/app/domains/wealth/routes/dd_reports.py`
- Creates `DDReportApproveRequest` schema and wires it into the approve endpoint

Wait for both to complete before Phase 2.

### Phase 2 — Frontend (2 agents in parallel)

Launch these two agents simultaneously:

**Agent C — BL-01 + BL-04: DD report page (approve + reject)**
- File: `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`
- Depends on Agent B (needs backend to accept `{ rationale }`)

**Agent D — BL-02 + BL-05: Universe page (approve + reject)**
- File: `frontends/wealth/src/routes/(team)/universe/+page.svelte`
- No backend dependency (backend already accepts optional `rationale`)

### Phase 3 — Verification (sequential)

Run `make test` and `pnpm check` in `frontends/wealth/`.

---

## Execution items

### BL-03 — Universe Approval: Reject Invalid Decision Values Server-Side

**Files:**
- `backend/app/domains/wealth/routes/universe.py` — approve endpoint (~line 125)

**Current code (approximate):**
```python
decision = body.decision if body.decision in ("approved", "watchlist") else "approved"
```

**Required change:** Replace silent fallback with explicit validation. If `body.decision` is not in the allowed set, raise `HTTPException(status_code=422, detail=...)`. The allowed set for the approve endpoint is `{"approved", "watchlist"}`. For the reject endpoint, the allowed value is `{"rejected"}`.

**Acceptance criteria:**
- `POST /universe/funds/{id}/approve` with `decision="garbage"` returns 422
- `POST /universe/funds/{id}/approve` with `decision="approved"` still works
- `POST /universe/funds/{id}/approve` with `decision="watchlist"` still works
- Error response body includes the invalid value and the allowed set
- Run existing tests to verify no regression

---

### BL-01 — DD Report Approval: Add ConsequenceDialog Friction

**Backend change needed first (Agent B):**

**File:** `backend/app/domains/wealth/schemas/dd_report.py`

Create a new schema:
```python
class DDReportApproveRequest(BaseModel):
    rationale: str = Field(..., min_length=10, max_length=2000)
```

**File:** `backend/app/domains/wealth/routes/dd_reports.py` — approve endpoint (~line 273)

Add `body: DDReportApproveRequest` parameter. Store `body.rationale` on the report (check if `DDReport` model has an `approval_rationale` field — if not, the rationale can be stored as part of the status change metadata or a comment field; for now, at minimum log it and ensure the endpoint requires it).

**Frontend change (Agent C):**

**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

Current approve handler (~line 113):
```javascript
async function approveReport() {
    approving = true;
    actionError = null;
    try {
        const api = createClientApiClient(getToken);
        await api.post(`/dd-reports/${data.reportId}/approve`, {});
```

**Required change:**
1. Import `ConsequenceDialog` from `@netz/ui` (it is exported — verified)
2. Replace the direct `ActionButton` with a trigger that opens `ConsequenceDialog`
3. ConsequenceDialog props:
   - `title="Approve DD Report"`
   - `description="This report will become visible to investors upon approval."`
   - `confirmLabel="Approve for Distribution"`
   - `requireRationale={true}`
   - `consequenceList` snippet listing consequences (e.g., "Report will be published to investor portal", "Approval decision is recorded in audit trail")
4. On confirm, send `{ rationale }` to `POST /dd-reports/{report_id}/approve`
5. On success, `invalidateAll()`

**Acceptance criteria:**
- Clicking "Approve" opens ConsequenceDialog, NOT direct API call
- Rationale is mandatory (submit disabled when empty or < 10 chars)
- Consequence list is displayed
- Successful approval sends rationale to backend
- Existing approve flow completes successfully end-to-end

---

### BL-04 — DD Report Rejection: Upgrade to ConsequenceDialog

**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (~lines 271-299)

Current: custom `Dialog` with `FormField` textarea sending `{ reason }`.

**Required change:**
1. Replace custom Dialog with `ConsequenceDialog`
2. Props:
   - `title="Reject DD Report"`
   - `description="This report will return to draft status."`
   - `confirmLabel="Confirm Rejection"`
   - `variant="destructive"`
   - `requireRationale={true}`
   - `consequenceList` snippet (e.g., "Report returns to draft status", "Author will be notified", "Investor distribution is blocked until re-approval")
3. On confirm, send `{ reason: rationale }` to `POST /dd-reports/{report_id}/reject` (note: backend field is `reason`, not `rationale`)

**Acceptance criteria:**
- Rejection opens ConsequenceDialog with consequence list
- Rationale mandatory (min 10 chars, matching backend `DDReportRejectRequest` schema)
- Backend receives `{ reason }` field correctly
- Consistent friction pattern between approve (BL-01) and reject (BL-04)

**Notes:** BL-01 and BL-04 touch the same page — implement together in Agent C.

---

### BL-02 — Universe Rejection: Wire Rationale Textarea

**File:** `frontends/wealth/src/routes/(team)/universe/+page.svelte` (~lines 60-61, 263-271)

Current state: `rejectRationale` is declared (line 60), sent to API (line ~72: `rationale: rejectRationale.trim() || undefined`), but the `ConfirmDialog` at line 263 has no textarea. The dialog is a simple OK/Cancel.

**Required change:**
Replace the rejection `ConfirmDialog` with `ConsequenceDialog`:
1. Props:
   - `title="Reject Fund from Universe"`
   - `description="This instrument will be excluded from the investable universe."`
   - `confirmLabel="Confirm Rejection"`
   - `variant="destructive"`
   - `requireRationale={true}`
2. Bind rationale from ConsequenceDialog payload to `rejectRationale`
3. On confirm, send `{ decision: "rejected", rationale }` to the reject endpoint

**Acceptance criteria:**
- Rejection dialog renders with textarea for rationale
- Rationale < 10 chars blocks submission
- API receives non-empty rationale string
- `rejectRationale` state is properly reset after dialog closes

---

### BL-05 — Universe Approval: Add Rationale Capture

**File:** `frontends/wealth/src/routes/(team)/universe/+page.svelte`

Current approve call (~line 57): `{ decision: "approved" }` — no rationale.

**Required change:**
Replace the approval `ConfirmDialog` with `ConsequenceDialog`:
1. Props:
   - `title="Approve Fund into Universe"`
   - `description="This instrument will become eligible for portfolio allocation."`
   - `confirmLabel="Approve for Universe"`
   - `requireRationale={true}`
2. On confirm, send `{ decision: "approved", rationale }` to the approve endpoint

The backend already accepts optional `rationale` in `UniverseApprovalDecision` schema — no backend change needed.

**Acceptance criteria:**
- Approval opens ConsequenceDialog with rationale field
- Rationale is captured and sent to API
- Backend receives and stores rationale
- Existing approval flow completes successfully

---

## Verification checklist

After all items are implemented:

- [ ] `POST /universe/funds/{id}/approve` with `decision="invalid"` → 422
- [ ] DD report approve button → ConsequenceDialog with mandatory rationale
- [ ] DD report reject button → ConsequenceDialog with consequences + mandatory rationale
- [ ] Universe approve → ConsequenceDialog with mandatory rationale
- [ ] Universe reject → ConsequenceDialog with textarea for rationale (not empty)
- [ ] All existing happy paths still work (approve, reject, watchlist)
- [ ] Run `make test` — all tests pass
- [ ] No TypeScript errors in Wealth frontend (`pnpm check` in `frontends/wealth/`)

---

## Critical rules (from CLAUDE.md)

- **Async-first:** All route handlers use `async def` + `AsyncSession`
- **Pydantic schemas:** All routes use `response_model=` and return via `model_validate()`
- **Frontend formatter discipline:** Use `@netz/ui` formatters, never `.toFixed()` or inline `Intl.*`
- **lazy="raise":** All relationships. Forces explicit `selectinload()`/`joinedload()`
- **expire_on_commit=False:** Always
- Do not add features beyond scope. This sprint is strictly BL-01 through BL-05.

---

## What to do when this sprint is done

After completing all items and verifying the checklist:

1. Run `make test` to confirm all tests pass
2. Commit with a descriptive message covering all 5 BL items
3. **Prepare a handoff prompt** for the next agent session to execute **Sprint 2 — Governance Integrity (P1)**, covering:
   - BL-06: Wealth Status Enums and Database Constraints
   - BL-07: Wealth Audit Trail Event Logging and Query Endpoints

   Save the prompt to `docs/prompts/ux-remediation-sprint-2-governance-integrity.md`. The prompt must be self-contained and follow the same structure as this one: context, what you're fixing, exact files, required changes, acceptance criteria, verification checklist, execution strategy with parallel agents (model: sonnet), and a "what to do when done" section that tells the next agent to prepare Sprint 3's prompt. Include any findings from Sprint 1 that affect Sprint 2 (e.g., if the `DDReport` model needed schema changes, note them for the enum migration).

Do not implement Sprint 2. Only prepare its prompt.
