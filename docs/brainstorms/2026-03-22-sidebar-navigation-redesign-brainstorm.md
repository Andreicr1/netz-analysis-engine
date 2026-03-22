# Brainstorm: Sidebar Navigation Redesign

**Date:** 2026-03-22
**Status:** Ready for planning
**Author:** Andrei + Claude

## What We're Building

Migrate the Netz Analysis Engine frontends from horizontal TopNav navigation to a collapsible Sidebar with hierarchical tree navigation. This transforms the UI from a "web page" feel to a "native analytical workstation" feel — aligned with the product's positioning as Executive Analytical Software.

### Current State

- `AppLayout` wraps `TopNav` (60px horizontal bar) + optional `ContextSidebar` (220px, detail pages only)
- Credit has 8+ sections, Wealth has 10+, Admin has 6+ — TopNav already uses `overflow-x: auto` and hamburger drawer on mobile
- `AppShell` and `Sidebar` components exist in `packages/ui` but are **not used** in production layouts
- `ContextSidebar` appears only inside fund/portfolio detail views for sub-page navigation

### Target State

```
┌──────────────────────────────────────────────────────────────┐
│ Funds > Fund ABC > Pipeline                    [Org] [●]    │  ← TopBar (~40px)
├────────┬─────────────────────────────────────────────────────┤
│ ▶ Dash │                                                     │
│ ▼ Funds│                                                     │
│  ▼ ABC │            Page Content Area                        │
│   Pipe │            Full vertical real estate                │
│   Port │            for DataTable, Charts, Memos             │
│   Docs │                                                     │
│  ▶ DEF │                                                     │
│ ▶ Copl │                                                     │
│        │                                                     │
│ ── ── ─│                                                     │
│ [◀][▶] │                                                     │  ← Collapse toggle
└────────┴─────────────────────────────────────────────────────┘
  240px expanded / 48-56px collapsed
```

## Why This Approach

1. **Vertical real estate** — TopNav consumes 60px of vertical space on every page. Sidebar consumes 0px vertical, using horizontal space that is abundant on widescreen monitors (1920px+). For data-dense screens (DataTable with 20+ rows, IC Memos, pipeline Kanban), this is significant.

2. **Module scalability** — TopNav caps at 5-7 items before becoming polluted with dropdowns. Sidebar accommodates 10-15+ sections with clear category grouping and tree navigation. The Netz platform is growing (Credit has 8 sections, Wealth has 10+).

3. **Hierarchical navigation** — Credit's fund detail pages have deep sub-navigation (Pipeline, Portfolio, Documents, Market Data, Reporting). A tree in the sidebar replaces the ContextSidebar, eliminating a second sidebar and providing persistent context of where the user is in the hierarchy.

4. **Premium perception** — Institutional analytical software (Bloomberg, Palantir Foundry, FactSet, Refinitiv Eikon) universally uses sidebar navigation. It signals "workstation" rather than "web app".

## Key Decisions

### D1: Sidebar scope — Per frontend (not cross-vertical)

Each frontend (credit, wealth, admin) has its own sidebar with its own sections. No cross-vertical switcher. This respects the existing architecture rule: "frontends never cross-import" — all sharing happens through `@netz/ui` and the backend API. Vertical switching happens at the URL/login level.

### D2: Hierarchical tree navigation (replaces ContextSidebar)

The sidebar displays top-level sections. When the user navigates into a detail entity (e.g., Fund ABC), the sidebar tree expands to show sub-pages (Pipeline, Portfolio, Documents, etc). This eliminates the separate `ContextSidebar` component. When the sidebar is collapsed to icon-only mode, the tree is hidden — user relies on breadcrumbs for context.

### D3: Surface style — Dark surface fixa (OS Frame)

The sidebar uses a fixed dark surface (`slate-900/950`) independent of the content area theme. Even in light mode, the sidebar remains dark — creating strong visual separation between navigation chrome and workspace. This is the "OS Frame" pattern used by VS Code, Linear, Figma, and Slack. The dark sidebar signals "workstation shell" while the content area adapts to user theme preference.

**Revised 2026-03-22:** Originally chose surface-elevated (leve contraste), changed to dark surface after further consideration. The premium "native app" feel requires stronger visual separation.

### D4: Slim TopBar replaces TopNav for context

A ~40px top bar provides:
- **Left:** Breadcrumbs (e.g., `Credit > Funds > Fund ABC > Pipeline`)
- **Right:** Org switcher, regime badge, user menu, contextual actions
- **No navigation** — the top bar is purely contextual

### D5: Migration strategy — All frontends at once

Single PR that:
1. Creates `AppSidebar` and `TopBar` components in `packages/ui`
2. Refactors `AppLayout` to use sidebar + top bar instead of TopNav
3. Updates all three frontend `+layout.svelte` files
4. Migrates fund/portfolio detail layouts from ContextSidebar to tree navigation
5. Keeps `TopNav` available for `InvestorShell` (read-only investor portal)

### D6: Responsive behavior

| Breakpoint | Sidebar | TopBar | Behavior |
|---|---|---|---|
| ≥1280px (desktop) | Expanded (240px), labels + tree | Full breadcrumbs | Default working state |
| 1024-1279px | Collapsed (48-56px), icon-only | Shortened breadcrumbs | Hover/click to expand |
| 768-1023px (tablet) | Hidden, overlay on hamburger | Full, hamburger button shown | Touch-friendly overlay |
| <768px (mobile) | Hidden, overlay drawer | Compact, hamburger | Full-width overlay sidebar |

### D7: Collapse persistence

Sidebar collapse state is persisted in `localStorage` per-user. User's preference is remembered across sessions. Default: expanded on desktop.

## Components Affected

### New components (`packages/ui`)
- `AppSidebar` — Collapsible sidebar with tree navigation, tooltips in icon mode
- `TopBar` — Slim breadcrumb + actions bar
- `SidebarTree` — Recursive tree item component with expand/collapse

### Modified components (`packages/ui`)
- `AppLayout` — Swap TopNav for AppSidebar + TopBar, remove ContextSidebar integration
- `AppShell` — May be extended or replaced by new AppLayout internals

### Deprecated (kept for InvestorShell)
- `TopNav` — No longer used by main frontends, kept for investor portal
- `ContextSidebar` — Replaced by tree navigation in sidebar

### Frontend changes
- `frontends/credit/src/routes/+layout.svelte` — New nav items config with tree structure
- `frontends/credit/src/routes/(team)/funds/[fundId]/+layout.svelte` — Remove ContextSidebar, configure tree
- `frontends/wealth/src/routes/+layout.svelte` — New nav items config
- `frontends/wealth/src/routes/(team)/portfolios/[profile]/+layout.svelte` — Tree nav for portfolio sub-pages
- `frontends/admin/src/routes/+layout.svelte` — New nav items config
- All `context-nav.svelte.ts` files — Adapt or remove (tree state replaces context nav)

## Open Questions

*None — all key decisions resolved during brainstorm dialogue.*

## Out of Scope

- **Cross-vertical switcher** — Each frontend is independent. No shared app shell wrapper.
- **Command palette (cmd+k)** — Valuable but separate feature. Can be added later without affecting sidebar architecture.
- **Dark-mode-only sidebar** — Decided against forced dark surface. Using surface-elevated tokens instead.
- **InvestorShell changes** — Investor portal keeps TopNav. Different audience, different UX needs.
- **Figma mockups** — Implementation-first approach. Figma validation can happen post-implementation.
