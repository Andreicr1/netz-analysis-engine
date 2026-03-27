# Portfolio Construction — Referência Técnica Completa
# SNAPSHOT: v1 — pré quant upgrade (Sprints 1-3)
# Salvo em: 2026-03-27

## Visão Geral

A construção de portfolio é um pipeline de 9 etapas que transforma um universo de fundos aprovados em uma alocação ótima com NAV sintético. O sistema usa o solver CLARABEL (interior-point conic) com cascade de 3 fases para enforcement de CVaR, fallback para SCS, e heurística score-proporcional como último recurso.

**Endpoint:** `POST /api/v1/model-portfolios/{portfolio_id}/construct`
**Response:** `ModelPortfolioRead` com `fund_selection_schema` contendo pesos e metadata de otimização.

---

## 1. Pipeline de Construção

```
POST /construct
  │
  ├─ 1. Carregar universo aprovado (instruments_universe + universe_approvals)
  ├─ 2. Query strategic allocation (blocks, min/max, target por perfil)
  ├─ 3. Resolver CVaR limit e max_single_fund do ConfigService
  ├─ 4. Computar inputs (covariance matrix + expected returns de NAV)
  ├─ 5. Rescalar constraints para universo parcial (se necessário)
  ├─ 6. Rodar CLARABEL com cascade de 3 fases
  ├─ 7. Construir PortfolioComposition (ou fallback heurístico)
  ├─ 8. Criar day-0 PortfolioSnapshot (CVaR, trigger, breach tracking)
  └─ 9. Persistir fund_selection_schema no ModelPortfolio
```

**Arquivo principal:** `backend/app/domains/wealth/routes/model_portfolios.py`
**Função:** `_run_construction_async()` (linha 343)

---

## 2. Carga do Universo Aprovado

**Função:** `_load_universe_funds()` (linha 618)

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

**Funções:** `_resolve_cvar_limit()` (linha 674), `_resolve_max_single_fund()` (linha 696)

---

## 4. Inputs Estatísticos — Covariance Matrix e Expected Returns

**Função:** `compute_fund_level_inputs()` (`backend/app/domains/wealth/services/quant_queries.py`, linha 212)

### 4.1 Coleta de Retornos

Busca `return_1d` da tabela `nav_timeseries` para todos os fundos no lookback window:

- **Lookback padrão:** 252 trading days (1 ano)
- **Buffer:** busca 1.5× (378 dias) para compensar weekends/feriados
- **Mínimo:** 120 trading days alinhados entre todos os fundos (≈6 meses)
- **Alinhamento:** interseção de datas comuns entre todos os fundos

### 4.2 Matriz de Covariância

```python
# Matriz T×N de retornos alinhados (T=datas, N=fundos)
returns_matrix = np.array([[fund_returns[fid][d] for fid in available_ids] for d in common_dates])

# Covariância diária (unbiased, N-1 denominador)
daily_cov = np.cov(returns_matrix, rowvar=False)

# Anualização: Σ_annual = Σ_daily × 252
annual_cov = daily_cov * 252
```

### 4.3 Reparo PSD (Positive Semi-Definite)

Matrizes de covariância amostral podem ter autovalores negativos por ruído numérico. O reparo garante que a matriz é PSD (requisito do solver conic):

```python
eigenvalues = np.linalg.eigvalsh(annual_cov)
if eigenvalues.min() < -1e-10:
    eigvals, eigvecs = np.linalg.eigh(annual_cov)
    eigvals = np.maximum(eigvals, 1e-10)           # floor em 1e-10
    annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T  # reconstrução
```

Não usa shrinkage (Ledoit-Wolf) — covariância amostral é suficiente para universos pequenos (<50 fundos).

### 4.4 Expected Returns

```python
daily_means = returns_matrix.mean(axis=0)         # média aritmética diária
annual_returns = daily_means * 252                 # anualização linear
```

**Output:** `(annual_cov: NxN, expected_returns: {fund_id: float}, ordered_fund_ids: list[str])`

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

**Exemplo real (3 fundos, 2 blocks):**
- `na_equity_large`: 1 fundo (PRWCX), max escalado = 0.94
- `na_equity_value`: 2 fundos (OAKMX, DODGX), max escalado = 0.336
- `max_single_fund` escalado = 0.4032
- Effective: min(0.94, 1×0.4032) + min(0.336, 2×0.4032) = 0.4032 + 0.336 = 0.7392 < 1.0
- → Relaxa para max=1.0 por block, apenas max_single_fund=0.4032 constrange

---

## 6. Otimizador CLARABEL — Cascade de 3 Fases

**Arquivo:** `backend/quant_engine/optimizer_service.py`
**Função:** `optimize_fund_portfolio()` (linha 306)

O otimizador usa `cvxpy` com solver CLARABEL (interior-point conic) e fallback para SCS.

### 6.1 Constraints Base (compartilhadas entre as 3 fases)

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

### 6.2 Phase 1 — Max Risk-Adjusted Return

**Objetivo:** maximizar retorno ajustado ao risco (proxy do Sharpe ratio).

```
maximize  μᵀw − λ · wᵀΣw     onde λ = 2.0 (risk aversion)
```

```python
prob1 = cp.Problem(
    cp.Maximize(mu @ w1 - 2.0 * cp.quad_form(w1, psd_cov)),
    _build_base_constraints(w1),
)
```

Após resolver, verifica CVaR parametricamente (Cornish-Fisher com skew/kurt = 0):

```python
cvar_neg = _compute_cvar(opt_w)  # retorna valor negativo (perda)
cvar_ok = cvar_neg >= cvar_limit  # e.g., -0.04 >= -0.06 → True
```

Se CVaR está dentro do limite → retorna `status="optimal"`.

### 6.3 Phase 2 — Re-otimização com Teto de Variância

Quando Phase 1 viola CVaR, deriva um teto de variância a partir do cvar_limit usando aproximação normal:

**Derivação matemática:**

```
CVaR₉₅ ≈ σ × (−z₀.₀₅ + φ(z₀.₀₅)/α) − μ

Onde:
  z₀.₀₅ = Φ⁻¹(0.05) ≈ −1.645     (quantil normal)
  φ(z)  = pdf normal em z           ≈ 0.1031
  α     = 0.05
  cvar_coeff = −z + φ(z)/α          ≈ 1.645 + 0.1031/0.05 ≈ 3.71

Portanto:
  σ_max = |cvar_limit| / cvar_coeff
  σ²_max = (|cvar_limit| / 3.71)²
```

```python
z_alpha = sp_norm.ppf(0.05)         # -1.645
phi_z = sp_norm.pdf(z_alpha)        # 0.1031
cvar_coeff = -z_alpha + phi_z / 0.05  # ≈ 3.71
max_var = (abs(cvar_limit) / cvar_coeff) ** 2

constraints2 = _build_base_constraints(w2)
constraints2.append(cp.quad_form(w2, psd_cov) <= max_var)

prob2 = cp.Problem(cp.Maximize(mu @ w2), constraints2)
```

Se feasible → retorna `status="optimal:cvar_constrained"`.

### 6.4 Phase 3 — Min-Variance Fallback

Quando Phase 2 é infeasível (o teto de variância é impossível de atingir com os constraints de block), resolve a alocação de menor risco possível:

```
minimize  wᵀΣw     (variância do portfolio)
```

```python
prob3 = cp.Problem(
    cp.Minimize(cp.quad_form(w3, psd_cov)),
    _build_base_constraints(w3),
)
```

Retorna `status="optimal:min_variance_fallback"`.

### 6.5 Fallback Final

Se todas as 3 fases falham, retorna o resultado de Phase 1 com `status="optimal:cvar_violated"`.

### 6.6 Solver Fallback (CLARABEL → SCS)

Cada fase tenta CLARABEL primeiro; se falhar ou retornar não-optimal, tenta SCS com tolerâncias mais relaxadas:

```python
prob.solve(solver=cp.CLARABEL, verbose=False)
if prob.status not in ("optimal", "optimal_inaccurate"):
    prob.solve(solver=cp.SCS, verbose=False, eps=1e-5, max_iters=10000)
```

**CLARABEL:** interior-point solver para problemas conic (SOCPs, SDPs). Tolerâncias padrão: `tol_gap_abs=1e-8`, `tol_gap_rel=1e-8`. Determinístico, preciso.

**SCS:** splitting conic solver, first-order. Mais robusto para problemas mal-condicionados, mas menos preciso. Usado com `eps=1e-5` e `max_iters=10000`.

### 6.7 Tabela de Status do Optimizer

| Status | Significado | Fase | CVaR OK? |
|--------|-------------|------|----------|
| `optimal` | Solução ótima com CVaR dentro do limite | Phase 1 | Sim |
| `optimal:cvar_constrained` | Re-otimizado com teto de variância | Phase 2 | Provável |
| `optimal:min_variance_fallback` | Menor risco possível | Phase 3 | Não garantido |
| `optimal:cvar_violated` | Todas fases falharam, usa Phase 1 | Phase 1 | Não |
| `solver_failed` | CLARABEL e SCS falharam | — | N/A |
| `fallback:insufficient_fund_data` | Sem dados suficientes, heurístico | — | N/A |
| `infeasible: {reason}` | Constraints impossíveis | — | N/A |

---

## 7. CVaR — Conditional Value at Risk

### 7.1 CVaR Parametrizado (Cornish-Fisher)

**Função:** `parametric_cvar_cf()` (`optimizer_service.py`, linha 46)

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

Quando `S ≈ 0` e `K ≈ 0` (fundos sem dados de momentos superiores), reduz para CVaR normal.

### 7.2 CVaR Empírico (Historical Simulation)

**Função:** `compute_cvar_from_returns()` (`backend/quant_engine/cvar_service.py`, linha 95)

Usado pelo worker `risk_calc` para calcular métricas de risco por fundo:

```python
sorted_returns = np.sort(returns)
cutoff_idx = int(len(sorted_returns) * (1 - 0.95))  # bottom 5%
var = sorted_returns[cutoff_idx]                       # VaR: retorno no cutoff
cvar = sorted_returns[:cutoff_idx].mean()              # CVaR: média dos retornos abaixo do VaR
```

Calculado em 4 janelas: 1m (21d), 3m (63d), 6m (126d), 12m (252d).

### 7.3 Convenção de Sinal

- **Valores negativos** representam perda (e.g., `-0.06` = perda de 6%)
- **cvar_limit** é negativo (e.g., `-0.06` para moderate)
- **cvar_within_limit** = `cvar_95 >= cvar_limit` (e.g., `-0.04 >= -0.06` → True)
- **cvar_utilized_pct** = `|cvar_current / cvar_limit| × 100` (e.g., `|-0.04 / -0.06| × 100 = 66.7%`)

---

## 8. Composição do Portfolio

### 8.1 Via Optimizer (`construct_from_optimizer`)

**Arquivo:** `backend/vertical_engines/wealth/model_portfolio/portfolio_builder.py` (linha 35)

Converte o dict `{instrument_id: weight}` do CLARABEL em `PortfolioComposition`:

- Filtra pesos near-zero (`< 1e-6`)
- Enriquece com metadata (fund_name, block_id, manager_score)
- Ordena por block → peso descrescente
- Anexa `OptimizationMeta` com dados do solver

### 8.2 Via Heurístico (`construct`)

**Arquivo:** mesmo, linha 88

Fallback quando optimizer não tem dados suficientes:

1. Agrupa fundos por block
2. Seleciona top-N por `manager_score` em cada block (default N=3)
3. Distribui peso do block proporcionalmente ao score:

```
w_fund = block_weight × (score_fund / sum_scores_in_block)
```

4. Normaliza para sum=1.0

### 8.3 Modelo de Dados

```python
@dataclass(frozen=True, slots=True)
class OptimizationMeta:
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    solver: str                     # "CLARABEL", "SCS", "min_variance_fallback", "heuristic_fallback"
    status: str
    cvar_95: float | None
    cvar_limit: float | None
    cvar_within_limit: bool

@dataclass(frozen=True, slots=True)
class FundWeight:
    instrument_id: uuid.UUID
    fund_name: str
    block_id: str
    weight: float
    score: float

@dataclass(frozen=True, slots=True)
class PortfolioComposition:
    profile: str
    funds: list[FundWeight]
    total_weight: float
    optimization: OptimizationMeta | None
```

---

## 9. Day-0 Snapshot e Documentação de Violação de CVaR

**Função:** `_create_day0_snapshot()` (`model_portfolios.py`, linha 717)

### 9.1 PortfolioSnapshot

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
| `cvar_utilized_pct` | Numeric(6,2) | `\|cvar/limit\| × 100` |
| `trigger_status` | String(20) | `"ok"` \| `"maintenance"` \| `"urgent"` |
| `consecutive_breach_days` | Integer | Dias consecutivos em breach |

### 9.2 Trigger Status Logic

```python
cvar_utilized = abs(cvar_current / cvar_limit) * 100
if cvar_utilized >= 100.0:
    trigger = "urgent"
elif cvar_utilized >= 80.0:
    trigger = "maintenance"
else:
    trigger = "ok"
```

### 9.3 Como a Violação é Documentada

**1. fund_selection_schema (JSONB no ModelPortfolio):**
```json
{
  "optimization": {
    "solver": "min_variance_fallback",
    "status": "optimal:min_variance_fallback",
    "cvar_95": -0.387937,
    "cvar_limit": -0.06,
    "cvar_within_limit": false,
    "sharpe_ratio": 0.7622,
    "expected_return": 0.150742,
    "portfolio_volatility": 0.145292
  }
}
```

**2. PortfolioSnapshot:** `cvar_current`, `cvar_limit`, `cvar_utilized_pct`, `trigger_status`, `consecutive_breach_days`

**3. Monitoring:** `portfolio_eval` worker (lock 900_008) incrementa `consecutive_breach_days` diariamente.

---

## 10. NAV Sintético

**Worker:** `run-portfolio-nav-synthesizer` (lock 900_030)
**Tabela:** `model_portfolio_nav`

NAV_t = NAV_{t-1} × (1 + Σ(w_i × r_i))

Batch upsert de 500 rows, `ON CONFLICT DO UPDATE`. Exemplo real: 501 registros, Day-0 nav=1000.0, último nav=1304.86.

---

## 11. Risk Calc Worker

**Lock ID:** 900_007 | **Tabela:** `fund_risk_metrics`

Métricas: CVaR/VaR (4 janelas), retornos, volatilidade, Sharpe, Sortino, Alpha, Beta, IR, TE, RSI, BB, DTW drift, Manager Score.

---

## 12. Glossário

| Termo | Definição |
|-------|-----------|
| **CLARABEL** | Solver interior-point para problemas conic. Determinístico, preciso a 1e-8. |
| **SCS** | Splitting Conic Solver, first-order. Fallback mais robusto, menos preciso. |
| **CVaR₉₅** | Média das perdas no 5% pior cenário. Negativo = perda. |
| **Cornish-Fisher** | Ajuste do quantil normal para skewness e kurtosis (fat tails). |
| **PSD** | Positive Semi-Definite: propriedade matricial necessária para solvers conic. |
| **Block** | Categoria de alocação (e.g., `na_equity_large`, `fi_us_treasury`). |
| **Trigger Status** | `ok` (<80%), `maintenance` (80-100%), `urgent` (≥100% CVaR). |
