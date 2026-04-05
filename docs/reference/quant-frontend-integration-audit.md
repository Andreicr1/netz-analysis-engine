# Auditoria de Integração: Quant Upgrade × Frontend

**Data:** 2026-04-05
**Escopo:** Stress Testing paramétrico, Black-Litterman Views, Factor Models (PCA)
**Resultado:** Integração COMPLETA — nenhum gap crítico identificado.

---

## 1. Backend Endpoints Encontrados

| Feature | Método | Path | Request Schema | Response Schema |
|---------|--------|------|----------------|-----------------|
| Stress (histórico) | POST | `/model-portfolios/{id}/stress` | `{}` | `StressResult` |
| Stress (paramétrico) | POST | `/model-portfolios/{id}/stress-test` | `StressTestRequest` | `StressTestResponse` |
| Views CRUD | POST | `/model-portfolios/{id}/views` | `PortfolioViewCreate` | `PortfolioViewRead` |
| Views List | GET | `/model-portfolios/{id}/views` | — | `list[PortfolioViewRead]` |
| Views Delete | DELETE | `/model-portfolios/{id}/views/{vid}` | — | 204 |
| Factor Analysis | GET | `/analytics/factor-analysis/{profile}` | `n_factors` query | `FactorAnalysisResponse` |
| CVaR Status | GET | `/risk/{profile}/cvar` | — | `CVaRStatus` |
| CVaR History | GET | `/risk/{profile}/cvar/history` | date range | `list[CVaRPoint]` |
| Track Record | GET | `/model-portfolios/{id}/track-record` | — | backtest + stress dict |
| Overlap | GET | `/model-portfolios/{id}/overlap` | `limit_pct` query | `OverlapResultRead` |
| Construction Advice | POST | `/model-portfolios/{id}/construction-advice` | — | `ConstructionAdviceRead` |

### Schemas Chave

```python
# backend/app/domains/wealth/schemas/model_portfolio.py

class StressTestRequest(BaseModel):
    scenario_name: Literal["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps", "custom"] = "custom"
    shocks: dict[str, float] | None = None

class StressTestResponse(BaseModel):
    portfolio_id: str
    scenario_name: str
    nav_impact_pct: float
    cvar_stressed: float | None = None
    block_impacts: dict[str, float]
    worst_block: str | None = None
    best_block: str | None = None
```

```python
# backend/app/domains/wealth/schemas/portfolio_view.py

class PortfolioViewCreate(BaseModel):
    asset_instrument_id: uuid.UUID | None = None
    peer_instrument_id: uuid.UUID | None = None
    view_type: str = Field(pattern=r"^(absolute|relative)$")
    expected_return: float
    confidence: float = Field(ge=0.01, le=1.0)
    rationale: str | None = None
    effective_from: date
    effective_to: date | None = None

class PortfolioViewRead(BaseModel):
    id: uuid.UUID
    portfolio_id: uuid.UUID
    asset_instrument_id: uuid.UUID | None = None
    peer_instrument_id: uuid.UUID | None = None
    view_type: str
    expected_return: float
    confidence: float
    rationale: str | None = None
    created_by: str | None = None
    effective_from: date
    effective_to: date | None = None
    created_at: datetime
```

```python
# backend/app/domains/wealth/schemas/analytics.py

class FactorAnalysisResponse(BaseModel):
    profile: str
    systematic_risk_pct: float
    specific_risk_pct: float
    factor_contributions: list[FactorContribution] = Field(default_factory=list)
    r_squared: float
    portfolio_factor_exposures: dict[str, float] = Field(default_factory=dict)
    as_of_date: date | None = None
```

---

## 2. Estado Atual da UI

### Estrutura de Rotas

```
frontends/wealth/src/routes/(app)/portfolio/models/
├── create/+page.svelte              # Wizard de criação
└── [portfolioId]/
    ├── +page.server.ts               # SSR load (portfolio, track-record, views, overlap)
    └── +page.svelte                  # Workbench principal (~57KB)
```

### Componentes Implementados

| Componente | Arquivo | Status |
|------------|---------|--------|
| ICViewsPanel | `lib/components/model-portfolio/ICViewsPanel.svelte` (796 linhas) | COMPLETO — CRUD absolute/relative, confidence slider, rationale, date range |
| Stress Test (histórico) | Inline no `[portfolioId]/+page.svelte` | COMPLETO — `runStress()` → POST `/stress`, scenarios table |
| Stress Test (paramétrico) | Inline no `[portfolioId]/+page.svelte` | COMPLETO — 4 presets (GFC, COVID, Taper, Rate Shock) + custom shocks por block |
| FactorContributionChart | `lib/components/analytics/FactorContributionChart.svelte` | COMPLETO — bar chart horizontal, systematic vs specific risk |
| ConstructionAdvisor | `lib/components/model-portfolio/ConstructionAdvisor.svelte` | COMPLETO — CVaR gap analysis + fund recommendations |
| CVaRHistoryChart | `lib/components/analytics/CVaRHistoryChart.svelte` | COMPLETO — série temporal CVaR |
| BacktestEquityCurve | `lib/components/analytics/BacktestEquityCurve.svelte` | COMPLETO — equity curve do backtest |

### SSR Data Flow

```typescript
// [portfolioId]/+page.server.ts
const [portfolio, trackRecord, factSheets, views, instruments, overlap, ...] = await Promise.all([
    api.get<ModelPortfolio>(`/model-portfolios/${params.portfolioId}`),
    api.get<TrackRecord>(`/model-portfolios/${params.portfolioId}/track-record`),
    api.get<PortfolioView[]>(`/model-portfolios/${params.portfolioId}/views`),
    api.get<OverlapResult>(`/model-portfolios/${params.portfolioId}/overlap`),
    // ...
]);
```

### TypeScript Types

```typescript
// frontends/wealth/src/lib/types/model-portfolio.ts

interface StressScenario {
    name: string; start_date: string; end_date: string;
    portfolio_return: number; max_drawdown: number; recovery_days: number | null;
}

interface ParametricStressResult {
    portfolio_id: string; scenario_name: string; nav_impact_pct: number;
    cvar_stressed: number | null; block_impacts: Record<string, number>;
    worst_block: string | null; best_block: string | null;
}

interface PortfolioView {
    id: string; portfolio_id: string; view_type: "absolute" | "relative";
    expected_return: number; confidence: number; rationale: string | null;
    effective_from: string; effective_to: string | null;
    asset_instrument_id: string | null; peer_instrument_id: string | null;
}

interface FactorAnalysisResult {
    profile: string; systematic_risk_pct: number; specific_risk_pct: number;
    factor_contributions: FactorContribution[]; r_squared: number;
    portfolio_factor_exposures: Record<string, number>;
}
```

---

## 3. API Client

`NetzApiClient` em `packages/ui/src/lib/utils/api-client.ts` (267 linhas) — genérico com `get<T>()`, `post<T>()`, `delete()`, retry logic, auth injection via Bearer token. Chamadas feitas inline nos componentes via URL path (sem métodos específicos por feature).

---

## 4. Gaps de Integração

| # | Gap | Severidade |
|---|-----|-----------|
| — | Nenhum gap crítico encontrado | — |

Todas as três features do quant upgrade estão plenamente integradas:

- **Stress Testing** — Ambos endpoints consumidos. UI com 4 presets + custom shocks por block. Optimistic updates.
- **Black-Litterman Views** — CRUD completo no ICViewsPanel. SSR load, role-gating para IC_ROLES.
- **Factor Models (PCA)** — FactorContributionChart renderiza decomposição systematic/specific. Endpoint tipado.

---

## 5. Oportunidades de Refinamento (não são gaps)

- Gráfico waterfall para `block_impacts` no stress paramétrico (hoje é tabela)
- Painel dedicado de Factor Exposure com drill-down por fundo
- Comparação side-by-side de cenários de stress
- Histórico de views (audit trail de mudanças IC)
