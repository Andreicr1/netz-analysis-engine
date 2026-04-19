# ii-tokens — Substituição da Camada de Tokens + Superfícies de Página

**Branch**: `feat/ii-tokens-adoption` (long-lived, não merge em main até visual pass)
**Plano**: apenas este arquivo é editável em plan mode; o artefato versionado final do plano vai para `docs/plans/2026-04-19-ii-tokens-adoption.md` durante execução.

---

## Context

Os 10 PRs da parity sprint do Netz Terminal (#230–#239) fecharam estrutura de componentes mas preservaram a **paleta errada**: `--terminal-bg-void: #000000` e `--terminal-accent-amber: #ffb020` estão em 3191 refs. O UX bundle em `docs/ux/Netz Terminal/` pede `#05081A` (navy deep) + `#FF965A` (orange), IBM Plex Sans/Mono e densidade Bloomberg que o visual atual não entrega.

Existem 2 catálogos de tokens hoje:
- `packages/investintell-ui/src/lib/styles/tokens.css` — `--ii-*` (278 linhas, `(app)` institucional)
- `packages/investintell-ui/src/lib/styles/terminal.css` — `--terminal-*` (225 linhas, superfície terminal)

O bundle traz 4 arquivos CSS (`netz-tokens.css`, `terminal.css`, `builder.css`, `screener.css`, `macro.css`) que representam a paleta + camadas de superfície corretas, mas usam `--netz-*`/`--term-*` com Google Fonts CDN e deltas (sem dataviz 1..8, status só 3-color, severity 3-tier).

**Decisões confirmadas**:
1. `--terminal-*` permanece como fachada — consumers não mudam; valores passam a resolver via `var(--ii-*)`.
2. Fontes via `@fontsource` npm (ibm-plex-sans + ibm-plex-mono + montserrat).
3. Escopo: core token swap + fonts + replicar as 4 CSSs de superfície sob `styles/surfaces/`. Urbanist cleanup nas 91 .svelte e migração `@netz/*`→`@investintell/*` ficam fora.
4. Branch staging longo; merge único em main após visual pass nas 4 páginas contra prints do bundle.

---

## Sub-PRs

### PR-T1 — ii-tokens base + fonts
**Branch**: `feat/ii-tokens-t1-base` → merge em `feat/ii-tokens-adoption`

Arquivos:
- `packages/investintell-ui/src/lib/styles/tokens.css` → **reescrever** a partir de `docs/ux/Netz Terminal/assets/netz-tokens.css`, renomeando prefixos:
  - `--netz-*` → `--ii-*` (navy/orange/sky/steel/indigo/cyan + neutrals)
  - `--color-*` → `--ii-color-*` (semantic layer)
  - `--font-*` → `--ii-font-*`
  - `--fs-*` → `--ii-fs-*`, `--fw-*` → `--ii-fw-*`, `--lh-*` → `--ii-lh-*`, `--tracking-*` → `--ii-tracking-*`
  - `--space-*` → `--ii-space-*`, `--radius-*` → `--ii-radius-*`, `--shadow-*` → `--ii-shadow-*`
  - `--ease-*` → `--ii-ease-*`, `--dur-*` → `--ii-dur-*`
  - Utility classes do bundle (`.netz-hero`, `.netz-display`, `h1-4`, `.body`, `.caption`, `.bg-navy`, `.bg-sky`) — NÃO portar para `tokens.css`; vão para `globals.css` se necessário.
- **Estender** com camadas faltantes (reutilizar valores do atual `terminal.css` para zero drift de status/dataviz):
  - `--ii-navy-deep: #05081A` (bundle terminal bg-void; adicionar ao brand core)
  - Status: `--ii-status-success: #3DD39A`, `--ii-status-warn: #F2C94C`, `--ii-status-error: #FF5C7A`, `--ii-status-critical: #FF5C7A`, `--ii-status-info: #6689BC`, `--ii-status-neutral: var(--ii-stone)`
  - Severity: `--ii-sev-tail: #FF5C7A`, `--ii-sev-mod: #F2C94C`, `--ii-sev-high: #FF965A`, `--ii-sev-upside: #3DD39A`
  - Dataviz ordinal 1..8 (reusar valores de `terminal.css` atuais: amber, cyan, violet, success-green, terracotta, bone-white, cobalt, ash-grey — remapeados para paleta warm do bundle onde faz sentido)
  - `--ii-font-mono: "IBM Plex Mono", "JetBrains Mono", "Menlo", monospace`
  - Density scale para terminal: `--ii-density-row-compact: 22px`, `--ii-density-row-normal: 28px`, `--ii-density-row-relaxed: 36px`
  - Text scale terminal-specific: `--ii-text-10: 10px`, `--ii-text-11: 11px`, `--ii-text-12: 12px`, `--ii-text-14: 14px`
- `packages/investintell-ui/src/lib/styles/typography.css`:
  - Remover `@fontsource-variable/urbanist` + `@fontsource-variable/geist-mono` imports
  - Adicionar `@fontsource-variable/ibm-plex-sans`, `@fontsource-variable/ibm-plex-mono`, `@fontsource/montserrat`
  - `font-family` chain: `"IBM Plex Sans Variable"` → `"IBM Plex Sans"` → system-ui; mono: `"IBM Plex Mono Variable"` → `"IBM Plex Mono"` → Menlo
  - Manter override `[data-surface="terminal"]` usando `var(--ii-font-mono)`
- `packages/investintell-ui/package.json`:
  - `dependencies`: swap `@fontsource-variable/urbanist` + `@fontsource-variable/geist-mono` por `@fontsource-variable/ibm-plex-sans` + `@fontsource-variable/ibm-plex-mono` + `@fontsource/montserrat`
- `packages/investintell-ui/src/lib/styles/globals.css`:
  - Garantir que importa tokens.css + typography.css atualizados
- **Preservar intactos**: `spacing.css`, `shadows.css`, `animations.css` (bundle cobre parcialmente — não duplicar agora)
- **Preservar intactos**: `terminal.css` do repo (rewire acontece em PR-T2)

Verificação PR-T1:
- `pnpm -F @investintell/ui build` passa
- Nenhum consumer de `--terminal-*` quebra (eles ainda apontam para os hex literals atuais)
- `node scripts/check-terminal-tokens-sync.mjs` segue verde (sem mudança em terminal.css/terminal-options.ts)
- Páginas `(app)` que consomem `--ii-*` renderizam com nova paleta bundle

---

### PR-T2 — terminal.css rewire (fachada → ii-*)
**Branch**: `feat/ii-tokens-t2-rewire-terminal` → merge em staging

Arquivos:
- `packages/investintell-ui/src/lib/styles/terminal.css`: **reescrever valores**, preservando **todos os nomes** `--terminal-*`. Cada token literal hex resolve via `var(--ii-*)`:
  - `--terminal-bg-void: var(--ii-navy-deep)` (era `#000000`)
  - `--terminal-bg-panel: var(--ii-navy)` (era `#050505`)
  - `--terminal-bg-panel-raised: var(--ii-navy-2)` (era `#0a0a0a`)
  - `--terminal-fg-primary: var(--ii-offwhite)` (era `#f5f5f0`)
  - `--terminal-fg-secondary: var(--ii-sky-3)`, `--terminal-fg-tertiary: var(--ii-steel)`, `--terminal-fg-muted: var(--ii-silver)`
  - `--terminal-accent-amber: var(--ii-orange)` (era `#ffb020`)
  - `--terminal-accent-amber-dim: var(--ii-orange-soft)`
  - `--terminal-accent-cyan: var(--ii-cyan)`, `--terminal-accent-violet: #A080FF` (bundle não tem violet; manter literal por ora)
  - `--terminal-status-success: var(--ii-status-success)`, `-warn: var(--ii-status-warn)`, `-error: var(--ii-status-error)`
  - `--terminal-dataviz-1..8: var(--ii-dataviz-1..8)`
  - `--terminal-space-*: var(--ii-space-*)` (mapear 4/8/12/16/24/32/48 → ii escala)
  - `--terminal-radius-*: var(--ii-radius-*)`
  - `--terminal-font-mono: var(--ii-font-mono)`, `--terminal-font-sans: var(--ii-font-sans)`
  - `--terminal-text-10..14: var(--ii-text-10..14)`
- `packages/investintell-ui/src/lib/charts/terminal-options.ts`: `DEFAULT_TOKENS` permanece idêntico (SSR fallback é agnóstico de qual layer resolve). Mas os hex literals de fallback devem ser atualizados para a nova paleta (`bgVoid: "#05081A"` em vez de `#000000`; `accentAmber: "#FF965A"` etc.) para evitar FOUC entre SSR e CSS hydration.
- `scripts/check-terminal-tokens-sync.mjs`: **nova Invariant E** — todo `var(--ii-*)` referenciado em `terminal.css` deve existir em `tokens.css`.

Verificação PR-T2:
- Scanner verde com Invariant E nova
- Visual: todas as páginas terminal (live, allocation, screener, macro, builder) renderizam com navy/orange do bundle em vez de black/amber — **comparar contra os 10 prints do bundle**
- SSR: primeira pintura do terminal não mostra o preto antigo (no-FOUC)

---

### PR-T3 — Surfaces (builder / screener / macro)
**Branch**: `feat/ii-tokens-t3-surfaces` → merge em staging

Arquivos:
- **Nova pasta**: `packages/investintell-ui/src/lib/styles/surfaces/`
- `surfaces/builder.css` — portar `docs/ux/Netz Terminal/builder.css`:
  - Classes `.bd-shell`, `.bd-breadcrumb`, `.bd-left`, `.bd-zone-*`, `.bd-tabs`, `.bd-cascade`, `.bd-phase*`, `.bd-kpis`, `.weights-table`, `.factor-row`, `.risk-*`, `.stress-*`, `.mc-metrics`, `.advisor-card*` → manter nomes; trocar `--term-*`/`--netz-*` por `var(--terminal-*)` (façade).
  - Stress severity classes (`.tail`, `.mod`, `.upside`) resolvem via `var(--ii-sev-*)` através do terminal façade.
- `surfaces/screener.css` — portar `docs/ux/Netz Terminal/screener.css`:
  - Classes `.scr-shell`, `.scr-filters*`, `.chip*`, `.scr-table*`, `.elite-badge`, `.universe-badge*`, `.fund-focus*`, `.fund-hero`, `.kpi-grid`, `.perf-chart`, `.radar-wrap`, `.dd-chapters`, `.peer-bar-row`.
  - Score pills `.score/.warn/.alert` → via `var(--terminal-status-*)`.
- `surfaces/macro.css` — portar `docs/ux/Netz Terminal/macro.css`:
  - Classes `.macro-shell`, `.macro-toolbar*`, `.macro-grid`, `.regime-panel*`, `.liq-gauge*`, `.sent-grid`, `.sent-tile*`, `.econ-list`, `.cb-list`, `.news-feed`, `.drawer*`.
  - Sentiment `.esur.hot/.esur.cool` → via status tokens.
  - CB calendar `.cb-chg.cut/hold/hike` → via status tokens.
- `surfaces/index.css` — barrel que importa os 3 acima; consumer importa uma linha só.
- `packages/investintell-ui/package.json` exports:
  - Adicionar `"./styles/surfaces/builder"`, `"./styles/surfaces/screener"`, `"./styles/surfaces/macro"`
- `frontends/wealth/src/routes/(terminal)/allocation/+layout.svelte` (ou nível onde faz sentido): `import "@investintell/ui/styles/surfaces/builder";`
- `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte`: `import "@investintell/ui/styles/surfaces/screener";`
- `frontends/wealth/src/routes/(terminal)/macro/+page.svelte`: `import "@investintell/ui/styles/surfaces/macro";`

**Blocking issues do bundle a resolver durante o port**:
- `url('assets/netz-pattern.svg')` em terminal.css do bundle → copiar o SVG para `packages/investintell-ui/src/lib/styles/assets/` ou inlinar como data URI.
- Google Fonts `@import` em netz-tokens.css + terminal.css do bundle → **remover completamente**; fontes já vêm de PR-T1 via @fontsource.
- `@font-face` aliases Charter→Source Serif 4 e Arboria→DM Sans → **não portar** (eram para slide deck, não app).

Verificação PR-T3:
- Páginas /allocation/*, /terminal-screener, /macro renderizam densidade bundle (rows 22px compact, grid layouts, pill chips, filter rail)
- Nenhuma classe bundle conflita com classes existentes do @investintell/ui (checar colisão `.chip`, `.pill`, `.panel`, `.drawer`)
- Scanner Invariant D ainda verde (nenhum hex literal novo em .svelte, nenhum localStorage/EventSource/emoji)

---

### PR-T4 — Visual pass + merge para main
**Branch**: `feat/ii-tokens-adoption` → PR para main

Conteúdo:
- Zero código novo. É apenas a PR que consolida T1+T2+T3 em main.
- Descrição contém screenshots lado a lado: implementação atual × bundle reference × nova implementação, para cada uma das 4 páginas (live/allocation/screener/macro — live já é navy; allocation com cascade+donut; screener com filter rail + table; macro com 3-col rail + regime matrix).
- CI: `check-frontends` pré-existente red OK conforme `feedback_dev_first_ci_later.md`; `check-terminal-tokens-sync` DEVE estar verde; `test-backend` skipped (nenhuma mudança backend).

Verificação PR-T4:
- Visual parity dos 10 prints do bundle
- `pnpm -F netz-wealth-os build` passa
- Scanner verde nas 4 invariants (A/B/C/D) + nova E
- Zero regressão em `(app)` — surfaces institucionais seguem renderizando via `--ii-*` direto (que agora têm a paleta corporativa correta do bundle)

---

## Arquivos críticos (paths absolutos)

Modificar:
- `packages/investintell-ui/src/lib/styles/tokens.css` (PR-T1 — reescrita)
- `packages/investintell-ui/src/lib/styles/typography.css` (PR-T1 — font swap)
- `packages/investintell-ui/src/lib/styles/globals.css` (PR-T1 — imports)
- `packages/investintell-ui/src/lib/styles/terminal.css` (PR-T2 — façade rewire)
- `packages/investintell-ui/src/lib/charts/terminal-options.ts` (PR-T2 — DEFAULT_TOKENS fallback hex)
- `packages/investintell-ui/package.json` (PR-T1 — deps; PR-T3 — exports)
- `scripts/check-terminal-tokens-sync.mjs` (PR-T2 — Invariant E)

Criar:
- `packages/investintell-ui/src/lib/styles/surfaces/builder.css` (PR-T3)
- `packages/investintell-ui/src/lib/styles/surfaces/screener.css` (PR-T3)
- `packages/investintell-ui/src/lib/styles/surfaces/macro.css` (PR-T3)
- `packages/investintell-ui/src/lib/styles/surfaces/index.css` (PR-T3)
- `packages/investintell-ui/src/lib/styles/assets/netz-pattern.svg` (PR-T3 — copiar do bundle se usado)

Tocar (um import cada):
- `frontends/wealth/src/routes/(terminal)/allocation/[profile]/+page.svelte` (PR-T3)
- `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte` (PR-T3)
- `frontends/wealth/src/routes/(terminal)/macro/+page.svelte` (PR-T3)

Fonte de verdade (read-only):
- `docs/ux/Netz Terminal/assets/netz-tokens.css`
- `docs/ux/Netz Terminal/terminal.css`
- `docs/ux/Netz Terminal/builder.css`
- `docs/ux/Netz Terminal/screener.css`
- `docs/ux/Netz Terminal/macro.css`

Não modificar:
- `packages/investintell-ui/src/lib/styles/spacing.css` (utility, bundle cobre parcialmente — deixa pra depois)
- `packages/investintell-ui/src/lib/styles/shadows.css` (mesmo)
- `packages/investintell-ui/src/lib/styles/animations.css` (mesmo)
- Qualquer `.svelte` com `font-family: 'Urbanist'` literal (out of scope — fallback cascade vai resolver)
- Arquivos com import `from "@netz/..."` (out of scope — migração separada)

---

## Funções e utilitários a reusar

- `readVar(style, name, fallback)` em `packages/investintell-ui/src/lib/charts/terminal-options.ts` — já resolve `--terminal-*` com fallback hex; continua válido pós-rewire (CSS var resolution é transparente a múltiplos níveis de `var()` indirection).
- `createTerminalChartOptions(...)` e `createTerminalLightweightChartOptions(...)` — idem, não precisam mudar.
- `injectBranding(config)` em `packages/investintell-ui/src/lib/utils/branding.ts` — já injeta tokens por tenant; substituição é paleta default, não mecanismo de branding.
- Scanner `scripts/check-terminal-tokens-sync.mjs` — extender com Invariant E, reusar parser existente de CSS custom-property declarations e readVar references.

---

## Verificação end-to-end

Após PR-T4 em main, executar sequencialmente:

```bash
# 1. Integridade do catálogo de tokens
node scripts/check-terminal-tokens-sync.mjs
# Esperado: OK — X CSS tokens, Y readVar references, Z DEFAULT_TOKENS keys in sync; Invariant E green

# 2. Build + type-check
pnpm -F @investintell/ui build
pnpm -F netz-wealth-os build
pnpm -F netz-wealth-os check

# 3. Dev server + smoke visual
pnpm -F netz-wealth-os dev
# Abrir manualmente:
# http://localhost:5174/live          → compara contra prints/live-bundle.png
# http://localhost:5174/allocation/moderate → compara contra allocation-bundle.png
# http://localhost:5174/terminal-screener    → compara contra screener-bundle.png
# http://localhost:5174/macro                → compara contra macro-bundle.png

# 4. Regressão em (app)
# http://localhost:5174/research, /portfolio, etc. (surfaces que usam --ii-* direto)
# Headings em IBM Plex Sans (não Urbanist); paleta navy/orange do bundle
```

Gates visuais (manual, operador):
- Background: navy deep, não preto
- Accent primário: laranja quente `#FF965A`, não amarelo âmbar
- Tipografia interface: IBM Plex Sans (serifas leves, proporcional), não Urbanist (grotesque round)
- Tipografia data: IBM Plex Mono (tabular-nums, ligatures off), não Geist Mono
- Densidade: rows 22px em tables, gutters 24px, gaps 16px
- Filter rail / chip groups / score pills renderizam com classes bundle (dentro das surfaces CSS)

Gates automatizados:
- `check-terminal-tokens-sync.mjs` — exit 0, todas as 5 invariants (A/B/C/D/E)
- `pnpm -F netz-wealth-os build` — exit 0
- CI `check-frontends` — pré-existente red aceitável; `test-backend` SKIPPED

---

## Out of scope (flags explícitas para Opus)

- Remover `font-family: 'Urbanist'` literal nas 91 .svelte (fallback cascade vai resolver via typography.css; cleanup físico fica para PR separado)
- Migrar 67 imports `from "@netz/..."` para `@investintell/...` (independente desta sprint)
- Dataviz palette remapeada para paleta warm do bundle (reusar valores atuais de terminal.css; tunning visual em PR separado)
- Dark mode vs light mode semântico — bundle netz-tokens.css é light-mode corporate; terminal é dark-mode. Continuamos com `[data-surface="terminal"]` como scope override para dark; `(app)` institucional continua light. Não consolidar no mesmo arquivo.
- Classes utility do bundle (`.netz-hero`, `.netz-display`, etc.) — fora de escopo; institucional já tem sua própria escala tipográfica em typography.css
