---
pr_id: PR-Q8
title: "feat(quant/equity-chars): equity_characteristics_monthly + derivation worker"
branch: feat/equity-characteristics-matview
sprint: S4 (parallel with PR-Q6)
dependencies: [PR-Q7]
loc_estimate: 350
reviewer: data-platform
---

# Prompt — PR-Q8: Equity Characteristics

## Goal

Derive the 6 Kelly-Pruitt-Su characteristics (size, book-to-market, momentum 12-1, ROA quality, investment growth, gross profitability) from Tiingo Fundamentals + `nav_timeseries` into a new hypertable. This is the input panel for PR-Q9 G5 IPCA.

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §6 (DDL + derivation + silver parquet)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §7 (Tiingo coverage table)
- `CLAUDE.md` §Data Ingestion Workers

## Files to create

1. `backend/alembic/versions/0135_equity_characteristics_monthly.py` — hypertable DDL per data-layer spec §6.1.
2. `backend/app/core/jobs/equity_characteristics_compute.py` — worker with lock 900_091. Reads `tiingo_fundamentals_*` + `nav_timeseries`, writes `equity_characteristics_monthly`.
3. `backend/app/domains/wealth/services/characteristics_derivation.py` — pure derivation functions (testable without DB).
4. `backend/tests/app/domains/wealth/test_characteristics_derivation.py` — ≥10 unit tests.
5. `backend/tests/integration/test_equity_characteristics_worker.py` — ≥5 integration tests.

## Files to modify

1. `CLAUDE.md` Data Ingestion Workers table — add row for lock 900_091.

## Implementation hints

### Derivation formulas

Assume `statements_latest` is a dict of statement line items for the ticker at a given `as_of` month, taking latest `filing_date` via `DISTINCT ON (ticker, period_end, line_item) ORDER BY ... filing_date DESC`.

```python
def derive_size(market_cap_eom: float) -> float | None:
    if market_cap_eom is None or market_cap_eom <= 0:
        return None
    return float(np.log(market_cap_eom))

def derive_book_to_market(total_equity: float, market_cap_eom: float) -> float | None:
    if None in (total_equity, market_cap_eom) or market_cap_eom <= 0:
        return None
    return float(total_equity / market_cap_eom)

def derive_momentum_12_1(nav_series: pd.Series, as_of: date) -> float | None:
    # nav_series indexed by month-end; compute return from t-12 to t-1
    window = nav_series.loc[:as_of].iloc[-13:-1]
    if len(window) < 11:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1)

def derive_quality_roa(net_income_ttm: float, total_assets: float) -> float | None:
    if None in (net_income_ttm, total_assets) or total_assets <= 0:
        return None
    return float(net_income_ttm / total_assets)

def derive_investment_growth(total_assets_now: float, total_assets_yoy: float) -> float | None:
    if None in (total_assets_now, total_assets_yoy) or total_assets_yoy <= 0:
        return None
    return float(total_assets_now / total_assets_yoy - 1)

def derive_profitability_gross(gross_profit: float | None,
                               revenue: float,
                               cost_of_revenue: float | None) -> float | None:
    if revenue is None or revenue <= 0:
        return None
    if gross_profit is not None:
        return float(gross_profit / revenue)
    if cost_of_revenue is not None:
        return float((revenue - cost_of_revenue) / revenue)
    return None
```

### Worker structure

```python
LOCK_ID = 900_091

async def run():
    got = await try_advisory_lock(LOCK_ID)
    if not got: return
    try:
        universe = await load_tiingo_universe()  # same 500 tickers
        for ticker, instrument_id in universe:
            await compute_ticker_characteristics(ticker, instrument_id)
    finally:
        await release_advisory_lock(LOCK_ID)

async def compute_ticker_characteristics(ticker, instrument_id):
    # Determine month range: from oldest daily metric to latest month-end
    # For each month, derive the 6 characteristics, upsert into equity_characteristics_monthly
    ...
```

### Silver parquet dual-write

Write monthly snapshots to `silver/_global/equity_characteristics/{as_of}/chars.parquet` with columns matching hypertable. Use zstd compression. `embedding_model` / `embedding_dim` columns not applicable here — this is analytics data, not retrieval.

### Schedule

Daily after `tiingo_fundamentals_ingestion` completes (04:30 UTC safe offset).

## Tests

### Derivation unit tests (≥10)
1. `derive_size(1e9)` ≈ ln(1e9)
2. `derive_size(None)` returns None
3. `derive_size(-1)` returns None
4. `derive_book_to_market(500, 1000)` == 0.5
5. `derive_momentum_12_1` on 13-month series: returns start-to-penultimate return
6. `derive_momentum_12_1` on <11-month series: returns None
7. `derive_quality_roa` TTM division
8. `derive_investment_growth`: +10% YoY → 0.10
9. `derive_profitability_gross` uses `grossProfit` when available
10. `derive_profitability_gross` fallback to `revenue - costOfRevenue`

### Integration tests (≥5)
1. Worker on 5 tickers × 12 months: inserts 60 rows
2. Restatement: updated statement filing_date propagates to characteristics (upsert wins)
3. Missing Tiingo data for ticker → row written with NULLs, not crash
4. Idempotent: re-run produces no duplicates
5. Silver parquet file written per month with correct schema

## Acceptance gates

- `make check` green
- Migration reversible
- Worker completes end-to-end for 5-ticker fixture in <10s
- Compression policy on hypertable active
- Missingness audit after full backfill: <5% NULLs in each of 6 cols for top-500 universe — log as `docs/diagnostics/2026-XX-XX-characteristics-missingness.json`
- P5 idempotent

## Non-goals

- Do NOT compute IPCA in this PR — PR-Q9
- Do NOT add more than 6 characteristics
- Do NOT extend universe beyond top 500 — expansion is follow-up
- Do NOT publish to any route or UI — data is worker-produced only

## Branch + commit

```
feat/equity-characteristics-matview
```

PR title: `feat(quant/equity-chars): equity_characteristics_monthly + derivation worker (lock 900_091)`
