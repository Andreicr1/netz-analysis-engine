# Wealth Frontend — Design Decisions (Review Session 2026-03-17)

**Origin:** Brainstorm + review session in Claude.ai (not captured in plan files)
**Applies to:** PRs touching `frontends/wealth/`, `packages/ui/`

---

## D1: Navigation — TopNav global + ContextSidebar in detail pages only

AppLayout uses TopNav (horizontal, always visible) as global nav.
ContextSidebar appears ONLY in detail pages ([fundId], [portfolioId]).
Sidebar is NOT used as global nav in the wealth frontend.

**Violation:** AppLayout importing Sidebar as primary nav, or any page using Sidebar
for global section switching.

**Files:** `packages/ui/src/lib/layouts/AppLayout.svelte`

---

## D2: Dark + Light for ALL frontends

Both wealth and credit support dark AND light via `data-theme="dark|light"` on `<html>`.
Dark is not exclusive to wealth. Light is not exclusive to credit.
`defaultBranding` (light) must remain unchanged; wealth uses `defaultDarkBranding`.

**Violation:** Hardcoded `bg-white`, `text-black`, `bg-gray-*` without token reference.

**Files:** `packages/ui/src/lib/styles/tokens.css`, `packages/ui/src/lib/utils/branding.ts`

---

## D3: AlertFeed — Discriminated Union Required

`WealthAlert` MUST be a discriminated union, not a flat type with
`meta?: Record<string, unknown>`. Required shape:

```typescript
type WealthAlert =
  | { type: "cvar_breach"; portfolio: string; utilization: number; ts: Date }
  | { type: "behavior_change"; instrument: string; severity: "LOW"|"MEDIUM"|"HIGH"|"CRITICAL"; changed_metrics: string[]; ts: Date }
  | { type: "dtw_drift"; instrument: string; drift_score: number; ts: Date }
  | { type: "regime_change"; from: string; to: string; ts: Date }
  | { type: "universe_removal"; instrument: string; affected_portfolios: string[]; ts: Date }
```

**Violation:** `meta?: Record<string, unknown>` in WealthAlert, or flat interface
without `type` literal union discriminator.

**Files:** `packages/ui/src/lib/components/AlertFeed.svelte`

---

## D4: CSS Tokens — No Undeclared Vars

Every `var(--netz-*)` used in any .svelte or .css file MUST be declared in
`packages/ui/src/lib/styles/tokens.css` (in :root or [data-theme="dark"]).
Aliases acceptable: `--netz-primary: var(--netz-brand-primary)`.

**Known undeclared tokens in current PR (must fix before merge):**
- `var(--netz-primary)` — used in screener, not declared
- `var(--netz-primary-foreground)` — used in screener buttons
- `var(--netz-primary-muted)` — used in screener tab badges

**Violation:** Any var(--netz-X) with no declaration in tokens.css.

---

## D5: Tokens are Admin-Configurable — No Hardcoded Colors in Components

Token values are set by admin via branding API. Components reference token names only,
never hardcode hex values. Semantic tokens (--netz-success, --netz-warning, --netz-danger)
are the only allowed status colors in component CSS.

**Violation:** Hardcoded hex (#10B981, #EF4444, etc.) or Tailwind color classes
(text-green-500, bg-red-100) in component files.

---

## D6: Figma Reference Scope

Figma is authoritative for layout and information hierarchy only.
Colors, typography, and styling follow the token system and UX principles,
NOT Figma color values (those were placeholder/prototype values).

---

## D7: MetricCard — Not DataCard — for Financial KPIs in Wealth

`MetricCard.svelte` (new) is the correct component for financial KPIs with
limit/utilization context in wealth pages. `DataCard.svelte` is legacy,
kept for credit frontend backward compat only.

**Violation:** Wealth pages importing DataCard for financial metrics.

---

## D8: Backend — alert_type Literal Discriminator in Schemas

StrategyDriftRead schema must include:
`alert_type: Literal["behavior_change"] = "behavior_change"`

This enables TypeScript discriminated union parsing without frontend heuristics.

**Files:** `backend/app/domains/wealth/schemas/strategy_drift.py`

---

## D9: Correlation — Intersection of Dates, Not Forward-Fill

When loading NavTimeseries for correlation, use INTERSECTION of dates where
ALL instruments have data. Do NOT forward-fill returns — creates artificial
zero-return days that underestimate correlation.

**Files:** `backend/app/domains/wealth/routes/correlation_regime.py`,
`backend/vertical_engines/wealth/correlation/service.py`
