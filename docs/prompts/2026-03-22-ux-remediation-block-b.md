# UX Remediation — Block B (Phases 3, 6, 7)

> Self-contained prompt for a fresh Claude Code session.
> Execute in order: Phase 3 → Phase 6 → Phase 7.
> Block A (Phases 1, 2, 4, 5, 8, 9) runs in parallel — no file conflicts except `tokens.css` (additive only, different sections).

Read the full plan first: `docs/plans/2026-03-22-frontend-ux-remediation-plan.md`

---

## Phase 3 — Navigation Consolidation (Wealth 12 → 7 nav items)

### T3.1 — Merge Exposure + Allocation into Analytics tabs

**Current state:**
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte` — 783 lines, already has 5 tabs (Correlations, Backtest, Pareto, What-If, Attribution)
- `frontends/wealth/src/routes/(team)/exposure/+page.svelte` — 158 lines, simple two-column heatmap
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte` — 838 lines, complex 3-tab view with edit modes + simulation

**Steps:**
1. Extract the content (everything below PageHeader) from `exposure/+page.svelte` into `frontends/wealth/src/lib/components/ExposureView.svelte`. Keep all imports, state, and logic. The component receives `data` as a prop (the page's `PageData`).
2. Extract the content from `allocation/+page.svelte` into `frontends/wealth/src/lib/components/AllocationView.svelte`. Same approach — receives `data` as prop. This is the complex one (edit modes, simulation, ConsequenceDialog). Preserve ALL state variables and async logic.
3. Add two new tabs to `analytics/+page.svelte`: "Exposure" and "Allocation" at the end of the existing tab list. When those tabs are active, render `<ExposureView {data} />` and `<AllocationView {data} />` respectively.
4. The analytics page's `+page.ts` or `+page.server.ts` load function must also fetch exposure and allocation data when those tabs are active. Check what data each page loads and ensure it's available. If the load functions are different, use conditional loading based on `url.searchParams.get('tab')`.
5. Tab state synced to URL: `?tab=exposure`, `?tab=allocation`. Default tab (no param) = first existing tab (Correlations).

### T3.2 — Merge Funds + Instruments + Universe into Screener tabs

**Current state:**
- `frontends/wealth/src/routes/(team)/screener/+page.svelte` — 500+ lines, 3-layer funnel with virtualized table
- `frontends/wealth/src/routes/(team)/funds/+page.svelte` — 373 lines, status tabs + detail panel
- `frontends/wealth/src/routes/(team)/instruments/+page.svelte` — 472 lines, CRUD + CSV import
- `frontends/wealth/src/routes/(team)/universe/+page.svelte` — check line count, approval workflow

**Steps:**
1. Extract content from `funds/+page.svelte` → `frontends/wealth/src/lib/components/FundsView.svelte`
2. Extract content from `instruments/+page.svelte` → `frontends/wealth/src/lib/components/InstrumentsView.svelte`
3. Extract content from `universe/+page.svelte` → `frontends/wealth/src/lib/components/UniverseView.svelte`
4. Add tabs to `screener/+page.svelte`: **Screening** (current content), **Funds**, **Managers** (link to `/manager-screener`), **Instruments**, **Universe**
5. Manager-screener is too large (40KB) to embed — the "Managers" tab should navigate to `/manager-screener` via `goto()` rather than rendering inline.
6. Tab state synced to URL: `?tab=funds`, `?tab=instruments`, `?tab=universe`. Default = "screening".
7. Handle data loading: each tab's data should only be fetched when that tab is active. Use the page's load function with tab-conditional fetching, or lazy-load data in the components themselves.

### T3.3 — Update Wealth layout nav items

**File:** `frontends/wealth/src/routes/+layout.svelte` (currently 12 items)

**Change to 7 items:**
```typescript
const navItems = [
    { label: "Dashboard",  href: "/dashboard" },
    { label: "Screener",   href: "/screener" },
    { label: "Portfolios", href: "/model-portfolios" },
    { label: "Risk",       href: "/risk" },
    { label: "Analytics",  href: "/analytics" },
    { label: "Documents",  href: "/documents" },
    { label: "Macro",      href: "/macro" },
];
```

### T3.4 — Redirect routes for backward compatibility

Create `+page.server.ts` in each old route with SvelteKit redirect:

```typescript
import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
    redirect(301, '/screener?tab=funds');
};
```

Files to create:
- `frontends/wealth/src/routes/(team)/funds/+page.server.ts` → `/screener?tab=funds`
- `frontends/wealth/src/routes/(team)/instruments/+page.server.ts` → `/screener?tab=instruments`
- `frontends/wealth/src/routes/(team)/universe/+page.server.ts` → `/screener?tab=universe`
- `frontends/wealth/src/routes/(team)/exposure/+page.server.ts` → `/analytics?tab=exposure`
- `frontends/wealth/src/routes/(team)/allocation/+page.server.ts` → `/analytics?tab=allocation`

**IMPORTANT:** When you add `+page.server.ts` with a redirect, the existing `+page.svelte` in the same directory will still be present but never reached (server redirect happens before client rendering). Keep the `+page.svelte` files during transition — do NOT delete them yet.

---

## Phase 6 — Dashboard Focal Point & Rhythm

### T6.1 — Redesign dashboard layout hierarchy

**File:** `frontends/wealth/src/routes/(team)/dashboard/+page.svelte` (296 lines)

**Current layout:** Flat grid of equal-weight cards (RegimeBanner, portfolio cards, NAV chart, drift alerts, quick actions, macro indicators — all same visual weight).

**New layout (top to bottom):**
1. **RegimeBanner** — stays at top (contextual alert)
2. **Portfolio health hero** — full-width section, 2-column: featured portfolio (largest AUM) at 60% width, secondary portfolios stacked at 40%
3. **NAV chart** — dedicated full-width SectionCard below hero
4. **Drift alerts + Quick actions** — side-by-side below chart (secondary information)
5. **Macro indicators** — bottom section, dense chip layout (reference data)

### T6.2 — Section density variation + empty states

**Add to `packages/ui/src/lib/styles/tokens.css`** (in `:root` block, NOT in dark mode block — these are theme-agnostic):
```css
--netz-space-card-padding-sm: clamp(12px, 0.5rem + 0.5vw, 16px);
--netz-space-card-padding-lg: clamp(24px, 1rem + 1vw, 40px);
```

**Apply in dashboard:**
- Hero section: `p-(--netz-space-card-padding-lg)`
- Chart section: `p-(--netz-space-card-padding)`
- Drift/actions: `p-(--netz-space-card-padding-sm)`
- Macro chips: minimal padding

**Also apply T5.2 empty states** (moved here from Block A to avoid file conflict):
- Replace generic "Awaiting data..." with domain-specific CTAs:
  - Portfolio empty: `title="No portfolios configured" message="Create your first model portfolio to see performance metrics." actionLabel="Create Portfolio"` with navigation to `/model-portfolios`
  - Drift alerts empty: `message="Monitoring {portfolioCount} portfolios for style drift."`

---

## Phase 7 — Navigation Grounding

### T7.1 — ContextSidebar for fund detail views

**Existing component:** `packages/ui/src/lib/layouts/ContextSidebar.svelte` (126 lines), already used in Credit via `AppLayout`.

This depends on the Screener tab consolidation from Phase 3. After Phase 3, fund detail views should eventually live under `/screener/[fundId]/...`. For now, integrate ContextSidebar in DD report views:

**File:** `frontends/wealth/src/routes/(team)/dd-reports/+page.svelte`

When viewing a specific fund's DD report, activate ContextSidebar with:
- Fund name + status badge
- Nav links: Overview, DD Report, Fact Sheet, Risk Metrics

Use `initContextNav()` pattern from Credit — check how `frontends/credit/` uses it and replicate.

### T7.2 — Add breadcrumbs to PageHeader

**File:** `packages/ui/src/lib/layouts/PageHeader.svelte` (126 lines)

**Changes:**
1. Add optional `breadcrumbs` prop: `Array<{label: string, href?: string}>`
2. Render above the title as: `Screener / Funds / Fund Name` with links on ancestors, plain text on current
3. Style: small text, muted color (`--netz-text-tertiary`), `/` separator

**Then update these pages to pass breadcrumbs:**
- `screener/+page.svelte` — when on a tab: `[{label: "Screener", href: "/screener"}, {label: "Funds"}]`
- `analytics/+page.svelte` — when on a tab: `[{label: "Analytics", href: "/analytics"}, {label: "Exposure"}]`
- `dd-reports/+page.svelte` — `[{label: "Screener", href: "/screener?tab=funds"}, {label: "Fund Name"}, {label: "DD Report"}]`

---

## Validation

After all changes:
1. Run `cd frontends/wealth && pnpm check` — must pass with zero errors
2. Run `cd packages/ui && pnpm check` — must pass (PageHeader changes)
3. Verify nav items reduced from 12 to 7 in `+layout.svelte`
4. Verify redirect files exist and use `redirect(301, ...)`
5. Verify dashboard has clear visual hierarchy (hero → chart → secondary → reference)
