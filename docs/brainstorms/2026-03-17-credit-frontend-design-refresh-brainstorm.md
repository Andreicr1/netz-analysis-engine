# Briefing: Credit Frontend Design Refresh — Migração do padrão Wealth OS

## Contexto

O PR `feat/wealth-senior-analyst-engines` entregou dois conjuntos de mudanças:

1. **Backend Sprint 6** — engines de análise sênior (attribution, strategy drift, correlation regime)
2. **Wealth Frontend Design Refresh** — redesign completo do `frontends/wealth/` com novo sistema
   de design institucional

Este briefing cobre a **migração do padrão do Wealth para o Credit frontend** (`frontends/credit/`).

---

## O que foi entregado no Wealth (referência)

### `@netz/ui` — novos componentes disponíveis para ambos os frontends

**Layouts:**
- `TopNav.svelte` — navegação horizontal global (texto, sem ícones, item ativo = border-bottom)
- `ContextSidebar.svelte` — sidebar contextual para páginas de detalhe ([id] routes)
- `AppLayout.svelte` refatorado — aceita `contextNav?: ContextNav` prop; sem contextNav = full width

**Componentes novos:**
- `MetricCard.svelte` — KPI financeiro com limite/utilização, borda esquerda semântica por status
- `UtilizationBar.svelte` — barra de utilização vs limite, overflow visual quando > 100%
- `RegimeBanner.svelte` — banner condicional de regime macro (não renderiza nada em RISK_ON)
- `AlertFeed.svelte` — feed de alertas com discriminated union tipado
- `SectionCard.svelte` — wrapper padrão com título + actions snippet
- `HeatmapTable.svelte` — tabela HTML com células coloridas por intensidade
- `PeriodSelector.svelte` — seletor compacto de período (1M/3M/YTD/1Y/3Y)

**Sistema de tokens:**
- `tokens.css` agora tem `:root` (light) + `[data-theme="dark"]` (dark override)
- Aliases adicionados: `--netz-primary`, `--netz-primary-foreground`, `--netz-primary-muted`
  → apontam para `--netz-brand-primary`
- dark/light via `data-theme="dark|light"` no `<html>`

### Decisões de design — obrigatório ler antes de planejar

`docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`

Contém 9 decisões que se aplicam a AMBOS os frontends:
- **D2**: dark + light para TODOS os frontends (credit incluso)
- **D4**: nenhum `var(--netz-*)` pode ser usado sem estar declarado em `tokens.css`
- **D5**: tokens são configuráveis pelo admin — sem cores hardcoded nos componentes

---

## Estado atual do Credit frontend

### Estrutura de rotas

```
frontends/credit/src/routes/
  (team)/
    dashboard/
    copilot/
    funds/
      [fundId]/     ← página de detalhe com hierarquia
  (investor)/
    documents/
    report-packs/
    statements/
  +layout.svelte    ← usa AppLayout com navItems hardcoded (emojis nos ícones!)
```

### Componentes específicos do Credit

```
lib/components/
  CopilotChat.svelte          ← 2 refs --netz-primary (bug P1)
  ICMemoViewer.svelte         ← 1 ref --netz-primary (bug P1)
  ICMemoStreamingChapter.svelte ← 1 ref --netz-primary (bug P1)
  DealStageTimeline.svelte
  PipelineFunnel.svelte
  IngestionProgress.svelte
  TaskInbox.svelte
  CopilotCitation.svelte
```

### Problemas já identificados no review do PR Wealth

Os seguintes arquivos do credit têm referências `--netz-primary` undefined (já fixadas no
`tokens.css` com aliases, mas as referências são code smell que deve ser normalizado):

- `+error.svelte` — 3 refs
- `CopilotChat.svelte` — 2 refs
- `ICMemoViewer.svelte` — 1 ref
- `ICMemoStreamingChapter.svelte` — 1 ref
- `copilot/+page.svelte` — 2 refs
- `funds/[fundId]/+layout.svelte` — 2 refs
- `documents/upload/+page.svelte` — 1 ref

---

## Decisões arquiteturais já tomadas para o Credit

### Navegação: diferente do Wealth

O Wealth migrou para **TopNav global** porque é um produto de monitoring — o usuário chega,
verifica status, sai.

O Credit tem **hierarquia de entidades profunda**: Deal → Documentos → IC Memo → Aprovação.
O usuário passa longos períodos dentro de um deal específico.

**Decisão:** Credit usa **Sidebar como navegação global** (não migra para TopNav) + **ContextSidebar**
dentro de páginas de detalhe `[fundId]`. O `AppLayout` já suporta ambos os padrões via a prop
`contextNav`.

Porém o layout atual do credit tem **emojis nos nav items** — isso deve ser removido. Nav items
devem ser texto puro, sem ícones (padrão institucional, mesma decisão do Wealth).

### Tema: light como default, dark disponível

O credit frontend usa **light como default** (`defaultBranding` existente, não alterado).
Mas dark deve funcionar via `data-theme="dark"` — o `tokens.css` já suporta.
O `hooks.server.ts` do credit precisa do mesmo padrão de FOUC prevention que o Wealth implementou.

---

## Escopo da migração

### O que fazer

1. **Remover emojis dos nav items** no `+layout.svelte` do credit

2. **Adicionar dark/light support** ao credit:
   - `app.html`: blocking script para FOUC prevention (ler `netz-theme` cookie antes do paint)
   - `hooks.server.ts`: `transformPageChunk` para injetar `data-theme` no SSR HTML
   - `defaultBranding` permanece light — credit não muda default

3. **Normalizar tokens** — substituir `var(--netz-primary)` por `var(--netz-brand-primary)`
   nos 7 arquivos identificados (os aliases já resolvem o bug visual, mas o código deve usar
   o token correto)

4. **Auditoria de hardcoded colors** nos componentes do credit — mesma checagem feita no Wealth:
   - `bg-white` → `bg-[var(--netz-surface)]`
   - `text-gray-*` → tokens
   - Hex hardcoded → tokens semânticos

5. **ContextSidebar em `funds/[fundId]/`** — implementar navegação contextual dentro de um deal:
   - Resumo
   - IC Memo
   - Documentos
   - Pipeline
   - Histórico
   O `[fundId]/+layout.svelte` passa `contextNav` para o `AppLayout`

6. **Migrar componentes credit para padrões Svelte 5** — auditoria similar à feita no Wealth:
   - `$effect` para derived state → `$derived`
   - `$state.raw()` para API responses grandes (IC Memo content, document lists)
   - `{#each}` sem key → adicionar key
   - Sem `EventSource` para SSE — usar `fetch() + ReadableStream` (já documentado no CLAUDE.md)

### O que NÃO fazer

- Não migrar para TopNav (credit mantém Sidebar global)
- Não redesenhar os componentes específicos do credit (CopilotChat, ICMemoViewer, etc.) —
  apenas normalizar tokens e padrões Svelte 5
- Não criar novas páginas — o credit tem escopo de rotas diferente do Wealth
- Não tocar no `defaultBranding` — light permanece o default do credit

---

## Referências obrigatórias

**Ler antes de planejar:**
- `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md` — decisões D1-D9
- `docs/plans/2026-03-16-feat-wealth-frontend-figma-design-refresh-plan.md` — o plano do Wealth
  como referência de padrões e decisões técnicas (Svelte 5, SSE, branding, tokens)
- `packages/ui/src/lib/styles/tokens.css` — tokens disponíveis (light + dark)
- `packages/ui/src/lib/layouts/AppLayout.svelte` — interface com `contextNav` prop
- `packages/ui/src/lib/layouts/ContextSidebar.svelte` — componente para [fundId] layout
- `frontends/credit/src/routes/+layout.svelte` — estado atual do credit layout
- `CLAUDE.md` — regras do projeto (SSE via fetch, async-first, etc.)

**UX principles (se existir):**
- `docs/ux/wealth-frontend-ux-principles.md` — princípios aplicáveis ao credit também

---

## Instrução para o agente

Use o skill `/ce-plan` para gerar o plano de implementação da migração do Credit frontend.

O plano deve:
- Ter fases independentes que possam rodar em paralelo (mesmo padrão do Wealth)
- Identificar quais fases são bloqueadas por outras
- Ser explícito sobre o que NÃO mudar (não migrar para TopNav, não alterar defaultBranding)
- Incluir acceptance criteria verificáveis por `make check`
- Documentar o contrato de `contextNav` para o `[fundId]` layout
- Incluir a query de diagnóstico de tokens: grep de `var(--netz-*)` vs declarações em tokens.css
