# Frontend UX Audit — 2026-03-22

Cross-frontend audit covering **Wealth OS**, **Credit Intelligence**, and **Admin** panels.
Evidence collected from live screenshots, CSS token analysis, route exploration, and component inspection.

---

## Executive Summary

| Severity | Count | Category |
|----------|-------|----------|
| **Critical** | 3 | Architecture (page sprawl), theme system, select indicator |
| **High** | 4 | Dark mode contrast, nav overflow, spacing inconsistency, filter UX |
| **Medium** | 5 | Toggle placement, empty states, redundant routes, mobile nav, missing ESMA route |
| **Low** | 3 | Badge inconsistency, animation jank, font fallback |

**Top 3 structural problems:**
1. Funds, Instruments, Universe, and ESMA Universe exist as standalone pages — they should be filter modes/tabs within the **Screener** (the Manager Screener plan already defines this unified model).
2. Dark/light theme switch barely changes the UI — only border colors shift visibly. Background and surface tokens have too little contrast in dark mode and may not propagate to all components.
3. Select/dropdown fields use `appearance-none` with no custom chevron indicator — users see a blank rectangle with no affordance that it's interactive.

---

## F1 — Theme System: Dark/Light Modes Nearly Identical

### Evidence

**Screenshots comparison:** Switching between dark and light mode produces nearly indistinguishable results. Only border colors shift from `#223146` (dark) to `#d6deea` (light). Background, cards, and text remain visually similar at a glance.

**Root cause analysis — three contributing factors:**

#### F1.1 — Dark mode surface contrast too low

```
--netz-surface:          #0f1826  (page background)
--netz-surface-elevated: #19273a  (cards)
--netz-surface-alt:      #142030  (alternate)
```

Delta between page bg and cards:
- R: 15 → 25 = **+10**
- G: 24 → 39 = **+15**
- B: 38 → 58 = **+20**

This ~6% luminance difference makes cards virtually invisible against the background. Compare with industry standards (GitHub dark: `#0d1117` bg vs `#161b22` card = similar but with stronger border contrast + elevation shadow).

**Fix:** Increase surface-elevated to `#1e3048` or similar (+30% luminance delta). Alternatively, add visible elevation shadows in dark mode (the current `--netz-shadow-2` has `inset 0 1px 0 rgba(255,255,255,0.05)` which is imperceptible).

#### F1.2 — ThemeToggle defaults to dark

`ThemeToggle.svelte:13` — `getInitialTheme()` returns `"dark"` when no `data-theme` attribute is set. Combined with possible SSR mismatch (server renders without `data-theme`, client hydrates to dark), users may never see light mode.

```typescript
// Current: defaults to dark
return "dark";
// Should: respect system preference
return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
```

#### F1.3 — `--netz-page-background` gradient defined but unused

`tokens.css:89-93` defines a page background gradient:
```css
--netz-page-background: linear-gradient(180deg,
    color-mix(in srgb, var(--netz-brand-light) 42%, var(--netz-surface) 58%) 0%,
    var(--netz-surface) 220px);
```

This gradient provides a subtle top wash that differentiates light from dark. But `AppLayout.svelte:152` uses `var(--netz-surface)` directly:
```css
.netz-app-layout__main { background: var(--netz-surface, #f9fafb); }
```

The gradient is never applied. In light mode, this costs the subtle brand-tinted header zone that would visually distinguish it from dark mode.

### Recommendation

1. Increase dark mode surface elevation delta (card bg `#1e3048`, alt `#172638`)
2. Respect `prefers-color-scheme` as initial theme default
3. Apply `--netz-page-background` to `.netz-app-layout__main` or `body`
4. Add `--netz-shadow-card` to all `Card`/`SectionCard` components (already defined but not universally applied)

---

## F2 — Navigation Overflow (Wealth OS: 12+ Items)

### Evidence

Wealth OS `+layout.svelte` defines **12 nav items** in a single horizontal bar:

```
Dashboard | Portfolios | Risk | Funds | Screener | Universe | Instruments | Documents | Analytics | Exposure | Allocation | Macro
```

Screenshots show items truncated (`Expo...`) and the theme toggle partially cut off. On 1440px screens, 12 items × ~90px average = 1080px + brand (120px) + trailing (80px) = 1280px. Anything below 1440px causes horizontal scroll with hidden scrollbar (`scrollbar-width: none`), making items invisibly unreachable.

The Credit frontend has only **3 nav items** (Dashboard, Funds, Copilot) — a completely different navigation density.

### Root cause

Too many top-level concepts. Per the Manager Screener plan (`docs/plans/2026-03-21`), Funds/Instruments/Universe/ESMA Universe should be data sources within the Screener, not separate destinations. See **F3** for the structural fix.

### Recommendation

Consolidate to **7-8 max top-level items**:

```
Dashboard | Portfolios | Screener | Risk | Analytics | Documents | Macro
```

Where **Screener** absorbs: Funds, Instruments, Universe, ESMA Universe, Manager Screener (as tabs/filter modes). Where **Analytics** absorbs: Exposure, Allocation, Backtest (as tabs). Where **Portfolios** absorbs: Model Portfolios (already at `/model-portfolios`).

---

## F3 — Page Sprawl: Standalone Pages That Should Be Screener Modes

### Evidence

**Current state:** 6 separate pages that query related data independently:

| Route | Purpose | Endpoints | Should be |
|-------|---------|-----------|-----------|
| `/screener` | 3-layer instrument screening funnel | `GET /screener/results`, `POST /screener/run` | **Screener main view** |
| `/manager-screener` | SEC manager discovery/monitoring | `GET /manager-screener` (planned) | **Screener tab: "Managers"** |
| `/funds` | Fund universe + DD pipeline status | `GET /funds` | **Screener tab: "Funds"** |
| `/instruments` | Instrument CRUD + Yahoo/CSV import | `GET /instruments`, `POST /instruments` | **Screener tab: "Instruments"** |
| `/universe` | Approval workflow (pending/approved) | `GET /universe/funds` | **Screener tab: "Universe"** |
| ESMA Universe (planned) | ESMA UCITS register | `GET /esma/funds` (planned) | **Screener tab: "ESMA"** |

**Why this is wrong:**

1. **The Manager Screener brainstorm explicitly defines a unified model** — filter blocks (firm attributes, portfolio metrics, drift signals, institutional pedigree, universe status) that cross-cut all these data sources. Having them as separate pages forces users to navigate between 6 pages to answer one question: "which managers/funds match my mandate?"

2. **Data redundancy** — Funds page shows `name, manager, strategy, status, score`. Screener results show `name, isin, ticker, instrument_type, score`. Instruments page shows `ticker, name, asset_class, currency`. These are the same entities viewed through different lenses. The Screener's filter system should dynamically select which columns and filters to show based on the active tab/mode.

3. **Action fragmentation** — "Add to Universe" lives on the Universe page. "Run Screening" lives on the Screener page. "Import from Yahoo" lives on the Instruments page. A unified Screener would surface the right action for the current view context.

4. **Backend supports this** — The planned `manager_screener_sql.py` uses a dynamic SQL builder with `LEFT JOIN instruments_universe` to show universe status inline. This same pattern should extend to all entity types: instruments, funds, ESMA registrations.

### Recommendation

**Single `/screener` route with tabs:**

```
Screener
├── Instruments (current /screener — 3-layer funnel)
├── Funds (current /funds — DD pipeline status)
├── Managers (planned /manager-screener — SEC ADV/13F)
├── ESMA (planned — UCITS register)
└── Universe (current /universe — approval workflow)
```

Each tab shares:
- **Filter sidebar** (from Manager Screener plan's filter blocks)
- **Results table** with tab-specific columns
- **ContextPanel** for drill-down
- **Bulk actions** appropriate to the tab

The `/instruments` CRUD operations (create, import) become a management dialog accessible from the Instruments tab header, not a standalone page.

---

## F4 — Select Component: No Dropdown Indicator

### Evidence

`Select.svelte:36` uses `appearance-none` to strip native browser chrome but provides **no replacement indicator**:

```svelte
<select class="... appearance-none ... pr-10 ...">
```

The `pr-10` (right padding 40px) reserves space for a chevron that doesn't exist. The result: a rectangular input field with no visual cue that it's a dropdown. Users must click it to discover it's interactive.

Screenshot evidence: Documents page shows a "Select..." field that looks like a disabled text input.

### Root cause

`appearance-none` removes the native dropdown arrow. No SVG chevron, `background-image`, or `::after` pseudo-element replaces it.

### Recommendation

Add a CSS chevron via `background-image` on the `.netz-ui-field` select or add an SVG overlay:

```css
select.netz-ui-field {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236f7f93' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    background-size: 16px;
}
```

Or wrap the `<select>` in a container with an absolutely-positioned chevron icon (more accessible, supports dark mode color swap via CSS variable).

---

## F5 — Dark Mode Background Excessively Dark

### Evidence

`--netz-surface: #0f1826` is luminance ~6%. Combined with:
- TopNav bg: `color-mix(surface-highlight 92%, transparent)` ≈ `#19273a` with 92% opacity ≈ still very dark
- Card bg: `#19273a` ≈ luminance ~10%
- Border: `#223146` ≈ luminance ~14%

The entire UI is a narrow band of 6-14% luminance. For comparison:
- GitHub Dark: bg `#0d1117` (~4%), card `#161b22` (~8%), border `#30363d` (~20%) — wider spread
- Linear Dark: bg `#1a1a2e` (~8%), card `#242442` (~14%) — higher card elevation
- Vercel Dark: bg `#000000` (0%), card `#111111` (~7%), border `#333333` (~20%) — extreme contrast

**Netz dark mode lacks the luminance spread** that makes cards readable against the background.

### Recommendation

Shift the dark palette to create more spread:

| Token | Current | Proposed | Delta |
|-------|---------|----------|-------|
| `--netz-surface` | `#0f1826` (6%) | `#0c1220` (4%) | Darker bg |
| `--netz-surface-elevated` | `#19273a` (10%) | `#1a2d44` (13%) | Lighter cards |
| `--netz-surface-alt` | `#142030` (8%) | `#152638` (10%) | Middle tier |
| `--netz-surface-raised` | `#213147` (14%) | `#243a52` (17%) | Higher elevation |
| `--netz-border-subtle` | `#223146` (14%) | `#2a3d55` (18%) | More visible borders |

Net effect: bg-to-card delta goes from 4% → 9% luminance, making cards visible without losing the dark aesthetic.

---

## F6 — Spacing Inconsistencies

### Evidence

Two competing spacing patterns across pages:

**Pattern A (token-based):**
```svelte
<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
```
Used in: some wealth pages, consistent with design system.

**Pattern B (hardcoded Tailwind):**
```svelte
<div class="space-y-6 p-6">
```
Used in: admin pages, some credit pages, some wealth pages.

These produce different values:
- `--netz-space-section-gap`: `clamp(28px, 1rem + 2vw, 48px)` — responsive, 28-48px
- `space-y-6`: fixed 24px
- `--netz-space-page-gutter`: `clamp(20px, 1rem + 1vw, 32px)` — responsive, 20-32px
- `p-6`: fixed 24px

On a 1920px viewport: token-based = 48px section gap, 32px gutter. Hardcoded = 24px both. That's a 2x density difference between pages.

### Recommendation

All pages should use token-based spacing exclusively. Grep for `space-y-6 p-6` and replace with `space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)`.

---

## F7 — Theme Toggle Placement and Visibility

### Evidence

Screenshots show the theme toggle partially cut off or compressed at the right edge of the TopNav. With 12 nav items consuming most horizontal space, the `.netz-topnav__trailing` section (containing ThemeToggle) is squeezed.

`TopNav.svelte:203-208`:
```css
.netz-topnav__trailing {
    margin-left: auto;
    flex-shrink: 0;
}
```

The `flex-shrink: 0` prevents the toggle from shrinking, but the nav items use `overflow-x: auto` with hidden scrollbar, meaning they don't shrink either. The trailing section can be pushed off-screen entirely on narrower viewports.

### Recommendation

1. Reduce nav items (see F2)
2. Add `min-width: 0` to `.netz-topnav__items` so items can compress
3. Consider moving the theme toggle into a settings dropdown or user menu to free trailing space

---

## F8 — Admin Frontend: Missing Theme Toggle UI

### Evidence

Admin `+layout.svelte` uses `AppLayout` which includes `ThemeToggle` automatically. However, the admin nav has only 5 items (Health, Inspect, Tenants, Config, Prompts) — toggle should be visible. Screenshots show it working but the admin has no explicit dark mode testing evidence. Since admin inherits the same token system, all F1/F5 issues apply equally.

---

## F9 — ESMA Universe: Nav Link Without Route

### Evidence

Screenshots show "ESMA Universe" in the Wealth OS navigation bar. However:
- No route exists at `frontends/wealth/src/routes/(team)/esma-universe/`
- The current `+layout.svelte` does not include an "ESMA Universe" nav item
- The ESMA seed pipeline is Phase 1.5 (in progress per data providers reference)

This is either a local addition not committed or a planned addition. Either way, per F3, it should not be a standalone route — it should be a tab within Screener.

---

## F10 — Empty State UX: No Progressive Disclosure

### Evidence

Dashboard shows three empty placeholder cards (`Awaiting data...`) with no content, no skeleton animation, and no call-to-action. Documents page shows "No Documents" with generic "Upload documents to start the ingestion pipeline" — no guidance on what to upload or what happens next.

"Drift Alerts" shows "No active drift alerts" — correct empty state text but visually indistinguishable from a loading state due to low-contrast dark mode.

### Recommendation

1. Add skeleton pulse animation to loading states
2. Add specific CTAs to empty states ("Upload your first fund prospectus" > "Upload documents")
3. Differentiate empty state (data exists but filtered to zero) from zero state (no data yet) — different icon, different message, different action

---

## F11 — Wealth Nav vs Credit Nav: Structural Asymmetry

### Evidence

| Frontend | Nav Style | Items | Sub-navigation |
|----------|-----------|-------|----------------|
| Credit | TopNav (3 items) + ContextSidebar | 3 | Fund-scoped sidebar (Pipeline, Portfolio, Documents, Reporting) |
| Wealth | TopNav (12 items) + no sidebar | 12 | None |
| Admin | TopNav (5 items) + tenant sub-nav | 5 | Inline links on tenant detail |

Credit uses a 2-level hierarchy (TopNav for module, Sidebar for context within a fund). Wealth puts everything flat in TopNav. This creates cognitive overload in Wealth — 12 items with no grouping vs Credit's focused 3+4 structure.

### Recommendation

Wealth should adopt a similar 2-level pattern:
- **TopNav:** Dashboard, Screener, Portfolios, Risk, Analytics, Documents, Macro (7 items)
- **ContextSidebar (when drilling into a fund/portfolio):** Fund detail tabs, portfolio breakdown, etc.

---

## F12 — `netz-ui-field` Focus States in Dark Mode

### Evidence

`index.css:247-253`:
```css
.netz-ui-field {
    border: 1px solid var(--netz-border-subtle);
    background: var(--netz-surface-raised);
    box-shadow: var(--netz-shadow-inset);
}
```

In dark mode:
- `--netz-border-subtle: #223146` (barely visible against `#19273a` card bg)
- `--netz-surface-raised: #213147` (nearly identical to card bg `#19273a`)
- `--netz-shadow-inset: inset 0 1px 0 rgba(255,255,255,0.07)` (invisible)

Result: form fields are invisible against their card containers. Users can't distinguish where one field ends and the card begins.

### Recommendation

Dark mode fields need stronger differentiation:
```css
[data-theme="dark"] .netz-ui-field {
    border-color: var(--netz-border);       /* #31425a instead of #223146 */
    background: var(--netz-surface-inset);  /* #0b121c — darker than card */
}
```

---

## Summary: Priority Action Items

### Phase 1 — Theme Fix (tokens.css + Select.svelte)
1. Fix dark mode surface contrast (F1.1, F5)
2. Add dropdown chevron to Select component (F4)
3. Fix field visibility in dark mode (F12)
4. Respect `prefers-color-scheme` in ThemeToggle default (F1.2)
5. Apply `--netz-page-background` to main layout (F1.3)

### Phase 2 — Navigation Consolidation (layout + routing)
6. Merge Funds/Instruments/Universe/ESMA into Screener tabs (F3)
7. Reduce Wealth nav to 7-8 items (F2)
8. Group Analytics/Exposure/Allocation under "Analytics" (F2)

### Phase 3 — Spacing + Polish
9. Standardize all pages on token-based spacing (F6)
10. Improve empty states with specific CTAs (F10)
11. Fix theme toggle truncation (F7)

---

## Files Referenced

| File | Issues |
|------|--------|
| `packages/ui/src/lib/styles/tokens.css` | F1, F5, F12 |
| `packages/ui/src/lib/components/ThemeToggle.svelte` | F1.2, F7 |
| `packages/ui/src/lib/components/Select.svelte` | F4 |
| `packages/ui/src/lib/styles/index.css` (`.netz-ui-field`) | F4, F12 |
| `packages/ui/src/lib/layouts/AppLayout.svelte` | F1.3 |
| `packages/ui/src/lib/layouts/TopNav.svelte` | F2, F7 |
| `frontends/wealth/src/routes/+layout.svelte` | F2, F3, F9 |
| `frontends/wealth/src/routes/(team)/screener/+page.svelte` | F3 |
| `frontends/wealth/src/routes/(team)/funds/+page.svelte` | F3 |
| `frontends/wealth/src/routes/(team)/instruments/+page.svelte` | F3 |
| `frontends/wealth/src/routes/(team)/universe/+page.svelte` | F3 |
| `frontends/credit/src/routes/+layout.svelte` | F11 |
| `frontends/admin/src/routes/+layout.svelte` | F8 |
| All `+page.svelte` files using `space-y-6 p-6` | F6 |
