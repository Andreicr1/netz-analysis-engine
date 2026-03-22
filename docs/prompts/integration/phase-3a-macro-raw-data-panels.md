# Phase 3A — Macro Intelligence Raw Hypertable Data Panels

**Status:** Ready
**Estimated scope:** ~500 lines (4 endpoints + 4 frontend panels)
**Risk:** Medium (new endpoints + chart components)
**Prerequisite:** None (hypertable data already populated by workers)

---

## Context

The macro page (`/macro`) shows composite scores but not the underlying raw data from BIS, IMF, Treasury, and OFR hypertables. Analysts need to see the source indicators that feed the composite scores.

**Data already in DB via workers:**
- `bis_statistics` (1yr chunks, segmentby: `country_code`) — lock 900_014, quarterly
- `imf_weo_forecasts` (1yr chunks, segmentby: `country_code`) — lock 900_015, quarterly
- `treasury_data` (1mo chunks, segmentby: `series_id`) — lock 900_011, daily
- `ofr_hedge_fund_data` (3mo chunks, segmentby: `series_id`) — lock 900_012, weekly

**Chart library:** ECharts via `@netz/ui`. Components in `packages/ui/src/lib/charts/` — use `TimeSeriesChart`, `BarChart`, `GaugeChart`, `ChartContainer`.

---

## Task 1: Four New Backend Endpoints

### Step 1.1 — Schemas

Add to `backend/app/domains/wealth/schemas/macro.py`:

```python
class BisDataResponse(BaseModel):
    country_code: str
    indicator: str
    values: list[BisTimePoint]
    source: str = "BIS SDMX"

class BisTimePoint(BaseModel):
    period: date
    value: float

class ImfDataResponse(BaseModel):
    country_code: str
    indicator: str
    values: list[ImfYearPoint]
    source: str = "IMF WEO"
    provenance: str = "model_inference"  # NOT deterministic — IMF are forecasts

class ImfYearPoint(BaseModel):
    year: int
    value: float

class TreasuryDataResponse(BaseModel):
    series_id: str
    values: list[TreasuryTimePoint]
    source: str = "US Treasury"

class TreasuryTimePoint(BaseModel):
    obs_date: date
    value: float

class OfrDataResponse(BaseModel):
    series_id: str
    values: list[OfrTimePoint]
    source: str = "OFR"

class OfrTimePoint(BaseModel):
    obs_date: date
    value: float
```

### Step 1.2 — Endpoints

Add to `backend/app/domains/wealth/routes/macro.py`:

```python
@router.get("/macro/bis", response_model=list[BisDataResponse])
async def get_bis_raw_data(
    country: str | None = Query(None),
    indicator: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
    """Raw BIS time series (credit gap, DSR, property prices)."""

@router.get("/macro/imf", response_model=list[ImfDataResponse])
async def get_imf_raw_data(
    country: str | None = Query(None),
    indicator: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
    """Raw IMF WEO forecasts (GDP growth, inflation, fiscal, debt)."""

@router.get("/macro/treasury", response_model=list[TreasuryDataResponse])
async def get_treasury_raw_data(
    series: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
    """Raw Treasury data (yield curve, rates, auctions)."""

@router.get("/macro/ofr", response_model=list[OfrDataResponse])
async def get_ofr_raw_data(
    metric: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
    """Raw OFR hedge fund data (leverage, AUM, stress)."""
```

**All global tables — no RLS, no organization_id filter.**

### Step 1.3 — Query patterns

**TimescaleDB query rules:**
- `bis_statistics`: filter on `period`, no `time_bucket()` (quarterly data)
- `imf_weo_forecasts`: filter on `period`, no `time_bucket()` (annual data)
- `treasury_data`: filter on `obs_date`, `segmentby: series_id`
- `ofr_hedge_fund_data`: filter on `obs_date`, `segmentby: series_id`
- **Never forward-fill gaps** — return actual observed points only
- Use date-floor filters, not `LIMIT * entity_count`

### Step 1.4 — Caching

Redis cache per endpoint:
- BIS/IMF: 6h TTL (quarterly data, slow to change)
- Treasury: 1h TTL (daily data)
- OFR: 1h TTL (weekly data)

Use existing Redis caching pattern from the codebase.

---

## Task 2: Frontend Data Source Panels

### Step 2.1 — Collapsible section

In `frontends/wealth/src/routes/(team)/macro/+page.svelte`, add a collapsible "Data Sources" section below the composite scores section:

```svelte
<SectionCard title="Data Sources" collapsible defaultOpen={false}>
  <div class="grid grid-cols-2 gap-4">
    {#await import('./BisPanel.svelte') then BisPanel}
      <BisPanel.default />
    {/await}
    {#await import('./ImfPanel.svelte') then ImfPanel}
      <ImfPanel.default />
    {/await}
    {#await import('./TreasuryPanel.svelte') then TreasuryPanel}
      <TreasuryPanel.default />
    {/await}
    {#await import('./OfrPanel.svelte') then OfrPanel}
      <OfrPanel.default />
    {/await}
  </div>
</SectionCard>
```

**Lazy load** each panel with dynamic imports — should not block page load.

### Step 2.2 — BIS Panel

Create `frontends/wealth/src/routes/(team)/macro/BisPanel.svelte`:

- Country selector dropdown (filter)
- Multi-series line chart (`TimeSeriesChart`): credit gap, DSR, property prices
- Per-country colors: `--netz-chart-1` through `--netz-chart-5`
- Provenance label: "Source: BIS SDMX — Deterministic Metric"

### Step 2.3 — IMF Panel

Create `frontends/wealth/src/routes/(team)/macro/ImfPanel.svelte`:

- Indicator `Select` dropdown (GDP growth, inflation, fiscal balance, debt-to-GDP)
- Horizontal bar chart (`BarChart` with `orientation="horizontal"`)
- One indicator at a time, countries as bars
- **CORRECTION:** Provenance label: "Source: IMF WEO — Model Inference" (NOT deterministic — these are economic forecasts)

### Step 2.4 — Treasury Panel

Create `frontends/wealth/src/routes/(team)/macro/TreasuryPanel.svelte`:

- Yield curve chart: X = maturities (1M, 3M, 6M, 1Y, 2Y, 5Y, 10Y, 30Y), Y = rate
- `markArea` for inverted regions (red at 8% opacity)
- Raw `ChartContainer` (category X axis, not time series)
- Provenance label: "Source: US Treasury — Deterministic Metric"

### Step 2.5 — OFR Panel

Create `frontends/wealth/src/routes/(team)/macro/OfrPanel.svelte`:

- Area chart for AUM trend (`TimeSeriesChart` area mode)
- Bar chart for strategy breakdown (`BarChart`)
- Gauge for repo stress indicator (`GaugeChart`)
- Provenance label: "Source: OFR — Deterministic Metric (Survey-Based)"

---

## Task 3: Tests

Create `backend/tests/routes/test_macro_raw_data_endpoints.py`:
- Test each of the 4 endpoints with and without filters
- Test empty results when no data for country/indicator
- Test auth (non-team gets 403)
- Verify global table access (no RLS assertion)

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/schemas/macro.py` | Add 8 new schemas |
| `backend/app/domains/wealth/routes/macro.py` | Add 4 new endpoints |
| `frontends/wealth/src/routes/(team)/macro/+page.svelte` | Add Data Sources section |
| `frontends/wealth/src/routes/(team)/macro/BisPanel.svelte` | New component |
| `frontends/wealth/src/routes/(team)/macro/ImfPanel.svelte` | New component |
| `frontends/wealth/src/routes/(team)/macro/TreasuryPanel.svelte` | New component |
| `frontends/wealth/src/routes/(team)/macro/OfrPanel.svelte` | New component |
| `backend/tests/routes/test_macro_raw_data_endpoints.py` | New test file |

## Acceptance Criteria

- [ ] 4 new endpoints return raw hypertable data with country/indicator filters
- [ ] Macro page has collapsible "Data Sources" section with 4 panels
- [ ] Each panel has chart + latest value badges
- [ ] Provenance labels correct: BIS=deterministic, IMF=model inference, Treasury=deterministic, OFR=deterministic
- [ ] Panels lazy-loaded (dynamic imports)
- [ ] Dark mode functional (ECharts netz-theme)
- [ ] All formatters from `@netz/ui`
- [ ] Redis caching (6h BIS/IMF, 1h Treasury/OFR)
- [ ] `make check` passes

## Gotchas

- IMF WEO forecasts are **model inference**, NOT deterministic metrics — critical provenance distinction
- No `time_bucket()` for raw data — BIS quarterly, IMF annual, return actual points
- Never forward-fill financial data gaps
- Global tables — no RLS, no `organization_id`
- ECharts dark mode via `echarts-setup.ts` MutationObserver — use CSS variables only
- Verify exact ECharts component imports from `packages/ui/src/lib/charts/` before building
