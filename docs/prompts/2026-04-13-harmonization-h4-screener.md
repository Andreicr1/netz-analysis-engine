# Session H4 -- Screener Token Migration

**Branch:** `feat/harmonization-h4-screener`
**Base:** `main` (after all prior harmonization sessions merged)
**Estimated scope:** ~115 hex replacements, 3 font replacements, 1 Svelte 5 migration, 2 straggler fixes

---

## CONTEXT

The Terminal Screener was built before Phase 1 primitives existed. Three Svelte components contain ~115 hardcoded hex values and use `"Urbanist"` font instead of the terminal monospace register. This session migrates every visual constant to `--terminal-*` CSS custom properties from the single source of truth:

```
packages/investintell-ui/src/lib/tokens/terminal.css
```

The `readTerminalTokens()` function exported from `@investintell/ui` (file: `packages/investintell-ui/src/lib/charts/terminal-options.ts`) reads CSS custom properties at runtime. Use it for JS-context colors (canvas sparkline drawing).

**CRITICAL design note:** The screener previously used `#2d7ef7` (medium blue) for accents. The terminal design system uses `--terminal-accent-cyan` which resolves to `#00e5ff` (bright cyan). This is an intentional aesthetic shift from the blue to the brutalist cyan palette. Do NOT preserve the old blue values.

---

## OBJECTIVE

1. Replace ALL hex color literals in the 3 screener component `<style>` blocks with `var(--terminal-*)` tokens
2. Replace ALL `"Urbanist"` font references with `var(--terminal-font-mono)` or `var(--terminal-font-sans)` as appropriate (screener is a data surface -- monospace is correct)
3. Replace ALL `rgba()` interactive states with `color-mix(in srgb, ...)` to avoid re-introducing hex
4. Square all rounded elements (badge `border-radius: 50%`, slider thumb `border-radius: 50%`) to `var(--terminal-radius-none)`
5. Migrate sparkline canvas colors from hex to runtime token reads via `readTerminalTokens()`
6. Migrate `$app/stores` to `$app/state` in the screener +page.svelte (Svelte 5)
7. Fix MonteCarloTab `.toLocaleString()` formatter violation
8. Fix BacktestTab hardcoded `font-size: 14px`

---

## CONSTRAINTS

- ZERO hex literals may remain in any modified `.svelte` file (CSS or JS)
- ZERO `"Urbanist"` references may remain
- ZERO `border-radius` values other than `0` or `var(--terminal-radius-none)` in screener components
- Do NOT modify `packages/investintell-ui/src/lib/tokens/terminal.css` -- it is the source of truth
- Do NOT modify `packages/investintell-ui/src/lib/charts/terminal-options.ts`
- Do NOT remove any methods, props, or exports from any component
- Do NOT change component logic, data flow, or API calls
- All `rgba()` values that embed a color must use `color-mix(in srgb, var(--terminal-TOKEN) PERCENT%, transparent)` -- never raw hex inside `rgba()`

---

## DELIVERABLES

### File 1: `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte`

**Hex-to-token mapping (CSS `<style>` block):**

| Line(s) | Old Value | New Value | Property/Selector |
|---------|-----------|-----------|-------------------|
| 463 | `background: #000000` | `background: var(--terminal-bg-void)` | `.ts-root` |
| 464 | `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` | `.ts-root` |
| 530 | `border: 1px solid rgba(255, 255, 255, 0.12)` | `border: var(--terminal-border-hairline)` | `.sep-btn` |
| 541 | `border-color: #f59e0b` | `border-color: var(--terminal-accent-amber)` | `.sep-btn:hover` |
| 542 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.sep-btn:hover` |
| 561 | `border: 1px solid rgba(255, 255, 255, 0.12)` | `border: var(--terminal-border-hairline)` | `.ts-toast` |
| 562 | `background: #0d1220` | `background: var(--terminal-bg-overlay)` | `.ts-toast` |
| 557 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.ts-toast` |
| 565 | `color: #22c55e` | `color: var(--terminal-status-success)` | `.ts-toast--success` |
| 565 | `border-color: rgba(34, 197, 94, 0.3)` | `border-color: color-mix(in srgb, var(--terminal-status-success) 30%, transparent)` | `.ts-toast--success` |
| 566 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.ts-toast--warn` |
| 566 | `border-color: rgba(245, 158, 11, 0.3)` | `border-color: color-mix(in srgb, var(--terminal-accent-amber) 30%, transparent)` | `.ts-toast--warn` |
| 567 | `color: #2d7ef7` | `color: var(--terminal-accent-cyan)` | `.ts-toast--info` |
| 567 | `border-color: rgba(45, 126, 247, 0.3)` | `border-color: color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent)` | `.ts-toast--info` |

**Note:** The error panel (`.sep-panel`, `.sep-header`, `.sep-code`, `.sep-title`, `.sep-message`, `.sep-hint`, `.sep-btn`, `.sep-btn--reload`) already uses `var(--terminal-*)` tokens with hex fallbacks. Leave those as-is -- they are correctly implemented.

---

### File 2: `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte`

**Hex-to-token mapping (CSS `<style>` block):**

| Line(s) | Old Value | New Value | Property/Selector |
|---------|-----------|-----------|-------------------|
| 530 | `background: #0c1018` | `background: var(--terminal-bg-panel)` | `.sf-root` |
| 531 | `border-right: 1px solid rgba(255, 255, 255, 0.06)` | `border-right: 1px solid var(--terminal-fg-muted)` | `.sf-root` |
| 532 | `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` | `.sf-root` |
| 534 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.sf-root` |
| 542 | `border-bottom: 1px solid rgba(255, 255, 255, 0.06)` | `border-bottom: 1px solid var(--terminal-fg-muted)` | `.sf-header` |
| 550 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.sf-title` |
| 563 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.sf-action` |
| 567 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-action` |
| 572 | `color: #9aa3b3` | `color: var(--terminal-fg-secondary)` | `.sf-action:hover` |
| 577 | `color: #2d7ef7` | `color: var(--terminal-accent-cyan)` | `.sf-clear` |
| 584 | `color: #5a9ef7` | `color: var(--terminal-accent-cyan)` | `.sf-clear:hover` (same token, lighter was old blue variant) |
| 590 | `border-bottom: 1px solid rgba(255, 255, 255, 0.06)` | `border-bottom: 1px solid var(--terminal-fg-muted)` | `.sf-elite-chip-row` |
| 595 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-elite-chip` |
| 602 | `border: 1px solid rgba(255, 255, 255, 0.12)` | `border: var(--terminal-border-hairline)` | `.sf-elite-chip` |
| 603 | `color: #8a94a6` | `color: var(--terminal-fg-secondary)` | `.sf-elite-chip` |
| 608 | `border-color: #f59e0b` | `border-color: var(--terminal-accent-amber)` | `.sf-elite-chip:hover` |
| 609 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.sf-elite-chip:hover` |
| 612 | `border-color: #f59e0b` | `border-color: var(--terminal-accent-amber)` | `.sf-elite-chip--active` |
| 613 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.sf-elite-chip--active` |
| 614 | `background: rgba(245, 158, 11, 0.08)` | `background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent)` | `.sf-elite-chip--active` |
| 625 | `border-bottom: 1px solid rgba(255, 255, 255, 0.04)` | `border-bottom: 1px solid var(--terminal-fg-disabled)` | `.sf-section` |
| 637 | `color: #8a94a6` | `color: var(--terminal-fg-secondary)` | `.sf-section-toggle` |
| 645 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.sf-section-toggle:hover` |
| 665 | `border-radius: 50%` | `border-radius: var(--terminal-radius-none)` | `.sf-active-count` -- **SQUARE THE BADGE** |
| 666 | `background: #22d3ee` | `background: var(--terminal-accent-cyan)` | `.sf-active-count` |
| 667 | `color: #0b0f1a` | `color: var(--terminal-fg-inverted)` | `.sf-active-count` |
| 668 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-active-count` |
| 694 | `accent-color: #2d7ef7` | `accent-color: var(--terminal-accent-cyan)` | `.sf-check input[type="checkbox"]` |
| 701 | `color: #9aa3b3` | `color: var(--terminal-fg-secondary)` | `.sf-check-label` |
| 721 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.sf-metric-label` |
| 736 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.sf-metric-input` |
| 737 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-metric-input` |
| 734 | `border: 1px solid rgba(255, 255, 255, 0.08)` | `border: 1px solid var(--terminal-fg-disabled)` | `.sf-metric-input` |
| 735 | `border-radius: 0` | (already 0, leave as-is) | `.sf-metric-input` |
| 751 | `color: #3d4a5c` | `color: var(--terminal-fg-muted)` | `.sf-metric-input::placeholder` |
| 755 | `border-color: rgba(45, 126, 247, 0.4)` | `border-color: color-mix(in srgb, var(--terminal-accent-cyan) 40%, transparent)` | `.sf-metric-input:focus` |
| 759 | `color: #3d4a5c` | `color: var(--terminal-fg-muted)` | `.sf-metric-sep` |
| 772 | `border: 1px solid rgba(255, 255, 255, 0.08)` | `border: 1px solid var(--terminal-fg-disabled)` | `.sf-manager-input` |
| 773 | `border-radius: 0` | (already 0, leave as-is) | `.sf-manager-input` |
| 774 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.sf-manager-input` |
| 775 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-manager-input` |
| 782 | `color: #3d4a5c` | `color: var(--terminal-fg-muted)` | `.sf-manager-input::placeholder` |
| 785 | `border-color: rgba(45, 126, 247, 0.4)` | `border-color: color-mix(in srgb, var(--terminal-accent-cyan) 40%, transparent)` | `.sf-manager-input:focus` |
| 793 | `background: #0d1220` | `background: var(--terminal-bg-overlay)` | `.sf-manager-suggestions` |
| 794 | `border: 1px solid rgba(255, 255, 255, 0.08)` | `border: 1px solid var(--terminal-fg-disabled)` | `.sf-manager-suggestions` |
| 806 | `color: #9aa3b3` | `color: var(--terminal-fg-secondary)` | `.sf-manager-suggestion` |
| 810 | `background: rgba(45, 126, 247, 0.08)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent)` | `.sf-manager-suggestion:hover` |
| 811 | `color: #e2e8f0` | `color: var(--terminal-fg-primary)` | `.sf-manager-suggestion:hover` |
| 825 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-manager-chip` |
| 827 | `color: #22d3ee` | `color: var(--terminal-accent-cyan)` | `.sf-manager-chip` |
| 828 | `border: 1px solid rgba(34, 211, 238, 0.3)` | `border: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent)` | `.sf-manager-chip` |
| 839 | `color: #22d3ee` | `color: var(--terminal-accent-cyan)` | `.sf-manager-chip-x` |
| 844 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.sf-manager-chip-x` |
| 862 | `color: #8a94a6` | `color: var(--terminal-fg-secondary)` | `.sf-range-header` |
| 866 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.sf-range-value` |
| 876 | `background: #1e293b` | `background: var(--terminal-bg-panel-raised)` | `.sf-slider` |
| 877 | `border-radius: 2px` | `border-radius: var(--terminal-radius-none)` | `.sf-slider` -- **SQUARE** |
| 884 | `border-radius: 50%` | `border-radius: var(--terminal-radius-none)` | `.sf-slider::-webkit-slider-thumb` -- **SQUARE** |
| 885 | `background: #2d7ef7` | `background: var(--terminal-accent-cyan)` | `.sf-slider::-webkit-slider-thumb` |
| 893 | `border-radius: 50%` | `border-radius: var(--terminal-radius-none)` | `.sf-slider::-moz-range-thumb` -- **SQUARE** |
| 894 | `background: #2d7ef7` | `background: var(--terminal-accent-cyan)` | `.sf-slider::-moz-range-thumb` |

---

### File 3: `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte`

**Hex-to-token mapping (CSS `<style>` block):**

| Line(s) | Old Value | New Value | Property/Selector |
|---------|-----------|-----------|-------------------|
| 415 | `background: #0b0f1a` | `background: var(--terminal-bg-void)` | `.dg-root` |
| 416 | `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` | `.dg-root` |
| 418 | `color: #c8d0dc` | `color: var(--terminal-fg-primary)` | `.dg-root` |
| 445 | `background: #0d1220` | `background: var(--terminal-bg-panel-sunken)` | `.dg-header` |
| 446 | `border-bottom: 1px solid rgba(255, 255, 255, 0.08)` | `border-bottom: 1px solid var(--terminal-fg-disabled)` | `.dg-header` |
| 455 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-th` |
| 487 | `background: rgba(45, 126, 247, 0.06)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 6%, transparent)` | `.dg-row:hover` |
| 490 | `background: rgba(45, 126, 247, 0.10)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent)` | `.dg-row.selected` |
| 493 | `background: rgba(45, 126, 247, 0.14)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 14%, transparent)` | `.dg-row.highlighted` |
| 494 | `outline: 1px solid rgba(45, 126, 247, 0.30)` | `outline: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 30%, transparent)` | `.dg-row.highlighted` |
| 498 | `background: rgba(255, 255, 255, 0.012)` | `background: color-mix(in srgb, var(--terminal-fg-primary) 1.2%, transparent)` | `.dg-row.zebra` |
| 501 | `background: rgba(45, 126, 247, 0.06)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 6%, transparent)` | `.dg-row.zebra:hover` |
| 504 | `background: rgba(45, 126, 247, 0.10)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 10%, transparent)` | `.dg-row.zebra.selected` |
| 507 | `background: rgba(45, 126, 247, 0.14)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 14%, transparent)` | `.dg-row.zebra.highlighted` |
| 523 | `color: #e2e8f0` | `color: var(--terminal-fg-primary)` | `.dg-ticker` |
| 527 | `color: #9aa3b3` | `color: var(--terminal-fg-secondary)` | `.dg-name` |
| 538 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-type-badge` |
| 550 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-elite-inline` |
| 561 | `color: #8a94a6` | `color: var(--terminal-fg-secondary)` | `.dg-strategy` |
| 566 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-geo` |
| 575 | `color: #22c55e` | `color: var(--terminal-status-success)` | `.pos` |
| 576 | `color: #ef4444` | `color: var(--terminal-status-error)` | `.neg` |
| 579 | `color: #22c55e` | `color: var(--terminal-status-success)` | `.score-high` |
| 580 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.score-mid` |
| 581 | `color: #ef4444` | `color: var(--terminal-status-error)` | `.score-low` |
| 586 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-empty` |
| 599 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-spark-empty` |
| 608 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-action-btn` |
| 619 | `border: 1px solid rgba(245, 158, 11, 0.35)` | `border: 1px solid color-mix(in srgb, var(--terminal-accent-amber) 35%, transparent)` | `.dg-action-approve` |
| 620 | `color: #f59e0b` | `color: var(--terminal-accent-amber)` | `.dg-action-approve` |
| 623 | `background: rgba(245, 158, 11, 0.08)` | `background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent)` | `.dg-action-approve:hover` |
| 624 | `color: #fbbf24` | `color: var(--terminal-accent-amber)` | `.dg-action-approve:hover` |
| 626 | `border: 1px solid rgba(45, 126, 247, 0.25)` | `border: 1px solid color-mix(in srgb, var(--terminal-accent-cyan) 25%, transparent)` | `.dg-action-dd` |
| 627 | `color: #2d7ef7` | `color: var(--terminal-accent-cyan)` | `.dg-action-dd` |
| 630 | `background: rgba(45, 126, 247, 0.08)` | `background: color-mix(in srgb, var(--terminal-accent-cyan) 8%, transparent)` | `.dg-action-dd:hover` |
| 631 | `color: #93bbfc` | `color: var(--terminal-accent-cyan)` | `.dg-action-dd:hover` |
| 636 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-action-label` |
| 641 | `color: #22c55e` | `color: var(--terminal-status-success)` | `.dg-action-approved` |
| 644 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-action-pending` |
| 658 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-loading-more` |
| 660 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-loading-more` |
| 672 | `font-family: "JetBrains Mono", monospace` | `font-family: var(--terminal-font-mono)` | `.dg-end-of-catalog` |
| 675 | `color: #3d4a5c` | `color: var(--terminal-fg-muted)` | `.dg-end-of-catalog` |
| 687 | `color: #5a6577` | `color: var(--terminal-fg-tertiary)` | `.dg-footer` |
| 688 | `border-top: 1px solid rgba(255, 255, 255, 0.06)` | `border-top: 1px solid var(--terminal-fg-muted)` | `.dg-footer` |
| 689 | `background: #0d1220` | `background: var(--terminal-bg-panel-sunken)` | `.dg-footer` |
| 692 | `color: #ef4444` | `color: var(--terminal-status-error)` | `.dg-footer-err` |

**Sparkline canvas colors (JS `<script>` block, `drawSparkline` function, ~line 232-233):**

The current code at line 232-233:
```js
ctx.strokeStyle = delta > 0 ? "#22c55e" : delta < 0 ? "#ef4444" : "#5a6577";
```

Must become:
```js
const tk = readTerminalTokens();
ctx.strokeStyle = delta > 0 ? tk.statusSuccess : delta < 0 ? tk.statusError : tk.fgTertiary;
```

**Import change:** Line 43 currently imports:
```ts
import { formatNumber } from "@investintell/ui";
```
Change to:
```ts
import { formatNumber, readTerminalTokens } from "@investintell/ui";
```

---

### File 4: `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte`

**Svelte 5 migration: `$app/stores` to `$app/state`**

This is NOT just an import swap. With `$app/state`, the `page` object is already reactive -- all `$page` auto-subscriptions must drop the `$` prefix.

**Before (line 13):**
```ts
import { page } from "$app/stores";
```

**After:**
```ts
import { page } from "$app/state";
```

**Then replace ALL `$page` references with `page`:**

| Line | Old | New |
|------|-----|-----|
| 49 | `const currentFilters = $derived(parseFiltersFromURL($page.url.searchParams));` | `const currentFilters = $derived(parseFiltersFromURL(page.url.searchParams));` |
| 53 | `const url = new URL($page.url);` | `const url = new URL(page.url);` |

There are exactly 2 occurrences of `$page` in this file (lines 49 and 53). Both must change. Verify with `grep '\$page' +page.svelte` after editing -- must return zero matches.

---

### File 5: `frontends/wealth/src/lib/components/terminal/builder/MonteCarloTab.svelte`

**Fix: `.toLocaleString()` formatter violation at line 156**

**Before (line 9):**
```ts
import { formatPercent, createTerminalChartOptions, readTerminalTokens } from "@investintell/ui";
```

**After:**
```ts
import { formatNumber, formatPercent, createTerminalChartOptions, readTerminalTokens } from "@investintell/ui";
```

**Before (line 156):**
```svelte
({data.n_simulations.toLocaleString()} paths)
```

**After:**
```svelte
({formatNumber(data.n_simulations, 0)} paths)
```

---

### File 6: `frontends/wealth/src/lib/components/terminal/builder/BacktestTab.svelte`

**Fix: hardcoded `font-size: 14px` at line 262**

**Before:**
```css
.bt-metric-value {
    font-size: 14px;
```

**After:**
```css
.bt-metric-value {
    font-size: var(--terminal-text-14);
```

---

## VERIFICATION

Run all checks from the `frontends/wealth/` directory:

### 1. Zero hex in modified screener files
```bash
# Must return ZERO matches
grep -nE '#[0-9a-fA-F]{3,8}' \
  frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte \
  frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte \
  frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte
```

### 2. Zero Urbanist references
```bash
# Must return ZERO matches
grep -rn "Urbanist" frontends/wealth/src/lib/components/screener/
```

### 3. Zero $app/stores in screener page
```bash
# Must return ZERO matches
grep -n 'app/stores' frontends/wealth/src/routes/\(terminal\)/terminal-screener/+page.svelte
```

### 4. Zero $page references (should only have `page` without $)
```bash
# Must return ZERO matches
grep -nE '\$page' frontends/wealth/src/routes/\(terminal\)/terminal-screener/+page.svelte
```

### 5. Zero .toLocaleString() in MonteCarloTab
```bash
grep -n 'toLocaleString' frontends/wealth/src/lib/components/terminal/builder/MonteCarloTab.svelte
```

### 6. Zero hardcoded font-size in BacktestTab (should all be var())
```bash
grep -n 'font-size: [0-9]' frontends/wealth/src/lib/components/terminal/builder/BacktestTab.svelte
```

### 7. Build check
```bash
cd frontends/wealth && pnpm check
```

### 8. No raw rgba() with hardcoded color channels in screener files
```bash
# Must return ZERO matches (rgba with numeric R,G,B is forbidden)
grep -nE 'rgba\([0-9]' \
  frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte \
  frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte \
  frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte
```

---

## ANTI-PATTERNS

1. **DO NOT** use `rgba(0, 229, 255, 0.06)` or any `rgba(R,G,B,A)` with numeric color values. This re-introduces hex-equivalent hardcoding. Use `color-mix(in srgb, var(--terminal-accent-cyan) 6%, transparent)` instead.

2. **DO NOT** leave any `"JetBrains Mono", monospace` hardcoded -- use `var(--terminal-font-mono)` which includes JetBrains Mono in its stack.

3. **DO NOT** change the import to `$app/state` without also removing the `$` prefix from every `$page` reference. The `$` prefix is Svelte 4 store auto-subscription syntax; with `$app/state` the object is natively reactive.

4. **DO NOT** add new CSS custom properties to `terminal.css`. All needed tokens already exist.

5. **DO NOT** change component props, exported interfaces, event dispatching, or API call logic. This is a purely visual/token migration.

6. **DO NOT** change the `.dg-type-badge` or `.dg-elite-inline` rules that already use `var(--terminal-*)` tokens. They are correct. Only change the ones that still use hardcoded `"JetBrains Mono"` font-family.

---

## COMMIT

```
fix(screener): migrate ~115 hex values + Urbanist font to --terminal-* tokens

- TerminalScreenerShell: replace hex with tokens, monospace font
- TerminalScreenerFilters: ~40 hex, square badge + slider, accent-cyan
- TerminalDataGrid: ~35 hex, color-mix() row states, sparkline tokens
- +page.svelte: $app/stores -> $app/state (Svelte 5)
- MonteCarloTab: .toLocaleString() -> formatNumber()
- BacktestTab: hardcoded font-size -> var(--terminal-text-14)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
