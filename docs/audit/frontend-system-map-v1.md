# Frontend System Map v1

**Scope:** 3 SvelteKit frontends + 1 shared UI package
**Date:** 2026-03-17
**Method:** Multi-agent codex review (8 specialized agents)
**Commit:** `2310254` (post-fix baseline)

---

## 1. Architecture Overview

| Attribute | Value |
|---|---|
| Framework | SvelteKit + Svelte 5 (runes syntax) |
| State management | `$state` / `$derived` / `$effect` + Svelte context |
| CSS | Tailwind CSS v4 + `--netz-*` CSS custom properties |
| Charts | ECharts 5.6 via `svelte-echarts` (canvas renderer) |
| Tables | @tanstack/svelte-table 9.0 + @tanstack/svelte-virtual 3.0 |
| Components | bits-ui 1.0 (headless primitives) |
| Auth | Clerk JWT v2 (JWKS verification, `svelte-clerk` UI) |
| Data fetching | Server: `+page.server.ts` → `NetzApiClient`. Client: SSE + polling fallback |
| SSE | `fetch()` + `ReadableStream` (NOT EventSource — auth headers) |
| Build | pnpm workspaces + Turborepo |
| Adapter | `@sveltejs/adapter-node` (all 3 apps) |
| CSP | Configured in all 3 `svelte.config.js` |

### Workspace Structure

```
packages/ui/          @netz/ui — shared design system (132 artifacts)
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

## 2. Route Inventory (51 pages)

### Credit — 19 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(team)/dashboard` | Task inbox, pipeline KPIs, macro, compliance alerts | L1 Overview |
| `(team)/copilot` | RAG chat with document retrieval (SSE streaming) | L2 Workbench |
| `(team)/funds` | Fund selector (auto-redirect if single fund) | L1 Overview |
| `(team)/funds/[fundId]/pipeline` | Deal list: kanban + list views, stage filters | L2 Workbench |
| `(team)/funds/[fundId]/pipeline/[dealId]` | Deal command center: tabs (Overview, Conditions, IC Memo, Documents, Timeline) | L2 Workbench |
| `(team)/funds/[fundId]/documents` | Document list, folder sidebar, ingestion control | L2 Workbench |
| `(team)/funds/[fundId]/documents/[documentId]` | Document metadata, version history | L2 Workbench |
| `(team)/funds/[fundId]/documents/upload` | File upload (50MB limit, magic-byte validation) | L2 Workbench |
| `(team)/funds/[fundId]/documents/reviews` | Review queue: pending/under review/approved/rejected | L2 Workbench |
| `(team)/funds/[fundId]/documents/reviews/[reviewId]` | Review detail: checklist, AI analysis, decision actions | L2 Workbench |
| `(team)/funds/[fundId]/documents/auditor` | Auditor evidence view | L3 Decision Pack |
| `(team)/funds/[fundId]/documents/dataroom` | Dataroom folder governance | L2 Workbench |
| `(team)/funds/[fundId]/portfolio` | Assets, obligations, alerts, actions (CRUD) | L2 Workbench |
| `(team)/funds/[fundId]/reporting` | NAV snapshots, report packs, investor statements | L3 Decision Pack |
| `(investor)/documents` | Investor-only approved documents | L1 Overview |
| `(investor)/report-packs` | Investor report distribution | L3 Decision Pack |
| `(investor)/statements` | Investor statements | L3 Decision Pack |
| `auth/sign-in` | Clerk login | — |
| `auth/sign-out` | Clerk logout | — |

### Wealth — 22 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(team)/dashboard` | Portfolio cards (3 profiles), NAV chart, risk alerts (SSE), macro chips | L1 Overview |
| `(team)/risk` | CVaR monitor, regime chart, drift alerts, macro detail | L2 Workbench |
| `(team)/allocation` | Strategic/Tactical/Effective tabs, edit mode with validation | L2 Workbench |
| `(team)/analytics` | 5 tabs: Correlation, Backtest, Pareto, What-If, Attribution | L2 Workbench |
| `(team)/funds` | Fund universe with status tabs, detail panel (SSE for DD reports) | L2 Workbench |
| `(team)/funds/[fundId]` | Fund detail | L2 Workbench |
| `(team)/screener` | Instrument screener: funnel sidebar, L1/L2/L3, virtualized table | L2 Workbench |
| `(team)/macro` | Regional scores, regime hierarchy, committee reviews | L2 Workbench |
| `(team)/model-portfolios` | Model portfolio list + detail sidebar, backtest, rebalance | L2 Workbench |
| `(team)/model-portfolios/[portfolioId]` | Model portfolio detail | L2 Workbench |
| `(team)/portfolios/[profile]` | Portfolio detail: allocation blocks, risk monitor, drift history | L2 Workbench |
| `(team)/instruments` | Instruments universe browser with search | L2 Workbench |
| `(team)/exposure` | Geographic + sector heatmaps | L2 Workbench |
| `(team)/content` | Content management (DD reports, flash reports, outlooks) | L2 Workbench |
| `(team)/dd-reports` | DD reports list by fund | L2 Workbench |
| `(team)/dd-reports/[fundId]` | Fund-specific DD reports | L2 Workbench |
| `(team)/dd-reports/[fundId]/[reportId]` | DD report detail: chapter sidebar + DOMPurify content | L3 Decision Pack |
| `(investor)/documents` | Published investment documents | L1 Overview |
| `(investor)/portfolios` | Model portfolios with track-record (read-only) | L1 Overview |
| `(investor)/fact-sheets` | Published fact sheets | L3 Decision Pack |
| `(investor)/reports` | Published outlooks, flash reports | L3 Decision Pack |
| `auth/sign-in` | Clerk login | — |

### Admin — 10 routes

| Path | Purpose | Narrative Level |
|---|---|---|
| `(admin)/` | Redirect to /health | — |
| `(admin)/health` | Service grid, worker status, pipeline metrics, log feed (SSE) | L2 Workbench |
| `(admin)/tenants` | Tenant list + create dialog | L1 Overview |
| `(admin)/tenants/[orgId=orgId]` | Tenant overview: edit form, metrics, seed action | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/branding` | Color pickers (8 colors) + asset upload (magic-byte validation) | L2 Workbench |
| `(admin)/tenants/[orgId=orgId]/config` | Placeholder (future) | — |
| `(admin)/tenants/[orgId=orgId]/prompts` | Placeholder (future) | — |
| `(admin)/config/[vertical=vertical]` | Global config editor: JSON + diff viewer + optimistic locking | L2 Workbench |
| `(admin)/prompts/[vertical=vertical]` | Prompt editor: Jinja2 + DOMPurify preview + version history | L2 Workbench |
| `auth/sign-in` | Clerk login (admin-only guard) | — |

---

## 3. Component System

### @netz/ui — Shared Design System (70+ artifacts)

**Primitives (via bits-ui):** Button, Card, Badge, Dialog, Sheet, Tabs, Input, Select, Textarea, Tooltip, DropdownMenu, Skeleton

**Composites:** DataTable, DataTableToolbar, DataCard, MetricCard, SectionCard, StatusBadge, EmptyState, ActionButton, ConfirmDialog, FormField, Toast, PageTabs, UtilizationBar, RegimeBanner, AlertFeed, HeatmapTable, PeriodSelector, PDFDownload, LanguageToggle, ErrorBoundary, ConnectionLost, BackendUnavailable

**Charts (ECharts 5.6):** ChartContainer, TimeSeriesChart, RegimeChart, GaugeChart, BarChart, FunnelChart, HeatmapChart, ScatterChart

**Layouts:** AppLayout (root), AppShell (CSS grid), TopNav (horizontal, 52px), ContextSidebar (detail nav, 220px), Sidebar (vertical, collapsible), ContextPanel (right slide-in), InvestorShell, PageHeader

**Utilities:** NetzApiClient (typed errors, retry, timeout), createSSEStream (heartbeat, backoff, registry-enforced 4-connection limit), createSSEWithSnapshot (subscribe-then-snapshot), createPoller (self-scheduling), formatCurrency/Percent/Compact/Date/ISIN, brandingToCSS/injectBranding, createClerkHook (JWKS), createThemeHook (SSR FOUC prevention), startSessionExpiryMonitor, SSE registry (canOpenSSE/registerSSE/unregisterSSE)

### Domain-Specific Components

| Credit (8) | Wealth (4) | Admin (7) |
|---|---|---|
| TaskInbox | PortfolioCard | ServiceHealthCard |
| PipelineFunnel | MacroChips | WorkerLogFeed |
| DealStageTimeline | FundDetailPanel | TenantCard |
| ICMemoViewer | StaleBanner | ConfigEditor |
| ICMemoStreamingChapter | | ConfigDiffViewer |
| IngestionProgress | | PromptEditor |
| CopilotChat | | BrandingEditor |
| CopilotCitation | | |

---

## 4. Data & State Mapping

### State Management Pattern

```
+layout.server.ts        → Server-side: createServerApiClient(token), Promise.allSettled()
+layout.svelte (root)    → Svelte context: getToken, riskStore, contextNav
+page.svelte             → Component-local: $state, $derived, $effect
```

| Store | Location | Scope | Mechanism |
|---|---|---|---|
| Auth token | `AppLayout` context (`netz:getToken`) | All pages | Clerk JWT, lazy accessor |
| Risk data | `(team)/+layout.svelte` context (`netz:riskStore`) | Wealth team pages | NetzApiClient + self-scheduling polling (30s) |
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

### Storage Policy

| Storage | Used For |
|---|---|
| **In-memory `$state`** | All application data (portfolios, deals, risk metrics) |
| **Svelte context** | Cross-component shared state (token, stores, nav) |
| **localStorage** | Theme preference only (`netz-theme`) — never sensitive data |
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
| Drift history | Inline panel (ContextPanel) | `/analytics/strategy-drift/{id}` |
| Prompt version history | Lazy-loaded panel in PromptEditor | `/prompts/{vertical}/{name}/versions` |
| Worker logs | `WorkerLogFeed.svelte` (SSE, 1000-line ring buffer) | `/admin/health/workers/logs` (SSE) |
| Activity feed (dashboard) | Wealth dashboard bottom section | Risk SSE events (capped 50) |

---

## 6. Security Posture

| Control | Status |
|---|---|
| CSP | Configured (all 3 frontends) |
| XSS — `{@html}` | DOMPurify on all 2 usages (PromptEditor, DD report) |
| Auth | Clerk JWKS verification via `createClerkHook` |
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
| Brand | `primary`, `secondary`, `accent`, `light`, `highlight` |
| Surface | `surface`, `surface-alt`, `surface-elevated`, `surface-inset` |
| Text | `text-primary`, `text-secondary`, `text-muted` |
| Border | `border` |
| Semantic | `success` (#10b981), `warning` (#f59e0b), `danger` (#ef4444), `info` (#3b82f6) |
| Charts | `chart-1` through `chart-5` |
| Spacing | `space-1` (4px) through `space-16` (64px) |
| Shadows | `shadow-1` through `shadow-5` |
| Duration | `fast` (150ms), `normal` (250ms), `slow` (350ms) |
| Fonts | `font-sans` (Inter), `font-mono` (JetBrains Mono) |

### Dark Mode

Supported via `[data-theme="dark"]` on `<html>`. Theme persisted in cookie (`netz-theme`). SSR injection via `createThemeHook` prevents FOUC.

### Tailwind Integration

All tokens mapped via `@theme` block in each frontend's `app.css`:
```css
@theme {
  --color-netz-navy: var(--netz-navy);
  --font-sans: var(--netz-font-sans), "Inter Variable", system-ui, sans-serif;
}
```
`@source` directive includes `packages/ui/src/**/*.{svelte,ts}` for class scanning.

---

## 8. Build & Performance

### Turborepo Pipeline

```
build    → depends on ^build (topological: @netz/ui first)
dev      → persistent, uncached (parallel via make dev:all)
check    → depends on ^build
types    → openapi-typescript from running backend
```

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
├── bits-ui 1.0         (headless components)
├── echarts 5.6         (charts — canvas renderer)
├── jose 5.0            (JWT verification)
├── clsx 2.1            (class merging)
├── tailwind-merge      (Tailwind class dedup)
├── @tanstack/svelte-table 9.0    (data tables)
└── @tanstack/svelte-virtual 3.0  (row virtualization)
```

### Frontend Dependencies (beyond @netz/ui)

| Dep | Credit | Wealth | Admin |
|---|---|---|---|
| dompurify | — | yes | yes |
| @tanstack/svelte-virtual | — | yes | — |
| @fontsource-variable/inter | yes | yes | yes |
| @tailwindcss/vite | yes | yes | yes |

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

### Remaining Pending Todos (pre-existing, not from this review)

See `todos/*-pending-*.md` for 24 additional findings from prior backend/frontend reviews spanning security, performance, architecture, and data integrity.

---

*Generated by multi-agent codex review: 4 Explore agents + security-sentinel + architecture-strategist + performance-oracle + pattern-recognition-specialist*
