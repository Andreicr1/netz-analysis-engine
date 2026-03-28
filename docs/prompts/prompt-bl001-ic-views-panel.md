# Prompt: BL-001 — Painel IC Views no Model Portfolio

## Contexto

O backend de portfolio views (Black-Litterman) está completamente implementado
desde o quant upgrade. O frontend usa `/construct` que aplica views implicitamente,
mas o CRUD de views individuais nunca foi exposto na UI.

**Endpoints disponíveis (todos funcionais):**
- `GET    /api/v1/model-portfolios/{portfolio_id}/views`
- `POST   /api/v1/model-portfolios/{portfolio_id}/views`
- `DELETE /api/v1/model-portfolios/{portfolio_id}/views/{view_id}`

**Schema de uma view (`PortfolioViewRead`):**
```typescript
{
  id: string                    // UUID
  portfolio_id: string
  asset_instrument_id: string | null   // fundo alvo
  peer_instrument_id: string | null    // fundo peer (views relativas)
  view_type: "absolute" | "relative"
  expected_return: number              // retorno esperado (ex: 0.08 = 8%)
  confidence: number                   // 0.01–1.0 (Idzorek method)
  rationale: string | null             // justificativa IC
  created_by: string | null
  effective_from: string               // date ISO
  effective_to: string | null          // null = aberta
  created_at: string                   // datetime ISO
}
```

**Restrições de acesso:**
- `GET`: qualquer usuário autenticado da org
- `POST` / `DELETE`: apenas role `INVESTMENT_TEAM` (IC role)
  — backend retorna 403 se não tiver o role

**Comportamento do optimizer:**
- Sem views: usa prior BL (Π = equilíbrio de mercado)
- Com views: retorna μ_BL (posterior Black-Litterman)
- Views têm `effective_from` / `effective_to` — o backend filtra automaticamente

---

## Mandatory First Steps

1. Ler a página atual do model portfolio:
   `apps/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.svelte`

2. Ler o SSR loader:
   `apps/wealth/src/routes/(app)/model-portfolios/[portfolioId]/+page.server.ts`

3. Verificar como outros tabs/painéis estão implementados na mesma página
   (ex: track-record, stress test) para seguir o padrão existente

4. Verificar se existe componente de instrumento picker reutilizável em
   `apps/wealth/src/lib/components/` — para selecionar `asset_instrument_id`

5. Verificar padrão de formatação de percentual em `@netz/ui` formatters —
   `expected_return` deve ser exibido como % (nunca `.toFixed()`)


---

## Entregável

Adicionar um painel "IC Views" na página de model portfolio
(`[portfolioId]/+page.svelte`) com as seguintes funcionalidades:

---

## Seção 1 — Carregar Views no SSR Loader

**Arquivo:** `+page.server.ts`

Adicionar ao loader existente:
```typescript
const views = await api.get(`/model-portfolios/${portfolioId}/views`)
```

Passar `views` para a página via `return { ..., views }`.

---

## Seção 2 — Painel ICViewsPanel.svelte

Criar componente novo:
`apps/wealth/src/lib/components/model-portfolio/ICViewsPanel.svelte`

### Props
```typescript
export let portfolioId: string
export let views: PortfolioView[] = []
export let instruments: Instrument[] = []  // universo para picker de instrumento
export let canEdit: boolean = false         // true se usuário tem IC role
```

### Layout

O painel tem duas partes:

**Parte A — Lista de views ativas:**
Tabela com colunas:
| Instrumento | Peer (se relativa) | Tipo | Retorno Esperado | Confiança | Válida de | Válida até | Ações |
- "Instrumento": nome do fundo via `instruments` lookup por `asset_instrument_id`
- "Peer": nome do fundo peer (só em views relativas)
- "Tipo": badge "Absolute" ou "Relative"
- "Retorno Esperado": formatado como % via `@netz/ui` formatter (ex: "8.0%")
- "Confiança": barra de progresso visual 0–100% ou valor percentual
- "Válida de" / "Válida até": datas formatadas; "—" se `effective_to` for null (aberta)
- "Ações": botão delete (visível apenas se `canEdit`)
- Se `rationale` existe: ícone de info com tooltip mostrando o texto

Estado vazio: "Nenhuma view cadastrada. O optimizer está usando o prior de equilíbrio de mercado."

**Parte B — Formulário de nova view (visível apenas se `canEdit`):**

```
[Tipo: Absolute | Relative]  ← toggle/select

[Instrumento] ← picker buscando em `instruments`
[Peer]        ← picker (visível apenas se tipo = Relative)

[Retorno Esperado (%)]  ← input numérico, ex: 8.5 → armazenado como 0.085
[Confiança (%)]         ← slider ou input 1–100, ex: 70 → armazenado como 0.70

[Válido de]  ← date picker (default: hoje)
[Válido até] ← date picker (opcional)

[Justificativa] ← textarea opcional

[Adicionar View] ← button, disabled durante submit
```

### Lógica de submit

```typescript
async function addView() {
  const body = {
    view_type: form.type,                           // "absolute" | "relative"
    asset_instrument_id: form.instrumentId,
    peer_instrument_id: form.type === "relative" ? form.peerId : null,
    expected_return: form.expectedReturnPct / 100,  // % → decimal
    confidence: form.confidencePct / 100,           // % → decimal
    rationale: form.rationale || null,
    effective_from: form.effectiveFrom,             // ISO date string
    effective_to: form.effectiveTo || null,
  }

  const created = await api.post(`/model-portfolios/${portfolioId}/views`, body)
  views = [...views, created]
  resetForm()
}
```

### Lógica de delete

```typescript
async function deleteView(viewId: string) {
  await api.delete(`/model-portfolios/${portfolioId}/views/${viewId}`)
  views = views.filter(v => v.id !== viewId)
}
```

Confirmar antes de deletar com dialog simples:
"Remover esta view? O próximo /construct usará o prior de equilíbrio para este ativo."

### Tratamento de erro 403

Se POST ou DELETE retornar 403:
```typescript
// Exibir toast: "Permissão negada. Apenas membros do Investment Committee podem gerenciar views."
```

---

## Seção 3 — Integrar na Página Principal

**Arquivo:** `[portfolioId]/+page.svelte`

Adicionar o painel após a seção de construct/stress, antes ou depois do track-record
(seguir o padrão de ordenação visual da página existente).

```svelte
<ICViewsPanel
  {portfolioId}
  views={data.views}
  instruments={data.instruments}
  canEdit={$userStore.hasRole('INVESTMENT_TEAM')}
/>
```

**Verificar como `canEdit` / role check é feito em outros componentes da página**
e seguir o mesmo padrão — não inventar novo mecanismo de role check.

---

## Seção 4 — Tipos TypeScript

Criar ou adicionar em `apps/wealth/src/lib/types/`:
```typescript
export interface PortfolioView {
  id: string
  portfolio_id: string
  asset_instrument_id: string | null
  peer_instrument_id: string | null
  view_type: 'absolute' | 'relative'
  expected_return: number
  confidence: number
  rationale: string | null
  created_by: string | null
  effective_from: string
  effective_to: string | null
  created_at: string
}
```

---

## Validação

```bash
# Typecheck
cd apps/wealth && pnpm check

# Build
cd apps/wealth && pnpm build

# Verificar manualmente:
# 1. Abrir página de model portfolio com fund no universo
# 2. Sem IC role: painel mostra lista mas sem formulário e sem botão delete
# 3. Com IC role: formulário visível, adicionar view absolute, confirmar aparece na lista
# 4. Adicionar view relative (com peer), confirmar peer exibido na tabela
# 5. Deletar view, confirmar removida da lista
# 6. Rodar /construct após adicionar view, verificar que μ_BL é aplicado
```

---

## What NOT to Do

- Não usar `.toFixed()` para formatar percentuais — usar `@netz/ui` formatters
- Não expor "Black-Litterman" como label de UI — usar "IC View" ou "Expected Return View"
- Não hardcodar role string — verificar como outros componentes checam IC role
- Não modificar `portfolio_views.py` no backend — está completo
- Não criar nova rota — o painel é um componente dentro da página existente
- Não usar `EventSource` para qualquer stream — padrão é `fetch()` + `ReadableStream`
- Não bloquear submit se `rationale` for vazio — campo opcional
- Não permitir `confidence = 0` — mínimo é 0.01 (1%) conforme schema do backend
