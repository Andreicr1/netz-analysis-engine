# Frontend Architecture Reference

> Authoritative inventory of the Netz Analysis Engine frontend platform.
> Last updated: 2026-04-05 (post Admin Frontend retirement, Phases 1-6 complete).

---

## 1. Monorepo Structure

```
netz-analysis-engine/
  packages/
    ui/                  @netz/ui           — Credit design system (Netz tokens)
    investintell-ui/     @investintell/ui   — Wealth design system (InvestIntell tokens)
  frontends/
    wealth/              netz-wealth-os     — Wealth OS SvelteKit app
    credit/              netz-credit-intelligence — Credit Intelligence SvelteKit app
```

**Workspace:** `pnpm-workspace.yaml` includes `"packages/*"` and `"frontends/*"`.
**Build orchestration:** Turborepo v2 (`turbo.json`) — `build` and `check` depend on `^build` (topological).
**Package manager:** pnpm 10.28.1.

### Dependency Graph

```
netz-wealth-os ───depends on──→ @investintell/ui
                                     │
                                     ├── tokens (--ii-*)
                                     ├── globals (Urbanist font, dark-first)
                                     └── components (analytical/ directory)

netz-credit-intelligence ──depends on──→ @netz/ui
                                             │
                                             ├── tokens (--netz-*)
                                             ├── index.css (IBM Plex Sans, light-first)
                                             └── components (admin/ directory)
```

**Cross-import rule:** Wealth never imports `@netz/ui` components directly. Credit never imports `@investintell/ui`. Both share backend API endpoints. Admin components exist in both packages with token-compatible variants.

---

## 2. Design System — Dual Token Architecture

Two independent design systems coexist. They share structural patterns but differ in palette, typography, and default theme.

### @netz/ui (Credit)

| Aspect | Value |
|--------|-------|
| Token prefix | `--netz-*` |
| Default theme | Light (`:root { color-scheme: light; }`) |
| Dark mode | `[data-theme="dark"]` |
| Font sans | IBM Plex Sans |
| Font mono | IBM Plex Mono |
| Primary color | `#0077e6` (institutional blue) |
| Design inspiration | Thunder Client documentation |

### @investintell/ui (Wealth)

| Aspect | Value |
|--------|-------|
| Token prefix | `--ii-*` |
| Default theme | Dark (`:root { color-scheme: dark; }`) |
| Light mode | `.light` or `[data-theme="light"]` |
| Font sans | Urbanist |
| Font mono | Geist Mono |
| Primary color | `#0177fb` (One X accent blue) |
| Design inspiration | One X Investment Dashboard |

### Shared Theme Bridge

`packages/ui/src/lib/styles/investintell-theme.css` re-exports all `--netz-*` tokens (tokens, typography, spacing, shadows, animations). This file is imported by Wealth's `app.css` so that `@netz/ui` admin components (which use `--netz-*` variables) render correctly inside the Wealth context.

```
Wealth app.css:
  @import "@investintell/ui/styles";                          ← --ii-* tokens
  @import "../../../packages/ui/src/lib/styles/investintell-theme.css";  ← --netz-* tokens
  @import "tailwindcss";

Credit app.css:
  @import "@netz/ui/investintell-theme";   ← --netz-* tokens (canonical)
  @import "tailwindcss";
```

### CSS Files Inventory

**@netz/ui** (`packages/ui/src/lib/styles/`):

| File | Purpose |
|------|---------|
| `index.css` | Entry point — imports all below + global reset |
| `investintell-theme.css` | Re-export layer for cross-frontend use |
| `tokens.css` | Color, surface, border, semantic, chart tokens (light `:root` + dark `[data-theme="dark"]`) |
| `typography.css` | Font scale, weights, line-heights, letter-spacing (IBM Plex imports) |
| `spacing.css` | Raw scale (`--netz-space-1` through `--netz-space-16`) + semantic rhythm |
| `shadows.css` | 5-level elevation system + inset/focus/card/floating (light + dark) |
| `animations.css` | Keyframe animations |

**@investintell/ui** (`packages/investintell-ui/src/lib/styles/`):

| File | Purpose |
|------|---------|
| `globals.css` | Entry point — imports all below + global reset + scrollbar theming |
| `tokens.css` | Color, surface, border, semantic, chart, glass/blur, shadcn bridge tokens (dark `:root` + light `.light`/`[data-theme="light"]`) |
| `typography.css` | Font scale (Urbanist imports) |
| `spacing.css` | Spacing tokens |
| `shadows.css` | Elevation system |
| `animations.css` | Keyframe animations |

### Token Mapping (structural equivalence)

| Concept | @netz/ui | @investintell/ui |
|---------|----------|------------------|
| Primary brand | `--netz-brand-primary` | `--ii-brand-primary` |
| Text primary | `--netz-text-primary` | `--ii-text-primary` |
| Text secondary | `--netz-text-secondary` | `--ii-text-secondary` |
| Text muted | `--netz-text-muted` | `--ii-text-muted` |
| Surface | `--netz-surface` | `--ii-surface` |
| Surface alt | `--netz-surface-alt` | `--ii-surface-alt` |
| Surface elevated | `--netz-surface-elevated` | `--ii-surface-elevated` |
| Border | `--netz-border` | `--ii-border` |
| Border subtle | `--netz-border-subtle` | `--ii-border-subtle` |
| Border focus | `--netz-border-focus` | `--ii-border-focus` |
| Success | `--netz-success` | `--ii-success` |
| Warning | `--netz-warning` | `--ii-warning` |
| Danger | `--netz-danger` | `--ii-danger` |
| Info | `--netz-info` | `--ii-info` |
| Font sans | `--netz-font-sans` | `--ii-font-sans` |
| Font mono | `--netz-font-mono` | `--ii-font-mono` |

Domain-semantic aliases are identical in both: `--desk-surface`, `--desk-elevated`, `--ink-primary`, `--ink-secondary`, `--ticker-mono`, `--regime-ok`, `--regime-caution`, `--regime-stress`.

---

## 3. UI Package Exports

### @netz/ui — 77 exports

**Package exports** (`package.json`):

| Export path | Target |
|-------------|--------|
| `"."` | `./dist/index.js` (components + utilities) |
| `"./styles"` | `./src/lib/styles/index.css` |
| `"./investintell-theme"` | `./src/lib/styles/investintell-theme.css` |
| `"./charts"` | `./dist/charts/index.js` |
| `"./charts/echarts-setup"` | `./dist/charts/echarts-setup.js` |
| `"./utils"` | `./dist/utils/index.js` |

**Components (53):**

Base: Button, Card, Badge, Dialog, Sheet, Tabs, Input, Select, Textarea, Tooltip, DropdownMenu, Skeleton, AlertBanner.

Data: DataTable, DataTableToolbar.

Mutation: ConfirmDialog, ActionButton, FormField, ConsequenceDialog, AuditTrailPanel.

Composites: DataCard, StatusBadge, EmptyState, PDFDownload, ThemeToggle, LanguageToggle, ErrorBoundary, ConnectionLost, BackendUnavailable, Toast, PageTabs, MetricCard, UtilizationBar, RegimeBanner, AlertFeed, SectionCard, HeatmapTable, PeriodSelector, EntityContextHeader, LongRunningAction.

Admin (migrated from retired admin frontend): ConfigEditor, ConfigDiffView, ServiceHealthCard, WorkerLogFeed, CodeEditor.

Layout: AppLayout, AppShell, Sidebar, TopNav, ContextSidebar, ContextPanel, InvestorShell, PageHeader.

Charts (via `@netz/ui/charts`): ChartContainer, TimeSeriesChart, RegimeChart, GaugeChart, BarChart, FunnelChart, HeatmapChart, ScatterChart.

**Utilities (via `@netz/ui/utils`):** NetzApiClient, createServerApiClient, createClientApiClient, createSSEStream, createPoller, formatNumber, formatCurrency, formatPercent, formatDate, formatDateTime, formatShortDate, resolveAdminStatus, branding utilities, auth functions.

### @investintell/ui — 72 exports

Mirrors @netz/ui with token-compatible analytical components. Additionally includes: Combobox, DatePicker, SimpleDialog, SimpleSelect. Components use `--ii-*` tokens internally.

---

## 4. Admin Components (Migrated)

Origin: `frontends/admin/` (retired, directory deleted).
Destination: `packages/ui/src/lib/components/admin/` (5 files).
Also mirrored in: `packages/investintell-ui/src/lib/components/analytical/`.

| Component | Props | API Endpoints | Notes |
|-----------|-------|---------------|-------|
| `ConfigEditor` | `vertical`, `configType`, `token`, `apiBaseUrl`, `orgId?`, `tenantName?` | `GET/PUT/DELETE /admin/configs/{v}/{ct}`, `PUT /admin/configs/defaults/{v}/{ct}`, `GET /admin/audit` | CodeMirror JSON editor, consequence-aware save, diff view, audit trail, optimistic locking (If-Match + 409 handling) |
| `ConfigDiffView` | `diff: ConfigDiffOut` | None (receives data) | CodeMirror merge view (split/unified), dynamic theme from CSS variables |
| `ServiceHealthCard` | `service: { name, status, latency_ms, error, checked_at }` | None (receives data) | Status badge with derived severity, latency display |
| `WorkerLogFeed` | `token`, `apiBaseUrl` | `GET /admin/health/workers/logs` (SSE) | Live SSE stream, severity filtering, search, auto-scroll, 100-line buffer |
| `CodeEditor` | `value` (bindable), `schema`, `ariaLabel` | None | CodeMirror JSON editor with linting, used by ConfigEditor |

**SSE pattern:** WorkerLogFeed uses `createSSEStream()` (fetch + ReadableStream), NOT EventSource. Auth headers are injected via token prop.

**Token compatibility:** In `@netz/ui`, components use `--netz-*` variables. In `@investintell/ui`, the analytical variants use `--ii-*` variables.

---

## 5. Route Architecture

### Wealth (39 route directories)

```
frontends/wealth/src/routes/
  +layout.server.ts          Root — Clerk auth, actor, token, branding
  (app)/
    +layout.svelte           Sidebar (300px) + TopNav (88px) + content panel
    dashboard/               Landing page
    screener/                Fund screening + analytics
      +page.svelte           Catalog table (mv_unified_funds)
      analytics/             Screening analytics
      dd-reports/            DD report viewer
        [fundId]/
          [reportId]/
      fund/
        [id]/                Fund factsheet + detail
      runs/
        [runId]/             Screening run results
    portfolio/
      approved/              Approved instruments
      builder/               Portfolio builder
      models/                Model portfolios
        [portfolioId]/
        create/
      policy/                Policy benchmark
    portfolios/
      [profile]/             Risk profile view
    analysis/                Quant analysis lab
      [entityId]/
      entity-analytics/
      exposure/
      lab/
      risk/
    market/                  Macro dashboard
      reviews/
        [reviewId]/
    documents/               Document management
      [documentId]/
      upload/
    content/                 Content viewer
      [id]/
    settings/                Settings (migrated from admin)
      +layout.svelte         Tab nav: Config | System
      +page.svelte           Redirect to /settings/config
      config/
        +page.server.ts      Loads liquid_funds configs
        +page.svelte         ConfigEditor (vertical=liquid_funds)
      system/
        +page.server.ts      Loads services, workers, pipelines
        +page.svelte         ServiceHealthCard grid + DataTable + WorkerLogFeed
  auth/
    callback/                Clerk callback
```

**Wealth navigation:** Sidebar with 5 main items (Dashboard, Screener, Portfolio, Analysis, Market) + System section (Settings). Logo at sidebar bottom. TopNav has search pill ("Ask InvestIntell anything"), notifications, AI agent drawer, user avatar.

**Wealth worker triggers (14):** instrument_ingestion, macro_ingestion, benchmark_ingest, risk_calc, portfolio_eval, screening_batch, watchlist_check, portfolio_nav_synthesizer, wealth_embedding, sec_13f_ingestion, sec_adv_ingestion, nport_ingestion, esma_ingestion, regime_fit.

### Credit (28 route directories)

```
frontends/credit/src/routes/
  +layout.server.ts          Root — Clerk auth, actor, token, branding
  +layout.svelte             AppLayout with credit nav items
  (investor)/                Role guard: investor + advisor only
    +layout.svelte           InvestorShell wrapper
    +layout.server.ts        Role validation
    documents/
    report-packs/
    statements/
  (team)/                    Role guard: non-investor roles
    +layout.svelte           Pass-through
    +layout.server.ts        Role validation
    copilot/                 Fund Copilot RAG
    dashboard/               Credit dashboard
    funds/
      [fundId]/
        +layout.svelte       Fund context layout
        +layout.server.ts    Fund data loader
        documents/
          [documentId]/
          auditor/
          dataroom/
          reviews/
            [reviewId]/
          upload/
        market-data/
        pipeline/
          [dealId]/
        portfolio/
        reporting/
    settings/                Settings (migrated from admin)
      +layout.svelte         Tab nav: Config | System
      +page.svelte           Redirect to /settings/config
      config/
        +page.server.ts      Loads private_credit configs
        +page.svelte         ConfigEditor (vertical=private_credit)
      system/
        +page.server.ts      Loads services, workers, pipelines
        +page.svelte         ServiceHealthCard grid + DataTable + WorkerLogFeed
  auth/
    sign-in/
    sign-out/
```

**Credit navigation:** AppLayout wrapper with 4 items (Dashboard, Funds, Copilot, Settings). Uses `initContextNav()` for entity-level context navigation inside fund routes.

**Credit role guards:** `(investor)` group allows `["investor", "advisor"]`. `(team)` group rejects investor role. 403 on unauthorized.

**Credit worker triggers (3):** macro_ingestion, treasury_ingestion, ofr_ingestion (all global scope).

---

## 6. Settings Routes Detail

Both frontends have identical settings structure, migrated from the retired admin frontend.

### /settings/config

**Server load (`+page.server.ts`):**
1. `GET /admin/configs/` — all config types
2. `GET /admin/configs/invalid` — configs with validation errors
3. Filters by vertical (`liquid_funds` for Wealth, `private_credit` for Credit)
4. Uses `Promise.allSettled` — partial failures don't crash

**Client page (`+page.svelte`):**
- Invalid overrides warning section (error badges)
- Config type list with override status badges (Default/Override)
- Inline ConfigEditor panel when a config type is selected
- API base from `VITE_API_BASE_URL` (defaults to `http://localhost:8000/api/v1`)

### /settings/system

**Server load (`+page.server.ts`):**
1. `GET /admin/health/services` — service health array
2. `GET /admin/health/workers` — worker status array
3. `GET /admin/health/pipelines` — pipeline stats (docs_processed, queue_depth, error_rate)
4. Computes `hasDegradedState` from errors or non-ok services

**Client page (`+page.svelte`):**
- Degraded state banner (yellow alert)
- Service health grid (ServiceHealthCard components, 4-col responsive)
- Pipeline stats (3 MetricCards: docs processed, queue depth, error rate)
- Worker status table (DataTable with expandable rows, status filter)
- Worker trigger controls (confirm dialog, "Run Now" button per worker)
- WorkerLogFeed (live SSE stream)
- Auto-refresh every 30 seconds via `$effect` + `setInterval`
- Toast notifications for trigger feedback

---

## 7. Auth Architecture

Both frontends use Clerk JWT v2 for authentication.

| Aspect | Wealth | Credit |
|--------|--------|--------|
| Root layout | `+layout.server.ts` loads `actor`, `token`, `branding` | Same |
| Branding | Fixed `defaultDarkBranding` (no API call) | Dynamic via `GET /api/v1/branding?vertical=credit` |
| Role normalization | Strips `org:` prefix from Clerk roles | Same |
| API client factory | `createServerApiClient(token)` for SSR, `createClientApiClient(getToken)` for client | Same |
| Role guards | None at route level (Clerk handles) | Multi-level: `(investor)` and `(team)` groups |
| Session management | Context: `netz:getToken` | Context: `netz:getToken` |

---

## 8. API Client Pattern

Both frontends wrap `@netz/ui/utils` (or `@investintell/ui/utils`) API client factories.

**Server-side** (`+page.server.ts`):
```typescript
import { createServerApiClient } from "$lib/api/client";
const api = createServerApiClient(locals.token);
const data = await api.get("/admin/configs/");
```

**Client-side** (components):
```typescript
import { createClientApiClient } from "$lib/api/client";
const api = createClientApiClient(() => Promise.resolve(data.token));
await api.post("/workers/run-macro-ingestion", {});
```

Base URL: `VITE_API_BASE_URL` env var, defaults to `http://localhost:8000/api/v1`.

Error handling: AuthError (401), ForbiddenError (403), ConflictError (409), ValidationError (422), ServerError (5xx). Single-flight 401 redirect gate prevents duplicate navigations.

---

## 9. Admin Frontend Retirement Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Migrate components to @netz/ui | COMPLETE | 5 components in `packages/ui/src/lib/components/admin/` |
| 2. Wealth /settings routes | COMPLETE | 6 files, liquid_funds vertical, 14 worker triggers |
| 3. Credit /settings routes | COMPLETE | 6 files, private_credit vertical, 3 worker triggers |
| 4. Navigation links | COMPLETE | Wealth: sidebar System section. Credit: navItems array |
| 5. CSS unification | COMPLETE | `investintell-theme.css` bridges --netz-* tokens into Wealth |
| 6. Delete admin frontend | COMPLETE | `frontends/admin/` removed, no stale references |
| 7. Backend prompt cleanup | PENDING | Out of scope for frontend migration |

### What was NOT migrated (by design)

- `BrandingEditor` — branding is InvestIntell, no per-tenant customization
- `PromptEditor` / `JinjaEditor` — prompts are core IP, no override UI
- Tenant CRUD UI — managed 100% via Clerk Dashboard
- `/inspect` route — debugging-only, no production value

### Stale references removed

- No `--filter admin` in any script
- No admin entry in `turbo.json` or `pnpm-workspace.yaml` (wildcards handle)
- No admin reference in `Makefile`

---

## 10. Build and Check Status

| Package | svelte-check | build | Notes |
|---------|-------------|-------|-------|
| @netz/ui | 0 errors, 1 warning | OK | Warning: `apiBaseUrl` capture in ConfigEditor (cosmetic) |
| @investintell/ui | 8 errors | OK | Pre-existing: spinner type union, chart config types |
| netz-wealth-os | 0 errors, 23 warnings | OK | Pre-existing: a11y labels, state_referenced_locally |
| netz-credit-intelligence | 0 errors, 0 warnings | OK | Clean |

**Build command:** `npx turbo run build --filter=netz-wealth-os --filter=netz-credit-intelligence`
**Check command:** `npx turbo run check --filter=@netz/ui --filter=netz-wealth-os --filter=netz-credit-intelligence`

---

## 11. Known Technical Debt

1. **Dual token prefix** (`--ii-*` vs `--netz-*`): Both coexist. Unification would require rewriting all Wealth components. The `investintell-theme.css` bridge ensures admin components work across frontends.

2. **@investintell/ui type errors**: 8 pre-existing svelte-check errors (spinner Loader2Icon union type, chart config item undefined). Build succeeds despite check errors.

3. **@tanstack/svelte-table version split**: Wealth uses `9.0.0-alpha.10` (pre-release), Credit uses `^8.21.3` (stable). Alpha API may break.

4. **Duplicate component mirrors**: Admin components exist in both `packages/ui/.../admin/` and `packages/investintell-ui/.../analytical/`. Changes must be synced manually.

5. **SSE token capture warning**: `ConfigEditor.svelte:68` captures `apiBaseUrl` at initialization, not reactively. Harmless in practice (URL never changes at runtime).
