# Fixed Income Quant Engine — Execution Wrapper

**Date:** 2026-04-12
**Specification:** `docs/plans/fixed_income_quant_engine.md` (authoritative spec, ~450 lines with exact code)
**Status:** Ready for execution after Tiingo post-merge operations complete
**Priority:** SCORING INTEGRITY GATE — must complete before Phase 4 Builder

## Why this wrapper exists

The FI Quant plan was expanded on 2026-04-12 with the wealth-portfolio-quant-architect agent. It is detailed and complete. This wrapper adds:

1. **Context updates** — Alembic head advanced to 0121 (Tiingo migration). Yahoo retired, `benchmark_ingest` now uses Tiingo.
2. **Session split** — 3 sessions with review gates between each.
3. **Dependency verification** — Tiingo post-merge ops must complete first (NAV data fresh for OLS regressions).

## Critical context updates

### Alembic renumbering

FI Quant migrations start at `0122` (or current head + 1). Verify via `alembic heads` before writing.

### Yahoo → Tiingo

The plan's Phase 0 §Execução says "benchmark_ingest — ele processa automaticamente todos os blocos [...] serão baixados via yfinance batch". **Yahoo is retired.** `benchmark_ingest` now uses `TiingoInstrumentProvider` (Tiingo PR-B). The 7 FI benchmark tickers (AGG, LQD, HYG, TIP, GOVT, EMB, SHY) will be ingested via Tiingo. No code change needed — the factory swap handles this automatically.

### Tiingo post-merge dependency

Before FI Quant Session 1 starts, verify:

```sql
-- NAV data is fresh (Tiingo re-ingestion completed)
SELECT source, COUNT(*), MAX(nav_date)
FROM nav_timeseries
WHERE nav_date >= CURRENT_DATE - INTERVAL '5 days'
GROUP BY source;
-- Expect: source='tiingo', MAX(nav_date) recent

-- Macro data exists for regressions
SELECT series_id, COUNT(*), MAX(obs_date)
FROM macro_data
WHERE series_id IN ('DGS10', 'BAA10Y')
GROUP BY series_id;
-- Expect: both series present with recent data
```

If NAV data is stale or macro series missing, FI analytics regressions will produce incorrect coefficients. Wait for the data to flow.

### ScoreCompositionPanel frontend update

Phase 3 Fix Sprint 4 shipped `ScoreCompositionPanel.svelte` showing 6 equity components as horizontal bars. When FI Quant ships, the panel must handle BOTH equity and FI component sets (different key names). The `scoring_model` field on `fund_risk_metrics` ("equity" or "fixed_income") tells the frontend which component set to render. The plan's Phase 3 (scoring dispatch) adds `scoring_model` to the response. The frontend update to ScoreCompositionPanel should be included in Session 3 (screener gates) since it's a consumer-facing change.

## 3-session execution

### Session 1 — Foundation: Benchmarks + Analytics Service (Phase 0 + Phase 1)

**Branch:** `feat/fi-quant-session-1`

**Deliverable:**
1. Migration seeding 7 FI allocation blocks (AGG, LQD, HYG, TIP, GOVT, EMB, SHY)
2. Run `benchmark_ingest` to populate NAV data for the 7 benchmarks via Tiingo
3. `backend/quant_engine/fixed_income_analytics_service.py` — new pure module with 4 functions:
   - `compute_empirical_duration()` — OLS vs DGS10 yield changes
   - `compute_credit_beta()` — OLS vs BAA10Y spread changes
   - `compute_yield_proxy()` — trailing 12m income return proxy
   - `compute_duration_adjusted_drawdown()` — max_drawdown / max(duration, 1)
4. `_ols_regression()` helper using `numpy.linalg.lstsq`
5. `FIAnalyticsResult` + `FIRegressionConfig` frozen dataclasses
6. Unit tests with synthetic data (6 test cases per plan Phase 1)

**Read:** plan §Phase 0 + §Phase 1 fully.

**Gate:**
- `ruff check` clean on new files
- `mypy` clean on new module
- `pytest tests/quant_engine/test_fixed_income_analytics_service.py` — 6 tests green
- `lint-imports` — contracts intact (quant_engine must NOT import from app.domains.wealth)
- Benchmark NAV data: `SELECT COUNT(*) FROM benchmark_nav WHERE block_id LIKE 'fi_%'` returns data for all 7 blocks

**Instruction for Opus:**
```
Read docs/plans/fixed_income_quant_engine.md sections "Fase 0" and "Fase 1" fully, and docs/plans/2026-04-12-fi-quant-execution-wrapper.md fully. Implement Phase 0 (benchmark seed migration + verify benchmark_ingest populates Tiingo data for 7 FI tickers) and Phase 1 (fixed_income_analytics_service.py with 4 functions + OLS helper + dataclasses + 6 unit tests). Alembic migration starts at current head + 1 (verify with alembic heads). benchmark_ingest uses Tiingo, not yfinance (Yahoo retired in PR-B/C). Report.
```

### Session 2 — Core: Migration + Worker + Scoring Dispatch (Phase 2 + Phase 3)

**Branch:** `feat/fi-quant-session-2`
**Depends on:** Session 1 merged.

**Deliverable:**
1. Migration adding 7 columns to `fund_risk_metrics` (empirical_duration, empirical_duration_r2, credit_beta, credit_beta_r2, yield_proxy_12m, duration_adj_drawdown_1y, scoring_model)
2. Worker `risk_calc.py` modification: new Pass 1.7 (FI analytics) before scoring, `_batch_fetch_macro_yield_changes()`, FI fund classification, scoring_model assignment
3. `scoring_service.py` modification: `compute_fund_score()` gains `asset_class` + `fi_metrics` params, `resolve_scoring_weights()` dispatches to FI defaults, `_compute_fi_score()` with 5 FI components + normalization
4. `_DEFAULT_FI_SCORING_WEIGHTS` config (yield_consistency 0.20, duration_management 0.25, spread_capture 0.20, duration_adjusted_drawdown 0.25, fee_efficiency 0.10)
5. `FIMetrics` Protocol + `_FIMetricsAdapter`
6. Tests for scoring dispatch (equity fund → equity components, FI fund → FI components, same function different weights)

**Read:** plan §Phase 2 + §Phase 3 fully.

**Gate:**
- `alembic upgrade head` clean
- `alembic downgrade -1` clean
- Worker run against dev DB: verify `scoring_model = 'fixed_income'` set on FI funds
- `pytest tests/quant_engine/test_scoring_service.py` — existing + new tests green
- `lint-imports` — quant_engine contracts intact
- Run ELITE ranking: verify 300 total still holds (distribution shifts expected as FI funds get fair scores)

**Instruction for Opus:**
```
Read docs/plans/fixed_income_quant_engine.md sections "Fase 2" and "Fase 3" fully, and docs/plans/2026-04-12-fi-quant-execution-wrapper.md fully. Verify Session 1 merged (FI benchmarks seeded, analytics service exists). Implement Phase 2 (migration + worker Pass 1.7 FI analytics) and Phase 3 (scoring dispatch by asset_class in scoring_service.py). Run the worker to verify scoring_model assignment. Report including ELITE distribution shift.
```

### Session 3 — Consumer: Screener Gates + ELITE Validation + E2E (Phase 4 + 5 + 6)

**Branch:** `feat/fi-quant-session-3`
**Depends on:** Session 2 merged.

**Deliverable:**
1. Screener Layer 1: `fund_fixed_income` eliminatory gate (e.g., empirical_duration IS NOT NULL for FI funds)
2. Screener Layer 2: duration mandate fit (fund duration within mandate's target range)
3. Screener Layer 3: `FIQuantMetrics` dataclass for FI-specific quant scoring
4. ELITE ranking validation: run ELITE, verify 300 total, check FI fund distribution improved
5. E2E test: pick a specific FI fund, show score >70 on FI model vs ~50 on equity model
6. **ScoreCompositionPanel update:** render FI components (yield_consistency, duration_management, spread_capture, duration_adjusted_drawdown, fee_efficiency) when `scoring_model = "fixed_income"`, keep equity components for equity funds. Use `scoring_model` field to dispatch.

**Read:** plan §Phase 4 + §Phase 5 + §Phase 6 fully.

**Gate:**
- `make check` full green
- ELITE distribution: 300 total, FI funds now with scores >70 (vs ~50 before)
- E2E test: specific FI fund comparison (equity score vs FI score documented)
- ScoreCompositionPanel renders correct component bars for both equity and FI funds in FocusMode
- Screener ELITE filter shows FI funds with fair rankings (not penalized)

**Instruction for Opus:**
```
Read docs/plans/fixed_income_quant_engine.md sections "Fase 4", "Fase 5", and "Fase 6" fully, and docs/plans/2026-04-12-fi-quant-execution-wrapper.md fully. Verify Session 2 merged (scoring_model column exists, FI scoring weights applied). Implement screener FI gates + ELITE validation + E2E test + ScoreCompositionPanel FI rendering. The E2E test must show a specific FI fund scoring higher on the FI model than on the equity model. Report including before/after score comparison.
```

## Post-FI-Quant validation

After all 3 sessions merge:

```sql
-- Verify scoring_model distribution
SELECT scoring_model, COUNT(*), AVG(manager_score), MIN(manager_score), MAX(manager_score)
FROM fund_risk_metrics
WHERE calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics)
GROUP BY scoring_model;

-- Verify ELITE distribution by scoring_model
SELECT scoring_model, COUNT(*) FILTER (WHERE elite_flag) AS elite_count
FROM fund_risk_metrics
WHERE calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics)
GROUP BY scoring_model;

-- Verify FI analytics populated
SELECT
  COUNT(*) AS total_fi,
  COUNT(empirical_duration) AS with_duration,
  COUNT(credit_beta) AS with_credit_beta,
  COUNT(yield_proxy_12m) AS with_yield,
  COUNT(duration_adj_drawdown_1y) AS with_dad
FROM fund_risk_metrics
WHERE scoring_model = 'fixed_income'
  AND calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics);
```

**Expected outcome:** FI funds score higher (median ~60-65 instead of ~50) because the scoring model now measures what FI funds actually do well (yield, duration management, spread capture) instead of penalizing them with equity metrics (return consistency, information ratio, momentum).

## Valid escape hatches

1. DGS10 or BAA10Y data missing from `macro_data` → Tiingo post-merge operations haven't completed. Wait.
2. FI benchmark tickers return empty from Tiingo (not in Tiingo universe) → check ticker mapping. AGG/LQD/HYG/TIP/GOVT/EMB/SHY are iShares/Vanguard ETFs that should be in Tiingo.
3. `asset_class` field not available on fund data at scoring time → investigate how the worker knows a fund's asset class. May be from `instruments_universe.asset_class`, `strategy_label`, or `universe` field. Read the worker to find the correct source.
4. Scoring dispatch changes break existing equity scores → equity path must be DEFAULT and UNCHANGED. `asset_class="equity"` + `fi_metrics=None` → existing flow. Test explicitly.
5. ELITE total shifts from exactly 300 → scoring_model change redistributes scores. The 300-target logic is per-strategy with `round(300 * weight)`. If FI funds now score higher, they may displace equity funds in strategies that overlap. This is CORRECT behavior. Verify the total is still 300 ± rounding tolerance.

## Not valid escape hatches

- "Equity scoring path might break, let me skip the dispatch" → NO. Default equity path must work exactly as before. Test it.
- "OLS regressions are too complex for one commit" → NO. 40 lines of numpy per the plan. Ship it.
- "ScoreCompositionPanel FI rendering can wait for Phase 4 Builder" → NO. FocusMode is already live in the screener. Users clicking FI funds should see the correct component bars immediately.
