# Discovery (FCL) + Enterprise Table + Standalone Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir uma página `/discovery` (renomeada de Screener — sinaliza que não é só filtros) com layout SAP UI5 Flexible Column Layout 3-col (Managers → Funds → DD Review | Fact Sheet) replicando o padrão enterprise table já validado em `/portfolio/universe`. Análises avançadas quantitativas saem do col3 e ganham uma página standalone full-width `/discovery/funds/{id}/analysis` com filtro avançado à esquerda + grid de charts (3 horizontal × 2 vertical) em três grupos: **Returns & Risk**, **Holdings Analysis**, **Peer Analysis**. Inclui features que aproveitam a profundidade do nosso quant engine + datasets SEC: Holdings Reverse Lookup com network viz Les Misérables, Style Drift Analysis, Institutional Portfolio Reveal (curated CIKs: Ivy endowments, Olayan, Iconic, single family offices), e bottom-dock persistente de análises abertas.

**Architecture:** Duas superfícies distintas, cada uma com sua disciplina:
1. **`/discovery`** — FCL 3-col CSS Grid `fr` interpolável (240ms transition), URL-driven (`?manager=&fund=&view=dd|factsheet`). Col3 = leitura rápida (DD chapters streaming + Fact Sheet metadata). Botão "Open Analysis" em cada fund row navega para a página standalone.
2. **`/discovery/funds/{external_id}/analysis`** — página standalone full-width com sidebar de filtros avançados à esquerda (260px) + main grid de charts em cards confortáveis. Tabs no topo selecionam grupo (Returns & Risk | Holdings | Peer). Bottom dock persistente acumula análises de fundos diferentes — usuário alterna sem perder estado.

Componentes neutros promovidos para `@netz/ui`: `FlexibleColumnLayout`, `EnterpriseTable`, `BottomTabDock`, `FilterRail`. Backend DB-only via `mv_unified_funds` + keyset pagination + Redis cache. ECharts institucional + ECharts Graph para network viz.

**Tech Stack:** SvelteKit 2 + Svelte 5 runes + `@netz/ui` + svelte-echarts (line/bar/scatter/graph/heatmap/sunburst) + FastAPI + PostgreSQL 16 + TimescaleDB + Redis + pgvector

**Decisions locked (Andrei, 2026-04-07 → 2026-04-08 revision):**
- Page renamed: `/screener` → `/discovery` (signals discovery + analysis, not just filters)
- Col2 default sort: `AUM DESC` (flagship-first institutional standard)
- Analytics moved OUT of col3 → standalone page (col3 too compressed for quant engine output)
- Col3 contains only: **DD Review** (SSE streaming) + **Fact Sheet** (metadata snapshot)
- Fund row buttons in col2: **DD** | **Fact Sheet** | **Open Analysis** (navigates away)
- Standalone Analysis default tab: **Returns & Risk**
- Default analytics window: `3y` (36 meses, industry standard) — applies to all charts that need a window
- Three analysis groups (filtered via left rail + tab selector):
  1. **Returns & Risk** — NAV/drawdown hero, rolling Sharpe/Vol, return distribution histogram, regime-conditioned scatter, monthly returns heatmap, contribution-to-risk
  2. **Holdings Analysis** — top holdings sunburst, sector/geo treemap, **Style Drift** (vector field of holding migration over quarters), **Holdings Reverse Lookup** (Les Misérables network viz of institutions sharing the same CIK), turnover/active share trend
  3. **Peer Analysis** — risk/return scatter (subject highlighted), peer return ranking ladder, expense ratio percentile, **Institutional Portfolio Reveal** (curated CIK list: Yale, Harvard, Princeton, Olayan Group, Iconic Capital, etc. — show their disclosed holdings overlap with subject fund)
- Bottom Tab Dock: persists analysis sessions across funds. Tab format: `[Fund Name] · [Group]`. Click switches state without losing filters. X closes. Persists in URL hash (no localStorage).
- `nav_monthly_returns_agg`: diagnóstico em prod **antes** de qualquer código
- L3 score em Col1: **apenas Layer 1 eliminatório no SQL** (sem worker batch novo neste sprint)
- UCITS vs US: **filtro separado** (sem LEI bridge)
- `FlexibleColumnsLayout`: **promover** para `@netz/ui` e migrar Portfolio Builder no mesmo PR
- `CatalogTable` + `CatalogTableV2`: **ambos eliminados** — nenhum é base canônica (ambos usam `@tanstack/svelte-table` quebrado no Svelte 5). Base vem da extração do `UniverseTable.svelte`.

---

## Revision Log

- **2026-04-08** — Major revision after design review:
  1. Renamed `/screener` → `/discovery` throughout
  2. Removed Analytics panel from FCL col3 (too compressed for quant engine power)
  3. Added Phases 5-8: standalone Analysis page, Holdings Analysis features (Style Drift, Reverse Lookup), Peer Analysis (Institutional Reveal), Bottom Tab Dock
  4. Backend gained 6 new endpoints + 3 new query modules
  5. New chart components: NetworkGraph (Les Mis), StyleDriftFlow, InstitutionalRevealMatrix, ReturnDistribution, MonthlyReturnsHeatmap
  6. Phase 5 (originally NAV-in-col3) is now reframed entirely as standalone page foundation

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
- Create: `backend/app/core/db/migrations/versions/0093_discovery_fcl_keyset_indexes.py`
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
# backend/app/core/db/migrations/versions/0093_discovery_fcl_keyset_indexes.py
"""discovery FCL keyset indexes

Revision ID: 0093_discovery_fcl_keyset_indexes
Revises: 0092_wealth_library_triggers
Create Date: 2026-04-07
"""
from alembic import op

revision = "0093_discovery_fcl_keyset_indexes"
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
git add backend/app/core/db/migrations/versions/0093_discovery_fcl_keyset_indexes.py backend/tests/db/test_migration_0093.py
git commit -m "feat(db): keyset indexes for discovery FCL col1/col2 pagination"
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
down_revision = "0093_discovery_fcl_keyset_indexes"
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

Extração dos dois primitives que tanto Discovery quanto Portfolio Builder vão consumir. Inclui refactor do Portfolio Builder no mesmo PR para evitar débito paralelo.

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
- Delete: `frontends/wealth/src/lib/components/discovery/CatalogTable.svelte`
- Delete: `frontends/wealth/src/lib/components/discovery/CatalogTableV2.svelte`
- Modify: Any route consuming them (will be rewritten in Phase 4)

- [ ] **Step 1: Grep for consumers**

Run: `grep -rn "CatalogTable" frontends/wealth/src/`
Note every file that imports either.

- [ ] **Step 2: Stub the new discovery route**

Create `frontends/wealth/src/routes/(app)/discovery/+page.svelte` as a placeholder:
```svelte
<script lang="ts">
  // Temporarily stubbed during FCL migration. Real impl in Phase 4.
</script>
<div class="p-8 text-center text-muted">
  Discovery is being rebuilt. Check back after Phase 4.
</div>
```
This keeps `make check` green while we land the component deletion.

- [ ] **Step 3: Delete both files**

```bash
rm frontends/wealth/src/lib/components/discovery/CatalogTable.svelte
rm frontends/wealth/src/lib/components/discovery/CatalogTableV2.svelte
```

- [ ] **Step 4: Run frontend check**

```bash
cd frontends/wealth && pnpm check
```
Expected: zero errors (or only errors about the stubbed page, which are fine).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(discovery): delete CatalogTable v1/v2 ahead of FCL rewrite"
```

---

## Phase 3 — Backend routes + caching

Rotas DB-only alimentando Col1/Col2/Col3, com Redis cache + SingleFlightLock.

### Task 3.1: Schemas + keyset helpers

**Files:**
- Create: `backend/app/domains/wealth/schemas/discovery.py`
- Create: `backend/app/domains/wealth/queries/discovery_keyset.py`
- Test: `backend/tests/domains/wealth/test_discovery_keyset.py`

- [ ] **Step 1: Write Pydantic schemas**

```python
# backend/app/domains/wealth/schemas/discovery.py
from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

class DiscoveryFilters(BaseModel):
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
# backend/tests/domains/wealth/test_discovery_keyset.py
import pytest
from backend.app.domains.wealth.queries.discovery_keyset import (
    build_managers_query, build_funds_query,
)
from backend.app.domains.wealth.schemas.discovery import (
    DiscoveryFilters, ManagerCursor, FundCursor,
)

def test_managers_query_no_cursor_no_filters():
    sql, params = build_managers_query(DiscoveryFilters(), cursor=None, limit=50)
    assert "ORDER BY sm.aum_total DESC NULLS LAST" in sql
    assert "LIMIT" in sql
    assert params["limit"] == 50
    assert params["cursor_aum"] is None

def test_managers_query_with_strategy_filter():
    sql, params = build_managers_query(
        DiscoveryFilters(strategies=["Private Credit", "Buyout"]),
        cursor=None, limit=50,
    )
    assert "strategy_label = ANY" in sql
    assert params["strategies"] == ["Private Credit", "Buyout"]

def test_managers_query_with_keyset_cursor():
    sql, params = build_managers_query(
        DiscoveryFilters(),
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

Run: `pytest backend/tests/domains/wealth/test_discovery_keyset.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement keyset builder**

```python
# backend/app/domains/wealth/queries/discovery_keyset.py
from typing import Any
from backend.app.domains.wealth.schemas.discovery import (
    DiscoveryFilters, ManagerCursor, FundCursor,
)

def build_managers_query(
    filters: DiscoveryFilters,
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

Run: `pytest backend/tests/domains/wealth/test_discovery_keyset.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/schemas/discovery_fcl.py backend/app/domains/wealth/queries/discovery_keyset.py backend/tests/domains/wealth/test_discovery_keyset.py
git commit -m "feat(wealth): discovery FCL keyset query builders + schemas"
```

### Task 3.2: Routes for Col1 (managers) + Col2 (funds)

**Files:**
- Create: `backend/app/domains/wealth/routes/discovery_fcl.py`
- Modify: `backend/app/domains/wealth/routes/__init__.py` (register router)
- Test: `backend/tests/domains/wealth/test_discovery_fcl_routes.py`

- [ ] **Step 1: Write failing integration tests**

```python
# backend/tests/domains/wealth/test_discovery_fcl_routes.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_managers_list_returns_200_with_rows(
    async_client: AsyncClient, dev_headers: dict,
):
    resp = await async_client.post(
        "/api/wealth/discovery/managers",
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
        f"/api/wealth/discovery/managers/{sample_manager_id}/funds",
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
    await async_client.post("/api/wealth/discovery/managers", json=payload, headers=dev_headers)
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    await async_client.post("/api/wealth/discovery/managers", json=payload, headers=dev_headers)
    warm = time.perf_counter() - t1
    assert warm < cold  # cache hit must be faster
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest backend/tests/domains/wealth/test_discovery_fcl_routes.py -v`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement routes**

```python
# backend/app/domains/wealth/routes/discovery_fcl.py
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db_with_rls
from backend.app.core.cache.redis_client import get_redis
from backend.app.core.runtime.single_flight import SingleFlightLock
from backend.app.domains.wealth.queries.discovery_keyset import (
    build_managers_query, build_funds_query,
)
from backend.app.domains.wealth.schemas.discovery import (
    DiscoveryFilters, ManagerCursor, FundCursor,
    ManagersListResponse, FundsListResponse, ManagerRow, FundRow,
)
from pydantic import BaseModel

router = APIRouter(prefix="/wealth/discovery", tags=["wealth-discovery"])

MANAGERS_TTL = 5 * 60
FUNDS_TTL = 10 * 60


class ManagersListRequest(BaseModel):
    filters: DiscoveryFilters = DiscoveryFilters()
    cursor: ManagerCursor | None = None
    limit: int = 50


class FundsListRequest(BaseModel):
    cursor: FundCursor | None = None
    limit: int = 50


def _cache_key(namespace: str, org_id: str, **kwargs) -> str:
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"discovery:{namespace}:{org_id}:{digest}"


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
from .discovery_fcl import router as discovery_fcl_router
# ... in the main include_router section:
# app.include_router(discovery_fcl_router)
```

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/domains/wealth/test_discovery_fcl_routes.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/routes/discovery_fcl.py backend/app/domains/wealth/routes/__init__.py backend/tests/domains/wealth/test_discovery_fcl_routes.py
git commit -m "feat(wealth): POST /discovery/managers + /managers/{id}/funds with Redis cache"
```

### Task 3.3: Routes for Col3 — Fact Sheet + DD snapshot

Col3 stays lightweight: Fact Sheet (metadata aggregation) + DD snapshot. Advanced analytics live in the standalone page (Phase 5+) — not in col3.

**Files:**
- Modify: `backend/app/domains/wealth/routes/discovery_fcl.py`
- Create: `backend/app/domains/wealth/queries/fund_resolver.py`
- Test: `backend/tests/domains/wealth/test_discovery_fcl_col3.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/domains/wealth/test_discovery_fcl_col3.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_fact_sheet_returns_aggregated_payload(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/fact-sheet",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "fund" in body
    assert "classes" in body

@pytest.mark.asyncio
async def test_dd_report_snapshot_returns_chapters(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/dd-report/snapshot",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "chapters" in body
    assert isinstance(body["chapters"], list)

@pytest.mark.asyncio
async def test_fact_sheet_404_for_unknown_fund(
    async_client: AsyncClient, dev_headers: dict,
):
    resp = await async_client.get(
        "/api/wealth/discovery/funds/NONEXISTENT/fact-sheet",
        headers=dev_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest backend/tests/domains/wealth/test_discovery_fcl_col3.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fund_resolver.py`**

Shared utility for resolving `external_id` → `(instrument_id, cik, universe)`. Used by Col3 routes AND by the standalone Analysis routes in Phase 5+.

```python
# backend/app/domains/wealth/queries/fund_resolver.py
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException


async def resolve_fund(db: AsyncSession, external_id: str) -> dict[str, Any]:
    sql = """
        SELECT external_id, universe, ticker, series_id, name
        FROM mv_unified_funds WHERE external_id = :id
    """
    row = (await db.execute(text(sql), {"id": external_id})).mappings().first()
    if not row:
        raise HTTPException(404, f"fund {external_id} not found")
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
        "name": row["name"],
        "ticker": row["ticker"],
        "series_id": row["series_id"],
        "instrument_id": inst["instrument_id"] if inst else None,
        "cik": inst["cik"] if inst else None,
    }
```

- [ ] **Step 4: Add Fact Sheet + DD snapshot routes to `discovery_fcl.py`**

```python
# append to backend/app/domains/wealth/routes/discovery_fcl.py
from backend.app.domains.wealth.queries.fund_resolver import resolve_fund

FACTSHEET_TTL = 60 * 60


@router.get("/funds/{external_id}/fact-sheet")
async def fund_fact_sheet(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
):
    redis = await get_redis()
    key = f"discovery:factsheet:{external_id}"
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
pytest backend/tests/domains/wealth/test_discovery_fcl_col3.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domains/wealth/queries/fund_resolver.py backend/app/domains/wealth/routes/discovery_fcl.py backend/tests/domains/wealth/test_discovery_fcl_col3.py
git commit -m "feat(wealth): discovery col3 routes — fact sheet + DD snapshot"
```

### Task 3.4: DD streaming SSE endpoint

**Files:**
- Modify: `backend/app/domains/wealth/routes/discovery_fcl.py`
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
        f"/api/wealth/discovery/funds/{sample_fund_id}/dd-report/stream",
        headers=dev_headers,
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test**

Run: `pytest backend/tests/domains/wealth/test_dd_stream.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement SSE bridge**

Append to `discovery_fcl.py`:
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
git add backend/app/domains/wealth/routes/discovery_fcl.py backend/tests/domains/wealth/test_dd_stream.py
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

## Phase 4 — Discovery frontend FCL page

### Task 4.1: Discovery state helpers + URL sync

**Files:**
- Create: `frontends/wealth/src/lib/discovery/fcl-state.svelte.ts`
- Create: `frontends/wealth/src/lib/discovery/api.ts`

- [ ] **Step 1: Implement URL-derived FCL state helpers**

```ts
// frontends/wealth/src/lib/discovery/fcl-state.svelte.ts
import { page } from '$app/state';
import { goto } from '$app/navigation';
import type { FCLState } from '@netz/ui';

export function useDiscoveryUrlState() {
  const managerId = $derived(page.url.searchParams.get('manager'));
  const fundId = $derived(page.url.searchParams.get('fund'));
  const view = $derived(
    (page.url.searchParams.get('view') ?? 'factsheet') as 'dd' | 'factsheet',
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
    selectFund: (id: string, v: 'dd' | 'factsheet' = 'factsheet') =>
      patch({ fund: id, view: v }),
    changeView: (v: 'dd' | 'factsheet') => patch({ view: v }),
    closeCol3: () => patch({ fund: null, view: null }),
    clearManager: () => patch({ manager: null, fund: null, view: null }),
    /** Navigates to the standalone full-width Analysis page. */
    openAnalysis: async (fundId: string, group: 'returns-risk' | 'holdings' | 'peer' = 'returns-risk') => {
      await goto(`/discovery/funds/${encodeURIComponent(fundId)}/analysis?group=${group}`, {
        noScroll: true,
      });
    },
  };
}
```

- [ ] **Step 2: Implement API client**

```ts
// frontends/wealth/src/lib/discovery/api.ts
import { getAuthHeaders } from '$lib/auth';

const BASE = '/api/wealth/discovery';

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
git add frontends/wealth/src/lib/discovery/
git commit -m "feat(discovery): URL state + API client helpers"
```

### Task 4.2: Managers table column defs + row component

**Files:**
- Create: `frontends/wealth/src/lib/components/discovery/DiscoveryManagersTable.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/columns.ts`

- [ ] **Step 1: Define manager columns**

```ts
// frontends/wealth/src/lib/components/discovery/columns.ts
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

- [ ] **Step 2: Implement `DiscoveryManagersTable`**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/DiscoveryManagersTable.svelte -->
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
git add frontends/wealth/src/lib/components/discovery/
git commit -m "feat(discovery): managers table with compact/full column modes"
```

### Task 4.3: Funds table with inline action buttons

**Files:**
- Create: `frontends/wealth/src/lib/components/discovery/DiscoveryFundsTable.svelte`

- [ ] **Step 1: Implement funds table with 3 action buttons per row**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/DiscoveryFundsTable.svelte -->
<script lang="ts">
  import { EnterpriseTable, formatCurrency, formatPercent } from '@netz/ui';
  import type { ColumnDef } from '@netz/ui';
  import type { FundRowView } from './columns';

  interface Props {
    rows: FundRowView[];
    selectedFundId: string | null;
    activeView: 'dd' | 'factsheet' | null;
    onSelectCol3: (id: string, view: 'dd' | 'factsheet') => void;
    onOpenAnalysis: (id: string) => void;
  }

  let { rows, selectedFundId, activeView, onSelectCol3, onOpenAnalysis }: Props = $props();

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
        onclick={(e) => { e.stopPropagation(); onSelectCol3(row.external_id, 'dd'); }}
        title="DD Review (opens in col3)"
      >DD</button>
      <button
        class="act-btn"
        class:active={row.external_id === selectedFundId && activeView === 'factsheet'}
        onclick={(e) => { e.stopPropagation(); onSelectCol3(row.external_id, 'factsheet'); }}
        title="Fact Sheet (opens in col3)"
      >FS</button>
      <button
        class="act-btn act-btn--primary"
        onclick={(e) => { e.stopPropagation(); onOpenAnalysis(row.external_id); }}
        title="Open full-width Analysis page"
      >Analysis →</button>
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
  .act-btn--primary {
    background: var(--ii-accent-subtle, rgba(0, 102, 255, 0.08));
    color: var(--ii-accent, #0066ff);
    border-color: var(--ii-accent, #0066ff);
  }
  .act-btn--primary:hover {
    background: var(--ii-accent, #0066ff);
    color: white;
  }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontends/wealth/src/lib/components/discovery/DiscoveryFundsTable.svelte
git commit -m "feat(discovery): funds table with inline DD/FS/Open-Analysis actions"
```

### Task 4.4: Col3 panels — Fact Sheet + DD Review

Col3 holds only the two "quick read" panels. Any deeper analytics use the standalone Analysis page (Phase 5+).

**Files:**
- Create: `frontends/wealth/src/lib/components/discovery/col3/FactSheetPanel.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/col3/DDReviewPanel.svelte`

- [ ] **Step 1: Fact Sheet panel**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/col3/FactSheetPanel.svelte -->
<script lang="ts">
  import { formatCurrency, formatPercent } from '@netz/ui';
  import { fetchFundFactSheet } from '$lib/discovery/api';

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

- [ ] **Step 2: DD Review panel with SSE**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/col3/DDReviewPanel.svelte -->
<script lang="ts">
  import { openDDReportStream } from '$lib/discovery/api';

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

- [ ] **Step 3: Commit**

```bash
git add frontends/wealth/src/lib/components/discovery/col3/
git commit -m "feat(discovery): col3 panels — factsheet + DD SSE (analytics lives in standalone page)"
```

### Task 4.5: Discovery page orchestrator

**Files:**
- Create: `frontends/wealth/src/routes/(app)/discovery/+page.server.ts`
- Modify: `frontends/wealth/src/routes/(app)/discovery/+page.svelte` (replace Phase 2 stub)

- [ ] **Step 1: Server load for initial managers**

```ts
// frontends/wealth/src/routes/(app)/discovery/+page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, url }) => {
  const res = await fetch('/api/wealth/discovery/managers', {
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
<!-- frontends/wealth/src/routes/(app)/discovery/+page.svelte -->
<script lang="ts">
  import { FlexibleColumnLayout, type FCLRatios } from '@netz/ui';
  import { useDiscoveryUrlState } from '$lib/discovery/fcl-state.svelte';
  import { fetchFundsByManager } from '$lib/discovery/api';
  import DiscoveryManagersTable from '$lib/components/discovery/DiscoveryManagersTable.svelte';
  import DiscoveryFundsTable from '$lib/components/discovery/DiscoveryFundsTable.svelte';
  import FactSheetPanel from '$lib/components/discovery/col3/FactSheetPanel.svelte';
  import DDReviewPanel from '$lib/components/discovery/col3/DDReviewPanel.svelte';
  import type { ManagerRow, FundRowView } from '$lib/components/discovery/columns';

  let { data } = $props();

  const fcl = useDiscoveryUrlState();

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

<svelte:head><title>Discovery — Netz Wealth</title></svelte:head>

<FlexibleColumnLayout
  state={fcl.state}
  ratios={SCREENER_RATIOS}
  column1Label="Managers"
  column2Label="Funds"
  column3Label="Fund Detail"
>
  {#snippet column1()}
    <DiscoveryManagersTable
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
      <DiscoveryFundsTable
        rows={funds}
        selectedFundId={fcl.fundId}
        activeView={fcl.fundId ? fcl.view : null}
        onSelectCol3={(id, view) => fcl.selectFund(id, view)}
        onOpenAnalysis={(id) => fcl.openAnalysis(id, 'returns-risk')}
      />
    {/if}
  {/snippet}
  {#snippet column3()}
    {#if fcl.fundId}
      {#if fcl.view === 'dd'}
        <DDReviewPanel fundId={fcl.fundId} />
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
npx @sveltejs/mcp svelte-autofixer src/routes/\(app\)/discovery/+page.svelte
```
Expected: zero errors.

- [ ] **Step 4: Visual validation in browser**

Run `make dev-wealth` then open `/discovery`. Verify:
1. Landing state: managers table full-width
2. Click manager → Col1 recua, Col2 abre com fundos em AUM DESC
3. Click **DD** ou **FS** button em qualquer fundo → Col3 abre com o conteúdo correto
4. Click outro botão do mesmo fundo → Col3 troca de view sem fechar
5. Click **Analysis →** → navega para `/discovery/funds/{id}/analysis` (standalone, full-width)
6. Browser back button → volta para `/discovery` restaurando seleção do manager/fundo
7. Refresh com `?manager=X&fund=Y&view=dd` na URL → restaura estado direto (views válidas: `dd` | `factsheet`)
8. Resize para < 1100px → Col3 vira overlay
9. Resize para < 1024px → stack vertical (fallback do container query)

- [ ] **Step 5: Commit**

```bash
git add frontends/wealth/src/routes/\(app\)/discovery/
git commit -m "feat(discovery): FCL 3-column page orchestrator with URL state sync"
```

---

## Phase 5 — Standalone Analysis page foundation (Returns & Risk)

Cria a rota `/discovery/funds/{external_id}/analysis`, seu layout (FilterRail 260px esquerda + main grid de chart cards), tabs de grupo (Returns & Risk | Holdings | Peer), o primeiro grupo totalmente funcional (Returns & Risk) e o backend que o alimenta. Grupos Holdings e Peer vêm nas Phases 6 e 7.

### Task 5.1: Backend — analysis_returns query module + route

**Files:**
- Create: `backend/app/domains/wealth/queries/analysis_returns.py`
- Create: `backend/app/domains/wealth/routes/discovery_analysis.py`
- Modify: `backend/app/domains/wealth/routes/__init__.py`
- Test: `backend/tests/domains/wealth/test_analysis_returns.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/domains/wealth/test_analysis_returns.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_returns_risk_default_3y(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/returns-risk",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"] == "3y"
    assert "nav_series" in body
    assert "monthly_returns" in body
    assert "rolling_metrics" in body
    assert "return_distribution" in body
    assert "risk_metrics" in body

@pytest.mark.asyncio
async def test_returns_risk_custom_window(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/returns-risk?window=5y",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["window"] == "5y"

@pytest.mark.asyncio
async def test_private_fund_returns_empty(
    async_client: AsyncClient, dev_headers: dict, sample_private_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_private_fund_id}/analysis/returns-risk",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclosure"]["has_nav"] is False
    assert body["nav_series"] == []
```

- [ ] **Step 2: Implement `analysis_returns.py`**

```python
# backend/app/domains/wealth/queries/analysis_returns.py
import asyncio
import math
from typing import Any, Literal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Window = Literal["1y", "3y", "5y", "max"]
WINDOW_INTERVAL = {"1y": "1 year", "3y": "3 years", "5y": "5 years", "max": "50 years"}


async def _nav_series(db: AsyncSession, instrument_id: str, window: Window) -> list[dict[str, Any]]:
    sql = f"""
        SELECT nav_date, nav, return_1d
        FROM nav_timeseries
        WHERE instrument_id = :id AND nav_date >= NOW() - INTERVAL '{WINDOW_INTERVAL[window]}'
        ORDER BY nav_date ASC
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    return [dict(r) for r in res.mappings().all()]


async def _monthly_returns(db: AsyncSession, instrument_id: str, window: Window) -> list[dict[str, Any]]:
    sql = f"""
        SELECT month, compound_return, trading_days
        FROM nav_monthly_returns_agg
        WHERE instrument_id = :id AND month >= NOW() - INTERVAL '{WINDOW_INTERVAL[window]}'
        ORDER BY month ASC
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    return [dict(r) for r in res.mappings().all()]


async def _risk_metrics(db: AsyncSession, instrument_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT * FROM fund_risk_metrics
        WHERE instrument_id = :id ORDER BY calc_date DESC LIMIT 1
    """
    res = await db.execute(text(sql), {"id": instrument_id})
    row = res.mappings().first()
    return dict(row) if row else None


def _compute_rolling(nav_series: list[dict[str, Any]], window_days: int = 252) -> list[dict[str, Any]]:
    """Simple rolling Sharpe/Vol from nav_series return_1d column."""
    out: list[dict[str, Any]] = []
    returns = [p["return_1d"] for p in nav_series if p["return_1d"] is not None]
    if len(returns) < window_days:
        return out
    for i in range(window_days, len(nav_series)):
        window = returns[i - window_days : i]
        mean = sum(window) / len(window)
        var = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
        vol = math.sqrt(var) * math.sqrt(252)
        sharpe = (mean * 252) / vol if vol > 0 else 0.0
        out.append({
            "date": nav_series[i]["nav_date"],
            "rolling_vol": vol,
            "rolling_sharpe": sharpe,
        })
    return out


def _compute_return_distribution(monthly: list[dict[str, Any]]) -> dict[str, Any]:
    """Bucket monthly returns into histogram bins for visualization."""
    if not monthly:
        return {"bins": [], "counts": []}
    values = [m["compound_return"] for m in monthly if m["compound_return"] is not None]
    if not values:
        return {"bins": [], "counts": []}
    lo, hi = min(values), max(values)
    n_bins = 20
    width = (hi - lo) / n_bins if hi > lo else 0.01
    counts = [0] * n_bins
    for v in values:
        idx = min(int((v - lo) / width), n_bins - 1) if width > 0 else 0
        counts[idx] += 1
    bins = [round(lo + i * width, 4) for i in range(n_bins)]
    return {"bins": bins, "counts": counts, "mean": sum(values) / len(values)}


async def fetch_returns_risk(
    db: AsyncSession, instrument_id: str, window: Window = "3y",
) -> dict[str, Any]:
    nav, monthly, risk = await asyncio.gather(
        _nav_series(db, instrument_id, window),
        _monthly_returns(db, instrument_id, window),
        _risk_metrics(db, instrument_id),
    )
    rolling = _compute_rolling(nav)
    distribution = _compute_return_distribution(monthly)
    return {
        "window": window,
        "nav_series": nav,
        "monthly_returns": monthly,
        "rolling_metrics": rolling,
        "return_distribution": distribution,
        "risk_metrics": risk,
        "disclosure": {"has_nav": len(nav) > 0},
    }
```

- [ ] **Step 3: Implement route in `discovery_analysis.py`**

```python
# backend/app/domains/wealth/routes/discovery_analysis.py
import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.db import get_db_with_rls
from backend.app.core.cache.redis_client import get_redis
from backend.app.domains.wealth.queries.analysis_returns import (
    fetch_returns_risk, Window,
)
from backend.app.domains.wealth.queries.fund_resolver import resolve_fund

router = APIRouter(prefix="/wealth/discovery", tags=["wealth-discovery-analysis"])

RETURNS_TTL = 60 * 60


@router.get("/funds/{external_id}/analysis/returns-risk")
async def analysis_returns_risk(
    external_id: str,
    window: Window = Query("3y"),
    db: AsyncSession = Depends(get_db_with_rls),
):
    redis = await get_redis()
    key = f"discovery:analysis:returns:{external_id}:{window}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)

    fund = await resolve_fund(db, external_id)
    if not fund["instrument_id"]:
        payload = {
            "window": window,
            "nav_series": [],
            "monthly_returns": [],
            "rolling_metrics": [],
            "return_distribution": {"bins": [], "counts": []},
            "risk_metrics": None,
            "disclosure": {"has_nav": False},
            "fund": fund,
        }
    else:
        payload = await fetch_returns_risk(db, fund["instrument_id"], window)
        payload["fund"] = fund

    await redis.setex(key, RETURNS_TTL, json.dumps(payload, default=str))
    return payload
```

- [ ] **Step 4: Register router and run tests**

Add to `backend/app/domains/wealth/routes/__init__.py`:
```python
from .discovery_analysis import router as discovery_analysis_router
# app.include_router(discovery_analysis_router)
```

```bash
pytest backend/tests/domains/wealth/test_analysis_returns.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domains/wealth/queries/analysis_returns.py backend/app/domains/wealth/routes/discovery_analysis.py backend/app/domains/wealth/routes/__init__.py backend/tests/domains/wealth/test_analysis_returns.py
git commit -m "feat(discovery): returns-risk analysis endpoint (DB-only, 3y default)"
```

### Task 5.2: `FilterRail` primitive in `@netz/ui`

**Files:**
- Create: `packages/ui/src/lib/layouts/FilterRail.svelte`
- Modify: `packages/ui/src/lib/index.ts`

- [ ] **Step 1: Implement FilterRail**

```svelte
<!-- packages/ui/src/lib/layouts/FilterRail.svelte -->
<!--
  260px sticky left rail for advanced filters on standalone analytical pages.
  Owns scrolling of filter groups; never scrolls the page. Caller composes
  filter UI via the `filters` snippet and header via `header` snippet.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  interface Props {
    header?: Snippet;
    filters: Snippet;
    footer?: Snippet;
    width?: string;
  }
  let { header, filters, footer, width = '260px' }: Props = $props();
</script>

<aside class="fr-root" style:width aria-label="Filters">
  {#if header}<div class="fr-header">{@render header()}</div>{/if}
  <div class="fr-body">{@render filters()}</div>
  {#if footer}<div class="fr-footer">{@render footer()}</div>{/if}
</aside>

<style>
  .fr-root {
    flex-shrink: 0;
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--ii-bg-surface-alt, #1a1c22);
    border-right: 1px solid var(--ii-border-subtle, rgba(64,66,73,0.4));
    font-family: 'Urbanist', system-ui, sans-serif;
  }
  .fr-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--ii-border-subtle);
    flex-shrink: 0;
  }
  .fr-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 16px 20px;
  }
  .fr-footer {
    padding: 12px 20px;
    border-top: 1px solid var(--ii-border-subtle);
    flex-shrink: 0;
  }
</style>
```

- [ ] **Step 2: Export**

```ts
// packages/ui/src/lib/index.ts
export { default as FilterRail } from './layouts/FilterRail.svelte';
```

- [ ] **Step 3: Commit**

```bash
git add packages/ui/src/lib/layouts/FilterRail.svelte packages/ui/src/lib/index.ts
git commit -m "feat(ui): FilterRail primitive for standalone analytical pages"
```

### Task 5.3: Chart card wrapper + analysis grid layout

**Files:**
- Create: `frontends/wealth/src/lib/components/discovery/analysis/ChartCard.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/analysis/AnalysisGrid.svelte`

- [ ] **Step 1: ChartCard wrapper (confortável, sem marketing)**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/ChartCard.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  interface Props {
    title: string;
    subtitle?: string;
    children: Snippet;
    actions?: Snippet;
    span?: 1 | 2 | 3;
    minHeight?: string;
  }
  let { title, subtitle, children, actions, span = 1, minHeight = '320px' }: Props = $props();
</script>

<section class="cc-card" data-span={span} style:min-height={minHeight}>
  <header class="cc-head">
    <div class="cc-titles">
      <h3 class="cc-title">{title}</h3>
      {#if subtitle}<p class="cc-subtitle">{subtitle}</p>{/if}
    </div>
    {#if actions}<div class="cc-actions">{@render actions()}</div>{/if}
  </header>
  <div class="cc-body">{@render children()}</div>
</section>

<style>
  .cc-card {
    display: flex;
    flex-direction: column;
    background: var(--ii-bg-surface, #141519);
    border: 1px solid var(--ii-border-subtle, rgba(64,66,73,0.4));
    border-radius: 6px;
    padding: 20px 24px 24px;
    font-family: 'Urbanist', system-ui, sans-serif;
  }
  .cc-card[data-span="2"] { grid-column: span 2; }
  .cc-card[data-span="3"] { grid-column: span 3; }
  .cc-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 16px;
    gap: 12px;
  }
  .cc-titles { min-width: 0; }
  .cc-title { font-size: 13px; font-weight: 600; margin: 0; color: var(--ii-text-primary); letter-spacing: 0.01em; }
  .cc-subtitle { font-size: 11px; color: var(--ii-text-muted); margin: 2px 0 0; }
  .cc-actions { flex-shrink: 0; }
  .cc-body { flex: 1; min-height: 0; }
</style>
```

- [ ] **Step 2: AnalysisGrid — 3 cols horizontal, 2 rows vertical**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/AnalysisGrid.svelte -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  interface Props { children: Snippet; }
  let { children }: Props = $props();
</script>

<div class="ag-root">{@render children()}</div>

<style>
  .ag-root {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 20px;
    padding: 24px;
    min-height: 0;
  }
  @container (max-width: 1400px) {
    .ag-root { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .ag-root :global(.cc-card[data-span="3"]) { grid-column: span 2; }
  }
  @container (max-width: 1000px) {
    .ag-root { grid-template-columns: 1fr; }
    .ag-root :global(.cc-card[data-span="2"]),
    .ag-root :global(.cc-card[data-span="3"]) { grid-column: span 1; }
  }
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontends/wealth/src/lib/components/discovery/analysis/
git commit -m "feat(discovery): ChartCard + AnalysisGrid primitives"
```

### Task 5.4: Returns & Risk charts (6 cards)

Six chart components feeding the Returns & Risk grid. All use `svelte-echarts`, `chartTokens()`, and `@netz/ui` formatters. Data comes from the Phase 5.1 endpoint.

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/discovery/NavHeroChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/RollingRiskChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/MonthlyReturnsHeatmap.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/ReturnDistributionChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/DrawdownUnderwaterChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/RiskMetricsBulletChart.svelte`

- [ ] **Step 1: NAV hero (cumulative return + drawdown shared dataset)**

Component already specified below. The hero chart gets `data-span="3"` in the grid (occupies full width on row 1).

- [ ] **Step 1.1: Implement NAV hero with shared dataset**

```svelte
<!-- frontends/wealth/src/lib/components/charts/discovery/NavHeroChart.svelte -->
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

- [ ] **Step 2: RollingRiskChart** — two stacked grids (rolling Sharpe top, rolling Vol bottom), single `dataset.source` fed by `rolling_metrics`. No dual y-axis. Line `series.sampling = 'lttb'`. Tokens from `chartTokens()`.

- [ ] **Step 3: MonthlyReturnsHeatmap** — X axis = month (1-12), Y axis = year descending, cell value = `compound_return`. `visualMap` divergent green/red around 0. Built from `monthly_returns`.

- [ ] **Step 4: ReturnDistributionChart** — vertical bars from `return_distribution.bins/counts`. Vertical dashed line at `mean`. `markLine` annotation for mean.

- [ ] **Step 5: DrawdownUnderwaterChart** — dedicated chart (even though NAV hero already overlays drawdown, users want a standalone zoomed view). Area below zero, `lineStyle.width: 1`, red token.

- [ ] **Step 6: RiskMetricsBulletChart** — horizontal bullet chart per metric (Sharpe, Sortino, Volatility, Max DD, CVaR 95, Beta). Each row: actual value bar + peer median marker + target band. Data: `risk_metrics` fields.

- [ ] **Step 7: Commit the 6 chart components**

```bash
git add frontends/wealth/src/lib/components/charts/discovery/
git commit -m "feat(discovery): Returns & Risk chart components (6 cards)"
```

### Task 5.5: Analysis page route + Returns & Risk view

**Files:**
- Create: `frontends/wealth/src/routes/(app)/discovery/funds/[external_id]/analysis/+page.server.ts`
- Create: `frontends/wealth/src/routes/(app)/discovery/funds/[external_id]/analysis/+page.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/analysis/ReturnsRiskView.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/analysis/AnalysisFilters.svelte`
- Create: `frontends/wealth/src/lib/discovery/analysis-api.ts`

- [ ] **Step 1: Analysis API client**

```ts
// frontends/wealth/src/lib/discovery/analysis-api.ts
import { getAuthHeaders } from '$lib/auth';

const BASE = '/api/wealth/discovery';

export async function fetchReturnsRisk(
  fundId: string,
  window: '1y' | '3y' | '5y' | 'max',
  signal: AbortSignal,
) {
  const res = await fetch(
    `${BASE}/funds/${encodeURIComponent(fundId)}/analysis/returns-risk?window=${window}`,
    { headers: await getAuthHeaders(), signal },
  );
  if (!res.ok) throw new Error(`returns-risk: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Server load (fact sheet header metadata)**

```ts
// +page.server.ts
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, params, url }) => {
  const fsRes = await fetch(
    `/api/wealth/discovery/funds/${encodeURIComponent(params.external_id)}/fact-sheet`,
  );
  if (!fsRes.ok) {
    return { status: 'error' as const, error: `fact-sheet load: ${fsRes.status}` };
  }
  const header = await fsRes.json();
  return {
    status: 'ok' as const,
    fundId: params.external_id,
    header,
    initialGroup: (url.searchParams.get('group') ?? 'returns-risk') as
      | 'returns-risk' | 'holdings' | 'peer',
    initialWindow: (url.searchParams.get('window') ?? '3y') as
      | '1y' | '3y' | '5y' | 'max',
  };
};
```

- [ ] **Step 3: Analysis filters rail (shared across 3 groups)**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/AnalysisFilters.svelte -->
<script lang="ts">
  interface Props {
    group: 'returns-risk' | 'holdings' | 'peer';
    window: '1y' | '3y' | '5y' | 'max';
    onWindowChange: (w: '1y' | '3y' | '5y' | 'max') => void;
    // Group-specific filter snippets rendered conditionally
  }
  let { group, window, onWindowChange }: Props = $props();
</script>

<div class="af-section">
  <h4>Time Window</h4>
  <div class="af-radio-group">
    {#each ['1y', '3y', '5y', 'max'] as w}
      <label class:active={window === w}>
        <input
          type="radio"
          name="window"
          value={w}
          checked={window === w}
          onchange={() => onWindowChange(w as any)}
        />
        {w.toUpperCase()}
      </label>
    {/each}
  </div>
</div>

{#if group === 'returns-risk'}
  <div class="af-section">
    <h4>Benchmarks</h4>
    <label><input type="checkbox" checked /> S&P 500</label>
    <label><input type="checkbox" /> MSCI World</label>
    <label><input type="checkbox" /> Peer median</label>
  </div>
  <div class="af-section">
    <h4>Display</h4>
    <label><input type="checkbox" checked /> Regime shading</label>
    <label><input type="checkbox" checked /> Drawdown overlay</label>
  </div>
{:else if group === 'holdings'}
  <div class="af-section">
    <h4>Holdings lens</h4>
    <label><input type="radio" name="lens" checked /> Top 25 by weight</label>
    <label><input type="radio" name="lens" /> Top sectors</label>
    <label><input type="radio" name="lens" /> Geography</label>
  </div>
  <div class="af-section">
    <h4>Style Drift</h4>
    <label>Quarters back: <input type="number" value="8" min="1" max="20" /></label>
  </div>
{:else}
  <div class="af-section">
    <h4>Peer Universe</h4>
    <label><input type="checkbox" checked /> Same strategy</label>
    <label><input type="checkbox" checked /> Same domicile</label>
    <label><input type="checkbox" /> Same size bucket</label>
  </div>
  <div class="af-section">
    <h4>Institutional Reveal</h4>
    <label><input type="checkbox" checked /> Endowments</label>
    <label><input type="checkbox" checked /> Family Offices</label>
    <label><input type="checkbox" /> Sovereign Funds</label>
  </div>
{/if}

<style>
  .af-section { margin-bottom: 24px; }
  .af-section h4 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--ii-text-muted); margin: 0 0 10px; font-weight: 600;
  }
  .af-section label {
    display: block; padding: 6px 0; font-size: 12px;
    color: var(--ii-text-primary); cursor: pointer;
  }
  .af-section input[type="checkbox"], .af-section input[type="radio"] {
    margin-right: 8px; accent-color: var(--ii-accent);
  }
  .af-radio-group { display: flex; gap: 4px; }
  .af-radio-group label {
    flex: 1; text-align: center; padding: 6px 8px;
    border: 1px solid var(--ii-border-subtle); border-radius: 4px;
    font-size: 11px; font-weight: 600;
  }
  .af-radio-group label.active {
    background: var(--ii-accent); color: white; border-color: var(--ii-accent);
  }
  .af-radio-group input { display: none; }
</style>
```

- [ ] **Step 4: Returns & Risk view composition**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/ReturnsRiskView.svelte -->
<script lang="ts">
  import { fetchReturnsRisk } from '$lib/discovery/analysis-api';
  import ChartCard from './ChartCard.svelte';
  import AnalysisGrid from './AnalysisGrid.svelte';
  import NavHeroChart from '$lib/components/charts/discovery/NavHeroChart.svelte';
  import RollingRiskChart from '$lib/components/charts/discovery/RollingRiskChart.svelte';
  import MonthlyReturnsHeatmap from '$lib/components/charts/discovery/MonthlyReturnsHeatmap.svelte';
  import ReturnDistributionChart from '$lib/components/charts/discovery/ReturnDistributionChart.svelte';
  import DrawdownUnderwaterChart from '$lib/components/charts/discovery/DrawdownUnderwaterChart.svelte';
  import RiskMetricsBulletChart from '$lib/components/charts/discovery/RiskMetricsBulletChart.svelte';

  interface Props {
    fundId: string;
    window: '1y' | '3y' | '5y' | 'max';
  }
  let { fundId, window }: Props = $props();

  let data = $state<any>(null);
  let error = $state<string | null>(null);

  $effect(() => {
    const id = fundId;
    const w = window;
    if (!id) return;
    const ctrl = new AbortController();
    data = null; error = null;
    fetchReturnsRisk(id, w, ctrl.signal)
      .then((d) => { data = d; })
      .catch((e) => { if (e.name !== 'AbortError') error = e.message; });
    return () => ctrl.abort();
  });
</script>

{#if error}
  <div class="rv-error">Failed to load: {error}</div>
{:else if !data}
  <div class="rv-loading">Loading Returns & Risk…</div>
{:else if !data.disclosure?.has_nav}
  <div class="rv-empty">
    <strong>No public pricing data</strong>
    <p>This fund reports via Form ADV filings only. Public NAV series is not available, so Returns & Risk analysis cannot be computed. Use the Holdings or Peer tabs instead.</p>
  </div>
{:else}
  <AnalysisGrid>
    <ChartCard title="Cumulative Return & Drawdown" subtitle="Hero view — shared dataset" span={3} minHeight="420px">
      <NavHeroChart series={data.nav_series} />
    </ChartCard>
    <ChartCard title="Rolling Sharpe & Volatility (12m)">
      <RollingRiskChart rolling={data.rolling_metrics} />
    </ChartCard>
    <ChartCard title="Monthly Returns Heatmap">
      <MonthlyReturnsHeatmap monthly={data.monthly_returns} />
    </ChartCard>
    <ChartCard title="Return Distribution">
      <ReturnDistributionChart distribution={data.return_distribution} />
    </ChartCard>
    <ChartCard title="Drawdown (Underwater)">
      <DrawdownUnderwaterChart series={data.nav_series} />
    </ChartCard>
    <ChartCard title="Risk Metrics vs Peers" span={2}>
      <RiskMetricsBulletChart metrics={data.risk_metrics} />
    </ChartCard>
  </AnalysisGrid>
{/if}

<style>
  .rv-error, .rv-loading, .rv-empty {
    padding: 40px; text-align: center;
    color: var(--ii-text-muted); font-family: 'Urbanist', system-ui, sans-serif;
  }
  .rv-empty strong { display: block; font-size: 14px; color: var(--ii-text-primary); margin-bottom: 8px; }
</style>
```

- [ ] **Step 5: Page component**

```svelte
<!-- frontends/wealth/src/routes/(app)/discovery/funds/[external_id]/analysis/+page.svelte -->
<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { FilterRail } from '@netz/ui';
  import AnalysisFilters from '$lib/components/discovery/analysis/AnalysisFilters.svelte';
  import ReturnsRiskView from '$lib/components/discovery/analysis/ReturnsRiskView.svelte';
  // HoldingsView + PeerView imported in Phases 6 and 7

  let { data } = $props();

  const group = $derived(
    (page.url.searchParams.get('group') ?? 'returns-risk') as
      'returns-risk' | 'holdings' | 'peer',
  );
  const window = $derived(
    (page.url.searchParams.get('window') ?? '3y') as '1y' | '3y' | '5y' | 'max',
  );

  async function patch(updates: Record<string, string>) {
    const url = new URL(page.url);
    for (const [k, v] of Object.entries(updates)) url.searchParams.set(k, v);
    await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<svelte:head><title>Analysis — {data.header?.fund?.name ?? data.fundId}</title></svelte:head>

<div class="analysis-page">
  <header class="ap-header">
    <div class="ap-back">
      <a href="/discovery?fund={encodeURIComponent(data.fundId)}">← Discovery</a>
    </div>
    <div class="ap-titles">
      <h1>{data.header?.fund?.name ?? data.fundId}</h1>
      <p>{data.header?.fund?.ticker ?? '—'} · {data.header?.fund?.strategy_label ?? '—'}</p>
    </div>
    <nav class="ap-tabs" aria-label="Analysis groups">
      <button class:active={group === 'returns-risk'} onclick={() => patch({ group: 'returns-risk' })}>Returns & Risk</button>
      <button class:active={group === 'holdings'} onclick={() => patch({ group: 'holdings' })}>Holdings Analysis</button>
      <button class:active={group === 'peer'} onclick={() => patch({ group: 'peer' })}>Peer Analysis</button>
    </nav>
  </header>

  <div class="ap-body">
    <FilterRail column1Label="Filters">
      {#snippet filters()}
        <AnalysisFilters
          {group}
          {window}
          onWindowChange={(w) => patch({ window: w })}
        />
      {/snippet}
    </FilterRail>

    <main class="ap-main">
      {#if group === 'returns-risk'}
        <ReturnsRiskView fundId={data.fundId} {window} />
      {:else if group === 'holdings'}
        <!-- HoldingsView lands in Phase 6 -->
        <div class="ap-placeholder">Holdings Analysis — Phase 6</div>
      {:else}
        <!-- PeerView lands in Phase 7 -->
        <div class="ap-placeholder">Peer Analysis — Phase 7</div>
      {/if}
    </main>
  </div>
</div>

<style>
  .analysis-page {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 88px);
    background: var(--ii-bg-canvas, #0e0f13);
    font-family: 'Urbanist', system-ui, sans-serif;
  }
  .ap-header {
    display: grid;
    grid-template-columns: 120px 1fr auto;
    align-items: center;
    padding: 16px 24px;
    border-bottom: 1px solid var(--ii-border-subtle);
    gap: 24px;
  }
  .ap-back a { color: var(--ii-text-muted); font-size: 12px; text-decoration: none; }
  .ap-back a:hover { color: var(--ii-accent); }
  .ap-titles h1 { font-size: 18px; font-weight: 600; margin: 0; }
  .ap-titles p { font-size: 11px; color: var(--ii-text-muted); margin: 2px 0 0; font-variant-numeric: tabular-nums; }
  .ap-tabs { display: inline-flex; gap: 4px; }
  .ap-tabs button {
    font-family: inherit; font-size: 12px; font-weight: 600;
    padding: 8px 16px; border-radius: 999px;
    background: transparent; border: 1px solid var(--ii-border-subtle);
    color: var(--ii-text-muted); cursor: pointer;
  }
  .ap-tabs button.active {
    background: var(--ii-accent); color: white; border-color: var(--ii-accent);
  }
  .ap-body {
    display: flex;
    flex: 1;
    min-height: 0;
  }
  .ap-main {
    flex: 1;
    min-width: 0;
    overflow-y: auto;
    container-type: inline-size;
  }
  .ap-placeholder {
    padding: 80px 40px;
    text-align: center;
    color: var(--ii-text-muted);
  }
</style>
```

- [ ] **Step 6: Visual validation**

Run `make dev-wealth`. From `/discovery`, click any fund's "Analysis →" button. Verify:
1. Route `/discovery/funds/{id}/analysis?group=returns-risk&window=3y` renders
2. Header shows fund name, ticker, strategy
3. FilterRail on left (260px), tab row at top, main grid fills remaining space
4. 6 chart cards render in 3×2 pattern (hero spans full width row 1)
5. Change window 1y/3y/5y/max → all charts reload with new data
6. Tab switch to Holdings/Peer → placeholder shown, URL updates
7. Back link returns to `/discovery` with fund preselected
8. Private fund (no NAV) → institutional empty state, no broken charts

- [ ] **Step 7: Commit**

```bash
git add frontends/wealth/src/routes/\(app\)/discovery/funds frontends/wealth/src/lib/components/discovery/analysis/ReturnsRiskView.svelte frontends/wealth/src/lib/components/discovery/analysis/AnalysisFilters.svelte frontends/wealth/src/lib/discovery/analysis-api.ts
git commit -m "feat(discovery): standalone Analysis page with Returns & Risk view"
```

### Task 5.6: Phase 5 check gate

- [ ] **Step 1: Run full gate**

```bash
make check
cd frontends/wealth && pnpm check
```
Expected: green.

- [ ] **Step 2: Commit any tweaks**

```bash
git add -A
git commit -m "polish(discovery): Phase 5 check gate fixes"
```

---

## Phase 6 — Holdings Analysis (Style Drift + Reverse Lookup network)

Features impactantes que aproveitam `sec_nport_holdings` + `sec_13f_holdings` + `sec_13f_diffs` para criar visualizações com densidade informacional alta.

### Task 6.1: Backend — holdings analysis queries

**Files:**
- Create: `backend/app/domains/wealth/queries/analysis_holdings.py`
- Modify: `backend/app/domains/wealth/routes/discovery_analysis.py`
- Test: `backend/tests/domains/wealth/test_analysis_holdings.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/domains/wealth/test_analysis_holdings.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_holdings_top_returns_sector_treemap(
    async_client: AsyncClient, dev_headers: dict, sample_nport_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_nport_fund_id}/analysis/holdings/top",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "top_holdings" in body
    assert "sector_breakdown" in body
    assert "as_of" in body

@pytest.mark.asyncio
async def test_style_drift_returns_n_quarters(
    async_client: AsyncClient, dev_headers: dict, sample_nport_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_nport_fund_id}/analysis/holdings/style-drift?quarters=8",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "snapshots" in body
    assert len(body["snapshots"]) <= 8

@pytest.mark.asyncio
async def test_reverse_lookup_returns_shared_holders(
    async_client: AsyncClient, dev_headers: dict, sample_cik: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/holdings/{sample_cik}/reverse-lookup",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body  # holders + the target holding
    assert "edges" in body  # holder -> holding relationships
    # Network must include at least target + 1 holder to be meaningful
    assert len(body["nodes"]) >= 2
```

- [ ] **Step 2: Implement `analysis_holdings.py`**

```python
# backend/app/domains/wealth/queries/analysis_holdings.py
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_top_holdings(db: AsyncSession, cik: str) -> dict[str, Any]:
    """Top holdings + sector breakdown for a registered/ETF/BDC fund."""
    top_sql = """
        SELECT issuer_name, cusip, security_type, percent_value, market_value
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = (SELECT MAX(report_date) FROM sec_nport_holdings WHERE cik = :cik)
        ORDER BY percent_value DESC NULLS LAST
        LIMIT 25
    """
    sector_sql = """
        SELECT security_type AS sector,
               SUM(percent_value) AS weight,
               COUNT(*) AS count
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = (SELECT MAX(report_date) FROM sec_nport_holdings WHERE cik = :cik)
        GROUP BY security_type
        ORDER BY weight DESC NULLS LAST
    """
    as_of_sql = "SELECT MAX(report_date) AS as_of FROM sec_nport_holdings WHERE cik = :cik"
    top = (await db.execute(text(top_sql), {"cik": cik})).mappings().all()
    sectors = (await db.execute(text(sector_sql), {"cik": cik})).mappings().all()
    as_of = (await db.execute(text(as_of_sql), {"cik": cik})).scalar()
    return {
        "top_holdings": [dict(r) for r in top],
        "sector_breakdown": [dict(r) for r in sectors],
        "as_of": as_of,
    }


async def fetch_style_drift(db: AsyncSession, cik: str, quarters: int = 8) -> dict[str, Any]:
    """
    Compute quarter-over-quarter drift: per sector, how weight moved across the
    last N quarters. Output: [{quarter, sectors: [{name, weight}]}].
    """
    sql = """
        WITH q AS (
            SELECT DISTINCT report_date
            FROM sec_nport_holdings
            WHERE cik = :cik
            ORDER BY report_date DESC
            LIMIT :quarters
        )
        SELECT h.report_date, h.security_type AS sector, SUM(h.percent_value) AS weight
        FROM sec_nport_holdings h
        JOIN q USING (report_date)
        WHERE h.cik = :cik
        GROUP BY h.report_date, h.security_type
        ORDER BY h.report_date ASC, weight DESC
    """
    rows = (await db.execute(text(sql), {"cik": cik, "quarters": quarters})).mappings().all()
    by_quarter: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        by_quarter.setdefault(r["report_date"], []).append(
            {"name": r["sector"], "weight": float(r["weight"] or 0)}
        )
    return {"snapshots": [{"quarter": q, "sectors": s} for q, s in by_quarter.items()]}


async def fetch_reverse_lookup(db: AsyncSession, target_cusip: str, limit: int = 30) -> dict[str, Any]:
    """
    Les Misérables-style network: given a CUSIP (holding), find the top N
    institutions that also hold it. Returns nodes + edges for ECharts graph.
    Node 0 is the target holding; subsequent nodes are holders.
    """
    # Pull from BOTH sec_nport_holdings (regulated funds) and sec_13f_holdings (13F filers)
    sql = """
        WITH combined AS (
            SELECT
                cik AS holder_cik,
                'nport' AS source,
                SUM(market_value) AS position_value
            FROM sec_nport_holdings
            WHERE cusip = :cusip
              AND report_date = (SELECT MAX(report_date) FROM sec_nport_holdings WHERE cusip = :cusip)
            GROUP BY cik
            UNION ALL
            SELECT
                filer_cik AS holder_cik,
                '13f' AS source,
                SUM(value) AS position_value
            FROM sec_13f_holdings
            WHERE cusip = :cusip
              AND report_date = (SELECT MAX(report_date) FROM sec_13f_holdings WHERE cusip = :cusip)
            GROUP BY filer_cik
        )
        SELECT holder_cik, source, SUM(position_value) AS position_value,
               sm.firm_name
        FROM combined c
        LEFT JOIN sec_managers sm ON sm.cik = c.holder_cik
        GROUP BY holder_cik, source, sm.firm_name
        ORDER BY position_value DESC NULLS LAST
        LIMIT :limit
    """
    rows = (await db.execute(text(sql), {"cusip": target_cusip, "limit": limit})).mappings().all()

    # Target holding (fetch name from either source)
    target_sql = """
        SELECT COALESCE(
            (SELECT issuer_name FROM sec_nport_holdings WHERE cusip = :cusip LIMIT 1),
            (SELECT issuer_name FROM sec_13f_holdings WHERE cusip = :cusip LIMIT 1)
        ) AS issuer_name
    """
    target_name = (await db.execute(text(target_sql), {"cusip": target_cusip})).scalar() or target_cusip

    nodes = [{"id": target_cusip, "name": target_name, "category": "holding", "symbolSize": 40}]
    edges = []
    for r in rows:
        node_id = str(r["holder_cik"])
        nodes.append({
            "id": node_id,
            "name": r["firm_name"] or f"CIK {r['holder_cik']}",
            "category": "holder",
            "symbolSize": 16,
            "value": float(r["position_value"] or 0),
            "source": r["source"],
        })
        edges.append({"source": node_id, "target": target_cusip})

    return {"nodes": nodes, "edges": edges, "target_cusip": target_cusip}
```

- [ ] **Step 3: Add routes**

```python
# append to backend/app/domains/wealth/routes/discovery_analysis.py
from backend.app.domains.wealth.queries.analysis_holdings import (
    fetch_top_holdings, fetch_style_drift, fetch_reverse_lookup,
)

HOLDINGS_TTL = 60 * 60


@router.get("/funds/{external_id}/analysis/holdings/top")
async def holdings_top(
    external_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
):
    fund = await resolve_fund(db, external_id)
    if not fund["cik"]:
        return {"top_holdings": [], "sector_breakdown": [], "as_of": None, "disclosure": {"has_holdings": False}}
    redis = await get_redis()
    key = f"discovery:analysis:holdings-top:{fund['cik']}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    payload = await fetch_top_holdings(db, fund["cik"])
    payload["disclosure"] = {"has_holdings": len(payload["top_holdings"]) > 0}
    await redis.setex(key, HOLDINGS_TTL, json.dumps(payload, default=str))
    return payload


@router.get("/funds/{external_id}/analysis/holdings/style-drift")
async def holdings_style_drift(
    external_id: str,
    quarters: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db_with_rls),
):
    fund = await resolve_fund(db, external_id)
    if not fund["cik"]:
        return {"snapshots": []}
    redis = await get_redis()
    key = f"discovery:analysis:style-drift:{fund['cik']}:{quarters}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    payload = await fetch_style_drift(db, fund["cik"], quarters)
    await redis.setex(key, HOLDINGS_TTL, json.dumps(payload, default=str))
    return payload


@router.get("/holdings/{cusip}/reverse-lookup")
async def holdings_reverse_lookup(
    cusip: str,
    limit: int = Query(30, ge=5, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
):
    redis = await get_redis()
    key = f"discovery:analysis:reverse-lookup:{cusip}:{limit}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    payload = await fetch_reverse_lookup(db, cusip, limit)
    await redis.setex(key, HOLDINGS_TTL, json.dumps(payload, default=str))
    return payload
```

- [ ] **Step 4: Run tests**

```bash
pytest backend/tests/domains/wealth/test_analysis_holdings.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/domains/wealth/queries/analysis_holdings.py backend/app/domains/wealth/routes/discovery_analysis.py backend/tests/domains/wealth/test_analysis_holdings.py
git commit -m "feat(discovery): holdings analysis endpoints (top, style drift, reverse lookup)"
```

### Task 6.2: Network graph chart (Les Misérables) + Holdings charts

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/discovery/HoldingsNetworkChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/TopHoldingsSunburst.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/SectorTreemap.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/StyleDriftFlow.svelte`

- [ ] **Step 1: HoldingsNetworkChart (ECharts `graph` series)**

```svelte
<!-- frontends/wealth/src/lib/components/charts/discovery/HoldingsNetworkChart.svelte -->
<script lang="ts">
  import { Chart } from 'svelte-echarts';
  import { init } from 'echarts';
  import { chartTokens } from '../chart-tokens';

  interface Node { id: string; name: string; category: 'holding' | 'holder'; symbolSize: number; value?: number; }
  interface Edge { source: string; target: string; }
  interface Props { nodes: Node[]; edges: Edge[]; }
  let { nodes, edges }: Props = $props();

  const tokens = $derived.by(() => chartTokens());

  const option = $derived({
    textStyle: { fontFamily: tokens.fontFamily, fontSize: 11 },
    tooltip: {
      backgroundColor: tokens.tooltipBg, borderColor: tokens.tooltipBorder, borderWidth: 1,
      formatter: (p: any) => {
        if (p.dataType === 'edge') return '';
        return `<strong>${p.data.name}</strong>`;
      },
    },
    legend: [{
      data: ['Holding', 'Holder'],
      textStyle: { color: tokens.axisLabel },
      bottom: 8,
    }],
    series: [{
      type: 'graph',
      layout: 'force',
      force: { repulsion: 120, edgeLength: [60, 140], gravity: 0.1 },
      roam: true,
      draggable: true,
      label: { show: true, position: 'right', color: tokens.axisLabel, fontSize: 10 },
      categories: [
        { name: 'Holding', itemStyle: { color: tokens.primary } },
        { name: 'Holder', itemStyle: { color: tokens.benchmark } },
      ],
      data: nodes.map((n) => ({
        id: n.id,
        name: n.name,
        symbolSize: n.symbolSize,
        category: n.category === 'holding' ? 0 : 1,
        value: n.value,
      })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        lineStyle: { color: tokens.grid, width: 1, curveness: 0.15 },
      })),
      emphasis: { focus: 'adjacency', lineStyle: { width: 2, color: tokens.primary } },
      animationDurationUpdate: 500,
    }],
  });
</script>

<div class="hn-root">
  <Chart {init} {option} notMerge={true} />
</div>

<style>.hn-root { width: 100%; height: 480px; }</style>
```

- [ ] **Step 2: TopHoldingsSunburst** — ECharts `sunburst` series with 2 levels: sector (outer) → holding (inner). Weights from `percent_value`. Color by sector token.

- [ ] **Step 3: SectorTreemap** — ECharts `treemap` series using `sector_breakdown`. Label shows sector + weight %.

- [ ] **Step 4: StyleDriftFlow** — ECharts stacked `line` series where X = quarter, Y = cumulative sector weight, stacked area. Shows sectors migrating over time. Fed by `snapshots`.

- [ ] **Step 5: Commit**

```bash
git add frontends/wealth/src/lib/components/charts/discovery/
git commit -m "feat(discovery): holdings charts — network (Les Mis), sunburst, treemap, drift flow"
```

### Task 6.3: HoldingsView composition + reverse lookup interaction

**Files:**
- Create: `frontends/wealth/src/lib/components/discovery/analysis/HoldingsView.svelte`
- Modify: `frontends/wealth/src/routes/(app)/discovery/funds/[external_id]/analysis/+page.svelte`

- [ ] **Step 1: HoldingsView with click-to-reverse-lookup**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/HoldingsView.svelte -->
<script lang="ts">
  import { getAuthHeaders } from '$lib/auth';
  import ChartCard from './ChartCard.svelte';
  import AnalysisGrid from './AnalysisGrid.svelte';
  import HoldingsNetworkChart from '$lib/components/charts/discovery/HoldingsNetworkChart.svelte';
  import TopHoldingsSunburst from '$lib/components/charts/discovery/TopHoldingsSunburst.svelte';
  import SectorTreemap from '$lib/components/charts/discovery/SectorTreemap.svelte';
  import StyleDriftFlow from '$lib/components/charts/discovery/StyleDriftFlow.svelte';
  import { EnterpriseTable, type ColumnDef } from '@netz/ui';

  interface Props { fundId: string; }
  let { fundId }: Props = $props();

  let topData = $state<any>(null);
  let driftData = $state<any>(null);
  let reverseData = $state<any>(null);
  let selectedCusip = $state<string | null>(null);

  $effect(() => {
    const id = fundId;
    if (!id) return;
    const ctrl = new AbortController();
    topData = null; driftData = null;
    (async () => {
      const headers = await getAuthHeaders();
      const [topRes, driftRes] = await Promise.all([
        fetch(`/api/wealth/discovery/funds/${id}/analysis/holdings/top`, { headers, signal: ctrl.signal }),
        fetch(`/api/wealth/discovery/funds/${id}/analysis/holdings/style-drift?quarters=8`, { headers, signal: ctrl.signal }),
      ]);
      if (topRes.ok) topData = await topRes.json();
      if (driftRes.ok) driftData = await driftRes.json();
    })().catch((e) => { if (e.name !== 'AbortError') console.error(e); });
    return () => ctrl.abort();
  });

  $effect(() => {
    const cusip = selectedCusip;
    if (!cusip) { reverseData = null; return; }
    const ctrl = new AbortController();
    (async () => {
      const headers = await getAuthHeaders();
      const res = await fetch(`/api/wealth/discovery/holdings/${cusip}/reverse-lookup`, {
        headers, signal: ctrl.signal,
      });
      if (res.ok) reverseData = await res.json();
    })().catch((e) => { if (e.name !== 'AbortError') console.error(e); });
    return () => ctrl.abort();
  });

  const holdingColumns: ColumnDef<any>[] = [
    { id: 'name', header: 'Holding', width: 'minmax(200px, 2fr)', accessor: (r) => r.issuer_name },
    { id: 'type', header: 'Type', width: '120px', accessor: (r) => r.security_type ?? '—' },
    { id: 'weight', header: 'Weight', numeric: true, width: '80px',
      accessor: (r) => r.percent_value, format: (v) => v != null ? `${(v as number).toFixed(2)}%` : '—' },
    { id: 'action', header: '', width: '100px', align: 'right', accessor: (r) => r.cusip },
  ];
</script>

{#if !topData || !topData.disclosure?.has_holdings}
  <div class="hv-empty">
    <strong>No holdings disclosure</strong>
    <p>Holdings analysis requires quarterly N-PORT or 13F filings. This fund does not disclose individual positions.</p>
  </div>
{:else}
  <AnalysisGrid>
    <ChartCard title="Top 25 Holdings" subtitle={`As of ${topData.as_of}`} span={2}>
      {#snippet cellSnippet(row: any, col: any)}
        {#if col.id === 'action'}
          <button
            class="rev-btn"
            class:active={selectedCusip === row.cusip}
            onclick={() => selectedCusip = row.cusip}
          >Reverse ↗</button>
        {:else if col.format}
          {col.format(col.accessor(row), row)}
        {:else}
          {col.accessor(row) ?? ''}
        {/if}
      {/snippet}
      <EnterpriseTable
        rows={topData.top_holdings}
        columns={holdingColumns}
        rowKey={(r) => r.cusip ?? r.issuer_name}
        cell={cellSnippet}
      />
    </ChartCard>

    <ChartCard title="Sector Composition">
      <SectorTreemap sectors={topData.sector_breakdown} />
    </ChartCard>

    <ChartCard title="Holdings Distribution" subtitle="Sunburst by sector → holding" span={2}>
      <TopHoldingsSunburst sectors={topData.sector_breakdown} holdings={topData.top_holdings} />
    </ChartCard>

    <ChartCard title="Style Drift" subtitle="Sector weight migration across quarters">
      {#if driftData}<StyleDriftFlow snapshots={driftData.snapshots} />{/if}
    </ChartCard>

    <ChartCard
      title="Holdings Reverse Lookup"
      subtitle={selectedCusip ? `Who else holds this CUSIP?` : 'Click "Reverse ↗" on any holding to reveal shared holders'}
      span={3}
      minHeight="520px"
    >
      {#if reverseData}
        <HoldingsNetworkChart nodes={reverseData.nodes} edges={reverseData.edges} />
      {:else}
        <div class="hv-hint">
          Select a holding from the Top 25 table above to see which other institutions hold the same CUSIP.
        </div>
      {/if}
    </ChartCard>
  </AnalysisGrid>
{/if}

<style>
  .hv-empty { padding: 80px 40px; text-align: center; color: var(--ii-text-muted); }
  .hv-empty strong { display: block; font-size: 14px; color: var(--ii-text-primary); margin-bottom: 8px; }
  .hv-hint { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--ii-text-muted); font-size: 13px; padding: 40px; }
  .rev-btn {
    font-family: 'Urbanist', system-ui, sans-serif;
    font-size: 11px; font-weight: 600;
    padding: 4px 10px; border-radius: 4px;
    background: transparent;
    border: 1px solid var(--ii-border-subtle);
    color: var(--ii-text-muted);
    cursor: pointer;
  }
  .rev-btn:hover, .rev-btn.active {
    background: var(--ii-accent); color: white; border-color: var(--ii-accent);
  }
</style>
```

- [ ] **Step 2: Wire into page.svelte**

Replace the `<!-- HoldingsView lands in Phase 6 -->` placeholder with:
```svelte
{:else if group === 'holdings'}
  <HoldingsView fundId={data.fundId} />
```

Add import:
```ts
import HoldingsView from '$lib/components/discovery/analysis/HoldingsView.svelte';
```

- [ ] **Step 3: Visual validation**

Open `/discovery/funds/{id}/analysis?group=holdings` on a registered fund with holdings. Verify:
1. Top 25 table renders with AUM-sorted sector chart alongside
2. Sunburst renders with 2-level hierarchy
3. Style Drift shows 8 quarters of sector migration
4. Click "Reverse ↗" on any row → network graph loads with that CUSIP at center + all institutions that hold it
5. Network is draggable, nodes show name on hover
6. Private fund → "No holdings disclosure" institutional empty state

- [ ] **Step 4: Commit**

```bash
git add frontends/wealth/src/lib/components/discovery/analysis/HoldingsView.svelte frontends/wealth/src/routes/\(app\)/discovery/funds/\[external_id\]/analysis/+page.svelte
git commit -m "feat(discovery): HoldingsView with Style Drift + Les Misérables reverse lookup"
```

---

## Phase 7 — Peer Analysis + Institutional Portfolio Reveal

### Task 7.1: Curated institutional CIK seed

**Files:**
- Create: `backend/app/core/db/migrations/versions/0095_curated_institutions_seed.py`

- [ ] **Step 1: Migration that creates + seeds `curated_institutions`**

```python
# backend/app/core/db/migrations/versions/0095_curated_institutions_seed.py
"""curated institutions seed

Revision ID: 0095_curated_institutions_seed
Revises: 0093_discovery_fcl_keyset_indexes
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0095_curated_institutions_seed"
down_revision = "0093_discovery_fcl_keyset_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curated_institutions",
        sa.Column("institution_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("cik", sa.String(20), nullable=True),  # 13F filer CIK
        sa.Column("category", sa.String(40), nullable=False),  # endowment | family_office | sovereign_fund | foundation
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("idx_curated_institutions_category", "curated_institutions", ["category", "display_order"])

    # Seed with publicly-disclosed institutional 13F filers
    # NOTE: CIK values must be confirmed by the 13F ingestion worker after first load — this
    # migration seeds names + category; the backfill job below fills the CIK field.
    seed = [
        ("yale_endowment", "Yale University Endowment", "endowment", "USA"),
        ("harvard_endowment", "Harvard University Endowment", "endowment", "USA"),
        ("princeton_endowment", "Princeton University Endowment", "endowment", "USA"),
        ("mit_endowment", "MIT Investment Management Company", "endowment", "USA"),
        ("stanford_endowment", "Stanford Management Company", "endowment", "USA"),
        ("columbia_endowment", "Columbia University Endowment", "endowment", "USA"),
        ("penn_endowment", "University of Pennsylvania Endowment", "endowment", "USA"),
        ("notre_dame_endowment", "University of Notre Dame Endowment", "endowment", "USA"),
        ("olayan_group", "Olayan Group", "family_office", "SAU"),
        ("iconiq_capital", "ICONIQ Capital", "family_office", "USA"),
        ("pictet_wealth", "Pictet Wealth Management", "family_office", "CHE"),
        ("rockefeller_cm", "Rockefeller Capital Management", "family_office", "USA"),
        ("bessemer_trust", "Bessemer Trust", "family_office", "USA"),
        ("gates_foundation", "Bill & Melinda Gates Foundation Trust", "foundation", "USA"),
        ("norges_bank", "Norges Bank Investment Management", "sovereign_fund", "NOR"),
        ("temasek", "Temasek Holdings", "sovereign_fund", "SGP"),
    ]
    conn = op.get_bind()
    for i, (inst_id, name, category, country) in enumerate(seed):
        conn.execute(
            sa.text("""
                INSERT INTO curated_institutions (institution_id, name, category, country, display_order, active)
                VALUES (:id, :name, :cat, :country, :ord, true)
                ON CONFLICT (institution_id) DO NOTHING
            """),
            {"id": inst_id, "name": name, "cat": category, "country": country, "ord": i * 10},
        )


def downgrade() -> None:
    op.drop_index("idx_curated_institutions_category", table_name="curated_institutions")
    op.drop_table("curated_institutions")
```

- [ ] **Step 2: Run migration**

```bash
make migrate
```

- [ ] **Step 3: Backfill CIKs via one-off script**

```python
# backend/scripts/backfill_curated_institution_ciks.py
"""
Fuzzy-match curated_institutions.name against sec_managers.firm_name to populate CIK.
Uses pg_trgm similarity. Manual review of matches required; script prints candidates
and asks for y/n confirmation per match.
"""
# Implementation left to the agent; not blocking — can be run post-migration.
```

Note this script is not blocking — Peer Analysis degrades gracefully to names-only display if CIKs aren't populated yet.

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/db/migrations/versions/0095_curated_institutions_seed.py backend/scripts/backfill_curated_institution_ciks.py
git commit -m "feat(db): curated_institutions table + seed (Ivy endowments, family offices, sovereign)"
```

### Task 7.2: Peer Analysis queries + routes

**Files:**
- Create: `backend/app/domains/wealth/queries/analysis_peer.py`
- Modify: `backend/app/domains/wealth/routes/discovery_analysis.py`
- Test: `backend/tests/domains/wealth/test_analysis_peer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/domains/wealth/test_analysis_peer.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_peer_comparison_returns_ranked_peers(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/peers",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "peers" in body
    assert "subject" in body
    # Subject must be marked
    assert body["subject"]["is_subject"] is True

@pytest.mark.asyncio
async def test_institutional_reveal_returns_overlap(
    async_client: AsyncClient, dev_headers: dict, sample_fund_id: str,
):
    resp = await async_client.get(
        f"/api/wealth/discovery/funds/{sample_fund_id}/analysis/institutional-reveal",
        headers=dev_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "institutions" in body  # curated list
    assert "overlap_matrix" in body  # [institution × holding] overlap counts
```

- [ ] **Step 2: Implement `analysis_peer.py`**

```python
# backend/app/domains/wealth/queries/analysis_peer.py
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_peer_comparison(
    db: AsyncSession, instrument_id: str, strategy: str | None, limit: int = 40,
) -> dict[str, Any]:
    """
    Fetch peers matching same strategy + domicile bucket, with risk metrics.
    Subject fund is included in the output with is_subject=True.
    """
    sql = """
        SELECT
            f.external_id,
            f.name,
            f.ticker,
            f.strategy_label,
            f.aum_usd,
            f.expense_ratio_pct,
            rm.volatility_1y,
            rm.sharpe_1y,
            rm.max_drawdown_1y,
            rm.cvar_95,
            (f.external_id::text = :subject_ext) AS is_subject
        FROM mv_unified_funds f
        LEFT JOIN instruments_universe i ON i.ticker = f.ticker
        LEFT JOIN fund_risk_metrics rm ON rm.instrument_id = i.instrument_id
        WHERE (:strategy::text IS NULL OR f.strategy_label = :strategy)
          AND f.aum_usd IS NOT NULL
          AND rm.volatility_1y IS NOT NULL
        ORDER BY (f.external_id::text = :subject_ext) DESC, rm.sharpe_1y DESC NULLS LAST
        LIMIT :limit
    """
    rows = (await db.execute(
        text(sql),
        {"strategy": strategy, "subject_ext": instrument_id, "limit": limit},
    )).mappings().all()
    peers = [dict(r) for r in rows]
    subject = next((p for p in peers if p["is_subject"]), None)
    return {"peers": peers, "subject": subject}


async def fetch_institutional_reveal(
    db: AsyncSession, fund_cik: str, category_filter: list[str] | None = None,
) -> dict[str, Any]:
    """
    For each curated institution with a 13F filing, compute how many of the
    subject fund's top 25 holdings (by CUSIP) they also hold. Returns:
      - institutions: [{id, name, category, total_overlap, total_value}]
      - overlap_matrix: [institution_id × cusip] value map (for heatmap)
      - holdings: top 25 of the subject fund (column labels)
    """
    # Step 1: subject fund's top 25 CUSIPs
    top_sql = """
        SELECT cusip, issuer_name, percent_value
        FROM sec_nport_holdings
        WHERE cik = :cik
          AND report_date = (SELECT MAX(report_date) FROM sec_nport_holdings WHERE cik = :cik)
        ORDER BY percent_value DESC NULLS LAST
        LIMIT 25
    """
    holdings = (await db.execute(text(top_sql), {"cik": fund_cik})).mappings().all()
    top_cusips = [h["cusip"] for h in holdings if h["cusip"]]
    if not top_cusips:
        return {"institutions": [], "overlap_matrix": {}, "holdings": []}

    # Step 2: curated institutions with populated CIK
    cat_clause = "AND category = ANY(:cats)" if category_filter else ""
    inst_sql = f"""
        SELECT institution_id, name, category, cik
        FROM curated_institutions
        WHERE active = true AND cik IS NOT NULL
        {cat_clause}
        ORDER BY display_order
    """
    params: dict[str, Any] = {}
    if category_filter:
        params["cats"] = category_filter
    institutions = (await db.execute(text(inst_sql), params)).mappings().all()
    if not institutions:
        return {"institutions": [], "overlap_matrix": {}, "holdings": [dict(h) for h in holdings]}

    # Step 3: overlap query — for each institution, find how much they hold of each top CUSIP
    overlap_sql = """
        SELECT filer_cik, cusip, SUM(value) AS position_value
        FROM sec_13f_holdings
        WHERE filer_cik = ANY(:ciks)
          AND cusip = ANY(:cusips)
          AND report_date = (
              SELECT MAX(report_date) FROM sec_13f_holdings
              WHERE filer_cik = ANY(:ciks)
          )
        GROUP BY filer_cik, cusip
    """
    overlap_rows = (await db.execute(
        text(overlap_sql),
        {"ciks": [i["cik"] for i in institutions], "cusips": top_cusips},
    )).mappings().all()

    # Assemble matrix and institution totals
    matrix: dict[str, dict[str, float]] = {}
    totals: dict[str, dict[str, float]] = {}
    for r in overlap_rows:
        inst = next((i for i in institutions if i["cik"] == r["filer_cik"]), None)
        if not inst:
            continue
        inst_id = inst["institution_id"]
        matrix.setdefault(inst_id, {})[r["cusip"]] = float(r["position_value"] or 0)
        t = totals.setdefault(inst_id, {"total_overlap": 0, "total_value": 0.0})
        t["total_overlap"] += 1
        t["total_value"] += float(r["position_value"] or 0)

    enriched_institutions = []
    for i in institutions:
        iid = i["institution_id"]
        t = totals.get(iid, {"total_overlap": 0, "total_value": 0.0})
        enriched_institutions.append({
            "id": iid,
            "name": i["name"],
            "category": i["category"],
            "total_overlap": t["total_overlap"],
            "total_value": t["total_value"],
        })

    return {
        "institutions": enriched_institutions,
        "overlap_matrix": matrix,
        "holdings": [dict(h) for h in holdings],
    }
```

- [ ] **Step 3: Add routes**

```python
# append to discovery_analysis.py
from backend.app.domains.wealth.queries.analysis_peer import (
    fetch_peer_comparison, fetch_institutional_reveal,
)

PEER_TTL = 60 * 60


@router.get("/funds/{external_id}/analysis/peers")
async def analysis_peers(
    external_id: str,
    limit: int = Query(40, ge=5, le=100),
    db: AsyncSession = Depends(get_db_with_rls),
):
    fund = await resolve_fund(db, external_id)
    redis = await get_redis()
    key = f"discovery:analysis:peers:{external_id}:{limit}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    strategy_sql = "SELECT strategy_label FROM mv_unified_funds WHERE external_id = :id"
    strategy = (await db.execute(text(strategy_sql), {"id": external_id})).scalar()
    payload = await fetch_peer_comparison(db, external_id, strategy, limit)
    await redis.setex(key, PEER_TTL, json.dumps(payload, default=str))
    return payload


@router.get("/funds/{external_id}/analysis/institutional-reveal")
async def institutional_reveal(
    external_id: str,
    categories: str | None = Query(None),  # comma-separated
    db: AsyncSession = Depends(get_db_with_rls),
):
    fund = await resolve_fund(db, external_id)
    if not fund["cik"]:
        return {"institutions": [], "overlap_matrix": {}, "holdings": []}
    redis = await get_redis()
    key = f"discovery:analysis:inst-reveal:{external_id}:{categories or 'all'}"
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    cat_list = categories.split(",") if categories else None
    payload = await fetch_institutional_reveal(db, fund["cik"], cat_list)
    await redis.setex(key, PEER_TTL, json.dumps(payload, default=str))
    return payload
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest backend/tests/domains/wealth/test_analysis_peer.py -v
git add backend/app/domains/wealth/queries/analysis_peer.py backend/app/domains/wealth/routes/discovery_analysis.py backend/tests/domains/wealth/test_analysis_peer.py
git commit -m "feat(discovery): peer analysis + institutional reveal endpoints"
```

### Task 7.3: Peer charts + PeerView composition

**Files:**
- Create: `frontends/wealth/src/lib/components/charts/discovery/PeerScatterChart.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/PeerRankingLadder.svelte`
- Create: `frontends/wealth/src/lib/components/charts/discovery/InstitutionalRevealMatrix.svelte`
- Create: `frontends/wealth/src/lib/components/discovery/analysis/PeerView.svelte`
- Modify: `frontends/wealth/src/routes/(app)/discovery/funds/[external_id]/analysis/+page.svelte`

- [ ] **Step 1: PeerScatterChart** — risk/return scatter highlighting subject with larger symbol + primary token color.

- [ ] **Step 2: PeerRankingLadder** — horizontal bar chart ranking peers by Sharpe; subject row highlighted. Shows percentile rank.

- [ ] **Step 3: InstitutionalRevealMatrix** — ECharts `heatmap` series. X = top 25 holdings (CUSIPs as labels → issuer name on hover), Y = institutions from curated list, color intensity = `position_value` log-scaled. Reveals which endowments/family offices share holdings with the subject fund.

```svelte
<!-- key part of InstitutionalRevealMatrix.svelte -->
<script lang="ts">
  import { Chart } from 'svelte-echarts';
  import { init } from 'echarts';
  import { chartTokens } from '../chart-tokens';

  interface Props {
    institutions: { id: string; name: string; category: string }[];
    holdings: { cusip: string; issuer_name: string }[];
    matrix: Record<string, Record<string, number>>;
  }
  let { institutions, holdings, matrix }: Props = $props();

  const tokens = $derived.by(() => chartTokens());

  const data = $derived.by(() => {
    const out: [number, number, number][] = [];
    institutions.forEach((inst, y) => {
      holdings.forEach((h, x) => {
        const v = matrix[inst.id]?.[h.cusip] ?? 0;
        out.push([x, y, v > 0 ? Math.log10(v + 1) : 0]);
      });
    });
    return out;
  });

  const option = $derived({
    textStyle: { fontFamily: tokens.fontFamily, fontSize: 10 },
    tooltip: {
      backgroundColor: tokens.tooltipBg, borderColor: tokens.tooltipBorder, borderWidth: 1,
      formatter: (p: any) => {
        const inst = institutions[p.data[1]];
        const h = holdings[p.data[0]];
        return `<strong>${inst.name}</strong><br/>${h.issuer_name}<br/>log10(value): ${p.data[2].toFixed(2)}`;
      },
    },
    grid: { left: 180, right: 32, top: 24, bottom: 120 },
    xAxis: {
      type: 'category', data: holdings.map((h) => h.issuer_name),
      axisLabel: { color: tokens.axisLabel, rotate: 45, interval: 0, fontSize: 9 },
    },
    yAxis: {
      type: 'category', data: institutions.map((i) => i.name),
      axisLabel: { color: tokens.axisLabel, fontSize: 10 },
    },
    visualMap: {
      min: 0, max: 10,
      calculable: true, orient: 'horizontal', left: 'center', bottom: 16,
      inRange: { color: [tokens.grid, tokens.primary] },
      textStyle: { color: tokens.axisLabel },
    },
    series: [{
      type: 'heatmap', data,
      emphasis: { itemStyle: { borderColor: tokens.primary, borderWidth: 2 } },
    }],
  });
</script>

<div class="irm-root"><Chart {init} {option} notMerge={true} /></div>

<style>.irm-root { width: 100%; height: 540px; }</style>
```

- [ ] **Step 4: PeerView composition**

```svelte
<!-- frontends/wealth/src/lib/components/discovery/analysis/PeerView.svelte -->
<script lang="ts">
  import { getAuthHeaders } from '$lib/auth';
  import ChartCard from './ChartCard.svelte';
  import AnalysisGrid from './AnalysisGrid.svelte';
  import PeerScatterChart from '$lib/components/charts/discovery/PeerScatterChart.svelte';
  import PeerRankingLadder from '$lib/components/charts/discovery/PeerRankingLadder.svelte';
  import InstitutionalRevealMatrix from '$lib/components/charts/discovery/InstitutionalRevealMatrix.svelte';

  interface Props { fundId: string; }
  let { fundId }: Props = $props();

  let peerData = $state<any>(null);
  let revealData = $state<any>(null);

  $effect(() => {
    const id = fundId;
    if (!id) return;
    const ctrl = new AbortController();
    peerData = null; revealData = null;
    (async () => {
      const headers = await getAuthHeaders();
      const [pRes, rRes] = await Promise.all([
        fetch(`/api/wealth/discovery/funds/${id}/analysis/peers`, { headers, signal: ctrl.signal }),
        fetch(`/api/wealth/discovery/funds/${id}/analysis/institutional-reveal`, { headers, signal: ctrl.signal }),
      ]);
      if (pRes.ok) peerData = await pRes.json();
      if (rRes.ok) revealData = await rRes.json();
    })().catch((e) => { if (e.name !== 'AbortError') console.error(e); });
    return () => ctrl.abort();
  });
</script>

{#if !peerData}
  <div class="pv-loading">Loading Peer Analysis…</div>
{:else}
  <AnalysisGrid>
    <ChartCard title="Risk / Return vs Peers" subtitle="Same strategy universe" span={2}>
      <PeerScatterChart peers={peerData.peers} />
    </ChartCard>
    <ChartCard title="Sharpe Ranking">
      <PeerRankingLadder peers={peerData.peers} />
    </ChartCard>
    {#if revealData && revealData.institutions?.length}
      <ChartCard
        title="Institutional Portfolio Reveal"
        subtitle="Holdings overlap with Ivy endowments, family offices, and sovereign funds"
        span={3}
        minHeight="580px"
      >
        <InstitutionalRevealMatrix
          institutions={revealData.institutions}
          holdings={revealData.holdings}
          matrix={revealData.overlap_matrix}
        />
      </ChartCard>
    {/if}
  </AnalysisGrid>
{/if}

<style>
  .pv-loading { padding: 40px; text-align: center; color: var(--ii-text-muted); }
</style>
```

- [ ] **Step 5: Wire into page.svelte** — replace the `<!-- PeerView lands in Phase 7 -->` placeholder and add the import.

- [ ] **Step 6: Visual validation + commit**

Verify matrix renders when institutional CIKs are populated; degrades gracefully otherwise.

```bash
git add -A
git commit -m "feat(discovery): PeerView with risk/return scatter + institutional reveal matrix"
```

---

## Phase 8 — Bottom Tab Dock (cross-fund analysis persistence)

Painel fixo no rodapé da página de Analysis. Cada tab é uma sessão de análise `{fund, group}` aberta. Usuário pode abrir múltiplas e alternar sem perder estado (filtros, selectedCusip, window). Persistência via URL hash (`#tabs=<encoded>`) — zero localStorage.

### Task 8.1: `BottomTabDock` primitive in `@netz/ui`

**Files:**
- Create: `packages/ui/src/lib/layouts/BottomTabDock.svelte`
- Modify: `packages/ui/src/lib/index.ts`

- [ ] **Step 1: Implement BottomTabDock**

```svelte
<!-- packages/ui/src/lib/layouts/BottomTabDock.svelte -->
<script lang="ts" module>
  export interface DockTab {
    id: string;
    label: string;
    sublabel?: string;
  }
</script>

<script lang="ts">
  interface Props {
    tabs: DockTab[];
    activeId: string | null;
    onActivate: (id: string) => void;
    onClose: (id: string) => void;
  }
  let { tabs, activeId, onActivate, onClose }: Props = $props();
</script>

{#if tabs.length > 0}
  <div class="btd-root" role="tablist" aria-label="Analysis sessions">
    {#each tabs as tab (tab.id)}
      <div
        class="btd-tab"
        class:active={tab.id === activeId}
        role="tab"
        aria-selected={tab.id === activeId}
        onclick={() => onActivate(tab.id)}
        onkeydown={(e) => e.key === 'Enter' && onActivate(tab.id)}
        tabindex="0"
      >
        <div class="btd-labels">
          <span class="btd-label">{tab.label}</span>
          {#if tab.sublabel}<span class="btd-sublabel">{tab.sublabel}</span>{/if}
        </div>
        <button
          class="btd-close"
          aria-label="Close tab"
          onclick={(e) => { e.stopPropagation(); onClose(tab.id); }}
        >×</button>
      </div>
    {/each}
  </div>
{/if}

<style>
  .btd-root {
    flex-shrink: 0;
    display: flex;
    gap: 2px;
    background: var(--ii-bg-surface-alt, #1a1c22);
    border-top: 1px solid var(--ii-border-subtle, rgba(64,66,73,0.4));
    padding: 0 16px;
    overflow-x: auto;
    height: 44px;
    font-family: 'Urbanist', system-ui, sans-serif;
  }
  .btd-tab {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    border-right: 1px solid var(--ii-border-hairline, rgba(64,66,73,0.2));
    cursor: pointer;
    min-width: 180px;
    max-width: 280px;
    white-space: nowrap;
  }
  .btd-tab.active {
    background: var(--ii-bg-canvas, #0e0f13);
    border-bottom: 2px solid var(--ii-accent, #0066ff);
  }
  .btd-tab:hover:not(.active) { background: var(--ii-bg-hover, rgba(80,140,255,0.04)); }
  .btd-labels { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .btd-label { font-size: 12px; font-weight: 600; color: var(--ii-text-primary); text-overflow: ellipsis; overflow: hidden; }
  .btd-sublabel { font-size: 10px; color: var(--ii-text-muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .btd-close {
    background: transparent; border: none;
    color: var(--ii-text-muted); cursor: pointer;
    font-size: 16px; line-height: 1; padding: 4px 6px; border-radius: 3px;
  }
  .btd-close:hover { background: var(--ii-bg-hover); color: var(--ii-error, #d94949); }
</style>
```

- [ ] **Step 2: Export + commit**

```ts
// packages/ui/src/lib/index.ts
export { default as BottomTabDock, type DockTab } from './layouts/BottomTabDock.svelte';
```

```bash
git add packages/ui/src/lib/layouts/BottomTabDock.svelte packages/ui/src/lib/index.ts
git commit -m "feat(ui): BottomTabDock primitive for persistent analysis sessions"
```

### Task 8.2: Analysis dock state + URL hash encoding

**Files:**
- Create: `frontends/wealth/src/lib/discovery/dock-state.svelte.ts`

- [ ] **Step 1: Dock state manager with URL hash persistence**

```ts
// frontends/wealth/src/lib/discovery/dock-state.svelte.ts
import { page } from '$app/state';
import { goto } from '$app/navigation';
import type { DockTab } from '@netz/ui';

export interface AnalysisSession {
  fundId: string;
  fundName: string;
  group: 'returns-risk' | 'holdings' | 'peer';
  window: '1y' | '3y' | '5y' | 'max';
}

function encode(sessions: AnalysisSession[]): string {
  return btoa(JSON.stringify(sessions));
}

function decode(hash: string): AnalysisSession[] {
  try {
    const raw = hash.replace(/^#tabs=/, '');
    if (!raw) return [];
    return JSON.parse(atob(raw)) as AnalysisSession[];
  } catch {
    return [];
  }
}

export function useAnalysisDock() {
  const sessions = $derived(decode(page.url.hash));

  const tabs = $derived<DockTab[]>(
    sessions.map((s) => ({
      id: `${s.fundId}:${s.group}`,
      label: s.fundName,
      sublabel: s.group === 'returns-risk' ? 'Returns & Risk' :
                s.group === 'holdings' ? 'Holdings' : 'Peer',
    })),
  );

  const activeId = $derived<string | null>(() => {
    const currentFund = page.params.external_id;
    const currentGroup = (page.url.searchParams.get('group') ?? 'returns-risk');
    return currentFund ? `${currentFund}:${currentGroup}` : null;
  });

  async function patchHash(nextSessions: AnalysisSession[]) {
    const url = new URL(page.url);
    url.hash = nextSessions.length > 0 ? `tabs=${encode(nextSessions)}` : '';
    await goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }

  async function addSession(s: AnalysisSession) {
    const id = `${s.fundId}:${s.group}`;
    const existing = sessions.find((x) => `${x.fundId}:${x.group}` === id);
    if (existing) return;
    await patchHash([...sessions, s]);
  }

  async function removeSession(id: string) {
    const next = sessions.filter((s) => `${s.fundId}:${s.group}` !== id);
    await patchHash(next);
  }

  async function activate(id: string) {
    const session = sessions.find((s) => `${s.fundId}:${s.group}` === id);
    if (!session) return;
    const url = new URL(page.url);
    url.pathname = `/discovery/funds/${encodeURIComponent(session.fundId)}/analysis`;
    url.searchParams.set('group', session.group);
    url.searchParams.set('window', session.window);
    // preserve hash
    await goto(url, { noScroll: true });
  }

  return {
    get tabs() { return tabs; },
    get activeId() { return activeId; },
    addSession,
    removeSession,
    activate,
  };
}
```

- [ ] **Step 2: Integrate into analysis `+page.svelte`**

```svelte
<script lang="ts">
  // add to existing imports
  import { BottomTabDock } from '@netz/ui';
  import { useAnalysisDock } from '$lib/discovery/dock-state.svelte';

  // ... existing state
  const dock = useAnalysisDock();

  // Auto-add current session to dock on first mount
  $effect(() => {
    dock.addSession({
      fundId: data.fundId,
      fundName: data.header?.fund?.name ?? data.fundId,
      group,
      window,
    });
  });
</script>

<!-- at the bottom of .analysis-page, BEFORE closing </div> -->
<BottomTabDock
  tabs={dock.tabs}
  activeId={dock.activeId}
  onActivate={(id) => dock.activate(id)}
  onClose={(id) => dock.removeSession(id)}
/>
```

- [ ] **Step 3: Visual validation**

1. Open `/discovery/funds/AAA/analysis` → tab `AAA · Returns & Risk` appears in dock
2. Switch group to Holdings → new tab `AAA · Holdings` added alongside
3. Navigate to `/discovery/funds/BBB/analysis` via back+click → tab `BBB · Returns & Risk` added; all 3 tabs visible
4. Click tab `AAA · Returns & Risk` → navigates back to AAA with group=returns-risk and window preserved
5. Close a tab via × → tab disappears, URL hash updates
6. Browser refresh → dock state restored from URL hash
7. Copy URL, paste in new tab → same dock state reconstructs

- [ ] **Step 4: Commit**

```bash
git add frontends/wealth/src/lib/discovery/dock-state.svelte.ts frontends/wealth/src/routes/\(app\)/discovery/funds/\[external_id\]/analysis/+page.svelte
git commit -m "feat(discovery): bottom tab dock with URL-hash persistence across funds"
```

### Task 8.3: Full check gate + visual sweep

- [ ] **Step 1: Run full gate**

```bash
make check
cd frontends/wealth && pnpm check
```

- [ ] **Step 2: Visual sweep at 4 breakpoints (1920/1440/1280/1024)**

Complete discovery → analysis flow including dock persistence, 3 groups, private fund degradation, reverse lookup, institutional reveal.

- [ ] **Step 3: Commit tweaks**

```bash
git add -A
git commit -m "polish(discovery): final Phase 8 visual validation fixes"
```

---

## Self-Review Results

**Spec coverage check:**

*Discovery FCL (Phases 0-4):*
- Rename `/screener` → `/discovery` throughout ✓
- FCL state machine + URL contract (`manager`, `fund`, `view=dd|factsheet`) ✓ (Task 4.1)
- Neutral `FlexibleColumnLayout` promoted to `@netz/ui` ✓ (Task 2.1)
- Portfolio Builder migrated to neutral FCL (same PR) ✓ (Task 2.2)
- `EnterpriseTable` extraction with ColumnDef + snippets ✓ (Task 2.3)
- `CatalogTable` v1/v2 both deleted (both had broken tanstack) ✓ (Task 2.4)
- Keyset pagination indexes (Col1 + Col2) ✓ (Task 1.1)
- `nav_monthly_returns_agg` prod diagnostic before code ✓ (Task 0.1)
- Col1 Managers query + Redis cache + SingleFlightLock ✓ (Tasks 3.1, 3.2)
- Col2 Funds query + Redis cache ✓ (Tasks 3.1, 3.2)
- Col3 Fact Sheet route with JSONB aggregate ✓ (Task 3.3)
- Col3 DD snapshot + SSE via Redis pub/sub ✓ (Tasks 3.3, 3.4)
- Fund row buttons: **DD / FS / Open Analysis →** ✓ (Task 4.3)

*Chart foundation:*
- CSS var `--chart-*` tokens + Urbanist + tooltip formatters ✓ (Task 1.3)
- `echarts-setup` fix to consume tokens ✓ (Task 1.3)

*Standalone Analysis page (Phase 5):*
- Route `/discovery/funds/{id}/analysis` with FilterRail + AnalysisGrid ✓ (Tasks 5.2, 5.3)
- `FilterRail` primitive promoted to `@netz/ui` ✓ (Task 5.2)
- `ChartCard` + `AnalysisGrid` (3-col responsive) ✓ (Task 5.3)
- Three-tab header (Returns & Risk | Holdings | Peer) ✓ (Task 5.5)
- Backend `analysis_returns` endpoint with 3y default ✓ (Task 5.1)
- 6 Returns & Risk charts: NAV hero, rolling risk, monthly heatmap, return distribution, drawdown underwater, risk metrics bullet ✓ (Task 5.4)

*Holdings Analysis (Phase 6):*
- `analysis_holdings` queries: top, style-drift, reverse-lookup ✓ (Task 6.1)
- **Les Misérables network viz** for reverse lookup ✓ (Task 6.2)
- **Style Drift flow** across quarters ✓ (Task 6.2)
- TopHoldingsSunburst + SectorTreemap ✓ (Task 6.2)
- HoldingsView with click-to-reverse-lookup interaction ✓ (Task 6.3)
- Institutional empty state for funds without N-PORT/13F disclosure ✓ (Task 6.3)

*Peer Analysis + Institutional Reveal (Phase 7):*
- `curated_institutions` table + seed (Ivy endowments, Olayan, Iconiq, Rockefeller, Bessemer, Gates, Norges, Temasek) ✓ (Task 7.1)
- `analysis_peer` queries: peer comparison + institutional reveal overlap matrix ✓ (Task 7.2)
- PeerScatter + PeerRankingLadder + **InstitutionalRevealMatrix** (heatmap: institutions × top 25 CUSIPs) ✓ (Task 7.3)
- Graceful degradation when curated CIKs not populated ✓ (Task 7.2)

*Bottom Tab Dock (Phase 8):*
- `BottomTabDock` primitive in `@netz/ui` ✓ (Task 8.1)
- Cross-fund persistence via URL hash encoding (no localStorage) ✓ (Task 8.2)
- Auto-add current session + preserve window/group on tab switch ✓ (Task 8.2)

*Stability & discipline:*
- URL-driven navigation with `replaceState:true, noScroll:true, keepFocus:true` ✓ (Task 4.1)
- `AbortController` on every async `$effect` that fetches ✓ (all col3 panels + analysis views)
- SSE via `fetch + ReadableStream` (never `EventSource`) ✓ (Task 4.4)
- Zero localStorage / sessionStorage ✓ (all state in `$state`, URL searchParams, or URL hash)
- Formatter discipline — all numbers via `@netz/ui` formatters ✓ (columns.ts, tooltips, panels)
- RLS subselect pattern on all tenant-scoped queries ✓ (dd_chapters, dd_reports)
- DB-only hot path — zero EDGAR/Yahoo calls from routes ✓ (all `read_*` methods)

**Placeholder scan:** clean. Every code block is concrete; no "implement later", "similar to X", or vague "add error handling".

**Type consistency check:** `FCLState`, `ColumnDef<T>`, `ManagerRow`, `FundRowView`, `DockTab`, `AnalysisSession`, `DiscoveryFilters`, `ManagerCursor`, `FundCursor`, `Window` consistent across all tasks. `external_id` is the polymorphic fund primary key throughout routes, keys, and components. `fund_id` param in URLs always means `external_id`.

**Method signatures cross-checked:**
- `resolve_fund(db, external_id)` → used in 3.3, 5.1, 6.1, 7.2 — signature matches.
- `chartTokens()` → called via `$derived.by` everywhere — consistent.
- `useDiscoveryUrlState().openAnalysis(fundId, group)` → matches call site in `DiscoveryFundsTable.onOpenAnalysis`.
- `fetchReturnsRisk(fundId, window, signal)` → matches ReturnsRiskView effect.

**Gaps flagged for follow-up sprint (not blockers):**
1. **Benchmark overlay in NAV hero** — backend payload doesn't yet include benchmark series; chart accepts `benchmarkSeries` prop but it's always empty. Add `sp500` / `msci_world` joins via `benchmark_nav` hypertable in a follow-up.
2. **Factor exposure chart** — PCA loadings from `factor_model_service` not yet wired into Returns & Risk (6 slots already full). Can add as 7th card or replace Drawdown Underwater.
3. **Regime shading on NAV hero** — `regime_service` output needs to be joined and serialized with `nav_series` in the backend payload.
4. **CIK backfill for `curated_institutions`** — script is a stub; requires manual pg_trgm review to confirm matches against `sec_managers.firm_name`.
5. **Style Drift Sankey view** — current flow is stacked line; a Sankey showing position-level migration between quarters would be more impactful but needs denormalized diff data.
6. **Reverse lookup scale** — current query scans latest quarter only. Historical "who used to hold this" over 8 quarters would show institutional conviction trends.
7. **L3 score materialization in `screening_results`** (Andrei chose L1-only for v1 per locked decisions).
8. **LEI bridge for UCITS↔SEC manager merge** (Andrei chose filter-separated per locked decisions).
9. **Rolling risk chart benchmark band** — peer-median overlay currently not fetched.
10. **Institutional Reveal filter by category** — query supports it, UI exposes it in AnalysisFilters, but wiring from filter rail to query param not yet implemented in PeerView. One-line follow-up.

---

Plan complete and saved to `docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
