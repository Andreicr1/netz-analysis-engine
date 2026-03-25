# Prompt: Quant Engine & DD Report — Reference Document

You are a senior quantitative analyst producing a **comprehensive reference document** for the Netz Analysis Engine's quantitative infrastructure and Due Diligence report system.

## Output

Write the document to: `docs/reference/quant-engine-dd-report-reference.md`

**Audience:** Institutional investors, compliance officers, portfolio managers, and auditors who need to understand exactly what the system computes, how, and when. Every claim must be traceable to code.

**Tone:** Technical but accessible. No marketing language. Every metric, method, and threshold must be **transparent, demonstrable, replicable, and quantifiable**. Include formulas where applicable (LaTeX notation in markdown).

## Document Structure

Produce these sections (adapt as evidence dictates):

### 1. Quant Engine Architecture
- High-level pipeline: data ingestion → computation → storage → consumption
- Thread/async model (workers in background, sync computation via `asyncio.to_thread`)
- Config injection pattern (`ConfigService.get()` → passed as parameter, no YAML at runtime)

### 2. Risk Metrics Pipeline (`risk_calc` worker)
- Read: `backend/quant_engine/scoring_service.py`, `backend/quant_engine/cvar_service.py`, `backend/quant_engine/regime_service.py`, `backend/quant_engine/momentum_service.py` (if exists, else check inside risk-related files)
- Read: `backend/app/domains/wealth/workers/risk_calc.py`
- Document every metric computed and stored in `fund_risk_metrics`:
  - CVaR (95%, 99%) — method (historical, parametric, or both), window
  - Sharpe ratio — annualization, risk-free rate source
  - Volatility — window, annualization
  - Max drawdown — computation method
  - Momentum signals: RSI(14), Bollinger Band position, OBV flow, NAV momentum score, flow momentum score, blended momentum score
  - Manager composite score — components and weights
- Frequency: daily worker, lock ID 900_007
- Storage: `fund_risk_metrics` hypertable

### 3. Regime Detection
- Read: `backend/quant_engine/regime_service.py`
- Method (e.g., Hidden Markov Model, rolling volatility thresholds, or other)
- States defined (normal, caution, stress, crisis — or whatever the code defines)
- Inputs (which series, which window)
- How regime feeds into portfolio evaluation and rebalancing triggers

### 4. Portfolio Evaluation (`portfolio_eval` worker)
- Read: `backend/app/domains/wealth/workers/portfolio_eval.py`
- What it computes: breach status, regime cascade, snapshot
- Storage: `portfolio_snapshots` hypertable
- Frequency: daily, lock ID 900_008

### 5. Drift Monitoring
- Read: `backend/quant_engine/drift_service.py`
- Block-level drift: absolute vs relative, maintenance/urgent thresholds
- DTW drift detection: derivative DTW (ddtw), normalization, window, max_lookback_days
- Batch DTW: pairwise_distance vectorized
- `drift_check` worker: frequency (daily), lock ID 42, storage (`strategy_drift_alerts`)

### 6. Walk-Forward Backtesting
- Read: `backend/quant_engine/backtest_service.py`
- TimeSeriesSplit with expanding window
- Parameters: n_splits, gap, min_train_size, test_size
- Per-fold metrics: Sharpe, CVaR(95%), max drawdown
- Fold consistency reporting (not p-values)
- ThreadPoolExecutor parallelization

### 7. Portfolio Optimization
- Read: `backend/quant_engine/optimizer_service.py`
- Optimization method (mean-variance, CVaR, or multi-objective)
- Constraints (box, turnover, sector)
- Pareto front (if multi-objective via pymoo)
- Caching: Redis SHA-256, 1h TTL
- Background job with SSE progress for Pareto

### 8. Rebalancing Engine
- Read: `backend/vertical_engines/wealth/rebalancing/service.py`, `weight_proposer.py`
- Read: `backend/quant_engine/rebalance_service.py`
- Triggers: drift thresholds, regime change, calendar-based
- LATERAL JOIN batch query for regime trigger detection
- Weight proposal logic
- Impact analysis (turnover, tax, cost estimates)

### 9. Attribution (Brinson-Fachler)
- Read: `backend/vertical_engines/wealth/attribution/service.py`
- Brinson-Fachler decomposition: allocation effect, selection effect, interaction effect
- Multi-period linking (Carino method)
- Granularity: monthly, quarterly

### 10. Correlation & Denoising
- Read: `backend/vertical_engines/wealth/correlation/service.py`
- Rolling correlation matrix
- Marchenko-Pastur denoising
- Absorption ratio
- Cache: `@route_cache(ttl=300)`

### 11. Screening Pipeline (3-Layer Deterministic)
- Read: `backend/vertical_engines/wealth/screener/service.py`, `models.py`
- Layer 1: Eliminatory filters (hard constraints)
- Layer 2: Mandate fit scoring
- Layer 3: Quantitative ranking
- Document each filter/criterion

### 12. Macro Intelligence Coverage
- Read: `backend/vertical_engines/wealth/macro_committee_engine.py`
- Read: `backend/vertical_engines/wealth/flash_report.py`
- Read: `backend/vertical_engines/wealth/investment_outlook.py`
- Weekly macro committee reports: regional coverage (4 regions + global)
- Flash reports: event-driven, 48h cooldown
- Investment outlook: quarterly macro narrative
- Data sources: FRED (~65 series), Treasury, OFR, BIS, IMF

### 13. Due Diligence Report Engine
- Read: `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`
- Read: `backend/vertical_engines/wealth/dd_report/sec_injection.py`
- Read all files in `backend/vertical_engines/wealth/dd_report/`
- 8-chapter structure — document each chapter's scope and evidence sources
- Evidence pack construction
- Confidence scoring methodology
- Critic engine (adversarial review, circuit-breaker, 3min timeout)
- SEC data injection: 13F holdings, ADV manager data, institutional investors
- Parallel chapter generation (ThreadPoolExecutor, chapters 1-7 parallel, chapter 8 sequential)
- Resume safety (cached chapters reused on retry)

### 14. SEC Data Integration
- Read: `backend/data_providers/sec/thirteenf_service.py`, `adv_service.py`, `institutional_service.py`
- 13F holdings: sector aggregation, concentration metrics, quarter-over-quarter diffs
- ADV: manager info, fund list, team composition
- Institutional: investor-in-manager discovery
- DB-only hot path (no EDGAR API calls in user-facing requests)

### 15. Fund Analysis (Top-Down Investment Chain)
- Document the full chain: Macro → Allocation → Screeners → DD → IC → Universe → Model Portfolios → Rebalance → Alerts
- For each stage, what is computed and what feeds the next

### 16. External Data Ingestion Workers
- Table of ALL workers with: lock ID, scope, hypertable, source, frequency, series count
- Workers: macro_ingestion, treasury_ingestion, ofr_ingestion, benchmark_ingest, instrument_ingestion, risk_calc, portfolio_eval, nport_ingestion, sec_13f_ingestion, sec_adv_ingestion, bis_ingestion, imf_ingestion, drift_check

### 17. Continuous Aggregates & Pre-computation
- `nav_monthly_returns_agg`: compound monthly returns per instrument
- `benchmark_monthly_returns_agg`: compound monthly returns per benchmark block
- `sec_13f_holdings_agg`: sector allocation per CIK/quarter
- `sec_13f_drift_agg`: churn count per CIK/quarter
- Refresh policies and frequencies

### 18. Alerting & Automated Actions
- Strategy drift alerts (DTW-based)
- Portfolio breach alerts (from portfolio_eval)
- Watchlist PASS→FAIL transitions
- Fee drag alerts
- Flash report triggers (event-driven with cooldown)

### 19. Computational Capacity & Performance
- ThreadPoolExecutor usage (DD chapters, backtest folds)
- Batch operations (pgvector batch INSERT, DTW batch)
- Redis caching layer (route_cache TTLs by endpoint category)
- TimescaleDB continuous aggregates (pre-computed monthly returns)
- Advisory locks for worker coordination (no duplicate computation)
- Index strategy (11 indexes from migration 0048)

## Research Instructions

1. **Read CLAUDE.md first** — it has the architecture overview and all rules
2. **Read actual code, not just docstrings** — extract formulas, thresholds, defaults from the implementation
3. For each metric, document: formula, default parameters, data source, storage location, update frequency
4. For each threshold, document: default value, config path (if configurable via ConfigService), units
5. Cross-reference workers table in CLAUDE.md with actual worker files
6. **Do NOT invent or assume** — if a metric or method isn't in the code, don't include it. Mark gaps as "Not implemented" if the architecture suggests it but code doesn't exist yet.

## Key Files to Read (prioritized)

```
# Quant Engine core
backend/quant_engine/cvar_service.py
backend/quant_engine/scoring_service.py
backend/quant_engine/regime_service.py
backend/quant_engine/drift_service.py
backend/quant_engine/backtest_service.py
backend/quant_engine/optimizer_service.py
backend/quant_engine/rebalance_service.py

# Workers
backend/app/domains/wealth/workers/risk_calc.py
backend/app/domains/wealth/workers/portfolio_eval.py

# Vertical engines — wealth
backend/vertical_engines/wealth/dd_report/dd_report_engine.py
backend/vertical_engines/wealth/dd_report/sec_injection.py
backend/vertical_engines/wealth/dd_report/evidence*.py
backend/vertical_engines/wealth/dd_report/critic*.py
backend/vertical_engines/wealth/attribution/service.py
backend/vertical_engines/wealth/correlation/service.py
backend/vertical_engines/wealth/screener/service.py
backend/vertical_engines/wealth/rebalancing/service.py
backend/vertical_engines/wealth/rebalancing/weight_proposer.py
backend/vertical_engines/wealth/monitoring/*.py
backend/vertical_engines/wealth/watchlist/service.py
backend/vertical_engines/wealth/fee_drag/service.py
backend/vertical_engines/wealth/mandate_fit/service.py
backend/vertical_engines/wealth/peer_group/service.py
backend/vertical_engines/wealth/macro_committee_engine.py
backend/vertical_engines/wealth/flash_report.py
backend/vertical_engines/wealth/investment_outlook.py
backend/vertical_engines/wealth/fund_analyzer.py
backend/vertical_engines/wealth/quant_analyzer.py
backend/vertical_engines/wealth/manager_spotlight.py

# SEC data providers
backend/data_providers/sec/thirteenf_service.py
backend/data_providers/sec/adv_service.py
backend/data_providers/sec/institutional_service.py

# Migrations (for continuous aggregates)
backend/app/core/db/migrations/versions/0038_manager_screener_indexes_continuous_aggs.py
backend/app/core/db/migrations/versions/0049_wealth_continuous_aggregates.py
```

## Quality Criteria

- Every formula has a code reference (`file:line`)
- Every default threshold has a code reference
- Every worker has lock ID, frequency, and hypertable documented
- No hand-waving: if the system doesn't do something, say so explicitly
- Document must be self-contained — readable without access to the codebase
- Target length: 3000-5000 lines (comprehensive, not padded)
