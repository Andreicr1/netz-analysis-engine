---
title: "refactor: Wealth frontend 100% shadcn/ui migration"
type: refactor
status: active
date: 2026-04-02
origin: docs/audit/shadcn-ui-gap-analysis.md
---

# refactor: Wealth Frontend 100% shadcn/ui Migration

## Overview

Systematically replace ALL custom/ad-hoc UI primitive implementations in `frontends/wealth/` with official shadcn/ui components from `@investintell/ui/components/ui/`. The package already ships 55 shadcn/ui directories (bits-ui based) — only 9 are used. Current adoption rate: 16%. Target: 100%.

This also includes refactoring the `@investintell/ui` analytical wrapper layer (`packages/investintell-ui/src/lib/components/`) to use shadcn primitives internally instead of raw HTML.

**Guiding principle:** Official library components over custom generic ones. No mixing.

**Expanded scope (2026-04-02):** Also migrate the foundational design tokens (typography, color palette, button variants) to match the official shadcn/ui design system, replacing the current custom `--ii-*` token values.

**Package clarification:**
- `packages/investintell-ui/` (`@investintell/ui`) — **ACTIVE** package. Has 55 shadcn/ui dirs, `--ii-*` tokens, used by Wealth frontend.
- `packages/ui/` (`@netz/ui`) — **LEGACY** package. Zero imports in Wealth. Not in scope.

## Problem Statement

The Wealth frontend has two parallel UI systems:
1. **shadcn/ui primitives** in `packages/investintell-ui/src/lib/components/ui/` — 55 directories, bits-ui based, ready to use
2. **Custom implementations** in both `packages/investintell-ui/src/lib/components/` (wrapper layer) and `frontends/wealth/src/lib/components/` — raw HTML, manual keyboard nav, custom CSS animations

This creates:
- Inconsistent interaction patterns (custom tabs behave differently from shadcn tabs)
- Duplicated accessibility logic (manual `onkeydown`, `click-outside` detection)
- Visual inconsistency (custom popovers, spinners, scroll behaviors differ across pages)
- Maintenance burden (two implementations for every primitive)

## Technical Approach

### Three-Layer Migration

**Layer 0 — Design token foundation** (`packages/investintell-ui/src/lib/styles/`):
Migrate typography, color palette, and button variants to match shadcn/ui official design system. All downstream components inherit the new tokens.

**Layer 1 — Direct replacements in Wealth frontend** (`frontends/wealth/src/`):
Replace inline custom patterns with shadcn/ui imports.

**Layer 2 — Wrapper refactoring in @investintell/ui** (`packages/investintell-ui/src/lib/components/`):
Refactor analytical wrappers to compose shadcn primitives internally. External API stays the same — consumers don't change.

### Import Convention (Post-Migration)

```svelte
<!-- Shadcn primitives — always from /components/ui/ -->
import { Button } from "@investintell/ui/components/ui/button";
import { Tabs } from "@investintell/ui/components/ui/tabs";
import { Sheet } from "@investintell/ui/components/ui/sheet";

<!-- Analytical wrappers — from barrel (these internally compose shadcn) -->
import { DataTable, MetricCard, PeriodSelector } from "@investintell/ui";
```

---

## Implementation Phases

### Phase 0: Design Token Foundation (High Impact, Foundation for Everything)

Migrate the `--netz-*` CSS custom property system to align with the official shadcn/ui design system. This phase MUST complete before component migration — all components inherit these tokens.

#### 0.1 — Typography: IBM Plex Sans → Inter

**Figma spec (shadcn/ui official):**

| Element | Font | Weight | Size | Line Height | Letter Spacing |
|---------|------|--------|------|-------------|----------------|
| **h1** | Inter | ExtraBold (800) | 48px | 48px (1.0) | -1.2px (-0.025em) |
| **h2** | Inter | SemiBold (600) | 30px | 36px (1.2) | -0.75px (-0.025em) |
| **h3** | Inter | SemiBold (600) | 24px | 32px (1.33) | -0.6px (-0.025em) |
| **h4** | Inter | SemiBold (600) | 20px | 28px (1.4) | -0.5px (-0.025em) |
| **p** | Inter | Regular (400) | 16px | 28px (1.75) | 0 |
| **lead** | Inter | Regular (400) | 20px | 28px (1.4) | 0 |
| **large** | Inter | SemiBold (600) | 18px | 28px (1.56) | 0 |
| **small** | Inter | Medium (500) | 14px | 14px (1.0) | 0 |
| **subtle/muted** | Inter | Regular (400) | 14px | 20px (1.43) | 0 |
| **blockquote** | Inter | Italic (400) | 16px | 24px (1.5) | 0 |
| **inline code** | Menlo | Bold (700) | 14px | 20px (1.43) | 0 |
| **table head** | Inter | Bold (700) | 16px | 24px (1.5) | 0 |
| **table body** | Inter | Regular (400) | 16px | 24px (1.5) | 0 |
| **body-medium** | Inter | Medium (500) | 14px | 24px (1.71) | 0 |

**Current system (`packages/investintell-ui/src/lib/styles/typography.css`):**
- Font: `--ii-font-sans: "IBM Plex Sans"` → change to `"Inter Variable", "Inter", ui-sans-serif, system-ui, sans-serif`
- Font: `--ii-font-mono: "IBM Plex Mono"` → change to `"Geist Mono", "Menlo", ui-monospace, monospace`
- Font weights: keep `--ii-weight-normal` (400), `--ii-weight-medium` (500), `--ii-weight-semibold` (600), `--ii-weight-bold` (700); **add** `--ii-weight-extrabold` (800) for h1
- Font sizes: realign `--ii-text-h1` (30px → 48px), `--ii-text-h2` (26px → 30px), `--ii-text-h3` (22px → 24px)
- Tracking: Inter has slightly different metrics — `--ii-tracking-h1` stays at -0.025em (matches Figma spec)
- Font features: `"tnum" 1` (tabular numerals) MUST stay — financial data needs aligned columns. Inter supports tnum.

**Files to modify:**
- [ ] `packages/investintell-ui/src/lib/styles/typography.css` — font family declarations, size scale, weight scale, @fontsource imports
- [ ] `packages/investintell-ui/package.json` — swap `@fontsource/ibm-plex-sans` / `@fontsource/ibm-plex-mono` for `@fontsource-variable/inter` / `@fontsource-variable/geist-mono`
- [ ] `packages/investintell-ui/src/lib/styles/globals.css` — any font references

**Migration strategy:** Change the CSS variable values. All consumers reference `--ii-font-sans` — they don't hardcode font names. Single point of change.

#### 0.2 — Color Palette: Institutional Blue → Tailwind Slate

**Figma spec (shadcn/ui official Slate palette):**

| Token | Hex | Usage |
|-------|-----|-------|
| slate-50 | `#f8fafc` | Lightest bg |
| slate-100 | `#f1f5f9` | Subtle bg, hover |
| slate-200 | `#e2e8f0` | Borders, dividers |
| slate-300 | `#cbd5e1` | Strong borders |
| slate-400 | `#94a3b8` | Placeholder text |
| slate-500 | `#64748b` | Muted text |
| slate-600 | `#475569` | Secondary text |
| slate-700 | `#334155` | Button hover bg |
| slate-800 | `#1e293b` | Dark surfaces |
| slate-900 | `#0f172a` | Primary text, default button bg |

**Current system (dark-first Zinc + Gold) → Target (shadcn Slate-based):**

The current `@investintell/ui` uses a **dark-first** design with Zinc neutral + Gold accent (`#c9a84c`). shadcn/ui standard is **light-first** with Slate neutral. The dark mode in the Figma reference uses Slate dark values.

**Light mode mapping (`[data-theme="light"]`):**

| Current `--ii-*` Token | Current Value | Target (Slate-based) | Notes |
|---|---|---|---|
| `--ii-brand-primary` | `#9a7a2e` (gold) | `#0f172a` (slate-900) | Primary action = dark |
| `--ii-brand-secondary` | `#0f6b5a` (teal) | `#475569` (slate-600) | Secondary |
| `--ii-text-primary` | `#18181b` (zinc-950) | `#0f172a` (slate-900) | Very close |
| `--ii-text-secondary` | `#3f3f46` (zinc-700) | `#475569` (slate-600) | Warmer gray |
| `--ii-text-muted` | `#71717a` (zinc-500) | `#64748b` (slate-500) | Very close |
| `--ii-text-tertiary` | `#a1a1aa` (zinc-400) | `#94a3b8` (slate-400) | Very close |
| `--ii-bg` | `#fafafa` (zinc-50) | `#ffffff` (white) | Slightly lighter |
| `--ii-surface` | `#ffffff` | `#ffffff` | Match |
| `--ii-surface-alt` | `#f4f4f5` (zinc-100) | `#f1f5f9` (slate-100) | Cool shift |
| `--ii-surface-inset` | `#e4e4e7` (zinc-200) | `#f1f5f9` (slate-100) | Lighter |
| `--ii-border` | `#d4d4d8` (zinc-300) | `#e2e8f0` (slate-200) | Lighter |
| `--ii-border-subtle` | `#e4e4e7` (zinc-200) | `#e2e8f0` (slate-200) | Very close |
| `--ii-border-strong` | `#a1a1aa` (zinc-400) | `#cbd5e1` (slate-300) | Lighter |
| `--ii-border-focus` | `#9a7a2e` (gold) | `#0f172a` (slate-900) | Neutral focus |
| `--ii-danger` | `#da3633` | `#ef4444` (red-500) | Brighter |
| `--ii-success` | `#2ea043` | Keep (close enough) | |
| `--ii-warning` | `#d29922` | Keep | |

**Dark mode mapping (`:root`):**

| Current `--ii-*` Token | Current Value | Target (Slate dark) | Notes |
|---|---|---|---|
| `--ii-brand-primary` | `#c9a84c` (gold) | `#f8fafc` (slate-50) or keep gold? | **Decision needed** |
| `--ii-bg` | `#18181b` (zinc-950) | `#020817` (slate-950) | Darker, cooler |
| `--ii-surface` | `#1c1c1f` (zinc-900) | `#0f172a` (slate-900) | Cooler |
| `--ii-surface-alt` | `#27272a` (zinc-800) | `#1e293b` (slate-800) | Cooler |
| `--ii-border` | `#3f3f46` (zinc-700) | `#1e293b` (slate-800) | Subtler |
| `--ii-text-primary` | `#e4e4e7` (zinc-200) | `#f8fafc` (slate-50) | Brighter |
| `--ii-text-muted` | `#71717a` (zinc-500) | `#94a3b8` (slate-400) | Cooler |

**Key decision:** Keep `--ii-*` CSS variable NAMES. Only change VALUES. Zero changes in consuming components.

**Decision: Remove gold entirely.** The gold accent (`#c9a84c`) is removed from the entire system — buttons, accents, charts, focus rings, links. Full neutral Slate palette, matching shadcn/ui standard.

**Chart palette replacement (Slate-based, professional):**

| Token | Old (Gold/Teal) | New (Slate-based) | Rationale |
|---|---|---|---|
| `--ii-chart-1` | `#c9a84c` (gold) | `#0f172a` (slate-900) | Primary series — dark, authoritative |
| `--ii-chart-2` | `#26a88f` (teal) | `#64748b` (slate-500) | Secondary — medium contrast |
| `--ii-chart-3` | `#58a6ff` (blue) | `#94a3b8` (slate-400) | Tertiary — lighter |
| `--ii-chart-4` | `#e3b341` (amber) | `#cbd5e1` (slate-300) | Quaternary — subtle |
| `--ii-chart-5` | `#71717a` (zinc-500) | `#e2e8f0` (slate-200) | Benchmark/muted |

**Note:** A monochrome Slate chart palette may lack contrast for 5+ series. If needed, add a **cool blue accent** (`#3b82f6` blue-500) as `--ii-chart-accent` for emphasis series — this is standard in financial dashboards (Bloomberg, Refinitiv) and avoids the gold/luxury aesthetic.

**Files to modify:**
- [ ] `packages/investintell-ui/src/lib/styles/tokens.css` — all color variable values (dark + light mode) + shadcn bridge section + chart palette + focus/link/accent tokens

#### 0.3 — Button Variants: Custom Elevation → Standard shadcn Flat

**Figma spec (shadcn/ui official buttons):**

| Variant | Background | Text | Border | Hover |
|---------|-----------|------|--------|-------|
| **default** | `#0f172a` (slate-900) | white | none | `#334155` (slate-700) |
| **destructive** | `#ef4444` (red-500) | white | none | `#dc2626` (red-600) |
| **outline** | white | `#0f172a` (slate-900) | `#e2e8f0` (slate-200) | `#f1f5f9` (slate-100) bg |
| **subtle/secondary** | `#f1f5f9` (slate-100) | `#0f172a` (slate-900) | none | `#e2e8f0` (slate-200) |
| **ghost** | transparent | `#0f172a` (slate-900) | none | `#f1f5f9` (slate-100) bg |
| **link** | transparent | `#0f172a` (slate-900) | none | underline |

**Shared button specs:**
- Font: Inter Medium, 14px, lh 24px
- Padding: 16px horizontal, 8px vertical
- Border radius: 6px
- **No elevation/shadow** (flat design)
- **No lift on hover** (`-translate-y-px` removed)

**Current system differences:**
- Default button uses `--primary` which maps to `--ii-brand-primary` (gold `#c9a84c` / `#9a7a2e`) → will resolve to slate-900 after Phase 0.2 shadcn bridge remap
- Current button in `packages/investintell-ui/src/lib/components/ui/button/` may have custom shadow/lift effects → remove
- Destructive uses `--destructive` → `--ii-danger` → will be `#ef4444` after Phase 0.2

**Files to modify:**
- [ ] `packages/investintell-ui/src/lib/components/ui/button/` — verify variant classes use `--primary`/`--destructive` shadcn vars (should work after token remap)
- [ ] `packages/investintell-ui/src/lib/components/Button.svelte` — old wrapper with custom elevation — deprecate or replace internals with shadcn Button

#### 0.4 — Shadcn/ui CSS Variables Layer

The standard shadcn/ui approach uses a semantic CSS variable layer (`--background`, `--foreground`, `--card`, `--primary`, `--muted`, etc.) that maps to HSL values. The `ui/` components in packages/investintell-ui/src/lib/components/ui/ likely already reference these.

**The bridge already exists** in `tokens.css` (lines 111-141). Currently it maps `--primary` → `--ii-brand-primary` (gold). After Phase 0.2, the `--ii-*` values will be Slate-based, so the bridge automatically resolves correctly. No HSL conversion needed — the bridge uses `var()` references.

**Verify** the bridge values match shadcn expectations. Reference HSL values for documentation:

```css
:root {
  --background: 0 0% 100%;           /* white */
  --foreground: 222.2 84% 4.9%;      /* slate-900 */
  --card: 0 0% 100%;                 /* white */
  --card-foreground: 222.2 84% 4.9%; /* slate-900 */
  --popover: 0 0% 100%;
  --popover-foreground: 222.2 84% 4.9%;
  --primary: 222.2 84% 4.9%;         /* slate-900 */
  --primary-foreground: 210 40% 98%; /* slate-50 */
  --secondary: 210 40% 96.1%;        /* slate-100 */
  --secondary-foreground: 222.2 84% 4.9%;
  --muted: 210 40% 96.1%;            /* slate-100 */
  --muted-foreground: 215.4 16.3% 46.9%; /* slate-500 */
  --accent: 210 40% 96.1%;
  --accent-foreground: 222.2 84% 4.9%;
  --destructive: 0 84.2% 60.2%;      /* red-500 */
  --destructive-foreground: 210 40% 98%;
  --border: 214.3 31.8% 91.4%;       /* slate-200 */
  --input: 214.3 31.8% 91.4%;
  --ring: 222.2 84% 4.9%;
  --radius: 0.375rem;                /* 6px */
}
```

**Files to modify:**
- [ ] `packages/investintell-ui/src/lib/styles/tokens.css` — verify shadcn bridge section maps correctly after `--ii-*` value changes

#### 0.5 — Icons: Phosphor → Lucide

shadcn/ui official icon library is **Lucide** (`lucide-svelte`). The current system uses **Phosphor** (`phosphor-svelte`).

**Current usage:**
- `packages/investintell-ui/` — **43 files** import from `phosphor-svelte` (shadcn primitive internals: chevrons, checks, arrows, dots, etc.)
- `frontends/wealth/` — **4 files** import from `phosphor-svelte` (GlobalSearch, AiAgentDrawer, layout, investment-policy)

**Common Phosphor → Lucide mappings:**

| Phosphor | Lucide | Used in |
|----------|--------|---------|
| `CaretDown` | `ChevronDown` | Select, Accordion, Navigation |
| `CaretUp` | `ChevronUp` | Select scroll, Calendar |
| `CaretRight` | `ChevronRight` | Breadcrumb separator |
| `CaretLeft` | `ChevronLeft` | Pagination, Calendar |
| `Check` | `Check` | Checkbox, Select item, Command item |
| `X` | `X` | Dialog close, Sheet close |
| `Circle` | `Circle` | Radio group |
| `DotsThree` | `Ellipsis` | Breadcrumb, Pagination |
| `MagnifyingGlass` | `Search` | Command input |
| `SpinnerGap` | `Loader2` | Spinner (with animate-spin) |
| `ArrowLeft` | `ArrowLeft` | Carousel |
| `ArrowRight` | `ArrowRight` | Carousel |
| `Minus` | `Minus` | Calendar range |
| `Plus` | `Plus` | Button with icon |
| `Envelope` | `Mail` | Button with icon |
| `GripVertical` | `GripVertical` | Resizable handle |

**Files to modify:**
- [ ] `packages/investintell-ui/src/lib/components/ui/` — 43 files: swap all `phosphor-svelte` imports to `lucide-svelte`
- [ ] `frontends/wealth/src/lib/components/GlobalSearch.svelte` — `SpinnerGap` → `Loader2`
- [ ] `frontends/wealth/src/lib/components/AiAgentDrawer.svelte` — spinner + any other icons
- [ ] `frontends/wealth/src/routes/(app)/+layout.svelte` — navigation icons
- [ ] `frontends/wealth/src/routes/(app)/investment-policy/+page.svelte` — page icons
- [ ] `packages/investintell-ui/package.json` — add `lucide-svelte`, remove `phosphor-svelte`
- [ ] `frontends/wealth/package.json` — add `lucide-svelte`, remove `phosphor-svelte`

**Note:** Lucide icons are 24x24 by default (same as Phosphor). `size` prop works the same way. Phosphor `weight` prop (thin/light/regular/bold/fill/duotone) has no Lucide equivalent — Lucide has a single stroke weight (`strokeWidth` prop, default 2). Verify no Phosphor `weight="bold"` or `weight="fill"` usage requires special handling.

**Acceptance:** Phase 0 complete when:
- [ ] Font family is Inter (sans) + Geist Mono/Menlo (mono) across both frontends
- [ ] Color palette is Tailwind Slate-based (no gold, no institutional blue)
- [ ] Buttons are flat with no shadow/lift effects
- [ ] shadcn bridge variables resolve to correct Slate values
- [ ] All icons use `lucide-svelte` — zero `phosphor-svelte` imports remain
- [ ] `make build-all` passes
- [ ] Dark mode still works correctly

---

### Phase 1: Mechanical Primitives (Low Risk, High Volume)

Simple find-and-replace patterns. No behavioral change. Can be done file-by-file with zero risk of regression.

#### 1.1 — Checkbox

**Current pattern** (`CatalogFilterSidebar.svelte:172-235`):
```svelte
<label class="cfs-check">
  <input type="checkbox" checked={selected} onchange={() => toggle(key)} />
  <span class="cfs-check-label">{label}</span>
</label>
```

**Target:**
```svelte
import { Checkbox } from "@investintell/ui/components/ui/checkbox";
import { Label } from "@investintell/ui/components/ui/label";

<div class="flex items-center gap-2">
  <Checkbox id={key} checked={selected} onCheckedChange={() => toggle(key)} />
  <Label for={key}>{label}</Label>
</div>
```

**Files to migrate:**
- [ ] `screener/CatalogFilterSidebar.svelte` — universe, strategy, geography, domicile checkboxes (~4 groups, ~20 checkboxes)
- [ ] `screener/InstrumentFilterSidebar.svelte` — asset class, sector, geography checkboxes
- [ ] `screener/ManagerFilterSidebar.svelte` — strategy, regulatory status checkboxes
- [ ] `screener/SecuritiesFilterSidebar.svelte` — asset class, sector, rating checkboxes
- [ ] `screener/ScreenerFilters.svelte` — eliminatory/mandate/quant filter checkboxes

**Remove:** `.cfs-check`, `.cfs-check-label`, `.cfs-check-count` CSS classes after migration.

#### 1.2 — Label

**Current:** Raw `<label>` tags with `for` attributes and manual CSS.

**Target:** `import { Label } from "@investintell/ui/components/ui/label";`

**Files:** All filter sidebars (co-migrated with Checkbox above), plus:
- [ ] `BlendedBenchmarkEditor.svelte` — benchmark weight labels
- [ ] `model-portfolio/ConstructionAdvisor.svelte` — wizard step labels
- [ ] `model-portfolio/ICViewsPanel.svelte` — view input labels
- [ ] `AllocationView.svelte` — allocation field labels

#### 1.3 — Separator

**Current:** `border-b border-(--ii-border)` Tailwind classes and `border-bottom: 1px solid` CSS.

**Target:** `import { Separator } from "@investintell/ui/components/ui/separator";`

**Files (30+ instances):**
- [ ] `FundDetailPanel.svelte:190` — tab row border
- [ ] `screener/CatalogFilterSidebar.svelte:344` — `.cfs-section` border-bottom
- [ ] All filter sidebars — section dividers
- [ ] Analytics panels — section dividers
- [ ] Model portfolio panels — section dividers

**Strategy:** Global search for `border-b border-(--ii-border)` and `border-bottom:.*solid` in `.svelte` files. Replace with `<Separator />` or `<Separator orientation="vertical" />`.

#### 1.4 — Spinner

**Current** (`GlobalSearch.svelte:186-188, 302-306`):
```svelte
import { SpinnerGap } from "phosphor-svelte";
<SpinnerGap size={16} weight="bold" class="gs-spinner" />
<!-- + @keyframes spin CSS -->
```

**Target:** `import { Spinner } from "@investintell/ui/components/ui/spinner";`

**Files:**
- [ ] `GlobalSearch.svelte` — search loading spinner
- [ ] `AiAgentDrawer.svelte` — message loading spinner
- [ ] `IngestionProgress.svelte` — ingestion loading
- [ ] Any other `@keyframes spin` instances

**Remove:** All `@keyframes spin` CSS blocks and `SpinnerGap` imports after migration.

#### 1.5 — Tooltip

**Current:** No UI tooltips exist (only echarts chart tooltips). Icon buttons and abbreviated metrics have no hover explanations.

**Target:** `import * as Tooltip from "@investintell/ui/components/ui/tooltip";`

**Files to ADD tooltips:**
- [ ] `analytics/entity/ReturnStatisticsPanel.svelte` — metric abbreviations (Sharpe, Sortino, etc.)
- [ ] `analytics/entity/RiskStatisticsGrid.svelte` — risk metric definitions
- [ ] `analytics/entity/TailRiskPanel.svelte` — VaR, CVaR, MES explanations
- [ ] Icon buttons throughout (export, refresh, settings icons)

#### 1.6 — Progress

**Current** (`FundDetailPanel.svelte:314-320`):
```svelte
<div class="h-1.5 w-full overflow-hidden rounded-full bg-(--ii-surface-inset)">
  <div class="h-full rounded-full bg-(--ii-brand-primary)" style="width: {ddProgress}%;"></div>
</div>
```

**Target:** `import { Progress } from "@investintell/ui/components/ui/progress";`

**Files:**
- [ ] `FundDetailPanel.svelte` — DD report progress
- [ ] `model-portfolio/ScoreBreakdownPopover.svelte` — score bar tracks

**Acceptance:** Phase 1 complete when zero `<input type="checkbox">`, zero `@keyframes spin`, zero raw `<label>` remain in `frontends/wealth/src/`.

---

### Phase 2: Structural Components (Medium Effort, High Visual Impact)

These change component structure and behavior. Test each page after migration.

#### 2.1 — Tabs

**Current pattern** (`FundDetailPanel.svelte:189-204`):
```svelte
let activeTab = $state<Tab>("resumo");
<div class="mb-4 flex gap-1 border-b border-(--ii-border)">
  {#each tabs as tab}
    <button class:text-(--ii-brand-primary)={activeTab === tab.value}
            onclick={() => (activeTab = tab.value)}>
      {tab.label}
      {#if activeTab === tab.value}
        <span class="absolute bottom-0 left-0 right-0 h-0.5 bg-(--ii-brand-primary)"></span>
      {/if}
    </button>
  {/each}
</div>
{#if activeTab === "resumo"} ... {/if}
```

**Target:**
```svelte
import * as Tabs from "@investintell/ui/components/ui/tabs";

<Tabs.Root value="resumo">
  <Tabs.List>
    <Tabs.Trigger value="resumo">Resumo</Tabs.Trigger>
    <Tabs.Trigger value="dd-report">DD Report</Tabs.Trigger>
  </Tabs.List>
  <Tabs.Content value="resumo">...</Tabs.Content>
  <Tabs.Content value="dd-report">...</Tabs.Content>
</Tabs.Root>
```

**Files:**
- [ ] `FundDetailPanel.svelte` — 6 tabs (resumo, holdings, performance, dd-report, docs, drift)
- [ ] `screener/CatalogDetailPanel.svelte` — fund/manager detail tabs
- [ ] `screener/ManagerDetailPanel.svelte` — manager detail tabs
- [ ] Portfolio detail page tabs
- [ ] Analytics entity page tabs
- [ ] Route-level `(app)/+layout.svelte` if page-level tabs exist

**Note:** Remove `activeTab` $state variable. Tabs.Root manages state internally. If external state sync is needed, use `bind:value` or `onValueChange`.

#### 2.2 — Sheet / Drawer

**Current pattern** (`AiAgentDrawer.svelte:235-373`):
```svelte
{#if open}
  <div class="agent-backdrop" onclick={onclose}></div>
  <aside class="agent-drawer">...</aside>
{/if}
<style>
  .agent-drawer { position: fixed; right: 0; width: 420px; animation: slideIn 200ms; }
  @keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
</style>
```

**Target:**
```svelte
import * as Sheet from "@investintell/ui/components/ui/sheet";

<Sheet.Root bind:open>
  <Sheet.Content side="right" class="w-[420px]">
    <Sheet.Header>
      <Sheet.Title>AI Assistant</Sheet.Title>
    </Sheet.Header>
    <!-- content -->
  </Sheet.Content>
</Sheet.Root>
```

**Files:**
- [ ] `AiAgentDrawer.svelte` — AI chat drawer (right side, 420px)
- [ ] `FundDetailPanel.svelte` → currently uses `<ContextPanel>` from @investintell/ui
- [ ] `screener/CatalogDetailPanel.svelte` → uses `<ContextPanel>`
- [ ] `screener/InstrumentDetailPanel.svelte` → uses `<ContextPanel>`
- [ ] `screener/ManagerDetailPanel.svelte` → uses `<ContextPanel>`
- [ ] `LongFormReportPanel.svelte` — report viewer panel

**Also refactor** the `ContextPanel` wrapper in `@investintell/ui` to use `Sheet` internally (Phase 3).

**Remove:** All `@keyframes slideIn`, `.agent-backdrop`, `.agent-drawer` CSS, and custom position/animation logic.

#### 2.3 — Pagination

**Current** (`CatalogTable.svelte:251-268`):
```svelte
<span class="ct-page-label">Page {catalog.page} of {totalPages}</span>
```

**Target:**
```svelte
import * as Pagination from "@investintell/ui/components/ui/pagination";

<Pagination.Root count={totalItems} perPage={pageSize} page={currentPage}>
  <Pagination.Content>
    <Pagination.Item><Pagination.PrevButton /></Pagination.Item>
    <!-- page numbers -->
    <Pagination.Item><Pagination.NextButton /></Pagination.Item>
  </Pagination.Content>
</Pagination.Root>
```

**Files:**
- [ ] `screener/CatalogTable.svelte` — fund catalog pagination
- [ ] `screener/InstrumentTable.svelte` — instrument list
- [ ] `screener/SecManagerTable.svelte` — manager list
- [ ] `screener/SecuritiesTable.svelte` — securities list
- [ ] `screener/SecHoldingsTable.svelte` — holdings list

#### 2.4 — Toggle Group

**Current** (`PortfolioNAVChart.svelte:32-37`):
```svelte
const TIME_RANGES = ["1M", "3M", "6M", "1Y", "YTD", "SI"] as const;
{#each TIME_RANGES as range}
  <button class:active={timeRange === range} onclick={() => (timeRange = range)}>{range}</button>
{/each}
```

**Target:**
```svelte
import * as ToggleGroup from "@investintell/ui/components/ui/toggle-group";

<ToggleGroup.Root type="single" value={timeRange} onValueChange={(v) => (timeRange = v)}>
  {#each TIME_RANGES as range}
    <ToggleGroup.Item value={range}>{range}</ToggleGroup.Item>
  {/each}
</ToggleGroup.Root>
```

**Files:**
- [ ] `charts/PortfolioNAVChart.svelte` — time range (1M/3M/6M/1Y/YTD/SI) + view mode (base100/absolute)
- [ ] `macro/SeriesPicker.svelte` — region filter chips, frequency filter
- [ ] Any other period selector / view mode toggle patterns

#### 2.5 — Scroll Area

**Current:** `overflow-y: auto; scrollbar-width: thin;` CSS.

**Target:** `import { ScrollArea } from "@investintell/ui/components/ui/scroll-area";`

**Files:**
- [ ] `GlobalSearch.svelte:329` — `.gs-results { max-height: 380px; overflow-y: auto; }`
- [ ] `AiAgentDrawer.svelte:420` — `.agent-messages { overflow-y: auto; }`
- [ ] `screener/CatalogFilterSidebar.svelte:329` — `.cfs-sidebar { overflow-y: auto; max-height: calc(100vh - 140px); }`
- [ ] `screener/InstrumentFilterSidebar.svelte` — same pattern
- [ ] `screener/ManagerFilterSidebar.svelte` — same pattern

#### 2.6 — Dropdown Menu

**Current:** Native `<select>` elements with custom CSS (`.cfs-select`).

For ACTION menus (portfolio actions, export, etc.), replace with:
```svelte
import * as DropdownMenu from "@investintell/ui/components/ui/dropdown-menu";
```

For FORM selects (AUM min, expense ratio, etc.), replace with:
```svelte
import * as Select from "@investintell/ui/components/ui/select";
```

**Files:**
- [ ] `screener/CatalogFilterSidebar.svelte:241-265` — AUM min, max expense ratio → `Select`
- [ ] `screener/InstrumentFilterSidebar.svelte` — similar filter selects → `Select`
- [ ] Portfolio action menus → `DropdownMenu`
- [ ] Fund card action menus → `DropdownMenu`
- [ ] Export/download menus → `DropdownMenu`

**Remove:** `.cfs-select` CSS class and SVG chevron data URI after migration.

#### 2.7 — Popover

**Current** (`ScoreBreakdownPopover.svelte:75-109`):
```svelte
<svelte:window onclick={handleClickOutside} />
<span class="sb-trigger" onclick={handleClick}>{score}</span>
{#if open}
  <div class="sb-popover" onclick={(e) => e.stopPropagation()}>...</div>
{/if}
```

**Target:**
```svelte
import * as Popover from "@investintell/ui/components/ui/popover";

<Popover.Root>
  <Popover.Trigger>{score}</Popover.Trigger>
  <Popover.Content align="end" class="min-w-[340px]">
    <!-- breakdown table -->
  </Popover.Content>
</Popover.Root>
```

**Files:**
- [ ] `model-portfolio/ScoreBreakdownPopover.svelte` — score breakdown
- [ ] Any other manual click-outside popover patterns

**Remove:** `svelte:window onclick={handleClickOutside}`, `e.stopPropagation()`, `.sb-popover` absolute positioning CSS.

**Acceptance:** Phase 2 complete when zero custom tab groups, zero custom slide panels, zero custom pagination, zero native `<select>` in filter sidebars remain.

---

### Phase 3: Wrapper Refactoring (Internal, No Consumer Change)

Refactor `@investintell/ui` wrapper components to use shadcn primitives internally. **External API stays identical** — consumers of `<MetricCard>`, `<PeriodSelector>`, etc. change nothing.

#### 3.1 — MetricCard → Card internally

**File:** `packages/investintell-ui/src/lib/components/MetricCard.svelte`

**Current:** Raw `<div>` with manual shadow/border styling.

**Target:** Compose `Card.Root` + `Card.Header` + `Card.Content` from `../ui/card`.

#### 3.2 — StatusBadge → Badge internally

**File:** `packages/investintell-ui/src/lib/components/StatusBadge.svelte`

**Current:** Raw `<span>` with CSS-in-JS color mixing.

**Target:** Compose `Badge` from `../ui/badge` with variant mapping.

#### 3.3 — FormField → Field + Label internally

**File:** `packages/investintell-ui/src/lib/components/FormField.svelte`

**Current:** Raw `<label>` + `<div>` for error wrapper.

**Target:** Compose `Label` from `../ui/label` + `Field` from `../ui/field`.

#### 3.4 — PageHeader → Breadcrumb internally

**File:** `packages/investintell-ui/src/lib/layouts/PageHeader.svelte`

**Current:** Raw `<ol>/<li>` breadcrumb list.

**Target:** Compose `Breadcrumb.Root` + `Breadcrumb.List` + `Breadcrumb.Item` + `Breadcrumb.Link` + `Breadcrumb.Separator` from `../ui/breadcrumb`.

#### 3.5 — PeriodSelector → ToggleGroup internally

**File:** `packages/investintell-ui/src/lib/components/PeriodSelector.svelte`

**Current:** Raw button group.

**Target:** Compose `ToggleGroup.Root` + `ToggleGroup.Item` from `../ui/toggle-group`.

#### 3.6 — ConfirmDialog → AlertDialog internally

**File:** `packages/investintell-ui/src/lib/components/ConfirmDialog.svelte`

**Current:** Already partially uses bits-ui Dialog. Migrate to proper AlertDialog pattern.

**Target:** Use `AlertDialog.Root/Content/Title/Description/Cancel/Action` from `../ui/alert-dialog`.

#### 3.7 — SectionCard → Card internally

**File:** `packages/investintell-ui/src/lib/components/SectionCard.svelte`

**Current:** Raw `<section>` with collapsible header.

**Target:** Compose `Card.Root` + `Card.Header` + `Collapsible.Root` from `../ui/card` and `../ui/collapsible`.

#### 3.8 — Select (wrapper) → Select (shadcn) internally

**File:** `packages/investintell-ui/src/lib/components/Select.svelte`

**Current:** 100% custom implementation with manual keyboard navigation, inline styles.

**Target:** Compose `Select.Root/Trigger/Content/Item` from `../ui/select`. Remove all custom keyboard handling.

#### 3.9 — Sheet (wrapper) → Sheet (shadcn) internally

**File:** `packages/investintell-ui/src/lib/components/Sheet.svelte` (if exists)

And `ContextPanel` / `ContextSidebar` layouts:
- `packages/investintell-ui/src/lib/layouts/ContextPanel.svelte`
- `packages/investintell-ui/src/lib/layouts/ContextSidebar.svelte`

**Target:** Use `Sheet.Root/Content` from `../ui/sheet`.

#### 3.10 — Tabs (wrapper) → Tabs (shadcn) internally

**File:** `packages/investintell-ui/src/lib/components/Tabs.svelte` (if exists)

**Target:** Use `Tabs.Root/List/Trigger/Content` from `../ui/tabs`.

#### 3.11 — AlertBanner → Alert internally

**File:** `packages/investintell-ui/src/lib/components/AlertBanner.svelte`

**Current:** Raw `<div>` with variant styles.

**Target:** Compose `Alert.Root` + `Alert.Title` + `Alert.Description` from `../ui/alert`.

**Acceptance:** Phase 3 complete when all wrapper components in `packages/investintell-ui/src/lib/components/` use shadcn primitives from `../ui/` internally. Zero raw `<div>`/`<span>`/`<label>` for primitive UI patterns.

---

### Phase 4: Composite Patterns

Build standard shadcn/ui composite components and refactor complex features.

#### 4.1 — GlobalSearch → Command

**File:** `frontends/wealth/src/lib/components/GlobalSearch.svelte` (439 lines)

**Current:** Fully custom Cmd+K palette with:
- `svelte:window onkeydown` for Cmd+K/Ctrl+K
- Custom backdrop + dialog
- Debounced search (300ms)
- Grouped results with flat-index keyboard nav
- Custom `.gs-*` CSS (190 lines)

**Target:** Rebuild using `Command` (cmdk-sv):
```svelte
import * as Command from "@investintell/ui/components/ui/command";
import * as Dialog from "@investintell/ui/components/ui/dialog";

<Dialog.Root bind:open>
  <Dialog.Content class="p-0">
    <Command.Root>
      <Command.Input placeholder="Search funds, managers, instruments..." />
      <Command.List>
        <Command.Empty>No results.</Command.Empty>
        <Command.Group heading="Funds">
          {#each fundResults as fund}
            <Command.Item onSelect={() => goto(fund.url)}>{fund.name}</Command.Item>
          {/each}
        </Command.Group>
        <!-- more groups -->
      </Command.List>
    </Command.Root>
  </Dialog.Content>
</Dialog.Root>
```

**Preserve:** Debounced API search, grouped results, Cmd+K keybinding, "/" shortcut.

**Remove:** All `.gs-*` CSS (~190 lines), manual keyboard navigation, custom backdrop.

#### 4.2 — Combobox Composite (Command + Popover)

**Build in:** `packages/investintell-ui/src/lib/components/Combobox.svelte`

**Pattern:**
```svelte
<Popover.Root bind:open>
  <Popover.Trigger>
    <Button variant="outline" role="combobox" aria-expanded={open}>
      {selectedLabel ?? placeholder}
    </Button>
  </Popover.Trigger>
  <Popover.Content class="p-0">
    <Command.Root>
      <Command.Input placeholder={searchPlaceholder} />
      <Command.List>
        {#each items as item}
          <Command.Item value={item.value} onSelect={handleSelect}>
            {item.label}
          </Command.Item>
        {/each}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
```

**Use in:**
- [ ] `macro/SeriesPicker.svelte` — macro series selection (currently custom dropdown)
- [ ] `BlendedBenchmarkEditor.svelte` — benchmark fund picker
- [ ] `model-portfolio/FundSelectionEditor.svelte` — fund search/select
- [ ] `model-portfolio/ICViewsPanel.svelte` — fund picker for views

#### 4.3 — DatePicker Composite (Calendar + Popover)

**Build in:** `packages/investintell-ui/src/lib/components/DatePicker.svelte`

**Pattern:** Standard shadcn DatePicker (Calendar inside Popover with Button trigger).

**Use in:**
- [ ] `macro/CommitteeReviews.svelte` — date picker for review navigation
- [ ] Any report date range selectors
- [ ] Filter date fields (if any)

#### 4.4 — DataTable Overhaul (Compact Density, Institutional)

**File:** `packages/investintell-ui/src/lib/components/DataTable.svelte`

**Figma reference:** [UI Prep Data Tables — Compact Density](https://www.figma.com/design/LsVyaCue9jNpiy12sblgfs/UI-Prep-Data-Tables--Community-?node-id=1271-18429&m=dev)

**Current:** TanStack Table with custom pagination controls and relaxed spacing.

**Architecture:** `@tanstack/svelte-table` stays as the data engine (sorting, filtering, column visibility, row selection). The rendering layer is fully replaced with shadcn primitives from `@investintell/ui/components/ui/`.

**Rendering primitives:**
- `Table.Root` / `Table.Header` / `Table.Body` / `Table.Row` / `Table.Head` / `Table.Cell` — table structure
- `Checkbox` — row selection (header = select-all, rows = individual)
- `Pagination` — page navigation
- `Select` — page size selector (20 / 50 / 100)
- `DropdownMenu` — column visibility toggle + row actions (vertical dots)
- `Card` — empty state wrapper

**Compact density spec (from Figma):**

| Element | Spec |
|---|---|
| **Row height** | 40px rigid (`h-10`) |
| **Header cell padding** | `py-[13px] px-2` — vertically centered, SemiBold 14px, `tracking-wide` (0.28px), `leading-4`, uppercase |
| **Data cell padding** | `py-2.5 px-2` — Regular 14px, `leading-5` |
| **Zebra striping** | Odd rows: `bg-background` (white), Even rows: `bg-muted/50` (~`#f8f9fc`) |
| **Header background** | `bg-muted` (~`#f1f3f9`) |
| **Checkbox column** | Fixed 36px (`w-9`), center-aligned |
| **Actions column** | Fixed 36px (`w-9`), center-aligned, `MoreVertical` icon (lucide-svelte) |
| **Container** | `rounded-lg shadow-sm` (elevation 100) |
| **Min visible rows** | 20 per page (compact allows ~20 rows in 800px viewport) |

**Tipografia financeira — obrigatória em todas as colunas numéricas:**

```css
/* Applied via utility class on numeric Table.Cell */
.ii-tabular-nums {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
  text-align: right;
  font-family: var(--ii-font-mono); /* Inter mono digits, or Geist Mono fallback */
}
```

Regras:
- Todas as colunas de métricas (AUM, NAV, returns, Sharpe, expense ratio, etc.) usam `tabular-nums` + alinhamento à direita
- Headers de colunas numéricas também alinhados à direita
- Colunas de texto (fund name, strategy, manager) alinhadas à esquerda
- Percentuais formatados via `formatPercent` de `@investintell/ui` (nunca `.toFixed()`)
- Currency via `formatCurrency` / `formatAUM`

**Frozen / Sticky columns:**

| Coluna | Comportamento |
|---|---|
| Checkbox (col 0) | `sticky left-0 z-10` — sempre visível ao scroll lateral |
| Fund name (col 1) | `sticky left-9 z-10` — fixa após checkbox, com `shadow-[2px_0_4px_-2px_rgba(0,0,0,0.1)]` no edge |
| Actions (última col) | `sticky right-0 z-10` — sempre visível |

Implementação via `position: sticky` no `Table.Head` e `Table.Cell` das colunas fixas. Background deve ser opaco (`bg-background` / `bg-muted`) para não sobrepor transparente.

**Empty state institucional:**

```svelte
{#if rows.length === 0}
  <Card.Root class="mx-auto my-12 max-w-md text-center">
    <Card.Content class="pt-6">
      <Search class="mx-auto mb-4 size-10 text-muted-foreground" />
      <p class="text-lg font-semibold">No funds match your criteria</p>
      <p class="text-sm text-muted-foreground mt-1">
        Try adjusting your filters or broadening your search.
      </p>
    </Card.Content>
  </Card.Root>
{/if}
```

Usa `Card` de shadcn + ícone `Search` de `lucide-svelte`. Sem ilustrações custom.

**Ícones (exclusivamente lucide-svelte):**

| Uso | Ícone |
|---|---|
| Sort ascending | `ArrowUp` |
| Sort descending | `ArrowDown` |
| Sort neutral | `ArrowUpDown` |
| Row actions | `MoreVertical` |
| Pagination prev | `ChevronLeft` |
| Pagination next | `ChevronRight` |
| First page | `ChevronsLeft` |
| Last page | `ChevronsRight` |
| Empty state | `Search` |
| Column visibility | `SlidersHorizontal` |

**Target code structure (simplified):**

```svelte
<div class="rounded-lg shadow-sm overflow-hidden">
  <Table.Root>
    <Table.Header>
      <Table.Row class="bg-muted">
        <Table.Head class="w-9 sticky left-0 bg-muted">
          <Checkbox checked={allSelected} onCheckedChange={toggleAll} />
        </Table.Head>
        <Table.Head class="sticky left-9 bg-muted shadow-[2px_0_4px_-2px_rgba(0,0,0,0.1)]">
          Fund Name
        </Table.Head>
        {#each numericHeaders as header}
          <Table.Head class="text-right tabular-nums">{header.label}</Table.Head>
        {/each}
        <Table.Head class="w-9 sticky right-0 bg-muted" />
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each rows as row, i}
        <Table.Row class={i % 2 === 0 ? "bg-background" : "bg-muted/50"}>
          <Table.Cell class="w-9 sticky left-0 {i % 2 === 0 ? 'bg-background' : 'bg-muted/50'}">
            <Checkbox checked={row.selected} />
          </Table.Cell>
          <Table.Cell class="sticky left-9 font-medium {i % 2 === 0 ? 'bg-background' : 'bg-muted/50'} shadow-[2px_0_4px_-2px_rgba(0,0,0,0.1)]">
            {row.name}
          </Table.Cell>
          {#each row.metrics as metric}
            <Table.Cell class="text-right tabular-nums">{metric}</Table.Cell>
          {/each}
          <Table.Cell class="w-9 sticky right-0 {i % 2 === 0 ? 'bg-background' : 'bg-muted/50'}">
            <DropdownMenu.Root>
              <DropdownMenu.Trigger><MoreVertical class="size-4" /></DropdownMenu.Trigger>
              <DropdownMenu.Content>...</DropdownMenu.Content>
            </DropdownMenu.Root>
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
</div>
```

**Acceptance:** Phase 4 complete when GlobalSearch uses Command, Combobox/DatePicker composites exist, and DataTable renders 100% through shadcn `Table.*` primitives with compact density (40px rows, 20+ visible), tabular-nums on all numeric columns, sticky fund name column, and lucide icons for sort/pagination/actions.

---

### Phase 5: Screener Navigation Redesign (3-Level Drill-Down)

Redesign the screener from a flat mixed-entity list into a **3-level hierarchical workspace** with Sheet-based drill-down navigation. The user never leaves the screener page — deeper levels slide in from the right, preserving search context.

#### 5.0 — Design Rationale

The current screener mixes funds, managers, and instruments in the same table with tab switching. This creates cognitive load: the user must context-switch between entity types and loses filter state when navigating to detail views.

The new model is **Manager-first**: the screener primary table lists Fund Managers. Clicking a manager opens a Sheet with that manager's funds. Clicking a fund opens a deeper Sheet with share classes. At every level, the previous level remains visible and scrollable behind the overlay — the user never loses their search context.

```
┌─────────────────────────────────────────────────────────────┐
│  Screener (Level 1)                                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Filters: [Funds] [ETFs] [Private] [Hedge] [AUM▾]   │    │
│  ├─────────────────────────────────────────────────────┤    │
│  │ ☐ Manager Name    AUM     Funds  Strategy    ...  ⋮ │    │
│  │ ☐ BlackRock       $10T    127    Multi       ...  ⋮ │◄─click──┐
│  │ ☐ Vanguard        $8.6T   84     Index       ...  ⋮ │    │    │
│  │ ☐ Bridgewater     $124B   12     Macro       ...  ⋮ │    │    │
│  │ ...                                                  │    │    │
│  └─────────────────────────────────────────────────────┘    │    │
│                                                              │    │
│  ┌──────────────── Sheet (Level 2) ──────────────────┐      │    │
│  │  ← BlackRock Funds                          [✕]   │◄─────────┘
│  │  ┌───────────────────────────────────────────┐    │      │
│  │  │ ☐ Fund Name      AUM    1Y    ER   ...  ⋮│    │      │
│  │  │ ☐ BLK Large Cap  $42B  12.3% 0.03 ...  ⋮│◄─click──┐│
│  │  │ ☐ BLK EM Equity  $8B   -2.1% 0.15 ...  ⋮│    │    ││
│  │  │ ...                                       │    │    ││
│  │  └───────────────────────────────────────────┘    │    ││
│  │                                                    │    ││
│  │  ┌──────────── Sheet (Level 3) ────────────┐     │    ││
│  │  │  ← BLK Large Cap — Share Classes  [✕]   │◄────────┘│
│  │  │  ┌─────────────────────────────────┐    │     │     │
│  │  │  │ Class   Ticker  ER    NAV  ...  │    │     │     │
│  │  │  │ Inst    BKLCX   0.03  $142 ...  │    │     │     │
│  │  │  │ Inv A   BKLAX   0.85  $141 ...  │    │     │     │
│  │  │  │ Adv     BKLDX   0.50  $142 ...  │    │     │     │
│  │  │  └─────────────────────────────────┘    │     │     │
│  │  └─────────────────────────────────────────┘     │     │
│  └───────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

#### 5.1 — Level 1: Fund Managers (Screener Primary Table)

**Route:** `/screener` (existing, refactored)

**Entity:** Fund Managers (from `sec_managers`, `esma_managers`)

**DataTable columns:**

| Column | Type | Align | Sticky | Source |
|---|---|---|---|---|
| Checkbox | selection | center | left-0 | — |
| Manager Name | text | left | left-9 | `manager_name` |
| CRD / LEI | text | left | — | `crd_number` or `lei` |
| AUM | numeric | right | — | `total_aum` (formatted via `formatAUM`) |
| # Funds | numeric | right | — | computed count |
| Primary Strategy | text | left | — | `strategy_label` |
| Domicile | text | left | — | `state` or `country` |
| Regulatory Status | badge | center | — | SEC/ESMA registered |
| Actions | menu | center | right-0 | MoreVertical |

**Universe filters (top-level tabs/toggle group):**

| Filter | Scope |
|---|---|
| **All** | All managers |
| **Mutual Funds** | Managers with `registered_us` funds |
| **ETFs** | Managers with `etf` funds |
| **Private Funds** | Managers with `private_us` funds (ADV Schedule D) |
| **Hedge Funds** | Managers with hedge fund `strategy_label` |
| **UCITS** | Managers from `esma_managers` |

**Sidebar filters:** AUM range, geography, strategy, regulatory status.

**Row click → opens Level 2 Sheet.**

#### 5.2 — Level 2: Funds by Manager (Sheet Drill-Down)

**Component:** `Sheet` from `@investintell/ui/components/ui/sheet`, side `"right"`, width `min(85vw, 1200px)`.

**Trigger:** Click on any row in Level 1.

**Sheet header:**
- Back arrow (`ChevronLeft` lucide) + Manager name + Close button (`X` lucide)
- Manager summary strip: AUM, # funds, primary strategy, CRD

**DataTable columns:**

| Column | Type | Align | Source |
|---|---|---|---|
| Checkbox | selection | center | — |
| Fund Name | text | left (sticky) | `fund_name` |
| Universe | badge | center | `registered_us` / `etf` / `private_us` / `ucits` |
| AUM / GAV | numeric | right | `total_assets` or `gross_asset_value` |
| 1Y Return | numeric | right | `return_1y` (conditional color: green/red) |
| 3Y Return | numeric | right | `return_3y` |
| Expense Ratio | numeric | right | `expense_ratio_pct` |
| Strategy | text | left | `strategy_label` |
| Holdings | numeric | right | `holdings_count` |
| Actions | menu | center | MoreVertical (import to universe, start DD, etc.) |

**Filters within Sheet:** Fund type, strategy, AUM range (scoped to this manager's funds only).

**Row click → opens Level 3 Sheet** (stacked on top of Level 2).

**Empty state:** "This manager has no disclosed funds matching your filters."

#### 5.3 — Level 3: Share Classes by Fund (Nested Sheet)

**Component:** `Sheet` stacked on top of Level 2. Same side `"right"`, width `min(70vw, 900px)`. Level 2 Sheet remains partially visible underneath (darker backdrop).

**Trigger:** Click on any row in Level 2.

**Sheet header:**
- Back arrow + Fund name + Close button
- Fund summary strip: AUM, inception date, strategy, manager name, CIK/ISIN

**DataTable columns:**

| Column | Type | Align | Source |
|---|---|---|---|
| Share Class | text | left | `class_name` (Institutional, Investor A, Advisor, etc.) |
| Ticker | mono | left | `ticker` (monospace, uppercase) |
| Expense Ratio | numeric | right | `expense_ratio_pct` |
| NAV | numeric | right | `net_assets` |
| 1Y Return | numeric | right | `avg_annual_return_pct` |
| Inception Date | date | left | `perf_inception_date` |
| Min Investment | numeric | right | `min_initial_investment` (if available) |

**Actions:** "Import to Universe" button (imports the selected share class as an `instruments_org` entry).

**This is the terminal level.** No further drill-down. Clicking a share class row selects it (checkbox). Bulk action: "Import selected to Universe".

#### 5.4 — Sheet Stacking Behavior

**Critical UX rules:**

1. **Context preservation:** Level 1 (screener table) stays fully interactive behind Sheet overlays. Scroll position, filters, and selections are preserved.
2. **Stacking order:** Level 2 Sheet has `z-40`. Level 3 Sheet has `z-50`. Backdrops dim progressively (Level 2 backdrop: `rgba(0,0,0,0.3)`, Level 3 backdrop: `rgba(0,0,0,0.2)`).
3. **Escape/close behavior:** Closing Level 3 returns to Level 2. Closing Level 2 returns to Level 1. Escape key closes the topmost Sheet only.
4. **URL state:** Each drill-down appends a query param for deep-linking:
   - Level 1: `/screener`
   - Level 2: `/screener?manager=123456` (CRD number)
   - Level 3: `/screener?manager=123456&fund=0001234567` (CIK or fund ID)
   - Browser back button closes the topmost Sheet and removes the param.
5. **Sheet width cascade:** Level 2 = `min(85vw, 1200px)`. Level 3 = `min(70vw, 900px)`. This creates a visible "stack" effect — the edge of Level 2 is visible behind Level 3.
6. **Mobile fallback:** Below `768px`, Sheets become full-screen (`w-full`) with a back button instead of stacking.

#### 5.5 — Data Flow

```
Level 1 (page load):
  GET /api/screener/managers?universe=all&page=1&size=20
  → returns paginated managers with fund counts

Level 2 (Sheet open):
  GET /api/screener/managers/{crd}/funds?page=1&size=20
  → returns funds for this manager

Level 3 (Sheet open):
  GET /api/screener/funds/{fund_id}/classes
  → returns share classes for this fund (no pagination — typically <20 classes)
```

**Backend routes needed:**
- [ ] `GET /screener/managers` — paginated, filterable manager list (new or refactored from existing)
- [ ] `GET /screener/managers/{crd}/funds` — funds by manager CRD (may exist via `AdvService.fetch_manager_funds()`)
- [ ] `GET /screener/funds/{fund_id}/classes` — share classes by fund (may exist via `sec_fund_classes` query)

#### 5.6 — Migration from Current Screener

**Current architecture** (`frontends/wealth/src/lib/components/screener/`):
- `CatalogTable` — mixed funds/managers in same table
- `CatalogFilterSidebar` — filters for the mixed view
- `CatalogDetailPanel` — right-side detail panel (replaces with Sheet Level 2)
- `ManagerDetailPanel` — separate manager detail (absorbed into Sheet Level 2)
- `SecManagerTable` — standalone manager table (absorbed into Level 1)

**Migration:**
- [ ] Level 1 replaces `CatalogTable` + `SecManagerTable` → unified manager-first `<DataTable>`
- [ ] Level 2 Sheet replaces `CatalogDetailPanel` → Sheet with funds `<DataTable>`
- [ ] Level 3 Sheet is new — share class view doesn't exist yet as a dedicated table
- [ ] `CatalogFilterSidebar` refactored → universe filter becomes `ToggleGroup`, sidebar filters stay
- [ ] `InstrumentTable`, `SecuritiesTable` → separate routes (not part of the 3-level hierarchy)

**Acceptance:** Phase 5 complete when:
- [ ] Screener primary table shows Fund Managers (not mixed entities)
- [ ] Universe filters (Funds, ETFs, Private, Hedge, UCITS) filter managers by their fund types
- [ ] Click on manager row opens Level 2 Sheet with that manager's funds
- [ ] Click on fund row in Level 2 opens Level 3 Sheet with share classes
- [ ] All 3 levels use the compact `<DataTable>` from Phase 4.4
- [ ] Sheet stacking preserves Level 1 context (scroll, filters, selections)
- [ ] URL state supports deep-linking to any level
- [ ] Escape/back closes topmost Sheet only

---

## System-Wide Impact

### Interaction Graph

- `@investintell/ui` is consumed by both `frontends/wealth/` and `frontends/credit/`
- Phase 3 wrapper refactoring (internal changes) affects Credit frontend passively — **test both frontends after Phase 3**
- Phases 1, 2, 4 only touch Wealth — no Credit impact
- bits-ui transitions/animations replace custom CSS `@keyframes` — verify no layout shift on mobile viewport

### Error Propagation

- shadcn/ui components (bits-ui) manage their own open/close state. Custom `onclick`/`onkeydown` handlers that currently manage state will be REMOVED, not adapted.
- If a component's `bind:open` or `bind:value` is connected to URL params (e.g., tab state in URL), use `onValueChange` callback instead of bind.

### State Lifecycle Risks

- **Tabs:** Current `activeTab` $state variable must be removed or converted to `Tabs.Root bind:value`. If other components read `activeTab` (e.g., conditional data fetching), wire through `onValueChange`.
- **Sheet:** Custom panels that use `{#if open}` conditional rendering will switch to Sheet's internal portal. Ensure no sibling components depend on the panel being in the DOM flow.
- **Command:** GlobalSearch debounce logic must be preserved. cmdk-sv has its own filtering — decide whether to use client-side filtering (cmdk built-in) or server-side (current API-based).

### API Surface Parity

- Credit frontend (`frontends/credit/`) uses the same `@investintell/ui` wrappers. Phase 3 wrapper refactoring must not break Credit. Run `make build-all` after Phase 3.
- `@netz/ui` (older package) may still be referenced somewhere — verify no imports remain.

### Integration Test Scenarios

1. **Screener filter flow:** Apply checkbox filters → verify URL params update → verify table re-renders with filtered data → verify pagination resets to page 1
2. **Sheet dismiss:** Open fund detail panel → press Escape → verify panel closes + no stale state → reopen → verify fresh data loads
3. **Command palette:** Press Cmd+K → type query → verify debounced API call → arrow down → Enter → verify navigation to correct route
4. **Tab + data fetch:** Switch tab on FundDetailPanel → verify tab-specific data loads → switch back → verify previous data is still cached
5. **Accessibility:** All migrated components must pass keyboard navigation (Tab, Enter, Escape, Arrow keys) without custom handlers

---

## Acceptance Criteria

### Functional Requirements

- [ ] Zero `<input type="checkbox">` in `frontends/wealth/src/` — all use `Checkbox` from `@investintell/ui/components/ui/checkbox`
- [ ] Zero raw `<label>` tags — all use `Label` from `@investintell/ui/components/ui/label`
- [ ] Zero `@keyframes spin` — all spinners use `Spinner` from `@investintell/ui/components/ui/spinner`
- [ ] Zero custom tab button groups — all use `Tabs` from `@investintell/ui/components/ui/tabs`
- [ ] Zero custom slide-in panels — all use `Sheet` or `Drawer` from `@investintell/ui/components/ui/sheet`
- [ ] Zero custom pagination — all use `Pagination` from `@investintell/ui/components/ui/pagination`
- [ ] Zero native `<select>` in forms — all use `Select` from `@investintell/ui/components/ui/select`
- [ ] Zero manual click-outside detection for popovers — all use `Popover` from `@investintell/ui/components/ui/popover`
- [ ] `GlobalSearch` rebuilt on `Command` primitive
- [ ] `Combobox` and `DatePicker` composites available in `@investintell/ui`
- [ ] All `@investintell/ui` wrapper components use shadcn primitives internally

### Non-Functional Requirements

- [ ] No visual regression on any existing page (screenshot comparison recommended)
- [ ] Keyboard navigation works on all migrated components (Tab, Enter, Escape, Arrow keys)
- [ ] `make build-all` passes (both Credit and Wealth frontends)
- [ ] `make check-all` passes (lint + types)
- [ ] Bundle size does not increase by more than 5% (bits-ui components are tree-shaken)

### Quality Gates

- [ ] Each phase has a separate PR
- [ ] Each PR includes before/after screenshots of affected pages
- [ ] Each PR tested with keyboard-only navigation
- [ ] Phase 3 PR tested against both Wealth AND Credit frontends

---

## Success Metrics

| Metric | Before | Target |
|---|---|---|
| shadcn primitive adoption rate | 16% (9/55) | 100% |
| Custom CSS for primitive patterns | ~500 lines | 0 lines |
| `@keyframes` in Wealth frontend | 3+ | 0 (chart animations excluded) |
| Raw HTML form elements | 30+ instances | 0 |
| Manual keyboard navigation handlers | 5+ components | 0 (shadcn handles it) |

---

## Dependencies & Prerequisites

1. **bits-ui version:** Verify `packages/investintell-ui/package.json` has bits-ui >= 1.0.0 (already confirmed)
2. **cmdk-sv:** Required for Command component. Verify it's installed or install it.
3. **No blocking backend work** — this is 100% frontend refactoring
4. **Credit frontend smoke test** after Phase 3 — automated or manual

---

## Risk Analysis & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| bits-ui component behavior differs from custom implementation | Medium | Medium | Test each component individually before bulk migration |
| Sheet portal breaks layout assumptions | Low | High | Test side panel heavy pages (screener, analytics) thoroughly |
| Command palette loses existing search UX | Medium | High | Preserve debounced API search; don't rely on cmdk client filtering alone |
| Phase 3 wrapper refactoring breaks Credit frontend | Medium | High | Run `make build-all` + manual smoke test after each wrapper change |
| Bundle size increase | Low | Low | bits-ui is tree-shaken; shadcn components are lightweight |

---

## PR Strategy

| PR | Phase | Scope | Risk |
|---|---|---|---|
| **PR 0a** | Phase 0.1-0.2 | Typography (Inter) + Color palette (Slate) | **High** — visual change across entire app |
| **PR 0b** | Phase 0.3-0.4 | Button variants (flat) + shadcn bridge verify | Medium |
| **PR 0c** | Phase 0.5 | Icons: Phosphor → Lucide (47 files) | Medium — mechanical but high volume |
| PR 1 | Phase 1.1-1.2 | Checkbox + Label in all filter sidebars | Low |
| PR 2 | Phase 1.3-1.6 | Separator + Spinner + Tooltip + Progress | Low |
| PR 3 | Phase 2.1 | Tabs migration (all pages) | Medium |
| PR 4 | Phase 2.2 | Sheet/Drawer migration (all panels) | Medium |
| PR 5 | Phase 2.3-2.5 | Pagination + ToggleGroup + ScrollArea | Low |
| PR 6 | Phase 2.6-2.7 | DropdownMenu + Select + Popover | Medium |
| PR 7 | Phase 3 | Wrapper refactoring (all @investintell/ui internals) | Medium |
| PR 8 | Phase 4.1 | GlobalSearch → Command | Medium |
| PR 9 | Phase 4.2-4.4 | Combobox + DatePicker + DataTable overhaul | Medium |
| **PR 10** | Phase 5.1-5.2 | Screener Level 1 (managers) + Level 2 Sheet (funds) | **High** — UX redesign |
| **PR 11** | Phase 5.3-5.4 | Level 3 Sheet (share classes) + stacking behavior + URL state | Medium |

**Total: 14 PRs** (3 foundation + 9 component migration + 2 screener redesign)

---

## Sources & References

### Origin

- **Gap analysis:** [docs/audit/shadcn-ui-gap-analysis.md](../audit/shadcn-ui-gap-analysis.md) — complete primitive inventory and gap quantification
- **Figma reference:** https://www.figma.com/design/hjrBXc90IlR5SHE2HiFGEU/-shadcn-ui---Design-System--Community-

### Internal References

- shadcn/ui primitives: `packages/investintell-ui/src/lib/components/ui/` (55 directories)
- Wrapper components: `packages/investintell-ui/src/lib/components/` (45 wrappers)
- Layout components: `packages/investintell-ui/src/lib/layouts/` (8 layouts)
- Design tokens: `packages/investintell-ui/src/lib/styles/tokens.css` (colors, radius, semantic)
- Typography tokens: `packages/investintell-ui/src/lib/styles/typography.css` (font, sizes, weights)
- Wealth frontend components: `frontends/wealth/src/lib/components/` (80 components)

### External References

- shadcn-svelte: https://www.shadcn-svelte.com/docs
- bits-ui: https://www.bits-ui.com/docs
- cmdk-sv: https://cmdk-sv.com/
