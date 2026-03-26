# Institutional Portfolio Lifecycle — E2E Master Reference

> **Netz Analysis Engine — Wealth OS**
> Documento interno de referencia para o ciclo de vida completo de portfolios institucionais.
> Atualizado em 2026-03-26 | Sprints 1–6 consolidadas | 2800+ testes

---

## Sumario

1. [Fase de Alocacao Preditiva (Ponte 1)](#1-fase-de-alocacao-preditiva-ponte-1)
2. [Fase de Construcao Convexa (Ponte 2)](#2-fase-de-construcao-convexa-ponte-2)
3. [Geracao do Ciclo de Vida: NAV Sintetico (Ponte 3)](#3-geracao-do-ciclo-de-vida-nav-sintetico-ponte-3)
4. [O Sistema Circulatorio (Etapa 6)](#4-o-sistema-circulatorio-etapa-6)
5. [A Saida de Dados (Etapa 7)](#5-a-saida-de-dados-etapa-7)

---

## 1. Fase de Alocacao Preditiva (Ponte 1)

### 1.1 Visao Geral

A Ponte 1 transforma uma visao macroeconomica aprovada pelo CIO em pesos numericos de alocacao. O pipeline implementa uma abordagem inspirada no Black-Litterman onde o "view" do investidor e capturado pela classificacao de regime e traduzido em tilts sobre a alocacao estrategica neutra.

**Cadeia de dados:**

```
MacroRegionalSnapshot (global, FRED+OAS)
    |
    v
MacroReview (org-scoped, status=pending)
    |  POST /macro/reviews/generate
    v
Regime Hierarquico (global + 4 regioes)
    |  PATCH /macro/reviews/{id}/approve
    v
compute_regime_tilted_weights()
    |  Black-Litterman tilt por classe de ativo
    v
StrategicAllocation (org-scoped, effective_from=today)
    |
    v
Otimizador CLARABEL (Ponte 2)
```

### 1.2 Modelo de Dados: MacroReview

**Arquivo:** `backend/app/domains/wealth/models/macro_committee.py`

```python
class MacroReview(IdMixin, OrganizationScopedMixin, AuditMetaMixin, Base):
    __tablename__ = "macro_reviews"

    status: str          # pending | approved | rejected
    is_emergency: bool   # bypass normal approval flow
    as_of_date: date
    snapshot_id: UUID    # FK -> MacroRegionalSnapshot (global)
    report_json: dict    # JSONB — regime + score_deltas + regional data
    approved_by: str | None
    approved_at: datetime | None
    decision_rationale: str | None
```

O campo critico e `report_json`, que embute o regime hierarquico computado no momento da geracao:

```json
{
  "regime": {
    "global": "RISK_OFF",
    "regional": {
      "US": "RISK_OFF",
      "EUROPE": "RISK_ON",
      "ASIA": "RISK_ON",
      "EM": "INFLATION"
    },
    "composition_reasons": {
      "region_us": "US=RISK_OFF (weight=0.25)",
      "decision": "GDP-weighted severity=1.23 -> RISK_OFF"
    }
  },
  "score_deltas": [
    {"region": "US", "previous_score": 55.0, "current_score": 62.5, "delta": 7.5, "flagged": true}
  ],
  "has_material_changes": true
}
```

### 1.3 Pipeline de Deteccao de Regime

**Arquivo:** `backend/quant_engine/regime_service.py`

O regime e detectado em duas camadas: global e regional. Nenhuma API externa e chamada em tempo de request — todos os dados vem da hypertable `macro_data` (pre-ingerida pelo worker `macro_ingestion`, lock ID 43).

#### Regime Global: `classify_regime_multi_signal()`

```python
def classify_regime_multi_signal(
    vix: float | None,
    yield_curve_spread: float | None,
    cpi_yoy: float | None,
    sahm_rule: float | None = None,
    thresholds: RegimeThresholds | None = None,
) -> tuple[str, dict[str, str]]:
```

**Arvore de decisao (prioridade descendente):**

| Prioridade | Condicao            | Regime       |
|-----------|---------------------|--------------|
| 1 (max)   | VIX >= 35           | **CRISIS**   |
| 2         | CPI YoY >= 4.0%     | **INFLATION**|
| 3         | VIX >= 25           | **RISK_OFF** |
| 4 (base)  | Nenhuma das acima   | **RISK_ON**  |

Sinais informativos (nao decisorios): yield curve < -0.10 (inversao), Sahm Rule >= 0.50 (recessao).

#### Regime Regional: `classify_regional_regime()`

Cada regiao usa credit spreads (OAS) como proxy de estresse:

| Regiao  | Series FRED                    | Threshold Risk-Off | Threshold Crisis |
|---------|--------------------------------|-------------------|-----------------|
| US      | VIXCLS + BAMLH0A0HYM2         | 550 bps           | 800 bps         |
| EUROPE  | BAMLHE00EHYIOAS               | 550 bps           | 800 bps         |
| ASIA    | BAMLEMRACRPIASIAOAS            | 550 bps           | 800 bps         |
| EM      | BAMLEMCBPIOAS                  | 550 bps           | 800 bps         |

#### Composicao Global: `compose_global_regime()`

```python
def compose_global_regime(
    regional_regimes: dict[str, str],   # region -> regime
) -> tuple[str, dict[str, str]]:
```

**Regras pessimistas:**
- 2+ regioes em CRISIS -> global CRISIS
- Qualquer regiao com peso GDP >= 0.20 em CRISIS -> global minimo RISK_OFF

**Pesos GDP default:** US: 0.25, EUROPE: 0.22, ASIA: 0.28, EM: 0.25

**Severidade:** RISK_ON=0, RISK_OFF=1, INFLATION=2, CRISIS=3

```
media_ponderada >= 2.5  ->  CRISIS
media_ponderada >= 1.5  ->  INFLATION
media_ponderada >= 0.5  ->  RISK_OFF
caso contrario           ->  RISK_ON
```

### 1.4 Motor de Tilts Black-Litterman

**Arquivo:** `backend/quant_engine/allocation_proposal_service.py`

```python
def compute_regime_tilted_weights(
    profile_name: str,
    strategic_config: dict[str, dict[str, float]],
    global_regime: str,
    regional_scores: dict[str, float] | None = None,
    score_neutral: float = 50.0,
    regional_sensitivity: float = 0.003,
) -> AllocationProposalResult:
```

#### Passo 1: Classificacao de Bloco

Cada `block_id` e classificado por asset class via prefixo:

```python
def _classify_block(block_id: str) -> str:
    # na_equity_*, dm_*_equity, em_equity -> "equity"
    # fi_*                                -> "fi"
    # alt_*                               -> "alt"
    # cash                                -> "cash"
```

#### Passo 2: Tilt de Regime Global

A matriz de tilts define a intensidade do ajuste por classe e regime:

```python
REGIME_TILTS = {
    "RISK_ON":    {"equity_tilt":  0.30, "fi_tilt": -0.15, "alt_tilt":  0.10, "cash_tilt": -0.20},
    "RISK_OFF":   {"equity_tilt": -0.25, "fi_tilt":  0.25, "alt_tilt":  0.05, "cash_tilt":  0.15},
    "INFLATION":  {"equity_tilt": -0.10, "fi_tilt": -0.20, "alt_tilt":  0.30, "cash_tilt":  0.10},
    "CRISIS":     {"equity_tilt": -0.50, "fi_tilt":  0.20, "alt_tilt": -0.10, "cash_tilt":  0.40},
}
```

**Formula do tilt global:**

```
regime_factor = REGIME_TILTS[regime]["{asset_class}_tilt"]

Se regime_factor >= 0:
    room = max_weight - target_weight
    global_delta = regime_factor * room

Se regime_factor < 0:
    room = target_weight - min_weight
    global_delta = regime_factor * room    (negativo)

proposed = target + global_delta
proposed = clamp(min_weight, max_weight)
```

**Exemplo concreto — RISK_ON no bloco `na_equity_large` (moderate):**

```
target = 0.20, min = 0.15, max = 0.28
equity_tilt = 0.30
room = 0.28 - 0.20 = 0.08
global_delta = 0.30 * 0.08 = 0.024
proposed = 0.20 + 0.024 = 0.224
```

#### Passo 3: Tilt Regional (somente equity)

Regional scores afetam APENAS blocos classificados como "equity":

```
score_deviation = regional_score - score_neutral    (ex: 75 - 50 = 25)

Se score_deviation >= 0:
    room_r = max_weight - target_weight
Senao:
    room_r = target_weight - min_weight

regional_delta = score_deviation * regional_sensitivity * room_r
proposed += regional_delta
proposed = clamp(min_weight, max_weight)
```

**Sensibilidade default:** 0.003 (cada ponto acima de 50 adiciona 0.3% do room).

**Mapeamento regiao -> blocos:**

```python
_REGION_TO_BLOCKS = {
    "US":     ["na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small"],
    "EUROPE": ["dm_europe_equity"],
    "ASIA":   ["dm_asia_equity"],
    "EM":     ["em_equity"],
}
```

#### Passo 4: Renormalizacao para soma = 1.0

Apos tiltar todos os blocos, o residual e distribuido:

1. **Cash absorve primeiro:** residual positivo -> cash sobe ate max; negativo -> cash desce ate min
2. **Proporcional no restante:** o que cash nao absorveu e distribuido proporcionalmente entre blocos com room disponivel

### 1.5 Persistencia

Quando o CIO aprova o `MacroReview`:

```python
# Expirar alocacoes anteriores do tipo macro_proposal
old_rows.effective_to = today

# Inserir novas propostas
StrategicAllocation(
    profile=profile_name,
    block_id=bp.block_id,
    target_weight=Decimal(str(bp.proposed_weight)),
    min_weight=Decimal(str(bp.min_weight)),
    max_weight=Decimal(str(bp.max_weight)),
    rationale=proposal.rationale,
    approved_by=actor_id,
    effective_from=today,
    actor_source="macro_proposal",   # identifica origem
)
```

O campo `actor_source='macro_proposal'` permite expirar seletivamente quando novos regimes viram.

### 1.6 Invariantes Criticos

1. **Zero chamadas de API externas** no path de alocacao — todos os dados FRED vem da hypertable pre-ingerida
2. **Funcoes sync-only** — `compute_regime_tilted_weights()` e puro sync, sem I/O
3. **Todos os pesos bounded** — [min, max] respeitado mesmo antes da renormalizacao
4. **Tilts regionais equity-only** — FI, alt, cash NAO sao afetados por scores regionais
5. **Precisao Decimal(6,4)** — 4 casas decimais em todos os pesos para evitar acumulo de floating-point
6. **Time-versioning** — alocacoes antigas expiradas via `effective_to = today`; queries sempre filtram `effective_from <= today AND (effective_to IS NULL OR effective_to >= today)`

---

## 2. Fase de Construcao Convexa (Ponte 2)

### 2.1 Visao Geral

A Ponte 2 recebe os pesos de bloco da Ponte 1 e resolve a alocacao **por fundo individual** usando o solver conico CLARABEL. O otimizador opera em nivel de fundo (nao de bloco), respeitando constraints de grupo que forcam os somatarios de bloco a cair dentro dos limites da alocacao estrategica.

**Cadeia:**

```
StrategicAllocation (block min/max)
    +
ApprovedUniverse (fund_ids, manager_scores)
    +
NavTimeseries (daily returns -> covariance matrix)
    |
    v
optimize_fund_portfolio()     <-- CLARABEL 3-phase cascade
    |
    v
fund_selection_schema (JSONB no ModelPortfolio)
    |
    v
Day-0 PortfolioSnapshot (CVaR baseline, trigger_status)
```

### 2.2 Assinatura do Otimizador

**Arquivo:** `backend/quant_engine/optimizer_service.py`

```python
async def optimize_fund_portfolio(
    fund_ids: list[str],
    fund_blocks: dict[str, str],           # fund_id -> block_id
    expected_returns: dict[str, float],     # fund_id -> E[r] anualizado
    cov_matrix: np.ndarray,                # NxN covariancia anualizada
    constraints: ProfileConstraints,        # blocks, cvar_limit, max_single_fund
    risk_free_rate: float = 0.04,
) -> FundOptimizationResult:
```

**ProfileConstraints:**

```python
@dataclass
class ProfileConstraints:
    blocks: list[BlockConstraint]     # [(block_id, min_weight, max_weight)]
    cvar_limit: float                 # ex: -0.08 (perda maxima 8% a 95%)
    max_single_fund_weight: float     # ex: 0.15 (concentracao)
```

**FundOptimizationResult:**

```python
@dataclass
class FundOptimizationResult:
    weights: dict[str, float]          # {fund_id: peso}
    block_weights: dict[str, float]    # {block_id: soma}
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    cvar_95: float | None
    cvar_limit: float | None
    cvar_within_limit: bool
    status: str                        # ver tabela abaixo
    solver_info: str | None            # "CLARABEL" | "SCS" | "min_variance_fallback"
```

### 2.3 A Cascata de 3 Fases

O otimizador implementa um fallback deterministico para garantir que o CVaR nunca seja violado sem controle:

```
Phase 1: Max Risk-Adjusted Return
    |
    | CVaR violado?
    v
Phase 2: Variance Ceiling (sigma_max = |cvar_limit| / 3.71)
    |
    | Infeasivel?
    v
Phase 3: Minimum Variance Fallback
    |
    | Todos falharam?
    v
Return Phase 1 com flag cvar_violated
```

#### Phase 1: Maximum Risk-Adjusted Return

**Objetivo:** Maximizar `mu^T * w - lambda * w^T * Sigma * w`

```python
w1 = cp.Variable(n, nonneg=True)
risk_aversion = 2.0

prob1 = cp.Problem(
    cp.Maximize(mu @ w1 - risk_aversion * cp.quad_form(w1, psd_cov)),
    _build_base_constraints(w1),
)
```

**Constraints base (compartilhadas entre as 3 fases):**

```
sum(w) == 1                                # fully invested
w[i] >= 0                                  # long-only
w[i] <= max_single_fund_weight             # concentracao por fundo
sum(w[funds in block]) >= block.min_weight # piso de bloco
sum(w[funds in block]) <= block.max_weight # teto de bloco
```

**Apos a solucao:** calcula CVaR parametrico via Cornish-Fisher. Se `cvar_95 >= cvar_limit`, retorna. Caso contrario, cascata para Phase 2.

#### Phase 2: Variance Ceiling (A Derivacao Genial)

**Trigger:** Phase 1 resolveu com sucesso MAS violou o limite de CVaR.

**O problema:** CVaR nao e diretamente convexo como constraint no cvxpy sem second-order cone reformulation. A solucao elegante: converter o limite de CVaR em um teto de variancia, que E convexo (`cp.quad_form`).

**Derivacao matematica do `sigma_max`:**

O CVaR parametrico para distribuicao normal a 95% de confianca e:

$$\text{CVaR}_{95\%} = -\mu_p - \sigma_p \cdot \left[ z_\alpha + \frac{\phi(z_\alpha)}{\alpha} \right]$$

Onde:
- `z_alpha = PPF(0.05) = -1.6449` (quantil 5%)
- `phi(z_alpha) = PDF(-1.6449) = 0.10317`
- `alpha = 0.05`

Calculando o coeficiente:

```
cvar_coeff = -z_alpha + phi(z_alpha) / alpha
           = -(-1.6449) + 0.10317 / 0.05
           = 1.6449 + 2.0634
           = 3.7083
           ~ 3.71
```

**Portanto, para manter CVaR dentro do limite assumindo mu ~ 0:**

$$\sigma_{\text{max}} = \frac{|\text{cvar\_limit}|}{\text{cvar\_coeff}} = \frac{|\text{cvar\_limit}|}{3.71}$$

$$\sigma^2_{\text{max}} = \left(\frac{|\text{cvar\_limit}|}{3.71}\right)^2$$

**Codigo exato:**

```python
from scipy.stats import norm as sp_norm

z_alpha = sp_norm.ppf(0.05)             # -1.6449
phi_z = sp_norm.pdf(z_alpha)            # 0.10317
cvar_coeff = -z_alpha + phi_z / 0.05    # 3.7083
max_var = (abs(cvar_limit) / cvar_coeff) ** 2
```

**Exemplo numerico:**

```
cvar_limit = -0.08 (8% de perda maxima)
sigma_max = 0.08 / 3.71 = 0.02156
sigma^2_max = 0.000465
```

**Otimizacao Phase 2:**

```python
w2 = cp.Variable(n, nonneg=True)
constraints2 = _build_base_constraints(w2)
constraints2.append(cp.quad_form(w2, psd_cov) <= max_var)   # NOVO: teto de variancia

prob2 = cp.Problem(cp.Maximize(mu @ w2), constraints2)
```

- **Objetivo:** Maximizar retorno esperado `mu^T * w` (sem penalidade de risco — a variancia ja esta limitada)
- **Constraint extra:** `w^T * Sigma * w <= sigma^2_max`
- **Propriedade-chave:** `cp.quad_form` e convexo, entao CLARABEL resolve sem heuristica
- **Status de saida:** `"optimal:cvar_constrained"`

#### Phase 3: Minimum Variance Fallback

**Trigger:** Phase 2 infeasivel (nenhuma alocacao satisfaz o teto de variancia com as constraints de bloco).

```python
w3 = cp.Variable(n, nonneg=True)
prob3 = cp.Problem(
    cp.Minimize(cp.quad_form(w3, psd_cov)),   # minimizar variancia
    _build_base_constraints(w3),
)
```

- **Objetivo:** Encontrar a alocacao de menor volatilidade que satisfaz as constraints de bloco/concentracao
- **Sem teto de CVaR** — aceita o melhor possivel
- **Status de saida:** `"optimal:min_variance_fallback"`

#### Fallback Terminal

Se todas as 3 fases falharem: retorna pesos da Phase 1 com `status="optimal:cvar_violated"` e `cvar_within_limit=False`. O sistema **nao levanta excecao** — degradacao graciosa.

### 2.4 Tabela de Status do Otimizador

| Status                         | Descricao                                         |
|-------------------------------|---------------------------------------------------|
| `optimal`                      | Phase 1 resolveu E CVaR dentro do limite          |
| `optimal:cvar_constrained`     | Phase 2 resolveu com teto de variancia            |
| `optimal:min_variance_fallback`| Phase 3 — menor variancia possivel                |
| `optimal:cvar_violated`        | Todas falharam; Phase 1 retornada com flag        |
| `solver_failed`                | CLARABEL + SCS ambos falharam                     |
| `fallback:insufficient_fund_data` | <120 dias de NAV; heuristica proporcional usada|

### 2.5 CVaR Parametrico Cornish-Fisher

**Arquivo:** `backend/quant_engine/optimizer_service.py`

```python
def parametric_cvar_cf(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    skewness: np.ndarray,
    excess_kurtosis: np.ndarray,
    alpha: float = 0.05,
) -> float:
```

**Formula (Cornish-Fisher ajustada para fat tails):**

```
z = PPF(alpha)                                          # -1.6449
z_cf = z
     + (z^2 - 1) * skewness / 6                        # ajuste de assimetria
     + (z^3 - 3z) * kurtosis / 24                       # ajuste de curtose
     - (2z^3 - 5z) * skewness^2 / 36                    # correcao cruzada

CVaR = -(mu_p + sigma_p * z_cf) + sigma_p * phi(z_cf) / alpha
```

Retorna **perda positiva** (quanto maior, pior). Para distribuicao normal (skew=0, kurt=0), simplifica para `CVaR = sigma * 3.71 - mu`.

### 2.6 Solver: CLARABEL -> SCS Fallback

```python
async def _solve_problem(prob: cp.Problem) -> str | None:
    def _do():
        try:
            prob.solve(solver=cp.CLARABEL, verbose=False)
        except cp.SolverError:
            try:
                prob.solve(solver=cp.SCS, verbose=False)
            except cp.SolverError:
                pass
    await asyncio.to_thread(_do)
    return prob.status
```

- **CLARABEL:** Solver conico interior-point, tipicamente 50-200ms
- **SCS:** Fallback ADMM, mais lento mas robusto
- `asyncio.to_thread` evita bloquear o event loop

### 2.7 De NAV para Covariance Matrix

**Arquivo:** `backend/app/domains/wealth/services/quant_queries.py`

```python
async def compute_fund_level_inputs(
    db: AsyncSession, fund_ids: list[uuid.UUID]
) -> tuple[np.ndarray, dict[str, float], list[str]]:
```

1. Query `NavTimeseries.return_1d` para todos os fundos (lookback 252 dias)
2. Intersecao de datas (alinhamento cross-fund)
3. Minimo 120 observacoes alinhadas
4. `Cov_annual = Cov_daily * 252`
5. **Ajuste PSD:** eigenvalues negativos floored em 1e-10 (obrigatorio para CLARABEL)
6. `E[r]_annual = mean(r_daily) * 252`

### 2.8 Schema de Saida: fund_selection_schema

Persistido como JSONB em `ModelPortfolio.fund_selection_schema`:

```json
{
  "profile": "moderate",
  "total_weight": 0.999999,
  "funds": [
    {
      "instrument_id": "550e8400-...",
      "fund_name": "Vanguard Total Stock Market ETF",
      "block_id": "na_equity_large",
      "weight": 0.1500,
      "score": 85.5
    }
  ],
  "optimization": {
    "expected_return": 0.0654,
    "portfolio_volatility": 0.0877,
    "sharpe_ratio": 0.5234,
    "solver": "CLARABEL",
    "status": "optimal",
    "cvar_95": -0.0654,
    "cvar_limit": -0.0800,
    "cvar_within_limit": true
  }
}
```

### 2.9 Day-0 Snapshot

Apos a construcao, `_create_day0_snapshot()` cria o primeiro `PortfolioSnapshot`:

```python
PortfolioSnapshot(
    profile=portfolio.profile,
    snapshot_date=date.today(),
    weights=block_weights,             # agregacao bloco-nivel
    fund_selection=fund_selection,     # detalhe fundo-nivel
    cvar_current=cvar_from_optimizer,
    cvar_limit=cvar_limit,
    cvar_utilized_pct=abs(cvar/limit)*100,
    trigger_status="ok",               # ok | maintenance | urgent
    consecutive_breach_days=0,
)
```

Este snapshot e o ponto de partida para o monitoring engine (`portfolio_eval` worker, lock 900_008) que roda diariamente.

---

## 3. Geracao do Ciclo de Vida: NAV Sintetico (Ponte 3)

### 3.1 Visao Geral

A Ponte 3 resolve um problema fundamental: como tratar um portfolio modelo (que nao existe como fundo listado) como uma entidade de primeira classe para analytics, charts e comparacoes? A resposta e um **NAV sintetico** computado diariamente a partir dos retornos ponderados dos fundos componentes, armazenado numa hypertable identica em schema a `nav_timeseries`.

### 3.2 O Sintetizador: `portfolio_nav_synthesizer.py`

**Arquivo:** `backend/app/domains/wealth/workers/portfolio_nav_synthesizer.py`
**Lock ID:** 900_030

```python
async def synthesize_portfolio_nav(
    db: AsyncSession,
    portfolio: ModelPortfolio,
) -> dict[str, Any]:
```

**Algoritmo de composicao ponderada:**

```
NAV_0 = inception_nav (default 1000.0)

Para cada dia t com dados de retorno:
    R_t = SUM(w_i * r_i_t)    para cada fundo i com retorno disponivel

    Se active_weight < weight_sum * 0.999:
        R_t *= (weight_sum / active_weight)    # renormalizacao por fundo faltante

    NAV_t = NAV_{t-1} * (1 + R_t)
```

**Detalhes criticos:**

1. **Extracao de pesos:** `fund_selection_schema.funds -> {instrument_id: weight}`
2. **Incrementalidade:** Busca `last_nav_date` existente; sintetiza apenas a partir de `last_date + 1`
3. **Reconstrucao completa:** Se nenhum NAV existe, reconstroi desde `backtest_start_date` ou `inception_date` (max 1260 dias = 5 anos)
4. **Day-0 insertion:** Insere row com `nav=inception_nav, daily_return=None` no dia anterior ao primeiro retorno
5. **Batch upsert:** 500 rows por batch, `ON CONFLICT DO UPDATE` em (portfolio_id, nav_date)
6. **Renormalizacao por fundo faltante:** Se um fundo nao tem retorno para um dia, o retorno do portfolio e escalado proporcionalmente ao peso ativo

### 3.3 Duck Typing: As Duas Tabelas NAV

**ModelPortfolioNav** (`backend/app/domains/wealth/models/model_portfolio_nav.py`):

```python
class ModelPortfolioNav(OrganizationScopedMixin, Base):
    __tablename__ = "model_portfolio_nav"

    portfolio_id: UUID    = PK, FK -> model_portfolios.id
    nav_date: date        = PK
    nav: Decimal(18, 6)
    daily_return: Decimal(12, 8) | None
    organization_id: UUID
```

**NavTimeseries** (`backend/app/domains/wealth/models/nav.py`):

```python
class NavTimeseries(OrganizationScopedMixin, Base):
    __tablename__ = "nav_timeseries"

    instrument_id: UUID   = PK, FK -> instruments_universe.instrument_id
    nav_date: date        = PK
    nav: Decimal(18, 6) | None
    return_1d: Decimal(12, 8) | None    # <-- nota: nome diferente de daily_return
    aum_usd: Decimal(18, 2) | None
    currency: str(3) | None
    source: str(30) | None
```

**O Duck Typing:** Ambas as tabelas tem:
- Composite PK: (entity_id, nav_date)
- `nav` Decimal(18, 6)
- Coluna de retorno diario (nomes diferentes: `daily_return` vs `return_1d`)

O `NavRow` normaliza a diferenca:

```python
@dataclass(frozen=True, slots=True)
class NavRow:
    entity_id: uuid.UUID     # portfolio_id OU instrument_id
    nav_date: date
    nav: float
    daily_return: float | None
```

### 3.4 O Polimorfismo Arquitetural: `nav_reader.py`

**Arquivo:** `backend/app/domains/wealth/services/nav_reader.py`

Este e o **pilar central** da arquitetura de Ponte 3. Todo codigo que precisa de series NAV DEVE usar `nav_reader` — nunca importar `NavTimeseries` ou `ModelPortfolioNav` diretamente.

```python
async def fetch_nav_series(
    db: AsyncSession,
    entity_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[NavRow]:
```

**Fluxo interno:**

```
1. is_portfolio = await is_model_portfolio(db, entity_id)
       |
       |-- SELECT ModelPortfolio.id WHERE id = entity_id LIMIT 1
       |-- True se encontrado
       |
2. Se is_portfolio:
       SELECT portfolio_id, nav_date, nav, daily_return
       FROM model_portfolio_nav
       WHERE portfolio_id = entity_id

   Senao:
       SELECT instrument_id, nav_date, nav, return_1d
       FROM nav_timeseries
       WHERE instrument_id = entity_id

3. Normalizar para list[NavRow]
```

**Variantes disponiveis:**

| Funcao                     | Contexto           | Retorno              |
|----------------------------|--------------------|----------------------|
| `fetch_nav_series()`       | async (routes)     | `list[NavRow]`       |
| `fetch_nav_series_sync()`  | sync (to_thread)   | `list[NavRow]`       |
| `fetch_returns_only()`     | async (CVaR, etc)  | `list[float]`        |
| `is_model_portfolio()`     | async              | `bool`               |
| `is_model_portfolio_sync()`| sync               | `bool`               |

### 3.5 Por Que Todo Novo Codigo DEVE Usar nav_reader

1. **Transparencia de tipo:** Routes e engines nao precisam saber se estao analisando um fundo ou portfolio
2. **Unica fonte de verdade:** Mudancas no schema de NAV afetam apenas o nav_reader, nao os 20+ consumidores
3. **RLS automatico:** Ambas as tabelas sao org-scoped; o nav_reader herda o contexto RLS da session
4. **Extensibilidade:** Novos tipos de entidade (ex: blended benchmark) podem ser adicionados ao nav_reader sem alterar nenhum consumidor
5. **Fronteira SOLID:** O nav_reader e o **unico ponto de acoplamento** entre a camada de dados NAV e o restante do sistema

**Regra do CLAUDE.md:** "Routes and vertical engines NEVER import NavTimeseries directly. All NAV access goes through nav_reader."

### 3.6 Resolucao de Benchmark: 3 Tiers

**Arquivo:** `backend/app/domains/wealth/routes/entity_analytics.py`

Quando o endpoint `/analytics/entity/{entity_id}` precisa de um benchmark para comparacao:

```
Tier 1: benchmark_id explicito (query param)
    |-- Usa nav_reader polymorphic (fundo OU portfolio como benchmark)
    |-- Retorna: source="param"
    v (se null ou sem dados)

Tier 2: AllocationBlock.benchmark_ticker da entidade
    |-- Query benchmark_nav hypertable (GLOBAL, sem RLS)
    |-- Retorna: source="block"
    v (se block_id null ou sem ticker)

Tier 3: SPY fallback
    |-- Busca qualquer block com benchmark_ticker='SPY'
    |-- Query benchmark_nav do bloco SPY
    |-- Retorna: source="spy_fallback"
    v (se nada encontrado)

    Retorna: {}, "spy_fallback", "SPY"
```

### 3.7 Entity Analytics: A Vitrine de 5 Metricas

O endpoint `GET /analytics/entity/{entity_id}` retorna 5 grupos de metricas institucionais, funcionando **identicamente** para fundos e portfolios modelo gracas ao polimorfismo do nav_reader:

| Grupo                | Fonte Quant                              | Metricas Principais                          |
|----------------------|------------------------------------------|---------------------------------------------|
| Risk Statistics      | `portfolio_metrics_service.aggregate()`  | Sharpe, Sortino, Calmar, Alpha, Beta, TE, IR|
| Drawdown Analysis    | `drawdown_service.analyze_drawdowns()`   | Serie, max, current, top 5 periods          |
| Capture Ratios       | Custom monthly aggregation               | Up/down capture, number ratios              |
| Rolling Returns      | `rolling_service.compute_rolling_returns()`| 1M, 3M, 6M, 1Y annualized                |
| Return Distribution  | Custom + `cvar_service`                  | Histogram, skew, kurtosis, VaR, CVaR       |

---

## 4. O Sistema Circulatorio (Etapa 6)

### 4.1 Visao Geral

A Etapa 6 implementa o "sistema circulatorio" que circula informacao de holdings entre os fundos de um portfolio modelo, detectando riscos ocultos de concentracao que nao sao visiveis no nivel de bloco. O mecanismo: explodir cada fundo ate suas holdings individuais via dados N-PORT do SEC, e cruzar CUSIPs e setores GICS entre todos os fundos.

**Cadeia:**

```
ModelPortfolio.fund_selection_schema
    |
    v
HoldingsExploder (I/O)
    |-- Instrument.attributes.sec_cik
    |-- sec_nport_holdings (GLOBAL, sem RLS)
    v
list[HoldingRow]  (fund_weight * pct_of_fund_nav)
    |
    v
OverlapScanner (pure math, zero I/O)
    |
    v
OverlapResult
    |-- cusip_exposures (agregacao CUSIP cross-fund)
    |-- sector_exposures (agregacao GICS)
    |-- breaches (CUSIP > limit_pct)
```

### 4.2 Holdings Exploder: Camada I/O

**Arquivo:** `backend/app/domains/wealth/services/holdings_exploder.py`

```python
async def fetch_portfolio_holdings_exploded(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> list[HoldingRow]:
```

**4 estagios de processamento:**

**Estagio 1: Extrair pesos do portfolio**

```python
funds = portfolio.fund_selection_schema.get("funds", [])
fund_weights = {UUID(f["instrument_id"]): f["weight"] for f in funds}
```

**Estagio 2: Resolver CIK de cada fundo**

```python
# Query Instrument.attributes (JSONB) para sec_cik
instrument_to_cik = {row.instrument_id: row.attributes["sec_cik"] for row in ...}
```

O `sec_cik` vive dentro do JSONB `attributes` de cada instrumento — o link entre o universo de fundos do Netz e o universo SEC.

**Estagio 3: Query N-PORT mais recente por CIK**

```sql
-- Subquery: data mais recente por CIK
SELECT cik, MAX(report_date) as max_date
FROM sec_nport_holdings
WHERE cik IN (:cik_list)
GROUP BY cik

-- Join: holdings da data mais recente
SELECT cik, cusip, issuer_name, sector, pct_of_nav
FROM sec_nport_holdings
JOIN latest_dates ON (cik, report_date) = (cik, max_date)
```

**Propriedade critica:** `sec_nport_holdings` e uma tabela **GLOBAL** (sem `organization_id`, sem RLS). Diferentes fundos podem ter datas de filing diferentes — a subquery resolve a data mais recente por fundo.

**Estagio 4: Ponderar cada holding**

```python
HoldingRow(
    cusip=h.cusip,
    issuer_name=h.issuer_name,
    sector=h.sector,                           # GICS sector
    fund_instrument_id=instrument_id,
    fund_weight=fund_w,                        # ex: 0.40 (40% do portfolio)
    pct_of_fund_nav=pct,                       # ex: 5.0 (5% do NAV do fundo)
    weighted_pct=fund_w * (pct / 100.0),       # ex: 0.02 (2% do portfolio total)
)
```

### 4.3 Overlap Scanner: Camada de Matematica Pura

**Arquivo:** `backend/vertical_engines/wealth/monitoring/overlap_scanner.py`

```python
def compute_overlap(
    holdings: list[HoldingRow],
    limit_pct: float = 0.05,      # 5% default
) -> OverlapResult:
```

**Zero I/O. Zero imports de DB. Recebe dados, retorna resultado.**

#### Nivel 1: Consolidacao CUSIP (Cross-Fund)

Para cada CUSIP, soma o `weighted_pct` de todos os fundos que detem aquela posicao:

```python
cusip_agg = {}
for h in holdings:
    entry = cusip_agg.setdefault(h.cusip, {"total": 0.0, "funds": set()})
    entry["total"] += h.weighted_pct
    entry["funds"].add(str(h.fund_instrument_id))

# Breach: CUSIP com exposicao > limit_pct (5%)
breach = entry["total"] > limit_pct
```

**Exemplo:** Se Fund A (40% do portfolio) tem 8% em AAPL, e Fund B (30% do portfolio) tem 5% em AAPL:

```
weighted_pct_A = 0.40 * 0.08 = 0.032
weighted_pct_B = 0.30 * 0.05 = 0.015
total AAPL = 0.047 (4.7% do portfolio)
breach? 0.047 < 0.05 -> False (mas proximo do limite!)
```

#### Nivel 2: Consolidacao GICS Sector

```python
sector_agg = {}
for h in holdings:
    sector = h.sector or "Unknown"
    entry = sector_agg.setdefault(sector, {"total": 0.0, "cusips": set()})
    entry["total"] += h.weighted_pct
    entry["cusips"].add(h.cusip)
```

#### Resultado Final

```python
@dataclass(frozen=True, slots=True)
class OverlapResult:
    cusip_exposures: tuple[CusipExposure, ...]    # sorted desc by exposure
    sector_exposures: tuple[SectorExposure, ...]  # sorted desc by exposure
    breaches: tuple[CusipExposure, ...]           # somente CUSIP > limit
    limit_pct: float
    total_holdings: int
```

### 4.4 Invariantes de Fronteira

1. **HoldingsExploder faz I/O, OverlapScanner nao** — separacao estrita entre camada de acesso a dados e logica pura
2. **sec_nport_holdings e GLOBAL** — sem RLS, sem organization_id. Os dados N-PORT sao publicos (SEC)
3. **Instrument e RLS-scoped** — apenas instrumentos do tenant sao resolvidos para CIK
4. **Nenhum endpoint expoe matematica em linha** — o overlap scanner e chamado pelo engine, nao por uma rota diretamente
5. **Dados de holdings sao snapshot-in-time** — usam o filing N-PORT mais recente, nao uma composicao real-time

---

## 5. A Saida de Dados (Etapa 7)

### 5.1 Visao Geral

A Etapa 7 constroi o ciclo de reporting institucional que entrega os resultados das Pontes 1-3 e Etapa 6 em formatos consumiveis por clientes. Dois engines coexistem:

| Engine               | Publico-Alvo          | Canais    | Capitulos |
|---------------------|----------------------|-----------|-----------|
| FactSheetEngine     | Prospects (marketing)| PDF       | Exec (2pg) + Institucional (6pg) |
| LongFormReportEngine| Clientes existentes  | SSE + JSON| 8 capitulos paralelos |

### 5.2 LongFormReportEngine: 8 Capitulos com asyncio.gather

**Arquivo:** `backend/vertical_engines/wealth/long_form_report/long_form_report_engine.py`

```python
class LongFormReportEngine:
    async def generate(
        self,
        db: AsyncSession,
        *,
        portfolio_id: str,
        organization_id: str,
        as_of: date | None = None,
    ) -> LongFormReportResult:
```

#### Orquestracao Paralela

```python
# Pre-load: dados compartilhados entre capitulos (1 query batch)
context = await self._load_context(db, pid, organization_id, as_of)

# Gerar 8 capitulos em paralelo
tasks = [
    self._generate_chapter(ch["tag"], ch["order"], ch["title"], context, db)
    for ch in CHAPTER_REGISTRY
]
chapters = await asyncio.gather(*tasks)
```

`asyncio.gather` executa os 8 handlers concorrentemente. Cada handler e **isolado** — a falha de um nao afeta os demais.

#### Os 8 Capitulos

| # | Tag                      | Fonte de Dados                                    |
|---|--------------------------|--------------------------------------------------|
| 1 | macro_context            | MacroReview aprovado mais recente (RLS)           |
| 2 | strategic_allocation     | StrategicAllocation vigente + rationale (RLS)     |
| 3 | portfolio_composition    | PortfolioSnapshot atual vs anterior (delta pesos) |
| 4 | performance_attribution  | `attribution/service.py` — Brinson-Fachler        |
| 5 | risk_decomposition       | `cvar_service.py` — CVaR por bloco                |
| 6 | fee_analysis             | `fee_drag/service.py` — fee drag ratio            |
| 7 | per_fund_highlights      | Top movers, newcomers, exits vs snapshot anterior  |
| 8 | forward_outlook          | WealthContent(type="investment_outlook", approved) |

#### Pattern Never-Raises

```python
async def _generate_chapter(self, tag, order, title, context, db) -> ChapterResult:
    try:
        handler = getattr(self, f"_chapter_{tag}", None)
        if handler is None:
            return ChapterResult(tag=tag, ..., status="failed", confidence=0.0)
        content = await handler(context, db)
        return ChapterResult(tag=tag, ..., content=content, status="completed", confidence=1.0)
    except Exception as exc:
        logger.warning("long_form_chapter_failed", chapter=tag, error=str(exc))
        return ChapterResult(tag=tag, ..., status="failed", confidence=0.0, error=str(exc))
```

**Garantia:** O `generate()` principal tambem e wrapped em try/except. O resultado SEMPRE retorna `LongFormReportResult`, mesmo em falha total (`status="failed"`).

**Rollup de status:**
- Todos 8 completos -> `"completed"`
- Alguns falharam -> `"partial"`
- Falha no pre-load -> `"failed"`

#### Capitulo 4: Attribution (Brinson-Fachler)

O capitulo 4 invoca o engine existente `vertical_engines/wealth/attribution/service.py` que implementa a decomposicao de retorno **Policy Benchmark** (padrao CFA CIPM):

```python
# Formulas Brinson-Fachler:
Allocation Effect = (w_p_i - w_b_i) * (r_b_i - R_b)    # Fachler adjustment
Selection Effect  = w_b_i * (r_p_i - r_b_i)
Interaction Effect= (w_p_i - w_b_i) * (r_p_i - r_b_i)
```

Onde:
- `w_p_i`: peso do portfolio no bloco i
- `w_b_i`: peso do benchmark (alocacao estrategica)
- `r_p_i`: retorno do portfolio no bloco i
- `r_b_i`: retorno do benchmark no bloco i
- `R_b`: retorno total do benchmark

Multi-period linking via **Carino (1999)** com clamp em `|k_t| <= 10.0` e fallback para media simples quando excess total ~ 0.

#### Capitulo 6: Fee Drag

Invoca `vertical_engines/wealth/fee_drag/service.py`:

```python
FeeDragService.compute_portfolio_fee_drag(
    instruments=[{instrument_id, name, instrument_type, attributes}],
    weights={instrument_id: weight},
)
```

**Fee drag ratio:** `total_fee_pct / gross_expected_return` (fracao do retorno consumida por taxas).
**Threshold default:** 0.50 (instrumento e "ineficiente" se > 50% do retorno bruto vai para taxas).

### 5.3 FactSheetEngine: Modo Institucional com Attribution + Fee Drag

**Arquivo:** `backend/vertical_engines/wealth/fact_sheet/fact_sheet_engine.py`

O FactSheetEngine no modo `format="institutional"` agora inclui 2 secoes adicionais:

```python
if format == "institutional":
    attribution = self._compute_attribution(db, pid, funds_data, block_weights)
    fee_drag_data = self._compute_fee_drag(funds_data, block_weights)
```

Ambas secoes sao **opcionais** (None/[] se dados insuficientes) e nunca levantam excecao:

```python
def _compute_attribution(self, db, portfolio_id, funds_data, block_weights) -> list[AttributionRow]:
    try:
        # Resolve benchmark via benchmark_resolver
        # Computa retornos por bloco
        # Invoca AttributionService
        return [AttributionRow(...) for s in result.sectors]
    except Exception:
        logger.warning("fact_sheet_attribution_failed", exc_info=True)
        return []
```

### 5.4 Benchmark Composite NAV

**Arquivo:** `backend/quant_engine/benchmark_composite_service.py`

Analogo ao portfolio_nav_synthesizer, mas para benchmarks compostos:

```python
def compute_composite_nav(
    block_weights: dict[str, float],
    benchmark_navs: dict[str, list[dict[str, Any]]],
    inception_nav: float = 1000.0,
) -> list[NavRow]:
```

**Algoritmo identico ao sintetizador de portfolio:**

```
NAV_0 = inception_nav
R_t = SUM(w_block * r_benchmark_block_t)
# Renormalizacao se bloco faltante
NAV_t = NAV_{t-1} * (1 + R_t)
```

A camada I/O vive em `benchmark_resolver.py`:

```python
async def fetch_benchmark_nav_series(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> tuple[dict[str, float], dict[str, list[dict]]]:
    # 1. Load portfolio -> profile
    # 2. Query StrategicAllocation -> block_ids + target_weights
    # 3. Query AllocationBlock -> benchmark_tickers (GLOBAL, no RLS)
    # 4. Query benchmark_nav hypertable por bloco (GLOBAL, no RLS)
    # Returns: (block_weights, benchmark_navs)
```

### 5.5 Rota SSE para Long-Form Report

**Arquivo:** `backend/app/domains/wealth/routes/long_form_reports.py`

```
POST /reporting/model-portfolios/{portfolio_id}/long-form-report
  -> 202 ACCEPTED + { job_id, portfolio_id }

GET  /reporting/model-portfolios/{portfolio_id}/long-form-report/stream/{job_id}
  -> SSE EventSourceResponse
```

**Controle de concorrencia:**

```python
_lfr_semaphore: asyncio.Semaphore | None = None   # lazy (regra CLAUDE.md)
_MAX_CONCURRENT = 2

# Tenta adquirir sem blocking
await asyncio.wait_for(sem.acquire(), timeout=0)
# Se ocupado: HTTP 429 Too Many Requests
```

**Fluxo SSE:**

```
Frontend                          Backend                         Redis
   |                                |                               |
   |-- POST /long-form-report ---->|                               |
   |                                |-- register_job_owner ------->|
   |<-- 202 { job_id } ------------|                               |
   |                                |-- asyncio.create_task ------>|
   |                                |                               |
   |-- GET /stream/{job_id} ------>|-- subscribe(job_id) -------->|
   |                                |                               |
   |                                | (background task running)     |
   |                                |-- publish "started" -------->|
   |<---- SSE: event=started ------|<-----------------------------|
   |                                |                               |
   |                                |-- publish "chapter_complete" |
   |<---- SSE: event=chapter_1 ----|<-----------------------------|
   |<---- SSE: event=chapter_2 ----|                               |
   |          ...                   |                               |
   |                                |-- publish_terminal "done" -->|
   |<---- SSE: event=done ---------|<-----------------------------|
```

**Frontend usa `fetch()` + `ReadableStream`** (NAO `EventSource`) para poder enviar headers de autenticacao:

```javascript
const response = await fetch(`/api/v1/reporting/.../stream/${jobId}`, {
    headers: { Authorization: `Bearer ${token}` }
});
const reader = response.body.getReader();
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = new TextDecoder().decode(value);
    // Parse SSE: "event: chapter_complete\ndata: {...}\n\n"
}
```

### 5.6 Renderizacao PDF: Institutional Renderer

**Arquivo:** `backend/vertical_engines/wealth/fact_sheet/institutional_renderer.py`

O renderer institucional produz um PDF de 4-6 paginas via ReportLab Platypus:

| Pagina | Conteudo                                                |
|--------|--------------------------------------------------------|
| 1      | Cover + NAV chart + Returns table (MTD/QTD/YTD/1Y/3Y) |
| 2      | Allocation pie + Top 10 holdings + Risk metrics         |
| 3      | **Attribution analysis** (Brinson 5-column table)       |
| 3-4    | Regime overlay chart + Stress scenarios table            |
| 4-5    | **Fee drag analysis** (summary table)                   |
| 5-6    | ESG placeholder + Disclaimer                            |

Charts renderizados em paralelo via `ThreadPoolExecutor(max_workers=4)`:

```python
with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
    futures = {name: pool.submit(fn) for name, fn in tasks.items()}
    for name, future in futures.items():
        try:
            charts[name] = future.result()
        except Exception:
            logger.warning("chart_render_failed", chart=name, exc_info=True)
```

### 5.7 i18n: Labels Bilingues

Todos os labels de PDF sao servidos via `LABELS[language]` em `i18n.py` — nenhum string hardcoded nos renderers. Suporte PT/EN completo para todas as secoes incluindo as novas (Fee Drag Analysis).

---

## Apendice A: Mapa de Arquivos

### Ponte 1 — Alocacao Preditiva

| Arquivo | Responsabilidade |
|---------|-----------------|
| `quant_engine/regime_service.py` | Deteccao de regime (global + regional) |
| `quant_engine/allocation_proposal_service.py` | Tilts Black-Litterman |
| `app/domains/wealth/models/macro_committee.py` | MacroReview ORM |
| `app/domains/wealth/models/allocation.py` | StrategicAllocation, TacticalPosition |
| `app/domains/wealth/models/block.py` | AllocationBlock (global) |
| `app/domains/wealth/routes/macro.py` | POST generate, PATCH approve |
| `app/domains/wealth/routes/allocation.py` | GET strategic, effective, simulate |

### Ponte 2 — Construcao Convexa

| Arquivo | Responsabilidade |
|---------|-----------------|
| `quant_engine/optimizer_service.py` | CLARABEL 3-phase cascade |
| `quant_engine/cvar_service.py` | CVaR computation + breach status |
| `app/domains/wealth/services/quant_queries.py` | NAV -> covariance matrix |
| `vertical_engines/wealth/model_portfolio/portfolio_builder.py` | Fund composition assembly |
| `app/domains/wealth/routes/model_portfolios.py` | POST construct, backtest |

### Ponte 3 — NAV Sintetico

| Arquivo | Responsabilidade |
|---------|-----------------|
| `app/domains/wealth/workers/portfolio_nav_synthesizer.py` | Daily NAV synthesis (lock 900_030) |
| `app/domains/wealth/services/nav_reader.py` | Polymorphic NAV access |
| `app/domains/wealth/models/model_portfolio_nav.py` | ModelPortfolioNav hypertable |
| `app/domains/wealth/models/nav.py` | NavTimeseries hypertable |
| `app/domains/wealth/routes/entity_analytics.py` | 5-metric analytics vitrine |
| `quant_engine/drawdown_service.py` | Drawdown analysis |
| `quant_engine/rolling_service.py` | Rolling returns |
| `quant_engine/portfolio_metrics_service.py` | Sharpe, Sortino, etc. |

### Etapa 6 — Sistema Circulatorio

| Arquivo | Responsabilidade |
|---------|-----------------|
| `app/domains/wealth/services/holdings_exploder.py` | Portfolio -> N-PORT I/O |
| `vertical_engines/wealth/monitoring/overlap_scanner.py` | CUSIP/GICS pure math |

### Etapa 7 — Saida de Dados

| Arquivo | Responsabilidade |
|---------|-----------------|
| `vertical_engines/wealth/long_form_report/long_form_report_engine.py` | 8-chapter async engine |
| `vertical_engines/wealth/long_form_report/models.py` | ChapterResult, registry |
| `vertical_engines/wealth/fact_sheet/fact_sheet_engine.py` | Exec + institutional PDF |
| `vertical_engines/wealth/fact_sheet/institutional_renderer.py` | ReportLab PDF builder |
| `vertical_engines/wealth/attribution/service.py` | Brinson-Fachler orchestrator |
| `vertical_engines/wealth/fee_drag/service.py` | Fee drag analysis |
| `quant_engine/attribution_service.py` | Core attribution math |
| `quant_engine/benchmark_composite_service.py` | Composite benchmark NAV |
| `app/domains/wealth/services/benchmark_resolver.py` | Benchmark I/O layer |
| `app/domains/wealth/routes/long_form_reports.py` | SSE route + job management |

---

## Apendice B: Regras de Fronteira (SOLID)

Para adicionar um novo recurso ao pipeline sem violar as fronteiras:

1. **Novo tipo de entidade analitica** -> Adicione deteccao em `nav_reader.is_model_portfolio()` e branch de query. NUNCA importe tabelas NAV diretamente.

2. **Nova metrica quantitativa** -> Crie service em `quant_engine/` (pure sync, sem I/O, config como parametro). Consuma via `asyncio.to_thread()` nas routes.

3. **Novo capitulo de report** -> Adicione ao `CHAPTER_REGISTRY`, implemente handler `_chapter_{tag}()`, wrappe em try/except. O asyncio.gather cuida do paralelismo automaticamente.

4. **Novo tipo de benchmark** -> Adicione tier ao `_resolve_benchmark_returns()` em entity_analytics.py. Benchmarks GLOBAIS nao tem RLS.

5. **Novo worker de ingestao** -> Lock ID deterministico (nunca `hash()`), unlock em `finally`. Insira na hypertable com compression policy. Routes leem do DB only.

6. **Nova secao do fact sheet** -> Adicione campo em `FactSheetData` (frozen), compute em `_build_fact_sheet_data()` com try/except, renderize em `institutional_renderer.py`, adicione labels em `i18n.py` (PT+EN).

7. **Dados SEC** -> Use apenas metodos DB-only em routes: `read_holdings()`, `fetch_manager()`, etc. NUNCA chame `fetch_holdings()` (triggera EDGAR API) de codigo user-facing.

---

## Apendice C: Constantes e Limites

| Constante | Valor | Contexto |
|-----------|-------|----------|
| CVaR coefficient | 3.71 | Normal distribution CVaR at 95% |
| Risk aversion (Phase 1) | 2.0 | Mean-variance tradeoff |
| Min aligned NAV observations | 120 | Optimizer input threshold |
| NAV synthesis max lookback | 1260 dias | 5 years |
| Batch upsert size | 500 rows | portfolio_nav_synthesizer |
| Chart ThreadPool max workers | 4 | FactSheet parallel charts |
| LongFormReport max concurrent | 2 | SSE semaphore |
| DD Report max concurrent | 3 | SSE semaphore |
| Overlap breach threshold | 5% | CUSIP concentration limit |
| Fee drag threshold | 50% | Fee efficiency flag |
| Carino k_t clamp | 10.0 | Multi-period attribution |
| Weight sum tolerance | 1e-4 | Attribution normalization |
| Weight epsilon | 1e-6 | Brinson zero-out threshold |

---

*Documento gerado em 2026-03-26. Referencia interna — nao distribuir externamente.*
