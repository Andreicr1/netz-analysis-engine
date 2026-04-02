# Database Inventory Reference

**Last updated:** 2026-04-02
**Database:** Timescale Cloud (PostgreSQL 16 + TimescaleDB + pgvector)
**Migration head:** `0078_consolidated_screener_views`
**Total tables:** ~135 | **Total data rows:** ~26.5M across key tables

---

## Executive Summary

The Netz Analysis Engine database aggregates financial data from 7 authoritative sources spanning US institutional asset management (SEC), European UCITS funds (ESMA), and global macroeconomic indicators (FRED, Treasury, BIS, IMF, OFR). The database provides:

- **Performance Layer (New):** Consolidated Materialized Views (`mv_unified_funds`, `mv_unified_assets`) providing sub-100ms screener and global search queries by pre-calculating geography logic, AUM normalization, and cross-universe deduplication.
- **976,980 US investment managers** from SEC FOIA bulk data + IAPD XML enrichment, including 15,963 registered investment advisers managing $50+ trillion in combined AUM, with 99.5% Form ADV Part 1A coverage on fund managers (AUM, fees, client types, compliance)
- **62,728 private funds** from ADV Part 1 PDFs with `fund_type` (7 SEC categories via checkbox image detection) and `strategy_label` (37 granular strategies via 3-layer keyword classifier)
- **4,617 US mutual funds and closed-end funds** in `sec_registered_funds` — enriched from 16 quarters of N-CEN data (2,232/3,652 mutual funds, $11.97T AUM coverage) + OEF XBRL fees via N-CSR
- **985 ETFs** in `sec_etfs` — N-CEN Q4 2025 with tracking difference, expense ratio, creation unit mechanics
- **196 BDCs** in `sec_bdcs` — business development companies (all = Private Credit strategy)
- **373 money market fund series** in `sec_money_market_funds` — N-MFP with WAM, WAL, 7-day yield, liquidity; **20,270 daily metric rows** in `sec_mmf_metrics` hypertable
- **36,516 share classes** in `sec_fund_classes` — **8,278 with expense ratios** from OEF XBRL (N-CSR filings), covering $100.9T in AUM across 615 fund families (Vanguard, Capital Group, Fidelity, BlackRock, etc.)
- **10,436 European UCITS funds** from 658 ESMA-registered managers across 25 countries, with `strategy_label` (31 categories, 69.7% coverage)
- **pgvector index** with 17 embedding sources covering all fund universes (SEC managers/funds/13F/private + ETF/BDC/MMF + ESMA enriched + prospectus stats/returns + N-PORT holdings + fund classes + DD chapters + macro reviews)
- **1.09M institutional holdings** (13F-HR) from 12 major institutional investors, with 25 years of quarterly history
- **5,461 active instruments in global catalog** (`instruments_universe`, 8,950 total) with **10Y NAV history** (**12.1M rows** in `nav_timeseries`, 2016-2026) and **risk metrics** (**8,346 rows** in `fund_risk_metrics` for 6,074 instruments: CVaR, Sharpe, volatility, momentum, GARCH). Instruments without Yahoo NAV or AUM auto-deactivated. Org-scoped selection via `instruments_org` (RLS)
- **2.03M fund portfolio holdings** (N-PORT) from 1,215 CIKs across 24 quarters (2020 Q1 — 2025 Q4), top 50 holdings per fund/quarter, with 7,759 series and ISIN enrichment
- **17,502 annual prospectus returns** (`sec_fund_prospectus_returns`) for 2,086 series (2012-2025) — bar chart data from RR1 filings
- **72,157 fee/risk stats** (`sec_fund_prospectus_stats`) for 20,390 series — management fees, expense ratios, turnover, best/worst quarter, average annual returns
- **59,677 insider transactions** (Form 3/4/5) from SEC EDGAR in `sec_insider_transactions`, with `sec_insider_sentiment` materialized view aggregating buy/sell signals per issuer per quarter (2,956 issuer-quarters with P/S activity)
- **78 macroeconomic time series** from FRED covering rates, spreads, housing, employment, and commodities
- **278 US Treasury series** covering debt, auction results, interest rates, and foreign exchange
- **Global financial stability data** from BIS (43 countries), IMF (44 countries, forecasts to 2030), and OFR (hedge fund industry metrics)

---

## 1. Performance Layer (Migration 0078)

To support the **Unified Fund Catalog** and **Global Search** at scale, the database implements a pre-computed Materialized View layer. This eliminates the need for expensive `UNION ALL` queries and complex text parsing during API requests.

### 1.1 `mv_unified_funds` (Screener Engine)

| Attribute | Value |
|---|---|
| **Purpose** | Single source of truth for the Fund Screener |
| **Sources** | `sec_registered_funds`, `sec_etfs`, `sec_bdcs`, `sec_manager_funds`, `esma_funds`, `sec_money_market_funds` |
| **Enrichments** | Manager names, AUM (USD), `investment_geography` (keyword-based), `has_13f_overlay` |
| **Indexes** | Unique GIN/BTree on `external_id`, `name`, `ticker`, `isin`, `aum_usd` |
| **Deduplication** | `DISTINCT ON (external_id)` across all universes |

### 1.2 `mv_unified_assets` (Global Search Index)

| Attribute | Value |
|---|---|
| **Purpose** | High-performance header search (Cmd+K) |
| **Coverage** | Internal Instruments + ESMA Funds + SEC Equities/ETFs |
| **Indexes** | Unique on `(id, source)`, GIN on `name`, `ticker`, `isin` |

### 1.3 Refresh Automation

Materialized Views are updated using `REFRESH MATERIALIZED VIEW CONCURRENTLY` to ensure zero-downtime for reads.

| Trigger Worker | Event | Refresh Utility |
|---|---|---|
| `esma_ingestion` | After UCITS sync | `view_refresh.refresh_screener_views()` |
| `sec_bulk_ingestion` | After quarterly SEC load | `view_refresh.refresh_screener_views()` |
| `sec_adv_ingestion` | After monthly ADV load | `view_refresh.refresh_screener_views()` |
| `nport_fund_discovery`| After discovering new US funds | `view_refresh.refresh_screener_views()` |

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

... [rest of file unchanged] ...
