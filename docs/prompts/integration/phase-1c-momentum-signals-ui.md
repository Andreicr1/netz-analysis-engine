# Phase 1C — Surface Pre-Computed Momentum Signals in UI

**Status:** Ready
**Estimated scope:** ~200 lines changed
**Risk:** Low (read-only frontend, data already in DB)
**Prerequisite:** None (momentum signals pre-computed by `risk_calc` worker)

---

## Context

The `risk_calc` worker (lock 900_007) pre-computes momentum signals daily into `fund_risk_metrics` columns:
- `rsi_14` — RSI 14-period (Float, line ~59 of `backend/app/domains/wealth/models/risk.py`)
- `bb_position` — Bollinger Band position (Float, line ~60)
- `nav_momentum_score` — NAV momentum (Float, line ~61)
- `flow_momentum_score` — Flow momentum (Float, line ~62)
- `blended_momentum_score` — Composite (Float, line ~63)

These values are **in the DB but invisible** — no frontend page shows them.

**Chart library:** ECharts via `@netz/ui` components (NOT LayerChart). Use `GaugeChart`, `MetricCard` from `packages/ui/src/lib/charts/`.

---

## Task 1: Ensure Momentum Fields in Risk API Response

### Step 1.1 — Check existing risk schemas

Read `backend/app/domains/wealth/schemas/risk.py` and verify momentum fields are in the response model. If not, add them:

```python
# In the risk metrics response schema
rsi_14: float | None = None
bb_position: float | None = None
nav_momentum_score: float | None = None
flow_momentum_score: float | None = None
blended_momentum_score: float | None = None
```

### Step 1.2 — Check risk route returns momentum data

Read `backend/app/domains/wealth/routes/risk.py`. The CVaR batch endpoint (line ~77) should already select from `fund_risk_metrics`. Verify momentum columns are included in the SELECT and response. If the query filters them out, add them.

---

## Task 2: Momentum Signals Section on Risk Page

### Step 2.1 — Risk page layout

In `frontends/wealth/src/routes/(team)/risk/+page.svelte` (drift alerts section is at lines ~125-150), add a new "Momentum Signals" section ABOVE or BELOW drift alerts.

**Layout:** `SectionCard title="Momentum Signals"` with a 3-column grid. Each column = one profile's momentum dashboard.

### Step 2.2 — Momentum components per profile

For each profile that has risk metrics:

| Signal | Component | Config |
|--------|-----------|--------|
| RSI-14 | `GaugeChart` | Zones: 0-30 green (oversold), 30-70 neutral, 70-100 amber (overbought) |
| Bollinger position | Horizontal bar or `GaugeChart` half-arc | Range 0-1, color gradient |
| Blended momentum | `MetricCard` | Color-coded value using semantic tokens |

**Color coding (UX Doctrine §17 — deterministic metric, not model inference):**
- RSI < 30: `--status-ok` (oversold opportunity)
- RSI 30-70: `--status-warning` (neutral)
- RSI > 70: `--status-breach` (overbought caution)
- Badge label: "Deterministic Metric" (not "AI Generated")

### Step 2.3 — Data loading

Momentum data should come from the existing risk endpoint response. Do NOT add a new endpoint. Extend the server load to include momentum fields if not already present.

```typescript
// In +page.server.ts or +page.svelte
const riskData = await api.get(`/risk/${profile}/cvar`);
// riskData should include rsi_14, bb_position, blended_momentum_score
```

---

## Task 3: Momentum Mini-Panel on Fund Detail Page

### Step 3.1 — Fund detail layout

In `frontends/wealth/src/routes/(team)/funds/[fundId]/+page.svelte`, add a compact momentum row:

```svelte
<div class="grid grid-cols-5 gap-3">
  <MetricCard label="RSI-14" value={formatNumber(fund.rsi_14, 1)} status={rsiStatus(fund.rsi_14)} />
  <MetricCard label="Bollinger" value={formatNumber(fund.bb_position, 2)} />
  <MetricCard label="NAV Momentum" value={formatNumber(fund.nav_momentum_score, 2)} />
  <MetricCard label="Flow Momentum" value={formatNumber(fund.flow_momentum_score, 2)} />
  <MetricCard label="Blended" value={formatNumber(fund.blended_momentum_score, 2)} />
</div>
```

### Step 3.2 — Formatters

Use `@netz/ui` formatters exclusively:
- `formatNumber(value, decimals)` for momentum scores
- `formatPercent(value)` if scores are 0-100 range
- NEVER use `.toFixed()` or inline `Intl.NumberFormat`

### Step 3.3 — Dark mode

All charts use `netz-theme` auto-switch via `echarts-setup.ts` MutationObserver. Use CSS variables (`--netz-chart-1`, `--status-ok`, etc.) — NEVER hardcoded hex colors.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/schemas/risk.py` | Ensure momentum fields in response model |
| `backend/app/domains/wealth/routes/risk.py` | Ensure momentum columns in query (if missing) |
| `frontends/wealth/src/routes/(team)/risk/+page.svelte` | Add "Momentum Signals" section with gauges |
| `frontends/wealth/src/routes/(team)/funds/[fundId]/+page.svelte` | Add momentum mini-panel |

## Acceptance Criteria

- [ ] Risk page shows RSI-14, Bollinger position, blended momentum per profile
- [ ] Fund detail shows instrument-level momentum signals as MetricCards
- [ ] Color coding: RSI <30 (oversold/green), >70 (overbought/amber)
- [ ] Provenance badge: "Deterministic Metric" per UX Doctrine §17
- [ ] Dark mode fully functional (semantic tokens only)
- [ ] All formatters from `@netz/ui` (no `.toFixed()`)
- [ ] `make check` passes

## Gotchas

- Momentum values may be `null` for recently added instruments — show "—" or "Pending" placeholder
- GaugeChart is from `packages/ui/src/lib/charts/` — verify exact import path before using
- If MetricCard doesn't exist, check `packages/ui/src/lib/components/` for the actual component name
- Risk data may be per-profile — group momentum by profile in the Risk page, by instrument in Fund detail
