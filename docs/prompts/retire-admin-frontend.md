# Retire Admin Frontend — Migrar para Settings no Wealth/Credit

## Objetivo

Eliminar `frontends/admin/` como serviço autônomo.
Migrar o que tem valor para páginas `/settings` no Wealth e Credit.
Deletar o que não tem valor (prompts customizados, branding, tenant CRUD, inspect).

Resultado: 1 serviço a menos para manter, deploy simplificado,
configurações onde semanticamente pertencem — dentro do produto.

---

## Leitura obrigatória antes de qualquer edição

```
frontends/admin/src/lib/components/ConfigEditor.svelte
frontends/admin/src/lib/components/ConfigDiffView.svelte
frontends/admin/src/lib/components/ServiceHealthCard.svelte
frontends/admin/src/lib/components/WorkerLogFeed.svelte
frontends/admin/src/routes/(admin)/health/+page.svelte
frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.svelte
frontends/admin/src/routes/(admin)/config/[vertical=vertical]/+page.server.ts
frontends/admin/src/lib/api/client.ts
frontends/wealth/src/routes/(app)/screener/+page.svelte    (padrão de rota existente)
frontends/wealth/src/routes/(app)/+layout.svelte           (nav existente)
packages/ui/src/lib/index.ts                               (exports do @netz/ui)
```

---

## Fase 1 — Mover componentes reutilizáveis para @netz/ui

Os 4 componentes abaixo têm valor e serão reusados.
Mover para `packages/ui/src/lib/components/admin/`:

```
ConfigEditor.svelte       → packages/ui/src/lib/components/admin/ConfigEditor.svelte
ConfigDiffView.svelte     → packages/ui/src/lib/components/admin/ConfigDiffView.svelte
ServiceHealthCard.svelte  → packages/ui/src/lib/components/admin/ServiceHealthCard.svelte
WorkerLogFeed.svelte      → packages/ui/src/lib/components/admin/WorkerLogFeed.svelte
```

Antes de mover cada um:
1. Ler o arquivo para mapear imports locais (ex: `$lib/api/client`)
2. Substituir imports locais por equivalentes do pacote ou props injetadas
3. Nenhum componente pode importar de `$lib/` do admin após a migração

Exportar no `packages/ui/src/lib/index.ts`:
```typescript
export { default as ConfigEditor } from './components/admin/ConfigEditor.svelte';
export { default as ConfigDiffView } from './components/admin/ConfigDiffView.svelte';
export { default as ServiceHealthCard } from './components/admin/ServiceHealthCard.svelte';
export { default as WorkerLogFeed } from './components/admin/WorkerLogFeed.svelte';
```

---

## Fase 2 — Criar `/settings` no Wealth

### 2.1 Estrutura de rotas

Criar as seguintes rotas em `frontends/wealth/src/routes/(app)/`:

```
settings/
  +page.svelte           (redirect para /settings/config)
  +layout.svelte         (nav interna: Config | System)
  config/
    +page.server.ts      (carrega configs liquid_funds)
    +page.svelte         (ConfigEditor para liquid_funds)
  system/
    +page.server.ts      (carrega health: services, workers, pipelines)
    +page.svelte         (ServiceHealthCard + WorkerLogFeed)
```

### 2.2 `/settings/config` — Configurações do Wealth

Adaptar da rota `/config/liquid_funds` do Admin.
Diferenças:
- Vertical é sempre `liquid_funds` (hardcoded) — sem seletor de vertical
- Usar `@netz/ui/ConfigEditor` e `@netz/ui/ConfigDiffView`
- Auth via JWT Clerk existente no Wealth (não criar novo cliente)
- Usar o `token` do `+layout.server.ts` existente

```svelte
<!-- settings/config/+page.svelte -->
<script lang="ts">
  import { ConfigEditor } from "@netz/ui";
  import type { PageData } from "./$types";
  // ... (adaptar de admin/config/+page.svelte, removendo seletor de vertical)
</script>
```

O `+page.server.ts` deve:
1. Chamar `GET /api/v1/admin/config/liquid_funds` para listar config types
2. Verificar role `ADMIN` ou `INVESTMENT_TEAM` antes de carregar

### 2.3 `/settings/system` — Saúde do Sistema

Adaptar de `admin/health/+page.svelte` — é o componente mais rico.

Manter integralmente:
- Grid de ServiceHealthCard com auto-refresh a 30s via `$effect`
- Pipeline stats (docs_processed, queue_depth, error_rate)
- Worker table com status filter, expand row, "Run Now" com ConfirmDialog
- WorkerLogFeed
- Toast de feedback

Remover apenas:
- Workers fora do escopo Wealth (private_credit workers)
- Qualquer referência a `frontends/admin/src/lib/api/client` → usar API client do Wealth

Lista de WORKER_TRIGGERS a manter no Wealth:
```typescript
const WORKER_TRIGGERS = [
  { name: "instrument_ingestion", ... },
  { name: "macro_ingestion", ... },
  { name: "benchmark_ingest", ... },
  { name: "risk_calc", ... },
  { name: "portfolio_eval", ... },
  { name: "screening_batch", ... },
  { name: "watchlist_check", ... },
  { name: "portfolio_nav_synthesizer", ... },
  { name: "wealth_embedding", ... },   // novo worker BL implementado
];
```


---

## Fase 3 — Criar `/settings` no Credit

Estrutura análoga ao Wealth, mas para `private_credit`:

```
frontends/credit/src/routes/(app)/settings/
  +page.svelte           (redirect para /settings/config)
  +layout.svelte
  config/
    +page.server.ts      (carrega configs private_credit)
    +page.svelte         (ConfigEditor para private_credit)
  system/
    +page.server.ts
    +page.svelte         (ServiceHealthCard + WorkerLogFeed — workers do Credit)
```

Verificar a estrutura de rotas existente em `frontends/credit/src/routes/(app)/`
antes de criar — seguir o mesmo padrão de layout.

---

## Fase 4 — Adicionar "Settings" na navegação do Wealth e Credit

### Wealth nav

Em `frontends/wealth/src/routes/(app)/+layout.svelte`, adicionar link para `/settings`:

```svelte
<!-- Ler o arquivo antes de editar — seguir o padrão de nav existente -->
<!-- Adicionar item Settings (ícone: gear/cog) com subitens Config e System -->
```

Fazer o mesmo no Credit layout.

---

## Fase 5 — Unificar CSS (eliminar branding por vertical)

O Admin tem um `app.css` com variáveis específicas.
O Wealth e Credit têm seus próprios `app.css`.

**Objetivo:** um único tema InvestIntell aplicado em ambos os frontends.

1. Auditar as variáveis CSS dos 3 `app.css` — listar diferenças reais
2. Criar `packages/ui/src/lib/styles/investintell-theme.css` com as variáveis consolidadas
3. No `app.css` do Wealth e Credit: importar o tema compartilhado
4. Garantir que `@netz/ui` exporte o tema (já pode estar, verificar)

Não é necessário que Wealth e Credit sejam identicamente visuais —
mas devem usar as mesmas variáveis CSS como base.

---

## Fase 6 — Deletar o Admin frontend

Após confirmar que Wealth e Credit têm Settings funcionando:

### 6.1 Remover do monorepo

```bash
# Não executar diretamente — apenas a sequência correta
# 1. Remover o diretório
rm -rf frontends/admin/

# 2. pnpm-workspace.yaml — "frontends/*" já cobre o que sobrar, nada a mudar

# 3. turbo.json — sem referência explícita ao admin, nada a mudar

# 4. Verificar se package.json raiz tem script referenciando --filter admin
```

Verificar `package.json` raiz e quaisquer scripts que referenciem `admin` antes de deletar.

### 6.2 Remover deploy do Cloudflare Pages

Etapa **manual** (não pode ser feita via código):
1. Acessar Cloudflare Pages dashboard
2. Deletar o projeto `admin.investintell.com` (ou nome equivalente)
3. Remover DNS record correspondente

### 6.3 Variáveis de ambiente

Verificar se há variáveis no Railway ou `.env` que só existem para o admin:
- `PUBLIC_ADMIN_API_URL` ou similar → remover
- `ADMIN_CLERK_*` → remover se não compartilhado

---

## Fase 7 — Remover prompts customizados do backend

Com o Admin eliminado, os endpoints de prompt customizado ficam sem caller.

Verificar no backend:
```bash
# Encontrar endpoints de prompt
grep -r "prompts" backend/app/domains/admin/routes/ --include="*.py" -l
```

Endpoints a verificar para remoção/deprecação:
- `GET /api/v1/admin/prompts/[vertical]`
- `POST /api/v1/admin/prompts/[vertical]`
- Qualquer `PromptOverride` model/migration

**Regra:** só remover endpoints de prompt se:
1. Nenhum outro caller (Wealth, Credit frontend) os usa
2. O `VerticalConfigOverride` model de prompts pode ser dropado da DB

Verificar `prompt_overrides` no DB antes de criar migration de drop.

---

## Definition of Done

- [ ] `ConfigEditor`, `ConfigDiffView`, `ServiceHealthCard`, `WorkerLogFeed` em `@netz/ui`
- [ ] `/settings/config` no Wealth (liquid_funds configs)
- [ ] `/settings/system` no Wealth (health + worker triggers)
- [ ] `/settings/config` no Credit (private_credit configs)
- [ ] `/settings/system` no Credit (health + worker triggers)
- [ ] Link "Settings" na nav do Wealth e Credit
- [ ] `app.css` do Wealth e Credit usando tema InvestIntell compartilhado
- [ ] `frontends/admin/` deletado
- [ ] Cloudflare Pages admin project removido (manual)
- [ ] Variáveis de ambiente admin removidas
- [ ] `npm run build` zero erros no Wealth e Credit
- [ ] `make check` no backend (nenhuma mudança esperada no backend nesta fase)

## O que NÃO fazer

- Não recriar o `BrandingEditor` — branding é InvestIntell, sem customização por tenant
- Não migrar `PromptEditor` / `JinjaEditor` — prompts são IP central, sem override
- Não migrar o tenant CRUD UI — criar tenants via endpoint admin protegido por super_admin
- Não migrar o `/inspect` — sem valor fora do contexto de debugging pontual
- Não criar nova autenticação nos Settings — usar o JWT Clerk existente em cada frontend
- Não quebrar os endpoints backend `/admin/config/*` e `/admin/health/*` —
  continuam sendo usados pelos novos Settings pages

## Ordem de execução recomendada

```
Fase 1 (mover componentes para @netz/ui)
    ↓
Fase 2 (Wealth Settings) — validar funcionamento
    ↓
Fase 3 (Credit Settings) — validar funcionamento
    ↓
Fase 4 (nav links)
    ↓
Fase 5 (CSS unificado)
    ↓
Fase 6 (deletar admin) — apenas após Fases 2-5 confirmadas
    ↓
Fase 7 (backend cleanup prompts) — opcional, não bloqueia
```

## Failure modes esperados

- **`ConfigEditor` usa `$lib/api/client` do admin internamente:**
  Refatorar para aceitar `fetchFn: (path, options) => Promise<Response>` como prop
  — o caller injeta o cliente HTTP correto. Padrão mais testável.

- **`WorkerLogFeed` usa SSE via `EventSource` direto:**
  Verificar se usa `fetch + ReadableStream` (padrão do sistema) ou `EventSource`.
  Se for `EventSource`, refatorar para `fetch` antes de mover — `EventSource`
  não suporta auth headers.

- **`ConfigDiffView` importa `CodeEditor` (Monaco):**
  Monaco é uma dependência pesada (~2MB). Verificar se já está no bundle do Wealth
  ou se precisa ser adicionado ao `package.json` do Wealth.
  Se não estiver, avaliar se o diff view simplificado (sem Monaco) é suficiente.

- **Role check nos Settings:**
  Settings deve ser visível apenas para `ADMIN` role. Verificar como o Wealth
  implementa role checks nas rotas existentes e usar o mesmo padrão.
