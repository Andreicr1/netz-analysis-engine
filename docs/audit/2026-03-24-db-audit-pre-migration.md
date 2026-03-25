# Database Audit Report — Pre-Migration to Timescale Cloud

**Date:** 2026-03-24
**Auditor:** Claude (automated)
**Target:** Timescale Cloud (`nvhhm6dwvh.keh9pcdgv1.tsdb.cloud.timescale.com:30124/tsdb`)

> **Key finding:** The local Docker PostgreSQL instance is **empty** (only 8 test audit_events).
> All production-grade data already resides in Timescale Cloud. This audit therefore reports
> on the **cloud DB state**, which is the authoritative source for the demo.

---

## Section A — Row Counts Summary

### Hypertables (time-series)

| Table | Type | Rows | Date Min | Date Max | Segments | Status |
|---|---|---|---|---|---|---|
| `macro_data` | hypertable (global) | 48,848 | 2016-01-01 | 2026-03-24 | 78 series | **OK** |
| `treasury_data` | hypertable (global) | 18,158 | 2016-03-28 | 2026-03-20 | 278 series | **OK** |
| `benchmark_nav` | hypertable (global) | 8,000 | 2024-03-25 | 2026-03-23 | 16 blocks | **OK** |
| `sec_13f_holdings` | hypertable (global) | 1,092,225 | 2000-06-30 | 2025-12-31 | 12 CIKs | **OK** |
| `sec_nport_holdings` | hypertable (global) | 75,514 | 2019-11-21 | 2026-03-23 | 40 CIKs | **OK** |
| `ofr_hedge_fund_data` | hypertable (global) | 475 | 2021-03-31 | 2026-02-28 | 23 series | **OK** (low volume expected) |
| `bis_statistics` | hypertable (global) | 11,489 | — | — | 43 countries, 3 indicators, 3 datasets | **OK** |
| `imf_weo_forecasts` | hypertable (global) | 8,033 | 1980 | 2030 | 44 countries, 4 indicators | **OK** |
| `nav_timeseries` | hypertable (org) | 0 | — | — | — | **EMPTY** |
| `fund_risk_metrics` | hypertable (org) | 0 | — | — | — | **EMPTY** |

### Global Relational Tables

| Table | Type | Rows | Status |
|---|---|---|---|
| `sec_managers` | global | 976,980 | **OK** |
| `sec_manager_funds` | global | 0 | **EMPTY** |
| `sec_manager_team` | global | 0 | **EMPTY** |
| `sec_manager_brochure_text` | global | 0 | **EMPTY** |
| `sec_cusip_ticker_map` | global | 17,837 | **OK** |
| `esma_funds` | global | 10,436 | **OK** |
| `esma_managers` | global | 658 | **OK** |
| `esma_isin_ticker_map` | global | 6,227 | **OK** |
| `instruments_global` | global | 231 | **OK** |
| `allocation_blocks` | global | 16 | **OK** |
| `macro_regional_snapshots` | global | 2 | **SPARSE** |

### Org-Scoped Relational Tables

| Table | Type | Rows | Orgs | Status |
|---|---|---|---|---|
| `instruments_universe` | org | 0 | 0 | **EMPTY** |
| `model_portfolios` | org | 0 | 0 | **EMPTY** |
| `strategic_allocation` | org | 0 | 0 | **EMPTY** |
| `portfolio_snapshots` | org | 0 | 0 | **EMPTY** |
| `dd_reports` | org | 0 | 0 | **EMPTY** |

### Continuous Aggregates

| Aggregate | Rows | Status |
|---|---|---|
| `benchmark_monthly_agg` | 400 | **OK** |
| `sec_13f_latest_quarter` | 19 | **OK** |
| `nav_monthly_returns_agg` | 0 | **EMPTY** (no nav_timeseries data) |
| `sec_13f_holdings_agg` | 0 | **EMPTY** (needs refresh) |
| `sec_13f_drift_agg` | 0 | **EMPTY** (needs refresh) |

---

## Section B — Quality Findings

### B.1 — NAV Timeseries Gaps
**Not applicable.** `nav_timeseries` is empty — no org-scoped instruments have been ingested yet.

### B.2 — Risk Metrics Without NAV History
**Not applicable.** `fund_risk_metrics` is also empty.

### B.3 — Model Portfolios
**Not applicable.** `model_portfolios` is empty — no live profiles exist yet.

### B.4 — Instruments Universe
**Not applicable.** `instruments_universe` is empty — no org has onboarded instruments.

### B.5 — ESMA: Funds Missing Yahoo Ticker (Screener Blind Spots)
- **7,507 out of 10,436 funds (71.9%) have no `yahoo_ticker`.**
- All 10,436 funds have an ISIN (PK), so they are identifiable.
- Ticker resolution is ongoing (via `esma_ingestion` worker). 2,929 funds (28.1%) resolved so far.
- **Impact:** Screener can filter/display by ISIN, but NAV time-series ingestion requires a ticker. Funds without tickers cannot have return data fetched until resolved.

### B.6 — ESMA: Domicile Breakdown
| Domicile | Count | % |
|---|---|---|
| LU | 8,535 | 81.8% |
| FR | 650 | 6.2% |
| AT | 381 | 3.7% |
| DE | 352 | 3.4% |
| LI | 201 | 1.9% |
| IE | 2 | 0.02% |
| Others (11) | 315 | 3.0% |

- **LU dominates (81.8%)** as expected for UCITS passported funds.
- **IE is surprisingly low at only 2 funds.** Ireland is typically the #2 UCITS domicile. This suggests the ESMA feed used may have been filtered or IE-domiciled funds are registered under different national competent authorities. **Flag for investigation.**
- LU + FR + AT + DE = 95.1% of total — geographic coverage is concentrated but credible.

### B.7 — ESMA: Manager Linkage Rate
- **100% linkage.** All 10,436 funds are linked to one of 658 managers.
- Top managers: Amundi (427), UBS (309), DWS (295), Eurizon (228), Allianz GI (212).

### B.8 — ESMA: NAV Date Coverage
**Not applicable.** `esma_funds` has no `nav_date` column — NAV data lives in `nav_timeseries` (currently empty).

### B.9 — SEC 13F: CIK Quality
- **12 CIKs ingested**, covering 1.09M holdings from 2000-06-30 to 2025-12-31.
- One CIK (`1393818`) appears as both zero-padded and unpadded — 7,720 + 241 = 7,961 holdings likely belong to the same filer. **Dedup needed.**
- One CIK (`0000355437`) has data only from 2000-06-30 to 2001-03-31 — historical-only filer, no recent filings.

### B.10 — SEC Managers: Registration Status
| Status | Count | % |
|---|---|---|
| `other` | 910,385 | 93.2% |
| `operating` | 45,208 | 4.6% |
| `Registered` | 15,963 | 1.6% |
| `investment` | 3,899 | 0.4% |
| (null) | 1,525 | 0.2% |

- 976,980 total managers ingested from SEC FOIA bulk feed.
- **93.2% classified as "other"** — most are non-IA entities in the SEC bulk data. This is expected for the full FOIA feed, which includes all SEC registrants.
- **15,963 "Registered"** = actual registered investment advisers (target population for wealth screener).
- **951,170 (97.4%) have no country set** — the FOIA feed stores state/country separately and most entries lack the country field.

### B.11 — SEC Manager Funds: EMPTY
`sec_manager_funds` has 0 rows. The ADV ingestion worker (`sec_adv_ingestion`) ingests manager-level data from the FOIA bulk CSV, but fund-level data (private fund details from Form ADV Part 1A, Schedule D, Section 7.B.1) has not been ingested yet. This is a **data gap** for the wealth screener's US fund analysis feature.

### B.12 — Continuous Aggregates: Stale
- `sec_13f_holdings_agg` and `sec_13f_drift_agg` are both 0 rows despite 1.09M underlying holdings. **Continuous aggregate refresh needed.**

### B.13 — Macro Regional Snapshots: SPARSE
Only 2 rows in `macro_regional_snapshots`. This table stores pre-computed regional macro summaries for the committee engine. Needs a `macro_committee_engine` run to populate.

---

## Section C — Migration Readiness

> **Context shift:** Since the local DB is empty, the migration question reverses.
> Data lives in Timescale Cloud already. The question is: **what still needs to be seeded?**

### Already Populated in Cloud (no migration needed)

| Table | Scope | Status | Notes |
|---|---|---|---|
| `macro_data` | global | **READY** | 48.8K rows, 78 series, current to 2026-03-24 |
| `treasury_data` | global | **READY** | 18.2K rows, 278 series, current to 2026-03-20 |
| `benchmark_nav` | global | **READY** | 8K rows, 16 blocks (all allocation blocks covered) |
| `sec_13f_holdings` | global | **READY** | 1.09M rows, 12 CIKs, 25 years of history |
| `sec_nport_holdings` | global | **READY** | 75.5K rows, 40 CIKs, current to 2026-03-23 |
| `ofr_hedge_fund_data` | global | **READY** | 475 rows, quarterly data |
| `bis_statistics` | global | **READY** | 11.5K rows, 43 countries |
| `imf_weo_forecasts` | global | **READY** | 8K rows, forecasts to 2030 |
| `sec_managers` | global | **READY** | 977K rows from FOIA bulk |
| `sec_cusip_ticker_map` | global | **READY** | 17.8K mappings |
| `esma_funds` | global | **READY** | 10.4K UCITS funds |
| `esma_managers` | global | **READY** | 658 managers |
| `esma_isin_ticker_map` | global | **READY** | 6.2K mappings |
| `instruments_global` | global | **READY** | 231 instruments (217 equity, 12 bond, 2 fund) |
| `allocation_blocks` | global | **READY** | 16 blocks (complete asset allocation framework) |
| `benchmark_monthly_agg` | aggregate | **READY** | 400 rows |
| `sec_13f_latest_quarter` | aggregate | **READY** | 19 rows |

### Needs Action Before Demo

| Table | Scope | Status | Action Required |
|---|---|---|---|
| `nav_timeseries` | org | **EMPTY** | Seed a demo org with instruments → run `instrument_ingestion` worker |
| `fund_risk_metrics` | org | **EMPTY** | Run `risk_calc` worker after NAV data exists |
| `instruments_universe` | org | **EMPTY** | Seed a demo org with instrument universe |
| `model_portfolios` | org | **EMPTY** | Seed demo model portfolios (at least 1 per profile) |
| `strategic_allocation` | org | **EMPTY** | Seed strategic allocation targets per profile |
| `portfolio_snapshots` | org | **EMPTY** | Run `portfolio_eval` worker after portfolio data exists |
| `dd_reports` | org | **EMPTY** | Generate via DD report engine after instruments exist |
| `sec_manager_funds` | global | **EMPTY** | Run ADV Part 1A Schedule D parsing (new worker needed or extend `sec_adv_ingestion`) |
| `sec_13f_holdings_agg` | aggregate | **EMPTY** | Run `CALL refresh_continuous_aggregate('sec_13f_holdings_agg', NULL, NULL);` |
| `sec_13f_drift_agg` | aggregate | **EMPTY** | Run `CALL refresh_continuous_aggregate('sec_13f_drift_agg', NULL, NULL);` |
| `macro_regional_snapshots` | global | **SPARSE** | Run `macro_committee_engine` to populate |

---

## Section D — Critical Values for Migration Step

### D.1 — Organization IDs
**No organization IDs found in any org-scoped table.** No tenant has been onboarded in Timescale Cloud yet. A demo organization must be created and seeded.

### D.2 — Live Model Portfolio Profiles
**0 live model portfolios.** Need to seed at least 3 profiles (conservative, balanced, aggressive) for demo.

### D.3 — NAV Date Range
**No NAV data.** `nav_timeseries` is empty. After seeding instruments and running `instrument_ingestion`, expect 2+ years of daily NAV history per instrument.

### D.4 — ESMA Totals Confirmed
- **10,436 UCITS funds** across 17 domiciles
- **658 ESMA managers** across 10+ countries (LU=275, IE=124, FR=87 top 3)
- **100% manager linkage** — all funds linked to a manager
- **2,929 funds (28.1%) have Yahoo tickers resolved** for NAV fetching

### D.5 — Blockers Before Demo

| # | Blocker | Severity | Resolution |
|---|---|---|---|
| 1 | **No demo tenant exists** — all org-scoped tables empty | **CRITICAL** | Run `seed_dev_tenant.py` or create org via Clerk + seed script |
| 2 | **sec_manager_funds empty** — US fund analysis screener has no data | **HIGH** | Extend `sec_adv_ingestion` to parse Schedule D fund details |
| 3 | **13F CIK dedup** — CIK `1393818` appears as both `0001393818` and `1393818` | **MEDIUM** | Normalize to zero-padded 10-digit format in ingestion |
| 4 | **ESMA ticker resolution at 28%** — 7,507 funds can't fetch NAV data | **MEDIUM** | Continue running `esma_ingestion` ticker resolver; 28% is sufficient for demo |
| 5 | **IE UCITS underrepresented** — only 2 funds vs expected hundreds | **MEDIUM** | Investigate ESMA feed source; may need Irish NCA registry supplement |
| 6 | **Continuous aggregates stale** — `sec_13f_holdings_agg` and `sec_13f_drift_agg` empty | **LOW** | One-time refresh command |
| 7 | **macro_regional_snapshots sparse** — only 2 rows | **LOW** | Run macro committee engine |

### Recommended Demo Seeding Sequence

1. Create demo org in Clerk → obtain `organization_id`
2. Seed `instruments_universe` with ~20-30 instruments (mix of equity, bond, fund)
3. Seed `strategic_allocation` with 3 profiles (conservative/balanced/aggressive)
4. Seed `model_portfolios` with 3 live portfolios
5. Run `instrument_ingestion` → populates `nav_timeseries`
6. Run `risk_calc` → populates `fund_risk_metrics`
7. Run `portfolio_eval` → populates `portfolio_snapshots`
8. Refresh continuous aggregates: `sec_13f_holdings_agg`, `sec_13f_drift_agg`
9. Run `macro_committee_engine` → populates `macro_regional_snapshots`
