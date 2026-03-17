---
title: "feat: Wealth OS Frontend — Figma Design Refresh + Dark Theme + Admin Tokens"
type: feat
status: in_progress
date: 2026-03-16
deepened: 2026-03-17
origin: Figma reference file "Netz Wealth OS — Design Reference" (7 frames)
---

# Wealth OS Frontend — Figma Design Refresh + Dark Theme + Admin Tokens

## Enhancement Summary

**Deepened on:** 2026-03-17
**Research agents used:** 8 (dark theme CSS patterns, SvelteKit SSE/data, architecture strategist, performance oracle, security sentinel, simplicity reviewer, learnings researcher, pattern recognition)

### Key Improvements from Research

1. **ARCHITECTURE: Two orthogonal navigation levels** — `TopNav` (global sections, always visible, full-width) + `ContextSidebar` (entity navigation on detail pages like `/funds/[fundId]`). List pages get 100% width. Detail pages get contextual sidebar. `AppLayout` prop `contextNav?` controls the mode — one line in `+layout.svelte` changes the entire layout.
1b. **CRITICAL: Don't change `defaultBranding` globally** — Export `defaultDarkBranding` separately for wealth. Keep `defaultBranding` light for credit/investor portals. This eliminates cross-frontend blast radius. (Architecture)
2. **CRITICAL: CSS injection via branding tokens** — Add server-side validation (regex allowlist for hex colors, font-family patterns) and `BrandingResponse extra="ignore"` instead of `extra="allow"`. (Security)
3. **CRITICAL: Fix @tanstack/svelte-table Svelte 5 breakage first** — DataTable import crashes SSR across all 3 frontends. Must upgrade to v9.x or isolate import before any UI work. (Learnings)
4. **Simplify BrandingConfig: 2 new fields, not 11** — Only add `surface_elevated_color` and `surface_inset_color`. Chart palette and semantic colors stay CSS-only (derived from brand via `color-mix()`). No admin needs to pick 5 individual chart colors. (Simplicity)
5. **Use `data-theme="dark"` attribute on `<html>`** — Not just CSS var overrides. Enables `[data-theme="dark"]` selectors in tokens.css, FOUC prevention via `transformPageChunk` in hooks.server.ts, and future light/dark toggle. (Dark Theme Research)
6. **FOUC prevention via server hook** — Use `transformPageChunk` to inject `data-theme` into SSR HTML. Blocking inline script in `app.html` for client-only navigation. (Dark Theme Research)
7. **Register ECharts theme ONCE globally** — Move from per-ChartContainer registration to `echarts-setup.ts`. Add `MutationObserver` on `<html>` for theme attribute changes. (Performance)
8. **Use `createSubscriber` from `svelte/reactivity`** for SSE — Lazy connection (starts when read, stops when unmounted), sharable across components, cleaner than raw `$effect`. (SvelteKit Research)
9. **Use HTML tables for Exposure Monitor heatmaps** — Not ECharts. The Figma shows colored table cells, not a chart canvas. Create `HeatmapTable.svelte`. (Pattern Recognition, Performance)
10. **Institutional components replace generic ones** — `MetricCard` (replaces DataCard in wealth — adds utilization bar, delta, status border), `UtilizationBar` (HTML primitive, not chart), `RegimeBanner` (conditional full-width), `AlertFeed` (discriminated union typed feed), `SectionCard`, `HeatmapTable`, `PeriodSelector`. DataCard stays for credit. (Architecture + Pattern Recognition)
11. **Collapse exposure endpoints from 4 to 2** — `GET /exposure/matrix?dimension=geographic|sector` + `GET /exposure/metadata` (freshness + leading indicators). (Simplicity)
12. **Merge Phase 9 into existing phases** — Nav items go with their pages (7, 8). Icons/skeletons go into Phase 1. Reduces to 8 phases. (Simplicity)
13. **Cap `riskAlerts` array at 50 entries** — Prevents unbounded memory growth during day-long sessions. Use `$state.raw()` for alerts. (Performance)
14. **Merge dashboard loader into single `Promise.allSettled`** — Current two sequential batches add ~100ms latency. All 7 calls are independent. (Performance)
15. **SSE tenant isolation gap** — Redis pub/sub channels `wealth:alerts:{profile}` missing `organization_id`. Fix before wiring dashboard SSE. (Security)
16. **Add `?portfolio={id}` URL state for Model Portfolios** — Sidebar selection should survive browser back/forward. Matches Analytics `?tab=` pattern. (Architecture, Pattern Recognition)

### Critical Anti-Patterns to Avoid (from research)

| Anti-Pattern | Consequence | Correct Pattern |
|---|---|---|
| Change `defaultBranding` to dark globally | Credit + investor portals flash dark on API failure | Export `defaultDarkBranding` separately; wealth uses it, credit keeps light |
| `BrandingResponse extra="allow"` | Arbitrary DB keys flow to frontend unfiltered | Use `extra="ignore"` with explicit field declarations and pattern validators |
| `injectBranding()` without CSS value sanitization | Admin can inject `url()` for data exfiltration or overlay phishing | Validate: colors match `/^#[0-9a-fA-F]{3,8}$/`, fonts match quoted family list |
| ECharts theme registered per ChartContainer | 7+ chart instances each call `registerTheme` + `getComputedStyle` | Register once in `echarts-setup.ts`, pass theme name as prop |
| Unbounded SSE alert array | Day-long sessions accumulate 480+ items, O(n²) memory churn | Cap at 50 entries: `items = [...items.slice(-49), newItem]` |
| `$effect` for SSE without `createSubscriber` | Manual lifecycle, no lazy connect/disconnect, no sharing | Use `createSubscriber` from `svelte/reactivity` (Svelte 5.7+) |
| ECharts `HeatmapChart` for Exposure Monitor tables | Overkill: canvas rendering for styled table cells, 2 extra chart instances | Use plain `HeatmapTable.svelte` (HTML table with `background-color`) |
| Hardcoded `bg-white` in 28+ files | Dark theme shows white rectangles on dark background | Replace all with `bg-[var(--netz-surface-alt)]` or `bg-[var(--netz-surface-elevated)]` |
| TanStack Virtual stable adapter for Svelte 5 | Doesn't exist. Community workaround requires `.svelte.ts` with manual lifecycle | Use server-side pagination for screener (primary), client virtual scroll as enhancement |

### Brainstorm Alignment Fixes (from review)

17. **Phase 4 Drift: two signals, not one** — `GET /risk/drift` returns `{ dtw_alerts, behavior_change_alerts }`. DTW from existing `drift_monitor.py`, behavior change from `strategy_drift_detector.py` (Sprint 1). EmptyState for behavior change until detector deploys.
18. **Analytics Phase 6: Attribution tab added** — 5th tab "Atribuição de Performance". EmptyState until `attribution_service.py` + `benchmark_data_ingestor.py` are ready. This is the highest-impact engine from the brainstorm (substitui 2-3 analistas).
19. **AlertCard discriminated union type** — `WealthAlert` union with `type` discriminator for `behavior_change | dtw_drift | cvar_breach | universe_removal`. Defined in Phase 1.3 shared component extraction.
20. **Correlation Monitor UI home noted** — Sprint 2 backend, noted in Phase 4 backend gaps. Future section in Risk Monitor or Analytics tab.
21. **Phase 7 split: 7a (heatmaps) + 7b (leading indicators backlog)** — 7a ships with `instruments_universe.attributes` data. 7b requires domain analysis (which FRED indicator → which exposure). Not a code problem.
22. **Model Portfolios periodic returns: EmptyState** — Carino linking is same complexity as attribution. Use EmptyState, defer to dedicated Sprint.

### WCAG Dark Theme Constraints (from research)

Default dark palette values are stored in `tokens.css [data-theme="dark"]` — NOT in this plan. The admin can override all values. The plan only specifies **constraints** that any dark palette must satisfy:

| Token | Minimum Contrast vs Surface | WCAG Level | Use |
|---|---|---|---|
| `--netz-text-primary` | 4.5:1 | AA (normal text) | Body text, headings |
| `--netz-text-secondary` | 4.5:1 | AA (normal text) | Secondary labels |
| `--netz-text-muted` | 3.0:1 | AA (large text only) | Captions, timestamps, placeholders |
| `--netz-success` | 4.5:1 | AA | Positive values |
| `--netz-warning` | 4.5:1 | AA | Warning badges |
| `--netz-danger` | 4.5:1 | AA | Negative values |
| `--netz-chart-{1-5}` | 3.0:1 | AA (graphical objects) | Chart series — must be distinguishable under deuteranopia |

Default values are provided in the code as a starting point. The admin can change them — the branding API validates contrast ratios are met.

### Architectural Changes

**1. Two orthogonal navigation levels** — Not TopNav vs Sidebar. Both, with different roles:

```
┌──────────────────────────────────────────────────────────────┐
│  TopNav — global navigation between sections                  │
│  Dashboard  Portfolios  Risk  Funds  Analytics  Macro         │
├──────────────────────────────────────────────────────────────┤
│  LIST PAGES (no sidebar): Dashboard, Funds list, Risk, etc.  │
│  100% width for data                                          │
└──────────────────────────────────────────────────────────────┘

DETAIL PAGES (/funds/[fundId], /model-portfolios/[portfolioId]):
┌──────────────────────────────────────────────────────────────┐
│  TopNav                                                       │
├──────────────────────────────────────────────────────────────┤
│  ← Vanguard Global Equity     [breadcrumb]                    │
├───────────────┬──────────────────────────────────────────────┤
│ ContextSidebar│  Main content                                 │
│  Resumo       │  (Resumo / DD Report / Documentos / etc.)     │
│  DD Report    │                                               │
│  Documentos   │                                               │
│  Screening    │                                               │
└───────────────┴──────────────────────────────────────────────┘
```

Three distinct roles, three components:

| Component | Role | When visible |
|---|---|---|
| `TopNav` | Global section navigation | Always |
| `ContextSidebar` | Navigation within an entity (fund, portfolio) | Only on detail pages `[id]` |
| `ContextPanel` | Slide-in for quick detail without leaving list | Inside list pages |

`ContextSidebar` is persistent (not a slide-in). `ContextPanel` already exists. `TopNav` is new. Current `Sidebar` is eliminated.

**AppLayout prop controls the mode:**

```typescript
interface AppLayoutProps {
  navItems: NavItem[]           // TopNav global items
  appName: string
  branding: BrandingConfig
  token: string
  contextNav?: {                // optional — appears only when passed
    backHref: string            // "← Vanguard Global Equity"
    backLabel: string
    items: NavItem[]            // Resumo, DD Report, Docs, etc.
    activeHref: string
  }
  children: Snippet
}
```

- List pages (`+page.svelte`) don't pass `contextNav` → full-width layout
- Detail pages (`[fundId]/+page.svelte`) pass `contextNav` → layout with ContextSidebar
- The `+layout.svelte` of each detail route group injects `contextNav` via `$props()`. One line of code, completely different behavior.

**2. Dark + Light for all frontends** — `tokens.css` defines both `:root { /* light */ }` and `[data-theme="dark"] { /* dark overrides */ }`. Each frontend sets its default via `data-theme` on `<html>`. Admin overrides token **values**, not which tokens exist. Both themes work independently of any override.

**3. Semantic components, not token-driven design** — What makes the product institutional is component structure (3px status border, utilization bars, typed alert feed), not color values. The plan specifies semantic interfaces (`status: "ok"|"warn"|"breach"`), never hex values. Admin changes tokens; components keep communicating correctly.

### New Institutional Components (Phase 1.3)

| Component | Replaces | Description |
|---|---|---|
| `TopNav.svelte` | `Sidebar.svelte` (as global nav) | Horizontal nav: logo, app name, text items (no icons), active = border-bottom, regime badge right-aligned, org dropdown. Mobile: hamburger → overlay drawer |
| `ContextSidebar.svelte` | (new) | Persistent sidebar for detail pages (`[id]`). Back link + entity name + contextual nav items (Resumo, DD Report, Docs, etc.). Only rendered when `contextNav` prop is passed to AppLayout |
| `MetricCard.svelte` | `DataCard.svelte` (in wealth) | Institutional metric: label, large mono value, utilization bar with limit, delta with direction + period, 3px status border left, optional sparkline |
| `UtilizationBar.svelte` | (new primitive) | HTML bar: current vs limit, overflow past 100% marker. Status derived internally: <0.8=ok, <1.0=warn, ≥1.0=breach. Used in MetricCard, PortfolioCard, CVaR section |
| `RegimeBanner.svelte` | (new) | Full-width conditional banner when regime ≠ RISK_ON. Shows regime, duration, key signals (VIX, yield curve), link to macro detail. Renders nothing when RISK_ON |
| `AlertFeed.svelte` | Risk alerts list | Chronological feed with `WealthAlert` discriminated union. Each type renders differently: cvar_breach shows utilization inline, behavior_change lists changed metrics, regime_change shows from→to |
| `SectionCard.svelte` | Repeated inline pattern | Standard section wrapper: title, subtitle, actions snippet, children, collapsible, loading state |
| `HeatmapTable.svelte` | (new) | HTML table with intensity-colored cells. Not ECharts. Rows × columns matrix with format function and color scale |
| `PeriodSelector.svelte` | Repeated button group | Compact button group for period selection (1M/3M/YTD/1Y/3Y). 3 usages across pages |
| Extend `Tabs` count | — | Add `count?: number` to tab item interface for Fund Universe + Screener status tabs |
| Extend `ContextPanel` header | — | Add optional `header` snippet (not just string title) for fund/instrument detail panels |

**`DataCard.svelte` unchanged** — kept for credit frontend compatibility, but wealth uses `MetricCard` exclusively.

---

## Overview

Redesign the Wealth OS frontend (`frontends/wealth/`) from a generic prototype to an institutional-grade product. The current design looks generic because the components are generic. The fix is **structural** — new semantic components (MetricCard, UtilizationBar, RegimeBanner, AlertFeed), TopNav replacing Sidebar for 100% data width, and dark/light dual-theme token system where the admin controls all color values.

**Scope:** Layout architecture change (Sidebar→TopNav) + 7 new institutional components + dual-theme tokens + 5 page redesigns + 2 new pages.

**Principle:** Tokens are configuration (admin-controlled). Component structure is product identity (code-controlled). The plan specifies semantic interfaces (`status: "ok"|"warn"|"breach"`), never hex values. Admin swaps tokens; components keep communicating correctly because semantics are in code.

## Problem Statement

The current wealth frontend looks generic because:

1. **Layout wastes space** — Sidebar (240px) steals width from data-dense pages. Institutional products (Bloomberg, Refinitiv, FactSet) use horizontal nav to maximize data area
2. **Components are generic** — `DataCard` shows label+value+trend. An institutional `MetricCard` shows label+value+utilization bar with limit+delta with direction+status border. The structure communicates, not just the values
3. **No regime awareness** — When RISK_OFF is active for 14 days, there's no persistent banner. A badge in the header is insufficient for a product where regime drives all portfolio decisions
4. **Alerts are undifferentiated** — Current list shows `StatusBadge` + text. An institutional `AlertFeed` discriminates by type: CVaR breach shows utilization inline, behavior change lists changed metrics, regime change shows transition
5. **Single theme** — Only light tokens exist. Dark theme requires `[data-theme="dark"]` override block in tokens.css. Both themes must work independently of admin branding overrides
6. **Two pages missing** — Exposure Monitor, Screener (backend ready)

## Current State vs Figma

| Page | Current | Figma Target | Gap |
|---|---|---|---|
| Dashboard | Light, PortfolioCards with gauge, empty NAV chart | Dark, horizontal KPI bars, multi-line NAV chart, active alerts | ~50% redesign |
| Model Portfolios | Light, simple DataTable list → detail page | Dark, sidebar portfolio list, detail with 6 KPIs + periodic returns + allocation bars + stress table | ~65% redesign |
| Risk Monitor | Light, CVaR status cards + timeline chart | Dark, horizontal CVaR utilization bars, regime area chart with zones, drift alerts | ~70% redesign |
| Fund Universe | Light, DataTable with dropdown filters | Dark, status tabs, strategy badges, side panel with DD pipeline progress | ~60% redesign |
| Analytics | Light, backtest trigger + correlation heatmap only | Dark, 4 tabs, KPI cards, correlation heatmap + Pareto frontier scatter | ~80% redesign |
| Exposure Monitor | **Does not exist** | Geographic + sector heatmap tables, leading indicator alerts, freshness badges | 100% new |
| Screener | **Does not exist** (backend ready) | Screening funnel, 3-layer results table, instrument detail panel | 100% new |

## Technical Approach

### Architecture

Two architectural changes from the current codebase:

```
BEFORE:                              AFTER (list pages):
AppLayout                            AppLayout
├── AppShell (CSS Grid)              ├── TopNav (global)
│   ├── Sidebar (240px, always)      ├── RegimeBanner (conditional)
│   ├── main                         ├── main (100% width)
│   └── ContextPanel (optional)      └── ContextPanel (slide-in, optional)

                                     AFTER (detail pages, e.g. /funds/[fundId]):
                                     AppLayout (contextNav prop passed)
                                     ├── TopNav (global)
                                     ├── RegimeBanner (conditional)
                                     ├── ContextSidebar (← Back + entity nav)
                                     └── main (remaining width)
```

Three navigation roles:
- **TopNav** — global sections (Dashboard, Portfolios, Risk, etc). Always visible. Text items, no icons.
- **ContextSidebar** — entity navigation (Resumo, DD Report, Docs, Screening). Only on `[id]` pages. Persistent, not slide-in.
- **ContextPanel** — quick-peek slide-in on list pages (fund detail from funds table, instrument detail from screener table). Already exists.

**Dual-theme token system:**

```
tokens.css
├── :root { /* light defaults */ }
└── [data-theme="dark"] { /* dark overrides */ }

↓ Runtime

data-theme attribute on <html>
  → Each frontend sets its default (wealth=dark, credit=light)
  → injectBranding() overlays admin token values on top
  → Components consume via var(--netz-*)
```

Admin controls **values** of tokens. Code controls **which tokens exist** and **what they mean semantically**. The admin cannot add tokens, remove tokens, or change component structure. They can make the dark theme use gold accents instead of blue. That's the boundary.

### Token Structure

`tokens.css` defines both themes. New tokens added: `--netz-surface-elevated`, `--netz-surface-inset`. Chart palette and semantic colors exist in both `:root` and `[data-theme="dark"]` blocks but are NOT exposed as branding API fields — they are CSS-only tokens derived from the design system.

```css
:root {
  /* Light defaults — unchanged from current */
  --netz-surface: #ffffff;
  --netz-surface-alt: #f8fafc;
  --netz-surface-elevated: #ffffff;
  --netz-surface-inset: #f1f5f9;
  /* ... all existing tokens ... */
}

[data-theme="dark"] {
  /* Dark overrides — values are placeholders, admin-overridable */
  --netz-surface: /* admin sets */;
  --netz-surface-alt: /* admin sets */;
  --netz-surface-elevated: /* admin sets */;
  --netz-surface-inset: /* admin sets */;
  /* ... */
  /* Chart palette — higher saturation for dark bg, CSS-only (not in branding API) */
  --netz-chart-1: /* derived from design system */;
  /* ... */
}
```

No hex values in this plan. Token values are configuration — set by the admin or by the default theme. The plan specifies token **names** and **semantic purpose** only.

### BrandingConfig Extension

```typescript
// packages/ui/src/lib/utils/types.ts — add new fields
interface BrandingConfig {
  // ... existing 13 color/font fields ...
  surface_elevated_color: string | null;  // NEW
  surface_inset_color: string | null;     // NEW
  success_color: string | null;           // NEW (was hardcoded)
  warning_color: string | null;           // NEW
  danger_color: string | null;            // NEW
  info_color: string | null;              // NEW
  chart_1: string | null;                 // NEW
  chart_2: string | null;                 // NEW
  chart_3: string | null;                 // NEW
  chart_4: string | null;                 // NEW
  chart_5: string | null;                 // NEW
}
```

Backend `BrandingResponse` schema already uses `extra="allow"`, so new fields propagate without migration.

### Component Strategy

**New institutional components replace generic ones in wealth. Credit keeps existing components unchanged.**

| What | Action |
|---|---|
| `Sidebar` → `TopNav` + `ContextSidebar` | Two new components. TopNav for global sections. ContextSidebar for entity detail pages. AppLayout uses `contextNav?` prop to switch modes |
| `DataCard` → `MetricCard` | New component for wealth. DataCard unchanged for credit compatibility |
| (none) → `UtilizationBar` | New primitive. Used by MetricCard, PortfolioCard, CVaR section |
| (none) → `RegimeBanner` | New component. Full-width, conditional (hidden when RISK_ON) |
| Alert list → `AlertFeed` | New component with discriminated union `WealthAlert` type |
| Inline card wrapper → `SectionCard` | Extracts the repeated `<div class="rounded-lg border p-5"><h3>` pattern |
| (none) → `HeatmapTable` | New component. HTML table with colored cells (not ECharts) |

**Existing `@netz/ui` fixes:**

1. All `bg-white` hardcodes → `bg-[var(--netz-surface-alt)]` or `bg-[var(--netz-surface-elevated)]`
2. `DataCard` hardcoded colors → `var(--netz-success)`, `var(--netz-danger)` — for credit compatibility
3. `ChartContainer` hardcoded `bg-white/80`, `text-zinc-*`, light palette → token-based
4. `AppLayout` session modal `bg-white` → token-based
5. `HeatmapChart` default `minColor: "#EFF6FF"` → token-based
6. ECharts theme registered ONCE in `echarts-setup.ts` (not per ChartContainer)
7. `$state.raw()` for all API response data, `$effect` audit, keyed `{#each}` blocks
8. `var(--netz-primary)` / `var(--netz-navy)` normalized to `var(--netz-brand-primary)`

---

## Svelte 5 Implementation Patterns (from Skills)

### Runes — Decision Matrix

| Need | Rune | Notes |
|---|---|---|
| API response data (large, replaced entirely) | `$state.raw()` | Skip deep proxy overhead. Fund lists, screening results, correlation matrices |
| UI state (selections, filters, toggles) | `$state()` | Period selector, selected portfolio, active tab |
| Computed from state | `const x = $derived()` | Use `const` to prevent accidental reassignment |
| Complex computation | `$derived.by(() => {...})` | Card data merging, funnel count aggregation |
| Side effect (SSE, subscriptions) | `$effect()` with cleanup | Risk alert SSE, DD report progress SSE. Return cleanup function |
| DOM integration (charts) | `@attach` (Svelte 5.29+) | Use for ECharts init/destroy instead of `$effect`. Reactive to data changes |

### Anti-Patterns to Enforce

```svelte
<!-- ❌ WRONG: $effect for derived state (exists in current codebase) -->
$effect(() => { doubled = count * 2; });

<!-- ✅ RIGHT: $derived -->
const doubled = $derived(count * 2);

<!-- ❌ WRONG: Optional chaining breaks effect reactivity -->
$effect(() => { chart?.update(data); }); // If chart is null, data dependency is never tracked

<!-- ✅ RIGHT: Read dependencies first -->
$effect(() => {
  const currentData = data; // Track dependency unconditionally
  if (chart) chart.update(currentData);
});

<!-- ❌ WRONG: Destructuring layout data (breaks reactivity) -->
const { user } = data; // Static snapshot, won't update after invalidateAll()

<!-- ✅ RIGHT: Access reactively -->
{data.user?.email}
```

### ECharts Integration via `@attach`

Current pattern uses `$effect` in `ChartContainer.svelte`. Prefer `@attach` (Svelte 5.29+) for chart lifecycle:

```svelte
<!-- Current pattern (ChartContainer.svelte) -->
<script>
  let container: HTMLDivElement;
  $effect(() => {
    const chart = echarts.init(container);
    // ... setup
    return () => chart.dispose();
  });
</script>
<div bind:this={container} />

<!-- Preferred pattern with @attach -->
<script>
  function initChart(getData) {
    return (node) => {
      const chart = echarts.init(node, 'netz-dark');
      $effect(() => { chart.setOption(getData()); }); // Cheap re-run on data change
      return () => chart.dispose();
    };
  }
</script>
<div {@attach initChart(() => chartOptions)} />
```

**Benefits:** Expensive init runs once, data updates are cheap `$effect` inside attach. Auto-cleanup on unmount.

### LayerChart (Future Consideration)

LayerChart (`layerchart@next`) is a Svelte 5-native chart library with snippet-based tooltips, automatic theme inheritance via CSS classes, and d3-scale integration. For this plan we **keep ECharts** (all chart components already built in `@netz/ui`), but note LayerChart as a future migration candidate for:

- Better Svelte 5 integration (snippets vs wrapper components)
- CSS-native theming (no manual `--netz-chart-*` reading)
- Smaller bundle (d3 modules vs full ECharts)

### Snippet Patterns for Component Composition

Use Svelte 5 snippets (not slots) for component content injection:

```svelte
<!-- DataTable custom cell renderer via snippet -->
<DataTable {data} {columns}>
  {#snippet cellRenderer(cell, column)}
    {#if column.id === 'status'}
      <StatusBadge status={cell.value} />
    {:else if column.id === 'score'}
      <span class="font-mono" style:color={cell.value > 0.7 ? 'var(--netz-success)' : 'var(--netz-danger)'}>{cell.value}</span>
    {:else}
      {cell.value}
    {/if}
  {/snippet}
</DataTable>

<!-- ContextPanel with typed snippet for content -->
<ContextPanel open={!!selectedFund}>
  {#snippet header()}
    <h3>{selectedFund.name}</h3>
  {/snippet}
  {#snippet children()}
    <FundDetail fund={selectedFund} />
  {/snippet}
</ContextPanel>
```

### SvelteKit Data Flow Patterns

```typescript
// +page.server.ts — Parallel fetch with proper error handling
export const load: PageServerLoad = async ({ parent }) => {
  const { token } = await parent();
  const api = createServerApiClient(token);

  // Use $state.raw() in component for these large responses
  const [funds, screenerRuns] = await Promise.allSettled([
    api.get("/funds"),
    api.get("/screener/runs?limit=1"),
  ]);

  return {
    funds: funds.status === "fulfilled" ? funds.value : null,
    latestRun: screenerRuns.status === "fulfilled" ? screenerRuns.value?.[0] : null,
  };
};
```

```svelte
<!-- Component — use $state.raw for API data, $state for UI state -->
<script lang="ts">
  let { data }: { data: PageData } = $props();

  // API data: large, replaced entirely → $state.raw
  let funds = $state.raw(data.funds);

  // UI state: user interactions → $state
  let selectedFundId = $state<string | null>(null);
  let activeTab = $state("all");

  // Computed: always const $derived
  const selectedFund = $derived(funds?.find(f => f.id === selectedFundId) ?? null);
  const filteredFunds = $derived.by(() => {
    if (!funds) return [];
    if (activeTab === "all") return funds;
    return funds.filter(f => f.status === activeTab);
  });
</script>
```

### SSE Subscriptions via `$effect` with Cleanup

```svelte
<script lang="ts">
  import { createSSEStream } from "@netz/ui";

  // SSE for risk alerts — proper cleanup pattern
  $effect(() => {
    const controller = new AbortController();

    (async () => {
      const stream = await createSSEStream("/risk/stream", {
        signal: controller.signal,
      });
      for await (const event of stream) {
        riskAlerts = [...riskAlerts, JSON.parse(event.data)];
      }
    })();

    return () => controller.abort(); // Cleanup on unmount or re-run
  });
</script>
```

### `invalidateAll()` After Branding Changes

When admin changes branding tokens, call `invalidateAll()` to re-run all load functions (which fetch branding from API). This is critical because SvelteKit caches server load data during client-side navigation.

```typescript
// After branding update in admin panel
await api.put("/branding", newBranding);
await invalidateAll(); // Re-runs +layout.server.ts → re-fetches branding → injectBranding()
```

### Keyed `{#each}` Blocks

Always use keyed each blocks per Svelte 5 best practices:

```svelte
<!-- ✅ Keyed by unique identifier -->
{#each portfolios as portfolio (portfolio.id)}
  <PortfolioCard {portfolio} />
{/each}

<!-- ❌ Never use index as key -->
{#each portfolios as portfolio, i (i)}
```

---

## Implementation Phases

### Phase 1: Dark Theme Token System + Component Fixes

**Goal:** Update design system tokens to dark theme defaults, extend BrandingConfig, fix all hardcoded light-mode values across components and pages.

**Estimated scope:** ~15 files.

#### 1.1: Dark Theme via `data-theme` Attribute + Token Overrides

##### Files

```
packages/ui/src/lib/styles/tokens.css
packages/ui/src/lib/styles/shadows.css
packages/ui/src/lib/styles/index.css
frontends/wealth/src/app.html
frontends/wealth/src/hooks.server.ts
```

##### Tasks

- [ ] Keep `:root` light defaults unchanged (backward compatible for credit)
- [ ] Add `[data-theme="dark"]` block in tokens.css with all dark overrides (surfaces, text, border, chart palette, semantic colors)
- [ ] Add new tokens: `--netz-surface-elevated` (#1c1f2b), `--netz-surface-inset` (#090c10), `--netz-surface-overlay`
- [ ] Add `[data-theme="dark"]` shadow overrides: replace drop-shadows with `inset border + ambient shadow` (shadows invisible on dark)
- [ ] Add FOUC-prevention blocking script in `app.html`: reads `localStorage('netz-theme')` or defaults to `'dark'`, sets `data-theme` attribute before paint
- [ ] Add `transformPageChunk` in `hooks.server.ts`: reads `netz-theme` cookie, injects `data-theme` attribute into SSR HTML
- [ ] Add smooth transition CSS (`transition: background-color 250ms, color 250ms`) gated by `data-theme-ready` attribute (set after hydration)
- [ ] Use WCAG-verified dark palette from Enhancement Summary (all text tokens pass 4.5:1 AA)
- [ ] Chart palette: `#60a5fa`, `#34d399`, `#fbbf24`, `#f87171`, `#a78bfa` (all pass 3:1 against #0f1117)

##### Acceptance Criteria

- [ ] All text meets WCAG 2.1 AA contrast ratio (4.5:1 body, 3:1 large) against `#0f1117` surface
- [ ] Chart colors distinguishable on dark background (tested with color blindness simulator)
- [ ] No FOUC on page load (dark theme applied before first paint)
- [ ] Credit frontend unaffected (`:root` light defaults preserved)
- [ ] Adding `data-theme="light"` overrides works for light-mode admin customization

#### 1.2: Extend BrandingConfig (2 fields) + Security Hardening

##### Files

```
packages/ui/src/lib/utils/types.ts
packages/ui/src/lib/utils/branding.ts
backend/app/domains/admin/schemas.py
```

##### Tasks

- [ ] Add only `surface_elevated_color` and `surface_inset_color` to `BrandingConfig` (2 fields, not 11 — chart palette and semantic colors stay CSS-only, derived from brand via tokens.css)
- [ ] Update `CSS_VAR_MAP` with 2 new field→variable mappings
- [ ] Export `defaultDarkBranding` separately from `defaultBranding` — dark surfaces, dark text, dark border values. **Do NOT change `defaultBranding`** (credit/investor fallback must stay light)
- [ ] In `frontends/wealth/src/routes/+layout.server.ts`, use `defaultDarkBranding` as fallback instead of `defaultBranding`
- [ ] **Security: Change `BrandingResponse` from `extra="allow"` to `extra="ignore"`** — explicitly declare every field with pattern validators
- [ ] **Security: Add CSS value sanitization in `injectBranding()`** — color fields must match `/^#[0-9a-fA-F]{3,8}$/` or `rgb()/hsl()` patterns. Font fields must match quoted font-family list. Reject values containing `url(`, `expression(`, `@import`, semicolons, curly braces
- [ ] Add shallow equality check in `injectBranding()` — skip re-injection if branding object reference unchanged (avoids redundant style recalc on every SvelteKit navigation)
- [ ] Set `data-theme` attribute based on branding response (if branding specifies a `theme_mode: "dark"|"light"` field, use it; otherwise default to `"dark"` for wealth)

##### Acceptance Criteria

- [ ] Admin can override surface, text, border, brand colors via branding API (13 existing + 2 new)
- [ ] Chart palette and semantic colors derived from CSS tokens, not admin-editable (simpler API surface)
- [ ] Malicious CSS values rejected by sanitization (test with `url()`, `expression()`, semicolons)
- [ ] Credit frontend falls back to light theme when branding API unavailable
- [ ] Wealth frontend falls back to dark theme when branding API unavailable

#### 1.3: Fix @tanstack/svelte-table + Hardcoded Light-Mode Values + Shared Components

##### Files

```
packages/ui/package.json                     (@tanstack/svelte-table upgrade)
packages/ui/src/lib/components/*.svelte      (scan all — especially DataTable, DataCard, HeatmapChart)
packages/ui/src/lib/charts/ChartContainer.svelte  (hardcoded bg-white/80, text-zinc, light palette)
packages/ui/src/lib/charts/echarts-setup.ts  (global theme registration)
packages/ui/src/lib/layouts/*.svelte         (scan all — especially AppLayout session modal)
frontends/wealth/src/routes/**/*.svelte      (scan all)
frontends/wealth/src/lib/components/*.svelte
```

##### Tasks

- [ ] Replace all `bg-white` with `bg-[var(--netz-surface-alt)]` or `bg-[var(--netz-surface)]`
- [ ] Replace all hardcoded `#ffffff`, `#f8fafc` with token references
- [ ] Replace `text-white` on brand-primary backgrounds → verify contrast, may need adjustment
- [ ] Fix `<select>` and `<input>` elements using `bg-white` → `bg-[var(--netz-surface-elevated)]`
- [ ] Replace CSS shadow-based elevation with `border` + `surface-elevated` token (shadows invisible on dark)
- [ ] Audit `color-mix()` references in Sidebar for dark compatibility
- [ ] Fix the `var(--netz-primary)` / `var(--netz-navy)` references that don't exist in tokens.css → normalize to `var(--netz-brand-primary)`
- [ ] **BLOCKER: Upgrade `@tanstack/svelte-table` to v9.x** (Svelte 5 compatible) — current v8.21.3 imports `SvelteComponent` from `svelte/internal` which doesn't exist in Svelte 5, crashing SSR across all 3 frontends
- [ ] Fix `DataCard.svelte` hardcoded colors (`#10B981`, `#EF4444`) → use `var(--netz-success)`, `var(--netz-danger)`
- [ ] Fix `HeatmapChart.svelte` hardcoded `minColor: "#EFF6FF"` → token-based value (invisible on dark)
- [ ] Fix `ChartContainer.svelte` hardcoded `bg-white/80`, `text-zinc-*`, light fallback palette
- [ ] Fix `AppLayout.svelte` session expiry modal `bg-white`, `bg-black/50`
- [ ] Audit all `$effect` usage — replace derived-state-via-effect with `$derived` (Svelte 5 anti-pattern)
- [ ] Convert large API response state to `$state.raw()` where data is replaced entirely (not mutated)
- [ ] Ensure all `$derived` used for read-only computed values use `const` declaration
- [ ] Ensure all `{#each}` blocks are keyed by unique ID, never by index
- [ ] Register ECharts theme ONCE in `echarts-setup.ts` (not per ChartContainer) — read CSS vars for surface/text/border, add `MutationObserver` on `<html>` for `data-theme` changes to re-register
- [ ] Remove per-instance `registerTheme` call from `ChartContainer.svelte`
- [ ] Deduplicate `regimeLabels` mapping (exists in both PortfolioCard.svelte and dashboard/+page.svelte) → move to shared constants
- [ ] **Create institutional components (see interfaces in "New Institutional Components" table above):**
  - [ ] `TopNav.svelte` — global horizontal nav: logo, app name, text items (no icons), active = border-bottom (token primary color), regime badge right-aligned, org dropdown. Mobile: hamburger → overlay drawer
  - [ ] `ContextSidebar.svelte` — persistent sidebar for detail pages. Back link ("← Vanguard Global Equity"), entity name, contextual nav items. Only rendered when `contextNav` prop is passed. NOT a slide-in (unlike ContextPanel)
  - [ ] Refactor `AppLayout.svelte` — accepts optional `contextNav` prop:
    - Without `contextNav`: `TopNav` + `main` (100% width) — list pages, monitoring
    - With `contextNav`: `TopNav` + `ContextSidebar` + `main` — detail pages ([fundId], [portfolioId])
    - Remove current `AppShell` sidebar grid layout. Replace with flex column (TopNav) + conditional flex row (ContextSidebar + main)
  - [ ] `MetricCard.svelte` — label, large mono value, UtilizationBar with limit, delta with direction + period, 3px status border left, sparkline snippet
  - [ ] `UtilizationBar.svelte` — HTML bar: current vs limit, overflow past 100%. Status derived: <0.8=ok, <1.0=warn, ≥1.0=breach. Color = semantic token
  - [ ] `RegimeBanner.svelte` — full-width conditional banner when regime ≠ RISK_ON. Shows regime, duration, key signals, link to macro detail. Renders nothing when RISK_ON
  - [ ] `AlertFeed.svelte` — chronological feed with `WealthAlert` discriminated union. Each type renders differently: cvar_breach shows UtilizationBar inline, behavior_change lists changed metrics, regime_change shows from→to
  - [ ] `SectionCard.svelte` — title + subtitle + optional actions snippet + children + collapsible + loading
  - [ ] `HeatmapTable.svelte` — HTML table with intensity-colored cells. rows × columns matrix + format function + color scale
  - [ ] `PeriodSelector.svelte` — compact button group for period selection (3 usages)
  - [ ] Extend `Tabs`/`PageTabs` with `count?: number` in tab item interface
  - [ ] Extend `ContextPanel` with optional `header` snippet (not just string title)
  - [ ] Extend `DataCard` with `sublabel?: string` and `valueColor?: string` (credit frontend compatibility)
  - [ ] **`DataCard` stays unchanged for credit.** Wealth uses `MetricCard` exclusively

##### Acceptance Criteria

- [ ] Zero hardcoded color values in any `.svelte` file (grep for `bg-white`, `#fff`, `#ffffff`, `bg-gray`, etc.)
- [ ] All pages render correctly with dark tokens (no invisible text, no contrast failures)
- [ ] All pages render correctly when admin overrides tokens to a light palette
- [ ] Zero `$effect` used for derived state (audit: no `$effect(() => { x = f(y) })` pattern)
- [ ] ECharts charts render with dark backgrounds, light axis labels, dark tooltips automatically

---

### Phase 2: Dashboard Redesign

**Goal:** Match Figma frame "Dashboard com portfólios + NAV chart + alertas" (node 1:4).

**Estimated scope:** ~4 files.

#### Figma Specification

- **3 Portfolio Cards** — horizontal layout, each showing: name + profile badge, large NAV ("USD 1.847"), "NAV +2.3% YTD" in green, 3 inline KPIs (CVaR 95%, Utilização %, Sharpe), colored utilization bar at bottom (green/yellow/red gradient based on limit proximity)
- **NAV — Portfólios Consolidados** — multi-line TimeSeriesChart (Conservador green, Moderado blue, Growth red), period buttons (1M, 3M, YTD, 1A, 3A), legend with current returns per line
- **Alertas Ativos** — right panel, list of alert cards with left border color (red=critical, orange=warning, purple=info), title, description, timestamp ("Hoje, 09:12")
- **Header** — "Wealth OS — Dashboard", subtitle "16 Mar 2026 · Atualizado às 09:42", regime badge right-aligned ("RISK_OFF ativo"), org name

#### 2.1: Redesign PortfolioCard

##### Files

```
frontends/wealth/src/lib/components/PortfolioCard.svelte
```

##### Tasks

- [ ] Replace GaugeChart with horizontal utilization bar (colored gradient: green→yellow→red at limit)
- [ ] Add profile badge (Conservative/Moderate/Growth) — pill with colored border, top-right
- [ ] Show large NAV value formatted as "USD {value}" using currency locale
- [ ] Show "NAV +X.X% YTD" in green/red below NAV
- [ ] Add inline KPI row: CVaR 95% | Utilização | Sharpe — each with label above, value below, smaller font
- [ ] Add "Lim: -X.X%" sublabel under CVaR value
- [ ] Card uses `bg-[var(--netz-surface-alt)]` with `border-[var(--netz-border)]`
- [ ] Colored bar at very bottom of card (full-width, 4px height), color = utilization status
- [ ] Add `CVaR breach` badge (red pill, top-right) when utilization > 100%

##### Acceptance Criteria

- [ ] Visual match to Figma frame 1:4 portfolio cards
- [ ] Cards responsive: 3-column on xl, 2 on md, 1 on sm

#### 2.2: Implement Consolidated NAV Chart

##### Files

```
frontends/wealth/src/routes/(team)/dashboard/+page.svelte
frontends/wealth/src/routes/(team)/dashboard/+page.server.ts
```

##### Tasks

- [ ] Fetch track-record data per model portfolio: `GET /model-portfolios/{id}/track-record`
- [ ] Build multi-series TimeSeriesChart with one line per portfolio (name + current return in legend)
- [ ] Wire period selector buttons (1M, 3M, YTD, 1A, 3A) to filter date range
- [ ] Chart area shows data or `EmptyState` if no track-record yet
- [ ] Chart background transparent (inherits card dark surface)
- [ ] Legend shows colored dots + portfolio name + "+X.X%" return

##### Acceptance Criteria

- [ ] Chart renders 3 portfolio lines with correct colors
- [ ] Period buttons filter data range correctly
- [ ] Legend matches Figma layout

#### 2.3: Implement Alertas Ativos Panel

##### Files

```
frontends/wealth/src/routes/(team)/dashboard/+page.svelte
frontends/wealth/src/routes/(team)/dashboard/+page.server.ts
```

##### Tasks

- [ ] **Performance: Merge dashboard loader into single `Promise.allSettled`** — current 2 sequential batches (4 calls + 3 CVaR calls) add ~100ms latency. All 7 calls are independent, merge into 1 batch
- [ ] Replace current Risk Alerts section with Figma-matching alert list using `AlertCard` component
- [ ] Each alert card: 4px left border (color by severity), title bold, description, timestamp ("Hoje, 09:12" / "Ontem, 13:00")
- [ ] Severity colors: red = critical (CVaR breach), orange = warning (RISK_OFF), purple/blue = info (DD report, regime)
- [ ] Layout: NAV chart (left, ~60%) + Alertas Ativos (right, ~40%) in a 2-column grid
- [ ] Scroll overflow on alerts panel if > 5 alerts
- [ ] **Wire SSE subscription** for risk alerts using `createSubscriber` from `svelte/reactivity` — lazy connection, auto-cleanup
- [ ] **Cap `riskAlerts` array at 50 entries** — `items = [...items.slice(-49), newItem]` prevents unbounded growth
- [ ] **Security: Verify Redis pub/sub channels include `organization_id`** — current `wealth:alerts:{profile}` channels leak cross-tenant. Fix to `wealth:alerts:{org_id}:{profile}`
- [ ] Add PortfolioCard click handler → navigate to `/model-portfolios?portfolio={id}`

##### Acceptance Criteria

- [ ] Alert cards match Figma severity colors and layout
- [ ] Side-by-side layout with NAV chart

#### 2.4: Update Dashboard Header

##### Files

```
frontends/wealth/src/routes/(team)/dashboard/+page.svelte
```

##### Tasks

- [ ] Show "Wealth OS — Dashboard" as page title
- [ ] Add subtitle: "16 Mar 2026 · Atualizado às {time}" using latest data timestamp
- [ ] Move regime badge to right side of header row
- [ ] Show regime badge with duration if available ("RISK_OFF ativo — 14 dias")
- [ ] Show org name from branding config right of regime badge

##### Acceptance Criteria

- [ ] Header layout matches Figma
- [ ] Regime badge reflects current API state

---

### Phase 3: Model Portfolios Redesign

**Goal:** Match Figma frame "Model Portfolios com track-record" (node 1:5).

**Estimated scope:** ~5 files.

#### Figma Specification

- **Left sidebar** — "PORTFÓLIOS" header + "+ Novo" button, list of portfolio cards (name, badge, YTD%, CVaR/utilização, Sharpe), selected item highlighted with blue left border
- **Main content** — Portfolio name + "Model Portfolio" subtitle, benchmark composite, última revisão date
- **Action buttons** — Fact-sheet ↓, Rebalancear, Construir portfólio
- **6 KPI cards** — NAV Atual, YTD, CVaR 95%, Sharpe, Vol Anual, Max Drawdown — inline horizontal row
- **Track-Record — Retornos Periódicos** — period cards: MTD, YTD (highlighted), QTD, 1 Ano, 3 Anos, Inception — with "Base 1.000 · Jan 2020" label
- **Alocação por bloco** — horizontal stacked bars per asset class (Global Equity 35%, Fixed Income 25%, etc.), count of funds per block
- **Stress Scenarios** — table: Cenário, Drawdown (red), Recup (months), CVaR Imr (red)

#### 3.1: Convert List → Sidebar + Detail Layout

##### Files

```
frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte
frontends/wealth/src/routes/(team)/model-portfolios/+page.server.ts
```

##### Tasks

- [ ] Replace DataTable with sidebar + detail split layout (sidebar 240px, detail fills remaining)
- [ ] Sidebar shows portfolio list with: name, profile badge, YTD%, "CVaR {X}% util · Sharpe {Y}"
- [ ] Selected portfolio has blue left border + slightly lighter background
- [ ] Clicking a portfolio loads its detail inline (no page navigation) — use `?portfolio={id}` URL state for browser back/forward support (matches Analytics `?tab=` pattern)
- [ ] Add "+ Novo" button in sidebar header
- [ ] **Performance: Lazy-load portfolio detail on selection**, not all at once — fetch list on page load (1 call), fetch selected detail + track-record on demand (2 calls). Cache in `Map<string, PortfolioDetail>` to avoid refetching on re-selection

##### Acceptance Criteria

- [ ] Sidebar + detail layout matches Figma
- [ ] Portfolio selection is instant (client-side state, no navigation)

#### 3.2: Portfolio Detail Content

##### Files

```
frontends/wealth/src/routes/(team)/model-portfolios/+page.svelte
```

##### Tasks

- [ ] Header: portfolio name, "— Model Portfolio", benchmark composite, "Última revisão: {date}"
- [ ] Action buttons right-aligned: "Fact-sheet ↓" (outline), "Rebalancear" (outline), "Construir portfólio" (primary)
- [ ] 6 KPI cards in horizontal row: NAV Atual (with "Base 1.000"), YTD (green), CVaR 95% (red, "lim: -12.0%  77%"), Sharpe, Vol Anual ("rolling 12M"), Max Drawdown (red, "Mar-Jun 2022")
- [ ] Track-Record section: period return pills (MTD, YTD highlight, QTD, 1 Ano, 3 Anos*, Inception) with disclaimer "*inclui período de backtest (Jan 2020–Dez 2022)". **If `GET /model-portfolios/{id}/periodic-returns` not yet available, render EmptyState** "Retornos periódicos serão calculados quando dados de NAV histórico estiverem disponíveis." — avoid rabbit-holing into Carino linking (same complexity as `attribution_service.py`)
- [ ] Alocação por bloco: horizontal bars with asset class name, bar fill, percentage, fund count badge
- [ ] Stress Scenarios: table with columns Cenário, Drawdown, Recup, CVaR Imr — values in red

##### Acceptance Criteria

- [ ] All 6 KPIs display with correct formatting and colors
- [ ] Period returns cards match Figma YTD-highlighted style
- [ ] Allocation bars are color-coded per asset class
- [ ] Stress table data comes from `GET /model-portfolios/{id}/track-record` stress_scenarios field

---

### Phase 4: Risk Monitor Redesign

**Goal:** Match Figma frame "CVaR gauges + regime chart + drift" (node 1:7).

**Estimated scope:** ~3 files.

#### Figma Specification

- **CVaR 95% — Utilização por Portfólio** — horizontal bars per portfolio (Conservador green, Moderado green, Growth red exceeding limit), values "−6.8% / 8.0%" right-aligned, period buttons (1M, 3M, 6M, 12M)
- **Regime de Mercado — FRED Indicators** — area chart with colored background zones (RISK_ON blue, RISK_OFF orange, CRISE red, INFLAÇÃO), "RISK_OFF ativo" badge, line overlay
- **Macro indicator chips** — VIX 24.8 (green), Yield Curve −0.12% (red), OP Risk 3.1%, SAHM Rule 0.18, IG Spread 142bps (yellow), PMI Mfg 49.2
- **Drift Alerts** — table: fund name, DTW vs benchmark value, warning icon if > threshold. "Threshold: 0.60 · Acima é drift significativo vs benchmark"

#### 4.1: CVaR Utilization Bars

##### Files

```
frontends/wealth/src/routes/(team)/risk/+page.svelte
```

##### Tasks

- [ ] Replace CVaR status cards with horizontal utilization bar visualization
- [ ] Each portfolio: name label left, horizontal bar (green→yellow→red gradient), values right ("−6.8% / 8.0%")
- [ ] Bar extends past 100% marker when breaching limit (red overflow)
- [ ] Add period selector buttons (1M, 3M, 6M, 12M)
- [ ] Section title: "CVaR 95% — Utilização por Portfólio", subtitle "Rolling 12M · Limite configurado por perfil de risco"

##### Acceptance Criteria

- [ ] Bars show utilization vs limit visually
- [ ] Red overflow clearly visible for breaching portfolios

#### 4.2: Regime Area Chart

##### Tasks

- [ ] Replace empty RegimeChart with full area chart implementation
- [ ] Background zones colored by regime type (RISK_ON=blue, RISK_OFF=orange/amber, CRISE=red, INFLAÇÃO=pink)
- [ ] Line overlay showing VIX or composite indicator
- [ ] Legend: colored dots + regime type labels
- [ ] "RISK_OFF ativo" badge in chart header
- [ ] Chart uses ECharts markArea for regime zones

##### Acceptance Criteria

- [ ] Regime zones visible as colored background areas
- [ ] Current regime badge matches API response

#### 4.3: Macro Indicator Chips + Drift Alerts

##### Tasks

- [ ] Replace DataCard grid with inline chip row: VIX, Yield Curve, OP Risk, SAHM Rule, IG Spread, PMI Mfg
- [ ] Each chip: label above, value large below, colored text (green/red/neutral based on thresholds)
- [ ] Add Drift Alerts section (right panel, beside regime chart) with **two subsections**:
  - **DTW vs Benchmark** — table: Fund name, DTW score (colored: red > 0.60, orange > 0.40, green < 0.40). Source: `drift_monitor.py` (existing). Threshold note: "0.60 = drift significativo vs benchmark"
  - **Behavior Change** — table: Fund name, change score, changed metrics list. Source: `strategy_drift_detector.py` (Sprint 1 brainstorm). EmptyState if detector not yet deployed: "Behavior change detection disponível em Sprint 2"
- [ ] Both subsections consume `GET /risk/drift` which returns `{ dtw_alerts: [...], behavior_change_alerts: [...] }`

**Backend gap:** `GET /risk/drift` must return both signal types with a discriminator. When `strategy_drift_detector.py` is not deployed, `behavior_change_alerts` returns empty array (graceful degradation)

##### Acceptance Criteria

- [ ] 6 macro chips inline with colored values
- [ ] Drift table shows per-fund DTW scores with color coding

---

### Phase 5: Fund Universe / DD Pipeline Redesign

**Goal:** Match Figma frame "Fund Universe + DD Pipeline streaming" (node 1:6).

**Estimated scope:** ~4 files.

#### Figma Specification

- **Status tabs** — Todos (count), Aprovados, DD Pendente, Watchlist + "Adicionar fundo" button
- **Table columns** — Fundo (name + subcategory), Gestor, AUM, Estratégia (colored badge), Status (Aprovado/Watchlist/Pendente DD badge), DD Report (Completo/Gerando.../Pendente), Score, Atualizado
- **Right side panel** — Fund detail with tabs: Resumo, DD Report, Docs (count), Screening
  - Resumo: AUM, Gestor, Domicílio, Estrutura, Liquidez, Fee
  - DD Report in generation: progress bar (5 de 8 capítulos, ~2 min restantes), chapter list with status checkmarks/spinner
  - CTAs: "Abrir DD Report →", "Ver documentos (8)"

#### 5.1: Status Tabs + Enhanced Table

##### Files

```
frontends/wealth/src/routes/(team)/funds/+page.svelte
frontends/wealth/src/routes/(team)/funds/+page.server.ts
```

##### Tasks

- [ ] Replace dropdown filters with status tabs: Todos, Aprovados, DD Pendente, Watchlist (with counts)
- [ ] Add "Adicionar fundo" button right-aligned
- [ ] Add Estratégia column with colored badge (Senior Secured=teal, Long Only=blue, Fixed Income=purple, Risk Parity=yellow, EM Bonds=green, CTA/Trend=orange)
- [ ] Add Status column with colored badge (Aprovado=green, Watchlist=yellow, Pendente DD=gray)
- [ ] Add DD Report column with status (Completo=green, Gerando...=orange pulsing, Pendente=gray)
- [ ] Add Score column with numeric value
- [ ] Add sorting: "Ordenar: Score ↓"
- [ ] Row click opens side panel instead of navigating to detail page

##### Acceptance Criteria

- [ ] Tab counts update based on fund status distribution
- [ ] Strategy/status badges match Figma color scheme

#### 5.2: Fund Detail Side Panel

##### Files

```
frontends/wealth/src/routes/(team)/funds/+page.svelte
frontends/wealth/src/lib/components/FundDetailPanel.svelte   (NEW)
```

##### Tasks

- [ ] Use `ContextPanel` component for right-side fund detail
- [ ] Panel header: fund name, subcategory, AUM
- [ ] Panel tabs: Resumo, DD Report, Docs ({count}), Screening — use `Tabs` component with snippet-based content:
  ```svelte
  <Tabs items={panelTabs} bind:value={activePanel}>
    {#snippet children(tab)}
      {#if tab === "resumo"}
        {@render resumoContent()}
      {:else if tab === "dd-report"}
        {@render ddReportContent()}
      {/if}
    {/snippet}
  </Tabs>
  ```
- [ ] Resumo tab: key-value pairs (AUM, Gestor, Domicílio, Estrutura, Liquidez, Fee)
- [ ] DD Report tab: generation progress with chapter checklist (✓ done, ⟳ generating, ○ pending), progress fraction ("5 de 8 capítulos"), estimated time remaining
- [ ] DD report progress via SSE subscription per fund using `$effect` with `AbortController` cleanup:
  ```svelte
  $effect(() => {
    if (!selectedFund?.activeReportId) return;
    const controller = new AbortController();
    (async () => {
      const stream = await createSSEStream(`/dd-reports/${selectedFund.activeReportId}/stream`, { signal: controller.signal });
      for await (const event of stream) { /* update chapters state */ }
    })();
    return () => controller.abort();
  });
  ```
- [ ] CTAs: "Abrir DD Report →" (primary), "Ver documentos (8)" (outline)
- [ ] Use `$state.raw()` for fund detail data (replaced entirely on fund selection change)

##### Acceptance Criteria

- [ ] Side panel opens on row click, closes on Escape or click outside
- [ ] DD report chapter progress updates in real-time via SSE

---

### Phase 6: Analytics Redesign

**Goal:** Match Figma frame "Correlações + Pareto frontier" (node 1:2).

**Estimated scope:** ~3 files.

#### Figma Specification

- **Tabs** — Correlações (active), Backtest & Walk-Forward, Pareto Frontier, What-If Scenarios, **Atribuição de Performance** (new — brainstorm gap)
- **Filters** — Portfolio dropdown (Moderado), Date range (Jan 2023 — Mar 2026)
- **6 KPI cards** — Sharpe do Portfólio (1.57), Correlação Média (0.42), Diversificação Efetiva (2.8 fundos), Maior Correlação Par (0.78), Menor Correlação Par (0.08), Benchmark Corr. (0.84)
- **Matriz de Correlação** — fund-level heatmap (blue/yellow color scale), labels on both axes, correlation values in cells
- **Pareto Frontier** — scatter plot: Risk (CVaR 95%) X-axis, Return Y-axis, blue dots = individual funds, yellow dots = portfolio positions (Conservador, Moderado, Growth labeled), dashed line = efficient frontier, "Executar otimização" button

#### 6.1: Tab System + Filters

##### Files

```
frontends/wealth/src/routes/(team)/analytics/+page.svelte
frontends/wealth/src/routes/(team)/analytics/+page.server.ts
```

##### Tasks

- [ ] Add PageTabs: Correlações, Backtest & Walk-Forward, Pareto Frontier, What-If Scenarios, **Atribuição de Performance**
- [ ] Add portfolio dropdown filter (Conservative, Moderate, Growth)
- [ ] Add date range filter (from/to date pickers)
- [ ] Wire tab changes to URL `?tab=` parameter
- [ ] Each tab renders its own content section

##### Acceptance Criteria

- [ ] Tabs switch content without page reload
- [ ] Filters persist across tab switches

#### 6.2: Correlações Tab — KPIs + Heatmap

##### Tasks

- [ ] Add 6 KPI cards in horizontal row above correlation matrix
- [ ] KPI values computed from correlation matrix data (mean, max, min correlations)
- [ ] Correlation heatmap: fund names on both axes (not block names), blue/yellow color scale
- [ ] Cell values displayed inside heatmap cells
- [ ] Subtitle: "Retornos mensais · Jan 2023 – Mar 2026"
- [ ] Note at bottom for high correlations: "⚠ Vanguard ↔ Bridgewater: correlação 0.78 — sobreposição elevada. Considerar substituição de um dos dois."

**Backend:** Current `GET /analytics/correlation` works with block IDs. For fund-level correlation, may need to extend endpoint or add `GET /analytics/fund-correlation?portfolio_id={id}`.

##### Acceptance Criteria

- [ ] Heatmap renders with fund names (not block names)
- [ ] KPI cards compute from matrix data

#### 6.3: Pareto Frontier Tab

##### Tasks

- [ ] ScatterChart with Risk (CVaR 95%) on X-axis, Return on Y-axis
- [ ] Blue dots = individual funds from approved list
- [ ] Yellow/orange dots = current portfolio positions (labeled: Conservador, Moderado, Growth)
- [ ] Dashed line = efficient frontier computed from `POST /analytics/optimize/pareto`
- [ ] "Executar otimização" button triggers Pareto optimization
- [ ] Legend: "Portfólio atual · Linha eficiente · Fronteira eficiente · Pareto aqui · portfólios ótimos"

##### Acceptance Criteria

- [ ] Scatter chart renders funds + portfolios + frontier
- [ ] Optimization button triggers and updates chart

#### 6.4: Atribuição de Performance Tab (EmptyState until backend ready)

##### Tasks

- [ ] Add "Atribuição de Performance" as 5th tab in Analytics
- [ ] Render `EmptyState` with message: "Dados de benchmark necessários. Atribuição de performance será habilitada quando benchmark_data_ingestor.py estiver ativo."
- [ ] When `attribution_service.py` endpoint becomes available (`GET /analytics/attribution?portfolio_id={id}&period=YTD`), replace EmptyState with:
  - Attribution waterfall chart: allocation effect, selection effect, interaction effect per block
  - Table: Block, Weight Δ, Return Δ, Allocation, Selection, Total contribution
  - Period selector matching other tabs
- [ ] This is the **highest-impact engine from the brainstorm** (substitui 2-3 analistas, é onde o comitê decide) — UI home must exist before backend delivers

##### Acceptance Criteria

- [ ] Tab exists and renders EmptyState cleanly
- [ ] When backend attribution endpoint is available, tab renders attribution breakdown

**Backend dependency:** `attribution_service.py` depends on `benchmark_data_ingestor.py`. Not blocking Phase 6 — EmptyState placeholder is the correct approach.

---

### Phase 7a: Exposure Monitor — Heatmaps (NEW)

**Goal:** Geographic + sector heatmap tables from Figma frame "Heatmaps geo/setor + leading alerts" (node 1:8).

**Estimated scope:** ~4 files (2 frontend + 2 backend).

**Data already exists in `instruments_universe.attributes` — straightforward aggregation.**

#### Figma Specification

- **Exposição Geográfica** — table-heatmap: rows = portfolios, columns = regions (North America, Europe, EM Asia, EM LATAM, Global/Other), cells = % weight with color intensity
- **Exposição Setorial** — table-heatmap: rows = portfolios, columns = sectors (Technology, Financials, Healthcare, Energy, Real Assets, Fixed Inc), cells = % weight with color intensity
- **Toggle** — "Portfólios" / "Por gestor" switches aggregation level
- **Leading Indicator Alerts** — cards connecting FRED indicators to exposure positions, with WARN/MONITOR/OK badges
- **Freshness dos Holdings** — fund name badges with "X dias" since last update, colored by staleness

#### 7.1: Backend — Exposure Endpoints

##### Files

```
backend/app/domains/wealth/routes/exposure.py       (NEW)
backend/app/domains/wealth/schemas/exposure.py      (NEW)
```

##### Tasks

- [ ] `GET /exposure/matrix?dimension=geographic|sector&aggregation=portfolio|manager` — single endpoint, query param selects pivot dimension. Returns exposure matrix (row × column → weight %). **Use `Literal["geographic", "sector"]` for dimension param** (not freeform string)
- [ ] `GET /exposure/metadata` — returns both freshness timestamps and leading-indicator alerts in one response (displayed on same page, fetched together)
- [ ] **Security: Use `Literal["portfolio", "manager"]` for aggregation param**. Require `get_current_user` + RLS. Consider restricting to INVESTMENT_TEAM role
- [ ] Data source: aggregate from fund holdings × allocation weights per portfolio (`instruments_universe.attributes` for geography/sector keys)
- [ ] Register router in `__init__.py`
- [ ] Add tests

##### Acceptance Criteria

- [ ] All 4 endpoints return valid data
- [ ] Tests pass in `make check`

#### 7.2: Frontend — Exposure Monitor Page

##### Files

```
frontends/wealth/src/routes/(team)/exposure/+page.svelte       (NEW)
frontends/wealth/src/routes/(team)/exposure/+page.server.ts    (NEW)
```

##### Tasks

- [ ] Add `/exposure` route to nav items in root layout
- [ ] Page header: "Exposure Monitor", breadcrumb "Exposição geográfica · Exposição setorial"
- [ ] Toggle button group: "Portfólios" / "Por gestor"
- [ ] Geographic exposure: `HeatmapTable` with colored cells (green→yellow→orange intensity scale)
- [ ] Sector exposure: same `HeatmapTable` pattern, different dimension
- [ ] Freshness badges: fund name + "X dias" pill, colored by staleness (green < 30d, yellow 30-60d, red > 60d)
- [ ] Fetch `GET /exposure/matrix?dimension=geographic` + `GET /exposure/metadata` in parallel

##### Acceptance Criteria

- [ ] Both heatmap tables render with correct color scaling using `HeatmapTable` component (NOT ECharts)
- [ ] Toggle switches between portfolio and manager aggregation
- [ ] Freshness badges show per-fund staleness

---

### Phase 7b: Exposure Monitor — Leading Indicator Alerts (BACKLOG)

**Goal:** Connect FRED indicators to geographic/sector exposure positions with WARN/MONITOR/OK alerts.

**Status:** **Backlog** — requires domain analysis decision on which FRED indicator maps to which exposure. This is the hardest item in the plan (analysis de domínio, not code). Can ship Phase 7a without it.

**When ready:**
- [ ] Leading Indicator Alerts section below heatmaps: cards with title, FRED indicator reference, exposure connection, action recommendation, WARN/MONITOR/OK badge
- [ ] Data from `GET /exposure/metadata` (leading_indicators field)
- [ ] Business logic: define mapping rules (e.g., PMI EM Asia < 50 → WARN on EM Asia geographic exposure > 15%)

**Dependency:** Decision on which indicators map to which exposures. Not a code problem — a business analysis problem. Separate from Phase 7a.

---

### Phase 8: Screener (NEW)

**Goal:** Implement Figma frame "Instrument Screener" (node 1:3).

**Estimated scope:** ~4 files. Backend already ready.

#### Figma Specification

- **Funil de Screening** — sidebar visual pipeline: 2.847 no universo → L1: 1.924 passaram → L2: 891 elegíveis → L3: 312 PASS + 421 WATCHLIST
- **Filtros** — Tipo (Fundos/Bonds/Equities), Status (PASS/WATCHLIST/FAIL), Bloco de alocação, Camada de reprovação
- **Tabs** — Todos (912), PASS (312), WATCHLIST (421), FAIL (158) + "Ordenar: Score ↓"
- **Table** — Instrumento (name+ISIN+gestor), Tipo (badge), Bloco Elegível, L1/L2/L3 (green/red dots), Score L3, Status (PASS/WATCH/FAIL badge), DD Requerido
- **Side panel** — Instrument detail:
  - Score badge (PASS 0.87)
  - Camada 1 — Eliminatórios: AUM mínimo, Track record, Domicílio, etc. (✓/✗)
  - Camada 2 — Mandato: Asset class, Estratégia, Fee máximo, Geografia (✓/✗)
  - Camada 3 — Score Quant: Sharpe (weight, value, percentile), MaxDrawdown, % meses positivos, Correlação diversificação
  - Blocos elegíveis badges
  - CTAs: "Iniciar DD Report →", "Histórico"
- **Header** — "Último batch: Domingo 02:00 UTC", "587 testados ✓", "Executar batch" button

#### 8.1: Screener Page + Funnel Sidebar

##### Files

```
frontends/wealth/src/routes/(team)/screener/+page.svelte       (NEW)
frontends/wealth/src/routes/(team)/screener/+page.server.ts    (NEW)
```

##### Tasks

- [ ] Add `/screener` route to nav items in root layout
- [ ] Screening funnel sidebar: pipeline stages as connected boxes (universe → L1 → L2 → L3 result)
  - Each stage: count, label, colored connector line
  - Stage counts from latest screening run metadata
- [ ] Filter chips: Tipo, Status, Bloco, Camada de reprovação — toggleable pill buttons
- [ ] Status tabs: Todos, PASS, WATCHLIST, FAIL — each with count badge
- [ ] Fetch data: `GET /screener/results?limit=500` + `GET /screener/runs?limit=1`
- [ ] "Executar batch" button: `POST /screener/run` → show progress/confirmation

##### Acceptance Criteria

- [ ] Funnel visualization shows correct counts
- [ ] Tabs filter results by status
- [ ] Batch execution triggers and shows feedback

#### 8.2: Screener Results Table

##### Tasks

- [ ] Table columns: Instrumento (name + ISIN/ticker + gestor), Tipo (Fund/Bond/Equity badge), Bloco Elegível, L1 (dot), L2 (dot), L3 (dot), Score L3 (numeric), Status (PASS/WATCHLIST/FAIL badge), DD Requerido
- [ ] L1/L2/L3 dots: green = pass, red = fail, gray = not reached
- [ ] Score column: colored by range (green > 0.7, yellow 0.4-0.7, red < 0.4)
- [ ] Sort by Score descending default
- [ ] Row click opens instrument detail side panel

##### Acceptance Criteria

- [ ] All columns render with correct badges and dots
- [ ] Sorting works on Score and other numeric columns

#### 8.3: Instrument Detail Side Panel

##### Tasks

- [ ] Use `ContextPanel` for right-side instrument detail
- [ ] Header: instrument name, type, ISIN, manager
- [ ] Score badge: large circle with score value + PASS/FAIL/WATCHLIST label
- [ ] Camada 1 — Eliminatórios: checklist of criteria (✓ pass with value, ✗ fail with value)
- [ ] Camada 2 — Mandato: checklist + eligible blocks as badges
- [ ] Camada 3 — Score Quant: table with Metric, Weight, Value, Percentile columns
  - "P = percentil dentro do peer group (Global Equity DM · 841 pares)"
- [ ] CTAs: "Iniciar DD Report →" (primary), "Histórico" (outline)
- [ ] Fetch: `GET /screener/results/{instrument_id}` for layer detail

##### Acceptance Criteria

- [ ] All 3 layers display with correct pass/fail indicators
- [ ] Quant score table shows percentile ranks
- [ ] "Iniciar DD Report" triggers DD generation for instrument

---

### Phase 9: MERGED INTO PHASES 1, 7, 8

> **Eliminated per simplicity review.** Tasks distributed:
> - SVG icon replacement + dark skeletons → Phase 1.3 (hardcoded light-mode fixes)
> - Exposure Monitor nav item → Phase 7.2 (when page is created)
> - Screener nav item → Phase 8.1 (when page is created)
> - Responsive testing → continuous acceptance criterion across all phases
> - Investor portal dark theme → Phase 1.1 (InvestorShell keeps light defaults via separate branding fallback)

**Total phases: 8 (was 9)**

---

## System-Wide Impact

### Interaction Graph

Token change in `tokens.css` → consumed by all `@netz/ui` components → affects all 3 frontends (wealth, credit, investor portals). Credit frontend inherits dark theme automatically unless it has its own branding override.

### Error Propagation

- Branding API failure → `defaultBranding` fallback (dark theme) → no visual break
- Missing token → CSS `var()` fallback value → component still renders (may have wrong color)
- New backend endpoints (Phase 7) failure → EmptyState on Exposure Monitor page

### State Lifecycle Risks

- **ContextPanel state** — opening side panel while SSE streams DD progress. Panel close should unsubscribe from SSE.
- **Tab state in URL** — Analytics tabs use `?tab=` param. Browser back/forward should work correctly.
- **Portfolio selection** — Model Portfolios sidebar selection is client-state only, not persisted to URL.

### API Surface Parity

- Existing endpoints used by current pages: no changes needed
- New `GET /exposure/*` endpoints: only consumed by Exposure Monitor page
- `GET /risk/drift` endpoint: may need to be added for Risk Monitor drift alerts

---

## Acceptance Criteria

### Functional Requirements

- [ ] All 7 Figma frames have corresponding pages in the wealth frontend
- [ ] Dark theme renders correctly across all pages
- [ ] Admin can override any token via branding API and see changes reflected
- [ ] All existing backend tests pass (`make check`)
- [ ] New exposure endpoints have tests

### Non-Functional Requirements

- [ ] WCAG 2.1 AA contrast on all text/background combinations
- [ ] Pages render under 2s on dev server (no unnecessary API calls)
- [ ] ECharts charts adapt automatically to dark theme via CSS variable reading

### Quality Gates

- [ ] `make check` passes (lint + typecheck + test)
- [ ] Visual validation in browser for each page against Figma screenshots
- [ ] Zero hardcoded color values in `.svelte` files

---

## Backend Gaps (from SpecFlow Analysis)

The following backend work is **required** before the corresponding frontend phases can be completed. These should be implemented as part of or immediately before their respective phases.

### Phase 2 Prerequisites

| Gap | Resolution |
|---|---|
| Dashboard SSE not connected — `riskAlerts` state exists but no `$effect` subscribes to `/risk/stream` | Wire SSE subscription in `$effect()` with cleanup on unmount |
| PortfolioCard has no click handler — no way to navigate to model portfolio detail | Add `onclick` + resolve `profile → portfolio.id` mapping from `modelPortfolios` data |

### Phase 3 Prerequisites

| Gap | Resolution |
|---|---|
| Track-record periodic returns — endpoint returns nulls, no MTD/QTD/1Y/3Y/Inception | **Use EmptyState for now.** Computing MTD/QTD/YTD/Inception correctly with Carino linking is the same problem as `attribution_service.py` — scope creep risk. Add `GET /model-portfolios/{id}/periodic-returns` in a dedicated Sprint when NAV history and benchmark data are ready |
| No allocation-by-block aggregation for specific portfolio | Aggregate from `fund_selection_schema` by `block_id` — can be client-side or new endpoint |
| Stress scenarios in track-record — may return null | Accept null gracefully; show EmptyState in stress table |

### Phase 4 Prerequisites

| Gap | Resolution |
|---|---|
| Missing macro indicators — OP Risk, SAHM, IG Spread, PMI not in FRED ingestion | Add FRED series: OPHNFB (OP Risk), SAHMREALTIME (SAHM), BAMLC0A0CM (IG Spread), ISM PMI. Extend `/risk/macro` response |
| No `GET /risk/drift` endpoint — DTW scores not exposed via API | Add `GET /risk/drift` returning **both signals**: `{ dtw_alerts: DtwAlert[], behavior_change_alerts: BehaviorChangeResult[] }`. DTW from `drift_monitor.py` (existing), behavior change from `strategy_drift_detector.py` (Sprint 1 brainstorm). Use type discriminator so frontend renders both in Drift Alerts section |
| Correlation Monitor has no UI home (Sprint 2 backend) | Add as future section in Risk Monitor (after regime chart) or Analytics tab. Not blocking — note in backend gaps for Sprint 2 planning |

### Phase 5 Prerequisites

| Gap | Resolution |
|---|---|
| Fund Universe + DD Pipeline are separate routes | Merge into single `/funds` route with status tabs. DD report progress fetched per-fund when side panel opens |
| DD Report SSE for chapter progress | Already exists: `GET /dd-reports/{id}/stream`. Wire in side panel component |

### Phase 7 Prerequisites (blocking — no backend exists)

| Gap | Resolution |
|---|---|
| No exposure endpoints at all | Build 4 new endpoints (geographic, sector, freshness, leading-indicators). Data from `instruments_universe.attributes` aggregated by portfolio weights |
| Leading indicator → exposure connection logic | Map FRED indicators (VIX, yield curve, PMI) to relevant geo/sector exposures. Business logic needed |

### Phase 8 Prerequisites

| Gap | Resolution |
|---|---|
| Screening is synchronous — blocks until complete | **MVP:** Show loading spinner → render final results. **Future:** SSE progressive streaming |
| Funnel counts not aggregated | Compute client-side from `ScreeningResultRead.failed_at_layer` field. No new endpoint needed |
| `layer_results` schema is `dict[str, Any]` | Define TypeScript interfaces for L1/L2/L3 layer result shapes based on screener service output |

---

## Critical Design Decisions

These questions should be resolved before starting implementation:

| # | Question | Decision (from research) |
|---|---|---|
| Q1 | Dark-only or light/dark toggle? | **`data-theme` attribute system** — dark as default for wealth, light for credit. Supports future toggle via localStorage + cookie. No `prefers-color-scheme` (admin controls theme) |
| Q2 | Fund Universe + DD Pipeline merged? | **Yes** — single `/funds` route with tabs + side panel |
| Q3 | Screener progressive funnel animation? | **No** — loading spinner → final counts. Server-side pagination for results (not client-side 2847 rows) |
| Q4 | Exposure data source? | `instruments_universe.attributes` (geography/sector keys). 2 endpoints not 4 |
| Q5 | Branding admin UI this sprint? | **No** — headless API only, admin UI is follow-up |
| Q6 | ECharts dark theme approach? | Register ONCE in `echarts-setup.ts` reading CSS vars. `MutationObserver` on `<html>` data-theme for re-registration. NOT per ChartContainer |
| Q7 | Investor portal keeps light theme? | **Yes** — `defaultBranding` (light) unchanged. Wealth uses `defaultDarkBranding`. InvestorShell also uses light fallback |
| Q8 | SSE primitive? | `createSubscriber` from `svelte/reactivity` (lazy, shareable) over raw `$effect` with AbortController |
| Q9 | Exposure Monitor heatmaps? | **HTML `HeatmapTable`**, NOT ECharts HeatmapChart (saves 2 chart instances, simpler) |
| Q10 | BrandingConfig extension scope? | **2 new fields** (surface_elevated, surface_inset). Chart/semantic colors CSS-only |

---

## Dependencies & Prerequisites

- **Figma access** for reference screenshots during implementation
- **Backend running** for data to populate pages (Docker: `make up && make serve`)
- **Track-record data** in database for dashboard NAV chart (may need seed data)
- **Screening run data** for screener page (run `POST /screener/run` to populate)

## Risk Analysis

| Risk | Mitigation |
|---|---|
| Dark theme breaks credit frontend | Credit has separate branding config; test in isolation |
| ECharts colors invisible on dark | ChartContainer already reads `--netz-chart-*` vars; verify |
| @tanstack/svelte-table Svelte 5 breakage | Known issue (see memory); may need workaround or upgrade |
| Investor portal affected by dark tokens | InvestorShell may need its own branding defaults (light for investor-facing) |
| Exposure backend queries slow (joins across holdings × allocations) | Add materialized view or cache; acceptable for MVP with warning |
| Svelte 5.29+ required for `@attach` pattern | Check installed Svelte version; if < 5.29, keep `$effect` for chart lifecycle |
| `$state.raw()` requires full object replacement (no mutation) | Only use for API response data that gets replaced entirely on refetch |
| Optional chaining in `$effect` breaks dependency tracking | Read all reactive dependencies before conditional checks (see patterns section) |

## Sources & References

### Internal References

- Design tokens: `packages/ui/src/lib/styles/tokens.css`
- Branding system: `packages/ui/src/lib/utils/branding.ts`
- Chart system: `packages/ui/src/lib/charts/ChartContainer.svelte`
- Existing dashboard: `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`
- Screener backend: `backend/app/domains/wealth/routes/screener.py`
- Frontend admin plan: `docs/plans/2026-03-16-feat-frontend-admin-platform-plan.md`

### Figma Frames

| Frame | Node ID | Page |
|---|---|---|
| Dashboard com portfólios + NAV chart + alertas | 1:4 | Dashboard |
| Model Portfolios com track-record | 1:5 | Model Portfolios |
| CVaR gauges + regime chart + drift | 1:7 | Risk Monitor |
| Fund Universe + DD Pipeline streaming | 1:6 | Fund Universe |
| Correlações + Pareto frontier | 1:2 | Analytics |
| Heatmaps geo/setor + leading alerts | 1:8 | Exposure Monitor |
| Instrument Screener | 1:3 | Screener |
