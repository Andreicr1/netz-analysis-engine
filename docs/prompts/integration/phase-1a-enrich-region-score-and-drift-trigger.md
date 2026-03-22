# Phase 1A — Wire `enrich_region_score()` + Drift Scan Trigger

**Status:** Ready
**Estimated scope:** ~120 lines changed
**Risk:** Low (pure function wiring + frontend button)
**Prerequisite:** None

---

## Context

Two small items that close data gaps with minimal code:

1. **`enrich_region_score()`** is a tested pure function at `quant_engine/regional_macro_service.py:771` that adds the 7th dimension (BIS credit cycle) and blends IMF growth into regional macro scores. It is **never called** from any worker. BIS and IMF data already exist in hypertables (`bis_statistics`, `imf_weo_forecasts`).

2. **Drift scan trigger** — `POST /analytics/strategy-drift/scan` endpoint exists but the wealth Risk page has no "Scan Now" button. Users must use curl.

---

## Task 1: Wire `enrich_region_score()` into Macro Ingestion Worker

### What to do

The macro ingestion worker at `backend/app/domains/wealth/workers/macro_ingestion.py` calls `build_regional_snapshot()` (line ~163) which internally calls `score_region()` per region. After scoring, the results are inserted into `macro_regional_snapshots` (line ~170).

**Insert `enrich_region_score()` between scoring and persistence.**

### Step 1.1 — Query BIS + IMF data in worker

In `macro_ingestion.py`, before the `build_regional_snapshot()` call, query the hypertables:

```python
# Query BIS data (global table, no RLS)
bis_rows = await db.execute(
    select(BisStatistic.country_code, BisStatistic.indicator, BisStatistic.value, BisStatistic.period)
    .where(BisStatistic.period >= func.now() - text("interval '180 days'"))
)
bis_data = [BisDataPoint(r.country_code, r.indicator, r.value, r.period) for r in bis_rows.all()]

# Query IMF data (global table, no RLS)
imf_rows = await db.execute(
    select(ImfWeoForecast.country_code, ImfWeoForecast.indicator, ImfWeoForecast.value, ImfWeoForecast.year)
    .where(ImfWeoForecast.year >= func.extract('year', func.now()) - 1)
)
imf_data = [ImfDataPoint(r.country_code, r.indicator, r.year, r.value) for r in imf_rows.all()]
```

**Models to import:** `BisStatistic` and `ImfWeoForecast` from `backend/app/shared/models.py` (global tables, no organization_id).

**Datapoint types to import:** `BisDataPoint` (line 597) and `ImfDataPoint` (line 607) from `quant_engine/regional_macro_service.py`.

### Step 1.2 — Pass BIS/IMF to `build_regional_snapshot()`

Modify `build_regional_snapshot()` in `backend/quant_engine/macro_snapshot_builder.py` (or wherever it's defined) to accept optional `bis_data` and `imf_data` params. Inside, after `score_region()` returns a `RegionalMacroResult`, call:

```python
from quant_engine.regional_macro_service import enrich_region_score

result = enrich_region_score(result, bis_data=bis_data, imf_data=imf_data)
```

**Error handling:** `enrich_region_score()` returns the original result unchanged if `bis_data`/`imf_data` is None/empty (lines 818-819 of `regional_macro_service.py`). Wrap the BIS/IMF DB queries in try/except, log warning, pass `None` on failure. The worker MUST NOT fail because of missing BIS/IMF data.

### Step 1.3 — Verify staleness constants

Use the existing decay constants from `regional_macro_service.py` for quarterly data freshness (100 days fresh / 180 days max). Do NOT introduce new hardcoded magic numbers.

### Step 1.4 — Test

Create `backend/tests/workers/test_macro_ingestion_enrichment.py`:
- Test that `enrich_region_score` is called when BIS+IMF data is available
- Test graceful degradation: BIS query fails → worker continues with unenriched scores
- Test graceful degradation: IMF data empty → original scores preserved
- Test that `GET /macro/scores` returns 7 dimensions (credit_cycle present) after enrichment

---

## Task 2: Add "Scan Now" Button for Drift Scanner

### What to do

The wealth Risk page at `frontends/wealth/src/routes/(team)/risk/+page.svelte` already shows drift alerts (lines ~125-150, reads `GET /analytics/strategy-drift/alerts?is_current=true`). Add a "Scan Now" button that triggers `POST /analytics/strategy-drift/scan`.

### Step 2.1 — Add button to Risk page

In the drift alerts section of `+page.svelte`:

```svelte
<Button
  variant="outline"
  size="sm"
  disabled={$state.scanning}
  onclick={triggerDriftScan}
>
  {$state.scanning ? 'Scanning...' : 'Scan Now'}
</Button>
```

### Step 2.2 — Implement scan trigger

```typescript
let scanning = $state(false);

async function triggerDriftScan() {
  scanning = true;
  try {
    const res = await api.post('/analytics/strategy-drift/scan');
    // If returns job_id, could subscribe SSE — for now just invalidate after delay
    await new Promise(r => setTimeout(r, 3000));
    invalidateAll();
  } catch (e) {
    // Show error banner
  } finally {
    scanning = false;
  }
}
```

**Pattern:** Use `api.post()` from existing client (never raw `fetch()`). After scan completes, `invalidateAll()` refreshes the drift alerts list.

### Step 2.3 — Loading state

While scanning, show a subtle loading indicator (spinner or pulsing badge). Per UX Doctrine §15: "motion clarifies state progression".

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/workers/macro_ingestion.py` | Query BIS/IMF, pass to builder |
| `backend/quant_engine/macro_snapshot_builder.py` | Accept optional bis_data/imf_data, call enrich_region_score |
| `frontends/wealth/src/routes/(team)/risk/+page.svelte` | Add "Scan Now" button + handler |
| `backend/tests/workers/test_macro_ingestion_enrichment.py` | New test file |

## Acceptance Criteria

- [ ] `GET /macro/scores` returns 7 dimensions (credit_cycle present)
- [ ] `GET /macro/snapshot` shows IMF-blended growth (FRED 70% + IMF 30%)
- [ ] Worker continues normally when BIS/IMF data is unavailable
- [ ] "Scan Now" button triggers POST, shows loading, refreshes alerts
- [ ] `make check` passes

## Gotchas

- `enrich_region_score` is a **sync** pure function — call it via `asyncio.to_thread()` if inside async context, or inline if already in `to_thread` block
- BIS/IMF tables are **global** (no `organization_id`, no RLS) — no tenant filter needed
- Do NOT use `hash()` for lock IDs — use deterministic integers only
- Staleness: use existing 100d/180d constants, not new magic numbers
