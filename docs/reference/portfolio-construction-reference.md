# Portfolio Construction — Referência Técnica Completa

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

Para cada fundo, busca o `manager_score` mais recente de `fund_risk_metrics`:

```
SELECT instrument_id, manager_score
FROM fund_risk_metrics
WHERE instrument_id IN (...)
ORDER BY instrument_id, calc_date DESC
DISTINCT ON instrument_id
```

**Output:** lista de `{instrument_id, fund_name, block_id, manager_score}`

---

## 3. Strategic Allocation — Constraints por Perfil

**Modelo:** `StrategicAllocation` (`backend/app/domains/wealth/models/allocation.py`)
**Tabela:** `strategic_allocation`

Cada perfil (conservative, moderate, growth) define constraints por block:

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `block_id` | FK → `allocation_blocks` | Bloco de alocação (e.g., `na_equity_large`) |
| `target_weight` | Decimal(6,4) | Peso alvo estratégico (informacional, para drift) |
| `min_weight` | Decimal(6,4) | Piso (hard constraint no optimizer) |
| `max_weight` | Decimal(6,4) | Teto (hard constraint no optimizer) |
| `effective_from` / `effective_to` | Date | Versionamento temporal |

**Deduplicação:** se houver rows duplicadas por block (effective_from overlap), prevalece a mais recente.

### CVaR Limits por Perfil

Resolvidos via `ConfigService.get("liquid_funds", "portfolio_profiles")` com fallbacks hardcoded:

| Perfil | CVaR Limit | Warning (%) | Breach Days | Max Single Fund |
|--------|-----------|-------------|-------------|-----------------|
| conservative | -0.08 (8%) | 80% | 5 | 0.10 (10%) |
| moderate | -0.06 (6%) | 80% | 3 | 0.12 (12%) |
| growth | -0.12 (12%) | 80% | 5 | 0.15 (15%) |

### Regime CVaR Multipliers (BL-9)

Quando o mercado está em regime adverso, o CVaR limit efetivo é apertado:

| Regime | Multiplier | Efeito (moderate) |
|--------|-----------|-------------------|
| RISK_ON | 1.0 (default) | -0.06 |
| RISK_OFF | 0.85 | -0.051 |
| CRISIS | 0.70 | -0.042 |

Configurado em `calibration.yaml` → `regime_cvar_multipliers`.

---

## 4. Inputs Estatísticos — Covariance Matrix e Expected Returns

**Função:** `compute_fund_level_inputs()` (`backend/app/domains/wealth/services/quant_queries.py`)

### 4.1 Coleta de Retornos

Busca `return_1d` da tabela `nav_timeseries` para todos os fundos no lookback window:

- **Lookback padrão:** 252 trading days (1 ano)
- **Buffer:** busca 1.5× (378 dias) para compensar weekends/feriados
- **Mínimo:** 120 trading days alinhados entre todos os fundos (≈6 meses)
- **Alinhamento:** interseção de datas comuns entre todos os fundos

### 4.2 Matriz de Covariância — Pipeline de 3 Estágios (BL-2, BL-5, BL-6)

A covariância agora passa por 3 estágios sequenciais:

**Estágio 1 — Regime-Conditioned Window (BL-2, BL-5):**

```python
def compute_regime_conditioned_cov(returns, regime_probs, short_window=63, long_window=252):
    mean_stress = np.mean(regime_probs[-long_window:])
    if mean_stress > 0.6:
        # Regime adverso: janela curta (63d) com observações ponderadas por stress prob
        window = returns[-short_window:]
        weights = regime_probs[-short_window:]
    else:
        # Regime normal: janela longa (252d) sem ponderação
        window = returns[-long_window:]
        weights = None
    daily_cov = np.cov(window, rowvar=False, aweights=weights)
    return daily_cov * 252  # anualização
```

`regime_probs` vem de um proxy VIX da `macro_data` hypertable: `vix / (median_vix + vix)`.

**Estágio 2 — Ledoit-Wolf Shrinkage (BL-6):**

```python
from sklearn.covariance import ledoit_wolf
if config.get("optimizer", {}).get("apply_shrinkage", False):
    shrunk_cov, shrinkage_coeff = ledoit_wolf(returns_matrix)
    annual_cov = shrunk_cov * 252
```

Shrinkage interpola entre a covariância amostral e uma matriz estruturada (diagonal), reduzindo o erro de estimação para universos pequenos. Controlado por `calibration.yaml` → `optimizer.apply_shrinkage: true`.

**Estágio 3 — Reparo PSD (Positive Semi-Definite):**

```python
eigenvalues = np.linalg.eigvalsh(annual_cov)
if eigenvalues.min() < -1e-10:
    eigvals, eigvecs = np.linalg.eigh(annual_cov)
    eigvals = np.maximum(eigvals, 1e-10)
    annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
```

Garante que a matriz é PSD (requisito do solver conic).

### 4.3 Expected Returns — Black-Litterman (BL-4)

**Arquivo:** `backend/quant_engine/black_litterman_service.py`

Substitui a média aritmética simples por retornos ajustados via Black-Litterman:

```python
def compute_bl_expected_returns(
    cov_matrix: np.ndarray,        # Σ (NxN)
    market_weights: np.ndarray,    # w_mkt (N,) — pesos de mercado
    risk_aversion: float = 2.5,    # δ — aversão a risco
    tau: float = 0.05,             # τ — escala de incerteza do prior
    views: np.ndarray | None,      # P (KxN) — matriz de views
    view_returns: np.ndarray | None,  # Q (K,) — retornos esperados das views
    view_confidence: np.ndarray | None,  # Ω diagonal (K,K)
) -> np.ndarray:
```

**Fórmula:**

```
Π = δ · Σ · w_mkt                          (prior: equilibrium excess returns)
μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]   (posterior com views)
```

Sem views (P=None): retorna o prior Π = δΣw_mkt (implied equilibrium returns).

**Parâmetros em `calibration.yaml`:**

```yaml
bl:
  risk_aversion: 2.5   # δ — calibrado pela relação retorno/risco do mercado
  tau: 0.05             # τ — menor = mais confiança no prior
```

### 4.4 Momentos Superiores (Skewness e Kurtosis)

Computados da mesma returns_matrix alinhada para CVaR Cornish-Fisher:

```python
fund_skewness = scipy.stats.skew(returns_matrix, axis=0)
fund_excess_kurtosis = scipy.stats.kurtosis(returns_matrix, axis=0)
```

**Output:** `(annual_cov: NxN, expected_returns: {fund_id: float}, ordered_fund_ids, skewness: N, excess_kurtosis: N)`

---

## 5. Rescale de Constraints para Universo Parcial

Quando o universo cobre apenas um subconjunto dos blocks (e.g., 2 de 14), os min/max originais não somam 1.0 → infeasível. O sistema rescala proporcionalmente:

```python
target_sum = sum(strategic_targets[bc.block_id] for bc in active_raw)
scale = 1.0 / target_sum

active_block_constraints = [
    BlockConstraint(
        block_id=bc.block_id,
        min_weight=0.0,                              # relax floor
        max_weight=min(bc.max_weight * scale, 1.0),   # scale ceiling
    )
    for bc in active_raw
]
```

### Feasibility Check Avançada

O check inclui a interação entre `max_single_fund` e block constraints. O max efetivo por block é o mínimo entre o block max e `n_fundos_no_block × max_single_fund`:

```python
effective_max_single = min(max_single_fund * (1.0 / max(target_sum, 0.01)), 1.0)
sum_of_scaled_maxes = sum(
    min(bc.max_weight, funds_per_block[bc.block_id] * effective_max_single)
    for bc in active_block_constraints
)
if sum_of_scaled_maxes < 1.0:
    # Relaxar para unconstrained (apenas max_single_fund aplica)
    active_block_constraints = [
        BlockConstraint(block_id=bc.block_id, min_weight=0.0, max_weight=1.0)
        for bc in active_block_constraints
    ]
```

---

## 6. Otimizador CLARABEL — Cascade de 4 Fases

**Arquivo:** `backend/quant_engine/optimizer_service.py`
**Função:** `optimize_fund_portfolio()`

O otimizador usa `cvxpy` com solver CLARABEL (interior-point conic) e fallback para SCS.

### 6.1 Constraints Base (compartilhadas entre todas as fases)

```python
def _build_base_constraints(w_var):
    cs = [cp.sum(w_var) == 1]                           # fully invested
    for i in range(n):
        cs.append(w_var[i] <= max_fund_w)               # concentração
    for blk_id, indices in block_fund_indices.items():
        blk_sum = cp.sum([w_var[i] for i in indices])
        cs.append(blk_sum >= bc.min_weight)              # piso do block
        cs.append(blk_sum <= bc.max_weight)              # teto do block
    return cs
```

### 6.2 Phase 1 — Max Risk-Adjusted Return (com Turnover Penalty)

**Objetivo:** maximizar retorno ajustado ao risco, penalizado pelo turnover.

```
maximize  μᵀw − λ · wᵀΣw − c_turnover · Σ|w_i − w_current_i|
```

Onde `λ = 2.0` (risk aversion) e `c_turnover` é o custo de turnover.

**Turnover penalty (BL-1):** quando `current_weights` é fornecido e `turnover_cost > 0`, adiciona variáveis de slack para a norma L1 de turnover:

```python
if current_weights is not None and turnover_cost > 0:
    t1 = cp.Variable(n, nonneg=True)
    constraints += [t1 >= w1 - current_weights, t1 >= current_weights - w1]
    objective_expr -= turnover_cost * cp.sum(t1)
```

**Dead-band filter:** mudanças de peso menores que `dead_band_pct` (default 0.5%) são suprimidas no rebalancing para evitar churn.

Se turnover penalty tornar o problema infeasível, retenta sem penalty.

Após resolver, verifica CVaR parametricamente (Cornish-Fisher) e aplica o regime multiplier:

```python
effective_cvar_limit = cvar_limit * regime_cvar_multiplier  # e.g., -0.06 * 0.70 = -0.042 em CRISIS
cvar_ok = cvar_neg >= effective_cvar_limit
```

Se CVaR está dentro do limite efetivo → retorna `status="optimal"`.

### 6.3 Phase 1.5 — Robust Optimization (BL-8)

**Novo.** Ativado quando `robust=True` em `calibration.yaml → optimizer.robust`.

Usa uncertainty sets elipsoidais — penaliza a incerteza na estimativa de retornos:

```
maximize  μ̂ᵀw − κ · ‖Lᵀw‖₂ − λ · wᵀΣw

Onde:
  κ = uncertainty_level × √N    (escala com dimensionalidade)
  L = Cholesky(Σ)               (para reformulação SOCP)
```

```python
kappa = uncertainty_level * np.sqrt(n)
L = np.linalg.cholesky(cov_matrix)
robust_penalty = kappa * cp.norm(L.T @ w_robust, 2)
robust_obj = cp.Maximize(mu @ w - robust_penalty - risk_aversion * cp.quad_form(w, Σ))
```

A reformulação SOCP (Second-Order Cone Program) é resolvida nativamente pelo CLARABEL. Se Phase 1.5 é infeasível ou o CVaR do resultado ainda viola, prossegue para Phase 2.

**Parâmetros em `calibration.yaml`:**

```yaml
optimizer:
  robust: true
  uncertainty_level: 0.5   # κ base — maior = mais conservador
```

Retorna `status="optimal:robust"` quando bem-sucedido.

### 6.4 Phase 2 — Re-otimização com Teto de Variância

Quando Phase 1 (e 1.5, se ativo) viola CVaR, deriva um teto de variância a partir do cvar_limit usando aproximação normal:

```
CVaR₉₅ ≈ σ × (−z₀.₀₅ + φ(z₀.₀₅)/α) − μ

Onde:
  z₀.₀₅ = Φ⁻¹(0.05) ≈ −1.645
  φ(z)  = pdf normal em z ≈ 0.1031
  cvar_coeff = −z + φ(z)/α ≈ 3.71

  σ_max = |cvar_limit| / cvar_coeff
  σ²_max = (|cvar_limit| / 3.71)²
```

```python
constraints2 = _build_base_constraints(w2)
constraints2.append(cp.quad_form(w2, psd_cov) <= max_var)
prob2 = cp.Problem(cp.Maximize(mu @ w2), constraints2)
```

Se feasible → retorna `status="optimal:cvar_constrained"`.

### 6.5 Phase 3 — Min-Variance Fallback

Quando Phase 2 é infeasível, resolve a alocação de menor risco possível:

```
minimize  wᵀΣw     (variância do portfolio)
```

Retorna `status="optimal:min_variance_fallback"`.

### 6.6 Fallback Final

Se todas as 4 fases falham, retorna o resultado de Phase 1 com `status="optimal:cvar_violated"`.

### 6.7 Solver Fallback (CLARABEL → SCS)

Cada fase tenta CLARABEL primeiro; se falhar ou retornar não-optimal, tenta SCS com tolerâncias mais relaxadas:

```python
prob.solve(solver=cp.CLARABEL, verbose=False)
if prob.status not in ("optimal", "optimal_inaccurate"):
    prob.solve(solver=cp.SCS, verbose=False, eps=1e-5, max_iters=10000)
```

### 6.8 Tabela de Status do Optimizer

| Status | Significado | Fase | CVaR OK? |
|--------|-------------|------|----------|
| `optimal` | Solução ótima com CVaR dentro do limite | Phase 1 | Sim |
| `optimal:robust` | Solução robusta (uncertainty set) com CVaR OK | Phase 1.5 | Sim |
| `optimal:cvar_constrained` | Re-otimizado com teto de variância | Phase 2 | Provável |
| `optimal:min_variance_fallback` | Menor risco possível | Phase 3 | Não garantido |
| `optimal:cvar_violated` | Todas fases falharam, usa Phase 1 | Phase 1 | Não |
| `solver_failed` | CLARABEL e SCS falharam | — | N/A |
| `fallback:insufficient_fund_data` | Sem dados suficientes, heurístico | — | N/A |
| `infeasible: {reason}` | Constraints impossíveis | — | N/A |

---

## 7. CVaR — Conditional Value at Risk

### 7.1 CVaR Parametrizado (Cornish-Fisher)

**Função:** `parametric_cvar_cf()` (`optimizer_service.py`)

Usado no NSGA-II (Pareto) e na validação pós-otimização. Mais preciso que CVaR normal para portfolios com fat tails.

**Fórmula Cornish-Fisher:**

```
z_CF = z + (z²−1)·S/6 + (z³−3z)·K/24 − (2z³−5z)·S²/36

Onde:
  z   = Φ⁻¹(α) = −1.645 para α=0.05
  S   = skewness do portfolio (wᵀskew)
  K   = excess kurtosis do portfolio (wᵀkurt)

CVaR = −(μ_p + σ_p · z_CF) + σ_p · φ(z_CF) / α
```

### 7.2 CVaR Empírico (Historical Simulation)

**Função:** `compute_cvar_from_returns()` (`backend/quant_engine/cvar_service.py`)

Usado pelo worker `risk_calc` para calcular métricas de risco por fundo:

```python
sorted_returns = np.sort(returns)
cutoff_idx = int(len(sorted_returns) * (1 - 0.95))  # bottom 5%
var = sorted_returns[cutoff_idx]
cvar = sorted_returns[:cutoff_idx].mean()
```

Calculado em 4 janelas: 1m (21d), 3m (63d), 6m (126d), 12m (252d).

### 7.3 CVaR Condicional ao Regime (BL-9)

**Função:** `compute_regime_cvar()` (`backend/quant_engine/cvar_service.py`)

CVaR empírico usando apenas observações onde `regime_probs > threshold`:

```python
def compute_regime_cvar(returns, regime_probs, confidence=0.95, regime_threshold=0.5):
    stress_mask = regime_probs > regime_threshold
    if stress_mask.sum() >= 30:
        stress_returns = returns[stress_mask]
    else:
        stress_returns = returns  # fallback para incondicional
    cvar, _ = compute_cvar_from_returns(stress_returns, confidence)
    return cvar
```

Persistido na coluna `cvar_95_conditional` de `fund_risk_metrics`.

**Integração no optimizer:** o `regime_cvar_multiplier` aperta o `cvar_limit` efetivo:

```python
effective_cvar_limit = cvar_limit * regime_cvar_multiplier
# RISK_OFF: 0.85, CRISIS: 0.70 (calibration.yaml → regime_cvar_multipliers)
```

### 7.4 Convenção de Sinal

- **Valores negativos** representam perda (e.g., `-0.06` = perda de 6%)
- **cvar_limit** é negativo (e.g., `-0.06` para moderate)
- **cvar_within_limit** = `cvar_95 >= cvar_limit` (e.g., `-0.04 >= -0.06` → True)
- **cvar_utilized_pct** = `|cvar_current / cvar_limit| × 100` (e.g., `|-0.04 / -0.06| × 100 = 66.7%`)

---

## 8. Composição do Portfolio

### 8.1 Via Optimizer (`construct_from_optimizer`)

**Arquivo:** `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py`

Converte o dict `{instrument_id: weight}` do CLARABEL em `PortfolioComposition`:

- Filtra pesos near-zero (`< 1e-6`)
- Enriquece com metadata (fund_name, block_id, manager_score)
- Ordena por block → peso descrescente
- Anexa `OptimizationMeta` com dados do solver

### 8.2 Via Heurístico (`construct`)

Fallback quando optimizer não tem dados suficientes:

1. Agrupa fundos por block
2. Seleciona top-N por `manager_score` em cada block (default N=3)
3. Distribui peso do block proporcionalmente ao score: `w_fund = block_weight × (score / sum_scores)`
4. Normaliza para sum=1.0

### 8.3 Modelo de Dados

```python
@dataclass(frozen=True, slots=True)
class OptimizationMeta:
    expected_return: float          # retorno anualizado
    portfolio_volatility: float     # volatilidade anualizada
    sharpe_ratio: float             # (return - rf) / vol
    solver: str                     # "CLARABEL", "CLARABEL:robust", "SCS", "min_variance_fallback", "heuristic_fallback"
    status: str                     # ver tabela de status acima
    cvar_95: float | None           # CVaR parametrizado (negativo = perda)
    cvar_limit: float | None        # limite do perfil (pode ser ajustado por regime)
    cvar_within_limit: bool         # flag de conformidade

@dataclass(frozen=True, slots=True)
class FundWeight:
    instrument_id: uuid.UUID
    fund_name: str
    block_id: str
    weight: float                   # peso no portfolio (0 a 1)
    score: float                    # manager_score usado no ranking

@dataclass(frozen=True, slots=True)
class PortfolioComposition:
    profile: str
    funds: list[FundWeight]
    total_weight: float             # deve ser ≈ 1.0
    optimization: OptimizationMeta | None
```

---

## 9. PCA Factor Decomposition (BL-7)

**Arquivo:** `backend/quant_engine/factor_model_service.py`

Após a construção bem-sucedida (status `optimal*`), o pipeline computa uma decomposição PCA dos retornos do portfolio e adiciona `factor_exposures` ao response.

### 9.1 Algoritmo

```python
def decompose_factors(returns_matrix, macro_proxies, portfolio_weights, n_factors=3):
    # 1. SVD-based PCA em returns_matrix (T×N)
    centered = returns_matrix - returns_matrix.mean(axis=0)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    # 2. Factor loadings (N×K) e factor returns (T×K)
    factor_loadings = Vt[:n_factors].T
    factor_returns = centered @ factor_loadings

    # 3. R² = variance explicada pelos K fatores
    r_squared = sum(S[:n_factors]**2) / sum(S**2)

    # 4. Label fatores por correlação com macro proxies (VIX, DGS10, etc.)
    #    Fallback para "factor_1", "factor_2" se proxies indisponíveis

    # 5. Portfolio factor exposures: w^T @ loadings
    exposures = portfolio_weights @ factor_loadings
```

### 9.2 Response

Adicionado ao campo `optimization` do `fund_selection_schema`:

```json
{
  "optimization": {
    "expected_return": 0.08,
    "sharpe_ratio": 0.72,
    "factor_exposures": {
      "factor_1": 0.234,
      "factor_2": -0.089,
      "factor_3": 0.012
    }
  }
}
```

### 9.3 Failure Modes

- **N > T (mais fundos que observações):** `n_factors` capado a `min(n_factors, T-1)`
- **macro_proxies indisponíveis:** labels default "factor_1", "factor_2"...
- **Dados insuficientes (< 3 fundos ou < 60 obs):** section omitida
- **Qualquer exceção:** silenciosamente omitido (never-raises, never-blocks)

---

## 10. Stress Testing Paramétrico (BL-10)

**Arquivo:** `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py`
**Endpoint:** `POST /api/v1/model-portfolios/{portfolio_id}/stress-test`

### 10.1 Cenários Predefinidos

| Cenário | Equity Large | Treasury | Credit HY | Gold | REITs |
|---------|-------------|----------|-----------|------|-------|
| `gfc_2008` | -38% | +6% | -26% | +5% | -38% |
| `covid_2020` | -34% | +8% | -12% | +3% | -25% |
| `taper_2013` | -6% | -5% | -4% | -28% | -4% |
| `rate_shock_200bps` | -10% | -12% | -6% | +2% | -15% |

### 10.2 Algoritmo

```python
def run_stress_scenario(weights_by_block, shocks, historical_returns, scenario_name):
    # NAV impact: ΔP/P = Σ(w_block × shock_block)
    nav_impact = sum(weight * shocks.get(block, 0.0) for block, weight in weights_by_block.items())

    # Stressed CVaR: shift historical returns e recomputa
    if historical_returns is not None:
        shifted = historical_returns + nav_impact / len(historical_returns)
        cvar_stressed, _ = compute_cvar_from_returns(shifted)
```

### 10.3 Response

```json
{
  "portfolio_id": "...",
  "scenario_name": "gfc_2008",
  "nav_impact_pct": -0.204,
  "cvar_stressed": -0.045,
  "block_impacts": {
    "na_equity_large": -0.228,
    "fi_treasury": 0.024
  },
  "worst_block": "na_equity_large",
  "best_block": "fi_treasury"
}
```

### 10.4 API

```
POST /api/v1/model-portfolios/{portfolio_id}/stress-test
Body: {
  "scenario_name": "rate_shock_200bps"   // preset
}
// ou
Body: {
  "scenario_name": "custom",
  "shocks": {"na_equity_large": -0.15, "fi_treasury": -0.08}
}
```

Org-scoped (RLS). Não persiste resultado (calculado on-demand).

---

## 11. Day-0 Snapshot e Documentação de Violação de CVaR

**Função:** `_create_day0_snapshot()` (`model_portfolios.py`)

### 11.1 PortfolioSnapshot

**Tabela:** `portfolio_snapshots` (TimescaleDB hypertable, chunks de 1 mês, compressão 3 meses)

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `snapshot_id` | UUID | PK |
| `profile` | String(20) | Perfil do portfolio |
| `snapshot_date` | Date | Data do snapshot (parte da PK) |
| `weights` | JSONB | `{block_id: weight}` agregado |
| `fund_selection` | JSONB | Schema completo com fundos e optimization |
| `cvar_current` | Numeric(10,6) | CVaR₉₅ do optimizer (negativo) |
| `cvar_limit` | Numeric(10,6) | Limite do perfil (negativo) |
| `cvar_utilized_pct` | Numeric(6,2) | `|cvar/limit| × 100` |
| `trigger_status` | String(20) | `"ok"` \| `"maintenance"` \| `"urgent"` |
| `consecutive_breach_days` | Integer | Dias consecutivos em breach |

### 11.2 Trigger Status Logic

```python
cvar_utilized = abs(cvar_current / cvar_limit) * 100

if cvar_utilized >= 100.0:
    trigger = "urgent"              # CVaR excede o limite
elif cvar_utilized >= 80.0:
    trigger = "maintenance"         # CVaR próximo do limite
else:
    trigger = "ok"
```

### 11.3 Rastreamento da Violação em 3 Camadas

**1. fund_selection_schema (JSONB no ModelPortfolio):**
```json
{
  "optimization": {
    "solver": "CLARABEL:robust",
    "status": "optimal:robust",
    "cvar_95": -0.05,
    "cvar_limit": -0.06,
    "cvar_within_limit": true,
    "factor_exposures": {"factor_1": 0.23, "factor_2": -0.09}
  }
}
```

**2. PortfolioSnapshot (hypertable para série temporal):**
- `cvar_current`, `cvar_limit`, `cvar_utilized_pct`, `trigger_status`
- `consecutive_breach_days = 0` (reset na construção; incrementado pelo worker diário)

**3. Monitoring Engine (workers diários):**
- `portfolio_eval` worker (lock 900_008) roda diário
- Re-computa CVaR do portfolio usando retornos atualizados
- Incrementa `consecutive_breach_days` se CVaR permanece acima do limite
- Quando `consecutive_breach_days >= breach_days`: alerta formal via Redis pub/sub

---

## 12. NAV Sintético

### 12.1 Worker: `run-portfolio-nav-synthesizer`

**Arquivo:** `backend/app/domains/wealth/workers/portfolio_nav_synthesizer.py`
**Lock ID:** 900_030
**Tabela de destino:** `model_portfolio_nav`

### 12.2 Algoritmo

Para cada ModelPortfolio com status `backtesting`, `active`, ou `live`:

1. Extrair pesos de `fund_selection_schema.funds[].{instrument_id, weight}`
2. Determinar ponto de partida (incremental ou inception)
3. Buscar retornos diários de `nav_timeseries`
4. Compor NAV diário: `NAV_t = NAV_{t-1} × (1 + Σ(w_i × r_i))` com renormalização para fundos faltando
5. Batch upsert em `model_portfolio_nav`

### 12.3 Modelo de Dados

```python
class ModelPortfolioNav(OrganizationScopedMixin, Base):
    __tablename__ = "model_portfolio_nav"

    portfolio_id: UUID (PK, FK → model_portfolios.id)
    nav_date: Date (PK)
    nav: Numeric(18, 6)
    daily_return: Numeric(12, 8) | None
    organization_id: UUID (RLS)
```

---

## 13. Risk Calc Worker — Pré-computação de Métricas

**Arquivo:** `backend/app/domains/wealth/workers/risk_calc.py`
**Lock ID:** 900_007
**Tabela:** `fund_risk_metrics`

O worker `run-risk-calc` é pré-requisito para o construct.

### 13.1 Métricas Computadas

| Categoria | Métricas | Janelas |
|-----------|----------|---------|
| **CVaR/VaR** | CVaR₉₅, VaR₉₅ | 1m, 3m, 6m, 12m |
| **CVaR Condicional** | CVaR₉₅ conditional on stress regime (BL-9) | 12m |
| **Returns** | Retorno cumulativo | 1m, 3m, 6m, 1y, 3y (ann.) |
| **Risco** | Volatilidade amostral, Max Drawdown | 1y, 3y |
| **GARCH** | Volatilidade condicional GARCH(1,1) (BL-11) | 1-step-ahead |
| **Ratios** | Sharpe, Sortino | 1y, 3y |
| **Benchmark** | Alpha, Beta, IR, TE | 1y |
| **Momentum** | RSI(14), BB Position, NAV/Flow/Blended Score | Últimos 50 obs |
| **Drift** | DTW Drift Score | 63 days |
| **Scoring** | Manager Score (composite 0-100) | latest |

### 13.2 GARCH(1,1) — Volatilidade Condicional (BL-11)

**Arquivo:** `backend/quant_engine/garch_service.py`
**Biblioteca:** `arch>=7.0` (adicionada em `pyproject.toml [quant]`)

```python
def fit_garch(returns, trading_days_per_year=252) -> GarchResult | None:
    model = arch_model(returns * 100, vol="Garch", p=1, q=1, mean="Zero")
    result = model.fit(disp="off")

    # 1-step-ahead forecast
    forecast = result.forecast(horizon=1)
    daily_vol = sqrt(forecast.variance[-1]) / 100
    annual_vol = daily_vol * sqrt(252)
```

**Integração no worker:**

```python
garch_result = fit_garch(returns)
if garch_result and garch_result.converged:
    metrics["volatility_garch"] = garch_result.volatility_garch
else:
    metrics["volatility_garch"] = metrics.get("volatility_1y")  # fallback amostral
```

**Failure modes:**
- `arch` não instalado → retorna None, worker usa vol amostral
- Dados insuficientes (< 100 obs) → retorna None
- Não converge → `converged=False`, worker usa vol amostral
- Retornos constantes → não crash, graceful fallback

### 13.3 Colunas Adicionadas (Migration 0058)

| Coluna | Tipo | Fonte |
|--------|------|-------|
| `volatility_garch` | Numeric(10,6) | GARCH(1,1) ou vol amostral fallback |
| `cvar_95_conditional` | Numeric(10,6) | CVaR empírico em dias de stress regime |

---

## 14. Portfolio Views (BL-3)

**Modelo:** `PortfolioView` (`backend/app/domains/wealth/models/portfolio_view.py`)
**Rotas:** `backend/app/domains/wealth/routes/portfolio_views.py`

Saved filter/sort configurations para visualização de portfolios no frontend.

**Endpoint base:** `/api/v1/model-portfolios/{portfolio_id}/views`

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/views` | Criar view |
| `GET` | `/views` | Listar views do portfolio |
| `PUT` | `/views/{view_id}` | Atualizar view |
| `DELETE` | `/views/{view_id}` | Deletar view |

**Schema:**

```python
class PortfolioView(OrganizationScopedMixin, Base):
    portfolio_id: UUID (FK → model_portfolios.id)
    name: str                     # nome da view
    filters: dict                 # JSONB — filtros aplicados
    sort_by: str | None           # coluna de ordenação
    sort_desc: bool               # ordem descendente
    columns: list[str] | None     # colunas visíveis
    created_by: str               # actor_id
```

---

## 15. Fluxo de Dados Completo

```
Yahoo Finance → instrument_ingestion worker → nav_timeseries (501 obs/fundo)
                                                    │
                            risk_calc worker ←──────┘
                                    │
                            fund_risk_metrics
                            ├── CVaR, Sharpe, momentum
                            ├── volatility_garch (GARCH 1,1)
                            └── cvar_95_conditional (regime)
                                    │
POST /construct ────────────────────┤
    │                               │
    ├── universe_approvals ─────────┤
    ├── strategic_allocation ───────┤
    ├── ConfigService (cvar_limit) ─┤
    ├── macro_data (VIX → regime) ──┤
    │                               │
    ├── compute_fund_level_inputs ──┤── nav_timeseries (retornos diários)
    │   ├── Regime-conditioned cov (BL-5)
    │   ├── Ledoit-Wolf shrinkage (BL-6)
    │   └── Black-Litterman returns (BL-4)
    │
    ├── optimize_fund_portfolio (CLARABEL 4-phase cascade)
    │   ├── Phase 1:   max risk-adjusted return + turnover penalty (BL-1)
    │   ├── Phase 1.5: robust optimization (BL-8)
    │   ├── Phase 2:   variance-capped (se CVaR viola)
    │   └── Phase 3:   min-variance (se Phase 2 infeasível)
    │
    ├── decompose_factors → factor_exposures (BL-7)
    │
    ├── construct_from_optimizer → PortfolioComposition
    │
    ├── _create_day0_snapshot → portfolio_snapshots
    │   └── cvar_current, trigger_status, breach tracking
    │
    └── fund_selection_schema → model_portfolios.fund_selection_schema
                                        │
                            portfolio_nav_synthesizer worker
                                        │
                                model_portfolio_nav (NAV sintético diário)
                                        │
                            GET /track-record → nav_series[]

POST /stress-test ──── run_stress_scenario → StressScenarioResult (BL-10)
    └── Presets: GFC, COVID, Taper, Rate Shock + custom
```

---

## 16. Calibração — `calibration/seeds/liquid_funds/calibration.yaml`

```yaml
cvar_limits:
  conservative: {cvar_95_3m: -0.04, cvar_95_12m: -0.08}
  moderate:     {cvar_95_3m: -0.08, cvar_95_12m: -0.15}
  growth:       {cvar_95_3m: -0.12, cvar_95_12m: -0.22}

portfolio_profiles:
  conservative: {max_single_fund_weight: 0.15, min_funds: 8, max_funds: 20}
  moderate:     {max_single_fund_weight: 0.12, min_funds: 10, max_funds: 25}
  growth:       {max_single_fund_weight: 0.10, min_funds: 12, max_funds: 30}

rebalance:
  drift_threshold_pct: 5.0
  min_rebalance_interval_days: 30
  consecutive_breach_days_trigger: 5
  turnover_penalty: 0.001            # BL-1: custo de turnover
  dead_band_pct: 0.005               # BL-1: dead-band filter

optimizer:
  apply_shrinkage: true              # BL-6: Ledoit-Wolf
  robust: true                       # BL-8: uncertainty sets
  uncertainty_level: 0.5             # BL-8: κ base

regime_cvar_multipliers:             # BL-9: CVaR apertado em stress
  RISK_OFF: 0.85
  CRISIS: 0.70

bl:                                  # BL-4: Black-Litterman
  risk_aversion: 2.5
  tau: 0.05

regime_detection:
  lookback_days: 252
  n_regimes: 3
  min_regime_length_days: 20
```

---

## 17. Glossário

| Termo | Definição |
|-------|-----------|
| **CLARABEL** | Solver interior-point para problemas conic (SOCP/SDP). Determinístico, preciso a 1e-8. |
| **SCS** | Splitting Conic Solver, first-order. Fallback mais robusto, menos preciso. |
| **CVaR₉₅** | Conditional Value at Risk: média das perdas no 5% pior cenário. Negativo = perda. |
| **CVaR Condicional** | CVaR empírico usando apenas observações em regime de stress (BL-9). |
| **VaR₉₅** | Value at Risk: perda no percentil 5%. CVaR é mais conservador (média da cauda). |
| **Cornish-Fisher** | Ajuste do quantil normal para skewness e kurtosis (fat tails). |
| **Black-Litterman** | Modelo bayesiano que combina equilíbrio de mercado (prior) com views do investidor (BL-4). |
| **Ledoit-Wolf** | Estimador de shrinkage que interpola cov amostral com diagonal, reduzindo erro (BL-6). |
| **PSD** | Positive Semi-Definite: propriedade matricial necessária para solvers conic. |
| **SOCP** | Second-Order Cone Program: classe de problema de otimização convexa usada na robust optimization (BL-8). |
| **GARCH(1,1)** | Generalized Autoregressive Conditional Heteroskedasticity: modelo de volatilidade condicional (BL-11). |
| **PCA** | Principal Component Analysis: extrai fatores latentes da returns matrix (BL-7). |
| **Block** | Categoria de alocação (e.g., `na_equity_large`, `fi_us_treasury`). |
| **Strategic Allocation** | Alocação alvo com bandas min/max por block e perfil. |
| **Trigger Status** | Estado do portfolio: `ok` (<80%), `maintenance` (80-100%), `urgent` (≥100% CVaR). |
| **Breach Days** | Dias consecutivos com CVaR acima do limite. Após N dias → alerta formal. |
| **NAV Sintético** | NAV diário do portfolio computado pela composição ponderada dos retornos dos fundos. |
| **Turnover Penalty** | Custo L1 de mudança de pesos que penaliza rebalanceamentos excessivos (BL-1). |
| **Dead-Band** | Threshold abaixo do qual mudanças de peso são suprimidas para evitar churn (BL-1). |
| **Regime Multiplier** | Fator que aperta o CVaR limit em mercados adversos: RISK_OFF=0.85, CRISIS=0.70 (BL-9). |
| **Uncertainty Set** | Região elipsoidal ao redor de μ̂ que captura a incerteza na estimativa de retornos (BL-8). |
