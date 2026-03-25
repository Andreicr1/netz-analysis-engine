# Prompt: Screener Redesign — Stacked Layout + 4 Tabs com Filtros por Tipo

## Contexto

O Screener precisa ser reescrito: o layout muda de sidebar+table para **stacked cards**
(filter card em cima, results card embaixo, sem sidebar). Suporta 4 tabs com filtros
e colunas específicos por tipo de instrumento. A tabela de resultados é a mesma para
todas as tabs, mas com colunas polimórficas.

**Manager screener removido:** Todo o código de manager mode, peer comparison,
`ManagerFilterSidebar`, `ManagerHierarchyTable`, `ManagerDetailPanel` sai do screener.
A funcionalidade de análise de gestores migra para `/us-fund-analysis` (prompt separado).

## Fontes de dados disponíveis no DB

| Tab | Fonte | Tabela | Rows |
|-----|-------|--------|------|
| Funds | ESMA | `esma_funds` + `esma_managers` | 10.435 UCITS |
| Funds | SEC US | `sec_managers` WHERE `registration_status='investment'` | 3.899 investment companies |
| Funds | SEC US Advisers | `sec_managers` WHERE `registration_status='Registered'` | 15.963 com AUM (Vanguard, Fidelity etc.) |
| Funds | Internal | `instruments_universe` (org-scoped) | 0 (cresce com DD approvals) |
| Equities | yfinance seed | `instruments_global` WHERE `instrument_type='equity'` | ~217 S&P 500 |
| ETF | yfinance seed | `instruments_global` WHERE `instrument_type='etf'` | ~41 broad market |
| Fixed Income | yfinance seed (bond ETFs) | `instruments_global` WHERE `instrument_type='bond'` | ~12 bond ETFs |

## Distinção crítica — sec_managers para o tab Funds

`sec_managers` tem dois tipos de entidades relevantes para o screener:

1. **Investment Advisers** (`registration_status='Registered'`, 15.963 rows):
   - São as firmas gestoras — Vanguard, Fidelity, BlackRock, PIMCO
   - Têm AUM, state, website, fee_types, client_types do Form ADV
   - SOURCE badge: "SEC ADV"
   - Aparecem no tab Funds como gestores com AUM agregado
   - Linking para o US Fund Analysis page para drill-down

2. **Investment Companies** (`registration_status='investment'`, 3.899 rows):
   - São os veículos de investimento registrados (mutual funds, closed-end funds)
   - Vêm dos submissions EDGAR — têm CIK, name, tickers quando disponíveis
   - Precisam de enriquecimento via OpenFIGI/yfinance para obter NAV, retorno
   - SOURCE badge: "SEC"

3. **N-PORT funds** (futuro — worker pendente):
   - Fundos que fazem filing N-PORT = fundos abertos registrados
   - Virão com CUSIP dos holdings, fund identifier, NAV mensal

## union_all para o tab Funds

```sql
-- Tab Funds = 4 fontes
SELECT ... FROM esma_funds                                              -- UCITS europeus
UNION ALL
SELECT ... FROM instruments_universe WHERE organization_id = $1        -- aprovados internamente
UNION ALL
SELECT ... FROM sec_managers WHERE registration_status = 'investment'  -- investment companies US
UNION ALL
SELECT ... FROM sec_managers WHERE registration_status = 'Registered'  -- advisers US com AUM
```

Filtro SOURCE no frontend:
- "ESMA" → só esma_funds
- "SEC" → só sec_managers (ambos tipos)
- "Internal" → só instruments_universe
- null → tudo

## Estrutura de tabs e filtros

### Tab 1: Funds
Filtros: Asset Class (dropdown), AUM min (number), Geography (dropdown), Type (dropdown: All/UCITS/Internal)
Colunas: NAME+ISIN, TYPE badge, SOURCE badge (ESMA/Internal), MANAGER/ISSUER, AUM, RETURN

### Tab 2: Equities
Filtros: Sector (dropdown), Market Cap min (dropdown: Any/Small/Mid/Large/Mega), P/E max (number), Dividend Yield min % (number)
Colunas: NAME+TICKER, TYPE badge, SOURCE badge (exchange: NASDAQ/NYSE), MANAGER/ISSUER (company name), MARKET CAP, DIV YIELD

### Tab 3: Fixed Income
Filtros: Asset Class (IG/HY/Govt/Muni — from attributes), Maturity Range (dropdown), YTM min % (number), Issuer Type (dropdown)
Colunas: NAME+CUSIP, TYPE badge (FIXED INCOME), SOURCE badge (yfinance/FINRA when available), ISSUER, MATURITY, YTM
Nota: por agora são bond ETFs (AGG, TLT, LQD, HYG etc). FINRA individual bonds virão depois.

### Tab 4: ETF
Filtros: Asset Class (dropdown), Issuer/Fund Family (text), Expense Ratio max % (number), Tracking Error max % (number)
Colunas: NAME+TICKER, TYPE badge (ETF), SOURCE badge (exchange), ISSUER (fund_family from attributes), AUM (totalAssets), EXPENSE RATIO

## Coluna polimórfica AUM/CAP/MAT
- Funds → AUM formatado ($1.2B, $4.5T)
- Equities → Market Cap ($2.8T, $450B)
- Fixed Income → Maturity (10 Yrs, 5 Yrs, 2033)
- ETF → AUM (totalAssets)

## Coluna polimórfica RET/YLD
- Funds → 1Y Return % (de nav_timeseries quando disponível, senão vazio)
- Equities → Dividend Yield % (do yfinance attributes)
- Fixed Income → YTM % (do yfinance attributes ou calculado)
- ETF → Expense Ratio % com label "ER" (annualReportExpenseRatio nos attributes)

## Mudanças no Backend — screener.py

### tab substitui instrument_type como roteador principal

**CRÍTICO:** O `search_instruments` atual usa `instrument_type` para decidir quais
sub-queries incluir no union_all (`_build_internal_query`, `_build_esma_query`,
`_build_global_query`). O novo parâmetro `tab` **substitui** `instrument_type` como
roteador primário. Se ambos chegarem no request, `tab` tem prioridade e `instrument_type`
é ignorado. O frontend deve enviar apenas `tab`, nunca `instrument_type` diretamente.

Mapeamento:
- `tab=fund` → inclui internal + esma + sec sub-queries (exclui instruments_global)
- `tab=equity` → só `_build_global_query` WHERE `instrument_type='equity'`
- `tab=etf` → só `_build_global_query` WHERE `instrument_type='etf'`
- `tab=bond` → só `_build_global_query` WHERE `instrument_type='bond'`
- `tab=None` → union_all de tudo (backwards compat, equivale a tab=fund + global types)

### Novos query params no GET /screener/search
```python
# Tab routing (replaces instrument_type as primary router)
tab: str | None = Query(None)  # "fund"|"equity"|"bond"|"etf"

# Equity filters
sector: str | None = Query(None)
market_cap_min: float | None = Query(None)
pe_max: float | None = Query(None)
div_yield_min: float | None = Query(None)

# ETF filters
fund_family: str | None = Query(None)
expense_ratio_max: float | None = Query(None)

# Fixed Income filters
bond_asset_class: str | None = Query(None)  # ig|hy|govt|muni
maturity_range: str | None = Query(None)    # 0-2|2-5|5-10|10+
ytm_min: float | None = Query(None)
```

### Filtros em JSONB attributes para instruments_global
```python
if sector:
    stmt = stmt.where(InstrumentGlobal.attributes["sector"].astext == sector)
if market_cap_min:
    stmt = stmt.where(
        InstrumentGlobal.market_cap >= market_cap_min
    )
if expense_ratio_max:
    stmt = stmt.where(
        InstrumentGlobal.attributes["expense_ratio"].astext.cast(Float) <= expense_ratio_max
    )
```

### Enrich response — campos numéricos separados (NÃO strings formatadas)

**Regra: NUNCA retornar valores formatados do backend.** Toda formatação de números,
moedas e datas é feita no frontend via `@netz/ui` formatters (`formatNumber`,
`formatCurrency`, `formatPercent`). O backend retorna campos numéricos puros.

Adicionar ao `InstrumentSearchItem` schema no backend (`schemas/screening.py`):
```python
market_cap: float | None = None       # em USD, para equities
return_1y: float | None = None        # decimal (0.054 = 5.4%), para funds
dividend_yield: float | None = None   # decimal, para equities
ytm: float | None = None              # decimal, para fixed income
expense_ratio: float | None = None    # decimal, para ETFs
maturity_date: str | None = None      # ISO date string, para fixed income
exchange: str | None = None           # NMS, NYQ, PCX etc. para SOURCE badge
```

O frontend decide qual campo mostrar na coluna polimórfica com base na tab ativa.

## Mudanças no Frontend

### Layout: stacked cards, sem sidebar

**CRÍTICO: O layout muda fundamentalmente.** O grid `260px 1fr` (sidebar + main) é
eliminado. O novo layout é vertical (stacked):

```
┌──────────────────────────────────────────────────────────┐
│  PageHeader: "Screener"       [Export] [Add to Portfolio] │
├──────────────────────────────────────────────────────────┤
│  FilterCard (border, rounded-16px, shadow)                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  [Funds] [Equities] [Fixed Income] [ETF]  ← tabs    │ │
│  ├──────────────────────────────────────────────────────┤ │
│  │  SEARCH: [________________________]                  │ │
│  │                                                      │ │
│  │  [Asset Class ▾]  [AUM min]  [Geography ▾]  [Type ▾] │ │
│  │                                                      │ │
│  │                          [Clear]  [Apply Filters]    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ResultsCard (border, rounded-16px, shadow)               │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Results  [4 INSTRUMENTS]         Sort by: Name (A-Z) │ │
│  ├──────────────────────────────────────────────────────┤ │
│  │  ☐  NAME           TYPE   SOURCE  MANAGER  AUM  RET  │ │
│  │  ☐  Fund Name      FUNDS  ESMA    Mgr      $1B  5%   │ │
│  │  ☐  Fund Name      FUNDS  SEC     Mgr      $4B  12%  │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Arquivo: +page.svelte — REWRITE

**Remover completamente:**
- Todo o código de `ScreenerMode` (`instruments` | `managers`)
- Imports e uso de: `ManagerFilterSidebar`, `ManagerHierarchyTable`,
  `PeerComparisonView`, `ManagerDetailPanel`
- Estado de: `expandedManagers`, `selectedManagers`, `canCompare`,
  `compareResult`, `comparing`, `compareError`, peer comparison functions
- O layout grid sidebar (`scr-grid` com `260px 1fr`)
- `InstrumentFilterSidebar` como componente sidebar

**Novo layout:**
- Stacked cards: FilterCard (com tabs + search + dropdowns inline) + ResultsCard
- Tab state via URL param: `/screener?tab=equity`
- Filtros inline dentro do FilterCard (não sidebar separado)
- O FilterCard pode ser um novo componente `ScreenerFilters.svelte` ou inline no +page

### Arquivo: +page.server.ts — ATUALIZAR

O server load precisa:
1. Ler `tab` dos URL search params (default: `fund`)
2. Passar `tab` como parâmetro para `GET /screener/search?tab=X`
3. Carregar facets filtrados por tab (se aplicável)
4. Retornar `tab` no `PageData` para o frontend saber qual tab está ativa

### Arquivo: InstrumentTable.svelte — atualizar colunas

Recebe `activeTab` como prop para decidir colunas polimórficas.

Colunas fixas para todas as tabs:
- Checkbox de seleção
- NAME (com identificador abaixo: ISIN para funds, ticker para equities/ETF, CUSIP para bonds — monospace, bg cinza)
- TYPE (badge com cor por tipo)
- SOURCE (badge derivado de `row.source` + `row.exchange` — ver lógica abaixo)
- MANAGER / ISSUER (texto clicável, cor brand-primary)
- AUM / CAP / MAT (polimórfico por tab, alinhado direita, formatado via `@netz/ui`)
- RET / YLD (polimórfico por tab, alinhado direita, formatado via `@netz/ui`)
- Info icon (ℹ) para abrir detail panel

### Arquivo: screening.ts — ATUALIZAR tipos

Adicionar ao `InstrumentSearchItem`:
```typescript
market_cap: number | null;
return_1y: number | null;
dividend_yield: number | null;
ytm: number | null;
expense_ratio: number | null;
maturity_date: string | null;
exchange: string | null;
```

### SOURCE badge por origem

**IMPORTANTE:** Os badges "MORNINGSTAR" vistos no wireframe Figma são placeholders
ilustrativos do designer. Esses dados NÃO existem no sistema. Os badges reais são
derivados exclusivamente de `row.source` e `row.exchange` conforme a lógica abaixo:

```typescript
function getSourceBadge(row: InstrumentSearchItem): { label: string; color: string } {
  if (row.source === "esma") return { label: "ESMA", color: "green" };
  if (row.source === "sec") return { label: "SEC", color: "blue" };
  if (row.exchange === "NMS" || row.exchange === "NGM") return { label: "NASDAQ", color: "blue" };
  if (row.exchange === "NYQ" || row.exchange === "PCX") return { label: "NYSE ARCA", color: "blue" };
  if (row.source === "internal") return { label: "INTERNAL", color: "purple" };
  return { label: row.exchange ?? "GLOBAL", color: "gray" };
}
```

## Índices disponíveis (migration 0047 — já aplicada)

Todos os índices necessários para performance dos filtros já estão criados:

**instruments_global:**
| Índice | Tipo | Finalidade |
|--------|------|------------|
| `ix_instruments_global_instrument_type` | btree | Tab routing (equity/etf/bond) |
| `ix_instruments_global_asset_class` | btree | Asset Class dropdown |
| `ix_instruments_global_geography` | btree | Geography dropdown |
| `idx_instruments_global_sector` | btree | Equities: Sector dropdown |
| `idx_instruments_global_exchange` | btree partial | SOURCE badge filter |
| `idx_instruments_global_market_cap` | btree partial | Equities: Market Cap min |
| `idx_instruments_global_attributes_gin` | GIN jsonb_path_ops | ETF: expense_ratio, Bond: YTM, fund_family |
| `idx_instruments_global_type_cap` | btree composite | Equities: type + market cap sort |

**sec_managers (Funds tab — SEC sources):**
| Índice | Tipo | Finalidade |
|--------|------|------------|
| `idx_sec_managers_investment` | btree partial (investment) | Investment companies por AUM |
| `idx_sec_managers_registered_aum` | btree partial (Registered) | Advisers por AUM |
| `idx_sec_managers_name_trgm` | GIN trigram | Search box fuzzy |
| `idx_sec_managers_reg_status` | btree | Entity type filter |
| `idx_sec_managers_status_aum` | btree composite | Status + AUM filtered sort |

**esma_funds / esma_managers:**
| Índice | Tipo | Finalidade |
|--------|------|------------|
| `idx_esma_funds_domicile` | btree | Geography filter |
| `idx_esma_funds_fund_type` | btree | Strategy/fund type filter |
| `idx_esma_funds_domicile_type` | btree composite | Geography + type combined |
| `idx_esma_managers_name_trgm` | GIN trigram | Search box fuzzy |

**NÃO criar novos índices.** Usar os existentes nas queries. Se um filtro não tem índice
dedicado (ex: filtros JSONB em `attributes`), o GIN `idx_instruments_global_attributes_gin`
cobre via `@>` containment operator.

## Regras gerais
1. Svelte 5 runes — $state, $derived, $effect
2. @netz/ui formatters para números (nunca .toFixed(), nunca .toLocaleString())
3. Tab state via URL param: /screener?tab=equity
4. Server load SSR: carrega tab inicial com dados do servidor via +page.server.ts
5. Client-side filtering adicional: debounce 300ms nos inputs numéricos
6. Paginação server-side: page_size=50, botão "Load more"
7. Checkbox de seleção mantido (para Add to Portfolio)
8. make check deve passar

## Deploy
```powershell
pnpm --filter netz-wealth-os build
npx wrangler pages deploy frontends/wealth/.svelte-kit/cloudflare --project-name netz-wealth
```
