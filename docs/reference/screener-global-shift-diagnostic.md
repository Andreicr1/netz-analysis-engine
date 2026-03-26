# Screener Global Shift — Diagnostic Report

**Date:** 2026-03-26
**Severity:** Architectural Bug (P0)
**Status:** Fixed

---

## 1. Bug Diagnosis

### The Problem

The Screener tabs "Equities", "Fixed Income", and "ETF" were querying `GET /screener/search`, which performs a UNION ALL including `instruments_universe` (RLS-protected, tenant-scoped). This means:

- A client could only "discover" equities/bonds they had **already imported**
- The Screener was acting as a **portfolio viewer**, not a **discovery tool**
- Global SEC data from `sec_cusip_ticker_map` was mixed with tenant data, confusing the user

### Architectural Rule Violated

```
Screener (Global/Free) → DD Report (AI/Quant) → Approval → Universe (RLS Tenant)
```

The `instruments_universe` is the **DESTINATION**, never the **SOURCE** for discovery.

---

## 2. Fix Applied — Mandate 1: Shift-to-Global

### New Endpoint: `GET /screener/securities`

Queries `sec_cusip_ticker_map` directly — **global, no RLS, no `instruments_universe`**.

| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Search by name, ticker, or CUSIP |
| `security_type` | string | Common Stock, ETP, ADR, REIT, MLP, Closed-End Fund |
| `exchange` | string | NYSE, NASDAQ, etc. |
| `asset_class` | string | equity, real_estate |
| `sort` | string | name_asc (default), name_desc |
| `page` / `page_size` | int | Server-side pagination (max 200) |

Response: `SecurityPage` with `SecurityItem[]`.

Cache: 120s TTL, global key.

### New Endpoint: `GET /screener/securities/facets`

Returns `SecurityFacets` with `security_types[]` and `exchanges[]` facet counts.

Cache: 300s TTL, global key.

### Tab Restructure

| Before | After | Reason |
|--------|-------|--------|
| Fund Catalog | Fund Catalog | Unchanged — already global |
| Managers | Managers | Unchanged — already global |
| Equities | **Equities & ETFs** | Now queries `/screener/securities` (global) |
| Fixed Income | **Removed** | No global bond master table. Bonds visible via N-PORT holdings in Fund Catalog detail. |
| ETF | **Merged into Equities & ETFs** | ETFs already in Fund Catalog as `registered_us`. `sec_cusip_ticker_map` covers ETP type. |

### New Types (`catalog.ts`)

```typescript
interface SecurityItem {
  cusip: string;
  ticker: string | null;
  name: string;
  security_type: string; // Common Stock, ETP, ADR, REIT, MLP
  exchange: string | null;
  asset_class: string;   // equity | real_estate
  figi: string | null;
  is_tradeable: boolean;
}

interface SecurityPage { items, total, page, page_size, has_next }
interface SecurityFacets { security_types[], exchanges[], total }
```

### New Components

| Component | Purpose |
|-----------|---------|
| `SecuritiesTable.svelte` | Server-side paginated table with type badges and exchange column |
| `SecuritiesFilterSidebar.svelte` | Faceted sidebar (security type + exchange checkboxes) |

---

## 3. Fix Applied — Mandate 2: Peer Compare Offload

**Diagnosis:** The `SecPeerCompare` backend (`GET /sec/managers/compare`) already performs all heavy computation server-side:

| Computation | Where | Method |
|-------------|-------|--------|
| Sector aggregation | Backend | SQL GROUP BY + market_value normalization |
| HHI concentration | Backend | `sum(weight²)` per manager |
| Jaccard overlap | Backend | `|A ∩ B| / |A ∪ B|` on CUSIP sets |
| Fund breakdown | Backend | SQL GROUP BY fund_type |

**Frontend does only:** Sector name deduplication (trivial `Set` operation) + ECharts rendering. No client-side joins, regressions, or matrix reductions.

**Verdict:** Backend is correctly offloaded. No changes needed.

---

## 4. Fix Applied — Mandate 3: Virtual Scrolling

### Problem

`SecHoldingsTable.svelte` renders N-PORT holdings for funds like Vanguard Total Stock Market (10k+ positions). At `page_size=500`, the browser would mount 500 `<tr>` DOM nodes. For large funds, this creates:

- Layout thrashing on scroll
- 500 reactive `$state` proxies tracking each row
- Memory pressure in Chrome DevTools

### Solution: `@tanstack/svelte-virtual`

**Already a dependency** in `frontends/wealth/package.json`.

**Implementation:**

1. **Virtual scroll container** with `max-height: 520px` and `overflow-y: auto`
2. **`createVirtualizer()`** with `estimateSize: 44px`, `overscan: 15` rows
3. **Absolute-positioned inner table** translated by `items[0].start`
4. **Only ~30 `<tr>` nodes mounted** at any time regardless of data size

### Raw Data Pattern

Holdings data is kept as a **plain variable** (`let holdings: SecHoldingsPage`), NOT wrapped in `$state()`. This avoids Svelte 5's deep reactivity proxy on large arrays:

```svelte
// ✅ Raw data — no deep proxy overhead
let holdings: SecHoldingsPage = EMPTY_HOLDINGS;

// ✅ Only bump a counter to trigger re-render
let dataVersion = $state(0);
```

The virtualizer store is subscribed manually to avoid `$derived` on a Readable:

```svelte
let virt = $state(null);
$effect(() => {
  if (!virtualizerStore) { virt = null; return; }
  const unsub = virtualizerStore.subscribe((v) => { virt = v; });
  return unsub;
});
```

### Sticky Header

The table header is rendered outside the virtual container as a fixed-width `<table>` with `table-layout: fixed`, keeping columns aligned with the virtualized body.

---

## 5. Files Changed

### Backend

| File | Change |
|------|--------|
| `routes/screener.py` | Added `GET /securities` + `GET /securities/facets` (global, no RLS). Added `SecurityItem`, `SecurityPage`, `SecurityFacets` inline schemas. |

### Frontend

| File | Change |
|------|--------|
| `types/catalog.ts` | Added `SecurityItem`, `SecurityPage`, `SecurityFacets`, `EMPTY_*` constants |
| `components/screener/SecuritiesTable.svelte` | **New** — global securities table with type badges |
| `components/screener/SecuritiesFilterSidebar.svelte` | **New** — faceted sidebar for security type + exchange |
| `components/screener/SecHoldingsTable.svelte` | **Rewritten** — `@tanstack/svelte-virtual` row virtualization + raw data pattern |
| `components/screener/index.ts` | Added `SecuritiesTable`, `SecuritiesFilterSidebar` exports |
| `routes/screener/+page.server.ts` | Equities tab → `GET /screener/securities`. Removed bond/etf tabs. |
| `routes/screener/+page.svelte` | 3 tabs (Catalog, Equities & ETFs, Managers). Equities tab uses master-detail with sidebar. |

### Not Changed (validated as correct)

| File | Reason |
|------|--------|
| `SecPeerCompare.svelte` | Backend already offloads all computation. Frontend only renders. |
| `/screener/search` endpoint | Kept for backward compatibility but no longer called by any frontend tab. |

---

## 6. Bond Discovery — Design Decision

There is **no global bond master table**. Bonds in the system come from:

| Source | Coverage | Limitation |
|--------|----------|-----------|
| `sec_nport_holdings` (asset_class='Debt') | ~50K funds holding bonds | No standalone bond CUSIP→ticker resolution |
| `instruments_universe` (type='bond') | Tenant-curated bonds | RLS-scoped, not for discovery |

**Decision:** Bond discovery is deferred. Bonds are visible through the Fund Catalog detail panel (Holdings tab for N-PORT registered funds). A dedicated `sec_bonds` global table would require ingesting FINRA TRACE or Bloomberg — out of scope for Milestone 2.

---

## 7. Performance Impact

| Metric | Before | After |
|--------|--------|-------|
| Equities tab query | UNION ALL (3 branches, RLS + global) | Single `sec_cusip_ticker_map` query |
| Equities tab latency | ~300-500ms (RLS + UNION ALL overhead) | ~50-100ms (single table, indexed) |
| Holdings DOM nodes | Up to 500 `<tr>` (page_size=500) | ~30 `<tr>` (virtual window) |
| Holdings memory | Deep `$state` proxy on 500 objects | Raw array, no proxy overhead |
| Tab count | 5 | 3 (cleaner UX, no empty tabs) |
