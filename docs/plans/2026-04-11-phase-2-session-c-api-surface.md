# Phase 2 Session C — API Surface + Retrofits + Load Test Gate

**Date:** 2026-04-11
**Branch:** `feat/terminal-unification-phase-2-session-c`
**Session scope:** 6 atomic commits shipping the public API surface + sanitization retrofits + load test harness
**Estimated duration:** 2-3 hours of concentrated Opus session
**Prerequisite reading:** `docs/plans/2026-04-11-phase-2-overview.md`
**Depends on:** Sessions 2.A AND 2.B merged to main

## Mission

Close Phase 2 by shipping everything that crosses the backend/frontend boundary:
- Retrofit `construction_run_executor` and `RiskTimeseriesOut` schema through the existing `sanitized.py` infrastructure (no jargon leakage to public API)
- Three new endpoints that Phase 3-6 frontend surfaces will consume
- A `make loadtest` target that proves the screener p95 < 300ms at 50k rows with ELITE filter, and verifies partial-index usage via `EXPLAIN (ANALYZE, BUFFERS)`

Six atomic commits on `feat/terminal-unification-phase-2-session-c`, in this exact order:

1. `refactor(wealth/workers): construction_run_executor retrofit through sanitized.py`
2. `refactor(wealth/schemas): RiskTimeseriesOut retrofit through sanitized.py`
3. `feat(jobs): DELETE /jobs/{id} cancel endpoint with cooperative cancellation`
4. `feat(wealth/routes): GET /model-portfolios/{id}/construction/runs/{runId}/diff`
5. `feat(wealth/routes): GET /dd-reports/queue aggregator`
6. `test(perf): make loadtest target with screener ELITE p95 gate`

After this session, Phase 2 Data Plane is COMPLETE. Phase 3 Screener Fast Path is fully unblocked.

## Project mandate (binding)

See `docs/plans/2026-04-11-phase-2-overview.md` §"Project mandate". For Session 2.C specifically: zero quant jargon may leak to any public endpoint. Every field emitted by construction_run_executor and by `RiskTimeseriesOut` must either be (a) routed through `sanitized.py` mapping, or (b) an explicitly audited exception with rationale in the commit message.

## READ FIRST (mandatory, in this order)

1. `docs/plans/2026-04-11-phase-2-overview.md`
2. `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` — §C.1 confirms `sanitized.py` exists; §C.2 confirms `volatility_garch` + raw regime enums leak via `RiskTimeseriesOut`; §D.2 confirms `construction_run_executor` has ZERO sanitization today
3. `backend/app/domains/wealth/schemas/sanitized.py` — the module you retrofit through. Read it FULLY. Note: `METRIC_LABELS`, `REGIME_LABELS`, Pydantic mixins, humanization helpers
4. `backend/app/domains/wealth/workers/construction_run_executor.py` — the file you retrofit in commit 1. Note: event emission functions, publish_event or similar, raw event type strings
5. `backend/app/domains/wealth/schemas/risk_timeseries.py` — the schema you retrofit in commit 2
6. `backend/app/domains/wealth/routes/risk_timeseries.py` — the route that emits the schema, to understand the full data path
7. `backend/app/core/jobs/` — find the job manager / tracker. Understand the current cancel support (if any) — audit §B.1 says there's no cancel endpoint; there may or may not be cancel support in the manager
8. `backend/app/domains/wealth/routes/model_portfolios.py` — where the `/model-portfolios/{id}/construction/runs/{runId}/diff` endpoint will be added
9. `backend/app/domains/wealth/routes/dd_reports.py` + `long_form_reports.py` — where the aggregator endpoint goes
10. Sessions 2.A + 2.B migration files (0110-0119 or current equivalents) — confirm `mv_construction_run_diff`, `elite_flag`, `event_log` all present
11. `backend/Makefile` — existing `make test` and `make check` targets, to add `make loadtest` in a consistent style
12. `backend/tests/wealth/routes/` — existing route test patterns for commits 3, 4, 5

## Pre-flight checks

```bash
alembic heads  # should show Session 2.B's last migration
make migrate   # apply everything
make test      # baseline green before starting
```

Verify in the local dev DB:
- `event_log` column exists on `portfolio_construction_runs`
- `elite_flag` column exists on `fund_risk_metrics`
- `mv_construction_run_diff` materialized view exists
- `sanitized.py` is importable

If any are missing, prior sessions did not complete — STOP and escalate.

---

# COMMIT 1 — refactor(wealth/workers): construction_run_executor retrofit through sanitized.py

## Problem

Audit §D.2 confirmed `construction_run_executor` emits SSE events with raw internal names (`optimizer_started`, `narrative_started`, etc.) and raw optimizer data (regime enums, CVaR numbers, Sharpe values, etc.) with zero sanitization. This violates the project's "smart backend, dumb frontend" rule. Every event that crosses the wire must be translated through `sanitized.py`'s `METRIC_LABELS` / `REGIME_LABELS` mappings before publish.

Also: commit 1 of Session 2.A added an `event_log JSONB` column — this commit wires `construction_run_executor` to APPEND sanitized events to that column as they fire. Late subscribers (Phase 4 Builder analytics replay) can then read the column directly without needing access to live SSE streams.

## Deliverable

Modify `backend/app/domains/wealth/workers/construction_run_executor.py`:

1. Import the sanitize helpers from `backend.app.domains.wealth.schemas.sanitized`:
   ```python
   from app.domains.wealth.schemas.sanitized import (
       METRIC_LABELS,
       REGIME_LABELS,
       humanize_event_type,  # or whatever the function is named in sanitized.py
   )
   ```
2. Define an `EVENT_TYPE_LABELS` dict that maps raw internal names to public-facing labels:
   ```python
   EVENT_TYPE_LABELS = {
       "optimizer_started": "Optimizer started",
       "narrative_started": "Narrative generation started",
       "solver_phase_completed": "Solver phase completed",
       "stress_test_running": "Stress test in progress",
       "validation_gate_passed": "Validation complete",
       # ... enumerate all event types the worker emits
   }
   ```
3. Wrap the existing event publish function:
   ```python
   def publish_event_sanitized(
       run_id: UUID,
       raw_type: str,
       raw_payload: dict[str, Any],
   ) -> dict[str, Any]:
       """Publish a sanitized event AND append to event_log column.

       - Maps raw_type to a public label via EVENT_TYPE_LABELS
       - Walks raw_payload, replacing any key matching METRIC_LABELS or
         REGIME_LABELS keys with the mapped values
       - Emits via the existing SSE bus
       - Appends to portfolio_construction_runs.event_log via jsonb_set
       """
       public_type = EVENT_TYPE_LABELS.get(raw_type, raw_type)
       public_payload = sanitize_payload(raw_payload)
       event = {
           "seq": next_sequence(),
           "type": public_type,
           "raw_type": raw_type,  # kept for internal diagnostics, not exposed to users
           "ts": datetime.now(tz=UTC).isoformat(),
           "payload": public_payload,
       }
       # 1. Emit via SSE
       sse_bus.publish(f"runs:v1:{run_id}", event)
       # 2. Append to event_log JSONB column
       db.execute(
           """
           UPDATE portfolio_construction_runs
           SET event_log = event_log || :event::jsonb
           WHERE id = :run_id
           """,
           {"event": json.dumps(event), "run_id": run_id},
       )
       return event
   ```
4. Replace every existing `publish_event(...)` call site in the worker with `publish_event_sanitized(...)`. Grep for call sites first, ensure none are missed.
5. The `sanitize_payload` helper walks the dict recursively and replaces:
   - Keys matching `METRIC_LABELS` keys → label
   - Values matching `REGIME_LABELS` keys (e.g., `"RISK_ON"`) → label (e.g., `"Expansion"`)
   - Keeps unknown keys and values as-is

Add the helper to `sanitized.py` if it doesn't exist:

```python
def sanitize_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Walk a payload dict, translating metric names and regime enums to
    public-facing labels. Non-matching keys/values pass through unchanged.
    """
    result: dict[str, Any] = {}
    for key, value in raw.items():
        public_key = METRIC_LABELS.get(key, key)
        if isinstance(value, str) and value in REGIME_LABELS:
            public_value = REGIME_LABELS[value]
        elif isinstance(value, dict):
            public_value = sanitize_payload(value)
        elif isinstance(value, list):
            public_value = [
                sanitize_payload(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            public_value = value
        result[public_key] = public_value
    return result
```

## Verification

1. Unit test: feed a raw payload with known jargon keys (`cvar_95`, `volatility_garch`, `regime=RISK_ON`) → assert output has translated labels + translated regime value
2. Integration test: run a construction job end-to-end, capture SSE stream, grep for banned substrings (`cvar_95`, `DTW`, `RISK_ON`, etc.) — zero matches
3. Read a sample `event_log` from `portfolio_construction_runs` after a test run, verify events are appended
4. `make test` passes

## Commit 1 template

```
refactor(wealth/workers): construction_run_executor retrofit through sanitized.py

Audit §D.2 confirmed construction_run_executor emitted SSE events with
raw internal names and raw optimizer data (regime enums, CVaR numbers,
Sharpe values). Zero sanitization — a direct violation of the project's
smart-backend/dumb-frontend rule.

Wires every event through sanitized.publish_event_sanitized() which:
- Maps raw event types to public labels via EVENT_TYPE_LABELS
- Walks the payload recursively, replacing METRIC_LABELS keys and
  REGIME_LABELS values with public-facing labels
- Emits to the SSE bus (existing behavior preserved)
- Also appends to portfolio_construction_runs.event_log via jsonb_set
  so late subscribers (Phase 4 Builder analytics replay) can read the
  full run history from the database column

sanitize_payload helper added to sanitized.py for recursive payload
walk.

No new module created — consolidated on the existing sanitized.py
infrastructure per audit finding that the module already exists and
is the established source of truth.

Part of Phase 2 Session C — API surface.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — refactor(wealth/schemas): RiskTimeseriesOut retrofit through sanitized.py

## Problem

Audit §C.2 confirmed `RiskTimeseriesOut` in `backend/app/domains/wealth/schemas/risk_timeseries.py` emits `volatility_garch` and raw regime enums (e.g., `RISK_ON`) directly from the regime_prob series without routing through the sanitized layer. Frontend consumers see raw jargon.

## Deliverable

Modify `backend/app/domains/wealth/schemas/risk_timeseries.py`:

1. Import the sanitized Pydantic mixin (or whatever primitive `sanitized.py` provides):
   ```python
   from app.domains.wealth.schemas.sanitized import SanitizedResponseMixin
   ```
2. Make `RiskTimeseriesOut` inherit from the mixin, which translates field names via a model_dump hook or validator
3. Alternative if the mixin pattern doesn't exist: add explicit field aliases via Pydantic `Field(alias="...", serialization_alias="tail_loss_garch")` or similar. The goal is that when Pydantic serializes the model to JSON, the wire format uses public labels, NOT raw field names.

**Critical: the Python-side field names can stay `volatility_garch` for internal consistency. Only the JSON serialization label changes.** This means internal code continues to reference `.volatility_garch` but the HTTP response body shows `"conditional_volatility"` or whatever `METRIC_LABELS["volatility_garch"]` maps to.

4. For the regime_prob series specifically: the values are dicts like `{"RISK_ON": 0.65, "RISK_OFF": 0.35}`. Add a validator or serializer that replaces the enum keys with human labels before emission:
   ```python
   @field_serializer("regime_prob")
   def serialize_regime_prob(self, v: dict[str, float]) -> dict[str, float]:
       return {REGIME_LABELS.get(k, k): prob for k, prob in v.items()}
   ```

Also audit the rest of `risk_timeseries.py` for other raw jargon leakage (Sharpe, CVaR_95, drawdown, etc.) and retrofit all of them in the same commit.

## Verification

1. Unit test: instantiate a `RiskTimeseriesOut` with raw internal values, call `.model_dump()`, assert the JSON output uses sanitized labels
2. Integration test: hit the `/risk-timeseries/{id}` route and assert response body has zero raw jargon
3. `make test` passes
4. Grep the response body for banned substrings: `cvar_95`, `volatility_garch`, `RISK_ON`, `REGIME_`, `DTW`, `dtw_distance` — zero matches

## Commit 2 template

```
refactor(wealth/schemas): RiskTimeseriesOut retrofit through sanitized.py

Audit §C.2 confirmed RiskTimeseriesOut emitted volatility_garch and
raw regime enums (RISK_ON, RISK_OFF, etc.) directly from the regime_prob
series without routing through the sanitized layer.

Inherits from SanitizedResponseMixin (or equivalent) so Pydantic
serialization applies METRIC_LABELS at the JSON boundary. Internal
Python code continues to reference .volatility_garch; only the wire
format changes.

Added field_serializer on regime_prob to translate REGIME enum keys
to human labels (RISK_ON → Expansion, RISK_OFF → Contraction, etc.)
per REGIME_LABELS mapping.

Audited and retrofitted any other raw jargon leaks in the same file.

Unit test asserts model_dump output uses sanitized labels. Integration
test greps the /risk-timeseries/{id} response for zero banned substrings.

Part of Phase 2 Session C — API surface.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 3 — feat(jobs): DELETE /jobs/{id} cancel endpoint with cooperative cancellation

## Problem

Audit §B.1 confirmed no job cancellation endpoint exists. Phase 4 Builder's construction run UI needs to cancel in-flight runs. The endpoint must be cooperative — it sets a cancellation flag that `construction_run_executor` polls, and the executor checks the flag between phases to exit cleanly.

## Deliverable

Two sub-changes in one commit:

### 3A — Cancellation flag infrastructure

In `backend/app/core/jobs/manager.py` (or wherever the job manager lives):

```python
async def request_cancellation(job_id: UUID) -> bool:
    """Mark a job for cancellation. Returns True if the job existed and
    was in a cancellable state, False otherwise.

    Sets cancellation_requested=true in Redis with a key scoped to job_id.
    Cooperative: the job's runner must poll for the flag and exit
    gracefully. No forced termination.
    """
    key = f"job:cancel:{job_id}"
    # Redis SET with 1h TTL — long enough for any reasonable run
    await redis_client.set(key, "1", ex=3600)
    return True


async def is_cancellation_requested(job_id: UUID) -> bool:
    """Called by the job runner between phases to check if cancellation
    was requested. Returns True if the flag is set.
    """
    key = f"job:cancel:{job_id}"
    return (await redis_client.get(key)) is not None
```

### 3B — HTTP endpoint

Add to the existing jobs router (`backend/app/core/jobs/routes.py` or wherever routes live):

```python
@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: UUID,
    actor: Actor = Depends(require_actor),
    db: AsyncSession = Depends(get_db_with_rls),
) -> JSONResponse:
    """Request cancellation of an in-flight job.

    Cooperative cancellation: sets a Redis flag that the job runner
    polls. Returns 202 Accepted immediately. Does NOT guarantee the
    job has stopped — caller should subscribe to the job stream to
    observe the cancellation completing.
    """
    success = await request_cancellation(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or not cancellable")

    # Audit log the cancel request
    await write_audit_event(
        db,
        actor=actor,
        action="job.cancel_requested",
        entity_type="job",
        entity_id=str(job_id),
        changes={"cancellation_requested": True},
    )

    return JSONResponse(
        status_code=202,
        content={
            "job_id": str(job_id),
            "status": "cancellation_requested",
            "message": "Cancellation requested. Subscribe to job stream to observe completion.",
        },
    )
```

### 3C — Wire cooperative polling in construction_run_executor

In `construction_run_executor.py`, add checks at phase boundaries:

```python
async def execute_run(run_id: UUID) -> None:
    # ... existing setup ...
    for phase in OPTIMIZER_PHASES:
        if await is_cancellation_requested(run_id):
            await publish_event_sanitized(run_id, "run_cancelled", {
                "phase": phase.name,
                "reason": "cancellation_requested",
            })
            await mark_run_as_cancelled(run_id)
            return
        await execute_phase(phase)
    # ... existing finalization ...
```

Also add a new status value to `portfolio_construction_runs.status` enum if needed: `cancelled`. If the enum already has it, skip.

## Verification

1. Unit test: request cancellation, assert Redis flag is set
2. Integration test: start a construction run, call DELETE /jobs/{id}, observe the run exits with status=cancelled
3. Unit test: attempt to cancel a non-existent job, assert 404
4. `make test` passes

## Commit 3 template

```
feat(jobs): DELETE /jobs/{id} cancel endpoint with cooperative cancellation

Audit §B.1 confirmed no job cancellation endpoint existed. Phase 4
Builder needs to cancel in-flight construction runs cleanly.

Cooperative cancellation pattern:
- Redis flag set by request_cancellation() with 1h TTL
- Polled by is_cancellation_requested() at construction_run_executor
  phase boundaries
- Executor exits gracefully, publishes run_cancelled event via the
  sanitized pipeline, marks run status as cancelled
- HTTP endpoint returns 202 immediately; caller subscribes to the
  job stream to observe completion

Auditable: every cancel request writes an audit event via
write_audit_event().

Part of Phase 2 Session C — API surface.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 4 — feat(wealth/routes): GET /model-portfolios/{id}/construction/runs/{runId}/diff

## Purpose

Expose the `mv_construction_run_diff` materialized view from Session 2.B via a GET endpoint that Phase 4 Builder's "Compare to previous run" panel will consume.

## Deliverable

In `backend/app/domains/wealth/routes/model_portfolios.py`:

```python
@router.get(
    "/model-portfolios/{portfolio_id}/construction/runs/{run_id}/diff",
    response_model=ConstructionRunDiffOut,
)
async def get_construction_run_diff(
    portfolio_id: UUID,
    run_id: UUID,
    db: AsyncSession = Depends(get_db_with_rls),
) -> ConstructionRunDiffOut:
    """Return weight + metrics deltas between this run and the previous
    run for the same portfolio. Reads from mv_construction_run_diff.
    """
    result = await db.execute(
        """
        SELECT
            portfolio_id,
            run_id,
            previous_run_id,
            weight_delta_jsonb,
            metrics_delta_jsonb,
            status_delta_text
        FROM mv_construction_run_diff
        WHERE portfolio_id = :portfolio_id
          AND run_id = :run_id
        """,
        {"portfolio_id": portfolio_id, "run_id": run_id},
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Diff not found. Run may not have completed or MV needs refresh.",
        )
    return ConstructionRunDiffOut.model_validate(row)
```

Add the response schema in `backend/app/domains/wealth/schemas/construction_run.py` (or equivalent):

```python
class WeightDelta(BaseModel):
    """Single instrument's weight change between runs."""
    from_weight: float = Field(alias="from")
    to_weight: float = Field(alias="to")
    delta: float


class ConstructionRunDiffOut(SanitizedResponseMixin, BaseModel):
    portfolio_id: UUID
    run_id: UUID
    previous_run_id: UUID | None
    weight_delta: dict[str, WeightDelta] = Field(alias="weight_delta_jsonb")
    metrics_delta: dict[str, float] = Field(alias="metrics_delta_jsonb")
    status_delta_text: str

    class Config:
        from_attributes = True
        populate_by_name = True
```

**Note:** `metrics_delta_jsonb` contains the sanitize-mapped keys because sanitize happens at construction_run_executor time (Session C commit 1). So by the time they hit the diff MV, the jargon is already stripped. But belt-and-suspenders: the schema uses `SanitizedResponseMixin` to ensure any residual keys get translated.

## Verification

1. Insert fixture data: portfolio with 2 construction runs, refresh MV
2. Unit test: call the endpoint, assert structure + values
3. Unit test: call with non-existent run_id, assert 404
4. `make test` passes
5. Integration test: run a real construction twice, call the diff endpoint, verify weight_delta_jsonb has correct from/to/delta per instrument

## Commit 4 template

```
feat(wealth/routes): GET /model-portfolios/{id}/construction/runs/{runId}/diff

Exposes mv_construction_run_diff (shipped in Session 2.B commit 4) via
a Phase 4 Builder-ready endpoint. Returns weight and metrics deltas
between the specified run and its previous run for the same portfolio.

Response schema ConstructionRunDiffOut inherits SanitizedResponseMixin
for belt-and-suspenders jargon stripping (primary sanitization happens
at construction_run_executor time via Session 2.C commit 1).

404 if MV has no row for the requested (portfolio_id, run_id) — may
indicate the run is incomplete or the MV needs refresh.

Part of Phase 2 Session C — API surface.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 5 — feat(wealth/routes): GET /dd-reports/queue aggregator

## Purpose

Phase 6 DD Track UI needs a single endpoint that returns the current state of the DD report queue: pending, in-progress, and recently-completed buckets. Audit §B.3 confirmed no aggregator exists.

## Deliverable

In `backend/app/domains/wealth/routes/dd_reports.py`:

```python
@router.get("/dd-reports/queue", response_model=DDReportsQueueOut)
async def get_dd_reports_queue(
    actor: Actor = Depends(require_actor),
    db: AsyncSession = Depends(get_db_with_rls),
    recent_limit: int = 20,
) -> DDReportsQueueOut:
    """Return the DD reports queue state for the authenticated org.

    Three buckets:
    - pending: runs not yet started (queued state)
    - in_progress: runs currently executing (including critic review)
    - completed_recent: last `recent_limit` completed runs (any status),
      sorted by completed_at DESC

    RLS filters by organization_id via the session-scoped context.
    """
    pending_q = select(DDReport).where(DDReport.status == "pending").order_by(DDReport.queued_at)
    in_progress_q = select(DDReport).where(
        DDReport.status.in_(["running", "critic_review"])
    ).order_by(DDReport.started_at)
    completed_q = (
        select(DDReport)
        .where(DDReport.status.in_(["completed", "approved", "rejected"]))
        .order_by(DDReport.completed_at.desc())
        .limit(recent_limit)
    )

    pending = (await db.execute(pending_q)).scalars().all()
    in_progress = (await db.execute(in_progress_q)).scalars().all()
    completed_recent = (await db.execute(completed_q)).scalars().all()

    return DDReportsQueueOut(
        pending=[DDReportSummary.model_validate(r) for r in pending],
        in_progress=[DDReportSummary.model_validate(r) for r in in_progress],
        completed_recent=[DDReportSummary.model_validate(r) for r in completed_recent],
        counts={
            "pending": len(pending),
            "in_progress": len(in_progress),
            "completed_recent": len(completed_recent),
        },
    )
```

Schemas in `backend/app/domains/wealth/schemas/dd_reports.py`:

```python
class DDReportSummary(BaseModel):
    id: UUID
    fund_id: UUID
    fund_label: str
    status: str  # pending | running | critic_review | completed | approved | rejected
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress_pct: int | None  # 0-100
    current_chapter: str | None  # "Chapter 4: Investment Process"

    class Config:
        from_attributes = True


class DDReportsQueueOut(BaseModel):
    pending: list[DDReportSummary]
    in_progress: list[DDReportSummary]
    completed_recent: list[DDReportSummary]
    counts: dict[str, int]
```

**Adjust** the model + schema field names to match the actual `DDReport` / `LongFormReport` ORM entity in `backend/app/domains/wealth/models.py`. If the table is named differently or the status enum values differ, use the actual values. Do not invent.

## Verification

1. Insert fixture data: 3 pending, 2 in-progress, 5 completed
2. Unit test: call the endpoint, assert three buckets have correct counts
3. Integration test: verify RLS filters by org (create another org, its DD reports should not leak)
4. `make test` passes

## Commit 5 template

```
feat(wealth/routes): GET /dd-reports/queue aggregator

Audit §B.3 confirmed no aggregator endpoint existed. Phase 6 DD Track
UI will consume this endpoint to render the queue Kanban (pending /
in_progress / completed_recent columns).

Three buckets:
- pending: status='pending'
- in_progress: status in {running, critic_review}
- completed_recent: status in {completed, approved, rejected},
  sorted by completed_at DESC, limit configurable via query param

RLS filters by authenticated organization. counts dict included for
badge counts without having to count lists client-side.

Part of Phase 2 Session C — API surface.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 6 — test(perf): make loadtest target with screener ELITE p95 gate

## Purpose

Phase 3 Screener's most demanding read is the catalog query with ELITE filter over 9k-50k instruments. Session 2.A's compression fix + Session 2.B's partial index + mv_fund_risk_latest should together push the query below 300ms p95. This commit ships a load test harness that PROVES the target is met and FAILS the gate if the query regresses.

## Deliverable

### 6A — Load test script

Add `backend/tests/loadtest/screener_elite.py` (use `locust` or `k6` — pick based on whatever is already in the repo; default to `locust` if neither). The script:

1. Seeds 50k rows in `fund_risk_metrics` if not already present (or skips if production-shape snapshot is available)
2. Spawns 20 virtual users
3. Each user repeatedly calls `POST /screener/catalog` with the ELITE filter + 3-4 additional dimensional filters
4. Measures p50 / p95 / p99 latency
5. Captures one representative `EXPLAIN (ANALYZE, BUFFERS)` output per unique query shape

Locust example skeleton:

```python
from locust import HttpUser, task, between

class ScreenerEliteUser(HttpUser):
    wait_time = between(0.1, 0.5)
    host = "http://localhost:8000"

    def on_start(self):
        self.client.headers["X-DEV-ACTOR"] = "loadtest@netz.internal"

    @task(3)
    def elite_with_region_filter(self):
        self.client.post(
            "/screener/catalog",
            json={
                "filters": {
                    "elite_only": True,
                    "region": "US",
                    "universe": ["registered_us", "etf"],
                    "aum_min": 100_000_000,
                },
                "sort_by": "composite_score",
                "limit": 50,
                "offset": 0,
            },
        )

    @task(2)
    def elite_with_strategy_filter(self):
        self.client.post(
            "/screener/catalog",
            json={
                "filters": {
                    "elite_only": True,
                    "strategy": ["Large Cap Growth", "Global Macro"],
                },
                "sort_by": "sharpe_1y",
                "limit": 50,
                "offset": 0,
            },
        )
```

### 6B — Make target

Add to `backend/Makefile`:

```makefile
loadtest: ## Run screener ELITE load test with p95 < 300ms gate
	@echo "Running screener ELITE load test..."
	cd backend && locust -f tests/loadtest/screener_elite.py \
		--host http://localhost:8000 \
		--users 20 \
		--spawn-rate 5 \
		--run-time 60s \
		--headless \
		--only-summary \
		--csv=tests/loadtest/results/screener_elite
	@python tests/loadtest/verify_p95.py \
		--csv tests/loadtest/results/screener_elite_stats.csv \
		--threshold-ms 300
```

### 6C — p95 verification script

Add `backend/tests/loadtest/verify_p95.py`:

```python
"""Parse locust CSV output and fail if p95 exceeds the threshold.

Also captures EXPLAIN (ANALYZE, BUFFERS) via a follow-up query and
asserts that the partial index idx_fund_risk_metrics_elite_partial is
used in the plan.
"""
import csv
import sys
from pathlib import Path
import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--threshold-ms", type=int, default=300)
    args = parser.parse_args()

    stats_path = Path(args.csv)
    if not stats_path.exists():
        print(f"ERROR: stats file not found: {stats_path}")
        return 1

    with stats_path.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    p95_max = 0.0
    for row in rows:
        if row.get("Type", "").lower() == "aggregated":
            continue
        p95_str = row.get("95%", row.get("95th Percentile", "0"))
        try:
            p95 = float(p95_str)
        except ValueError:
            continue
        p95_max = max(p95_max, p95)

    print(f"Maximum p95 across endpoints: {p95_max}ms")
    print(f"Threshold: {args.threshold_ms}ms")

    if p95_max > args.threshold_ms:
        print(f"FAIL: p95 {p95_max}ms exceeds threshold {args.threshold_ms}ms")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 6D — Explain plan verification (optional, high-value)

Add a step that runs one of the locust requests, captures `EXPLAIN (ANALYZE, BUFFERS)`, greps the plan for the partial index name:

```python
# In verify_p95.py or a sibling script
def verify_index_usage(db_url: str) -> bool:
    import psycopg
    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        cur.execute("""
            EXPLAIN (ANALYZE, BUFFERS)
            SELECT * FROM mv_fund_risk_latest
            WHERE elite_flag = true
              AND instrument_id IN (
                SELECT id FROM instruments_universe LIMIT 1000
              )
            ORDER BY sharpe_1y DESC NULLS LAST
            LIMIT 50
        """)
        plan = "\n".join(row[0] for row in cur.fetchall())

    if "idx_fund_risk_metrics_elite_partial" in plan or "idx_mv_fund_risk_latest_elite" in plan:
        print("PASS: partial index used")
        return True
    print("FAIL: partial index NOT used")
    print(plan)
    return False
```

## Verification

1. Run `make loadtest` locally against dev DB — should PASS with p95 < 300ms
2. Deliberately regress (disable the partial index temporarily) — `make loadtest` should FAIL
3. Restore the index — PASS again
4. Add `make loadtest` to the CI workflow or document it as a pre-merge manual gate

## Commit 6 template

```
test(perf): make loadtest target with screener ELITE p95 gate

Proves that the physical schema + partial index work from Sessions 2.A
and 2.B deliver the Phase 3 Screener hot path target of p95 < 300ms at
50k rows with the ELITE filter.

Load test harness:
- Locust script at backend/tests/loadtest/screener_elite.py
- 20 virtual users, 60-second run, realistic filter + sort combinations
- Captures p50/p95/p99 per endpoint via CSV
- make loadtest target wraps the run + p95 verification

p95 verification:
- Parses locust CSV output
- Fails with exit 1 if max p95 exceeds 300ms

Index usage verification:
- Runs EXPLAIN (ANALYZE, BUFFERS) on the hot path query
- Greps the plan for idx_fund_risk_metrics_elite_partial or
  idx_mv_fund_risk_latest_elite — fails if neither is used

Phase 2 is now complete. Phase 3 Screener Fast Path can begin
consuming the real data plane.

Part of Phase 2 Session C — final commit.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

After all 6 commits land:

1. `make check` → green
2. `make test` → all tests pass
3. `make loadtest` → PASS with p95 < 300ms, partial index usage confirmed
4. Grep all new routes' responses for banned jargon substrings → zero matches
5. Integration test: run a full construction run, observe SSE events via curl, verify zero raw jargon
6. Verify `portfolio_construction_runs.event_log` is populated on a sample run
7. Verify `/dd-reports/queue` returns three buckets with correct counts
8. Verify `/model-portfolios/{id}/construction/runs/{runId}/diff` returns a row after 2 runs
9. Verify `DELETE /jobs/{id}` cancels an in-flight run cleanly

# SELF-CHECK CHECKLIST

- [ ] Sessions 2.A and 2.B confirmed merged to main before starting
- [ ] Commit 1: construction_run_executor events sanitized, event_log column populated
- [ ] Commit 2: RiskTimeseriesOut response body has zero raw jargon
- [ ] Commit 3: DELETE /jobs/{id} cancels in-flight, cooperative pattern verified
- [ ] Commit 4: diff endpoint returns from mv_construction_run_diff with correct structure
- [ ] Commit 5: dd queue aggregator returns three buckets with RLS
- [ ] Commit 6: make loadtest PASS, partial index usage verified in plan
- [ ] Grep for banned jargon in all new responses: zero matches
- [ ] No files outside Session C scope touched
- [ ] Parallel session files untouched

# VALID ESCAPE HATCHES

1. `sanitized.py` does not have `SanitizedResponseMixin` or equivalent → add the mixin as part of commit 1 (it's a retrofit dependency)
2. Construction run fixture data does not exist in the dev DB → write fixture setup script as part of commit 4 verification
3. `DDReport` model name is different → use actual name, adjust schema/route accordingly
4. locust is not installed → add to `pyproject.toml` as a dev dependency under `[project.optional-dependencies] loadtest = [...]`
5. The partial index is not used because the query planner picks a different strategy → investigate planner statistics, consider ANALYZE hints or index hint extensions
6. p95 > 300ms after all optimizations → STOP and investigate. Do NOT raise the threshold. The threshold is a guarantee, not an aspiration.

# NOT VALID ESCAPE HATCHES

- "Sanitization is too invasive, I'll skip some events" → NO, zero jargon leakage is mandatory
- "I'll skip the EXPLAIN check" → NO, partial index usage is the whole point of Session 2.B's index
- "I'll use an absolute threshold of 500ms to pass" → NO, threshold is 300ms
- "I'll defer the cancel endpoint's cooperative polling to Phase 4" → NO, the cooperative pattern is part of commit 3

# REPORT FORMAT

1. Six commit SHAs with full messages
2. Per commit: file paths, lines added/removed, verification output
3. Commit 1 extra: before/after event capture showing sanitization applied
4. Commit 2 extra: before/after response body showing label translation
5. Commit 3 extra: end-to-end cancel test output
6. Commit 4 extra: sample diff endpoint response with real data
7. Commit 5 extra: sample queue aggregator response
8. Commit 6 extra: FULL locust output + EXPLAIN plan showing partial index usage
9. Full-tree verification checklist results
10. Any escape hatches hit

Phase 2 is complete after this session. Report includes a final "Phase 2 Data Plane Done" summary + handoff to Phase 3 Screener Fast Path.

Begin by confirming Sessions 2.A and 2.B are merged, reading the overview + this brief + audit, then executing commit 1.
