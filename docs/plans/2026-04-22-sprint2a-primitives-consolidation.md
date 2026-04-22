# Sprint 2a — Consolidação de Primitivos Terminais em `ii-terminal-core`

**Data**: 2026-04-22
**Dono**: Andrei
**Status**: em execução — PR-2a.1 CONCLUÍDO, PR-2a.2 próximo
**Predecessor**: `docs/plans/2026-04-19-ii-terminal-extraction.md` (X1–X5b concluídos, PRs #240–#247)

---

## Contexto

A extração do terminal para `frontends/terminal/` (sprint X) criou o pacote `@investintell/ii-terminal-core` com ~100 componentes. No entanto, dois primitivos terminais — `MiniSparkline` e `Drawer` — continuam vivendo em `packages/investintell-ui/src/lib/components/terminal/` e são exportados de `@investintell/ui`.

Isso viola a separação arquitetural estabelecida:

| Pacote | Responsabilidade correta |
|---|---|
| `@investintell/ui` (`@netz/ui`) | Tokens semânticos neutros, shadcn wrappers, formatters, layouts genéricos |
| `@investintell/ii-terminal-core` | Primitivos terminais (shell, data grid, charts, sparklines, drawer) com tokens navy+orange |

`MiniSparkline` e `Drawer` usam **exclusivamente** `--terminal-*` CSS tokens — são semanticamente terminais, não genéricos. Mantê-los em `@investintell/ui` contamina o pacote com artefatos de surface-específica.

**Estado atual confirmado (leitura de arquivos):**
- `packages/investintell-ui/src/lib/components/terminal/MiniSparkline.svelte` — 122 linhas, Svelte 5 runes OK
- `packages/investintell-ui/src/lib/components/terminal/Drawer.svelte` — 207 linhas, Svelte 5 runes OK
- Exportados em `packages/investintell-ui/src/lib/index.ts` linhas 116-119 como `TerminalMiniSparkline` e `TerminalDrawer`
- 6 consumidores confirmados (ver §6)

---

## Objetivo

Promover `MiniSparkline` e `Drawer` para `packages/ii-terminal-core/src/lib/components/terminal/primitives/`, formalizar a subpasta `primitives/` como casa canônica de átomos terminais reutilizáveis, e limpar `@investintell/ui` de quaisquer dependências de `--terminal-*` tokens.

**Non-goals:**
- Não mover nada para `@netz/ui` (packages/ui)
- Não adicionar componentes terminais ao `@investintell/ui`
- Não alterar lógica de busca ou dados de API
- Não modificar `FundDetailsDrawer` (componente wealth-específico, tokens blue — diferente)

---

## Decisões arquiteturais

### 1. Localização: `terminal/primitives/`

```
packages/ii-terminal-core/src/lib/components/terminal/
├── primitives/                    ← NOVO
│   ├── MiniSparkline.svelte
│   ├── Drawer.svelte
│   └── index.ts
├── shell/
├── builder/
├── live/
├── macro/
├── dd/
├── layout/
├── data/
├── charts/
└── focus-mode/
```

**Justificativa para `primitives/`** (não `atoms/`): alinha com vocabulário Radix/shadcn-svelte já referenciado no projeto. `atoms/` remete a Atomic Design (Brad Frost) — fora do modelo mental adotado. As subpastas existentes são feature-oriented; `primitives/` formaliza uma categoria distinta de átomos sem feature própria.

**Critério de entrada em `primitives/`:**
1. Usa apenas `--terminal-*` tokens (sem hex, sem tokens wealth/genéricos)
2. Sem estado de domínio (não chama backend, não persiste, sem shape específico de domínio nas props)
3. Reutilizável em ≥ 2 features distintas (critério empírico, não especulativo)
4. API slot-based ou prop-based simples

**Candidatos futuros** (não migrar agora): `TerminalTag`, `TerminalKeyValue`, `TerminalHairlineDivider`, `TerminalStatusDot`.

### 2. Estratégia de export

Adicionar em `packages/ii-terminal-core/src/lib/index.ts`:

```ts
// Terminal primitives
export { default as TerminalMiniSparkline } from './components/terminal/primitives/MiniSparkline.svelte';
export type { MiniSparklineTone } from './components/terminal/primitives/MiniSparkline.svelte';
export { default as TerminalDrawer } from './components/terminal/primitives/Drawer.svelte';
export type { DrawerSide } from './components/terminal/primitives/Drawer.svelte';
```

**Manter prefixo `Terminal*`:** 6 call-sites já existem; sem rename os consumidores não quebram. O prefixo é necessário para distinguir de shadcn `Dialog`/`Drawer` no autocomplete.

**Barrel `primitives/index.ts`:**

```ts
export { default as TerminalMiniSparkline } from './MiniSparkline.svelte';
export type { MiniSparklineTone } from './MiniSparkline.svelte';
export { default as TerminalDrawer } from './Drawer.svelte';
export type { DrawerSide } from './Drawer.svelte';
```

Root `index.ts` passa a `export * from './components/terminal/primitives'` — quando a 3ª/4ª primitiva surgir, não precisa tocar no root.

**Sem subpath exports no `package.json`:** core é consumido por apenas 2 frontends internos; tree-shaking do bundler resolve dead-code. Entrypoint único simplifica Invariant H scanner e IDE autocomplete.

### 3. Svelte 5 — validação dos componentes

**MiniSparkline — sem refatoração necessária:**

```ts
const resolvedTone = $derived<MiniSparklineTone>(tone ?? computeTone(data));
const points = $derived(buildPoints(data, width, height, strokeWidth));
```

Correto. `$derived.by()` é overkill para expressões de uma linha. `computeTone` e `buildPoints` são funções puras — `$derived` é a escolha certa.

**Drawer — apenas extensão, sem refatoração estrutural:**

Renomear `titleSlot` → `title` (mais idiomático no Svelte 5) e adicionar `footer` na mesma passada da migração para não causar dois breaking changes separados.

API final:

```ts
interface Props {
  open: boolean;
  label: string;
  side?: DrawerSide;       // "left" | "right", default "right"
  width?: number;          // px, default 320
  onClose?: () => void;    // opcional — hook para telemetria + navegação programática
  children: Snippet;       // body (obrigatório)
  title?: Snippet;         // renomeado de titleSlot — badge/chip à direita do label
  footer?: Snippet;        // NOVO — CTAs de transição entre fases do lifecycle
}
```

Layout CSS do Drawer (3 linhas grid):

```
┌─────────────────────────┐
│  Header (auto)          │  ← label + title? + close button
├─────────────────────────┤
│  Body (1fr, scroll)     │  ← children, overflow-y: auto
├─────────────────────────┤
│  Footer (auto)          │  ← footer? (colapsa se não passado)
└─────────────────────────┘
grid-template-rows: auto 1fr auto
```

Footer: `border-top: 1px solid var(--terminal-border-hairline)`, padding idêntico ao header.

**`{#if open}` obrigatório (unmount verdadeiro):** o Drawer não pode usar `display:none` para fechar. Unmount garante que qualquer `$effect` de cleanup (ECharts dispose, ResizeObserver disconnect) roda corretamente ao fechar.

### 4. Fronteira SVG vs ECharts

**Regra escrita para o projeto:**

| Critério | SVG polyline (`TerminalMiniSparkline`) | `svelte-echarts` |
|---|---|---|
| Tamanho do alvo | ≤ 120×32 px (thumbnail, inline, célula de grid) | ≥ 240 px wide (painel) |
| Pontos por série | ≤ 250 (típico: 12–60) | ≥ 500, ou múltiplas séries com total ≥ 1000 |
| Eixos | Ausentes | Presentes (ticks, labels, formatados) |
| Interatividade | Nenhuma ou hover simples no wrapper | Tooltip, crosshair, brush, dataZoom, legend |
| Séries | 1 | Múltiplas, com overlay (área, drawdown, banda) |
| Propósito | Indicação de tendência | Leitura de valor, análise comparativa |

**`lightweight-charts`**: reservado para OHLC/candlestick em tempo real no Live Workbench. Não usar para charts analíticos.

**`SparklineWall` (4×N grid FRED):** mantém SVG. 12 pontos mensais por série, zero interatividade, FRED data é estático (diário). ECharts = 40 instâncias canvas ≈ 3–5 MB de overhead desnecessário.

### 5. Drawer hospedando ECharts

Três hazards de lifecycle a respeitar nos consumidores (o Drawer em si não os resolve — é passthrough):

1. **Resize on open**: chart mede container no mount. Se Drawer anima com `transform: translateX`, container pode estar com width=0. Mitigação: ResizeObserver no wrapper do chart (não `onOpened` hook no Drawer — mais robusto para resize subsequente).

2. **Dispose on close**: com `{#if open}`, `$effect` cleanup roda automaticamente no unmount. Se fosse `display:none`, instâncias ECharts vazariam.

3. **Ordering de `$effect` no Svelte 5**: separar em 3 efeitos independentes no wrapper do chart — (a) criação/disposal da instância, (b) `setOption`, (c) `resize` via ResizeObserver. Sem coupling com o Drawer.

O Drawer não importa nada de `svelte-echarts` ou `echarts-core`. Tudo chart-específico fica no wrapper que o consumidor monta dentro de `children`.

### 6. Investigações pré-execução

Antes de iniciar PR-2a.1, ler estes dois arquivos:

1. **`packages/investintell-ui/src/lib/components/ui/charts/SparklineSVG.svelte`** — determinar se é redundante com `MiniSparkline` (deletar), distinto (documentar split), ou stale (deletar). End state ideal: `@investintell/ui` tem `SparklineSVG` neutro sem `--terminal-*`, `ii-terminal-core` tem `TerminalMiniSparkline` que o compõe com tokens terminais.

2. **`frontends/wealth/src/lib/components/portfolio/charts/TaaTransitionSparkline.svelte`** — confirmar se já usa ECharts (se sim, downgrade para SVG no mesmo PR) ou se é SVG (migrar para `primitives/` renomeando para `TerminalTransitionSparkline`, sem prefixo `Taa` que é route-specific).

---

## Escopo de PRs

### PR-2a.1 — Adicionar em core (copy, não move) ✅ CONCLUÍDO

**Branch**: `feat/sprint2a-primitives-copy`

O que foi executado:
- `packages/ii-terminal-core/src/lib/components/terminal/primitives/` criado com `MiniSparkline.svelte`, `Drawer.svelte`, `index.ts`
- Drawer estendido: `title?: Snippet`, `footer?: Snippet`, `onClose` tornado opcional, layout 3 linhas (`grid-template-rows: auto 1fr auto`)
- Exports adicionados em `packages/ii-terminal-core/src/lib/index.ts:29`
- Exports antigos em `packages/investintell-ui/src/lib/index.ts` marcados com `@deprecated` (linhas 116, 119)
- Consumidores internos migrados: `SparklineWall.svelte:16`, `TerminalDataGrid.svelte:45` — usando import relativo para evitar resolver dist estale
- `svelte-autofixer`: sem issues
- `pnpm --filter @investintell/ii-terminal-core check`: passou
- `pnpm --filter @investintell/ii-terminal-core build`: passou
- `pnpm --filter @investintell/ui build`: passou
- `pnpm --filter @investintell/ui check`: falhou por erros preexistentes em `tests/terminal-options.test.ts` (fora de escopo)

Gates:
- [x] `svelte-autofixer` sem warnings
- [x] `build` verde nos dois packages
- [x] `check` verde no core
- [ ] `make check-all` completo — pendente para PR-2a.4 (gate de cleanup final)

### PR-2a.2 — Migrar `frontends/terminal/`

**Branch**: `feat/sprint2a-terminal-imports`

Arquivos a atualizar:

| Arquivo | Mudança |
|---------|---------|
| `frontends/terminal/src/routes/macro/+page.svelte` | `from '@investintell/ui'` → `from '@investintell/ii-terminal-core'`; `titleSlot=` → `{#snippet title()}` |

Gates:
- [ ] `make dev-terminal` + abrir `/macro` no browser
- [ ] Abrir Drawer, verificar animação open/close, testar ESC
- [ ] SparklineWall visível com sparklines coloridos

### PR-2a.3 — Migrar `frontends/wealth/src/routes/(terminal)/`

**Branch**: `feat/sprint2a-wealth-terminal-imports`

Arquivos a atualizar:

| Arquivo | Mudança |
|---------|---------|
| `frontends/wealth/src/routes/(terminal)/macro/+page.svelte` | idem PR-2a.2 |
| `frontends/wealth/src/lib/components/terminal/macro/SparklineWall.svelte` | `TerminalMiniSparkline` de `@investintell/ui` → `@investintell/ii-terminal-core` |
| `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` | idem |

Gates:
- [ ] `make dev-wealth` + abrir `/(terminal)/macro` no browser
- [ ] `/(terminal)/screener` com sparklines na coluna NAV
- [ ] Confirmar que rotas wealth não-terminal (`/portfolio`, `/dashboard`) não consomem `TerminalMiniSparkline` ou `TerminalDrawer`

### PR-2a.4 — Remover de `@investintell/ui`

**Branch**: `feat/sprint2a-cleanup`

Ações:
- Deletar `packages/investintell-ui/src/lib/components/terminal/MiniSparkline.svelte`
- Deletar `packages/investintell-ui/src/lib/components/terminal/Drawer.svelte`
- Se `components/terminal/` ficar vazio: deletar o diretório
- Remover linhas 116-119 de `packages/investintell-ui/src/lib/index.ts`

Gates:
- [ ] `make build-all` verde (prova de que 2a.2 e 2a.3 cobriram todos os consumidores)
- [ ] `grep -rn "var(--terminal-" packages/investintell-ui/src/lib/` → 0 resultados (Invariant I manual)
- [ ] CI completo verde antes de merge

---

## 6 consumidores a migrar (lista definitiva)

| # | Arquivo | Símbolo | PR |
|---|---------|---------|-----|
| 1 | `packages/ii-terminal-core/src/lib/components/terminal/macro/SparklineWall.svelte` | `TerminalMiniSparkline` | interno — atualizar junto com 2a.1 |
| 2 | `packages/ii-terminal-core/src/lib/components/screener-terminal/TerminalDataGrid.svelte` | `TerminalMiniSparkline` | interno — atualizar junto com 2a.1 |
| 3 | `frontends/wealth/src/lib/components/terminal/macro/SparklineWall.svelte` | `TerminalMiniSparkline` | 2a.3 |
| 4 | `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` | `TerminalMiniSparkline` | 2a.3 |
| 5 | `frontends/terminal/src/routes/macro/+page.svelte` | `TerminalDrawer` + `titleSlot→title` | 2a.2 |
| 6 | `frontends/wealth/src/routes/(terminal)/macro/+page.svelte` | `TerminalDrawer` + `titleSlot→title` | 2a.3 |

**Nota:** consumidores 1 e 2 são internos ao core — atualizar na própria PR-2a.1 para evitar que o pacote tenha imports temporariamente inconsistentes.

---

## Invariant I (nova regra de CI)

Após PR-2a.4, adicionar ao scanner de invariantes existente (mesmo script do Invariant H do X3):

```bash
# Invariant I: @investintell/ui não pode referenciar tokens terminais
grep -rn "var(--terminal-" packages/investintell-ui/src/lib/ && echo "INVARIANT_I_FAIL" && exit 1 || true
```

Propósito: bloquear regressão caso um futuro PR adicione por descuido um componente terminal no pacote genérico.

---

## Rollback

- **Se PR-2a.4 quebrar consumidor não previsto em prod**: reverter 2a.4, readicionar re-exports `@deprecated` em `@investintell/ui`, investigar o consumidor faltante, abrir PR-2a.5 de migração, re-tentar remoção.
- PRs 2a.1–2a.3 são individualmente reversíveis sem cascata.
- Sem re-export de compat cross-package (`@investintell/ui` reexportando de `ii-terminal-core`) — criaria import cycle (core já pode depender de ui; o inverso não).

---

## Checklist de validação por PR

- [ ] `svelte-autofixer` em todos os arquivos tocados, sem warnings
- [ ] `make check-all` verde (lint + typecheck + build)
- [ ] Validação visual no browser: `/macro` (Drawer + SparklineWall), `/screener` (MiniSparkline coluna NAV)
- [ ] Drawer: open → ESC → reopen sem listener leak; `footer` renderiza se passado, colapsa se não
- [ ] Zero `--terminal-*` em `packages/investintell-ui/src/lib/` (Invariant I)
- [ ] Formatters de `@netz/ui` respeitados em qualquer conteúdo numérico dentro do Drawer (sem `.toFixed()` ou `Intl.*` inline nos consumidores)
- [ ] `FundDetailsDrawer` intocado (wealth, tokens blue, escopo diferente)
