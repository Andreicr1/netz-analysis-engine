---
pr_id: PR-Q7
title: "feat(ingest/tiingo-fundamentals): statements + daily hypertables + worker 900_060"
branch: feat/tiingo-fundamentals-worker
sprint: S3 (parallel with PR-Q5)
dependencies: []
loc_estimate: 950
reviewer: data-platform
---

# Opus Prompt — PR-Q7: Tiingo Fundamentals Worker

## Goal

Ship a production-grade daily worker that ingests Tiingo Fundamentals API data (statements + daily metrics) into two TimescaleDB hypertables. Seeds universe = top 500 US equities. This unblocks PR-Q8 (characteristics matview) and PR-Q9 (G5 IPCA prod).

## Spec references (READ FIRST)

- `docs/superpowers/specs/2026-04-19-edhec-gaps-data-layer.md` §5 (migration 0134 DDL, worker spec, universe seed)
- `docs/superpowers/specs/2026-04-19-edhec-gaps-followup.md` §7 (Tiingo Final Design, coverage confirmed, cost, ToS)
- `CLAUDE.md` §Data Ingestion Workers, §Stability Guardrails
- Tiingo docs: https://www.tiingo.com/documentation/fundamentals
- `backend/app/core/jobs/nport_ingestion.py` as reference pattern
- `backend/app/core/jobs/live_price_poll.py` (lock 900_100) as reference for Tiingo client usage

## Files to create

1. `backend/alembic/versions/0134_tiingo_fundamentals.py` — hypertables DDL per data-layer spec §5.1 (two tables: `tiingo_fundamentals_statements`, `tiingo_fundamentals_daily`). Compression policies. Idempotent.
2. `backend/app/core/jobs/tiingo_fundamentals_ingestion.py` — worker with lock 900_060.
3. `backend/app/services/tiingo_fundamentals_client.py` — async Tiingo REST client wrapping `/tiingo/fundamentals/{ticker}/statements` and `/tiingo/fundamentals/{ticker}/daily`. If `backend/app/services/tiingo_client.py` already exists for live prices, extend it rather than duplicate.
4. `backend/scripts/seed_tiingo_universe.py` — CLI that populates universe of top 500 US equities by market cap from `instruments_universe` (asset_class IN equity_us_*).
5. `backend/tests/integration/test_tiingo_fundamentals_worker.py` — ≥12 integration tests (mock Tiingo responses via `pytest-httpx` or similar).
6. `backend/tests/app/services/test_tiingo_fundamentals_client.py` — ≥5 unit tests for client retry, rate limit, restatement handling.

## Files to modify

1. `CLAUDE.md` Data Ingestion Workers table — add row: `tiingo_fundamentals_ingestion | 900_060 | global | tiingo_fundamentals_statements, tiingo_fundamentals_daily | Tiingo REST (fundamentals) | Daily`
2. `backend/app/core/config.py` (or equivalent) — add env var `TIINGO_API_KEY` (required for Power tier).
3. `pyproject.toml` — no new deps if Tiingo client already used; add `httpx-retries` if retry policy not present.

## Implementation hints

### Worker skeleton

```python
# backend/app/core/jobs/tiingo_fundamentals_ingestion.py
import asyncio
import logging
from datetime import datetime, timezone
from zlib import crc32
from backend.app.core.runtime import ExternalProviderGate, try_advisory_lock

LOCK_ID = 900_060
logger = logging.getLogger(__name__)

async def run():
    got = await try_advisory_lock(LOCK_ID)
    if not got:
        logger.info("tiingo_fundamentals_ingestion: lock held, skipping")
        return
    try:
        async with ExternalProviderGate.bulk(timeout_sec=300) as gate:
            universe = await load_universe()  # 500 tickers
            semaphore = asyncio.Semaphore(8)  # concurrency cap
            async def process(ticker):
                async with semaphore:
                    await ingest_ticker(ticker, gate)
            await asyncio.gather(*[process(t) for t in universe])
    finally:
        await release_advisory_lock(LOCK_ID)
```

### Client retry + rate limit

```python
# backend/app/services/tiingo_fundamentals_client.py
class TiingoFundamentalsClient:
    def __init__(self, api_key, base_url="https://api.tiingo.com"):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Token {api_key}"},
            timeout=httpx.Timeout(30.0, connect=5.0),
        )

    @retry(stop=stop_after_attempt(4),
           wait=wait_exponential(multiplier=1, min=2, max=30),
           retry=retry_if_exception_type(httpx.HTTPStatusError))
    async def get_statements(self, ticker: str, start_date: date | None = None):
        resp = await self._client.get(f"/tiingo/fundamentals/{ticker}/statements",
                                      params={"startDate": start_date.isoformat() if start_date else None})
        resp.raise_for_status()
        return resp.json()

    @retry(...)
    async def get_daily(self, ticker: str, start_date: date | None = None):
        ...
```

### Restatement handling

PK on statements includes `filing_date`. Upsert via `ON CONFLICT (ticker, period_end, statement_type, line_item, filing_date) DO UPDATE SET value = EXCLUDED.value` — idempotent, preserves history.

### Dual-write (storage + DB)

Per CLAUDE.md Data Lake Rules: write raw JSON payload to StorageClient `silver/_global/tiingo/statements/{ticker}/{filing_date}.json.zst` BEFORE upserting hypertable. If storage write fails, log warning and continue (storage is source of truth but worker must keep moving).

### Schedule

Daily 04:00 UTC (after `nport_ingestion` 03:00 UTC). Configure in whatever scheduler layer the repo uses (Railway cron, APScheduler, etc.). Verify by reading `CLAUDE.md` and any `backend/app/core/jobs/scheduler.py`.

### Universe seed query

```sql
SELECT instrument_id, ticker, name
FROM instruments_universe
WHERE asset_class IN ('equity_us_large', 'equity_us_mid', 'equity_us_small')
  AND is_active = true
ORDER BY market_cap_usd DESC NULLS LAST
LIMIT 500;
```

Store universe as a static list `backend/app/core/jobs/tiingo_universe.py` regenerated by the seed script.

## Tests

### Client unit tests (≥5)
1. Retry on 429 with exponential backoff
2. Retry on 503 up to 4 attempts then raise
3. Auth header injected correctly
4. Response parsed into dataclass
5. Timeout respected

### Worker integration tests (≥12)
1. Advisory lock acquired + released
2. Concurrent invocation: second call exits gracefully
3. Universe load: 500 tickers fetched from instruments_universe
4. Statements ingest: upsert inserts new rows
5. Statements restatement: same (ticker, period_end, statement_type, line_item) with newer filing_date inserts new row (does NOT overwrite old filing_date)
6. Daily ingest: upserts by (ticker, as_of)
7. Rate limit respected: semaphore cap of 8 concurrent requests
8. External gate timeout: bulk gate 5min enforced
9. Storage dual-write: silver parquet file created before hypertable upsert
10. Storage write failure: worker continues with warning
11. Tiingo API 5xx: retry and eventual failure logged per ticker, worker does not crash
12. Idempotent: re-running worker same day → no duplicate rows, no errors

## Acceptance gates

- `make check` green
- Migration 0134 reversible (drops both hypertables cleanly)
- Worker completes end-to-end on 5-ticker fixture in <30s
- Storage write before DB upsert verified in test
- No EDGAR/FRED calls introduced
- `TIINGO_API_KEY` documented in `.env.example` and `CLAUDE.md` env vars section
- Compression policy active on both hypertables (verify via `timescaledb_information.compression_settings`)
- Idempotent re-run: no duplicate rows on second execution

## Non-goals

- Do NOT compute characteristics (size, B/M, etc.) in this PR — that's PR-Q8
- Do NOT wire Tiingo data into any route or DD chapter — PR-Q9
- Do NOT extend beyond the statements + daily endpoints (no /metrics, /news, etc.)
- Do NOT build admin UI for Tiingo
- Do NOT upgrade to Enterprise tier — Power is sufficient for dev

## Branch + commit

```
feat/tiingo-fundamentals-worker
```

PR title: `feat(ingest/tiingo-fundamentals): statements + daily hypertables + worker 900_060`
