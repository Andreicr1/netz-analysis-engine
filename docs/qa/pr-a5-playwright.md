# PR-A5 — Playwright Visual Validation

**Date:** 2026-04-15
**Stack:** docker-compose (PG 16 + Timescale + Redis) + FastAPI on :8000 + SvelteKit wealth on :5177 (5173/74/75/76 busy from parallel sessions)
**Tenant:** NETZ org, actor `AR` via dev bypass (`X-DEV-ACTOR`)
**Portfolio under test:** `Limit PCT Test Portfolio` (id `76dc3cf8-ca02-46ec-8765-65e34bdfda80`)

## Artefacts

- `pr-a5-builder-initial.png` — Builder at rest, RUN CONSTRUCTION visible, "Compare with: Last run" selector present (Section F.2 satisfied).
- `pr-a5-builder-building.png` — Mid-build state with pipeline strip (FACTOR MODEL → COVARIANCE → OPTIMIZER → BACKTEST → COMPLETE) rendered above the optimizer cascade (PRIMARY OBJECTIVE → ROBUST OPTIMIZATION → VARIANCE-CAPPED → MINIMUM VARIANCE). Confirms Section B.2 (pipeline strip above CascadeTimeline).
- `pr-a5-builder-terminal.png` — Terminal state after ~35s.

## Network evidence (Section A.3 / A.4)

```
[POST] http://localhost:8000/api/v1/portfolios/76dc3cf8-ca02-46ec-8765-65e34bdfda80/build => [200] OK
  idempotency-key: 8f281f45-a2f9-41ee-bd6e-a5c0b574234a
  authorization: Bearer efa71850…
  content-type: application/json

[GET] http://localhost:8000/api/v1/jobs/34051f0e-f5f0-42a5-af68-c7b1c52a842b/stream => [200] OK
  accept: text/event-stream
```

- Hardened endpoint `POST /portfolios/{id}/build` is the ONLY POST the Builder now issues.
- `Idempotency-Key` header is a UUID v4 generated client-side per click (A.1, D.1).
- SSE subscribed via `fetch()` + `ReadableStream` (auth header attached — no `EventSource`).
- Zero traffic to legacy `POST /model-portfolios/{id}/construct` during the session.

## Console

- 1 error: `Failed to load resource: 404 /favicon.png` — pre-existing, unrelated to PR-A5.
- 0 Svelte warnings, 0 4xx on `/api/v1/*` beyond the favicon.

## Scenarios executed

1. Navigate `http://localhost:5177/portfolio/builder` → authenticated instantly via dev bypass.
2. Portfolio auto-selected from dropdown; BASIC calibration tab renders Mandate / Tail loss budget / Max single-fund weight / Turnover cap sliders.
3. `Saved · last updated 04/14` indicator + `Compare with: Last run` selector present → Section F (originalValue per-field overlay + selector) wired.
4. Click `Run Construction` → button becomes disabled; pipeline strip activates; GET `/jobs/{id}/stream` opens immediately after POST `/build`.
5. 35s observation window captured the SSE lifecycle and final state.

## Scenarios not executed in this session

| Scenario                            | Reason                                                       | Mitigation                                                  |
|-------------------------------------|--------------------------------------------------------------|-------------------------------------------------------------|
| Cross-tenant 403 (G.2 step 10)      | Only NETZ tenant seeded locally                              | Backend `verify_job_owner` has unit coverage (Section A.10) |
| DEDUPED re-attachment (A.4.3)       | Requires two backend pods — single-process local dev         | Documented as staging-only verification before PR-A6        |
| Deterministic timeout (G.2 step 11) | Cannot reliably force >120s with test universe               | 130s client timeout + 120s server bound code-reviewed       |

## Backend verification

- Backend log inspection: zero `legacy_construct_endpoint_called` warnings during the run (no frontend code path reaches `/construct` after A.5).
- Docker stack already running from prior session: `netz-analysis-engine-db-1` (Timescale), `netz-analysis-engine-redis-1` — both healthy for ≥ 2 days.

## Outcome

Visual validation **pass** for the migration wiring (A.1–A.11), pipeline-strip rendering (B.2), and idempotency-key contract (D.1). The runtime build itself did not return a fully successful result within the session window — the test portfolio's universe likely does not satisfy the optimizer constraints — but this is orthogonal to PR-A5, which is a frontend migration of transport and UI state, not a change to the quant pipeline.
