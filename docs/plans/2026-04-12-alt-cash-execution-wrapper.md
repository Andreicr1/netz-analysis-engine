# Alternatives & Cash Scoring Engine — Execution Wrapper

**Date:** 2026-04-12
**Specification:** `docs/plans/alternatives_cash_scoring_engine.md` (authoritative spec)
**Status:** Ready for execution in 3 sprints
**Priority:** SCORING INTEGRITY GATE — must complete before Phase 4 Builder

## Context updates

### Alembic head

Current head after FI Quant: `0123_add_fixed_income_risk_metrics`. Cash/Alt migrations start at `0124+`. Verify via `alembic heads` before each sprint.

### Scoring dispatch state

After FI Quant, `scoring_service.py` dispatches on `asset_class`:
- `"equity"` → 6 equity components (original)
- `"fixed_income"` → 5 FI components (FI Quant)
- `"alternatives"` → falls through to equity (WRONG — this sprint fixes it)
- `"cash"` → falls through to equity (WRONG — this sprint fixes it)

### Classification state

After the classification hotfix (PR #120), `universe_sync.py` correctly classifies:
- equity: 3,914 funds
- fixed_income: 1,234 funds
- cash: 237 funds
- alternatives: 61 funds

### Existing data availability (confirmed)

- `sec_mmf_metrics`: 20k daily rows (Cash Sprint 1 data source)
- `sec_money_market_funds`: MMF catalog with `pct_weekly_liquid`, WAM
- `macro_data.DFF`: Fed Funds rate for yield spread computation
- `nav_timeseries`: 17.4M rows via Tiingo (for alternatives correlation/capture/beta)
- `benchmark_nav`: existing equity + FI benchmarks; 2 new blocks needed for Alt (QAI, DBMF)

## 3-sprint execution

### Sprint 1 — Cash/MMF Scoring

**Branch:** `feat/cash-scoring`
**Scope:** 5 columns + scoring + screener gates + worker pass
**Estimated duration:** 1 Opus session, ~2h

**Deliverable:**
1. Migration adding 5 Cash columns to `fund_risk_metrics`: `seven_day_net_yield`, `fed_funds_rate_at_calc`, `nav_per_share_mmf`, `pct_weekly_liquid`, `weighted_avg_maturity_days`
2. `quant_engine/cash_analytics_service.py` — pure-sync module computing Cash metrics from `sec_mmf_metrics` + `sec_money_market_funds` + `macro_data.DFF`
3. `scoring_service.py` — add `_DEFAULT_CASH_SCORING_WEIGHTS` (yield_vs_risk_free 0.30, nav_stability 0.25, liquidity_quality 0.20, maturity_discipline 0.15, fee_efficiency 0.10) + `_compute_cash_score()` + dispatch for `asset_class = "cash"`
4. `risk_calc.py` — new Pass for Cash analytics (fetch from sec_mmf_metrics, compute, store)
5. Screener: Layer 1 cash gate, Layer 3 CashQuantMetrics dataclass
6. `ScoreCompositionPanel.svelte` — render Cash components when `scoring_model = "cash"`
7. Unit tests + E2E test (MMF fund scored on Cash model vs equity model)
8. Update `mv_fund_risk_latest` to include new columns

**Key fix:** Remove `MIN_ANNUALIZED_VOL = 0.01` guard from Layer 3 for cash funds — this guard currently DISCARDS all MMFs from scoring, producing zero scores. Cash funds with vol ~0.5% should be scored, not discarded.

**Instruction for Opus:**
```
Read docs/plans/alternatives_cash_scoring_engine.md Cash Model section fully, and docs/plans/2026-04-12-alt-cash-execution-wrapper.md fully. Implement the Cash scoring model: migration (5 columns), analytics service, scoring dispatch, worker pass, screener gates, ScoreCompositionPanel cash rendering, E2E test. Fix the MIN_ANNUALIZED_VOL guard that discards MMFs. Verify with alembic heads for migration numbering. Report including Cash fund score comparison (cash model vs equity model).
```

### Sprint 2 — Alternatives Core (Analytics + Scoring Profiles)

**Branch:** `feat/alt-scoring-core`
**Depends on:** Sprint 1 merged (for clean scoring dispatch base)
**Scope:** analytics service + 7 columns + 5 scoring profiles
**Estimated duration:** 1 Opus session, ~3h (largest sprint — 5 profiles)

**Deliverable:**
1. Migration adding 7 Alt columns to `fund_risk_metrics`: `equity_correlation_252d`, `downside_capture_1y`, `upside_capture_1y`, `crisis_alpha_score`, `calmar_ratio_3y`, `inflation_beta`, `inflation_beta_r2`
2. 2 new allocation blocks: `alt_hedge_fund` (benchmark QAI), `alt_managed_futures` (benchmark DBMF) — seed migration
3. `quant_engine/alternatives_analytics_service.py` — pure-sync module with:
   - `compute_equity_correlation()` — 252d rolling correlation with SPY/VTI
   - `compute_capture_ratios()` — up/down capture vs equity benchmark
   - `compute_crisis_alpha()` — performance during equity drawdown periods (>10% peak-to-trough)
   - `compute_calmar_ratio()` — 3Y return / max drawdown
   - `compute_inflation_beta()` — OLS regression of returns vs CPI/TIPS spread changes
4. `scoring_service.py` — add 5 profile weight configs (REIT, Commodity, Gold, Hedge Fund, CTA) + `_compute_alternatives_score()` with profile sub-dispatch + dispatch for `asset_class = "alternatives"`
5. Profile resolution: `block_id` → profile mapping (org worker) or `strategy_label` → profile (global worker)
6. Unit tests with synthetic data for each profile

**Design principle:** All 5 components (diversification_value, income_generation, crisis_alpha, inflation_hedge, downside_protection, alpha_generation, fee_efficiency — pick the 5 used) are computed for ALL alt funds. Weights determine which matter per profile. A CTA with `income_generation=38` doesn't show that component (weight 0).

**Instruction for Opus:**
```
Read docs/plans/alternatives_cash_scoring_engine.md Alternatives Model section fully, and docs/plans/2026-04-12-alt-cash-execution-wrapper.md fully. Implement the Alternatives analytics service (correlation, capture, crisis alpha, Calmar, inflation beta), 5 scoring profiles (REIT, Commodity, Gold, Hedge Fund, CTA), scoring dispatch, 2 new benchmark blocks (QAI, DBMF). Unit tests per profile. Report including profile weight tables used.
```

### Sprint 3 — Alternatives Integration (Worker + Screener + E2E)

**Branch:** `feat/alt-scoring-integration`
**Depends on:** Sprint 2 merged
**Scope:** worker pass + screener gates + block mapping + ScoreComposition + E2E
**Estimated duration:** 1 Opus session, ~2h

**Deliverable:**
1. `risk_calc.py` — new Pass for Alternatives analytics (profile resolution, metric computation, scoring)
2. Screener: Layer 1 alternatives gate, Layer 3 AltQuantMetrics dataclass
3. `ScoreCompositionPanel.svelte` — render Alternatives components when `scoring_model = "alternatives"` (dispatch by profile shows different component names/weights)
4. E2E tests:
   - REIT fund: alt model score vs equity model score
   - Commodity fund: inflation_hedge component recognized
   - CTA fund: crisis_alpha component dominates
5. ELITE ranking validation: 300 total maintained, all 4 asset classes scored fairly
6. Update `mv_fund_risk_latest` with new columns

**Final validation:**
```sql
SELECT scoring_model, COUNT(*), AVG(manager_score)::numeric(5,1),
       COUNT(*) FILTER (WHERE elite_flag) AS elite
FROM fund_risk_metrics
WHERE calc_date = (SELECT MAX(calc_date) FROM fund_risk_metrics)
GROUP BY scoring_model ORDER BY scoring_model;
```

Expected: 4 rows (cash, equity, fixed_income, alternatives), each with appropriate avg_score and elite distribution matching allocation weights.

**Instruction for Opus:**
```
Read docs/plans/alternatives_cash_scoring_engine.md Integration section fully, and docs/plans/2026-04-12-alt-cash-execution-wrapper.md fully. Verify Sprint 2 merged (alternatives_analytics_service importable, 7 columns exist, 2 new blocks seeded). Implement worker pass, screener gates, ScoreCompositionPanel alternatives rendering (per-profile component dispatch), E2E tests for REIT/Commodity/CTA, ELITE validation. Report including 4-model scoring distribution table and ELITE per asset_class.
```

## Post-completion state

After all 3 sprints merge:

```python
# scoring_service.py dispatch — COMPLETE
match asset_class:
    case "equity":        → 6 equity components (original)
    case "fixed_income":  → 5 FI components (FI Quant)
    case "alternatives":  → 5 alt components × 5 profile weights (NEW)
    case "cash":          → 5 cash components (NEW)
```

ELITE ranking of 300 funds distributed across 4 allocation blocks is genuinely cross-asset fair. No class penalized by metrics of another class. Phase 4 Builder is unblocked with trustworthy scoring.

## Valid escape hatches

1. `sec_mmf_metrics` table doesn't have `seven_day_net_yield` column → investigate actual column names, adapt
2. QAI or DBMF tickers not in Tiingo → find alternative benchmark ETFs for hedge funds and managed futures
3. Crisis alpha computation requires identifying equity drawdown periods → use pre-computed drawdown periods from existing `fund_risk_metrics.max_drawdown_1y` on SPY/VTI benchmark, or compute inline
4. `MIN_ANNUALIZED_VOL` guard is used by other callers besides Layer 3 → make the fix conditional on `asset_class == "cash"`, not a global removal
5. Profile resolution from `strategy_label` is ambiguous for some funds → default to the most conservative profile (REIT if contains "real estate", else generic alternatives with equal weights)
