# Phase 2A — ESMA Ingestion Worker + REST Endpoints

**Status:** Ready
**Estimated scope:** ~500 lines new code
**Risk:** Medium (new worker + 5 endpoints, but follows existing patterns)
**Prerequisite:** None (ESMA services already validated in e2e tests)

---

## Context

ESMA (European Securities and Markets Authority) manages ~134K UCITS funds across Europe. The `RegisterService` and `TickerResolver` in `backend/data_providers/esma/` are functional (e2e validated), but:

1. **No worker** populates DB tables (`esma_managers`, `esma_funds`, `esma_isin_ticker_map`)
2. **No REST endpoints** expose the data
3. **No frontend** page exists

This session creates the backend (worker + endpoints). Frontend is in Phase 2B.

**Template to follow:** `nport_ingestion.py` (lock 900_018, ~91 lines, cleanest worker example).

---

## Task 1: ESMA Ingestion Worker

### Step 1.1 — Create worker file

Create `backend/app/domains/wealth/workers/esma_ingestion.py`:

```python
"""
ESMA UCITS fund universe ingestion worker.
Lock ID: 900_019 (deterministic, never use hash()).
Frequency: weekly.
Source: ESMA Solr register via RegisterService.
Tables: esma_managers, esma_funds, esma_isin_ticker_map (global, no RLS).
"""
```

**Pattern:** Copy structure from `backend/app/domains/wealth/workers/nport_ingestion.py`:
- Advisory lock with `pg_try_advisory_lock(900019)`
- Unlock in `finally` block
- Redis idempotency guard
- Chunked upsert (2000 rows per batch)

### Step 1.2 — Worker flow

```python
async def run_esma_ingestion(db: AsyncSession) -> dict:
    """
    1. Acquire advisory lock 900_019
    2. RegisterService.iter_ucits_funds() → paginate through ESMA Solr
    3. parse_manager_from_doc() extracts managers from fund docs
    4. Upsert esma_managers FIRST (FK dependency order)
    5. Upsert esma_funds SECOND
    6. TickerResolver.resolve_all() → upsert esma_isin_ticker_map
    7. Unlock in finally
    """
```

**Critical constraints:**
- ESMA Solr API: 4 req/s rate limit. ~134 pages at 1000/page = ~35s total. The `RegisterService` should already handle this.
- FK dependency: insert `esma_managers` before `esma_funds` (fund has FK to manager)
- Use `pg_insert(...).on_conflict_do_update()` for idempotent upserts
- Chunk size: 2000 rows per batch (same as other workers)
- Lock ID: **900_019** (next available after 900_018 for N-PORT)

### Step 1.3 — Imports

```python
from backend.data_providers.esma.register_service import RegisterService
from backend.data_providers.esma.ticker_resolver import TickerResolver
from backend.app.shared.models import EsmaManager, EsmaFund, EsmaIsinTickerMap
```

**Verify these models exist in `backend/app/shared/models.py`.** If not, they need to be created (check if migration for these tables already exists).

### Step 1.4 — Register trigger endpoint

In `backend/app/domains/wealth/routes/workers.py`, add:

```python
@router.post("/run-esma-ingestion", status_code=202, summary="Trigger ESMA universe ingestion")
async def trigger_run_esma_ingestion(
    bg: BackgroundTasks,
    _actor: dict = Depends(require_role(Role.ADMIN)),
):
    return _dispatch_worker(
        bg, "run-esma-ingestion", "global",
        run_esma_ingestion,
        timeout_seconds=_HEAVY_WORKER_TIMEOUT,  # 600s
    )
```

**Pattern:** Follow `trigger_run_nport_ingestion` (lines ~482-509 of `workers.py`). Use `_HEAVY_WORKER_TIMEOUT` (600s) since ESMA fetch is ~35s + DB writes.

---

## Task 2: ESMA REST Endpoints

### Step 2.1 — Create schemas

Create `backend/app/domains/wealth/schemas/esma.py`:

```python
from pydantic import BaseModel
from datetime import date

class EsmaManagerItem(BaseModel):
    esma_id: str
    company_name: str
    country: str | None = None
    sec_crd_number: int | None = None  # Cross-reference to SEC
    fund_count: int = 0

class EsmaManagerPage(BaseModel):
    items: list[EsmaManagerItem]
    total: int
    page: int
    page_size: int

class EsmaManagerDetail(BaseModel):
    esma_id: str
    company_name: str
    country: str | None = None
    sec_crd_number: int | None = None
    funds: list["EsmaFundItem"]

class EsmaFundItem(BaseModel):
    isin: str
    fund_name: str
    domicile: str | None = None
    fund_type: str | None = None
    ticker: str | None = None  # From ticker resolution
    esma_manager_id: str | None = None

class EsmaFundPage(BaseModel):
    items: list[EsmaFundItem]
    total: int
    page: int
    page_size: int

class EsmaFundDetail(BaseModel):
    isin: str
    fund_name: str
    domicile: str | None = None
    fund_type: str | None = None
    ticker: str | None = None
    manager: EsmaManagerItem | None = None

class EsmaSecCrossRef(BaseModel):
    esma_id: str
    sec_crd_number: int | None = None
    sec_firm_name: str | None = None
    matched: bool = False
```

### Step 2.2 — Create query builder

Create `backend/app/domains/wealth/queries/esma_sql.py`:

```python
"""
ESMA query builder.
Tables are global (no organization_id, no RLS).
Text search: ILIKE with _escape_ilike() — same as screener.
Consider trigram GIN index if search is slow:
  CREATE INDEX ix_esma_funds_name_trgm ON esma_funds USING gin (fund_name gin_trgm_ops)
"""
```

- Paginated manager list with country filter + text search
- Manager detail with fund list (2 queries, no ORM relationship)
- Paginated fund list with domicile + type filters + text search
- Fund detail with ticker resolution + manager join
- SEC cross-reference lookup

### Step 2.3 — Create router

Create `backend/app/domains/wealth/routes/esma.py`:

```python
router = APIRouter(prefix="/esma", tags=["esma"])

# 1. GET /esma/managers?country=&search=&page=&page_size=
# 2. GET /esma/managers/{esma_id}
# 3. GET /esma/funds?domicile=&type=&search=&page=&page_size=
# 4. GET /esma/funds/{isin}
# 5. GET /esma/managers/{esma_id}/sec-crossref
```

**Auth:** `Role.INVESTMENT_TEAM` or `Role.ADMIN` on all endpoints.

**Important:** All ESMA tables are **global** (no `organization_id`, no RLS). Use `get_db_session` not `get_db_with_rls`.

**Response pattern:** All endpoints use `response_model=` and return via `model_validate()`.

### Step 2.4 — Register router

Add the ESMA router to the main app router registration (find where other wealth routers are registered, likely in `backend/app/domains/wealth/routes/__init__.py` or main app setup).

---

## Task 3: Tests

### Step 3.1 — Worker tests

Create `backend/tests/workers/test_esma_ingestion.py`:
- Test worker with mocked RegisterService HTTP responses
- Test advisory lock acquisition + release in `finally`
- Test idempotent upsert (run twice, no duplicates)
- Test FK dependency order (managers before funds)

### Step 3.2 — Endpoint tests

Create `backend/tests/routes/test_esma_endpoints.py`:
- Test paginated manager list with country filter
- Test manager detail returns fund list
- Test fund search with text query
- Test fund detail with ticker resolution
- Test SEC cross-reference (matched + unmatched)
- Test auth (non-admin gets 403)
- Test empty results

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/workers/esma_ingestion.py` | New worker file |
| `backend/app/domains/wealth/routes/workers.py` | Add trigger endpoint |
| `backend/app/domains/wealth/schemas/esma.py` | New schemas file |
| `backend/app/domains/wealth/queries/esma_sql.py` | New query builder |
| `backend/app/domains/wealth/routes/esma.py` | New router (5 endpoints) |
| `backend/app/domains/wealth/routes/__init__.py` | Register ESMA router |
| `backend/tests/workers/test_esma_ingestion.py` | New test file |
| `backend/tests/routes/test_esma_endpoints.py` | New test file |

## Acceptance Criteria

- [ ] Worker populates `esma_managers` (~5K managers) and `esma_funds` (~134K funds)
- [ ] Advisory lock 900_019, idempotent via Redis
- [ ] `POST /workers/run-esma-ingestion` returns 202
- [ ] 5 ESMA endpoints functional with pagination
- [ ] Text search uses ILIKE with `_escape_ilike()`
- [ ] Cross-reference endpoint returns SEC CRD when available
- [ ] Auth: `Role.INVESTMENT_TEAM` or `Role.ADMIN`
- [ ] All tests pass, `make check` passes

## Gotchas

- ESMA models may not exist yet in `shared/models.py` — check first. If not, verify migration exists (check `backend/alembic/versions/` for ESMA tables)
- FK dependency: always upsert managers before funds
- ESMA Solr rate limit: 4 req/s — RegisterService should handle this internally
- Lock ID 900_019 — verify it's not taken by grepping `pg_try_advisory_lock` across all workers
- Global tables — no RLS, no `organization_id` filter in queries
- Use `_escape_ilike()` for search to prevent SQL injection via `%` or `_` characters
