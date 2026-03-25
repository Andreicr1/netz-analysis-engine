# Database Inventory Reference

**Last updated:** 2026-03-24
**Database:** Timescale Cloud (PostgreSQL 16 + TimescaleDB + pgvector)
**Total tables:** 124 | **Total data rows:** ~3.4M across key tables

---

## Executive Summary

The Netz Analysis Engine database aggregates financial data from 7 authoritative sources spanning US institutional asset management (SEC), European UCITS funds (ESMA), and global macroeconomic indicators (FRED, Treasury, BIS, IMF, OFR). The database provides:

- **976,980 US investment managers** from SEC FOIA bulk data, including 15,963 registered investment advisers managing $38+ trillion in combined AUM
- **10,436 European UCITS funds** from 658 ESMA-registered managers across 25 countries
- **1.09M institutional holdings** (13F-HR) from 12 major institutional investors, with 25 years of quarterly history
- **132,823 fund portfolio holdings** (N-PORT) from 69 US registered investment companies
- **78 macroeconomic time series** from FRED covering rates, spreads, housing, employment, and commodities
- **278 US Treasury series** covering debt, auction results, interest rates, and foreign exchange
- **Global financial stability data** from BIS (43 countries), IMF (44 countries, forecasts to 2030), and OFR (hedge fund industry metrics)

---

## 1. Data Sources & Workers

### 1.1 SEC EDGAR — Investment Advisers (ADV)

| Attribute | Value |
|---|---|
| **Source** | SEC FOIA Bulk CSV (IA_FIRM_SEC_Feed, IA_FIRM_STATE_Feed) |
| **Worker** | `sec_adv_ingestion` (lock ID 900_022) |
| **Frequency** | Monthly |
| **Table** | `sec_managers` |
| **Rows** | 976,980 |

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
| > $100B | 210 | Vanguard ($7.9T), Fidelity ($3.96T), Capital Research ($3.3T) |
| $10B - $100B | 957 | |
| $1B - $10B | 3,553 | |
| $100M - $1B | 9,452 | |
| < $100M | 1,149 | |
| No AUM reported | 642 | |

#### Top 10 Registered Advisers by AUM

| Firm | State | AUM | Accounts |
|---|---|---|---|
| Vanguard Group | PA | $7.91T | 209 |
| Fidelity Management & Research | MA | $3.96T | 31,349 |
| Capital Research and Management | CA | $3.32T | 22,262 |
| BlackRock Fund Advisors | CA | $3.05T | 522 |
| PIMCO | CA | $2.62T | 2,811 |
| J.P. Morgan Investment Management | NY | $2.55T | 92,898 |
| T. Rowe Price Associates | MD | $1.75T | 4,696 |
| Goldman Sachs Asset Management | NY | $1.66T | 189,311 |
| Morgan Stanley | NY | $1.40T | 2,405,783 |
| BlackRock Financial Management | NY | $1.29T | 2,184 |

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

All 10,436 funds are classified as **UCITS** (Undertakings for Collective Investment in Transferable Securities).

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

**Funds:** `isin` (PK), `fund_name`, `esma_manager_id`, `domicile`, `fund_type`, `host_member_states[]`, `yahoo_ticker`, `ticker_resolved_at`

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

## 2. Instruments & Reference Data

### 2.1 Global Instruments

| Table | Rows | Types |
|---|---|---|
| `instruments_global` | 231 | 217 equity, 12 bond, 2 fund |

### 2.2 CUSIP/ISIN Ticker Mappings

| Table | Rows | Description |
|---|---|---|
| `sec_cusip_ticker_map` | 0 | CUSIP-to-ticker (pending population) |
| `esma_isin_ticker_map` | 6,227 | ISIN-to-Yahoo ticker for ESMA funds |

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

## 4. Continuous Aggregates

| Aggregate | Source | Rows | Refresh | Description |
|---|---|---|---|---|
| `nav_monthly_returns_agg` | `nav_timeseries` | 384 | Daily | Monthly compound returns per instrument (log + arithmetic) |
| `benchmark_monthly_agg` | `benchmark_nav` | 400 | Daily | Monthly benchmark returns per allocation block |
| `sec_13f_holdings_agg` | `sec_13f_holdings` | 1,964 | Daily | Quarterly sector allocation per CIK |
| `sec_13f_drift_agg` | `sec_13f_diffs` | 529 | Daily | Quarterly position churn per CIK |
| `sec_13f_latest_quarter` | `sec_13f_holdings` | 543 | Daily | Latest equity AUM + position count per CIK |

---

## 5. Demo Tenant (wmf-corp)

| Attribute | Value |
|---|---|
| **org_id** | `e28fc30c-9d6d-4b21-8e91-cad8696b44fa` |
| **Instruments** | 16 ETF proxies (one per allocation block) |
| **NAV history** | 8,016 daily observations (2024-03-25 to 2026-03-24) |
| **Risk metrics** | 16 instruments computed |
| **Portfolios** | 3 live model portfolios (Conservative Income, Balanced Growth, Aggressive Growth) |
| **Regime** | All profiles: RISK_ON, trigger status OK |

---

## 6. Worker Inventory

| Worker | Lock ID | Scope | Frequency | Source | Target Table |
|---|---|---|---|---|---|
| `macro_ingestion` | 43 | global | Daily | FRED API | `macro_data` |
| `treasury_ingestion` | 900_011 | global | Daily | US Treasury API | `treasury_data` |
| `benchmark_ingest` | 900_004 | global | Daily | Yahoo Finance | `benchmark_nav` |
| `instrument_ingestion` | 900_010 | org | Daily | Yahoo Finance | `nav_timeseries` |
| `risk_calc` | 900_007 | org | Daily | Computed | `fund_risk_metrics` |
| `portfolio_eval` | 900_008 | org | Daily | Computed | `portfolio_snapshots` |
| `drift_check` | 42 | org | Daily | Computed | `strategy_drift_alerts` |
| `ofr_ingestion` | 900_012 | global | Weekly | OFR API | `ofr_hedge_fund_data` |
| `nport_ingestion` | 900_018 | global | Weekly | SEC EDGAR | `sec_nport_holdings` |
| `sec_13f_ingestion` | 900_021 | global | Weekly | SEC EDGAR | `sec_13f_holdings`, `sec_13f_diffs` |
| `sec_adv_ingestion` | 900_022 | global | Monthly | SEC FOIA CSV | `sec_managers`, `sec_manager_funds` |
| `esma_ingestion` | — | global | Daily | ESMA Register | `esma_funds`, `esma_managers` |
| `bis_ingestion` | 900_014 | global | Quarterly | BIS SDMX API | `bis_statistics` |
| `imf_ingestion` | 900_015 | global | Quarterly | IMF DataMapper | `imf_weo_forecasts` |

---

## 7. Data Quality Summary

| Dimension | Metric | Value |
|---|---|---|
| **Coverage — US Managers** | Registered investment advisers | 15,963 |
| **Coverage — US Managers** | Combined RIA AUM | $38+ trillion |
| **Coverage — US Institutional** | 13F filers tracked | 12 institutions |
| **Coverage — US Institutional** | Combined latest-quarter AUM | $8.9+ trillion |
| **Coverage — European Funds** | UCITS funds | 10,436 |
| **Coverage — European Managers** | ESMA-registered managers | 658 across 25 countries |
| **Coverage — Macro** | Economic time series | 78 FRED + 278 Treasury + 23 OFR |
| **Coverage — Global** | Countries in BIS/IMF data | 43-44 countries |
| **Freshness — Markets** | NAV/benchmark data | Updated to 2026-03-24 (today) |
| **Freshness — Macro** | FRED data | Updated to 2026-03-24 (today) |
| **Freshness — SEC** | 13F holdings | Through Q4 2025 |
| **Freshness — SEC** | N-PORT filings | Through 2026-03-23 |
| **Linkage — ESMA** | Fund-to-manager linkage | 100% |
| **Linkage — ESMA** | Ticker resolution | 28.1% (ongoing) |
| **History — 13F** | Longest history | Northern Trust: 92 quarters (2002-2025) |
| **History — Macro** | Longest daily series | FRED: 10 years (2016-2026) |
| **History — IMF** | Forecast horizon | To 2030 |
| **Derived Data** | 13F quarter-over-quarter diffs | 1,071,320 position changes |
| **Derived Data** | Continuous aggregates | 5 materialized views, auto-refreshed daily |
