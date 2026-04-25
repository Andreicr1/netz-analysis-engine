# PR-Q8A — equity_characteristics_compute worker (XBRL × nav_timeseries)

**Model:** Opus 4.7 (1M context).
**Branch to create:** `feat/equity-characteristics-compute-xbrl` from main (head: `0173_factor_model_fits`).
**Role:** backend implementer. Ships one new worker + its integration test, populating `equity_characteristics_monthly` from XBRL fundamentals × NAV price history.
**Tracking issue:** #286.
**Reference spec:** `docs/prompts/2026-04-20-opus-q7-sec-xbrl-companyfacts-worker.md` (Q7 context), `docs/prompts/2026-04-20-opus-q8-equity-characteristics-matview.md` (Q8 original spec — superseded by this prompt).

---

## Why this exists

The original `equity_characteristics_compute` worker was deleted in PR #287 because it queried Tiingo Fundamentals tables we decided not to activate. Issue #286 tracks the replacement. With PR #285 (schema alignment) and PR #288 (migration 0173 on cascade) merged and the dev DB restored with real data, this is the sprint that lights up `equity_characteristics_monthly`.

**Downstream unlock:** once this worker populates the table, the existing `/api/v1/research/funds/{instrument_id}` and `/api/v1/research/scatter` routes will return non-empty results → PR-Q8B (terminal `/research` route) can consume. PR-Q9 (IPCA factor model writing to `factor_model_fits`) also depends on this.

---

## Current state of the world (verified 2026-04-25)

```sql
-- Data already present (post-restore)
SELECT COUNT(*) FROM sec_xbrl_facts;         -- 106,008,345 rows
SELECT COUNT(*) FROM nav_timeseries;         -- 20,143,205 rows
SELECT COUNT(*) FROM instruments_universe;   -- 9,419 rows
SELECT COUNT(*) FROM equity_characteristics_monthly;  -- 0 rows ← gap to close

-- Universe with complete data for characteristics
SELECT
  COUNT(*) AS with_cik,                                                    -- 6,455
  COUNT(*) FILTER (WHERE ticker IS NOT NULL) AS with_ticker,               -- 6,139
  COUNT(DISTINCT i.instrument_id) FILTER (WHERE EXISTS (
    SELECT 1 FROM nav_timeseries n WHERE n.instrument_id = i.instrument_id
  )) AS with_nav                                                            -- 5,867
FROM instruments_universe i
WHERE attributes->>'sec_cik' IS NOT NULL;
```

Target coverage: **~5,867 instruments** (those with CIK + ticker + NAV history). These are the ones that will produce characteristics rows.

---

## Concept mapping — Tiingo line_items → XBRL us-gaap concepts (verified observation counts)

| Kelly-Pruitt-Su need | XBRL concept(s) — ordered by preference | us-gaap obs count |
|---|---|---|
| Book equity | `StockholdersEquity` | 1,138,123 |
| Total assets | `Assets` | 803,826 |
| Net income (TTM) | `NetIncomeLoss` | 1,052,693 |
| Revenue (for gross profit) | `Revenues` → `RevenueFromContractWithCustomerExcludingAssessedTax` (ASC 606 fallback) | 415,325 / 189,825 |
| Cost of revenue (for gross profit) | `CostOfRevenue` → `CostOfGoodsAndServicesSold` (industry fallback) | 154,307 / 176,605 |
| Capex (investment growth) | `PaymentsToAcquirePropertyPlantAndEquipment` | 504,526 |
| PP&E (investment growth denominator) | `PropertyPlantAndEquipmentNet` | 599,523 |
| Shares outstanding (market cap) | `dei.EntityCommonStockSharesOutstanding` | 359,303 (unit='shares') |
| Close price (market cap) | `nav_timeseries.nav` (last of month for instrument_id) | — |

**Unit filtering:** for every us-gaap concept, filter `WHERE unit = 'USD'` (~99% of obs are USD; the ~1% in CNY/CAD/JPY/EUR are foreign-listed issuers out of our US equity scope). For `EntityCommonStockSharesOutstanding`, filter `unit = 'shares'`.

**Restatement dedupe:** XBRL stores multiple observations per `(cik, concept, period_end)` — one per filing accession. Always pick the LATEST `filed` DESC per group. Use SQL pattern:

```sql
SELECT DISTINCT ON (cik, concept, period_end)
       cik, concept, period_end, val, unit, filed, accn
FROM sec_xbrl_facts
WHERE taxonomy = 'us-gaap' AND unit = 'USD'
  AND concept IN (...)
ORDER BY cik, concept, period_end, filed DESC
```

---

## Derivation math (reuse existing pure functions)

All six characteristics have pure math implementations in
`backend/app/domains/wealth/services/characteristics_derivation.py` —
**do NOT rewrite**. The test file `test_characteristics_derivation.py`
covers their correctness independently. The worker's job is data plumbing:
fetch inputs, call the functions, persist outputs.

Function signatures (read the source before using):

- `derive_size(market_cap: float | None) -> float | None` — returns `log(market_cap)` or `None`
- `derive_book_to_market(book_equity: float | None, market_cap: float | None) -> float | None`
- `derive_momentum_12_1(nav_series: pd.Series, as_of: date) -> float | None` — needs ≥11 months of history, drops most-recent month
- `derive_quality_roa(net_income_ttm: float | None, total_assets: float | None) -> float | None`
- `derive_investment_growth(capex_ttm: float | None, ppe_prior: float | None) -> float | None`
- `derive_profitability_gross(revenue: float | None, cost_of_revenue: float | None, total_assets: float | None) -> float | None`

**Note on `derive_momentum_12_1`:** the function uses `nav_series.loc[:as_of].iloc[-13:-1]` (12-month window, drops most recent) and guards `start_val <= 0 → None`. Your worker already has this tested in PR #281 (B1 Cluster D test fix). No changes needed to the function — just feed it the nav series.

---

## Target schema (migration 0171, already created)

```
equity_characteristics_monthly (HYPERTABLE on as_of, chunk 1 year)
├── instrument_id       UUID NOT NULL
├── ticker              TEXT NOT NULL
├── as_of               DATE NOT NULL    (month-end)
├── size_log_mkt_cap    NUMERIC(10,4)
├── book_to_market      NUMERIC(10,4)
├── mom_12_1            NUMERIC(10,4)
├── quality_roa         NUMERIC(10,4)
├── investment_growth   NUMERIC(10,4)
├── profitability_gross NUMERIC(10,4)
├── source_filing_date  DATE              (LATEST filed from the XBRL obs that fed the row — for audit)
├── computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
└── PRIMARY KEY (instrument_id, as_of)
```

Upsert pattern: `INSERT ... ON CONFLICT (instrument_id, as_of) DO UPDATE SET ... computed_at = now()` so reruns refresh values without accumulating duplicates.

---

## Files to create

### 1. `backend/app/core/jobs/equity_characteristics_compute.py` (recreate — same lock 900_091)

Reclaim the deleted file's advisory lock ID. Module structure:

```python
"""equity_characteristics_compute — 6 Kelly-Pruitt-Su chars from XBRL × nav.

Advisory lock : 900_091
Frequency     : daily — market_cap depends on end-of-month NAV (daily
                refresh keeps the latest month fresh), fundamentals come
                from quarterly XBRL filings so non-market-cap chars only
                change monthly at most.
Idempotent    : yes — ON CONFLICT (instrument_id, as_of) DO UPDATE.
Scope         : global (no RLS) — equity_characteristics_monthly is a
                shared analytical table.
"""
```

**Key functions to implement:**

- `async def run_equity_characteristics_compute(limit: int | None = None, dry_run: bool = False) -> dict[str, Any]` — entry point with advisory-lock guard (per CLAUDE.md §Data Ingestion Workers pattern)
- `async def _load_universe(db, limit=None) -> list[tuple[UUID, int, str]]` — returns `(instrument_id, cik, ticker)` for every instrument in `instruments_universe` with `attributes->>'sec_cik' IS NOT NULL` AND ticker IS NOT NULL AND at least one NAV row in `nav_timeseries`. The CIK is `(attributes->>'sec_cik')::BIGINT`.
- `async def _fetch_fundamentals(db, cik: int) -> dict[date, dict]` — single query pulling all needed concepts for one CIK, deduped by latest filing date. Returns `{period_end: {'book_equity': float, 'assets': float, 'net_income': float, 'revenue': float, 'cost_of_revenue': float, 'capex': float, 'ppe': float, 'filed': date}}`. Use the `DISTINCT ON` pattern. Prefer `Revenues` then fallback to `RevenueFromContractWithCustomerExcludingAssessedTax` per period if Revenues is missing; same for CostOfRevenue → CostOfGoodsAndServicesSold.
- `async def _fetch_shares_outstanding(db, cik: int) -> dict[date, float]` — monthly shares outstanding from `dei.EntityCommonStockSharesOutstanding`. Returns `{period_end_month: shares}`. Used to compute market cap.
- `async def _fetch_nav_monthly(db, instrument_id: UUID) -> pd.Series` — month-end NAV series from `nav_timeseries`. Returns a pandas Series indexed on month-end dates. (Pattern already in old deleted worker's `_fetch_nav_series` — check git history for that file if you want reference, but the function signature is simpler now.)
- `async def _compute_instrument(db, instrument_id: UUID, cik: int, ticker: str) -> list[dict]` — orchestrates the per-instrument computation. Joins the three data sources, iterates month-by-month, calls the `derive_*` functions, returns rows ready for upsert.
- `async def _upsert_rows(db, rows: list[dict]) -> int` — batch upsert. Returns count of rows written.

**Upsert SQL:**

```sql
INSERT INTO equity_characteristics_monthly (
    instrument_id, ticker, as_of,
    size_log_mkt_cap, book_to_market, mom_12_1,
    quality_roa, investment_growth, profitability_gross,
    source_filing_date, computed_at
) VALUES (...) 
ON CONFLICT (instrument_id, as_of) DO UPDATE SET
    size_log_mkt_cap = EXCLUDED.size_log_mkt_cap,
    book_to_market = EXCLUDED.book_to_market,
    mom_12_1 = EXCLUDED.mom_12_1,
    quality_roa = EXCLUDED.quality_roa,
    investment_growth = EXCLUDED.investment_growth,
    profitability_gross = EXCLUDED.profitability_gross,
    source_filing_date = EXCLUDED.source_filing_date,
    computed_at = now()
```

**Advisory lock pattern** — reference any existing worker (e.g., `backend/app/core/jobs/nport_ingestion.py` lock 900_018 is a good model):

```python
LOCK_ID = 900_091

async def run_equity_characteristics_compute(...):
    async with async_session() as db:
        acquired = await db.scalar(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID})
        if not acquired:
            logger.info("equity_characteristics_compute skip — lock held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            # ... main loop
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID})
```

### 2. `backend/tests/integration/test_equity_characteristics_compute.py` (new)

Integration test that:
1. Seeds `instruments_universe` with 2-3 test instruments (with ticker + sec_cik attributes)
2. Seeds `sec_xbrl_facts` with ~12-18 months of observations for key concepts (StockholdersEquity, Assets, NetIncomeLoss, Revenues, CostOfRevenue, CapEx, PP&E, shares outstanding) — enough to produce 1-2 computed rows
3. Seeds `nav_timeseries` with ≥13 months of daily NAV data (so momentum_12_1 is computable)
4. Calls `run_equity_characteristics_compute()`
5. Asserts:
   - `equity_characteristics_monthly` has the expected rows
   - Values are mathematically correct (call pure `derive_*` with the same seed inputs and compare)
   - Restatement test: insert two observations for the same `(cik, concept, period_end)` with different `filed` dates and a different `val`; confirm the LATER one wins

Mark with `@pytest.mark.integration` (consistent with other integration tests). Use self-seeding (no dependency on `scripts/dev_seed_local.py`).

### 3. `backend/app/core/jobs/__init__.py` (small update, if registry exists)

Check if there's a worker registry (`grep -rn "900_091\|LOCK_ID = 900" backend/app/core/jobs/__init__.py backend/app/main.py 2>/dev/null`). If the worker is mentioned in a scheduler dict or router-like registration, add the re-created worker back. If not, skip.

### 4. `CLAUDE.md` §"Data Ingestion Workers" table — restore the row

Replace the strikethrough row with the new description:

```
| `equity_characteristics_compute` | 900_091 | global | `equity_characteristics_monthly` | Computed (6 Kelly-Pruitt-Su chars from sec_xbrl_facts × nav_timeseries) | Daily |
```

---

## Verification plan (MUST pass before commit)

### A. Unit tests (fast, run first)

```bash
cd backend
python -m pytest tests/integration/test_equity_characteristics_compute.py -xvs
# Expected: all passed
```

### B. Smoke run against restored dev DB (the real payoff)

```bash
# Ensure backend deps installed + .env points at docker compose postgres
python -c "
import asyncio
from app.core.jobs.equity_characteristics_compute import run_equity_characteristics_compute
result = asyncio.run(run_equity_characteristics_compute(limit=100))
print(result)
"
# Expected: {'status': 'succeeded', 'instruments_processed': 100, 'rows_written': >1000}
```

Then verify:

```bash
docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "
SELECT COUNT(*) AS rows,
       MIN(as_of) AS earliest,
       MAX(as_of) AS latest,
       COUNT(DISTINCT instrument_id) AS instruments
FROM equity_characteristics_monthly;
"
# Expected: rows > 1000 (for 100 instruments × ~12 months), earliest 2015ish, latest 2026ish
```

### C. Sanity query on a known ticker

Pick SPY or AAPL (should have ample data), fetch from existing `/api/v1/research/funds/{id}` endpoint via curl:

```bash
# First get the instrument_id for SPY or AAPL
docker exec netz-analysis-engine-db-1 psql -U netz -d netz_engine -c "
SELECT instrument_id, ticker, name FROM instruments_universe WHERE ticker IN ('SPY','AAPL','MSFT') LIMIT 3;
"

# Then call the existing endpoint
curl -s -H "X-DEV-ACTOR: super_admin:403d8392-ebfa-5890-b740-45da49c556eb" \
     "http://localhost:8000/api/v1/research/funds/<instrument_id>" | jq .
# Expected: non-empty response with all 6 characteristics + z-scores
```

### D. Full pytest suite still green

```bash
cd backend
python -m pytest tests/ --tb=no -q 2>&1 | tail -5
# Expected: 0 failed, 0 new regressions vs main baseline
```

---

## Stop conditions

- **Schema mismatch in `equity_characteristics_monthly`**: if the migration 0171 columns don't match what I described above, verify via `\d equity_characteristics_monthly` before proceeding. The spec here is from a read of the migration file, but if an intermediate migration altered it, adapt.
- **`characteristics_derivation.py` function signatures differ** from what I listed: read the actual file before calling. I may have the wrong arg order or parameter names.
- **Market cap computation returns NaN/zero for most instruments**: means shares_outstanding data is too sparse at period-end. Report — may need a different XBRL concept (e.g., `CommonStockSharesOutstanding` from us-gaap rather than dei).
- **Worker loop exceeds 30 minutes for the 5,867-instrument run**: flag for batching strategy (the worker should scale; 30min × 6k = needs optimization via parallel fetches or bulk SQL).
- **Tests pass but smoke-run produces 0 rows**: means the JOIN logic between XBRL (CIK) and NAV (instrument_id) is dropping everything. Debug with a single known instrument (SPY).

---

## Commit + PR

```bash
git push -u origin feat/equity-characteristics-compute-xbrl

gh pr create --title "feat(wealth): equity_characteristics_compute worker (XBRL × nav → 6 Kelly-Pruitt-Su chars)" --body "## Summary

Populates the currently-empty \`equity_characteristics_monthly\` table with 6 Kelly-Pruitt-Su characteristics per instrument per month, computed from \`sec_xbrl_facts\` (fundamentals) × \`nav_timeseries\` (price history). Replaces the deprecated Tiingo worker removed in #287.

Closes #286 (data layer side — terminal UX comes in PR-Q8B).

## Architecture

- **Worker:** \`backend/app/core/jobs/equity_characteristics_compute.py\` (lock 900_091 — reclaimed)
- **Inputs:** \`sec_xbrl_facts\` (106M rows, us-gaap taxonomy, USD unit, restatement-deduped via DISTINCT ON … filed DESC) + \`nav_timeseries\` (20M rows, monthly-bucketed)
- **Output:** \`equity_characteristics_monthly\` upserted with ON CONFLICT (instrument_id, as_of)
- **Reuses:** pure derivation functions in \`characteristics_derivation.py\` — zero math reimplemented

## Concept mapping (Tiingo → XBRL us-gaap)

| Characteristic | Input concept(s) |
|---|---|
| size_log_mkt_cap | \`dei.EntityCommonStockSharesOutstanding\` × \`nav_timeseries.nav\` |
| book_to_market | \`StockholdersEquity\` / market_cap |
| mom_12_1 | \`nav_timeseries\` 12-month window (excludes most-recent month) |
| quality_roa | \`NetIncomeLoss\` TTM / \`Assets\` |
| investment_growth | \`PaymentsToAcquirePropertyPlantAndEquipment\` TTM / \`PropertyPlantAndEquipmentNet\` (prior) |
| profitability_gross | (\`Revenues\` − \`CostOfRevenue\`) / \`Assets\` |

Revenue/cost fallbacks: \`Revenues\` → \`RevenueFromContractWithCustomerExcludingAssessedTax\`; \`CostOfRevenue\` → \`CostOfGoodsAndServicesSold\`.

## Universe coverage

6,455 instruments with \`attributes.sec_cik\`; ~5,867 have ticker + NAV history. Expected population: ~70k–100k rows over 10y of monthly data.

## Test plan

- [x] Integration test seeds XBRL + NAV, runs worker, asserts computed values match pure-function outputs
- [x] Restatement test: two XBRL obs for same \`(cik, concept, period_end)\` with different \`filed\` — later wins
- [x] Smoke run (limit=100) against restored dev DB produces >1000 rows
- [x] \`/api/v1/research/funds/{id}\` returns non-empty for SPY/AAPL

## Unblocks

- **PR-Q8B** — terminal \`/research/[instrumentId]\` route consumes \`/api/v1/research/funds/{id}\`
- **PR-Q9** — \`ipca_estimation\` worker writing to \`factor_model_fits\` (needs ECM as input)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"
```

---

## What "done" looks like

- 1 new worker file (~300-400 lines) + 1 new integration test (~200-300 lines)
- `equity_characteristics_monthly` populated with thousands of rows after a smoke run
- `/api/v1/research/funds/{id}` returns a meaningful payload for SPY/AAPL/MSFT
- Full pytest suite green (no regressions)
- CLAUDE.md row restored

Report back with PR URL + smoke-run counts + `gh pr checks <N>` output.
