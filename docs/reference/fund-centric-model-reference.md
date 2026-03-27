# Fund-Centric Model Reference

> Netz Analysis Engine — Architectural reference for the fund-centric data model.
> Last updated: 2026-03-27.

---

## 1. Design Philosophy

The Netz Analysis Engine is organized around **funds as the primary analytical entity**. Every capability — discovery, screening, due diligence, risk computation, portfolio construction — revolves around a polymorphic instrument record that represents a fund.

Key principles:

- **Global discovery, tenant-scoped analysis.** SEC/ESMA fund data is shared (no RLS). Once a fund is imported into an organization's universe, it becomes tenant-scoped.
- **Three-universe normalization.** Three heterogeneous data sources (SEC N-PORT, SEC ADV Schedule D, ESMA Register) are unified into a single polymorphic catalog schema.
- **Disclosure-driven rendering.** Each fund carries a `DisclosureMatrix` that declares what data is available. The frontend conditionally renders panels based on these flags — never hard-codes per-universe logic.
- **Pre-computed metrics, zero hot-path API calls.** All external data (FRED, Treasury, Yahoo Finance, SEC EDGAR) is pre-ingested by background workers into hypertables. User-facing routes and engines read from DB only.

---

## 2. Entity Hierarchy

```
SEC EDGAR (global)                   ESMA Register (global)
  |                                    |
  sec_managers (CRD)                   esma_managers (esma_id)
  |       \                            |
  |        sec_manager_funds           esma_funds (ISIN)
  |        (ADV Schedule D)
  |
  sec_registered_funds (CIK)
  |
  sec_fund_classes (CIK, series_id, class_id)

          |                |                |
          v                v                v
    ┌──────────────────────────────────────────────┐
    │        Unified Fund Catalog (UNION ALL)       │
    │   registered_us  |  private_us  |  ucits_eu   │
    └─────────────────────┬────────────────────────┘
                          |
                    (user imports)
                          |
                          v
              instruments_universe (org-scoped, RLS)
              |           |            |
     nav_timeseries  fund_risk_metrics  wealth_vector_chunks
              |
       screening_results → dd_reports → universe_approvals
```

---

## 3. Three-Universe Model

### 3.1 registered_us — SEC Registered Funds

| Attribute | Value |
|-----------|-------|
| Source | SEC EDGAR N-PORT filings |
| Primary key | `cik` (fund-level Central Index Key) |
| Table | `sec_registered_funds` |
| Fund types | mutual_fund, etf, closed_end, interval, uit |
| Holdings | N-PORT quarterly (sec_nport_holdings hypertable) |
| NAV | Yahoo Finance via ticker |
| AUM source | N-PORT total_assets |
| Share classes | `sec_fund_classes` (series_id → class_id → ticker) |
| Manager link | `crd_number` FK → `sec_managers` |
| 13F overlay | Correlated subquery checks if manager files 13F-HR |

**Share class model:**

A single registered fund (one CIK) may contain multiple **series**, each with multiple **share classes**:

```
Fund CIK 0000789019
  ├─ Series S000001111 "Growth Fund"
  │   ├─ Class C000001111 "Class A"  → ticker GRFAX
  │   ├─ Class C000002222 "Class I"  → ticker GRFIX
  │   └─ Class C000003333 "Class R6" → ticker GRFRX
  └─ Series S000002222 "Income Fund"
      ├─ Class C000004444 "Institutional" → ticker INCIX
      └─ Class C000005555 "Investor"      → ticker INCVX
```

The catalog query `LEFT JOIN sec_fund_classes` produces **one row per class** for registered funds. Funds without classes produce one row with NULL class fields. The frontend groups rows by `external_id` (CIK) and renders a tree view with expand/collapse.

### 3.2 private_us — ADV Schedule D Private Funds

| Attribute | Value |
|-----------|-------|
| Source | SEC Form ADV bulk CSV (monthly FOIA) |
| Primary key | UUID (sec_manager_funds.id) |
| Table | `sec_manager_funds` |
| Fund types | hedge, pe, vc, real_estate, securitized_asset, other |
| Holdings | None |
| NAV | None |
| AUM source | Schedule D `gross_asset_value` |
| Share classes | N/A |
| Manager link | `crd_number` FK → `sec_managers` |

Private funds have no EDGAR filings, no ticker, no NAV history. Their disclosure matrix is minimal: only `has_private_fund_data=True` and potentially `has_13f_overlay` if the manager files 13F.

### 3.3 ucits_eu — ESMA Register UCITS

| Attribute | Value |
|-----------|-------|
| Source | ESMA Fund Register |
| Primary key | `isin` |
| Table | `esma_funds` |
| Fund types | ucits |
| Holdings | None |
| NAV | Yahoo Finance via `yahoo_ticker` |
| AUM source | None |
| Share classes | N/A |
| Manager link | `esma_manager_id` FK → `esma_managers` |

Only UCITS funds with a resolved `yahoo_ticker` appear in the catalog (others are filtered out at the SQL level).

---

## 4. Unified Fund Catalog

### 4.1 Query Architecture

The catalog is built by `catalog_sql.py` as a `UNION ALL` of three SQL branches:

```sql
SELECT 'registered_us' AS universe, cik AS external_id, ...
  FROM sec_registered_funds
  LEFT JOIN sec_fund_classes ON ...
  LEFT JOIN sec_managers ON ...
UNION ALL
SELECT 'private_us' AS universe, id::text AS external_id, ...
  FROM sec_manager_funds
  JOIN sec_managers ON ...
UNION ALL
SELECT 'ucits_eu' AS universe, isin AS external_id, ...
  FROM esma_funds
  JOIN esma_managers ON ...
  WHERE yahoo_ticker IS NOT NULL
```

**Performance:** ~130k total rows (50k registered + 50k private + 30k UCITS). PostgreSQL pushes WHERE predicates into each branch. `count() OVER()` window avoids a second roundtrip for pagination. If p95 exceeds 200ms at scale, a materialized view `mv_unified_fund_catalog` is the planned mitigation.

### 4.2 Schema: UnifiedFundItem

```python
class UnifiedFundItem(BaseModel):
    # Identity
    external_id: str                              # CIK | UUID | ISIN
    universe: "registered_us" | "private_us" | "ucits_eu"
    name: str
    ticker: str | None
    isin: str | None

    # Share class (registered_us only)
    series_id: str | None
    series_name: str | None
    class_id: str | None
    class_name: str | None

    # Classification
    region: "US" | "EU"
    fund_type: str
    domicile: str | None
    currency: str | None

    # Manager
    manager_name: str | None
    manager_id: str | None                        # CRD | esma_id

    # Metrics
    aum: float | None
    inception_date: date | None
    total_shareholder_accounts: int | None         # registered_us only
    investor_count: int | None                     # private_us only

    # Tenant overlay (populated if fund imported to org universe)
    instrument_id: str | None
    screening_status: "PASS" | "FAIL" | "WATCHLIST" | None
    screening_score: float | None
    approval_status: str | None

    # Disclosure matrix — drives conditional UI rendering
    disclosure: DisclosureMatrix
```

### 4.3 DisclosureMatrix

```python
class DisclosureMatrix(BaseModel):
    has_holdings: bool          # N-PORT data available
    has_nav_history: bool       # ticker → Yahoo Finance NAV
    has_quant_metrics: bool     # pre-computed risk metrics exist
    has_private_fund_data: bool # ADV Schedule D data
    has_style_analysis: bool    # N-PORT style snapshots
    has_13f_overlay: bool       # manager files 13F-HR
    has_peer_analysis: bool     # peer group available
    holdings_source: "nport" | "13f" | None
    nav_source: "yfinance" | None
    aum_source: "nport" | "schedule_d" | "yfinance" | None
```

The disclosure matrix is computed at SQL level per-universe branch and drives every frontend rendering decision. The frontend never checks `universe === "registered_us"` to decide what to show — it checks `disclosure.has_holdings`.

---

## 5. Fund Lifecycle

```
Discovery           Catalog            Import           Screening
┌─────────┐     ┌────────────┐     ┌──────────┐     ┌───────────┐
│ Workers  │ ──> │ UNION ALL  │ ──> │ POST     │ ──> │ 3-Layer   │
│ ingest   │     │ 3 universes│     │ /import  │     │ screener  │
│ SEC/ESMA │     │ (global)   │     │ (org)    │     │           │
└─────────┘     └────────────┘     └──────────┘     └─────┬─────┘
                                                          |
                                                          v
                  Approval          DD Report         Analysis
                ┌───────────┐     ┌──────────────┐   ┌───────────┐
                │ Universe   │ <── │ 8-Chapter    │ <─│ Fund      │
                │ Approval   │     │ DD Report    │   │ Analyzer  │
                │ Workflow   │     │ Engine       │   │ + Quant   │
                └───────────┘     └──────────────┘   └───────────┘
```

### 5.1 Discovery (Background Workers → Global Tables)

| Worker | Lock ID | Frequency | Output |
|--------|---------|-----------|--------|
| `sec_adv_ingestion` | 900_022 | Monthly | sec_managers, sec_manager_funds, sec_manager_team, sec_manager_brochure_text |
| `nport_fund_discovery` | 900_024 | Weekly | sec_registered_funds, sec_fund_classes |
| `nport_ingestion` | 900_009 | Weekly | sec_nport_holdings (hypertable) |
| `sec_13f_ingestion` | 900_021 | Weekly | sec_13f_holdings, sec_13f_diffs (hypertables) |
| `esma_ingestion` | — | Weekly | esma_funds, esma_managers |

All discovery tables are **global** (no `organization_id`, no RLS). They represent the public regulatory universe.

### 5.2 Catalog Browsing

- `GET /screener/catalog` → executes `build_catalog_query()` with filters
- `GET /screener/catalog/facets` → aggregation counts by universe, region, fund_type, domicile
- Filters: `q` (text search), `fund_universe`, `region`, `fund_type`, `aum_min`, `domicile`, `has_nav`
- Server-side pagination with `page` / `page_size`

### 5.3 Import to Universe

Two import endpoints create an `Instrument` record in the tenant-scoped `instruments_universe`:

- `POST /screener/import-sec/{ticker}` — resolves ticker → CIK, creates Instrument with `attributes.sec_cik`, `attributes.sec_crd`, `attributes.universe = "registered_us"`
- `POST /screener/import-esma/{isin}` — resolves ISIN, creates Instrument with `attributes.esma_id`, `attributes.universe = "ucits_eu"`

The Instrument is created with `approval_status = "pending"` and becomes visible only to the importing organization (RLS enforced).

### 5.4 Screening (3-Layer Deterministic)

`POST /screener/run` triggers `ScreenerService` for an imported instrument:

| Layer | Name | Logic |
|-------|------|-------|
| L1 | Eliminatory | Hard criteria per instrument type (minimum AUM, inception age, liquidity) |
| L2 | Mandate Fit | Allocation block constraints (geography, asset class, concentration limits) |
| L3 | Quant Scoring | Percentile rank within peer group (CVaR, Sharpe, momentum, drawdown) |

Output: `ScreeningResult` with `overall_status` (PASS / FAIL / WATCHLIST), `score`, `failed_at_layer`.

### 5.5 DD Report (8-Chapter Analysis)

`POST /dd-reports/funds/{instrument_id}` triggers `DDReportEngine.generate()`:

| Chapter | Content | Evidence Source |
|---------|---------|----------------|
| 1. Executive Summary | High-level thesis | All chapters |
| 2. Investment Strategy | Strategy classification, factor exposure | ADV brochure vectors, N-PORT style |
| 3. Manager Assessment | Team, track record, operational capacity | ADV brochure, sec_manager_team |
| 4. Performance Analysis | Returns, attribution, benchmark comparison | nav_timeseries, fund_risk_metrics |
| 5. Risk Framework | CVaR, tail risk, regime sensitivity | quant_engine pre-computed metrics |
| 6. Fee Analysis | Fee drag, expense ratio, TER comparison | N-PORT expense data, peer group |
| 7. Operational DD | Custody, audit, compliance infrastructure | ADV Part 2A brochure sections |
| 8. Recommendation | Final verdict with confidence score | Synthesized from chapters 1-7 |

Chapters 1-7 run in parallel; chapter 8 runs sequentially (depends on all 7). Evidence retrieved from `wealth_vector_chunks` via pgvector similarity search.

### 5.6 Universe Approval

- `POST /universe/funds/{instrument_id}/approve` — submits fund for approval
- Self-approval prevented: `decided_by != created_by`
- Decisions: approved / rejected / watchlist
- Audit trail via `write_audit_event()` (immutable JSONB snapshots)
- Once approved: fund appears in `GET /universe` portfolio-eligible list

---

## 6. Instrument Model

The `instruments_universe` table is the tenant-scoped polymorphic core:

```python
class Instrument(OrganizationScopedMixin, Base):
    __tablename__ = "instruments_universe"

    instrument_id: UUID        # PK
    instrument_type: str       # "fund" | "bond" | "equity"
    name: str
    isin: str | None
    ticker: str | None
    bloomberg_ticker: str | None
    asset_class: str
    geography: str
    currency: str              # default "USD"
    block_id: str | None       # FK → allocation_blocks
    is_active: bool
    approval_status: str       # "pending" | "approved" | "rejected"
    attributes: dict           # type-specific JSONB (see below)
```

### 6.1 Fund-Specific Attributes (JSONB)

For `instrument_type = "fund"`, the `attributes` column contains:

| Key | Type | Description |
|-----|------|-------------|
| `universe` | string | "registered_us" / "private_us" / "ucits_eu" |
| `sec_cik` | string | Fund-level CIK (registered_us) |
| `sec_crd` | string | Adviser CRD number |
| `external_id` | string | CIK (registered) / ISIN (UCITS) / null (private) |
| `adv_fund_name` | string | Fund name from ADV Schedule D (private_us) |
| `adv_crd` | string | Manager CRD (private_us) |
| `esma_id` | string | ESMA manager ID (ucits_eu) |
| `holdings_source` | string | "nport" / "13f" / null |
| `fund_type` | string | mutual_fund, etf, hedge, pe, vc, ucits, etc. |

### 6.2 Downstream Tables (Organization-Scoped)

| Table | Relationship | Hypertable | Segmentby |
|-------|-------------|------------|-----------|
| `nav_timeseries` | FK instrument_id | 1-month chunks | organization_id |
| `fund_risk_metrics` | FK instrument_id | 1-month chunks | organization_id |
| `portfolio_snapshots` | FK portfolio_id | 1-month chunks | organization_id |
| `screening_results` | FK instrument_id | No | — |
| `dd_reports` | FK instrument_id | No | — |
| `universe_approvals` | FK instrument_id | No | — |

---

## 7. Identifier Architecture

### 7.1 CIK (Central Index Key)

The SEC assigns CIK numbers at two levels:

- **Adviser-level CIK:** The investment company (e.g., BlackRock). Used for 13F-HR filings. Stored in `sec_managers.cik`.
- **Fund-level CIK:** Each registered fund has its own CIK for N-PORT filings. Stored in `sec_registered_funds.cik` and `instruments_universe.attributes.sec_cik`.

These are different CIK values. An adviser CIK maps to many fund CIKs. The `crd_number` (CRD = Central Registration Depository) links between them via `sec_registered_funds.crd_number → sec_managers.crd_number`.

### 7.2 Cross-Entity Lookups

```
Ticker → sec_fund_classes.ticker → (cik, series_id, class_id)
       → sec_registered_funds.ticker → cik
CIK    → sec_registered_funds → crd_number → sec_managers
CRD    → sec_managers → cik (adviser-level) → sec_13f_holdings
       → sec_managers → sec_manager_funds (private funds)
       → sec_managers → sec_manager_team (team bios)
       → sec_managers → sec_manager_brochure_text (ADV Part 2A)
ISIN   → esma_funds → esma_manager_id → esma_managers
```

### 7.3 Instrument ↔ Global Data Bridge

When an instrument is imported, `attributes.sec_cik` and `attributes.sec_crd` enable joining to global SEC tables without violating RLS:

```sql
-- Fund holdings (N-PORT)
SELECT * FROM sec_nport_holdings WHERE cik = :sec_cik

-- Manager brochure (ADV)
SELECT * FROM sec_manager_brochure_text WHERE crd_number = :sec_crd

-- Institutional holders (13F reverse lookup)
SELECT * FROM sec_13f_holdings WHERE cik = :adviser_cik

-- Style snapshots
SELECT * FROM sec_fund_style_snapshots WHERE cik = :sec_cik
```

---

## 8. Vector Embedding Layer

`wealth_vector_chunks` stores fund-centric embeddings for RAG retrieval in DD reports:

```python
entity_type: str    # "firm" | "fund" | "macro"
entity_id: str      # CRD (firm) | instrument_id (fund) | key (macro)
source_type: str    # "adv_brochure" | "nport" | "esma_disclosure" | "dd_chapter"
chunk_text: str
embedding: vector(3072)  # text-embedding-3-large
organization_id: UUID | None  # NULL for global SEC/ESMA data
```

**Entity hierarchy for vector search:**

1. **Firm (RIA) → all managed funds:** Query by `entity_type='firm' AND entity_id=:crd` retrieves all brochure chunks for the management company.
2. **Fund → specific instrument:** Query by `entity_type='fund' AND entity_id=:instrument_id` retrieves fund-specific DD chapters and analysis.
3. **Macro → market context:** Query by `entity_type='macro'` retrieves macro review content (weekly committee reports).

Vector search always includes `WHERE organization_id = :org_id OR organization_id IS NULL` to merge tenant-specific and global context.

---

## 9. Pre-Computed Metrics Pipeline

### 9.1 NAV Ingestion

`instrument_ingestion` worker (daily, lock 900_010):
1. Queries active instruments with tickers from `instruments_universe`
2. Fetches daily NAV from Yahoo Finance (or pluggable provider)
3. Upserts into `nav_timeseries` (hypertable, 1-month chunks)
4. Computes `return_1d` as `(nav / lag(nav)) - 1`

### 9.2 Risk Computation

`risk_calc` worker (daily, lock 900_007):
1. Reads `nav_timeseries` returns for each active instrument
2. Computes: CVaR (1m/3m/6m/1y at 95%), Sharpe, Sortino, max drawdown
3. Computes momentum: RSI-14, Bollinger band position, OBV flow score, blended momentum
4. Upserts into `fund_risk_metrics` (hypertable, 1-month chunks)
5. Scoring routes read pre-computed values — zero in-request computation

### 9.3 Style Classification

`nport_ingestion` worker (weekly, lock 900_009):
1. Parses N-PORT XML holdings (equity %, fixed income %, cash %)
2. Computes sector weights from CUSIP → SIC mapping
3. Classifies style (growth/value/blend) via growth_tilt metric
4. Upserts into `sec_fund_style_snapshots` (quarterly)

---

## 10. Frontend Tree View

The fund catalog frontend (`CatalogTable.svelte`) groups the flat item array by `external_id`:

```typescript
interface FundGroup {
    fund_key: string;              // external_id (CIK | UUID | ISIN)
    representative: UnifiedFundItem;
    classes: UnifiedFundItem[];
    has_classes: boolean;          // registered_us && classes.length > 1 && class_id != null
}
```

**Rendering rules:**

| Condition | Behavior |
|-----------|----------|
| `has_classes = true` | Parent row with chevron + "N classes" badge. Click expands child rows. |
| `has_classes = false` | Flat row (single fund). Click opens detail panel. |
| Child class row | Shows class_name, ticker, disclosure dots, checkbox for DD Review selection. |
| Selected classes | "Send N classes to DD Review" button appears in header. |

The tree is client-side only — the backend always returns a flat array (one row per class). Pagination operates on the flat array; grouping is a frontend presentation concern.

---

## 11. Global vs Tenant-Scoped Tables

### Global Tables (no organization_id, no RLS)

| Table | PK | Source |
|-------|-----|--------|
| sec_managers | crd_number | ADV bulk CSV |
| sec_manager_funds | id (UUID) | ADV Schedule D |
| sec_manager_team | id (UUID) | ADV Part 2A/2B |
| sec_manager_brochure_text | (crd_number, section, filing_date) | ADV Part 2A |
| sec_registered_funds | cik | N-PORT discovery |
| sec_fund_classes | (cik, series_id, class_id) | N-PORT header |
| sec_fund_style_snapshots | (cik, report_date) | N-PORT computed |
| sec_nport_holdings | (cik, report_date, cusip) | N-PORT XML |
| sec_13f_holdings | (cik, report_date, cusip) | 13F-HR |
| sec_13f_diffs | (cik, report_date, cusip) | 13F computed |
| sec_cusip_ticker_map | cusip | SEC EDGAR |
| esma_funds | isin | ESMA Register |
| esma_managers | esma_id | ESMA Register |
| macro_data | (series_id, observation_date) | FRED API |
| treasury_data | (series_id, observation_date) | US Treasury |
| benchmark_nav | (symbol, nav_date) | Yahoo Finance |

### Tenant-Scoped Tables (organization_id + RLS)

| Table | PK | Lifecycle stage |
|-------|-----|----------------|
| instruments_universe | instrument_id | Import |
| nav_timeseries | (instrument_id, nav_date) | Post-import |
| fund_risk_metrics | (instrument_id, calc_date) | Post-import |
| screening_results | id | Screening |
| dd_reports | id | Analysis |
| dd_chapters | id | Analysis |
| universe_approvals | id | Approval |
| portfolio_snapshots | (portfolio_id, snapshot_date) | Portfolio |
| wealth_vector_chunks | id | Embedding |

---

## 12. Key Files

| Area | Path |
|------|------|
| Catalog query builder | `backend/app/domains/wealth/queries/catalog_sql.py` |
| Catalog schemas | `backend/app/domains/wealth/schemas/catalog.py` |
| Instrument ORM | `backend/app/domains/wealth/models/instrument.py` |
| Screener routes | `backend/app/domains/wealth/routes/screener.py` |
| Universe routes | `backend/app/domains/wealth/routes/universe.py` |
| DD Report routes | `backend/app/domains/wealth/routes/dd_reports.py` |
| Fund analyzer | `backend/vertical_engines/wealth/fund_analyzer.py` |
| DD Report engine | `backend/vertical_engines/wealth/dd_report/` |
| Screener engine | `backend/vertical_engines/wealth/screener/` |
| Quant analyzer | `backend/vertical_engines/wealth/quant_analyzer.py` |
| ADV data provider | `backend/data_providers/sec/adv_service.py` |
| 13F data provider | `backend/data_providers/sec/thirteenf_service.py` |
| N-PORT data provider | `backend/data_providers/sec/nport_service.py` |
| ADV ingestion worker | `backend/app/domains/wealth/workers/sec_adv_ingestion.py` |
| Fund discovery worker | `backend/app/domains/wealth/workers/nport_fund_discovery.py` |
| NAV ingestion worker | `backend/app/domains/wealth/workers/instrument_ingestion.py` |
| Risk calc worker | `backend/app/domains/wealth/workers/risk_calc.py` |
| Vector chunks model | `backend/app/domains/wealth/models/wealth_vector_chunk.py` |
| Frontend catalog table | `frontends/wealth/src/lib/components/screener/CatalogTable.svelte` |
| Frontend catalog types | `frontends/wealth/src/lib/types/catalog.ts` |
