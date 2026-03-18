# Frontend UX Remediation Plan

## Enhancement Summary

**Deepened on:** 2026-03-17
**Sections enhanced:** All 6 sections + new sections 7-9 added
**Research agents used:** 13 parallel agents (8 best-practices researchers, 3 review agents, 1 spec-flow analyzer, 1 learnings researcher)

### Key Improvements
1. Concrete library choices and code patterns for every shared primitive (CodeMirror 6, AlertDialog migration, SSE-primary architecture)
2. Performance budget and optimization roadmap for each new component (lazy loading, virtual scrolling, formatter caching)
3. Security hardening requirements added (XSS via `{@html}`, server-side enforcement, tenant isolation)
4. Sprint timeline expanded from 3 to 4 sprints based on scope realism analysis
5. Backend contract milestones with `make types` gate added as hard dependency
6. Institutional compliance patterns from DORA/SEC/SOX mapped to specific components

### New Considerations Discovered
- `AuditTrailPanel` and `ConsequenceDialog` already exist in codebase — plan items 1-2 are enhancement, not greenfield
- 50+ ad-hoc `.toFixed()` calls across wealth/credit frontends need ESLint enforcement
- `CodeEditor` should be admin-local, not in `@netz/ui` (single consumer, ~90KB dependency)
- 6 local `formatDate` redeclarations shadow `@netz/ui` — formatter drift is systemic
- `{@html}` + Jinja2 `safe` filter = stored XSS vulnerability found in admin frontend
- SSE connection starvation risk: plan adds 3-4 new SSE consumers against 4-connection cap

---

## 1. Immediate Risk Blocks
1. Credit IC decision governance
   Must block approval, rejection, conversion, and document-review decisions until rationale, actor identity, actor capacity, timestamp, and visible post-submit audit output are present in the UI.
   Frontend focus: `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`, shared confirm and audit primitives in `packages/ui`.
   Dependency: Backend payloads must accept and return rationale, actor metadata, and immutable audit events.

   ### Research Insights

   **Best Practices (Audit Trail UI):**
   - Migrate `ConsequenceDialog` from `Dialog` to `AlertDialog` (bits-ui) for correct `role="alertdialog"` semantics — W3C WAI-ARIA recommends this for high-consequence confirmations
   - Focus Cancel button (not Confirm) when dialog opens for destructive actions — prevents accidental keyboard activation
   - Add explicit consequences list: bulleted "what will happen" section beyond the impact summary text (pattern from Carbon Design System and PatternFly)
   - Add `actorCapacity` field to `AuditTrailEntry` interface — SEC/DORA require "in what capacity" alongside "who"
   - Add `role="log"` and `aria-live="polite"` to `AuditTrailPanel` entry list — W3C ARIA23 technique for sequential information
   - Add `<time datetime="...">` elements around all formatted timestamps for machine readability
   - Add `role="alert"` to error message containers for screen reader announcement

   **Existing Component Status:**
   - `AuditTrailPanel.svelte` already exists at `packages/ui/src/lib/components/` — this is an enhancement task, not greenfield
   - `ConsequenceDialog.svelte` already exists with rationale, typed confirmation, metadata grid, and async submission
   - `ConfirmDialog.svelte` is already a thin wrapper over `ConsequenceDialog` — layering is correct
   - Deal page already constructs entries with `actorCapacity` and passes it through `ConsequenceDialog` metadata

   **Missing: Optimistic Mutation Pattern.**
   The plan mentions "append optimistic audit entry through AuditTrailPanel" but no shared pattern exists for optimistic mutations with rollback. When `ConsequenceDialog` confirm fires, the UI should show the audit entry immediately (with a "pending" indicator), then reconcile when the backend responds. Document this as a ninth shared utility: `createOptimisticMutation()`.

   **Performance Consideration:**
   - Add `maxVisible` initial render cap (50 entries) to `AuditTrailPanel` with "Load earlier entries" trigger — prevents DOM explosion for deals with 100+ audit events
   - Replace `formatTimestamp` internal `Intl.DateTimeFormat` allocation with shared `formatDateTime` from `format.ts`

   **Security Requirement:**
   - Rationale requirement MUST be enforced server-side, not just UI — the ConsequenceDialog is a UX convenience, not a security boundary
   - Actor identity must come from JWT claims (Clerk `o.id`, user metadata), not from client-submitted form fields
   - Audit trail entries must be server-persisted and immutable — the client renders them but cannot create or modify them directly

   **Canonical SvelteKit Patterns (from learnings):**
   - All mutations must use `$state` loading + `invalidateAll()` pattern
   - All loaders must use `Promise.allSettled` (never `Promise.all`) — silent 404s were swallowed by `r.ok ? r.json() : null` causing blank panels
   - Dismissible error banner pattern must be used for all mutation failures

2. Wealth freshness and state integrity
   Must stop all page-local freshness claims that are derived from fetch/render time and consolidate live risk updates behind one authoritative store path before further analytical UX work.
   Frontend focus: `frontends/wealth/src/lib/stores/risk-store.svelte.ts`, `frontends/wealth/src/routes/(team)/+layout.svelte`, `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`, `frontends/wealth/src/lib/components/FundDetailPanel.svelte`.
   Dependency: Backend responses and streams must provide source timestamps and consistent event payloads.

   ### Research Insights

   **SSE-Primary, Poll-Fallback Architecture:**
   - Unify SSE stream + polling into single store with one `applyUpdate()` gate — every data source passes through the same function
   - SSE is primary (low latency); polling activates only when SSE errors or heartbeat times out
   - Monotonic version counter prevents stale-poll-overwrites-fresh-SSE race condition
   - Backend must add `computed_at` (server timestamp) and `next_expected_update` (holiday-aware) to all responses
   - Client `Date.now()` must never be used for freshness — always use server `computed_at`
   - Connection quality derived via `$derived`: SSE connected = "live", SSE reconnecting + poll active = "degraded", both down = "offline"

   **Implementation Details:**
   ```typescript
   // Freshness levels derived from server timestamps
   type ConnectionQuality = "live" | "degraded" | "offline";
   type FreshnessLevel = "live" | "recent" | "stale" | "unknown";
   // SSE < 5min = live, < 1hr = recent, isStale() = stale
   ```

   **Performance Considerations:**
   - Use `$state.raw` for large arrays (CVaR history, drift alerts) — avoids proxy overhead
   - Use `$state` for small objects (regime) — allows granular mutation tracking
   - Guard `checkStale()` to only mutate when status actually changes — prevents unnecessary `$derived` cascade
   - Cache `Intl.DateTimeFormat` instances in `stale.ts` — current `toLocaleString` creates new formatter per call
   - Batch risk API calls into single backend endpoint (`GET /risk/summary?profiles=a,b,c`) — reduces 10+ concurrent requests to 1

   **Degraded State Banner Pattern:**
   - Amber banner for degraded: "Live connection interrupted. Showing data from {timestamp}. Reconnecting..."
   - Red banner for offline: "Unable to reach server. Last update: {timestamp}. [Retry]"
   - Mount banners in `(team)/+layout.svelte` above route content

   **Svelte 5 Patterns:**
   - Store creation: factory function with `$state` + getter returns (already correct in codebase)
   - Store lifecycle: `$effect` with cleanup return in `+layout.svelte`
   - Computed views: always `$derived`, never `$effect` for derived state
   - Context sharing: `setContext` in layout, `getContext` in pages (SSR-safe)

   **SSE Connection Budget:**
   - Current cap: 4 connections (sse-registry.svelte.ts)
   - Plan adds: risk-store SSE + long-running action SSE + potential drift-history feed
   - Solution: multiplex related events onto single SSE connection per frontend (1 primary + 1 LRA max)
   - Enhancement: add HTTP/2 detection to dynamically raise limit to 8 when available

3. Wealth drift-history implementation
   Must replace placeholder drift-history UI with a real event timeline, table, and export flow because it is the portfolio audit surface.
   Frontend focus: `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte`, new drift-history panel components under `frontends/wealth/src/lib/components`.
   Dependency: Backend history and export endpoints required.

   ### Research Insights

   **Chart Implementation (svelte-echarts mandatory):**
   - Use timeline chart with scatter overlay for drift events — canvas renderer (already configured in `echarts-setup.ts`)
   - Enable `dataZoom` for period navigation (already registered)
   - Set `large: true` and `largeThreshold: 500` for series with many data points
   - 3 years of daily drift = 756 points — ECharts handles this easily in canvas mode
   - Add generation-counter or shallow-equality guard to `ChartContainer` `$effect` to prevent unnecessary full chart rebuilds

   **Event Table Pattern:**
   - Date range picker + severity filter + asset class filter in filter bar
   - Columns: date, drift magnitude, threshold, breached assets, rebalance triggered (yes/no), severity
   - Row expansion for per-asset-class drift breakdown
   - Use `DataTable` with `pageSize` capped at 50 for drift events

   **Export:**
   - CSV export from client-side table data (immediate, no backend round-trip)
   - PDF export via backend endpoint (pre-formatted compliance report)
   - Export button in panel header with dropdown for format selection

   **Performance:**
   - Use `$state.raw` for drift history arrays (replaced wholesale from API)
   - Lazy-load the drift panel — only mount when user expands the section

4. Admin change governance
   Must make config and setup actions consequence-aware before more operator features are added.
   Frontend focus: `frontends/admin/src/lib/components/ConfigEditor.svelte`, `frontends/admin/src/lib/components/ConfigDiffViewer.svelte`, `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`.
   Dependency: Backend must return reliable diff context, impact counts, mutation history, and actor metadata.

   ### Research Insights

   **Code Editor: CodeMirror 6 (not Monaco):**
   - ~90KB gzipped total vs Monaco's 2-5MB — dramatically smaller
   - Modular: import only needed extensions (JSON mode, diff gutter, lint)
   - First-party Jinja2 support: `@codemirror/lang-jinja` with overlay parsing
   - First-party diff: `@codemirror/merge` with split and unified views
   - JSON schema validation: `codemirror-json-schema` (lint + autocomplete + hover)
   - No web workers, no SSR complications, no CDN dependency

   **Architecture Decision: CodeEditor is admin-local, not @netz/ui.**
   Only Admin uses it (single consumer). Placing a ~90KB dependency in `@netz/ui` would add weight to Credit and Wealth bundles even with tree-shaking (SvelteKit's Vite build does not always eliminate dynamic Svelte component imports cleanly). Keep at `frontends/admin/src/lib/components/CodeEditor.svelte`. Promote to `@netz/ui` only when a second consumer exists.

   **Lazy Loading Pattern:**
   ```typescript
   // Dynamic import — only loads when component mounts
   onMount(async () => {
     const [{ EditorView, basicSetup }, { json }] = await Promise.all([
       import("codemirror"),
       import("@codemirror/lang-json"),
     ]);
     // Initialize editor
   });
   ```
   Route-level code splitting is automatic in SvelteKit — admin config page loads editor code only when navigated to.

   **Critical Integration Pattern: `isInternalUpdate` guard.**
   When syncing CodeMirror state with Svelte 5 runes, an `isInternalUpdate` flag must break the update loop: editor changes → `onchange` → `value` update → `$effect` → dispatch back to editor. Without the guard, undo history is destroyed.

   **Diff View:**
   - Default: split (side-by-side) view for config change review — more natural for JSON diffs
   - Toggle to unified view for narrow viewports or small changes
   - `collapseUnchanged: { margin: 3, minSize: 4 }` to focus on differences
   - Add text summary above diff: "3 properties changed, 1 added, 2 modified" for screen readers

   **Recommended packages:**
   ```
   codemirror ^6.0, @codemirror/lang-json ^6.0, @codemirror/lang-jinja ^0.1,
   @codemirror/merge ^6.0, @codemirror/lint ^6.0, codemirror-json-schema ^0.7
   ```

   **Two-layer validation:**
   - Layer 1: `jsonParseLinter()` at 300ms debounce — catches syntax errors instantly
   - Layer 2: `jsonSchemaLinter()` at 750ms debounce — heavier schema validation after pause
   - Dynamic schema updates via `updateSchema(view, newSchema)` when user switches config types

5. Admin tenant scope clarity
   Must surface tenant identity and blast radius in every tenant-scoped and global-impact action flow.
   Frontend focus: `frontends/admin/src/lib/components/TenantCard.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte`, `frontends/admin/src/lib/components/ConfigEditor.svelte`.
   Dependency: Frontend-only for most header and dialog work; backend needed only for tenant metadata fields not already exposed.

   ### Research Insights

   **Blast Radius Display Patterns:**
   - Every global-impact action must include explicit scope in button labels: "Apply to ALL tenants" not just "Apply"
   - Tenant-scoped actions show tenant name + org_id in button: "Save for [TenantName]"
   - `ConsequenceDialog` consequences list must enumerate affected entities: "This will affect 12 active portfolios across 3 funds"

   **Persistent Context Header:**
   - `EntityContextHeader` renders above all tenant-scoped content, never scrolls off-screen (sticky)
   - Shows: tenant name, org_id, plan tier, status badge, freshness metadata
   - Color-coded border: production tenants = blue, sandbox = amber, inactive = gray

## 2. Shared Primitive Backlog (@netz/ui)

**Status note:** Items 1 and 2 already exist in the codebase. The work described is enhancement, not creation.

1. `AuditTrailPanel.svelte` — ENHANCE (exists)
   Purpose: Render immutable action history with actor, capacity, timestamp, rationale, and outcome.
   Why needed: Credit and Admin both fail at visible post-action auditability; Wealth needs the same pattern for drift/rebalance history.
   Domains: Credit, Wealth, Admin
   Files: modify `packages/ui/src/lib/components/AuditTrailPanel.svelte`; update exports in `packages/ui/src/lib/index.ts`.

   ### Research Insights

   **Required Interface Changes:**
   - Add `actorCapacity?: string` to `AuditTrailEntry` — compliance requires "in what capacity"
   - Add `actorEmail?: string` — for compliance cross-reference
   - Add `immutable?: boolean` — visual indicator (lock icon) for backend-persisted vs. optimistic entries
   - Add `sourceSystem?: string` — "ic-workflow", "pipeline-engine", "manual"

   **Accessibility Enhancements:**
   - Add `role="log"`, `aria-labelledby`, `aria-live="polite"`, `aria-atomic="false"` to entry list
   - Wrap timestamps in `<time datetime={iso}>` elements
   - Use `<dl>` definition lists for entry metadata (already done)

   **Performance:**
   - Add `maxVisible` prop (default 50) — only render recent entries, "Load earlier" trigger for history
   - Replace internal `formatTimestamp` with shared `formatDateTime` from `format.ts` — avoids per-render `Intl.DateTimeFormat` allocation
   - Use `$state.raw` for the entries array (replaced wholesale, not mutated)

   **Rendering Enhancements:**
   - Date-group headers: "Today", "Yesterday", "Mar 14, 2026" when trail grows beyond 3 entries
   - Typed `Snippet<[AuditTrailEntry]>` render prop for custom row rendering per domain
   - PDF/CSV export action in panel header

2. `ConsequenceDialog.svelte` — ENHANCE (exists)
   Purpose: Standardize high-consequence confirmation with scope, warnings, required rationale, actor block, and explicit confirm language.
   Why needed: Current dialogs confirm actions but do not enforce institutional evidence or scope clarity.
   Domains: Credit, Admin, later Wealth allocation approvals
   Files: modify `packages/ui/src/lib/components/ConsequenceDialog.svelte`; `packages/ui/src/lib/components/ConfirmDialog.svelte` already adapted.

   ### Research Insights

   **AlertDialog Migration (compliance-critical):**
   - Migrate from `Dialog.Root` (bits-ui) to `AlertDialog.Root` for correct `role="alertdialog"` semantics
   - `AlertDialog.Action` does NOT auto-close — exactly right for async operations that might fail
   - Focus Cancel button on open for destructive actions via `onOpenAutoFocus` handler
   - Prevent Escape key during submission — handle `onEscapeKeyDown` during submitting state

   **Content Enhancements:**
   - Add explicit consequences list section — bulleted "what will happen" beyond impact summary
   - Add named snippets for finer-grained composition: `consequenceList?: Snippet`, `footer?: Snippet<[{ canConfirm; submitting }]>`
   - Add `aria-required="true"` on rationale textarea when `requireRationale` is true
   - Add `aria-describedby` on rationale textarea pointing to hint text

3. `StatusBadge` domain-mapper hardening
   Purpose: Separate raw status tokens from domain-facing display labels, severity semantics, and optional rationale tooltips.
   Why needed: Raw enums are leaking in Credit and Wealth and generic status semantics are weakening Admin clarity.
   Domains: Credit, Wealth, Admin
   Files: modify `packages/ui/src/lib/components/StatusBadge.svelte`; create domain-specific mapper files in each frontend.

   ### Research Insights

   **Architecture Decision: Domain maps live in frontends, not @netz/ui.**
   The architecture review identified that placing Credit deal-stage labels in `@netz/ui` violates the abstraction boundary. When Credit adds a new deal stage, `@netz/ui` would need updating, forcing rebuild of Wealth and Admin.

   **Recommended Pattern:**
   - `StatusBadge` accepts a generic `colorMap` prop or a `resolve: (token: string) => StatusConfig` function prop
   - `@netz/ui` exports `resolveStatus()` utility with `StatusConfig` type (`label`, `severity`, `color`)
   - Domain-specific maps live at `frontends/{vertical}/src/lib/utils/status-maps.ts`
   - Severity type: `"neutral" | "info" | "success" | "warning" | "danger"` — enables programmatic severity checks

   **Binding Design Decisions (D1-D9) from learnings:**
   - No hardcoded hex values in components (D2/D5) — use `var(--netz-*)` tokens
   - No `DataCard` for financial KPIs in Wealth — use `MetricCard` (D7)
   - Backend schemas must include `alert_type` literal discriminators — no `meta: unknown` (D6)
   - These 9 decisions are acceptance criteria for all remediation changes

4. Shared formatting layer
   Purpose: Make date, currency, percent, and financial-number formatting mandatory through one import path.
   Why needed: Ad hoc formatting is causing ambiguous dates, locale drift, and inconsistent financial presentation.
   Domains: Credit, Wealth, Admin
   Files: modify `packages/ui/src/lib/utils/format.ts`; update barrel exports in `packages/ui/src/lib/index.ts`.

   ### Research Insights

   **Codebase Audit Findings — Formatter Drift is Systemic:**
   - 50+ ad-hoc `.toFixed()` calls scattered across wealth/credit frontends
   - 6 local `formatDate` redeclarations shadowing `@netz/ui`'s version
   - 5 local `formatPercent` reimplementations
   - 12+ inline `(value * 100).toFixed(N)%` patterns
   - 4 local AUM formatters
   - 3 `value.toLocaleString("pt-BR")` calls bypassing the format utility

   **New Formatters Required:**
   - `formatAUM(value, currency, locale)` — compact currency: "R$ 1.2B", "$350M"
   - `formatBps(value, { signed })` — basis points: "150 bps", "+25 bps"
   - `formatNAV(value, currency, locale)` — per-share: "$1,234.5678" (4 decimals)
   - `formatRatio(value, decimals, suffix)` — "1.23x", "0.85"
   - `formatNumber(value, decimals, locale)` — generic with null→em-dash
   - `formatDateTime(date, locale)` — "17 Mar 2026, 14:30" for audit trails
   - `formatRelativeDate(date, locale)` — "2 days ago", "in 3 hours"
   - `plColor(value)` — returns CSS variable for P&L coloring
   - `plDirection(value)` — "up" | "down" | "flat" for MetricCard delta

   **Performance: Formatter Caching (critical).**
   `Intl.NumberFormat` and `Intl.DateTimeFormat` construction is expensive (10-50μs per instance). Current code creates new instances per call. Add a `Map<string, Intl.NumberFormat>` cache keyed by format parameters. The `.format()` call is cheap — only construction matters.

   **Null Handling Convention:**
   Every formatter accepts `null | undefined` and returns `"\u2014"` (em-dash). Eliminates the pervasive `value !== null ? value.toFixed(2) : "\u2014"` pattern.

   **Existing `formatPercent` Bug:**
   Current implementation uses manual `(value * 100).toFixed(decimals) + "%"` — loses locale-aware decimal separators and sign display. Replace with `Intl.NumberFormat` with `style: "percent"` and `signDisplay: "exceptZero"`.

   **ESLint Enforcement (three layers):**
   1. `no-restricted-syntax` rules banning `.toFixed()`, `.toLocaleString()`, inline `new Intl.NumberFormat/DateTimeFormat` in components
   2. `no-restricted-imports` preventing import from internal `**/utils/format` path — force barrel import from `@netz/ui`
   3. CLAUDE.md rule: "All number/date/currency formatting MUST use formatters from `@netz/ui`"

   **Migration Priority (by drift severity):**
   1. `frontends/wealth/src/routes/(team)/allocation/+page.svelte` — 10+ inline `.toFixed()` calls
   2. `frontends/wealth/src/routes/(team)/analytics/+page.svelte` — 5+ inline `.toFixed()` calls
   3. `frontends/wealth/src/lib/components/FundDetailPanel.svelte` — 3 local formatters
   4. `frontends/wealth/src/lib/components/MacroChips.svelte` — 4 inline `.toFixed()` calls
   5. `frontends/credit/src/lib/components/DealStageTimeline.svelte` — raw `new Date().toLocaleDateString()`

5. `CodeEditor.svelte` — ADMIN-LOCAL (not @netz/ui)
   Purpose: Provide syntax-highlighting, debounced validation, accessible error output, and split diff support for JSON and template editing.
   Why needed: Admin config and prompt editing cannot stay on plain textareas.
   Domains: Admin only
   Files: create `frontends/admin/src/lib/components/CodeEditor.svelte`; create `frontends/admin/src/lib/components/ConfigDiffView.svelte`.

   ### Research Insights

   **Architecture Decision: Admin-local, NOT @netz/ui.**
   Single consumer (Admin). CodeMirror 6 adds ~90KB gzipped. Placing in `@netz/ui` barrel would add weight to Credit and Wealth bundles. SvelteKit's Vite build does not always tree-shake dynamic Svelte component imports cleanly. Keep admin-local; promote to `@netz/ui` only when a second consumer exists.

   **Library: CodeMirror 6.**
   See Risk Block 4 research insights for full details. Key packages: `codemirror`, `@codemirror/lang-json`, `@codemirror/lang-jinja`, `@codemirror/merge`, `@codemirror/lint`, `codemirror-json-schema`.

   **Component Architecture:**
   ```
   AdminConfigPage.svelte
     ConfigEditorPanel.svelte        (tab: "Edit" | "Template" | "Diff")
       JsonEditor.svelte             (JSON config with schema validation)
       JinjaEditor.svelte            (Jinja2 template with variable completions)
       ConfigDiffView.svelte         (split/unified diff of saved vs. draft)
     ConfigMetadataPanel.svelte      (version, author, timestamps)
   ```
   Keep JSON and Jinja editors as separate components — do not mix Jinja parsing inside JSON values.

   **Accessibility:**
   - `contenteditable` with `role="textbox"`, `aria-multiline="true"`, `aria-label`
   - Visible instructions: "Press Escape to leave the editor, Tab to indent"
   - Text summary above diff: "3 properties changed, 1 added, 2 modified" for screen readers
   - Lint errors announced via CM6's accessible lint panel

   **Security: XSS via `{@html}` + Jinja2 `safe` filter.**
   Admin frontend bug found in learnings: Jinja2 `safe` filter combined with `{@html}` enables stored XSS. Any remediation work rendering dynamic HTML must sanitize via nh3 or a `SafeHtml` component. Audit all `{@html}` usage in admin templates.

6. `EntityContextHeader.svelte`
   Purpose: Render always-visible identity blocks with slug, org_id, plan, status, and freshness metadata.
   Why needed: Admin tenant context and Credit/Wealth entity headers are too easy to misread or bury below the fold.
   Domains: Admin, Credit, Wealth
   Likely files: create `packages/ui/src/lib/components/EntityContextHeader.svelte`.

   ### Research Insights

   **Implementation Pattern:**
   - Sticky positioning — never scrolls off-screen
   - Color-coded border: production = blue, sandbox = amber, inactive = gray (via semantic tokens)
   - Compact layout: name | org_id | plan | status badge | freshness — all in one line
   - Snippet slot for domain-specific actions (e.g., "View Tenant" button for Admin)

7. `LongRunningAction` pattern
   Purpose: Standardize SSE or polling-driven progress with start, in-flight, success, error, retry, and cancellation states.
   Why needed: Wealth DD report and backtest flows, plus Credit report generation, are diverging into ad hoc implementations.
   Domains: Credit, Wealth, Admin
   Likely files: create `packages/ui/src/lib/components/LongRunningAction.svelte`; modify `packages/ui/src/lib/utils/sse-client.svelte.ts`.

   ### Research Insights

   **State Machine Design:**
   - States: `idle` → `starting` → `in-flight` → `success` | `error` | `cancelled`
   - `in-flight` substates: percentage, stage label, ETA (optional)
   - Error state includes retry action and failure details
   - Cancellation requires confirmation if job is past 50% progress

   **SSE Connection Budget:**
   - LongRunningAction consumes 1 SSE connection per active job
   - Must share connection pool with risk-store SSE — enforce max 2 SSE per frontend
   - If job completes, connection released immediately (not kept for polling)

8. `DataTable` hardening
   Purpose: Support dense operational tables, multi-sort, header associations, inline expansion hooks, and filter-bar composition.
   Why needed: Wealth fund browser and Admin tenant/worker views are blocked by current generic table limits.
   Domains: Wealth, Admin, selective Credit use
   Likely files: modify `packages/ui/src/lib/components/DataTable.svelte`.

   ### Research Insights

   **Performance:**
   - Cap `pageSize` at 100 maximum — enforce in component: `const effectivePageSize = Math.min(pageSize, 100)`
   - Add `totalCount` prop for server-side pagination scenarios
   - For tables > 500 rows (worker monitor logs), consider virtual scrolling container
   - `@tanstack/svelte-table` recalculates full sorted/filtered model on every data change before paginating — O(n log n) on full dataset

   **Features to Add:**
   - Multi-sort with shift-click on column headers
   - Row expansion with `Snippet<[RowData]>` render prop for expanded content
   - Filter-bar composition: typed filter controls per column
   - Column pinning for identity columns (name, ID)
   - Export action: CSV from client-side filtered/sorted data

9. `Optimistic Mutation Utility` — NEW
   Purpose: Shared pattern for optimistic UI updates with rollback on failure.
   Why needed: Credit IC decisions and Admin config saves both need to show immediate feedback while awaiting server response.
   Domains: Credit, Admin, Wealth (allocation saves)
   Likely files: create `packages/ui/src/lib/utils/optimistic.svelte.ts`.

   ### Research Insights

   **Pattern:**
   - `createOptimisticMutation<T>()` factory returns `{ mutate, rollback, isPending, error }`
   - On `mutate()`: immediately update local state, fire async request
   - On success: replace optimistic state with server response, call `invalidateAll()`
   - On failure: rollback to pre-mutation state, show error banner
   - Distinguishes "pending" entries (dashed border, spinner) from "confirmed" entries (solid, lock icon)

## 3. Domain Remediation Backlog

### Credit
1. IC decision workflow hardening
   Problem: Approve, reject, convert, and condition-resolution actions are not audit-safe.
   Recommended implementation direction: Replace current decision dialogs with `ConsequenceDialog` (AlertDialog migration), require rationale and actor block, append optimistic audit entry through `AuditTrailPanel`, and disable submit until evidence fields are present.
   Likely files/components affected: `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`, `packages/ui/src/lib/components/ConsequenceDialog.svelte`, `packages/ui/src/lib/components/AuditTrailPanel.svelte`
   Dependency on backend/data-contract: Yes; decision and conversion payloads plus audit-event response contract
   Severity: Critical
   Effort: M

2. Document review decision governance
   Problem: Review decisions and checklist reversals can occur without rationale or durable visible history.
   Recommended implementation direction: Add required rationale with minimum-length validation, gate checklist uncheck through `ConsequenceDialog`, and render decision history in-page.
   Likely files/components affected: `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`, `packages/ui/src/lib/components/AuditTrailPanel.svelte`
   Dependency on backend/data-contract: Yes; review decision payload/history contract
   Severity: Critical
   Effort: M

3. Credit data-contract expansion
   Problem: Deal and portfolio views cannot render tenor, basis, covenant, collateral, and agreement-language detail.
   Recommended implementation direction: Expand typed models first, then rebuild detail sections around those fields instead of retrofitting generic cards. Use `formatBps()` for spreads, `formatCurrency()` for notional amounts, `formatRatio()` for LTV.
   Likely files/components affected: `frontends/credit/src/lib/types/api.ts`, `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`
   Dependency on backend/data-contract: Yes; new deal, portfolio, covenant, and memo metadata fields
   Severity: Critical
   Effort: L

4. Action-first dashboard and pipeline reconstruction
   Problem: Dashboard and pipeline surfaces prioritize summary widgets and generic tables over actionable work.
   Recommended implementation direction: Move `TaskInbox` and stage filters to first viewport, add stage-driven list/Kanban controls, and demote analytics to secondary regions.
   Likely files/components affected: `frontends/credit/src/routes/(team)/dashboard/+page.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`, `frontends/credit/src/lib/components/TaskInbox.svelte`
   Dependency on backend/data-contract: Partial; frontend-only for layout, backend-dependent for stage counts if not already exposed
   Severity: High
   Effort: M

5. Document lineage and AI provenance surface
   Problem: Upload, classification, review, AI analysis, and decision evidence are fragmented across pages.
   Recommended implementation direction: Create a unified document lifecycle timeline with AI labels, timestamps, model metadata, reviewer metadata, and decision links. Reuse `AuditTrailPanel` with custom `Snippet<[AuditTrailEntry]>` row rendering for document-specific events.
   Likely files/components affected: `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte`, `frontends/credit/src/lib/components/ICMemoViewer.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte`
   Dependency on backend/data-contract: Yes; classification, AI provenance, memo review, and decision timeline fields
   Severity: High
   Effort: L

6. Domain-language and formatting enforcement
   Problem: Raw stage labels, ambiguous dates, and inconsistent number formatting remain visible.
   Recommended implementation direction: Migrate Credit routes to shared formatters and status mappers; block raw badge rendering in domain routes. Specific file: `DealStageTimeline.svelte` line 25 uses raw `new Date(event.transitioned_at).toLocaleDateString()` — replace with shared `formatDate()`.
   Likely files/components affected: `packages/ui/src/lib/components/StatusBadge.svelte`, `packages/ui/src/lib/utils/format.ts`, `frontends/credit/src/lib/components/DealStageTimeline.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/documents/[documentId]/+page.svelte`
   Dependency on backend/data-contract: No
   Severity: High
   Effort: S

7. Memo and reporting workflow hardening
   Problem: Memo review gating and long-running reporting behavior are incomplete.
   Recommended implementation direction: Add memo review metadata and voting gate, then move report generation to shared long-running progress pattern.
   Likely files/components affected: `frontends/credit/src/lib/components/ICMemoViewer.svelte`, `frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte`, `packages/ui/src/lib/components/LongRunningAction.svelte`
   Dependency on backend/data-contract: Yes for memo reviewer metadata; frontend-only for progress pattern reuse if reporting status exists
   Severity: High
   Effort: M

### Wealth
1. Authoritative live-risk state spine
   Problem: Risk data updates, freshness, and staleness are handled inconsistently across store, page-local SSE, and ad hoc streams.
   Recommended implementation direction: Make `risk-store.svelte.ts` the only live-risk entry point, route all updates through single `applyUpdate()` gate, derive freshness from server `computed_at` timestamps only. SSE-primary, poll-fallback architecture.
   Likely files/components affected: `frontends/wealth/src/lib/stores/risk-store.svelte.ts`, `frontends/wealth/src/lib/stores/stale.ts`, `frontends/wealth/src/routes/(team)/+layout.svelte`, `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`, `frontends/wealth/src/lib/components/FundDetailPanel.svelte`
   Dependency on backend/data-contract: Yes; `computed_at` + `next_expected_update` fields in all responses, consistent SSE event shapes, batched risk summary endpoint
   Severity: Critical
   Effort: L

2. Drift-history workbench
   Problem: Portfolio drift history is a placeholder shell instead of the audit record.
   Recommended implementation direction: Build a real panel with event table, period filters, timeline chart (svelte-echarts with `large: true`), rebalance rows, and CSV/PDF export wiring. Lazy-load the drift panel.
   Likely files/components affected: `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte`, new `frontends/wealth/src/lib/components/DriftHistoryPanel.svelte`, `packages/ui/src/lib/components/AuditTrailPanel.svelte`
   Dependency on backend/data-contract: Yes; history and export endpoints
   Severity: Critical
   Effort: L

3. Allocation editor governance rebuild
   Problem: Strategic edits bypass rationale, simulation, approval flow, and effective allocation evidence.
   Recommended implementation direction: Replace plain inputs with governed controls, pre-save simulation summary, required rationale via `ConsequenceDialog`, approval-routing states, and selected-fund/effective-CVaR evidence.
   Likely files/components affected: `frontends/wealth/src/routes/(team)/allocation/+page.svelte`, new allocation editor subcomponents under `frontends/wealth/src/lib/components`
   Dependency on backend/data-contract: Yes; simulation endpoint, approval-routing state, effective allocation detail
   Severity: Critical
   Effort: L

4. Backtest and Pareto decision-pack split
   Problem: PM-facing workflow is buried in a generic analytics lab and uses the wrong interaction model.
   Recommended implementation direction: Pull backtest into a dedicated route or surface, replace raw Pareto scatter with guided control/slider interaction, and standardize long-running job state via `LongRunningAction`.
   Likely files/components affected: `frontends/wealth/src/routes/(team)/analytics/+page.svelte`, possible new `frontends/wealth/src/routes/(team)/backtest/+page.svelte`, `packages/ui/src/lib/components/LongRunningAction.svelte`
   Dependency on backend/data-contract: Partial; frontend can restructure presentation, backend may be needed for richer scenario outputs
   Severity: Critical
   Effort: L

5. Dashboard decision-surface completion
   Problem: Dashboard still contains placeholders and misleading freshness copy.
   Recommended implementation direction: Replace placeholder central block with drift-alert and activity modules, wire card actions to decision paths, and bind all freshness copy to store `computed_at` timestamps (never client `Date.now()`).
   Likely files/components affected: `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`, `frontends/wealth/src/lib/components/PortfolioCard.svelte`
   Dependency on backend/data-contract: Partial; frontend-only if underlying alert and activity data already exists
   Severity: High
   Effort: M

6. Portfolio detail workbench rebuild
   Problem: Portfolio detail is a summary page rather than the specified manager workbench.
   Recommended implementation direction: Recompose as multi-region workspace with allocation navigator, full allocation table, and before/after rebalance sections.
   Likely files/components affected: `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte`, new portfolio workbench components under `frontends/wealth/src/lib/components`
   Dependency on backend/data-contract: Partial; full allocation and rebalance detail may require additional fields
   Severity: High
   Effort: L

7. Domain-language, accessibility, and chart-stack alignment
   Problem: Raw enums, inconsistent locale policy, and non-compliant chart integration continue across Wealth screens.
   Recommended implementation direction: Introduce Wealth label mappers (at `frontends/wealth/src/lib/utils/status-maps.ts`), central formatters from `@netz/ui`, chart accessibility props, and shallow-equality guard on `ChartContainer` `$effect`. Migrate all 50+ `.toFixed()` calls to shared formatters.
   Likely files/components affected: `packages/ui/src/lib/components/StatusBadge.svelte`, `packages/ui/src/lib/charts/ChartContainer.svelte`, `frontends/wealth/src/lib/components/PortfolioCard.svelte`, `frontends/wealth/src/routes/(team)/risk/+page.svelte`
   Dependency on backend/data-contract: No for mapping/formatting/accessibility; no backend dependency for chart wrapper migration
   Severity: High
   Effort: M

### Admin
1. Consequence-aware config editing
   Problem: Config changes do not show reliable diff context, exact impact scope, or durable history.
   Recommended implementation direction: Replace the current editor flow with admin-local `CodeEditor` (CodeMirror 6, lazy-loaded), permanent side-by-side diff via `@codemirror/merge`, explicit scope block, toast plus audit trail refresh, and action labels that name tenant/global impact.
   Likely files/components affected: `frontends/admin/src/lib/components/ConfigEditor.svelte`, `frontends/admin/src/lib/components/ConfigDiffViewer.svelte`, `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte`, new `frontends/admin/src/lib/components/CodeEditor.svelte`, `packages/ui/src/lib/components/AuditTrailPanel.svelte`
   Dependency on backend/data-contract: Yes; real diff data, impact counts, mutation history, actor identity
   Severity: High
   Effort: L

2. Tenant identity and scope headers
   Problem: Operators can act without persistent tenant identity or clear blast-radius copy.
   Recommended implementation direction: Introduce `EntityContextHeader` across tenant pages and update every global-impact action to include explicit scope wording in button labels and dialogs.
   Likely files/components affected: `frontends/admin/src/lib/components/TenantCard.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte`, `frontends/admin/src/lib/components/ConfigEditor.svelte`
   Dependency on backend/data-contract: Mostly frontend-only
   Severity: High
   Effort: M

3. Health degraded-state visibility
   Problem: Health UI suppresses failures and omits freshness metadata.
   Recommended implementation direction: Preserve loader errors in page data via `Promise.allSettled` (never `Promise.all`), add degraded-state banners and per-section error panels, and render global plus per-service `checked_at`. Use `ErrorBoundary` with "degraded" mode for partial-failure rendering.
   Likely files/components affected: `frontends/admin/src/routes/(admin)/health/+page.server.ts`, `frontends/admin/src/routes/(admin)/health/+page.svelte`, `frontends/admin/src/lib/components/ServiceHealthCard.svelte`
   Dependency on backend/data-contract: Partial; frontend-only for error preservation, backend needed if `checked_at` is not returned
   Severity: High
   Effort: M

4. Worker monitor and log console upgrade
   Problem: Worker table and log feed are not an operator-grade monitor.
   Recommended implementation direction: Replace raw table with hardened `DataTable` (multi-sort, filters, expansion), auto-connect logs via shared SSE client, add filters and severity styling, and move streaming onto the shared SSE client. Cap log page size at 100.
   Likely files/components affected: `frontends/admin/src/routes/(admin)/health/+page.svelte`, `frontends/admin/src/lib/components/WorkerLogFeed.svelte`, `packages/ui/src/lib/components/DataTable.svelte`, `packages/ui/src/lib/utils/sse-client.svelte.ts`
   Dependency on backend/data-contract: Partial; worker heartbeat and queue-depth fields required if not already available
   Severity: High
   Effort: M

5. Tenant IA completion
   Problem: Tenant-scoped config and setup flows are placeholders or misplaced.
   Recommended implementation direction: Replace placeholder routes with real pages, align tenant nav to the intended task model, and move seed/setup into a dedicated surface with explicit replacement warnings.
   Likely files/components affected: `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+layout.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/config/+page.svelte`, new `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/setup/+page.svelte`, `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`
   Dependency on backend/data-contract: Partial; depends on tenant-scoped config APIs and setup status data
   Severity: High
   Effort: L

6. Prompt editing ergonomics and audit depth
   Problem: Prompt editing is usable but still too thin for operator-grade control.
   Recommended implementation direction: Move to admin-local `CodeEditor` (CodeMirror 6 with `@codemirror/lang-jinja`), add explicit Validate and Run Preview controls, enrich history rows with actor and summary, and keep editing full-page. Lazy-load via dynamic `import()`.
   Likely files/components affected: `frontends/admin/src/lib/components/PromptEditor.svelte`, `frontends/admin/src/routes/(admin)/prompts/[vertical=vertical]/+page.svelte`, `frontends/admin/src/lib/components/CodeEditor.svelte`
   Dependency on backend/data-contract: Partial; actor and change-summary fields needed for history
   Severity: Medium
   Effort: M

7. Admin formatting, localization, and semantic tokens
   Problem: Operator surfaces still rely on generic tokens, hardcoded strings, and inconsistent technical formatting.
   Recommended implementation direction: Introduce Admin semantic tokens, centralize timestamp formatting via `formatDateTime` from `@netz/ui`, and move UI labels to i18n keys without altering raw log content. Audit all `var(--netz-*)` references and verify each exists in `tokens.css` (undeclared tokens were the single most common defect found in prior review).
   Likely files/components affected: `packages/ui/src/lib/styles/tokens.css`, `packages/ui/src/lib/components/StatusBadge.svelte`, `frontends/admin/src/routes/(admin)/health/+page.svelte`, `frontends/admin/src/lib/components/WorkerLogFeed.svelte`
   Dependency on backend/data-contract: No
   Severity: Medium
   Effort: S

## 4. Structural Dependencies
1. Backend contract changes required
   Credit decision payloads and history responses; Credit deal/portfolio term models; Credit document lineage and AI provenance metadata; Wealth source timestamps (`computed_at`, `next_expected_update`) and SSE event shapes; Wealth batched risk summary endpoint; Wealth drift-history and export endpoints; Wealth allocation simulation and approval state; Admin config diff, impact counts, mutation history, actor metadata; Admin worker heartbeat and queue metrics where absent.

   ### Research Insights

   **Backend Contract Milestones (NEW):**
   Every domain item marked "Dependency on backend/data-contract: Yes" must have its OpenAPI endpoint defined and `make types` regenerated BEFORE frontend work begins on that item. This is a hard gate — not a soft dependency.

   **Enforcement mechanism:** `make types` generates TypeScript types from the OpenAPI schema. Frontend code uses these generated types. If the backend contract does not exist, the TypeScript types do not exist, and the frontend code will not compile. This is the enforcement point.

   **Recommended ordering:**
   - Sprint 1 backend: Credit decision payloads, Wealth `computed_at` fields, Admin `checked_at` fields
   - Sprint 2 backend: Wealth drift-history endpoints, Admin diff/history endpoints, Credit term models
   - Sprint 3 backend: Wealth simulation endpoint, Credit AI provenance fields, Admin worker heartbeat

2. Shared state or model changes required
   Wealth must move to one authoritative `risk-store.svelte.ts` update path with SSE-primary/poll-fallback architecture; shared status-mapping and formatting utilities must replace route-local logic; `DataTable`, SSE client, and audit primitives must become reusable enforcement points rather than optional helpers.

3. Frontend-only fixes
   Credit and Wealth status-label mapping; shared date/currency formatting adoption (50+ `.toFixed()` replacements); Admin tenant headers and scope copy; Admin degraded-state rendering via `Promise.allSettled`; Wealth dashboard layout cleanup; long-running progress UX where existing endpoints already expose progress; accessibility and semantic-token hardening in shared components; `{@html}` XSS audit across all frontends; CSS token audit (scan for undeclared `var(--netz-*)` references).

## 5. Security Hardening Requirements (NEW)

### Research Insights

1. **Server-side enforcement of all governance rules.** The ConsequenceDialog enforces rationale and actor identity in the UI, but the backend must independently validate: non-empty rationale, actor identity from JWT (not form fields), minimum rationale length, and valid actor capacity for the action type. The frontend is a convenience layer, not a security boundary.

2. **`{@html}` XSS audit.** The learnings revealed that Jinja2 `safe` filter combined with Svelte `{@html}` enables stored XSS. Every `{@html}` usage must be audited. Dynamic HTML rendering must use nh3 sanitization or a `SafeHtml` component wrapper.

3. **Audit trail immutability.** Client-side audit entries are optimistic display only. The backend must persist entries in an append-only log. The client renders server-provided entries but cannot create, modify, or delete them. Distinguish "pending" (optimistic) from "confirmed" (server-persisted) entries visually.

4. **SSE tenant isolation.** All SSE streams must be scoped to the authenticated organization_id from JWT claims. Cross-tenant data leakage in SSE is as severe as in REST endpoints. The fail-closed pattern (empty stream rather than cross-tenant data) means the frontend should surface "No data available" rather than a blank state.

5. **Config diff cross-tenant leakage.** Admin config diff data could leak cross-tenant information if the diff endpoint does not properly scope to the requested tenant. The backend must validate that the requesting admin has access to both the "before" and "after" config states.

6. **CodeEditor XSS via template content.** The CodeMirror editor renders content in a `contenteditable` div. While CM6 escapes content by default, custom extensions or tooltip renderers that use `innerHTML` could introduce XSS. Validate that all CM6 extension configurations use text-only rendering.

## 6. Performance Budget (NEW)

### Research Insights

| Component | Budget | Current | Action |
|---|---|---|---|
| CodeEditor (CodeMirror 6) | 90KB gzipped, lazy | 0 (not yet built) | Dynamic `import()`, admin-local only |
| AuditTrailPanel DOM | Max 50 entries initial | Unbounded | `maxVisible` prop with "Load more" |
| DataTable page size | Max 100 rows | 10 (safe) | Enforce cap in component |
| Risk store API calls | 1 request per poll | 10+ parallel | Batch into single endpoint |
| SSE connections | Max 2 per frontend | Variable | Multiplex events, enforce in registry |
| Intl.NumberFormat | Cached (1 per format) | New instance per call | Add Map cache to format.ts |
| ChartContainer rebuilds | Only on data change | Every reactive update | Shallow equality guard |
| Formatter per-call cost | <1μs | 10-50μs (new instance) | Hoist/cache all formatters |

**Priority actions (Sprint 1):**
1. Lazy-load CodeEditor via dynamic import
2. Add `maxVisible` to AuditTrailPanel
3. Batch risk store API calls
4. Hoist `Intl.DateTimeFormat` instances in `format.ts`

## 7. 4-Sprint Plan (revised from 3)

### Research Insights

The architecture review found the original 3-sprint timeline unrealistic: 7 Large + 8 Medium items in 3 sprints requires 3+ weeks per sprint with 2+ dedicated frontend engineers. Sprint 2 was overloaded as the heaviest sprint with no buffer. Splitting into 4 sprints with a clear integration checkpoint is more defensible.

**Sequencing concern resolved:** The original plan put `AuditTrailPanel` and `ConsequenceDialog` landing in Sprint 2, but Sprint 1 already uses them. Since both already exist, Sprint 1 consumes them as-is; Sprint 2a hardens/extends them.

1. Sprint 1: risk reduction + performance foundations
   Ship Credit consequence dialogs and visible audit panels for IC and review actions (consuming existing `AuditTrailPanel` and `ConsequenceDialog`); remove Wealth fake freshness and route all live-risk displays through the store with SSE-primary architecture; implement Admin tenant context headers, config scope copy, and degraded-state banners via `Promise.allSettled`; convert no-op or misleading actions into real or explicitly disabled states; add `maxVisible` to AuditTrailPanel; hoist formatter instances; batch risk API calls.

   **Backend gate:** Credit decision payloads, Wealth `computed_at` fields, Admin `checked_at` fields must land before or during this sprint. Run `make types` to regenerate TS types.

2. Sprint 2a: shared primitive hardening
   Enhance `AuditTrailPanel` (accessibility, capacity field, immutability indicator, date groups); migrate `ConsequenceDialog` to AlertDialog; expand formatting layer with new formatters + caching; extract StatusBadge domain maps to frontends; add ESLint enforcement rules; implement `LongRunningAction` pattern; add `DataTable` multi-sort, expansion, filter-bar; build admin-local `CodeEditor` (CodeMirror 6, lazy-loaded).

   **Backend gate:** Wealth drift-history endpoints, Admin diff/history endpoints must be available. Run `make types`.

3. Sprint 2b: domain consumption
   Implement Wealth drift-history workbench; implement Admin config-history/diff flow with CodeEditor + MergeView; expand Credit typed models and begin deal/portfolio screen reconstruction; migrate 50+ `.toFixed()` calls to shared formatters; implement optimistic mutation pattern; audit and fix all `{@html}` XSS vectors.

   **Backend gate:** Credit term models, Wealth batched risk summary endpoint. Run `make types`.

4. Sprint 3: institutional UX consolidation
   Complete Wealth allocation and backtest decision surfaces; complete Credit action-first dashboard, pipeline, and document lineage; complete Admin tenant IA and worker-console rebuild with hardened DataTable; add component-boundary and review-gate enforcement so raw enums, placeholder panels, and auditless mutations cannot re-enter the codebase; run CSS token audit; enforce ESLint formatter rules in CI with zero warnings.

   **Backend gate:** Wealth simulation endpoint, Credit AI provenance fields, Admin worker heartbeat. Run `make types`.

## 8. Definition of Done
1. Credit decision governance
   Done when no IC or document-review action can submit without rationale, actor identity, actor capacity, scope, and timestamp; successful mutation appends a visible audit entry (optimistic with pending indicator, then confirmed with lock icon) in the same view; raw generic confirm dialogs are removed from those flows; `ConsequenceDialog` uses `AlertDialog` with correct ARIA semantics; server-side validation independently enforces all governance rules.

2. Credit data-contract remediation
   Done when deal and portfolio screens render tenor, basis, covenant frequency, collateral context, and agreement-language fields from typed models (generated via `make types`) rather than placeholder text or omissions; all financial values use shared formatters (`formatBps`, `formatCurrency`, `formatRatio`).

3. Wealth live-state integrity
   Done when dashboard, portfolio, risk, and fund-detail surfaces consume one store-backed freshness model with SSE-primary/poll-fallback architecture; no page-local SSE or ad hoc stream remains for risk state; displayed freshness always reflects backend `computed_at` timestamps; degraded state banner renders when connection quality drops.

4. Wealth drift-history
   Done when the portfolio view can open a populated drift-history surface with filters, timeline chart (svelte-echarts with `large: true`), event rows, and CSV/PDF export actions backed by real data; panel is lazy-loaded.

5. Wealth allocation governance
   Done when strategic edits require rationale (via `ConsequenceDialog`), show pre-save risk impact, respect approval states, and render effective allocation evidence including selected funds and CVaR utilization; all allocation values use `formatPercent`/`formatBps` from `@netz/ui`.

6. Admin config governance
   Done when config editing uses CodeMirror 6 (lazy-loaded, admin-local), shows live split diff via `@codemirror/merge`, names exact scope and impact before confirm via `ConsequenceDialog`, and refreshes visible mutation history after save, revert, or default update; JSON validated with two-layer linting (syntax 300ms + schema 750ms).

7. Admin operator clarity
   Done when every tenant-scoped page shows persistent `EntityContextHeader`, health screens render degraded states via `Promise.allSettled` and `checked_at` timestamps, and worker monitoring supports sort/filter/log drilldown via hardened `DataTable` without manual connection steps.

8. Shared primitive adoption
   Done when consequence handling (AlertDialog), audit display (`role="log"`), formatting (cached `Intl` formatters, ESLint enforced), status mapping (domain maps in frontends, generic in `@netz/ui`), and long-running progress are all consumed through `@netz/ui` primitives in the remediated flows, not reimplemented route by route.

9. Security hardening
   Done when all `{@html}` usage is audited and sanitized; all governance rules are server-enforced (not just UI); SSE streams are tenant-isolated; no undeclared `var(--netz-*)` tokens exist; ESLint `no-restricted-syntax` rules run in CI with zero warnings.

10. Performance budget
    Done when CodeEditor is lazy-loaded (~90KB, admin-only); AuditTrailPanel caps initial render at 50 entries; DataTable pageSize capped at 100; risk store uses batched API endpoint; all `Intl.NumberFormat/DateTimeFormat` instances are cached; ChartContainer has shallow-equality guard.

## 9. Acceptance Criteria from Binding Design Decisions (D1-D9)

These 9 decisions from the Wealth frontend review are mandatory acceptance criteria for ALL remediation changes:

| Decision | Rule | Violation |
|---|---|---|
| D1 | Navigation is TopNav (global) + ContextSidebar (entity) — two orthogonal levels | Using Sidebar as global nav |
| D2 | No hardcoded hex values in components | Any `#RRGGBB` in `.svelte` files |
| D3 | TopNav/ContextSidebar requires both `<head>` script AND `transformPageChunk` for theme | Missing either anti-FOUC mechanism |
| D4 | All CSS tokens must be declared in `tokens.css` | Referencing undeclared `var(--netz-*)` |
| D5 | Semantic tokens only — never raw hex | Hardcoded colors in inline styles |
| D6 | Discriminated unions for alert types — no `meta: unknown` | Flat/untyped alert objects |
| D7 | Use `MetricCard` for financial KPIs, not `DataCard` | `DataCard` rendering financial values |
| D8 | Backend schemas must include `alert_type` literal discriminator | Missing discriminator field |
| D9 | Lock integration contracts (tokens, routes, SSE, components) before delegating work | Starting implementation without contract definition |

**Pre-merge checklist for every PR:**
- Scan all `.svelte` files for hardcoded hex values
- Scan for undeclared `var(--netz-*)` references against `tokens.css`
- Verify no `DataCard` is used for financial KPIs
- Verify all alert objects use discriminated unions
- Run ESLint `no-restricted-syntax` with zero warnings
