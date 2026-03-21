---
date: 2026-03-21
topic: hypertable-opportunities-manager-screener-free-data-sources
---

# Hypertable Opportunities, Manager Screener & Free Data Sources

## Context

After a call with eVestment (Nasdaq), their platform demonstrated sophisticated manager analytics — but fundamentally built on the same public data we're already ingesting: SEC EDGAR (13F, ADV), FRED macro series, and OFR hedge fund data. Their edge is aggregation + UI, not proprietary data. With our hypertable infrastructure (TimescaleDB), Redis caching, and pre-computed worker pattern, we can deliver comparable analytics at zero marginal data cost.

This brainstorm covers three axes:
1. **Hypertable + cache opportunities** across Credit and Wealth verticals
2. **Manager Screener** — a dedicated Wealth OS module (eVestment-comparable)
3. **Additional free data sources** to enrich the platform beyond what eVestment offers

---

## 1. Hypertable + Redis Cache Opportunities

### 1.1 What We Already Have (DB-First Pattern)

| Hypertable | Worker | Lock ID | Chunks | Compression | Status |
|-----------|--------|---------|--------|-------------|--------|
| `macro_data` | macro_ingestion | 43 | 1mo | 3mo+ | ✅ Production |
| `treasury_data` | treasury_ingestion | 900_011 | 1mo | 3mo+ | ✅ Production |
| `ofr_hedge_fund_data` | ofr_ingestion | 900_012 | 3mo | 6mo+ | ✅ Production |
| `benchmark_nav` | benchmark_ingest | 900_004 | 1mo | 3mo+ | ✅ Production |
| `nav_timeseries` | instrument_ingestion | 900_010 | 1mo | 3mo+ | ✅ Production |
| `fund_risk_metrics` | risk_calc | 900_007 | 1mo | 3mo+ | ✅ Production |
| `portfolio_snapshots` | portfolio_eval | 900_008 | 1mo | 3mo+ | ✅ Production |
| `strategy_drift_alerts` | drift_check | 42 | 1mo | 3mo+ | ✅ Production |
| `sec_13f_holdings` | seed/on-demand | — | 3mo | 6mo+ | ✅ Production |
| `sec_13f_diffs` | seed/on-demand | — | 3mo | 6mo+ | ✅ Production |
| `sec_institutional_allocations` | seed/on-demand | — | 3mo | 6mo+ | ✅ Production |

### 1.2 Opportunities — Wealth Vertical

#### A. Manager Screener Aggregation Cache (Redis)

**Problem:** The Manager Screener query joins 4 global tables (`sec_managers` + `sec_13f_holdings` + `sec_13f_diffs` + `sec_institutional_allocations`) with an org-scoped left join on `instruments_universe`. With 5000+ managers and multi-quarter holdings, the full query can be heavy.

**Opportunity:** Pre-compute and cache screener aggregates in Redis.

```
Key: screener:agg:{crd_number}
TTL: 24h (refreshed by SEC worker)
Value: {
  top_sector: "Information Technology",
  hhi: 0.0834,
  position_count: 127,
  portfolio_value: 2_400_000_000,
  turnover_4q: 0.23,
  style_drift: false,
  institutional_holders_count: 14,
  last_13f_date: "2025-12-31"
}
```

**Impact:** Screener list endpoint drops from complex multi-table join to `sec_managers` + Redis lookup. Sub-100ms for 5000 rows.

#### B. Analytics Correlation Pre-computation

**Problem:** `GET /analytics/correlation` computes correlation matrix on every request from NAV time-series (O(n²) for n instruments, window-dependent).

**Opportunity:** Pre-compute correlation matrices by profile in the `risk_calc` worker. Store in Redis or a new `correlation_snapshots` table.

```
Key: correlation:{org_id}:{profile}:{date}
TTL: 24h
Value: {matrix: [[...]], tickers: [...], regime: "risk_on"}
```

**Impact:** Correlation heatmap renders instantly. Regime-conditioned correlation becomes a lookup instead of computation.

#### C. Scoring Leaderboard Cache

**Problem:** Fund scoring route reads `fund_risk_metrics` for all instruments, sorts, ranks. Repeated on every page load.

**Opportunity:** Pre-compute rank percentiles in `risk_calc` worker, store in `fund_risk_metrics.rank_percentile` column or Redis sorted set.

```
Key: scoring:leaderboard:{org_id}:{profile}
TTL: 24h
Value: sorted set of (instrument_id, composite_score)
```

**Impact:** Screener Layer 3 (quant scoring) and fund listing pages become O(1) lookups.

#### D. Exposure Aggregation Worker

**Problem:** `GET /exposure` computes geographic + sector exposure by iterating portfolio holdings. CPU-bound for large portfolios.

**Opportunity:** Add exposure computation to `portfolio_eval` worker. Store in `portfolio_snapshots.exposure_json`.

**Impact:** Exposure heatmap renders from pre-computed snapshot. Zero in-request computation.

### 1.3 Opportunities — Credit Vertical

#### E. Credit Market Data Snapshot Cache

**Problem:** `get_macro_snapshot()` in credit `market_data` reads ~65 FRED series from `macro_data` hypertable on every deep review. Each deep review does this independently.

**Opportunity:** Cache the assembled macro snapshot in Redis (daily TTL, keyed by date + geography).

```
Key: credit:macro_snapshot:{geography}:{date}
TTL: 24h
Value: {rates: {...}, spreads: {...}, indicators: {...}, case_shiller: {...}}
```

**Impact:** Deep review stage 5 (macro injection) goes from ~50 DB reads to 1 Redis GET. Batch deep reviews (multiple deals) benefit most.

#### F. EDGAR Data Freshness Worker

**Problem:** 13F holdings for credit EDGAR analysis are fetched on-demand via `ThirteenFService.fetch_holdings()` with 45-day staleness TTL. First request for a new entity is slow (EDGAR parse).

**Opportunity:** Background worker that refreshes 13F holdings for all entities referenced in active deals/portfolio. Run daily.

```
Worker: sec_refresh
Lock ID: 900_013
Scope: global
Table: sec_13f_holdings, sec_13f_diffs
Source: EDGAR (entities from active credit deals + wealth universe)
```

**Impact:** Credit deep review EDGAR stage (stage 4) always hits warm cache. Zero cold-start latency for known entities.

### 1.4 Opportunities — Cross-Vertical

#### G. Macro Dashboard Widget Cache

**Problem:** Both wealth `/dashboard` and credit `/dashboard` render macro summary chips from `macro_data` + `macro_regional_snapshots`.

**Opportunity:** Pre-compute dashboard macro widget payload in `macro_ingestion` worker. Store in Redis.

```
Key: macro:dashboard_widget
TTL: until next ingestion run
Value: {
  regime: "RISK_ON",
  vix: 18.2,
  yield_curve: 0.45,
  regions: {US: {score: 62, trend: "improving"}, ...}
}
```

**Impact:** Dashboard macro chips load in <10ms. No DB query on every page view.

---

## 2. Manager Screener Module

### 2.1 What We're Building

A dedicated module within Wealth OS for discovery, monitoring, and peer comparison of SEC-registered investment managers. It operates entirely over existing global SEC tables (`sec_managers`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_institutional_allocations`) with a left join to `instruments_universe` for status linkage. No new data models.

The primary action — "Add to Universe" — injects the manager into the existing IC approval flow exactly like any other instrument. The screener is a channel of entry, not a bypass.

### 2.2 Three Modes, One Interface

| Mode | Context | Pre-filter | Primary Use Case |
|------|---------|-----------|-----------------|
| **Discovery** | No filter applied | Full SEC universe | Find unknown managers matching mandate criteria |
| **Monitoring** | `universe_status IN (approved, dd_pending, watchlist)` | Only tracked managers | Watch for drift, compliance changes, AUM shifts |
| **Peer Comparison** | Multi-select (2-5 managers) | User selection | Side-by-side metrics, overlap analysis |

The interface is identical — mode is determined by filter state and selection behavior. No explicit "mode toggle".

### 2.3 Data Architecture

All filters and columns derive from existing tables:

```
sec_managers                    → firm-level attributes (AUM, fees, compliance, geography)
sec_13f_holdings (latest Q)     → current portfolio snapshot (sectors, concentration, size)
sec_13f_diffs (last 4Q)         → drift signals (turnover, style rotation, activity)
sec_institutional_allocations   → institutional pedigree (endowments, pensions, foundations)
instruments_universe            → link to managers already in the Wealth OS flow
sec_cusip_ticker_map            → CUSIP→ticker for holdings enrichment
```

**Zero new ORM models.** The screener is a read-only view layer with one write action (Add to Universe → creates `Instrument` row).

### 2.4 Filter Blocks

#### Block 1 — Firm (sec_managers)

| Filter | Type | Column | SQL Pattern |
|--------|------|--------|------------|
| AUM range | range slider | `aum_total` | `aum_total BETWEEN :min AND :max` |
| Strategy type | multi-select | `client_types` JSONB | `client_types ?| array[:types]` |
| Fee type | multi-select | `fee_types` JSONB | `fee_types ?| array[:types]` |
| Geography | multi-select | `state`, `country` | `state = ANY(:states) OR country = ANY(:countries)` |
| Registration status | select | `registration_status` | `registration_status = :status` |
| Compliance clean | toggle | `compliance_disclosures` | `compliance_disclosures = 0` |
| Last ADV filed | date range | `last_adv_filed_at` | `last_adv_filed_at BETWEEN :from AND :to` |

#### Block 2 — Portfolio (sec_13f_holdings, latest quarter)

| Filter | Type | Column | SQL Pattern |
|--------|------|--------|------------|
| Sector exposure | multi-select | `sector` (post-enrichment) | Subquery: sectors present in latest Q |
| Top holding concentration | range | HHI computed | `HAVING hhi BETWEEN :min AND :max` |
| Position count | range | `COUNT(cusip)` per CIK/quarter | `HAVING position_count BETWEEN :min AND :max` |
| Min portfolio size | range | `SUM(market_value)` | `HAVING portfolio_value >= :min` |

#### Block 3 — Drift (sec_13f_diffs, last 4 quarters)

| Filter | Type | Column | SQL Pattern |
|--------|------|--------|------------|
| Style drift detected | toggle | derived (sector rotation) | Subquery: sector weight delta > threshold |
| Turnover rate | range | `(EXITED + NEW_POSITION) / total` | `HAVING turnover BETWEEN :min AND :max` |
| High activity quarters | range | quarters with turnover > threshold | `HAVING active_quarters >= :min` |

#### Block 4 — Institutional Pedigree (sec_institutional_allocations)

| Filter | Type | Column | SQL Pattern |
|--------|------|--------|------------|
| Institutional holders | toggle | EXISTS check | `EXISTS (SELECT 1 FROM sec_institutional_allocations ...)` |
| Holder type | multi-select | `filer_type` | `filer_type = ANY(:types)` |

#### Block 5 — Universe Status (instruments_universe join)

| Filter | Type | Column | SQL Pattern |
|--------|------|--------|------------|
| In universe | multi-select | join presence | `LEFT JOIN instruments_universe ... WHERE iu.instrument_id IS [NOT] NULL` |
| Status | multi-select | `approval_status` | `iu.approval_status = ANY(:statuses)` |

### 2.5 Result Table

Default columns (all server-side sortable):

| Column | Source | Computation |
|--------|--------|------------|
| Manager name | `sec_managers.firm_name` | Direct |
| AUM | `sec_managers.aum_total` | Direct |
| Strategy | `sec_managers.client_types` | JSONB keys extraction |
| Top sector | `sec_13f_holdings` aggregated | `MAX(SUM(market_value))` by sector, latest Q |
| HHI | computed | `SUM(weight²)` from latest Q holdings |
| Compliance | `sec_managers.compliance_disclosures` | Direct |
| Drift signal | `sec_13f_diffs` derived | Boolean: any quarter with turnover > 25% |
| Institutional holders | `sec_institutional_allocations` | `COUNT(DISTINCT filer_cik)` |
| Universe status | `instruments_universe` join | `approval_status` or "not_in_universe" |
| Last 13F | `sec_13f_holdings.report_date` | `MAX(report_date)` |

**Performance:** VirtualList for 5000+ rows. Server-side pagination (50/page default, max 100). Sort by any column.

### 2.6 Backend Architecture

**Route file:** `backend/app/domains/wealth/routes/manager_screener.py`

**Endpoints:**

```
GET  /manager-screener              → paginated list with all filters
GET  /managers/{crd}/profile        → Profile tab (ADV data + team)
GET  /managers/{crd}/holdings       → Holdings tab (sectors, top 10, HHI)
GET  /managers/{crd}/drift          → Drift tab (turnover timeline)
GET  /managers/{crd}/institutional  → Institutional tab (13F reverse)
GET  /managers/{crd}/universe       → Universe tab (status, links)
POST /managers/{crd}/add-to-universe → Create Instrument (pending status)
POST /managers/compare              → Peer comparison (2-5 CRDs)
```

**Query Strategy:**

The main screener endpoint uses a dynamic SQL builder (not ORM). The query starts from `sec_managers` and left-joins derived subqueries for holdings aggregates, drift signals, institutional counts, and universe status.

```sql
WITH latest_quarter AS (
    SELECT cik, MAX(report_date) AS latest_q
    FROM sec_13f_holdings
    GROUP BY cik
),
holdings_agg AS (
    SELECT h.cik,
           COUNT(DISTINCT h.cusip) AS position_count,
           SUM(h.market_value) AS portfolio_value,
           -- HHI: sum of squared weights
           SUM(POWER(h.market_value::float / NULLIF(q_total.total, 0), 2)) AS hhi,
           -- Top sector
           (SELECT sector FROM sec_13f_holdings h2
            WHERE h2.cik = h.cik AND h2.report_date = lq.latest_q
            GROUP BY sector ORDER BY SUM(market_value) DESC LIMIT 1) AS top_sector
    FROM sec_13f_holdings h
    JOIN latest_quarter lq ON h.cik = lq.cik AND h.report_date = lq.latest_q
    JOIN LATERAL (
        SELECT SUM(market_value) AS total
        FROM sec_13f_holdings WHERE cik = h.cik AND report_date = lq.latest_q
    ) q_total ON true
    GROUP BY h.cik, lq.latest_q, q_total.total
),
drift_agg AS (
    SELECT cik,
           COUNT(DISTINCT quarter_to) FILTER (
               WHERE (SELECT COUNT(*) FILTER (WHERE action IN ('NEW_POSITION', 'EXITED'))::float
                      / NULLIF(COUNT(*), 0)
                      FROM sec_13f_diffs d2
                      WHERE d2.cik = d.cik AND d2.quarter_to = d.quarter_to) > 0.25
           ) AS high_activity_quarters,
           BOOL_OR(...) AS style_drift
    FROM sec_13f_diffs d
    WHERE quarter_to >= (CURRENT_DATE - INTERVAL '15 months')
    GROUP BY cik
),
institutional_agg AS (
    SELECT target_cusip, COUNT(DISTINCT filer_cik) AS holder_count
    FROM sec_institutional_allocations
    WHERE report_date >= (CURRENT_DATE - INTERVAL '6 months')
    GROUP BY target_cusip
)
SELECT
    m.crd_number, m.firm_name, m.aum_total, m.client_types,
    ha.top_sector, ha.hhi, ha.position_count, ha.portfolio_value,
    m.compliance_disclosures,
    COALESCE(da.high_activity_quarters, 0) > 0 AS drift_signal,
    COALESCE(ic.holder_count, 0) AS institutional_holders_count,
    iu.approval_status AS universe_status,
    lq.latest_q AS last_13f_date
FROM sec_managers m
LEFT JOIN latest_quarter lq ON m.cik = lq.cik
LEFT JOIN holdings_agg ha ON m.cik = ha.cik
LEFT JOIN drift_agg da ON m.cik = da.cik
LEFT JOIN LATERAL (
    -- institutional holders for this manager's CUSIPs
    SELECT COUNT(DISTINCT ia.filer_cik) AS holder_count
    FROM sec_13f_holdings h
    JOIN sec_institutional_allocations ia ON ia.target_cusip = h.cusip
    WHERE h.cik = m.cik AND h.report_date = lq.latest_q
    AND ia.report_date >= (CURRENT_DATE - INTERVAL '6 months')
) ic ON true
LEFT JOIN instruments_universe iu ON iu.attributes->>'crd_number' = m.crd_number
    AND iu.organization_id = :org_id
WHERE 1=1
    -- Dynamic filters appended here
ORDER BY :sort_col :sort_dir
LIMIT :page_size OFFSET (:page - 1) * :page_size
```

**Key Decision:** The `instruments_universe` join uses `attributes->>'crd_number'` to link SEC managers to the Wealth OS universe. When "Add to Universe" creates an Instrument, it sets `attributes = {"source": "sec_manager", "crd_number": "..."}`. No new FK column needed.

### 2.7 ContextPanel (Drill-Down)

#### Tab 1 — Profile
- ADV data: AUM (total/discretionary/non-discretionary), fee structure, compliance history, account count
- Registration info, website, headquarters (state/country)
- Team members (stub M1, full M2 via Part 2A PDF OCR)

#### Tab 2 — Holdings
- Sector allocation chart (pie or horizontal bar) — current quarter + 4 quarters prior (small multiples or overlay)
- Top 10 positions table: CUSIP, issuer name, market value, weight %, sector
- Style drift timeline: sector weights over 8 quarters as stacked area chart

#### Tab 3 — Institutional
- List of endowments/pensions/foundations that hold the manager's securities (via 13F reverse)
- Coverage type indicator: `FOUND` / `PUBLIC_SECURITIES_NO_HOLDERS` / `NO_PUBLIC_SECURITIES`
- Holder details: filer name, filer type, market value, report date

#### Tab 4 — Universe
- Current status in Wealth OS (not_in_universe / pending / dd_pending / approved / watchlist)
- Link to DD Report if exists
- Link to instrument detail page if approved
- **Primary action button** (varies by status — see §2.8)

### 2.8 Primary Action — Add to Universe

| Current Status | Button Label | Action |
|---------------|-------------|--------|
| not_in_universe | "Add to Universe" | `POST /managers/{crd}/add-to-universe` → creates `Instrument(approval_status="pending")` → IC approval flow |
| dd_pending | "View DD Report" | Navigate to `/dd-reports/{fundId}` |
| approved | "View in Portfolio" | Navigate to `/funds/{id}` |
| watchlist | "Review" | Open existing review workflow |

**Critical:** "Add to Universe" injects into the existing IC flow. It creates a single `Instrument` row with `approval_status = "pending"` — identical to manual instrument creation. No parallel approval track.

### 2.9 Peer Comparison Mode

Activated when 2-5 managers are checkbox-selected in the result table.

**Comparison Panel:**

| Component | Data Source | Visualization |
|-----------|-----------|---------------|
| Metrics table | sec_managers + computed | Side-by-side: AUM, compliance, HHI, top sector, institutional holders |
| Sector allocation | sec_13f_holdings (latest Q) | Grouped bar chart — same axes, one group per manager |
| Holdings overlap | sec_13f_holdings cross-join | % of CUSIPs in common between selected managers (Jaccard similarity) |
| Drift comparison | sec_13f_diffs (4Q) | Line chart: turnover rate per quarter, one line per manager |

**Backend endpoint:** `POST /managers/compare` with body `{crd_numbers: ["...", "..."]}` — returns all comparison data in one response.

### 2.10 Schemas

```
backend/app/domains/wealth/schemas/manager_screener.py

ManagerScreenerResult       → paginated list response
ManagerRow                  → single row in screener table
ManagerProfileRead          → Profile tab
ManagerHoldingsRead         → Holdings tab (sector_allocation, top_10, hhi, sector_history)
ManagerDriftRead            → Drift tab (quarters: [{date, turnover_rate, actions}])
ManagerInstitutionalRead    → Institutional tab (holders, coverage_type)
ManagerUniverseRead         → Universe tab (status, dd_report_id, instrument_id)
ManagerToUniverseRequest    → Add to Universe body (instrument_type, asset_class, etc.)
ManagerCompareRequest       → Peer comparison request (crd_numbers: list[str])
ManagerCompareResult        → Peer comparison response
```

---

## 3. Additional Free Data Sources

### 3.1 Sources That Enrich the Manager Screener Directly

#### A. SEC Form N-PORT (Mutual Fund Holdings — Monthly)

**What:** Monthly portfolio holdings for registered investment companies (mutual funds, ETFs). Filed within 60 days of quarter-end, monthly data available.

**API:** EDGAR XBRL viewer + bulk downloads. Same `edgartools` library we already use.

**Enrichment:**
- Monthly holdings snapshots (vs 13F quarterly) for mutual fund managers
- Derivatives exposure (not in 13F)
- Cash/collateral positions
- Liquidity classification (highly liquid / moderately liquid / less liquid / illiquid)

**Tables:**
```
sec_nport_holdings (hypertable)
  → report_date, cik, cusip, issuer_name, asset_type, market_value, shares,
    pct_of_nav, liquidity_classification, derivative_type
```

**Priority:** HIGH — fills the gap for non-13F filers (mutual funds that don't file 13F because they're investment companies, not institutional investors). Expands our universe from ~5000 13F filers to ~15000 registered funds.

#### B. SEC Form ADV Part 2A Brochure (Manager Narrative — PDF)

**What:** Firm brochure with investment philosophy, strategy description, risk factors, fee schedule, conflicts of interest, disciplinary history.

**API:** IAPD brochure download (PDF). OCR via Mistral (already integrated).

**Enrichment:**
- Investment philosophy text (searchable, embeddable)
- Detailed fee schedule (beyond the CSV boolean flags we currently parse)
- Disciplinary history detail (not just count from Q11)
- Key person bios with full narrative

**Implementation:** Already stubbed as M2 scope in `AdvService.fetch_manager_team()`. Uses existing Mistral OCR pipeline.

**Tables:** Populates existing `sec_manager_team` (currently stub). Adds `sec_manager_brochure_text` for full-text search.

**Priority:** HIGH — transforms the Profile tab from basic ADV CSV data to rich narrative. Enables text search across manager philosophies ("value investing", "ESG integration", "private credit").

#### C. SEC Form D (Private Fund Offerings)

**What:** Notice of exempt offering. Contains fund size, investor count, minimum investment, use of proceeds.

**API:** EDGAR EFTS search + XBRL parsing.

**Enrichment:**
- Private fund size history (Form D amendments over time)
- Minimum investment amounts
- Number of investors (more granular than ADV Schedule D)
- Offering type (506(b), 506(c), Reg A, etc.)
- Sales compensation data

**Tables:**
```
sec_form_d_offerings (no hypertable — low volume)
  → cik, file_date, fund_name, total_offering_amount, total_amount_sold,
    total_remaining, investor_count, min_investment, offering_type
```

**Priority:** MEDIUM — useful for private fund manager screening. Less relevant for public equity managers.

### 3.2 Sources That Enrich the Macro/Market Intelligence

#### D. BIS (Bank for International Settlements) Statistics

**What:** International banking statistics, OTC derivatives, credit-to-GDP, debt service ratios, property prices across 60+ countries.

**API:** `https://data.bis.org/api/v2/` — RESTful JSON, no auth required, generous rate limits.

**Key Series:**
- Total credit to non-financial sector (% GDP) — all 60+ countries
- Property price indices (residential) — 60+ countries
- Debt service ratios — 32 countries
- OTC derivatives market statistics
- Effective exchange rates (broad + narrow)

**Enrichment:**
- Cross-country credit cycle indicators (credit-to-GDP gap = Basel III countercyclical buffer trigger)
- Global property market comparison (complements Case-Shiller domestic)
- Debt sustainability metrics for EM sovereign exposure
- Global derivatives market context for OFR hedge fund analysis

**Tables:**
```
bis_statistics (hypertable)
  → obs_date, series_id, value, country, frequency
  → Worker: bis_ingestion (Lock ID: 900_014, quarterly)
```

**Priority:** HIGH — directly enriches regional macro scoring. credit-to-GDP gap is the most cited early warning indicator for banking crises. No other free source provides this.

#### E. IMF World Economic Outlook (WEO) Database

**What:** GDP forecasts, inflation forecasts, fiscal balance, current account — 190+ countries, 5-year forward projections.

**API:** `https://www.imf.org/external/datamapper/api/v1/` — JSON, no auth.

**Key Series:**
- GDP growth forecasts (current year + 5 forward years)
- Inflation projections
- Government fiscal balance (% GDP)
- Current account balance (% GDP)
- Public debt (% GDP)

**Enrichment:**
- Forward-looking macro context (FRED is backward-looking observations, IMF is projections)
- Enables "macro outlook vs. current positioning" analysis in Manager Screener
- Enhances Investment Outlook quarterly reports with IMF consensus

**Tables:**
```
imf_weo_forecasts (hypertable)
  → obs_date, series_id, country, forecast_year, value, vintage
  → Worker: imf_ingestion (Lock ID: 900_015, semi-annual — April + October WEO)
```

**Priority:** MEDIUM-HIGH — the only free source of consensus macro forecasts. Useful for the Macro Committee Engine and Investment Outlook content.

#### F. World Bank Open Data

**What:** Development indicators — 1400+ indicators across 200+ countries. Demographics, education, health, infrastructure, governance.

**API:** `https://api.worldbank.org/v2/` — JSON/XML, no auth. Already partially covered by Data Commons.

**Key Differentiators vs Data Commons:**
- Governance indicators (rule of law, regulatory quality, political stability) — direct input to EM country risk
- Financial inclusion metrics
- Logistics Performance Index
- Ease of Doing Business (archived but still valuable)

**Priority:** LOW — Data Commons already covers demographics. Governance indicators could enrich EM macro scoring but are annual frequency.

#### G. ECB Statistical Data Warehouse

**What:** Euro area monetary, financial, and economic statistics. More granular than FRED's European series.

**API:** `https://data-api.ecb.europa.eu/service/data/` — RESTful SDMX, no auth.

**Key Series:**
- MFI balance sheet items (credit growth by sector)
- Securities statistics (debt issuance, corporate bonds)
- Bank interest rates (MFI lending rates by maturity)
- Payment statistics
- Euro area yield curves (full term structure, daily)

**Enrichment:**
- Granular European financial conditions (beyond FRED's EA-level aggregates)
- European credit cycle indicators
- European yield curve for attribution analysis (EU-denominated portfolios)

**Tables:**
```
ecb_statistics (hypertable)
  → obs_date, series_id, value, frequency
  → Worker: ecb_ingestion (Lock ID: 900_016, daily for rates, monthly for others)
```

**Priority:** MEDIUM — valuable for European exposure analysis in Wealth portfolios. Currently we only have aggregate EA data from FRED.

#### H. OECD Data Explorer

**What:** Composite leading indicators, housing prices, consumer confidence, business confidence across 38 OECD + partner countries.

**API:** `https://sdmx.oecd.org/public/rest/data/` — SDMX-JSON, no auth.

**Key Series:**
- Composite Leading Indicators (CLI) — 38 countries (6-9 month forward signal)
- Business Confidence Index (BCI)
- Consumer Confidence Index (CCI)
- Housing Price-to-Income / Price-to-Rent ratios

**Enrichment:**
- CLIs are the canonical forward-looking cyclical indicator. FRED has some OECD CLIs but with lag. Direct OECD source is fresher.
- Housing valuation ratios complement Case-Shiller levels

**Tables:**
```
oecd_statistics (hypertable)
  → obs_date, series_id, country, value, frequency
  → Worker: oecd_ingestion (Lock ID: 900_017, monthly)
```

**Priority:** MEDIUM — CLIs would strengthen the regime classification engine with forward-looking signals.

### 3.3 Sources That Enrich the Credit Vertical Specifically

#### I. SEC EDGAR Full-Text Search (EFTS) — Expanded

**What:** We already use EFTS for CIK resolution and institutional filer discovery. But EFTS indexes ALL SEC filings — 10-K, 10-Q, 8-K, proxy statements, etc.

**Enrichment for Credit:**
- 10-K risk factor text extraction (searchable across all public issuers)
- 8-K material event detection (M&A, defaults, covenant violations)
- Proxy statement governance data (board composition, compensation)
- Going concern opinion detection (auditor language in 10-K)

**Already partially implemented** in `vertical_engines/credit/edgar/` — entity extraction uses edgartools for financials, ratios, insider signals. Expanding to full-text 8-K search would enable real-time credit event detection.

**Priority:** MEDIUM — incremental enhancement to existing EDGAR integration.

#### J. FDIC BankFind API

**What:** Financial institution data — all FDIC-insured banks and branches. Call reports, financial data, enforcement actions.

**API:** `https://banks.data.fdic.gov/api/` — RESTful JSON, no auth.

**Key Data:**
- Bank financial summary (assets, deposits, net income, ROA, ROE)
- History events (mergers, name changes, status changes)
- Enforcement actions and failures
- Branch locations

**Enrichment for Credit:**
- Counterparty risk assessment (is the lender/bank healthy?)
- Bank failure history for stress scenarios
- Concentration risk (geographic bank coverage)

**Priority:** LOW for current scope — more relevant when credit vertical expands to direct lending analysis.

### 3.4 Sources That Create Competitive Differentiation

#### K. UN Comtrade (International Trade Data)

**What:** Bilateral trade flows between 200+ countries, 5000+ commodity codes. Monthly updates.

**API:** `https://comtradeapi.un.org/` — JSON, free tier (250 requests/day).

**Enrichment:**
- Trade flow disruption signals (sanctions impact, supply chain shifts)
- Commodity-specific import/export trends
- Trade balance trends for currency risk assessment

**Priority:** LOW — niche but differentiating. No competitor in the wealth management space offers trade flow analytics.

#### L. GLEIF (Global Legal Entity Identifier Foundation)

**What:** LEI database linking legal entities to their parent structures. Maps corporate hierarchies.

**API:** `https://api.gleif.org/api/v1/` — JSON, no auth, no rate limit.

**Enrichment:**
- Map SEC CIK → LEI → corporate parent → ultimate parent
- Identify manager group affiliations
- Detect fund-of-funds structural relationships
- Cross-reference institutional holders by corporate family

**Priority:** MEDIUM — improves institutional ownership analysis by deduplicating related entities and mapping corporate hierarchies.

### 3.5 UCITS Fund Data — Reality Check & Pragmatic Approach

#### The EU vs US Transparency Gap

MiFID II / UCITS V increased transparency **for the end investor** (KID documents, fee disclosure, suitability), but did NOT create a centralized, structured, free data repository like SEC EDGAR. The data exists but is fragmented:

| Data | US (SEC) | EU (UCITS) |
|------|----------|------------|
| Portfolio holdings (position-level) | 13F quarterly, N-PORT monthly — **public, free, structured** | Annual/semi-annual report PDF on fund website — **not centralized** |
| Daily NAV | Yahoo Finance (mutual funds listed) | Published by fund on its own site — **no free central repo** |
| Fee breakdown | ADV CSV bulk — **free, structured** | KIID/KID document — **PDF per fund** |
| Manager AUM | ADV Q5F2 — **free, structured** | AIFMD Annex IV — **regulator-only, not public** |
| Institutional ownership | 13F reverse lookup — **free** | No equivalent |
| Fund catalog | EDGAR company search | ESMA Register — **free, API available** |

Commercial providers (Morningstar, Refinitiv/Lipper, Bloomberg, fundinfo) aggregate this fragmented EU data and charge $$$$ for it. This is exactly what eVestment uses for European coverage.

#### Tier 1 — Factível Agora (Zero Cost)

**Strategy: ESMA Register (catalog) → ISIN → Yahoo Finance (NAV) → DB seed**

Three free sources combined give us ~5-10K UCITS funds with daily NAV:

1. **ESMA Register** (`esma-registers` Python package) → ~15K management companies + funds authorized for cross-border marketing. Fields: fund name, ISIN, management company, domicile, fund type, host member state.

2. **Yahoo Finance** (`yfinance`) → Daily NAV for UCITS with exchange-listed ISINs. Coverage by exchange suffix:
   - `.L` London Stock Exchange (~3000 UCITS ETFs + funds)
   - `.PA` Euronext Paris
   - `.AS` Euronext Amsterdam
   - `.DE` / `.F` Frankfurt (Xetra / Frankfurt)
   - `.MI` Borsa Italiana
   - `.SW` SIX Swiss Exchange
   - `.IR` Euronext Dublin
   - `.BR` Euronext Brussels

3. **ECB IVF Statistics** → Aggregate fund flows by country × fund type (monthly). Macro signal for regime scoring, not fund-level.

#### ESMA → Yahoo Finance Seed Pipeline

**Location:** `backend/data_providers/esma/` (new data provider, follows `sec/` pattern)

```
backend/data_providers/esma/
  __init__.py
  models.py              ← frozen dataclasses (EsmaManager, EsmaFund, IsinResolution)
  register_service.py    ← ESMA Register API client (esma-registers package)
  ticker_resolver.py     ← ISIN → YFinance ticker resolution (exchange suffix cascade)
  seed/
    __init__.py
    populate_seed.py     ← 4-phase resumable seed (follows sec/seed pattern)
```

**Phase 1 — Ingest ESMA Register:**
- Download UCITS management companies + cross-border fund notifications via `esma-registers` Python package
- Parse into `EsmaManager` (management company) and `EsmaFund` (individual fund with ISIN)
- Upsert to `esma_managers` and `esma_funds` tables

**Phase 2 — ISIN → Yahoo Finance Ticker Resolution:**
- For each fund ISIN, attempt resolution via exchange suffix cascade:
  ```
  ISIN: LU0996182563
  Try: LU0996182563.L → LU0996182563.PA → LU0996182563.AS → LU0996182563.DE → ...
  Method: yfinance.Ticker(candidate).info — check if valid (has regularMarketPrice)
  ```
- Cache results in `esma_isin_ticker_map` (similar to `sec_cusip_ticker_map`)
- Batch processing: ~15K ISINs × 8 suffixes = ~120K attempts, but with early exit on first hit
- Rate limit: YFinance is generous but throttle to 5 req/s to be safe
- Expected yield: ~5-10K resolved tickers (ETFs + exchange-listed fund classes)

**Phase 3 — NAV History Backfill:**
- For resolved tickers, fetch 3-year NAV history via `yfinance.download()`
- Upsert to existing `nav_timeseries` hypertable (with `source = "yfinance_esma"`)
- Create corresponding `Instrument` entries in `instruments_universe` with:
  ```python
  attributes = {
      "source": "esma_register",
      "isin": "LU0996182563",
      "management_company": "BlackRock (Luxembourg) S.A.",
      "domicile": "LU",
      "fund_type": "UCITS",
      "esma_fund_id": "...",
  }
  ```

**Phase 4 — Management Company Linkage:**
- Cross-reference ESMA management companies with SEC managers via:
  - Name fuzzy match (rapidfuzz, threshold 0.85)
  - LEI lookup (GLEIF API, if LEI available in ESMA register)
- Store linkage in `esma_managers.sec_crd_number` (nullable FK)
- Enables: "This manager operates in both US (SEC) and EU (ESMA)" unified view

#### Database Tables (Global, No RLS)

```sql
-- Management companies from ESMA Register
CREATE TABLE esma_managers (
    esma_id         TEXT PRIMARY KEY,      -- ESMA register internal ID
    lei             TEXT,                   -- Legal Entity Identifier (if available)
    company_name    TEXT NOT NULL,
    country         TEXT,                   -- Home member state (2-letter ISO)
    authorization_status TEXT,              -- Authorized / Withdrawn
    fund_count      INTEGER,               -- Number of funds under management
    sec_crd_number  TEXT,                   -- Cross-reference to sec_managers (nullable)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fetched_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_esma_managers_lei ON esma_managers(lei) WHERE lei IS NOT NULL;
CREATE INDEX idx_esma_managers_country ON esma_managers(country);

-- Individual UCITS funds from ESMA Register
CREATE TABLE esma_funds (
    isin            TEXT PRIMARY KEY,       -- ISIN is natural PK for UCITS
    fund_name       TEXT NOT NULL,
    esma_manager_id TEXT NOT NULL REFERENCES esma_managers(esma_id),
    domicile        TEXT,                   -- Fund domicile country
    fund_type       TEXT,                   -- UCITS / AIF / MMF / ELTIF
    host_member_states TEXT[],              -- Countries where marketed cross-border
    yahoo_ticker    TEXT,                   -- Resolved YFinance ticker (nullable)
    ticker_resolved_at TIMESTAMPTZ,         -- When resolution was last attempted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fetched_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_esma_funds_manager ON esma_funds(esma_manager_id);
CREATE INDEX idx_esma_funds_ticker ON esma_funds(yahoo_ticker) WHERE yahoo_ticker IS NOT NULL;
CREATE INDEX idx_esma_funds_domicile ON esma_funds(domicile);

-- ISIN → YFinance ticker resolution cache
CREATE TABLE esma_isin_ticker_map (
    isin            TEXT PRIMARY KEY,
    yahoo_ticker    TEXT,                   -- e.g., "LU0996182563.L"
    exchange        TEXT,                   -- "LSE", "XETRA", "EURONEXT", etc.
    resolved_via    TEXT NOT NULL,          -- "suffix_cascade" | "unresolved"
    is_tradeable    BOOLEAN NOT NULL,       -- Has valid YFinance data
    last_verified_at TIMESTAMPTZ NOT NULL
);
```

**Note:** These are NOT hypertables (low-volume reference data). The NAV data goes into the existing `nav_timeseries` hypertable via standard `instrument_ingestion` worker.

#### Integration with Manager Screener

The ESMA data expands the Manager Screener in two ways:

1. **European manager catalog:** `esma_managers` appears alongside `sec_managers` in discovery mode. Filter by `country` for EU managers, `registration_status` for SEC managers.

2. **Cross-border presence indicator:** When an SEC manager has a linked `esma_managers.sec_crd_number`, the screener shows "Also registered in EU (ESMA)" — signals global reach.

3. **UCITS fund NAV in existing workflows:** Resolved ESMA funds flow into `instruments_universe` → existing screening, risk calc, DD report pipelines. No new workflow needed.

#### Limitations (Honest Assessment)

- **No holdings data:** ESMA Register has zero portfolio composition. Only SEC 13F provides that.
- **No fee structure:** ESMA has fund type but not fee breakdown. That's in KIID PDFs (future extraction).
- **Partial NAV coverage:** ~5-10K of ~60K UCITS. ETFs have better coverage than traditional funds.
- **Management company data is thin:** Name, country, fund count. No AUM, no team, no compliance history (unlike SEC ADV).

#### Why It's Still Valuable

- **5-10K UCITS funds with daily NAV** is enough to build a credible European universe alongside our SEC universe
- **Management company catalog** provides the discovery dimension — "find all Luxembourg-domiciled equity UCITS managers"
- **Cross-border marketing data** tells you where each fund is distributed — a unique competitive signal
- **Zero marginal cost** — all free public data + `yfinance`
- **Incremental enrichment path** — fundinfo or Morningstar can be added later per-tenant when clients demand full UCITS coverage

---

## 4. Implementation Phases

### Phase 1 — Manager Screener Core (Backend + Frontend)

**Backend:**
1. `backend/app/domains/wealth/routes/manager_screener.py` — all endpoints
2. `backend/app/domains/wealth/schemas/manager_screener.py` — Pydantic schemas
3. No new ORM models (reads existing SEC global tables)
4. No new migrations
5. Redis aggregation cache (`screener:agg:{crd_number}`)

**Frontend:**
1. `frontends/wealth/src/routes/(team)/manager-screener/+page.svelte` — main page
2. Filter panel component (5 blocks, collapsible)
3. VirtualList result table
4. ContextPanel with 4 tabs
5. Peer Comparison panel (activated on multi-select)

### Phase 2 — Screener Aggregation Worker + Caching

1. SEC refresh worker (`sec_refresh`, Lock ID 900_013) — daily 13F freshness
2. Screener aggregation cache in Redis (pre-computed metrics per CRD)
3. Macro snapshot cache (credit + wealth dashboards)
4. Correlation pre-computation in `risk_calc` worker

### Phase 3 — ESMA Register + UCITS Yahoo Finance Seed

1. `backend/data_providers/esma/register_service.py` — ESMA Register API client (`esma-registers` package)
2. `backend/data_providers/esma/ticker_resolver.py` — ISIN → YFinance suffix cascade
3. `backend/data_providers/esma/models.py` — frozen dataclasses
4. `backend/data_providers/esma/seed/populate_seed.py` — 4-phase resumable seed
5. Migration for `esma_managers`, `esma_funds`, `esma_isin_ticker_map` tables (global, no RLS)
6. Resolved UCITS funds auto-create `Instrument` entries → flow into existing screening/risk/DD pipelines
7. Cross-reference ESMA management companies ↔ SEC managers (name fuzzy match + LEI)

### Phase 4 — N-PORT Integration

1. `backend/data_providers/sec/nport_service.py` — N-PORT bulk download + parse
2. Migration for `sec_nport_holdings` hypertable
3. N-PORT ingestion worker (Lock ID 900_018)
4. Expand Manager Screener to include mutual fund managers with N-PORT data

### Phase 5 — ADV Part 2A Brochure Extraction (M2 Scope)

1. Full implementation of `AdvService.fetch_manager_team()` via Mistral OCR
2. `sec_manager_brochure_text` table for full-text search
3. Manager philosophy search in screener ("value investing", "ESG", etc.)

### Phase 6 — BIS + IMF Macro Enrichment

1. `backend/data_providers/bis/service.py` — BIS Statistics API client
2. `backend/data_providers/imf/service.py` — IMF WEO API client
3. Hypertables + ingestion workers
4. Integrate into `regional_macro_service.py` scoring

---

## 5. Key Decisions

1. **No new ORM models for screener:** All data already exists in global SEC tables. The screener is a read-only view with dynamic SQL.
2. **Redis aggregation cache:** Pre-compute heavy joins (HHI, drift signals, institutional counts) per CRD. Refresh daily. Makes main listing sub-100ms.
3. **`instruments_universe.attributes->>'crd_number'`** for SEC→Wealth linkage. No FK column needed. Already supports JSONB queries.
4. **Dynamic SQL builder, not ORM:** The screener query is a complex multi-CTE join that would be painful in SQLAlchemy ORM. Raw SQL with parameterized filters is cleaner and faster.
5. **Phase N-PORT before Part 2A:** N-PORT data is structured (XBRL) and expands our universe 3x. Part 2A is unstructured (PDF OCR) and enriches existing managers.
6. **BIS credit-to-GDP gap** is the single most valuable new macro indicator. It's the Basel III canonical early warning signal and no competitor offers it free.
7. **ESMA Register → YFinance for UCITS:** ISIN suffix cascade resolution gives us ~5-10K European funds with daily NAV at zero cost. Funds flow into existing `instruments_universe` → screening → risk calc → DD report pipelines. No parallel workflow.
8. **SEC depth > EU breadth for competitive moat:** Our SEC data (13F holdings, diffs, institutional reverse, ADV) is uniquely deep and free. EU fund-level data is fragmented behind paywalls. We lead with SEC depth + EU catalog breadth, defer full EU fund-level to commercial providers when client demand justifies cost.

## Open Questions

1. **SEC refresh worker scope:** Should it refresh ALL 5000+ managers daily, or only managers referenced in active org's universe? Full refresh at 8 req/s = ~10 minutes but consumes EDGAR rate limit.
2. **Screener route authorization:** Should it require `INVESTMENT_TEAM` role, or should `ADVISOR` also have access for client-facing manager selection?
3. **Holdings overlap in Peer Comparison:** Jaccard similarity (% CUSIPs in common) or weighted overlap (% of portfolio value in common positions)?
4. **N-PORT priority:** Implement before or after Part 2A? N-PORT is higher data value but lower enrichment per manager.

## Next Steps

→ `/ce:plan` for Phase 1 implementation (Manager Screener Core)
