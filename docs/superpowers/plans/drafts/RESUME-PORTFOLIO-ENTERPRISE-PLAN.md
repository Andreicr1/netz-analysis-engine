# Resume — Portfolio Enterprise Workbench Plan

> **Status:** 5 specialist drafts complete, final unified plan pending. Created 2026-04-08 to survive computer restart / session handoff.

## Context for new session

Andrei asked for a Portfolio vertical rebuild at the same quality bar as the Discovery FCL plan (`docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md`). 5 specialist agents were dispatched in parallel, all completed, and wrote design drafts to this `drafts/` folder.

Then a 6th "stitching" agent was dispatched to merge the 5 drafts into a single unified implementation plan at `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`. It crashed twice with API 529 Overloaded. User chose to pause and let the API recover.

## What exists (do not redo)

5 completed design drafts in this folder:

| File | Author agent | Status |
|---|---|---|
| `portfolio-enterprise-ux-flow.md` | wealth-ux-flow-architect | COMPLETE (720 lines) — URL contract, state machine, TerminalShell, jargon translation, 13-phase sequence |
| `portfolio-enterprise-db.md` | financial-timeseries-db-architect | COMPLETE (548 lines) — migrations 0097-0104, 6 new tables, live_price_poll worker lock 900_100 |
| `portfolio-enterprise-components.md` | svelte5-frontend-consistency | COMPLETE (731 lines) — 29-component MOCK/REAL audit, CalibrationPanel, ConstructionNarrative |
| `portfolio-enterprise-charts.md` | wealth-echarts-specialist | COMPLETE (676 lines) — WorkbenchCoreChart, SSE+tickBuffer, SVG sparklines, chartTokens variant |
| `portfolio-enterprise-quant.md` | wealth-portfolio-quant-architect | COMPLETE (939 lines) — 63 calibration inputs, narrative payload contract, validation gate, advisor surfacing |

## Critical findings (already in drafts)

1. **`PolicyPanel.svelte` é MOCK literal** — `portfolio-workspace.svelte.ts:684-688`, `updatePolicy()` é no-op
2. **2 sliders UI vs 63 inputs no quant engine** — tiered Basic (6) / Advanced (11) / Expert (46)
3. **Construction Advisor já existe** — 789 linhas em `backend/vertical_engines/wealth/model_portfolio/construction_advisor.py`, wired to `POST /model-portfolios/{id}/construction-advice`, só NÃO embutido na response do `/construct`
4. **Optimizer_trace é o campo mais crítico** — hoje o `optimize_fund_portfolio` loga phase/solver/iterations via `structlog` e descarta. Exposure é enabler da ConstructionNarrative
5. **validation_gate.py NÃO EXISTE** — só `Composition.validate_weights()` (sum-to-1). Quant draft especifica 15 checks novos
6. **Current migration head real: `0096_discovery_fcl_keyset_indexes`** — CLAUDE.md diz 0095 (stale). Portfolio migrations começam em 0097
7. **Stress test backend já tem 4 cenários** (`gfc_2008`, `covid_2020`, `taper_2013`, `rate_shock_200bps`) — é bug frontend que não expõe, não gap backend

## Cross-draft convergences (write ONCE in unified plan)

- **State machine backend-authoritative com `allowed_actions`** (UX + DB)
- **Narrative JSONB persistent replayable** (UX + DB + components + quant)
- **`optimizer_trace` exposure BEFORE `ConstructionNarrative.svelte`** — hard dependency, sequence phases accordingly
- **Advisor fold into `response.advisor`** (quant + UX + components)
- **PolicyPanel fix = CalibrationPanel with Preview/Apply** (UX drawer + components panel — same thing, name it ONCE)
- **TerminalShell (UX) = WorkbenchLayout (components) = chartTokens('workbench') variant (charts)** — same primitive, pick ONE name

## Cross-draft divergences to reconcile in unified plan

- UX proposes 13 phases, DB proposes migrations 0097-0104 — sequence so migrations fall inside phase boundaries
- Quant lists 15 validation_gate checks, UX only mentions validation as gate G3 — put quant's 15-check list inside gate G3 task
- Charts `chartTokens('workbench')` variant + UX admin-config via ConfigService — reconcile as token-based with admin override

## What's pending

**Task #6: Stitch the 5 drafts into unified plan**

Target path: `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`

Format: mirror Discovery plan structure (Phase 0 diagnostics → N + self-review). Target 2500-5000 lines OR leaner 1200-1500 line "orchestral playbook" variant that cross-references drafts for detail.

## How to resume in a new session

Paste the following prompt verbatim in a new Claude Code session:

---

```
Continue the Portfolio Enterprise Workbench planning task. Full state is in
docs/superpowers/plans/drafts/RESUME-PORTFOLIO-ENTERPRISE-PLAN.md — read that
file first for context.

The 5 specialist drafts in docs/superpowers/plans/drafts/ are complete. I need
the unified stitched plan at
docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md.

Previous attempts to dispatch this as a background agent failed with API 529
Overloaded. Try once more in background mode; if it fails again, write the
leaner 1200-1500 line "orchestral playbook" variant directly in the foreground
that cross-references the drafts by section rather than inlining all code
snippets.

Quality bar: docs/superpowers/plans/2026-04-07-discovery-fcl-analysis-page.md
Respect: Andrei's product-facing-first rule (Builder + Analytics ship before
Live). Migrations start at 0097 (current head is 0096_discovery_fcl_keyset_indexes).
Consolidate all ~50 open decisions from the 5 drafts into a single BLOCKING
section at the top with IDs OD-1..OD-N.
```

---

## Memory anchors that must be respected

All 5 drafts referenced these. New session should honor them:

- smart-backend / dumb-frontend — sanitize jargon (no CVaR / regime / CLARABEL leaking to end users)
- Tokens = admin config, never hex in plans
- No localStorage / sessionStorage — URL + Redis only
- Formatter discipline via @netz/ui (no `.toFixed`, `.toLocaleString`, inline `Intl.*`)
- Layout cage pattern `calc(100vh-88px) + padding:24px`
- Universe lives in Portfolio Builder (sub-pill, never standalone route)
- Visual validation in browser mandatory
- Never remove "unused" methods (yagni-agent danger)
- Stability guardrails P1-P6
- DB-first for external data, advisory locks via integer literals or `zlib.crc32` (never `hash()`)
- ConfigService for runtime config (YAML is seed only)
- Prompts are Netz IP (Jinja2 SandboxedEnvironment for narrative templater)

## TaskList state

Task #6 (stitch) was `in_progress`. Tasks #1-#5 (the 5 specialists) are `completed`. TaskList resets on new session — new session should recreate the single task for the stitch or proceed directly.

## Branch state

Branch `feat/discovery-fcl`. Discovery plan being executed in parallel. Portfolio work has not started — only planning.

Uncommitted per last git status check:
- `backend/app/domains/wealth/workers/regime_fit.py` (modified) — needs inspection before Phase 0 of portfolio plan
- Several Discovery-phase untracked files for the in-flight Discovery Phase 5 work

## Open question catalogue (preview)

The unified plan must consolidate these into a single BLOCKING section. Short version:

**Lifecycle & states** — drop legacy `status` column? 4-eyes for 1-user orgs? Live-in-place vs spawn-draft on rebalance accept? (UX #3, DB #2, Components #8)

**Calibration scope** — all 63 inputs in v1, or staged Basic → Advanced → Expert across sprints? Paired slider+numeric? (Quant #1, Components #2, #9)

**Advisor** — fold into Construct response (recommended) or keep separate? When NOT to auto-run? Surface as BuilderRightStack tab, modal, or banner? (Quant C.2-C.3, Components #8)

**Stress scenarios** — 4 presets only or add custom scenario authoring? UI: single panel with dropdown or two-tab (ScenarioMatrix + CustomShock)? (Quant J.1, Components #3)

**Live price** — Yahoo 15min delay acceptable or need intraday provider (IEX/Polygon)? No `nav_intraday` hypertable (DB defer) or add now? (DB #4, #5, Charts H.2)

**Validation gate strictness** — hard block on activation or soft with IC chair override + audit? (Quant J.1.3)

**Narrative language** — PT/EN i18n required for v1, or EN only? Deterministic templater (recommended) or LLM? (UX #5, Quant J.1.2)

**Jargon labels** — "Cautious/Balanced/Growth/Stress" for regime, or Andrei's preference? Translation table in UX §10 is the normative draft (UX #8, Quant B.5)

**Workbench density** — 10px font aggressive vs 11px safer? `TerminalShell` tokens admin-configurable or hardcoded v1? (UX #10, Charts H.3, Components #7)

**Legacy routes** — delete `/portfolio/advanced`, `/portfolio/model`? Rename `PortfolioOverview.svelte`? (UX #9, Components #5, #6)

**Alert dedupe** — materialized `dedupe_key` column + UNIQUE partial index vs app-level dedupe on JSONB path? Portfolio-scoped drift fanout vs instrument-centric join? (DB #7, #8)

**Profile vs portfolio_id coexistence** — dual-table for 1-2 quarters (recommended) or hard cutover? Retention on `portfolio_construction_runs` / `portfolio_alerts`? (DB #1, #9)

Full list with IDs and source attribution lives in each draft's final section — the unified plan consolidates.

---

End of resume document.
