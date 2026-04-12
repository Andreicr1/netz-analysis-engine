# Phase 3 Scope Audit — Screener Fast Path Investigation Brief

**Date:** 2026-04-12
**Mission:** Pure investigation. NO code changes. NO commits. Produce a structured markdown report so the primary Opus planner can write an accurate Phase 3 execution brief against the real current state of the Screener surface.
**Branch:** any — this audit does not modify files

## Why this audit exists

The Terminal Unification master plan proposes Phase 3 as "Screener Fast Path — the first real consumer of TerminalShell + FocusMode + data plane primitives". Phase 1 (shell foundations) and Phase 2 (data plane) are both complete in main. The master plan's Phase 3 scope was written BEFORE Phases 1 and 2 shipped, so it reflects assumptions about the screener state that may no longer be accurate.

Phase 2's audit proved that 40% of its proposed scope was wrong because the master plan was stale. Phase 3 audit exists to prevent the same class of error — we need to know what the current screener surface ACTUALLY is before writing a brief that says "create this" or "refactor that".

## How to execute

1. READ-ONLY investigation. Do not write, edit, or commit any file.
2. Use Read, Grep, Glob, and Bash (read-only commands only) tools.
3. For each item in the Audit Checklist below, run the specified queries, read the specified files, and record findings.
4. Output ONE structured markdown report via the Report Format at the end.
5. If any item is ambiguous or requires judgment, report both the finding AND the ambiguity — do NOT resolve it yourself.
6. Budget: investigation should take ~20-40 minutes of agent time.

## Audit Checklist

Work through all items in order. For each item, produce a verdict: `EXISTS_AS_EXPECTED`, `EXISTS_WITH_DIVERGENT_SHAPE`, `PARTIAL`, `MISSING`, `NOT_APPLICABLE`, or `NEEDS_HUMAN_DECISION`.

---

### A. Route state — `/terminal-screener/+page.svelte`

#### A.1 Current route page structure

**Investigate:**
- Read `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.svelte` fully.
- Note:
  - What components it imports
  - How it mounts inside the shell (is it a direct child of `TerminalShell` from Part C, or does it still use some legacy layout pattern?)
  - Whether it uses the Part C `children` snippet pattern
  - What props it passes down and what state it owns
  - What URL params it reads via `$app/state.page`
  - Whether it uses `registerFocusTrigger` from Part C's focus-mode attachments, or still uses the Phase 1 `onOpenWarRoom` prop callback pattern
- Read `frontends/wealth/src/routes/(terminal)/terminal-screener/+page.server.ts` if present — does it have `load()` calling the backend screener catalog endpoint?

**Report:** concrete summary of current wiring, import list, state shape.

#### A.2 Companion files

**Investigate:**
- Is there a `+layout.svelte` inside `terminal-screener/`?
- Is there a `+page.ts` client loader?
- Any `+error.svelte` boundary?

**Report:** list of all files under `routes/(terminal)/terminal-screener/`.

---

### B. Component state

#### B.1 `TerminalScreenerShell.svelte`

**Investigate:**
- Read `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerShell.svelte` fully.
- Note:
  - Current props contract
  - Does it mount `TerminalScreenerFilters`, `TerminalScreenerQuickStats`, `TerminalDataGrid`?
  - Does it have its own layout/grid, or does it delegate to `LayoutCage` from Part C?
  - Does it still render any chrome (nav, statusbar) itself, or does it fully delegate to `TerminalShell`?
  - Does it have any hardcoded data or is it pure presentational?
  - How big is the file (LOC)?

**Report:** full structure summary.

#### B.2 `TerminalDataGrid.svelte`

**Investigate:**
- Read `frontends/wealth/src/lib/components/screener/terminal/TerminalDataGrid.svelte` fully.
- Note:
  - Is it virtualized? If yes, what virtualization library or custom approach?
  - What columns does it render by default?
  - Does it support column definition via a prop (headless column def API), or are columns hardcoded?
  - Does it have row click handling? If yes, how is it wired?
  - Does it support inline sparklines in any column? If yes, via what library/pattern?
  - Does it have an "elite" badge or similar visual treatment on any row?
  - Sort state: does it own sort? Is sort stable with multi-column tiebreaker?
  - Pagination: offset-based or keyset-based?
  - How big is the file (LOC)?

**Report:** full component API, column structure, interaction model, virtualization approach.

#### B.3 `TerminalScreenerFilters.svelte`

**Investigate:**
- Read `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerFilters.svelte` fully.
- Note:
  - What filter categories it exposes (region, universe, strategy, AUM, etc.)
  - Does it have an ELITE filter chip?
  - Is the filter API reactive (writes to URL or to a store)?
  - Single unified filter pattern vs provider-named filter pattern (per memory `feedback_screener_macro_ux.md`, screener should have ONE unified filter, NOT provider-named categories)
  - How big is the file (LOC)?
  - Any known bugs flagged in the file's comments?

**Report:** filter inventory, ELITE chip status, URL sync state.

#### B.4 `TerminalScreenerQuickStats.svelte`

**Investigate:**
- Read `frontends/wealth/src/lib/components/screener/terminal/TerminalScreenerQuickStats.svelte` fully.
- Note: what stats it displays, where the data comes from, whether it's reactive to filter changes.

**Report:** stats list, data source, reactivity model.

#### B.5 Any other screener components

**Investigate:**
- Glob `frontends/wealth/src/lib/components/screener/terminal/` and list every file.
- For each file not covered in B.1-B.4, read enough to classify: active / legacy / helper.

**Report:** full file inventory with classification.

---

### C. Backend route state

#### C.1 `POST /screener/catalog` endpoint

**Investigate:**
- Read `backend/app/domains/wealth/routes/screener.py` fully (or the relevant sections around the catalog endpoint).
- Note:
  - Does it exist? If yes, what's its current signature?
  - Does the response schema include `elite_flag`? (Phase 2 Session B added the column — the route may or may not expose it yet.)
  - Does the request schema accept an `elite_only: bool` filter or similar?
  - Does the query read from `mv_fund_risk_latest` (the MV from Phase 2 Session B) or directly from `fund_risk_metrics`?
  - Does the query use `v_screener_org_membership` for the org-membership marker?
  - Pagination shape: offset+limit or keyset cursor?
  - What's the response schema for a single row (column list)?

**Report:** endpoint signature, request schema, response schema, query shape, join usage.

#### C.2 `POST /universe/approve` endpoint

**Investigate:**
- Read the relevant section of `backend/app/domains/wealth/routes/universe.py` (or wherever it lives).
- Note:
  - Does it exist?
  - Does it support a fast-track path for liquid universes (`registered_us`, `etf`, `ucits_eu`, `money_market`)?
  - Does it return the newly-approved instruments in the response body?
  - Is it idempotent via `@idempotent` decorator or similar?
  - Does it enforce the DD requirement for `private_us` and `bdc` universes (returns 409 if DD not complete)?

**Report:** endpoint state, fast-track support, idempotency, DD gate status.

#### C.3 `POST /dd-reports/queue` (enqueue new DD)

**Investigate:**
- Read relevant section of `backend/app/domains/wealth/routes/dd_reports.py` or `long_form_reports.py`.
- Note: does a "queue a new DD report for a fund" endpoint exist?

**Report:** endpoint state.

#### C.4 Sparkline data endpoint

**Investigate:**
- Is there a batch endpoint that returns NAV monthly aggregate data for a list of instruments? Master plan proposes sparklines pulling from `nav_monthly_returns_agg`.
- Grep for routes that return data from `nav_monthly_returns_agg`.

**Report:** endpoint exists / missing, shape.

---

### D. Shell consumption

#### D.1 Is the screener route wrapped by `TerminalShell`?

**Investigate:**
- Read `frontends/wealth/src/routes/(terminal)/+layout.svelte`.
- Confirm it mounts `TerminalShell` from Part C.
- Trace the chain: `+layout.svelte` → `TerminalShell` → `{@render children()}` → `terminal-screener/+page.svelte`.
- Verify that the screener does NOT re-render its own top nav or status bar — that's the shell's job.

**Report:** wiring chain, any duplications or conflicts.

#### D.2 `registerFocusTrigger` usage

**Investigate:**
- Read `frontends/wealth/src/lib/components/terminal/focus-mode/` for the `registerFocusTrigger` attachment (if it exists — master plan proposes it, Part C may or may not have shipped it).
- Grep for `registerFocusTrigger` usage across the screener code.
- If missing: is there still a legacy `onOpenWarRoom` callback prop in the screener? (Phase 1 pattern.)

**Report:** attachment existence, current trigger pattern.

---

### E. Keyboard / URL state

#### E.1 Keyboard shortcuts

**Investigate:**
- Grep for keyboard event handlers in the screener components (`keydown`, `keyup`, `keypress`, `on:keydown`, `onkeydown`).
- Note which shortcuts are currently wired: `/`, `↑ ↓`, `Enter`, `u`, `d`, `e`, etc.
- Check if the global keyboard handler in `TerminalShell` conflicts with any screener-specific shortcuts.

**Report:** shortcut inventory, conflict analysis.

#### E.2 URL state shape

**Investigate:**
- Grep for `$page.url.searchParams` or `page.url.searchParams` in the screener route and components.
- Note what URL keys are currently read (q, filter, page, sort, elite, universe, etc.)
- Are filters persisted to URL or only to local state?

**Report:** URL param inventory, persistence pattern.

---

### F. Focus mode trigger wiring

#### F.1 Row click handling

**Investigate:**
- In `TerminalDataGrid.svelte`, find the row click handler.
- Does it call `openFocus({ type: 'fund', id })` from Part C, or does it still use a legacy callback pattern like `onOpenWarRoom(fundId)`?
- How is the target entity-kind determined? (Master plan says `fund` for screener rows, but the data grid might be generic.)

**Report:** current click-to-focus pattern, alignment with Part C.

#### F.2 `FundFocusMode` integration

**Investigate:**
- Does the screener route currently mount `FundFocusMode` from Part C at the page level, or does it rely on the shell's mount from Part C commit 8?
- Grep for `FundFocusMode` usage in the screener route and TerminalShell.

**Report:** mount location.

---

### G. Inline action column state

#### G.1 Fast-path `[→ UNIVERSE]` / `[+ DD]` column

**Investigate:**
- Does `TerminalDataGrid` or any screener component currently render an action column per row?
- If yes, what actions? Do they map to `POST /universe/approve` or `POST /dd-reports/queue`?
- Is the fast-track-vs-DD decision based on the universe column value?

**Report:** action column state.

---

### H. Test coverage

#### H.1 Existing screener tests

**Investigate:**
- Glob `frontends/wealth/tests/` for screener-related tests.
- Glob `backend/tests/wealth/routes/test_screener*.py`.
- Note: what paths are currently tested (backend catalog query, frontend DataGrid sort, filter apply, etc.)?

**Report:** test file inventory with coverage summary.

---

### I. Visual and UX state

#### I.1 Current screener visual state

**Investigate:**
- Run `pnpm --filter netz-wealth-os dev` locally IF POSSIBLE (only if you can cleanly start and stop the dev server, otherwise skip).
- Open `http://localhost:<port>/terminal-screener` in a headless browser or report verbally what the page renders.
- Note:
  - Does the shell (TopNav, StatusBar, Cage) render correctly around the screener content?
  - Does the DataGrid render rows?
  - Do filters visually appear in the expected layout?
  - Are there any console errors?
- If you cannot start the dev server safely, skip this and just report "not verified visually".

**Report:** visual state or "not verified visually" with reason.

---

## Report Format

Produce ONE structured markdown report. Do NOT include code diffs. Do NOT propose changes. Do NOT write a Phase 3 brief. Only report current state findings.

```markdown
# Phase 3 Scope Audit — Findings

**Audit run at:** <UTC timestamp>
**Auditor:** <agent identity>

## Section A — Route state

### A.1 /terminal-screener/+page.svelte current structure
- **Verdict:** <enum>
- **Current state:** <one paragraph>
- **Key imports:** <list>
- **State shape:** <describe>
- **URL reads:** <list of params read>
- **Focus trigger pattern:** <legacy prop / registerFocusTrigger / missing>

### A.2 Companion files
- **Files in routes/(terminal)/terminal-screener/:** <list>

## Section B — Component state

### B.1 TerminalScreenerShell.svelte
- **Verdict:** <enum>
- **Props contract:** <describe>
- **Mounts:** <list of child components>
- **Shell delegation:** <delegates to LayoutCage / renders own chrome / partial>
- **LOC:** <number>

### B.2 TerminalDataGrid.svelte
- **Verdict:** <enum>
- **Column API:** <headless def / hardcoded>
- **Virtualization:** <library or custom or none>
- **Row click wiring:** <pattern>
- **Sparkline support:** <yes / no / planned>
- **Elite badge:** <yes / no / other treatment>
- **Sort + pagination:** <describe>
- **LOC:** <number>

### B.3 TerminalScreenerFilters.svelte
- **Verdict:** <enum>
- **Filter inventory:** <list>
- **ELITE chip:** <yes / no>
- **URL sync:** <yes / no / partial>
- **Unified vs provider-named:** <describe>
- **LOC:** <number>

### B.4 TerminalScreenerQuickStats.svelte
- **Verdict:** <enum>
- **Stats displayed:** <list>
- **Data source:** <describe>

### B.5 Other screener components
- **Inventory:** <list with classification>

## Section C — Backend route state

### C.1 POST /screener/catalog
- **Verdict:** <enum>
- **Signature:** <code or description>
- **Request filters:** <list, including ELITE support status>
- **Response row schema:** <column list>
- **elite_flag exposed:** <yes / no>
- **Reads from mv_fund_risk_latest:** <yes / no>
- **Uses v_screener_org_membership:** <yes / no>
- **Pagination shape:** <offset / keyset>

### C.2 POST /universe/approve
- **Verdict:** <enum>
- **Fast-track for liquids:** <yes / no / partial>
- **Idempotency:** <yes / no>
- **DD gate for privates:** <yes / no>

### C.3 POST /dd-reports/queue (enqueue)
- **Verdict:** <enum>

### C.4 Sparkline data endpoint
- **Verdict:** <enum>
- **Location if exists:** <path>

## Section D — Shell consumption

### D.1 (terminal)/+layout.svelte chain
- **Verdict:** <enum>
- **Wiring:** <describe>
- **Duplications:** <none / list>

### D.2 registerFocusTrigger
- **Exists in Part C:** <yes / no>
- **Used by screener:** <yes / no>
- **Legacy callback still present:** <yes / no>

## Section E — Keyboard / URL state

### E.1 Keyboard shortcuts
- **Currently wired:** <list>
- **Conflicts with TerminalShell global handler:** <none / list>

### E.2 URL state shape
- **Params read:** <list>
- **Persistence pattern:** <URL / local / mixed>

## Section F — Focus mode wiring

### F.1 Row click to focus
- **Current pattern:** <describe>
- **Matches Part C openFocus:** <yes / no>

### F.2 FundFocusMode mount location
- **Location:** <route page / shell / missing>

## Section G — Inline action column

### G.1 Fast-path action column
- **Verdict:** <enum>
- **Current actions:** <list if exists>

## Section H — Test coverage

### H.1 Existing tests
- **Frontend test files:** <list>
- **Backend test files:** <list>
- **Coverage summary:** <paragraph>

## Section I — Visual state

### I.1 Current visual rendering
- **Verdict:** <visually verified / not verified>
- **Notes:** <paragraph or "skipped">

## Aggregated gap matrix

| Area | Current state | Phase 3 action needed |
|---|---|---|
| ELITE filter chip in Filters | <yes/no> | <create/refactor/none> |
| elite_flag in catalog response | <yes/no> | <add/none> |
| DataGrid virtualization | <yes/no> | <promote/refactor/none> |
| Row click → openFocus | <yes/no> | <rewire/none> |
| Inline action column | <yes/no> | <create/none> |
| Sparklines | <yes/no> | <add/none> |
| Keyboard shortcuts (/, ↑↓, Enter, u, d, e) | <status per key> | <wire/none> |
| URL state (elite=1, etc.) | <status> | <add/none> |
| Backend reads mv_fund_risk_latest | <yes/no> | <refactor/none> |
| Backend uses v_screener_org_membership | <yes/no> | <refactor/none> |
| Fast-track /universe/approve for liquids | <yes/no> | <add/none> |
| DD gate in /universe/approve | <yes/no> | <add/none> |
| POST /dd-reports/queue | <yes/no> | <add/none> |
| Sparkline batch endpoint | <yes/no> | <add/none> |

## Open questions for human decision

<list of items flagged NEEDS_HUMAN_DECISION with the specific ambiguity>
```

## Constraints

- Zero file modifications
- Zero commits
- Zero git state changes
- If unsure, report ambiguity — do NOT decide
- If a file is too large to read fully, read in chunks but cover the complete file
- If you find additional Phase 3-adjacent items not in this checklist, note them in a "Section J — Other findings" at the end
- Budget: investigation should take ~20-40 minutes of agent time. If it exceeds 60 minutes, stop and report what you have with a "partial audit" flag at the top.

## Mandatory READ FIRST for context

Before executing the checklist, read:

1. `docs/plans/2026-04-11-terminal-unification-master-plan.md` Appendix B §2.3 "Screener" and §5 "Deprecation Map" — the master plan's Phase 3 vision
2. `docs/plans/2026-04-11-phase-2-session-b-analytical-layer.md` §"COMMIT 1" and §"COMMIT 2" — the ELITE column + mv_fund_risk_latest that Phase 3 consumes
3. `docs/audits/Phase-2-Scope-Audit-Investigation-Report.md` §E — the audit noted frontend already has an "elite" badge based on `managerScore >= 75`; Phase 3 must replace that hack with real `elite_flag` consumption

Begin by reading those 3 files, then work through the checklist in order.
