# Database Inventory Reference

**Last updated:** 2026-04-05
**Database:** Timescale Cloud (PostgreSQL 16 + TimescaleDB 2.26.1 + pgvector 0.8.2 + vectorscale 0.9.0)
**Migration head:** `0085_fix_13f_sector_mv_and_cusip_queue`
**Total tables:** 143 | **Total materialized views:** 6 | **Total views:** 5 (continuous aggregates) + 3 (regular)
**Hypertables:** 36 | **Continuous aggregates:** 5
**Database size:** 8.8 GB
**Extensions:** plpgsql, timescaledb (2.26.1), timescaledb_toolkit (1.22.0), vector (0.8.2), vectorscale (0.9.0), pg_trgm (1.6), pgcrypto (1.3), uuid-ossp (1.1), btree_gin (1.3), pg_buffercache (1.4), pg_stat_statements (1.10), amcheck (1.3), autoinc (1.0), postgres_fdw (1.1)

---

## Executive Summary

The Netz Analysis Engine database aggregates financial data from 7 authoritative sources spanning US institutional asset management (SEC), European UCITS funds (ESMA), and global macroeconomic indicators (FRED, Treasury, BIS, IMF, OFR). The database provides:

- **Performance Layer:** 6 Materialized Views (`mv_unified_funds`, `mv_unified_assets`, `mv_macro_latest`, `mv_macro_regional_summary`, `sec_insider_sentiment`, `sec_13f_manager_sector_latest`) + 5 Continuous Aggregates (`benchmark_monthly_agg`, `nav_monthly_returns_agg`, `sec_13f_holdings_agg`, `sec_13f_latest_quarter`, `sec_13f_drift_agg`) providing sub-100ms screener and global search queries
- **976,980 US investment managers** from SEC FOIA bulk data, including 17,488 registered advisers (16,712 with AUM, $149.2T combined) and 3,899 investment-status entities
- **62,728 private funds** from ADV Part 1 with `fund_type` (7 SEC categories) and `strategy_label` (37 granular strategies, 99.998% coverage)
- **4,617 US mutual funds and closed-end funds** in `sec_registered_funds` (3,652 mutual funds, 965 closed-end) — all with `strategy_label`
- **985 ETFs** in `sec_etfs` — N-CEN Q4 2025 with tracking difference, expense ratio, creation unit mechanics
- **196 BDCs** in `sec_bdcs` — business development companies (all = Private Credit strategy)
- **373 money market fund series** in `sec_money_market_funds` — N-MFP with WAM, WAL, 7-day yield, liquidity; **20,270 daily metric rows** in `sec_mmf_metrics` hypertable
- **36,516 share classes** in `sec_fund_classes` — **9,996 with expense ratios**, **8,293 with advisory fees** from OEF XBRL (N-CSR filings)
- **10,436 European UCITS funds** from 658 ESMA-registered managers across 25 countries, 17 domiciles, with `strategy_label` (100% coverage); 2,929 with Yahoo ticker
- **pgvector index** with 153,664 wealth vector chunks across 16 embedding sources + 2,064 credit vector chunks
- **1.39M institutional holdings** (13F-HR) from 65 institutional filers, spanning 96 quarters (2000 Q2 — 2025 Q4); **1.08M quarterly diffs** in `sec_13f_diffs`; **55 rows** in `sec_13f_manager_sector_latest` MV (top sector per filer, latest quarter)
- **8,950 instruments in global catalog** (`instruments_universe`, 5,446 active / 3,504 inactive) with **12.1M NAV rows** in `nav_timeseries` (6,164 instruments, 2016–2026) and **risk metrics** (11,555 rows in `fund_risk_metrics` for 6,074 instruments: CVaR, Sharpe, volatility, momentum, GARCH)
- **2.03M fund portfolio holdings** (N-PORT) from 1,215 CIKs across 30 quarters (2019 Q3 — 2026 Q4), 7,759 series with ISIN enrichment
- **17,502 annual prospectus returns** (`sec_fund_prospectus_returns`) for 2,086 series
- **72,157 fee/risk stats** (`sec_fund_prospectus_stats`) for 20,390 series — management fees, expense ratios, turnover, best/worst quarter, average annual returns
- **59,677 insider transactions** (Form 3/4/5) from SEC EDGAR, covering 3,759 issuers and 17,435 owners (2005–2026); **2,956 issuer-quarter rows** in `sec_insider_sentiment` MV
- **153,834 brochure text segments** from 14,195 managers in `sec_manager_brochure_text`
- **2,373 manager team members** in `sec_manager_team`
- **78 macroeconomic time series** (48,905 rows) from FRED covering rates, spreads, housing, employment, and commodities
- **278 US Treasury series** (18,170 rows) covering debt, auction results, interest rates, and foreign exchange
- **Global financial stability data** from BIS (43 countries, 11,509 rows), IMF (44 countries, 8,033 rows), and OFR (495 rows of hedge fund industry metrics)
- **94,419 rows** in `mv_unified_funds` screener (62,728 private + 28,762 registered US + 2,929 UCITS)
- **13,825 rows** in `mv_unified_assets` global search index

---

## 1. Performance Layer

### 1.1 Materialized Views

#### `mv_unified_funds` (Screener Engine) — 94,419 rows, 43 MB

| Attribute | Value |
|---|---|
| **Purpose** | Single source of truth for the Fund Screener |
| **Sources** | `sec_registered_funds`, `sec_etfs`, `sec_bdcs`, `sec_manager_funds`, `esma_funds`, `sec_money_market_funds` |
| **Enrichments** | Manager names, AUM (USD), `investment_geography`, `has_13f_overlay`, prospectus stats (`expense_ratio_pct`, `avg_annual_return_1y/10y`), fund flags (`is_index`, `is_target_date`, `is_fund_of_fund`), share class data (`series_id/name`, `class_id/name`), `vintage_year` |
| **Deduplication** | `DISTINCT ON (external_id)` across all universes |
| **Universe breakdown** | `private_us`: 62,728 / `registered_us`: 28,762 / `ucits_eu`: 2,929 |
| **Disclosure flags** | `has_holdings`: 2,952 / `has_nav`: 21,219 / `has_13f_overlay`: 37 |

**Columns (31):** `universe`, `external_id`, `name`, `ticker`, `isin`, `region`, `fund_type`, `strategy_label`, `aum_usd`, `currency`, `domicile`, `manager_name`, `manager_id`, `inception_date`, `total_shareholder_accounts`, `investor_count`, `series_id`, `series_name`, `class_id`, `class_name`, `has_holdings`, `has_nav`, `has_13f_overlay`, `investment_geography`, `vintage_year`, `expense_ratio_pct`, `avg_annual_return_1y`, `avg_annual_return_10y`, `is_index`, `is_target_date`, `is_fund_of_fund`

**Indexes:**
- `idx_mv_unified_funds_ext_id` — UNIQUE BTree on `external_id`
- `idx_mv_unified_funds_aum` — BTree on `aum_usd DESC NULLS LAST`
- `idx_mv_unified_funds_name` — BTree on `name`
- `idx_mv_unified_funds_ticker` — BTree on `ticker`
- `idx_mv_unified_funds_isin` — BTree on `isin`
- `idx_mv_unified_funds_universe` — BTree on `universe`
- `idx_mv_unified_funds_fund_type` — BTree on `fund_type`
- `idx_mv_unified_funds_manager` — BTree on `manager_name`
- `idx_mv_unified_funds_mgr_id` — BTree on `manager_id` WHERE NOT NULL
- `idx_mv_unified_funds_mgr_ticker` — BTree on `(manager_id, ticker)` WHERE NOT NULL
- `idx_mv_unified_funds_strategy_aum` — BTree on `(strategy_label, aum_usd DESC)` WHERE NOT NULL
- `idx_mv_unified_funds_type_ticker` — BTree on `(fund_type, ticker)` WHERE ticker NOT NULL

#### `mv_unified_assets` (Global Search Index) — 13,825 rows, 3.8 MB

| Attribute | Value |
|---|---|
| **Purpose** | High-performance header search (Cmd+K) |
| **Coverage** | Internal Instruments + ESMA Funds + SEC Equities/ETFs |
| **Columns** | `id`, `name`, `ticker`, `isin`, `asset_class`, `source`, `geography` |
| **Indexes** | Unique on `(id, source)`, BTree on `name`, `ticker`, `isin` |

#### `mv_macro_latest` — 493 rows

Latest value per macro indicator series (FRED + Treasury). Used for dashboard cards.

#### `mv_macro_regional_summary` — 4 rows

Regional macro aggregation (4 regions). Used for macro dashboard.

#### `sec_insider_sentiment` — 2,956 rows

Aggregated buy/sell signals per issuer per quarter from `sec_insider_transactions`.

#### `sec_13f_manager_sector_latest` — 55 rows

Latest quarter top sector allocation per 13F filer. One row per CIK: the sector with the highest `sector_value` in the most recent `report_date`. Columns: `cik`, `report_date`, `sector`, `sector_value`, `sector_weight`. Refreshed by `sec_refresh` worker and post-ingestion in `sec_13f_ingestion` worker (migration 0085 fixed initial empty state via DROP + CREATE).

### 1.2 Continuous Aggregates (TimescaleDB)

| View | Source Hypertable | Purpose |
|---|---|---|
| `nav_monthly_returns_agg` | `nav_timeseries` | Monthly NAV open/close, trading days, avg return, volatility |
| `benchmark_monthly_agg` | `benchmark_nav` | Monthly benchmark performance |
| `sec_13f_holdings_agg` | `sec_13f_holdings` | Quarterly sector allocation per CIK |
| `sec_13f_latest_quarter` | `sec_13f_holdings` | Latest quarter total equity value + position count per CIK |
| `sec_13f_drift_agg` | `sec_13f_diffs` | Quarterly churn count per CIK |

### 1.3 Refresh Automation

Materialized Views are updated using `REFRESH MATERIALIZED VIEW CONCURRENTLY` to ensure zero-downtime for reads.

| Trigger Worker | Event | Refresh Utility |
|---|---|---|
| `esma_ingestion` | After UCITS sync | `view_refresh.refresh_screener_views()` |
| `sec_bulk_ingestion` | After quarterly SEC load | `view_refresh.refresh_screener_views()` |
| `sec_adv_ingestion` | After monthly ADV load | `view_refresh.refresh_screener_views()` |
| `nport_fund_discovery` | After discovering new US funds | `view_refresh.refresh_screener_views()` |
| `macro_ingestion` | After FRED load | `macro_view_refresh.refresh_macro_views()` |
| `treasury_ingestion` | After Treasury load | `macro_view_refresh.refresh_macro_views()` |
| `sec_13f_ingestion` | After 13F holdings load | `REFRESH MATERIALIZED VIEW CONCURRENTLY sec_13f_manager_sector_latest` |
| `sec_refresh` | After continuous agg refresh | `REFRESH MATERIALIZED VIEW CONCURRENTLY sec_13f_manager_sector_latest` |

---

## 2. Data Sources & Workers

### 2.1 SEC EDGAR — Investment Advisers (ADV)

| Attribute | Value |
|---|---|
| **Source** | SEC FOIA Bulk CSV + IAPD XML Feeds (Form ADV Part 1A structured data) |
| **Worker** | `sec_adv_ingestion` (lock ID 900_022) |
| **Enrichment** | `iapd_xml_parser.py` — streaming XML parser for IA_FIRM_SEC_Feed / IA_FIRM_STATE_Feed |
| **Frequency** | Monthly (CSV bulk) + on-demand (XML enrichment via env vars or CLI) |
| **Table** | `sec_managers` |
| **Rows** | 976,980 |
| **Storage** | 271 MB |

**`sec_managers` schema (27 columns):** PK `crd_number` (text). Key fields: `cik`, `firm_name`, `sec_number`, `registration_status` (Registered: 17,488, investment: 3,899, operating: 45,208, other: 910,385), `aum_total` (bigint), `aum_discretionary`, `aum_non_discretionary`, `total_accounts`, `fee_types` (JSONB), `client_types` (JSONB), `state`, `country`, `website`, `compliance_disclosures`, `last_adv_filed_at`, `private_fund_count`, `hedge_fund_count`, `pe_fund_count`, `vc_fund_count`, `real_estate_fund_count`, `securitized_fund_count`, `liquidity_fund_count`, `other_fund_count`, `total_private_fund_assets`.

**Indexes:** `sec_managers_pkey` (crd_number), `idx_sec_managers_aum` (aum_total DESC), `idx_sec_managers_cik`, `idx_sec_managers_name_trgm` (GIN pg_trgm), `idx_sec_managers_reg_status`, `idx_sec_managers_registration_status`, `idx_sec_managers_registered_aum`, `idx_sec_managers_investment`, `idx_sec_managers_status_aum`, `idx_sec_managers_compliance_aum`, `idx_sec_managers_client_types_gin` (GIN jsonb_path_ops), `idx_sec_managers_private_fund_count`, `idx_sec_managers_last_adv_filed`.

### 2.2 SEC EDGAR — Private Funds (ADV Schedule D)

| Attribute | Value |
|---|---|
| **Source** | Form ADV Part 1 PDFs (checkbox image xref detection for fund_type) |
| **Worker** | `sec_adv_ingestion` (same as managers) |
| **Enrichment** | `backfill_strategy_label.py` — 3-layer keyword classifier for strategy_label |
| **Table** | `sec_manager_funds` |
| **Rows** | 62,728 |
| **Storage** | 20 MB |

**`sec_manager_funds` schema (12 columns):** PK `id` (UUID). Key fields: `crd_number`, `fund_name`, `fund_id`, `gross_asset_value` (bigint), `fund_type` (7 SEC categories), `is_fund_of_funds`, `investor_count`, `strategy_label` (37 strategies, 62,727/62,728 coverage), `vintage_year`.

**Fund type distribution:**
| Fund Type | Count |
|---|---|
| Private Equity Fund | 28,683 |
| Hedge Fund | 13,804 |
| Other Private Fund | 6,675 |
| Real Estate Fund | 5,636 |
| Venture Capital Fund | 4,509 |
| Securitized Asset Fund | 3,339 |
| Liquidity Fund | 81 |

**Indexes:** `sec_manager_funds_pkey` (id), `uq_sec_manager_funds_crd_name` (UNIQUE crd_number, fund_name), `idx_sec_manager_funds_crd_type` (crd_number, fund_type), `idx_sec_manager_funds_type` (fund_type WHERE NOT NULL), `idx_smf_gav` (gross_asset_value DESC WHERE NOT NULL), `idx_smf_strategy` (strategy_label WHERE NOT NULL), `ix_sec_manager_funds_vintage_year`.

### 2.3 SEC EDGAR — Registered Funds (N-PORT / N-CEN)

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR N-PORT headers + N-CEN quarterly filings |
| **Worker** | `nport_fund_discovery` (lock 900_024), `sec_bulk_ingestion` (lock 900_050) |
| **Table** | `sec_registered_funds` |
| **Rows** | 4,617 (3,652 mutual funds + 965 closed-end) |
| **Storage** | 1.9 MB |

**`sec_registered_funds` schema (45 columns):** PK `cik` (text). Key fields: `crd_number`, `fund_name`, `fund_type` (mutual_fund/closed_end), `ticker`, `isin`, `series_id`, `class_id`, `total_assets`, `total_shareholder_accounts`, `inception_date`, `strategy_label` (100% coverage), `currency`, `domicile`. N-CEN enrichment (27 columns): `is_index` (77 funds), `is_non_diversified`, `is_target_date` (11), `is_fund_of_fund` (124), `is_master_feeder`, `lei`, `management_fee`, `net_operating_expenses`, `has_expense_limit/waived`, `return_before/after_fees`, `nav_per_share`, `market_price_per_share`, lending/borrowing flags, `ncen_accession_number`, `ncen_report_date`, `ncen_fund_id`.

### 2.4 SEC EDGAR — ETFs

| Attribute | Value |
|---|---|
| **Source** | SEC N-CEN Q4 2025 |
| **Worker** | `sec_bulk_ingestion` (lock 900_050) |
| **Table** | `sec_etfs` |
| **Rows** | 985 |

**`sec_etfs` schema (34 columns):** PK `series_id` (varchar). Key fields: `cik`, `fund_name`, `ticker`, `isin`, `strategy_label` (73/985 with labels), `asset_class`, `index_tracked`, `is_index`, `is_in_kind_etf`, `creation_unit_size`, `pct_in_kind_creation/redemption`, `tracking_difference_gross/net`, `management_fee`, `net_operating_expenses`, `return_before/after_fees`, `monthly/daily_avg_net_assets`, `nav_per_share`, `market_price_per_share`, `has_expense_limit`, `ncen_report_date`, `domicile`, `currency`, `inception_date`, `crd_number`.

### 2.5 SEC EDGAR — BDCs

| Attribute | Value |
|---|---|
| **Source** | SEC N-CEN |
| **Worker** | `sec_bulk_ingestion` (lock 900_050) |
| **Table** | `sec_bdcs` |
| **Rows** | 196 |

**`sec_bdcs` schema:** PK `series_id`. Same structure as ETFs minus tracking/creation fields. All BDCs default `strategy_label = 'Private Credit'`.

### 2.6 SEC EDGAR — Money Market Funds

| Attribute | Value |
|---|---|
| **Source** | SEC N-MFP filings |
| **Worker** | `sec_bulk_ingestion` (lock 900_050) |
| **Tables** | `sec_money_market_funds` (373 rows), `sec_mmf_metrics` (20,270 rows, hypertable) |

**`sec_money_market_funds` schema (32 columns):** PK `series_id`. Key fields: `cik`, `fund_name`, `mmf_category` (CHECK constraint), `strategy_label`, `is_govt_fund`, `is_retail`, `is_exempt_retail`, `weighted_avg_maturity`, `weighted_avg_life`, `seven_day_gross_yield`, `net_assets`, `shares_outstanding`, `pct_daily/weekly_liquid_latest`, `seeks_stable_nav`, `stable_nav_price`, `investment_adviser`, `crd_number`.

**`sec_mmf_metrics` schema (12 columns):** Hypertable on `metric_date`. PK `(metric_date, series_id, class_id)`. Fields: `accession_number`, `seven_day_net_yield`, `daily_gross_subscriptions/redemptions`, `pct_daily/weekly_liquid`, `total_daily/weekly_liquid_assets`.

### 2.7 SEC EDGAR — Share Classes & XBRL Fees

| Attribute | Value |
|---|---|
| **Source** | N-PORT headers (discovery) + N-CSR XBRL (OEF taxonomy) |
| **Worker** | `nport_fund_discovery` + `sec_bulk_ingestion` |
| **Table** | `sec_fund_classes` |
| **Rows** | 36,516 (9,996 with expense ratios, 8,293 with advisory fees) |
| **Storage** | 9.8 MB |

**`sec_fund_classes` schema (16 columns):** PK `(cik, series_id, class_id)` (composite). Key fields: `series_name`, `class_name`, `ticker`, `fund_name`, `expense_ratio_pct`, `advisory_fees_paid`, `expenses_paid`, `avg_annual_return_pct`, `net_assets`, `holdings_count`, `portfolio_turnover_pct`, `perf_inception_date`, `xbrl_accession`, `xbrl_period_end`.

### 2.8 SEC EDGAR — Prospectus Data

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR RR1 filings (bar chart data) + prospectus fee/risk tables |
| **Worker** | `sec_bulk_ingestion` |
| **Tables** | `sec_fund_prospectus_returns` (17,502), `sec_fund_prospectus_stats` (72,157) |
| **Storage** | 1.8 MB + 12 MB |

**`sec_fund_prospectus_returns` schema (5 columns):** PK `(series_id, year)`. Fields: `annual_return_pct`, `filing_date`, `created_at`.

**`sec_fund_prospectus_stats` schema (26 columns):** PK `(series_id, class_id)`. Fields: `filing_date`, `management_fee_pct`, `expense_ratio_pct`, `net_expense_ratio_pct`, `fee_waiver_pct`, `distribution_12b1_pct`, `acquired_fund_fees_pct`, `other_expenses_pct`, `portfolio_turnover_pct`, `expense_example_1y/3y/5y/10y`, `bar_chart_best/worst_qtr_pct`, `bar_chart_ytd_pct`, `avg_annual_return_1y/5y/10y`.

### 2.9 SEC EDGAR — N-PORT Holdings

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR N-PORT XML filings |
| **Worker** | `nport_ingestion` (lock 900_018) |
| **Table** | `sec_nport_holdings` (hypertable on `report_date`) |
| **Rows** | 2,025,754 |
| **Coverage** | 1,215 CIKs, 7,759 series, 30 quarters (2019-09 — 2026-10) |

**`sec_nport_holdings` schema (17 columns):** PK `(report_date, cik, cusip)`. Fields: `isin`, `series_id`, `issuer_name`, `asset_class`, `sector`, `market_value`, `quantity`, `currency`, `pct_of_nav`, `is_restricted`, `fair_value_level`.

**Indexes:** `idx_sec_nport_holdings_cik_date`, `idx_sec_nport_holdings_cusip_date`, `idx_sec_nport_holdings_series_date`.

### 2.10 SEC EDGAR — 13F Holdings

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR 13F-HR filings (edgartools) |
| **Worker** | `sec_13f_ingestion` (lock 900_021) |
| **Tables** | `sec_13f_holdings` (1,392,487 rows, hypertable), `sec_13f_diffs` (1,083,433 rows, hypertable) |
| **Coverage** | 65 filers, 96 quarters (2000-06 — 2025-12) |

**`sec_13f_holdings` schema (16 columns):** PK `(report_date, cik, cusip)`. Fields: `filing_date`, `accession_number`, `issuer_name`, `asset_class`, `shares`, `market_value`, `discretion`, `voting_sole/shared/none`, `sector`.

**Indexes:** `idx_sec_13f_holdings_cik_report_date`, `idx_sec_13f_holdings_cusip_report_date` (INCLUDE cik, shares, market_value), `idx_sec_13f_holdings_sector`.

### 2.11 SEC EDGAR — Insider Transactions (Form 3/4/5)

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR Form 345 bulk TSV |
| **Worker** | `form345_ingestion` (lock 900_051) |
| **Table** | `sec_insider_transactions` |
| **Rows** | 59,677 |
| **Coverage** | 3,759 issuers, 17,435 owners (2005-11 — 2026-12) |
| **Storage** | 16 MB |

**`sec_insider_transactions` schema (16 columns):** PK `trans_sk` (bigint serial). Fields: `accession_number`, `issuer_cik`, `issuer_ticker`, `owner_cik`, `owner_name`, `owner_relationship`, `owner_title`, `trans_date`, `period_of_report`, `document_type`, `trans_code`, `trans_acquired_disp`, `trans_shares`, `trans_price_per_share`, `trans_value`, `shares_owned_after`.

### 2.12 SEC EDGAR — Manager Brochures

| Attribute | Value |
|---|---|
| **Source** | ADV Part 2A brochures (PDF text extraction) |
| **Worker** | `bulk_extract_brochures.py` script |
| **Table** | `sec_manager_brochure_text` |
| **Rows** | 153,834 segments from 14,195 managers |
| **Storage** | 695 MB |

**`sec_manager_brochure_text` schema (5 columns):** PK `(crd_number, section, filing_date)`. Fields: `content` (text), `created_at`.

### 2.13 SEC EDGAR — Manager Teams

| Attribute | Value |
|---|---|
| **Table** | `sec_manager_team` |
| **Rows** | 2,373 |
| **Storage** | 2.9 MB |

### 2.14 SEC EDGAR — CUSIP Resolution

| Attribute | Value |
|---|---|
| **Source** | `sec_13f_holdings` + `sec_nport_holdings` (unique CUSIPs) |
| **Worker** | `cusip_resolution` (lock ID 900_025) |
| **API** | OpenFIGI v3 batch mapping (100 CUSIPs/request, 250 req/min with key) |
| **Frequency** | On-demand (via `POST /workers/run-cusip-resolution`) |
| **Tables** | `sec_cusip_ticker_map` (33,248 rows), `_cusip_resolve_queue` (26,077 rows) |

**`sec_cusip_ticker_map` schema (12 columns):** PK `cusip` (text). Fields: `ticker`, `issuer_name`, `exchange`, `security_type`, `figi`, `composite_figi`, `resolved_via` (openfigi/unresolved), `is_tradeable`, `last_verified_at`, `issuer_cik`.

**`_cusip_resolve_queue` schema (2 columns):** PK `cusip` (text). Fields: `issuer_name`. Consumed by `cusip_resolution` worker (drains resolved entries, discovers new unresolved CUSIPs from 13F/N-PORT). Of 26,077 queued entries, 21,213 are already resolved in the map; 4,864 remain pending.

**Resolution flow:** Worker drains queue → discovers new unresolved CUSIPs from holdings → resolves via OpenFIGI batch API (exponential backoff, never-raises) → upserts to `sec_cusip_ticker_map` → cleans resolved entries from queue.

### 2.15 SEC EDGAR — Other Auxiliary Tables

| Table | Rows | Purpose |
|---|---|---|
| `sec_entity_links` | 121 | Cross-entity linkages (CIK ↔ CRD ↔ series) |
| `sec_fund_style_snapshots` | 0 | Style analysis snapshots (unused) |
| `sec_institutional_allocations` | 0 | Institutional allocation hypertable (unused) |

### 2.16 ESMA — European UCITS Funds

| Attribute | Value |
|---|---|
| **Source** | ESMA Fund Register |
| **Worker** | `esma_ingestion` (no advisory lock) |
| **Frequency** | Weekly |
| **Tables** | `esma_funds` (10,436), `esma_managers` (658) |
| **Storage** | 3.2 MB (funds) |

**`esma_funds` schema (11 columns):** PK `isin`. Fields: `fund_name`, `esma_manager_id` (FK), `domicile` (17 domiciles), `fund_type`, `host_member_states` (ARRAY), `yahoo_ticker` (2,929/10,436 with tickers), `ticker_resolved_at`, `strategy_label` (100% coverage).

**`esma_managers` schema (10 columns):** PK `esma_id`. Fields: `lei`, `company_name`, `country` (25 countries — LU:275, IE:124, FR:87, SE:41, DE:31, BE:17, AT:15...), `authorization_status`, `fund_count`, `sec_crd_number`.

**Auxiliary tables:**
| Table | Rows | Purpose |
|---|---|---|
| `esma_isin_ticker_map` | 6,227 | ISIN → Yahoo ticker resolution |
| `esma_nav_history` | 19,481 | Historical NAV for ESMA funds (hypertable on `nav_date`) |

### 2.17 Instruments & NAV

| Attribute | Value |
|---|---|
| **Workers** | `universe_sync` (lock 900_070), `instrument_ingestion` (lock 900_010) |
| **Tables** | `instruments_universe` (8,950), `instruments_org` (17), `nav_timeseries` (12,127,189) |

**`instruments_universe` schema (14 columns):** PK `instrument_id` (UUID). Fields: `instrument_type` (fund: 8,949, equity: 1), `name`, `isin` (UNIQUE), `ticker` (UNIQUE), `bloomberg_ticker`, `asset_class`, `geography` (north_america: 5,437, unknown: 9), `investment_geography`, `currency`, `is_active` (5,446 active / 3,504 inactive), `attributes` (JSONB — aum_usd, sec_cik, sec_crd, credit_rating_sp, market_cap_usd, etc.).

**Indexes:** `instruments_universe_pkey`, `uq_iu_isin`, `uq_iu_ticker`, `idx_iu_attrs_gin` (GIN jsonb_path_ops), `idx_iu_fund_aum`, `idx_iu_equity_mcap`, `idx_iu_bond_rating`, `ix_instruments_universe_geography`, `ix_instruments_universe_investment_geography`.

**`instruments_org` schema (6 columns):** PK `id` (UUID). Fields: `organization_id` (RLS), `instrument_id` (FK), `block_id`, `approval_status`, `selected_at`. 17 rows (org-scoped selections).

**`nav_timeseries` schema (8 columns):** Hypertable on `nav_date`. PK `(instrument_id, nav_date)`. Fields: `nav`, `return_1d`, `aum_usd`, `currency`, `source`, `return_type`. **12.1M rows**, 6,164 instruments, range 2016-03-28 — 2026-03-29.

**Indexes:** `nav_timeseries_pkey`, `nav_timeseries_nav_date_idx`, `ix_nav_timeseries_instrument_date` (WHERE return_1d NOT NULL).

### 2.18 Fund Risk Metrics

| Attribute | Value |
|---|---|
| **Worker** | `risk_calc` (lock 900_007) |
| **Table** | `fund_risk_metrics` (hypertable on `calc_date`) |
| **Rows** | 11,555 (6,074 instruments, date range 2026-03-27 — 2026-03-30) |

**`fund_risk_metrics` schema (42 columns):** PK `(instrument_id, calc_date)`. Fields: `organization_id` (nullable), CVaR/VaR (1m/3m/6m/12m), returns (1m/3m/6m/1y/3y_ann), `volatility_1y`, `max_drawdown_1y/3y`, `sharpe_1y/3y`, `sortino_1y`, `alpha_1y`, `beta_1y`, `information_ratio_1y`, `tracking_error_1y`, `manager_score`, `score_components` (JSONB), `dtw_drift_score`, momentum signals (`rsi_14`, `bb_position`, `nav_momentum_score`, `flow_momentum_score`, `blended_momentum_score`), GARCH (`volatility_garch`, `cvar_95_conditional`), peer percentiles (`peer_strategy_label`, `peer_sharpe/sortino/return/drawdown_pctl`, `peer_count`).

### 2.19 Macroeconomic Data — FRED

| Attribute | Value |
|---|---|
| **Source** | FRED API (~65 series: 4 regions + global + credit + 20 Case-Shiller metros) |
| **Worker** | `macro_ingestion` (lock 43) |
| **Frequency** | Daily |
| **Table** | `macro_data` (hypertable on `obs_date`, 1mo chunks) |
| **Rows** | 48,905 (78 series) |

### 2.20 Macroeconomic Data — US Treasury

| Attribute | Value |
|---|---|
| **Source** | US Treasury API (rates, debt, auctions, FX, interest) |
| **Worker** | `treasury_ingestion` (lock 900_011) |
| **Frequency** | Daily |
| **Table** | `treasury_data` (hypertable on `obs_date`, 1mo chunks) |
| **Rows** | 18,170 (278 series) |

### 2.21 Macroeconomic Data — OFR Hedge Fund Monitor

| Attribute | Value |
|---|---|
| **Source** | OFR API (leverage, AUM, strategy, repo, stress) |
| **Worker** | `ofr_ingestion` (lock 900_012) |
| **Frequency** | Weekly |
| **Table** | `ofr_hedge_fund_data` (hypertable on `obs_date`, 3mo chunks) |
| **Rows** | 495 |

### 2.22 Macroeconomic Data — BIS

| Attribute | Value |
|---|---|
| **Source** | BIS SDMX API (credit gap, DSR, property) |
| **Worker** | `bis_ingestion` (lock 900_014) |
| **Frequency** | Quarterly |
| **Table** | `bis_statistics` (hypertable on `period`, 1yr chunks) |
| **Rows** | 11,509 (43 countries) |

### 2.23 Macroeconomic Data — IMF WEO

| Attribute | Value |
|---|---|
| **Source** | IMF DataMapper API (GDP, inflation, fiscal) |
| **Worker** | `imf_ingestion` (lock 900_015) |
| **Frequency** | Quarterly |
| **Table** | `imf_weo_forecasts` (hypertable on `period`, 1yr chunks) |
| **Rows** | 8,033 (44 countries) |

### 2.24 Benchmarks

| Attribute | Value |
|---|---|
| **Source** | Yahoo Finance |
| **Worker** | `benchmark_ingest` (lock 900_004) |
| **Frequency** | Daily |
| **Table** | `benchmark_nav` (hypertable on `nav_date`, 1mo chunks) |
| **Rows** | 8,032 |

### 2.25 Macro Regional Snapshots

| Attribute | Value |
|---|---|
| **Table** | `macro_regional_snapshots` (hypertable on `as_of_date`) |
| **Rows** | 3 |

---

## 3. Vector Embedding Layer

### 3.1 Wealth Vector Chunks — 153,664 rows, 2.1 GB

| Attribute | Value |
|---|---|
| **Worker** | `wealth_embedding` (lock 900_041, daily 03:00 UTC) |
| **Model** | OpenAI text-embedding-3-large |
| **RLS** | None (WHERE-clause filtering, `organization_id` nullable) |

**Source type breakdown (16 sources):**

| Source Type | Entity Type | Count |
|---|---|---|
| `prospectus_stats` | fund | 72,157 |
| `brochure` | firm | 13,491 |
| `sec_fund_series_profile` | fund | 13,229 |
| `fund_classes` | fund | 13,229 |
| `esma_fund_profile` | fund | 10,436 |
| `nport_holdings` | fund | 7,759 |
| `sec_private_funds` | firm | 6,348 |
| `sec_manager_profile` | firm | 5,680 |
| `sec_fund_profile` | fund | 4,690 |
| `esma_manager_profile` | firm | 2,916 |
| `prospectus_returns` | fund | 2,086 |
| `sec_etf_profile` | fund | 985 |
| `sec_mmf_profile` | fund | 373 |
| `sec_bdc_profile` | fund | 196 |
| `sec_13f_summary` | firm | 65 |
| `dd_chapter` | fund | 24 |

**Indexes:** `wealth_vector_chunks_pkey` (id), `ix_wvc_entity` (entity_type, entity_id), `ix_wvc_entity_id`, `ix_wvc_firm_crd`, `ix_wvc_org`, `ix_wvc_org_entity`, `ix_wvc_source`.

### 3.2 Credit Vector Chunks — 2,064 rows, 46 MB

| Attribute | Value |
|---|---|
| **Purpose** | Deal-centric RAG for credit vertical |
| **RLS** | Yes (`organization_id` required in all queries) |

---

## 4. Multi-Tenant Architecture

### 4.1 RLS Policy Summary

**78 RLS policies** across 75 tables. All use the `(SELECT current_setting('app.current_organization_id'))::uuid` subselect pattern for performance.

**Tables with RLS (96 total with `organization_id` column):**

| Category | Tables |
|---|---|
| **Credit Domain** | `deals`, `deal_cashflows`, `deal_documents`, `deal_events`, `deal_ic_briefs`, `deal_intelligence_profiles`, `deal_qualifications`, `deal_underwriting_artifacts`, `pipeline_deals`, `pipeline_deal_decisions`, `pipeline_deal_documents`, `pipeline_deal_stage_history`, `pipeline_qualification_results`, `pipeline_qualification_rules`, `pipeline_alerts`, `ic_memos`, `memo_chapters`, `memo_evidence_packs`, `investment_memorandum_drafts` |
| **Wealth Domain** | `dd_reports`, `dd_chapters`, `instruments_org`, `screening_runs`, `screening_results`, `instrument_screening_metrics`, `model_portfolios`, `model_portfolio_nav`, `portfolio_assets`, `portfolio_views`, `rebalance_events`, `universe_approvals`, `macro_reviews`, `wealth_content`, `wealth_documents`, `wealth_document_versions`, `wealth_generated_reports`, `wealth_vector_chunks` (WHERE-clause only, no RLS policy) |
| **Portfolio** | `portfolio_snapshots`, `strategic_allocation`, `tactical_positions`, `allocation_blocks`, `blended_benchmarks`, `active_investments`, `fund_investments`, `fund_memberships`, `lipper_ratings`, `manager_profiles` |
| **Documents** | `documents`, `document_access_policies`, `document_chunks`, `document_classifications`, `document_governance_profile`, `document_registry`, `document_reviews`, `document_root_folders`, `document_versions`, `evidence_documents` |
| **AI / Copilot** | `ai_queries`, `ai_questions`, `ai_answers`, `ai_answer_citations`, `ai_responses` |
| **Config / Admin** | `vertical_config_overrides`, `prompt_overrides`, `prompt_override_versions`, `tenant_assets` |
| **Reporting** | `report_runs`, `report_schedules`, `report_pack_sections`, `monthly_report_packs`, `investor_statements`, `board_monitoring_briefs` |
| **Risk / Monitoring** | `alerts`, `backtest_runs`, `fund_risk_metrics`, `nav_snapshots`, `performance_drift_flags`, `strategy_drift_alerts`, `asset_obligations`, `asset_valuation_snapshots`, `obligation_register`, `obligation_evidence_map`, `investment_risk_registry`, `cash_impact_flags`, `covenant_status_register`, `governance_alerts`, `periodic_review_reports` |
| **Knowledge** | `knowledge_anchors`, `knowledge_entities`, `knowledge_links` |
| **Review** | `review_assignments`, `review_checklist_items`, `review_events` |
| **Actions** | `actions`, `deal_conversion_events`, `deal_risk_flags`, `deep_review_validation_runs`, `eval_runs` |

### 4.2 Global Tables (No RLS, No organization_id)

| Table | Rows | Purpose |
|---|---|---|
| `sec_managers` | 976,980 | SEC investment advisers |
| `sec_manager_funds` | 62,728 | Private funds |
| `sec_registered_funds` | 4,617 | US mutual/closed-end funds |
| `sec_etfs` | 985 | ETFs |
| `sec_bdcs` | 196 | BDCs |
| `sec_money_market_funds` | 373 | Money market funds |
| `sec_mmf_metrics` | 20,270 | MMF daily metrics |
| `sec_fund_classes` | 36,516 | Share classes |
| `sec_fund_prospectus_returns` | 17,502 | Annual returns |
| `sec_fund_prospectus_stats` | 72,157 | Fee/risk stats |
| `sec_nport_holdings` | 2,025,754 | N-PORT holdings |
| `sec_13f_holdings` | 1,392,487 | 13F holdings |
| `sec_13f_diffs` | 1,083,433 | 13F diffs |
| `sec_insider_transactions` | 59,677 | Insider trades |
| `sec_manager_brochure_text` | 153,834 | Brochure text |
| `sec_manager_team` | 2,373 | Manager teams |
| `sec_cusip_ticker_map` | 33,248 | CUSIP map |
| `sec_entity_links` | 121 | Entity links |
| `esma_funds` | 10,436 | UCITS funds |
| `esma_managers` | 658 | ESMA managers |
| `esma_isin_ticker_map` | 6,227 | ISIN ticker map |
| `esma_nav_history` | 19,481 | ESMA NAV |
| `instruments_universe` | 8,950 | Global instrument catalog |
| `nav_timeseries` | 12,127,189 | NAV prices |
| `benchmark_nav` | 8,032 | Benchmark prices |
| `macro_data` | 48,905 | FRED macro |
| `treasury_data` | 18,170 | Treasury data |
| `ofr_hedge_fund_data` | 495 | OFR hedge funds |
| `bis_statistics` | 11,509 | BIS statistics |
| `imf_weo_forecasts` | 8,033 | IMF forecasts |
| `macro_regional_snapshots` | 3 | Regional snapshots |
| `vertical_config_defaults` | 13 | Default config |
| `allocation_blocks` | 16 | Block definitions |

---

## 5. Hypertable Inventory (36 total)

| Hypertable | Time Column | Scope | Rows | Purpose |
|---|---|---|---|---|
| `nav_timeseries` | `nav_date` | global | 12,127,189 | Fund NAV prices |
| `sec_nport_holdings` | `report_date` | global | 2,025,754 | N-PORT holdings |
| `sec_13f_holdings` | `report_date` | global | 1,392,487 | 13F institutional holdings |
| `sec_13f_diffs` | `quarter_to` | global | 1,083,433 | 13F quarter-over-quarter diffs |
| `macro_data` | `obs_date` | global | 48,905 | FRED macro indicators |
| `esma_nav_history` | `nav_date` | global | 19,481 | ESMA fund NAV |
| `treasury_data` | `obs_date` | global | 18,170 | US Treasury data |
| `fund_risk_metrics` | `calc_date` | org | 11,555 | Risk/return/momentum metrics |
| `bis_statistics` | `period` | global | 11,509 | BIS financial stability |
| `sec_mmf_metrics` | `metric_date` | global | 20,270 | MMF daily metrics |
| `imf_weo_forecasts` | `period` | global | 8,033 | IMF WEO forecasts |
| `benchmark_nav` | `nav_date` | global | 8,032 | Benchmark NAV |
| `ofr_hedge_fund_data` | `obs_date` | global | 495 | OFR hedge fund monitor |
| `sec_institutional_allocations` | `report_date` | global | 0 | Institutional allocations |
| `macro_regional_snapshots` | `as_of_date` | global | 3 | Regional macro snapshots |
| `macro_regime_history` | `regime_date` | global | 0 | Regime detection history |
| `macro_snapshots` | `as_of_date` | global | 0 | Macro snapshots |
| `model_portfolio_nav` | `nav_date` | org | 0 | Synthesized portfolio NAV |
| `portfolio_snapshots` | `snapshot_date` | org | 0 | Portfolio evaluation snapshots |
| `strategy_drift_alerts` | `detected_at` | org | 0 | Drift detection alerts |
| `audit_events` | `created_at` | org | 0 | Immutable audit trail |
| `asset_valuation_snapshots` | `created_at` | org | 0 | Asset valuation snapshots |
| `cash_impact_flags` | `created_at` | org | 0 | Cash impact flags |
| `covenant_status_register` | `created_at` | org | 0 | Covenant status |
| `deal_conversion_events` | `created_at` | org | 0 | Deal conversion events |
| `deal_events` | `created_at` | org | 0 | Deal lifecycle events |
| `deal_risk_flags` | `created_at` | org | 0 | Deal risk flags |
| `deep_review_validation_runs` | `created_at` | global | 0 | Deep review validation |
| `eval_runs` | `started_at` | org | 0 | Evaluation runs |
| `governance_alerts` | `created_at` | org | 0 | Governance alerts |
| `investment_risk_registry` | `created_at` | org | 0 | Investment risk registry |
| `nav_snapshots` | `created_at` | org | 0 | NAV snapshots |
| `performance_drift_flags` | `created_at` | org | 0 | Performance drift flags |
| `periodic_review_reports` | `created_at` | org | 0 | Periodic reviews |
| `pipeline_alerts` | `created_at` | org | 0 | Pipeline alerts |
| `pipeline_deal_stage_history` | `changed_at` | org | 0 | Deal stage history |

---

## 6. Org-Scoped Data (Sample Tenant)

| Table | Rows | Purpose |
|---|---|---|
| `dd_reports` | 16 | Due diligence reports |
| `dd_chapters` | 104 | DD report chapters (8 per report) |
| `model_portfolios` | 84 | Model portfolios |
| `instruments_org` | 17 | Org-selected instruments |
| `allocation_blocks` | 16 | Allocation blocks |
| `vertical_config_overrides` | 15 | Config overrides |
| `macro_reviews` | 8 | Weekly macro reviews |
| `screening_runs` | 4 | Screening executions |
| `screening_results` | 41 | Screening results |
| `wealth_generated_reports` | 1 | Generated PDF reports |

---

## 7. Storage Summary

| Rank | Table/View | Size | Rows |
|---|---|---|---|
| 1 | `wealth_vector_chunks` | 2,115 MB | 153,664 |
| 2 | `sec_manager_brochure_text` | 695 MB | 153,834 |
| 3 | `sec_managers` | 271 MB | 976,980 |
| 4 | `vector_chunks` | 46 MB | 2,064 |
| 5 | `mv_unified_funds` | 43 MB | 94,419 |
| 6 | `sec_manager_funds` | 20 MB | 62,728 |
| 7 | `sec_insider_transactions` | 16 MB | 59,677 |
| 8 | `sec_fund_prospectus_stats` | 12 MB | 72,157 |
| 9 | `sec_fund_classes` | 9.8 MB | 36,516 |
| 10 | `instruments_universe` | 7.8 MB | 8,950 |
| — | **Hypertables (compressed)** | **~5.7 GB** | **~18.8M** |
| — | **Total database** | **8.8 GB** | — |

**Note:** Hypertable sizes (nav_timeseries: 12.1M rows, sec_nport_holdings: 2M, sec_13f_holdings: 1.4M, sec_13f_diffs: 1.1M) are stored in compressed TimescaleDB chunks and not reflected in `pg_class` sizes above.

---

## 8. Data Ingestion Workers (Complete Reference)

| Worker | Lock ID | Scope | Target Table(s) | Source | Frequency |
|---|---|---|---|---|---|
| `macro_ingestion` | 43 | global | `macro_data` | FRED API (~78 series) | Daily |
| `drift_check` | 42 | org | `strategy_drift_alerts` | Computed (DTW drift) | Daily |
| `benchmark_ingest` | 900_004 | global | `benchmark_nav` | Yahoo Finance | Daily |
| `risk_calc` | 900_007 | org | `fund_risk_metrics` | Computed | Daily |
| `portfolio_eval` | 900_008 | org | `portfolio_snapshots` | Computed | Daily |
| `instrument_ingestion` | 900_010 | global | `nav_timeseries` | Yahoo Finance | Daily |
| `treasury_ingestion` | 900_011 | global | `treasury_data` | US Treasury API | Daily |
| `ofr_ingestion` | 900_012 | global | `ofr_hedge_fund_data` | OFR API | Weekly |
| `bis_ingestion` | 900_014 | global | `bis_statistics` | BIS SDMX API | Quarterly |
| `imf_ingestion` | 900_015 | global | `imf_weo_forecasts` | IMF DataMapper API | Quarterly |
| `nport_ingestion` | 900_018 | global | `sec_nport_holdings` | SEC EDGAR N-PORT XML | Weekly |
| `sec_13f_ingestion` | 900_021 | global | `sec_13f_holdings`, `sec_13f_diffs`, `sec_13f_manager_sector_latest` (MV refresh) | SEC EDGAR 13F-HR | Weekly |
| `sec_adv_ingestion` | 900_022 | global | `sec_managers`, `sec_manager_funds` | SEC FOIA CSV + IAPD XML | Monthly |
| `nport_fund_discovery` | 900_024 | global | `sec_registered_funds`, `sec_fund_classes` | SEC EDGAR N-PORT headers | Weekly |
| `cusip_resolution` | 900_025 | global | `sec_cusip_ticker_map`, `_cusip_resolve_queue` | OpenFIGI batch API | On-demand |
| `sec_refresh` | 900_016 | global | `sec_13f_holdings_agg`, `sec_13f_drift_agg` (CA refresh), `sec_13f_manager_sector_latest` (MV refresh), Redis cache | Computed | On-demand |
| `portfolio_nav_synthesizer` | 900_030 | org | `model_portfolio_nav` | Computed (weighted NAV) | Daily |
| `wealth_embedding` | 900_041 | global | `wealth_vector_chunks` | OpenAI text-embedding-3-large | Daily |
| `sec_bulk_ingestion` | 900_050 | global | `sec_etfs`, `sec_bdcs`, `sec_money_market_funds`, `sec_mmf_metrics`, `sec_registered_funds`, `sec_fund_prospectus_*` | SEC DERA bulk ZIPs | Quarterly |
| `form345_ingestion` | 900_051 | global | `sec_insider_transactions` | SEC EDGAR Form 345 TSV | Quarterly |
| `universe_sync` | 900_070 | global | `instruments_universe` | SEC/ESMA catalog | Weekly |
| `esma_ingestion` | — | global | `esma_funds`, `esma_managers` | ESMA Fund Register | Weekly |

---

## 9. Row Count Summary (All Tables)

| Table | Rows | Scope |
|---|---|---|
| `nav_timeseries` | 12,127,189 | global |
| `sec_nport_holdings` | 2,025,754 | global |
| `sec_13f_holdings` | 1,392,487 | global |
| `sec_13f_diffs` | 1,083,433 | global |
| `sec_managers` | 976,980 | global |
| `wealth_vector_chunks` | 153,664 | global/org |
| `sec_manager_brochure_text` | 153,834 | global |
| `sec_fund_prospectus_stats` | 72,157 | global |
| `sec_manager_funds` | 62,728 | global |
| `sec_insider_transactions` | 59,677 | global |
| `macro_data` | 48,905 | global |
| `sec_fund_classes` | 36,516 | global |
| `sec_cusip_ticker_map` | 33,248 | global |
| `_cusip_resolve_queue` | 26,077 | global |
| `sec_mmf_metrics` | 20,270 | global |
| `esma_nav_history` | 19,481 | global |
| `treasury_data` | 18,170 | global |
| `sec_fund_prospectus_returns` | 17,502 | global |
| `fund_risk_metrics` | 11,555 | org |
| `bis_statistics` | 11,509 | global |
| `esma_funds` | 10,436 | global |
| `instruments_universe` | 8,950 | global |
| `imf_weo_forecasts` | 8,033 | global |
| `benchmark_nav` | 8,032 | global |
| `esma_isin_ticker_map` | 6,227 | global |
| `sec_registered_funds` | 4,617 | global |
| `sec_manager_team` | 2,373 | global |
| `vector_chunks` | 2,064 | org |
| `sec_etfs` | 985 | global |
| `esma_managers` | 658 | global |
| `ofr_hedge_fund_data` | 495 | global |
| `sec_money_market_funds` | 373 | global |
| `sec_bdcs` | 196 | global |
| `sec_entity_links` | 121 | global |
| `dd_chapters` | 104 | org |
| `model_portfolios` | 84 | org |
| `screening_results` | 41 | org |
| `allocation_blocks` | 16 | global |
| `dd_reports` | 16 | org |
| `instruments_org` | 17 | org |
| `vertical_config_overrides` | 15 | org |
| `vertical_config_defaults` | 13 | global |
| `macro_reviews` | 8 | org |
| `screening_runs` | 4 | org |
| `macro_regional_snapshots` | 3 | global |
| `wealth_generated_reports` | 1 | org |
| *~97 remaining tables* | 0 | *various* |

**Materialized view row counts:**

| View | Rows |
|---|---|
| `mv_unified_funds` | 94,419 |
| `mv_unified_assets` | 13,825 |
| `sec_insider_sentiment` | 2,956 |
| `mv_macro_latest` | 493 |
| `mv_macro_regional_summary` | 4 |
| `sec_13f_manager_sector_latest` | 55 |

**Total data rows across key tables:** ~32.5M
