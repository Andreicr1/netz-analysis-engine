# Prompt: Frontend Migration Phase 1 — Sidebar, Layout, Design System

## Contexto

Migrar o app `frontends/wealth/` de `@netz/ui` para `@investintell/ui` com:
- Nova taxonomia de sidebar por fluxo do processo institucional
- Tokens `--ii-*` em vez de `--netz-*`
- Fonte Geist em vez de IBM Plex Sans
- Branding "InvestIntell" em vez de "Wealth OS"
- Nova rota `/investment-policy` (renomear `settings/config`)

## Mandatory First Steps

1. Ler `frontends/wealth/src/routes/(app)/+layout.svelte` — estrutura atual completa
2. Ler `packages/investintell-ui/src/lib/styles/tokens.css` — tokens `--ii-*` disponíveis
3. Ler `packages/investintell-ui/src/lib/index.ts` — exports disponíveis
4. Verificar `frontends/wealth/package.json` — dependências atuais

---

## Fase 1 — Atualizar dependência do pacote

**Arquivo:** `frontends/wealth/package.json`

Substituir `"@netz/ui"` por `"@investintell/ui"` nas dependencies.

Rodar `pnpm install` no monorepo root após a mudança.

---

## Fase 2 — Nova Sidebar em `+layout.svelte`

**Arquivo:** `frontends/wealth/src/routes/(app)/+layout.svelte`

### 2.1 Nova taxonomia de seções

Substituir o array `sections` pela nova estrutura por fluxo do processo:

```typescript
const sections: SidebarSection[] = [
  {
    id: "setup",
    label: "Setup",
    defaultOpen: true,
    items: [
      { label: "Investment Policy", href: "/investment-policy", icon: ShieldCheck },
    ],
  },
  {
    id: "portfolio",
    label: "Portfolio",
    defaultOpen: true,
    items: [
      { label: "Portfolio Builder", href: "/model-portfolios", icon: Layers },
      { label: "Assets Universe",   href: "/universe",         icon: Database },
      { label: "Portfolios",        href: "/portfolios",       icon: Briefcase },
    ],
  },
  {
    id: "research",
    label: "Research",
    defaultOpen: true,
    items: [
      { label: "Screener",   href: "/screener",   icon: Search },
      { label: "DD Reports", href: "/dd-reports", icon: ClipboardList },
    ],
  },
  {
    id: "intelligence",
    label: "Intelligence",
    defaultOpen: true,
    items: [
      { label: "Analytics",  href: "/analytics", icon: BarChart2 },
      { label: "Macro",      href: "/macro",      icon: Globe },
      { label: "Risk",       href: "/risk",        icon: Zap },
    ],
  },
  {
    id: "content",
    label: "Content",
    defaultOpen: true,
    items: [
      { label: "Content",   href: "/content",   icon: Newspaper },
      { label: "Documents", href: "/documents", icon: FileText },
    ],
  },
  {
    id: "system",
    label: "System",
    defaultOpen: false,
    items: [
      { label: "System", href: "/settings/system", icon: Settings },
    ],
  },
];
```

### 2.2 Atualizar imports de ícones Lucide

Adicionar ícones necessários e remover os não usados:
```typescript
import {
  ShieldCheck, Layers, Database, Briefcase, Search,
  ClipboardList, BarChart2, Globe, Zap, Newspaper,
  FileText, Settings, Bot, ChevronDown, LayoutDashboard,
} from "lucide-svelte";
```

### 2.3 Atualizar branding no topbar

Substituir o bloco de brand atual pelo logo InvestIntell:

```svelte
<div class="ii-topbar-brand">
  <!-- Hourglass SVG mark (inline) -->
  <svg width="20" height="24" viewBox="0 0 20 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="4"  cy="4"  r="1.5" fill="#2563EB"/>
    <circle cx="10" cy="4"  r="1.5" fill="#2563EB"/>
    <circle cx="16" cy="4"  r="1.5" fill="#2563EB"/>
    <circle cx="10" cy="12" r="2"   fill="#2563EB"/>
    <circle cx="4"  cy="20" r="1.5" fill="#64748B"/>
    <circle cx="10" cy="20" r="1.5" fill="#64748B"/>
    <circle cx="16" cy="20" r="1.5" fill="#64748B"/>
    <line x1="4"  y1="4"  x2="10" y2="12" stroke="#2563EB" stroke-width="1" stroke-linecap="round"/>
    <line x1="16" y1="4"  x2="10" y2="12" stroke="#2563EB" stroke-width="1" stroke-linecap="round"/>
    <line x1="4"  y1="20" x2="10" y2="12" stroke="#64748B" stroke-width="1" stroke-linecap="round"/>
    <line x1="16" y1="20" x2="10" y2="12" stroke="#64748B" stroke-width="1" stroke-linecap="round"/>
  </svg>
  {#if !sidebarCollapsed}
    <span class="ii-topbar-wordmark">
      <span class="ii-topbar-invest">invest</span><span class="ii-topbar-intell">intell</span>
    </span>
  {/if}
</div>
```

### 2.4 Atualizar tokens CSS em `<style>`

Substituir todas as referências `--netz-*` pelos equivalentes `--ii-*`:

| De | Para |
|---|---|
| `--netz-border-subtle` | `--ii-border-subtle` |
| `--netz-border` | `--ii-border` |
| `--netz-border-focus` | `--ii-border-focus` |
| `--netz-surface-elevated` | `--ii-surface` |
| `--netz-surface-alt` | `--ii-surface-alt` |
| `--netz-surface` | `--ii-surface` |
| `--netz-bg` | `--ii-bg` |
| `--netz-text-primary` | `--ii-text-primary` |
| `--netz-text-secondary` | `--ii-text-secondary` |
| `--netz-text-muted` | `--ii-text-muted` |
| `--netz-brand-primary` | `--ii-brand-primary` |
| `--netz-brand-highlight` | `--ii-brand-secondary` |
| `--netz-ease-out` | `--ii-ease-out` |
| `--netz-radius-md` | `--ii-radius-md` |
| `--netz-radius-xs` | `--ii-radius-xs` |
| `--netz-font-sans` | `--ii-font-sans` |
| `--netz-font-mono` | `--ii-font-mono` |

### 2.5 Atualizar import de ThemeToggle

```typescript
// De:
import { ThemeToggle } from "@netz/ui";
// Para:
import { ThemeToggle } from "@investintell/ui";
```

### 2.6 Renomear classes CSS internas

Substituir prefixo `netz-` por `ii-` em todos os nomes de classe do layout:
- `.netz-shell` → `.ii-shell`
- `.netz-topbar` → `.ii-topbar`
- `.netz-workstation-sidebar` → `.ii-sidebar`
- `.netz-shell-main` → `.ii-main`
- `.netz-shell-content` → `.ii-content`
- `.netz-shell-sidebar` → `.ii-sidebar-wrapper`
- etc.

Atualizar todos os usos correspondentes no template.

### 2.7 Adicionar estilos de wordmark

```css
.ii-topbar-wordmark {
  font-family: var(--ii-font-sans);
  font-size: 16px;
  font-weight: 400;
  letter-spacing: -0.4px;
  white-space: nowrap;
  overflow: hidden;
}

.ii-topbar-invest {
  color: var(--ii-text-primary);
}

.ii-topbar-intell {
  color: var(--ii-brand-primary);
  font-weight: 600;
}
```

---

## Fase 3 — Criar rota `/investment-policy`

A rota `/settings/config` existe mas aponta para o editor JSON raw.
A nova página Investment Policy é uma interface reativa com sliders.

### 3.1 Criar página

**Arquivo:** `frontends/wealth/src/routes/(app)/investment-policy/+page.svelte`

```svelte
<script lang="ts">
  import type { PageData } from "./$types";
  // Usar componentes de @investintell/ui
  // Slider, Input, Select, Switch, Button, Card, SectionCard
</script>
```

**Arquivo:** `frontends/wealth/src/routes/(app)/investment-policy/+page.server.ts`

Carregar configs do backend:
```typescript
import type { PageServerLoad } from "./$types";
import { createServerApiClient } from "$lib/api/client";

export const load: PageServerLoad = async ({ locals }) => {
  const api = createServerApiClient(locals.token);
  const [configsResult] = await Promise.allSettled([
    api.get("/admin/configs/"),
  ]);
  const configs = configsResult.status === "fulfilled"
    ? (configsResult.value as any[]).filter((c: any) => c.vertical === "wealth")
    : [];
  return { configs, token: locals.token };
};
```

### 3.2 Layout da página Investment Policy

A página tem duas colunas:
- Esquerda (260px): navegação de categorias com links âncora
- Direita (flex): seções de configuração

**Categorias:**
1. Risk Limits — VaR, CVaR, Max Drawdown por model portfolio
2. Scoring Weights — 6 componentes do scoring (momentum, quality, value, risk_adj_return, fee_efficiency, insider_sentiment)
3. Universe Filters — Min AUM, Max ER, exclusões
4. Rebalancing Rules — drift threshold, frequência

**Seção Risk Limits — por model portfolio:**
```
[Card: Conservative Income]
  CVaR Limit:      [====●------] 5.0%
  VaR Limit:       [===●-------] 4.0%
  Max Drawdown:    [======●----] 15%
  Min Liquidity:   [========●--] 80%
  [Save]  (disabled até haver mudança)

[Card: Balanced Growth]
  ...

[Card: Aggressive Growth]
  ...
```

**Seção Scoring Weights:**
```
momentum              [input: 20%] [====]
quality               [input: 20%] [====]
value                 [input: 15%] [===]
risk_adjusted_return  [input: 25%] [=====]
fee_efficiency        [input: 10%] [==]
insider_sentiment     [input: 10%] [==]
                      Total: 100% ✓
[Auto-normalize toggle]
[Save Weights]
```

**Seção Universe Filters:**
```
Min AUM:           [$___M] input
Max Expense Ratio: [====●------] 1.5%
Exclude Index Funds: [toggle]
Exclude Target Date: [toggle]
Min Track Record:  [___] years
[Save Filters]
```

**Seção Rebalancing Rules:**
```
Drift Threshold:   [===●-------] 5%
Frequency:         [Select: Monthly]
Min Trade Size:    [$___]
[Save Rules]
```

**Comportamento de save:**
- Cada seção tem seu próprio botão Save
- `PATCH /admin/configs/{vertical}/{config_type}` com o valor atualizado
- Toast de confirmação após save bem-sucedido
- Botão Save fica disabled até haver mudança (dirty state por seção)

---

## Fase 4 — Atualizar imports `@netz/ui` → `@investintell/ui` no layout

**Arquivo:** `frontends/wealth/src/routes/(app)/+layout.svelte`

Qualquer import de `@netz/ui` deve ser substituído por `@investintell/ui`.

---

## Fase 5 — Validação

```bash
# No root do monorepo
pnpm check --filter frontends/wealth

# Build
pnpm build --filter frontends/wealth
```

**Esperado:**
- Zero erros de typecheck
- Build bem-sucedido
- Sidebar com nova taxonomia funcional
- Logo "investintell" no topbar
- Rota /investment-policy acessível

---

## What NOT to Do

- Não migrar todas as páginas agora — apenas o layout e a nova página Investment Policy
- Não remover as rotas existentes (`/settings`, `/allocation`, etc.) — apenas ajustar a sidebar
- Não hardcodar cores hex nos estilos — usar apenas tokens `--ii-*`
- Não usar `EventSource` — padrão é `fetch()` + `ReadableStream`
- Não remover `packages/ui/` ainda — manter durante transição
- Não alterar backend — apenas frontend
- Não modificar as rotas de sistema existentes em `settings/` — apenas criar a nova `investment-policy/`
