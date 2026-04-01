# Fix: Unified Fund Catalog — Correct Hierarchy for All Fund Types

## Context

InvestIntell Wealth OS. File: `backend/app/domains/wealth/queries/catalog_sql.py`
and `frontends/wealth/src/lib/components/screener/CatalogTable.svelte`.

The Unified Fund Catalog displays a 3-level tree. Currently the hierarchy is
structurally wrong for all fund types. This prompt fixes the data model and
rendering for all five branches.

---

## The Problem (read carefully before changing anything)

### SEC registered funds (mutual_fund, closed_end, ETF, BDC)

The real SEC hierarchy is:
```
Registrant/Trust (CIK)           ← legal shell, NOT a fund
  └── Series (series_id)          ← the actual FUND
        └── Class (class_id)      ← share class (A, C, Institutional)
```

**What the code does now:**
- `external_id = cik` (Trust level) — groups ALL series of a trust together
- `name = class_name + " - " + fund_name` — e.g. "A-Class - GUGGENHEIM FUNDS TRUST"

**What users see:** "A-Class - GUGGENHEIM FUNDS TRUST" as the L2 (fund row), with
"A-Class / C-Class / Inst-Class" repeating as L3 — wrong at every level.

**What they should see:**
```
L1 Manager:  Guggenheim Investments LLC          (sec_managers.firm_name)
  L2 Fund:   Guggenheim Global Strategic Income  (sec_fund_classes.series_name)
    L3 Class: A-Class  GIOAX                     (class_name + ticker)
    L3 Class: C-Class  SECUX
    L3 Class: Institutional  GILDX
```

### Private US funds (hedge, PE, VC, RE)

Each row in `sec_manager_funds` is a fund. PE/VC managers have multiple
vintage funds (Fund I 2016, Fund II 2019, Fund III 2022).

`sec_manager_funds` has NO `vintage_year` column today. The table has:
`crd_number, fund_name, fund_id, gross_asset_value, fund_type, strategy_label,
is_fund_of_funds, investor_count, created_at, data_fetched_at`

**What they should see for PE/VC managers:**
```
L1 Manager:  KKR & Co. Inc.
  L2 Fund:   KKR North America Fund XII    (fund_name)
    L3:      Vintage 2022  ·  $18.2B GAV   (vintage_year + gross_asset_value)
  L2 Fund:   KKR North America Fund XI
    L3:      Vintage 2017  ·  $13.9B GAV
```

For hedge funds (no vintage concept), show L2 only — no L3.

---

## Task 1 — Add `vintage_year` to `sec_manager_funds`

### Step 1a — Alembic migration

Create: `backend/alembic/versions/0072_add_vintage_year_to_sec_manager_funds.py`

```python
"""Add vintage_year to sec_manager_funds.

Revision ID: 0072
Revises: 0071
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0072"
down_revision = "0071"  # verify this is the current head before running
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sec_manager_funds",
        sa.Column("vintage_year", sa.Integer(), nullable=True),
    )
    # Back-fill: extract 4-digit year from fund_name via regex
    # Matches: "Apollo Fund IX 2019", "KKR NA XII (2022)", "Fund III, L.P. - 2018"
    op.execute("""
        UPDATE sec_manager_funds
        SET vintage_year = (
            regexp_match(fund_name, '\\b(19[89]\\d|20[012]\\d)\\b')
        )[1]::integer
        WHERE fund_name ~ '\\b(19[89]\\d|20[012]\\d)\\b'
    """)
    # Index for catalog sort/filter
    op.create_index(
        "ix_sec_manager_funds_vintage_year",
        "sec_manager_funds",
        ["vintage_year"],
        postgresql_where=sa.text("vintage_year IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sec_manager_funds_vintage_year", table_name="sec_manager_funds")
    op.drop_column("sec_manager_funds", "vintage_year")
```

IMPORTANT: Verify the current Alembic head before writing `down_revision`.
Run: `alembic heads` to confirm. Do NOT hardcode 0071 if that's not correct.

### Step 1b — Add `vintage_year` to ORM model

File: `backend/app/shared/models.py`

In `class SecManagerFund(Base, IdMixin):`, add after `investor_count`:

```python
vintage_year: Mapped[int | None] = mapped_column(Integer)
```

---

## Task 2 — Fix `catalog_sql.py` — Registered US branch

File: `backend/app/domains/wealth/queries/catalog_sql.py`

### 2a — Fix `_registered_us_branch()`

The `external_id` must be at the **series level**, not the trust (CIK) level.
The `name` must show the series name, not "ClassName - TrustName".

**Change the SELECT columns** (find the existing select() block and replace):

```python
# OLD — trust-level grouping with bad name construction
sec_registered_funds.c.cik.label("external_id"),
func.coalesce(
    sec_fund_classes.c.class_name + literal(" - ") + sec_registered_funds.c.fund_name,
    sec_registered_funds.c.fund_name,
).label("name"),

# NEW — series-level grouping, series name as fund display name
func.coalesce(
    sec_fund_classes.c.series_id,
    sec_registered_funds.c.cik,
).label("external_id"),
func.coalesce(
    sec_fund_classes.c.series_name,
    sec_registered_funds.c.fund_name,
).label("name"),
```

Also fix the `ticker` column — it should be the class-level ticker, not the
coalesced fund-level ticker (which is now irrelevant at this grouping level):

```python
# OLD
_effective_ticker = func.coalesce(
    sec_fund_classes.c.ticker, sec_registered_funds.c.ticker,
)

# NEW — class ticker takes precedence; fund ticker is fallback for single-class funds
_effective_ticker = func.coalesce(
    sec_fund_classes.c.ticker,
    sec_registered_funds.c.ticker,
)
# (same logic, but now it's used at class level — unchanged in SQL, just clarified)
```

The `series_id`, `series_name`, `class_id`, `class_name` columns in the SELECT
are already present — they are what drives L3 rendering on the frontend. No
changes needed there.

### 2b — Fix `_etf_branch()` and `_bdc_branch()`

ETFs and BDCs have `series_id` as PK and no classes. Their `external_id` is
already `series_id` — correct. The `name` is `fund_name` — correct. No changes.

---

## Task 3 — Fix `catalog_sql.py` — Private US branch

File: `backend/app/domains/wealth/queries/catalog_sql.py`

In `_private_us_branch()`, add `vintage_year` to the SELECT:

```python
# Add after investor_count in the select() columns list:
sec_manager_funds.c.vintage_year,
```

Also add `vintage_year` to the reflected `sec_manager_funds` Table definition
at the top of the file:

```python
sec_manager_funds = Table(
    "sec_manager_funds",
    _meta,
    Column("id", PG_UUID, primary_key=True),
    Column("crd_number", Text, nullable=False),
    Column("fund_name", Text, nullable=False),
    Column("fund_type", Text),
    Column("strategy_label", Text),
    Column("gross_asset_value", BigInteger),
    Column("investor_count", Integer),
    Column("is_fund_of_funds", Boolean),
    Column("vintage_year", Integer),   # ← ADD THIS
)
```

---

## Task 4 — Fix the schema: `UnifiedFundItem`

File: Find the TypeScript type for `UnifiedFundItem` in the frontend.
Run: `grep -r "UnifiedFundItem" frontends/wealth/src/lib/types/`

In the type definition, add `vintage_year`:

```ts
export interface UnifiedFundItem {
  // ... existing fields ...
  vintage_year?: number | null;   // ← ADD: private fund vintage
}
```

Also check the backend Pydantic schema for the catalog item. Find it with:
`grep -r "UnifiedFundItem\|CatalogItem\|FundCatalogItem" backend/app/domains/wealth/schemas/`

Add `vintage_year: int | None = None` to the Pydantic schema.

---

## Task 5 — Fix `CatalogTable.svelte` — correct hierarchy for all fund types

File: `frontends/wealth/src/lib/components/screener/CatalogTable.svelte`

### 5a — Fix `FundGroup` grouping logic

The current code groups by `item.external_id`. With the SQL fix in Task 2,
`external_id` is now `series_id` (or `cik` fallback) — the FUND level.
This means each series becomes its own `FundGroup`. The grouping logic in
`managerGroups` $derived block should continue working correctly.

However, `has_classes` needs a tighter condition. Update it:

```ts
// OLD
has_classes: items[0]!.universe === "registered_us" && items.length > 1 && items.some((i) => i.class_id != null),

// NEW — only registered US funds have classes; private/UCITS never do
has_classes:
    items[0]!.universe === "registered_us" &&
    items.length > 1 &&
    items.some((i) => i.class_id != null && i.class_id !== ""),
```

### 5b — Add `has_vintages` to `FundGroup`

```ts
interface FundGroup {
    fund_key: string;
    representative: UnifiedFundItem;
    classes: UnifiedFundItem[];
    has_classes: boolean;
    has_vintages: boolean;    // ← ADD: PE/VC funds with vintage_year
}
```

Populate it in the `fundGroups` construction:

```ts
const fundGroups: FundGroup[] = Array.from(fundMap.entries()).map(([key, items]) => ({
    fund_key: key,
    representative: items[0]!,
    classes: items,
    has_classes:
        items[0]!.universe === "registered_us" &&
        items.length > 1 &&
        items.some((i) => i.class_id != null && i.class_id !== ""),
    has_vintages:
        items[0]!.universe === "private_us" &&
        items.some((i) => i.vintage_year != null) &&
        items[0]!.fund_type !== "Hedge Fund",    // hedge funds have no vintage concept
}));
```

### 5c — Fix L2 fund row `onclick` to account for `has_vintages`

```ts
// OLD
onclick={() => {
    if (group.has_classes) {
        toggleFund(group.fund_key);
    } else {
        onSelectFund(group.representative);
    }
}}

// NEW
onclick={() => {
    if (group.has_classes || group.has_vintages) {
        toggleFund(group.fund_key);
    } else {
        onSelectFund(group.representative);
    }
}}
```

Also update the expand chevron visibility:

```svelte
<!-- OLD -->
{#if group.has_classes}
    <span class="ct-chevron ct-chevron--fund" ...>&#9654;</span>
{/if}

<!-- NEW -->
{#if group.has_classes || group.has_vintages}
    <span class="ct-chevron ct-chevron--fund" ...>&#9654;</span>
{/if}
```

### 5d — Add L3 vintage rows for private funds

After the existing L3 class rows block (the `{#if group.has_classes && expandedFunds.has(...)}` block),
add a sibling block for vintage rows:

```svelte
<!-- Vintage rows (L3) — PE/VC private funds only -->
{#if group.has_vintages && expandedFunds.has(group.fund_key)}
    {#each group.classes.sort((a, b) => (b.vintage_year ?? 0) - (a.vintage_year ?? 0)) as vintage (`${vintage.external_id}:${vintage.vintage_year}`)}
        <tr class="scr-inst-row ct-vintage-row" onclick={(e) => { e.stopPropagation(); onSelectFund(vintage); }}>
            <td class="ct-col-expand"></td>
            <td class="ct-col-check"></td>
            <td></td>
            <td class="ct-col-name">
                <div class="ct-vintage-name-cell">
                    <span class="ct-vintage-label">
                        {vintage.vintage_year != null ? `Vintage ${vintage.vintage_year}` : vintage.name}
                    </span>
                    {#if vintage.gross_asset_value != null}
                        <span class="ct-vintage-aum">{formatAumNeutral(vintage.gross_asset_value)}</span>
                    {/if}
                    {#if vintage.investor_count != null}
                        <span class="ct-vintage-meta">{vintage.investor_count} investors</span>
                    {/if}
                </div>
            </td>
            <td>
                <span class="ct-strategy-label">{vintage.strategy_label ?? "\u2014"}</span>
            </td>
            <td class="std-aum">{formatAumNeutral(vintage.aum)}</td>
            <td></td>
        </tr>
    {/each}
{/if}
```

### 5e — Add CSS for vintage rows

In the `<style>` block, add:

```css
/* ── Vintage rows (L3 — PE/VC) ── */
.ct-vintage-row {
    background: var(--ii-surface-alt);
    cursor: pointer;
}
.ct-vintage-row:hover {
    background: var(--ii-bg-hover);
}

.ct-vintage-name-cell {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-left: 36px;
}

.ct-vintage-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--ii-text-primary);
    font-variant-numeric: tabular-nums;
}

.ct-vintage-aum {
    font-size: 12px;
    color: var(--ii-text-secondary);
    font-variant-numeric: tabular-nums;
}

.ct-vintage-meta {
    font-size: 11px;
    color: var(--ii-text-muted);
}
```

---

## Task 6 — Update `UnifiedFundItem` backend schema + route

### 6a — Find and update the catalog item Pydantic schema

Run: `grep -rn "class.*CatalogItem\|class.*UnifiedFund\|external_id.*str" backend/app/domains/wealth/schemas/catalog.py`

Add `vintage_year: int | None = None` to the Pydantic model that represents a
catalog row. This ensures the new SQL column is serialized to the API response.

### 6b — Verify the route passes through the new column

File: `backend/app/domains/wealth/routes/screener.py`

The screener route maps SQL result rows to the Pydantic schema. Verify that the
mapping includes `vintage_year`. If the route uses `**row._mapping` or similar
dict-based construction, it will pick up new columns automatically. If it maps
fields explicitly, add `vintage_year=row.vintage_year`.

---

## Definition of Done

- [ ] Alembic migration runs: `alembic upgrade head` succeeds
- [ ] `sec_manager_funds.vintage_year` populated for funds with year in name
- [ ] `pnpm --filter netz-wealth-os run check` passes (no TypeScript errors)
- [ ] `make check` passes (backend lint + types + tests)
- [ ] Registered US funds: "GUGGENHEIM FUNDS TRUST" shows as manager (L1), each series (e.g. "Guggenheim Global Strategic Income Fund") as L2, share classes as L3
- [ ] ETFs/BDCs: display as flat L2 items under manager (no classes)
- [ ] PE/VC private funds: manager L1, fund L2, vintage rows L3 (sorted newest first)
- [ ] Hedge funds: manager L1, fund L2, no L3 (no vintage concept)
- [ ] UCITS: manager L1, fund L2, no L3 (UCITS have no share class in our data)
- [ ] `vintage_year` column present in `UnifiedFundItem` TypeScript type

## What NOT to do

- Do NOT change anything in `pgvector_search_service.py`
- Do NOT modify any other route files except `screener.py` (and only if needed for vintage_year passthrough)
- Do NOT add vintage_year to ETF/BDC/UCITS branches — it's only meaningful for private US funds
- Do NOT try to infer "fund family" from fund_name for grouping purposes — each `sec_manager_funds` row is already one fund, no further grouping needed at L2
- Do NOT change the `_etf_branch` or `_bdc_branch` SQL — their external_id is already correct (series_id)
- Do NOT change the UCITS branch — it has no series/class structure in the current data
- After adding vintage_year to the ORM model, do NOT run `alembic autogenerate` — the migration is written manually above
- Do NOT use `session.execute(text(...))` for the vintage_year backfill in application code — it's a one-time migration operation only

## Verification commands

```bash
# Backend
cd backend
alembic heads                          # verify current head before migration
alembic upgrade head                   # run migration
python -c "
from sqlalchemy import create_engine, text
import os
e = create_engine(os.environ['DATABASE_URL_SYNC'])
with e.connect() as c:
    r = c.execute(text('SELECT COUNT(*) FROM sec_manager_funds WHERE vintage_year IS NOT NULL'))
    print('Funds with vintage_year:', r.scalar())
"

# Frontend
cd frontends/wealth
pnpm run check
```
