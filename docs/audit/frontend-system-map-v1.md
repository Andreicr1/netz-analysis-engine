# Frontend System Map v1

**Scope:** 3 SvelteKit frontends + 1 shared UI package
**Date:** 2026-03-19
**Method:** Multi-agent codex review (8 specialized agents) + incremental audit
**Commit:** `0be67dd` (post-fix baseline — 0 svelte-check errors)

---

## 1. Architecture Overview

| Attribute | Value |
|---|---|
| Framework | SvelteKit + Svelte 5.53 (runes syntax) |
| State management | `$state` / `$derived` / `$effect` + Svelte context |
| CSS | Tailwind CSS v4 + `--netz-*` CSS custom properties |
| Charts | ECharts 5.6 via `svelte-echarts` (canvas renderer) |
| Tables | @tanstack/svelte-table 9.0 + @tanstack/svelte-virtual 3.0 |
| Components | bits-ui 1.8.0 (headless primitives) |
| Auth | Clerk JWT v2 (JWKS verification, `svelte-clerk` UI) |
| Data fetching | Server: `+page.server.ts` → `NetzApiClient`. Client: SSE + polling fallback |
| SSE | `fetch()` + `ReadableStream` (NOT EventSource — auth headers) |
| Build | pnpm workspaces + Turborepo |
| Adapter | `@sveltejs/adapter-node` (all 3 apps) |
| CSP | Configured in all 3 `svelte.config.js` |
| Type health | **0 errors** across all 4 packages (svelte-check clean) |

### Workspace Structure

```
packages/ui/          @netz/ui — shared design system (57 artifacts)
frontends/credit/     netz-credit-intelligence  :5173
frontends/wealth/     netz-wealth-os            :5174
frontends/admin/      netz-admin                :5175
```

### Cross-Import Policy

Frontends **never** cross-import. Shared code flows exclusively through `@netz/ui`:

```
  credit ──→ @netz/ui ←── wealth
                ↑
              admin
```

Zero violations detected. Enforced by convention (no import-linter for frontend yet).

---

## 2. Route Inventory (55 pages)

### Credit — 19 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(team)/dashboard` | Task inbox, pipeline KPIs, FRED explorer, macro, compliance alerts | L1 Overview |
| `(team)/copilot` | RAG chat with document retrieval (SSE streaming, multiline input) | L2 Workbench |
| `(team)/funds` | Fund selector (auto-redirect if single fund) | L1 Overview |
| `(team)/funds/[fundId]/pipeline` | Deal list: kanban + list views (toggle with aria), stage filters | L2 Workbench |
| `(team)/funds/[fundId]/pipeline/[dealId]` | Deal command center: tabs (Overview, Conditions, IC Memo, Documents, Timeline, Cashflow) | L2 Workbench |
| `(team)/funds/[fundId]/documents` | Document list, folder sidebar, ingestion control | L2 Workbench |
| `(team)/funds/[fundId]/documents/[documentId]` | Document metadata (humanized keys), version history | L2 Workbench |
| `(team)/funds/[fundId]/documents/upload` | File upload (50MB limit, magic-byte validation) | L2 Workbench |
| `(team)/funds/[fundId]/documents/reviews` | Review queue: pending/under review/approved/rejected (humanized status) | L2 Workbench |
| `(team)/funds/[fundId]/documents/reviews/[reviewId]` | Review detail: checklist, AI analysis, decision actions | L2 Workbench |
| `(team)/funds/[fundId]/documents/auditor` | Auditor evidence view | L3 Decision Pack |
| `(team)/funds/[fundId]/documents/dataroom` | Dataroom folder governance (SectionCard wrapper) | L2 Workbench |
| `(team)/funds/[fundId]/portfolio` | Assets, obligations, alerts, actions (CRUD) | L2 Workbench |
| `(team)/funds/[fundId]/reporting` | NAV snapshots, report packs, investor statements | L3 Decision Pack |
| `(investor)/documents` | Investor-only approved documents | L1 Overview |
| `(investor)/report-packs` | Investor report distribution | L3 Decision Pack |
| `(investor)/statements` | Investor statements | L3 Decision Pack |
| `auth/sign-in` | Clerk login | — |
| `auth/sign-out` | Clerk logout | — |

### Wealth — 24 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(team)/dashboard` | Portfolio cards (3 profiles), NAV chart, risk alerts (SSE), macro chips | L1 Overview |
| `(team)/risk` | CVaR monitor, regime chart, drift alerts, macro detail | L2 Workbench |
| `(team)/allocation` | Strategic/Tactical/Effective tabs, edit mode with validation | L2 Workbench |
| `(team)/analytics` | 5 tabs: Correlation, Backtest, Pareto, What-If, Attribution | L2 Workbench |
| `(team)/funds` | Fund universe with status tabs, detail panel (SSE for DD reports) | L2 Workbench |
| `(team)/funds/[fundId]` | Fund detail with risk metrics | L2 Workbench |
| `(team)/screener` | Instrument screener: funnel sidebar, L1/L2/L3, virtualized table | L2 Workbench |
| `(team)/backtest` | Portfolio backtesting with Pareto optimization | L2 Workbench |
| `(team)/macro` | Regional scores, regime hierarchy, committee reviews | L2 Workbench |
| `(team)/model-portfolios` | Model portfolio list + detail sidebar, backtest, rebalance | L2 Workbench |
| `(team)/model-portfolios/[portfolioId]` | Model portfolio detail | L2 Workbench |
| `(team)/portfolios/[profile]` | Portfolio detail: allocation blocks, risk monitor, drift history | L2 Workbench |
| `(team)/instruments` | Instruments universe browser with search | L2 Workbench |
| `(team)/exposure` | Geographic + sector heatmaps | L2 Workbench |
| `(team)/content` | Content management (DD reports, flash reports, outlooks) | L2 Workbench |
| `(team)/dd-reports` | DD reports list by fund | L2 Workbench |
| `(team)/dd-reports/[fundId]` | Fund-specific DD reports | L2 Workbench |
| `(team)/dd-reports/[fundId]/[reportId]` | DD report detail: chapter sidebar (cn() utility) + DOMPurify content | L3 Decision Pack |
| `(investor)/documents` | Published investment documents | L1 Overview |
| `(investor)/portfolios` | Model portfolios with track-record (read-only) | L1 Overview |
| `(investor)/fact-sheets` | Published fact sheets | L3 Decision Pack |
| `(investor)/reports` | Published outlooks, flash reports | L3 Decision Pack |
| `auth/sign-in` | Clerk login | — |
| `auth/sign-out` | Clerk logout | — |

### Admin — 12 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(admin)/` | Redirect to /health | — |
| `(admin)/health` | Service grid, worker status, pipeline metrics, log feed (SSE) | L2 Workbench |
| `(admin)/tenants` | Tenant list + create dialog | L1 Overview |
| `(admin)/tenants/[orgId=orgId]` | Tenant overview: edit form, metrics, seed action | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/setup` | Tenant setup | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/health` | Tenant health metrics | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/config` | Tenant config | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/prompts` | Tenant prompts | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/branding` | Color pickers (8 colors) + asset upload (magic-byte validation) | L2 Workbench |
| `(admin)/config/[vertical=vertical]` | Global config editor: JSON + diff viewer + optimistic locking | L2 Workbench |
| `(admin)/prompts/[vertical=vertical]` | Prompt editor: Jinja2 + DOMPurify preview + version history | L2 Workbench |
| `auth/sign-in` | Clerk login (admin-only guard) | — |

---

## 3. Component System

### @netz/ui — Shared Design System (57 artifacts)

**Primitives (via bits-ui 1.8.0):** Button (with `href` link mode), Card (with rest props), Badge, Dialog (with `title`), Sheet, Tabs, Input (string | number), Select, Textarea ($bindable), Tooltip, DropdownMenu, Skeleton

**Composites:** DataTable (with `onRowClick`, cursor-pointer), DataTableToolbar, DataCard, MetricCard, SectionCard, StatusBadge, EmptyState (title + message/description), ActionButton, ConfirmDialog, ConsequenceDialog, FormField, Toast, PageTabs (controlled + uncontrolled, `id`/`value` alias), UtilizationBar, RegimeBanner, AlertFeed, AlertBanner, AuditTrailPanel, EntityContextHeader, HeatmapTable, PeriodSelector, PDFDownload, LanguageToggle, LongRunningAction, ThemeToggle, ErrorBoundary, ConnectionLost, BackendUnavailable

**Charts (ECharts 5.6 — 8 components):** ChartContainer, TimeSeriesChart, RegimeChart, GaugeChart, BarChart, FunnelChart, HeatmapChart, ScatterChart

**Layouts (8):** AppLayout (root), AppShell (CSS grid), TopNav (horizontal, 52px), ContextSidebar (detail nav, 220px), Sidebar (vertical, collapsible, token-based radius), ContextPanel (right slide-in), InvestorShell, PageHeader (token-based font-size)

**Utilities:** NetzApiClient (typed errors, retry, timeout), createSSEStream (heartbeat, backoff, registry-enforced 4-connection limit), createSSEWithSnapshot (subscribe-then-snapshot), createPoller (self-scheduling), formatCurrency/Percent/Compact/Date/ISIN, brandingToCSS/injectBranding, createClerkHook (JWKS, proper `Handle` typing), createThemeHook (SSR FOUC prevention), startSessionExpiryMonitor, SSE registry (canOpenSSE/registerSSE/unregisterSSE), cn (clsx + tailwind-merge), ContextNav type

### Domain-Specific Components

| Credit (11) | Wealth (5) | Admin (10) |
|---|---|---|
| TaskInbox | PortfolioCard | ServiceHealthCard |
| PipelineFunnel | MacroChips | WorkerLogFeed |
| PipelineKanban | FundDetailPanel | TenantCard |
| DealStageTimeline | StaleBanner | ConfigEditor |
| DealPerformancePanel | DriftHistoryPanel | ConfigDiffView |
| ICMemoViewer | | ConfigDiffViewer |
| ICMemoStreamingChapter | | PromptEditor |
| IngestionProgress | | JinjaEditor |
| CopilotChat | | BrandingEditor |
| CopilotCitation | | CodeEditor |
| CashflowLedger | | |

---

## 4. Data & State Mapping

### State Management Pattern

```
+layout.server.ts        → Server-side: createServerApiClient(token), Promise.allSettled()
+layout.svelte (root)    → Svelte context: getToken, riskStore, contextNav
+page.svelte             → Component-local: $state, $derived.by, $effect
```

| Store | Location | Scope | Mechanism |
|---|---|---|---|
| Auth token | `AppLayout` context (`netz:getToken`) | All pages | Clerk JWT, lazy accessor |
| Risk data | `(team)/+layout.svelte` context (`netz:riskStore`) | Wealth team pages | NetzApiClient + self-scheduling polling (30s), SSE-primary with monotonic version counter |
| Context nav | `context-nav.svelte.ts` context | Credit + Admin detail pages | $state via setContext/getContext |
| Stale detection | `stale.ts` utility | Wealth | Business hours aware (São Paulo TZ) |

### Data Fetching Patterns

| Pattern | Where | Mechanism |
|---|---|---|
| Server-side load | All `+page.server.ts` | `createServerApiClient(token)` → `Promise.allSettled()` |
| Client-side REST | Mutations, lazy loads | `createClientApiClient(getToken)` → `api.get/post/put/patch/delete` |
| SSE streaming | IC memo, ingestion, risk alerts, worker logs, DD reports | `createSSEStream` (registry-enforced, max 4/tab) |
| SSE + snapshot | (Available, not yet used) | `createSSEWithSnapshot` — subscribe-then-snapshot pattern |
| Polling | Risk store (wealth) | Self-scheduling `setTimeout` via `schedulePoll()` |
| Backtest polling | Analytics page | `createPoller` (5s interval, 60s max) |
| SvelteKit invalidation | Screener batch actions | `invalidateAll()` (replaced `window.location.reload()`) |

### Storage Policy

| Storage | Used For |
|---|---|
| **In-memory `$state`** | All application data (portfolios, deals, risk metrics) |
| **Svelte context** | Cross-component shared state (token, stores, nav) |
| **localStorage** | Theme preference (`netz-theme`), investor language (`netz-investor-language`) — never sensitive data |
| **sessionStorage** | Not used |
| **Cookies** | `__session` (Clerk JWT fallback), `netz-theme` |

---

## 5. UX-Critical Mechanisms

### Actions & Mutations

| Domain | Action | Pattern | Confirmation |
|---|---|---|---|
| Credit | IC decision (approve/reject/convert) | PATCH `/deals/{id}/decision` + mandatory rationale | ConfirmDialog (deal convert requires typing name) |
| Credit | Generate IC Memo | POST → SSE stream chapters | Explicit trigger only (never auto) |
| Credit | Document review decide | POST `/reviews/{id}/decide` | ConfirmDialog for reject |
| Credit | Resolve IC condition | PATCH `/ic-memo/conditions` | ConfirmDialog |
| Credit | Upload document | SAS URL → Azure Blob (50MB limit, magic-byte validation) | — |
| Credit | Move deal stage (Kanban) | PATCH `/pipeline/deals/{id}/stage` + rationale | ConsequenceDialog |
| Wealth | Edit strategic allocation | PUT `/allocation/{profile}/strategic` | Sum-to-100% validation |
| Wealth | Trigger rebalance | POST `/model-portfolios/{id}/rebalance` | ConfirmDialog |
| Wealth | Run drift scan | POST `/analytics/strategy-drift/scan` | ConfirmDialog |
| Wealth | Approve/reject macro review | PATCH `/macro/reviews/{id}/approve\|reject` | ConfirmDialog for reject |
| Wealth | Run Pareto optimization | POST `/analytics/optimize/pareto` (180s timeout) | Duplicate prevention |
| Admin | Save config override | PUT with `If-Match` header (optimistic locking) | 409 conflict handling |
| Admin | Update global default | PUT `/configs/defaults/{vertical}/{type}` | ConfirmDialog ("affects ALL tenants") |
| Admin | Seed tenant | POST `/tenants/{id}/seed` | ConfirmDialog |
| Admin | Delete branding asset | DELETE | ConfirmDialog (destructive variant) |
| Admin | Save/revert prompt | PUT/POST (creates new version, immutable history) | ConfirmDialog for revert |

### Audit Trails

| System | Mechanism |
|---|---|
| IC decisions | Server-side audit log: timestamp, user, rationale (immutable) |
| Document reviews | Full trail: reviewer, date, rationale, checklist changes |
| Config changes | Version history via `If-Match` / ETag, before/after diff |
| Prompt versions | Immutable version chain (filesystem → global → org cascade) |
| Drift history | Timestamped events: entered OUT, returned to band, rebalance |
| Regime changes | Timestamped with signal sources |

### Timeline/History Implementations

| View | Component | Data Source |
|---|---|---|
| Deal stage timeline | `DealStageTimeline.svelte` | `/deals/{id}/stage-timeline` |
| Drift history | `DriftHistoryPanel.svelte` (ContextPanel) | `/analytics/strategy-drift/{id}` |
| Prompt version history | Lazy-loaded panel in PromptEditor | `/prompts/{vertical}/{name}/versions` |
| Worker logs | `WorkerLogFeed.svelte` (SSE, 1000-line ring buffer) | `/admin/health/workers/logs` (SSE) |
| Activity feed (dashboard) | Wealth dashboard bottom section | Risk SSE events (capped 50) |

---

## 6. Security Posture

| Control | Status |
|---|---|
| CSP | Configured (all 3 frontends) |
| XSS — `{@html}` | DOMPurify on all 2 usages (PromptEditor, DD report) |
| Auth | Clerk JWKS verification via `createClerkHook` (proper `Handle` typing) |
| Admin guard | `ADMIN_ROLES` set (super_admin, admin, org:admin) |
| Route param validation | SvelteKit matchers: `[vertical=vertical]`, `[orgId=orgId]` |
| File upload | 50MB limit + magic-byte validation (credit docs, admin branding) |
| SSE auth | Bearer token via fetch headers (not EventSource) |
| SSE limits | Registry enforced: max 4 connections/tab |
| Optimistic locking | `If-Match` header on config saves (409 conflict handling) |
| Branding sanitization | CSS value validation (blocks `url()`, `expression()`, `@import`) |
| Session monitoring | `startSessionExpiryMonitor` (5min warning before JWT expiry) |
| Dev bypass | `X-DEV-ACTOR` header gated by `import.meta.env.DEV` only |

---

## 7. Token & Theme System

### CSS Custom Properties (`--netz-*`)

| Category | Tokens |
|---|---|
| Brand | `primary` (#18324d), `secondary` (#3e628d), `accent` (#c58757), `light`, `highlight` |
| Surface | `surface` (#f4f7fb), `surface-alt` (#edf2f7), `surface-elevated` (#e6edf6), `surface-inset` |
| Text | `text-primary` (#122033), `text-secondary` (#48586b), `text-muted` (#6f7f93) |
| Border | `border` (#c5d0de) |
| Semantic | `success` (#10b981), `warning` (#f59e0b), `danger` (#ef4444), `info` (#3b82f6) |
| Charts | `chart-1` through `chart-5` |
| Spacing | `space-1` (4px) through `space-16` (64px) |
| Shadows | `shadow-1` through `shadow-5` (token-based, `shadow-(--netz-shadow-1)`) |
| Radius | `radius-sm` (6px), `radius-md`, `radius-lg` |
| Typography | `text-h2` (clamp-based responsive) |
| Duration | `fast` (150ms), `normal` (250ms), `slow` (350ms) |
| Fonts | `font-sans` (Inter), `font-mono` (JetBrains Mono) |

### Dark Mode

Supported via `[data-theme="dark"]` on `<html>`. Theme persisted in cookie (`netz-theme`) + localStorage. SSR injection via `createThemeHook` prevents FOUC.

### Tailwind Integration

All tokens mapped via `@theme` block in each frontend's `app.css`:
```css
@theme {
  --color-netz-navy: var(--netz-navy);
  --font-sans: var(--netz-font-sans), "Inter Variable", system-ui, sans-serif;
}
```
`@source` directive includes `packages/ui/src/**/*.{svelte,ts}` for class scanning. Tailwind config fallback hex values synced with `tokens.css` `:root` definitions.

---

## 8. Build & Performance

### Turborepo Pipeline

```
build    → depends on ^build (topological: @netz/ui first)
dev      → persistent, uncached (parallel via make dev-all)
check    → depends on ^build
types    → openapi-typescript from running backend
```

### TypeScript Configuration

| Setting | Value | Notes |
|---|---|---|
| `strict` | `true` | All frontends |
| `moduleResolution` | `bundler` | Vite-compatible |
| `noUncheckedIndexedAccess` | `true` | Safe array/record access |
| `verbatimModuleSyntax` | `true` | Explicit type imports |
| `skipLibCheck` | `true` | Suppresses echarts/svelte-dnd-action `.d.ts` issues |

### Bundle Optimization

| Technique | Status |
|---|---|
| Manual chunks (ECharts, TanStack Table) | Configured (credit, wealth) |
| ECharts modular imports | 6 chart types + 9 components + CanvasRenderer |
| Table virtualization | Screener page (@tanstack/svelte-virtual) |
| SSR data loading | All pages (eliminates client-side waterfall) |
| Polling self-scheduling | Risk store (prevents overlap, supports abort) |
| Ring buffer (logs) | WorkerLogFeed (1000 lines, single-assignment) |
| Event buffer cap | SSE client (200 events max) |

### Dev Server Ports

| App | Port |
|---|---|
| Credit | 5173 |
| Wealth | 5174 |
| Admin | 5175 |

---

## 9. Dependency Graph

### @netz/ui Dependencies

```
@netz/ui
├── bits-ui 1.8.0       (headless components, aliased imports: BitsDialog, BitsTooltip, BitsDropdownMenu)
├── echarts 5.6          (charts — canvas renderer)
├── jose 5.0             (JWT verification)
├── clsx 2.1             (class merging)
├── tailwind-merge       (Tailwind class dedup)
├── @tanstack/svelte-table 9.0    (data tables)
└── @tanstack/svelte-virtual 3.0  (row virtualization)
```

### Frontend Dependencies (beyond @netz/ui)

| Dep | Credit | Wealth | Admin |
|---|---|---|---|
| dompurify | — | yes | yes |
| @tanstack/svelte-table | yes (direct) | yes (via @netz/ui) | — |
| @tanstack/svelte-virtual | — | yes | — |
| svelte-dnd-action | yes (Kanban) | — | — |
| @codemirror/* | — | — | yes |
| @fontsource-variable/inter | yes | yes | yes |
| @tailwindcss/vite | yes | yes | yes |

### Workspace Root

```
devDependencies:
  csstype ^3.2.3          (peer dep for bits-ui/svelte-toolbelt)
  openapi-typescript ^7.0  (API type generation)
  turbo ^2.0              (monorepo orchestration)
```

---

## 10. Known Gaps & Future Work

### Not Yet Implemented

| Gap | Notes |
|---|---|
| OpenAPI type generation | `make types` scaffolded but empty — all types hand-written |
| Wealth ContextSidebar for fund detail | Credit + Admin have it; wealth fund pages lack entity-scoped nav |
| `state/` vs `stores/` naming | Credit uses `state/`, wealth uses `stores/` — cosmetic inconsistency |
| `$state.raw()` in credit | Wealth uses it for large datasets; credit does not (acceptable) |
| Investor layout dedup | Credit and wealth investor layouts are identical (by design — no cross-import) |

### Resolved (since v1 baseline 2026-03-17)

| Item | Resolution |
|---|---|
| 2,576 svelte-check errors | Fixed: csstype peer dep, @netz/ui component props, bits-ui re-export aliases, Handle typing, skipLibCheck for library issues |
| PageTabs lacked `id` support | TabDef now accepts `id` or `value` (alias), controlled + uncontrolled modes |
| DataTable too strict generics | RowData relaxed, `onRowClick` prop added |
| Button lacked `href` | Renders `<a>` when `href` provided |
| Dialog lacked `title` | Optional `title` prop renders heading |
| Textarea not bindable | `$bindable()` added for `value` prop |
| hooks.server.ts manual typing | Proper SvelteKit `Handle` type via `createClerkHook` |
| bits-ui re-export naming conflicts | Aliased: `BitsDialog`, `BitsTooltip`, `BitsDropdownMenu` |
| Tailwind fallback colors stale | Synced with `tokens.css` `:root` values |
| 26 UX minor issues | Keyboard nav, aria labels, transitions, humanized enums/keys, dead code removal, localStorage persistence |

---

*Generated by multi-agent codex review: 4 Explore agents + security-sentinel + architecture-strategist + performance-oracle + pattern-recognition-specialist. Updated 2026-03-19 with type system cleanup and UX remediation.*
