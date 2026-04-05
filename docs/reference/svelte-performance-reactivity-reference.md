# Svelte 5 Performance & Reactivity Reference

> Authoritative reference for the rate-limiting reactivity layer in the Wealth OS frontend.
> Last updated: 2026-04-05 (Phase 11 — Global Performance Optimization).

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

Reserved for future implementation. No current components use `onscroll` / `onresize` listeners or WebSocket live feeds. The rune is ready:

| Future Use Case | Recommended Limit | Edge Config |
|-----------------|-------------------|-------------|
| Sticky headers on scroll | 100ms | `leading: true, trailing: true` |
| Window resize layout recalc | 150ms | `leading: false, trailing: true` |
| Live price ticker (WebSocket) | 250–500ms | `leading: true, trailing: true` |

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
