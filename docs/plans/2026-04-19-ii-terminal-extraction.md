# II Terminal — Extração para Frontend Isolado

**Data**: 2026-04-19
**Dono**: Andrei
**Status**: aguardando dispatch
**Predecessor**: `docs/plans/_deprecated/2026-04-19-ii-tokens-adoption.md` (token swap in-wealth, abandonado pelo pivot)

## Context

A parity sprint #230-#239 fechou estrutura mas o terminal segue alojado em `frontends/wealth/src/routes/(terminal)/`. Dois problemas com isso:

1. **UX errada**: para abrir o terminal o usuário entra no wealth, vai para portfolio/live, navega para dentro do route group. Bloomberg-style workspace não funciona escondido dentro de outro produto.
2. **Acoplamento de produto**: "II Terminal" e "Wealth Client Portal" têm perfis de usuário distintos (analyst/PM vs advisor/investor) e ciclos de release incompatíveis.

**Decisões já batidas**:

1. **URL isolada**: terminal vive em `terminal.investintell.com` com entry-point próprio.
2. **Auth**: Clerk SSO via cookie domain `.investintell.com` — mesmo login entre `wealth.*` e `terminal.*`.
3. **Wealth pós-split**: read-only client-facing advisor portal (NAV reports, compliance views, IC memo delivery, investor statements). Sem Screener/Macro/Allocation/Live/Research.
4. **Estado compartilhado**: backend-owned. Watchlist/alerts/notifications vivem em Postgres, ambas apps leem via API. Sem cross-domain sync no cliente.
5. **Branding**: produto = **InvestIntell** / **II Terminal**. Remover "Netz" de product chrome (breadcrumb, topnav, titles, score labels, logos). "Netz" continua existindo como **tenant** dentro do Clerk, com sua branding injetada runtime via `injectBranding()` — mas não aparece em chrome unauthenticated, em empty state do produto, em nome de score, em logo do app shell.
6. **Visual**: 1:1 com bundle `docs/ux/Netz Terminal/` — não "parity estrutural". Pixel-level review, cor/fonte/densidade exatas.

## Escopo de sprints (7 sub-PRs, cada 1 sessão Opus independente)

### X1 — Scaffold `frontends/terminal/` (SvelteKit empty shell)

**Branch**: `feat/ii-terminal-x1-scaffold` → main

Arquivos novos:
- `frontends/terminal/package.json` — name `"ii-terminal"`, deps: `@sveltejs/kit`, `svelte@^5`, `vite`, `@investintell/ui`, `clerk-sveltekit`, `svelte-clerk`, `@fontsource-variable/ibm-plex-sans`, `@fontsource-variable/ibm-plex-mono`, `@fontsource/montserrat`
- `frontends/terminal/svelte.config.js` — adapter-node
- `frontends/terminal/vite.config.ts` — porta 5175 (wealth=5174, credit=5173)
- `frontends/terminal/tailwind.config.ts` — theme IBM Plex + bundle palette
- `frontends/terminal/src/app.html` — title "II Terminal", meta, font preload
- `frontends/terminal/src/app.css` — importa `@investintell/ui/styles` + tokens do bundle (ii-tokens)
- `frontends/terminal/src/hooks.server.ts` — Clerk JWT verify (reusar `packages/investintell-ui/src/lib/utils/auth.ts`), cookie domain `.investintell.com` (via env `CLERK_COOKIE_DOMAIN`)
- `frontends/terminal/src/hooks.client.ts` — session expiry monitor
- `frontends/terminal/src/routes/+layout.svelte` — shell vazio com placeholder "II Terminal boots here"
- `frontends/terminal/src/routes/+page.svelte` — redirect para `/live` (ou landing)
- `frontends/terminal/railway.toml` — deploy target `terminal.investintell.com`
- `Makefile` — targets `dev-terminal`, `build-terminal`, `check-terminal`
- `turbo.json` — pipeline entries para `ii-terminal#build`, `ii-terminal#dev`, `ii-terminal#check`
- `pnpm-workspace.yaml` — já cobre `frontends/*`, nada a alterar

Backend:
- `backend/app/core/config.py` — adicionar `terminal.investintell.com` em `ALLOWED_ORIGINS`
- `backend/app/main.py` — CORS middleware já reusa a lista

Clerk (manual, operador):
- Configurar **Cookie Domain** no Clerk dashboard para `.investintell.com` (unlocks SSO)
- Adicionar `https://terminal.investintell.com` em Allowed origins e Redirect URLs

**Verificação X1**:
- `make dev-terminal` sobe em `localhost:5175`, renderiza placeholder, Clerk login funciona
- Login no wealth → cookie compartilhado → navegar para `localhost:5175` já autenticado (SSO local via `.localhost` cookie domain em dev)
- Build passa: `pnpm -F ii-terminal build`
- Scanner terminal-tokens continua verde (nada mudou em wealth)

---

### X2 — Move routes `(terminal)/` para `frontends/terminal/src/routes/`

**Branch**: `feat/ii-terminal-x2-route-move` → main

Movimentação:
- `frontends/wealth/src/routes/(terminal)/live/` → `frontends/terminal/src/routes/live/`
- `frontends/wealth/src/routes/(terminal)/portfolio/live/` → `frontends/terminal/src/routes/portfolio/live/`
- `frontends/wealth/src/routes/(terminal)/allocation/` → `frontends/terminal/src/routes/allocation/`
- `frontends/wealth/src/routes/(terminal)/macro/` → `frontends/terminal/src/routes/macro/`
- `frontends/wealth/src/routes/(terminal)/terminal-screener/` → `frontends/terminal/src/routes/screener/` (simplifica nome — namespace do produto já é terminal)
- `frontends/wealth/src/routes/(terminal)/research/` → `frontends/terminal/src/routes/research/`
- `frontends/wealth/src/routes/(terminal)/alerts/` → `frontends/terminal/src/routes/alerts/`
- `frontends/wealth/src/routes/(terminal)/+layout.svelte` → `frontends/terminal/src/routes/+layout.svelte` (merge com placeholder de X1)

Estratégia de imports durante a transição:
- Terminal importa componentes de `frontends/wealth/src/lib/components/**` via **workspace path** em `tsconfig.json`:
  ```json
  "paths": {
    "$wealth-components/*": ["../../wealth/src/lib/components/*"]
  }
  ```
- Isso é temporário — Sprint X5 promove para package. Durante X2, ambas apps rodam com o mesmo código de componente.
- Loaders `+page.server.ts` mantêm a mesma assinatura (reusam `$lib/api/client`).
- Rotas antigas em `frontends/wealth/src/routes/(terminal)/` **continuam vivas** durante X2 — espelham o conteúdo. Wealth e terminal servem os mesmos URLs em domínios diferentes.

**Verificação X2**:
- `localhost:5174/allocation/moderate` (wealth) e `localhost:5175/allocation/moderate` (terminal) renderizam idêntico
- Mesma chamada `/portfolio/profiles/moderate/latest-proposal` em ambos
- Login SSO funciona em ambos
- Nenhum hard-code de domínio em fetch (tudo via `createClientApiClient`)

---

### X3 — Visual migration (ii-tokens + surface CSS do bundle)

**Branch**: `feat/ii-terminal-x3-visual` → main

Reusa a intenção do plano deprecated, mas escopado ao terminal frontend:

- `packages/investintell-ui/src/lib/styles/tokens.css` — estender com `--ii-navy-deep`, status 6-slot, severity 4-tier, dataviz 8-slot, density, text scale (detalhes em `_deprecated/2026-04-19-ii-tokens-adoption.md` §PR-T1)
- `packages/investintell-ui/src/lib/styles/terminal.css` — rewire façade `--terminal-*` → `var(--ii-*)` (bundle paleta)
- `packages/investintell-ui/src/lib/styles/surfaces/` — nova pasta com `terminal.css`, `builder.css`, `screener.css`, `macro.css` portados de `docs/ux/Netz Terminal/*.css` (renomeados, prefixos migrados)
- `packages/investintell-ui/src/lib/styles/typography.css` — swap Urbanist/Geist → IBM Plex Sans/Mono + Montserrat (via @fontsource)
- `packages/investintell-ui/package.json` — swap deps de fontes
- `frontends/terminal/src/app.css` — import `@investintell/ui/styles/surfaces/terminal`
- Terminal routes importam CSS por rota (`allocation/+page.svelte` importa `surfaces/builder`, etc.)
- `scripts/check-terminal-tokens-sync.mjs` — nova Invariant E (ii-tokens sync)

**Acceptance 1:1 com bundle** (não parity — fidelidade):
- Screenshots side-by-side de cada rota × bundle PNG correspondente
- Gates: cor de fundo `#05081A` exato, accent `#FF965A` exato, fonte IBM Plex Sans computada, row-height 22px compact mode
- Ferramenta sugerida: Playwright + pixelmatch para regression automático

**Verificação X3**:
- Todas as 6 rotas do terminal renderizam bundle-like
- Wealth `(terminal)/` ainda existe e ainda usa paleta antiga (não tocada neste PR)
- Scanner verde com Invariant E

---

### X4 — Brand cleanup (remover "Netz" de product chrome)

**Branch**: `feat/ii-terminal-x4-brand` → main

Blast radius mapeado (3 arquivos + assets):
- `frontends/terminal/src/lib/components/.../FundDetailsDrawer.svelte` — "Netz Score" → "II Score" (ou só "Score")
- `frontends/terminal/src/lib/components/.../TerminalRiskKpis.svelte` — "Netz Elite" → "Elite"
- `frontends/terminal/src/lib/components/terminal/shell/TerminalTopNav.svelte` — "NETZ / TERMINAL" → "II / TERMINAL" ou só "TERMINAL"
- `frontends/terminal/src/app.html` — `<title>` e meta
- `frontends/terminal/static/` — logo InvestIntell (substituir qualquer netz-logo.svg)
- Screener ELITE badge — mantém "ELITE" (sem prefixo "Netz")

Copy review manual:
- Empty states ("Carregando dados Netz..." → "Carregando...")
- Error messages
- Loading screens
- Tooltip text
- Aria labels
- Alt text em imagens

Arquivos de assets a auditar:
- `packages/investintell-ui/src/lib/styles/assets/` (se houver netz-pattern.svg do bundle)

**Preservar**: `BrandingConfig` runtime per-tenant em `packages/investintell-ui/src/lib/utils/branding.ts`. Netz como tenant continua injetando sua marca quando o usuário Netz loga. Mas o **default/unauthenticated chrome** é InvestIntell.

**Verificação X4**:
- Grep `-i "netz"` em `frontends/terminal/src/` + `packages/investintell-ui/src/lib/components/terminal/` → zero hits em strings user-visible
- Meta title do terminal = "II Terminal"
- Unauthenticated route (login screen) mostra InvestIntell logo

---

### X5 — Promote componentes para `packages/ii-terminal-core/`

**Branch**: `feat/ii-terminal-x5-promote` → main

Novo package:
- `packages/ii-terminal-core/package.json` — name `"@investintell/ii-terminal-core"`
- `packages/ii-terminal-core/src/lib/` — move:
  - Tudo de `frontends/wealth/src/lib/components/terminal/**` (shell, focus-mode, drawer, tweaks, chart, market-data-store, formatters mono)
  - `frontends/wealth/src/lib/components/allocation/**` (CascadeTimeline, IpsSummaryStrip, RegimeContextStrip, ProposalReviewPanel, ApprovalHistoryTable, OverrideBandsEditor, AllocationDonut, StrategicAllocationTable, ProposeButton)
  - `frontends/wealth/src/lib/components/screener/terminal/**` (FilterChipRow, TerminalScreenerShell, TerminalDataGrid)
- `packages/ii-terminal-core/src/lib/index.ts` — barrel
- `packages/ii-terminal-core/package.json` `exports` — `./components/terminal/*`, `./components/allocation/*`, etc.

Terminal frontend consome via `import { TerminalShell } from "@investintell/ii-terminal-core/components/terminal"`.

Wealth:
- Se wealth NÃO precisar mais desses componentes (read-only portal não tem builder/screener/live), **remove** o import path workspace configurado em X2.
- Se wealth ainda referencia algum (ex: IC memo delivery usa ECharts compartilhado), deixa wealth consumir também via `@investintell/ii-terminal-core` — não diferencia.

`packages/investintell-ui/` fica lean: design system genérico (Button, Dialog, Input, FormField, ChartContainer), tokens globais, layouts genéricos (AppLayout, AppShell, Sidebar, TopNav genéricos — não terminal-specific).

**Verificação X5**:
- `pnpm -F ii-terminal build` passa sem resolver `../../wealth/src/lib/components/*`
- Wealth também compila
- Zero referência entre `frontends/terminal/` e `frontends/wealth/`

---

### X6 — DNS + Railway deploy cutover

**Branch**: `feat/ii-terminal-x6-deploy` → main

Infra:
- Railway: criar serviço novo `ii-terminal` apontando para `frontends/terminal/` (adapter-node build)
- DNS: CNAME `terminal.investintell.com` → Railway target
- Clerk dashboard (operador): verificar que cookie domain `.investintell.com` e allowed origin `https://terminal.investintell.com` estão ativos (preparado em X1, confirmar)
- Backend CORS: confirmar `terminal.investintell.com` em `ALLOWED_ORIGINS` (feito em X1)
- Environment: `.env.production` do terminal com `PUBLIC_API_BASE_URL=https://api.investintell.com`, `PUBLIC_CLERK_PUBLISHABLE_KEY=...`

Testes prod:
- SSO real: logar em `wealth.investintell.com`, navegar para `terminal.investintell.com`, confirmar sessão persistida
- Navegação entre apps: cross-domain = full reload (esperado), mas com cookie SSO é transparente
- Performance: FCP/LCP do terminal em prod

**Verificação X6**:
- Terminal acessível em `terminal.investintell.com` com HTTPS
- SSO funciona
- Todas as 6 rotas carregam dados reais do backend prod
- Zero regressão em `wealth.investintell.com`

---

### X7 — Wealth cleanup (remover rotas migradas)

**Branch**: `feat/ii-terminal-x7-wealth-cleanup` → main

Deleta:
- `frontends/wealth/src/routes/(terminal)/**` inteiro
- Links de navegação no wealth que apontam para rotas do terminal
- `frontends/wealth/src/lib/components/terminal/**` (já promovido em X5)
- `frontends/wealth/src/lib/components/allocation/**` (idem)
- `frontends/wealth/src/lib/components/screener/terminal/**` (idem)

Redirects (opcional, 6 meses transição):
- `frontends/wealth/src/hooks.server.ts` — detecta path `/allocation/*`, `/live`, `/macro`, `/screener/*` → 301 para `terminal.investintell.com/...`

Wealth pós-X7:
- Rotas: `/`, `/dashboard`, `/reports`, `/clients`, `/compliance`, `/admin`
- Sem escrita — read-only portal per decisão batida
- TopNav simplificado: "InvestIntell Wealth — Client Portal"
- Reuses `@investintell/ui` (design system institucional)
- Não importa `@investintell/ii-terminal-core`

**Verificação X7**:
- `wealth.investintell.com/allocation/moderate` → 301 para `terminal.investintell.com/allocation/moderate`
- `pnpm -F netz-wealth-os build` passa com tree menor
- Nenhum link quebrado entre os dois domínios

---

## Arquivos críticos (paths absolutos)

**Criar** (X1):
- `frontends/terminal/` (pasta inteira — scaffold SvelteKit)

**Criar** (X5):
- `packages/ii-terminal-core/` (promoção)

**Mover** (X2):
- `frontends/wealth/src/routes/(terminal)/**` → `frontends/terminal/src/routes/**`

**Mover** (X5):
- `frontends/wealth/src/lib/components/terminal/**` → `packages/ii-terminal-core/src/lib/components/terminal/**`
- `frontends/wealth/src/lib/components/allocation/**` → `packages/ii-terminal-core/src/lib/components/allocation/**`
- `frontends/wealth/src/lib/components/screener/terminal/**` → `packages/ii-terminal-core/src/lib/components/screener/**`

**Modificar** (X3):
- `packages/investintell-ui/src/lib/styles/tokens.css`, `typography.css`, `terminal.css`, `package.json`
- `packages/investintell-ui/src/lib/styles/surfaces/*.css` (novo)
- `scripts/check-terminal-tokens-sync.mjs` (nova Invariant E)

**Modificar** (X4):
- Arquivos com strings "Netz" em product chrome (3 arquivos identificados + varredura manual)

**Modificar** (X6):
- `backend/app/core/config.py` (ALLOWED_ORIGINS — feito em X1)
- `railway.toml` raiz (adicionar serviço terminal)
- DNS (operador, fora do git)

**Deletar** (X7):
- `frontends/wealth/src/routes/(terminal)/**`
- `frontends/wealth/src/lib/components/{terminal,allocation,screener/terminal}/**`

---

## Funções e utilitários a reusar

- `packages/investintell-ui/src/lib/utils/auth.ts` — `createClerkHook`, `startSessionExpiryMonitor` (Clerk JWT handling, funciona entre apps)
- `packages/investintell-ui/src/lib/utils/api-client.ts` — `createClientApiClient`, `createServerApiClient` (zero mudança)
- `packages/investintell-ui/src/lib/utils/sse-client.svelte.ts` — SSE infra funciona em ambas apps
- `packages/investintell-ui/src/lib/utils/branding.ts` — `injectBranding`, per-tenant runtime branding (preservar, não confundir com X4 que é product chrome)
- `packages/investintell-ui/src/lib/charts/terminal-options.ts` — `readVar`, `createTerminalChartOptions`, continua sendo SSR-safe layer
- `scripts/check-terminal-tokens-sync.mjs` — extender com Invariant E

---

## Verificação end-to-end

Após X7:

```bash
# 1. Builds independentes
pnpm -F ii-terminal build
pnpm -F netz-wealth-os build
pnpm -F netz-credit build
pnpm -F @investintell/ui build
pnpm -F @investintell/ii-terminal-core build

# 2. Scanner de tokens
node scripts/check-terminal-tokens-sync.mjs

# 3. Dev servers simultâneos (3 portas)
make dev-terminal  # :5175
make dev-wealth    # :5174
make dev-credit    # :5173

# 4. SSO smoke (local via .localhost cookie domain)
# Logar em localhost:5174 (wealth)
# Abrir localhost:5175 em nova aba → já autenticado

# 5. Prod smoke (após X6)
# https://wealth.investintell.com login
# https://terminal.investintell.com abrir → autenticado via SSO
# Navegar entre rotas
# 6 rotas do terminal carregam dados reais

# 6. Visual parity 1:1 com bundle (X3 acceptance)
# Playwright + pixelmatch para cada rota contra docs/ux/Netz Terminal/prints
```

Gates de bloqueio:
- X3 não fecha sem 1:1 visual (pixel diff < 2% contra bundle PNG)
- X6 não fecha sem SSO funcionando em prod
- X7 não fecha sem redirects testados (ou decisão consciente de hard-break)

---

## Out of scope

- **Credit frontend**: fora. Credit continua em credit.investintell.com como está.
- **Mobile apps**: fora. Terminal é desktop-first (32" monitor target per memory).
- **Refactor do backend**: zero mudança em `backend/app/`. API endpoints idênticos.
- **Dark/light mode para wealth client portal**: X7 mantém wealth como está visualmente. Re-skin do wealth é outra sprint.
- **Migração `@netz/*` → `@investintell/*`** (67 imports deprecated): sprint separada, ortogonal.

---

## Dependências de decisão (manual, operador)

Antes de X1 rodar:
1. Clerk dashboard: configurar cookie domain `.investintell.com` + allowed origins + redirect URLs para `terminal.investintell.com`
2. Decidir nome exato do subdomínio: `terminal.investintell.com` (assumido) ou `ii.investintell.com` ou outro?
3. DNS control: confirmar que GoDaddy ou similar permite CNAME para Railway target

Antes de X6 rodar:
4. Railway: autorizar criação de novo service
5. Backup/rollback strategy caso SSO falhe em prod (rollback = manter wealth (terminal) como ativo, apenas DNS não propaga)
