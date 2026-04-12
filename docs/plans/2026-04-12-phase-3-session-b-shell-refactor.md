# Phase 3 Session B — Screener Shell Refactor

**Date:** 2026-04-12
**Branch:** `feat/phase-3-session-b`
**Scope:** 5 atomic commits rewiring screener frontend to consume Part C primitives + Phase 3.A backend
**Prerequisite reading:** `docs/plans/2026-04-12-phase-3-overview.md`
**Depends on:** Session 3.A merged to main (catalog returns elite_flag, in_universe, sparklines, keyset pagination)

## Mission

Rewire the screener frontend from its Phase 1 "skeleton" state to a proper Part C shell consumer. After this session: row clicks open FocusMode (not legacy War Room modal), ELITE filter chip works against real data, filters sync to URL for deep-linking, and the legacy `FundWarRoomModal.svelte` is deleted.

Five atomic commits:

1. `feat(terminal): registerFocusTrigger use:action directive`
2. `refactor(screener): rewire row click to openFocus + FundFocusMode`
3. `feat(screener): ELITE filter chip + amber star badge on rows`
4. `refactor(screener): URL state sync for all filters`
5. `chore(screener): delete FundWarRoomModal.svelte (cutover complete)`

## READ FIRST

1. `docs/plans/2026-04-12-phase-3-overview.md`
2. `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte` — current route (legacy `activeFundId` + `onOpenWarRoom` + `FundWarRoomModal`)
3. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` — 3-column grid, props contract
4. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — row click handler, column rendering
5. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte` — filter categories, local state model
6. `frontends/wealth/src/lib/components/terminal/focus-mode/FocusMode.svelte` — props contract (`entityKind`, `entityId`, `entityLabel`, `reactor`, `rail`, `actions`, `onClose`)
7. `frontends/wealth/src/lib/components/terminal/focus-mode/fund/FundFocusMode.svelte` — props contract (`fundId`, `fundLabel`, `onClose`)
8. `frontends/wealth/src/lib/components/terminal/FundWarRoomModal.svelte` — the file being deleted in commit 5
9. Session 3.A's catalog response schema — confirm `elite_flag`, `in_universe`, `approval_status` fields are present
10. `frontends/wealth/eslint.config.js` — terminal guardrails still active

## Pre-flight

```bash
# Verify Session 3.A merged
curl -s http://localhost:8000/screener/catalog -H "X-DEV-ACTOR: test" | jq '.items[0] | keys' | grep elite_flag
# Should show "elite_flag" in the key list
```

If `elite_flag` is not in the response, Session 3.A didn't merge — STOP.

---

# COMMIT 1 — feat(terminal): registerFocusTrigger use:action directive

## Problem

Phase 3 audit confirmed `registerFocusTrigger` is MISSING from the codebase. My master plan proposed it as a `{@attach}` helper but Part C didn't ship it. The screener needs it (and Phase 4 Builder, Phase 5 Live Workbench will too) to trigger FocusMode from any row element without prop-drilling callbacks.

## Deliverable

New file: `frontends/wealth/src/lib/components/terminal/focus-mode/focus-trigger.ts`

```typescript
import type { FocusModeEntityKind } from "./FocusMode.svelte";

export interface FocusTriggerOptions {
  entityKind: FocusModeEntityKind;
  entityId: string;
  entityLabel?: string;
}

/**
 * Svelte use:action that makes any element a FocusMode trigger.
 *
 * Usage:
 *   <tr use:focusTrigger={{ entityKind: "fund", entityId: row.id, entityLabel: row.name }}>
 *
 * On click, dispatches a CustomEvent "focus-trigger" on the element,
 * which the page-level FocusMode listener picks up. This decouples
 * the grid row from knowing about FocusMode internals.
 */
export function focusTrigger(
  node: HTMLElement,
  options: FocusTriggerOptions,
): { update(opts: FocusTriggerOptions): void; destroy(): void } {
  let currentOptions = options;

  function handleClick(event: MouseEvent) {
    // Don't trigger if the click was on an interactive element inside the row
    // (button, link, input) — those have their own handlers
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select, textarea")) return;

    node.dispatchEvent(
      new CustomEvent("focus-trigger", {
        bubbles: true,
        detail: { ...currentOptions },
      }),
    );
  }

  node.addEventListener("click", handleClick);
  node.style.cursor = "pointer";

  return {
    update(opts: FocusTriggerOptions) {
      currentOptions = opts;
    },
    destroy() {
      node.removeEventListener("click", handleClick);
      node.style.cursor = "";
    },
  };
}
```

**Page-level listener pattern** (used in commit 2):

```svelte
<script>
  function handleFocusTrigger(event: CustomEvent<FocusTriggerOptions>) {
    focusEntity = event.detail;
    showFocusMode = true;
  }
</script>

<div on:focus-trigger={handleFocusTrigger}>
  <TerminalScreenerShell ... />
</div>

{#if showFocusMode && focusEntity}
  <FundFocusMode
    fundId={focusEntity.entityId}
    fundLabel={focusEntity.entityLabel ?? ""}
    onClose={() => { showFocusMode = false; }}
  />
{/if}
```

This decouples: DataGrid row has `use:focusTrigger`, page listens for the bubbled event, page mounts FundFocusMode. Grid doesn't import FocusMode.

**Export from barrel:** add `focusTrigger` to the terminal component barrel if one exists, or import directly from the path.

## Verification

1. `svelte-check` on the new file → 0 errors
2. `eslint` on the new file → 0 errors
3. Grep for banned patterns → 0 matches
4. Type-check: `FocusTriggerOptions` references `FocusModeEntityKind` without circular dependency

---

# COMMIT 2 — refactor(screener): rewire row click to openFocus + FundFocusMode

## Problem

Audit confirmed screener route still uses legacy `activeFundId` state + `onOpenWarRoom` callback to mount `FundWarRoomModal.svelte` directly. Must replace with the new `focusTrigger` action + page-level `FundFocusMode` mount.

## Deliverable

### In `+page.svelte`:

1. Remove `import FundWarRoomModal` and `let activeFundId = $state<string | null>(null)`
2. Add `import FundFocusMode` from Part C
3. Add `import { focusTrigger, type FocusTriggerOptions }` from commit 1
4. Add focus state:
   ```svelte
   let focusEntity = $state<FocusTriggerOptions | null>(null);
   ```
5. Add event handler for `focus-trigger` custom event
6. Mount `FundFocusMode` conditionally when `focusEntity !== null`
7. Remove `onOpenWarRoom` prop pass-through to `TerminalScreenerShell`

### In `TerminalScreenerShell.svelte`:

1. Remove `onOpenWarRoom` prop from interface
2. Pass through without modifying

### In `TerminalDataGrid.svelte`:

1. Remove `onOpenWarRoom` prop and `onSelect` prop if only used for War Room
2. Add `use:focusTrigger` on each `<tr>`:
   ```svelte
   <tr use:focusTrigger={{ entityKind: "fund", entityId: asset.id, entityLabel: asset.name }}>
   ```
3. Keep row selection state for QuickStats (if it's driven by row click too, separate the concerns: focusTrigger fires FocusMode on the MAIN click area, QuickStats selection stays as a lightweight local state)

## Verification

1. Click a row → `FundFocusMode` opens with correct fund data (via EntityAnalyticsVitrine)
2. Click a button/link INSIDE the row → FocusMode does NOT open (interactive element guard in focusTrigger)
3. ESC closes FocusMode, focus returns to the row
4. `FundWarRoomModal` is NOT imported anywhere in the screener route
5. `svelte-check` → 0 errors

---

# COMMIT 3 — feat(screener): ELITE filter chip + amber star badge on rows

## Deliverable

### In `TerminalScreenerFilters.svelte`:

Add an ELITE chip as the FIRST item in the filter ribbon:

```svelte
<button
  class="filter-chip"
  class:filter-chip--active={filters.eliteOnly}
  onclick={() => { filters.eliteOnly = !filters.eliteOnly; applyFilters(); }}
>
  ELITE
</button>
```

When active, the chip has `var(--terminal-accent-amber)` border + text. Toggling it sends `elite_only: true` to the catalog endpoint (which Session 3.A wired to filter `WHERE elite_flag = true`).

### In `TerminalDataGrid.svelte`:

For rows where `asset.elite_flag === true`, render an amber star badge:

```svelte
{#if asset.elite_flag}
  <span class="elite-badge" title="Elite — top {asset.elite_target_count_per_strategy} in {asset.strategy_label}">
    ELITE
  </span>
{/if}
```

Style: amber text, monospace, uppercase, `var(--terminal-accent-amber)`, no border-radius, letter-spacing caps.

### Also display `in_universe` marker:

For rows where `asset.in_universe === true`, show a small `IN UNIVERSE` pill:

```svelte
{#if asset.in_universe}
  <span class="universe-badge">IN UNIVERSE</span>
{/if}
```

Style: `var(--terminal-status-success)` text, subtle, not competing with ELITE badge.

## Verification

1. Toggle ELITE chip → grid filters to ELITE-only funds, count ≤ 300
2. ELITE badge visible on qualifying rows even when not filtered
3. `IN UNIVERSE` badge visible on approved instruments
4. Chips are keyboard-accessible (Tab + Enter toggles)

---

# COMMIT 4 — refactor(screener): URL state sync for all filters

## Problem

Audit §E.2 confirmed filters are held in local state in the Shell. URL does not reflect filter state. Reloading the page loses all filters. Not deep-linkable, not shareable.

## Deliverable

Refactor filter state from local `$state` to URL searchParams:

1. Read initial filter state from `$page.url.searchParams` on mount:
   ```typescript
   const params = page.url.searchParams;
   const initialFilters = {
     q: params.get("q") ?? "",
     universe: params.getAll("universe"),
     strategy: params.getAll("strategy"),
     geography: params.getAll("geography"),
     eliteOnly: params.get("elite") === "1",
     sortBy: params.get("sort") ?? "composite_score",
     sortDir: (params.get("dir") ?? "desc") as "asc" | "desc",
     cursor: params.get("cursor") ?? undefined,
   };
   ```

2. On filter change, update URL via `goto()` with new params:
   ```typescript
   async function applyFilters(newFilters: ScreenerFilters) {
     const url = new URL(page.url);
     url.searchParams.set("q", newFilters.q);
     // ... set all params
     if (newFilters.eliteOnly) url.searchParams.set("elite", "1");
     else url.searchParams.delete("elite");
     // Clear cursor on filter change (new search starts from page 1)
     url.searchParams.delete("cursor");
     const target = resolve(url.pathname) + "?" + url.searchParams.toString();
     await goto(target, { replaceState: true, noScroll: true, keepFocus: true });
   }
   ```

3. Use `$derived` to react to `$page.url.searchParams` changes:
   ```typescript
   const currentFilters = $derived.by(() => parseFiltersFromURL(page.url.searchParams));
   ```

4. Data fetching triggers on `currentFilters` change via `$effect`:
   ```typescript
   $effect(() => {
     fetchCatalog(currentFilters);
   });
   ```

**Critical:** use `resolve()` for the `goto` target path per Phase 1 learning (svelte/no-navigation-without-resolve rule).

**Critical:** clear the `cursor` param whenever filters change — keyset cursor is invalid after filter change. Only preserve cursor on "next page" navigation.

## Verification

1. Set filters → URL updates → reload page → same filters applied
2. Copy URL → paste in new tab → same view
3. Change a filter → cursor resets to page 1
4. Keyset "next page" → cursor appears in URL
5. Browser back button → previous filter state restored
6. `svelte-check` → 0 errors

---

# COMMIT 5 — chore(screener): delete FundWarRoomModal.svelte (cutover complete)

## Problem

After commits 1-2, no consumer imports `FundWarRoomModal.svelte`. It's dead code — the legacy Phase 1 War Room modal has been replaced by `FocusMode` + `FundFocusMode` from Part C.

## Deliverable

1. `git rm frontends/wealth/src/lib/components/terminal/FundWarRoomModal.svelte`
2. Grep for any remaining imports of `FundWarRoomModal` — there should be zero after commit 2. If any remain, update them first.
3. Verify `FocusMode.svelte` and `FundFocusMode.svelte` are untouched by this commit.

## Verification

1. `grep -rn "FundWarRoomModal" frontends/wealth/src/` → zero matches
2. `svelte-check` → 0 errors
3. `pnpm --filter netz-wealth-os build` → clean (no broken imports)
4. Sandbox smoke test at `/sandbox/focus-mode-smoke` still works (it uses `FocusMode`, not `FundWarRoomModal`)

---

# FINAL FULL-TREE VERIFICATION

1. `svelte-check` → 0 errors, 12 pre-existing warnings baseline
2. `eslint` terminal namespace → 0 errors
3. `pnpm --filter netz-wealth-os build` → clean
4. Sandbox smoke test → FocusMode still works
5. Screener route → ELITE filter works, row click opens FundFocusMode, URL syncs, IN UNIVERSE badge displays
6. `FundWarRoomModal.svelte` is GONE from the filesystem

# SELF-CHECK

- [ ] Commit 1: `focusTrigger` action created, typed, exported
- [ ] Commit 2: row click → FundFocusMode, no FundWarRoomModal import anywhere in screener
- [ ] Commit 3: ELITE chip toggles filter, amber badge on elite rows, IN UNIVERSE badge
- [ ] Commit 4: all filters in URL, reload-safe, cursor resets on filter change
- [ ] Commit 5: FundWarRoomModal deleted, zero imports remain, build clean
- [ ] No backend files touched
- [ ] No Phase 2 migration files touched
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `use:focusTrigger` Svelte 5 action pattern differs from what I described — adapt to whatever the Svelte 5 action API actually requires (may need `$effect` cleanup inside the action)
2. `FundFocusMode` props contract doesn't match what I assumed — read the actual component and adapt
3. URL sync breaks the existing data fetch pattern (currently done in a `$effect` or `load()` function) — investigate the actual fetch trigger and adapt, possibly moving to a load function in `+page.ts`
4. `resolve()` is not available for the screener path construction — use the extracted-const pattern from Phase 1 Task 0
5. `TerminalScreenerFilters` has its own internal state management that resists refactoring to URL params — investigate and report before force-converting

# REPORT FORMAT

1. Five commit SHAs with messages
2. Per commit: files created/modified/deleted, lines added/removed, verification output
3. Commit 2 extra: screenshot or description of FocusMode opening from screener row click
4. Commit 4 extra: URL examples showing filter persistence
5. Commit 5 extra: grep output confirming zero FundWarRoomModal references
6. Full-tree verification output
7. Any escape hatches hit

Begin by reading overview + this brief + audit. Verify Session 3.A merged (elite_flag in catalog response). Start commit 1.
