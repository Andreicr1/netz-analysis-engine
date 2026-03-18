# Credit UX Compliance Audit

Scope: Credit domain only.
Sources: `docs/ux/credit-frontend-ux-principles.md`, `docs/audit/frontend-system-map-v1.md`, `docs/audit/system-map-validation-report.md`, and the Credit/shared UI implementation under `frontends/credit` and `packages/ui`.

## 1
- Domain: Credit
- Principle: `"Every screen answers one question: "What requires action now?"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:108-141` renders KPI cards before the task list.
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:144-286` dedicates most of the page to pipeline analytics, macro data, and a FRED explorer.
- UI / Behavior Evidence:
  - The dashboard leads with summary metrics and analytical widgets rather than an operational inbox.
  - Action-taking is secondary to browsing and exploration.
- Gap Description:
  - The default dashboard state is not action-first. The dominant experience is monitoring, not triage.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Rebuild `frontends/credit/src/routes/(team)/dashboard/+page.svelte` so the first viewport is an action-required banner plus a dominant `TaskInbox`.
  - Move macro/FRED content below the fold or behind a collapsible secondary section.

## 2
- Domain: Credit
- Principle: `"Never default to a chart or summary when there are pending actions."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:114-135` shows four summary cards before the inbox.
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:149-286` always renders funnel, macro, and FRED panels.
- UI / Behavior Evidence:
  - The dashboard defaults to charts/summaries even when `taskInbox` exists.
- Gap Description:
  - Pending actions are present but are not the default visual priority.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - In `frontends/credit/src/routes/(team)/dashboard/+page.svelte`, render `TaskInbox` first when `data.taskInbox?.length > 0`.
  - Demote KPI/analytics panels to secondary regions and conditionally collapse them while actionable work exists.

## 3
- Domain: Credit
- Principle: `"Deal stage is always visible and unambiguous"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:127-140` shows a stage badge in deal detail.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:64-70` uses a plain `stage` column in a generic table rather than stage-driven Kanban identity.
  - `frontends/credit/src/lib/components/DealStageTimeline.svelte:19-32` shows a timeline, but only on the deal detail route.
- UI / Behavior Evidence:
  - Stage is visible on deal detail, but it is not the primary visual identity of pipeline items.
  - Pipeline rows/cards do not visually differentiate stages the way the spec requires.
- Gap Description:
  - Stage exists, but it is not consistently dominant, semantic, or workflow-defining across Credit views.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Replace the generic pipeline table in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte` with a stage-driven Kanban/list hybrid.
  - Add a Credit-specific stage presentation layer in `packages/ui/src/lib/components/StatusBadge.svelte` or a dedicated `CreditStageBadge` component.

## 4
- Domain: Credit
- Principle: `"Never use raw enum values. Translate to professional credit language:"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/components/StatusBadge.svelte:50-55` simply title-cases raw status strings.
  - `frontends/credit/src/lib/types/api.ts:44-46` exposes raw stages like `INTAKE`, `QUALIFIED`, and `CONVERTED_TO_ASSET`.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:115-123` hardcodes transition labels that do not match the Credit spec language.
- UI / Behavior Evidence:
  - Raw workflow enums would render as labels like `Qualified`, `Ic Review`, or `Converted To Asset`, not the required professional language.
- Gap Description:
  - Credit stage language is not normalized anywhere in the shared UI layer.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a canonical Credit stage label map in `packages/ui/src/lib/components/StatusBadge.svelte` or a new `frontends/credit/src/lib/components/CreditStageBadge.svelte`.
  - Refactor `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` and `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte` to consume the mapped labels only.

## 5
- Domain: Credit
- Principle: `"IC decisions are irrevocable — the UI must reflect that"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:143-165` renders approve/reject/convert as ordinary header buttons.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:301-347` uses a generic dialog for decisions.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:350-381` uses a name-confirm dialog for conversion, but still omits rationale and actor context.
- UI / Behavior Evidence:
  - Approve/Reject/Convert read like ordinary workflow steps rather than legally consequential decisions.
- Gap Description:
  - The UI does not differentiate consequential IC actions strongly enough from routine mutations.
- Severity: CRITICAL
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Replace the current decision dialogs in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` with a Credit-specific IC action flow built on `@netz/ui` `ConfirmDialog`.
  - Require explicit consequence copy, actor identity, capacity, and rationale capture before submission.

## 6
- Domain: Credit
- Principle: `"- Mandatory comments/rationale field (cannot be left empty)"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:45-58` submits approve/conditional decisions without any rationale field.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:317-324` makes rejection notes optional.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:98-103` resolves IC conditions with `notes: null`.
- UI / Behavior Evidence:
  - IC actions can be completed without a written legal record.
- Gap Description:
  - Mandatory rationale is not enforced for any IC outcome.
- Severity: CRITICAL
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add a required rationale textarea with minimum length validation in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`.
  - Pass the rationale through `/decision`, `/convert`, and `/ic-memo/conditions` payloads.

## 7
- Domain: Credit
- Principle: `"- Display of who is acting and in what capacity"`
- Status: NON-COMPLIANT
- Code Evidence:
  - No acting-user or role/capacity fields are rendered in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:301-381`.
- UI / Behavior Evidence:
  - A committee member cannot verify who is submitting a decision in the moment of action.
- Gap Description:
  - The UI omits actor identity and committee capacity entirely.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Thread current-user identity/role into `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`.
  - Render actor name and capacity inside the decision/convert dialogs before confirm.

## 8
- Domain: Credit
- Principle: `"- Visible audit trail entry immediately after the action"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:58-59` only closes the dialog and invalidates data after a decision.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:24-39` similarly posts a review decision and reloads without rendering a trail.
- UI / Behavior Evidence:
  - The user gets no immediate on-screen audit entry after a decision.
- Gap Description:
  - Audit logging may exist server-side, but the UI does not surface it at the decision point.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add an audit-trail panel to `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` and `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`.
  - Append the newly created audit event optimistically after successful mutations.

## 9
- Domain: Credit
- Principle: `"Document lineage is not optional — it is compliance"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte:159-162` shows ingestion progress.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte:58-93` shows document metadata and version history.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:187-220` shows assignments and checklist state.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/auditor/+page.svelte:55-76` shows evidence items.
- UI / Behavior Evidence:
  - The chain exists in fragments across multiple pages, but not as a single traceable lifecycle.
- Gap Description:
  - There is no unified upload -> ingestion -> classification -> review -> decision lineage view for a document.
- Severity: HIGH
- Root Cause: architectural inconsistency
- Recommended Fix:
  - Add a document lineage timeline to `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte`.
  - Extend `frontends/credit/src/lib/types/api.ts` with classification/review/decision lifecycle fields and surface them in auditor and document detail views.

## 10
- Domain: Credit
- Principle: `"Credit numbers always carry their basis"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/types/api.ts:52-68` does not include tenor, yield basis, LTV basis, covenant frequency, collateral description, or appraisal date for deal detail.
  - `frontends/credit/src/lib/types/api.ts:168-189` does not include yield, LTV, maturity profile, or WAL for portfolio assets/obligations.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:193-230` shows only sponsor, type, description, and created date.
- UI / Behavior Evidence:
  - The deal command center does not show the basis of core credit terms.
  - Portfolio rows do not expose yield basis, LTV basis, or maturity structure.
- Gap Description:
  - The frontend data contract is too shallow to support the documented Credit analysis UX.
- Severity: CRITICAL
- Root Cause: other (the Credit frontend domain model is materially under-specified for the required workflow)
- Recommended Fix:
  - Expand `frontends/credit/src/lib/types/api.ts` deal and portfolio models with tenor, coupon basis, collateral basis, appraisal date, covenant frequency, guarantees, geography, and WAL.
  - Rebuild `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` and `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte` around those fields.

## 11
- Domain: Credit
- Principle: `"The IC Memo is a first-class document, not a modal"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:283-289` mounts the memo in a tab, not a modal.
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:77-133` renders only a chapter list with no print/export header or document controls.
- UI / Behavior Evidence:
  - The memo is not a modal, but it also is not a dedicated full-width printable document experience.
- Gap Description:
  - The implementation clears the lowest bar only. It does not behave like a first-class formal memo.
- Severity: MEDIUM
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Rework `frontends/credit/src/lib/components/ICMemoViewer.svelte` into a document-grade viewer with header metadata, print/download actions, and memo-level review controls.

## 12
- Domain: Credit
- Principle: `"Narrative level determines density — not data availability"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:185-286` adds macro and FRED exploration to the L1 dashboard.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:77-125` presents the pipeline as a generic table plus side panel, not a Credit workbench.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte:147-245` uses tabbed CRUD screens rather than a decision-pack layout.
- UI / Behavior Evidence:
  - Overview, workbench, and decision-pack screens are not differentiated by density or narrative mode.
- Gap Description:
  - The same generic app-shell patterns are reused across very different Credit tasks.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Define Credit-specific L1/L2/L3 layout primitives in `frontends/credit/src/lib/components` and use them in dashboard, deal detail, and reporting routes.

## 13
- Domain: Credit
- Principle: `"Color system (strict semantic meaning — never decorative)"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/app.css:8-17` defines only generic brand tokens.
  - `packages/ui/src/lib/components/StatusBadge.svelte:14-46` uses a generic color map that does not match the Credit stage/review/obligation token system.
- UI / Behavior Evidence:
  - Stage/review colors are not tied to the documented Credit semantics.
- Gap Description:
  - The Credit semantic color system has not been implemented in the theme or badge layer.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add Credit semantic CSS custom properties to `frontends/credit/src/app.css`.
  - Update `packages/ui/src/lib/components/StatusBadge.svelte` or replace it with a Credit-specific semantic badge component.

## 14
- Domain: Credit
- Principle: `"- Deal amounts: font-variant-numeric: tabular-nums always"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `rg` found no `tabular-nums` usage in Credit deal/portfolio views.
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:114-179` renders numeric cards without any tabular numeric styling.
- UI / Behavior Evidence:
  - Numeric alignment for deal amounts is not enforced anywhere in the Credit UI.
- Gap Description:
  - Even where numbers appear, they are not presented with the required financial typography.
- Severity: LOW
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a shared `financial-number` utility class in `packages/ui/src/lib/styles` and apply it in Credit KPI, deal, and portfolio amount fields.

## 15
- Domain: Credit
- Principle: `"- Stage labels: always full text, never abbreviations in primary UI"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/components/StatusBadge.svelte:50-55` title-cases raw tokens instead of mapping to approved full labels.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:160` falls back to raw transition values when no label exists.
- UI / Behavior Evidence:
  - Users would see stage tokens like `Qualified`, `Ic Review`, or `Converted To Asset` rather than the approved full-language labels.
- Gap Description:
  - Primary-stage language is neither normalized nor domain-correct.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a required stage label transformer for Credit in `packages/ui` and block raw status rendering in Credit routes.

## 16
- Domain: Credit
- Principle: `"- Dates: always DD MMM YYYY (e.g., "14 Feb 2026") — never ambiguous formats"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/DealStageTimeline.svelte:25` uses `toLocaleDateString()`.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte:85` uses `toLocaleDateString()`.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte:233` and `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte:198,222` render raw date strings.
- UI / Behavior Evidence:
  - Date formatting varies by browser locale or raw API format instead of a fixed Credit format.
- Gap Description:
  - The spec's non-ambiguous date standard is not enforced.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Replace ad hoc date rendering with `formatDate()` usage in all Credit routes/components.
  - Update `packages/ui/src/lib/utils/format.ts` to expose a Credit-specific `DD MMM YYYY` formatter and use it consistently.

## 17
- Domain: Credit
- Principle: `"- AI-generated content: always marked with purple \`AI\` badge — never presented as human-authored without explicit label"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:88-133` renders memo content without any `AI` badge.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:153-156` exposes only an `AI Analysis` button; no labeled AI result panel exists.
- UI / Behavior Evidence:
  - Memo content and AI review outputs are not visibly separated from human-authored content.
- Gap Description:
  - The required AI provenance marker is missing from the primary AI surfaces.
- Severity: HIGH
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a reusable purple `AI` badge component in `@netz/ui`.
  - Apply it in `frontends/credit/src/lib/components/ICMemoViewer.svelte` and the document review page when AI output exists.

## 18
- Domain: Credit
- Principle: `"- Rationale/comments fields: monospace font — these are formal records"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:318-323` uses a default textarea class without `font-mono`.
  - `frontends/credit/src/app.css:15-16` defines a mono font token, but the rationale fields do not use it.
- UI / Behavior Evidence:
  - Formal-record inputs do not visually distinguish themselves as audit text.
- Gap Description:
  - The typography rule exists in tokens only, not in the actual forms.
- Severity: LOW
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a shared audit-textarea variant in `@netz/ui` and switch decision/rationale fields to it.

## 19
- Domain: Credit
- Principle: `"- Click on any deal card → opens deal detail (never navigate to new page from list)"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:72-74,90-124` opens a context panel on row click.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:119-121` requires a second click on `Open Deal` to reach the detail route.
- UI / Behavior Evidence:
  - Row click does not open the actual command-center deal detail; it opens an intermediate panel.
- Gap Description:
  - The workflow adds an unnecessary intermediary instead of taking the user straight into deal work.
- Severity: MEDIUM
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Change the primary row/card interaction in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte` to open the deal detail directly.
  - Keep the context panel as an explicit secondary preview, not the primary click target.

## 20
- Domain: Credit
- Principle: `"- Click on any document → opens document viewer inline (slide panel)"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte:171-175` navigates to `/documents/[documentId]` on row click.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:139-220` has no inline document viewer at all.
- UI / Behavior Evidence:
  - Document interaction is route-based and full-page, not inline and review-centric.
- Gap Description:
  - The document review workflow breaks context instead of showing the document alongside the review controls.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add an inline slide-panel document viewer to `frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte`.
  - Refactor `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte` into the required two-column viewer + checklist layout.

## 21
- Domain: Credit
- Principle: `"- Click on any IC vote → opens vote detail with voter, timestamp, rationale"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:191-296` has no IC vote table or vote detail interaction.
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:89-100` only shows aggregate voting status.
- UI / Behavior Evidence:
  - Vote-level drilldown does not exist.
- Gap Description:
  - Committee voting lacks traceable voter-level evidence in the UI.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Extend `frontends/credit/src/lib/types/api.ts` voting detail types with timestamp/rationale fields.
  - Add a vote detail panel/table in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`.

## 22
- Domain: Credit
- Principle: `"- All destructive actions: ConfirmDialog, mandatory rationale, immediate audit entry"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:157-165` calls approve/reject/revision directly.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:258-274` resolves/waives IC conditions directly.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte:238-255,298-305` fulfills/closes obligations/actions without rationale capture.
- UI / Behavior Evidence:
  - Destructive or consequential actions lack the required compliance wrapper across multiple routes.
- Gap Description:
  - The required pattern is not enforced centrally, so each page drifts.
- Severity: CRITICAL
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Introduce a shared Credit mutation wrapper on top of `ConfirmDialog` in `@netz/ui` that requires rationale and emits an audit event.
  - Apply it in deal, review, and portfolio mutation paths.

## 23
- Domain: Credit
- Principle: `"- Tables: click column to sort, shift-click for secondary sort"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/components/DataTable.svelte:94-140` supports clickable column sorting.
  - `packages/ui/src/lib/components/DataTable.svelte:37-61` maintains a sorting state but exposes no shift-click multi-sort UX.
- UI / Behavior Evidence:
  - Single-column sort exists; secondary sort interaction is absent.
- Gap Description:
  - The table abstraction only satisfies half of the rule.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Enable explicit multi-sort behavior in `packages/ui/src/lib/components/DataTable.svelte` and document shift-click affordance in header controls.

## 24
- Domain: Credit
- Principle: `"- Stage filter always visible at top of pipeline — never buried in a sidebar"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:77-95` renders only a title, `New Deal`, and a table.
- UI / Behavior Evidence:
  - There is no stage filter bar, no view toggle, and no Kanban/list control at the top of the pipeline.
- Gap Description:
  - A core navigation/filtering control for Credit work is missing entirely.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add a persistent stage filter bar to `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`.
  - Include stage counts, sort, and Kanban/list toggles per the Credit spec.

## 25
- Domain: Credit
- Principle: `"Never show a deal amount without currency and tenor."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte:64-70` does not show amount or tenor columns.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:193-230` omits amount and tenor from the overview entirely.
  - `frontends/credit/src/lib/types/api.ts:62` includes `amount` only, without tenor/basis fields.
- UI / Behavior Evidence:
  - The UI cannot present the required amount + tenor pair because the view and model do not carry it.
- Gap Description:
  - Critical credit context is missing from the main pipeline and deal detail views.
- Severity: HIGH
- Root Cause: other (the deal model and page composition omit required credit-term fields)
- Recommended Fix:
  - Add tenor and instrument basis fields to `frontends/credit/src/lib/types/api.ts`.
  - Render amount + tenor in pipeline cards/list and the deal header/overview.

## 26
- Domain: Credit
- Principle: `"Never use generic empty states in the Task Inbox."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/TaskInbox.svelte:22-25` renders `No pending tasks.`
- UI / Behavior Evidence:
  - The empty inbox state is generic and gives no compliance or operational reassurance.
- Gap Description:
  - The empty state fails the required “all clear” operational summary pattern.
- Severity: LOW
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Replace the empty state text in `frontends/credit/src/lib/components/TaskInbox.svelte` with a timestamped operational summary.

## 27
- Domain: Credit
- Principle: `"Never show a covenant without its test frequency."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/types/api.ts:52-68` has no covenant-frequency fields for deal detail.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:193-230` does not render covenants at all.
- UI / Behavior Evidence:
  - Covenants are absent, so the interface cannot prove frequency-aware covenant monitoring.
- Gap Description:
  - A central compliance concept is missing from both the data contract and the UI.
- Severity: HIGH
- Root Cause: other (frontend data contract does not model covenant presentation requirements)
- Recommended Fix:
  - Add covenant and test-frequency fields to the deal detail model and render them in the Overview and Portfolio views.

## 28
- Domain: Credit
- Principle: `"Never auto-trigger IC Memo generation."`
- Status: COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:45-74` generates the memo only inside `generateMemo()`.
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:77-85` exposes an explicit `Generate IC Memo` button.
- UI / Behavior Evidence:
  - Memo generation is user-initiated; it is not triggered on load.
- Gap Description:
  - No gap on trigger semantics. Other memo requirements remain unmet.
- Severity: LOW
- Root Cause: other (this requirement is implemented correctly)
- Recommended Fix:
  - Keep the explicit trigger flow in `frontends/credit/src/lib/components/ICMemoViewer.svelte` while upgrading the rest of the memo experience.

## 29
- Domain: Credit
- Principle: `"Never show document review checklist as read-only by default."`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:208-217` renders interactive checkboxes immediately.
  - The same code does not gate interactivity by reviewer role or `UNDER_REVIEW` state.
- UI / Behavior Evidence:
  - The checklist is interactive, but indiscriminately so.
- Gap Description:
  - The implementation satisfies “not read-only by default” but misses the required reviewer/status guardrails.
- Severity: MEDIUM
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Gate checklist interactivity in `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte` by reviewer role and review status.

## 30
- Domain: Credit
- Principle: `"Unchecking requires confirmation + reason."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:117-129` posts checklist changes directly.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:208-217` binds checkbox change directly to `toggleChecklistItem`.
- UI / Behavior Evidence:
  - A reviewer can remove checklist evidence with no confirm step and no written explanation.
- Gap Description:
  - Checklist reversals are not audit-safe.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add a `ConfirmDialog` with required reason capture before uncheck in `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`.

## 31
- Domain: Credit
- Principle: `"Never paginate the obligation schedule."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte:223-260` shows a flat obligations list, not an expanded full schedule per asset.
  - `packages/ui/src/lib/components/DataTable.svelte:180-241` paginates tables by default when row counts grow.
- UI / Behavior Evidence:
  - The required one-scroll cash flow schedule does not exist.
- Gap Description:
  - Future obligations are not presented as a continuous schedule tied to each asset.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Replace the current obligations tab in `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte` with expandable per-asset schedules rendered in one scroll.

## 32
- Domain: Credit
- Principle: `"- All IC decisions: logged with timestamp, user identity, rationale — immutable"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:45-58` sends no rationale for approve/conditional decisions.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:301-381` renders no timestamp, actor, or immutable log UI.
- UI / Behavior Evidence:
  - The decision UI does not capture or display the full compliance record required by the spec.
- Gap Description:
  - The frontend does not enforce or surface immutable IC decision logging.
- Severity: CRITICAL
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Extend decision payloads and deal detail rendering in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` to include rationale, actor identity, timestamp, and immutable audit entries.

## 33
- Domain: Credit
- Principle: `"- All AI-generated content: labeled, with generation timestamp and model version"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:77-133` renders no generation timestamp or model version.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:98-112` triggers AI analysis but has no UI for model/version/timestamp metadata.
- UI / Behavior Evidence:
  - AI outputs lack provenance metadata.
- Gap Description:
  - The provenance of AI-generated content is not visible to users or auditors.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add model, generated-at, and reviewer metadata fields to the memo and AI-analysis payloads in `frontends/credit/src/lib/types/api.ts`.
  - Render them in `ICMemoViewer.svelte` and the document review decision panel.

## 34
- Domain: Credit
- Principle: `"- Document review decisions: full audit trail with reviewer, date, rationale"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:24-32` submits decisions with `comments: null`.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:187-220` shows assignments/checklist only; no decision trail.
- UI / Behavior Evidence:
  - Review decisions cannot be inspected as an auditable sequence with reviewer/date/rationale.
- Gap Description:
  - Decision auditability is missing from the page where the decision occurs.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add required rationale capture and a visible review decision history to `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`.

## 35
- Domain: Credit
- Principle: `"- Stage labels, status labels: paraglide-js i18n keys — never hardcoded"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/components/StatusBadge.svelte:50-55` generates labels algorithmically rather than via i18n keys.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:115-123` hardcodes transition labels inline.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/+page.svelte:24-31` hardcodes review summary labels inline.
- UI / Behavior Evidence:
  - Credit status language is embedded directly in components instead of a translation layer.
- Gap Description:
  - Localization and domain-language governance are not in place.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Move Credit stage/status labels into paraglide-js keys and replace inline strings in Credit routes and `StatusBadge.svelte`.

## 36
- Domain: Credit
- Principle: `"- All amounts: \`Intl.NumberFormat\` with explicit currency code"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/utils/format.ts:7-18` provides `formatCurrency()` with explicit currency support.
  - `frontends/credit/src/routes/(team)/dashboard/+page.svelte:161-179` and `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte:208-233` render raw string values instead of the formatter.
- UI / Behavior Evidence:
  - The utility exists, but Credit views do not consistently use it.
- Gap Description:
  - Currency formatting is available but not enforced at the page layer.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Refactor Credit KPI, pipeline, deal, portfolio, and reporting amounts to call `formatCurrency()` from `packages/ui/src/lib/utils/format.ts`.

## 37
- Domain: Credit
- Principle: `"- All dates: \`Intl.DateTimeFormat\` — always show full date, never relative-only (relative "3 days ago" always accompanied by absolute date on hover)"`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `packages/ui/src/lib/utils/format.ts:44-59` provides a shared `formatDate()` utility.
  - Credit components/routes still use `toLocaleDateString()` or raw API strings instead of the utility, for example `frontends/credit/src/lib/components/DealStageTimeline.svelte:25` and `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte:85`.
- UI / Behavior Evidence:
  - The implementation is inconsistent and does not guarantee a full absolute date across views.
- Gap Description:
  - A valid shared formatter exists but is not the enforced default.
- Severity: MEDIUM
- Root Cause: missing enforcement of shared patterns
- Recommended Fix:
  - Add a lintable Credit formatting helper and replace all ad hoc date rendering in Credit routes/components with it.

## 38
- Domain: Credit
- Principle: `"- Covenant descriptions: always in the language of the credit agreement"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/types/api.ts:52-68` does not model covenant text or agreement-language descriptions.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:193-230` renders no covenant section at all.
- UI / Behavior Evidence:
  - Covenant language preservation is impossible because the UI has no covenant rendering model.
- Gap Description:
  - The agreement-language requirement is not implemented structurally.
- Severity: HIGH
- Root Cause: other (the current frontend contract omits covenant-description content entirely)
- Recommended Fix:
  - Add agreement-language covenant fields to the deal detail model and render them verbatim in the Overview and Portfolio covenant views.

## 39
- Domain: Credit
- Principle: `"Rationale: [required — minimum 50 characters]"`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:24-32` submits document review decisions with `comments: null`.
  - No min-length validation exists anywhere in the review page.
- UI / Behavior Evidence:
  - Reviewers can approve/reject/request revision without any written rationale, let alone a 50-character minimum.
- Gap Description:
  - The document review decision panel is missing its core compliance control.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add a required rationale textarea with 50-character validation and decision gating in `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`.

## 40
- Domain: Credit
- Principle: `"Always labeled \`[AI]\`. Never auto-shown — only after explicit "Run AI Analysis" trigger."`
- Status: PARTIALLY COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte:101-106,153-156` triggers AI analysis only from an explicit button.
  - The page contains no AI analysis result panel or `[AI]` label.
- UI / Behavior Evidence:
  - The explicit trigger rule is met, but the labeled AI-analysis presentation is missing.
- Gap Description:
  - The trigger semantics are correct; the UI output contract is absent.
- Severity: MEDIUM
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add a dedicated `[AI]` analysis panel to `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte` with confidence, extracted metrics, flags, completeness score, timestamp, and model metadata.

## 41
- Domain: Credit
- Principle: `"Generate: ActionButton → long-running → SSE progress bar."`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte:30-41` and `93-111` use simple request/await/invalidate flows for report pack generation.
  - No SSE progress component is wired into reporting.
- UI / Behavior Evidence:
  - Report generation is a blocking button state, not a long-running auditable progress flow.
- Gap Description:
  - A documented long-running reporting workflow is reduced to a generic mutation.
- Severity: MEDIUM
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Reuse the streaming/progress pattern from `frontends/credit/src/lib/components/IngestionProgress.svelte` for reporting jobs in `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`.

## 42
- Domain: Credit
- Principle: `"Reviewed by" field mandatory before the memo can be used in IC voting`
- Status: NON-COMPLIANT
- Code Evidence:
  - `frontends/credit/src/lib/components/ICMemoViewer.svelte:77-133` renders no review metadata, reviewer field, or voting gate tied to memo review state.
  - `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte:143-165` shows stage actions independently of memo review metadata.
- UI / Behavior Evidence:
  - The user can access IC actions without any visible memo review confirmation.
- Gap Description:
  - The memo review gate required before voting is absent from both the memo view and the action surface.
- Severity: HIGH
- Root Cause: placeholder / incomplete implementation
- Recommended Fix:
  - Add reviewer name/date fields to the memo model in `frontends/credit/src/lib/types/api.ts`.
  - Render that metadata in `frontends/credit/src/lib/components/ICMemoViewer.svelte` and disable IC voting actions in `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte` until it is set.
