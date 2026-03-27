# Quant Upgrade — Sprint 3: Diferenciais Competitivos (BL-7, BL-8, BL-9, BL-10, BL-11)

## Status: CONCLUÍDO — 2026-03-27

Lint ✅ | Architecture 31/31 ✅ | Tests 2905 passed (10 pre-existing failures)
49 novos testes adicionados: test_factor_model.py ×7, test_robust_optimizer.py ×3, test_regime_cvar.py ×5, test_stress_parametric.py ×7, test_garch.py ×5 + testes anteriores do sprint

### Implementações entregues
- **BL-7:** `factor_model_service.py` pure sync — PCA com macro proxy labelling. `factor_exposures` no response do construct. GARCH vol e CVaR condicional injetados em `quant_injection.py` para capítulo de risco do DD Report
- **BL-8:** Phase 1.5 (ellipsoidal SOCP) na cascade do `optimizer_service.py`. Status `"optimal:robust"`. Config: `optimizer.robust: true`, `optimizer.uncertainty_level: 0.5`
- **BL-9:** `compute_regime_cvar()` em `cvar_service.py` — subset stress ≥30 obs, fallback incondicional. `regime_cvar_multiplier` no optimizer. Coluna `cvar_95_conditional` em `FundRiskMetrics`. Config: `regime_cvar_multipliers` (RISK_OFF: 0.85, CRISIS: 0.70)
- **BL-10:** `StressScenarioResult` + `PRESET_SCENARIOS` (GFC, COVID, Taper, Rate Shock +200bps) em `stress_scenarios.py`. Endpoint `POST /api/v1/model-portfolios/{id}/stress-test` org-scoped, on-demand
- **BL-11:** `garch_service.py` — `fit_garch()` com convergence fallback. `arch>=7.0` em `pyproject.toml`. Coluna `volatility_garch` em `FundRiskMetrics`. Migration `0058_add_garch_and_conditional_cvar.py`. Worker `risk_calc` persiste vol GARCH (fallback para vol amostral se não convergir)

---

## Pré-condição

Sprint 2 (BL-4, BL-5, BL-6) executado e validado.
`make check` passando antes de iniciar.

## Itens

- **BL-7:** Factor model decomposition (PCA-based)
- **BL-8:** Robust optimization com uncertainty sets
- **BL-9:** CVaR condicional ao regime
- **BL-10:** Stress testing paramétrico (cenários do IC)
- **BL-11:** GARCH(1,1) para volatilidade condicional

---

## Leitura obrigatória antes de qualquer edição

```
backend/quant_engine/optimizer_service.py
backend/quant_engine/attribution_service.py
backend/vertical_engines/wealth/dd_report/
backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py
backend/app/domains/wealth/routes/model_portfolios.py
backend/app/domains/wealth/workers/portfolio_eval.py
backend/calibration/seeds/liquid_funds/calibration.yaml
```

---

## BL-7 — Factor Model Decomposition (PCA)

### Novo arquivo: `backend/quant_engine/factor_model_service.py`

Pure sync. Zero I/O. Config via parâmetro.

```python
@dataclass(frozen=True)
class FactorModelResult:
    factor_returns: np.ndarray        # (T x K) — K fatores extraídos
    factor_loadings: np.ndarray       # (N x K) — exposição de cada fundo
    factor_labels: list[str]          # labels interpretados (ex: "market", "volatility")
    portfolio_factor_exposures: dict  # {label: exposure_float}
    r_squared: float                  # % variância explicada pelos K fatores
    residual_returns: np.ndarray      # (T,) idiosyncratic

def decompose_factors(
    returns_matrix: np.ndarray,       # (T x N) retornos dos fundos
    macro_proxies: dict[str, np.ndarray] | None,  # séries macro para label dos fatores
    portfolio_weights: np.ndarray,    # (N,) pesos atuais
    n_factors: int = 3,
) -> FactorModelResult:
    """
    1. PCA em returns_matrix → extrair n_factors componentes
    2. Correlacionar cada PC com macro_proxies para gerar label
       (ex: alta corr com VIX → "volatility factor")
    3. Projetar portfolio_weights no espaço de fatores
    4. Computar R² dos K fatores
    """
```

`macro_proxies` vem da `macro_data` hypertable (VIX, credit spread, DGS10).
Callers buscam do DB e passam como arrays — o service não faz I/O.

### Integração

Em `model_portfolios.py` — response do construct:
Adicionar `factor_exposures` ao `fund_selection_schema.optimization` meta.

Em `vertical_engines/wealth/dd_report/`:
Identificar o capítulo de risco e adicionar `factor_exposure` section.
Se `FactorModelResult` não disponível (dados insuficientes): section omitida
(never-raises).

### O que NÃO fazer
- Não usar Fama-French ou fatores externos — PCA é self-contained
- Não persistir `factor_returns` em nova tabela — resultado é calculado on-demand
- Não expor `factor_returns` brutos na API — apenas `portfolio_factor_exposures`


---

## BL-8 — Robust Optimization (uncertainty sets)

### Implementação em `optimizer_service.py`

Adicionar como Phase 1.5 na cascade (entre Phase 1 CVaR e Phase 2 min-variance):

```python
# Phase 1.5 — Robust (ellipsoidal uncertainty set)
# maximize μ̂ᵀw − κ·√(wᵀΣw) − λ·wᵀΣw
# Reformulação SOCP — resolve com CLARABEL nativamente
# κ = uncertainty_level * sqrt(n_funds)  — escala com dimensionalidade

if config.get("optimizer", {}).get("robust", False):
    kappa = uncertainty_level * np.sqrt(n_funds)
    # cp.quad_form(w, sigma) = wᵀΣw
    robust_penalty = kappa * cp.norm(cp.matmul(L, w), 2)
    # onde L é Cholesky de Σ: L @ Lᵀ = Σ
    objective_robust = cp.Maximize(
        mu @ w - robust_penalty - risk_aversion * cp.quad_form(w, sigma)
    )
```

Adicionar à cascade: tentar Phase 1.5 antes do fallback min-variance.
Se Phase 1.5 infeasible: prosseguir para Phase 2 normalmente.

Novo status documentado: `"optimal:robust"`.

### Em `calibration.yaml`

```yaml
optimizer:
  robust: true
  uncertainty_level: 0.5   # κ base — maior = mais conservador
```

### O que NÃO fazer
- Não remover Phase 1 (CVaR) nem Phase 2 (min-variance)
- Não alterar a lógica de cascade — apenas inserir Phase 1.5 como tentativa
  antes do fallback

---

## BL-9 — CVaR Condicional ao Regime

### Novo arquivo: `backend/quant_engine/cvar_service.py`

```python
def compute_regime_cvar(
    returns: np.ndarray,          # (T,) retornos do portfolio
    regime_probs: np.ndarray,     # (T,) probabilidade do regime stress
    confidence: float = 0.95,
    regime_threshold: float = 0.5,
) -> float:
    """
    CVaR empírico usando apenas os dias onde regime_probs > threshold.
    Se subset resultante < 30 observações: fallback para CVaR incondicional
    com log warning.
    """
    stress_mask = regime_probs > regime_threshold
    if stress_mask.sum() >= 30:
        stress_returns = returns[stress_mask]
    else:
        log.warning("cvar_conditional_insufficient_data", n=stress_mask.sum())
        stress_returns = returns
    var = np.percentile(stress_returns, (1 - confidence) * 100)
    return float(np.mean(stress_returns[stress_returns <= var]))
```

### Integração em `portfolio_eval.py`

Ao computar o CVaR do portfolio no worker diário:
- Buscar regime_probs do período
- Computar CVaR condicional via `cvar_service.py`
- Persistir em `fund_risk_metrics` com campo `cvar_95_conditional`

### Ajuste de limite em regimes adversos

Em `optimizer_service.py`, aceitar `regime_cvar_multiplier: float = 1.0`.
Quando regime = RISK_OFF ou CRISIS: `effective_cvar_limit = cvar_limit * 0.7`
(configurável em `calibration.yaml` como `regime_cvar_multipliers`).

### O que NÃO fazer
- Não substituir o CVaR incondicional — adicionar como campo paralelo
- `cvar_service.py` não importa de `app/` — pure quant


---

## BL-10 — Stress Testing Paramétrico

### Expandir `backend/vertical_engines/wealth/model_portfolio/stress_scenarios.py`

Antes de editar, ler o arquivo atual para entender o que já existe.

Adicionar função:

```python
@dataclass(frozen=True)
class StressScenarioResult:
    scenario_name: str
    nav_impact_pct: float          # ΔP/P = Σ(w_block × shock_block)
    cvar_stressed: float           # CVaR re-computado com retornos stressed
    block_impacts: dict[str, float] # {block_id: impact_pct}
    worst_block: str
    best_block: str

def run_stress_scenario(
    weights_by_block: dict[str, float],   # {block_id: weight}
    shocks: dict[str, float],              # {block_id: shock_return}
    historical_returns: np.ndarray,        # (T x N) para CVaR stressed
    scenario_name: str,
) -> StressScenarioResult:
```

Cenários pré-definidos como constantes:

```python
PRESET_SCENARIOS = {
    "gfc_2008":    {"na_equity_large": -0.38, "fi_treasury": 0.06, "alt_gold": 0.05, ...},
    "covid_2020":  {"na_equity_large": -0.34, "fi_treasury": 0.08, ...},
    "taper_2013":  {"na_equity_large": -0.06, "fi_treasury": -0.05, ...},
    "rate_shock_200bps": {"fi_treasury": -0.12, "fi_credit_ig": -0.08, "na_equity_large": -0.10, ...},
}
```

### Novo endpoint: `backend/app/domains/wealth/routes/stress_test.py`

```
POST /api/v1/model-portfolios/{portfolio_id}/stress-test
Body: {
  "scenario_name": "rate_shock_200bps",  # preset ou "custom"
  "shocks": {"na_equity_large": -0.15}   # obrigatório se scenario_name="custom"
}
Response: StressScenarioResult
```

Endpoint é org-scoped (RLS). Não persiste resultado (calculado on-demand).
Integrar no router de `model_portfolios.py` ou criar router separado.

### O que NÃO fazer
- Não criar nova tabela para resultados de stress — on-demand apenas
- Não expor `historical_returns` na response — apenas os resultados agregados
- Shocks em `PRESET_SCENARIOS` devem cobrir apenas os block_ids que existem
  em `allocation_blocks` — verificar antes de hardcodar

---

## Definition of Done

- [ ] `factor_model_service.py` criado em `quant_engine/`
- [ ] `factor_exposures` no response do construct (optimization meta)
- [ ] Capítulo de fator no DD report (omitido se dados insuficientes)
- [ ] Phase 1.5 (robust) na cascade, status `"optimal:robust"` documentado
- [ ] `cvar_service.py` criado em `quant_engine/`
- [ ] `cvar_95_conditional` em `fund_risk_metrics`
- [ ] `regime_cvar_multipliers` em `calibration.yaml`
- [ ] `POST /api/v1/model-portfolios/{id}/stress-test` funcionando
- [ ] Preset scenarios cobrindo GFC, COVID, Taper, Rate Shock
- [ ] `garch_service.py` criado em `quant_engine/`
- [ ] Coluna `volatility_garch` adicionada em `fund_risk_metrics` via migration
- [ ] Worker `risk_calc` persiste vol GARCH quando converge, vol amostral como fallback
- [ ] `make check` passa (lint + typecheck + testes)

## Failure modes esperados

- **PCA com N > T (mais fundos que observações):** usar `n_components = min(n_factors, T-1)`
  e logar warning; resultado ainda válido com menos fatores
- **macro_proxies indisponíveis:** `factor_labels` default para "factor_1", "factor_2"...
  sem interpretação — não bloquear o resultado
- **SOCP infeasible com robust:** Phase 1.5 skipped, log warning, cascade continua normal
- **Shocks em blocks sem peso no portfolio:** ignorar silenciosamente (impacto zero)
- **regime_probs não disponíveis para BL-9:** fallback para CVaR incondicional
  (mesmo comportamento atual) — nunca raise
- **GARCH não converge:** `fit_garch()` retorna None, worker usa vol amostral — transparente
- **`arch` library ausente:** adicionar ao `requirements.txt`, verificar compatibilidade Python 3.12
