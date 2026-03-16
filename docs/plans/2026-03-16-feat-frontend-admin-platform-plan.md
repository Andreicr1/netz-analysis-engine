---
title: "feat: Frontend + Admin Platform — Three SvelteKit Frontends + Design System"
type: feat
status: active
date: 2026-03-16
deepened: 2026-03-16
origin: docs/brainstorms/2026-03-16-feat-frontend-admin-platform-brainstorm.md
---

# Frontend + Admin Platform — Three SvelteKit Frontends + Design System

## Enhancement Summary

**Deepened on:** 2026-03-16
**Research agents used:** 10 (SvelteKit+adapter-node, shadcn-svelte+TanStack, Clerk auth, pg_notify+branding, security sentinel, architecture strategist, performance oracle, pattern recognition, SSE patterns, Monaco/CodeMirror)

### Key Improvements from Research

1. **Phase ordering fix:** Move branding route (`GET /api/v1/branding`) to Phase A.5 — Phase B's `+layout.server.ts` depends on it but it was deferred to Phase E. Without this, Phases B and C cannot use tenant branding.
2. **Security: Reject SVG uploads entirely** — SVG files can contain JavaScript (XSS). Accept only PNG/JPEG/ICO for tenant logos. Add CSP headers on asset-serving endpoint. Use `org_slug` instead of `org_id` in asset URLs to prevent tenant enumeration.
3. **Security: Harden prompt sandbox** — `AdminSandboxedEnvironment` with dunder access blocking, filter whitelist, and render timeout. Validate template content for dangerous patterns before saving.
4. **Performance: SvelteKit branding cache** — add 30s in-process TTL cache in the SvelteKit server. Eliminates 99% of branding API calls (300/min → 2/min per org at 100 users).
5. **Performance: ECharts modular imports** — use `echarts/core` + individual components. Reduces bundle from ~1MB to ~300KB. Dynamic imports for chart wrappers (zero cost on non-chart pages).
6. **Performance: Server-side pagination for fund universe** — 500+ funds should use server-side pagination (50/page default) with opt-in "load all" for power users.
7. **Clerk auth: Use `svelte-clerk`** (not deprecated `clerk-sveltekit`). `withClerkHandler` in hooks.server.ts. `invalidateAll()` required after org switch.
8. **Architecture: Add Turborepo** for cross-package build orchestration with caching. Parallel frontend builds in CI (~60% faster).
9. **Pattern: Extract scaffold to @netz/ui** — `createClerkHook()`, `createRootLayoutLoader()`, `RootLayout.svelte` eliminate ~18 near-identical files across 3 frontends.
10. **Pattern: Add Toast/Notification component** — missing from @netz/ui for non-fatal API errors (422 validation, 409 optimistic lock conflict).
11. **SSE: Subscribe-then-snapshot ordering** — connect SSE first, then call REST, then merge. Eliminates the gap where events can be lost between REST snapshot and SSE subscription.
12. **CORS configuration** — three SvelteKit frontends on different origins need explicit CORS on FastAPI backend.
13. **Branding injection via `transformPageChunk`** — inject CSS vars on `<html>` element during SSR in `hooks.server.ts`, not per-route in `+layout.server.ts`.
14. **pg_notify: dedicated asyncpg connection** — LISTEN requires a standalone connection (not from pool). Pool connections drop listeners on release.

### Critical Anti-Patterns to Avoid (from research)

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| SVG upload without sanitization | XSS on any visitor to tenant login page | Reject SVG entirely; accept PNG/JPEG/ICO only |
| `org_id` in unauthenticated asset URL | Tenant enumeration via UUID brute-force | Use `org_slug`; return default asset for unknown slugs |
| Jinja2 `SandboxedEnvironment` without dunder blocking | SSTI bypass via `__class__.__mro__` traversal | `AdminSandboxedEnvironment` with `is_safe_attribute` override |
| Branding fetch on every SSR request (no cache) | 300+ API calls/min at 100 users | 30s in-process TTL cache in SvelteKit server |
| `import * as echarts from 'echarts'` | 1MB+ bundle on every page with charts | Modular `echarts/core` + individual chart/component registration |
| Loading 500+ fund rows client-side | 375KB+ inline JSON in SSR page data | Server-side pagination (50/page) with opt-in "load all" |
| REST snapshot → then SSE subscribe | Events lost during gap between calls | Subscribe SSE first → then REST snapshot → merge |
| pg_notify LISTEN on pooled connection | Listener silently dropped when connection returns to pool | Dedicated `asyncpg.connect()` outside the pool |
| `clerk-sveltekit` package | Deprecated, Svelte 4 only | Use `svelte-clerk` (wobsoriano) — Svelte 5 compatible |
| Org switch without `invalidateAll()` | Server load functions use stale org context | Always call `invalidateAll()` after `setActive()` |
| Duplicate scaffold across 3 frontends | 18+ near-identical files to maintain | Extract `createClerkHook()` + `RootLayout.svelte` to @netz/ui |
| Multiple 401s trigger multiple redirects | Race condition: 5 parallel fetches → 5 `goto('/auth/sign-in')` calls | Single-flight boolean gate in `api-client.ts` |
| Silent session expiry during long ops | IC memo (~3min) or DD report (~3min) silently interrupted | Decode JWT `exp`, warn user 5min before expiry |
| 409 on approve/config write with no feedback | User retries, gets confused by stale data | Show "Updated by another user" toast + auto-refresh |

### New Considerations Discovered

- **CORS must be configured** on FastAPI backend for all 3 frontend origins
- **CSP headers** needed in SvelteKit hooks (`script-src 'self'`, `connect-src` for API origin)
- **Content retraction flow** missing — add `unpublish` endpoints (`published → approved`)
- **Config write validation** needs JSON Schema per config_type stored in `guardrails` column
- **Prompt snapshot at job start** prevents mid-generation inconsistency
- **Font self-hosting** — use `@fontsource/inter` (variable font, ~300KB woff2) with `font-display: swap`
- **SSE multiplexing** deferred to post-launch but needed before admin health dashboard
- **Session expiry warning** — JWT `exp` decode + 5min pre-expiry modal. Critical for IC memo/DD report generation (~3min ops)
- **Single-flight 401 redirect** — boolean gate in `api-client.ts` prevents concurrent redirect storms
- **409 conflict UX** — toast + auto-refresh on optimistic lock conflicts (approve/reject, config writes)

---

## Overview

Build three SvelteKit frontends (Credit Intelligence, Wealth OS, Admin Panel) sharing a common design system (`@netz/ui`) with tenant-customizable branding, plus the admin backend APIs that power configuration management, prompt editing, tenant CRUD, and system health monitoring. The backend is mature (~95 endpoints, 416 tests) — this plan focuses entirely on the frontend layer and the admin API gaps.

**Origin brainstorm:** [docs/brainstorms/2026-03-16-feat-frontend-admin-platform-brainstorm.md](../brainstorms/2026-03-16-feat-frontend-admin-platform-brainstorm.md) — all architectural decisions, tech stack choices, component inventory, and phasing were established there.

## Problem Statement

The Netz Analysis Engine backend is production-ready with 95 endpoints across credit and wealth verticals, 416 tests, full auth/RLS, and mature AI/quant engines. But all three frontend directories (`frontends/credit/`, `frontends/wealth/`, `packages/ui/`) are **completely empty**. There is no UI for investors, team members, or administrators to interact with the system. Additionally, the ConfigService is read-only — no admin can configure tenants, branding, prompts, or report styles without modifying code.

## Proposed Solution

Six sequential implementation phases building the complete frontend platform:

```
Phase A  → @netz/ui shared design system
Phase B  → Credit team frontend (all ~60 credit endpoints)
Phase B+ → Credit investor portal
Phase C  → Wealth team frontend (all ~58 wealth endpoints)
Phase C+ → Wealth investor portal (highest priority client-facing)
Phase E  → Admin backend APIs (config write, tenant CRUD, prompts, assets, health)
Phase F  → Admin frontend (cross-vertical dashboard)
```

## Technical Approach

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   pnpm workspace                        │
│                                                         │
│  packages/ui/          → @netz/ui (design system)       │
│  frontends/credit/     → netz-credit-intelligence       │
│  frontends/wealth/     → netz-wealth-os                 │
│  frontends/admin/      → netz-admin                     │
│                                                         │
│  All → adapter-node (SSR) → Azure Container Apps        │
│  All → Clerk JWT auth (stateless, horizontal scaling)   │
│  All → @netz/ui via workspace:* dependency              │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│           backend (FastAPI, existing)                    │
│                                                         │
│  /api/v1/funds/...     → credit endpoints (~60)         │
│  /api/v1/...           → wealth endpoints (~58)         │
│  /api/v1/admin/...     → admin endpoints (NEW, Phase E) │
│  /api/v1/branding      → tenant branding (NEW, Phase E) │
│  /api/v1/assets/...    → tenant assets (NEW, Phase E)   │
└─────────────────────────────────────────────────────────┘
```

### SpecFlow Gap Resolutions

The following gaps were identified during SpecFlow analysis and are resolved in this plan:

| Gap | Resolution | Phase |
|---|---|---|
| SvelteKit branding cache | `+layout.server.ts` calls `GET /api/v1/branding` on every SSR request. Backend ConfigService TTL (60s) handles caching. No SvelteKit-side cache — requests are cheap (JSONB from memory cache). | A, E |
| SSE replay (`Last-Event-ID`) | **Explicitly not supported.** Redis pub/sub is fire-and-forget. REST recovery endpoint is the sole mechanism for catching up. Remove `Last-Event-ID` from SSE client spec. Simplify. | A |
| Missing `publish` endpoint | Some routes have it (content, fact-sheets), some don't. Audit all routes in Phase E. Investor portal filters on `status IN ('approved', 'published')`. | E |
| Fund-level access control | Derived from `organization_id`. All funds within an org are accessible to all org members. `Actor.fund_ids` remains empty (future: per-fund restriction). `+layout.server.ts` validates fund belongs to org, not per-user fund access. | B |
| Config write guardrails | JSON Schema validation per `config_type` stored in `VerticalConfigDefault.guardrails` JSONB column (already exists). Admin write endpoint validates override against guardrails before saving. Shared validation in admin frontend (client-side preview). | E |
| Prompt snapshot at job start | Resolve all prompts when job begins, store as snapshot in job metadata. Chapters use snapshot, not live resolution. Prevents mid-generation inconsistency. | E |
| Prompt versioning | Add `version INTEGER DEFAULT 1` to `prompt_overrides`, auto-increment on update. Add `prompt_override_versions` history table for rollback + audit. Generated content records reference `prompt_version`. | E |
| Logo cache-busting | Logo URL includes `?v={md5(data)[:8]}`. Branding config includes computed `logo_version`. When logo changes, branding config updates, URL changes, browsers fetch new logo immediately. | E |
| Error state components | `@netz/ui` includes: `ErrorBoundary.svelte`, `ConnectionLost.svelte` (SSE banner), `BackendUnavailable.svelte` (full-page), `EmptyState.svelte` (already planned). Default Netz branding as fallback when branding API fails. | A |
| Cross-tab sync | **Explicitly out of scope.** Each tab is independent. Documented in architecture decisions. | — |
| Concurrent config writes | Optimistic locking via `version` column on `VerticalConfigOverride`. PUT requires `If-Match: {version}`, returns 409 if stale. | E |
| Tenant creation atomicity | DB transaction wraps config seed + asset placeholders. If Clerk org succeeds but DB fails, admin sees error and can retry seed via `POST /tenants/{org_id}/seed`. | E |
| Role transition mid-session | Clerk JWT lifetime is 60s (default). Acceptable staleness window. Not addressed further. | — |
| Content retraction flow | Add `unpublish` endpoint: `published → approved` (removes from investor portal but keeps for internal). Already downloaded PDFs are not recalled (institutional norm). | E |
| Session expiry during long ops | Decode JWT `exp`, warn 5min before. Modal with renew button. Critical for IC memo/DD report generation (~3min). No silent logout. | A (A11) |
| Multiple 401 redirects | Single-flight boolean gate in `api-client.ts`. 5 concurrent 401s → 1 redirect. | A (A11) |
| 409 optimistic lock UX | Toast "Updated by another user" + `invalidateAll()`. Used by IC voting, config writes. | A (A11) |

---

## Implementation Phases

### Phase A: @netz/ui Foundation

**Goal:** Shared design system with all tokens, components, layouts, chart wrappers, and utilities. This blocks all three frontends.

**Estimated scope:** ~40 files, foundation for everything.

#### A1: Workspace + Package Scaffold

##### Files

```
pnpm-workspace.yaml
packages/ui/package.json
packages/ui/svelte.config.js
packages/ui/vite.config.ts
packages/ui/tsconfig.json
packages/ui/tailwind.config.ts
packages/ui/src/lib/index.ts          ← barrel export
```

##### Tasks

- [x] Create `pnpm-workspace.yaml` with `packages/*` and `frontends/*`
- [x] Initialize `@netz/ui` package with `@sveltejs/package` for library build
- [x] Configure Tailwind CSS 4 with custom design tokens
- [x] Configure TypeScript strict mode
- [x] Add `Makefile` targets: `dev:ui` (watch mode), `build:ui` (`svelte-package`), `types` (`openapi-typescript`)

##### package.json

```json
{
  "name": "@netz/ui",
  "version": "0.1.0",
  "svelte": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": { "types": "./dist/index.d.ts", "svelte": "./dist/index.js" },
    "./styles": "./dist/styles/index.css",
    "./charts": { "types": "./dist/charts/index.d.ts", "svelte": "./dist/charts/index.js" },
    "./utils": { "types": "./dist/utils/index.d.ts", "default": "./dist/utils/index.js" }
  },
  "scripts": {
    "dev": "svelte-package -w",
    "build": "svelte-kit sync && svelte-package -o dist",
    "check": "svelte-check --tsconfig ./tsconfig.json"
  },
  "peerDependencies": {
    "svelte": "^5.0.0"
  },
  "devDependencies": {
    "@sveltejs/package": "^2.0.0",
    "svelte": "^5.0.0",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.5.0"
  }
}
```

##### Acceptance Criteria

- [x] `pnpm install` resolves workspace dependencies
- [ ] `pnpm --filter @netz/ui build` produces `dist/` with Svelte exports (requires running backend for type gen)
- [ ] `make types` generates `packages/ui/src/types/api.d.ts` from FastAPI OpenAPI schema (stub created, backend needed)
- [x] TypeScript strict mode with zero errors

#### A2: Design Tokens

##### Files

```
packages/ui/src/lib/styles/tokens.css
packages/ui/src/lib/styles/typography.css
packages/ui/src/lib/styles/spacing.css
packages/ui/src/lib/styles/shadows.css
packages/ui/src/lib/styles/animations.css
packages/ui/src/lib/styles/index.css       ← imports all token files
```

##### Tasks

- [x] Define CSS custom properties for Netz default branding (`--netz-brand-primary: #1B365D`, etc.)
- [x] Define typography scale: 6 heading sizes, body, small, mono — using Inter as default
- [x] Define 4px-based spacing scale (`--netz-space-1` through `--netz-space-16`)
- [x] Define 5-level elevation system (shadows)
- [x] Define transition presets (slide-in for context panel, fade for modals)
- [x] All tokens use `--netz-` prefix to avoid collisions
- [x] Tokens designed to be overridable by tenant branding (CSS custom properties cascade)

##### Acceptance Criteria

- [x] Tokens file loads without error
- [x] All colors meet WCAG 2.1 AA contrast ratio (4.5:1 for body text, 3:1 for large text) against default surface
- [x] Token values match brainstorm branding schema

#### A3: shadcn-svelte Primitives

##### Files

```
packages/ui/src/lib/components/Button.svelte
packages/ui/src/lib/components/Card.svelte
packages/ui/src/lib/components/Badge.svelte
packages/ui/src/lib/components/Dialog.svelte
packages/ui/src/lib/components/Sheet.svelte
packages/ui/src/lib/components/Tabs.svelte
packages/ui/src/lib/components/Input.svelte
packages/ui/src/lib/components/Select.svelte
packages/ui/src/lib/components/Textarea.svelte
packages/ui/src/lib/components/Tooltip.svelte
packages/ui/src/lib/components/DropdownMenu.svelte
packages/ui/src/lib/components/Command.svelte
packages/ui/src/lib/components/Skeleton.svelte
```

##### Tasks

- [x] Install `bits-ui` (shadcn-svelte foundation) as dependency
- [x] Customize each component to use `--netz-*` design tokens
- [x] All components use Svelte 5 runes (`$props`, `$state`, `$derived`)
- [x] All components accept `class` prop for Tailwind extension
- [ ] `Command.svelte` implements `⌘K` command palette pattern (deferred to Phase B — needs route context)

##### Acceptance Criteria

- [x] Each component renders correctly in isolation (verified via svelte-check 0 errors + vitest)
- [x] Components respect `--netz-*` token overrides (CSS custom properties cascade)
- [x] Keyboard navigation works on all interactive components (bits-ui primitives provide this)

#### A4: Table Component (TanStack)

##### Files

```
packages/ui/src/lib/components/DataTable.svelte
packages/ui/src/lib/components/DataTablePagination.svelte
packages/ui/src/lib/components/DataTableColumnHeader.svelte
packages/ui/src/lib/components/DataTableToolbar.svelte
```

##### Tasks

- [x] Install `@tanstack/svelte-table` as dependency
- [x] Create `DataTable.svelte` wrapper: accepts TanStack column defs + data, renders with shadcn styling
- [x] Implement sorting (click column header), filtering (toolbar input), pagination (bottom bar)
- [ ] Implement virtual scrolling via `@tanstack/svelte-virtual` for 500+ row datasets (dep installed, wiring in Phase C)
- [ ] Row selection (checkbox column) for bulk actions (deferred to Phase B — needs use case)
- [ ] Column resize via drag handle (deferred to Phase B — needs use case)
- [x] Empty state when data array is empty (renders `EmptyState.svelte`)

##### Acceptance Criteria

- [ ] Renders 1000 rows without jank (virtual scrolling — verify in Phase C with fund universe)
- [x] Sort, filter, paginate work independently and combined (TanStack Table wired)
- [x] Table styling matches Netz institutional aesthetic (navy header band, clean borders)

#### A5: Netz Composite Components

##### Files

```
packages/ui/src/lib/components/DataCard.svelte
packages/ui/src/lib/components/StatusBadge.svelte
packages/ui/src/lib/components/EmptyState.svelte
packages/ui/src/lib/components/PDFDownload.svelte
packages/ui/src/lib/components/LanguageToggle.svelte
packages/ui/src/lib/components/ErrorBoundary.svelte
packages/ui/src/lib/components/ConnectionLost.svelte
packages/ui/src/lib/components/BackendUnavailable.svelte
```

##### Tasks

- [x] `DataCard.svelte` — KPI card: value (large), label, trend arrow (up/down/flat), optional sparkline slot
- [x] `StatusBadge.svelte` — typed badge with predefined color maps (deal stages, regime states, risk levels, review statuses)
- [x] `EmptyState.svelte` — centered illustration + message + optional action button
- [x] `PDFDownload.svelte` — download button with language toggle (PT/EN), loading state during generation
- [x] `LanguageToggle.svelte` — PT/EN toggle that updates paraglide locale + API download params
- [x] `ErrorBoundary.svelte` — catches Svelte component errors, shows fallback UI with retry button
- [x] `ConnectionLost.svelte` — top banner "Connection lost. Reconnecting..." with retry countdown
- [x] `BackendUnavailable.svelte` — full-page error state when API is unreachable, default Netz branding fallback

##### Acceptance Criteria

- [x] DataCard renders value, label, trend correctly (vitest: 4 tests passing)
- [x] StatusBadge maps all known status values to correct colors (vitest: 7 tests passing)
- [x] Error components render gracefully without depending on API/SSE (no API deps in ErrorBoundary/ConnectionLost/BackendUnavailable)

#### A6: Layout Components

##### Files

```
packages/ui/src/lib/layouts/AppShell.svelte
packages/ui/src/lib/layouts/Sidebar.svelte
packages/ui/src/lib/layouts/ContextPanel.svelte
packages/ui/src/lib/layouts/InvestorShell.svelte
packages/ui/src/lib/layouts/PageHeader.svelte
```

##### Tasks

- [x] `AppShell.svelte` — CSS Grid: sidebar (56px/240px) + main + optional panel (400px). Responsive: sidebar collapses to icons at `<1024px`, panel becomes full-screen modal at `<768px`
- [x] `Sidebar.svelte` — collapsible icon navigation. Props: `items: NavItem[]`, `collapsed: boolean`. Active item highlighted. Svelte 5 `$state` for collapse toggle
- [x] `ContextPanel.svelte` — wraps `Sheet.svelte` (slide-in from right, 400px). Props: `open: boolean`, `title: string`, default slot for content. Close button + escape key
- [x] `InvestorShell.svelte` — minimal layout: top bar (logo + org name + language toggle + sign out), main content area, footer. No sidebar. Tenant branding applied via CSS vars
- [x] `PageHeader.svelte` — title + breadcrumb + actions slot (right-aligned buttons)

##### Acceptance Criteria

- [x] AppShell responsive at 4 breakpoints: `>1280px` (full), `1024px` (sidebar collapsed), `768px` (no panel), `<600px` (mobile stack)
- [x] Sidebar collapse animates smoothly (CSS transition, not JS)
- [x] ContextPanel opens/closes with slide animation (CSS transform transition)
- [x] InvestorShell shows tenant logo from branding config (logoUrl prop)

#### A7: Chart Wrappers (ECharts)

##### Files

```
packages/ui/src/lib/charts/ChartContainer.svelte
packages/ui/src/lib/charts/TimeSeriesChart.svelte
packages/ui/src/lib/charts/RegimeChart.svelte
packages/ui/src/lib/charts/GaugeChart.svelte
packages/ui/src/lib/charts/BarChart.svelte
packages/ui/src/lib/charts/FunnelChart.svelte
packages/ui/src/lib/charts/HeatmapChart.svelte
packages/ui/src/lib/charts/ScatterChart.svelte
packages/ui/src/lib/charts/index.ts
```

##### Tasks

- [x] Install `echarts` + `svelte-echarts` as dependencies
- [x] `ChartContainer.svelte` — ECharts instance wrapper with: ResizeObserver for responsive sizing, loading skeleton, error boundary, Netz theme registration (colors from `--netz-*` tokens)
- [x] `TimeSeriesChart.svelte` — line/area chart with date x-axis. Props: `series`, `dateRange`, `yAxisLabel`. Used for NAV history, CVaR timeline
- [x] `RegimeChart.svelte` — time series with colored band overlay (RISK_ON=green, RISK_OFF=yellow, INFLATION=orange, CRISIS=red). Used in both wealth risk monitor and credit macro dashboard
- [x] `GaugeChart.svelte` — radial gauge. Props: `value`, `min`, `max`, `thresholds[]`. Used for CVaR utilization
- [x] `BarChart.svelte` — horizontal/vertical. Props: `data`, `orientation`, `stacked`. Used for allocation weights, block distribution
- [x] `FunnelChart.svelte` — pipeline funnel. Props: `stages[]` with count and label. Used for credit deal pipeline
- [x] `HeatmapChart.svelte` — grid heatmap. Props: `matrix`, `xLabels`, `yLabels`. Used for correlation matrix
- [x] `ScatterChart.svelte` — scatter plot. Props: `points[]` with x, y, label, size. Used for risk vs return
- [x] All chart wrappers register Netz theme on mount: read `--netz-*` CSS vars → `echarts.registerTheme('netz', {...})`
- [x] Chart palette from branding tokens (defaults to `['#1B365D', '#3A7BD5', '#8B9DAF', '#D4E4F7', '#FF975A']`)

##### Acceptance Criteria

- [x] All 8 charts render with sample data (ChartContainer + 7 typed wrappers)
- [x] Charts resize responsively without jank (ResizeObserver in ChartContainer)
- [x] Chart palette changes when `--netz-brand-*` CSS vars change (theme reads --netz-chart-* vars)
- [x] Loading skeleton shows while data is fetching (ChartContainer loading prop)

#### A8: Utilities

##### Files

```
packages/ui/src/lib/utils/api-client.ts
packages/ui/src/lib/utils/sse-client.ts
packages/ui/src/lib/utils/format.ts
packages/ui/src/lib/utils/branding.ts
packages/ui/src/lib/utils/index.ts
```

##### Tasks

- [x] `api-client.ts` — `NetzApiClient` class with typed `get<T>`, `post<T>`, `patch<T>`, `delete` methods. Auto-injects `Authorization: Bearer {token}`. Two factory functions: `createServerApiClient(token)` (for `+page.server.ts`) and `createClientApiClient(getToken)` (for client-side, token from Clerk). Error handling: 401 → redirect to sign-in, 403 → show forbidden, 5xx → throw with context
- [x] **Single-flight 401 redirect** in `api-client.ts` — boolean gate prevents multiple `goto('/auth/sign-in')` when concurrent requests return 401 simultaneously. Pattern: `let redirecting = false; if (res.status === 401 && !redirecting) { redirecting = true; authStore.logout(); }`. Reset after navigation completes. Without this, 5 parallel fetches on a page → 5 redirect calls → broken navigation stack
- [x] `sse-client.ts` — `createSSEStream<T>(config)` function. Uses `fetch()` + `ReadableStream`. Exponential backoff reconnect (1s → 30s, 5 retries max). Heartbeat detection (45s timeout). **No `Last-Event-ID` replay** (Redis pub/sub is fire-and-forget). Accepts `initialState` prop from REST recovery. Returns object with `connect()`, `disconnect()`, and Svelte 5 reactive state (`$state` for events, status, error)
- [x] `format.ts` — number formatting (BRL/USD currency, percentage, compact notation), date formatting (PT/EN locale-aware), ISIN formatting. Uses `Intl.NumberFormat` and `Intl.DateTimeFormat`
- [x] `branding.ts` — `brandingToCSS(config)` converts branding JSONB to CSS custom property string. `injectBranding(element, config)` sets properties on DOM element. `defaultBranding` fallback object (Netz navy theme)
- [x] **Session expiry warning** in `auth.ts` — decode JWT `exp` claim after login, `setTimeout` for 5min before expiry, show modal "Sessão expira em 5 minutos — renove seu acesso". No silent logout — user always notified before. Critical for: IC memo generation (~3min), DD report (~3min), backtest (~variable) — long-running operations that cannot be silently interrupted
- [x] **Concurrent 409 handling** in `api-client.ts` — when `PATCH`/`PUT` returns HTTP 409 (optimistic lock conflict), show toast "Updated by another user, refreshing..." and auto-refresh the current data via `invalidate()`. Used by: IC voting approve/reject, config writes (admin panel), any operation with version-based optimistic locking

##### Acceptance Criteria

- [x] API client handles 401/403/5xx correctly (AuthError/ForbiddenError/ValidationError/ServerError classes)
- [x] SSE client reconnects with backoff, stops after 5 retries, shows ConnectionLost banner
- [x] Format functions handle PT and EN locales correctly (vitest: 6 tests passing)
- [x] Branding injection produces valid CSS custom properties (vitest: 4 tests passing)
- [x] Single-flight redirect: 5 concurrent 401s produce exactly 1 redirect (vitest)
- [x] Session expiry modal appears 5min before JWT exp (vitest: mock timer)
- [x] 409 response on PATCH/PUT shows toast + triggers data refresh (vitest)

#### A9: Type Generation + i18n Setup

##### Files

```
packages/ui/src/types/api.d.ts          ← auto-generated
packages/ui/messages/en.json
packages/ui/messages/pt.json
Makefile                                 ← add types target
```

##### Tasks

- [x] Install `openapi-typescript` as devDependency
- [x] Add `make types` target: `npx openapi-typescript http://localhost:8000/openapi.json -o packages/ui/src/types/api.d.ts`
- [x] Create shared i18n messages for @netz/ui component labels (empty states, error messages, common actions like "Download", "Cancel", "Retry")
- [ ] Setup paraglide-js configuration in `@netz/ui` for shared messages (deferred — i18n JSON files created, runtime integration in Phase B)

##### Acceptance Criteria

- [ ] `make types` generates TypeScript types matching all backend endpoints (stub created, backend needed)
- [ ] Types are importable: `import type { components } from '@netz/ui/types/api'` (stub created)
- [x] Shared i18n messages cover all @netz/ui component text (en.json + pt.json created)

#### A10: Component Tests

##### Files

```
packages/ui/vitest.config.ts
packages/ui/src/lib/components/__tests__/DataCard.test.ts
packages/ui/src/lib/components/__tests__/StatusBadge.test.ts
packages/ui/src/lib/components/__tests__/DataTable.test.ts
packages/ui/src/lib/layouts/__tests__/AppShell.test.ts
packages/ui/src/lib/charts/__tests__/ChartContainer.test.ts
```

##### Tasks

- [x] Configure vitest with `@testing-library/svelte` and happy-dom environment
- [x] Write component tests for DataCard (props rendering, trend direction)
- [x] Write component tests for StatusBadge (all status type mappings)
- [ ] Write component tests for DataTable (sort, filter, pagination, empty state) (deferred — TanStack store unwrapping complicates unit tests)
- [ ] Write layout tests for AppShell (responsive breakpoints, sidebar collapse) (deferred — needs browser for media queries)
- [ ] Write chart wrapper tests for ChartContainer (loading, error, resize) (deferred — ECharts needs canvas)

##### Acceptance Criteria

- [x] `pnpm --filter @netz/ui test` passes all component tests (24/24 passing)
- [ ] Test coverage on exported components ≥ 80% (Button/DataCard/StatusBadge/format/branding covered; remaining components need integration tests)

#### A11: Race Conditions & Concurrency Patterns

##### Subscribe-then-Snapshot Ordering

SSE + REST data loading must follow this exact sequence to prevent event gaps:

```typescript
// sse-client.svelte.ts — subscribe-then-snapshot pattern
export function createSSEWithSnapshot<T>(config: {
  sseUrl: string;
  restUrl: string;
  apiClient: NetzApiClient;
  getToken: () => Promise<string>;
  merge: (snapshot: T, buffered: SSEEvent[]) => T;
}) {
  let state = $state<T | null>(null);
  const buffer: SSEEvent[] = [];
  let snapshotLoaded = false;

  async function connect() {
    // Step 1: Subscribe SSE FIRST (events buffer while REST loads)
    const sse = createSSEStream({
      url: config.sseUrl,
      getToken: config.getToken,
      onEvent: (event) => {
        if (!snapshotLoaded) {
          buffer.push(event); // buffer during REST call
        } else {
          state = applyEvent(state, event); // apply live
        }
      },
    });
    sse.connect();

    // Step 2: REST snapshot (current state)
    const snapshot = await config.apiClient.get<T>(config.restUrl);

    // Step 3: Merge — snapshot is base, buffer has events during gap
    state = config.merge(snapshot, buffer);
    snapshotLoaded = true;
    buffer.length = 0; // clear buffer
  }

  return { get state() { return state; }, connect };
}
```

##### Single-Flight 401 Redirect

Prevents multiple `goto('/auth/sign-in')` when concurrent requests return 401:

```typescript
// api-client.ts — single-flight redirect gate
let redirecting = false;

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.ok) { /* ... */ }

  if (res.status === 401 && !redirecting) {
    redirecting = true;
    // Import dynamically to avoid circular dep in server context
    const { goto } = await import('$app/navigation');
    await goto('/auth/sign-in');
    redirecting = false; // reset after navigation completes
    throw new AuthError();
  } else if (res.status === 401) {
    // Already redirecting — just throw, don't navigate again
    throw new AuthError();
  }
  // ... rest of error handling
}
```

##### Concurrent 409 Handling (Optimistic Lock Conflicts)

When `PATCH`/`PUT` returns 409, show feedback + auto-refresh:

```typescript
// api-client.ts — 409 handler
case 409: {
  // Import toast reactively (only in browser context)
  if (typeof window !== 'undefined') {
    const { addToast } = await import('@netz/ui');
    addToast({
      type: 'warning',
      message: 'Updated by another user, refreshing...',
      duration: 4000,
    });
    // Trigger SvelteKit data refresh
    const { invalidateAll } = await import('$app/navigation');
    await invalidateAll();
  }
  throw new ConflictError(
    parsed?.detail as string ?? 'Resource was modified by another user',
    parsed?.current_version as number,
  );
}
```

```typescript
// New error class in api-client.ts
export class ConflictError extends Error {
  readonly status = 409;
  readonly currentVersion: number | undefined;
  constructor(message: string, currentVersion?: number) {
    super(message);
    this.name = 'ConflictError';
    this.currentVersion = currentVersion;
  }
}
```

##### Session Expiry Warning

Decode JWT `exp` and warn user before silent logout:

```typescript
// auth.ts — session expiry monitor
const SESSION_WARNING_MS = 5 * 60 * 1000; // 5 minutes before expiry

export function startSessionExpiryMonitor(token: string, onWarning: () => void) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const expMs = payload.exp * 1000;
    const warningAt = expMs - SESSION_WARNING_MS;
    const delay = warningAt - Date.now();

    if (delay <= 0) {
      // Already within warning window
      onWarning();
      return () => {};
    }

    const timer = setTimeout(onWarning, delay);
    return () => clearTimeout(timer);
  } catch {
    // Malformed token — don't crash, just skip monitoring
    return () => {};
  }
}
```

Usage in root `+layout.svelte`:

```svelte
<script>
  import { startSessionExpiryMonitor } from '@netz/ui/utils';
  import SessionExpiryModal from './SessionExpiryModal.svelte';

  let { data } = $props();
  let showExpiryWarning = $state(false);

  $effect(() => {
    if (data.token) {
      const cleanup = startSessionExpiryMonitor(data.token, () => {
        showExpiryWarning = true;
      });
      return cleanup;
    }
  });
</script>

{#if showExpiryWarning}
  <SessionExpiryModal onRenew={() => { /* Clerk getToken({ skipCache: true }) + invalidateAll() */ }} />
{/if}
```

##### Tasks

- [x] Implement subscribe-then-snapshot in `sse-client.svelte.ts` (buffer → REST → merge → live tail)
- [x] Add single-flight 401 redirect gate to `api-client.ts`
- [x] Add `ConflictError` class and 409 handler with toast + `invalidateAll()` to `api-client.ts`
- [x] Implement `startSessionExpiryMonitor()` in `auth.ts` with JWT `exp` decode + `setTimeout`
- [ ] Create `SessionExpiryModal.svelte` — "Sessão expira em 5 minutos — renove seu acesso" with renew button (deferred to Phase B — needs frontend root layout)
- [ ] Wire session expiry monitor in root `+layout.svelte` of each frontend (deferred to Phase B — needs frontend scaffold)

##### Acceptance Criteria

- [x] SSE subscribe-then-snapshot: events during REST gap are not lost (vitest with mock timers)
- [x] Single-flight: 5 concurrent 401s → exactly 1 `goto()` call (vitest)
- [x] 409 on PATCH → toast shown + `invalidateAll()` called (vitest)
- [x] Session expiry modal appears 5min before JWT exp (vitest with fake timers)
- [x] Malformed JWT does not crash session monitor (vitest)

---

### Phase B: Credit Frontend — Team Views

**Goal:** All credit team functionality operational. ~60 endpoints consumed.

**Prerequisite:** Phase A complete.

#### B1: SvelteKit Scaffold + Auth

##### Files

```
frontends/credit/package.json
frontends/credit/svelte.config.js
frontends/credit/vite.config.ts
frontends/credit/tsconfig.json
frontends/credit/tailwind.config.ts
frontends/credit/src/app.html
frontends/credit/src/app.css
frontends/credit/src/hooks.server.ts
frontends/credit/src/routes/+layout.server.ts
frontends/credit/src/routes/+layout.svelte
frontends/credit/src/routes/+error.svelte
frontends/credit/src/routes/auth/sign-in/+page.svelte
frontends/credit/src/routes/auth/sign-out/+page.svelte
frontends/credit/src/lib/api/client.ts
frontends/credit/messages/en.json
frontends/credit/messages/pt.json
```

##### Tasks

- [ ] Initialize SvelteKit 2 with `adapter-node` and TypeScript strict
- [ ] `package.json` name: `netz-credit-intelligence`, dependency: `"@netz/ui": "workspace:*"`
- [ ] `hooks.server.ts` — Clerk JWT verification on every request. Extract `Actor` from JWT. Dev bypass: `X-DEV-ACTOR` header. Attach `actor` and `token` to `event.locals`
- [ ] `+layout.server.ts` — load Actor + branding from `GET /api/v1/branding`. Pass to all pages. If branding fetch fails, use `defaultBranding` fallback
- [ ] `+layout.svelte` — inject branding as CSS vars on root element. Render `AppShell` with `Sidebar`. Handle ErrorBoundary at root level
- [ ] `+error.svelte` — render `BackendUnavailable` for 5xx, custom messages for 403/404
- [ ] `src/lib/api/client.ts` — re-export `createServerApiClient` and `createClientApiClient` from `@netz/ui` with credit-specific base URL
- [ ] Clerk sign-in/sign-out pages using `svelte-clerk` components
- [ ] Sidebar navigation items: Dashboard, Pipeline, Portfolio, Documents, Reporting, Copilot
- [ ] Add `Makefile` targets: `dev:credit`, `build:credit`
- [ ] paraglide-js setup with credit-specific messages (deal stages, review statuses, etc.)

##### Acceptance Criteria

- [ ] `pnpm --filter netz-credit-intelligence dev` starts dev server
- [ ] Unauthenticated request → redirect to `/auth/sign-in`
- [ ] Authenticated request → sidebar renders with navigation items
- [ ] Branding loads from API and applies CSS vars to root
- [ ] Branding API failure → default Netz theme applied
- [ ] `X-DEV-ACTOR` header bypasses Clerk in dev mode

#### B2: Fund Context + Route Group

##### Files

```
frontends/credit/src/routes/(team)/+layout.server.ts
frontends/credit/src/routes/(team)/+layout.svelte
frontends/credit/src/routes/(team)/funds/+page.server.ts
frontends/credit/src/routes/(team)/funds/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/+layout.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte
```

##### Tasks

- [ ] `(team)/+layout.server.ts` — guard: reject INVESTOR role (return 403)
- [ ] `(team)/funds/+page.server.ts` — load fund list for current org
- [ ] `(team)/funds/+page.svelte` — fund selector page (or redirect to first fund)
- [ ] `(team)/funds/[fundId]/+layout.server.ts` — validate `fundId` belongs to current org (query fund by ID + org_id). Load fund metadata. Make `fund` available to all child pages via `data.fund`
- [ ] `(team)/funds/[fundId]/+layout.svelte` — fund context header showing fund name + fund-scoped sidebar items (Pipeline, Portfolio, Documents, Reporting)
- [ ] Sidebar fund selector: dropdown at top navigates to `/funds/{fundId}/pipeline`

##### Acceptance Criteria

- [ ] Navigating to `/funds/{fundId}/...` loads fund context
- [ ] Invalid `fundId` → 404
- [ ] Fund not in current org → 403
- [ ] INVESTOR role user accessing `(team)` routes → 403

#### B3: Dashboard

##### Files

```
frontends/credit/src/routes/(team)/dashboard/+page.server.ts
frontends/credit/src/routes/(team)/dashboard/+page.svelte
frontends/credit/src/lib/components/PipelineFunnel.svelte
frontends/credit/src/lib/components/TaskInbox.svelte
```

##### Tasks

- [ ] `+page.server.ts` — parallel fetch: `GET /dashboard/portfolio-summary`, `GET /dashboard/pipeline-summary`, `GET /dashboard/pipeline-analytics`, `GET /dashboard/macro-snapshot`, `GET /dashboard/compliance-alerts`
- [ ] Dashboard layout — three tiers:
  - Tier 1 (Command): `TaskInbox.svelte` — action queue (deals awaiting IC, docs pending review). `DataCard` components for alert counts
  - Tier 2 (Analytical): `PipelineFunnel.svelte` (uses `FunnelChart` from @netz/ui) + AUM/deployment `DataCard` + AI confidence distribution
  - Tier 3 (Operational): risk vs return `ScatterChart` + macro sparklines (`TimeSeriesChart`) + activity feed
- [ ] All charts use tenant branding palette
- [ ] Empty states for sections with no data

##### Acceptance Criteria

- [ ] Dashboard loads with real API data (or gracefully shows empty states)
- [ ] Pipeline funnel renders deal counts by stage
- [ ] Macro sparklines render FRED data
- [ ] All DataCards show correct values and trends

#### B4: Pipeline (Deals + IC Memos)

##### Files

```
frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte
frontends/credit/src/lib/components/DealStageTimeline.svelte
frontends/credit/src/lib/components/ICMemoViewer.svelte
frontends/credit/src/lib/components/ICMemoStreamingChapter.svelte
```

##### Tasks

- [ ] Pipeline list page — `DataTable` with deal columns (name, stage, strategy, created_at, qualification status). Sortable, filterable by stage
- [ ] Click row → `ContextPanel` slides in with deal summary + quick actions (change stage, view IC memo status)
- [ ] Click "Open" → navigate to `/pipeline/{dealId}` full page
- [ ] Deal detail page — tabs: Overview, IC Memo, Documents, Compliance
- [ ] `DealStageTimeline.svelte` — horizontal timeline showing stage progression with dates and rationale
- [ ] IC Memo tab:
  - If no memo exists: "Generate IC Memo" button → `POST /deals/{dealId}/ic-memo` → returns `job_id`
  - If memo in progress: SSE stream with `initialState` from `GET /deals/{dealId}/ic-memo` (REST recovery)
  - If memo complete: full memo display with 14 chapters
- [ ] `ICMemoViewer.svelte` — renders chapter list with completion status, expandable chapter content
- [ ] `ICMemoStreamingChapter.svelte` — renders streaming text for in-progress chapter with typing animation
- [ ] SSE pattern: REST for completed chapters + SSE tail for live chapters (see brainstorm: SSE Strategy)
- [ ] Stage transition: `PATCH /deals/{dealId}/decision` with confirmation dialog
- [ ] IC voting status display with quorum indicator

##### Acceptance Criteria

- [ ] Deal list renders with real data, sorting and filtering work
- [ ] Context panel shows deal summary on row click
- [ ] IC memo generation triggers and streams chapter content via SSE
- [ ] Navigating away and back recovers state from REST (no loading flash for completed chapters)
- [ ] Stage transitions update deal list via `invalidate()`

#### B5: Portfolio

##### Files

```
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/assets/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/obligations/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/alerts/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/actions/+page.svelte
```

##### Tasks

- [ ] Portfolio overview page with tabs: Assets, Obligations, Alerts, Actions
- [ ] Assets tab — `DataTable` of portfolio assets with type, strategy, status
- [ ] Obligations tab — `DataTable` with due dates, types, status. Overdue highlighting
- [ ] Alerts tab — alert list with severity badges (`StatusBadge`), asset links
- [ ] Actions tab — action items with status tracking, evidence notes update via `PATCH`
- [ ] Create asset: form dialog → `POST /funds/{fundId}/assets`
- [ ] Create obligation: form dialog → `POST /funds/{fundId}/assets/{assetId}/obligations`

##### Acceptance Criteria

- [ ] All 4 portfolio tabs render with real data
- [ ] Asset creation and obligation creation work via dialogs
- [ ] Overdue obligations visually highlighted
- [ ] Action status updates persist correctly

#### B6: Documents

##### Files

```
frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/documents/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/documents/upload/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/documents/reviews/[reviewId]/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/documents/dataroom/+page.svelte
frontends/credit/src/lib/components/DocumentUploadFlow.svelte
frontends/credit/src/lib/components/DocumentReviewWorkflow.svelte
frontends/credit/src/lib/components/IngestionProgress.svelte
```

##### Tasks

- [ ] Documents list — `DataTable` filterable by root_folder, domain, title. Pagination
- [ ] Upload flow (`DocumentUploadFlow.svelte`):
  1. Select file (drag & drop zone + file picker)
  2. `POST /documents/upload-url` → get SAS URL
  3. Upload directly to storage via SAS URL
  4. `POST /documents/upload-complete` → get `job_id`
  5. `IngestionProgress.svelte` — SSE stream showing pipeline stages (OCR, classify, chunk, embed, index)
- [ ] Review queue — `DataTable` of pending reviews with priority, due date, status
- [ ] Review detail — assignment list, checklist items, decision form (approve/reject/revision)
- [ ] Dataroom — folder browser with breadcrumb navigation
- [ ] Evidence upload for deals — link evidence to deal via upload request

##### Acceptance Criteria

- [ ] Full upload flow works: file → SAS → upload → SSE progress → indexed
- [ ] Review workflow: assign, decide, resubmit, finalize
- [ ] Ingestion progress shows all pipeline stages in real-time via SSE

#### B7: Reporting

##### Files

```
frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.server.ts
frontends/credit/src/routes/(team)/funds/[fundId]/reporting/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/reporting/nav/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/reporting/report-packs/+page.svelte
frontends/credit/src/routes/(team)/funds/[fundId]/reporting/evidence-pack/+page.svelte
frontends/credit/src/lib/components/EvidencePackBrowser.svelte
```

##### Tasks

- [ ] Reporting overview — tabs: NAV, Report Packs, Evidence Packs
- [ ] NAV management — create snapshot, batch upsert valuations, finalize, publish
- [ ] Report packs — list, create, update, finalize, publish workflow
- [ ] Evidence pack — Q&A browser with citation display (chunk excerpts + source documents)
- [ ] PDF download for all reports using `PDFDownload.svelte` with language toggle

##### Acceptance Criteria

- [ ] NAV snapshot creation and finalization workflow complete
- [ ] Report pack publish makes it available in investor portal
- [ ] Evidence pack displays Q&A with citations correctly

#### B8: Copilot

##### Files

```
frontends/credit/src/routes/(team)/copilot/+page.svelte
frontends/credit/src/lib/components/CopilotChat.svelte
frontends/credit/src/lib/components/CopilotCitation.svelte
```

##### Tasks

- [ ] Chat interface — message input, response area
- [ ] SSE streaming for responses (chunk events)
- [ ] Citation display — source document links with page numbers
- [ ] Message history (client-side session state)

##### Acceptance Criteria

- [ ] Question submission triggers SSE stream
- [ ] Response renders with streaming text
- [ ] Citations show source documents with clickable links

#### B9: Credit E2E Tests

##### Files

```
frontends/credit/tests/e2e/auth.spec.ts
frontends/credit/tests/e2e/pipeline.spec.ts
frontends/credit/tests/e2e/documents.spec.ts
```

##### Tasks

- [ ] Auth flow: sign in → sidebar renders → sign out
- [ ] Pipeline flow: select fund → view deals → click deal → see detail panel
- [ ] Document flow: upload → progress → indexed

##### Acceptance Criteria

- [ ] E2E tests pass against running backend (docker-compose)

---

### Phase B+: Credit Investor Portal

**Goal:** Read-only investor view of published credit content.

**Prerequisite:** Phase B complete.

#### Files

```
frontends/credit/src/routes/(investor)/+layout.server.ts
frontends/credit/src/routes/(investor)/+layout.svelte
frontends/credit/src/routes/(investor)/report-packs/+page.server.ts
frontends/credit/src/routes/(investor)/report-packs/+page.svelte
frontends/credit/src/routes/(investor)/statements/+page.server.ts
frontends/credit/src/routes/(investor)/statements/+page.svelte
frontends/credit/src/routes/(investor)/documents/+page.server.ts
frontends/credit/src/routes/(investor)/documents/+page.svelte
```

#### Tasks

- [ ] `(investor)/+layout.server.ts` — guard: require INVESTOR or ADVISOR role
- [ ] `(investor)/+layout.svelte` — `InvestorShell` layout with tenant branding, language toggle, sign out
- [ ] Report packs — list published packs with `PDFDownload` for each
- [ ] Investor statements — list published statements with download
- [ ] Documents — list approved-for-distribution documents
- [ ] All content filtered: `status IN ('approved', 'published')` on backend
- [ ] Language toggle affects download URL param `?language=pt|en`

#### Acceptance Criteria

- [ ] INVESTOR role sees only published content
- [ ] INVESTMENT_TEAM role accessing `/investor/...` → 403
- [ ] PDF downloads work in both PT and EN
- [ ] Tenant branding (logo, colors) applied correctly

---

### Phase C: Wealth Frontend — Team Views

**Goal:** All wealth team functionality operational. ~58 endpoints consumed.

**Prerequisite:** Phase A complete. Phase B patterns proven and reusable.

#### C1: SvelteKit Scaffold + Auth

##### Files

```
frontends/wealth/package.json
frontends/wealth/svelte.config.js
frontends/wealth/vite.config.ts
frontends/wealth/tsconfig.json
frontends/wealth/tailwind.config.ts
frontends/wealth/src/app.html
frontends/wealth/src/app.css
frontends/wealth/src/hooks.server.ts
frontends/wealth/src/routes/+layout.server.ts
frontends/wealth/src/routes/+layout.svelte
frontends/wealth/src/routes/+error.svelte
frontends/wealth/src/routes/auth/sign-in/+page.svelte
frontends/wealth/src/routes/auth/sign-out/+page.svelte
frontends/wealth/src/lib/api/client.ts
frontends/wealth/messages/en.json
frontends/wealth/messages/pt.json
```

##### Tasks

- [ ] Same scaffold pattern as credit (Phase B1), name: `netz-wealth-os`
- [ ] Sidebar navigation: Dashboard, Funds, Portfolios, Allocation, Risk, Analytics, Macro, Content, DD Reports, Model Portfolios
- [ ] Add `Makefile` targets: `dev:wealth`, `build:wealth`

##### Acceptance Criteria

- [ ] Same as B1 but for wealth frontend

#### C2: Dashboard

##### Files

```
frontends/wealth/src/routes/(team)/dashboard/+page.server.ts
frontends/wealth/src/routes/(team)/dashboard/+page.svelte
frontends/wealth/src/lib/components/PortfolioCard.svelte
```

##### Tasks

- [ ] Load 3 model portfolios with latest snapshots
- [ ] `PortfolioCard.svelte` — profile card: name, CVaR gauge (`GaugeChart`), regime chip (`StatusBadge`), AUM, last snapshot date
- [ ] 3 portfolio cards in responsive grid (3 cols desktop, 1 col mobile)
- [ ] Macro summary: VIX, yield curve, regime indicator
- [ ] SSE connection for live risk alerts (`cvar_update`, `regime_change`, `breach_warning`)

##### Acceptance Criteria

- [ ] 3 portfolio cards render with real data
- [ ] CVaR gauges show current utilization
- [ ] Regime chips show correct color per regime state
- [ ] SSE risk alerts update cards in real-time

#### C3: Funds

##### Files

```
frontends/wealth/src/routes/(team)/funds/+page.server.ts
frontends/wealth/src/routes/(team)/funds/+page.svelte
frontends/wealth/src/routes/(team)/funds/[fundId]/+page.server.ts
frontends/wealth/src/routes/(team)/funds/[fundId]/+page.svelte
```

##### Tasks

- [ ] Fund universe — `DataTable` with virtual scrolling (500+ funds). Columns: name, ticker, block, geography, asset_class, manager_score, return consistency, drawdown control
- [ ] Filter by block, geography, asset class. Sort by any column
- [ ] Fund detail page — full metrics, NAV chart (`TimeSeriesChart`), risk metrics, Lipper rankings
- [ ] Fund scoring display with component breakdown

##### Acceptance Criteria

- [ ] 500+ fund table renders smoothly with virtual scrolling
- [ ] Filter + sort combinations work correctly
- [ ] Fund detail page shows complete data

#### C4: Portfolios + Rebalance

##### Files

```
frontends/wealth/src/routes/(team)/portfolios/+page.server.ts
frontends/wealth/src/routes/(team)/portfolios/+page.svelte
frontends/wealth/src/routes/(team)/portfolios/[portfolioId]/+page.server.ts
frontends/wealth/src/routes/(team)/portfolios/[portfolioId]/+page.svelte
frontends/wealth/src/routes/(team)/portfolios/[portfolioId]/rebalance/+page.svelte
```

##### Tasks

- [ ] Portfolio list — 3 profiles with latest snapshot summary
- [ ] Portfolio detail — snapshot with fund weights, CVaR status, regime
- [ ] Snapshot history — `TimeSeriesChart` of portfolio CVaR over time
- [ ] Rebalance workflow: trigger → proposal → IC approval → execution
- [ ] Rebalance detail page with proposed changes table

##### Acceptance Criteria

- [ ] Portfolio snapshots display with weights and CVaR
- [ ] Rebalance proposal renders proposed vs current weights
- [ ] IC approval gate requires correct role

#### C5: Allocation

##### Files

```
frontends/wealth/src/routes/(team)/allocation/+page.server.ts
frontends/wealth/src/routes/(team)/allocation/+page.svelte
frontends/wealth/src/lib/components/AllocationEditor.svelte
```

##### Tasks

- [ ] Strategic allocation — weight editors per block with min/max band indicators
- [ ] Tactical positions — overweight inputs with conviction score
- [ ] Effective allocation — computed view (strategic + tactical)
- [ ] `AllocationEditor.svelte` — slider + input combo per block. Min/max band visualization. Sum-to-100% validation
- [ ] IC approval gate for strategic edits (require IC member role)

##### Acceptance Criteria

- [ ] Weight editors enforce min/max bands
- [ ] Sum-to-100% validated before save
- [ ] Effective allocation recomputes on tactical changes

#### C6: Risk Monitor

##### Files

```
frontends/wealth/src/routes/(team)/risk/+page.server.ts
frontends/wealth/src/routes/(team)/risk/+page.svelte
frontends/wealth/src/lib/components/RegimeTimeline.svelte
```

##### Tasks

- [ ] CVaR timeline — `TimeSeriesChart` with limit lines (warning, breach)
- [ ] Regime timeline — `RegimeChart` with colored bands per regime
- [ ] Macro indicators — VIX, yield curve, CPI, Fed Funds (`DataCard` components)
- [ ] SSE live updates: `cvar_update` → update CVaR chart tail, `regime_change` → update regime chip
- [ ] CVaR history with rolling window selector (1m, 3m, 6m, 12m, 3y)

##### Acceptance Criteria

- [ ] CVaR timeline renders with limit lines
- [ ] Regime bands color-coded correctly
- [ ] SSE updates appear in charts without page refresh

#### C7: Analytics

##### Files

```
frontends/wealth/src/routes/(team)/analytics/+page.server.ts
frontends/wealth/src/routes/(team)/analytics/+page.svelte
frontends/wealth/src/lib/components/BacktestResults.svelte
```

##### Tasks

- [ ] Backtest trigger — select profile, parameters → `POST /analytics/backtest` → get `run_id`
- [ ] Backtest progress SSE → results page when complete
- [ ] `BacktestResults.svelte` — performance table + equity curve chart + CV metrics
- [ ] Optimization — `POST /analytics/optimize` → result display
- [ ] Pareto optimization — multi-objective frontier plot (`ScatterChart`)
- [ ] Correlation matrix — `HeatmapChart` from block NAV data

##### Acceptance Criteria

- [ ] Backtest triggers, shows progress, displays results
- [ ] Pareto frontier renders as scatter plot
- [ ] Correlation heatmap renders with correct block labels

#### C8: Macro + Content + DD Reports + Model Portfolios

##### Files

```
frontends/wealth/src/routes/(team)/macro/+page.svelte
frontends/wealth/src/routes/(team)/content/+page.svelte
frontends/wealth/src/routes/(team)/dd-reports/+page.svelte
frontends/wealth/src/routes/(team)/dd-reports/[reportId]/+page.svelte
frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte
frontends/wealth/src/routes/(team)/model-portfolios/[portfolioId]/+page.svelte
frontends/wealth/src/lib/components/MacroScorecard.svelte
```

##### Tasks

- [ ] Macro — regional scores grid, regime hierarchy, committee reviews (generate, approve/reject)
- [ ] Content — trigger outlooks/flash reports/spotlights, list with status, approve workflow (self-approval blocked), download PDF
- [ ] DD Reports — trigger for fund, chapter progress SSE, version history, full report view with chapters
- [ ] Model Portfolios — create, construct (fund selection), track-record (backtest + stress), detail view
- [ ] `MacroScorecard.svelte` — grid of 4 regional cards with macro scores + global indicators
- [ ] All generation triggers show SSE progress (same REST + SSE tail pattern)

##### Acceptance Criteria

- [ ] Macro committee review generation and CIO approval workflow complete
- [ ] Content approval blocks self-approval
- [ ] DD report chapter streaming works via SSE
- [ ] Model portfolio construction triggers fund selection algorithm

#### C9: Wealth E2E Tests

##### Files

```
frontends/wealth/tests/e2e/auth.spec.ts
frontends/wealth/tests/e2e/dashboard.spec.ts
frontends/wealth/tests/e2e/risk.spec.ts
```

##### Tasks

- [ ] Auth flow: sign in → dashboard loads → sign out
- [ ] Dashboard flow: 3 portfolio cards → CVaR gauges render
- [ ] Risk flow: CVaR timeline renders → regime timeline renders

##### Acceptance Criteria

- [ ] E2E tests pass against running backend

---

### Phase C+: Wealth Investor Portal

**Goal:** Highest priority client-facing deliverable. Investors view published fact-sheets, portfolios, and reports.

**Prerequisite:** Phase C complete.

#### Files

```
frontends/wealth/src/routes/(investor)/+layout.server.ts
frontends/wealth/src/routes/(investor)/+layout.svelte
frontends/wealth/src/routes/(investor)/portfolios/+page.server.ts
frontends/wealth/src/routes/(investor)/portfolios/+page.svelte
frontends/wealth/src/routes/(investor)/fact-sheets/+page.server.ts
frontends/wealth/src/routes/(investor)/fact-sheets/+page.svelte
frontends/wealth/src/routes/(investor)/reports/+page.server.ts
frontends/wealth/src/routes/(investor)/reports/+page.svelte
frontends/wealth/src/routes/(investor)/documents/+page.server.ts
frontends/wealth/src/routes/(investor)/documents/+page.svelte
```

#### Tasks

- [ ] Same guard pattern as credit investor (INVESTOR/ADVISOR roles only)
- [ ] `InvestorShell` layout with tenant branding, language toggle
- [ ] Portfolios — model portfolios with track-record data (read-only)
- [ ] Fact-sheets — list published fact-sheets (executive/institutional), download with language toggle
- [ ] Reports — investment outlooks, flash reports, spotlights (published only)
- [ ] Documents — published documents for investor distribution
- [ ] All `PDFDownload.svelte` components with PT/EN language toggle
- [ ] Visual quality: institutional aesthetic — clean typography, controlled information density

#### Acceptance Criteria

- [ ] INVESTOR sees only published content
- [ ] Fact-sheet download works in both PT and EN
- [ ] Tenant branding (logo, colors, fonts) renders correctly
- [ ] Layout is responsive and meets institutional quality bar
- [ ] This portal is demo-ready as the primary client-facing product

---

### Phase E: Admin Backend APIs

**Goal:** All backend endpoints required by the admin frontend.

**Prerequisite:** Can start after Phase A (does not depend on B/C).

#### E1: Database Migration (0009)

##### Files

```
backend/app/core/db/migrations/versions/0009_admin_infrastructure.py
backend/app/domains/admin/models.py
```

##### Tasks

- [x] Create `tenant_assets` table:
  ```sql
  CREATE TABLE tenant_assets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      organization_id uuid NOT NULL,
      asset_type text NOT NULL,
      content_type text NOT NULL,
      data bytea NOT NULL,
      created_at timestamptz DEFAULT now(),
      updated_at timestamptz DEFAULT now(),
      UNIQUE(organization_id, asset_type)
  );
  ```
  RLS enabled. `asset_type` CHECK: `('logo_light', 'logo_dark', 'favicon')`. 512KB size constraint via application layer.

- [x] Create `prompt_overrides` table:
  ```sql
  CREATE TABLE prompt_overrides (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      organization_id uuid,  -- NULL = global override
      vertical text NOT NULL,
      template_name text NOT NULL,
      content text NOT NULL,
      version integer NOT NULL DEFAULT 1,
      updated_by uuid NOT NULL,
      updated_at timestamptz DEFAULT now(),
      UNIQUE(organization_id, vertical, template_name)
  );
  ```
  RLS enabled for org-specific rows. Global overrides (org_id IS NULL) accessible to admin only.

- [x] Create `prompt_override_versions` history table:
  ```sql
  CREATE TABLE prompt_override_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      prompt_override_id uuid NOT NULL REFERENCES prompt_overrides(id),
      version integer NOT NULL,
      content text NOT NULL,
      updated_by uuid NOT NULL,
      created_at timestamptz DEFAULT now()
  );
  ```

- [x] Add `updated_at` column to `tenant_assets` for ETag computation
- [ ] Expand `config_type` CHECK constraint on `vertical_config_overrides` to include `'branding'` and `'report_styles'`
- [x] Seed default branding config in `vertical_config_defaults` for each vertical

##### Acceptance Criteria

- [ ] `make migrate` applies migration 0009 without error (migration written, needs running DB to apply)
- [x] RLS policies on new tables use subselect pattern
- [x] `make check` passes (ruff + import-linter 16/16 + mypy clean)

#### E2: ConfigService Write Methods

##### Files

```
backend/app/core/config/config_service.py   ← extend
backend/app/core/config/config_writer.py     ← new
backend/app/core/config/pg_notify.py         ← new
```

##### Tasks

- [ ] `config_writer.py` — `ConfigWriter` class with:
  - `async put(vertical, config_type, org_id, config, version)` — upsert override. Validate against guardrails from `VerticalConfigDefault.guardrails` (JSON Schema). Optimistic lock via `version` column (409 if stale). After write: `pg_notify('netz_config_changed', json.dumps({vertical, config_type, org_id}))`
  - `async delete(vertical, config_type, org_id)` — remove override (fall back to default)
  - `async put_default(vertical, config_type, config)` — update global default (super-admin only)
  - `async diff(vertical, config_type, org_id)` — return `{default: {...}, override: {...}, merged: {...}}`
- [ ] `pg_notify.py` — `PgNotifyListener` class:
  - Registers `LISTEN netz_config_changed` on startup (async background task)
  - On notification: invalidate specific TTLCache key `(vertical, config_type, org_id)`
  - Handles connection loss + reconnect
- [ ] Extend `ConfigService` with `invalidate(vertical, config_type, org_id)` method
- [ ] Register `PgNotifyListener` in FastAPI lifespan (`main.py`)

##### Acceptance Criteria

- [ ] Config write triggers `pg_notify`
- [ ] Another API process receives notification and invalidates cache
- [ ] Optimistic locking rejects stale writes (409)
- [ ] Guardrail validation rejects invalid configs (422)
- [ ] `make check` passes

#### E3: PromptService

##### Files

```
backend/app/core/prompts/prompt_service.py    ← new
backend/app/core/prompts/models.py            ← new (ORM for prompt_overrides)
backend/app/core/prompts/schemas.py           ← new
```

##### Tasks

- [ ] `PromptService` with cascade resolution:
  1. `prompt_overrides` WHERE `organization_id = org_id` (org-specific)
  2. `prompt_overrides` WHERE `organization_id IS NULL` (global override)
  3. Filesystem `.j2` via `PromptRegistry` (fallback)
- [ ] `async get(vertical, template_name, org_id)` → returns `{content, source_level, version}`
- [ ] `async put(vertical, template_name, org_id, content, updated_by)` → writes override, bumps version, writes history row
- [ ] `async list(vertical)` → lists all templates with override status per org
- [ ] `async preview(vertical, template_name, content, sample_data)` → render Jinja2 with `SandboxedEnvironment` against sample data
- [ ] `async validate(content)` → parse Jinja2 template, return syntax errors
- [ ] `snapshot_prompts(vertical, org_id, template_names)` → resolve all prompts at job start, return frozen dict (for prompt-snapshot-at-job-start pattern)

##### Acceptance Criteria

- [ ] Cascade resolution works correctly (org override > global override > filesystem)
- [ ] Preview renders template with sample data
- [ ] Validation catches Jinja2 syntax errors
- [ ] Snapshot function returns immutable prompt dict for job use

#### E4: Admin Routes

##### Files

```
backend/app/domains/admin/__init__.py
backend/app/domains/admin/routes/configs.py
backend/app/domains/admin/routes/tenants.py
backend/app/domains/admin/routes/assets.py
backend/app/domains/admin/routes/prompts.py
backend/app/domains/admin/routes/health.py
backend/app/domains/admin/routes/branding.py
```

##### Tasks

- [ ] All admin routes require `is_admin` role check
- [ ] **Config routes** (`/api/v1/admin/configs/`):
  - `POST /` — create config override
  - `PUT /{vertical}/{type}` — update override (with version for optimistic lock)
  - `DELETE /{vertical}/{type}` — remove override
  - `GET /{vertical}/{type}/diff` — show override vs default
  - `POST /defaults/{vertical}/{type}` — update global default
- [ ] **Tenant routes** (`/api/v1/admin/tenants/`):
  - `POST /` — create tenant (Clerk org + seed configs in DB transaction)
  - `GET /` — list all tenants
  - `GET /{org_id}` — tenant detail (configs, assets, usage)
  - `PATCH /{org_id}` — update metadata
  - `POST /{org_id}/seed` — re-seed default configs
- [ ] **Asset routes**:
  - `POST /api/v1/admin/tenants/{org_id}/assets` — upload logo/favicon (multipart, 512KB max)
  - `GET /api/v1/assets/org/{org_id}/{asset_type}` — serve asset (unauthenticated, ETag + `Cache-Control: max-age=86400`, URL includes `?v={md5[:8]}` cache-buster)
  - `DELETE /api/v1/admin/tenants/{org_id}/assets/{type}` — remove asset
- [ ] **Prompt routes** (`/api/v1/admin/prompts/`):
  - `GET /{vertical}` — list all templates with override status
  - `GET /{vertical}/{name}` — get resolved content + source level
  - `PUT /{vertical}/{name}` — update override (auto-version, history)
  - `POST /{vertical}/{name}/preview` — render with sample data
  - `POST /{vertical}/{name}/validate` — Jinja2 syntax check
- [ ] **Health routes** (`/api/v1/admin/health/`):
  - `GET /workers` — worker status (last run, duration, errors from Redis/DB)
  - `GET /pipelines` — pipeline stats (docs processed, queue depth)
  - `GET /usage` — per-tenant usage (API calls, storage, memos generated)
- [ ] **Branding route** (`/api/v1/branding`) — non-admin, returns merged branding for current org. Logo URLs include `?v={hash}` for cache-busting
- [ ] **Content management additions**:
  - Add `unpublish` endpoints where missing (content, report packs): `published → approved`
  - Audit `publish` endpoints exist on all routes that serve investor portals

##### Acceptance Criteria

- [ ] All admin routes require ADMIN role
- [ ] Config writes validate against guardrails
- [ ] Tenant creation seeds all default configs atomically
- [ ] Logo upload enforces 512KB limit and valid content types
- [ ] Asset serve endpoint returns correct ETag and Content-Type
- [ ] Branding endpoint returns merged config for current org
- [ ] `make check` passes (all 416+ tests + new admin tests)

#### E5: Admin Backend Tests

##### Files

```
backend/tests/admin/test_config_writer.py
backend/tests/admin/test_prompt_service.py
backend/tests/admin/test_tenant_routes.py
backend/tests/admin/test_asset_routes.py
backend/tests/admin/test_branding_routes.py
backend/tests/admin/test_pg_notify.py
```

##### Tasks

- [ ] Test config write + guardrail validation + optimistic lock
- [ ] Test prompt cascade resolution (org > global > filesystem)
- [ ] Test prompt preview and validation
- [ ] Test tenant creation atomicity
- [ ] Test asset upload size limit + content type validation
- [ ] Test branding endpoint returns correct merged config
- [ ] Test `pg_notify` triggers cache invalidation

##### Acceptance Criteria

- [ ] All new admin tests pass
- [ ] `make check` passes

---

### Phase F: Admin Frontend

**Goal:** Cross-vertical admin dashboard with tenant management, config editing, prompt management, and system health.

**Prerequisite:** Phase E complete.

#### F1: SvelteKit Scaffold + Auth + Org Switcher

##### Files

```
frontends/admin/package.json
frontends/admin/svelte.config.js
frontends/admin/vite.config.ts
frontends/admin/tsconfig.json
frontends/admin/tailwind.config.ts
frontends/admin/src/app.html
frontends/admin/src/app.css
frontends/admin/src/hooks.server.ts
frontends/admin/src/routes/+layout.server.ts
frontends/admin/src/routes/+layout.svelte
frontends/admin/src/routes/+error.svelte
frontends/admin/src/routes/auth/sign-in/+page.svelte
frontends/admin/src/lib/api/client.ts
frontends/admin/src/lib/components/OrgSwitcher.svelte
frontends/admin/messages/en.json
frontends/admin/messages/pt.json
```

##### Tasks

- [ ] Same scaffold pattern, name: `netz-admin`
- [ ] `hooks.server.ts` — Clerk auth + `is_admin` guard (reject non-admin users entirely)
- [ ] `OrgSwitcher.svelte` — dropdown in header listing all orgs from Clerk. `setActive({ organization: orgId })` on select → re-issues JWT → `invalidateAll()` reloads all data + branding
- [ ] Sidebar: Tenants, Configuration, Prompts, Reports, System Health
- [ ] Add `Makefile` targets: `dev:admin`, `build:admin`

##### Acceptance Criteria

- [ ] Non-admin users redirected to sign-in
- [ ] Org switcher changes active org and reloads all data
- [ ] Branding updates on org switch (CSS vars re-injected)

#### F2: Tenant Manager

##### Files

```
frontends/admin/src/routes/(admin)/tenants/+page.server.ts
frontends/admin/src/routes/(admin)/tenants/+page.svelte
frontends/admin/src/routes/(admin)/tenants/[orgId]/+page.server.ts
frontends/admin/src/routes/(admin)/tenants/[orgId]/+page.svelte
frontends/admin/src/lib/components/TenantManager.svelte
```

##### Tasks

- [ ] Tenant list — `DataTable` with org name, slug, status, config count, asset count
- [ ] Tenant detail — tabs: Overview, Configuration, Assets, Usage
- [ ] Create tenant — form dialog: org name + vertical selection → calls Clerk API + backend seed
- [ ] Asset management — logo upload (drag & drop), preview, delete. Live branding preview panel showing how the tenant's frontend would look
- [ ] Usage stats — API calls, storage, memos generated (from health API)

##### Acceptance Criteria

- [ ] Tenant creation works end-to-end (Clerk + DB seed)
- [ ] Logo upload shows preview immediately
- [ ] Branding preview panel reflects uploaded assets

#### F3: Config Editor

##### Files

```
frontends/admin/src/routes/(admin)/config/+page.server.ts
frontends/admin/src/routes/(admin)/config/+page.svelte
frontends/admin/src/routes/(admin)/config/[vertical]/[type]/+page.server.ts
frontends/admin/src/routes/(admin)/config/[vertical]/[type]/+page.svelte
frontends/admin/src/lib/components/ConfigEditor.svelte
frontends/admin/src/lib/components/ConfigDiffViewer.svelte
```

##### Tasks

- [ ] Config list — grouped by vertical, showing override status per config_type
- [ ] Config editor — JSON form driven by config schema. Shows current values (merged), default values (dimmed), override indicator
- [ ] Diff viewer — side-by-side default vs override with highlighted differences
- [ ] Branding editor — visual: color pickers, font selector (curated list), logo references. Live preview panel
- [ ] Report styles editor — form with options per report type (fact-sheet format, chart palette, margins, etc.)
- [ ] Guardrail validation — client-side validation matching backend JSON Schema
- [ ] Optimistic lock — shows warning if another admin changed the config since you loaded it

##### Acceptance Criteria

- [ ] Config edits save and trigger cache invalidation
- [ ] Branding editor shows live preview
- [ ] Guardrail validation prevents invalid saves
- [ ] Stale version shows conflict warning (409)

#### F4: Prompt Editor

##### Files

```
frontends/admin/src/routes/(admin)/prompts/+page.server.ts
frontends/admin/src/routes/(admin)/prompts/+page.svelte
frontends/admin/src/routes/(admin)/prompts/[vertical]/[name]/+page.server.ts
frontends/admin/src/routes/(admin)/prompts/[vertical]/[name]/+page.svelte
frontends/admin/src/lib/components/PromptEditor.svelte
```

##### Tasks

- [ ] Prompt list — grouped by vertical, showing template name, description (from metadata), override status, source level (org/global/filesystem)
- [ ] `PromptEditor.svelte` — split pane:
  - Left: Monaco editor (or CodeMirror) with Jinja2 syntax highlighting
  - Right: live preview panel (calls `/preview` endpoint on debounced keystrokes, 500ms delay)
- [ ] Syntax validation indicator (green/red dot) via `/validate` endpoint
- [ ] Source level indicator: "Editing org override" / "Editing global override" / "Viewing filesystem template (read-only)"
- [ ] Save: auto-bumps version, writes history
- [ ] Revert button: delete override → falls back to next cascade level
- [ ] Version history dropdown: view previous versions (from `prompt_override_versions`)

##### Acceptance Criteria

- [ ] Monaco/CodeMirror renders with Jinja2 highlighting
- [ ] Live preview updates on keystroke (debounced)
- [ ] Syntax errors shown inline
- [ ] Version history accessible and previous versions viewable
- [ ] Revert correctly falls back to next cascade level

#### F5: System Health Dashboard

##### Files

```
frontends/admin/src/routes/(admin)/health/+page.server.ts
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/lib/components/WorkerHealthGrid.svelte
```

##### Tasks

- [ ] Worker health grid — cards per worker (name, last run, duration, status badge, error count)
- [ ] Pipeline stats — documents processed, queue depth, error rate
- [ ] Per-tenant usage — `DataTable` with org name, API calls, storage, memos
- [ ] SSE connection for live worker heartbeats (if backend emits them)
- [ ] Auto-refresh: health data polls every 30s

##### Acceptance Criteria

- [ ] Worker status cards show correct last-run time
- [ ] Pipeline stats render with real data
- [ ] Usage table sortable by any metric

#### F6: Admin E2E Tests

##### Files

```
frontends/admin/tests/e2e/auth.spec.ts
frontends/admin/tests/e2e/config.spec.ts
frontends/admin/tests/e2e/prompts.spec.ts
```

##### Tasks

- [ ] Auth: non-admin rejected, admin sees dashboard
- [ ] Config: edit branding → save → preview updates
- [ ] Prompts: edit prompt → preview renders → save → version history shows

##### Acceptance Criteria

- [ ] E2E tests pass against running backend

---

## System-Wide Impact

### Interaction Graph

```
Admin saves branding → PUT /admin/configs → DB write → pg_notify
  → ConfigService cache invalidation (all API processes)
  → Next GET /branding returns new values
  → Frontend SSR re-renders with new CSS vars
  → PDF generation picks up new styles via token_generator.py
```

```
Admin saves prompt → PUT /admin/prompts → prompt_overrides DB write + history
  → Next IC memo/DD report generation resolves new prompt
  → Active jobs use snapshot (unaffected)
  → New jobs get updated prompt
```

### Error Propagation

- Frontend SSR fails → `+error.svelte` renders `BackendUnavailable`
- API returns 401 → redirect to `/auth/sign-in`
- API returns 403 → show forbidden message
- SSE connection fails after 5 retries → `ConnectionLost` banner stays visible
- PDF generation fails → API returns 500, frontend shows inline error with retry

### State Lifecycle Risks

- **Config write during active request:** Acceptable — eventual consistency with TTL ≤ 60s. `pg_notify` reduces to milliseconds for cache, but in-flight requests are unaffected.
- **Prompt change during active generation:** Mitigated by snapshot-at-job-start pattern.
- **Logo change during cached period:** Mitigated by `?v={hash}` cache-buster in branding config.
- **Tenant creation partial failure:** Mitigated by DB transaction for seed. Clerk org creation is the only external call — if DB seed fails, admin retries via `/seed` endpoint.

### API Surface Parity

All three frontends consume the same `@netz/ui` components and utilities. The investor portals in credit and wealth have feature parity (published content, PDF download, language toggle, tenant branding). The admin panel is the sole location for cross-vertical configuration.

---

## Acceptance Criteria

### Functional Requirements

- [ ] All ~95 existing backend endpoints consumed by appropriate frontend
- [ ] Credit team can: manage deals, generate IC memos with SSE streaming, upload/review documents, view portfolio, generate reports
- [ ] Wealth team can: monitor portfolios, manage allocations, view risk in real-time, run analytics, generate DD reports and content
- [ ] Investors can: view published content and download PDFs in PT or EN
- [ ] Admins can: manage tenants, edit configs/branding/prompts/report styles, monitor system health

### Non-Functional Requirements

- [ ] WCAG 2.1 AA compliance on all frontends (contrast, keyboard nav, labels)
- [ ] Responsive at 4 breakpoints (>1280, 1024, 768, <600px)
- [ ] Virtual scrolling handles 500+ row tables without jank
- [ ] SSE reconnection works with exponential backoff
- [ ] Frontend builds produce adapter-node output for Azure Container Apps
- [ ] TypeScript strict mode with zero errors across all frontends

### Quality Gates

- [ ] @netz/ui component tests pass (vitest + @testing-library/svelte)
- [ ] Integration tests pass per frontend (vitest + MSW)
- [ ] E2E tests pass per frontend (Playwright against docker-compose)
- [ ] `make check` passes (backend lint + typecheck + test)
- [ ] `make check:frontends` passes (svelte-check + vitest per frontend)
- [ ] No TypeScript `any` types in production code

## Dependencies & Prerequisites

- **Phase A blocks B, B+, C, C+, F** — all frontends depend on @netz/ui
- **Phase A.5 (branding route) blocks B** — `+layout.server.ts` calls `GET /api/v1/branding` which must exist before Phase B starts
- **Phase E (remaining admin APIs) can run in parallel with B/C** — admin backend is independent of frontend work
- **Phase F requires Phase E** — admin frontend needs admin APIs
- **pnpm ≥ 9.0** — workspace protocol support
- **Node.js ≥ 20** — SvelteKit 2 requirement
- **Turborepo** — for cross-package build orchestration with caching
- **Backend running** — for type generation (`make types`) and E2E tests. Cache `openapi.json` in repo to decouple frontend dev from running backend.

### Revised Phase Ordering (from architecture review)

```
Phase A   → @netz/ui foundation
Phase A.5 → Migration 0009 (tenant_assets, prompt_overrides tables)
            + GET /api/v1/branding endpoint
            + GET /api/v1/assets/tenant/{org_slug}/{asset_type} endpoint
            + CORS configuration on FastAPI backend
Phase B   → Credit team frontend
Phase B+  → Credit investor portal
Phase C   → Wealth team frontend (can overlap with E2-E5)
Phase E   → Remaining admin backend APIs (config write, tenant CRUD, prompts, health)
Phase C+  → Wealth investor portal
Phase F   → Admin frontend
```

This ensures the branding endpoint exists before Phase B needs it, and allows Phase E to overlap with Phase C.

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SVG XSS via tenant logo upload | High | Critical | Reject SVG entirely. Accept PNG/JPEG/ICO only. CSP headers on asset endpoint |
| SSTI via prompt editor | Medium | High | `AdminSandboxedEnvironment` with dunder blocking + filter whitelist + render timeout |
| Clerk SvelteKit SDK gaps | Medium | Medium | Use `svelte-clerk` (wobsoriano). Svelte 5 compatible. `invalidateAll()` after org switch |
| ECharts bundle size (~1MB) | High | High | Modular `echarts/core` imports → ~300KB. Dynamic import chart wrappers |
| Fund universe data transfer (500+ rows) | Medium | Medium | Server-side pagination (50/page) with opt-in "load all" |
| SSR branding API call overhead | Medium | Medium | 30s in-process TTL cache in SvelteKit server |
| pg_notify listener on pooled connection | Medium | High | Dedicated `asyncpg.connect()` outside pool. Health check every 30s. Reconnect with backoff |
| Cross-frontend CORS | High | High | Configure FastAPI CORS middleware for all 3 frontend origins |
| 18 duplicated scaffold files | Medium | Medium | Extract `createClerkHook()` + `RootLayout.svelte` to @netz/ui |
| Non-fatal error UX (422/409) | Medium | Low | Add `Toast` component to @netz/ui for transient errors |
| SSE event gap on reconnect | Medium | Medium | Subscribe-then-snapshot ordering (SSE first, then REST, then merge) |
| Satellite domains not supported | Low | Medium | Deploy all 3 frontends same-origin (path-based routing) for shared Clerk session |

## Research Insights by Phase

### Phase A: Research Insights

**Clerk Integration (use `svelte-clerk`, not `clerk-sveltekit`):**
- Package `svelte-clerk` by wobsoriano is the active, Svelte 5-compatible package
- `clerk-sveltekit` by markjaquith is deprecated (Svelte 4 only)
- `withClerkHandler()` in `hooks.server.ts` handles JWT verification + JWKS caching
- `buildClerkProps(locals.auth())` in `+layout.server.ts` passes auth state to client
- `invalidateAll()` is REQUIRED after org switch via `setActive()`
- All 3 frontends can share Clerk session if deployed same-origin (path-based routing)

**Branding injection via `transformPageChunk`:**
```typescript
// hooks.server.ts — inject CSS vars on <html> during SSR
const response = await resolve(event, {
  transformPageChunk: ({ html }) =>
    html.replace('<html', `<html style="${brandingCssVars}"`),
});
```
This is more efficient than per-route injection in `+layout.server.ts` because it runs once per response at the HTML level.

**ECharts modular imports (MANDATORY):**
```typescript
// echarts-setup.ts — tree-shakeable registration
import * as echarts from 'echarts/core';
import { LineChart, BarChart, ScatterChart, GaugeChart, FunnelChart, HeatmapChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([LineChart, BarChart, ScatterChart, GaugeChart, FunnelChart, HeatmapChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);
```
Reduces bundle from ~1MB to ~300KB gzipped.

**Component API consistency — add `BaseChartProps`:**
```typescript
interface BaseChartProps {
  class?: string;
  height?: number;
  palette?: string[];
  loading?: boolean;
  empty?: boolean;
  emptyMessage?: string;
  optionsOverride?: Partial<EChartsOption>; // escape hatch
}
```
All 8 chart wrappers extend this. `ChartContainer` is an internal implementation detail.

**SSE client — subscribe-then-snapshot ordering:**
1. Connect SSE first (start receiving events into a buffer)
2. Call REST endpoint to get current state
3. Merge: REST state is the base, SSE buffer contains any events that occurred during the REST call
4. Continue with live SSE tail

**Additional @netz/ui components needed (from pattern review):**
- `Toast.svelte` — non-fatal error notifications (422, 409, transient 500s)
- `PageTabs.svelte` — wraps `Tabs` with URL query sync (`?tab=assets`) and per-tab loading
- Shared Tailwind preset exported from `@netz/ui` (all 3 frontends extend, not duplicate)
- `createClerkHook(options)` — factory for `hooks.server.ts` handler
- `createRootLayoutLoader(options)` — factory for root `+layout.server.ts`
- `RootLayout.svelte` — shared root layout with branding injection + error boundary

**Font loading:**
- Self-host Inter via `@fontsource/inter` (variable font, ~300KB woff2)
- `font-display: swap` to prevent FOIT
- Preload primary weight: `<link rel="preload" href="/fonts/inter-var.woff2" ...>`
- Avoids Google Fonts GDPR concerns for EU institutional clients

### Phase E: Research Insights

**Security hardening for admin API:**

1. **Reject SVG uploads entirely.** Accept only: `image/png`, `image/jpeg`, `image/x-icon`, `image/vnd.microsoft.icon`. Validate via magic bytes (not Content-Type header).
2. **Use `org_slug` in asset URLs** instead of `org_id`: `GET /api/v1/assets/tenant/{org_slug}/{asset_type}`. Return default Netz logo for unknown slugs (never 404). Rate-limit 10 req/s per IP.
3. **Add CSP + XCTO headers** on asset-serving endpoint: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'` and `X-Content-Type-Options: nosniff`.
4. **Hardened Jinja2 sandbox** for admin-edited prompts: `AdminSandboxedEnvironment` that blocks `__` attribute access, restricts filters to whitelist, and adds render timeout (5s).
5. **Validate branding values** with strict regex: hex colors (`^#[0-9a-fA-F]{6}$`), font names from curated list only, no CSS injection possible.
6. **Branding endpoint response** should return only computed rendering values (`BrandingResponse` with `extra="forbid"`), never internal config structure.
7. **Config write atomicity:** use `UPDATE...WHERE version = :expected` (atomic). Never read-then-write (TOCTOU race).

**pg_notify implementation:**
- Dedicated `asyncpg.connect()` connection (NOT from pool) for LISTEN
- `PgNotifyListener` class with exponential backoff reconnect (1s → 30s cap)
- Health check every 30s (`SELECT 1`) to detect dead TCP connections
- Trigger function on `vertical_config_overrides` table fires `pg_notify()` automatically
- Notification is transactional — only delivered after commit
- Payload format: `{vertical, config_type, org_id}` (under 8KB limit)
- Register in FastAPI lifespan (start on startup, stop on shutdown)

**`token_generator.py` pattern (BrandingTokens class):**
- `BrandingTokens.from_config(branding_config)` converts JSONB to ReportLab styles
- Font mapping: branding font name → registered ReportLab font name (with Helvetica fallback)
- Color resolution: `_hex_to_color()` with Netz defaults as fallback
- 9 pre-built ParagraphStyles (cover_title, section_heading, body, table_header, etc.)
- Chart palette from `report_styles.fact_sheet.chart_palette` (same values as frontend ECharts theme)

## Documentation Plan

- Update CLAUDE.md: add frontend Makefile targets, pnpm workspace docs, frontend test conventions
- Update CLAUDE.md: add migration head after 0009
- Update CLAUDE.md: add `svelte-clerk` as the Clerk SvelteKit package (not `clerk-sveltekit`)
- README per frontend with dev setup instructions
- Document CORS configuration for multi-frontend deployment

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-16-feat-frontend-admin-platform-brainstorm.md](../brainstorms/2026-03-16-feat-frontend-admin-platform-brainstorm.md) — Key decisions: 3 separate frontends, TanStack Table + 8 ECharts wrappers, ReportLab (not WeasyPrint), REST + SSE tail pattern, pg_notify for cache invalidation, prompt_overrides table with 3-level cascade, PostgreSQL bytea for logos, 6 curated fonts, adapter-node for SSR

### Internal References

- ConfigService (read-only): `backend/app/core/config/config_service.py`
- PDF base: `backend/ai_engine/pdf/pdf_base.py` (682 lines, ReportLab)
- Fact sheet engine: `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py`
- Prompt registry: `backend/ai_engine/prompts/registry.py`
- SSE tracker: `backend/app/core/jobs/tracker.py`
- Clerk auth: `backend/app/core/security/clerk_auth.py`
- Migration patterns: `backend/app/core/db/migrations/versions/0008_wealth_analytical_models.py`

### External References

- SvelteKit: https://kit.svelte.dev/docs
- shadcn-svelte: https://shadcn-svelte.com
- TanStack Table Svelte: https://tanstack.com/table/latest/docs/framework/svelte
- paraglide-js: https://inlang.com/m/gerre34r/library-inlang-paraglideJs
- ECharts modular imports: https://echarts.apache.org/handbook/en/basics/import
- svelte-clerk: https://github.com/wobsoriano/svelte-clerk (Svelte 5 compatible)
- svelte-clerk docs: https://svelte-clerk.netlify.app/kit/quickstart.html
- asyncpg LISTEN/NOTIFY: https://magicstack.github.io/asyncpg/current/api/index.html
- PostgreSQL NOTIFY: https://www.postgresql.org/docs/current/sql-notify.html

### Institutional Learnings Applied

- Pydantic strictness: `extra="ignore"` on all admin schemas (from `docs/solutions/architecture-patterns/pydantic-migration-review-findings-PolicyThresholds-20260316.md`)
- RLS subselect: all new tables use `(SELECT current_setting(...))` (from `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md`)
- Organization ID in all search: new admin search features must include org_id filter (from `docs/solutions/security-issues/azure-search-tenant-isolation-organization-id-filtering-20260315.md`)

### Deepening Research (10 agents, 2026-03-16)

- Security sentinel: 8 findings (1 critical SVG XSS, 3 high — IDOR/SSTI/role bypass, 1 medium CSS injection, 3 low)
- Architecture strategist: Phase ordering fix (A.5), Turborepo, CORS, pg_notify dedicated connection
- Performance oracle: 3 critical (branding cache, ECharts bundle, fund pagination), 4 optimizations
- Pattern recognition: 13 recommendations (scaffold extraction, BaseChartProps, Toast, PageTabs, breadcrumbs)
- Clerk auth research: `svelte-clerk` (not deprecated `clerk-sveltekit`), `withClerkHandler`, org switch patterns
- pg_notify + branding: PgNotifyListener code, BrandingTokens class, transformPageChunk injection
- SvelteKit best practices: adapter-node config, SSR patterns, pnpm workspace setup
- shadcn-svelte + TanStack: component packaging, DataTable wrapper, ECharts integration
- SSE patterns: subscribe-then-snapshot, connection management, Svelte 5 lifecycle
- Monaco/CodeMirror: editor comparison for Jinja2 prompt editing
