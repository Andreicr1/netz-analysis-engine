# Screener FCL + Enterprise Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replicar no `/screener` o padrão enterprise table já validado em `/portfolio/universe` e envolver tudo num layout SAP UI5 Flexible Column Layout 3 colunas (Managers → Funds → DD/Analytics/FactSheet), aproveitando full-width da janela sem perder contexto de navegação top-down.

**Architecture:** CSS Grid `fr` interpolável com transição 240ms controlada 100% pela URL (`?manager=&fund=&view=`). Componentes neutros promovidos para `@netz/ui`: `FlexibleColumnLayout` (extração do atual, sem acoplamento a Portfolio Builder) e `EnterpriseTable` (extração do padrão UniverseTable com snippets tipados). Backend DB-only via `mv_unified_funds` com keyset pagination, SSE via Redis pub/sub para DD streaming, ECharts institucional com dataset compartilhado para NAV+drawdown.

**Tech Stack:** SvelteKit 2 + Svelte 5 runes + `@netz/ui` + svelte-echarts + FastAPI + PostgreSQL 16 + TimescaleDB + Redis + pgvector

**Decisions locked (Andrei, 2026-04-07):**
- Col2 default sort: `AUM DESC` (flagship-first institutional standard)
- Col3 Analytics default window: `3y` (36 meses, industry standard)
- `nav_monthly_returns_agg`: diagnóstico em prod **antes** de qualquer código
- L3 score em Col1: **apenas Layer 1 eliminatório no SQL** (sem worker batch novo neste sprint)
- UCITS vs US: **filtro separado** (sem LEI bridge)
- `FlexibleColumnsLayout`: **promover** para `@netz/ui` e migrar Portfolio Builder no mesmo PR
- `CatalogTable` + `CatalogTableV2`: **ambos eliminados** — nenhum é base canônica (ambos usam `@tanstack/svelte-table` quebrado no Svelte 5). Base vem da extração do `UniverseTable.svelte`.

---

## Phase 0 — Prod Diagnostics (bloqueadores)

Antes de qualquer migration ou código, confirmar o estado real de produção.

### Task 0.1: Diagnose `nav_monthly_returns_agg` state

**Files:**
- Report: `docs/superpowers/diagnostics/2026-04-07-nav-cagg-state.md`

- [ ] **Step 1: Query Timescale continuous aggregates metadata**

Run against Timescale Cloud prod (read-only):
```sql
SELECT view_name, materialization_hypertable_name, view_definition
FROM timescaledb_information.continuous_aggregates
WHERE view_name = 'nav_monthly_returns_agg';
```
Expected: 1 row. If 0 rows → CAGG foi dropada e nunca recriada.

- [ ] **Step 2: Query column structure**

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'nav_monthly_returns_agg'
ORDER BY ordinal_position;
```
Expected: NO `organization_id` column. If present → mig 0069 não completou o rebuild.

- [ ] **Step 3: Sample data freshness**

```sql
SELECT instrument_id, MAX(month) AS last_bucket, COUNT(*) AS buckets
FROM nav_monthly_returns_agg
GROUP BY instrument_id
ORDER BY last_bucket DESC
LIMIT 10;
```
Expected: `last_bucket` within current month. Stale → refresh policy quebrada.

- [ ] **Step 4: Write diagnostic report**

Create `docs/superpowers/diagnostics/2026-04-07-nav-cagg-state.md` with findings. Classify state as: `OK`, `BROKEN_NEEDS_REBUILD`, `STALE_NEEDS_REFRESH`, or `MISSING_NEEDS_CREATE`. This drives whether Phase 1 Task 1.2 is a fix or a no-op.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/diagnostics/2026-04-07-nav-cagg-state.md
git commit -m "docs: nav_monthly_returns_agg prod state diagnostic"
```

### Task 0.2: Update CLAUDE.md migration head reference

**Files:**
- Modify: `CLAUDE.md` (line mentioning `0079_macro_performance_layer`)

- [ ] **Step 1: Confirm actual head**

Run: `ls backend/app/core/db/migrations/versions/ | sort | tail -5`
Expected: `0092_wealth_library_triggers.py` (or higher).

- [ ] **Step 2: Update CLAUDE.md**

Edit the line `Current migration head: \`0079_macro_performance_layer\`` to reference the real head from Step 1.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: sync CLAUDE.md migration head to actual state"
```

---

## Phase 1 — Foundation (DB indexes + chart tokens)

Sem mudança de UX. Prepara o terreno para Phases 2-5.

### Task 1.1: Create Alembic migration for FCL keyset indexes

**Files:**
- Create: `backend/app/core/db/migrations/versions/0093_screener_fcl_keyset_indexes.py`
- Test: `backend/tests/db/test_migration_0093.py`

- [ ] **Step 1: Write failing test for index existence**

```python
# backend/tests/db/test_migration_0093.py
import pytest
from sqlalchemy import text

@pytest.mark.asyncio
async def test_sec_managers_aum_crd_index_exists(db_session):
    result = await db_session.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'sec_managers'
          AND indexname = 'idx_sec_managers_aum_crd'
    """))
    assert result.scalar() == 'idx_sec_managers_aum_crd'

@pytest.mark.asyncio
async def test_mv_unified_funds_mgr_aum_index_exists(db_session):
    result = await db_session.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'mv_unified_funds'
          AND indexname = 'idx_mv_unified_funds_mgr_aum'
    """))
    assert result.scalar() == 'idx_mv_unified_funds_mgr_aum'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/db/test_migration_0093.py -v`
Expected: FAIL (index missing).

- [ ] **Step 3: Write migration**

```python
# backend/app/core/db/migrations/versions/0093_screener_fcl_keyset_indexes.py
"""screener FCL keyset indexes

Revision ID: 0093_screener_fcl_keyset_indexes
Revises: 0092_wealth_library_triggers
Create Date: 2026-04-07
"""
from alembic import op

revision = "0093_screener_fcl_keyset_indexes"
down_revision = "0092_wealth_library_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Col1 keyset: (aum_total DESC, crd_number ASC)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sec_managers_aum_crd
          ON sec_managers (aum_total DESC NULLS LAST, crd_number ASC)
          WHERE aum_total IS NOT NULL
    """)
    # Col2 keyset: (manager_id, aum_usd DESC)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_unified_funds_mgr_aum
          ON mv_unified_funds (manager_id, aum_usd DESC NULLS LAST)
          WHERE manager_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_mv_unified_funds_mgr_aum")
    op.execute("DROP INDEX IF EXISTS idx_sec_managers_aum_crd")
```

Note: NOT using `CONCURRENTLY` because Alembic wraps `upgrade()` in a transaction and `CREATE INDEX CONCURRENTLY` cannot run inside one. For prod rollout, ship as separate manual ops with `autocommit_block()` if table size warrants — current sizes (`sec_managers` ~15k rows, `mv_unified_funds` ~50k rows) make blocking index acceptable.

- [ ] **Step 4: Run migration + test**

```bash
make migrate
pytest backend/tests/db/test_migration_0093.py -v
```
Expected: migration applies, both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/db/migrations/versions/0093_screener_fcl_keyset_indexes.py backend/tests/db/test_migration_0093.py
git commit -m "feat(db): keyset indexes for screener FCL col1/col2 pagination"
```

### Task 1.2: Fix `nav_monthly_returns_agg` if diagnostic flagged it

**Files:**
- Create: `backend/app/core/db/migrations/versions/0094_nav_cagg_fix.py` (only if Phase 0 Task 0.1 flagged BROKEN/MISSING)

- [ ] **Step 1: Conditional task based on diagnostic**

If Task 0.1 classified as `OK`, skip this task entirely. If `BROKEN_NEEDS_REBUILD` or `MISSING_NEEDS_CREATE`, proceed.

- [ ] **Step 2: Write migration to recreate CAGG without organization_id**

```python
# backend/app/core/db/migrations/versions/0094_nav_cagg_fix.py
from alembic import op

revision = "0094_nav_cagg_fix"
down_revision = "0093_screener_fcl_keyset_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS nav_monthly_returns_agg CASCADE")
    op.execute("""
        CREATE MATERIALIZED VIEW nav_monthly_returns_agg
        WITH (timescaledb.continuous) AS
        SELECT
            instrument_id,
            time_bucket('1 month', nav_date) AS month,
            SUM(return_1d) AS compound_log_return,
            (EXP(SUM(return_1d)) - 1) AS compound_return,
            COUNT(*) AS trading_days,
            LAST(nav, nav_date) AS month_end_nav
        FROM nav_timeseries
        WHERE return_1d IS NOT NULL
        GROUP BY instrument_id, time_bucket('1 month', nav_date)
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('nav_monthly_returns_agg',
            start_offset => INTERVAL '3 months',
            end_offset => INTERVAL '1 day',
            schedule_interval => INTERVAL '1 day')
    """)
    op.execute("CALL refresh_continuous_aggregate('nav_monthly_returns_agg', NULL, NULL)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS nav_monthly_returns_agg CASCADE")
```

- [ ] **Step 3: Apply migration**

```bash
make migrate
```
Expected: CAGG rebuilt, initial refresh kicks off.

- [ ] **Step 4: Verify with sample query**

```sql
SELECT instrument_id, month, compound_return
FROM nav_monthly_returns_agg
ORDER BY month DESC
LIMIT 5;
```
Expected: recent rows returned.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/db/migrations/versions/0094_nav_cagg_fix.py
git commit -m "fix(db): rebuild nav_monthly_returns_agg without organization_id"
```

### Task 1.3: Chart foundation — CSS variables + tokens module

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/chart-tokens.ts`
- Create: `frontends/wealth/src/lib/components/charts/tooltips.ts`
- Modify: `packages/ui/src/lib/charts/echarts-setup.ts` (if exists; otherwise locate actual setup file)
- Modify: `frontends/wealth/src/app.css` (add `--chart-*` CSS variables)

- [ ] **Step 1: Locate existing echarts setup**

Run: Grep for `globalChartOptions` or `echarts.registerTheme` across `packages/ui/` and `frontends/wealth/`.

- [ ] **Step 2: Define CSS variables in wealth app.css**

Add to `frontends/wealth/src/app.css`:
```css
:root {
  /* Chart palette — light mode */
  --chart-primary: 214 100% 50%;        /* #0066ff neon blue */
  --chart-benchmark: 220 15% 55%;
  --chart-positive: 150 70% 40%;
  --chart-negative: 0 72% 50%;
  --chart-regime-stress: 30 95% 55% / 0.08;
  --chart-regime-normal: 210 30% 50% / 0.04;
  --chart-grid: 220 15% 90%;
  --chart-axis-label: 220 15% 35%;
  --chart-tooltip-bg: 0 0% 100%;
  --chart-tooltip-border: 220 15% 85%;
  --chart-font: 'Urbanist', system-ui, sans-serif;
}

:root.dark {
  --chart-primary: 214 100% 60%;
  --chart-benchmark: 220 10% 60%;
  --chart-positive: 150 60% 50%;
  --chart-negative: 0 65% 55%;
  --chart-regime-stress: 30 85% 60% / 0.12;
  --chart-regime-normal: 210 25% 45% / 0.06;
  --chart-grid: 220 10% 20%;
  --chart-axis-label: 220 10% 65%;
  --chart-tooltip-bg: 220 15% 12%;
  --chart-tooltip-border: 220 10% 25%;
}
```

- [ ] **Step 3: Create `chart-tokens.ts` reader**

```ts
// frontends/wealth/src/lib/components/charts/chart-tokens.ts
function cssVar(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v ? `hsl(${v})` : fallback;
}

export function chartTokens() {
  return {
    primary: cssVar('--chart-primary', '#0066ff'),
    benchmark: cssVar('--chart-benchmark', '#7a869a'),
    positive: cssVar('--chart-positive', '#1fa971'),
    negative: cssVar('--chart-negative', '#d94949'),
    regimeStress: cssVar('--chart-regime-stress', 'rgba(255,140,0,0.08)'),
    regimeNormal: cssVar('--chart-regime-normal', 'rgba(100,120,140,0.04)'),
    grid: cssVar('--chart-grid', '#e5e7eb'),
    axisLabel: cssVar('--chart-axis-label', '#4b5563'),
    tooltipBg: cssVar('--chart-tooltip-bg', '#ffffff'),
    tooltipBorder: cssVar('--chart-tooltip-border', '#d1d5db'),
    fontFamily: cssVar('--chart-font', 'Urbanist, system-ui, sans-serif')
      .replace(/^hsl\(|\)$/g, ''),
  };
}

export type ChartTokens = ReturnType<typeof chartTokens>;
```

- [ ] **Step 4: Create tooltip formatters**

```ts
// frontends/wealth/src/lib/components/charts/tooltips.ts
import { formatCurrency, formatPercent, formatShortDate } from '@netz/ui';
import type { ChartTokens } from './chart-tokens';

export function navTooltipFormatter(tokens: ChartTokens) {
  return (params: any) => {
    const items = Array.isArray(params) ? params : [params];
    const date = formatShortDate(new Date(items[0].axisValue));
    const rows = items
      .map((p) => {
        const label = p.seriesName;
        const value = typeof p.value === 'number' ? p.value : p.value?.[1];
        const formatted = formatPercent(value, 2);
        return `<div style="display:flex;justify-content:space-between;gap:16px;font-variant-numeric:tabular-nums">
                  <span style="color:${tokens.axisLabel}">${label}</span>
                  <strong>${formatted}</strong>
                </div>`;
      })
      .join('');
    return `<div style="font-family:${tokens.fontFamily};font-size:12px;padding:4px 2px">
              <div style="color:${tokens.axisLabel};margin-bottom:6px">${date}</div>
              ${rows}
            </div>`;
  };
}
```

- [ ] **Step 5: Fix echarts-setup to consume tokens**

Replace any hex literals and `Geist` font refs in `packages/ui/src/lib/charts/echarts-setup.ts` (or equivalent) with a function that accepts `ChartTokens` and returns `globalChartOptions`. Remove the static hex palette; callers pass `chartTokens()` on theme change.

- [ ] **Step 6: Run frontend type check**

Run: `cd frontends/wealth && pnpm check`
Expected: no new type errors.

- [ ] **Step 7: Commit**

```bash
git add frontends/wealth/src/lib/components/charts/ frontends/wealth/src/app.css packages/ui/src/lib/charts/echarts-setup.ts
git commit -m "feat(charts): CSS var tokens + Urbanist + tooltip formatters"
```

---

## Phase 2 — Neutral components in `@netz/ui`

Extração dos dois primitives que tanto Screener quanto Portfolio Builder vão consumir. Inclui refactor do Portfolio Builder no mesmo PR para evitar débito paralelo.

### Task 2.1: Promote `FlexibleColumnLayout` to `@netz/ui` (neutral)

**Files:**
- Create: `packages/ui/src/lib/layouts/FlexibleColumnLayout.svelte`
- Modify: `packages/ui/src/lib/index.ts` (export)
- Test: `packages/ui/src/lib/layouts/FlexibleColumnLayout.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// packages/ui/src/lib/layouts/FlexibleColumnLayout.test.ts
import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import FlexibleColumnLayout from './FlexibleColumnLayout.svelte';

test('expand-1 state hides col2 and col3', () => {
  const { container } = render(FlexibleColumnLayout, {
    props: {
      state: 'expand-1',
      column1Label: 'List',
      column2Label: 'Detail',
      column3Label: 'Sub-detail',
    },
  });
  const root = container.querySelector('.fcl-root') as HTMLElement;
  expect(root.style.gridTemplateColumns).toContain('0fr');
  expect(root.dataset.state).toBe('expand-1');
});

test('custom ratios override defaults', () => {
  const { container } = render(FlexibleColumnLayout, {
    props: {
      state: 'expand-3',
      ratios: { 'expand-3': [0.1, 0.3, 0.6] },
      column1Label: 'A', column2Label: 'B', column3Label: 'C',
    },
  });
  const root = container.querySelector('.fcl-root') as HTMLElement;
  expect(root.style.gridTemplateColumns).toContain('0.1fr');
  expect(root.style.gridTemplateColumns).toContain('0.6fr');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/ui && pnpm test FlexibleColumnLayout`
Expected: FAIL (component missing).

- [ ] **Step 3: Implement neutral component**

```svelte
<!-- packages/ui/src/lib/layouts/FlexibleColumnLayout.svelte -->
<!--
  Neutral 3-column FCL primitive. Caller owns semantics via labels + ratios.
  State is caller-derived from URL — NEVER $bindable.
-->
<script lang="ts" module>
  export type FCLState = 'expand-1' | 'expand-2' | 'expand-3';
  export type FCLRatios = Record<FCLState, [number, number, number]>;

  export const DEFAULT_RATIOS: FCLRatios = {
    'expand-1': [1, 0, 0],
    'expand-2': [0.32, 0.68, 0],
    'expand-3': [0.22, 0.42, 0.36],
  };
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    state: FCLState;
    ratios?: Partial<FCLRatios>;
    column1: Snippet;
    column2: Snippet;
    column3: Snippet;
    column1Label: string;
    column2Label: string;
    column3Label: string;
    overlayBreakpoint?: number;
  }

  let {
    state,
    ratios,
    column1,
    column2,
    column3,
    column1Label,
    column2Label,
    column3Label,
  }: Props = $props();

  const resolvedRatios = $derived<[number, number, number]>(
    ratios?.[state] ?? DEFAULT_RATIOS[state],
  );

  const gridTemplate = $derived(
    resolvedRatios.map((r) => (r === 0 ? '0fr' : `minmax(0, ${r}fr)`)).join(' '),
  );

  const col1Collapsed = $derived(resolvedRatios[0] === 0);
  const col2Collapsed = $derived(resolvedRatios[1] === 0);
  const col3Collapsed = $derived(resolvedRatios[2] === 0);
</script>

<div
  class="fcl-root"
  style:grid-template-columns={gridTemplate}
  data-state={state}
>
  <section
    class="fcl-col fcl-col-1"
    class:fcl-col--collapsed={col1Collapsed}
    aria-hidden={col1Collapsed}
    aria-label={column1Label}
  >
    {@render column1()}
  </section>
  <section
    class="fcl-col fcl-col-2"
    class:fcl-col--collapsed={col2Collapsed}
    aria-hidden={col2Collapsed}
    aria-label={column2Label}
  >
    {@render column2()}
  </section>
  <section
    class="fcl-col fcl-col-3"
    class:fcl-col--collapsed={col3Collapsed}
    aria-hidden={col3Collapsed}
    aria-label={column3Label}
  >
    {@render column3()}
  </section>
</div>

<style>
  .fcl-root {
    display: grid;
    width: 100%;
    height: 100%;
    min-height: 0;
    gap: 0;
    background: var(--ii-bg-canvas, #0e0f13);
    border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
    transition: grid-template-columns 240ms cubic-bezier(0.4, 0, 0.2, 1);
    container-type: inline-size;
    container-name: fcl;
  }
  .fcl-col {
    min-width: 0;
    min-height: 0;
    overflow: auto;
    background: var(--ii-bg-surface, #141519);
    position: relative;
  }
  .fcl-col-2, .fcl-col-3 {
    border-left: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
  }
  .fcl-col--collapsed {
    visibility: hidden;
    pointer-events: none;
    border: none;
  }
  @media (prefers-reduced-motion: reduce) {
    .fcl-root { transition: none; }
  }
  @container fcl (max-width: 1100px) {
    .fcl-root[data-state='expand-3'] {
      grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) 0fr;
    }
    .fcl-root[data-state='expand-3'] .fcl-col-3 {
      position: absolute;
      top: 0; right: 0; bottom: 0;
      width: min(520px, 80%);
      visibility: visible;
      pointer-events: auto;
      border-left: 1px solid var(--ii-border-subtle);
      box-shadow: -12px 0 32px -16px rgb(0 0 0 / 0.4);
      z-index: 10;
    }
  }
</style>
```

- [ ] **Step 4: Export from `@netz/ui`**

Add to `packages/ui/src/lib/index.ts`:
```ts
export { default as FlexibleColumnLayout } from './layouts/FlexibleColumnLayout.svelte';
export type { FCLState, FCLRatios } from './layouts/FlexibleColumnLayout.svelte';
export { DEFAULT_RATIOS as FCL_DEFAULT_RATIOS } from './layouts/FlexibleColumnLayout.svelte';
```

- [ ] **Step 5: Run test**

Run: `cd packages/ui && pnpm test FlexibleColumnLayout`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/ui/src/lib/layouts/FlexibleColumnLayout.svelte packages/ui/src/lib/layouts/FlexibleColumnLayout.test.ts packages/ui/src/lib/index.ts
git commit -m "feat(ui): neutral FlexibleColumnLayout primitive"
```

### Task 2.2: Migrate Portfolio Builder to neutral FCL

**Files:**
- Modify: `frontends/wealth/src/lib/components/layout/FlexibleColumnsLayout.svelte` → delete
- Modify: `frontends/wealth/src/routes/(app)/portfolio/+page.svelte` (or whatever consumes it)

- [ ] **Step 1: Grep for old component consumers**

Run: `grep -rn "FlexibleColumnsLayout" frontends/wealth/src/`

- [ ] **Step 2: Replace imports and usage**

For each consumer, update:
```ts
// Before
import FlexibleColumnsLayout from '$lib/components/layout/FlexibleColumnsLayout.svelte';
type LayoutState = 'landing' | 'two-col' | 'three-col';

// After
import { FlexibleColumnLayout, type FCLState } from '@netz/ui';

// Map old → new
const state = $derived<FCLState>(
  selectedAnalyticsFund ? 'expand-3' : portfolioId ? 'expand-2' : 'expand-1',
);

// Pass Portfolio Builder-specific ratios (preserves exact current proportions)
const PORTFOLIO_RATIOS = {
  'expand-1': [0, 1, 0],         // landing: center only
  'expand-2': [1.4, 1, 0],       // two-col: universe wide, builder
  'expand-3': [1.5, 1, 1.1],     // three-col: current values
} as const;
```

Template change:
```svelte
<FlexibleColumnLayout
  {state}
  ratios={PORTFOLIO_RATIOS}
  column1Label="Approved Universe"
  column2Label="Portfolio Builder"
  column3Label="Analytics"
  column1={leftColumn}
  column2={centerColumn}
  column3={rightColumn}
/>
```

- [ ] **Step 3: Delete the old component**

```bash
rm frontends/wealth/src/lib/components/layout/FlexibleColumnsLayout.svelte
```

- [ ] **Step 4: Visual validation in browser**

Run: `make dev-wealth`. Open `/portfolio`. Verify:
- Landing state (no portfolio selected): Builder only
- Two-col (portfolio selected): Universe + Builder, transition smooth
- Three-col (fund selected for Analytics): all three columns, same proportions as before
- Resize window to < 1100px: Analytics becomes overlay

- [ ] **Step 5: Run check suite**

```bash
cd frontends/wealth && pnpm check
```
Expected: zero new errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(portfolio): migrate Builder to neutral FlexibleColumnLayout from @netz/ui"
```

### Task 2.3: Extract `EnterpriseTable` from UniverseTable pattern

**Files:**
- Create: `packages/ui/src/lib/table/EnterpriseTable.svelte`
- Create: `packages/ui/src/lib/table/types.ts`
- Modify: `packages/ui/src/lib/index.ts`
- Test: `packages/ui/src/lib/table/EnterpriseTable.test.ts`

- [ ] **Step 1: Read the reference UniverseTable**

Read `frontends/wealth/src/lib/components/portfolio/UniverseTable.svelte` entirely. Identify:
- Sticky header CSS
- Tabular-nums treatment on numeric columns
- Container queries for responsive column hiding
- Zebra row pattern
- Row click handler contract

- [ ] **Step 2: Define types**

```ts
// packages/ui/src/lib/table/types.ts
export interface ColumnDef<TRow> {
  id: string;
  header: string;
  width?: string;
  align?: 'left' | 'right' | 'center';
  numeric?: boolean;
  freezable?: boolean;
  hideBelow?: number; // container query px breakpoint
  accessor: (row: TRow) => unknown;
  format?: (value: unknown, row: TRow) => string;
}
```

- [ ] **Step 3: Write the failing test**

```ts
// packages/ui/src/lib/table/EnterpriseTable.test.ts
import { render } from '@testing-library/svelte';
import { expect, test } from 'vitest';
import EnterpriseTable from './EnterpriseTable.svelte';
import type { ColumnDef } from './types';

interface Row { id: string; name: string; aum: number; }

const rows: Row[] = [
  { id: '1', name: 'Alpha Fund', aum: 1_200_000_000 },
  { id: '2', name: 'Beta Fund', aum: 800_000_000 },
];
const columns: ColumnDef<Row>[] = [
  { id: 'name', header: 'Name', accessor: (r) => r.name },
  { id: 'aum', header: 'AUM', numeric: true, accessor: (r) => r.aum, format: (v) => `${((v as number) / 1e6).toFixed(1)}M` },
];

test('renders headers and rows', () => {
  const { getByText } = render(EnterpriseTable<Row>, {
    props: { rows, columns, rowKey: (r: Row) => r.id },
  });
  expect(getByText('Name')).toBeTruthy();
  expect(getByText('Alpha Fund')).toBeTruthy();
  expect(getByText('1200.0M')).toBeTruthy();
});

test('numeric column gets tabular-nums class', () => {
  const { container } = render(EnterpriseTable<Row>, {
    props: { rows, columns, rowKey: (r: Row) => r.id },
  });
  const aumCells = container.querySelectorAll('td.et-num');
  expect(aumCells.length).toBe(2);
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd packages/ui && pnpm test EnterpriseTable`
Expected: FAIL (component missing).

- [ ] **Step 5: Implement `EnterpriseTable.svelte`**

```svelte
<!-- packages/ui/src/lib/table/EnterpriseTable.svelte -->
<script lang="ts" generics="TRow">
  import type { Snippet } from 'svelte';
  import type { ColumnDef } from './types';

  interface Props {
    rows: TRow[];
    columns: ColumnDef<TRow>[];
    rowKey: (row: TRow) => string;
    headerCell?: Snippet<[ColumnDef<TRow>]>;
    cell?: Snippet<[TRow, ColumnDef<TRow>]>;
    rowAttrs?: (row: TRow) => Record<string, unknown>;
    stickyHeader?: boolean;
    freezeFirstColumn?: boolean;
    density?: 'compact' | 'comfortable';
    emptyState?: Snippet;
    onRowClick?: (row: TRow) => void;
  }

  let {
    rows,
    columns,
    rowKey,
    headerCell,
    cell,
    rowAttrs,
    stickyHeader = true,
    freezeFirstColumn = false,
    density = 'compact',
    emptyState,
    onRowClick,
  }: Props = $props();

  function formatCell(row: TRow, col: ColumnDef<TRow>): string {
    const value = col.accessor(row);
    if (col.format) return col.format(value, row);
    return value == null ? '' : String(value);
  }
</script>

<div class="et-wrap" data-density={density}>
  {#if rows.length === 0 && emptyState}
    {@render emptyState()}
  {:else}
    <table class="et-table" class:et-sticky={stickyHeader} class:et-freeze={freezeFirstColumn}>
      <thead>
        <tr>
          {#each columns as col (col.id)}
            <th
              class:et-num={col.numeric}
              class:et-center={col.align === 'center'}
              style:width={col.width}
              style:text-align={col.align}
              data-hide-below={col.hideBelow}
            >
              {#if headerCell}{@render headerCell(col)}{:else}{col.header}{/if}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as row (rowKey(row))}
          {@const extra = rowAttrs?.(row) ?? {}}
          <tr
            {...extra}
            onclick={onRowClick ? () => onRowClick(row) : undefined}
            class:et-clickable={!!onRowClick}
          >
            {#each columns as col (col.id)}
              <td
                class:et-num={col.numeric}
                class:et-center={col.align === 'center'}
                style:text-align={col.align}
                data-hide-below={col.hideBelow}
              >
                {#if cell}
                  {@render cell(row, col)}
                {:else}
                  {formatCell(row, col)}
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .et-wrap {
    width: 100%;
    height: 100%;
    overflow: auto;
    container-type: inline-size;
  }
  .et-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-family: 'Urbanist', system-ui, sans-serif;
    font-size: 13px;
    color: var(--ii-text-primary, #e6e8ec);
  }
  .et-table thead th {
    background: var(--ii-bg-surface-alt, #1a1c22);
    color: var(--ii-text-muted, #85a0bd);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 10px 12px;
    border-bottom: 1px solid var(--ii-border-subtle, rgba(64,66,73,0.4));
    text-align: left;
    white-space: nowrap;
  }
  .et-sticky thead th {
    position: sticky;
    top: 0;
    z-index: 2;
  }
  .et-freeze thead th:first-child,
  .et-freeze tbody td:first-child {
    position: sticky;
    left: 0;
    background: var(--ii-bg-surface, #141519);
    z-index: 1;
  }
  .et-freeze thead th:first-child {
    z-index: 3;
  }
  .et-table tbody tr:nth-child(even) td {
    background: var(--ii-bg-surface-alt, rgba(255,255,255,0.015));
  }
  .et-table tbody td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--ii-border-hairline, rgba(64,66,73,0.2));
    white-space: nowrap;
  }
  [data-density='comfortable'] .et-table tbody td { padding: 12px 14px; }
  [data-density='comfortable'] .et-table thead th { padding: 14px 14px; }
  .et-num { font-variant-numeric: tabular-nums; text-align: right; }
  .et-center { text-align: center; }
  .et-clickable { cursor: pointer; }
  .et-clickable:hover td { background: var(--ii-bg-hover, rgba(80,140,255,0.06)); }

  @container (max-width: 900px) {
    [data-hide-below='900'] { display: none; }
  }
  @container (max-width: 1200px) {
    [data-hide-below='1200'] { display: none; }
  }
</style>
```

- [ ] **Step 6: Export and test**

Add to `packages/ui/src/lib/index.ts`:
```ts
export { default as EnterpriseTable } from './table/EnterpriseTable.svelte';
export type { ColumnDef } from './table/types';
```

Run: `cd packages/ui && pnpm test EnterpriseTable`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/ui/src/lib/table/ packages/ui/src/lib/index.ts
git commit -m "feat(ui): EnterpriseTable primitive with snippet-based customization"
```

### Task 2.4: Delete `CatalogTable` + `CatalogTableV2`

**Files:**
- Delete: `frontends/wealth/src/lib/components/screener/CatalogTable.svelte`
- Delete: `frontends/wealth/src/lib/components/screener/CatalogTableV2.svelte`
- Modify: Any route consuming them (will be rewritten in Phase 4)

- [ ] **Step 1: Grep for consumers**

Run: `grep -rn "CatalogTable" frontends/wealth/src/`
Note every file that imports either.

- [ ] **Step 2: Temporarily stub the old screener route**

Replace the screener `+page.svelte` body with a placeholder:
```svelte
<script lang="ts">
  // Temporarily stubbed during FCL migration. Real impl in Phase 4.
</script>
<div class="p-8 text-center text-muted">
  Screener is being rebuilt. Check back after Phase 4.
</div>
```
This keeps `make check` green while we land the component deletion.

- [ ] **Step 3: Delete both files**

```bash
rm frontends/wealth/src/lib/components/screener/CatalogTable.svelte
rm frontends/wealth/src/lib/components/screener/CatalogTableV2.svelte
```

- [ ] **Step 4: Run frontend check**

```bash
cd frontends/wealth && pnpm check
```
Expected: zero errors (or only errors about the stubbed page, which are fine).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(screener): delete CatalogTable v1/v2 ahead of FCL rewrite"
```

---

## Phase 3 — Backend routes + caching

Rotas DB-only alimentando Col1/Col2/Col3, com Redis cache + SingleFlightLock.

### Task 3.1: Schemas + keyset helpers

**Files:**
- Create: `backend/app/domains/wealth/schemas/screener_fcl.py`
- Create: `backend/app/domains/wealth/queries/screener_keyset.py`
- Test: `backend/tests/domains/wealth/test_screener_keyset.py`

- [ ] **Step 1: Write Pydantic schemas**

```python
# backend/app/domains/wealth/schemas/screener_fcl.py
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

class ScreenerFilters(BaseModel):
    strategies: list[str] | None = None
    geographies: list[str] | None = None
    fund_types: list[str] | None = None
    min_aum_usd: float | None = None
    max_expense_ratio_pct: float | None = None
    region: Literal["US", "EU", "ALL"] = "ALL"

class ManagerCursor(BaseModel):
    aum: float | None = None
    crd: str | None = None

class ManagerRow(BaseModel):
    manager_id: str
    manager_name: str
    firm_name: str | None
    cik: str | None
    aum_total: float | None
    fund_count: int
    fund_types: list[str]
    strategy_label_top: str | None

class ManagersListResponse(BaseModel):
    rows: list[ManagerRow]
    next_cursor: ManagerCursor | None
    total_estimate: int | None = None

class FundCursor(BaseModel):
    aum: float | None = None
    external_id: str | None = None

class FundRow(BaseModel):
    external_id: str
    universe: str
    name: str
    ticker: str | None
    isin: str | None
    fund_type: str | None
    strategy_label: str | None
    aum_usd: float | None
    currency: str | None
    domicile: str | None
    series_id: str | None
    has_holdings: bool
    has_nav: bool
    expense_ratio_pct: float | None
    avg_annual_return_1y: float | None
    avg_annual_return_10y: float | None

class FundsListResponse(BaseModel):
    rows: list[FundRow]
    next_cursor: FundCursor | None
    manager_summary: ManagerRow
```

- [ ] **Step 2: Write the failing keyset test**

```python
# backend/tests/domains/wealth/test_screener_keyset.py
import pytest
from backend.app.domains.wealth.queries.screener_keyset import (
    build_managers_query, build_funds_query,
)
from backend.app.domains.wealth.schemas.screener_fcl import (
    ScreenerFilters, ManagerCursor, FundCursor,
)

def test_managers_query_no_cursor_no_filters():
    sql, params = build_managers_query(ScreenerFilters(), cursor=None, limit=50)
    assert "ORDER BY sm.aum_total DESC NULLS LAST" in sql
    assert "LIMIT" in sql
    assert params["limit"] == 50
    assert params["cursor_aum"] is None

def test_managers_query_with_strategy_filter():
    sql, params = build_managers_query(
        ScreenerFilters(strategies=["Private Credit", "Buyout"]),
        cursor=None, limit=50,
    )
    assert "strategy_label = ANY" in sql
    assert params["strategies"] == ["Private Credit", "Buyout"]

def test_managers_query_with_keyset_cursor():
    sql, params = build_managers_query(
        ScreenerFilters(),
        cursor=ManagerCursor(aum=500_000_000, crd="123456"),
        limit=50,
    )
    assert "(sm.aum_total, g.manager_id) <" in sql
    assert params["cursor_aum"] == 500_000_000
    assert params["cursor_id"] == "123456"

def test_funds_query_by_manager_aum_sort():
    sql, params = build_funds_query(
        manager_id="123456", cursor=None, limit=50,
    )
    assert "WHERE manager_id = :manager_id" in sql
    assert "ORDER BY aum_usd DESC NULLS LAST" in sql
    assert params["manager_id"] == "123456"
```

- [ ] **Step 3: Run test to verify fail**

Run: `pytest backend/tests/domains/wealth/test_screener_keyset.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement keyset builder**

```python
# backend/app/domains/wealth/queries/screener_keyset.py
from typing import Any
from backend.app.domains.wealth.schemas.screener_fcl import (
    ScreenerFilters, ManagerCursor, FundCursor,
)

def build_managers_query(
    filters: ScreenerFilters,
    cursor: ManagerCursor | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "strategies": filters.strategies,
        "geos": filters.geographies,
        "fund_types": filters.fund_types,
        "min_aum": filters.min_aum_usd,
        "max_er": filters.max_expense_ratio_pct,
        "cursor_aum": cursor.aum if cursor else None,
        "cursor_id": cursor.crd if cursor else None,
        "limit": limit,
    }
    region_clause = ""
    if filters.region == "US":
        region_clause = "AND f.manager_id ~ '^[0-9]+$'"  # crd numbers
    elif filters.region == "EU":
        region_clause = "AND f.manager_id NOT ~ '^[0-9]+$'"

    sql = f"""
    WITH filtered AS (
        SELECT manager_id, manager_name, series_id, external_id,
               ticker, fund_type, aum_usd, strategy_label
        FROM mv_unified_funds f
        WHERE manager_id IS NOT NULL
          {region_clause}
          AND (:strategies::text[] IS NULL OR strategy_label = ANY(:strategies))
          AND (:geos::text[] IS NULL OR investment_geography = ANY(:geos))
          AND (:fund_types::text[] IS NULL OR fund_type = ANY(:fund_types))
          AND (:min_aum::numeric IS NULL OR aum_usd >= :min_aum)
          AND (:max_er::numeric IS NULL OR expense_ratio_pct <= :max_er)
    ), grouped AS (
        SELECT
            f.manager_id,
            MAX(f.manager_name) AS manager_name,
            COUNT(DISTINCT COALESCE(f.series_id, f.external_id)) AS fund_count,
            ARRAY_AGG(DISTINCT f.fund_type) FILTER (WHERE f.fund_type IS NOT NULL) AS fund_types,
            MODE() WITHIN GROUP (ORDER BY f.strategy_label) AS strategy_label_top
        FROM filtered f
        GROUP BY f.manager_id
    )
    SELECT
        g.manager_id,
        g.manager_name,
        g.fund_count,
        g.fund_types,
        g.strategy_label_top,
        sm.aum_total,
        sm.firm_name,
        sm.cik
    FROM grouped g
    LEFT JOIN sec_managers sm ON g.manager_id = sm.crd_number
    WHERE (
        :cursor_aum::numeric IS NULL
        OR (sm.aum_total, g.manager_id) < (:cursor_aum, :cursor_id)
    )
    ORDER BY sm.aum_total DESC NULLS LAST, g.manager_id ASC
    LIMIT :limit
    """
    return sql, params


def build_funds_query(
    manager_id: str,
    cursor: FundCursor | None,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {
        "manager_id": manager_id,
        "cursor_aum": cursor.aum if cursor else None,
        "cursor_ext": cursor.external_id if cursor else None,
        "limit": limit,
    }
    sql = """
    SELECT
        external_id, universe, name, ticker, isin,
        fund_type, strategy_label, aum_usd, currency, domicile,
        series_id, has_holdings, has_nav,
        expense_ratio_pct, avg_annual_return_1y, avg_annual_return_10y
    FROM mv_unified_funds
    WHERE manager_id = :manager_id
      AND (
          :cursor_aum::numeric IS NULL
          OR (aum_usd, external_id) < (:cursor_aum, :cursor_ext)
      )
    ORDER BY aum_usd DESC NULLS LAST, external_id ASC
    LIMIT :limit
    """
    return sql, params
```

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/domains/wealth/test_screener_keyset.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/schemas/screener_fcl.py backend/app/domains/wealth/queries/screener_keyset.py backend/tests/domains/wealth/test_screener_keyset.py
git commit -m "feat(wealth): screener FCL keyset query builders + schemas"
```

### Task 3.2: Routes for Col1 (managers) + Col2 (funds)

**Files:**
- Create: `backend/app/domains/wealth/routes/screener_fcl.py`
- Modify: `backend/app/domains/wealth/routes/__init__.py` (register router)
- Test: `backend/tests/domains/wealth/test_screener_fcl_routes.py`

- [ ] **Step 1: Write failing integration tests**

```python
# backend/tests/domains/wealth/test_screener_fcl_routes.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_managers_list_returns_200_with_rows(
    async_client: AsyncClient, dev_headers: dict,
):
    resp = await async_client.post(
        "/api/wealth/screener/managers",
        json={"filters": {}, "limit": 10},
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body
    assert isinstance(body["rows"], list)
    if body["rows"]:
        row = body["rows"][0]
        assert "manager_id" in row
        assert "fund_count" in row

@pytest.mark.asyncio
async def test_funds_by_manager_returns_ordered_by_aum(
    async_client: AsyncClient, dev_headers: dict, sample_manager_id: str,
):
    resp = await async_client.post(
        f"/api/wealth/screener/managers/{sample_manager_id}/funds",
        json={"limit": 20},
        headers=dev_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    aums = [r["aum_usd"] for r in rows if r["aum_usd"] is not None]
    assert aums == sorted(aums, reverse=True)

@pytest.mark.asyncio
async def test_managers_cache_hit_is_faster(
    async_client: AsyncClient, dev_headers: dict,
):
    import time
    payload = {"filters": {"strategies": ["Private Credit"]}, "limit": 10}
    t0 = time.perf_counter()
    await async_client.post("/api/wealth/screener/managers", json=payload, headers=dev_headers)
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    await async_client.post("/api/wealth/screener/managers", json=payload, headers=dev_headers)
    warm = time.perf_counter() - t1
    assert warm < cold  # cache hit must be faster
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest backend/tests/domains/wealth/test_screener_fcl_routes.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement routes**

```python
# backend/app/domains/wealth/routes/screener_fcl.py
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db_with_rls
from backend.app.core.cache.redis_client import get_redis
from backend.app.core.runtime.single_flight import SingleFlightLock
from backend.app.domains.wealth.queries.screener_keyset import (
    build_managers_query, build_funds_query,
)
from backend.app.domains.wealth.schemas.screener_fcl import (
    ScreenerFilters, ManagerCursor, FundCursor,
    ManagersListResponse, FundsListResponse, ManagerRow, FundRow,
)
from pydantic import BaseModel

router = APIRouter(prefix="/wealth/screener", tags=["wealth-screener"])

MANAGERS_TTL = 5 * 60
FUNDS_TTL = 10 * 60


class ManagersListRequest(BaseModel):
    filters: ScreenerFilters = ScreenerFilters()
    cursor: ManagerCursor | None = None
    limit: int = 50


class FundsListRequest(BaseModel):
    cursor: FundCursor | None = None
    limit: int = 50


def _cache_key(namespace: str, org_id: str, **kwargs) -> str:
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"screener:{namespace}:{org_id}:{digest}"


@router.post("/managers", response_model=ManagersListResponse)
async def list_managers(
    req: ManagersListRequest,
    db: AsyncSession = Depends(get_db_with_rls),
):
    from backend.app.core.tenancy import current_organization_id
    org_id = current_organization_id()
    redis = await get_redis()
    key = _cache_key(
        "managers", str(org_id),
        filters=req.filters.model_dump(),
        cursor=req.cursor.model_dump() if req.cursor else None,
        limit=req.limit,
    )
    cached = await redis.get(key)
    if cached:
        return ManagersListResponse.model_validate_json(cached)

    async with SingleFlightLock(redis, f"lock:{key}", ttl_seconds=10):
        cached = await redis.get(key)
        if cached:
            return ManagersListResponse.model_validate_json(cached)

        sql, params = build_managers_query(req.filters, req.cursor, req.limit + 1)
        result = await db.execute(text(sql), params)
        raw = result.mappings().all()

        has_more = len(raw) > req.limit
        rows_data = raw[: req.limit]
        rows = [ManagerRow.model_validate(dict(r)) for r in rows_data]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = ManagerCursor(aum=last.aum_total, crd=last.manager_id)

        response = ManagersListResponse(rows=rows, next_cursor=next_cursor)
        await redis.setex(key, MANAGERS_TTL, response.model_dump_json())
        return response


@router.post("/managers/{manager_id}/funds", response_model=FundsListResponse)
async def list_funds_by_manager(
    manager_id: str,
    req: FundsListRequest,
    db: AsyncSession = Depends(get_db_with_rls),
):
    from backend.app.core.tenancy import current_organization_id
    org_id = current_organization_id()
    redis = await get_redis()
    key = _cache_key(
        "funds", str(org_id),
        manager_id=manager_id,
        cursor=req.cursor.model_dump() if req.cursor else None,
        limit=req.limit,
    )
    cached = await redis.get(key)
    if cached:
        return FundsListResponse.model_validate_json(cached)

    async with SingleFlightLock(redis, f"lock:{key}", ttl_seconds=10):
        cached = await redis.get(key)
        if cached:
            return FundsListResponse.model_validate_json(cached)

        sql, params = build_funds_query(manager_id, req.cursor, req.limit + 1)
        result = await db.execute(text(sql), params)
        raw = result.mappings().all()

        if not raw:
            raise HTTPException(status_code=404, detail=f"manager {manager_id} has no funds")

        has_more = len(raw) > req.limit
        rows_data = raw[: req.limit]
        rows = [FundRow.model_validate(dict(r)) for r in rows_data]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = FundCursor(aum=last.aum_usd, external_id=last.external_id)

        # Minimal manager summary for col1 slim mode
        summary_sql = """
            SELECT g.manager_id, g.manager_name, sm.firm_name, sm.cik,
                   sm.aum_total, COUNT(f.external_id) AS fund_count
            FROM mv_unified_funds f
            LEFT JOIN sec_managers sm ON f.manager_id = sm.crd_number
            CROSS JOIN LATERAL (SELECT f.manager_id, MAX(f.manager_name) AS manager_name) g
            WHERE f.manager_id = :manager_id
            GROUP BY g.manager_id, g.manager_name, sm.firm_name, sm.cik, sm.aum_total
        """
        summary_row = (await db.execute(text(summary_sql), {"manager_id": manager_id})).mappings().first()
        manager_summary = ManagerRow.model_validate({
            **dict(summary_row),
            "fund_types": [],
            "strategy_label_top": None,
        })

        response = FundsListResponse(
            rows=rows, next_cursor=next_cursor, manager_summary=manager_summary,
        )
        await redis.setex(key, FUNDS_TTL, response.model_dump_json())
        return response
```

- [ ] **Step 4: Register router**

Add to `backend/app/domains/wealth/routes/__init__.py`:
```python
from .screener_fcl import router as screener_fcl_router
# ... in the main include_router section:
# app.include_router(screener_fcl_router)
```

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/domains/wealth/test_screener_fcl_routes.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/routes/screener_fcl.py backend/app/domains/wealth/routes/__init__.py backend/tests/domains/wealth/test_screener_fcl_routes.py
git commit -m "feat(wealth): POST /screener/managers + /managers/{id}/funds with Redis cache"
```

### Task 3.3: Routes for Col3 — Analytics + Fact Sheet + DD snapshot

**Files:**
- Modify: `backend/app/domains/wealth/routes/screener_fcl.py`
- Create: `backend/app/domains/wealth/queries/fund_analytics.py`
- Test: `backend/tests/domains/wealth/test_screener_fcl_col3.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/domains/wealth/test_screener_fcl_col3.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_analytics_default_window_is_3y(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/screener/funds/{sample_fund_id}/analytics",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "nav_series" in body
    assert "risk_metrics" in body
    assert body["window"] == "3y"

@pytest.mark.asyncio
async def test_analytics_custom_window(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/screener/funds/{sample_fund_id}/analytics?window=1y",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["window"] == "1y"

@pytest.mark.asyncio
async def test_fact_sheet_returns_aggregated_payload(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/screener/funds/{sample_fund_id}/fact-sheet",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "fund" in body
    assert "classes" in body

@pytest.mark.asyncio
async def test_private_fund_analytics_empty_state(
    async_client: AsyncClient, dev_headers: dict, sample_private_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/screener/funds/{sample_private_fund_id}/analytics",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nav_series"] == []
    assert body["disclosure"]["has_nav"] is False
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest backend/tests/domains/wealth/test_screener_fcl_col3.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fund_analytics.py` queries**

```python
# backend/app/domains/wealth/queries/fund_analytics.py
import asyncio
from datetime import date, timedelta
from typing import Any, Literal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Window = Literal["1y", "3y", "5y", "max"]

WINDOW_INTERVAL = {
    "1y": "1 year",
    "3y": "3 years",
    "5y": "5 years",
    "max": "50 years",
}


async def _fetch_nav_series(
    db: AsyncSession, instrument_id: str, window: Window,
) -> list[dict[str, Any]]:
    interval = WINDOW_INTERVAL[window]
    sql = f"""
        SELECT nav_date, nav, return_1d
        FROM nav_timeseries
        WHERE instrument_id = :id
          AND nav_date >= NOW() - INTERVAL '{interval}'
        ORDER BY nav_date ASC
    """
    result = await db.execute(text(sql), {"id": instrument_id})
    return [dict(r) for r in result.mappings().all()]


async def _fetch_risk_metrics(
    db: AsyncSession, instrument_id: str,
) -> dict[str, Any] | None:
    sql = """
        SELECT *
        FROM fund_risk_metrics
        WHERE instrument_id = :id
        ORDER BY calc_date DESC
        LIMIT 1
    """
    result = await db.execute(text(sql), {"id": instrument_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def _fetch_holdings(
    db: AsyncSession, cik: str | None, universe: str,
) -> list[dict[str, Any]]:
    if not cik:
        return []
    if universe in ("registered_us", "etf", "bdc"):
        sql = """
            SELECT issuer_name, security_type, percent_value, market_value
            FROM sec_nport_holdings
            WHERE cik = :cik
              AND report_date = (SELECT MAX(report_date) FROM sec_nport_holdings WHERE cik = :cik)
            ORDER BY percent_value DESC NULLS LAST
            LIMIT 100
        """
    else:
        return []
    result = await db.execute(text(sql), {"cik": cik})
    return [dict(r) for r in result.mappings().all()]


async def fetch_fund_analytics(
    db: AsyncSession,
    instrument_id: str,
    cik: str | None,
    universe: str,
    window: Window = "3y",
) -> dict[str, Any]:
    nav, risk, holdings = await asyncio.gather(
        _fetch_nav_series(db, instrument_id, window),
        _fetch_risk_metrics(db, instrument_id),
        _fetch_holdings(db, cik, universe),
    )
    return {
        "window": window,
        "nav_series": nav,
        "risk_metrics": risk,
        "holdings": holdings,
        "disclosure": {
            "has_nav": len(nav) > 0,
            "has_holdings": len(holdings) > 0,
        },
    }
```

- [ ] **Step 4: Add routes to `screener_fcl.py`**

```python
# append to backend/app/domains/wealth/routes/screener_fcl.py
from fastapi import Query
from backend.app.domains.wealth.queries.fund_analytics import (
    fetch_fund_analytics, Window,
)

ANALYTICS_TTL = 60 * 60
FACTSHEET_TTL = 60 * 60


async def _resolve_fund(db: AsyncSession, external_id: str) -> dict:
    sql = """
        SELECT external_id, universe, ticker, series_id, external_id AS instrument_ref
        FROM mv_unified_funds WHERE external_id = :id
    """
    row = (await db.execute(text(sql), {"id": external_id})).mappings().first()
    if not row:
        raise HTTPException(404, f"fund {external_id} not found")
    # Resolve instrument_id via ticker or series_id
    inst_sql = """
        SELECT instrument_id, attributes->>'sec_cik' AS cik
        FROM instruments_universe
        WHERE ticker = :ticker OR attributes->>'series_id' = :sid
        LIMIT 1
    """
    inst = (await db.execute(text(inst_sql), {"ticker": row["ticker"], "sid": row["series_id"]})).mappings().first()
    return {
        "external_id": external_id,
        "universe": row["universe"],
        "instrument_id": inst["instrument_id"] if inst else None,
        "cik": inst["cik"] if inst else None,
    }


@router.get("/funds/{external_id}/analytics")
async def fund_analytics(
    external_id: str,
    window: Window = Query("3y"),
    db: AsyncSession = Depends(get_db_with_rls),
):
    redis = await get_redis()
    key = f"screener:analytics:{external_id}:{window}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    fund = await _resolve_fund(db, external_id)
    if not fund["instrument_id"]:
        # Private fund or unmapped — return institutional empty state
        payload = {
            "window": window,
            "nav_series": [],
            "risk_metrics": None,
            "holdings": [],
            "disclosure": {"has_nav": False, "has_holdings": False},
            "fund_meta": fund,
        }
    else:
        payload = await fetch_fund_analytics(
            db, fund["instrument_id"], fund["cik"], fund["universe"], window,
        )
        payload["fund_meta"] = fund

    await redis.setex(key, ANALYTICS_TTL, json.dumps(payload, default=str))
    return payload


@router.get("/funds/{external_id}/fact-sheet")
async def fund_fact_sheet(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
):
    redis = await get_redis()
    key = f"screener:factsheet:{external_id}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    sql = """
        SELECT
            to_jsonb(f) AS fund,
            (SELECT to_jsonb(rm) FROM fund_risk_metrics rm
               JOIN instruments_universe i ON i.instrument_id = rm.instrument_id
               WHERE i.ticker = f.ticker
               ORDER BY rm.calc_date DESC LIMIT 1) AS risk,
            (SELECT to_jsonb(ps) FROM sec_fund_prospectus_stats ps
               WHERE ps.series_id = f.series_id LIMIT 1) AS prospectus,
            (SELECT jsonb_agg(to_jsonb(fc)) FROM sec_fund_classes fc
               WHERE fc.series_id = f.series_id) AS classes
        FROM mv_unified_funds f
        WHERE f.external_id = :id
    """
    row = (await db.execute(text(sql), {"id": external_id})).mappings().first()
    if not row:
        raise HTTPException(404, f"fund {external_id} not found")

    payload = dict(row)
    await redis.setex(key, FACTSHEET_TTL, json.dumps(payload, default=str))
    return payload


@router.get("/funds/{external_id}/dd-report/snapshot")
async def dd_report_snapshot(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
):
    sql = """
        SELECT chapter_tag, chapter_order, content_md, critic_status, generated_at
        FROM dd_chapters
        WHERE dd_report_id = (
            SELECT id FROM dd_reports
            WHERE fund_external_id = :id
              AND organization_id = (SELECT current_setting('app.current_organization_id')::uuid)
            ORDER BY created_at DESC LIMIT 1
        )
        ORDER BY chapter_order ASC
    """
    rows = (await db.execute(text(sql), {"id": external_id})).mappings().all()
    return {"chapters": [dict(r) for r in rows]}
```

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/domains/wealth/test_screener_fcl_col3.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/queries/fund_analytics.py backend/app/domains/wealth/routes/screener_fcl.py backend/tests/domains/wealth/test_screener_fcl_col3.py
git commit -m "feat(wealth): screener col3 routes — analytics (3y default), fact sheet, DD snapshot"
```

### Task 3.4: DD streaming SSE endpoint

**Files:**
- Modify: `backend/app/domains/wealth/routes/screener_fcl.py`
- Test: `backend/tests/domains/wealth/test_dd_stream.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/domains/wealth/test_dd_stream.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_dd_stream_returns_event_stream_content_type(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    async with async_client.stream(
        "GET",
        f"/api/wealth/screener/funds/{sample_fund_id}/dd-report/stream",
        headers=dev_headers,
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test**

Run: `pytest backend/tests/domains/wealth/test_dd_stream.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement SSE bridge**

Append to `screener_fcl.py`:
```python
from sse_starlette.sse import EventSourceResponse
from backend.app.core.jobs.redis_bridge import subscribe_channel

@router.get("/funds/{external_id}/dd-report/stream")
async def dd_report_stream(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
):
    # First: resolve active dd_report_id
    from backend.app.core.tenancy import current_organization_id
    org_id = current_organization_id()
    sql = """
        SELECT id FROM dd_reports
        WHERE fund_external_id = :id
          AND organization_id = :org
        ORDER BY created_at DESC LIMIT 1
    """
    row = (await db.execute(text(sql), {"id": external_id, "org": str(org_id)})).first()
    if not row:
        raise HTTPException(404, "no DD report for fund")
    report_id = row[0]

    async def event_generator():
        # Emit initial snapshot
        snap_sql = """
            SELECT chapter_tag, chapter_order, content_md, critic_status, generated_at
            FROM dd_chapters WHERE dd_report_id = :rid ORDER BY chapter_order
        """
        rows = (await db.execute(text(snap_sql), {"rid": report_id})).mappings().all()
        yield {
            "event": "snapshot",
            "data": json.dumps({"chapters": [dict(r) for r in rows]}, default=str),
        }

        # Subscribe to Redis channel for incremental updates
        channel = f"dd:report:{report_id}"
        async for message in subscribe_channel(channel):
            yield {"event": "chapter", "data": message}

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: Run test**

Run: `pytest backend/tests/domains/wealth/test_dd_stream.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domains/wealth/routes/screener_fcl.py backend/tests/domains/wealth/test_dd_stream.py
git commit -m "feat(wealth): SSE DD report stream (Redis pub/sub bridge)"
```

### Task 3.5: Run full backend check gate

- [ ] **Step 1: Run make check**

```bash
make check
```
Expected: lint + architecture + typecheck + test all green.

- [ ] **Step 2: Fix any issues inline, recommit**

---

## Phase 4 — Screener frontend FCL page

### Task 4.1: Screener state helpers + URL sync

**Files:**
- Create: `frontends/wealth/src/lib/screener/fcl-state.svelte.ts`
- Create: `frontends/wealth/src/lib/screener/api.ts`

- [ ] **Step 1: Implement URL-derived FCL state helpers**

```ts
// frontends/wealth/src/lib/screener/fcl-state.svelte.ts
import { page } from '$app/state';
import { goto } from '$app/navigation';
import type { FCLState } from '@netz/ui';

export function useScreenerUrlState() {
  const managerId = $derived(page.url.searchParams.get('manager'));
  const fundId = $derived(page.url.searchParams.get('fund'));
  const view = $derived(
    (page.url.searchParams.get('view') ?? 'analytics') as 'dd' | 'analytics' | 'factsheet',
  );
  const state = $derived<FCLState>(
    fundId ? 'expand-3' : managerId ? 'expand-2' : 'expand-1',
  );

  async function patch(updates: Record<string, string | null>) {
    const url = new URL(page.url);
    for (const [k, v] of Object.entries(updates)) {
      if (v === null) url.searchParams.delete(k);
      else url.searchParams.set(k, v);
    }
    await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }

  return {
    get managerId() { return managerId; },
    get fundId() { return fundId; },
    get view() { return view; },
    get state() { return state; },
    selectManager: (id: string) => patch({ manager: id, fund: null, view: null }),
    selectFund: (id: string, v: 'dd' | 'analytics' | 'factsheet' = 'analytics') =>
      patch({ fund: id, view: v }),
    changeView: (v: 'dd' | 'analytics' | 'factsheet') => patch({ view: v }),
    closeCol3: () => patch({ fund: null, view: null }),
    clearManager: () => patch({ manager: null, fund: null, view: null }),
  };
}
```

- [ ] **Step 2: Implement API client**

```ts
// frontends/wealth/src/lib/screener/api.ts
import { getAuthHeaders } from '$lib/auth';

const BASE = '/api/wealth/screener';

export async function fetchManagers(
  body: object,
  signal: AbortSignal,
) {
  const res = await fetch(`${BASE}/managers`, {
    method: 'POST',
    headers: { ...(await getAuthHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(`managers fetch: ${res.status}`);
  return res.json();
}

export async function fetchFundsByManager(
  managerId: string,
  body: object,
  signal: AbortSignal,
) {
  const res = await fetch(`${BASE}/managers/${encodeURIComponent(managerId)}/funds`, {
    method: 'POST',
    headers: { ...(await getAuthHeaders()), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(`funds fetch: ${res.status}`);
  return res.json();
}

export async function fetchFundAnalytics(
  fundId: string,
  window: '1y' | '3y' | '5y' | 'max',
  signal: AbortSignal,
) {
  const res = await fetch(`${BASE}/funds/${encodeURIComponent(fundId)}/analytics?window=${window}`, {
    headers: await getAuthHeaders(),
    signal,
  });
  if (!res.ok) throw new Error(`analytics fetch: ${res.status}`);
  return res.json();
}

export async function fetchFundFactSheet(
  fundId: string,
  signal: AbortSignal,
) {
  const res = await fetch(`${BASE}/funds/${encodeURIComponent(fundId)}/fact-sheet`, {
    headers: await getAuthHeaders(),
    signal,
  });
  if (!res.ok) throw new Error(`factsheet fetch: ${res.status}`);
  return res.json();
}

export async function openDDReportStream(
  fundId: string,
  signal: AbortSignal,
  onEvent: (evt: { event: string; data: unknown }) => void,
) {
  const res = await fetch(`${BASE}/funds/${encodeURIComponent(fundId)}/dd-report/stream`, {
    headers: { ...(await getAuthHeaders()), Accept: 'text/event-stream' },
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`dd stream: ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) return;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop() ?? '';
    for (const frame of frames) {
      const eventLine = frame.split('\n').find((l) => l.startsWith('event: '));
      const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!dataLine) continue;
      try {
        onEvent({
          event: eventLine?.slice(7) ?? 'message',
          data: JSON.parse(dataLine.slice(6)),
        });
      } catch { /* skip malformed frame */ }
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontends/wealth/src/lib/screener/
git commit -m "feat(screener): URL state + API client helpers"
```

### Task 4.2: Managers table column defs + row component

**Files:**
- Create: `frontends/wealth/src/lib/components/screener/ScreenerManagersTable.svelte`
- Create: `frontends/wealth/src/lib/components/screener/columns.ts`

- [ ] **Step 1: Define manager columns**

```ts
// frontends/wealth/src/lib/components/screener/columns.ts
import type { ColumnDef } from '@netz/ui';
import { formatCurrency, formatNumber } from '@netz/ui';

export interface ManagerRow {
  manager_id: string;
  manager_name: string;
  firm_name: string | null;
  cik: string | null;
  aum_total: number | null;
  fund_count: number;
  fund_types: string[];
  strategy_label_top: string | null;
}

export function managerColumns(compact: boolean): ColumnDef<ManagerRow>[] {
  const cols: ColumnDef<ManagerRow>[] = [
    {
      id: 'name', header: 'Manager', width: 'minmax(220px, 2fr)',
      accessor: (r) => r.firm_name ?? r.manager_name,
    },
    {
      id: 'aum', header: 'AUM', numeric: true, width: '120px',
      accessor: (r) => r.aum_total,
      format: (v) => (v == null ? '—' : formatCurrency(v as number, { compact: true, symbol: false })),
    },
  ];
  if (!compact) {
    cols.push(
      {
        id: 'funds', header: 'Funds', numeric: true, width: '80px',
        accessor: (r) => r.fund_count,
        format: (v) => formatNumber(v as number, 0),
      },
      {
        id: 'strategy', header: 'Top Strategy', width: 'minmax(140px, 1fr)',
        hideBelow: 1200,
        accessor: (r) => r.strategy_label_top ?? '—',
      },
      {
        id: 'crd', header: 'CRD', width: '90px', hideBelow: 900,
        accessor: (r) => r.manager_id,
      },
    );
  }
  return cols;
}

export interface FundRowView {
  external_id: string;
  universe: string;
  name: string;
  ticker: string | null;
  aum_usd: number | null;
  fund_type: string | null;
  strategy_label: string | null;
  expense_ratio_pct: number | null;
  avg_annual_return_1y: number | null;
  avg_annual_return_10y: number | null;
  has_nav: boolean;
  has_holdings: boolean;
}
```

- [ ] **Step 2: Implement `ScreenerManagersTable`**

```svelte
<!-- frontends/wealth/src/lib/components/screener/ScreenerManagersTable.svelte -->
<script lang="ts">
  import { EnterpriseTable } from '@netz/ui';
  import { managerColumns, type ManagerRow } from './columns';

  interface Props {
    rows: ManagerRow[];
    compact: boolean;
    selectedId: string | null;
    onSelect: (id: string) => void;
  }

  let { rows, compact, selectedId, onSelect }: Props = $props();
  const columns = $derived(managerColumns(compact));
</script>

<EnterpriseTable
  {rows}
  {columns}
  rowKey={(r) => r.manager_id}
  freezeFirstColumn={!compact}
  onRowClick={(r) => onSelect(r.manager_id)}
  rowAttrs={(r) => ({
    'data-selected': r.manager_id === selectedId ? 'true' : undefined,
  })}
/>

<style>
  :global([data-selected='true'] td) {
    background: var(--ii-bg-selected, rgba(80, 140, 255, 0.12)) !important;
  }
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontends/wealth/src/lib/components/screener/
git commit -m "feat(screener): managers table with compact/full column modes"
```

### Task 4.3: Funds table with inline action buttons

**Files:**
- Create: `frontends/wealth/src/lib/components/screener/ScreenerFundsTable.svelte`

- [ ] **Step 1: Implement funds table with 3 action buttons per row**

```svelte
<!-- frontends/wealth/src/lib/components/screener/ScreenerFundsTable.svelte -->
<script lang="ts">
  import { EnterpriseTable, formatCurrency, formatPercent } from '@netz/ui';
  import type { ColumnDef } from '@netz/ui';
  import type { FundRowView } from './columns';

  interface Props {
    rows: FundRowView[];
    selectedFundId: string | null;
    activeView: 'dd' | 'analytics' | 'factsheet' | null;
    onSelect: (id: string, view: 'dd' | 'analytics' | 'factsheet') => void;
  }

  let { rows, selectedFundId, activeView, onSelect }: Props = $props();

  const columns: ColumnDef<FundRowView>[] = [
    { id: 'ticker', header: 'Ticker', width: '90px', accessor: (r) => r.ticker ?? '—' },
    { id: 'name', header: 'Name', width: 'minmax(220px, 2fr)', accessor: (r) => r.name },
    { id: 'type', header: 'Type', width: '110px', hideBelow: 1200, accessor: (r) => r.fund_type ?? '—' },
    { id: 'strategy', header: 'Strategy', width: 'minmax(140px, 1fr)', hideBelow: 1400, accessor: (r) => r.strategy_label ?? '—' },
    {
      id: 'aum', header: 'AUM', numeric: true, width: '110px',
      accessor: (r) => r.aum_usd,
      format: (v) => (v == null ? '—' : formatCurrency(v as number, { compact: true, symbol: false })),
    },
    {
      id: 'er', header: 'ER', numeric: true, width: '70px', hideBelow: 1200,
      accessor: (r) => r.expense_ratio_pct,
      format: (v) => (v == null ? '—' : formatPercent((v as number) / 100, 2)),
    },
    {
      id: 'ret1y', header: '1Y', numeric: true, width: '80px',
      accessor: (r) => r.avg_annual_return_1y,
      format: (v) => (v == null ? '—' : formatPercent((v as number) / 100, 1)),
    },
    {
      id: 'ret10y', header: '10Y', numeric: true, width: '80px', hideBelow: 1400,
      accessor: (r) => r.avg_annual_return_10y,
      format: (v) => (v == null ? '—' : formatPercent((v as number) / 100, 1)),
    },
    { id: 'actions', header: '', width: '140px', align: 'right', accessor: (r) => r.external_id },
  ];
</script>

{#snippet cellSnippet(row: FundRowView, col: ColumnDef<FundRowView>)}
  {#if col.id === 'actions'}
    <div class="action-row">
      <button
        class="act-btn"
        class:active={row.external_id === selectedFundId && activeView === 'dd'}
        onclick={(e) => { e.stopPropagation(); onSelect(row.external_id, 'dd'); }}
        title="DD Review"
      >DD</button>
      <button
        class="act-btn"
        class:active={row.external_id === selectedFundId && activeView === 'analytics'}
        onclick={(e) => { e.stopPropagation(); onSelect(row.external_id, 'analytics'); }}
        title="Analytics"
      >Ana</button>
      <button
        class="act-btn"
        class:active={row.external_id === selectedFundId && activeView === 'factsheet'}
        onclick={(e) => { e.stopPropagation(); onSelect(row.external_id, 'factsheet'); }}
        title="Fact Sheet"
      >FS</button>
    </div>
  {:else if col.format}
    {col.format(col.accessor(row), row)}
  {:else}
    {col.accessor(row) ?? ''}
  {/if}
{/snippet}

<EnterpriseTable
  {rows}
  {columns}
  rowKey={(r) => r.external_id}
  cell={cellSnippet}
  rowAttrs={(r) => ({ 'data-selected': r.external_id === selectedFundId ? 'true' : undefined })}
/>

<style>
  .action-row {
    display: inline-flex;
    gap: 4px;
    justify-content: flex-end;
  }
  .act-btn {
    font-family: 'Urbanist', system-ui, sans-serif;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 4px;
    background: transparent;
    border: 1px solid var(--ii-border-subtle, rgba(64,66,73,0.4));
    color: var(--ii-text-muted, #85a0bd);
    cursor: pointer;
    transition: all 150ms;
  }
  .act-btn:hover {
    border-color: var(--ii-accent, #0066ff);
    color: var(--ii-accent, #0066ff);
  }
  .act-btn.active {
    background: var(--ii-accent, #0066ff);
    color: white;
    border-color: var(--ii-accent, #0066ff);
  }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontends/wealth/src/lib/components/screener/ScreenerFundsTable.svelte
git commit -m "feat(screener): funds table with inline DD/Analytics/FactSheet actions"
```

### Task 4.4: Col3 panels — placeholders for Fact Sheet + Analytics + DD

**Files:**
- Create: `frontends/wealth/src/lib/components/screener/col3/FactSheetPanel.svelte`
- Create: `frontends/wealth/src/lib/components/screener/col3/AnalyticsPanel.svelte`
- Create: `frontends/wealth/src/lib/components/screener/col3/DDReviewPanel.svelte`

- [ ] **Step 1: Fact Sheet panel**

```svelte
<!-- frontends/wealth/src/lib/components/screener/col3/FactSheetPanel.svelte -->
<script lang="ts">
  import { formatCurrency, formatPercent } from '@netz/ui';
  import { fetchFundFactSheet } from '$lib/screener/api';

  interface Props { fundId: string; }
  let { fundId }: Props = $props();

  let data = $state<any>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const id = fundId;
    if (!id) return;
    const ctrl = new AbortController();
    data = null; error = null;
    fetchFundFactSheet(id, ctrl.signal)
      .then((d) => { data = d; })
      .catch((e) => { if (e.name !== 'AbortError') error = e.message; });
    return () => ctrl.abort();
  });
</script>

<div class="fs-root">
  {#if error}
    <div class="fs-error">Failed to load: {error}</div>
  {:else if !data}
    <div class="fs-loading">Loading…</div>
  {:else}
    <header class="fs-header">
      <h2>{data.fund?.name}</h2>
      <div class="fs-meta">
        {data.fund?.ticker ?? '—'} · {data.fund?.domicile ?? '—'} · {data.fund?.currency ?? '—'}
      </div>
    </header>
    <section class="fs-metrics">
      <div class="metric">
        <span class="label">AUM</span>
        <strong>{data.fund?.aum_usd ? formatCurrency(data.fund.aum_usd, { compact: true }) : '—'}</strong>
      </div>
      <div class="metric">
        <span class="label">Expense Ratio</span>
        <strong>{data.fund?.expense_ratio_pct != null ? formatPercent(data.fund.expense_ratio_pct / 100, 2) : '—'}</strong>
      </div>
      <div class="metric">
        <span class="label">Strategy</span>
        <strong>{data.fund?.strategy_label ?? '—'}</strong>
      </div>
    </section>
    {#if data.classes?.length}
      <section class="fs-classes">
        <h3>Share Classes</h3>
        <ul>
          {#each data.classes as cls}
            <li>{cls.ticker ?? cls.class_id} — ER {cls.expense_ratio_pct != null ? formatPercent(cls.expense_ratio_pct / 100, 2) : '—'}</li>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</div>

<style>
  .fs-root { padding: 24px; font-family: 'Urbanist', system-ui, sans-serif; }
  .fs-header h2 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
  .fs-meta { color: var(--ii-text-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
  .fs-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 24px 0; }
  .metric { display: flex; flex-direction: column; gap: 4px; }
  .metric .label { font-size: 11px; text-transform: uppercase; color: var(--ii-text-muted); }
  .metric strong { font-size: 18px; font-variant-numeric: tabular-nums; }
  .fs-classes h3 { font-size: 13px; font-weight: 600; margin: 0 0 8px; }
  .fs-classes ul { list-style: none; padding: 0; margin: 0; font-size: 12px; }
  .fs-classes li { padding: 6px 0; border-bottom: 1px solid var(--ii-border-hairline); font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 2: Analytics panel (minimal — charts come in Phase 5)**

```svelte
<!-- frontends/wealth/src/lib/components/screener/col3/AnalyticsPanel.svelte -->
<script lang="ts">
  import { fetchFundAnalytics } from '$lib/screener/api';

  interface Props { fundId: string; }
  let { fundId }: Props = $props();

  let window = $state<'1y' | '3y' | '5y' | 'max'>('3y');
  let data = $state<any>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const id = fundId;
    const w = window;
    if (!id) return;
    const ctrl = new AbortController();
    data = null; error = null;
    fetchFundAnalytics(id, w, ctrl.signal)
      .then((d) => { data = d; })
      .catch((e) => { if (e.name !== 'AbortError') error = e.message; });
    return () => ctrl.abort();
  });
</script>

<div class="an-root">
  <header class="an-header">
    <h2>Analytics</h2>
    <nav class="range-picker">
      {#each ['1y', '3y', '5y', 'max'] as w}
        <button class:active={window === w} onclick={() => (window = w as any)}>{w.toUpperCase()}</button>
      {/each}
    </nav>
  </header>
  {#if error}
    <div class="an-error">Failed to load: {error}</div>
  {:else if !data}
    <div class="an-loading">Loading…</div>
  {:else if !data.disclosure?.has_nav}
    <div class="an-empty">
      <strong>No public pricing data</strong>
      <p>This fund reports only via Form ADV filings. Public NAV series is not available.</p>
    </div>
  {:else}
    <div class="an-placeholder">
      <!-- Phase 5 will render NAV + drawdown + peer scatter + factor exposure here -->
      <p>NAV series loaded: {data.nav_series?.length} points. Charts land in Phase 5.</p>
    </div>
  {/if}
</div>

<style>
  .an-root { padding: 24px; font-family: 'Urbanist', system-ui, sans-serif; height: 100%; }
  .an-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .an-header h2 { font-size: 18px; font-weight: 600; margin: 0; }
  .range-picker { display: inline-flex; gap: 4px; }
  .range-picker button {
    font-family: inherit; font-size: 11px; font-weight: 600;
    padding: 6px 12px; border-radius: 999px;
    background: transparent; border: 1px solid var(--ii-border-subtle);
    color: var(--ii-text-muted); cursor: pointer;
  }
  .range-picker button.active {
    background: var(--ii-accent); color: white; border-color: var(--ii-accent);
  }
  .an-empty { padding: 40px; text-align: center; color: var(--ii-text-muted); }
  .an-empty strong { display: block; font-size: 14px; color: var(--ii-text-primary); margin-bottom: 8px; }
</style>
```

- [ ] **Step 3: DD Review panel with SSE**

```svelte
<!-- frontends/wealth/src/lib/components/screener/col3/DDReviewPanel.svelte -->
<script lang="ts">
  import { openDDReportStream } from '$lib/screener/api';

  interface Props { fundId: string; }
  let { fundId }: Props = $props();

  interface Chapter { chapter_tag: string; chapter_order: number; content_md: string; critic_status: string | null; }

  let chapters = $state<Chapter[]>([]);
  let status = $state<'idle' | 'streaming' | 'done' | 'error'>('idle');
  let error = $state<string | null>(null);

  $effect(() => {
    const id = fundId;
    if (!id) return;
    const ctrl = new AbortController();
    chapters = []; error = null; status = 'streaming';
    (async () => {
      try {
        await openDDReportStream(id, ctrl.signal, (evt) => {
          if (evt.event === 'snapshot') {
            chapters = (evt.data as { chapters: Chapter[] }).chapters;
          } else if (evt.event === 'chapter') {
            const ch = evt.data as Chapter;
            const existing = chapters.findIndex((c) => c.chapter_order === ch.chapter_order);
            if (existing >= 0) {
              chapters = chapters.map((c, i) => (i === existing ? ch : c));
            } else {
              chapters = [...chapters, ch].sort((a, b) => a.chapter_order - b.chapter_order);
            }
          }
        });
        status = 'done';
      } catch (e) {
        if ((e as Error).name === 'AbortError') return;
        error = (e as Error).message;
        status = 'error';
      }
    })();
    return () => ctrl.abort();
  });
</script>

<div class="dd-root">
  <header class="dd-header">
    <h2>DD Review</h2>
    <span class="status" data-state={status}>{status}</span>
  </header>
  {#if error}
    <div class="dd-error">Failed: {error}</div>
  {:else if chapters.length === 0 && status === 'streaming'}
    <div class="dd-loading">Waiting for first chapter…</div>
  {:else}
    <div class="dd-chapters">
      {#each chapters as ch (ch.chapter_order)}
        <article class="dd-chapter">
          <h3>{ch.chapter_tag}</h3>
          <div class="dd-content">{ch.content_md}</div>
          {#if ch.critic_status}<span class="dd-critic">Critic: {ch.critic_status}</span>{/if}
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dd-root { padding: 24px; font-family: 'Urbanist', system-ui, sans-serif; height: 100%; overflow: auto; }
  .dd-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .dd-header h2 { font-size: 18px; font-weight: 600; margin: 0; }
  .status { font-size: 11px; text-transform: uppercase; color: var(--ii-text-muted); }
  .status[data-state='streaming'] { color: var(--ii-accent); }
  .status[data-state='done'] { color: var(--ii-success); }
  .status[data-state='error'] { color: var(--ii-error); }
  .dd-chapter { padding: 16px 0; border-bottom: 1px solid var(--ii-border-hairline); }
  .dd-chapter h3 { font-size: 13px; font-weight: 600; margin: 0 0 8px; }
  .dd-content { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
  .dd-critic { font-size: 11px; color: var(--ii-text-muted); margin-top: 8px; display: block; }
</style>
```

- [ ] **Step 4: Commit**

```bash
git add frontends/wealth/src/lib/components/screener/col3/
git commit -m "feat(screener): col3 panels — factsheet, analytics scaffold, DD SSE"
```

### Task 4.5: Screener page orchestrator

**Files:**
- Create: `frontends/wealth/src/routes/(app)/screener/+page.server.ts`
- Modify: `frontends/wealth/src/routes/(app)/screener/+page.svelte` (replace Phase 2 stub)

- [ ] **Step 1: Server load for initial managers**

```ts
// frontends/wealth/src/routes/(app)/screener/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, url }) => {
  const res = await fetch('/api/wealth/screener/managers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filters: {}, limit: 50 }),
  });
  if (!res.ok) {
    return { status: 'error' as const, error: `managers load: ${res.status}`, initialManagers: [] };
  }
  const body = await res.json();
  return {
    status: 'ok' as const,
    initialManagers: body.rows,
    nextCursor: body.next_cursor,
    preselectedManagerId: url.searchParams.get('manager'),
    preselectedFundId: url.searchParams.get('fund'),
  };
};
```

- [ ] **Step 2: Page component**

```svelte
<!-- frontends/wealth/src/routes/(app)/screener/+page.svelte -->
<script lang="ts">
  import { FlexibleColumnLayout, type FCLRatios } from '@netz/ui';
  import { useScreenerUrlState } from '$lib/screener/fcl-state.svelte';
  import { fetchFundsByManager } from '$lib/screener/api';
  import ScreenerManagersTable from '$lib/components/screener/ScreenerManagersTable.svelte';
  import ScreenerFundsTable from '$lib/components/screener/ScreenerFundsTable.svelte';
  import FactSheetPanel from '$lib/components/screener/col3/FactSheetPanel.svelte';
  import AnalyticsPanel from '$lib/components/screener/col3/AnalyticsPanel.svelte';
  import DDReviewPanel from '$lib/components/screener/col3/DDReviewPanel.svelte';
  import type { ManagerRow, FundRowView } from '$lib/components/screener/columns';

  let { data } = $props();

  const fcl = useScreenerUrlState();

  let managers = $state<ManagerRow[]>(data.initialManagers ?? []);
  let funds = $state<FundRowView[]>([]);
  let fundsError = $state<string | null>(null);

  const SCREENER_RATIOS: FCLRatios = {
    'expand-1': [1, 0, 0],
    'expand-2': [0.32, 0.68, 0],
    'expand-3': [0.22, 0.42, 0.36],
  };

  // Lazy-load funds when manager changes
  $effect(() => {
    const mid = fcl.managerId;
    if (!mid) { funds = []; return; }
    const ctrl = new AbortController();
    fundsError = null;
    fetchFundsByManager(mid, { limit: 100 }, ctrl.signal)
      .then((body) => { funds = body.rows; })
      .catch((e) => { if (e.name !== 'AbortError') fundsError = e.message; });
    return () => ctrl.abort();
  });
</script>

<svelte:head><title>Screener — Netz Wealth</title></svelte:head>

<FlexibleColumnLayout
  state={fcl.state}
  ratios={SCREENER_RATIOS}
  column1Label="Managers"
  column2Label="Funds"
  column3Label="Fund Detail"
>
  {#snippet column1()}
    <ScreenerManagersTable
      rows={managers}
      compact={fcl.state !== 'expand-1'}
      selectedId={fcl.managerId}
      onSelect={(id) => fcl.selectManager(id)}
    />
  {/snippet}
  {#snippet column2()}
    {#if fundsError}
      <div class="col-error">Failed to load funds: {fundsError}</div>
    {:else if funds.length === 0 && fcl.managerId}
      <div class="col-loading">Loading funds…</div>
    {:else}
      <ScreenerFundsTable
        rows={funds}
        selectedFundId={fcl.fundId}
        activeView={fcl.fundId ? fcl.view : null}
        onSelect={(id, view) => fcl.selectFund(id, view)}
      />
    {/if}
  {/snippet}
  {#snippet column3()}
    {#if fcl.fundId}
      {#if fcl.view === 'dd'}
        <DDReviewPanel fundId={fcl.fundId} />
      {:else if fcl.view === 'analytics'}
        <AnalyticsPanel fundId={fcl.fundId} />
      {:else}
        <FactSheetPanel fundId={fcl.fundId} />
      {/if}
    {/if}
  {/snippet}
</FlexibleColumnLayout>

<style>
  .col-error, .col-loading {
    padding: 24px; text-align: center;
    color: var(--ii-text-muted); font-family: 'Urbanist', system-ui, sans-serif;
  }
  .col-error { color: var(--ii-error); }
</style>
```

- [ ] **Step 3: Run svelte-autofixer + check**

```bash
cd frontends/wealth && pnpm check
npx @sveltejs/mcp svelte-autofixer src/routes/\(app\)/screener/+page.svelte
```
Expected: zero errors.

- [ ] **Step 4: Visual validation in browser**

Run `make dev-wealth` then open `/screener`. Verify:
1. Landing state: managers table full-width
2. Click manager → Col1 recua, Col2 abre com fundos em AUM DESC
3. Click DD/Ana/FS button em qualquer fundo → Col3 abre com o conteúdo correto
4. Click outro botão do mesmo fundo → Col3 troca de view sem fechar
5. Click outro fundo → Col3 atualiza
6. Browser back button → estado anterior restaura
7. Refresh com `?manager=X&fund=Y&view=dd` na URL → restaura estado direto
8. Resize para < 1100px → Col3 vira overlay
9. Resize para < 1024px → stack vertical (fallback do container query)

- [ ] **Step 5: Commit**

```bash
git add frontends/wealth/src/routes/\(app\)/screener/
git commit -m "feat(screener): FCL 3-column page orchestrator with URL state sync"
```

---

## Phase 5 — ECharts institutional charts

Substitui o placeholder do AnalyticsPanel com charts reais: NAV hero + drawdown overlay, rolling risk, holdings composition, peer scatter, factor exposure.

### Task 5.1: NAV hero chart (NAV + benchmark + regime + drawdown)

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/screener/NavHeroChart.svelte`

- [ ] **Step 1: Implement NAV hero with shared dataset**

```svelte
<!-- frontends/wealth/src/lib/components/charts/screener/NavHeroChart.svelte -->
<script lang="ts">
  import { Chart } from 'svelte-echarts';
  import { init } from 'echarts';
  import { chartTokens } from '../chart-tokens';
  import { navTooltipFormatter } from '../tooltips';

  interface NavPoint { nav_date: string; nav: number; return_1d: number | null; }
  interface Props { series: NavPoint[]; benchmarkSeries?: NavPoint[]; }

  let { series, benchmarkSeries = [] }: Props = $props();

  const tokens = $derived.by(() => chartTokens());

  // Compute cumulative returns from return_1d, drawdown from peak
  const dataset = $derived.by(() => {
    let cumLog = 0; let peak = 0;
    return series.map((p) => {
      cumLog += p.return_1d ?? 0;
      const cumRet = Math.exp(cumLog) - 1;
      peak = Math.max(peak, cumRet);
      const dd = cumRet - peak;
      return [p.nav_date, cumRet, dd];
    });
  });

  const option = $derived({
    textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: tokens.tooltipBg,
      borderColor: tokens.tooltipBorder,
      borderWidth: 1,
      padding: 10,
      formatter: navTooltipFormatter(tokens),
    },
    grid: [
      { left: 56, right: 24, top: 24, height: '62%', containLabel: false },
      { left: 56, right: 24, top: '72%', height: '22%', containLabel: false },
    ],
    xAxis: [
      { type: 'time', gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: tokens.grid } } },
      { type: 'time', gridIndex: 1, axisLabel: { color: tokens.axisLabel }, axisLine: { lineStyle: { color: tokens.grid } } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, axisLabel: { color: tokens.axisLabel, formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: tokens.grid, type: 'dashed' } } },
      { type: 'value', gridIndex: 1, axisLabel: { color: tokens.axisLabel, formatter: (v: number) => `${(v * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: tokens.grid, type: 'dashed' } }, max: 0 },
    ],
    dataset: { source: dataset },
    series: [
      {
        name: 'Cumulative Return',
        type: 'line',
        xAxisIndex: 0, yAxisIndex: 0,
        encode: { x: 0, y: 1 },
        showSymbol: false,
        lineStyle: { color: tokens.primary, width: 2 },
        sampling: 'lttb',
        progressive: 500,
        progressiveThreshold: 3000,
      },
      {
        name: 'Drawdown',
        type: 'line',
        xAxisIndex: 1, yAxisIndex: 1,
        encode: { x: 0, y: 2 },
        showSymbol: false,
        areaStyle: { color: tokens.negative, opacity: 0.3 },
        lineStyle: { color: tokens.negative, width: 1 },
        sampling: 'lttb',
      },
    ],
    animationDuration: 300,
    animationEasing: 'linear',
  });
</script>

<div class="nav-hero">
  <Chart {init} {option} notMerge={true} />
</div>

<style>
  .nav-hero { width: 100%; height: 380px; }
</style>
```

- [ ] **Step 2: Wire into `AnalyticsPanel.svelte`**

Replace the placeholder block in `AnalyticsPanel.svelte`:
```svelte
<script lang="ts">
  // ... existing imports
  import NavHeroChart from '$lib/components/charts/screener/NavHeroChart.svelte';
</script>

<!-- replace <div class="an-placeholder">...</div> with: -->
<NavHeroChart series={data.nav_series} />
```

- [ ] **Step 3: Visual validation**

Run `make dev-wealth`, open `/screener?manager=X&fund=Y&view=analytics`. Verify:
- NAV cumulative line in blue neon
- Drawdown area below in red, anchored at max=0
- Tooltip shows date + cumulative return + drawdown on hover
- Range picker changes window (window change triggers `$effect` reload)
- No console errors

- [ ] **Step 4: Commit**

```bash
git add frontends/wealth/src/lib/components/charts/screener/NavHeroChart.svelte frontends/wealth/src/lib/components/screener/col3/AnalyticsPanel.svelte
git commit -m "feat(screener): NAV hero chart with drawdown overlay (shared dataset)"
```

### Task 5.2: Peer scatter + factor exposure (lower priority charts)

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/screener/PeerScatterChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/screener/FactorExposureChart.svelte`

- [ ] **Step 1: Peer scatter**

```svelte
<!-- frontends/wealth/src/lib/components/charts/screener/PeerScatterChart.svelte -->
<script lang="ts">
  import { Chart } from 'svelte-echarts';
  import { init } from 'echarts';
  import { chartTokens } from '../chart-tokens';
  import { formatPercent } from '@netz/ui';

  interface Peer { id: string; name: string; volatility: number; annualized_return: number; is_subject?: boolean; }
  interface Props { peers: Peer[]; }
  let { peers }: Props = $props();

  const tokens = $derived.by(() => chartTokens());
  const option = $derived({
    textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
    grid: { left: 56, right: 24, top: 24, bottom: 48, containLabel: false },
    tooltip: {
      trigger: 'item',
      backgroundColor: tokens.tooltipBg,
      borderColor: tokens.tooltipBorder,
      borderWidth: 1,
      formatter: (p: any) => {
        const [x, y, name] = p.value;
        return `<strong>${name}</strong><br/>Vol: ${formatPercent(x, 2)}<br/>Ret: ${formatPercent(y, 2)}`;
      },
    },
    xAxis: {
      type: 'value', name: 'Volatility (1Y)', nameGap: 24, nameLocation: 'middle',
      axisLabel: { color: tokens.axisLabel, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: tokens.grid, type: 'dashed' } },
    },
    yAxis: {
      type: 'value', name: 'Annualized Return',
      axisLabel: { color: tokens.axisLabel, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: tokens.grid, type: 'dashed' } },
    },
    series: [{
      type: 'scatter',
      symbolSize: (val: any, params: any) => (peers[params.dataIndex]?.is_subject ? 18 : 10),
      itemStyle: {
        color: (p: any) => (peers[p.dataIndex]?.is_subject ? tokens.primary : tokens.benchmark),
      },
      data: peers.map((p) => [p.volatility, p.annualized_return, p.name]),
    }],
    animationDuration: 300,
  });
</script>

<div class="peer-scatter"><Chart {init} {option} notMerge={true} /></div>

<style>.peer-scatter { width: 100%; height: 340px; }</style>
```

- [ ] **Step 2: Factor exposure horizontal bar**

```svelte
<!-- frontends/wealth/src/lib/components/charts/screener/FactorExposureChart.svelte -->
<script lang="ts">
  import { Chart } from 'svelte-echarts';
  import { init } from 'echarts';
  import { chartTokens } from '../chart-tokens';
  import { formatNumber } from '@netz/ui';

  interface Factor { name: string; loading: number; }
  interface Props { factors: Factor[]; }
  let { factors }: Props = $props();

  const tokens = $derived.by(() => chartTokens());
  const option = $derived({
    textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
    grid: { left: 120, right: 32, top: 16, bottom: 24 },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      backgroundColor: tokens.tooltipBg, borderColor: tokens.tooltipBorder, borderWidth: 1,
      formatter: (p: any) => `<strong>${p[0].name}</strong>: ${formatNumber(p[0].value, 2)}`,
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: tokens.axisLabel },
      splitLine: { lineStyle: { color: tokens.grid, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: factors.map((f) => f.name),
      axisLabel: { color: tokens.axisLabel },
      axisLine: { lineStyle: { color: tokens.grid } },
    },
    series: [{
      type: 'bar',
      data: factors.map((f) => ({
        value: f.loading,
        itemStyle: { color: f.loading >= 0 ? tokens.positive : tokens.negative },
      })),
      barWidth: 16,
    }],
    animationDuration: 300,
  });
</script>

<div class="factor-bar"><Chart {init} {option} notMerge={true} /></div>

<style>.factor-bar { width: 100%; height: 280px; }</style>
```

- [ ] **Step 3: Wire into AnalyticsPanel if backend payload has `peers` / `factors`**

Only render when data is present; otherwise skip gracefully. These come from `peer_group` and `factor_model_service` — if not in the current analytics payload, this task can land the components without integration and track integration as a follow-up.

- [ ] **Step 4: Commit**

```bash
git add frontends/wealth/src/lib/components/charts/screener/
git commit -m "feat(screener): peer scatter + factor exposure charts"
```

### Task 5.3: Final visual validation + check gate

- [ ] **Step 1: Run full check**

```bash
make check
cd frontends/wealth && pnpm check
```

- [ ] **Step 2: Visual sweep at 4 breakpoints**

Test at 1920, 1440, 1280, 1024 px:
- Flow Managers → Funds → Fact Sheet / Analytics / DD
- Back button restores
- Theme toggle dark/light (charts re-read tokens)
- Private fund (no NAV) → empty state institutional
- Registered fund → full NAV chart
- Resize mid-session doesn't break chart sizing

- [ ] **Step 3: Commit any tweaks**

```bash
git add -A
git commit -m "polish(screener): visual validation fixes across breakpoints"
```

---

## Self-Review Results

**Spec coverage check:**
- FCL state machine + URL contract ✓ (Task 4.1)
- Neutral FlexibleColumnLayout promotion ✓ (Task 2.1)
- Portfolio Builder migration ✓ (Task 2.2)
- EnterpriseTable extraction ✓ (Task 2.3)
- CatalogTable v1/v2 deletion ✓ (Task 2.4)
- Keyset pagination indexes ✓ (Task 1.1)
- nav_monthly_returns_agg verification ✓ (Task 0.1, conditional 1.2)
- Col1 managers query + cache ✓ (Tasks 3.1, 3.2)
- Col2 funds query + cache ✓ (Tasks 3.1, 3.2)
- Col3 Analytics default 3y ✓ (Task 3.3)
- Col3 Fact Sheet ✓ (Task 3.3)
- Col3 DD snapshot + SSE ✓ (Tasks 3.3, 3.4)
- Chart foundation (CSS vars, Urbanist, formatters) ✓ (Task 1.3)
- NAV hero with drawdown overlay ✓ (Task 5.1)
- Institutional empty state for private funds ✓ (Task 4.4 AnalyticsPanel)
- URL-driven navigation with `replaceState:true, noScroll:true, keepFocus:true` ✓ (Task 4.1)
- AbortController on all async `$effect` ✓ (Tasks 4.4, 4.5)
- No localStorage ✓ (all state in `$state` or URL)
- Formatter discipline ✓ (columns.ts, panels use `@netz/ui` formatters)
- Peer scatter + factor exposure ✓ (Task 5.2)
- Rolling risk chart — **GAP**: not covered (originally in ECharts spec). **Rationale for gap:** depends on rolling metrics endpoint not yet in Phase 3 scope; ship as follow-up sprint.
- Holdings sunburst/treemap — **GAP**: same as above; holdings data is in payload but chart component deferred. **Rationale:** ScreenerFundsTable already exposes `has_holdings`; sunburst can land in a follow-up PR without blocking FCL UX.

**Placeholder scan:** clean — every code block is concrete.

**Type consistency:** `FCLState`, `ColumnDef<T>`, `ManagerRow`, `FundRowView` used consistently across tasks. `external_id` is the fund primary key throughout routes and frontend.

**Gaps flagged for follow-up sprint (not blockers):**
1. Rolling Sharpe/Vol chart
2. Holdings sunburst/treemap
3. L3 score materialization in `screening_results` (Andrei chose L1-only for v1)
4. LEI bridge for UCITS↔SEC manager merge

---

Plan complete and saved to `docs/superpowers/plans/2026-04-07-screener-fcl-enterprise-table.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
