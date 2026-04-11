# Part C Execution Brief — Terminal Shell Primitive Layer

**Date:** 2026-04-11
**Branch:** `feat/terminal-unification-part-c`
**Status:** Execution brief — ready for Opus CLI
**Depends on:** `feat/terminal-unification` merged to main (dfa8301b)

## How to execute this file

This is a standalone execution brief for the Opus CLI agent. To run it:

1. Open an Opus CLI session on branch `feat/terminal-unification-part-c`
2. Tell the agent: *"Read `docs/plans/2026-04-11-terminal-unification-part-c-prompt.md` in full and execute every instruction in it. Ship the 8 commits in order. Report per the Report Format section at the end."*
3. The agent should read all 12 files listed in "READ FIRST" before writing any code
4. The agent ships 8 atomic commits and produces a final report

Do not paraphrase this file when handing it to the agent — point the agent at the path and let it read the full contents via the Read tool. This preserves every contract detail that prior prompt-round truncation would have lost.

---

# MISSION

Ship the full Terminal Shell primitive layer in a single concentrated session. Eight atomic commits on `feat/terminal-unification-part-c`, in this exact order:

1. `feat(terminal): LayoutCage primitive — canonical 24px cage wrapper`
2. `feat(terminal): TerminalStatusBar — bottom chrome with clock, build SHA, connection LiveDot`
3. `feat(terminal): TerminalTopNav — global navigation with 8-tab vision, 3 active + 5 pending`
4. `feat(terminal): CommandPalette — Cmd+K launcher with go-to navigation commands`
5. `feat(terminal): AlertTicker — streaming alert marquee primitive`
6. `feat(terminal): TerminalContextRail — entity-scoped right rail with URL pinning`
7. `feat(terminal): TerminalShell — shell composition of all chrome primitives`
8. `chore(terminal): wire TerminalShell into (terminal)/+layout, delete TerminalGlobalNav`

This is the most contract-heavy phase of the terminal. Every component created here is mounted inside every future terminal surface (Phase 3 Screener, Phase 4 Builder, Phase 5 Live Workbench, Phase 6 DD, Phase 7 Macro, Phase 8 Research). A wrong prop contract or a wrong z-index layer propagates to every page. Slow down. Verify each commit before the next.

# PROJECT MANDATE (binding)

> Usaremos os recursos mais avançados disponíveis para dar ao sistema o máximo de performance e percepção visual de um produto high-end e high-tech, não importa quantas vezes tenhamos que retornar ao mesmo item para corrigi-lo ou quantas novas dependências devam ser instaladas. Sem economia ou desvios para simplificações.

For this session specifically:
- Every component is permanent production code, not a stub. Every interactive pattern must work end-to-end at the visual layer even when the backend endpoint is not yet wired.
- "Coming soon" is NOT acceptable shortcut. If a tab is not yet routed, render it as VISIBLY pending with explicit pending-state styling — users must see the full terminal vision from day one even when some routes are stubs.
- Use design tokens semantically (no hex, no inline durations, no inline colors). Every color, spacing, border, motion, z-index lookup goes through `var(--terminal-*)` or imported helpers.
- A11y is production-grade. Every interactive element has keyboard handling, ARIA roles, focus management. CommandPalette must be WAI-ARIA combobox-compliant (or listbox if simpler). No exceptions.
- Re-read the `FocusMode.svelte` implementation as reference. That primitive sets the quality bar — match it.

# CRITICAL CONTEXT — the shell is the foundation

After this session, the Terminal Shell is the **persistent chrome of every terminal route**. `(terminal)/+layout.svelte` mounts `TerminalShell` once; every `+page.svelte` under `(terminal)/` renders inside it via snippet children. This means:

- Any contract defect in `TerminalShell` props = every page breaks
- Any z-index mistake = overlay layers collide with FocusMode or page content
- Any layout-cage math mistake = content panels wrong-sized on every surface
- Any keyboard handler conflict = global shortcuts collide with page shortcuts

Before touching any code, you MUST understand:
1. How FocusMode positions itself above the shell (`--terminal-z-focusmode` = 60)
2. How the current `(terminal)/+layout.svelte` wraps pages today (existing offset math)
3. How the sandbox at `/sandbox/focus-mode-smoke` will inherit the new shell automatically (it's under `(terminal)/` → wrapped by the new layout → FocusMode overlay must still work correctly with z-index 60 BELOW CommandPalette at z-index 70)
4. How the Svelte 5 snippet composition pattern works (used in FocusMode's `reactor` / `rail` / `actions`, will be used here for `children` and context rail slot)

# Z-INDEX STACK (from master plan Appendix C, must be respected)

```
--terminal-z-base:        0    // page content
--terminal-z-panel:       10   // panels inside pages
--terminal-z-rail:        20   // TerminalContextRail
--terminal-z-statusbar:   30   // TerminalStatusBar
--terminal-z-dropdown:    40   // context menus, select dropdowns
--terminal-z-modal:       50   // confirmation dialogs
--terminal-z-focusmode:   60   // FocusMode (already in prod)
--terminal-z-palette:     70   // CommandPalette (must be above FocusMode so it can open inside one)
--terminal-z-toast:       80   // transient notifications
```

CommandPalette at z=70 means the palette opens ABOVE a FocusMode that is already open. This is intentional — a user in a FocusMode should still be able to Cmd+K to navigate or search without closing the focus first.

Verify these tokens exist in `packages/investintell-ui/src/lib/tokens/terminal.css` before using them. If any are missing, ESCAPE HATCH and report — do not invent z-index values.

# READ FIRST (mandatory, in this order)

1. `docs/plans/2026-04-11-terminal-unification-master-plan.md` — sections §1.4 TerminalShell + layer taxonomy, Appendix B (navigation flow), Appendix C (tokens), Appendix G (file structure)
2. `packages/investintell-ui/src/lib/tokens/terminal.css` — complete token inventory. Find the z-index tokens, motion tokens, spacing tokens you will consume.
3. `packages/investintell-ui/src/lib/charts/choreo.ts` — motion grammar. You will use `svelteTransitionFor` for every fly/fade site.
4. `frontends/wealth/src/lib/components/terminal/focus-mode/FocusMode.svelte` — quality reference. Note: runes patterns, snippet composition, `$effect` cleanup, focus trap via `queryFocusables`, WAI-ARIA dialog role.
5. `frontends/wealth/src/lib/components/terminal/focus-mode/fund/FundFocusMode.svelte` — snippet composition reference.
6. `frontends/wealth/src/lib/components/terminal/runtime/stream.ts` — `createTerminalStream<T>` signature. You will use this in AlertTicker.
7. `frontends/wealth/src/lib/components/layout/TerminalGlobalNav.svelte` — the file you are refactoring into `TerminalTopNav`. Note: current 32px height, 3 tabs (PORTFOLIOS / SCREENER / RESEARCH), existing class names + styles.
8. `frontends/wealth/src/routes/(terminal)/+layout.svelte` — the layout you will edit in commit 8. Understand the current offset math (terminal-root 100dvh, terminal-content overflow:hidden, where `TerminalGlobalNav` is rendered, what padding/margin surrounds the page body).
9. `frontends/wealth/src/routes/(terminal)/portfolio/live/+page.svelte` — example consumer that imports `page` from `$app/state` and uses URL params. Your ContextRail will read URL via the same API.
10. `frontends/wealth/src/routes/(terminal)/sandbox/focus-mode-smoke/+page.svelte` — the sandbox. After commit 8, this route must STILL render correctly wrapped by the new shell. FocusMode overlay must still appear above the shell chrome.
11. `frontends/wealth/src/app.html` and `frontends/wealth/vite.config.ts` — check how env vars / build-time constants are exposed. You need a way to expose git SHA for StatusBar (vite `define` or `import.meta.env`).
12. `frontends/wealth/eslint.config.js` — confirm the terminal namespace guardrails are active so your new files stay within the constraints.

# Z-INDEX STACK VERIFICATION (run before writing code)

Before writing ANY code, run:

```bash
grep -n "terminal-z-" packages/investintell-ui/src/lib/tokens/terminal.css
```

You should find: `terminal-z-base`, `terminal-z-panel`, `terminal-z-rail`, `terminal-z-statusbar`, `terminal-z-dropdown`, `terminal-z-modal`, `terminal-z-focusmode`, `terminal-z-palette`, `terminal-z-toast`.

If ANY are missing, STOP and report. Do not invent z-index values — they must be added to the token file first in a separate edit.

# ORDER OF OPERATIONS (why this specific order)

Commits are ordered to minimize coupling risk:

1. **LayoutCage** — foundation primitive, zero deps on other new components
2. **TerminalStatusBar** — standalone bottom bar, zero deps on other new components (uses `createTerminalStream` from Part B but that is already shipped)
3. **TerminalTopNav** — standalone top bar, zero deps on other new components. Refactor from existing `TerminalGlobalNav`.
4. **CommandPalette** — standalone overlay, zero deps on other new components. Keyboard-only interaction.
5. **AlertTicker** — standalone streaming component, uses `createTerminalStream` from Part B
6. **TerminalContextRail** — standalone right rail, zero deps on other new components, reads URL via `$app/state`
7. **TerminalShell** — COMPOSES all 6 above. Must come last because it imports them. This is the single coupling point.
8. **Wire `+layout.svelte` + delete `TerminalGlobalNav`** — integration commit. After this, the terminal is fully chromed.

Each commit is independently verifiable. If commit 7 surfaces a contract issue in, say, AlertTicker's props, you amend commit 5 only — commits 1-4 and 6 are untouched.

---

# COMMIT 1 — feat(terminal): LayoutCage primitive

## File

`frontends/wealth/src/lib/components/terminal/shell/LayoutCage.svelte`

## Purpose

The canonical 24px black-margin wrapper that every terminal page body renders inside. Preserves the `calc(100vh - <chrome-height>)` pattern from the current `(terminal)/+layout.svelte` offset math, but via grid layout instead of hardcoded calc. Single implementation so every page can compose it trivially.

## Props contract

```ts
import type { Snippet } from "svelte";

interface LayoutCageProps {
  children: Snippet;
  // Optional class hook for consumers that need to add their own layout
  // modifiers (e.g., a grid or flex setup) on top of the cage frame.
  class?: string;
}
```

## Rendering

```svelte
<div class="lc-cage {className}">
  {@render children()}
</div>
```

## Styling

- Position: `relative`, fills whatever grid/flex container the shell gives it.
- Background: `var(--terminal-bg-void)`.
- Padding: `var(--terminal-space-6)` (24px) on ALL SIDES — this is the black margin.
- Height: NOT `calc(100vh - X)`. The PARENT (`TerminalShell`) owns the viewport math and hands the cage a constrained height via grid. LayoutCage just fills its grid cell.
- Overflow: `hidden` on the outer. Children decide their own inner overflow.
- `box-sizing: border-box`.
- NO flex/grid in LayoutCage itself. Children are free to compose. Cage is a pure frame.

**Critical:** do NOT hardcode `100vh` or `calc()` math. The cage does not know the chrome heights. `TerminalShell` hands it a sized grid cell and LayoutCage fills it.

## Rune pattern

```svelte
<script lang="ts">
  import type { Snippet } from "svelte";

  interface LayoutCageProps {
    children: Snippet;
    class?: string;
  }

  let { children, class: className = "" }: LayoutCageProps = $props();
</script>
```

No state, no effects, no derivations. Pure presentational.

## Verification

1. `pnpm --filter netz-wealth-os svelte-check src/lib/components/terminal/shell/LayoutCage.svelte` → 0 errors
2. `pnpm --filter netz-wealth-os exec eslint src/lib/components/terminal/shell/LayoutCage.svelte` → 0 errors
3. Banned patterns grep → 0 matches

## Commit 1 message

```
feat(terminal): LayoutCage primitive — canonical black-margin frame

The single source of truth for the 24px black cage that every terminal
page body renders inside. Replaces the manual calc(100vh - 88px) +
padding:24px pattern that was scattered across every (terminal) page
and layout file.

Pure presentational primitive: fills its grid cell (parent owns the
viewport math), applies var(--terminal-space-6) padding on all sides,
var(--terminal-bg-void) background, overflow: hidden. Children decide
their own inner overflow.

Part C commit 1/8. Zero deps on other new primitives. Consumed by
TerminalShell in commit 7.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 2 — feat(terminal): TerminalStatusBar

## File

`frontends/wealth/src/lib/components/terminal/shell/TerminalStatusBar.svelte`

## Purpose

Fixed 28px bottom chrome strip. Displays: build metadata (git SHA, env), clock (UTC, tabular-nums), connection indicator (LiveDot), streaming ticker content (via `ticker` snippet slot from parent — TerminalShell injects AlertTicker output here).

## Props contract

```ts
import type { Snippet } from "svelte";

interface TerminalStatusBarProps {
  // Build SHA string (7-char short form). Exposed via vite define or
  // import.meta.env. Parent resolves this and passes it in so the
  // status bar stays a pure presentational primitive.
  buildSha: string;
  // Environment label (e.g., "dev", "staging", "prod"). Not shown on
  // "prod" — suppressed entirely to reduce visual noise on the
  // institutional surface.
  environment: "dev" | "staging" | "prod";
  // Organization name (from Clerk org context). Empty string allowed
  // during bootstrap; statusbar shows "—" until resolved.
  orgName: string;
  // Current user initials (2 char mono). Empty string fallback.
  userInitials: string;
  // Optional ticker content — a snippet provided by TerminalShell
  // that injects AlertTicker output. If omitted, the ticker area
  // shows a subtle "STANDBY" placeholder.
  ticker?: Snippet;
  // Connection status driving the LiveDot color. Parent (TerminalShell)
  // aggregates the state of all active TerminalStream subscriptions
  // and hands down the worst status.
  connectionStatus: "connecting" | "open" | "degraded" | "closed" | "error";
}
```

## Layout

28px high, fixed to the bottom of the TerminalShell grid row. Grid columns: `auto 1fr auto` (left cluster | ticker | right cluster).

**Left cluster:** `[ NETZ ] [<build>] [<env>|<orgName>|<userInitials>]` with hairline vertical separators. Use `var(--terminal-text-10)` monospace, `var(--terminal-fg-tertiary)` for labels, `var(--terminal-fg-secondary)` for values.

**Center ticker:** renders the `ticker` snippet if provided. If not, renders a single pulsing `STANDBY` label in `var(--terminal-fg-muted)`.

**Right cluster:** `[<connection-livedot>] [<utc-clock>]` — LiveDot is 6px dot with pulse animation matching the FocusMode LIVE dot pattern, colored by `connectionStatus`:

- `open` → `var(--terminal-status-success)`
- `connecting` → `var(--terminal-accent-cyan)`
- `degraded` → `var(--terminal-status-warn)`
- `closed` | `error` → `var(--terminal-status-error)`

UTC clock updates every second via a `$effect` with `setInterval`. Display format: `HH:MM:SS UTC` in tabular-nums. Compose the time string via `new Date().toISOString().substring(11, 19) + " UTC"` (machine ISO extraction, not locale-dependent — acceptable without a formatter).

## Rune pattern

```svelte
<script lang="ts">
  import type { Snippet } from "svelte";

  interface TerminalStatusBarProps { /* ... as above */ }
  let props: TerminalStatusBarProps = $props();

  let utcClock = $state("--:--:-- UTC");

  $effect(() => {
    if (typeof window === "undefined") return;
    const tick = () => {
      utcClock = new Date().toISOString().substring(11, 19) + " UTC";
    };
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  });
</script>
```

## Z-index

Uses `var(--terminal-z-statusbar)` (30) so it sits above page content but below modals/focus mode/palette.

## Verification

1. svelte-check + eslint on the file → 0 errors, 0 warnings
2. Banned patterns grep → 0 matches
3. Visual check: the clock `$effect` cleanup is called when the component unmounts (test by mounting and unmounting in sandbox or by inspection)

## Commit 2 message

```
feat(terminal): TerminalStatusBar — bottom chrome with clock, build, connection

Fixed 28px bottom strip for the terminal shell. Three-zone grid:
- Left: brand tag, build SHA, environment (dev/staging hidden on prod),
  org name, user initials
- Center: optional ticker snippet slot (TerminalShell injects AlertTicker
  output here via snippet composition)
- Right: connection LiveDot (pulse animation, color-coded by stream
  state), UTC clock (tabular-nums, 1Hz tick via $effect + setInterval
  with cleanup)

Pure presentational primitive — build SHA, org, user, and connection
status are passed in as props. TerminalShell resolves these from
import.meta.env + Clerk context + TerminalStream aggregation.

Uses var(--terminal-z-statusbar) = 30, above page content (10) and
rail (20), below modals (50), focus mode (60), and palette (70).

Part C commit 2/8.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 3 — feat(terminal): TerminalTopNav

## File

`frontends/wealth/src/lib/components/terminal/shell/TerminalTopNav.svelte`

## Purpose

Fixed 32px top chrome strip. Left-aligned brand, primary route tabs (with pending-state for unrouted phases), right cluster with command palette trigger + regime ticker placeholder + tenant switcher placeholder + alert pill + session chip.

## Props contract

```ts
interface TerminalTopNavProps {
  // Currently active pathname (from $page.url.pathname). TopNav uses
  // this to highlight the active tab.
  activePath: string;
  // Callback when user clicks the command palette trigger. TerminalShell
  // wires this to opening the CommandPalette overlay.
  onOpenPalette: () => void;
  // Optional: unread alert count driving the alert pill badge. Zero
  // means no badge, non-zero means red circle with count.
  alertCount?: number;
}
```

## Routes to render

All 8 tabs from the master plan vision (3 active, 5 pending):

```ts
const PRIMARY_TABS: ReadonlyArray<{
  id: string;
  label: string;
  href: string;
  status: "active" | "pending";
  pendingReason?: string;
}> = [
  { id: "macro",     label: "MACRO",     href: "/macro",             status: "pending", pendingReason: "Phase 7" },
  { id: "alloc",     label: "ALLOC",     href: "/allocation",        status: "pending", pendingReason: "Phase 7" },
  { id: "screener",  label: "SCREENER",  href: "/terminal-screener", status: "active" },
  { id: "builder",   label: "BUILDER",   href: "/portfolio/build",   status: "pending", pendingReason: "Phase 4" },
  { id: "live",      label: "LIVE",      href: "/portfolio/live",    status: "active" },
  { id: "research",  label: "RESEARCH",  href: "/research",          status: "active" },
  { id: "alerts",    label: "ALERTS",    href: "/alerts",            status: "pending", pendingReason: "Phase 5" },
  { id: "dd",        label: "DD",        href: "/dd",                status: "pending", pendingReason: "Phase 6" },
];
```

## Rendering per tab

- **Active tab** (`status='active'`): renders as an `<a>` tag with `href`. If `activePath.startsWith(href)`, adds `tn-tab--current` class with amber underline (`border-bottom: 2px solid var(--terminal-accent-amber)`). Hover state: amber color.
- **Pending tab** (`status='pending'`): renders as a `<span>` (NOT a link) with `tn-tab--pending` class: greyed out (`var(--terminal-fg-tertiary)`), `cursor: not-allowed`, and a small uppercase `PENDING` badge next to the label in `var(--terminal-text-10)` tertiary color. `title` attribute shows the `pendingReason`.

## Right cluster layout

```
[ ⌘K ]   REGIME: <placeholder>   [ ORG ▾ ]   △ <alertCount>   <userInitials>
```

- **⌘K trigger:** a button styled as a bracketed pill. `onClick` → calls `onOpenPalette()`. Uses monospace mono, hover border amber. Shows `⌘K` on macOS, `Ctrl+K` otherwise — detect via `navigator.platform` in a `$derived` (SSR-safe: default to `Ctrl+K` on server, hydrate to correct value on client).
- **Regime ticker:** placeholder reading `REGIME: STANDBY` in `var(--terminal-fg-muted)` — wire to real SSE stream in Phase 7 when `/macro/regime/stream` ships. Render as a non-interactive `<span>` for now.
- **Tenant switcher:** placeholder showing a fixed `[ NETZ ▾ ]` button with hover state but no click handler (no-op button per Clerk SDK gap noted in CLAUDE.md). Will wire to Clerk org switcher in a separate PR when the SvelteKit SDK stabilizes.
- **Alert pill:** if `alertCount > 0`, renders a red circle with the count. Zero means no pill rendered. Click → navigate to `/alerts` via `goto(resolve("/alerts"))` (pending route, so actually does nothing for now — hover state shows "coming soon").
- **Session chip:** renders `userInitials` in a 24×24 mono box with hairline border. Click → opens Clerk user menu (also pending per SDK gap).

## Keyboard

No keyboard handling in TerminalTopNav itself. Cmd+K is a GLOBAL handler mounted in TerminalShell (commit 7) that calls the same `onOpenPalette` callback. The ⌘K button is a click affordance; the keyboard shortcut is separate.

## Refactor existing TerminalGlobalNav

The existing file at `frontends/wealth/src/lib/components/layout/TerminalGlobalNav.svelte` has 3 tabs and simpler structure. In this commit, CREATE the new `TerminalTopNav` in `terminal/shell/`. Do NOT delete `TerminalGlobalNav` yet — that happens in commit 8 along with the layout wiring.

## Commit 3 message

```
feat(terminal): TerminalTopNav — 8-tab global navigation with pending states

Fixed 32px top chrome with the full master plan navigation vision:
SCREENER / LIVE / RESEARCH active, MACRO / ALLOC / BUILDER / ALERTS /
DD rendered in visible pending state (greyed, PENDING badge, title
attribute with phase attribution). Institutional surface shows the
complete product scope from day one — no "coming soon" hidden tabs.

Right cluster: Cmd/Ctrl+K palette trigger button (platform detection
SSR-safe), REGIME placeholder for Phase 7 regime stream, tenant
switcher button stubbed pending Clerk SDK resolution, alert pill with
count badge, session chip with user initials.

Active tab highlight via amber bottom border. Hover via amber color
shift. Pending tabs are non-interactive spans, not disabled links.

Existing TerminalGlobalNav at lib/components/layout/ stays in place
for this commit — commit 8 wires TerminalShell into the layout and
deletes the legacy nav.

Part C commit 3/8.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 4 — feat(terminal): CommandPalette

## File

`frontends/wealth/src/lib/components/terminal/shell/CommandPalette.svelte`

## Purpose

Cmd+K fuzzy launcher overlay. WAI-ARIA combobox with listbox results. Triggered by TerminalShell's global keyboard handler AND by the ⌘K button in TopNav (both call the same `open: boolean` `$bindable`).

## Props contract

```ts
interface CommandPaletteProps {
  open: boolean; // $bindable
}
```

## Commands catalog

Seed with go-to navigation commands that work TODAY. Hardcoded catalog in the component for now; Phase 3+ can refactor to a registry.

```ts
import { goto } from "$app/navigation";
import { resolve } from "$app/paths";

type Command = {
  id: string;
  label: string;
  hint: string; // keyboard hint like "g s"
  status: "active" | "pending";
  action: () => void | Promise<void>;
};

const COMMANDS: Command[] = [
  {
    id: "nav.screener",
    label: "Go to Screener",
    hint: "g s",
    status: "active",
    action: async () => {
      const target = resolve("/terminal-screener");
      await goto(target);
    },
  },
  {
    id: "nav.live",
    label: "Go to Live Workbench",
    hint: "g l",
    status: "active",
    action: async () => {
      const target = resolve("/portfolio/live");
      await goto(target);
    },
  },
  {
    id: "nav.research",
    label: "Go to Research",
    hint: "g r",
    status: "active",
    action: async () => {
      const target = resolve("/research");
      await goto(target);
    },
  },
  { id: "nav.macro",    label: "Go to Macro Desk",        hint: "g m", status: "pending", action: () => {} },
  { id: "nav.alloc",    label: "Go to Allocation",        hint: "g a", status: "pending", action: () => {} },
  { id: "nav.builder",  label: "Go to Portfolio Builder", hint: "g p", status: "pending", action: () => {} },
  { id: "nav.alerts",   label: "Go to Alerts",            hint: "g n", status: "pending", action: () => {} },
  { id: "nav.dd",       label: "Go to DD Queue",          hint: "g d", status: "pending", action: () => {} },
];
```

**Critical:** every `goto()` call must wrap its target with `resolve(...)` extracted to a local `const target` variable BEFORE the `goto` call. The `svelte/no-navigation-without-resolve` rule's AST matcher does not accept template literals or inline resolve calls — it requires a plain Identifier passed to `goto`. This is the pattern Opus confirmed in Phase 1 Task 0 fix.

## Rendering

- Full-viewport overlay (`position: fixed; inset: 0`), backdrop `var(--terminal-bg-scrim)`.
- Centered frame 640px × auto, max-height 60vh, black (`var(--terminal-bg-void)`), 1px hairline border, zero radius.
- Top: search input, hairline bottom border, monospace, placeholder `"Type a command or search..."`. Auto-focus on open.
- Middle: scrolling `<ul role="listbox">` of filtered results. Each `<li role="option">` shows the label, right-aligned hint, and a `PENDING` badge for pending commands.
- Bottom: a thin status strip showing `<count> results · ↑↓ navigate · ⏎ select · ESC close` in tertiary color.

## Filtering

Simple substring match on `label` + `hint`, case-insensitive. Pending commands STAY in the list (greyed out) so users can see what's coming.

## Keyboard

- `ESC` → closes palette (sets `open = false`)
- `↑ / ↓` → moves `highlightedIndex`
- `Enter` → invokes `COMMANDS[highlightedIndex].action()` and closes palette on success
- `Tab` → move focus, but since the palette has only one focusable (the input), Tab effectively cycles back to it; the listbox items do NOT receive focus (standard combobox pattern)

When a pending command is highlighted and user presses Enter, play a subtle shake animation on the result row and do NOT close the palette. Visual feedback that the command is not yet available.

## Lifecycle

- On open: focus the search input, reset query, reset `highlightedIndex` to 0
- On close: restore focus to the previously-focused element (same pattern as FocusMode's focus restoration)
- Body scroll lock while open (same pattern as FocusMode)

## Z-index

`var(--terminal-z-palette)` = 70. Must be above `--terminal-z-focusmode` = 60 so the palette can open inside a FocusMode.

## Commit 4 message

```
feat(terminal): CommandPalette — Cmd+K launcher with go-to commands

WAI-ARIA combobox overlay with listbox results. Seeded with 8 go-to
navigation commands from the master plan Appendix B (3 active
routes → goto via resolve(), 5 pending routes → greyed with PENDING
badge and no-op action). Pending commands stay visible so users see
the full terminal vision.

Full-viewport backdrop (var(--terminal-bg-scrim)), centered 640px
frame, brutalist chrome, auto-focus on open, focus restore on close,
body scroll lock, ESC/Enter/↑/↓ keyboard handling, simple substring
filter on label + hint.

Navigation uses goto(resolve("/...")) via extracted-const pattern
per Phase 1 Task 0 — svelte/no-navigation-without-resolve rule's
AST matcher does not accept inline composition, only plain Identifier
passed to goto.

Z-index var(--terminal-z-palette) = 70, above FocusMode (60) so
palette can open inside an active focus mode.

Part C commit 4/8.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 5 — feat(terminal): AlertTicker

## File

`frontends/wealth/src/lib/components/terminal/shell/AlertTicker.svelte`

## Purpose

Streaming marquee of recent portfolio alerts. Mounts inside TerminalStatusBar's `ticker` snippet slot.

## Props contract

```ts
interface AlertTickerProps {
  // URL of the SSE endpoint. Optional — when omitted (Part C scope),
  // component renders a static STANDBY state without subscribing.
  // Phase 5 wires this to /alerts/stream when the backend endpoint
  // ships.
  streamUrl?: string;
}
```

## Behavior

- If `streamUrl` is provided, mount a `createTerminalStream<AlertEvent>` subscription in a `$effect` with cleanup.
- Buffer incoming events — check if `createTickBuffer<AlertEvent>` exists in `packages/investintell-ui/src/lib/runtime/` (or anywhere in the ui package). If it does, use it. If it does NOT exist, implement a simple `$state`-capped array that holds the 5 most recent events and replaces the oldest on new event. Document the deferral in the commit message for Phase 2+ to add proper `createTickBuffer`.
- Render the 5 most recent alerts as a horizontal scrolling marquee. Each alert is `[<severity-dot>] <timestamp> · <title>` in a single line.
- If `streamUrl` is absent OR the stream is not connected yet, render a single static line: `STANDBY — alert stream not connected` in `var(--terminal-fg-muted)`.
- Click on an alert (future enhancement) — for Part C, not interactive; pure marquee display.

## Commit 5 message

```
feat(terminal): AlertTicker — streaming alert marquee primitive

Horizontal marquee of the 5 most recent portfolio alerts. Mounts
inside TerminalStatusBar's ticker snippet slot.

When streamUrl prop is provided, subscribes via createTerminalStream
and buffers events <describe: via createTickBuffer if available, or
via simple $state-capped array otherwise — state which>. When
streamUrl is absent, renders a STANDBY placeholder in muted color.

Part C scope: TerminalShell passes streamUrl=undefined because the
backend /alerts/stream endpoint is Phase 5 territory. Component is
ready to consume the stream the moment the endpoint ships.

Part C commit 5/8.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 6 — feat(terminal): TerminalContextRail

## File

`frontends/wealth/src/lib/components/terminal/shell/TerminalContextRail.svelte`

## Purpose

Right-side 280px rail that renders entity-scoped metadata when the URL has `?entity=<kind>:<id>`. Collapsible via `[` / `]` keyboard shortcuts. Hidden entirely (not mounted) when no entity is pinned.

## Props contract

```ts
import type { Snippet } from "svelte";

type EntityKind = "fund" | "portfolio" | "manager" | "sector" | "regime";

interface TerminalContextRailProps {
  // Currently-pinned entity. Null when no entity in URL.
  entity: { kind: EntityKind; id: string } | null;
  // Optional content snippet. If provided, rail renders this.
  // If absent, rail renders a minimal default card with entity kind + id.
  content?: Snippet<[{ kind: EntityKind; id: string }]>;
  // Collapsed state controlled externally (TerminalShell handles
  // the [ / ] keyboard shortcuts and passes the state down).
  collapsed: boolean;
}
```

## Rendering

- When `entity === null`: component returns nothing. No DOM, no layout impact.
- When `entity !== null && !collapsed`: renders a 280px fixed-width right panel with:
  - 32px header: `[ CONTEXT · <KIND> ]` brand + entity id truncated
  - Body: renders `content` snippet with the entity as parameter, or a default card listing kind + id
  - Fly-in transition on mount via `svelteTransitionFor("secondary")`
- When `collapsed`: renders a 32px width sliver with a vertical label `CTX` — click expands back. Sliver occupies the same grid column so page content width does not shift.

## Z-index

`var(--terminal-z-rail)` = 20.

## Keyboard shortcuts

The ACTUAL keyboard handling (`[` and `]`) is in `TerminalShell` (commit 7). `TerminalContextRail` just receives `collapsed` as a prop. This keeps the rail purely presentational.

## Commit 6 message

```
feat(terminal): TerminalContextRail — entity-scoped right rail with collapse

Right-side 280px rail that appears when URL contains ?entity=<kind>:<id>
and disappears entirely otherwise. Supports fund / portfolio / manager /
sector / regime entity kinds (matching FocusMode.entityKind).

Snippet-based content composition: caller passes a content snippet
typed with Snippet<[{ kind, id }]> so the rail renders entity-specific
metadata without the primitive knowing domain details. Default card
shows kind + id when no snippet provided.

Collapse to 32px sliver with vertical CTX label preserving grid
column width. TerminalShell owns the [ / ] keyboard shortcuts and
passes collapsed state down as a prop — rail stays purely
presentational.

Fly-in via svelteTransitionFor("secondary"). Z-index
var(--terminal-z-rail) = 20.

Part C commit 6/8.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 7 — feat(terminal): TerminalShell

## File

`frontends/wealth/src/lib/components/terminal/shell/TerminalShell.svelte`

## Purpose

The outermost shell composition. Mounts all 6 prior primitives in a grid layout, owns the GLOBAL keyboard shortcuts (Cmd+K for palette, `[` / `]` for rail collapse, `g`-prefix for navigation), resolves environment data (build SHA, Clerk user/org), aggregates stream connection status, reads URL entity param for context rail, and passes everything down.

## Props contract

```ts
import type { Snippet } from "svelte";

interface TerminalShellProps {
  children: Snippet;
}
```

Just `children`. Everything else is resolved internally from `$app/state`, `import.meta.env`, and Clerk context.

## Grid layout

```
grid-template-rows:    32px 1fr 28px      (topnav | content | statusbar)
grid-template-columns: 1fr <rail?>        (page | rail when entity pinned)
grid-template-areas:
  "nav     nav"
  "content rail"
  "status  status"
```

When no entity pinned, rail column disappears and content spans full width.

## State resolved internally

```ts
import { page } from "$app/state";
import TerminalTopNav from "./TerminalTopNav.svelte";
import TerminalStatusBar from "./TerminalStatusBar.svelte";
import TerminalContextRail from "./TerminalContextRail.svelte";
import CommandPalette from "./CommandPalette.svelte";
import AlertTicker from "./AlertTicker.svelte";
import LayoutCage from "./LayoutCage.svelte";

type EntityKind = "fund" | "portfolio" | "manager" | "sector" | "regime";

// Build metadata from import.meta.env
const buildSha = (import.meta.env.VITE_BUILD_SHA as string | undefined) ?? "local";
const environment = ((import.meta.env.VITE_ENV as string | undefined) ?? "dev") as "dev" | "staging" | "prod";

// URL-pinned entity
const entity = $derived.by(() => {
  const raw = page.url.searchParams.get("entity");
  if (!raw) return null;
  const [kind, id] = raw.split(":");
  if (!kind || !id) return null;
  // Validate kind is a known EntityKind
  const knownKinds: EntityKind[] = ["fund", "portfolio", "manager", "sector", "regime"];
  if (!knownKinds.includes(kind as EntityKind)) return null;
  return { kind: kind as EntityKind, id };
});

// Context rail collapsed state — ephemeral, not URL-persisted
let railCollapsed = $state(false);

// Command palette open state — ephemeral
let paletteOpen = $state(false);

// Connection status — Part C hardcodes to "connecting" since no
// streams are wired yet. Phase 5+ will aggregate from real
// TerminalStream subscriptions.
const connectionStatus = "connecting" as const;

// Clerk context — org name + user initials. Placeholder for Part C;
// Phase 2+ wires real Clerk data when SvelteKit SDK stabilizes.
const orgName = "NETZ";
const userInitials = "AR";
```

## Global keyboard handler

One `$effect` listening on `window.keydown`:

- `Cmd+K` / `Ctrl+K` → `paletteOpen = !paletteOpen` (toggle). Check `event.metaKey || event.ctrlKey` + `event.key === "k"`. Prevent default.
- `[` (outside of input fields) → `railCollapsed = true`
- `]` (outside of input fields) → `railCollapsed = false`
- Go-to prefixes (`g` followed within 800ms by `s/l/r/m/a/p/n/d`) → use a small state machine for multi-key sequences. Track the last `g` timestamp in a local var. On the second key, if within 800ms, look up and invoke the corresponding command action. Reset timestamp on any other key.

Critical: the handler MUST ignore keypresses when focus is inside an `<input>`, `<textarea>`, `[contenteditable="true"]`, or any element with `role="textbox"`. Check via `document.activeElement` tag name + attribute check. Otherwise typing in a search field would trigger `g` shortcuts.

The handler has a single `$effect` cleanup that removes the listener.

## Rendering

```svelte
<div class="ts-shell" class:ts-shell--has-rail={entity !== null}>
  <TerminalTopNav
    activePath={page.url.pathname}
    onOpenPalette={() => (paletteOpen = true)}
  />

  <main class="ts-content">
    <LayoutCage>
      {@render children()}
    </LayoutCage>
  </main>

  {#if entity !== null}
    <TerminalContextRail {entity} collapsed={railCollapsed} />
  {/if}

  <TerminalStatusBar
    {buildSha}
    {environment}
    {orgName}
    {userInitials}
    {connectionStatus}
    ticker={tickerSnippet}
  />

  <CommandPalette bind:open={paletteOpen} />
</div>

{#snippet tickerSnippet()}
  <AlertTicker />
{/snippet}
```

## Styling

```css
.ts-shell {
  display: grid;
  grid-template-rows: 32px 1fr 28px;
  grid-template-columns: 1fr;
  grid-template-areas: "nav" "content" "status";
  height: 100dvh;
  overflow: hidden;
  background: var(--terminal-bg-void);
  color: var(--terminal-fg-primary);
  font-family: var(--terminal-font-mono);
}

.ts-shell--has-rail {
  grid-template-columns: 1fr 280px;
  grid-template-areas: "nav nav" "content rail" "status status";
}

/* Use a modifier class instead of :has() selector to maximize
   compatibility. Falls back gracefully across browsers. */

:global(.ts-shell > .tn-nav) { grid-area: nav; }
:global(.ts-shell > .ts-content) { grid-area: content; min-width: 0; min-height: 0; }
:global(.ts-shell > .tcr-rail) { grid-area: rail; }
:global(.ts-shell > .sb-bar) { grid-area: status; }
```

Use class-modifier approach instead of CSS `:has()` to avoid compatibility concerns. The child components apply their own class names which Shell references via `:global`. If the class names conflict with what's in TopNav / StatusBar / ContextRail, adapt to whatever the children actually use.

## Verification

1. svelte-check on TerminalShell + all 6 child components → 0 errors
2. Grid math: 32 + 28 = 60, so page content gets `calc(100dvh - 60px)`. Combined with LayoutCage's 24px padding on all sides, usable content area is `calc(100dvh - 108px)` horizontally. Verify this aligns with the existing `(terminal)` sandbox page which expects certain content dimensions.

## Commit 7 message

```
feat(terminal): TerminalShell — shell composition of all chrome primitives

The outermost shell of every terminal route. Composes TerminalTopNav
+ LayoutCage (via children snippet) + TerminalStatusBar +
CommandPalette (overlay) + TerminalContextRail (conditional on URL
entity param).

Owns the global keyboard shortcuts: Cmd/Ctrl+K toggles palette,
[ / ] toggles rail collapse, g-prefix go-to commands (g s / g l /
g r etc.) trigger navigation via CommandPalette action handlers.
Input-field detection so shortcuts do not fire inside text inputs.

Resolves build metadata (VITE_BUILD_SHA, VITE_ENV), Clerk user/org
placeholders, and URL-pinned entity via $derived reading $page.url.
Context rail only mounts when ?entity=<kind>:<id> is in the URL with
a valid entity kind. Rail collapse is ephemeral $state, not
URL-persisted.

Grid layout via class-modifier approach (.ts-shell--has-rail) for
conditional rail column. 32px topnav + 1fr content + 28px statusbar
rows. Content column = 1fr, rail column = 280px when active.

Part C commit 7/8. Commit 8 wires this into (terminal)/+layout.svelte
and deletes the legacy TerminalGlobalNav.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# COMMIT 8 — chore(terminal): wire TerminalShell + delete TerminalGlobalNav

## Files

1. `frontends/wealth/src/routes/(terminal)/+layout.svelte` — modify
2. `frontends/wealth/src/lib/components/layout/TerminalGlobalNav.svelte` — delete
3. `frontends/wealth/vite.config.ts` — modify if needed to expose `VITE_BUILD_SHA` / `VITE_ENV`

## Layout change

Current `(terminal)/+layout.svelte` renders `TerminalGlobalNav` + a content wrapper. Replace the entire body with a single `TerminalShell` wrapping the route children:

```svelte
<script lang="ts">
  import type { Snippet } from "svelte";
  import TerminalShell from "$lib/components/terminal/shell/TerminalShell.svelte";

  let { children }: { children: Snippet } = $props();
</script>

<TerminalShell>
  {@render children()}
</TerminalShell>
```

Strip any remaining offset math, global CSS, nav mounting, etc. The shell primitive owns all of it now.

## Delete TerminalGlobalNav

`git rm frontends/wealth/src/lib/components/layout/TerminalGlobalNav.svelte`.

If anything else imports from that path, ESCAPE HATCH. The only importer should be the layout you just refactored. Grep before deleting:

```bash
grep -rn "TerminalGlobalNav" frontends/wealth/src/
```

If zero matches after the layout edit, proceed with the delete. If matches, investigate each and either update the import to `TerminalTopNav` (if it's a caller that wanted global nav) or decouple the usage.

## Vite config (if needed)

If `import.meta.env.VITE_BUILD_SHA` is not currently defined, add to `frontends/wealth/vite.config.ts`:

```ts
// Inside defineConfig({ ... }):
define: {
  "import.meta.env.VITE_BUILD_SHA": JSON.stringify(
    process.env.GIT_SHA ?? "local-dev"
  ),
  "import.meta.env.VITE_ENV": JSON.stringify(
    process.env.NODE_ENV === "production" ? "prod" : "dev"
  ),
},
```

If vite.config is already set up with these, skip. If not, add them.

## Verification (full regression)

1. `pnpm --filter netz-wealth-os svelte-check` → 0 errors, same 12 pre-existing warnings
2. `pnpm --filter netz-wealth-os exec eslint .` → 0 terminal errors, remaining legacy errors unchanged
3. `cd packages/investintell-ui && pnpm build` → clean
4. `node scripts/check-terminal-tokens-sync.mjs` → OK
5. `pnpm --filter netz-wealth-os build` → clean, all routes bundle
6. **Manual browser smoke test.** Start dev server via `pnpm --filter netz-wealth-os dev`, open `http://localhost:5173/sandbox/focus-mode-smoke`:
   - Shell chrome visible (topnav + cage + statusbar)
   - All 8 tabs render with pending badges on non-active tabs
   - Status bar shows build SHA, org, clock ticking, connection dot
   - Click `[ ⌘K ]` → CommandPalette opens, lists 8 commands with 3 active and 5 pending
   - ESC closes palette
   - Click `[ OPEN WAR ROOM ]` → FocusMode still opens correctly ABOVE the shell, below the palette z-index
   - Inside FocusMode, press Cmd+K → palette opens ABOVE the focus mode
   - ESC closes palette, ESC again closes FocusMode
   - Press `[` (no entity pinned) → no-op gracefully
   - Append `?entity=fund:smoke-test` to URL → rail appears on right with default card
   - Press `[` → rail collapses to sliver
   - Press `]` → rail expands back
   - Navigate between routes via topnav tabs, verify active tab highlight updates correctly
   - Test keyboard: `g s` → navigates to screener; `g m` → no-op with visual feedback (pending command)
7. If any smoke test step fails, DO NOT commit. Fix the offending component first, re-verify, then commit 8.

## Commit 8 message

```
chore(terminal): wire TerminalShell into (terminal)/+layout, delete TerminalGlobalNav

Collapses (terminal)/+layout.svelte to a minimal wrapper around
TerminalShell. Shell now owns all chrome — topnav, cage, statusbar,
palette, context rail, global keyboard shortcuts. Layout file is 12
lines total.

Deletes lib/components/layout/TerminalGlobalNav.svelte (replaced by
terminal/shell/TerminalTopNav with expanded 8-tab vision).

Vite config exposes VITE_BUILD_SHA and VITE_ENV for TerminalStatusBar
(if not already defined).

Full regression verified:
- svelte-check baseline preserved (0 errors, 12 warnings)
- eslint terminal namespace clean
- packages/investintell-ui unchanged
- Sandbox smoke route renders correctly inside new shell
- FocusMode overlay z-index (60) remains below CommandPalette (70)
  allowing palette to open inside focus mode
- CommandPalette Cmd+K trigger works from anywhere
- Rail keyboard shortcuts [ and ] toggle correctly
- g-prefix go-to navigation fires for active routes, visually
  signals pending for unrouted phases

Part C complete. Terminal Shell primitive layer production-grade.
Phase 3 Screener can now consume the shell via minimal page wrapping
(children snippet handed off by +layout).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

# FINAL FULL-TREE VERIFICATION

After all 8 commits land:

1. svelte-check: 0 errors, 12 pre-existing warnings baseline
2. eslint: terminal namespace clean, legacy errors unchanged
3. packages/investintell-ui build: clean
4. Token sync: OK
5. Wealth build: clean, all routes bundle including the new shell
6. Manual smoke test in browser — the checklist in Commit 8 §Verification
7. FocusMode sandbox still passes its 10-item checklist with the new shell wrapping

# SELF-CHECK CHECKLIST

## Per commit
- [ ] Commit 1: LayoutCage — pure presentational, no state, 0 deps
- [ ] Commit 2: TerminalStatusBar — clock ticks, `$effect` cleans up, 0 deps on other new primitives
- [ ] Commit 3: TerminalTopNav — 8 tabs, pending states, right cluster, 0 deps
- [ ] Commit 4: CommandPalette — combobox a11y, focus restore, z=70, uses `resolve()` for `goto()`
- [ ] Commit 5: AlertTicker — streamUrl optional, STANDBY fallback, consumes `createTerminalStream` when wired
- [ ] Commit 6: TerminalContextRail — entity-conditional mount, collapsed prop, snippet composition
- [ ] Commit 7: TerminalShell — composes all 6, owns global keyboard + state, resolves env/Clerk
- [ ] Commit 8: layout wired, TerminalGlobalNav deleted, vite config updated if needed

## Cross-commit contract validation
- [ ] Z-index stack respected: rail 20 < statusbar 30 < focusmode 60 < palette 70
- [ ] CommandPalette opens ABOVE FocusMode in the sandbox smoke test
- [ ] Global Cmd+K handler doesn't fire inside input fields
- [ ] Rail collapse keyboard `[` / `]` doesn't fire inside input fields
- [ ] `g`-prefix navigation doesn't fire inside input fields
- [ ] Status bar clock `$effect` cleanup verified (no interval leak on unmount)
- [ ] Stream subscription `$effect` cleanup verified in AlertTicker (even though `streamUrl` is undefined in Part C)

## Scope discipline
- [ ] Zero files outside the 7 new shell components + layout + deleted nav touched
- [ ] FundWarRoomModal.svelte still byte-identical
- [ ] FocusMode.svelte still byte-identical
- [ ] packages/investintell-ui unchanged (except vite.config.ts if needed)
- [ ] Tokens sync still green
- [ ] Parallel session files untouched (2 untracked + 1 modified from other sessions)

## Final
- [ ] 8 new commits on `feat/terminal-unification-part-c`
- [ ] Not pushed — local only, awaiting review

# VALID ESCAPE HATCHES

1. A z-index token is missing from terminal.css → STOP, report, do not invent.
2. `createTickBuffer` does not exist in `packages/investintell-ui` → implement AlertTicker with simple `$state`-capped array, document deferral in commit 5 message.
3. `import.meta.env.VITE_BUILD_SHA` definition requires touching `vite.config.ts` and the touch conflicts with existing config → report, ship StatusBar with `buildSha="local"` fallback, defer vite config to a separate PR.
4. `svelte/no-navigation-without-resolve` rule complains about dynamic command palette actions that compose `goto` at runtime → extract each action to `const target = resolve("/...")` pattern (same fix Opus applied in Phase 1 Task 0). The prompt's Commands catalog already shows this pattern — follow it verbatim.
5. CSS grid class-modifier approach causes parse errors → try CSS `:has()` as fallback; if neither works, use a `$derived` reactive class binding and report the decision.
6. `TerminalGlobalNav` has unexpected importers beyond the layout → investigate each, report with full import list, do not delete blindly.
7. Clerk context resolution is more complex than a simple context read → ship with placeholder strings "NETZ" and "AR" as documented in the component; Phase 2 wires real Clerk data.
8. Rail fly-in transition conflicts with the grid layout (flying element distorts grid cells) → use opacity fade instead of y translate for the rail, report the swap in the commit message.
9. Any contract between TerminalShell and a child component is ambiguous → read the child's code you just wrote, align the contract, amend the child commit BEFORE shipping commit 7.
10. `pnpm dev` cannot be started for the manual smoke test in commit 8 → ship commits 1-7, push, and report that commit 8 needs manual verification by the human operator before the final commit is made.

# NOT VALID ESCAPE HATCHES

- "This feels too complex for one commit" → it is ONE component, ship it
- "I could skip the pending tab states" → NO, the vision must be visible
- "I could skip the rail keyboard shortcuts" → NO, ship the full keyboard contract
- "The Cmd+K detection is hard on SSR" → use `$derived` that defaults to Ctrl on server, hydrates to Cmd on client when `navigator.platform` is available
- "I could use a simple stub for CommandPalette" → NO, WAI-ARIA combobox is the floor
- "I could skip the manual browser smoke test" → NO, commit 8 is the integration gate. The shell being physically rendered in a real browser is the only way to catch z-index conflicts and grid layout bugs that pass svelte-check

# REPORT FORMAT

When the session is done (all 8 commits on the branch), report in this exact structure:

1. Eight commit SHAs with full messages
2. Per commit: files created/modified/deleted, lines added/removed, verification results (svelte-check + eslint + banned grep + specific behavioral notes)
3. Commit 7 extra: z-index stack verification output, keyboard handler input-field detection verification
4. Commit 8 extra: manual browser smoke test results from the Verification list — you DO run `pnpm dev` and open the sandbox to verify, unlike prior sessions. This is the integration gate for Part C. If `pnpm dev` cannot be started, report that and request manual verification.
5. `git log --oneline feat/terminal-unification-part-c ^main` showing 8 new commits
6. Full-tree verification: svelte-check, eslint, investintell-ui build, token sync, wealth build
7. Scope discipline confirmation: files touched list, untouched byte-identical confirmations
8. Any escape hatches hit with full context

Begin by reading the 12 required files and grep'ing the z-index tokens. Do not write any code until you have confirmed: all z-index tokens exist, the current `+layout.svelte` structure, and the `createTerminalStream` + `createTickBuffer` primitives are available.
