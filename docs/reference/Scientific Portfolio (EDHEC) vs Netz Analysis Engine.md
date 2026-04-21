# Scientific Portfolio (EDHEC) vs Netz Analysis Engine — Análise Metodológica Comparativa

**Data:** 2026-04-18
**Autor:** Andrei / Netz
**Escopo:** Comparação entre o Methodology Guide do Scientific Portfolio e a implementação atual do Netz Analysis Engine (vertical wealth)
**Fonte SP:** https://scientific-portfolio.atlassian.net/wiki/spaces/MG/pages/25591816/Methodology+Guide + knowledge center público + papers EDHEC
**Fonte Netz:** CLAUDE.md + auditoria direta em `quant_engine/`, `vertical_engines/wealth/`, `ai_engine/`

---

## 1. Sumário executivo

O Scientific Portfolio é um spin-off da EDHEC Business School (EDHEC-Risk Institute) posicionado como plataforma acadêmica de **análise independente de portfólios de equity**. O produto atende institucionais (asset owners, consultants, fund selectors) que querem decompor exposições de risco, avaliar fundos sob framework fator + sustentabilidade, e rodar simulações/otimizações sob restrições.

O Netz Analysis Engine tem **um escopo mais amplo** (wealth management institucional multi-asset, não apenas equity) e **funcionalidades operacionais** que a SP não possui (due diligence report gerado por LLM, RAG sobre documentos de fundos, fund copilot, pipeline de ingestão multi-fonte, integração com catálogos regulatórios globais — SEC N-PORT/N-CEN/ADV, ESMA, 13F, Form 345). A SP tem profundidade acadêmica superior em três áreas específicas — (i) modelo de fator dinâmico via IPCA (Kelly-Pruitt-Su), (ii) stack climático completo, e (iii) Robust Sharpe + métricas de diversificação mais sofisticadas — mas **apenas (i) e (iii) são relevantes para o Netz**.

**Decisão de escopo explícita:** Climate Transition, Carbon Decomposition, Climate Alignment e ESG Screening multi-tier **estão fora do roadmap do Netz**. Não são atributos de análise financeira pura — são overlays de política/ideologia que reduzem o universo investível por critérios não-financeiros. O cliente UHNW offshore do Netz avalia retorno ajustado ao risco, liquidez, governança do gestor e alinhamento fiduciário — não pathway 1,5°C. Evitar o stack ESG/climate é **decisão de produto**, não lacuna técnica, e será explicitado nos materiais de marketing como princípio de neutralidade analítica.

**Veredito estratégico:** o Netz já cobre ~78% do framework quantitativo *relevante* da SP (excluindo por decisão as seções climate/ESG), excede em operacional/documental, e tem gaps materiais reais em **(a) fator dinâmico/IPCA, (b) Robust Sharpe + Effective Number of Bets, e (c) atribuição de performance resiliente à ausência de benchmark constituents pagos (Morningstar/Bloomberg).** Este último é o gap prático mais urgente.

---

## 2. Framework Scientific Portfolio

### 2.1 Posicionamento

SP se apresenta em três pilares:

- **Financial pillar** — investidores devem olhar além da alocação por ativo e examinar exposições sistemáticas a fatores, favorecendo fontes remuneradas de risco e controlando/diversificando as não remuneradas.
- **Sustainability pillar** — "do no harm" alinhado aos 17 UN SDGs, integrando ESG screening + climate transition de forma operacional.
- **Independência acadêmica** — metodologia aberta (Methodology Guide público), publicações com EDHEC.

### 2.2 Estrutura do Methodology Guide (16 seções)

Navegação extraída do Confluence público:

| # | Seção | Objeto metodológico principal |
|---|---|---|
| 1 | Risk Model | IPCA factor model + rotating PCA, 10+ fatores latentes condicionais |
| 2 | Risk Model Applications | Decomposição de risco (fator, setor, país), risk budgeting |
| 3 | Performance Attribution | Brinson-Fachler + atribuição por fator (não só por setor) |
| 4 | Climate Transition Factor | Fator sistemático de transição climática |
| 5 | Climate Transition Scenarios | NGFS / IEA scenario overlay |
| 6 | Conditional Transition Loss | Impacto operacional e de receita por cenário — aplicado a 1.287 companhias listadas |
| 7 | ESG Screening | 3 screens: consensus, comprehensive (com net zero), ambitious (UN SDGs negativos) |
| 8 | Carbon Emissions Decomposition | Scopes 1/2/3, atribuição de carbono por fator/setor |
| 9 | Extreme Risk | CVaR, EVT, tail dependency, extreme scenarios |
| 10 | Macro | Fator macro (inflação, crescimento, taxa, crédito) |
| 11 | Portfolio Allocation | Otimização com restrições + view blending |
| 12 | Simulations | Monte Carlo + bootstrap para distribuição de P&L |
| 13 | Robust Sharpe Ratio | Sharpe corrigido para não-normalidade + erro amostral |
| 14 | Diversification | Effective number of bets, diversification ratio, entropy |
| 15 | Climate Alignment | Implied temperature rise, pathway alignment |
| 16 | Appendix / Glossary | Notação e referências |

### 2.3 Diferenciadores quantitativos da SP

- **IPCA (Instrumented Principal Component Analysis)** — Kelly, Pruitt, Su (2019, *Journal of Financial Economics*). Ao contrário do PCA estático, o IPCA permite que as cargas fatoriais variem no tempo em função de características observáveis (instrumentos). Produz fatores latentes mais estáveis entre reestimações e requer apenas dados de preço + características, escalando para multi-região sem reestimação completa.
- **Conditional Transition Loss** — modelo híbrido forward-looking (cenário NGFS/IEA) + backward-looking (fator financeiro) que deriva perda esperada por companhia e agrega no portfólio. Perdas setoriais chegam a 10-60% em Utilities, com impacto agregado de 0,5-6% no portfólio.
- **Robust Sharpe** — correção para skewness/kurtosis (Cornish-Fisher) e erro amostral, evitando inflar skill em séries não-normais ou curtas.

---

## 3. Comparação chapter-by-chapter

### 3.1 Tabela-síntese de paridade

| # | Seção SP | Netz hoje | Paridade | Arquivo Netz |
|---|---|---|---|---|
| 1 | Risk Model (IPCA) | PCA estático + SVD, 8 fatores | **Parcial — 50%** | `quant_engine/factor_model_service.py` |
| 2 | Risk Model Applications | Decomposição por bloco, contribuição de risco | **60%** | `factor_model_pca.py` + scoring |
| 3 | Performance Attribution | Brinson-Fachler + Carino multi-período | **70% (gated em benchmark data)** | `vertical_engines/wealth/attribution/` |
| 4 | Climate Transition Factor | **Fora de escopo por decisão** | N/A | — |
| 5 | Climate Transition Scenarios | **Fora de escopo por decisão** (macro stress continua 80%) | N/A | `quant_engine/stress_severity_service.py` |
| 6 | Conditional Transition Loss | **Fora de escopo por decisão** | N/A | — |
| 7 | ESG Screening | **Fora de escopo por decisão** (mandate_fit mantém flags fiduciárias não-ESG) | N/A | `vertical_engines/wealth/mandate_fit/` |
| 8 | Carbon Decomposition | **Fora de escopo por decisão** | N/A | — |
| 9 | Extreme Risk (CVaR + EVT + tail dep) | CVaR histórico + paramétrico + Cornish-Fisher; sem EVT | **60%** | `cvar_service.py`, `tail_var_service.py` |
| 10 | Macro | Multi-signal (VIX/curve/CPI/spreads), regional, hysteresis | **80%** | `regime_service.py`, `regional_macro_service.py` |
| 11 | Portfolio Allocation | CLARABEL cascata 4 fases + SOCP robusto + BL + Ledoit-Wolf + GARCH + regime-conditioned cov | **100% — superior em alguns aspectos** | `quant_engine/optimizer_service.py`, `black_litterman_service.py` |
| 12 | Simulations | Block bootstrap 21-day + walk-forward backtest | **85%** | `monte_carlo_service.py`, `backtest_service.py` |
| 13 | Robust Sharpe | Sharpe tradicional apenas | **0%** | — |
| 14 | Diversification | Diversification ratio + absorption ratio (Marchenko-Pastur) | **60%** | `correlation_regime_service.py` |
| 15 | Climate Alignment | **Fora de escopo por decisão** | N/A | — |

**Paridade média ponderada considerando apenas as seções in-scope:** ~73%. As 6 seções climate/ESG são excluídas do cálculo por decisão de produto — Netz é plataforma de análise financeira neutra, não overlay de política climática.

### 3.2 Análise detalhada por capítulo

#### Capítulo 1-2 — Risk Model (IPCA vs PCA)

O Netz implementa PCA clássico em retornos residuais (após regressão contra 8 benchmarks) com SVD para extração de loadings. Isso captura estrutura estática de fatores, mas tem duas fraquezas:

1. Reestimação completa a cada rebalanceamento — fatores podem "pular" entre reestimações, gerando ruído na atribuição.
2. Cargas fatoriais são constantes no estimation window — não captam que a sensibilidade de um fundo a "growth" muda quando growth deixa de ser caro.

O IPCA da SP resolve ambas: as cargas são função de características observáveis (`β(x_it)`) que atualizam naturalmente. A literatura (Kelly et al. 2019) mostra que IPCA supera Fama-French, Barra, e PCA estático em out-of-sample R² e estabilidade.

**Implicação prática:** em uma carteira com rotação setorial, o PCA do Netz vai atribuir parte do retorno ao fator "residual idiossincrático" quando na verdade foi uma mudança de exposição fatorial — prejudicando qualidade de atribuição.

#### Capítulo 3 — Performance Attribution (GAP CRÍTICO)

O Netz tem Brinson-Fachler implementado com decomposição alocação/seleção/interação e linking multi-período via Carino. Limitação atual: **retorna vazio quando constituents do benchmark não estão disponíveis**. Pagar Bloomberg/Morningstar/MSCI por feed de composição de índice custa USD 30-100k/ano por provedor e cria dependência não-arquitetônica.

**Solução proposta — três vias não-dependentes de provedor pago, combinadas em cascata:**

**Via 1 — Returns-Based Style Analysis (Sharpe 1992).** Regressão restrita dos retornos do fundo contra um conjunto de índices de estilo (Russell 1000 Value, R1000 Growth, R2000, MSCI EAFE, Bloomberg Agg, etc.), com pesos ≥ 0 e soma = 1. Produz **weights implícitos por estilo** sem precisar de constituents. Inputs: apenas NAV do fundo (que Netz já tem via `nav_timeseries`) + retornos dos índices de estilo (Yahoo Finance via ETFs proxy — SPY, IWM, EFA, AGG). Zero dependência externa paga. Implementável em ~400 LOC com `scipy.optimize`.

**Via 2 — Holdings-Based Attribution via N-PORT.** Para `registered_us`, `etf`, `bdc`: o Netz já ingere holdings trimestrais via N-PORT (worker `nport_ingestion`, lock 900_018). Isso **é** a composição do portfólio. Brinson-Fachler roda direto sobre essas holdings, sem benchmark externo. Cobertura: ~4.800 fundos da universe.

**Via 3 — Benchmark Proxy via ETF Canonicamente Associado.** Quando o fundo declara benchmark em N-CEN (campo `primary_benchmark`) e é um índice padrão (S&P 500 → SPY, Russell 2000 → IWM, MSCI EAFE → EFA, Bloomberg US Agg → AGG, MSCI ACWI → ACWI), usamos as **holdings do ETF tracker mais líquido** como proxy da composição do benchmark. Essas holdings também vêm via N-PORT. Mapa canônico de 20-30 benchmarks cobre ~90% da universe registered.

**Arquitetura sugerida:**

```
vertical_engines/wealth/attribution/
  ├── service.py              ← orquestrador, roda cascata
  ├── returns_based.py        ← NOVO — Sharpe 1992 style analysis
  ├── holdings_based.py       ← NOVO — N-PORT direct
  ├── benchmark_proxy.py      ← NOVO — N-CEN → ETF canonical map
  ├── brinson_fachler.py      ← existente, alimentado por holdings_based + benchmark_proxy
  └── models.py
```

**Cascata de fallback:**

1. Se fundo tem N-PORT + benchmark mapeado → **Via 2 + Via 3** (holdings-based contra proxy). Confidence ALTA.
2. Se fundo tem N-PORT mas benchmark não mapeável → **Via 2 sozinho** (análise absoluta, não relativa). Confidence MÉDIA.
3. Se fundo não tem N-PORT (privados, UCITS sem holdings) → **Via 1** (returns-based style analysis). Confidence MÉDIA — inferência estatística, não observação direta.
4. Apenas se nenhuma rodar → retornar None com flag `data_unavailable`.

**Implicação:** fecha o gap sem contratar dados pagos, usando assets que Netz já ingere. Torna attribution **universal** — hoje ela quebra para fundos sem benchmark constituents; com essa cascata, roda em ≥95% da universe. E o SP não tem Via 3, só faz factor-based (que é equivalente da Via 1). É uma oportunidade de **superar a SP neste capítulo**, não apenas igualar.

#### Capítulos 4-8, 15 — Stack Climático e ESG (FORA DE ESCOPO POR DECISÃO)

O Netz **não implementará** Climate Transition Factor, Climate Scenarios, Conditional Transition Loss, ESG Screening multi-tier, Carbon Decomposition ou Climate Alignment. A decisão não é técnica — é de posicionamento de produto.

**Rationale:**

- Esses módulos não avaliam atributos de análise financeira pura. Carbon footprint, pathway 1,5°C e UN SDGs são critérios **normativos** (o que *deve* ser financiado) sobrepostos a instrumentos financeiros. O Netz se posiciona como plataforma de análise **neutra**: avalia risco, retorno, liquidez, governança, alinhamento fiduciário — não prescreve que setores da economia real o cliente deve privilegiar.
- O cliente UHNW offshore (core do Netz hoje via BTG Cayman) avalia fundos por mérito financeiro, não por rating ESG de terceiros. Adicionar overlays reduz universo investível por critérios que não são do próprio cliente.
- Evita dependência de dados caros e controversos (MSCI ESG, Sustainalytics, Trucost: USD 50-150k/ano cada) cuja metodologia é opaca e inconsistente entre provedores. Estudos acadêmicos mostram correlação baixa (~0,3-0,5) entre ratings ESG de provedores diferentes — não é sinal analítico estável.
- O `mandate_fit/constraint_evaluator.py` permanece como mecanismo de flags fiduciárias (e.g. "evitar derivativos alavancados", "liquidez mínima 30 dias", "sem concentração single-manager > 15%") — restrições que o próprio cliente ou mandato impõem, não overlays externos.

**Se um cliente europeu futuro exigir SFDR Article 8/9:** será tratado como integração opt-in com provedor terceiro (MSCI ou similar) via feature flag, sem incorporar a metodologia no core analítico do Netz. O Netz continuará sendo plataforma neutra; ESG será um adapter externo que o cliente contrata se quiser.

**Mensagem de marketing associada:** *"Netz analisa o que é mensurável financeiramente. Decisões de política — climate, ESG, temáticas — são do cliente, não da ferramenta."*

#### Capítulo 9 — Extreme Risk

O Netz tem CVaR histórico + paramétrico com ajuste Cornish-Fisher para caudas gordas. Não tem:

- EVT (Generalized Pareto Distribution para além do 5% / 1% quantil).
- Tail dependency modeling (copulas) — relevante para medir co-quedas em regime de crise.
- Monte Carlo CVaR com simulação de dependência não-linear.

A ausência de EVT é sentida quando o cliente pergunta "qual a perda esperada em um evento 1-em-50-anos?". CVaR histórico a 95% não responde; EVT responde.

#### Capítulo 10 — Macro

**Área onde o Netz está em paridade ou à frente.** O regime_service do Netz faz classificação multi-signal (VIX, yield curve, CPI, credit spreads) com hierarquia CRISIS > INFLATION > RISK_OFF > RISK_ON e hysteresis assimétrica (para evitar thrashing). Regional via ICE BofA spreads + GDP-weighted global override. A SP publica fator macro (inflação, crescimento, taxa, crédito) mas o framework do Netz de **classificação discreta de regime com histerese** é mais direto para trading/rebalance decisions.

#### Capítulo 11 — Portfolio Allocation

**O Netz supera a SP neste capítulo** em termos de engenharia:

- CLARABEL 4-fase cascade (max risk-adj return → robust SOCP → variance-capped → min-variance → heurístico).
- Fallback solver SCS em cada fase.
- Black-Litterman com IC views e flagging de inconsistência.
- Ledoit-Wolf shrinkage (toward constant-correlation target).
- Regime-conditioned covariance (curto window em stress, longo em normalidade).
- GARCH(1,1) condicional + incondicional.
- Turnover penalty via L1 slack.
- Stress testing parametrizado (GFC, COVID, Taper, Rate Shock).

O SP tem otimização robusta, mas a arquitetura de cascata + fallback do Netz é produção-grade (timeout 120s, construction_run_executor com lock 900_101, alert_sweeper).

#### Capítulo 12 — Simulations

Block bootstrap de 21 dias preserva autocorrelação — sólido. Walk-forward backtest existe. O que a SP tem e o Netz não:

- Cenários customizáveis pelo usuário (e.g. "rates +200bps + USD -10% + equity -20%").
- Monte Carlo com dependência não-gaussiana (copulas de Student-t ou Clayton).

#### Capítulo 13 — Robust Sharpe (AUSENTE)

Apenas Sharpe tradicional. Sem correções para:

- **Cornish-Fisher Sharpe** — penaliza skew negativa e excess kurtosis.
- **Opdyke (2007)** — intervalo de confiança para Sharpe sob não-normalidade.
- **Ledoit-Wolf corrected** — ajuste para amostras curtas.

Gap pequeno em esforço, grande em credibilidade acadêmica. Fundos hedge com série curta e caudas gordas têm Sharpe inflado quando calculado tradicionalmente — a SP expõe isso.

#### Capítulo 14 — Diversification

O Netz tem diversification ratio + absorption ratio (Marchenko-Pastur denoising) + eigenvalue concentration. Bom, mas não tem:

- **Effective Number of Bets (ENB)** — Meucci (2009), converte exposição fatorial em número efetivo de apostas independentes.
- **Entropy-based diversification** — Shannon entropy sobre pesos ou contribuições de risco.

ENB é especialmente útil para comunicação com comitê de investimento: "seu portfólio tem 40 fundos mas só 3 apostas efetivas".

---

## 4. Onde o Netz vai além da SP

Áreas onde o Netz oferece valor que a SP não oferece (porque tem escopo distinto):

### 4.1 Operacional / Documental

- **DD Report de 8 capítulos** gerado por LLM com evidence pack, confidence scoring, critic adversarial, circuit-breaker (`vertical_engines/wealth/dd_report/` + `critic/`).
- **Long-form DD report** com SSE streaming e Semaphore(2) para paralelismo controlado.
- **Fund Copilot RAG** — busca semântica sobre prospectos, brochures, DD chapters (wealth_vector_chunks, 12 sources, 16 embedding streams).
- **Macro Committee Engine** — gera relatórios regionais macro semanais automaticamente.
- **Flash Report** — event-driven market flash com cooldown 48h.
- **Investment Outlook** — narrativa macro trimestral via LLM.
- **Manager Spotlight** — análise deep-dive de um PM específico.
- **Fact Sheet PDF** — Executive e Institutional, PT/EN i18n.

A SP **não gera relatórios**. Ela mostra números na plataforma; o analista escreve o memo. O Netz produz o memo.

### 4.2 Catálogo regulatório global

- **SEC** — 13F, N-PORT, N-CEN, N-MFP, ADV (Parts 1 e 2), Form 345, NCSR XBRL, bulk DERA ZIPs.
- **ESMA** — Fund Register + ManCo.
- **Universe unificado** — 6 universos (registered, ETF, BDC, MMF, private, UCITS) em materialized view única (`mv_unified_funds`).
- **Strategy labels** — 37 estratégias granulares via 3-layer classifier.

A SP foca em equity listada. O Netz cobre listed + private + UCITS + MMF + BDC.

### 4.3 Multi-tenant operacional

- RLS PostgreSQL com `SET LOCAL` + ConfigService por tenant.
- Auth Clerk com RBAC (ADMIN/INVESTMENT_TEAM/investor).
- Data lake bronze/silver/gold com `{organization_id}/{vertical}/` prefix.
- Audit trail imutável com before/after JSONB snapshots.
- Stability guardrails (P1-P6: Bounded, Batched, Isolated, Lifecycle, Idempotent, Fault-Tolerant).

A SP é SaaS single-tenant-per-contract tradicional. O Netz foi desenhado multi-tenant desde o dia zero.

### 4.4 Credit vertical

Fora do escopo desta comparação, mas vale registrar: o Netz tem um vertical **credit** completo (IC memos, deal pipeline, underwriting artifact, sponsor engine, KYC, EDGAR, pipeline intelligence) que a SP nem tenta cobrir. SP é equity-only.

### 4.5 Quant-engine em produção

- Optimizer cascade com fallback solver (SCS) e timeout 120s.
- Momentum pré-computado globalmente (lock 900_071) — todos os tenants veem score sem reimportar fundo.
- Live price poll a 60s para carteiras live/paused com alertas de staleness.
- 3176+ testes passando, import-linter enforcement.

---

## 5. Gap analysis priorizado

### 5.1 Matriz Impacto × Esforço (apenas gaps in-scope)

| # | Gap | Impacto | Esforço | Prioridade |
|---|---|---|---|---|
| G1 | Robust Sharpe (Cornish-Fisher + Opdyke) | **Alto** (credibilidade) | **Baixo** (~200 LOC) | **P0** |
| G2 | Effective Number of Bets (Meucci 2009) | **Alto** (comunicação comitê) | **Baixo** (~150 LOC) | **P0** |
| G3 | **Attribution cascade (returns-based + N-PORT + benchmark proxy)** | **Muito alto** (destrava relatórios hoje travados) | **Médio-alto** (~1500 LOC total, 3 vias) | **P0** |
| G4 | EVT para extreme risk (GPD fitting) | Médio-alto | Médio (~600 LOC + tests) | **P1** |
| G5 | IPCA factor model (Kelly-Pruitt-Su) | **Alto** (diferencial acadêmico) | **Alto** (3-6 meses, paper reference) | **P1** |
| G6 | Copula-based tail dependency | Baixo-médio | Médio | **P2** |
| G7 | Entropy-based diversification | Baixo | Baixo | **P2** |

**Removidos do roadmap (decisão de produto):** Climate Transition stack, ESG Screening multi-tier, Carbon decomposition Scope 1/2/3, Climate Alignment. Ver seção 3.2 para rationale.

### 5.2 Recomendações de P0 (executar agora)

**G3 — Attribution cascade (prioridade máxima)**

É o único gap que já está **quebrando entregas atuais** (Brinson-Fachler retornando vazio). As outras P0 são upgrades de credibilidade; essa é correção de funcionalidade travada.

Plano de execução em 3 fases, cada uma entregável independentemente:

*Fase 1 — Returns-Based Style Analysis (2 semanas, ~400 LOC).* Novo módulo `attribution/returns_based.py`. Inputs: série NAV do fundo (de `nav_timeseries`) + série de retornos de um basket configurável de índices de estilo (proxied via ETFs SPY, IWM, EFA, EEM, AGG, HYG, LQD — todos já em `benchmark_nav`). Optimizer `scipy.optimize.minimize` com constraint `Σw=1, w≥0`. Output: vetor de pesos de estilo + R² + tracking error. Cobertura: 100% da universe que tem ≥ 36 meses de NAV.

*Fase 2 — Holdings-Based via N-PORT (3 semanas, ~600 LOC).* Novo módulo `attribution/holdings_based.py`. Lê `sec_nport_holdings` (já existe, preenchido pelo worker `nport_ingestion`). Agrega por setor/país/style usando classificação SEC. Computa contribuição de cada posição ao retorno total. Cobertura: ~4.800 fundos (registered_us + ETF + BDC).

*Fase 3 — Benchmark Proxy via N-CEN (1 semana, ~200 LOC + tabela de mapeamento).* Novo módulo `attribution/benchmark_proxy.py` + tabela `benchmark_etf_canonical_map` (seed data em `benchmark_etf_map.yaml`, 20-30 entradas: S&P 500 → SPY CIK/series, Russell 2000 → IWM, etc). Lê `primary_benchmark` de `sec_registered_funds` (campo N-CEN já ingerido), resolve para ETF tracker, puxa holdings via Fase 2. Completa o ciclo: `brinson_fachler.py` agora tem tanto portfolio holdings quanto benchmark holdings sem depender de Bloomberg.

Arquivos tocar:
- `vertical_engines/wealth/attribution/service.py` — orquestrador da cascata
- `vertical_engines/wealth/attribution/returns_based.py` — NOVO
- `vertical_engines/wealth/attribution/holdings_based.py` — NOVO
- `vertical_engines/wealth/attribution/benchmark_proxy.py` — NOVO
- `vertical_engines/wealth/attribution/brinson_fachler.py` — refatorar para aceitar holdings por ambos os lados
- `backend/alembic/versions/0132_benchmark_etf_canonical_map.py` — NOVO, tabela + seed
- DD Report capítulo 4 (Performance Analysis) — renderizar qualquer que a Via tenha rodado, com confidence badge

**G1 — Robust Sharpe**

Adicionar em `quant_engine/scoring_service.py` uma função `robust_sharpe(returns, rf_rate)` que retorne tripla `(traditional_sharpe, cornish_fisher_sharpe, opdyke_95_ci)`. Usar como componente adicional no scoring (`risk_adjusted_return` já tem peso 0,25; pode ser substituído pelo robust variant sem quebrar retrocompat, apenas com feature flag). Dependência: nenhuma nova biblioteca — scipy.stats já no stack.

**G2 — Effective Number of Bets**

Adicionar em `quant_engine/factor_model_service.py` (ou novo `diversification_service.py`) a função `effective_number_of_bets(weights, factor_loadings, factor_cov)` seguindo Meucci (2009). Surface no DD Report capítulo 5 (Risk Management Framework) e no dashboard do portfolio construction. Baixíssimo esforço, alto impacto comunicacional.

### 5.3 Recomendações de P1 (próximos 2 trimestres)

**G4 — EVT**

Implementar Peaks-Over-Threshold com GPD fitting (`scipy.stats.genpareto`). Expor em `cvar_service.py` como `extreme_var_evt(returns, quantile, threshold_method="mean_excess")`. Útil para tail risk reporting em eventos 1-em-50, 1-em-100 anos.

**G5 — IPCA factor model**

Este é o diferencial acadêmico da SP. Tem biblioteca open-source de referência: `github.com/bkelly-lab/ipca`. Plano:

1. Spike de 2 semanas para replicar resultados do paper em dados Netz (500 instrumentos liquid equity US).
2. Comparar R² out-of-sample contra PCA estático atual. Se > 15% melhoria, go.
3. Implementar como `factor_model_ipca_service.py` com mesma interface que `factor_model_service.py` atual, feature flag por tenant.
4. Benchmark de estabilidade em reestimações trimestrais.
5. Uma vez pronto, **quarta via** na cascata de attribution: factor-based attribution `return = Σ β_i · f_i + α`, usando IPCA como gerador dos fatores. Cobertura total da universe, independente de N-PORT ou benchmark mapeável.

---

## 6. Recomendações finais

### 6.1 Mensagem de marketing derivada

Em marketing materials e decks institucionais, o Netz pode se posicionar como:

> "Análise financeira institucional sem overlays políticos. Mesma profundidade quantitativa da Scientific Portfolio em otimização (CLARABEL cascade), regime (multi-signal com histerese) e extreme risk (CVaR + Cornish-Fisher), mais o que a SP não tem: DD reports gerados por LLM, catálogo regulatório global (SEC + ESMA + 13F), arquitetura multi-tenant institucional, e atribuição de performance que não depende de feeds pagos de composição de índice."

Três princípios declarativos:

1. **Neutralidade analítica** — avaliamos risco, retorno, liquidez e governança. Não prescrevemos alinhamento climático nem filtros ESG. Decisões normativas são do cliente.
2. **Independência de provedor** — infra de dados construída sobre fontes públicas reguladas (SEC, ESMA, FRED, Treasury, BIS, IMF). Atribuição, risk model e screening não param quando o contrato com Bloomberg vence.
3. **Profundidade acadêmica comprovada** — mesmos métodos publicados em journals (Black-Litterman, Ledoit-Wolf, GARCH, CVaR Cornish-Fisher, Brinson-Fachler, Meucci ENB, Cornish-Fisher Sharpe) implementados em produção com testes e guardrails.

### 6.2 Quick wins antes do próximo IC

Três entregas que mudam percepção de rigor sem esforço alto:

1. **Attribution cascade Fase 1 (returns-based)** — destrava DD Report capítulo 4 para 100% da universe imediatamente, sem custo de dados. Prioridade máxima.
2. **Robust Sharpe** no DD Report capítulo 4 (Performance Analysis) — uma linha: "Traditional Sharpe 1.42; Robust Sharpe (Cornish-Fisher) 1.18; 95% CI Opdyke [0.71, 1.65]." Imediato upgrade de credibilidade.
3. **Effective Number of Bets** no capítulo 5 (Risk Management) — "Carteira de 40 fundos equivale a 4.2 apostas efetivas — abaixo do target 6.0."

### 6.3 Longo prazo

O valor diferencial do Netz não está em **superar a SP em toda metodologia quantitativa** (ela é spin-off acadêmico da EDHEC, sempre terá 6-18 meses de vantagem em publicações específicas). Está em ser **a única plataforma que une análise quant rigorosa + geração de relatórios institucionais + catálogo regulatório global + arquitetura multi-tenant + neutralidade analítica (sem overlays políticos)**. A SP é ferramenta do analista; o Netz é o analista.

Manter foco em (a) fechar attribution cascade para destravar entregas, (b) quick wins de credibilidade (Robust Sharpe, ENB), (c) trilhar IPCA como diferencial de médio prazo, e (d) rejeitar explicitamente o stack climate/ESG como decisão de produto — transformando o que a SP trata como feature em **linha editorial do Netz**.

---

## 7. Referências

- Kelly, B., Pruitt, S., Su, Y. (2019). *Characteristics are covariances: A unified model of risk and return*. Journal of Financial Economics.
- Meucci, A. (2009). *Managing Diversification*. Risk Magazine.
- Opdyke, J. D. (2007). *Comparing Sharpe Ratios: So Where are the p-values?*. Journal of Asset Management.
- Cornish, E., Fisher, R. (1938). *Moments and cumulants in the specification of distributions*.
- Ledoit, O., Wolf, M. (2004). *Honey, I shrunk the sample covariance matrix*.
- EDHEC-Risk Institute. *Multi-Dimensional Risk and Performance Analysis for Equity Portfolios* (2016).
- NGFS Scenarios Portal — https://www.ngfs.net/ngfs-scenarios-portal/
- Scientific Portfolio Methodology Guide — https://scientific-portfolio.atlassian.net/wiki/spaces/MG/pages/25591816/Methodology+Guide (acesso Confluence, conteúdo público)
- Scientific Portfolio Knowledge Center — https://scientificportfolio.com/knowledge-center/