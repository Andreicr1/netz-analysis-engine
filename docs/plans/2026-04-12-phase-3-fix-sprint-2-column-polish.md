# Phase 3 Fix Sprint 2 — Grid Column Polish + Overflow Fix

**Date:** 2026-04-12
**Branch:** `feat/phase-3-fix-sprint-2`
**Scope:** 4 atomic commits fixing grid overflow + column restructuring for institutional density
**Estimated duration:** 1.5-2 hours concentrated Opus session
**Prerequisite reading:** this file only (self-contained)
**Depends on:** Fix Sprint 1 merged (main has 2-column layout, compact density, error boundary)

## Why this sprint exists

Fix Sprint 1 solved the major layout issues (QuickStats deletion, compact density, NAV filter, error boundary). Screenshots from 2026-04-12 post-merge reveal 4 remaining polish issues that prevent institutional-grade visual density:

1. **Grid rows overflow past the status bar** — content renders UNDER the 28px TerminalStatusBar at the bottom, clipping the last visible rows. The virtual scroll container's height doesn't account for the status bar.
2. **"Universe" column shows "MUTUAL" for every row** — repetitive, wastes space, carries no differentiating signal. Should be replaced with compact TYPE badges (MF, ETF, HF, BDC, MMF, UCITS, PRIV) + inline ELITE badge for elite-flagged funds.
3. **Name column is unbounded on 32" displays** — at 4K 100% zoom, the Name column consumes excessive width while data columns (AUM, returns) get compressed. Needs max-width constraint so the layout is consistent across 13" and 32" displays.
4. **Action column says "UNIVERSE"** — ambiguous institutional term. Should be "APPROVE" (the actual action the button performs).

All fixes are in `TerminalDataGrid.svelte` + minor CSS in `TerminalScreenerShell.svelte`. Pure frontend, zero backend changes.

## Project mandate (binding)

> Máximo de percepção visual é válida somente quando a infraestrutura está correta, reportando dados reais e precisos.

Infrastructure IS correct. Now every pixel must earn its place on screen. Bloomberg density is the target: compact badges, fixed column widths, zero overflow.

## READ FIRST

1. `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` — the main file being modified across all 4 commits. Read FULLY before starting.
2. `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` — the 2-column grid container. May need height adjustment.
3. `frontends/wealth/src/lib/components/terminal/shell/TerminalShell.svelte` — understand the grid layout: `32px 1fr 28px` rows (topnav | content | statusbar). The content row's `1fr` is where LayoutCage lives. The cage's child (screener) must NOT overflow past the `1fr` boundary into the statusbar's 28px.
4. `frontends/wealth/src/lib/components/terminal/shell/LayoutCage.svelte` — `overflow: hidden` should contain children, but the virtual scroll spacer div may be circumventing this.
5. `packages/investintell-ui/src/lib/tokens/terminal.css` — token values for spacing, colors, text scales used in badge styling.

## Pre-flight

```bash
pnpm --filter netz-wealth-os dev
# Open http://localhost:<port>/terminal-screener
# Confirm all 4 issues visible:
# 1. Scroll down — last rows clip under the status bar
# 2. Universe column shows "MUTUAL" for every row
# 3. On 32" display at 100% zoom, Name column is too wide
# 4. Action column says "+ UNIVERSE"
```

---

# COMMIT 1 — fix(screener): grid height respects status bar boundary

## Problem

The virtual scroll container's height extends past the TerminalShell's content grid row boundary (`1fr`), causing rows to render under the 28px TerminalStatusBar. The user cannot see or interact with the last ~1 row that's hidden behind the status bar.

Root cause is likely one of:
- The virtual scroll container uses `height: 100%` which resolves to the LayoutCage's full height, but the cage's `overflow: hidden` is not clipping the spacer div correctly
- The spacer div's absolute height (`totalRows * 32px`) exceeds the container, and the scroll container itself overflows
- A `min-height` or `flex-grow` on an ancestor is pushing the grid past its bounded area

## Deliverable

Investigate and fix the height chain from TerminalShell → LayoutCage → TerminalScreenerShell → TerminalDataGrid → virtual scroll container.

**Expected fix pattern:** The DataGrid's scroll container must have `height: 100%` relative to a parent that has a BOUNDED height (not content-derived). The chain should be:

```
TerminalShell grid row "content" (1fr of 100dvh - 32px - 28px)
  → LayoutCage (height: 100%, overflow: hidden, padding: 8px compact)
    → TerminalScreenerShell (height: 100%, display: grid, grid: 1fr)
      → DataGrid scroll container (height: 100%, overflow-y: auto)
        → spacer div (height: totalRows * 32px, contains visible rows)
```

Every element in this chain must have either `height: 100%` or a grid/flex constraint that prevents content-based growth. If ANY element uses `min-height: 0` (flex item shrink) instead of bounded height, the overflow escapes.

**Specific checks:**
1. TerminalScreenerShell: is the grid container `height: 100%` or `min-height: 0`?
2. DataGrid scroll container: is `overflow-y: auto` set? Is `height: 100%` set?
3. Is there a `position: relative` missing that would cause the spacer div to escape containment?
4. Is the LayoutCage `overflow: hidden` actually effective, or is a child using `position: fixed/absolute` that escapes the clip?

Fix the root cause. Do NOT use `calc(100vh - Npx)` as a workaround — the shell grid already computes the correct height via `grid-template-rows: 32px 1fr 28px`. The cage should fill `1fr` without knowing the pixel values.

## Verification

1. Open screener with 9k+ rows
2. Scroll to the very bottom — last row is FULLY visible ABOVE the status bar
3. Status bar is always visible and never overlapped by grid content
4. No vertical scrollbar on the outer page (only the DataGrid has a scrollbar)
5. Resize the browser window — grid height adjusts, status bar stays pinned
6. Test on both narrow (13" equivalent, ~1366px wide) and wide (32" equivalent, ~3840px or 2560px) viewports

## Commit 1 template

```
fix(screener): grid height respects status bar boundary

Grid rows were rendering under the 28px TerminalStatusBar because
the virtual scroll container's height wasn't bounded by the shell's
grid layout. Root cause: <describe what you found>.

Fix: <describe the fix — which element needed height constraint,
which overflow was missing, which ancestor was unbounded>.

The height chain is now fully bounded:
TerminalShell 1fr → LayoutCage 100% overflow:hidden → ScreenerShell
100% grid → DataGrid 100% overflow-y:auto → spacer div (scrollable).

Last row is fully visible above the status bar. No outer page scroll.
Resizing adjusts correctly.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — refactor(screener): replace Universe column with TYPE badges + inline ELITE badge

## Problem

The "Universe" column shows "MUTUAL" for almost every row — zero differentiating signal, wastes horizontal space with a repeated 6-letter word. The ELITE badge (Phase 3.B commit 3) is not visible because it was either rendered in a compressed area or is not displaying at all.

## Deliverable

### Replace "Universe" column with "TYPE" column

Instead of a full-text universe label, render a compact uppercase badge per fund type:

```typescript
const TYPE_BADGES: Record<string, { label: string; title: string }> = {
  registered_us: { label: "MF",    title: "Mutual Fund" },
  etf:           { label: "ETF",   title: "Exchange-Traded Fund" },
  bdc:           { label: "BDC",   title: "Business Development Company" },
  money_market:  { label: "MMF",   title: "Money Market Fund" },
  private_us:    { label: "PRIV",  title: "Private Fund" },
  ucits_eu:      { label: "UCITS", title: "UCITS (European)" },
  // Add others as needed
};
```

Each badge is:
- 2-4 letter uppercase text
- Monospace, `var(--terminal-text-10)`, `var(--terminal-fg-tertiary)`
- 1px hairline border, zero radius, `padding: 1px 4px`
- `title` attribute shows the full name on hover

### Add inline ELITE badge in the same column

For rows where `asset.elite_flag === true`, render an additional amber badge AFTER the type badge:

```svelte
<div class="type-badges">
  <span class="type-badge" title={typeBadge.title}>{typeBadge.label}</span>
  {#if asset.elite_flag}
    <span class="elite-badge" title="Elite — top {asset.elite_target_count_per_strategy} in {asset.strategy_label}">
      ELITE
    </span>
  {/if}
</div>
```

ELITE badge styling:
- `var(--terminal-accent-amber)` text and border
- Same dimensions as type badge
- Stands out visually next to the muted type badge

### Column header

Change from "UNIVERSE" to "TYPE" in the grid header.

### Column width

TYPE column: fixed 100px (enough for `UCITS ELITE` side by side with small gap). If badges wrap, that's OK — 2 rows of badges in a 32px row height works if `line-height` is tight.

Actually, better: make the TYPE column `min-width: 60px; max-width: 120px` so it adapts. If only `MF`, 60px is fine. If `UCITS ELITE`, needs 120px.

### Remove ELITE badge from wherever it was previously rendered

If commit 3 of Phase 3.B put the ELITE badge in a different column (e.g., inline with the ticker or name), move it to the TYPE column. One canonical location for badges.

## Verification

1. Every row shows a 2-4 letter TYPE badge (MF, ETF, BDC, etc.) instead of "MUTUAL"
2. Elite-flagged rows show `MF ELITE` (or `ETF ELITE`, etc.) in amber
3. Non-elite rows show only the type badge in muted color
4. Hover on any badge → full name in title tooltip
5. Column header reads "TYPE"
6. Column width is reasonable on both 13" and 32" displays

---

# COMMIT 3 — refactor(screener): column width tuning for 13" to 32" display range

## Problem

On 32" 4K at 100% zoom, the Name column consumes excessive width while data columns are compressed. On 13" 4K, everything is compressed but usable. The grid needs fixed/constrained column widths that work across the display size range.

## Deliverable

Replace the current column width definitions with an explicit grid template that constrains every column:

```css
/* Column width spec optimized for 13"-32" range at 4K */
.grid-header, .grid-row {
  display: grid;
  grid-template-columns:
    80px           /* TICKER — fixed, always visible */
    100px          /* TYPE — badges (MF/ETF + ELITE) */
    minmax(180px, 1fr) /* NAME — flex absorbs remaining space, bounded */
    140px          /* STRATEGY — fixed */
    40px           /* GEO — 2-letter code */
    90px           /* AUM — right-aligned, compact format */
    70px           /* 1Y RET — right-aligned */
    70px           /* 10Y RET — right-aligned */
    60px           /* ER% — right-aligned */
    50px           /* TREND — sparkline canvas */
    90px           /* ACTION — APPROVE/+DD button */
  ;
  column-gap: 4px; /* Bloomberg-grade tight gap */
}
```

**Key design decisions:**
- NAME is the ONLY flex column (`minmax(180px, 1fr)`) — absorbs extra space on wide displays, respects minimum on narrow
- All data columns are FIXED width — no expansion on wide displays, consistent alignment
- `column-gap: 4px` is Bloomberg-density tight (not 8px or 16px)
- Total fixed columns: 80+100+140+40+90+70+70+60+50+90 = 790px. On 1920px viewport minus 280px filters minus 16px padding = 1624px available. NAME gets 1624-790 = 834px. On 1366px: 1366-280-16 = 1070px. NAME gets 1070-790 = 280px. Both work.
- On 3840px at 100% zoom: NAME gets ~3000px which is too wide. That's why `max-width` or `1fr` with a cap would help. BUT CSS Grid `minmax(180px, 1fr)` will naturally expand the NAME column. The user said 125% zoom on 32" is fine — at 125% zoom the effective viewport is ~3072px / 1.25 = ~2457px, and NAME gets ~1667px which is reasonable.

**Alternate approach:** add a `max-width` on the grid container itself:

```css
.grid-container {
  max-width: 2200px; /* Cap for ultra-wide displays */
  margin: 0 auto; /* Center on ultra-wide */
}
```

This caps the grid at 2200px and centers it on 32"+ displays, preventing NAME from growing unbounded. The grid stays left-aligned on normal displays.

**Pick the approach that produces the best result on both screen sizes.** Test in the browser at both 1366px and 2560px+ widths. If `max-width` centering looks odd on the terminal (Bloomberg doesn't center — it fills), skip centering and just let NAME grow.

Actually, the institutional approach is: **fill the viewport, never center**. Bloomberg, Refinitiv, FactSet all fill edge-to-edge. So skip max-width centering. Let NAME grow on ultra-wide. The NAME column growing wide on a 32" display is acceptable because the analyst has more screen to read fund names — that IS the use case for a 32" display.

The real problem the user reported is "at 100% zoom the NAME column is too wide". The fix is the fixed widths on data columns + `1fr` on NAME + tight column-gap. If NAME still feels too wide on ultra-wide, that's a user preference for zoom level, not a code bug.

## Verification

1. On 1366px viewport: all columns visible, NAME is ~280px, no truncation on AUM/returns
2. On 1920px viewport: all columns comfortable, NAME is ~830px
3. On 2560px+ viewport: NAME grows proportionally, data columns stay fixed, no compression
4. Column gaps are tight (4px) — Bloomberg density
5. Right-aligned columns (AUM, returns, ER%) are right-aligned with tabular-nums
6. Sparkline column is exactly 50px wide (matches the 48px canvas + 1px border each side)

---

# COMMIT 4 — refactor(screener): rename action column UNIVERSE → APPROVE

## Problem

The action column header and button labels say "UNIVERSE" which is ambiguous — "universe" in institutional wealth management could mean "the investment universe" (all available funds), "the approved universe" (the portfolio's eligible set), or a specific product category. The button's actual action is APPROVE (send to approved universe), so the label should say that.

## Deliverable

### In TerminalDataGrid.svelte:

1. Column header: `UNIVERSE` → `ACTION` (or keep `ACTION` if it's already that)
2. Button label for liquid funds: `+ UNIVERSE` → `APPROVE`
3. Button label for private/BDC funds: `+ DD` stays as-is (already clear)
4. For already-approved funds: `IN UNIVERSE` → `APPROVED` (past tense, clearer status)
5. For pending DD: `PENDING` stays as-is

### Label map:

```typescript
function getActionLabel(asset: ScreenerAsset): { label: string; style: string } {
  if (asset.in_universe)
    return { label: "APPROVED", style: "status-success" };
  if (asset.approval_status === "pending")
    return { label: "PENDING", style: "fg-muted" };
  if (LIQUID_UNIVERSES.has(asset.universe))
    return { label: "APPROVE", style: "accent-amber" };
  return { label: "+ DD", style: "accent-cyan" };
}
```

## Verification

1. Liquid fund row → button says `APPROVE` (not `+ UNIVERSE`)
2. Already-approved fund → label says `APPROVED` in success green
3. Private fund → button says `+ DD` in cyan
4. Pending → label says `PENDING` in muted
5. Column header says `ACTION`

## Commit 4 template

```
refactor(screener): rename action labels for institutional clarity

"UNIVERSE" is ambiguous in institutional wealth management — could mean
the investment universe, the approved universe, or a product category.
The button's action is explicitly "approve to universe", so the label
should say APPROVE.

Label changes:
- "+ UNIVERSE" → "APPROVE" (liquid fund action)
- "IN UNIVERSE" → "APPROVED" (past tense status)
- "+ DD" unchanged (already clear)
- "PENDING" unchanged (already clear)

Column header remains "ACTION" (unchanged if already that).

Institutional analysts expect precise verbs, not nouns. "Approve"
is an action; "Universe" is a concept.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

After all 4 commits:

1. **Height:** scroll to bottom → last row fully visible above status bar, no overflow
2. **TYPE column:** shows compact badges (MF/ETF/BDC/MMF/PRIV/UCITS) + amber ELITE badge for elite-flagged rows
3. **Name column:** constrained but flexible, reasonable on both 13" and 32"
4. **ACTION column:** says APPROVE for liquids, APPROVED for approved, +DD for privates
5. **Column gaps:** tight (4px), Bloomberg density
6. **All other features preserved:** virtualization, sparklines, keyboard shortcuts, ELITE filter, URL sync, FocusMode
7. `svelte-check` → 0 new errors
8. `pnpm --filter netz-wealth-os build` → clean

# SELF-CHECK

- [ ] Commit 1: grid height bounded, last row visible above status bar, no outer scroll
- [ ] Commit 2: TYPE badges replace Universe text, ELITE badge visible in amber for flagged rows
- [ ] Commit 3: column widths tuned, tested at 1366px AND 2560px+, data columns fixed, NAME flexible
- [ ] Commit 4: APPROVE label, APPROVED status, +DD unchanged
- [ ] All terminal tokens (no hex)
- [ ] No backend files touched
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. Height fix requires changing LayoutCage or TerminalShell (not just DataGrid) → make the change in the correct file, report which file was the root cause
2. ELITE badge data shows `elite_flag = false` for all visible rows (Tiingo migration hasn't run, scores degraded) → badge rendering is correct but no rows qualify. Add a note in the commit body. The badge WILL appear once Tiingo migration populates scores correctly.
3. CSS Grid `minmax()` doesn't work on the grid-template-columns for the NAME column in the specific Svelte/Vite build → use `min-width` + `max-width` on the column div instead
4. `column-gap: 4px` causes touch targets to be too small on mobile → this is a desktop terminal, not mobile. 4px is fine. Note in commit body.
5. Sparkline canvas width doesn't match the new fixed 50px column → adjust canvas width in the sparkline drawing code to match

# NOT VALID ESCAPE HATCHES

- "The height overflow is a browser-specific issue" → fix it for ALL browsers
- "Column widths look fine at MY resolution" → test at BOTH 1366px AND 2560px, per the user's explicit dual-display requirement
- "ELITE badge can wait until Tiingo populates data" → ship the rendering NOW. Badge appears automatically when data arrives.

# REPORT FORMAT

1. Four commit SHAs with messages
2. Per commit: files modified, lines changed, verification
3. Commit 1 extra: root cause analysis of the height overflow
4. Commit 2 extra: list of TYPE badge mappings used
5. Commit 3 extra: column widths at 1366px vs 2560px (before/after)
6. Screenshots if possible (before fix sprint 2 vs after)
7. Full-tree verification

Begin by reading this brief + starting pnpm dev to see the current state. Fix the height overflow FIRST (commit 1) because it affects visual validation of all subsequent commits.
