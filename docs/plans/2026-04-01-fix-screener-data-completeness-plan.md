---
title: "fix: Screener Data Completeness — AUM Coverage, Holdings Accuracy, MMF Branch, Default Filters"
type: fix
status: active
date: 2026-04-01
deepened: 2026-04-01
origin: docs/brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md
---

# fix: Screener Data Completeness

## Enhancement Summary

**Deepened on:** 2026-04-01
**Sections enhanced:** 7
**Research agents used:** 6 (ETF/BDC model verification, prospectus route audit, AUM subquery performance, solution docs, MMF column mapping, frontend filter patterns)

### Key Improvements from Research
1. **AUM fallback simplified** — no correlated subquery needed; `sec_fund_classes.net_assets` is already joined, use direct column reference (zero query cost)
2. **`has_prospectus` already wired** — plan incorrectly stated it was missing; Phase 3.2 scope reduced to verification only
3. **`instrument_id` unavailable in catalog** — `nav_status` implementation must use a different approach (LEFT JOIN to `instruments_universe` or post-query enrichment)
4. **Table definition gap found** — `sec_fund_classes` Table in catalog_sql.py lacks `net_assets` column (must add before COALESCE can reference it)
5. **ETF/BDC have no `last_nport_date`** — must keep `literal(True)` with comment; only `sec_registered_funds` has this column

### New Considerations Discovered
- ETF/BDC models use `ncen_report_date` (not `last_nport_date`) — could be used as a staleness indicator in the future
- `sec_money_market_funds` Table definition is missing from catalog_sql.py — must be added
- MMF branch requires exactly 31 columns matching the UNION ALL order
- Frontend filter wiring pattern: URL params are source of truth, `$state` tracks UI, `invalidateAll: true` triggers SSR reload
- CI gotcha: must run `svelte-kit sync` before `svelte-check` after adding new types

---

## Overview

The screener catalog (5-branch UNION ALL in `catalog_sql.py`) has several data accuracy and completeness gaps. Most funds show "—" for AUM, `has_holdings` is hardcoded `TRUE` regardless of actual N-PORT data, Money Market Funds are absent, and the disclosure matrix overpromises data availability. This plan addresses all gaps in priority order across 3 phases.

## Problem Statement

Audit findings from 2026-04-01 identified 8 issues across 3 priority tiers:

| # | Issue | Impact | Priority |
|---|-------|--------|----------|
| 1 | AUM fallback chain incomplete — `sec_fund_classes.net_assets` (XBRL) not used | Most registered_us funds show "—" for AUM | P0 |
| 2 | `has_holdings = TRUE` hardcoded for registered_us/etf/bdc | Disclosure promises holdings that may not exist | P0 |
| 3 | No `has_aum` default filter — untradeable funds clutter catalog | UX: 12k+ funds with many missing core data | P1 |
| 4 | Money Market Funds (373) absent from catalog | Entire asset class invisible | P1 |
| 5 | `has_nav_history` = True when fund has ticker, but NAV only exists post-import | Disclosure says "Available" but data is empty | P2 |
| 6 | `sec_fund_prospectus_returns` not connected to detail panel | Calendar year bar chart data exists but unused in catalog context | P2 |
| 7 | UCITS have no AUM source | All UCITS show "—" for AUM | P3 |
| 8 | ER% uses `.toFixed(2)` instead of `@investintell/ui` formatter | Violates formatter discipline rule (CLAUDE.md) | P0 |

## Proposed Solution

Three phases, each independently deployable:

### Phase 1: Data Accuracy (P0) — Backend only
Fix what the catalog already shows to be truthful.

### Phase 2: Catalog Completeness (P1) — Backend + Frontend
Add missing data sources and default filters.

### Phase 3: Disclosure Honesty (P2) — Backend + Frontend
Fix what the detail panel promises vs delivers.

---

## Phase 1: Data Accuracy (P0)

### 1.1 AUM Fallback Chain

**File:** `backend/app/domains/wealth/queries/catalog_sql.py`

**Current (line 368-371):**
```python
func.coalesce(
    func.nullif(sec_registered_funds.c.total_assets, 0),
    sec_registered_funds.c.monthly_avg_net_assets,
).label("aum"),
```

**Target — 3-level fallback using direct column reference:**
```python
func.coalesce(
    func.nullif(sec_registered_funds.c.total_assets, 0),
    sec_fund_classes.c.net_assets,            # Class-level XBRL AUM (already joined)
    sec_registered_funds.c.monthly_avg_net_assets,
).label("aum"),
```

#### Research Insight: No Correlated Subquery Needed

The original plan proposed a `SUM(sec_fund_classes.net_assets)` correlated subquery. Research revealed this is unnecessary:

- The registered_us branch already performs `OUTERJOIN sec_fund_classes ON cik = cik` (line 402-404)
- The catalog returns **one row per class** (no GROUP BY) — so `sec_fund_classes.c.net_assets` gives the correct class-level AUM directly
- **Zero additional query cost** — the column is already in the result set
- **More accurate** — class-level AUM is the right granularity for a per-class catalog display

**Prerequisite — Add missing column to Table definition (lines 85-94):**
```python
sec_fund_classes = Table(
    "sec_fund_classes",
    _meta,
    Column("cik", Text, primary_key=True),
    Column("series_id", Text, primary_key=True),
    Column("class_id", Text, primary_key=True),
    Column("series_name", Text),
    Column("class_name", Text),
    Column("ticker", Text),
    Column("net_assets", Numeric(20, 2)),  # ADD THIS — from migration 0066 XBRL
)
```

**AUM min filter (line 503-508):** Must also use the same 3-level COALESCE for consistent filtering:
```python
_aum_col = func.coalesce(
    func.nullif(sec_registered_funds.c.total_assets, 0),
    sec_fund_classes.c.net_assets,
    sec_registered_funds.c.monthly_avg_net_assets,
)
conditions.append(_aum_col >= int(f.aum_min))
```

**ETF/BDC branches (lines 540, 621):** Currently use `monthly_avg_net_assets` only. No class-level XBRL data available for these tables. Keep as-is.

**Acceptance criteria:**
- [ ] `sec_fund_classes` Table definition includes `net_assets` column
- [ ] registered_us AUM uses 3-level COALESCE: `total_assets → sec_fund_classes.net_assets → monthly_avg_net_assets`
- [ ] `aum_min` filter uses the same COALESCE expression
- [ ] No performance regression (zero additional I/O — column already joined)

### 1.2 Fix `has_holdings` — Use `last_nport_date`

**File:** `backend/app/domains/wealth/queries/catalog_sql.py`

**Current (line 383):**
```python
literal(True).label("has_holdings"),  # registered_us
```

**Target:**
```python
(sec_registered_funds.c.last_nport_date.isnot(None)).label("has_holdings"),
```

#### Research Insight: ETF/BDC Models Lack `last_nport_date`

Verified against ORM models:
- `SecRegisteredFund` — **HAS** `last_nport_date` (models.py line 555, type `Date | None`)
- `SecEtf` — **DOES NOT** have `last_nport_date` (has `ncen_report_date` at line 644)
- `SecBdc` — **DOES NOT** have `last_nport_date` (has `ncen_report_date` at line 691)

**Decision:** Keep `literal(True)` for ETF and BDC branches. ETFs/BDCs virtually always have N-PORT data. Add a comment explaining:
```python
# ETFs/BDCs: keep True — no last_nport_date column, but N-PORT coverage is ~100%
literal(True).label("has_holdings"),
```

**Future improvement:** Could add `last_nport_date` column to `sec_etfs` and `sec_bdcs` models via migration, populated by the `nport_ingestion` worker.

**Acceptance criteria:**
- [ ] registered_us: `has_holdings = last_nport_date IS NOT NULL`
- [ ] ETF/BDC: keep `literal(True)` with comment explaining why
- [ ] Disclosure matrix correctly shows "N/A" for registered funds without N-PORT data

### 1.3 Fix ER% Formatter Violation

**File:** `frontends/wealth/src/lib/components/screener/CatalogTable.svelte`

**Current (line 371):**
```svelte
{group.representative.expense_ratio_pct != null ? `${Number(group.representative.expense_ratio_pct).toFixed(2)}%` : "\u2014"}
```

**Target:**
```svelte
{group.representative.expense_ratio_pct != null ? formatPercent(Number(group.representative.expense_ratio_pct) / 100) : "\u2014"}
```

Same fix at line 409 (class row).

#### Research Insight: CI Gotcha

From `docs/solutions/build-errors/ci-frontend-typecheck-failures-CIFrontendPipeline-20260323.md`: must run `svelte-kit sync` before `svelte-check` in CI. Ensure `formatPercent` is already imported (line 9 confirms it is).

**Acceptance criteria:**
- [ ] Both ER% renders use `formatPercent` from `@investintell/ui`
- [ ] No `.toFixed()` usage in CatalogTable.svelte
- [ ] `pnpm check` passes locally before push

---

## Phase 2: Catalog Completeness (P1)

### 2.1 Add `has_aum` Filter

**Backend — `catalog_sql.py`:**

Add to `CatalogFilters` dataclass (line 263):
```python
has_aum: bool | None = True   # True = only funds with AUM > 0 (default: exclude no-AUM)
```

Apply in each branch: add condition `WHERE aum IS NOT NULL AND aum > 0` using the branch-specific AUM expression.

For UCITS branch (line 820): if `has_aum is True`, return `None` (skip branch — UCITS have no AUM). Same pattern as existing `has_nav` filter (line 879).

**Backend — `screener.py` route (line 1380):**

Add query parameter:
```python
has_aum: bool | None = Query(None, description="Only funds with AUM data"),
```

Pass to `CatalogFilters`.

#### Research Insight: Frontend Filter Wiring Pattern

From frontend research, the complete wiring for a new filter follows this pattern:

1. **`+page.svelte` state** — `let showNoAum = $state(initParams.has_aum === "false");`
2. **`buildCatalogParams()`** — `if (showNoAum) params.set("has_aum", "false");`
3. **Filter bar UI** — checkbox or toggle in filter bar
4. **Handler** — `function toggleNoAum() { showNoAum = !showNoAum; applyCatalogFilters(); }`
5. **`clearAllFilters()`** — reset `showNoAum = false`
6. **`hasActiveFilters`** — add `|| showNoAum` to derived check
7. **`+page.server.ts`** — deserialize `has_aum` URL param and pass to API

**Key architectural rule:** URL params are source of truth (SSR-friendly). `$state` tracks UI. `invalidateAll: true` on `goto()` triggers server refetch.

**Design decision:** Since default is `has_aum=True` (server-side), the frontend only needs to send `has_aum=false` when user wants to see funds without AUM. The toggle label should be "Show all" or "Include funds without AUM data".

**Acceptance criteria:**
- [ ] Default catalog shows only funds with AUM > 0
- [ ] User can toggle "Show all" to see funds without AUM
- [ ] Total fund count drops from ~12.5k to a more focused set
- [ ] UCITS branch excluded when `has_aum=True` (no AUM source)
- [ ] URL param `has_aum=false` survives page reload (SSR)

### 2.2 Add Money Market Fund Branch

**Backend — `catalog_sql.py`:**

#### Step 1: Add Table Definition (after line 156)

`sec_money_market_funds` Table is **missing** from catalog_sql.py. Must be added:
```python
sec_money_market_funds = Table(
    "sec_money_market_funds",
    _meta,
    Column("series_id", String, primary_key=True),
    Column("cik", String, nullable=False),
    Column("fund_name", String, nullable=False),
    Column("strategy_label", String),
    Column("mmf_category", String),
    Column("net_assets", Numeric(20, 2)),
    Column("seven_day_gross_yield", Numeric(8, 4)),
    Column("weighted_avg_maturity", Integer),
    Column("weighted_avg_life", Integer),
    Column("investment_adviser", String),
    Column("domicile", String),
    Column("currency", String),
    Column("is_govt_fund", Boolean),
    Column("is_retail", Boolean),
    extend_existing=True,
)
```

#### Step 2: Add 6th UNION ALL Branch

The catalog UNION ALL has exactly **31 columns** that each branch must return in order:

```
universe, external_id, name, ticker, isin, region, fund_type, strategy_label,
aum, currency, domicile, manager_name, manager_id, inception_date,
total_shareholder_accounts, investor_count, series_id, series_name,
class_id, class_name, has_holdings, has_nav, has_13f_overlay,
investment_geography, vintage_year, expense_ratio_pct, avg_annual_return_1y,
avg_annual_return_10y, is_index, is_target_date, is_fund_of_fund
```

```python
def _mmf_branch(f: CatalogFilters) -> Select | None:
    """Branch 6: US Money Market Funds from SEC N-MFP filings."""
    cats = _parse_categories(f.fund_universe)
    if cats is not None and "money_market" not in cats:
        return None
    if f.has_nav is True:
        return None  # MMFs have stable NAV, no yfinance ticker

    stmt = select(
        literal("registered_us").label("universe"),
        sec_money_market_funds.c.series_id.label("external_id"),
        sec_money_market_funds.c.fund_name.label("name"),
        literal_column("NULL").label("ticker"),
        literal_column("NULL").label("isin"),
        literal("US").label("region"),
        literal("money_market").label("fund_type"),
        sec_money_market_funds.c.strategy_label,
        sec_money_market_funds.c.net_assets.label("aum"),
        sec_money_market_funds.c.currency,
        sec_money_market_funds.c.domicile,
        sec_money_market_funds.c.investment_adviser.label("manager_name"),
        literal_column("NULL").label("manager_id"),
        literal_column("NULL::date").label("inception_date"),
        literal_column("NULL::integer").label("total_shareholder_accounts"),
        literal_column("NULL::integer").label("investor_count"),
        literal_column("NULL").label("series_id"),
        literal_column("NULL").label("series_name"),
        literal_column("NULL").label("class_id"),
        literal_column("NULL").label("class_name"),
        literal(False).label("has_holdings"),
        literal(False).label("has_nav"),
        literal(False).label("has_13f_overlay"),
        literal("US").label("investment_geography"),
        literal_column("NULL::integer").label("vintage_year"),
        literal_column("NULL::numeric").label("expense_ratio_pct"),
        literal_column("NULL::numeric").label("avg_annual_return_1y"),
        literal_column("NULL::numeric").label("avg_annual_return_10y"),
        literal_column("NULL::boolean").label("is_index"),
        literal_column("NULL::boolean").label("is_target_date"),
        literal_column("NULL::boolean").label("is_fund_of_fund"),
    ).select_from(sec_money_market_funds)

    conditions: list[ColumnElement] = []
    if f.q:
        _q = f"%%{f.q}%%"
        conditions.append(sec_money_market_funds.c.fund_name.ilike(_q))
    if f.aum_min is not None:
        conditions.append(sec_money_market_funds.c.net_assets >= int(f.aum_min))
    if f.has_aum is True:
        conditions.append(sec_money_market_funds.c.net_assets.isnot(None))
        conditions.append(sec_money_market_funds.c.net_assets > 0)

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt
```

#### Step 3: Register in `_all_branches` (line 908-919)

```python
def _all_branches(filters: CatalogFilters) -> list[Select]:
    return [
        b
        for b in [
            _registered_us_branch(filters),
            _etf_branch(filters),
            _bdc_branch(filters),
            _private_us_branch(filters),
            _ucits_eu_branch(filters),
            _mmf_branch(filters),              # ADD HERE
        ]
        if b is not None
    ]
```

#### Step 4: Add to `ALL_CATEGORIES` (line 281-284)

```python
ALL_CATEGORIES = frozenset({
    "mutual_fund", "closed_end", "etf", "bdc",
    "hedge_fund", "private_fund", "ucits",
    "money_market",  # NEW
})
```

**Decision: `has_nav` for MMFs.** Money market funds have stable NAV ($1.00) — they don't need yfinance price history. The default `has_nav=True` filter will EXCLUDE MMFs unless the user explicitly selects the MMF category. Use **Option A**: When category = `money_market`, the branch handles its own `has_nav` logic (returns None if True, matching private_us pattern).

**Backend — `_build_disclosure` (screener.py line 1145):**

Add MMF-specific disclosure. The `_build_disclosure` function currently dispatches on `universe`, but MMFs use `universe="registered_us"`. Need to also check `fund_type`:

```python
def _build_disclosure(
    universe: str,
    has_holdings: bool,
    has_nav: bool,
    has_13f_overlay: bool = False,
    has_prospectus: bool = False,
    fund_type: str | None = None,  # ADD parameter
) -> DisclosureMatrix:
    if fund_type == "money_market":
        return DisclosureMatrix(
            has_holdings=False,
            has_nav_history=False,
            has_quant_metrics=False,
            has_fund_details=True,     # yield, WAM, WAL, liquidity
            has_style_analysis=False,
            has_13f_overlay=False,
            has_peer_analysis=True,
            holdings_source=None,
            nav_source=None,
            aum_source="nport",
        )
    # ... existing logic
```

Update all call sites to pass `fund_type=r.fund_type`.

**Frontend — `catalog.ts`:**

```typescript
// Add to CatalogCategory union type
export type CatalogCategory = ... | "money_market";

// Add to CATALOG_CATEGORIES array
{ key: "money_market", label: "Money Market", universe: "registered_us", icon: "..." },

// Add to FUND_TYPE_LABELS
money_market: "Money Market",
```

**Schema change — `UnifiedFundItem`:**

Add optional fields (NULL for non-MMF):
```python
# catalog.py
mmf_category: str | None = None          # Government | Prime | Tax Exempt
seven_day_gross_yield: float | None = None
weighted_avg_maturity: int | None = None  # days
weighted_avg_life: int | None = None      # days
```

**Frontend — `CatalogTable.svelte`:**

Add `yield_7d` to `UnifiedFundItem` (NULL for non-MMF). Render in the "1Y Ret" column with yield data when fund_type = money_market.

**Frontend — `CatalogDetailPanel.svelte`:**

For MMF overview tab, show MMF-specific metrics:
- WAM (Weighted Average Maturity)
- WAL (Weighted Average Life)
- 7-Day Gross Yield
- Daily / Weekly Liquidity %
- MMF Category (Government / Prime / Tax-Exempt)
- Stable NAV indicator

**Acceptance criteria:**
- [ ] `sec_money_market_funds` Table definition added to catalog_sql.py
- [ ] `_mmf_branch` function returns exactly 31 columns matching UNION ALL order
- [ ] `_all_branches` includes `_mmf_branch`
- [ ] `ALL_CATEGORIES` includes `"money_market"`
- [ ] `_build_disclosure` handles `fund_type="money_market"`
- [ ] "Money Market" category in frontend filter bar with count badge
- [ ] MMF rows show yield, WAM, AUM in table
- [ ] Detail panel shows MMF-specific overview
- [ ] Facets endpoint returns MMF counts

### 2.3 Facets — Include MMF

**Backend — screener.py facets route:**

The facets endpoint must include `money_market` in `fund_types` and `universes` counts. Since facets are computed from the same `build_catalog_query` result, adding the MMF branch to `_all_branches` should automatically include MMF in facet counts. **Verify** that the facets query does not filter branches separately.

---

## Phase 3: Disclosure Honesty & Detail Enrichment (P2)

### 3.1 Fix NAV History Disclosure

**Problem:** `has_nav_history = True` when fund has ticker. But NAV data in `nav_timeseries` only exists after the fund is imported to `instruments_universe` and the `instrument_ingestion` worker runs.

**Decision: Option A — Honest disclosure.**

Change `_build_disclosure()` to distinguish between "can have NAV" and "has NAV data":
- `has_nav_history` stays `True` (the data CAN be obtained)
- Add `nav_status: Literal["available", "pending_import", "unavailable"]` to `DisclosureMatrix`

Frontend shows:
- `"available"` → green badge "Available"
- `"pending_import"` → amber badge "Available after import"
- `"unavailable"` → gray "N/A"

#### Research Insight: `instrument_id` Not in Catalog Results

The plan originally proposed using `instrument_id IS NOT NULL` to determine if a fund was imported. **Research revealed that `instrument_id` is NOT available in the catalog SQL result set** — the catalog queries SEC/ESMA tables directly, not `instruments_universe`.

**Revised approach — LEFT JOIN to `instruments_universe`:**

For registered_us/etf/bdc branches, add a LEFT JOIN:
```python
.outerjoin(
    instruments_universe,
    and_(
        instruments_universe.c.external_id == _effective_external_id,
        instruments_universe.c.is_active == True,
    ),
)
```

Then compute:
```python
(instruments_universe.c.instrument_id.isnot(None)).label("is_imported"),
```

**Performance concern:** This adds a JOIN per branch. Alternative — **post-query enrichment** at the route level:
```python
# After fetching catalog items, batch-check which external_ids exist in instruments_universe
imported_ids = set()
if items:
    ext_ids = [i.external_id for i in items]
    result = await db.execute(
        select(Instrument.external_id)
        .where(Instrument.external_id.in_(ext_ids))
        .where(Instrument.is_active == True)
    )
    imported_ids = {r[0] for r in result.fetchall()}

# Set nav_status per item
for item in items:
    if item.disclosure.has_nav_history:
        item.disclosure.nav_status = "available" if item.external_id in imported_ids else "pending_import"
```

**Recommended:** Post-query enrichment. Single batch query, no JOIN overhead on the 50k-row UNION ALL.

**Schema change — `DisclosureMatrix`:**
```python
nav_status: Literal["available", "pending_import", "unavailable"] = "unavailable"
```

**Frontend — `CatalogDetailPanel.svelte`:**

Update disclosure matrix row for NAV History:
```svelte
{#if fund.disclosure.nav_status === "available"}
  <span class="cdp-avail">Available</span>
{:else if fund.disclosure.nav_status === "pending_import"}
  <span class="cdp-pending">After Import</span>
{:else}
  <span class="cdp-unavail">N/A</span>
{/if}
```

Add `.cdp-pending` style with amber/orange color using `var(--ii-warning)`.

**Acceptance criteria:**
- [ ] `nav_status` field added to DisclosureMatrix
- [ ] Post-query batch enrichment checks `instruments_universe` for imported funds
- [ ] Frontend renders 3-state badge (green/amber/gray)
- [ ] No performance regression (batch query, not per-row JOIN)

### 3.2 Connect Prospectus Returns (Calendar Year Bar Chart)

#### Research Insight: Already Wired

Research verified that `has_prospectus` **IS already passed** to `_build_disclosure()` at both call sites (lines 1467-1473 and 1665-1671):
```python
has_prospectus=getattr(r, "expense_ratio_pct", None) is not None,
```

And `FundDetailsTab.svelte` already renders the calendar year bar chart (lines 230-257) using data from `GET /sec/funds/{cik}/prospectus`, which queries `SecFundProspectusReturn` for annual returns.

**This means Phase 3.2 is likely already working.** The only gap is:
- Funds without `expense_ratio_pct` in `sec_fund_prospectus_stats` won't show the Fund Details tab, even if they have `sec_fund_prospectus_returns` data (calendar year returns)
- The proxy `expense_ratio_pct IS NOT NULL` may exclude some funds that have returns but no expense data

**Revised action:** Verify the overlap. If `sec_fund_prospectus_returns` has rows for funds whose `sec_fund_prospectus_stats.expense_ratio_pct IS NULL`, broaden the proxy:
```python
has_prospectus=(
    getattr(r, "expense_ratio_pct", None) is not None
    or getattr(r, "avg_annual_return_1y", None) is not None
),
```

**Acceptance criteria:**
- [ ] Verify `has_fund_details = True` for funds with prospectus stats (already working)
- [ ] Broaden proxy if needed to include funds with returns but no expense ratio
- [ ] Calendar year bar chart renders when data exists (already working)
- [ ] No new API endpoints needed

---

## Out of Scope (P3 — Future)

### UCITS AUM
ESMA Register provides no AUM. Options for future:
- Yahoo Finance `totalAssets` field via yfinance (available for ~28% of UCITS with resolved tickers)
- Would require adding to `esma_funds` table or a separate enrichment table
- Not blocking for P0-P2

### ETF/BDC `last_nport_date`
Could add via migration to `sec_etfs` and `sec_bdcs` models, populated by `nport_ingestion` worker. Low priority since coverage is ~100%.

---

## Technical Considerations

### Performance
- **AUM fallback (Phase 1.1):** Zero additional I/O — `sec_fund_classes.net_assets` is already in the joined result. No subquery needed.
- **MMF branch (Phase 2.2):** Only 373 rows — negligible impact on UNION ALL performance.
- **NAV status enrichment (Phase 3.1):** Single batch query against `instruments_universe` with `IN (external_ids)`. ~50 IDs per page. Sub-millisecond.

### Migration
- No database migrations needed — all changes are query-level and schema-level (Pydantic + TypeScript)
- `UnifiedFundItem` schema is additive (new optional fields)
- Table definitions in `catalog_sql.py` need `net_assets` column added to `sec_fund_classes` and new `sec_money_market_funds` table

### Backwards Compatibility
- `has_aum` defaults to `None` in the query parameter (not `True`) to avoid breaking existing API consumers. The server-side `CatalogFilters` default is `True`.
- New `nav_status` field is additive — existing `has_nav_history` stays unchanged.
- MMF category is additive — existing categories unaffected.
- New `fund_type` parameter in `_build_disclosure` has default `None` — existing call sites work without changes until updated.

---

## System-Wide Impact

### Interaction Graph
- `catalog_sql.py` changes → affects `/screener/catalog` route → affects frontend `+page.server.ts` → SSR render
- `_build_disclosure` changes → affects all 6 branches → affects `CatalogDetailPanel` tab rendering
- New MMF branch → affects facets endpoint → affects `CatalogFilterSidebar` counts
- NAV status enrichment → adds batch query in route handler → small latency addition (~2ms)

### Error Propagation
- All changes are read-only query modifications — no write paths affected
- If `sec_fund_classes.net_assets` is NULL (class has no XBRL data), COALESCE falls through to next level — no error
- If MMF branch returns 0 rows (all filtered), UNION ALL handles gracefully — no error

### State Lifecycle Risks
- None — catalog is read-only (no writes). Changes are to query logic only.
- Facet counts will change (fund_types now includes `money_market`). Frontend already handles dynamic facets.

### API Surface Parity
- `/screener/catalog` gains `has_aum` query param
- `UnifiedFundItem` gains 4 optional MMF fields + `nav_status` in disclosure
- `_build_disclosure` gains `fund_type` parameter
- TypeScript types in `catalog.ts` must match — run `make types` after backend changes

---

## Acceptance Criteria

### Phase 1 (P0)
- [ ] `sec_fund_classes` Table definition includes `net_assets` column
- [ ] AUM shows for significantly more registered_us funds (target: >80% coverage vs current ~60%)
- [ ] `has_holdings` is `False` for registered funds without N-PORT data
- [ ] ETF/BDC keep `has_holdings = True` with comment
- [ ] ER% uses `formatPercent` from `@investintell/ui`
- [ ] No performance regression (catalog p95 < 500ms)

### Phase 2 (P1)
- [ ] Default catalog excludes funds without AUM
- [ ] User can toggle to see all funds
- [ ] "Money Market" category visible in filter bar with count badge
- [ ] MMF detail panel shows yield, WAM, WAL, liquidity metrics
- [ ] `ALL_CATEGORIES` includes `money_market`
- [ ] `_build_disclosure` dispatches on `fund_type`
- [ ] URL param `has_aum` survives SSR page reload

### Phase 3 (P2)
- [ ] NAV History disclosure shows 3-state badge (available/pending/N/A)
- [ ] Batch enrichment checks `instruments_universe` for imported status
- [ ] `has_fund_details` proxy broadened if needed
- [ ] Calendar year returns bar chart renders in fund details (verify existing)

## Dependencies & Risks

| Risk | Mitigation |
|------|-----------|
| `sec_fund_classes.net_assets` column missing from Table definition | Verified — must add Column to Table() before COALESCE can reference it |
| `last_nport_date` missing on ETF/BDC | Verified — keep `literal(True)` with comment; future migration if needed |
| MMF `has_nav` filter interaction | When category=`money_market`, branch returns None if `has_nav=True` (private_us pattern) |
| `instrument_id` not in catalog results | Use post-query batch enrichment instead of JOIN |
| Frontend type sync | Run `make types` + `svelte-kit sync` + `pnpm check` after backend changes |
| `has_prospectus` proxy too narrow | Verify overlap between stats and returns tables; broaden if needed |
| MMF column count mismatch | Verified 31-column list; each NULL must have correct type cast |

## File Change Map

### Phase 1
| File | Change |
|------|--------|
| `backend/app/domains/wealth/queries/catalog_sql.py` | Add `net_assets` to `sec_fund_classes` Table + AUM 3-level COALESCE + `has_holdings` fix |
| `frontends/wealth/src/lib/components/screener/CatalogTable.svelte` | ER% formatter fix (2 locations) |

### Phase 2
| File | Change |
|------|--------|
| `backend/app/domains/wealth/queries/catalog_sql.py` | `sec_money_market_funds` Table + `_mmf_branch` function + `ALL_CATEGORIES` + `has_aum` filter |
| `backend/app/domains/wealth/routes/screener.py` | `has_aum` query param + `fund_type` in `_build_disclosure` + MMF disclosure |
| `backend/app/domains/wealth/schemas/catalog.py` | MMF fields in `UnifiedFundItem` |
| `frontends/wealth/src/lib/types/catalog.ts` | MMF types + `CatalogCategory` + `FUND_TYPE_LABELS` |
| `frontends/wealth/src/routes/(app)/screener/+page.svelte` | "Show all" toggle + MMF category |
| `frontends/wealth/src/routes/(app)/screener/+page.server.ts` | `has_aum` param serialization |
| `frontends/wealth/src/lib/components/screener/CatalogDetailPanel.svelte` | MMF overview metrics |
| `frontends/wealth/src/lib/components/screener/CatalogFilterSidebar.svelte` | MMF category count |

### Phase 3
| File | Change |
|------|--------|
| `backend/app/domains/wealth/schemas/catalog.py` | `nav_status` in DisclosureMatrix |
| `backend/app/domains/wealth/routes/screener.py` | `nav_status` batch enrichment + `has_prospectus` proxy review |
| `frontends/wealth/src/lib/types/catalog.ts` | `nav_status` type |
| `frontends/wealth/src/lib/components/screener/CatalogDetailPanel.svelte` | 3-state NAV badge + `.cdp-pending` style |

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md](docs/brainstorms/2026-03-16-wealth-instrument-screener-suite-brainstorm.md) — D1 (polymorphic data model), D3 (YFinance as data source), D6 (per-tenant screening config)
- **Screener stabilization backlog:** [docs/prompts/prompt-i-screener-stabilization-backlog.md](docs/prompts/prompt-i-screener-stabilization-backlog.md) — P3.1 (expense ratio/returns in catalog) already planned
- **Fund-centric model reference:** [docs/reference/fund-centric-model-reference.md](docs/reference/fund-centric-model-reference.md) — Three-universe architecture, disclosure matrix design
- **Screener audit:** conversation 2026-04-01 — full diagnostic of all 5 catalog branches, data gaps, and table connectivity
- **CI frontend type-check failures:** [docs/solutions/build-errors/ci-frontend-typecheck-failures-CIFrontendPipeline-20260323.md](docs/solutions/build-errors/ci-frontend-typecheck-failures-CIFrontendPipeline-20260323.md) — must run `svelte-kit sync` before `svelte-check`
- **Frontend wiring patterns:** [docs/solutions/architecture-patterns/endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md](docs/solutions/architecture-patterns/endpoint-coverage-multi-agent-review-frontend-wiring-20260317.md) — mutation patterns, state management, sequence counters
- **Legacy worker provider:** [docs/solutions/integration-issues/legacy-worker-direct-provider-WealthIngestion-20260319.md](docs/solutions/integration-issues/legacy-worker-direct-provider-WealthIngestion-20260319.md) — always use factory pattern for instrument data
