---
title: "feat: Wealth Macro Intelligence Suite — Top-Down Analysis & Tactical Allocation"
type: feat
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-wealth-macro-intelligence-suite-brainstorm.md
deepened: 2026-03-15 (10 parallel research + review agents), re-deepened post-merge (6 agents vs current codebase)
---

# feat: Wealth Macro Intelligence Suite

## Overview

Build a top-down macro analysis suite for the Wealth Management vertical: **Global Macro → Regional Analysis → Sector Rotation → Tactical Asset Allocation**. The system generates tactical allocation proposals that a Macro Committee (CIO approval) reviews.

Today, Netz Wealth has strong bottom-up capabilities (backtest, optimization, CVaR, rebalance, drift) but zero top-down intelligence. Tactical positions in `TacticalPosition` are 100% manual. Two parallel FRED data paths exist that need unification.

(see brainstorm: `docs/brainstorms/2026-03-15-wealth-macro-intelligence-suite-brainstorm.md`)

## Architecture

```
quant_engine/
  regional_macro_service.py       ← Regional scores + series registry (Phase 1)
  macro_snapshot_builder.py       ← Pure snapshot assembler, no I/O (Phase 1)
  regime_service.py               ← EXPANDED: classify_regional_regime() (Phase 2)
  fred_service.py                 ← EXISTING: single FRED source

vertical_engines/wealth/
  macro_committee_engine.py       ← Committee reports + workflow (Phase 2)

backend/app/domains/wealth/
  workers/macro_ingestion.py      ← Worker: FRED fetch + score compute (Phase 1)
  models/macro_committee.py       ← MacroReview + MacroRegionalSnapshot (Phase 1-2)
  schemas/macro.py                ← EXPANDED: regional scores, committee (Phase 1+)
  routes/macro.py                 ← 2 routes Phase 1, +5 Phase 2

calibration/seeds/liquid_funds/
  macro_intelligence.yaml         ← Regional weights, thresholds, staleness config
```

No `macro_engine/` sub-package — files go directly in `quant_engine/` to match existing flat structure.

### Design Principles

1. **Pure sync functions** in `quant_engine/` — no DB, no async, no I/O. Config injected as parameter.
2. **`resolve_*_config(config: dict | None) → TypedDict`** — hardcoded defaults when `config is None`.
3. **Worker handles all I/O** — `macro_snapshot_builder.py` receives raw data dict, never calls `FredService` directly. Worker is async, dispatches sync `FredService` via `asyncio.to_thread()`.
4. **Separate snapshot table** — `macro_regional_snapshots` in `app/shared/models.py` (global, no RLS) to avoid collision with credit's `macro_snapshots`.
5. **Geopolitical neutrality** — system measures intensity of stress/disruption, never classifies nations or favors outcomes.
6. **Frozen dataclasses** — all result types use `@dataclass(frozen=True)` for thread safety across async/sync boundary.
7. **Shared model placement** — global tables (`MacroRegionalSnapshot`) go in `app/shared/models.py` alongside `MacroData` and `MacroSnapshot`. Org-scoped tables (`MacroReview`) go in `app/domains/wealth/models/`.

---

## Phase 1: Foundation — Global Macro Collection & Scoring

**Goal:** Unify FRED paths, build regional macro scoring for 4 regions + global indicators, expose via API.

### 1.1 FRED Series Registry (Validated Active)

All series validated against FRED API. Corrected for OECD 2023 migration discontinuities.

#### US (14 series — 6/6 dimensions)

| Dimension | Series ID | Label | Freq | Lag |
|---|---|---|---|---|
| growth | A191RL1Q225SBEA | Real GDP Growth | Q | 30d |
| growth | INDPRO | Industrial Production | M | 16d |
| growth | PAYEMS | Nonfarm Payrolls | M | 5d |
| inflation | CPIAUCSL | CPI All Urban | M | 16d |
| inflation | PCEPILFE | Core PCE | M | 30d |
| monetary | DFF | Fed Funds Rate | D | 1d |
| monetary | DGS10 | 10Y Treasury | D | 1d |
| monetary | DGS2 | 2Y Treasury | D | 1d |
| financial_conditions | NFCI | Chicago Fed Financial Conditions | W | 7d |
| financial_conditions | VIXCLS | VIX | D | 1d |
| labor | UNRATE | Unemployment Rate | M | 5d |
| labor | JTSJOL | JOLTS Openings | M | 40d |
| labor | SAHMREALTIME | Sahm Rule | M | 5d |
| sentiment | UMCSENT | Michigan Consumer Sentiment | M | 3d |

#### Europe (6 series — 5/6 dimensions, no labor)

| Dimension | Series ID | Label | Freq | Lag | Notes |
|---|---|---|---|---|---|
| growth | CLVMNACSCAB1GQEA19 | Euro Area Real GDP | Q | 90d | Active |
| inflation | CP0000EZ19M086NEST | Eurostat HICP EA19 | M | 45d | Replaces stale EA19CPALTT01GYM |
| monetary | ECBDFR | ECB Deposit Facility Rate | D | 1d | Active, direct ECB source |
| monetary | IRLTLT01DEM156N | German 10Y Bund | M | 45d | Active |
| financial_conditions | BAMLHE00EHYIEY | Euro HY Effective Yield (ICE BofA) | D | 1d | Active, market-priced |
| sentiment | CSCICP02EZM460S | Consumer Confidence EA19 | M | 5d | Corrected ID (VERIFY at implementation) |

Labor deferred to Eurostat integration (future phase). `LRHUTTTTEZM156S` stale since Jan 2023.

#### Asia (7 series — 4/6 dimensions)

| Dimension | Series ID | Label | Freq | Lag | Notes |
|---|---|---|---|---|---|
| growth | JPNRGDPEXP | Japan Real GDP | Q | 75d | Active |
| growth | CHNLOLITOAASTSAM | China CLI Amplitude-Adjusted | M | 45d | Replaces dead BSCICP03CNM460S + stale CHNGDPNQDSMEI |
| growth | JPNLOLITOAASTSAM | Japan CLI Amplitude-Adjusted | M | 45d | Active; cycle proxy |
| inflation | JPNCPIALLMINMEI | Japan CPI | M | 45d | Active |
| inflation | CHNCPIALLMINMEI | China CPI | M | 60d | Active |
| monetary | IRLTLT01JPM156N | 10Y JGB Yield | M | 45d | Active |
| financial_conditions | BAMLEMRACRPIASIAOAS | Asia EM Corp OAS (ICE BofA) | D | 1d | Active, market-priced |

No labor or sentiment series available on FRED for Asia.

#### EM (7 series — 4/6 dimensions)

| Dimension | Series ID | Label | Freq | Lag | Notes |
|---|---|---|---|---|---|
| growth | BRALOLITOAASTSAM | Brazil CLI Amplitude-Adjusted | M | 45d | Replaces stale BRALORSGPNOSTSAM |
| growth | INDLOLITOAASTSAM | India CLI Amplitude-Adjusted | M | 45d | Replaces stale INDLORSGPNOSTSAM |
| growth | MEXLOLITONOSTSAM | Mexico CLI Normalized | M | 45d | Replaces dead MXNLORSGPNOSTSAM |
| inflation | BRACPIALLMINMEI | Brazil CPI | M | 45d | Active |
| inflation | INDCPIALLMINMEI | India CPI | M | 45d | Active |
| monetary | INTDSRBRM193N | Brazil SELIC (IMF) | M | 30d | Corrected typo from INTDSRBZM193N |
| financial_conditions | BAMLEMCBPIOAS | EM Corp OAS (ICE BofA) | D | 1d | Active, market-priced |

India repo rate (INTDSRINM193N) stale since Jul 2022 — no FRED replacement.

#### Global Indicators (11 series — geopolitical risk + commodities)

| Category | Series ID | Label | Freq | Lag |
|---|---|---|---|---|
| geopolitical | GPRH | Geopolitical Risk Index (Fed) | M | 30d |
| geopolitical | USEPUINDXD | Economic Policy Uncertainty | D | 1d |
| energy | DCOILWTICO | WTI Crude Oil | D | 1d |
| energy | DCOILBRENTEU | Brent Crude Oil | D | 1d |
| energy | DHHNGSP | Henry Hub Natural Gas | D | 1d |
| reserves | WCSSTUS1 | US Strategic Petroleum Reserve | W | 7d |
| reserves | WCESTUS1 | US Crude Oil Inventories | W | 7d |
| metals | PCOPPUSDM | Global Copper Price | M | 30d |
| metals | GOLDAMGBD228NLBM | London Gold Price | D | 1d |
| agriculture | PFERTINDEXM | Fertilizer Price Index | M | 30d |
| currency | DTWEXBGS | USD Trade-Weighted Index | D | 1d |

**Total: ~45 FRED series.** At 2 req/s = ~23 seconds fetch time.

### 1.2 Regional Macro Scoring

`quant_engine/regional_macro_service.py`

**Normalization:** Expanding-window percentile rank over full available history (minimum 10 years). Each indicator maps to 0-100 where 50 = historical median. Robust to outliers (unlike min-max), bounded (unlike z-score), no distributional assumptions.

Source: Macrosynergy Research (2024) — institutional standard for macro scorecards.

```python
def percentile_rank_score(current: float, history: np.ndarray, invert: bool = False) -> float:
    """0-100 percentile rank. Returns 50.0 if insufficient history (<60 obs)."""
```

**Staleness weight decay:** Linear decay with per-frequency config:

| Frequency | Fresh Window | Max Useful | Floor Weight |
|---|---|---|---|
| Daily | 3 days | 10 days | 0.30 |
| Weekly | 10 days | 30 days | 0.40 |
| Monthly | 45 days | 90 days | 0.50 |
| Quarterly | 100 days | 180 days | 0.50 |

**Composite score:** Weighted average of dimension scores. Dimensions with no data excluded from denominator. Equal-weight defaults (configurable via ConfigService). Coverage threshold: min 50% of total weight to produce a score.

```python
@dataclass
class RegionalMacroResult:
    region: str                               # "US", "EUROPE", "ASIA", "EM"
    composite_score: float                    # 0-100
    dimensions: dict[str, DimensionScore]     # per-dimension detail
    data_freshness: dict[str, DataFreshness]  # per-indicator staleness
    as_of_date: date
    coverage: float                           # 0-1, fraction of dimensions with data

@dataclass
class GlobalIndicatorsResult:
    geopolitical_risk_score: float            # GPR + EPU composite
    energy_stress: float                      # oil, gas, reserves
    commodity_stress: float                   # copper, gold, fertilizer
    usd_strength: float                       # trade-weighted index percentile
    as_of_date: date
```

### 1.3 Snapshot Builder (Pure Function)

`quant_engine/macro_snapshot_builder.py`

**Receives raw data dict from worker — does NOT call FredService.** Pure computation.

```python
def build_regional_snapshot(
    raw_observations: dict[str, list[FredObservation]],  # fetched by worker
    *,
    config: dict | None = None,
) -> dict:
    """Build v1 regional snapshot from raw FRED data. No I/O."""
```

### 1.4 New Table: `macro_regional_snapshots`

**CRITICAL:** Separate from credit's `macro_snapshots` to avoid cross-vertical JSON schema collision. Lives in `app/shared/models.py` (global table pattern, alongside `MacroData` and `MacroSnapshot`).

```python
# In backend/app/shared/models.py
class MacroRegionalSnapshot(IdMixin, AuditMetaMixin, Base):
    __tablename__ = "macro_regional_snapshots"
    as_of_date: Mapped[date]       # UNIQUE
    data_json: Mapped[dict]        # JSONB (not JSON — unlike credit's macro_snapshots)
    # GLOBAL — no organization_id, no RLS
    # AuditMetaMixin provides created_by, updated_at, updated_by for traceability
```

**Note:** Credit's `macro_snapshots` uses `JSON` column type. This table uses `JSONB` (preferred — supports GIN indexes). Intentional difference.

Migration: `backend/app/core/db/migrations/versions/0005_macro_regional_snapshots.py`

### 1.5 Worker

`backend/app/domains/wealth/workers/macro_ingestion.py`

- `async def run_macro_ingestion() -> dict`
- Creates `FredService` instance with `httpx.Client` persistent session + thread-safe `TokenBucketRateLimiter`
- Dispatches sync `FredService.fetch_batch()` via `asyncio.to_thread()` (worker is async, FredService is sync)
- **IMPORTANT:** Set `limit` per series config to match lookback needs: daily=2520, monthly=120, quarterly=40 (default `limit=10` is far too low for 10yr percentile computation)
- Passes raw data to `build_regional_snapshot()` (pure function, also in `to_thread()`)
- Stores snapshot in `macro_regional_snapshots` table
- Upserts individual series to `macro_data` table (backward compat with existing `regime_service.get_latest_macro_values()`)
- **Advisory lock ID = 43** (separate from drift_check's 42)
- **Replaces `fred_ingestion.py`** — superset of its 10 series (VIXCLS, DGS10, DGS2, DFF, CPIAUCSL, SAHMREALTIME, UNRATE, PAYEMS, INDPRO, NFCI + 3 derived). Kill switch: disable `fred_ingestion` before enabling `macro_ingestion`.
- **Suppress httpx DEBUG logs:** Add `logging.getLogger("httpx").setLevel(logging.WARNING)` to prevent FRED API key exposure in URL parameters (matching pattern from `fred_ingestion.py:28`).

### 1.6 API Routes (Phase 1)

```python
GET  /api/wealth/macro/scores     # Latest regional scores + global indicators
GET  /api/wealth/macro/snapshot   # Latest full snapshot
```

All routes use `response_model=` and `model_validate()`. Authenticated via Clerk JWT.

### 1.7 Calibration Config

`calibration/seeds/liquid_funds/macro_intelligence.yaml`

**ConfigService integration:** The `_YAML_FALLBACK_MAP` in `config_service.py` currently has no entry for macro config. Two options:
- **(A) New config_type `"macro_intelligence"`** — requires ALTER CHECK constraint on `vertical_config_defaults.config_type` to add `'macro_intelligence'` to allowed values (migration 0005). Then add `("liquid_funds", "macro_intelligence"): "calibration/seeds/liquid_funds/macro_intelligence.yaml"` to the fallback map.
- **(B) Nest under existing `"calibration"` type** — add a `macro_intelligence:` top-level key inside `calibration/config/limits.yaml`. Simpler (no CHECK ALTER, no new fallback entry) but mixes concerns.

**Recommended: Option A** — clean separation. The CHECK ALTER is trivial (one line in migration 0005).

**Note:** `calibration/seeds/liquid_funds/` directory does not exist yet — must be created.

```yaml
regional_scoring:
  lookback_years: 10
  dimension_weights:
    growth: 0.20
    inflation: 0.20
    monetary: 0.15
    financial_conditions: 0.20
    labor: 0.15
    sentiment: 0.10
  min_coverage: 0.50
  staleness:
    daily:     { fresh_days: 3,   max_useful_days: 10,  floor: 0.30 }
    weekly:    { fresh_days: 10,  max_useful_days: 30,  floor: 0.40 }
    monthly:   { fresh_days: 45,  max_useful_days: 90,  floor: 0.50 }
    quarterly: { fresh_days: 100, max_useful_days: 180, floor: 0.50 }
```

### Phase 1 Files

| File | Action | LOC est. |
|---|---|---|
| `quant_engine/regional_macro_service.py` | Create (includes series registry as constant) | ~300 |
| `quant_engine/macro_snapshot_builder.py` | Create (pure function) | ~120 |
| `backend/app/domains/wealth/workers/macro_ingestion.py` | Create | ~120 |
| `backend/app/shared/models.py` | Expand (+MacroRegionalSnapshot, global table) | +15 |
| `backend/app/domains/wealth/schemas/macro.py` | Expand | +80 |
| `backend/app/domains/wealth/routes/macro.py` | Create | ~60 |
| `calibration/seeds/liquid_funds/macro_intelligence.yaml` | Create | ~40 |
| `backend/app/core/db/migrations/versions/0005_macro_regional_snapshots.py` | Create (includes CHECK ALTER for config_type) | ~40 |
| `backend/tests/quant_engine/test_regional_macro_service.py` | Create | ~200 |
| `backend/tests/quant_engine/test_macro_snapshot_builder.py` | Create | ~100 |

---

## Phase 2: Regime Hierarchy & Committee

**Goal:** Expand regime detection to per-region + global, add committee workflow with weekly snapshots.

### 2.1 Hierarchical Regime Detection

Expand `quant_engine/regime_service.py` with new functions (not replacing existing):

**Primary regional signals (all ICE BofA credit spreads — daily, never discontinued):**

| Region | Primary Signal | FRED ID |
|---|---|---|
| US | VIX + US HY OAS | VIXCLS, BAMLH0A0HYM2 |
| Europe | Euro HY OAS | BAMLHE00EHYIOAS |
| Asia | Asia EM Corp OAS | BAMLEMRACRPIASIAOAS |
| EM | EM Corp OAS | BAMLEMCBPIOAS |

**Asymmetric hysteresis:**

| Transition | Confirmation Days |
|---|---|
| Any → CRISIS | 0 (immediate) |
| Any → RISK_OFF | 3 |
| Any → INFLATION | 5 |
| CRISIS → RISK_OFF | 5 |
| RISK_OFF → RISK_ON | 5 |
| CRISIS → RISK_ON | 10 |

**Global composition:** GDP-weighted (US: 0.25, EU: 0.22, Asia: 0.28, EM: 0.25) with pessimistic override:
- Any region weight ≥ 0.20 in CRISIS → global at minimum RISK_OFF
- 2+ regions in CRISIS → global CRISIS regardless of weights

**Backward compatibility:** `RegimeRead` extended with optional `regional_regimes: dict[str, str] | None`.

### 2.2 MacroReview Model

```python
class MacroReview(IdMixin, OrganizationScopedMixin, AuditMetaMixin, Base):
    __tablename__ = "macro_reviews"

    status: Mapped[str]                    # "pending" | "approved" | "rejected"
    is_emergency: Mapped[bool]             # True = auto-generated on regime transition
    as_of_date: Mapped[date]
    snapshot_id: Mapped[UUID | None]       # FK → macro_regional_snapshots.id (global→org cross-scope FK)
    report_json: Mapped[dict]              # Full report (JSONB)
    approved_by: Mapped[str | None]        # CIO email
    approved_at: Mapped[datetime | None]
    decision_rationale: Mapped[str | None]
```

**Migration `backend/app/core/db/migrations/versions/0006_macro_reviews.py`** must include the **full RLS pattern from 0003** (not the incomplete one from 0004):
```sql
ALTER TABLE macro_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY org_isolation ON macro_reviews
    USING (organization_id = (SELECT current_setting('app.current_organization_id')::uuid))
    WITH CHECK (organization_id = (SELECT current_setting('app.current_organization_id')::uuid));
```

Also add **CHECK constraint on status**:
```sql
ALTER TABLE macro_reviews ADD CONSTRAINT chk_macro_review_status
    CHECK (status IN ('pending', 'approved', 'rejected'));
```

### 2.3 Committee Workflow

**Weekly delta report:**
- Compare current snapshot vs. previous week
- Flag: regime transitions, score changes > 5 points, staleness alerts, commodity stress changes
- Generate `MacroReview(status="pending")` for CIO

**Emergency trigger:**
- Global regime transition → auto-generate `MacroReview(is_emergency=True)`
- 24-hour cooldown between emergency reviews
- `created_by = "system:macro_committee_engine"`

### 2.4 CIO Approval

**Security:**
- `PATCH .../approve` and `PATCH .../reject`: `require_role(Role.DIRECTOR, Role.ADMIN)` — use **variadic Role enums**, NOT lists (pre-existing bug in credit dataroom uses list form which silently fails for non-admin roles)
- `POST .../generate`: `require_role(Role.INVESTMENT_TEAM)`
- Phase 2 routes: use `get_db_with_rls` from `app.core.tenancy.middleware` (NOT `get_db` from `app.database`)
- Background worker (report generation): receives `org_id`, creates own session with `SET LOCAL` — first worker in codebase to do this correctly. Create reusable `get_worker_session_with_rls(org_id)` utility.
- Pydantic validation on PATCH bodies: `decision_rationale: str = Field(max_length=2000)`

**Atomic transaction:**
```python
async with db.begin():
    # SELECT FOR UPDATE on existing TacticalPositions for this profile
    # Close existing (valid_to = review.as_of_date - 1)
    # Insert new TacticalPositions (validate block_ids against allocation_blocks FK)
    # Update MacroReview.status = "approved"
```

**DB enforcement (in migration 0006):**
```sql
-- Data cleanup before index (handles any pre-existing duplicate active positions)
UPDATE tactical_positions tp1 SET valid_to = CURRENT_DATE - 1
WHERE valid_to IS NULL AND position_id != (
    SELECT position_id FROM tactical_positions tp2
    WHERE tp2.organization_id = tp1.organization_id
      AND tp2.profile = tp1.profile AND tp2.block_id = tp1.block_id
      AND tp2.valid_to IS NULL
    ORDER BY tp2.created_at DESC LIMIT 1);

CREATE UNIQUE INDEX uq_tactical_one_active_per_block
ON tactical_positions (organization_id, profile, block_id)
WHERE valid_to IS NULL;
```

### 2.5 API Routes (Phase 2)

```python
GET    /api/wealth/macro/regime                       # Hierarchical regime
GET    /api/wealth/macro/reviews                      # List reviews
POST   /api/wealth/macro/reviews/generate             # Trigger report
PATCH  /api/wealth/macro/reviews/{review_id}/approve  # CIO approval
PATCH  /api/wealth/macro/reviews/{review_id}/reject   # CIO rejection
```

### Phase 2 Files

| File | Action | LOC est. |
|---|---|---|
| `quant_engine/regime_service.py` | Expand (+classify_regional, +compose_global) | +150 |
| `vertical_engines/wealth/macro_committee_engine.py` | Create | ~250 |
| `backend/app/domains/wealth/models/macro_committee.py` | Expand (+MacroReview) | +30 |
| `backend/app/domains/wealth/schemas/macro.py` | Expand | +60 |
| `backend/app/domains/wealth/routes/macro.py` | Expand | +100 |
| `backend/app/core/db/migrations/versions/0006_macro_reviews.py` | Create (RLS + CHECK + partial index) | ~60 |
| `calibration/seeds/liquid_funds/macro_intelligence.yaml` | Expand (regime config) | +30 |
| Tests | Create/expand | ~250 |

---

## Performance Requirements

1. ~~`TokenBucketRateLimiter.acquire()` needs `threading.Lock`~~ — **ALREADY FIXED** in credit-quant-parity refactor (`fred_service.py:49`)
2. **`FredService`** should use `httpx.Client` persistent session — **STILL NEEDED** (current code uses per-request `httpx.get()`, wastes ~10-22s in TLS overhead for 45 series)
3. ~~Fix double `parse_fred_value()` call~~ — **ALREADY FIXED** with walrus operator in refactor (`fred_service.py:225-229`)
4. **`fetch_batch()` limit defaults:** Current default is `limit=10` which silently truncates 10yr history. Worker must set `limit` per frequency: daily=2520, monthly=120, quarterly=40
5. **Percentile ranks** computed from FRED response data (10yr `observation_start`), not from stored snapshots
6. **Advisory lock registry:** `DRIFT_CHECK_LOCK = 42`, `MACRO_INGESTION_LOCK = 43`
7. **Composite indexes** on `macro_reviews`: `(organization_id, status)`, `(organization_id, is_emergency, created_at DESC)`
8. **Suppress httpx DEBUG logs** in `fred_service.py` to prevent FRED API key exposure in URL parameters

---

## Future Considerations

### Sector Rotation
- OECD CLI (`USALOLITONOSTSAM`) as primary cycle indicator — 4-phase economic clock
- Fidelity/State Street sector-cycle mapping table for GICS 11
- Continuous 0-100 conviction scores (55% cycle + 30% momentum + 10% valuation + 5% thematic)
- Only 3 new FRED series needed. Thematic overlays with mandatory human review dates
- Separate `cycle_phase_service.py` from `regime_service.py` (cycle ≠ regime)

### Eurostat Integration
- Statistics API (JSON-stat 2.0), no auth, direct `httpx` (no library)
- 7 datasets: GDP, HICP, unemployment, industrial production, consumer/business confidence, govt debt
- 13 target countries (EA + EU27 + 11 majors). Self-imposed 1 req/s rate limit

### Predictive Model + Tactical Allocation
- Leading indicator model consuming trade flows, rate differentials, energy, PMIs
- TacticalAllocationService generating proposals within configurable bands per profile × asset class
- Monthly committee report generation with full integration to drift/rebalance services

### Geopolitical Scenario Engine
- Pre-defined scenarios with triggers and playbooks (e.g., "Energy supply disruption", "Trade route blockage")
- Scenarios are symmetric — escalation and détente variants for each
- Monitor GPR/EPU indices + commodity/shipping signals against configurable thresholds
- Not prediction — detection + preparation

---

## Sources & References

### Origin
- **Brainstorm:** `docs/brainstorms/2026-03-15-wealth-macro-intelligence-suite-brainstorm.md`

### Research (10-agent deep review, 2026-03-15)
- Macrosynergy (2024): "Macro-quantamental scorecards" — percentile normalization, equal-weight composites
- CFA Institute (2025): "Regime-Based Strategic Asset Allocation"
- Fidelity: "The Business Cycle Approach to Equity Sector Investing"
- Resonanz Capital (2025): "Regime-Based Allocation: What It Actually Delivers"
- OECD SDMX Migration Documentation (2023) — explains stale international FRED series
- Eurostat Statistics API Documentation (JSON-stat 2.0)
- Caldara & Iacoviello (Federal Reserve): Geopolitical Risk Index methodology

### Internal References
- `quant_engine/fred_service.py` — Universal FRED client
- `quant_engine/regime_service.py` — Current US-only regime (expansion target)
- `quant_engine/stress_severity_service.py` — Pattern reference for configurable scoring
- `quant_engine/drift_service.py:190-202` — TacticalPosition integration point
- `backend/app/domains/wealth/models/allocation.py:36` — TacticalPosition model
- `backend/app/domains/wealth/workers/fred_ingestion.py` — Worker pattern reference
