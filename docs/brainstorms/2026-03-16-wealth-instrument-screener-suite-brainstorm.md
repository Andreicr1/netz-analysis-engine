# Brainstorm: Wealth Instrument Screener Suite

**Date:** 2026-03-16
**Status:** Ready for planning
**Vertical:** Wealth Management (`liquid_funds`)

---

## The Gap

The platform handles **post-submission** analysis (DD Report -> Universe Approval) but has **zero pre-submission triage**. The current flow:

```
Human decides to submit fund -> DD Report -> UniverseApproval
```

What's missing is the funnel before that:

```
Market universe (thousands) -> [DETERMINISTIC SCREENING] -> Candidate list -> DD Report -> Approval
```

Without automated screening, the platform depends on ad-hoc human judgment to decide which instruments enter the pipeline — exactly what the system should automate.

Additionally, the platform is fund-only. Institutional wealth managers also hold **bonds** (sovereign, corporate, municipal) and **equities** (direct positions, not just via funds). The data model must generalize.

---

## What We're Building

A suite of 6 engines that complete the wealth management analytical loop:

| # | Engine | Purpose | Sprint |
|---|--------|---------|--------|
| 1 | **Screener Engine** | Deterministic multi-layer triage of market instruments | Sprint 1 |
| 2 | **Peer Group Engine** | Automatic peer identification and percentile ranking | Sprint 2 |
| 3 | **Rebalancing Engine** | Impact analysis and weight adjustment proposals | Sprint 3 |
| 4 | **Watchlist Monitoring Engine** | Periodic re-evaluation of watchlisted instruments | Sprint 4 |
| 5 | **Mandate Fit Engine** | Client-specific eligibility from approved universe | Sprint 5 |
| 6 | **Fee Drag Calculator** | Net fee impact on expected returns | Sprint 5 |

Foundation work (Sprint 1): **instruments_universe** polymorphic data model + **YahooFinanceProvider** + migration from `funds_universe`.

---

## Key Decisions

### D1: Data Model — Single Polymorphic Table with JSONB

**Decision:** One `instruments_universe` table with typed JSONB `attributes`.

**Why:** Tabelas separadas por tipo forçam UNION em queries cross-type (screener filtra "todos os instrumentos de renda fixa por geografia" constantemente). Herança com tabela base cria JOINs obrigatórios e complica RLS. JSONB com `extra="allow"` is the established pattern (PolicyThresholds, calibration seeds).

**Schema:**

```sql
CREATE TABLE instruments_universe (
    instrument_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id   TEXT NOT NULL,              -- RLS multi-tenant

    -- Common fields (always present, indexable)
    instrument_type   TEXT NOT NULL,              -- 'fund' | 'bond' | 'equity'
    name              TEXT NOT NULL,
    isin              TEXT,
    ticker            TEXT,
    bloomberg_ticker  TEXT,
    asset_class       TEXT NOT NULL,              -- equity | fixed_income | alternatives
    geography         TEXT NOT NULL,              -- US | EU | EM_ASIA | GLOBAL
    currency          TEXT NOT NULL DEFAULT 'USD',
    block_id          TEXT,                       -- FK -> AllocationBlock (base field, NOT JSONB)
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    approval_status   TEXT NOT NULL DEFAULT 'pending',

    -- Type-specific attributes: schema-free JSONB
    attributes        JSONB NOT NULL DEFAULT '{}',

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_instrument_org UNIQUE (instrument_id, organization_id)
);

-- GIN for JSONB queries (screener uses ->> extensively)
CREATE INDEX ix_instruments_attributes ON instruments_universe USING GIN (attributes);

-- Partial index by type (screener filters heavily by type + org)
CREATE INDEX ix_instruments_type_active
    ON instruments_universe (instrument_type, organization_id, asset_class)
    WHERE is_active = TRUE;

-- RLS
ALTER TABLE instruments_universe ENABLE ROW LEVEL SECURITY;
CREATE POLICY instruments_org_isolation ON instruments_universe
    USING (organization_id = (SELECT current_setting('app.current_organization_id')));
```

**`block_id` in base table, not JSONB:** Used in allocation queries constantly (model portfolio builder, rebalancing engine, screener mandate filters). JSONB would prevent efficient indexing.

### D2: JSONB Attributes by Instrument Type

**Fund attributes:**
```yaml
aum_usd, manager_name, manager_aum_usd, inception_date, domicile,
structure (UCITS | Cayman LP | Delaware LP | SICAV),
liquidity_days, lock_up_months, management_fee_pct, performance_fee_pct,
hurdle_rate_pct, high_water_mark, strategy (long_only | long_short | market_neutral),
benchmark, esg_compliant, sfdr_article (null | 6 | 8 | 9)
```

**Bond attributes:**
```yaml
issuer_name, issuer_type (sovereign | corporate | municipal | supranational),
credit_rating_sp, credit_rating_moodys, credit_rating_fitch, is_investment_grade,
yield_to_maturity_pct, coupon_rate_pct, coupon_frequency, maturity_date,
duration_years, convexity, face_value_usd, outstanding_usd, callable,
seniority (senior_secured | senior | subordinated | mezzanine), sector
```

**Equity attributes:**
```yaml
market_cap_usd, sector (GICS), industry (GICS), country_of_domicile, exchange,
pe_ratio_ttm, pe_ratio_forward, pb_ratio, ev_ebitda, dividend_yield_pct,
roe_pct, debt_to_equity, free_float_pct, avg_daily_volume_usd, beta,
short_interest_pct, 52w_high, 52w_low, index_membership (list), esg_score
```

### D3: Data Source — YahooFinanceProvider (Sprint 1) -> Lipper (Production)

**Decision:** `yfinance` as v1 provider with adapter pattern for future migration.

**Coverage:**
- **Equities:** Excellent — prices, fundamentals (P/E, P/B, ROE, market cap), sector/industry via GICS, exchange, country. Historical data for Sharpe/drawdown/volatility.
- **ETFs/Funds:** Good — NAV history, expense ratio, Morningstar category, approximate AUM. No complete holdings for active funds.
- **Bonds:** Limited but functional — US treasuries, some corporate bonds via ticker. Yield and current price. CSV import complements for bonds.

**Known limitations requiring Lipper migration:**

| Limitation | Screener Impact | Lipper Resolves |
|---|---|---|
| No complete fund holdings | Layer 2 incomplete | Yes |
| No bond credit ratings | Layer 1 incomplete | Yes |
| Partial UCITS coverage | Reduced European universe | Yes |
| No liquidity_days for funds | Field absent | Yes |
| Rate limit ~2000 req/hour | Slow batch import | Yes (bulk) |
| **ToS prohibits commercial use** | **Legal risk in production** | **Yes** |

**Migration path:** `InstrumentDataProvider` protocol. `YahooFinanceProvider` -> `LipperProvider` swap changes zero screener engine code.

**Sprint 1 enrichment:** OpenFIGI resolver for ISIN -> ticker before calling Yahoo.

### D4: Quant Metrics — New `instrument_risk_metrics` Table

**Decision:** Separate table for screening metrics. Existing `nav_timeseries` and `fund_risk_metrics` stay as-is for approved fund portfolio analytics.

```sql
CREATE TABLE instrument_risk_metrics (
    instrument_id   UUID NOT NULL REFERENCES instruments_universe(instrument_id),
    calc_date       DATE NOT NULL,
    metrics         JSONB NOT NULL,  -- {sharpe_ratio, annual_vol_pct, max_drawdown_pct, ...}
    source          TEXT NOT NULL,   -- 'yahoo_finance' | 'lipper' | 'computed'
    data_period_days INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, calc_date)
);
```

**Why separate:**
- Screening metrics cover ALL instruments (thousands); portfolio metrics cover only approved instruments (tens).
- Different calculation methodology may apply (screening uses provider history; portfolio uses nav_timeseries with controlled data quality).
- Clear ownership: screener writes `instrument_risk_metrics`; quant_engine writes `fund_risk_metrics`.

### D5: Screening Trigger — Batch Weekly + On-Demand

**Decision:** Cron job (weekly) for full universe re-screening + on-demand endpoint for individual instruments.

- **Weekly batch:** Re-screens entire universe. Updates scores, detects status changes (AUM drop below threshold, rating downgrade). Runs via Redis job queue.
- **On-demand:** Single instrument screening after import or manual request. Returns `ScreeningResult` synchronously.
- **No event-driven for v1:** Adds pub/sub complexity without proportional value. Weekly batch is the safety net.

### D6: Screening Config — Per-Tenant + Per-Block

**Decision:** Three-level config granularity matching screening layers:

- **Layer 1 (Eliminatory):** Global per tenant. Stored as `ConfigService.get("liquid_funds", "screening_layer1", org_id)`.
- **Layer 2 (Mandate fit):** Per AllocationBlock. Reuses existing block structure (already has geography, asset_class). Stored as nested config keyed by `block_id`.
- **Layer 3 (Quant score):** Weights global per tenant. Stored as `ConfigService.get("liquid_funds", "screening_layer3", org_id)`.

**Config example:**
```yaml
# screening_criteria (config_type in ConfigService)
layer1:
  fund:
    min_aum_usd: 100_000_000
    min_track_record_years: 3
    allowed_domiciles: [IE, LU, KY, US]
    allowed_structures: [UCITS, Cayman_LP, Delaware_LP, SICAV]
  bond:
    min_credit_rating: BBB-          # investment grade floor
    min_remaining_maturity_years: 1
    min_outstanding_usd: 50_000_000
  equity:
    min_market_cap_usd: 1_000_000_000
    allowed_exchanges: [NYSE, NASDAQ, LSE, XETRA, TSE]
    min_free_float_pct: 25
    excluded_sectors: []              # ESG blacklist

layer2:
  by_block:
    US_EQUITY:
      asset_class: equity
      geography: US
      max_pe_ratio: 40
      min_dividend_yield_pct: 0
    GLOBAL_FI:
      asset_class: fixed_income
      max_duration_years: 10
      min_yield_pct: 3.0
    ALTERNATIVES:
      allowed_strategies: [long_short, market_neutral]
      max_management_fee_pct: 2.0
      max_performance_fee_pct: 20.0

layer3:
  fund:
    weights:
      sharpe_ratio: 0.30
      max_drawdown: 0.25
      pct_positive_months: 0.20
      correlation_diversification: 0.25
    min_data_period_days: 756       # ~3 years
  bond:
    weights:
      spread_vs_benchmark: 0.40
      liquidity_score: 0.30
      duration_efficiency: 0.30
  equity:
    weights:
      pe_relative_sector: 0.25
      roe: 0.25
      debt_equity: 0.20
      momentum_score: 0.30
```

### D7: Analysis Requirements — Nullable with Conditional Validation

**Decision:** `dd_report_id` in `UniverseApproval` becomes nullable (`analysis_report_id`). Validation is in the service layer, not DB constraints.

**Rules by type:**
- **Funds + Equities:** Full DD Report required (`REQUIRES_FULL_DD`)
- **Bonds:** Bond Brief (2-page report) required (`REQUIRES_BOND_BRIEF`)
- **Bond Brief** reuses `dd_reports` table with `report_type = 'bond_brief'` and 2 fixed chapters: `instrument_overview` + `key_metrics`

### D8: Peer Group Engine — Configurable by Instrument Type

**Decision:** Peer group criteria defined per `instrument_type` in ConfigService.

- **Funds:** block + strategy + AUM range
- **Bonds:** issuer_type + rating range + duration range
- **Equities:** sector + market_cap range

Peer comparison calculates percentile rankings within the group. Enriches DD Reports with real comparative data.

---

## Engine Designs (High-Level)

### Engine 1: Screener Engine (Sprint 1)

Fully deterministic — no LLM, no probability. Applies objective criteria in layers over structured data. Returns ranked candidate list.

**Architecture:**
```
vertical_engines/wealth/screener/
    service.py              -- entry point: screen_universe(), screen_instrument()
    layer_evaluator.py      -- evaluates one layer of criteria against one instrument
    quant_metrics.py        -- compute_quant_metrics() from price history
    models.py               -- CriterionResult, ScreeningResult, QuantMetrics
```

**Data flow:**
```
instruments_universe
    -> Layer 1 (eliminatory): any FAIL = discard, stop
    -> Layer 2 (mandate fit per block): any FAIL = discard, stop
    -> Layer 3 (quant score): compute score 0.0-1.0, rank
    -> ScreeningResult per instrument:
         status: PASS | FAIL | WATCHLIST
         score: 0.0-1.0 (only for PASS)
         layer_results: {layer: [CriterionResult]}
         failed_at_layer: 1 | 2 | 3 | None
         required_analysis_type: 'dd_report' | 'bond_brief' | 'none'
```

**Watchlist logic:** Instrument passes Layer 1 but fails Layer 2 by narrow margin (configurable threshold) -> WATCHLIST status instead of FAIL.

### Engine 2: Peer Group Engine (Sprint 2)

Given an approved instrument, automatically identifies the correct peer group and calculates percentile rankings.

**Architecture:**
```
vertical_engines/wealth/peer_group/
    service.py              -- find_peers(), compute_rankings()
    peer_matcher.py         -- peer group identification by type
    models.py               -- PeerGroup, PeerRanking
```

**Peer criteria by type (configurable via ConfigService):**
- **Funds:** Same block + similar strategy + AUM within 0.5x-2x range
- **Bonds:** Same issuer_type + rating within 2 notches + duration within +/- 2y
- **Equities:** Same GICS sector + market_cap within same tier (mega/large/mid/small)

**Output:** Percentile rank on key metrics (return, risk-adjusted return, volatility, Sharpe). Injected into DD Reports and fact sheets.

### Engine 3: Rebalancing Engine (Sprint 3)

When an instrument is removed (`deactivate_asset`) or regime changes, calculates impact on model portfolios and proposes weight adjustments.

**Architecture:**
```
vertical_engines/wealth/rebalancing/
    service.py              -- compute_rebalance_impact(), propose_adjustments()
    impact_analyzer.py      -- what happens if instrument X is removed
    weight_proposer.py      -- redistribution logic
    models.py               -- RebalanceImpact, WeightProposal
```

**Connects existing pieces:**
- `DeactivationResult.rebalance_needed` flag (already exists, currently goes nowhere)
- `RebalanceEvent` records (already in rebalance_service.py)
- `StrategicAllocation` targets (block weight targets with min/max bounds)
- `PortfolioSnapshot` current state

**Logic:**
1. Identify affected model portfolios (which portfolios hold the removed instrument?)
2. Calculate weight gap (how much weight needs redistribution?)
3. Propose redistribution: pro-rata to remaining instruments in same block, respecting min/max bounds
4. Flag if redistribution violates CVaR limits (calls `cvar_service.compute_cvar_from_returns()`)

### Engine 4: Watchlist Monitoring Engine (Sprint 4)

Periodic engine that re-evaluates screening criteria on watchlisted instruments.

**Architecture:**
```
vertical_engines/wealth/watchlist/
    service.py              -- monitor_watchlist(), evaluate_transitions()
    transition_detector.py  -- detects WATCHLIST -> PASS or WATCHLIST -> FAIL
    models.py               -- WatchlistAlert, TransitionEvent
```

**Logic:**
1. Weekly job (same cadence as screener batch)
2. Re-runs screener criteria on all `approval_status = 'watchlist'` instruments
3. Detects transitions:
   - **Improvement:** Was WATCHLIST, now passes all layers -> Alert: "candidate for DD initiation"
   - **Deterioration:** Was WATCHLIST, now fails Layer 1 -> Alert: "candidate for removal"
   - **Stable:** No change -> No alert
4. Publishes alerts via Redis pub/sub (existing SSE infrastructure)

### Engine 5: Mandate Fit Engine (Sprint 5)

Given a client profile (risk tolerance, objectives, ESG constraints, tax domicile), calculates which instruments from the approved universe are eligible.

**Architecture:**
```
vertical_engines/wealth/mandate_fit/
    service.py              -- compute_eligible_instruments()
    constraint_evaluator.py -- evaluates client constraints against instrument attributes
    models.py               -- ClientProfile, MandateConstraints, EligibilityResult
```

**Logic:**
- Client profile defines: risk bucket (conservative/moderate/growth), ESG requirements (SFDR article floor), domicile restrictions (withholding tax optimization), liquidity requirements, sector exclusions
- Filters approved universe by client constraints
- Returns eligible instruments with suitability score

### Engine 6: Fee Drag Calculator (Sprint 5)

Given a portfolio with N instruments, calculates net fee impact on expected returns.

**Architecture:**
```
vertical_engines/wealth/fee_drag/
    service.py              -- compute_fee_impact()
    models.py               -- FeeDragResult, InstrumentFeeAnalysis
```

**Logic:**
- For each instrument: `gross_expected_return - management_fee - performance_fee_estimate = net_return`
- Performance fee estimate uses high water mark and hurdle rate if applicable
- Identifies instruments where fee is structurally high for delivered return (fee_drag_ratio)
- Aggregates portfolio-level fee drag
- Direct input for fee negotiation with managers

---

## Migration Plan (Sprint 1 Foundation)

Migration `0010_instruments_universe`:

1. **CREATE** `instruments_universe` (schema above)
2. **INSERT INTO** `instruments_universe` SELECT from `funds_universe` (data migration with JSONB construction)
3. **ALTER** `universe_approvals`: rename `fund_id` -> `instrument_id`, rename `dd_report_id` -> `analysis_report_id`, drop NOT NULL on `analysis_report_id`
4. **ALTER** `dd_reports`: rename `fund_id` -> `instrument_id`, add `report_type TEXT NOT NULL DEFAULT 'dd_report'`
5. **CREATE** `instrument_risk_metrics` table
6. **CREATE** indexes (GIN, partial)
7. **DROP** `funds_universe` (after rowcount assertion)

**Impact on existing code:**
- `universe_service.py`: Add `instrument_type = 'fund'` as default filter to preserve current behavior
- `list_universe()`: Works as-is with type filter
- All wealth routes referencing `fund_id`: Rename to `instrument_id`
- Screener is a new package — no modification to existing code

---

## Sprint Sequence

```
Sprint 1A: instruments_universe migration + YahooFinanceProvider + normalizador + OpenFIGI enricher
Sprint 1B: Screener Engine Layers 1 + 2 (deterministic, no quant)
Sprint 1C: Screener Layer 3 (quant metrics via Yahoo history) + instrument_risk_metrics
Sprint 1D: Batch weekly job + on-demand endpoint + CSV import adapter

Sprint 2:  Peer Group Engine (configurable by type, enriches DD Reports)
Sprint 3:  Rebalancing Engine (closes operational loop, connects deactivate_asset)
Sprint 4:  Watchlist Monitoring Engine (periodic re-evaluation, SSE alerts)
Sprint 5:  Mandate Fit Engine + Fee Drag Calculator (client sophistication)

Future:    LipperProvider replaces YahooFinanceProvider (zero screener changes)
```

---

## Why This Approach

1. **Polymorphic table:** Avoids UNION hell for cross-type queries. GIN index on JSONB gives fast attribute filtering. Established pattern in the codebase.
2. **Deterministic screener:** No LLM, no probability. Objective criteria on structured data. Auditable, reproducible, fast. ConfigService makes it tenant-customizable.
3. **Layered evaluation with early exit:** Layer 1 failure = immediate discard. No wasted compute on Layer 2/3 for clearly ineligible instruments.
4. **Provider abstraction:** yfinance for v1 validation, Lipper for production. Swap is transparent to the engine.
5. **Separate screening metrics:** `instrument_risk_metrics` keeps screening data separate from portfolio analytics (`fund_risk_metrics`). Different lifecycle, different ownership.
6. **Per-block mandate config:** Reuses AllocationBlock structure already in place. Natural granularity for Layer 2 filtering.

---

## Open Questions

*None — all design questions resolved during brainstorm.*

---

## Resolved Questions

1. **Data model approach?** -> Single polymorphic table with JSONB (D1)
2. **Data source for v1?** -> yfinance with InstrumentDataProvider protocol (D3)
3. **NavTimeseries/FundRiskMetrics generalization?** -> New instrument_risk_metrics table, existing tables unchanged (D4)
4. **Screening trigger model?** -> Batch weekly + on-demand (D5)
5. **Config granularity?** -> Per-tenant Layer 1/3, per-block Layer 2 (D6)
6. **Analysis requirements for bonds?** -> Nullable analysis_report_id, Bond Brief (2-page) for bonds (D7)
7. **Peer group definition?** -> Configurable criteria per instrument_type (D8)
8. **Brainstorm scope?** -> All 6 engines documented, Sprint 1 focuses on Screener + foundation
