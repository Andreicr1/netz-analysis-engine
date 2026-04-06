# Risk Methodology v3 — Netz Analysis Engine

> Authoritative reference for the quantitative risk framework.
> Version 3: Multi-factor stress scoring with real-economy integration.
> Last updated: 2026-04-06.

---

## 1. Regime de Mercado (Multi-Factor Stress Scoring)

### 1.1 Filosofia

O modelo classifica o regime de mercado combinando sinais financeiros de alta frequência com indicadores de economia real. Isto evita o viés monetário de modelos puramente financeiros, que são cegos a choques de oferta (petróleo, commodities) e contrações de produção até que estes contaminem VIX e credit spreads — tipicamente semanas depois.

### 1.2 Cinco Quadrantes de Destruição de Capital

O motor é desenhado para cobrir os 5 principais vectores de risco sem pontos cegos:

| Quadrante | Sinal Primário | Sinal Secundário |
|---|---|---|
| **Crise de Liquidez** | DXY Z-score (dollar crunch) | VIX |
| **Crise de Crédito** | HY OAS, BAA-10Y | Yield Curve |
| **Crise de Crescimento / Recessão** | CFNAI, Sahm Rule | Yield Curve |
| **Choque de Oferta** | Energy Shock Composite | CPI override |
| **Estagflação Estrutural** | CPI YoY override (≥4%) | CFNAI + Energy |

### 1.3 Arquitectura de Sinais

```
                    ┌─────────────────────────────────┐
                    │     CPI YoY ≥ 4.0% ?            │
                    │   SIM → INFLATION (override)     │
                    │   NÃO → composite stress scoring │
                    └───────────────┬─────────────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        │                                                       │
   FAST SIGNALS (55%)                                 SLOW SIGNALS (45%)
   Reagem em dias                                     Estruturais, semanas-meses
        │                                                       │
   ┌────┴────┐                                         ┌────────┴────────┐
   │ VIX 20% │  HY OAS 15%  Energy 10%  DXY 10%       │ CFNAI 15%      │
   └─────────┘                                         │ Yield Curve 10% │
                                                       │ BAA 5%          │
                                                       │ FF RoC 5%       │
                                                       │ Sahm 5%         │
                                                       │ (Reserved 5%)   │
                                                       └─────────────────┘
                                    │
                            Composite Score (0-100)
                                    │
                    ┌───────────────┴───────────────┐
                    │ < 25 → RISK_ON                │
                    │ 25-49 → RISK_OFF              │
                    │ ≥ 50 → CRISIS                 │
                    └───────────────────────────────┘
```

### 1.4 Tabela de Sinais

#### Fast Signals (55%) — reagem em dias

| Sinal | Peso | Calma (0) | Pânico (100) | Fonte FRED | Frequência |
|---|---|---|---|---|---|
| VIX | 20% | 18.0 | 35.0 | VIXCLS | Diária |
| US HY OAS | 15% | 2.5% | 6.0% | BAMLH0A0HYM2 | Diária |
| Energy Shock Composite | 10% | 0 | 100 | DCOILWTICO (derivado) | Diária |
| DXY Z-score | 10% | 0.0σ | +2.0σ | DTWEXBGS (derivado) | Diária |

#### Slow Signals (45%) — estruturais, semanas a meses

| Sinal | Peso | Calma (0) | Pânico (100) | Fonte FRED | Frequência |
|---|---|---|---|---|---|
| CFNAI | 15% | +0.20 | -0.70 | CFNAI | Mensal |
| Yield Curve 10Y-2Y | 10% | +1.0% | -0.5% | Derivado DGS10-DGS2 | Diária |
| BAA-10Y Spread | 5% | 1.2% | 2.5% | BAA10Y | Diária |
| Fed Funds Δ6m | 5% | -0.50% | +1.50% | DFF (derivado) | Diária |
| Sahm Rule | 5% | 0.00 | 0.50 | SAHMREALTIME | Mensal |
| *Reservado* | *5%* | — | — | *Baltic Dry, soft commodities* | — |

### 1.5 Energy Shock Composite

Funde dois sinais de petróleo num único indicador para evitar multicolinearidade:

```
energy_shock = max(
    ramp(WTI_z_score, calm=0.5, panic=3.0),    # magnitude do desvio
    ramp(WTI_roc_3m,  calm=0.0, panic=50.0),   # velocidade do choque
)
```

**Justificação:** Durante um choque de oferta agudo, WTI Z-score e WTI RoC 3m têm correlação ~1.0. Pesos separados (ex: 10% cada) entregariam 20% do poder de decisão a um único ativo. O `max()` captura whichever tail is louder — a magnitude (Z-score) para choques graduais, a velocidade (RoC) para spikes súbitos.

### 1.6 Fed Funds: Rate-of-Change, Não Nível Absoluto

O nível absoluto da taxa de juros não dita crise. Um Fed Funds de 4.5% num cenário de alto crescimento é neutro. O que causa stress é a **surpresa** e a **velocidade do aperto**.

```
FF_stress = ramp(DFF_now - DFF_6_months_ago, calm=-0.50%, panic=+1.50%)
```

- Δ6m positivo = hiking rápido → stress
- Δ6m negativo = cortando → dovish, calm
- Evita viés estrutural em regimes de taxa alta

### 1.7 DXY Z-score: Dollar Stress

Trade-Weighted Dollar Index vs média rolling de 1 ano. Captura crises de liquidez global em USD:

```
DXY_stress = ramp(DXY_zscore, calm=0.0σ, panic=+2.0σ)
```

Historicamente, subidas parabólicas do dólar precedem ou acompanham crises agudas (2008, 2020 Mar, 2022 Sep).

### 1.8 CFNAI: Substitui INDPRO

O Chicago Fed National Activity Index é um composite de **85 indicadores** (produção, emprego, consumo, vendas, inventários). Vantagens sobre INDPRO:

- Sem revisões retroactivas significativas (INDPRO é revisto por 2+ meses)
- Threshold calibrado pelo NBER: abaixo de -0.70 = alta probabilidade de recessão
- Mensal, mas integra dezenas de indicadores de alta frequência

### 1.9 Override de Inflação (CPI YoY ≥ 4.0%)

**Regra incondicional mantida permanentemente.** Justificações:

1. **Paradoxo do VIX (Complacência Inicial):** Nos estágios iniciais de inflação broad-based, empresas repassam preços, lucros nominais sobem, mercados fazem novas máximas. VIX colapsa, spreads apertam — o modelo multifatorial gritaria RISK_ON. O override corta este sinal ruidoso: "O mercado está calmo, mas o capital real está sendo destruído."

2. **Aderência de Serviços e Housing:** Shelter = ~33% do CPI. Supercore é impulsionado por salários e crédito, não petróleo. O Energy Shock é de alta frequência e alta volatilidade; a inflação de serviços é pesada, inercial e de baixa frequência. O modelo não pode depender do WTI para prever rigidez salarial.

3. **Falsa Sensação de Segurança:** Se o petróleo desaba ($120→$70), os sinais Fast aliviam o score. Sem o override, o motor voltaria a RISK_ON. Mas se CPI roda a 5% por injeções fiscais ou repasses atrasados, a política monetária continua restritiva. O override impede compra prematura de duration longa (Tech/Growth).

**O override é ortogonal ao Energy Shock** — cobre estagflação demand-driven (excesso fiscal, credit boom, espiral salarial) que nenhum choque de commodity pode capturar.

### 1.10 Normalização e Sinais Ausentes

- Se nem todos os sinais estão disponíveis, o score é escalado proporcionalmente ao peso dos sinais presentes
- Mínimo 2 sinais para classificação confiante; abaixo disso assume RISK_OFF conservador
- Staleness: séries diárias aceites até 5 dias (weekends + feriados), mensais até 45-75 dias dependendo da série

---

## 2. Fund Risk Metrics (Global, Pre-Computed)

Tabela `fund_risk_metrics` — **global** (sem RLS, `organization_id = NULL`), computada pelo worker `global_risk_metrics` (lock 900_071) para todos os instrumentos activos em `instruments_universe`. Todos os tenants vêem os mesmos scores sem importar fundos.

### 2.1 Métricas por Janela Temporal

| Métrica | Janelas | Fórmula |
|---|---|---|
| CVaR (95%) | 1m, 3m, 6m, 12m | Expected Shortfall: média dos retornos abaixo do percentil 5 |
| VaR (95%) | 1m, 3m, 6m, 12m | Percentil 5 da distribuição de retornos |
| Return | 1m, 3m, 6m, 1y, 3y ann | Retorno cumulativo / anualizado |
| Volatility | 1y | Desvio padrão anualizado (×√252) |
| Max Drawdown | 1y, 3y | Maior pico-to-trough na janela |
| Sharpe | 1y, 3y | (Return - Rf) / Volatility |
| Sortino | 1y | (Return - Rf) / Downside Deviation |
| Alpha | 1y | Retorno acima do benchmark (regressão OLS) |
| Beta | 1y | Sensibilidade ao benchmark |
| Information Ratio | 1y | Alpha / Tracking Error |
| Tracking Error | 1y | Volatility do excess return vs benchmark |

Risk-free rate: FRED DFF (Federal Funds Rate diário).

---

## 3. Volatilidade Condicional (GARCH + EWMA Fallback)

### 3.1 Primário: GARCH(1,1)

$$\sigma^2_t = \omega + \alpha \cdot \epsilon^2_{t-1} + \beta \cdot \sigma^2_{t-1}$$

- Mínimo 100 observações
- Converge para ~80-85% dos fundos
- Captura volatility clustering (choques persistentes)

### 3.2 Fallback: EWMA (RiskMetrics, λ=0.94)

$$\sigma^2_t = \lambda \cdot \sigma^2_{t-1} + (1-\lambda) \cdot r^2_{t-1}$$

- λ=0.94 é o standard J.P. Morgan RiskMetrics para dados diários
- Sem convergência iterativa (não depende de MLE)
- **Preserva volatility clustering** — o desvio padrão estático perde esta propriedade
- Evita misturar metodologias no dashboard (condicional vs estática)
- **Cobertura: 100%** (5,367/5,367 instrumentos)

**Justificação da mudança:** O fallback anterior era `volatility_1y` (desvio padrão estático de 252 dias). Isto criava inconsistência metodológica: no mesmo dashboard, alguns fundos mostravam volatilidade condicional (GARCH, reactiva a choques recentes) e outros mostravam volatilidade suavizada (estática, média de 1 ano). EWMA preserva a reactividade sem exigir convergência.

---

## 4. Momentum Signals

| Sinal | Fórmula | Coluna |
|---|---|---|
| RSI(14) | Relative Strength Index, 14 períodos | `rsi_14` |
| Bollinger Position | (Price - BB_lower) / (BB_upper - BB_lower) | `bb_position` |
| NAV Momentum | Composite de RSI + Bollinger (0-100) | `nav_momentum_score` |
| Flow Momentum | Variação de AUM vs NAV (proxy de fluxos, EMA-filtered) | `flow_momentum_score` |
| Blended Momentum | 50% NAV + 50% Flow | `blended_momentum_score` |

### 4.1 Flow Momentum: Low-Pass Filter (EMA 63 dias)

O proxy AUM-minus-NAV é ruidoso — distribuições de dividendos, splits, fusões e taxas de performance geram falsos alertas. A série de AUM é suavizada com EMA de 63 dias (~3 meses) antes do cálculo do slope.

**Peso reduzido para 5%** no scoring (era 10%). O proxy de fluxo é inerentemente impreciso sem dados de Net Flows limpos. Peso redistribuído para Risk Adjusted Return (componente mais robusto).

---

## 5. Fund Scoring (Composite 0-100)

### 5.1 Componentes e Pesos

| Componente | Peso | Normalização |
|---|---|---|
| Risk Adjusted Return | **30%** | sharpe_1y normalizado [-1.0, +3.0] → [0, 100] |
| Return Consistency | 20% | return_1y normalizado [-20%, +40%] → [0, 100] |
| Drawdown Control | 20% | max_drawdown_1y normalizado [-50%, 0%] → [0, 100] |
| Information Ratio | 15% | IR_1y normalizado [-1.0, +2.0] → [0, 100] |
| Fee Efficiency | 10% | max(0, 100 - ER% × 50) |
| Flows Momentum | **5%** | blended_momentum_score (0-100), EMA-filtered |

**Overall Score** = Σ (componente_i × peso_i)

### 5.2 Fee Efficiency

```
fee_efficiency = max(0, 100 - expense_ratio_pct × 100 × 50)
```

| Expense Ratio | Score |
|---|---|
| 0.00% | 100 (grátis) |
| 0.50% | 75 |
| 1.00% | 50 |
| 1.30% (média) | 35 |
| 2.00% | 0 |

Fonte: XBRL N-CSR filings (`sec_fund_classes.expense_ratio_pct`). Cobertura: 81% dos fundos.

### 5.3 Tratamento de Dados Ausentes

~~Neutral 50 cego~~ → **Mediana do peer group (strategy) - 5 pontos**

- Penaliza fundos opacos ou com histórico curto vs peers transparentes com scores medianos
- Quando não há peer median disponível, fallback para 45.0 (abaixo do midpoint)
- Sem dados = ligeira desvantagem, não neutralidade

### 5.4 Distribuição Actual (5,367 fundos)

| Percentil | Score |
|---|---|
| Min | 8.5 |
| P25 | 46.8 |
| **Mediana** | **51.6** |
| P75 | 56.5 |
| Max | 74.8 |

---

## 6. Peer Percentile Ranking

Ranking percentil (0-100) dentro de cada grupo de strategy:

| Métrica | Direcção |
|---|---|
| Sharpe 1Y | Higher = better |
| Sortino 1Y | Higher = better |
| Return 1Y | Higher = better |
| Max Drawdown 1Y | Less negative = better |

- Agrupamento por `strategy_label` da `mv_unified_funds`
- Mínimo 5 peers por grupo
- Percentil = `count(peers ≤ value) / total_peers × 100`
- **Cobertura:** 5,152 fundos (96%), avg peer group = 509 fundos

---

## 7. Regime-Conditioned CVaR

A joia da coroa do motor. CVaR incondicional falha porque a correlação dos ativos tende a 1 em momentos de pânico. Filtrar retornos apenas para dias de stress fornece uma estimativa de risco de cauda extremamente realista.

- Filtra retornos apenas de datas classificadas como RISK_OFF ou CRISIS
- Computa Expected Shortfall (CVaR 95%) sobre esta sub-amostra
- Coluna: `cvar_95_conditional`
- Mínimo 20 observações de stress
- Uso: calibração de limites de risco em portfólios institucionais

---

## 8. Pipeline de Computação

```
macro_ingestion worker (lock 43, diário)
  └── FRED API → macro_data (90 séries, 4 regiões + global + credit)
      ├── VIX, HY OAS, DXY, WTI, BAA, DFF, CFNAI, Sahm, Yield Curve
      └── regime_service.classify_regime_multi_signal()
          └── 9 sinais (55% fast + 45% slow) → composite stress → regime

instrument_ingestion worker (lock 900_010)
  └── Tiingo / Yahoo Finance → nav_timeseries (preços diários)

global_risk_metrics worker (lock 900_071, diário)
  ├── Pass 1.0: CVaR, VaR, Sharpe, Sortino, Alpha, Beta, IR, Volatility
  ├── Pass 1.5: RSI(14), Bollinger, NAV Momentum, Flow Momentum (EMA 63d)
  ├── Pass 1.6: GARCH(1,1) → EWMA(λ=0.94) fallback
  ├── Pass 1.7: Regime-Conditional CVaR (stress-filtered returns)
  ├── Pass 1.8: Fund Scoring (6 components, peer median imputation, ER from XBRL)
  └── Pass 2.0: Peer Percentile Ranking (by strategy, 4 metrics)
        ↓
  fund_risk_metrics (global, org_id = NULL, 5,367 instrumentos)
        ↓
  Screener → Fact Sheet → Dashboard → Portfolio Construction
```

---

## 9. Leitura Actual do Mercado (2026-04-06)

| Layer | Signal | Value | Stress | Weight |
|---|---|---|---|---|
| **FAST** | VIX | 24.5 | 38/100 | 20% |
| **FAST** | US HY OAS | 3.17% | 19/100 | 15% |
| **FAST** | Energy Shock | WTI +4.4σ, +81% 3m | **100/100** | 10% |
| **FAST** | DXY z-score | +0.09σ | 4/100 | 10% |
| **SLOW** | CFNAI | -0.11 | 0/100 | 15% |
| **SLOW** | Yield Curve | +0.52% | 32/100 | 10% |
| **SLOW** | BAA-10Y | 1.75% | 42/100 | 5% |
| **SLOW** | FF Δ6m | -0.45% | 2/100 | 5% |
| **SLOW** | Sahm | 0.20 | 40/100 | 5% |
| | **Composite** | | **30.0/100** | **→ RISK_OFF** |

**Interpretação:** Choque de oferta energético severo (Hormuz) com VIX e credit spreads ainda moderados. Fed em ciclo de corte (dovish). CFNAI perto do trend. O modelo correctamente classifica como RISK_OFF (cautela, tilt defensivo) em vez de CRISIS — a contração real ainda não se materializou na economia. Se CFNAI cair abaixo de -0.30 ou HY spreads alargarem acima de 4%, cruza para CRISIS.
