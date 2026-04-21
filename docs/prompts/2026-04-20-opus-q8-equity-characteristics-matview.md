---
pr_id: PR-Q8
title: "feat(quant/equity-chars): equity_characteristics_monthly from sec_xbrl_facts"
branch: feat/equity-characteristics-matview
sprint: S4
dependencies: [PR-Q7]
loc_estimate: 450
reviewer: data-platform
---

# Opus Prompt — PR-Q8: Equity Characteristics (XBRL-sourced)

## Goal

Derive the 6 Kelly-Pruitt-Su characteristics (size, book-to-market, momentum 12-1, ROA quality, investment growth, gross profitability) from `sec_xbrl_facts` (shipped in PR-Q7) + `nav_timeseries` into a new hypertable `equity_characteristics_monthly`. This is the input panel for PR-Q9 G5 IPCA.

**Source change vs original draft:** this prompt was rewritten after the PR-Q7 pivot from Tiingo Fundamentals (paid add-on, not activated) to SEC XBRL Company Facts bulk (local). All source joins, universe resolution, and concept naming now use `sec_xbrl_facts` (tall, CIK-keyed, us-gaap concepts with point-in-time `accn`/`filed`).

## Spec references (READ FIRST)

- `docs/prompts/2026-04-20-opus-q7-sec-xbrl-companyfacts-worker.md` — upstream hypertable shape (PK `(cik, taxonomy, concept, unit, period_end, accn)`, restatements preserved)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §6 (characteristics target DDL — still valid for the downstream shape)
- `CLAUDE.md` §Data Ingestion Workers, §Stability Guardrails, §Critical Rules (global tables, advisory locks, `zlib.crc32`)
- `backend/app/core/jobs/global_risk_metrics.py` (lock 900_071) — reference for worker that computes analytical features across `instruments_universe`
- Kelly, Pruitt, Su (2019) "Characteristics are covariances" — theoretical anchor for the 6 features

## Files to create

### Migration

1. `backend/app/core/db/migrations/versions/0167_equity_characteristics_monthly.py`
   - `equity_characteristics_monthly` hypertable:
     - `instrument_id UUID NOT NULL` (FK to `instruments_universe.instrument_id`, no CASCADE — catalog rows are immutable)
     - `cik BIGINT NOT NULL` (denormalised for query convenience)
     - `ticker TEXT NOT NULL` (denormalised at compute time; frozen per row)
     - `month_end DATE NOT NULL`
     - Six characteristic columns (all NUMERIC, nullable):
       - `size` (ln market cap)
       - `book_to_market`
       - `momentum_12_1`
       - `quality_roa_ttm`
       - `investment_growth_yoy`
       - `profitability_gross`
     - Inputs used (store for audit / regeneration): `market_cap_usd NUMERIC`, `stockholders_equity NUMERIC`, `total_assets NUMERIC`, `total_assets_lag_12m NUMERIC`, `net_income_ttm_usd NUMERIC`, `revenues_ttm_usd NUMERIC`, `gross_profit_ttm_usd NUMERIC`, `cost_of_revenue_ttm_usd NUMERIC`, `shares_outstanding NUMERIC`
     - Audit: `source_accn_map JSONB` — `{concept: accn}` mapping of which filing was the point-in-time source for each balance-sheet/income-statement input
     - `computed_at TIMESTAMPTZ NOT NULL DEFAULT now()`
     - PK: `(instrument_id, month_end)`
   - `SELECT create_hypertable('equity_characteristics_monthly', 'month_end', chunk_time_interval => INTERVAL '2 years', if_not_exists => TRUE);`
   - Indexes:
     - `(cik, month_end DESC)`
     - `(month_end DESC)` — for cross-sectional IPCA pulls
   - Compression: `timescaledb.compress_segmentby = 'instrument_id'`, `compress_orderby = 'month_end DESC'`, policy at 1 year.
   - Global table (no RLS) — same rationale as `fund_risk_metrics`, `sec_xbrl_facts`: pre-computed shared analytics.
   - `downgrade()` drops hypertable cleanly.

### Pure derivation module

2. `backend/app/domains/wealth/services/characteristics_derivation.py`

   Keep pure (no DB, no I/O). Exports:

   ```python
   from dataclasses import dataclass
   from datetime import date
   from decimal import Decimal

   @dataclass(frozen=True, slots=True)
   class CharacteristicInputs:
       market_cap_usd: Decimal | None
       stockholders_equity: Decimal | None
       total_assets: Decimal | None
       total_assets_lag_12m: Decimal | None
       net_income_ttm: Decimal | None
       revenues_ttm: Decimal | None
       gross_profit_ttm: Decimal | None
       cost_of_revenue_ttm: Decimal | None
       nav_series: "pd.Series"  # month-end NAV, indexed by date

   @dataclass(frozen=True, slots=True)
   class Characteristics:
       size: float | None
       book_to_market: float | None
       momentum_12_1: float | None
       quality_roa_ttm: float | None
       investment_growth_yoy: float | None
       profitability_gross: float | None

   def derive_size(market_cap_usd) -> float | None: ...
   def derive_book_to_market(stockholders_equity, market_cap_usd) -> float | None: ...
   def derive_momentum_12_1(nav_series, as_of) -> float | None: ...
   def derive_quality_roa(net_income_ttm, total_assets) -> float | None: ...
   def derive_investment_growth(total_assets_now, total_assets_lag_12m) -> float | None: ...
   def derive_profitability_gross(gross_profit_ttm, revenues_ttm, cost_of_revenue_ttm) -> float | None: ...

   def compute_characteristics(inputs: CharacteristicInputs, as_of: date) -> Characteristics: ...
   ```

   Formulas unchanged from the original spec (the math is taxonomy-agnostic):

   ```python
   def derive_size(market_cap_usd):
       if market_cap_usd is None or market_cap_usd <= 0:
           return None
       return float(math.log(float(market_cap_usd)))

   def derive_book_to_market(stockholders_equity, market_cap_usd):
       if None in (stockholders_equity, market_cap_usd) or market_cap_usd <= 0:
           return None
       return float(Decimal(stockholders_equity) / Decimal(market_cap_usd))

   def derive_momentum_12_1(nav_series, as_of):
       window = nav_series.loc[:as_of].iloc[-13:-1]
       if len(window) < 11:
           return None
       return float(window.iloc[-1] / window.iloc[0] - 1)

   def derive_quality_roa(net_income_ttm, total_assets):
       if None in (net_income_ttm, total_assets) or total_assets <= 0:
           return None
       return float(Decimal(net_income_ttm) / Decimal(total_assets))

   def derive_investment_growth(total_assets_now, total_assets_lag_12m):
       if None in (total_assets_now, total_assets_lag_12m) or total_assets_lag_12m <= 0:
           return None
       return float(Decimal(total_assets_now) / Decimal(total_assets_lag_12m) - 1)

   def derive_profitability_gross(gross_profit_ttm, revenues_ttm, cost_of_revenue_ttm):
       if revenues_ttm is None or revenues_ttm <= 0:
           return None
       if gross_profit_ttm is not None:
           return float(Decimal(gross_profit_ttm) / Decimal(revenues_ttm))
       if cost_of_revenue_ttm is not None:
           return float((Decimal(revenues_ttm) - Decimal(cost_of_revenue_ttm)) / Decimal(revenues_ttm))
       return None
   ```

### XBRL point-in-time fetcher

3. `backend/app/domains/wealth/services/xbrl_pit_fetcher.py`

   The hard part of this PR. Translates "what did the market know at `as_of`" into SQL against `sec_xbrl_facts`. Pure-ish module (takes an `AsyncConnection`, returns dataclasses).

   Concept mapping (us-gaap — and alternates where taxonomy evolved):

   | Input | Primary concept | Alternates (try in order) |
   |---|---|---|
   | `stockholders_equity` (instant) | `StockholdersEquity` | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
   | `total_assets` (instant) | `Assets` | — |
   | `net_income_quarterly` (duration) | `NetIncomeLoss` | `ProfitLoss` |
   | `revenues_quarterly` (duration) | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, `SalesRevenueGoodsNet` |
   | `gross_profit_quarterly` (duration) | `GrossProfit` | — (fallback computed downstream) |
   | `cost_of_revenue_quarterly` (duration) | `CostOfRevenue` | `CostOfGoodsAndServicesSold`, `CostOfGoodsSold` |
   | `shares_outstanding` (instant, unit=shares) | `CommonStockSharesOutstanding` | `dei:EntityCommonStockSharesOutstanding` (taxonomy=`dei`, concept=`EntityCommonStockSharesOutstanding`) |

   Point-in-time selection pattern (apply to every instant concept):

   ```sql
   SELECT DISTINCT ON (concept, unit)
     concept, unit, period_end, val, accn, filed
   FROM sec_xbrl_facts
   WHERE cik = :cik
     AND taxonomy = :taxonomy
     AND concept = ANY(:candidates)
     AND unit = :unit
     AND filed <= :as_of                  -- no look-ahead: cannot see filings not yet public
     AND period_end <= :as_of
   ORDER BY concept, unit, period_end DESC, filed DESC;
   ```

   Two crucial rules:
   - **Never read a fact with `filed > as_of`** — enforces point-in-time. Restatements are picked up the day they were filed, not retroactively.
   - **Prefer the most recent `period_end` that was filed on or before `as_of`**, then tiebreak by most recent `filed` (picks restated value if the amended 10-K/A arrived before `as_of`).

   TTM aggregation (for net income, revenues, gross profit, cost of revenue):
   - Preferred: take the single latest `form='10-K'` duration observation where `period_end <= as_of` and `filed <= as_of` — this is the annual value and is already "TTM".
   - Fallback when no 10-K yet or last 10-K is >15 months old: sum the last 4 observations with `fp IN ('Q1','Q2','Q3','Q4','FY')` and distinct `period_end` within the 4 quarters ending at or before `as_of`. Guard against gaps — if <4 quarters available, return `None`.
   - Document both paths in docstrings and test them separately.

   `total_assets_lag_12m`: the `Assets` value with `period_end` closest to `as_of - 365 days` (within ±90 days tolerance), filed ≤ `as_of`.

   `market_cap_usd` at month-end:
   - `shares` = most recent `CommonStockSharesOutstanding` (or `dei:EntityCommonStockSharesOutstanding`) with `filed ≤ as_of` and `period_end ≤ as_of`.
   - `price` = `nav_timeseries.close` on `as_of` (month-end) for the matched `instrument_id`. Fall back to latest `close` within 5 business days prior.
   - `market_cap_usd = shares × price`.
   - If either is null → `market_cap_usd = None`, and `size`, `book_to_market` return `None`.

   Return type:

   ```python
   @dataclass(frozen=True, slots=True)
   class XbrlPitSnapshot:
       inputs: CharacteristicInputs
       source_accn_map: dict[str, str]  # {"Assets": "0000320193-24-000123", ...}
   ```

### Worker

4. `backend/app/core/jobs/equity_characteristics_compute.py`

   ```python
   LOCK_ID = 900_091
   ```

   Responsibilities:
   - Acquire advisory lock (pattern from `global_risk_metrics`); skip if held.
   - Resolve universe: `instruments_universe` WHERE `is_active = true` AND `asset_class IN ('equity_us_large','equity_us_mid','equity_us_small')` AND `attributes->>'sec_cik' IS NOT NULL`. Top 500 by `market_cap_usd DESC NULLS LAST` (same filter the Tiingo draft used — now sourced from `instruments_universe`, not Tiingo). Store the resolved universe snapshot in a session-scoped list.
   - For each `(instrument_id, cik, ticker)`:
     - Determine month range: first month-end with any `sec_xbrl_facts` row for that CIK → latest completed month-end.
     - For each `month_end` in range:
       - `snapshot = await fetch_xbrl_pit(cik, as_of=month_end)`
       - `nav_window = await fetch_nav_window(instrument_id, end=month_end, months=13)`
       - `inputs = snapshot.inputs.replace(nav_series=nav_window)`
       - `chars = compute_characteristics(inputs, month_end)`
       - Upsert row into `equity_characteristics_monthly` (`ON CONFLICT (instrument_id, month_end) DO UPDATE SET ...`) — idempotent.
   - Concurrency: `asyncio.Semaphore(8)` across tickers, not across months (in-ticker work shares fetched XBRL dataset in a local dict cache — avoid re-querying `sec_xbrl_facts` 120 times per ticker; cache all concepts in one query per ticker, then index locally by `(concept, period_end, filed)`).
   - Per-ticker progress log every 50 tickers.
   - `try/finally` releases the lock. Return summary dict.

   **Cache hint:** for each CIK, issue a single SQL pull of all needed concepts across all time, build an in-memory index, then iterate months against the index. This turns N_months × N_concepts small queries into one bulk query per ticker — critical for ~500 tickers × 20 years × 12 months × 9 concepts = ~1M logical lookups.

### CLI runner

5. `backend/scripts/run_equity_characteristics_compute.py`
   - `--ticker AAPL --ticker MSFT` → subset
   - `--limit 10` → first N of universe
   - `--month-start 2015-01-31 --month-end 2024-12-31` → month range override
   - `--dry-run` → computes but does not write

### Tests

6. `backend/tests/app/domains/wealth/test_characteristics_derivation.py` — ≥10 unit tests (pure math):
   1. `derive_size(Decimal("1e9"))` ≈ `math.log(1e9)`
   2. `derive_size(None)` → None
   3. `derive_size(Decimal("-1"))` → None
   4. `derive_book_to_market(500, 1000)` == 0.5
   5. `derive_book_to_market(500, 0)` → None
   6. `derive_momentum_12_1` on 13-month series returns `nav[-2]/nav[-13] - 1` (t-12 to t-1, skipping most recent month)
   7. `derive_momentum_12_1` on 10-month series → None
   8. `derive_quality_roa(100, 1000)` == 0.1
   9. `derive_investment_growth(1100, 1000)` == 0.1
   10. `derive_profitability_gross(300, 1000, None)` == 0.3 (uses gross_profit)
   11. `derive_profitability_gross(None, 1000, 700)` == 0.3 (fallback to revenue - cost)
   12. `derive_profitability_gross(None, 1000, None)` → None

7. `backend/tests/app/domains/wealth/test_xbrl_pit_fetcher.py` — ≥8 integration tests (real PG, fixture data loaded into `sec_xbrl_facts`):
   1. Basic point-in-time: `Assets` at `as_of=2023-06-30` returns latest pre-asof filing
   2. Look-ahead guard: `Assets` filed `2023-09-01` for `period_end=2023-06-30` is **not** returned when `as_of=2023-08-15`
   3. Restatement: `10-K/A` filed before `as_of` is preferred over original `10-K`
   4. Concept alternate: when `Revenues` absent but `RevenueFromContractWithCustomerExcludingAssessedTax` present, alternate is picked
   5. TTM from 10-K: latest annual `NetIncomeLoss` used when available
   6. TTM from 4Q sum: 4 quarterly NetIncomeLoss summed when no recent 10-K
   7. Shares outstanding found via us-gaap `CommonStockSharesOutstanding`
   8. Shares outstanding fallback to `dei:EntityCommonStockSharesOutstanding`

8. `backend/tests/integration/test_equity_characteristics_worker.py` — ≥5 integration tests:
   1. Worker on 2-ticker fixture × 12 months: inserts 24 rows with non-null characteristics for months with adequate data
   2. Missing shares_outstanding → `size` and `book_to_market` NULL, other four still compute
   3. Restatement flows through: after adding a 10-K/A to fixture and re-running, relevant months' `source_accn_map` updates to amended `accn`
   4. Idempotent: re-run produces zero INSERTs and deterministic UPDATE values
   5. CLI `--limit 1` respects and logs

### Missingness diagnostic

9. `backend/scripts/diagnose_characteristics_missingness.py`
   - After full backfill, writes `docs/diagnostics/2026-04-20-characteristics-missingness.json` with per-column NULL share for top-500 universe across last 10 years
   - Accept any column >5% NULLs as long as documented (real data has gaps); worker must not crash on missing concepts

## Files to modify

1. `CLAUDE.md` — Data Ingestion Workers table: `equity_characteristics_compute | 900_091 | global | equity_characteristics_monthly | sec_xbrl_facts + nav_timeseries | On-demand (local dev); daily in prod follow-up`. Add `equity_characteristics_monthly` to global-tables list.
2. No `.env` additions.
3. `pyproject.toml` — no new deps (pandas already present).

## Implementation hints

### No silver parquet dual-write in this PR

The original draft mentioned a silver parquet mirror. Drop it here: `sec_xbrl_facts` is already durable, and the derivation is deterministic — rebuild from DB is cheap. A follow-up PR can add parquet export if needed for offline IPCA runs.

### Ticker-to-CIK bridge

Universe resolution reads `instruments_universe.attributes->>'sec_cik'`. If a target ticker lacks a CIK, **skip with warning** — do not crash, do not attempt a fallback lookup. This PR assumes PR-Q7 ingested facts for those CIKs. If facts are absent for a given CIK, worker logs `no xbrl facts for cik=X ticker=Y` and moves on.

### Price source

Use `nav_timeseries` directly. No adjustment for splits/dividends needed for momentum (total-return NAV already reflects it if that's what the column holds — verify against one well-known ticker in the integration test). For `market_cap_usd`, however, a split-adjusted price multiplied by split-adjusted shares is fine; a raw close × raw shares is also fine; do **not** mix. Prefer raw close × raw `CommonStockSharesOutstanding` on the filing date.

### Advisory lock key

`LOCK_ID = 900_091` (int constant). If the helper expects a string, use `zlib.crc32(b"equity_characteristics_compute")`. Never `hash()`.

## Acceptance gates

- `make check` green
- Migration 0167 reversible
- Worker 5-ticker × 120-month smoke completes in <60s on Andrei's machine
- Per-ticker XBRL bulk fetch executes 1 SQL query (not N_concepts × N_months) — grep the worker for loops around SQL calls
- Missingness diagnostic written to `docs/diagnostics/`
- No look-ahead bias: dedicated integration test (#2 above) passes
- Restatement propagation: dedicated integration test (#3 above) passes
- P5 idempotent: second run writes 0 changed rows
- Compression policy active on `equity_characteristics_monthly`
- No HTTP calls introduced (grep new files: no `httpx`, `requests`, `aiohttp`, `data.sec.gov`)

## Non-goals

- IPCA estimation (PR-Q9)
- More than 6 characteristics
- Universe beyond top 500 US equities
- Any frontend / route / DD chapter wiring
- Silver parquet mirror
- Daily schedule / Railway cron (prod productionisation is a follow-up PR after PR-Q7 HTTP delta lands)
- IFRS or non-US issuers
- Sector-adjusted or industry-neutral variants

## Branch + commit

```
feat/equity-characteristics-matview
```

PR title: `feat(quant/equity-chars): equity_characteristics_monthly from sec_xbrl_facts (lock 900_091)`

PR body must include:
- Summary of the XBRL source pivot and link to PR-Q7
- Row count on Andrei's machine after full backfill
- Missingness diagnostic summary (per-column NULL %)
- One concrete restatement example showing `source_accn_map` updating across 10-K → 10-K/A
- Link to this prompt
