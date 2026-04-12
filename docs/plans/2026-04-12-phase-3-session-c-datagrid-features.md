# Phase 3 Session C — DataGrid Features

**Date:** 2026-04-12
**Branch:** `feat/phase-3-session-c`
**Scope:** 5 atomic commits polishing the DataGrid to institutional-grade
**Prerequisite reading:** `docs/plans/2026-04-12-phase-3-overview.md`
**Depends on:** Sessions 3.A + 3.B merged (ELITE filter works, FocusMode rewired, URL sync active, FundWarRoomModal deleted)

## Mission

Polish `TerminalDataGrid` from a basic HTML table to an institutional-grade data surface: virtualized rendering for 9k+ rows, inline sparkline charts on visible rows, one-click universe actions, full keyboard navigation, and an end-to-end integration smoke test. After this session, Phase 3 is COMPLETE and the Screener is the first fully operational terminal surface.

Five atomic commits:

1. `feat(screener): DataGrid virtualization for 9k+ rows`
2. `feat(screener): inline sparklines column via batch endpoint`
3. `feat(screener): action column — [→ UNIVERSE] for liquids, [+ DD] for privates`
4. `feat(screener): keyboard shortcuts (/, ↑↓, Enter, u, d, e)`
5. `test(screener): end-to-end integration smoke test`

## READ FIRST

1. `docs/plans/2026-04-12-phase-3-overview.md`
2. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — the component being enhanced across all 5 commits
3. `frontends/wealth/src/lib/components/terminal/charts/TerminalChart.svelte` — the chart primitive for sparklines (Phase 1 Part A)
4. `packages/investintell-ui/src/lib/charts/choreo.ts` — motion grammar for sparkline reveal
5. Session 3.A's sparkline endpoint documentation — `POST /screener/sparklines` request/response shape
6. Session 3.B's `focusTrigger` action — how row click triggers FocusMode (must not conflict with keyboard Enter)
7. Session 3.B's URL state — filter/sort/cursor params that this session's keyboard shortcuts must interact with correctly
8. `backend/app/domains/wealth/routes/universe.py` — for action column's `POST /universe/approve` fast-track
9. `backend/app/domains/wealth/routes/dd_reports.py` — for action column's DD queue endpoint
10. `CLAUDE.md` Critical Rules — formatter discipline, no localStorage, SSE patterns

## Pre-flight

```bash
# Verify Sessions 3.A + 3.B merged
grep -rn "FundWarRoomModal" frontends/wealth/src/  # should be ZERO matches
curl -s http://localhost:8000/screener/sparklines -X POST -H "Content-Type: application/json" -d '{"instrument_ids":["<any-valid-uuid>"]}' -H "X-DEV-ACTOR: test" | jq 'keys'  # should return instrument IDs
```

---

# COMMIT 1 — feat(screener): DataGrid virtualization for 9k+ rows

## Problem

Audit §B.2 confirmed DataGrid is a standard HTML `<table>` with `{#each}` rendering ALL rows. At 9k+ rows, DOM node count (~50k+ nodes for a 6-column grid) destroys rendering performance — initial paint > 3 seconds, scroll jank, high memory.

## Deliverable

Implement windowed rendering in `TerminalDataGrid.svelte`:

### Approach: IntersectionObserver-based virtual scroll

Replace the `{#each assets as asset}` block with a windowed rendering pattern:

1. Render a container `<div class="grid-scroll">` with `overflow-y: auto`
2. Inside, a spacer `<div>` with `height: totalRows * ROW_HEIGHT` to maintain scroll position and scrollbar size
3. Only render the visible rows (viewport height / ROW_HEIGHT ± overscan buffer of 5 rows)
4. On scroll, recalculate the visible window via `scrollTop / ROW_HEIGHT`
5. Position visible rows via `transform: translateY(startIndex * ROW_HEIGHT)` on the row container

**ROW_HEIGHT:** fixed at 32px (terminal monospace line height). All rows same height — no dynamic measurement needed.

**Alternative:** if a package like `@tanstack/svelte-virtual` is already installed AND confirmed compatible with Svelte 5 (the audit from prior phases noted Svelte 5 breakage risk), use it. If not installed or not compatible, implement the IntersectionObserver/scroll-based approach described above. Under the mandate, installing a new dep is authorized if it's production-grade. Do NOT use `@tanstack/svelte-table` (confirmed Svelte 5 breakage per memory).

### Table vs div-grid decision

Current DataGrid uses `<table>`. Virtualization with `<table>` is awkward because `<tbody>` can't have a spacer div. Two options:

- (a) Switch to CSS Grid `<div>` layout with `role="grid"` ARIA — cleaner for virtualization, full control over positioning
- (b) Keep `<table>` but use a scrollable `<div>` wrapper with `table-layout: fixed` and manual row rendering

Prefer (a) under the mandate — CSS Grid with proper ARIA roles is the institutional-grade approach. Ensures accessibility compliance and layout control.

## Verification

1. Load screener with 9k+ rows in dev DB → initial paint < 500ms
2. Scroll rapidly → no jank, smooth rendering, visible rows update
3. DOM inspector → only ~50 row elements in DOM at any time (not 9000+)
4. Sort change → visible window resets to top
5. Filter change → visible window resets to top
6. `svelte-check` → 0 errors
7. Keyboard `↑↓` from commit 4 will need to interact with the virtual scroll — the scroll position must follow the keyboard-highlighted row. Note this in the commit message for commit 4 integration.

---

# COMMIT 2 — feat(screener): inline sparklines column via batch endpoint

## Problem

Screener grid should show a tiny NAV trend chart per row to give institutional analysts an instant visual signal of momentum. Master plan specified sparklines via the `TerminalChart` pattern with Canvas renderer.

## Deliverable

Add a sparkline column to `TerminalDataGrid`:

1. When the visible window changes (scroll, filter), collect the `instrument_id` values of the ~40 visible rows
2. Call `POST /screener/sparklines` (Session 3.A commit 3) with those IDs
3. Render a 48×16px `<canvas>` sparkline per row using a minimal ECharts spark instance OR a pure Canvas 2D path (no full ECharts for 40 tiny charts — too heavy)

### Recommended approach: Pure Canvas 2D path (no ECharts per row)

For 40 tiny sparklines at 48×16px, full ECharts instances are wasteful. Instead:

1. Create a reusable `drawSparkline(canvas: HTMLCanvasElement, values: number[], color: string)` function
2. The function draws a simple polyline on the canvas 2D context — no axes, no labels, no tooltip
3. Color: positive delta (last > first) → `var(--terminal-status-success)`, negative → `var(--terminal-status-error)`, flat → `var(--terminal-fg-muted)`
4. Line width: 1px, smooth: false (crisp pixel-aligned lines for terminal aesthetic)

This is 20 lines of Canvas 2D code, runs in <1ms per sparkline, and doesn't conflict with the ECharts import restriction (no `echarts` import at all — pure `<canvas>` API).

### Data flow

```
visible rows change
  → collect instrument_ids
  → debounce 150ms (avoid rapid-fire on fast scroll)
  → POST /screener/sparklines
  → response dict keyed by instrument_id
  → for each visible row, if sparkline data exists, call drawSparkline
  → if data doesn't exist (instrument has no NAV history), show "—" glyph
```

Cache sparkline data in a `Map<string, SparklinePoint[]>` in-memory (not localStorage per mandate). Clear on filter change. Persist across scroll (already-fetched sparklines don't re-fetch on scroll-back).

## Verification

1. Scroll through grid → sparklines appear for visible rows within ~200ms of scroll stop
2. Sparklines are green (positive) or red (negative) matching the fund's actual trend
3. No ECharts import in the DataGrid file (grep for `echarts` → 0)
4. DOM inspector → each sparkline is a `<canvas>` element, not an ECharts instance
5. Performance: 40 sparklines render in < 50ms total (Canvas 2D is fast)
6. Funds with no NAV history show "—" (em-dash glyph)

---

# COMMIT 3 — feat(screener): action column — [→ UNIVERSE] for liquids, [+ DD] for privates

## Problem

Master plan defines the fast-path flow: liquid funds go directly from Screener to Approved Universe via one click. Private funds and BDCs queue DD. The screener grid needs an inline action column that renders the appropriate button per row.

## Deliverable

Add a final column to `TerminalDataGrid` (or an action overlay per row):

### Per-row logic:

```typescript
function getRowAction(asset: CatalogRow): RowAction {
  if (asset.in_universe) {
    return { type: "in_universe", label: "IN UNIVERSE", disabled: true };
  }
  if (asset.approval_status === "pending") {
    return { type: "pending", label: "PENDING", disabled: true };
  }
  const liquidUniverses = ["registered_us", "etf", "ucits_eu", "money_market"];
  if (liquidUniverses.includes(asset.universe)) {
    return { type: "approve", label: "→ UNIVERSE", action: () => approveFund(asset.id) };
  }
  return { type: "queue_dd", label: "+ DD", action: () => queueDD(asset.id) };
}
```

### Backend calls:

```typescript
async function approveFund(fundId: string) {
  const res = await fetch("/api/v1/wealth/universe/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ fund_ids: [fundId], source: "screener_fast_path" }),
  });
  if (res.status === 409) {
    // DD required — shouldn't happen for liquids but handle defensively
    showToast("DD report required for this fund type", "warn");
    return;
  }
  if (res.ok) {
    showToast("Fund approved to universe", "success");
    // Update the row's in_universe status locally without re-fetching
    updateRowInUniverse(fundId, true);
  }
}

async function queueDD(fundId: string) {
  const res = await fetch("/api/v1/wealth/dd-reports/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify({ fund_id: fundId }),
  });
  if (res.ok) {
    showToast("DD report queued", "info");
    updateRowApprovalStatus(fundId, "pending");
  }
}
```

### Visual:

- `→ UNIVERSE` button: amber border, monospace, uppercase, hover state
- `+ DD` button: cyan border (secondary action color)
- `IN UNIVERSE` label: success color, non-interactive
- `PENDING` label: muted color, non-interactive

### Guard:

The `focusTrigger` action on the row must NOT fire when clicking an action button. Commit 1 of Session B already handles this via the `target.closest("button, a, input")` guard in `focusTrigger`. Verify this works.

## Verification

1. Click `→ UNIVERSE` on a liquid fund → toast "approved", row badge changes to `IN UNIVERSE`
2. Click `+ DD` on a private fund → toast "queued", row badge changes to `PENDING`
3. Action buttons do NOT trigger FocusMode (guard works)
4. Already-approved funds show `IN UNIVERSE` (non-interactive)
5. Button styles use terminal tokens (no hex)

---

# COMMIT 4 — feat(screener): keyboard shortcuts (/, ↑↓, Enter, u, d, e)

## Problem

Audit §E.1 confirmed ZERO keyboard handlers in screener components. Institutional terminals are keyboard-first. Must wire the full shortcut set per master plan Appendix B.

## Deliverable

Add a keyboard handler `$effect` in `TerminalDataGrid.svelte` (or a shared keyboard manager):

| Key | Action |
|---|---|
| `/` | Focus the search/filter input |
| `↑` | Move highlight to previous row (wraps at top) |
| `↓` | Move highlight to next row (wraps at bottom) |
| `Enter` | Open FocusMode on highlighted row (triggers `focusTrigger` programmatically) |
| `u` | Execute `→ UNIVERSE` action on highlighted row (if available) |
| `d` | Execute `+ DD` action on highlighted row (if available) |
| `e` | Toggle ELITE filter chip |

### Integration with virtualization (commit 1):

When `↑↓` moves the highlight outside the visible window, the virtual scroll must scroll to bring the highlighted row into view. Pattern: after updating `highlightedIndex`, compute `newScrollTop = highlightedIndex * ROW_HEIGHT` and set `scrollContainer.scrollTop = newScrollTop` if the row is outside the viewport.

### Conflict avoidance with TerminalShell global handler:

TerminalShell owns Cmd+K, `[`/`]`, and `g`-prefix. The screener's `↑↓/Enter/u/d/e` are LOCAL to the grid and should only fire when the grid has focus. Use a focus guard:

```typescript
function isGridFocused(): boolean {
  return gridContainer?.contains(document.activeElement) ?? false;
}
```

The keyboard `$effect` checks `isGridFocused()` before processing any keystroke. This prevents screener shortcuts from firing when the user is typing in the CommandPalette or editing something else.

## Verification

1. Focus the grid → `↑↓` moves highlight, visual indicator on highlighted row
2. `Enter` on highlighted row → FocusMode opens
3. `u` on highlighted liquid fund → approve action fires
4. `d` on highlighted private fund → DD action fires
5. `e` → ELITE chip toggles
6. `/` → filter input focuses
7. While CommandPalette is open → screener shortcuts do NOT fire
8. While in FocusMode → screener shortcuts do NOT fire (FocusMode has its own keyboard trap)

---

# COMMIT 5 — test(screener): end-to-end integration smoke test

## Problem

Zero frontend tests for the screener. Phase 3 is the first real consumer — needs at minimum an end-to-end validation that the screener loads, filters, navigates, and triggers FocusMode.

## Deliverable

### Approach: Browser-based smoke test via pnpm dev + script

Create `frontends/wealth/tests/screener-smoke.ts` (or `.mjs`) that:

1. Starts `pnpm --filter netz-wealth-os dev` in background
2. Waits for the dev server to be ready (poll `/health` or similar)
3. Opens `http://localhost:<port>/terminal-screener` via `fetch` (not a real browser — just checks the HTML response is valid)
4. Verifies: response status 200, HTML contains expected markers (`TerminalDataGrid`, `ELITE`, `SCREENER` tab, `LIVE` tab)
5. Kills the dev server

**Alternative:** if Playwright is set up (it's in root `package.json` per the audit), use it for a real browser test:

```typescript
test("screener loads and renders grid", async ({ page }) => {
  await page.goto("/terminal-screener");
  await expect(page.locator(".tg-grid")).toBeVisible();
  await expect(page.locator(".filter-chip:has-text('ELITE')")).toBeVisible();
  // Toggle ELITE
  await page.click(".filter-chip:has-text('ELITE')");
  // Verify grid updates (row count changes)
  const rows = await page.locator("[role='row']").count();
  expect(rows).toBeLessThanOrEqual(300);
});
```

Under the mandate (institutional-grade), Playwright is preferred. If setup is too complex for this session, defer Playwright and ship the simpler fetch-based smoke. Report which was chosen.

### Also add: manual smoke test protocol

Add a checklist file at `frontends/wealth/tests/SCREENER_SMOKE_CHECKLIST.md` (similar to the FocusMode sandbox checklist):

```markdown
# Screener Smoke Test Checklist

Open http://localhost:<port>/terminal-screener after `pnpm dev`.

1. Grid renders with 9k+ row indicators (scrollbar size, row count in footer)
2. Scroll down rapidly — no jank, sparklines load on visible rows
3. Toggle ELITE chip — grid filters to ≤ 300 rows, amber badges visible
4. Clear ELITE — grid returns to full catalog
5. Click a row — FocusMode opens with fund analytics vitrine
6. ESC closes FocusMode, focus returns to grid
7. Press ↑↓ — highlight moves between rows
8. Press Enter — FocusMode opens on highlighted row
9. Highlight a liquid fund, press `u` — toast "approved to universe", badge changes
10. Highlight a private fund, press `d` — toast "DD queued", badge changes
11. Press `/` — filter input focuses
12. Press `e` — ELITE chip toggles
13. Apply filters → URL updates → reload page → same filters applied
14. Navigate to page 2 via scroll → cursor appears in URL
15. All text is monospace, all borders are 1px hairline, zero radius
16. DOM inspector shows --terminal-* custom properties, no hex literals
```

## Verification

1. Smoke test script (fetch or Playwright) runs green
2. Manual checklist present for human validation
3. `make test` or `pnpm test` includes the smoke test if Playwright
4. Checklist file committed in the same commit

---

# FINAL FULL-TREE VERIFICATION

1. `svelte-check` → 0 errors, baseline warnings preserved
2. `eslint` → terminal namespace clean
3. `pnpm --filter netz-wealth-os build` → clean
4. `make loadtest` → screener p95 still < 300ms (virtualization doesn't affect backend)
5. DataGrid renders 9k+ rows without jank
6. Sparklines display on visible rows
7. Action column functional (approve + DD queue)
8. Full keyboard navigation works
9. URL state persists across reload
10. FocusMode opens from both click and Enter key
11. ELITE filter works end-to-end (chip → backend → grid → badge)

# SELF-CHECK

- [ ] Commit 1: only ~50 row elements in DOM when grid has 9k+ rows
- [ ] Commit 2: sparklines render in < 50ms per visible batch, no ECharts import
- [ ] Commit 3: action buttons don't trigger FocusMode, fast-track works for liquids
- [ ] Commit 4: all 7 shortcuts work, no conflict with global TerminalShell shortcuts
- [ ] Commit 5: smoke test green, checklist file committed
- [ ] No backend files touched (this is pure frontend)
- [ ] Terminal tokens only (no hex), formatters only (no .toFixed)
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `@tanstack/svelte-virtual` is compatible with Svelte 5 and already installed → use it instead of custom IntersectionObserver approach. More battle-tested.
2. Playwright setup requires Docker or a different test runner config → ship fetch-based smoke test and document Playwright as follow-up
3. Pure Canvas sparkline rendering has anti-aliasing issues at 48×16 → bump to 64×20 or use SVG path instead (SVG at this size is equally fast)
4. `POST /screener/sparklines` endpoint returns different shape than specified → adapt the call, report the delta
5. Keyboard shortcut `u` (universe approve) fires on a fund that's already `IN UNIVERSE` → guard with `if (!asset.in_universe)` before calling the API
6. Virtual scroll interacts badly with the `use:focusTrigger` action on rows (action doesn't re-attach after rows are recycled) → move the click handler to a delegated event on the grid container instead of per-row attachment

# NOT VALID ESCAPE HATCHES

- "Virtualization is too complex, I'll skip it" → NO, 9k+ rows without virtualization is broken
- "I'll use ECharts for sparklines" → NO, 40 ECharts instances per scroll event is wasteful. Pure Canvas/SVG.
- "I'll skip the keyboard shortcuts" → NO, institutional terminals are keyboard-first
- "The smoke test is enough without the manual checklist" → NO, automated smoke catches regressions, manual checklist catches visual/UX issues. Both.

# REPORT FORMAT

1. Five commit SHAs with messages
2. Per commit: files modified, lines changed, verification output
3. Commit 1 extra: DOM node count proof (before vs after virtualization, from DevTools)
4. Commit 2 extra: sparkline rendering time measurement
5. Commit 4 extra: keyboard shortcut demo (describe the interaction flow)
6. Commit 5 extra: smoke test output + checklist file path
7. Full-tree verification output
8. Phase 3 COMPLETE summary

After this session, Phase 3 Screener Fast Path is done. The terminal has its first fully operational production surface. Phase 4 Builder is next.

Begin by reading overview + this brief + audit. Verify Sessions 3.A + 3.B merged. Start commit 1.
