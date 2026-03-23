# Prompt: Collapsible Two-Level Sidebar — Wealth OS

## Contexto

Frontend: SvelteKit 5 runes, `@netz/ui`, Tailwind.
Arquivo a modificar: `frontends/wealth/src/routes/(app)/+layout.svelte`

## Referência visual

Thunder Client sidebar: duas camadas hierárquicas.
- Nível 1: Seções colapsáveis com chevron (Discovery & Screening, Investment Engine, etc.)
- Nível 2: Links de navegação dentro de cada seção
- Estado de colapso persiste em `$state` local (não precisa de localStorage nesta fase)
- Sidebar inteira também colapsa para modo icon-only (já existe, manter)

## Estado atual

O `+layout.svelte` tem um sidebar com seções hardcoded usando `navItems.slice(0,2)`,
`navItems.slice(2,6)`, etc. Funciona mas é rígido e não colapsa por seção.

## Estrutura de dados desejada

Substituir o array `navItems: SidebarNavItem[]` flat por `sections: SidebarSection[]`:

```typescript
interface SidebarNavItem {
  label: string;
  href: string;
  icon: any; // lucide-svelte component
}

interface SidebarSection {
  id: string;
  label: string;          // ex: "Discovery & Screening"
  icon?: any;             // ícone opcional para o header da seção
  items: SidebarNavItem[];
  defaultOpen?: boolean;  // true = começa expandido
}
```

Definição das seções (manter exatamente estes itens e ordem):

```typescript
const sections: SidebarSection[] = [
  {
    id: "discovery",
    label: "Discovery & Screening",
    defaultOpen: true,
    items: [
      { label: "Screener",    href: "/screener",    icon: Search },
      { label: "DD Reports",  href: "/dd-reports",  icon: ClipboardList },
    ],
  },
  {
    id: "investment",
    label: "Investment Engine",
    defaultOpen: true,
    items: [
      { label: "Universe",         href: "/universe",         icon: Globe },
      { label: "Model Portfolios", href: "/model-portfolios", icon: Folders },
      { label: "Portfolios",       href: "/portfolios",       icon: Briefcase },
      { label: "Allocation",       href: "/allocation",       icon: PieChart },
    ],
  },
  {
    id: "risk",
    label: "Risk & Intelligence",
    defaultOpen: true,
    items: [
      { label: "Risk",      href: "/risk",      icon: Zap },
      { label: "Analytics", href: "/analytics", icon: BarChart2 },
      { label: "Exposure",  href: "/exposure",  icon: Map },
      { label: "Macro",     href: "/macro",     icon: Landmark },
    ],
  },
  {
    id: "content",
    label: "Content & Data",
    defaultOpen: true,
    items: [
      { label: "Documents", href: "/documents", icon: FileText },
      { label: "Content",   href: "/content",   icon: Newspaper },
    ],
  },
];
```

## Comportamento das seções colapsáveis

Estado: `let openSections = $state<Set<string>>(new Set(sections.filter(s => s.defaultOpen).map(s => s.id)))`

Toggle: `function toggleSection(id: string) { const next = new Set(openSections); next.has(id) ? next.delete(id) : next.add(id); openSections = next; }`

### Header de seção (nível 1)
- Clicável em toda a largura
- Label em uppercase, tamanho 10px, letra-spacing 0.08em, cor `--netz-text-muted`
- Chevron à direita: rotaciona 90° quando aberto, 0° quando fechado
- Animação de rotação: `transition: transform 200ms ease`
- No modo collapsed (sidebar icon-only): ocultar label e chevron, mostrar apenas divisor

### Items de navegação (nível 2)
- Animação de expand/collapse: `display: grid; grid-template-rows: 0fr / 1fr` com `overflow: hidden`
  e `transition: grid-template-rows 200ms ease` — padrão moderno sem height: auto hacks
- Item ativo: background `color-mix(in srgb, var(--netz-brand-primary) 12%, transparent)`, 
  cor `--netz-brand-primary`, font-weight 600
- Item hover: background `color-mix(in srgb, var(--netz-brand-primary) 6%, transparent)`
- Ícone: 18px, strokeWidth 1.5 (igual ao atual)
- No modo collapsed: mostrar apenas ícone centralizado (sem label), tooltip via `title` attribute

## Animação

Usar CSS grid-template-rows para accordion suave (não height):

```css
.section-items {
  display: grid;
  grid-template-rows: 0fr;
  overflow: hidden;
  transition: grid-template-rows 200ms ease;
}
.section-items.open {
  grid-template-rows: 1fr;
}
.section-items-inner {
  min-height: 0;
  padding: 4px 8px;
}
```

## Modo Collapsed (sidebar icon-only)

Quando `sidebarCollapsed = true`:
- Seções não têm header clicável — mostrar apenas divisor sutil entre grupos
- Todos os items ficam visíveis (não há colapso por seção no modo icon)
- Cada item mostra apenas ícone centralizado com `title` para tooltip nativo
- Footer collapse button mantém comportamento atual

## Restrições obrigatórias

1. **Svelte 5 runes**: `$state`, `$derived`, `$effect`. Sem `writable()`.
2. **Sem imports adicionais**: usar apenas o que já está importado (`lucide-svelte`, `@netz/ui`, etc.)
3. **CSS scoped**: todo CSS dentro do `<style>` do componente, sem classes Tailwind no sidebar
4. **Não quebrar** o layout shell existente (grid `--sidebar-w`, topbar, `netz-shell-content`)
5. **Manter** o footer com o botão de colapso da sidebar
6. **`make check` deve passar** após as mudanças

## Arquivos a modificar

Apenas: `frontends/wealth/src/routes/(app)/+layout.svelte`

Nenhum outro arquivo precisa ser alterado.

## Critério de sucesso

- Cada seção tem header clicável que colapsa/expande seus itens com animação suave
- Estado de colapso por seção funciona independentemente
- Modo icon-only (sidebar collapsed) ainda funciona
- Link ativo highlighted corretamente
- Transições suaves em ambos: colapso de seção e colapso da sidebar
- Visualmente similar ao Thunder Client: limpo, hierárquico, professional
