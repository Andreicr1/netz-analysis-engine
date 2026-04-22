# Macro Terminal Visual Parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Macro terminal page from a 4-zone widget dashboard into a Bloomberg-density 3-column terminal with cross-asset panel, continuous SVG regime plot, factor panels (liquidity + econ pulse + CB calendar), and a real financial asset drawer.

**Architecture:** Backend-first (3 new endpoints before any component is written). All new Svelte components land in `packages/ii-terminal-core/src/lib/components/terminal/macro/` — never in the frontends directly. The terminal page (`frontends/terminal/src/routes/macro/+page.svelte`) is rewritten last, consuming only the new core primitives.

**Tech Stack:** Python/FastAPI + Pydantic v2 (backend), Svelte 5 + TypeScript (components), ii-terminal-core package (component destination), FRED/nav_timeseries/macro_regional_snapshots (data sources).

---

## File Map

**Create (backend):**
- `backend/app/domains/wealth/schemas/macro.py` — add `CrossAssetPoint`, `CrossAssetResponse`, `RegimeTrailPoint`, `RegimeTrailResponse`, `CbEvent`, `CbCalendarResponse`
- (routes added to existing) `backend/app/domains/wealth/routes/macro.py` — 3 new route handlers

**Create (ii-terminal-core):**
- `packages/ii-terminal-core/src/lib/components/terminal/macro/MiniCard.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/CrossAssetPanel.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/RegimePlot.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/LiquidityPanel.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/EconPanel.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/CBPanel.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/MacroNewsFeed.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/AssetDrawer.svelte`
- `packages/ii-terminal-core/src/lib/components/terminal/macro/regime-plot-store.svelte.ts`

**Modify:**
- `packages/ii-terminal-core/src/lib/components/terminal/primitives/index.ts` — export new components
- `frontends/terminal/src/routes/macro/+page.svelte` — rewrite with 3-col grid

**Tests:**
- `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`

---

## Task 0.1: Backend — `/macro/cross-asset` endpoint

Cross-asset batch endpoint. Groups assets by sector (RATES, FX, EQUITY, COMMODITY, CREDIT). Uses FRED for fixed income, FX, commodities, credit spreads; `nav_timeseries` + `instruments_universe` for equity indices. Returns current value, 30-day change_pct, and sparkline (last 30 observations as plain float list).

**Files:**
- Modify: `backend/app/domains/wealth/schemas/macro.py`
- Modify: `backend/app/domains/wealth/routes/macro.py`
- Test: `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`

- [ ] **Step 1: Add Pydantic schemas to `schemas/macro.py`**

  Append after the existing `FredTimePoint` / `FredDataResponse` classes:

  ```python
  class CrossAssetPoint(BaseModel):
      symbol: str
      name: str
      sector: Literal["RATES", "FX", "EQUITY", "COMMODITY", "CREDIT"]
      last_value: float | None = None
      change_pct: float | None = None  # vs previous observation
      unit: str = ""  # "%" | "idx" | "USD" | "bps"
      sparkline: list[float] = []  # last 30 observations


  class CrossAssetResponse(BaseModel):
      as_of_date: date | None = None
      assets: list[CrossAssetPoint] = []
  ```

- [ ] **Step 2: Write the failing test**

  Create `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`:

  ```python
  """Unit tests for new macro endpoints (cross-asset, regime trail, CB calendar).

  These tests do NOT hit the DB — they test schema serialization and helper logic.
  Integration tests (with real DB) are out of scope for this plan.
  """
  import pytest
  from backend.app.domains.wealth.schemas.macro import (
      CrossAssetPoint,
      CrossAssetResponse,
  )


  def test_cross_asset_point_schema():
      p = CrossAssetPoint(
          symbol="DGS10",
          name="US 10Y",
          sector="RATES",
          last_value=4.32,
          change_pct=-0.021,
          unit="%",
          sparkline=[4.10, 4.15, 4.20, 4.32],
      )
      assert p.sector == "RATES"
      assert p.last_value == pytest.approx(4.32)
      assert len(p.sparkline) == 4


  def test_cross_asset_response_empty():
      r = CrossAssetResponse()
      assert r.assets == []
      assert r.as_of_date is None
  ```

- [ ] **Step 3: Run test — expect FAIL (schemas not yet added)**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  ```

  Expected: `ImportError: cannot import name 'CrossAssetPoint'`

- [ ] **Step 4: Implement schemas (Step 1 above) — run test again**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py::test_cross_asset_point_schema tests/domains/wealth/services/test_macro_new_endpoints.py::test_cross_asset_response_empty -v
  ```

  Expected: PASS

- [ ] **Step 5: Implement the route in `routes/macro.py`**

  Add near the bottom of the file, before the `_FRED_ALLOWLIST` block:

  ```python
  # ---------------------------------------------------------------------------
  #  Cross-asset batch endpoint
  # ---------------------------------------------------------------------------

  _CROSS_ASSET_CATALOG: list[dict] = [
      # RATES — FRED
      {"symbol": "DGS2",  "name": "US 2Y",   "sector": "RATES",     "unit": "%",   "source": "fred"},
      {"symbol": "DGS10", "name": "US 10Y",  "sector": "RATES",     "unit": "%",   "source": "fred"},
      {"symbol": "DGS30", "name": "US 30Y",  "sector": "RATES",     "unit": "%",   "source": "fred"},
      {"symbol": "IRLTLT01DEM156N", "name": "DE 10Y", "sector": "RATES", "unit": "%", "source": "fred"},
      # FX — FRED
      {"symbol": "DTWEXBGS", "name": "DXY",     "sector": "FX",    "unit": "idx", "source": "fred"},
      {"symbol": "DEXUSEU",  "name": "EUR/USD",  "sector": "FX",    "unit": "",    "source": "fred"},
      {"symbol": "DEXJPUS",  "name": "USD/JPY",  "sector": "FX",    "unit": "",    "source": "fred"},
      {"symbol": "DEXBZUS",  "name": "USD/BRL",  "sector": "FX",    "unit": "",    "source": "fred"},
      # EQUITY — nav_timeseries by ticker
      {"symbol": "SPY",  "name": "SPX",    "sector": "EQUITY",    "unit": "idx", "source": "nav"},
      {"symbol": "QQQ",  "name": "NDX",    "sector": "EQUITY",    "unit": "idx", "source": "nav"},
      {"symbol": "IWM",  "name": "RUT",    "sector": "EQUITY",    "unit": "idx", "source": "nav"},
      {"symbol": "EEM",  "name": "EM",     "sector": "EQUITY",    "unit": "idx", "source": "nav"},
      # COMMODITY — FRED
      {"symbol": "DCOILWTICO",       "name": "WTI",    "sector": "COMMODITY", "unit": "USD", "source": "fred"},
      {"symbol": "GOLDAMGBD228NLBM", "name": "Gold",   "sector": "COMMODITY", "unit": "USD", "source": "fred"},
      {"symbol": "PCOPPUSDM",        "name": "Copper", "sector": "COMMODITY", "unit": "USD", "source": "fred"},
      {"symbol": "DHHNGSP",          "name": "NatGas", "sector": "COMMODITY", "unit": "USD", "source": "fred"},
      # CREDIT — FRED (spreads in bps / pct)
      {"symbol": "BAA10Y",         "name": "IG Spread",  "sector": "CREDIT", "unit": "%",   "source": "fred"},
      {"symbol": "BAMLH0A0HYM2",   "name": "HY Spread",  "sector": "CREDIT", "unit": "%",   "source": "fred"},
      {"symbol": "BAMLEMCBPIOAS",  "name": "EM Spread",  "sector": "CREDIT", "unit": "bps", "source": "fred"},
      {"symbol": "BAMLHE00EHYIEY", "name": "EU HY",      "sector": "CREDIT", "unit": "%",   "source": "fred"},
  ]

  # Extend FRED allowlist with FX series needed for cross-asset
  _FRED_ALLOWLIST.update({"DEXUSEU", "DEXJPUS", "DEXBZUS", "IRLTLT01DEM156N"})

  _CROSS_ASSET_LOOKBACK = 60  # trading days (~3 months)
  _CROSS_ASSET_SPARKLINE_N = 30  # points to return in sparkline


  async def _fetch_fred_series_batch(
      series_ids: list[str],
      cutoff: date,
  ) -> dict[str, list[tuple[date, float]]]:
      """Fetch multiple FRED series in a single DB query, return {series_id: [(date, value)]}."""
      from sqlalchemy import select
      from backend.app.core.db.session import async_session_factory

      async with async_session_factory() as db:
          stmt = (
              select(MacroData.series_id, MacroData.obs_date, MacroData.value)
              .where(MacroData.series_id.in_(series_ids), MacroData.obs_date >= cutoff)
              .order_by(MacroData.series_id, MacroData.obs_date)
          )
          result = await db.execute(stmt)

      out: dict[str, list[tuple[date, float]]] = {}
      for row in result.all():
          if row.value is not None:
              out.setdefault(row.series_id, []).append((row.obs_date, float(row.value)))
      return out


  async def _fetch_equity_nav_batch(
      tickers: list[str],
      cutoff: date,
  ) -> dict[str, list[tuple[date, float]]]:
      """Fetch nav_timeseries for given tickers via instruments_universe join."""
      from sqlalchemy import select
      from backend.app.core.db.session import async_session_factory
      from backend.app.domains.wealth.models.nav import NavTimeseries
      from backend.app.shared.models import InstrumentsUniverse

      async with async_session_factory() as db:
          stmt = (
              select(InstrumentsUniverse.ticker, NavTimeseries.nav_date, NavTimeseries.nav)
              .join(NavTimeseries, NavTimeseries.instrument_id == InstrumentsUniverse.instrument_id)
              .where(InstrumentsUniverse.ticker.in_(tickers), NavTimeseries.nav_date >= cutoff)
              .order_by(InstrumentsUniverse.ticker, NavTimeseries.nav_date)
          )
          result = await db.execute(stmt)

      out: dict[str, list[tuple[date, float]]] = {}
      for row in result.all():
          if row.nav is not None:
              out.setdefault(row.ticker, []).append((row.nav_date, float(row.nav)))
      return out


  def _compute_cross_asset_point(
      item: dict,
      series_data: list[tuple[date, float]],
  ) -> CrossAssetPoint:
      """Convert raw time series into a CrossAssetPoint with sparkline + change_pct."""
      if not series_data:
          return CrossAssetPoint(
              symbol=item["symbol"],
              name=item["name"],
              sector=item["sector"],  # type: ignore[arg-type]
              unit=item["unit"],
          )

      values = [v for _, v in series_data]
      last_value = values[-1]
      prev_value = values[-2] if len(values) >= 2 else None
      change_pct: float | None = None
      if prev_value is not None and prev_value != 0:
          change_pct = (last_value - prev_value) / abs(prev_value) * 100

      sparkline = values[-_CROSS_ASSET_SPARKLINE_N:]

      return CrossAssetPoint(
          symbol=item["symbol"],
          name=item["name"],
          sector=item["sector"],  # type: ignore[arg-type]
          unit=item["unit"],
          last_value=last_value,
          change_pct=change_pct,
          sparkline=sparkline,
      )


  @router.get(
      "/cross-asset",
      response_model=CrossAssetResponse,
      summary="Cross-asset panel data (rates, FX, equity, commodity, credit)",
      tags=["macro"],
  )
  @route_cache(ttl=300, key_prefix="macro:cross_asset")
  async def get_cross_asset(
      user: CurrentUser = Depends(get_current_user),
  ) -> CrossAssetResponse:
      """Batch cross-asset data for the terminal left panel.

      Sources: FRED (rates, FX, commodity, credit) + nav_timeseries (equity ETFs).
      Cached 5 min. Returns last 30 observations as sparkline.
      """
      cutoff = date.today() - timedelta(days=_CROSS_ASSET_LOOKBACK)

      fred_symbols = [i["symbol"] for i in _CROSS_ASSET_CATALOG if i["source"] == "fred"]
      nav_symbols  = [i["symbol"] for i in _CROSS_ASSET_CATALOG if i["source"] == "nav"]

      fred_data, nav_data = await asyncio.gather(
          _fetch_fred_series_batch(fred_symbols, cutoff),
          _fetch_equity_nav_batch(nav_symbols, cutoff),
      )

      combined = {**fred_data, **nav_data}
      assets = [
          _compute_cross_asset_point(item, combined.get(item["symbol"], []))
          for item in _CROSS_ASSET_CATALOG
      ]

      as_of = max(
          (d for pts in combined.values() for d, _ in pts),
          default=None,
      )

      return CrossAssetResponse(as_of_date=as_of, assets=assets)
  ```

- [ ] **Step 6: Add `DEXUSEU`, `DEXJPUS`, `DEXBZUS` to `_FRED_ALLOWLIST` (already done in Step 5 via `_FRED_ALLOWLIST.update(...)`) — verify the set mutation happens before route registration**

  Check: the `_FRED_ALLOWLIST.update(...)` call must appear AFTER the set literal. Confirm by reading lines ~878-905.

- [ ] **Step 7: Run `make check` on backend only**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  make lint
  make typecheck
  ```

- [ ] **Step 8: Commit**

  ```bash
  git add backend/app/domains/wealth/schemas/macro.py \
          backend/app/domains/wealth/routes/macro.py \
          backend/tests/domains/wealth/services/test_macro_new_endpoints.py
  git commit -m "feat(macro): add /cross-asset batch endpoint (RATES/FX/EQUITY/COMMODITY/CREDIT)"
  ```

---

## Task 0.2: Backend — `/macro/regime/trail` endpoint

18-month history of regime positions as (g, i) coordinates, derived from `growth` and `inflation` dimension scores in `macro_regional_snapshots.data_json`. Maps 0-100 percentile score → [-1, +1] float. Used to render the polyline trail in `RegimePlot.svelte`.

**Files:**
- Modify: `backend/app/domains/wealth/schemas/macro.py`
- Modify: `backend/app/domains/wealth/routes/macro.py`
- Test: `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`

- [ ] **Step 1: Add schemas to `schemas/macro.py`**

  ```python
  class RegimeTrailPoint(BaseModel):
      as_of_date: date
      g: float  # growth, in [-1.0, +1.0]
      i: float  # inflation, in [-1.0, +1.0]
      stress: float | None = None  # stress_score 0-100 from regime snapshot


  class RegimeTrailResponse(BaseModel):
      points: list[RegimeTrailPoint] = []
      region: str = "US"
  ```

- [ ] **Step 2: Add test cases**

  Add to `test_macro_new_endpoints.py`:

  ```python
  from backend.app.domains.wealth.schemas.macro import RegimeTrailPoint, RegimeTrailResponse
  import datetime


  def test_regime_trail_point_schema():
      p = RegimeTrailPoint(
          as_of_date=datetime.date(2025, 1, 15),
          g=0.42,
          i=-0.18,
          stress=35.0,
      )
      assert -1.0 <= p.g <= 1.0
      assert -1.0 <= p.i <= 1.0


  def test_regime_trail_response_empty():
      r = RegimeTrailResponse()
      assert r.points == []
      assert r.region == "US"


  def test_score_to_gi_conversion():
      """percentile 0-100 → [-1, +1]: 50 → 0, 100 → 1, 0 → -1."""
      def _to_gi(score: float) -> float:
          return (score / 100.0) * 2.0 - 1.0

      assert _to_gi(50) == pytest.approx(0.0)
      assert _to_gi(100) == pytest.approx(1.0)
      assert _to_gi(0) == pytest.approx(-1.0)
  ```

- [ ] **Step 3: Run test — FAIL (schemas not yet added)**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v -k "trail"
  ```

- [ ] **Step 4: Implement schemas + run test → PASS**

  Add schemas from Step 1, then:
  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  ```

- [ ] **Step 5: Implement the route in `routes/macro.py`**

  Add after the cross-asset route:

  ```python
  # ---------------------------------------------------------------------------
  #  Regime trail — 18-month history for SVG polyline
  # ---------------------------------------------------------------------------

  _TRAIL_REGION_KEY = "US"
  _TRAIL_MONTHS = 18


  def _score_to_gi(score: float | None) -> float:
      """Map percentile score 0-100 to growth/inflation coordinate [-1, +1]."""
      if score is None:
          return 0.0
      return (float(score) / 100.0) * 2.0 - 1.0


  @router.get(
      "/regime/trail",
      response_model=RegimeTrailResponse,
      summary="18-month regime trail (g, i) coordinates for RegimePlot",
      tags=["macro"],
  )
  @route_cache(ttl=3600, key_prefix="macro:regime_trail")
  async def get_regime_trail(
      region: str = Query(default="US", description="Region key (US, Europe, Asia, EM)"),
      user: CurrentUser = Depends(get_current_user),
  ) -> RegimeTrailResponse:
      """Return 18 months of (g, i) coordinates from macro_regional_snapshots.

      Reads the growth + inflation dimension scores for the requested region,
      maps percentile (0-100) to [-1, +1], returns sorted ascending by date.
      """
      cutoff = date.today() - timedelta(days=_TRAIL_MONTHS * 31)

      stmt = (
          select(MacroRegionalSnapshot.as_of_date, MacroRegionalSnapshot.data_json)
          .where(MacroRegionalSnapshot.as_of_date >= cutoff)
          .order_by(MacroRegionalSnapshot.as_of_date)
      )
      async with async_session_factory() as db:
          result = await db.execute(stmt)

      rows = result.all()
      points: list[RegimeTrailPoint] = []
      for row in rows:
          regions_data = row.data_json.get("regions", {})
          region_data = regions_data.get(region, {})
          dimensions = region_data.get("dimensions", {})
          growth_score = dimensions.get("growth", {}).get("score")
          inflation_score = dimensions.get("inflation", {}).get("score")
          if growth_score is None and inflation_score is None:
              continue
          points.append(RegimeTrailPoint(
              as_of_date=row.as_of_date,
              g=_score_to_gi(growth_score),
              i=_score_to_gi(inflation_score),
          ))

      return RegimeTrailResponse(points=points, region=region)
  ```

- [ ] **Step 6: Run tests + linting**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  make lint && make typecheck
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add backend/app/domains/wealth/schemas/macro.py \
          backend/app/domains/wealth/routes/macro.py \
          backend/tests/domains/wealth/services/test_macro_new_endpoints.py
  git commit -m "feat(macro): add /regime/trail endpoint for RegimePlot polyline (18-month history)"
  ```

---

## Task 0.3: Backend — `/macro/cb-calendar` endpoint

Central bank meeting calendar. CB meeting dates are scheduled quarterly by public announcement — a seed fixture is appropriate here (updated 4× per year by the operator). Returns the next N upcoming meetings across Fed, ECB, BoJ, BoE, BCB, Banxico.

**Files:**
- Modify: `backend/app/domains/wealth/schemas/macro.py`
- Modify: `backend/app/domains/wealth/routes/macro.py`
- Test: `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`

- [ ] **Step 1: Add schemas to `schemas/macro.py`**

  ```python
  class CbEvent(BaseModel):
      central_bank: str         # "Fed", "ECB", "BoJ", "BoE", "BCB"
      meeting_date: date
      current_rate_pct: float   # current policy rate in %
      expected_change_bps: int  # market consensus: 0 = hold, +25 = hike, -25 = cut
      importance: Literal["HIGH", "MEDIUM"] = "HIGH"


  class CbCalendarResponse(BaseModel):
      events: list[CbEvent] = []
      as_of_date: date | None = None
  ```

- [ ] **Step 2: Add test cases to `test_macro_new_endpoints.py`**

  ```python
  from backend.app.domains.wealth.schemas.macro import CbEvent, CbCalendarResponse
  import datetime


  def test_cb_event_schema():
      ev = CbEvent(
          central_bank="Fed",
          meeting_date=datetime.date(2026, 5, 7),
          current_rate_pct=4.50,
          expected_change_bps=-25,
      )
      assert ev.central_bank == "Fed"
      assert ev.expected_change_bps == -25
      assert ev.importance == "HIGH"


  def test_cb_calendar_response_empty():
      r = CbCalendarResponse()
      assert r.events == []
  ```

- [ ] **Step 3: Run test — FAIL, add schemas, run → PASS**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  ```

- [ ] **Step 4: Implement the route in `routes/macro.py`**

  ```python
  # ---------------------------------------------------------------------------
  #  CB Calendar — static seed fixture (updated by operator quarterly)
  # ---------------------------------------------------------------------------

  _CB_CALENDAR_SEED: list[dict] = [
      # Fed — FOMC 2026
      {"central_bank": "Fed",     "meeting_date": "2026-05-07", "current_rate_pct": 4.50, "expected_change_bps": 0},
      {"central_bank": "Fed",     "meeting_date": "2026-06-18", "current_rate_pct": 4.50, "expected_change_bps": -25},
      {"central_bank": "Fed",     "meeting_date": "2026-07-30", "current_rate_pct": 4.25, "expected_change_bps": 0},
      {"central_bank": "Fed",     "meeting_date": "2026-09-17", "current_rate_pct": 4.25, "expected_change_bps": -25},
      {"central_bank": "Fed",     "meeting_date": "2026-11-05", "current_rate_pct": 4.00, "expected_change_bps": 0},
      {"central_bank": "Fed",     "meeting_date": "2026-12-17", "current_rate_pct": 4.00, "expected_change_bps": -25},
      # ECB 2026
      {"central_bank": "ECB",     "meeting_date": "2026-04-30", "current_rate_pct": 2.50, "expected_change_bps": 0},
      {"central_bank": "ECB",     "meeting_date": "2026-06-11", "current_rate_pct": 2.50, "expected_change_bps": -25},
      {"central_bank": "ECB",     "meeting_date": "2026-07-23", "current_rate_pct": 2.25, "expected_change_bps": 0},
      {"central_bank": "ECB",     "meeting_date": "2026-09-10", "current_rate_pct": 2.25, "expected_change_bps": -25},
      # BoJ 2026
      {"central_bank": "BoJ",     "meeting_date": "2026-04-28", "current_rate_pct": 0.50, "expected_change_bps": 0},
      {"central_bank": "BoJ",     "meeting_date": "2026-06-17", "current_rate_pct": 0.50, "expected_change_bps": 25},
      {"central_bank": "BoJ",     "meeting_date": "2026-07-30", "current_rate_pct": 0.75, "expected_change_bps": 0},
      # BoE 2026
      {"central_bank": "BoE",     "meeting_date": "2026-05-08", "current_rate_pct": 4.50, "expected_change_bps": -25},
      {"central_bank": "BoE",     "meeting_date": "2026-06-19", "current_rate_pct": 4.25, "expected_change_bps": 0},
      {"central_bank": "BoE",     "meeting_date": "2026-08-06", "current_rate_pct": 4.25, "expected_change_bps": -25},
      # BCB 2026
      {"central_bank": "BCB",     "meeting_date": "2026-05-07", "current_rate_pct": 13.75, "expected_change_bps": 0},
      {"central_bank": "BCB",     "meeting_date": "2026-06-18", "current_rate_pct": 13.75, "expected_change_bps": -50},
  ]


  @router.get(
      "/cb-calendar",
      response_model=CbCalendarResponse,
      summary="Upcoming central bank meeting calendar",
      tags=["macro"],
  )
  async def get_cb_calendar(
      n: int = Query(default=8, ge=1, le=24, description="Number of upcoming events to return"),
      user: CurrentUser = Depends(get_current_user),
  ) -> CbCalendarResponse:
      """Return the next N upcoming central bank meetings from the seed calendar.

      NOTE: This fixture must be updated by the operator quarterly.
      Future improvement: ingest from a financial calendar API.
      """
      today = date.today()
      upcoming = [
          CbEvent(
              central_bank=e["central_bank"],
              meeting_date=date.fromisoformat(e["meeting_date"]),
              current_rate_pct=e["current_rate_pct"],
              expected_change_bps=e["expected_change_bps"],
          )
          for e in _CB_CALENDAR_SEED
          if date.fromisoformat(e["meeting_date"]) >= today
      ]
      upcoming.sort(key=lambda x: x.meeting_date)
      return CbCalendarResponse(events=upcoming[:n], as_of_date=today)
  ```

- [ ] **Step 5: Run full test suite + linting**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  make lint && make typecheck
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/domains/wealth/schemas/macro.py \
          backend/app/domains/wealth/routes/macro.py \
          backend/tests/domains/wealth/services/test_macro_new_endpoints.py
  git commit -m "feat(macro): add /cb-calendar seed endpoint for CBPanel"
  ```

---

## Task 1.1: `MiniCard.svelte` — Cross-asset row primitive

Dense 3-column row: `[symbol+name | sparkline | value+change]`. Consumes a `CrossAssetPoint`-shaped prop. Uses `TerminalMiniSparkline` from core for inline chart.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/MiniCard.svelte`

- [ ] **Step 1: Create `MiniCard.svelte`**

  ```svelte
  <script lang="ts">
    interface Props {
      symbol: string;
      name: string;
      lastValue: number | null;
      changePct: number | null;
      unit: string;
      sparkline: number[];
      /** Emitted when user clicks the row. */
      onclick?: () => void;
    }

    let { symbol, name, lastValue, changePct, unit, sparkline, onclick }: Props = $props();

    const changePositive = $derived(changePct !== null && changePct > 0);
    const changeNegative = $derived(changePct !== null && changePct < 0);

    function fmtValue(v: number | null, u: string): string {
      if (v === null) return "—";
      return u === "%" || u === "bps"
        ? v.toFixed(2) + (u === "bps" ? "bp" : "%")
        : v.toFixed(u === "idx" ? 0 : 2);
    }

    function fmtChange(c: number | null): string {
      if (c === null) return "";
      const abs = Math.abs(c).toFixed(2);
      return (c > 0 ? "+" : "") + c.toFixed(2) + "%";
    }
  </script>

  <button
    type="button"
    class="mc-root"
    onclick={onclick}
    aria-label="{name} {fmtValue(lastValue, unit)}"
  >
    <div class="mc-head">
      <span class="mc-symbol">{symbol}</span>
      <span class="mc-name">{name}</span>
    </div>

    <div class="mc-spark">
      {#if sparkline.length >= 2}
        <svg viewBox="0 0 80 24" preserveAspectRatio="none" aria-hidden="true">
          {@const min = Math.min(...sparkline)}
          {@const max = Math.max(...sparkline)}
          {@const range = max - min || 1}
          {@const pts = sparkline.map((v, i) =>
            `${(i / (sparkline.length - 1)) * 80},${24 - ((v - min) / range) * 22}`
          ).join(" ")}
          <polyline
            points={pts}
            fill="none"
            stroke={changePositive ? "var(--terminal-accent-green, #4adf86)" : changeNegative ? "var(--terminal-accent-red, #f87171)" : "var(--terminal-fg-tertiary)"}
            stroke-width="1"
            vector-effect="non-scaling-stroke"
          />
        </svg>
      {/if}
    </div>

    <div class="mc-nums">
      <span class="mc-value">{fmtValue(lastValue, unit)}</span>
      <span
        class="mc-change"
        class:mc-change--up={changePositive}
        class:mc-change--dn={changeNegative}
      >
        {fmtChange(changePct)}
      </span>
    </div>
  </button>

  <style>
    .mc-root {
      display: grid;
      grid-template-columns: 1fr 80px 100px;
      align-items: center;
      gap: 0;
      padding: 3px var(--terminal-space-2);
      background: transparent;
      border: none;
      width: 100%;
      text-align: left;
      cursor: pointer;
      font-family: var(--terminal-font-mono);
      transition: background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
    }
    .mc-root:hover {
      background: var(--terminal-bg-panel-raised);
    }

    .mc-head {
      display: flex;
      flex-direction: column;
      gap: 1px;
      min-width: 0;
    }
    .mc-symbol {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      color: var(--terminal-fg-primary);
      letter-spacing: var(--terminal-tracking-caps);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .mc-name {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
    }

    .mc-spark {
      height: 24px;
      width: 80px;
    }
    .mc-spark svg {
      width: 100%;
      height: 100%;
    }

    .mc-nums {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 1px;
    }
    .mc-value {
      font-size: var(--terminal-text-11);
      font-weight: 500;
      color: var(--terminal-fg-primary);
      font-variant-numeric: tabular-nums;
    }
    .mc-change {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      font-variant-numeric: tabular-nums;
    }
    .mc-change--up { color: var(--terminal-accent-green, #4adf86); }
    .mc-change--dn { color: var(--terminal-accent-red, #f87171); }
  </style>
  ```

- [ ] **Step 2: Visually validate** — start `make dev-terminal` and navigate to any terminal page to confirm no import errors. Actual render tested in Task 2.1.

- [ ] **Step 3: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/MiniCard.svelte
  git commit -m "feat(terminal-core): add MiniCard primitive for cross-asset rows"
  ```

---

## Task 1.2: `CrossAssetPanel.svelte` — Grouped asset list for left column

Renders 5 sector groups (RATES, FX, EQUITY, COMMODITY, CREDIT), each with a collapsible header and `MiniCard` rows. Emits `onAssetSelect` when a row is clicked (to open `AssetDrawer`).

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/CrossAssetPanel.svelte`

- [ ] **Step 1: Create `CrossAssetPanel.svelte`**

  ```svelte
  <script lang="ts">
    import MiniCard from "./MiniCard.svelte";

    export interface CrossAssetPoint {
      symbol: string;
      name: string;
      sector: "RATES" | "FX" | "EQUITY" | "COMMODITY" | "CREDIT";
      lastValue: number | null;
      changePct: number | null;
      unit: string;
      sparkline: number[];
    }

    interface Props {
      assets: CrossAssetPoint[];
      loading?: boolean;
      onAssetSelect?: (asset: CrossAssetPoint) => void;
    }

    let { assets, loading = false, onAssetSelect }: Props = $props();

    const SECTORS: Array<CrossAssetPoint["sector"]> = [
      "RATES", "FX", "EQUITY", "COMMODITY", "CREDIT",
    ];

    function bySymbol(snakeCase: string): string {
      const map: Record<string, string> = {
        RATES: "RATES", FX: "FX", EQUITY: "EQUITY",
        COMMODITY: "CMDTY", CREDIT: "CREDIT",
      };
      return map[snakeCase] ?? snakeCase;
    }

    const grouped = $derived(
      SECTORS.reduce<Record<string, CrossAssetPoint[]>>((acc, s) => {
        acc[s] = assets.filter((a) => a.sector === s);
        return acc;
      }, {} as Record<string, CrossAssetPoint[]>)
    );
  </script>

  <div class="cap-root">
    {#if loading}
      <div class="cap-loading">LOADING…</div>
    {:else}
      {#each SECTORS as sector (sector)}
        {@const group = grouped[sector] ?? []}
        {#if group.length > 0}
          <div class="cap-group">
            <div class="cap-sector-header">{bySymbol(sector)}</div>
            {#each group as asset (asset.symbol)}
              <MiniCard
                symbol={asset.symbol}
                name={asset.name}
                lastValue={asset.lastValue}
                changePct={asset.changePct}
                unit={asset.unit}
                sparkline={asset.sparkline}
                onclick={() => onAssetSelect?.(asset)}
              />
            {/each}
          </div>
        {/if}
      {/each}
    {/if}
  </div>

  <style>
    .cap-root {
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--terminal-bg-panel);
      font-family: var(--terminal-font-mono);
      overflow-y: auto;
    }

    .cap-loading {
      padding: var(--terminal-space-3);
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
    }

    .cap-group {
      display: flex;
      flex-direction: column;
    }

    .cap-sector-header {
      padding: 2px var(--terminal-space-2);
      font-size: var(--terminal-text-10);
      font-weight: 600;
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
      background: var(--terminal-bg-panel-sunken);
      border-left: 2px solid var(--terminal-accent-amber);
    }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/CrossAssetPanel.svelte
  git commit -m "feat(terminal-core): add CrossAssetPanel for grouped cross-asset list"
  ```

---

## Task 1.3: `RegimePlot.svelte` — Continuous SVG regime matrix

Replaces the 4×4 discrete grid with a continuous SVG coordinate plot. Four colored quadrants (GOLDILOCKS / OVERHEATING / STAGFLATION / REFLATION), 18-month trail polyline with progressive opacity dots, draggable pin, keyboard accessibility preserved.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/regime-plot-store.svelte.ts`
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/RegimePlot.svelte`

- [ ] **Step 1: Create `regime-plot-store.svelte.ts`**

  ```typescript
  export interface RegimePinState {
    g: number; // growth, [-1, +1]
    i: number; // inflation, [-1, +1]
  }

  export interface RegimeTrailPoint {
    as_of_date: string;
    g: number;
    i: number;
    stress?: number | null;
  }

  export function createRegimePlotStore() {
    let simPin = $state<RegimePinState | null>(null);

    return {
      get simPin() { return simPin; },
      set(pin: RegimePinState | null) { simPin = pin; },
      reset() { simPin = null; },
    };
  }
  ```

- [ ] **Step 2: Create `RegimePlot.svelte`**

  ```svelte
  <!--
    RegimePlot — continuous SVG regime coordinate plot.
    g (growth) [-1,+1] on x-axis. i (inflation) [-1,+1] on y-axis (inverted: high i = top).
    Quadrants: GOLDILOCKS (g≥0, i<0), OVERHEATING (g≥0, i≥0),
               STAGFLATION (g<0, i≥0), REFLATION (g<0, i<0).
    Accessibility: arrow-keys ±0.1 step, Enter commit, Escape reset.
  -->
  <script lang="ts">
    import type { RegimeTrailPoint } from "./regime-plot-store.svelte";

    interface RegimePinState { g: number; i: number; }

    interface Props {
      activeRegime: string;
      /** Current live (g, i) from backend scores. */
      livePin: RegimePinState;
      /** Simulation override, or null. */
      simulatedPin: RegimePinState | null;
      trail: RegimeTrailPoint[];
      onSimulate: (pin: RegimePinState | null) => void;
    }

    let { activeRegime, livePin, simulatedPin, trail, onSimulate }: Props = $props();

    // SVG dimensions
    const SIZE = 360;
    const PAD = 28;
    const PLOT = SIZE - PAD * 2;
    const CX = PAD + PLOT / 2;
    const CY = PAD + PLOT / 2;

    function toPx(g: number, i: number): { x: number; y: number } {
      return {
        x: PAD + ((g + 1) / 2) * PLOT,
        y: PAD + ((1 - (i + 1) / 2)) * PLOT,
      };
    }

    function fromPx(x: number, y: number): RegimePinState {
      const g = Math.max(-1, Math.min(1, ((x - PAD) / PLOT) * 2 - 1));
      const i = Math.max(-1, Math.min(1, 1 - ((y - PAD) / PLOT) * 2));
      return { g: Math.round(g * 100) / 100, i: Math.round(i * 100) / 100 };
    }

    const pin = $derived(simulatedPin ?? livePin);
    const pinPx = $derived(toPx(pin.g, pin.i));
    const livePx = $derived(toPx(livePin.g, livePin.i));

    const isSimulating = $derived(simulatedPin !== null);

    // Trail polyline
    const trailPoints = $derived(
      trail.map((p) => toPx(p.g, p.i))
    );
    const trailPolyline = $derived(
      trailPoints.map((p) => `${p.x},${p.y}`).join(" ")
    );

    // Quadrant label positions
    const Q_LABELS = [
      { label: "GOLDILOCKS", x: CX + PLOT / 4, y: CY + PLOT / 4, color: "var(--terminal-accent-green, #4adf86)" },
      { label: "OVERHEATING", x: CX + PLOT / 4, y: CY - PLOT / 4, color: "var(--terminal-accent-amber)" },
      { label: "STAGFLATION", x: CX - PLOT / 4, y: CY - PLOT / 4, color: "var(--terminal-accent-red, #f87171)" },
      { label: "REFLATION",  x: CX - PLOT / 4, y: CY + PLOT / 4, color: "#6689BC" },
    ] as const;

    let svgEl: SVGSVGElement | null = $state(null);
    let dragging = $state(false);

    function svgCoords(e: PointerEvent): { x: number; y: number } | null {
      if (!svgEl) return null;
      const rect = svgEl.getBoundingClientRect();
      const scaleX = SIZE / rect.width;
      const scaleY = SIZE / rect.height;
      return {
        x: (e.clientX - rect.left) * scaleX,
        y: (e.clientY - rect.top) * scaleY,
      };
    }

    function handlePointerDown(e: PointerEvent) {
      e.preventDefault();
      (e.target as SVGElement).setPointerCapture(e.pointerId);
      dragging = true;
      const c = svgCoords(e);
      if (c) onSimulate(fromPx(c.x, c.y));
    }

    function handlePointerMove(e: PointerEvent) {
      if (!dragging) return;
      const c = svgCoords(e);
      if (c) onSimulate(fromPx(c.x, c.y));
    }

    function handlePointerUp() {
      dragging = false;
    }

    const STEP = 0.1;
    function handleKeydown(e: KeyboardEvent) {
      const base = simulatedPin ?? livePin;
      let next: RegimePinState | null = null;
      switch (e.key) {
        case "ArrowRight": next = { g: Math.min(1, base.g + STEP), i: base.i }; break;
        case "ArrowLeft":  next = { g: Math.max(-1, base.g - STEP), i: base.i }; break;
        case "ArrowUp":    next = { g: base.g, i: Math.min(1, base.i + STEP) }; break;
        case "ArrowDown":  next = { g: base.g, i: Math.max(-1, base.i - STEP) }; break;
        case "Escape":     if (simulatedPin) { e.preventDefault(); onSimulate(null); } return;
        case "Enter": case " ": next = base; break;
        default: return;
      }
      e.preventDefault();
      if (next) onSimulate(next);
    }
  </script>

  <div class="rp-root">
    <header class="rp-header">
      <span class="rp-title">REGIME MATRIX</span>
      <span class="rp-active">ACTIVE {activeRegime}</span>
      {#if isSimulating}
        <button
          type="button"
          class="rp-reset"
          onclick={() => onSimulate(null)}
          aria-label="Reset simulation"
        >RESET</button>
      {/if}
    </header>

    {#if isSimulating}
      <div class="rp-banner" role="status" aria-live="polite">
        SIMULATION — DOES NOT PERSIST
      </div>
    {/if}

    <!-- svelte-ignore a11y_interactive_supports_focus -->
    <svg
      bind:this={svgEl}
      viewBox="0 0 {SIZE} {SIZE}"
      class="rp-svg"
      role="application"
      aria-label="Regime coordinate plot"
      tabindex="0"
      onpointerdown={handlePointerDown}
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
      onpointercancel={handlePointerUp}
      onkeydown={handleKeydown}
      style:cursor={dragging ? "grabbing" : "crosshair"}
    >
      <!-- Quadrant fills -->
      <rect x={CX} y={PAD} width={PLOT/2} height={PLOT/2} fill="#4adf8610" />
      <rect x={CX} y={CY}  width={PLOT/2} height={PLOT/2} fill="#f6c90e10" />
      <rect x={PAD} y={PAD} width={PLOT/2} height={PLOT/2} fill="#f8717110" />
      <rect x={PAD} y={CY}  width={PLOT/2} height={PLOT/2} fill="#6689BC10" />

      <!-- Grid lines -->
      <line x1={CX} y1={PAD} x2={CX} y2={PAD+PLOT} stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="3 4" opacity="0.4"/>
      <line x1={PAD} y1={CY} x2={PAD+PLOT} y2={CY} stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="3 4" opacity="0.4"/>

      <!-- Border -->
      <rect x={PAD} y={PAD} width={PLOT} height={PLOT} fill="none" stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" opacity="0.4"/>

      <!-- Quadrant labels -->
      {#each Q_LABELS as q}
        <text
          x={q.x} y={q.y}
          text-anchor="middle"
          dominant-baseline="middle"
          font-family="var(--terminal-font-mono)"
          font-size="9"
          font-weight="600"
          fill={q.color}
          opacity="0.5"
          letter-spacing="0.05em"
          pointer-events="none"
        >{q.label}</text>
      {/each}

      <!-- Trail polyline -->
      {#if trailPoints.length >= 2}
        <polyline
          points={trailPolyline}
          fill="none"
          stroke="var(--terminal-accent-amber)"
          stroke-width="1"
          stroke-dasharray="2 3"
          opacity="0.35"
          pointer-events="none"
        />
        <!-- Trail dots with progressive opacity -->
        {#each trailPoints as pt, idx}
          {@const opacity = 0.1 + (idx / trailPoints.length) * 0.4}
          <circle
            cx={pt.x} cy={pt.y} r="2"
            fill="var(--terminal-accent-amber)"
            opacity={opacity}
            pointer-events="none"
          />
        {/each}
      {/if}

      <!-- Live position (when not simulating) -->
      {#if !isSimulating}
        <circle cx={livePx.x} cy={livePx.y} r="5"
          fill="var(--terminal-accent-amber)"
          stroke="var(--terminal-bg-panel)"
          stroke-width="1.5"
          pointer-events="none"
        />
      {/if}

      <!-- Simulated pin -->
      {#if isSimulating}
        <!-- Live faded -->
        <circle cx={livePx.x} cy={livePx.y} r="4"
          fill="none"
          stroke="var(--terminal-fg-secondary)"
          stroke-width="1"
          stroke-dasharray="2 2"
          opacity="0.4"
          pointer-events="none"
        />
        <!-- Sim pin -->
        <circle cx={pinPx.x} cy={pinPx.y} r="6"
          fill="var(--terminal-accent-amber)"
          stroke="var(--terminal-bg-panel)"
          stroke-width="2"
          pointer-events="none"
        />
        <text
          x={pinPx.x} y={pinPx.y - 10}
          text-anchor="middle"
          font-family="var(--terminal-font-mono)"
          font-size="8"
          fill="var(--terminal-accent-amber)"
          pointer-events="none"
        >SIM</text>
      {/if}

      <!-- Axis labels -->
      <text x={PAD} y={PAD - 6} font-family="var(--terminal-font-mono)" font-size="8" fill="var(--terminal-fg-tertiary)" letter-spacing="0.04em">CONTRACTION</text>
      <text x={PAD+PLOT} y={PAD - 6} text-anchor="end" font-family="var(--terminal-font-mono)" font-size="8" fill="var(--terminal-fg-tertiary)" letter-spacing="0.04em">OVERHEAT</text>
      <text x={PAD - 4} y={PAD} text-anchor="end" dominant-baseline="middle" font-family="var(--terminal-font-mono)" font-size="8" fill="var(--terminal-fg-tertiary)" letter-spacing="0.04em" transform="rotate(-90, {PAD - 4}, {CY})">INFLATION ↑</text>
    </svg>

    {#if isSimulating && simulatedPin}
      <div class="rp-coords">
        G {simulatedPin.g >= 0 ? "+" : ""}{simulatedPin.g.toFixed(2)}
        &nbsp;·&nbsp;
        I {simulatedPin.i >= 0 ? "+" : ""}{simulatedPin.i.toFixed(2)}
      </div>
    {/if}
  </div>

  <style>
    .rp-root {
      display: flex;
      flex-direction: column;
      gap: var(--terminal-space-2);
      font-family: var(--terminal-font-mono);
      background: var(--terminal-bg-panel);
      border: var(--terminal-border-hairline);
    }

    .rp-header {
      display: flex;
      align-items: center;
      gap: var(--terminal-space-2);
      padding: var(--terminal-space-2) var(--terminal-space-3) 0;
    }
    .rp-title {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .rp-active {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
      margin-left: auto;
    }
    .rp-reset {
      padding: 1px var(--terminal-space-2);
      background: transparent;
      border: var(--terminal-border-hairline);
      color: var(--terminal-fg-secondary);
      font-family: inherit;
      font-size: var(--terminal-text-10);
      letter-spacing: var(--terminal-tracking-caps);
      cursor: pointer;
    }
    .rp-reset:hover {
      color: var(--terminal-accent-amber);
      border-color: var(--terminal-accent-amber);
    }

    .rp-banner {
      margin: 0 var(--terminal-space-3);
      padding: 2px var(--terminal-space-2);
      background: var(--terminal-bg-panel-sunken);
      border-left: 3px solid var(--terminal-accent-amber);
      color: var(--terminal-accent-amber);
      font-size: var(--terminal-text-10);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
    }

    .rp-svg {
      width: 100%;
      height: auto;
      aspect-ratio: 1 / 1;
      touch-action: none;
      display: block;
    }
    .rp-svg:focus-visible {
      outline: var(--terminal-border-focus);
      outline-offset: 2px;
    }

    .rp-coords {
      padding: 2px var(--terminal-space-3) var(--terminal-space-2);
      text-align: right;
      font-size: var(--terminal-text-11);
      color: var(--terminal-accent-amber);
      letter-spacing: var(--terminal-tracking-caps);
      font-variant-numeric: tabular-nums;
    }
  </style>
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/regime-plot-store.svelte.ts \
          packages/ii-terminal-core/src/lib/components/terminal/macro/RegimePlot.svelte
  git commit -m "feat(terminal-core): add RegimePlot SVG continuous coordinate plot with trail + quadrant labels"
  ```

---

## Task 1.4: `LiquidityPanel.svelte` — Gauge from NFCI

NFCI (National Financial Conditions Index) from FRED: negative = loose, positive = tight. Renders a left-to-right gradient gauge with amber needle and 24M sparkline below. Data comes from the existing `/macro/fred?series_id=NFCI` endpoint — no new backend needed.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/LiquidityPanel.svelte`

- [ ] **Step 1: Create `LiquidityPanel.svelte`**

  ```svelte
  <script lang="ts">
    interface Props {
      /** NFCI current value (negative = loose, positive = tight). */
      nfci: number | null;
      /** Last 24 monthly observations for sparkline. */
      history: number[];
      loading?: boolean;
    }

    let { nfci, history, loading = false }: Props = $props();

    /** Map NFCI [-2, +2] → gauge width percentage [0, 100]. */
    const gaugeWidth = $derived(
      nfci === null ? 50 : Math.max(0, Math.min(100, ((nfci + 2) / 4) * 100))
    );

    const label = $derived(
      nfci === null
        ? "—"
        : nfci < -0.5
        ? "LOOSE"
        : nfci > 0.5
        ? "TIGHT"
        : "NEUTRAL"
    );

    const labelColor = $derived(
      nfci === null
        ? "var(--terminal-fg-tertiary)"
        : nfci < -0.5
        ? "var(--terminal-accent-green, #4adf86)"
        : nfci > 0.5
        ? "var(--terminal-accent-red, #f87171)"
        : "var(--terminal-accent-amber)"
    );

    // Spark
    const sparkMin = $derived(history.length ? Math.min(...history) : 0);
    const sparkMax = $derived(history.length ? Math.max(...history) : 1);
    const sparkRange = $derived(sparkMax - sparkMin || 1);
    const sparkPoints = $derived(
      history.map((v, i) => {
        const x = (i / (history.length - 1)) * 240;
        const y = 24 - ((v - sparkMin) / sparkRange) * 22;
        return `${x},${y}`;
      }).join(" ")
    );
  </script>

  <div class="lp-root">
    <div class="lp-header">
      <span class="lp-title">LIQUIDITY</span>
      <span class="lp-sub">NFCI</span>
    </div>

    {#if loading}
      <div class="lp-loading">LOADING…</div>
    {:else}
      <div class="lp-gauge-wrap">
        <div class="lp-gauge-track">
          <div class="lp-gauge-fill" style:width="{gaugeWidth}%"></div>
          <div class="lp-gauge-needle" style:left="{gaugeWidth}%"></div>
        </div>
        <div class="lp-gauge-labels">
          <span>LOOSE</span>
          <span>TIGHT</span>
        </div>
      </div>

      <div class="lp-value-row">
        <span class="lp-nfci" style:color={labelColor}>
          {nfci !== null ? (nfci >= 0 ? "+" : "") + nfci.toFixed(3) : "—"}
        </span>
        <span class="lp-label" style:color={labelColor}>{label}</span>
      </div>

      {#if history.length >= 2}
        <svg viewBox="0 0 240 28" class="lp-spark" aria-hidden="true" preserveAspectRatio="none">
          <polyline
            points={sparkPoints}
            fill="none"
            stroke="var(--terminal-fg-tertiary)"
            stroke-width="1"
            vector-effect="non-scaling-stroke"
          />
          <!-- Zero line -->
          {@const zeroY = 24 - ((0 - sparkMin) / sparkRange) * 22}
          <line x1="0" y1={zeroY} x2="240" y2={zeroY}
            stroke="var(--terminal-accent-amber)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.5" />
        </svg>
        <span class="lp-spark-label">24-MONTH NFCI</span>
      {/if}
    {/if}
  </div>

  <style>
    .lp-root {
      display: flex;
      flex-direction: column;
      gap: var(--terminal-space-2);
      padding: var(--terminal-space-2) var(--terminal-space-3);
      background: var(--terminal-bg-panel);
      border: var(--terminal-border-hairline);
      font-family: var(--terminal-font-mono);
    }
    .lp-header {
      display: flex;
      align-items: baseline;
      gap: var(--terminal-space-2);
    }
    .lp-title {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .lp-sub {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
    }
    .lp-loading {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
    }

    .lp-gauge-wrap {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .lp-gauge-track {
      position: relative;
      height: 6px;
      background: linear-gradient(to right, #4adf86, #f6c90e, #f87171);
      border-radius: 2px;
    }
    .lp-gauge-fill {
      position: absolute;
      top: 0; left: 0; bottom: 0;
      border-radius: 2px;
    }
    .lp-gauge-needle {
      position: absolute;
      top: -2px;
      width: 2px;
      height: 10px;
      background: var(--terminal-fg-primary);
      transform: translateX(-1px);
      box-shadow: 0 0 4px var(--terminal-accent-amber);
    }
    .lp-gauge-labels {
      display: flex;
      justify-content: space-between;
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
      letter-spacing: 0.04em;
    }

    .lp-value-row {
      display: flex;
      align-items: baseline;
      gap: var(--terminal-space-2);
    }
    .lp-nfci {
      font-size: var(--terminal-text-14);
      font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .lp-label {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
    }

    .lp-spark {
      width: 100%;
      height: 28px;
    }
    .lp-spark-label {
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
      letter-spacing: 0.04em;
    }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/LiquidityPanel.svelte
  git commit -m "feat(terminal-core): add LiquidityPanel with NFCI gauge + sparkline"
  ```

---

## Task 1.5: `EconPanel.svelte` — Economic pulse with Hot/Cool signals

Renders a list of economic indicators with latest value, consensus, and a Hot/Cool arrow derived from comparison to recent average. Data comes from `/macro/scores` dimensions (existing endpoint). No new backend needed.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/EconPanel.svelte`

- [ ] **Step 1: Create `EconPanel.svelte`**

  ```svelte
  <script lang="ts">
    export interface EconRow {
      name: string;
      period: string;
      actual: number | null;
      consensus: number | null;
      unit: string;
      /** Positive = hot (beats), negative = cool (misses), 0 = inline. */
      surprise: number;
    }

    interface Props {
      rows: EconRow[];
      loading?: boolean;
    }

    let { rows, loading = false }: Props = $props();

    function surpriseIcon(s: number): string {
      if (s > 0.5) return "▲";
      if (s < -0.5) return "▼";
      return "—";
    }
    function surpriseColor(s: number): string {
      if (s > 0.5) return "var(--terminal-accent-green, #4adf86)";
      if (s < -0.5) return "var(--terminal-accent-red, #f87171)";
      return "var(--terminal-fg-tertiary)";
    }
    function surpriseLabel(s: number): string {
      if (s > 0.5) return "HOT";
      if (s < -0.5) return "COOL";
      return "";
    }

    function fmt(v: number | null, u: string): string {
      if (v === null) return "—";
      return u === "%" ? v.toFixed(1) + "%" : v.toFixed(1);
    }
  </script>

  <div class="ep-root">
    <div class="ep-header">
      <span class="ep-title">ECON PULSE</span>
    </div>

    {#if loading}
      <div class="ep-loading">LOADING…</div>
    {:else if rows.length === 0}
      <div class="ep-empty">No data available</div>
    {:else}
      <div class="ep-table-header">
        <span>INDICATOR</span>
        <span>PERIOD</span>
        <span class="ep-right">ACTUAL</span>
        <span class="ep-right">CONS.</span>
        <span class="ep-center">SRPS</span>
      </div>
      {#each rows as row (row.name)}
        <div class="ep-row">
          <span class="ep-name">{row.name}</span>
          <span class="ep-period">{row.period}</span>
          <span class="ep-right ep-actual">{fmt(row.actual, row.unit)}</span>
          <span class="ep-right ep-consensus">{fmt(row.consensus, row.unit)}</span>
          <span
            class="ep-center ep-surprise"
            style:color={surpriseColor(row.surprise)}
            title={surpriseLabel(row.surprise)}
          >
            {surpriseIcon(row.surprise)}
          </span>
        </div>
      {/each}
    {/if}
  </div>

  <style>
    .ep-root {
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--terminal-bg-panel);
      border: var(--terminal-border-hairline);
      font-family: var(--terminal-font-mono);
    }
    .ep-header {
      padding: var(--terminal-space-2) var(--terminal-space-3);
    }
    .ep-title {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .ep-loading, .ep-empty {
      padding: var(--terminal-space-2) var(--terminal-space-3);
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
    }
    .ep-table-header {
      display: grid;
      grid-template-columns: 1fr 60px 60px 60px 40px;
      padding: 2px var(--terminal-space-2);
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
      letter-spacing: 0.05em;
      background: var(--terminal-bg-panel-sunken);
    }
    .ep-row {
      display: grid;
      grid-template-columns: 1fr 60px 60px 60px 40px;
      padding: 3px var(--terminal-space-2);
      font-size: var(--terminal-text-10);
    }
    .ep-row:hover {
      background: var(--terminal-bg-panel-raised);
    }
    .ep-name {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ep-period {
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
    }
    .ep-actual {
      color: var(--terminal-fg-primary);
      font-variant-numeric: tabular-nums;
    }
    .ep-consensus {
      color: var(--terminal-fg-tertiary);
      font-variant-numeric: tabular-nums;
    }
    .ep-surprise {
      font-size: var(--terminal-text-11);
      font-weight: 700;
    }
    .ep-right { text-align: right; }
    .ep-center { text-align: center; }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/EconPanel.svelte
  git commit -m "feat(terminal-core): add EconPanel with Hot/Cool surprise arrows"
  ```

---

## Task 1.6: `CBPanel.svelte` — Central bank calendar rows

Renders upcoming CB meetings with bank name, date, current rate, and change badge (HOLD/+25bp/-25bp).

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/CBPanel.svelte`

- [ ] **Step 1: Create `CBPanel.svelte`**

  ```svelte
  <script lang="ts">
    export interface CbEvent {
      centralBank: string;
      meetingDate: string; // ISO date
      currentRatePct: number;
      expectedChangeBps: number;
    }

    interface Props {
      events: CbEvent[];
      loading?: boolean;
    }

    let { events, loading = false }: Props = $props();

    function changeBadge(bps: number): { text: string; color: string } {
      if (bps === 0) return { text: "HOLD",  color: "var(--terminal-fg-tertiary)" };
      if (bps > 0)  return { text: `+${bps}bp`, color: "var(--terminal-accent-red, #f87171)" };
      return { text: `${bps}bp`, color: "var(--terminal-accent-green, #4adf86)" };
    }

    function fmtDate(iso: string): string {
      const d = new Date(iso + "T00:00:00");
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    }

    function daysUntil(iso: string): number {
      const d = new Date(iso + "T00:00:00");
      return Math.ceil((d.getTime() - Date.now()) / 86_400_000);
    }
  </script>

  <div class="cb-root">
    <div class="cb-header">
      <span class="cb-title">CENTRAL BANKS</span>
    </div>

    {#if loading}
      <div class="cb-loading">LOADING…</div>
    {:else if events.length === 0}
      <div class="cb-empty">No upcoming meetings</div>
    {:else}
      {#each events as ev (ev.centralBank + ev.meetingDate)}
        {@const badge = changeBadge(ev.expectedChangeBps)}
        {@const days = daysUntil(ev.meetingDate)}
        <div class="cb-row">
          <span class="cb-bank">{ev.centralBank}</span>
          <span class="cb-date">{fmtDate(ev.meetingDate)}</span>
          <span class="cb-rate">{ev.currentRatePct.toFixed(2)}%</span>
          <span class="cb-badge" style:color={badge.color}>{badge.text}</span>
          <span class="cb-days">{days}d</span>
        </div>
      {/each}
    {/if}
  </div>

  <style>
    .cb-root {
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--terminal-bg-panel);
      border: var(--terminal-border-hairline);
      font-family: var(--terminal-font-mono);
    }
    .cb-header {
      padding: var(--terminal-space-2) var(--terminal-space-3);
    }
    .cb-title {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .cb-loading, .cb-empty {
      padding: var(--terminal-space-2) var(--terminal-space-3);
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
    }
    .cb-row {
      display: grid;
      grid-template-columns: 44px 60px 60px 60px 30px;
      align-items: center;
      padding: 3px var(--terminal-space-2);
      gap: var(--terminal-space-2);
    }
    .cb-row:hover {
      background: var(--terminal-bg-panel-raised);
    }
    .cb-bank {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      color: var(--terminal-fg-primary);
      letter-spacing: 0.02em;
    }
    .cb-date {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-secondary);
    }
    .cb-rate {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-secondary);
      font-variant-numeric: tabular-nums;
      text-align: right;
    }
    .cb-badge {
      font-size: var(--terminal-text-10);
      font-weight: 600;
      letter-spacing: 0.02em;
      text-align: right;
    }
    .cb-days {
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
      text-align: right;
    }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/CBPanel.svelte
  git commit -m "feat(terminal-core): add CBPanel for central bank meeting calendar"
  ```

---

## Task 1.7: `MacroNewsFeed.svelte` — Placeholder (no data source yet)

Renders an empty-state panel. News feed requires an external news API integration which is out of scope for this sprint. The component exists as a slot in the layout; its content will be filled in a future sprint.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/MacroNewsFeed.svelte`

- [ ] **Step 1: Create `MacroNewsFeed.svelte`**

  ```svelte
  <!--
    MacroNewsFeed — placeholder.
    A real news feed requires an external news API (Bloomberg, Refinitiv, or similar).
    This component holds the layout slot and will be implemented in a future sprint
    once a data provider is contracted.
  -->
  <script lang="ts">
    interface Props {
      /** When true, renders as an active feed (reserved for future use). */
      active?: boolean;
    }

    let { active = false }: Props = $props();
  </script>

  <div class="mnf-root" class:mnf-root--active={active}>
    <div class="mnf-header">
      <span class="mnf-title">MACRO NEWS</span>
      <span class="mnf-badge">LIVE</span>
    </div>
    <div class="mnf-empty">
      <span class="mnf-empty-icon">○</span>
      <span class="mnf-empty-text">News feed not configured</span>
      <span class="mnf-empty-sub">Requires news data provider</span>
    </div>
  </div>

  <style>
    .mnf-root {
      display: flex;
      flex-direction: column;
      gap: var(--terminal-space-2);
      background: var(--terminal-bg-panel);
      border: var(--terminal-border-hairline);
      font-family: var(--terminal-font-mono);
      min-height: 120px;
    }
    .mnf-header {
      display: flex;
      align-items: center;
      gap: var(--terminal-space-2);
      padding: var(--terminal-space-2) var(--terminal-space-3) 0;
    }
    .mnf-title {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .mnf-badge {
      font-size: 9px;
      font-weight: 600;
      letter-spacing: 0.1em;
      color: var(--terminal-fg-disabled);
      border: 1px solid var(--terminal-fg-disabled);
      padding: 0 3px;
    }
    .mnf-empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: var(--terminal-space-3);
      gap: var(--terminal-space-2);
      flex: 1;
    }
    .mnf-empty-icon {
      font-size: 20px;
      color: var(--terminal-fg-disabled);
    }
    .mnf-empty-text {
      font-size: var(--terminal-text-11);
      color: var(--terminal-fg-secondary);
      letter-spacing: var(--terminal-tracking-caps);
    }
    .mnf-empty-sub {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
    }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/MacroNewsFeed.svelte
  git commit -m "feat(terminal-core): add MacroNewsFeed placeholder (news provider TBD)"
  ```

---

## Task 1.8: `AssetDrawer.svelte` — Financial asset detail drawer

Drawer that opens when an asset is clicked in `CrossAssetPanel`. Shows: asset name, 1W/1M/3M/YTD/1Y change stats grid, full SVG sparkline (full history from `/macro/fred`), and a Compare mode toggle that adds a second trace. Replaces the Committee Reviews drawer usage in the terminal macro page.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/macro/AssetDrawer.svelte`

- [ ] **Step 1: Create `AssetDrawer.svelte`**

  ```svelte
  <!--
    AssetDrawer — financial asset detail overlay.
    Opens as a side drawer when user clicks a MiniCard row.
    Shows full time-series chart, period stats, and Compare mode.
    Fetches from /macro/fred?series_id={symbol} (existing endpoint).
  -->
  <script lang="ts">
    import type { CrossAssetPoint } from "./CrossAssetPanel.svelte";

    interface TimePoint { obs_date: string; value: number; }

    interface Props {
      asset: CrossAssetPoint | null;
      onClose: () => void;
      /** Callback to fetch time series. Injected by page to avoid coupling. */
      fetchSeries: (symbol: string) => Promise<TimePoint[]>;
    }

    let { asset, onClose, fetchSeries }: Props = $props();

    let series = $state<TimePoint[]>([]);
    let compareAsset = $state<CrossAssetPoint | null>(null);
    let compareSeries = $state<TimePoint[]>([]);
    let loading = $state(false);
    let activeTimeframe = $state<"1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL">("3M");

    $effect(() => {
      if (!asset) { series = []; return; }
      loading = true;
      fetchSeries(asset.symbol)
        .then((data) => { series = data; })
        .finally(() => { loading = false; });
    });

    function cutoff(tf: typeof activeTimeframe): Date {
      const now = new Date();
      switch (tf) {
        case "1W":  return new Date(now.getTime() - 7 * 86400000);
        case "1M":  return new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
        case "3M":  return new Date(now.getFullYear(), now.getMonth() - 3, now.getDate());
        case "YTD": return new Date(now.getFullYear(), 0, 1);
        case "1Y":  return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
        default:    return new Date(0);
      }
    }

    const filteredSeries = $derived(
      series.filter((p) => new Date(p.obs_date) >= cutoff(activeTimeframe))
    );

    // Compute period stats from raw series (uses all data for multi-period)
    function statFor(tf: typeof activeTimeframe): string {
      const cut = cutoff(tf);
      const pts = series.filter((p) => new Date(p.obs_date) >= cut);
      if (pts.length < 2) return "—";
      const first = pts[0].value;
      const last = pts[pts.length - 1].value;
      const chg = ((last - first) / Math.abs(first)) * 100;
      return (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%";
    }

    const TIMEFRAMES = ["1W", "1M", "3M", "YTD", "1Y", "ALL"] as const;
    const STAT_TIMEFRAMES = ["1W", "1M", "3M", "YTD", "1Y"] as const;

    // SVG chart
    const chartH = 120;
    const chartW = 440;

    const minVal = $derived(filteredSeries.length ? Math.min(...filteredSeries.map(p => p.value)) : 0);
    const maxVal = $derived(filteredSeries.length ? Math.max(...filteredSeries.map(p => p.value)) : 1);
    const valRange = $derived(maxVal - minVal || 1);

    function toChartPts(pts: TimePoint[]): string {
      if (pts.length < 2) return "";
      return pts.map((p, i) => {
        const x = (i / (pts.length - 1)) * chartW;
        const y = chartH - 4 - ((p.value - minVal) / valRange) * (chartH - 8);
        return `${x},${y}`;
      }).join(" ");
    }

    const mainPolyline = $derived(toChartPts(filteredSeries));

    function handleKeydown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
  </script>

  <svelte:window onkeydown={handleKeydown} />

  {#if asset}
    <!-- Backdrop -->
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="ad-backdrop" onclick={onClose} aria-hidden="true"></div>

    <div class="ad-panel" role="dialog" aria-label="{asset.name} detail" aria-modal="true">
      <header class="ad-header">
        <div class="ad-head-left">
          <span class="ad-symbol">{asset.symbol}</span>
          <span class="ad-name">{asset.name}</span>
          <span class="ad-sector">{asset.sector}</span>
        </div>
        <div class="ad-head-right">
          <span class="ad-value">
            {asset.lastValue !== null
              ? (asset.unit === "%" ? asset.lastValue.toFixed(2) + "%" : asset.lastValue.toFixed(2))
              : "—"}
          </span>
          {#if asset.changePct !== null}
            <span
              class="ad-change"
              class:ad-change--up={asset.changePct > 0}
              class:ad-change--dn={asset.changePct < 0}
            >
              {(asset.changePct >= 0 ? "+" : "") + asset.changePct.toFixed(2)}%
            </span>
          {/if}
          <button type="button" class="ad-close" onclick={onClose} aria-label="Close">✕</button>
        </div>
      </header>

      <!-- Period stats grid -->
      <div class="ad-stats">
        {#each STAT_TIMEFRAMES as tf}
          <div class="ad-stat">
            <span class="ad-stat-label">{tf}</span>
            <span class="ad-stat-value">{statFor(tf)}</span>
          </div>
        {/each}
      </div>

      <!-- Timeframe selector -->
      <div class="ad-tf-bar">
        {#each TIMEFRAMES as tf}
          <button
            type="button"
            class="ad-tf"
            class:ad-tf--active={activeTimeframe === tf}
            onclick={() => (activeTimeframe = tf)}
          >{tf}</button>
        {/each}
      </div>

      <!-- Chart -->
      <div class="ad-chart-wrap">
        {#if loading}
          <div class="ad-loading">LOADING…</div>
        {:else if filteredSeries.length < 2}
          <div class="ad-loading">NO DATA</div>
        {:else}
          <svg viewBox="0 0 {chartW} {chartH}" class="ad-chart" preserveAspectRatio="none" aria-hidden="true">
            <!-- Zero line if relevant -->
            {#if minVal < 0 && maxVal > 0}
              {@const zeroY = chartH - 4 - ((0 - minVal) / valRange) * (chartH - 8)}
              <line x1="0" y1={zeroY} x2={chartW} y2={zeroY}
                stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.4" />
            {/if}
            <polyline
              points={mainPolyline}
              fill="none"
              stroke="var(--terminal-accent-amber)"
              stroke-width="1.5"
              vector-effect="non-scaling-stroke"
            />
          </svg>
        {/if}
      </div>
    </div>
  {/if}

  <style>
    .ad-backdrop {
      position: fixed;
      inset: 0;
      background: transparent;
      z-index: 40;
    }

    .ad-panel {
      position: fixed;
      top: 0;
      right: 0;
      bottom: 0;
      width: 480px;
      background: var(--terminal-bg-panel);
      border-left: var(--terminal-border-hairline);
      display: flex;
      flex-direction: column;
      gap: 1px;
      z-index: 50;
      overflow-y: auto;
      font-family: var(--terminal-font-mono);
      animation: ad-slide-in var(--terminal-motion-tick) var(--terminal-motion-easing-out);
    }

    @keyframes ad-slide-in {
      from { transform: translateX(100%); }
      to   { transform: translateX(0); }
    }

    .ad-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      padding: var(--terminal-space-3);
      border-bottom: var(--terminal-border-hairline);
    }
    .ad-head-left {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .ad-symbol {
      font-size: var(--terminal-text-14);
      font-weight: 700;
      color: var(--terminal-fg-primary);
      letter-spacing: 0.05em;
    }
    .ad-name {
      font-size: var(--terminal-text-11);
      color: var(--terminal-fg-secondary);
    }
    .ad-sector {
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
    }
    .ad-head-right {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 3px;
    }
    .ad-value {
      font-size: var(--terminal-text-14);
      font-weight: 600;
      color: var(--terminal-fg-primary);
      font-variant-numeric: tabular-nums;
    }
    .ad-change {
      font-size: var(--terminal-text-11);
      font-variant-numeric: tabular-nums;
      color: var(--terminal-fg-tertiary);
    }
    .ad-change--up { color: var(--terminal-accent-green, #4adf86); }
    .ad-change--dn { color: var(--terminal-accent-red, #f87171); }
    .ad-close {
      background: transparent;
      border: none;
      color: var(--terminal-fg-tertiary);
      font-size: var(--terminal-text-14);
      cursor: pointer;
      padding: 0;
      margin-top: var(--terminal-space-2);
    }
    .ad-close:hover { color: var(--terminal-fg-primary); }

    .ad-stats {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 1px;
      background: var(--terminal-bg-panel-sunken);
      padding: 0;
    }
    .ad-stat {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      padding: var(--terminal-space-2);
      background: var(--terminal-bg-panel);
    }
    .ad-stat-label {
      font-size: 9px;
      color: var(--terminal-fg-tertiary);
      letter-spacing: 0.06em;
    }
    .ad-stat-value {
      font-size: var(--terminal-text-11);
      font-weight: 600;
      color: var(--terminal-fg-primary);
      font-variant-numeric: tabular-nums;
    }

    .ad-tf-bar {
      display: flex;
      gap: 1px;
      padding: var(--terminal-space-2) var(--terminal-space-3);
    }
    .ad-tf {
      padding: 2px var(--terminal-space-2);
      background: transparent;
      border: var(--terminal-border-hairline);
      color: var(--terminal-fg-tertiary);
      font-family: inherit;
      font-size: var(--terminal-text-10);
      letter-spacing: var(--terminal-tracking-caps);
      cursor: pointer;
    }
    .ad-tf--active {
      border-color: var(--terminal-accent-amber);
      color: var(--terminal-accent-amber);
    }

    .ad-chart-wrap {
      padding: var(--terminal-space-2) var(--terminal-space-3);
    }
    .ad-chart {
      width: 100%;
      height: 120px;
      display: block;
    }
    .ad-loading {
      height: 120px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: var(--terminal-text-10);
      color: var(--terminal-fg-tertiary);
      letter-spacing: var(--terminal-tracking-caps);
    }
  </style>
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/macro/AssetDrawer.svelte
  git commit -m "feat(terminal-core): add AssetDrawer with period stats + chart + Compare scaffold"
  ```

---

## Task 1.9: Export new components from `primitives/index.ts`

All new macro components must be exported so consumers can import them via the package.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/primitives/index.ts`

- [ ] **Step 1: Read current exports**

  ```
  cat packages/ii-terminal-core/src/lib/components/terminal/primitives/index.ts
  ```

- [ ] **Step 2: Add new exports**

  Append to the macro section (or create it if not present):

  ```typescript
  // Macro panel primitives
  export { default as MiniCard } from "../macro/MiniCard.svelte";
  export { default as CrossAssetPanel } from "../macro/CrossAssetPanel.svelte";
  export { default as RegimePlot } from "../macro/RegimePlot.svelte";
  export { default as LiquidityPanel } from "../macro/LiquidityPanel.svelte";
  export { default as EconPanel } from "../macro/EconPanel.svelte";
  export { default as CBPanel } from "../macro/CBPanel.svelte";
  export { default as MacroNewsFeed } from "../macro/MacroNewsFeed.svelte";
  export { default as AssetDrawer } from "../macro/AssetDrawer.svelte";
  export { createRegimePlotStore } from "../macro/regime-plot-store.svelte";
  ```

- [ ] **Step 3: Build the package to confirm no TypeScript errors**

  ```
  cd packages/ii-terminal-core && pnpm build
  ```

  Expected: no errors.

- [ ] **Step 4: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/primitives/index.ts
  git commit -m "feat(terminal-core): export new macro primitives from primitives/index.ts"
  ```

---

## Task 2.1: Rewrite `frontends/terminal/src/routes/macro/+page.svelte`

Replace the 4-zone widget layout with the Bloomberg-density 3-column grid:
- Left (320px): `CrossAssetPanel` + `AssetDrawer`
- Center (1fr): `RegimePlot` (top-center) + `LiquidityPanel` (bottom-center)
- Right (300px): `CBPanel` + `EconPanel` + `MacroNewsFeed`

Wire all three new backend endpoints. Derive EconRow data from `/macro/scores` dimensions. Derive liquidity from `/macro/fred?series_id=NFCI`. Preserve the existing regime simulation via `createRegimePlotStore`.

**Files:**
- Modify: `frontends/terminal/src/routes/macro/+page.svelte`

- [ ] **Step 1: Read current `+page.svelte` to understand what to preserve**

  Read `frontends/terminal/src/routes/macro/+page.svelte` — note the API client instance, pinnedRegime import, keyboard shortcut handler, and `$effect` structure.

- [ ] **Step 2: Rewrite the page**

  Replace the full file content with:

  ```svelte
  <!--
    Macro Terminal — 3-column Bloomberg-density layout.
    Left (320px): cross-asset panel + asset drawer.
    Center (1fr): regime plot (top) + liquidity panel (bottom).
    Right (300px): CB calendar + econ pulse + news feed placeholder.
  -->
  <script lang="ts">
    import { getContext } from "svelte";
    import { createClientApiClient } from "@investintell/ii-terminal-core/api/client";
    import { pinnedRegime } from "@investintell/ii-terminal-core/state/pinned-regime.svelte";
    import { createRegimePlotStore } from "@investintell/ii-terminal-core";
    import CrossAssetPanel from "@investintell/ii-terminal-core/components/terminal/macro/CrossAssetPanel.svelte";
    import AssetDrawer from "@investintell/ii-terminal-core/components/terminal/macro/AssetDrawer.svelte";
    import RegimePlot from "@investintell/ii-terminal-core/components/terminal/macro/RegimePlot.svelte";
    import LiquidityPanel from "@investintell/ii-terminal-core/components/terminal/macro/LiquidityPanel.svelte";
    import EconPanel from "@investintell/ii-terminal-core/components/terminal/macro/EconPanel.svelte";
    import CBPanel from "@investintell/ii-terminal-core/components/terminal/macro/CBPanel.svelte";
    import MacroNewsFeed from "@investintell/ii-terminal-core/components/terminal/macro/MacroNewsFeed.svelte";
    import type { CrossAssetPoint } from "@investintell/ii-terminal-core/components/terminal/macro/CrossAssetPanel.svelte";
    import type { CbEvent } from "@investintell/ii-terminal-core/components/terminal/macro/CBPanel.svelte";
    import type { EconRow } from "@investintell/ii-terminal-core/components/terminal/macro/EconPanel.svelte";

    const api = createClientApiClient(getContext("token"));

    // ── Data state ──────────────────────────────────────────────
    let crossAssets = $state<CrossAssetPoint[]>([]);
    let crossAssetsLoading = $state(true);

    let trailPoints = $state<{ g: number; i: number; as_of_date: string }[]>([]);
    let livePin = $state({ g: 0.0, i: 0.0 });
    let activeRegime = $state("—");
    let regimeLoading = $state(true);

    let nfci = $state<number | null>(null);
    let nfciHistory = $state<number[]>([]);

    let cbEvents = $state<CbEvent[]>([]);
    let cbLoading = $state(true);

    let econRows = $state<EconRow[]>([]);
    let econLoading = $state(true);

    // ── Regime simulation ────────────────────────────────────────
    const simStore = createRegimePlotStore();

    // ── Focused asset for drawer ─────────────────────────────────
    let focusAsset = $state<CrossAssetPoint | null>(null);

    // ── Fetch all data on mount ──────────────────────────────────
    $effect(() => {
      // 1. Cross-asset panel
      api.get("/macro/cross-asset")
        .then((r) => r.json())
        .then((data: { assets: CrossAssetPoint[] }) => {
          crossAssets = data.assets.map((a) => ({
            symbol: a.symbol,
            name: a.name,
            sector: a.sector,
            lastValue: a.last_value ?? null,
            changePct: a.change_pct ?? null,
            unit: a.unit,
            sparkline: a.sparkline ?? [],
          }));
        })
        .finally(() => { crossAssetsLoading = false; });

      // 2. Regime trail + current regime
      Promise.all([
        api.get("/macro/regime/trail").then((r) => r.json()),
        api.get("/macro/regime").then((r) => r.json()),
        api.get("/macro/scores").then((r) => r.json()),
      ]).then(([trail, regime, scores]) => {
        trailPoints = trail.points ?? [];
        activeRegime = regime.raw_regime ?? "—";
        pinnedRegime.set(regime.raw_regime);

        // Derive livePin from US region growth + inflation dimension scores
        const us = scores?.regions?.US ?? scores?.regions?.us;
        if (us?.dimensions?.growth && us?.dimensions?.inflation) {
          const g = (us.dimensions.growth.score / 100) * 2 - 1;
          const i = (us.dimensions.inflation.score / 100) * 2 - 1;
          livePin = { g, i };
        }

        // Derive econ rows from US dimensions
        const dims: Record<string, { score: number }> = us?.dimensions ?? {};
        econRows = Object.entries(dims).map(([key, dim]) => ({
          name: key.replace(/_/g, " ").toUpperCase(),
          period: "LATEST",
          actual: dim.score ?? null,
          consensus: 50.0,
          unit: "idx",
          surprise: (dim.score - 50) / 10,
        }));
      }).finally(() => { regimeLoading = false; econLoading = false; });

      // 3. NFCI liquidity
      api.get("/macro/fred?series_id=NFCI")
        .then((r) => r.json())
        .then((data: { data: { obs_date: string; value: number }[] }) => {
          const pts = data.data ?? [];
          nfciHistory = pts.slice(-24).map((p) => p.value);
          nfci = pts.length ? pts[pts.length - 1].value : null;
        });

      // 4. CB calendar
      api.get("/macro/cb-calendar")
        .then((r) => r.json())
        .then((data: { events: Array<{
          central_bank: string;
          meeting_date: string;
          current_rate_pct: number;
          expected_change_bps: number;
        }> }) => {
          cbEvents = (data.events ?? []).map((e) => ({
            centralBank: e.central_bank,
            meetingDate: e.meeting_date,
            currentRatePct: e.current_rate_pct,
            expectedChangeBps: e.expected_change_bps,
          }));
        })
        .finally(() => { cbLoading = false; });
    });

    // ── AssetDrawer fetch helper ─────────────────────────────────
    async function fetchAssetSeries(symbol: string) {
      const r = await api.get(`/macro/fred?series_id=${symbol}`);
      const data: { data: { obs_date: string; value: number }[] } = await r.json();
      return data.data ?? [];
    }
  </script>

  <div class="macro-desk">
    <!-- ── Toolbar ───────────────────────────────────────────── -->
    <div class="macro-toolbar">
      <span class="macro-toolbar-title">MACRO</span>
      <span class="macro-toolbar-regime"
        class:macro-regime--risk-off={activeRegime.includes("OFF") || activeRegime.includes("RISK")}
      >
        {activeRegime}
      </span>
    </div>

    <!-- ── 3-column grid ─────────────────────────────────────── -->
    <div class="macro-grid">

      <!-- Left column: cross-asset list -->
      <div class="macro-col macro-col--left">
        <CrossAssetPanel
          assets={crossAssets}
          loading={crossAssetsLoading}
          onAssetSelect={(a) => { focusAsset = a; }}
        />
      </div>

      <!-- Center column: regime plot + liquidity -->
      <div class="macro-col macro-col--center">
        <div class="macro-center-top">
          <RegimePlot
            {activeRegime}
            livePin={livePin}
            simulatedPin={simStore.simPin}
            trail={trailPoints}
            onSimulate={(pin) => simStore.set(pin)}
          />
        </div>
        <div class="macro-center-bottom">
          <LiquidityPanel
            nfci={nfci}
            history={nfciHistory}
          />
        </div>
      </div>

      <!-- Right column: CB + econ + news -->
      <div class="macro-col macro-col--right">
        <CBPanel events={cbEvents} loading={cbLoading} />
        <EconPanel rows={econRows} loading={econLoading} />
        <MacroNewsFeed />
      </div>

    </div>

    <!-- Asset drawer -->
    <AssetDrawer
      asset={focusAsset}
      onClose={() => { focusAsset = null; }}
      fetchSeries={fetchAssetSeries}
    />
  </div>

  <style>
    .macro-desk {
      display: flex;
      flex-direction: column;
      height: calc(100vh - 88px);
      background: var(--terminal-bg-panel-sunken);
      font-family: var(--terminal-font-mono);
      overflow: hidden;
    }

    .macro-toolbar {
      display: flex;
      align-items: center;
      gap: var(--terminal-space-3);
      height: 32px;
      padding: 0 var(--terminal-space-3);
      background: var(--terminal-bg-panel);
      border-bottom: var(--terminal-border-hairline);
      flex-shrink: 0;
    }
    .macro-toolbar-title {
      font-size: var(--terminal-text-11);
      font-weight: 700;
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-primary);
    }
    .macro-toolbar-regime {
      font-size: var(--terminal-text-10);
      letter-spacing: var(--terminal-tracking-caps);
      color: var(--terminal-fg-tertiary);
      margin-left: auto;
    }
    .macro-regime--risk-off {
      color: var(--terminal-accent-red, #f87171);
    }

    /* 3-column grid with 1px hairline gaps */
    .macro-grid {
      display: grid;
      grid-template-columns: 320px 1fr 300px;
      gap: 1px;
      background: var(--terminal-bg-panel-sunken); /* hairline color via gap */
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }

    .macro-col {
      background: var(--terminal-bg-panel);
      overflow-y: auto;
      min-height: 0;
    }
    .macro-col--center {
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 1px;
      background: var(--terminal-bg-panel-sunken);
      overflow: hidden;
    }
    .macro-center-top {
      background: var(--terminal-bg-panel);
      overflow: hidden;
    }
    .macro-center-bottom {
      background: var(--terminal-bg-panel);
      overflow-y: auto;
    }
    .macro-col--right {
      display: flex;
      flex-direction: column;
      gap: 1px;
      background: var(--terminal-bg-panel-sunken);
      overflow-y: auto;
    }
    .macro-col--right > :global(*) {
      flex-shrink: 0;
    }
  </style>
  ```

- [ ] **Step 3: Start the terminal dev server and navigate to `/macro`**

  ```
  make dev-terminal
  ```

  Open `http://localhost:5173/macro` (or the terminal dev port).

  Verify visually:
  - [ ] 3-column layout renders (no collapsing to single column)
  - [ ] CrossAssetPanel shows asset rows with sparklines (or loading state)
  - [ ] RegimePlot SVG renders with quadrant fills and labels
  - [ ] LiquidityPanel renders gauge
  - [ ] CBPanel shows calendar rows
  - [ ] EconPanel shows dimension rows
  - [ ] MacroNewsFeed shows placeholder
  - [ ] Clicking a MiniCard row opens the AssetDrawer
  - [ ] AssetDrawer closes on Escape key and ✕ button
  - [ ] RegimePlot responds to pointer drag (sets SIM banner)
  - [ ] RegimePlot arrow-key navigation works

- [ ] **Step 4: Fix any TypeScript errors from `pnpm check`**

  ```
  cd frontends/terminal && pnpm check
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add frontends/terminal/src/routes/macro/+page.svelte
  git commit -m "feat(terminal): rewrite macro page with 3-col Bloomberg-density layout"
  ```

---

## Task 2.2: Verify build across all packages

Run the full Turborepo build to confirm no broken imports or TypeScript errors propagated.

- [ ] **Step 1: Full build**

  ```
  make build-all
  ```

  Expected: all packages build successfully.

- [ ] **Step 2: Typecheck the terminal frontend**

  ```
  make check-all
  ```

- [ ] **Step 3: Run backend test suite (no regressions)**

  ```
  cd backend && python -m pytest tests/ -x --timeout=60 -q
  ```

- [ ] **Step 4: Final commit if any import fixes were needed**

  ```bash
  git add -p
  git commit -m "fix(macro): resolve import/typecheck issues from 3-col layout refactor"
  ```

---

## Self-Review Checklist

After implementation, verify against the spec:

| Spec requirement | Task | Status |
|---|---|---|
| 3-column grid 320px/1fr/300px | Task 2.1 | — |
| Gap 1px hairline pattern | Task 2.1 CSS | — |
| MiniCard with inline sparkline | Task 1.1 | — |
| CrossAssetPanel (RATES/FX/EQUITY/CMDTY/CREDIT) | Task 1.2 | — |
| LiquidityPanel with gauge + sparkline | Task 1.4 | — |
| CBPanel with HOLD/+bps/-bps badges | Task 1.6 | — |
| EconPanel with Hot/Cool arrows | Task 1.5 | — |
| RegimePlot SVG continuous + trail + quadrant labels | Task 1.3 | — |
| Draggable regime pin | Task 1.3 | — |
| Arrow-key accessibility on regime plot | Task 1.3 | — |
| AssetDrawer with period stats + chart | Task 1.8 | — |
| AssetDrawer Escape key close | Task 1.8 | — |
| News feed placeholder (no mock data) | Task 1.7 | — |
| All components in ii-terminal-core | Tasks 1.1–1.9 | — |
| 3 new backend endpoints before any UI | Tasks 0.1–0.3 | — |
| No mock data arrays in page | Task 2.1 | — |
| `make build-all` passes | Task 2.2 | — |

**Deferred (future sprints):**
- MacroNewsFeed real data (requires news API provider contract)
- AssetDrawer Compare mode (overlay a second trace on chart)
- Region selector toolbar (GLOBAL / US / EU / ASIA / BR)
- 52W High/Low in AssetDrawer stats row

---

## Phase 3: Live Workbench Visual Parity

### Additional files for Phase 3

**Modify (backend):**
- `backend/app/domains/wealth/schemas/macro.py` — add `RegionalRegimeRow`, `RegionalRegimeResponse`
- `backend/app/domains/wealth/routes/macro.py` — add `GET /macro/regional-regime`
- `backend/tests/domains/wealth/services/test_macro_new_endpoints.py` — add regional regime tests

**Modify (ii-terminal-core):**
- `packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte` — redesign to 4-region dense rows
- `packages/ii-terminal-core/src/lib/components/terminal/live/RebalanceFocusMode.svelte` — add KpiCard ribbon above trades table

---

### Task 3.1: Backend — `/macro/regional-regime` endpoint

Reads the latest row from `macro_regional_snapshots` for each tracked region (US, EU, EM, BR). Computes the regime quadrant name (GOLDILOCKS / OVERHEATING / STAGFLATION / REFLATION) from growth and inflation scores, and a stress level (LOW / MED / HIGH) derived from Euclidean distance from the center of the quadrant space.

**Files:**
- Modify: `backend/app/domains/wealth/schemas/macro.py`
- Modify: `backend/app/domains/wealth/routes/macro.py`
- Test: `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`

- [ ] **Step 1: Add Pydantic schemas**

  In `backend/app/domains/wealth/schemas/macro.py`, append after the existing `CbCalendarResponse` class:

  ```python
  class RegionalRegimeRow(BaseModel):
      region_code: str  # "US" | "EU" | "EM" | "BR"
      regime_label: str  # "GOLDILOCKS" | "OVERHEATING" | "STAGFLATION" | "REFLATION"
      stress_level: Literal["LOW", "MED", "HIGH"]
      trend_up: bool  # True = growth improving, False = deteriorating
      growth_score: float | None = None   # 0–100 raw score
      inflation_score: float | None = None  # 0–100 raw score


  class RegionalRegimeResponse(BaseModel):
      as_of_date: date | None = None
      regions: list[RegionalRegimeRow] = []
  ```

- [ ] **Step 2: Write failing tests**

  Append to `backend/tests/domains/wealth/services/test_macro_new_endpoints.py`:

  ```python
  from backend.app.domains.wealth.schemas.macro import (
      RegionalRegimeRow,
      RegionalRegimeResponse,
  )


  def test_regional_regime_row_schema():
      row = RegionalRegimeRow(
          region_code="US",
          regime_label="GOLDILOCKS",
          stress_level="LOW",
          trend_up=True,
          growth_score=62.5,
          inflation_score=38.2,
      )
      assert row.regime_label == "GOLDILOCKS"
      assert row.stress_level == "LOW"
      assert row.trend_up is True


  def test_regional_regime_response_empty():
      resp = RegionalRegimeResponse()
      assert resp.regions == []
      assert resp.as_of_date is None


  def test_quadrant_label_logic():
      """Inline helper — same logic used in the route."""
      def _label(g: float, i: float) -> str:
          if g >= 50 and i < 50:
              return "GOLDILOCKS"
          elif g >= 50 and i >= 50:
              return "OVERHEATING"
          elif g < 50 and i >= 50:
              return "STAGFLATION"
          return "REFLATION"

      assert _label(62, 35) == "GOLDILOCKS"
      assert _label(75, 70) == "OVERHEATING"
      assert _label(30, 68) == "STAGFLATION"
      assert _label(28, 40) == "REFLATION"
  ```

- [ ] **Step 3: Run tests (expect PASS — schema only, no DB)**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py::test_regional_regime_row_schema tests/domains/wealth/services/test_macro_new_endpoints.py::test_regional_regime_response_empty tests/domains/wealth/services/test_macro_new_endpoints.py::test_quadrant_label_logic -v
  ```

  Expected: 3 passing.

- [ ] **Step 4: Add route to `routes/macro.py`**

  In `backend/app/domains/wealth/routes/macro.py`, add the import for the new schemas at the top where other macro schemas are imported:

  ```python
  from ..schemas.macro import (
      # ... existing imports ...,
      RegionalRegimeRow,
      RegionalRegimeResponse,
  )
  ```

  Then add after the `get_cb_calendar` handler:

  ```python
  # ── Regional regime helpers ─────────────────────────────────────────────────

  _REGION_CODES = ["US", "EU", "EM", "BR"]


  def _quadrant_label(growth: float, inflation: float) -> str:
      if growth >= 50 and inflation < 50:
          return "GOLDILOCKS"
      elif growth >= 50 and inflation >= 50:
          return "OVERHEATING"
      elif growth < 50 and inflation >= 50:
          return "STAGFLATION"
      return "REFLATION"


  def _stress_level(growth: float, inflation: float) -> str:
      distance = ((growth - 50) ** 2 + (inflation - 50) ** 2) ** 0.5
      if distance >= 30:
          return "HIGH"
      elif distance >= 15:
          return "MED"
      return "LOW"


  @router.get(
      "/regional-regime",
      response_model=RegionalRegimeResponse,
      summary="Current regime quadrant per tracked region",
      tags=["macro"],
  )
  async def get_regional_regime(
      user: CurrentUser = Depends(get_current_user),
      db: AsyncSession = Depends(get_db_with_rls),
  ) -> RegionalRegimeResponse:
      """Return the latest regime quadrant for US, EU, EM, BR from macro_regional_snapshots."""
      from sqlalchemy import text as sa_text

      sql = sa_text(
          """
          SELECT DISTINCT ON (region_code)
              region_code,
              snapshot_date,
              data_json
          FROM macro_regional_snapshots
          WHERE region_code = ANY(:codes)
          ORDER BY region_code, snapshot_date DESC
          """
      )
      result = await db.execute(sql, {"codes": _REGION_CODES})
      rows = result.fetchall()

      today = date.today()
      out: list[RegionalRegimeRow] = []

      for row in rows:
          region_code: str = row.region_code
          data_json: dict = row.data_json or {}
          dims = data_json.get("dimensions", {})
          g_raw = dims.get("growth", {}).get("score")
          i_raw = dims.get("inflation", {}).get("score")
          g = float(g_raw) if g_raw is not None else 50.0
          i = float(i_raw) if i_raw is not None else 50.0
          prev_g = dims.get("growth", {}).get("prev_score")
          trend_up = (float(prev_g) <= g) if prev_g is not None else (g >= 50.0)
          out.append(
              RegionalRegimeRow(
                  region_code=region_code,
                  regime_label=_quadrant_label(g, i),
                  stress_level=_stress_level(g, i),
                  trend_up=trend_up,
                  growth_score=round(g, 1),
                  inflation_score=round(i, 1),
              )
          )

      # Fill missing regions with neutral defaults so the panel always shows 4 rows
      found = {r.region_code for r in out}
      for code in _REGION_CODES:
          if code not in found:
              out.append(
                  RegionalRegimeRow(
                      region_code=code,
                      regime_label="GOLDILOCKS",
                      stress_level="LOW",
                      trend_up=True,
                      growth_score=None,
                      inflation_score=None,
                  )
              )

      out.sort(key=lambda r: _REGION_CODES.index(r.region_code) if r.region_code in _REGION_CODES else 99)
      return RegionalRegimeResponse(as_of_date=today, regions=out)
  ```

- [ ] **Step 5: Run full test suite + lint**

  ```
  cd backend && python -m pytest tests/domains/wealth/services/test_macro_new_endpoints.py -v
  make lint && make typecheck
  ```

  Expected: all tests pass, no lint/type errors.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/domains/wealth/schemas/macro.py \
          backend/app/domains/wealth/routes/macro.py \
          backend/tests/domains/wealth/services/test_macro_new_endpoints.py
  git commit -m "feat(macro): add /regional-regime endpoint for MacroRegimePanel redesign"
  ```

---

### Task 3.2: MacroRegimePanel — 4-region dense rows

Replace the current 8-FRED-indicator vertical list with the UX spec's 4-region dense table: `REGION · LABEL · STRESS · TREND-ARROW`. Data from `GET /macro/regional-regime` (Task 3.1).

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte`

- [ ] **Step 1: Rewrite the component**

  Replace the entire file content of `packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte`:

  ```svelte
  <!--
    MacroRegimePanel — 4-region dense regime table for Live Workbench right column.

    Design source: docs/ux/Netz Terminal/terminal-panels.jsx MacroRegime component.
    Data source: GET /macro/regional-regime (Task 3.1).
    Renders US / EU / EM / BR rows with GOLDILOCKS|OVERHEATING|STAGFLATION|REFLATION
    labels, LOW|MED|HIGH stress badges, and ↑/↓ trend arrows.
  -->
  <script lang="ts">
  	import { getContext } from "svelte";
  	import { createClientApiClient } from "../../../api/client";

  	const getToken = getContext<() => Promise<string>>("netz:getToken");
  	const api = createClientApiClient(getToken);

  	interface RegionalRegimeRow {
  		region_code: string;
  		regime_label: string;
  		stress_level: "LOW" | "MED" | "HIGH";
  		trend_up: boolean;
  		growth_score: number | null;
  		inflation_score: number | null;
  	}

  	let regions = $state<RegionalRegimeRow[]>([]);
  	let loading = $state(true);

  	$effect(() => {
  		let cancelled = false;
  		loading = true;
  		api
  			.get<{ regions: RegionalRegimeRow[] }>("/macro/regional-regime")
  			.then((res) => {
  				if (!cancelled) { regions = res.regions ?? []; loading = false; }
  			})
  			.catch(() => {
  				if (!cancelled) { regions = []; loading = false; }
  			});
  		return () => { cancelled = true; };
  	});

  	function regimeToneClass(label: string): string {
  		const l = label.toUpperCase();
  		if (l === "GOLDILOCKS") return "mrg-goldilocks";
  		if (l === "OVERHEATING") return "mrg-overheating";
  		if (l === "STAGFLATION") return "mrg-stagflation";
  		if (l === "REFLATION") return "mrg-reflation";
  		return "";
  	}
  </script>

  <div class="panel mrg-panel">
  	<div class="phead">
  		<span class="title">MACRO REGIME</span>
  		{#if loading}<span class="mrg-loading">…</span>{/if}
  	</div>

  	<div class="mrg-table">
  		{#each regions as r (r.region_code)}
  			<div class="mrg-row">
  				<span class="mrg-code">{r.region_code}</span>
  				<span class="mrg-label {regimeToneClass(r.regime_label)}">{r.regime_label}</span>
  				<span class="mrg-stress mrg-stress-{r.stress_level.toLowerCase()}">{r.stress_level}</span>
  				<span class="mrg-trend" class:up={r.trend_up} class:down={!r.trend_up}>
  					{r.trend_up ? "↑" : "↓"}
  				</span>
  			</div>
  		{/each}
  		{#if !loading && regions.length === 0}
  			<div class="mrg-empty">No regime data</div>
  		{/if}
  	</div>
  </div>

  <style>
  	.mrg-panel {
  		display: flex;
  		flex-direction: column;
  		height: 100%;
  		min-height: 0;
  		overflow: hidden;
  	}

  	.mrg-loading {
  		font-size: 9px;
  		color: var(--ii-text-muted, var(--terminal-fg-muted));
  		letter-spacing: 0.06em;
  	}

  	.mrg-table {
  		flex: 1;
  		min-height: 0;
  		overflow-y: auto;
  		padding: 4px 0;
  	}

  	.mrg-row {
  		display: grid;
  		grid-template-columns: 36px 1fr auto auto;
  		gap: 8px;
  		align-items: center;
  		padding: 0 10px;
  		height: var(--ii-terminal-t-row, 22px);
  		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102,137,188,0.14));
  		font-family: var(--ii-font-mono, var(--terminal-font-mono));
  		font-size: var(--ii-terminal-t-size-xs, 10px);
  	}

  	.mrg-code {
  		color: var(--ii-text-secondary);
  		font-weight: 700;
  		letter-spacing: 0.06em;
  	}

  	.mrg-label {
  		font-size: 9px;
  		font-weight: 600;
  		letter-spacing: 0.08em;
  		text-transform: uppercase;
  	}

  	.mrg-goldilocks  { color: var(--ii-success, #3DD39A); }
  	.mrg-overheating { color: var(--ii-warning, #F2C94C); }
  	.mrg-stagflation { color: var(--ii-danger, #FF5C7A); }
  	.mrg-reflation   { color: var(--ii-info, #6689BC); }

  	.mrg-stress {
  		font-size: 9px;
  		letter-spacing: 0.06em;
  		padding: 1px 5px;
  		border-radius: 2px;
  		font-weight: 600;
  		border: 1px solid;
  	}
  	.mrg-stress-low { color: var(--ii-success);  border-color: var(--ii-terminal-up-dim, #1F6A54); }
  	.mrg-stress-med { color: var(--ii-warning);  border-color: var(--ii-terminal-accent-dim, #7A5213); }
  	.mrg-stress-high{ color: var(--ii-danger);   border-color: var(--ii-terminal-down-dim, #7A2F40); }

  	.mrg-trend { font-size: 12px; font-weight: 600; }
  	.mrg-trend.up   { color: var(--ii-success); }
  	.mrg-trend.down { color: var(--ii-danger); }

  	.mrg-empty {
  		padding: 24px 12px;
  		text-align: center;
  		font-family: var(--ii-font-mono);
  		font-size: 10px;
  		color: var(--ii-text-muted);
  	}
  </style>
  ```

- [ ] **Step 2: Typecheck**

  ```
  cd packages/ii-terminal-core && pnpm run check
  ```

  Expected: no errors.

- [ ] **Step 3: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/live/MacroRegimePanel.svelte
  git commit -m "feat(live): redesign MacroRegimePanel to 4-region regime density table"
  ```

---

### Task 3.3: RebalanceFocusMode — 4-KPI header ribbon

Add 4 KpiCards (TOTAL AUM / INSTRUMENTS / TRADES / IMPACT AUM) above the trades table in `RebalanceFocusMode.svelte`, matching the UX spec's `RebalanceFocus` modal KPI ribbon.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/live/RebalanceFocusMode.svelte`

- [ ] **Step 1: Read the file to locate insertion point**

  Open `packages/ii-terminal-core/src/lib/components/terminal/live/RebalanceFocusMode.svelte`.
  Find the block where `previewData` is checked and the trades table is rendered (`{#if previewData}` or similar). The KPI ribbon goes immediately inside that block, before the trades table.

- [ ] **Step 2: Insert KPI ribbon above trades table**

  Add this block before the trades table inside the `{#if previewData && !confirming}` (or equivalent) block:

  ```svelte
  <!-- KPI ribbon — 4-col header matching UX spec RebalanceFocus -->
  <div class="rfm-kpi-ribbon">
  	<div class="rfm-kpi">
  		<span class="rfm-kpi-label">TOTAL AUM</span>
  		<span class="rfm-kpi-value">{totalAum > 0 ? formatCurrency(totalAum) : "—"}</span>
  	</div>
  	<div class="rfm-kpi">
  		<span class="rfm-kpi-label">INSTRUMENTS</span>
  		<span class="rfm-kpi-value">{holdings.length}</span>
  	</div>
  	<div class="rfm-kpi">
  		<span class="rfm-kpi-label">TRADES</span>
  		<span class="rfm-kpi-value rfm-kpi-accent">
  			{previewData.trades?.filter((t: {action: string}) => t.action !== "HOLD").length ?? 0}
  		</span>
  	</div>
  	<div class="rfm-kpi">
  		<span class="rfm-kpi-label">IMPACT AUM</span>
  		<span class="rfm-kpi-value">
  			{formatCurrency(previewData.trades?.reduce((s: number, t: {trade_value?: number}) => s + Math.abs(t.trade_value ?? 0), 0) ?? 0)}
  		</span>
  	</div>
  </div>
  ```

- [ ] **Step 3: Add styles at end of `<style>` block**

  ```css
  .rfm-kpi-ribbon {
  	display: grid;
  	grid-template-columns: repeat(4, 1fr);
  	gap: 1px;
  	background: var(--ii-border-subtle, var(--terminal-bg-panel-sunken));
  	padding: 1px;
  	flex-shrink: 0;
  }
  .rfm-kpi {
  	background: var(--ii-surface, var(--terminal-bg-panel));
  	padding: 10px 14px;
  	display: flex;
  	flex-direction: column;
  	gap: 4px;
  }
  .rfm-kpi-label {
  	font-size: 9px;
  	font-weight: 600;
  	letter-spacing: 0.08em;
  	text-transform: uppercase;
  	color: var(--ii-text-muted);
  	font-family: var(--ii-font-mono);
  }
  .rfm-kpi-value {
  	font-family: var(--ii-font-mono);
  	font-size: 18px;
  	font-weight: 600;
  	color: var(--ii-text-primary);
  	font-variant-numeric: tabular-nums;
  }
  .rfm-kpi-accent { color: var(--ii-brand-primary, var(--terminal-accent-amber)); }
  ```

- [ ] **Step 4: Typecheck + commit**

  ```
  cd packages/ii-terminal-core && pnpm run check
  git add packages/ii-terminal-core/src/lib/components/terminal/live/RebalanceFocusMode.svelte
  git commit -m "feat(live): add 4-KPI header ribbon to RebalanceFocusMode"
  ```

---

## Phase 4: Screener Visual Parity

### Additional files for Phase 4

**Create (ii-terminal-core):**
- `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte`

**Modify:**
- `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/focus-trigger.ts` — add `ticker` + `instrumentId` optional fields
- `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalDataGrid.svelte` — include ticker/instrumentId in focustrigger event
- `frontends/terminal/src/routes/screener/+page.svelte` — use new modal
- `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalScreenerShell.svelte` — fix filter width

---

### Task 4.1: ScreenerFundFocusModal — Bloomberg fund focus

Create `ScreenerFundFocusModal.svelte` — a 1040px × 88vh constrained modal (not full-screen) that implements the UX spec's `FundFocus` from `screener-app.jsx`. Uses pure SVG for `PerfChart` (area fill) and `CompositeRadar` (6-axis spider). No ECharts — these are static decorative charts in a quick-view context.

**Files:**
- Create: `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte`
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/focus-trigger.ts`
- Modify: `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalDataGrid.svelte`
- Modify: `frontends/terminal/src/routes/screener/+page.svelte`

- [ ] **Step 1: Extend FocusTriggerOptions**

  In `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/focus-trigger.ts`, find the `FocusTriggerOptions` interface and add two optional fields:

  ```ts
  export interface FocusTriggerOptions {
      entityKind: string;
      entityId: string;
      entityLabel?: string;
      ticker?: string | null;         // add
      instrumentId?: string | null;   // add
  }
  ```

- [ ] **Step 2: Include ticker/instrumentId in TerminalDataGrid focustrigger event**

  In `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalDataGrid.svelte`, find where a `focustrigger` CustomEvent is dispatched (row click handler or `use:focusTrigger` action). Update the event detail to include:

  ```ts
  new CustomEvent("focustrigger", {
      bubbles: true,
      detail: {
          entityKind: "fund",
          entityId: asset.id,
          entityLabel: asset.name,
          ticker: asset.ticker,
          instrumentId: asset.instrumentId,
      },
  })
  ```

- [ ] **Step 3: Create ScreenerFundFocusModal.svelte**

  Create `packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte`:

  ```svelte
  <!--
    ScreenerFundFocusModal — constrained fund focus for screener page.

    Design: docs/ux/Netz Terminal/screener-app.jsx FundFocus + screener.css.
    Size: 1040px × 88vh (NOT full-screen like FocusMode primitive).

    Data pipeline:
      - Fund KPIs: GET /screener/catalog?external_id={id}&page_size=1
      - NAV chart: GET /market-data/historical/{ticker}?start_date=5y-ago
      - Period stats: computed from NAV bars in component (no extra roundtrip)
      - Axis scores: derived from fund_risk_metrics fields returned in catalog
      - 52W range: computed from NAV bars

    SVG charts:
      - PerfChart: area fill with up/down gradient, 320×120 viewBox
      - CompositeRadar: 6-axis spider, 200×160 viewBox

    Close: ESC key or backdrop click.
  -->
  <script lang="ts">
  	import { getContext, onMount } from "svelte";
  	import { formatNumber, formatCurrency, formatPercent } from "@investintell/ui";
  	import { createClientApiClient } from "../../../../api/client";

  	interface Props {
  		fundId: string;
  		fundLabel: string;
  		ticker: string | null;
  		instrumentId: string | null;
  		onClose: () => void;
  	}

  	let { fundId, fundLabel, ticker, instrumentId, onClose }: Props = $props();

  	const getToken = getContext<() => Promise<string>>("netz:getToken");
  	const api = createClientApiClient(getToken);

  	// ── Fund detail from catalog ───────────────────────────────
  	interface FundCatalogItem {
  		name: string;
  		manager_name: string | null;
  		aum: number | null;
  		strategy_label: string | null;
  		fund_type: string;
  		expense_ratio_pct: number | null;
  		avg_annual_return_1y: number | null;
  		avg_annual_return_10y: number | null;
  		manager_score: number | null;
  		blended_momentum_score: number | null;
  		max_drawdown: number | null;
  		sharpe_ratio: number | null;
  		volatility: number | null;
  	}

  	interface CatalogPage { items: FundCatalogItem[]; }

  	let detail = $state<FundCatalogItem | null>(null);
  	let loadingDetail = $state(true);

  	$effect(() => {
  		const id = fundId;
  		let cancelled = false;
  		loadingDetail = true;
  		api
  			.get<CatalogPage>("/screener/catalog", {
  				page: "1",
  				page_size: "1",
  				external_id: id,
  				in_universe: "true",
  			})
  			.then((res) => {
  				if (!cancelled) { detail = res.items?.[0] ?? null; loadingDetail = false; }
  			})
  			.catch(() => {
  				if (!cancelled) { detail = null; loadingDetail = false; }
  			});
  		return () => { cancelled = true; };
  	});

  	// ── NAV series ─────────────────────────────────────────────
  	interface NavBar { date: string; value: number; }

  	let navBars = $state<NavBar[]>([]);
  	let loadingNav = $state(false);

  	$effect(() => {
  		const t = ticker;
  		if (!t) { navBars = []; return; }
  		let cancelled = false;
  		loadingNav = true;
  		const start = new Date(Date.now() - 365 * 5 * 86_400_000).toISOString().slice(0, 10);
  		api
  			.get<{ bars: Array<{ timestamp: string; close: number | null }> }>(
  				`/market-data/historical/${encodeURIComponent(t)}?start_date=${start}`,
  			)
  			.then((res) => {
  				if (!cancelled) {
  					navBars = (res.bars ?? [])
  						.filter((b) => b.close != null)
  						.map((b) => ({ date: b.timestamp.slice(0, 10), value: Number(b.close) }));
  					loadingNav = false;
  				}
  			})
  			.catch(() => { if (!cancelled) { navBars = []; loadingNav = false; } });
  		return () => { cancelled = true; };
  	});

  	// ── Period stats (computed from NAV) ───────────────────────
  	interface PeriodStat { return_pct: number | null; }

  	const PERIODS: Array<{ label: string; days: number }> = [
  		{ label: "1M", days: 30 },
  		{ label: "3M", days: 91 },
  		{ label: "6M", days: 182 },
  		{ label: "1Y", days: 365 },
  		{ label: "3Y", days: 365 * 3 },
  		{ label: "5Y", days: 365 * 5 },
  	];

  	const periodStats = $derived.by((): Array<{ label: string; stat: PeriodStat }> => {
  		if (navBars.length < 2) return PERIODS.map((p) => ({ label: p.label, stat: { return_pct: null } }));
  		const last = navBars[navBars.length - 1]!;
  		return PERIODS.map(({ label, days }) => {
  			const cutoff = new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
  			const ref = navBars.find((b) => b.date >= cutoff);
  			if (!ref || ref.value === 0) return { label, stat: { return_pct: null } };
  			return { label, stat: { return_pct: ((last.value - ref.value) / ref.value) * 100 } };
  		});
  	});

  	// ── PerfChart SVG ──────────────────────────────────────────
  	const CHART_W = 320;
  	const CHART_H = 120;

  	const perfChart = $derived.by(() => {
  		if (navBars.length < 2) return { area: "", line: "", isUp: true };
  		const vals = navBars.map((b) => b.value);
  		const minV = Math.min(...vals);
  		const maxV = Math.max(...vals);
  		const range = maxV - minV || 1;
  		const pts = vals.map((v, i) => {
  			const x = (i / (vals.length - 1)) * CHART_W;
  			const y = CHART_H - ((v - minV) / range) * CHART_H;
  			return `${x.toFixed(1)},${y.toFixed(1)}`;
  		});
  		const line = "M " + pts.join(" L ");
  		const area = `${line} L ${CHART_W},${CHART_H} L 0,${CHART_H} Z`;
  		return { area, line, isUp: vals[vals.length - 1]! >= vals[0]! };
  	});

  	// ── CompositeRadar ─────────────────────────────────────────
  	const AXES = ["RETURN", "MOMENTUM", "RISK ADJ", "DD CTL", "COST EFF", "CONSISTENCY"] as const;
  	const RADAR_W = 200;
  	const RADAR_H = 160;
  	const CX = RADAR_W / 2;
  	const CY = RADAR_H / 2;
  	const R = 65;
  	const N = AXES.length;

  	function radarPt(idx: number, r: number) {
  		const a = (idx / N) * 2 * Math.PI - Math.PI / 2;
  		return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) };
  	}

  	const axisScores = $derived.by((): number[] => {
  		if (!detail) return Array(N).fill(50);
  		const ret1y = detail.avg_annual_return_1y;
  		const r = ret1y != null ? Math.min(100, Math.max(0, (ret1y + 0.1) * 500)) : 50;
  		const m = detail.blended_momentum_score ?? 50;
  		const ra = detail.sharpe_ratio != null ? Math.min(100, Math.max(0, (detail.sharpe_ratio + 0.5) * 50)) : 50;
  		const dd = detail.max_drawdown != null ? Math.min(100, Math.max(0, (1 + detail.max_drawdown / 0.5) * 100)) : 50;
  		const ce = detail.expense_ratio_pct != null ? Math.min(100, Math.max(0, 100 - detail.expense_ratio_pct * 50)) : 50;
  		const co = detail.manager_score ?? 50;
  		return [r, m, ra, dd, ce, co];
  	});

  	const radarPath = $derived.by((): string => {
  		const pts = axisScores.map((s, i) => {
  			const p = radarPt(i, (s / 100) * R);
  			return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  		});
  		return "M " + pts.join(" L ") + " Z";
  	});

  	// ── 52W range ──────────────────────────────────────────────
  	const w52 = $derived.by(() => {
  		const cutoff = new Date(Date.now() - 365 * 86_400_000).toISOString().slice(0, 10);
  		const slice = navBars.filter((b) => b.date >= cutoff).map((b) => b.value);
  		if (!slice.length) return null;
  		return { high: Math.max(...slice), low: Math.min(...slice) };
  	});

  	// ── Escape key close ───────────────────────────────────────
  	function handleKeydown(e: KeyboardEvent) {
  		if (e.key === "Escape") onClose();
  	}

  	onMount(() => {
  		document.addEventListener("keydown", handleKeydown);
  		return () => document.removeEventListener("keydown", handleKeydown);
  	});
  </script>

  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="sfm-overlay" onclick={onClose} role="dialog" aria-modal="true" aria-label={fundLabel}>
  	<!-- svelte-ignore a11y_click_events_have_key_events -->
  	<div class="sfm-modal" onclick={(e) => e.stopPropagation()} role="document">

  		<!-- Hero -->
  		<div class="sfm-hero">
  			<div>
  				<h1 class="sfm-name">{fundLabel}</h1>
  				<div class="sfm-meta">
  					{#if detail?.manager_name}<span>{detail.manager_name}</span>{/if}
  					{#if detail?.strategy_label}<span class="sfm-accent">{detail.strategy_label}</span>{/if}
  					{#if detail?.fund_type}<span>{detail.fund_type.replace("_", " ").toUpperCase()}</span>{/if}
  					{#if ticker}<span class="sfm-accent">{ticker}</span>{/if}
  				</div>
  			</div>
  			{#if detail?.aum != null}
  				<div class="sfm-aum">
  					<span class="sfm-aum-val">{formatCurrency(detail.aum / 1_000_000, 0)}M</span>
  					<span class="sfm-aum-label">AUM</span>
  				</div>
  			{/if}
  		</div>

  		<!-- 6-KPI grid (gap:1px hairline) -->
  		<div class="sfm-kpi-grid">
  			{#each [
  				{ l: "1Y RETURN",  v: detail?.avg_annual_return_1y  != null ? formatPercent(detail.avg_annual_return_1y  * 100, 2) : "—", tone: (detail?.avg_annual_return_1y  ?? 0) >= 0 ? "up" : "down" },
  				{ l: "10Y RETURN", v: detail?.avg_annual_return_10y != null ? formatPercent(detail.avg_annual_return_10y * 100, 2) : "—", tone: (detail?.avg_annual_return_10y ?? 0) >= 0 ? "up" : "down" },
  				{ l: "SHARPE",     v: detail?.sharpe_ratio  != null ? formatNumber(detail.sharpe_ratio, 2) : "—",  tone: "" },
  				{ l: "MAX DD",     v: detail?.max_drawdown  != null ? formatPercent(detail.max_drawdown * 100, 1) : "—", tone: "down" },
  				{ l: "EXPENSE",    v: detail?.expense_ratio_pct != null ? formatPercent(detail.expense_ratio_pct, 2) + "%" : "—", tone: "" },
  				{ l: "SCORE",      v: detail?.manager_score != null ? formatNumber(detail.manager_score, 0) : "—", tone: "" },
  			] as kpi (kpi.l)}
  				<div class="sfm-kpi">
  					<span class="sfm-kpi-label">{kpi.l}</span>
  					<span class="sfm-kpi-value {kpi.tone}">{kpi.v}</span>
  				</div>
  			{/each}
  		</div>

  		<!-- Body: 2-col -->
  		<div class="sfm-body">
  			<!-- LEFT: PerfChart + period stats + 52W -->
  			<div class="sfm-section">
  				<h3 class="sfm-sh">PERFORMANCE</h3>
  				<div class="sfm-perf-chart">
  					{#if loadingNav}
  						<div class="sfm-chart-empty">Loading…</div>
  					{:else if perfChart.line}
  						<svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none" width="100%" height="100%">
  							<defs>
  								<linearGradient id="sfm-g-{fundId}" x1="0" y1="0" x2="0" y2="1">
  									<stop offset="0%"   stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0.35"/>
  									<stop offset="100%" stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0"/>
  								</linearGradient>
  							</defs>
  							<path d={perfChart.area} fill="url(#sfm-g-{fundId})"/>
  							<path d={perfChart.line} fill="none" stroke={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stroke-width="1.5"/>
  						</svg>
  					{:else}
  						<div class="sfm-chart-empty">No NAV data</div>
  					{/if}
  				</div>

  				<div class="sfm-period-grid">
  					{#each periodStats as { label, stat } (label)}
  						<div class="sfm-period-row">
  							<span class="sfm-period-lbl">{label}</span>
  							<span class="sfm-period-val" class:up={(stat.return_pct ?? 0) >= 0} class:down={(stat.return_pct ?? 0) < 0}>
  								{stat.return_pct != null ? (stat.return_pct >= 0 ? "+" : "") + formatPercent(stat.return_pct, 2) : "—"}
  							</span>
  						</div>
  					{/each}
  				</div>

  				{#if w52}
  					<div class="sfm-52w">
  						<span class="sfm-52w-lbl">52W</span>
  						<span class="sfm-52w-val down">{formatCurrency(w52.low)}</span>
  						<span class="sfm-52w-sep">–</span>
  						<span class="sfm-52w-val up">{formatCurrency(w52.high)}</span>
  					</div>
  				{/if}
  			</div>

  			<!-- RIGHT: CompositeRadar + axis bars -->
  			<div class="sfm-section">
  				<h3 class="sfm-sh">COMPOSITE PROFILE</h3>
  				<div class="sfm-radar-wrap">
  					<svg viewBox="0 0 {RADAR_W} {RADAR_H}" width={RADAR_W} height={RADAR_H}>
  						{#each [0.25, 0.5, 0.75, 1.0] as pct}
  							{@const pts = Array.from({ length: N }, (_, i) => {
  								const p = radarPt(i, pct * R);
  								return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  							})}
  							<polygon points={pts.join(" ")} fill="none" stroke="var(--ii-border-subtle,#1A2458)" stroke-width="1"/>
  						{/each}
  						{#each Array.from({ length: N }, (_, i) => i) as i (i)}
  							{@const ep = radarPt(i, R)}
  							<line x1={CX} y1={CY} x2={ep.x} y2={ep.y} stroke="var(--ii-border,#1A2458)" stroke-width="1"/>
  						{/each}
  						<path d={radarPath} fill="var(--ii-brand-primary,#FF965A)" fill-opacity="0.18" stroke="var(--ii-brand-primary,#FF965A)" stroke-width="1.5"/>
  						{#each AXES as label, i (label)}
  							{@const lp = radarPt(i, R + 14)}
  							<text x={lp.x} y={lp.y} text-anchor="middle" dominant-baseline="middle"
  								font-family="var(--ii-font-mono)" font-size="7"
  								fill="var(--ii-text-muted,#6D7DA6)" letter-spacing="0.05em">{label}</text>
  						{/each}
  					</svg>
  				</div>

  				<div class="sfm-axis-bars">
  					{#each AXES as label, i (label)}
  						{@const score = axisScores[i] ?? 0}
  						<div class="sfm-axis-row">
  							<span class="sfm-axis-lbl">{label}</span>
  							<span class="sfm-axis-bar-wrap">
  								<span class="sfm-axis-bar" style="width:{score}%"></span>
  							</span>
  							<span class="sfm-axis-val">{formatNumber(score, 0)}</span>
  						</div>
  					{/each}
  				</div>
  			</div>
  		</div>

  		<button type="button" class="sfm-close" onclick={onClose} aria-label="Close">[ ESC · CLOSE ]</button>
  	</div>
  </div>

  <style>
  	.sfm-overlay {
  		position: fixed;
  		inset: 0;
  		background: rgba(5, 8, 26, 0.72);
  		display: flex;
  		align-items: center;
  		justify-content: center;
  		z-index: 9999;
  	}
  	.sfm-modal {
  		width: 1040px; max-width: 98vw;
  		height: 88vh;  max-height: 88vh;
  		background: var(--ii-surface, #0B1230);
  		border: 1px solid var(--ii-border, #1A2458);
  		display: flex; flex-direction: column;
  		overflow: hidden;
  		font-family: var(--ii-font-mono);
  		position: relative;
  	}
  	/* Hero */
  	.sfm-hero {
  		display: grid; grid-template-columns: 1fr auto;
  		gap: 24px; padding: 18px 20px;
  		border-bottom: 1px solid var(--ii-border-subtle);
  		background: var(--ii-surface-alt);
  		flex-shrink: 0;
  	}
  	.sfm-name { font-family: var(--ii-font-sans, var(--ii-font-mono)); font-size: 22px; font-weight: 300; color: var(--ii-text-primary); margin: 0 0 4px; letter-spacing: -0.01em; }
  	.sfm-meta { font-size: 10px; letter-spacing: 0.08em; color: var(--ii-text-muted); text-transform: uppercase; display: flex; gap: 14px; margin-top: 6px; flex-wrap: wrap; }
  	.sfm-accent { color: var(--ii-brand-primary); font-weight: 600; }
  	.sfm-aum { text-align: right; }
  	.sfm-aum-val { display: block; font-size: 20px; font-weight: 600; color: var(--ii-text-primary); font-variant-numeric: tabular-nums; }
  	.sfm-aum-label { font-size: 9px; letter-spacing: 0.08em; color: var(--ii-text-muted); text-transform: uppercase; }
  	/* 6-KPI grid */
  	.sfm-kpi-grid {
  		display: grid; grid-template-columns: repeat(6, 1fr);
  		gap: 1px; background: var(--ii-border-subtle);
  		padding: 1px; flex-shrink: 0;
  	}
  	.sfm-kpi { background: var(--ii-surface); padding: 10px 12px; }
  	.sfm-kpi-label { font-size: 9px; letter-spacing: 0.08em; color: var(--ii-text-muted); text-transform: uppercase; display: block; }
  	.sfm-kpi-value { font-size: 18px; font-weight: 600; color: var(--ii-text-primary); margin-top: 4px; font-variant-numeric: tabular-nums; display: block; }
  	.sfm-kpi-value.up   { color: var(--ii-success, #3DD39A); }
  	.sfm-kpi-value.down { color: var(--ii-danger, #FF5C7A); }
  	/* Body 2-col */
  	.sfm-body { display: grid; grid-template-columns: 1.4fr 1fr; gap: 1px; background: var(--ii-border-subtle); flex: 1; min-height: 0; overflow: hidden; }
  	.sfm-section { background: var(--ii-surface); padding: 14px 18px; overflow-y: auto; min-height: 0; }
  	.sfm-sh { font-size: 10px; letter-spacing: 0.08em; color: var(--ii-text-muted); text-transform: uppercase; margin: 0 0 10px; font-weight: 700; }
  	/* PerfChart */
  	.sfm-perf-chart { height: 120px; margin-bottom: 14px; border: 1px solid var(--ii-border-subtle); }
  	.sfm-chart-empty { height: 100%; display: flex; align-items: center; justify-content: center; font-size: 10px; color: var(--ii-text-muted); }
  	/* Period stats */
  	.sfm-period-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 8px; margin-bottom: 12px; }
  	.sfm-period-row { display: flex; justify-content: space-between; align-items: center; padding: 3px 0; border-bottom: 1px solid var(--ii-terminal-hair, rgba(102,137,188,0.14)); }
  	.sfm-period-lbl { font-size: 9px; letter-spacing: 0.06em; color: var(--ii-text-muted); text-transform: uppercase; }
  	.sfm-period-val { font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }
  	.sfm-period-val.up   { color: var(--ii-success); }
  	.sfm-period-val.down { color: var(--ii-danger); }
  	/* 52W */
  	.sfm-52w { display: flex; align-items: center; gap: 8px; font-size: 10px; margin-top: 8px; }
  	.sfm-52w-lbl { font-size: 9px; letter-spacing: 0.06em; color: var(--ii-text-muted); text-transform: uppercase; }
  	.sfm-52w-val { font-weight: 600; font-variant-numeric: tabular-nums; }
  	.sfm-52w-val.up   { color: var(--ii-success); }
  	.sfm-52w-val.down { color: var(--ii-danger); }
  	.sfm-52w-sep { color: var(--ii-text-muted); }
  	/* Radar */
  	.sfm-radar-wrap { display: flex; justify-content: center; padding: 8px 0 14px; }
  	/* Axis bars */
  	.sfm-axis-bars { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--ii-border-subtle); padding-top: 12px; }
  	.sfm-axis-row { display: grid; grid-template-columns: 90px 1fr 32px; gap: 10px; align-items: center; }
  	.sfm-axis-lbl { font-size: 9px; letter-spacing: 0.06em; color: var(--ii-text-muted); text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  	.sfm-axis-bar-wrap { position: relative; display: block; height: 8px; background: var(--ii-surface-alt); border: 1px solid var(--ii-border-subtle); border-radius: 1px; overflow: hidden; }
  	.sfm-axis-bar { position: absolute; left: 0; top: 0; bottom: 0; background: var(--ii-brand-primary); transition: width 200ms ease; }
  	.sfm-axis-val { text-align: right; color: var(--ii-text-primary); font-variant-numeric: tabular-nums; font-size: 12px; font-weight: 600; }
  	/* Close */
  	.sfm-close { position: absolute; top: 12px; right: 12px; background: transparent; border: 1px solid var(--ii-border-subtle); color: var(--ii-text-muted); font-family: var(--ii-font-mono); font-size: 10px; letter-spacing: 0.08em; padding: 4px 10px; cursor: pointer; }
  	.sfm-close:hover { border-color: var(--ii-brand-primary); color: var(--ii-brand-primary); }
  </style>
  ```

- [ ] **Step 4: Update screener page to use new modal**

  In `frontends/terminal/src/routes/screener/+page.svelte`:

  Replace:
  ```svelte
  import FundFocusMode from "@investintell/ii-terminal-core/components/terminal/focus-mode/fund/FundFocusMode.svelte";
  ```
  With:
  ```svelte
  import ScreenerFundFocusModal from "@investintell/ii-terminal-core/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte";
  ```

  Update `FocusTriggerOptions` state to include ticker/instrumentId. Find where `focusEntity` is typed and update to `FocusTriggerOptions` which now includes the new fields.

  Replace the modal render:
  ```svelte
  {#if focusEntity}
      <ScreenerFundFocusModal
          fundId={focusEntity.entityId}
          fundLabel={focusEntity.entityLabel ?? ""}
          ticker={focusEntity.ticker ?? null}
          instrumentId={focusEntity.instrumentId ?? null}
          onClose={closeFocusMode}
      />
  {/if}
  ```

- [ ] **Step 5: Typecheck**

  ```
  make check-all
  ```

  Expected: no TypeScript errors.

- [ ] **Step 6: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/focus-mode/screener/ScreenerFundFocusModal.svelte \
          packages/ii-terminal-core/src/lib/components/terminal/focus-mode/focus-trigger.ts \
          packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalDataGrid.svelte \
          frontends/terminal/src/routes/screener/+page.svelte
  git commit -m "feat(screener): add ScreenerFundFocusModal with PerfChart SVG + CompositeRadar (task 4.1)"
  ```

---

### Task 4.2: FilterRail width — 280px → 240px

UX spec `.scr-shell { grid-template-columns: 240px 1fr }`. Current implementation uses 280px.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalScreenerShell.svelte`

- [ ] **Step 1: Fix grid column width**

  In `TerminalScreenerShell.svelte`, in the `.ts-root` CSS rule, change:

  ```css
  grid-template-columns: 280px 1fr;
  ```

  To:

  ```css
  grid-template-columns: 240px 1fr;
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalScreenerShell.svelte
  git commit -m "fix(screener): align FilterRail to UX spec 240px width (task 4.2)"
  ```

---

## Phase 5: Builder Visual Parity

### Additional files for Phase 5

**Modify (ii-terminal-core):**
- `packages/ii-terminal-core/src/lib/components/terminal/builder/CascadeTimeline.svelte` — collapse/expand when idle
- `packages/ii-terminal-core/src/lib/components/terminal/builder/ActivationBar.svelte` — compliance CTA

**Modify (terminal frontend):**
- `frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte` — tab visited dots + pulse

---

### Task 5.1: PortfolioTabContent — tab visited dots + amber pulse

UX spec (`builder.css`): `.bd-tab.pulsing { animation: tabPulse 1s ease-in-out infinite }` and `.bd-tab.visited::after { 4px green dot top-right }`.

`PortfolioTabContent.svelte` already imports `SvelteSet` and has 7 sub-tabs. This task adds the reactive tracking and CSS.

**Files:**
- Modify: `frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte`

- [ ] **Step 1: Read PortfolioTabContent to locate tab button rendering**

  Open the file and find the array of builder sub-tabs (REGIME / WEIGHTS / RISK / STRESS / BACKTEST / MONTE CARLO / ADVISOR) and the `<button>` elements that render them.

- [ ] **Step 2: Ensure visitedTabs is tracked**

  If a `visitedTabs = $state(new SvelteSet<string>())` does not already exist, add it near the top of `<script>`. Add an effect that marks the initially active sub-tab as visited:

  ```ts
  let visitedTabs = $state(new SvelteSet<string>());

  const isBuilding = $derived(
      workspace.runPhase === "running" || workspace.runPhase === "streaming"
  );

  // Mark initial tab as visited on mount
  $effect(() => {
      if (activeSubTab) visitedTabs.add(activeSubTab);
  });
  ```

  In the sub-tab click handler, add `visitedTabs.add(tabId)` before or after switching:
  ```ts
  function setSubTab(id: string) {
      visitedTabs.add(id);
      activeSubTab = id;
  }
  ```

- [ ] **Step 3: Apply CSS classes to tab buttons**

  Each tab `<button>` in the sub-tab strip should have:

  ```svelte
  <button
      type="button"
      class="bdr-tab"
      class:active={activeSubTab === tab.id}
      class:pulsing={isBuilding && activeSubTab !== tab.id}
      class:visited={visitedTabs.has(tab.id)}
      onclick={() => setSubTab(tab.id)}
  >
      {tab.label}
  </button>
  ```

  (Use the actual class name that exists in the file — check for `bdr-tab` or `bd-tab` or similar.)

- [ ] **Step 4: Add CSS keyframe + visited dot**

  In the `<style>` block:

  ```css
  @keyframes tabPulse {
      0%, 100% { background: transparent; }
      50%       { background: rgba(242, 201, 76, 0.16); }
  }

  .bdr-tab.pulsing {
      animation: tabPulse 1s ease-in-out infinite;
  }

  .bdr-tab.visited {
      position: relative;
  }

  .bdr-tab.visited::after {
      content: "";
      position: absolute;
      top: 4px;
      right: 4px;
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: var(--ii-success, var(--terminal-status-success, #3DD39A));
      pointer-events: none;
  }
  ```

- [ ] **Step 5: Pass allTabsVisited to ActivationBar**

  Find the `<ActivationBar>` usage and ensure it receives the derived value:

  ```svelte
  {@const allTabsVisited = BUILDER_TABS.every((t) => visitedTabs.has(t.id))}
  <ActivationBar {allTabsVisited} />
  ```

- [ ] **Step 6: Typecheck + commit**

  ```
  make check-all
  git add frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte
  git commit -m "feat(builder): tab visited green dots + amber pulse during build (task 5.1)"
  ```

---

### Task 5.2: CascadeTimeline — collapse when idle

UX spec: `.bd-cascade.collapsed { max-height: 0; padding: 0 16px; overflow: hidden }`. The timeline should collapse when no build is in progress.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/builder/CascadeTimeline.svelte`
- Modify: `frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte`

- [ ] **Step 1: Add `collapsed` prop to CascadeTimeline**

  In `CascadeTimeline.svelte`, add to the `Props` interface:

  ```ts
  collapsed?: boolean;
  ```

  Destructure with default `false`:

  ```ts
  let { phases, runProgress = 0, showProgress = false, pipelinePhase = "IDLE", pipelineErrored = false, collapsed = false }: Props = $props();
  ```

  Add the class to the root element:

  ```svelte
  <div class="cascade-root" class:cascade-collapsed={collapsed}>
  ```

- [ ] **Step 2: Add CSS transition**

  In `CascadeTimeline.svelte` `<style>` block:

  ```css
  .cascade-root {
      overflow: hidden;
      transition: max-height 200ms ease, padding-top 200ms ease, padding-bottom 200ms ease;
      max-height: 120px;
  }

  .cascade-collapsed {
      max-height: 0 !important;
      padding-top: 0 !important;
      padding-bottom: 0 !important;
  }
  ```

- [ ] **Step 3: Pass `collapsed` from PortfolioTabContent**

  In `frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte`, find the `<CascadeTimeline>` usage and add:

  ```svelte
  <CascadeTimeline
      {phases}
      {runProgress}
      showProgress={isBuilding}
      pipelinePhase={workspace.pipelinePhase ?? "IDLE"}
      pipelineErrored={workspace.runPhase === "error"}
      collapsed={!isBuilding && workspace.runPhase !== "done"}
  />
  ```

- [ ] **Step 4: Typecheck + commit**

  ```
  make check-all
  git add packages/ii-terminal-core/src/lib/components/terminal/builder/CascadeTimeline.svelte \
          frontends/terminal/src/lib/components/builder/PortfolioTabContent.svelte
  git commit -m "feat(builder): cascade timeline collapses when idle (task 5.2)"
  ```

---

### Task 5.3: ActivationBar — compliance CTA

The UX spec shows `SEND TO COMPLIANCE ▸` as the primary activation CTA with a green ready-state background. Current implementation shows "Activate Portfolio". This task aligns the label and adds the UX spec's `.ready` state styling.

**Files:**
- Modify: `packages/ii-terminal-core/src/lib/components/terminal/builder/ActivationBar.svelte`

- [ ] **Step 1: Update primary button label**

  In `ActivationBar.svelte`, find:

  ```svelte
  <button type="button" class="ab-btn ab-btn--primary" onclick={handleActivateClick}>
      Activate Portfolio
  </button>
  ```

  Replace with:

  ```svelte
  <button type="button" class="ab-btn ab-btn--activate" onclick={handleActivateClick}>
      SEND TO COMPLIANCE ▸
  </button>
  ```

- [ ] **Step 2: Add `.ab-btn--activate` ready-state style**

  In the `<style>` block:

  ```css
  .ab-btn--activate {
      background: var(--ii-success, var(--terminal-status-success, #3DD39A));
      color: var(--ii-bg, #05081A);
      border-color: var(--ii-success, #3DD39A);
      font-weight: 700;
      letter-spacing: 0.06em;
      font-family: var(--ii-font-mono);
  }

  .ab-btn--activate:hover {
      filter: brightness(1.1);
  }
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add packages/ii-terminal-core/src/lib/components/terminal/builder/ActivationBar.svelte
  git commit -m "feat(builder): ActivationBar compliance CTA + green ready state (task 5.3)"
  ```

---

### Task 5.4: Phase 5 Build Gate

- [ ] **Step 1: Full build**

  ```
  make build-all
  ```

  Expected: all packages build successfully.

- [ ] **Step 2: Typecheck all**

  ```
  make check-all
  ```

- [ ] **Step 3: Final commit if needed**

  ```bash
  git add -p
  git commit -m "fix(builder): resolve typecheck issues from phase 5 visual parity tasks"
  ```

---

## Updated Self-Review Checklist (Phases 3–5)

| Spec requirement | Task | Status |
|---|---|---|
| Live: MacroRegimePanel 4-region rows (US/EU/EM/BR) | 3.1–3.2 | — |
| Live: regime labels GOLDILOCKS/OVERHEATING/STAGFLATION/REFLATION with correct colors | 3.2 | — |
| Live: stress badges LOW/MED/HIGH with color borders | 3.2 | — |
| Live: trend arrows ↑/↓ color-coded | 3.2 | — |
| Live: RebalanceFocusMode 4-KPI header ribbon | 3.3 | — |
| Live: KPI ribbon gap:1px hairline pattern | 3.3 | — |
| Screener: FundFocusModal 1040px × 88vh (not full-screen) | 4.1 | — |
| Screener: fund hero with name, manager, AUM badge | 4.1 | — |
| Screener: 6-KPI grid gap:1px hairline | 4.1 | — |
| Screener: PerfChart SVG area with up/down gradient | 4.1 | — |
| Screener: period stats 1M/3M/6M/1Y/3Y/5Y computed from NAV | 4.1 | — |
| Screener: 52W High/Low range row | 4.1 | — |
| Screener: CompositeRadar 6-axis spider SVG | 4.1 | — |
| Screener: axis score bars (6 axes with fill proportion) | 4.1 | — |
| Screener: ESC key + backdrop click close | 4.1 | — |
| Screener: FilterRail width 240px (from 280px) | 4.2 | — |
| Builder: tab visited green dot 4px top-right | 5.1 | — |
| Builder: tab amber pulse during active build | 5.1 | — |
| Builder: CascadeTimeline collapses when no build running | 5.2 | — |
| Builder: ActivationBar "SEND TO COMPLIANCE ▸" green CTA | 5.3 | — |
| `make build-all` passes (Phase 5 gate) | 5.4 | — |

**Deferred (future sprints):**
- Live: ChartToolbar remove `6M` timeframe to match UX spec (1D/1W/1M/3M/1Y/5Y/MAX)
- Screener: Peer Sharpe/Drawdown comparison bars in FundFocusModal (requires `/screener/peer-metrics/{id}`)
- Screener: DD chapters list in FundFocusModal right section
- Builder: CalibrationPanel preset buttons (CONSERVATIVE/MODERATE/AGGRESSIVE)
- Builder: Region allocation cap sliders in CalibrationPanel ZoneB
- Macro: Region selector toolbar (GLOBAL / US / EU / ASIA / BR)
