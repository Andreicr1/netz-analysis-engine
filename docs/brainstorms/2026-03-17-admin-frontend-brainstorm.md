# Briefing: Admin Frontend — Build from Scratch

## Contexto

O admin frontend (`frontends/admin/`) é o terceiro e último frontend do monorepo.
Ao contrário do Wealth e Credit que foram redesenhados, o admin não tem `src/` — é uma
construção do zero. O `.svelte-kit/types` revela a estrutura de rotas planejada.

Este briefing cobre o que o agente precisa saber antes de rodar `/ce-plan`.

---

## Estado atual

```
frontends/admin/
  .svelte-kit/          ← gerado automaticamente (não é código real)
  node_modules/         ← dependências instaladas
  [sem src/]            ← nada implementado
```

Rotas planejadas (inferidas do `.svelte-kit/types`):
```
(admin)/
  config/[vertical]     ← editor de configuração por vertical
  health/               ← health dashboard do sistema
  prompts/[vertical]    ← editor de prompts por vertical
  tenants/[orgId]       ← gestão de tenants
auth/sign-in/
```

---

## O que já existe e pode ser usado

### `@netz/ui` — design system completo

O Wealth e Credit já foram implementados. O `@netz/ui` tem todos estes componentes
disponíveis para o admin reutilizar diretamente:

**Layouts:**
- `AppLayout.svelte` — TopNav + ContextSidebar opcional (ideal para o admin)
- `TopNav.svelte` — navegação horizontal institucional
- `ContextSidebar.svelte` — sidebar contextual para páginas de detalhe

**Componentes:**
- `DataTable.svelte` — tabela com sort/filter (para lista de tenants, logs)
- `SectionCard.svelte` — wrapper padrão com título + actions
- `MetricCard.svelte` — KPI com status semântico
- `Dialog.svelte` — modais de confirmação
- `Toast.svelte` — notificações non-fatal (409 conflicts, 422 errors)
- `Input.svelte`, `Select.svelte`, `Textarea.svelte` — form controls
- `StatusBadge.svelte` — badges coloridos de status
- `EmptyState.svelte` — estado vazio contextual
- `ErrorBoundary.svelte` — boundary de erros
- `Skeleton.svelte` — loading states
- `Badge.svelte`, `Button.svelte`, `Tabs.svelte`, `PageTabs.svelte`

**Sistema de tokens:**
- dark/light via `data-theme="dark|light"` no `<html>`
- Admin deve usar **light como default** (painel administrativo, não produto)
- `--netz-primary` alias disponível → `--netz-brand-primary`

---

## Diferenças fundamentais vs Wealth/Credit

| Dimensão | Wealth / Credit | Admin |
|---|---|---|
| Usuário | Investment team / Investor | Super-admin Netz |
| Auth | Clerk JWT com org context | Clerk JWT com role ADMIN |
| Tema default | Dark (Wealth) / Light (Credit) | Light (admin panel) |
| Nav | TopNav global | TopNav global |
| Hierarquia | Portfolio → Funds → DD | Tenant → Config → Prompts |
| Dados | Financeiros em tempo real | Configuração e metadados |
| Escopo | Por tenant (RLS) | Cross-tenant (sem RLS) |

---

## Funcionalidades do admin (Phase F do plano existente)

### 1. Dashboard de saúde (`/health`)
- Status dos serviços (backend, Redis, PostgreSQL, ADLS, Azure Search)
- Métricas de pipeline (jobs em fila, last run, erros)
- Logs de worker em tempo real (SSE)

### 2. Gestão de tenants (`/tenants`)
- Lista de tenants com status, AUM, plano
- Criar novo tenant (modal com Clerk org sync)
- Detalhe: `tenants/[orgId]` com tabs — Overview, Branding, Config, Prompts, Usuários

### 3. Editor de branding (`/tenants/[orgId]/branding`)
- Upload de logo (PNG/JPEG/ICO apenas — sem SVG, XSS risk)
- Color picker para tokens de brand
- Preview live das mudanças
- Salvar → invalidar cache de branding do tenant

### 4. Editor de configuração (`/config/[vertical]` ou `/tenants/[orgId]/config`)
- Config por vertical (credit / wealth)
- Editor JSON com Monaco/CodeMirror (já no plano)
- Validação contra JSON Schema (`guardrails` column)
- Preview do resultado antes de salvar
- Histórico de versões

### 5. Editor de prompts (`/prompts/[vertical]` ou `/tenants/[orgId]/prompts`)
- Lista de prompts por vertical com status (default / overridden)
- Editor de template Jinja2 com syntax highlight
- Preview de render com dados mock
- Versionamento (rollback)
- Sandbox seguro (sem execução real de prompts no frontend)

---

## Decisões de design obrigatórias

**Ler antes de planejar:**
`docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`

Decisões que se aplicam ao admin:
- **D2**: dark/light para TODOS os frontends — admin suporta ambos, default light
- **D4**: nenhum `var(--netz-*)` sem estar declarado em `tokens.css`
- **D5**: tokens configuráveis pelo admin via branding API (o admin é quem configura
  para os outros — ele mesmo usa os defaults)

---

## Referências obrigatórias

**Ler antes de planejar:**

1. `docs/plans/2026-03-16-feat-frontend-admin-platform-plan.md`
   — **Phase F** é o admin frontend (buscar a seção "Phase F: Admin Frontend")
   — **Phase E** são os admin backend APIs necessários (verificar o que já foi implementado)
   — **Enhancement Summary** tem decisões críticas de segurança (SVG rejection, SSTI sandbox)

2. `docs/solutions/design-decisions/2026-03-17-wealth-frontend-review-decisions.md`
   — D1-D9 aplicáveis

3. `docs/plans/2026-03-16-feat-wealth-frontend-figma-design-refresh-plan.md`
   — Referência de padrões técnicos (Svelte 5 runes, SSE, branding, AppLayout)

4. `packages/ui/src/lib/index.ts`
   — Inventário completo de componentes disponíveis no `@netz/ui`

5. `packages/ui/src/lib/styles/tokens.css`
   — Tokens declarados (light + dark)

6. `packages/ui/src/lib/layouts/AppLayout.svelte`
   — Interface com `contextNav` prop para hierarquia tenant → config

7. `CLAUDE.md`
   — Regras do projeto (async-first, SSE via fetch, Clerk auth patterns)

---

## O que NÃO fazer

- Não implementar Monaco/CodeMirror se aumentar demais o escopo — um `<textarea>` com
  syntax highlight básico serve para MVP do editor de prompts/config
- Não criar sistema de permissões granular por tenant — admin tem acesso cross-tenant
  por definição; o controle de acesso é pelo role ADMIN no Clerk
- Não implementar real-time collaboration no editor — last-write-wins com 409 toast
  (já decidido no plano existente)
- Não redesenhar componentes do `@netz/ui` — usar o que existe; só criar componentes
  admin-specific que não fazem sentido no design system compartilhado

---

## Componentes admin-specific (não existem no @netz/ui)

Estes precisam ser criados em `frontends/admin/src/lib/components/`:

- `BrandingEditor.svelte` — color pickers + logo upload + preview live
- `ConfigEditor.svelte` — JSON editor com validação de schema
- `PromptEditor.svelte` — editor Jinja2 com preview de render
- `TenantCard.svelte` — card compacto para lista de tenants
- `ServiceHealthCard.svelte` — status de serviço (ok/degraded/down) com latência
- `WorkerLogFeed.svelte` — feed SSE de logs de worker em tempo real

---

## Instrução para o agente

Use o skill `/ce-plan` para gerar o plano em:
`docs/plans/2026-03-17-feat-admin-frontend-plan.md`

O plano deve:
- Mapear as rotas do admin às funcionalidades (health, tenants, config, prompts)
- Identificar quais backend endpoints (Phase E) já existem vs precisam ser criados
- Ter fases independentes executáveis em paralelo
- Usar `@netz/ui` para tudo que já existe — só criar componentes admin-specific
- Especificar o padrão de auth (role ADMIN no Clerk, sem org context)
- Incluir a hierarquia de navegação: TopNav global + ContextSidebar dentro de [orgId]
- Documentar o contrato de segurança do branding editor (sem SVG, validação de hex)
- Incluir acceptance criteria verificáveis por `make check` (lint + typecheck + test)
