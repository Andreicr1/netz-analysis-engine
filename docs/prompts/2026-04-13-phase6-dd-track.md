# Phase 6 — DD Track: Terminal-Native Due Diligence Workflow

**Date:** 2026-04-13
**Branch:** `feat/terminal-dd-track`
**Sessions:** 2 (Session A: Kanban + TopNav, Session B: Viewer + Approval)
**Depends on:** main (Phases 1-5 merged, all 17 harmonization PRs merged)

---

## Strategic Rationale

The terminal has Screener, Builder, and Live operational. But private funds (`private_us`, `bdc`) cannot reach the Approved Universe without a DD report. The path is broken: Screener queues DD via `[+ DD]`, but there is no terminal surface to monitor queue progress, read completed reports, or approve/reject them. Phase 6 closes this gap.

The backend is 100% ready. Every endpoint exists and is tested. This is pure frontend work.

---

## Session A — DD Kanban + TopNav Activation

### CONTEXT

The terminal navigation (`TerminalTopNav.svelte`) already has a DD tab at position 8 (last) with `status: "pending"`. The backend exposes `GET /dd-reports/queue` which returns three buckets (`pending`, `in_progress`, `completed_recent`) with counts. The `createTerminalStream` runtime primitive in `frontends/wealth/src/lib/components/terminal/runtime/stream.ts` handles SSE with fetch+ReadableStream. Terminal Layer 2/3 primitives exist in `frontends/wealth/src/lib/components/terminal/layout/` and `terminal/data/`.

### OBJECTIVE

1. Create the `(terminal)/dd/+page.svelte` route with a 3-column kanban layout.
2. Activate the DD tab in TopNav (change from "pending" to "active").
3. Add a DD queue badge count on the TopNav DD tab when `counts.pending + counts.in_progress > 0`.
4. Clicking a kanban card navigates to `(terminal)/dd/[reportId]` (Session B builds that page; for now, just wire the navigation).

### CONSTRAINTS

- All colors via `--terminal-*` CSS custom properties. No hex values anywhere.
- Font: `var(--terminal-font-mono)` only. No Urbanist, no sans-serif.
- Border radius: `var(--terminal-radius-none)` (0). No rounding.
- Use Layer 2/3 primitives: `Panel`, `PanelHeader`, `StatSlab`, `KeyValueStrip`, `LiveDot`.
- SSE via `createTerminalStream` from `$lib/components/terminal/runtime/stream.ts` — never `EventSource`.
- Formatters from `@netz/ui` (`formatDateTime`, `formatPercent`) exclusively. No `.toFixed()`, `.toLocaleString()`.
- No `localStorage`. State is in-memory via `$state` runes.
- Svelte 5 runes: `$state`, `$derived`, `$effect`. No legacy stores.
- Every `$effect` that starts a timer/fetch must return cleanup.
- Smart backend / dumb frontend: show "Confidence: 87%" not "confidence_score: 0.87". Show "Pending Review" not "pending_approval".
- `LayoutCage` pattern: `calc(100vh - 88px)` + `padding: 24px` for content area.

### DELIVERABLES

#### 1. `frontends/wealth/src/routes/(terminal)/dd/+page.svelte`

Main DD Track page. Three-column kanban layout.

```
+------------------+------------------+------------------+
|  QUEUE (pending) | IN PROGRESS      | COMPLETED        |
|  count badge     | count badge      | count badge      |
+------------------+------------------+------------------+
|  Card            | Card (pulsing)   | Card (approved)  |
|  Card            | Card             | Card (rejected)  |
|                  |                  | Card (failed)    |
+------------------+------------------+------------------+
```

Logic:
- On mount, fetch `GET /api/wealth/dd-reports/queue` with auth token from `getContext("netz:getToken")`.
- Use `createClientApiClient` from `$lib/api/client` to make authenticated requests.
- Poll every 30 seconds via `$effect` with `setInterval` + cleanup.
- Map queue buckets to columns:
  - Column 1 "QUEUE": `pending` bucket (status = "draft")
  - Column 2 "IN PROGRESS": `in_progress` bucket (status = "generating" or "pending_approval")
  - Column 3 "COMPLETED": `completed_recent` bucket (status = "approved", "rejected", "failed")
- Each column uses `Panel` + `PanelHeader` with count badge.
- Cards show: instrument label, status badge, version number, created date (`formatDateTime`), confidence score if present (`formatPercent`).
- Status badge colors: draft = `--terminal-fg-secondary`, generating = `--terminal-accent-amber` (pulsing), pending_approval = `--terminal-accent-cyan`, approved = `--terminal-status-ok`, rejected = `--terminal-status-error`, failed = `--terminal-status-error`.
- Click card → `goto(resolve(\`/dd/\${card.id}\`))`.
- "In Progress" cards with `status === "generating"` show a `LiveDot` component pulsing.

#### 2. `frontends/wealth/src/lib/components/terminal/dd/DDQueueCard.svelte`

Reusable card component for a single DD report in the kanban.

Props (Svelte 5):
```typescript
interface DDQueueCardProps {
    id: string;
    instrumentId: string;
    instrumentLabel: string | null;
    status: string;
    version: number;
    confidenceScore: number | null;
    decisionAnchor: string | null;
    createdAt: string;
    approvedAt: string | null;
    onClick: () => void;
}
```

Rendering rules:
- Card is a `<button>` (keyboard accessible, `onclick` handler).
- Background: `var(--terminal-bg-surface)`.
- Border: `var(--terminal-border-hairline)`.
- On hover: border becomes `var(--terminal-accent-amber)`.
- Top line: instrument label (truncated, mono, `--terminal-fg-primary`).
- Second line: `v{version}` + status badge + `LiveDot` if generating.
- Third line: created date via `formatDateTime`.
- Bottom line (conditional): if `confidenceScore !== null`, show "CONF: {formatPercent(confidenceScore / 100)}" and if `decisionAnchor`, show anchor label.
- Decision anchor labels (smart backend, dumb frontend):
  - "APPROVE" → "Recommend Approve" in `--terminal-status-ok`
  - "REJECT" → "Recommend Reject" in `--terminal-status-error`
  - "CONDITIONAL" → "Conditional" in `--terminal-accent-amber`
- Status label mapping:
  - "draft" → "Queued"
  - "generating" → "Generating..."
  - "pending_approval" → "Pending Review"
  - "approved" → "Approved"
  - "rejected" → "Rejected"
  - "failed" → "Failed"

#### 3. Modify `frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`

Changes:
1. Add `ddQueueCount` prop (number, default 0).
2. Move DD tab from position 8 to position 4 (between SCREENER and BUILDER) to match workflow order: `MACRO | ALLOC | SCREENER | DD | BUILDER | LIVE | RESEARCH | ALERTS`.
3. Change DD tab status from `"pending"` to `"active"`.
4. Add resolved href: `const HREF_DD = resolve("/dd");`
5. Wire DD tab as an active `<a>` element (same pattern as other active tabs).
6. Add `isHrefActive` and `activePathSegment` entries for DD.
7. When `ddQueueCount > 0`, render a count badge next to the DD label (same style as the alerts badge but using `--terminal-accent-cyan` background).

#### 4. Modify `frontends/wealth/src/lib/components/terminal/shell/TerminalShell.svelte`

Pass `ddQueueCount` prop down to `TerminalTopNav`. The shell should poll `GET /api/wealth/dd-reports/queue` every 60 seconds to get the count, or receive it from a parent context. Simplest approach: add a `$state` variable in the shell, fetch on mount + 60s interval, pass `counts.pending + counts.in_progress` to TopNav.

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes (no type errors, no lint errors).
2. DD tab is active in TopNav, clickable, navigates to `(terminal)/dd`.
3. DD tab shows between SCREENER and BUILDER.
4. Badge appears on DD tab when queue has pending/in-progress items.
5. Kanban renders three columns with cards from the queue endpoint.
6. Cards are keyboard-accessible (Enter/Space triggers navigation).
7. No hex colors in any new `.svelte` file.
8. No `.toFixed()` or `.toLocaleString()` in any new file.
9. `LiveDot` pulses on generating cards.

### ANTI-PATTERNS

- Do NOT import `@investintell/ui/components/ui/button` or any shadcn component. Use terminal-native HTML buttons with `--terminal-*` tokens.
- Do NOT use `DDReportBody.svelte` from `$lib/components/library/readers/`. That component uses shadcn/old design system. It is a logic reference only.
- Do NOT use `EventSource`. SSE must use `createTerminalStream` or plain `fetch`.
- Do NOT add `localStorage` or `sessionStorage`.
- Do NOT create stores (`.svelte.ts` files with module-level `$state`). Keep state local to the page component.
- Do NOT show raw status enum values. Map them to human-readable labels.
- Do NOT use `flex`/`grid min-h-0` for full-height layouts. Use `LayoutCage` with `calc(100vh - 88px)`.

---

## Session B — DD Report Viewer + Approval Workflow

### CONTEXT

Session A created the DD kanban at `(terminal)/dd`. Cards navigate to `(terminal)/dd/[reportId]`. The backend exposes:
- `GET /dd-reports/{report_id}` — full report with chapters (response: `DDReportRead` with `chapters: DDChapterRead[]`)
- `GET /dd-reports/{report_id}/stream` — SSE for real-time chapter generation progress
- `POST /dd-reports/{report_id}/approve` — body: `{ rationale: string }` (min 10 chars)
- `POST /dd-reports/{report_id}/reject` — body: `{ reason: string }` (min 10 chars)
- `GET /dd-reports/{report_id}/audit-trail` — approval history

DDReportBody.svelte in `$lib/components/library/readers/` has the business logic for SSE progress, audit trail, and approval — use it as **logic reference only**, rebuild all UI with terminal primitives.

Chapter schema (`DDChapterRead`):
```typescript
{
    id: string;
    chapter_tag: string;    // e.g. "executive_summary", "risk_assessment"
    chapter_order: number;
    content_md: string | null;
    evidence_refs: Record<string, any> | null;
    quant_data: Record<string, any> | null;  // already sanitized by backend
    critic_iterations: number;
    critic_status: string;  // "passed", "failed", "skipped"
    generated_at: string | null;
}
```

Chapter tags and display names (reference `$lib/types/dd-report.ts` for `chapterTitle()` function):
- "executive_summary" → "Executive Summary"
- "investment_thesis" → "Investment Thesis"
- "risk_assessment" → "Risk Assessment"
- "quant_analysis" → "Quantitative Analysis"
- "peer_comparison" → "Peer Comparison"
- "fee_analysis" → "Fee Analysis"
- "governance" → "Governance & Structure"
- "recommendation" → "Recommendation"

### OBJECTIVE

1. Create `(terminal)/dd/[reportId]/+page.svelte` — full-page DD report viewer.
2. Build chapter accordion with evidence pack, confidence score, critic status.
3. Wire SSE stream for real-time chapter generation progress.
4. Build terminal-native approve/reject workflow with confirmation dialogs.
5. Show audit trail panel.

### CONSTRAINTS

Same as Session A, plus:
- Markdown rendering: use the existing `renderMarkdown` utility from `$lib/utils/render-markdown.ts`.
- Approval requires `INVESTMENT_TEAM` role — the backend enforces this, but the UI should also hide approve/reject buttons if the user lacks the role (check `$page.data.actor?.role`).
- Self-approval is blocked by backend (403) — handle gracefully in UI.
- The `quant_data` dict keys are already sanitized by the backend schema validator. Render them as-is in a `KeyValueStrip`.
- `evidence_refs` may contain URLs or document references. Render as a list of links/references.

### DELIVERABLES

#### 1. `frontends/wealth/src/routes/(terminal)/dd/[reportId]/+page.svelte`

Two-column layout inside `LayoutCage`:

```
+----------------------------------+-------------------+
|  REPORT HEADER                   |  ACTIONS PANEL    |
|  Fund name, version, status      |  [APPROVE]        |
|  Confidence bar, decision anchor |  [REJECT]         |
|                                  |  Audit Trail      |
+----------------------------------+-------------------+
|  CHAPTER LIST (scrollable)       |                   |
|  > Executive Summary             |                   |
|    [content, evidence, quant]    |                   |
|  > Investment Thesis             |                   |
|  > Risk Assessment               |                   |
|  ...                             |                   |
+----------------------------------+-------------------+
```

Left column (75% width): report content.
Right column (25% width, min 280px): actions + audit trail.

**Report header** (top of left column):
- Fund name (from report data or instrument label).
- `v{version}` badge + status badge (same labels/colors as Session A).
- If `confidence_score` present: horizontal bar from 0-100%, colored by threshold (< 50 red, 50-75 amber, > 75 green using `--terminal-status-*` tokens).
- If `decision_anchor` present: anchor label (same mapping as Session A cards).
- Back link: `[< BACK TO QUEUE]` navigating to `(terminal)/dd`.

**Chapter list** (below header, scrollable):
- Each chapter is a collapsible section (click to expand/collapse).
- Chapter header: `{chapter_order}. {chapterTitle(chapter_tag)}` + critic status badge + `LiveDot` if generating.
- Critic status badges: "passed" = `--terminal-status-ok` with "CRITIC: PASS", "failed" = `--terminal-status-error` with "CRITIC: FAIL", "skipped" = `--terminal-fg-muted` with "CRITIC: SKIP".
- Expanded chapter shows:
  1. Rendered markdown content (`renderMarkdown(content_md)`).
  2. If `quant_data` is non-null and non-empty: `KeyValueStrip` showing all key-value pairs.
  3. If `evidence_refs` is non-null and non-empty: "Evidence" section listing references.
  4. Footer: `critic_iterations` count + `generated_at` timestamp.
- All chapters start collapsed except the first one.
- If report is `status === "generating"`, show a progress indicator: count of completed chapters vs total expected (8).

**SSE integration** (when `status === "generating"`):
- Use `createTerminalStream` to connect to `/api/wealth/dd-reports/{reportId}/stream`.
- Auth header: `Authorization: Bearer {token}` from `getContext("netz:getToken")`.
- Handle events:
  - `chapter_started`: mark chapter as generating (show `LiveDot`).
  - `chapter_completed`: update chapter content, remove `LiveDot`, show critic result.
  - `report_completed`: refresh full report data, stop stream.
  - `report_failed`: show error state, stop stream.
- Cleanup stream in `$effect` return or `onDestroy`.

**Actions panel** (right column):
- Wrapped in `Panel` + `PanelHeader` with title "ACTIONS".
- If `status === "pending_approval"`:
  - `[APPROVE]` button: `--terminal-status-ok` border, opens confirmation dialog.
  - `[REJECT]` button: `--terminal-status-error` border, opens rejection dialog.
- If `status === "approved"`: show "Approved by {approved_by}" + `formatDateTime(approved_at)`.
- If `status === "rejected"`: show rejection reason.
- If `status === "generating"`: show "Report generation in progress..." with `LiveDot`.
- If `status === "draft"`: show "Queued for generation" + `[REGENERATE]` button.

**Approval dialog** (terminal-native, not shadcn):
- Overlay with scrim (same z-index pattern as FocusMode).
- Title: "Approve DD Report".
- Body: "Approving this report will add the fund to the Approved Universe."
- Required field: rationale textarea (min 10 chars, mono font).
- Buttons: `[CONFIRM APPROVAL]` (--terminal-status-ok) and `[CANCEL]` (--terminal-fg-secondary).
- POST to `/api/wealth/dd-reports/{reportId}/approve` with `{ rationale }`.
- On success: refresh report data, show success state.
- On 403 (self-approval): show inline error "Self-approval is not permitted".
- On error: show inline error message.

**Rejection dialog** (same pattern):
- Title: "Reject DD Report".
- Body: "This report will be returned to draft status."
- Required field: reason textarea (min 10 chars).
- POST to `/api/wealth/dd-reports/{reportId}/reject` with `{ reason }`.

**Audit trail** (below actions, right column):
- Fetch `GET /api/wealth/dd-reports/{reportId}/audit-trail` on mount.
- Render as a timeline list: each event shows action label, actor, timestamp.
- Action labels: "dd_report.approve" → "Approved", "dd_report.reject" → "Rejected", "dd_report.approve.override" → "Approved (Override)", "dd_report.reject.override" → "Rejected (Override)".

#### 2. `frontends/wealth/src/lib/components/terminal/dd/DDChapterSection.svelte`

Reusable collapsible chapter section.

Props:
```typescript
interface DDChapterSectionProps {
    chapterTag: string;
    chapterOrder: number;
    contentMd: string | null;
    evidenceRefs: Record<string, any> | null;
    quantData: Record<string, any> | null;
    criticIterations: number;
    criticStatus: string;
    generatedAt: string | null;
    isGenerating: boolean;
    defaultOpen: boolean;
}
```

#### 3. `frontends/wealth/src/lib/components/terminal/dd/DDApprovalDialog.svelte`

Terminal-native confirmation dialog for approve/reject actions.

Props:
```typescript
interface DDApprovalDialogProps {
    mode: "approve" | "reject";
    isOpen: boolean;
    isSubmitting: boolean;
    error: string | null;
    onSubmit: (text: string) => void;
    onCancel: () => void;
}
```

### VERIFICATION

1. `pnpm --filter @investintell/wealth check` passes.
2. Navigate from kanban card to `(terminal)/dd/{reportId}` — report loads with chapters.
3. Chapters are collapsible. First chapter starts expanded.
4. Quant data renders in `KeyValueStrip` format.
5. Approve/reject dialogs open, validate min 10 chars, submit correctly.
6. SSE stream connects when report is generating, updates chapters in real-time.
7. Audit trail loads and displays event history.
8. Back link returns to kanban.
9. No hex colors, no shadcn imports, no localStorage.
10. Self-approval error is handled gracefully (inline message, not crash).

### ANTI-PATTERNS

- Do NOT import from `$lib/components/library/readers/DDReportBody.svelte`. Build fresh with terminal primitives.
- Do NOT use `ConsequenceDialog` from `@investintell/ui`. Build terminal-native dialogs.
- Do NOT use `StatusBadge` from `@investintell/ui`. Build terminal-native status badges with `--terminal-*` tokens.
- Do NOT expose raw chapter tags in the UI. Always map through `chapterTitle()` or the display name mapping.
- Do NOT show `quant_data` keys that look like backend identifiers. The backend already sanitizes them, but if any slip through, display them as Title Case.
- Do NOT use `$effect` that derives state. Use `$derived` for computed values.
- Do NOT create `+page.server.ts` or `+page.ts` load functions that fetch data. Fetch client-side in `$effect` on mount (the terminal uses client-side data fetching, not SvelteKit load functions, because auth headers are needed).
