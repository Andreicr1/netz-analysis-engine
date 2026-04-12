# Phase 3 Fix Sprint 3 — Screener Completeness

**Date:** 2026-04-12
**Branch:** `feat/phase-3-fix-sprint-3`
**Scope:** 6 atomic commits closing the 3 screener gaps that block institutional use
**Estimated duration:** 2-3 hours concentrated Opus session
**Prerequisite reading:** this file only (self-contained)
**Depends on:** Fix Sprint 2 merged (main at `6bbb39e0` or later)

## Why this sprint exists

The screener renders 200 of 9,193 instruments with NO way to see the remaining 8,993. Keyset pagination was implemented in Session 3.A (backend returns `next_cursor`), but the frontend never ships a mechanism to request the next page. An institutional analyst cannot screen the full catalog. Additionally, two critical filter categories — Investment Manager and metric range filters — are missing, preventing the two most common institutional screening workflows.

These are not polish items. They are **functional blockers** that prevent the screener from being usable as a product. Must ship before Phase 4 Builder because the Builder consumes the screener's approved universe — if the screener can only surface 200 funds, the Builder's universe is artificially constrained.

## Project mandate (binding)

> Máximo de percepção visual é válida somente quando a infraestrutura está correta, reportando dados reais e precisos.

The data plane is correct (Phase 2 confirmed, p95 84ms). But data that's correct yet INVISIBLE (8,993 unreachable funds) is not "reportando dados reais e precisos" — it's hiding them. Infinite scroll + filters fix this.

## READ FIRST

1. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — virtual scroll implementation, current fetch pattern, where infinite scroll hooks in
2. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` — the fetch trigger, current filter state, where new filters are added
3. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte` — the filter sidebar, current filter categories
4. `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte` — URL state sync (Session 3.B commit 4), cursor param handling
5. `backend/app/domains/wealth/routes/screener.py` — catalog endpoint, current filter support, keyset cursor implementation
6. `backend/app/domains/wealth/schemas/catalog.py` — `CatalogFilters` model, `UnifiedCatalogPage` response with `next_cursor`
7. `backend/app/domains/wealth/queries/catalog_sql.py` — query builder, WHERE clause construction, how new filters plug in

## Pre-flight

```bash
pnpm --filter netz-wealth-os dev
# Open http://localhost:<port>/terminal-screener
# Confirm: "Showing 200 of 9,193 instruments" with no way to see more
# Confirm: no Investment Manager filter in sidebar
# Confirm: metric filters are limited (Min AUM, Min 1Y Return, Max ER only)
```

---

# COMMIT 1 — feat(screener): infinite scroll with keyset cursor auto-loading

## Problem

`TerminalDataGrid` virtualizes 200 rows but NEVER requests the next page. Backend Session 3.A commit 5 returns `next_cursor` in the response. The frontend ignores it. 8,993 of 9,193 funds are invisible.

## Deliverable

### Infinite scroll pattern in TerminalDataGrid

When the user scrolls within 5 rows of the current data boundary (not the virtual viewport boundary, but the END of the loaded data array), automatically fetch the next page:

```typescript
// In TerminalDataGrid or TerminalScreenerShell (wherever the fetch lives)

let assets = $state<ScreenerAsset[]>([]);
let nextCursor = $state<string | null>(null);
let isLoadingMore = $state(false);

// Watch scroll position relative to data boundary
$effect(() => {
  if (!scrollContainer) return;
  const handler = () => {
    const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    const threshold = ROW_HEIGHT * 5; // 5 rows before the end

    if (distanceFromBottom < threshold && nextCursor && !isLoadingMore) {
      loadNextPage();
    }
  };
  scrollContainer.addEventListener("scroll", handler, { passive: true });
  return () => scrollContainer.removeEventListener("scroll", handler);
});

async function loadNextPage() {
  if (!nextCursor || isLoadingMore) return;
  isLoadingMore = true;
  try {
    const response = await fetchCatalog(currentFilters, nextCursor);
    assets = [...assets, ...response.items]; // APPEND, not replace
    nextCursor = response.next_cursor;
    // Update spacer height for virtual scroll
    totalRows = assets.length;
  } finally {
    isLoadingMore = false;
  }
}
```

### Loading indicator

When `isLoadingMore === true`, show a minimal loading strip at the bottom of the scroll area:

```svelte
{#if isLoadingMore}
  <div class="dg-loading-more">
    LOADING PAGE {Math.ceil(assets.length / 200) + 1}...
  </div>
{/if}
```

Style: monospace, 24px height, centered, `var(--terminal-fg-muted)`, pulsing opacity animation via `var(--terminal-motion-tick)`.

### End-of-catalog indicator

When `nextCursor === null` AND `assets.length > 0`:

```svelte
{#if !nextCursor && assets.length > 0}
  <div class="dg-end-of-catalog">
    END OF CATALOG — {formatNumber(assets.length, 0)} instruments loaded
  </div>
{/if}
```

Style: same as loading, but static. `var(--terminal-fg-tertiary)`.

### Footer update

The existing "Showing 200 of 9,193 instruments" footer should update dynamically:
- During load: `Showing {assets.length} of {total} instruments — loading...`
- After all pages: `Showing {assets.length} of {total} instruments — complete`
- Key insight: `total` comes from the backend response (`total_count` or similar field). Verify the response schema includes a total count.

### Filter change resets

When any filter changes (Session 3.B commit 4 URL sync), the infinite scroll state must RESET:
- `assets = []` (clear loaded data)
- `nextCursor = null` (clear cursor)
- `isLoadingMore = false`
- Fresh fetch with no cursor (page 1)

This is already handled by the URL sync pattern (filter change → `goto()` → page remount or `$derived` re-derivation) but VERIFY that the append array resets correctly on filter change. If the `$effect` that watches `currentFilters` doesn't clear `assets`, you'll get stale data from the previous filter set mixed with new results.

### Debounce scroll events

The scroll handler fires on EVERY scroll pixel. The threshold check is O(1) so it's cheap, but the actual fetch should be debounced to avoid double-firing during fast scroll:

```typescript
let scrollDebounce: ReturnType<typeof setTimeout> | null = null;

function onScroll() {
  if (scrollDebounce) clearTimeout(scrollDebounce);
  scrollDebounce = setTimeout(() => {
    checkAndLoadMore();
  }, 100); // 100ms debounce
}
```

## Verification

1. Open screener → 200 rows load
2. Scroll to row ~195 → next 200 rows load automatically, footer updates to "Showing 400 of 9,193"
3. Continue scrolling → pages keep loading until all 9,193 are loaded
4. "END OF CATALOG" indicator appears after last page
5. Change a filter → loaded data resets to page 1, cursor clears
6. Toggle ELITE → loads only elite funds (≤300), "END OF CATALOG" appears quickly
7. No duplicate rows between pages (keyset ensures this per Session 3.A commit 5 test)
8. Sparkline batch re-fetches for newly-visible rows on each page load

---

# COMMIT 2 — feat(screener/backend): Investment Manager filter in catalog query

## Problem

Institutional analysts filter by manager as their PRIMARY screening action. "Show me all Vanguard funds" or "Vanguard + Fidelity" is the most common workflow. No manager filter exists.

## Deliverable

### Backend — add manager filter to catalog query

In `backend/app/domains/wealth/schemas/catalog.py`:

```python
class CatalogFilters(BaseModel):
    # ... existing filters ...
    manager_names: list[str] | None = None  # Multi-select: ["Vanguard", "Fidelity"]
```

In `catalog_sql.py` (or wherever the query is built):

```python
if filters.manager_names:
    # Manager name is on mv_unified_funds or instruments_universe
    # Find the correct column — likely "manager_name" or "adviser_name"
    stmt = stmt.where(
        manager_column.in_(filters.manager_names)
    )
```

**Investigation required:** find where the manager/adviser name lives in the data model:
- `mv_unified_funds` might have a `manager_name` column
- `instruments_universe` might have an `adviser_name` or `firm_name`
- `sec_manager_funds` has a relationship to `sec_managers` via `crd_number`

Read the actual schema before implementing. The manager name must be the one visible in the DataGrid's Name column context — whatever the user sees as "Franklin" or "Vanguard" next to the fund name.

### Backend — manager typeahead endpoint

Add a lightweight endpoint for the typeahead:

```python
@router.get("/screener/managers")
async def get_screener_managers(
    q: str = "",
    limit: int = 20,
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[str]:
    """Return distinct manager names matching the query prefix.
    Used by the Investment Manager typeahead filter.
    """
    stmt = (
        select(distinct(manager_column))
        .where(manager_column.ilike(f"{q}%"))
        .order_by(manager_column)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.fetchall()]
```

## Verification

1. `GET /screener/managers?q=Van` → returns `["Vanguard", ...]`
2. `POST /screener/catalog` with `manager_names: ["Vanguard"]` → returns only Vanguard funds
3. `POST /screener/catalog` with `manager_names: ["Vanguard", "Fidelity"]` → returns both
4. Backend tests green

---

# COMMIT 3 — feat(screener/frontend): Investment Manager multi-select typeahead filter

## Problem

Frontend needs a UI control for the manager filter added in commit 2.

## Deliverable

### In TerminalScreenerFilters.svelte

Add a new filter section between ELITE chip and UNIVERSE checkboxes:

```svelte
<section class="filter-section">
  <h3 class="filter-section-title">MANAGER</h3>
  <div class="manager-typeahead">
    <input
      type="text"
      class="manager-input"
      placeholder="Search managers..."
      bind:value={managerQuery}
      oninput={debounce(fetchManagerSuggestions, 200)}
    />
    {#if managerSuggestions.length > 0}
      <ul class="manager-suggestions" role="listbox">
        {#each managerSuggestions as name (name)}
          <li
            role="option"
            class="manager-suggestion"
            onclick={() => addManager(name)}
          >
            {name}
          </li>
        {/each}
      </ul>
    {/if}
    {#if selectedManagers.length > 0}
      <div class="manager-chips">
        {#each selectedManagers as name (name)}
          <span class="manager-chip">
            {name}
            <button
              class="manager-chip-remove"
              onclick={() => removeManager(name)}
              aria-label="Remove {name}"
            >x</button>
          </span>
        {/each}
      </div>
    {/if}
  </div>
</section>
```

### State management

```typescript
let managerQuery = $state("");
let managerSuggestions = $state<string[]>([]);
let selectedManagers = $state<string[]>([]);

async function fetchManagerSuggestions() {
  if (managerQuery.length < 2) {
    managerSuggestions = [];
    return;
  }
  const res = await fetch(`/api/v1/wealth/screener/managers?q=${encodeURIComponent(managerQuery)}&limit=10`);
  if (res.ok) managerSuggestions = await res.json();
}

function addManager(name: string) {
  if (!selectedManagers.includes(name)) {
    selectedManagers = [...selectedManagers, name];
    onFiltersChange({ ...currentFilters, manager_names: selectedManagers });
  }
  managerQuery = "";
  managerSuggestions = [];
}

function removeManager(name: string) {
  selectedManagers = selectedManagers.filter(n => n !== name);
  onFiltersChange({ ...currentFilters, manager_names: selectedManagers.length > 0 ? selectedManagers : undefined });
}
```

### URL sync

In `+page.svelte` URL state sync, add `manager` param:
- Serialize: `manager=Vanguard,Fidelity` (comma-separated)
- Deserialize: `params.get("manager")?.split(",") ?? []`
- On chip remove → URL updates → grid re-fetches

### Styling

- Input: monospace, hairline border, zero radius, `var(--terminal-text-11)`, full width of filter sidebar
- Suggestions dropdown: absolute positioned below input, black background, hairline border, `var(--terminal-z-dropdown)` z-index, max 10 items
- Chips: inline-flex, `var(--terminal-accent-cyan)` border + text, `x` button on hover, removable
- Section title: `MANAGER` in uppercase, `var(--terminal-text-10)`, `var(--terminal-fg-tertiary)`, letter-spacing caps

## Verification

1. Type "Van" in manager input → dropdown shows "Vanguard" (+ others starting with "Van")
2. Click "Vanguard" → chip appears below input, grid filters to Vanguard funds only
3. Type "Fid" → "Fidelity" appears → click → second chip, grid shows Vanguard + Fidelity
4. Click `x` on Vanguard chip → removed, grid shows only Fidelity
5. Reload page → `?manager=Fidelity` in URL → filter persists
6. Clear all chips → grid returns to full catalog

---

# COMMIT 4 — feat(screener/backend): expanded metric range filters

## Problem

Current metric filters are limited to Min AUM, Min 1Y Return, Max Expense Ratio. Institutional screening requires ranges on: Sharpe, Max Drawdown, Volatility, multi-period returns (1Y/3Y/5Y/10Y). Each as a min-max interval.

## Deliverable

### Backend — expand CatalogFilters

```python
class CatalogFilters(BaseModel):
    # ... existing filters ...

    # Metric range filters (all optional, None = no filter)
    aum_min: float | None = None           # already exists
    aum_max: float | None = None           # NEW
    sharpe_min: float | None = None        # NEW
    sharpe_max: float | None = None        # NEW
    max_drawdown_min: float | None = None  # NEW (less negative = better)
    max_drawdown_max: float | None = None  # NEW
    volatility_max: float | None = None    # NEW
    expense_ratio_max: float | None = None # already exists
    return_1y_min: float | None = None     # exists as min_return? check
    return_1y_max: float | None = None     # NEW
    return_3y_min: float | None = None     # NEW
    return_3y_max: float | None = None     # NEW
    return_5y_min: float | None = None     # NEW
    return_5y_max: float | None = None     # NEW
    return_10y_min: float | None = None    # NEW
    return_10y_max: float | None = None    # NEW
```

### Backend — query builder

For each metric filter, add a WHERE clause when the value is not None:

```python
# In the query builder (catalog_sql.py or equivalent):
if filters.sharpe_min is not None:
    stmt = stmt.where(risk_table.c.sharpe_1y >= filters.sharpe_min)
if filters.sharpe_max is not None:
    stmt = stmt.where(risk_table.c.sharpe_1y <= filters.sharpe_max)
if filters.max_drawdown_min is not None:
    stmt = stmt.where(risk_table.c.max_drawdown_1y >= filters.max_drawdown_min)
if filters.max_drawdown_max is not None:
    stmt = stmt.where(risk_table.c.max_drawdown_1y <= filters.max_drawdown_max)
# ... same pattern for all metric filters
```

The risk columns come from the `mv_fund_risk_latest` JOIN (Session 3.A commit 1 already wired this). Verify the column names match the actual MV columns.

**Note on drawdown sign convention:** `max_drawdown_1y` is typically stored as a NEGATIVE number (e.g., -0.15 for a 15% drawdown). The filter should allow users to specify "max drawdown no worse than -10%" which means `max_drawdown_1y >= -0.10`. The UI must handle the sign correctly — display as positive percentage but query as negative.

### Test coverage

Add integration tests for each new filter:
- Sharpe min/max filter
- Drawdown range filter
- Volatility max filter
- Multi-period return range filters
- Combined filters (e.g., Sharpe > 0.5 AND drawdown > -15%)

## Verification

1. `POST /screener/catalog` with `sharpe_min: 0.5` → returns only funds with Sharpe ≥ 0.5
2. Combined: `sharpe_min: 0.5, max_drawdown_min: -0.15` → intersection
3. `make test` green with new integration tests

---

# COMMIT 5 — feat(screener/frontend): expanded metric range filter UI

## Problem

Frontend needs UI controls for the expanded metric filters from commit 4.

## Deliverable

### In TerminalScreenerFilters.svelte

Expand the METRICS section to include all metric filters as dual-input range fields:

```svelte
<section class="filter-section">
  <h3 class="filter-section-title">METRICS</h3>

  <div class="metric-range">
    <label class="metric-label">AUM</label>
    <div class="metric-inputs">
      <input type="number" placeholder="min" bind:value={filters.aum_min} class="metric-input" />
      <span class="metric-sep">—</span>
      <input type="number" placeholder="max" bind:value={filters.aum_max} class="metric-input" />
    </div>
  </div>

  <div class="metric-range">
    <label class="metric-label">Sharpe (1Y)</label>
    <div class="metric-inputs">
      <input type="number" step="0.1" placeholder="min" bind:value={filters.sharpe_min} class="metric-input" />
      <span class="metric-sep">—</span>
      <input type="number" step="0.1" placeholder="max" bind:value={filters.sharpe_max} class="metric-input" />
    </div>
  </div>

  <div class="metric-range">
    <label class="metric-label">Max Drawdown (%)</label>
    <div class="metric-inputs">
      <input type="number" step="1" placeholder="min" bind:value={filters.drawdown_min_pct} class="metric-input" />
      <span class="metric-sep">—</span>
      <input type="number" step="1" placeholder="max" bind:value={filters.drawdown_max_pct} class="metric-input" />
    </div>
  </div>

  <div class="metric-range">
    <label class="metric-label">Volatility (max)</label>
    <div class="metric-inputs">
      <input type="number" step="0.01" placeholder="max" bind:value={filters.volatility_max} class="metric-input" />
    </div>
  </div>

  <div class="metric-range">
    <label class="metric-label">Expense Ratio (max %)</label>
    <div class="metric-inputs">
      <input type="number" step="0.01" placeholder="max" bind:value={filters.expense_ratio_max} class="metric-input" />
    </div>
  </div>

  <div class="metric-range">
    <label class="metric-label">1Y Return (%)</label>
    <div class="metric-inputs">
      <input type="number" step="0.1" placeholder="min" bind:value={filters.return_1y_min} class="metric-input" />
      <span class="metric-sep">—</span>
      <input type="number" step="0.1" placeholder="max" bind:value={filters.return_1y_max} class="metric-input" />
    </div>
  </div>

  <!-- Repeat for 3Y, 5Y, 10Y returns -->
</section>
```

### Scale conversion for drawdown

Drawdown is stored as negative decimals (e.g., -0.15 for 15% drawdown) but displayed to users as positive percentages. The UI must convert:
- User enters `15` (meaning "15% max drawdown") → backend receives `max_drawdown_min: -0.15`
- User enters `5` to `15` range → backend receives `max_drawdown_min: -0.15, max_drawdown_max: -0.05`

This conversion happens in the filter serialization layer (where filters are converted to the catalog request body), NOT in the input binding.

### URL sync

Add URL params for each new metric filter:
- `sharpe_min=0.5&sharpe_max=2.0`
- `dd_min=5&dd_max=15` (positive user-facing values, converted to negative on serialize)
- `vol_max=0.20`
- `ret_1y_min=5&ret_1y_max=30`
- etc.

### Styling

- Metric range row: flex, `gap: var(--terminal-space-2)`, label left-aligned 100px, inputs fill rest
- Input: monospace, `var(--terminal-text-11)`, hairline border, zero radius, width 60px per input, right-aligned text
- Separator `—`: `var(--terminal-fg-muted)`, centered
- Label: `var(--terminal-text-10)`, `var(--terminal-fg-tertiary)`, uppercase, letter-spacing

### Debounce

Metric filter inputs should debounce before triggering a fetch — user might type "0.5" as three keystrokes ("0", ".", "5"). Debounce 500ms after last input change before applying filters.

## Verification

1. Set Sharpe min to 0.5 → grid filters to funds with Sharpe ≥ 0.5 (count drops)
2. Set Max Drawdown to 15 → grid shows funds with drawdown no worse than -15%
3. Combined: Sharpe > 0.5 AND Drawdown < 15% → intersection
4. URL shows `?sharpe_min=0.5&dd_max=15`
5. Reload → same filters applied
6. Clear all → grid returns to full catalog
7. Debounce: rapid typing doesn't fire multiple requests

---

# COMMIT 6 — test(screener): completeness smoke test

## Deliverable

### Browser validation (mandatory)

Start dev server, open `/terminal-screener`, verify ALL:

1. **Infinite scroll:** scroll to row ~195 → next page loads, footer updates, scroll continues
2. **Full catalog:** scroll all the way to end → "END OF CATALOG — 9,193 instruments loaded" (or partial if filters active)
3. **Manager filter:** type "Van" → Vanguard in suggestions → select → chip appears → grid filters → URL updates
4. **Multi-manager:** add Fidelity → grid shows both → remove Vanguard chip → only Fidelity
5. **Metric Sharpe filter:** set min 0.5 → count drops → URL shows `sharpe_min=0.5`
6. **Metric Drawdown filter:** set max 15 → grid filters (with sign conversion)
7. **Filter combination:** ELITE + Manager=Vanguard + Sharpe>0.5 → narrow result set
8. **Filter reset:** click "Clear" → all filters reset, full catalog, URL clean
9. **URL persistence:** apply filters → reload page → same view
10. **Infinite scroll + filters:** apply ELITE → scroll → next page loads (within 300 total) → "END OF CATALOG" appears
11. **Keyboard:** `/` focuses the manager input (or the first input in the filter sidebar)
12. **No console errors** related to infinite scroll, manager fetch, or metric filter debounce

### Update SCREENER_SMOKE_CHECKLIST.md

Add items 24-35 covering infinite scroll, manager filter, metric ranges, combined filtering, URL persistence for new params.

## Verification

1. All 12 items pass
2. Checklist updated
3. `svelte-check` clean
4. `pnpm build` clean
5. `make test` green (with new backend integration tests from commit 4)

---

# FINAL FULL-TREE VERIFICATION

1. `svelte-check` → 0 new errors
2. `pnpm --filter netz-wealth-os build` → clean
3. `make test` → green including new metric filter tests
4. `make lint` → clean
5. Infinite scroll loads full 9,193 catalog in ~47 pages
6. Manager typeahead responsive (< 200ms per keystroke)
7. Metric filters produce correct intersection results
8. URL deep-link works for all new filter params
9. All previous features preserved (ELITE, sparklines, actions, keyboard, FocusMode, TYPE badges)

# SELF-CHECK

- [ ] Commit 1: infinite scroll loads next pages, footer updates, filter change resets, debounced
- [ ] Commit 2: backend manager filter + typeahead endpoint work
- [ ] Commit 3: frontend manager typeahead with chips, multi-select, URL sync
- [ ] Commit 4: backend metric range filters (Sharpe, drawdown, vol, returns)
- [ ] Commit 5: frontend metric range UI with debounce, drawdown sign conversion, URL sync
- [ ] Commit 6: all 12 smoke items pass
- [ ] Infinite scroll + ELITE combo works (loads ≤300, END OF CATALOG)
- [ ] Drawdown sign convention correct (user enters positive, backend receives negative)
- [ ] No keyboard shortcut conflicts (manager input captures keystrokes, global shortcuts don't fire)
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `next_cursor` field name is different in the response schema → use the actual field name, report the correction
2. Manager name column is not on `mv_unified_funds` → find the correct join path (may need `instruments_universe.manager_name` or a sec_managers JOIN)
3. Drawdown column stores values as percentages (e.g., -15.0) not decimals (-0.15) → adjust the sign conversion accordingly
4. Some metric columns have NULL for most rows (Tiingo migration pending) → filters on NULL-heavy columns return fewer results. This is expected and NOT a bug — add a note in the UI "N/A values excluded from filtered results"
5. `<svelte:boundary>` from fix sprint 1 catches errors from infinite scroll fetch failures → the fetch error state (commit 4 of fix sprint 1) should handle this gracefully, showing RETRY on network failure during page load
6. Total count in response is missing or inaccurate → use the count from the FIRST page response and update on each subsequent response. If backend doesn't return total, show "Showing {loaded} instruments" without the "of {total}" part

# NOT VALID ESCAPE HATCHES

- "Infinite scroll is complex, let me add a NEXT button instead" → NO, Bloomberg has infinite scroll, not pagination buttons. Institutional terminals scroll, they don't click "page 2"
- "I'll skip the manager typeahead and just use a text input that filters on submit" → NO, typeahead with suggestions is the institutional standard (FactSet, Bloomberg, Morningstar all do this)
- "Metric range filters can wait" → NO, quantitative screening without metric ranges is not screening at all
- "Debounce isn't necessary" → YES IT IS. Without debounce, typing "0.5" fires 3 requests

# REPORT FORMAT

1. Six commit SHAs with messages
2. Per commit: files modified, lines changed, verification
3. Commit 1 extra: how many pages load for the full 9,193 catalog, timing per page
4. Commit 2 extra: which column/table the manager name comes from (investigation finding)
5. Commit 3 extra: describe the typeahead UX flow with a specific example
6. Commit 5 extra: drawdown sign conversion example (user input → backend value)
7. Commit 6 extra: all 12 smoke items with pass/fail
8. Full-tree verification

Begin by reading this brief. Start dev server, confirm the 3 gaps, execute commits 1-6 in order.
