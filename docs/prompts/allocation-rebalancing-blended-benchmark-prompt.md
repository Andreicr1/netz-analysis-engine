# Prompt: Allocation Route Migration + Blended Benchmarks

## Contexto

Plataforma institucional Netz Analysis Engine. Stack: FastAPI async + SQLAlchemy + Svelte 5 runes + @netz/ui.

### O que existe hoje

**Frontend — `frontends/wealth/src/`:**
- `routes/(app)/portfolios/[profile]/+page.svelte` — Portfolio Workbench ativo, tem editor de pesos e tabs Strategic/Tactical/Effective, mas sem rota de allocation separada e sem tab de Rebalancing
- `lib/components/AllocationView.svelte` — componente de allocation com 3 tabs (Strategic/Tactical/Effective), self-loading, simulação CVaR
- `_legacy_routes/(team)/portfolios/[profile]/RebalancingTab.svelte` — componente completo de rebalancing com state machine (proposed→pending_review→approved→executing→executed), butterfly chart, before/after table, ConsequenceDialog duplo (approve + execute)
- `_legacy_routes/(team)/allocation/` — rota de allocation não migrada

**Backend:**
- `app/domains/wealth/models/block.py` — `AllocationBlock` com `block_id`, `geography`, `asset_class`, `display_name`, `benchmark_ticker`, `is_active`
- `app/domains/wealth/models/benchmark_nav.py` — `BenchmarkNav` com `block_id` (FK → allocation_blocks), `nav_date`, `nav`, `return_1d` (log returns)
- `app/domains/wealth/routes/allocation.py` — rotas `GET/PUT /{profile}/strategic`, `GET/PUT /{profile}/tactical`, `GET /{profile}/effective`, `POST /{profile}/simulate`
- `app/domains/wealth/routes/portfolios.py` — rotas de portfolio + rebalance
- `allocation_blocks` já tem seed com 16 blocos (SPY, QQQ, AGG, etc.)
- `benchmark_nav` será populado pelo worker após seed (hypertable global)

---

## Tarefa 1 — Migrar rota de allocation + integrar RebalancingTab

### 1a. Criar rota `/allocation` ativa

Criar `frontends/wealth/src/routes/(app)/allocation/+page.svelte` e `+page.server.ts` baseado no `_legacy_routes/(team)/allocation/`.

A página deve usar `AllocationView.svelte` (já existe em `lib/components/`) diretamente — não duplicar lógica.

### 1b. Integrar RebalancingTab no Portfolio Workbench

Em `routes/(app)/portfolios/[profile]/+page.svelte`, adicionar uma 4ª tab "Rebalancing" que usa o conteúdo de `_legacy_routes/(team)/portfolios/[profile]/RebalancingTab.svelte`.

**IMPORTANTE:** Mover o componente para `lib/components/RebalancingTab.svelte` e importar de lá. Não duplicar inline.

Props que RebalancingTab precisa:
```typescript
interface Props {
  profile: string;
  currentWeights: Record<string, number>;  // de snapshot.weights
  cvarCurrent: number | null;              // de live.cvar_current ou portfolio.cvar_current
  cvarLimit: number | null;                // de live.cvar_limit ou portfolio.cvar_limit
}
```

---

## Tarefa 2 — Blended Benchmarks (feature nova)

### Objetivo

Permitir que o usuário monte um benchmark composto para cada portfolio modelo, escolhendo índices/ETFs do DB (`allocation_blocks`) e atribuindo pesos. O benchmark blended é calculado como média ponderada dos retornos dos constituintes.

### 2a. Backend — nova tabela + service + rotas

**Migration Alembic** — nova tabela global (sem `organization_id`, sem RLS):

```sql
CREATE TABLE blended_benchmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_profile TEXT NOT NULL,     -- 'conservative' | 'moderate' | 'growth'
    name TEXT NOT NULL,                  -- ex: "60/40 Blend", "Moderate Custom"
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE blended_benchmark_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    benchmark_id UUID NOT NULL REFERENCES blended_benchmarks(id) ON DELETE CASCADE,
    block_id TEXT NOT NULL REFERENCES allocation_blocks(block_id),
    weight NUMERIC(6,4) NOT NULL CHECK (weight > 0 AND weight <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (benchmark_id, block_id)
);
-- Constraint: sum of weights per benchmark_id must = 1.0
-- Enforce via CHECK in service layer (trigger optional)

CREATE INDEX idx_blended_benchmark_components_benchmark_id
    ON blended_benchmark_components (benchmark_id);
```

**SQLAlchemy models** em `app/domains/wealth/models/blended_benchmark.py`:
- `BlendedBenchmark` — tabela `blended_benchmarks`, `lazy="raise"` nos relationships
- `BlendedBenchmarkComponent` — tabela `blended_benchmark_components`

**Pydantic schemas** em `app/domains/wealth/schemas/blended_benchmark.py`:
- `BlendedBenchmarkCreate` — `portfolio_profile`, `name`, lista de `{block_id, weight}`
- `BlendedBenchmarkRead` — inclui lista de componentes com `display_name`, `benchmark_ticker` do AllocationBlock
- `BlendedBenchmarkNAV` — série temporal calculada: `{date, nav, return_1d}`

**Service** `app/domains/wealth/services/blended_benchmark_service.py`:

```python
async def create_blended_benchmark(db, payload) -> BlendedBenchmark:
    # Valida: sum(weights) == 1.0 (tolerância 0.0001)
    # Valida: todos block_ids existem e têm benchmark_ticker
    # Upsert: desativa benchmark anterior do mesmo profile se is_active
    ...

async def compute_blended_nav(db, benchmark_id: UUID, lookback_days: int = 365) -> list[BlendedBenchmarkNAV]:
    # JOIN benchmark_nav ON block_id para todos os componentes
    # Weighted sum: sum(component.weight * nav.return_1d)
    # Acumula retorno log para reconstituir série de NAV indexada a 100
    # Retorna série diária alinhada (inner join por data)
    ...

async def list_available_blocks(db) -> list[dict]:
    # SELECT block_id, display_name, benchmark_ticker, geography, asset_class
    # FROM allocation_blocks
    # WHERE is_active = true AND benchmark_ticker IS NOT NULL
    # ORDER BY geography, asset_class
    ...
```

**Rotas** em `app/domains/wealth/routes/blended_benchmark.py` (registrar em `main.py`):

```
GET    /blended-benchmarks/blocks          → lista blocos disponíveis para compor
GET    /blended-benchmarks/{profile}       → benchmark ativo do profile + componentes
POST   /blended-benchmarks/{profile}       → cria/substitui benchmark do profile
GET    /blended-benchmarks/{id}/nav        → série temporal calculada (query: ?lookback_days=365)
DELETE /blended-benchmarks/{id}            → desativa
```

Regras:
- Tabelas são globais — sem RLS, sem `organization_id`
- `GET /blocks` é público (sem auth) para o frontend poder fazer typeahead
- `POST` e `DELETE` exigem `require_ic_member`
- `lazy="raise"` + `selectinload()` explícito

### 2b. Frontend — componente de edição

Criar `frontends/wealth/src/lib/components/BlendedBenchmarkEditor.svelte`:

**Props:**
```typescript
interface Props {
  profile: string;       // 'conservative' | 'moderate' | 'growth'
  onSaved?: () => void;  // callback após salvar
}
```

**UX:**
1. Ao montar, carrega `GET /blended-benchmarks/{profile}` (benchmark atual) e `GET /blended-benchmarks/blocks` (disponíveis)
2. Exibe lista de componentes atuais com peso e sparkline do NAV individual (se disponível)
3. Campo de busca com typeahead sobre `list_available_blocks` — filtrável por `display_name`, `geography`, `asset_class`
4. Ao selecionar um bloco: adiciona à lista de componentes com peso default `= (1 / total_components)` auto-normalizado
5. Barra de total de pesos — verde se == 100%, vermelho se diferente — impede salvar
6. Botão "Normalize" que distribui proporcionalmente os pesos para somar 100%
7. ConsequenceDialog ao salvar: mostra componentes e pesos, exige rationale (min 10 chars)
8. Após salvar: mostra série temporal do benchmark blended via `GET /blended-benchmarks/{id}/nav`

**Usar componentes @netz/ui:** `Input`, `Button`, `ActionButton`, `ConsequenceDialog`, `EmptyState`, `MetricCard`, `SectionCard`. Para o gráfico de NAV blended usar `ChartContainer` do `@netz/ui/charts` com ECharts.

### 2c. Integrar no Portfolio Workbench

Em `routes/(app)/portfolios/[profile]/+page.svelte`, adicionar uma 5ª tab "Benchmark" que usa `BlendedBenchmarkEditor` com `profile={profile}`.

Após salvar um blended benchmark, o componente deve exibir a série de NAV blended sobreposta ao NAV do portfólio (se disponível no `snapshot`).

---

## Regras obrigatórias

1. **async def** + **AsyncSession** em todo o backend. Nunca sync Session.
2. **`lazy="raise"`** em todos os relationships. Usar `selectinload()` ou `joinedload()` explícito.
3. **`expire_on_commit=False`** nas sessions.
4. **Global tables**: `blended_benchmarks` e `blended_benchmark_components` sem `organization_id`, sem RLS.
5. **Import-linter**: não importar `vertical_engines` nem `app.domains` de dentro de `data_providers`.
6. **Never-raises pattern** nos services: capturar exceções e retornar defaults seguros.
7. **Svelte 5 runes**: usar `$state`, `$derived`, `$effect`, `$props`. Nunca `writable()`, `readable()` do Svelte 4.
8. **Formatação**: sempre `formatPercent()`, `formatNumber()`, `formatDateTime()` de `@netz/ui`. Nunca `.toFixed()` ou `.toLocaleString()`.
9. **SSE**: se precisar de updates em tempo real, usar `fetch()` + `ReadableStream`. Nunca `EventSource`.
10. **Migrations**: usar autocommit para `create_hypertable()`. Não rodar dentro de transaction.
11. **Pesos**: validar `sum(weights) ≈ 1.0` (tolerância `abs < 0.0001`) tanto no backend (HTTPException 422) quanto no frontend (disable submit button).

---

## Arquivos a criar/modificar

**Backend (novos):**
- `backend/app/domains/wealth/models/blended_benchmark.py`
- `backend/app/domains/wealth/schemas/blended_benchmark.py`
- `backend/app/domains/wealth/services/blended_benchmark_service.py`
- `backend/app/domains/wealth/routes/blended_benchmark.py`
- `backend/app/core/db/migrations/versions/XXXX_blended_benchmarks.py`

**Backend (modificar):**
- `backend/app/main.py` — registrar router de blended_benchmark
- `backend/app/shared/models.py` — adicionar imports dos novos models se necessário

**Frontend (novos):**
- `frontends/wealth/src/lib/components/BlendedBenchmarkEditor.svelte`
- `frontends/wealth/src/lib/components/RebalancingTab.svelte` (movido de legacy)
- `frontends/wealth/src/routes/(app)/allocation/+page.svelte`
- `frontends/wealth/src/routes/(app)/allocation/+page.server.ts`

**Frontend (modificar):**
- `frontends/wealth/src/routes/(app)/portfolios/[profile]/+page.svelte` — adicionar tabs Rebalancing + Benchmark

---

## Critérios de sucesso

- `make check` passa (lint + typecheck + todos os testes existentes)
- Rota `/allocation` acessível no app wealth
- Tab "Rebalancing" funcional no Portfolio Workbench com state machine completa
- Tab "Benchmark" permite criar blended benchmark com busca de blocos, validação de pesos e persistência
- Série temporal blended calculada corretamente (retornos log ponderados → NAV indexado a 100)
- Nenhuma chamada a API externa em user-facing requests (tudo via DB)
