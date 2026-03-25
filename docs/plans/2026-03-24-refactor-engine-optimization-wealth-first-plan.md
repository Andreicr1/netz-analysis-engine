---
title: "refactor: Engine Optimization — Wealth-First"
type: refactor
status: active
date: 2026-03-24
origin: docs/brainstorms/2026-03-24-engine-optimization-opportunities-brainstorm.md
deepened: 2026-03-24
---

# Engine Optimization — Wealth-First

## Enhancement Summary

**Deepened on:** 2026-03-24
**Review agents used:** Performance Oracle, Architecture Strategist, Data Integrity Guardian, Python Code Quality (Kieran), Redis Caching Best Practices, pgvector Batch Operations, TimescaleDB Index Best Practices

### Critical Fixes Found During Deepening

1. **Continuous aggregate formula is mathematically wrong** — codebase stores log returns (`math.log(close/prev)`) but the plan applied `LN(1+r)` (for arithmetic returns). Double-transforms the data, causing ~10bps/month tracking error. Fixed to `EXP(SUM(return_1d)) - 1`.
2. **Batch INSERT fallback requires SAVEPOINT** — after a batch INSERT fails, the transaction enters error state. Without `SAVEPOINT`/`ROLLBACK TO`, the per-chunk fallback will fail with `InFailedSqlTransaction`.
3. **ThreadPoolExecutor missing exception handling** — `future.result()` re-raises exceptions, killing the entire chapter loop. Must wrap in try/except to preserve the "never raises" contract.
4. **`invalidate_prefix` SCAN must batch deletes** — per-key `delete()` inside `scan_iter` creates N Redis round-trips. Must use `redis.delete(*batch)`.

### Key Improvements Added

- Savepoint pattern for batch INSERT with fallback
- Exception-safe ThreadPoolExecutor pattern
- Batched Redis key deletion
- DD report concurrency semaphore recommendation
- `bench:nav` TTL corrected from 120s to 300s
- Cache key hash extended from [:8] to [:16] (64-bit collision safety)
- Cache version prefix (`CACHE_SCHEMA_VERSION`) to prevent stale schemas after deploy
- Covering index + VACUUM ANALYZE note for hypertable visibility maps
- `transaction_per_chunk` for non-blocking hypertable index creation
- Batch size increased from 50 to 100 (pgvector research recommends 100 as sweet spot)
- `funds.py` removed from caching (deprecated routes with Sunset header)
- Worker invalidation mapping completed (6 missing workers added)
- SCAN fix moved from Phase 2 to Phase 1 (prerequisite for scaling cache)
- LATERAL JOIN recommended over ROW_NUMBER for N+1 fix (preserves Top-N optimization)
- Continuous aggregate RLS bypass warning + mandatory org_id filter documentation
- Continuous aggregate migration requires autocommit (same pattern as migration 0038)

## Overview

Systematic performance optimization across `vertical_engines/wealth/`, `quant_engine/`, and `ai_engine/`. Applies the same pattern proven in the Screener indexing work (33 indexes, `docs/reference/screener-index-reference.md`): **indexes + caching + query optimization = instant response**.

20 prioritized opportunities organized in 4 phases. Each phase is independently shippable and adds measurable value.

## Problem Statement

Current state analysis (see brainstorm: `docs/brainstorms/2026-03-24-engine-optimization-opportunities-brainstorm.md`):

- **20 of 25 route files have no caching** — every request hits DB even for data that changes once/day
- **Core hypertables lack dedicated indexes** — `nav_timeseries` and `fund_risk_metrics` rely only on TimescaleDB auto-indexes
- **DD report chapters generated sequentially** — 7 independent LLM calls run one-by-one (35-210s total)
- **pgvector upsert is N+1** — 200 chunks = 200 sequential INSERT statements
- **Multiple N+1 query patterns** — regime trigger detection, SEC injection, quant analyzer

## Proposed Solution

4-phase sprint with increasing complexity. Phase 1 is pure mechanical application of existing patterns (lowest risk). Each subsequent phase builds on the previous.

## Technical Approach

### Architecture

All changes follow existing codebase patterns:

- **Caching:** `@route_cache(ttl=N, key_prefix="x")` decorator from `app.core.cache` — fail-open, org-scoped by default, `global_key=True` for tenant-agnostic data
- **Indexes:** `op.execute("CREATE INDEX IF NOT EXISTS ...")` in Alembic migrations — idempotent, same pattern as migrations 0046/0047
- **Parallelization:** `ThreadPoolExecutor` (used in fact_sheet, fred_service, entity_bootstrap) or `asyncio.gather()` at route layer
- **Batch INSERT:** Multi-row VALUES with ON CONFLICT — replaces per-row loop in pgvector_search_service

### Implementation Phases

---

#### Phase 1: Caching Blitz + Index Sprint

**Goal:** Mechanical application of `@route_cache` to all eligible GET endpoints + new indexes on core wealth tables.

**Why first:** Lowest risk, highest cumulative impact. Both are additive (no behavior change), use proven patterns, and are independently testable.

##### 1A. Route Caching (~40 endpoints across 15 files)

For each file, add `from app.core.cache import route_cache` and decorate eligible GET handlers.

**Key pattern:**
```python
@router.get("/{profile}", response_model=CorrelationRegimeRead)
@route_cache(ttl=300, key_prefix="corr:regime")
async def get_correlation_regime(
    profile: str,
    ...
    user: CurrentUser = Depends(get_current_user),  # ← actor resolved from user
) -> CorrelationRegimeRead:
```

**Routes to cache (org-scoped):**

| File | Endpoints to cache | TTL | key_prefix |
|---|---|---|---|
| `correlation_regime.py` | `GET /{profile}`, `GET /{profile}/pair/{a}/{b}` | 300s | `corr:regime`, `corr:pair` |
| `attribution.py` | `GET /{profile}` | 300s | `attr:profile` |
| `blended_benchmark.py` | `GET /blocks`, `GET /{profile}`, `GET /{id}/nav` | 600s, 300s, 300s | `bench:blocks`, `bench:profile`, `bench:nav` |
| `exposure.py` | `GET /matrix`, `GET /metadata` | 300s | `exp:matrix`, `exp:meta` |
| ~~`funds.py`~~ | ~~DEPRECATED~~ | — | — | **DROPPED** — deprecated routes with `Sunset: 2026-06-30`. Cache `instruments.py` equivalents instead. |
| `instruments.py` | `GET /`, `GET /{id}` | 120s | `inst:list`, `inst:detail` |
| `model_portfolios.py` | `GET /`, `GET /{id}`, `GET /{id}/track-record` | 120s, 120s, 300s | `mp:list`, `mp:detail`, `mp:track` |
| `portfolios.py` | `GET /`, `GET /{id}/snapshot`, `GET /{id}/history` | 60s, 120s, 300s | `port:list`, `port:snap`, `port:hist` |
| `content.py` | `GET /` (list_content) | 60s | `content:list` |
| `strategy_drift.py` | GET endpoints | 120s | `drift:*` |
| `dd_reports.py` | `GET /` (list), `GET /{id}` (detail) | 60s, 120s | `dd:list`, `dd:detail` |

**Routes to cache (global — `global_key=True`):**

| File | Endpoints | TTL | key_prefix |
|---|---|---|---|
| `esma.py` | `GET /managers`, `GET /managers/{id}`, `GET /funds`, `GET /funds/{id}` | 600s | `esma:mgrs`, `esma:mgr`, `esma:funds`, `esma:fund` |

**Migrate legacy manual caching to `route_cache`:**

`macro.py` has 4 endpoints (`/bis`, `/imf`, `/treasury`, `/ofr`) using an older `_get_cached`/`_set_cached` pattern with raw Redis calls. These should migrate to `@route_cache(ttl=N, global_key=True)` for consistency.

**DO NOT cache:**
- POST/PUT/DELETE endpoints (mutations)
- SSE streaming endpoints (dd_reports SSE generation)
- Worker trigger endpoints
- `analytics.py` optimizer endpoints (already have custom Redis caching with SHA-256 hash)

**Cache invalidation strategy:** Workers that update data should call `invalidate_prefix()` after successful writes. Complete mapping (includes transitive dependencies):

| Worker | Writes To | Prefixes to Invalidate |
|---|---|---|
| `instrument_ingestion` | `instruments_universe`, `nav_timeseries` | `inst`, `fund` |
| `risk_calc` | `fund_risk_metrics` | `risk:summary`, `risk:cvar`, `risk:regime`, `fund:scoring`, `fund:risk`, `corr:regime`, `port:snap` |
| `portfolio_eval` | `portfolio_snapshots` | `port`, `corr`, `attr:profile` |
| `benchmark_ingest` | `benchmark_nav` | `bench` |
| `macro_ingestion` | `macro_data`, `macro_regional_snapshots` | `macro:snapshot` |
| `esma_ingestion` | `esma_managers`, `esma_funds` | `esma` (global: `org_id=None`) |
| `drift_check` | `strategy_drift_alerts` | `drift` |
| `sec_13f_ingestion` | `sec_13f_holdings`, `sec_13f_diffs` | `sec:holdings`, `sec:drift`, `sec:compare` (global) |
| `sec_adv_ingestion` | `sec_managers`, `sec_manager_funds` | `sec:search`, `sec:manager_funds`, `mgr` (global) |

**Staleness contract:** If Redis is temporarily unreachable during worker invalidation, stale data persists for at most TTL seconds. This is accepted for TTLs ≤ 600s.

##### 1B. Index Migration (`0048_wealth_analytics_indexes`)

Single migration with all 11 indexes. All use `CREATE INDEX IF NOT EXISTS` (idempotent) and `CONCURRENTLY` where possible (non-blocking on production).

**Note on hypertables:** Use `WITH (timescaledb.transaction_per_chunk)` for hypertable indexes. This creates the index one chunk at a time, each in its own transaction — only the chunk being indexed is write-locked, all other chunks remain unblocked. For non-hypertable tables (`model_portfolios`, `strategic_allocation`, `dd_reports`, `dd_chapters`), use `CREATE INDEX CONCURRENTLY` via autocommit connection (same pattern as migration 0038).

```python
# backend/app/core/db/migrations/versions/0048_wealth_analytics_indexes.py

def upgrade() -> None:
    # ── nav_timeseries (hypertable) ────────────────────────────────

    # Covering index for correlation/attribution: index-only scan
    # Covers: SELECT instrument_id, nav_date, return_1d WHERE instrument_id IN (...) AND nav_date >= ...
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_nav_ts_instrument_date_return
        ON nav_timeseries (instrument_id, nav_date)
        INCLUDE (return_1d)
        WITH (timescaledb.transaction_per_chunk)
    """)

    # RLS optimization: org_id + instrument for filtered scans
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_nav_ts_org_instrument
        ON nav_timeseries (organization_id, instrument_id)
        WITH (timescaledb.transaction_per_chunk)
    """)

    # ── fund_risk_metrics (hypertable) ─────────────────────────────

    # Latest metric per instrument (DISTINCT ON optimization)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fund_risk_instrument_date_desc
        ON fund_risk_metrics (instrument_id, calc_date DESC)
        WITH (timescaledb.transaction_per_chunk)
    """)

    # RLS + instrument + latest
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fund_risk_org_instrument_date
        ON fund_risk_metrics (organization_id, instrument_id, calc_date DESC)
        WITH (timescaledb.transaction_per_chunk)
    """)

    # Scoring ranking
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fund_risk_score
        ON fund_risk_metrics (manager_score DESC NULLS LAST)
        WHERE manager_score IS NOT NULL
        WITH (timescaledb.transaction_per_chunk)
    """)

    # ── model_portfolios ──────────────────────────────────────────

    # Live portfolio lookup (correlation, attribution, track record)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_model_portfolios_profile_live
        ON model_portfolios (profile)
        WHERE status = 'live'
    """)

    # ── strategic_allocation ──────────────────────────────────────

    # Temporal range scan for attribution
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_strategic_alloc_profile_dates
        ON strategic_allocation (profile, effective_from, effective_to)
    """)

    # ── benchmark_nav (hypertable) ────────────────────────────────

    # Per-block date range for attribution
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_benchmark_nav_block_date
        ON benchmark_nav (block_id, nav_date)
        WITH (timescaledb.transaction_per_chunk)
    """)

    # ── dd_reports ────────────────────────────────────────────────

    # Current report lookup (1 row per instrument)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dd_reports_instrument_current
        ON dd_reports (instrument_id, organization_id)
        WHERE is_current = true
    """)

    # ── dd_chapters ───────────────────────────────────────────────

    # Chapter listing ordered by report
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_dd_chapters_report_order
        ON dd_chapters (dd_report_id, chapter_order)
    """)
```

**Tests:**
- Existing `make check` (lint + architecture + typecheck) validates migration syntax
- `make migrate` on dev DB confirms clean execution
- Run `EXPLAIN ANALYZE` on key queries before/after to measure index impact

##### Phase 1 Acceptance Criteria

- [ ] `@route_cache` added to all 15 route files listed above
- [ ] Cache invalidation calls added to 4 workers
- [ ] Migration `0048_wealth_analytics_indexes` created with 11 indexes (10 btree + 1 covering)
- [ ] `make check` passes (lint + architecture + typecheck + 1439+ tests)
- [ ] `make migrate` clean on dev DB
- [ ] Manual: confirm cache HIT in Redis after second request to any cached endpoint

---

#### Phase 2: Pipeline & DD Report Optimization

**Goal:** Fix the two highest-impact computation bottlenecks: pgvector N+1 upsert and DD report sequential chapters.

##### 2A. pgvector Batch INSERT

**File:** `backend/ai_engine/extraction/pgvector_search_service.py`

Refactor `upsert_chunks()` (lines 231-288) from per-chunk INSERT to batched multi-row INSERT.

**Approach:** Use the existing `pg_insert().values(list).on_conflict_do_update()` pattern (already used in `benchmark_ingest.py:266`, `adv_service.py:473`, `thirteenf_service.py:730`). Group chunks into batches of 50.

**Challenge:** `vector_chunks` uses raw `text()` SQL because embeddings need `CAST(:embedding AS vector)`. Two options:

- **Option A (preferred):** Define a lightweight SQLAlchemy `Table` reflection for `vector_chunks` to use `pg_insert`. The pgvector SQLAlchemy extension handles vector column types natively.
- **Option B (fallback):** Keep raw SQL but batch with multi-row VALUES clause.

```python
# Option A — follows codebase pattern from benchmark_ingest.py
from sqlalchemy.dialects.postgresql import insert as pg_insert

BATCH_SIZE = 100  # 100 rows × 17 cols = 1700 params (well under PG 65535 limit)
                   # 100 rows × ~25KB (3072-dim vector) = ~2.5MB per INSERT
                   # Research: 100 is the sweet spot — 98% round-trip reduction vs single,
                   # keeps transaction duration under a few hundred ms

async def upsert_chunks(db: AsyncSession, documents: list[dict], ...) -> UpsertResult:
    # ... dedup validation unchanged ...

    succeeded = 0
    failed = 0
    errors: list[str] = []

    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        rows = [_doc_to_row(doc) for doc in batch]
        try:
            # SAVEPOINT so batch failure doesn't poison the transaction
            async with db.begin_nested():
                stmt = pg_insert(vector_chunks_table).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "content": stmt.excluded.content,
                        "embedding": stmt.excluded.embedding,
                        "embedding_model": stmt.excluded.embedding_model,
                        "updated_at": func.now(),
                    },
                )
                await db.execute(stmt)
            succeeded += len(batch)
        except Exception as exc:
            # Transaction rolled back to savepoint automatically.
            # Fallback: retry individually for this batch.
            logger.warning("Batch %d failed (%s), falling back to per-chunk", i // BATCH_SIZE, type(exc).__name__)
            for doc in batch:
                try:
                    async with db.begin_nested():
                        await _upsert_single_chunk(db, doc)
                    succeeded += 1
                except Exception as inner_exc:
                    failed += 1
                    errors.append(f"{doc.get('id', '?')}: {inner_exc}")
    ...
```

**Error handling:** `db.begin_nested()` creates a SAVEPOINT. If the batch INSERT fails, the transaction rolls back to the savepoint (not the entire transaction), allowing the per-chunk fallback to proceed. Without this, the fallback would fail with `InFailedSqlTransaction`.

##### 2B. DD Report Chapter Parallelization

**File:** `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`

Refactor `_generate_all_chapters()` (lines 329-428) to use `ThreadPoolExecutor` for chapters 1-7.

**Design decision (see brainstorm Open Question #2):** Use `ThreadPoolExecutor` inside the sync engine. This is safe because:
- The engine already runs inside `asyncio.to_thread()` (one dedicated OS thread)
- `ThreadPoolExecutor` creates additional threads within that thread — no event loop conflict
- `EvidencePack` is a frozen dataclass (thread-safe read-only)
- `generate_chapter()` is stateless (takes `call_openai_fn` + evidence, returns result)
- `_DEFAULT_LLM_CONCURRENCY = 5` already defines the intended parallelism
- **VERIFIED:** `CallOpenAiFn` (`shared_protocols.py:13-27`) is a **sync protocol** — `def __call__(...) -> dict[str, Any]`. No async, no coroutine. Safe to call from ThreadPoolExecutor threads.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _generate_all_chapters(self, *, evidence, existing_chapters, force):
    assert self._call_openai_fn is not None
    chapters: list[ChapterResult] = []
    chapter_summaries: dict[str, str] = {}

    # Phase A: Chapters 1-7 in parallel
    parallel_defs = [
        ch for ch in CHAPTER_REGISTRY if ch["tag"] != SEQUENTIAL_CHAPTER_TAG
    ]
    # Filter cached chapters
    to_generate = []
    for ch_def in parallel_defs:
        if not force and ch_def["tag"] in existing_chapters:
            cached_content = existing_chapters[ch_def["tag"]]
            chapters.append(ChapterResult(
                tag=ch_def["tag"], order=ch_def["order"],
                title=ch_def["title"], content_md=cached_content,
                status="completed", critic_status="accepted",
            ))
            chapter_summaries[ch_def["tag"]] = cached_content[:500]
            continue
        to_generate.append(ch_def)

    if to_generate:
        with ThreadPoolExecutor(
            max_workers=_DEFAULT_LLM_CONCURRENCY,
            thread_name_prefix="dd-chapter",
        ) as pool:
            future_to_ch = {
                pool.submit(
                    generate_chapter,
                    self._call_openai_fn,
                    chapter_tag=ch["tag"],
                    evidence_context=evidence.filter_for_chapter(ch["tag"]),
                    evidence_pack=evidence,
                ): ch
                for ch in to_generate
            }
            for future in as_completed(future_to_ch):
                ch_def = future_to_ch[future]
                try:
                    result = future.result()
                except Exception as exc:
                    # Preserve "never raises" contract — failed chapter, not failed report
                    logger.exception("chapter_generation_failed", chapter_tag=ch_def["tag"])
                    result = ChapterResult(
                        tag=ch_def["tag"], order=ch_def["order"],
                        title=ch_def["title"], content_md=None,
                        status="failed", error=str(exc),
                    )
                chapters.append(result)
                if result.content_md:
                    chapter_summaries[result.tag] = result.content_md[:500]

    # Phase B: Chapter 8 (Recommendation) — sequential, unchanged
    # ... existing code ...
```

**Speedup:** 5-7x (from 35-210s sequential to 7-42s parallel, bounded by slowest chapter).

##### ~~2C. TF-IDF Vectorizer Singleton~~ — DROPPED

**Already implemented.** `hybrid_classifier.py:484-537` has `_ensure_doc_type_vectorizer()` and `_ensure_vehicle_type_vectorizer()` singleton patterns with module-level globals. No work needed.

##### 2C. Fix `invalidate_prefix` to use SCAN instead of KEYS

**File:** `backend/app/core/cache/route_cache.py:100`

Current `invalidate_prefix()` uses `redis.keys(pattern)` which is O(N) across the entire keyspace and blocks the Redis event loop. With 40+ cached endpoints, this must be replaced with `SCAN` before scaling.

```python
async def invalidate_prefix(prefix: str, org_id: UUID | None = None) -> int:
    """Delete all cache keys matching a prefix + org scope.

    Uses SCAN (not KEYS) to avoid blocking Redis event loop.
    Batches DELETE calls to reduce network round-trips.
    """
    try:
        from app.core.jobs.tracker import get_redis_pool
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        pattern = f"rc:{prefix}:{org_id or '*'}:*"
        deleted = 0
        batch: list[bytes] = []
        async for key in redis.scan_iter(match=pattern, count=100):
            batch.append(key)
            if len(batch) >= 100:
                deleted += await redis.delete(*batch)
                batch.clear()
        if batch:
            deleted += await redis.delete(*batch)
        return deleted
    except Exception as exc:
        logger.warning("Cache invalidation failed: %s", exc)
        return 0
```

##### Phase 2 Acceptance Criteria

- [ ] pgvector `upsert_chunks()` uses batch INSERT (BATCH_SIZE=50)
- [ ] Fallback to per-chunk insert on batch failure
- [ ] DD report chapters 1-7 generated in parallel via ThreadPoolExecutor
- [ ] Chapter 8 still sequential (depends on 1-7 summaries)
- [ ] `invalidate_prefix()` uses `SCAN` instead of `KEYS`
- [ ] `make check` passes
- [ ] Pipeline test: process a test PDF, verify all chunks upserted correctly
- [ ] DD report test: generate a report, verify all 8 chapters present + correct order

---

#### Phase 3: N+1 Fixes + Computation Optimization

**Goal:** Eliminate all identified N+1 patterns and optimize hot computation paths.

##### 3A. Rebalancing Regime Trigger — Batch Query

**File:** `backend/vertical_engines/wealth/rebalancing/service.py`

Replace per-profile snapshot query (lines 143-151) with single batch query using LATERAL JOIN (preserves Top-N index optimization per profile):

```python
def detect_regime_trigger(self, db, organization_id):
    from app.domains.wealth.models.portfolio import PortfolioSnapshot
    from sqlalchemy import literal_column, text

    threshold = self._regime_threshold
    _STRESS_REGIMES = frozenset({"stress", "crisis"})

    # LATERAL JOIN: single roundtrip, but planner uses index+LIMIT per profile
    # (ROW_NUMBER alternative scans all rows before filtering — slower for small threshold)
    rows = db.execute(text("""
        SELECT p.profile, s.snapshot_date, s.regime
        FROM (
            SELECT DISTINCT profile
            FROM portfolio_snapshots
            WHERE organization_id = :org_id
        ) p
        CROSS JOIN LATERAL (
            SELECT snapshot_date, regime
            FROM portfolio_snapshots ps
            WHERE ps.organization_id = :org_id AND ps.profile = p.profile
            ORDER BY ps.snapshot_date DESC
            LIMIT :threshold
        ) s
    """), {"org_id": organization_id, "threshold": threshold}).all()

    # Group in-memory by profile
    by_profile: dict[str, list] = {}
    for row in rows:
        by_profile.setdefault(row.profile, []).append(row)

    # ... rest of logic unchanged, iterating by_profile ...
```

**Why LATERAL over ROW_NUMBER:** With threshold=3 and 10 profiles, LATERAL executes 10 index-assisted LIMIT 3 scans (30 rows fetched). ROW_NUMBER scans ALL 10,000 snapshots, computes window, then discards 99.7%. LATERAL is O(profiles × threshold) vs ROW_NUMBER O(total_rows).

##### 3B. Attribution Batch Computation

**File:** `backend/app/domains/wealth/routes/attribution.py`

1. Instantiate `AttributionService` ONCE before the period loop (line 214)
2. Collect all period data, compute in a single `asyncio.to_thread()` call

```python
svc = AttributionService()

# Compute all periods in one thread call
def _compute_all_periods():
    results = []
    for period_start, period_end in periods:
        # ... build period data (already in-memory) ...
        result = svc.compute_portfolio_attribution(...)
        results.append(result)
    return results

period_results = await asyncio.to_thread(_compute_all_periods)
```

##### 3C. SEC Injection Batch CIK Resolution

**File:** `backend/vertical_engines/wealth/dd_report/sec_injection.py`

Batch the available-dates query and sector-weights query into fewer DB roundtrips:
- Query all report_dates for the CIK in one call
- Query sector weights for latest + previous quarter in one call (instead of two separate calls)

##### 3D. Peer Group Batch Migration

Audit all callers of `peer_group/service.py` — ensure they use `compute_rankings_batch()` instead of individual `compute_rankings()` calls.

##### Phase 3 Acceptance Criteria

- [ ] `detect_regime_trigger()` uses single window-function query (no per-profile loop)
- [ ] Attribution service instantiated once, all periods computed in single `to_thread` call
- [ ] SEC injection uses <=2 DB queries per manager (was 3)
- [ ] All peer group callers use batch API
- [ ] `make check` passes
- [ ] Existing tests still pass (no behavior change)

---

#### Phase 4: Pre-computation + Continuous Aggregates

**Goal:** Materialize expensive computations and add TimescaleDB continuous aggregates.

##### 4A. Continuous Aggregates Migration (`0049_wealth_continuous_aggregates`)

Three new continuous aggregates following the pattern from `sec_13f_holdings_agg`:

```sql
-- Monthly NAV returns per instrument (for attribution, backtest, track record)
-- IMPORTANT: return_1d stores LOG returns (math.log(close/prev)), NOT arithmetic returns.
-- For log returns, compounding = SUM(log_returns), then exponentiate for arithmetic equivalent.
-- DO NOT use LN(1 + return_1d) — that's for arithmetic returns and would double-transform.
CREATE MATERIALIZED VIEW IF NOT EXISTS nav_monthly_returns_agg
WITH (timescaledb.continuous) AS
SELECT
    instrument_id,
    organization_id,
    time_bucket('1 month', nav_date) AS month,
    SUM(return_1d) AS compound_log_return,
    (EXP(SUM(return_1d)) - 1) AS compound_return,
    COUNT(*) AS trading_days,
    MIN(nav) AS min_nav,
    MAX(nav) AS max_nav
FROM nav_timeseries
WHERE return_1d IS NOT NULL
GROUP BY instrument_id, organization_id, time_bucket('1 month', nav_date);

-- Monthly benchmark returns per block
-- Same log return convention as nav_timeseries.
CREATE MATERIALIZED VIEW IF NOT EXISTS benchmark_monthly_returns_agg
WITH (timescaledb.continuous) AS
SELECT
    block_id,
    time_bucket('1 month', nav_date) AS month,
    SUM(return_1d) AS compound_log_return,
    (EXP(SUM(return_1d)) - 1) AS compound_return,
    COUNT(*) AS trading_days
FROM benchmark_nav
WHERE return_1d IS NOT NULL
GROUP BY block_id, time_bucket('1 month', nav_date);

-- Refresh policies
SELECT add_continuous_aggregate_policy('nav_monthly_returns_agg',
    start_offset => INTERVAL '3 months',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');

SELECT add_continuous_aggregate_policy('benchmark_monthly_returns_agg',
    start_offset => INTERVAL '3 months',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');
```

**Note:** `risk_latest_agg` (latest risk metrics per instrument) is **NOT expressible as a TimescaleDB continuous aggregate** — continuous aggregates require `time_bucket()` as the grouping dimension, but the "latest per instrument" pattern uses `DISTINCT ON` which is incompatible. The `ix_fund_risk_instrument_date_desc` index from Phase 1 addresses this query pattern instead. If a materialized "latest metrics" table is needed later, it would be a worker-populated regular table, not a continuous aggregate.

##### 4B. Correlation Regime Caching

Rather than pre-computing in a worker (see brainstorm Open Question #1), add `@route_cache(ttl=300)` in Phase 1. If 300s cache is insufficient after measurement, then add worker-based pre-computation as a follow-up.

##### 4C. Quant Engine Refinements

1. **DTW sliding window:** In `drift_service.py`, add optional `max_lookback_days` parameter (default 504 = 2 years). Truncate timeseries before DTW computation.

2. **Backtest parallelization:** In `backtest_service.py`, parallelize fold computation:
```python
from concurrent.futures import ThreadPoolExecutor

def walk_forward_backtest(..., n_splits=5):
    with ThreadPoolExecutor(max_workers=min(n_splits, 4)) as pool:
        fold_results = list(pool.map(_evaluate_fold, folds))
```

##### Phase 4 Acceptance Criteria

- [ ] Migration `0049_wealth_continuous_aggregates` with 2 materialized views + refresh policies
- [ ] Attribution route updated to read from `nav_monthly_returns_agg` when available
- [ ] DTW drift computation respects `max_lookback_days` parameter
- [ ] Backtest folds parallelized via ThreadPoolExecutor
- [ ] `make check` passes
- [ ] `make migrate` clean on dev DB
- [ ] Continuous aggregates refresh correctly after `instrument_ingestion` worker runs

---

## System-Wide Impact

### Interaction Graph

```
Worker writes data → DB updated → cache stale (TTL expires or invalidate_prefix called)
                                → continuous aggregate refreshes (TimescaleDB policy)

User request → route_cache check → HIT: return cached JSON
                                 → MISS: execute query → serialize → cache SET → return

DD Report trigger → route handler → asyncio.to_thread(engine.generate)
                                     → ThreadPoolExecutor(5) → 7 parallel LLM calls
                                     → sequential chapter 8 → persist → SSE events

Pipeline ingest → ... → embedding → batch INSERT (50/batch) → audit
```

### Error & Failure Propagation

- **Cache errors:** Fail-open by design (`route_cache.py:69-70`). Redis down = no cache, requests proceed normally.
- **Batch INSERT failure:** Falls back to per-chunk insert for the failed batch. Partial success tracked in `UpsertResult`.
- **ThreadPoolExecutor chapter failure:** Each future is independent. Failed chapters get `status="failed"` in result — same as current sequential behavior.
- **Index creation failure:** `IF NOT EXISTS` makes migration idempotent. Safe to re-run.
- **Continuous aggregate refresh failure:** TimescaleDB retries automatically. Data stays consistent (old aggregate until refresh succeeds).

### State Lifecycle Risks

- **Cache staleness:** Workers update DB but cache has old data. Mitigated by: (1) TTL ensures eventual consistency, (2) explicit `invalidate_prefix()` in workers for critical paths. Maximum staleness = TTL value (60-600s depending on endpoint).
- **Partial DD report:** If ThreadPoolExecutor chapter fails, resume safety still works — cached chapters are reused on retry (unchanged behavior).
- **Index creation on large hypertables:** `nav_timeseries` may have 500K+ rows. TimescaleDB chunk-level index creation is fast (<5s per chunk). Full migration should complete in <30s.

### API Surface Parity

No API changes. All optimizations are internal:
- Same response schemas
- Same HTTP status codes
- Same error handling
- Cache returns `JSONResponse` with identical JSON structure

### Integration Test Scenarios

1. **Cache + Worker invalidation:** Trigger `risk_calc` worker → verify cached `/funds/scoring` is invalidated → next request returns fresh data
2. **DD report parallel chapters:** Generate full DD report → verify all 8 chapters present, correct order, chapter 8 references summaries from 1-7
3. **Batch INSERT resilience:** Upsert 200 chunks where chunk #150 has invalid embedding → verify 199 succeed, 1 fails, `UpsertResult.failed_chunk_count == 1`
4. **Continuous aggregate freshness:** Insert new NAV data → trigger refresh → verify `nav_monthly_returns_agg` includes new data

## Acceptance Criteria

### Functional Requirements

- [ ] All 15 route files have appropriate `@route_cache` decorators
- [ ] 4 workers call `invalidate_prefix()` after data writes
- [ ] Migration `0048` creates 11 indexes
- [ ] Migration `0049` creates 2 continuous aggregates with refresh policies
- [ ] pgvector upsert uses batch INSERT (50 chunks/batch)
- [ ] DD report chapters 1-7 generate in parallel
- [ ] All N+1 patterns fixed (rebalancing, SEC injection)
- [ ] Attribution uses single `to_thread` call for all periods

### Non-Functional Requirements

- [ ] No API response schema changes (backward compatible)
- [ ] Cache fail-open on Redis unavailable
- [ ] `make check` passes at each phase boundary
- [ ] All 1439+ existing tests pass

### Quality Gates

- [ ] Each phase is a separate PR with focused scope
- [ ] EXPLAIN ANALYZE on 3 key queries before/after indexes (nav_timeseries, fund_risk_metrics, model_portfolios)
- [ ] Manual verification of cache HIT/MISS via Redis CLI or structlog

## Dependencies & Prerequisites

- Docker compose running (PostgreSQL 16 + TimescaleDB + Redis 7)
- Current migration head applied (`0047_screener_redesign_indexes`)
- All current tests passing (`make check`)

## Risk Analysis & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Index creation slows worker INSERTs | Medium | Measure INSERT performance before/after. TimescaleDB chunk indexes are small. |
| Cache staleness confuses users | Low | TTL values chosen conservatively. Worker invalidation for critical paths. |
| ThreadPoolExecutor + to_thread nesting | Low | EvidencePack is frozen (read-only). generate_chapter is stateless. No shared mutable state. |
| Batch INSERT SQL injection risk | Low | Using `pg_insert().values(list)` pattern (not raw SQL string building). SQLAlchemy handles parameterization. Same pattern as `benchmark_ingest.py`, `adv_service.py`. |
| Continuous aggregate refresh lag | Low | 1-day refresh interval + manual refresh available. Data is eventually consistent. |

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-24-engine-optimization-opportunities-brainstorm.md](../brainstorms/2026-03-24-engine-optimization-opportunities-brainstorm.md)
  - Key decisions: 20 opportunities prioritized by impact/effort, wealth-first approach, 4-phase delivery
  - Screener index reference as pattern template

### Internal References

- `route_cache` implementation: `backend/app/core/cache/route_cache.py`
- Index migration pattern: `backend/app/core/db/migrations/versions/0047_screener_redesign_indexes.py`
- pgvector upsert (current): `backend/ai_engine/extraction/pgvector_search_service.py:231-288`
- DD report engine: `backend/vertical_engines/wealth/dd_report/dd_report_engine.py:329-428`
- Rebalancing N+1: `backend/vertical_engines/wealth/rebalancing/service.py:143-180`
- ThreadPoolExecutor examples: `backend/quant_engine/fred_service.py:377`, `backend/data_providers/sec/shared.py:882`
- Screener index reference: `docs/reference/screener-index-reference.md`

### Related Work

- Screener indexing: migrations 0046, 0047 (33 indexes across 8 tables)
- Screener caching: `screener.py`, `sec_analysis.py`, `manager_screener.py` routes
- DD Report optimization backlog: `docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md` — complementary work on evidence-aware prompts (our Phase 2B handles parallelization, that plan handles prompt quality)
- Batch INSERT pattern source: `benchmark_ingest.py:266`, `adv_service.py:473`, `thirteenf_service.py:730` — `pg_insert().values(list).on_conflict_do_update()`
- RLS subselect pattern: `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md` — prerequisite for all index work (already enforced)
- VectorChunk ORM model: `backend/app/domains/credit/documents/models/vector_chunk.py` — has `Vector(3072)` column, usable with `pg_insert`

---

## Research Insights (from /deepen-plan agents)

### Redis Caching

**Cache stampede prevention (future improvement):** XFetch algorithm (probabilistic early recomputation) is the best fit for Upstash serverless Redis. No lock coordination overhead. Each request independently decides whether to recompute based on exponentially increasing probability as TTL nears expiry. Implementation deferred — current TTLs are short enough that stampede impact is minimal.

**Cache version prefix:** Add `CACHE_SCHEMA_VERSION` to key format to prevent serving stale schemas after deploys. Key becomes `rc:{version}:{prefix}:{scope}:{hash}`. Bump version only on schema-breaking changes, not every deploy. Old keys expire naturally via TTL — no FLUSHDB needed.

**Hash collision safety:** Extend `_params_hash` from `[:8]` (32-bit, collision at ~77K keys) to `[:16]` (64-bit, collision at ~4B keys). Cost: 8 extra bytes per Redis key. Safety: collision-safe up to millions of parameter variants per endpoint.

**UNLINK vs DELETE:** Use `redis.unlink(*batch)` instead of `redis.delete(*batch)` for async memory freeing. `UNLINK` is non-blocking — it removes the key immediately but frees memory in a background thread.

### pgvector Batch Operations

**`pg_insert` works natively with Vector type:** The `pgvector.sqlalchemy.Vector` type has a `bind_processor` that auto-serializes `list[float]` to pgvector text format. No `CAST(:embedding AS vector)` needed when using ORM/Core path. Must `import pgvector.sqlalchemy` before table reflection.

**COPY binary for full rebuilds:** `search_rebuild.py` could use psycopg3 COPY binary path for 8-10x faster full re-indexing. COPY doesn't support ON CONFLICT, so only for clean rebuilds. This is a follow-up optimization, not in current scope.

**Batch size benchmark data:** Single INSERT: ~100-500 rows/sec. Batch INSERT (100): ~2,000-5,000 rows/sec. COPY binary: ~15,000-30,000 rows/sec. (For 3072-dim vectors.)

### TimescaleDB Indexing

**`transaction_per_chunk`:** Creates indexes one chunk at a time, each in its own transaction. Only the chunk being indexed is write-locked. If creation fails partway, some chunks have the index and some don't — the parent index is marked invalid. Detect with `SELECT * FROM pg_index WHERE indisvalid IS FALSE`.

**INCLUDE on hypertables:** Fully propagated to chunk indexes. For covering index benefit (index-only scan), the visibility map must indicate all tuples visible. Run `VACUUM ANALYZE` after bulk ingestion to maximize coverage on recent (uncompressed) chunks.

**Continuous aggregate refresh:** `start_offset=3 days` handles late-arriving data corrections. `end_offset=1 day` excludes incomplete current day. `schedule_interval=1 day` matches worker frequency. Enable `materialized_only=false` for real-time aggregation of unmaterialized buckets.

### Continuous Aggregates + RLS (CRITICAL)

**Continuous aggregates DO NOT respect RLS.** They are materialized views containing data from ALL organizations. Any route reading from `nav_monthly_returns_agg` MUST explicitly include `WHERE organization_id = :org_id`. Failure to do so is a **tenant data isolation violation**.

Recommendations:
1. Add prominent comment in migration: `-- WARNING: No RLS. ALL queries must include WHERE organization_id = :org_id`
2. Create wrapper function that requires `organization_id` as mandatory parameter — never expose aggregate name in route code
3. Add test to `test_global_table_isolation.py` verifying continuous aggregate queries always filter by `organization_id`
4. `benchmark_monthly_returns_agg` is safe (global table, no org_id, no RLS)

### Continuous Aggregate Migration (autocommit)

Continuous aggregate DDL cannot run inside a transaction block. Must use autocommit connection, same pattern as migration 0038:

```python
from alembic import op

def upgrade() -> None:
    # Continuous aggregates require autocommit
    conn = op.get_bind().connection.dbapi_connection
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS nav_monthly_returns_agg ...
    """)
    # ... refresh policies ...
    conn.autocommit = False
```

### DD Report Concurrency

**Recommended:** Add a lazy `asyncio.Semaphore(3)` in the DD report route handler to bound concurrent generations. With ThreadPoolExecutor(5) per report and potential 3 concurrent reports, that's 18 OS threads — manageable but should be capped. The `content.py` routes already use `asyncio.Semaphore(3)` as precedent.

### Performance Oracle Verified Correct

- ThreadPoolExecutor(5) inside `asyncio.to_thread()` — safe for I/O-bound LLM calls (GIL released during socket ops)
- INCLUDE clause propagates to TimescaleDB chunks correctly
- LATERAL JOIN is preferred over ROW_NUMBER for small threshold values
- Phase ordering (caching → computation → N+1 → materialization) minimizes risk
- Per-report ThreadPoolExecutor lifecycle matches `fact_sheet_engine.py` precedent
