# Milestone 2.5 — Execution Prompts

Backend-focused prompts for fresh Claude Code sessions. Each is self-contained with all context needed. Frontend work is deferred to UX remediation sprints (see `docs/plans/ux-remediation-plan.md`).

**Goal:** Expose all backend capabilities the UX remediation plan depends on.

---

## Prompt 1: DuckDB Admin API Endpoints — DONE

Completed. 5 endpoints under `/admin/inspect/{org_id}/{vertical}/`, 10 tests, 1363 tests passing.

---

## Prompt 2: Type Hardening — StorageClient + DuckDB Path Integration (half day)

```
Branch: feat/duckdb-data-lake
Task: Fix type signatures in StorageClient.get_duckdb_path() and DuckDBClient._parquet_glob().

Read CLAUDE.md first for critical rules.

### Changes Required

#### 1. StorageClient ABC — Fix type signature
File: `backend/app/services/storage_client.py`

Current (WRONG — uses bare `str` for tier and org_id):
```python
def get_duckdb_path(self, tier: str, org_id: str, vertical: str) -> str:
```

Change to:
```python
def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
```

Add `Literal` to the `typing` import at top of file. Add `from uuid import UUID` if not present.

#### 2. LocalStorageClient — Fix type signature
Same file, `LocalStorageClient.get_duckdb_path()`:

Current:
```python
def get_duckdb_path(self, tier: str, org_id: str, vertical: str) -> str:
    from ai_engine.pipeline.storage_routing import _validate_segment, _validate_vertical
    _validate_segment(org_id, "org_id")
```

Change to:
```python
def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
    from ai_engine.pipeline.storage_routing import _validate_segment, _validate_vertical
    _validate_segment(str(org_id), "org_id")
```

Note: `str(org_id)` because `_validate_segment` expects str. UUID type structurally prevents path injection.

#### 3. DuckDBClient._parquet_glob() — Remove str() conversion
File: `backend/app/services/duckdb_client.py`

Current:
```python
def _parquet_glob(self, org_id: uuid.UUID, vertical: str) -> str:
    base = self._storage.get_duckdb_path("silver", str(org_id), vertical)
    return base + "chunks/*/chunks.parquet"
```

Change to (get_duckdb_path now accepts UUID directly):
```python
def _parquet_glob(self, org_id: uuid.UUID, vertical: str) -> str:
    base = self._storage.get_duckdb_path("silver", org_id, vertical)
    return base + "chunks/*/chunks.parquet"
```

#### 4. Fix all other callers
Grep for `get_duckdb_path(` across backend/. Update any caller still passing `str(org_id)` to pass `org_id` (UUID) directly.

#### 5. Add tests to test_storage_client.py
File: `backend/tests/test_storage_client.py`

Add these test cases (follow existing patterns):

```python
class TestGetDuckdbPath:
    def test_returns_resolved_path(self, tmp_path):
        client = LocalStorageClient(root=tmp_path)
        org_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        path = client.get_duckdb_path("silver", org_id, "credit")
        assert "silver" in path
        assert str(org_id) in path
        assert "credit" in path
        assert path.endswith("/")

    def test_rejects_invalid_vertical(self, tmp_path):
        client = LocalStorageClient(root=tmp_path)
        org_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        with pytest.raises(ValueError, match="Invalid vertical"):
            client.get_duckdb_path("silver", org_id, "hacked")

    def test_all_valid_tiers(self, tmp_path):
        client = LocalStorageClient(root=tmp_path)
        org_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        for tier in ("bronze", "silver", "gold"):
            path = client.get_duckdb_path(tier, org_id, "credit")
            assert tier in path

    def test_base_class_raises_not_implemented(self):
        class StubStorage(StorageClient):
            async def write(self, *a, **kw): pass
            async def read(self, *a, **kw): return b""
            async def exists(self, *a, **kw): return False
            async def delete(self, *a, **kw): pass
            async def list_files(self, *a, **kw): return []
        stub = StubStorage()
        org_id = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        with pytest.raises(NotImplementedError):
            stub.get_duckdb_path("silver", org_id, "credit")
```

### Verification
- Run `make check` (lint + typecheck + test)
- All 1363+ tests must pass
- mypy must accept Literal and UUID types
```

---

## Prompt 3: Wealth Backend Contracts — computed_at + Drift Export (1 day)

```
Branch: feat/wealth-backend-contracts (create from main or current branch)
Task: Add missing backend contract fields required by the UX remediation plan (docs/plans/ux-remediation-plan.md, Section 4 "Structural Dependencies").

Read CLAUDE.md first for critical rules (async-first, response_model, Pydantic schemas, RLS).

### Context

The UX remediation plan identifies backend contract gates that must land BEFORE frontend sprints begin. Most wealth backend contracts are already complete. Two gaps remain:

1. `computed_at` + `next_expected_update` missing from portfolio response schemas
2. Drift history export endpoint missing

### Gap 1: Add computed_at to Portfolio Schemas

**What exists (ALREADY DONE — do not touch):**
- `CVaRStatus` schema in `backend/app/domains/wealth/schemas/risk.py` — has `computed_at` and `next_expected_update`
- `RiskSummaryBatch` schema — has `computed_at`
- `SimulationResult` schema in `schemas/allocation.py` — has `computed_at`
- `FundRiskRead` schema — has `computed_at`

**What's missing:**
File: `backend/app/domains/wealth/schemas/portfolio.py`

1. Add `computed_at: datetime | None = None` to `PortfolioSummary` (the list item schema for `GET /portfolios`)
2. Add `computed_at: datetime | None = None` to `PortfolioSnapshotRead` (the detail schema for `GET /portfolios/{profile}/snapshot`)

Then update the route handlers to populate these fields:

File: `backend/app/domains/wealth/routes/portfolios.py`

- For `PortfolioSummary`: set `computed_at` to the snapshot's `created_at` or `updated_at` timestamp
- For `PortfolioSnapshotRead`: set `computed_at` to the snapshot's `created_at` timestamp

Import `datetime` if not already imported. Use the ORM model's timestamp — never `datetime.now()` on the server.

### Gap 2: Drift History Export Endpoint

**What exists:**
- `GET /analytics/strategy-drift/{instrument_id}/history` — returns `DriftHistoryOut` with events list, supports `from_date`, `to_date`, `severity` filters
- File: `backend/app/domains/wealth/routes/strategy_drift.py` (around line 287-353)
- Model: `StrategyDriftAlert` in `backend/app/domains/wealth/models/strategy_drift_alert.py`
- Schema: `DriftEventOut`, `DriftHistoryOut` in `backend/app/domains/wealth/schemas/strategy_drift.py`

**What to implement:**
Add a new endpoint in the same file:

```python
@router.get(
    "/strategy-drift/{instrument_id}/export",
    summary="Export drift history as CSV or JSON",
)
async def export_drift_history(
    instrument_id: uuid.UUID,
    format: Literal["csv", "json"] = Query("csv"),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    severity: str | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
```

Implementation:
1. Reuse the same query logic from the existing history endpoint (extract into a shared helper if not already)
2. For CSV: use `csv.DictWriter` with `io.StringIO`, return `Response(content=..., media_type="text/csv")` with `Content-Disposition: attachment; filename="drift-history-{instrument_id}.csv"` header
3. For JSON: return `Response(content=json.dumps(...), media_type="application/json")` with download header
4. Include columns: `detected_at`, `status`, `severity`, `anomalous_count`, `metric_details`
5. All queries must include RLS tenant filter (via `get_db_with_rls`)

### Tests

Add tests in `backend/tests/` (follow existing wealth test patterns):

1. Test `computed_at` is present in portfolio summary response
2. Test `computed_at` is present in portfolio snapshot response
3. Test drift export CSV returns valid CSV with correct headers
4. Test drift export JSON returns valid JSON array
5. Test drift export respects date filters
6. Test drift export respects RLS (returns 404 for wrong tenant's instrument)

### Constraints
- All route handlers: `async def` + `AsyncSession` from `get_db_with_rls`
- All responses with Pydantic schema use `response_model=` + `model_validate()`
- CSV/JSON export returns raw `Response` (not Pydantic — binary content)
- Never use `datetime.now()` for `computed_at` — use ORM model timestamps
- Run `make check` before finishing
```

---

## Prompt 4: Credit AI Provenance Endpoints (1-2 days)

```
Branch: feat/credit-ai-provenance (create from main or current branch)
Task: Create 3 new credit endpoints that expose AI classification provenance, memo review timeline, and deal decision audit trail.

Read CLAUDE.md first for critical rules (async-first, response_model, Pydantic schemas, RLS).

### Context

The UX remediation plan (docs/plans/ux-remediation-plan.md) requires Credit AI provenance fields for Sprint 3. The backend has ALL the data but lacks dedicated endpoints to expose it.

**What already exists (do NOT recreate):**
- `DocumentReview` model has: `classification_confidence`, `classification_layer` (1=rules, 2=embeddings, 3=llm), `classification_model`, `routing_basis`
- `ReviewEvent` model (immutable log) — tracks all review state transitions
- `ICMemo` model has: `version` field for version tracking
- `AuditEvent` model — tracks all state changes with `before_state`/`after_state` JSONB
- `Deal` model has stage history tracked via audit events
- Existing endpoint: `GET /funds/{fund_id}/deals/{deal_id}/stage-timeline` — returns stage transitions
- Existing endpoint: `PATCH /funds/{fund_id}/deals/{deal_id}/decision` — writes to audit_events

### What to implement

#### Endpoint 1: Document AI Provenance
```
GET /funds/{fund_id}/deals/{deal_id}/documents/{document_id}/ai-provenance
```

Returns classification decision with full provenance metadata for a document:

Schema `AIProvenanceOut`:
- `document_id: UUID`
- `classification_result: str` — the assigned doc_type
- `classification_confidence: float | None`
- `classification_layer: int | None` — 1=rules, 2=cosine_similarity, 3=LLM
- `classification_layer_label: str | None` — human-readable: "Rule-based", "Embedding similarity", "LLM fallback"
- `classification_model: str | None` — model name if layer 3
- `routing_basis: str | None` — why it was routed to this reviewer
- `embedding_model: str | None` — model used for embeddings
- `embedding_dim: int | None` — dimension of embeddings
- `processed_at: datetime | None` — when classification ran
- `review_count: int` — number of reviews completed
- `current_review_status: str | None` — latest review status

Implementation: Query `DocumentReview` model joined with review events count. Use `selectinload()` for relationships (lazy="raise" enforcement).

#### Endpoint 2: IC Memo Timeline
```
GET /funds/{fund_id}/deals/{deal_id}/ic-memo/timeline
```

Returns all memo versions and review events:

Schema `MemoTimelineOut`:
- `deal_id: UUID`
- `memo_count: int`
- `events: list[MemoTimelineEventOut]`
- `computed_at: datetime`

Schema `MemoTimelineEventOut`:
- `event_type: str` — "memo_created", "memo_updated", "review_submitted", "review_approved", "review_rejected"
- `version: int | None` — memo version number
- `actor_id: str | None`
- `actor_email: str | None`
- `actor_capacity: str | None`
- `rationale: str | None`
- `timestamp: datetime`
- `metadata: dict[str, object] | None` — additional context

Implementation: Query `ICMemo` versions + `ReviewEvent` entries for this deal's memos, merge and sort by timestamp.

#### Endpoint 3: Deal Decision Audit Trail
```
GET /funds/{fund_id}/deals/{deal_id}/decision-audit
```

Returns all state transitions and decisions with full actor context:

Schema `DecisionAuditOut`:
- `deal_id: UUID`
- `events: list[DecisionAuditEventOut]`
- `total_events: int`
- `computed_at: datetime`

Schema `DecisionAuditEventOut`:
- `event_type: str` — "stage_change", "decision", "condition_added", "condition_resolved", "document_reviewed"
- `from_stage: str | None`
- `to_stage: str | None`
- `action: str`
- `actor_id: str | None`
- `actor_email: str | None`
- `actor_capacity: str | None`
- `rationale: str | None`
- `timestamp: datetime`
- `metadata: dict[str, object] | None`

Implementation: Query `AuditEvent` where `entity_type='deal'` and `entity_id=deal_id`, parse `before_state`/`after_state` JSONB to extract stage transitions. Merge with stage-timeline data. Sort chronologically.

### File Organization

Option A (preferred if credit routes use per-module files):
- Create `backend/app/domains/credit/deals/routes/provenance.py` — all 3 endpoints
- Create `backend/app/domains/credit/deals/schemas/provenance.py` — all schemas
- Register router in `backend/app/main.py`

Option B (if credit routes are in a single file):
- Add endpoints to existing `backend/app/domains/credit/deals/routes/deals.py`
- Add schemas to existing `backend/app/domains/credit/deals/schemas/deals.py`

Read the existing file structure first and follow the established pattern.

### Tests

Write tests in `backend/tests/credit/test_provenance.py` (or follow existing test organization):

1. AI provenance returns classification metadata for a reviewed document
2. AI provenance returns 404 for nonexistent document
3. Memo timeline returns events sorted by timestamp
4. Memo timeline returns empty list when no memos exist
5. Decision audit returns stage transitions with actor context
6. Decision audit returns empty list for deal with no decisions
7. All endpoints respect RLS (403/404 for wrong tenant)

### Constraints
- All route handlers: `async def` + `AsyncSession` from `get_db_with_rls`
- All responses: `response_model=` with Pydantic schema + `model_validate()`
- Use `selectinload()`/`joinedload()` for all relationships (lazy="raise" rule)
- Never expose prompt content in responses (Netz IP rule)
- `computed_at` fields use `datetime.now(timezone.utc)` (this is server computation time, not ORM timestamp)
- Run `make check` before finishing
```

---

## Prompt 5: Wealth Batched Risk Summary Endpoint (half day)

```
Branch: feat/wealth-batched-risk (create from main or current branch)
Task: Add a batched risk summary endpoint that returns risk metrics for multiple profiles in a single request.

Read CLAUDE.md first for critical rules.

### Context

The UX remediation plan (docs/plans/ux-remediation-plan.md, Section 2.2 "Wealth freshness and state integrity") identifies that the Wealth dashboard currently makes 10+ parallel API requests to fetch risk data for each profile. This should be consolidated into a single batched endpoint.

**What exists:**
- `GET /risk/{profile}/cvar` — returns `CVaRStatus` for a single profile (includes `computed_at`, `next_expected_update`)
- `RiskSummaryBatch` schema in `backend/app/domains/wealth/schemas/risk.py` — already has `computed_at`
- File: `backend/app/domains/wealth/routes/risk.py`

**What to implement:**

Add a new endpoint:

```python
@router.get(
    "/risk/summary",
    response_model=BatchRiskSummaryOut,
    summary="Batched risk summary for multiple profiles",
)
async def get_risk_summary_batch(
    profiles: str = Query(..., description="Comma-separated profile names"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> BatchRiskSummaryOut:
```

Schema `BatchRiskSummaryOut`:
- `profiles: dict[str, CVaRStatus | None]` — keyed by profile name, None if profile not found
- `computed_at: datetime`
- `profile_count: int`

Implementation:
1. Parse `profiles` query param: split by comma, strip whitespace, validate each against known profiles
2. For each valid profile, fetch CVaR status (reuse existing query logic from the single-profile endpoint)
3. Use `asyncio.gather()` for parallel DB queries (or a single query with `WHERE profile IN (...)`)
4. Return aggregated results keyed by profile name
5. Cap at 20 profiles per request — return 422 if exceeded

### Tests
1. Single profile returns correct CVaR data
2. Multiple profiles returns all results keyed correctly
3. Unknown profile returns None in result (not error)
4. Empty profiles param returns 422
5. More than 20 profiles returns 422
6. All queries respect RLS

### Constraints
- `async def` + `get_db_with_rls`
- `response_model=` with Pydantic schema
- Use `WHERE profile IN (...)` with parameterized query (never string interpolation)
- Prefer single DB query over N parallel queries
- Run `make check` before finishing
```

---

## Prompt 6: Ghost Endpoint Cleanup + Dataroom Deprecation (half day)

```
Branch: chore/endpoint-cleanup (create from main or current branch)
Task: Remove 4 phantom frontend API calls and deprecate 14 dataroom ghost endpoints. No new features.

Read CLAUDE.md first for critical rules.

### Part 1: Remove Phantom Frontend Calls (Wealth)

These are frontend API calls to nonexistent backend endpoints. They fail silently via
Promise.allSettled() but leave blank sections on pages. The SSE-primary risk store
(UX remediation Sprint 1, Wealth.1) will replace this data path.

#### File: `frontends/wealth/src/routes/(team)/funds/[fundId]/+page.server.ts`

Remove these 3 API calls from the load function:
- `GET /funds/{fundId}/stats` — does not exist
- `GET /funds/{fundId}/performance` — does not exist
- `GET /funds/{fundId}/holdings` — does not exist

Remove the corresponding data properties from the return object. If the page component
(`+page.svelte`) references `data.stats`, `data.performance`, or `data.holdings`, remove
those references too — they've always been null.

#### File: `frontends/wealth/src/routes/(team)/analytics/+page.server.ts`

Fix the path mismatch (1-line fix):
- WRONG:  `/wealth/analytics/correlation-regime/{profile}`
- CORRECT: `/analytics/correlation-regime/{profile}`

The backend endpoint exists at `backend/app/domains/wealth/routes/correlation_regime.py`
with prefix `/analytics/correlation-regime`. The `/wealth` prefix is a frontend-side error.

### Part 2: Deprecate Dataroom Ghost Endpoints

14 dataroom endpoints exist but have zero consumers (frontend or backend).
Deprecate them in-place — do NOT delete. Sunset date: 2026-06-30.

#### Files to modify:
- `backend/app/domains/credit/documents/routes/dataroom.py` (or wherever dataroom routes live)

For each route decorator, add `deprecated=True`:
```python
@router.get("/browse", deprecated=True, summary="[DEPRECATED 2026-06-30] ...")
```

Also add a module-level docstring:
```python
"""Dataroom endpoints — DEPRECATED 2026-06-30.
These endpoints predate the modularized document pipeline.
Sunset alongside Fund model routes (SR-4).
No frontend consumers exist. Do not build new integrations against these.
"""
```

If there are two separate files (`/api/dataroom/` and `/api/data-room/`), deprecate both.

### Verification
- Run `make check-all` (backend + all frontends)
- Verify the wealth fund detail page still renders (it should — the removed data was always null)
- Verify the analytics correlation-regime section now loads data (path was wrong before)
- Verify deprecated endpoints still respond (deprecated ≠ removed)
- Check OpenAPI schema (`/docs`) shows deprecated badge on dataroom endpoints
```

---

## Execution Order

| # | Prompt | Effort | Status | Dependency |
|---|--------|--------|--------|------------|
| 1 | DuckDB Admin API | 1-2 days | **DONE** | None |
| 2 | Type Hardening | half day | Ready | None |
| 3 | Wealth Backend Contracts | 1 day | Ready | None |
| 4 | Credit AI Provenance | 1-2 days | Ready | None |
| 5 | Batched Risk Summary | half day | Ready | None |
| 6 | Ghost Endpoint Cleanup | half day | Ready | None |

All prompts are independent — can be executed in any order or in parallel sessions.

After all 6 are complete:
1. Backend exposes all capabilities the UX remediation plan's 4 frontend sprints depend on
2. Run `make types` to regenerate TypeScript types from the updated OpenAPI schema
3. Frontend sprints can begin (see `docs/plans/ux-remediation-plan.md` Section 7)

### Decisions Log (2026-03-18)
- **Phantom fund endpoints** (`/stats`, `/performance`, `/holdings`): remove from frontend, not create backend. SSE-primary store replaces this data path.
- **Correlation-regime path**: fix frontend prefix (`/wealth/analytics/...` → `/analytics/...`), backend is correct.
- **Dataroom ghost endpoints**: deprecate with `deprecated=True` in OpenAPI, sunset 2026-06-30 alongside Fund model routes (SR-4). Do not delete.
