# Premium UX Remediation — Execution Brief

Source: `docs/ux/principles-audit-remediation-plan.md`
Date: 2026-03-19

---

## 1. Objective

Bring Wealth frontend and backend governance to parity with Credit, close critical safety gaps in investor-facing approval flows, surface AI provenance data already tracked by the backend, and harden developer enforcement to prevent regression.

---

## 2. Non-Negotiable Fixes

These must ship before any design-layer work. They are bugs and security issues.

| # | Issue | Severity | Current behavior | Required behavior |
|---|-------|----------|-----------------|-------------------|
| 1 | DD report approval — zero friction | Critical | Single ActionButton click, no dialog, no rationale | ConsequenceDialog with mandatory rationale + impact summary |
| 2 | Universe rejection rationale — broken | Critical | `rejectRationale` state exists but ConfirmDialog has no textarea; rationale is always empty | Dialog with textarea, min-length validation before submit |
| 3 | Universe approval silent default | Critical | Unknown decision values default to `"approved"` | 422 Unprocessable Entity for any value outside `{"approved", "watchlist"}` |

---

## 3. Workstreams

### WS1 — Critical Safety

**Scope:** Fix the three non-negotiable items above. Frontend dialog upgrades + one backend validation fix.

**Files affected:**

| File | Change |
|------|--------|
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (lines 163-169) | Replace ActionButton with ConsequenceDialog. Props: `title="Approve DD Report"`, `consequence="This report will become visible to investors"`, rationale mandatory, confirm label "Approve for Distribution" |
| `frontends/wealth/src/routes/(team)/universe/+page.svelte` (lines 60-61, 251-272) | Replace rejection ConfirmDialog with a Dialog containing a `<textarea>` bound to `rejectRationale`. Validate `rejectRationale.trim().length >= 10` before enabling submit |
| `backend/app/domains/wealth/routes/universe.py` (line 157) | Replace `decision = body.decision if body.decision in ("approved", "watchlist") else "approved"` with explicit validation: if decision not in allowed set, raise `HTTPException(422)` |

**Dependencies:** None. Self-contained.

**Acceptance criteria:**
- [ ] DD report approval opens ConsequenceDialog with mandatory rationale field. Empty rationale blocks submission.
- [ ] Universe rejection dialog renders textarea. Rationale of <10 chars blocks submission. API receives non-empty rationale string.
- [ ] `POST /universe/{id}/decision` with `decision="garbage"` returns 422, not silent approval.
- [ ] Existing approve/reject happy paths still work (regression).

**Risks:**
- ConsequenceDialog import may need wiring in the Wealth frontend if not already in the barrel export. Verify `@netz/ui` exports it.

---

### WS2 — Backend Governance Parity

**Scope:** Replace bare string status/decision fields with Python enums + DB constraints. Add audit trail event logging for Wealth approval actions.

**Files affected:**

| File | Change |
|------|--------|
| `backend/app/domains/wealth/enums.py` (NEW) | Create `DDReportStatus` enum (`draft`, `generating`, `ready_for_review`, `approved`, `rejected`, `published`) and `UniverseDecision` enum (`approved`, `watchlist`, `rejected`) |
| `backend/app/domains/wealth/models/dd_report.py` (lines 47-49) | Change `status` column from `String(30)` to use `DDReportStatus` enum. Add `CheckConstraint` |
| `backend/app/domains/wealth/models/universe_approval.py` (lines 38-40) | Change `decision` column from `String(30)` to use `UniverseDecision` enum. Add `CheckConstraint` |
| `backend/app/domains/wealth/routes/dd_reports.py` | Validate status transitions against enum. Log `AuditEvent` on status change. Add `GET /dd-reports/{id}/audit-trail` endpoint |
| `backend/app/domains/wealth/routes/universe.py` | Validate decision against enum. Log `AuditEvent` on decision. Add `GET /universe/{id}/audit-trail` endpoint |
| Alembic migration (NEW) | `ALTER TABLE` to add check constraints on existing `status`/`decision` columns. Migrate any non-conforming values first |

**Dependencies:** WS1 must be complete (universe route validation fix ships first).

**Acceptance criteria:**
- [ ] `DDReportStatus` and `UniverseDecision` are Python `str, Enum` subclasses in `backend/app/domains/wealth/enums.py`
- [ ] DB columns have `CheckConstraint` enforcing valid values. Migration passes on existing data.
- [ ] All Wealth routes that mutate status/decision validate against enum (no bare string assignment).
- [ ] `AuditEvent` rows are created for: DD report status changes, universe approval decisions.
- [ ] `GET /dd-reports/{reportId}/audit-trail` returns chronological list of status change events with actor, timestamp, old/new value.
- [ ] `GET /universe/{instrumentId}/audit-trail` returns chronological list of decision events.
- [ ] StatusBadge resolvers updated with new enum values (no gray fallback for valid states).
- [ ] Existing tests pass. New tests cover enum validation and audit trail endpoints.

**Risks:**
- Migration must handle existing data with unexpected string values. Run `SELECT DISTINCT status FROM dd_reports` and `SELECT DISTINCT decision FROM universe_approvals` before writing migration to map all existing values.
- `AuditEvent` model in `core/db/models.py` may need new `event_type` values for Wealth. Check its structure before extending.

---

### WS3 — Provenance Surfaces

**Scope:** Surface AI provenance data already tracked by the backend: evidence packs, model versions, generation timestamps, and AI-generated content markers.

**Files affected:**

| File | Change |
|------|--------|
| Backend: memo/DD report endpoints | Add `evidence_pack` field to serialization (or new `GET /memos/{id}/evidence` endpoint). Include source document refs, page numbers, extraction metadata per chapter |
| `frontends/credit/src/lib/components/ICMemoViewer.svelte` | Add "View Sources" button per chapter that opens Sheet component with evidence pack data |
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` | Add "View Sources" drawer per section. Same Sheet-based pattern as Credit |
| `frontends/credit/src/lib/components/ICMemoStreamingChapter.svelte` | Add provenance caption below chapter header: model version + generation timestamp. Use `--netz-text-caption` token, `--netz-info` color |
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` | Same provenance caption on DD report sections |
| `packages/ui/src/lib/components/StatusBadge.svelte` (lines 55-75) | Add `console.warn()` in dev mode when `inferSeverity` returns neutral for an unrecognized token. Add `dev-unknown` CSS class (dashed border) in dev builds |

**Dependencies:** WS2 should be complete so audit trail data is available alongside provenance. Evidence pack API may be independent.

**Acceptance criteria:**
- [ ] Each IC memo chapter has a "View Sources" action that opens a Sheet showing: source document name, page range, extraction confidence, chunk ID.
- [ ] Each DD report section has equivalent "View Sources" functionality.
- [ ] AI-generated chapters/sections display a caption: `"Generated by {model} on {date}"` in subdued typography.
- [ ] Caption does not appear on human-written or edited content (requires `is_ai_generated` or equivalent flag).
- [ ] StatusBadge logs `console.warn('StatusBadge: unrecognized status "{token}"')` in dev mode for unknown tokens.
- [ ] StatusBadge renders dashed border on unknown tokens in dev builds only (no production visual change).

**Risks:**
- `MemoEvidencePack.evidence_json` structure may not be documented. Read the model and any existing serialization before designing the API contract.
- Model version may not be stored per-chapter — could be per-memo only. Design caption accordingly.
- "View Sources" Sheet requires a loading state if evidence is fetched on-demand vs. included in initial page load.

---

### WS4 — Workflow Archetype Consistency

**Scope:** Align Wealth workflow patterns with Credit's established archetypes: ConsequenceDialog for consequential actions, typed state machines for status transitions.

This workstream is largely satisfied by WS1 + WS2. Remaining work:

| File | Change |
|------|--------|
| `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` | Wire `AuditTrailPanel` (or equivalent timeline component) into DD report detail page showing status history from WS2's audit trail endpoint |
| `frontends/wealth/src/routes/(team)/universe/+page.svelte` | Add decision history display (inline or expandable) per instrument showing past decisions from audit trail endpoint |

**Dependencies:** WS2 (audit trail endpoints must exist).

**Acceptance criteria:**
- [ ] DD report detail page shows status change history with actor + timestamp + rationale.
- [ ] Universe page shows decision history per instrument (at minimum: last decision + actor).
- [ ] All consequential Wealth actions (approve, reject, status change) use ConsequenceDialog or equivalent friction pattern.

**Risks:**
- Timeline/audit trail UI component may not exist in `@netz/ui`. Check if Credit has one that can be extracted, or build a minimal version.

---

### WS5 — Investor Archetype Refinement

**Scope:** Differentiate investor-facing pages from internal operational pages per doctrine SS21: "cleaner and calmer."

**Files affected:**

| File | Change |
|------|--------|
| `packages/ui/src/lib/components/Card.svelte` | Add `variant="investor"` prop. Investor variant: `border-subtle` only, no shadow, increased padding (`p-6` vs `p-4`), `body-lg` default typography, no action buttons in header |
| All `(investor)` route pages in `frontends/credit/` | Apply `variant="investor"` to Card components |
| All `(investor)` route pages in `frontends/wealth/` | Apply `variant="investor"` to Card components |

**Dependencies:** None, but lower priority than WS1-WS4.

**Acceptance criteria:**
- [ ] `Card variant="investor"` renders visually distinct from default Card: flatter, more padded, calmer.
- [ ] All investor route pages use the investor variant exclusively.
- [ ] No action buttons (edit, delete, configure) appear in investor Card headers.
- [ ] Side-by-side screenshot comparison of internal vs investor page shows clear archetype difference.

**Risks:**
- Investor route pages may be few (wealth has `inv-dd-reports`). Enumerate all `(investor)` route groups before estimating scope.
- "Calmer" is subjective. Define the CSS diff explicitly to avoid scope creep.

---

### WS6 — Dev Enforcement

**Scope:** Ensure formatter rules and status safety nets are enforced in CI, not just documented.

**Files affected:**

| File | Change |
|------|--------|
| `Makefile` | Add `lint-frontend` target: `cd frontends && pnpm lint`. Add to `check` target or create `check-full` that includes frontend lint |
| `frontends/wealth/src/lib/stores/stale.ts` (lines 14-23, 89) | Fix ESLint formatter violation (inline formatting instead of `@netz/ui` formatters) |
| `packages/ui/src/lib/components/StatusBadge.svelte` | Dev-mode warning (covered in WS3) |

**Dependencies:** WS3 StatusBadge changes.

**Acceptance criteria:**
- [ ] `make check` (or `make check-full`) runs frontend ESLint and fails on violations.
- [ ] `stale.ts` passes ESLint with no formatter violations.
- [ ] CI pipeline (GitHub Actions) runs the frontend lint step.
- [ ] No existing frontend file has ESLint violations (clean baseline).

**Risks:**
- Running ESLint across all frontends may surface violations beyond `stale.ts`. Budget time for a fix pass.
- Turborepo already runs `check` per package — verify this includes `eslint` or only `svelte-check`.

---

## 4. Suggested Implementation Order

```
WS1 Critical Safety          ███░░░░░░░  ~4h    Phase 1
WS2 Backend Governance Parity ░░░████████  ~10h   Phase 2
WS3 Provenance Surfaces       ░░░░░░░░░██████████████  ~13h   Phase 3
WS4 Workflow Consistency       ░░░░░░░░░░░░░████  ~4h    Phase 3 (parallel with WS3)
WS5 Investor Archetype        ░░░░░░░░░░░░░░░░░██████  ~6h    Phase 4
WS6 Dev Enforcement            ░░░░░░░░░░░░░░░░░░██  ~2h    Phase 4 (parallel with WS5)
```

**Phase 1 → Phase 2 gate:** All investor-facing actions require confirmation dialog with rationale.
**Phase 2 → Phase 3 gate:** Wealth has enum-safe status fields and queryable audit history.
**Phase 3 → Phase 4 gate:** AI-generated content has provenance annotations. Evidence is inspectable.
**Phase 4 exit gate:** CI catches formatter violations. Investor pages are visually distinct.

Total estimated effort: ~39h across 4 phases.

---

## 5. What Must Be Validated Manually After Implementation

These cannot be verified by automated tests alone:

| Check | Method | Who |
|-------|--------|-----|
| ConsequenceDialog copy matches regulatory tone | Visual review of dialog text and consequence messaging | Product owner |
| Investor Card variant is perceptibly "calmer" | Side-by-side screenshot comparison | Design review |
| AI provenance caption is subtle, not alarming | Visual review in context of full memo/report page | Product owner |
| Evidence pack drawer is navigable for non-technical users | Walkthrough with sample data | UX review |
| Audit trail timeline is readable at scale (>20 events) | Load test with realistic event count | QA |
| StatusBadge dev warning fires correctly and doesn't leak to production | Dev build vs prod build comparison | Developer |
| Universe rejection flow feels natural with new textarea dialog | End-to-end walkthrough | Product owner |
| DD report full approval→distribution flow has appropriate gravity | End-to-end walkthrough comparing with Credit deal stage transition | Product owner |

---

## 6. What Should Be Re-Audited After Completion

Run these checks after all 4 phases ship:

1. **P09 re-audit (Cross-Vertical Consistency):** Verify Credit and Wealth now share: enum-based status governance, audit trail architecture, ConsequenceDialog friction pattern, provenance annotation pattern. Surface-level consistency was already validated; re-audit must confirm process-layer parity.

2. **P07 re-audit (Workflow State Visibility):** Verify all consequential actions across both verticals require explicit confirmation. Check: DD report approve, DD report reject, universe approve, universe reject, deal stage transition, document review decision. All must have dialog + rationale capture.

3. **P08 re-audit (AI/Provenance Visibility):** Verify evidence pack is accessible for IC memos and DD reports. Verify AI-generated content markers appear on all generated chapters/sections. Verify classification provenance still renders on document detail pages.

4. **P15 re-audit (Status Language Consistency):** Verify no StatusBadge renders neutral gray for a valid Wealth status. Verify dev-mode warning fires for genuinely unknown tokens. Verify all `DDReportStatus` and `UniverseDecision` enum values have explicit severity mappings.

5. **SR2 re-audit (Approval Gravity):** Verify DD report approval friction is now >= Credit deal stage transition friction. The severity inversion identified in the original audit must be fully resolved.

6. **HC1 re-audit (ESLint Enforcement):** Run `make check` from clean state. Verify frontend lint runs and passes. Introduce a deliberate formatter violation and verify CI catches it.
