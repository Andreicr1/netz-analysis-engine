# Prompt: Global Financial Instrument Screener — Upgrade Completo

## Contexto

Plataforma Netz Analysis Engine. Stack: FastAPI async + SQLAlchemy + SvelteKit 5 runes + @netz/ui.

## Diagnóstico do Estado Atual

### O que existe (e funciona)
- `routes/(app)/screener/+page.svelte` — screener Manager-centric (SEC)
- `vertical_engines/wealth/screener/` — engine de 3 camadas (L1 eliminatório, L2 mandate fit, L3 quant)
- `app/domains/wealth/routes/screener.py` — `POST /screener/run`, `GET /screener/results`
- `app/domains/wealth/routes/manager_screener.py` — managers SEC paginados, holdings, institutional
- `instruments_universe` — tabela polimórfica (fund | bond | equity) com JSONB attributes, `block_id` FK, `geography`, `asset_class`, `currency`
- `esma_funds` + `esma_isin_ticker_map` — universo UCITS com tickers resolvidos
- `esma_nav_history` — série temporal de NAV dos UCITS operáveis
- `sec_managers` — 16k managers US com AUM, compliance, CIK
- `sec_13f_holdings` + `sec_13f_diffs` — holdings trimestrais

### Problemas críticos
1. **Filtro client-side**: `GET /screener/results` carrega 500 instrumentos e filtra em Svelte. Não escala.
2. **Sem server-side search**: busca por nome, ISIN, ticker, manager não existe no backend.
3. **ESMA desconectado**: `esma_funds` não está em `instruments_universe`. Fundos europeus não aparecem no screener.
4. **Asset class única**: screener só mostra fundos US (via manager → fund sub-row). Bonds, ETFs, equities, hedge funds europeus não são selecionáveis.
5. **Sem filtros de dimensão**: geography, domicile, currency, strategy, AUM range, structure (UCITS/Cayman/LP) não são filtráveis via URL.
6. **Sem métricas de risco nos resultados**: retorno 1Y/3M, volatilidade, Sharpe não estão em `ScreeningResult`.
7. **Sem modo "instrument-first"**: o screener atual é Manager→Fund hierárquico. Não há modo de busca plana por instrumento.

---

## Tarefa 1 — Backend: Endpoint de Search Global

### 1a. Novo endpoint `GET /screener/search`

Em `app/domains/wealth/routes/screener.py`, adicionar:

```python
@router.get("/search", response_model=InstrumentSearchPage)
async def search_instruments(
    q: str | None = Query(None),              # busca full-text: nome, ISIN, ticker, manager
    instrument_type: str | None = Query(None), # fund | bond | equity | etf | hedge_fund
    asset_class: str | None = Query(None),     # equity | fixed_income | alternatives | cash
    geography: str | None = Query(None),       # north_america | dm_europe | em | global | ...
    domicile: str | None = Query(None),        # US | IE | LU | KY | ... (ISO-2)
    currency: str | None = Query(None),        # USD | EUR | GBP | BRL
    strategy: str | None = Query(None),        # long_only | long_short | market_neutral | ...
    aum_min: float | None = Query(None),
    aum_max: float | None = Query(None),
    block_id: str | None = Query(None),
    approval_status: str | None = Query(None), # approved | pending | watchlist
    source: str | None = Query(None),          # internal | esma | sec  (origem do instrumento)
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
) -> InstrumentSearchPage:
```

**Lógica:**
- Busca primária em `instruments_universe` (tabela org-scoped com RLS)
- Se `source=esma` ou `instrument_type=fund` sem resultados internos: busca também em `esma_funds` JOIN `esma_isin_ticker_map` WHERE `is_tradeable=TRUE`
- Busca full-text (`q`): `ilike` em `name`, `isin`, `ticker`. Para ESMA: `fund_name`, `isin`, `yahoo_ticker`.
- Retorna `InstrumentSearchPage` com `total`, `page`, `has_next`, `items: list[InstrumentSearchItem]`

**Schema `InstrumentSearchItem`** (Pydantic):
```python
class InstrumentSearchItem(BaseModel):
    instrument_id: str | None       # UUID se for instruments_universe, None se for ESMA-only
    source: str                     # "internal" | "esma" | "sec"
    instrument_type: str            # fund | bond | equity | etf | hedge_fund
    name: str
    isin: str | None
    ticker: str | None
    asset_class: str
    geography: str
    domicile: str | None
    currency: str
    strategy: str | None
    aum: float | None
    manager_name: str | None
    manager_crd: str | None         # se source=sec
    esma_manager_id: str | None     # se source=esma
    approval_status: str | None     # None se for ESMA-only (ainda não no universe)
    screening_status: str | None    # PASS | FAIL | WATCHLIST | None se não screened
    screening_score: float | None
    nav_1y_return: float | None     # calculado de esma_nav_history ou fund_risk_metrics
    nav_3m_return: float | None
    block_id: str | None
    structure: str | None           # UCITS | Cayman LP | Delaware LP | SICAV (de attributes JSONB)
```

### 1b. Endpoint `GET /screener/facets`

Retorna contagens por dimensão para alimentar os filtros do sidebar dinamicamente:

```python
@router.get("/facets", response_model=ScreenerFacets)
async def get_screener_facets(
    # Aceita os mesmos parâmetros de /search para facets contextuais
    ...
) -> ScreenerFacets:
```

```python
class ScreenerFacets(BaseModel):
    instrument_types: list[FacetItem]   # [{value: "fund", count: 143}, ...]
    geographies: list[FacetItem]
    asset_classes: list[FacetItem]
    domiciles: list[FacetItem]
    currencies: list[FacetItem]
    strategies: list[FacetItem]
    sources: list[FacetItem]            # internal / esma / sec
    screening_statuses: list[FacetItem] # PASS / FAIL / WATCHLIST / unscreened
    total_universe: int
    total_screened: int
    total_approved: int

class FacetItem(BaseModel):
    value: str
    label: str
    count: int
```

### 1c. Serviço de import ESMA → Universe

Adicionar em `app/domains/wealth/services/` um `esma_import_service.py`:

```python
async def import_esma_fund_to_universe(
    db: AsyncSession,
    org_id: uuid.UUID,
    isin: str,
    *,
    block_id: str | None = None,
    strategy: str | None = None,
) -> Instrument:
    """Cria um Instrument em instruments_universe a partir de esma_funds.

    Busca fund_name, esma_manager_id, domicile de esma_funds.
    Busca yahoo_ticker de esma_isin_ticker_map.
    Determina currency e geography do domicile.
    Popula attributes JSONB com: structure=UCITS, domicile, fund_type, host_member_states.
    """
```

Adicionar rota `POST /screener/import-esma/{isin}` que chama esse service.

---

## Tarefa 2 — Frontend: Screener Global com Modo Duplo

Reescrever `frontends/wealth/src/routes/(app)/screener/+page.svelte` com **dois modos**:

### Modo A: Instrument Search (padrão, novo)
- Sidebar com filtros server-side: busca textual, instrument_type (chips), geography (dropdown), domicile, currency, strategy, AUM range, source (Internal/ESMA/SEC), approval_status
- Facets dinâmicos carregados de `GET /screener/facets` — atualizam counts à medida que filtros são aplicados
- Resultado: tabela plana paginada (não hierárquica) com colunas:
  - Nome + ISIN/ticker
  - Tipo (badge colorido: Fund/ETF/Bond/Equity/Hedge Fund)
  - Source (Internal/ESMA/SEC)
  - Manager
  - AUM
  - Geography/Domicile
  - Currency
  - Retorno 1Y (se disponível)
  - Score / Status (PASS/FAIL/WATCHLIST/—)
  - Ação: "Add to Universe" (se source=esma/sec e não está em universe) ou "View" (se interno)

### Modo B: Manager Screener (existente, preservado)
- Manter o comportamento atual (hierárquico Manager→Fund)
- Toggle entre modos via tab ou botão no topo da página

### Painel de Detalhe (ContextPanel)
Para qualquer instrumento clicado, exibir:
- Dados básicos: nome, ISIN, ticker, tipo, manager, AUM, domicile, currency, structure
- Métricas de risco (se disponíveis): retorno 1Y/3M/YTD, volatilidade, Sharpe, drawdown
- Série temporal NAV (mini sparkline via `esma_nav_history` ou `nav_timeseries`)
- Resultado de screening: layers L1/L2/L3 com critérios
- Botão "Add to Universe" com ConsequenceDialog se ainda não estiver

### Mudanças no `+page.server.ts`

```typescript
// Carregar facets + resultados iniciais em paralelo
const [facets, results, runs] = await Promise.all([
    api.get("/screener/facets").catch(() => null),
    api.get("/screener/search", { page: "1", page_size: "50", ...urlParams }).catch(() => ({ items: [], total: 0 })),
    api.get("/screener/runs", { limit: "1" }).catch(() => []),
]);
```

---

## Tarefa 3 — Frontend: Filtros e Chips de Asset Class

No sidebar do modo Instrument Search, adicionar chips visuais (não dropdowns) para `instrument_type`:

```
[Todos] [Fundos US] [UCITS/EU] [ETFs] [Bonds] [Equities] [Hedge Funds]
```

Cada chip mapeia para:
```typescript
const TYPE_FILTERS = {
    "Fundos US": { source: "sec", instrument_type: "fund" },
    "UCITS/EU":  { source: "esma", instrument_type: "fund" },
    "ETFs":      { instrument_type: "etf" },
    "Bonds":     { instrument_type: "bond" },
    "Equities":  { instrument_type: "equity" },
    "Hedge Funds": { instrument_type: "hedge_fund" },
};
```

---

## Tarefa 4 — Types TypeScript

Criar/atualizar `frontends/wealth/src/lib/types/screener.ts`:

```typescript
export interface InstrumentSearchItem {
    instrument_id: string | null;
    source: "internal" | "esma" | "sec";
    instrument_type: "fund" | "bond" | "equity" | "etf" | "hedge_fund";
    name: string;
    isin: string | null;
    ticker: string | null;
    asset_class: string;
    geography: string;
    domicile: string | null;
    currency: string;
    strategy: string | null;
    aum: number | null;
    manager_name: string | null;
    manager_crd: string | null;
    esma_manager_id: string | null;
    approval_status: string | null;
    screening_status: "PASS" | "FAIL" | "WATCHLIST" | null;
    screening_score: number | null;
    nav_1y_return: number | null;
    nav_3m_return: number | null;
    block_id: string | null;
    structure: string | null;
}

export interface InstrumentSearchPage {
    items: InstrumentSearchItem[];
    total: number;
    page: number;
    page_size: number;
    has_next: boolean;
}

export interface FacetItem {
    value: string;
    label: string;
    count: number;
}

export interface ScreenerFacets {
    instrument_types: FacetItem[];
    geographies: FacetItem[];
    asset_classes: FacetItem[];
    domiciles: FacetItem[];
    currencies: FacetItem[];
    strategies: FacetItem[];
    sources: FacetItem[];
    screening_statuses: FacetItem[];
    total_universe: number;
    total_screened: number;
    total_approved: number;
}
```

---

## Regras Obrigatórias

1. **Async-first**: `async def` + `AsyncSession` em todo o backend. Nunca sync Session.
2. **`lazy="raise"`** em todos os relationships. `selectinload()` explícito.
3. **RLS**: `instruments_universe` tem `organization_id` + RLS. `esma_funds`, `sec_managers` são globais (sem RLS).
4. **Server-side filters**: NUNCA filtrar no frontend o que pode ser filtrado no SQL.
5. **Import-linter**: `vertical_engines` não importa `app.domains`. `data_providers` não importa verticals.
6. **Never-raises**: services capturam exceções e retornam defaults. Endpoint retorna 200 com lista vazia em vez de 500.
7. **Svelte 5 runes**: `$state`, `$derived`, `$effect`, `$props`. Sem `writable()` Svelte 4.
8. **Formatação**: `formatAUM()`, `formatPercent()`, `formatNumber()` de `@netz/ui`. Nunca `.toFixed()`.
9. **DB-first**: retornos NAV calculados via query em `esma_nav_history` ou `fund_risk_metrics`. Nunca chamar Yahoo Finance em user-facing requests.
10. **Paginação**: `page` + `page_size` server-side. Frontend não carrega tudo de uma vez.
11. **`make check` deve passar** após as mudanças (lint + typecheck + testes existentes).

---

## Arquivos a Criar/Modificar

**Backend (novos):**
- `app/domains/wealth/schemas/instrument_search.py` — InstrumentSearchItem, InstrumentSearchPage, ScreenerFacets, FacetItem
- `app/domains/wealth/services/esma_import_service.py` — import ESMA fund → instruments_universe

**Backend (modificar):**
- `app/domains/wealth/routes/screener.py` — adicionar `GET /search` e `GET /facets` e `POST /import-esma/{isin}`

**Frontend (novos):**
- `lib/types/screener.ts` — tipos TypeScript

**Frontend (modificar):**
- `routes/(app)/screener/+page.server.ts` — carregar facets + search results
- `routes/(app)/screener/+page.svelte` — reescrever com modo duplo (instrument search + manager screener)

---

## Critério de Sucesso

- `GET /screener/search?q=pimco` retorna fundos US e UCITS da Pimco em resultado único
- `GET /screener/search?source=esma&geography=dm_europe` retorna fundos UCITS europeus paginados
- `GET /screener/search?instrument_type=etf` retorna ETFs do universe
- `GET /screener/facets` retorna contagens por tipo, geography, source
- Sidebar do screener tem chips de asset class clicáveis que disparam busca server-side
- Clicar em fundo ESMA mostra painel com dados do `esma_funds` + NAV de `esma_nav_history`
- Botão "Add to Universe" em fundo ESMA chama `POST /screener/import-esma/{isin}` com ConsequenceDialog
- Modo Manager Screener (hierárquico) ainda funciona via toggle
- `make check` verde
