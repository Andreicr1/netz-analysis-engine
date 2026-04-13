# Session H3 -- Builder CalibrationPanel Terminal-ization

**Branch:** `feat/harmonization-h3-calibration`
**Base:** `main` (after all regime fix PRs are merged)
**Commit message:** `refactor(builder): terminal-ize CalibrationPanel — replace ii tokens, Urbanist, rounded corners, @investintell/ui components`

---

## CONTEXT

The Builder page (`(terminal)/portfolio/builder/+page.svelte`) is a terminal-aesthetic 2-column layout. The right column (tabs, cascade, activation) already speaks the terminal dialect (`--terminal-*` tokens, `var(--terminal-font-mono)`, `border-radius: 0`). The left column embeds `CalibrationPanel.svelte` from `$lib/components/portfolio/` -- this component and its children still use the legacy `--ii-*` token system, `"Urbanist"` font, rounded corners, and `@investintell/ui` Select/Button/Tabs components. The `+page.svelte` currently papers over the mismatch with `:global` overrides (lines 210-241).

**Decision (already made):** Refactor CalibrationPanel IN-PLACE. The `(app)/` routes become read-only in Phase 9, so maintaining two versions is waste.

### Key files

| File | Role |
|---|---|
| `frontends/wealth/src/lib/components/portfolio/CalibrationPanel.svelte` | Main 63-input calibration surface (828 lines) |
| `frontends/wealth/src/lib/components/portfolio/CalibrationSliderField.svelte` | Paired slider + numeric input (260 lines) |
| `frontends/wealth/src/lib/components/portfolio/CalibrationSelectField.svelte` | Dropdown field using `@investintell/ui` Select (90 lines) |
| `frontends/wealth/src/lib/components/portfolio/CalibrationToggleField.svelte` | Boolean toggle (121 lines) |
| `frontends/wealth/src/lib/components/portfolio/CalibrationScenarioGroup.svelte` | 4-checkbox stress scenario selector (165 lines) |
| `frontends/wealth/src/lib/components/terminal/builder/RiskTab.svelte` | Zone E RISK tab with inline ECharts options (249 lines) |
| `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` | Builder page with `:global` overrides to remove |
| `packages/investintell-ui/src/lib/tokens/terminal.css` | Token source of truth |
| `packages/investintell-ui/src/lib/charts/terminal-options.ts` | `createTerminalChartOptions()` factory |

### Reference patterns (already terminal-native)

| Pattern | Reference file |
|---|---|
| Terminal button (`rc-btn`) | `frontends/wealth/src/lib/components/terminal/builder/RunControls.svelte` |
| Terminal select (`builder-select`) | `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` lines 192-203 |
| Terminal tab (`builder-tab`) | `frontends/wealth/src/routes/(terminal)/portfolio/builder/+page.svelte` lines 269-295 |
| Square badge (no radius) | `frontends/wealth/src/lib/components/terminal/builder/RegimeContextStrip.svelte` `.rcs-badge` lines 136-143 |
| Flat stress track (no radius) | `RegimeContextStrip.svelte` `.rcs-stress-track` / `.rcs-stress-fill` lines 165-172 |

---

## OBJECTIVE

Convert all 5 CalibrationPanel family components from the legacy `--ii-*` / Urbanist / rounded aesthetic to the terminal dialect. Refactor RiskTab to route charts through the `createTerminalChartOptions()` factory. Remove the `:global` overrides from `+page.svelte` that are no longer needed.

---

## CONSTRAINTS

1. **No new files.** All changes are edits to existing files.
2. **No logic changes.** Every `$state`, `$derived`, `$effect`, `$props`, event handler, and data flow stays exactly as-is. This is a pure visual/import refactor.
3. **No `@investintell/ui` component imports in the final CalibrationPanel family.** The only allowed imports from `@investintell/ui` are formatter functions (`formatNumber`, `formatPercent`, `formatBps`, `formatShortDate`) and `readTerminalTokens`.
4. **Zero `--ii-*` tokens** in the 5 CalibrationPanel files after refactor.
5. **Zero `border-radius > 0`** except: (a) native `<input type="range">` slider thumb (circular for usability), and (b) CalibrationToggleField toggle slider/knob (`border-radius: 999px` -- standard toggle switch idiom, not decorative).
6. **Zero hex literals** in the 5 CalibrationPanel files. All colors via `var(--terminal-*)` tokens.
7. **Zero `"Urbanist"` font references.** All replaced with `var(--terminal-font-mono)`.
8. **Svelte 5 syntax only.** `$state`, `$derived`, `$props` -- no legacy `export let`.
9. **Do NOT remove any methods, props, or event handlers** from any component.
10. **Do NOT touch** `CalibrationPanel.svelte` script logic (lines 25-272). Only modify the template (lines 273-611) and style block (lines 613-828).

---

## DELIVERABLES

### 1. CalibrationPanel.svelte

#### 1a. Import changes (script block)

Remove these imports:
```svelte
import {
    EmptyState,
    Button,
    formatNumber,
    formatShortDate,
} from "@investintell/ui";
import * as Tabs from "@investintell/ui/components/ui/tabs";
```

Replace with:
```svelte
import { formatNumber, formatShortDate } from "@investintell/ui";
```

(EmptyState, Button, and Tabs are no longer used -- they are replaced by terminal-native HTML elements.)

#### 1b. Template changes

**EmptyState replacement (3 instances, lines 274-294):**

Replace each `<EmptyState title="..." message="..." />` with a terminal-native empty state div:

```svelte
{#if !workspace.portfolio}
    <div class="cp-empty">
        <div class="cp-empty-block">
            <span class="cp-empty-title">NO PORTFOLIO SELECTED</span>
            <span class="cp-empty-msg">Select a model portfolio on the left to edit its calibration.</span>
        </div>
    </div>
{:else if loading && !draft}
    <div class="cp-empty">
        <div class="cp-empty-block">
            <span class="cp-empty-title">LOADING CALIBRATION</span>
            <span class="cp-empty-msg">Fetching the 63-input surface from the backend.</span>
        </div>
    </div>
{:else if !draft}
    <div class="cp-empty">
        <div class="cp-empty-block">
            <span class="cp-empty-title">CALIBRATION UNAVAILABLE</span>
            <span class="cp-empty-msg">{workspace.lastError?.message ?? "Calibration could not be loaded for this portfolio."}</span>
        </div>
    </div>
```

**Regime badge (line 305) -- pill to square:**

Replace:
```svelte
<span class="cp-regime-badge" style="background: {regimeColor}; color: #0e0f13">
```
With:
```svelte
<span class="cp-regime-badge" style="background: {regimeColor}; color: var(--terminal-fg-inverted)">
```

**Tabs.Root/Tabs.List/Tabs.Trigger/Tabs.Content replacement (lines 321-563):**

Replace the entire `<Tabs.Root>` block with terminal-native tabs matching the `builder-tab` pattern:

```svelte
<div class="cp-tabs" role="tablist">
    <button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "basic"}
        aria-selected={tier === "basic"} onclick={() => (tier = "basic")}>BASIC</button>
    <button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "advanced"}
        aria-selected={tier === "advanced"} onclick={() => (tier = "advanced")}>ADVANCED</button>
    <button type="button" role="tab" class="cp-tab" class:cp-tab--active={tier === "expert"}
        aria-selected={tier === "expert"} onclick={() => (tier = "expert")}>EXPERT</button>
</div>

{#if tier === "basic"}
    <section class="cp-section" role="tabpanel">
        <!-- ... Basic tier fields (unchanged) ... -->
    </section>
{:else if tier === "advanced"}
    <section class="cp-section" role="tabpanel">
        <!-- ... Advanced tier fields (unchanged) ... -->
    </section>
{:else if tier === "expert"}
    <section class="cp-section" role="tabpanel">
        <!-- ... Expert tier fields (unchanged) ... -->
    </section>
{/if}
```

**Expert tier "Add" Button (line 552-558):**

Replace:
```svelte
<Button
    variant="outline"
    size="sm"
    onclick={addExpertKey}
    disabled={!newExpertKey.trim()}
>
    Add
</Button>
```

With terminal-native button:
```svelte
<button
    type="button"
    class="cp-expert-add-btn"
    onclick={addExpertKey}
    disabled={!newExpertKey.trim()}
>
    ADD
</button>
```

**Footer buttons (lines 584-608) -- replace 3 `<Button>` components:**

Replace the 3 `@investintell/ui` `<Button>` components with terminal-native buttons:

```svelte
<div class="cp-footer-actions">
    <button type="button" class="cp-action cp-action--ghost"
        disabled={!dirty || applying || isPreviewing}
        onclick={handleReset}>RESET</button>
    <button type="button" class="cp-action cp-action--outline"
        disabled={!dirty || applying || isPreviewing}
        onclick={schedulePreview}>PREVIEW</button>
    <button type="button" class="cp-action cp-action--primary"
        disabled={!dirty || applying || isPreviewing}
        onclick={handleApply}>APPLY</button>
</div>
```

#### 1c. Complete token mapping table (style block)

Every `--ii-*` token occurrence and its replacement:

| Current (old) | Replacement (new) | Occurrences |
|---|---|---|
| `#141519` | `var(--terminal-bg-panel)` | 2 (`.cp-root`, `.cp-footer`) |
| `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` | 1 (`.cp-root`) |
| `var(--ii-border-subtle, rgba(64, 66, 73, 0.4))` | `var(--terminal-border-hairline)` | 3 (`.cp-regime-strip`, `.cp-footer`, `.cp-expert-add`) |
| `var(--ii-border-subtle, rgba(64, 66, 73, 0.6))` | `var(--terminal-border-hairline)` | 1 (`.cp-expert-input`) |
| `var(--ii-text-muted, #85a0bd)` | `var(--terminal-fg-muted)` | 7 (`.cp-regime-kicker`, `.cp-regime-date`, `.cp-regime-posture`, `.cp-expert-hint`, `.cp-expert-empty`, `.cp-expert-value`, `.cp-expert-remove`) |
| `var(--ii-text-primary, #ffffff)` | `var(--terminal-fg-primary)` | 2 (`.cp-expert-key`, `.cp-expert-input`) |
| `var(--ii-primary, #0177fb)` | `var(--terminal-accent-amber)` | 1 (`.cp-expert-input:focus`) |
| `var(--ii-danger, #fc1a1a)` | `var(--terminal-status-error)` | 1 (`.cp-expert-remove:hover`) |
| `var(--ii-warning, #f0a020)` | `var(--terminal-status-warn)` | 1 (`.cp-status--dirty`) |
| `var(--ii-primary, #0177fb)` (status) | `var(--terminal-accent-cyan)` | 1 (`.cp-status--pending`) |
| `var(--ii-danger, #fc1a1a)` (status) | `var(--terminal-status-error)` | 1 (`.cp-status--error`) |
| `var(--ii-text-muted, #85a0bd)` (status) | `var(--terminal-fg-muted)` | 1 (`.cp-status--clean`) |
| `rgba(255, 255, 255, 0.06)` | `var(--terminal-bg-panel-raised)` | 2 (`.cp-expert-hint code`, `.cp-expert-remove:hover`) |
| `rgba(255, 255, 255, 0.02)` | `var(--terminal-bg-panel-sunken)` | 1 (`.cp-expert-row`) |
| `border-radius: 999px` | removed (0) | 1 (`.cp-regime-badge`) |
| `border-radius: 3px` | removed (0) | 2 (`.cp-stress-bar-track`, `.cp-stress-bar-fill`) |
| `border-radius: 6px` | removed (0) | 2 (`.cp-expert-row`, `.cp-expert-input`) |
| `border-radius: 4px` | removed (0) | 2 (`.cp-expert-hint code`, `.cp-expert-remove`) |

#### 1d. New/modified style rules

**Remove the `:global(.cp-tabs)` rule entirely** (line 686-691). Replace with the terminal tab styles:

```css
.cp-tabs {
    display: flex;
    align-items: stretch;
    height: 32px;
    padding: 0;
    flex-shrink: 0;
    border-bottom: var(--terminal-border-hairline);
}

.cp-tab {
    display: inline-flex;
    align-items: center;
    padding: 0 var(--terminal-space-3);
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    font-weight: 600;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
    cursor: pointer;
    transition:
        color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
        border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out);
}

.cp-tab:hover {
    color: var(--terminal-accent-amber);
}

.cp-tab--active {
    color: var(--terminal-accent-amber);
    border-bottom-color: var(--terminal-accent-amber);
}

.cp-tab:focus-visible {
    outline: var(--terminal-border-focus);
    outline-offset: -2px;
}
```

**New empty state styles:**

```css
.cp-empty-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--terminal-space-2);
}
.cp-empty-title {
    font-size: var(--terminal-text-11);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    color: var(--terminal-fg-tertiary);
}
.cp-empty-msg {
    font-size: var(--terminal-text-11);
    color: var(--terminal-fg-muted);
    text-align: center;
    max-width: 280px;
    line-height: var(--terminal-leading-normal);
}
```

**New expert "Add" button style:**

```css
.cp-expert-add-btn {
    height: 28px;
    padding: 0 var(--terminal-space-3);
    background: transparent;
    color: var(--terminal-fg-secondary);
    border: var(--terminal-border-hairline);
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    cursor: pointer;
}
.cp-expert-add-btn:hover:not(:disabled) {
    color: var(--terminal-accent-amber);
    border-color: var(--terminal-accent-amber);
}
.cp-expert-add-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
```

**New footer action button styles:**

```css
.cp-action {
    height: 28px;
    padding: 0 var(--terminal-space-3);
    border: none;
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    cursor: pointer;
    transition:
        background var(--terminal-motion-tick) var(--terminal-motion-easing-out),
        color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
        opacity var(--terminal-motion-tick) var(--terminal-motion-easing-out);
}
.cp-action:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.cp-action:focus-visible {
    outline: var(--terminal-border-focus);
    outline-offset: 2px;
}
.cp-action--ghost {
    background: transparent;
    color: var(--terminal-fg-tertiary);
}
.cp-action--ghost:hover:not(:disabled) {
    color: var(--terminal-fg-primary);
}
.cp-action--outline {
    background: transparent;
    color: var(--terminal-fg-secondary);
    border: var(--terminal-border-hairline);
}
.cp-action--outline:hover:not(:disabled) {
    color: var(--terminal-accent-amber);
    border-color: var(--terminal-accent-amber);
}
.cp-action--primary {
    background: var(--terminal-accent-amber);
    color: var(--terminal-fg-inverted);
}
.cp-action--primary:hover:not(:disabled) {
    opacity: 0.9;
}
```

**Regime badge (square):**
```css
.cp-regime-badge {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    font-size: var(--terminal-text-10);
    font-weight: 700;
    letter-spacing: var(--terminal-tracking-caps);
    text-transform: uppercase;
    white-space: nowrap;
}
```

**Stress bar (flat, no radius):**
```css
.cp-stress-bar-track {
    flex: 1;
    height: 4px;
    background: var(--terminal-fg-muted);
    overflow: hidden;
}
.cp-stress-bar-fill {
    height: 100%;
    transition: width var(--terminal-motion-update) var(--terminal-motion-easing-out);
}
```

**`.cp-empty` update:**
```css
.cp-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--terminal-space-6);
    height: 100%;
    font-family: var(--terminal-font-mono);
    background: var(--terminal-bg-panel);
}
```

---

### 2. CalibrationSliderField.svelte

#### 2a. Import changes

No import changes needed. `formatPercent`, `formatNumber`, `formatBps` from `@investintell/ui` are formatter functions (allowed).

#### 2b. Complete token mapping

| Current (old) | Replacement (new) |
|---|---|
| `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` |
| `var(--ii-text-primary, #ffffff)` | `var(--terminal-fg-primary)` |
| `var(--ii-primary, #0177fb)` | `var(--terminal-accent-amber)` |
| `var(--ii-danger, #fc1a1a)` | `var(--terminal-status-error)` |
| `var(--ii-success, #3fb950)` | `var(--terminal-status-success)` |
| `var(--ii-text-muted, #85a0bd)` | `var(--terminal-fg-muted)` |
| `var(--ii-border-subtle, rgba(64, 66, 73, 0.6))` | `var(--terminal-border-hairline)` |
| `rgba(64, 66, 73, 0.6)` (slider track) | `var(--terminal-fg-muted)` |
| `#1a1b20` (slider thumb bg) | `var(--terminal-bg-panel)` |
| `border-radius: 999px` (slider track) | removed (0) |
| `border-radius: 50%` (slider thumb) | **KEEP** -- native slider thumb stays circular |
| `border-radius: 6px` (number input) | removed (0) |
| `rgba(1, 119, 251, 0.2)` (focus ring) | `color-mix(in srgb, var(--terminal-accent-amber) 25%, transparent)` |

**Critical:** The slider thumb `border-radius: 50%` is the ONLY allowed exception to the zero-radius rule. Native range input thumbs must remain circular for usability.

#### 2c. Slider thumb border color

Change from `--ii-primary` (blue) to `--terminal-accent-amber`:
```css
.csf-slider::-webkit-slider-thumb {
    border: 2px solid var(--terminal-accent-amber);
}
.csf-slider::-moz-range-thumb {
    border: 2px solid var(--terminal-accent-amber);
}
```

#### 2d. Number input border

Change from `border: 1px solid var(--ii-border-subtle, ...)` to `border: var(--terminal-border-hairline)` and `border-radius: 0`:
```css
.csf-number {
    /* ... */
    border: var(--terminal-border-hairline);
    border-radius: 0;
    /* ... */
}
.csf-number:focus {
    outline: none;
    border-color: var(--terminal-accent-amber);
}
```

---

### 3. CalibrationSelectField.svelte

#### 3a. Import changes

Remove:
```svelte
import { Select } from "@investintell/ui";
```

No replacement import needed -- using native `<select>`.

#### 3b. Template replacement

Replace the `<Select>` component (lines 49-55):
```svelte
<div class="csf-control">
    <Select
        {value}
        onValueChange={onChange}
        options={[...options]}
        {placeholder}
        {disabled}
    />
</div>
```

With terminal-native select:
```svelte
<div class="csf-control">
    <select
        {id}
        class="csf-select"
        {disabled}
        value={value}
        onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
    >
        {#each options as opt (opt.value)}
            <option value={opt.value}>{opt.label}</option>
        {/each}
    </select>
</div>
```

#### 3c. Complete token mapping

| Current (old) | Replacement (new) |
|---|---|
| `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` |
| `var(--ii-text-primary, #ffffff)` | `var(--terminal-fg-primary)` |
| `var(--ii-text-muted, #85a0bd)` | `var(--terminal-fg-muted)` |

#### 3d. New select style (matching `builder-select` pattern from +page.svelte)

```css
.csf-select {
    width: 100%;
    height: 28px;
    background: var(--terminal-bg-panel-sunken);
    color: var(--terminal-fg-primary);
    border: var(--terminal-border-hairline);
    border-radius: 0;
    font-family: var(--terminal-font-mono);
    font-size: var(--terminal-text-11);
    padding: 0 var(--terminal-space-2);
    cursor: pointer;
}
.csf-select:focus-visible {
    outline: var(--terminal-border-focus);
    outline-offset: 2px;
}
.csf-select:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
```

---

### 4. CalibrationToggleField.svelte

#### 4a. Complete token mapping

| Current (old) | Replacement (new) |
|---|---|
| `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` |
| `var(--ii-text-primary, #ffffff)` | `var(--terminal-fg-primary)` |
| `var(--ii-text-muted, #85a0bd)` | `var(--terminal-fg-muted)` |
| `rgba(64, 66, 73, 0.7)` (slider bg) | `var(--terminal-fg-muted)` |
| `#ffffff` (knob color) | `var(--terminal-fg-primary)` |
| `var(--ii-primary, #0177fb)` (checked bg) | `var(--terminal-accent-amber)` |
| `rgba(1, 119, 251, 0.25)` (focus ring) | `color-mix(in srgb, var(--terminal-accent-amber) 25%, transparent)` |
| `border-radius: 999px` (slider + knob) | **KEEP** -- toggle switches remain pill-shaped for usability (this is a standard toggle, not a decorative element) |

**Decision on toggle radius:** Toggle switches (`border-radius: 999px`) are a recognized native control idiom. Unlike decorative pills and badges, the circular toggle is a platform UX convention that must be preserved. This is the same reasoning as the range slider thumb exception.

---

### 5. CalibrationScenarioGroup.svelte

#### 5a. Complete token mapping

| Current (old) | Replacement (new) |
|---|---|
| `font-family: "Urbanist", system-ui, sans-serif` | `font-family: var(--terminal-font-mono)` |
| `var(--ii-text-primary, #ffffff)` | `var(--terminal-fg-primary)` |
| `var(--ii-text-muted, #85a0bd)` | `var(--terminal-fg-muted)` |
| `var(--ii-border-subtle, rgba(64, 66, 73, 0.6))` | `var(--terminal-border-hairline)` |
| `var(--ii-primary, #0177fb)` | `var(--terminal-accent-amber)` |
| `rgba(1, 119, 251, 0.08)` (chip selected bg) | `color-mix(in srgb, var(--terminal-accent-amber) 10%, transparent)` |
| `rgba(255, 255, 255, 0.03)` (chip hover bg) | `var(--terminal-bg-panel-raised)` |
| `rgba(255, 255, 255, 0.28)` (checkbox border) | `var(--terminal-fg-tertiary)` |
| `#ffffff` (tick color) | `var(--terminal-fg-inverted)` |
| `border-radius: 8px` (chip) | removed (0) |
| `border-radius: 4px` (checkbox box) | removed (0) |

---

### 6. RiskTab.svelte -- Factory Migration

The current RiskTab builds two EChartsOption objects inline, using `readTerminalTokens()` directly. This bypasses the `createTerminalChartOptions()` factory, missing the standard tooltip chrome, animation wiring, and choreo integration.

#### 6a. Import changes

Add `createTerminalChartOptions` import:
```svelte
import { formatNumber, readTerminalTokens, createTerminalChartOptions } from "@investintell/ui";
```

Remove `type { EChartsOption }` import -- the factory returns the correct type.

**Wait -- re-check.** The current RiskTab uses `EChartsOption` as a type annotation for its derived values. Keep the type import:
```svelte
import type { EChartsOption } from "echarts";
import { formatNumber, readTerminalTokens, createTerminalChartOptions } from "@investintell/ui";
```

#### 6b. CVaR stacked bar -- factory migration

The CVaR chart is a horizontal stacked bar with custom grid (no axes visible). Use `createTerminalChartOptions()` with axis/grid overrides:

**Before (current inline, lines 53-79):**
```typescript
const cvarOption = $derived.by<EChartsOption>(() => {
    if (!hasCvar) return {};
    const total = cvarContributions.reduce((sum, c) => sum + c.value, 0);
    return {
        textStyle: { fontFamily: tk.fontMono, fontSize: tk.text10 },
        grid: { left: 0, right: 0, top: 0, bottom: 0 },
        tooltip: { ... },
        xAxis: { type: "value", show: false, max: total },
        yAxis: { type: "category", show: false, data: ["Tail Loss"] },
        animation: false,
        series: cvarContributions.map((c, i) => ({ ... })),
    };
});
```

**After (factory-driven):**
```typescript
const cvarOption = $derived.by<EChartsOption>(() => {
    if (!hasCvar) return {};
    const tk = readTerminalTokens();
    const total = cvarContributions.reduce((sum, c) => sum + c.value, 0);

    return createTerminalChartOptions({
        slot: "secondary",
        disableAnimation: true,
        showXAxisLabels: false,
        showYAxisLabels: false,
        xAxis: { type: "value" as const, show: false, max: total },
        yAxis: { type: "category" as const, show: false, data: ["Tail Loss"] },
        series: cvarContributions.map((c, i) => ({
            type: "bar" as const,
            stack: "cvar",
            barWidth: "100%",
            data: [c.value],
            name: c.name,
            itemStyle: { color: tk.dataviz[i % tk.dataviz.length] },
        })),
    });
});
```

Note: the factory's default grid (left: 44, right: 16, etc.) is wrong for this flush stacked bar. Apply a grid override. Check if `createTerminalChartOptions` merges grid. **It does not currently expose a `grid` override.** Two options:

**Option A (preferred):** Spread the factory result and override grid:
```typescript
const base = createTerminalChartOptions({ ... });
return { ...base, grid: { left: 0, right: 0, top: 0, bottom: 0 } };
```

**Option B:** Keep the inline option but ensure it uses factory-standard tooltip/textStyle patterns. **Use Option A.**

#### 6c. Factor exposure bar -- factory migration

**Before (current inline, lines 101-165):**
```typescript
const factorOption = $derived.by<EChartsOption>(() => {
    // ... inline with readTerminalTokens() for all colors
});
```

**After (factory-driven):**
```typescript
const factorOption = $derived.by<EChartsOption>(() => {
    if (!hasFactors) return {};
    const tk = readTerminalTokens();
    const labels = factorExposures.map((e) => e.label);
    const values = factorExposures.map((e) => Math.round(e.value * 1000) / 1000);

    const base = createTerminalChartOptions({
        slot: "secondary",
        xAxis: {
            type: "value" as const,
            axisLabel: {
                formatter: (v: number) => formatNumber(v, 1),
            },
        },
        yAxis: {
            type: "category" as const,
            data: labels,
            inverse: true,
            axisLabel: { fontWeight: 600 as const },
            axisTick: { show: false },
            axisLine: { show: false },
        },
        series: [
            {
                type: "bar" as const,
                barWidth: "55%",
                data: values.map((v) => ({
                    value: v,
                    itemStyle: {
                        color: v >= 0 ? tk.accentCyan : tk.accentAmber,
                    },
                })),
                label: {
                    show: true,
                    position: "right" as const,
                    fontSize: tk.text10,
                    fontWeight: 600 as const,
                    color: tk.fgPrimary,
                },
                markLine: {
                    silent: true,
                    symbol: "none" as const,
                    data: [{ xAxis: 0 }],
                    lineStyle: { color: tk.fgTertiary, type: "solid" as const, width: 1 },
                    label: { show: false },
                },
            },
        ],
    });

    return { ...base, grid: { left: 130, right: 50, top: 12, bottom: 24 } };
});
```

#### 6d. Remove top-level `tk` derived

The current file has `const tk = $derived.by(() => readTerminalTokens());` at line 29. Since both chart deriveds now call `readTerminalTokens()` inline (or via the factory), and `tk` is no longer used elsewhere in the template/style, **remove the top-level `tk` derived** to avoid a stale reference.

**Actually -- verify.** Check if `tk` is used in the template. Scanning lines 170-248: no `tk` references in template or style. Only in the two chart option deriveds. Confirmed safe to remove. The two chart options now call `readTerminalTokens()` locally where needed for series colors.

---

### 7. builder/+page.svelte -- Remove `:global` overrides

Remove lines 210-240 (the entire block of `:global` overrides for CalibrationPanel):

```css
/* REMOVE THIS ENTIRE BLOCK: */

/* Terminal overrides for CalibrationPanel */
.builder-calibration {
    flex: 1;
    overflow-y: auto;
    border-bottom: var(--terminal-border-hairline);

    /* Override @investintell/ui rounded corners */
    --ii-radius-md: 0px;
    --ii-radius-sm: 0px;
    --ii-radius-lg: 0px;
    --ii-radius-xl: 0px;
    font-family: var(--terminal-font-mono);
}

/* Deep scoped overrides for CalibrationPanel child elements */
.builder-calibration :global(button) {
    border-radius: var(--terminal-radius-none);
}

.builder-calibration :global([data-slot="tablist"]) {
    border-radius: var(--terminal-radius-none);
}

.builder-calibration :global([data-slot="trigger"]) {
    border-radius: var(--terminal-radius-none);
    font-family: var(--terminal-font-mono);
}

.builder-calibration :global([data-slot="content"]) {
    border-radius: var(--terminal-radius-none);
}
```

**Replace with the minimal structural rule only:**

```css
.builder-calibration {
    flex: 1;
    overflow-y: auto;
    border-bottom: var(--terminal-border-hairline);
}
```

The `--ii-radius-*` overrides and `:global` selectors are no longer needed because CalibrationPanel now uses terminal tokens natively.

---

## VERIFICATION

After all changes, run these validation steps:

### 1. Zero `--ii-` tokens in modified files
```bash
cd frontends/wealth
grep -rn "\-\-ii-" src/lib/components/portfolio/CalibrationPanel.svelte \
  src/lib/components/portfolio/CalibrationSliderField.svelte \
  src/lib/components/portfolio/CalibrationSelectField.svelte \
  src/lib/components/portfolio/CalibrationToggleField.svelte \
  src/lib/components/portfolio/CalibrationScenarioGroup.svelte
```
**Expected:** zero matches.

### 2. Zero `border-radius` > 0 (except native controls)
```bash
cd frontends/wealth
grep -n "border-radius" src/lib/components/portfolio/CalibrationPanel.svelte \
  src/lib/components/portfolio/CalibrationSelectField.svelte \
  src/lib/components/portfolio/CalibrationScenarioGroup.svelte
```
**Expected:** zero matches in these files.

```bash
grep -n "border-radius" src/lib/components/portfolio/CalibrationSliderField.svelte
```
**Expected:** only `border-radius: 50%` on slider thumb (2 occurrences -- webkit + moz).

```bash
grep -n "border-radius" src/lib/components/portfolio/CalibrationToggleField.svelte
```
**Expected:** only `border-radius: 999px` on toggle slider/knob (2 occurrences -- `.ctf-slider` and `.ctf-slider::before`).

### 3. Zero hex literals in CalibrationPanel family
```bash
cd frontends/wealth
grep -En "#[0-9a-fA-F]{3,8}" src/lib/components/portfolio/CalibrationPanel.svelte \
  src/lib/components/portfolio/CalibrationSliderField.svelte \
  src/lib/components/portfolio/CalibrationSelectField.svelte \
  src/lib/components/portfolio/CalibrationToggleField.svelte \
  src/lib/components/portfolio/CalibrationScenarioGroup.svelte
```
**Expected:** zero matches.

### 4. Zero "Urbanist" in CalibrationPanel family
```bash
cd frontends/wealth
grep -rn "Urbanist" src/lib/components/portfolio/Calibration*.svelte
```
**Expected:** zero matches.

### 5. Zero `:global` overrides for CalibrationPanel in builder page
```bash
grep -n ":global" src/routes/\(terminal\)/portfolio/builder/+page.svelte
```
**Expected:** zero matches.

### 6. No `@investintell/ui` component imports (only formatters allowed)
```bash
grep -n "from \"@investintell/ui\"" src/lib/components/portfolio/CalibrationPanel.svelte
```
**Expected:** one match containing only `formatNumber, formatShortDate`.

```bash
grep -n "from \"@investintell/ui\"" src/lib/components/portfolio/CalibrationSelectField.svelte
```
**Expected:** zero matches (Select import removed, no formatters used).

```bash
grep -n "@investintell/ui/components" src/lib/components/portfolio/CalibrationPanel.svelte
```
**Expected:** zero matches (Tabs import removed).

### 7. Type check
```bash
cd frontends/wealth && pnpm check
```
**Expected:** zero errors.

### 8. RiskTab factory usage
```bash
grep -n "createTerminalChartOptions" src/lib/components/terminal/builder/RiskTab.svelte
```
**Expected:** 2 matches (one per chart option derived).

---

## ANTI-PATTERNS

1. **Do NOT create new files.** No `CalibrationPanelTerminal.svelte` or `CalibrationPanelV2.svelte`. In-place refactor only.
2. **Do NOT change any props, event handlers, or data flow.** The `update()`, `diffPatch()`, `handleApply()`, `schedulePreview()`, `handleReset()`, `addExpertKey()`, `removeExpertKey()` functions must remain byte-identical.
3. **Do NOT introduce new `@investintell/ui` component imports.** The migration direction is away from `@investintell/ui` components, toward terminal-native HTML.
4. **Do NOT use `rgba()` or `hsla()` in component styles.** Use `var(--terminal-*)` tokens or `color-mix()` for opacity variants.
5. **Do NOT add new CSS custom properties.** All needed tokens already exist in `terminal.css`.
6. **Do NOT remove the `formatNumber`, `formatPercent`, `formatBps`, `formatShortDate` imports.** These are formatter functions (DL16 discipline), not components.
7. **Do NOT change the `.cp-section` overflow behavior.** It must remain `overflow-y: auto` for scrollable calibration content.
8. **Do NOT touch RiskTab's data derivation logic** (lines 32-98). Only change the chart option construction (lines 53-79, 101-165).

---

## COMMIT

```
refactor(builder): terminal-ize CalibrationPanel — replace ii tokens, Urbanist, rounded corners, @investintell/ui components

- CalibrationPanel.svelte: replace EmptyState/Button/Tabs with terminal-native HTML,
  migrate all --ii-* to --terminal-*, replace #141519 with var(--terminal-bg-panel),
  square regime badge + flat stress bar
- CalibrationSliderField.svelte: terminal tokens + amber accent on slider thumb
- CalibrationSelectField.svelte: replace @investintell/ui Select with native <select>
- CalibrationToggleField.svelte: terminal tokens + amber toggle
- CalibrationScenarioGroup.svelte: terminal tokens + square chips
- RiskTab.svelte: route both charts through createTerminalChartOptions() factory
- builder/+page.svelte: remove :global CalibrationPanel overrides (no longer needed)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
