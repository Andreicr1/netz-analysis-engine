# Unified Screener — Reference

**Date:** 2026-03-26
**Route:** `/screener` (SvelteKit — `frontends/wealth/src/routes/(app)/screener/`)
**Replaces:** `/screener` (old instrument-only) + `/us-fund-analysis` (deleted)

---

## 1. Overview

The Unified Screener is the single entry point for fund discovery and manager analysis in the Wealth frontend. It consolidates three previously separate workflows into one tabbed "Single Pane of Glass":

| Tab | Data Source | Backend Endpoint | Scope |
|-----|------------|-----------------|-------|
| **Fund Catalog** (default) | 3-universe UNION ALL | `GET /screener/catalog` | Global (no RLS) |
| **Managers** | SEC ADV/13F | `GET /sec/managers/search` | Global |
| **Equities** | `instruments_universe` | `GET /screener/search` | Tenant (RLS) |
| **Fixed Income** | `instruments_universe` | `GET /screener/search` | Tenant (RLS) |
| **ETF** | `instruments_universe` | `GET /screener/search` | Tenant (RLS) |

---

## 2. Fund Catalog — Three Universes

The catalog tab queries `GET /screener/catalog` which performs a UNION ALL across three global tables:

| Universe | Table | PK | Disclosure |
|----------|-------|----|-----------|
| `registered_us` | `sec_registered_funds` | `cik` | Holdings (N-PORT), NAV (YFinance), Style Analysis, 13F overlay |
| `private_us` | `sec_manager_funds` | `id` (UUID) | Private fund data (GAV, investor_count) only |
| `ucits_eu` | `esma_funds` (ticker != NULL) | `isin` | NAV (YFinance) only — no holdings or style |

### 2.1 DisclosureMatrix

Every `UnifiedFundItem` carries a `disclosure: DisclosureMatrix` object that determines which UI panels are available:

```typescript
interface DisclosureMatrix {
  has_holdings: boolean;        // N-PORT for registered, false otherwise
  has_nav_history: boolean;     // Requires YFinance ticker
  has_quant_metrics: boolean;   // Requires NAV history
  has_private_fund_data: boolean; // Schedule D (GAV, investor_count)
  has_style_analysis: boolean;  // N-PORT style snapshots
  has_13f_overlay: boolean;     // 13F via sec_entity_links
  has_peer_analysis: boolean;   // >=3 peers in same fund_type
  holdings_source: "nport" | "13f" | null;
  nav_source: "yfinance" | null;
  aum_source: "nport" | "schedule_d" | "yfinance" | null;
}
```

**Rules by universe:**

| Flag | US Registered | US Private | EU UCITS |
|------|:------------:|:----------:|:--------:|
| `has_holdings` | `true` (nport) | `false` | `false` |
| `has_nav_history` | `true` | `false` | `true` (if ticker) |
| `has_quant_metrics` | `true` | `false` | `true` (if ticker) |
| `has_style_analysis` | `true` | `false` | `false` |
| `has_private_fund_data` | `false` | `true` | `false` |
| `has_13f_overlay` | possible | possible | `false` |

### 2.2 Backend Endpoints

**`GET /api/v1/wealth/screener/catalog`**

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Text search (name, ticker, ISIN, manager) |
| `region` | string | `US` or `EU` |
| `fund_universe` | string | `registered_us`, `private_us`, `ucits_eu` (comma-separated) |
| `fund_type` | string | `mutual_fund`, `etf`, `hedge_fund`, `pe`, `vc`, `ucits` (comma-separated) |
| `aum_min` | float | Minimum AUM in USD |
| `has_nav` | bool | Only funds with NAV history |
| `domicile` | string | Domicile filter (comma-separated) |
| `manager` | string | Manager name text search |
| `sort` | string | `name_asc` (default), `name_desc`, `aum_desc`, `aum_asc` |
| `page` | int | Page number (1-based) |
| `page_size` | int | Items per page (1-200, default 50) |

Response: `UnifiedCatalogPage` (`items: UnifiedFundItem[]`, `total`, `page`, `page_size`, `has_next`).

Cache: 120s TTL, global key (no tenant scoping — global tables).

**`GET /api/v1/wealth/screener/catalog/facets`**

Same filter params as `/catalog` (without `sort`, `page`, `page_size`). Returns `CatalogFacets`:

```typescript
interface CatalogFacets {
  universes: CatalogFacetItem[];  // [{value: "registered_us", label: "US Registered", count: 52000}]
  regions: CatalogFacetItem[];
  fund_types: CatalogFacetItem[];
  domiciles: CatalogFacetItem[];
  total: number;
}
```

Cache: 300s TTL, global key.

---

## 3. Frontend Architecture

### 3.1 File Map

```
frontends/wealth/src/
├── routes/(app)/screener/
│   ├── +page.server.ts          # SSR: routes to catalog/managers/instrument endpoints
│   └── +page.svelte             # Unified 5-tab master-detail page
├── lib/types/
│   ├── catalog.ts               # UnifiedFundItem, DisclosureMatrix, CatalogFacets, etc.
│   ├── screening.ts             # InstrumentSearchItem, ScreenerFacets (tenant universe)
│   └── sec-analysis.ts          # SecManagerItem, SecHoldingsPage, SecStyleDrift, etc.
└── lib/components/screener/
    ├── index.ts                 # Barrel exports (28 components)
    │
    │  ── Catalog (new) ──
    ├── CatalogFilterSidebar.svelte   # eVestment-style facet tree sidebar
    ├── CatalogTable.svelte           # Server-side paginated table with disclosure dots
    ├── CatalogDetailPanel.svelte     # Disclosure-conditional detail (Overview/Holdings/Style/Quant)
    │
    │  ── SEC Analysis (moved from us-fund-analysis) ──
    ├── SecManagerTable.svelte        # SEC manager paginated table
    ├── SecHoldingsTable.svelte       # Quarter selector + holdings with CUSIP popover
    ├── SecStyleDriftChart.svelte     # Stacked bar chart + drift signals
    ├── SecReverseLookup.svelte       # CUSIP → holder lookup with history chart
    ├── SecPeerCompare.svelte         # Multi-manager comparison (sectors, overlaps, HHI)
    │
    │  ── Instrument Universe (existing) ──
    ├── ScreenerFilters.svelte        # Tab-specific filters (equity/bond/etf)
    ├── InstrumentTable.svelte        # Infinite scroll results table
    ├── InstrumentDetailPanel.svelte  # Detail panel for InstrumentSearchItem
    ├── InstrumentFilterSidebar.svelte
    │
    │  ── Manager Hierarchy (existing, different flow) ──
    ├── ManagerHierarchyTable.svelte
    ├── ManagerDetailPanel.svelte
    ├── ManagerFilterSidebar.svelte
    │
    │  ── Sub-tabs ──
    ├── HoldingsTab.svelte
    ├── DriftTab.svelte
    ├── DocsTab.svelte
    ├── FundDetailPanel.svelte
    └── PeerComparisonView.svelte
```

### 3.2 SSR Data Loading (`+page.server.ts`)

The `load()` function dispatches by `tab` URL param:

| `tab` | Fetches | Returns |
|-------|---------|---------|
| `catalog` (default) | `/screener/catalog` + `/screener/catalog/facets` | `catalog`, `catalogFacets` |
| `managers` | `/sec/managers/search` + `/sec/managers/sic-codes` | `managerResults`, `sicCodes` |
| `equity`/`bond`/`etf` | `/screener/search` + `/screener/facets` | `searchResults`, `facets` |

All fetches are `Promise.all` with `.catch(() => EMPTY_*)` fallbacks. Auth token comes from `await parent()`.

### 3.3 Layout

**Catalog tab** uses a master-detail split layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  PageHeader: "Screener"                           [Export]      │
├─────────────────────────────────────────────────────────────────┤
│  Fund Catalog │ Managers │ Equities │ Fixed Income │ ETF        │
├────────────┬────────────────────────────────────────────────────┤
│            │                                                    │
│  Sidebar   │  CatalogTable                                     │
│  Facets    │  ┌──────────────────────────────────────────────┐  │
│            │  │ Catalog  52,300 FUNDS        Page 1 of 1046 │  │
│  Universe  │  ├──────────────────────────────────────────────┤  │
│  ☑ US Reg  │  │ Universe │ Ticker │ Name │ Manager │ AUM... │  │
│  ☑ US Priv │  │ ● ● ● ● │ SPY    │ SPDR │ SSgA    │ $452B  │  │
│  ☐ EU      │  │ ● ● ○ ○ │ —      │ Fund │ KKR     │ $12B   │  │
│            │  └──────────────────────────────────────────────┘  │
│  Region    │                                                    │
│  Fund Type │  [Prev]  1 / 1046  [Next]                         │
│  Domicile  │                                                    │
│  AUM Min   │                                                    │
│            │                                                    │
│ [Clear All]│                                                    │
└────────────┴────────────────────────────────────────────────────┘
                          ↓ click row
              ┌───────────────────────────────────┐
              │  ContextPanel (50vw max 720px)     │
              │  ┌─────────────────────────────┐   │
              │  │ Overview│Holdings│Style│Quant│   │
              │  ├─────────────────────────────┤   │
              │  │ [US Registered] [PASS]      │   │
              │  │ Ticker: SPY                 │   │
              │  │ ISIN: US78462F1030          │   │
              │  │ Manager: State Street       │   │
              │  │ AUM: $452.3B               │   │
              │  │                             │   │
              │  │ Data Availability           │   │
              │  │ Holdings ● N-PORT           │   │
              │  │ NAV      ● YFinance         │   │
              │  │ Quant    ● Available         │   │
              │  │ Style    ● Available         │   │
              │  │ Private  ○ N/A              │   │
              │  │ 13F      ● Linked           │   │
              │  │                             │   │
              │  │ [Send to Review]            │   │
              │  └─────────────────────────────┘   │
              └───────────────────────────────────┘
```

**Managers tab** replicates the old `/us-fund-analysis` with 5 sub-tabs:

```
Overview → SecManagerTable (paginated, checkboxes for compare)
Holdings → SecHoldingsTable (quarter selector, CUSIP popover)
Style Drift → SecStyleDriftChart (stacked bar + signals)
Reverse Lookup → SecReverseLookup (CUSIP search → holders)
Peer Compare → SecPeerCompare (2-5 managers, sectors, overlap, HHI)
```

**Equity/Bond/ETF tabs** keep the existing `ScreenerFilters` + `InstrumentTable` (infinite scroll from tenant `instruments_universe`).

### 3.4 State Management

All filter state is URL-driven:

```
/screener?tab=catalog&universe=registered_us&universe=ucits_eu&fund_type=etf&aum_min=1000000000&page=2
```

- Sidebar checkbox toggles → rebuild URL params → `goto()` with `invalidateAll: true`
- `+page.server.ts` reads URL → calls backend → returns SSR data
- Table pagination uses URL `page` param (server-side, no infinite scroll for catalog)
- Text search is debounced (400ms) with instant apply on Enter

### 3.5 Disclosure-Conditional Rendering

`CatalogDetailPanel.svelte` builds tabs dynamically from the `DisclosureMatrix`:

```svelte
let availableTabs = $derived.by(() => {
  const tabs = [{ key: "overview", label: "Overview" }];
  if (fund.disclosure.has_holdings) tabs.push({ key: "holdings", label: "Holdings" });
  if (fund.disclosure.has_style_analysis) tabs.push({ key: "style", label: "Style Drift" });
  if (fund.disclosure.has_quant_metrics) tabs.push({ key: "quant", label: "Quant Metrics" });
  return tabs;
});
```

When a tab is shown but data is not available, it renders a styled N/A badge:

```svelte
<div class="cdp-na-section">
  <span class="cdp-na-badge">Holdings N/A</span>
  <p class="cdp-na-text">This fund's universe does not provide holdings disclosure.</p>
</div>
```

---

## 4. TypeScript Types

### 4.1 `catalog.ts` — Unified Catalog

| Type | Description |
|------|-------------|
| `DisclosureMatrix` | 10 fields: 7 booleans + 3 source literals. Drives conditional UI. |
| `FundUniverse` | `"registered_us" \| "private_us" \| "ucits_eu"` |
| `FundRegion` | `"US" \| "EU"` |
| `UnifiedFundItem` | 18 fields: identity, classification, manager, metrics, screening overlay, disclosure |
| `CatalogFacetItem` | `{ value, label, count }` |
| `CatalogFacets` | Facet arrays: `universes`, `regions`, `fund_types`, `domiciles` + `total` |
| `UnifiedCatalogPage` | `{ items, total, page, page_size, has_next, facets }` |

Constants: `EMPTY_CATALOG_PAGE`, `EMPTY_FACETS`, `UNIVERSE_LABELS`, `REGION_LABELS`.

### 4.2 `screening.ts` — Tenant Instruments

Used by Equities/Bond/ETF tabs. `InstrumentSearchItem`, `ScreenerFacets`, `ScreenerTab`.

### 4.3 `sec-analysis.ts` — SEC Manager Analysis

Used by Managers tab. `SecManagerItem`, `SecHoldingsPage`, `SecStyleDrift`, `SecReverseLookup`, `SecPeerCompare`.

---

## 5. Component Reference

### 5.1 Catalog Components

| Component | Props | Responsibility |
|-----------|-------|---------------|
| `CatalogFilterSidebar` | `facets`, `selectedUniverses` (bindable), `selectedRegions` (bindable), `selectedFundTypes` (bindable), `selectedDomiciles` (bindable), `searchQ` (bindable), `aumMin` (bindable), `onFilterChange` | Sticky sidebar with hierarchical checkbox facets. 260px wide, max-height `calc(100vh - 140px)`. |
| `CatalogTable` | `catalog: UnifiedCatalogPage`, `searchQ`, `onSelectFund`, `onPageChange` | Server-side paginated table. Columns: Universe badge, Ticker, Name+ISIN, Manager, Type, AUM, Region, Disclosure dots. |
| `CatalogDetailPanel` | `fund: UnifiedFundItem` | Disclosure-conditional tabs. Overview shows DisclosureMatrix as color-coded grid. Embeds `SecHoldingsTable` and `SecStyleDriftChart` when available. |

### 5.2 SEC Components (moved from `/us-fund-analysis`)

| Component | Props | Responsibility |
|-----------|-------|---------------|
| `SecManagerTable` | `data: SecManagerSearchPage`, `onSelect`, `onDetail`, `onPageChange`, `compareCiks`, `onToggleCompare` | Paginated manager table with compare checkboxes. |
| `SecHoldingsTable` | `api`, `cik`, `managerName` | Quarter selector + holdings table with CUSIP popover reverse lookup. |
| `SecStyleDriftChart` | `api`, `cik`, `managerName` | ECharts stacked bar (sector allocation history) + drift signal table. |
| `SecReverseLookup` | `api` | CUSIP input → holders table + holders/value history chart. |
| `SecPeerCompare` | `api`, `ciks: string[]` | Side-by-side comparison: cards, sector allocation, Jaccard overlap, HHI, fund structure donuts. |

---

## 6. Deleted Routes

| Route | Disposition |
|-------|------------|
| `/us-fund-analysis` | **Deleted.** All functionality absorbed into `/screener?tab=managers`. |
| `/us-fund-analysis/[crd]/[cik]` | **Deleted.** Legacy sub-routes. |
| `us-fund-analysis/components/*.svelte` | **Moved** to `lib/components/screener/Sec*.svelte`. |

The sidebar nav entry "US Fund Analysis" was removed from `+layout.svelte`.

---

## 7. Performance Considerations

- **Catalog query:** ~130k funds (50k registered + 50k private + 30k UCITS with ticker). UNION ALL with WHERE push-down and LIMIT/OFFSET. Cached 120s.
- **Facets query:** Same UNION ALL with GROUP BY. Cached 300s.
- **Server-side pagination:** 50 items/page, no infinite scroll, no client-side accumulation. Lightweight for the browser.
- **No deep reactivity:** Catalog items are plain objects from SSR, not wrapped in `$state` proxies. Table rows use `{#each items as item (key)}` keyed iteration.
- **Materialized view trigger:** If p95 latency exceeds 200ms, create `mv_unified_fund_catalog` with 6h refresh (data changes infrequently — SEC filings are quarterly, ESMA daily at most).

---

## 8. Future Work

| Item | Status | Notes |
|------|--------|-------|
| Materialized view | Deferred | Only if p95 > 200ms at scale |
| Trigram index on `name` | Deferred | Enables `ILIKE %q%` without seq scan |
| Sort by AUM, inception | Done | `sort` param: `name_asc`, `name_desc`, `aum_desc`, `aum_asc` |
| Import-to-universe from catalog | Done | "Send to Review" calls `import-esma/{isin}` or `import-sec/{ticker}` |
| Quant metrics inline | Partial | Shows placeholder; requires fund import to `instruments_universe` first |
| N-PORT holdings inline | Done | `SecHoldingsTable` embedded in detail panel for registered funds |
| Style drift inline | Done | `SecStyleDriftChart` embedded in detail panel for registered funds |
| `has_peer_analysis` flag | Stub | Currently always `false`; needs peer count query |
