# Phase 4 — Analytics Route Optimization: Pareto → Background Job + Redis Cache

**Status:** Ready
**Estimated scope:** ~200 lines changed
**Risk:** Low (uses existing SSE/Redis infra)

---

## Context

Three analytics endpoints in `backend/app/domains/wealth/routes/analytics.py` run heavy computation synchronously in-request:

| Endpoint | Operation | Latency | Problem |
|---|---|---|---|
| `POST /analytics/backtest` | Walk-forward CV | 30-60s | Blocks request thread |
| `POST /analytics/optimize` | CLARABEL solver | 5-20s | Acceptable for daily use |
| `POST /analytics/optimize/pareto` | NSGA-II Pareto | 45-135s | **Unacceptable** — user waits 2+ min |

**Goal:**
1. Move Pareto optimization to background job with SSE progress polling
2. Add Redis result caching for backtest and optimize (same inputs → same output)

---

## Part A: Pareto → Background Job + SSE

### Step 1: Make Pareto Async

File: `backend/app/domains/wealth/routes/analytics.py`

The current `optimize_pareto()` handler (lines 214-294) runs `optimize_portfolio_pareto()` synchronously. Refactor to:

1. Create a job ID
2. Spawn a background task
3. Return immediately with `job_id` + status `"generating"`
4. Client polls via SSE or GET endpoint

```python
from app.core.jobs.sse import publish_event, create_job_stream, register_job_owner
import uuid as uuid_mod

@router.post(
    "/optimize/pareto",
    response_model=ParetoOptimizeResult,
    status_code=status.HTTP_202_ACCEPTED,  # Changed from 200
    summary="Multi-objective portfolio optimization (Pareto) — async",
)
async def optimize_pareto(
    body: OptimizeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> ParetoOptimizeResult:
    _validate_profile(body.profile)

    today = date.today()
    # ... same allocation fetch logic ...

    cov_matrix, computed_returns = await compute_inputs_from_nav(db, block_ids)
    expected_returns = body.expected_returns if body.expected_returns else computed_returns

    # Generate job ID for SSE tracking
    job_id = str(uuid_mod.uuid4())
    await register_job_owner(job_id, str(actor.organization_id))

    # Snapshot inputs for background task (avoid session leak)
    frozen_block_ids = list(block_ids)
    frozen_returns = list(expected_returns)
    frozen_cov = cov_matrix.tolist()
    frozen_constraints = [
        {"block_id": a.block_id, "min_weight": float(a.min_weight), "max_weight": float(a.max_weight)}
        for a in allocations
    ]
    profile = body.profile

    async def _run_pareto():
        try:
            await publish_event(job_id, "progress", {"stage": "optimizing", "pct": 10})

            constraints = ProfileConstraints(blocks=[
                BlockConstraint(**c) for c in frozen_constraints
            ])
            cov = np.array(frozen_cov)

            result = await optimize_portfolio_pareto(
                block_ids=frozen_block_ids,
                expected_returns=frozen_returns,
                cov_matrix=cov,
                constraints=constraints,
                profile=profile,
                calc_date=today,
            )

            await publish_event(job_id, "complete", {
                "recommended_weights": result.recommended_weights,
                "pareto_sharpe": result.pareto_sharpe,
                "pareto_cvar": result.pareto_cvar,
                "n_solutions": result.n_solutions,
                "seed": result.seed,
                "input_hash": result.input_hash,
                "status": result.status,
            })
        except Exception as e:
            logger.exception("pareto_background_failed", job_id=job_id)
            await publish_event(job_id, "error", {"message": str(e)})

    background_tasks.add_task(_run_pareto)

    # Return immediately with job_id
    return ParetoOptimizeResult(
        profile=profile,
        recommended_weights={},
        pareto_sharpe=None,
        pareto_cvar=None,
        n_solutions=0,
        seed=0,
        input_hash="",
        status="generating",
        job_id=job_id,  # Add to schema
    )
```

### Step 2: Add SSE Stream Endpoint

```python
@router.get("/optimize/pareto/{job_id}/stream")
async def stream_pareto_progress(
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """SSE stream for Pareto optimization progress."""
    return await create_job_stream(request, job_id)
```

### Step 3: Update ParetoOptimizeResult Schema

File: `backend/app/domains/wealth/schemas/analytics.py`

Add `job_id: str | None = None` and `status: str = "completed"` to `ParetoOptimizeResult`.

---

## Part B: Redis Result Cache for Backtest + Optimize

### Step 4: Input Hashing

Create a utility function for deterministic input hashing:

```python
import hashlib
import json

def _hash_analytics_input(
    block_ids: list[str],
    returns: list[float],
    cov_matrix: list[list[float]] | None = None,
    extra: dict | None = None,
) -> str:
    """Deterministic hash of analytics inputs for cache key."""
    payload = {
        "blocks": sorted(block_ids),
        "returns": [round(r, 8) for r in returns],
    }
    if cov_matrix:
        payload["cov"] = [[round(c, 8) for c in row] for row in cov_matrix]
    if extra:
        payload.update(extra)
    encoded = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]
```

### Step 5: Cache Wrapper

File: `backend/app/domains/wealth/routes/analytics.py`

Add Redis cache check before computation:

```python
from app.core.config.settings import settings
import redis.asyncio as aioredis

async def _get_cached_result(cache_key: str) -> dict | None:
    """Check Redis for cached analytics result."""
    try:
        r = aioredis.from_url(settings.redis_url)
        cached = await r.get(f"analytics:cache:{cache_key}")
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    return None

async def _set_cached_result(cache_key: str, result: dict, ttl: int = 3600) -> None:
    """Cache analytics result in Redis (1h TTL)."""
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.set(f"analytics:cache:{cache_key}", json.dumps(result, default=str), ex=ttl)
    except Exception:
        pass
```

In the `optimize()` handler, wrap the computation:

```python
cache_key = _hash_analytics_input(block_ids, expected_returns, cov_matrix.tolist())
cached = await _get_cached_result(cache_key)
if cached:
    return OptimizeResult(**cached)

# ... existing computation ...

# After computation, cache result
await _set_cached_result(cache_key, result_dict)
```

Same pattern for `create_backtest()`.

### Step 6: Cache Invalidation

Cache is automatically invalidated by TTL (1 hour). Since NAV data changes daily (via workers), yesterday's cached results become stale. 1h TTL is conservative — during a session, repeated calls with same parameters return instantly.

Optionally, include `date.today().isoformat()` in the hash to ensure daily invalidation.

---

## Step 7: Tests

- Test Pareto returns 202 with `job_id` and `status="generating"`
- Test SSE stream receives `complete` event
- Test Redis cache hit/miss for optimize
- Test cache key stability (same inputs → same hash)

## Validation

```bash
make check
```

---

## Files to Modify

| File | Action |
|---|---|
| `backend/app/domains/wealth/routes/analytics.py` | Pareto → background task, add cache, add SSE stream endpoint |
| `backend/app/domains/wealth/schemas/analytics.py` | Add `job_id`, `status` to ParetoOptimizeResult |

## Dependencies

- Existing SSE infra: `app.core.jobs.sse` (publish_event, create_job_stream, register_job_owner)
- Existing Redis: `settings.redis_url`
- No new tables or migrations needed
