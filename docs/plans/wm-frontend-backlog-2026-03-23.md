# Backlog: Wealth Vertical — Frontend Wiring Completo
**Gerado em:** 2026-03-23
**Fonte:** `docs/plans/wm-coverage-plan-2026-03-23.md`
**Gate por sessao:** `make check` (backend) + `pnpm run check` (wealth frontend) verde

---

## Sumario de Tasks

### Backend (pre-requisitos bloqueantes)
- [x] WM-BE-01 — Expor `mp_threshold` + `n_signal_eigenvalues` em `ConcentrationAnalysis` DONE
- [x] WM-BE-02 — Criar endpoint `GET /analytics/rolling-correlation` DONE

### Sessao 1 — Macro Intelligence
- [x] WM-S1-PRE — Validar sort ascending nos endpoints macro (bug #20658 prep) DONE
- [x] WM-S1-01 — ECharts multi-grid: estrutura base do chart DONE
- [x] WM-S1-02 — Series picker: catalogo de indicadores (UI) DONE
- [x] WM-S1-03 — Wiring dos endpoints macro ao chart DONE
- [x] WM-S1-04 — Snapshot badge + additions no server load DONE
- [x] WM-S1-05 — Committee Reviews: list + generate + approve/reject DONE

### Sessao 2 — Screener Unificado
- [x] WM-S2-PRE — Extrair 7 componentes do screener (2473 linhas) DONE
- [x] WM-S2-01 — Tab Drift (`/managers/{crd}/drift`) DONE
- [x] WM-S2-02 — Tab Holdings/NPort (`/managers/{crd}/nport`) DONE
- [x] WM-S2-03 — Tab Docs (`/managers/{crd}/brochure/sections` + search) DONE
- [x] WM-S2-04 — Dynamic facets por asset type DONE

### Sessao 3 — Model Portfolios + Fact Sheets
- [ ] WM-S3-01 — `POST /model-portfolios`: dialog de criacao
- [ ] WM-S3-02 — Fact Sheets: generate + list + download
- [ ] WM-S3-03 — Portfolio History: tab de snapshots

### Sessao 4 — Analytics + Pontuais + Bug Fix
- [ ] WM-S4-01 — `CorrelationHeatmap.svelte`: componente novo (diverging palette)
- [ ] WM-S4-02 — Correlation page: wiring `GET /analytics/correlation`
- [ ] WM-S4-03 — Backtest: wiring `POST /analytics/backtest` com `LongRunningAction`
- [ ] WM-S4-04 — Rolling correlation drill-down (deps: WM-BE-02, WM-S4-02)
- [ ] WM-S4-05 — Pontuais: DELETE benchmark + audit-trail + screener run detail
- [ ] WM-S4-06 — Bug fix: exposure path mismatch

---

## Detalhe das Tasks

---

### WM-BE-01 — Expor `mp_threshold` + `n_signal_eigenvalues` em `ConcentrationAnalysis`

**Tipo:** Backend
**Sessao:** Pre-requisito para WM-S4-02 / WM-S4-04
**Arquivo:** `vertical_engines/wealth/correlation/models.py`
**Bloqueante para:** WM-S4-02 (eigenvalue bar chart), WM-S4-04 (rolling correlation com MP line)

**Contexto:**
O `quant_engine` ja computa `mp_threshold` e `n_signal_eigenvalues` internamente em `_marchenko_pastur_denoise()`. O campo nao e exposto no schema de resposta. O frontend nao pode recomputar porque `q = N/T` requer `T` (window_days) que tambem nao e exposto.

**Mudanca:**
Adicionar ao modelo `ConcentrationAnalysis`:
```python
mp_threshold: float          # Marchenko-Pastur upper bound lambda_plus
n_signal_eigenvalues: int    # eigenvalues above mp_threshold
```
Propagar do resultado interno do quant_engine para o schema de resposta.

**Acceptance criteria:**
- `GET /analytics/correlation` retorna `mp_threshold` e `n_signal_eigenvalues` no objeto `concentration`
- Valores batem com o que o quant_engine computa internamente
- `make check` verde

---

### WM-BE-02 — Criar endpoint `GET /analytics/rolling-correlation`

**Tipo:** Backend
**Sessao:** Pre-requisito para WM-S4-04
**Arquivo:** `app/domains/wealth/routes/analytics.py` (novo endpoint)
**Bloqueante para:** WM-S4-04

**Contexto:**
`RegimeChart.svelte` ja existe em `@netz/ui` e aceita `series` + `regimes` (markArea segments). O endpoint `/analytics/correlation-regime/{profile}/pair/{inst_a}/{inst_b}` JA EXISTE e retorna pairwise regime. Falta um endpoint de rolling correlation simples (sem regime) para o drill-down ao clicar celula do heatmap.

**Contrato esperado:**
```
GET /analytics/rolling-correlation?inst_a={id}&inst_b={id}&profile={profile}&window_days={int}
Response: { dates: str[], values: float[], instrument_a: str, instrument_b: str }
```

**Acceptance criteria:**
- Endpoint retorna serie temporal de correlacao rolling entre dois instrumentos
- `organization_id` enforced (RLS — tabela `nav_timeseries` e org-scoped)
- `window_days` default 90, max 252
- `make check` verde

---

### WM-S1-PRE — Validar sort ascending nos endpoints macro

**Tipo:** Pre-requisito de sessao / verificacao
**Sessao:** 1
**Risco:** Bug ECharts #20658 — `step: 'end'` inverte direction com dados descending

**O que fazer:**
Verificar nos handlers de `/macro/bis`, `/macro/imf`, `/macro/treasury`, `/macro/ofr` que as series retornam com `date` sorted ascending (oldest first). Se algum retornar descending, adicionar `.sort(key=lambda x: x.date)` antes de serializar.

**Acceptance criteria:**
- Todos os endpoints macro retornam arrays com `date` ascending
- Verificado via teste ou inspecao manual de resposta

---

### WM-S1-01 — ECharts multi-grid: estrutura base do chart

**Tipo:** Frontend — componente
**Sessao:** 1
**Arquivo:** `routes/(app)/macro/+page.svelte` + `lib/components/macro/MacroChart.svelte` (novo)
**Deps:** WM-S1-PRE

**O que implementar:**
- `MacroChart.svelte` wrapping `ChartContainer` com dois grids (main 55% + sub-chart 15%)
- Dual Y-axis: left `%` (gridIndex 0), right `absolute` (gridIndex 0), sub-chart volume (gridIndex 1)
- `axisPointer.link: [{ xAxisIndex: 'all' }]` — MUST be at root level
- `dataZoom` com `filterMode: 'weakFilter'` OBRIGATORIO em ambos os entries (slider + inside)
- Time range buttons externos: 1M, 3M, 6M, 1Y, 2Y — desabilitar 3Y/5Y/Max
  - Implementar via `echarts.getInstanceByDom(containerEl)` + `dispatchAction dataZoom`
- `scale: true` + `alignTicks: true` nos eixos Y
- `animation: false` no load inicial
- `$state.raw()` para arrays de dados de series

**Mixed frequency:**
- `step: 'end'` para monthly/quarterly/annual
- `step: false` para daily
- `connectNulls: false`
- Banner dismissivel "Mixed frequencies — quarterly series forward-filled" quando chart tem daily + quarterly

**Performance:**
- `showSymbol: false` para series daily densas
- NAO usar `sampling: 'lttb'` (bug #15538)
- `progressive: 0`

**Acceptance criteria:**
- Chart renderiza com 2+ series de frequencias diferentes sem quebrar tooltip
- Zoom nao remove series quarterly
- `pnpm run check` verde

---

### WM-S1-02 — Series picker: catalogo de indicadores

**Tipo:** Frontend — componente
**Sessao:** 1
**Arquivo:** `lib/components/macro/SeriesPicker.svelte` (novo)
**Deps:** WM-S1-01

**O que implementar:**
- Catalogo com 11 grupos (~120 series), taxonomia Bloomberg ECST
- Hybrid UX: search-first (flat results com group labels separadores) + browse colapsado por default
- Region chips: All | US | Europe | Asia | EM | Global — single-select radio (filtra catalogo, nao o chart)
- Frequency chips: All | Daily | Monthly | Quarterly
- Star icon por indicador — favoritos backed por `user_indicator_favorites` (carregado no server load)
- Frequency badge pill (`D`, `M`, `Q`, `A`) em cada entry do legend
- Hard cap 8 series:
  - Warning banner em 6: "Approaching series limit"
  - Botao "Add" desabilitado em 8 com tooltip "Maximum 8 series reached"
  - "Switch to Data Table" affordance ao lado do chart

**State:**
```typescript
type MacroChartState = {
  selectedSeries: Set<string>;
  timeRange: '1M' | '3M' | '6M' | '1Y' | '2Y';
  region: string;
  scaleMode: 'percent' | 'absolute' | 'log';
};
```
Derivar ECharts option como unico `$derived.by()` deste state. Debounce 150ms com cleanup `return () => clearTimeout(timer)`.

**Acceptance criteria:**
- Adicionar/remover series atualiza chart dentro de 150ms
- Ao atingir 8 series, botao desabilita com tooltip
- `pnpm run check` verde

---

### WM-S1-03 — Wiring dos endpoints macro ao chart

**Tipo:** Frontend — wiring
**Sessao:** 1
**Arquivo:** `routes/(app)/macro/+page.svelte` + `+page.server.ts`
**Deps:** WM-S1-01, WM-S1-02
**Endpoints:**
- `GET /macro/bis` (credit gap, DSR, property)
- `GET /macro/imf` (GDP, inflation, fiscal)
- `GET /macro/treasury` (rates, debt, auctions)
- `GET /macro/ofr` (hedge fund leverage, stress)
- `GET /macro/scores` (ja no server load — verificar)
- `GET /macro/regime` (ja no server load — verificar)
- `GET /risk/macro` (ja no server load — verificar)

**Race condition — usar pattern 2 (AbortController em $effect):**
```typescript
$effect(() => {
  const controller = new AbortController();
  // fetch series
  return () => controller.abort();
});
```
Comparar series ID retornado contra `selectedSeries` atual antes de atualizar.

**Forecast IMF WEO:**
- Dois series separados: actual (solid) + forecast (dashed)
- Repetir ultimo ponto actual como primeiro ponto forecast
- `markLine` vertical no boundary (NAO `markArea` — bugs #15708/#3637)
- Legend suffix "(proj.)" na serie forecast

**Acceptance criteria:**
- Selecionar qualquer indicador dos 4 endpoints carrega dados no chart
- Forecast IMF renderiza com linha dashed + markLine vertical
- Sem race condition ao trocar series rapidamente
- `pnpm run check` verde

---

### WM-S1-04 — Snapshot badge + additions no server load

**Tipo:** Frontend — wiring
**Sessao:** 1
**Arquivo:** `routes/(app)/macro/+page.server.ts`
**Endpoint:** `GET /macro/snapshot` (DESCONECTADO)

**O que implementar:**
- Adicionar `api.get("/macro/snapshot")` no server load
- Regime badge no header: `[Regime: RISK-ON ●]` com cor por regime (risk-on verde, risk-off vermelho, transicao amarelo)
- Badges por regiao: US | Europe | EM | Global

**Acceptance criteria:**
- Badge de regime carrega no SSR (visivel sem JS)
- `pnpm run check` verde

---

### WM-S1-05 — Committee Reviews: list + generate + approve/reject

**Tipo:** Frontend — wiring
**Sessao:** 1
**Arquivo:** `routes/(app)/macro/+page.svelte`
**Deps:** WM-S1-04
**Endpoints:**
- `GET /macro/reviews` (DESCONECTADO) — params: `limit=20`, `offset`, `status`
- `POST /macro/reviews/generate` (DESCONECTADO) — requer `INVESTMENT_TEAM`
- `PATCH /macro/reviews/{id}/approve` (DESCONECTADO) — requer `DIRECTOR|ADMIN`
- `PATCH /macro/reviews/{id}/reject` (DESCONECTADO) — requer `DIRECTOR|ADMIN`

**O que implementar:**
1. Adicionar `api.get("/macro/reviews")` no server load
2. Secao "Committee Reviews" abaixo do chart
3. Lista: data, status badge, resumo truncado
4. "Generate Review" com `ConsequenceDialog`, loading state + timeout generoso (backpressure via `require_content_slot()`)
5. Approve/Reject com `ConsequenceDialog`, rationale obrigatorio (`rationaleMinLength={10}`)
6. Tratar 409 de approve/reject concorrente: toast "Review already processed" + refresh lista
7. Role-gate: mostrar approve/reject apenas para `DIRECTOR|ADMIN`

**Acceptance criteria:**
- Reviews listam corretamente paginados
- Approve/reject funcionam com rationale
- 409 tratado sem crash
- `pnpm run check` verde

---

### WM-S2-PRE — Extrair 7 componentes do screener (2473 linhas)

**Tipo:** Refactor — pre-requisito obrigatorio
**Sessao:** 2
**Arquivo:** `routes/(app)/screener/+page.svelte`
**Risco:** MEDIO — sem esta extracao, adicionar tabs quebra o arquivo

**7 componentes a extrair (ranges aproximados):**

| Componente novo | Linhas | Conteudo |
|-----------------|--------|----------|
| `InstrumentFilterSidebar.svelte` | ~562–653 | Filter form + chip grid + facet summary |
| `ManagerFilterSidebar.svelte` | ~654–798 | Manager filters + funnel + fund filters + last run |
| `InstrumentTable.svelte` | ~806–901 | Search results table + pagination |
| `PeerComparisonView.svelte` | ~902–951 | Compare result cards + sector grid |
| `ManagerHierarchyTable.svelte` | ~952–1087 | Manager/fund hierarchical table + pagination |
| `ManagerDetailPanel.svelte` | ~1099–1371 | Manager detail + 4 tab snippets |
| `InstrumentDetailPanel.svelte` | ~1391–1432 | Fund detail ContextPanel |

**State que FICA no page:** `activeMode`, `panelOpen`, `panelMode`, `selectedInstrument`, `fundFilters`, `expandedManagers`, `selectedManagers`.

**Panel state via context (nao prop drilling):**
```typescript
// +page.svelte
const panelState = $state({ open: false, instrument: null, crd: null });
setContext('screener:panel', panelState);
```

**Acceptance criteria:**
- Screener funciona identicamente ao pre-refactor
- Arquivo principal abaixo de 400 linhas
- `pnpm run check` verde
- Nenhum teste existente quebrado (`make check` verde)

---

### WM-S2-01 — Tab Drift

**Tipo:** Frontend — wiring
**Sessao:** 2
**Arquivo:** `lib/components/screener/DriftTab.svelte` (novo)
**Deps:** WM-S2-PRE
**Endpoint:** `GET /manager-screener/managers/{crd}/drift` (DESCONECTADO)

**O que implementar:**
- Componente isolado com `$effect` reativo + `AbortController` cleanup
- Bar chart ECharts: turnover timeline por quarter
- Churn metrics (top gainers/losers de posicao)
- Empty state se `crd` null: "Institutional data unavailable — This manager is not registered with the SEC."
- Tab state preservation: manter tab ativa ao trocar instrumento

**Cache:**
```typescript
import { SvelteMap } from 'svelte/reactivity';
// cache por `${crd}:drift`
```

**Acceptance criteria:**
- Drift carrega on-demand ao entrar na tab
- AbortController cancela fetch ao sair da tab
- `pnpm run check` verde

---

### WM-S2-02 — Tab Holdings/NPort

**Tipo:** Frontend — wiring
**Sessao:** 2
**Arquivo:** `lib/components/screener/HoldingsTab.svelte` (novo)
**Deps:** WM-S2-PRE
**Endpoint:** `GET /manager-screener/managers/{crd}/nport` (DESCONECTADO)

**O que implementar:**
- Merge com dados N-PORT quando disponivel (mais recente que quarterly 13F)
- Paginacao server-side (`page_size=50`) — wire up pagination controls
- Label "Holdings" na tab, nunca "13F" ou "N-PORT"
- 3 empty states:
  1. No CIK: "Institutional data unavailable..."
  2. CIK existe, 0 holdings: "No holdings on record. Coverage updates quarterly."
  3. Fetch error: mensagem + Retry

**Acceptance criteria:**
- Paginacao funciona
- Merge N-PORT exibe data mais recente quando disponivel
- `pnpm run check` verde

---

### WM-S2-03 — Tab Docs

**Tipo:** Frontend — wiring
**Sessao:** 2
**Arquivo:** `lib/components/screener/DocsTab.svelte` (novo)
**Deps:** WM-S2-PRE
**Endpoints:**
- `GET /manager-screener/managers/{crd}/brochure/sections` (DESCONECTADO)
- `GET /manager-screener/managers/{crd}/brochure` com search (DESCONECTADO)

**O que implementar:**
- Lista de secoes do documento regulatorio
- Search com debounce 300ms
- Label "Docs" na tab, nunca "ADV Part 2A Brochure"

**Acceptance criteria:**
- Search retorna resultados relevantes com debounce
- `pnpm run check` verde

---

### WM-S2-04 — Dynamic facets por asset type

**Tipo:** Frontend — enhancement
**Sessao:** 2
**Arquivo:** `lib/components/screener/InstrumentFilterSidebar.svelte`
**Deps:** WM-S2-PRE

**O que implementar:**
```typescript
const CHIP_FACETS: Record<ChipKey, (keyof ScreenerFacets)[]> = {
  all:         ['geographies', 'domiciles', 'currencies'],
  us_funds:    ['geographies', 'currencies', 'strategies'],
  ucits:       ['domiciles', 'currencies'],
  etfs:        ['geographies', 'currencies', 'asset_classes'],
  bonds:       ['geographies', 'currencies', 'credit_ratings', 'maturities'],
  equities:    ['geographies', 'currencies', 'sectors'],
  hedge_funds: ['geographies', 'currencies', 'strategies'],
};
```
- Revelar facets com `transition:slide`
- Desabilitar (nao esconder) facets inaplicaveis com tooltip "Applies to bonds only"

**Acceptance criteria:**
- Trocar asset type atualiza facets visiveis com animacao
- `pnpm run check` verde

---

### WM-S3-01 — `POST /model-portfolios`: dialog de criacao

**Tipo:** Frontend — wiring
**Sessao:** 3
**Arquivo:** `routes/(app)/model-portfolios/+page.svelte`
**Endpoint:** `POST /model-portfolios` (DESCONECTADO)

**O que implementar:**
1. Botao "New Portfolio" no header da listing page
2. Dialog com form: `profile`, `display_name`, `description`, `benchmark_composite`, `inception_date`, `backtest_start_date`
3. POST → redirect para `/model-portfolios/{new_id}`
4. Tratar 409: "A portfolio with this profile already exists." — inline error com dismiss (nao toast)
5. Role-gate: botao visivel apenas para `INVESTMENT_TEAM`

**409 pattern (padrao do codebase — confirmado em `RebalancingTab.svelte`):**
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

**Acceptance criteria:**
- Criacao redireciona para detail page
- 409 exibe erro inline sem crash
- `pnpm run check` verde

---

### WM-S3-02 — Fact Sheets: generate + list + download

**Tipo:** Frontend — wiring
**Sessao:** 3
**Arquivo:** `routes/(app)/model-portfolios/[portfolioId]/+page.svelte`
**Endpoints:**
- `POST /fact-sheets/model-portfolios/{portfolio_id}` (DESCONECTADO)
- `GET /fact-sheets/model-portfolios/{portfolio_id}` (DESCONECTADO)
- `GET /fact-sheets/{fact_sheet_path}/download` (DESCONECTADO)

**O que implementar:**
1. Secao "Fact Sheets" abaixo de track-record/stress
2. Botao "Generate Fact Sheet" com `language=pt|en` (default pt)
3. Lista com data + botao download por item (`downloadingId` para loading state per-item)
4. Feature-gate: `FEATURE_WEALTH_FACT_SHEETS`
5. Filename via `Content-Disposition` header

**Blob download — pattern canonico do codebase (confirmado em `content/+page.svelte`):**
- `URL.revokeObjectURL()` imediatamente apos `.click()`
- Alternativa: `api.getBlob(path)` do `NetzApiClient`

**Acceptance criteria:**
- Generate dispara POST com loading state
- Download inicia blob correto com filename do Content-Disposition
- `pnpm run check` verde

---

### WM-S3-03 — Portfolio History: tab de snapshots

**Tipo:** Frontend — wiring
**Sessao:** 3
**Arquivo:** `routes/(app)/portfolios/[profile]/+page.svelte`
**Endpoint:** `GET /portfolios/{profile}/history` (DESCONECTADO)

**O que implementar:**
- Tab ou secao "History" com timeline de snapshots
- Colunas: date, NAV, breach status, regime
- Lazy load client-side via `$effect` + `AbortController`

**Acceptance criteria:**
- History carrega on-demand ao entrar na tab
- `pnpm run check` verde

---

### WM-S4-01 — `CorrelationHeatmap.svelte`: componente novo

**Tipo:** Frontend — componente
**Sessao:** 4
**Arquivo:** `packages/ui/src/lib/charts/CorrelationHeatmap.svelte` (novo)
**Deps:** WM-BE-01

**Contexto:**
`HeatmapChart.svelte` existente usa single-color gradient. Correlation precisa diverging blue-white-red. Criar componente novo wrapping `ChartContainer` diretamente (nao extension do existente). `echarts-setup.ts` ja registra `HeatmapChart`, `VisualMapComponent`, `MarkLineComponent` — zero changes.

**Diverging palette (Brewer RdBu, colorblind-safe):**
```typescript
visualMap: {
  min: -1, max: 1,
  calculable: true,
  orient: 'horizontal', left: 'center', bottom: 0,
  inRange: {
    color: ['#053061','#2166ac','#92c5de','#f7f7f7','#f4a582','#d6604d','#67001f'],
  },
  text: ['+1', '−1'],
}
```
Nota: `#f7f7f7` para light mode. Dark mode: ler `--netz-surface-alt` via `getComputedStyle` (ECharts nao aceita CSS vars em `visualMap.color`).

**Config 50x50:**
- `axisLabel: { rotate: 90, fontSize: 9, interval: 0, overflow: 'truncate', width: 80 }`
- `label: { show: false }` — nunca in-cell labels para 50x50
- `grid: { left: 120, right: 80, top: 20, bottom: 100 }`

**Click handler (ChartContainer nao expoe instancia):**
```typescript
const chart = echarts.getInstanceByDom(containerEl);
chart?.on('click', (params) => {
  if (params.componentType !== 'series') return;
  const [xi, yi] = params.data as [number, number, number];
  if (xi === yi) return;
  onPairSelect?.(labels[xi], labels[yi]);
});
```

**Clustering (client-side):**
- Greedy nearest-neighbor em `lib/utils/correlation-sort.ts` (testavel, fora do componente)
- Toggle "Clustered / Original order" no chart header

**Props exportadas:** `matrix: number[][]`, `labels: string[]`, `onPairSelect?: (a: string, b: string) => void`

**Acceptance criteria:**
- Diverging palette renderiza corretamente em light e dark mode
- Click em celula dispara `onPairSelect` com os dois labels
- Clustering toggle reordena matrix e labels
- `pnpm run check` verde

---

### WM-S4-02 — Correlation page: wiring `GET /analytics/correlation`

**Tipo:** Frontend — wiring
**Sessao:** 4
**Arquivo:** `routes/(app)/analytics/+page.svelte`
**Deps:** WM-BE-01, WM-S4-01
**Endpoint:** `GET /analytics/correlation` (DESCONECTADO)

**O que implementar:**
1. Usar `CorrelationHeatmap.svelte` (WM-S4-01)
2. Absorption ratio como `MetricCard`:
   ```typescript
   <MetricCard
     label="Absorption Ratio"
     value={formatPercent(absorptionRatio)}
     sublabel={`Top ${k} eigenvalues of ${n} total`}
     status={absorptionStatus === 'critical' ? 'breach' : absorptionStatus === 'warning' ? 'warn' : 'ok'}
   />
   ```
   Thresholds: >0.80 warning, >0.90 critical
3. Eigenvalue bar chart (Marchenko-Pastur denoising):
   - Barras azuis `#2166ac` = signal (acima de `mp_threshold`)
   - Barras cinza `#94a3b8` = noise
   - `markLine` dashed red no threshold MP
   - x-axis: `λ1, λ2, ...`

**Acceptance criteria:**
- Heatmap renderiza dados reais do endpoint
- Absorption ratio exibe status correto
- Eigenvalue chart mostra linha MP no threshold correto
- `pnpm run check` verde

---

### WM-S4-03 — Backtest: wiring `POST /analytics/backtest`

**Tipo:** Frontend — wiring
**Sessao:** 4
**Arquivo:** `routes/(app)/analytics/+page.svelte`
**Endpoints:**
- `POST /analytics/backtest` (DESCONECTADO)
- `GET /analytics/backtest/{run_id}` (DESCONECTADO)

**CRITICO: Backtest e SINCRONO no backend.** NAO implementar polling. `LongRunningAction` com `slaSeconds={90}`.

**Implementacao:**
```typescript
<LongRunningAction
  title="Walk-Forward Backtest"
  description="Running cross-validated backtest..."
  slaSeconds={90}
  slaMessage="Backtest is computing walk-forward folds. This is normal for long date ranges."
  onStart={runBacktest}
/>
```
`api.post()` com `options.timeoutMs = 180000` (3min, override do default 15s).

**Timeline SLA:**
- 0–15s: Indeterminate progress (pulsing)
- 15–90s: Elapsed timer visivel
- 90s+: Warning banner "This is taking longer than expected"

**Backtest result display (`BacktestResultDetail`):**
1. KPI row: mean Sharpe (MetricCard), std Sharpe, positive fold ratio
2. Fold detail table: fold #, period range, Sharpe, CVaR-95, max drawdown

**Timeout risk:** Se Railway proxy timeout (30-60s) bloquear antes do 90s SLA, converter para async+SSE (mesmo pattern do Pareto).

**Acceptance criteria:**
- `LongRunningAction` exibe elapsed timer apos 15s
- Resultado exibe KPIs e tabela de folds
- `pnpm run check` verde

---

### WM-S4-04 — Rolling correlation drill-down

**Tipo:** Frontend — wiring
**Sessao:** 4
**Arquivo:** `routes/(app)/analytics/+page.svelte`
**Deps:** WM-BE-02, WM-S4-02
**Endpoint:** `GET /analytics/rolling-correlation` (criado em WM-BE-02)

**O que implementar:**
- Click em celula do heatmap → lazy load rolling correlation
- Usar `RegimeChart.svelte` existente (aceita `series` + `regimes`)
- yAxis: `min: -1, max: 1`, `markLine` em y=0
- Panel ou sheet abaixo do heatmap com title "Rolling Correlation: {inst_a} vs {inst_b}"
- `AbortController` cancela fetch anterior ao clicar nova celula

**Acceptance criteria:**
- Click em celula carrega rolling correlation no panel
- Trocar celula cancela fetch anterior (sem race condition)
- `pnpm run check` verde

---

### WM-S4-05 — Pontuais

**Tipo:** Frontend — wiring
**Sessao:** 4

| Task | Endpoint | Arquivo | Implementacao |
|------|----------|---------|---------------|
| WM-S4-05a | `DELETE /blended-benchmarks/{id}` | `BlendedBenchmarkEditor.svelte` | Botao Delete + `ConsequenceDialog` com rationale |
| WM-S4-05b | `GET /universe/funds/{id}/audit-trail` | `UniverseView.svelte` | Toggle "Audit Trail", lazy load on open, `AbortController` |
| WM-S4-05c | `GET /screener/runs/{run_id}` | `screener/+page.svelte` | Click em run na lista → expand detalhe inline |

**Acceptance criteria por sub-task:**
- 05a: Delete requer ConsequenceDialog, remove item da lista apos confirmacao
- 05b: Toggle carrega/descarta audit trail on-demand
- 05c: Click expande detalhe sem navegar
- `pnpm run check` verde

---

### WM-S4-06 — Bug fix: exposure path mismatch

**Tipo:** Bug fix
**Sessao:** 4
**Arquivo:** `routes/(app)/exposure/+page.server.ts`, linhas 11-12
**Prioridade:** Alta — exposure page esta quebrando silenciosamente

**Fix:**
```diff
- const matrix = await api.get("/exposure/matrix");
+ const matrix = await api.get("/wealth/exposure/matrix");
```

**Acceptance criteria:**
- Exposure page carrega sem erro 404
- `pnpm run check` verde

---

## Ordem de Execucao Recomendada

```
WM-BE-01  ──────────────────────────────────────────► WM-S4-02 ──► WM-S4-04
WM-BE-02  ──────────────────────────────────────────────────────► WM-S4-04
WM-S1-PRE ──► WM-S1-01 ──► WM-S1-02 ──► WM-S1-03 ──► WM-S1-04 ──► WM-S1-05
WM-S2-PRE ──► WM-S2-01 ──► WM-S2-02 ──► WM-S2-03
              WM-S2-04  (paralelo apos WM-S2-PRE)
WM-S3-01 ──► WM-S3-02
WM-S3-03  (independente)
WM-S4-01 ──► WM-S4-02 ──► WM-S4-04
             WM-S4-03   (independente)
             WM-S4-05   (independente)
WM-S4-06  (independente — fix imediato)
```

**Total: 2 backend + 20 frontend = 22 tasks**
