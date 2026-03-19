# Principles vs Implementation Audit

Source: `docs/ux/system-ux-principles.md`
Checkpoint: `docs/ux/principles-audit-checkpoint-1.md`
Date: 2026-03-19

---

## Domain 1 — Design-System Foundations

### P10 — Token Governance (SS19, SS24)

**Principle:** No arbitrary colors outside the token system. No local gray mixing. No one-off shadows. No decorative gradients without system guidance. Token categories must cover surface, border, accent, semantic status, typography roles, semantic spacing, elevation, motion durations, and state tokens.

**Status:** PARTIALLY VALIDATED

**Evidence:**
- `packages/ui/src/lib/styles/tokens.css` defines 9 surface tokens, 6 border tokens, 5 brand colors, 4 semantic colors, 5 text colors, all with `[data-theme="dark"]` overrides (lines 6-188).
- `spacing.css` defines raw scale (`--netz-space-1` to `--netz-space-16`), semantic inline/stack tokens, and component-specific tokens (`--netz-space-card-padding`, `--netz-space-panel-padding`, `--netz-space-page-gutter`).
- `typography.css` defines Inter Variable sans + JetBrains Mono, 8 heading/body levels, 8 line-heights, 7 tracking values, 5 weights, 3 text measures.
- `shadows.css` defines 5 elevation levels + semantic aliases (`--netz-shadow-card` = shadow-2, `--netz-shadow-floating` = shadow-4), with dark mode remapping.
- `animations.css` defines 5 durations, 5 easings, 7 keyframe animations, 7 utility classes, and a `prefers-reduced-motion` gate.

**Violations found:**
- Sign-in pages (credit, wealth, admin) contain ~10+ fallback hex colors inside `var()` declarations (e.g., `background: var(--netz-brand-primary, #0f172a)`), ~6 inline `rgba()` box-shadows, and ~15 hardcoded px spacing values. These are defensive CSS fallbacks but violate single-source-of-truth governance.
- `frontends/wealth/src/lib/stores/stale.ts:14-23` instantiates `new Intl.DateTimeFormat("en-US", {...})` directly, and line 89 uses `.toLocaleDateString()`. Both violate ESLint rules defined in `frontends/eslint.config.js:18-44`.
- ESLint formatter rules exist but are not enforced in CI (`make check` does not run ESLint on frontends).

**Why partially:** Token infrastructure is comprehensive and well-structured. All application pages (excluding sign-in) use tokens exclusively. But the sign-in pages and stale.ts violate governance, and the ESLint enforcement gap means violations can reappear without detection.

**Severity:** Medium — violations are isolated to 4 files, not systemic.
**Confidence:** High — grep-verified across all frontends.

---

### P11 — Color as Governance Instrument (SS9)

**Principle:** Base palette: deep navy, steel-blue neutrals, mineral grays, warm highlights. Accent indicates actionability/focus/emphasis. Semantic colors are role-driven, not decorative.

**Status:** VALIDATED

**Evidence:**
- Light theme brand: `--netz-brand-primary: #0f172a` (deep navy), `--netz-brand-secondary: #3b82f6` (steel-blue), `--netz-brand-accent: #6366f1` (indigo accent), `--netz-brand-light: #dfe7f0` (mineral gray), `--netz-brand-highlight: #f9c74f` (warm highlight).
- Semantic colors: `--netz-success: #059669`, `--netz-warning: #d97706`, `--netz-danger: #dc2626`, `--netz-info: #2563eb` — role-driven, not decorative.
- `StatusBadge.svelte` maps status tokens to severity levels (success/warning/danger/info/neutral) with `color-mix(in srgb, {token} 14%, transparent)` backgrounds — restrained, not saturated.
- `Button.svelte` uses `--netz-brand-primary` for default, `--netz-danger` for destructive, `--netz-surface-panel` for secondary — action class determines color.

**Why it holds:** Color palette is cohesive, navy-anchored, and semantically governed. Accent usage is limited to actionability (buttons, focus rings, active nav items), not decoration.

**Severity:** N/A
**Confidence:** High

---

### P01 — Surface Hierarchy (SS10)

**Principle:** Five distinct surface layers must be perceptible: structural frame (shell, nav), operational workspace (pages), analytical surface (cards, tables, charts), process layer (statuses, approvals, SSE progress), elevated decision layer (modals, drawers, dropdowns).

**Status:** PARTIALLY VALIDATED

**Evidence:**
- 9 surface tokens exist: `--netz-surface` (base), `--netz-surface-alt`, `--netz-surface-elevated` (#ffffff), `--netz-surface-inset`, `--netz-surface-overlay`, `--netz-surface-raised`, `--netz-surface-panel`, `--netz-surface-highlight`, `--netz-surface-accent`.
- Structural frame: `TopNav.svelte` uses gradient from `surface-highlight` to `surface-elevated` with backdrop-blur + shadow. Body background is `--netz-surface`.
- Analytical surface: `Card.svelte` uses `.netz-ui-surface` (surface-elevated + border-subtle + shadow-card). `MetricCard.svelte` uses `surface-highlight` + shadow-card. `DataTable.svelte` uses surface-panel for container, surface-highlight for header, surface-elevated for rows, surface-inset for expanded rows.
- Elevated decision: `Dialog.svelte` and `Sheet.svelte` use `surface-panel` + `shadow-floating` (shadow-4) + `surface-overlay` backdrop.

**What's missing:** The five-layer model from the doctrine (structural frame, operational workspace, analytical surface, process layer, elevated decision) is NOT expressed as named token tiers (`surface-1`, `surface-2`, `surface-3`, `surface-inverse`). The system uses 9 functionally-named tokens instead. There is no explicit `--netz-surface-inverse` token. The process layer has no dedicated surface treatment — status badges use `color-mix` inline, not a distinct surface.

**Why partially:** Surface differentiation exists and works visually, but the naming and conceptual model diverge from the doctrine's five-layer specification. A developer cannot look at the tokens and understand the 5-layer hierarchy without reading the doctrine. The mapping is implicit, not explicit.

**Severity:** Low — the visual result is correct; the naming gap is a documentation/evolvability issue.
**Confidence:** High

---

### P02 — Border Semantics (SS11)

**Principle:** Four tiers: subtle (layout containment), default (affordance), strong (emphasis/stateful), focus (interaction only).

**Status:** VALIDATED

**Evidence:**
- `tokens.css` defines: `--netz-border-subtle` (layout), `--netz-border` (standard affordance), `--netz-border-strong` (emphasis), `--netz-border-focus` (interaction rings), plus `--netz-border-accent` and `--netz-border-inverse`.
- Usage in components: `Card.svelte` → `border-subtle`, `DataTable.svelte` container → `border-subtle`, `Input.svelte` → `border-subtle` baseline with `focus:border-accent` + `shadow-focus` ring, `Dialog/Sheet` → `border-subtle` on elevated surface.
- `MetricCard.svelte` uses a 3px left border in status color for process emphasis — semantic border application.

**Why it holds:** All four required tiers exist and are used with correct semantic intent. Two additional tokens (accent, inverse) extend the system without violating it.

**Severity:** N/A
**Confidence:** High

---

### P03 — Typography as Institutional Hierarchy (SS12)

**Principle:** Display (rare, major entry points) → heading (authority) → subheading (sectional navigation) → body (readable under density) → label (precise, compact) → caption (metadata/secondary context). Must support scanning and sustained reading.

**Status:** VALIDATED

**Evidence:**
- `typography.css` defines: `--netz-text-display` (2.25rem/650wt), H1-H6, `--netz-text-body-lg`, `--netz-text-body`, `--netz-text-small`, `--netz-text-label` (0.8125rem/0.08em tracking), `--netz-text-caption` (0.75rem), `--netz-text-mono`.
- Line heights: body at 1.65 (generous for sustained reading), display at 1.08 (tight for authority).
- Text measures: `--netz-measure-compact` (48ch), `--netz-measure-body` (70ch), `--netz-measure-wide` (82ch) — controls line length for readability.
- `PageHeader.svelte` uses H2 for page titles. `MetricCard.svelte` uses label for kicker, mono for value. `AuditTrailPanel.svelte` uses caption for metadata.

**Why it holds:** All six tiers exist with distinct operational roles. Line-height and tracking are tuned per tier. Text measures prevent wide-screen readability collapse.

**Severity:** N/A
**Confidence:** High

---

### P04 — Semantic Spacing (SS13)

**Principle:** Spacing must be role-driven: section spacing, block spacing, card padding, form gap, inline spacing. Mixed compositions must not feel improvised.

**Status:** VALIDATED

**Evidence:**
- `spacing.css` defines: semantic inline (`--netz-space-inline-2xs` to `--netz-space-inline-2xl`), semantic stack (`--netz-space-stack-2xs` to `--netz-space-stack-2xl`), and component-specific tokens (`--netz-space-card-padding: 20px`, `--netz-space-panel-padding: 28px`, `--netz-space-page-gutter: 32px`, `--netz-space-page-block: 40px`, `--netz-space-section-gap: 32px`).
- Control heights: `--netz-space-control-height-sm/md/lg` (32/40/48px).
- Wealth dashboard uses `p--netz-space-page-gutter` and `space-y--netz-space-section-gap` CSS variables directly.
- Credit pages use Tailwind classes (px-6, gap-4, space-y-6) which map to the same raw scale but bypass semantic naming.

**Why it holds:** The semantic token layer exists and is correct. Wealth frontend adopts it more thoroughly than Credit, but both produce visually consistent results because the raw Tailwind classes align with the scale.

**Severity:** N/A
**Confidence:** High

---

### P05 — Depth from Surface + Border + Shadow (SS14)

**Principle:** Elevation must emerge from the interaction of surface color, border discipline, and ambient shadow — not shadow alone.

**Status:** VALIDATED

**Evidence:**
- `Card.svelte` uses `.netz-ui-surface` → `surface-elevated` (white) + `border-subtle` (low-noise containment) + `shadow-card` (shadow-2, ambient) = three-source depth.
- `Dialog.svelte` uses `surface-panel` (color-mix tint) + `border-subtle` + `shadow-floating` (shadow-4) + `surface-overlay` (blur backdrop) = four-source elevation.
- `MetricCard.svelte` adds status-color left border (3px) as a fourth depth source.
- `DataTable.svelte` container uses `surface-panel` + `border-subtle` + `shadow-1` for base, with `surface-highlight` header and `surface-inset` for expanded rows — layered depth within a single component.
- Dark mode shadows in `shadows.css` use inset highlights + increased opacity — not just inverted light mode shadows.

**Why it holds:** Every elevated component composes surface + border + shadow. No component relies on shadow alone.

**Severity:** N/A
**Confidence:** High

---

### P06 — Motion as State Communication (SS15)

**Principle:** Hover/pressed/focus: subtle and fast. Panel entrances: controlled. Loading/generation: process legitimacy. SSE-fed changes: never jumpy. No animation without clarity.

**Status:** VALIDATED

**Evidence:**
- `animations.css` defines: `--netz-duration-fast` (140ms) for hover/pressed/focus, `--netz-duration-normal` (220ms) for panel entrances, `--netz-duration-slow` (320ms) for emphasis transitions.
- `Button.svelte` uses `-translate-y-px` on hover, `translate-y-0` on press — subtle, fast (shadow transition preset).
- `Sheet.svelte` uses `translate-x` slide with configurable duration — controlled panel entrance.
- `LongRunningAction.svelte` shows progress bar with percentage + stage label + ETA during SSE generation — process legitimacy through concrete metrics, not spinner loops.
- `sse-client.svelte.ts` caps events at 200 with exponential backoff — prevents jumpy flooding.
- `prefers-reduced-motion: reduce` gate disables all animations — accessibility-compliant.

**Why it holds:** Motion vocabulary is purpose-driven. Fast for interaction states, controlled for panels, metric-based for generation. No decorative animations found.

**Severity:** N/A
**Confidence:** High

---

## Domain 2 — Structural Shell and Layout Hierarchy

### P01 (Shell Layer) — Structural Frame

**Principle:** Application shell, side navigation, top-level headers, page chrome must establish where the user is in the operating system.

**Status:** PARTIALLY VALIDATED

**Evidence:**
- Shared shell components in `packages/ui/src/lib/layouts/`: `AppLayout.svelte` (155 lines), `TopNav.svelte` (296 lines), `ContextSidebar.svelte` (126 lines), `InvestorShell.svelte` (181 lines), `PageHeader.svelte` (126 lines).
- All three frontends (Credit, Wealth, Admin) use identical `AppLayout` + `TopNav` primitives.
- `TopNav` renders text-only nav items with border-bottom active indicator and gradient background using surface tokens.
- Credit: 3 nav items (Dashboard, Funds, Copilot). Wealth: 12 nav items. Admin: 5 nav items.
- `ContextSidebar` provides detail-page navigation with back link + contextual nav items. Used by Credit and Admin, NOT by Wealth.
- `InvestorShell` provides minimal investor portal shell. Used by both Credit and Wealth investor routes.
- Branding injection via `BrandingConfig` → CSS custom properties on document root (tenant-aware theming).

**What's missing:**
- `Sidebar.svelte` (227 lines) and `AppShell.svelte` (164 lines, CSS Grid 3-column layout) are fully built but NOT USED in any frontend.
- `ContextPanel.svelte` (186 lines, slide-in right panel) is built but unused.
- `PageHeader` breadcrumbs are supported but rarely used in practice.
- Wealth has no `ContextSidebar` for detail pages (fund detail, DD report detail) — users navigate flat routes without hierarchical context.

**Why partially:** The structural frame exists and is consistent across verticals. But significant infrastructure (`Sidebar`, `AppShell` grid, `ContextPanel`) is built and not activated. Wealth's lack of `ContextSidebar` means detail pages don't express hierarchical position as strongly as Credit's.

**Severity:** Medium — built components sitting unused is not harmful, but Wealth's missing context nav weakens wayfinding on detail pages.
**Confidence:** High

---

## Domain 3 — Shared Components and Interaction Language

### P12 — Component Doctrine (SS20)

**Principle:** Cards express containment + hierarchy. Buttons reflect action class + decision gravity. Inputs feel precise and stable. Tables optimize for density + scanability. Badges convey state without decoration. Drawers/modals feel meaningfully elevated. Charts feel analytical, not promotional.

**Status:** VALIDATED

**Evidence:**
- **Card.svelte:** `.netz-ui-surface` = surface-elevated + border-subtle + shadow-card. `MetricCard.svelte` adds status-color left border, sparkline slot, delta indicators. `DataCard.svelte` provides simpler variant with trend support.
- **Button.svelte:** 6 variants (default, secondary, destructive, outline, ghost, link) × 3 sizes. Default uses brand-primary with shadow elevation. Destructive uses danger. Ghost is transparent. All have y-translation press feedback. `ActionButton.svelte` wraps Button with loading spinner for async mutations.
- **Input/Textarea:** Use `.netz-ui-field` class = surface-raised + border-subtle baseline + focus:border-accent + shadow-focus ring. `FormField.svelte` standardizes label/error/hint layout.
- **DataTable.svelte:** @tanstack/svelte-table. Header = surface-highlight, rows = surface-elevated with hover:accent-soft, expanded rows = surface-inset. Compact cells (h-11 header, px-4 py-3.5 cells). Server-side pagination support.
- **StatusBadge.svelte:** Smart inference with severity mapping. Dot indicator + color-mixed background at 14% opacity. Custom resolver prop for domain-specific mappings. No decorative styling.
- **Dialog.svelte / Sheet.svelte:** Both use surface-panel + shadow-floating (shadow-4) + surface-overlay backdrop with blur. Dialog centers with scale-in. Sheet slides from edge. Both use `--netz-space-panel-padding`.
- **ConsequenceDialog.svelte:** Multi-layered gravity escalation: impact summary, consequence list, metadata grid, require-rationale, typed confirmation text, auto-focus cancel for destructive. 284 lines of institutional-grade friction.
- **Charts:** 8 chart types exported (TimeSeriesChart, RegimeChart, GaugeChart, BarChart, FunnelChart, HeatmapChart, ScatterChart + ChartContainer wrapper).

**Why it holds:** Every component category named in the doctrine has a concrete, token-compliant implementation. The interaction language (color for action class, elevation for importance, friction for gravity) is consistent.

**Severity:** N/A
**Confidence:** High

---

### Component Duplication

**Status:** PARTIALLY VALIDATED (for shared component consolidation)

**Evidence:**
- `IngestionProgress.svelte` exists identically in both `frontends/credit/src/lib/components/` and `frontends/wealth/src/lib/components/` (69 lines each). Only difference: status resolver import (`resolveCreditStatus` vs `resolveWealthStatus`) and a `type="review"` prop on one StatusBadge.
- 43 exports shared via `@netz/ui`. Credit has 11 vertical-specific components. Wealth has 6.
- No other cross-vertical duplication detected.

**Why partially:** One concrete duplication exists. The shared library adoption is otherwise excellent — both frontends import exclusively from `@netz/ui` for all shared primitives.

**Severity:** Low — single file, minimal divergence.
**Confidence:** High

---

## Domain 4 — Workflow and Process-State Visibility

### P07 — Workflow State Visibility (SS16)

**Principle:** Users must distinguish at a glance: draft vs approved, generated vs reviewed, pending vs blocked, published vs internal, monitoring vs action-required, analysis vs evidence, temporary UI state vs committed system state.

**Status:** PARTIALLY VALIDATED

**Evidence:**

**Backend state machines are well-defined:**
- Credit `DealStage`: 8-state enum (INTAKE → QUALIFIED → IC_REVIEW → CONDITIONAL → APPROVED → CONVERTED_TO_ASSET | REJECTED | CLOSED).
- Credit `DocumentReviewStatus`: 6-state FSM (SUBMITTED → UNDER_REVIEW → APPROVED | REJECTED | REVISION_REQUESTED | CANCELLED).
- Credit `DocumentIngestionStatus`: 4-state enum (PENDING → PROCESSING → INDEXED | FAILED), shared with Wealth.
- Credit deal intelligence: 3-state lifecycle (PENDING → PROCESSING → READY | FAILED).
- Wealth `DDReport.status`: string field (draft → pending_approval → approved), NOT an enum.
- Wealth `UniverseApproval.decision`: string field (pending → approved | rejected), NOT an enum.

**Frontend rendering is functional but inconsistent:**
- `StatusBadge` correctly maps states to severity colors via per-vertical resolvers (`resolveCreditStatus`, `resolveWealthStatus`, `resolveAdminStatus`).
- Credit `PipelineKanban.svelte`: 8-column Kanban with drag-drop + ConsequenceDialog for stage transitions.
- Credit `DealStageTimeline.svelte`: horizontal timeline with StatusBadge per event + actor + rationale.
- Credit `IngestionProgress.svelte`: 7-stage SSE pipeline visualization (ocr → classify → governance → chunk → extract → embed → index).
- Wealth DD report page: approval bar with color-coded status + approval/reject buttons gated by IC role + not-self-approval constraint.
- Wealth universe page: two-tab interface (approved vs pending) with approve/reject actions.

**Gaps:**
- Wealth uses string defaults (not enums) for DD report status and universe decisions — no compile-time validation of state transitions. State values are convention, not contract.
- ConsequenceDialog is used for deal stage moves (Credit) and cashflow edits (Credit) and allocation saves (Wealth), but NOT for DD report approvals (Wealth) or universe approvals (Wealth) — these use simpler `ConfirmDialog` without consequence metadata.
- "Published vs internal" distinction exists in backend (`DDReport.status` → approved = investor-visible) but no explicit visual differentiation between internal-draft and investor-published versions in the UI beyond the status badge text.
- "Generated vs reviewed" distinction: IC memos show committee votes + quorum gate, but generated narrative chapters have no inline "AI-generated" marker.
- "Monitoring vs action-required" partially addressed: Wealth SSE risk store shows degraded-state banner (amber/red) when connection interrupted; Credit has no equivalent.

**Why partially:** The core state machines and status rendering work. But the approval gravity varies between verticals (ConsequenceDialog in Credit vs ConfirmDialog in Wealth), Wealth uses strings instead of enums for critical states, and several doctrine-required distinctions (published vs internal, generated vs reviewed) are implicit rather than visually explicit.

**Severity:** High — inconsistent approval gravity between verticals and missing enum safety in Wealth are operational risks.
**Confidence:** High

---

### P15 — Status Language Consistency (SS24)

**Principle:** No status language that differs between domains without reason. No component styling that hides process maturity.

**Status:** PARTIALLY VALIDATED

**Evidence:**
- Credit status vocabulary: INTAKE, QUALIFIED, IC_REVIEW, CONDITIONAL, APPROVED, REJECTED, CLOSED, CONVERTED_TO_ASSET, SUBMITTED, UNDER_REVIEW, REVISION_REQUESTED, CANCELLED, PENDING, PROCESSING, INDEXED, FAILED.
- Wealth status vocabulary: draft, pending_approval, approved, rejected, pending, generating, published, completed, pass, fail, watchlist, breach, crisis, risk_on.
- Shared vocabulary: PENDING, PROCESSING, FAILED, APPROVED, REJECTED — these overlap semantically but differ in casing (Credit: UPPER_CASE enums, Wealth: lower_case strings).
- StatusBadge auto-inference handles both (case-insensitive token matching), so visual output is consistent despite backend inconsistency.

**Why partially:** The StatusBadge component normalizes the visual output, so users see consistent colors. But the backend vocabulary divergence (enums vs strings, UPPER_CASE vs lower_case) is a hidden inconsistency that creates maintenance risk. The visual layer masks the structural gap.

**Severity:** Medium — visually consistent but structurally fragile.
**Confidence:** High

---

## Domain 5 — Cross-Vertical Consistency

### P09 — Cross-Vertical Consistency (SS18)

**Principle:** Credit and Wealth must share: surface hierarchy, typography logic, border semantics, spacing rhythm, depth model, action hierarchy, process state language. Vertical-specific nuance appears in page composition and domain modules only.

**Status:** VALIDATED

**Evidence:**

**Shared foundations (100% consistent):**
- Both frontends use identical `AppLayout` + `TopNav` from `@netz/ui`.
- Both use identical `InvestorShell` for investor portals.
- Both import all shared components from `@netz/ui` barrel export (43 exports).
- Both use Svelte 5 runes ($state, $derived, $effect) identically.
- Both use `createClientApiClient` + `getContext("netz:getToken")` for API authentication.
- Token system is shared via `@netz/ui` package — single CSS source.

**Formatter discipline (100% compliant):**
- Zero `.toFixed()`, `.toLocaleString()`, or inline `Intl.*` violations across 41 files in both frontends (excluding `stale.ts` utility).
- Both import `formatCurrency`, `formatNumber`, `formatPercent`, `formatDate`, etc. from `@netz/ui`.
- Wealth uses locale-specific wrappers (e.g., `formatAUM(value, "BRL", "pt-BR")`) — acceptable pattern.

**Route organization reflects domain, not divergent design:**
- Credit: hierarchical routes (`/funds/[fundId]/pipeline/[dealId]`) — deal-centric.
- Wealth: broader flat routes (`/risk`, `/macro`, `/allocation`) — portfolio-centric.
- Both use `(team)` / `(investor)` route groups identically.

**Page archetypes follow same patterns:**
- PageHeader + SectionCard wrapper for content sections.
- Grid-based responsive layouts (sm:, md:, lg: breakpoints).
- Card-based metric displays with StatusBadge for status rendering.

**Vertical-specific components are domain-appropriate:**
- Credit: 11 components (deal pipeline, copilot, IC memos — document-heavy domain).
- Wealth: 6 components (portfolio cards, macro chips, drift history — analytics-heavy domain).

**Minor divergence:**
- Credit pages use bare Tailwind classes (px-6, gap-4). Wealth pages use CSS variable references (`p--netz-space-page-gutter`). Both produce the same visual result because Tailwind classes align with the raw scale.
- IngestionProgress.svelte is duplicated (see Domain 3).

**Why it holds:** The shared design language persists across both verticals at every level: tokens, components, layouts, formatters, state management, and API patterns. Divergence is limited to domain-appropriate page composition and one duplicated component.

**Severity:** N/A
**Confidence:** High

---

## Domain 6 — AI/Provenance/Determinism Visibility

### P08 — AI vs Determinism Visibility (SS17)

**Principle:** The interface must not blur: raw evidence, deterministic metric, model inference, generated narrative, approval-required content, published artifact. Achieved via badges, captions, metadata treatment, provenance presentation, evidence containers, generation states.

**Status:** PARTIALLY VALIDATED

**Evidence:**

**What exists (strong backend provenance):**
- `DocumentReview` model tracks: `classification_confidence` (float 0-1), `classification_layer` (1=rules, 2=embeddings, 3=LLM), `classification_model` (e.g., "gpt-4.1-mini"), `routing_basis`.
- `MemoEvidencePack` model: frozen institutional truth source (evidence_json, version_tag, token_count, model_version, is_current).
- `MemoChapter` model: chapter_number, chapter_tag, content_md, model_version, token_count_input/output, generated_at, evidence_pack_id.
- `DealUnderwritingArtifact` model: recommendation, confidence_level, risk_band, model_version, evidence_pack_hash, critic_findings, policy_breaches.
- `DDReport` model: status (draft/pending_approval/approved), created_by, approved_by, rejection_reason. `DDChapter` tracks critic_iterations.
- Provenance API endpoint: `GET /funds/{fund_id}/deals/{deal_id}/documents/{document_id}/ai-provenance` returns classification layer label, confidence, model, embedding metadata.
- Decision audit endpoint: `GET /funds/{fund_id}/deals/{deal_id}/decision-audit` returns immutable audit events with actor, rationale, before/after state snapshots.
- IC memo timeline endpoint: `GET /funds/{fund_id}/deals/{deal_id}/ic-memo/timeline` tracks memo versions + committee votes.

**What exists (frontend generation states):**
- `LongRunningAction.svelte`: 6-state machine (idle → starting → in-flight → success → error → cancelled) with progress bar, stage label, ETA countdown.
- `ICMemoViewer.svelte`: streaming chapters with animated cursor, quorum gate (chapters hidden until committee quorum reached), committee vote display with colored badges.
- `ICMemoStreamingChapter.svelte`: individual chapter streaming with typing animation.
- `CopilotChat.svelte`: citations displayed under "Sources:" header with clickable links to source document + page number.
- `CopilotCitation.svelte`: document title + page number attribution.
- `IngestionProgress.svelte`: 7-stage pipeline visualization (ocr → classify → governance → chunk → extract → embed → index) with per-stage StatusBadge.

**What's missing (frontend provenance gaps):**
1. **No AI-generated badge on memo narrative content.** Memo chapters render as plain markdown. No visible indicator distinguishing AI-generated narrative from human-written or evidence-quoted content. The `StatusBadge` "generated" token maps to `info` (blue) — no dedicated AI-vs-deterministic visual treatment exists.
2. **Confidence scores are tracked but hidden.** `DDReport.confidence_score` (Decimal 5,2) and `DealUnderwritingArtifact.confidence_level` are stored in the database but NOT rendered in any frontend page.
3. **Classification layer transparency is API-only.** The `/ai-provenance` endpoint returns whether classification used rules (60%), embeddings (30%), or LLM (10%), but this information is not integrated into the document review UI. Users see the classification result but not the method.
4. **Evidence pack is not user-inspectable.** `MemoEvidencePack.evidence_json` (frozen source of truth for chapter generation) is never serialized to the frontend. Users see generated chapters but cannot inspect the evidence that produced them.
5. **DD report chapter-level metadata is hidden.** `DDChapter.critic_iterations`, `quant_data`, and `evidence_refs` are stored but not exposed in the UI.
6. **No "Sources for this chapter" inspector** on IC memos or DD reports. Citations exist in Copilot but not in memo/report viewers.

**Why partially:** The backend provenance architecture is institutional-grade — classification layers, evidence packs, model versions, decision audit trails, committee votes, and approval workflows are all tracked with full metadata. The frontend generation state machine (LongRunningAction) is excellent. But the frontend does not surface most of this provenance data to users. The interface blurs "generated narrative" and "evidence" because memo chapters render identically regardless of source. Confidence scores exist but are invisible. Classification transparency exists but is API-only. The gap is not architectural — it's a presentation gap.

**Severity:** High — this is the doctrine's central demand ("make intelligence auditable"), and the frontend underdelivers relative to what the backend already provides.
**Confidence:** High

---

## Contradictions

### C1 — Consequence Dialog gravity inconsistency

The `ConsequenceDialog` component (284 lines) implements institutional-grade friction: impact summary, consequence list, metadata grid, typed confirmation, rationale requirement, auto-focus cancel for destructive actions. It is used for Credit deal stage transitions (`PipelineKanban.svelte`) and cashflow edits (`CashflowLedger.svelte`). However, Wealth's approval workflows (DD report approval, universe approval) use the simpler `ConfirmDialog` from shadcn-ui without consequence metadata, rationale fields, or typed confirmation. This means approving a DD report for investor distribution — an action with regulatory implications — has LESS friction than moving a deal between pipeline stages.

### C2 — Enum safety asymmetry

Credit defines all workflow states as Python enums (`DealStage`, `DocumentReviewStatus`, `DocumentIngestionStatus`). Wealth uses bare string fields with `server_default` values for DD report status and universe approval decisions. This means Credit has compile-time validation of state transitions while Wealth relies on convention. A typo in a Wealth status string ("pendig_approval") would pass type checks and produce a silent bug.

### C3 — Built infrastructure vs actual usage

`Sidebar.svelte` (227 lines), `AppShell.svelte` (164 lines, CSS Grid 3-column layout), and `ContextPanel.svelte` (186 lines) are fully implemented, exported from `@netz/ui`, but unused in any frontend. The doctrine describes a structural frame layer that "establishes where the user is in the operating system," but the actual navigation uses only TopNav + ContextSidebar (Credit/Admin) or TopNav alone (Wealth). The sidebar infrastructure represents 577 lines of maintained-but-dead code.

### C4 — Surface token naming vs doctrine model

The doctrine specifies five named layers (surface-base, surface-1, surface-2, surface-3, surface-inverse). The implementation provides nine functionally-named tokens (surface, surface-alt, surface-elevated, surface-inset, surface-overlay, surface-raised, surface-panel, surface-highlight, surface-accent). These serve the same visual purpose but the mapping between doctrine names and implementation names is undocumented. A developer reading the doctrine cannot map it to the code without institutional knowledge.

---

## Hidden Complexity and False Confidence

### HC1 — ESLint rules exist but are not enforced

`frontends/eslint.config.js` (lines 18-44) bans `.toFixed()`, `.toLocaleString()`, `new Intl.NumberFormat()`, and `new Intl.DateTimeFormat()`. However, `make check` does not run ESLint on frontends, and `stale.ts` already violates these rules. The rules create a false impression of enforcement. Without CI integration, violations will accumulate silently in future development.

### HC2 — Branding injection can override all surface tokens

`branding.ts` maps `BrandingConfig` fields to CSS custom properties via `Element.style.setProperty()` on the document root. This includes `surface_color → --netz-surface`, `surface_alt_color → --netz-surface-alt`, `surface_elevated_color → --netz-surface-elevated`, `border_color → --netz-border`, `text_primary → --netz-text-primary`. A tenant with misconfigured branding can override the entire surface hierarchy, breaking token governance. There is no validation that tenant-provided colors maintain sufficient contrast ratios or surface differentiation.

### HC3 — StatusBadge fallback masks unknown states

`StatusBadge.svelte` auto-infers severity from a token set. Any status string not in the known sets falls to `neutral` (gray). This means a new backend state introduced without updating the frontend resolver will silently render as a gray badge — technically correct but informationally vacant. The component never warns about unrecognized states.

### HC4 — Wealth's 12-item TopNav at scale

Wealth renders 12 top-level nav items in `TopNav`. At `< 768px`, these collapse into a hamburger drawer. But even at desktop widths, 12 text items in a horizontal nav creates density pressure. As Wealth adds features (backtest, content, exposure were recent additions), the nav will need restructuring. The built-but-unused `Sidebar.svelte` is the intended solution, but the migration path is not documented.

---

## Missing Critical Embodiment

### ME1 — No AI provenance badge or marker in generated content

The doctrine (SS17) requires that users can distinguish "raw evidence" from "model inference" and "generated narrative." The backend tracks model version, classification layer, confidence scores, evidence pack hashes, and critic iterations. None of this is surfaced inline with generated content in the frontend. Memo chapters and DD report sections render as undifferentiated markdown. There is no "AI-generated" watermark, no confidence indicator, no "view sources" inspector, and no classification transparency in the document review UI.

### ME2 — No investor-facing page archetype distinction

The doctrine (SS21) requires that "investor-facing pages must feel cleaner and calmer than internal operational pages, but still belong to the same system." The `InvestorShell` provides a minimal shell (logo + org name + sign out). But investor pages themselves (`/investor/documents`, `/investor/statements`, `/investor/report-packs`, `/investor/fact-sheets`, `/investor/inv-portfolios`, `/investor/inv-dd-reports`) use the same Card/DataTable/StatusBadge components as internal pages. There is no visual differentiation between internal operational surfaces and investor-facing read-only surfaces beyond the shell change.

### ME3 — No review-page archetype standardization

The doctrine (SS21) specifies that "review pages must surface status, responsibility, checklist logic, and decision controls without ambiguity." The Credit document review page (`reviews/[reviewId]/+page.svelte`) implements this with status badge, approval bar, role-gated actions, and rationale requirements. But there is no standardized `ReviewPage` pattern or shared component — each review flow (document review, DD report approval, universe approval) implements its own layout with varying levels of friction and structure.

### ME4 — Dark mode not tested end-to-end

The doctrine (SS22) requires "deliberate component-level adjustment" for dark mode. Token-level dark mode exists (`[data-theme="dark"]` in `tokens.css`), shadow adaptation exists (`shadows.css`), and a theme toggle hook exists (`theme.ts`). But there is no evidence of dark mode testing, screenshots, or validation across the full page surface. Token inversion does not guarantee that all components maintain contrast, readability, and surface differentiation in dark mode. Sign-in pages with hardcoded hex colors will partially break in dark mode.

---

## Structural Risks

### SR1 — Wealth state management is stringly-typed

Wealth's core workflow states (`DDReport.status`, `UniverseApproval.decision`) are bare string fields with no enum constraint. The server_default provides an initial value, but transitions are enforced only by application code. A raw SQL update or an API bug could set `status = 'approvd'` without any validation layer catching it. Credit's enum-based approach provides compile-time safety that Wealth lacks.

### SR2 — Approval gravity gap creates operational risk

DD report approval (investor distribution, regulatory implications) uses `ConfirmDialog` (simple OK/Cancel). Deal stage transition (internal workflow) uses `ConsequenceDialog` (rationale + typed confirmation + consequence metadata). The approval with higher real-world impact has lower UI friction. If a DD report is accidentally approved, the only recourse is setting `rejection_reason` after the fact.

### SR3 — Provenance endpoints exist but are not consumed

`/ai-provenance`, `/ic-memo/timeline`, and `/decision-audit` endpoints are implemented and tested. But no frontend page renders their data. These endpoints represent backend investment that is not delivering value to users. The longer they go unconsumed, the higher the risk of them drifting from the frontend's data contract.

### SR4 — Token override via branding without validation

Tenant branding can override all core surface and text tokens. Without contrast ratio validation, a tenant could configure `text_primary: #ffffff` and `surface_color: #fefefe`, making text invisible. The system trusts tenant configuration completely.

---

## Overall Verdict

The Netz Analysis Engine's design system is **structurally sound and architecturally mature at the token and component level**. The CSS token system (tokens, spacing, typography, shadows, animations) is comprehensive and well-structured. Shared components are institutional-grade — `ConsequenceDialog`, `AuditTrailPanel`, `StatusBadge`, `LongRunningAction` encode system logic, not just visual styling. Cross-vertical consistency is excellent: both frontends share foundations via `@netz/ui` with zero visual fragmentation. Formatter discipline is near-perfect.

**The system's primary weakness is a presentation gap between backend provenance and frontend visibility.** The backend tracks classification layers, confidence scores, model versions, evidence pack hashes, critic iterations, and full decision audit trails — institutional-grade provenance infrastructure. Almost none of this reaches the user. Memo chapters and DD reports render as undifferentiated markdown. The doctrine's central demand — "make intelligence feel auditable" — is satisfied architecturally but not yet in the interface.

**Secondary weaknesses are operational:** Wealth's stringly-typed workflow states lack enum safety. Approval gravity is inverted (internal stage moves have more friction than investor-facing approvals). ESLint enforcement exists on paper but not in CI. Built layout infrastructure (Sidebar, AppShell, ContextPanel) sits unused.

The token and component foundation is ready for the next stage of the doctrine — surfacing provenance, standardizing review-page archetypes, and activating the structural layout infrastructure that is already built.
