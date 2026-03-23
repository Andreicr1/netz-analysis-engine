# Backend E2E Smoke Test — All Services & Connections

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Goal

Run a comprehensive E2E smoke test of every backend service, external API connection, and data pipeline. This is a **read-only test** — seed temporary data, verify results, then clean up. No code changes.

All tests use `TEST_ORG = UUID('00000000-0000-0000-0000-000000000001')` and clean up after themselves.

**Prerequisites:** `docker-compose up` (PostgreSQL + Redis), `.env` with API keys (OpenAI, Mistral, Clerk, FRED, DC_API_KEY, R2 credentials).

---

## Reference Files

```
# Load env
from dotenv import load_dotenv; load_dotenv('../.env')

# DB setup
backend/app/core/db/session.py          # AsyncSession factory
backend/app/core/config/settings.py     # Settings

# Providers
backend/app/services/providers/__init__.py              # get_instrument_provider()
backend/app/services/providers/yahoo_finance_provider.py
backend/app/services/storage_client.py                  # StorageClient

# Workers
backend/app/domains/wealth/workers/instrument_ingestion.py  # run_instrument_ingestion
backend/app/domains/wealth/workers/benchmark_ingest.py
backend/app/domains/wealth/workers/ingestion.py

# Quant engine (pure computation)
backend/quant_engine/cvar_service.py
backend/quant_engine/regime_service.py
backend/quant_engine/optimizer_service.py
backend/quant_engine/scoring_service.py
backend/quant_engine/drift_service.py
backend/quant_engine/rebalance_service.py
backend/quant_engine/stress_severity_service.py
backend/quant_engine/talib_momentum_service.py
backend/quant_engine/portfolio_metrics_service.py
backend/quant_engine/backtest_service.py

# External API clients
backend/quant_engine/fred_service.py
backend/quant_engine/fiscal_data_service.py
backend/quant_engine/data_commons_service.py
backend/quant_engine/ofr_hedge_fund_service.py

# AI Pipeline
backend/ai_engine/classification/hybrid_classifier.py  # classify()
backend/ai_engine/extraction/semantic_chunker.py        # chunk_document()
backend/ai_engine/extraction/mistral_ocr.py             # async_extract_pdf_with_mistral()
backend/ai_engine/extraction/embedding_service.py       # async_generate_embeddings()
backend/ai_engine/pipeline/validation.py                # validate_ocr_output, validate_classification, etc.
backend/ai_engine/pipeline/unified_pipeline.py          # process() — full pipeline
backend/ai_engine/pipeline/models.py                    # IngestRequest, PipelineStageResult
backend/vertical_engines/credit/memo/service.py         # generate_memo_book, async_generate_memo_book
backend/vertical_engines/credit/memo/chapter_engine.py  # single chapter generation

# Models
backend/app/domains/wealth/models/instrument.py
backend/app/domains/wealth/models/nav.py
backend/app/domains/wealth/models/dd_report.py  # DDReport + DDChapter (approval fields: approved_by, approved_at, rejection_reason)

# DD Report Approval (Group 7)
backend/app/domains/wealth/routes/dd_reports.py      # approve_dd_report, reject_dd_report endpoints
backend/app/domains/wealth/schemas/dd_report.py      # DDReportRejectRequest, DDReportSummary (with approval fields)
backend/app/domains/wealth/routes/fact_sheets.py     # download_dd_report_pdf (approval gate)
backend/vertical_engines/wealth/dd_report/dd_report_engine.py  # _persist_results sets pending_approval
backend/vertical_engines/wealth/dd_report/models.py  # ChapterResult
backend/app/core/db/migrations/versions/0021_dd_report_approval_fields.py
```

---

## Test Structure

Write a single Python script `backend/tests/e2e_smoke_test.py` that can be run with `python tests/e2e_smoke_test.py` from the `backend/` directory. Use `asyncio.run()` at the top level. Print clear pass/fail for each test group.

Output format per test:
```
[PASS] Test name — brief result (e.g., "5 instruments, 305 NAV rows")
[FAIL] Test name — error message
[SKIP] Test name — reason (e.g., "MISTRAL_API_KEY not set")
```

Summary at the end: `X passed, Y failed, Z skipped`.

---

## Test Groups

### Group 1: Infrastructure Connections

**1.1 PostgreSQL** — Connect via asyncpg, check version, extensions (pgvector, timescaledb), table count, migration head.

**1.2 Redis** — SET/GET/PUBLISH, check version.

**1.3 Cloudflare R2** — List top-level prefixes in bucket (bronze/, silver/, gold/). Skip if `R2_ACCESS_KEY_ID` not set.

### Group 2: External API Connections

**2.1 OpenAI** — Chat completion (gpt-4o-mini, "Reply with CONNECTION_OK", max_tokens=10) + embedding (text-embedding-3-large, single string, verify dim=3072). Skip if `OPENAI_API_KEY` not set.

**2.2 Mistral** — List models, verify `mistral-ocr-latest` exists. Skip if `MISTRAL_API_KEY` not set.

**2.3 Clerk** — Fetch JWKS, verify RS256 key exists. Skip if `CLERK_JWKS_URL` not set.

**2.4 FRED** — Fetch DFF (Fed Funds Rate), last 3 observations. Skip if `FRED_API_KEY` not set.

**2.5 US Treasury Fiscal Data** — `fetch_treasury_rates('2026-01-01')`, verify >0 records. No auth needed.

**2.6 OFR Hedge Fund Monitor** — `fetch_industry_size('2024-01-01')`, verify >0 snapshots. No auth needed.

**2.7 Data Commons** — `resolve_entity('California', 'State')`, verify returns `geoId/06`. Skip if `DC_API_KEY` not set.

### Group 3: Instrument Provider Pipeline

**3.1 Provider factory** — Call `get_instrument_provider()`, verify returns `YahooFinanceProvider` (feature flag off).

**3.2 fetch_batch** — Fetch metadata for `['SPY', 'AGG', 'GLD', 'VWO', 'ARKK']`. Verify 5 results, each has name, type, currency, raw_attributes.

**3.3 fetch_batch_history** — Fetch 1mo history for same tickers. Verify 5 DataFrames, each with >15 rows.

**3.4 DB round-trip** — Insert 5 instruments into `instruments_universe` (TEST_ORG), run `run_instrument_ingestion(db, TEST_ORG, lookback_days=30)`, verify `nav_timeseries` has >50 rows. **Clean up at end.**

### Group 4: Quant Engine (Pure Computation)

Use returns from Group 3.4 nav_timeseries (or synthetic data if Group 3 failed).

**4.1 CVaR** — `compute_cvar_from_returns(returns, 0.95)` for each ticker. Verify CVaR < 0 (it's a loss). Also test `check_breach_status('moderate', cvar, 0, None)`.

**4.2 Regime Classification** — `classify_regime_multi_signal(vix=18, yield_curve_spread=0.5, cpi_yoy=2.5, sahm_rule=0.2)` → verify returns `RISK_ON`. Test crisis scenario (vix=45) → verify returns `CRISIS`.

**4.3 Portfolio Optimizer** — Build 5x5 covariance matrix from returns, compute expected returns. Call `optimize_portfolio(block_ids, expected_returns, cov_dict, {}, 0.04, 'max_sharpe')`. Verify weights sum to ~1.0, Sharpe ratio > 0.

**4.4 Portfolio Metrics** — `aggregate(portfolio_returns, benchmark_returns, 0.04, None)`. Verify Sharpe, Sortino, max_drawdown are finite numbers.

**4.5 Scoring** — `compute_fund_score(RiskMetrics(...), None, 50.0, None)` for each ticker. Verify score in 0-100.

**4.6 Drift Detection** — `compute_block_drifts(current_weights, target_weights, 0.05, 0.10)` with intentional drift. Verify at least one "maintenance" or "urgent" status.

**4.7 Rebalance Cascade** — `determine_cascade_action('warning', 'ok', 0.85, 0, 'moderate', None)`. Verify returns non-None event.

**4.8 Stress Severity** — `compute_stress_severity({'macro': {'vix': 35, 'yield_curve_10y_2y': -0.3}}, None)`. Verify score > 0, level in ('none','mild','moderate','severe').

**4.9 Momentum** — `compute_momentum_signals_talib(nav_array)` for one ticker (reconstruct NAV from returns). Verify momentum_score in 0-100. Graceful degradation if talib not installed.

**4.10 Backtest** — `walk_forward_backtest(returns_matrix, equal_weights, n_splits=3)` if sklearn available. Verify returns dict with folds. Skip if sklearn not installed.

### Group 5: Regime from DB (requires FRED data)

**5.1 Regime from macro_data** — Check if `macro_data` table has recent rows. If yes, call `get_current_regime(db, None, 'RISK_ON')`. Verify returns a regime string. If no macro_data, skip with note.

### Group 6: Wealth Document Pipeline (light check)

**6.1 Document models** — Verify `WealthDocument` and `WealthDocumentVersion` tables exist in DB (just check table exists, don't insert).

**6.2 Storage client** — Instantiate `StorageClient`, verify it initializes without error. If R2 enabled, list a prefix. If local, verify `.data/lake/` path logic.

---

### Group 7: DD Report Approval Workflow

Tests the full approve/reject lifecycle added in commit 23aa467. Requires PostgreSQL with migration 0021 applied (`alembic upgrade head`).

**7.1 Migration check** — Verify `dd_reports` table has columns `approved_by`, `approved_at`, `rejection_reason`. Use `SELECT column_name FROM information_schema.columns WHERE table_name = 'dd_reports' AND column_name IN ('approved_by', 'approved_at', 'rejection_reason')`. Expect 3 rows.

**7.2 Seed DD Report in pending_approval** — Insert a DDReport with `status='pending_approval'`, `created_by='smoke-creator'`, `organization_id=TEST_ORG`, `instrument_id=<random UUID>`, `version=1`, `is_current=true`. Also insert one DDChapter linked to it. Store report_id for subsequent tests.

**7.3 Approve endpoint — happy path** — `POST /api/v1/dd-reports/{report_id}/approve` with X-DEV-ACTOR header `{"actor_id": "smoke-reviewer", "roles": ["INVESTMENT_TEAM"], "org_id": "<TEST_ORG>"}`. Verify:
- Response 200
- `status == "approved"`
- `approved_by == "smoke-reviewer"`
- `approved_at` is not null

**7.4 Self-approval blocked** — Reset the report to `pending_approval` (direct SQL UPDATE). Then `POST /approve` with X-DEV-ACTOR `actor_id: "smoke-creator"` (same as `created_by`). Verify 403 with "Self-approval" in detail.

**7.5 Wrong status returns 409** — With report still in `approved` status (from 7.3), call `POST /approve` again. Verify 409.

**7.6 Reject endpoint — happy path** — Reset report to `pending_approval` (SQL UPDATE). `POST /api/v1/dd-reports/{report_id}/reject` with body `{"reason": "Smoke test: insufficient evidence on liquidity risk analysis."}` and reviewer actor. Verify:
- Response 200
- `status == "draft"`
- `rejection_reason` contains "liquidity risk"

**7.7 Reject validation — short reason** — `POST /reject` with `{"reason": "short"}`. Verify 422 (Pydantic min_length=10).

**7.8 Status filter on list** — Insert a second DDReport with `status='approved'` for the same `instrument_id`. Call `GET /api/v1/dd-reports/funds/{instrument_id}?status=approved`. Verify response is a list with exactly 1 item (the approved one, not the draft one from 7.6).

**7.9 Status filter without param** — `GET /api/v1/dd-reports/funds/{instrument_id}` (no filter). Verify response contains 2 reports (both draft and approved).

**7.10 Download gate — draft blocked** — `GET /api/v1/fact-sheets/dd-reports/{report_id}/download` where report is in `draft` status. Verify 400 with "not ready" in detail.

**7.11 Download gate — approved allowed** — Switch report to `approved` (SQL UPDATE). Same download call. Verify 200 and response content-type is `application/pdf`. (May fail if fund doesn't exist — acceptable, just verify it's NOT a 400 "not ready" error.)

**7.12 Engine pending_approval verification** — Import `DDReportEngine` from `vertical_engines.wealth.dd_report.dd_report_engine` and `ChapterResult` from `vertical_engines.wealth.dd_report.models`. Instantiate engine, call `_persist_results()` with a mock db session and 8 completed chapters. Verify `mock_report.status == "pending_approval"`. Then repeat with one failed chapter — verify `mock_report.status == "draft"`.

**Cleanup:** DELETE FROM `dd_chapters` WHERE `organization_id = TEST_ORG`. DELETE FROM `dd_reports` WHERE `organization_id = TEST_ORG`.

---

### Group 8: AI Pipeline (Classification, OCR, Chunking, Embedding, Memo)

These tests exercise the document processing and IC memo generation pipeline. Some require API keys (OpenAI, Mistral).

**8.1 Hybrid Classifier (standalone, no API)** — Call `classify(text="Fund Limited Partnership Agreement with GP obligations and LP capital commitments...", filename="Fund_VI_LPA_Final.pdf")`. Verify `doc_type="legal_lpa"`, `layer=1` (rules), `confidence=1.0`. Also test Layer 2 with an ambiguous filename: `classify(text="This document describes the fee structure...", filename="document_scan_001.pdf")` — should fall to cosine similarity (layer=2). Import from `ai_engine.classification.hybrid_classifier`.

**8.2 Semantic Chunker (standalone, no API)** — Call `chunk_document(ocr_markdown, doc_id="test-doc", doc_type="fund_presentation", metadata={"source_file": "test.pdf"})` with a synthetic markdown string containing headers, a table, and financial figures. Verify: chunks returned > 0, each chunk has `chunk_id`, `content`, `section_type`, `has_table`, `has_numbers`. Import from `ai_engine.extraction.semantic_chunker`.

**8.3 Mistral OCR** — Create a minimal test PDF (use `reportlab` or a small static PDF file). Call `async_extract_pdf_with_mistral(pdf_bytes)`. Verify returns list of `PageBlock` with non-empty text. Skip if `MISTRAL_API_KEY` not set. Import from `ai_engine.extraction.mistral_ocr`.

**8.4 Embedding** — Call `async_generate_embeddings(["Fund Limited Partnership Agreement", "Net Asset Value Report Q1 2026"])`. Verify: `batch.count == 2`, `len(batch.vectors[0]) == 3072`, `batch.model` contains "embedding". Skip if `OPENAI_API_KEY` not set. Import from `ai_engine.extraction.embedding_service`.

**8.5 Validation Gates** — Test each pipeline validation function with valid and invalid inputs:
- `validate_ocr_output(text)` — pass with 200 chars of text, fail with 10 chars
- `validate_classification(result)` — pass with confidence ≥ 0.3, fail with 0.1
- `validate_chunks(chunks)` — pass with non-empty list, fail with empty
- `validate_embeddings(vectors, expected_dim=3072)` — pass with correct dim, fail with wrong dim
Import from `ai_engine.pipeline.validation`.

**8.6 IC Memo Chapter Generation (single chapter, requires OpenAI)** — Test a single chapter generation using the chapter engine directly (not the full memo book). Import from `vertical_engines.credit.memo.chapter_engine`. Call with minimal inputs:
- `chapter_name`: "executive_summary"
- `evidence_text`: synthetic deal context (2-3 paragraphs about a hypothetical loan)
- `call_openai_fn`: real OpenAI call (use gpt-4o-mini for cost efficiency)
Verify: returns non-empty markdown string. Skip if `OPENAI_API_KEY` not set.

**8.7 Full Pipeline Integration (mini, requires Mistral + OpenAI)** — If both API keys are available, test the full pipeline flow with a synthetic PDF:
1. OCR the PDF → get markdown
2. Classify the markdown → get doc_type
3. Chunk the markdown → get chunks
4. Embed chunks → get vectors
5. Verify dimensional consistency (all vectors are 3072-dim)
Do NOT write to storage or pgvector — just verify the data flows through each stage. Skip if either `MISTRAL_API_KEY` or `OPENAI_API_KEY` not set.

---

## Cleanup

After all tests, delete from `dd_chapters`, `dd_reports`, `instruments_universe`, and `nav_timeseries` where `organization_id = TEST_ORG`. Use a try/finally block to guarantee cleanup even on test failure. Order matters: `dd_chapters` before `dd_reports` (FK constraint).

---

## Script Structure

```python
#!/usr/bin/env python
"""E2E smoke test — run from backend/ directory."""
import asyncio, os, sys, uuid, time, traceback
from dotenv import load_dotenv
load_dotenv('../.env')

TEST_ORG = uuid.UUID('00000000-0000-0000-0000-000000000001')
TICKERS = ['SPY', 'AGG', 'GLD', 'VWO', 'ARKK']

passed = failed = skipped = 0

def ok(name, detail=""): ...
def fail(name, detail=""): ...
def skip(name, reason=""): ...

async def main():
    # Setup DB engine
    # Run all groups
    # Cleanup
    # Print summary

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Critical Rules

- **Never leave test data behind** — always clean up TEST_ORG rows
- **Skip, don't fail** when an API key is missing — the test should still run the groups it can
- **Timeout each external API call** at 15s — don't hang on network issues
- **Print elapsed time** per group
- **Do not modify any code** — this is a test-only script
- **Use SET LOCAL** for RLS context in all DB operations
- **Do not import from route handlers** — only import from models, services, and quant_engine
- **Group 7 endpoint tests** use `httpx.AsyncClient` with `ASGITransport(app=app)` and `X-DEV-ACTOR` header (requires `APP_ENV=development` env var). This is the exception — route testing requires the ASGI app.
- **Group 7 X-DEV-ACTOR header format:** `{"actor_id": "<id>", "roles": ["INVESTMENT_TEAM"], "fund_ids": [], "org_id": "<TEST_ORG as string>"}`
