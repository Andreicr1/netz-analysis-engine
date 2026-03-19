# Principles Audit — Checkpoint 1

Source: `docs/ux/system-ux-principles.md`

---

## 1. Extracted Principles

### P01 — Surface Hierarchy (§10)
The interface must express five distinct surface layers: structural frame, operational workspace, analytical surface, process layer, elevated decision layer. Users must immediately perceive whether content is page background, grouped section, primary panel, inset process block, or elevated decision surface.

### P02 — Border Semantics (§11)
Borders must encode structural containment, interaction readiness, and process emphasis — not serve as generic separators. Four tiers: subtle (layout), default (affordance), strong (emphasis/stateful), focus (interaction only).

### P03 — Typography as Institutional Hierarchy (§12)
Typography must support both scanning and sustained reading across narrative outputs, legal documentation, memo chapters, macro commentary, tables, and approval interfaces. Hierarchy: display → heading → subheading → body → label → caption. Each tier has a distinct operational role.

### P04 — Semantic Spacing (§13)
Spacing must be role-driven, not purely numeric. Semantic roles: section spacing, block spacing, card padding, form gap, inline spacing. Mixed compositions (charts + forms + tables + long-form) must not feel improvised.

### P05 — Depth from Surface+Border+Shadow (§14)
Elevation must emerge from the interaction of surface color, border discipline, and ambient shadow — not shadow alone. Cards, modals, dropdowns each have distinct elevation semantics.

### P06 — Motion as State Communication (§15)
Motion clarifies state progression and responsiveness. Hover/pressed/focus: subtle and fast. Panel entrances: controlled. Loading/generation: reinforces process legitimacy. SSE-fed changes: never jumpy. No animation that adds personality without clarity.

### P07 — Workflow State Visibility (§16)
Users must distinguish at a glance: draft vs approved, generated vs reviewed, pending vs blocked, published vs internal, monitoring vs action-required, analysis vs evidence, temporary UI state vs committed system state.

### P08 — AI vs Determinism Visibility (§17)
The interface must not blur: raw evidence, deterministic metric, model inference, generated narrative, approval-required content, published artifact. Achieved via badges, captions, metadata treatment, provenance presentation, evidence containers, generation states.

### P09 — Cross-Vertical Consistency (§18)
Credit and Wealth must share: surface hierarchy, typography logic, border semantics, spacing rhythm, depth model, action hierarchy, process state language. Vertical-specific nuance appears in page composition and domain modules only.

### P10 — Token Governance (§19, §24)
No arbitrary colors outside the token system. No local gray mixing. No one-off shadows. No decorative gradients without system guidance. No spontaneous visual variants outside action hierarchy. Token categories: surface, border, accent, semantic status, typography roles, semantic spacing, elevation, motion durations, state tokens.

### P11 — Color as Governance Instrument (§9)
Base palette: deep navy, steel-blue neutrals, mineral grays, warm highlights. Accent indicates actionability/focus/emphasis — not just "button color." Semantic colors (success/warning/danger/info) are role-driven, not decorative. Risk must feel serious without saturating the interface red.

### P12 — Component Doctrine (§20)
Components carry system logic: cards express containment hierarchy, buttons reflect action class and decision gravity, inputs feel precise and stable, tables optimize for density and scanability, badges convey state without decoration, drawers/modals feel meaningfully elevated, charts feel analytical not promotional.

### P13 — Page Archetype Discipline (§21)
Recurring page types must follow explicit compositional logic: dashboards (summary + exception visibility), workbenches (action locality + before/after legibility), detail pages (metadata + narrative + evidence balance), review pages (status + responsibility + decision controls), report readers (long-form readability + chapter nav), document pages (provenance + classification + lifecycle states), investor-facing pages (cleaner/calmer but same system).

### P14 — Dark Mode as Deliberate Adaptation (§22)
Dark mode requires component-level adjustment, not inversion. Elevated surfaces stay distinct. Hover states stay legible. Borders don't disappear. Charts and badges stay restrained. Long-form reading avoids glowing fatigue.

### P15 — Status Language Consistency (§24)
No status language that differs between domains without reason. No component styling that hides process maturity.

### P16 — No Page-Level Improvisation (§24)
No page-level improvisation that overrides semantic spacing and surface logic.

---

## 2. Runtime and UX Anchors

### Token System — `packages/ui/src/lib/styles/`

| File | Anchors |
|---|---|
| `tokens.css` | `--netz-surface`, `--netz-surface-alt`, `--netz-surface-elevated`, `--netz-surface-raised`, `--netz-surface-panel`, `--netz-surface-highlight`, `--netz-surface-accent`; `--netz-border-subtle`, `--netz-border`, `--netz-border-strong`, `--netz-border-accent`, `--netz-border-focus`; `--netz-brand-primary`, `--netz-brand-secondary`, `--netz-brand-accent`, `--netz-brand-highlight`; `--netz-success`, `--netz-warning`, `--netz-danger`, `--netz-info`; `[data-theme="dark"]` overrides |
| `spacing.css` | Raw scale `--netz-space-1` to `--netz-space-16`; semantic inline `--netz-space-inline-2xs` to `--netz-space-inline-2xl`; semantic stack `--netz-space-stack-2xs` to `--netz-space-stack-2xl`; context tokens `--netz-space-card-padding`, `--netz-space-panel-padding`, `--netz-space-page-gutter` |
| `typography.css` | `--netz-text-display`, H1–H6, `--netz-text-body-lg`, `--netz-text-body`, `--netz-text-small`, `--netz-text-label`, `--netz-text-caption`, `--netz-text-mono`; `--netz-leading-body` (1.65), `--netz-tracking-label` (0.08em); `--netz-measure-body` (70ch) |
| `shadows.css` | `--netz-shadow-1` to `--netz-shadow-5`; `--netz-shadow-inset`, `--netz-shadow-focus`, `--netz-shadow-card`, `--netz-shadow-floating` |
| `animations.css` | `--netz-duration-fast` (140ms), `--netz-duration-normal` (220ms), `--netz-duration-slow` (320ms); `--netz-ease-default`, `--netz-ease-emphasized`; `@media (prefers-reduced-motion: reduce)` gate |

### Workflow & Approval — Backend Models

| Anchor | Location |
|---|---|
| `DealStage` enum | `backend/app/domains/credit/deals/enums.py` — INTAKE → QUALIFIED → IC_REVIEW → CONDITIONAL → APPROVED → CONVERTED_TO_ASSET \| REJECTED \| CLOSED |
| `DDReport.status` | `backend/app/domains/wealth/models/dd_report.py` — draft → pending_approval → completed \| escalated \| rejected; tracks `approved_by`, `approved_at`, `rejection_reason`, `version`, `is_current` |
| `UniverseApproval.decision` | `backend/app/domains/wealth/models/dd_report.py` — pending → approved \| rejected \| watchlist; enforces `decided_by != created_by` (no self-approval) |
| Deal stage PATCH | `backend/app/domains/credit/modules/deals/routes.py:332` — `PATCH /pipeline/deals/{deal_id}/stage` with `DealStagePatch` schema |

### Shared Components — `packages/ui/src/lib/components/`

| Component | Validates Principle |
|---|---|
| `StatusBadge.svelte` | P07, P15 — auto-infers status color from token set: {approved, completed, published → success}, {pending, warning → warning}, {rejected, failed → danger}, {active, generated, processing → info} |
| `ConsequenceDialog.svelte` | P07, P12 — requires rationale, typed confirmation, metadata grid, consequence list; destructive variant shifts focus to Cancel |
| `AuditTrailPanel.svelte` | P07, P08 — immutable event log with actor, rationale, outcome, changedFields, sourceSystem; status-colored entries |
| `Badge.svelte` | P12 — variants: default, secondary, destructive, outline |
| `Card.svelte` | P01, P12 — containment + hierarchy carrier |
| `DataTable` | P12, P13 — density + scanability |
| `AppShell`, `Sidebar`, `TopNav` | P01 — structural frame layer |
| `Sheet`, `Dialog`, `DropdownMenu` | P01, P05 — elevated decision layer |
| `MetricCard`, `DataCard` | P01, P03 — analytical surface layer |

### SSE Streaming — Real-Time State Communication

| Anchor | Location |
|---|---|
| Frontend SSE client | `packages/ui/src/lib/utils/sse-client.svelte.ts` — `fetch()` + `ReadableStream`, exponential backoff, heartbeat 45s, event cap 200, subscribe-then-snapshot pattern |
| Backend SSE emitter | `backend/app/core/jobs/sse.py` — `EventSourceResponse`, heartbeat 15s, terminal event detection, disconnect respect |
| SSE registry | `packages/ui/src/lib/index.ts` — `canOpenSSE`, `registerSSE`, `unregisterSSE`, max 4 concurrent |

### Formatter Discipline — `packages/ui/src/lib/utils/format.ts`

| Function | Domain |
|---|---|
| `formatCurrency` | BRL default, 2 decimal |
| `formatNumber` | Fixed decimals, pt-BR locale |
| `formatPercent` | 0.05 → 5%, optional sign |
| `formatBps` | Basis points |
| `formatNAV` | 4-decimal NAV |
| `formatRatio` | Leverage (1.23x) |
| `formatDate`, `formatDateTime`, `formatShortDate`, `formatRelativeDate`, `formatDateRange` | Date tiers for audit, dense, and narrative contexts |
| `formatISIN` | ISIN segmentation |
| `plDirection`, `plColor` | P&L semantic coloring |

### Dark Mode — Theme Infrastructure

| Anchor | Location |
|---|---|
| CSS token overrides | `packages/ui/src/lib/styles/tokens.css` — `[data-theme="dark"]` block inverts surfaces, brightens text, adjusts brand colors |
| Shadow adaptation | `packages/ui/src/lib/styles/shadows.css` — dark mode uses inset highlights + stronger drops |
| Theme hook | `packages/ui/src/lib/utils/theme.ts` — cookie-driven `data-theme` attribute, SSR-safe |

### AI Provenance — Current State

| Anchor | Location |
|---|---|
| `CopilotCitation.svelte` | `frontends/credit/src/lib/components/CopilotCitation.svelte` — source document attribution with page number |
| `CopilotChat.svelte` | `frontends/credit/src/lib/components/CopilotChat.svelte` — RAG chat with SSE streaming |
| StatusBadge "generated" token | Maps to `info` (blue) — no dedicated AI-vs-deterministic badge exists |

### Cross-Vertical Sharing — `packages/ui/src/lib/index.ts`

43 exports shared via `@netz/ui`. Credit has ~11 vertical-specific components, Wealth has ~6. `IngestionProgress` is duplicated across both frontends (consolidation candidate). Frontends never cross-import — sharing is exclusively via `@netz/ui` and the backend API.
