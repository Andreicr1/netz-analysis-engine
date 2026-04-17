# PR-A13.1 — Backend `POST /preview-cvar` Endpoint (Live Band Preview)

**Branch:** `feat/pr-a13-1-preview-cvar-endpoint` (cut from `main` at commit `0ccadbc7` post-PR-A13).
**Estimated effort:** ~3h Opus.
**Predecessor:** PR-A13 #194 (static band panel).
**Successor:** PR-A13.2 (frontend wiring of live drag preview into the reserved `previewBand ?? serverBand` channel).

---

## Context

PR-A13 shipped the static band panel. The slider is interactive, the chart renders the last completed run's telemetry, but dragging the slider does NOT update the band until the operator triggers a full construction (~10s, four-phase cascade, stress tests, advisor, validation, narrative).

A13.1 ships a **lightweight preview endpoint** that runs only Phase 1 + Phase 3 of the RU cascade (no stress/advisor/validation/narrative), returns the new `achievable_return_band + min_achievable_cvar + operator_signal` in ~170ms server compute (empirical per A12 smoke: Phase 1 ~80ms + Phase 3 ~90ms). Redis-cached on `(org_id, portfolio_id, universe_hash, cvar_limit)` with a 5-minute TTL so drag-burst drag-back cycles hit cache.

---

## Section A — Endpoint contract

### A.1 Route

**Path:** `POST /api/v1/portfolios/{portfolio_id}/preview-cvar`
**File:** `backend/app/domains/wealth/routes/portfolios/builder.py` (same file as `POST /{id}/build` from PR-A4; new route alongside)
**Auth:** `require_ic_member` (same as `/build` — IC role required)
**Budget:** 3s hard timeout (`asyncio.wait_for`)

### A.2 Request body

```python
class PreviewCvarRequest(BaseModel):
    cvar_limit: float = Field(..., ge=0.0005, le=0.20)
    # Future-proofing: allow overriding strategic allocation mandate without persisting
    mandate: Literal["conservative", "moderate", "growth", "aggressive"] | None = None
```

`cvar_limit` bounds match the slider's `min=0.005, max=0.20` from PR-A13 Section C.2 (slightly wider on the low end for robustness). `mandate` is reserved for future use (A13.2 only sends `cvar_limit`); ignore for now but accept in schema.

### A.3 Response body

```python
class PreviewCvarResponse(BaseModel):
    achievable_return_band: AchievableReturnBandDTO
    min_achievable_cvar: float
    operator_signal: OperatorSignalDTO
    cached: bool  # true if served from Redis
    wall_ms: int


class AchievableReturnBandDTO(BaseModel):
    lower: float
    upper: float
    lower_at_cvar: float
    upper_at_cvar: float


class OperatorSignalDTO(BaseModel):
    kind: Literal["feasible", "cvar_limit_below_universe_floor", "upstream_data_missing", "constraint_polytope_empty"]
    binding: str | None
    message_key: str
```

Schema file: extend `backend/app/domains/wealth/schemas/model_portfolio.py` OR create dedicated `backend/app/domains/wealth/schemas/preview.py`. Pick the cleaner fit; don't over-fragment.

### A.4 Response codes

- `200` — band returned (either from cache or fresh compute)
- `202` — not applicable (sync endpoint, not job-or-stream; operator expects fast response)
- `400` — invalid body (`cvar_limit` outside [0.0005, 0.20])
- `404` — portfolio not found or not owned by caller's org
- `422` — upstream data missing (universe has <2 funds with NAV, no strategic allocation). Body includes `operator_signal.kind="upstream_data_missing"` — frontend renders the empty state
- `504` — `asyncio.wait_for` timeout (3s). Should never happen in practice; log.error if it does.

---

## Section B — Implementation

### B.1 Reuse `compute_fund_level_inputs` + optimizer subset

The heavy lifting that PR-A13.1 must NOT duplicate:

1. Universe load via `_load_universe_funds(db, portfolio_id)` (already exists, `model_portfolios.py`)
2. Layer 3 correlation dedup via `dedup_correlated_funds` (PR-A8)
3. Strategic allocation block bounds via `StrategicAllocation` query
4. `compute_fund_level_inputs(db, fund_ids, mu_prior=..., config=..., portfolio_id=..., profile=...)` — returns FundLevelInputs with mu, cov, returns_scenarios, fund blocks

Once FundLevelInputs is loaded, run **only** the two optimizer LPs:

```python
from quant_engine.optimizer_service import (
    _solve_phase1_ru_max_return,  # verify exact private name post-A12
    _solve_phase3_min_cvar,
)
from quant_engine.ru_cvar_lp import realized_cvar_from_weights
```

Both Phase 1 and Phase 3 were extracted as internal functions in PR-A12. If they're not already module-level callable, refactor ONLY the minimal amount needed to expose them (agent decides: either add thin public helpers `run_phase_1_only(...)` + `run_phase_3_only(...)` in `optimizer_service.py`, OR call through a new `build_preview_band(...)` function that encapsulates both). Prefer the new `build_preview_band(...)` approach — single entry, clean contract:

```python
# backend/quant_engine/optimizer_service.py (NEW public function)
async def build_preview_band(
    fund_ids: list[UUID],
    expected_returns: dict[UUID, float],
    cov_matrix: np.ndarray,
    returns_scenarios: np.ndarray,
    constraints: ActiveConstraints,
    cvar_limit: float,
    cvar_alpha: float = 0.95,
) -> PreviewBandResult:
    """Run only Phase 1 (RU max-return) + Phase 3 (min-CVaR) of the A12 cascade.

    Returns achievable_return_band + min_achievable_cvar + operator_signal
    without stress, advisor, validation, or narrative generation.
    """
```

Internal implementation calls the same RU LP builders used by `optimize_fund_portfolio`, just without Phase 2 robust (skip — not needed for preview) and without the persistence to `portfolio_construction_runs` (preview is ephemeral).

**Result shape:**

```python
@dataclass(frozen=True)
class PreviewBandResult:
    achievable_return_band: dict[str, float]  # {lower, upper, lower_at_cvar, upper_at_cvar}
    min_achievable_cvar: float
    operator_signal: dict[str, Any]  # {kind, binding, message_key}
```

### B.2 Redis caching

Cache key construction:

```python
import zlib

def _preview_cache_key(
    org_id: str,
    portfolio_id: str,
    universe_hash: str,
    cvar_limit: float,
) -> str:
    # cvar_limit quantized to 4-decimal precision (matches column + slider step).
    q_cvar = round(cvar_limit, 4)
    raw = f"{org_id}|{portfolio_id}|{universe_hash}|{q_cvar:.4f}"
    return f"preview_cvar:v1:{zlib.crc32(raw.encode()):08x}"
```

Use `zlib.crc32` per the stability charter (`CLAUDE.md` §3: "Advisory lock keys → zlib.crc32, never Python built-in hash() — non-deterministic across processes").

`universe_hash` is the stable fingerprint of the current dedup'd universe. It exists: `portfolio_construction_runs.universe_fingerprint` is populated by the construction worker. For the preview endpoint, compute it the same way — the function is presumably in `construction_run_executor.py` or a shared helper. Reuse, don't reimplement.

**Cache TTL:** 300s (5 min). Short enough that universe changes mid-session invalidate naturally.

**Cache invalidation:** explicit `DEL preview_cvar:v1:*` pattern invalidation NOT needed for A13.1; TTL handles it. Future PR can add explicit invalidation on universe mutation if profiling shows cache thrashing.

### B.3 Idempotency

Apply `@idempotent` decorator per stability charter § 3:

```python
@router.post("/portfolios/{portfolio_id}/preview-cvar", response_model=PreviewCvarResponse)
@idempotent(
    key=_preview_idempotency_key,  # defined in this file
    ttl_s=60,
    storage=get_idempotency_storage(),
)
async def preview_cvar(
    portfolio_id: str,
    request: PreviewCvarRequest,
    ...
) -> PreviewCvarResponse:
    ...
```

`_preview_idempotency_key` returns a string derived from `(org_id, portfolio_id, cvar_limit_rounded)`. Short TTL (60s) because slider drag naturally produces many distinct cvar_limit values.

### B.4 Single-flight

Apply `SingleFlightLock[str, PreviewCvarResponse]` per `RateLimitedBroadcaster` pattern — prevents thundering-herd when the operator drags the slider through the same value repeatedly. Lock key matches the Redis cache key.

### B.5 Error handling

- If `compute_fund_level_inputs` raises `ValueError` for insufficient data → return 422 with `operator_signal.kind="upstream_data_missing"`, `message_key="universe_too_narrow"`
- If no strategic allocation for profile → 422 with `operator_signal.kind="upstream_data_missing"`, `message_key="no_strategic_allocation"`
- If optimizer raises `IllConditionedCovarianceError` → 422 with `operator_signal.kind="constraint_polytope_empty"`, `message_key="covariance_ill_conditioned"` (rare — κ > 1e6 per A9's threshold)
- If `asyncio.wait_for` hits 3s budget → 504, log structured error with `cvar_limit` + `universe_size`

All error responses still carry the DTO shape — frontend (A13.2) renders the edge-case UX regardless of HTTP status.

---

## Section C — RLS + auth

Same pattern as `POST /{id}/build`:

```python
async def preview_cvar(
    portfolio_id: str,
    request: PreviewCvarRequest,
    actor: Actor = Depends(get_actor),
    _ic: Any = Depends(require_ic_member()),
) -> PreviewCvarResponse:
    org_id = str(actor.organization_id)
    # Validate portfolio UUID, 404 if not found in org
    ...
    async with async_session_factory() as db:
        await _set_rls_org(db, org_id)
        ...
```

No background task. No job_id. No SSE. This is a synchronous REST endpoint.

---

## Section D — Observability

Structured logging:

```python
logger.info(
    "preview_cvar_invoked",
    portfolio_id=portfolio_id,
    cvar_limit=request.cvar_limit,
    cache_hit=cached,
    wall_ms=wall_ms,
    universe_size=universe_size,
    band_width=result.achievable_return_band["upper"] - result.achievable_return_band["lower"],
)
```

Emit a separate `logger.warning("preview_cvar_slow", wall_ms=...)` if `wall_ms > 1000` — helps detect regression to the old multi-phase cascade.

No SSE events. No DB writes (preview is ephemeral, not persisted to `portfolio_construction_runs`).

---

## Section E — Tests

### E.1 Unit tests (`backend/tests/wealth/test_preview_cvar_endpoint.py`)

- `test_preview_feasible`: conservative portfolio, cvar_limit=0.025 → 200, band populated, operator_signal.kind="feasible"
- `test_preview_below_universe_floor`: same portfolio, cvar_limit=0.001 → 200 with `operator_signal.kind="cvar_limit_below_universe_floor"`, band collapses (lower==upper)
- `test_preview_upstream_data_missing`: mock universe with <2 funds → 422 with correct signal kind
- `test_preview_no_strategic_allocation`: mock missing strategic_allocation → 422
- `test_preview_validation_bounds`: cvar_limit=0.0 → 400, cvar_limit=0.5 → 400
- `test_preview_rls`: caller from org A requesting portfolio from org B → 404
- `test_preview_requires_ic_role`: viewer role → 403
- `test_preview_timeout`: monkeypatch optimizer to sleep 5s → 504

### E.2 Cache tests

- `test_cache_hit_second_call`: call twice with same inputs → second returns `cached=true`, wall_ms < 50
- `test_cache_miss_different_cvar`: call with cvar=0.025 then 0.030 → both fresh
- `test_cache_invalidates_on_ttl`: freeze clock, advance 301s, assert miss

### E.3 Integration test (`backend/tests/wealth/test_preview_cvar_integration.py`)

End-to-end against test DB:
- Seed a portfolio identical to Conservative Preservation
- POST to `/preview-cvar` with cvar_limit=0.025
- Assert band.lower ≈ 9.56%, band.upper ≈ 30.62% (± tolerance, matches PR-A12.2 smoke numbers)
- Assert wall_ms < 500

### E.4 Full regression

`pytest backend/tests/wealth/ backend/tests/quant_engine/ -q` — all green, no regressions to PR-A12 cascade.

---

## Section F — Pass criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | Endpoint `POST /api/v1/portfolios/{id}/preview-cvar` exists and responds | manual curl + test |
| 2 | Wall time < 500ms for typical Conservative portfolio | integration test timing |
| 3 | Band numbers match full-cascade output (within 1bp tolerance — Phase 2 robust not run but Phase 1 + Phase 3 are identical) | diff vs stored `cascade_telemetry` from PR-A13 |
| 4 | Cache hit rate > 0 on repeated calls | unit test |
| 5 | All edge cases return correct operator_signal.kind | unit tests |
| 6 | RLS + IC role enforced | unit tests |
| 7 | 3s timeout enforced | unit test with monkeypatched sleep |
| 8 | No writes to `portfolio_construction_runs` | grep assertion + integration test |
| 9 | `pytest backend/tests/wealth/ backend/tests/quant_engine/` green | CI + manual |
| 10 | Live DB manual curl: `curl -X POST http://localhost:8000/api/v1/portfolios/3945cee6.../preview-cvar -H "X-DEV-ACTOR: ..." -d '{"cvar_limit": 0.025}'` returns band in < 500ms | manual |

Per `feedback_dev_first_ci_later.md`: local live-DB curl success is the merge gate.

---

## Section G — Out of scope

- Frontend wiring (PR-A13.2 — debounce + AbortController + two-channel state merge)
- Persistence of preview results (intentionally ephemeral)
- Live preview of stress test scenarios (full cascade responsibility)
- Preview of `min_achievable_cvar` variation across different mandates (A13.2 + future)
- Caching preview results in DB (Redis TTL is sufficient)
- WebSocket streaming of preview (REST is correct for this interaction pattern)
- Admin UI to monitor preview cache hit rates (future observability sprint)
- μ prior calibration (`memory/project_mu_prior_calibration_concern.md` — separate sprint)

---

## Section H — Commit & PR

**Branch:** `feat/pr-a13-1-preview-cvar-endpoint`

**Commit message:**

```
feat(wealth): POST /preview-cvar endpoint for live band preview (PR-A13.1)

Ships a lightweight sync endpoint that returns the achievable_return_band
for a proposed cvar_limit without running the full construction cascade
(skips stress/advisor/validation/narrative). Redis-cached on
(org, portfolio, universe_hash, cvar_limit) with 5min TTL.

Introduces build_preview_band() in optimizer_service.py that encapsulates
Phase 1 (RU max-return) + Phase 3 (min-CVaR) of the A12 cascade. No
persistence to portfolio_construction_runs — preview is ephemeral.

Frontend wiring to debounced slider drag comes in PR-A13.2, which
populates the reserved previewBand state channel in RiskBudgetPanel.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**PR title:** `feat(wealth): POST /preview-cvar endpoint (PR-A13.1)`

**PR body:** include the integration test timing (<500ms), cache hit rate demo, and the diff between preview band vs full-cascade band (should be identical or within 1bp).

---

## Section I — Open decisions for implementer

1. **Extract `build_preview_band` from `optimize_fund_portfolio` or inline duplicate?** — prefer extraction (DRY, single source of truth for Phase 1 + Phase 3 math). If refactor is invasive, inline with a TODO to extract later. **Locked: extraction preferred.**

2. **Schema location** — new `schemas/preview.py` vs extending `schemas/model_portfolio.py`. Prefer new file if it keeps model_portfolio.py under 500 lines; else extend.

3. **Idempotency key** — based on `(org, portfolio, cvar_limit)` alone or include `universe_hash`? Locked: include `universe_hash` so universe mutations invalidate.

4. **Wait-for timeout** — 3s. Alternative is 1.5s more aggressive. Lock 3s for safety margin; revisit after A13.2 shows real drag-latency profile.

5. **Response includes `cached: bool`** — useful for frontend to render "instant" vs "recomputed" subtle affordance, and for telemetry. Lock yes.

---

**End of spec. If `compute_fund_level_inputs` takes > 300ms in preview context (defeating the sub-500ms budget), that's a sign the preview must cache FundLevelInputs separately — flag and propose a second cache layer before proceeding.**
