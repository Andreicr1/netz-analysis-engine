# Quant Upgrade — Sprint 4: Horizonte Longo (BL-12, BL-13)

## Status: DEFERIDO — spec de referência, não executar ainda

**BL-11 (GARCH) foi movido para Sprint 3.**
Os itens remanescentes aqui são deferidos por razões de produto (BL-13)
ou dependem de validação empírica pós-Sprint 1 (BL-12).

---

## BL-12 — Tail Dependence (Copulas)

### Por que deferido
BL-1 (Cornish-Fisher com momentos reais) precisa rodar em produção com
universo real primeiro. O critério de entrada é empírico: se a diferença
de CVaR entre Cornish-Fisher e t-copula for < 5% sistematicamente,
a copula não acrescenta nada observável e não vale a complexidade.
Essa validação requer dados de produção — não pode ser feita antes.

### Pré-condição para desbloquear
- Sprint 1 (BL-1) rodando em produção com universo real (N > 10 fundos)
- Benchmark CVaR CF vs CVaR copula por pelo menos 3 meses de dados
- Diferença média > 5% em pelo menos 30% dos portfolios avaliados

### Escopo técnico (quando desbloquear)

```python
def fit_student_t_copula(
    returns_matrix: np.ndarray,   # (T x N)
) -> dict:
    """
    1. Transformar margens para uniformes via ECDF
    2. Ajustar t-copula: estimar ν (graus de liberdade) e ρ (correlation)
    3. Retornar parâmetros para simulação Monte Carlo
    """
```

Usar simulação (N=10_000 cenários) para estimar CVaR com tail dependence.
Comparar com CVaR Cornish-Fisher — se diferença < 5%, a copula não acrescenta.

### Notas técnicas
- `copulas` library tem bugs conhecidos em Python 3.12 — verificar antes de implementar
- Custo computacional de MLE para t-copula: O(N² × T) — validar timing com universo real

---

## BL-13 — Multi-Period Optimization

### Status: OVERKILL para o caso de uso atual

Mean-variance single-period com rebalanceamento periódico aproxima bem
o ótimo multi-período para mandatos sem horizonte fixo definido.

Implementar apenas se:
- Produto evoluir para target-date funds (mandato com data de término)
- Cliente exigir liability-driven investing (LDI) explícito
- Scale justificar pesquisa acadêmica dedicada

### Referências técnicas para quando o momento chegar
- Mossin (1968): solução analítica para horizonte finito sem restrições
- Model Predictive Control (MPC): otimização rolling com horizonte T
- Approximate Dynamic Programming: para problemas com restrições
- Li & Ng (2000): mean-variance multi-period com solução closed-form

---

## Critério para desbloquear Sprint 4

| Condição | BL-12 | BL-13 |
|----------|-------|-------|
| Sprint 1 (BL-1) em produção com universo real | obrigatório | — |
| Benchmark CF vs copula > 5% por 3 meses | obrigatório | — |
| Requisito regulatório ou produto target-date/LDI | — | obrigatório |
