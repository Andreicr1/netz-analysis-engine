# shadcn/ui Gap Analysis — Wealth Frontend

**Date:** 2026-04-02
**Scope:** `frontends/wealth/` vs `@investintell/ui` (packages/ui/) shadcn primitives
**Figma Reference:** https://www.figma.com/design/hjrBXc90IlR5SHE2HiFGEU/-shadcn-ui---Design-System--Community-

---

## Executive Summary

The gap is at **two levels**: foundation tokens AND component adoption.

**Foundation gap:** The design token system uses custom values (IBM Plex Sans, institutional blue palette, elevated buttons) instead of shadcn/ui standard (Inter, Tailwind Slate, flat buttons).

**Component gap:** The `@investintell/ui` package ships **55 shadcn/ui primitive directories** (via bits-ui). The Wealth frontend only imports **9 of them directly** — 46 primitives are available but unused, with custom/ad-hoc implementations in their place.

---

## Foundation Token Gap

**Active package:** `packages/investintell-ui/` (`@investintell/ui`) — uses `--ii-*` token prefix.

| Token Layer | Current (`--ii-*`) | shadcn/ui Official | Gap |
|---|---|---|---|
| **Font family (sans)** | IBM Plex Sans | **Inter** | Font swap needed |
| **Font family (mono)** | IBM Plex Mono | **Geist Mono / Menlo** | Font swap needed |
| **h1** | 30px SemiBold | **48px ExtraBold** | Size + weight differ |
| **h2** | 26px SemiBold | **30px SemiBold** | Size differs |
| **h3** | 22px SemiBold | **24px SemiBold** | Size differs |
| **h4** | 1.125rem SemiBold | **20px SemiBold** | Match |
| **Color base** | Zinc neutral + Gold accent (#c9a84c) | **Tailwind Slate** (#0f172a → #f8fafc) | Palette swap (Zinc→Slate) |
| **Theme default** | Dark-first (`:root` = dark) | **Light-first** | Invert default |
| **Brand accent** | Gold (#c9a84c dark / #9a7a2e light) | **None** (neutral) | Keep for charts, remove from buttons |
| **Surface bg (light)** | #fafafa (zinc-50) | **#ffffff** (white) | Minor |
| **Borders (light)** | #d4d4d8 (zinc-300) | **#e2e8f0** (slate-200) | Lighter, cooler |
| **Button default** | Gold (`--primary` → `--ii-brand-primary`) | **Slate-900** (#0f172a) flat | Major visual change |
| **Button hover** | Color change only (current) | **Color change only** | OK — no lift in current system either |
| **Danger** | #da3633 (light) / #f85149 (dark) | **#ef4444** (red-500) | Close, minor shift |

---

## Component Adoption Gap

| Metric | Value |
|---|---|
| shadcn primitives available in package | **55** |
| shadcn primitives used directly in Wealth | **9** |
| Primitives available but **not used** | **46** |
| **Adoption rate** | **16%** |

---

## Primitives Available in `@investintell/ui`

```
accordion        alert            alert-dialog     aspect-ratio     avatar
badge            breadcrumb       button           button-group     calendar
card             carousel         chart            checkbox         collapsible
command          context-menu     data-table       dialog           drawer
dropdown-menu    empty            field            form             hover-card
input            input-group      input-otp        item             kbd
label            menubar          native-select    navigation-menu  pagination
popover          progress         radio-group      range-calendar   resizable
scroll-area      select           separator        sheet            sidebar
skeleton         slider           sonner           spinner          switch
table            tabs             textarea         toggle           toggle-group
tooltip
```

---

## Detailed Status per Primitive

### Currently Used (9)

| Component | Import Path | Usage Locations |
|---|---|---|
| **Button** | `@investintell/ui/components/ui/button` | 35+ files — AllocationView, BlendedBenchmarkEditor, UniverseView, FundsView, screener panels, model-portfolio, DD reports, rebalancing |
| **Badge** | `@investintell/ui/components/ui/badge` | UniverseView, PortfolioCard, FundsView |
| **Skeleton** | `@investintell/ui/components/ui/skeleton` | UniverseView, FundsView, InstrumentsView, ExposureView |
| **Input** | `@investintell/ui/components/ui/input` | BlendedBenchmarkEditor |
| **Card** | `@investintell/ui/components/ui/card` | RebalancingTab, IngestionProgress |
| **Switch** | `@investintell/ui/components/ui/switch` | investment-policy page |
| **Chart** | `@investintell/ui/charts` | Via ChartContainer wrapper (all chart components) |
| **DataTable** | `@investintell/ui` barrel | Via DataTable wrapper (screener, universe, instruments) |
| **Sonner** | `@investintell/ui` barrel | Via Toast wrapper |

### Available but NOT Used (46)

| Component | Current Implementation | Where It Should Replace |
|---|---|---|
| **Accordion** | Custom collapsible lists | DD chapter navigation, settings sections |
| **Alert** | `StaleBanner`, `AlertBanner` wrappers with custom markup | All warning/info banners |
| **Alert Dialog** | `ConfirmDialog`/`ConsequenceDialog` wrappers | Destructive action confirmations |
| **Aspect Ratio** | Not used | Image/video containers (fact sheets, PDFs) |
| **Avatar** | Icon-only user menu | User menu, manager profiles, fund logos |
| **Breadcrumb** | Custom breadcrumb in `PageHeader` | All page headers |
| **Calendar** | Custom date picker in macro views | Macro date selection, report date ranges |
| **Carousel** | Not used | Fund card carousels, report galleries |
| **Checkbox** | `<input type="checkbox">` raw HTML | Filter sidebars (6+ instances: CatalogFilterSidebar, InstrumentFilterSidebar, ManagerFilterSidebar, SecuritiesFilterSidebar, ScreenerFilters) |
| **Collapsible** | Custom expand/collapse divs | Filter groups, detail sections |
| **Command** | Custom search implementation | GlobalSearch (Cmd+K palette) |
| **Context Menu** | Not used | Table row actions, fund card actions |
| **Dialog** | `ConfirmDialog`/`SimpleDialog` wrappers | All modal dialogs |
| **Drawer** | Custom slide-in div | AiAgentDrawer |
| **Dropdown Menu** | Custom action menus | Portfolio actions, fund actions, export menus |
| **Form** | Ad-hoc form markup | All forms (settings, filters, construction wizard) |
| **Hover Card** | Not used | Fund/manager preview on hover |
| **Input OTP** | Not applicable | — |
| **Label** | `<label>` raw HTML | All form labels |
| **Menubar** | Not used | — |
| **Navigation Menu** | Custom sidebar | Top-level navigation (if needed) |
| **Pagination** | Custom pagination buttons | Screener tables, catalog, instrument lists |
| **Popover** | Custom positioned divs | ScoreBreakdownPopover, macro tooltips, filter dropdowns |
| **Progress** | Custom progress bar | IngestionProgress, DD report generation, long-running actions |
| **Radio Group** | Not used | Screening mode selection, construction methodology |
| **Range Calendar** | Not used | Date range pickers (macro, reports) |
| **Resizable** | Fixed-width panels | Master-detail layouts (screener, analytics) |
| **Scroll Area** | `overflow-auto` CSS | Long lists in side panels, filter sidebars, log feeds |
| **Select** | `Select` wrapper from barrel (not shadcn direct) | All dropdowns should use shadcn Select |
| **Separator** | `<hr>` or `border-b` Tailwind | Section dividers throughout |
| **Sheet** | Custom slide-in `<div>` panels | FundDetailPanel, CatalogDetailPanel, all side panels |
| **Sidebar** | Custom `AppLayout` sidebar | Main navigation sidebar |
| **Slider** | `<input type="number">` | Weight inputs, threshold sliders |
| **Spinner** | Inline SVG animation | Loading states (should use shadcn Spinner) |
| **Table** | `DataTable` wrapper or raw `<table>` | Simple tables without sorting/filtering |
| **Tabs** | Custom `<button>` groups | Portfolio tabs, screener tabs, analytics entity tabs, DD report chapters |
| **Textarea** | Not detected in Wealth | AI chat input, notes, rationale fields |
| **Toggle** | Custom toggle buttons | View mode toggles (list/grid/kanban) |
| **Toggle Group** | Custom button groups | PeriodSelector (1M/3M/6M/1Y/3Y/5Y/10Y), view modes |
| **Tooltip** | echarts tooltips only (no UI tooltips) | Metric explanations, abbreviated values, icon buttons |

---

## Top 10 Gaps by Impact

Priority based on: frequency of occurrence x visual inconsistency x effort to fix.

| # | Gap | Occurrences | Affected Components | shadcn Primitive | Effort |
|---|---|---|---|---|---|
| 1 | **Tabs custom** | 15+ tab groups | Portfolio tabs, screener tabs, analytics entity tabs, DD chapters, macro tabs | `Tabs` | Medium |
| 2 | **Sheet/Drawer custom** | 8+ panels | FundDetailPanel, CatalogDetailPanel, InstrumentDetailPanel, ManagerDetailPanel, AiAgentDrawer, LongFormReportPanel | `Sheet` / `Drawer` | Medium |
| 3 | **Pagination custom** | 6+ tables | CatalogTable, InstrumentTable, SecManagerTable, SecuritiesTable, SecHoldingsTable | `Pagination` | Low |
| 4 | **Checkbox raw HTML** | 6+ sidebars | CatalogFilterSidebar, InstrumentFilterSidebar, ManagerFilterSidebar, SecuritiesFilterSidebar, ScreenerFilters | `Checkbox` | Low |
| 5 | **Label raw HTML** | 20+ forms | All filter sidebars, settings, construction wizard, benchmark editor | `Label` | Low |
| 6 | **Separator ad-hoc** | 30+ dividers | Section dividers across all pages | `Separator` | Low |
| 7 | **Scroll Area CSS-only** | 10+ lists | Side panels, filter sidebars, log feeds, dropdown lists | `Scroll Area` | Low |
| 8 | **Toggle Group custom** | 5+ selectors | PeriodSelector, view mode toggles (list/kanban/grid) | `Toggle Group` | Low |
| 9 | **Dropdown Menu custom** | 8+ menus | Portfolio actions, fund actions, export menus, user menu | `Dropdown Menu` | Medium |
| 10 | **Popover custom** | 5+ popovers | ScoreBreakdownPopover, macro indicator tooltips, filter dropdowns | `Popover` | Low |

---

## Composite Components Missing from Package

These are standard shadcn/ui patterns built from composing primitives:

| Composite | Primitives Used | Use Case in Wealth |
|---|---|---|
| **Date Picker** | Calendar + Popover | Macro date selection, report date ranges, filter date fields |
| **Combobox** | Command + Popover | Fund search/select, benchmark picker, series picker |
| **Data Table (full)** | Table + Pagination + Dropdown Menu + Checkbox | Screener tables (currently DataTable wrapper exists but doesn't use all shadcn sub-components) |

---

## Analytical Wrapper Layer (`@investintell/ui` barrel exports)

These domain-aware components wrap shadcn primitives. They are correctly abstracted and should **continue to exist** — but should be refactored to use shadcn primitives internally where they currently use raw HTML.

| Wrapper | Uses shadcn internally? | Should use |
|---|---|---|
| `DataTable` | Partially (TanStack Table) | `Table` + `Pagination` + `Checkbox` |
| `ConfirmDialog` | Partially | `Alert Dialog` |
| `ConsequenceDialog` | Partially | `Alert Dialog` |
| `SimpleDialog` | Partially | `Dialog` |
| `Select` (wrapper) | Partially | `Select` (shadcn direct) |
| `MetricCard` | No (raw divs) | `Card` |
| `StatusBadge` | No (raw spans) | `Badge` |
| `EmptyState` | No (raw divs) | `Card` or custom (OK as-is) |
| `PeriodSelector` | No (raw buttons) | `Toggle Group` |
| `ActionButton` | Partial (uses Button) | OK as-is |
| `FormField` | No (raw label+div) | `Field` + `Label` |
| `SectionCard` | No (raw divs) | `Card` + `Separator` |
| `PageHeader` | No (raw breadcrumb) | `Breadcrumb` |

---

## Recommended Migration Order

### Phase 1 — Low-hanging fruit (mechanical replacements, low risk)
1. `Checkbox` — replace raw `<input>` in filter sidebars
2. `Label` — replace raw `<label>` in forms
3. `Separator` — replace `<hr>` and `border-b` dividers
4. `Spinner` — replace inline SVG loaders
5. `Tooltip` — add to icon buttons and abbreviated values

### Phase 2 — High-impact structural (medium effort)
6. `Tabs` — replace custom tab groups across all pages
7. `Sheet` — replace custom side panels (FundDetailPanel, CatalogDetailPanel, etc.)
8. `Pagination` — replace custom pagination in screener tables
9. `Toggle Group` — replace PeriodSelector and view mode toggles
10. `Scroll Area` — replace `overflow-auto` in side panels and lists

### Phase 3 — Wrapper refactoring (internal, no visible change)
11. `MetricCard` → use `Card` internally
12. `StatusBadge` → use `Badge` internally
13. `FormField` → use `Field` + `Label` internally
14. `PageHeader` → use `Breadcrumb` internally
15. `PeriodSelector` → use `Toggle Group` internally
16. `ConfirmDialog` → use `Alert Dialog` internally

### Phase 4 — Composite patterns
17. Build `DatePicker` composite (Calendar + Popover)
18. Build `Combobox` composite (Command + Popover)
19. Refactor `GlobalSearch` to use `Command`
20. Refactor `DataTable` to use `Table` + `Pagination` + `Checkbox`

---

## Files with Highest Concentration of Non-shadcn Patterns

| File | Issues | Priority |
|---|---|---|
| `screener/CatalogFilterSidebar.svelte` | checkbox, label, separator, scroll-area, collapsible | High |
| `screener/InstrumentFilterSidebar.svelte` | checkbox, label, separator, scroll-area | High |
| `screener/ManagerFilterSidebar.svelte` | checkbox, label, separator | High |
| `screener/CatalogTable.svelte` | pagination, dropdown-menu | High |
| `FundDetailPanel.svelte` | sheet, tabs, scroll-area, separator | High |
| `AllocationView.svelte` | tabs, table, separator | Medium |
| `analytics/entity/ReturnStatisticsPanel.svelte` | tooltip, separator | Medium |
| `model-portfolio/ConstructionAdvisor.svelte` | form, label, radio-group, separator | Medium |
| `GlobalSearch.svelte` | command (should use Command primitive) | Medium |
| `macro/SeriesPicker.svelte` | combobox pattern (Command + Popover) | Medium |
