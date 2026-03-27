# Screener Fund Catalog — Tree View com Share Classes

## Contexto

O backend agora retorna **uma row por share class** no catalog (resultado do
`feat-sec-fund-classes-table.md`). O `external_id` (CIK) se repete para classes
do mesmo fundo. Fundos `registered_us` com múltiplas classes aparecem como N rows
com o mesmo `external_id` e `name` do fundo, diferenciando-se em `class_id`,
`class_name` e `ticker`.

Fundos `private_us` e `ucits_eu` continuam retornando uma row por fundo
(sem classes), pois não têm `sec_fund_classes`.

## Objetivo

1. Atualizar tipos TypeScript para incluir os novos campos de classe
2. Reescrever `CatalogTable.svelte` para agrupar rows pelo fundo e expandir classes
3. Adicionar checkbox por classe para "Send to DD Review"

---

## Leitura obrigatória antes de qualquer edição

```
frontends/wealth/src/lib/types/catalog.ts          (tipos atuais)
frontends/wealth/src/lib/components/screener/CatalogTable.svelte  (tabela atual)
frontends/wealth/src/lib/components/screener/screener.css         (estilos existentes)
frontends/wealth/src/routes/(app)/screener/+page.svelte           (como o catalog é usado)
frontends/wealth/src/routes/(app)/screener/+page.server.ts        (dados carregados no server)
```

---

## Etapa 1 — Atualizar `catalog.ts`

Em `frontends/wealth/src/lib/types/catalog.ts`, adicionar campos ao `UnifiedFundItem`:

```typescript
export interface UnifiedFundItem {
  external_id: string;
  universe: FundUniverse;
  name: string;
  ticker: string | null;
  isin: string | null;

  region: FundRegion;
  fund_type: string;
  domicile: string | null;
  currency: string | null;

  manager_name: string | null;
  manager_id: string | null;

  aum: number | null;
  inception_date: string | null;
  total_shareholder_accounts: number | null;
  investor_count: number | null;

  // Share class fields (populated for registered_us funds with classes)
  series_id: string | null;
  series_name: string | null;
  class_id: string | null;
  class_name: string | null;   // "Class A", "Class I", "Institutional", etc.

  instrument_id: string | null;
  screening_status: "PASS" | "FAIL" | "WATCHLIST" | null;
  screening_score: number | null;
  approval_status: string | null;

  disclosure: DisclosureMatrix;
}
```

---

## Etapa 2 — Reescrever `CatalogTable.svelte`

### Lógica de agrupamento

O componente recebe `catalog.items` como array flat. Precisa agrupar pelo fundo
antes de renderizar:

```typescript
// Tipo auxiliar para o grupo
interface FundGroup {
  fund_key: string;           // external_id (CIK) ou isin para ucits
  representative: UnifiedFundItem;  // primeiro item do grupo (dados do fundo)
  classes: UnifiedFundItem[];       // todas as classes (≥1)
  has_classes: boolean;             // true se universe=registered_us E classes.length > 1
}

// Agrupamento (Svelte 5 $derived)
let fundGroups = $derived((): FundGroup[] => {
  const map = new Map<string, UnifiedFundItem[]>();
  for (const item of catalog.items) {
    const key = item.external_id;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(item);
  }
  return Array.from(map.entries()).map(([key, items]) => ({
    fund_key: key,
    representative: items[0],
    classes: items,
    has_classes: items[0].universe === "registered_us" && items.length > 1,
  }));
});
```

### Estado de expansão

```typescript
let expandedFunds = $state<Set<string>>(new Set());
let selectedClasses = $state<Set<string>>(new Set()); // chave: `${cik}:${class_id}`

function toggleExpand(fundKey: string) {
  if (expandedFunds.has(fundKey)) {
    expandedFunds.delete(fundKey);
  } else {
    expandedFunds.add(fundKey);
  }
  expandedFunds = new Set(expandedFunds); // trigger reactivity
}

function toggleClass(item: UnifiedFundItem) {
  const key = `${item.external_id}:${item.class_id}`;
  if (selectedClasses.has(key)) {
    selectedClasses.delete(key);
  } else {
    selectedClasses.add(key);
  }
  selectedClasses = new Set(selectedClasses);
}

function isClassSelected(item: UnifiedFundItem): boolean {
  return selectedClasses.has(`${item.external_id}:${item.class_id}`);
}
```

### Props

```typescript
interface Props {
  catalog: UnifiedCatalogPage;
  searchQ: string;
  onSelectFund: (item: UnifiedFundItem) => void;
  onSendToDDReview: (items: UnifiedFundItem[]) => void;  // NOVO
  onPageChange: (page: number) => void;
}
```

### Template da tabela

```svelte
<div class="scr-data-header">
  <!-- header existente ... -->
  {#if selectedClasses.size > 0}
    <button class="ct-send-dd-btn" onclick={handleSendSelected}>
      Send {selectedClasses.size} class{selectedClasses.size > 1 ? 'es' : ''} to DD Review
    </button>
  {/if}
</div>

<div class="scr-table-wrap">
  <table class="scr-table ct-tree-table">
    <thead>
      <tr>
        <th class="ct-col-expand"></th>       <!-- chevron / indent -->
        <th class="ct-col-check"></th>        <!-- checkbox (só em class rows) -->
        <th class="sth-univ">Universe</th>
        <th>Ticker</th>
        <th class="sth-name">Name / Class</th>
        <th>Manager</th>
        <th>Type</th>
        <th class="sth-aum">AUM</th>
        <th>Region</th>
        <th>Disclosure</th>
      </tr>
    </thead>
    <tbody>
      {#each fundGroups as group (group.fund_key)}
        <!-- ── Fund row (parent) ── -->
        <tr
          class="scr-inst-row ct-fund-row"
          class:ct-fund-row--expanded={expandedFunds.has(group.fund_key)}
          onclick={() => {
            if (group.has_classes) {
              toggleExpand(group.fund_key);
            } else {
              onSelectFund(group.representative);
            }
          }}
        >
          <td class="ct-col-expand">
            {#if group.has_classes}
              <span class="ct-chevron" class:ct-chevron--open={expandedFunds.has(group.fund_key)}>
                ▶
              </span>
            {/if}
          </td>
          <td class="ct-col-check"></td>  <!-- vazio no fund row -->
          <td>
            <span class="univ-badge {universeBadgeClass(group.representative.universe)}">
              {UNIVERSE_LABELS[group.representative.universe] ?? group.representative.universe}
            </span>
          </td>
          <td class="std-ticker">
            <span class="ticker-cell">{group.representative.ticker ?? "—"}</span>
          </td>
          <td class="std-name">
            <span class="inst-name">{group.representative.name}</span>
            {#if group.has_classes}
              <span class="ct-class-count">{group.classes.length} classes</span>
            {:else if group.representative.isin}
              <span class="inst-ids">{group.representative.isin}</span>
            {/if}
          </td>
          <td class="std-manager">{group.representative.manager_name ?? "—"}</td>
          <td><span class="ct-type-label">{fundTypeLabel(group.representative.fund_type)}</span></td>
          <td class="std-aum">{group.representative.aum ? formatAUM(group.representative.aum) : "—"}</td>
          <td>{group.representative.region}</td>
          <td><div class="ct-disclosure-dots"><!-- dots --></div></td>
        </tr>

        <!-- ── Class rows (children) — só se expandido ── -->
        {#if group.has_classes && expandedFunds.has(group.fund_key)}
          {#each group.classes as cls (`${cls.external_id}:${cls.class_id}`)}
            <tr
              class="scr-inst-row ct-class-row"
              class:ct-class-row--selected={isClassSelected(cls)}
            >
              <td class="ct-col-expand ct-class-indent"></td>
              <td class="ct-col-check">
                <input
                  type="checkbox"
                  class="ct-class-checkbox"
                  checked={isClassSelected(cls)}
                  onchange={() => toggleClass(cls)}
                  onclick={(e) => e.stopPropagation()}
                />
              </td>
              <td></td>  <!-- universe — vazio, já mostrado no pai -->
              <td class="std-ticker">
                <span class="ticker-cell">{cls.ticker ?? "—"}</span>
              </td>
              <td class="std-name">
                <span class="ct-class-name">{cls.class_name ?? cls.class_id ?? "—"}</span>
                {#if cls.isin}
                  <span class="inst-ids">{cls.isin}</span>
                {/if}
              </td>
              <td colspan="4">
                <button
                  class="ct-detail-link"
                  onclick={(e) => { e.stopPropagation(); onSelectFund(cls); }}
                >
                  View details →
                </button>
              </td>
              <td>
                <div class="ct-disclosure-dots">
                  <span class="ct-dot" class:ct-dot--on={cls.disclosure.has_holdings} title="Holdings"></span>
                  <span class="ct-dot" class:ct-dot--on={cls.disclosure.has_nav_history} title="NAV"></span>
                  <span class="ct-dot" class:ct-dot--on={cls.disclosure.has_quant_metrics} title="Quant"></span>
                  <span class="ct-dot" class:ct-dot--on={cls.disclosure.has_style_analysis} title="Style"></span>
                </div>
              </td>
            </tr>
          {/each}
        {/if}
      {/each}
    </tbody>
  </table>
</div>
```

### Handler "Send to DD Review"

```typescript
function handleSendSelected() {
  const items: UnifiedFundItem[] = [];
  for (const key of selectedClasses) {
    const [cik, classId] = key.split(':');
    const item = catalog.items.find(
      (i) => i.external_id === cik && i.class_id === classId
    );
    if (item) items.push(item);
  }
  onSendToDDReview(items);
  selectedClasses = new Set(); // limpar após envio
}
```

---

## Etapa 3 — Estilos novos em `screener.css`

Adicionar ao arquivo existente (não substituir os estilos atuais):

```css
/* ── Tree table ── */
.ct-tree-table .ct-col-expand { width: 28px; }
.ct-tree-table .ct-col-check  { width: 36px; text-align: center; }

/* Fund row parent */
.ct-fund-row { cursor: pointer; }
.ct-fund-row--expanded { background: #f8fafc; }

/* Chevron */
.ct-chevron {
  display: inline-block;
  font-size: 10px;
  color: #62748e;
  transition: transform 120ms ease;
  user-select: none;
}
.ct-chevron--open { transform: rotate(90deg); }

/* Class rows (children) */
.ct-class-row { background: #fbfdff; }
.ct-class-row:hover { background: #f0f7ff; }
.ct-class-row--selected { background: #eff6ff !important; }
.ct-class-indent { padding-left: 28px; }

.ct-class-name {
  font-size: 13px;
  font-weight: 500;
  color: #374151;
}

/* Class count badge next to fund name */
.ct-class-count {
  display: inline-block;
  margin-left: 8px;
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 8px;
  padding: 1px 7px;
}

/* Checkbox */
.ct-class-checkbox {
  cursor: pointer;
  width: 15px;
  height: 15px;
  accent-color: #1447e6;
}

/* Send to DD button (aparece quando há seleção) */
.ct-send-dd-btn {
  margin-left: auto;
  padding: 6px 14px;
  background: #1447e6;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.ct-send-dd-btn:hover { background: #0f3ccc; }

/* Detail link inside class row */
.ct-detail-link {
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  color: #1447e6;
  cursor: pointer;
  text-decoration: underline;
}
.ct-detail-link:hover { color: #0f3ccc; }
```

---

## Etapa 4 — Conectar `onSendToDDReview` na página

Em `+page.svelte` do screener, implementar o handler que recebe as classes selecionadas
e envia para o fluxo de DD Review. Verificar como o screener atualmente navega para
o DD Report (ler o arquivo antes de implementar) e seguir o mesmo padrão.

O handler deve:
1. Para cada `UnifiedFundItem` selecionado com `instrument_id` preenchido:
   → Navegar para `/dd-reports/{instrument_id}` (instrumento já importado)
2. Para cada item com `instrument_id` NULL:
   → Primeiro importar via `POST /screener/import-sec/{ticker}` (ou equivalente),
   → Depois navegar para o DD Report criado

Se houver múltiplas classes selecionadas, abrir em paralelo ou enfileirar.
Verificar o comportamento atual de `onSelectFund` na página para usar o mesmo padrão.

---

## Definition of Done

- [ ] `UnifiedFundItem` com `series_id`, `series_name`, `class_id`, `class_name`
- [ ] `CatalogTable.svelte` agrupa rows por `external_id` antes de renderizar
- [ ] Fundos `registered_us` com múltiplas classes mostram chevron + contador
- [ ] Expandir mostra uma row por classe com checkbox
- [ ] Clicar no fundo pai (sem classes) → `onSelectFund` (comportamento atual preservado)
- [ ] Clicar no fundo pai (com classes) → toggle expand (não chama `onSelectFund`)
- [ ] Checkbox seleciona a classe; "Send X classes to DD Review" aparece com seleção
- [ ] Fundos `private_us` e `ucits_eu` sem classes → comportamento idêntico ao atual (flat row)
- [ ] Paginação funciona normalmente (opera no array flat do backend, grouping é client-side)
- [ ] `make check` e `npm run build` zero erros TypeScript

## O que NÃO fazer

- Não fazer request adicional ao backend para buscar classes — os dados já chegam
  no `catalog.items` (uma row por classe já populada pelo backend)
- Não usar `$state` deep em `catalog.items` — manter como prop reativa normal
- Não quebrar o comportamento de `onSelectFund` para fundos sem classes
- Não remover os estilos existentes de `screener.css` — apenas acrescentar
- Não implementar expansão aninhada (series dentro de classes) — nível único é suficiente

## Failure modes esperados

- **Fundo com `class_id` NULL** (ETF single-class sem classes populadas):
  `group.has_classes = false` → renderiza como row flat normal. OK.
- **Backend retorna classes fora de ordem** (ex: Class I antes de Class A):
  O agrupamento por `external_id` preserva a ordem do backend — não reordenar
  client-side (o backend já ordena por class_name ou ticker).
- **`series_id` presente mas `class_id` NULL** (fundo com series sem classes):
  Tratar como fund sem classes → `has_classes = false`.
