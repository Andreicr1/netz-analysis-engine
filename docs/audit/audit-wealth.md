## 1
Domain
Wealth

Principle
Chart library standard: `svelte-echarts` only for Wealth analytical charts.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:16-24` requires `svelte-echarts` and explicitly rejects Chart.js-style workarounds.
- `frontends/wealth/package.json:12-29` does not declare `svelte-echarts`.
- `packages/ui/package.json:33-39` declares `echarts`, not `svelte-echarts`.
- `packages/ui/src/lib/charts/ChartContainer.svelte:34-58` initializes charts directly with `echarts.init(...)`.
- `packages/ui/src/lib/charts/echarts-setup.ts:1-40` wires Wealth charts directly against `echarts/core`.

UI / Behavior Evidence
- Wealth dashboard, risk, portfolio, and analytics charts all render through shared `ChartContainer` / `TimeSeriesChart` / `RegimeChart` wrappers, not a `svelte-echarts` integration layer.

Gap Description
The Wealth frontend does use ECharts, but it does not use the mandated `svelte-echarts` stack. That makes the spec and the actual chart architecture diverge at the foundation layer, which is why interactions, accessibility, and synchronization behavior are being reimplemented inconsistently screen by screen.

Severity
High

Root Cause
The shared chart system standardized on direct ECharts primitives before the Wealth spec was updated, and the spec is not being enforced at package-manifest or component-boundary level.

Recommended Fix
Adopt a single Wealth-approved chart wrapper based on `svelte-echarts`, migrate shared chart primitives to that wrapper, and block new Wealth chart work from importing raw `echarts` setup directly.

## 2
Domain
Wealth

Principle
View 1 Dashboard: status before detail, act-today answer in the first 3 seconds, and complete decision-first layout.

Status
PARTIALLY COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:54-56` says the dashboard must answer “Do I need to act today?” before detail.
- `docs/ux/wealth-frontend-ux-principles.md:160-249` defines the required dashboard layout: regime banner, 3 portfolio cards, macro bar, allocation summary, drift alerts panel, and activity feed.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:146-179` renders a regime banner and three cards.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:193-198` renders the central NAV chart as `series={[]}` with `empty={true}`.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:203-211` shows a generic SSE `AlertFeed`, not the specified drift-alerts panel.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:164-177` links cards to `/model-portfolios?...` and provides no inline “History” action.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:139-141` derives “updated at” from `new Date()` on the client, not from backend freshness.
- `system-map-validation-report.md:297-303` already documents the Wealth dashboard chart as a placeholder.

UI / Behavior Evidence
- Users do get a regime banner and top-level cards, but the main analytical block is an empty placeholder.
- The page surfaces a live alert feed, not the specified drift summary sorted by severity with rebalance actioning.
- The “updated” timestamp reflects page-render time, which can imply freshness even when underlying risk data is old.

Gap Description
The page partially satisfies the overview requirement, but it does not actually deliver the specified act-today dashboard. The dominant center-of-screen component is a placeholder, the drift-alert decision surface is missing, and the freshness signal is structurally misleading.

Severity
High

Root Cause
The dashboard was assembled from available generic components instead of the Wealth-specific decision layout, and the validation report’s dashboard-placeholder contradiction has not been resolved.

Recommended Fix
Replace the placeholder chart with the specified decision blocks, add the drift-alerts panel and activity feed in the mandated order, wire portfolio cards to portfolio-detail/history actions, and source dashboard freshness from backend data timestamps instead of `new Date()`.

## 3
Domain
Wealth

Principle
Core Philosophy: language of decision, not language of computation; never expose raw regime or trigger enums.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:58-63` forbids exposing internal enums and requires decision-language phrasing.
- `docs/ux/wealth-frontend-ux-principles.md:654-656` repeats that regime must not be shown as a raw enum.
- `frontends/wealth/src/lib/components/PortfolioCard.svelte:78-80` passes raw `regime` into `StatusBadge`.
- `frontends/wealth/src/lib/components/PortfolioCard.svelte:124-127` renders `triggerStatus` directly.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:253-257` renders raw regime and trigger-derived status.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:154-156` and `frontends/wealth/src/routes/(team)/risk/+page.svelte:148-150` render the current regime through `StatusBadge`.
- `packages/ui/src/lib/components/StatusBadge.svelte:50-69` only title-cases the incoming token; it does not translate it into Wealth decision language or rationale.

UI / Behavior Evidence
- A Wealth user sees labels like `Risk Off` or raw trigger-derived states instead of explanations such as “Stress environment active” or “approaching risk limit — monitor closely.”
- The UI provides almost no signal rationale alongside those statuses.

Gap Description
The implementation exposes system-state tokens in lightly prettified form instead of decision-oriented language. That weakens explainability for portfolio managers, clients, and committees and directly violates a core Wealth principle.

Severity
High

Root Cause
Status display is delegated to a generic badge formatter that capitalizes tokens mechanically, without a Wealth-specific narrative mapping layer.

Recommended Fix
Introduce Wealth-specific display mappers for regime and trigger states, require a plain-language label plus tooltip/rationale payload, and block direct rendering of backend enum values in Wealth views.

## 4
Domain
Wealth

Principle
Core Philosophy: drift history is the audit trail and must be complete, timestamped, and exportable from the portfolio view.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:65-71` makes drift history mandatory and exportable.
- `docs/ux/wealth-frontend-ux-principles.md:338-379` specifies the slide-in panel, export controls, event table, and timeline chart.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:210-212` exposes a “Drift History” button.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:358-366` renders placeholder copy, “Export to CSV coming soon,” and an `EmptyState` instead of real history.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:183-185` only tracks panel open/close state; there is no drift-history fetch or export call.

UI / Behavior Evidence
- The user can open the panel, but the panel contains no history rows, no period filter, no CSV/PDF export, and no drift timeline chart.
- The audit-trail surface exists as a shell only.

Gap Description
This is the clearest Wealth audit-trail violation in the codebase. The entry point exists, but the actual institutional record the spec depends on is missing.

Severity
Critical

Root Cause
The portfolio-detail route implemented the panel affordance before the underlying drift-history product requirements were built, leaving a placeholder in a workflow that the spec treats as mandatory.

Recommended Fix
Implement a real drift-history datasource and panel with period filters, event table, timeline chart, rebalance rows, and separate export fetches capped at the documented `limit=500`.

## 5
Domain
Wealth

Principle
View 2 Portfolio Detail: three-column workbench with allocation navigator, full allocation table, and rebalance proposals with before/after detail.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:252-337` defines a three-column FCL layout with allocation blocks navigator, CVaR monitor tabs, full allocation table, and rebalance proposals.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:231-336` renders metric cards, one CVaR chart, and simple rebalance event cards in a single-column flow.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:281-336` shows rebalance events as compact cards only; there is no before/after allocation diff.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.server.ts:10-20` loads `portfolio`, `snapshot`, and `history`, but the page does not render the full allocation workbench described by the spec.
- `system-map-validation-report.md:47-50` and `system-map-validation-report.md:384-390` note that the Wealth `profile` route lacks matcher validation.

UI / Behavior Evidence
- The portfolio page behaves like a summary page, not the specified institutional workbench.
- Users cannot navigate allocation blocks from a left rail, inspect the full strategic/current/deviation/band/status table, or review rebalance proposals with the required operational detail.

Gap Description
The route exists, but the actual portfolio-management surface described in the Wealth UX document is largely absent. This leaves the most important Wealth screen without the comparison and audit structure the domain requires.

Severity
High

Root Cause
The page was implemented as a simplified summary around generic cards and actions rather than as a dedicated portfolio-management workspace. Route robustness is also weaker than documented because `profile` is still an unvalidated free-form param.

Recommended Fix
Rebuild the route as the specified three-column workspace, add matcher validation for `profile`, and render the full allocation detail and rebalance proposal model instead of summary cards alone.

## 6
Domain
Wealth

Principle
View 3 Fund Browser: rapid-comparison workbench with always-visible filters, sortable dense table, and inline expanded rows.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:389-437` requires a persistent filter bar, sortable dense table, and inline expanded rows.
- `frontends/wealth/src/routes/(team)/funds/+page.svelte:193-221` implements status tabs only; it has no filter bar for block, geography, asset class, score, liquidity, AUM, or regime compatibility.
- `frontends/wealth/src/routes/(team)/funds/+page.svelte:223-348` renders a raw table without sorting handlers and without the required CVaR 3m, Sharpe 1y, liquidity, or regime-compatibility columns.
- `frontends/wealth/src/routes/(team)/funds/+page.svelte:257-262` opens details via row click.
- `frontends/wealth/src/routes/(team)/funds/+page.svelte:362-367` routes the detail into `FundDetailPanel`, a side panel rather than an inline expanded row.
- `system-map-validation-report.md:356-363` calls out Wealth table implementation inconsistency as a hidden pattern.

UI / Behavior Evidence
- The screen supports status filtering, but not the rapid risk/fit comparison workflow the spec describes.
- Users must leave table context to inspect meaningful detail because expansion happens in a separate side panel instead of inline.

Gap Description
The current page is closer to an operations list than a fund-selection workbench. It does not support the high-speed comparison of risk, liquidity, compatibility, and quality signals required to populate allocation blocks.

Severity
High

Root Cause
The implementation was optimized around an existing raw-table pattern and a reusable side panel, not around the Wealth-specific comparison flow.

Recommended Fix
Add the specified filter bar and default sort, render the missing comparison columns, and replace the side-panel-only drilldown with inline row expansion that keeps adjacent fund comparisons visible.

## 7
Domain
Wealth

Principle
Operational next actions must not be placeholders or no-ops; DD-report workflows must provide meaningful execution paths and consistent live progress behavior.

Status
PARTIALLY COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:642-645` forbids generic empty states and requires actionable explanations.
- `frontends/wealth/src/lib/components/FundDetailPanel.svelte:77-149` implements DD-report live progress through an ad hoc `fetch()` stream reader.
- `frontends/wealth/src/lib/components/FundDetailPanel.svelte:342-347` shows `actionLabel="Gerar Relatório"` with `onAction={() => {}}`, a no-op action.
- `system-map-validation-report.md:256-265` documents Wealth ad hoc streaming as a contradiction to shared SSE-registry enforcement.
- `system-map-validation-report.md:373-379` explicitly calls out the Wealth fund-detail DD-report empty-state action as a no-op.

UI / Behavior Evidence
- Users can watch a DD report progress if generation is already in-flight.
- Users cannot actually initiate the DD workflow from the pending empty state, because the visible CTA does nothing.
- The live-progress path also bypasses the shared SSE registry model, so its behavior differs from the rest of the app’s documented live-data architecture.

Gap Description
This flow looks actionable but is not. That is operationally worse than a missing button because it suggests a capability that the UI does not actually deliver.

Severity
High

Root Cause
The DD-report detail panel was wired for read/progress states before the trigger action and shared streaming abstraction were finished.

Recommended Fix
Replace the no-op CTA with a real generate action and confirmation path, move DD streaming onto the shared SSE abstraction, and surface explicit success/error/retry outcomes instead of a placeholder empty state.

## 8
Domain
Wealth

Principle
View 4 Allocation Editor: strategic edits require slider-based controls, CVaR impact simulation, rationale capture, and governance-aware save behavior.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:446-500` requires band sliders, CVaR-impact simulation, rationale, approval handling, tactical signal source/validity, and effective allocation with selected funds plus effective CVaR.
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte:216-224` edits strategic weights through plain numeric inputs, not range sliders.
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte:93-111` saves strategic changes directly with a PUT once totals sum to 100%; there is no rationale, simulation, or approval queue logic.
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte:265-285` shows tactical conviction as plain text and editable numeric inputs only.
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte:296-333` omits selected funds and effective CVaR summary from the effective-allocation view.

UI / Behavior Evidence
- Strategic edits can be made without any explanation of expected risk impact or governance trail.
- Tactical positions do not expose signal source or validity horizon.
- The effective view does not show which funds actually fill each block or whether the resulting portfolio is approaching the CVaR limit.

Gap Description
The current allocation page allows editing, but it does not satisfy the domain’s decision-control or governance requirements. It is a generic weight editor, not the specified institutional allocation editor.

Severity
Critical

Root Cause
The page is wired directly to backend PUT endpoints with minimal guardrails, so the richer PM/IC workflow in the Wealth spec never materialized in the UI.

Recommended Fix
Implement slider-based strategic controls with hard stops, pre-save CVaR simulation, required rationale, role-aware approval routing, tactical rationale columns, and an effective-allocation table that includes selected funds and effective CVaR utilization.

## 9
Domain
Wealth

Principle
View 5 Risk Monitor: deep analytics screen with full CVaR timeline, synchronized regime chart, clickable detail, and 3×2 macro sparkline grid.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:510-577` specifies the full risk-monitor layout and chart behavior.
- `frontends/wealth/src/routes/(team)/risk/+page.svelte:161-185` renders utilization bars by profile, not the required full-width CVaR timeline.
- `frontends/wealth/src/routes/(team)/risk/+page.svelte:190-194` calls `<RegimeChart series={[]} regimes={regimeBands} />`, so the chart has no analytical series at all.
- `frontends/wealth/src/routes/(team)/risk/+page.svelte:235-239` renders `MacroChips`, while `frontends/wealth/src/lib/components/MacroChips.svelte:24-61` provides only four compact numeric chips and no sparklines.
- `frontends/wealth/src/routes/(team)/risk/+page.svelte:121-132` defines `loadDriftDetail(...)`, but the alert rows in `frontends/wealth/src/routes/(team)/risk/+page.svelte:206-227` do not invoke it.

UI / Behavior Evidence
- Users do not get the specified deep-investigation CVaR chart with warning bands, breach zones, rebalance markers, and synced regime context.
- Drift alerts are visible but not actually drillable.
- Macro detail is compressed into chips rather than the required 6-card sparkline evidence panel.

Gap Description
The route is named “Risk Monitor,” but it behaves like a lightweight summary page. The required analytical depth and drilldown behavior are missing.

Severity
High

Root Cause
The risk page reused simplified shared components intended for overview surfaces instead of implementing the dedicated analytical chart system described in the Wealth spec.

Recommended Fix
Build the full CVaR timeline with synchronized regime chart, wire drift rows to a real detail panel, and replace macro chips with the specified 3×2 sparkline grid and chart drilldowns.

## 10
Domain
Wealth

Principle
View 6 Backtest: decision-pack presentation and Pareto interaction must be portfolio-manager oriented, not raw quantitative tooling.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:581-627` defines a dedicated backtest view, summary row, stress-scenario analysis, breach history, and a slider-based Pareto interaction.
- `docs/ux/wealth-frontend-ux-principles.md:617-620` explicitly says never show the Pareto front as a scatter plot of raw points.
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte:432-468` renders backtest as a single button plus a generic metrics dump inside an analytics tab.
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte:150-178` builds Pareto as scatter and line series.
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte:531-534` renders that raw chart through `ChartContainer`.
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte:213-239` polls backtest results via a manual loop and timeout, not a cancellable shared poller.
- `system-map-validation-report.md:267-274` already documents the analytics/backtest polling contradiction.

UI / Behavior Evidence
- The backtest experience is hidden inside a multi-tab analytics lab instead of presented as a decision pack.
- Users do not get cumulative return, drawdown analysis, stress scenarios, or CVaR breach history.
- The Pareto surface is shown exactly in the raw scatter/efficient-frontier style the spec forbids.

Gap Description
This is a fundamental audience mismatch. The current implementation exposes raw quantitative primitives instead of the decision-support workflow the Wealth document is written around.

Severity
Critical

Root Cause
The Wealth analytics route collapsed multiple quantitative experiments into one generic screen and never converged back to the PM-facing interaction model in the spec.

Recommended Fix
Split backtest into its own route or dedicated decision-pack surface, implement the specified result sections, replace the scatter frontier with a slider metaphor, and move polling to a cancellable shared abstraction with explicit long-run messaging.

## 11
Domain
Wealth

Principle
Store architecture: shared in-memory Wealth store, correct stale model, and single multiplexed SSE connection across team views.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:724-783` requires one root-level in-memory store, SSE as primary source, 30s polling fallback, stale status, and shared multiplexed connections.
- `frontends/wealth/src/routes/(team)/+layout.svelte:15-29` creates one shared `riskStore`, but only calls `fetchAll()` and `startPolling()`.
- `frontends/wealth/src/lib/stores/risk-store.svelte.ts:105-188` implements fetches plus self-scheduling polling only; there is no SSE path in the store.
- `frontends/wealth/src/lib/stores/risk-store.svelte.ts:164-165` stamps `lastUpdated` with fetch time, not source-data time.
- `frontends/wealth/src/lib/stores/stale.ts:39-46` handles weekdays/weekends but not Brazilian holidays from the spec.
- `frontends/wealth/src/lib/stores/stale.ts:50-64` formats staleness in English relative text.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:115-129` opens its own `createSSEStream(...)` outside the shared store.
- `frontends/wealth/src/lib/components/FundDetailPanel.svelte:87-149` opens another ad hoc live stream with raw `fetch()`.
- `system-map-validation-report.md:98-123`, `system-map-validation-report.md:256-265`, and `system-map-validation-report.md:320-339` document the same Wealth streaming/polling inconsistencies as structural risks.

UI / Behavior Evidence
- Different Wealth screens use different live-data mechanisms for different pieces of the same domain.
- Freshness status can imply data is current merely because the frontend fetched recently, even if the underlying risk batch is old.

Gap Description
The store architecture is documented as a single, reliable, SSE-first Wealth data spine, but the actual app mixes polling-only stores, page-local SSE, and ad hoc streaming readers. That is both a UX consistency failure and an operational reliability risk.

Severity
Critical

Root Cause
Shared abstractions were introduced but not made authoritative, so teams kept adding page-local live-data implementations that bypass the documented Wealth state model.

Recommended Fix
Move all Wealth live risk updates into the root store, make SSE primary there, attach real source timestamps for staleness, add holiday-aware stale evaluation, and remove page-local or ad hoc streams that bypass the shared registry model.

## 12
Domain
Wealth

Principle
Accessibility requirements: charts, dense tables, and status changes must be screen-reader legible and keyboard robust.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:812-819` requires chart `aria-label`s, keyboard navigability, table cell/header associations, and `role="status"` for status badges.
- `packages/ui/src/lib/charts/ChartContainer.svelte:61-77` renders chart containers with no `aria-label` or alternative chart description.
- `frontends/wealth/src/routes/(team)/funds/+page.svelte:227-348` renders a dense raw table with plain `th`/`td` markup and no `headers` attributes on numeric cells.
- `packages/ui/src/lib/components/StatusBadge.svelte:58-69` renders a plain `span` with no `role="status"` or live-region semantics.
- `rg -n "role=|headers=|aria-label" frontends/wealth/src` only returned a small set of controls, not systematic chart/table/status coverage.

UI / Behavior Evidence
- Wealth charts have no exposed descriptive label for screen-reader users.
- Dense operational tables do not provide the richer cell/header semantics the spec requires.
- Status changes are visible but not announced as status updates.

Gap Description
The Wealth app has isolated accessibility attributes, but it does not satisfy the documented accessibility contract for the screens that matter most: charts, dense tables, and status surfaces.

Severity
Medium

Root Cause
Accessibility requirements live in the Wealth document, but the shared UI primitives used by Wealth do not encode those semantics by default.

Recommended Fix
Add required aria props to chart components, enrich Wealth tables with header associations, and update `StatusBadge` to expose `role="status"` or a live-region wrapper where status changes matter.

## 13
Domain
Wealth

Principle
Localization and formatting: one locale policy, explicit numeric formatting, and no hardcoded status/label strings outside i18n keys.

Status
NON-COMPLIANT

Code Evidence
- `docs/ux/wealth-frontend-ux-principles.md:823-830` requires `Intl.DateTimeFormat`, `Intl.NumberFormat`, explicit decimal/sign handling, and paraglide-based label localization.
- `frontends/wealth/src/lib/components/PortfolioCard.svelte:35-48` formats numbers with `Intl.NumberFormat("en-US")`.
- `frontends/wealth/src/lib/stores/stale.ts:50-64` returns English text like `just now` and uses `toLocaleDateString("en-US")`.
- `frontends/wealth/src/routes/(team)/dashboard/+page.svelte:139-141` formats timestamp text in `pt-BR`.
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:245` and `frontends/wealth/src/routes/(team)/portfolios/[profile]/+page.svelte:299` use bare `toLocaleDateString()` with no explicit locale.
- No Wealth scan results showed paraglide/i18n usage in `frontends/wealth/src`.

UI / Behavior Evidence
- The same Wealth domain mixes English and Portuguese copy, explicit and implicit locale formatting, and inconsistent date/number conventions across screens.
- Status and workflow labels remain hardcoded in templates and shared components.

Gap Description
Formatting and copy are being handled ad hoc at the component level, so the Wealth product does not present a coherent locale model. That is especially damaging on an institutional product where numeric interpretation must be consistent.

Severity
Medium

Root Cause
Formatting logic is decentralized across route components, and the i18n requirement from the Wealth spec was not integrated into the actual component model.

Recommended Fix
Centralize Wealth formatters, require explicit locale and sign-display behavior for numeric/date output, and move regime/status/signal labels behind paraglide keys instead of hardcoded strings.
