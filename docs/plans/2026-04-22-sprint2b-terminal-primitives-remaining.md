# Sprint 2b — Migração dos 6 Componentes Terminais Restantes

**Data**: 2026-04-22
**Dono**: Andrei
**Status**: aguardando dispatch — KpiCard: migrar preservando (decisão confirmada 2026-04-22)
**Predecessor**: `docs/plans/2026-04-22-sprint2a-primitives-consolidation.md` (concluído — MiniSparkline + Drawer migrados)

---

## Contexto

A Sprint 2a fechou MiniSparkline e Drawer. Restam 6 componentes em
`packages/investintell-ui/src/lib/components/terminal/` que usam exclusivamente
`--terminal-*` tokens e pertencem ao `@investintell/ii-terminal-core`:

| Componente | Linhas | Export atual |
|---|---|---|
| `Pill.svelte` | 123 | `TerminalPill` + types `PillTone`, `PillSize`, `PillAs` |
| `Kbd.svelte` | 55 | `TerminalKbd` |
| `KpiCard.svelte` | 128 | `TerminalKpiCard` + types `KpiCardSize`, `KpiDeltaTone` |
| `DensityToggle.svelte` | 38 | `TerminalDensityToggle` + type `Density` |
| `AccentPicker.svelte` | 92 | `TerminalAccentPicker` + type `Accent` |
| `ThemeToggle.svelte` | 38 | `TerminalThemeToggle` + type `TerminalTheme` |

Todos exportados de `packages/investintell-ui/src/lib/index.ts` linhas 101-115.

**Estado Svelte 5 confirmado por grep:** todos 6 já usam `$props()` com `Props` tipado. Nenhum usa `export let` legado. Migração é cópia literal — zero refatoração de runes necessária.

---

## Decisão pendente: KpiCard

`TerminalKpiCard` tem **zero consumidores ativos** no repositório. Grep exaustivo (`*.svelte`, `*.ts`) retornou apenas a linha de export em `index.ts`.

Opções:
- **Deletar** — remove 128 linhas de código sem uso real
- **Migrar preservando** — custo baixo, evita decisão irreversível se sprint futura precisar

**Decisão**: migrar preservando (confirmado 2026-04-22).

---

## O que NÃO migra

- `packages/investintell-ui/src/lib/tokens/terminal.css` — **definição** de tokens CSS (`:root { --terminal-*: value }`). Fica em `@investintell/ui` para ser importado globalmente pelo host app. Não é consumo, é fonte.
- `packages/investintell-ui/src/lib/styles/typography.css` — define `[data-surface="terminal"]` font overrides e variáveis `--ii-font-terminal-*`. Mesma lógica: fica em `@investintell/ui`.

Após a sprint, o diretório `components/terminal/` em `@investintell/ui` deve ficar **vazio e ser deletado**. Os arquivos CSS de tokens ficam onde estão.

---

## Escopo do PR único (Sprint 2b consolidada)

Recomendação: **um único PR** com todos os 5 ou 6 componentes + todos os consumidores.

Justificativa:
- 4 dos 6 componentes têm consumer único (`TerminalTweaksPanel`) — dividir em PRs forçaria abrir o mesmo arquivo 4 vezes.
- Remoção atômica dos exports de `@investintell/ui` mantém o Invariant I verde imediatamente. PRs incrementais deixam o pacote em estado misto.
- `Pill` tem 11 call-sites mas todos seguem o mesmo padrão de troca de import.

**Branch**: `feat/sprint2b-terminal-primitives-remaining`

---

## Consumidores mapeados (todos os 11 call-sites)

### `TerminalPill` — 8 consumidores

| Arquivo | Uso |
|---------|-----|
| `packages/ii-terminal-core/src/lib/components/allocation/IpsSummaryStrip.svelte` | 4 usos |
| `packages/ii-terminal-core/src/lib/components/allocation/RegimeContextStrip.svelte` | 2 usos |
| `packages/ii-terminal-core/src/lib/components/terminal/live/ChartToolbar.svelte` | 1 uso |
| `packages/ii-terminal-core/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` | 1 uso |
| `frontends/wealth/src/lib/components/allocation/IpsSummaryStrip.svelte` | 4 usos (duplicata do core) |
| `frontends/wealth/src/lib/components/allocation/RegimeContextStrip.svelte` | 2 usos (duplicata) |
| `frontends/wealth/src/lib/components/terminal/live/ChartToolbar.svelte` | 1 uso (duplicata) |
| `frontends/wealth/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` | 1 uso (duplicata) |

### `TerminalKbd` — 4 consumidores

| Arquivo | Uso |
|---------|-----|
| `frontends/terminal/src/routes/macro/+page.svelte` | 1 uso |
| `frontends/wealth/src/routes/(terminal)/macro/+page.svelte` | 1 uso |
| `packages/ii-terminal-core/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` | 1 uso |
| `frontends/wealth/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` | 1 uso (duplicata) |

### `TerminalAccentPicker`, `TerminalDensityToggle`, `TerminalThemeToggle` — 2 consumidores cada

| Arquivo |
|---------|
| `packages/ii-terminal-core/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` |
| `frontends/wealth/src/lib/components/terminal/shell/TerminalTweaksPanel.svelte` (duplicata) |

---

## Sequência de execução

### Passo 1 — Copiar componentes para `primitives/`

Destino: `packages/ii-terminal-core/src/lib/components/terminal/primitives/`

Copiar 5 (ou 6) arquivos `.svelte` sem alterações de conteúdo.

Se houver arquivos `.test.ts` para os componentes em `@investintell/ui`, portá-los para
`packages/ii-terminal-core/src/lib/components/terminal/primitives/__tests__/` para preservar coverage.

### Passo 2 — Estender `primitives/index.ts`

Adicionar exports em bloco aditivo abaixo dos exports existentes (MiniSparkline + Drawer — não tocar):

```
TerminalAccentPicker + type Accent
TerminalDensityToggle + type Density
TerminalKbd (sem types adicionais)
TerminalKpiCard + types KpiCardSize, KpiDeltaTone  ← omitir se decisão for deletar
TerminalPill + types PillTone, PillSize, PillAs
TerminalThemeToggle + type TerminalTheme
```

### Passo 3 — Adicionar ao barrel raiz do core

Em `packages/ii-terminal-core/src/lib/index.ts`, adicionar re-exports dos novos símbolos
(consistente com o que foi feito em Sprint 2a para MiniSparkline e Drawer).

### Passo 4 — Atualizar todos os 11 consumidores

Para cada arquivo na tabela acima: trocar

```
import { TerminalPill, ... } from "@investintell/ui"
```

por

```
import { TerminalPill, ... } from "@investintell/ii-terminal-core"
```

Os 4 arquivos em `frontends/wealth/src/lib/components/` são duplicatas físicas dos
arquivos em `packages/ii-terminal-core/src/lib/components/` — atualizar ambos no mesmo PR.

### Passo 5 — Deletar de `@investintell/ui`

Arquivos a deletar:
- `packages/investintell-ui/src/lib/components/terminal/AccentPicker.svelte`
- `packages/investintell-ui/src/lib/components/terminal/DensityToggle.svelte`
- `packages/investintell-ui/src/lib/components/terminal/Kbd.svelte`
- `packages/investintell-ui/src/lib/components/terminal/KpiCard.svelte` (se migrado)
- `packages/investintell-ui/src/lib/components/terminal/Pill.svelte`
- `packages/investintell-ui/src/lib/components/terminal/ThemeToggle.svelte`
- Arquivos `.test.ts` correspondentes
- Diretório `packages/investintell-ui/src/lib/components/terminal/` (ficará vazio)

Linhas a remover de `packages/investintell-ui/src/lib/index.ts`:
- Bloco completo linhas 101-115 (seção `// ── Terminal primitives ──`)

### Passo 6 — Verificar ESLint config

Checar se `frontends/eslint.config.js` tem regra restringindo import de
`@investintell/ui/components/terminal/*`. Se sim, remover — o path deixa de existir.

---

## Gates de validação

- [ ] `svelte-autofixer` em todos os componentes migrados — sem warnings
- [ ] `pnpm --filter @investintell/ii-terminal-core build` verde
- [ ] `pnpm --filter @investintell/ui build` verde
- [ ] `pnpm --filter ii-terminal check` sem novos erros nos arquivos tocados
- [ ] `pnpm --filter netz-wealth-os check` sem novos erros nos arquivos tocados
- [ ] **Invariant I**: `grep -rn "var(--terminal-" packages/investintell-ui/src/lib/ --include="*.svelte"` → 0 resultados
- [ ] **Cleanup completo**: `ls packages/investintell-ui/src/lib/components/terminal/` → diretório inexistente
- [ ] **Validação visual**: `make dev-wealth` e `make dev-terminal` → abrir `/live` (ChartToolbar com Pill), `/(terminal)/allocation/*` (IpsSummaryStrip + RegimeContextStrip), `/(terminal)/macro` (TerminalKbd hint), abrir TerminalTweaksPanel (Kbd + DensityToggle + AccentPicker + ThemeToggle)

---

## Invariant I — por que fecha após esta sprint

Gate: `grep -rn "var(--terminal-" packages/investintell-ui/src/lib/ --include="*.svelte"` → 0

Após deletar os arquivos `.svelte` de `components/terminal/`, não resta nenhum `.svelte`
em `@investintell/ui` que consuma `var(--terminal-*)`.

Os arquivos `tokens/terminal.css` e `typography.css` **não violam** o gate porque:
1. O flag `--include="*.svelte"` exclui arquivos `.css` do escopo.
2. Mesmo se o grep fosse ampliado para `.css`, esses arquivos **declaram** os tokens
   (`:root { --terminal-*: value }`) — não os consomem dentro de um componente.
   Declaração ≠ consumo cross-surface.

**Recomendação**: após fechar o gate manual, adicionar o grep como step obrigatório
no CI para bloquear regressão futura.
