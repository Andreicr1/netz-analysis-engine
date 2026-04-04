---
module: Wealth Frontend
date: 2026-04-04
problem_type: performance_issue
component: frontend_stimulus
symptoms:
  - "Dashboard fires 14 HTTP requests + 1 SSE + 1 interval timer on load"
  - "Risk store SSR data ignored — 3 duplicate requests on every dashboard mount"
  - "Re-navigation between dashboard and risk page causes 8+ redundant requests"
  - "AllocationView fires 4 client-side requests on mount with zero SSR"
  - "300ms artificial delay in risk store Group B fetches"
root_cause: async_timing
resolution_type: code_fix
severity: critical
tags: [over-fetching, sse, risk-store, svelte-lifecycle, ssr, cache, allocation-view, network-performance]
---

# Troubleshooting: Wealth Frontend Over-Fetching — Risk Store Lifecycle Leak + AllocationView Zero-SSR

## Problem

The Wealth frontend was firing ~20-25 redundant API requests per typical navigation session due to a risk store lifecycle mismatch (SSR data ignored, double-start on navigation), an AllocationView component with zero SSR (100% client-side fetching), and a 300ms artificial delay in the risk store's fetch pipeline.

## Environment

- Module: Wealth Frontend (SvelteKit)
- Framework: SvelteKit + Svelte 5 runes
- Affected Components: `risk-store.svelte.ts`, `(app)/+layout.svelte`, `dashboard/+page.svelte`, `analysis/risk/+page.svelte`, `AllocationView.svelte`, `portfolio/builder/+page.server.ts`
- Date: 2026-04-04

## Symptoms

- Dashboard load fires 14 HTTP requests + 1 SSE connection + 1 `setInterval(2000ms)` timer
- SSR load function fetches `/risk/summary`, `/risk/regime`, `/analytics/strategy-drift/alerts` — then risk store's `fetchAll()` fetches the same 3 endpoints again 2 seconds later
- `seedFromSSR()` method existed in the risk store but was never called by the dashboard
- Navigating Dashboard → Analysis → Dashboard triggers full `start()` + `fetchAll()` cycle again (8+ requests)
- AllocationView on `/portfolio/builder` fetches 4 endpoints client-side on mount, plus 4 more on every profile tab switch — with zero SSR and no cache
- 300ms `setTimeout` stagger between Group A and Group B fetches in risk store with no technical justification

## What Didn't Work

**Direct solution:** The problems were identified through comprehensive audit and fixed on the first attempt. The key insight was that the risk store was created at layout level but its lifecycle (start/destroy) was managed by child pages, causing repeated initialization cycles.

## Solution

### Fix 1: Risk Store Lifecycle — Move to Layout (Findings #1, #2)

**Before (broken):** Dashboard page managed start/destroy with a 2-second delay timer:

```typescript
// dashboard/+page.svelte (BEFORE)
onMount(() => {
    const timer = setTimeout(() => {
        try { riskStore.start(); } catch (e) { console.warn(...); }
    }, 2000);
    return () => { clearTimeout(timer); riskStore.destroy(); };
});
```

**After (fixed):** Layout manages lifecycle once; pages only seed SSR data:

```typescript
// (app)/+layout.svelte — lifecycle managed once at layout level
onMount(() => {
    riskStore.start(true); // SSE only, no fetchAll
    return () => riskStore.destroy();
});

// dashboard/+page.svelte — seed SSR data, no start/destroy
onMount(() => {
    if (data.riskSummary || data.regime) {
        riskStore.seedFromSSR({
            riskSummary: data.riskSummary,
            regime: data.regime,
            driftAlerts: data.alerts,
        });
    }
});
```

### Fix 2: Double-Start Guard (Finding #2)

Added `started` flag to risk store to prevent duplicate initialization:

```typescript
// risk-store.svelte.ts
let started = false;

function start(skipInitialFetch = false) {
    if (started) return; // guard
    started = true;
    // ...
}

function destroy() {
    started = false;
    // ...
}
```

### Fix 3: Remove 300ms Artificial Delay (Finding #6)

```typescript
// BEFORE:
// ── Group B: enrichment — history and macro (staggered 300ms) ──
await new Promise((r) => setTimeout(r, 300));

// AFTER: line removed entirely
// ── Group B: enrichment — history and macro ──
```

### Fix 4: AllocationView to SSR (Finding #3)

**Before:** `portfolio/builder/+page.server.ts` returned `{}` — AllocationView fetched everything client-side with `$effect(() => fetchProfile(activeProfile))`.

**After:** SSR load function fetches all 4 endpoints in parallel:

```typescript
// portfolio/builder/+page.server.ts
export const load = async (event) => {
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

Profile tab switch uses `goto()` with `replaceState` (re-runs SSR load):

```typescript
function switchProfile(profile: Profile) {
    goto(`/portfolio/builder?profile=${profile}`, { replaceState: true });
}
```

### Fix 5: Client-Side Cache Layer (Finding #4)

Created `lib/api/cache.ts` with in-memory stale-while-revalidate cache:

```typescript
export async function cachedGet<T>(api, url, params?, ttl?): Promise<T> {
    const key = buildKey(url, params);
    const entry = cache.get(key);
    if (entry && Date.now() - entry.ts < ttlFor(url, ttl)) {
        return entry.data as T;
    }
    const data = await api.get<T>(url, params);
    cache.set(key, { data, ts: Date.now() });
    return data;
}
```

Endpoint-specific TTLs: `/universe` (5min), `/blended-benchmarks/blocks` (5min), `/model-portfolios` (2min), `/portfolios` (1min).

## Why This Works

1. **Risk store lifecycle at layout level:** The `(app)/+layout.svelte` stays mounted across all page navigations within the app. By starting the risk store here once (with SSE-only, no fetchAll), we avoid re-initialization on every page navigation. The `started` guard prevents double-start if any page still tries to call `start()`.

2. **seedFromSSR bridges SSR → client state:** Pages that fetch risk data in their SSR load functions (dashboard, risk) call `seedFromSSR()` to populate the store immediately. The monotonic version counter (already existing in the store) ensures SSE events (version N+1) will correctly overwrite the seed (version 1).

3. **Timing is correct:** Layout `onMount` fires before child page `onMount` in Svelte. So: layout starts SSE (version=0, no data) → dashboard mounts and seeds (version=1, SSR data visible) → SSE delivers first event (version=2, live data). No race condition.

4. **AllocationView SSR eliminates client-side fetch cascade:** Moving to SSR means data arrives with the page HTML. Profile switches via `goto()` re-run the server load function (4 parallel fetches server-to-server, fast), avoiding the previous pattern of 4 client-to-server fetches per tab switch.

5. **Cache prevents cross-page duplication:** Stable endpoints like `/universe` are cached in-memory for 5 minutes, so navigating between analysis, portfolio/approved, and portfolio/models doesn't re-fetch the same data.

## Prevention

- **Rule: Store lifecycle must match store scope.** If a store is scoped to a layout (via `setContext`), its `start()`/`destroy()` must live in that layout's `onMount`, not in child pages. Child pages only read or seed.
- **Rule: Always use `seedFromSSR()` when SSR data is available.** If a load function fetches data that a client-side store also manages, seed the store immediately on mount to avoid duplicate fetches.
- **Rule: Prefer SSR for initial data loads.** Components should receive data as props from `+page.server.ts`, not fetch client-side on mount. Client-side fetches are only for: (a) user-triggered mutations, (b) SSE streaming, (c) real-time updates.
- **Rule: No artificial delays in fetch pipelines.** `setTimeout` staggering between fetch groups has no technical justification — the backend handles concurrency natively.
- **Rule: Add `started` guards to singleton stores.** Any store that can be started from multiple call sites needs a guard to prevent double initialization.

## Related Issues

- See also: [rls-subselect-1000x-slowdown-Database-20260315.md](rls-subselect-1000x-slowdown-Database-20260315.md) — another performance issue in the same vertical (backend-side RLS)
