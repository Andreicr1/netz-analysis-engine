## Summary
PR-Q7.1 delivery per spec. Parallelize sec_xbrl_facts_ingestion using asyncpg COPY and ProcessPoolExecutor.

## Changes
- `backend/app/core/jobs/sec_xbrl_facts_ingestion.py` — rewrote for parallel processing with `asyncpg` COPY
- `backend/scripts/run_sec_xbrl_facts_ingestion.py` — added `--workers` flag
- Preserved zero schema, parser, or test changes.

## Scope
Performance optimization (Target speedup: 20-30x. Wall clock: 2-4h → 10-20min).

## Test plan
- [x] All 17 existing Q7 tests pass unchanged
- [x] Smoke run completes <15s
- [x] Idempotency preserved
- [x] Advisory lock preserved

🤖 Generated with Gemini session