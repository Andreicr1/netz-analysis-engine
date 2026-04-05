# Auditoria de Integração: Backend Quant vs Frontend Wealth

**Data:** 2026-04-05
**Escopo:** Stress Testing paramétrico, Black-Litterman Views, Factor Models
**Tipo:** Discovery (read-only)

---

## 1. Backend Endpoints Encontrados

### A) Stress Testing (2 endpoints)

| Endpoint | Schema Request | Schema Response |
|---|---|---|
| `POST /model-portfolios/{portfolio_id}/stress` | Nenhum body (trigger) | `dict` (stress scenarios históricos via `compute_stress`) |
| `POST /model-portfolios/{portfolio_id}/stress-test` | `StressTestRequest` | `StressTestResponse` |

**StressTestRequest** (`backend/app/domains/wealth/schemas/model_portfolio.py:56`):
```python
class StressTestRequest(BaseModel):
    scenario_name: Literal["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps", "custom"] = "custom"
    shocks: dict[str, float] | None = None
```

**StressTestResponse** (`backend/app/domains/wealth/schemas/model_portfolio.py:65`):
```python
class StressTestResponse(BaseModel):
    portfolio_id: str
    scenario_name: str
    nav_impact_pct: float
    cvar_stressed: float | None = None
    block_impacts: dict[str, float]
    worst_block: str | None = None
    best_block: str | None = None
```

### B) Black-Litterman Views (3 endpoints)

| Endpoint | Schema | Descrição |
|---|---|---|
| `POST /model-portfolios/{portfolio_id}/views` | Body: `PortfolioViewCreate` → Response: `PortfolioViewRead` | Criar view (IC role) |
| `GET /model-portfolios/{portfolio_id}/views` | Response: `list[PortfolioViewRead]` | Listar views ativas |
| `DELETE /model-portfolios/{portfolio_id}/views/{view_id}` | 204 | Deletar view (IC role) |

**PortfolioViewCreate** (`backend/app/domains/wealth/schemas/portfolio_view.py:11`):
```python
class PortfolioViewCreate(BaseModel):
    asset_instrument_id: uuid.UUID | None = None
    peer_instrument_id: uuid.UUID | None = None
    view_type: str = Field(pattern=r"^(absolute|relative)$")
    expected_return: float
    confidence: float = Field(ge=0.01, le=1.0)
    rationale: str | None = None
    effective_from: date
    effective_to: date | None = None
```

### C) Factor Analysis (1 endpoint)

| Endpoint | Params | Response |
|---|---|---|
| `GET /analytics/factor-analysis/{profile}` | `n_factors: int = 3` (1-10) | `FactorAnalysisResponse` |

### D) Outros endpoints quantitativos já expostos

| Endpoint | Rota |
|---|---|
| `POST /analytics/optimize` | CLARABEL 4-phase cascade |
| `POST /analytics/optimize/pareto` | Multi-objective Pareto (SSE) |
| `GET /analytics/optimize/pareto/{job_id}/stream` | SSE progress |
| `POST /analytics/risk-budget/{profile}` | MCTR/PCTR/MCETL/PCETL |
| `POST /analytics/monte-carlo` | Block bootstrap simulation |
| `GET /analytics/peer-group/{entity_id}` | Peer rankings |
| `GET /analytics/correlation` | Correlation matrix |
| `GET /analytics/rolling-correlation` | Pairwise rolling |
| `POST /model-portfolios/{id}/backtest` | Walk-forward backtest |
| `GET /model-portfolios/{id}/track-record` | Backtest + stress + NAV |
| `GET /model-portfolios/{id}/overlap` | Holdings overlap |
| `POST /model-portfolios/{id}/construction-advice` | CVaR gap diagnosis |

---

## 2. Estado Atual da UI

### A) Roteamento

Nao existe `model-portfolios/[id]/` com sub-rotas tab-based. Tudo vive numa single page:

```
frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/
  +page.server.ts    <- loads portfolio + trackRecord + views + overlap + reports
  +page.svelte       <- "Model Portfolio Workbench" (monolítico)
```

### B) O que JA ESTA integrado na UI

| Feature | Status | Componente |
|---|---|---|
| Historical Stress (4 cenários) | INTEGRADO | Inline em `+page.svelte` — bar chart com `POST .../stress` |
| Parametric Stress (custom shocks) | INTEGRADO | Inline em `+page.svelte` — form com presets + `POST .../stress-test` |
| Black-Litterman Views CRUD | INTEGRADO | `ICViewsPanel.svelte` — tabela + form de criação |
| Factor Exposures (optimizer output) | INTEGRADO | Chips inline no optimizer metadata section |
| Backtest (walk-forward) | INTEGRADO | Equity curve + fold stats |
| Overlap (CUSIP concentration) | INTEGRADO | Seção dedicada |
| Construction Advisor (CVaR gaps) | INTEGRADO | `ConstructionAdvisor.svelte` |

### C) Factor Analysis (standalone)

O `GET /analytics/factor-analysis/{profile}` já está consumido no **Analysis Lab**:
- `frontends/wealth/src/routes/(app)/analysis/+page.svelte` — loads `factorData` via `loadFactorAnalysis()`
- `frontends/wealth/src/lib/components/analytics/FactorContributionChart.svelte`

---

## 3. Gaps de Integração Identificados

| # | Gap | Severidade | Descrição |
|---|---|---|---|
| 1 | **Factor Analysis no Model Portfolio** | Medio | Factor decomposition (PCA) existe no Analysis Lab por profile, mas nao aparece na workbench do portfolio individual. O optimizer retorna `factor_exposures` (chips), mas a decomposição completa (systematic vs specific risk, R-squared, per-factor contributions) não está na detail page. |
| 2 | **Risk Budget no Model Portfolio** | Medio | `POST /analytics/risk-budget/{profile}` (MCTR/PCTR/MCETL/PCETL) não tem UI dedicada na workbench — só está no Analysis Lab. |
| 3 | **Monte Carlo no Model Portfolio** | Medio | `POST /analytics/monte-carlo` não tem UI na workbench — só no Analysis Lab. |
| 4 | **Peer Group no Model Portfolio** | Baixo | `GET /analytics/peer-group/{entity_id}` não tem link direto da workbench. |
| 5 | **API Client genérico** | Nenhum | O `client.ts` é um wrapper fino sobre `createServerApiClient`/`createClientApiClient` do `@investintell/ui`. Todos os endpoints são chamados via paths relativos (`api.post<T>("/model-portfolios/...")`) — nao precisa de wrappers dedicados por endpoint. Todos os novos endpoints já são chamáveis. |
| 6 | **Types TS completos** | Nenhum | `model-portfolio.ts` já tem `StressScenario`, `StressResult`, `ParametricStressResult`, `PortfolioView`, `OverlapResult`. `analytics.ts` já tem `FactorAnalysisResult`, `RiskBudgetResult`, `MonteCarloResult`, `PeerGroupResult`. |

---

## 4. Resumo

Os 3 endpoints centrais do quant upgrade (Parametric Stress, Black-Litterman Views, Factor Exposures do optimizer) **já estão totalmente integrados na UI** do Model Portfolio Workbench. Os types TypeScript mapeiam 1:1 com os schemas Pydantic. O API client genérico cobre todos os endpoints sem necessidade de wrappers.

Os gaps reais são de **profundidade analítica na workbench**: Risk Budget, Monte Carlo, Factor Decomposition completa, e Peer Group existem no Analysis Lab (rota `/analysis`) mas não estão embarcados na page de detalhe do portfolio individual. Se o objetivo é que um IC member tenha tudo num lugar só, esses 4 painéis precisariam ser adicionados à workbench ou linkados dela.

---

## 5. Arquivos-Chave (Referência Rápida)

### Backend
- `backend/app/domains/wealth/routes/model_portfolios.py` — stress, backtest, overlap, construction-advice
- `backend/app/domains/wealth/routes/portfolio_views.py` — Black-Litterman CRUD
- `backend/app/domains/wealth/routes/analytics.py` — optimize, pareto, risk-budget, factor-analysis, monte-carlo, peer-group
- `backend/app/domains/wealth/schemas/model_portfolio.py` — StressTestRequest/Response, OverlapResultRead
- `backend/app/domains/wealth/schemas/portfolio_view.py` — PortfolioViewCreate/Read

### Frontend
- `frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/+page.svelte` — Model Portfolio Workbench
- `frontends/wealth/src/routes/(app)/portfolio/models/[portfolioId]/+page.server.ts` — SSR data loader
- `frontends/wealth/src/lib/components/model-portfolio/ICViewsPanel.svelte` — Views CRUD
- `frontends/wealth/src/lib/components/model-portfolio/ConstructionAdvisor.svelte` — CVaR advisor
- `frontends/wealth/src/lib/types/model-portfolio.ts` — TS types (stress, views, overlap)
- `frontends/wealth/src/lib/types/analytics.ts` — TS types (factor, risk-budget, monte-carlo, peer)
- `frontends/wealth/src/routes/(app)/analysis/+page.svelte` — Analysis Lab (factor, risk-budget, monte-carlo)
- `frontends/wealth/src/lib/api/client.ts` — API client (generic wrapper)
