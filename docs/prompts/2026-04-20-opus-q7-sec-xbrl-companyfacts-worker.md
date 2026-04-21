---
pr_id: PR-Q7
title: "feat(ingest/sec-xbrl): companyfacts bulk ingestion into sec_xbrl_facts hypertable"
branch: feat/sec-xbrl-companyfacts-worker
sprint: S3
dependencies: []
loc_estimate: 900
reviewer: data-platform
scope: local-dev-only
---

# Prompt — PR-Q7: SEC XBRL Company Facts Ingestion (Local Bulk)

## Goal

Ship a one-shot + replayable ingestion worker that loads SEC XBRL **Company Facts** bulk JSON (already downloaded locally) into a single TimescaleDB hypertable `sec_xbrl_facts`. This replaces the previously-scoped Tiingo Fundamentals worker (Tiingo Fundamentals is a paid add-on not yet activated). Company Facts gives us point-in-time fundamentals with restatement history natively, zero HTTP cost, for **all 19,330 SEC filers** — superset of the original top-500 universe.

Scope for this PR: **local dev DB only**. Source = `$COMPANYFACTS_DIR` filesystem (Andrei has it at `C:\Users\andre\Downloads\companyfacts\`). No HTTP to SEC, no Railway cron, no prod deploy. Follow-up PR will productionise (delta via `data.sec.gov` API, scheduler entry, Railway).

This unblocks PR-Q8 (characteristics matview: P/E, P/B, EV/EBITDA, market cap from `sec_xbrl_facts ⋈ nav_timeseries`) and PR-Q9 (G5 IPCA prod).

## Context — why this shape

The SEC bulk `companyfacts.zip` is a flat set of `CIK{10digits}.json` files. Each file has:

```
{
  "cik": 1750,
  "entityName": "AAR CORP.",
  "facts": {
    "dei":    {concept: {label, description, units: {unit_name: [obs, ...]}}, ...},
    "us-gaap":{concept: {label, description, units: {unit_name: [obs, ...]}}, ...}
  }
}
```

Each observation object:

```json
{"end":"2010-05-31","val":114906000,"accn":"0001104659-10-049632","fy":2011,"fp":"Q1","form":"10-Q","filed":"2010-09-23"}
```

Some flow concepts (income, cash flow) also carry `"start"` (period_start). Units vary per concept (USD, shares, USD/shares, pure, etc.). Restatements appear as additional observations with different `accn` (e.g. 10-K/A filed later) — **never overwrite**. Filesystem scan confirmed ~19,330 files, ~18 GB total, ~469 concepts per large issuer, ~100+ obs per concept.

## Spec references (READ FIRST)

- `CLAUDE.md` §Data Ingestion Workers, §Stability Guardrails, §Data Lake Rules, §Critical Rules (RLS/global tables, advisory locks via `zlib.crc32`, `SET LOCAL`, `expire_on_commit=False`)
- `backend/app/core/db/migrations/versions/0066_fund_class_xbrl_fees.py` — existing XBRL precedent (fund-class fees, separate domain)
- `backend/scripts/seed_fund_class_fees_xbrl.py` — existing XBRL ingestion style reference
- `backend/app/core/jobs/nport_ingestion.py` (lock 900_018) — reference worker pattern (advisory lock, upsert, progress logging)
- `backend/app/core/jobs/sec_bulk_ingestion.py` (lock 900_050) — reference bulk-file ingestion pattern
- SEC XBRL Company Facts schema: https://www.sec.gov/edgar/sec-api-documentation

## Files to create

### Migration

1. `backend/app/core/db/migrations/versions/0166_sec_xbrl_facts.py`
   - `sec_xbrl_facts` hypertable:
     - `cik BIGINT NOT NULL`
     - `taxonomy TEXT NOT NULL` (`us-gaap` | `dei` | `ifrs-full` | `srt`)
     - `concept TEXT NOT NULL`
     - `unit TEXT NOT NULL` (USD, shares, USD/shares, pure, etc.)
     - `period_end DATE NOT NULL`
     - `period_start DATE` (nullable — only present for flow concepts)
     - `val NUMERIC` (some dei concepts are not numeric — nullable, see `val_text` below)
     - `val_text TEXT` (fallback for non-numeric observations; nullable)
     - `accn TEXT NOT NULL` (SEC accession number)
     - `fy INT` (fiscal year)
     - `fp TEXT` (Q1/Q2/Q3/FY/CY — keep raw)
     - `form TEXT NOT NULL` (10-K, 10-Q, 10-K/A, 8-K, etc.)
     - `filed DATE NOT NULL`
     - `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()`
     - PK: `(cik, taxonomy, concept, unit, period_end, accn)`
   - `SELECT create_hypertable('sec_xbrl_facts', 'period_end', chunk_time_interval => INTERVAL '1 year', if_not_exists => TRUE);`
   - Indexes:
     - `(cik, taxonomy, concept, period_end DESC)` — primary analytical access
     - `(concept, period_end DESC)` where `taxonomy='us-gaap'` — cross-sectional reads for matview
     - `(filed DESC)` — for delta updates in follow-up PR
   - Compression:
     - `ALTER TABLE sec_xbrl_facts SET (timescaledb.compress, timescaledb.compress_segmentby = 'cik, concept', timescaledb.compress_orderby = 'period_end DESC, accn');`
     - `SELECT add_compression_policy('sec_xbrl_facts', INTERVAL '180 days');`
   - No RLS (global reference data — same pattern as `sec_nport_holdings`, `macro_data`, etc.; add `sec_xbrl_facts` to the global-tables docstring in CLAUDE.md update).
   - `downgrade()` drops hypertable cleanly.

### Worker

2. `backend/app/core/jobs/sec_xbrl_facts_ingestion.py`

   ```python
   LOCK_ID = 900_060
   ```

   Responsibilities:
   - Acquire advisory lock via existing helper in `backend/app/core/runtime/` (pattern from `nport_ingestion`); skip if held.
   - Resolve source directory from `settings.companyfacts_dir` (new config field). Fail fast if not set or missing.
   - Resolve universe: default to **all `*.json` files in dir** (scope = local dev; operator can subset with CLI `--cik` flag on the script in §5). No filtering by `instruments_universe` in this PR (universe filter becomes the second-pass matview in PR-Q8).
   - Streaming parse via `ijson` (already in repo deps if present; else add) — do **not** `json.load` 3MB+ files fully if possible; however, `ijson` over a 469-concept × 100-obs file is ~45k events, acceptable. If `ijson` adds complexity, falling back to `json.load` per file is acceptable (18 GB total but only one file at a time in memory).
   - Batch buffer: accumulate observations, flush every 10,000 rows via `asyncpg.Connection.copy_records_to_table('sec_xbrl_facts', records=[...], columns=[...])` for speed, or `execute_values` via psycopg if copy path is harder. **Prefer COPY**.
   - Upsert semantics: since PK is immutable (XBRL facts are append-only once published), use `COPY` into staging temp table `_sec_xbrl_facts_stage` then `INSERT ... SELECT ... ON CONFLICT DO NOTHING`. Idempotent.
   - Per-file progress log every 500 files: `{files_done}/{total} cik={cik} entity={entityName} facts_inserted={n}`.
   - Error handling: individual file parse failure → log `ERROR` with cik + filename, increment `failed_files` counter, continue. Worker must not crash on one bad file.
   - `try/finally` releases the advisory lock.
   - Return summary dict: `{files_processed, files_failed, rows_inserted, elapsed_sec}`.

   Non-goals of the worker (do **not** implement here):
   - Delta via SEC HTTP API
   - Scheduler registration
   - Universe subsetting beyond CLI flag

### Config

3. `backend/app/core/config.py` (or wherever Settings lives)
   - Add `companyfacts_dir: Path | None = None` with env var `COMPANYFACTS_DIR`.
   - No `TIINGO_API_KEY`. Remove/skip any remnants from the old PR-Q7 draft.

### CLI runner

4. `backend/scripts/run_sec_xbrl_facts_ingestion.py`
   - `python -m backend.scripts.run_sec_xbrl_facts_ingestion` → runs full dir.
   - `--cik 0000320193 --cik 0000789019` → subset for smoke tests.
   - `--limit 50` → first N files (by sort order).
   - `--dry-run` → parses and counts but does not write to DB.
   - Uses `asyncio.run(main())`, wires into the worker function.

### Tests

5. `backend/tests/fixtures/xbrl/CIK0000001750.json` — trimmed AAR CORP fixture (~5 us-gaap concepts, ~3 obs each, both `10-K` and `10-K/A` present to exercise restatement).
6. `backend/tests/fixtures/xbrl/CIK0000320193.json` — trimmed AAPL fixture (similar shape, different unit mix — shares + USD).
7. `backend/tests/fixtures/xbrl/CIK0000000000_malformed.json` — truncated JSON for failure path test.

8. `backend/tests/test_sec_xbrl_facts_ingestion.py` — ≥12 integration tests against a real PG (follow existing pattern — `docker-compose` PG in CI or session-scoped pytest fixture; match the style of `test_nport_ingestion.py`):
    1. Advisory lock acquired + released across success path
    2. Second concurrent invocation exits with "lock held" log, zero writes
    3. Fixture AAR: inserts expected row count, correct `cik`, `taxonomy`, `concept`, `accn`
    4. Restatement: `10-K` and `10-K/A` for same `(cik, concept, unit, period_end)` produce **two separate rows** (distinct `accn`), neither overwrites the other
    5. Unit switching: `shares` and `USD` observations for same concept both persist with correct `unit`
    6. Re-run idempotent: second run of same fixture inserts 0 additional rows, no error
    7. `period_start` populated when present in source, NULL when absent
    8. Non-numeric observation (e.g. `dei:EntityRegistrantName`) → `val IS NULL`, `val_text` populated (or row skipped gracefully — decide and document)
    9. Malformed fixture: logged as failure, counter increments, worker continues to next file
    10. `--limit 1` flag processes exactly one file
    11. `--cik` flag subsets correctly (rejects CIKs not present in dir with warning)
    12. `--dry-run` writes zero rows, returns summary with expected `rows_would_insert`

9. `backend/tests/test_sec_xbrl_parser.py` — ≥5 pure-function tests for the observation-parsing helper (no DB):
    1. Observation with all fields present → dataclass correct
    2. Observation missing `fy`/`fp` → NULL handled
    3. Observation with `start` → `period_start` set
    4. Non-USD unit preserved verbatim
    5. Non-numeric `val` routed to `val_text`

## Files to modify

1. `CLAUDE.md`
   - Add to Data Ingestion Workers table:
     `sec_xbrl_facts_ingestion | 900_060 | global | sec_xbrl_facts | SEC XBRL Company Facts bulk (local) | On-demand (local dev)`
   - Add `sec_xbrl_facts` to the global-tables list under Critical Rules.
   - Add `COMPANYFACTS_DIR` to Environment Variables section with note: "local path to SEC Company Facts bulk JSON; dev-only until follow-up PR wires HTTP delta ingestion."
2. `.env.example` — add `COMPANYFACTS_DIR=` placeholder with comment.
3. `pyproject.toml` — add `ijson` if not already present. No other deps.
4. `backend/app/core/jobs/__init__.py` (or worker registry) — register the new worker if the repo has a central registry; otherwise skip.

## Implementation hints

### Parser seam

Keep parsing pure (no DB) so it can be unit-tested in isolation:

```python
# backend/app/core/jobs/_sec_xbrl_parser.py
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True, slots=True)
class XbrlFact:
    cik: int
    taxonomy: str
    concept: str
    unit: str
    period_end: date
    period_start: date | None
    val: Decimal | None
    val_text: str | None
    accn: str
    fy: int | None
    fp: str | None
    form: str
    filed: date

def iter_facts_from_file(path: Path) -> Iterator[XbrlFact]:
    ...
```

Worker consumes the iterator and batches into COPY.

### Batched COPY

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE _stg (LIKE sec_xbrl_facts INCLUDING DEFAULTS) ON COMMIT DROP;")
        await conn.copy_records_to_table("_stg", records=batch, columns=COLS)
        await conn.execute("""
            INSERT INTO sec_xbrl_facts (...)
            SELECT ... FROM _stg
            ON CONFLICT (cik, taxonomy, concept, unit, period_end, accn) DO NOTHING;
        """)
```

### Non-numeric observations

`dei` has concepts like `EntityRegistrantName` where `val` is a string. Two options: (a) store in `val_text`, leaving `val` NULL; (b) skip non-numeric entirely with debug log. **Choose (a)** — cheap and preserves data for later. Document in the model docstring.

### Universe filtering

Out of scope this PR. All 19,330 files ingested. Matview in PR-Q8 will JOIN to `instruments_universe` via `sec_cik` to narrow to investable names.

### Advisory lock

Use existing helper (look for `try_advisory_lock`/`acquire_advisory_lock` in `backend/app/core/runtime/` — the `nport_ingestion` worker uses it). Do **not** use Python `hash()` for the key — `LOCK_ID = 900_060` is already an int and goes straight to `pg_try_advisory_lock(900060)`. If a helper expects a string, use `zlib.crc32(b"sec_xbrl_facts_ingestion")` per CLAUDE.md Critical Rules.

### Storage dual-write

**Skip** for this PR. The source is already durable JSON on disk; re-ingesting from the same bulk is trivial. Productionisation PR will add `silver/_global/sec/xbrl/companyfacts/{cik}.json.zst` mirror + delta pull.

## Acceptance gates

- `make check` green (lint, typecheck, architecture, tests)
- Migration 0166 reversible (drops hypertable + compression policy cleanly)
- `python -m backend.scripts.run_sec_xbrl_facts_ingestion --limit 10` completes <30s on Andrei's machine
- Full-dir run: worker processes all 19,330 files without crashing; `failed_files` logged and below 1% (malformed files tolerated)
- Re-running full ingestion on a populated DB inserts **0 new rows** (idempotency)
- Row count sanity check (after full run): `SELECT COUNT(*) FROM sec_xbrl_facts` in the tens of millions; `SELECT COUNT(DISTINCT cik)` ≈ 19,330
- Restatement integrity check: `SELECT cik, concept, period_end, unit, COUNT(DISTINCT accn) FROM sec_xbrl_facts GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT accn) > 1 LIMIT 5;` returns rows (proves 10-K/A co-exists with 10-K)
- Compression policy active: `SELECT hypertable_name, segmentby, orderby FROM timescaledb_information.compression_settings WHERE hypertable_name='sec_xbrl_facts';` returns expected row
- No new network calls introduced (grep new files: no `httpx`, `requests`, `aiohttp`, `data.sec.gov`)
- `CLAUDE.md` and `.env.example` updated

## Non-goals

- SEC HTTP delta ingestion (follow-up PR)
- Scheduler / Railway cron registration
- Computing P/E, P/B, EV/EBITDA, market cap (PR-Q8 matview)
- Wiring XBRL data into any route, DD chapter, or scoring component (PR-Q9)
- Universe filtering by `instruments_universe`
- IFRS filers (ingest `ifrs-full` taxonomy if present in file, but do not specialise logic)
- Admin UI, metrics dashboard, Prometheus counters
- Storage dual-write to silver layer
- Prod DB deployment

## Branch + commit

```
feat/sec-xbrl-companyfacts-worker
```

PR title: `feat(ingest/sec-xbrl): companyfacts bulk ingestion into sec_xbrl_facts hypertable (local dev)`

PR body must include:
- Summary of the pivot (Tiingo Fundamentals add-on unavailable → SEC Company Facts bulk locally)
- Row count + entity count after full ingestion on Andrei's machine
- One restatement example (concrete CIK, concept, period_end with ≥2 accns)
- Link to this prompt file
- Explicit mention that prod (HTTP delta + scheduler) is a follow-up PR
