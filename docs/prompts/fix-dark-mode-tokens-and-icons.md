# Fix: Dark Mode Token Consistency + Icon Library Migration

## Context

InvestIntell Wealth OS — SvelteKit 5 frontend (`frontends/wealth/`).
Design system: `packages/investintell-ui/` (tokens in `src/lib/styles/tokens.css`).

The design tokens were recently migrated to a **dark-first zinc + gold** palette:
- `:root` is now dark (`--ii-bg: #18181b`, `--ii-brand-primary: #c9a84c`)
- `.light` is the light-mode override
- Token bridge for shadcn: `--background`, `--primary`, `--border` etc. all point to `--ii-*` vars

**Problem:** Several components were written for the old light-mode-first system and use
hardcoded color values instead of tokens. They break visually in dark mode.

---

## Task 1 — Migrate icon library: lucide-svelte → phosphor-svelte (Light weight)

Phosphor Light weight is more sophisticated and appropriate for an institutional platform.

### Step 1a — Install packages

```bash
# In monorepo root
pnpm add phosphor-svelte --filter netz-wealth-os
pnpm add phosphor-svelte --filter @investintell/ui
pnpm remove lucide-svelte --filter netz-wealth-os
pnpm remove @lucide/svelte --filter @investintell/ui
pnpm remove lucide-svelte --filter @investintell/ui
```

### Step 1b — Update `+layout.svelte` imports

File: `frontends/wealth/src/routes/(app)/+layout.svelte`

Replace the lucide import block:
```ts
// OLD
import {
    ShieldCheck, Layers, Database, Briefcase, Search,
    ClipboardList, BarChart2, Globe, Zap, Newspaper,
    FileText, Settings, Bot, ChevronDown,
    Search as SearchIcon,
} from "lucide-svelte";

// NEW — Phosphor Light weight
import {
    ShieldCheck, Stack, Database, Briefcase, MagnifyingGlass,
    ClipboardText, ChartBar, Globe, Lightning, Newspaper,
    FileText, GearSix, Robot, CaretDown,
} from "phosphor-svelte";
```

Update references in the nav items array (same file):
```ts
// OLD → NEW icon names in the sections[] array:
// BarChart2   → ChartBar       (Dashboard, Risk)
// Search      → MagnifyingGlass (Screener)
// ClipboardList → ClipboardText (DD Reports)
// Database    → Database        (Assets Universe — same name)
// ShieldCheck → ShieldCheck     (Investment Policy — same name)
// Globe       → Globe           (Macro — same name)
// Layers      → Stack           (Portfolio Builder)
// Briefcase   → Briefcase       (Portfolios — same name)
// Zap         → Lightning       (Risk)
// Newspaper   → Newspaper       (Content — same name)
// FileText    → FileText        (Documents — same name)
// Settings    → GearSix         (System)
```

Update AI button in topbar:
```svelte
<!-- OLD -->
<Bot size={18} strokeWidth={1.5} />
<!-- NEW — Phosphor uses weight prop -->
<Robot size={18} weight="light" />
```

Update ChevronDown → CaretDown for section accordion:
```svelte
<!-- OLD -->
<ChevronDown size={12} strokeWidth={2} class="section-chevron ..." />
<!-- NEW -->
<CaretDown size={12} weight="light" class="section-chevron ..." />
```

Update SearchIcon → MagnifyingGlass in topbar search:
```svelte
<!-- OLD -->
<SearchIcon size={15} strokeWidth={1.5} class="ii-topbar-search-icon" />
<!-- NEW -->
<MagnifyingGlass size={15} weight="light" class="ii-topbar-search-icon" />
```

All nav item icon usages (inside `{@const Icon = item.icon}` blocks):
```svelte
<!-- OLD -->
<Icon size={18} strokeWidth={1.5} />
<!-- NEW -->
<Icon size={18} weight="light" />
```

### Step 1c — Update `@investintell/ui` component imports

Scan `packages/investintell-ui/src/lib/` for any files importing from `lucide-svelte`
or `@lucide/svelte` and replace with equivalent `phosphor-svelte` icons.

Run to find them:
```bash
grep -r "from \"lucide-svelte\"\|from \"@lucide/svelte\"" packages/investintell-ui/src/
```

Apply same mapping as above. For any icon without a clear equivalent, use the closest
Phosphor icon and note it in a comment. Use `weight="light"` everywhere.

### Step 1d — Update `package.json` description in `@investintell/ui`

```json
"description": "InvestIntell Design System — shadcn-svelte + IBM Plex + Phosphor Icons + analytical components"
```

---

## Task 2 — Fix hardcoded colors in `+layout.svelte`

File: `frontends/wealth/src/routes/(app)/+layout.svelte`

### 2a — Fix the logo SVG (inline in template)

The SVG has hardcoded `fill="#2563EB"` (old blue) and `fill="#64748B"`. Replace with
gold accent and zinc muted:

```svelte
<!-- OLD -->
<circle cx="4"  cy="4"  r="1.5" fill="#2563EB"/>
<circle cx="10" cy="4"  r="1.5" fill="#2563EB"/>
<circle cx="16" cy="4"  r="1.5" fill="#2563EB"/>
<circle cx="10" cy="12" r="2"   fill="#2563EB"/>
<circle cx="4"  cy="20" r="1.5" fill="#64748B"/>
<circle cx="10" cy="20" r="1.5" fill="#64748B"/>
<circle cx="16" cy="20" r="1.5" fill="#64748B"/>
<line x1="4"  y1="4"  x2="10" y2="12" stroke="#2563EB" stroke-width="1" stroke-linecap="round"/>
<line x1="16" y1="4"  x2="10" y2="12" stroke="#2563EB" stroke-width="1" stroke-linecap="round"/>
<line x1="4"  y1="20" x2="10" y2="12" stroke="#64748B" stroke-width="1" stroke-linecap="round"/>
<line x1="16" y1="20" x2="10" y2="12" stroke="#64748B" stroke-width="1" stroke-linecap="round"/>

<!-- NEW — use currentColor driven by CSS vars -->
<style>
  .logo-top    { fill: var(--ii-brand-primary); }
  .logo-bottom { fill: var(--ii-text-tertiary); }
  .logo-line-top    { stroke: var(--ii-brand-primary); }
  .logo-line-bottom { stroke: var(--ii-text-tertiary); }
</style>
<circle class="logo-top" cx="4"  cy="4"  r="1.5"/>
<circle class="logo-top" cx="10" cy="4"  r="1.5"/>
<circle class="logo-top" cx="16" cy="4"  r="1.5"/>
<circle class="logo-top" cx="10" cy="12" r="2"/>
<circle class="logo-bottom" cx="4"  cy="20" r="1.5"/>
<circle class="logo-bottom" cx="10" cy="20" r="1.5"/>
<circle class="logo-bottom" cx="16" cy="20" r="1.5"/>
<line class="logo-line-top"    x1="4"  y1="4"  x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
<line class="logo-line-top"    x1="16" y1="4"  x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
<line class="logo-line-bottom" x1="4"  y1="20" x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
<line class="logo-line-bottom" x1="16" y1="20" x2="10" y2="12" stroke-width="1" stroke-linecap="round"/>
```

### 2b — Fix nav item colors in `<style>` block

Replace ALL hardcoded color values in the nav item CSS:

```css
/* OLD */
.nav-item {
    color: #62748e;
}
.nav-item:hover {
    background: rgba(239, 246, 255, 0.4);   /* light blue wash — invisible on dark */
    color: var(--ii-text-primary);
}
.nav-item.active {
    background: rgba(239, 246, 255, 0.8);   /* light blue — broken on dark */
    color: #1447e6;
    font-weight: 700;
}
.section-label {
    color: #90a1b9;
}
.section-header :global(.section-chevron) {
    color: #90a1b9;
    ...
}

/* NEW */
.nav-item {
    color: var(--ii-text-secondary);
}
.nav-item:hover {
    background: var(--ii-bg-hover);
    color: var(--ii-text-primary);
}
.nav-item.active {
    background: var(--ii-accent-soft);
    color: var(--ii-brand-primary);
    font-weight: 700;
}
.section-label {
    color: var(--ii-text-tertiary);
}
.section-header :global(.section-chevron) {
    color: var(--ii-text-tertiary);
    ...
}
```

Also fix the sidebar background. Currently hardcoded to `--ii-surface-alt`. That's correct
via token, but double-check the sidebar uses `background: var(--ii-surface)` (slightly
elevated from bg), not a hardcoded value:
```css
.ii-sidebar {
    background: var(--ii-surface);   /* was: var(--ii-surface-alt) — too close to bg */
}
```

---

## Task 3 — Fix hardcoded colors in `screener/+page.svelte`

File: `frontends/wealth/src/routes/(app)/screener/+page.svelte`

The main container renders as a white box on a dark background. Fix:

```css
/* OLD */
.scr-results {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
}
.scr-btn--outline {
    background: white;
    border: 1px solid #e2e8f0;
    color: #45556c;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1);
}
.scr-btn--outline:hover {
    background: #f8fafc;
    border-color: #cbd5e1;
}

/* NEW */
.scr-results {
    background: var(--ii-surface);
    border: 1px solid var(--ii-border-subtle);
    border-radius: var(--ii-radius-lg);
    overflow: hidden;
    box-shadow: none;
}
.scr-btn--outline {
    background: transparent;
    border: 1px solid var(--ii-border);
    color: var(--ii-text-secondary);
}
.scr-btn--outline:hover {
    background: var(--ii-surface-alt);
    border-color: var(--ii-border-strong);
    color: var(--ii-text-primary);
}
```

---

## Task 4 — Fix hardcoded colors in `screener.css`

File: `frontends/wealth/src/lib/components/screener/screener.css`

This file has ~25 hardcoded light-mode values. Replace ALL of them with tokens.
Do a search for each pattern and replace:

| Hardcoded value | Replace with |
|---|---|
| `background: white` | `background: var(--ii-surface)` |
| `background: #f8fafc` | `background: var(--ii-surface-alt)` |
| `background: #f1f5f9` | `background: var(--ii-surface-alt)` |
| `border: 1px solid #e2e8f0` | `border: 1px solid var(--ii-border-subtle)` |
| `border-color: #e2e8f0` | `border-color: var(--ii-border-subtle)` |
| `border-bottom: 1px solid #e2e8f0` | `border-bottom: 1px solid var(--ii-border-subtle)` |
| `border-bottom: 1px solid #f1f5f9` | `border-bottom: 1px solid var(--ii-border-subtle)` |
| `color: #62748e` | `color: var(--ii-text-secondary)` |
| `color: #90a1b9` | `color: var(--ii-text-muted)` |
| `color: #1d293d` | `color: var(--ii-text-primary)` |
| `color: #314158` | `color: var(--ii-text-primary)` |
| `color: #45556c` | `color: var(--ii-text-secondary)` |
| `color: #155dfc` | `color: var(--ii-brand-primary)` |
| `color: #1447e6` | `color: var(--ii-brand-primary)` |
| `background: #eff6ff` | `background: var(--ii-accent-soft)` |
| `border: 1px solid #dbeafe` | `border: 1px solid var(--ii-border-accent)` |
| `background: #ecfdf5` | `background: color-mix(in srgb, var(--ii-success) 10%, var(--ii-surface))` |
| `background: #fef9ec` | `background: color-mix(in srgb, var(--ii-warning) 10%, var(--ii-surface))` |
| `background: #fef2f2` | `background: color-mix(in srgb, var(--ii-danger) 10%, var(--ii-surface))` |
| `background: #f1f5f9` (mini-bar-track) | `background: var(--ii-surface-raised)` |
| `font-family: Consolas, ...` | `font-family: var(--ii-font-mono)` |

For the `scr-input` and `scr-select` fields specifically:
```css
/* OLD */
.scr-input, .scr-select {
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    background: white;
    ...
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.scr-input:focus, .scr-select:focus {
    border-color: #155dfc;
    box-shadow: 0 0 0 3px rgba(21,93,252,0.1);
}

/* NEW */
.scr-input, .scr-select {
    border: 1px solid var(--ii-border);
    border-radius: var(--ii-radius-md);
    background: var(--ii-surface-inset);
    ...
    box-shadow: none;
}
.scr-input:focus, .scr-select:focus {
    border-color: var(--ii-border-focus);
    box-shadow: 0 0 0 3px var(--ii-focus-ring);
}
```

For the table headers (`.scr-table th`):
```css
/* OLD */
.scr-table th {
    color: #62748e;
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}
.scr-table td {
    border-bottom: 1px solid #f1f5f9;
}

/* NEW */
.scr-table th {
    color: var(--ii-text-secondary);
    background: var(--ii-surface-alt);
    border-top: 1px solid var(--ii-border-subtle);
    border-bottom: 1px solid var(--ii-border-subtle);
}
.scr-table td {
    border-bottom: 1px solid var(--ii-border-subtle);
}
```

For the data header border:
```css
/* OLD */
.scr-data-header {
    border-bottom: 1px solid #e2e8f0;
}
.scr-data-count {
    color: #1d293d;
}

/* NEW */
.scr-data-header {
    border-bottom: 1px solid var(--ii-border-subtle);
}
.scr-data-count {
    color: var(--ii-text-primary);
}
```

For instrument row hover:
```css
/* OLD */
.scr-inst-row:hover { background: rgba(248,250,252,0.8); }
.inst-name          { color: #1d293d; }
.inst-ids           { color: #62748e; background: #f1f5f9; }
.std-manager        { color: #155dfc; }

/* NEW */
.scr-inst-row:hover { background: var(--ii-bg-hover); }
.inst-name          { color: var(--ii-text-primary); }
.inst-ids           { color: var(--ii-text-secondary); background: var(--ii-surface-raised); }
.std-manager        { color: var(--ii-brand-primary); }
```

---

## Task 5 — Fix hardcoded colors in `macro/+page.svelte`

File: `frontends/wealth/src/routes/(app)/macro/+page.svelte`

The local `<style>` block has hardcoded light-mode values. Apply same mapping:

```css
/* Specific values to fix: */

/* Region chevron */
.region-chevron { background: #eff6ff; color: #155dfc; }
→ .region-chevron { background: var(--ii-accent-soft); color: var(--ii-brand-primary); }

/* Region body (light wash) */
.region-body { background: rgba(248,250,252,0.5); border-top: 1px solid #f1f5f9; }
→ .region-body { background: var(--ii-surface-inset); border-top: 1px solid var(--ii-border-subtle); }

/* Mini bar track */
.mini-bar-track { background: #f1f5f9; }
→ .mini-bar-track { background: var(--ii-surface-raised); }

/* Labels */
color: #90a1b9  → color: var(--ii-text-muted)
color: #62748e  → color: var(--ii-text-secondary)

/* Breakdown section */
.breakdown-title { color: #62748e; }
→ .breakdown-title { color: var(--ii-text-secondary); }
```

Also update the `scoreColor()` and `stressBarColor()` JS functions to use the semantic
token values aligned with the new palette:
```ts
// OLD
function scoreColor(score: number): string {
    if (score >= 70) return "#22c55e";
    if (score >= 40) return "#fe9a00";
    return "#ff2056";
}
function stressBarColor(value: number): string {
    if (value > 80) return "#ff2056";
    if (value >= 40) return "#fe9a00";
    return "#155dfc";
}

// NEW — align with --ii-success, --ii-warning, --ii-danger, --ii-brand-primary
function scoreColor(score: number): string {
    if (score >= 70) return "#3fb950";   /* --ii-success */
    if (score >= 40) return "#e3b341";   /* --ii-warning */
    return "#f85149";                     /* --ii-danger */
}
function stressBarColor(value: number): string {
    if (value > 80) return "#f85149";    /* --ii-danger */
    if (value >= 40) return "#e3b341";   /* --ii-warning */
    return "#c9a84c";                    /* --ii-brand-primary (gold) */
}
```

---

## Definition of Done

- [ ] `pnpm install` succeeds at monorepo root
- [ ] `pnpm --filter netz-wealth-os run check` passes (no type errors)
- [ ] All icons render — no missing import errors in console
- [ ] Nav sidebar: active item shows gold highlight, not blue
- [ ] Logo SVG circles: top nodes gold, bottom nodes zinc muted
- [ ] Screener page: filter sidebar and catalog table have dark zinc background, not white
- [ ] Screener inputs: dark inset background, gold focus ring
- [ ] Screener table headers: zinc surface, not white
- [ ] Macro page: region cards have dark zinc body, not near-white wash
- [ ] `pnpm --filter netz-wealth-os run build` succeeds

## What NOT to do

- Do NOT change anything in `tokens.css` or `globals.css` — those are already correct
- Do NOT use `.dark` class conditionals — all fixes must use tokens that respond automatically
- Do NOT add `!important` anywhere
- Do NOT change `border-radius: 14px` on screener filter sidebar checkboxes (those are intentionally pill-shaped)
- Do NOT touch any backend files
- Do NOT modify files in `frontends/credit/`
- Do NOT change the icon sizes or layout — only the import source and `weight` prop
- After replacing lucide imports, verify no residual `strokeWidth` props remain — Phosphor uses `weight` not `strokeWidth`
