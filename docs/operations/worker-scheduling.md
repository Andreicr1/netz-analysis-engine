# Wealth Worker Scheduling Reference

All workers live in `backend/app/domains/wealth/workers/`.

## Daily Pipeline Order

Workers that form the daily pipeline must run in this sequence:

```
macro_ingestion -> ingestion -> risk_calc -> portfolio_eval -> regime_fit -> bayesian_cvar -> drift_check
```

## Worker Inventory

### HTTP-Triggered Workers (via `/api/wealth/workers/`)

These workers have POST endpoints in `routes/workers.py`. They can be triggered by the admin UI, CI pipelines, or an external scheduler hitting the HTTP endpoint. All require `ADMIN` or `INVESTMENT_TEAM` role.

| Worker | Route | Entry Point | Advisory Lock ID | Dependencies | Recommended Interval |
|---|---|---|---|---|---|
| `ingestion.py` | `POST /workers/run-ingestion` | `run_ingestion()` | `900_006` | PostgreSQL, Yahoo Finance API | Daily, after market close |
| `risk_calc.py` | `POST /workers/run-risk-calc` | `run_risk_calc()` | `900_007` | PostgreSQL | Daily, after `ingestion` |
| `portfolio_eval.py` | `POST /workers/run-portfolio-eval` | `run_portfolio_eval()` | `900_008` | PostgreSQL, Redis (alerts) | Daily, after `risk_calc` |
| `macro_ingestion.py` | `POST /workers/run-macro-ingestion` | `run_macro_ingestion()` | `43` | PostgreSQL, FRED API (`FRED_API_KEY`) | Daily, before `risk_calc` |
| `fact_sheet_gen.py` | `POST /workers/run-fact-sheet-gen` | `run_monthly_fact_sheets()` | `900_001` | PostgreSQL, OpenAI API | Monthly (1st business day) |
| `screening_batch.py` | `POST /workers/run-screening-batch` | `run_screening_batch(org_id)` | `900_002` | PostgreSQL | Weekly |
| `watchlist_batch.py` | `POST /workers/run-watchlist-check` | `run_watchlist_check(org_id)` | `900_003` | PostgreSQL, Redis (alerts) | Weekly |
| `benchmark_ingest.py` | `POST /workers/run-benchmark-ingest` | `run_benchmark_ingest()` | `900_004` | PostgreSQL, Yahoo Finance API | Daily, after market close |

### Scheduler-Only Workers (no HTTP route)

These workers have **no HTTP endpoint**. They must be invoked via an external scheduler (cron, Azure Functions Timer Trigger, etc.) using `python -m app.workers.<name>` or by importing and calling the async entry point directly.

| Worker | Entry Point | Advisory Lock ID | Dependencies | Recommended Interval | Notes |
|---|---|---|---|---|---|
| `drift_check.py` | `run_drift_check()` | `42` | PostgreSQL, `quant_engine` | Daily, after `portfolio_eval` | Creates rebalance events when drift exceeds thresholds. Runs for all 3 profiles (conservative, moderate, growth). |
| `regime_fit.py` | `run_regime_fit()` | None | PostgreSQL, **statsmodels** (`[timeseries]` extra) | Daily, after `portfolio_eval` | Fits 2-state Markov HMM on VIX log-levels. Requires 252+ VIX observations. Skips gracefully if statsmodels is not installed. |
| `bayesian_cvar.py` | `run_bayesian_cvar()` | None | PostgreSQL, **PyMC >= 5.0** (`[bayesian]` extra) | Daily, after `portfolio_eval` | ADVI approximation for CVaR credible intervals. Gated by `FEATURE_BAYESIAN_CVAR=true` feature flag. Skips entirely if PyMC is not installed or flag is disabled. CPU-intensive (offloads to thread pool). |
| `fred_ingestion.py` | `run_fred_ingestion()` | None | PostgreSQL, FRED API (`FRED_API_KEY`) | **DEPRECATED** -- do not schedule | Superseded by `macro_ingestion.py` (45 series vs 10, regional scoring). Do not run both simultaneously -- they write to the same `macro_data` rows. Pending removal in cleanup sprint. |

## CLI Invocation

All workers support direct CLI execution for debugging and one-off runs:

```bash
# HTTP-triggered workers (can also be called via CLI)
python -m app.domains.wealth.workers.ingestion
python -m app.domains.wealth.workers.risk_calc
python -m app.domains.wealth.workers.portfolio_eval
python -m app.domains.wealth.workers.macro_ingestion

# Scheduler-only workers (must be called via CLI or external trigger)
python -m app.domains.wealth.workers.drift_check
python -m app.domains.wealth.workers.regime_fit
python -m app.domains.wealth.workers.bayesian_cvar
```

## Advisory Lock Registry

All locks use `pg_try_advisory_lock` (non-blocking). If the lock is already held, the worker skips its run and logs a warning.

| Lock ID | Worker | Purpose |
|---|---|---|
| `42` | `drift_check.py` | Pipeline serialization |
| `43` | `macro_ingestion.py` | Macro ingestion serialization |
| `900_001` | `fact_sheet_gen.py` | Fact sheet generation |
| `900_002` | `screening_batch.py` | Batch screening |
| `900_003` | `watchlist_batch.py` | Watchlist re-evaluation |
| `900_004` | `benchmark_ingest.py` | Benchmark NAV ingestion |
| `900_006` | `ingestion.py` | NAV ingestion |
| `900_007` | `risk_calc.py` | Risk calculation |
| `900_008` | `portfolio_eval.py` | Portfolio evaluation |

## Optional Dependencies

| Extra Group | Package | Workers |
|---|---|---|
| `[timeseries]` | statsmodels | `regime_fit.py` |
| `[bayesian]` | pymc >= 5.0, arviz | `bayesian_cvar.py` |

Both workers degrade gracefully (skip with a log warning) when their optional dependency is not installed.

## Feature Flags

| Flag | Default | Worker |
|---|---|---|
| `FEATURE_BAYESIAN_CVAR` | `false` | `bayesian_cvar.py` -- worker exits immediately when disabled |

## Example Cron Schedule (Production)

```cron
# Daily pipeline (US market close = 16:00 ET = 21:00 UTC)
00 21 * * 1-5  macro_ingestion
05 21 * * 1-5  ingestion
05 21 * * 1-5  benchmark_ingest
20 21 * * 1-5  risk_calc
35 21 * * 1-5  portfolio_eval
50 21 * * 1-5  regime_fit
55 21 * * 1-5  bayesian_cvar
00 22 * * 1-5  drift_check

# Weekly (Sunday night)
00 22 * * 0    screening_batch
15 22 * * 0    watchlist_batch

# Monthly (1st of month)
00 23 1 * *    fact_sheet_gen
```
