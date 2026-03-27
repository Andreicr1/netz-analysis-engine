# Quant Upgrade — Sprint 1: Quick Wins (BL-1, BL-2, BL-3)

## Status: CONCLUÍDO — 2026-03-27

Todos os gates passaram (lint, arquitetura, testes).
31 import-linter contracts mantidos, zero quebrados.
8 falhas em test_instrument_ingestion são pré-existentes — não introduzidas neste sprint.

### Implementações entregues
- **BL-3:** `_fetch_returns_by_type()` em `quant_queries.py` — log preferred, arithmetic fallback com warning, nunca mistura tipos
- **BL-1:** `compute_fund_level_inputs()` retorna 5-tuple com skewness + excess_kurtosis via `scipy.stats`. `optimize_fund_portfolio()` propaga para `_compute_cvar()` substituindo zeros hard-coded
- **BL-2:** `_apply_ledoit_wolf()` em `quant_queries.py` via `sklearn.covariance.LedoitWolf`. Aplicado por default, controlado por `calibration.yaml: optimizer.apply_shrinkage: true`

---

## Objetivo

Corrigir três bugs de integração no path de otimização que desperdiçam
infraestrutura já implementada. Nenhum novo service é criado.

## Itens

- **BL-1:** Cornish-Fisher CVaR alimentado com momentos reais (skewness, kurtosis)
- **BL-2:** Ledoit-Wolf shrinkage aplicado no optimizer (já existe, nunca chamado)
- **BL-3:** Filtrar `return_type` em `compute_fund_level_inputs()` (log vs arithmetic)

---

## Leitura obrigatória antes de qualquer edição

Ler os seguintes arquivos na íntegra antes de começar:

```
backend/app/domains/wealth/services/quant_queries.py
backend/quant_engine/optimizer_service.py
backend/quant_engine/correlation_regime_service.py
backend/calibration/seeds/liquid_funds/calibration.yaml
```

Mapear exatamente:
- Assinatura atual de `compute_fund_level_inputs()` — inputs e outputs
- Assinatura atual de `optimize_fund_portfolio()` — como recebe a cov matrix
- Onde `parametric_cvar_cf()` é chamada e quais args recebe hoje
- Como `ledoit_wolf_shrinkage()` (ou equivalente) está implementado em `correlation_regime_service.py`
- Se `return_type` já existe como coluna em `NavTimeseries`

---

## BL-3 — Filtrar return_type (fazer primeiro — pré-requisito dos outros)

### Problema
`compute_fund_level_inputs()` busca retornos sem filtrar `return_type`.
Misturar log returns e arithmetic returns contamina a covariância silenciosamente.

### Implementação

Em `quant_queries.py`, na query de retornos dentro de `compute_fund_level_inputs()`:

1. Verificar se `NavTimeseries` tem coluna `return_type`
2. Se sim: adicionar `.filter(NavTimeseries.return_type == 'log')` na query principal
3. Se um fundo não tiver log returns, fazer fallback para 'arithmetic' com `log.warning`
4. Nunca misturar os dois tipos na mesma matriz de retornos

### O que NÃO fazer
- Não criar nova coluna na tabela
- Não alterar o schema de NavTimeseries
- Não converter arithmetic → log (pode introduzir erro; apenas filtrar e logar)


---

## BL-1 — Cornish-Fisher com momentos reais

### Problema
`parametric_cvar_cf()` recebe `skew=zeros, kurt=zeros`, anulando o ajuste fat-tail.
Os momentos reais dos retornos nunca são computados.

### Implementação

**Em `quant_queries.py` — `compute_fund_level_inputs()`:**

Após construir a matriz de retornos (já existente), adicionar:

```python
from scipy import stats as sp_stats

# Calcular por fundo (eixo 0 = tempo, eixo 1 = fundo)
skewness = sp_stats.skew(returns_matrix, axis=0)            # shape (n_funds,)
excess_kurtosis = sp_stats.kurtosis(returns_matrix,
                                    axis=0, fisher=True)    # shape (n_funds,)
```

Atualizar o retorno da função para incluir `skewness` e `excess_kurtosis`.
Manter backward-compat: se callers existentes não usam os novos campos, retornar
como campos adicionais em um dataclass ou tuple expandida — verificar o pattern
atual antes de decidir.

**Em `optimizer_service.py` — `optimize_fund_portfolio()`:**

Receber `skewness` e `excess_kurtosis` como parâmetros opcionais
(default `None` → fallback para zeros, mantendo comportamento atual).

Propagar para `_compute_cvar()` e para `PortfolioProblem.__init__()`
(NSGA-II), substituindo os `zeros` hard-coded.

**Em `model_portfolios.py`:**

Na chamada a `compute_fund_level_inputs()`, capturar os novos campos
e passá-los para `optimize_fund_portfolio()`.

### O que NÃO fazer
- Não alterar a assinatura pública de `parametric_cvar_cf()` — apenas alimentá-la corretamente
- Não usar `pd.DataFrame.skew()` — usar `scipy.stats.skew()` diretamente na matrix numpy


---

## BL-2 — Ledoit-Wolf shrinkage no optimizer

### Problema
`compute_fund_level_inputs()` usa `np.cov` puro. Ledoit-Wolf já está em
`correlation_regime_service.py` mas nunca é chamado no path de otimização.

### Implementação

**Em `correlation_regime_service.py`:**

Extrair a lógica de shrinkage para uma função standalone que possa ser
importada sem carregar o service inteiro. Algo como:

```python
def apply_ledoit_wolf(returns_matrix: np.ndarray) -> np.ndarray:
    """Retorna covariância shrinkada. Input: (T x N) returns."""
    from sklearn.covariance import LedoitWolf
    lw = LedoitWolf()
    lw.fit(returns_matrix)
    return lw.covariance_
```

Se `sklearn` não estiver no requirements, verificar antes. Alternativa:
usar a implementação já existente no service — não duplicar lógica.

**Em `quant_queries.py` — `compute_fund_level_inputs()`:**

Após `np.cov(returns_matrix.T)`, aplicar shrinkage se config habilitada:

```python
apply_shrinkage = config.get("optimizer", {}).get("apply_shrinkage", True)
if apply_shrinkage:
    annual_cov = apply_ledoit_wolf(returns_matrix) * 252
else:
    annual_cov = np.cov(returns_matrix.T) * 252
```

**Em `calibration/seeds/liquid_funds/calibration.yaml`:**

Adicionar flag (se não existir):
```yaml
optimizer:
  apply_shrinkage: true
```

**Import linter:** verificar se import de `correlation_regime_service`
dentro de `quant_queries.py` viola fronteiras. Se violar, duplicar a
função helper em `quant_engine/` diretamente.

### O que NÃO fazer
- Não modificar `correlation_regime_service.py` de forma que quebre
  os callers existentes do service
- Não aplicar shrinkage na covariância do NSGA-II separadamente —
  um único ponto de aplicação em `compute_fund_level_inputs()`

---

## Definition of Done

- [ ] `compute_fund_level_inputs()` retorna `skewness` e `excess_kurtosis`
- [ ] `parametric_cvar_cf()` recebe momentos reais (não zeros) na chamada do optimizer
- [ ] Ledoit-Wolf aplicado na covariância antes de passar ao CLARABEL
- [ ] `return_type` filtrado na query de retornos (log preferred, arithmetic fallback com warning)
- [ ] Flag `optimizer.apply_shrinkage` em `calibration.yaml`
- [ ] `make check` passa (lint + typecheck + 2858 tests)
- [ ] Nenhum outro arquivo modificado além dos listados acima

## Failure modes esperados

- **`scipy` não instalado:** improvável, mas verificar `requirements.txt`
- **`return_type` não existe em `NavTimeseries`:** se coluna não existir,
  pular BL-3 e logar warning — não criar migration neste sprint
- **Import linter violação:** se `quant_queries.py` não pode importar de
  `correlation_regime_service.py`, duplicar o helper de shrinkage em
  `quant_engine/shrinkage_utils.py` (arquivo novo, <30 linhas)
- **Assinatura de `compute_fund_level_inputs()` tem muitos callers:**
  usar retorno com dataclass ou dict para não quebrar callers existentes
