# Database Inventory Reference

**Last updated:** 2026-03-29
**Database:** Timescale Cloud (PostgreSQL 16 + TimescaleDB + pgvector)
**Migration head:** `0069_globalize_instruments_nav`
**Total tables:** ~135 | **Total data rows:** ~24.6M across key tables

---

## Executive Summary

The Netz Analysis Engine database aggregates financial data from 7 authoritative sources spanning US institutional asset management (SEC), European UCITS funds (ESMA), and global macroeconomic indicators (FRED, Treasury, BIS, IMF, OFR). The database provides:

- **976,980 US investment managers** from SEC FOIA bulk data + IAPD XML enrichment, including 15,963 registered investment advisers managing $50+ trillion in combined AUM, with 99.5% Form ADV Part 1A coverage on fund managers (AUM, fees, client types, compliance)
- **62,728 private funds** from ADV Part 1 PDFs with `fund_type` (7 SEC categories via checkbox image detection) and `strategy_label` (37 granular strategies via 3-layer keyword classifier)
- **4,617 US mutual funds and closed-end funds** in `sec_registered_funds` — enriched from 16 quarters of N-CEN data (2,232/3,652 mutual funds, $11.97T AUM coverage) + OEF XBRL fees via N-CSR
- **985 ETFs** in `sec_etfs` — N-CEN Q4 2025 with tracking difference, expense ratio, creation unit mechanics
- **196 BDCs** in `sec_bdcs` — business development companies (all = Private Credit strategy)
- **373 money market fund series** in `sec_money_market_funds` — N-MFP with WAM, WAL, 7-day yield, liquidity; **20,270 daily metric rows** in `sec_mmf_metrics` hypertable
- **36,516 share classes** in `sec_fund_classes` — **8,278 with expense ratios** from OEF XBRL (N-CSR filings), covering $100.9T in AUM across 615 fund families (Vanguard, Capital Group, Fidelity, BlackRock, etc.)
- **10,436 European UCITS funds** from 658 ESMA-registered managers across 25 countries, with `strategy_label` (31 categories, 69.7% coverage)
- **pgvector index** with 12 embedding sources covering all fund universes (SEC managers/funds/13F/private + ETF/BDC/MMF + ESMA enriched)
- **1.09M institutional holdings** (13F-HR) from 12 major institutional investors, with 25 years of quarterly history
- **8,950 instruments in global catalog** (`instruments_universe`) with **5,339+ having 10Y NAV history** (~10.4M+ rows in `nav_timeseries`). Org-scoped selection via `instruments_org` (RLS). Sources: SEC ETFs (925), mutual fund series (4,700), registered funds (358), BDCs (48), ESMA UCITS (2,929)
- **2.03M fund portfolio holdings** (N-PORT) from 1,215 CIKs across 24 quarters (2020 Q1 — 2025 Q4), top 50 holdings per fund/quarter, with 7,759 series and ISIN enrichment
- **17,502 annual prospectus returns** (`sec_fund_prospectus_returns`) for 2,086 series (2012-2025) — bar chart data from RR1 filings
- **72,157 fee/risk stats** (`sec_fund_prospectus_stats`) for 20,390 series — management fees, expense ratios, turnover, best/worst quarter, average annual returns
- **59,677 insider transactions** (Form 3/4/5) from SEC EDGAR in `sec_insider_transactions`, with `sec_insider_sentiment` materialized view aggregating buy/sell signals per issuer per quarter (2,956 issuer-quarters with P/S activity)
- **78 macroeconomic time series** from FRED covering rates, spreads, housing, employment, and commodities
- **278 US Treasury series** covering debt, auction results, interest rates, and foreign exchange
- **Global financial stability data** from BIS (43 countries), IMF (44 countries, forecasts to 2030), and OFR (hedge fund industry metrics)

---

## 1. Data Sources & Workers

### 1.1 SEC EDGAR — Investment Advisers (ADV)

| Attribute | Value |
|---|---|
| **Source** | SEC FOIA Bulk CSV + IAPD XML Feeds (Form ADV Part 1A structured data) |
| **Worker** | `sec_adv_ingestion` (lock ID 900_022) |
| **Enrichment** | `iapd_xml_parser.py` — streaming XML parser for IA_FIRM_SEC_Feed / IA_FIRM_STATE_Feed |
| **Frequency** | Monthly (CSV bulk) + on-demand (XML enrichment via env vars or CLI) |
| **Table** | `sec_managers` |
| **Rows** | 976,980 |

**Data sources:** The FOIA CSV provides the base population (976,980 entities). The IAPD XML feeds (Form ADV Part 1A) enrich with structured Item 5 (AUM, accounts, fees, client types), Item 1 (website), Item 11 (compliance disclosures), and filing metadata. SEC feed (23,037 SEC-registered firms) updated 16,595 rows; STATE feed (21,532 state-registered firms) updated 237 additional rows.

#### Registration Breakdown

| Status | Count | % | Description |
|---|---|---|---|
| `other` | 910,385 | 93.2% | Non-IA entities in SEC bulk data |
| `operating` | 45,208 | 4.6% | Operating entities (broker-dealers, etc.) |
| `Registered` | 15,963 | 1.6% | **Registered Investment Advisers** (target population) |
| `investment` | 3,899 | 0.4% | Investment companies |
| (null) | 1,525 | 0.2% | Unclassified |

#### Registered Advisers — AUM Distribution

| AUM Bracket | Count | Notable Firms |
|---|---|---|
| > $100B | 239 | Vanguard ($10.2T), Fidelity ($4.73T), Capital Research ($3.75T) |
| $10B - $100B | 1,039 | |
| $1B - $10B | 4,006 | |
| $100M - $1B | 10,179 | |
| < $100M | 1,249 | |
| No AUM reported | 776 | |

#### Top 10 Registered Advisers by AUM

| Firm | State | AUM | Accounts |
|---|---|---|---|
| Vanguard Group | PA | $10.25T | 212 |
| Fidelity Management & Research | MA | $4.73T | 36,290 |
| Capital Research and Management | CA | $3.75T | 22,833 |
| BlackRock Fund Advisors | CA | $3.54T | 541 |
| PIMCO | CA | $2.99T | 2,793 |
| J.P. Morgan Investment Management | NY | $2.99T | 114,499 |
| Goldman Sachs Asset Management | NY | $2.06T | 220,874 |
| T. Rowe Price Associates | MD | $1.93T | 5,924 |
| Merrill Lynch, Pierce, Fenner & Smith | NY | $1.78T | 3,253,265 |
| Morgan Stanley | NY | $1.65T | 2,539,760 |

#### Fund Manager Enrichment Coverage (IAPD XML — 2026-03-27)

5,657 fund managers (advisers with private_fund_count > 0):

| Field | Populated | Coverage | Source |
|---|---|---|---|
| `aum_total` | 5,629 | 99.5% | Item 5F — Q5F2C |
| `aum_discretionary` | 5,629 | 99.5% | Item 5F — Q5F2A |
| `total_accounts` | 5,629 | 99.5% | Item 5F — Q5F2F |
| `fee_types` | 5,649 | 99.9% | Item 5E — Y/N flags → JSON array |
| `client_types` | 5,635 | 99.6% | Item 5D — count + AUM per type → JSONB |
| `website` | 5,232 | 92.5% | Item 1 — WebAddrs |
| `compliance_disclosures` | 5,652 | 99.9% | Item 11 — count of "Y" answers |
| `last_adv_filed_at` | 5,652 | 99.9% | Filing/@Dt |

#### Geographic Distribution (Top US States)

| State | Managers | State | Managers |
|---|---|---|---|
| CA | 132,137 | MA | 37,870 |
| NY | 128,587 | PA | 27,527 |
| TX | 74,053 | CO | 24,316 |
| IL | 57,761 | NJ | 23,923 |
| FL | 42,751 | CT | 19,721 |
| WA | 39,230 | | |

#### Available Fields per Manager

`crd_number`, `cik`, `firm_name`, `sec_number`, `registration_status`, `aum_total`, `aum_discretionary`, `aum_non_discretionary`, `total_accounts`, `fee_types`, `client_types`, `state`, `country`, `website`, `compliance_disclosures`, `last_adv_filed_at`

#### Private Funds — sec_manager_funds (2026-03-28)

| Attribute | Value |
|---|---|
| **Source** | Form ADV Part 1 PDFs (IAPD), Section 7.B.(1) |
| **Script** | `seed_private_funds.py` (Playwright download → PyMuPDF parse → asyncpg upsert) |
| **Rows** | 62,728 funds across 5,634 managers |
| **PDFs** | 5,659 locally stored at `.data/adv_part1/pdfs/` |

**fund_type detection:** SEC Form ADV PDFs render Q10 checkboxes as small JPEG images (17×21 px). Checked vs unchecked use different image xrefs. Script `backfill_fund_type.py` (20-worker ProcessPoolExecutor) detects the minority xref = selected fund type. 97.8% detection rate.

| fund_type | Count | % |
|---|---|---|
| Private Equity Fund | 28,683 | 46% |
| Hedge Fund | 13,804 | 22% |
| Other Private Fund | 6,675 | 11% |
| Real Estate Fund | 5,636 | 9% |
| Venture Capital Fund | 4,509 | 7% |
| Securitized Asset Fund | 3,339 | 5% |
| Liquidity Fund | 81 | 0.1% |

**strategy_label:** 3-layer keyword classifier (`backfill_strategy_label.py`):
1. Fund name regex (cascading, most specific first) — ~87%
2. Hedge fund sub-strategy refinement (equity, CTA, volatility, macro) — +2%
3. Brochure content enrichment (methods_of_analysis, investment_philosophy) — +127 funds

Top strategy_labels: Private Equity (19,935), Hedge Fund (8,281), Real Estate (5,601), Venture Capital (3,978), Secondaries/Co-Invest (3,703), Structured Credit (2,789), Private Credit (2,761), Co-Investment (1,328), Energy (1,084), Credit Hedge (1,007), Infrastructure (936), Growth Equity (848), Long/Short Equity (701), Multi-Strategy (348), Quantitative (92), Global Macro (90). Total: **37 distinct strategies**.

**AUM floor for embedding:** `_embed_sec_private_funds()` in wealth_embedding_worker filters to managers with combined GAV ≥ $1B → 2,087 managers (37%), 45,942 funds (73%).

**Available fields:** `crd_number`, `fund_name`, `fund_id`, `gross_asset_value`, `fund_type`, `strategy_label`, `is_fund_of_funds`, `investor_count`

#### Brochure & Team Extraction (ADV Part 2A/2B)

| Table | Description | Source |
|---|---|---|
| `sec_manager_brochure_text` | 18 classified sections per brochure (Items 4-18 + philosophy/risk/ESG + full_brochure fallback) | ADV Part 2A PDF (PyMuPDF extraction) |
| `sec_manager_team` | Key personnel: name, title, certifications (CFA/CFP/CAIA/CPA/FRM/CIPM), years_experience, bio_summary | ADV Part 2B supplement (regex extraction) |

---

### 1.2 SEC EDGAR — 13F Institutional Holdings

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR 13F-HR filings (via edgartools) |
| **Worker** | `sec_13f_ingestion` (lock ID 900_021) |
| **Frequency** | Weekly |
| **Table** | `sec_13f_holdings` (hypertable, 3-month chunks) |
| **Rows** | 1,092,225 |
| **Date range** | 2000-06-30 to 2025-12-31 |
| **CIKs** | 12 institutional investors |

#### Institutional Investors Tracked

| CIK | Firm | Holdings | Quarters | History | Latest AUM |
|---|---|---|---|---|---|
| 0002012383 | BlackRock, Inc. | 32,172 | 6 | 2024-09 to 2025-12 | $5.92T |
| 0001374170 | Norges Bank (Norway Sovereign Fund) | 105,021 | 52 | 2013-03 to 2025-12 | $934.8B |
| 0000073124 | Northern Trust Corp | 406,711 | 92 | 2002-12 to 2025-12 | $784.4B |
| 0000914208 | Invesco Ltd. | 316,080 | 84 | 2004-12 to 2025-12 | $652.2B |
| 0000038777 | Franklin Resources | 149,700 | 85 | 2004-12 to 2025-12 | $407.6B |
| 0001179392 | Two Sigma Investments | 50,250 | 8 | 2024-03 to 2025-12 | $141.8B |
| 0001393818 | Blackstone Inc. | 7,961 | 73 | 2007-12 to 2025-12 | $25.3B |
| 0001527166 | Carlyle Group | 952 | 55 | 2012-06 to 2025-12 | $13.6B |
| 0001284812 | Cohen & Steers | 30,839 | 82 | 2005-09 to 2025-12 | $55.3M |
| 0000355437 | DFA Investment Dimensions | 17,542 | 4 | 2000-06 to 2001-03 | (historical) |
| 0000747546 | Parnassus Funds | 122 | 1 | 2007-06 | (historical) |

#### Sector Allocation (Latest Quarter — Q4 2025)

| Sector | Positions | Market Value |
|---|---|---|
| Information Technology | 3,373 | $3.45T |
| Financials | 3,856 | $1.09T |
| Industrials | 2,790 | $937.9B |
| Health Care | 3,450 | $849.9B |
| Consumer Discretionary | 1,816 | $808.1B |
| Energy | 1,239 | $316.4B |
| Real Estate | 1,134 | $237.5B |
| Materials | 851 | $226.4B |
| Utilities | 543 | $218.4B |
| Consumer Staples | 531 | $148.6B |
| Communication Services | 528 | $140.6B |

#### Derived Tables

| Table | Rows | Description |
|---|---|---|
| `sec_13f_diffs` | 1,071,320 | Quarter-over-quarter position changes (NEW, INCREASED, DECREASED, EXITED) |
| `sec_13f_holdings_agg` | 1,964 | Continuous aggregate: sector value + position count per CIK/quarter |
| `sec_13f_drift_agg` | 529 | Continuous aggregate: churn count + total changes per CIK/quarter |
| `sec_13f_latest_quarter` | 543 | Continuous aggregate: latest equity AUM + position count per CIK/quarter |

#### Available Fields per Holding

`cik`, `report_date`, `filing_date`, `accession_number`, `cusip`, `issuer_name`, `asset_class`, `shares`, `market_value`, `discretion`, `voting_sole`, `voting_shared`, `voting_none`, `sector`

---

### 1.3 SEC EDGAR — N-PORT Fund Holdings

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR N-PORT XML filings |
| **Worker** | `nport_ingestion` (lock ID 900_018) |
| **Frequency** | Weekly |
| **Table** | `sec_nport_holdings` (hypertable, 3-month chunks) |
| **Rows** | 132,823 |
| **Date range** | 2019-11-21 to 2026-03-23 |
| **CIKs** | 69 US registered investment companies |

#### Top Fund Complexes Filing N-PORT

| CIK | Fund Complex | Holdings | Reports |
|---|---|---|---|
| 0000758003 | T. Rowe Price Tax-Free High Yield | 12,144 | 12 |
| 0000806564 | Morgan Stanley Mortgage Securities | 6,452 | 12 |
| 0000773478 | Franklin California Tax Free Trust | 6,226 | 12 |
| 0000357057 | Fidelity Massachusetts Municipal Trust | 5,563 | 12 |
| 0000703112 | Franklin New York Tax Free Income | 5,323 | 12 |

#### Sector Distribution

| Sector Code | Holdings | Description |
|---|---|---|
| MUN | 91,019 | Municipal bonds |
| CORP | 26,446 | Corporate bonds |
| USGSE | 7,671 | US Government-Sponsored Enterprises |
| USGA | 4,880 | US Government Agency |
| UST | 1,251 | US Treasury |
| RF | 749 | Revenue/Funding |
| NUSS | 310 | Non-US Sovereign |
| PF | 81 | Preferred |

#### Available Fields per Holding

`report_date`, `cik`, `cusip`, `isin`, `issuer_name`, `asset_class`, `sector`, `market_value`, `quantity`, `currency`, `pct_of_nav`, `is_restricted`, `fair_value_level`

---

### 1.3b SEC EDGAR — Form 345 Insider Transactions

| Attribute | Value |
|---|---|
| **Source** | SEC EDGAR Form 3/4/5 bulk quarterly TSV files |
| **Worker** | `form345_ingestion` (lock ID 900_051) |
| **Seed script** | `scripts/seed_insider_transactions.py --form345-dir <path>` |
| **Frequency** | Quarterly |
| **Table** | `sec_insider_transactions` (regular table, not hypertable) |
| **Rows** | 59,677 (Q4 2025) |
| **Materialized view** | `sec_insider_sentiment` (2,956 issuer-quarter rows) |

**Data sources (3 TSV files per quarter):**
- `SUBMISSION.tsv` (36,421 rows) — issuer CIK, ticker, document type, period of report
- `REPORTINGOWNER.tsv` (36,421 rows) — owner CIK, name, relationship (compound: `Officer`, `Director,Officer`, `TenPercentOwner`, etc.), title
- `NONDERIV_TRANS.tsv` (59,677 rows) — transaction code, shares, price per share, date, acquired/disposed

#### Transaction Code Distribution (Q4 2025)

| Code | Count | Description | Used in Score |
|---|---|---|---|
| S | 22,489 | Open market sale | Yes (bearish) |
| A | 8,994 | Award/grant | No |
| F | 8,096 | Tax withholding | No |
| M | 8,141 | Option exercise | No |
| P | 5,447 | Open market purchase | Yes (bullish) |
| G | 2,342 | Gift | No |
| J | 1,542 | Other | No |
| D | 1,374 | Disposition to issuer | No |
| C | 756 | Conversion | No |
| L | 293 | Small acquisition | No |
| X | 94 | Expiration | No |
| U | 67 | Tender | No |
| I | 22 | Discretionary transaction | No |
| W | 18 | Acquisition/disposition by will | No |
| E | 2 | Expiration of short derivative | No |

#### Insider Sentiment Score

The `sec_insider_sentiment` materialized view aggregates buy/sell activity per issuer per quarter, **excluding sole 10% Owners** (`TenPercentOwner`, `TenPercentOwner,Other` — they trade for portfolio reasons, not conviction). Mixed relationships like `Director,TenPercentOwner` are **included** (they have fiduciary insight).

**Score formula:** `insider_sentiment_score = buy_value / (buy_value + sell_value) * 100`
- Score > 50 → net buying pressure (bullish)
- Score = 50 → neutral (no data or balanced)
- Score < 50 → net selling pressure (bearish)

**Top insider buying signals (Q4 2025):**

| Ticker | Buy Count | Sell Count | Buy Value ($M) | Sell Value ($M) | Score |
|---|---|---|---|---|---|
| BGC | 6 | 4 | 247.9 | 82.6 | 75.0 |
| BETA | 7 | 0 | 99.0 | — | 100.0 |
| KMI | 3 | 3 | 26.1 | 0.5 | 98.1 |
| AMR | 62 | 5 | 24.7 | 1.5 | 94.2 |
| BLND | 13 | 5 | 21.8 | 0.3 | 98.8 |

**Literature:** Insider purchases have greater predictive power in 6-12 month windows (Seyhun 1986, Jeng et al. 2003). Purchases are more informative than sales (sales may reflect diversification/personal liquidity).

#### Integration Points

1. **Scoring service** — `compute_fund_score()` accepts optional `insider_sentiment_score` parameter (activated when config includes `"insider_sentiment"` weight)
2. **DD Report — fund enrichment** — `gather_fund_enrichment()` queries insider sentiment for fund's issuer CIK
3. **DD Report — N-PORT portfolio** — `gather_sec_nport_data()` computes weighted portfolio-level insider sentiment from top 20 holdings
4. **Query service** — `insider_queries.py` provides `get_insider_sentiment_score()` and `get_insider_summary()` (sync, for DD report context)

#### Available Fields per Transaction

`accession_number` (PK), `trans_sk` (PK), `issuer_cik`, `issuer_ticker`, `owner_cik`, `owner_name`, `owner_relationship`, `owner_title`, `trans_date`, `period_of_report`, `document_type`, `trans_code`, `trans_acquired_disp`, `trans_shares`, `trans_price_per_share`, `trans_value` (generated), `shares_owned_after`

---

### 1.4 ESMA — European UCITS Funds & Managers

| Attribute | Value |
|---|---|
| **Source** | ESMA UCITS Register (fund + manager registry) |
| **Worker** | `esma_ingestion` |
| **Frequency** | Daily (ticker resolution ongoing) |
| **Tables** | `esma_funds` (10,436 rows), `esma_managers` (658 rows) |

#### Fund Domicile Distribution

| Domicile | Funds | % | Note |
|---|---|---|---|
| LU (Luxembourg) | 8,535 | 81.8% | Primary UCITS passporting hub |
| FR (France) | 650 | 6.2% | |
| AT (Austria) | 381 | 3.7% | |
| DE (Germany) | 352 | 3.4% | |
| LI (Liechtenstein) | 201 | 1.9% | |
| BE (Belgium) | 88 | 0.8% | |
| FI (Finland) | 85 | 0.8% | |
| NO (Norway) | 77 | 0.7% | |
| MT (Malta) | 33 | 0.3% | |
| Others (8) | 34 | 0.3% | BG, CZ, ES, GR, IE, IT, LV, SE |

All 10,436 funds are classified as **UCITS** (Undertakings for Collective Investment in Transferable Securities). `strategy_label` assigned via fund name keyword classifier (multilíngue EN/DE/FR/PT) — **31 categories, 69.7% coverage** (7,278 / 10,436). Top categories: Multi-Asset (811), Fixed Income (526), ESG/Sustainable (523), Equity (506), Target Date (491), Global Equity (435), Index/Passive (353), Global Fixed Income (334). `strategy_label` assigned via fund name keyword classifier — **31 categories, 69.7% coverage** (7,278 / 10,436). Top categories: Multi-Asset (811), Fixed Income (526), ESG/Sustainable (523), Equity (506), Target Date (491), Global Equity (435), Index/Passive (353), Global Fixed Income (334).

#### Manager Country Distribution

| Country | Managers | Country | Managers |
|---|---|---|---|
| LU | 275 | LI | 11 |
| IE | 124 | MT | 11 |
| FR | 87 | FI | 10 |
| SE | 41 | NO | 8 |
| DE | 31 | Others (15) | 35 |
| BE | 17 | | |
| AT | 15 | **Total** | **658** |

#### Top 15 UCITS Managers by Fund Count

| Manager | Country | Funds |
|---|---|---|
| Amundi Luxembourg S.A. | LU | 427 |
| UBS Fund Management (Luxembourg) | LU | 309 |
| DWS Investment S.A. | LU | 295 |
| Eurizon Capital SGR (Luxembourg Branch) | LU | 228 |
| Allianz Global Investors GmbH | LU | 212 |
| BNP Paribas Asset Management Luxembourg | LU | 210 |
| Waystone Management Company (Lux) | LU | 173 |
| Schroder Investment Management (Europe) | LU | 153 |
| BG Fund Management Luxembourg | LU | 149 |
| FundPartner Solutions (Europe) | LU | 147 |
| FundRock Management Company | LU | 145 |
| FIL Investment Management (Luxembourg) | LU | 144 |
| JPMorgan Asset Management (Europe) | LU | 142 |
| BlackRock (Luxembourg) S.A. | LU | 140 |
| Lombard Odier Funds (Europe) | LU | 126 |

#### Data Quality

| Metric | Value |
|---|---|
| Manager linkage rate | 100% (all funds linked to a manager) |
| ISIN coverage | 100% (10,436 / 10,436) |
| Yahoo ticker resolved | 28.1% (2,929 / 10,436) — resolution ongoing |
| ISIN-ticker mappings | 6,227 in `esma_isin_ticker_map` |

#### Available Fields

**Funds:** `isin` (PK), `fund_name`, `esma_manager_id`, `domicile`, `fund_type`, `strategy_label`, `host_member_states[]`, `yahoo_ticker`, `ticker_resolved_at`

**Managers:** `esma_id` (PK), `lei`, `company_name`, `country`, `authorization_status`, `fund_count`, `sec_crd_number`

---

### 1.5 FRED — Federal Reserve Economic Data

| Attribute | Value |
|---|---|
| **Source** | FRED API (Federal Reserve Bank of St. Louis) |
| **Worker** | `macro_ingestion` (lock ID 43) |
| **Frequency** | Daily |
| **Table** | `macro_data` (hypertable, 1-month chunks) |
| **Rows** | 48,848 |
| **Series** | 78 |
| **Date range** | 2016-01-01 to 2026-03-24 |

#### Series Inventory by Category

**Interest Rates & Monetary Policy (7 series)**
| Series | Description | Frequency | Observations |
|---|---|---|---|
| DFF | Federal Funds Effective Rate | Daily | 2,521 |
| DGS2 | 2-Year Treasury Constant Maturity | Daily | 2,414 |
| DGS10 | 10-Year Treasury Constant Maturity | Daily | 2,414 |
| BAA10Y | Moody's Baa-10Y Treasury Spread | Daily | 2,410 |
| SOFR | Secured Overnight Financing Rate | Daily | 1,990 |
| ECBDFR | ECB Deposit Facility Rate | Daily | 2,524 |
| INTDSRBRM193N | Brazil Interest Rate | Monthly | 119 |

**Credit Spreads (4 series)**
| Series | Description | Observations |
|---|---|---|
| BAMLH0A0HYM2 | ICE BofA US High Yield OAS | 2,492 |
| BAMLHE00EHYIEY | ICE BofA Euro High Yield OAS | 2,492 |
| BAMLEMCBPIOAS | ICE BofA EM Corporate OAS | 2,492 |
| BAMLEMRACRPIASIAOAS | ICE BofA Asia EM Corporate OAS | 2,492 |

**Commodities & Energy (4 series)**
| Series | Description | Observations |
|---|---|---|
| DCOILWTICO | WTI Crude Oil | 2,415 |
| DCOILBRENTEU | Brent Crude Oil | 2,452 |
| DHHNGSP | Henry Hub Natural Gas | 2,426 |
| PCOPPUSDM | Global Copper Price | 119 |

**Volatility & Financial Conditions (3 series)**
| Series | Description | Observations |
|---|---|---|
| VIXCLS | CBOE VIX Index | 2,458 |
| STLFSI4 | St. Louis Fed Financial Stress Index | 520 |
| NFCI | Chicago Fed National Financial Conditions | 520 |

**Housing — Case-Shiller Metro Indexes (20 series)**
| Series | Metro Area | Series | Metro Area |
|---|---|---|---|
| ATXRSA | Atlanta | MNXRSA | Minneapolis |
| BOXRSA | Boston | NYXRSA | New York |
| CHXRSA | Charlotte | PHXRSA | Phoenix |
| CRXRSA | Cleveland | POXRSA | Portland |
| CSUSHPINSA | US Composite | SDXRSA | San Diego |
| DAXRSA | Dallas | SEXRSA | Seattle |
| DEXRSA | Detroit | SFXRSA | San Francisco |
| DNXRSA | Denver | TPXRSA | Tampa |
| LXXRSA | Los Angeles | WDXRSA | Washington DC |
| MSPUS | US National | WRMFSL | Money Market Funds |

**Labor Market (5 series)**
| Series | Description | Observations |
|---|---|---|
| PAYEMS | Total Nonfarm Payrolls | 120 |
| UNRATE | Unemployment Rate | 119 |
| JTSJOL | Job Openings (JOLTS) | 119 |
| SAHMREALTIME | Sahm Rule Recession Indicator | 119 |
| USREC | US Recession Indicator | 120 |

**Housing Activity (4 series)**
| Series | Description | Observations |
|---|---|---|
| HOUST | Housing Starts | 119 |
| PERMIT | Building Permits | 119 |
| EXHOSLUSM495S | Existing Home Sales | 13 |
| MSACSR | Monthly Housing Supply | 119 |

**Inflation (3 series)**
| Series | Description | Observations |
|---|---|---|
| CPIAUCSL | Consumer Price Index | 119 |
| PCEPILFE | Core PCE (Fed's preferred measure) | 119 |
| USEPUINDXD | Economic Policy Uncertainty Index | 2,524 |

**Consumer Sentiment (1 series)**
| Series | Description | Observations |
|---|---|---|
| UMCSENT | University of Michigan Consumer Sentiment | 119 |

**Lending & Credit (4 series)**
| Series | Description | Observations |
|---|---|---|
| MORTGAGE30US | 30-Year Fixed Mortgage Rate | 520 |
| MORTGAGE15US | 15-Year Fixed Mortgage Rate | 520 |
| CCLACBW027SBOG | Credit Card Loans | 520 |
| TOTLL | Total Loans & Leases | 520 |
| DPSACBW027SBOG | Deposits at Commercial Banks | 520 |

**Industrial & GDP (2 series)**
| Series | Description | Observations |
|---|---|---|
| INDPRO | Industrial Production Index | 120 |
| A191RL1Q225SBEA | US Real GDP Growth | 40 |

**Emerging Markets (7 series)**
Brazil: `BRACPIALLMINMEI` (CPI), `BRALOLITOAASTSAM` (Leading Indicator)
China: `CHNCPIALLMINMEI` (CPI), `CHNLOLITOAASTSAM` (Leading Indicator)
India: `INDCPIALLMINMEI` (CPI), `INDLOLITOAASTSAM` (Leading Indicator)
Japan: `JPNCPIALLMINMEI` (CPI), `JPNLOLITOAASTSAM` (Leading Indicator), `JPNRGDPEXP` (GDP)
Mexico: `MEXLOLITONOSTSAM` (Leading Indicator)

**BIS-Sourced Series (4 series)**
| Series | Description | Observations |
|---|---|---|
| DRALACBN | LatAm Credit/GDP | 40 |
| DRCCLACBS | LatAm Credit Growth | 40 |
| DRSFRMACBS | France Credit/GDP | 40 |
| CLVMNACSCAB1GQEA19 | Euro Area GDP | 40 |

**Bond Market Indicators (3 series)**
| Series | Description | Observations |
|---|---|---|
| OBMMIFHA30YF | 30Y Fixed Mortgage Index | 496 |
| IRLTLT01DEM156N | Germany Long-Term Rate | 119 |
| IRLTLT01JPM156N | Japan Long-Term Rate | 120 |

---

### 1.6 US Treasury API

| Attribute | Value |
|---|---|
| **Source** | US Treasury Fiscal Data API |
| **Worker** | `treasury_ingestion` (lock ID 900_011) |
| **Frequency** | Daily |
| **Table** | `treasury_data` (hypertable, 1-month chunks) |
| **Rows** | 18,158 |
| **Series** | 278 |
| **Date range** | 2016-03-28 to 2026-03-20 |

#### Series Categories

| Category | Sample Series | Observations |
|---|---|---|
| **National Debt** | `DEBT_TOTAL_PUBLIC`, `DEBT_HELD_PUBLIC`, `DEBT_INTRAGOV` | 2,505 each |
| **Auction Results** | `AUCTION_NOTE_3-YEAR`, `AUCTION_NOTE_5-YEAR`, `AUCTION_NOTE_7-YEAR` | 120-137 |
| **Interest Rates** | `RATE_TREASURY_BILLS`, `RATE_TREASURY_BONDS`, `RATE_TIPS` | 120 each |
| **Interest Expense** | `INTEREST_EXPENSE_ON_GOVT_ACCOUNT_SERIES` (monthly + FYTD) | 120 each |
| **Foreign Series** | `RATE_FOREIGN_SERIES`, `RATE_DOMESTIC_SERIES` | 120 each |

---

### 1.7 BIS — Bank for International Settlements

| Attribute | Value |
|---|---|
| **Source** | BIS SDMX API |
| **Worker** | `bis_ingestion` (lock ID 900_014) |
| **Frequency** | Quarterly |
| **Table** | `bis_statistics` (hypertable, 1-year chunks) |
| **Rows** | 11,489 |
| **Countries** | 43 |
| **Indicators** | 3 |
| **Datasets** | 3 |

#### Datasets & Indicators

| Dataset | Indicator | Observations | Description |
|---|---|---|---|
| `WS_CREDIT_GAP` | `credit_to_gdp_gap` | 4,223 | Credit-to-GDP gap (early warning indicator for banking crises) |
| `WS_DSR` | `debt_service_ratio` | 3,288 | Private non-financial sector debt service ratio |
| `WS_SPP` | `property_prices` | 3,978 | Residential property price indices |

---

### 1.8 IMF — World Economic Outlook

| Attribute | Value |
|---|---|
| **Source** | IMF DataMapper API |
| **Worker** | `imf_ingestion` (lock ID 900_015) |
| **Frequency** | Quarterly |
| **Table** | `imf_weo_forecasts` (hypertable, 1-year chunks) |
| **Rows** | 8,033 |
| **Countries** | 44 |
| **Indicators** | 4 |
| **Year range** | 1980 to 2030 (includes forecasts) |

#### Indicators

| Indicator | Observations | Description |
|---|---|---|
| `NGDP_RPCH` | 2,214 | Real GDP growth (%) |
| `PCPIPCH` | 2,195 | Inflation, end of period (%) |
| `GGXCNL_NGDP` | 1,871 | General government net lending/borrowing (% of GDP) |
| `GGXWDG_NGDP` | 1,753 | General government gross debt (% of GDP) |

---

### 1.9 OFR — Office of Financial Research (Hedge Fund Monitor)

| Attribute | Value |
|---|---|
| **Source** | OFR Hedge Fund Monitor API |
| **Worker** | `ofr_ingestion` (lock ID 900_012) |
| **Frequency** | Weekly |
| **Table** | `ofr_hedge_fund_data` (hypertable, 3-month chunks) |
| **Rows** | 475 |
| **Series** | 23 |
| **Date range** | 2021-03-31 to 2026-02-28 |

#### Series Inventory

| Category | Series | Description |
|---|---|---|
| **Industry Size** | `OFR_INDUSTRY_COUNT`, `OFR_INDUSTRY_NAV`, `OFR_INDUSTRY_GAV` | Fund count, NAV, gross asset value |
| **Leverage** | `OFR_LEVERAGE_P5`, `OFR_LEVERAGE_P50`, `OFR_LEVERAGE_P95`, `OFR_LEVERAGE_WEIGHTED_MEAN` | Leverage distribution (5th/50th/95th percentile) |
| **Strategy AUM** | `OFR_STRATEGY_{CREDIT,EQUITY,EVENT,FOF,FUTURES,MACRO,MULTI,OTHER,RV}_AUM` | AUM by hedge fund strategy (9 strategies) |
| **Stress Tests** | `OFR_CDS_UP_250BPS_P5/P50`, `OFR_CDS_DOWN_250BPS_P5/P50` | CDS spread shock scenario results |
| **Repo Market** | `OFR_REPO_VOLUME` | FICC sponsored repo volume |
| **Dealer Financing** | `OFR_SCOOS_NET_LENDERCOMPET`, `OFR_SCOOS_NET_LENDERWILLINGNESS` | Senior Credit Officer Survey |

---

### 1.10 Yahoo Finance — Benchmark & Instrument NAV

| Attribute | Value |
|---|---|
| **Source** | Yahoo Finance API |
| **Workers** | `benchmark_ingest` (lock 900_004), `instrument_ingestion` (lock 900_010) |
| **Frequency** | Daily |

#### Benchmark NAV (Global)

| Table | Rows | Date Range | Blocks |
|---|---|---|---|
| `benchmark_nav` | 8,000 | 2024-03-25 to 2026-03-23 | 16 |

All 16 allocation blocks have 500 daily NAV observations with computed log returns.

#### Allocation Block Framework

| Block | Display Name | Geography | Asset Class | Benchmark ETF |
|---|---|---|---|---|
| `na_equity_large` | North America Large Cap Equity | North America | Equity | SPY |
| `na_equity_growth` | North America Growth Equity | North America | Equity | QQQ |
| `na_equity_value` | North America Value Equity | North America | Equity | IWD |
| `na_equity_small` | North America Small Cap Equity | North America | Equity | IWM |
| `dm_europe_equity` | Developed Europe Equity | Developed Europe | Equity | VGK |
| `dm_asia_equity` | Developed Asia Pacific Equity | Developed Asia | Equity | EWJ |
| `em_equity` | Emerging Markets Equity | Emerging Markets | Equity | EEM |
| `fi_us_aggregate` | US Aggregate Bond | North America | Fixed Income | AGG |
| `fi_us_treasury` | US Treasury | North America | Fixed Income | IEF |
| `fi_us_tips` | US TIPS | North America | Fixed Income | TIP |
| `fi_us_high_yield` | US High Yield | North America | Fixed Income | HYG |
| `fi_em_debt` | Emerging Market Debt | Emerging Markets | Fixed Income | EMB |
| `alt_real_estate` | Real Estate (REITs) | North America | Alternatives | VNQ |
| `alt_commodities` | Commodities | Global | Alternatives | DJP |
| `alt_gold` | Gold | Global | Alternatives | GLD |
| `cash` | Cash & Equivalents | North America | Cash | SHV |

---

### 1.11 SEC — Registered Fund Catalog (2026-03-28)

**Migration history:** 0064 (ETF/BDC/MMF tables) → 0065 (N-CEN enrichment) → 0066 (XBRL fees)

ETF, BDC, and Money Market funds were extracted from `sec_registered_funds` into dedicated tables
with schemas derived from their respective EDGAR datasets. `sec_registered_funds` now contains
only mutual funds and closed-end funds.

#### Fund Tables Overview

| Table | Rows | Source | PK | fund_type constraint |
|---|---|---|---|---|
| `sec_registered_funds` | 4,617 | EDGAR XML + N-CEN + OEF XBRL | `cik` | `mutual_fund`, `closed_end`, `interval_fund` |
| `sec_etfs` | 985 | N-CEN Q4 2025 (ETF.tsv + FUND_REPORTED_INFO) | `series_id` | — |
| `sec_bdcs` | 196 | BDC XML whitelist + N-CEN | `series_id` | — |
| `sec_money_market_funds` | 373 | N-MFP (SUBMISSION + SERIESLEVELINFO) | `series_id` | — |
| `sec_mmf_metrics` | 20,270 | N-MFP daily (hypertable, 1-month chunks) | `(metric_date, series_id, class_id)` | — |
| `sec_fund_classes` | 36,516 | EDGAR series/class XML + N-PORT + OEF XBRL | `(cik, series_id, class_id)` | — |

---

#### `sec_registered_funds` — Mutual Funds + Closed-End (4,617 rows)

**fund_type distribution:**

| fund_type | Count | N-CEN enriched | % enriched |
|---|---|---|---|
| mutual_fund | 3,652 | 2,232 | 61.1% ($11.97T AUM) |
| closed_end | 965 | ~0% | N/A (CEFs report fees differently) |
| **Total** | **4,617** | | |

**N-CEN enrichment (migration 0065):** 27 new columns added, populated from 16 quarters of N-CEN filings (2021 Q3 – 2025 Q4):
- Flags: `is_index`, `is_non_diversified`, `is_target_date`, `is_fund_of_fund`, `is_master_feeder`
- Costs: `management_fee`, `net_operating_expenses`, `has_expense_limit`, `has_expense_waived`
- Performance: `return_before_fees`, `return_after_fees`, `return_stdv_before_fees`, `return_stdv_after_fees`
- AUM/NAV: `monthly_avg_net_assets`, `daily_avg_net_assets`, `nav_per_share`, `market_price_per_share`
- Operational: `is_sec_lending_authorized`, `has_line_of_credit`, `has_swing_pricing`
- Metadata: `ncen_accession_number`, `ncen_report_date`, `lei`

**Key discovery:** `MANAGEMENT_FEE` in N-CEN is exclusive to closed-end/interval funds. Open-end mutual fund expense ratios come from OEF XBRL taxonomy via N-CSR filings (migration 0066).

**strategy_label sources (layered):**
1. Fund name keywords — baseline
2. `sec_fund_classes.series_name` — +13pp
3. RR1 XBRL `ObjectivePrimaryTextBlock` — 98.3% hit rate
4. N-PORT `FUND_REPORTED_INFO.SERIES_NAME` — 12,556 series with AUM

Top strategy_labels: Index/Passive (411), Multi-Asset (381), Municipal Bond (309), Fixed Income (196), Equity (186), Size-Focused Equity (109), Global/International (112).

**Available fields:** `cik` (PK), `crd_number`, `fund_name`, `fund_type`, `strategy_label`, `ticker`, `isin`, `series_id`, `total_assets`, `inception_date`, `currency`, `domicile`, `last_nport_date` + 27 N-CEN columns

---

#### `sec_etfs` — ETF Catalog (985 rows)

Source: N-CEN Q4 2025 `ETF.tsv` JOIN `FUND_REPORTED_INFO.tsv` JOIN `SHARES_OUTSTANDING.tsv`

Key fields beyond base identifiers:
- `tracking_difference_gross` / `tracking_difference_net` — `ANNUAL_DIFF_B4/AFTER_FEE_EXPENSE` (%)
- `creation_unit_size`, `pct_in_kind_creation`, `pct_in_kind_redemption` — ETF mechanics
- `management_fee`, `net_operating_expenses` — expense ratio
- `nav_per_share`, `market_price_per_share` — premium/discount tracking
- `monthly_avg_net_assets`, `return_after_fees`, `is_index`, `is_in_kind_etf`

---

#### `sec_bdcs` — Business Development Companies (196 rows)

Source: BDC XML whitelist (CIK authority list) + N-CEN `FUND_REPORTED_INFO` enrichment

All BDCs carry `strategy_label = 'Private Credit'`. Key fields: `management_fee`, `net_operating_expenses`, `nav_per_share`, `market_price_per_share` (discount to NAV typical), `has_line_of_credit`, `is_externally_managed`.

---

#### `sec_money_market_funds` — MMF Series Catalog (373 rows) + `sec_mmf_metrics` Hypertable (20,270 rows)

**Catalog** (`sec_money_market_funds`): one row per series, sourced from N-MFP `SUBMISSION` JOIN `SERIESLEVELINFO`.

| mmf_category | Series |
|---|---|
| Government | 234 |
| Prime | 98 |
| Other Tax Exempt | 25 |
| Single State | 16 |

Key fields: `weighted_avg_maturity` (WAM, days), `weighted_avg_life` (WAL, days), `seven_day_gross_yield` (%), `net_assets`, `pct_daily_liquid_latest`, `pct_weekly_liquid_latest`, `seeks_stable_nav`, `stable_nav_price` (1.0000).

**Timeseries** (`sec_mmf_metrics`): daily by share class, hypertable with 1-month chunks + 3-month compression.
- `seven_day_net_yield` — daily 7-day net yield per class (N-MFP `SEVENDAYNETYIELD`)
- `daily_gross_subscriptions`, `daily_gross_redemptions` — shareholder flows (N-MFP `DLYSHAREHOLDERFLOWREPORT`)
- `pct_daily_liquid`, `pct_weekly_liquid` — daily liquidity % (N-MFP `LIQUIDASSETSDETAILS`)

---

#### `sec_fund_classes` — Share Classes (36,516 rows)

Source: EDGAR series/class XML + N-PORT + OEF XBRL (N-CSR inline XBRL, migration 0066).

**OEF XBRL enrichment (11 new columns, migration 0066):** populated via `seed_fund_class_fees_playwright.py` — Playwright (Edge non-headless) browser pipeline fetching N-CSR XBRL per CIK. 1,259/1,779 CIKs downloaded, 12,372 class facts parsed, **8,278 classes with expense ratios** covering **$100.9T in AUM** across **615 fund families**.

Columns added:
- `expense_ratio_pct` — annual expense ratio (e.g. Vanguard 500 Index: 0.01% – 0.14%)
- `advisory_fees_paid` — advisory fees paid in period ($)
- `expenses_paid` — total expenses paid per $10k
- `avg_annual_return_pct` — average annual return
- `net_assets` — net assets at period end
- `holdings_count` — number of portfolio holdings
- `portfolio_turnover_pct` — portfolio turnover rate
- `fund_name` — fund name from XBRL
- `perf_inception_date` — performance inception date
- `xbrl_accession` — source N-CSR filing accession number
- `xbrl_period_end` — reporting period end date

**Expense ratio by AUM tier:**

| AUM Tier | Share Classes | Funds | Avg ER | Median ER |
|---|---|---|---|---|
| >$1T | 4 | 1 | 0.06% | 0.04% |
| $100B–$1T | 330 | 22 | 0.61% | 0.51% |
| $10B–$100B | 711 | 104 | 0.66% | 0.60% |
| $1B–$10B | 2,477 | 298 | 0.84% | 0.79% |
| $100M–$1B | 3,367 | 379 | 0.92% | 0.86% |
| $10M–$100M | 1,113 | 190 | 1.02% | 0.91% |
| <$10M | 276 | 53 | 1.21% | 1.03% |

Expense ratio scales inversely with AUM as expected (economy of scale). Coverage spans all major families: Vanguard, Capital Group (Growth Fund of America $6.9T), Fidelity, BlackRock, JPMorgan, Federated Hermes, T. Rowe Price, PIMCO, etc.

**Key discovery:** OEF XBRL taxonomy (oef-2026.xsd) via N-CSR is the authoritative source for open-end mutual fund expense ratios — not N-CEN (which only covers closed-end/interval fund fees). The EFM taxonomy study (`efm-77-260316/`) confirmed OEF as the correct namespace.

**Available fields (base):** `cik`, `series_id`, `series_name`, `class_id`, `class_name`, `ticker` + 11 XBRL columns

---

#### EDGAR Bulk Datasets Used

| File | Records | Purpose |
|---|---|---|
| `investment_company_series_class_2025-xml.xml` | 24,898 classes, 7,333 series | Share class/series names + CIK linkage |
| `2025q4_nport/FUND_REPORTED_INFO.tsv` | 12,556 series | Series AUM (Vanguard Total Stock $2T at top) |
| `closed-end-investment-company-2025.xml` | 965 funds | Closed-end fund universe |
| `business-development-company-2025.xml` | 196 funds | BDC CIK authority list |
| `mmf-2025-11_0.xml` | 312 series, 1,192 classes | MMF identification catalog |
| `20260209-20260306_nmfp/` | 6 TSV files, ~45k rows | N-MFP daily metrics (yield, flows, liquidity) |
| `2025q4_ncen (1)/` | 2,445 funds | N-CEN annual: fees, NAV, returns, ETF mechanics |
| `2025q4_rr1/txt.tsv` | 4,452 strategy narratives | N-1A XBRL investment objective + strategy text |
| SEC EDGAR N-CSR XBRL | ~1,794 CIKs | OEF expense ratios and returns per share class |

---

## 2. Instruments & Reference Data

### 2.1 Global Instruments

| Table | Rows | Types |
|---|---|---|
| `instruments_global` | 231 | 217 equity, 12 bond, 2 fund |

### 2.2 CUSIP/ISIN Ticker Mappings

| Table | Rows | Description |
|---|---|---|
| `sec_cusip_ticker_map` | 12,609 | CUSIP-to-ticker via OpenFIGI (N-PORT CORP bonds + 13F equity) |
| `esma_isin_ticker_map` | 6,227 | ISIN-to-Yahoo ticker for ESMA funds |

**CUSIP Ticker Map breakdown:**
- **Source:** 12,609 unique 9-char CUSIPs from `sec_nport_holdings` (sector = CORP)
- **Resolved:** 11,977 (95.0% coverage via OpenFIGI batch API)
- **Tradeable:** 438 (equity instruments with YFinance-compatible tickers)
- **Issuer CIK:** 5,160 backfilled via `sec_managers` firm_name match
- **Unresolved:** 632 (private placements, delisted bonds)
- **Columns:** cusip (PK), ticker, issuer_name, exchange, security_type, figi, composite_figi, issuer_cik, resolved_via, is_tradeable, last_verified_at
- **Seed script:** `scripts/seed_cusip_ticker_map.py` (asyncpg + httpx, 250 req/min with API key)
- **Use case:** Bond CUSIP → issuer equity ticker → Form 345 insider flow for FI/HY funds

---

## 3. Computed Data (Workers)

### 3.1 Risk Metrics

| Worker | Lock ID | Frequency | Table | Description |
|---|---|---|---|---|
| `risk_calc` | 900_007 | Daily | `fund_risk_metrics` | CVaR, VaR, Sharpe, Sortino, volatility, drawdown, momentum (RSI, Bollinger, OBV), DTW drift |

**Metrics computed per instrument:**
CVaR 95% (1m/3m/6m/12m), VaR 95% (1m/3m/6m/12m), returns (1m/3m/6m/1y/3y ann.), volatility 1y, max drawdown (1y/3y), Sharpe (1y/3y), Sortino 1y, alpha 1y, beta 1y, information ratio 1y, tracking error 1y, manager score, RSI(14), Bollinger band position, NAV momentum score, flow momentum score, blended momentum score, DTW drift score.

### 3.2 Portfolio Evaluation

| Worker | Lock ID | Frequency | Table | Description |
|---|---|---|---|---|
| `portfolio_eval` | 900_008 | Daily | `portfolio_snapshots` | CVaR breach status, regime detection, cascade analysis |

**Metrics computed per profile:**
CVaR current, CVaR limit, CVaR utilized %, trigger status (ok/warning/breach), consecutive breach days, regime (RISK_ON/RISK_OFF/STRESS/CRISIS), core weight, satellite weight.

### 3.3 Strategy Drift

| Worker | Lock ID | Frequency | Table | Description |
|---|---|---|---|---|
| `drift_check` | 42 | Daily | `strategy_drift_alerts` | DTW-based strategy drift detection |

---

### 3.4 Wealth Vector Embedding (pgvector)

| Worker | Frequency | Table | Description |
|---|---|---|---|
| `wealth_embedding_worker` | On-demand | `wealth_vector_chunks` | 12-source incremental embedding pipeline |

**12 embedding sources (2026-03-28):**

| Source | Table | Description |
|---|---|---|
| F | `sec_managers` + `sec_manager_team` | SEC manager profiles — AUM, team, fees, compliance |
| G | `sec_registered_funds` + `sec_fund_classes` | SEC fund profiles — strategy, fees (XBRL), share classes, N-PORT holdings |
| H | `sec_13f_holdings` | 13F summaries — top 20 positions, sector concentration |
| I | `sec_manager_funds` | Private fund portfolios — grouped by CRD, AUM ≥ $1B floor |
| J | `esma_funds` | ESMA fund profiles — enriched with manager, domicile, strategy_label |
| K | `esma_managers` | ESMA manager profiles — fund count, LEI, domicile cross-ref |
| L | `sec_etfs` | ETF profiles — tracking difference, expense ratio, index info |
| M | `sec_bdcs` | BDC profiles — NAV discount, Private Credit strategy |
| N | `sec_money_market_funds` | MMF profiles — WAM, WAL, 7-day yield, liquidity buckets |

Sources B (esma_fund name-only) and C (esma_manager name-only) were retired and replaced by enriched J and K.
`_cleanup_legacy_source_types()` removes old `esma_fund`/`esma_manager` rows on next run.

All sources use incremental embedding via LEFT JOIN anti-pattern (only rows without existing `wealth_vector_chunks` entry). Batch: 10,000 rows, cosine similarity index.

---

## 4. Continuous Aggregates

| Aggregate | Source | Rows | Refresh | Description |
|---|---|---|---|---|
| `nav_monthly_returns_agg` | `nav_timeseries` | 384 | Daily | Monthly compound returns per instrument (no org_id — global) |
| `benchmark_monthly_agg` | `benchmark_nav` | 400 | Daily | Monthly benchmark returns per allocation block |
| `sec_13f_holdings_agg` | `sec_13f_holdings` | 1,964 | Daily | Quarterly sector allocation per CIK |
| `sec_13f_drift_agg` | `sec_13f_diffs` | 529 | Daily | Quarterly position churn per CIK |
| `sec_13f_latest_quarter` | `sec_13f_holdings` | 543 | Daily | Latest equity AUM + position count per CIK |

---

## 5. Demo Tenant (wmf-corp)

| Attribute | Value |
|---|---|
| **org_id** | `e28fc30c-9d6d-4b21-8e91-cad8696b44fa` |
| **Instruments** | 17 in global `instruments_universe` (post-dedup), 17 linked via `instruments_org` |
| **NAV history** | 5,511 daily observations in global `nav_timeseries` (2024-03-27 to 2026-03-26) |
| **Risk metrics** | 15 instruments computed |
| **Portfolios** | 3 live model portfolios (Conservative Income, Balanced Growth, Aggressive Growth) |
| **Regime** | All profiles: RISK_ON, trigger status OK |

---

## 6. Worker Inventory

| Worker | Lock ID | Scope | Frequency | Source | Target Table |
|---|---|---|---|---|---|
| `macro_ingestion` | 43 | global | Daily | FRED API | `macro_data` |
| `treasury_ingestion` | 900_011 | global | Daily | US Treasury API | `treasury_data` |
| `benchmark_ingest` | 900_004 | global | Daily | Yahoo Finance | `benchmark_nav` |
| `instrument_ingestion` | 900_010 | global | Daily | Yahoo Finance | `nav_timeseries` |
| `risk_calc` | 900_007 | org | Daily | Computed | `fund_risk_metrics` |
| `portfolio_eval` | 900_008 | org | Daily | Computed | `portfolio_snapshots` |
| `drift_check` | 42 | org | Daily | Computed | `strategy_drift_alerts` |
| `ofr_ingestion` | 900_012 | global | Weekly | OFR API | `ofr_hedge_fund_data` |
| `nport_ingestion` | 900_018 | global | Weekly | SEC EDGAR | `sec_nport_holdings` |
| `sec_13f_ingestion` | 900_021 | global | Weekly | SEC EDGAR | `sec_13f_holdings`, `sec_13f_diffs` |
| `sec_adv_ingestion` | 900_022 | global | Monthly | SEC FOIA CSV + IAPD XML | `sec_managers`, `sec_manager_funds` |
| `esma_ingestion` | — | global | Daily | ESMA Register | `esma_funds`, `esma_managers` |
| `bis_ingestion` | 900_014 | global | Quarterly | BIS SDMX API | `bis_statistics` |
| `imf_ingestion` | 900_015 | global | Quarterly | IMF DataMapper | `imf_weo_forecasts` |
| `sec_bulk_ingestion` | 900_050 | global | Quarterly | SEC DERA bulk ZIPs | sec_etfs, sec_bdcs, sec_money_market_funds, sec_mmf_metrics, sec_registered_funds + strategy_label backfill |
| `form345_ingestion` | 900_051 | global | Quarterly | SEC EDGAR Form 345 bulk TSV | `sec_insider_transactions`, `sec_insider_sentiment` (MV) |
| `wealth_embedding` | 900_041 | global | Daily | Computed | `wealth_vector_chunks` (12 sources) |
| `universe_sync` | 900_070 | global | Weekly | SEC/ESMA catalog | `instruments_universe` (8,950 instruments) |

---

## 6.1 Global Instruments Refactor (Migration 0068-0069, 2026-03-29)

`instruments_universe` and `nav_timeseries` are now **global tables** (no `organization_id`, no RLS). Org-scoped instrument selection moved to `instruments_org`.

### Rationale

Market data (prices, fund metadata) is the same regardless of which tenant views it. The previous design duplicated instruments per org and ran the NAV ingestion worker once per tenant for the same tickers.

### Schema Changes

| Table | Before | After |
|---|---|---|
| `instruments_universe` | org-scoped (RLS, `organization_id`, `block_id`, `approval_status`) | **global** — no org_id, no block_id, no approval_status, no RLS |
| `nav_timeseries` | org-scoped (RLS, `organization_id`) | **global** — no org_id, no RLS. Compression segmentby = `instrument_id` |
| `instruments_org` | did not exist | **new** — org-scoped (RLS), links orgs to instruments with `block_id` + `approval_status` |
| `nav_monthly_returns_agg` | grouped by `(organization_id, instrument_id, month)` | grouped by `(instrument_id, month)` — recreated without org_id |

### `instruments_org` Schema

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | gen_random_uuid() |
| `organization_id` | UUID NOT NULL | RLS-scoped |
| `instrument_id` | UUID NOT NULL FK | → `instruments_universe.instrument_id` ON DELETE CASCADE |
| `block_id` | VARCHAR(80) FK | → `allocation_blocks.block_id` (org-specific assignment) |
| `approval_status` | VARCHAR(20) | `pending` / `approved` / `rejected` |
| `selected_at` | TIMESTAMPTZ | Default now() |
| | UNIQUE | `(organization_id, instrument_id)` |

### Worker Impact

| Worker | Before | After |
|---|---|---|
| `instrument_ingestion` | scope: `org` (ran 1x per tenant, received `org_id`) | scope: `global` (runs once, deduplicates tickers) |
| `risk_calc` | queried `Instrument` via RLS | JOINs `instruments_org` for org scoping + `block_id` lookup |
| `portfolio_eval` | uses `Fund` (legacy) — unaffected | no change |
| `benchmark_ingest` | already global | no change |

### Query Pattern Change

```sql
-- Before: RLS on instruments_universe filtered by org
SELECT * FROM instruments_universe WHERE is_active = true;

-- After: explicit JOIN instruments_org for org-scoped queries
SELECT iu.*
FROM instruments_universe iu
JOIN instruments_org io ON io.instrument_id = iu.instrument_id
WHERE io.organization_id = :org_id AND iu.is_active = true;

-- NAV queries: no org filter needed (global table)
SELECT * FROM nav_timeseries WHERE instrument_id = :id;
```

---

## 7. Data Quality Summary

| Dimension | Metric | Value |
|---|---|---|
| **Coverage — US Managers** | Registered investment advisers | 15,963 (16,712 with AUM data from IAPD XML) |
| **Coverage — US Managers** | Combined RIA AUM | $50+ trillion (refreshed via IAPD XML 2026-03-24) |
| **Coverage — US Fund Managers** | Fund managers with Form ADV Part 1A data | 5,629 / 5,657 (99.5%) |
| **Coverage — Private Funds** | sec_manager_funds | 62,728 funds, 5,634 managers |
| **Coverage — Private Funds** | fund_type classification | 97.8% (checkbox image detection from ADV PDFs) |
| **Coverage — Private Funds** | strategy_label | 47.3% specific (37 strategies via 3-layer classifier) |
| **Coverage — Registered Funds** | sec_registered_funds (MF + CEF) | 4,617 funds |
| **Coverage — Registered Funds** | N-CEN enrichment (mutual funds) | 2,232 / 3,652 (61.1%, $11.97T AUM) |
| **Coverage — Registered Funds** | OEF XBRL fees (sec_fund_classes) | 8,278 / 36,516 classes with expense ratios ($100.9T AUM) |
| **Coverage — ETFs** | sec_etfs | 985 funds (N-CEN Q4 2025) |
| **Coverage — BDCs** | sec_bdcs | 196 funds (all = Private Credit) |
| **Coverage — MMFs** | sec_money_market_funds | 373 series; 20,270 daily metric rows |
| **Coverage — Share Classes** | sec_fund_classes | 36,516 rows + 11 XBRL columns (8,278 enriched), **17,233 with ticker** (5,002 series) via SEC series/class XML + company_tickers_mf.json |
| **Coverage — Global Catalog** | instruments_universe | **8,950 instruments** (ETFs 925, MF series 4,700, registered 358, BDCs 48, ESMA 2,929). **5,339+ with 10Y NAV** (~10.4M+ nav_timeseries rows) |
| **Coverage — NAV History** | nav_timeseries (global, no RLS) | 10.4M+ rows, 2016-2026, ~1,877 days/instrument avg |
| **Coverage — N-PORT Holdings** | sec_nport_holdings | **2.03M rows**, 1,215 CIKs, 7,759 series, 24 quarters (2020 Q1 — 2025 Q4), top 50 holdings/fund |
| **Coverage — Prospectus Returns** | sec_fund_prospectus_returns | **17,502 annual returns**, 2,086 series, 2012-2025 (RR1 bar chart data) |
| **Coverage — Prospectus Stats** | sec_fund_prospectus_stats | **72,157 rows**, 20,390 series — fees, expense ratios, turnover, risk |
| **Coverage — US Institutional** | 13F filers tracked | 12 institutions |
| **Coverage — US Institutional** | Combined latest-quarter AUM | $8.9+ trillion |
| **Coverage — European Funds** | UCITS funds | 10,436 |
| **Coverage — European Funds** | strategy_label | 69.7% classified (31 categories) |
| **Coverage — European Managers** | ESMA-registered managers | 658 across 25 countries |
| **Coverage — Total Fund Universe** | All fund tables combined | sec_registered_funds(4,617) + sec_etfs(985) + sec_bdcs(196) + sec_money_market_funds(373) + sec_manager_funds(62,728) + esma_funds(10,436) = **79,335 funds** |
| **Coverage — Macro** | Economic time series | 78 FRED + 278 Treasury + 23 OFR |
| **Coverage — Global** | Countries in BIS/IMF data | 43-44 countries |
| **Coverage — CUSIP Mapping** | sec_cusip_ticker_map | 12,609 CUSIPs, 95.0% resolved, 5,160 with issuer_cik |
| **Coverage — Insider Transactions** | sec_insider_transactions (Q4 2025) | 59,677 transactions (5,447 P + 22,489 S); 2,956 issuer-quarters in sentiment MV |
| **Coverage — Embeddings** | pgvector sources | 12 active sources across all fund universes |
| **Freshness — Markets** | NAV data | 10Y backfill in progress (5,339+ instruments, through 2026-03-27) |
| **Freshness — Markets** | Benchmark NAV | Updated to 2026-03-25 |
| **Freshness — Macro** | FRED data | Updated to 2026-03-24 |
| **Freshness — SEC** | 13F holdings | Through Q4 2025 |
| **Freshness — SEC** | N-PORT filings | Through 2026-03-23 |
| **Freshness — Fund Catalog** | N-CEN enrichment | Q4 2025 (16 quarters processed) |
| **Freshness — Fund Catalog** | OEF XBRL fees | Feb 2026 N-CSR filings (1,259 CIKs processed) |
| **Linkage — ESMA** | Fund-to-manager linkage | 100% |
| **Linkage — ESMA** | Ticker resolution | 28.1% (1,942 fixed .LU→.LX, many still fail on Yahoo) |
| **History — 13F** | Longest history | Northern Trust: 92 quarters (2002-2025) |
| **History — Macro** | Longest daily series | FRED: 10 years (2016-2026) |
| **History — IMF** | Forecast horizon | To 2030 |
| **History — MMF** | Daily metrics | N-MFP Feb-Mar 2026 (20,270 rows) |
| **Derived Data** | 13F quarter-over-quarter diffs | 1,071,320 position changes |
| **Derived Data** | Continuous aggregates | 5 materialized views, auto-refreshed daily (nav_monthly_returns_agg rebuilt without org_id) |
| **Automation** | Quarterly SEC bulk ingestion | `sec_bulk_ingestion` worker (lock 900_050) — N-CEN, N-MFP, BDC, strategy_label |
| **Automation** | Weekly universe sync | `universe_sync` worker (lock 900_070) — auto-fetches SEC company_tickers_mf.json, syncs SEC/ESMA → instruments_universe, deactivates funds without NAV |
| **Automation** | Daily NAV ingestion | `instrument_ingestion` worker (lock 900_010, **global**) — Yahoo Finance for all active instruments |
| **Automation** | Daily wealth embedding | `wealth_embedding` worker (lock 900_041) — 12 sources + 4 new brochure sections, incremental |
