# Wealth Library — Design Spec

**Date:** 2026-04-08
**Status:** Draft for approval — three specialist agents consulted, awaiting Andrei's sign-off on §3.2 (SVAR vs build-own) and §9.8 decisions
**Owner:** Andrei (Netz)
**Supersedes:** PR-UX-07 "IC Memos Route" (branch `feat/wealth-ic-memos-route`, commit `18df148`) — **obsoleted, not to be merged**
**Branch (to create):** `feat/wealth-library`
**Base:** `main` (post merge of `feat/wealth-portfolio-flex-columns`, commit `74828b3`)
**Specialist agents consulted (2026-04-08):**
  - `wealth-ux-flow-architect` — institutional flow + folder taxonomy + permissions
  - `svelte5-frontend-consistency` — SVAR Filemanager technical audit + build-own fallback
  - `financial-timeseries-db-architect` — data layer, indexes, RLS, API, worker locks

---

## §0 — Princípio Fundador

> **A Library é a memória institucional transversal do Wealth OS.** Não
> é uma fase do pipeline top-down — é o sedimento que sobra de cada fase,
> organizado para ser consultado de volta. Se o Screener é o verbo
> *screen*, a Library é o substantivo *archive*. O PM nunca vai à
> Library para descobrir um fundo novo — vai para **recuperar** o
> raciocínio analítico que o engine já produziu.

Essa frase é a navalha de Occam do sprint. Cada decisão — taxonomia de
pastas, disable de delete, escolha de componente de UI, schema de índice
— passa por essa frase. Se algo viola o "read-only institucional com
auditoria perfeita", sai do escopo.

---

## §1 — Contexto e decisão estratégica

### 1.1 — Inconsistência identificada no screenshot de 2026-04-08

O layout atual de `/screener/+layout.svelte` tem três pills:
**Screening | Analytics | DD Reviews**. A terceira pill renderiza um
DD Report v5 de 8 capítulos (Executive Summary / Investment Strategy /
Fund Manager Assessment / Performance Analysis / Risk Management
Framework / Fee Analysis / Operational Due Diligence / Recommendation)
com breadcrumbs `DD Reports > {uuid} > v5` **dentro** do contexto do
Screener.

Isso mistura duas atividades institucionais distintas:

- **Screener** = ato de **triagem**, verbo ativo de descoberta/análise
- **DD Report** = **output oficial do comitê**, documento assinado, read-only, auditável

Um DD Report v5 aprovado é documento oficial — não é um subproduto de
screening. A pill `DD Reviews` dentro do Screener é dívida arquitetural
acumulada desde quando havia só screening + um primeiro draft de DD.

### 1.2 — Decisão do Andrei (2026-04-08)

1. **Renomear a superfície prevista** na Onda 1 de `IC Memos` → **`Library`**.
2. **Consolidar TODOS os outputs do engine** numa única surface: Investment Outlooks, Flash Reports, Manager Spotlights, DD Reports (8 capítulos), Macro Committee Reviews, Fact Sheets gerados, futuros Committee Packs.
3. **Organizar por pastas temáticas** para dar a "impressão de organização impecável". É a **vitrine do projeto** — materialização visível de toda a memória analítica institucional.
4. **Base do UI:** a sugestão inicial foi [SVAR Filemanager](https://svar.dev/svelte/filemanager/). A avaliação técnica do agent Svelte 5 (§3.2 abaixo) apontou bloqueadores potenciais e recomendou fortemente **build próprio** como default. **Decisão final fica com o Andrei após checklist do §9.8.**

### 1.3 — A PR-UX-07 IC Memos entregue anteriormente fica obsoleta

O branch `feat/wealth-ic-memos-route` (commit `18df148`) foi entregue
mas não mergeado porque o Andrei expandiu o escopo antes da aprovação.
Esse branch permanece como referência histórica e será **descartado na
limpeza pré-merge do Library**. Não há código a recuperar — o IC Memos
era uma versão limitada do que a Library vai ser.

### 1.4 — O que a Library NÃO é

Para evitar scope creep e garantir foco:

- **NÃO é editor** — zero create/delete/rename/move/upload
- **NÃO é substituta do Dataroom** — Dataroom recebe uploads externos; Library mostra outputs internos
- **NÃO é substituta do Dashboard** — Dashboard é situational awareness em tempo real; Library é consulta de memória
- **NÃO é substituta do Screener** — Screener é triagem ativa; Library é recuperação passiva
- **NÃO cria dados novos** — só agrega, indexa, apresenta

---

## §2 — Fluxo institucional (UX)

Seção baseada na entrega do `wealth-ux-flow-architect`.

### 2.1 — Posicionamento no mental model do PM

Momentos-chave em que o PM abre a Library (e não outras surfaces):

1. **8h30 — café da manhã institucional.** Primeira coisa depois do Dashboard. "O que foi publicado ontem? O que o comitê aprovou? Tem flash report novo?"
2. **Preparação da reunião do comitê** (quinta-feira). Pacote de materiais: Outlook do trimestre + 3 Spotlights + últimos DD Reports v5 + Fact Sheet.
3. **Resposta reativa a alerta.** Drift alert no Portfolio surface → botão "View analytical history" → pasta do fundo com todos os DDs, Spotlights, Fact Sheets.
4. **Auditoria / compliance.** "Mostra tudo aprovado em Q3 2026 relacionado ao Moderate portfolio" → 30 segundos.
5. **Handover entre PMs.** Onboarding do novo analista: pasta do fundo é o tour.

### 2.2 — Taxonomia primária de pastas (tree do filemanager)

Decisão híbrida: **Fase do Ciclo no primeiro nível, Entidade no segundo**.

```
Library/
├── 1. Macro & Outlook/
│   ├── Weekly Macro Reviews/
│   │   └── 2026-W14 — Global Macro Review
│   ├── Quarterly Outlooks/
│   │   └── 2026-Q2 — Investment Outlook
│   └── Flash Reports/
│       └── 2026-04-03 — Rate Shock Flash
│
├── 2. Due Diligence/
│   ├── By Fund/
│   │   └── T. Rowe Price Capital Appreciation/
│   │       ├── DD Report v5 (Current) — 2026-03-20
│   │       ├── DD Report v4 — 2025-11-10
│   │       ├── Manager Spotlight — 2026-02-14
│   │       ├── Fact Sheet — Institutional PT — 2026-03-22
│   │       └── Fact Sheet — Executive EN — 2026-03-22
│   ├── Bond Briefs/
│   └── Manager Spotlights/  (cross-fund, por firma)
│
├── 3. Committee & Decisions/
│   ├── 2026-Q2/
│   │   └── IC Meeting 2026-04-10/
│   │       ├── Agenda Pack
│   │       ├── Approved — T. Rowe Price Cap App DD v5
│   │       └── Conditional — Fidelity LPS DD v3
│   └── 2026-Q1/
│
├── 4. Portfolio Models/
│   ├── Moderate Growth/
│   │   ├── Model Rationale — 2026-03-15
│   │   ├── Rebalance Analysis — 2026-03-30
│   │   └── Stress Scenarios — 2026-03-15
│   └── Conservative Income/
│
└── 5. Drafts & Pending/   ← só visível para authors + ADMIN
    ├── My Drafts/
    └── Pending My Approval/
```

**Justificativa da hierarquia híbrida:**
- Fase do ciclo como L1 mapeia diretamente o mental model top-down
- `Due Diligence > By Fund > {Fund}` resolve o cenário mais crítico: tudo sobre um fundo num só lugar, versioning de DD Reports visualmente óbvio
- `Committee & Decisions` é sagrada institucionalmente — auditor abre aqui primeiro
- `Drafts & Pending` escondida para quem não é autor (não polui visão read-only)

### 2.3 — Taxonomias secundárias (filtros, não trees alternativas)

Vivem como **chips de filtro no topo** da Library — filter bar, não switches de tree. Múltiplos trees confundem.

- **Date range:** Today / This Week / This Month / Q / Year / custom
- **Status:** Approved / Published / Pending Approval / Rejected / Archived
- **Kind:** DD Report / Outlook / Flash / Spotlight / Macro Review / Fact Sheet / Committee Pack
- **Author / Approver:** "documentos assinados por mim", "drafts meus", "aguardando minha aprovação"
- **Decision Anchor** (só DD Reports): Approve / Conditional / Reject
- **Portfolio Model:** mostra só docs linkados a um modelo específico
- **Starred / Pinned:** favoritos do PM
- **Language:** PT / EN

Busca full-text transversal (`?q=`) sempre disponível, independe do tree.

### 2.4 — Migração da rota legada `/screener/dd-reports/*`

**Decisão: Opção A — 308 permanente + remoção da pill DD Reviews do layout do Screener.**

Regras de redirect:

```
/screener/dd-reports                                   → /library (landing)
/screener/dd-reports/[fundId]                          → /library/due-diligence/by-fund/{slug}
/screener/dd-reports/[fundId]/[reportId]               → /library/due-diligence/by-fund/{slug}/v{version}
```

O resolver `fundId → slug` + `reportId → version` vive em endpoint
dedicado `GET /library/redirect-dd-report/{old_fund_id}/{old_report_id}`
(ver §4.8) que responde 308 em <20ms.

**A pill `DD Reviews` sai** do `/screener/+layout.svelte`. Screener
volta a ter duas pills: **Screening | Analytics**. Duas atividades
coerentes (triagem e análise quant), mental model limpo.

**Preservação de deep-links:** todos os URLs antigos em emails de IC,
Slack shares, breadcrumbs do backend, PDFs exportados continuam
funcionando via 308. Sem isso, perda de confiança institucional.

### 2.5 — Estrutura de URL e deep-linking da Library

**Tudo na URL, sem exceção.** Compartilhar URL = compartilhar view
exata (pasta aberta, arquivo selecionado, filtros, busca, preview mode).

```
/library                                              → Landing, tree root
/library/macro-outlook                                → Pasta L1
/library/macro-outlook/weekly                         → Subpasta
/library/due-diligence/by-fund/t-rowe-price-cap-app   → Pasta do fundo
/library/due-diligence/by-fund/t-rowe-price-cap-app/v5 → Arquivo aberto em preview
/library/committee/2026-q2/ic-2026-04-10              → Pack de meeting
```

**Query params (estado ortogonal ao tree):**

- `?q=risk+adjusted` — busca full-text
- `?status=approved&kind=dd_report` — filtros combinados
- `?from=2026-01-01&to=2026-03-31` — range temporal
- `?view=grid|list|tree` — visualização do filemanager
- `?preview=inline|fullscreen` — modo de leitura
- `?starred=1` — só favoritos

Breadcrumbs clicáveis renderizam a hierarquia.

### 2.6 — Cenários de uso hora-a-hora (5 fluxos)

Documentados em detalhe no output do `wealth-ux-flow-architect`. Resumo:

1. **Morning briefing** (8h30) — banner "Updated since your last visit (24h)" com cards clicáveis
2. **Compare DD v4 vs v5** — multi-select + botão "Compare" → view side-by-side
3. **Drift alert → context** — link da Portfolio surface abre pasta do fundo com highlight
4. **Committee pack prep** — multi-select cross-folder + "Create meeting pack" → ZIP download
5. **Auditor query** — filter chips combinados + view List + "Export CSV+ZIP"

### 2.7 — Permissões e visibilidade

| Recurso | ADMIN | INVESTMENT_TEAM | investor |
|---|---|---|---|
| Ver Approved/Published | ✅ | ✅ | ✅ |
| Ver Pending Approval | ✅ | ✅ (se aprovador designado) | ❌ |
| Ver Drafts (próprios) | ✅ | ✅ | ❌ |
| Ver Drafts (de outros) | ✅ | ❌ | ❌ |
| Ver Rejected / Archived | ✅ | ✅ | ❌ |
| Download individual | ✅ | ✅ | ✅ (só Approved/Published) |
| Multi-select bundle download | ✅ | ✅ | ❌ |
| Pin / Star documento | ✅ | ✅ | ✅ |
| Criar Committee Pack | ✅ | ✅ | ❌ |
| Ver audit trail | ✅ | ✅ | ❌ |

Pasta `5. Drafts & Pending` condicional no tree — só ADMIN e
INVESTMENT_TEAM veem. Investor nem vê a folder.

Org scoping é absoluto (RLS `organization_id`). Zero vazamento
cross-tenant.

### 2.8 — Princípios UX não-negociáveis

1. Dark mode exclusivo (paleta Screener: `#141519`, `#85a0bd`, `#cbccd1`, `#ffffff`, `#404249`, `#0177fb`)
2. Urbanist font em todos os componentes
3. Zero jargão quant (sanitization layer do backend §4)
4. Stability Guardrails §3.2 Route Data Contract obrigatório
5. `<svelte:boundary>` + `PanelErrorState` + `PanelEmptyState` em cada painel top-level
6. Formatadores `@investintell/ui` exclusivos — zero `.toFixed`/`.toLocaleString`/`Intl.*`
7. Zero localStorage — estado vive na URL; pins vivem no backend
8. Svelte 5 runes puros — `$state`, `$derived`, `$effect`, `$props`
9. Smart backend, polished frontend — zero campo bruto do DB exposto
10. Deep-linking rigoroso — back/forward do browser funciona
11. Desktop-first (1440px+) — split view 320px tree / fluid content / 520px preview
12. **Preview reaproveita readers EXISTENTES** — DDReport, Content, MacroReview components reutilizados via slot dinâmico. Zero reimplementação
13. Virtualização obrigatória — 5000+ nodes sem lag
14. Transições ~200ms — abrir pasta, selecionar arquivo, trocar preview
15. lint `netz-runtime` no nível error — `no-throw-error-in-load`, `require-load-timeout`, `require-svelte-boundary`, `require-tick-buffer-dispose`, `no-unsafe-derived`

---

## §3 — Frontend Architecture

Seção baseada na entrega do `svelte5-frontend-consistency`.

### 3.1 — Componente base: decisão fundamental

A pergunta: **SVAR Filemanager (comercial) ou build próprio com `@tanstack/svelte-virtual`?**

### 3.2 — SVAR Filemanager — auditoria técnica

O agent identificou **4 bloqueadores potenciais não-confirmados**:

| # | Bloqueador | Risco | Impacto se vermelho |
|---|---|---|---|
| 1 | **Licença** — se GPL-only, inviabiliza produto proprietário | Alto | STOP absoluto |
| 2 | **Svelte 5 runes rewrite** — se ainda em compat mode, smell de manutenção | Médio | Aceitável com ressalva |
| 3 | **Controlled mode** — props bindable para state externo (URL adapter depende disso) | Alto | Adapter wrapper de ~300 linhas, loops anti-padrão |
| 4 | **Preview slot customizável** — injetar readers existentes (DD, Content, Macro) | Alto | Bloqueia reaproveitamento, obriga reimplementação |

Outros riscos secundários:

- Bundle size estimado 80-180KB gz (aceitável se ≤150KB)
- Acessibilidade (área fraca histórica da linhagem DHTMLX/SVAR)
- Custo comercial provável (dual GPL + commercial)
- Compatibilidade com dark mode Urbanist

### 3.3 — Recomendação do agent: **BUILD PRÓPRIO (Plano B)**

O agent foi categórico: *"Dada a centralidade da Library ('vitrine do
projeto', palavras do Andrei), o custo de descobrir um bloqueador 3
sprints depois da integração é alto demais. Recomendo rodar o
checklist §6 em 2-4h ANTES de qualquer instalação — não faz sentido
commitar com SVAR sem os 4 greens."*

Razões para build próprio mesmo se SVAR passar:

1. **Zero risco de licença** — código nosso, proprietário
2. **Svelte 5 runes idiomático** — controlled mode nativo, adapter URL↔state vira boilerplate de ~50 linhas em vez de camada de reconciliação de ~300 linhas
3. **Bundle menor** — ~30-60KB gz vs ~80-180KB
4. **Acessibilidade sob nosso controle** — WCAG AA tree bem documentado
5. **Preview pane via snippet nativo** — sem hack dynamic component
6. **Customização infinita** — "Compare side-by-side inline no tree" é código nosso
7. **Alinhamento com identidade Netz** — Library é vitrine, merece pixel-perfect

### 3.4 — Plano B — build próprio, estrutura e fases

**Estimativa:** 11-16 dias-dev distribuídos em 6 fases.

**Estrutura de arquivos proposta:**

```
frontends/wealth/src/
├── routes/(app)/library/
│   ├── +page.server.ts                   RouteData<LibraryTree>, timeout 8s
│   ├── +page.svelte                      orchestrator puro
│   └── [...path]/+page.svelte            rest param para deep-link
│
├── lib/components/library/
│   ├── LibraryShell.svelte               3-pane layout (tree | content | preview)
│   ├── LibraryTree.svelte                tree virtualizado com @tanstack/svelte-virtual
│   ├── LibraryTreeNode.svelte            row recursiva (group/folder/file)
│   ├── LibraryBreadcrumbs.svelte         navegação hierárquica
│   ├── LibraryFilterBar.svelte           chips de filtro (status/kind/date/author)
│   ├── LibrarySearchInput.svelte         debounced search (300ms)
│   ├── LibraryViewToggle.svelte          Tree / List / Grid
│   ├── LibraryActionBar.svelte           Compare / Bundle / Export (ações custom)
│   ├── LibraryContextMenu.svelte         right-click menu
│   ├── LibraryPreviewPane.svelte         slot dinâmico + dynamic import
│   └── LibraryPinsSection.svelte         Pinned + Starred + Recent na landing
│
├── lib/components/library/readers/
│   ├── DDReportBody.svelte               extraído do atual /screener/dd-reports/[fundId]/[reportId]
│   ├── ContentBody.svelte                extraído do atual /content/[id]
│   └── MacroReviewBody.svelte            extraído do atual /market/reviews/[reviewId]
│
└── lib/state/library/
    ├── url-adapter.svelte.ts             bidirectional URL ↔ library state, guard anti-loop
    ├── tree-loader.svelte.ts             lazy load children on expand (AbortController)
    ├── preview-loader.svelte.ts          single-flight preview fetch
    └── pins-client.svelte.ts             read/write pins API client
```

**Fases:**

| Fase | Escopo | Dias | Milestone |
|---|---|---|---|
| **Fase 1 — Tree virtualizado** | `LibraryTree.svelte` + `LibraryTreeNode.svelte` com `@tanstack/svelte-virtual`. Lazy load per folder expand. Keyboard nav (arrow keys, Enter, Space). Contagens no hover. | 3-5 | Navegar 5000 nodes sem lag |
| **Fase 2 — Seleção + context menu + ícones** | Ctrl/Shift+click multi-select, context menu via `bits-ui` ou custom popover, ícones por kind via `lucide-svelte` map | 2-3 | Right-click funcional |
| **Fase 3 — Breadcrumbs + filter bar + view toggle** | Breadcrumbs derivados de `selectedPath: string[]`, filter chips, Tree/List/Grid via `$state` + conditional rendering | 2 | Chips atualizam URL |
| **Fase 4 — URL adapter bidirecional** | `url-adapter.svelte.ts` com guard anti-loop. Search debounced 300ms, filters imediatos. Back/forward preserva estado. | 2-3 | Copiar URL → colar em outra aba → mesmo estado |
| **Fase 5 — Preview pane + dynamic readers** | `LibraryPreviewPane.svelte` com snippet dinâmico + dynamic import. **Refactor dos 3 readers existentes para componentes standalone** (DDReportBody, ContentBody, MacroReviewBody). Single-flight loader, AbortController. | 1-2 | Click row → preview carrega em <300ms sem race |
| **Fase 6 — Action bar custom + ARIA + shortcuts** | Compare / Bundle / Export, ARIA audit (WCAG AA tree), keyboard shortcuts (Cmd+K busca global, Esc fecha preview), ícones por kind, hover states polidos | 1 | Lighthouse a11y ≥ 90 |

**Total: 11-16 dias.** Caminho crítico: Fase 1 → Fase 5.

### 3.5 — Refactor dos readers existentes (pré-requisito da Fase 5)

Os readers atuais estão acoplados a rotas `+page.svelte`:

- `routes/(app)/screener/dd-reports/[fundId]/[reportId]/+page.svelte` (948 linhas)
- `routes/(app)/content/[id]/+page.svelte` (236 linhas)
- `routes/(app)/market/reviews/[reviewId]/+page.svelte` (~170 linhas)

**Refactor necessário:** extrair o body de cada um para componente
standalone que recebe `{ id }` via props, faz seu próprio fetch
client-side, e renderiza sem `PageHeader`/breadcrumbs (esses vêm do
wrapper da Library).

**Custo:** 3 readers × ~2-4h cada = **~1-2 dias dev**. Pode ser feito
**antes** da integração Library — é refactor puro, valor imediato,
zero acoplamento com SVAR vs build-own.

### 3.6 — Riscos técnicos específicos

| Risco | Mitigação |
|---|---|
| **Race condition no preview pane** (click A → click B enquanto A ainda carrega) | `AbortController` por click + `createMountedGuard()` do runtime toolkit |
| **Memory leak em tree grande** | Virtualização libera nós fora do viewport; `$effect` cleanup em subscriptions |
| **Hydration mismatch SSR vs client** | `+page.server.ts` canoniza URL; client recebe state coerente |
| **Back/forward do browser não respeitado** | URL adapter bidirecional com observer sobre `$page.url.searchParams` |
| **Performance do search full-text** | Index server-side (ver §4.2); client só filtra <100 results já pre-filtrados |
| **Single-flight no preview loader** | AbortController por click, último click wins |

### 3.7 — Checklist de validação do SVAR (se Andrei quiser reconsiderar)

Se o Andrei preferir tentar SVAR antes de committar ao build-own, o
checklist é **obrigatório em 2-4h** antes de `pnpm add`:

1. **Licença** — `cat LICENSE` no repo GitHub. Se GPL-3.0-only → **STOP absoluto**. Se MIT → verde. Se dual GPL+commercial → validar custo.
2. **Svelte 5 rewrite** — CHANGELOG.md com entry explícita "Svelte 5 runes". Ou `pnpm view @svar-ui/filemanager peerDependencies`.
3. **Controlled mode** — docs procurando `selectedIds`, `openFolder`, `activeFile` como props **bindable** (não só events). Se só tem `on:change` + imperative setter → amarelo-vermelho.
4. **Preview slot/snippet customizável** — docs procurando `custom preview`, `preview slot`, `snippet`. Se ausente → **bloqueador**.
5. **Disable actions granular** — whitelist por ação (`actions: ['open','download','pin']`) ou `readonly: true` seletivo.
6. **Bundle size real** — install num sandbox, medir chunk `/library`.
7. **Acessibilidade** — demo oficial com `role="tree"`, `aria-expanded`, keyboard nav.
8. **Precedente em produção com Svelte 5** — GitHub search + Reddit/Discord Svelte.

**Regra de decisão:** 4+ greens nos itens 1-4 → GO com ressalvas. Qualquer vermelho em 1-4 → NO-GO, Plano B.

### 3.8 — **Recomendação do spec: Plano B (build próprio)**

O Andrei pode overridar, mas o default defensável deste spec é:

- **Plano B confirmado como caminho canônico**
- **SVAR relegado a backup condicional** (só se checklist 1-4 passar e houver ganho claro de velocidade)
- **Refactor dos 3 readers** incluído como Fase 0 (pré-requisito, independente da decisão)

---

## §4 — Backend data layer

Seção baseada na entrega do `financial-timeseries-db-architect`.

### 4.1 — Índice unificado: nova tabela `wealth_library_index` via triggers

**Decisão:** Opção C — nova tabela física mantida por triggers AFTER
INSERT/UPDATE/DELETE em cada tabela-fonte.

**Alternativas rejeitadas:**
- **Materialized view + UNION ALL:** refresh custa 2-5s por ciclo, staleness window inaceitável, sem predicate pushdown em filtros
- **Aggregator in-memory no route handler:** 80-150ms por request, cresce linear com novos pipelines, busca full-text impossível

**Schema canônico (`wealth_library_index`):**

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `uuid PRIMARY KEY` | Próprio do índice |
| `organization_id` | `uuid NOT NULL` | RLS scope |
| `source_table` | `text NOT NULL` | `wealth_content` / `dd_reports` / `macro_reviews` discriminator |
| `source_id` | `uuid NOT NULL` | PK na tabela-fonte |
| `kind` | `text NOT NULL` | `investment_outlook` / `flash_report` / `manager_spotlight` / `dd_report` / `bond_brief` / `macro_review` / `committee_pack` |
| `title` | `text NOT NULL` | Computado pelo trigger |
| `subtitle` | `text` | Instrumento, ano-semana macro, etc. |
| `status` | `text NOT NULL` | Espelho do source |
| `language` | `text` | `pt`, `en`, ou `null` |
| `version` | `int` | Default 1, populado para DD Reports |
| `is_current` | `boolean NOT NULL DEFAULT true` | Versionamento DD |
| `entity_kind` | `text` | `instrument` / `region` / `portfolio` / `none` |
| `entity_id` | `uuid` | FK lógico (sem constraint física) |
| `entity_slug` | `text` | Imutável, URL-safe |
| `entity_label` | `text` | Display label |
| `folder_path` | `text[] NOT NULL` | Materializado pelo trigger |
| `author_id` | `text` | `created_by` |
| `approver_id` | `text` | `approved_by` |
| `approved_at` | `timestamptz` | |
| `created_at` | `timestamptz NOT NULL` | |
| `updated_at` | `timestamptz NOT NULL` | |
| `confidence_score` | `numeric(5,2)` | DD only |
| `decision_anchor` | `text` | DD only |
| `storage_path` | `text` | Para R2/local link |
| `search_vector` | `tsvector GENERATED` | Ver §4.2 |
| `metadata` | `jsonb` | Source-specific bag |

**Chave lógica única:** `UNIQUE (source_table, source_id, organization_id)`.

**NÃO é hypertable.** Volume projetado ~120k linhas em 3 anos; padrão
de acesso dominado por equality em `organization_id + kind + status`.
Reavaliar se passar de 10M linhas.

### 4.2 — Full-text search

**Decisão:** `tsvector` generated column + `GIN index` + `pg_trgm` fuzzy + `pgvector` semantic re-rank como Fase 2.

**Text search configuration: `'simple'`** (não `english`/`portuguese`).

Razão: PT e EN convivem na mesma org (committee notes PT, brochures EN,
outlook bilíngue). `english` quebra stemming PT; `simple` dá
comportamento previsível cross-language. Para auditores que pedem
"encontre a frase exata X", `simple` é o que querem.

**Generated column com pesos:**
- Peso A (highest): `title`
- Peso B: `subtitle`, `entity_label`
- Peso C: `kind`, `status`, `language`, primeiros 2KB de `metadata->>'summary'`
- Peso D: `author_id`, `approver_id`

**Content markdown NÃO indexado aqui** — `wealth_vector_chunks` (pgvector)
já cobre RAG semantic. Library indexa metadados.

**Indexes:**
```
CREATE INDEX wli_search_vector_gin ON wealth_library_index USING gin (search_vector);
CREATE INDEX wli_title_trgm      ON wealth_library_index USING gin (title gin_trgm_ops);
CREATE INDEX wli_entity_label_trgm ON wealth_library_index USING gin (entity_label gin_trgm_ops);
```

**Latência target <100ms** — viável com 120k linhas + GIN + predicate pushdown.

**pgvector reuse (Fase 2):** quando o PM digita query natural, backend:
1. Full-text primeiro (determinístico, <20ms) → top-100 candidatos
2. Re-ranking contra embeddings de `wealth_vector_chunks`
3. Retorna top-20

Isso evita pagar embedding cost em toda busca, mantém recall exato, e
reaproveita o índice vetorial existente.

### 4.3 — Folder path materializado (`text[]`)

**Decisão:** `folder_path text[]` materializado pelo trigger. **Rejeita `ltree`.**

Razões:
- `ltree` restringe caracteres (ASCII + underscore), nomes de fundos têm pontos/acentos/parênteses
- `text[]` com `&&`/`@>` + GIN é equivalente funcional
- Operacional: time conhece `text[]`, não conhece `ltree`

**Trigger logic (resumo):**

```
DD report instrument:
  ['Due Diligence', 'By Fund', entity_label, 'v' || version]

DD report bond_brief:
  ['Due Diligence', 'Bond Briefs', entity_label]

Investment Outlook:
  ['Macro & Outlook', 'Investment Outlook', '2026-Q2']

Flash Report:
  ['Macro & Outlook', 'Flash Reports', '2026-04']

Manager Spotlight:
  ['Due Diligence', 'Manager Spotlights', entity_label]

Macro Review:
  ['Macro & Outlook', 'Weekly Macro Reviews', '2026-W14']

Committee Pack (futuro):
  ['Committee & Decisions', '2026-Q2', 'IC Meeting 2026-04-10']

Drafts (status IN ('draft','review','rejected','failed')):
  ['Drafts & Pending', ...original_root]
```

**Reorganização futura é trivial** — folder_path é derivado puro. Se
UX decidir mover pastas, reescreve o trigger + roda
`library_index_rebuild` worker. Zero data migration.

**Indexes:**
```
CREATE INDEX wli_folder_path_gin ON wealth_library_index USING gin (folder_path);
CREATE INDEX wli_folder_root_btree ON wealth_library_index
  ((folder_path[1]), organization_id, created_at DESC);
```

### 4.4 — `wealth_library_pins` — tabela única, 3 pin_types

**Schema:**

| Coluna | Tipo |
|---|---|
| `id` | `uuid PRIMARY KEY` |
| `organization_id` | `uuid NOT NULL` |
| `user_id` | `text NOT NULL` (Clerk subject) |
| `library_index_id` | `uuid NOT NULL REFERENCES wealth_library_index(id) ON DELETE CASCADE` |
| `pin_type` | `text CHECK (pin_type IN ('pinned','starred','recent'))` |
| `created_at` | `timestamptz NOT NULL` |
| `last_accessed_at` | `timestamptz NOT NULL` |
| `position` | `int` (drag-reorder futuro) |

**Constraints:**
```
UNIQUE (organization_id, user_id, library_index_id, pin_type)
INDEX (organization_id, user_id, pin_type, last_accessed_at DESC)
INDEX (last_accessed_at) WHERE pin_type = 'recent'   -- TTL worker
```

**RLS:** `(organization_id, user_id)` — pins são per-user, não
compartilhados.

**Phase 0 audit finding (2026-04-08):** o middleware atual
`backend/app/core/tenancy/middleware.py` só seta
`app.current_organization_id` via `set_config`. **`app.current_user_id`
NÃO é setado em lugar nenhum.** A RLS policy proposta não vai
funcionar sem extensão.

**Fix obrigatório (primeiro commit da Phase 1):** estender
`set_rls_context` para aceitar `user_id` opcional:

```python
async def set_rls_context(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: str | None = None,
) -> None:
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": str(org_id)},
    )
    if user_id:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": user_id},
        )
```

E `get_db_with_rls` passa `actor.actor_id` (confirmar shape do Actor):

```python
await set_rls_context(session, actor.organization_id, user_id=actor.actor_id)
```

No fallback dev (actor sem org_id), setar
`app.current_user_id = 'anonymous'` para evitar policy failures
silenciosos.

**Impacto:** mudança isolada em ~15 linhas, zero regressão para rotas
que não leem `app.current_user_id` (hoje nenhuma lê).

**`recent` é auto-populado server-side** no `GET /library/documents/{id}`
handler via UPSERT. Cliente nunca envia POST explícito — evita confiar
no cliente para reportar atividade e dá audit trail correto.

**TTL worker** (`library_pins_ttl`, lock **900_081**): a cada 6h, corta
`recent` > 20 por user via DELETE com row_number() OVER (PARTITION BY user_id).

### 4.5 — Audit trail

**Decisão:** reusar `audit_events` global (já existente), adicionar
evento `entity_type='library_view'` no handler de detail.

**Phase 0 audit findings (2026-04-08):**

1. **`audit_events` JÁ é hypertable** (migration `0030_audit_event_hypertables.py`):
   - `chunk_time_interval = INTERVAL '1 week'`
   - `compress_segmentby = 'organization_id'`
   - `add_compression_policy` após 1 mês
   - PK composto `(created_at, id)`
   - Index `idx_audit_events_org_entity_created ON (organization_id, entity_type, created_at DESC)`

2. **⚠️ RLS DESABILITADO** em `audit_events` (também na migration `0030`):
   ```
   ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY
   ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY
   ```
   Razão: *"RLS incompatible with TimescaleDB columnstore"*. Padrão
   conhecido do projeto (mesmo caso de `fund_risk_metrics` global).

   **Implicação para Library:** queries contra `audit_events` no
   handler de audit-trail (`GET /library/documents/{id}/audit-trail`
   ou similar) **NÃO podem confiar em RLS automático**. Toda query
   deve explicitar `WHERE organization_id = :org_id` no código de
   aplicação. Isso é responsabilidade do handler, não do DB.

3. **⚠️ Sem retention policy de 7 anos** — a migration só configura
   compression. Audit events ficam indefinidos (comprimidos após 1
   mês). Para compliance institucional, **adicionar migration
   não-bloqueante em paralelo ao Library**:
   ```sql
   SELECT add_retention_policy('audit_events', INTERVAL '7 years',
                                if_not_exists => true);
   ```
   Fica fora do caminho crítico da Library — pode ser uma PR
   separada curta feita pelo time a qualquer momento.

Schema do evento:
```json
{
  "entity_type": "library_view",
  "entity_id": "<library_index_id>",
  "action": "view",
  "metadata": {
    "source_table": "dd_reports",
    "source_id": "...",
    "kind": "dd_report",
    "version": 5,
    "user_agent": "...",
    "ip_address": "...",
    "session_id": "..."
  }
}
```

**NÃO auditar listing/tree calls** — volume explode sem ganho compliance.
O auditor pergunta "quem viu o relatório", não "quem listou a pasta".

**Retention:** 7 anos (padrão institucional). `audit_events` deve ser
hypertable com `chunk_time_interval = '1 month'`, compression a partir
de 90 dias, retention policy 7 anos. **Confirmar se já é hypertable;
senão, migration separada (não bloqueante).**

### 4.6 — Slug strategy para redirect legacy

**Decisão:** coluna `slug text` em `instruments_universe` (global) e
`instruments_org` (tenant), gerada por trigger BEFORE INSERT.
**Imutável após criação** — mesmo se o nome do fundo mudar.

Razões:
- URLs em emails IC, PDFs exportados, audit logs ficam órfãs se slug muda
- Mudança de nome do fundo é raríssima (cosmética)
- Rastreabilidade > aparência

**Implementação:**
- Trigger BEFORE INSERT only — slugify via PL/pgSQL pure (`lower`, accent strip, ASCII fold)
- Trigger BEFORE UPDATE OF name **não toca no slug** — emite NOTICE
- Colisão: suffix `-2`, `-3`, ...

**Resolver endpoint** `GET /library/redirect-dd-report/{old_fund_id}/{old_report_id}`:
```sql
SELECT i.slug, dr.version
FROM dd_reports dr
JOIN instruments_universe i ON i.id = dr.instrument_id
WHERE dr.id = $1 AND dr.instrument_id = $2
  AND dr.organization_id = (SELECT current_setting('app.current_organization_id')::uuid);
```
Target latency: <20ms.

**Edge case — report arquivado:** resolver retorna 308 para
`/library?q={fund_name}` com flash message.

### 4.7 — TimescaleDB decisions

| Tabela | Hypertable? | Justificativa |
|---|---|---|
| `wealth_library_index` | ❌ NÃO | Volume ~120k linhas, padrão equality, sem range por tempo |
| `wealth_library_pins` | ❌ NÃO | Volume ~125k, acesso por user não por tempo |
| `audit_events` | ✅ SIM | Range por tempo, retention 7y, compression 90d |

Worker locks reservados (ADICIONAR ao `CLAUDE.md` Data Ingestion Workers table):
- **900_080** — `library_index_rebuild` (nightly self-heal, EXCEPT/MINUS source vs index)
- **900_081** — `library_pins_ttl` (6h, corta recent > 20)
- **900_082** — `library_bundle_builder` (on-demand, async ZIP + manifest + R2 upload + SSE emit)

### 4.8 — API endpoints

| Endpoint | Response | RLS | Cache | Notas |
|---|---|---|---|---|
| `GET /library/tree` | `LibraryTree` (nested, até 2 níveis) | `org_id` | ETag + `max-age=30` | Lazy: cliente expande por demanda |
| `GET /library/folders/{path:path}/children` | `LibraryNodePage` (cursor paginated, 50/page) | `org_id` | ETag por (path, max(updated_at)) | Path serializado URL-encoded |
| `GET /library/search` | `LibrarySearchResult` | `org_id` | — | Query params: `q`, `kind[]`, `status[]`, `from`, `to`, `entity_id`, `language`, `cursor`, `limit` |
| `GET /library/pins` | `LibraryPinsResponse` (3 listas: pinned, starred, recent) | `(org_id, user_id)` | — | Single query + GROUP BY no app |
| `POST /library/pins` | `LibraryPin` | `(org_id, user_id)` | — | Idempotent: UNIQUE violation → 200 com linha existente, NÃO 409 |
| `DELETE /library/pins/{id}` | `204` | `(org_id, user_id)` | — | |
| `GET /library/documents/{id}` | `LibraryDocumentDetail` | `org_id` | ETag + `max-age=60` | Side effect: UPSERT `recent` pin |
| `POST /library/bundle` | `202` + `bundle_id` + SSE channel | `org_id` | — | Dispara `library_bundle_builder` worker |
| `GET /library/bundle/{bundle_id}/download` | `StreamingResponse` ZIP | `org_id` | `no-store` | Audit event antes de servir |
| `GET /library/redirect-dd-report/{old_fund_id}/{old_report_id}` | `308` | `org_id` | — | Resolver slug + version, <20ms |

**Sanitization layer:** todos response models passam por
`backend/app/domains/wealth/schemas/sanitized.py`. Jargão quant (`cvar_95`,
`regime_label`, `dtw_drift_score`) nunca vaza.

**Rate limiting:**
- `/library/search` — 60 req/min/user
- `/library/bundle` — 10 req/hora/user
- Outros — sem limit explícito (Cache-Control absorve)

### 4.9 — Riscos e mitigações de dados

| Risco | Severidade | Mitigação |
|---|---|---|
| Trigger lag em writes pesados (rebuild DD chapter) | Média | Trigger STATEMENT-level com `WHEN (NEW IS DISTINCT FROM OLD)`. Medir em load test. |
| Trigger silencia falha, índice fora de sync | Alta | `library_index_rebuild` worker nightly. EXCEPT/MINUS alerta se delta > 0. Self-healing. |
| GIN bloat em `search_vector` | Média | `fillfactor=70`, autovacuum agressivo, monitor `pg_stat_user_indexes` |
| `wealth_library_pins` cresce sem bound | Baixa | TTL worker (900_081). Pinned/starred bounded por comportamento humano. |
| Pin órfão (document deletado) | Baixa | `ON DELETE CASCADE` em `wealth_library_index(id)` |
| Slug collision | Média | Suffix automático (`-2`, `-3`). Trigger emite WARNING + structlog. |
| Multi-idioma confunde tsvector | Baixa | Mitigado por `simple` config (sem stemming). Trade-off: menos recall verboso, > determinismo. |
| RLS com `current_setting` per-row | **Crítica** | **Subselect pattern sem exceção:** `(SELECT current_setting('app.current_organization_id')::uuid)`. Sem isso, pins cai 1000x. |
| Composite FK ausente em `wealth_library_index` | Média | UNIQUE `(source_table, source_id, org_id)` + rebuild worker safety net |
| Frontend espera `updated_at` mas tabelas-fonte não propagam | Média | Trigger captura `GREATEST(NEW.updated_at, NEW.approved_at, NEW.created_at)` |

---

## §5 — Integração entre as três camadas

### 5.1 — Contrato Data ↔ Frontend

O backend expõe endpoints tipados (§4.8). O frontend consome via route
loaders Svelte 5 com `RouteData<T>` strict.

**Modelos Pydantic propostos (backend):**

- `LibraryNode` — um nó na tree (folder ou file, discriminator)
- `LibraryTree` — árvore hierárquica até 2 níveis
- `LibraryNodePage` — página de children com cursor
- `LibrarySearchResult` — flat list de hits + total count
- `LibraryPin`, `LibraryPinsResponse` — pins agrupados por tipo
- `LibraryDocumentDetail` — metadata + storage_path + reader-specific payload
- `LibraryBundleAck` — 202 + bundle_id + SSE channel

**Tipos TypeScript mirror (frontend):** gerados via `make types`
(OpenAPI → TS) contra backend rodando.

### 5.2 — Contrato Frontend ↔ Svelte runtime toolkit

Library reusa primitivas já existentes em `@investintell/ui/runtime`:

- `RouteData<T>` / `okData` / `errData` — route loaders
- `PanelErrorState`, `PanelEmptyState` — fallbacks
- `createMountedGuard()` — preview loader safety
- `createTickBuffer()` — não aplicável aqui (sem fan-out WS)

### 5.3 — Contrato UX ↔ Backend taxonomy

A taxonomia primária definida em §2.2 DEVE bater exatamente com a
trigger logic em §4.3. Qualquer mudança em qualquer lado requer
sincronização do outro.

**Owner da taxonomia:** o backend — via função SQL do trigger. UI é
dumb e só renderiza `folder_path` como vier.

---

## §6 — Plano de ataque por fases

### 6.1 — Phase 0 — Prerequisites (1-2 dias)

Independente da decisão SVAR vs build-own:

- Extrair `DDReportBody.svelte`, `ContentBody.svelte`, `MacroReviewBody.svelte` standalone dos readers atuais
- Confirmar middleware Clerk faz `SET LOCAL app.current_user_id` (necessário para RLS pins). Se não, adicionar em `tenancy.py`
- Confirmar `audit_events` é hypertable; senão, migration separada
- Reservar lock IDs 900_080, 900_081, 900_082 no `CLAUDE.md`

### 6.2 — Phase 1 — Backend foundations (L, 4-5 dias)

1. Migration: `wealth_library_index` + triggers AFTER INSERT/UPDATE/DELETE em `wealth_content`, `dd_reports`, `macro_reviews`
2. Migration: `wealth_library_pins` + constraints + RLS policy `(org_id, user_id)`
3. Migration: slug column em `instruments_universe` + trigger BEFORE INSERT
4. Backfill script: popular `wealth_library_index` a partir das tabelas existentes
5. Backfill script: gerar slugs retrospectivos para instrumentos existentes
6. `library_index_rebuild` worker (lock 900_080)
7. `library_pins_ttl` worker (lock 900_081)

### 6.3 — Phase 2 — Backend API (M, 3-4 dias)

1. `routes/wealth/library.py` — endpoints tree, folders, search, pins, documents, redirect
2. Response schemas via sanitization layer
3. `library_bundle_builder` worker (lock 900_082)
4. Unit tests 95%+ coverage em todos os endpoints
5. `make types` atualiza TS types no frontend

### 6.4 — Phase 3 — Frontend shell + tree (L, 4-5 dias, **plano B default**)

1. `routes/(app)/library/+page.server.ts` — RouteData loader
2. `routes/(app)/library/+page.svelte` — orchestrator puro
3. `LibraryShell.svelte` — 3-pane layout
4. `LibraryTree.svelte` + `LibraryTreeNode.svelte` — virtualização
5. `LibraryBreadcrumbs.svelte`
6. Lazy load por expand via `tree-loader.svelte.ts`
7. Keyboard nav básico (arrow keys, Enter, Space)
8. Full-bleed NÃO aplicado — Library vive no cage padrão `max-w-screen-2xl`

### 6.5 — Phase 4 — Filters, search, view toggle (M, 3 dias)

1. `LibraryFilterBar.svelte` — chips de filtro
2. `LibrarySearchInput.svelte` — debounced 300ms
3. `LibraryViewToggle.svelte` — Tree / List / Grid
4. `url-adapter.svelte.ts` — bidirectional URL ↔ state, guard anti-loop
5. Sub-pills no shell global: decidir se Library aparece no nav. **Sim** — com ícone `Library` de lucide, entre Portfolio e Market (mesma posição da PR-UX-07 revogada)

### 6.6 — Phase 5 — Preview pane + dynamic readers (M, 2-3 dias)

1. `LibraryPreviewPane.svelte` — slot dinâmico
2. `preview-loader.svelte.ts` — single-flight com AbortController + `createMountedGuard`
3. Dynamic import dos 3 readers refatorados (`DDReportBody`, `ContentBody`, `MacroReviewBody`)
4. Race condition tests (Playwright)
5. Preview fullscreen via `?preview=fullscreen`

### 6.7 — Phase 6 — Actions, pins, bundle (M, 3-4 dias)

1. `LibraryActionBar.svelte` — Compare / Bundle / Export
2. `LibraryContextMenu.svelte` — right-click
3. `LibraryPinsSection.svelte` — landing com Pinned + Starred + Recent
4. `pins-client.svelte.ts` — API client com optimistic updates
5. Committee Pack wizard — multi-select → bundle modal → SSE progress
6. Bundle download endpoint + audit event

### 6.8 — Phase 7 — Redirect + polish (S, 2 dias)

1. Migration: `/screener/dd-reports/*` routes viram redirect handlers
2. `/screener/+layout.svelte` — remove pill `DD Reviews`, volta para 2 pills
3. Delete do `routes/(app)/screener/dd-reports/` folder inteira (movida para Library)
4. Visual regression tests Playwright (screenshot baseline)
5. ARIA audit + keyboard shortcut polish
6. `docs/reference/wealth-library.md` charter doc

### 6.9 — Sizing consolidado

| Phase | Size | Dias-dev |
|---|---|---|
| Phase 0 — Prerequisites | S | 1-2 |
| Phase 1 — Backend foundations | L | 4-5 |
| Phase 2 — Backend API | M | 3-4 |
| Phase 3 — Frontend shell + tree | L | 4-5 |
| Phase 4 — Filters, search, view toggle | M | 3 |
| Phase 5 — Preview pane + dynamic readers | M | 2-3 |
| Phase 6 — Actions, pins, bundle | M | 3-4 |
| Phase 7 — Redirect + polish | S | 2 |
| **TOTAL (plano B build-own)** | | **22-28 dias** |
| **TOTAL (SVAR se passar checklist)** | | **17-22 dias** (economiza ~5) |

---

## §7 — Critérios de aceitação

### Backend
- [ ] B1. `wealth_library_index` + triggers + RLS + backfill funcional
- [ ] B2. `wealth_library_pins` + RLS `(org_id, user_id)`
- [ ] B3. Slug trigger em `instruments_universe` + backfill
- [ ] B4. 3 workers (900_080/081/082) registrados em `CLAUDE.md`
- [ ] B5. 10 endpoints em `routes/wealth/library.py` com RLS + sanitization
- [ ] B6. `ruff check` + `mypy` passam nos arquivos novos
- [ ] B7. Unit tests ≥95% cobertura em endpoints + triggers + workers
- [ ] B8. Latency targets: tree <20ms, search <100ms, redirect <20ms

### Frontend
- [ ] F1. `/library/*` rotas funcionais com `RouteData<T>` strict contract
- [ ] F2. 3 readers refatorados como `*Body.svelte` standalone
- [ ] F3. Tree virtualizado suporta 5000+ nodes sem lag (scroll 60fps)
- [ ] F4. Deep-linking bidireccional 100% funcional — copiar URL → abrir em outra aba → mesmo estado
- [ ] F5. `<svelte:boundary>` + `PanelErrorState` + `PanelEmptyState` em todos os painéis top-level
- [ ] F6. `pnpm --filter netz-wealth-os lint` → 0 problems
- [ ] F7. `pnpm --filter netz-wealth-os check` → 0 errors (excluindo 3 pré-existentes em `portfolio/model/+page.server.ts`)
- [ ] F8. Dark hex literais em todo componente novo — zero `var(--ii-*)` fallbacks
- [ ] F9. Formatter discipline — zero `.toFixed`/`.toLocaleString`/`Intl.*`
- [ ] F10. Lighthouse a11y ≥ 90 na rota `/library`

### Migração
- [ ] M1. `/screener/dd-reports/*` → `/library/due-diligence/*` via 308
- [ ] M2. Pill `DD Reviews` removida do `/screener/+layout.svelte`
- [ ] M3. Zero deep-link quebrado em emails IC / Slack shares / PDFs exportados
- [ ] M4. Visual regression baseline Playwright sem diffs inesperados

### Documentação
- [ ] D1. `docs/reference/wealth-library.md` charter completo
- [ ] D2. Este spec doc com §9 Post-Decision Log atualizado
- [ ] D3. Memória `feedback_library_taxonomy.md` salva (taxonomia canônica)

---

## §8 — Riscos consolidados e rollback

Riscos já listados em §2 (UX), §3 (Frontend), §4 (Backend). Consolidados em ordem de probabilidade × impacto:

| ID | Risco | Prob | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | SVAR bloqueador não-confirmado (licença/Svelte 5/controlled/preview) | Alta | Crítico | **Default para build-own** (§3.3). Checklist §3.7 antes de qualquer install |
| R2 | Trigger silencia falha, índice fora de sync | Média | Alto | Worker 900_080 nightly self-heal |
| R3 | Deep-link legacy quebra (redirect resolver falha) | Média | Alto | Backfill de slugs + fallback `/library?q=...` |
| R4 | RLS sem subselect = 1000× slowdown | Baixa | Crítico | Review code obrigatório de toda policy |
| R5 | Race condition no preview pane | Média | Médio | `AbortController` + `createMountedGuard` |
| R6 | Refactor dos readers introduce bug em rotas existentes | Média | Médio | Phase 0 + smoke tests + visual regression |
| R7 | PM resiste ("já conseguia achar tudo") | Média | Baixo | Onboarding + cenário auditor como killer feature |
| R8 | Virtualização tree não entrega 5000+ | Baixa | Alto | `@tanstack/svelte-virtual` já comprovado em outras features |
| R9 | Slug collision em nomes parecidos | Média | Baixo | Suffix automático + WARNING |
| R10 | Sprint estoura escopo | Alta | Médio | Princípio de corte: parar se Phase estourar >50% do size |

**Rollback:**
- `git revert` granular por phase (cada phase é commit isolado ou merge commit)
- Backend migrations são reversíveis (Alembic downgrade)
- Trigger drop é operação trivial
- Frontend Library route pode ser removida sem afetar rotas legacy (que continuam com redirect ativo)

---

## §9 — Post-Decision Log

| Data | Decisão | Autor | Justificativa |
|---|---|---|---|
| 2026-04-08 | Renomear `IC Memos` → `Library` | Andrei | Escopo mais amplo — consolida TODOS os outputs do engine, não só IC |
| 2026-04-08 | DD Reviews sai do `/screener`, vira pasta da Library | Andrei | Inconsistência arquitetural — DD Report é output oficial, não subproduto de screening |
| 2026-04-08 | Taxonomia primária híbrida (Fase > Entidade) | `wealth-ux-flow-architect` | Mapa do mental model top-down do PM institucional |
| 2026-04-08 | 308 redirect permanente de `/screener/dd-reports/*` | `wealth-ux-flow-architect` | Preserva 100% deep-links (emails IC, Slack shares, PDFs exportados) |
| 2026-04-08 | `wealth_library_index` via triggers (não MV, não aggregator) | `financial-timeseries-db-architect` | Latência + consistência + predicate pushdown |
| 2026-04-08 | `text[]` para folder_path (não `ltree`) | `financial-timeseries-db-architect` | Operacional, sem ganho real, lida com acentos |
| 2026-04-08 | `'simple'` text search config (não english/portuguese) | `financial-timeseries-db-architect` | Multi-idioma PT+EN na mesma org |
| 2026-04-08 | tsvector + trigram + pgvector re-rank Fase 2 | `financial-timeseries-db-architect` | Determinismo > recall em queries exatas; reusa `wealth_vector_chunks` |
| 2026-04-08 | Slug imutável após criação | `financial-timeseries-db-architect` | URLs em emails/PDFs ficam estáveis |
| 2026-04-08 | `'simple'` config text search | `financial-timeseries-db-architect` | Multi-idioma previsível |
| 2026-04-08 | **RECOMMENDED — Plano B build-own** (não SVAR) | `svelte5-frontend-consistency` | 4 bloqueadores não-confirmados no SVAR; Svelte 5 runes idiomático; zero risco de licença |
| 2026-04-08 | Refactor dos 3 readers como Phase 0 pré-requisito | `svelte5-frontend-consistency` | Independente de SVAR vs build-own; valor imediato |

### 9.8 — Aprovações do Andrei (2026-04-08)

Todas as 8 decisões do rascunho inicial foram aprovadas pelo Andrei
em 2026-04-08:

| # | Decisão | Status |
|---|---|---|
| 1 | SVAR vs Build-own | ✅ **Plano B (Build-own) APROVADO.** SVAR REJEITADO completamente. *"A Library é a vitrine do projeto. Depender de um componente de terceiros com licenciamento nebuloso e bloqueadores potenciais não-confirmados no suporte a runes do Svelte 5 é risco inaceitável."* |
| 2 | Taxonomia primária | ✅ APROVADA integralmente. Hierarquia híbrida (Macro & Outlook / Due Diligence / Committee & Decisions / Portfolio Models / Drafts & Pending). *"Ela espelha perfeitamente o mental model de um comitê de investimentos."* |
| 3 | 308 redirect + remoção da pill `DD Reviews` | ✅ APROVADO imediatamente. *"O padrão institucional exige estabilidade de links. Quebrar URLs de relatórios de Due Diligence já enviados por e-mail ou Slack é falha crítica."* |
| 4 | Schema `wealth_library_index` + UNIQUE logic | ✅ APROVADO. *"Consistência transacional + baixa latência + isolamento via organization_id."* |
| 5 | Lock IDs 900_080/081/082 | ✅ AUTORIZADO. Adicionar ao `CLAUDE.md` imediatamente. |
| 6 | Sizing 22-28 dias | ✅ CABE no Q2. *"Preferível gastar 28 dias fazendo um build-own perfeito do que 17 dias lutando contra limitações de lib comercial."* |
| 7 | `audit_events` hypertable | ⚠️ **VERIFICADO Phase 0 — JÁ EXISTE (migration 0030).** 2 achados importantes: RLS desabilitada em `audit_events` (handler precisa filtrar `organization_id` explicitamente); retention 7y não configurada (migration não-bloqueante em paralelo). Ver §4.5. |
| 8 | Clerk `SET LOCAL app.current_user_id` | ⚠️ **VERIFICADO Phase 0 — NÃO EXISTE.** Middleware só seta `app.current_organization_id`. Extensão obrigatória em ~15 linhas como primeiro commit da Phase 1. Ver §4.4. |

### 9.9 — Phase 0 audit report (2026-04-08)

Investigação executada em resposta às ações prioritárias #7 e #8 do
Andrei.

**#7 — `audit_events` já é hypertable (migration `0030_audit_event_hypertables.py`).**

Achados:
- ✅ Hypertable com chunk_time_interval 1 week
- ✅ Compression segmentby organization_id, após 1 mês
- ✅ PK composto `(created_at, id)`
- ✅ Index `idx_audit_events_org_entity_created` cobre RLS-free queries
- ⚠️ **RLS DESABILITADA** (trade-off TimescaleDB columnstore). Implicação: handler de audit-trail da Library deve explicitar `WHERE organization_id = :org_id`.
- ⚠️ **Retention 7y não configurada.** Apenas compression. Adicionar `add_retention_policy` em migration separada, não-bloqueante.

**#8 — Clerk middleware NÃO seta `app.current_user_id`.**

Inspeção em `backend/app/core/tenancy/middleware.py`:
- Função `set_rls_context(session, org_id)` só chama `set_config('app.current_organization_id', ...)` via SELECT
- `get_db_with_rls` só passa `actor.organization_id` — user_id nunca é propagado para o GUC

Fix obrigatório: estender `set_rls_context` para aceitar `user_id: str | None = None` opcional. `get_db_with_rls` passa `actor.actor_id`. ~15 linhas. Primeiro commit da Phase 1.

**Ambos achados documentados nas §4.5 e §4.4 deste spec.**

---

## §10 — Backlog (fora de escopo desta sprint)

1. **Library Activity Dashboard** — continuous aggregate `cagg_library_kind_weekly` alimentando dashboard "docs aprovados por semana por kind". Speculativo, YAGNI, volta quando houver request.
2. **Archive to cold storage** — `wealth_content`/`dd_reports` > 3 anos movem para R2 cold + soft-delete. Fora de escopo.
3. **OCR de Fact Sheets** — Fact Sheets PDF ficam indexados via `storage_path` + thumbnail. Full-text do PDF é trabalho separado.
4. **Collaborative annotations** — PM pode comentar num DD Report; comentário aparece em overlay. Feature pedida por UX mas fora desta sprint.
5. **Export customizado** — PM define template de capa/footer para bundle Committee Pack. Feature futura.
6. **Multi-language toggle** — UI da Library em EN/PT conforme preferência. Depende de i18n completo do Wealth.
7. **Shared collections** — pastas compartilhadas entre múltiplos users do mesmo IC. Requer redesign de RLS.
8. **Library Insights** — "documentos mais vistos este mês", "autores mais ativos", "tempo médio de aprovação". Analytics sobre a Library.
9. **Auto-tagging** — LLM classifica docs novos em tags semânticas além da taxonomia estrutural.
10. **Fase 3 do pgvector re-rank semantic** — implementar o re-ranking em cima do full-text quando houver tempo.

---

## Fim do spec.

Próximo passo após aprovação: Andrei responde as 8 decisões do §9.8.
Com luz verde nelas, abre-se o branch `feat/wealth-library` a partir de
`main` (commit `74828b3` — Portfolio Builder Phase A+B mergeado) e
começa a Phase 0 (prerequisites). Caminho crítico: Phase 0 → Phase 1
→ Phase 2 (backend foundations + API) antes de qualquer linha de
frontend.

**PR-UX-07 IC Memos Route (branch `feat/wealth-ic-memos-route`, commit
`18df148`) permanece como código obsoleto em branch separada, não será
mergeada. Será deletada após aprovação deste spec ou mantida como
referência histórica conforme preferência do Andrei.**
