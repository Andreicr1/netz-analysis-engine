# Prompt: US Fund Analysis — Redesign Layout para Figma

## Contexto

A página `/us-fund-analysis` está funcional mas o layout diverge do design Figma.
O redesign principal é:
1. Eliminar o sidebar de filtros — filtros passam para **inline dentro do card principal**
2. Ajustar colunas da tabela para corresponder ao Figma
3. Melhorar estética geral (espaçamento, tipografia, badges)

A lógica de dados (5 tabs, ContextPanel, peer compare, holdings, style drift, reverse
lookup) permanece intocada — apenas layout e visual mudam.

## Arquivos a modificar

- `frontends/wealth/src/routes/(app)/us-fund-analysis/+page.svelte` — layout rewrite
- `frontends/wealth/src/routes/(app)/us-fund-analysis/components/FilterSidebar.svelte` — **deletar** (substituído por filtros inline)
- `frontends/wealth/src/routes/(app)/us-fund-analysis/components/ManagerTable.svelte` — colunas + visual

## Arquivos NÃO tocados

- `+page.server.ts` — já carrega dados corretamente
- `HoldingsTable.svelte` — sem mudanças
- `StyleDriftChart.svelte` — sem mudanças
- `ReverseLookup.svelte` — sem mudanças
- `PeerCompare.svelte` — sem mudanças
- `$lib/types/sec-analysis.ts` — verificar se tem `last_adv_filed_at`, adicionar se faltar

---

## Mudança 1 — +page.svelte: layout stacked, sem sidebar

### Header: subtitle + Export Data button

```svelte
<PageHeader title="US Fund Analysis" subtitle="Screen and analyze US-based fund managers, their holdings, and historical drift.">
    {#snippet actions()}
        <Button size="sm" variant="outline">Export Data</Button>
    {/snippet}
</PageHeader>
```

### Eliminar grid sidebar

Remover:
- Import de `FilterSidebar`
- `<aside class="ufa-sidebar">` e o componente `<FilterSidebar>`
- CSS `.ufa-layout` grid `240px 1fr`, `.ufa-sidebar`

Novo layout — card único full-width que contém tabs + filtros + tabela:

```svelte
<div class="ufa-page">
    <div class="ufa-card">
        <PageTabs {tabs} active={activeTab} onChange={(t) => (activeTab = t)}>
            {#snippet children(current)}
                <!-- Filter Parameters (visível apenas na tab overview) -->
                {#if current === "overview"}
                    <div class="ufa-filters-section">
                        <div class="ufa-filters-header">
                            <span class="ufa-filters-label">Filter Parameters</span>
                        </div>
                        <form class="ufa-filters-row" onsubmit|preventDefault={applyFilters}>
                            <div class="ufa-filter-field">
                                <label class="ufa-field-label" for="ufa-q">Search</label>
                                <div class="ufa-search-wrap">
                                    <input
                                        id="ufa-q"
                                        class="ufa-input ufa-input--search"
                                        type="text"
                                        placeholder="Name, CIK, or CRD..."
                                        bind:value={filters.q}
                                    />
                                </div>
                            </div>
                            <div class="ufa-filter-field">
                                <label class="ufa-field-label" for="ufa-entity">Entity Type</label>
                                <select id="ufa-entity" class="ufa-select" bind:value={filters.entity_type}>
                                    <option value="">All</option>
                                    <option value="Registered">Registered</option>
                                    <option value="Exempt Reporting Adviser">Exempt Reporting</option>
                                    <option value="Not Registered">Not Registered</option>
                                </select>
                            </div>
                            <div class="ufa-filter-field">
                                <label class="ufa-field-label" for="ufa-strategy">Strategy</label>
                                <select id="ufa-strategy" class="ufa-select" bind:value={filters.strategy}>
                                    <option value="">All</option>
                                    <option value="equity">Equity</option>
                                    <option value="fixed_income">Fixed Income</option>
                                    <option value="multi_asset">Multi-Asset</option>
                                    <option value="alternatives">Alternatives</option>
                                    <option value="real_estate">Real Estate</option>
                                </select>
                            </div>
                            <div class="ufa-filter-field">
                                <label class="ufa-field-label" for="ufa-asset-class">Asset Class</label>
                                <select id="ufa-asset-class" class="ufa-select" bind:value={filters.asset_class}>
                                    <option value="">All</option>
                                    <option value="equity">Equity</option>
                                    <option value="fixed_income">Fixed Income</option>
                                    <option value="balanced">Balanced</option>
                                    <option value="money_market">Money Market</option>
                                    <option value="alternatives">Alternatives</option>
                                </select>
                            </div>
                            <div class="ufa-filter-field">
                                <label class="ufa-field-label" for="ufa-aum">Min AUM ($)</label>
                                <input
                                    id="ufa-aum"
                                    class="ufa-input"
                                    type="number"
                                    placeholder="e.g. 1000000000"
                                    bind:value={filters.aum_min}
                                />
                            </div>
                        </form>
                        <div class="ufa-filters-actions">
                            <button class="ufa-btn-clear" onclick={clearFilters}>Clear</button>
                            <button class="ufa-btn-apply" onclick={applyFilters}>Apply Filters</button>
                        </div>
                    </div>
                {/if}

                <!-- Tab content (existing logic, unchanged) -->
                {#if current === "overview"}
                    <ManagerTable ... />
                {:else if current === "holdings"}
                    <HoldingsTable ... />
                {:else if current === "style-drift"}
                    <StyleDriftChart ... />
                {:else if current === "reverse"}
                    <ReverseLookup ... />
                {:else if current === "compare"}
                    <PeerCompare ... />
                {/if}
            {/snippet}
        </PageTabs>
    </div>
</div>
```

### Filter state — remover `state` e `has_cik`, adicionar `strategy` e `asset_class`

```typescript
let filters = $state({
    q: "",
    entity_type: "",
    strategy: "",
    asset_class: "",
    aum_min: "",
});
```

Atualizar `applyFilters()`, `clearFilters()`, e o `$effect` que sincroniza `initParams`
para usar os novos campos em vez dos antigos.

### CSS novo (substitui .ufa-layout, .ufa-sidebar)

```css
.ufa-page {
    padding: 0 var(--netz-space-inline-lg, 24px) var(--netz-space-stack-xl, 48px);
}

.ufa-card {
    background: var(--netz-surface-elevated);
    border: 1px solid var(--netz-border-subtle);
    border-radius: 16px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}

/* Filters */
.ufa-filters-section {
    padding: 24px;
    border-bottom: 1px solid var(--netz-border-subtle);
    background: var(--netz-surface-elevated);
}

.ufa-filters-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
}

.ufa-filters-label {
    font-size: var(--netz-text-label, 0.75rem);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--netz-text-muted);
}

.ufa-filters-row {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 16px;
}

.ufa-filter-field {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.ufa-field-label {
    font-size: 12px;
    font-weight: 700;
    color: var(--netz-text-secondary);
}

.ufa-input,
.ufa-select {
    padding: 8px 12px;
    font-size: 14px;
    border: 1px solid var(--netz-border-subtle);
    border-radius: 10px;
    background: var(--netz-surface-alt);
    color: var(--netz-text-primary);
    font-family: var(--netz-font-sans);
}

.ufa-input::placeholder {
    color: var(--netz-text-muted);
}

.ufa-input:focus,
.ufa-select:focus {
    outline: none;
    border-color: var(--netz-brand-primary);
}

.ufa-input--search {
    padding-left: 36px;
}

.ufa-search-wrap {
    position: relative;
}

.ufa-search-wrap::before {
    content: "\2315";
    position: absolute;
    left: 12px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 14px;
    color: var(--netz-text-muted);
    pointer-events: none;
}

.ufa-filters-actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--netz-border-subtle);
}

.ufa-btn-clear {
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 700;
    color: var(--netz-text-secondary);
    background: none;
    border: none;
    border-radius: 10px;
    cursor: pointer;
}

.ufa-btn-clear:hover {
    color: var(--netz-text-primary);
}

.ufa-btn-apply {
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 700;
    color: white;
    background: var(--netz-brand-primary);
    border: none;
    border-radius: 10px;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.ufa-btn-apply:hover {
    filter: brightness(1.1);
}

@media (max-width: 1024px) {
    .ufa-filters-row {
        grid-template-columns: repeat(3, 1fr);
    }
}

@media (max-width: 600px) {
    .ufa-filters-row {
        grid-template-columns: 1fr;
    }
}
```

---

## Mudança 2 — Deletar FilterSidebar.svelte

Deletar `frontends/wealth/src/routes/(app)/us-fund-analysis/components/FilterSidebar.svelte`.
Os filtros agora são inline no `+page.svelte`. Remover o import correspondente.

---

## Mudança 3 — ManagerTable.svelte: colunas Figma

### Colunas a remover
- **CIK** — não está no Figma, acessível via detail panel
- **SIC** — não está no Figma

### Colunas a manter/ajustar
- **Manager Name** (antes "Firm Name") — com icon placeholder (quadrado cinza 32px com
  icon SVG de building) à esquerda. Nome bold, clicável para detail.
- **Entity Type** (antes "Status") — texto muted, sem badge/chip. Ex: "Registered Investment Adviser"
- **AUM ($)** — valor absoluto formatado com `formatNumber(aum, 0)` prefixado com `$`.
  Font-weight 900, alinhado direita. **Usar `@netz/ui` formatters** — nunca `.toLocaleString()`.

### Coluna a adicionar
- **Last Filing** — `last_adv_filed_at` do manager. Data ISO (`2026-02-14`), alinhada
  direita, cor muted. Se null, mostrar "—".

### Checkbox de compare
Remover da tabela Overview. A seleção para peer compare pode ser feita diretamente na
tab Peer Compare. O Figma não mostra checkboxes.

### Estrutura da nova `<thead>`

```svelte
<tr>
    <th class="mt-th">Manager Name</th>
    <th class="mt-th">Entity Type</th>
    <th class="mt-th mt-th--right">AUM ($)</th>
    <th class="mt-th mt-th--right">Last Filing</th>
</tr>
```

### Estrutura da nova `<tr>`

```svelte
<tr class="mt-row" onclick={() => mgr.cik && onSelect(mgr.cik, mgr.firm_name)}>
    <td class="mt-td mt-td--name">
        <div class="mt-name-cell">
            <div class="mt-avatar">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path d="M2 14V3h5v3h5v8H2zm1-1h3V4H3v9zm4 0h3V7H7v6z"
                          fill="currentColor" opacity="0.5"/>
                </svg>
            </div>
            <button
                class="mt-name-btn"
                onclick|stopPropagation={() => mgr.cik && onDetail(mgr.cik)}
            >
                {mgr.firm_name}
            </button>
        </div>
    </td>
    <td class="mt-td mt-td--entity">
        {mgr.registration_status ?? "—"}
    </td>
    <td class="mt-td mt-td--aum">
        {mgr.aum_total != null ? `$${formatNumber(mgr.aum_total, 0)}` : "—"}
    </td>
    <td class="mt-td mt-td--date">
        {mgr.last_adv_filed_at ?? "—"}
    </td>
</tr>
```

### CSS atualizado para ManagerTable

```css
.mt-table {
    width: 100%;
    border-collapse: collapse;
}

.mt-th {
    padding: 12px 24px;
    font-size: var(--netz-text-label, 0.75rem);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--netz-text-muted);
    text-align: left;
    background: color-mix(in srgb, var(--netz-surface-alt) 50%, transparent);
    border-bottom: 1px solid var(--netz-border-subtle);
}

.mt-th--right { text-align: right; }

.mt-row {
    cursor: pointer;
    border-bottom: 1px solid var(--netz-border-subtle);
    transition: background 100ms ease;
}

.mt-row:hover {
    background: color-mix(in srgb, var(--netz-surface-alt) 30%, transparent);
}

.mt-row:last-child { border-bottom: none; }

.mt-td {
    padding: 16px 24px;
    font-size: 14px;
    vertical-align: middle;
}

.mt-td--name { min-width: 280px; }

.mt-name-cell {
    display: flex;
    align-items: center;
    gap: 12px;
}

.mt-avatar {
    width: 32px;
    height: 32px;
    border-radius: 10px;
    background: var(--netz-surface-alt);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--netz-text-muted);
    flex-shrink: 0;
}

.mt-name-btn {
    background: none;
    border: none;
    padding: 0;
    font-size: 14px;
    font-weight: 700;
    color: var(--netz-text-primary);
    cursor: pointer;
    text-align: left;
}

.mt-name-btn:hover { text-decoration: underline; }

.mt-td--entity {
    color: var(--netz-text-secondary);
}

.mt-td--aum {
    text-align: right;
    font-weight: 900;
    font-variant-numeric: tabular-nums;
    color: var(--netz-text-primary);
}

.mt-td--date {
    text-align: right;
    color: var(--netz-text-muted);
}

.mt-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    font-size: var(--netz-text-small, 0.8125rem);
    color: var(--netz-text-muted);
}

.mt-empty {
    padding: 48px 24px;
    text-align: center;
    color: var(--netz-text-muted);
    font-size: 14px;
}
```

---

## Mudança 4 — Backend: novos filtros strategy e asset_class

Se o endpoint `GET /sec/managers/search` não suporta filtros `strategy` e `asset_class`,
adicionar como query params opcionais. A filtragem usa o índice GIN
`idx_sec_managers_client_types_gin` (migration 0047, já aplicada) para queries
`client_types @> '{"sic": "..."}'`.

Se não houver dados suficientes para mapear strategy/asset_class via SIC codes no momento,
manter os dropdowns no frontend mas documentar com TODO no backend. Os filtros são
ignorados silenciosamente quando o valor é vazio string.

---

## Mudança 5 — +page.server.ts: atualizar params

Atualizar o server load para passar os novos filtros (`strategy`, `asset_class`) e
remover os antigos (`state`, `has_cik`) dos search params forwarded ao backend.

---

## Mudança 6 — Verificar SecManagerRow type

Verificar se `SecManagerRow` em `$lib/types/sec-analysis.ts` tem campo `last_adv_filed_at`.
Se não, adicionar:
```typescript
last_adv_filed_at: string | null;
```
E verificar se o backend retorna esse campo no search response. O índice
`idx_sec_managers_last_adv_filed` (migration 0047) já suporta sort por esta coluna.

---

## Índices disponíveis (migration 0047 — já aplicada)

Todos os índices necessários para performance já estão criados no banco:

| Índice | Tipo | Finalidade |
|--------|------|------------|
| `idx_sec_managers_registered_aum` | btree partial (Registered) | Advisers sorted by AUM |
| `idx_sec_managers_investment` | btree partial (investment) | Investment companies sorted by AUM |
| `idx_sec_managers_name_trgm` | GIN trigram | Search box fuzzy matching |
| `idx_sec_managers_reg_status` | btree | Entity type filter |
| `idx_sec_managers_client_types_gin` | GIN jsonb_path_ops | Strategy filter via SIC codes |
| `idx_sec_managers_last_adv_filed` | btree partial | Last Filing column sort |
| `idx_sec_managers_status_aum` | btree composite | Status + AUM filtered sort |

**NÃO criar novos índices.** Usar os existentes nas queries.

---

## Regras gerais

1. Svelte 5 runes — `$state`, `$derived`, `$effect`
2. `@netz/ui` formatters para números (nunca `.toFixed()`, nunca `.toLocaleString()`)
3. Tabs permanecem funcionais — Holdings, Style Drift, Reverse Lookup, Peer Compare não mudam
4. ContextPanel para detail permanece intocado
5. Paginação permanece intocada (apenas visual da tabela muda)
6. `make check` deve passar

---

## Checklist

- [ ] `FilterSidebar.svelte` deletado
- [ ] Layout sidebar (`grid 240px 1fr`) removido, substituído por `.ufa-card` full-width
- [ ] PageHeader com subtitle + "Export Data" button
- [ ] Filtros inline: Search, Entity Type, Strategy, Asset Class, Min AUM — 5 campos em grid horizontal
- [ ] Filtros `state` e `has_cik` removidos do state e de `applyFilters()`/`clearFilters()`
- [ ] Filtros `strategy` e `asset_class` adicionados ao state
- [ ] "FILTER PARAMETERS" header acima dos filtros
- [ ] Clear + "Apply Filters" buttons alinhados à direita com border-top separator
- [ ] Filtros só visíveis na tab Overview (outras tabs mostram conteúdo direto)
- [ ] ManagerTable: colunas CIK e SIC removidas
- [ ] ManagerTable: coluna "Manager Name" com avatar icon 32px + nome bold
- [ ] ManagerTable: coluna "Entity Type" com texto muted (não badge)
- [ ] ManagerTable: coluna "AUM ($)" com valor absoluto formatado, font-weight 900, right-aligned
- [ ] ManagerTable: coluna "Last Filing" adicionada, data ISO, right-aligned, muted
- [ ] Checkbox de compare removido da tabela Overview
- [ ] Row height ~64px com padding vertical adequado
- [ ] `SecManagerRow` type verificado para `last_adv_filed_at`
- [ ] Todo o flow de 5 tabs, ContextPanel, peer compare logic preservado
- [ ] `make check` green
