# Phase 2B — ESMA European Fund Universe Frontend

**Status:** Ready
**Estimated scope:** ~400 lines new code
**Risk:** Low (follows Manager Screener pattern exactly)
**Prerequisite:** Phase 2A (ESMA backend endpoints must exist)

---

## Context

Phase 2A created 5 ESMA REST endpoints. This session builds the frontend page in the wealth app. **Copy the Manager Screener pattern exactly** — same structure: paginated table + filter sidebar + detail drawer with tabs.

**Template:** `frontends/wealth/src/routes/(team)/manager-screener/+page.svelte`
**Design system:** `@netz/ui` components (PageHeader, PageTabs, EmptyState, StatusBadge, etc.)

---

## Task 1: ESMA Page + Server Load

### Step 1.1 — Server load

Create `frontends/wealth/src/routes/(team)/esma/+page.server.ts`:

```typescript
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ locals, url }) => {
  const api = locals.api;
  const activeTab = url.searchParams.get('tab') || 'managers';
  const page = parseInt(url.searchParams.get('page') || '1');
  const search = url.searchParams.get('search') || '';
  const country = url.searchParams.get('country') || '';

  // Use Promise.allSettled (NEVER Promise.all)
  const [managersResult, fundsResult] = await Promise.allSettled([
    activeTab === 'managers'
      ? api.get(`/esma/managers?page=${page}&search=${encodeURIComponent(search)}&country=${encodeURIComponent(country)}`)
      : Promise.resolve(null),
    activeTab === 'funds'
      ? api.get(`/esma/funds?page=${page}&search=${encodeURIComponent(search)}`)
      : Promise.resolve(null),
  ]);

  return {
    managers: managersResult.status === 'fulfilled' ? managersResult.value : null,
    funds: fundsResult.status === 'fulfilled' ? fundsResult.value : null,
    activeTab,
    page,
    search,
    country,
  };
};
```

### Step 1.2 — Main page

Create `frontends/wealth/src/routes/(team)/esma/+page.svelte`:

**Layout (UX Doctrine §21 — Workbench page):**
- `PageHeader title="ESMA Universe"`
- `PageTabs` with 2 tabs: "Managers" and "Funds"
- Filter bar: search input + country select (managers) or domicile/type (funds)
- Paginated table
- Detail drawer on row click

**Surface hierarchy (UX Doctrine §10):**
- Manager/fund tables on `surface-1`
- Detail drawer on `surface-3`

**Table columns — Managers tab:**
| Column | Key | Sortable |
|--------|-----|----------|
| Company Name | `company_name` | Yes |
| Country | `country` | Yes |
| Funds | `fund_count` | Yes |
| SEC Cross-Ref | `sec_crd_number` | No |

**Table columns — Funds tab:**
| Column | Key | Sortable |
|--------|-----|----------|
| Fund Name | `fund_name` | Yes |
| ISIN | `isin` | No |
| Domicile | `domicile` | Yes |
| Type | `fund_type` | Yes |
| Ticker | `ticker` | No |

### Step 1.3 — Pagination

URL-driven pagination with `goto()`:

```typescript
function goToPage(newPage: number) {
  const url = new URL(window.location.href);
  url.searchParams.set('page', String(newPage));
  goto(url.toString(), { replaceState: true });
}
```

### Step 1.4 — Search with sequence counter

```typescript
let searchSeq = $state(0);
let searchValue = $state(data.search);

function onSearch() {
  const seq = ++searchSeq;
  // Debounce 300ms
  setTimeout(() => {
    if (seq !== searchSeq) return;
    const url = new URL(window.location.href);
    url.searchParams.set('search', searchValue);
    url.searchParams.set('page', '1');
    goto(url.toString(), { replaceState: true });
  }, 300);
}
```

---

## Task 2: Manager Detail Drawer

### Step 2.1 — Create drawer component

Create `frontends/wealth/src/routes/(team)/esma/EsmaManagerDrawer.svelte`:

**Content:**
- Manager name, country, ESMA ID
- SEC Cross-Reference badge: `StatusBadge` with "Matched" (green) or "Unmatched" (neutral)
- Fund list table (loaded on drawer open via `api.get(`/esma/managers/${esmaId}`)`)
- "Add to Universe" button per fund (reuses existing `instruments_universe` flow)

**Load on demand:**
```svelte
<script>
  let { esmaId, onClose } = $props();
  let manager = $state(null);
  let loading = $state(true);

  $effect(() => {
    if (esmaId) {
      loading = true;
      api.get(`/esma/managers/${esmaId}`).then(m => {
        manager = m;
        loading = false;
      });
    }
  });
</script>
```

### Step 2.2 — SEC Cross-Reference badge

If `sec_crd_number` is set, show:
```svelte
<StatusBadge status="ok" label="SEC Matched (CRD {manager.sec_crd_number})" />
```
Otherwise:
```svelte
<StatusBadge status="neutral" label="No SEC Match" />
```

### Step 2.3 — "Add to Universe" action

Reuse existing universe workflow. Find how Manager Screener's "Add to Universe" works (POST `/manager-screener/managers/{crd}/add-to-universe`) and adapt for ESMA funds by ISIN.

---

## Task 3: Navigation

### Step 3.1 — Add to TopNav

Per wealth frontend review learning: use **TopNav** item (not sidebar). Find the navigation config and add "ESMA Universe" under the Data section.

Look for navigation definition in:
- `frontends/wealth/src/lib/components/TopNav.svelte`
- `frontends/wealth/src/routes/(team)/+layout.svelte`

Add entry matching existing pattern.

---

## Files Created

| File | Purpose |
|------|---------|
| `frontends/wealth/src/routes/(team)/esma/+page.server.ts` | Server load |
| `frontends/wealth/src/routes/(team)/esma/+page.svelte` | Main page |
| `frontends/wealth/src/routes/(team)/esma/EsmaManagerDrawer.svelte` | Detail drawer |

## Files Modified

| File | Change |
|------|--------|
| TopNav or layout component | Add "ESMA Universe" navigation entry |

## Acceptance Criteria

- [ ] Paginated manager + fund tables with filters
- [ ] Manager drawer shows funds + SEC cross-ref badge
- [ ] "Add to Universe" button integrates with existing universe workflow
- [ ] Empty state for unresolved tickers
- [ ] Responsive layout matching Manager Screener patterns
- [ ] Search uses sequence counter (not AbortController)
- [ ] URL-driven pagination with `goto()`
- [ ] Dark mode functional (semantic tokens only)
- [ ] Both tabs load via `Promise.allSettled`
- [ ] All formatters from `@netz/ui`

## Gotchas

- Use TopNav not sidebar for navigation (per wealth frontend review decision)
- Never use raw `fetch()` — always `api.get()` or `api.post()` from client
- `Promise.allSettled` in server load (never `Promise.all`)
- Svelte 5 runes syntax: `$state`, `$derived`, `$effect`, `$props`
- SEC cross-ref is optional — many ESMA managers won't have a CRD match
- "Add to Universe" may need ISIN-based flow (Manager Screener uses CRD-based)
