# Plano: Wiring Completo — Wealth Vertical Frontend

**Data:** 2026-03-23
**Audit fonte:** `docs/audit/endpoint_coverage_audit.md`
**Gate:** `make check` (backend) + `pnpm run check` (wealth frontend) verde em cada sessao
**Estimativa:** 4 sessoes seguindo a cadeia de investimento top-down

## Enhancement Summary

**Deepened on:** 2026-03-23
**Research agents:** 6 (ECharts financial charting, screener UX, SvelteKit patterns, architecture risks, macro catalog design, codebase audit)

### Key Improvements
1. Catalogo concreto de ~120 indicadores macro agrupados por dominio (11 grupos, taxonomia Bloomberg ECST)
2. ECharts configs detalhados: dual Y-axis, multi-grid sub-chart, crosshair sync, dataZoom
3. 5 riscos arquiteturais identificados com mitigacoes (macro rewrite scope, screener file size, backtest sync vs polling, time range vs backend lookback, HeatmapChart dependency)
4. Mixed frequency handling: step function (forward-fill) para dados quarterly/annual em chart diario
5. Forecast vs actual visual treatment: solid vs dashed line, vertical demarcation
6. Componentes @netz/ui confirmados: `createPoller`, `LongRunningAction`, `ConflictError`, `HeatmapChart`, `api.getBlob()`
7. Screener UX: tab state preservation entre instrumentos, dynamic facets por asset type, autocomplete search
8. `filterMode: 'weakFilter'` obrigatorio em dataZoom — default `'filter'` faz series quarterly desaparecerem no zoom
9. LTTB sampling DESABILITADO para este volume (520pts x 10 series) — bug #15538 quebra tooltips multi-series
10. Novo `CorrelationHeatmap.svelte` como componente separado (nao extension do HeatmapChart existente)
11. `$state.raw()` para arrays grandes de ECharts data — evita overhead de deep proxy do Svelte 5
12. 7 seams naturais identificados para extrair componentes do screener (2473 linhas) com ranges de linha
13. ARIA tab pattern completo com keyboard navigation e `aria-busy` para lazy loading
14. `SvelteMap` de `svelte/reactivity` para cache per-instrument per-tab (ja reativo, sem wrapper `$state`)
15. Backend schema gap: `mp_threshold` e `n_signal_eigenvalues` nao expostos na API — extension necessaria
16. Hard limit series reduzido para 8 (nao 10) — evita cycling da palette ECharts + limite cognitivo
17. Region chips como single-select (radio) nao multi-select — filtra catalogo, nao o chart

### Critical Risks Discovered
1. **Macro page e REWRITE, nao port** — 753 linhas atuais usam CSS sparklines, nao ECharts. Mitigar com abordagem aditiva (novo chart acima dos panels, deprecar panels depois)
2. **Backtest e SINCRONO** no backend (nao async) — legacy esperava polling mas backend retorna imediato. Usar `LongRunningAction` com timeout generoso, NAO polling
3. **Backend lookback e 730 dias** — time range selector com 5Y/Max vai mostrar apenas 2Y silenciosamente. Desabilitar botoes ou adicionar `lookback_days` param
4. **Screener page tem 2473 linhas** — extrair ManagerDetailPanel.svelte antes de adicionar tabs
5. **HeatmapChart EXISTE** em @netz/ui mas usa single-color gradient — criar `CorrelationHeatmap.svelte` separado
6. **ChartContainer NAO expoe instancia ECharts** — para click events no heatmap e dispatch de dataZoom, usar `echarts.getInstanceByDom(containerEl)` ou wrapper
7. **Backtest timeout risk** — 120s sync call pode exceder proxy timeout do Railway (30-60s). Se falhar, converter para async+SSE (mesmo pattern do Pareto)
8. **`step: 'end'` bug #20658** — dados DEVEM ser sorted ascending, senao step direction inverte
9. **`markArea` desaparece no zoom parcial** (bugs #15708, #3637) — usar `markLine` para forecast demarcation, nao `markArea`
10. **Rolling correlation endpoint nao existe** — `RegimeChart.svelte` esta pronto no frontend, mas `/analytics/rolling-correlation` precisa ser criado no backend

---

## Principios de UX

### 1. Provider-agnostico

O DB e alimentado por data providers (FRED, SEC EDGAR, ESMA Register, BIS, IMF, Treasury, OFR, Yahoo Finance). **A UI nunca menciona providers.** O analista pensa em "credit gap", "GDP growth", "fund holdings" — nao em "BIS API" ou "ESMA Register".

- Nenhum componente nomeado por provider (nada de `BisPanel`, `ImfPanel`, `EsmaManagerDrawer`)
- Nenhum label de provider na UI (nada de "Source: ESMA", "Data: SEC 13F")
- Filtros por dominio: asset type, geography, strategy, currency, AUM range

### 2. Screener unificado

Um unico screener filtra todos os assets (funds, ETFs, equities, bonds). O backend ja faz `union_all` entre `instruments_universe` e fontes globais. A pagina de detalhe faz breakdowns: holdings, drift, allocations, institutional investors, regulatory docs. Apenas filtros na listagem.

### 3. Macro como charting tecnico

Estilo Barchart/Bloomberg: multi-series overlay num chart ECharts unificado.
- Time range selector: 1M, 3M, 6M, 1Y, 2Y (max backend lookback)
- Series picker: o analista escolhe indicadores (credit gap, GDP, CPI, treasury rates, etc.)
- Compare mode: overlay de 2+ series com eixos duplos
- Volume/activity sub-chart quando aplicavel
- % vs absolute toggle
- Dados vem do DB via endpoints por dominio, mas a UI apresenta como catalogo de indicadores

---

## Cadeia de Investimento (ordem de execucao)

```
Macro Intelligence → Asset Allocation (blocks) → Asset Screeners → DD Reports
→ IC Approval → Universe → Model Portfolios → Rebalancing → Risk/Alerts
```

```
Sessao 1: Macro (charting tecnico + committee reviews)
Sessao 2: Screener unificado (detail page com drift/holdings/institutional/docs)
Sessao 3: Model Portfolios (create) + Fact Sheets + Portfolio History
Sessao 4: Analytics (backtest + correlation) + pontuais + bug fix
```

---

## Sessao 1 — Macro Intelligence

### 1A. Macro Chart — Series Picker + Technical Charting

**O que faz:** Chart profissional estilo Barchart onde o analista seleciona indicadores macroeconomicos e compara series overlay. Substitui as secoes provider-specific atuais (CSS sparklines por panel).

**Nota: Isto e um REWRITE da macro page, nao um port.** A page atual (753 linhas) usa CSS-only sparklines com panels individuais por dominio. O novo design substitui por ECharts profissional. Mitigacao: implementar o novo chart como secao acima dos panels existentes, deprecar panels em commit separado.

**Endpoints consumidos:**
- `GET /macro/scores` (indicadores agregados)
- `GET /macro/regime` (regime detection)
- `GET /macro/bis` (credit gap, DSR, property — via query params `country`, `indicator`)
- `GET /macro/imf` (GDP, inflation, fiscal — via query params `country`, `indicator`)
- `GET /macro/treasury` (rates, debt, auctions — via query param `series`)
- `GET /macro/ofr` (hedge fund leverage, stress — via query param `metric`)
- `GET /macro/snapshot` (regime badge por regiao) **← DESCONECTADO**
- `GET /risk/macro` (macro risk overlay)

**Destino:** `routes/(app)/macro/+page.svelte` + `+page.server.ts`

**Design:**

```
┌──────────────────────────────────────────────────────────────┐
│  Macro Intelligence                                          │
│                                                              │
│  [Regime: RISK-ON ●] [US ▼] [Europe ▼] [EM ▼] [Global ▼]  │
│                                                              │
│  Series: [Credit Gap ✕] [10Y Treasury ✕] [+ Add Indicator]  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │          Main chart (ECharts multi-grid)               │  │
│  │          Y-axis left: % | Y-axis right: absolute      │  │
│  │          Crosshair synced across grids                 │  │
│  │──────────────────────────────────────────────────────  │  │
│  │  [activity sub-chart]                                  │  │
│  │  1M  3M  6M  1Y  2Y                     % | abs  log  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Committee Reviews                                     │  │
│  │  2026-03-20  APPROVED  "Risk-on bias persists..."      │  │
│  │  2026-03-13  APPROVED  "EM spreads tightening..."      │  │
│  │  [Generate Review]                                     │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Catalogo de indicadores** (11 grupos, ~120 series, taxonomia Bloomberg ECST):

| Grupo | Exemplos | Freq | Backend |
|-------|----------|------|---------|
| Output & Growth | Real GDP, Industrial Production, CLI | Q/M | `/macro/imf`, `/macro/scores` |
| Prices & Inflation | CPI, Core PCE, HICP | M | `/macro/scores` |
| Monetary Policy & Rates | Fed Funds, 10Y Treasury, ECB Rate, SOFR | D | `/macro/treasury`, `/macro/scores` |
| Financial Conditions | NFCI, VIX, St. Louis Stress, Policy Uncertainty | D/W | `/macro/scores` |
| Credit Spreads & Quality | Baa Spread, HY Spread, Delinquency, Charge-Off | D/Q | `/macro/scores` |
| Labor Market | Unemployment, JOLTS, Sahm Rule | M | `/macro/scores` |
| Consumer & Sentiment | Michigan Sentiment, Euro Confidence | M | `/macro/scores` |
| Housing & Real Estate | Case-Shiller (nat + 20 metros), Starts, Permits, Mortgage Rates | M/W | `/macro/scores`, `/macro/bis` |
| Commodities & Energy | WTI, Brent, Gold, Copper, SPR, Inventories | D/W | `/macro/scores` |
| Fiscal & Sovereign | Total Debt, Interest Expense, FX, Credit-to-GDP Gap, DSR | D/Q | `/macro/treasury`, `/macro/bis`, `/macro/imf` |
| Alternative & Hedge Fund | Leverage (mean/P50/P95), GAV, NAV, Strategy AUM, Repo | Q | `/macro/ofr` |

**Series Picker UX:**
- Hybrid: search-first flat list com grouped fallback browsing (11 groups colapsados por default)
- Typing inicia busca flat com group labels como separadores — power users pulam a arvore
- Region filter chips at top: All | US | Europe | Asia | EM | Global — **single-select radio** (filtra catalogo, nao o chart)
- Frequency filter chips: All | Daily | Monthly | Quarterly
- Star icon per indicator for favorites (DB-backed `user_indicator_favorites`, loaded in server load)
- Hard limit **8 series** no chart (nao 10) — warning banner em 6, botao desabilita em 8, tooltip explica
- "Switch to Data Table" affordance ao lado do chart para analistas que precisam comparar mais series
- Frequency badge pill (`D`, `M`, `Q`, `A`) no legend entry de cada serie — mostra cadencia do dado

### Research Insights

**ECharts Multi-Grid Config (main chart + sub-chart):**
- Two `grid` entries: main (top 55%) + sub-chart (bottom 15%)
- Two `xAxis` entries linked via `dataZoom.xAxisIndex: [0, 1]`
- Three `yAxis` entries: left % (gridIndex 0), right absolute (gridIndex 0), sub-chart volume (gridIndex 1)
- `axisPointer.link: [{ xAxisIndex: 'all' }]` syncs crosshair across grids — MUST be at root level, not per-axis
- `splitLine: { show: false }` on right axis to prevent double gridlines
- `containLabel: true` on grids prevents axis labels from overflowing
- Reserve bottom ~10% for dataZoom slider: `dataZoom: [{ type: 'slider', bottom: '0%' }]`

**Dual Y-Axis Scaling (ECharts 5.3+):**
- `scale: true` on both axes — prevents forcing zero baseline, essential for return series (-2% to +5%)
- `alignTicks: true` on secondary (right) axis — aligns tick lines horizontally for readability
- If a third axis is needed: `offset: 80` shifts it outward on the same side
- Formatter: `(v) => \`${(v * 100).toFixed(1)}%\`` for left, `(v) => \`$${(v/1000).toFixed(0)}k\`` for right

**DataZoom — CRITICO para mixed frequency:**
```typescript
dataZoom: [
  {
    type: 'slider',
    xAxisIndex: [0, 1],         // link both grids
    filterMode: 'weakFilter',   // OBRIGATORIO — 'filter' faz series quarterly desaparecerem
    bottom: 8, height: 20,
    showDataShadow: false,      // evita preview desalinhada com dados esparsos
    labelFormatter: (value: number) => new Date(value).getFullYear().toString()
  },
  {
    type: 'inside',
    xAxisIndex: [0, 1],
    filterMode: 'weakFilter'
  }
]
```

**Time Range:**
- Backend lookback e 730 dias (`_DEFAULT_LOOKBACK_DAYS` em `macro.py:403`). **Desabilitar botoes 3Y/5Y/Max** ou adicionar `lookback_days` query param
- Implementar como botoes externos que chamam `chart.dispatchAction({ type: 'dataZoom', startValue, endValue })`
- ECharts NAO tem componente nativo de range buttons — sempre implementado no wrapper UI
- Para acessar a instancia ECharts (dispatch): `echarts.getInstanceByDom(containerEl)` — ChartContainer nao expoe instancia

**Mixed Frequency (crucial):**
- Step function (forward-fill) para dados quarterly/annual: `step: 'end'` no ECharts
- NUNCA interpolar — BIS trimestral nao tem dados entre pontos
- **BUG CRITICO #20658:** dados DEVEM ser sorted ascending (oldest first). Descending inverte step direction
- `connectNulls: false` (default) — mostra breaks em gaps de dados quarterly, nao interpola
- Daily: `step: false` (linha normal)
- Monthly: `step: 'end'` com circle markers (`showSymbol: true, symbolSize: 5`)
- Quarterly: `step: 'end'` com linha mais grossa (`lineStyle: { width: 2 }`)
- Annual (IMF): `step: 'end'` ou apenas point markers
- Mixed frequency annotation banner: "Mixed frequencies — quarterly series forward-filled" (dismissible, aparece apenas quando chart tem daily + quarterly+)

**Forecast vs Actual (IMF WEO):**
- Solid line para actuals, dashed line para forecasts — **dois series separados** (nao uma serie com estilo condicional)
- Repetir ultimo ponto actual como primeiro ponto forecast — cria juncao visual seamless
- Vertical `markLine` no boundary (NAO `markArea` — bugs #15708, #3637 fazem markArea desaparecer no zoom parcial)
- Legend suffix: "(proj.)" no nome da serie forecast — ex: "Brazil GDP Growth (proj.)"
- Tooltip: "2025: 2.1% (actual)" vs "2027: 1.8% (estimate)"
- Confidence band (se disponivel): `areaStyle: { color: "rgba(..., 0.08)" }` entre lower/upper WEO bounds

**Performance (confirmado para 8 series x 520 pts = 4,160 pts):**
- `animation: false` no load inicial — single highest-impact perf toggle
- `showSymbol: false` para series densas (daily) — enorme ganho de perf em canvas
- **NAO usar `sampling: 'lttb'`** — bug #15538 quebra tooltips multi-series. So habilitar acima de 2000+ pts/serie
- `progressive: 0` — chunked rendering so necessario acima de 10,000+ pts
- `$state.raw()` para arrays grandes de dados (evita deep proxy overhead do Svelte 5)
- `notMerge: true` ja configurado no `ChartContainer.svelte` existente — safe para multi-grid

**Debounce Pattern (Svelte 5 — confirmado no codebase):**
```typescript
let selected = $state<Set<string>>(new Set(['gdp', 'cpi']));
let debouncedOption = $state<Record<string, unknown>>({});

const rawOption = $derived.by(() => { /* build ECharts option from selected — pure computation */ });

$effect(() => {
  const opt = rawOption;
  const timer = setTimeout(() => { debouncedOption = opt; }, 150);
  return () => clearTimeout(timer);  // cleanup cancela timer pendente no re-run
});
```

**State Management — single state object:**
```typescript
type MacroChartState = {
  selectedSeries: Set<string>;
  timeRange: '1M' | '3M' | '6M' | '1Y' | '2Y';
  region: string;
  scaleMode: 'percent' | 'absolute' | 'log';
};
```
Derivar ECharts option como um unico `$derived.by()` deste state. Nunca deixar filtros individuais trigarem fetches independentes.

**Race Condition — series add/remove (3 patterns, por preferencia):**
1. `getAbortSignal()` from Svelte (newest, cleanest) — auto-aborts when `$effect` re-runs
2. `AbortController` in `$effect` com cleanup: `return () => controller.abort()`
3. Sequence counter (monotonic) — `if (seq !== currentSeq) return;` para rejeitar resultados stale

**Server Load Structure (confirmado em `macro/+page.server.ts`):**
- SSR carrega: `/macro/scores`, `/macro/regime`, `/risk/macro` (ja wired)
- Adicionar: `/macro/snapshot`, `/macro/reviews` (ambos DESCONECTADOS)
- Client-side via `$effect`: `/macro/treasury`, `/macro/ofr`, `/macro/bis`, `/macro/imf` (ja wired, reativo a selectors)

### 1B. Committee Reviews (5 endpoints)

**O que faz:** Workflow de committee review — gerar, listar, aprovar, rejeitar. Abaixo do chart principal.

**Endpoints:**
- `GET /macro/reviews` **← DESCONECTADO**
- `POST /macro/reviews/generate` **← DESCONECTADO**
- `PATCH /macro/reviews/{review_id}/approve` **← DESCONECTADO**
- `PATCH /macro/reviews/{review_id}/reject` **← DESCONECTADO**
- `GET /macro/snapshot` **← DESCONECTADO**

**Implementacao:**
1. Adicionar ao server load: `api.get("/macro/snapshot")`, `api.get("/macro/reviews")`
2. Secao "Committee Reviews" abaixo do chart
3. Lista de reviews com data, status badge, resumo truncado
4. "Generate Review" → POST com ConsequenceDialog
5. Approve/Reject → PATCH com rationale obrigatorio

### Research Insights

**`POST /macro/reviews/generate` e sincrono e deterministic** (nao chama LLM) — `generate_weekly_report()` e pure function. MAS usa `require_content_slot()` (semaforo de backpressure). Se slots exauridos por spotlight/flash-report concorrentes, o request bloqueia.
- Mitigacao: loading state + timeout generoso + mensagem clara "Too many concurrent tasks, try again"

**Concurrent approve/reject:** Backend usa `with_for_update()` + check `status != "pending"`. Segundo approve retorna 409.
- Mitigacao: UI pessimista (padrao do codebase — confirmado em `RebalancingTab.svelte`). Catch 409 explicitamente, surface como inline error "Review already processed" com dismiss button, refresh lista

**ConsequenceDialog API (confirmado — 284 linhas, props completas):**
```typescript
<ConsequenceDialog
  open={showApproveDialog}
  title="Approve Macro Review"
  impactSummary="This review will inform allocation decisions."
  requireRationale={true}
  rationaleLabel="Approval rationale"
  rationaleMinLength={10}
  onConfirm={handleApprove}
/>
```
- Gate logic: `canConfirm = rationaleSatisfied && typedConfirmationSatisfied`
- Payload: `{ rationale?: string; typedConfirmation?: string }`
- `metadata` prop disponivel para mostrar context items no dialog (ex: review date, regime)

**Review endpoint details (confirmado no backend):**
- `GET /macro/reviews`: params `limit` (default 20), `offset` (default 0), `status` filter (`pending|approved|rejected`). Returns `list[MacroReviewRead]`
- `POST /macro/reviews/generate`: requires `INVESTMENT_TEAM` role
- `PATCH /macro/reviews/{id}/approve`: requires `DIRECTOR|ADMIN` role, body `MacroReviewApprove`
- `PATCH /macro/reviews/{id}/reject`: requires `DIRECTOR|ADMIN` role, body `MacroReviewReject`

---

## Sessao 2 — Screener Unificado + Detail Page

### 2A. Screener — filtros agnosticos + detail tabs

**O que faz:** Adicionar tabs avancadas ao detail panel do screener existente.

**PREREQUISITO:** Extrair `ManagerDetailPanel.svelte` do screener page (2473 linhas) antes de adicionar tabs. Cada nova tab como componente separado (`DriftTab.svelte`, `NportTab.svelte`, `DocsTab.svelte`).

**Endpoints a conectar no detail panel:**
- `GET /manager-screener/managers/{crd}/drift` **← DESCONECTADO**
- `GET /manager-screener/managers/{crd}/nport` **← DESCONECTADO**
- `GET /manager-screener/managers/{crd}/brochure/sections` **← DESCONECTADO**
- `GET /manager-screener/managers/{crd}/brochure` (search) **← DESCONECTADO**

**Design do detail panel:**

```
┌──────────────────────────────────────────────────────┐
│  Vanguard Total Stock Market ETF                      │
│  Fund | US | Large Blend | USD | AUM $300B            │
│                                                       │
│  [Overview] [Holdings] [Drift] [Institutional] [Docs] │
│                                                       │
│  Labels por dominio, NUNCA por provider:              │
│  "Holdings" (nao "13F Holdings" ou "N-PORT")          │
│  "Drift" (nao "13F Diff Turnover")                    │
│  "Institutional" (nao "SEC 13F Reverse Lookup")       │
│  "Docs" (nao "ADV Part 2A Brochure")                  │
│                                                       │
│  [Add to Universe]  [Compare]                         │
└──────────────────────────────────────────────────────┘
```

**Implementacao:**
1. Extrair `ManagerDetailPanel.svelte` do screener page
2. Cada tab como componente isolado com proprio fetch/loading/abort
3. Tab "Holdings": merge com dados N-PORT quando disponivel (mais recente que quarterly)
4. Tab "Drift": turnover timeline por quarter (bar chart ECharts), churn metrics
5. Tab "Docs": secoes do documento regulatorio + search com debounce 300ms
6. Lazy load por tab, `AbortController` cleanup no tab switch
7. N-PORT e paginado server-side (`page_size=50`) — wire up pagination controls

### Research Insights

**Screener extraction — 7 seams naturais identificados:**

| Novo componente | Linhas extraidas | Conteudo |
|-----------------|-----------------|----------|
| `InstrumentFilterSidebar.svelte` | ~562–653 | Instrument filter form + chip grid + facet summary |
| `ManagerFilterSidebar.svelte` | ~654–798 | Manager filters + funnel + fund filters + last run |
| `InstrumentTable.svelte` | ~806–901 | Search results table + pagination |
| `ManagerHierarchyTable.svelte` | ~952–1087 | Manager/fund hierarchical table + pagination |
| `PeerComparisonView.svelte` | ~902–951 | Compare result cards + sector grid |
| `InstrumentDetailPanel.svelte` | ~1391–1432 | Fund detail ContextPanel (target for 5-tab refactor) |
| `ManagerDetailPanel.svelte` | ~1099–1371 | Manager detail + 4 tab snippets |

**State que FICA no page component:** `activeMode`, `panelOpen`, `panelMode`, `selectedInstrument`, `fundFilters`, `expandedManagers`, `selectedManagers` — coordenam entre sidebar e table.

**Use `setContext`/`getContext` para panel state (nao prop drilling):**
```typescript
// +page.svelte
const panelState = $state({ open: false, instrument: null, crd: null });
setContext('screener:panel', panelState);

// ManagerDetailPanel.svelte
const panel = getContext('screener:panel');
// panel.instrument is live and reactive
```

**Tab implementation — Svelte 5 reactive pattern (substitui imperative `fetchTab()`):**
```typescript
// Cada tab como componente isolado com $effect reativo
$effect(() => {
  const controller = new AbortController();
  loading = true;
  fetch(`/api/manager-screener/managers/${crd}/${tab}`, { signal: controller.signal })
    .then(r => r.json())
    .then(data => { tabData = data; })
    .catch(e => { if (e.name !== 'AbortError') error = e.message; })
    .finally(() => { loading = false; });
  return () => controller.abort();  // cleanup on tab switch, crd change, or unmount
});
```

**Tab data cache — `SvelteMap` from `svelte/reactivity`:**
```typescript
// stores/manager-tab-cache.svelte.ts
import { SvelteMap } from 'svelte/reactivity';
const cache = new SvelteMap<string, Partial<Record<TabKey, TabData | null>>>();
// SvelteMap JA e reativo — NAO wrappear em $state()
// $derived(getCachedTab(crd, tab)) recomputa quando cache.set() e chamado
// Invalidar cache apos "Add to Universe" ou ESMA import
```

**Tab state preservation (descoberta importante):**
- Preservar `activeTab` ao trocar de instrumento (nao resetar para "overview")
- Se usuario esta em "Holdings" e clica outro instrumento, mostrar Holdings do novo instrumento
- Reset apenas ao fechar o panel
- Cache wipe apenas quando `crd` muda (nao quando tab muda)

**ARIA tab pattern obrigatorio:**
```html
<div role="tablist" aria-label="Manager details">
  <button role="tab" id="tab-profile" aria-selected={activeTab === 'profile'}
    aria-controls="panel-profile" tabindex={activeTab === 'profile' ? 0 : -1}
    onkeydown={(e) => handleTabKeydown(e, 'profile')}>Profile</button>
  <!-- ... -->
</div>
<div role="tabpanel" id="panel-profile" aria-labelledby="tab-profile"
  aria-busy={loading} tabindex="0" hidden={activeTab !== 'profile'}>
  <!-- content -->
</div>
```
- Arrow keys (Left/Right) navegam entre tabs
- `tabindex="-1"` em tabs inativos — impede Tab key de iterar por todos
- `aria-busy={loading}` esconde children de screen readers durante fetch
- `hidden` attribute (nao `display:none` via CSS) remove de accessibility tree

**3 tipos de empty state para cada tab:**
1. **Feature unavailable** (no CIK): "Institutional data unavailable — This manager is not registered with the SEC and has no CIK." Sem retry button.
2. **Empty but valid** (CIK existe, 0 holders): "No institutional holders on record. Coverage updates quarterly." Link externo opcional.
3. **Fetch error**: Error message + Retry button. Sempre.

**Dynamic facets por asset type — extend `CHIP_FILTERS`:**
```typescript
const CHIP_FACETS: Record<ChipKey, (keyof ScreenerFacets)[]> = {
  all:        ['geographies', 'domiciles', 'currencies'],
  us_funds:   ['geographies', 'currencies', 'strategies'],
  ucits:      ['domiciles', 'currencies'],
  etfs:       ['geographies', 'currencies', 'asset_classes'],
  bonds:      ['geographies', 'currencies', 'credit_ratings', 'maturities'],
  equities:   ['geographies', 'currencies', 'sectors'],
  hedge_funds:['geographies', 'currencies', 'strategies'],
};
```
- Revelar facets com `transition:slide` — nunca hard show/hide
- Desabilitar (nao esconder) facets inaplicaveis — mostra tooltip "Applies to bonds only"

### 2B. ESMA Browse → absorvido pelo Screener

**Decisao:** NAO criar rota separada `/esma`. Os dados ESMA ja fluem pelo screener via `union_all`. O screener com filtro cobre o caso de uso.

Os 5 endpoints ESMA permanecem no backend como API de conveniencia. **Se necessario no futuro:** cross-ref SEC como badge no detail panel.

---

## Sessao 3 — Model Portfolios + Fact Sheets + Portfolio History

### 3A. POST /model-portfolios — Create

**O que faz:** Criar novo model portfolio. **Sem este endpoint, todo o downstream fica bloqueado:** construct → backtest → stress → track-record → fact-sheets.

**Endpoint:** `POST /model-portfolios` **← DESCONECTADO**

**Destino:** `routes/(app)/model-portfolios/+page.svelte`

**Implementacao:**
1. Botao "New Portfolio" no header da listing page (card grid existente, 172 linhas)
2. Dialog com form: profile, display_name, description, benchmark_composite, inception_date, backtest_start_date
3. POST → redirect para `/model-portfolios/{new_id}`
4. Tratar 409 conflict: `profile` e chave unica por org — mostrar "Portfolio with this profile already exists"
5. Botao role-gated: `POST /model-portfolios` requires `INVESTMENT_TEAM` role — mostrar botao apenas para roles autorizados

### Research Insights

**409 handling — pessimistic UI (padrao do codebase, confirmado em `RebalancingTab.svelte`):**
```typescript
try {
  const result = await api.post<ModelPortfolio>("/model-portfolios", body);
  goto(`/model-portfolios/${result.id}`);
} catch (e) {
  if (e instanceof Error && e.message.includes("409")) {
    formError = "A portfolio with this profile already exists.";
  } else {
    formError = e instanceof Error ? e.message : "Failed to create portfolio.";
  }
}
```
- Inline error com dismiss button (nao toast) — padrao do codebase
- Server-side: retorna 409 se `profile` duplicado por `organization_id`

### 3B. Fact Sheets — Model Portfolios (3 endpoints)

**Endpoints:**
- `POST /fact-sheets/model-portfolios/{portfolio_id}` **← DESCONECTADO**
- `GET /fact-sheets/model-portfolios/{portfolio_id}` **← DESCONECTADO**
- `GET /fact-sheets/{fact_sheet_path}/download` **← DESCONECTADO**

**Destino:** Secao "Fact Sheets" em `model-portfolios/[portfolioId]/+page.svelte`

**Implementacao:**
1. Secao abaixo de track-record/stress
2. Botao "Generate Fact Sheet" (POST) com loading state — params: `language=pt|en` (default pt)
3. Lista com data + botao download (blob pattern)
4. Feature-gated: `FEATURE_WEALTH_FACT_SHEETS`

### Research Insights

**Blob download — pattern canonico do codebase (confirmado em `content/+page.svelte`):**
```typescript
let downloadingId = $state<string | null>(null);

async function downloadFactSheet(path: string, filename: string) {
  downloadingId = path;
  try {
    const token = await getToken();
    const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
    const res = await fetch(`${apiBase}/fact-sheets/${encodeURIComponent(path)}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error("Download failed");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);  // revoke imediatamente — browser ja enfileirou download
  } catch (e) {
    error = e instanceof Error ? e.message : "Download failed";
  } finally {
    downloadingId = null;
  }
}
```
- `downloadingId` permite loading state per-item no botao de download
- Alternativa: `api.getBlob(path)` de `NetzApiClient` — handles auth automaticamente
- `URL.revokeObjectURL()` chamado imediatamente apos `.click()` — seguro, browser ja enfileirou

**Filename from Content-Disposition (se backend enviar):**
```typescript
const disposition = res.headers.get("Content-Disposition");
const filename = disposition?.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)?.[1] ?? "factsheet.pdf";
```

### 3C. GET /portfolios/{profile}/history

**Endpoint:** `GET /portfolios/{profile}/history` **← DESCONECTADO**

**Destino:** `routes/(app)/portfolios/[profile]/+page.svelte`

**Implementacao:** Tab/secao "History" com timeline de snapshots (date, NAV, breach status, regime). Lazy load client-side via `$effect` + `AbortController`.

---

## Sessao 4 — Analytics + Pontuais + Bug Fix

### 4A. Analytics — Backtest + Correlation (4 endpoints)

**Endpoints:**
- `POST /analytics/backtest` **← DESCONECTADO**
- `GET /analytics/backtest/{run_id}` **← DESCONECTADO**
- `GET /analytics/correlation` **← DESCONECTADO**
- `GET /analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` **← DESCONECTADO**

**Destino:** `routes/(app)/analytics/+page.svelte` (928 linhas, Pareto SSE ja wired)

### Research Insights

**CRITICO: Backtest e SINCRONO no backend.** Em `analytics.py:126-157`, quando `cv=True`, executa `walk_forward_backtest()` dentro do request. Retorna imediato com status "completed" ou "failed". O legacy esperava polling (createPoller) mas o backend nao usa background task para backtest (diferente de Pareto que e async com SSE).

- **Implementacao correta:** Usar `LongRunningAction` (existe em `@netz/ui`, 350 linhas, props completas) com `slaSeconds={90}` + `slaMessage="Backtest is computing walk-forward folds. This is normal for long date ranges."`
- **Timeout risk:** 120s sync call pode exceder Railway proxy timeout (30-60s). Se falhar, converter para async+SSE
- `LongRunningAction` props confirmadas: `title`, `description`, `stream`, `slaSeconds`, `slaMessage`, `disabled`, `onStart`, `onRetry`, `onCancel`
- States: `idle → starting → in-flight → success | error | cancelled`
- Se `onStart` resolve imediatamente (sync backend), component transita direto para success — safe

**Backtest SLA Timeline:**
- 0–15s: Indeterminate progress (pulsing)
- 15–90s: Elapsed timer visible
- 90s+ (SLA exceeded): Warning banner — "This is taking longer than expected"
- `api.post()` com `options.timeoutMs = 180000` (3min) — override do default 15s

**Backtest result display (`BacktestResultDetail` schema):**
1. Summary KPI row: mean Sharpe (MetricCard, status ok/warn/breach), std Sharpe, positive fold ratio
2. Fold detail table: columns = fold #, period range, Sharpe, CVaR-95, max drawdown
3. `folds: BacktestFoldMetrics[]` (per-fold), `mean_sharpe`, `std_sharpe`, `positive_folds`

**Correlation Heatmap — CRIAR `CorrelationHeatmap.svelte` (componente novo, nao extension do existente):**
- `HeatmapChart.svelte` existente usa single-color gradient (`minColor → maxColor`). Correlation precisa diverging.
- Criar componente novo wrapping `ChartContainer` diretamente (mesmo pattern de todos charts em `@netz/ui`)
- `echarts-setup.ts` ja registra `HeatmapChart`, `VisualMapComponent`, `MarkLineComponent`, `MarkAreaComponent` — zero changes

**Diverging palette (7-stop Brewer RdBu, colorblind-safe):**
```typescript
visualMap: {
  min: -1, max: 1,
  calculable: true,
  orient: 'horizontal', left: 'center', bottom: 0,
  inRange: {
    color: ['#053061', '#2166ac', '#92c5de', '#f7f7f7', '#f4a582', '#d6604d', '#67001f'],
  },
  text: ['+1', '−1'],
}
```
- `#f7f7f7` neutral center — para dark mode, ler computed value de `--netz-surface-alt` via `getComputedStyle` (ECharts nao aceita CSS vars em `visualMap.color`)

**Heatmap 50x50 config:**
- `axisLabel: { rotate: 90, fontSize: 9, interval: 0, overflow: 'truncate', width: 80 }` para 50 labels
- `label: { show: false }` — nunca in-cell labels para 50x50
- `grid: { left: 120, right: 80, top: 20, bottom: 100 }` para rotated labels
- Canvas renderer (default) — correto para 2500 rects

**Click handler para pairwise drill-down:**
```typescript
// Via echarts.getInstanceByDom() — ChartContainer nao expoe instancia
const chart = echarts.getInstanceByDom(containerEl);
chart?.on('click', (params) => {
  if (params.componentType !== 'series') return;
  const [xi, yi] = params.data as [number, number, number];
  if (xi === yi) return;  // diagonal = self-correlation
  onPairSelect?.(labels[xi], labels[yi]);
});
```

**Greedy nearest-neighbor clustering (client-side, O(N²), N≤50):**
- Implementar em `frontends/wealth/src/lib/utils/correlation-sort.ts` (testavel, fora do componente)
- Start at index 0, greedily pick nearest (highest correlation) unvisited neighbor
- Apply permutation to both labels and matrix rows/columns
- Toggle checkbox no chart header: "Clustered" vs "Original order"
- Para Phase 2: considerar hierarchical clustering com `ml-hclust` npm (O(N³) = 125K ops, viable)

**Eigenvalue bar chart (Marchenko-Pastur):**
- Barras azuis (`#2166ac`) = signal (acima do threshold), cinza (`#94a3b8`) = noise (abaixo)
- `markLine`: dashed red line no threshold MP — `data: [{ yAxis: mpThreshold }]`
- `markArea` shading na regiao noise (bars abaixo do threshold)
- x-axis labels: `λ1, λ2, ...`
- Reference: Laloux et al. 1999, Plerou et al. 2002, Lopez de Prado "Advances in Financial ML" Fig 2.3

**Backend schema gap — EXTENSION NECESSARIA:**
- `ConcentrationAnalysis` model (`correlation/models.py`) precisa de: `mp_threshold: float`, `n_signal_eigenvalues: int`
- O quant engine ja computa ambos internamente em `_marchenko_pastur_denoise()` — so precisa expor
- Sem este campo, frontend teria que recomputar `(1 + sqrt(q))^2` — mas `q = N/T` onde `T` (window_days) nao e exposto

**Absorption ratio — MetricCard:**
```typescript
<MetricCard
  label="Absorption Ratio"
  value={formatPercent(absorptionRatio)}
  sublabel={`Top ${k} eigenvalues of ${n} total`}
  status={absorptionStatus === 'critical' ? 'breach' : absorptionStatus === 'warning' ? 'warn' : 'ok'}
/>
```
- `k = Math.max(1, Math.floor(n / 5))` (matches backend formula, Kritzman & Li 2010)
- Thresholds: >0.80 warning, >0.90 critical (ja no backend)

**Rolling correlation — `RegimeChart.svelte` ja existe e e reutilizavel:**
- Aceita `series` (line data) + `regimes` (markArea segments com RISK_ON/RISK_OFF/etc.)
- Backend endpoint `/analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` JA EXISTE
- yAxis: `min: -1, max: 1`, markLine em y=0
- Flow: heatmap cell click → lazy load rolling correlation → show em panel/sheet below heatmap

### 4B. Pontuais

| Endpoint | Destino | Implementacao |
|----------|---------|---------------|
| `DELETE /blended-benchmarks/{id}` | BlendedBenchmarkEditor.svelte | Botao Delete + ConsequenceDialog |
| `GET /universe/funds/{id}/audit-trail` | UniverseView.svelte | Toggle audit trail, lazy load |
| `GET /screener/runs/{run_id}` | screener/+page.svelte | Click run → expand detalhe |

### 4C. Bug fix: exposure path mismatch

**Arquivo:** `routes/(app)/exposure/+page.server.ts:11-12`
**Fix:** `/exposure/matrix` → `/wealth/exposure/matrix`

---

## Resumo

| Sessao | Foco | Endpoints | Risco | Mitigacao |
|--------|------|-----------|-------|-----------|
| 1 | Macro Intelligence | 6 | ALTO (rewrite) | Chart aditivo acima dos panels |
| 2 | Screener detail | 4 | MEDIO (file size) | Extrair ManagerDetailPanel primeiro |
| 3 | Model Portfolios + Facts | 5 | BAIXO (port) | 409 handling |
| 4 | Analytics + pontuais | 7 + 1 bug | MEDIO (backtest sync) | Nao implementar polling |
| **Total** | | **19 + 1 bug** | | **100% cobertura** |

---

## Regras Invariantes

1. **Provider-agnostico:** Nunca mencionar ESMA, SEC, BIS, IMF, FRED, OFR na UI
2. **ECharts obrigatorio:** svelte-echarts via ChartContainer, nunca Chart.js
3. **Formatacao @netz/ui:** Nunca `.toFixed()` / `.toLocaleString()`
4. **SSE via fetch:** Nunca `EventSource`
5. **ConsequenceDialog:** Toda acao destrutiva/aprovacao requer rationale
6. **Lazy load:** Tabs carregam dados on-demand com AbortController cleanup
7. **Mixed frequency:** Step function (forward-fill), NUNCA interpolar. Dados SORTED ASCENDING.
8. **Forecast visual:** Solid actual, dashed forecast, vertical markLine (nao markArea)
9. **Gate:** `make check` + `pnpm run check` verde antes de fechar cada sessao
10. **Macro page:** Aditivo primeiro (novo chart + panels existentes), remover panels em commit separado
11. **dataZoom:** `filterMode: 'weakFilter'` OBRIGATORIO — default `'filter'` faz series quarterly desaparecerem
12. **LTTB disabled:** Nao usar `sampling: 'lttb'` abaixo de 2000pts/serie — bug #15538 quebra tooltips
13. **Series limit:** Hard cap 8 series, warning em 6, "Switch to Table" como escape hatch
14. **`$state.raw()`:** Usar para arrays grandes de dados ECharts — evita deep proxy overhead
15. **ARIA tabs:** `role="tablist"` + `role="tab"` + `aria-selected` + arrow key navigation + `aria-busy` em lazy panels
16. **Empty states:** 3 tipos distintos (unavailable/empty-valid/error) — sempre explicar *why*, nunca so "no data"
