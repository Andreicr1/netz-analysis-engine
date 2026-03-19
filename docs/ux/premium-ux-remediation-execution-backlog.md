# Premium UX Remediation — Execution Backlog

Date: 2026-03-19
Source doctrine: `docs/ux/system-ux-principles.md`
Source audit: `docs/ux/principles-vs-implementation-audit.md`
Source remediation plan: `docs/ux/principles-audit-remediation-plan.md`
Source execution brief: `docs/ux/premium-ux-remediation-execution-brief.md`

---

## 1. Objective

Close the gap between the institutional UX doctrine and the actual system implementation across frontend, backend, and cross-vertical governance. The backlog covers critical safety fixes, governance integrity work, provenance visibility, structural consistency, and refinement — in that order of priority.

This is not a visual polish pass. It is a system-level remediation effort targeting operational trust, approval gravity, provenance clarity, workflow maturity, and cross-vertical governance parity.

---

## 2. Prioritization Model

| Level | Name | Definition |
|-------|------|------------|
| **P0** | Critical Risk | Bugs, silent failures, or missing friction on investor-facing or regulatory-grade actions. Ship immediately. |
| **P1** | Governance Integrity | Backend enum safety, audit trail coverage, state machine enforcement. Prevents silent data corruption and governance theater. |
| **P2** | System Legibility | Provenance visibility, evidence inspection, AI-generated content markers. Makes backend intelligence auditable in the frontend. |
| **P3** | Structural Consistency | Workflow archetype parity, status language normalization, component consolidation, investor archetype. Reduces vertical drift. |
| **P4** | Refinement and Perception | Dev enforcement, CI hardening, token documentation alignment, unused code cleanup. Prevents regression and improves developer experience. |

---

## 3. Backlog Items

---

### BL-01 — DD Report Approval: Add ConsequenceDialog Friction

**Priority:** P0 Critical Risk

**Problem:** Approving a DD report for investor distribution is a single `ActionButton` click with no confirmation dialog, no rationale capture, no consequence display, and no typed confirmation. This is the highest-impact action in Wealth (regulatory, investor-facing) and has the lowest friction in the entire system.

**Why it matters:** A mistakenly approved DD report becomes visible to investors. There is no recorded rationale for the decision. In a regulated fund management context, this is an audit finding. Credit deal stage transitions — lower-impact internal workflow moves — require `ConsequenceDialog` with typed confirmation and mandatory rationale. The severity is inverted relative to real-world impact.

**Scope:** Frontend only. Replace the approve `ActionButton` with `ConsequenceDialog`. `ConsequenceDialog` already exists in `@netz/ui` (284 lines, production-ready, supports `requireRationale`, `consequenceList`, `typedConfirmationText`, `metadata`).

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (lines 163-170)

**Dependencies:** None. Self-contained.

**Acceptance criteria:**
- DD report approval opens `ConsequenceDialog` with impact summary ("This report will become visible to investors"), mandatory rationale field, and confirm label "Approve for Distribution"
- Empty rationale blocks submission
- Existing approve happy path still works
- Backend receives rationale string alongside approval action

**Notes:** Verify `ConsequenceDialog` is in the `@netz/ui` barrel export accessible from Wealth frontend. It is exported — confirmed in component source.

---

### BL-02 — Universe Rejection: Wire Rationale Textarea into Dialog

**Priority:** P0 Critical Risk

**Problem:** `rejectRationale` state variable is declared (line 60) and sent to the API (`rationale: rejectRationale.trim() || undefined`), but the `ConfirmDialog` at line 263 has no textarea field. Every universe rejection sends empty rationale to the API. This is a functional bug — the UI declares intent to capture rationale but never renders the input.

**Why it matters:** Universe rejection is a governance decision. Empty rationale means no audit trail for why an instrument was excluded. When auditors or compliance reviewers ask why a fund was rejected from the universe, there is no recorded answer.

**Scope:** Frontend only. Replace `ConfirmDialog` with a `Dialog` containing a bound `<textarea>` for rejection rationale. Add minimum length validation.

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/universe/+page.svelte` (lines 60-61, 263-271)

**Dependencies:** None. Self-contained.

**Acceptance criteria:**
- Universe rejection dialog renders a textarea bound to `rejectRationale`
- Rationale with fewer than 10 characters blocks submission
- API receives non-empty rationale string on rejection
- Existing rejection flow still completes successfully

**Notes:** Consider whether universe rejection should escalate to `ConsequenceDialog` (with consequence list) or remain a simpler `Dialog` with textarea. The rationale textarea is the minimum fix; `ConsequenceDialog` is the doctrine-aligned fix.

---

### BL-03 — Universe Approval: Reject Invalid Decision Values Server-Side

**Priority:** P0 Critical Risk

**Problem:** Backend universe routes accept decision values and validate that the current state is `pending` before mutation, but there is no explicit validation that the submitted decision value is a member of the allowed set. Without enum constraints on the database column (`String(30)` with `server_default="pending"`), any string can be written.

**Why it matters:** A malformed API request — from a frontend bug, a script, or an integration — could write an invalid decision value. Combined with bare string status fields, Wealth's data integrity depends entirely on convention and the absence of bugs.

**Scope:** Backend only. Add explicit validation that `decision` is in `{"approved", "watchlist", "rejected"}`. Return 422 for any other value.

**Likely areas affected:**
- `backend/app/domains/wealth/routes/universe.py`

**Dependencies:** None. Self-contained.

**Acceptance criteria:**
- `POST /universe/{id}/decision` with `decision="garbage"` returns 422 Unprocessable Entity
- Valid decisions (`approved`, `watchlist`, `rejected`) still work
- Error response includes the invalid value and the allowed set

**Notes:** This is an interim fix. BL-06 (Wealth Status Enums) is the structural fix that makes this validation permanent at the database level.

---

### BL-04 — DD Report Rejection Rationale: Upgrade to ConsequenceDialog

**Priority:** P0 Critical Risk

**Problem:** DD report rejection currently uses a custom `Dialog` with a `FormField` textarea (lines 271-299). While functional, it does not communicate consequences (rejected report may need re-generation, delay investor distribution timeline, require IC notification). It also diverges from the `ConsequenceDialog` pattern used for Credit deal stage transitions.

**Why it matters:** Rejection of a DD report is a governance decision with workflow consequences. The current dialog captures rationale but does not communicate the impact of the decision. This creates asymmetry: approval (BL-01, once fixed) will use `ConsequenceDialog`, but rejection uses a simpler dialog.

**Scope:** Frontend only. Replace custom rejection `Dialog` with `ConsequenceDialog` including consequence list and mandatory rationale.

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (lines 271-299)

**Dependencies:** BL-01 (should ship together for consistency).

**Acceptance criteria:**
- DD report rejection opens `ConsequenceDialog` with consequence list (e.g., "Report will return to draft status", "Author will be notified")
- Mandatory rationale field with minimum length
- Consistent friction pattern with approval (BL-01)

**Notes:** This may be shipped as part of BL-01 since both touch the same page.

---

### BL-05 — Universe Approval: Add Approval Friction

**Priority:** P0 Critical Risk

**Problem:** Universe approval (adding an instrument to the investable universe) uses `ConfirmDialog` — a simple OK/Cancel with no rationale, no consequence display. Approving an instrument into the universe is an IC-level governance decision that determines what is investable.

**Why it matters:** The universe defines the investable perimeter. An instrument approved into the universe is eligible for allocation. This is not a routine action — it has portfolio-level consequences.

**Scope:** Frontend only. Replace approval `ConfirmDialog` with `ConsequenceDialog` or add rationale capture.

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/universe/+page.svelte`

**Dependencies:** BL-02 (rejection fix should ship first or together).

**Acceptance criteria:**
- Universe approval opens a dialog with rationale field (at minimum) or full `ConsequenceDialog`
- Rationale is captured and sent to API
- Existing approval flow still completes successfully

**Notes:** Assess whether `ConsequenceDialog` is appropriate or whether a rationale-enabled `Dialog` suffices. The doctrine demands approval gravity proportional to real-world impact — universe approval has material impact.

---

### BL-06 — Wealth Status Enums and Database Constraints

**Priority:** P1 Governance Integrity

**Problem:** `DDReport.status` (`String(30)`, server_default `"draft"`) and `UniverseApproval.decision` (`String(30)`, server_default `"pending"`) are bare string fields with no enum constraint. Any value is accepted by the database. Credit defines all workflow states as Python enums with compile-time validation. A typo in a Wealth status string (`"pendig_approval"`) would pass all type checks and produce a silent bug.

**Why it matters:** This is the structural root cause behind multiple surface-level issues. Without enum safety, StatusBadge renders unknown states as neutral gray (governance theater), audit trail events record arbitrary strings, and the frontend resolver must guess at valid states. Credit has compile-time safety that Wealth lacks entirely.

**Scope:** Backend. Create `DDReportStatus` and `UniverseDecision` Python enums. Add `CheckConstraint` on database columns. Alembic migration to convert existing values. Update all routes to validate against enum.

**Likely areas affected:**
- `backend/app/domains/wealth/enums.py` (NEW)
- `backend/app/domains/wealth/models/dd_report.py` (lines 47-49)
- `backend/app/domains/wealth/models/universe_approval.py` (lines 38-40)
- `backend/app/domains/wealth/routes/dd_reports.py`
- `backend/app/domains/wealth/routes/universe.py`
- `backend/app/domains/wealth/schemas/` (response models)
- Alembic migration (NEW)

**Dependencies:** BL-03 (interim validation) should ship first. Migration must handle existing data.

**Acceptance criteria:**
- `DDReportStatus` enum: `draft`, `generating`, `ready_for_review`, `pending_approval`, `approved`, `rejected`, `published`
- `UniverseDecision` enum: `pending`, `approved`, `watchlist`, `rejected`
- Both are `str, Enum` subclasses (JSON-serializable)
- Database columns have `CheckConstraint` enforcing valid values
- Migration passes on existing data (run `SELECT DISTINCT status FROM dd_reports` first)
- All Wealth routes that mutate status/decision validate against enum
- StatusBadge resolvers updated with new enum values — no gray fallback for valid states
- Existing tests pass; new tests cover enum validation rejection

**Notes:** Run data audit before writing migration: `SELECT DISTINCT status FROM dd_reports` and `SELECT DISTINCT decision FROM universe_approvals` to map all existing values. Any unexpected values must be cleaned up in the migration.

---

### BL-07 — Wealth Audit Trail: Event Logging and Query Endpoints

**Priority:** P1 Governance Integrity

**Problem:** Wealth tracks only final approval state (`approved_by`, `approved_at` on DD reports; final `decision` on universe approvals). No event history. No audit query endpoint. Credit has full `AuditEvent` + `ReviewEvent` + `ReviewAssignment` tables and a `/decision-audit` query endpoint. A DD report that was rejected, revised, and then approved shows only the final approval — the rejection and its rationale are lost.

**Why it matters:** Audit trail is a regulatory requirement for institutional fund management. Without event history, compliance reviews cannot reconstruct the decision timeline. The backend already has `AuditEvent` infrastructure in `core/db/models.py` — Wealth simply does not use it.

**Scope:** Backend + Frontend. Extend `AuditEvent` model to cover Wealth domain events. Add audit trail logging to DD report and universe routes. Create query endpoints. Wire `AuditTrailPanel` (already exists in `@netz/ui`, 317 lines, production-ready) into Wealth pages.

**Likely areas affected:**
- `backend/app/core/db/models.py` (check `AuditEvent` model structure, may need new event_type values)
- `backend/app/domains/wealth/routes/dd_reports.py` (log status changes)
- `backend/app/domains/wealth/routes/universe.py` (log decisions)
- `backend/app/domains/wealth/services/` (if audit event creation belongs in service layer)
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (wire AuditTrailPanel)

**Dependencies:** BL-06 (enum-safe status values should exist before logging starts, to avoid recording arbitrary strings in audit events).

**Acceptance criteria:**
- `AuditEvent` rows created for: DD report status changes (draft → generating → approved, etc.), universe approval decisions
- Each event records: actor, timestamp, old value, new value, rationale (when captured)
- `GET /dd-reports/{reportId}/audit-trail` returns chronological event list
- `GET /universe/{instrumentId}/audit-trail` returns chronological event list
- DD report detail page renders `AuditTrailPanel` showing status change history
- Audit events are immutable (no UPDATE or DELETE on audit event rows)

**Notes:** Check `AuditEvent` model structure before extending — it may have Credit-specific fields that need generalization. `AuditTrailPanel` component supports custom entry renderers, grouping by date, and field change tracking.

---

### BL-08 — Evidence Pack Inspector: IC Memos

**Priority:** P2 System Legibility

**Problem:** `MemoEvidencePack.evidence_json` (frozen source of truth for IC memo chapter generation) is tracked in the database with full metadata (version_tag, token_count, model_version, is_current) but is never serialized to the frontend. Users see generated chapters but cannot inspect the evidence that produced them.

**Why it matters:** The doctrine's central demand is "make intelligence feel auditable." IC memos drive investment committee decisions. Without evidence inspection, a user cannot distinguish between a well-evidenced chapter and a hallucinated one. The backend already stores this data — the gap is purely a presentation gap.

**Scope:** Backend (new serialization endpoint or extend existing memo endpoints) + Frontend (Sheet-based evidence drawer per chapter).

**Likely areas affected:**
- Backend: IC memo routes (add evidence pack serialization)
- `frontends/credit/src/lib/components/ICMemoViewer.svelte` (add "View Sources" per chapter)
- `frontends/credit/src/lib/components/ICMemoStreamingChapter.svelte` (add trigger for evidence drawer)

**Dependencies:** None for backend. Frontend depends on evidence pack API being available.

**Acceptance criteria:**
- Each IC memo chapter has a "View Sources" action (button or link)
- Action opens `Sheet` component (already built in `@netz/ui`) showing: source document name, page range, extraction confidence, chunk ID
- Evidence data loads on demand (not included in initial page load unless lightweight)
- Empty evidence packs show a clear "No evidence sources recorded" message

**Notes:** Read `MemoEvidencePack.evidence_json` structure before designing the API contract — its schema may not be documented. Model version may be per-memo, not per-chapter — design accordingly.

---

### BL-09 — Evidence Pack Inspector: DD Reports

**Priority:** P2 System Legibility

**Problem:** Same gap as BL-08 but for Wealth DD reports. `DDChapter` tracks `critic_iterations`, `quant_data`, and `evidence_refs` but none is exposed in the UI.

**Why it matters:** DD reports are approved for investor distribution. Investors and compliance reviewers should be able to trace generated analysis back to evidence. This is particularly critical because DD reports go through an approval workflow — the approver should be able to inspect evidence quality before approving.

**Scope:** Backend (serialize DD chapter evidence) + Frontend (Sheet-based evidence drawer).

**Likely areas affected:**
- Backend: DD report routes (add evidence/chapter metadata serialization)
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

**Dependencies:** BL-01 and BL-04 (approval friction) should ship first. Evidence inspection makes approval friction meaningful — reviewers need to see evidence before deciding.

**Acceptance criteria:**
- Each DD report section has a "View Sources" action
- Action opens `Sheet` showing evidence references, quant data context, and critic iteration count
- Approver can inspect evidence before approving (evidence drawer accessible from approval screen)

**Notes:** Consider whether evidence inspection should be mandatory before approval (gated) or optional. The doctrine does not require mandatory inspection, but surfacing it in the approval flow increases governance quality.

---

### BL-10 — AI-Generated Content Markers on Memos and Reports

**Priority:** P2 System Legibility

**Problem:** IC memo chapters and DD report sections render as undifferentiated markdown. No inline indicator distinguishes AI-generated narrative from evidence-quoted or human-written content. The backend tracks `model_version`, `generated_at`, and `token_count` per chapter.

**Why it matters:** The doctrine requires that users can distinguish "raw evidence" from "model inference" and "generated narrative." Without markers, a reader cannot tell whether a passage is extracted evidence, deterministic calculation, or LLM-generated synthesis. This is not about distrust — it is about calibrating appropriate scrutiny.

**Scope:** Frontend only. Add a provenance caption below each chapter/section header: `"Generated by {model} on {date}"` using existing `--netz-text-caption` typography token and `--netz-info` semantic color.

**Likely areas affected:**
- `frontends/credit/src/lib/components/ICMemoStreamingChapter.svelte`
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

**Dependencies:** Backend must already serialize `model_version` and `generated_at` per chapter. Check if existing endpoints include these fields.

**Acceptance criteria:**
- Each AI-generated chapter/section displays a subdued caption with model and generation date
- Caption uses `--netz-text-caption` size and `--netz-info` color (calm, not alarming)
- Caption does not appear on human-written or manually edited content (requires distinguishing flag — check if `model_version` being non-null is a reliable indicator)
- Caption is consistent across Credit IC memos and Wealth DD reports

**Notes:** Avoid loud "AI WARNING" labels. The doctrine says "disciplined use of badges, captions, metadata treatment" — not alarm bells. A calm annotation is the correct treatment.

---

### BL-11 — Persistent Provenance Visibility on Document Detail Pages

**Priority:** P2 System Legibility

**Problem:** Document classification provenance is already rendered on Credit document detail pages (classification layer, model, confidence). The remediation plan's pressure test confirmed this. However, this provenance is page-specific — it does not persist in list views or summary contexts. A user reviewing a list of documents cannot see at a glance which were classified by rules vs. LLM.

**Why it matters:** Provenance visibility at the document level is satisfied, but system-level provenance (seeing patterns across documents) is not. If 90% of a fund's documents were classified by LLM fallback, that signals potential classification rule gaps — but this is only visible by opening each document individually.

**Scope:** Frontend. Add classification method indicator (icon or badge) to document list views.

**Likely areas affected:**
- Credit document list pages (pipeline document tables)
- Wealth document list pages (if they exist)

**Dependencies:** Backend already serves classification_layer in document list endpoints (verify).

**Acceptance criteria:**
- Document list views show a compact classification method indicator per row (e.g., "Rules" / "Embed" / "LLM" badge)
- Indicator uses existing `StatusBadge` with appropriate severity mapping (rules=success, embeddings=info, LLM=warning)

**Notes:** This is lower priority within P2 because individual document provenance already works. The gap is aggregated visibility.

---

### BL-12 — StatusBadge Unknown State Dev Warning

**Priority:** P2 System Legibility

**Problem:** `StatusBadge` silently renders unrecognized states as neutral gray (line 74 falls back to "neutral"). No console warning, no dev-mode indicator. A new backend state shipped without updating the frontend resolver renders as an uninformative gray badge. Combined with Wealth's string-based status fields, this is a silent failure path.

**Why it matters:** The gray fallback creates governance theater — the badge looks intentional but carries no information. Without a dev warning, this is undetectable until a user reports it. The visual layer masks backend/frontend drift.

**Scope:** Shared component. Add `console.warn()` in dev mode for unrecognized tokens. Add `dev-unknown` CSS class (dashed border) in development builds.

**Likely areas affected:**
- `packages/ui/src/lib/components/StatusBadge.svelte` (line 74, fallback logic)

**Dependencies:** None. Can ship independently.

**Acceptance criteria:**
- `console.warn('StatusBadge: unrecognized status "{token}"')` fires in dev mode for unknown tokens
- Dashed border renders on unknown tokens in dev builds only (no production visual change)
- Known "neutral" statuses (explicitly listed) do not trigger the warning

**Notes:** Define an explicit `NEUTRAL_STATUSES` set so that intentionally-neutral states like "inactive" or "archived" don't trigger false positives.

---

### BL-13 — Wealth DD Report Detail: Wire AuditTrailPanel

**Priority:** P3 Structural Consistency

**Problem:** Credit has audit trail visibility on deal detail pages (DealStageTimeline, decision audit). Wealth DD report detail page shows only current status — no history. After BL-07 adds audit trail events, the frontend must surface them.

**Why it matters:** Workflow visibility requires seeing not just current state but how the system got there. A DD report marked "approved" with no visible history leaves reviewers unable to verify that proper process was followed.

**Scope:** Frontend only (depends on BL-07 backend). Wire `AuditTrailPanel` (exists in `@netz/ui`, 317 lines, supports custom renderers) into DD report detail page.

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

**Dependencies:** BL-07 (audit trail query endpoint must exist).

**Acceptance criteria:**
- DD report detail page shows audit trail panel with status change history
- Each event shows: actor, timestamp, old/new status, rationale (when available)
- Panel is collapsible or positioned to not overwhelm the main content

**Notes:** `AuditTrailPanel` supports grouping by date and field change tracking — leverage these features for multi-event histories.

---

### BL-14 — Universe Page: Decision History per Instrument

**Priority:** P3 Structural Consistency

**Problem:** Universe page shows only current decision state per instrument. No history of past decisions. After BL-07, audit trail events exist — they need a frontend surface.

**Why it matters:** An instrument that was rejected, then later approved, has a decision history that matters for compliance. Showing only the final state hides the governance process.

**Scope:** Frontend only. Add expandable decision history per instrument row or link to audit trail.

**Likely areas affected:**
- `frontends/wealth/src/routes/(team)/universe/+page.svelte`

**Dependencies:** BL-07 (audit trail query endpoint must exist).

**Acceptance criteria:**
- Universe page shows decision history per instrument (at minimum: last decision + actor, expandable to full history)
- History loaded on demand (not in initial page load)

**Notes:** Consider whether this is inline expansion in the table or a link to a detail view. Table expansion is more immediate but adds complexity.

---

### BL-15 — Status Language Normalization: Casing and Vocabulary

**Priority:** P3 Structural Consistency

**Problem:** Credit uses `UPPER_CASE` Python enums. Wealth uses `lower_case` strings. Shared vocabulary (`PENDING/pending`, `APPROVED/approved`, `REJECTED/rejected`) overlaps semantically but differs in casing. `StatusBadge` normalizes this visually (case-insensitive token matching), but the backend inconsistency creates maintenance risk and developer confusion.

**Why it matters:** When BL-06 creates Wealth enums, the casing convention must be decided. If Wealth enums use `lower_case` values while Credit uses `UPPER_CASE`, the visual normalization masks a structural inconsistency. This should be resolved as part of enum creation, not as separate work.

**Scope:** Decision + implementation as part of BL-06.

**Likely areas affected:**
- `backend/app/domains/wealth/enums.py` (NEW, from BL-06)
- `StatusBadge` resolver functions in both frontends

**Dependencies:** BL-06. This is a sub-decision within BL-06, not separate work.

**Acceptance criteria:**
- Wealth enums use a consistent casing convention (recommendation: `lower_case` for Wealth to match existing data, but document the cross-vertical casing divergence)
- All StatusBadge resolvers explicitly map every valid enum value — no reliance on auto-inference for valid states
- Auto-inference fallback to neutral is reserved for genuinely unknown states only

**Notes:** Do not force Credit to change casing — that would require a Credit migration for no user benefit. Accept the casing divergence but ensure StatusBadge resolvers are explicit.

---

### BL-16 — Investor Page Archetype Differentiation

**Priority:** P3 Structural Consistency

**Problem:** Investor-facing pages are visually identical to internal operational pages except for navigation chrome (`InvestorShell` instead of `TopNav`). Same `Card`, same `DataTable`, same `StatusBadge`, same surface tokens. The doctrine demands investor pages "feel cleaner and calmer than internal operational pages."

**Why it matters:** Investor pages are read-only distribution surfaces. Displaying them with the same density, shadows, and action affordances as internal operational pages creates false complexity. Investors should not see a surface that looks like it expects input — it should look like it presents curated output.

**Scope:** Shared component + frontend. Add `variant="investor"` to `Card.svelte`. Apply across all `(investor)` route pages.

**Likely areas affected:**
- `packages/ui/src/lib/components/Card.svelte` (add variant prop)
- All `(investor)` route pages in `frontends/credit/` (documents, statements, report-packs)
- All `(investor)` route pages in `frontends/wealth/` (fact-sheets, inv-documents, inv-portfolios, inv-dd-reports, reports)

**Dependencies:** None.

**Acceptance criteria:**
- `Card variant="investor"` renders: `border-subtle` only, no shadow, increased padding, `body-lg` default typography
- All investor route pages use the investor variant exclusively
- No action buttons (edit, delete, configure) appear in investor Card headers
- Side-by-side screenshot comparison of internal vs investor page shows clear archetype difference

**Notes:** "Calmer" is subjective. Define the CSS diff explicitly to prevent scope creep. The variant should be purely CSS — no structural changes to Card internals.

---

### BL-17 — IngestionProgress Component Consolidation

**Priority:** P3 Structural Consistency

**Problem:** `IngestionProgress.svelte` exists identically in both `frontends/credit/src/lib/components/` and `frontends/wealth/src/lib/components/` (69 lines each). The only difference is the status resolver import (`resolveCreditStatus` vs `resolveWealthStatus`) and one `type="review"` prop on a StatusBadge.

**Why it matters:** This is the only cross-vertical component duplication in the codebase. Both frontends otherwise import exclusively from `@netz/ui` for shared primitives. Leaving the duplication creates a maintenance risk — a fix in one copy will be missed in the other.

**Scope:** Move `IngestionProgress.svelte` to `@netz/ui` with a `resolveStatus` prop for vertical-specific resolver injection.

**Likely areas affected:**
- `packages/ui/src/lib/components/IngestionProgress.svelte` (NEW)
- `packages/ui/src/lib/index.ts` (add export)
- `frontends/credit/src/lib/components/IngestionProgress.svelte` (DELETE)
- `frontends/wealth/src/lib/components/IngestionProgress.svelte` (DELETE)
- Import sites in both frontends

**Dependencies:** None.

**Acceptance criteria:**
- Single `IngestionProgress` component in `@netz/ui` with resolver prop
- Both frontends import from `@netz/ui` and pass their vertical resolver
- No duplicate files remain in frontend `src/lib/components/`

**Notes:** Low effort, high signal — demonstrates consolidation discipline.

---

### BL-18 — Remove Internal-Only Noise from Investor Surfaces

**Priority:** P3 Structural Consistency

**Problem:** Investor pages may display operational metadata (ingestion status, pipeline stage, classification layer) that is meaningful to internal users but noise for investors. The audit did not enumerate specific instances, but the doctrine warns against surfacing internal-only information on investor pages.

**Why it matters:** Investor pages should present curated output, not operational state. Showing "INDEXED" status badges or classification confidence to an investor is meaningless at best and confusing at worst.

**Scope:** Audit all `(investor)` route pages for internal-only metadata exposure. Remove or hide operational fields that have no investor meaning.

**Likely areas affected:**
- All `(investor)` route pages in both frontends

**Dependencies:** BL-16 (investor archetype work provides the right context for this audit).

**Acceptance criteria:**
- No investor page displays: ingestion status, classification layer, classification confidence, pipeline stage, embedding metadata, or internal review status
- Investor pages display only: document name, date, type, download action, report content, portfolio positions, fund metrics
- Any operational field removal is verified against the investor API response (not just hidden in CSS)

**Notes:** This requires reading each investor page and its data contract. The scope may be small (investor APIs may already filter operational fields) or non-trivial (if investor pages render the same schemas as internal pages).

---

### BL-19 — ESLint CI Enforcement for Frontends

**Priority:** P4 Refinement and Perception

**Problem:** `frontends/eslint.config.js` (lines 18-44) bans `.toFixed()`, `.toLocaleString()`, `new Intl.NumberFormat()`, and `new Intl.DateTimeFormat()`. However, `make check` does not run ESLint on frontends. `frontends/wealth/src/lib/stores/stale.ts` (lines 14-23, 89) already violates these rules. Without CI enforcement, violations will accumulate.

**Why it matters:** The formatter discipline is near-perfect today (confirmed by audit). But enforcement on paper without CI integration is governance theater — the same pattern this backlog criticizes in other areas. One known violation already exists; more will follow without automated detection.

**Scope:** Build system. Add `pnpm lint` to `make check` or create `make lint-frontend`. Fix `stale.ts` violation. Verify all frontends pass.

**Likely areas affected:**
- `Makefile`
- `frontends/wealth/src/lib/stores/stale.ts` (lines 14-23, 89)
- Potentially other files if ESLint surfaces unknown violations

**Dependencies:** None.

**Acceptance criteria:**
- `make check` (or `make check-full`) runs frontend ESLint and fails on violations
- `stale.ts` passes ESLint with no formatter violations
- CI pipeline (GitHub Actions) runs the frontend lint step
- No existing frontend file has ESLint violations (clean baseline before enforcement)

**Notes:** Running ESLint across all frontends may surface violations beyond `stale.ts`. Budget time for a fix pass before enabling CI enforcement. Verify whether Turborepo's existing `check` task includes ESLint or only `svelte-check`.

---

### BL-20 — Branding Override Safety: Contrast Validation

**Priority:** P4 Refinement and Perception

**Problem:** `branding.ts` maps `BrandingConfig` fields to CSS custom properties via `Element.style.setProperty()` on the document root. This includes all core surface and text tokens. A tenant with misconfigured branding can override the entire surface hierarchy — `text_primary: #ffffff` and `surface_color: #fefefe` would make text invisible. No contrast ratio validation exists.

**Why it matters:** Token governance is meaningless if a tenant can override all tokens without validation. In a multi-tenant institutional product, branding misconfiguration should fail safely, not silently break the interface.

**Scope:** Backend validation on branding configuration save + frontend fallback.

**Likely areas affected:**
- `branding.ts` (frontend)
- Backend branding configuration endpoint (if exists)

**Dependencies:** None.

**Acceptance criteria:**
- Branding configuration validates minimum contrast ratio (WCAG AA: 4.5:1) between text and surface colors
- Invalid branding configurations are rejected with specific error messages ("text_primary has insufficient contrast against surface_color")
- Alternatively: frontend fallback that detects insufficient contrast at runtime and reverts to default tokens

**Notes:** This is a defensive measure. If branding configuration is admin-only and rarely changed, the risk is low. If it's tenant-self-service, the risk is higher. Scope accordingly.

---

### BL-21 — Sign-In Page Token Compliance

**Priority:** P4 Refinement and Perception

**Problem:** Sign-in pages (credit, wealth, admin) contain ~10+ fallback hex colors in `var()` declarations, ~6 inline `rgba()` box-shadows, and ~15 hardcoded px spacing values. These are defensive CSS fallbacks but violate single-source-of-truth token governance.

**Why it matters:** Sign-in pages are the first surface users see. If tokens fail to load (SSR edge case, CSS loading race), the fallbacks kick in — but they may diverge from the token values, creating visual inconsistency. More importantly, these pages will partially break in dark mode because hardcoded hex colors don't respond to theme changes.

**Scope:** Frontend. Replace hardcoded values with token references. Remove or align fallback colors.

**Likely areas affected:**
- Sign-in pages in all three frontends (credit, wealth, admin)

**Dependencies:** None.

**Acceptance criteria:**
- Zero hardcoded hex colors outside `var()` declarations in sign-in pages
- All spacing uses token references or Tailwind classes mapped to the scale
- Sign-in pages render correctly in dark mode

**Notes:** Low risk, low urgency. These pages are not institutional workflow surfaces — they are entry points. Fix when convenient, not as a priority.

---

### BL-22 — ContextPanel Unused Code Cleanup

**Priority:** P4 Refinement and Perception

**Problem:** `ContextPanel.svelte` (186 lines) in `@netz/ui` is fully implemented but unused in any frontend. The original audit incorrectly claimed Sidebar and AppShell were also unused — they are not. Only ContextPanel is genuinely dead code.

**Why it matters:** Unused code creates false expectations. A developer finding `ContextPanel` in `@netz/ui` may assume it's meant to be used, spending time understanding it. If it has no planned use, it should be removed. If it does, it should be documented.

**Scope:** Decision: keep with documentation or remove. If keeping, add a comment explaining intended use. If removing, delete file and remove from barrel export.

**Likely areas affected:**
- `packages/ui/src/lib/components/ContextPanel.svelte`
- `packages/ui/src/lib/index.ts` (if exported)

**Dependencies:** None.

**Acceptance criteria:**
- Either: ContextPanel is removed from codebase and barrel export
- Or: ContextPanel has a comment explaining its intended future use case

**Notes:** 186 lines is not a maintenance burden. Bias toward keeping if there's a plausible future use (e.g., Wealth detail pages needing contextual navigation). Remove if it was speculative.

---

## 4. Dependency Map

```
BL-01 (DD approval friction)  ──┐
BL-02 (Universe rejection bug)  ├── Phase 1: Critical Safety (no deps)
BL-03 (Universe API validation)  │
BL-04 (DD rejection upgrade)  ──┘
BL-05 (Universe approval friction) ─┘

BL-06 (Wealth enums) ── depends on BL-03 (interim fix first)
                     └── includes BL-15 (casing decision)
BL-07 (Audit trail)  ── depends on BL-06 (enum-safe values before logging)

BL-08 (Evidence pack: memos) ── no backend deps (evidence_json already exists)
BL-09 (Evidence pack: DD reports) ── depends on BL-01/BL-04 (approval friction first)
BL-10 (AI content markers) ── needs model_version in API (verify)
BL-11 (List provenance) ── needs classification_layer in list API (verify)
BL-12 (StatusBadge warning) ── no deps

BL-13 (DD audit trail panel) ── depends on BL-07
BL-14 (Universe decision history) ── depends on BL-07
BL-16 (Investor archetype) ── no deps
BL-17 (IngestionProgress consolidation) ── no deps
BL-18 (Investor noise removal) ── best after BL-16

BL-19 (ESLint CI) ── no deps
BL-20 (Branding validation) ── no deps
BL-21 (Sign-in tokens) ── no deps
BL-22 (ContextPanel cleanup) ── no deps
```

---

## 5. Recommended Execution Phases

### Phase 1 — Critical Safety (P0)

Items: BL-01, BL-02, BL-03, BL-04, BL-05

**Gate:** All investor-facing and governance-grade approval/rejection actions across Wealth require explicit confirmation with rationale capture. No single-click approvals for consequential actions. Backend rejects invalid decision values.

### Phase 2 — Governance Integrity (P1)

Items: BL-06 (includes BL-15), BL-07

**Gate:** Wealth has enum-safe status fields with database constraints. Audit trail events are logged for all DD report and universe state changes. Query endpoints exist. StatusBadge resolvers updated.

### Phase 3 — System Legibility (P2)

Items: BL-08, BL-09, BL-10, BL-11, BL-12

**Gate:** Every AI-generated surface has provenance annotation. Evidence packs are inspectable on IC memos and DD reports. Document list views show classification method. Unknown StatusBadge states are flagged in development.

### Phase 4 — Structural Consistency (P3)

Items: BL-13, BL-14, BL-16, BL-17, BL-18

**Gate:** Audit trail is visible on DD report and universe pages. Investor pages are visually distinct from internal pages. IngestionProgress is consolidated. Investor surfaces are free of internal-only metadata.

### Phase 5 — Refinement (P4)

Items: BL-19, BL-20, BL-21, BL-22

**Gate:** CI catches frontend formatter violations. Branding overrides are validated or safe. Sign-in pages are token-compliant. Unused code is resolved.

---

## 6. System-Level Definition of Done

The remediation is complete when:

1. **No single-click approvals exist for investor-facing or regulatory-grade actions.** Every consequential action (DD report approval/rejection, universe approval/rejection) requires explicit confirmation with rationale capture.

2. **Wealth backend governance matches Credit's structural maturity.** Enum-safe status fields, database constraints, compile-time validation, audit trail event logging, and query endpoints.

3. **AI-generated content is visibly distinguished from evidence and deterministic data.** Provenance annotations appear on all generated chapters/sections. Evidence packs are inspectable.

4. **Cross-vertical workflow patterns are consistent.** The same action archetype (consequential decision) uses the same UI pattern (`ConsequenceDialog` with rationale) regardless of vertical.

5. **StatusBadge never silently misrepresents system state.** All valid enum values have explicit resolver mappings. Unknown values trigger dev warnings. No governance theater via gray fallback on valid states.

6. **Investor pages are architecturally distinct from internal pages.** Calmer, flatter, read-only-optimized. No internal-only metadata leaks.

7. **Dev enforcement is automated.** Frontend ESLint runs in CI. Violations block merge.

8. **Audit trail is visible wherever approval decisions are made.** Not just stored — rendered.

---

## 7. Open Questions / Validation Points

| # | Question | When to resolve | Who decides |
|---|----------|-----------------|-------------|
| 1 | Should universe approval use `ConsequenceDialog` (full friction) or a simpler rationale-enabled `Dialog`? | Phase 1 implementation | Product owner |
| 2 | Should evidence inspection be mandatory before DD report approval (gated) or optional? | Phase 3 implementation | Product owner + compliance |
| 3 | What casing convention should Wealth enums use? `lower_case` (matches existing data) or `UPPER_CASE` (matches Credit)? | BL-06 implementation | Engineering |
| 4 | Does `MemoEvidencePack.evidence_json` have a stable schema, or is it free-form JSON? | Before BL-08 | Backend review |
| 5 | Are model_version and generated_at already included in IC memo and DD report API responses? | Before BL-10 | API contract check |
| 6 | Does classification_layer appear in document list API responses, or only in individual document detail? | Before BL-11 | API contract check |
| 7 | Is branding configuration tenant-self-service or admin-only? | Before BL-20 scoping | Product owner |
| 8 | Should `ContextPanel.svelte` be retained for future Wealth detail page navigation? | Before BL-22 | Engineering / Product |
| 9 | How many existing DD reports and universe approvals have non-standard status strings that need migration cleanup? | Before BL-06 migration | Data audit (SQL) |
| 10 | Does Turborepo's existing `check` task include ESLint, or only `svelte-check`? | Before BL-19 | Build system check |
