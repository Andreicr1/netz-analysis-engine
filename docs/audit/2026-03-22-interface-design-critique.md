# Interface Design Critique — 2026-03-22

Applied against `/interface-design` skill principles + Ousterhout's "A Philosophy of Software Design" evaluation criteria.

---

## The Question This Critique Answers

If a design lead reviewed these three frontends, not asking "does this work?" but "would I put my name on this?" — what would they say?

---

## 1. Product Domain: Was It Explored?

The interface-design skill mandates: **before any visual decision, explore the product's world. Name 5 domain concepts, 5 colors from that world, 1 signature element, 3 defaults to reject.**

### What Netz's World Actually Is

This is an **institutional investment analysis engine**. The humans using it are:
- Portfolio managers reviewing fund allocations at 7am with Bloomberg on a second screen
- Credit analysts running due diligence on private debt deals, cross-referencing SEC filings
- Wealth ops teams screening 5000+ managers against mandate constraints
- CIOs reviewing macro regime indicators before an investment committee meeting

Their world has specific textures: the matte black of a Bloomberg terminal, the off-white of a printed prospectus, the green/red of P&L, the density of a risk report, the precision of basis points. These people live in data. They read 14-column tables for breakfast.

### What the Tokens Actually Say

```css
--netz-brand-primary: #18324d;    /* "Navy" */
--netz-brand-highlight: #c58757;  /* "Orange" */
--netz-surface: #f4f7fb;          /* "Light blue-gray" */
```

Token names: `--netz-brand-primary`, `--netz-surface-elevated`, `--netz-border-subtle`. These are **generic infrastructure names**. They could belong to a project management tool, a CRM, a fintech checkout, a SaaS dashboard. Nothing says "institutional investment."

**The Token Test (FAIL):** Read the CSS variables out loud. "Netz brand primary. Netz surface elevated. Netz border subtle." Could someone identify this as an investment analysis platform? No. These names describe structure, not domain.

Compare what domain-aware tokens would sound like:
```
--desk-surface       (trading desk metaphor)
--prospectus-bg      (document origin)
--ink-primary        (authority, precision)
--ticker-mono        (financial data)
--regime-caution     (macro regime state)
```

### Verdict: No Domain Exploration Happened

The color palette (#18324d navy + #c58757 orange) is a respectable financial-adjacent palette, but it wasn't derived from the product's world — it was applied to it. The navy could be any enterprise product. The orange could be any warm accent. Nothing about the visual language screams "this is where institutional capital decisions happen."

**This is the skill's first warning: "If you cannot answer these with specifics, stop."**

---

## 2. The Swap Test

> "If you swapped the typeface for your usual one, would anyone notice? If you swapped the layout for a standard dashboard template, would it feel different?"

### Typography: PARTIAL PASS

Inter Variable is a reasonable choice for data-heavy interfaces (tabular figures, clean x-height). But Inter is the **most common AI-generated interface font**. It's the default of defaults. The skill says: "If you're reaching for your usual font, you're not designing."

JetBrains Mono for data is a stronger choice — it signals technical precision. But the combination Inter + JetBrains Mono is the exact combo you'd find in a Vercel dashboard clone.

The typography hierarchy itself (tracking-[-0.03em] for h1, tracking-[0.08em] for labels) is well-executed. But swap Inter for Geist, Public Sans, or DM Sans and the interface wouldn't feel different. **The typeface isn't doing identity work.**

For an institutional investment platform, consider: a slightly more authoritative sans (Söhne, Graphik, or even a humanist like Source Sans Pro for warmth) paired with a data-optimized mono (Tabular, Berkeley Mono). The type should feel like it belongs in a boardroom, not a dev tools dashboard.

### Layout: FAIL

The Wealth dashboard layout is: header + 3 card grid + 2-column section below. This is the **most common dashboard template in existence**. Swap in any other SaaS dashboard and the structure is identical. The skill calls this out explicitly: "Same sidebar width, same card grid, same metric boxes with icon-left-number-big-label-small every time — this signals AI-generated immediately."

The Credit frontend uses TopNav (3 items) + ContextSidebar (220px) + main content — a more distinctive pattern, but still generic.

**Nothing about the layout communicates "investment analysis."** A Bloomberg terminal has information density that communicates purpose. A Reuters Eikon has panel-based layouts that say "configure your workspace." Even Morningstar uses a distinctive card-heavy layout with specific hierarchy for fund data. Netz looks like any Tailwind admin template.

### Color: PARTIAL PASS

The navy (#18324d) + orange (#c58757) palette has personality. It's not the default blue+gray. But swap it for Stripe's blue+purple or Linear's blue+violet and the interface wouldn't feel more or less like an investment tool. The colors don't carry domain meaning.

The semantic colors (green/amber/red for success/warning/danger) follow industry convention, which is correct — these are universal signals. But the brand palette doesn't reinforce the domain.

---

## 3. The Squint Test

> "Blur your eyes. Can you still perceive hierarchy? Is anything jumping out harshly?"

### Dark Mode: FAIL

Squinting at the dark mode screenshots:
- Page background (#0f1826): dark navy blob
- Cards (#19273a): barely distinguishable dark navy blob
- Borders (#223146): faintly visible lines

**The hierarchy collapses.** Cards don't separate from background. The 4% luminance delta between surface levels is below the perceptual threshold for most monitors. The careful shadow system (shadow-1 through shadow-5) is essentially invisible on dark backgrounds because `rgba(0,0,0,0.28)` on a `#0f1826` background has almost no visible edge.

The skill's principles state: "Squint at your interface. You should still perceive the hierarchy — what's above what, where regions begin and end." In dark mode, you cannot.

### Light Mode: PASS (when working)

The light mode tokens (#f4f7fb bg, #ffffff cards, #d6deea borders) create clear hierarchy. White cards on light gray background with visible borders — the squint test passes. But as documented in the UX audit (F1), users may never see this because the ThemeToggle defaults to dark.

---

## 4. The Signature Test

> "Can you point to five specific elements where your signature appears? Not 'the overall feel' — actual components."

### Candidate Signatures Found

1. **MetricCard left accent bar** — 3px colored left border for status (ok/warn/breach). This is the strongest signature element. It's efficient, institutional, and distinctive.

2. **StatusBadge 14% opacity tint** — `color-mix(in srgb, ${color} 14%, transparent)` creates ultra-restrained badges. More subtle than most badge implementations. Institutional restraint.

3. **Button Y-axis translation** — Hover lifts 1px (`-translate-y-px`) + shadow deepens. Active presses back. Tactile, physical-object feedback. Distinctive interaction pattern.

4. **SectionCard collapsible header** — Header with `bg-surface-highlight` (4% brand tint) + chevron rotation. Good organizational tool for dense data.

5. **Double-ring focus** — `0 0 0 1px border-focus, 0 0 0 4px focus-ring`. Two-layer focus indicator. Accessibility-first, visually refined.

### Assessment

These are **craft signatures**, not **product signatures**. They demonstrate technical skill in component design but don't communicate "investment analysis platform." The MetricCard accent bar comes closest — it evokes the visual language of a Bloomberg terminal or risk dashboard. But it's used in one component, not as a pervasive design language.

A true product signature might be: a regime-aware color shift across the entire interface (when macro regime is "risk-off," the entire palette subtly shifts toward caution tones), or a data-density toggle that switches between executive summary and analyst detail views, or a consistent "confidence indicator" visual pattern that appears everywhere evidence quality matters.

**The Signature Test: PARTIAL PASS.** Craft signatures exist but product signatures don't.

---

## 5. Depth Strategy: One Approach or Mixed?

The skill mandates: **"Choose ONE depth approach and commit."** Options: borders-only, subtle shadows, layered shadows, or surface color shifts.

### Current State: Mixed (3 strategies simultaneously)

1. **Layered shadows** — Card.svelte uses shadow-2 (multi-layer). Button uses shadow-1 → shadow-2 on hover. Dialog uses shadow-4. This is a sophisticated 5-level shadow system.

2. **Border definition** — All surfaces also have `1px solid var(--netz-border-subtle)`. Borders do structural work alongside shadows.

3. **Surface color shifts** — DataTable rows use background color change (not shadow) for hover/expanded states. SectionCard header uses `bg-surface-highlight`.

In light mode, this combination works because shadows are visible and borders reinforce structure without being redundant. **But in dark mode, shadows become invisible**, leaving only borders and surface shifts. The system effectively has **two different depth strategies** depending on theme.

### Assessment: CONDITIONAL PASS

The layered shadow system is well-crafted. But it doesn't degrade to dark mode gracefully because the dark shadow values (`rgba(0,0,0,0.28)` on `#0f1826`) lack visible contrast. The skill says for dark mode: "Shadows are less visible on dark backgrounds — lean on borders for definition."

The system should recognize this: in dark mode, **promote borders to primary depth mechanism** and increase border contrast. The shadows can remain as supplementary. Currently the dark mode borders (#223146 on #19273a) are too subtle to carry the structural weight that invisible shadows leave behind.

---

## 6. Controls: Custom or Native?

The skill mandates: **"Never use native form elements for styled UI."** Native `<select>` renders OS-native dropdowns that cannot be styled.

### Current State: FAIL

`Select.svelte` uses `<select>` with `appearance-none`:
```svelte
<select class="... appearance-none ... pr-10 ...">
```

This strips the native chrome but adds **no custom dropdown indicator**. The `pr-10` (40px right padding) reserves space for a chevron that doesn't exist. Result: a blank rectangle.

The skill explicitly says: "Build custom components — trigger buttons with positioned dropdowns, calendar popovers, styled state management." The project has `DropdownMenu` (via bits-ui) but doesn't use it for the Select component.

Some pages also use raw `<select>` elements (without even the Select wrapper), particularly in the admin health page worker filters and DataTable pagination.

### Recommendation

Replace `Select.svelte` with a custom trigger-button + positioned dropdown pattern. bits-ui already provides the primitives (`Select.Root`, `Select.Trigger`, `Select.Content`, `Select.Item`). This gives full style control, consistent chevron indicator, dark mode compatibility, and keyboard navigation.

---

## 7. Navigation: Screens Grounded or Floating?

The skill says: "A data table floating in space feels like a component demo, not a product."

### Wealth OS: GROUNDING PROBLEM

With 12 items in the TopNav and no sidebar, the Wealth OS interface lacks **hierarchical grounding**. Every page is a peer of every other page. There's no spatial model — no sense of "I'm inside the Screener section" or "I'm in the Analytics workspace." Pages appear and disappear without contextual framing.

Compare with Credit: TopNav (3 items, module level) + ContextSidebar (fund-scoped detail nav). When you're in a fund's pipeline, you know where you are: the sidebar tells you. The breadcrumb tells you. The fund name is visible. You're grounded.

Wealth OS pages float. You go to `/instruments` and see a table. You go to `/screener` and see a different table. You go to `/funds` and see another table. No sidebar tells you where these relate to each other. No breadcrumb shows the hierarchy. No spatial model communicates that Instruments, Funds, and Screener are **related views of the same domain** (which they are — see UX audit F3).

### Admin: ADEQUATE GROUNDING

5 nav items (Health, Inspect, Tenants, Config, Prompts) with tenant detail pages having inline sub-navigation. The admin panel is simple enough that flat navigation works.

---

## 8. Empty States: Content Coherence

The critique reference says: "Content incoherence breaks the illusion faster than any visual flaw."

### Current State: WEAK

Dashboard shows "Awaiting data..." with three empty card placeholders. No skeleton animation. No progressive disclosure. No guidance on what to do next.

Documents page shows "No Documents" with "Upload documents to start the ingestion pipeline." — generic. The pipeline is a backend concept, not a user concept. Users don't think in terms of "ingestion pipelines" — they think "I need to analyze this fund's prospectus."

Drift Alerts shows "No active drift alerts" with "Risk alerts will appear here when detected by the analysis engine." — passive, informational. Doesn't tell the user what would trigger an alert or whether the system is actively monitoring.

### Recommendation

Empty states should be domain-specific and action-oriented:
- "Awaiting data..." → "No portfolios configured. Create your first model portfolio to see performance metrics here."
- "Upload documents..." → "Upload a fund prospectus, DDQ, or financial statement to start analysis."
- "No active drift alerts" → "Monitoring 0 portfolios for style drift. Add portfolios to enable drift detection."

---

## 9. Ousterhout's "Philosophy of Software Design" Evaluation

### 9.1 Interface Simplicity

**@netz/ui exports 56 components.** That's a large surface area. But many are necessary for the domain (DataTable, MetricCard, StatusBadge, ConsequenceDialog, AuditTrailPanel, etc.).

**Issue: Shallow components.** Several components are thin wrappers that add minimal abstraction:

| Component | Implementation | Interface Simplicity Score |
|-----------|---------------|--------------------------|
| `Input.svelte` | 22 lines. Wraps `<input>` with CSS class + cn() | **Shallow** — nearly zero abstraction over native |
| `Textarea.svelte` | 22 lines. Wraps `<textarea>` with CSS class | **Shallow** — same |
| `Select.svelte` | 50 lines. Wraps `<select>` with options mapping | **Shallow** — appearance-none without replacement |
| `Card.svelte` | 15 lines. Wraps `<div>` with `.netz-ui-surface` class | **Shallow** — could be a CSS class, not a component |
| `Badge.svelte` | 35 lines. Wraps `<span>` with variant classes | **Shallow** — Tailwind class string |

These violate Ousterhout's principle: "Large interface with thin implementation = shallow module (avoid)." A `Card` component that's just `<div class="netz-ui-surface">` provides no meaningful abstraction. It makes the interface larger (another import to learn) without hiding complexity.

**Contrast with deep components:**

| Component | Implementation | Interface Simplicity Score |
|-----------|---------------|--------------------------|
| `DataTable.svelte` | 280+ lines. TanStack table, sort, filter, pagination, expand, export | **Deep** — significant complexity hidden |
| `ConsequenceDialog.svelte` | 100+ lines. Decision flow, rationale capture, audit trail | **Deep** — workflow hidden behind simple API |
| `NetzApiClient` | SSE, polling, auth refresh, optimistic mutations | **Deep** — network complexity hidden |
| `MetricCard.svelte` | 80+ lines. Status coloring, delta arrows, sparkline slot | **Medium** — some visual logic hidden |

**Recommendation:** Consider eliminating shallow components (Input, Textarea, Card) and replacing with CSS utility classes. Or make them deeper by adding meaningful behavior (validation, masking, auto-resize).

### 9.2 General-Purpose vs Over-Specific

**Good general-purpose design:**
- `DataTable` accepts any column configuration + custom cell renderers + expandable rows. Highly reusable.
- `SectionCard` works for any collapsible content section. Title + optional actions snippet + children. Clean interface.
- `ActionButton` adds loading state to any action. Simple wrapper with high reuse.

**Over-specific components that should be more general:**
- `MetricCard` has hardcoded status types (`ok | warn | breach`) and specific border color mapping. Should accept arbitrary accent color + let the caller decide semantics.
- `RegimeBanner` has hardcoded regime tones. Should be a general `AlertBanner` with configurable severity.
- `PortfolioCard` (wealth-specific) is too specific for @netz/ui — should live in the wealth frontend, not the shared package.

**Under-general — missing components:**
- No `Combobox` (searchable select with autocomplete). Critical for selecting from 5000+ managers/instruments.
- No `FilterBar` component for composable filter blocks. Each page builds its own filter UI ad hoc.
- No `VirtualList` wrapper. The Screener page imports `@tanstack/svelte-virtual` directly instead of through a shared component.

### 9.3 Implementation Efficiency

**The interface shape of Select forces inefficiency.** Because Select uses native `<select>`, it cannot support:
- Search/autocomplete (critical for 5000+ item lists)
- Multi-select
- Custom option rendering (showing AUM, status badge inline with fund name)
- Grouped options
- Loading states (async option fetching)

Every page that needs these features must build its own solution or use bits-ui primitives directly, defeating the purpose of the shared component library.

**DataTable's interface is efficient.** It accepts columns, data, and optional overrides. The TanStack table abstraction is well-chosen — it handles sorting, filtering, and pagination internally while exposing customization points (cell renderers, filter bar snippet, expanded row snippet).

### 9.4 Depth Analysis Summary

| Component | Interface Size | Implementation Size | Depth Rating |
|-----------|---------------|-------------------|-------------|
| DataTable | Small (columns + data + options) | Large (280+ lines, TanStack integration) | **Deep** |
| ConsequenceDialog | Small (title + consequences + onConfirm) | Medium (decision flow, rationale, audit) | **Deep** |
| NetzApiClient | Small (get/post/stream methods) | Large (SSE, auth, retry, optimistic) | **Deep** |
| AppLayout | Small (navItems + children) | Large (theme, branding, session, conflict) | **Deep** |
| TopNav | Small (items + trailing) | Medium (mobile drawer, active state, scroll) | **Medium** |
| MetricCard | Medium (7 props) | Medium (color logic, delta, sparkline) | **Medium** |
| SectionCard | Small (title + children) | Medium (collapse, chevron, header styling) | **Medium** |
| Button | Medium (variant + size + disabled + asChild) | Small (CSS classes only) | **Shallow** |
| Input | Small (value + placeholder) | Tiny (CSS class wrapper) | **Shallow** |
| Card | Tiny (children + class) | Tiny (CSS class) | **Very Shallow** |
| Select | Small (value + options) | Small (native select wrapper) | **Shallow** |
| Badge | Small (variant + children) | Tiny (CSS class mapping) | **Shallow** |

---

## 10. Composition and Rhythm

### Dashboard Layout Rhythm: MONOTONE

The skill's critique reference says: "Great interfaces breathe unevenly — dense tooling areas give way to open content." The Wealth dashboard is monotonous:

```
[Banner — full width, same density]
[Card] [Card] [Card] — same size, same padding, same structure
[Section — 60%] [Section — 40%] — different width but same internal density
[Section — full width] — same density again
```

Every section has the same padding (20px), the same border treatment, the same gap between items. There's no rhythm — no dense area giving way to open space, no heavy element balanced by a light one.

### Proportions: NOT DOING WORK

The skill says: "A 280px sidebar next to full-width content says 'navigation serves content.' A 360px sidebar says 'these are peers.'"

Credit's ContextSidebar is 220px — navigation serves content. This is a deliberate proportion.

Wealth's 60/40 split between Drift Alerts and Quick Actions — what does this say? That drift alerts are 50% more important than quick actions? The proportion doesn't communicate meaning. It's a layout decision, not a design decision.

### Focal Point: MISSING

The skill says: "Every screen has one thing the user came here to do. That thing should dominate."

What does the Wealth dashboard user come to do? Check portfolio health. But the portfolio cards (the most important element) are a uniform 3-column grid at the same visual weight as the drift alerts and quick actions below. Nothing dominates. The eye has no entry point. The page is a **parking lot** — everything at the same importance.

---

## 11. Sameness Assessment

> "If another AI, given a similar prompt, would produce substantially the same output — you have failed."

### Verdict: The Wealth frontend would pass the sameness test. The Credit frontend would partially fail.

If you prompted "build a SaaS dashboard with navy/orange palette, dark mode, data tables, metric cards" — the output would be recognizably similar to Wealth OS. The horizontal nav, 3-column card grid, data tables with status badges, collapsible sections — all standard patterns.

Credit has slightly more identity through the ContextSidebar pattern and the pipeline Kanban board. But the individual components (cards, tables, badges) are interchangeable with the Wealth frontend.

**The frontends lack product identity.** They are well-crafted infrastructure — professionally executed tokens, consistent components, sophisticated shadows — but they don't communicate "institutional investment analysis" through their structure or visual language.

---

## 12. Summary: What the Design Lead Would Say

"The engineering is solid. The token architecture is professional. The component system is consistent. The shadow layering shows real craft.

But I wouldn't put my name on this yet.

The dark mode doesn't work — I can't see the cards. The navigation is a dump of 12 links with no hierarchy. There are 6 pages that should be one Screener. The Select component has no dropdown indicator. And when I step back and squint, I see a well-built template, not a product designed for investment professionals.

The infrastructure is ready. The identity isn't."

---

## Prioritized Action Items

### Tier 1: Broken (must fix)
1. Dark mode surface contrast — cards invisible (F1/F5 from UX audit)
2. Select component — add chevron indicator or rebuild as custom component (F4)
3. Page consolidation — merge Funds/Instruments/Universe/ESMA into Screener tabs (F3)
4. Nav reduction — 12 items → 7 max (F2)

### Tier 2: Missing Identity (should fix)
5. Establish product signature — regime-aware color shifts, data-density toggle, confidence indicators
6. Dashboard focal point — portfolio health should dominate, not share equal weight with quick actions
7. Empty states — domain-specific, action-oriented
8. Navigation grounding — add sidebar or breadcrumb hierarchy to Wealth pages

### Tier 3: Polish (nice to fix)
9. Token naming — consider domain-evocative names alongside infrastructure names
10. Shallow components — either deepen (add behavior) or eliminate (use CSS classes)
11. Dashboard rhythm — break monotonous card density with varying section treatments
12. Typography identity — evaluate whether Inter is the right choice for institutional finance

---

## Files Analyzed

| Category | Files |
|----------|-------|
| Token system | `packages/ui/src/lib/styles/tokens.css`, `spacing.css`, `shadows.css`, `typography.css`, `animations.css`, `index.css` |
| Layout components | `AppLayout.svelte`, `TopNav.svelte`, `ContextSidebar.svelte`, `PageHeader.svelte` |
| Core components | `Card.svelte`, `SectionCard.svelte`, `Button.svelte`, `Input.svelte`, `Select.svelte`, `Dialog.svelte`, `DataTable.svelte` |
| Data components | `MetricCard.svelte`, `DataCard.svelte`, `StatusBadge.svelte`, `Badge.svelte`, `EmptyState.svelte` |
| Feedback components | `Toast.svelte`, `RegimeBanner.svelte`, `ThemeToggle.svelte` |
| Wealth pages | `dashboard/+page.svelte`, `screener/+page.svelte`, `funds/+page.svelte`, `instruments/+page.svelte`, `universe/+page.svelte` |
| Credit pages | `dashboard/+page.svelte`, `pipeline/+page.svelte`, `portfolio/+page.svelte` |
| Admin pages | `health/+page.svelte`, `inspect/+page.svelte`, `tenants/+page.svelte` |
| Frontend layouts | `frontends/wealth/src/routes/+layout.svelte`, `frontends/credit/src/routes/+layout.svelte`, `frontends/admin/src/routes/+layout.svelte` |
