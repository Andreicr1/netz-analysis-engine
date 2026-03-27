# Netz Wealth OS — Referência Completa da Vertical
## Documento Institucional — Março 2026

---

# Visão Geral

O Netz Wealth OS é um sistema operacional para gestão institucional de portfólios que integra inteligência macroeconômica, otimização quantitativa, triagem de fundos, due diligence e reporting em um único ambiente multi-tenant.

O sistema cobre o ciclo completo de decisão de investimento — da leitura macro até o relatório para o investidor final — sem dependência de planilhas, provedores externos de dados de risco ou ferramentas desconectadas.

**Números do sistema (Março 2026):**

| Dimensão | Valor |
|----------|-------|
| Testes automatizados | 2.670+ |
| Migrações de banco | 63 |
| Módulos verticais (vertical_engines/wealth) | 14 pacotes + 6 engines |
| Serviços quantitativos (quant_engine) | 12 |
| Workers de ingestão/cálculo | 15 |
| Endpoints de API (wealth) | 75+ em 28 módulos de rotas |
| Modelos ORM (wealth) | 26 |
| Páginas frontend | 21 |
| Componentes frontend | 96 (39 wealth + 57 compartilhados) |

---

# 1. Inteligência Macroeconômica

## O que faz

Monitora continuamente indicadores de 7 fontes primárias, classifica o regime de mercado automaticamente e gera relatórios semanais de comitê com detecção de mudanças materiais por região. O CIO aprova ou rejeita o diagnóstico; a aprovação dispara a cascata de alocação.

## Fontes de dados ingeridas por workers automáticos

| Fonte | Volume | Frequência | Worker |
|-------|--------|------------|--------|
| Federal Reserve (FRED) | ~65 séries (4 regiões + global + crédito + 20 metros Case-Shiller) | Diária | `macro_ingestion` |
| Tesouro dos EUA | 278 séries (taxas, dívida, leilões, câmbio, juros) | Diária | `treasury_ingestion` |
| OFR (Office of Financial Research) | 23 séries (alavancagem, AUM, estratégia, repo, stress) | Semanal | `ofr_ingestion` |
| BIS (Bank for International Settlements) | Credit gap, DSR, preços imobiliários — 43 países | Trimestral | `bis_ingestion` |
| FMI (IMF WEO) | GDP, inflação, fiscal, dívida — 44 países, horizonte 2030 | Trimestral | `imf_ingestion` |
| SEC EDGAR (13F) | 1,09M posições de 12 grandes institucionais — 25 anos de histórico | Semanal | `sec_13f_ingestion` |
| SEC EDGAR (N-PORT) | 132.823 posições de 69 companhias de investimento | Semanal | `nport_ingestion` |
| SEC FOIA (Form ADV) | 976.980 gestores (15.963 RIAs, >US$ 38T AUM combinado) | Mensal | `sec_adv_ingestion` |

**Princípio arquitetural: dados externos nunca são chamados durante requests de usuário.** Toda ingestão é feita por workers de background com advisory locks determinísticos. Rotas e engines leem exclusivamente do banco de dados — zero latência de APIs externas no caminho crítico.

## Detecção de regime

O sistema classifica o regime de mercado em dois níveis — global e regional — usando uma árvore de decisão determinística (sem ML, sem APIs externas).

**Regime global** (4 estados, prioridade descendente):

| Prioridade | Condição | Regime |
|-----------|----------|--------|
| 1 (máxima) | VIX >= 35 | CRISIS |
| 2 | CPI YoY >= 4,0% | INFLATION |
| 3 | VIX >= 25 | RISK_OFF |
| 4 (base) | Nenhuma acima | RISK_ON |

Sinais informativos adicionais: inversão da yield curve (< -0.10), Sahm Rule (>= 0.50).

**Regime regional** (por região — US, Europa, Ásia, Emergentes):
Cada região classificada via credit spreads ICE BofA (OAS). Thresholds: Risk-Off a 550 bps, Crisis a 800 bps.

**Composição global:** Pesos GDP (US: 0.25, Europa: 0.22, Ásia: 0.28, EM: 0.25). Regras pessimistas: 2+ regiões em CRISIS → global CRISIS; região com peso >= 0.20 em CRISIS → global mínimo RISK_OFF.

## Fluxo de aprovação

```
MacroRegionalSnapshot (dados globais, FRED + OAS)
    ↓  POST /macro/reviews/generate
MacroReview (pendente, com regime hierárquico + score deltas)
    ↓  CIO revisa e aprova (PATCH /macro/reviews/{id}/approve)
Tilts Black-Litterman computados automaticamente
    ↓
StrategicAllocation persistida (time-versioned, effective_from = today)
```

---

# 2. Alocação Estratégica (Ponte 1)

## O que faz

Transforma a visão macroeconômica aprovada pelo CIO em pesos numéricos de alocação por bloco de ativos. Implementa uma abordagem inspirada no Black-Litterman onde o regime de mercado é traduzido em tilts sobre a alocação estratégica neutra.

## Blocos de alocação

O sistema organiza o universo de investimentos em blocos geográfico-setoriais (ex: `na_equity_large`, `dm_europe_equity`, `fi_ig_core`, `alt_real_estate`, `cash`). Cada bloco tem peso-alvo, mínimo e máximo por perfil de investimento.

## Tilts de regime

A matriz de tilts define a intensidade do ajuste por classe de ativo e regime:

| Regime | Equity | Renda Fixa | Alternativos | Caixa |
|--------|--------|------------|--------------|-------|
| RISK_ON | +30% do room | -15% | +10% | -20% |
| RISK_OFF | -25% | +25% | +5% | +15% |
| INFLATION | -10% | -20% | +30% | +10% |
| CRISIS | -50% | +20% | -10% | +40% |

**Room** = distância entre o peso-alvo e o limite (max se tilt positivo, min se negativo). Os tilts nunca violam os limites min/max.

**Tilts regionais** (somente equity): Scores regionais desviam blocos de equity da região correspondente. Sensibilidade: 0.3% do room por ponto acima/abaixo de 50.

**Renormalização:** Cash absorve residual primeiro; restante distribuído proporcionalmente.

## Persistência temporal

Alocações estratégicas são versionadas com `effective_from`/`effective_to`. Queries sempre filtram pela data vigente. O campo `actor_source='macro_proposal'` permite expirar seletivamente quando novos regimes viram.

---

# 3. Otimização de Portfólios (Ponte 2)

## O que faz

Recebe os pesos de bloco da Ponte 1 e resolve a alocação por fundo individual usando o solver cônico CLARABEL. Opera em nível de fundo, respeitando constraints de grupo que forçam os somatórios de bloco a permanecer dentro dos limites da alocação estratégica.

## Cascata de 3 fases

O otimizador implementa um fallback determinístico para garantir que o CVaR nunca seja violado sem controle:

```
Phase 1: Máximo Retorno Ajustado ao Risco
    ↓  CVaR violado?
Phase 2: Teto de Variância (σ_max = |CVaR_limit| / 3.71)
    ↓  Infeasível?
Phase 3: Mínima Variância (melhor possível)
    ↓  Todos falharam?
Retorna Phase 1 com flag cvar_violated (degradação graciosa)
```

**Phase 1 — Max Risk-Adjusted Return:**
Maximiza `μᵀw − λwᵀΣw` (λ = 2.0) sujeito a constraints de bloco, concentração e fully-invested. Verifica CVaR parametricamente após solução.

**Phase 2 — Variance Ceiling:**
Converte o limite de CVaR em teto de variância via derivação analítica (coeficiente 3.71 para 95% de confiança sob normal). Maximiza retorno esperado com `wᵀΣw ≤ σ²_max` como constraint convexa.

**Phase 3 — Minimum Variance Fallback:**
Minimiza `wᵀΣw` sem teto de CVaR — aceita o melhor possível.

## Constraints em todas as fases

- `Σw = 1` (fully invested)
- `w ≥ 0` (long-only)
- `w_i ≤ max_single_fund` (concentração por fundo, ex: 15%)
- `Σw[bloco] ≥ min_bloco` e `Σw[bloco] ≤ max_bloco`

## CVaR parametrico Cornish-Fisher

O CVaR é calculado com ajuste para fat tails (assimetria e curtose):

```
z_cf = z + (z²-1)·skew/6 + (z³-3z)·kurt/24 − (2z³-5z)·skew²/36
CVaR = −(μ_p + σ_p · z_cf) + σ_p · φ(z_cf) / α
```

Para distribuição normal, simplifica para `CVaR ≈ σ × 3.71 − μ`.

## Solver

- **CLARABEL** (interior-point, cônico): solver primário, tipicamente 50-200ms
- **SCS** (ADMM): fallback se CLARABEL falha
- Execução via `asyncio.to_thread` para não bloquear o event loop

## Fronteira de Pareto (multiobjetivo)

O endpoint `POST /analytics/optimize/pareto` gera a fronteira eficiente risco-retorno. Roda como background job com SSE progress (retorna 202 imediatamente). Resultados cacheados em Redis (SHA-256 dos inputs, TTL 1h).

---

# 4. Triagem de Fundos (Screener)

## O que faz

Pipeline determinístico de três camadas que avalia cada fundo do universo. Sem LLM, sem ML externo — 100% regras e estatística.

## As 3 camadas

**Camada 1 — Eliminatória (filtros hard):**
Restrições inegociáveis do mandato. Fundos que falham aqui são eliminados sem apelação. Exemplos: AUM mínimo, domicílio proibido, tipo de fundo incompatível.

**Camada 2 — Adequação ao mandato:**
Avaliação de aderência às restrições do perfil de investimento com margem de watchlist. Critérios: risk bucket (classe de ativo), requisitos ESG, restrições de domicílio, limiares de liquidez, restrições de moeda. Retorna score de adequação (0-100) e motivos de desqualificação.

**Camada 3 — Ranking quantitativo:**
Percentil dentro do peer group. Métricas: Sharpe ratio, máximo drawdown, retorno anualizado, volatilidade, meses positivos. Normalização 0-100 com inversão para métricas "menor é melhor" (drawdown, volatilidade). Score composto ponderado e auditável.

## Peer group dinâmico

Matching hierárquico: `asset_class → geography → sub_category`. Tamanho mínimo do grupo: 20 instrumentos. Se o grupo natural é pequeno, o matcher sobe na hierarquia até encontrar 20+ pares.

## Cobertura do universo

| Fonte | Volume |
|-------|--------|
| Gestores SEC (FOIA) | 976.980 entidades |
| Registered Investment Advisers | 15.963 |
| AUM combinado (RIAs) | > US$ 38 trilhões |
| Fundos UCITS (ESMA) | 10.436 de 658 gestores em 25 países |
| Holdings 13F (institucionais) | 1.092.225 posições / 25 anos |

---

# 5. Due Diligence (DD Report)

## O que faz

Gera relatórios de due diligence com 8 capítulos estruturados, integrando dados quantitativos de risco, dados regulatórios da SEC e evidências documentais. Cada relatório produz um score de confiança determinístico e uma âncora de decisão para o comitê.

## Os 8 capítulos

| # | Capítulo | Conteúdo |
|---|----------|----------|
| 1 | Sumário Executivo | Visão geral do fundo, tese de investimento, riscos-chave |
| 2 | Estratégia de Investimento | Análise da estratégia declarada vs comportamento observado |
| 3 | Avaliação do Gestor | AUM, equipe, histórico, dados Form ADV (SEC) |
| 4 | Análise de Performance | Retornos, consistência, drawdowns, peer comparison |
| 5 | Framework de Risco | CVaR, VaR, volatilidade, correlação, concentração |
| 6 | Análise de Taxas | Management fee, performance fee, fee drag ratio |
| 7 | Due Diligence Operacional | Custódia, auditoria, compliance, histórico regulatório |
| 8 | Recomendação | Decisão (APROVAR / CONDICIONAL / REJEITAR) com justificativa |

## Arquitetura de geração

- **Capítulos 1-7:** Gerados em paralelo via `ThreadPoolExecutor(5)`. Cada capítulo recebe um `EvidencePack` congelado (frozen dataclass) — garantia de thread-safety.
- **Capítulo 8 (Recomendação):** Gerado sequencialmente após 1-7, consumindo os sumários dos capítulos anteriores.
- **Revisão adversarial:** O `CriticService` revisa cada capítulo em até 3 iterações. Circuit breaker de 3 minutos aborta capítulos que excedem o tempo.
- **Pattern never-raises:** Nenhum capítulo que falha interrompe a geração dos demais. Capítulos com falha retornam `status="failed"` com `confidence=0.0`.

## Score de confiança

Score determinístico 0-100 baseado em: completude de evidência, cobertura quantitativa e resultado da revisão adversarial. Decisão de comitê derivada do score e do conteúdo do capítulo de recomendação.

## Dados SEC integrados

| Fonte SEC | Uso no DD Report | Método DB-only |
|-----------|-----------------|----------------|
| Form ADV | Equipe, AUM, compliance, taxas | `AdvService.fetch_manager()`, `fetch_manager_funds()` |
| 13F Holdings | Posições do gestor, drift trimestral | `ThirteenFService.read_holdings()`, `compute_diffs()` |
| N-PORT | Holdings do fundo, concentração setorial | `sec_nport_holdings` (tabela global) |

---

# 6. Portfólios Modelo

## O que faz

Construção e acompanhamento de portfólios modelo com alocação estratégica por perfil. Cada portfólio é tratado como entidade de primeira classe para analytics, charts e comparações.

## Perfis

O sistema suporta múltiplos perfis de investimento (tipicamente Conservative, Moderate, Growth), cada um com:
- Limites de alocação por bloco (min/max/target)
- Limite de CVaR (ex: -8% a 95% de confiança)
- Limite de concentração por fundo (ex: 15%)

## Construção

**Via otimizador (primário):** Usa os pesos da cascata CLARABEL diretamente — `construct_from_optimizer()`.

**Via heurística (fallback):** Se dados insuficientes (<120 dias de NAV alinhado entre fundos), usa distribuição proporcional ao score dentro de cada bloco — `construct()`.

O resultado é persistido como JSONB em `ModelPortfolio.fund_selection_schema`:

```json
{
  "profile": "moderate",
  "funds": [
    { "instrument_id": "...", "fund_name": "Vanguard TSM", "block_id": "na_equity_large", "weight": 0.15, "score": 85.5 }
  ],
  "optimization": {
    "expected_return": 0.0654, "portfolio_volatility": 0.0877,
    "sharpe_ratio": 0.5234, "solver": "CLARABEL", "status": "optimal",
    "cvar_95": -0.0654, "cvar_limit": -0.0800, "cvar_within_limit": true
  }
}
```

## NAV sintético (Ponte 3)

O worker `portfolio_nav_synthesizer` (diário) computa o NAV sintético do portfólio a partir dos retornos ponderados dos fundos componentes:

```
NAV₀ = 1000.0 (inception)
Rₜ = Σ(wᵢ × rᵢₜ)   para cada fundo i
NAVₜ = NAVₜ₋₁ × (1 + Rₜ)
```

Renormalização automática quando um fundo não reporta retorno num dado dia. Lookback máximo de 5 anos (1260 dias). Batch upsert de 500 rows com `ON CONFLICT DO UPDATE`.

## Polimorfismo via nav_reader

Todo código que precisa de séries NAV usa `nav_reader.py` — nunca importa tabelas NAV diretamente. O `nav_reader` detecta se o `entity_id` é um fundo ou portfólio e retorna `NavRow` normalizado. Isso permite que analytics, charts e comparações funcionem identicamente para fundos individuais e portfólios modelo.

## Benchmark composto

Para cada portfólio modelo, o sistema compõe um benchmark ponderado a partir dos benchmarks de cada bloco de alocação (ETFs de referência como SPY, AGG, VWO). O `BenchmarkCompositeService` calcula o NAV sintético do benchmark com algoritmo idêntico ao do portfólio.

**Resolução de benchmark em 3 tiers:**
1. `benchmark_id` explícito (query param)
2. `AllocationBlock.benchmark_ticker` do bloco da entidade
3. SPY como fallback universal

---

# 7. Monitoramento Contínuo

## Avaliação diária de risco (portfolio_eval)

Worker diário que avalia o estado de cada portfólio:
- Computa CVaR corrente vs limite do perfil
- Classifica: `ok` | `warning` | `breach`
- Rastreia dias consecutivos de breach
- Registra regime corrente e probabilidades
- Persiste snapshot em hypertable `portfolio_snapshots`

## Detecção de drift estratégico (drift_check)

- **DTW (Dynamic Time Warping):** Compara retornos normalizados do fundo vs benchmark do bloco. Score 0-1; threshold 0.15.
- **Z-score em 7 métricas de risco:** Baseline de 12 meses. Detecta mudança comportamental mesmo sem drift de retorno.
- **Resultado:** `on_track` | `drifting` | `severe`

## Sinais de momentum (pré-computados por risk_calc)

| Sinal | Descrição |
|-------|-----------|
| RSI-14 | Overbought (>70) / Oversold (<30) |
| Bollinger Bands | Posição dentro das bandas (0-1) |
| OBV Flow | Tendência de volume relativo |
| Score composto | Blend ponderado RSI + BB + OBV (0-100) |

Estes sinais são pré-computados na hypertable `fund_risk_metrics` — zero cálculo TA-Lib em tempo de request.

## Overlap de holdings (Sistema Circulatório)

Detecta concentração oculta cross-fund explodindo cada fundo até suas holdings individuais via dados N-PORT do SEC:

1. **HoldingsExploder** (I/O): Resolve CIK de cada fundo → query N-PORT mais recente → pondera cada holding pelo peso do fundo no portfólio
2. **OverlapScanner** (math pura): Agrega por CUSIP e por setor GICS; detecta breaches (exposição > 5% do portfólio total a um único CUSIP)

Exemplo: Se Fundo A (40% do portfólio) tem 8% em AAPL e Fundo B (30%) tem 5% em AAPL → exposição total AAPL = 4.7% (próximo do limite de 5%).

## Watchlist

Monitora transições PASS→FAIL no screener. Re-executa as 3 camadas de screening periodicamente e detecta fundos que perderam aderência ao mandato.

---

# 8. Correlação e Diversificação

## O que faz

Analisa a estrutura de correlação do portfólio com métodos de Random Matrix Theory e detecta contágio entre pares de fundos.

## Métodos

| Método | Descrição |
|--------|-----------|
| Marchenko-Pastur denoising | Filtra eigenvalues espúrios da matriz de correlação |
| Ledoit-Wolf shrinkage | Estimativa robusta de covariância |
| Absorption Ratio (Kritzman & Li, 2010) | Fração da variância explicada pelos primeiros eigenvalues — proxy de risco sistêmico |
| Diversification Ratio (Choueifaty) | Razão entre vol média ponderada e vol do portfólio |
| Contágio por pares | Detecta correlações elevadas vs baseline entre pares específicos de fundos |

---

# 9. Atribuição de Performance

## O que faz

Decomposição de retorno Policy Benchmark (padrão CFA CIPM) usando o método Brinson-Fachler com linking multiperiodo pelo método Carino.

## Fórmulas

```
Allocation Effect  = (w_p − w_b) × (r_b_i − R_b)     [Fachler adjustment]
Selection Effect   = w_b × (r_p_i − r_b_i)
Interaction Effect = (w_p − w_b) × (r_p_i − r_b_i)
```

Onde:
- `w_p`, `w_b`: pesos do portfólio e do benchmark no bloco
- `r_p_i`, `r_b_i`: retornos do portfólio e benchmark no bloco
- `R_b`: retorno total do benchmark

**Linking multiperiodo:** Carino (1999) com clamp em |k_t| ≤ 10.0 e fallback para média simples quando excess total ≈ 0.

---

# 10. Fee Drag Analysis

## O que faz

Quantifica o impacto das taxas sobre o retorno esperado de cada fundo e do portfólio como um todo.

## Métricas

- **Management fee** e **performance fee** extraídos do JSONB `attributes` de cada instrumento
- **Adições por tipo:** Bond → bid-ask spread; Equity → brokerage fee
- **Fee drag ratio:** `total_fee_pct / gross_expected_return`
- **Threshold de eficiência:** 50% — fundo flaggado como "ineficiente" se mais da metade do retorno bruto é consumida por taxas

---

# 11. Rebalanceamento

## O que faz

Engine de rebalanceamento com proposta automática de pesos, análise de impacto de turnover e estados de aprovação rastreáveis.

## Triggers

| Trigger | Descrição |
|---------|-----------|
| Violação de CVaR | Breach consecutivo acima do threshold de dias |
| Mudança de regime | Aprovação de novo MacroReview pelo CIO |
| Calendário | Periodicidade definida pelo gestor |
| Desativação de fundo | Fundo removido do universo aprovado |
| Drift detectado | Score DTW acima do threshold de severidade |

## Proposta de pesos

- **Redistribuição proporcional** dentro dos limites de alocação (feedback imediato)
- **Análise de impacto:** Estimativa de custos de transação (turnover)
- **Fluxo de aprovação:** `pending → approved → executed | rejected`

---

# 12. Reporting Institucional

## Engines de reporting

O sistema oferece dois engines de reporting para públicos distintos:

| Engine | Público-Alvo | Canal | Formato |
|--------|-------------|-------|---------|
| FactSheetEngine | Prospects (marketing) | Download PDF | Executive (4pg) ou Institucional (6-8pg) |
| LongFormReportEngine | Clientes existentes | SSE + JSON streaming | 8 capítulos interativos |

## Fact Sheet (PDF)

**Formato Executive (4 páginas):**
Cover + NAV chart + tabela de retornos (MTD/QTD/YTD/1Y/3Y)

**Formato Institucional (6-8 páginas):**

| Página | Conteúdo |
|--------|----------|
| 1 | Cover + NAV chart + Returns table |
| 2 | Allocation pie + Top 10 holdings + Risk metrics |
| 3 | Attribution analysis (Brinson, tabela 5 colunas) |
| 3-4 | Regime overlay chart + Stress scenarios |
| 4-5 | Fee drag analysis |
| 5-6 | ESG placeholder + Disclaimer |

Charts renderizados em paralelo via `ThreadPoolExecutor(4)`. Labels bilingues PT/EN via sistema de i18n (zero strings hardcoded nos renderers).

## Long-Form Report (SSE streaming)

8 capítulos gerados via `asyncio.gather` (paralelos):

| # | Capítulo | Fonte de dados |
|---|----------|---------------|
| 1 | Contexto Macro | MacroReview aprovado mais recente |
| 2 | Alocação Estratégica | StrategicAllocation vigente + rationale |
| 3 | Composição do Portfólio | Snapshot atual vs anterior (delta pesos) |
| 4 | Atribuição de Performance | Brinson-Fachler |
| 5 | Decomposição de Risco | CVaR por bloco |
| 6 | Análise de Taxas | Fee drag ratio |
| 7 | Destaques por Fundo | Top movers, newcomers, exits |
| 8 | Perspectiva Forward | WealthContent aprovado |

**Garantias de resiliência:**
- Falha de um capítulo não afeta os demais
- Status rollup: todos completos → `completed`; alguns falharam → `partial`; falha no pre-load → `failed`
- Concorrência controlada: máximo 2 reports simultâneos (semáforo)

**Streaming via SSE:**
Frontend usa `fetch()` + `ReadableStream` (não EventSource — necessário para enviar headers de autenticação). Progresso em tempo real: evento por capítulo concluído.

---

# 13. Gestão do Universo de Investimentos

## O que faz

Governa o ciclo de aprovação de instrumentos para inclusão no universo investível de cada organização.

## Fluxo de aprovação

```
Instrumento adicionado (pending)
    ↓  DD Report gerado e revisado
    ↓  Self-approval prevention (decided_by ≠ created_by)
Aprovação: pending → approved | watchlist | rejected
    ↓
Instrumento disponível para construção de portfólio (se approved)
```

## Tipos de instrumento

O modelo `Instrument` é polimórfico: `fund | bond | equity`. Atributos específicos por tipo armazenados em JSONB `attributes` (ex: `sec_cik`, `management_fee_pct`, `domicile`, `liquidity_days`).

---

# 14. Conteúdo Institucional

## O que faz

Gera conteúdo analítico para distribuição interna ou para investidores:

| Tipo | Descrição | Frequência |
|------|-----------|------------|
| Macro Committee Report | Relatório semanal de comitê com regime e score deltas | Semanal |
| Investment Outlook | Narrativa macro trimestral | Trimestral |
| Flash Report | Análise de evento de mercado (cooldown 48h) | Event-driven |
| Manager Spotlight | Deep-dive em gestor individual | On-demand |

Fluxo de aprovação: `draft → review → approved → published`. Conteúdo armazenado em markdown com dados estruturados em JSONB.

---

# 15. Frontend — Wealth OS

## Tecnologia

| Aspecto | Stack |
|---------|-------|
| Framework | SvelteKit 5 (adapter-node) |
| Linguagem UI | Svelte 5 com runes ($state, $derived, $effect) |
| Estilização | Tailwind 4.0 + CSS custom properties (design tokens Netz) |
| Charts | ECharts via wrappers @netz/ui |
| Tabelas | TanStack Table (@tanstack/svelte-table) |
| Auth | Clerk JWT v2 (server-side verification + client-side token injection) |
| Dados | SSR (batch Promise.all) + SSE (primário) + polling (fallback 30s) |
| Componentes | 57 compartilhados (@netz/ui) + 39 específicos wealth |

## Telas principais

| Tela | Função |
|------|--------|
| **Dashboard** | Regime, CVaR por perfil, alertas de drift, atividade recente |
| **Risk Workstation** | Dashboard de comando com qualidade de conexão (Live/Degraded/Offline), CVaR por perfil, histórico sparklines, alertas DTW |
| **Screener** | Master-detail com 3 abas: Catálogo de fundos (eVestment-style), Securities (CUSIP), Managers (SEC ADV). Filtros facetados, paginação server-side |
| **DD Reports** | Lista com filtro de status + geração + visualização com painel do critic |
| **Universe** | Universo aprovado com fluxo de aprovação |
| **Model Portfolios** | Grid de portfólios com criação, construção e tracking |
| **Portfolios** | Card por perfil com KPIs live via SSE — posições, obrigações, alertas, ações |
| **Allocation** | Alocação estratégica + ajustes táticos + alocação efetiva |
| **Analytics** | Atribuição Brinson-Fachler + strategy drift + backtest + correlação |
| **Exposure** | Heatmap geográfico × setorial (CSS grid) |
| **Macro** | Dashboard macro com série temporal, regime bands, reviews de comitê |
| **Documents** | Upload, review, OCR viewer |
| **Content** | Status de conteúdo gerado (macro reviews, flash reports, spotlights) |

## Comunicação em tempo real

**SSE-first com fallback para polling:**

```
1. Conecta SSE → escuta eventos (heartbeat resets a cada tick)
2. Se SSE falha ou timeout 45s sem dados → ativa polling (30s)
3. Gate de versão monotônica: update.version ≤ current → descarta
   (previne poll stale sobrescrever SSE fresh)
4. Se SSE recupera → desativa polling
```

Máximo 4 conexões SSE simultâneas (limite do browser). O Risk Store é a fonte única de verdade para CVaR, regime, drift e indicadores macro.

---

# 16. Métricas Quantitativas Computadas

O `quant_engine/` concentra 12 serviços de cálculo, todos funções sync puras sem I/O:

| Serviço | Métricas |
|---------|----------|
| `cvar_service` | CVaR (1m, 3m, 6m, 12m), VaR, breach status, dias consecutivos |
| `scoring_service` | Score composto 0-100 (return consistency, risk-adjusted return, drawdown control, IR, momentum, Lipper) |
| `regime_service` | Classificação global e regional (4 regimes × 4 regiões) |
| `attribution_service` | Brinson-Fachler (allocation, selection, interaction effects) |
| `correlation_regime_service` | Marchenko-Pastur, absorption ratio, diversification ratio, contágio |
| `optimizer_service` | CLARABEL 3-phase cascade, fronteira de Pareto |
| `drift_service` | DTW drift score, status (on_track, drifting, severe) |
| `portfolio_metrics_service` | Sharpe, Sortino, Calmar, alpha, beta, tracking error, information ratio |
| `drawdown_service` | Série de drawdown, máximo, corrente, top 5 períodos |
| `rolling_service` | Rolling returns 1M, 3M, 6M, 1Y anualizados |
| `backtest_service` | Walk-forward CV (training + gap + test), Sharpe por fold |
| `benchmark_composite_service` | NAV sintético de benchmark composto |

---

# 17. Arquitetura e Infraestrutura

## Multi-tenancy

Isolamento completo de dados por organização via Row-Level Security (RLS) no PostgreSQL. Contexto RLS definido por transação (`SET LOCAL`). 19 tabelas org-scoped + 5 tabelas globais (macro, benchmarks, SEC).

## Stack de infraestrutura (até 50 tenants, US$ 100-200/mês)

| Componente | Serviço | Função |
|------------|---------|--------|
| Banco de dados | Timescale Cloud | PostgreSQL 16 + TimescaleDB + pgvector |
| API | Railway | FastAPI (async, asyncpg) |
| Frontend | Railway | SvelteKit (adapter-node) |
| Cache / Pub-Sub | Upstash Redis | SSE bridging, job tracking, cache |
| Storage | Cloudflare R2 | Documentos, fact sheets, parquet |
| Auth | Clerk | JWT v2, multi-org |
| LLM | OpenAI API | Análise textual (DD reports, conteúdo) |
| OCR | Mistral | Extração de documentos |

## Hypertables TimescaleDB

| Tabela | Partição | Chunk | Compression | segmentby |
|--------|----------|-------|-------------|-----------|
| `nav_timeseries` | nav_date | 1 mês | 3 meses | organization_id |
| `fund_risk_metrics` | calc_date | 1 mês | 3 meses | organization_id |
| `portfolio_snapshots` | snapshot_date | 1 mês | 3 meses | organization_id |
| `benchmark_nav` | nav_date | 1 mês | 3 meses | block_id |
| `strategy_drift_alerts` | detected_at | 1 mês | 3 meses | instrument_id |
| `macro_data` | obs_date | 1 mês | 3 meses | series_id |
| `treasury_data` | obs_date | 1 mês | 3 meses | series_id |
| `ofr_hedge_fund_data` | obs_date | 3 meses | — | — |
| `bis_statistics` | period | 1 ano | — | — |
| `imf_weo_forecasts` | year | 1 ano | — | — |

## Auditoria imutável

Toda criação, atualização e exclusão é registrada via `write_audit_event()` com snapshots before/after em JSONB, correlacionados por `request_id`. Modelo `AuditEvent` (RLS-scoped). Usado em 17+ módulos.

---

# 18. Metodologia e Referências Acadêmicas

Todos os métodos quantitativos do sistema são baseados em literatura acadêmica e prática de mercado estabelecida:

| Método | Referência | Uso no sistema |
|--------|-----------|----------------|
| Black-Litterman | Black & Litterman (1992) | Tilts de regime sobre alocação neutra |
| CVaR (Expected Shortfall) | Rockafellar & Uryasev (2000) | Constraint de risco na otimização |
| Cornish-Fisher expansion | Cornish & Fisher (1937) | Ajuste de CVaR para fat tails |
| Brinson-Fachler attribution | Brinson, Hood & Beebower (1986), Fachler | Decomposição de retorno por bloco |
| Carino linking | Carino (1999) | Linking multiperiodo de atribuição |
| Dynamic Time Warping | Berndt & Clifford (1994) | Detecção de drift estratégico |
| Marchenko-Pastur | Marchenko & Pastur (1967) | Denoising de matriz de correlação |
| Ledoit-Wolf shrinkage | Ledoit & Wolf (2004) | Estimativa robusta de covariância |
| Absorption Ratio | Kritzman & Li (2010) | Proxy de risco sistêmico |
| Diversification Ratio | Choueifaty & Coignard (2008) | Medida de diversificação efetiva |

---

# 19. Workers de Background — Visão Consolidada

| Worker | Lock ID | Escopo | Tabela-alvo | Frequência |
|--------|---------|--------|-------------|------------|
| `macro_ingestion` | 43 | global | macro_data | Diária |
| `benchmark_ingest` | 900_004 | global | benchmark_nav | Diária |
| `instrument_ingestion` | 900_010 | org | nav_timeseries | Diária |
| `risk_calc` | 900_007 | org | fund_risk_metrics | Diária |
| `portfolio_eval` | 900_008 | org | portfolio_snapshots | Diária |
| `drift_check` | 42 | org | strategy_drift_alerts | Diária |
| `portfolio_nav_synthesizer` | 900_030 | org | model_portfolio_nav | Diária |
| `treasury_ingestion` | 900_011 | global | treasury_data | Diária |
| `ofr_ingestion` | 900_012 | global | ofr_hedge_fund_data | Semanal |
| `nport_ingestion` | 900_018 | global | sec_nport_holdings | Semanal |
| `sec_13f_ingestion` | 900_021 | global | sec_13f_holdings | Semanal |
| `sec_adv_ingestion` | 900_022 | global | sec_managers | Mensal |
| `bis_ingestion` | 900_014 | global | bis_statistics | Trimestral |
| `imf_ingestion` | 900_015 | global | imf_weo_forecasts | Trimestral |
| `screening_batch` | 900_002 | org | screening_results | Semanal |

Todos usam `pg_try_advisory_lock(ID)` com IDs determinísticos (nunca `hash()`), unlock em `finally`, upserts chunked (200-5000 rows por transação), e retry backoff (1s → 4s → 16s).

---

# Apêndice: Constantes e Limites do Sistema

| Constante | Valor | Contexto |
|-----------|-------|----------|
| CVaR coefficient | 3.71 | Normal distribution CVaR at 95% |
| Risk aversion (Phase 1) | 2.0 | Mean-variance tradeoff |
| Min aligned NAV observations | 120 | Optimizer input threshold |
| NAV synthesis max lookback | 1260 dias (5 anos) | Portfólio NAV |
| Batch upsert size | 500 rows | portfolio_nav_synthesizer |
| Chart ThreadPool workers | 4 | FactSheet parallel charts |
| LongFormReport max concurrent | 2 | SSE semaphore |
| DD Report max concurrent | 3 | SSE semaphore |
| Overlap breach threshold | 5% | CUSIP concentration limit |
| Fee drag threshold | 50% | Fee efficiency flag |
| Carino k_t clamp | ±10.0 | Multi-period attribution |
| DTW drift threshold | 0.15 | Drift detection (on_track → drifting) |
| Peer group min size | 20 | Screener Layer 3 |
| SSE heartbeat timeout | 45s | Frontend fallback trigger |
| Poll interval (fallback) | 30s | When SSE unavailable |
| Max concurrent SSE | 4 | Browser limit |
| Regional sensitivity | 0.003 | Equity tilt per score point |
| Weight precision | Decimal(6,4) | 4 decimal places |
| NaN max ratio (data quality) | 5% | Worker ingestion |
| Redis cache TTL (Pareto) | 1h | Optimizer results |

---

Documento preparado pela equipe Netz — Março 2026.
Confidencial. Para uso exclusivo dos sócios e stakeholders autorizados.
