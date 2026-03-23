# Wealth DD Report & Fact Sheet Approval Workflow + Full Verification

Fresh session prompt. Read `CLAUDE.md` first for critical rules.

---

## Part 1: Gap Analysis — DD Report & Fact Sheet Approval Cycle

### Problem

The wealth vertical has backend services for DD reports and fact sheets, but the **approval workflow cycle is incomplete**. The frontend allows generating DD reports for funds and fact sheets for model portfolios, but the full cycle of **generate → review → approve/reject → publish → download** is not fully wired.

### Investigation Required

Read these files and map the complete lifecycle:

```
# DD Report backend
backend/app/domains/wealth/routes/dd_reports.py
backend/vertical_engines/wealth/dd_report/dd_report_engine.py

# Fact Sheet backend
backend/app/domains/wealth/routes/fact_sheets.py

# Content approval backend (may be shared)
backend/app/domains/wealth/routes/content.py

# Frontend pages
frontends/wealth/src/routes/(team)/dd-reports/+page.svelte
frontends/wealth/src/routes/(team)/dd-reports/[fundId]/+page.svelte
frontends/wealth/src/routes/(team)/dd-reports/[fundId]/[reportId]/+page.svelte
frontends/wealth/src/routes/(investor)/fact-sheets/+page.svelte

# Audit report
docs/audit/endpoint-frontend-coverage-audit.md
```

Answer these questions:

1. **DD Report lifecycle:** What are all the backend endpoints for DD reports? Which ones have frontend consumers? Is there an approve/reject flow? Can a generated DD report be published to the investor portal?

2. **Fact Sheet lifecycle:** Same questions. Can fact sheets be regenerated? Is there a version history? Download flow?

3. **Bond-specific:** Are there DD report templates or fact sheet templates specific to bonds vs funds? Do bonds go through a different approval path? Check if `instrument_type` affects the DD report or fact sheet generation.

4. **Content approval bridge:** The `/content` routes have an approve endpoint (`POST /content/{id}/approve`). Do DD reports and fact sheets flow through this? Or do they have their own approval mechanism?

5. **Investor portal delivery:** Once approved, how does a DD report or fact sheet reach the investor portal? Check investor routes (`/investor/documents`, `/investor/report-packs`).

### Deliverable

Write a gap analysis document to `docs/audit/wealth-dd-factsheet-workflow-gap.md` with:
- Current state diagram (what works end-to-end today)
- Missing links (backend exists but no frontend, or no backend endpoint at all)
- Recommended implementation plan (prioritized)

Then create an implementation prompt at `docs/prompts/wealth-dd-factsheet-approval-workflow-prompt.md` with precise steps to close the gaps.

---

## Part 2: Full System Verification Checklist

Run ALL of the following verifications and report results. This is a comprehensive health check of everything implemented in the 2026-03-19 session.

### 2.1 Git State

```bash
git status                        # Should be clean (no uncommitted changes)
git log --oneline origin/main..HEAD  # Should be 0 (all pushed)
git log --oneline -10             # Show recent commits for reference
```

### 2.2 Backend Tests

```bash
cd backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
# Expected: 1506+ tests passing
```

### 2.3 Frontend Builds

```bash
cd frontends/wealth && pnpm check 2>&1 | tail -5    # 0 errors
cd frontends/admin && pnpm check 2>&1 | tail -5     # 0 errors
cd frontends/credit && pnpm check 2>&1 | tail -5    # 0 errors
```

### 2.4 Import Architecture

```bash
cd backend && python -m importlinter 2>&1 | tail -10
# Expected: 30/30 contracts kept
```

### 2.5 Infrastructure Connections

```python
# PostgreSQL
import asyncpg
conn = await asyncpg.connect('postgresql://netz:password@localhost:5434/netz_engine')
version = await conn.fetchval('SELECT version()')
tables = await conn.fetch("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
head = await conn.fetchval('SELECT version_num FROM alembic_version')
# Expected: PG 16, 104+ tables, head=0020_wealth_docs

# Redis
import redis.asyncio as aioredis
r = aioredis.from_url('redis://localhost:6379/0')
await r.set('health', 'ok', ex=5)
val = await r.get('health')
# Expected: val == 'ok'
```

### 2.6 External API Connections

Test each API (skip if key not in .env):

| API | Test | Expected |
|-----|------|----------|
| OpenAI | Chat completion (gpt-4o-mini, "CONNECTION_OK") | Response contains "CONNECTION_OK" |
| OpenAI | Embedding (text-embedding-3-large, 1 string) | dim=3072 |
| Mistral | List models | mistral-ocr-latest in list |
| Clerk | Fetch JWKS | RS256 key present |
| FRED | Fetch DFF series, last 3 obs | 3 observations returned |
| US Treasury | fetch_treasury_rates('2026-01-01') | >0 records |
| OFR | fetch_industry_size('2024-01-01') | >0 snapshots |
| Data Commons | resolve_entity('California', 'State') | geoId/06 |
| R2 | List bucket prefixes | bronze/, silver/, gold/ |

### 2.7 Provider Pipeline E2E

```python
# 1. Provider factory returns YahooFinanceProvider
provider = get_instrument_provider()
assert type(provider).__name__ == 'YahooFinanceProvider'

# 2. Fetch 5 instruments
raw = provider.fetch_batch(['SPY', 'AGG', 'GLD', 'VWO', 'ARKK'])
assert len(raw) == 5

# 3. Insert into DB, run worker, verify NAV rows
# (use TEST_ORG, clean up after)
result = await run_instrument_ingestion(db, TEST_ORG, lookback_days=30)
assert result['instruments_processed'] == 5
assert result['rows_upserted'] > 50

# 4. Clean up
```

### 2.8 Quant Engine Smoke

Test each service with synthetic data:

| Service | Test | Expected |
|---------|------|----------|
| cvar_service | compute_cvar_from_returns(random_returns, 0.95) | CVaR < 0 |
| regime_service | classify_regime_multi_signal(vix=18, spread=0.5, cpi=2.5, sahm=0.2) | RISK_ON |
| optimizer_service | optimize_portfolio(5 assets, max_sharpe) | weights sum ≈ 1.0 |
| scoring_service | compute_fund_score(mock_metrics) | 0 < score < 100 |
| drift_service | compute_block_drifts(drifted_weights, targets) | ≥1 maintenance/urgent |
| stress_severity | compute_stress_severity(mock_snapshot) | level in valid set |
| momentum | compute_momentum_signals_talib(nav_array) | score 0-100 |
| portfolio_metrics | aggregate(returns, benchmark, 0.04) | finite Sharpe |
| rebalance | determine_cascade_action('warning','ok',0.85,0,'moderate') | non-None event |

### 2.9 AI Pipeline Smoke

| Component | Test | Expected |
|-----------|------|----------|
| Hybrid classifier | classify(text="Fund LPA...", filename="Fund_VI_LPA.pdf") | doc_type=legal_lpa, layer=1 |
| Semantic chunker | chunk_document(markdown, "test", "fund_presentation", {}) | >0 chunks |
| Embedding | async_generate_embeddings(["test string"]) | dim=3072 |
| Validation gates | validate_ocr_output("x"*200) | passes |

### 2.10 Endpoint Coverage

```bash
# Count from audit report
grep -c "CONNECTED" docs/audit/endpoint-frontend-coverage-audit.md
grep -c "DISCONNECTED" docs/audit/endpoint-frontend-coverage-audit.md
grep -c "Phantom" docs/audit/endpoint-frontend-coverage-audit.md
# Expected: 152 connected, 34 disconnected, 3 phantom (all credit)
```

### 2.11 New Files Inventory

Verify all files created in the 2026-03-19 sessions exist:

```
# Data layer (session 1)
backend/app/services/providers/fefundinfo_client.py
backend/app/services/providers/fefundinfo_provider.py
backend/quant_engine/fiscal_data_service.py
backend/quant_engine/data_commons_service.py
backend/quant_engine/ofr_hedge_fund_service.py
backend/app/domains/wealth/models/document.py
backend/app/domains/wealth/schemas/document.py
backend/app/domains/wealth/services/document_service.py
backend/app/domains/wealth/routes/documents.py
backend/app/core/db/migrations/versions/0020_wealth_documents.py

# Instrument ingestion (session 2)
backend/app/domains/wealth/workers/instrument_ingestion.py

# Frontend UX (session 3)
frontends/wealth/src/routes/(team)/documents/+page.svelte
frontends/wealth/src/routes/(team)/documents/upload/+page.svelte
frontends/wealth/src/routes/(team)/documents/[documentId]/+page.svelte
frontends/wealth/src/routes/(team)/universe/+page.svelte
frontends/wealth/src/lib/components/IngestionProgress.svelte
frontends/admin/src/routes/(admin)/inspect/+page.svelte
```

---

## Deliverables

1. `docs/audit/wealth-dd-factsheet-workflow-gap.md` — gap analysis
2. `docs/prompts/wealth-dd-factsheet-approval-workflow-prompt.md` — implementation prompt
3. Console output of all verification checks (2.1–2.11) with PASS/FAIL/SKIP per item
4. Summary: total passed, failed, skipped

---

## Critical Rules

- Do NOT modify code — this is audit and verification only (except for the gap analysis documents)
- Skip tests gracefully if API keys are missing
- Always clean up test data (TEST_ORG)
- Report exact counts and versions, not approximations
