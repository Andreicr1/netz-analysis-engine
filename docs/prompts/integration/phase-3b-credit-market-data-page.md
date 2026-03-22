# Phase 3B — Credit Market Data Page

**Status:** Ready
**Estimated scope:** ~250 lines
**Risk:** Low (read-only, data already in `macro_data` hypertable)
**Prerequisite:** None

---

## Context

The credit vertical's `market_data` engine (`vertical_engines/credit/market_data/`) reads from the `macro_data` hypertable (BAA spread, yield curve, Case-Shiller 20 metros, regional indicators). **Zero FRED API calls at runtime.** But no credit frontend page shows this data.

**Data available (via credit's FRED_SERIES_REGISTRY, all in `macro_data`):**
- BAA-OAS spread (`BAA10Y`, `BAMLH0A0HYM2`)
- Yield curve rates (`DGS2`, `DGS10`, `DFF`, `SOFR`)
- Case-Shiller national + 20 metros (`CSUSHPINSA` + metro series)
- Housing indicators (`HOUST`, `PERMIT`, `EXHOSLUSM495S`, `MSACSR`)
- Mortgage rates (`MORTGAGE30US`, `MORTGAGE15US`)
- Banking credit quality (`DRCCLACBS`, `DRSFRMACBS`, `NETCIBAL`)
- Financial stress (`STLFSI4`)

---

## Task 1: Backend — Extend Dashboard Macro Snapshot

### Step 1.1 — Check existing endpoint

Read `backend/app/domains/credit/routes/dashboard.py`. Find the `macro-snapshot` endpoint. Determine if it already returns full market data or just a summary.

### Step 1.2 — Extend or create endpoint

**Option A (preferred):** If `GET /dashboard/macro-snapshot` returns limited data, extend its response to include:
- Credit spreads (BAA-OAS, HY spread)
- Yield curve points (DFF, SOFR, DGS2, DGS10)
- Case-Shiller national + metro time series
- Housing indicators (starts, permits, existing home sales, months supply)
- Mortgage rates (30Y, 15Y)
- Banking credit quality indicators
- Financial stress index (STLFSI4)

**Option B:** If extending is too disruptive, create `GET /credit/market-data` endpoint that returns all credit market data from `macro_data` hypertable.

### Step 1.3 — Query pattern

```python
# All from macro_data hypertable (global table, no RLS)
stmt = select(MacroData.series_id, MacroData.obs_date, MacroData.value).where(
    MacroData.series_id.in_(CREDIT_MARKET_SERIES),
    MacroData.obs_date >= func.now() - text("interval '2 years'"),
).order_by(MacroData.series_id, MacroData.obs_date)
```

Group results by `series_id` for frontend chart consumption.

---

## Task 2: Frontend — Market Data Page

### Step 2.1 — Add route

Create `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.server.ts`:

```typescript
export const load: PageServerLoad = async ({ locals, params }) => {
  const [macroResult] = await Promise.allSettled([
    locals.api.get(`/dashboard/macro-snapshot`) // or /credit/market-data
  ]);
  return {
    marketData: macroResult.status === 'fulfilled' ? macroResult.value : null,
  };
};
```

### Step 2.2 — Market data page

Create `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.svelte`:

**Layout — 4 sections:**

1. **Credit Spreads** — Line chart showing BAA-OAS and HY spread over time
2. **Yield Curve** — Current yield curve (DFF, SOFR, 2Y, 10Y) + 2Y/10Y inversion indicator
3. **Case-Shiller** — National index line + Select dropdown for 20 metros (default: top 5)
4. **Housing & Banking** — Grid of MetricCards (housing starts, permits, mortgage rates, credit quality)

**Chart components:** ECharts via `@netz/ui` — `TimeSeriesChart`, `ChartContainer`, `MetricCard`.

### Step 2.3 — Navigation

Add "Market Data" to the fund-level navigation in credit frontend. Find the nav/layout at `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte` and add entry.

### Step 2.4 — Provenance labels

All data is from `macro_data` hypertable → "Source: FRED (via DB) — Deterministic Metric".

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/credit/routes/dashboard.py` | Extend macro-snapshot or create new endpoint |
| `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.server.ts` | New server load |
| `frontends/credit/src/routes/(team)/funds/[fundId]/market-data/+page.svelte` | New page |
| `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte` | Add Market Data nav item |

## Acceptance Criteria

- [ ] BAA spread, yield curve, Case-Shiller displayed with time series
- [ ] Regional breakdown (20 Case-Shiller metros visible via selector)
- [ ] Data sourced from `macro_data` hypertable (zero FRED API calls)
- [ ] All UX Doctrine compliance (provenance labels, semantic spacing, dark mode)
- [ ] All formatters from `@netz/ui`
- [ ] `make check` passes

## Gotchas

- `macro_data` is a **global** hypertable — no RLS, no organization_id
- Credit frontend (`frontends/credit/`) must NOT import from wealth frontend
- Case-Shiller metro series may have gaps — show available data only, never forward-fill
- ECharts components from `packages/ui/src/lib/charts/` — verify imports
