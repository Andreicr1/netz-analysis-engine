# Svelte 5 Performance & Reactivity Reference

> Authoritative reference for the rate-limiting reactivity layer in the Wealth OS frontend.
> Last updated: 2026-04-06 (Phase 12 — ECharts live tick reactivity over Tiingo IEX Firehose).

---

## 1. Problem Statement

Institutional finance UIs are data-intensive: screener tables with 10k+ rows, macro charting with 80+ indicator catalogs, portfolio builders with drag-and-drop. Svelte 5's fine-grained reactivity (`$state` / `$derived`) is fast, but connecting a raw `$state` directly to an expensive `$derived` (array filter, API call, URL navigation) causes jank when the user types or moves the mouse at high frequency.

**Solution:** A thin layer of rate-limiting runes that sit between user input and expensive downstream computation. The input stays at 60fps; the computation runs at a controlled cadence.

---

## 2. Architecture

```
User Input (60fps)           Rate-Limiting Rune           Expensive Downstream
─────────────────           ──────────────────           ────────────────────
keystroke → .current ──→  debounce/throttle/rAF  ──→  .debounced/.throttled/.synced
                              │                              │
                              │  $effect cleanup:            │  $derived / $effect
                              │  clearTimeout /              │  filters, API calls,
                              │  cancelAnimationFrame        │  goto() navigation
                              ▼                              ▼
                         Timer/rAF lifecycle           Runs only when settled
```

**Key invariant:** `.current` is always immediately reactive (input never lags). The optimized accessor (`.debounced`, `.throttled`, `.synced`) is the only one wired to expensive operations.

---

## 3. Rune Library

Location: `frontends/wealth/src/lib/utils/reactivity/`

### 3.1 `createDebouncedState<T>(init, delay)`

**File:** `debounced.svelte.ts`

Delays the optimized value update until the user stops changing `.current` for `delay` milliseconds. Best for search inputs and filter fields where only the final value matters.

```typescript
const search = createDebouncedState("", 300);

// Template: bind to .current for instant feedback
// <input value={search.current} oninput={(e) => { search.current = e.currentTarget.value; }} />

// Downstream: depend on .debounced for filtered results
let results = $derived.by(() => {
  const q = search.debounced.trim().toLowerCase();
  if (!q) return allItems;
  return allItems.filter((item) => item.name.includes(q));
});
```

**API:**

| Member | Type | Description |
|--------|------|-------------|
| `.current` | get/set `T` | Immediate value — bind to UI inputs |
| `.debounced` | get `T` | Settled value — use in `$derived` / `$effect` |
| `.cancel()` | `() => void` | Cancel pending timer without updating |
| `.flush()` | `() => void` | Immediately push `.current` to `.debounced` (e.g., on Enter key) |

**Cleanup:** `$effect` return calls `clearTimeout` — no leaked timers on component destroy.

### 3.2 `createThrottledState<T>(init, limit, options?)`

**File:** `throttled.svelte.ts`

Ensures the optimized value updates at most once per `limit` milliseconds. Supports `leading` and `trailing` edges. Best for scroll, resize, and high-frequency data feeds where periodic updates are needed.

```typescript
const scrollY = createThrottledState(0, 100);

// On scroll event:
// scrollY.current = window.scrollY;

// Downstream: use .throttled for sticky header calculations
let isSticky = $derived(scrollY.throttled > 200);
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `leading` | `true` | Fire immediately on first change |
| `trailing` | `true` | Fire after the quiet period ends |

**API:** Same shape as debounced (`.current`, `.throttled`, `.cancel()`, `.flush()`).

**Cleanup:** `$effect` return calls `clearTimeout`.

### 3.3 `createRafState<T>(init)`

**File:** `raf.svelte.ts`

Batches updates to the next `requestAnimationFrame` tick. Best for cursor tracking, tooltip positioning, and drag visual feedback — anything that should sync with the display refresh rate.

```typescript
const cursor = createRafState({ x: 0, y: 0 });

// On mousemove:
// cursor.current = { x: e.clientX, y: e.clientY };

// Downstream: use .synced for rendering — always aligned to vsync
// <div style:transform="translate({cursor.synced.x}px, {cursor.synced.y}px)" />
```

**API:** `.current` (get/set), `.synced` (get), `.cancel()`, `.flush()`.

**Cleanup:** `$effect` return calls `cancelAnimationFrame`.

### 3.4 Barrel Export

```typescript
// Import from:
import { createDebouncedState, createThrottledState, createRafState } from "$lib/utils/reactivity";
```

---

## 4. Svelte 5 Binding Constraint

Svelte 5 `bind:value` only works on `$state` or `$props` — not on getter/setter objects. Since our runes return plain objects with getters/setters, use the `value` + `oninput` pattern instead:

```svelte
<!-- WRONG: bind:value won't work on a getter/setter -->
<input bind:value={search.current} />

<!-- CORRECT: explicit value + oninput -->
<input
  value={search.current}
  oninput={(e) => { search.current = e.currentTarget.value; }}
/>
```

For `onkeydown` Enter flush:

```svelte
<input
  value={search.current}
  oninput={(e) => { search.current = e.currentTarget.value; }}
  onkeydown={(e) => { if (e.key === "Enter") search.flush(); }}
/>
```

---

## 5. Application Map

### 5.1 Debounce (300ms) — Search & Filter Inputs

| Component | Input | Delay | Flush Trigger |
|-----------|-------|-------|---------------|
| `ScreenerFilters.svelte` | Main search (`searchQ`), all filter fields | 300ms | Enter key → `applyFilters()` |
| `ManagerFilterSidebar.svelte` | Manager text search | 300ms | Enter key → `managerSearch.flush()` |
| `GlobalSearch.svelte` | Command palette query (Cmd+K) | 300ms | Dialog reset → `search.flush()` |
| `UniversePanel.svelte` | Fund search in portfolio sidebar | 300ms | Enter key → `search.flush()` |
| `SeriesPicker.svelte` | Macro indicator catalog search | 250ms | — (no Enter action needed) |

### 5.2 Throttle — Scroll/Resize/Live Feeds

| Use Case | Status | Limit | Edge Config | Notes |
|----------|--------|-------|-------------|-------|
| Live price ticker → ECharts overlay | **IMPLEMENTED** (Phase 12) | Implicit (ECharts paint cadence + 1e-9 dedup guard) | n/a | Driven by `$effect` reading `marketStore.totalReturnPct`; see §10 |
| Sticky headers on scroll | Reserved | 100ms | `leading: true, trailing: true` | — |
| Window resize layout recalc | Reserved | 150ms | `leading: false, trailing: true` | — |

### 5.3 rAF — Cursor/Drag/Tooltip Sync

Reserved for future implementation. No current components track cursor coordinates for tooltip positioning (ECharts handles its own tooltips internally). The rune is ready:

| Future Use Case | Description |
|-----------------|-------------|
| Custom DnD ghost position | Replace `ondragover` coordinate tracking with rAF-synced state |
| Chart crosshair overlay | Custom Svelte overlay synced to mouse position over ECharts canvas |
| Resize handle feedback | Smooth panel resize drag indicator |

---

## 6. Decision Log

### Why not `$derived` with a built-in delay?

Svelte 5 has no built-in debounce/throttle primitive. `$derived` is synchronous — it recalculates immediately when dependencies change. The rune layer adds the async scheduling that `$derived` lacks.

### Why not a generic `useDebounce` action?

Svelte actions (`use:debounce`) operate on DOM elements, not reactive state. We need the debounced value to be reactive (usable in `$derived`), which requires `$state` internally. Actions can't provide that.

### Why separate `.current` and `.debounced` instead of a single delayed `$state`?

User experience. The input field must reflect keystrokes instantly (`.current`), while the expensive operation (filtering, API call) should wait (`.debounced`). A single delayed state would make the input feel laggy.

### Why 300ms default for search, 250ms for SeriesPicker?

- **300ms** is the standard UX threshold for "user has paused typing" — matches Google Suggest, VS Code search, and prior inline debounce in this codebase.
- **250ms** for SeriesPicker because the catalog is local (80 items, no API call) — slightly faster feedback improves the charting workflow without cost.

### Why not debounce `<select>` and checkbox changes?

Selects and checkboxes are discrete single-value changes (click = final value). Debounce adds latency without benefit. Only continuous/rapid inputs (typing, sliding, scrolling) need rate limiting.

---

## 7. Memory Cleanup Verification

All three runes use the `$effect` return function for deterministic cleanup:

```typescript
// debounced.svelte.ts / throttled.svelte.ts
$effect(() => {
  // ... schedule timer ...
  return () => clearTimeout(_timer);  // cleanup on re-run or destroy
});

// raf.svelte.ts
$effect(() => {
  // ... schedule rAF ...
  return () => {
    if (_raf !== undefined) {
      cancelAnimationFrame(_raf);
      _raf = undefined;
    }
  };
});
```

**Guarantee:** When the component unmounts, Svelte 5 runs the `$effect` cleanup. No timer or animation frame can fire after the component is destroyed. No memory leaks.

---

## 8. Testing Strategy

The runes are pure reactive primitives — no DOM, no API calls. Test strategies:

1. **Unit tests (Vitest + `@testing-library/svelte`):** Create a minimal test component that uses the rune, advance timers with `vi.useFakeTimers()` / `vi.advanceTimersByTime()`, and assert that `.debounced` / `.throttled` / `.synced` update at the expected cadence.

2. **Integration validation:** `svelte-check` with `--threshold error` (0 errors as of Phase 11). The generic `<T>` type parameter flows correctly through all component usages.

3. **Visual regression:** Browser dev tools Performance panel — record a typing session in ScreenerFilters, verify that `$derived` recalculations cluster at 300ms intervals rather than per-keystroke.

---

## 9. Rules for Contributors

1. **Never wire a raw `$state` input to an expensive `$derived` or `$effect`.** If the downstream operation involves: array filtering (>100 items), API calls, URL navigation (`goto()`), or heavy DOM updates — use a debounced/throttled rune.

2. **Always use `.debounced` / `.throttled` / `.synced` in `$derived`.** Never use `.current` in downstream computation — that defeats the purpose.

3. **Always use `.current` for input binding.** Never bind the input to `.debounced` — that makes typing laggy.

4. **Use `value` + `oninput`, not `bind:value`.** Svelte 5 `bind:value` requires `$state` or `$props`. Our rune objects use getter/setter, which `bind:value` rejects.

5. **Call `.flush()` on Enter key** for search inputs where the user expects immediate results.

6. **Prefer debounce for typed input, throttle for continuous events (scroll/resize/WS), rAF for coordinates (cursor/drag).**

7. **Do not create component-local `setTimeout` debounce.** Always use the shared rune library. This ensures consistent timing, proper cleanup, and a single pattern to audit.

8. **For ECharts live updates, always use `replaceMerge: ['series']` and never recreate the chart instance.** See §10.

---

## 10. ECharts Live Tick Reactivity (Phase 12)

The Tiingo institutional plan turned the WebSocket layer into a true firehose: thousands of trade ticks per second flow through `tiingo_bridge.py` → Redis → `MarketDataStore.totalReturnPct`. Wiring that store directly to a `$derived` ECharts `option` would re-serialize the entire option object on every tick, triggering ECharts' `notMerge: true` code path inside `ChartContainer` and resetting the user's zoom state. This section documents the pattern that avoids both pitfalls.

### 10.1 Architecture

```
Tiingo IEX Firehose
        │
        ▼
backend tiingo_bridge.py ──→ Redis market:prices ──→ ConnectionManager ──→ WebSocket
                                                                                │
                                                                                ▼
                                                              MarketDataStore.priceMap
                                                                                │  ($state)
                                                                                ▼
                                                              MarketDataStore.totalReturnPct
                                                                                │  ($derived from holdings)
                                                                                ▼
                                            $effect in PortfolioNAVChart.svelte
                                                                                │
                                                                                ▼
                                                                chart.setOption(
                                                                  { series: [...] },
                                                                  { replaceMerge: ['series'] }
                                                                )
```

The `$effect` is the rate-limiter: it runs **only when `totalReturnPct` actually changes** (Svelte 5 fine-grained reactivity), and the inner `1e-9` floor short-circuits duplicate ticks before they reach ECharts. No `throttle` rune needed — the rune layer is for events that fire at 60fps regardless of value change (mousemove, scroll), whereas WebSocket ticks already arrive at the right cadence for paint.

### 10.2 Bindable Chart Instance Pattern

`ChartContainer` (in `@investintell/ui/charts`) exposes its internal echarts instance as a `$bindable` prop so callers can drive surgical updates without going through the full `option` re-render path:

```svelte
<!-- ChartContainer.svelte (the shared component) -->
<script lang="ts">
  interface ChartContainerProps extends BaseChartProps {
    option: Record<string, unknown>;
    /** Bindable echarts instance — exposed so callers can drive live
     *  updates via setOption({ replaceMerge }) without triggering the
     *  full notMerge replacement done by this component's $effect. */
    chart?: ReturnType<typeof echarts.init> | undefined;
  }

  let {
    option,
    chart = $bindable(),
    /* ... */
  }: ChartContainerProps = $props();
</script>
```

```svelte
<!-- PortfolioNAVChart.svelte (the consumer) -->
<script lang="ts">
  let chart = $state<ReturnType<typeof echarts.init> | undefined>();
</script>

<ChartContainer {option} bind:chart />
```

**Why bindable, not a callback prop?** `$bindable` is the Svelte 5 idiom for parent ↔ child two-way reactive sharing. A callback prop (`onChartReady`) would require the parent to manage instance lifecycle manually and reconcile mount/unmount. With `bind:chart`, when `ChartContainer` disposes the instance on unmount, the parent's `chart` state automatically becomes `undefined` and the `$effect` short-circuits.

### 10.3 The Live Update `$effect`

```svelte
<script lang="ts">
  import { getContext } from "svelte";
  import type { MarketDataStore } from "$lib/stores/market-data.svelte";

  const marketStore = getContext<MarketDataStore | undefined>("netz:marketDataStore");
  let chart = $state<ReturnType<typeof echarts.init> | undefined>();
  const todayISO = new Date().toISOString().slice(0, 10);
  let livePoint = $state<{ date: string; nav: number } | null>(null);

  $effect(() => {
    if (!marketStore || !chart) return;
    if (visibleSeries.length === 0) return;

    const liveReturn = marketStore.totalReturnPct;
    if (liveReturn == null) return;

    const lastVisible = visibleSeries[visibleSeries.length - 1]!;
    if (lastVisible.date !== todayISO) return;  // never overwrite history

    const prev = visibleSeries.length > 1
      ? visibleSeries[visibleSeries.length - 2]!.nav
      : lastVisible.nav;
    if (prev === 0) return;

    const liveNav = prev * (1 + liveReturn);
    if (livePoint && Math.abs(livePoint.nav - liveNav) < 1e-9) return;  // dedup

    livePoint = { date: lastVisible.date, nav: liveNav };

    chart.setOption(
      { series: [
          { name: "NAV", type: "line", /* ... patched data ... */ },
          { name: "Live", type: "effectScatter", /* ripple marker */ },
      ] },
      { replaceMerge: ["series"] },
    );
  });
</script>
```

**Five guard clauses, in order:**

1. `marketStore` and `chart` exist (defensive — enables Storybook / SSR).
2. `visibleSeries` non-empty (no chart data → nothing to patch).
3. `liveReturn != null` (no quote yet).
4. `lastVisible.date === todayISO` (**never** rewrite historical bars — they're immutable).
5. `Math.abs(livePoint.nav - liveNav) < 1e-9` (idempotent burst dedup).

### 10.4 Why `replaceMerge: ['series']`

ECharts has three update modes:

| Mode | Behavior | Use case | Side effects |
|------|----------|----------|--------------|
| `notMerge: true` (default in `ChartContainer.$effect`) | Wipe everything, rebuild from scratch | Initial render, full redraw | **Resets `dataZoom`, brushes, legend selection** |
| Default merge (`{}`) | Deep-merge incoming option into existing | Tooltip/title changes | Series array merged element-wise — hard to swap |
| **`replaceMerge: ['series']`** | Replace named keys wholesale, leave the rest untouched | Live data updates | Preserves user's zoom/pan/selection state |

Using `replaceMerge: ['series']` means a user can pinch-zoom the NAV chart to a 2-week window during market hours and the rendering stays pinned to that window across every IEX tick.

### 10.5 The `effectScatter` Ripple

A second series anchored exclusively to the last (today) coordinate provides the visual "alive" signal:

```typescript
{
  name: "Live",
  type: "effectScatter",
  yAxisIndex: 0,
  coordinateSystem: "cartesian2d",
  data: [[lastVisible.date, liveNav]],
  symbolSize: 10,
  rippleEffect: { period: 3, scale: 3.5, brushType: "stroke" },
  showEffectOn: "render",
  zlevel: 2,
  itemStyle: {
    color: liveReturn >= 0 ? "#22c55e" : "#ef4444",
    shadowBlur: 8,
    shadowColor: liveReturn >= 0
      ? "rgba(34, 197, 94, 0.6)"
      : "rgba(239, 68, 68, 0.6)",
  },
  silent: true,
  animation: false,
}
```

**Settings rationale:**

| Field | Why |
|-------|-----|
| `data: [[date, nav]]` | Single coordinate — never plot historical points as ripples |
| `period: 3` | One ripple every 3 s — visible without being a strobe |
| `brushType: "stroke"` | Hollow ring rather than filled disc — overlays cleanly on the line |
| `zlevel: 2` | Draws above the line series |
| `silent: true` | Excluded from tooltip + click hit-testing |
| `animation: false` | The ripple itself is the animation — global animation would re-trigger on every tick |
| `color` flips on sign | Green when portfolio is up on the day, red when down — matches the cumulative return badge |

### 10.6 Anti-Patterns

| Anti-pattern | Why it breaks | Correct pattern |
|--------------|---------------|-----------------|
| Wiring `marketStore.totalReturnPct` into `$derived option` | Re-serializes the entire option on every tick → `ChartContainer.$effect` calls `setOption(..., { notMerge: true })` → zoom resets | Bind chart instance, drive `$effect` directly |
| Calling `chart.setOption(option, true)` | `notMerge: true` resets dataZoom | Use `{ replaceMerge: ['series'] }` |
| Mutating `displaySeries` in place | `$derived` won't re-trigger; ECharts reads stale data | Compute a new `navSeriesPatched` array |
| Updating today's bar in `navSeries` source-of-truth | Pollutes the canonical history with intraday values that flicker | Compute the live overlay locally; never write back |
| `effectScatter` with `data: navSeries` | Renders a ripple on every historical point — visual chaos | Always `data: [[lastDate, lastNav]]` (single coordinate) |
| `getContext` inside `$effect` | Context must be read synchronously during component init | Read once at top of `<script>`, store in a `const` |

### 10.7 Cleanup

The `$effect` has no cleanup function — it doesn't allocate timers, event listeners, or subscriptions. The bindable `chart` instance is cleaned up by `ChartContainer.onMount`'s teardown (`chart.dispose()`), which sets the parent's `chart = undefined` automatically through the `$bindable` link, naturally short-circuiting the effect on the next run.

### 10.8 Components Using This Pattern

| Component | File | Store | Series Patched |
|-----------|------|-------|----------------|
| Portfolio NAV chart | `frontends/wealth/src/lib/components/charts/PortfolioNAVChart.svelte` | `marketStore.totalReturnPct` | `NAV` (line) + `Live` (effectScatter ripple) |
