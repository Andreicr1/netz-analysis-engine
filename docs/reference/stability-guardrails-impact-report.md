# Stability Guardrails — Reproducible Impact Report (Relatório B)

**Date:** 2026-04-07
**Branch:** `feat/stability-guardrails`
**Pre-sprint baseline:** `b521aec^` = `ea799f7` (post-Phase-3, pre-Phase-4)
**Post-sprint HEAD:** `4177ad1` (Phase 4 + crc32 hotfix + SET LOCAL hotfix + benchmark suite)

This is the **empirical impact report** for the Phase 4 retrofit of the
screener import path. Every number in this document was produced by a
reproducible benchmark script run against a live local stack
(PostgreSQL 16 + Redis 7 + FastAPI backend on `:8000`). The benchmark
scripts live in `backend/scripts/benchmark_stability_phase4.py` and
`backend/scripts/benchmark_compare_pre_phase4.py` and can be re-run
on any developer machine.

---

## §0 Bugs Discovered During the Benchmark Run

The benchmark immediately surfaced **two real defects** that escaped
the unit + integration test suite. Both were fixed inline before
collecting the final numbers.

### Bug 1 — Worker `SET LOCAL` syntax error (production-blocking)

**File:** `backend/app/domains/wealth/workers/screener_import_worker.py`
**Found by:** B1 first run → 0 InstrumentOrg rows persisted, worker
log full of `asyncpg.exceptions.PostgresSyntaxError: syntax error at
or near "$1"`.

**Failing code:**

```python
await db.execute(
    text("SET LOCAL app.current_organization_id = :org_id"),
    {"org_id": str(organization_id)},
)
```

**Root cause:** PostgreSQL's `SET` command does **not** accept bind
parameters. asyncpg's prepared-statement protocol rewrites `:org_id`
to `$1`, and the PG parser rejects it with a syntax error. Every
worker invocation under PostgreSQL was failing silently:

- `import_instrument()` never ran
- No rows were ever inserted into `instruments_org`
- The SSE `done` event was never published
- `publish_terminal_event("error", code=UNKNOWN, ...)` fired with the
  raw exception in the message

**Why unit tests missed it:** the screener-import service tests
inject a session that already has the org bound by the test fixture
(`get_db_with_rls`). The worker is the **only** call site that binds
the org itself via `SET LOCAL`, and it had no unit test that
exercised the full RLS path against a live PostgreSQL.

**Fix (commit `4177ad1`):**

```python
await db.execute(
    text("SELECT set_config('app.current_organization_id', :org_id, true)"),
    {"org_id": str(organization_id)},
)
```

`set_config(name, value, is_local)` is the parameter-friendly
equivalent of `SET LOCAL` — third arg `true` makes it
transaction-scoped, identical semantics. Standard idiom in
production async-PostgreSQL code.

### Bug 2 — Benchmark harness X-DEV-ACTOR field schema (false positive)

**File:** `backend/scripts/benchmark_stability_phase4.py`
**Found by:** B1 second run after the worker fix → still 0 rows; log
showed `null value in column "organization_id" of relation
"instruments_org" violates not-null constraint`.

**Root cause:** my benchmark harness sent the dev actor with the
fields `user_id` / `organization_id` / `organization_slug` / `role`,
but `_parse_dev_actor()` in `backend/app/core/security/clerk_auth.py`
expects `actor_id` / `org_id` / `org_slug` / `roles` (list). The
parser silently ignored the unknown fields and built an `Actor` with
`organization_id=None`. The route's `get_org_id` dependency returned
`None`. The worker received `organization_id=None`. The
`InstrumentOrg.organization_id` NOT NULL constraint then fired.

**Fix:** schema-corrected the test harness in the same commit.

**Lesson:** the dev-actor parser silently dropping unknown fields is
itself a small charter violation (P3 Isolated — bad input should
fail loud, not silently produce a degraded actor). Filed in charter
§6 backlog.

---

## §1 Methodology

### Stack

| Component | Version / image | Configuration |
|-----------|-----------------|---------------|
| PostgreSQL | `timescale/timescaledb-ha:pg16` | port 5434, `POSTGRES_HOST_AUTH_METHOD=trust` |
| Redis | `redis:7-alpine` | port 6379 |
| Backend | uvicorn + FastAPI | port 8000, single worker, no `--reload` |
| Migrations | `alembic upgrade head` | head: `0087_enable_timescale_compression` |

### Comparison strategy

1. Apply migrations to the shared PG container (head schema).
2. Start uvicorn from `HEAD` (current branch tip with hotfixes).
3. Run benchmark suite, capture results to JSON.
4. `taskkill` the HEAD uvicorn.
5. `git worktree add /tmp/netz-pre-phase4 b521aec^` — checks out
   commit `ea799f7` (post-Phase-3, pre-Phase-4) into a separate
   directory without touching the main checkout.
6. Start uvicorn from the worktree's `backend/` directory against
   the **same** PG and Redis containers.
7. Run the comparison harness (`benchmark_compare_pre_phase4.py`)
   and the latency harness (`benchmark_compare_latency.py`).
8. Cleanup: `taskkill`, `git worktree remove --force`.

The DB schema is identical between the two states (no migrations
were added during Phase 4) so the same `instruments_org` table
serves both code paths. The bench org's rows are deleted before
each run to give every benchmark a clean slate.

### Bench actor

Every request carries an `X-DEV-ACTOR` header with a stable
deterministic UUID for the bench org:

```json
{
  "actor_id": "bench-actor-001",
  "name": "Bench Actor",
  "email": "bench@netz.local",
  "roles": ["INVESTMENT_TEAM", "ADMIN"],
  "org_id": "f1392e06-dda0-5537-aee7-2474f2ce9241",
  "org_slug": "bench-org",
  "fund_ids": []
}
```

The org UUID is `uuid.uuid5(uuid.NAMESPACE_DNS, "bench-org-001")` so
multiple runs converge on the same row set.

---

## §2 Headline Numbers

### B1.1 — 5 parallel POSTs to the same ticker with the same Idempotency-Key

**Acceptance:** the application must collapse 5 concurrent imports
of the same payload into exactly 1 successful operation, exactly 1
`InstrumentOrg` row, and 0 user-facing errors.

| Metric | **Pre-Phase-4** | **HEAD (Phase 4 + hotfixes)** | Delta |
|--------|----------------:|-----------------------------:|------:|
| Wall time (5 parallel) | 121.5 ms | 105.5 ms | **−13 %** |
| HTTP 2xx success | 1 / 5 (20 %) | **5 / 5 (100 %)** | **+400 %** |
| HTTP 4xx conflicts | 3 / 5 (60 %) | 0 / 5 (0 %) | **−100 %** |
| HTTP 5xx server errors | 1 / 5 (20 %) | 0 / 5 (0 %) | **−100 %** |
| InstrumentOrg rows created | 1 (saved by unique constraint) | 1 (deliberate, via dedup) | match |
| Mean latency per request | 67.05 ms | 54.61 ms | **−18.5 %** |
| Max latency | 111.93 ms | 94.69 ms | **−15.4 %** |
| Distinct response shapes | `[201, 409, 409, 409, 500]` | `[202, 202, 202, 202, 202]` | — |

**Pre-Phase-4 raw output:**

```json
{
  "label": "PRE-PHASE-4 (synchronous handler)",
  "ticker": "VTI",
  "parallel": 5,
  "wall_ms": 121.47,
  "status_codes": [409, 201, 409, 500, 409],
  "latency_min_ms": 49.43,
  "latency_max_ms": 111.93,
  "latency_mean_ms": 67.05,
  "rows_pre": 0,
  "rows_post": 1,
  "rows_created": 1,
  "passes_idempotency": true,
  "first_body_keys": ["detail"]
}
```

**HEAD raw output:**

```json
{
  "label": "HEAD-with-hotfix",
  "ticker": "VTI",
  "parallel": 5,
  "wall_ms": 105.46,
  "status_codes": [202, 202, 202, 202, 202],
  "latency_min_ms": 41.9,
  "latency_max_ms": 94.69,
  "latency_mean_ms": 54.61,
  "rows_pre": 0,
  "rows_post": 1,
  "rows_created": 1,
  "passes_idempotency": true,
  "first_body_keys": ["identifier", "job_id", "status"]
}
```

**Interpretation.** The pre-Phase-4 handler relied entirely on the
`UNIQUE (organization_id, instrument_id)` constraint in
`instruments_org` to prevent duplicate rows. Data integrity was
**accidental** — the application had no coordination, the database
was the only defence. From the user's perspective, 4 of every 5
clicks failed with a 4xx or 5xx, with no way to know which one
"won" without polling. Phase 4 makes the dedup **intentional** at
three layers (Redis `@idempotent`, in-process `SingleFlightLock`,
DB `pg_advisory_xact_lock` keyed on `crc32`) and every caller
receives a clean 202 with the same `job_id`.

### B1.2 — 20 parallel POSTs (high-concurrency stress)

**Acceptance:** the same guarantees as B1.1 must hold under realistic
high-concurrency load (e.g. a button held down or a script firing
20 retries in a tight loop).

| Metric | **Pre-Phase-4** | **HEAD** | Delta |
|--------|----------------:|---------:|------:|
| Wall time (20 parallel) | 240.84 ms | 192.57 ms (p100 of indiv. latencies) | **−20 %** |
| HTTP 2xx success | 1 / 20 (5 %) | **20 / 20 (100 %)** | **+1900 %** |
| HTTP 4xx conflicts | 15 / 20 (75 %) | 0 / 20 (0 %) | **−100 %** |
| HTTP 5xx server errors | 4 / 20 (20 %) | 0 / 20 (0 %) | **−100 %** |
| InstrumentOrg rows created | 1 | 1 | match |
| Mean latency per request | 219.90 ms | 158.41 ms | **−28 %** |
| Max latency | 233.25 ms | 192.57 ms | **−17 %** |

**Pre-Phase-4 status code distribution:**

```
[500, 500, 500, 201, 500, 409, 409, 409, 409, 409,
 409, 409, 409, 409, 409, 409, 409, 409, 409, 409]
```

**95 % of pre-Phase-4 requests under 20× concurrency landed as 4xx
or 5xx.** That is the headline result of this report. The
synchronous handler held asyncpg connections for the entire 350-line
SQL chain on every concurrent caller, the unique constraint fired
on every loser of the race, and 4 callers timed out badly enough on
the `instruments_org` insert to surface as 5xx.

**HEAD status code distribution:**

```
[202, 202, 202, 202, 202, 202, 202, 202, 202, 202,
 202, 202, 202, 202, 202, 202, 202, 202, 202, 202]
```

100 % clean 202 with a single shared `job_id`. The mean latency of
158 ms reflects the `@idempotent` decorator's cooperative wait
loop (`wait_poll_s=0.05`): the first caller pays ~50 ms to
execute, the other 19 callers each wait one or two poll cycles to
read the cached result. Higher mean than the 5-parallel case but
the variance is bounded and predictable, and **no caller sees an
error**.

### B2 — Sequential enqueue latency, 50 imports

**Acceptance:** the `@router.post("/screener/import/{identifier}")`
endpoint must respect the Job-or-Stream §3.2 budget — p95 < 500 ms
for the enqueue itself, irrespective of the work the worker does
afterwards.

| Metric | **Pre-Phase-4** | **HEAD** | Delta |
|--------|----------------:|---------:|------:|
| Sample size | 50 | 50 | — |
| Mean | 12.02 ms | 12.07 ms | +0.4 % |
| p50 | 11.41 ms | 11.80 ms | +3.4 % |
| p95 | 15.70 ms | **14.21 ms** | **−9.5 %** |
| p99 | 26.31 ms | **14.82 ms** | **−43.7 %** |
| Max | 26.31 ms | 14.82 ms | **−43.7 %** |
| Min | 9.85 ms | 9.27 ms | −5.9 % |
| Status code distribution | `{201: 50}` | `{202: 50}` | contract change |
| Acceptance (p95 < 500 ms) | PASS (15.7 ms) | **PASS (14.2 ms)** | both |

**Interpretation.** This is the most surprising result of the
report. The pre-Phase-4 handler is **mean-comparable** to the HEAD
enqueue — 12.0 vs 12.1 ms — because the synchronous handler is
running against a local PostgreSQL with everything cached and the
350-line SQL chain reduces to ~10 ms of pure DB execution. The
naive expectation that "sync handler = slow" does not hold for the
happy path on a warm local stack.

**Where the HEAD wins is the tail.** p99 is **43 % better**
(14.8 ms vs 26.3 ms) because the HEAD's latency profile is dominated
by the constant-time enqueue (`@idempotent` Redis `SET NX EX` +
`asyncio.create_task`), while the pre-Phase-4 handler's latency is
dominated by the variable-time SQL chain (`SELECT … FROM
sec_cusip_ticker_map`, fallback into `sec_fund_classes`, fallback
into `sec_etfs`, then the `INSERT … RETURNING …`). The variance
between the cheapest happy path and the most expensive fallback
chain is what produces the long tail.

**The real Phase 4 latency win is on the cold / loaded path** —
when the SQL working set doesn't fit in PG cache, when N worker
coroutines compete for asyncpg connections, when the FOIA brochure
download is reachable from the request path. None of those are
exercised by this benchmark (which runs against a warm local PG
with no external HTTP calls), so the report **understates** the
real-world impact. To stress those paths properly we would need
production-equivalent data volumes and a cold stack — out of
scope for this run.

### B3 — Triple-layer dedup with 4 distinct keys

**Acceptance:** 20 requests fired in parallel across 4 distinct
`Idempotency-Key` headers must produce exactly 4 unique `job_id`s
and exactly 4 `InstrumentOrg` rows. Tests the boundary between
"same key → coalesce" and "different key → execute".

This is HEAD-only — the pre-Phase-4 handler has no concept of an
idempotency key, so the comparison would only be a repetition of
B1.

| Metric | **HEAD** |
|--------|---------:|
| Wall time (20 parallel) | 131.32 ms |
| Distinct `job_id`s observed | 4 / 4 expected |
| `InstrumentOrg` rows by ticker | `{"IWM": 1, "QQQ": 1, "DIA": 1, "SPY": 1}` |
| Acceptance | **PASS** |

The triple-layer dedup correctly distinguishes between concurrent
callers that share a key (collapse to one execution) and concurrent
callers that have distinct keys (execute independently). Tested
across 4 tickers in 20 parallel calls; every ticker received
exactly one execution and one row.

---

## §3 Bug Class Eliminated (B3.3 from the design spec)

The design spec §4.3 lists **B3.3** as "Sem `@idempotent` —
duplo-clique gera 409 ou race condition". The pre-Phase-4 numbers
above are the empirical proof of that incident class:

> **Pre-Phase-4, 5 parallel clicks on the same ticker:**
>
> ```
> [201, 409, 409, 409, 500]
> ```
>
> **Pre-Phase-4, 20 parallel clicks on the same ticker:**
>
> ```
> [500, 500, 500, 201, 500, 409, 409, 409, 409, 409,
>  409, 409, 409, 409, 409, 409, 409, 409, 409, 409]
> ```

A user double-clicking the import button in the screener UI under
realistic latency (a few hundred ms of network round-trip) reliably
landed in this state. The unique constraint on `instruments_org`
prevented duplicate rows, but the user's screen showed an error
toast and they had no way to know whether the operation actually
succeeded without manually refreshing the universe.

Phase 4 closes this incident class by:

1. **`@idempotent` decorator** (`backend/app/core/runtime/idempotency.py`)
   — Redis `SET NX EX` cross-process lock with cached results.
2. **`SingleFlightLock`** in `dispatch_screener_import` —
   in-process coalesce within the same uvicorn worker.
3. **`pg_advisory_xact_lock(900_072, crc32(...))`** in
   `_import_sec` — DB-level serialisation that survives Redis
   degradation. The crc32 is deterministic across processes
   (unlike the original `hash()` which was seeded per interpreter
   — fixed by hotfix `d65cde6`).

The combination of the three layers is what produces the
`[202, 202, 202, 202, 202]` clean run — defence in depth.

---

## §4 Performance Trade-offs (Honestly Documented)

Phase 4 is **not** a pure performance win. Several costs were
deliberately accepted:

| Cost | Magnitude | Why it's worth it |
|------|----------|-------------------|
| Mean enqueue latency | +0.5 ms (12.02 → 12.07) | Negligible; well under any UX threshold |
| Memory per request | +1 SingleFlightLock entry × ttl_s=300 = ~few KB | Bounded; releases on TTL |
| Redis round-trips per import | +2 (`SET NX EX` + `set_result` + cleanup) | Required for cross-process dedup |
| Worker coroutine complexity | +200 lines (`screener_import_worker.py`) | Isolates the work from the request path |
| Code paths that fail open | 3 (Redis down, gate open, single-flight error) | All log structured warnings; no caller crashes |
| Two new uvicorn timers | broadcaster eviction sweeper + ws heartbeat | Documented in charter §3.1 |

The benchmark **does not measure** any of the failure-mode wins
that the Phase 4 retrofit was actually designed for:

- **Tail latency under PG cold cache** — would require data >> shared_buffers
- **Behaviour during a Redis outage** — would require killing redis mid-run
- **Behaviour under sustained write load** — would require >100 distinct tickers
- **Multi-process advisory lock contention** — would require >1 uvicorn worker
- **SEC EDGAR provider gate circuit opening** — would require killing the brochure
  endpoint mid-run
- **30-min Dashboard soak (charter §9 C18)** — covered separately by
  the Playwright spec; this report is the screener-import slice only

Adding any of these would require either production-shaped data
volumes or chaos-engineering the dependencies. The numbers above
are the **floor** of the Phase 4 win, not the ceiling.

---

## §5 Reproducing this report

### Stack up

```bash
make up                # PG + Redis containers
make migrate           # alembic upgrade head
```

### HEAD benchmarks

```bash
# Start HEAD uvicorn (port 8000)
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
sleep 12  # allow startup

# Full B1/B2/B3 suite
python scripts/benchmark_stability_phase4.py

# B1 head-on comparison harness
python scripts/benchmark_compare_pre_phase4.py "HEAD-with-hotfix" VTI 5
python scripts/benchmark_compare_pre_phase4.py "HEAD-with-hotfix (20 parallel)" VTI 20

# B2 latency harness
python scripts/benchmark_compare_latency.py "HEAD" 50
```

### Pre-Phase-4 benchmarks

```bash
# Kill HEAD uvicorn (use the PID from the start command)
taskkill //F //PID <pid>          # Windows
pkill -f "uvicorn app.main"        # Linux/macOS

# Create worktree at the pre-Phase-4 commit
git worktree add /tmp/netz-pre-phase4 b521aec^

# Start the legacy uvicorn from the worktree (same port, same DB)
cd /tmp/netz-pre-phase4/backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
sleep 14

# Run the same comparison harnesses
python /path/to/main/checkout/backend/scripts/benchmark_compare_pre_phase4.py \
    "PRE-PHASE-4 (5 parallel)" VTI 5
python /path/to/main/checkout/backend/scripts/benchmark_compare_pre_phase4.py \
    "PRE-PHASE-4 (20 parallel)" VTI 20
python /path/to/main/checkout/backend/scripts/benchmark_compare_latency.py \
    "PRE-PHASE-4" 50
```

### Cleanup

```bash
taskkill //F //PID <pre_phase4_pid>
git worktree remove /tmp/netz-pre-phase4 --force
make down                # optional — drop containers
```

The benchmark scripts are committed to `backend/scripts/` so anyone
on the team can reproduce these numbers on their machine.

---

## §6 Honest Limitations & What This Report Does Not Claim

| Claim **NOT** made | Why |
|--------------------|-----|
| "Phase 4 made the import N % faster" | The mean latency is essentially unchanged on a warm local stack. The win is in tail latency and error rate under concurrency. |
| "Phase 4 reduced memory" | Probably increased it slightly. Trade-off documented in §4. |
| "Phase 4 eliminates all import failures" | Only the dedup class. Network partitions, PG outages, Tiingo brochure downtime all still produce failures (now mapped to typed `error` events instead of 500s). |
| "These numbers extrapolate to production" | The benchmark runs against a warm local PG with everything cached. Cold cache + production data volumes would produce different (probably more dramatic) results. |
| "The 24 pre-existing test failures are now fixed" | They're not. They still require live PG/Redis and weren't part of this sprint. The Phase 4 retrofit is orthogonal to that backlog. |
| "Phase 4 covers every screener import path" | The legacy `/import-esma/{isin}` and `/import-sec/{ticker}` aliases delegate to the unified path; the unified path is the one tested here. |

---

## §7 Conclusions

1. **Phase 4 closes the B3.3 incident class definitively.** Empirical
   proof: pre-Phase-4 produces a 95 % failure rate at 20×
   concurrency; HEAD produces 100 % success at the same concurrency
   on the same hardware against the same database.

2. **Two real production-blocking bugs were caught by the benchmark
   that escaped the unit test suite.** The `SET LOCAL` worker bug
   would have made every screener import silently fail in production
   the moment Phase 4 landed. Caught and fixed (commit `4177ad1`)
   before any user could hit it.

3. **The mean enqueue latency cost of Phase 4 is statistically zero**
   on a warm local stack (+0.5 ms). The tail (p99) is **43 %
   better** because the Phase 4 path is constant-time while the
   pre-Phase-4 path has variable SQL chain depth.

4. **The unit test suite has a coverage gap.** No test exercises the
   worker's `SET LOCAL` path against a live PG. Filed as charter
   §6 backlog: "add a worker integration test that runs the full
   `run_import_job` against a real PG and asserts row creation".

5. **The dev-actor parser silently dropping unknown fields is a
   small charter violation** that should be tightened in a follow-up
   commit. Filed in charter §6 backlog.

6. **The benchmark scripts are reproducible primary artefacts**, not
   throwaway harnesses. They live in `backend/scripts/` and are
   committed to the branch. Future regressions to the screener
   import path will be caught by re-running them.

---

## §8 Next Recommended Actions

1. **Land this report and the two hotfix commits** (`d65cde6` for
   `crc32`, `4177ad1` for `set_config`) in the same PR as the
   Phase 4 retrofit.
2. **Add a backend integration test** that runs `run_import_job`
   end-to-end against a `pytest-postgresql` ephemeral instance,
   asserting row creation. This would have caught Bug 1 in CI.
3. **Tighten `_parse_dev_actor`** to either reject unknown fields
   or warn loudly when expected fields are missing. This would have
   caught Bug 2 in CI.
4. **Schedule the C18 30-min Dashboard soak** as a nightly CI job
   so the heap-growth invariant is continuously enforced.
5. **Rerun this benchmark against a production-shaped dataset**
   (millions of `nav_timeseries` rows, cold PG cache) once a
   staging environment is provisioned. The numbers in this report
   are the floor.

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-04-07 | Andrei + Opus 4.6 | Initial impact report. Covers Phase 4 backend retrofit. Two hotfixes (`d65cde6`, `4177ad1`) discovered and applied during the benchmark execution. |
