---
date: 2026-03-24
task: screener-page-wiring
priority: P0 — demo presentation today
---

# Screener Page — Wire ScreenerFilters into +page.svelte

## Context

`ScreenerFilters.svelte` (372 lines) already exists and is complete:
- 4 tabs: Funds / Equities / Fixed Income / ETF
- Inline filters per tab (no sidebar)
- `goto()` navigation with URL params
- Props: `activeTab: ScreenerTab`, `facets: ScreenerFacets`, `initParams`

The `+page.svelte` was never updated to use it — still uses the old
dual-mode sidebar layout. This prompt wires the existing component in.

## Files to read BEFORE writing anything

```
frontends/wealth/src/routes/(app)/screener/+page.svelte          (359 lines)
frontends/wealth/src/routes/(app)/screener/+page.server.ts       (read fully)
frontends/wealth/src/lib/components/screener/ScreenerFilters.svelte (372 lines)
frontends/wealth/src/lib/components/screener/InstrumentTable.svelte
frontends/wealth/src/lib/components/screener/FundDetailPanel.svelte
frontends/wealth/src/lib/components/screener/InstrumentDetailPanel.svelte
frontends/wealth/src/lib/types/screening.ts
```

---

## What to change in +page.svelte

### 1. Remove sidebar layout and manager mode

Remove entirely:
- `type ScreenerMode = "instruments" | "managers"` and `activeMode` state
- `switchMode()` function
- All manager-related state: `expandedManagers`, `selectedManagers`,
  `compareResult`, `comparing`, `compareError`, `runCompare()`, `clearCompare()`
- All panel state for managers: `panelMode`, `panelCrd`, `panelFirm`
- `openManagerDetail()`, `openFundDetail()` (replace with single `openDetail()`)
- `runDetailData`, `runDetailOpen`, `runDetailLoading`, `toggleRunDetail()`
- `.scr-grid` CSS grid (the `260px 1fr` sidebar layout)
- `.mode-toggle`, `.mode-btn` CSS

Remove these imports:
- `ManagerFilterSidebar`, `ManagerHierarchyTable`, `ManagerDetailPanel`,
  `PeerComparisonView`, `InstrumentFilterSidebar`

### 2. Add activeTab state from URL params

```typescript
import type { ScreenerTab } from "$lib/types/screening";

const initParams = (untrack(() => data.currentParams) as Record<string, string>) ?? {};
let activeTab = $state<ScreenerTab>((initParams.tab as ScreenerTab) ?? "fund");
```

### 3. Add ScreenerFilters import

```typescript
import { ScreenerFilters } from "$lib/components/screener";
```

Check `$lib/components/screener/index.ts` to confirm ScreenerFilters is exported.
If not, add: `export { default as ScreenerFilters } from "./ScreenerFilters.svelte";`

### 4. Simplify panel state

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

### 5. Keep batch screening

```typescript
let isRunning = $state(false);
let runError = $state<string | null>(null);

async function executeBatch() {
  isRunning = true;
  runError = null;
  try {
    const api = createClientApiClient(getToken);
    await api.post("/screener/run", {});
    await invalidateAll();
  } catch (e) {
    runError = e instanceof Error ? e.message : "Failed";
  } finally {
    isRunning = false;
  }
}
```

### 6. New HTML structure

```svelte
<PageHeader title="Screener">
  {#snippet actions()}
    <div class="scr-actions">
      <Button size="sm" onclick={executeBatch} disabled={isRunning}>
        {isRunning ? "Running…" : "Run Screening"}
      </Button>
    </div>
  {/snippet}
</PageHeader>

<div class="scr-page">
  <!-- Filter card with 4 tabs -->
  <ScreenerFilters
    {activeTab}
    {facets}
    {initParams}
  />

  <!-- Results table -->
  <div class="scr-results">
    <InstrumentTable
      {searchResults}
      searchQ={initParams.q ?? ""}
      onOpenInstrumentDetail={openDetail}
    />
  </div>

  {#if runError}
    <div class="scr-error">{runError}</div>
  {/if}
</div>

<!-- Context Panel -->
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

### 7. New CSS (replace entire style block)

```css
.scr-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 48px;
}

.scr-results {
  background: var(--netz-surface-elevated);
  border: 1px solid var(--netz-border-subtle);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}

.scr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scr-error {
  padding: 10px 16px;
  background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
  color: var(--netz-danger);
  font-size: 13px;
  border-radius: 8px;
}
```

### 8. Check +page.server.ts

The server load must pass `tab` param to backend. Verify it reads `url.searchParams.get("tab")`
and passes it to the `/screener/search` endpoint as `instrument_type` filter.

If not already doing this, add:
```typescript
const tab = url.searchParams.get("tab") ?? "fund";
const tabToInstrumentType: Record<string, string> = {
  fund: "fund",
  equity: "equity",
  bond: "bond",
  etf: "etf",
};
// Pass to search params: instrument_type: tabToInstrumentType[tab]
```

---

## Also update sidebar (+layout.svelte)

In `frontends/wealth/src/routes/(app)/+layout.svelte`, find the `discovery` section
and add "US Fund Analysis":

```typescript
{
  id: "discovery", label: "Discovery & Screening", defaultOpen: true,
  items: [
    { label: "Screener",         href: "/screener",         icon: Search },
    { label: "US Fund Analysis", href: "/us-fund-analysis", icon: Bot },
    { label: "DD Reports",       href: "/dd-reports",       icon: ClipboardList },
  ],
},
```

`Bot` is already imported in the layout file.

---

## Verification

```powershell
cd C:\Users\andre\projetos\netz-analysis-engine
pnpm --filter netz-wealth-os exec svelte-check --threshold error 2>&1 | Select-String "Error|found"
```

Expected: 0 errors.

Browser check:
- Screener shows ScreenerFilters card with 4 tabs at top
- No sidebar
- InstrumentTable below the filter card
- Sidebar has "US Fund Analysis" between Screener and DD Reports
- Run Screening button works
- Clicking a row opens ContextPanel

---

## Rules

- Svelte 5 runes only
- Do NOT modify ScreenerFilters.svelte — it is complete, wire only
- Do NOT modify InstrumentTable.svelte
- Do NOT modify +page.server.ts unless tab param is not being passed
- `make check` must pass
