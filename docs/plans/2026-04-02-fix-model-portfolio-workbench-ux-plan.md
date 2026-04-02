---
title: "fix: Model Portfolio workbench — persist backtest/stress, NAV chart, CORS, fund management UX"
type: fix
status: active
date: 2026-04-02
---

# Fix: Model Portfolio Workbench UX — Backtest/Stress Persistence, NAV Chart, Fund Management

## Enhancement Summary

**Deepened on:** 2026-04-02
**Sections enhanced:** 6 phases + technical considerations
**Research agents used:** JSONB persistence patterns, SvelteKit optimistic updates (Svelte 5.25+), NAV chart institutional UX, PostgreSQL SET LOCAL security, documented learnings (7 solutions files), fund selection UX patterns

### Key Improvements
1. **Critical fix: SQL injection remedy corrected.** `SET LOCAL` does NOT accept bind parameters in PostgreSQL (utility statement limitation). Must use `set_config()` function instead. Affects 15+ files, not just 5.
2. **Svelte 5.25+ `$derived` override pattern** for optimistic updates — eliminates the `$effect` sync anti-pattern from the original plan.
3. **NAV chart enhanced** with base-100 normalization keyed to visible window start, time range selectors (1M/3M/6M/1Y/YTD/SI), benchmark overlay, and view mode toggle.
4. **Fund editor UX grounded** in Bloomberg PORT / FactSet PA institutional patterns — checkbox selection, soft removal, staged changes with ConsequenceDialog.

### New Considerations Discovered
- `$state.raw` should be used for large backtest/stress result objects (avoids deep proxy overhead)
- Benchmark overlay on NAV chart is achievable — `benchmark_composite` field + `/blended-benchmarks/{id}/nav` endpoint already exist
- Fund removal should be "soft" (exclude from construction) not "hard" (remove from universe)
- The `_run_construction_async` function loads the full approved universe — may need `include_fund_ids` parameter for selective construction

---

## Overview

The Model Portfolio workbench and Portfolio Monitoring pages have multiple interrelated issues that make the end-to-end portfolio construction workflow non-functional in production. The core problems are: (1) backtest/stress results are computed but never persisted or displayed, (2) the NAV evolution chart is missing, (3) CORS errors in production, (4) no way to manage funds in allocation blocks after initial construction, and (5) analytics sections produce no visible output.

## Problem Statement

From production screenshots (2026-04-02):

1. **Backtest/Stress results invisible** — clicking "Run Backtest" or "Stress Test" computes results server-side but the GET `/track-record` endpoint hardcodes `backtest: null, stress: null`. The frontend ignores the POST response body and relies on `invalidateAll()` which re-fetches the broken GET endpoint.

2. **No NAV evolution chart** — the `nav_series` data exists in `model_portfolio_nav` (synthesized by `portfolio_nav_synthesizer` worker) and is returned by `/track-record`, but the Model Portfolio detail page doesn't render it. Users expect a base-100 equity curve showing portfolio performance since inception.

3. **CORS errors in production** — `.env.production` points to Railway internal URL (`web-production-ae62.up.railway.app`) instead of the custom domain (`api.investintell.com`). Browser-side API calls fail with CORS errors when error responses (500s) don't include CORS headers.

4. **No fund management after construction** — the `ConstructionAdvisor` only appears when CVaR exceeds limits. If CVaR is within bounds, there's no UI to add/remove/swap funds in allocation blocks.

5. **Analytics empty** — Fund Analytics dropdown on `/analytics` page shows "Select a fund..." but the dropdown population depends on instruments loaded from `/universe`. When the endpoint returns errors (500s from CORS), the list is empty with no helpful guidance.

6. **Portfolio Workbench confusion** — unclear relationship between Model Portfolios (construction) and Portfolio Workbench (monitoring). No empty states guide the user when no active portfolio exists.

## Proposed Solution

Six phases, ordered by impact and dependency:

### Phase 1: CORS Production Fix

**File:** `frontends/wealth/.env.production`

Change `VITE_API_BASE_URL` from Railway internal URL to production custom domain:
```
VITE_API_BASE_URL=https://api.investintell.com/api/v1
```

This fixes all CORS errors because `api.investintell.com` is already in the backend's `cors_origins` allowlist (`backend/app/core/config/settings.py:59`) and the regex pattern.

**Verification:** All browser console CORS errors should disappear. 500 errors will now surface as proper error messages in the UI.

---

### Phase 2: Persist Backtest/Stress Results (Migration + Backend)

#### 2A: Migration `0081_model_portfolio_results`

Add two nullable JSONB columns to `model_portfolios`:

```python
# backend/app/core/db/migrations/versions/0081_model_portfolio_results.py
"""Add backtest_result and stress_result JSONB columns to model_portfolios."""

revision = "0081"
down_revision = "0080_fix_mv_unified_funds_manager"

def upgrade():
    op.add_column("model_portfolios", sa.Column("backtest_result", postgresql.JSONB(), nullable=True))
    op.add_column("model_portfolios", sa.Column("stress_result", postgresql.JSONB(), nullable=True))

def downgrade():
    op.drop_column("model_portfolios", "stress_result")
    op.drop_column("model_portfolios", "backtest_result")
```

Pattern follows `fund_selection_schema` (JSONB nullable, no server_default needed).

#### Research Insights — JSONB Persistence

**JSONB on the parent row is the correct choice, not a separate table:**
- **1:1 relationship.** One "latest" backtest/stress result per portfolio. A join table adds cost with zero normalization benefit.
- **Data is small and bounded.** Backtest with 20 folds: ~1.5KB. Stress with 6 scenarios: ~400 bytes. Both stay inline (below PostgreSQL TOAST threshold of 2KB).
- **The existing `BacktestRun` table serves a different purpose.** It's for `/analytics/backtest` on-demand runs with configurable params and status lifecycle. Model portfolio backtests are portfolio-owned computation results.
- **No `MutableDict` needed.** The codebase uses full-replacement assignment for all JSONB columns (never in-place mutation). SQLAlchemy detects the new object identity automatically. Zero instances of `MutableDict` or `flag_modified` across 63 JSONB files.
- **No index needed.** Read by PK only, never filtered/queried inside the JSONB.

#### 2B: Update ORM Model

**File:** `backend/app/domains/wealth/models/model_portfolio.py`

Add two columns after `fund_selection_schema`:
```python
backtest_result: Mapped[dict | None] = mapped_column(JSONB)
stress_result: Mapped[dict | None] = mapped_column(JSONB)
```

#### 2C: Update Schema

**File:** `backend/app/domains/wealth/schemas/model_portfolio.py`

Add to `ModelPortfolioRead`:
```python
backtest_result: dict | None = None
stress_result: dict | None = None
```

#### 2D: Update POST endpoints to persist results

**File:** `backend/app/domains/wealth/routes/model_portfolios.py`

**`trigger_backtest` (line 261):**
After computing `backtest_result`, persist it:
```python
backtest_result = await asyncio.to_thread(_backtest)
# Full replacement — SQLAlchemy detects new object identity automatically
portfolio.backtest_result = backtest_result
await db.flush()  # Push UPDATE within RLS transaction (not commit — middleware handles that)
return {"portfolio_id": str(portfolio_id), "status": "completed", "backtest": backtest_result}
```

**`trigger_stress` (line 311):**
Same pattern:
```python
stress_result = await asyncio.to_thread(_stress)
portfolio.stress_result = stress_result
await db.flush()
return {"portfolio_id": str(portfolio_id), "status": "completed", "stress": stress_result}
```

**Note:** `expire_on_commit=False` is enforced globally (`backend/app/core/db/engine.py:8`), so `portfolio.backtest_result` remains accessible after flush without re-querying.

#### 2E: Update GET /track-record to read persisted data

**File:** `backend/app/domains/wealth/routes/model_portfolios.py` (lines 245-253)

Replace hardcoded nulls:
```python
return {
    "portfolio_id": str(portfolio_id),
    "profile": portfolio.profile,
    "status": portfolio.status,
    "fund_selection": portfolio.fund_selection_schema,
    "nav_series": nav_series,
    "backtest": portfolio.backtest_result,   # was: None
    "stress": portfolio.stress_result,       # was: None
}
```

#### 2F: Fix SQL injection in sync wrappers — use `set_config()`

**CRITICAL: PostgreSQL does NOT support bind parameters in `SET` statements.** `SET` is a utility statement; the PostgreSQL parser rejects `$1` placeholders in utility commands during the Parse phase of the extended query protocol. This is a PostgreSQL server limitation, not a driver issue — documented in PL/pgSQL docs: "Variable substitution currently works only in SELECT, INSERT, UPDATE, DELETE, MERGE."

The plan's original proposed fix (`text("SET LOCAL ... = :oid")`) **would fail at runtime**. The correct fix uses PostgreSQL's `set_config()` function, which runs via a `SELECT` (a plannable statement that accepts parameters):

```python
# BEFORE (unsafe string interpolation):
safe_oid = str(_org_id).replace("'", "")
sync_db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))

# AFTER (fully parameterized via set_config):
sync_db.execute(
    text("SELECT set_config('app.current_organization_id', :oid, true)"),
    {"oid": str(_org_id)},
)
# Third arg `true` = transaction-scoped (equivalent to SET LOCAL)
```

**Proof this works in the codebase:** `tmp_e2e_db_check.py:27-29` already uses this pattern:
```python
await conn.execute("SELECT set_config('app.current_organization_id', $1, false)", ORG_ID)
```

**Affected files (15+ locations):**

| File | Line(s) | Context |
|------|---------|---------|
| `backend/app/core/tenancy/middleware.py` | 41-42 | `set_rls_context()` — canonical |
| `backend/app/core/tenancy/admin_middleware.py` | 27-29 | `get_db_for_tenant()` |
| `backend/app/core/db/session.py` | 49-51 | sync session |
| `backend/app/domains/wealth/routes/content.py` | 461, 498, 534 | 3 call sites |
| `backend/app/domains/wealth/routes/dd_reports.py` | 722 | sync engine call |
| `backend/app/domains/wealth/routes/model_portfolios.py` | 294, 344 | backtest + stress |
| `backend/app/domains/wealth/routes/fact_sheets.py` | 100 | sync fact sheet |
| `backend/app/domains/wealth/routes/universe.py` | 37 | sync session |
| `backend/app/domains/wealth/workers/fact_sheet_gen.py` | 136 | worker |
| `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` | 587 | engine |

Static literals (like `'00000000-...'` in middleware reset) are safe as-is but could be converted for consistency.

**Sources:** [PostgreSQL SET docs](https://www.postgresql.org/docs/current/sql-set.html), [asyncpg #883](https://github.com/MagicStack/asyncpg/discussions/883), [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)

---

### Phase 3: NAV Evolution Chart on Model Portfolio Detail

**File:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

The `PortfolioNAVChart` component already exists at `lib/components/charts/PortfolioNAVChart.svelte` and accepts `navSeries: NAVPoint[]`. The `nav_series` data is already returned by `/track-record` and available as `trackRecord.nav_series`.

Add a new section above the Backtest section:

```svelte
<!-- NAV Evolution -->
<section class="mp-section mp-section--full">
  <h3 class="mp-section-title">Portfolio NAV</h3>
  {#if trackRecord?.nav_series && trackRecord.nav_series.length > 1}
    <PortfolioNAVChart
      navSeries={trackRecord.nav_series}
      inceptionDate={portfolio.inception_date}
      baseIndex={100}
      height={360}
    />
  {:else}
    <div class="mp-empty">
      <p>NAV series is synthesized daily by the background worker. Data will appear after the next run.</p>
    </div>
  {/if}
</section>
```

#### Research Insights — Institutional NAV Chart UX

**Base-100 normalization — industry standard:**
- Bloomberg PORT, Morningstar Direct, eVestment all default to base-100 for equity curves.
- **Key detail:** The base date should track the visible window start, not inception. Changing date range from "1Y" to "3M" rebases to 100 at 3 months ago. This is how Bloomberg does it.

**Enhanced `PortfolioNAVChart.svelte` props:**

```typescript
interface Props {
  navSeries: NAVPoint[];
  benchmarkSeries?: { date: string; nav: number }[] | null;  // NEW: benchmark overlay
  inceptionDate?: string | null;
  height?: number;
  loading?: boolean;
  baseIndex?: number;  // NEW: normalize to this base (default: null = absolute)
}
```

**Base-100 transformation (client-side, keyed to visible window):**

```typescript
let viewMode = $state<"base100" | "absolute">("base100");
const TIME_RANGES = ["1M", "3M", "6M", "1Y", "YTD", "SI"] as const;
let timeRange = $state<typeof TIME_RANGES[number]>("SI");

let displaySeries = $derived.by(() => {
  if (viewMode !== "base100" || navSeries.length === 0) return navSeries;
  // Find first visible point based on timeRange
  const windowStart = computeWindowStart(navSeries, timeRange);
  const baseNav = windowStart.nav;
  if (baseNav === 0) return navSeries;
  return navSeries.map(p => ({ ...p, nav: (p.nav / baseNav) * 100 }));
});
```

**Additional enhancements:**
- **View mode toggle:** Two pill buttons (Base 100 / Absolute) — same styling as MacroChart `range-btn` pattern.
- **Time range selectors:** `1M | 3M | 6M | 1Y | YTD | SI` — reuse MacroChart dataZoom percentage computation.
- **Benchmark overlay:** If `portfolio.benchmark_composite` is set, fetch `GET /blended-benchmarks/{id}/nav` and pass as `benchmarkSeries`. Both series normalized from same window start for apples-to-apples comparison.
- **Cumulative return label:** Small annotation at chart end: "+14.3% since [start date]".
- **ECharts performance:** Add `large: true` and `largeThreshold: 500` for datasets > 750 points (3+ years daily).

---

### Phase 4: Frontend — Capture POST Results with Svelte 5 Optimistic Pattern

**File:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

#### Research Insights — Svelte 5.25+ Optimistic Update Pattern

The **`$derived` override pattern** (available since Svelte 5.25) is the official way to handle optimistic UI. Key rules:
1. **Use `$state.raw`** for large result objects (avoids deep proxy overhead on chart datasets).
2. **Do NOT use `$effect` for state sync.** The `$derived` expression auto-resets when server data changes via `invalidateAll()`.
3. **Do NOT destructure `data` beyond `$props()`.** Access nested properties via `$derived(data.trackRecord)` to maintain reactivity.
4. **Call `invalidateAll()` non-blocking** — the UI already shows local state.

```typescript
// Local optimistic state (use $state.raw for large objects)
let localBacktest = $state.raw<BacktestResult | null>(null);
let localStress = $state.raw<StressResult | null>(null);

// Merged view: local result wins until server catches up
let backtest = $derived(localBacktest ?? trackRecord?.backtest ?? null);
let stress = $derived(localStress ?? trackRecord?.stress ?? null);

async function runBacktest() {
  backtesting = true;
  error = null;
  const previousResult = localBacktest;  // Snapshot for rollback
  try {
    const api = createClientApiClient(getToken);
    const result = await api.post<{ backtest: BacktestResult }>(
      `/model-portfolios/${portfolioId}/backtest`, {}
    );
    localBacktest = result.backtest;  // Immediate display
    invalidateAll();                  // Background sync (no await)
  } catch (e) {
    localBacktest = previousResult;   // Rollback on error
    error = e instanceof Error ? e.message : "Backtest failed";
  } finally {
    backtesting = false;
  }
}

async function runStress() {
  stressing = true;
  error = null;
  const previousResult = localStress;
  try {
    const api = createClientApiClient(getToken);
    const result = await api.post<{ stress: StressResult }>(
      `/model-portfolios/${portfolioId}/stress`, {}
    );
    localStress = result.stress;
    invalidateAll();
  } catch (e) {
    localStress = previousResult;
    error = e instanceof Error ? e.message : "Stress test failed";
  } finally {
    stressing = false;
  }
}
```

**Why NOT `$effect` for reset:** When `trackRecord` updates via `invalidateAll()`, the `$derived` expression re-evaluates automatically. Since `localBacktest` is still set, it wins via `??`. The local and server values are identical (same POST result was persisted in Phase 2D), so there's no visual flicker. No manual synchronization needed.

**Sources:** [Svelte $derived docs](https://svelte.dev/docs/svelte/$derived), [Svelte best practices](https://svelte.dev/docs/svelte/best-practices)

---

### Phase 5: Empty States + UX Guidance

#### 5A: Portfolio Workbench — No Active Portfolio

**File:** `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte`

When `modelPortfolio` is null or has status "draft", show guidance:

```svelte
{#if !modelPortfolio || modelPortfolio.status === "draft"}
  <EmptyState
    title="No active model portfolio"
    description="Construct and activate a model portfolio to see monitoring data here."
    actionLabel="Go to Model Portfolios"
    actionHref="/model-portfolios"
  />
{/if}
```

#### 5B: Analytics — Empty Fund Dropdown

**File:** `frontends/wealth/src/routes/(app)/analytics/+page.svelte`

When instruments list is empty, show guidance instead of empty dropdown:

```svelte
{#if instruments.length === 0}
  <div class="analytics-empty">
    <p>No approved funds in universe. <a href="/screener">Import funds via Screener</a> first.</p>
  </div>
{:else}
  <!-- existing dropdown -->
{/if}
```

#### 5C: Risk Monitor — Connection Status

The Risk Monitor page shows CORS errors silently. After Phase 1 CORS fix, the 500s will surface properly. Add error state display on failed data loads — the risk store already has error tracking, just needs to render it.

#### Research Insights — Frontend Design Rules

From `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`:
- **All new components must use CSS tokens** (`var(--ii-*)` or `var(--netz-*)`), no hardcoded hex colors (D4/D5).
- **Dark + Light theme support** required for all new UI elements (D2).
- **Use `MetricCard` for financial KPIs**, not `DataCard` (D7).
- **Verify exact backend response shapes** before writing frontend API calls — recurring source of bugs per phantom-calls solution doc.

---

### Phase 6: Fund Management in Allocation Blocks

Currently, funds can only be added via:
- **Creation wizard** (Step 2 — block-filtered checkbox selection)
- **ConstructionAdvisor** (only appears when CVaR > limit)

Need: an "Edit Fund Selection" capability on the Model Portfolio detail page.

#### 6A: Add "Edit Funds" Button

**File:** `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

Add button near Fund Selection section header:
```svelte
<div class="mp-section-header">
  <h3 class="mp-section-title">Fund Selection</h3>
  {#if canEdit && portfolio.status === "draft"}
    <Button size="sm" variant="outline" onclick={() => editingFunds = true}>
      Edit Funds
    </Button>
  {/if}
</div>
```

#### 6B: Fund Editor Inline Panel — `FundSelectionEditor.svelte`

#### Research Insights — Institutional Fund Selection UX

**Bloomberg PORT / FactSet PA / MSCI Barra patterns:**
- **Master-detail with persistent context.** Portfolio summary (weights, CVaR) stays visible while editing. User never loses sight of impact zone.
- **Block/sleeve-centric grouping.** Tree: Asset Class Group > Block > Fund. IC member clicks block to see eligible funds. This is exactly the creation wizard Step 2 pattern.
- **Checkbox selection, not drag-and-drop.** Funds are pre-assigned to blocks via `instruments_org.block_id`. The IC decision is binary (include/exclude), not spatial. Bloomberg, FactSet, and MSCI all use toggles.

**Recommended layout (reuse creation wizard Step 2 pattern):**
- Left panel: block selector (list of allocation blocks with selected/total count)
- Right panel: approved instruments filtered by selected block
- Pre-populate with current portfolio selections from `fund_selection_schema.funds`
- Show current optimizer-assigned weight next to each selected fund
- Distinguish "in portfolio" (solid check) vs "in universe but not in portfolio" (hollow "+" icon)

**Soft removal only:**
- "Exclude from construction" ≠ "Remove from universe"
- Toggle button label: "Include" / "Exclude" (not "Add" / "Remove")
- Excluded funds stay in block's approved list but are dimmed
- Universe management stays in `/universe` (separate governance concern)

**Confirmation via ConsequenceDialog:**
- Sticky footer appears when changes are made: "2 funds added, 1 removed across 3 blocks"
- "Apply & Re-construct" triggers ConsequenceDialog with:
  - Added fund tickers
  - Removed fund tickers
  - Affected block count
  - "Re-optimization will run the 4-phase CLARABEL cascade. This may take 5-10 seconds."
- Do NOT auto-reconstruct on every toggle — batch changes then reconstruct once

**3-tier empty states per block:**
1. No approved funds: link to `/universe?block={blockId}` and `/screener`
2. Approved funds exist but none selected: "Skipped blocks have weight redistributed proportionally"
3. Block is ConstructionAdvisor gap: show target/gap weight, link to catalog

**API flow:**
1. User toggles fund checkboxes per block
2. "Apply & Re-construct" button (with ConsequenceDialog):
   - For newly selected funds not yet imported: `POST /screener/import/{identifier}`
   - For fund block assignment: `PATCH /instruments/{id}/org` with `{ block_id }`
   - For excluded funds: no API call needed — exclusion is passed to construct
   - Finally: `POST /model-portfolios/{id}/construct` to re-optimize
3. `invalidateAll()` to refresh page
4. Disable "Activate" button while in edit mode

**Implementation note:** The `_run_construction_async` function currently loads the full approved universe. If selective construction is needed (only include checked funds), add an optional `include_fund_ids: list[str] | None` parameter to the construct endpoint. Check if the creation wizard already passes `fund_ids` in the request body.

---

## Technical Considerations

### Database Migration
- Migration 0081 adds two nullable JSONB columns — lightweight ALTER TABLE, no data backfill needed.
- Existing portfolios will have `backtest_result = null` and `stress_result = null` until next backtest/stress run.
- No index needed on JSONB columns (read by PK only, never queried/filtered).
- No RLS changes needed (column addition, not new table).

### Backward Compatibility
- GET `/track-record` response shape unchanged (same keys, just non-null values now).
- Frontend `TrackRecord` type already has `backtest: BacktestResult | null` — no type changes needed.
- POST response bodies unchanged — local state capture is additive.

### Performance
- JSONB write on backtest/stress adds ~1ms to already-expensive compute operations (seconds).
- NAV chart rendering uses existing LTTB sampling in `PortfolioNAVChart` for large series.
- Base-100 normalization is O(n) client-side — negligible for <1000 daily points.
- Use `$state.raw` for backtest/stress result objects to avoid Svelte deep proxy overhead.
- Add `large: true` to ECharts series for NAV datasets > 500 points.

### Security
- `set_config()` fix converts all 15+ string interpolation sites to fully parameterized queries.
- Not exploitable today (org_id from JWT typed as UUID), but violates OWASP defense-in-depth.
- `set_config('...', :oid, true)` is a drop-in replacement for `SET LOCAL` — third argument `true` = transaction-scoped.

### Svelte 5 Patterns
- Use `$state.raw` (not `$state`) for large response objects that are only reassigned, never mutated in place.
- Use `$derived` override pattern for optimistic updates — no `$effect` for state synchronization.
- Never destructure `data` from `$props()` — access nested properties via `$derived` to maintain reactivity with `invalidateAll()`.
- Use client-side `fetch` via API client for POST mutations (not SvelteKit form actions) — complex JSON responses + auth headers required.

### Frontend Design Rules
- All new components must use `var(--ii-*)` / `var(--netz-*)` CSS tokens, no hardcoded hex colors.
- Dark + Light theme support required.
- Use `MetricCard` for financial KPIs (not `DataCard`).

---

## Acceptance Criteria

### Phase 1 — CORS
- [ ] `.env.production` uses `api.investintell.com` domain
- [ ] No CORS errors in browser console on production

### Phase 2 — Backtest/Stress Persistence
- [ ] Migration 0081 adds `backtest_result` and `stress_result` JSONB columns
- [ ] POST `/backtest` persists result to `model_portfolios.backtest_result`
- [ ] POST `/stress` persists result to `model_portfolios.stress_result`
- [ ] GET `/track-record` returns persisted backtest/stress data (not null)
- [ ] All `SET LOCAL` string interpolation replaced with `set_config()` parameterized calls
- [ ] `make check` passes (lint + typecheck + tests)

### Phase 3 — NAV Chart
- [ ] Model Portfolio detail page renders `PortfolioNAVChart` with nav_series
- [ ] Chart shows base-100 indexed values normalized to visible window start
- [ ] View mode toggle (Base 100 / Absolute)
- [ ] Time range selectors (1M / 3M / 6M / 1Y / YTD / SI)
- [ ] Empty state shown when no NAV data available

### Phase 4 — Frontend POST Capture
- [ ] Backtest results display immediately after POST completes (no page reload required)
- [ ] Stress results display immediately after POST completes
- [ ] Uses `$state.raw` for large result objects
- [ ] Error rollback restores previous state
- [ ] Server data takes over via `$derived` after `invalidateAll()`

### Phase 5 — Empty States
- [ ] Portfolio Workbench shows guidance when no active model portfolio exists
- [ ] Analytics fund dropdown shows "Import funds via Screener" when instruments empty
- [ ] Error messages surface properly (not swallowed as CORS errors)
- [ ] All new components use CSS token-based styling

### Phase 6 — Fund Management
- [ ] "Edit Funds" button visible on draft model portfolios
- [ ] Inline fund editor with block-filtered checkbox selection
- [ ] Pre-populated with current portfolio fund selections
- [ ] Soft removal (exclude from construction, keep in universe)
- [ ] ConsequenceDialog on "Apply & Re-construct"
- [ ] Save triggers re-construction automatically

---

## Files Modified

### Backend
| File | Changes |
|------|---------|
| `backend/app/core/db/migrations/versions/0081_model_portfolio_results.py` | NEW — add JSONB columns |
| `backend/app/domains/wealth/models/model_portfolio.py` | Add 2 columns |
| `backend/app/domains/wealth/schemas/model_portfolio.py` | Add 2 fields to `ModelPortfolioRead` |
| `backend/app/domains/wealth/routes/model_portfolios.py` | Persist results, fix track-record, fix `set_config()` |
| `backend/app/core/tenancy/middleware.py` | Fix `set_config()` — canonical |
| `backend/app/core/tenancy/admin_middleware.py` | Fix `set_config()` |
| `backend/app/core/db/session.py` | Fix `set_config()` |
| `backend/app/domains/wealth/routes/content.py` | Fix `set_config()` (3 sites) |
| `backend/app/domains/wealth/routes/dd_reports.py` | Fix `set_config()` |
| `backend/app/domains/wealth/routes/fact_sheets.py` | Fix `set_config()` |
| `backend/app/domains/wealth/routes/universe.py` | Fix `set_config()` |
| `backend/app/domains/wealth/workers/fact_sheet_gen.py` | Fix `set_config()` |
| `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` | Fix `set_config()` |

### Frontend
| File | Changes |
|------|---------|
| `frontends/wealth/.env.production` | Fix API base URL |
| `frontends/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte` | NAV chart, POST capture, edit funds button |
| `frontends/wealth/src/lib/components/charts/PortfolioNAVChart.svelte` | Add `baseIndex`, `benchmarkSeries`, view mode, time range |
| `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte` | Empty state for no active portfolio |
| `frontends/wealth/src/routes/(app)/analytics/+page.svelte` | Empty state for no instruments |
| `frontends/wealth/src/lib/components/model-portfolio/FundSelectionEditor.svelte` | NEW — inline fund editor |

---

## Sources

### Internal References
- Model Portfolio model: `backend/app/domains/wealth/models/model_portfolio.py`
- Track-record endpoint (broken): `backend/app/domains/wealth/routes/model_portfolios.py:207-253`
- Backtest trigger: `backend/app/domains/wealth/routes/model_portfolios.py:256-303`
- Stress trigger: `backend/app/domains/wealth/routes/model_portfolios.py:306-353`
- NAV chart component: `frontends/wealth/src/lib/components/charts/PortfolioNAVChart.svelte`
- TrackRecord type: `frontends/wealth/src/lib/types/model-portfolio.ts:68-83`
- CORS config: `backend/app/core/config/settings.py:47-68`
- JSONB pattern reference: `fund_selection_schema` column in same model
- Migration pattern reference: `0008_wealth_analytical_models.py`
- Creation wizard fund selector: `frontends/wealth/src/routes/(app)/model-portfolios/create/+page.svelte` (Step 2)
- `set_config()` precedent: `tmp_e2e_db_check.py:27-29`

### Documented Learnings Applied
- `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md` — confirms `set_config()` pattern
- `docs/solutions/integration-issues/phantom-calls-missing-ui-wealth-frontend-20260319.md` — verify response shapes before frontend work
- `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md` — CSS tokens, MetricCard, dark/light themes
- `docs/solutions/database-issues/alembic-monorepo-migration-fk-rls-ordering.md` — migration patterns (nullable JSONB)
- `docs/solutions/patterns/critical-patterns.md` — DB-only reads in user-facing code

### External References
- [PostgreSQL SET docs](https://www.postgresql.org/docs/current/sql-set.html) — utility statements don't accept bind params
- [PostgreSQL set_config()](https://pgpedia.info/s/set_config.html) — parameterized equivalent
- [asyncpg #883](https://github.com/MagicStack/asyncpg/discussions/883) — SET parameter limitation discussion
- [Svelte $derived docs](https://svelte.dev/docs/svelte/$derived) — writable derived for optimistic updates
- [Svelte best practices](https://svelte.dev/docs/svelte/best-practices) — no $effect for state sync
- [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
