# Principles Audit — Pressure Test & Remediation Plan

Source: `docs/ux/principles-vs-implementation-audit.md`
Date: 2026-03-19

---

## 1. Where the Audit Was Too Optimistic

### 1.1 P09 (Cross-Vertical Consistency) rated VALIDATED — should be PARTIALLY VALIDATED

The audit validated P09 because both frontends share tokens, components, and formatters. This is surface-level consistency. The doctrine (SS18) demands shared "process state language" and "action hierarchy" — not just shared CSS.

What the code actually shows:
- Credit defines all workflow states as Python enums with a hardcoded FSM (`VALID_TRANSITIONS` dict in `stage_transition.py:18-27`). Wealth uses bare `String(30)` fields with `server_default` values and no transition rules.
- Credit has a full `AuditEvent` + `ReviewEvent` + `ReviewAssignment` audit trail with a `/decision-audit` query endpoint. Wealth tracks only final state (`approved_by`, `approved_at`) — no history, no audit query endpoint.
- Credit's universe of valid states is compiler-enforced. Wealth's is convention-enforced. A typo in a Wealth status string passes all validation.
- Universe approval endpoint (`universe.py:157`) silently defaults unknown decision values to `"approved"` — `decision = body.decision if body.decision in ("approved", "watchlist") else "approved"`. This means a malformed request doesn't fail; it approves.

Calling this "validated" because the CSS tokens are shared is like calling a building structurally sound because the paint matches. The process layer is structurally divergent.

### 1.2 P07 (Workflow State Visibility) rated HIGH severity but analysis was incomplete

The audit correctly identified the ConsequenceDialog asymmetry but made a factual error: ConsequenceDialog IS used in Wealth on the allocation page (2 instances for strategic/tactical saves with rationale). The gap is specifically that **DD report approval and universe approval** — the two actions with investor-facing regulatory implications — use simpler dialogs.

The audit also missed:
- **Universe rejection rationale is broken.** `universe/+page.svelte` declares `rejectRationale` state (line 60-61) and sends it to the API (`rationale: rejectRationale.trim() || undefined`), but the ConfirmDialog at line 262 has no textarea field. The rationale is always empty. This isn't a design gap — it's a bug.
- **DD report approval has zero friction.** The approve button is a direct `ActionButton` (line 163-169) with no dialog at all. Not even a ConfirmDialog. Only rejection opens a dialog. Approving investor-facing content is a single click.

### 1.3 P08 (AI/Provenance Visibility) — audit overstated the gap

The audit claimed "almost none of this reaches the user" and "no frontend page renders their data." This is factually wrong:

- `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte` (lines 35-74, 141-150) renders classification layer (mapped to "Rules"/"Embeddings"/"LLM"), classification model, and classification confidence as percentage.
- `frontends/wealth/src/routes/(investor)/inv-dd-reports/+page.svelte` (lines 75-79) renders `confidence_score` and `decision_anchor` in the investor report list.

What IS genuinely missing: evidence pack inspection, model version on generated chapters, per-chapter source citations on memos/DD reports, and inline AI-generated markers on narrative content. The gap is real but the audit's framing was too absolute.

### 1.4 C3 (Built infrastructure vs actual usage) — audit claimed Sidebar/AppShell/ContextPanel are all unused

Factually incorrect:
- `AppShell.svelte` is used internally by `AppLayout.svelte` — the component every frontend imports. It's not dead code.
- `Sidebar.svelte` is imported in `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte`.
- Only `ContextPanel.svelte` is genuinely unused.

The audit inflated 577 lines of "dead code" to dramatize the finding. The real unused infrastructure is ~186 lines (ContextPanel only).

### 1.5 ME2 (Investor page archetype) — audit was too soft

The doctrine (SS21) says investor-facing pages must "feel cleaner and calmer than internal operational pages." The audit noted that investor pages use the same components as internal pages, then moved on. But the actual gap is worse:

- Investor pages are not "calmer" — they are simply *less*. Same Card, same DataTable, same StatusBadge, same surface tokens. The only difference is InvestorShell provides a minimal nav instead of TopNav. No differentiated typography weight, no reduced surface complexity, no calmer color treatment, no read-only-optimized data display. The doctrine asks for a distinct archetype; the implementation delivers a layout swap.

### 1.6 P15 (Status Language Consistency) rated MEDIUM — should be HIGH

The audit said "StatusBadge normalizes the visual output, so users see consistent colors." This masks the real problem: the frontend layer is papering over backend incoherence. When Wealth adds a new status value (which has happened — `generating`, `published`, `completed`, `pass`, `fail`, `watchlist`, `breach`, `crisis`, `risk_on` are all bare strings), it silently renders as neutral gray if nobody updates the resolver. The StatusBadge fallback is not a safety net — it's a silent failure mode.

Combined with Wealth's lack of enum constraints, this means: a new status can be introduced by a backend change, pass all type checks, render as an uninformative gray badge, and nobody notices until a user reports it. This is not medium severity — it's a governance hole.

---

## 2. Revised Severity and Status Adjustments

| Finding | Audit Rating | Revised Rating | Reason |
|---------|-------------|----------------|--------|
| P09 — Cross-Vertical Consistency | VALIDATED | **PARTIALLY VALIDATED, Medium** | Visual layer consistent; process layer structurally divergent (enums vs strings, FSM vs implicit, audit trail vs final-state-only) |
| P07 — Workflow State Visibility | PARTIALLY VALIDATED, High | **PARTIALLY VALIDATED, Critical** | DD report approval is zero-click (no dialog). Universe rejection rationale is broken (state exists but UI doesn't render it). Regulatory-grade actions have less friction than internal workflow moves |
| P08 — AI/Provenance Visibility | PARTIALLY VALIDATED, High | **PARTIALLY VALIDATED, High** | Provenance IS rendered for document classification. Gap is real but narrower: evidence pack, model version on chapters, inline AI markers, per-chapter citations |
| P15 — Status Language Consistency | PARTIALLY VALIDATED, Medium | **PARTIALLY VALIDATED, High** | Silent neutral fallback + no enum safety in Wealth = undetected status drift. Visual masking creates false confidence |
| ME2 — Investor page archetype | Missing Embodiment | **Missing Embodiment, High** | Not just "missing differentiation" — investor pages are indistinguishable from internal pages except for navigation chrome |
| C3 — Built infrastructure unused | Contradiction | **Downgraded to Low** | AppShell and Sidebar are used. Only ContextPanel (~186 lines) is genuinely unused |
| SR2 — Approval gravity gap | Structural Risk | **Critical** | DD report approval (investor distribution) is a single click with no dialog. Credit deal stage moves require typed confirmation + rationale. Severity is inverted relative to real-world impact |
| P01 (Shell) — Structural Frame | PARTIALLY VALIDATED, Medium | **PARTIALLY VALIDATED, Medium** | Confirmed: Wealth has no ContextSidebar for detail pages. Audit assessment was fair |
| HC1 — ESLint not enforced | Hidden Complexity | **High** | `stale.ts` already violates. Without CI, this will expand. Audit assessment was fair but severity should be explicit |

---

## 3. Top 10 Remediation Priorities

### Priority 1 — DD Report Approval Friction (Critical, ~2h)

**Problem:** Approving a DD report for investor distribution is a single ActionButton click with no confirmation dialog, no rationale capture, no consequence display. This is the highest-impact action in Wealth (regulatory, investor-facing) and has the lowest friction in the entire system.

**Fix:** Replace the approve ActionButton with ConsequenceDialog. Required fields: rationale (mandatory), impact summary ("This report will become visible to investors"), consequence list. Match Credit's document review pattern.

**File:** `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte` (lines 163-169)

### Priority 2 — Universe Rejection Rationale Bug (Critical, ~1h)

**Problem:** `rejectRationale` state variable exists but the ConfirmDialog doesn't render a textarea for it. Every universe rejection sends empty rationale to the API. This is a functional bug, not a design gap.

**Fix:** Replace ConfirmDialog with a Dialog containing a textarea for rejection rationale. Validate minimum length before allowing submission.

**File:** `frontends/wealth/src/routes/(team)/universe/+page.svelte` (lines 60-61, 262-272)

### Priority 3 — Universe Approval Silent Default (Critical, ~30min)

**Problem:** `universe.py:157` defaults unknown decision values to `"approved"` instead of rejecting them. A malformed API request approves an instrument.

**Fix:** Reject unknown decision values with 422 Unprocessable Entity. Only accept `"approved"` and `"watchlist"` explicitly.

**File:** `backend/app/domains/wealth/routes/universe.py` (line 157)

### Priority 4 — Wealth Status Enums (High, ~4h)

**Problem:** `DDReport.status` and `UniverseApproval.decision` are bare strings with no database constraint. Any value is accepted.

**Fix:** Create `DDReportStatus` and `UniverseDecision` Python enums. Add `CheckConstraint` on database columns. Alembic migration to convert existing values. Update routes to validate against enum.

**Files:**
- `backend/app/domains/wealth/models/dd_report.py` (line 47-49)
- `backend/app/domains/wealth/models/universe_approval.py` (line 38-40)
- New: `backend/app/domains/wealth/enums.py`
- Migration required

### Priority 5 — Wealth Audit Trail (High, ~6h)

**Problem:** Wealth tracks only final approval state (approved_by, approved_at). No event history. No audit query endpoint. Credit has full `AuditEvent` + `ReviewEvent` tables and a `/decision-audit` endpoint.

**Fix:** Extend the existing `AuditEvent` model (already in `core/db/models.py`) to cover Wealth domain events. Add DD report status change events and universe decision events. Create `/dd-reports/{id}/audit-trail` endpoint. Wire `AuditTrailPanel` component into Wealth DD report detail page.

**Files:**
- `backend/app/domains/wealth/routes/dd_reports.py`
- `backend/app/domains/wealth/routes/universe.py`
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

### Priority 6 — Evidence Pack Inspector (High, ~8h)

**Problem:** `MemoEvidencePack.evidence_json` (frozen source of truth for chapter generation) is never serialized to the frontend. Users see generated chapters but cannot inspect the evidence that produced them. This is the doctrine's central demand: "make intelligence feel auditable."

**Fix:** Add a "View Sources" drawer/panel to ICMemoViewer and DD report chapter view. Serialize evidence pack via API. Display source documents, page references, and extraction metadata per chapter. Use Sheet component (already built).

**Files:**
- Backend: New serialization endpoint or extend existing memo/DD report endpoints
- `frontends/credit/src/lib/components/ICMemoViewer.svelte`
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

### Priority 7 — AI-Generated Content Markers (High, ~4h)

**Problem:** Memo chapters and DD report sections render as undifferentiated markdown. No inline indicator distinguishes AI-generated narrative from evidence-quoted or human-written content.

**Fix:** Add a subtle "AI-generated" caption below each chapter header with model version and generation timestamp. Use existing `--netz-text-caption` typography token and `--netz-info` semantic color. Not a loud warning — a calm provenance annotation.

**Files:**
- `frontends/credit/src/lib/components/ICMemoStreamingChapter.svelte`
- `frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte`

### Priority 8 — StatusBadge Unknown State Warning (Medium, ~1h)

**Problem:** StatusBadge silently renders unrecognized states as neutral gray. No console warning, no dev-mode indicator. New backend states can ship without frontend awareness.

**Fix:** Add `console.warn()` in dev mode when `inferSeverity` falls to neutral for a token not in an explicit "neutral" set. Add a `dev-unknown` CSS class that renders a dashed border in development builds.

**File:** `packages/ui/src/lib/components/StatusBadge.svelte` (lines 55-75)

### Priority 9 — ESLint CI Enforcement (Medium, ~2h)

**Problem:** ESLint formatter rules exist but `make check` doesn't run them on frontends. `stale.ts` already violates. Without CI enforcement, violations will accumulate.

**Fix:** Add `pnpm lint` to `make check` or create `make lint-frontend`. Fix `stale.ts` violation. Verify all frontends pass.

**Files:**
- `Makefile`
- `frontends/wealth/src/lib/stores/stale.ts` (lines 14-23, 89)

### Priority 10 — Investor Page Archetype Differentiation (Medium, ~6h)

**Problem:** Investor pages are visually identical to internal pages minus navigation. The doctrine demands they "feel cleaner and calmer."

**Fix:** Create an `InvestorCard` variant or CSS class that applies: reduced border weight (border-subtle only), no shadow (flat), slightly increased padding, body-lg typography default for content areas, no action buttons in card headers. Apply to all investor route pages. The goal is not a different design system — it's a read-only-optimized variant of the same system.

**Files:**
- `packages/ui/src/lib/components/Card.svelte` (add `variant="investor"` prop)
- All `(investor)` route pages in both frontends

---

## 4. Sequencing Plan

### Phase 1 — Critical Safety (Priorities 1-3, ~4h)

These are bugs and security issues, not design improvements. Ship independently.

1. DD report approval → ConsequenceDialog with mandatory rationale
2. Universe rejection → wire rationale textarea into dialog
3. Universe approval → reject unknown decision values server-side

**Gate:** All investor-facing approval actions require explicit confirmation with rationale capture.

### Phase 2 — Backend Governance Parity (Priorities 4-5, ~10h)

Structural fixes that bring Wealth's backend governance to Credit's standard.

4. Wealth status enums + CheckConstraints + migration
5. Wealth audit trail events + query endpoint

**Gate:** Wealth has enum-safe status fields and queryable audit history. StatusBadge resolvers updated for new enum values.

### Phase 3 — Provenance Surfaces (Priorities 6-8, ~13h)

The doctrine's central demand. Requires Phase 2 complete for audit trail data.

6. Evidence pack inspector (Sheet-based, per chapter)
7. AI-generated content markers (caption annotations)
8. StatusBadge unknown state warning (dev-mode safety net)

**Gate:** Every AI-generated surface has provenance annotation. Evidence is inspectable. Unknown states are flagged in development.

### Phase 4 — Enforcement & Polish (Priorities 9-10, ~8h)

Hardening and archetype work.

9. ESLint CI enforcement
10. Investor page archetype differentiation

**Gate:** CI catches formatter violations. Investor pages are visually distinct from internal pages.

---

## 5. Risks If No Action Is Taken

### Regulatory Exposure (Critical)

DD report approval is a single click with no confirmation, no rationale, no audit trail beyond `approved_by`. If a report is mistakenly approved and distributed to investors, there is no recorded rationale for the decision and no friction that would have caught the mistake. In a regulated fund management context, this is an audit finding waiting to happen.

### Silent Data Corruption (High)

Universe approval endpoint defaults unknown decision values to `"approved"`. A malformed API request — from a frontend bug, a script, or an integration — will silently approve instruments. Combined with bare string status fields and no enum constraints, Wealth's data integrity depends entirely on convention and the absence of bugs.

### Governance Theater (High)

The StatusBadge normalizes visual output across inconsistent backends. This creates an appearance of consistency that masks structural divergence. Stakeholders reviewing the product will see matching colors and assume matching governance. They will be wrong. The visual layer is doing the backend's job, and it does it by hiding information (unknown states render as neutral gray, not as errors).

### Provenance Debt Compounds (Medium)

The backend already tracks classification layers, confidence scores, model versions, evidence pack hashes, and critic iterations. Every sprint where the frontend doesn't surface this data is a sprint where backend investment delivers zero user value. Worse: unconsumed endpoints drift from the frontend's data contract, making future integration harder. The longer this waits, the more expensive it becomes.

### Vertical Drift (Medium)

Credit has enums, FSMs, full audit trails, ConsequenceDialog friction, and ContextSidebar navigation. Wealth has strings, implicit transitions, final-state-only tracking, single-click approvals, and flat navigation. If this asymmetry isn't addressed, the two verticals will continue diverging in governance maturity while sharing a visual surface that makes them look equivalent. This is the definition of technical debt that compounds invisibly.
