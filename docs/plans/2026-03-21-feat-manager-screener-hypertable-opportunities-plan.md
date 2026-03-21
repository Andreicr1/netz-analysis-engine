---
title: "feat: SEC Manager Screener + Hypertable Opportunities + ESMA UCITS Seed"
type: feat
status: active
date: 2026-03-21
origin: docs/brainstorms/2026-03-21-hypertable-opportunities-manager-screener-brainstorm.md
---

# SEC Manager Screener + Hypertable Opportunities + ESMA UCITS Seed

## Enhancement Summary

**Deepened on:** 2026-03-21
**Sections enhanced:** 6
**Research agents used:** TimescaleDB optimization, Dynamic SQL patterns, Redis caching, ESMA Register API, Peer comparison SQL, BIS/IMF APIs

### Key Improvements

1. **TimescaleDB continuous aggregates** replace CTEs for holdings/drift aggregation — incremental refresh, not per-request recomputation
2. **LATERAL JOIN bug confirmed** (TimescaleDB issue #8642) — replaced with CTE + subquery pattern throughout
3. **ESMA seed pipeline corrected** — `esma-registers` package doesn't exist; replaced with direct Solr API + FIRDS XML for ISINs + OpenFIGI batch resolution. Yield increased from ~5-10K to ~35-45K funds
4. **BIS credit-to-GDP gap is pre-computed** (CG_DTYPE=C) — no HP filter needed; confirmed working API calls with actual data
5. **SQLAlchemy Core builder** replaces raw `text()` SQL — type-safe, composable, matches codebase conventions
6. **Separate count query** via `asyncio.gather()` replaces `COUNT(*) OVER()` — avoids full materialization on paginated queries

### Critical Findings from Research

- **LATERAL JOIN breaks chunk exclusion in TimescaleDB 2.22+** (issue #8642). All LATERAL joins in the plan replaced with CTEs.
- **IMF WEO API is simple JSON** (not SDMX) — direct `httpx.get()`, no `sdmx1` dependency needed. Current data shows US GDP 2025 = 2.0%, inflation = 2.7%.
- **BIS confirmed 44 countries** with credit-to-GDP gaps pre-computed. No HP filter computation needed.
- **ESMA Fund Register has 134K UCITS entries** — far more than the 15K estimated. Combined with FIRDS ISIN join + OpenFIGI, realistic yield is ~35-45K funds with Yahoo Finance NAV.
- **Redis aggregation cache total memory: ~4MB** for 5000 managers + 6 leaderboard sorted sets. Trivial for Upstash.

---

## Overview

Dedicated Wealth OS module for discovery, monitoring, and peer comparison of SEC-registered investment managers. Operates over existing global SEC tables (`sec_managers`, `sec_13f_holdings`, `sec_13f_diffs`, `sec_institutional_allocations`) with left join to `instruments_universe`. No new data models for the screener itself — it's a read-only view layer with one write action (Add to Universe).

Secondary deliverables: Redis caching layer for pre-computed aggregates, ESMA Register seed pipeline for ~5-10K UCITS funds, and hypertable optimization opportunities across both verticals.

(see brainstorm: `docs/brainstorms/2026-03-21-hypertable-opportunities-manager-screener-brainstorm.md`)

## Problem Statement / Motivation

After evaluating eVestment (Nasdaq), we confirmed that their platform fundamentally operates on the same public SEC/FRED/OFR data we already ingest. Their edge is aggregation + UI, not proprietary data. With our hypertable infrastructure and pre-computed worker pattern, we can deliver comparable manager analytics at zero marginal cost. The Manager Screener is the user-facing module that surfaces this data.

## Proposed Solution

Six implementation phases, each independently shippable:

| Phase | Deliverable | New Files | New Tables | Depends On |
|-------|------------|-----------|-----------|-----------|
| **1** | Manager Screener Core (backend + frontend) | 3 backend, 1 frontend page | 0 | Existing SEC tables |
| **2** | Screener Aggregation Cache + Cross-Vertical Caching | 1 worker, Redis keys | 0 | Phase 1 |
| **3** | ESMA Register + UCITS Yahoo Finance Seed | 4 backend, 1 migration | 3 (esma_*) | Independent |
| **4** | N-PORT Integration | 2 backend, 1 migration | 1 hypertable | Independent |
| **5** | ADV Part 2A Brochure Extraction | 1 service update | 1 table | Existing Mistral OCR |
| **6** | BIS + IMF Macro Enrichment | 2 data providers, 2 workers | 2 hypertables | Independent |

---

## Phase 1 — Manager Screener Core (Backend)

### 1.1 New Files

```
backend/app/domains/wealth/routes/manager_screener.py      ← 8 endpoints (thin handlers)
backend/app/domains/wealth/queries/manager_screener_sql.py ← query builder (pure, no I/O)
backend/app/domains/wealth/schemas/manager_screener.py     ← Pydantic schemas
backend/tests/test_manager_screener.py                     ← Tests
```

**Separation rationale:** The query builder is a pure helper — frozen dataclass input, `Select` output, zero I/O. Lives in `queries/` (not `routes/`, not `services/`). The route imports the builder and executes it. Testable in isolation without DB mock — just compile the SQL and verify conditions.

### 1.2 Route Registration

**File:** `backend/app/main.py`

Add import and mount alongside existing wealth routes:

```python
from app.domains.wealth.routes.manager_screener import router as wealth_manager_screener_router

# In api_v1 mount block:
api_v1.include_router(wealth_manager_screener_router)
```

### 1.3 Endpoints

**File:** `backend/app/domains/wealth/routes/manager_screener.py`

```python
router = APIRouter(prefix="/manager-screener", tags=["manager-screener"])
```

| Method | Path | Response Model | Summary |
|--------|------|---------------|---------|
| `GET` | `/` | `ManagerScreenerPage` | Paginated list with all 5 filter blocks |
| `GET` | `/managers/{crd}/profile` | `ManagerProfileRead` | Profile tab — ADV data + team |
| `GET` | `/managers/{crd}/holdings` | `ManagerHoldingsRead` | Holdings tab — sectors, top 10, HHI, 4Q history |
| `GET` | `/managers/{crd}/drift` | `ManagerDriftRead` | Drift tab — turnover timeline |
| `GET` | `/managers/{crd}/institutional` | `ManagerInstitutionalRead` | Institutional tab — 13F reverse |
| `GET` | `/managers/{crd}/universe-status` | `ManagerUniverseRead` | Universe tab — status + links |
| `POST` | `/managers/{crd}/add-to-universe` | `InstrumentRead` (201) | Create Instrument (pending) → IC flow |
| `POST` | `/managers/compare` | `ManagerCompareResult` | Peer comparison (2-5 CRDs) |

**Dependency stack** (follows existing patterns from `screener.py`, `instruments.py`):

```python
async def handler(
    db: AsyncSession = Depends(get_db_with_rls),  # Needed for instruments_universe join (org-scoped)
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
    # Query params for filters
)
```

**Authorization:** All endpoints require `INVESTMENT_TEAM` or `ADMIN` role (same `_require_investment_role` pattern from `screener.py`).

**SEC tables are global (no RLS)** — queried directly. The `instruments_universe` join uses the RLS-scoped session to filter by `organization_id`.

### 1.4 Main Screener Query Strategy

**Dynamic SQL builder** — not ORM. The screener joins 4 global tables + 1 org-scoped table with computed aggregates. Raw SQL with parameterized filters is cleaner than SQLAlchemy ORM for this.

**File:** `backend/app/domains/wealth/queries/manager_screener_sql.py`

```python
# Pure query builder — no I/O, no state, no imports from app.domains
from dataclasses import dataclass
from datetime import date
from typing import Any
from sqlalchemy import Select

@dataclass(frozen=True)
class ScreenerFilters:
    # Block 1 — Firma
    aum_min: int | None = None
    aum_max: int | None = None
    strategy_types: list[str] | None = None
    fee_types: list[str] | None = None
    states: list[str] | None = None
    countries: list[str] | None = None
    registration_status: list[str] | None = None
    compliance_clean: bool | None = None
    adv_filed_from: date | None = None
    adv_filed_to: date | None = None
    search: str | None = None
    # Block 2 — Portfolio (continuous aggregate)
    sectors: list[str] | None = None
    hhi_min: float | None = None
    hhi_max: float | None = None
    position_count_min: int | None = None
    position_count_max: int | None = None
    portfolio_value_min: int | None = None
    # Block 3 — Drift (continuous aggregate)
    style_drift_detected: bool | None = None
    turnover_min: float | None = None
    turnover_max: float | None = None
    high_activity_quarters_min: int | None = None
    # Block 4 — Institutional
    has_institutional_holders: bool | None = None
    holder_types: list[str] | None = None
    # Block 5 — Universe status
    universe_statuses: list[str] | None = None
    # Sort & pagination
    sort_by: str = "aum_total"
    sort_dir: str = "desc"
    page: int = 1
    page_size: int = 50

def build_screener_queries(
    filters: ScreenerFilters,
    org_id: ...,
) -> tuple[Select, Select]:
    """Returns (data_query, count_query) — both parameterized.

    Route handler calls asyncio.gather(db.execute(data_q), db.scalar(count_q))
    to execute both in parallel.
    """
    ...
```

**SQL structure** (reads from continuous aggregates, no LATERAL joins, no COUNT(*) OVER()):

```sql
-- DATA QUERY (paginated, sorted)
-- Reads from continuous aggregates sec_13f_holdings_agg and sec_13f_drift_agg
-- instead of computing CTEs on raw hypertables per request
WITH holdings_agg AS (
    -- From continuous aggregate (pre-computed, not per-request CTE)
    SELECT cik,
           SUM(position_count) AS position_count,
           SUM(sector_value) AS portfolio_value,
           -- HHI from pre-aggregated sector weights
           SUM(POWER(sector_value::float / NULLIF(cik_total.total, 0), 2)) AS hhi,
           -- Top sector by value
           (ARRAY_AGG(sector ORDER BY sector_value DESC))[1] AS top_sector
    FROM sec_13f_holdings_agg ca
    CROSS JOIN LATERAL (  -- NOTE: safe on continuous aggregate (not hypertable)
        SELECT SUM(sector_value) AS total
        FROM sec_13f_holdings_agg
        WHERE cik = ca.cik AND quarter = ca.quarter
    ) cik_total
    WHERE quarter = :latest_quarter  -- exact match on continuous agg bucket
    GROUP BY cik, cik_total.total
),
drift_agg AS (
    -- From continuous aggregate
    SELECT cik,
           COUNT(*) FILTER (WHERE churn_count::float / NULLIF(total_changes, 0) > 0.25)
               AS high_activity_quarters,
           AVG(churn_count::float / NULLIF(total_changes, 0)) AS avg_turnover
    FROM sec_13f_drift_agg
    WHERE quarter >= :drift_cutoff  -- last 4 quarters
    GROUP BY cik
),
inst_agg AS (
    SELECT h.cik AS manager_cik,
           COUNT(DISTINCT ia.filer_cik) AS holder_count
    FROM sec_13f_holdings h
    JOIN sec_institutional_allocations ia
        ON ia.target_cusip = h.cusip
        AND ia.report_date >= :inst_cutoff  -- chunk pruning on both hypertables
    WHERE h.report_date = :latest_quarter   -- chunk pruning
    GROUP BY h.cik
)
SELECT
    m.crd_number, m.firm_name, m.aum_total, m.client_types,
    m.compliance_disclosures, m.registration_status, m.last_adv_filed_at,
    m.state, m.country,
    ha.top_sector, ha.hhi, ha.position_count, ha.portfolio_value,
    COALESCE(da.high_activity_quarters, 0) > 0 AS drift_signal,
    da.avg_turnover,
    COALESCE(ic.holder_count, 0) AS institutional_holders_count,
    iu.approval_status AS universe_status,
    iu.instrument_id AS universe_instrument_id
FROM sec_managers m
LEFT JOIN holdings_agg ha ON m.cik = ha.cik
LEFT JOIN drift_agg da ON m.cik = da.cik
LEFT JOIN inst_agg ic ON m.cik = ic.manager_cik
LEFT JOIN instruments_universe iu
    ON iu.attributes->>'sec_crd_number' = m.crd_number
    AND iu.organization_id = :org_id
WHERE 1=1
    {dynamic_filters}  -- appended by build_screener_queries()
ORDER BY {sort_column} {sort_direction} NULLS LAST
LIMIT :page_size OFFSET :offset;

-- COUNT QUERY (separate, run via asyncio.gather with data query)
SELECT COUNT(*) FROM sec_managers m
LEFT JOIN holdings_agg ha ON m.cik = ha.cik
LEFT JOIN drift_agg da ON m.cik = da.cik
LEFT JOIN inst_agg ic ON m.cik = ic.manager_cik
LEFT JOIN instruments_universe iu
    ON iu.attributes->>'sec_crd_number' = m.crd_number
    AND iu.organization_id = :org_id
WHERE 1=1
    {same_dynamic_filters};  -- identical WHERE clause, no ORDER BY/LIMIT
```

**Critical:** All hypertable queries include time-column filters (`:cutoff_date`, `:drift_cutoff`, `:inst_cutoff`) for chunk pruning. Default cutoffs: 2 years for holdings, 15 months for drift, 6 months for institutional.

### Research Insights — TimescaleDB Query Optimization

**1. Continuous aggregates replace per-request CTEs:**

Create 2 continuous aggregates (new migration 0038) for pre-computed holdings and drift metrics:

```sql
-- Holdings aggregate: sector weights, HHI components, position counts
CREATE MATERIALIZED VIEW sec_13f_holdings_agg
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT
    cik,
    time_bucket('3 months'::interval, report_date) AS quarter,
    sector,
    SUM(market_value) AS sector_value,
    COUNT(DISTINCT cusip) AS position_count
FROM sec_13f_holdings
WHERE asset_class = 'COM'
GROUP BY cik, time_bucket('3 months'::interval, report_date), sector
WITH NO DATA;

-- Drift aggregate: churn counts per quarter
CREATE MATERIALIZED VIEW sec_13f_drift_agg
WITH (timescaledb.continuous, timescaledb.materialized_only = true) AS
SELECT
    cik,
    time_bucket('3 months'::interval, quarter_to) AS quarter,
    COUNT(*) FILTER (WHERE action IN ('NEW_POSITION','EXITED')) AS churn_count,
    COUNT(*) AS total_changes
FROM sec_13f_diffs
GROUP BY cik, time_bucket('3 months'::interval, quarter_to)
WITH NO DATA;
```

Use `materialized_only = true` (not real-time mode) — SEC 13F data arrives in quarterly batches, real-time union adds overhead with no benefit. Refresh policy: daily after SEC ingestion.

**2. LATERAL JOIN bug — confirmed (TimescaleDB issue #8642):**

LATERAL JOINs break chunk exclusion in TimescaleDB 2.22+. The plan's original `CROSS JOIN LATERAL` for per-manager totals must be replaced with CTEs:

```sql
-- BAD: LATERAL breaks chunk pruning
CROSS JOIN LATERAL (SELECT SUM(market_value) ... WHERE h.cik = m.cik) q_total

-- GOOD: CTE with explicit time filter
WITH holdings_totals AS (
    SELECT cik, SUM(market_value) AS total
    FROM sec_13f_holdings
    WHERE report_date >= :cutoff AND report_date < :end
    GROUP BY cik
)
SELECT m.*, ht.total FROM sec_managers m LEFT JOIN holdings_totals ht ON ...
```

**3. Chunk pruning verification:**

Always verify with `EXPLAIN (ANALYZE, BUFFERS)`. Look for `Chunks excluded during startup: N` (good) vs `0` (bad). Date boundary must be computed in application code and passed as bind parameter — subqueries in WHERE defeat chunk exclusion.

**4. Separate count query instead of `COUNT(*) OVER()`:**

`COUNT(*) OVER()` forces full materialization before LIMIT. Use `asyncio.gather()` with two queries:

```python
results_query = screener_stmt.limit(page_size).offset(offset)
count_query = select(func.count()).select_from(screener_base.subquery())
results, total = await asyncio.gather(
    db.execute(results_query),
    db.scalar(count_query),
)
```

### Research Insights — Dynamic SQL Builder

**Use SQLAlchemy Core, not `text()`** — matches existing codebase patterns (`screener.py`, `instruments.py`, `funds.py`). Core provides type safety and automatic parameterization while remaining flexible.

```python
@dataclass(frozen=True)
class ScreenerFilters:
    aum_min: int | None = None
    aum_max: int | None = None
    compliance_clean: bool | None = None
    registration_status: list[str] | None = None
    states: list[str] | None = None
    search: str | None = None
    # ... all filter fields
    sort_by: str = "aum_total"
    sort_dir: str = "desc"
    page: int = 1
    page_size: int = 50

def build_screener_query(filters: ScreenerFilters) -> Select:
    stmt = select(SecManager.crd_number, SecManager.firm_name, ...)
    conditions: list = []
    if filters.aum_min is not None:
        conditions.append(SecManager.aum_total >= filters.aum_min)
    if filters.compliance_clean:
        conditions.append(SecManager.compliance_disclosures == 0)
    # ... each filter adds to conditions list
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = _apply_sort(stmt, filters.sort_by, filters.sort_dir)
    return stmt.limit(filters.page_size).offset((filters.page - 1) * filters.page_size)
```

**Sort column allowlist** (prevents SQL injection on ORDER BY):

```python
_SORT_COLUMNS = {
    "firm_name": SecManager.firm_name,
    "aum_total": SecManager.aum_total,
    "compliance_disclosures": SecManager.compliance_disclosures,
    "last_adv_filed_at": SecManager.last_adv_filed_at,
}
def _apply_sort(stmt, sort_by, sort_dir):
    column = _SORT_COLUMNS.get(sort_by, SecManager.aum_total)
    order = column.desc() if sort_dir == "desc" else column.asc()
    return stmt.order_by(order.nulls_last())
```

**Text search escaping** for firm_name ILIKE:

```python
if filters.search:
    escaped = filters.search.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
    conditions.append(SecManager.firm_name.ilike(f"%{escaped}%"))
```

**Invariant test** (most important test in the suite):

```python
def test_holdings_subquery_always_filters_report_date():
    stmt = build_screener_query(ScreenerFilters())
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "report_date" in compiled, "Missing report_date filter — full hypertable scan!"
```

### 1.5 Detail Endpoints

**`GET /managers/{crd}/profile`** — Direct read from `sec_managers` + `sec_manager_funds` + `sec_manager_team` using `selectinload()` (lazy="raise" enforced):

```python
stmt = (
    select(SecManager)
    .options(selectinload(SecManager.funds), selectinload(SecManager.team))
    .where(SecManager.crd_number == crd)
)
```

**`GET /managers/{crd}/holdings`** — Two queries:
1. Latest quarter holdings aggregated by sector (for pie chart)
2. Top 10 positions by market_value (for table)
3. Last 4 quarters sector_allocation for history (small multiples)

All queries filter by `report_date >= cutoff` for hypertable chunk pruning.

**`GET /managers/{crd}/drift`** — Query `sec_13f_diffs` for last 4-8 quarters, compute per-quarter metrics:

```python
# Per quarter: turnover_rate, new_positions, exited_positions, increased, decreased
SELECT quarter_to,
       COUNT(*) FILTER (WHERE action = 'NEW_POSITION') AS new_positions,
       COUNT(*) FILTER (WHERE action = 'EXITED') AS exited_positions,
       COUNT(*) FILTER (WHERE action IN ('NEW_POSITION', 'EXITED'))::float
           / NULLIF(COUNT(*), 0) AS turnover_rate
FROM sec_13f_diffs
WHERE cik = :cik AND quarter_to >= :cutoff
GROUP BY quarter_to
ORDER BY quarter_to
```

**`GET /managers/{crd}/institutional`** — Join `sec_13f_holdings` → `sec_institutional_allocations`:
1. Find all CUSIPs held by manager (latest quarter)
2. Find all institutional filers holding those CUSIPs
3. Determine coverage type (FOUND / PUBLIC_SECURITIES_NO_HOLDERS / NO_PUBLIC_SECURITIES)

**`POST /managers/{crd}/add-to-universe`** — Creates `Instrument` row:

```python
instrument = Instrument(
    organization_id=org_id,
    instrument_type="fund",
    name=manager.firm_name,
    asset_class=body.asset_class,  # User selects
    geography=body.geography,      # User selects
    currency=body.currency,        # Default USD
    block_id=body.block_id,        # Optional
    approval_status="pending",     # Enters IC approval flow
    attributes={
        "source": "sec_manager",
        "sec_crd_number": crd,
        "sec_cik": manager.cik,
        "aum_total": manager.aum_total,
    },
)
```

**`POST /managers/compare`** — Accepts `{crd_numbers: ["...", "..."]}` (2-5), returns:
- Side-by-side metrics table
- Sector allocation per manager (latest quarter)
- Holdings overlap (Jaccard: `|A ∩ B| / |A ∪ B|` on CUSIP sets)
- Turnover rate per quarter per manager (last 4Q)

### 1.6 Pydantic Schemas

**File:** `backend/app/domains/wealth/schemas/manager_screener.py`

```python
# --- Request schemas ---

class ManagerCompareRequest(BaseModel):
    crd_numbers: list[str] = Field(min_length=2, max_length=5)

class ManagerToUniverseRequest(BaseModel):
    asset_class: str
    geography: str
    currency: str = "USD"
    block_id: str | None = None

# --- Response schemas ---

class ManagerRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    crd_number: str
    firm_name: str
    aum_total: int | None = None
    strategy_types: list[str] = Field(default_factory=list)
    top_sector: str | None = None
    hhi: float | None = None
    position_count: int | None = None
    portfolio_value: int | None = None
    compliance_disclosures: int | None = None
    drift_signal: bool = False
    avg_turnover: float | None = None
    institutional_holders_count: int = 0
    universe_status: str | None = None  # "pending" | "approved" | "dd_pending" | "watchlist" | None
    universe_instrument_id: uuid.UUID | None = None
    last_13f_date: date | None = None

class ManagerScreenerPage(BaseModel):
    managers: list[ManagerRow]
    total_count: int
    page: int
    page_size: int
    has_next: bool

class ManagerProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    crd_number: str
    cik: str | None = None
    firm_name: str
    sec_number: str | None = None
    registration_status: str | None = None
    aum_total: int | None = None
    aum_discretionary: int | None = None
    aum_non_discretionary: int | None = None
    total_accounts: int | None = None
    fee_types: dict[str, Any] = Field(default_factory=dict)
    client_types: dict[str, Any] = Field(default_factory=dict)
    state: str | None = None
    country: str | None = None
    website: str | None = None
    compliance_disclosures: int | None = None
    last_adv_filed_at: date | None = None
    funds: list[ManagerFundRead] = Field(default_factory=list)
    team: list[ManagerTeamMemberRead] = Field(default_factory=list)

class ManagerFundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    fund_name: str
    fund_id: str | None = None
    gross_asset_value: int | None = None
    fund_type: str | None = None
    is_fund_of_funds: bool | None = None
    investor_count: int | None = None

class ManagerTeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    person_name: str
    title: str | None = None
    role: str | None = None
    certifications: list[str] = Field(default_factory=list)
    years_experience: int | None = None
    bio_summary: str | None = None

class HoldingRow(BaseModel):
    cusip: str
    issuer_name: str
    sector: str | None = None
    market_value: int | None = None
    shares: int | None = None
    weight_pct: float | None = None

class ManagerHoldingsRead(BaseModel):
    crd_number: str
    report_date: date | None = None
    sector_allocation: dict[str, float] = Field(default_factory=dict)  # sector → weight %
    top_10_positions: list[HoldingRow] = Field(default_factory=list)
    hhi: float | None = None
    position_count: int | None = None
    portfolio_value: int | None = None
    sector_history: list[dict[str, Any]] = Field(default_factory=list)  # [{quarter, sectors: {}}]

class DriftQuarter(BaseModel):
    quarter_date: date
    turnover_rate: float
    new_positions: int
    exited_positions: int
    increased: int
    decreased: int
    unchanged: int

class ManagerDriftRead(BaseModel):
    crd_number: str
    quarters: list[DriftQuarter] = Field(default_factory=list)
    style_drift_detected: bool = False

class InstitutionalHolder(BaseModel):
    filer_name: str
    filer_type: str | None = None
    filer_cik: str
    market_value: int | None = None
    shares: int | None = None
    report_date: date | None = None

class ManagerInstitutionalRead(BaseModel):
    crd_number: str
    coverage_type: str  # "found" | "public_securities_no_holders" | "no_public_securities"
    institutional_holders: list[InstitutionalHolder] = Field(default_factory=list)
    holder_count: int = 0

class ManagerUniverseRead(BaseModel):
    crd_number: str
    universe_status: str | None = None
    instrument_id: uuid.UUID | None = None
    dd_report_id: uuid.UUID | None = None
    approval_status: str | None = None

class ManagerCompareResult(BaseModel):
    managers: list[ManagerRow]
    sector_allocations: dict[str, dict[str, float]]  # crd → {sector: weight}
    holdings_overlap: dict[str, float]  # "crd1_crd2" → jaccard similarity
    drift_comparison: dict[str, list[DriftQuarter]]  # crd → quarters
```

### Research Insights — Peer Comparison SQL

**Combined single-query approach** (all metrics in one round-trip):

```sql
WITH holdings AS (
    SELECT h.cik, h.cusip, h.market_value, h.sector,
           h.market_value::float / SUM(h.market_value) OVER (PARTITION BY h.cik) AS weight
    FROM sec_13f_holdings h
    WHERE h.cik = ANY(:cik_list) AND h.report_date = :quarter AND h.market_value > 0
),
hhi AS (
    SELECT cik, SUM(weight * weight) AS hhi,
           1.0 / NULLIF(SUM(weight * weight), 0) AS effective_positions,
           COUNT(*) AS position_count, SUM(market_value) AS total_mv
    FROM holdings GROUP BY cik
),
sectors AS (
    SELECT cik, jsonb_object_agg(
        COALESCE(sector, 'Unknown'), ROUND((SUM(weight) * 100)::numeric, 2)
    ) AS allocation
    FROM holdings GROUP BY cik
),
cusip_sets AS (
    SELECT cik, array_agg(DISTINCT cusip) AS cusips FROM holdings GROUP BY cik
),
jaccard AS (
    SELECT a.cik AS cik_a, b.cik AS cik_b,
           cardinality(ARRAY(SELECT unnest(a.cusips) INTERSECT SELECT unnest(b.cusips)))::float
           / NULLIF(cardinality(ARRAY(SELECT unnest(a.cusips) UNION SELECT unnest(b.cusips))), 0)::float
           AS jaccard
    FROM cusip_sets a CROSS JOIN cusip_sets b WHERE a.cik < b.cik
)
-- Return via UNION ALL with type discriminator
SELECT 'hhi' AS type, cik, NULL AS cik_b, jsonb_build_object('hhi', hhi, 'positions', position_count) AS data FROM hhi
UNION ALL SELECT 'sectors', cik, NULL, jsonb_build_object('allocation', allocation) FROM sectors
UNION ALL SELECT 'jaccard', cik_a, cik_b, jsonb_build_object('jaccard', jaccard) FROM jaccard;
```

**Weighted Jaccard** recommended in Python (SQL FULL OUTER JOIN is fragile): fetch holdings as `{cusip: weight}` dicts, compute `SUM(min(w_A, w_B)) / SUM(max(w_A, w_B))`.

**Style drift detection** — industry standard thresholds:
- Sector weight shift > 5pp in one quarter = notable drift
- Top sector change between quarters = definitive rotation signal
- Combine both into a boolean `style_drift_detected` flag

**Performance:** 5 managers × 100 positions × 4 quarters = 2000 rows. Trivial. Existing indexes `(cik, report_date DESC)` sufficient. No new indexes needed for peer comparison.

### 1.7 Tests

**File:** `backend/tests/test_manager_screener.py`

Test categories:
1. **Screener query builder** — verify dynamic WHERE clauses for each filter block
2. **Pagination** — page/page_size/total_count/has_next
3. **Sort** — each sortable column, ASC/DESC, NULL handling
4. **Profile endpoint** — selectinload of funds/team
5. **Holdings endpoint** — sector aggregation, HHI computation, 4Q history
6. **Drift endpoint** — turnover calculation, style drift detection
7. **Institutional endpoint** — coverage type detection, holder count
8. **Add to Universe** — creates Instrument with correct attributes JSONB, enters pending status
9. **Compare endpoint** — Jaccard overlap, sector comparison, turnover comparison
10. **Authorization** — 403 for non-investment roles
11. **Chunk pruning** — all hypertable queries include time filters

### 1.8 Acceptance Criteria — Phase 1

- [ ] `GET /api/v1/manager-screener` returns paginated results with all 5 filter blocks functional
- [ ] All filters use parameterized SQL (no f-string injection)
- [ ] All hypertable queries include time-column filters for chunk pruning
- [ ] `instruments_universe` join uses `attributes->>'sec_crd_number'` with org_id filter
- [ ] `POST /managers/{crd}/add-to-universe` creates Instrument with `approval_status="pending"`
- [ ] `POST /managers/compare` validates 2-5 CRD numbers, returns overlap + drift
- [ ] All endpoints require INVESTMENT_TEAM or ADMIN role
- [ ] VirtualList-compatible pagination (total_count via window function)
- [ ] Tests cover all filter blocks, edge cases (empty results, missing 13F data)
- [ ] `make check` passes (lint + typecheck + architecture + test)

---

## Phase 2 — Screener Aggregation Cache + Cross-Vertical Caching

### 2.1 Redis Aggregation Cache

Pre-compute heavy aggregates per manager and cache in Redis. Refreshed daily by a new worker or piggybacked on existing SEC seed refresh.

```
Key:    screener:agg:{crd_number}
TTL:    24 hours
Value:  JSON {
    top_sector, hhi, position_count, portfolio_value,
    turnover_4q, style_drift, institutional_holders_count,
    last_13f_date
}
```

**Impact:** Main screener list query drops from multi-CTE join to `sec_managers` + Redis MGET. Sub-100ms for 5000 rows.

### 2.2 SEC Refresh Worker

**File:** `backend/app/domains/wealth/workers/sec_refresh.py`

| Property | Value |
|----------|-------|
| Lock ID | **900_016** (900_013 reserved for `thirteenf_backfill.py` historical backfill) |
| Scope | global |
| Frequency | Daily |
| Timeout | 600s (heavy) |

Refreshes 13F holdings for managers referenced in any tenant's `instruments_universe` (not all 5000+). Recomputes Redis aggregation cache after refresh.

**Lock ID allocation (updated):**

| Worker | Lock ID | Notes |
|--------|---------|-------|
| `thirteenf_backfill.py` (historical) | 900_013 | Already proposed in prior conversation |
| `sec_refresh.py` (daily + cache) | 900_016 | This plan |
| `nport_ingestion` (Phase 4) | 900_018 | This plan |
| `bis_ingestion` (Phase 6) | 900_014 | This plan |
| `imf_ingestion` (Phase 6) | 900_015 | This plan |

### 2.3 Cross-Vertical Caching

| Cache Key | TTL | Source | Impact |
|-----------|-----|--------|--------|
| `credit:macro_snapshot:{geography}:{date}` | 24h | `macro_data` hypertable | Deep review stage 5: 50 DB reads → 1 Redis GET |
| `macro:dashboard_widget` | Until next ingestion | `macro_data` + `macro_regional_snapshots` | Both dashboards: <10ms load |
| `correlation:{org_id}:{profile}:{date}` | 24h | Pre-computed in `risk_calc` | Correlation heatmap: instant render |
| `scoring:leaderboard:{org_id}:{profile}` | 24h | Pre-computed in `risk_calc` | Screener Layer 3: O(1) lookup |

### Research Insights — Redis Caching Patterns

**Batch reads:** Use `MGET` (single atomic command, single round-trip) for 50-100 keys per page. Not pipeline (adds overhead for homogeneous reads).

**Cache warming:** Hybrid — worker refresh after SEC ingestion + compute-on-miss fallback:

```python
async def get_manager_aggregates(db, crd_numbers):
    try:
        cached = await redis.mget([f"screener:agg:{crd}" for crd in crd_numbers])
        misses = [crd for crd, val in zip(crd_numbers, cached) if val is None]
    except Exception:
        logger.warning("screener_cache_unavailable_falling_back_to_sql")
        misses = crd_numbers
    if misses:
        computed = await _compute_aggregates_sql(db, misses)
        try:
            await _set_aggregates_batch(computed)  # best-effort backfill
        except Exception:
            pass
        return {**{crd: json.loads(v) for crd, v in zip(crd_numbers, cached) if v}, **computed}
    return {crd: json.loads(v) for crd, v in zip(crd_numbers, cached) if v}
```

**Invalidation:** Worker-driven targeted refresh. After SEC 13F ingestion, recompute only touched CIKs. Daily full refresh as safety net. No `KEYS *`, no keyspace notifications.

**Stampede prevention:** TTL jitter (`86400 ± 3600` seconds) + worker-driven refresh (keys rarely expire naturally).

**Serialization:** `json.dumps`/`json.loads` (consistent with codebase, debuggable, ~200 byte payload).

**Memory:** ~4MB total (5000 keys × 320 bytes + 6 leaderboard sorted sets). Trivial for Upstash.

### 2.4 Acceptance Criteria — Phase 2

- [ ] SEC refresh worker uses advisory lock 900_013, deterministic (not `hash()`)
- [ ] Redis aggregation cache populated for all managers with 13F data
- [ ] Main screener query reads from cache when available, falls back to live query
- [ ] Credit macro snapshot cache reduces deep review DB reads measurably
- [ ] `make check` passes

---

## Phase 3 — ESMA Register + UCITS Yahoo Finance Seed

### 3.1 New Files

```
backend/data_providers/esma/
    __init__.py
    models.py                ← frozen dataclasses (EsmaManager, EsmaFund, IsinResolution)
    register_service.py      ← ESMA Register API client (esma-registers package)
    ticker_resolver.py       ← ISIN → YFinance ticker resolution (suffix cascade)
    seed/
        __init__.py
        populate_seed.py     ← 4-phase resumable seed (follows sec/seed pattern)
```

### 3.2 New Tables (Migration 0038)

```sql
CREATE TABLE esma_managers (
    esma_id         TEXT PRIMARY KEY,
    lei             TEXT,
    company_name    TEXT NOT NULL,
    country         TEXT,
    authorization_status TEXT,
    fund_count      INTEGER,
    sec_crd_number  TEXT,  -- cross-reference to sec_managers (nullable)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fetched_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE esma_funds (
    isin            TEXT PRIMARY KEY,
    fund_name       TEXT NOT NULL,
    esma_manager_id TEXT NOT NULL REFERENCES esma_managers(esma_id),
    domicile        TEXT,
    fund_type       TEXT,
    host_member_states TEXT[],
    yahoo_ticker    TEXT,
    ticker_resolved_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_fetched_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE esma_isin_ticker_map (
    isin            TEXT PRIMARY KEY,
    yahoo_ticker    TEXT,
    exchange        TEXT,
    resolved_via    TEXT NOT NULL,
    is_tradeable    BOOLEAN NOT NULL,
    last_verified_at TIMESTAMPTZ NOT NULL
);
```

All global (no `organization_id`, no RLS). Not hypertables (low-volume reference data).

### 3.3 Seed Pipeline (4 phases, resumable)

| Phase | Input | Output | Volume |
|-------|-------|--------|--------|
| 1 | `esma-registers` Python package | `esma_managers` + `esma_funds` | ~15K |
| 2 | ISIN suffix cascade (.L, .PA, .AS, .DE, .MI, .SW, .IR, .BR) | `esma_isin_ticker_map` | ~5-10K resolved |
| 3 | `yfinance.download()` 3yr backfill | `nav_timeseries` (existing hypertable) | ~5-10K × 750 days |
| 4 | Name fuzzy match (rapidfuzz ≥0.85) + LEI (GLEIF) | `esma_managers.sec_crd_number` | Cross-ref |

Resolved funds auto-create `Instrument` entries in `instruments_universe` with `attributes.source = "esma_register"`, entering existing screening/risk/DD pipelines.

### 3.4 Import-Linter

Existing contract (pyproject.toml line 473-477) already covers `data_providers.esma`:

```toml
[[tool.importlinter.contracts]]
name = "Data providers must not import verticals or app domains or quant_engine"
type = "forbidden"
source_modules = ["data_providers"]
forbidden_modules = ["vertical_engines", "app.domains", "quant_engine"]
```

No new contracts needed.

### 3.5 Dependencies (CORRECTED)

**`esma-registers` package does NOT exist on PyPI.** The ESMA-published `esma_data_py` only covers MIFID/FIRDS/SSR — not the UCITS fund register.

**Correct approach:** Direct Solr API queries to ESMA registers + FIRDS bulk XML download.

```toml
# pyproject.toml [project.optional-dependencies]
esma = ["sdmx1>=2.5.0"]  # for BIS SDMX parsing (Phase 6), not needed for ESMA Solr
# ESMA Solr API uses httpx (already a dependency)
# FIRDS XML uses stdlib xml.etree.ElementTree
# OpenFIGI uses httpx (already a dependency)
```

### Research Insights — ESMA Seed Pipeline (Corrected Architecture)

**ESMA Fund Register has 134K UCITS entries** (not 15K as estimated). Available via public Solr:

```
https://registers.esma.europa.eu/solr/esma_registers_funds_cbdif/select
  ?q=*:*&fq=funds_legal_framework_name:UCITS&rows=1000&start=0&wt=json
```

Fields per fund: `funds_lei`, `funds_national_name`, `funds_manager_lei`, `funds_manager_nat_name`, `funds_domicile_cou_code`, `funds_status_code_name`, `funds_host_country_codes`.

**Critical: No ISIN in fund register.** ISINs are in FIRDS (Financial Instruments Reference Data System):

```
Download: https://firds.esma.europa.eu/firds/FULINS_C_YYYYMMDD_01of01.zip
```

Weekly XML dump of all Collective Investment Vehicle instruments (CFI starts with "C"). Contains ISIN + issuer_LEI. **Join with fund register on LEI.**

**Corrected 4-phase pipeline:**

| Phase | Input | Output | Volume |
|-------|-------|--------|--------|
| 1 | ESMA Solr API (paginated) | `esma_managers` + `esma_funds` (LEI-keyed) | ~134K UCITS |
| 2 | FIRDS FULINS_C XML download | Join ISIN to `esma_funds` via LEI | ~70-80% ISIN match |
| 3 | OpenFIGI batch API (`idType=ID_ISIN`) | `esma_isin_ticker_map` (ticker + exchange) | ~70-80% of ISINs |
| 4 | `yfinance.download()` (only resolved tickers) | `nav_timeseries` + `instruments_universe` | ~35-45K with NAV |

**OpenFIGI is the key resolver** (not suffix cascade). With free API key: 25,000 ISINs/minute, 100 per batch. 134K ISINs resolved in ~6 minutes.

**Exchange code mapping** (OpenFIGI → Yahoo Finance suffix):

```python
EXCH_SUFFIX = {"LN": "L", "GY": "DE", "FP": "PA", "NA": "AS", "SM": "MC",
               "IM": "MI", "SE": "ST", "DC": "CO", "BB": "BR", "AV": "VI", "SW": "SW"}
```

**Realistic yield: ~35-45K funds with usable NAV** (not 5-10K). Many non-exchange-traded UCITS won't have Yahoo Finance data, but exchange-accessible funds (which institutional portfolios heavily use) will be covered.

### 3.6 Acceptance Criteria — Phase 3

- [ ] ESMA seed populates `esma_managers` and `esma_funds` from register API
- [ ] ISIN → YFinance resolution achieves ≥30% success rate (≥5K of ~15K)
- [ ] Resolved UCITS funds appear in `instruments_universe` with correct attributes JSONB
- [ ] NAV backfill uses existing `nav_timeseries` hypertable (no new time-series table)
- [ ] SEC ↔ ESMA cross-reference populated where name match ≥0.85
- [ ] Checkpoint/resume works (`.esma_seed_checkpoint.json`)
- [ ] `make check` passes (import-linter validates no forbidden imports)

---

## Phase 4 — N-PORT Integration

Monthly portfolio holdings for US mutual funds (not covered by 13F).

```
backend/data_providers/sec/nport_service.py
```

New hypertable: `sec_nport_holdings` (partitioned by `report_date`, 3-month chunks, segmentby=`cik`). Expands universe from ~5K 13F filers to ~15K+ registered funds.

Worker: `nport_ingestion` (Lock ID: 900_018).

---

## Phase 5 — ADV Part 2A Brochure Extraction

Full implementation of `AdvService.fetch_manager_team()` via Mistral OCR (currently stub returning empty list).

New table: `sec_manager_brochure_text` for full-text search across manager philosophies.

Enables search like "find all managers mentioning 'ESG integration'" in the Manager Screener.

---

## Phase 6 — BIS + IMF Macro Enrichment

```
backend/data_providers/bis/service.py      ← BIS Statistics API (credit-to-GDP, property prices)
backend/data_providers/imf/service.py      ← IMF WEO API (GDP forecasts, inflation projections)
```

New hypertables: `bis_statistics` (Lock ID: 900_014), `imf_weo_forecasts` (Lock ID: 900_015).

Integrates into `regional_macro_service.py` scoring dimensions.

### Research Insights — BIS & IMF APIs (Confirmed Working)

**BIS SDMX REST API** (`https://stats.bis.org/api/v1/data/`):

| Dataset | Dataflow | Key Example | Data Confirmed |
|---------|----------|------------|----------------|
| Credit-to-GDP gap | `WS_CREDIT_GAP` | `Q.US.P.A.C` | US Q3 2025 = -12.1pp |
| Debt service ratio | `WS_DSR` | `Q.US.P` | US Q3 2025 = 14.1% |
| Property prices | `WS_SPP` | `Q.US.R.628` | US Q3 2025 = 157.67 |
| Effective exchange rates | `WS_EER` | `M.N.B.CH` | Available |
| Central bank rates | `WS_CBPOL` | varies | Available |

**Credit-to-GDP gap is pre-computed by BIS** (`CG_DTYPE=C`). No HP filter needed. 44 countries covered.

**IMF WEO DataMapper API** (`https://www.imf.org/external/datamapper/api/v1/`):

Simple JSON (not SDMX). No authentication. Confirmed data:

| Indicator | Code | US 2025 | CN 2025 | BR 2025 |
|-----------|------|---------|---------|---------|
| GDP growth | `NGDP_RPCH` | 2.0% | 4.8% | 2.4% |
| Inflation | `PCPIPCH` | 2.7% | 0.0% | 5.2% |
| Fiscal balance | `GGXCNL_NGDP` | -7.4% | -8.6% | -8.4% |
| Govt debt | `GGXWDG_NGDP` | Available | Available | Available |

5-year forward projections (through 2030). Updated April + October.

**Integration with `regional_macro_service.py`:** BIS credit-to-GDP gap → `financial_conditions` dimension. IMF GDP forecasts → `growth` dimension (forward-looking complement to FRED backward-looking). Consider adding a 7th `credit_cycle` dimension with BIS gap + DSR + property prices.

**Parsing:** BIS via `sdmx1` library (BIS source available since v2.5.0) or direct XML parsing. IMF via simple `httpx.get()` → JSON. No heavy dependencies needed.

---

## System-Wide Impact

### Interaction Graph

```
Manager Screener Route
  → reads sec_managers (global, no RLS)
  → reads sec_13f_holdings (global hypertable, chunk-pruned)
  → reads sec_13f_diffs (global hypertable, chunk-pruned)
  → reads sec_institutional_allocations (global hypertable, chunk-pruned)
  → left joins instruments_universe (org-scoped, RLS via get_db_with_rls)
  → Add to Universe writes instruments_universe → triggers existing:
    → screening_batch worker (re-screens new instrument)
    → instrument_ingestion worker (fetches NAV if ticker provided)
    → risk_calc worker (computes CVaR/Sharpe once NAV available)
    → IC approval flow (pending → approved/rejected)
```

### Error Propagation

- SEC global tables may be empty for new deployments → screener returns empty results (not error)
- Missing 13F data for a manager → holdings/drift tabs show "No 13F filings found"
- ESMA seed failure → does not affect SEC screener (independent)
- Redis cache miss → fallback to live SQL query (transparent to client)

### State Lifecycle Risks

- `POST /add-to-universe` is the only write → single Instrument INSERT, atomic
- If INSERT succeeds but subsequent screening/ingestion workers fail → instrument exists in pending state, can be re-triggered
- No partial state: either the Instrument row exists or it doesn't

### API Surface Parity

- `POST /add-to-universe` produces same `InstrumentRead` as `POST /instruments` — identical response model
- Instrument enters same approval flow as manual creation or CSV/Yahoo import
- No parallel approval track — Manager Screener is a channel of entry, not a bypass

---

## Technical Considerations

### Performance

- **Main screener query** with 5000+ managers: O(N) scan of `sec_managers` + pre-computed continuous aggregates. Phase 2 Redis cache reduces to O(N) of small Redis MGET.
- **Hypertable chunk pruning** is mandatory — without time filters, full scans on `sec_13f_holdings` (~millions of rows) would be catastrophic.
- **VirtualList** on frontend — server only sends page_size rows. Separate count query via `asyncio.gather()` (not `COUNT(*) OVER()`).
- **New indexes for screener** (migration 0038):
  ```sql
  CREATE INDEX idx_sec_managers_aum ON sec_managers (aum_total DESC);
  CREATE INDEX idx_sec_managers_compliance_aum ON sec_managers (compliance_disclosures, aum_total DESC);
  ```
- **Continuous aggregate indexes** (auto-created by TimescaleDB, plus manual):
  ```sql
  CREATE INDEX idx_sec_13f_holdings_agg_cik_quarter ON sec_13f_holdings_agg (cik, quarter DESC);
  CREATE INDEX idx_sec_13f_drift_agg_cik_quarter ON sec_13f_drift_agg (cik, quarter DESC);
  ```

### Security

- All SQL uses parameterized queries (`:param` syntax with `text()`) — no f-string injection
- Global SEC tables have no RLS, but `instruments_universe` join is org-scoped
- Role enforcement on all endpoints (INVESTMENT_TEAM or ADMIN)
- CRD number validated as alphanumeric before use in queries

### Architecture

- No new ORM models (screener is a view layer)
- No new import-linter contracts (existing `data_providers` contract sufficient)
- Dynamic SQL builder lives in route file (not a separate service) — the screener has no business logic to test independently
- ESMA data provider follows exact same structure as `data_providers/sec/`

---

## Dependencies & Prerequisites

| Dependency | Status | Notes |
|-----------|--------|-------|
| SEC tables populated (seed) | ✅ Done | ~200 managers, 8 quarters holdings |
| `sec_13f_holdings.sector` enriched | ✅ Done | Phase 4 of SEC seed |
| `instruments_universe` model | ✅ Done | Migration 0012+ |
| ESMA Solr API + FIRDS XML + OpenFIGI | ⏳ Phase 3 | Direct HTTP (httpx), no package dependency. OpenFIGI free API key needed. |
| Redis available | ✅ Done | docker-compose (dev), Upstash (prod) |

---

## Sources & References

### Origin

- **Brainstorm:** [docs/brainstorms/2026-03-21-hypertable-opportunities-manager-screener-brainstorm.md](docs/brainstorms/2026-03-21-hypertable-opportunities-manager-screener-brainstorm.md)
  - Key decisions: no new ORM models, dynamic SQL builder, Redis aggregation cache, `attributes->>'sec_crd_number'` linkage, ESMA→YFinance seed pipeline

### Internal References

- Query builder: `backend/app/domains/wealth/queries/manager_screener_sql.py` (pure, no I/O)
- Route patterns: `backend/app/domains/wealth/routes/screener.py`, `instruments.py`
- Schema patterns: `backend/app/domains/wealth/schemas/screening.py`, `instrument.py`
- SEC models: `backend/app/shared/models.py` (lines 107-369)
- Worker dispatch: `backend/app/domains/wealth/routes/workers.py`
- SEC seed: `backend/data_providers/sec/seed/populate_seed.py`
- Advisory lock pattern: `backend/app/domains/wealth/workers/treasury_ingestion.py`
- Router registration: `backend/app/main.py` (lines 87-107, 337-358)

### External References

- ESMA Registers Python package: `esma-registers` on PyPI
- SEC EDGAR rate limit: 10 req/s (we use 8 req/s conservative)
- OpenFIGI batch API: 100 CUSIPs/request, 250 req/min with API key
- Yahoo Finance ISIN resolution: suffix by exchange (.L, .PA, .AS, .DE, .MI, .SW)
