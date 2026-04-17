# Local DB State Reference -- 2026-04-16

Snapshot of the docker-compose local database after running all workers via the worker population runbook. Migration head: `0138_holdings_drift_alerts`. DB size: **9.7 GB**.

---

## 1. Global Regime Intelligence

| Metric | Value |
|--------|-------|
| Current regime | RISK_OFF |
| Stress score | 36.1 / 100 |
| Snapshot date | 2026-04-15 |
| Previous regime | RISK_ON (2026-04-13, stress 22.2) |
| Total snapshots | 2 |

The regime shifted from RISK_ON to RISK_OFF between 2026-04-13 and 2026-04-15. Signal inputs include VIX z-score, HY OAS, CFNAI, ICSA (initial claims). PERMIT signal flagged as stale (104 days, last data 2026-01-01).

---

## 2. Macro Data (FRED + Derived)

| Metric | Value |
|--------|-------|
| Distinct series | 83 |
| Total observations | 52,899 |
| Date range | 2016-01-01 to 2026-04-15 |
| Hypertable chunks | 125 |

Key series by category:

- **US economic**: GDP (A191RL1Q225SBEA), INDPRO, PAYEMS, UNRATE, JTSJOL, CFNAI, SAHMREALTIME, UMCSENT
- **Inflation**: CPIAUCSL, PCEPILFE
- **Rates**: DFF, DGS2, DGS10, SOFR, BAA10Y, MORTGAGE30US/15US
- **Financial conditions**: VIXCLS, NFCI, STLFSI4, BAMLH0A0HYM2, BAMLHE00EHYIEY
- **Credit**: TOTBKCR, TOTLL, DPSACBW027SBOG, CCLACBW027SBOG, DRCCLACBS
- **Housing**: CSUSHPINSA, HOUST, PERMIT, MSACSR + 18 Case-Shiller metro indices
- **Labor**: ICSA (initial claims), PAYEMS
- **Commodities**: DCOILWTICO, DCOILBRENTEU, DHHNGSP, PCOPPUSDM
- **International**: EU CPI, GDP, ECB rate; Japan/China/Brazil/India/Mexico CPI + output; EM bond spread

5 FRED series return 400 errors (deprecated): GPRH, WCSSTUS1, WCESTUS1, GOLDAMGBD228NLBM, PFERTINDEXM. 3 others intermittently fail (DRHMACBS, NETCIBAL, DRCILNFNQ). Total functional: ~75 direct + 8 derived.

---

## 3. Treasury Data

| Metric | Value |
|--------|-------|
| Distinct series | 278 |
| Total observations | 18,170 |
| Date range | 2016-03-28 to 2026-03-26 |
| Hypertable chunks | 123 |

Covers yield curves, debt outstanding, auction results, FX rates, interest expense.

---

## 4. External Data Sources

| Table | Rows | Scope | Source |
|-------|------|-------|--------|
| `ofr_hedge_fund_data` | 495 | global | OFR API |
| `bis_statistics` | 11,509 | global | BIS SDMX |
| `imf_weo_forecasts` | 8,033 | global | IMF DataMapper |
| `sec_insider_transactions` | 59,677 | global | SEC Form 345 |
| `sec_insider_sentiment` | 2,956 | global | Computed |

---

## 5. Fund Universe

### 5.1 Source Tables (before instruments_universe)

| Table | Total | Institutional | Excluded | Exclusion Reasons |
|-------|-------|---------------|----------|-------------------|
| `sec_manager_funds` | 62,728 | 35,241 | 27,487 | GAV < $3B (27,417), retirement (59), CIT (3), duplicate (6), insurance (1), SMA (1) |
| `sec_registered_funds` | 4,617 | 4,560 | 57 | retirement (24), sub-scale (28), target-date (5) |
| `sec_etfs` | 985 | 971 | 14 | retirement (10), leveraged/retail (4) |
| `esma_funds` | 10,436 | 10,429 | 7 | retirement/pension (7) |
| `sec_bdcs` | 196 | 196 | 0 | -- |
| `sec_money_market_funds` | 373 | 307 | 66 | retail MMF (65), retirement/insurance (1) |
| **Total** | **79,335** | **51,704** | **27,631** | |

### 5.2 instruments_universe

| Metric | Value |
|--------|-------|
| Total instruments | 9,079 |
| Institutional | 9,008 |
| Excluded | 71 |
| Active (with NAV) | 5,446 |
| By type | fund: 9,078, equity: 1 |

### 5.3 Materialized Views

| View | Rows | Description |
|------|------|-------------|
| `mv_unified_funds` | 104,793 | 6-universe fund catalog with prospectus stats |
| `mv_unified_assets` | 13,825 | Global instrument search |
| `mv_macro_latest` | 498 | Latest macro indicator values |
| `mv_macro_regional_summary` | 4 | Regional macro aggregation (US, EU, ASIA, EM) |

### 5.4 Strategy Label Distribution (mv_unified_funds, top 20)

| Label | Count |
|-------|-------|
| Private Equity | 24,578 |
| Real Estate | 6,589 |
| Multi-Strategy | 6,470 |
| Venture Capital | 4,137 |
| Hedge Fund | 3,514 |
| Structured Credit | 2,624 |
| International Equity | 2,480 |
| Other | 2,454 |
| Private Credit | 2,274 |
| Intermediate-Term Bond | 2,231 |
| Municipal Bond | 1,539 |
| Secondaries / Co-Invest | 1,027 |
| Infrastructure | 654 |
| Sector Equity | 634 |
| ESG/Sustainable Equity | 578 |
| Balanced | 570 |
| Large Growth | 563 |
| High Yield Bond | 509 |
| Energy | 483 |
| Co-Investment | 475 |

72,005 out of 104,793 funds in `mv_unified_funds` have a non-null `strategy_label` (68.7%). 42,318 have AUM >= $200M.

---

## 6. NAV Timeseries

| Metric | Value |
|--------|-------|
| Distinct instruments | 6,164 |
| Total observations | 20,138,181 |
| Date range | 1970-01-30 to 2026-04-10 |
| Hypertable chunks | 571 |

Average ~3,267 price points per instrument. Source: Yahoo Finance (daily via `instrument_ingestion` worker).

---

## 7. Benchmark NAV

| Metric | Value |
|--------|-------|
| Distinct benchmarks | 22 |
| Total observations | 125,554 |
| Date range | 1993-01-29 to 2026-04-10 |
| Hypertable chunks | 406 |

---

## 8. Fund Risk Metrics (Global, calc_date 2026-04-15)

| Metric | Count | Coverage |
|--------|-------|----------|
| Total instruments computed | 5,446 | 100% |
| Manager score | 5,446 | 100% |
| GARCH volatility | 5,446 | 100% |
| CVaR 95 conditional | 5,446 | 100% |
| DTW drift score | 5,042 | 92% |
| RSI-14 | 4,859 | 89% |
| Blended momentum | 4,857 | 89% |
| Bollinger Band position | 4,839 | 88% |
| 5Y annualized return | 4,472 | 82% |
| 10Y annualized return | 2,580 | 47% |

**Elite ranking (300 per regime):**

| Regime | Equity | Fixed Income | Alternatives | Cash |
|--------|--------|-------------|-------------|------|
| Expansion (RISK_ON) | 150 | 99 | 36 | 15 |
| Risk-Off | 114 | 108 | 39 | 39 |
| Inflation | 126 | 75 | 66 | 33 |
| Crisis | 75 | 105 | 45 | 75 |

Total `fund_risk_metrics` rows across all calc_dates: 43,061 (global: 42,878 across 8 calc_dates; org: 183).

---

## 9. Org-Scoped Data

### 9.1 Organizations

| Org ID | Instruments | Risk Metrics | calc_date |
|--------|-------------|-------------|-----------|
| `403d8392-...` | 168 | 183 rows | 2026-04-15 |
| `f1392e06-...` | 1 | 0 (empty) | -- |

### 9.2 Portfolio Construction

| Status | Count |
|--------|-------|
| succeeded | 2 |
| failed | 22 |

- Model portfolio NAV: 7,539 synthetic observations
- Portfolio snapshots: 9
- Portfolio stress results: 8
- Allocation blocks: 22
- Config defaults: 14

---

## 10. SEC Holdings & Filings

| Table | Rows | Granularity |
|-------|------|-------------|
| `sec_nport_holdings` | 2,025,754 | 1,215 funds, quarterly |
| `sec_13f_holdings` | 1,392,487 | 65 filers, quarterly |
| `sec_13f_diffs` | 1,083,433 | Computed quarter-over-quarter diffs |
| `sec_fund_classes` | 36,516 | Share classes (CIK->series->class->ticker) |
| `sec_managers` | 976,980 | SEC FOIA ADV bulk |
| `sec_manager_funds` | 62,728 | ADV Schedule D funds |

---

## 11. Wealth Vector Embeddings

| Metric | Value |
|--------|-------|
| Total chunks | 153,664 |
| Fund entity type | 125,164 (81.5%) |
| Firm entity type | 28,500 (18.5%) |
| Hypertable chunks | 1 |

Sources: ADV brochures, SEC manager profiles, 13F summaries, private funds (GAV >= $1B), SEC fund profiles, ESMA funds, ETFs, BDCs, MMFs, prospectus stats/returns, N-PORT holdings, share classes, org-scoped DD chapters, macro reviews.

---

## 12. Strategy Reclassification (Staging)

| Metric | Value |
|--------|-------|
| Total staged rows (all runs) | 937,846 |
| Latest run ID | `8ee413b8-e32d-4f76-ac2c-24a6aac5e6d7` |
| Latest run staged | 56,647 |
| Applied P0 (NULL to label) | 45 |
| Applied P1 (style refinement) | 113 |
| Applied P2 (asset class change) | 2,648 |
| Applied P3 (label removal) | 0 |
| Unchanged/skipped | 53,841 |

---

## 13. Hypertable Summary

| Hypertable | Chunks |
|------------|--------|
| `nav_timeseries` | 571 |
| `benchmark_nav` | 406 |
| `macro_data` | 125 |
| `treasury_data` | 123 |
| `model_portfolio_nav` | 122 |
| `macro_regime_history` | 120 |
| `sec_13f_holdings` | 96 |
| `sec_13f_diffs` | 94 |
| `_materialized_hypertable_90` | 54 |
| `sec_nport_holdings` | 30 |
| `bis_statistics` | 27 |
| `ofr_hedge_fund_data` | 21 |
| `esma_nav_history` | 14 |
| `audit_events` | 5 |
| `sec_mmf_metrics` | 4 |
| `fund_risk_metrics` | 3 |
| `portfolio_snapshots` | 2 |
| `macro_regional_snapshots` | 2 |
| `imf_weo_forecasts` | 1 |
| `wealth_vector_chunks` | 1 |

---

## 14. Top Tables by Disk Size

| Table | Size |
|-------|------|
| `sec_manager_brochure_text` | 695 MB |
| `strategy_reclassification_stage` | 273 MB |
| `sec_managers` | 272 MB |
| `instruments_universe` | 53 MB |
| `sec_manager_funds` | 49 MB |
| `vector_chunks` | 46 MB |
| `sec_insider_transactions` | 16 MB |
| `sec_fund_prospectus_stats` | 12 MB |

Note: `nav_timeseries` and `sec_nport_holdings` with their 20M+ and 2M+ rows respectively are stored across 571 and 30 hypertable chunks not reflected in this single-table view. Total DB: 9.7 GB.

---

## 15. Data Freshness Summary

| Data Source | Latest Date | Refresh Frequency |
|-------------|-------------|-------------------|
| Macro (FRED) | 2026-04-15 | Daily |
| Regime snapshot | 2026-04-15 | Daily |
| Global risk metrics | 2026-04-15 | Daily |
| Org risk metrics (403d) | 2026-04-15 | Daily |
| NAV timeseries | 2026-04-10 | Daily (market days) |
| Benchmark NAV | 2026-04-10 | Daily (market days) |
| Treasury | 2026-03-26 | Daily |
| N-PORT holdings | quarterly | Weekly worker |
| 13F holdings | quarterly | Weekly worker |
| SEC managers (FOIA) | monthly | Monthly worker |
| ESMA funds | weekly | Weekly worker |
| BIS statistics | quarterly | Quarterly worker |
| IMF forecasts | quarterly | Quarterly worker |
| Strategy reclassification | 2026-04-16 | On-demand |
| Universe sanitization | 2026-04-16 | On-demand |
| Materialized views | 2026-04-16 | After data changes |

---

## 16. Known Gaps

1. **10Y return coverage at 47%** -- only instruments with 10+ years of NAV history can have this metric. Not a data quality issue.
2. **DTW drift at 92%** -- funds with no `strategy_label` group under `__unclassified__` and may lack enough peers for DTW computation.
3. **22 failed construction runs** -- legacy runs from earlier development iterations; 2 recent runs succeeded.
4. **FRED series deprecation** -- 5 series permanently return 400 (removed from FRED). 3 others intermittent. Consider pruning the series list.
5. **Treasury data lag** -- latest observation 2026-03-26, ~20 days stale. Worker may need manual re-trigger.
6. **Org f1392e06 is empty** -- 1 instrument in `instruments_org` but no risk metrics computed (0 processable funds).
7. **Audit events fail for global operations** -- `organization_id` NOT NULL constraint on the hypertable prevents logging global batch operations (sanitization, reclassification). Non-blocking (data still applied).
