---
date: 2026-03-24
task: screener-figma-redesign + sidebar update
priority: P0 — demo presentation today
---

# Screener Redesign — Figma Layout + Sidebar Update

## Context

The current Screener (`/screener`) uses a dual-mode layout (Instruments | Managers)
with a left sidebar for filters. The Figma design requires:

1. **Tabs by asset class** — Funds / Equities / Fixed Income / ETF (horizontal, inside card)
2. **Inline horizontal filters** — no sidebar, filters above the table
3. **Table with checkboxes** — multi-select for Export/Add to Portfolio
4. **Managers removed from Screener** — Managers is now only accessible via US Fund Analysis
5. **Sidebar updated** — add "US Fund Analysis" to Discovery & Screening section

## Files to read BEFORE writing any code

```
frontends/wealth/src/routes/(app)/screener/+page.svelte        (359 lines — current impl)
frontends/wealth/src/routes/(app)/screener/+page.server.ts     (read fully)
frontends/wealth/src/routes/(app)/+layout.svelte               (583 lines — sidebar)
frontends/wealth/src/lib/types/screening.ts                    (read fully)
frontends/wealth/src/lib/components/screener/InstrumentTable.svelte
frontends/wealth/src/lib/components/screener/InstrumentDetailPanel.svelte
frontends/wealth/src/lib/components/screener/FundDetailPanel.svelte
frontends/wealth/src/lib/components/screener/screener.css
```

Read ALL of these before writing a single line of code.

---

## Change 1 — Sidebar: add US Fund Analysis

In `frontends/wealth/src/routes/(app)/+layout.svelte`, find the `sections` array.
In the `discovery` section, add US Fund Analysis after Screener:

```typescript
{
  id: "discovery", label: "Discovery & Screening", defaultOpen: true,
  items: [
    { label: "Screener",          href: "/screener",          icon: Search },
    { label: "US Fund Analysis",  href: "/us-fund-analysis",  icon: Bot },
    { label: "DD Reports",        href: "/dd-reports",        icon: ClipboardList },
  ],
},
```

`Bot` is already imported in the layout. No other changes to the sidebar.

---

## Change 2 — Screener page: full rewrite

Replace the entire `+page.svelte` with the new layout. The `+page.server.ts`
stays UNCHANGED — it already loads `searchResults`, `facets`, `screener`, `results`.

### Tab definition

```typescript
type AssetTab = "funds" | "equities" | "fixed_income" | "etf";

const TABS: { id: AssetTab; label: string; instrument_type: string }[] = [
  { id: "funds",        label: "Funds",         instrument_type: "fund"          },
  { id: "equities",     label: "Equities",       instrument_type: "equity"        },
  { id: "fixed_income", label: "Fixed Income",   instrument_type: "bond"          },
  { id: "etf",          label: "ETF",            instrument_type: "etf"           },
];
```

### Filter state

```typescript
let activeTab   = $state<AssetTab>("funds");
let searchQ     = $state("");
let geography   = $state("");
let currency    = $state("");
let source      = $state<"" | "esma" | "sec" | "universe">("");
let aum_min     = $state("");
let selected    = $state<Set<string>>(new Set()); // instrument ISINs or IDs
```

### Derived filtered results

The `searchResults.items` from SSR contains all instruments. Filter client-side:

```typescript
let activeInstrumentType = $derived(
  TABS.find(t => t.id === activeTab)?.instrument_type ?? "fund"
);

let filteredItems = $derived.by(() => {
  let items = searchResults.items;
  items = items.filter(i => i.instrument_type === activeInstrumentType);
  if (searchQ) {
    const q = searchQ.toLowerCase();
    items = items.filter(i =>
      i.name?.toLowerCase().includes(q) ||
      i.isin?.toLowerCase().includes(q) ||
      i.ticker?.toLowerCase().includes(q) ||
      i.manager?.toLowerCase().includes(q)
    );
  }
  if (geography) items = items.filter(i => i.geography === geography);
  if (currency)  items = items.filter(i => i.currency === currency);
  if (source)    items = items.filter(i => i.source === source);
  if (aum_min)   items = items.filter(i => (i.aum_usd ?? 0) >= Number(aum_min));
  return items;
});

let tabCounts = $derived.by(() => {
  const counts: Record<AssetTab, number> = {
    funds: 0, equities: 0, fixed_income: 0, etf: 0,
  };
  for (const tab of TABS) {
    counts[tab.id] = searchResults.items.filter(
      i => i.instrument_type === tab.instrument_type
    ).length;
  }
  return counts;
});
```

### Selection helpers

```typescript
function toggleSelect(id: string) {
  const next = new Set(selected);
  next.has(id) ? next.delete(id) : next.add(id);
  selected = next;
}

function toggleAll() {
  if (selected.size === filteredItems.length) {
    selected = new Set();
  } else {
    selected = new Set(filteredItems.map(i => i.instrument_id));
  }
}

let allSelected = $derived(
  filteredItems.length > 0 && selected.size === filteredItems.length
);
```

### Export (client-side CSV)

```typescript
function exportCSV() {
  const rows = filteredItems.filter(i => selected.size === 0 || selected.has(i.instrument_id));
  const headers = ["Name", "ISIN", "Ticker", "Type", "Manager", "Geography", "Currency", "AUM", "Score", "Status"];
  const lines = [
    headers.join(","),
    ...rows.map(r => [
      `"${r.name ?? ""}"`,
      r.isin ?? "",
      r.ticker ?? "",
      r.instrument_type ?? "",
      `"${r.manager ?? ""}"`,
      r.geography ?? "",
      r.currency ?? "",
      r.aum_usd ?? "",
      r.composite_score ?? "",
      r.overall_status ?? "",
    ].join(","))
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `screener-${activeTab}-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
```

### Batch screening (keep existing pattern)

```typescript
let isRunning = $state(false);
async function executeBatch() {
  isRunning = true;
  try {
    const api = createClientApiClient(getToken);
    await api.post("/screener/run", {});
    await invalidateAll();
  } finally {
    isRunning = false;
  }
}
```

### Panel state (keep existing — ContextPanel for detail)

Keep `panelOpen`, `selectedInstrument`, `openInstrumentDetail`, `closePanel`.
Use `InstrumentDetailPanel` for click-through. `FundDetailPanel` for funds.
Remove all manager-related panel state — no more `panelMode === "manager"`.

---

## HTML structure

```svelte
<PageHeader title="Screener">
  {#snippet actions()}
    <div class="scr-actions">
      {#if selected.size > 0}
        <span class="scr-selected-count">{selected.size} selected</span>
        <Button size="sm" variant="outline" onclick={exportCSV}>Export</Button>
      {:else}
        <Button size="sm" variant="outline" onclick={exportCSV}>Export</Button>
      {/if}
      <Button size="sm" onclick={executeBatch} disabled={isRunning}>
        {isRunning ? "Running…" : "Run Screening"}
      </Button>
    </div>
  {/snippet}
</PageHeader>

<div class="scr-page">
  <div class="scr-card">

    <!-- TABS -->
    <div class="scr-tabs">
      {#each TABS as tab (tab.id)}
        <button
          class="scr-tab"
          class:scr-tab--active={activeTab === tab.id}
          onclick={() => { activeTab = tab.id; selected = new Set(); }}
        >
          {tab.label}
          <span class="scr-tab-count">{tabCounts[tab.id]}</span>
        </button>
      {/each}
    </div>

    <!-- FILTERS -->
    <div class="scr-filters-row">
      <div class="scr-filter-field scr-filter-field--search">
        <label class="scr-filter-label" for="scr-search">Search</label>
        <input
          id="scr-search"
          class="scr-input scr-input--search"
          type="text"
          placeholder="Name, ISIN, ticker, manager..."
          bind:value={searchQ}
        />
      </div>
      <div class="scr-filter-field">
        <label class="scr-filter-label" for="scr-geo">Geography</label>
        <select id="scr-geo" class="scr-select" bind:value={geography}>
          <option value="">All</option>
          {#each (facets.geographies ?? []) as g (g.value)}
            <option value={g.value}>{g.label} ({g.count})</option>
          {/each}
        </select>
      </div>
      <div class="scr-filter-field">
        <label class="scr-filter-label" for="scr-currency">Currency</label>
        <select id="scr-currency" class="scr-select" bind:value={currency}>
          <option value="">All</option>
          {#each (facets.currencies ?? []) as c (c.value)}
            <option value={c.value}>{c.label} ({c.count})</option>
          {/each}
        </select>
      </div>
      <div class="scr-filter-field">
        <label class="scr-filter-label" for="scr-source">Source</label>
        <select id="scr-source" class="scr-select" bind:value={source}>
          <option value="">All</option>
          <option value="esma">ESMA</option>
          <option value="sec">SEC</option>
          <option value="universe">Universe</option>
        </select>
      </div>
      <div class="scr-filter-field">
        <label class="scr-filter-label" for="scr-aum">Min AUM (USD)</label>
        <input
          id="scr-aum"
          class="scr-input"
          type="number"
          placeholder="e.g. 1000000"
          bind:value={aum_min}
        />
      </div>
      <div class="scr-filter-actions">
        <button class="scr-btn-clear" onclick={() => {
          searchQ = ""; geography = ""; currency = ""; source = ""; aum_min = "";
        }}>Clear</button>
      </div>
    </div>

    <!-- TABLE SUMMARY -->
    <div class="scr-table-summary">
      <span class="scr-table-count">
        {filteredItems.length} instruments
        {#if selected.size > 0}· {selected.size} selected{/if}
      </span>
    </div>

    <!-- TABLE -->
    <div class="scr-table-wrap">
      <table class="scr-table">
        <thead>
          <tr>
            <th class="scr-th scr-th--check">
              <input
                type="checkbox"
                class="scr-checkbox"
                checked={allSelected}
                onchange={toggleAll}
              />
            </th>
            <th class="scr-th">Name</th>
            <th class="scr-th">Source</th>
            <th class="scr-th">Manager</th>
            <th class="scr-th scr-th--right">
              {activeTab === "fixed_income" ? "Maturity" : activeTab === "equities" ? "Mkt Cap" : "AUM"}
            </th>
            <th class="scr-th">Geography</th>
            <th class="scr-th">Currency</th>
            <th class="scr-th scr-th--right">Score</th>
            <th class="scr-th">Status</th>
          </tr>
        </thead>
        <tbody>
          {#if filteredItems.length === 0}
            <tr>
              <td colspan="9" class="scr-empty">No instruments found for this filter.</td>
            </tr>
          {/if}
          {#each filteredItems as item (item.instrument_id)}
            <tr
              class="scr-row"
              class:scr-row--selected={selected.has(item.instrument_id)}
              onclick={() => openDetail(item)}
            >
              <td class="scr-td scr-td--check" onclick|stopPropagation={() => toggleSelect(item.instrument_id)}>
                <input
                  type="checkbox"
                  class="scr-checkbox"
                  checked={selected.has(item.instrument_id)}
                  onchange={() => toggleSelect(item.instrument_id)}
                />
              </td>
              <td class="scr-td scr-td--name">
                <div class="scr-name-cell">
                  <span class="scr-name">{item.name ?? "—"}</span>
                  {#if item.isin}
                    <span class="scr-isin">{item.isin}</span>
                  {/if}
                </div>
              </td>
              <td class="scr-td">
                {#if item.source}
                  <span class="scr-source-badge scr-source-badge--{item.source.toLowerCase()}">
                    {item.source.toUpperCase()}
                  </span>
                {:else}—{/if}
              </td>
              <td class="scr-td scr-td--manager">{item.manager ?? "—"}</td>
              <td class="scr-td scr-td--right scr-td--num">
                {item.aum_usd != null ? formatAUM(item.aum_usd) : "—"}
              </td>
              <td class="scr-td">{item.geography ?? "—"}</td>
              <td class="scr-td">{item.currency ?? "—"}</td>
              <td class="scr-td scr-td--right scr-td--num">
                {item.composite_score != null ? item.composite_score.toFixed(1) : "—"}
              </td>
              <td class="scr-td">
                {#if item.overall_status}
                  <StatusBadge status={item.overall_status} />
                {:else}—{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

  </div>
</div>

<!-- CONTEXT PANEL -->
<ContextPanel open={panelOpen} onClose={closePanel} title={panelTitle} width="min(45vw, 680px)">
  {#if selectedItem}
    {#if selectedItem.instrument_type === "fund" || selectedItem.instrument_type === "etf"}
      <FundDetailPanel fund={selectedItem} />
    {:else}
      <InstrumentDetailPanel instrument={selectedItem} />
    {/if}
  {/if}
</ContextPanel>
```

### openDetail function

```typescript
let panelOpen = $state(false);
let selectedItem = $state<InstrumentSearchItem | null>(null);
let panelTitle = $derived(selectedItem?.name ?? "");

function openDetail(item: InstrumentSearchItem) {
  selectedItem = item;
  panelOpen = true;
}

function closePanel() {
  panelOpen = false;
  selectedItem = null;
}
```

---

## CSS

Replace the entire `<style>` block:

```css
.scr-page {
  padding: 0 0 48px;
}

.scr-card {
  background: var(--netz-surface-elevated);
  border: 1px solid var(--netz-border-subtle);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}

/* TABS */
.scr-tabs {
  display: flex;
  border-bottom: 1px solid var(--netz-border-subtle);
  padding: 0 24px;
  background: var(--netz-surface-elevated);
}

.scr-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 12px;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--netz-text-muted);
  font-size: 14px;
  font-weight: 500;
  font-family: var(--netz-font-sans);
  cursor: pointer;
  transition: color 120ms ease, border-color 120ms ease;
  margin-bottom: -1px;
}

.scr-tab:hover { color: var(--netz-text-primary); }

.scr-tab--active {
  color: var(--netz-brand-primary);
  border-bottom-color: var(--netz-brand-primary);
  font-weight: 600;
}

.scr-tab-count {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--netz-surface-alt) 80%, transparent);
  color: var(--netz-text-muted);
}

.scr-tab--active .scr-tab-count {
  background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
  color: var(--netz-brand-primary);
}

/* FILTERS */
.scr-filters-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr 1fr auto;
  gap: 16px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--netz-border-subtle);
  background: var(--netz-surface-elevated);
  align-items: end;
}

.scr-filter-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.scr-filter-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--netz-text-muted);
}

.scr-input,
.scr-select {
  padding: 8px 12px;
  font-size: 13px;
  border: 1px solid var(--netz-border-subtle);
  border-radius: 10px;
  background: var(--netz-surface-alt);
  color: var(--netz-text-primary);
  font-family: var(--netz-font-sans);
  height: 36px;
}

.scr-input:focus,
.scr-select:focus {
  outline: none;
  border-color: var(--netz-brand-primary);
}

.scr-input::placeholder { color: var(--netz-text-muted); }

.scr-filter-actions {
  display: flex;
  align-items: flex-end;
  padding-bottom: 2px;
}

.scr-btn-clear {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--netz-text-secondary);
  background: none;
  border: 1px solid var(--netz-border-subtle);
  border-radius: 10px;
  cursor: pointer;
  height: 36px;
}

.scr-btn-clear:hover { color: var(--netz-text-primary); background: var(--netz-surface-alt); }

/* TABLE SUMMARY */
.scr-table-summary {
  padding: 10px 24px;
  border-bottom: 1px solid var(--netz-border-subtle);
}

.scr-table-count {
  font-size: 12px;
  color: var(--netz-text-muted);
  font-weight: 500;
}

/* TABLE */
.scr-table-wrap {
  overflow-x: auto;
  overflow-y: auto;
  max-height: calc(100vh - 280px);
}

.scr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.scr-th {
  padding: 10px 16px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--netz-text-muted);
  text-align: left;
  background: color-mix(in srgb, var(--netz-surface-alt) 60%, transparent);
  border-bottom: 1px solid var(--netz-border-subtle);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}

.scr-th--check { width: 40px; padding: 10px 16px 10px 24px; }
.scr-th--right { text-align: right; }

.scr-row {
  cursor: pointer;
  border-bottom: 1px solid var(--netz-border-subtle);
  transition: background 80ms ease;
}

.scr-row:hover { background: color-mix(in srgb, var(--netz-surface-alt) 40%, transparent); }
.scr-row--selected { background: color-mix(in srgb, var(--netz-brand-primary) 5%, transparent); }
.scr-row:last-child { border-bottom: none; }

.scr-td {
  padding: 12px 16px;
  vertical-align: middle;
  color: var(--netz-text-secondary);
}

.scr-td--check { padding: 12px 16px 12px 24px; width: 40px; }
.scr-td--right { text-align: right; }
.scr-td--num { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--netz-text-primary); }

.scr-name-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 200px;
  max-width: 320px;
}

.scr-name {
  font-weight: 600;
  color: var(--netz-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scr-isin {
  font-size: 11px;
  color: var(--netz-text-muted);
  font-family: var(--netz-font-mono);
}

.scr-td--manager {
  max-width: 180px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scr-source-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 700;
  border-radius: 6px;
}

.scr-source-badge--esma {
  background: color-mix(in srgb, #6366f1 10%, transparent);
  color: #6366f1;
}

.scr-source-badge--sec {
  background: color-mix(in srgb, #0ea5e9 10%, transparent);
  color: #0ea5e9;
}

.scr-source-badge--universe {
  background: color-mix(in srgb, #10b981 10%, transparent);
  color: #10b981;
}

.scr-checkbox {
  width: 15px;
  height: 15px;
  cursor: pointer;
  accent-color: var(--netz-brand-primary);
}

.scr-empty {
  text-align: center;
  padding: 48px 24px;
  color: var(--netz-text-muted);
  font-size: 14px;
}

.scr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scr-selected-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--netz-brand-primary);
}

@media (max-width: 1024px) {
  .scr-filters-row {
    grid-template-columns: 1fr 1fr 1fr;
  }
}
```

---

## Imports for the new page

```typescript
import { getContext, untrack } from "svelte";
import { invalidateAll } from "$app/navigation";
import { PageHeader, Button, ContextPanel, StatusBadge, formatAUM } from "@netz/ui";
import { createClientApiClient } from "$lib/api/client";
import type { PageData } from "./$types";
import type { InstrumentSearchPage, ScreenerFacets, InstrumentSearchItem } from "$lib/types/screening";
import { EMPTY_SEARCH_PAGE, EMPTY_FACETS } from "$lib/types/screening";
import { InstrumentDetailPanel, FundDetailPanel } from "$lib/components/screener";
```

---

## What to remove (no longer needed)

- All `ScreenerMode` / `switchMode` / `activeMode` logic
- All manager-related state: `expandedManagers`, `selectedManagers`, `compareResult`,
  `panelMode === "manager"`, `panelCrd`, `panelFirm`
- All imports of: `ManagerFilterSidebar`, `ManagerHierarchyTable`, `ManagerDetailPanel`,
  `PeerComparisonView`, `InstrumentFilterSidebar`
- The `.mode-toggle`, `.mode-btn` CSS
- The `scr-grid` grid layout (replace with `.scr-page`)
- The `runDetailData`, `runDetailOpen`, `toggleRunDetail` logic

---

## What to preserve

- `executeBatch()` — POST /screener/run (keep exactly as-is)
- `ContextPanel` with `FundDetailPanel` and `InstrumentDetailPanel`
- `invalidateAll` after batch run
- `formatAUM` from `@netz/ui`
- SSR data binding: `searchResults`, `facets` from `data`

---

## Verification

```powershell
# After edits, run svelte-check
cd C:\Users\andre\projetos\netz-analysis-engine
pnpm --filter netz-wealth-os exec svelte-check --threshold error 2>&1 | Select-String "Error|found"
```

Expected: 0 errors.

Then confirm in browser:
- Screener shows 4 tabs (Funds / Equities / Fixed Income / ETF) with counts
- Sidebar shows "US Fund Analysis" under Discovery & Screening
- Filters are horizontal inline (no sidebar)
- Table has checkboxes + Export button works
- Clicking a row opens ContextPanel with instrument detail
- Run Screening button still works

---

## Rules

- Svelte 5 runes only: `$state`, `$derived`, `$derived.by`, `$effect`
- `@netz/ui` formatters — never `.toLocaleString()`, never `.toFixed()` for AUM
- Do NOT change `+page.server.ts` — only `+page.svelte` and `+layout.svelte`
- Do NOT remove `FundDetailPanel` or `InstrumentDetailPanel` components
- Do NOT change any other route pages
- `make check` must pass after changes (lint + typecheck)

## Success Criteria

- [ ] Sidebar has "US Fund Analysis" between Screener and DD Reports
- [ ] Screener has 4 horizontal tabs with instrument counts
- [ ] Filters are inline horizontal row (no sidebar)
- [ ] Table has checkboxes, Name+ISIN, Source badge, Manager, AUM, Geography, Currency, Score, Status
- [ ] Export button generates CSV of selected (or all) instruments
- [ ] Clicking row opens ContextPanel
- [ ] Run Screening button still works
- [ ] 0 TypeScript errors (`svelte-check --threshold error`)
