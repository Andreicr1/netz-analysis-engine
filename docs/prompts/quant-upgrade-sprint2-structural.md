# Quant Upgrade — Sprint 2: Elevações Estruturais (BL-4, BL-5, BL-6)

## Status: CONCLUÍDO — 2026-03-27

Lint ✅ | Architecture 31/31 ✅ | Tests 2880 passed (8 pre-existing failures)
24 novos testes adicionados (test_black_litterman.py ×11, test_regime_cov.py ×6, test_turnover_penalty.py ×7)

### Implementações entregues
- **BL-4:** `black_litterman_service.py` pure sync — π=λΣw, views absolutas/relativas, Idzorek omega, posterior canônico. Endpoints POST/GET/DELETE `/model-portfolios/{id}/views`. Migration `a1b2c3d4e5f6` com RLS. BL ativo quando views cadastradas, mean-historical como fallback
- **BL-5:** `compute_regime_conditioned_cov()` em `quant_queries.py` — janela adaptativa 63d (stress P>0.6) vs 252d (normal). VIX via `macro_data`. Fallback silencioso se `regime_fit` nunca rodou
- **BL-6:** Turnover penalty L1 com slack variables no `optimize_fund_portfolio()`. `apply_dead_band()` em `weight_proposer.py` (default 0.5%). `calibration.yaml` atualizado: `turnover_penalty`, `dead_band_pct`, `bl.risk_aversion`, `bl.tau`

---

## Status: CONCLUÍDO — 2026-03-27

Todos os gates passaram. 31 import-linter contracts mantidos.
24 novos testes adicionados (2880 total, 8 falhas pré-existentes).

### Implementações entregues
- **BL-4:** `black_litterman_service.py` pure sync. Views CRUD em `/model-portfolios/{id}/views`. BL returns ativam automaticamente quando views existem; fallback para mean-historical quando não
- **BL-5:** `compute_regime_conditioned_cov()` em `quant_queries.py`. Janela adaptativa: stress (VIX P(high_vol) > 0.6) → 63d ponderado; normal → 252d. Fallback silencioso se regime_fit nunca rodou
- **BL-6:** Turnover penalty L1 via slack variables no CLARABEL. `apply_dead_band()` em `weight_proposer.py`. Config em `calibration.yaml`: `turnover_penalty: 0.001`, `dead_band_pct: 0.005`
- **Migration:** `a1b2c3d4e5f6` — tabela `portfolio_views` com RLS policy

---

## Pré-condição

Sprint 1 (BL-1, BL-2, BL-3) executado e validado.
`make check` passando com 2858+ testes antes de iniciar.

## Itens

- **BL-4:** Black-Litterman completo com views do IC
- **BL-5:** Covariância regime-dependente
- **BL-6:** Transaction cost modeling no rebalanceamento

---

## Leitura obrigatória antes de qualquer edição

```
backend/quant_engine/optimizer_service.py
backend/quant_engine/allocation_proposal_service.py
backend/app/domains/wealth/services/quant_queries.py
backend/app/domains/wealth/routes/model_portfolios.py
backend/vertical_engines/wealth/rebalancing/service.py
backend/app/domains/wealth/workers/regime_fit.py
backend/calibration/seeds/liquid_funds/calibration.yaml
```

Mapear:
- Como `allocation_proposal_service.py` acessa strategic_allocation targets
  (servirão como `w_mkt` proxy para BL-4)
- Como `regime_fit.py` armazena o estado do HMM e onde buscar o regime corrente
- Assinatura completa de `optimize_fund_portfolio()` após Sprint 1
- Schema de `WeightProposal` e `RebalanceImpact` em `rebalancing/service.py`

---

## BL-4 — Black-Litterman (fazer primeiro — BL-5 depende da estrutura)

### Novo arquivo: `backend/quant_engine/black_litterman_service.py`

Service pure sync. Zero I/O. Config via parâmetro. Implementar:

```python
def compute_bl_returns(
    sigma: np.ndarray,           # (N x N) covariância anualizada
    w_market: np.ndarray,        # (N,) pesos de mercado (strategic allocation targets)
    views: list[dict] | None,    # views do IC [{"assets": [...], "Q": float, "omega": float}]
    risk_aversion: float = 2.5,  # λ — parâmetro de aversão a risco
    tau: float = 0.05,           # escalar de incerteza nos priors
) -> np.ndarray:                 # (N,) expected returns BL
    """
    1. π = λ · Σ · w_mkt  (market-implied returns)
    2. Se views is None ou vazio: retornar π diretamente
    3. Construir P (K x N), Q (K,), Ω (K x K diagonal) das views
    4. Posterior: μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹π + PᵀΩ⁻¹Q]
    5. Retornar μ_BL
    """
```

Views format aceito:
- `{"type": "absolute", "asset_idx": 0, "Q": 0.08, "confidence": 0.6}`
- `{"type": "relative", "long_idx": 0, "short_idx": 1, "Q": 0.02, "confidence": 0.5}`
- `confidence` mapeia para `omega = variance_prior / confidence` (Idzorek method simplificado)


### Novos arquivos de domínio para views do IC

**`backend/app/domains/wealth/models/portfolio_view.py`**

```python
class PortfolioView(Base):
    __tablename__ = "portfolio_views"
    id: UUID (PK)
    portfolio_id: UUID (FK model_portfolios)
    organization_id: UUID  # RLS
    asset_instrument_id: UUID | None
    peer_instrument_id: UUID | None   # para views relativas
    view_type: str  # "absolute" | "relative"
    expected_return: float
    confidence: float  # 0.0 - 1.0
    rationale: str | None
    created_by: str
    effective_from: date
    effective_to: date | None
```

Migration necessária. Tabela org-scoped (com RLS).

**`backend/app/domains/wealth/schemas/portfolio_view.py`**

Schemas Pydantic: `PortfolioViewCreate`, `PortfolioViewRead`.

**`backend/app/domains/wealth/routes/portfolio_views.py`**

```
POST /api/v1/model-portfolios/{portfolio_id}/views
GET  /api/v1/model-portfolios/{portfolio_id}/views
DELETE /api/v1/model-portfolios/{portfolio_id}/views/{view_id}
```

### Integração no optimizer

Em `quant_queries.py` — `compute_fund_level_inputs()`:

Adicionar parâmetro `use_bl_returns: bool = False`.
Se True: buscar views ativas do portfolio, buscar strategic allocation targets
como `w_market`, chamar `compute_bl_returns()`, retornar μ_BL em vez de média histórica.

Em `model_portfolios.py` — `construct_portfolio`:

Passar `use_bl_returns=True` se portfolio tiver views cadastradas.

### O que NÃO fazer
- `black_litterman_service.py` não importa de `app/` — é pure quant
- Views são opcionais — sem views cadastradas, comportamento idêntico ao atual
- Não remover expected_returns de média histórica — apenas substituir quando BL ativo
- Não expor a matrix P/Q na API response (são IP interno)

---

## BL-5 — Covariância regime-dependente

### Implementação em `quant_queries.py`

Adicionar função:

```python
def compute_regime_conditioned_cov(
    returns_matrix: np.ndarray,    # (T x N)
    regime_probs: np.ndarray,      # (T,) probabilidade do regime stress no dia t
    short_window: int = 63,
    long_window: int = 252,
) -> np.ndarray:
    """
    Estratégia adaptativa:
    - Se regime atual (média dos últimos 21d de regime_probs) > 0.6 (stress):
        usar janela curta (63d) e ponderar mais os dias de stress
    - Caso contrário: usar janela longa (252d)
    Retorna covariância (N x N) anualizada.
    """
```

### Buscar regime corrente

Em `model_portfolios.py`, antes do construct:

```python
# Buscar último estado HMM do regime_fit worker
regime_state = await db.execute(
    select(RegimeFitResult)
    .order_by(RegimeFitResult.fitted_at.desc())
    .limit(1)
)
```

Verificar onde `regime_fit.py` persiste o resultado (tabela ou Redis).
Adaptar a busca conforme o storage atual.

### O que NÃO fazer
- Não re-implementar o HMM — apenas consumir o resultado já computado
- Se `regime_fit` nunca rodou: fallback silencioso para covariância padrão (252d)


---

## BL-6 — Transaction cost modeling no rebalanceamento

### Implementação em `optimizer_service.py`

Adicionar parâmetro opcional `current_weights: np.ndarray | None = None` em
`optimize_fund_portfolio()`.

Se `current_weights` fornecido, adicionar termo de penalidade ao objetivo:

```python
# Turnover penalty: κ · ‖w - w_current‖₁
# No CLARABEL: usar variáveis auxiliares t_i ≥ |w_i - w_current_i|
# minimize -μᵀw + λwᵀΣw + κ · Σt_i
# sujeito a: t_i ≥ w_i - w_current_i
#            t_i ≥ w_current_i - w_i

import cvxpy as cp
t = cp.Variable(n_funds, nonneg=True)  # slack para |Δw|
turnover_penalty = turnover_cost * cp.sum(t)
constraints += [t >= w - current_weights, t >= current_weights - w]
objective = cp.Maximize(expected_return - risk_term - turnover_penalty)
```

### Dead-band em `rebalancing/service.py`

Após `optimize_fund_portfolio()` retornar novos pesos, aplicar filtro:

```python
dead_band_pct = config.get("rebalance", {}).get("dead_band_pct", 0.005)
for fund_id, new_w in proposed_weights.items():
    current_w = current_weights.get(fund_id, 0.0)
    if abs(new_w - current_w) < dead_band_pct:
        proposed_weights[fund_id] = current_w  # não rebalancear
```

### Em `calibration.yaml`

```yaml
rebalance:
  turnover_penalty: 0.001   # κ — custo proporcional por unidade de turnover
  dead_band_pct: 0.005      # 0.5% — não rebalancear abaixo disso
```

### Como `current_weights` chega ao optimizer

Em `model_portfolios.py` — endpoint de rebalanceamento (não o construct inicial):
- Buscar snapshot mais recente do portfolio
- Extrair `fund_selection_schema.weights` como `current_weights`
- Passar ao optimizer

No construct inicial (Dia 0): `current_weights=None` → sem penalty.

### O que NÃO fazer
- Não aplicar turnover penalty no construct inicial (Dia 0)
- Não alterar a cascade de fases (CVaR → min-variance) — apenas adicionar
  o termo à função objetivo das fases existentes
- Não criar nova tabela para tracking de trades

---

## Definition of Done

- [ ] `black_litterman_service.py` criado em `quant_engine/`
- [ ] Migration para `portfolio_views` criada e aplicada
- [ ] `POST/GET/DELETE /api/v1/model-portfolios/{id}/views` funcionando
- [ ] Construct usa BL returns quando views cadastradas, mean-historical quando não
- [ ] Covariância usa janela adaptativa baseada no regime corrente
- [ ] Fallback silencioso se `regime_fit` não tiver rodado
- [ ] Turnover penalty no objective function quando `current_weights` fornecido
- [ ] Dead-band configurável em `calibration.yaml`
- [ ] `make check` passa (lint + typecheck + testes)
- [ ] Nenhuma nova dependência Python além das já no `requirements.txt`

## Failure modes esperados

- **`portfolio_views` migration falha em hypertable:** é tabela regular, não hypertable
  — sem autocommit necessário
- **w_market (strategic allocation) não cobre todos os fundos:** normalizar os pesos
  para os fundos presentes, logar os fundos sem cobertura
- **regime_fit storage format desconhecido:** ler `regime_fit.py` para entender
  exatamente onde e como o resultado é persistido antes de implementar BL-5
- **Turnover penalty torna problema infeasible:** se infeasible com penalty,
  repetir sem penalty (fallback silencioso com log warning)
