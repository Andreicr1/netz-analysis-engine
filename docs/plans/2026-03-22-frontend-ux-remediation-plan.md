# Frontend UX Remediation Plan — 2026-03-22

Backlog derived from two audit documents:
- `docs/audit/2026-03-22-frontend-ux-audit.md` (F1–F12)
- `docs/audit/2026-03-22-interface-design-critique.md` (sections 1–12)

---

## Phase 1 — Dark Mode & Token Fix (visual foundation)

**Goal:** Make dark mode usable. Cards visible, fields distinguishable, hierarchy recoverable.

### T1.1 — Increase dark mode surface luminance spread

**Finding:** F1.1, F5, Critique §3
**File:** `packages/ui/src/lib/styles/tokens.css` (dark mode block, ~line 100+)
**Problem:** bg-to-card delta is ~4% luminance — cards invisible against page background.

**Changes:**
```
--netz-surface:          #0f1826 → #0c1220   (darker page bg, 4%)
--netz-surface-elevated: #19273a → #1a2d44   (lighter cards, 13%)
--netz-surface-alt:      #142030 → #152638   (middle tier, 10%)
--netz-surface-raised:   #213147 → #243a52   (higher elevation, 17%)
--netz-surface-inset:    #0b121c → keep      (already darkest)
--netz-border-subtle:    #223146 → #2a3d55   (more visible borders, 18%)
--netz-border:           #31425a → #345270   (stronger borders)
```

Net effect: bg-to-card delta 4% → 9%. Borders go from 14% → 18% luminance.

**Validation:** Screenshot comparison before/after — cards must be visually distinct from background at arm's length.

---

### T1.2 — Dark mode shadow → border promotion

**Finding:** Critique §5
**File:** `packages/ui/src/lib/styles/tokens.css`
**Problem:** `--netz-shadow-card` uses `rgba(0,0,0,0.28)` which is invisible on dark backgrounds. Dark mode relies on shadows that don't work.

**Changes:**
- Add dark-mode-specific shadow overrides with lighter `rgba` values:
```css
[data-theme="dark"] {
    --netz-shadow-card: 0 1px 3px rgba(0,0,0,0.5), 0 0 0 1px var(--netz-border-subtle);
    --netz-shadow-1:    0 1px 2px rgba(0,0,0,0.4), 0 0 0 1px var(--netz-border-subtle);
}
```
- The `0 0 0 1px border` fallback ensures elevation is always visible even when shadows fail.

---

### T1.3 — Fix form field visibility in dark mode

**Finding:** F12
**File:** `packages/ui/src/lib/styles/index.css` (`.netz-ui-field`, ~line 247)
**Problem:** Fields use `--netz-surface-raised` which is near-identical to card background `--netz-surface-elevated`.

**Changes:**
Add dark-mode override for `.netz-ui-field`:
```css
[data-theme="dark"] .netz-ui-field {
    border-color: var(--netz-border);           /* #345270 (stronger) */
    background: var(--netz-surface-inset);      /* #0b121c (darker than card) */
}
```

Fields will appear as recessed inputs (darker than card) with visible borders — standard dark mode pattern.

---

### T1.4 — Apply `--netz-page-background` gradient to layout

**Finding:** F1.3
**File:** `packages/ui/src/lib/layouts/AppLayout.svelte` (~line 152)
**Problem:** `.netz-app-layout__main` uses `var(--netz-surface)` flat — the defined gradient `--netz-page-background` is never applied.

**Changes:**
```css
/* Before */
.netz-app-layout__main { background: var(--netz-surface, #f9fafb); }

/* After */
.netz-app-layout__main { background: var(--netz-page-background, var(--netz-surface, #f9fafb)); }
```

Light mode gains subtle brand-tinted top wash. Dark mode gains subtle brand-primary tint at top.

---

### T1.5 — Respect `prefers-color-scheme` in ThemeToggle

**Finding:** F1.2
**File:** `packages/ui/src/lib/components/ThemeToggle.svelte` (~line 13)
**Problem:** `getInitialTheme()` returns `"dark"` as hardcoded default.

**Note:** `app.html` in both wealth and credit already checks `prefers-color-scheme` on first load. But ThemeToggle's `getInitialTheme()` can override this on hydration. Align them:

**Changes:**
```typescript
// Before
return "dark";

// After
return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
```

Users whose OS is set to light mode will see light mode by default. localStorage override still takes precedence for returning users.

---

## Phase 2 — Select Component Rebuild

**Goal:** Replace native `<select>` with custom dropdown. Fix chevron, enable search/multi-select.

### T2.1 — Rebuild Select.svelte as custom trigger + dropdown

**Finding:** F4, Critique §6
**File:** `packages/ui/src/lib/components/Select.svelte` (50 lines → ~150 lines)
**Problem:** Native `<select>` with `appearance-none` has no chevron, can't support search, custom rendering, or multi-select.

**Implementation:**
- Custom component with trigger button + positioned dropdown panel
- Trigger shows selected value + chevron SVG icon
- Dropdown: positioned below trigger, `max-height: 240px`, `overflow-y: auto`
- Keyboard: arrow keys navigate, Enter selects, Escape closes, type-ahead search
- Props: keep existing API (`value`, `options`, `onValueChange`, `placeholder`, `disabled`) + add optional `searchable` boolean
- Svelte 5 runes (`$state`, `$derived`, `$effect`)
- Use Svelte `transition:fly` for open/close animation
- Click-outside to close (use `pointerdown` handler on document)
- Maintain `.netz-ui-field` styling on the trigger for consistency

**No bits-ui dependency** — the project doesn't use bits-ui, keep it that way. Build from primitives.

---

### T2.2 — Migrate raw `<select>` elements to Select component

**Finding:** F4, Critique §6
**Files (13 files with raw `<select>`):**
- `frontends/admin/src/routes/(admin)/health/+page.svelte`
- `frontends/admin/src/routes/(admin)/inspect/+page.svelte`
- `frontends/credit/src/lib/components/CashflowLedger.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/pipeline/[dealId]/+page.svelte`
- `frontends/credit/src/routes/(team)/funds/[fundId]/portfolio/+page.svelte`
- `frontends/wealth/src/lib/components/DriftHistoryPanel.svelte`
- `frontends/wealth/src/routes/(team)/backtest/+page.svelte`
- `frontends/wealth/src/routes/(team)/content/+page.svelte`
- `frontends/wealth/src/routes/(team)/dd-reports/+page.svelte`

**Changes per file:** Replace inline `<select class="rounded-md border ...">` with `<Select options={...} bind:value={...} />` import from `@netz/ui`.

---

## Phase 3 — Navigation Consolidation (Wealth)

**Goal:** Reduce Wealth nav from 12 → 7 items. Merge related pages into tabs.

### T3.1 — Merge Exposure + Allocation into Analytics tabs

**Finding:** F2
**Files:**
- `frontends/wealth/src/routes/(team)/analytics/+page.svelte` — add tab system
- `frontends/wealth/src/routes/(team)/exposure/+page.svelte` — extract content into component
- `frontends/wealth/src/routes/(team)/allocation/+page.svelte` — extract content into component

**Implementation:**
- Analytics page gets `PageTabs` with 3 tabs: **Overview** (current analytics), **Exposure** (current `/exposure` content), **Allocation** (current `/allocation` content)
- Extract page content from exposure and allocation into importable components: `ExposureView.svelte`, `AllocationView.svelte` in `frontends/wealth/src/lib/components/`
- Keep `/exposure` and `/allocation` routes as redirects to `/analytics?tab=exposure` and `/analytics?tab=allocation` for bookmark compatibility
- Tab state synced to URL search params (`?tab=exposure`)

**Nav reduction:** 12 → 10 (removed Exposure, Allocation as standalone items).

---

### T3.2 — Merge Funds + Instruments + Universe into Screener tabs

**Finding:** F3
**Files:**
- `frontends/wealth/src/routes/(team)/screener/+page.svelte` — becomes tabbed Screener
- `frontends/wealth/src/routes/(team)/funds/+page.svelte` — extract into `FundsView.svelte`
- `frontends/wealth/src/routes/(team)/instruments/+page.svelte` — extract into `InstrumentsView.svelte`
- `frontends/wealth/src/routes/(team)/universe/+page.svelte` — extract into `UniverseView.svelte`

**Implementation:**
- Screener page gets `PageTabs` with 5 tabs:
  1. **Screening** (current `/screener` — 3-layer funnel)
  2. **Funds** (current `/funds` — DD pipeline status)
  3. **Managers** (link to `/manager-screener` or embed — already fully implemented at 40KB)
  4. **Instruments** (current `/instruments` — CRUD + import)
  5. **Universe** (current `/universe` — approval workflow)
- ESMA tab added later when backend route exists (F9)
- Keep `/funds`, `/instruments`, `/universe` routes as redirects to `/screener?tab=funds` etc.
- Manager-screener stays as its own route (40KB page, too large to embed) but gets a tab link

**Nav reduction:** 10 → 7 (removed Funds, Instruments, Universe as standalone items).

---

### T3.3 — Update Wealth layout nav items

**Finding:** F2
**File:** `frontends/wealth/src/routes/+layout.svelte` (nav items array, ~line 5-20)

**Final nav (7 items):**
```typescript
const navItems = [
    { label: "Dashboard",  href: "/dashboard" },
    { label: "Screener",   href: "/screener" },
    { label: "Portfolios",  href: "/model-portfolios" },
    { label: "Risk",        href: "/risk" },
    { label: "Analytics",   href: "/analytics" },
    { label: "Documents",   href: "/documents" },
    { label: "Macro",       href: "/macro" },
];
```

---

### T3.4 — Add redirect routes for backward compatibility

**Files (new `+page.server.ts` in each):**
- `frontends/wealth/src/routes/(team)/funds/+page.server.ts` → redirect to `/screener?tab=funds`
- `frontends/wealth/src/routes/(team)/instruments/+page.server.ts` → redirect to `/screener?tab=instruments`
- `frontends/wealth/src/routes/(team)/universe/+page.server.ts` → redirect to `/screener?tab=universe`
- `frontends/wealth/src/routes/(team)/exposure/+page.server.ts` → redirect to `/analytics?tab=exposure`
- `frontends/wealth/src/routes/(team)/allocation/+page.server.ts` → redirect to `/analytics?tab=allocation`

Each redirect uses SvelteKit's `redirect(301, ...)` in the `load` function.

**Note:** Keep the original `+page.svelte` files during a transition period (1 sprint) in case of deep links from backend SSE notifications or external bookmarks. Remove them after confirming no inbound traffic hits the old routes.

---

## Phase 4 — Spacing Standardization

**Goal:** Replace all hardcoded `space-y-6 p-6` with token-based spacing.

### T4.1 — Migrate admin pages to token spacing

**Finding:** F6
**Files (11 admin pages):**
- `frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte`
- `frontends/admin/src/routes/(admin)/health/+page.svelte`
- `frontends/admin/src/routes/(admin)/inspect/+page.svelte`
- `frontends/admin/src/routes/(admin)/prompts/[vertical=vertical]/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/branding/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/config/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/health/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/prompts/+page.svelte`
- `frontends/admin/src/routes/(admin)/tenants/[orgId=orgId]/setup/+page.svelte`

**Change per file:**
```
space-y-6 → space-y-(--netz-space-section-gap)
p-6       → p-(--netz-space-page-gutter)
```

---

### T4.2 — Migrate wealth investor pages to token spacing

**Finding:** F6
**Files (4 investor pages):**
- `frontends/wealth/src/routes/(investor)/fact-sheets/+page.svelte`
- `frontends/wealth/src/routes/(investor)/inv-dd-reports/+page.svelte`
- `frontends/wealth/src/routes/(investor)/inv-documents/+page.svelte`
- `frontends/wealth/src/routes/(investor)/reports/+page.svelte`

**Change per file:**
```
space-y-6 p-6 md:p-10 → space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)
```

---

## Phase 5 — Empty States & Content Coherence

**Goal:** Domain-specific, action-oriented empty states with progressive disclosure.

### T5.1 — Add skeleton pulse to loading states

**Finding:** F10, Critique §8
**File:** `packages/ui/src/lib/components/EmptyState.svelte` (73 lines)

**Changes:**
- Add optional `loading` prop (boolean)
- When `loading=true`, render skeleton pulse animation (existing `Skeleton` component) instead of the empty icon + message
- Differentiate: `loading` → skeleton, `!loading && noData` → empty state with CTA

---

### T5.2 — Improve Wealth dashboard empty states

**Finding:** F10, Critique §8
**File:** `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`

**Changes:**
Replace generic messages with domain-specific CTAs:
- "Awaiting data..." → `title="No portfolios configured" message="Create your first model portfolio to see performance metrics." actionLabel="Create Portfolio" onAction={() => goto('/model-portfolios')}`
- Drift alerts empty: "No active drift alerts" → `message="Monitoring {portfolioCount} portfolios for style drift. Add portfolios to enable drift detection."`

---

### T5.3 — Improve Documents empty state

**Finding:** F10
**File:** `frontends/wealth/src/routes/(team)/documents/+page.svelte`

**Changes:**
- "Upload documents to start the ingestion pipeline" → `title="No documents yet" message="Upload a fund prospectus, DDQ, or financial statement to start analysis." actionLabel="Upload Document"`

---

## Phase 6 — Dashboard Focal Point & Rhythm

**Goal:** Break monotonous card grid. Make portfolio health dominate.

### T6.1 — Redesign dashboard layout hierarchy

**Finding:** Critique §10
**File:** `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`

**Changes:**
- **RegimeBanner** stays at top (contextual alert — correct placement)
- **Portfolio health cards:** promote to larger, full-width hero section. Use 2-column layout with featured portfolio (largest AUM) at 60% width and secondary portfolios stacked at 40%
- **NAV chart:** move to dedicated `SectionCard` below hero, full-width
- **Drift alerts + Quick actions:** below chart, side-by-side — these are secondary
- **Macro indicators:** bottom section, dense chip layout — reference data

This creates rhythm: alert (narrow) → hero (dense, large) → chart (open, breathing) → secondary (medium density) → reference (dense, compact).

---

### T6.2 — Vary section density with padding tokens

**Finding:** Critique §10
**File:** `frontends/wealth/src/routes/(team)/dashboard/+page.svelte`

**Changes:**
- Hero section: `p-(--netz-space-card-padding-lg)` (larger internal padding)
- Chart section: `p-(--netz-space-card-padding)` (standard)
- Drift/actions: `p-(--netz-space-card-padding-sm)` (denser, secondary info)
- Macro chips: minimal padding, high density

If `--netz-space-card-padding-lg` and `-sm` don't exist, add them to `tokens.css`:
```css
--netz-space-card-padding-sm: clamp(12px, 0.5rem + 0.5vw, 16px);
--netz-space-card-padding-lg: clamp(24px, 1rem + 1vw, 40px);
```

---

## Phase 7 — Navigation Grounding (Wealth sidebar)

**Goal:** Add hierarchical context to Wealth pages via breadcrumb/sidebar when drilling into entities.

### T7.1 — Add ContextSidebar to fund detail views

**Finding:** F11, Critique §7
**Files:**
- `frontends/wealth/src/routes/(team)/dd-reports/+page.svelte` — when viewing a specific fund's DD report
- Any future fund detail route (`/screener/[fundId]/...`)

**Implementation:**
- Reuse existing `ContextSidebar` component from `@netz/ui` (already used in Credit)
- When navigating into a fund's detail view, show sidebar with:
  - Fund name + status badge
  - Nav links: Overview, DD Report, Fact Sheet, Risk Metrics, Holdings, Peer Comparison
- Sidebar activates via `initContextNav()` (same pattern as Credit)

**Note:** This is a larger structural change that depends on Screener consolidation (Phase 3). The fund detail pattern should be `/screener/[fundId]/overview`, `/screener/[fundId]/dd-report`, etc.

---

### T7.2 — Add breadcrumbs to Wealth pages

**Finding:** Critique §7
**File:** `packages/ui/src/lib/layouts/PageHeader.svelte`

**Changes:**
- Add optional `breadcrumbs` prop to `PageHeader`: `Array<{label: string, href?: string}>`
- Render as: `Screener / Funds / Fund Name` with links on ancestors
- Each page passes its breadcrumb chain based on current route

---

## Phase 8 — Product Identity (design language)

**Goal:** Move from "well-built template" toward "investment analysis platform" identity.

### T8.1 — Add domain-semantic token aliases

**Finding:** Critique §1
**File:** `packages/ui/src/lib/styles/tokens.css`

**Changes:** Add semantic aliases that reference existing tokens (zero visual change, pure naming):
```css
:root {
    /* Domain-semantic aliases (mapped to existing infrastructure tokens) */
    --desk-surface:      var(--netz-surface);
    --desk-elevated:     var(--netz-surface-elevated);
    --ink-primary:       var(--netz-text-primary);
    --ink-secondary:     var(--netz-text-secondary);
    --ticker-mono:       var(--netz-font-mono);
    --regime-ok:         var(--netz-semantic-success);
    --regime-caution:    var(--netz-semantic-warning);
    --regime-stress:     var(--netz-semantic-danger);
}
```

This is a naming-only change. Components can gradually adopt domain names. No immediate migration needed.

---

### T8.2 — Deepen shallow components or convert to CSS classes

**Finding:** Critique §9.1
**Files:**
- `packages/ui/src/lib/components/Card.svelte` (22 lines)
- `packages/ui/src/lib/components/Input.svelte`
- `packages/ui/src/lib/components/Textarea.svelte`
- `packages/ui/src/lib/components/Badge.svelte`

**Decision (per component):**
- **Card:** Keep as component but add optional `elevation` prop (`1|2|3`) mapping to shadow levels + optional `accent` prop (left border color like MetricCard). Makes it deeper without breaking existing usage.
- **Input:** Add optional `mask` prop (currency, percentage, integer) for common financial input patterns. Add `error` prop for inline validation display.
- **Textarea:** Add optional `autoResize` prop (auto-grow to content). Add `maxLength` with character counter.
- **Badge:** Keep as-is — it already handles variant mapping. Shallow but appropriate for a badge.

---

### T8.3 — MetricCard: generalize status to arbitrary accent

**Finding:** Critique §9.2
**File:** `packages/ui/src/lib/components/MetricCard.svelte` (139 lines)

**Changes:**
- Keep `status` prop (backward compat) but add `accentColor` prop as override
- `accentColor` accepts any CSS color value — lets callers use regime colors, custom domain colors
- If both provided, `accentColor` wins

---

## Phase 9 — Theme Toggle & Mobile

**Goal:** Fix toggle visibility, improve mobile nav.

### T9.1 — Fix theme toggle truncation

**Finding:** F7
**File:** `packages/ui/src/lib/layouts/TopNav.svelte` (~line 203)

**Changes:**
- Add `min-width: 0` to `.netz-topnav__items` so nav items can compress
- After Phase 3 reduces nav to 7 items, truncation should not occur on ≥1280px screens
- As fallback, add `flex-shrink: 1` to individual nav items with `text-overflow: ellipsis`

---

### T9.2 — Mobile nav drawer improvements

**Finding:** Critique §7
**File:** `packages/ui/src/lib/layouts/TopNav.svelte`

**Changes:**
- Group nav items in mobile drawer by category (matching Phase 3 consolidation):
  - **Core:** Dashboard, Screener, Portfolios
  - **Analysis:** Risk, Analytics, Macro
  - **Data:** Documents
- Add visual separators between groups
- Show current page with active indicator in drawer

---

## Dependency Graph

```
Phase 1 (tokens)     ─── no deps, start immediately
Phase 2 (select)     ─── no deps, can parallel with Phase 1
Phase 3 (nav)        ─── depends on Phase 1 (tokens must be fixed for visual testing)
Phase 4 (spacing)    ─── no deps, can parallel
Phase 5 (empty)      ─── no deps, can parallel
Phase 6 (dashboard)  ─── depends on Phase 1 (token changes affect layout)
Phase 7 (sidebar)    ─── depends on Phase 3 (routes must be consolidated first)
Phase 8 (identity)   ─── depends on Phase 1 (token layer must be stable)
Phase 9 (toggle)     ─── depends on Phase 3 (nav reduction fixes most overflow)
```

**Suggested execution order (parallelizable groups):**

| Sprint | Phases | Effort |
|--------|--------|--------|
| **S1** | Phase 1 (tokens) + Phase 2 (select) + Phase 4 (spacing) | Foundation |
| **S2** | Phase 3 (nav consolidation) + Phase 5 (empty states) | Structure |
| **S3** | Phase 6 (dashboard) + Phase 7 (sidebar) + Phase 9 (toggle) | Hierarchy |
| **S4** | Phase 8 (identity) | Polish |

---

## Task Summary

| ID | Task | Phase | Files | Severity |
|----|------|-------|-------|----------|
| T1.1 | Dark mode surface luminance spread | 1 | `tokens.css` | Critical |
| T1.2 | Dark mode shadow → border promotion | 1 | `tokens.css` | Critical |
| T1.3 | Form field visibility dark mode | 1 | `index.css` | Critical |
| T1.4 | Apply page background gradient | 1 | `AppLayout.svelte` | High |
| T1.5 | Respect prefers-color-scheme | 1 | `ThemeToggle.svelte` | High |
| T2.1 | Rebuild Select as custom component | 2 | `Select.svelte` | Critical |
| T2.2 | Migrate 13 raw `<select>` elements | 2 | 13 files (see list) | High |
| T3.1 | Merge Exposure+Allocation → Analytics tabs | 3 | 3 pages + 2 new components | High |
| T3.2 | Merge Funds+Instruments+Universe → Screener tabs | 3 | 4 pages + 3 new components | Critical |
| T3.3 | Update Wealth layout nav items (12 → 7) | 3 | `+layout.svelte` | High |
| T3.4 | Add redirect routes for backward compat | 3 | 5 new `+page.server.ts` | Medium |
| T4.1 | Admin pages token spacing | 4 | 11 admin pages | Medium |
| T4.2 | Investor pages token spacing | 4 | 4 investor pages | Medium |
| T5.1 | Skeleton pulse for loading states | 5 | `EmptyState.svelte` | Medium |
| T5.2 | Dashboard empty states domain CTAs | 5 | `dashboard/+page.svelte` | Medium |
| T5.3 | Documents empty state CTA | 5 | `documents/+page.svelte` | Low |
| T6.1 | Dashboard layout hierarchy redesign | 6 | `dashboard/+page.svelte` | High |
| T6.2 | Section density variation tokens | 6 | `tokens.css` + dashboard | Medium |
| T7.1 | ContextSidebar for fund detail views | 7 | Wealth fund detail routes | High |
| T7.2 | Breadcrumbs in PageHeader | 7 | `PageHeader.svelte` + pages | Medium |
| T8.1 | Domain-semantic token aliases | 8 | `tokens.css` | Low |
| T8.2 | Deepen shallow components | 8 | Card, Input, Textarea | Low |
| T8.3 | MetricCard generalize accent | 8 | `MetricCard.svelte` | Low |
| T9.1 | Theme toggle truncation fix | 9 | `TopNav.svelte` | Medium |
| T9.2 | Mobile nav drawer grouping | 9 | `TopNav.svelte` | Low |

---

## Out of Scope

- **Typography change** (Inter → alternative): Critique §2 noted Inter is generic but functional. Changing fonts is high-risk for layout regression with low UX payoff. Defer.
- **PortfolioCard relocation** (from @netz/ui to wealth frontend): Low priority, no user impact. Defer.
- **VirtualList wrapper component**: Manager-screener already uses `@tanstack/svelte-virtual` directly. Wrapping it adds abstraction without value until a third consumer exists.
- **Combobox component**: T2.1 adds `searchable` to Select which covers the primary use case. Full Combobox (async loading, multi-select, grouped options) deferred until Manager Screener needs it.
- **ESMA Universe tab**: Backend route doesn't exist yet. Add tab to Screener when `GET /esma/funds` is implemented.
- **Regime-aware color shifts** (Critique §4): Interesting product signature idea but requires backend→frontend regime state propagation. Design spike needed before implementation. Defer to post-remediation.
