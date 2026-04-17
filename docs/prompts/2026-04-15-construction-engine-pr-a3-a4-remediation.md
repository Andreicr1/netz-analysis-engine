# Construction Engine PR-A3 + PR-A4 — Remediation PR

**Date:** 2026-04-15
**Executor:** Opus 4.6 (1M context)
**Branch:** `feat/construction-engine-remediation`
**Base:** current `main` (commit `a58b1a7c` — PR-A3 already merged direct to main; PR-A4 changes uncommitted in working tree)
**Scope:** Single remediation PR consolidating fixes for both PR-A3 (Hybrid Factor Model) and PR-A4 (Job-or-Stream builder). Do NOT proceed to PR-A5 until this PR is merged with `make check` green.

---

## Why this PR exists

PR-A3 was implemented by Gemini and merged directly to `main` (violating branch protocol). PR-A4 was implemented by Gemini in the working tree but has not been committed. A senior architectural audit identified BLOCKER-level defects in both:

- **PR-A3**: protocol violation (no PR/CI), missing audit events, `inputs_metadata` not persisted, `# type: ignore` bypassing mypy, factor cov without EWMA, duplicated DB query, fraudulent type-test, separation-of-concerns gate failed.
- **PR-A4**: cross-tenant SSE disclosure (no `verify_job_owner`), router duplicated, endpoint silently removed, worker is a stub (no real factor/optimizer/persist pipeline), no idempotency, no RBAC, no timeout/cancel/refresh, smoke test patches a function that doesn't exist in the patched module, optimizer↔factor coupling broken.

This PR fixes everything in a single tracked, reviewed, CI-validated unit. **No item below is optional.**

---

## Mandates (non-negotiable)

1. **Brutal honesty on test results.** If a test cannot be made to pass without a shortcut, stop and report — do NOT add `# type: ignore`, do NOT mock around real failures, do NOT skip with `pytest.skip`. The audit found 11 `# type: ignore[type-arg]` in `factor_model_service.py` introduced as "bypass mypy errors" — this is forbidden.
2. **No cost-cutting / no shortcuts.** Andrei's standing mandate (memory `mandate_high_end_no_shortcuts.md`): install whatever deps are needed, iterate as many times as needed, never simplify to make tests pass.
3. **Backend before frontend, infrastructure before visual.** This entire PR is backend. Do not touch frontends.
4. **Never remove endpoints.** `wealth_portfolio_meta_router` was silently dropped from `main.py` — restore it.
5. **DB-first hot path.** Worker must read NAV/factor data from DB (`nav_timeseries`, `macro_data`, `benchmark_nav`); no FRED/Yahoo calls inside the request/worker path beyond what `quant_queries.py` already does.
6. **Smart backend, dumb frontend.** SSE event payloads must be sanitized — no `CVaR`, `kappa`, `eigenvalue`, `shrinkage_lambda` in human-facing `message` field; expose those numbers in a `metrics: {...}` sibling field for the frontend to consume programmatically.
7. **Per CLAUDE.md guardrails (P1–P6)**: Job-or-Stream pattern with 202 + `/jobs/{id}/stream` SSE, `@idempotent` decorator + triple-layer dedup, `zlib.crc32` for advisory lock keys (never `hash()`), `RateLimitedBroadcaster` for fan-out, `ConnectionId` UUID, async-first, `lazy="raise"`, `expire_on_commit=False`, `SET LOCAL` (not `SET`), Pydantic `response_model=` everywhere.

---

## Section A — PR-A3 patches (Hybrid Factor Model)

Reference spec: `docs/prompts/2026-04-14-construction-engine-pr-a3.md`. Read it first.

### A.1 — Audit events for skipped factors (Gate #6)
- File: `backend/app/domains/wealth/services/quant_queries.py` (function `build_fundamental_factor_returns`)
- Replace every `logger.warning("factor %s skipped ...")` with a `write_audit_event(db, action="factor_skipped", entity_type="factor_model", entity_id=block_id, payload={"factor": factor_name, "reason": reason, "ticker": ticker})` call. Keep `logger.warning` for stdout but add the audit row.
- Audit primitives live in `backend/app/core/db/audit.py`.

### A.2 — Persist `inputs_metadata.factor_model` (Spec §7)
- File: `backend/quant_engine/factor_model_service.py` and the `FundLevelInputs` dataclass (find it via grep — `compute_fund_level_inputs` returns it).
- Add fields `inputs_metadata.factor_model`:
  - `k_factors: int = 8`
  - `k_factors_effective: int` (after skipped)
  - `factors_skipped: list[str]`
  - `r_squared_per_fund: dict[fund_id, float]`
  - `kappa_factor_cov: float`
  - `shrinkage_lambda: float | None`
- Add `inputs_metadata.residual_pca`:
  - `n_components: int`
  - `cumulative_variance: list[float]`
  - `top_eigenvalue_share: float`
- Currently `_pca_diag` is computed in `compute_fund_level_inputs` and discarded — wire it into the metadata.
- Do NOT defer to PR-A4 (already deferred and now A4 is also broken).

### A.3 — Separate `PCADiagnostic` from `assemble_factor_covariance` module (Gate #5)
- File: split `backend/quant_engine/factor_model_service.py`:
  - Keep `assemble_factor_covariance`, `fit_fundamental_loadings`, `_apply_ledoit_wolf` in `factor_model_service.py`.
  - Move `PCADiagnostic` dataclass + `compute_residual_pca` to new file `backend/quant_engine/factor_model_pca.py`.
- Update imports in `quant_queries.py` and tests.
- Verify with `grep` that `factor_model_service.py` does NOT import `PCADiagnostic`.

### A.4 — Remove `# type: ignore[type-arg]` (Mandate violation)
- Replace every `np.ndarray  # type: ignore[type-arg]` with `npt.NDArray[np.float64]` (or appropriate dtype).
- Add `import numpy.typing as npt` where needed.
- `make typecheck` must pass with **zero** `# type: ignore` introduced by PR-A3.

### A.5 — Fix fraudulent type test (Gate #5 enforcement)
- File: `backend/tests/quant_engine/test_assemble_factor_covariance_types.py`
- Remove the `# type: ignore` on the call site that should fail.
- Use `from typing_extensions import assert_type` to make the type assertion compile-time enforced.
- The test must FAIL when someone passes `PCADiagnostic` to `assemble_factor_covariance` — verify by temporarily flipping the assertion locally.

### A.6 — EWMA on factor covariance (Spec §3)
- File: `backend/quant_engine/factor_model_service.py`, function `assemble_factor_covariance` (or wherever factor cov is computed).
- Apply EWMA weights `λ=0.97` over 5Y daily factor returns BEFORE LedoitWolf shrinkage. Currently shrinkage is on raw returns.
- Document the weighting in a docstring line.

### A.7 — Deduplicate `build_fundamental_factor_returns` call (Bug)
- File: `backend/app/domains/wealth/services/quant_queries.py:1203` (in `compute_fund_level_inputs` N<20 branch).
- The function is called twice in the same code path. Hoist to a single call before the branch.

### A.8 — Fix import order (Ruff E402)
- File: `backend/app/domains/wealth/services/quant_queries.py:134`
- Move `from backend.quant_engine.factor_model_service import ...` to the top imports block.

### A.9 — Fix `factor_names = []` bug
- File: `backend/quant_engine/factor_model_service.py`, function `fit_fundamental_loadings`.
- The `isinstance(factor_returns, pd.DataFrame)` branch never fires because callers pass `.values`. Either:
  - Change signature to `factor_returns: pd.DataFrame` (preferred — column names are intrinsic), and update callers; OR
  - Add `factor_names: list[str]` as required parameter.
- Update test T1 to assert `factor_names` is non-empty and matches the 8 (or fewer) factor identifiers.

### A.10 — Fix `r_squared` divide-by-zero (Bug)
- File: `backend/quant_engine/factor_model_service.py`
- In `fit_fundamental_loadings`, guard `r_squared = 1 - residual_var / total_var` when `total_var == 0` (constant return series). Return `r_squared = 0.0` explicitly with audit event `factor_fit_degenerate`.

### A.11 — Real end-to-end test (Gate #3)
- File: `backend/tests/quant_engine/test_fundamental_factor_model.py`, test `test_k_equals_six_end_to_end`.
- Remove the `patch("...build_fundamental_factor_returns")`. Use the docker-compose Postgres (`make up`) and seed minimal fixtures via SQL. The test must read from the real `nav_timeseries` / `benchmark_nav` / `allocation_blocks`.
- Mark with `@pytest.mark.integration` if not already; ensure CI runs the integration lane.

### A.12 — `dropna` policy (Bug)
- `factors.dropna()` final discards entire days when any single factor has NaN. Replace with forward-fill ≤2 days then drop, AND emit `factor_data_gap` audit event with the date range dropped.

---

## Section B — PR-A4 patches (Job-or-Stream Builder)

### B.1 — Cross-tenant SSE authorization (BLOCKER SEC-1)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`
- In `GET /jobs/{job_id}/stream`, before `create_job_stream(...)`, call:
  ```python
  if not await verify_job_owner(job_id, str(actor.organization_id)):
      raise HTTPException(status_code=403, detail="Job not found or access denied")
  ```
- Reference canonical implementation: `backend/app/domains/wealth/routes/dd_reports.py:731`.
- Add a test that tenant B receives 403 when streaming tenant A's job.

### B.2 — Idempotency + triple-layer dedup (BLOCKER IDP-1)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`, `POST /portfolios/{id}/build`.
- Decorate with `@idempotent` (find decorator in `backend/app/core/runtime/`).
- Inside the route: acquire `SingleFlightLock` keyed by `f"build:{portfolio_id}"`, AND `pg_advisory_xact_lock(zlib.crc32(f"build:{portfolio_id}".encode()))`. Use `zlib.crc32`, NEVER Python `hash()`.
- Re-POST with same `Idempotency-Key` header within TTL must return the same `job_id` with HTTP 202.
- Test: two concurrent POSTs return the same job_id; only one worker fires.

### B.3 — RBAC (BLOCKER SEC-2)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`, `POST /portfolios/{id}/build`.
- Add `actor: Actor = Depends(require_ic_member)` (mirror `portfolios/__init__.py:207`).

### B.4 — Fix `main.py` router wiring (BLOCKER ROUTE-1, ROUTE-2)
- File: `backend/app/main.py`
- `wealth_portfolios_router` is included twice (lines ~543 and ~556). Remove the duplicate. Keep ONE include.
- `wealth_portfolio_meta_router` is imported but no longer included. Restore the `app.include_router(wealth_portfolio_meta_router, ...)` line.
- Verify by running `python -c "from backend.app.main import app; [print(r.path) for r in app.routes]"` and confirming no duplicate paths and meta router endpoints are present.

### B.5 — Implement the real worker (BLOCKER WORKER-1)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`, function `_build_portfolio_worker`.
- The current implementation is a stub that only emits SSE messages with no real work. Replace with the full pipeline:
  1. **`FACTOR_MODELING`**: load mandate + universe via `quant_queries`. Call `build_fundamental_factor_returns` → `fit_fundamental_loadings`. Emit metrics `{n_factors, n_factors_effective, factors_skipped, r_squared_distribution: {p25, p50, p75}}`.
  2. **`SHRINKAGE`**: call `assemble_factor_covariance` (now EWMA-weighted). Apply Ledoit-Wolf single-index shrinkage. Apply regime multiplier from `regime_service` (RISK_OFF=0.85, CRISIS=0.70). Compute `kappa = np.linalg.cond(cov)`. If `kappa > 1e6`, emit `WARNING` event and fall back to single-index target. Emit metrics `{kappa, shrinkage_lambda, regime, regime_multiplier}`.
  3. **`SOCP_OPTIMIZATION`**: call `optimize_fund_portfolio(cov_matrix=Σ_ready, expected_returns=μ_BL, mandate_constraints=..., lambda_risk=...)` — pass ready-made Σ, NOT `factor_fit`. Run the 4-phase CLARABEL cascade (existing in `optimizer_service.py`). Emit metrics `{phase_used, status, objective, n_iter}`.
  4. **`BACKTESTING`**: call existing stress test with 4 parametric scenarios (GFC, COVID, Taper, Rate Shock) via `stress_service`. Emit metrics `{cvar_95, max_drawdown_pct, scenario_results}`.
  5. **`COMPLETED`**: persist `PortfolioConstructionRun` row with weights + metadata + status. Emit final SSE event with `run_id`.
- Wrap entire worker in `asyncio.wait_for(..., timeout=120)` (matches `construction_run_executor` lock 900_101 contract).
- Between phases, check `is_cancellation_requested(job_id)` and emit `CANCELLED` + early return if true.
- Call `refresh_job_owner_ttl(job_id)` after each phase.
- On any exception: emit `ERROR` event with sanitized message (no stack trace to client; full trace to `logger.exception`), set job status to `failed`, persist failure row.
- All DB writes inside the worker MUST happen in a session opened by `async_session_factory()` with `SET LOCAL app.current_organization_id` set FIRST.

### B.6 — Fix `SET LOCAL` (BLOCKER SQL-1)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`
- `asyncpg` does not bind parameters in `SET LOCAL` (it's a command, not a query). Validate UUID then interpolate:
  ```python
  validated = str(uuid.UUID(org_id))  # raises ValueError on invalid
  await session.execute(text(f"SET LOCAL app.current_organization_id = '{validated}'"))
  ```
- Mirror the canonical pattern in `backend/app/core/middleware.py:103`.

### B.7 — Decouple optimizer from factor model (BLOCKER OPT-1/2/3)
- File: `backend/quant_engine/optimizer_service.py`
- Revert: `optimize_fund_portfolio` does NOT accept `factor_fit`. It accepts `cov_matrix: npt.NDArray[np.float64]` (required, no default).
- Move the import of `assemble_factor_covariance` OUT of `optimizer_service.py` entirely (the worker is now responsible for assembling Σ before calling the optimizer).
- Before `cp.psd_wrap(cov_matrix)`, add:
  ```python
  assert cov_matrix.shape == (len(fund_ids), len(fund_ids)), f"cov_matrix shape mismatch"
  min_eig = float(np.linalg.eigvalsh(cov_matrix).min())
  if min_eig < -1e-10:
      return OptimizationResult(status="psd_violation", weights=None, ...)
  ```

### B.8 — Fix BackgroundTasks lifecycle (RESSALVA BG-1)
- File: `backend/app/domains/wealth/routes/portfolios/builder.py`
- FastAPI `BackgroundTasks` ties worker lifetime to the request — bad for 120s SOCP. Use `asyncio.create_task(_build_portfolio_worker(...))` after the route returns 202. Track in `app.state.active_build_jobs: dict[str, asyncio.Task]` for graceful shutdown cancellation.

### B.9 — Smoke test rewrite (BLOCKER TEST-1, TEST-2)
- File: `backend/tests/wealth/test_builder_sse.py`
- DELETE the patch on `app.main.verify_job_owner` (function does not exist there).
- Patch the correct module: `app.domains.wealth.routes.portfolios.builder.verify_job_owner`.
- Add 5 tests minimum:
  1. **Happy path** (integration, no mock of worker): real Redis from docker-compose, real worker runs against seeded DB fixture, SSE stream yields all 5 phase events + COMPLETED, run row persisted.
  2. **Cross-tenant 403**: tenant B requests stream of tenant A's job → 403.
  3. **Idempotency**: two concurrent POSTs with same `Idempotency-Key` → same `job_id`, single worker run.
  4. **Cancellation**: POST → DELETE `/jobs/{id}` → SSE yields `CANCELLED` event, worker stops within 5s.
  5. **Timeout**: monkeypatch worker phase to sleep 200s → SSE yields `ERROR` event with timeout reason within 130s.

### B.10 — `RateLimitedBroadcaster` + `ConnectionId` (RESSALVA CONN-1, BCAST-1)
- File: `backend/app/core/jobs/sse.py` (or wherever `create_job_stream` lives)
- If not already using `RateLimitedBroadcaster` for fan-out, add it. Confirm `ConnectionId` is a UUID (not `id(ws)`). Add a unit test that 5 concurrent subscribers to the same `job_id` all receive the same events.

---

## Section C — Verification (mandatory before declaring done)

Run all of these locally and paste output in PR description:

```bash
make up                          # docker-compose: Postgres + Timescale + Redis
make migrate                     # alembic upgrade head
make lint                        # ruff check — zero violations
make typecheck                   # mypy — zero new # type: ignore
make architecture                # import-linter — verify A.3 split is honored
make test ARGS="-k factor_model" # PR-A3 unit tests
make test ARGS="-k builder_sse"  # PR-A4 integration tests
make test                        # full suite — must be 3176+ passing
```

**Manual verification:**
1. `grep -rn "# type: ignore" backend/quant_engine/factor_model_service.py backend/quant_engine/factor_model_pca.py` → zero hits.
2. `grep -n "PCADiagnostic" backend/quant_engine/factor_model_service.py` → zero hits.
3. `python -c "from backend.app.main import app; paths = [r.path for r in app.routes]; assert len(paths) == len(set(paths)), 'duplicate routes'"` → no duplicates.
4. `python -c "from backend.app.main import app; paths = [r.path for r in app.routes]; assert any('/portfolios/meta' in p for p in paths), 'meta router missing'"`.
5. Manual SSE smoke: `curl -X POST .../portfolios/{id}/build -H "Authorization: ..."` then `curl -N .../jobs/{job_id}/stream -H "Authorization: ..."` — observe 5 phase events with sanitized messages and structured metrics.

---

## Section D — Deliverables checklist

- [ ] Branch `feat/construction-engine-remediation` created from `main`.
- [ ] All A.1–A.12 patches applied with commits scoped per item.
- [ ] All B.1–B.10 patches applied with commits scoped per item.
- [ ] PR opened with title `fix(wealth): construction engine PR-A3 + PR-A4 remediation`.
- [ ] PR description includes:
  - Link to this remediation prompt.
  - Output of all `make` commands from Section C.
  - Output of the 5 manual verification steps.
  - Explicit confirmation that NO `# type: ignore` was added.
  - Explicit confirmation that NO endpoint was removed.
  - Cross-tenant 403 test output.
- [ ] CI green (GitHub Actions).
- [ ] Self-review by reading the full diff one more time before requesting human review.

---

## Section E — What NOT to do

- Do NOT proceed to PR-A5.
- Do NOT add `# type: ignore` anywhere.
- Do NOT mock the worker in the happy-path integration test.
- Do NOT commit directly to `main` (PR-A3 violated this — do not repeat).
- Do NOT remove any existing endpoint.
- Do NOT call FRED / Yahoo / SEC EDGAR APIs from the worker hot path.
- Do NOT expose CVaR/kappa/eigenvalue jargon in SSE `message` field — sanitize for human reader, expose raw numbers in `metrics` field.
- Do NOT skip a test with `pytest.skip` to make CI green.
- Do NOT add `try/except: pass` to swallow real errors.
- Do NOT use `id(ws)` for connection identification.
- Do NOT use Python `hash()` for advisory lock keys — `zlib.crc32` only.

---

## Reference files

- `backend/quant_engine/factor_model_service.py` (split into 2 files per A.3)
- `backend/quant_engine/factor_model_pca.py` (new, per A.3)
- `backend/quant_engine/optimizer_service.py` (revert A4 changes per B.7)
- `backend/app/domains/wealth/services/quant_queries.py`
- `backend/app/domains/wealth/routes/portfolios/__init__.py`
- `backend/app/domains/wealth/routes/portfolios/builder.py`
- `backend/app/main.py` (lines ~125, ~134, ~543, ~556)
- `backend/app/core/jobs/tracker.py` (reference for `verify_job_owner`, `is_cancellation_requested`, `refresh_job_owner_ttl`)
- `backend/app/core/jobs/sse.py` (reference for `create_job_stream`, `RateLimitedBroadcaster`)
- `backend/app/core/middleware.py:103` (reference for `SET LOCAL` interpolation)
- `backend/app/domains/wealth/routes/dd_reports.py:731` (reference for canonical `verify_job_owner` usage)
- `backend/tests/wealth/test_builder_sse.py` (rewrite per B.9)
- `backend/tests/quant_engine/test_fundamental_factor_model.py` (real end-to-end per A.11)
- `backend/tests/quant_engine/test_assemble_factor_covariance_types.py` (de-fraud per A.5)
- `docs/prompts/2026-04-14-construction-engine-pr-a3.md` (original PR-A3 spec)
- `CLAUDE.md` (Stability Guardrails P1–P6, mandatory patterns §3)

---

**End of remediation prompt. Execute end-to-end. Report back with PR URL + CI status + verification command outputs.**
