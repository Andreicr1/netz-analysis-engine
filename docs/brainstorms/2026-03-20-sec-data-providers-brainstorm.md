---
date: 2026-03-20
topic: sec-data-providers-layer
---

# SEC Data Providers Layer — Replicating eVestment with Public SEC Data

## What We're Building

A new `backend/data_providers/` layer that fetches, normalizes, and persists public SEC filing data (Form ADV, 13F-HR, IAPD) as structured data available to both Credit and Wealth verticals. This replaces the need for paid data providers like eVestment for US Investment Manager intelligence.

The layer provides three capabilities:

1. **Manager catalog** (Form ADV / IAPD API) — firm-level registration, AUM, fee structure, compliance history, private funds managed, team bios and backgrounds
2. **Portfolio holdings** (13F-HR) — quarterly holdings snapshots for institutional managers (>$100M AUM), quarter-over-quarter diffs for style drift and concentration analysis
3. **Institutional ownership** (13F reverse lookup) — which endowments, pensions, and foundations invest in which managers, as evidence of institutional pedigree

All data is public, free, and API-accessible. The eVestment value proposition is curation and UI — the data source is identical.

## Why This Approach

### Approaches considered

**Approach A — New services in `quant_engine/`:** Consistent with where FRED, OFR, Treasury services live today. Rejected because IAPD/ADV is registration data (catalog), not quantitative computation. `quant_engine/` would accumulate semantically misplaced code.

**Approach B — New `data_providers/` top-level layer (chosen):** Dedicated layer for external data ingestion with provider abstraction. Eliminates CIK resolver duplication between `credit/edgar/` and new code. Clean import graph. Accommodates future non-SEC providers (FCA, ESMA, CVM) without restructuring.

**Approach C — Expand `vertical_engines/credit/edgar/`:** Violates import-linter (verticals cannot cross-import). 13F/ADV are not credit-specific. Discarded.

### Why B wins

- The `credit/edgar/` package already proved that SEC data fetching is infrastructure, not vertical logic — CIK resolution, rate limiting, edgartools setup are shared concerns
- The Wealth DD Report optimization plan (`wm-ddreport-optimization-2026-03-20.md`) explicitly anticipates "future providers" of structured data — `data_providers/` is exactly where they live
- Import-linter prevents sharing via verticals; `quant_engine/` is semantically wrong; a new top-level package is the correct architectural answer

## Key Decisions

### M1 includes full credit/edgar refactor (no tech debt)

The refactor of `vertical_engines/credit/edgar/` to consume `data_providers/sec/shared` is **not phased** — it ships in M1 alongside the new layer. Zero tolerance for two CIK resolvers coexisting. M1 ends with a single point of truth for all SEC infrastructure. M2 only begins with this guaranteed.

### Global tables, no RLS

All new PostgreSQL tables are global (no `organization_id`, no RLS). SEC filings are public data shared across all tenants. Consistent with existing pattern: `macro_data`, `benchmark_nav`, `allocation_blocks`, `macro_regional_snapshots`.

### models.py monolithic for now, split if it grows

A single `data_providers/sec/models.py` holds all frozen dataclasses. 13F and institutional services share types (an endowment is a subset of 13F filer). If dataclasses begin to overlap or the file exceeds ~300 lines, split into `models/thirteenf.py`, `models/adv.py`, etc. This is a conscious decision, not oversight — documented here for future reference.

### Provider abstraction in the design, SEC-only in M1

The `data_providers/` namespace accommodates future regulators (FCA UK, ESMA, CVM Brazil). M1 implements only `data_providers/sec/`. The abstraction is structural (directory layout, import graph) not premature (no abstract base classes or interfaces until a second provider exists).

### Blob index tier eliminated from CIK resolver

The current `cik_resolver.py` has a 4-tier cascade: (1) edgartools ticker, (2) edgartools fuzzy name, (3) blob index from StorageClient, (4) EFTS full-text search. The blob index (Tier 3) is **removed** in the migration to `shared.py`. The new resolver has 3 tiers: ticker -> fuzzy -> EFTS.

**Rationale:** The blob index resolves names against a static snapshot of the SEC entity index. Tier 2 (edgartools fuzzy) does the same thing with live SEC data. If Tier 2 fails on a name, it means the SEC doesn't have that entity — the blob index "succeeding" in that case is a false positive from stale data. False confidence is worse than not resolving.

Tier 4 (EFTS) is genuinely different: it searches filing content, not just the entity index. This covers cases Tier 2 misses for structural reasons (entity named differently in filings vs. index), not data staleness. The blob index has no such differentiation — it is a strictly inferior version of Tier 2.

Eliminating the blob index also removes the `app.services.blob_storage` dependency from `shared.py`, keeping it standalone (no `app.*`, no `StorageClient` injection). No DI pattern needed. If an edge case surfaces in production where EFTS also misses, it means the entity genuinely does not exist in SEC — which is the correct answer.

### Frontend in separate sprints

The data layer (M1-M2) and the frontend consumption (dashboards, peer comparison, style analysis, attribution interactivity) are separate sprint scopes. The brainstorm covers the data layer. Frontend sprints consume the tables and API endpoints built here.

## Architecture

### Package structure

```
backend/data_providers/
  __init__.py
  sec/
    __init__.py
    shared.py               -- CIK resolver (migrated from credit/edgar/cik_resolver.py),
                                SEC rate limiter (distributed Redis-based, migrated from credit/edgar/service.py),
                                edgartools helpers, User-Agent config
    adv_service.py           -- Form ADV + IAPD API: manager registration, AUM, fee structure,
                                compliance, Schedule D private funds, Part 2A team bios
    thirteenf_service.py     -- 13F-HR via edgartools: quarterly holdings, sector/geography
                                aggregation, quarter-over-quarter diff computation
    institutional_service.py -- 13F reverse: endowment/pension/foundation filings,
                                manager exposure from institutional portfolios
    models.py                -- Frozen dataclasses for all SEC data types
```

### credit/edgar refactor (M1)

```
vertical_engines/credit/edgar/
  cik_resolver.py       -- DELETE (migrated to data_providers.sec.shared)
  service.py            -- refactored: imports resolve_cik, rate_check from data_providers.sec.shared
  financials.py         -- unchanged (credit-specific XBRL extraction)
  going_concern.py      -- unchanged (credit-specific 10-K text analysis)
  insider_signals.py    -- unchanged (credit-specific Form 4 analysis)
  entity_extraction.py  -- unchanged (credit-specific deal entity logic)
  context_serializer.py -- unchanged (credit-specific LLM context building)
  models.py             -- unchanged (CikResolution dataclass stays or re-exports from shared)
```

The credit/edgar/ package retains all credit-specific analysis logic. Only the infrastructure (CIK resolution, rate limiting) moves to data_providers/sec/shared.

### New PostgreSQL tables (all global, no org_id)

```sql
-- Manager catalog from Form ADV / IAPD
sec_managers (
    crd_number TEXT PRIMARY KEY,     -- CRD = Central Registration Depository (unique per adviser)
    cik TEXT,                        -- SEC CIK (nullable, not all advisers have EDGAR filings)
    firm_name TEXT NOT NULL,
    sec_number TEXT,                 -- SEC file number (801-XXXXX)
    registration_status TEXT,        -- REGISTERED, EXEMPT, WITHDRAWN
    aum_total BIGINT,               -- total regulatory AUM (USD)
    aum_discretionary BIGINT,
    aum_non_discretionary BIGINT,
    total_accounts INTEGER,
    fee_types JSONB,                 -- {percentage_of_aum, hourly, fixed, performance}
    client_types JSONB,              -- {individuals, hnw, pension, endowment, corporation, ...}
    state TEXT,
    country TEXT,
    website TEXT,
    compliance_disclosures INTEGER,  -- count of disciplinary disclosures
    last_adv_filed_at DATE,
    data_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- Private funds managed by each adviser (ADV Schedule D)
sec_manager_funds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crd_number TEXT NOT NULL REFERENCES sec_managers(crd_number),
    fund_name TEXT NOT NULL,
    fund_id TEXT,                    -- SEC private fund ID if available
    gross_asset_value BIGINT,       -- fund GAV (USD)
    fund_type TEXT,                  -- hedge_fund, pe, vc, real_estate, other
    is_fund_of_funds BOOLEAN,
    investor_count INTEGER,
    data_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- Key personnel from ADV Part 2A brochure
sec_manager_team (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    crd_number TEXT NOT NULL REFERENCES sec_managers(crd_number),
    person_name TEXT NOT NULL,
    title TEXT,
    role TEXT,                       -- portfolio_manager, cio, ceo, coo, compliance, analyst
    education JSONB,                 -- [{institution, degree, year}]
    certifications TEXT[],           -- CFA, CAIA, etc.
    years_experience INTEGER,
    bio_summary TEXT,                -- extracted from Part 2A
    data_fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- 13F quarterly holdings snapshots
sec_13f_holdings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cik TEXT NOT NULL,               -- filer CIK (manager or institution)
    report_date DATE NOT NULL,       -- quarter end date
    filing_date DATE NOT NULL,       -- actual filing date
    accession_number TEXT NOT NULL,
    cusip TEXT NOT NULL,
    issuer_name TEXT NOT NULL,
    asset_class TEXT,                -- equity, option, convertible, other
    shares BIGINT,
    market_value BIGINT,             -- USD (as reported, in thousands * 1000)
    discretion TEXT,                 -- SOLE, SHARED, NONE
    voting_sole BIGINT,
    voting_shared BIGINT,
    voting_none BIGINT,
    UNIQUE (cik, report_date, cusip)
)
-- Explicit indexes for frequent access patterns:
-- idx_sec_13f_holdings_cik_report_date ON sec_13f_holdings (cik, report_date)
--   Covers: holdings by manager per period, diff computation, time-range aggregation
-- idx_sec_13f_holdings_cusip ON sec_13f_holdings (cusip)
--   Covers: reverse lookup (who holds this security), institutional ownership queries

-- Quarter-over-quarter diffs (materialized from sec_13f_holdings)
sec_13f_diffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cik TEXT NOT NULL,
    cusip TEXT NOT NULL,
    issuer_name TEXT NOT NULL,
    quarter_from DATE NOT NULL,
    quarter_to DATE NOT NULL,
    shares_before BIGINT,
    shares_after BIGINT,
    shares_delta BIGINT,             -- positive = bought, negative = sold
    value_before BIGINT,
    value_after BIGINT,
    action TEXT,                     -- NEW_POSITION, INCREASED, DECREASED, EXITED, UNCHANGED
    weight_before FLOAT,             -- % of portfolio (value / total)
    weight_after FLOAT
)

-- Institutional investor allocations (13F reverse lookup)
sec_institutional_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filer_cik TEXT NOT NULL,          -- endowment/pension CIK
    filer_name TEXT NOT NULL,
    filer_type TEXT,                  -- endowment, pension, foundation, sovereign, insurance
    report_date DATE NOT NULL,
    target_cusip TEXT NOT NULL,       -- what they hold
    target_issuer TEXT NOT NULL,
    market_value BIGINT,
    shares BIGINT,
    UNIQUE (filer_cik, report_date, target_cusip)
)
```

### Import graph

```
data_providers.sec.shared       -- standalone: no app.*, no vertical_engines.*, no quant_engine.*
                                   only stdlib + httpx + edgartools + structlog + redis
data_providers.sec.*_service    -- imports data_providers.sec.shared + data_providers.sec.models
                                   may import httpx, edgartools

vertical_engines.credit.edgar.* -- imports data_providers.sec.shared (CIK, rate limit)
                                   does NOT import data_providers.sec.*_service (no 13F/ADV dependency)
vertical_engines.wealth.*       -- imports data_providers.sec.*_service (for DD report, manager spotlight)
quant_engine.*                  -- imports data_providers.sec.* (for holdings analytics, attribution)
app.domains.*                   -- imports data_providers.sec.* (for API routes serving the data)
```

### import-linter changes required (M1)

```toml
# pyproject.toml additions:

[tool.importlinter]
root_packages = ["vertical_engines", "quant_engine", "app", "data_providers"]
#                                                          ^^^^^^^^^^^^^^^^
#                                                          NEW: add to root

# NEW CONTRACT: data_providers must not import vertical engines or app domains
[[tool.importlinter.contracts]]
name = "Data providers must not import verticals or app"
type = "forbidden"
source_modules = ["data_providers"]
forbidden_modules = ["vertical_engines", "app.domains"]

# EXISTING CONTRACT UPDATE: quant_engine forbidden list stays as-is.
# quant_engine already cannot import app.domains.wealth or app.domains.credit.
# quant_engine -> data_providers is a NEW allowed edge (not forbidden by any existing contract).
# No contract change needed — just awareness that the edge exists.
```

## Data Sources — API Details

### IAPD API (Form ADV)

```
Base: https://api.adviserinfo.sec.gov (SEC IAPD public API, no auth)
Fallback: https://www.sec.gov/cgi-bin/browse-ia (EDGAR IAPD HTML search)

Endpoints:
  GET /search/firm?query={name}        -- search by firm name
  GET /search/firm?crd={number}        -- lookup by CRD number
  GET /search/firm/summary/{crd}       -- registration, AUM, client types
  GET /search/firm/brochures/{crd}     -- Part 2A brochures (PDF URLs)
  GET /search/firm/schedule-d/{crd}    -- private funds list

Rate limit: undocumented, conservative 2 req/s recommended
Auth: none (public disclosure)
```

### 13F-HR (via edgartools)

```python
# edgartools already installed and used by credit/edgar/
from edgar import Company

company = Company(cik_or_ticker)
filings_13f = company.get_filings(form="13F-HR")
latest = filings_13f.latest()
holdings = latest.obj()  # parsed ThirteenF object with .holdings DataFrame

# Holdings DataFrame columns:
# cusip, name, title, value (thousands), shares, discretion,
# voting_sole, voting_shared, voting_none
```

### EDGAR Full-Text Search (for institutional filer discovery)

```
Base: https://efts.sec.gov/LATEST/search-index
Params: forms=13F-HR&q="endowment" OR "pension" OR "foundation"

Used to discover institutional filers (endowments, pensions) by keyword,
then fetch their 13F holdings to build the reverse allocation map.
```

## Consumption Points

### Credit vertical (existing + enhanced)

| Consumer | Current data | Enhanced with data_providers |
|---|---|---|
| Deep review Stage 10 (sponsor analysis) | `credit/edgar/service.py` — 10-K financials, going concern, insider signals | + Form ADV data: manager AUM history, compliance disclosures, team stability. Richer sponsor evidence = higher RetrievalSignal confidence. |
| IC Memo ch04 (Sponsor & Management) | Sponsor profile from LLM analysis of deal docs | + ADV team bios, years of experience, certifications. Structured data supplements documentary evidence. |
| IC Memo ch12 (Peer Comparison) | Currently thin — no peer data source | + 13F holdings of comparable managers for portfolio composition comparison. |

### Wealth vertical (new consumers)

| Consumer | Current data | Enhanced with data_providers |
|---|---|---|
| DD Report ch03 (Fund Manager Assessment) | "manager data from API" (placeholder per wm-ddreport optimization) | Form ADV: AUM, fee structure, compliance history, team bios. Direct structured data, no hedging. |
| DD Report ch02 (Investment Strategy) | Fund classification from YFinance | + 13F holdings for strategy verification (equity style, sector concentration, position sizing) |
| Manager Spotlight engine | Limited to YFinance metadata | + Full ADV profile + 13F portfolio history + institutional investor base |
| Screener Layer 2 (Mandate Fit) | Only instrument-level attributes | + Manager-level attributes (AUM, compliance, team size) as screening criteria |
| Style drift detection | DTW on NAV returns (behavioral proxy) | + 13F quarter-over-quarter diffs = actual holdings drift (sector rotation, concentration changes) |
| Peer group matching | Fund-level metrics only | + Manager-level peer grouping by AUM, strategy, client type from ADV |
| Exposure monitor | Portfolio-level only | + Look-through to 13F holdings for geographic/sector exposure |

### Quant engine (analytics)

| Consumer | Usage |
|---|---|
| `attribution_service.py` | 13F holdings enable Brinson-Fachler at the manager level (not just portfolio) |
| `correlation_regime_service.py` | Cross-manager holdings overlap = contagion risk signal |
| Future: concentration analytics | 13F data enables HHI, top-10 concentration, sector tilt metrics per manager |

## Milestone Sequencing

### M1 — Data layer + credit/edgar refactor

| Phase | Scope |
|---|---|
| 1.1 | Create `data_providers/sec/shared.py`: migrate CIK resolver + rate limiter from `credit/edgar/`. Add comprehensive tests. |
| 1.2 | Refactor `credit/edgar/service.py` + `credit/edgar/cik_resolver.py`: delete cik_resolver.py, import from `data_providers.sec.shared`. All existing EDGAR tests must pass unchanged. |
| 1.3 | Update `pyproject.toml`: add `data_providers` to import-linter root_packages, add forbidden contract (data_providers must not import verticals/app). Run `make architecture` to verify. |
| 1.4 | Create `data_providers/sec/models.py`: frozen dataclasses for ADV manager, fund, team, 13F holding, 13F diff, institutional allocation. |
| 1.5 | Create `data_providers/sec/adv_service.py`: IAPD API client. Fetch manager registration, AUM, fee structure, Schedule D funds, Part 2A team extraction. |
| 1.6 | Create `data_providers/sec/thirteenf_service.py`: 13F-HR parsing via edgartools. Holdings snapshot extraction, quarter-over-quarter diff computation, sector/geography aggregation. |
| 1.7 | Create `data_providers/sec/institutional_service.py`: Institutional filer discovery (endowments, pensions via EFTS keyword search), 13F holdings fetch, reverse allocation mapping. |
| 1.8 | Alembic migration: 6 new global tables (sec_managers, sec_manager_funds, sec_manager_team, sec_13f_holdings, sec_13f_diffs, sec_institutional_allocations). |
| 1.9 | Tests: unit tests for each service (mocked HTTP), integration tests for CIK resolver migration (must match existing behavior), import-linter green. |

**M1 exit criteria:** `make check` green. Single CIK resolver in `data_providers.sec.shared`. All existing credit/edgar tests pass. New services fetch and persist to new tables. Import-linter enforces data_providers isolation.

### M2 — Vertical engine integration

| Phase | Scope |
|---|---|
| 2.1 | Credit deep_review: inject ADV manager data into Stage 10 (sponsor analysis) evidence pack. Enrich ch04_sponsor prompt context with structured ADV data. |
| 2.2 | Wealth DD report: wire ADV + 13F data into evidence_pack.py for ch02 (strategy), ch03 (manager), ch07 (operational). Update source-aware prompts per wm-ddreport optimization plan. |
| 2.3 | Wealth manager_spotlight: consume full ADV profile + 13F history + institutional ownership. |
| 2.4 | Wealth screener: add manager-level attributes (AUM, compliance, team size) to Layer 2 mandate fit criteria. |
| 2.5 | Background workers: create ingestion workers for ADV refresh (weekly), 13F update (quarterly, 45 days after quarter-end), institutional scan (quarterly). |

### M3 — Analytics + frontend (separate sprint scope)

| Phase | Scope |
|---|---|
| 3.1 | Quant engine: 13F-based attribution, cross-manager overlap analysis, concentration metrics (HHI, top-10, sector tilt). |
| 3.2 | Style drift: 13F quarter-over-quarter diffs as input to drift detection alongside DTW returns-based drift. |
| 3.3 | API endpoints: REST routes for manager search, holdings history, institutional ownership, peer comparison data. |
| 3.4 | Frontend — Credit: enhanced sponsor section in deal detail with ADV data cards, team table, compliance badges. |
| 3.5 | Frontend — Wealth: manager intelligence pages (manager profile, holdings timeline, institutional investors, peer comparison tables, style analysis charts). |

## Open Questions

- **IAPD API stability:** The SEC IAPD API is not officially documented as a public API. If it becomes unreliable, fallback is direct Form ADV EDGAR filings parsing (more complex but fully within SEC EDGAR infrastructure). Monitor reliability in M1.
- **13F coverage for private credit:** 13F only covers Section 13(f) securities (mostly public equities). Private credit positions are NOT in 13F. For credit vertical, 13F adds peer comparison data but not direct portfolio data. The primary credit data source remains 10-K/Form 4/Form D.
- **Part 2A parsing:** ADV brochures are PDF documents. Team bio extraction may require Mistral OCR or structured text parsing. Evaluate in M1 whether IAPD API provides structured team data or if PDF parsing is needed.
- **Historical depth:** 13F filings are available on EDGAR going back to 1999. For M1, fetch 8 quarters (2 years) as default lookback. Configurable parameter.

## Next Steps

This brainstorm is ready for `/ce:plan` to produce the implementation plan for M1 (data layer + credit/edgar refactor). M2 and M3 will be planned separately after M1 is validated.

## Related Documents

- `docs/reference/deep-review-optimization-plan-2026-03-20.md` — Credit deep_review signal-aware optimization (consumes EDGAR data)
- `docs/reference/wm-ddreport-optimization-2026-03-20.md` — Wealth DD report source-aware optimization (anticipates new structured data providers)
- `docs/reference/prompt-retrieval-confidence-signals.md` — RetrievalSignal spec (confidence framework that benefits from richer evidence)
- `docs/plans/2026-03-15-feat-edgar-upgrade-edgartools-plan.md` — Original edgartools migration plan
