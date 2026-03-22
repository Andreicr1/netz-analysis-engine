# Phase 4A — Worker Management Dashboard (Admin Frontend)

**Status:** Ready
**Estimated scope:** ~500 lines (backend status endpoint + SSE + admin page)
**Risk:** Medium (requires modifying `_dispatch_worker()` for SSE)
**Prerequisite:** None

---

## Context

15 `POST /workers/run-*` endpoints exist in `backend/app/domains/wealth/routes/workers.py` with zero UI. Operations require manual HTTP calls. The admin frontend exists but has limited pages.

**Current state:** Workers do NOT publish SSE progress events. They run in `BackgroundTasks` with idempotency tracking only.

**Worker registry (all in `workers.py`):**

| Worker | Lock ID | Scope | Frequency |
|--------|---------|-------|-----------|
| macro_ingestion | 43 | global | Daily |
| drift_check | 42 | org | Daily |
| benchmark_ingest | 900_004 | global | Daily |
| risk_calc | 900_007 | org | Daily |
| portfolio_eval | 900_008 | org | Daily |
| instrument_ingestion | 900_010 | org | Daily |
| treasury_ingestion | 900_011 | global | Daily |
| ofr_ingestion | 900_012 | global | Weekly |
| bis_ingestion | 900_014 | global | Quarterly |
| imf_ingestion | 900_015 | global | Quarterly |
| nport_ingestion | 900_018 | global | Weekly |
| esma_ingestion | 900_019 | global | Weekly (Phase 2A) |

---

## Task 1: Backend — Worker Status Endpoint

### Step 1.1 — Worker metadata registry

In `backend/app/domains/wealth/routes/workers.py` (or a new file), define a metadata dict:

```python
WORKER_REGISTRY = {
    "macro-ingestion": {"lock_id": 43, "scope": "global", "frequency": "daily"},
    "drift-check": {"lock_id": 42, "scope": "org", "frequency": "daily"},
    "benchmark-ingest": {"lock_id": 900_004, "scope": "global", "frequency": "daily"},
    # ... all workers
}
```

### Step 1.2 — Status endpoint

Create `GET /admin/workers/status` that returns all worker states + last run metadata:

```python
@router.get("/admin/workers/status", summary="Get all worker statuses")
async def get_all_worker_status(
    db: AsyncSession = Depends(get_db_session),
    _actor: dict = Depends(require_role(Role.ADMIN)),
) -> list[WorkerStatusResponse]:
    """
    Returns status of all workers:
    - Name, lock_id, scope, frequency
    - Last run time (from Redis or DB)
    - Last run status (success/failed)
    - Current advisory lock status (locked/available)
    """
```

**Lock status check:** Query `pg_locks` to check if advisory lock is held:
```sql
SELECT objid FROM pg_locks WHERE locktype = 'advisory' AND objid = :lock_id
```

### Step 1.3 — Schema

```python
class WorkerStatusResponse(BaseModel):
    name: str
    lock_id: int
    scope: str  # "global" | "org"
    frequency: str  # "daily" | "weekly" | "quarterly"
    is_running: bool
    last_run_at: datetime | None = None
    last_run_status: str | None = None  # "success" | "failed" | "timeout"
    last_run_duration_ms: int | None = None
    last_error: str | None = None
```

---

## Task 2: Backend — SSE Progress for Workers

### Step 2.1 — Modify `_dispatch_worker()`

Current `_dispatch_worker()` (lines ~92-100 of `workers.py`) does NOT generate a `job_id`. Modify to:

```python
def _dispatch_worker(bg, name, scope, worker_fn, *, timeout_seconds):
    job_id = str(uuid4())
    # Register job for SSE tracking
    register_job_owner(job_id, org_id=None if scope == "global" else current_org_id)

    async def wrapped():
        try:
            publish_event(job_id, "started", {"worker": name})
            result = await asyncio.wait_for(worker_fn(db), timeout=timeout_seconds)
            publish_terminal_event(job_id, "done", {"worker": name, "result": result})
        except Exception as e:
            publish_terminal_event(job_id, "failed", {"worker": name, "error": str(e)})

    bg.add_task(wrapped)
    return WorkerScheduledResponse(job_id=job_id, worker=name, status="scheduled")
```

**Check existing SSE infrastructure:** Look for `register_job_owner`, `publish_event`, `publish_terminal_event`, `create_job_stream` in the codebase. These should exist in `backend/app/core/jobs/`.

### Step 2.2 — Worker milestone events

Inside each worker function, add `publish_event()` calls at milestones:

```python
publish_event(job_id, "progress", {"pct": 25, "message": "Fetching BIS data..."})
```

**Note:** This is optional for this session — adding SSE events inside each of the 15 workers is substantial. Start with just wrapping `_dispatch_worker()` and add per-worker events incrementally.

### Step 2.3 — SSE stream endpoint

Add `GET /workers/{job_id}/stream` if not already available via the generic job stream:

```python
@router.get("/workers/{job_id}/stream")
async def stream_worker_progress(
    request: Request,
    job_id: str,
    _actor: dict = Depends(require_role(Role.ADMIN)),
):
    return create_job_stream(request, job_id)
```

---

## Task 3: Admin Frontend — Workers Dashboard

### Step 3.1 — Page structure

Create `frontends/admin/src/routes/(admin)/workers/+page.svelte` (verify admin route group):

**Layout (UX Doctrine §21 — Dashboard):**
- Grid of worker cards (3 columns)
- Each card shows: name, lock ID, frequency, last run, status badge, "Run Now" button
- Color coding for states

### Step 3.2 — Worker card states

| State | Badge Color | Meaning |
|-------|-------------|---------|
| idle | neutral | Not running, lock available |
| queued | info | Scheduled but not started |
| running | accent | Currently executing |
| completed | success | Last run succeeded |
| failed | danger | Last run failed |
| timeout | warning | Last run timed out |

**Note:** "Locked" is implementation detail — display as "In Progress (another instance)" if lock is held but no active job.

### Step 3.3 — Run Now action

```svelte
<script>
  async function triggerWorker(workerName: string) {
    const res = await api.post(`/workers/run-${workerName}`);
    if (res.job_id) {
      // Subscribe to SSE for progress
      subscribeToWorkerStream(res.job_id);
    }
    await invalidateAll();
  }
</script>
```

### Step 3.4 — SSE progress subscription

Use `fetch()` + `ReadableStream` (not EventSource — auth headers needed):

```typescript
async function subscribeToWorkerStream(jobId: string) {
  const res = await fetch(`/api/v1/workers/${jobId}/stream`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    // Parse SSE event, update worker card state
  }
}
```

### Step 3.5 — Server load

Create `frontends/admin/src/routes/(admin)/workers/+page.server.ts`:

```typescript
export const load: PageServerLoad = async ({ locals }) => {
  const [statusResult] = await Promise.allSettled([
    locals.api.get('/admin/workers/status')
  ]);
  return {
    workers: statusResult.status === 'fulfilled' ? statusResult.value : [],
  };
};
```

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/domains/wealth/routes/workers.py` | Add WORKER_REGISTRY, modify _dispatch_worker, add SSE stream |
| `backend/app/domains/wealth/schemas/workers.py` | Add WorkerStatusResponse, WorkerScheduledResponse |
| `backend/app/domains/admin/routes/` | Add GET /admin/workers/status (or in wealth routes) |
| `frontends/admin/src/routes/(admin)/workers/+page.server.ts` | New server load |
| `frontends/admin/src/routes/(admin)/workers/+page.svelte` | New dashboard page |

## Acceptance Criteria

- [ ] All 15+ workers displayed as cards with status
- [ ] "Run Now" triggers worker, returns job_id
- [ ] SSE progress stream for active workers
- [ ] Last run history with duration + error messages
- [ ] Advisory lock status visible
- [ ] Role-gated: `ADMIN` only
- [ ] `make check` passes

## Gotchas

- Verify admin frontend route group — might be `(admin)` or different
- `_dispatch_worker()` modification affects ALL worker triggers — test thoroughly
- Check if `register_job_owner`, `publish_event` exist in `backend/app/core/jobs/` — if not, they need to be created first
- SSE: use `fetch()` + `ReadableStream`, NEVER `EventSource`
- Advisory lock status from `pg_locks` is best-effort — race conditions possible
- Adding SSE events inside individual workers is optional for this session — start with the infrastructure
