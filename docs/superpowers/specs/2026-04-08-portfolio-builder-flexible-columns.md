# Portfolio Builder — Flexible Columns Layout — Design Spec

**Date:** 2026-04-08
**Status:** Approved for implementation
**Owner:** Andrei (Netz)
**Branch:** `feat/wealth-portfolio-flex-columns`
**Base:** `main` (post Stability Guardrails + Onda 0 + PR-UX-09 sanitisation)
**Sprint sizing:** S + L + M + S (4 phases)

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

### 4.1 — Fase A — Foundations (S)

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

### 4.2 — Fase B — Estado B (L) — **núcleo da sprint**

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

### 4.3 — Fase C — Estado C + LayerChart (M)

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

### 4.4 — Fase D — Polish + deprecação (S)

```
15 refactor(wealth/portfolio): delete UniversePanel.svelte (after visual validation)
16 test(wealth/portfolio): visual regression baseline (Playwright screenshot)
17 docs(wealth/portfolio): charter doc for FCL + deprecations
```

**Critérios:**
  - `UniversePanel.svelte` removido
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

---

## Fim do spec.

Próximo passo após aprovação: execução da Fase A nos commits atômicos
01-04, base `feat/wealth-portfolio-flex-columns`, com visual validation
no browser antes de avançar para Fase B.
