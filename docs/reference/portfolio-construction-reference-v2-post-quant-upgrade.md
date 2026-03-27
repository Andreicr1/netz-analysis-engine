# Portfolio Construction — Referência Técnica Completa
# SNAPSHOT: v2 — pós quant upgrade Sprints 1-3
# Salvo em: 2026-03-27

## Visão Geral

A construção de portfolio é um pipeline de 11 etapas que transforma um universo de fundos aprovados em uma alocação ótima com NAV sintético. O sistema usa o solver CLARABEL (interior-point conic) com cascade de 4 fases (incluindo otimização robusta) para enforcement de CVaR, fallback para SCS, e heurística score-proporcional como último recurso.

O pipeline incorpora:
- **Black-Litterman** para expected returns (prior + views do mercado)
- **Ledoit-Wolf shrinkage** na covariância amostral
- **Covariância regime-conditioned** (janela curta em stress, longa em normalidade)
- **Otimização robusta** (uncertainty sets elipsoidais, SOCP)
- **CVaR condicional ao regime** (limite mais apertado em RISK_OFF/CRISIS)
- **Turnover penalty** para minimizar custos de rebalanceamento
- **PCA factor decomposition** para exposição a fatores latentes
- **GARCH(1,1)** para volatilidade condicional por fundo
- **Stress testing paramétrico** com cenários predefinidos (GFC, COVID, Taper, Rate Shock)

**Endpoint:** `POST /api/v1/model-portfolios/{portfolio_id}/construct`
**Response:** `ModelPortfolioRead` com `fund_selection_schema` contendo pesos, metadata de otimização e factor exposures.

---

## 1. Pipeline de Construção

```
POST /construct
  │
  ├─ 1. Carregar universo aprovado (instruments_universe + universe_approvals)
  ├─ 2. Query strategic allocation (blocks, min/max, target por perfil)
  ├─ 3. Resolver CVaR limit e max_single_fund do ConfigService
  ├─ 4. Fetch regime probs (VIX proxy da macro_data)
  ├─ 5. Computar inputs (BL expected returns + shrinkage cov + regime conditioning)
  ├─ 6. Rescalar constraints para universo parcial (se necessário)
  ├─ 7. Rodar CLARABEL com cascade de 4 fases (incluindo Phase 1.5 robust)
  ├─ 8. Construir PortfolioComposition (ou fallback heurístico)
  ├─ 9. Computar PCA factor exposures (best-effort, nunca bloqueia)
  ├─ 10. Criar day-0 PortfolioSnapshot (CVaR, trigger, breach tracking)
  └─ 11. Persistir fund_selection_schema no ModelPortfolio
```

**Arquivo principal:** `backend/app/domains/wealth/routes/model_portfolios.py`
**Função:** `_run_construction_async()`

---

## 2. Carga do Universo Aprovado

**Função:** `_load_universe_funds()`

Busca fundos com aprovação ativa via join:

```
instruments_universe
  JOIN universe_approvals ON (instrument_id, is_current=true, decision='approved')
  WHERE is_active=true AND block_id IS NOT NULL
```

Para cada fundo, busca o `manager_score` mais recente de `fund_risk_metrics`.

**Output:** lista de `{instrument_id, fund_name, block_id, manager_score}`

---

## 3. Strategic Allocation — Constraints por Perfil

**Tabela:** `strategic_allocation`

| Perfil | CVaR Limit | Warning (%) | Breach Days | Max Single Fund |
|--------|-----------|-------------|-------------|-----------------|
| conservative | -0.08 (8%) | 80% | 5 | 0.10 (10%) |
| moderate | -0.06 (6%) | 80% | 3 | 0.12 (12%) |
| growth | -0.12 (12%) | 80% | 5 | 0.15 (15%) |

### Regime CVaR Multipliers (BL-9)

| Regime | Multiplier | Efeito (moderate) |
|--------|-----------|-------------------|
| RISK_ON | 1.0 | -0.06 |
| RISK_OFF | 0.85 | -0.051 |
| CRISIS | 0.70 | -0.042 |

Configurado em `calibration.yaml` → `regime_cvar_multipliers`.


---

## 4. Inputs Estatísticos — Covariance Matrix e Expected Returns

**Função:** `compute_fund_level_inputs()` (`backend/app/domains/wealth/services/quant_queries.py`)

### 4.1 Coleta de Retornos

- Lookback padrão: 252 trading days (buffer 1.5× = 378 dias)
- Mínimo: 120 trading days alinhados (≈6 meses)
- Alinhamento: interseção de datas comuns entre todos os fundos
- `return_type` filtrado: log preferred, arithmetic fallback com warning (BL-3)

### 4.2 Matriz de Covariância — Pipeline de 3 Estágios

**Estágio 1 — Regime-Conditioned Window (BL-5):**

```python
def compute_regime_conditioned_cov(returns, regime_probs, short_window=63, long_window=252):
    mean_stress = np.mean(regime_probs[-long_window:])
    if mean_stress > 0.6:
        window = returns[-short_window:]
        weights = regime_probs[-short_window:]
    else:
        window = returns[-long_window:]
        weights = None
    daily_cov = np.cov(window, rowvar=False, aweights=weights)
    return daily_cov * 252
```

`regime_probs` = proxy VIX de `macro_data`: `vix / (median_vix + vix)`.
Fallback silencioso se `regime_fit` nunca rodou.

**Estágio 2 — Ledoit-Wolf Shrinkage (BL-2):**

```python
from sklearn.covariance import ledoit_wolf
if config.get("optimizer", {}).get("apply_shrinkage", True):
    shrunk_cov, _ = ledoit_wolf(returns_matrix)
    annual_cov = shrunk_cov * 252
```

Controlado por `calibration.yaml` → `optimizer.apply_shrinkage: true`.

**Estágio 3 — Reparo PSD:**

```python
eigenvalues = np.linalg.eigvalsh(annual_cov)
if eigenvalues.min() < -1e-10:
    eigvals, eigvecs = np.linalg.eigh(annual_cov)
    eigvals = np.maximum(eigvals, 1e-10)
    annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
```

### 4.3 Expected Returns — Black-Litterman (BL-4)

**Arquivo:** `backend/quant_engine/black_litterman_service.py`

```
Π = δ · Σ · w_mkt                                              (prior: equilibrium)
μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]             (posterior com views)
```

Sem views: retorna o prior Π (implied equilibrium). Com views do IC cadastradas
em `portfolio_views`: retorna μ_BL. `w_mkt` = strategic allocation targets.

**Parâmetros:** `calibration.yaml` → `bl.risk_aversion: 2.5`, `bl.tau: 0.05`

### 4.4 Momentos Superiores (BL-1)

```python
fund_skewness = scipy.stats.skew(returns_matrix, axis=0)
fund_excess_kurtosis = scipy.stats.kurtosis(returns_matrix, axis=0)
```

Passados ao CVaR Cornish-Fisher — substituem os zeros hard-coded anteriores.

**Output:** `(annual_cov: NxN, expected_returns: {fund_id: float}, ordered_fund_ids, skewness: N, excess_kurtosis: N)`

---

## 5. Rescale de Constraints para Universo Parcial

Mesma lógica da v1. Quando universo cobre subconjunto dos blocks:

```python
target_sum = sum(strategic_targets[bc.block_id] for bc in active_raw)
scale = 1.0 / target_sum
# min_weight relaxado para 0.0, max_weight escalado
```

Se `sum_of_scaled_maxes < 1.0`: relaxa para `max=1.0` por block, apenas `max_single_fund` constrange.

---

## 6. Otimizador CLARABEL — Cascade de 4 Fases

**Arquivo:** `backend/quant_engine/optimizer_service.py`

### 6.1 Constraints Base (compartilhadas entre todas as fases)

```python
def _build_base_constraints(w_var):
    cs = [cp.sum(w_var) == 1]                   # fully invested
    for i in range(n):
        cs.append(w_var[i] <= max_fund_w)        # concentração
    for blk_id, indices in block_fund_indices.items():
        blk_sum = cp.sum([w_var[i] for i in indices])
        cs.append(blk_sum >= bc.min_weight)
        cs.append(blk_sum <= bc.max_weight)
    return cs
```

### 6.2 Phase 1 — Max Risk-Adjusted Return + Turnover Penalty (BL-6)

```
maximize  μᵀw − λ · wᵀΣw − c_turnover · Σ|w_i − w_current_i|
```

Turnover penalty via slack variables L1 quando `current_weights` fornecido:
```python
t1 = cp.Variable(n, nonneg=True)
constraints += [t1 >= w1 - current_weights, t1 >= current_weights - w1]
objective_expr -= turnover_cost * cp.sum(t1)
```

Se turnover penalty torna o problema infeasível: retenta sem penalty.

CVaR verificado com Cornish-Fisher + momentos reais (BL-1):
```python
effective_cvar_limit = cvar_limit * regime_cvar_multiplier   # BL-9
cvar_ok = cvar_neg >= effective_cvar_limit
```

→ Se OK: `status="optimal"`


### 6.3 Phase 1.5 — Robust Optimization (BL-8) — NOVO

Ativado por `calibration.yaml` → `optimizer.robust: true`.

```
maximize  μ̂ᵀw − κ · ‖Lᵀw‖₂ − λ · wᵀΣw

Onde:
  κ = uncertainty_level × √N    (escala com dimensionalidade)
  L = Cholesky(Σ)               (reformulação SOCP)
```

```python
kappa = uncertainty_level * np.sqrt(n)
L = np.linalg.cholesky(cov_matrix)
robust_penalty = kappa * cp.norm(L.T @ w_robust, 2)
```

Resolvido nativamente pelo CLARABEL (SOCP).
Se infeasível ou CVaR viola → prossegue para Phase 2.
→ Se OK: `status="optimal:robust"`

**Parâmetros:** `optimizer.robust: true`, `optimizer.uncertainty_level: 0.5`

### 6.4 Phase 2 — Re-otimização com Teto de Variância

```
σ_max = |effective_cvar_limit| / cvar_coeff    (cvar_coeff ≈ 3.71)
σ²_max = σ_max²

maximize  μᵀw    s.t.  wᵀΣw ≤ σ²_max
```

→ Se OK: `status="optimal:cvar_constrained"`

### 6.5 Phase 3 — Min-Variance Fallback

```
minimize  wᵀΣw
```

→ `status="optimal:min_variance_fallback"`

### 6.6 Fallback Final

Todas as 4 fases falham → retorna Phase 1 com `status="optimal:cvar_violated"`.

### 6.7 Solver Fallback (CLARABEL → SCS)

Cada fase tenta CLARABEL; se falhar → SCS com `eps=1e-5`, `max_iters=10000`.

### 6.8 Tabela de Status do Optimizer

| Status | Significado | Fase | CVaR OK? |
|--------|-------------|------|----------|
| `optimal` | Solução ótima | Phase 1 | Sim |
| `optimal:robust` | Solução robusta (uncertainty set) | Phase 1.5 | Sim |
| `optimal:cvar_constrained` | Re-otimizado com teto de variância | Phase 2 | Provável |
| `optimal:min_variance_fallback` | Menor risco possível | Phase 3 | Não garantido |
| `optimal:cvar_violated` | Todas fases falharam | Phase 1 | Não |
| `solver_failed` | CLARABEL e SCS falharam | — | N/A |
| `fallback:insufficient_fund_data` | Heurístico | — | N/A |
| `infeasible: {reason}` | Constraints impossíveis | — | N/A |

---

## 7. CVaR — Conditional Value at Risk

### 7.1 CVaR Parametrizado (Cornish-Fisher) — agora com momentos reais (BL-1)

```
z_CF = z + (z²−1)·S/6 + (z³−3z)·K/24 − (2z³−5z)·S²/36

Onde S = skewness, K = excess kurtosis (computados de retornos reais)
```

Anteriormente S=K=0 (hard-coded). Agora usa momentos reais dos fundos.

### 7.2 CVaR Empírico (Historical Simulation)

4 janelas: 1m (21d), 3m (63d), 6m (126d), 12m (252d).

### 7.3 CVaR Condicional ao Regime (BL-9) — NOVO

```python
def compute_regime_cvar(returns, regime_probs, confidence=0.95, regime_threshold=0.5):
    stress_mask = regime_probs > regime_threshold
    if stress_mask.sum() >= 30:
        stress_returns = returns[stress_mask]
    else:
        stress_returns = returns  # fallback incondicional
    return compute_cvar_from_returns(stress_returns, confidence)
```

Persistido em `fund_risk_metrics.cvar_95_conditional`.
No optimizer: `effective_cvar_limit = cvar_limit * regime_multiplier`.

### 7.4 Convenção de Sinal

- Valores negativos = perda (e.g., `-0.06` = 6%)
- `cvar_within_limit` = `cvar_95 >= cvar_limit`
- `cvar_utilized_pct` = `|cvar_current / cvar_limit| × 100`

---

## 8. Composição do Portfolio

### 8.1 Via Optimizer

- Filtra pesos near-zero (< 1e-6)
- Enriquece com metadata (fund_name, block_id, manager_score)
- Ordena por block → peso descrescente
- Anexa `OptimizationMeta` com dados do solver

### 8.2 Via Heurístico (fallback)

`w_fund = block_weight × (score / sum_scores)`, normalizado para sum=1.0.

### 8.3 OptimizationMeta — campos adicionados em v2

```python
@dataclass(frozen=True, slots=True)
class OptimizationMeta:
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    solver: str         # "CLARABEL", "CLARABEL:robust", "SCS", "min_variance_fallback", "heuristic_fallback"
    status: str
    cvar_95: float | None
    cvar_limit: float | None
    cvar_within_limit: bool
    factor_exposures: dict | None   # NOVO — PCA (BL-7)
```


---

## 9. PCA Factor Decomposition (BL-7) — NOVO

**Arquivo:** `backend/quant_engine/factor_model_service.py`

Computado após construção bem-sucedida. Nunca bloqueia — omitido silenciosamente em falha.

```python
def decompose_factors(returns_matrix, macro_proxies, portfolio_weights, n_factors=3):
    # SVD-based PCA em returns (T×N)
    centered = returns_matrix - returns_matrix.mean(axis=0)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    factor_loadings = Vt[:n_factors].T    # (N×K)
    factor_returns  = centered @ factor_loadings   # (T×K)
    r_squared = sum(S[:n_factors]**2) / sum(S**2)

    # Label via correlação com macro proxies (VIX, DGS10...)
    # Fallback para "factor_1", "factor_2" se indisponível

    # Portfolio exposures: w^T @ loadings
    exposures = portfolio_weights @ factor_loadings
```

**Response** (em `optimization` do `fund_selection_schema`):

```json
{
  "factor_exposures": {
    "factor_1": 0.234,
    "factor_2": -0.089,
    "factor_3": 0.012
  }
}
```

**Failure modes:** N>T → `n_factors = min(n_factors, T-1)` | dados insuficientes → omitido | qualquer exceção → silencioso.

---

## 10. Stress Testing Paramétrico (BL-10) — NOVO

**Arquivo:** `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py`
**Endpoint:** `POST /api/v1/model-portfolios/{portfolio_id}/stress-test`

### Cenários Predefinidos

| Cenário | Equity Large | Treasury | Credit HY | Gold |
|---------|-------------|----------|-----------|------|
| `gfc_2008` | -38% | +6% | -26% | +5% |
| `covid_2020` | -34% | +8% | -12% | +3% |
| `taper_2013` | -6% | -5% | -4% | -28% |
| `rate_shock_200bps` | -10% | -12% | -6% | +2% |

### Algoritmo

```python
nav_impact = sum(weight * shocks.get(block, 0.0) for block, weight in weights_by_block.items())
# CVaR stressed: shift historical returns e recomputa
```

Org-scoped (RLS). On-demand — não persiste.

---

## 11. Day-0 Snapshot

Mesma lógica da v1.
`trigger_status`: `ok` (<80%) | `maintenance` (80-100%) | `urgent` (≥100%)
`consecutive_breach_days`: reset na construção, incrementado pelo `portfolio_eval` worker diário.

---

## 12. NAV Sintético

Inalterado em relação à v1.
`NAV_t = NAV_{t-1} × (1 + Σ(w_i × r_i))`, batch upsert 500 rows.

---

## 13. Risk Calc Worker — Métricas Atualizadas

**Migration 0058** adicionou 2 colunas a `fund_risk_metrics`:

| Coluna | Tipo | Fonte | Sprint |
|--------|------|-------|--------|
| `volatility_garch` | Numeric(10,6) | GARCH(1,1) ou fallback amostral | BL-11 |
| `cvar_95_conditional` | Numeric(10,6) | CVaR empírico em dias de stress | BL-9 |

### GARCH(1,1) (BL-11) — NOVO

**Arquivo:** `backend/quant_engine/garch_service.py` | **Lib:** `arch>=7.0`

```python
def fit_garch(returns) -> GarchResult | None:
    model = arch_model(returns * 100, vol="Garch", p=1, q=1, mean="Zero")
    result = model.fit(disp="off")
    forecast = result.forecast(horizon=1)
    daily_vol = sqrt(forecast.variance[-1]) / 100
    return GarchResult(volatility_garch=daily_vol * sqrt(252), converged=...)
```

Fallback para vol amostral se: `arch` ausente | < 100 obs | não converge | retornos constantes.

---

## 14. Portfolio Views (BL-4) — NOVO

**Tabela:** `portfolio_views` (org-scoped, RLS) | **Migration:** `a1b2c3d4e5f6`

Views do IC para Black-Litterman:

```
POST   /api/v1/model-portfolios/{id}/views
GET    /api/v1/model-portfolios/{id}/views
DELETE /api/v1/model-portfolios/{id}/views/{view_id}
```

| Campo | Descrição |
|-------|-----------|
| `view_type` | `"absolute"` ou `"relative"` |
| `expected_return` | retorno esperado expresso na view |
| `confidence` | 0.0–1.0 (Idzorek method) |
| `asset_instrument_id` | fundo alvo |
| `peer_instrument_id` | fundo peer (views relativas) |

Sem views cadastradas: optimizer usa prior BL (Π = δΣw_mkt).

---

## 15. Fluxo de Dados Completo

```
Yahoo Finance → instrument_ingestion → nav_timeseries
                                            │
                    risk_calc worker ←──────┘
                            │
                    fund_risk_metrics
                    ├── CVaR, Sharpe, momentum (v1)
                    ├── volatility_garch      (BL-11)
                    └── cvar_95_conditional   (BL-9)
                            │
POST /construct ────────────┤
    │                       │
    ├── universe_approvals ─┤
    ├── strategic_allocation┤
    ├── ConfigService ───────┤
    ├── macro_data (VIX) ────┤── regime_probs
    ├── portfolio_views ─────┤── IC views para BL
    │
    ├── compute_fund_level_inputs
    │   ├── return_type filter     (BL-3)
    │   ├── regime-conditioned cov (BL-5)
    │   ├── Ledoit-Wolf shrinkage  (BL-2)
    │   ├── Black-Litterman μ      (BL-4)
    │   └── skewness + kurtosis    (BL-1)
    │
    ├── optimize_fund_portfolio (CLARABEL 4-phase cascade)
    │   ├── Phase 1:   max risk-adj + turnover penalty (BL-6)
    │   ├── Phase 1.5: robust SOCP                     (BL-8)
    │   ├── Phase 2:   variance-capped
    │   └── Phase 3:   min-variance
    │
    ├── decompose_factors → factor_exposures (BL-7)
    │
    ├── construct_from_optimizer → PortfolioComposition
    │
    ├── _create_day0_snapshot → portfolio_snapshots
    │
    └── fund_selection_schema → model_portfolios

POST /stress-test → run_stress_scenario (BL-10)
    └── GFC | COVID | Taper | Rate Shock | custom
```

---

## 16. Calibração — `calibration.yaml` (atualizado)

```yaml
rebalance:
  turnover_penalty: 0.001        # BL-6
  dead_band_pct: 0.005           # BL-6

optimizer:
  apply_shrinkage: true          # BL-2
  robust: true                   # BL-8
  uncertainty_level: 0.5         # BL-8

regime_cvar_multipliers:         # BL-9
  RISK_OFF: 0.85
  CRISIS: 0.70

bl:                              # BL-4
  risk_aversion: 2.5
  tau: 0.05
```

---

## 17. Glossário

| Termo | Definição |
|-------|-----------|
| **CLARABEL** | Solver interior-point para problemas conic. Determinístico, preciso a 1e-8. |
| **SCS** | Splitting Conic Solver, first-order. Fallback mais robusto, menos preciso. |
| **CVaR₉₅** | Média das perdas no 5% pior cenário. Negativo = perda. |
| **CVaR Condicional** | CVaR empírico usando apenas dias em regime de stress (BL-9). |
| **Cornish-Fisher** | Ajuste do quantil normal para skewness e kurtosis reais (BL-1). |
| **Black-Litterman** | Prior de equilíbrio de mercado + views do IC → posterior μ_BL (BL-4). |
| **Ledoit-Wolf** | Shrinkage: interpola cov amostral com diagonal — reduz erro de estimação (BL-2). |
| **SOCP** | Second-Order Cone Program: robust optimization (BL-8). |
| **GARCH(1,1)** | Volatilidade condicional time-varying por fundo (BL-11). |
| **PCA** | Fatores latentes extraídos da returns matrix (BL-7). |
| **PSD** | Positive Semi-Definite: requisito para solvers conic. |
| **Block** | Categoria de alocação (e.g., `na_equity_large`). |
| **Trigger Status** | `ok` (<80%) | `maintenance` (80-100%) | `urgent` (≥100% CVaR). |
| **Turnover Penalty** | Custo L1 de mudança de pesos — penaliza rebalanceamento excessivo (BL-6). |
| **Dead-Band** | Threshold abaixo do qual mudanças de peso são suprimidas (BL-6). |
| **Regime Multiplier** | Aperta CVaR limit em stress: RISK_OFF=0.85, CRISIS=0.70 (BL-9). |
| **Uncertainty Set** | Região elipsoidal ao redor de μ̂ — captura incerteza na estimação (BL-8). |
