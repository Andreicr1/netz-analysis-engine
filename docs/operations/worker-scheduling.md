# Wealth Worker Scheduling Reference

All workers live in `backend/app/domains/wealth/workers/`.

## Scheduler: Railway Cron Jobs

Workers are scheduled via `[[crons]]` entries in `railway.toml` at the repo root.
Each cron job invokes workers directly via CLI:

```bash
python -m app.workers.cli <worker_name>
```

The CLI:
- Resolves the worker from `worker_registry.py`
- For org-scoped workers, queries all active orgs and runs once per org
- Uses `asyncio.run()` — same async pattern as the HTTP endpoints
- Returns exit code 0 (success) or 1 (failure/timeout) — Railway uses this for alerting

Advisory locks (`pg_try_advisory_lock`) inside each worker prevent concurrent execution
even if Railway fires overlapping cron runs.

## Daily Pipeline Order

Workers that form the daily pipeline must run in this sequence:

```
06:00  macro_ingestion, treasury_ingestion, benchmark_ingest  (parallel, global)
06:30  ingestion, instrument_ingestion                        (parallel, org-scoped)
07:00  risk_calc, portfolio_eval                              (parallel, org-scoped)
07:30  portfolio_nav_synthesizer, drift_check, regime_fit     (parallel, post-eval)
08:00  screening_batch, watchlist_batch                       (parallel, org-scoped)
```

## Complete Worker Inventory

### Global Workers (no org_id)

| Worker | Schedule | Lock ID | Entry Point | Source | Timeout |
|--------|----------|---------|-------------|--------|---------|
| `macro_ingestion` | `0 6 * * *` | 43 | `run_macro_ingestion()` | FRED API (~65 series) | 10min |
| `treasury_ingestion` | `0 6 * * *` | 900_011 | `run_treasury_ingestion()` | US Treasury API | 10min |
| `benchmark_ingest` | `0 6 * * *` | 900_004 | `run_benchmark_ingest()` | Yahoo Finance | 10min |
| `ofr_ingestion` | `0 2 * * 0` | 900_012 | `run_ofr_ingestion()` | OFR API | 10min |
| `nport_ingestion` | `0 2 * * 0` | 900_018 | `run_nport_ingestion()` | SEC EDGAR N-PORT | 10min |
| `nport_fund_discovery` | manual | 900_024 | `run_nport_fund_discovery()` | SEC EDGAR EFTS | 10min |
| `nport_ticker_resolution` | manual | 900_025 | `run_nport_ticker_resolution()` | OpenFIGI | 10min |
| `esma_ingestion` | `0 4 * * 1` | 900_019 | `run_esma_ingestion()` | ESMA Solr | 10min |
| `sec_13f_ingestion` | `0 3 1 1,4,7,10 *` | 900_021 | `run_sec_13f_ingestion()` | SEC EDGAR 13F | 10min |
| `sec_adv_ingestion` | `0 3 1 1,4,7,10 *` | 900_022 | `run_sec_adv_ingestion()` | SEC FOIA CSV | 10min |
| `sec_refresh` | `0 5 1 1,4,7,10 *` | 900_016 | `run_sec_refresh()` | Computed | 10min |
| `bis_ingestion` | `0 3 1 1,4,7,10 *` | 900_014 | `run_bis_ingestion()` | BIS SDMX API | 10min |
| `imf_ingestion` | `0 3 1 1,4,7,10 *` | 900_015 | `run_imf_ingestion()` | IMF DataMapper | 10min |
| `brochure_download` | manual | 900_019 | `run_brochure_download()` | IAPD | 10min |
| `brochure_extract` | manual | 900_020 | `run_brochure_extract()` | Local PDFs | 10min |
| `drift_check` | `30 7 * * *` | 42 | `run_drift_check()` | Computed (DTW) | 5min |
| `regime_fit` | `30 7 * * *` | — | `run_regime_fit()` | Computed (HMM) | 5min |
| `fact_sheet_gen` | manual | 900_001 | `run_monthly_fact_sheets()` | Computed + OpenAI | 10min |

### Org-Scoped Workers (dispatched per active org)

| Worker | Schedule | Lock ID | Entry Point | Source | Timeout |
|--------|----------|---------|-------------|--------|---------|
| `ingestion` | `30 6 * * *` | 900_006 | `run_ingestion()` | Yahoo Finance | 10min |
| `instrument_ingestion` | `30 6 * * *` | 900_010 | `run_instrument_ingestion()` | Yahoo Finance | 10min |
| `risk_calc` | `0 7 * * *` | 900_007 | `run_risk_calc()` | Computed | 10min |
| `portfolio_eval` | `0 7 * * *` | 900_008 | `run_portfolio_eval()` | Computed | 5min |
| `portfolio_nav_synthesizer` | `30 7 * * *` | 900_030 | `run_portfolio_nav_synthesizer()` | Computed (weighted NAV) | 5min |
| `screening_batch` | `0 8 * * *` | 900_002 | `run_screening_batch()` | Computed | 5min |
| `watchlist_batch` | `0 8 * * *` | 900_003 | `run_watchlist_check()` | Computed | 5min |

## Manual Trigger

All workers with HTTP endpoints can be triggered manually via the admin API:

```bash
POST /api/v1/workers/run-{name}
# Requires ADMIN or INVESTMENT_TEAM role
# Returns 202 Accepted, runs in background
# Returns 409 if already running or recently completed
```

## CLI Invocation

For debugging and one-off runs:

```bash
# Via the Railway Cron CLI (same as cron uses)
python -m app.workers.cli macro_ingestion
python -m app.workers.cli risk_calc

# Direct module invocation (some workers support this)
python -m app.domains.wealth.workers.portfolio_nav_synthesizer
```

## Advisory Lock Registry

All locks use `pg_try_advisory_lock` (non-blocking). If the lock is already held,
the worker skips its run and logs a warning.

| Lock ID | Worker | Purpose |
|---------|--------|---------|
| 42 | `drift_check` | Pipeline serialization |
| 43 | `macro_ingestion` | Macro ingestion serialization |
| 900_001 | `fact_sheet_gen` | Fact sheet generation |
| 900_002 | `screening_batch` | Batch screening |
| 900_003 | `watchlist_batch` | Watchlist re-evaluation |
| 900_004 | `benchmark_ingest` | Benchmark NAV ingestion |
| 900_006 | `ingestion` | NAV ingestion |
| 900_007 | `risk_calc` | Risk calculation |
| 900_008 | `portfolio_eval` | Portfolio evaluation |
| 900_010 | `instrument_ingestion` | Instrument NAV ingestion |
| 900_011 | `treasury_ingestion` | Treasury data ingestion |
| 900_012 | `ofr_ingestion` | OFR hedge fund data |
| 900_014 | `bis_ingestion` | BIS statistics |
| 900_015 | `imf_ingestion` | IMF WEO forecasts |
| 900_016 | `sec_refresh` | SEC aggregate refresh |
| 900_018 | `nport_ingestion` | N-PORT holdings |
| 900_019 | `brochure_download`, `esma_ingestion` | Brochure download / ESMA |
| 900_020 | `brochure_extract` | Brochure text extraction |
| 900_021 | `sec_13f_ingestion` | SEC 13F holdings |
| 900_022 | `sec_adv_ingestion` | SEC ADV bulk CSV |
| 900_024 | `nport_fund_discovery` | N-PORT fund discovery |
| 900_025 | `nport_ticker_resolution` | N-PORT ticker resolution |
| 900_030 | `portfolio_nav_synthesizer` | Portfolio NAV synthesis |
