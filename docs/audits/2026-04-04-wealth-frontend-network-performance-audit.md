# Wealth Frontend Network Performance Audit

**Date:** 2026-04-04
**Scope:** All SvelteKit routes, stores, and components in `frontends/wealth/src/`
**Focus:** Over-fetching, waterfall requests, duplicate API calls, missing cache, lifecycle leaks

---

## Executive Summary

Audited **31 load functions**, **~45 unique API endpoints**, and **90+ Svelte components** across the Wealth vertical frontend. The codebase has strong foundational patterns (Promise.all in SSR, proper AbortController cleanup, monotonic version gating in risk store), but suffers from **5 architectural problems** that compound into severe network pressure on the backend.

**Estimated waste:** ~20-25 redundant requests per typical user navigation session.

---

## Surface Map: Request Inventory

### SSR Load Functions (31 total)

| Route | Endpoints | Pattern | Calls |
|-------|-----------|---------|-------|
| `/dashboard` | `/risk/summary`, `/risk/regime`, `/analytics/strategy-drift/alerts`, `/portfolios/{p}/snapshot` x3 | Promise.all | 6 |
| `/analysis` | `/analytics/attribution/{p}`, `/analytics/strategy-drift/alerts?limit=100`, `/analytics/correlation`, `/analytics/correlation-regime/{p}`, `/universe` | Promise.all | 5 |
| `/analysis/risk` | `/risk/summary`, `/risk/regime`, `/analytics/strategy-drift/alerts` | Promise.all | 3 |
| `/analysis/[entityId]` | `/analytics/entity/{id}`, `/analytics/peer-group/{id}`, `/analytics/active-share/{id}` (conditional) | Promise.all | 2-3 |
| `/analysis/exposure` | `/wealth/exposure/matrix?dimension=geographic`, `...?dimension=sector`, `/portfolios` | Promise.all | 3 |
| `/market` | `/macro/scores`, `/macro/regime`, `/risk/macro`, `/macro/snapshot`, `/macro/reviews?limit=20` | Promise.all | 5 |
| `/market/reviews/[id]` | `/macro/reviews?limit=50` (fetches 50, filters 1) | Sequential | 1 |
| `/portfolios` | `/portfolios` | Sequential | 1 |
| `/portfolios/[profile]` | `/portfolios/{p}`, `/portfolios/{p}/snapshot`, `/allocation/{p}/strategic`, `/allocation/{p}/effective`, `/blended-benchmarks/blocks`, `/model-portfolios`, then conditional `/model-portfolios/{id}/overlap`, `/fact-sheets/model-portfolios/{id}` | Mixed | 6-8 |
| `/portfolio/approved` | `/universe`, `/universe/pending` | Promise.allSettled | 2 |
| `/portfolio/builder` | **(none — returns `{}`)** | N/A | 0 |
| `/portfolio/models` | `/model-portfolios` | Sequential | 1 |
| `/portfolio/models/create` | `/universe`, `/allocation/moderate/strategic`, `/macro/reviews?status=approved&limit=5`, `/model-portfolios` | Promise.all | 4 |
| `/portfolio/models/[id]` | `/model-portfolios/{id}`, `.../{id}/track-record`, `/fact-sheets/model-portfolios/{id}`, `.../{id}/views`, `/universe`, `.../{id}/overlap`, `/reporting/.../monthly-report/history`, `/reporting/.../long-form-report/history` | Promise.all | 8 |
| `/portfolio/policy` | `/admin/configs/liquid_funds/calibration`, `.../scoring`, `.../portfolio_profiles` | Promise.allSettled | 3 |
| `/screener` | `/screener/catalog?page={p}&page_size=50&q={q}` (conditional on tab) | Conditional | 0-1 |
| `/screener/fund/[id]` | `/screener/catalog/{id}/fact-sheet` | Sequential | 1 |
| `/screener/runs/[runId]` | `/screener/runs/{id}`, `/screener/results?limit=1000` | Promise.all | 2 |
| `/screener/dd-reports` | `/dd-reports/?status={s}` | Sequential | 1 |
| `/screener/dd-reports/[fundId]` | `/dd-reports/funds/{id}`, `/funds/{id}` | Promise.all | 2 |
| `/screener/dd-reports/[fundId]/[reportId]` | `/dd-reports/{id}` | Sequential | 1 |
| `/content` | `/content`, `/funds` | Promise.all | 2 |
| `/content/[id]` | `/content/{id}` | Sequential | 1 |
| `/documents` | `/wealth/documents?limit=100&domain={d}` | Sequential | 1 |
| `/documents/[documentId]` | `/wealth/documents/{id}` | Sequential | 1 |
| `/settings/config` | `/admin/configs/liquid_funds/calibration`, `.../scoring`, `.../portfolio_profiles` | Promise.allSettled | 3 |
| `/settings/system` | `/admin/health/services`, `.../workers`, `.../pipelines` | Promise.allSettled | 3 |

### Client-Side Fetches (stores + components)

| Source | Endpoints | Trigger | Pattern |
|--------|-----------|---------|---------|
| **risk-store.svelte.ts** (Group A) | `/risk/summary`, `/risk/regime`, `/analytics/strategy-drift/alerts` | `start()` / poll fallback | Promise.allSettled |
| **risk-store.svelte.ts** (Group A fallback) | `/risk/{p}/cvar` x3 | Batch failure | Promise.allSettled |
| **risk-store.svelte.ts** (Group B) | `/risk/regime/history`, `/risk/macro`, `/risk/{p}/cvar/history` x3 | 300ms after Group A | Promise.allSettled |
| **risk-store.svelte.ts** (SSE) | `/risk/stream` | After fetchAll | SSE + heartbeat |
| **AllocationView.svelte** | `/blended-benchmarks/blocks`, `/allocation/{p}/strategic`, `.../tactical`, `.../effective` | `$effect` on profile tab | Promise.all |
| **ManagerDetailPanel.svelte** | `/screener/catalog?manager_id={crd}` | `$effect` on open + manager | Single fetch |
| **ManagerFundsSheet.svelte** | `/screener/catalog?manager_id={crd}` | `$effect` on open + managerId | Single fetch |
| **FundClassesSheet.svelte** | `/screener/catalog/{id}/classes` | `$effect` on open + fundId | Single fetch |
| **DriftHistoryPanel.svelte** | `/analytics/strategy-drift/{id}/history` | Manual filter change (no debounce) | Single fetch |
| **GlobalSearch.svelte** | `/search/global?q={q}` | `$effect` on searchQuery (300ms debounce) | Debounced |
| **ScreenerFilters.svelte** | Triggers page navigation (SSR re-fetch) | `debouncedApply()` (300ms) | Debounced |
| **Content +page.svelte** | `invalidateAll()` | `setInterval(5000)` when items generating | Polling |
| **AiAgentDrawer.svelte** | `/wealth/agent/chat` | User-triggered POST | SSE stream |
| **LongFormReportPanel.svelte** | `/reporting/.../long-form-report/stream/{jobId}` | User-triggered | SSE stream |
| **MonthlyReportPanel.svelte** | `/reporting/.../monthly-report/stream/{jobId}` | User-triggered | SSE stream |
| **DD Report +page.svelte** | `/dd-reports/{id}/stream` | onMount | SSE stream |
| **IngestionProgress.svelte** | `/jobs/{jobId}/stream` | onMount | SSE stream |

---

## Critical Findings

### FINDING #1 — Dashboard Double-Fetch: SSR + Risk Store (CRITICAL)

**Impact:** 8 wasted requests + 300ms artificial delay on every dashboard load.

**Request timeline on dashboard navigation:**

```
T=0     SSR load function fires:
        → /risk/summary              ← FETCH
        → /risk/regime               ← FETCH
        → /strategy-drift/alerts     ← FETCH
        → /portfolios/*/snapshot x3  ← FETCH
        = 6 requests (parallel)

T=0     Page renders with SSR data (good)

T=2000  onMount setTimeout fires → riskStore.start()
        → riskStore.fetchAll() fires:
          → /risk/summary            ← DUPLICATE of SSR
          → /risk/regime             ← DUPLICATE of SSR
          → /strategy-drift/alerts   ← DUPLICATE of SSR
          = 3 WASTED requests

T=2300  300ms artificial stagger delay

T=2300  Group B fires:
          → /risk/regime/history
          → /risk/macro
          → /risk/*/cvar/history x3
          = 5 requests

T=2300+ SSE connects → /risk/stream
        + setInterval(2000) for SSE status monitoring
```

**Total: 14 HTTP requests + 1 SSE connection + 1 interval timer.**

**Root cause:** `dashboard/+page.svelte:16-17` calls `riskStore.start()` without `skipInitialFetch`, ignoring the SSR data. The `seedFromSSR()` method exists in the risk store (`risk-store.svelte.ts:474-495`) but is never called.

```typescript
// Current (broken)
onMount(() => {
    const timer = setTimeout(() => {
        try { riskStore.start(); } catch (e) { console.warn(...); }
    }, 2000);
    return () => { clearTimeout(timer); riskStore.destroy(); };
});

// Fixed
onMount(() => {
    riskStore.seedFromSSR(data);
    riskStore.start(true); // skipInitialFetch = true → goes straight to SSE
    return () => riskStore.destroy();
});
```

**Savings:** 3 duplicate requests eliminated. 2-second unnecessary delay eliminated.

---

### FINDING #2 — Risk Store Lifecycle Leak (HIGH)

**Impact:** 8+ wasted requests per re-navigation to dashboard.

**Location:** `(app)/+layout.svelte:23-28` creates the store. `dashboard/+page.svelte:15-19` calls `start()`/`destroy()`.

The risk store is a layout-level singleton, but its lifecycle (start/stop) is managed by a child page. This causes:

1. **Re-navigation waste:** Navigating Dashboard → Analysis → Dashboard triggers a new `onMount`, calling `start()` again (full `fetchAll()` + SSE reconnection).
2. **SSE connection leak:** If the user navigates away quickly before the 2-second setTimeout fires, `destroy()` runs but the timer may still fire on a stale reference.
3. **Overlap with /analysis/risk:** That page fetches the same 3 core endpoints via SSR, completely independent of the risk store.

**Fix:** Move `start()`/`destroy()` to the layout level. Pages only read from the store.

```svelte
<!-- (app)/+layout.svelte — add lifecycle management -->
<script>
  import { onMount } from "svelte";

  onMount(() => {
    const timer = setTimeout(() => riskStore.start(), 1000);
    return () => {
      clearTimeout(timer);
      riskStore.destroy();
    };
  });
</script>
```

Dashboard and Risk pages: remove `start()`/`destroy()` calls. Only use `riskStore.cvarByProfile`, `riskStore.regime`, etc.

---

### FINDING #3 — AllocationView: Zero SSR, 100% Client-Side Fetch (HIGH)

**Impact:** 4 requests on mount + 4 requests per profile tab switch, with no cache.

**Location:** `portfolio/builder/+page.server.ts` returns `{}`. `AllocationView.svelte:79-100` does all fetching client-side.

```typescript
// AllocationView.svelte:98-100
$effect(() => {
    fetchProfile(activeProfile); // 4 API calls, every tab switch
});
```

Compare with `portfolios/[profile]/+page.server.ts` which fetches `strategic` and `effective` via SSR. Same data, two paths, zero sharing.

**Fix:** Move fetches to SSR. Profile switches use `goto(?profile=growth)` which re-executes the load function server-side.

```typescript
// portfolio/builder/+page.server.ts
export const load: PageServerLoad = async (event) => {
    const { token } = await event.parent();
    const api = createServerApiClient(token);
    const profile = event.url.searchParams.get("profile") ?? "moderate";

    const [blocks, strategic, tactical, effective] = await Promise.all([
        api.get("/blended-benchmarks/blocks"),
        api.get(`/allocation/${profile}/strategic`),
        api.get(`/allocation/${profile}/tactical`),
        api.get(`/allocation/${profile}/effective`),
    ]);

    return { blocks, strategic, tactical, effective, profile };
};
```

---

### FINDING #4 — Cross-Page Endpoint Duplication Without Cache (MEDIUM)

**Impact:** 3-5 redundant requests per navigation between pages.

Endpoints fetched independently by multiple pages with no shared cache:

| Endpoint | Pages |
|----------|-------|
| `/risk/summary?profiles=...` | dashboard SSR, analysis/risk SSR, risk store client |
| `/risk/regime` | dashboard SSR, analysis/risk SSR, risk store client |
| `/analytics/strategy-drift/alerts` | dashboard SSR, analysis/risk SSR, analysis SSR, risk store client |
| `/risk/macro` | market SSR, risk store client |
| `/universe` | analysis SSR, portfolio/approved SSR, portfolio/models/create SSR, portfolio/models/[id] SSR |
| `/portfolios` | exposure SSR, portfolios list SSR |
| `/model-portfolios` | portfolios/[profile] SSR, portfolio/models SSR, portfolio/models/create SSR |
| `/blended-benchmarks/blocks` | AllocationView client, portfolios/[profile] SSR |
| `/admin/configs/liquid_funds/*` | portfolio/policy SSR, settings/config SSR (identical 3 fetches) |

Each SvelteKit navigation re-runs the destination page's load function. No cache layer exists between the frontend API client and the backend.

**Fix:** In-memory stale-while-revalidate cache on the client API client for stable endpoints:

```typescript
// lib/api/cache.ts
const cache = new Map<string, { data: unknown; ts: number }>();
const DEFAULT_TTL = 60_000; // 1 minute

export function cachedGet<T>(
    api: ApiClient,
    url: string,
    params?: Record<string, string>,
    ttl = DEFAULT_TTL,
): Promise<T> {
    const key = url + JSON.stringify(params ?? {});
    const entry = cache.get(key);
    if (entry && Date.now() - entry.ts < ttl) {
        return Promise.resolve(entry.data as T);
    }
    return api.get<T>(url, params).then((data) => {
        cache.set(key, { data, ts: Date.now() });
        return data;
    });
}

export function invalidateCache(urlPrefix?: string) {
    if (!urlPrefix) { cache.clear(); return; }
    for (const key of cache.keys()) {
        if (key.startsWith(urlPrefix)) cache.delete(key);
    }
}
```

**Candidate endpoints for caching** (stable data, changes infrequently):
- `/universe` — TTL 5 min
- `/model-portfolios` — TTL 2 min
- `/blended-benchmarks/blocks` — TTL 5 min
- `/admin/configs/*` — TTL 5 min
- `/portfolios` — TTL 1 min

---

### FINDING #5 — Screener Drill-Down Cascade (MEDIUM)

**Impact:** 1-3 redundant requests per drill-down interaction.

The screener has 3 levels of nested Sheet components, each fetching independently:

```
Level 0: +page.server.ts → /screener/catalog?page=1&page_size=50
Level 1: ManagerDetailPanel ($effect) → /screener/catalog?manager_id={crd}&page_size=200
Level 2: ManagerFundsSheet ($effect) → /screener/catalog?manager_id={crd}
Level 3: FundClassesSheet ($effect) → /screener/catalog/{fundId}/classes
```

Levels 1 and 2 fetch essentially the same data (manager's funds) via the same endpoint with slightly different params. Level 3 could be derived from Level 1/2 data (classes are children of funds already fetched).

**Fix:** Pre-fetch manager funds at Level 0 and pass as props:

```typescript
// In screener page component
let managerFundsCache = new Map<string, UnifiedFundItem[]>();

async function openManagerDetail(manager: Manager) {
    if (!managerFundsCache.has(manager.crd)) {
        const result = await api.get("/screener/catalog", {
            manager_id: manager.crd,
            page_size: "200",
        });
        managerFundsCache.set(manager.crd, result.items);
    }
    // Pass cached data as prop instead of letting child fetch
    selectedManagerFunds = managerFundsCache.get(manager.crd)!;
    managerPanelOpen = true;
}
```

---

## Secondary Findings

### FINDING #6 — 300ms Artificial Delay in Risk Store (LOW)

**Location:** `risk-store.svelte.ts:420`

```typescript
// Group B: enrichment — history and macro (staggered 300ms)
await new Promise((r) => setTimeout(r, 300));
```

No technical justification. The backend handles concurrency. This adds 300ms latency to every risk store fetch cycle.

**Fix:** Remove the line.

### FINDING #7 — Content Polling with invalidateAll (LOW)

**Location:** `content/+page.svelte:71-78`

```typescript
$effect(() => {
    if (hasGenerating && !pollTimer && !activeJobId) {
        pollTimer = setInterval(() => { invalidateAll(); }, 5000);
    }
});
```

`invalidateAll()` re-runs the entire page load function (both `/content` and `/funds` endpoints), not just the generating item. This doubles the polling cost.

**Fix:** Poll only the generating content item's status endpoint instead of full page invalidation.

### FINDING #8 — Market Review Detail Over-Fetch (LOW)

**Location:** `market/reviews/[reviewId]/+page.server.ts`

Fetches up to 50 reviews (`/macro/reviews?limit=50`) then filters client-side for the one matching `params.reviewId`. The backend should have a `/macro/reviews/{id}` endpoint.

**Fix:** Add `GET /macro/reviews/{id}` to the backend and use it directly.

### FINDING #9 — DriftHistoryPanel Missing Debounce (LOW)

**Location:** `DriftHistoryPanel.svelte:219-221`

Filter changes (date range, severity) trigger immediate `fetchHistory()` calls with no debouncing. Rapid filter adjustments can fire 5-10 requests in quick succession.

**Fix:** Add 300ms debounce (same pattern as GlobalSearch and ScreenerFilters).

---

## Well-Designed Patterns (Preserve These)

| Pattern | Location | Why It Works |
|---------|----------|-------------|
| Promise.all in SSR load functions | All page.server.ts files | Parallel fetches, no waterfalls |
| Promise.allSettled for resilient pages | policy, system, approved | Individual failure isolation |
| Monotonic version gate in risk store | risk-store.svelte.ts:154-201 | Prevents stale poll overwriting fresh SSE |
| AbortController cleanup in SSE | AiAgentDrawer, LongFormReportPanel, etc. | Proper connection lifecycle |
| `$state.raw` for large arrays | risk-store.svelte.ts:114-117 | Avoids Svelte proxy overhead |
| 300ms debounce on search | GlobalSearch, ScreenerFilters | Prevents request spam |
| Conditional fetch on sheet open | ManagerDetailPanel, FundClassesSheet | Lazy loading, no wasted fetches |
| SSE via fetch+ReadableStream | All SSE consumers | Auth headers (no EventSource limitation) |

---

## Refactoring Strategy: The Orchestrator Pattern

### Principle: "One fetch per route, store as cache"

The frontend should request the macro state needed for the current route, store it, and render. Components receive data via props from the route orchestrator — they never fetch their own data.

### Implementation Priority

| # | Action | Requests Eliminated | Complexity | Files Changed |
|---|--------|-------------------|------------|---------------|
| 1 | Risk Store SSR seed + skip | -3 per dashboard load | Trivial | 1 file |
| 2 | Risk Store lifecycle to layout | -8 per re-navigation | Low | 2 files |
| 3 | Remove 300ms delay | -300ms latency | Trivial | 1 file |
| 4 | AllocationView to SSR | -4 per tab switch | Medium | 2 files |
| 5 | In-memory cache for stable endpoints | -3-5 per navigation | Medium | 3-4 files |
| 6 | Screener pre-fetch + prop drilling | -1-3 per drill-down | Low | 3 files |
| 7 | Content targeted polling | -1 per 5s poll cycle | Low | 1 file |
| 8 | DriftHistory debounce | Variable | Trivial | 1 file |

**Total estimated savings: ~20-25 requests per typical navigation session.**

---

## Appendix: Request Flow Diagrams

### Dashboard Load (Current)

```
Browser                    SvelteKit Server             Backend
  |                              |                          |
  |── GET /dashboard ──────────> |                          |
  |                              |── /risk/summary ────────>|
  |                              |── /risk/regime ─────────>|
  |                              |── /strategy-drift/alerts>|
  |                              |── /portfolios/*/snap x3 >|
  |                              |<── 6 responses ──────────|
  |<── SSR HTML ─────────────────|                          |
  |                              |                          |
  | [T+2s onMount]               |                          |
  |── /risk/summary ──────────────────────────────────────> | DUPLICATE
  |── /risk/regime ───────────────────────────────────────> | DUPLICATE
  |── /strategy-drift/alerts ─────────────────────────────> | DUPLICATE
  |<── 3 responses ────────────────────────────────────────|
  |                              |                          |
  | [T+2.3s after 300ms delay]   |                          |
  |── /risk/regime/history ───────────────────────────────> |
  |── /risk/macro ────────────────────────────────────────> |
  |── /risk/*/cvar/history x3 ────────────────────────────> |
  |<── 5 responses ────────────────────────────────────────|
  |                              |                          |
  |── SSE /risk/stream ──────────────────────────────────> | PERSISTENT
```

### Dashboard Load (Fixed)

```
Browser                    SvelteKit Server             Backend
  |                              |                          |
  |── GET /dashboard ──────────> |                          |
  |                              |── /risk/summary ────────>|
  |                              |── /risk/regime ─────────>|
  |                              |── /strategy-drift/alerts>|
  |                              |── /portfolios/*/snap x3 >|
  |                              |<── 6 responses ──────────|
  |<── SSR HTML ─────────────────|                          |
  |                              |                          |
  | [onMount — immediate]        |                          |
  | seedFromSSR(data)            |                          |
  | start(skipInitialFetch=true) |                          |
  |── SSE /risk/stream ──────────────────────────────────> | PERSISTENT
  |                              |                          |
  | [SSE delivers updates]       |                          |
  |<── regime change ────────────────────────────────────> |
  |<── cvar update ──────────────────────────────────────> |
```
