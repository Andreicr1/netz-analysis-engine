# Phase 1B — N-PORT Holdings Tab + Brochure Full-Text Search

**Status:** Ready
**Estimated scope:** ~350 lines changed
**Risk:** Low (new endpoints + frontend tab, existing data)
**Prerequisite:** None

---

## Context

The Manager Screener has 5 tabs (Profile, Holdings, Drift, Institutional, Universe) in a detail drawer. Two data sources are in the DB but have no REST endpoints:

1. **`sec_nport_holdings`** hypertable — populated by `nport_ingestion` worker (lock 900_018), contains mutual fund portfolio data from SEC N-PORT filings. No endpoint exposes it.
2. **`sec_manager_brochure_text`** table — 18 classified ADV Part 2A sections with GIN full-text index. No search endpoint.

**Existing patterns to follow:**
- Routes: `backend/app/domains/wealth/routes/manager_screener.py` (8 endpoints, lines 100-806)
- Schemas: `backend/app/domains/wealth/schemas/manager_screener.py` (7 response models)
- Queries: `backend/app/domains/wealth/queries/manager_screener_sql.py` (reflected tables)
- Frontend drawer: `frontends/wealth/src/routes/(team)/manager-screener/+page.svelte`

---

## Task 1: N-PORT Holdings Endpoint + Tab

### Step 1.1 — Schema

In `backend/app/domains/wealth/schemas/manager_screener.py`, add:

```python
class NportHoldingItem(BaseModel):
    cusip: str | None = None
    isin: str | None = None
    issuer_name: str
    asset_class: str | None = None
    sector: str | None = None
    market_value: float | None = None
    quantity: float | None = None
    currency: str | None = None
    pct_of_nav: float | None = None
    report_date: date

class NportHoldingsResponse(BaseModel):
    crd_number: int
    report_date: date | None = None
    total_holdings: int
    holdings: list[NportHoldingItem]
    page: int
    page_size: int
    total_pages: int
```

### Step 1.2 — Query

In `backend/app/domains/wealth/queries/manager_screener_sql.py`, add N-PORT query function:

```python
def build_nport_query(cik: int, report_date: date | None = None, page: int = 1, page_size: int = 50):
    """
    Query sec_nport_holdings by CIK.
    N-PORT is keyed on `cik` (not `crd_number`) — resolve CRD→CIK first.
    Hypertable: 3-month chunks, segmentby: cik.
    If no report_date, get latest quarter.
    """
```

**Critical:** N-PORT uses `cik` not `crd_number`. The route receives `crd`, must resolve to CIK via `sec_managers` table first. Use existing `_get_manager()` pattern from routes file.

**Query pattern:** Get latest `report_date` first if not specified, then filter holdings by that quarter. Always include `report_date` filter for efficient chunk pruning.

### Step 1.3 — Route

In `backend/app/domains/wealth/routes/manager_screener.py`, add:

```python
@router.get(
    "/managers/{crd}/nport",
    response_model=NportHoldingsResponse,
    summary="N-PORT mutual fund holdings for a manager",
)
async def get_manager_nport_holdings(
    crd: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    report_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table, no RLS needed
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
```

**Important:** `sec_nport_holdings` is a **global table** (no `organization_id`, no RLS). Use `get_db_session` not `get_db_with_rls`.

### Step 1.4 — Frontend Tab

In the Manager Screener drawer (find the tabs section in `+page.svelte`), add a 6th tab "Fund Holdings":

- Load on-demand when tab is selected (not in server load)
- Use `api.get(`/manager-screener/managers/${crd}/nport`)` inline
- Show paginated table: issuer, asset class, market value, % NAV, report date
- Empty state: "No N-PORT filings found for this manager"
- Pagination: URL-driven with `goto()`

---

## Task 2: Brochure Full-Text Search Endpoints

### Step 2.1 — Schemas

In `backend/app/domains/wealth/schemas/manager_screener.py`, add:

```python
class BrochureSectionItem(BaseModel):
    section: str
    content_excerpt: str  # first 200 chars
    filing_date: date

class BrochureSectionsResponse(BaseModel):
    crd_number: int
    sections: list[BrochureSectionItem]
    total_sections: int

class BrochureSearchHit(BaseModel):
    section: str
    headline: str  # ts_headline highlighted match
    filing_date: date
    rank: float

class BrochureSearchResponse(BaseModel):
    crd_number: int
    query: str
    results: list[BrochureSearchHit]
    total_results: int
```

### Step 2.2 — Queries

In `backend/app/domains/wealth/queries/manager_screener_sql.py`, add two raw SQL queries:

**Sections listing:**
```sql
SELECT crd_number, section, LEFT(content, 200) AS content_excerpt, filing_date
FROM sec_manager_brochure_text
WHERE crd_number = :crd
ORDER BY filing_date DESC, section
```

**Full-text search** (use `text()` raw SQL — SQLAlchemy ORM lacks ts_vector support):
```sql
SELECT crd_number, section, filing_date,
       ts_headline('english', content, plainto_tsquery('english', :query),
                   'MaxFragments=2,MaxWords=30') AS headline,
       ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) AS rank
FROM sec_manager_brochure_text
WHERE crd_number = :crd
  AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
ORDER BY rank DESC
```

**Critical:**
- Use `plainto_tsquery` (NOT `to_tsquery`) — safe for arbitrary user input
- GIN index `ix_sec_brochure_text_fts` already exists
- Use `text()` from SQLAlchemy for raw SQL, with bound parameters (`:crd`, `:query`)

### Step 2.3 — Routes

**CRITICAL — Route Shadowing:** Register literal routes BEFORE parameterized routes.

In `manager_screener.py`, the endpoint `/managers/{crd}/brochure/sections` could be shadowed by `/{crd}` param. Add the brochure routes BEFORE any `/{crd}` catch-all.

```python
@router.get(
    "/managers/{crd}/brochure/sections",
    response_model=BrochureSectionsResponse,
    summary="List ADV brochure sections for a manager",
)
async def get_brochure_sections(
    crd: int,
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):

@router.get(
    "/managers/{crd}/brochure",
    response_model=BrochureSearchResponse,
    summary="Full-text search within manager's ADV brochure",
)
async def search_brochure(
    crd: int,
    q: str = Query(..., min_length=2, max_length=200),
    section: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),  # Global table
    _actor: dict = Depends(require_role(Role.INVESTMENT_TEAM)),
):
```

### Step 2.4 — Frontend Integration

In the Manager Screener drawer **Profile tab** (not a new tab), add an expandable "ADV Brochure" accordion section:

- Show sections listing by default (collapsed)
- Add search input with sequence counter for debounce (NOT AbortController)
- Display highlighted search results in a list

**Sequence counter pattern (from endpoint-coverage learning):**
```typescript
let searchSeq = $state(0);

async function searchBrochure(q: string) {
  const seq = ++searchSeq;
  const res = await api.get(`/manager-screener/managers/${crd}/brochure?q=${encodeURIComponent(q)}`);
  if (seq !== searchSeq) return; // stale
  searchResults = res;
}
```

### Step 2.5 — Shadowing Regression Test

Add test: `backend/tests/routes/test_manager_screener_route_shadowing.py`

```python
async def test_literal_routes_not_shadowed(client):
    """Brochure sections route must not be shadowed by {crd} param."""
    res = await client.get("/manager-screener/managers/12345/brochure/sections")
    assert res.status_code != 404  # Should not 404 from param shadowing
```

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/schemas/manager_screener.py` | Add 5 new response schemas |
| `backend/app/domains/wealth/queries/manager_screener_sql.py` | Add N-PORT + brochure queries |
| `backend/app/domains/wealth/routes/manager_screener.py` | Add 3 new endpoints |
| `frontends/wealth/src/routes/(team)/manager-screener/+page.svelte` | Add Fund Holdings tab + brochure accordion |
| `backend/tests/routes/test_manager_screener_route_shadowing.py` | New regression test |

## Acceptance Criteria

- [ ] `GET /managers/{crd}/nport` returns paginated N-PORT holdings
- [ ] Manager Screener drawer has 6th tab "Fund Holdings"
- [ ] Empty state when manager has no N-PORT filings
- [ ] `GET /managers/{crd}/brochure/sections` returns 18 sections with excerpts
- [ ] `GET /managers/{crd}/brochure?q=ESG` returns highlighted passages
- [ ] Profile tab shows collapsible brochure sections
- [ ] GIN index used (verify with EXPLAIN)
- [ ] Route shadowing regression test passes
- [ ] `make check` passes

## Gotchas

- N-PORT keyed on `cik`, not `crd_number` — resolve CRD→CIK via `sec_managers` first
- Both `sec_nport_holdings` and `sec_manager_brochure_text` are **global tables** — no RLS, no `organization_id`
- Use `plainto_tsquery` for safe user input (never `to_tsquery`)
- Register literal routes (`/brochure/sections`) BEFORE parameterized (`/{crd}`)
- Frontend: use sequence counter for search debounce, not AbortController
- Frontend: never use raw `fetch()` — always `api.get()` from client
