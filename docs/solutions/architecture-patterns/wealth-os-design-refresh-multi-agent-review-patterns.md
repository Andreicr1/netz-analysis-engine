---
title: "Wealth OS Frontend Design Refresh — Multi-Agent Development & Review Patterns"
date: 2026-03-17
module: frontends/wealth + packages/ui + backend/app/domains/wealth
severity: mixed
tags:
  - dark-theme
  - navigation-refactor
  - institutional-components
  - svelte5
  - multi-agent-development
  - code-review-patterns
  - discriminated-union
  - token-system
  - fouc-prevention
  - sse
related_issues:
  - "PR #52: feat(wealth): Frontend Design Refresh + Senior Analyst Engines"
  - "docs/plans/2026-03-16-feat-wealth-frontend-figma-design-refresh-plan.md"
  - "docs/plans/2026-03-17-feat-wealth-senior-analyst-engines-plan.md"
---

# Wealth OS Frontend Design Refresh — Multi-Agent Development & Review Patterns

## Problem Statement

The Wealth OS frontend was a functional prototype: light-only theme, vertical Sidebar stealing 240px, generic DataCard components, and two missing pages (Exposure Monitor, Screener). The system needed to become an institutional-grade product with dark theme, horizontal TopNav, domain-semantic components, and all 7 Figma frames implemented — across 99 files and +13K lines.

The challenge was not just the code volume but the coordination: 8 phases of work, 4 parallel page implementations, 7 parallel review agents, and 14 findings to resolve — all in a single session.

## Root Cause Analysis

Four compounding problems made the prototype feel generic:

1. **Light-only theme with no token system.** Hard-coded `bg-white`, `text-gray-*`, and raw hex values scattered across 28+ files. No semantic token layer.
2. **Vertical Sidebar consuming 240px.** Institutional dashboards need maximum data density; a permanent sidebar makes every panel cramped.
3. **Generic DataCard components.** Data-agnostic components cannot express domain semantics (utilization bars, regime banners, typed alert feeds).
4. **Missing pages.** Exposure Monitor and Screener had backend engines (Sprints 1-5) but no frontend.

## Solution

### Architecture: Two Orthogonal Navigation Levels

The Sidebar was replaced with two components serving distinct roles:

- **TopNav** (full-width, 52px): Global section navigation (Dashboard, Portfolios, Risk, etc.). Always visible. Text items, no icons. Active = border-bottom.
- **ContextSidebar** (220px, optional): Entity-level navigation on detail pages (`/funds/[fundId]`, `/model-portfolios/[portfolioId]`). Only rendered when `contextNav` prop is passed to AppLayout.

This recovers 240px on list pages while adding contextual navigation on detail pages.

### Dark Theme: Token System + FOUC Prevention

```
tokens.css
├── :root { /* light defaults */ }
└── [data-theme="dark"] { /* dark overrides */ }

↓ Runtime

data-theme attribute on <html>
  → Wealth defaults to "dark", credit defaults to "light" (no attribute)
  → injectBranding() overlays admin token values on top
  → Components consume via var(--netz-*)
```

FOUC prevention requires TWO mechanisms:
1. **Inline `<script>` in `<head>`** — reads cookie/localStorage synchronously before first paint
2. **`transformPageChunk` in hooks.server.ts** — injects `data-theme` into SSR HTML

Both must validate against allowlist (`"dark"` | `"light"`) to prevent injection.

### Institutional Components (7 new)

| Component | Purpose | Key Pattern |
|-----------|---------|-------------|
| `MetricCard` | Financial KPI with limit context | 3px status border, UtilizationBar inline, delta with direction |
| `UtilizationBar` | Current vs limit bar | Status derived internally: <0.8=ok, <1.0=warn, ≥1.0=breach |
| `RegimeBanner` | Conditional full-width regime alert | Renders nothing when RISK_ON |
| `AlertFeed` | Typed alert stream | **Discriminated union** WealthAlert (not flat type with `meta: unknown`) |
| `SectionCard` | Consistent section wrapper | Title + subtitle + actions snippet + collapsible |
| `HeatmapTable` | HTML table with colored cells | NOT ECharts — plain HTML with `color-mix()` intensity |
| `PeriodSelector` | Compact period button group | 1M/3M/YTD/1Y/3Y with typed selection |

### WealthAlert Discriminated Union (Critical Design Decision)

```typescript
// ✅ CORRECT: Each type carries its own payload shape
type WealthAlert =
  | { type: "cvar_breach"; portfolio: string; utilization: number; ts: Date }
  | { type: "behavior_change"; instrument: string; severity: "LOW"|"MEDIUM"|"HIGH"|"CRITICAL"; changed_metrics: string[]; ts: Date }
  | { type: "dtw_drift"; instrument: string; drift_score: number; ts: Date }
  | { type: "regime_change"; from: string; to: string; ts: Date }
  | { type: "universe_removal"; instrument: string; affected_portfolios: string[]; ts: Date };

// ❌ WRONG: Flat type with generic meta
type WealthAlert = {
  type: string;
  title: string;
  description: string;
  severity: string;
  meta?: Record<string, unknown>;  // Requires casting at every render site
};
```

## Multi-Agent Review: What 7 Agents Found That Humans Missed

14 findings across 7 specialized review agents. Key insight: **agents produce structurally correct code that fails on integration contracts.** The code compiles, types check, but wiring is wrong.

### P1 Findings (Blocked Merge)

| Finding | Agent | Root Cause |
|---------|-------|------------|
| Migration 0013 `down_revision="0011"` skips 0012 | data-integrity-guardian | Alembic chain gap → `upgrade head` fails |
| Exposure router double `/wealth` prefix → 404 | architecture-strategist | Inconsistent router mount pattern |
| Frontend calls `/wealth/analytics/strategy-drift/` but route has no `/wealth` prefix | pattern-recognition | Route path mismatch between frontend loader and backend mount |
| `--netz-primary` referenced 30+ times but undefined in tokens.css | **Manual review (human)** | Agents generated code using token names that don't exist |

### P2 Findings

| Finding | Agent | Fix |
|---------|-------|-----|
| Advisory lock cross-tenant collision | security-sentinel | `pg_try_advisory_xact_lock` (auto-release) |
| Theme cookie XSS via attribute injection | security-sentinel | Allowlist validation before HTML interpolation |
| FK `ondelete` mismatch migration vs ORM | data-integrity-guardian | Add `ondelete="RESTRICT"` to migration |
| N+1 staleness query (1 SELECT per block) | performance-oracle | Single `GROUP BY` query |
| Redundant re-scan + O(N*M) lookup | code-simplicity-reviewer | `all_results` field on scan result |
| closePanel timeout race condition | performance-oracle | Clear timeout ref on openPanel |
| Dashboard SSE never wired | **Manual review (human)** | `createSSEStream` + 50-entry cap |

### What Human Review Caught That Agents Missed

Two findings were invisible to all 7 review agents:

1. **`--netz-primary` undefined (30+ refs)** — agents check syntax, not whether a CSS variable resolves. This requires a token audit that cross-references `var(--netz-*)` usage against the token definition file.
2. **Dashboard SSE not wired** — agents verified the AlertFeed component works, but no agent checked the end-to-end data flow from SSE → state → component.

## Prevention: Checklist for Future Multi-Agent Frontend Work

### Phase 0 — Lock Contracts Before Delegation

- [ ] Token file complete and committed — agents import, never define
- [ ] Route manifest written — every path, auth guard, data shape
- [ ] Shared component inventory — agents use, never create duplicates
- [ ] SSE reference implementation committed with inline comments
- [ ] API contract types committed before frontend work begins

### Common Agent Failure Modes

| Failure Mode | Prevention |
|---|---|
| Undefined CSS tokens | Provide token file path in every prompt |
| Missing SSE wiring | Include SSE requirement explicitly per page |
| Route path mismatch | Provide route manifest before delegation |
| Duplicate components | Lock component inventory before delegation |
| Wrong import paths | Include `tsconfig.json` aliases in context |

### Effective Review Agent Specialization

Generalist "review this page" agents produce shallow findings. Specialist agents find real integration failures:

1. **Token audit agent** — scans `.svelte` files for values not in token file
2. **SSE audit agent** — verifies real-time pages have live subscriptions
3. **Route audit agent** — diffs every `href`/`goto()` against SvelteKit file tree
4. **Component dedup agent** — checks for local duplicates of `@netz/ui` components
5. **Backend contract agent** — verifies every `fetch()` maps to a real FastAPI route

## Key Patterns Worth Preserving

- **Discriminated unions for domain types** — prevents `meta: unknown` casting that makes TypeScript safety meaningless at render time
- **Theme via `<head>` cookie script** — only FOUC-free pattern for SSR; `localStorage` in `onMount` always flashes
- **`pg_try_advisory_xact_lock` over session locks** — auto-releases on commit/rollback, cannot leak across pooled connections
- **Backward-compat alias tokens** (`--netz-primary: var(--netz-brand-primary)`) — incremental migration without big-bang rename
- **Allowlist before cookie/localStorage write** — two-line guard that eliminates entire injection class

## Key Lesson

> The multi-agent approach compresses calendar time but does not reduce total review work — it shifts review from serial to parallel. The review cost is fixed by the number of integration contracts (tokens, routes, SSE, components, backend). The only way to reduce review cost is to lock those contracts before delegation, not after. Every undefined contract at delegation time becomes one or more review findings at integration time.
