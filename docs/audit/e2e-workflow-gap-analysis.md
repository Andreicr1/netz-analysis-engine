# E2E Workflow Gap Analysis — Wealth Management Institucional

> **Data:** 2026-03-26
> **Escopo:** Ciclo completo de vida do ativo e do portfólio
> **Método:** Confronto direto entre o Ideal Circular Workflow (7 etapas) e a implementação real no código

---

## Visão Geral do Ciclo

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   1. MACRO APPROVAL ──► 2. SCREENER ──► 3. DD REPORT               │
│          ▲                                      │                   │
│          │                                      ▼                   │
│   7. REPORTING    ◄──  6. MONITORING  ◄──  4. UNIVERSE APPROVAL     │
│                           │                     │                   │
│                           ▼                     ▼                   │
│                      REBALANCE ◄──────── 5. PORTFOLIO CONSTRUCTION  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

| # | Etapa | Status | Completude |
|---|-------|--------|------------|
| 1 | Top-Down & Macro Approval | **Parcialmente Implementado** | ~70% |
| 2 | Bottom-Up Discovery (Screener) | **Em Produção** | ~95% |
| 3 | Due Diligence (DD Report) | **Em Produção** | ~95% |
| 4 | Universe of Approved Assets | **Em Produção** | ~90% |
| 5 | Portfolio Construction | **Parcialmente Implementado** | ~60% |
| 6 | Continuous Monitoring & Rebalancing | **Parcialmente Implementado** | ~75% |
| 7 | Client Reporting | **Parcialmente Implementado** | ~55% |

---

## Etapa 1 — Top-Down & Macro Approval

### Status Atual: Parcialmente Implementado (~70%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| Macro Ingestion Worker | `workers/macro_ingestion.py` (lock 43) | Ingere ~65 séries FRED + BIS + IMF diariamente em `macro_data` hypertable |
| Regional Macro Scoring | `quant_engine/regional_macro_service.py` | 7 dimensões × 4 regiões, percentil expandido 10 anos, staleness decay |
| Macro Snapshot Builder | `quant_engine/macro_snapshot_builder.py` | Constrói `MacroRegionalSnapshot` (global, 1 row/dia) |
| Macro Committee Engine | `vertical_engines/wealth/macro_committee_engine.py` | Compara snapshots, detecta deltas >5pt, transições de regime, alertas stale |
| Regime Service | `quant_engine/regime_service.py` | Markov 2-state switching em log-VIX, classify_regional_regime() |
| Investment Outlook | `vertical_engines/wealth/investment_outlook.py` | Narrativa trimestral LLM estendendo WeeklyReportData |
| MacroReview Model | `models/macro_committee.py` | status: pending → approved → rejected, CIO audit trail |
| Allocation Models | `models/block.py`, `models/allocation.py` | `AllocationBlock` (15 blocos globais), `StrategicAllocation` (por perfil/org), `TacticalPosition` |
| Calibration YAML | `calibration/config/profiles.yaml` | 3 mandatos (conservative/moderate/growth) com CVaR limits, blocos alvo |

### O que funciona

- **Fundação sólida:** 65 séries FRED + BIS credit gap + IMF WEO → snapshot regional diário com 7 dimensões por região.
- **3 mandatos definidos:** `profiles.yaml` com CVaR limits (conservative -8%, moderate -6%, growth -12%), core/satellite ranges, e 11 blocos com target/min/max por perfil.
- **Fluxo de aprovação CIO:** `POST /macro/reviews/generate` → `PATCH /macro/reviews/{id}/approve` com `decision_rationale` e audit trail.
- **Regime detection:** Markov 2-state switching (low_vol/normal/stress/crisis) já integrado ao snapshot.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G1.1 — Macro Report não gera Sugestão de Asset Allocation** | `macro_committee_engine.generate_weekly_report()` produz `WeeklyReportData` (score deltas, regime transitions, staleness) mas **não** produz uma proposta de ajuste nos pesos dos blocos de `StrategicAllocation`. O CIO aprova/rejeita um relatório textual, não uma alocação numérica. | A ponte entre macro intelligence e otimização está quebrada. O CIO deveria aprovar um **vetor de pesos sugerido**, não apenas um relatório de deltas. | **Alta** |
| **G1.2 — Aprovação macro não alimenta StrategicAllocation** | `PATCH /macro/reviews/{id}/approve` muda `MacroReview.status` para `approved` mas **não** cria/atualiza registros em `StrategicAllocation`. A rota `POST /allocation/{profile}/strategic` existe mas é manual e desconectada do macro review. | Sem costura automática, o analista precisa ler o relatório macro e manualmente atualizar alocações. | **Alta** |
| **G1.3 — TacticalPosition sem trigger automático de regime** | `TacticalPosition` model existe com `signal_source` e `conviction_score`, mas nenhum engine popula automaticamente posições táticas baseado em mudanças de regime. | O ciclo tático (regime change → overweight/underweight automático) não fecha. Tactical adjustments são puramente manuais. | **Média** |
| **G1.4 — Asset Allocation preditivo ausente** | Não há modelo preditivo (forward-looking) gerando sugestão de alocação. O scoring regional é retrospectivo (percentil expandido sobre 10 anos de histórico). O regime detector é Markov (probabilístico mas não prescritivo de alocação). | O ideal prevê "modelos preditivos gerando Sugestão Estratégica". O que existe é descriptive/diagnostic, não predictive/prescriptive. | **Média** |

### Costura Necessária

```
MacroReview (approved)
  └─► NOVO: AllocationProposalEngine
        ├─ Lê regime atual + score deltas do MacroReview.report_json
        ├─ Aplica regras prescritivas (regime → tilts definidos em limits.yaml)
        ├─ Gera StrategicAllocationProposal (vetor de pesos por perfil)
        └─ Submete para aprovação CIO como entidade separada
              └─► Aprovação → upsert StrategicAllocation (effective_from = today)
                    └─► Notifica optimizer que targets mudaram
```

---

## Etapa 2 — Bottom-Up Discovery (Screener)

### Status Atual: Em Produção (~95%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| ScreenerService | `vertical_engines/wealth/screener/service.py` | Screening determinístico 3 camadas (zero LLM) |
| LayerEvaluator | `screener/layer_evaluator.py` | L1 eliminatório, L2 mandate fit (com histerese 5%), L3 quant percentil |
| QuantMetrics | `screener/quant_metrics.py` | Sharpe, vol, drawdown, % meses positivos → composite_score 0.0-1.0 |
| ScreeningRun/Result | `models/screening_result.py` | Audit trail (JSONB layer_results), is_current pattern |
| Routes | `routes/screener.py` | `POST /screener/run`, `GET /results`, facets, search, securities, ESMA import |

### O que funciona

- **3-layer screening completo:** Eliminatory → Mandate Fit → Quant Scoring, tudo determinístico.
- **Audit trail detalhado:** Cada criterion avaliado com expected/actual/passed em JSONB.
- **Global discovery:** `/screener/securities` (global, sem RLS) para equity/ETF + `/screener/search` com paginação server-side.
- **Block-aware:** Layer 2 avalia mandate fit por `block_id` do allocation_blocks.
- **Output tipado:** `required_analysis_type` (dd_report | bond_brief | none) direciona próximo passo.
- **Hysteresis:** Buffer 5% previne oscilação PASS/WATCHLIST.
- **Unified Fund Catalog:** `/us-fund-analysis` absorvido pelo `/screener` (2026-03-26).

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G2.1 — Screener não recebe targets de bloco da Etapa 1** | O screener avalia `block_id` mas não sabe quantos fundos cada bloco precisa ou qual peso alvo. O analista precisa saber externamente que "preciso preencher 20% em na_equity_large". | Sem awareness dos targets, o screener não pode priorizar blocos deficitários nem rankear candidatos por gap a preencher. | **Baixa** |
| **G2.2 — Batch scheduling ausente** | Screening é on-demand (`POST /screener/run`). Não há worker diário/semanal que re-screen o universo automaticamente para detectar deterioração. | `WatchlistService.check_transitions()` existe mas depende de trigger manual. | **Baixa** |

### Costura Necessária

Mínima. O screener é o módulo mais maduro. G2.1 é quality-of-life (exibir gaps por bloco no frontend). G2.2 é operacional (cron job simples chamando `POST /screener/run`).

---

## Etapa 3 — Due Diligence (DD Report)

### Status Atual: Em Produção (~95%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| DDReportEngine | `vertical_engines/wealth/dd_report/dd_report_engine.py` | Orquestrador 8 capítulos, parallel(1-7) + sequential(8) |
| EvidencePack | `dd_report/evidence_pack.py` | Frozen dataclass: quant + SEC (N-PORT, 13F, ADV) + risk metrics |
| Chapters | `dd_report/chapters.py` | Dispatch por tag, Jinja2 → OpenAI → sanitize |
| ConfidenceScoring | `dd_report/confidence_scoring.py` | Score baseado em evidence quality + chapter completion |
| SEC Injection | `dd_report/sec_injection.py` | N-PORT (fund-level), 13F (manager overlay), ADV (compliance) |
| Quant Injection | `dd_report/quant_injection.py` | Sharpe, CVaR, momentum de `fund_risk_metrics` hypertable |
| Peer Injection | `dd_report/peer_injection.py` | Comparação peer group |
| Critic | `dd_report/critic/` | Adversarial review (circuit-breaker, 3min timeout) |
| DDReport/DDChapter | `models/dd_report.py` | Versioning (is_current), composite FK com organization_id |
| Routes | `routes/dd_reports.py` | Generate (202), stream SSE, approve/reject, audit trail |

### O que funciona

- **8 capítulos fund-centric:** Overview, Performance, Holdings, Risks, Governance, Process, Valuation, Recommendation.
- **Evidence imutável:** Frozen `EvidencePack` com SEC data real (N-PORT + 13F + ADV), quant metrics pré-computados.
- **Paralelismo controlado:** ThreadPoolExecutor(5) para cap 1-7, cap 8 sequencial (sintetiza 1-7).
- **Resume safety:** Chapters cacheados em DB, `force=False` pula regeneração.
- **Concurrency control:** Semaphore (max 3 concurrent) + advisory lock por fund.
- **Approval workflow:** draft → pending_approval → approved/escalated/rejected com rationale.
- **Confidence scoring:** Score numérico derivado de evidence quality + chapter completion.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G3.1 — Bond Brief não implementado** | `required_analysis_type` pode ser `bond_brief` mas não existe `BondBriefEngine`. Bonds passam pelo screener mas não têm DD path. | Bonds ficam sem comprovação analítica para aprovação no universo. | **Média** |

### Costura Necessária

Mínima. DD Report é o segundo módulo mais maduro. G3.1 é scope expansion (bonds são minoria no universo atual).

---

## Etapa 4 — Universe of Approved Assets

### Status Atual: Em Produção (~90%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| UniverseService | `vertical_engines/wealth/asset_universe/universe_service.py` | add_fund, approve_fund, reject_fund, list_universe, deactivate |
| FundApproval | `asset_universe/fund_approval.py` | State machine: pending → approved/watchlist/rejected, self-approval prevention |
| UniverseApproval | `models/universe_approval.py` | SELECT FOR UPDATE, is_current pattern, audit trail |
| Instrument | `models/instrument.py` | Polymorphic (fund/bond/equity), JSONB attributes, approval_status |
| Routes | `routes/universe.py` | List approved, list pending, approve, reject, audit trail |

### O que funciona

- **Governance gate completa:** DD Report obrigatório → UniverseApproval (pending) → IC review → approve/reject.
- **Self-approval prevention:** `decided_by != created_by` enforced.
- **Concurrency safety:** `SELECT FOR UPDATE` previne race conditions.
- **Deactivation cascade:** `deactivate_asset()` → marca inactive → triggers `RebalancingService.compute_rebalance_impact()`.
- **RLS isolation:** Universo é tenant-scoped. Portfolio Manager só vê fundos aprovados do seu org.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G4.1 — Watchlist → Approved sem re-screening automático** | Fund em watchlist pode ser promovido a approved via rota manual, mas não há trigger para re-screen automático quando métricas melhoram. | Fundos watchlist ficam em limbo. Promoção depende de memória humana. | **Baixa** |
| **G4.2 — Sem expiração automática de aprovação** | `alert_engine.scan_alerts()` detecta DD reports >12 meses mas **não** revoga aprovação automaticamente. Apenas gera alerta. | Fundos com DD expirado permanecem no universo aprovado indefinidamente. | **Média** |

### Costura Necessária

G4.2 é a mais relevante: transformar o alerta de DD expirado em ação (mover fund para watchlist + notificar).

---

## Etapa 5 — Portfolio Construction

### Status Atual: Parcialmente Implementado (~60%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| Portfolio Builder | `vertical_engines/wealth/model_portfolio/portfolio_builder.py` | Score-proportional weighting dentro de cada bloco, top-N selection |
| Optimizer (CLARABEL) | `quant_engine/optimizer_service.py` | Max Sharpe / Min Variance com constraints cvxpy |
| Optimizer (NSGA-II) | `quant_engine/optimizer_service.py` | Pareto front [-Sharpe, CVaR_95], NSGA-II via pymoo |
| CVaR Service | `quant_engine/cvar_service.py` | Cornish-Fisher parametric CVaR, breach classification |
| ModelPortfolio | `models/model_portfolio.py` | draft → backtesting → published, fund_selection_schema JSONB |
| Track Record | `model_portfolio/track_record.py` | Walk-forward backtest, stress scenarios |
| Routes | `routes/model_portfolios.py` | Create, construct, backtest, stress, track-record |

### O que funciona

- **Portfolio Builder:** Agrupa fundos aprovados por block_id, seleciona top-N por score, distribui peso score-proporcional.
- **Optimizer (CLARABEL):** Single-objective max Sharpe com constraints por bloco (min/max weight) + max single fund weight.
- **Optimizer (NSGA-II):** Pareto front multi-objetivo com CVaR constraint, seed determinístico, ESG weight opcional.
- **CVaR enforcement:** `ProfileConstraints.cvar_limit` passado ao optimizer, feasibility-first tournament no NSGA-II.
- **Backtest:** Walk-forward com rolling Sharpe, stress scenarios (GFC, COVID, 2022 rate hike).
- **3 portfolios:** Conservative, Moderate, Growth com blocos quase idênticos, proporções diferentes.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G5.1 — Portfolio Builder e Optimizer são desconectados** | `portfolio_builder.construct()` usa score-proportional weighting (heurística simples). `optimizer_service.optimize_portfolio()` usa cvxpy/NSGA-II. **São dois caminhos independentes** — o builder não chama o optimizer, e o optimizer não é chamado no fluxo de construct. | O fluxo principal (`POST /model-portfolios/{id}/construct`) usa a heurística simples, não a otimização matemática. O optimizer só é acessível via `/analytics/optimize` (rota separada). Os portfólios construídos **não respeitam rigorosamente** o teto de CVaR — a heurística distribui por score sem constraint de CVaR. | **Crítica** |
| **G5.2 — StrategicAllocation não alimenta o Optimizer automaticamente** | O optimizer recebe `block_ids`, `expected_returns`, `cov_matrix`, `constraints` como parâmetros da rota. Não há pipeline que leia `StrategicAllocation` → compute retornos esperados → monte constraints → chame o optimizer. | O analista precisa montar manualmente os inputs do optimizer. Não há botão "otimizar este portfólio respeitando a alocação estratégica aprovada". | **Crítica** |
| **G5.3 — Sem construção simultânea dos 3 mandatos** | `POST /model-portfolios/{id}/construct` constrói um portfólio por vez. Não há endpoint que construa os 3 perfis atomicamente a partir do mesmo universo aprovado. | O ideal prevê "o algoritmo aloca os ativos aprovados nas 3 carteiras-modelo". Hoje cada perfil é construído isoladamente. | **Alta** |
| **G5.4 — Expected returns não derivados de macro** | O optimizer recebe `expected_returns` como input, mas não há service que derive retornos esperados dos macro scores/regime. Black-Litterman ou similar não implementado. | Retornos esperados são inseridos manualmente. A ponte macro → retornos esperados → optimizer não existe. | **Alta** |
| **G5.5 — Rebalance post-construction ausente** | Após `construct()`, os pesos são salvos em `fund_selection_schema` mas **não** propagados para `StrategicAllocation` nem para `PortfolioSnapshot`. O optimizer e o monitoring olham para fontes diferentes de "pesos atuais". | Silos de dados: builder salva em JSONB, monitoring lê de snapshot, optimizer recebe por parâmetro. | **Alta** |

### Costura Necessária

Esta é a etapa com **maior gap funcional**. A ponte principal que falta:

```
StrategicAllocation (approved, Etapa 1)
  └─► NOVO: PortfolioConstructionPipeline
        ├─ Para cada perfil (conservative, moderate, growth):
        │   ├─ Lê StrategicAllocation targets por bloco
        │   ├─ Lê universo aprovado (asset_universe)
        │   ├─ Computa expected_returns de NAV history (ou Black-Litterman c/ macro views)
        │   ├─ Monta cov_matrix de retornos
        │   ├─ Monta ProfileConstraints (cvar_limit, block min/max, max_single_fund)
        │   ├─ Chama optimizer_service.optimize_portfolio()
        │   └─ Persiste resultado em ModelPortfolio.fund_selection_schema
        │        + Propaga para PortfolioSnapshot.weights (dia 0)
        └─ Atomicidade: 3 perfis construídos em batch
```

---

## Etapa 6 — Continuous Monitoring & Tactical Rebalancing

### Status Atual: Parcialmente Implementado (~75%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| Portfolio Eval Worker | `workers/portfolio_eval.py` (lock 900_008) | CVaR diário, breach detection, regime classification, PortfolioSnapshot |
| Drift Check Worker | `workers/drift_check.py` (lock 42) | Drift vs targets, RebalanceEvent quando drift > threshold |
| Risk Calc Worker | `workers/risk_calc.py` (lock 900_007) | CVaR, Sharpe, momentum (RSI, Bollinger, OBV) por fund, diário |
| Drift Monitor | `vertical_engines/wealth/monitoring/drift_monitor.py` | Style drift (DTW) + universe removal impact |
| Alert Engine | `monitoring/alert_engine.py` | DD expiry >12m, rebalance overdue >90d |
| Strategy Drift Scanner | `monitoring/strategy_drift_scanner.py` | Z-score anomaly (90d vs 360d baseline), |z| > 2.0 |
| Rebalancing Service | `vertical_engines/wealth/rebalancing/service.py` | Impact analysis + weight proposals (proportional redistribution) |
| Weight Proposer | `rebalancing/weight_proposer.py` | Iterative clamping dentro de bounds, max 10 iterações |
| Correlation Service | `vertical_engines/wealth/correlation/service.py` | Marchenko-Pastur denoising, absorption ratio, contagion pairs |
| Watchlist Service | `vertical_engines/wealth/watchlist/service.py` | Detecção de transições PASS → FAIL |
| CVaR Service | `quant_engine/cvar_service.py` | Cornish-Fisher CVaR, breach classification (ok/warning/breach) |

### O que funciona

- **Pipeline diário robusto:** `risk_calc` → `portfolio_eval` → `drift_check`, todos com advisory locks e hypertable output.
- **CVaR monitoring:** Breach detection com `consecutive_breach_days` e regime tracking.
- **Multi-layer drift:** DTW style drift + allocation drift + strategy drift (Z-score) — 3 perspectivas complementares.
- **Alert system:** DD expiry + rebalance overdue scanning.
- **Rebalancing engine:** Impact analysis (quais portfólios afetados) + weight proposals (redistribuição proporcional dentro de bounds).
- **Correlation/concentration:** Marchenko-Pastur eigenvalue decomposition, absorption ratio, contagion pair detection.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G6.1 — Overlap detection ausente** | `CorrelationService` detecta correlação entre instrumentos, mas **não** detecta overlap de posições (mesmo holding aparecendo em múltiplos fundos via N-PORT). Se Fund A e Fund B ambos possuem 15% em AAPL, o portfólio tem concentração oculta. | Risco de concentração hidden — correlação mede co-movimento, não co-holding. São riscos distintos. | **Alta** |
| **G6.2 — Limites setoriais não monitorados** | Nenhum worker ou scanner verifica concentração setorial do portfólio agregado (ex: >30% em tech via holdings dos fundos). | O ideal prevê "fiscalizam limites setoriais". Não existe sector limit check. | **Alta** |
| **G6.3 — Regime-triggered rebalance não wired** | `RebalancingService.detect_regime_trigger()` existe mas **não está conectado a nenhum scheduler/worker**. Código comment indica "future sprint". | Mudanças de regime (stress → crisis) não disparam rebalance automático. Apenas drift-triggered funciona. | **Média** |
| **G6.4 — Rebalancing proposals sem execução** | `propose_weights()` gera proposals mas não há endpoint para **aplicar** a proposal (atualizar `ModelPortfolio.fund_selection_schema` + `PortfolioSnapshot`). | Proposals são read-only. O ciclo rebalance → apply → persist não fecha. | **Alta** |
| **G6.5 — VaR limit monitoring ausente** | Monitoring foca em CVaR mas o ideal menciona "limites de VaR". `cvar_service` computa VaR como subproduto mas não há trigger/alert específico para VaR breach. | Menor impacto (CVaR é mais conservador que VaR), mas gap formal vs o ideal descrito. | **Baixa** |

### Costura Necessária

```
NOVO: HoldingsOverlapScanner
  ├─ Lê N-PORT holdings dos fundos no portfólio
  ├─ Agrega posições por security (CUSIP/ISIN)
  ├─ Detecta concentração hidden (>X% em mesma security via múltiplos fundos)
  └─ Detecta concentração setorial (>Y% em mesmo setor GICS)

EXISTENTE → WIRE: detect_regime_trigger()
  └─ Adicionar ao portfolio_eval worker:
       if regime changed to stress/crisis → call detect_regime_trigger()
       → create RebalanceEvent with trigger='regime_change'

NOVO: ApplyRebalanceEndpoint
  └─ POST /rebalancing/proposals/{id}/apply
       ├─ Atualiza ModelPortfolio.fund_selection_schema
       ├─ Cria PortfolioSnapshot entry (dia 0 do novo portfólio)
       └─ Audit event
```

---

## Etapa 7 — Client Reporting (Marketing & Tracking)

### Status Atual: Parcialmente Implementado (~55%)

### Engines Vinculados

| Componente | Arquivo | Função |
|------------|---------|--------|
| Fact Sheet Engine | `vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` | PDF generation (Executive 1-2p, Institutional 3-4p) |
| Executive Renderer | `fact_sheet/executive_renderer.py` | PDF 1-2 páginas: holdings, returns, risk |
| Institutional Renderer | `fact_sheet/institutional_renderer.py` | PDF 3-4 páginas: + regime overlay + stress scenarios |
| Chart Builder | `fact_sheet/chart_builder.py` | matplotlib: NAV line, allocation pie, regime overlay |
| i18n | `fact_sheet/i18n.py` | PT/EN labels |
| Track Record | `model_portfolio/track_record.py` | Walk-forward backtest + stress scenarios |
| Fact Sheet Worker | `workers/fact_sheet_gen.py` (lock 900_001) | Mensal: gera executive + institutional para todos os portfolios ativos |
| Investment Outlook | `vertical_engines/wealth/investment_outlook.py` | Narrativa trimestral LLM + PDF |
| Flash Report | `vertical_engines/wealth/flash_report.py` | Event-driven market flash (48h cooldown) |
| Manager Spotlight | `vertical_engines/wealth/manager_spotlight.py` | Deep-dive single manager analysis |
| Content Routes | `routes/content.py` | Generate, approve, download PDF (2-person rule) |
| Fact Sheet Routes | `routes/fact_sheets.py` | Generate on-demand, list, download |

### O que funciona

- **Fact Sheets em PDF:** Dois formatos (Executive para prospects, Institutional para clientes), com charts (NAV, allocation pie, regime overlay), backtest, stress scenarios, i18n PT/EN.
- **Worker mensal:** Gera automaticamente para todos os portfolios ativos.
- **Content pipeline:** Flash Report (48h cooldown), Investment Outlook (trimestral), Manager Spotlight (on-demand), todos com LLM + PDF rendering.
- **Approval workflow:** 2-person rule (approver ≠ creator), status: draft → review → approved → published.

### Gaps (Action Plan)

| Gap | Descrição | Impacto | Prioridade |
|-----|-----------|---------|------------|
| **G7.1 — NAV diário consolidado do portfólio modelo não existe** | `PortfolioSnapshot` captura CVaR e regime, mas **não** captura NAV consolidado diário. `track_record.py` computa backtest sob demanda (não persiste série diária). Fact Sheet usa backtest results, não uma série NAV real. | O ideal prevê "processar o histórico consolidado diário dos portfólios". Sem NAV diário persistido, reporting é sempre re-computado e não há "track record real" — apenas backtest. | **Crítica** |
| **G7.2 — Portfólios modelo não parecem fundos independentes** | Fact Sheet mostra "Model Portfolio: Conservative" — não um fundo com nome, CNPJ/LEI, gestora, custodiante. Não há camada de branding que transforme o portfólio modelo em um "produto comercializável". | O ideal prevê "fazendo os portfólios modelo parecerem fundos maduros e independentes". Falta metadata de produto (nome comercial, benchmark composite, início do track record, disclaimer legal). | **Alta** |
| **G7.3 — Long Form Report ausente** | Existe Fact Sheet (resumo visual) e DD Report (fund-level). **Não** existe "Long Form Report" do portfólio modelo — um documento 10-20 páginas com: macro context + allocation rationale + per-fund summaries + performance attribution + risk decomposition + outlook. | O ideal prevê relatórios para "clientes atuais" (Long Form). Fact Sheet é marketing (prospects). O gap é o relatório detalhado para clientes existentes. | **Alta** |
| **G7.4 — Performance Attribution (Brinson-Fachler) não integrada ao reporting** | `vertical_engines/wealth/attribution/` existe com Brinson-Fachler policy benchmark attribution, mas **não** é chamada pelo Fact Sheet Engine nem por nenhum report renderer. | Attribution engine existe mas está órfão — nunca aparece em nenhum PDF. | **Média** |
| **G7.5 — Fee Drag não integrada ao reporting** | `vertical_engines/wealth/fee_drag/` existe com fee drag ratio e efficiency analysis, mas **não** aparece em nenhum relatório. | Fee transparency é item regulatório. Existe engine mas não chega ao cliente. | **Média** |
| **G7.6 — Série NAV para benchmark composite ausente** | `ModelPortfolio.benchmark_composite` field existe mas é string livre. Não há engine que compute NAV diário do benchmark composite (weighted ETF benchmark por bloco). | Fact Sheet mostra NAV do portfólio vs. benchmark, mas benchmark é genérico. Deveria ser o composite ponderado dos benchmark_tickers dos blocos. | **Média** |

### Costura Necessária

```
NOVO: DailyPortfolioNAV Worker (extensão do portfolio_eval)
  ├─ Para cada ModelPortfolio publicado:
  │   ├─ Lê fund_selection_schema (pesos por fund)
  │   ├─ Busca NAV diário de cada fund em nav_timeseries
  │   ├─ Computa portfolio_nav = Σ(weight_i × nav_i) normalizado a base 1000
  │   ├─ Computa benchmark_nav = Σ(block_weight_i × benchmark_etf_nav_i)
  │   └─ Persiste em NOVA hypertable: model_portfolio_nav
  │        (portfolio_id, date, portfolio_nav, benchmark_nav, daily_return, cumulative_return)
  └─ Fact Sheet Engine lê desta tabela em vez de re-computar backtest

NOVO: LongFormReportEngine
  ├─ Capítulos:
  │   1. Macro Context (do MacroReview mais recente)
  │   2. Strategic Allocation Rationale (do StrategicAllocation + decision_rationale)
  │   3. Portfolio Composition & Changes (delta vs mês anterior)
  │   4. Performance Attribution (Brinson-Fachler — engine já existe!)
  │   5. Risk Decomposition (CVaR por bloco, regime analysis)
  │   6. Fee Analysis (Fee Drag — engine já existe!)
  │   7. Per-Fund Highlights (top movers, newcomers, exits)
  │   8. Forward Outlook (do InvestmentOutlook engine)
  └─ Renderer: 10-20 páginas PDF, similar ao DD Report pattern (parallel chapters)

EXISTENTE → INTEGRAR:
  ├─ attribution/ → FactSheetEngine (institucional) + LongFormReportEngine
  └─ fee_drag/ → FactSheetEngine (institucional) + LongFormReportEngine
```

---

## Matriz de Prioridades Consolidada

### Crítico (bloqueia o ciclo completo)

| ID | Gap | Etapa | Esforço Estimado |
|----|-----|-------|-----------------|
| G5.1 | Portfolio Builder e Optimizer desconectados | 5 | Médio — wire optimizer into construct flow |
| G5.2 | StrategicAllocation não alimenta Optimizer | 5 | Médio — pipeline de inputs automáticos |
| G7.1 | NAV diário consolidado do portfólio modelo não existe | 7 | Médio — novo worker + hypertable |

### Alto (funcionalidade incompleta visível ao usuário)

| ID | Gap | Etapa | Esforço Estimado |
|----|-----|-------|-----------------|
| G1.1 | Macro Report não gera Sugestão de Asset Allocation | 1 | Alto — novo engine prescritivo |
| G1.2 | Aprovação macro não alimenta StrategicAllocation | 1 | Baixo — wire approve → upsert allocation |
| G5.3 | Sem construção simultânea dos 3 mandatos | 5 | Baixo — batch endpoint |
| G5.4 | Expected returns não derivados de macro | 5 | Alto — Black-Litterman ou rules-based |
| G5.5 | Rebalance post-construction ausente | 5 | Baixo — propagação de pesos |
| G6.1 | Holdings overlap detection ausente | 6 | Médio — novo scanner N-PORT based |
| G6.2 | Limites setoriais não monitorados | 6 | Médio — sector aggregation via N-PORT GICS |
| G6.4 | Rebalancing proposals sem execução | 6 | Baixo — apply endpoint |
| G7.2 | Portfólios modelo não parecem fundos independentes | 7 | Baixo — metadata + branding layer |
| G7.3 | Long Form Report ausente | 7 | Alto — novo engine multi-chapter |

### Médio (melhoria significativa)

| ID | Gap | Etapa | Esforço Estimado |
|----|-----|-------|-----------------|
| G1.3 | TacticalPosition sem trigger automático | 1 | Médio |
| G1.4 | Asset Allocation preditivo ausente | 1 | Alto |
| G3.1 | Bond Brief não implementado | 3 | Médio |
| G4.2 | Sem expiração automática de aprovação | 4 | Baixo |
| G6.3 | Regime-triggered rebalance não wired | 6 | Baixo |
| G7.4 | Attribution não integrada ao reporting | 7 | Baixo |
| G7.5 | Fee Drag não integrada ao reporting | 7 | Baixo |
| G7.6 | Benchmark composite NAV ausente | 7 | Médio |

### Baixo (nice-to-have)

| ID | Gap | Etapa | Esforço Estimado |
|----|-----|-------|-----------------|
| G2.1 | Screener não recebe targets de bloco | 2 | Baixo |
| G2.2 | Batch scheduling ausente | 2 | Trivial |
| G4.1 | Watchlist → Approved sem re-screening | 4 | Baixo |
| G6.5 | VaR limit monitoring ausente | 6 | Trivial |

---

## As 3 Pontes que Faltam

O sistema tem **engines excelentes** mas **3 costuras estruturais** estão ausentes, quebrando o ciclo:

### Ponte 1: Macro → Allocation (Etapa 1 → 5)

```
HOJE:   MacroReview (texto) ──X──► StrategicAllocation (manual)
IDEAL:  MacroReview (approved) ──► AllocationProposal (numérico) ──► StrategicAllocation (auto)
```

O CIO aprova um relatório textual, depois precisa manualmente atualizar as alocações estratégicas em outra tela. A ponte prescritiva (regime → tilts → pesos sugeridos) não existe.

### Ponte 2: Allocation → Otimização → Portfólio (Etapa 5)

```
HOJE:   StrategicAllocation ──X──► portfolio_builder (heurística) ──X──► optimizer (isolado)
IDEAL:  StrategicAllocation ──► expected_returns + cov_matrix ──► optimizer (CVaR-constrained) ──► ModelPortfolio
```

O `portfolio_builder` usa distribuição score-proporcional (sem constraint de CVaR). O `optimizer_service` (cvxpy/NSGA-II) existe mas não é chamado no fluxo de construção. São dois caminhos paralelos que nunca se cruzam.

### Ponte 3: Portfólio → NAV Diário → Reporting (Etapa 5 → 7)

```
HOJE:   ModelPortfolio.fund_selection_schema ──► backtest on-demand ──► Fact Sheet (re-computa sempre)
IDEAL:  ModelPortfolio ──► daily NAV worker ──► model_portfolio_nav hypertable ──► Fact Sheet + Long Form Report
```

Não existe série NAV diária persistida dos portfólios modelo. Fact Sheets re-computam backtest a cada geração. Não há "track record real" — apenas backtested. E não existe Long Form Report para clientes existentes.

---

## Conclusão

O sistema possui **~85% dos engines necessários** já implementados e testados. Os módulos individuais (Screener, DD Report, Optimizer, CVaR, Monitoring, Fact Sheet) são maduros e bem arquitetados. O gap não é de **capacidade** — é de **integração**. As 3 pontes acima representam o trabalho de costura para transformar um conjunto de calculadoras independentes em um ciclo contínuo de vida do ativo e do portfólio.
