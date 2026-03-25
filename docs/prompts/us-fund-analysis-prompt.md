# Prompt: US Fund Analysis — Nova Página Wealth OS

## Contexto de produto

**O que é:** Ferramenta analítica de alto valor para análise de gestores e fundos
institucionais americanos. Usa dados SEC já populados no DB (sec_managers,
sec_13f_holdings, sec_13f_diffs). É uma página separada do Screener — o Screener
é catálogo de instrumentos, o US Fund Analysis é inteligência institucional.

**Dados disponíveis no DB:**
- `sec_managers` — 976k registros (CIK, name, entity_type, tickers, state, AUM quando ADV)
- `sec_13f_holdings` — 991k holdings trimestrais (cik, cusip, company_name, value, shares, quarter)
- `sec_13f_diffs` — variações quarter-over-quarter (new/increased/decreased/exited positions)

**URL:** `/us-fund-analysis`
**Nav:** Discovery & Screening section, após DD Reports

---

## Arquitetura da página

```
┌─────────────────────────────────────────────────────────────────┐
│  US Fund Analysis                           [Search manager...] │
├──────────────┬──────────────────────────────────────────────────┤
│  FILTER      │  MAIN CONTENT                                    │
│  SIDEBAR     │                                                  │
│              │  [tabs: Overview | Holdings | Style Drift |      │
│  Entity Type │        Reverse Lookup | Peer Compare]            │
│  ○ All       │                                                  │
│  ○ Investment│  (content by tab)                                │
│  ○ Operating │                                                  │
│  ○ Other     │                                                  │
│              │                                                  │
│  AUM Range   │                                                  │
│  State       │                                                  │
│  Has Ticker  │                                                  │
└──────────────┴──────────────────────────────────────────────────┘
```

## 5 tabs

### Tab 1: Overview (default)
- Tabela paginada de gestores com: Name, CIK, Entity Type, State, AUM, Tickers
- Server-side search + filter
- Click numa linha → abre detail panel lateral com tabs (Holdings, Drift, Filings)
- Endpoint: `GET /wealth/sec/managers/search` (já existe) ou criar

### Tab 2: Holdings
- Busca por gestor → mostra top holdings trimestrais
- Seleciona quarter → tabela com: Company, CUSIP, Shares, Value ($), % portfolio
- Delta vs quarter anterior (verde/vermelho)
- Endpoint: `GET /wealth/sec/managers/{cik}/holdings?quarter=YYYY-QN`

### Tab 3: Style Drift
- Seleciona gestor → chart de evolução de alocação setorial por quarter
- Stacked bar chart (ECharts) com % por setor ao longo do tempo
- Tabela de drift: sector, weight_current, weight_prev, delta, signal (DRIFT/STABLE)
- Endpoint: `GET /wealth/sec/managers/{cik}/style-drift`

### Tab 4: Reverse Lookup
- Busca por CUSIP ou ticker → quem possui este papel
- Tabela: Manager Name, Shares, Value, % do float, Quarter
- Filtrar por top N holders
- Endpoint: `GET /wealth/sec/holdings/reverse?cusip=XXX&quarter=YYYY-QN`

### Tab 5: Peer Compare
- Seleciona 2-5 gestores → compara AUM, concentração (HHI), top holdings sobrepostos
- Overlap matrix: % de overlap de portfólio entre pares
- Endpoint: `GET /wealth/sec/managers/compare?ciks=A,B,C`

---

## Backend — endpoints a criar em `app/domains/wealth/routes/`

### Arquivo: `sec_analysis.py` (novo)

```python
router = APIRouter(prefix="/sec", tags=["sec-analysis"])

GET  /sec/managers/search       — paginated, q, entity_type, state, has_ticker, has_aum
GET  /sec/managers/{cik}        — manager detail + latest holdings summary
GET  /sec/managers/{cik}/holdings — holdings by quarter (default: latest)
GET  /sec/managers/{cik}/style-drift — sector allocation history
GET  /sec/holdings/reverse      — reverse lookup by cusip
GET  /sec/managers/compare      — peer comparison (max 5 ciks)
```

Todos os endpoints:
- Lêem das tabelas GLOBAIS (`sec_managers`, `sec_13f_holdings`, `sec_13f_diffs`)
- Sem RLS, sem `organization_id`
- `@route_cache(ttl=300)` — dados mudam só trimestralmente
- Never-raises pattern

### Lógica de sector via SIC code:

`sec_managers.client_types` = `{"sic": "6726", "sic_description": "Investment Offices"}`

Mapeamento SIC → sector para style drift:
```python
SIC_TO_SECTOR = {
    "01xx": "Agriculture", "10xx-14xx": "Mining/Energy",
    "15xx-17xx": "Construction", "20xx-39xx": "Manufacturing",
    "40xx-49xx": "Utilities/Transport", "50xx-59xx": "Trade/Retail",
    "60xx-67xx": "Finance/Investment", "70xx-89xx": "Services",
}
```

### Holdings sector enrichment:

`sec_13f_holdings.company_name` → join com `sec_managers.firm_name` ou lookup pelo CUSIP
via `sec_cusip_ticker_map` para resolver setor.

---

## Frontend — `frontends/wealth/src/routes/(app)/us-fund-analysis/`

### Estrutura de arquivos:
```
us-fund-analysis/
  +page.svelte          ← página principal com tabs
  +page.server.ts       ← SSR: carrega managers iniciais
  components/
    ManagerTable.svelte       ← tab Overview
    HoldingsTable.svelte      ← tab Holdings
    StyleDriftChart.svelte    ← tab Style Drift (ECharts stacked bar)
    ReverseLookup.svelte      ← tab Reverse Lookup
    PeerCompare.svelte        ← tab Peer Compare
    ManagerDetailPanel.svelte ← side panel (reutilizável)
```

### Regras de implementação:
1. **Svelte 5 runes** — `$state`, `$derived`, `$effect`. Sem Svelte 4.
2. **fetch() + ReadableStream** para SSE quando aplicável (nunca EventSource)
3. **@netz/ui formatters** para números e datas (nunca `.toFixed()`)
4. **Lazy loading** — tabs carregam dados só quando ativadas
5. **ECharts** para Style Drift — mesmo setup do resto do Wealth OS
6. **Paginação server-side** — nunca carregar todos os 976k managers

### Design:
- Segue o sistema Thunder Client: IBM Plex Sans, tokens `var(--netz-*)`
- Tabelas com hover state, row click → detail panel
- Chips de tipo (Investment / Operating / All) no topo da sidebar
- Quarter selector para holdings: dropdown com últimos 8 quarters disponíveis

---

## Schemas TypeScript (criar em `$lib/types/sec-analysis.ts`)

```typescript
interface SecManager {
  crd_number: string;
  cik: string | null;
  firm_name: string;
  registration_status: string | null; // entity_type
  aum_total: number | null;
  state: string | null;
  tickers: string[];
  exchanges: string[];
  sic: string | null;
  sic_description: string | null;
}

interface SecHolding {
  cusip: string;
  company_name: string;
  shares: number;
  value: number;        // USD thousands
  pct_portfolio: number;
  period_of_report: string;
  delta_shares: number | null;
  delta_value: number | null;
}

interface StyleDriftPoint {
  quarter: string;
  sector: string;
  weight_pct: number;
}

interface ReverseLookupResult {
  cik: string;
  firm_name: string;
  shares: number;
  value: number;
  pct_float: number | null;
  quarter: string;
}
```

---

## Regras gerais

1. Sem imports entre verticais
2. `make check` deve passar
3. Tabelas com mais de 100 rows = paginação obrigatória
4. Todos os números financeiros via `@netz/ui` formatters
5. Error states e empty states para cada tab
6. Mobile: não priorizar, mas não quebrar layout

## Deploy após implementar

```powershell
pnpm --filter netz-wealth-os build
npx wrangler pages deploy frontends/wealth/.svelte-kit/cloudflare --project-name netz-wealth
```
