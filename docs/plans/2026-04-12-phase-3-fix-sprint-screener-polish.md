# Phase 3 Fix Sprint — Screener Production Polish

**Date:** 2026-04-12
**Branch:** `feat/phase-3-fix-sprint`
**Scope:** 5 atomic commits fixing the 4 UX problems visible in the screener screenshots before Phase 4 begins
**Estimated duration:** 2-3 hours concentrated Opus session
**Prerequisite reading:** this file only (self-contained)
**Depends on:** Phase 3 complete (main at `227fbe35` or later)

## Why this sprint exists

Phase 3 shipped institutional-grade DATA features (ELITE, sparklines, actions, keyboard, virtualization) on top of a Phase 1 SHELL that was never polished for production density. The result: excellent data flowing through a container that wastes viewport space, compresses the grid with a redundant third column, shows an amateur filter, and dumps raw error traces. Screenshots from 2026-04-12 confirmed all four issues in the live terminal.

This sprint fixes the container so Phase 4 Builder starts from a validated reference implementation — not from a reference that institutional analysts would dismiss as amateur.

## Project mandate (binding)

> Usaremos os recursos mais avançados disponíveis para dar ao sistema o máximo de performance e percepção visual de um produto high-end e high-tech, não importa quantas vezes tenhamos que retornar ao mesmo item para corrigi-lo ou quantas novas dependências devam ser instaladas. Sem economia ou desvios para simplificações.

> Máximo de percepção visual é válida somente quando a infraestrutura está correta, reportando dados reais e precisos, do contrário o sistema não é confiável.

Infrastructure IS correct (Phase 2 + 3 confirmed). Now the visual container must match the data quality. Bloomberg terminal has ~4px gaps, zero wasted padding, every pixel is data. That is the target density.

## READ FIRST

1. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` — the 3-column grid you are collapsing to 2 columns
2. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerQuickStats.svelte` — the component being DELETED
3. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte` — where the "Only funds with NAV" filter lives (being removed)
4. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — will gain full width after QuickStats removal
5. `frontends/wealth/src/lib/components/terminal/shell/LayoutCage.svelte` — the cage wrapper whose padding is too generous for data-dense surfaces
6. `frontends/wealth/src/lib/components/terminal/shell/TerminalShell.svelte` — the shell composition, to understand how LayoutCage wraps the screener
7. `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte` — the route that mounts TerminalScreenerShell
8. `backend/app/domains/wealth/routes/screener.py` — the catalog endpoint where `has_nav` default needs to be set
9. `backend/app/domains/wealth/queries/catalog_sql.py` (if exists) — the query builder where the WHERE clause lives

## Pre-flight

```bash
# Start dev server and open screener to see current state
pnpm --filter netz-wealth-os dev
# Open http://localhost:<port>/terminal-screener
# Confirm: 3-column layout visible, "Only funds with NAV" filter visible,
# thick borders/padding visible. This is the baseline you are fixing.
```

---

# COMMIT 1 — refactor(screener): delete QuickStats third column, screener becomes 2-column

## Problem

`TerminalScreenerShell` renders a 3-column grid: Filters (left sidebar) | DataGrid (center) | QuickStats (right panel, ~280px). The QuickStats panel shows 4-5 basic fields for the selected fund (name, AUM, asset class, domicile, currency). This information is:

1. **Redundant** — FocusMode (Phase 3.B) now provides a full-frame 95vw×95vh vitrine with 7 analytics modules triggered by row click or Enter key. The QuickStats panel adds zero information that FocusMode doesn't provide better.
2. **Harmful** — it steals ~280px from the DataGrid, compressing data columns (AUM, returns, trend) to the point of truncation. In a 1920px viewport, the DataGrid gets only ~1200px after filters (240px) + QuickStats (280px) + padding + borders. That's not enough for 8+ columns of institutional data.

## Deliverable

### Delete QuickStats

1. `git rm frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerQuickStats.svelte`
2. Grep for all imports of `TerminalScreenerQuickStats` — should be only in `TerminalScreenerShell.svelte`. Remove the import and the rendering.

### Collapse TerminalScreenerShell to 2-column

In `TerminalScreenerShell.svelte`, change the grid layout:

**Before (3-column):**
```css
grid-template-columns: 240px 1fr 280px;
```

**After (2-column):**
```css
grid-template-columns: 240px 1fr;
```

Remove:
- The QuickStats `<aside>` or `<section>` from the template
- Any `selectedAsset` state that was only used by QuickStats
- Any `onSelect` callback that was only forwarding selection to QuickStats

Keep:
- The `selectedAsset` state IF it's also used by the focusTrigger (it might set `entityLabel` from the selected asset). If so, keep the state but remove the visual panel.
- The DataGrid's row highlighting (visual feedback on which row is "current") — this is useful for keyboard navigation independent of QuickStats.

### Verify DataGrid expands

After the removal, the DataGrid should fill `1fr` of the remaining space (viewport width minus 240px filters minus padding). At 1920px, that's ~1650px+ of grid — enough for 10+ columns without truncation.

## Verification

1. Open screener in browser — grid fills the right side, no third column
2. Row click → FocusMode opens (still works, not affected by QuickStats removal)
3. Keyboard ↑↓ highlight still works
4. `grep -rn "QuickStats" frontends/wealth/src/` → zero matches
5. `svelte-check` → 0 new errors
6. `pnpm --filter netz-wealth-os build` → clean

## Commit 1 template

```
refactor(screener): delete QuickStats third column, screener becomes 2-column

The QuickStats right panel (280px) showed 4-5 basic fund fields that
FocusMode now provides better in a full-frame 95vw×95vh vitrine. The
panel was stealing ~280px from the DataGrid, compressing institutional
data columns to the point of truncation.

Deleted TerminalScreenerQuickStats.svelte (-N lines). Collapsed
TerminalScreenerShell grid from 3-column (240px | 1fr | 280px) to
2-column (240px | 1fr). DataGrid now gets the full remaining viewport
width — at 1920px that's ~1650px+ for 10+ columns.

Row click → FocusMode still works (unaffected by panel removal).
Keyboard highlight still works. selectedAsset state preserved if
needed by focusTrigger entity label.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — refactor(terminal): LayoutCage compact density for data-dense surfaces

## Problem

`LayoutCage.svelte` applies `var(--terminal-space-6)` = 24px padding on ALL sides. For narrative surfaces (DD reports, macro outlook, flash reports), this generous padding creates comfortable reading margins. For data-dense surfaces (screener grid, portfolio builder, live workbench), it wastes 48px horizontal + 48px vertical of viewport on empty black margins.

Bloomberg terminal has ~2-4px gaps between chrome and content. An institutional terminal for 9k+ fund screening needs every pixel for data.

## Deliverable

Add a `density` prop to `LayoutCage.svelte`:

```svelte
<script lang="ts">
  import type { Snippet } from "svelte";

  interface LayoutCageProps {
    children: Snippet;
    class?: string;
    density?: "standard" | "compact";
  }

  let { children, class: className = "", density = "standard" }: LayoutCageProps = $props();
</script>

<div class="lc-cage lc-cage--{density} {className}">
  {@render children()}
</div>

<style>
  .lc-cage {
    position: relative;
    background: var(--terminal-bg-void);
    overflow: hidden;
    box-sizing: border-box;
  }

  .lc-cage--standard {
    padding: var(--terminal-space-6); /* 24px — narrative surfaces */
  }

  .lc-cage--compact {
    padding: var(--terminal-space-2); /* 8px — data-dense surfaces */
  }
</style>
```

### Wire the screener to use compact

In `TerminalShell.svelte`, the cage currently wraps children with no density prop. For this sprint, the SIMPLEST approach is:

**Option A — LayoutCage gets a default that TerminalShell passes through:**

Add a `cageDensity` prop to `TerminalShell`:

```svelte
interface TerminalShellProps {
  children: Snippet;
  cageDensity?: "standard" | "compact";
}
```

Then in the shell template:

```svelte
<LayoutCage density={cageDensity}>
  {@render children()}
</LayoutCage>
```

The `(terminal)/+layout.svelte` does NOT change — it stays minimal. Instead, each route's `+page.svelte` can opt into compact density via a layout data prop or a direct wrapper.

**Option B — Screener bypasses LayoutCage entirely:**

If Option A is too invasive (changes TerminalShell contract for all consumers), the screener can mount its OWN compact cage inside the shell's standard cage:

```svelte
<!-- In TerminalScreenerShell.svelte -->
<div class="screener-compact-cage">
  <!-- filters + grid -->
</div>

<style>
  .screener-compact-cage {
    padding: var(--terminal-space-2);
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }
</style>
```

And remove the padding from the inherited LayoutCage by setting `padding: 0` on the screener's content area via a CSS override.

**Pick whichever produces the cleanest result.** Under the mandate, Option A is preferred (proper prop API) but Option B is acceptable if the shell contract change is risky for other consumers.

## Verification

1. Open screener — black margins around the grid are visibly reduced (8px instead of 24px)
2. Open a NON-screener terminal route (e.g., `/sandbox/focus-mode-smoke`) — padding is still 24px (standard density preserved for narrative surfaces)
3. Grid columns have more horizontal space — verify by checking that AUM column is no longer truncated
4. `svelte-check` → 0 new errors
5. No other routes visually regressed (spot-check 2-3 routes)

## Commit 2 template

```
refactor(terminal): LayoutCage compact density for data-dense surfaces

LayoutCage's 24px padding (var(--terminal-space-6)) was designed for
narrative surfaces (DD reports, macro outlook) but wastes 48px
horizontal + 48px vertical on data-dense surfaces like the screener
grid where every pixel is institutional data.

Adds density="compact" prop (8px padding via var(--terminal-space-2)).
Default remains "standard" (24px) so existing narrative surfaces are
unaffected. Screener opts into compact density.

Bloomberg target: ~2-4px gaps between chrome and content. 8px is a
conservative first step that recovers ~32px horizontal + 32px vertical
without going to zero (which risks elements touching the chrome).

<describe which approach was used: Option A shell prop or Option B
screener-local override>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 3 — fix(screener): remove "Only funds with NAV" filter, default catalog to NAV-populated

## Problem

`TerminalScreenerFilters.svelte` has a checkbox "Only funds with NAV" that:

1. Should not exist as a user-facing filter — a fund without NAV cannot be screened (no sparkline, no returns, no drawdown, no scoring). The system should DEFAULT to showing only NAV-populated funds.
2. Has a visible bug per screenshots (error state when toggled).
3. Projects amateurism — institutional analysts expect curated data, not raw toggles that expose data-quality gaps.

## Deliverable

### Backend — default has_nav filter

In `backend/app/domains/wealth/routes/screener.py` (or `catalog_sql.py`):

Find where the `has_nav` filter is applied conditionally. Change it to ALWAYS apply:

```python
# Before: applied only when filter is set
if filters.has_nav:
    stmt = stmt.where(some_column.isnot(None))

# After: always applied, not a user-facing filter
# Funds without NAV are not screenable — no sparkline, no returns,
# no drawdown, no scoring. Filtering them is a data-quality gate,
# not a user preference.
stmt = stmt.where(some_column.isnot(None))
```

Identify the correct column: it might be `nav_timeseries` JOIN check, or a `nav_status` field, or a `last_nav_date IS NOT NULL` predicate. Read the existing implementation to find the right column.

Remove `has_nav` from `CatalogFilters` Pydantic schema (or keep it as a no-op deprecated field that always evaluates to True).

### Frontend — delete the checkbox

In `TerminalScreenerFilters.svelte`:

1. Remove the "Only funds with NAV" checkbox element
2. Remove the `onlyNavFunds` (or similar) state field
3. Remove any URL param sync for this filter (if it was URL-synced in Session 3.B)

### Test update

Any existing test that toggles `has_nav=false` must be updated or removed — the filter no longer exists.

## Verification

1. Open screener — "Only funds with NAV" checkbox is GONE
2. All visible funds have NAV data (sparklines render for every row)
3. Backend test: `POST /screener/catalog` without any `has_nav` param → response includes only NAV-populated funds
4. Backend test: `POST /screener/catalog` WITH `has_nav=false` → either ignored (backward compat) or 400 (strict)
5. `make test` → green (updated tests)
6. `make lint` → clean

## Commit 3 template

```
fix(screener): remove "Only funds with NAV" filter, default catalog to NAV-populated

The "Only funds with NAV" checkbox was amateur-grade: a fund without
NAV is not screenable (no sparkline, no returns, no drawdown, no
scoring). The system must default to showing only NAV-populated funds.
The filter also had a visible bug per 2026-04-12 screenshots.

Backend: catalog query now unconditionally filters to NAV-populated
instruments. has_nav removed from CatalogFilters (or deprecated as
always-true). This is a data-quality gate, not a user preference.

Frontend: checkbox deleted from TerminalScreenerFilters. URL param
removed. State field removed.

Tests updated to reflect the new default (has_nav is no longer
toggleable).

Institutional analysts expect curated data — not raw toggles that
expose data-quality gaps in the pipeline.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 4 — feat(screener): error boundary with terminal-native error panel

## Problem

Screenshot 2 shows a JavaScript error trace dumped as raw red text filling the entire DataGrid area. This is unacceptable for any user-facing surface. Errors must be caught and presented as a terminal-native error panel per the master plan's "empty/loading/error patterns" spec.

## Deliverable

### Error boundary in TerminalScreenerShell

Wrap the main content area (DataGrid + any sibling panels) in a Svelte 5 `{#snippet}` error boundary or `<svelte:boundary>`:

```svelte
<svelte:boundary onerror={handleScreenerError}>
  <section class="screener-grid-area">
    <TerminalDataGrid ... />
  </section>

  {#snippet failed(error, reset)}
    <div class="screener-error-panel">
      <div class="sep-header">
        <span class="sep-code">[ ERR ]</span>
        <span class="sep-title">SCREENER DATA ERROR</span>
      </div>
      <div class="sep-body">
        <p class="sep-message">{error?.message ?? "An unexpected error occurred"}</p>
        <p class="sep-hint">The screener encountered a rendering error. This may be caused by a backend timeout, a malformed response, or a client-side exception.</p>
      </div>
      <div class="sep-actions">
        <button class="sep-retry" onclick={reset}>[ RETRY ]</button>
        <button class="sep-reload" onclick={() => location.reload()}>[ RELOAD PAGE ]</button>
      </div>
    </div>
  {/snippet}
</svelte:boundary>
```

### Styling

Terminal-native error panel:

```css
.screener-error-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--terminal-space-6);
  padding: var(--terminal-space-6);
  font-family: var(--terminal-font-mono);
  color: var(--terminal-status-error);
}

.sep-header {
  display: flex;
  align-items: baseline;
  gap: var(--terminal-space-3);
}

.sep-code {
  font-size: var(--terminal-text-20);
  font-weight: 700;
  letter-spacing: var(--terminal-tracking-caps);
}

.sep-title {
  font-size: var(--terminal-text-14);
  letter-spacing: var(--terminal-tracking-caps);
  color: var(--terminal-fg-secondary);
}

.sep-body {
  text-align: center;
  max-width: 480px;
}

.sep-message {
  font-size: var(--terminal-text-11);
  color: var(--terminal-fg-primary);
  margin: 0 0 var(--terminal-space-2);
}

.sep-hint {
  font-size: var(--terminal-text-11);
  color: var(--terminal-fg-tertiary);
  margin: 0;
}

.sep-actions {
  display: flex;
  gap: var(--terminal-space-4);
}

.sep-retry, .sep-reload {
  background: transparent;
  border: var(--terminal-border-hairline);
  border-radius: var(--terminal-radius-none);
  color: var(--terminal-fg-primary);
  font-family: var(--terminal-font-mono);
  font-size: var(--terminal-text-11);
  letter-spacing: var(--terminal-tracking-caps);
  padding: var(--terminal-space-2) var(--terminal-space-4);
  cursor: pointer;
}

.sep-retry:hover {
  border-color: var(--terminal-accent-amber);
  color: var(--terminal-accent-amber);
}

.sep-reload:hover {
  border-color: var(--terminal-status-warn);
  color: var(--terminal-status-warn);
}
```

### Also: fetch error handling

The DataGrid's data fetch (catalog endpoint call) should have a try/catch that sets an error state BEFORE the rendering error boundary fires. This provides a SPECIFIC error message ("Backend returned 500", "Request timed out after 10s", "Network error") instead of a generic rendering crash.

```typescript
let fetchError = $state<string | null>(null);

async function fetchCatalog(filters: ScreenerFilters) {
  fetchError = null;
  try {
    const res = await fetch(catalogUrl, { ... });
    if (!res.ok) {
      fetchError = `Backend error ${res.status}: ${res.statusText}`;
      return;
    }
    const data = await res.json();
    assets = data.items;
  } catch (err) {
    fetchError = err instanceof Error ? err.message : "Network error";
  }
}
```

Then render the error inline ABOVE the grid (or replacing it):

```svelte
{#if fetchError}
  <div class="screener-fetch-error">
    <span class="sfe-code">[ ERR ]</span>
    <span class="sfe-message">{fetchError}</span>
    <button class="sfe-retry" onclick={() => fetchCatalog(currentFilters)}>[ RETRY ]</button>
  </div>
{:else}
  <TerminalDataGrid ... />
{/if}
```

Two layers of error handling: fetch errors (specific) + rendering errors (boundary, generic). Belt and suspenders.

## Verification

1. Simulate a backend error (stop the dev server, try to load screener) → error panel shows "Network error" with RETRY button
2. Click RETRY → re-fetches, if server is back up, grid renders
3. Simulate a rendering error (inject a bad prop or corrupt data) → boundary catches, shows `[ ERR ] SCREENER DATA ERROR` with RETRY and RELOAD buttons
4. NO raw stack traces visible to the user in any error scenario
5. `svelte-check` → 0 new errors

## Commit 4 template

```
feat(screener): error boundary with terminal-native error panel

Screenshot from 2026-04-12 showed a JavaScript error trace dumped as
raw red text filling the DataGrid area. Unacceptable for any
institutional surface.

Two-layer error handling:
1. Fetch error state (specific): try/catch on catalog fetch, shows
   error code + message + RETRY button above the grid area
2. Rendering error boundary (generic): <svelte:boundary> wrapping the
   grid area, catches unexpected rendering crashes, shows terminal-
   native error panel with [ ERR ] header, explanation, RETRY + RELOAD

Both layers use terminal tokens (error status color, monospace, hairline
borders, zero radius). No raw stack traces visible to users in any
scenario.

Error panel follows master plan "empty/loading/error patterns" spec:
ASCII-style, monospace error codes, never web-modern spinners or
mascot illustrations.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 5 — test(screener): visual smoke test confirming fix sprint results

## Deliverable

### Browser validation (mandatory — run pnpm dev and check)

Start the dev server, open `/terminal-screener`, and verify ALL of the following:

1. **2-column layout:** Filters on left (~240px), DataGrid fills the rest. NO third column. NO QuickStats panel.
2. **Compact density:** minimal padding between shell chrome and screener content. Grid columns are NOT truncated at 1920px viewport.
3. **"Only funds with NAV" filter is GONE** from the filter sidebar. All visible funds have sparklines (confirming NAV data exists).
4. **ELITE chip still works:** toggle → grid filters to ≤300 elite funds with amber badges.
5. **Row click → FocusMode** still opens the full vitrine (not broken by QuickStats removal).
6. **Keyboard shortcuts** still work: ↑↓ navigate, Enter opens FocusMode, `u` approves, `e` toggles ELITE.
7. **URL sync** still works: filters → URL → reload → same view.
8. **Error handling:** stop the backend, try to load → terminal-native error panel appears (not red stack trace).
9. **Sparklines render** on visible rows within ~200ms of scroll stop.
10. **No console errors** related to the fix sprint changes.

### Update the smoke checklist

Update `frontends/wealth/tests/SCREENER_SMOKE_CHECKLIST.md` to reflect the new 2-column layout and removed QuickStats:

- Remove any checklist item about QuickStats
- Add item: "Grid fills viewport width (no third column, no excessive padding)"
- Add item: "Error state renders as terminal-native panel, not raw stack trace"
- Update item count

### Report visual findings

In the commit message body, describe what you see in the browser. If any item fails, fix it BEFORE committing (this is the integration gate).

## Verification

1. All 10 items above pass
2. `SCREENER_SMOKE_CHECKLIST.md` updated
3. `svelte-check` → no new errors introduced by the fix sprint
4. `pnpm --filter netz-wealth-os build` → clean

## Commit 5 template

```
test(screener): visual smoke test confirming fix sprint results

Fix sprint (5 commits) verified in browser on 2026-04-12:

1. 2-column layout: QuickStats deleted, DataGrid fills viewport
2. Compact density: <N>px padding vs prior 24px, grid columns
   no longer truncated at 1920px
3. "Only funds with NAV" filter removed, all funds have sparklines
4. ELITE chip still functional
5. FocusMode still opens from row click and Enter key
6. Keyboard shortcuts all working
7. URL sync preserved across reload
8. Error panel renders terminal-native [ ERR ] on backend down
9. Sparklines render within ~200ms
10. Zero console errors from fix sprint changes

SCREENER_SMOKE_CHECKLIST.md updated to reflect 2-column layout
and error state handling. QuickStats items removed.

Phase 3 Fix Sprint complete. Screener is now production-grade in
both data quality AND visual density. Phase 4 Builder can begin
from a validated reference implementation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

1. `svelte-check` → 0 new errors (pre-existing baseline preserved)
2. `pnpm --filter netz-wealth-os build` → clean
3. `make test` → green (backend has_nav default change + test updates)
4. `make lint` → clean
5. Browser visual verification → all 10 smoke items pass
6. `grep -rn "QuickStats" frontends/wealth/src/` → zero matches
7. `grep -rn "Only funds with NAV\|has_nav\|onlyNavFunds" frontends/wealth/src/lib/components/screener/` → zero matches (UI side)

# SELF-CHECK

- [ ] Commit 1: QuickStats deleted, grid is 2-column, row click → FocusMode still works
- [ ] Commit 2: compact density applied to screener, standard preserved for other routes, no visual regression on sandbox
- [ ] Commit 3: "Only funds with NAV" filter gone from UI, backend defaults to NAV-populated, tests updated
- [ ] Commit 4: error boundary catches rendering errors, fetch errors show specific messages, zero raw stack traces
- [ ] Commit 5: all 10 visual smoke items pass in browser, checklist updated
- [ ] No files outside screener + LayoutCage + backend screener route touched
- [ ] Terminal tokens only (no hex)
- [ ] Formatters only (no .toFixed)
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `TerminalScreenerQuickStats` is imported by other files besides the shell → investigate, update all importers, report
2. `has_nav` filter is used by OTHER endpoints beyond the screener catalog → keep the field in the schema but default to True; only remove the UI toggle
3. `<svelte:boundary>` Svelte 5 API has different syntax than I described → read Svelte 5 docs via MCP (`npx @sveltejs/mcp get-documentation`), use the correct API
4. Compact density on LayoutCage causes other (terminal)/ routes to break visually → use Option B (screener-local override) instead of Option A (LayoutCage prop)
5. The error visible in screenshot 2 is a backend error (500) not a rendering error → the fetch error handler (try/catch on catalog fetch) catches this; the `<svelte:boundary>` is defense-in-depth for rendering crashes

# NOT VALID ESCAPE HATCHES

- "QuickStats might be useful later" → NO, FocusMode replaced it. Delete.
- "24px padding is fine, users can zoom out" → NO, institutional analysts don't zoom. Every pixel is data.
- "I'll just hide the NAV filter instead of removing it" → NO, hidden state is tech debt. Delete.
- "Error boundary is too much work for one commit" → NO, 40 lines of Svelte + styling. Ship it.

# REPORT FORMAT

1. Five commit SHAs with messages
2. Per commit: files created/modified/deleted, lines added/removed, verification
3. Commit 2 extra: which approach (A or B) was used for compact density, before/after padding measurement
4. Commit 3 extra: backend query diff showing the has_nav default
5. Commit 4 extra: description of error panel appearance when backend is down
6. Commit 5 extra: all 10 visual smoke items with pass/fail status
7. Before/after screenshots if possible (terminal screener at 1920px viewport before fix sprint vs after)
8. Phase 3 Fix Sprint COMPLETE summary

Begin by reading this brief. Start dev server to see current state. Execute commits 1-5 in order. Commit 5 is the visual integration gate — if any smoke item fails, fix before committing.
