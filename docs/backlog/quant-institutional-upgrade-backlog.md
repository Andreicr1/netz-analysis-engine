# Backlog — Upgrade Quant Engine para Nível Institucional

## Objetivo

Elevar o quant engine de **B+/A- (wealth management mid-market)** para **A/A+ (multi-family office / gestora institucional)**, aproveitando infraestrutura existente que já cobre regime detection, correlation denoising, attribution, e drift monitoring.

## Inventário do que já existe

Antes de definir gaps, é crítico documentar o que já está implementado para evitar retrabalho:

| Feature | Arquivo | Status |
|---------|---------|--------|
| Cornish-Fisher CVaR | `quant_engine/optimizer_service.py:46` | ✅ Ativado com momentos reais (BL-1, 2026-03-27) |
| Marchenko-Pastur denoising | `quant_engine/correlation_regime_service.py` | Implementado |
| Ledoit-Wolf shrinkage | `quant_engine/correlation_regime_service.py` | ✅ Ativo no optimizer path (BL-2, 2026-03-27) |
| Absorption ratio (Kritzman) | `quant_engine/correlation_regime_service.py` | Implementado |
| Diversification ratio (Choueifaty) | `quant_engine/correlation_regime_service.py` | Implementado |
| Regime tilts BL-inspired | `quant_engine/allocation_proposal_service.py` | Implementado (regime → tilt map determinístico) |
| Markov HMM regime (2-state) | `app/domains/wealth/workers/regime_fit.py` | Implementado (log-VIX filtered) |
| Brinson-Fachler attribution | `quant_engine/attribution_service.py` | Implementado |
| Carino multi-period linking | `quant_engine/attribution_service.py` | Implementado |
| NSGA-II Pareto (Sharpe×CVaR×ESG) | `quant_engine/optimizer_service.py` | Implementado (pymoo) |
| DTW drift detection | `quant_engine/drift_service.py` | Implementado (batch) |
| Walk-forward backtesting | `quant_engine/backtest_service.py` | Implementado (TimeSeriesSplit) |
| TA-Lib momentum (RSI, BB, OBV) | `quant_engine/talib_momentum_service.py` | Implementado |
| Stress severity scoring | `quant_engine/stress_severity_service.py` | Implementado |
| Manager score composite (8 fatores) | `quant_engine/scoring_service.py` | Implementado |

---

## Backlog de Implementações

### Prioridade 1 — Quick Wins (leverage direto da infra existente)

---

#### BL-1: Ativar Cornish-Fisher com momentos reais — ✅ CONCLUÍDO 2026-03-27

**Problema:** `parametric_cvar_cf()` recebe `skew=zeros, kurt=zeros` no optimizer, anulando o ajuste fat-tail que já está implementado.

**Solução:** Computar skewness e excess kurtosis dos retornos reais dos fundos em `compute_fund_level_inputs()` e passá-los ao optimizer.

**Escopo:**
- Adicionar cálculo de `scipy.stats.skew()` e `scipy.stats.kurtosis(fisher=True)` no `compute_fund_level_inputs()`
- Retornar `(annual_cov, expected_returns, ordered_ids, skewness, excess_kurtosis)`
- Propagar para `optimize_fund_portfolio()` → `_compute_cvar()`
- Propagar para NSGA-II `PortfolioProblem.__init__()`

**Arquivos:**
- `app/domains/wealth/services/quant_queries.py` — computar momentos
- `quant_engine/optimizer_service.py` — consumir momentos reais
- `app/domains/wealth/routes/model_portfolios.py` — passar novos params

**Impacto:** CVaR mais preciso para portfolios equity-heavy com fat tails. Zero dependência nova.

**Estimativa:** P (pequeno)

---

#### BL-2: Integrar Ledoit-Wolf shrinkage no optimizer — ✅ CONCLUÍDO 2026-03-27

**Problema:** `compute_fund_level_inputs()` usa covariância amostral pura (`np.cov`). Ledoit-Wolf já existe em `correlation_regime_service.py` mas não é usado no path de otimização.

**Solução:** Aplicar shrinkage à covariância antes de passar ao CLARABEL.

**Escopo:**
- Extrair a lógica de shrinkage de `correlation_regime_service.py` para um helper compartilhado (ou importar diretamente)
- Aplicar em `compute_fund_level_inputs()` após `np.cov`, antes da anualização
- Configurável via `calibration.yaml` (`optimizer.apply_shrinkage: true`)

**Arquivos:**
- `app/domains/wealth/services/quant_queries.py` — aplicar shrinkage
- `quant_engine/correlation_regime_service.py` — extrair helper
- `calibration/seeds/liquid_funds/calibration.yaml` — config flag

**Impacto:** Covariância mais estável, especialmente com N>10 fundos. Reduz sensibilidade a outliers.

**Estimativa:** P

---

#### BL-3: Filtrar return_type em compute_fund_level_inputs — ✅ CONCLUÍDO 2026-03-27

**Problema:** `compute_fund_level_inputs()` não filtra por `return_type` (log vs arithmetic), enquanto `risk_calc.py` distingue. Misturar tipos contamina a covariância.

**Solução:** Replicar a lógica de `_batch_resolve_return_types()` do risk_calc no compute_fund_level_inputs.

**Escopo:**
- Adicionar filtro `NavTimeseries.return_type == resolved_type` na query
- Preferir log returns (mais correto para covariância)
- Log warning se fundo tem apenas arithmetic

**Arquivos:**
- `app/domains/wealth/services/quant_queries.py`

**Impacto:** Correção de consistência. Evita erros silenciosos.

**Estimativa:** P

---

### Prioridade 2 — Elevações Estruturais (novo código, alta alavancagem)

---

#### BL-4: Black-Litterman completo com views do IC — ✅ CONCLUÍDO 2026-03-27 — ✅ CONCLUÍDO 2026-03-27

**Problema:** O sistema tem regime tilts "BL-inspired" (`allocation_proposal_service.py`) que aplica multiplicadores determinísticos por regime. Mas não implementa o framework BL real: market-implied returns + views com incerteza + posterior bayesiano.

**Solução:** Implementar Black-Litterman como alternativa ao `daily_mean × 252` para expected returns.

**Escopo:**
- Novo service: `quant_engine/black_litterman_service.py`
- **Market-implied returns (π):** resolver retornos de equilíbrio via reverse optimization: `π = λΣw_mkt` onde `w_mkt` = pesos do benchmark ou strategic allocation
- **Views matrix (P, Q, Ω):** IC pode expressar views relativas ou absolutas via API (e.g., "OAKMX supera DODGX em 2% com 60% confiança")
- **Posterior:** `μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ × [(τΣ)⁻¹π + PᵀΩ⁻¹Q]`
- **Fallback:** se IC não definiu views, usar π (market-implied) em vez de média histórica
- Integrar como opção em `compute_fund_level_inputs()` ou como step anterior ao optimizer
- Expor endpoint `POST /api/v1/model-portfolios/{id}/views` para IC definir views

**Arquivos (novos):**
- `quant_engine/black_litterman_service.py`
- `app/domains/wealth/routes/portfolio_views.py`
- `app/domains/wealth/models/portfolio_view.py` (tabela para persistir views do IC)
- `app/domains/wealth/schemas/portfolio_view.py`

**Arquivos (modificados):**
- `app/domains/wealth/routes/model_portfolios.py` — opção BL nos expected returns
- `app/domains/wealth/services/quant_queries.py` — flag `use_bl_returns`

**Fronteiras SOLID (ref: institutional-portfolio-lifecycle-reference.md, Apêndice B):**
- NAV access via `nav_reader.py` — nunca importar `NavTimeseries` diretamente
- Views são org-scoped (RLS), market-implied returns usam `strategic_allocation` targets como proxy de w_mkt
- Novo service em `quant_engine/` deve ser pure sync, sem I/O, config como parâmetro

**Impacto:** Transformacional. Expected returns de média histórica são o elo mais fraco do sistema. BL permite o IC expressar convicções de investimento de forma estatisticamente rigorosa.

**Estimativa:** M (médio)

---

#### BL-5: Covariância regime-dependente — ✅ CONCLUÍDO 2026-03-27 — ✅ CONCLUÍDO 2026-03-27

**Problema:** O optimizer usa uma única covariância (sample, últimos 252 dias). Mas correlações mudam significativamente entre regimes — em crise, correlações sobem (contágio). O sistema já tem regime detection (Markov HMM) e correlation regime analysis, mas não usa regime para condicionar a otimização.

**Solução:** Computar covariância condicional ao regime atual e usar na otimização.

**Escopo:**
- Buscar regime corrente do `regime_fit` worker (HMM state)
- Particionar retornos históricos por regime (usar probabilidades filtradas do HMM)
- Computar covariância ponderada: `Σ_regime = Σ(p_regime_t × r_t × r_tᵀ)` onde `p_regime_t` é a probabilidade do regime no dia t
- Alternativa mais simples: usar janela adaptativa — janela curta (63d) em regime de crise, longa (252d) em risk-on
- Integrar como opção no optimizer path

**Arquivos:**
- `app/domains/wealth/services/quant_queries.py` — covariância condicional
- `quant_engine/optimizer_service.py` — aceitar regime como param
- `app/domains/wealth/routes/model_portfolios.py` — buscar regime corrente

**Impacto:** Alocação mais defensiva automaticamente em crise. Evita que covariância de período calm sub-estime correlações em stress.

**Estimativa:** M

---

#### BL-6: Transaction cost modeling no rebalanceamento — ✅ CONCLUÍDO 2026-03-27

**Problema:** O optimizer ignora custos de transação. Quando roda construct novamente (rebalanceamento), pode gerar trades de 0.1% de peso que custam mais em spread/comissão do que o ganho de otimalidade.

**Solução:** Adicionar penalty de turnover ao objetivo do optimizer e implementar dead-band (minimum trade size).

**Escopo:**
- Aceitar `current_weights` opcionais no `optimize_fund_portfolio()`
- Adicionar termo de penalidade: `maximize μᵀw − λwᵀΣw − κ‖w − w_current‖₁` onde κ = custo proporcional por unidade de turnover
- Dead-band: não rebalancear fundo se |Δw| < threshold (e.g., 0.5%)
- Configurável via `calibration.yaml`: `rebalance.turnover_penalty`, `rebalance.dead_band_pct`
- Integrar com `vertical_engines/wealth/rebalancing/service.py` que já tem infraestrutura de WeightProposal e RebalanceImpact

**Arquivos:**
- `quant_engine/optimizer_service.py` — termo de turnover
- `calibration/seeds/liquid_funds/calibration.yaml` — params
- `vertical_engines/wealth/rebalancing/service.py` — dead-band filter

**Impacto:** Reduz turnover desnecessário. Importante para fundos com custos de transação significativos (EM, small-cap, alternatives).

**Estimativa:** M

---

### Prioridade 3 — Diferenciais Competitivos (complexidade alta, impacto estratégico)

---

#### BL-7: Factor model decomposition (PCA-based) — ✅ CONCLUÍDO 2026-03-27

**Problema:** Não há decomposição de fatores para entender a que o portfolio está exposto (value, growth, momentum, size, quality). O scoring_service.py calcula métricas individuais, mas não há um factor model integrado.

**Solução:** Implementar PCA-based statistical factor model como camada analítica.

**Escopo:**
- Novo service: `quant_engine/factor_model_service.py`
- **Step 1:** PCA na matriz de retornos cross-sectional → extrair k fatores estatísticos
- **Step 2:** Interpretar fatores via correlação com proxy series (VIX, credit spread, yield curve, momentum index)
- **Step 3:** Decompor retorno do portfolio em contribuição de fatores: `R_p = Σ(β_k × F_k) + ε`
- **Step 4:** Reportar factor exposures no DD report e no construct response
- Não usar Fama-French diretamente (requer dados de fatores que não temos). PCA é self-contained.

**Arquivos (novos):**
- `quant_engine/factor_model_service.py`

**Arquivos (modificados):**
- `vertical_engines/wealth/dd_report/` — capítulo de factor exposure
- Response do construct — adicionar `factor_exposures` ao optimization meta

**Impacto:** IC pode ver se o portfolio está concentrado em um fator. Diferencial para relatórios institucionais.

**Estimativa:** G (grande)

---

#### BL-8: Robust optimization (uncertainty sets) — ✅ CONCLUÍDO 2026-03-27

**Problema:** Mean-variance assume que os inputs (μ, Σ) são conhecidos com certeza. Na prática, expected returns têm erro de estimação alto. A solução ótima pode ser instável.

**Solução:** Implementar robust counterpart com uncertainty sets para expected returns.

**Escopo:**
- Novo service ou extensão do optimizer
- **Box uncertainty:** `μ ∈ [μ̂ − δ, μ̂ + δ]` onde δ = f(estimation error)
- **Ellipsoidal uncertainty:** `(μ − μ̂)ᵀΣ⁻¹(μ − μ̂) ≤ κ²`
- Reformulação SOCP (second-order cone): o worst-case é convexo e resolve com CLARABEL
- `maximize min_{μ ∈ U} μᵀw − λwᵀΣw` ↔ `maximize μ̂ᵀw − κ√(wᵀΣw) − λwᵀΣw`
- Implementar como Phase alternativa no cascade (antes do min-variance fallback)
- Configurável: `optimizer.robust: true`, `optimizer.uncertainty_level: 0.5`

**Arquivos:**
- `quant_engine/optimizer_service.py` — Phase 1.5 robust
- `calibration/seeds/liquid_funds/calibration.yaml` — params

**Impacto:** Portfolio mais estável entre rebalanceamentos. Menos sensível a outliers nos retornos históricos.

**Estimativa:** M

---

#### BL-9: Expected Shortfall condicional (regime-aware CVaR) — ✅ CONCLUÍDO 2026-03-27

**Problema:** CVaR é computado com distribuição incondicional (todos os retornos igualmente ponderados). Em crise, o CVaR condicional é muito pior do que o incondicional.

**Solução:** Computar CVaR condicional ao regime e usar como constraint mais conservador durante regimes de stress.

**Escopo:**
- Quando regime = RISK_OFF ou CRISIS, usar subset de retornos desse regime para computar CVaR empírico
- Alternativamente, ponderar retornos recentes (EWMA decay) para dar mais peso a dados recentes de stress
- Usar CVaR condicional como `cvar_limit` mais apertado em regimes adversos (e.g., limit × 0.7 em CRISIS)
- Integrar com regime_service.py e portfolio_eval.py

**Arquivos:**
- `quant_engine/cvar_service.py` — CVaR regime-conditional
- `app/domains/wealth/workers/portfolio_eval.py` — usar CVaR condicional
- `calibration/seeds/liquid_funds/calibration.yaml` — regime multipliers

**Impacto:** Protege melhor contra tail events durante crises. Alinhado com regulação de stress testing (ESMA, SEC).

**Estimativa:** M

---

#### BL-10: Stress testing paramétrico (cenários do IC) — ✅ CONCLUÍDO 2026-03-27

**Problema:** `stress_scenarios.py` existe no model_portfolio package mas é básico. Gestoras institucionais precisam de cenários paramétricos definidos pelo IC (e.g., "Fed sobe 200bps: equity -15%, bonds +3%").

**Solução:** Permitir IC definir cenários como shocks nos fatores, e propagar via sensibilidade do portfolio.

**Escopo:**
- Novo endpoint: `POST /api/v1/model-portfolios/{id}/stress-test`
- Body: `{"scenario_name": "Rate Shock +200bps", "shocks": {"equity": -0.15, "fi_treasury": 0.03, "alt_gold": 0.05}}`
- Computar impacto no NAV: `ΔP = Σ(w_block × shock_block)`
- Computar impacto no CVaR: re-computar com retornos stressed
- Persistir resultado para relatórios
- Cenários pré-definidos (2008, COVID, Taper Tantrum) como templates

**Arquivos (novos):**
- `app/domains/wealth/routes/stress_test.py`
- `vertical_engines/wealth/model_portfolio/stress_scenarios.py` — expandir

**Impacto:** Requisito regulatório para gestoras. Diferencial em relatórios para investidores institucionais.

**Estimativa:** M

---

### Prioridade 4 — Horizonte Longo (quando scale justificar)

---

#### BL-11: GARCH(1,1) para volatilidade condicional — ✅ CONCLUÍDO 2026-03-27

**Problema:** Volatilidade é tratada como constante (sample std). Na realidade, volatilidade é time-varying e clusteriza (GARCH effect).

**Solução:** Ajustar GARCH(1,1) por fundo e usar a volatilidade condicional forward-looking.

**Escopo:**
- Novo service: `quant_engine/garch_service.py`
- Usar `arch` library (Python): `am = arch_model(returns, vol='GARCH', p=1, q=1)`
- Computar σ²_{t+1|t} = ω + α·ε²_t + β·σ²_t
- Substituir `volatility_1y` no `fund_risk_metrics` pelo forecast GARCH
- Usar covariância DCC-GARCH para otimização (Engle 2002)

**Impacto:** Previsão de risco mais responsiva a clusters de volatilidade.

**Estimativa:** G — DCC-GARCH é computacionalmente caro para N>20

---

#### BL-12: Tail dependence modeling (copulas)

**Problema:** Covariância assume dependência linear (Gaussiana). Em crises, a dependência na cauda é muito maior (tail dependence). Copulas modelam isso.

**Solução:** Ajustar Student-t copula aos retornos e usar para simulação de stress.

**Escopo:**
- Ajustar t-copula: graus de liberdade (ν) e correlation matrix
- Simular N cenários multivariados com tail dependence
- Computar CVaR via simulação Monte Carlo com copula
- Comparar com CVaR parametrizado para calibrar confiança

**Impacto:** Modelo de risco mais realista para portfolios diversificados em crises.

**Estimativa:** G — pesquisa intensa, alto custo computacional

---

#### BL-13: Multi-period optimization (dynamic programming)

**Problema:** O optimizer resolve um único período. Não considera que rebalanceamento futuro é possível, nem path dependency do NAV.

**Solução:** Implementar otimização multi-período via programação dinâmica ou model predictive control (MPC).

**Impacto:** Ótimo para mandatos com horizonte definido (e.g., target-date). Over-engineering para wealth management genérico.

**Estimativa:** XG — pesquisa acadêmica, complexidade alta, benefício marginal para o caso de uso

---

## Roadmap Sugerido

```
Sprint 1 (Quick Wins)          Sprint 2 (Estrutural)          Sprint 3 (Diferencial)
─────────────────────          ────────────────────           ────────────────────
BL-1: CF com momentos reais    BL-4: Black-Litterman         BL-7: Factor model (PCA)
BL-2: Shrinkage no optimizer   BL-5: Cov regime-dependente   BL-8: Robust optimization
BL-3: Filtrar return_type      BL-6: Transaction costs       BL-9: CVaR regime-aware
                                                              BL-10: Stress testing IC

                               Sprint 4 (Horizonte longo)
                               ────────────────────────
                               BL-11: GARCH
                               BL-12: Copulas
                               BL-13: Multi-period
```

### Estimativas de Tamanho

| Tamanho | Significado | Items |
|---------|-------------|-------|
| **P** (pequeno) | 1-2 arquivos, <100 linhas novo código | BL-1, BL-2, BL-3 |
| **M** (médio) | 3-5 arquivos, 200-500 linhas, novo service | BL-4, BL-5, BL-6, BL-8, BL-9, BL-10 |
| **G** (grande) | Novo vertical package, pesquisa necessária | BL-7, BL-11, BL-12 |
| **XG** (extra grande) | Pesquisa acadêmica, POC antes de implementar | BL-13 |

### Critério de "Par" com Institucional

Para atingir paridade com multi-family office / gestora institucional, os itens **obrigatórios** são:

| Item | Razão |
|------|-------|
| **BL-1** | Cornish-Fisher sem momentos reais é desperdício da infra existente |
| **BL-2** | Shrinkage é standard em qualquer optimizer institucional |
| **BL-3** | Consistência de dados é pré-requisito, não feature |
| **BL-4** | Expected returns de média histórica é o gap mais crítico vs institucional |
| **BL-6** | Ignorar transaction costs gera turnover que destrói valor |
| **BL-10** | Stress testing paramétrico é requisito regulatório |

Os itens BL-5, BL-7, BL-8, BL-9 são **diferenciais** que posicionam acima da paridade.
Os itens BL-11, BL-12, BL-13 são **overkill** para o estágio atual — implementar apenas se scale ou requisito regulatório justificar.

---

## Reavaliação Pós-Implementação — Sprints 1–3 concluídos em 2026-03-27

Após implementar Sprint 1 + Sprint 2, o sistema estaria em:

| Feature | Antes | Depois |
|---------|-------|--------|
| Expected returns | Média histórica (ruidoso) | ✅ Black-Litterman com views do IC |
| Covariância | Sample (ruidosa) | ✅ Ledoit-Wolf shrinkage + regime-conditioned |
| CVaR | Normal (ignora fat tails) | ✅ Cornish-Fisher com momentos reais + regime-aware |
| Regime awareness | Tilts pós-otimização | ✅ Covariância, CVaR e limite condicionais ao regime |
| Rebalanceamento | Sem custos | ✅ Turnover penalty + dead-band |
| Stress testing | Básico | ✅ Cenários paramétricos do IC (GFC, COVID, Taper, Rate Shock) |
| Volatilidade | Amostral (constante) | ✅ GARCH(1,1) condicional com fallback |
| Otimização | Mean-variance | ✅ Robust (ellipsoidal SOCP) + Phase cascade |
| Factor exposure | Ausente | ✅ PCA-based decomposition com macro proxy labelling |

**Classificação pós-upgrade: A / A+** — on-par com gestoras institucionais mid-tier. Acima de qualquer robo-advisor e da maioria das wealth platforms SaaS.

**Testes:** 2858 → 2905 passing (+47 testes de cobertura quant).
**Sprints concluídos:** 1 (BL-1,2,3) ✅ | 2 (BL-4,5,6) ✅ | 3 (BL-7,8,9,10,11) ✅
**Pendentes:** BL-12 (copulas — aguarda validação empírica pós-BL-1) | BL-13 (multi-period — aguarda decisão de produto)
