# Prompt A — Fix Phantom Calls (2 bugs de produção)

## Contexto

Dois endpoints chamados pelo frontend não existem no backend, causando erros em produção.

**Bug 1:** `PATCH /model-portfolios/{portfolio_id}` → HTTP 405 em produção
- Chamado em: `frontends/wealth/src/routes/(app)/model-portfolios/create/+page.svelte:306`
- Usado para: atualizar `display_name` e `inception_date` dos 3 portfólios logo antes de ativar
- O handler POST (criação) existe mas não há handler PATCH

**Bug 2:** `GET /instruments/{instrument_id}/risk-metrics` → HTTP 404 em produção
- Chamado em: `frontends/wealth/src/lib/components/model-portfolio/ScoreBreakdownPopover.svelte:40`
- Usado para: lazy-fetch de `score_components` (breakdown dos 6 componentes do manager score)
- Retorno esperado pelo frontend: `{ score_components: Record<string, number> }`

---

## Arquivos a ler antes de implementar

```
backend/app/domains/wealth/routes/model_portfolios.py      — ver POST handler (linhas 58-90) como referência
backend/app/domains/wealth/schemas/model_portfolio.py      — ver ModelPortfolioCreate/Read para base do Update
backend/app/domains/wealth/models/model_portfolio.py       — ver campos do ORM para PATCH
backend/app/domains/wealth/routes/instruments.py           — ver GET /{instrument_id} como padrão para nova sub-rota
backend/app/domains/wealth/models/risk.py                  — ver FundRiskMetrics para score_components
```

---

## Fase 1 — Fix Bug 1: PATCH /model-portfolios/{portfolio_id}

### 1.1 Criar schema ModelPortfolioUpdate

Em `backend/app/domains/wealth/schemas/model_portfolio.py`, adicionar:

```python
class ModelPortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None
```

Exportar no `__init__.py` do schemas se necessário.

### 1.2 Adicionar handler PATCH em model_portfolios.py

Adicionar APÓS o `@router.get("/{portfolio_id}")` e ANTES do `@router.post("/{portfolio_id}/construct")`:

```python
@router.patch(
    "/{portfolio_id}",
    response_model=ModelPortfolioRead,
    summary="Update model portfolio metadata (display_name, inception_date, description)",
)
async def update_model_portfolio(
    portfolio_id: uuid.UUID,
    body: ModelPortfolioUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ModelPortfolioRead:
    _require_investment_role(actor)

    stmt = select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(portfolio, field, value)

    await db.flush()
    await db.refresh(portfolio)
    return ModelPortfolioRead.model_validate(portfolio)
```

**Importante:** `_require_investment_role` já existe no arquivo — usar o mesmo helper.

---

## Fase 2 — Fix Bug 2: GET /instruments/{instrument_id}/risk-metrics

### 2.1 Criar schema RiskMetricsRead

Em `backend/app/domains/wealth/schemas/instrument.py` (ou criar
`instrument_risk.py` se o arquivo ficar grande), adicionar:

```python
class InstrumentRiskMetricsRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    instrument_id: uuid.UUID
    score_components: dict[str, float] | None = None
    manager_score: float | None = None
    sharpe_1y: float | None = None
    volatility_1y: float | None = None
    max_drawdown_1y: float | None = None
    cvar_95_1m: float | None = None
```

### 2.2 Adicionar endpoint em instruments.py

Ler `backend/app/domains/wealth/models/risk.py` para confirmar o nome exato do modelo ORM
(provavelmente `FundRiskMetrics`) e o campo `score_components`.

Adicionar APÓS o `@router.get("/{instrument_id}")`:

```python
@router.get(
    "/{instrument_id}/risk-metrics",
    response_model=InstrumentRiskMetricsRead,
    summary="Risk metrics and score breakdown for an instrument",
)
async def get_instrument_risk_metrics(
    instrument_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> InstrumentRiskMetricsRead:
    from app.domains.wealth.models.risk import FundRiskMetrics  # adjust import if needed

    stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id == instrument_id)
        .order_by(FundRiskMetrics.calc_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No risk metrics found for this instrument",
        )

    return InstrumentRiskMetricsRead.model_validate(row)
```

**Atenção ao campo `score_components`:** O frontend espera `dict[str, float]` mas o DB armazena
JSONB — confirmar que `FundRiskMetrics.score_components` é JSONB com valores `float`.
Se o campo tiver um nome diferente, ajustar o schema e/ou adicionar `@field_validator`.

---

## Fase 3 — Não alterar frontend

Ambos os bugs são de backend. O frontend já está correto:
- `create/+page.svelte` já chama `PATCH /model-portfolios/{id}` com o body certo
- `ScoreBreakdownPopover.svelte` já consome `data.score_components` corretamente

Não modificar nenhum arquivo frontend.

---

## Verificação

Após implementar:

```bash
# Backend
cd backend
make check   # lint + typecheck + tests

# Testar manualmente com psql ou curl:
# PATCH /model-portfolios/{id} com body {"display_name": "Test"} → 200 OK
# GET /instruments/{id}/risk-metrics → 200 com score_components preenchido ou 404
```

---

## Definition of Done

- [ ] `ModelPortfolioUpdate` schema criado e exportado
- [ ] `PATCH /model-portfolios/{portfolio_id}` handler implementado
- [ ] `InstrumentRiskMetricsRead` schema criado
- [ ] `GET /instruments/{instrument_id}/risk-metrics` handler implementado
- [ ] `make check` passa sem erros
- [ ] Nenhum arquivo frontend modificado
