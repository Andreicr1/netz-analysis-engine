# Portfolio Builder — Flexible Columns Layout — Design Spec

**Date:** 2026-04-08
**Status:** ✅ **Phase A + B — CONCLUÍDAS e mergeadas em `main`.** Phase C e demais itens desta spec movidos para backlog explícito (§6.4 + §10) — tratamento em sprints separadas.
**Owner:** Andrei (Netz)
**Branch:** `feat/wealth-portfolio-flex-columns` (merged via `--no-ff` em `main` on 2026-04-08)
**Base:** `main` (post Stability Guardrails + Onda 0 + PR-UX-09 sanitisation)
**Sprint sizing (planned):** S + L + M + S (4 phases)
**Actual delivery (Phase A + B):** 8 commits, 3,634 lines added, 16 files touched

---

## §0 — Princípio Fundador

> **Em Wealth Management institucional, densidade de informação na
> área de decisão é obrigação — não preferência estética.** Um PM que
> precisa olhar um modal para conhecer o risco, o custo e a correlação
> de um fundo antes de decidir alocá-lo não está fazendo decisão de
> portfólio — está fazendo navegação. Todo candidato à alocação deve
> mostrar sua ficha tática na linha, na primeira visualização, sem
> clique.

Essa frase é a navalha de Occam deste sprint. Sempre que houver dúvida
entre "esconder dado para poupar pixel" e "mostrar dado e exigir
largura", a frase decide pelo dado. Ela transforma o que seria
preferência de layout em regra de produto.

---

## §1 — Estados do Layout

O Portfolio Builder adota o padrão **Flexible Columns Layout** (FCL)
inspirado em SAP Fiori, mas adaptado ao fluxo construtivo de Wealth
(não é master-detail — é master-workspace-analytics). Três estados
adaptativos:

### 1.1 — Estado A — Landing (1 coluna)

**Quando:** PM entrou em `/portfolio` sem model selecionado.
**Escopo desta sprint:** **ADIADO.** O fallback atual (Builder com
allocation blocks vazios + Model picker na pill "Models") é aceitável.
Foco total em B+C.

### 1.2 — Estado B — Workspace de construção (2 colunas, **default**)

**Quando:** PM selecionou ou criou um model portfolio.
**Proporção:** `45% Universe / 55% Builder`.
**Redimensionamento:** splitter vertical drag-handle, clamp `[min 35%, max 55%]` para Universe.

**Coluna esquerda — Universe (expandida):**
  - Header fino: search, filter pills (Asset Class, Region, Liquidity), sort dropdown, count "N approved funds".
  - Tabela densa com **12 colunas Tier 1** (ver §3).
  - Linha altura ~44px, confortável para scan, ~15 linhas visíveis sem scroll.
  - Agrupamento por BLOCK_GROUPS (Cash, Equities, Fixed Income, Alternatives) — headers colapsáveis.
  - Virtual scroll se `rows > 50`.
  - Hover na linha → mini-card lateral com Tier 2 (holdings, manager tenure, regime fit, fee breakdown).
  - Click na linha → triggera Estado C com fund ativo.
  - Drag source HTML5 nativo (preservado do `UniversePanel.svelte` atual).

**Coluna direita — Builder:**
  - Action bar: `[Construct] [Stress Test] [View Chart] [Compare] [Export]`.
  - **Allocation blocks como cards grandes** (altura mínima 120px por block) — cada um mostra: target %, current %, drift bar, funds dentro, weighted fee, weighted Netz score.
  - Drop targets visualmente generosos.
  - Summary bar no topo: `Total allocated %`, `Cash remaining`, `#funds`, `weighted ER`, `portfolio risk-adj estimate`.
  - **Sem chart neste estado** — libera espaço para os blocks respirarem.

### 1.3 — Estado C — Workspace + Analytics (3 colunas, on-demand)

**Quando:** três triggers distintos:
  1. Click em linha do Universe → tab `Fund` ativa com fact sheet do fundo.
  2. Click em "View Chart" no Builder action bar → tab `Portfolio` ativa com MainPortfolioChart + performance attribution.
  3. Click em "Stress Test" no Builder action bar → tab `Stress` ativa com scenarios em plain-English.

**Proporção:** `30% Universe / 40% Builder / 30% Analytics`.

**Coluna direita — Analytics (multi-tab):**
  - Tab `Fund` — fact sheet drill-down, top holdings, rolling vol, peer comparison, CTA "Add to Builder".
  - Tab `Portfolio` — chart NAV sintético, drawdown, sector/geo breakdown, concentração.
  - Tab `Stress` — 4 scenarios (GFC, COVID, Taper, Rate Shock) em plain-English narratives.
  - Tab `Compare` — slots para até 3 fundos side-by-side (multi-select Ctrl+click no Universe).

Tabs são **sticky dentro da sessão** (in-memory, não localStorage). Fechar e reabrir a coluna preserva a última tab ativa.

**Reset entre navegações:** quando o PM sai de `/portfolio` e volta, o Estado volta para **B** e `selectedAnalyticsFund` é limpo. Isso é regra explícita (não sobreviver a navegação).

### 1.4 — Transições

| De → Para | Trigger | Animação |
|---|---|---|
| A → B | Model selecionado | Fade-in Builder (200ms ease-out) |
| B → C | Click fundo / View Chart / Stress Test | Slide-in 3ª coluna da direita (240ms cubic-bezier) + Universe contrai suave |
| C → B | Close button no header da 3ª coluna OU Esc | Slide-out reverso |
| B → A | "Back to Models" breadcrumb (follow-up) | N/A nesta sprint |

**Preservação de contexto durante transições:**
  - Scroll position independente por coluna (nenhuma coluna perde scroll por transição de estado).
  - **Drag state atravessa transição**: se o PM inicia drag no Universe e a 3ª coluna abre por qualquer motivo, o `dataTransfer` não é cancelado.
  - **O DOM das três colunas nunca é desmontado** (ver §2.1 — implementação CSS Grid com `0fr`).

### 1.5 — Responsive breakpoints

| Viewport | Comportamento |
|---|---|
| `≥ 1440px` | 3-col normal (30/40/30). Estado C desliza lado-a-lado com B. |
| `1200-1440px` | Estado C vira drawer overlay (absolute, full-height) SOBRE o Builder — não empurra. |
| `1024-1200px` | Estado B força 50/50. Estado C sempre drawer. |
| `768-1024px` | Fallback single-column ao layout atual com sub-pills `Models \| Universe \| Policy`. |
| `< 768px` | Read-only. Redireciona para tela de Models com aviso *"Portfolio construction requires a desktop browser."* |

Mobile de construção é anti-padrão institucional explícito — decisão do Engenheiro-Chefe.

---

## §2 — Decisões Arquiteturais

### 2.1 — Layout adaptativo: CSS Grid com `grid-template-columns` reativo

**Recomendação validada:** CSS Grid + `grid-template-columns` derivado de `layoutState`. As três colunas **sempre renderizam no DOM**; visibilidade é controlada por largura (`0fr` + `overflow: hidden`).

```
layoutState === 'two-col':
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) 0fr

layoutState === 'three-col':
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 2.2fr) minmax(0, 1.4fr)
```

- Animação via `transition: grid-template-columns 240ms cubic-bezier(.4,0,.2,1)` — CSS puro, estável em Chrome/Edge/Safari 16+ desde 2023.
- **Evitar `display: none` ou `{#if}`** aninhados — quebrariam drag state, scroll position e ciclo de vida do LayerChart (remontagem cara). `0fr + visibility: hidden + pointer-events: none` é idiomático.
- **Container queries** sobre o wrapper do layout, não media queries. O cage do shell (`calc(100vh - 72px)`) define a geometria, não o viewport.

### 2.2 — Layout state: derivado, não armazenado

**Regra:**

```
layoutState = $derived(
  selectedAnalyticsFund ? 'three-col' :
  workspace.portfolioId ? 'two-col' :
  'landing'
)
```

Armazenar `layoutState` cria classes de bug tipo *"three-col mas selectedAnalyticsFund é null"*. Derivar elimina isso. Single source of truth é o fato observável (`selectedAnalyticsFund` no store), não a representação (`layoutState`).

### 2.3 — Tabela Universe: rejeitar `@tanstack/svelte-table`

**Recomendação validada:** descartar `@tanstack/svelte-table@9.0.0-alpha.10` (breakage conhecido com Svelte 5 runes — memória `project_frontend_platform.md`). Usar:

  - `<table>` HTML semântico
  - `@tanstack/svelte-virtual@^3.0.0` (já instalado, compatível com runes)
  - Sort/filter/group caseiro em `$derived.by()` — pipeline funcional `rows → filter → sort → group → virtualize`

**~40 linhas a mais** que uma headless lib, sem dependência quebrada. Trade-off institucional correto.

**Padrão de integração Svelte 5:**
  - `Virtualizer` da TanStack é imperativo — guardar instância em variável normal, expor `getVirtualItems()` via `$derived(virtualizer.getVirtualItems())`.
  - `count` do virtualizer reativo via `$effect(() => virtualizer.setOptions({ count: filteredRows.length }))`.
  - Sticky header: `<thead>` FORA do spacer do virtualizer, `position: sticky; top: 0` no parent com `overflow-y: auto`.
  - Agrupamento por asset class: pre-compute em `$derived.by()` retornando `Array<{ type: 'header' | 'row', payload }>`, depois virtualizar a lista achatada.

### 2.4 — Drag-drop: manter HTML5 nativo

**Recomendação validada:** manter `e.dataTransfer.setData("text/plain", fund.instrument_id)` como source, allocation blocks como drop targets. **Zero nova dependência.**

Reorder intra-block dentro do Builder é **fora de escopo** desta sprint (adiado).

### 2.5 — Charts: LayerChart

**Decisão do Andrei (2026-04-08):** adotar **LayerChart** para a 3ª coluna. Memória `feedback_echarts_no_localstorage.md` atualizada.

Justificativa:
  - Bundle ~80-150kb vs ECharts ~900kb (6-10× menor).
  - Svelte 5 native, snippet-based para tooltips/legends/axes.
  - Tokens `--ii-*` injetados via props — sem theme object duplicado.
  - Lifecycle gerenciado pelo Svelte — sem memory leak ao abrir/fechar a 3ª coluna.

**Escopo de migração:**
  - Novos charts nesta sprint (`AnalyticsColumn.svelte` tabs) **devem** usar LayerChart.
  - Charts existentes em `lib/components/charts/*.svelte` mantidos como estão (muitos são SVG/canvas vanilla, nenhum é Chart.js).
  - Qualquer chart novo em Wealth a partir de 2026-04-08 **deve** ser LayerChart salvo justificativa explícita.

**Dependência a instalar:** `pnpm --filter netz-wealth-os add layerchart`. Versão fixada no primeiro commit da Fase B.

**Lifecycle do chart na 3ª coluna:** como o layout não desmonta colunas, embrulhar o chart em `{#if layoutState === 'three-col'}` **dentro** da coluna sempre-renderizada. Coluna persiste no grid; chart monta/desmonta conforme demand. Isso isola ciclo de vida sem mexer no layout.

### 2.6 — Estado compartilhado

| Slot | Onde vive | Justificativa |
|---|---|---|
| `layoutState` | `$derived` local em `+page.svelte` | Derivado de fatos no store — nunca armazenado |
| `selectedAnalyticsFund` | Store `portfolio-workspace.svelte.ts` | Lido por 3 componentes não-irmãos (Universe highlight, Builder "analyzing", AnalyticsColumn) |
| `analyticsTab` | `$state` local em `AnalyticsColumn.svelte` | Trivial, não cross-component |
| `workspace.universe`, `.funds`, `.activeBuilderTab` | Store (já existem) | Sem mudança |
| `splitterPosition` (se feito) | `$state` local + session volátil | Fora do escopo v1 |

**Reset entre navegações:** `selectedAnalyticsFund` **não persiste**. Quando o PM entra em `/portfolio` novamente, o store zera o campo no `onMount` do `+page.svelte`. Essa é a regra explícita "Reset ao voltar".

### 2.7 — Comunicação entre colunas: callbacks props, não `$bindable`

  - Quando Universe triggera abertura da 3ª coluna: `onSelectFund(fund)` prop passada do `+page.svelte` para `UniverseColumn`.
  - Quando 3ª coluna pede fechamento: `onClose()` prop.
  - `$bindable` é evitado — acoplamento bidirecional invisível dificulta auditoria.

### 2.8 — Sanity checks validados antes desta sprint

| # | Pergunta | Resposta travada |
|---|---|---|
| 1 | `@tanstack/svelte-table` quebrado? | Sim — rejeitar |
| 2 | ECharts mandatory? | Não mais — LayerChart |
| 3 | Container queries aceitáveis? | Sim — Safari < 16 não suportado |
| 4 | Reorder intra-block requer DnD lib? | Fora de escopo — adiado |
| 5 | 3ª coluna persiste entre navegações? | Não — reset ao voltar |
| 6 | Correlação contra portfolio? | Backend on-the-fly via query param |
| 7 | Keyboard drag-drop fallback? | Sprint de follow-up |
| 8 | Estado A (landing)? | Adiado |

---

## §3 — Universe Column — Especificação de Densidade

### 3.1 — Colunas Tier 1 (sempre visíveis em Estado B)

| # | Coluna | Largura | Formatter / Componente |
|---|---|---|---|
| 1 | Grip handle | 24px | Lucide `GripVertical` |
| 2 | Fund name + ticker (2 linhas) | flex (min 220px) | Texto institucional + ticker mono |
| 3 | Asset class chip | 100px | Chip colorido por classe |
| 4 | AUM | 90px | `formatCurrency` compact (`$2.4B`) |
| 5 | Expense ratio | 70px | `formatPercent` (`0.75%`) |
| 6 | 3Y return (ann.) | 80px | `formatPercent` com sinal |
| 7 | Risk-adjusted return | 90px | `formatNumber(1)` — traduzido de Sharpe |
| 8 | Worst loss period | 90px | `formatPercent` negativo — traduzido de max drawdown |
| 9 | **Correlation → portfolio** | 100px | `formatNumber(2)` + color scale ⭐ |
| 10 | Momentum indicator | 60px | Ícone ↑/→/↓ |
| 11 | Liquidity tier | 80px | Pill (Daily/Weekly/Monthly/Quarterly) |
| 12 | Netz Score | 70px | Badge com tooltip decompondo |

**Total mínimo:** 1074px (sem flex). Esperado em Estado B com Universe 45%: ~700px de área de tabela — todas as 12 colunas cabem com folga.

**Em Estado C (Universe 30%):** ~450px disponíveis — colunas 9, 10, 11 escondem progressivamente via container query. 6, 7, 8 nunca escondem — são os não-negociáveis.

### 3.2 — Tier 2 (hover card)

Mini-card flutuante lateral à direita da linha (dentro da coluna Universe), 260px largura, sticky durante hover:
  - Top 5 holdings (nome + peso %)
  - Sector breakdown pie pequeno (ou bar stack)
  - Manager tenure (anos)
  - Fee breakdown (mgmt vs perf)
  - Regime fit badge (Expansion/Cautious/Stress performance score)
  - Último DD report date

### 3.3 — Tier 3 (drill-down completo)

Abre na 3ª coluna, tab `Fund`. Fact sheet institucional full.

### 3.4 — Correlação contra o portfólio: **cálculo backend on-the-fly**

**Endpoint:** `GET /universe?current_holdings=<uuid1>,<uuid2>,...`

**Novo parâmetro:** `current_holdings: list[UUID] | None` — IDs dos fundos atualmente em `workspace.funds`. Quando fornecido, o backend:
  1. Carrega `nav_timeseries` rolling 36M para cada fundo do universo + cada `current_holding`.
  2. Calcula correlação de Pearson entre a série do candidato e a série sintética do portfólio (pesos iguais ou weighted por target %).
  3. Devolve `correlation_to_portfolio: Decimal | None` por linha em `UniverseAssetRead`.

**Trade-off aceito:** route loader adiciona ~200-500ms. Compensado pela eliminação de chamada extra do frontend e pela preservação de metodologia no servidor (smart-backend).

**Fallback:** quando `current_holdings` está vazio ou None, `correlation_to_portfolio` vem `null`. A coluna mostra "—" em vez de número, sem degradar UX.

---

## §4 — Plano de Ataque: 4 Fases

> **Status consolidado (2026-04-08):**
>
> - ✅ **Fase A — Foundations — CONCLUÍDA** e mergeada em `main`.
> - ✅ **Fase B — Estado B funcional — CONCLUÍDA** e mergeada em `main`
>   (inclui 3 rounds de polish visual + refactor estrutural para
>   mirror do BuilderColumn com BuilderTable).
> - 🅱️ **Fase C — Estado C + LayerChart — MOVIDA PARA BACKLOG** (§10.3).
>   Depende de refatoração mais profunda do layout que será tratada
>   em sprints separadas.
> - 🅱️ **Fase D — Polish + deprecação — MOVIDA PARA BACKLOG** (§10.3).
>   Deleção do `PortfolioOverview.svelte` fica para ser feita em
>   conjunto com a refatoração profunda.
>
> As seções 4.1 a 4.4 abaixo são preservadas como referência histórica
> do plano original. O estado real entregue está documentado no §9
> (Execution Log) e §10 (Backlog follow-up).

### 4.1 — Fase A — Foundations (S) — ✅ CONCLUÍDA

Arquivos backend + scaffolding frontend. Nenhuma mudança visual ainda.

```
01 feat(wealth/universe): current_holdings query param + correlation field
02 feat(wealth/workspace): add selectedAnalyticsFund to portfolio-workspace store
03 feat(wealth/layout): FlexibleColumnsLayout.svelte primitive (CSS Grid + container queries)
04 chore(wealth): install layerchart
```

**Arquivos:**
  - `backend/app/domains/wealth/routes/universe.py` — adicionar `current_holdings: list[UUID] = Query(None)` + cálculo de correlação
  - `backend/app/domains/wealth/schemas/universe.py` — adicionar `correlation_to_portfolio: Decimal | None`
  - `backend/app/domains/wealth/services/correlation_service.py` *(se necessário, extrair do rolling correlation existente)*
  - `frontends/wealth/src/lib/state/portfolio-workspace.svelte.ts` — adicionar `selectedAnalyticsFund: Instrument | null` + setters
  - `frontends/wealth/src/lib/components/layout/FlexibleColumnsLayout.svelte` *(novo)* — primitiva: props `layoutState`, snippets `universe`, `builder`, `analytics`
  - `frontends/wealth/src/lib/types/universe.ts` — adicionar `correlation_to_portfolio: number | null`
  - `frontends/wealth/package.json` — `pnpm add layerchart`

**Critério:** backend retorna correlação em chamada de exemplo; FlexibleColumnsLayout renderiza visualmente em isolated storybook-like test; lint wealth passa.

### 4.2 — Fase B — Estado B (L) — ✅ CONCLUÍDA — **núcleo da sprint**

Migração do `/portfolio/+page.svelte` para o novo layout, Estado B funcional.

```
05 feat(wealth/portfolio): scaffold UniverseColumn + BuilderColumn wrappers
06 feat(wealth/portfolio): UniverseTable with 12-column density + svelte-virtual
07 feat(wealth/portfolio): BuilderColumn expanded allocation blocks (120px+) + summary bar
08 refactor(wealth/portfolio): +page.svelte becomes pure orchestrator using FlexibleColumnsLayout
09 feat(wealth/portfolio): hover card with Tier 2 info
```

**Arquivos novos:**
  - `lib/components/portfolio/UniverseColumn.svelte` — wrapper com `<svelte:boundary>`, header de filtros, monta UniverseTable
  - `lib/components/portfolio/UniverseTable.svelte` — tabela 12 colunas com svelte-virtual, substitui UniversePanel.svelte
  - `lib/components/portfolio/UniverseHoverCard.svelte` — Tier 2 flutuante
  - `lib/components/portfolio/BuilderColumn.svelte` — wrapper com `<svelte:boundary>`, action bar, allocation blocks expandidos, summary bar
  - `lib/components/portfolio/AllocationBlockCard.svelte` *(se extraído do inline)*

**Arquivos alterados:**
  - `routes/(app)/portfolio/+page.svelte` — vira orchestrator puro (~100 linhas)
  - `routes/(app)/portfolio/+page.server.ts` — garantir RouteData + passar `current_holdings` derivado quando disponível

**Deprecação:**
  - `lib/components/portfolio/UniversePanel.svelte` — marcar `@deprecated` em comentário, manter até cutover passar visual validation, deletar na fase D.

**Critérios (obrigatórios):**
  - Universe mostra 12 colunas densas com dados reais
  - Drag-drop Universe → Builder funciona sem regressão
  - Splitter entre colunas redimensiona com clamp `[35%, 55%]`
  - Correlation column preenche quando `workspace.funds` tem ≥ 1 fundo
  - Hover mostra Tier 2 card
  - `pnpm lint` passa
  - Visual validation no browser (memory `feedback_visual_validation.md`) — screenshot antes/depois

### 4.3 — Fase C — Estado C + LayerChart (M) — 🅱️ MOVIDA PARA BACKLOG (§10.3)

> **Status:** Fora do escopo da v1 entregue em `main`. Estado C
> ganhou um **placeholder funcional** na Phase B commit `e1957ac`:
> `AnalyticsColumn.svelte` mostra `MainPortfolioChart` inline quando
> `workspace.analyticsMode === "portfolio"` e um fund drill-down
> placeholder quando `=== "fund"`. Esse placeholder é serviceable.
>
> A implementação completa (LayerChart + tabs Fund/Portfolio/Stress/
> Compare) depende de uma refatoração mais profunda do layout FCL
> que será conduzida numa sprint separada. Ver §10.3 para o backlog
> detalhado.

3ª coluna funcional com LayerChart.

```
10 feat(wealth/portfolio): AnalyticsColumn with tab machinery (Fund/Portfolio/Stress/Compare)
11 feat(wealth/portfolio): AnalyticsColumn Fund tab — factsheet drill-down + LayerChart NAV history
12 feat(wealth/portfolio): AnalyticsColumn Portfolio tab — MainPortfolioChart migrated to LayerChart
13 feat(wealth/portfolio): AnalyticsColumn Stress tab — 4 scenario narratives
14 feat(wealth/portfolio): slide-in animation + Esc close + outside-click close
```

**Arquivos novos:**
  - `lib/components/portfolio/AnalyticsColumn.svelte` — wrapper + tabs
  - `lib/components/portfolio/analytics/FundTab.svelte`
  - `lib/components/portfolio/analytics/PortfolioTab.svelte`
  - `lib/components/portfolio/analytics/StressTab.svelte`
  - `lib/components/portfolio/analytics/CompareTab.svelte` *(se tempo; caso contrário placeholder)*
  - `lib/components/charts-v3/LayerChartNavHistory.svelte` *(primeiro chart LayerChart do wealth)*

**Critérios:**
  - Click em linha do Universe abre tab Fund com chart NAV history
  - View Chart abre tab Portfolio
  - Stress Test abre tab Stress
  - Esc fecha 3ª coluna
  - Drag state do Universe preserva quando 3ª coluna abre no meio de um drag
  - LayerChart dispose correto quando 3ª coluna fecha
  - `pnpm lint` passa
  - Visual validation browser

### 4.4 — Fase D — Polish + deprecação (S) — 🅱️ MOVIDA PARA BACKLOG (§10.3)

> **Status:** Fora do escopo da v1 entregue em `main`. Dois legados
> continuam em disco como código morto (já não importados por
> lugar nenhum): `UniversePanel.svelte` e `PortfolioOverview.svelte`.
> Serão deletados em conjunto com a refatoração profunda do layout,
> evitando mudanças duplicadas.

```
15 refactor(wealth/portfolio): delete UniversePanel.svelte (after visual validation)
16 test(wealth/portfolio): visual regression baseline (Playwright screenshot)
17 docs(wealth/portfolio): charter doc for FCL + deprecations
```

**Critérios (quando a sprint de refatoração profunda for executada):**
  - `UniversePanel.svelte` removido
  - `PortfolioOverview.svelte` removido
  - Screenshot baseline salvo
  - Doc `docs/reference/wealth-portfolio-builder.md` atualizado com seção FCL

---

## §5 — Critérios de Aceitação Globais

**Código:**
  - [ ] C1. `FlexibleColumnsLayout.svelte` primitiva CSS Grid + container queries funcional.
  - [ ] C2. `UniverseTable.svelte` mostra 12 colunas Tier 1, virtual scroll via `@tanstack/svelte-virtual`.
  - [ ] C3. Correlation column povoada pelo backend quando `current_holdings` não vazio.
  - [ ] C4. `selectedAnalyticsFund` no store; `layoutState` derivado puro em `+page.svelte`.
  - [ ] C5. Universe column wrapper, Builder column wrapper, Analytics column wrapper cada um com próprio `<svelte:boundary>` + `failed` snippet mostrando `PanelErrorState`.
  - [ ] C6. Drag-drop HTML5 nativo preservado, zero regressão.
  - [ ] C7. `pnpm --filter netz-wealth-os lint` passa (0 problems).
  - [ ] C8. `ruff check` + `mypy` passam nos arquivos backend tocados.
  - [ ] C9. LayerChart instalado no `package.json` com versão pinada.

**Funcional:**
  - [ ] C10. Transição B→C preserva drag state quando usuário está arrastando.
  - [ ] C11. Transição B→C preserva scroll position de Universe e Builder.
  - [ ] C12. Reset de `selectedAnalyticsFund` ao sair de `/portfolio` e voltar.
  - [ ] C13. Correlation column mostra "—" quando workspace está vazio.
  - [ ] C14. Hover Tier 2 card não bloqueia drag-drop.
  - [ ] C15. LayerChart dispose correto quando 3ª coluna fecha.

**Viewport:**
  - [ ] C16. `≥1440px` renderiza 3-col empurrando layout.
  - [ ] C17. `1200-1440px` renderiza 3ª coluna como drawer overlay.
  - [ ] C18. `768-1024px` volta ao fallback single-column com sub-pills.
  - [ ] C19. `<768px` redireciona ou mostra aviso desktop-required.

**Visual validation:**
  - [ ] C20. Screenshot Estado B baseline salvo.
  - [ ] C21. Screenshot Estado C (cada tab) baseline salvo.
  - [ ] C22. Comparação Before/After do Universe — densidade visível.

**Documentação:**
  - [ ] C23. `docs/reference/wealth-portfolio-builder.md` atualizado com seção FCL.
  - [ ] C24. Memória `feedback_echarts_no_localstorage.md` atualizada (já feito em commit de kickoff).

---

## §6 — Riscos, Rollback, Backlog

### 6.1 — Riscos Críticos

| ID | Risco | Prob | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | Correlation backend lento (> 500ms) bloqueia loader | Média | Alto | Measure + cache in-memory por (holdings_hash, 30min) no backend; escalar para job assíncrono se ultrapassar p95 1s |
| R2 | `@tanstack/svelte-virtual` incompatível com Svelte 5 apesar da v3 | Baixa | Alto | Fallback para virtualização caseira (window-based) em <100 linhas. Já comprovado em outros projetos |
| R3 | LayerChart sem feature institucional específica (regime bands, markArea) | Média | Médio | Compor via snippets + SVG primitives; escalar para ECharts localizado numa tab se necessário (exceção documentada) |
| R4 | Grid transition `grid-template-columns` 0fr quebra em Safari 16 | Baixa | Médio | Testar early em Safari; fallback com `width` transition no container filho |
| R5 | Drag state perdido durante transição B→C | Baixa | Alto | Nunca desmontar coluna; testar com Playwright simulando drag + click |
| R6 | UniversePanel deletado antes de visual validation | Média | Alto | Regra explícita: delete só em Fase D após screenshot baseline |
| R7 | Hover card bloqueia drag source da linha | Média | Médio | `pointer-events: none` no hover card durante drag (detectar via `dataTransfer` flag) |
| R8 | PM não descobre que click na linha abre a 3ª coluna | Alta | Médio | Cursor affordance (pointer + hover highlight); CTA "View details →" no hover card |

### 6.2 — Rollback

**Estratégia:** `git revert` granular por commit.

  - Reverter Fase C → reverter commits 10-14. Estado B continua funcional.
  - Reverter Fase B → reverter 05-09. Volta ao `UniversePanel` original.
  - Reverter Fase A → reverter 01-04. Backend volta ao schema original.

**Sem feature flags.** Código limpo desde o primeiro commit.

### 6.3 — T-Shirt Sizing

| Fase | Size | Justificativa |
|---|---|---|
| Fase A — Foundations | **S** | Backend param + store field + primitiva layout + install pnpm |
| Fase B — Estado B | **L** | Substituição do UniversePanel + 12 colunas + virtual scroll + hover card + orchestrator refactor |
| Fase C — Estado C + LayerChart | **M** | 3ª coluna + 4 tabs + primeiro chart LayerChart + animação + lifecycle |
| Fase D — Polish | **S** | Delete UniversePanel + screenshot baseline + charter doc |

**Total:** S+L+M+S. Caminho crítico: Fase A → Fase B → Fase C. Fase D puramente sequencial ao final.

### 6.4 — Backlog explícito (fora do escopo)

Dívida documentada:

  1. **Estado A (Landing)** — Model picker visual com cards grandes, drift ring, YTD return. Follow-up sprint.
  2. **Keyboard drag-drop fallback** — ARIA grab mode, arrow key navigation, Enter to drop. Follow-up sprint por compliance.
  3. **Reorder intra-block no Builder** — avaliar `svelte-dnd-action@0.9.x` com teste de compat Svelte 5. Follow-up.
  4. **Multi-select Compare** — Ctrl+click no Universe marca fundos, tab Compare side-by-side. Parcialmente na Fase C (Compare tab pode ser placeholder v1).
  5. **Splitter persistente** — position sobrevive sessão (in-memory), mas não entre navegações. Ver se PM quer.
  6. **Migração dos charts existentes** — `charts/*.svelte`, `charts-v2/*.svelte` para LayerChart quando tocados.
  7. **Guard test METRIC_LABELS mirror** — assert que `backend/app/domains/wealth/schemas/sanitized.py::METRIC_LABELS` casa com `frontends/wealth/src/lib/i18n/quant-labels.ts::METRIC_LABELS`. Unit test backend.
  8. **Correlation cache** — materialized view de correlação inter-fundos atualizada diariamente pelo worker de risk metrics, reduz custo do route loader.

---

## §7 — Definição Operacional de "Institucional"

Na semana seguinte ao merge da Fase C, em uso single-user normal:

  1. O PM consegue construir um portfolio completo (selecionar model → ver universo → arrastar 6+ fundos para blocks → ver correlação caindo conforme diversifica → construir → stress test) sem abrir modal nenhum e sem navegar para fora de `/portfolio`.
  2. A densidade da Universe column é visualmente equivalente ou superior a Aladdin / Addepar / FactSet no que diz respeito a colunas visíveis por linha.
  3. A 3ª coluna abre e fecha em < 300ms sem flash, sem perda de scroll, sem perda de drag.
  4. Nenhum jargão CVaR / regime / Sharpe / drawdown / DTW aparece na UI (todos passam pelo `humanizeMetric` ou foram renomeados para as contrapartes institucionais).

Se qualquer um desses falhar, sprint é **incompleto** → novo ciclo.

---

## §8 — Post-Decision Log

| Data | Decisão | Autor | Justificativa |
|---|---|---|---|
| 2026-04-08 | Adotar LayerChart, retirar mandato ECharts | Andrei | Svelte 5 native + bundle 6-10× menor |
| 2026-04-08 | Correlation calculated backend | Andrei | Smart-backend / dumb-frontend, metodologia no servidor |
| 2026-04-08 | Adiar Estado A | Andrei | MVP foca na construção, landing é sprint de follow-up |
| 2026-04-08 | Adiar keyboard drag-drop | Andrei | Estabilidade visual + boundaries primeiro |
| 2026-04-08 | Adiar reorder intra-block | Andrei | HTML5 puro, sem nova dependência DnD nesta sprint |
| 2026-04-08 | Container queries (sem Safari < 16) | Andrei | Clientes institucionais em ambiente gerenciado |
| 2026-04-08 | Reset 3ª coluna ao voltar | Andrei | Default sempre Estado B para visão holística |
| 2026-04-08 | `<768px` mobile read-only | Andrei | Wealth construction em mobile é anti-padrão |
| 2026-04-08 | Fase C adiada para sprint separada | Andrei | Após Phase B estabilizar, layout precisa refactor mais profundo para atingir o verdadeiro FCL de 3 colunas — será tratado isoladamente |
| 2026-04-08 | `<header class="uc-header">` removido | Andrei | Alinhamento Y-axis com BuilderColumn — search fica suspensa até retornar como toolbar nas sub-pills |

---

## §9 — Execution Log (Phase A + B — delivered)

Branch `feat/wealth-portfolio-flex-columns` shipped 7 commits
between 2026-04-08 morning and 2026-04-08 afternoon, covering the
foundations + Estado B (2-column workspace) + all visual polish
rounds the institutional PM flagged during live dev-server review.

### 9.1 — Commit ledger (in execution order)

| # | SHA | Summary |
|---|---|---|
| 1 | `ba98678` | **Fase A — Foundations.** Backend correlation service + `/universe` query param + FlexibleColumnsLayout primitive + `selectedAnalyticsFund` on workspace store + `UniverseAssetRead` Decimal field. |
| 2 | `66fe6b7` | **Fase B — Estado B functional.** UniverseColumn + UniverseTable 12-col density + BuilderColumn wrapper + AnalyticsColumn Estado C placeholder + orchestrator refactor of `/portfolio/+page.svelte`. |
| 3 | `e1957ac` | **Polish round 1.** Full-bleed opt-out in shell (kills max-w-screen-2xl for /portfolio only), chart moved to AnalyticsColumn, harmonisation attempt on rounded cards, dark hex fallbacks. |
| 4 | `3600e4b` | **Polish round 2.** Screener palette alignment — `UniverseTable` var() → hex literals (30+ replacements), Screener pill pattern for all buttons, 16px padding standard, grid proportions rebalanced (58% Universe / 42% Builder). |
| 5 | `a19f8a3` | **3-level tree + reverse drag.** UniverseTable restructured to Asset Class Group → Block/Region → Fund (matching Builder shape). `workspace.removeFund()` added. UniverseColumn becomes drop target for allocated funds. Two-MIME-type drag payload distinguishes add from remove. |
| 6 | `ab4e7d9` | **Mirror refactor.** New `BuilderTable.svelte` component 1:1 mirrors `UniverseTable` structurally (`<table>` + 3 nested `<tbody>` per group + sticky header). PortfolioOverview unplugged from BuilderColumn (kept on disk as dead code for rollback). Both headers use stacked 2-row layout for Y-axis lock. |
| 7 | `fe74b88` | **Y-axis alignment.** `<header class="uc-header">` removed from UniverseColumn (title + count + search). Table now starts at top of column. Search functionality temporarily suspended — will return as sub-pills toolbar in a future sprint. |

### 9.2 — What actually shipped (capabilities checklist)

**Backend**
- [x] `GET /universe?current_holdings=<uuids>` enriches each row with on-the-fly Pearson correlation against the equal-weight synthetic portfolio
- [x] `quant_engine/portfolio_correlation_service.py` (pure, 45-day overlap floor, fallback to None on insufficient history or degenerate series)
- [x] `UniverseAssetRead` schema extended with all Tier 1 density fields + `correlation_to_portfolio: Decimal | None`
- [x] Latest-per-instrument LEFT JOIN against `fund_risk_metrics` + `nav_timeseries` for AUM/return_3y_ann/sharpe_1y/max_drawdown_1y/blended_momentum_score/manager_score
- [x] Best-effort enrichment: if the batch correlation query or the JOIN raises, route logs warning and serves rows with None density fields

**Frontend — layout primitive**
- [x] `FlexibleColumnsLayout.svelte`: CSS Grid + `grid-template-columns` reactive via `$derived`
- [x] Columns always in DOM (zero `{#if}` unmount) — `0fr + overflow hidden + visibility hidden + pointer-events none` on collapsed
- [x] 240ms cubic-bezier transition with `prefers-reduced-motion` honoured
- [x] Container queries fallback for narrow viewports (<1100px → 3rd column drawer)
- [x] Shell opt-out of `max-w-screen-2xl` + `p-6` via `FULL_BLEED_PATHS` list (only `/portfolio`)

**Frontend — Universe column**
- [x] `UniverseColumn.svelte` wrapper with `<svelte:boundary>` + `PanelErrorState` failed snippet
- [x] `UniverseTable.svelte` as continuous hierarchical tree: Group → Block → Fund
- [x] 12 Tier 1 columns (grip, fund+ticker, asset class chip, AUM, expense, 3Y return, risk-adjusted, max drawdown, correlation→portfolio, momentum, liquidity, Netz Score)
- [x] Ordering: canonical `BLOCK_GROUPS` sequence (Cash → Equities → Fixed Income → Alternatives) with deterministic block order inside each group
- [x] Per-group AND per-block collapse state (in-memory only)
- [x] 48px grip padding on fund rows for visual nesting under block header
- [x] Screener palette hardcoded: #141519, #85a0bd, #cbccd1, #ffffff, #404249, #0177fb
- [x] Drop target for **reverse drag-drop** (remove fund): `application/x-netz-allocated` MIME marker check, `uc-root--removing` highlight + full-column overlay with `Undo2` icon and *"Drop to return fund to the Universe"* / *"The portfolio is not live — changes are staged for review"* copy
- [x] `<header class="uc-header">` deliberately removed for Y-axis alignment; search functionality queued for sub-pills toolbar return

**Frontend — Builder column**
- [x] `BuilderColumn.svelte` wrapper with `<svelte:boundary>` + `PanelErrorState` failed snippet
- [x] `BuilderTable.svelte` structural mirror of `UniverseTable` (same `<table>` + 3-level tbody pattern)
- [x] Columns: Grip | Fund+Ticker | Score | Weight | Remove
- [x] Weight in #11ec79 (brand accent) with tabular-nums
- [x] Drop target on L2 block header rows (Universe → Builder adds)
- [x] Drag source on L3 fund rows (Builder → Universe removes) with `application/x-netz-allocated` marker
- [x] Hover-reveal remove X button on each fund row (secondary interaction path, faster than drag for mouse users)
- [x] Action pill row in header (View Chart / Construct / Stress Test) matching Screener `.scr-pill` pattern
- [x] `PortfolioOverview.svelte` unplugged from the BuilderColumn render path; kept on disk as dead code for rollback

**Frontend — Analytics column (Estado C placeholder)**
- [x] `AnalyticsColumn.svelte` with two explicit modes driven by `workspace.analyticsMode`:
  - `"fund"` → Fund details placeholder (opened by UniverseTable row click)
  - `"portfolio"` → inline `MainPortfolioChart` (opened by Builder "View Chart" pill) — relocated from old BuilderColumn top
- [x] Esc-to-close via window keydown with cleanup `$effect`
- [x] Close button clears both mode + selected fund atomically
- [x] `PanelEmptyState` when closed, `PanelErrorState` failed snippet in `<svelte:boundary>`
- [x] Dark hex hardcoded

**Frontend — state store**
- [x] `analyticsMode: "fund" | "portfolio" | null` on `PortfolioWorkspaceState`
- [x] `openAnalyticsForFund(fund)` / `openAnalyticsForPortfolio()` / `clearAnalytics()`
- [x] `removeFund(instrumentId)` with automatic weight re-equalisation within the affected block
- [x] `resetBuilderEntry()` called from `onMount` of `/portfolio/+page.svelte` (enforces "reset ao voltar" rule)
- [x] `loadUniverse()` passes `?current_holdings=<uuids>` derived from `workspace.funds`
- [x] `layoutState` derived purely from observable facts, never stored

### 9.3 — Visual validation rounds

Three live-browser reviews by Andrei, each producing a targeted
polish commit:

**Round 1** (commit `e1957ac`) — "O container é muito pequeno e não
tem ajuste automático" + "O gráfico NAV precisa ir para a terceira
coluna" + "Bordas arredondadas quebram harmonia" + "Dark mode não
está aplicado por default". All four addressed.

**Round 2** (commit `3600e4b`) — "As cores ainda não proporcionam
contraste; use o padrão do Screener" + "Os botões estão fora do
padrão da página" + "Padding do header praticamente inexistente,
use 16px" + "A tabela do Builder ocupa mais da metade com só 3
colunas". Hex palette ported from `.scr-*` rules verbatim, `.bc-pill`
+ `.bld-pill` Screener pattern, 16px everywhere, grid rebalanced.

**Round 3** (commits `a19f8a3` + `ab4e7d9` + `fe74b88`) —
"Precisa padronizar os componentes da primeira e segunda coluna" +
"A coluna 2 é feita em 3 níveis — a primeira também deve ser" +
"Deve haver drag reverso" + "A coluna direita está usando um padrão
de acordeão com cartões separados — faz a direita ser espelho
estrutural da esquerda" + "Remove o header da Universe para Y-axis
lock". Full structural mirror achieved.

### 9.4 — Phase B sign-off

Andrei (2026-04-08): *"Vamos deixar assim por enquanto porque as
páginas precisam de uma refatoração de layout bem mais profunda,
para aplicar o verdadeiro conceito de Flexible Column Layout com
três colunas, mas farei em sprints separadas. Está bom por enquanto."*

Phase B is closed as **stable enough to park**. A deeper
layout refactor is planned in a future sprint to realise the full
3-column FCL concept that §1.3 of this spec originally envisaged.
That sprint will likely touch:
- Sub-pills placement / consolidation with search toolbar
- Column header strategy (whether to carry any chrome at all, and
  where it lives)
- Shared typography scale across the left shell nav + FCL columns
- Possibly a ContextSidebar global component (memory
  `feedback_nav_architecture.md`) that owns the 3-column framing
  differently

Phase C (LayerChart + AnalyticsColumn tabs Fund/Portfolio/Stress/
Compare) is **also deferred** until that deeper layout refactor
lands — it doesn't make sense to build tabs into a column design
that's about to be reshaped. The `MainPortfolioChart` inline
placeholder stays in AnalyticsColumn as a serviceable v1.

---

## §10 — Backlog explícito (fora do escopo da v1)

Tudo o que NÃO foi entregue na v1 (Phase A + B mergeadas em `main`)
e fica reservado para sprints futuras. Dividido em três grupos por
origem e prioridade.

### 10.1 — Débito de estabilização da Phase B

Itens levantados durante as 3 rounds de validação visual da Phase B
que ficaram parados porque requerem a refatoração profunda do
layout:

1. **Search toolbar return** — reinstate Universe filter input, but
   in a shared toolbar surface above the FCL columns (likely inside
   the left-shell sub-pills row `Models | Universe | Policy`), not
   back inside `UniverseColumn`. The `filtered` `$derived` inside
   `UniverseColumn` is ready to consume a shared search state.

2. **Builder column header alignment finalisation (Y-axis lock)** —
   decidir se `BuilderColumn`'s action pill row (View Chart /
   Construct / Stress Test) permanece acima da tabela ou migra
   para outro lugar. Atualmente o Y-axis está desalinhado em
   ~112px porque Universe perdeu seu header mas Builder manteve.
   Opções: remover bc-header também, migrar ações para um toolbar
   compartilhado acima do FCL, ou inserir header equivalente no
   Universe (com conteúdo estrutural diferente do search).

3. **Deleção do `PortfolioOverview.svelte`** — o componente legado
   está como código morto em disco (não importado em lugar
   nenhum). Deletar quando a refatoração profunda do layout
   estiver em progresso e não houver apetite por rollback.

4. **L2 block drop target UX** — a linha do block header é o drop
   zone para adds Universe→Builder, mas o feedback visual accept/
   reject é sutil. Follow-up pode ampliar a área de drop ou
   adicionar uma borda tracejada na linha L2 inteira durante o
   drag.

### 10.2 — Itens do backlog original da spec (§6.4) ainda pendentes

5. **Estado A (Landing)** — Model picker visual com cards, drift
   ring, YTD return. Prioridade baixa — o empty state atual é
   aceitável como MVP.

6. **Keyboard drag-drop fallback** — ARIA grab mode, arrow key
   navigation, Enter to drop. Requisito de compliance institucional.

7. **Reorder intra-block no Builder** — avaliar `svelte-dnd-action@0.9.x`
   compat com Svelte 5. Permitiria reordenar fundos dentro de um
   mesmo block sem exportar/reimportar.

8. **Multi-select Compare** — Ctrl+click no Universe marca fundos
   (estado in-memory), tab Compare na Analytics column side-by-side.

9. **Splitter persistente** — position das colunas sobrevive a
   session (in-memory, não localStorage), mas não entre navegações.

10. **`expense_ratio` + `liquidity_tier` backend enrichment** — via
    `instrument.attributes` JSON. Schema fields existem mas sempre
    retornam `None` na v1; a UniverseTable renderiza em-dash.

11. **Correlation cache** — materialised view de correlação
    inter-fundos com refresh diário pelo worker de risk metrics.
    Reduz custo do route loader de ~200-500ms para <50ms.

12. **Guard test** — assertion backend `METRIC_LABELS` mirrors
    frontend `quant-labels.ts` exactly.

13. **LayerChart migration dos charts existentes** — oportunística,
    quando cada chart é tocado em outro contexto.

### 10.3 — Fases C + D originais, movidas na íntegra do §4

Consolidadas aqui como escopo da sprint futura de refatoração
profunda do layout FCL:

14. **Fase C (original) — Estado C + LayerChart tabs completas**
    - `AnalyticsColumn.svelte` ganha tab machinery (Fund / Portfolio
      / Stress / Compare) em vez do branching simples `analyticsMode`
    - `lib/components/portfolio/analytics/FundTab.svelte` — factsheet
      drill-down + LayerChart NAV history
    - `lib/components/portfolio/analytics/PortfolioTab.svelte` —
      MainPortfolioChart migrado para LayerChart
    - `lib/components/portfolio/analytics/StressTab.svelte` — 4
      scenario narratives em plain-English
    - `lib/components/portfolio/analytics/CompareTab.svelte` —
      slots para até 3 fundos side-by-side
    - `lib/components/charts-v3/LayerChartNavHistory.svelte` — primeiro
      chart LayerChart canónico do wealth vertical
    - Slide-in animation refinada + outside-click close
    - **Pré-requisito:** refatoração profunda do layout FCL deve
      acontecer primeiro — não faz sentido construir tabs sobre um
      column design que está para ser reshaped

15. **Fase D (original) — Polish + deprecação final**
    - `UniversePanel.svelte` removido (legado 2-col)
    - `PortfolioOverview.svelte` removido (legado card-based)
    - Playwright visual regression baseline
    - `docs/reference/wealth-portfolio-builder.md` atualizado com
      seção FCL completa

### 10.4 — Refatoração profunda do layout (meta-item)

Item guarda-chuva que precisa ser planejado e brainstormed antes
dos itens 14 e 15 acima:

16. **Deeper FCL refactor** — a v1 entregou o 3-level tree mirror
    e o reverse drag, mas o verdadeiro Flexible Column Layout
    ainda não foi atingido. Tópicos que a sprint futura deve
    endereçar:
    - **Sub-pills placement** — consolidação com search toolbar
      global acima do FCL
    - **Column header strategy** — decisão sobre carregar qualquer
      chrome ou não nas colunas, e onde ele vive
    - **Shared typography scale** — escala tipográfica unificada
      entre o left-shell nav + FCL columns
    - **ContextSidebar global** — possível componente global
      (memória `feedback_nav_architecture.md`) que assume o
      framing de 3 colunas de forma diferente
    - **Y-axis lock estrutural** — resolver definitivamente o
      desalinhamento de 112px entre Universe e Builder headers

---

## Fim do spec.

**Phase A + B delivered, validated, and merged.** Branch
`feat/wealth-portfolio-flex-columns` (8 commits including this
doc update) mergeada em `main` via `--no-ff` on 2026-04-08
após aprovação direta do Andrei.

Backlog §10 aguarda planeamento do próximo sprint de Wealth.
