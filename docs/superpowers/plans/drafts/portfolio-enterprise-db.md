# Portfolio Enterprise Workbench — Database Layer Design

> **Scope:** Database layer only (schema, hypertables, migrations, worker touchpoints, query patterns). No routes, no engines, no frontend. Produced 2026-04-08 against migration head `0096_discovery_fcl_keyset_indexes`.
>
> **Mandate:** Turn the Portfolio vertical into an institutional-grade workbench. The current schema is a daily risk monitor bolted onto a 3-profile model-portfolio prototype. It cannot express lifecycle states, does not persist optimizer narrative, has no unified alerts feed, has no real-time price layer, and conflates strategic / tactical / effective weights into a single JSONB blob on `portfolio_snapshots`.

---

## 0. Current migration head and coordination

Actual head in repo (listed from `backend/app/core/db/migrations/versions/`):

```
0089_wealth_library_index
0090_instruments_universe_slug
0091_wealth_library_pins
0092_wealth_library_triggers
0093_fund_risk_metrics_composite_pk
0094_mv_unified_funds_aum_native_fx
0095_mv_unified_funds_share_class
0096_discovery_fcl_keyset_indexes          <-- current head
```

CLAUDE.md still says head is `0095_mv_unified_funds_share_class` (stale one revision — the Discovery FCL plan committed `0096` on the `feat/discovery-fcl` branch we are on).

**This plan allocates `0097`–`0104`** — eight forward migrations, all reversible. Discovery plan owns 0093–0096; no overlap. Do not collapse into fewer migrations: each is independently reviewable and revertible, and several need `CREATE INDEX` outside a transaction when the prod tables grow.

---

## 1. Audit of current portfolio-related tables

| Table | File | Populated by | Reality check |
|---|---|---|---|
| `model_portfolios` | `backend/app/domains/wealth/models/model_portfolio.py` | `POST /model-portfolios` routes | Has `status` column (`draft` default, `String(20)`) but NO check constraint, NO transition audit, NO `state_changed_at`. Fund selection stored as free-form JSONB (`fund_selection_schema`). `backtest_result` and `stress_result` are JSONB dumps — unqueryable, unversioned, no per-scenario rows. |
| `model_portfolio_nav` | `backend/app/domains/wealth/models/model_portfolio_nav.py` | `portfolio_nav_synthesizer` (lock 900_030) | Org-scoped. **Already a hypertable per CLAUDE.md with 1mo chunks** (added in migration `c3d4e5f6a7b8_timescaledb_hypertables_compression.py`). Stores daily synthetic NAV + `daily_return`. Works. |
| `portfolio_snapshots` | `backend/app/domains/wealth/models/portfolio.py` | `portfolio_eval` (lock 900_008) | **Hypertable, 1mo chunks, segmentby `organization_id`**. Keyed on `(organization_id, profile, snapshot_date)` — note **profile-based**, not portfolio-id-based. Stores effective `weights` as `JSONB`, breach status, regime, cvar_current/limit. This is the current source of "what happened today" but is profile-coarse (conservative / moderate / growth) — cannot express per-portfolio state for an institutional workbench with dozens of named portfolios. |
| `strategic_allocation` | `backend/app/domains/wealth/models/allocation.py` | Manual + `POST /strategic-allocation` | Stores strategic target weights **per block, per profile** with `effective_from`/`effective_to`. Not tied to `model_portfolios.id` — another profile-vs-portfolio mismatch. No versioning of the full vector (each row is a single block). |
| `tactical_positions` | same file | Manual | Overlay overweights per block/profile. Same coarseness problem. |
| `rebalance_events` | `backend/app/domains/wealth/models/rebalance.py` | `POST /rebalance` route | JSONB `weights_before` / `weights_after`, cvar delta. Also profile-keyed, not portfolio-keyed. |
| `strategy_drift_alerts` | `backend/app/domains/wealth/models/strategy_drift_alert.py` | `drift_check` (lock 42) | Per-instrument drift alert with `is_current` flag + `status`, `severity`, `drift_magnitude`. **Hypertable, 1mo chunks, segmentby `instrument_id`** (per migration `0087`). Good primitive, but the **alert surface is instrument-scoped, not portfolio-scoped** — there is no way to ask "what alerts are live on Portfolio Alpha right now." |
| `backtest_runs` | `backend/app/domains/wealth/models/backtest.py` | `POST /backtest` | Generic params+results JSONB. No linkage to model portfolio. |
| `portfolio_views` | `backend/app/domains/wealth/models/portfolio_view.py` (per CLAUDE.md) | IC view entry UI | Feeds Black-Litterman. OK. |
| `fund_risk_metrics` | — | `global_risk_metrics` (900_071) + `risk_calc` (900_007) | **GLOBAL, RLS disabled, hypertable.** Per CLAUDE.md and memory: all tenants see same metrics, org DTW overlay is allowed. Do not touch ownership semantics. |
| `nav_timeseries` | `backend/app/domains/wealth/models/nav.py` | `instrument_ingestion` (900_010) | **GLOBAL, no RLS.** Daily closing NAV via Yahoo. Used for everything. |

**Gaps revealed by the audit:**

1. **Everything is keyed on `profile` (3 buckets), not on `portfolio_id`.** A workbench needs to manage arbitrary named portfolios per tenant, each with independent lifecycle, alerts, stress runs, narrative. `profile` is a v0 relic.
2. **No persisted optimizer narrative.** `ModelPortfolio.backtest_result` and `.stress_result` are single JSONB slots that get overwritten on every run. No history, no per-scenario drill-down, no link to the calibration inputs that produced them.
3. **No unified alert feed.** `strategy_drift_alerts` handles drift only. Breach alerts are fire-and-forget Redis pubsub (`_publish_alert` in `portfolio_eval.py` lines 138–166). Regime changes and rebalance suggestions have nowhere to land.
4. **Three weight vectors (strategic / tactical / effective) are smeared** across `strategic_allocation` (target, block-level), `tactical_positions` (overlay), and `portfolio_snapshots.weights` (effective JSONB, block-level). None of them is instrument-level over time.
5. **No real-time price layer.** `nav_timeseries` is daily closing, ingested by a 900_010 worker. The workbench promise of "live prices" has no home.
6. **No calibration persistence.** The optimizer cascade exposes dozens of knobs (cvar_target, turnover_cap, bl_tau, ledoit_wolf_blend, robust_uncertainty_radius, regime_override, per-fund max weight, sector caps…). None of these are persisted per-run, so after a reload Andrei cannot see "what were the inputs that produced this allocation."

The redesign does **not** delete the legacy profile-keyed tables. They continue to serve the 3-profile risk monitor. The new tables sit alongside and are keyed on `model_portfolios.id` from day one.

---

## 2. Portfolio lifecycle state machine (migration 0097)

### 2.1. Columns added to `model_portfolios`

```sql
-- 0097_model_portfolio_lifecycle_state.py
ALTER TABLE model_portfolios
  ADD COLUMN state              text        NOT NULL DEFAULT 'draft',
  ADD COLUMN state_changed_at   timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN state_changed_by   text,                      -- Clerk user_id
  ADD COLUMN state_metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE model_portfolios
  ADD CONSTRAINT ck_model_portfolios_state
  CHECK (state IN ('draft','constructed','validated','approved','live','paused','archived'));

-- Backfill: existing 'draft' default stays; anything with a backtest_result IS NOT NULL
-- moves to 'constructed', anything with inception_date IS NOT NULL moves to 'live'.
UPDATE model_portfolios SET state = 'constructed' WHERE backtest_result IS NOT NULL AND inception_date IS NULL;
UPDATE model_portfolios SET state = 'live'        WHERE inception_date IS NOT NULL;
```

The legacy `status` column (also `String(20)`) is **kept** for backward compat and marked deprecated in the model docstring. A follow-up cleanup migration (not in this plan) can drop it after all call sites migrate to `state`.

### 2.2. State transitions

```
draft ──construct──▶ constructed ──validate──▶ validated ──approve──▶ approved
                                                                         │
                                                                         ▼
                        archived ◀──archive── paused ◀──pause── live ◀──go_live
                                                                         │
                                                      reopen ◀───────────┘  (allowed only from paused → live)
```

Enforcement lives in the service layer (cleaner than a Postgres function) but the CHECK constraint guarantees no invalid state can be written.

### 2.3. Transition audit table — `portfolio_state_transitions`

**Decision: dedicated table, NOT re-using `AuditEvent`.**

Reason: `AuditEvent` is a generic entity-change log (before/after JSONB). State transitions are domain events with strict schema (from_state, to_state, reason, gate_checks_passed), and the query pattern is "show me all transitions for portfolio X in order" — a very hot workbench read that benefits from a dedicated index. Using `AuditEvent` would force JSON path queries on every load.

```sql
CREATE TABLE portfolio_state_transitions (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id        uuid NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
    from_state          text NOT NULL,
    to_state            text NOT NULL,
    changed_by          text,                        -- Clerk user_id
    changed_at          timestamptz NOT NULL DEFAULT now(),
    reason              text,
    gate_checks         jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {cvar_ok: bool, turnover_ok: bool, stress_ok: bool, …}
    construction_run_id uuid REFERENCES portfolio_construction_runs(id) ON DELETE SET NULL,
    CONSTRAINT ck_pst_to_state CHECK (to_state IN ('draft','constructed','validated','approved','live','paused','archived'))
);

CREATE INDEX ix_pst_portfolio_changed_at ON portfolio_state_transitions (portfolio_id, changed_at DESC);

ALTER TABLE portfolio_state_transitions ENABLE ROW LEVEL SECURITY;
CREATE POLICY pst_rls ON portfolio_state_transitions
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

Subselect pattern mandatory (CLAUDE.md rule — bare `current_setting()` causes 1000× slowdown on per-row evaluation).

---

## 3. Run Construct narrative persistence — `portfolio_construction_runs` (migration 0098)

Every click of "Run Construct" produces one row. Over time a single portfolio has dozens of runs; the workbench shows them in a sidebar and lets the user diff any two.

```sql
CREATE TABLE portfolio_construction_runs (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id            uuid NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
    calibration_id          uuid NOT NULL REFERENCES portfolio_calibration(id),   -- see §4
    requested_by            text NOT NULL,                                        -- Clerk user_id
    requested_at            timestamptz NOT NULL DEFAULT now(),
    completed_at            timestamptz,
    status                  text NOT NULL DEFAULT 'pending',

    -- Optimizer outcome
    optimizer_status        text,                           -- optimal | suboptimal | infeasible | fallback
    solver_name             text,                           -- CLARABEL | SCS
    phase_hit               text,                           -- phase1 | phase1_5 | phase2 | phase3 | heuristic
    solver_wall_ms          integer,
    binding_constraints     jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- e.g. [{"type":"max_weight","fund":"uuid","value":0.10,"slack":0.0}, …]

    regime_context          jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- {"regime":"RISK_OFF","prob":0.82,"multiplier":0.85,"as_of":"2026-04-08"}

    -- Ex-ante metrics reported by the optimizer at solve time
    ex_ante_return          numeric(10,6),
    ex_ante_vol             numeric(10,6),
    ex_ante_cvar_95         numeric(10,6),
    ex_ante_sharpe          numeric(10,6),
    turnover_l1             numeric(10,6),
    active_share_vs_prior   numeric(6,4),

    -- Per-weight rationale (small enough to fit, one row per holding)
    rationale_per_weight    jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- [{"instrument_id":"uuid","weight_new":0.08,"weight_prior":0.05,
    --   "delta":0.03,"driver":"bl_view_override","bl_view_conviction":0.7,
    --   "binding_constraints":["max_weight"]}, …]

    narrative_markdown      text,                           -- LLM-generated explanatory paragraph

    error_message           text,

    CONSTRAINT ck_pcr_status CHECK (status IN ('pending','running','succeeded','failed')),
    CONSTRAINT ck_pcr_optimizer_status CHECK (
      optimizer_status IS NULL OR optimizer_status IN ('optimal','suboptimal','infeasible','fallback')
    )
);

CREATE INDEX ix_pcr_portfolio_requested_at ON portfolio_construction_runs (portfolio_id, requested_at DESC);
CREATE INDEX ix_pcr_portfolio_status       ON portfolio_construction_runs (portfolio_id, status);

ALTER TABLE portfolio_construction_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY pcr_rls ON portfolio_construction_runs
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

**Field source mapping** (against `backend/quant_engine/optimizer_service.py`):
- `optimizer_status`, `solver_name`, `solver_info` → `OptimizationResult.status` / `.solver_info` (line 37–44).
- `phase_hit` → derived from which of Phase 1 / 1.5 / 2 / 3 / heuristic returned. The optimizer already logs this; we need to add a return field (see §11).
- `binding_constraints` → new output the optimizer must emit (CLARABEL dual variables non-zero → constraint binding).
- `ex_ante_*` → already computed in `OptimizationResult`.
- `rationale_per_weight` → per-holding decomposition — requires a new helper in `optimizer_service.py` that compares `w_new` vs `w_prior` and attributes delta to driver (BL view, binding constraint, regime multiplier, turnover penalty). Not in the DB plan's scope to implement, but the column is shaped to receive it.

**TTL/retention:** Keep forever for `live`/`approved` portfolios; drop `failed` runs older than 90 days via a nightly cleanup (reuse `drift_check` worker's schedule to avoid a new lock). Not a hypertable — growth is ~dozens of rows per portfolio per quarter, a plain table with the two indexes above is correct.

**Relationship to `portfolio_snapshots`:** `portfolio_snapshots` remains the daily risk monitor (profile-keyed). `portfolio_construction_runs` is the event log for named portfolios. They intentionally do not share a foreign key — different axes (daily time series vs. discrete construction events).

---

## 4. Calibration parameters persistence — `portfolio_calibration` (migration 0099)

Every construction run references **exactly one** calibration row. Calibrations are versioned per portfolio; the workbench "save as preset" flow copies the row and updates `name`.

```sql
CREATE TABLE portfolio_calibration (
    id                           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id              uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id                 uuid REFERENCES model_portfolios(id) ON DELETE CASCADE,  -- nullable: org-level presets allowed
    name                         text NOT NULL,
    version                      integer NOT NULL DEFAULT 1,
    created_by                   text NOT NULL,
    created_at                   timestamptz NOT NULL DEFAULT now(),

    -- CVaR & risk budget
    cvar_target                  numeric(10,6),             -- e.g. 0.05 = 5% 1-month CVaR
    cvar_confidence              numeric(4,3) NOT NULL DEFAULT 0.95,
    regime_override              text,                      -- NULL = use detected; else RISK_ON|RISK_OFF|CRISIS|NEUTRAL

    -- Concentration / liquidity limits
    max_weight_per_fund          numeric(6,4) NOT NULL DEFAULT 0.10,
    min_weight_per_fund          numeric(6,4) NOT NULL DEFAULT 0.00,
    max_sector_weight            numeric(6,4),
    max_country_weight           numeric(6,4),
    max_single_manager_weight    numeric(6,4),

    -- Turnover
    turnover_cap                 numeric(6,4),              -- L1 cap (e.g. 0.20 = 20% one-way)
    turnover_penalty_lambda      numeric(10,6),

    -- Black-Litterman
    bl_tau                       numeric(10,6) NOT NULL DEFAULT 0.025,
    bl_view_confidence_scalar    numeric(6,4) NOT NULL DEFAULT 1.0,
    bl_use_market_prior          boolean NOT NULL DEFAULT true,

    -- Covariance estimation
    ledoit_wolf_blend            numeric(4,3),              -- NULL = auto
    cov_window_months_normal     integer NOT NULL DEFAULT 36,
    cov_window_months_stress     integer NOT NULL DEFAULT 12,

    -- Robust optimization
    robust_enabled               boolean NOT NULL DEFAULT true,
    robust_uncertainty_radius    numeric(10,6) NOT NULL DEFAULT 0.05,

    -- Stress
    stress_scenarios_enabled     text[] NOT NULL DEFAULT ARRAY['gfc','covid','taper','rate_shock']::text[],

    -- Escape hatch for experimental knobs
    extra_params                 jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT uq_portfolio_calibration_name UNIQUE (portfolio_id, name, version),
    CONSTRAINT ck_cvar_confidence CHECK (cvar_confidence BETWEEN 0.80 AND 0.999),
    CONSTRAINT ck_max_weight CHECK (max_weight_per_fund BETWEEN 0 AND 1),
    CONSTRAINT ck_regime_override CHECK (
      regime_override IS NULL OR regime_override IN ('RISK_ON','RISK_OFF','CRISIS','NEUTRAL')
    )
);

CREATE INDEX ix_calibration_portfolio ON portfolio_calibration (portfolio_id, created_at DESC);

ALTER TABLE portfolio_calibration ENABLE ROW LEVEL SECURITY;
CREATE POLICY calibration_rls ON portfolio_calibration
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

Every slider in the workbench UI must map to a named column here (not `extra_params`) so migrations remain self-documenting. `extra_params` exists only for experiments that have not yet graduated.

---

## 5. Stress test results — `portfolio_stress_results` (migration 0100)

One row per `(construction_run_id, scenario)`. Loss decomposition per holding lives in a JSONB column — the per-holding contribution array is small (~30 entries for a 30-holding portfolio).

```sql
CREATE TABLE portfolio_stress_results (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id             uuid NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
    construction_run_id      uuid NOT NULL REFERENCES portfolio_construction_runs(id) ON DELETE CASCADE,
    scenario                 text NOT NULL,
    -- built-ins: 'gfc','covid','taper','rate_shock' — user-defined scenarios get a custom label
    scenario_label           text,
    scenario_kind            text NOT NULL DEFAULT 'parametric',   -- parametric | historical | user_defined
    as_of                    date NOT NULL,
    computed_at              timestamptz NOT NULL DEFAULT now(),

    -- Top-line ex-ante impact
    portfolio_loss_pct       numeric(10,6) NOT NULL,
    portfolio_loss_usd       numeric(18,2),
    cvar_under_stress        numeric(10,6),
    max_drawdown_implied     numeric(10,6),
    recovery_days_estimate   integer,

    -- Per-holding breakdown
    loss_by_holding          jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- [{"instrument_id":"uuid","weight":0.08,"loss_pct":-0.32,"contrib_to_portfolio_loss":-0.0256}, …]

    -- Factor shocks applied (parametric)
    shock_params             jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT uq_stress_run_scenario UNIQUE (construction_run_id, scenario),
    CONSTRAINT ck_scenario_kind CHECK (scenario_kind IN ('parametric','historical','user_defined'))
);

CREATE INDEX ix_stress_portfolio_as_of ON portfolio_stress_results (portfolio_id, as_of DESC);
CREATE INDEX ix_stress_construction_run ON portfolio_stress_results (construction_run_id);

ALTER TABLE portfolio_stress_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY stress_rls ON portfolio_stress_results
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

The CLAUDE.md charter already defines four parametric scenarios (GFC, COVID, Taper, Rate Shock). The `scenario` column has no CHECK constraint on values — user-defined scenarios require freedom. The `scenario_kind` CHECK distinguishes engine-provided from user-authored.

---

## 6. Strategic / Tactical / Effective weights — `portfolio_weight_snapshots` (migration 0101)

Three vectors per day, keyed on `(portfolio_id, instrument_id, as_of)`. Hypertable because the row count is `portfolios × holdings × days` → for 50 tenants × 5 portfolios × 30 holdings × 5 years = ~13.7M rows. Query pattern: "give me all weights for portfolio X for the last 180 days" — strict time-range + portfolio equality filter, which is the classic TimescaleDB sweet spot.

```sql
CREATE TABLE portfolio_weight_snapshots (
    organization_id   uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id      uuid NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
    instrument_id     uuid NOT NULL REFERENCES instruments_universe(instrument_id),
    as_of             date NOT NULL,
    weight_strategic  numeric(8,6),
    weight_tactical   numeric(8,6),
    weight_effective  numeric(8,6),
    source            text NOT NULL DEFAULT 'eod',          -- eod | intraday | construction_run
    PRIMARY KEY (organization_id, portfolio_id, instrument_id, as_of)
);

SELECT create_hypertable(
    'portfolio_weight_snapshots',
    'as_of',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

ALTER TABLE portfolio_weight_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'portfolio_id',
    timescaledb.compress_orderby   = 'as_of DESC, instrument_id'
);

SELECT add_compression_policy('portfolio_weight_snapshots', INTERVAL '14 days');

ALTER TABLE portfolio_weight_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY pws_rls ON portfolio_weight_snapshots
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

**Chunk interval rationale:** 7 days. For 50 tenants × 5 portfolios × 30 holdings = 7,500 rows/day → 52,500 rows/chunk. Well inside the 25MB–1GB target (~10MB/chunk uncompressed). Short chunks also make the hot week-old data compress within 14 days — the workbench "last 30 days" read touches ~5 chunks.

**Segmentby `portfolio_id`:** dominant filter. Cardinality ~250 across all tenants (50 × 5) — inside the 100–100k sweet spot.

**Why not three separate tables?** One table with three nullable columns is correct because the three vectors evolve on different schedules (strategic: quarterly revisions; tactical: weekly overlays; effective: daily EOD from actual holdings). A single row can persist the full trio on days where all three are defined, and fill `NULL` on days where only effective is known. Splitting would triple the chunk count and force 3-way JOINs for every workbench chart.

**Eliminate redundancy with `strategic_allocation` / `tactical_positions`?** Not yet. Those are block-level (coarse), this is instrument-level (fine). Keep both — the old tables back the 3-profile monitor, the new hypertable backs the named-portfolio workbench. A future migration can deprecate the old ones once all call sites move.

---

## 7. Unified alerts feed — `portfolio_alerts` (migration 0102)

```sql
CREATE TABLE portfolio_alerts (
    alert_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    portfolio_id        uuid NOT NULL REFERENCES model_portfolios(id) ON DELETE CASCADE,
    alert_type          text NOT NULL,
    severity            text NOT NULL,
    title               text NOT NULL,
    payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_worker       text,                            -- 'portfolio_eval' | 'drift_check' | 'regime_fit' | …
    source_lock_id      integer,
    created_at          timestamptz NOT NULL DEFAULT now(),
    acknowledged_at     timestamptz,
    acknowledged_by     text,
    dismissed_at        timestamptz,
    dismissed_by        text,

    CONSTRAINT ck_alert_type CHECK (alert_type IN (
      'regime_change','limit_breach','drift','rebalance_suggestion',
      'stress_threshold','data_quality','price_staleness'
    )),
    CONSTRAINT ck_alert_severity CHECK (severity IN ('info','warning','critical'))
);

-- Hot-path index: unacknowledged alerts for a portfolio, newest first
CREATE INDEX ix_portfolio_alerts_open
  ON portfolio_alerts (portfolio_id, created_at DESC)
  WHERE acknowledged_at IS NULL AND dismissed_at IS NULL;

-- Cold-path index: full history
CREATE INDEX ix_portfolio_alerts_portfolio_created
  ON portfolio_alerts (portfolio_id, created_at DESC);

ALTER TABLE portfolio_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY alerts_rls ON portfolio_alerts
  USING (organization_id = (SELECT current_setting('app.current_organization_id', true)::uuid));
```

**Not a hypertable.** Expected volume: ~10 alerts per portfolio per week → ~2,500/week across 50 tenants. A plain table with a partial index is far simpler and supports the "open alerts only" filter in O(log n). Hypertable would add chunk management overhead for no benefit at this scale.

**SSE bridge:** workers write the row, then `PUBLISH` on Redis channel `portfolio:alerts:{portfolio_id}` with the new `alert_id`. SSE endpoint reads from Redis pubsub (hot path) and lazily fetches full rows from Postgres on reconnect. Redis channel is ephemeral — Postgres is the durable source of truth. This replaces the current fire-and-forget `_publish_alert` in `portfolio_eval.py` lines 138–166.

---

## 8. Live price layer (migration 0103)

**Andrei's ask:** live prices in the workbench, "fetch via nossa api" (i.e. the existing market-data providers — Yahoo Finance is current, pluggable per `instrument_ingestion` worker's architecture).

### 8.1. Options considered

| Option | Latency | Complexity | Cost | Fits workbench? |
|---|---|---|---|---|
| **(a) New worker `live_price_poll` (lock 900_100) polling Yahoo every 60s, writes Redis `live:px:{instrument_id}`** | <60s staleness | Low — mirrors `instrument_ingestion` pattern | Yahoo has no explicit rate limit but we are throttled via `ExternalProviderGate` bulk variant (5min cap). One poll every 60s across ~1500 unique live-portfolio holdings = ~25 calls/sec — too aggressive for Yahoo. | **Needs batching**: Yahoo batch quote accepts up to 250 symbols per call. At 60s cadence we need 6 batch calls → safe. |
| **(b) On-demand fetch with Redis cache + `ExternalProviderGate`** | <100ms cache hit, 500–2000ms cache miss | Medium — requires cache TTL tuning and stampede protection | Lowest — only fetches what is viewed | Good for sparse workbench sessions, bad for "50 tenants watching their portfolios simultaneously" — thundering herd on cold cache. |
| **(c) TimescaleDB hypertable `nav_intraday` with 1min chunks** | Persists history for replay | High — huge row count | Highest storage | Overkill for a workbench that does not need 1-min history. |

### 8.2. Recommendation: hybrid (a) + (b)

- **`live_price_poll` worker (lock 900_100)** — background worker polls Yahoo batch quotes every 60 seconds **only for instruments currently held by any portfolio in `live` or `paused` state** (union query against `portfolio_weight_snapshots` WHERE `as_of = CURRENT_DATE`). Writes to Redis hash `live:px:v1` with per-instrument JSON `{price, as_of_ts, source, stale}`, TTL 180s (3× poll interval, so a missed cycle still serves data until the next).
- **On-demand refresh on workbench open** — when a user opens a portfolio, the route reads Redis first. On cache miss it calls the worker's `fetch_one()` helper synchronously, gated by `ExternalProviderGate` interactive (30s). This covers the case of a newly-added holding that hasn't been picked up by the poll loop yet.
- **No new hypertable.** Live prices are ephemeral by design — intraday history is not a workbench requirement Andrei raised. If it becomes one, add `nav_intraday` later (1min chunks, segmentby `instrument_id`, compression after 7 days).

### 8.3. Stability guardrails

- `ExternalProviderGate` **bulk variant (5min)** wraps the worker's batch polling loop.
- `ExternalProviderGate` **interactive variant (30s)** wraps the on-demand fallback.
- Advisory lock via `zlib.crc32(b'live_price_poll')` — **not** `hash()` (CLAUDE.md rule, non-deterministic across processes). Or use the explicit integer literal `900_100` consistent with existing worker locks.
- Redis key versioned (`live:px:v1`) so a future schema change can cut over without flushing.
- The worker emits a `price_staleness` alert into `portfolio_alerts` if > 30% of instruments in any live portfolio have been stale > 10 minutes.

### 8.4. No DB migration for Redis keys

This section is recommendation-only — no Alembic file. The only DB artefact is the `price_staleness` enum value already included in the `portfolio_alerts` CHECK constraint in §7.

---

## 9. Required indexes (consolidated)

All indexes are declared inline in their migrations (§2–§8). Summary:

| Index | Table | Purpose | Migration |
|---|---|---|---|
| `ix_pst_portfolio_changed_at` | `portfolio_state_transitions` | Lifecycle audit trail load | 0097 |
| `ix_pcr_portfolio_requested_at` | `portfolio_construction_runs` | Sidebar of past runs | 0098 |
| `ix_pcr_portfolio_status` | `portfolio_construction_runs` | Pending/running filter | 0098 |
| `ix_calibration_portfolio` | `portfolio_calibration` | Load latest preset | 0099 |
| `uq_portfolio_calibration_name` | `portfolio_calibration` | Prevent duplicate presets | 0099 |
| `ix_stress_portfolio_as_of` | `portfolio_stress_results` | Latest stress table | 0100 |
| `ix_stress_construction_run` | `portfolio_stress_results` | Drill-down from run | 0100 |
| `uq_stress_run_scenario` | `portfolio_stress_results` | Idempotent writes | 0100 |
| (hypertable time index) | `portfolio_weight_snapshots` | Auto by Timescale | 0101 |
| `ix_portfolio_alerts_open` | `portfolio_alerts` | **Hottest** — feed shows open alerts | 0102 |
| `ix_portfolio_alerts_portfolio_created` | `portfolio_alerts` | History drawer | 0102 |

**No speculative indexes.** Every index above maps to a known workbench query. If review surfaces a chart that also filters by `severity`, add it then — not now.

---

## 10. Migration sequence (0097 → 0104)

| # | File | Content | Reversible? |
|---|---|---|---|
| 0097 | `0097_model_portfolio_lifecycle_state.py` | ALTER `model_portfolios` add state columns + CHECK; create `portfolio_state_transitions` + RLS | Yes — drop columns + table |
| 0098 | `0098_portfolio_construction_runs.py` | Create `portfolio_construction_runs` + indexes + RLS | Yes — drop table |
| 0099 | `0099_portfolio_calibration.py` | Create `portfolio_calibration` + indexes + RLS | Yes — drop table |
| 0100 | `0100_portfolio_stress_results.py` | Create `portfolio_stress_results` + indexes + RLS (depends on 0098 FK) | Yes — drop table |
| 0101 | `0101_portfolio_weight_snapshots_hypertable.py` | Create `portfolio_weight_snapshots`, call `create_hypertable`, set compression, add policy, RLS | Yes — drop policy, drop hypertable, drop table |
| 0102 | `0102_portfolio_alerts.py` | Create `portfolio_alerts` + partial index + RLS | Yes — drop table |
| 0103 | `0103_portfolio_alerts_backfill.py` | Backfill existing `strategy_drift_alerts` that correspond to portfolio holdings into `portfolio_alerts` (idempotent, keyed on `source_lock_id + dedupe_hash`) | Yes — DELETE WHERE source_worker = 'drift_check_backfill' |
| 0104 | `0104_portfolio_calibration_fk_on_construction_runs.py` | ALTER `portfolio_construction_runs` to ADD FK on `calibration_id` REFERENCES `portfolio_calibration(id)` | Yes — drop FK |

**Why is the calibration FK split into 0104?** Because 0098 needs to land before 0099 to keep migrations in dependency order for anyone reviewing (constructions are the consumer, calibration is the producer — but reading top-down, the construction table is conceptually primary). The FK is added last, once both tables exist. Alembic supports this cleanly via a follow-up migration rather than forcing a chicken-and-egg dance.

**`CREATE INDEX CONCURRENTLY`:** Alembic migrations run inside a transaction; `CONCURRENTLY` is incompatible. For prod, the three hot indexes (`ix_portfolio_alerts_open`, `ix_pcr_portfolio_requested_at`, the hypertable chunk indexes auto-created by Timescale) should be re-created manually with `CONCURRENTLY` if the tables are already large at deploy time. This is the same pattern the Discovery plan used for `0096`.

**No `DROP TABLE IF EXISTS` in downgrade** — let Alembic fail loudly on missing objects.

---

## 11. Worker changes

### 11.1. Existing workers that gain new writes

| Worker | File | Lock | New write target | Change required |
|---|---|---|---|---|
| `portfolio_eval` | `backend/app/domains/wealth/workers/portfolio_eval.py` | 900_008 | `portfolio_alerts` (replaces `_publish_alert` fire-and-forget) | On breach/warning, INSERT row, then Redis PUBLISH `portfolio:alerts:{portfolio_id}`. Keep pubsub for SSE bridging, DB is truth. |
| `drift_check` | `backend/app/domains/wealth/workers/drift_check.py` | 42 | `portfolio_alerts` | When a held instrument's drift status flips to warning/critical, write a row per portfolio holding that instrument, `alert_type='drift'`, payload includes the `strategy_drift_alerts.id` for drill-down. |
| `regime_fit` | `backend/app/domains/wealth/workers/regime_fit.py` (currently uncommitted per git status) | TBD — confirm existing lock | `portfolio_alerts` | On regime transition (detected_regime != previous), emit `regime_change` alert to every `live` portfolio. |
| `portfolio_nav_synthesizer` | `backend/app/domains/wealth/workers/portfolio_nav_synthesizer.py` | 900_030 | `portfolio_weight_snapshots` (effective column only) | After computing daily NAV, also upsert the effective weight vector (what the synthesizer already uses internally — one new INSERT per holding). Strategic/tactical columns left NULL; they are written by separate flows (IC view acceptance, manual overlay). |
| `risk_calc` | `backend/app/domains/wealth/workers/risk_calc.py` | 900_007 | (unchanged) | No new writes. Still overlays DTW drift on `fund_risk_metrics`. |
| `global_risk_metrics` | (worker file) | 900_071 | (unchanged) | GLOBAL ownership of `fund_risk_metrics` intact. |

### 11.2. New workers

| Worker | Lock ID | Schedule | Responsibility |
|---|---|---|---|
| `live_price_poll` | **900_100** | Every 60s (or on-demand invocation) | §8 — batch-poll Yahoo for instruments held by `live`/`paused` portfolios; write Redis `live:px:v1`; emit `price_staleness` alert if stale. |
| `construction_run_executor` | **900_101** | On-demand (triggered by `POST /portfolios/{id}/construct`) | Wraps the optimizer cascade. Writes `portfolio_construction_runs` (status `running` → `succeeded`/`failed`), populates `binding_constraints`, `phase_hit`, `rationale_per_weight`. Downstream triggers stress suite which writes `portfolio_stress_results`. |
| `alert_sweeper` | **900_102** | Hourly | Marks stale open alerts as auto-dismissed after configurable window (`payload.auto_dismiss_after`), keeps the open-alerts index small. |

**Lock ID allocation** — 900_100, 900_101, 900_102 are unused per CLAUDE.md's worker table (highest current is 900_082). Reserve them here. All three use `pg_try_advisory_lock(ID)` with `ID` passed as an integer literal (not `hash()`, not `zlib.crc32` on a string — matches the existing pattern in `portfolio_eval.py` line 266).

---

## 12. Stability guardrails mapping

| Principle | Where it applies in this design |
|---|---|
| **P1 Bounded** | `live_price_poll` batches Yahoo calls in groups of 250 symbols (max), `construction_run_executor` enforces a 120s wall-clock cap and writes `failed` status on timeout. |
| **P2 Batched** | `portfolio_nav_synthesizer` upserts `portfolio_weight_snapshots` via `execute_many` on the full holding list per portfolio (one round trip per portfolio, not per holding). |
| **P3 Isolated** | All new tables RLS-scoped with the subselect pattern. `fund_risk_metrics` untouched (GLOBAL, RLS disabled — memory confirms). |
| **P4 Lifecycle** | State machine in §2 is the literal implementation. |
| **P5 Idempotent** | `portfolio_construction_runs` keyed on UUID PK generated server-side; `portfolio_stress_results` has `UNIQUE (construction_run_id, scenario)` so stress re-runs upsert cleanly; `portfolio_alerts` dedupe via `(portfolio_id, alert_type, payload->>'dedupe_key')` check in application code before insert. |
| **P6 Fault-Tolerant** | `live_price_poll` wraps Yahoo calls in `ExternalProviderGate` bulk (5min), on-demand fallback uses interactive (30s). Circuit breaker on 3 consecutive failures → emit `data_quality` alert, serve stale data with `stale=true` flag. |
| **Advisory locks** | 900_100/101/102 use integer literals. String-keyed locks (none in this plan) would require `zlib.crc32`, never `hash()`. |
| **`SET LOCAL`** | All workers already wrap their session in `set_rls_context(db, org_id)` which issues `SET LOCAL` — confirmed in `portfolio_eval.py` line 264. |
| **`lazy="raise"` + `expire_on_commit=False`** | All new models (following the pattern in `model_portfolio.py` and `portfolio.py`) use `OrganizationScopedMixin` + explicit `selectinload`/`joinedload` — no lazy IO. |

---

## 13. Gaps, risks, open questions for Andrei

1. **Profile vs. portfolio_id rollover.** The plan deliberately keeps `strategic_allocation` / `tactical_positions` / `portfolio_snapshots` alive because they back the current 3-profile CVaR monitor and the `portfolio_eval` worker. Long-term we should migrate the monitor onto `portfolio_weight_snapshots` and retire the profile-keyed tables — but that is a separate sprint. **Q: confirm that dual-table coexistence for 1–2 quarters is acceptable, or do you want a hard cutover inside this migration set?**

2. **`ModelPortfolio.status` legacy column.** Kept alongside the new `state` column. **Q: drop it immediately (forces all call sites to migrate in one PR) or defer to a 01xx cleanup migration?** My recommendation is defer — cleaner audit trail.

3. **`rationale_per_weight` generation.** The schema is ready, but producing meaningful per-holding rationale requires optimizer instrumentation (CLARABEL dual values → binding constraints → attribution). This is a **quant engine task outside the DB layer** and is listed here only so the column doesn't surprise reviewers.

4. **Live price provider.** Plan assumes Yahoo Finance batch quote (same provider as `instrument_ingestion`). **Q: confirm, or are you integrating a paid real-time feed (Refinitiv / Polygon) that would change the rate-limit math in §8?**

5. **Intraday history.** §8 explicitly does **not** add an `nav_intraday` hypertable. **Q: confirm you do not need intraday history in the workbench (only "current price"). If you do, I'll add `nav_intraday` with 1min chunks, segmentby `instrument_id`, compression after 7 days as migration 0105.**

6. **Stress scenario authoring.** `portfolio_stress_results` supports user-defined scenarios (`scenario_kind = 'user_defined'`) but there is no table storing the scenario *definition*. If users build custom shocks in the UI, we need a `portfolio_stress_scenarios` catalog table. **Q: scope this sprint or defer?** Recommendation: defer — ship the 4 parametric scenarios first, add custom later.

7. **Alert dedup key.** `portfolio_alerts` dedups via `payload->>'dedupe_key'` in application code. A DB-level UNIQUE partial index would be stricter but harder to index on a JSONB expression efficiently. **Q: accept app-level dedup or want a materialized `dedupe_key text` column + UNIQUE (portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL?** Recommendation: materialized column — one more column is cheap, stronger guarantee.

8. **Portfolio-scoped drift alerts vs instrument-scoped.** `strategy_drift_alerts` is instrument-keyed (one row per instrument per detection). For the workbench alert feed we want portfolio-scoped rows. The backfill in migration 0103 fans out instrument alerts to every portfolio holding that instrument, which means N rows per drift event for N portfolios. **Q: acceptable or do you want alerts to remain instrument-centric with a join at query time?** Recommendation: fanout is correct — the open-alerts hot-path index in §7 assumes portfolio_id equality, joining would regress that.

9. **Retention.** No retention policy on `portfolio_construction_runs`, `portfolio_stress_results`, `portfolio_alerts`. Data volume projected to stay under 10M rows across all three for years — plain B-tree indexes remain fast. Revisit at 10M rows per table. `portfolio_weight_snapshots` has compression after 14 days but **no drop retention** — we want the full history for attribution. **Q: confirm.**

10. **CLAUDE.md migration head is stale** (0095 vs actual 0096). Update in a separate docs commit alongside this plan's first migration.

---

**End of design document.** Total new tables: 6 (`portfolio_state_transitions`, `portfolio_construction_runs`, `portfolio_calibration`, `portfolio_stress_results`, `portfolio_weight_snapshots`, `portfolio_alerts`). New hypertables: 1. New worker lock IDs reserved: 900_100, 900_101, 900_102. Migration range: 0097–0104. All reversible, all RLS-compliant with subselect pattern, zero changes to `fund_risk_metrics` ownership semantics.
