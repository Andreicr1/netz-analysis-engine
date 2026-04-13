# Screener DataGrid — Clickable Sort Headers

**Date:** 2026-04-13
**Branch:** `feat/screener-sort-headers` (off `main`)
**Scope:** Frontend only — single Svelte component, zero backend changes
**Risk:** LOW — client-side sort on already-loaded data, no API changes
**Priority:** MEDIUM — UX improvement for institutional screener workflow

---

## Problem Statement

The Screener's `TerminalDataGrid` displays ~200 rows per page (cursor pagination) but provides no way to sort by column. The backend default is `sort: "aum_desc"` (hardcoded in `TerminalScreenerShell.svelte` line 142), which is not useful when looking for best scores, lowest expense ratios, or top returns.

Users need clickable column headers that sort the currently loaded dataset client-side.

---

## Target File

**Single file change:**
`frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte`

No changes to `TerminalScreenerShell.svelte` or `+page.svelte` — sort is entirely internal to the DataGrid component.

---

## CONTEXT

### Current Architecture (read before coding)

- **Component:** `TerminalDataGrid.svelte` — virtualized grid with `ROW_HEIGHT=32`, OVERSCAN buffer, CSS Grid layout
- **Props interface** (lines 55-70): `assets: ScreenerAsset[]`, `total`, `loading`, `selectedId`, `highlightedIndex`, etc.
- **Virtual scroll:** `visibleAssets = $derived(assets.slice(startIndex, endIndex))` (line 124). This derives from `assets` directly.
- **Header:** Lines 272-285 — plain `<span class="dg-th">` elements, NOT `<th>`. Uses CSS Grid, not `<table>`.
- **Data type:** `ScreenerAsset` interface (lines 8-38) with typed fields for all columns.
- **Formatters:** `fmtAum()`, `fmtPct()`, `fmtNum()` already exist (lines 179-195).
- **Style tokens:** Terminal design system uses `--terminal-accent-amber`, `--terminal-fg-tertiary`, `--terminal-font-mono`.
- **Svelte 5 runes:** Component uses `$state()`, `$derived()`, `$props()`, `$effect()`. NO legacy `$:` reactive statements.

### Key Constraint

The virtual scroll derives `visibleAssets` from `assets`. Sorting must intercept BEFORE the slice. The chain must be:

```
assets (prop) -> sortedAssets ($derived) -> visibleAssets ($derived from sortedAssets)
```

The existing `visibleAssets = $derived(assets.slice(startIndex, endIndex))` on line 124 must change to derive from `sortedAssets` instead of `assets`.

Similarly, `totalHeight`, `scrollToIndex`, and the `{#each visibleAssets}` block all reference `assets.length` — these must reference `sortedAssets.length` after the change.

---

## OBJECTIVE

Add client-side column sorting to TerminalDataGrid with 3-state toggle (ascending, descending, none) and visual sort indicators.

---

## CONSTRAINTS

1. Svelte 5 runes only (`$state`, `$derived`). No `$:` reactive statements.
2. No new dependencies. No external sort libraries.
3. Terminal aesthetic: monospace carets, amber accent for active sort.
4. Null/undefined values always sort to bottom regardless of direction.
5. Do NOT change the Props interface — sort is internal state only.
6. Do NOT modify `TerminalScreenerShell.svelte` or `+page.svelte`.
7. Preserve all existing functionality: virtual scroll, keyboard nav, focus trigger, action buttons, sparkline infrastructure.
8. Default sort: none (preserves backend's AUM desc ordering as-is).

---

## DELIVERABLES

### 1. Sort State (add after line 126, inside the `<script lang="ts">` block)

```typescript
// ── Sort state ────────────────────────────────────────
type SortDirection = "asc" | "desc" | null;
type SortableColumn =
	| "ticker"
	| "name"
	| "fundType"
	| "strategy"
	| "geography"
	| "aum"
	| "ret1y"
	| "ret10y"
	| "expenseRatioPct"
	| "managerScore";

let sortColumn = $state<SortableColumn | null>(null);
let sortDirection = $state<SortDirection>(null);

function toggleSort(col: SortableColumn) {
	if (sortColumn !== col) {
		sortColumn = col;
		sortDirection = "desc"; // First click = descending (highest first for numeric)
	} else if (sortDirection === "desc") {
		sortDirection = "asc";
	} else {
		// asc -> clear sort (back to backend default order)
		sortColumn = null;
		sortDirection = null;
	}
	// Reset scroll to top on sort change
	if (scrollContainer) {
		scrollContainer.scrollTop = 0;
		scrollTop = 0;
	}
}

/** Column sort key config — defines which columns are sortable and their type */
const SORTABLE_COLUMNS: Record<SortableColumn, "numeric" | "text"> = {
	ticker: "text",
	name: "text",
	fundType: "text",
	strategy: "text",
	geography: "text",
	aum: "numeric",
	ret1y: "numeric",
	ret10y: "numeric",
	expenseRatioPct: "numeric",
	managerScore: "numeric",
};

function sortCaret(col: SortableColumn): string {
	if (sortColumn !== col) return "";
	return sortDirection === "asc" ? " \u25B2" : " \u25BC"; // ▲ or ▼
}
```

### 2. Sorted + Virtual Scroll Derivation (replace existing derivations)

Find and replace the existing derived values. The key change: insert `sortedAssets` between `assets` and `visibleAssets`.

**Find** (lines 118-125):
```typescript
const totalHeight = $derived(assets.length * ROW_HEIGHT);
const visibleCount = $derived(Math.ceil(viewportHeight / ROW_HEIGHT));
const startIndex = $derived(Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN));
const endIndex = $derived(
	Math.min(assets.length, Math.floor(scrollTop / ROW_HEIGHT) + visibleCount + OVERSCAN),
);
const visibleAssets = $derived(assets.slice(startIndex, endIndex));
const offsetY = $derived(startIndex * ROW_HEIGHT);
```

**Replace with:**
```typescript
// ── Sorted asset derivation ───────────────────────────
const sortedAssets = $derived.by(() => {
	if (!sortColumn || !sortDirection) return assets;

	const col = sortColumn;
	const dir = sortDirection;
	const colType = SORTABLE_COLUMNS[col];

	return [...assets].sort((a, b) => {
		const aVal = a[col];
		const bVal = b[col];

		// Nulls always to bottom
		if (aVal == null && bVal == null) return 0;
		if (aVal == null) return 1;
		if (bVal == null) return -1;

		let cmp: number;
		if (colType === "numeric") {
			cmp = (aVal as number) - (bVal as number);
		} else {
			cmp = String(aVal).localeCompare(String(bVal), undefined, { sensitivity: "base" });
		}

		return dir === "asc" ? cmp : -cmp;
	});
});

const totalHeight = $derived(sortedAssets.length * ROW_HEIGHT);
const visibleCount = $derived(Math.ceil(viewportHeight / ROW_HEIGHT));
const startIndex = $derived(Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN));
const endIndex = $derived(
	Math.min(sortedAssets.length, Math.floor(scrollTop / ROW_HEIGHT) + visibleCount + OVERSCAN),
);
const visibleAssets = $derived(sortedAssets.slice(startIndex, endIndex));
const offsetY = $derived(startIndex * ROW_HEIGHT);
```

### 3. Update scrollToIndex to use sortedAssets

**Find** (line 157):
```typescript
if (!scrollContainer || index < 0 || index >= assets.length) return;
```

**Replace with:**
```typescript
if (!scrollContainer || index < 0 || index >= sortedAssets.length) return;
```

### 4. Update infinite scroll threshold check

In the `handleScroll` function, the infinite scroll trigger must still work. No change needed here — `hasMore` is controlled by the parent. But the distance calculation uses `scrollContainer.scrollHeight` which derives from the spacer div, so it works as-is.

### 5. Header Markup (replace lines 272-285)

**Find:**
```svelte
<div class="dg-header" role="row" aria-rowindex={1}>
	<span class="dg-th dg-col-ticker">Ticker</span>
	<span class="dg-th dg-col-name">Name</span>
	<span class="dg-th dg-col-type">Type</span>
	<span class="dg-th dg-col-strategy">Strategy</span>
	<span class="dg-th dg-col-geo">Geo</span>
	<span class="dg-th dg-col-aum dg-right">AUM</span>
	<span class="dg-th dg-col-ret dg-right">1Y Ret</span>
	<span class="dg-th dg-col-ret dg-right">10Y Ret</span>
	<span class="dg-th dg-col-er dg-right">ER%</span>
	<span class="dg-th dg-col-score dg-right">Score</span>
	<span class="dg-th dg-col-action dg-center">Action</span>
</div>
```

**Replace with:**
```svelte
<div class="dg-header" role="row" aria-rowindex={1}>
	<button class="dg-th dg-th-sort dg-col-ticker" class:dg-th-active={sortColumn === "ticker"} onclick={() => toggleSort("ticker")}>Ticker{sortCaret("ticker")}</button>
	<button class="dg-th dg-th-sort dg-col-name" class:dg-th-active={sortColumn === "name"} onclick={() => toggleSort("name")}>Name{sortCaret("name")}</button>
	<button class="dg-th dg-th-sort dg-col-type" class:dg-th-active={sortColumn === "fundType"} onclick={() => toggleSort("fundType")}>Type{sortCaret("fundType")}</button>
	<button class="dg-th dg-th-sort dg-col-strategy" class:dg-th-active={sortColumn === "strategy"} onclick={() => toggleSort("strategy")}>Strategy{sortCaret("strategy")}</button>
	<button class="dg-th dg-th-sort dg-col-geo" class:dg-th-active={sortColumn === "geography"} onclick={() => toggleSort("geography")}>Geo{sortCaret("geography")}</button>
	<button class="dg-th dg-th-sort dg-col-aum dg-right" class:dg-th-active={sortColumn === "aum"} onclick={() => toggleSort("aum")}>AUM{sortCaret("aum")}</button>
	<button class="dg-th dg-th-sort dg-col-ret dg-right" class:dg-th-active={sortColumn === "ret1y"} onclick={() => toggleSort("ret1y")}>1Y Ret{sortCaret("ret1y")}</button>
	<button class="dg-th dg-th-sort dg-col-ret dg-right" class:dg-th-active={sortColumn === "ret10y"} onclick={() => toggleSort("ret10y")}>10Y Ret{sortCaret("ret10y")}</button>
	<button class="dg-th dg-th-sort dg-col-er dg-right" class:dg-th-active={sortColumn === "expenseRatioPct"} onclick={() => toggleSort("expenseRatioPct")}>ER%{sortCaret("expenseRatioPct")}</button>
	<button class="dg-th dg-th-sort dg-col-score dg-right" class:dg-th-active={sortColumn === "managerScore"} onclick={() => toggleSort("managerScore")}>Score{sortCaret("managerScore")}</button>
	<span class="dg-th dg-col-action dg-center">Action</span>
</div>
```

Note: The **Action** column remains a plain `<span>` — it is not sortable.

### 6. CSS for Sort Headers (add inside the `<style>` block, after the existing `.dg-th` rule around line 458)

```css
/* ── Sortable headers ────────────────────────────────── */
.dg-th-sort {
	background: none;
	border: none;
	cursor: pointer;
	text-align: left;
	transition: color 80ms ease;
}
.dg-th-sort:hover {
	color: var(--terminal-fg-secondary);
}
.dg-th-sort.dg-right {
	text-align: right;
}
.dg-th-active {
	color: var(--terminal-accent-amber) !important;
}
```

### 7. Reset sort on filter change (update the fetchGeneration effect)

**Find** (lines 170-176):
```typescript
$effect(() => {
	void fetchGeneration;
	if (scrollContainer) {
		scrollContainer.scrollTop = 0;
		scrollTop = 0;
	}
});
```

**Replace with:**
```typescript
$effect(() => {
	void fetchGeneration;
	// Reset sort and scroll on filter change
	sortColumn = null;
	sortDirection = null;
	if (scrollContainer) {
		scrollContainer.scrollTop = 0;
		scrollTop = 0;
	}
});
```

### 8. Update footer row count references

**Find** in the footer section (the `dg-end-of-catalog` div, line 387):
```svelte
END OF CATALOG — {formatNumber(assets.length, 0)} instruments loaded
```

No change needed here — `assets.length` is correct for the footer because it shows the total loaded count, not the sorted count (they are the same length).

### 9. Update keyboard navigation bounds

In the parent `TerminalScreenerShell.svelte`, keyboard navigation uses `assets.length` from its own state — this is correct because it references the Shell's `assets` array, not the DataGrid's internal sorted view. The `highlightedIndex` passed to DataGrid should index into `sortedAssets`. This is already correct because `highlightedIndex` is managed by the Shell and the DataGrid renders based on `sortedAssets` order.

**Important consideration:** When the user presses ArrowDown/ArrowUp in the Shell, it increments `highlightedIndex` which maps to `assets[highlightedIndex]` in the Shell for Enter/approve/DD actions. But the DataGrid renders `sortedAssets[globalIndex]` visually. This means the highlighted visual row and the Shell's `assets[highlightedIndex]` will diverge when a sort is active.

To fix this properly, the Shell's `handleKeydown` Enter handler dispatches a `focustrigger` event using `assets[highlightedIndex]`. Since the DataGrid is purely visual, and selection happens via `onSelect(asset)` which passes the actual asset object (not an index), the click-to-select flow is correct regardless of sort order.

For keyboard navigation correctness with sorting, add a new callback or keep the current behavior (keyboard always navigates in backend order, clicks navigate in visual order). The simplest correct approach: **do not change the Shell**. Keyboard nav uses backend order (unsorted), mouse clicks use visual (sorted) order. This is acceptable for V1 — a future iteration can pass `sortedAssets` up if needed.

---

## VERIFICATION

1. **Build check:**
   ```bash
   cd frontends/wealth && pnpm check
   ```
   Must pass with zero errors.

2. **Visual verification in browser:**
   - Navigate to `/terminal-screener`
   - Click "AUM" header -> rows reorder by AUM descending (triangle down, amber)
   - Click "AUM" again -> ascending (triangle up, amber)
   - Click "AUM" again -> back to default (no triangle, header returns to tertiary color)
   - Click "Score" -> descending by score, null scores at bottom
   - Click "ER%" -> descending by expense ratio
   - Change a filter (e.g., toggle ELITE) -> sort resets, no triangle visible
   - Scroll down -> infinite scroll still triggers loadMore
   - Click a row -> FocusMode still opens correctly
   - Keyboard navigation (arrow keys) still works

3. **Edge cases to verify:**
   - Sort by Score with many null values -> nulls at bottom
   - Sort by Ticker (text) -> alphabetical, case-insensitive
   - Sort by 1Y Ret -> negative returns sort correctly (e.g., -5% < 2% < 10%)
   - Load more rows while sorted -> new rows integrate into sort order (they will, because `sortedAssets` is derived from `assets` which grows on loadMore)
   - Action column (APPROVE/+DD) buttons still work after sort

---

## ANTI-PATTERNS

1. **Do NOT add `sort_by` query parameter to the backend API call.** This is client-side sort only on loaded data. Server sort remains `aum_desc`.
2. **Do NOT use `Array.prototype.sort()` without spreading first** — `assets` is a prop; mutating it in-place causes upstream bugs. Always `[...assets].sort()`.
3. **Do NOT use `$:` reactive statements** — this is Svelte 5, use `$derived` and `$state` only.
4. **Do NOT add new Props** — sort state is internal to the DataGrid, not controlled by the parent.
5. **Do NOT use `localStorage`** to persist sort state — terminal components use in-memory state only (per project rules).
6. **Do NOT install any dependencies.**

---

## COMMIT

```
feat(screener): add clickable sort headers to TerminalDataGrid

Column headers (Ticker, Name, Type, Strategy, Geo, AUM, 1Y Ret,
10Y Ret, ER%, Score) are now sortable via click. Three-state toggle:
desc -> asc -> clear. Active sort column highlighted with amber
accent and directional caret. Null values sort to bottom.
Sort resets on filter change. Client-side only on loaded rows.
```
