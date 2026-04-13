# Advisor Handoff Context — Session 2026-04-13

**Role:** You are the wealth-architect advisor for Netz Analysis Engine. Andrei delegates prompt writing to you, then executes prompts via separate Opus agent sessions. You review results, merge PRs, and plan next steps.

**Workflow established this session:**
1. Andrei describes what needs doing
2. You launch specialist agents (wealth-architect, svelte5-frontend-consistency, wealth-echarts-specialist, etc.) to research and generate precise execution prompts
3. Prompts are committed to `docs/prompts/` with exact file paths, line numbers, code blocks
4. Andrei executes prompts in parallel Opus sessions
5. When execution is clean (tests pass, lint clean), you open PR, merge, and prepare next step — no confirmation needed (memory: `feedback_clean_execution_merge.md`)

---

## What Was Delivered Today (17 PRs merged)

**Regime fixes:**
- PR #139: TAA regime signal fix — 3 missing signals (35% weight), `build_regime_inputs()` as single authoritative builder
- PR #140: Global `macro_regime_snapshot` table — decouple raw regime from org scope

**Harmonization H0-H5 (6-agent audit → 6 sessions):**
- PR #141: H0+H1 combined — Layer 2/3 primitives (Panel, PanelHeader, SplitPane, StackedPanels, StatSlab, KeyValueStrip, LiveDot) + LW-charts factory (`terminal-lw-options.ts`) + SSE sanitization (3 backend files) + 22 jargon leaks fixed across 16 files
- PR #142: H3 — CalibrationPanel terminal-ization (--ii-* to --terminal-*, Urbanist to mono, radius to 0, Select/Button/Tabs to terminal-native)
- PR #143: H2 — Live LW charts tokenized, border fixes, LiveDot composition
- PR #144: Builder layout (removed duplicate regime, RunControls inside card)
- PR #145: H5 — Navigation (goto fix, lifecycle links, choreo wiring, border consistency)
- PR #146: H4 — Screener 115 hex→token migration, Urbanist→mono, $app/state, formatter fixes

**Features:**
- PR #148: Builder REGIME tab — regime history chart (markArea bands + S&P500 line), signal breakdown, allocation bands. New `GET /allocation/regime-overlay` endpoint.
- PR #149: Screener sort headers — clickable columns, 3-state toggle (desc→asc→clear), null-to-bottom
- PR #150: Live layout redesign — 3-col redistribution (Alerts+TradeLog→left, News+Macro→right), drift→alert conversion

**Bug fixes & polish:**
- PR #147: Live chart string coercion (`Number()` instead of `as number`), Builder dual scrollbar fix
- PR #151: Removed redundant RegimeContextStrip from Builder left column
- PR #152: PortfolioSummary as vertical panel beside Holdings (sub-grid `200px 1fr`)
- PR #153: Same PR as #152 correction
- PR #154: Live zero-padding LayoutCage (full-bleed dashboard)
- PR #155: Live columns equalized (280px/280px), hairline borders, monospace font fallbacks

---

## Master Plan Status

Plan: `docs/plans/2026-04-11-terminal-unification-master-plan.md`

| Phase | Status | Notes |
|---|---|---|
| 1 — Primitives | DONE | choreo, factory, FocusMode, Shell, Layer 2/3 |
| 2 — Backend gaps | PARTIAL | SSE sanitization done, ELITE done, ReadOnlyRouteGate deferred |
| 3 — Screener | PARTIAL | Tokens migrated, sort added, fast-track flow still pending |
| 4 — Builder | DONE | 3 sessions + REGIME tab + CalibrationPanel terminal-ized |
| 5 — Live | DONE | 4 sessions + layout redesign + polish iterations |
| 6 — DD Track | PENDING | Next priority option |
| 7 — Macro Desk | PENDING | Next priority option |
| 8 — Research | PENDING | |
| 9 — (app)/ freeze | PENDING | Last phase |

---

## Next Steps (Phase 6 and/or 7)

### Phase 6 — DD Track (illiquids parallel lane)
- `/(terminal)/dd` — 3-column Kanban: Pending / In Report / In Critic Review / Approved
- DD Queue aggregator endpoint `GET /dd-reports/queue` (backend gap)
- Long-form DD SSE stream (8 chapters) via `long_form_report` engine (already built)
- Chapter Viewer with evidence pack, confidence score, critic observations
- `[APPROVE]`/`[REJECT]` gates fund into universe (branches on `universe IN ('private_us','bdc')`)
- DD Queue badge on TopNav only when > 0 items pending

### Phase 7 — Macro Desk + Allocation Blocks
- `/(terminal)/macro` — 12-column grid: 4 regional regime tiles (US/EU/JP/EM), yield curves, macro indicator sparkline wall, flash feed (SSE)
- `/(terminal)/allocation` — strategic allocation editor: block tree | weights editor with regime-conditioned suggestions | impact preview
- Forward link: `[→ BUILDER]` carries template UUID
- Context pinning: `[PIN REGIME]` writes to context rail

---

## Open Visual Issues (from latest validation)

1. **PortfolioSummary fonts** may still render sans-serif if `--terminal-font-mono` CSS variable isn't reaching the component (fallback `"JetBrains Mono"` added in PR #155 — needs browser validation)
2. **Live chart crash** was fixed (PR #147 `Number()` coercion) but needs re-validation with real market data
3. **Builder RunControls** position (inside/outside scrollable area) may need re-validation — PR #147 fixed dual scrollbar but H5 may have interfered

---

## Key Memories to Reference

- `feedback_clean_execution_merge.md` — auto-merge clean executions
- `feedback_consultant_not_implementer.md` — role is strategic consultant + prompt writer
- `feedback_specialist_agents_for_design.md` — use 6 specialist agents before writing prompts
- `feedback_smart_backend_dumb_frontend.md` — no quant jargon in UI
- `feedback_infra_before_visual.md` — backend accuracy before frontend polish
- `project_harmonization_complete.md` — full session summary

---

## Execution Prompts Already Committed (not yet executed)

- `docs/prompts/2026-04-13-live-layout-redesign.md` — already executed as PR #150
- All H0-H5 prompts executed and merged
- REGIME tab, Screener sort, Live layout prompts executed and merged

**No pending unexecuted prompts.** Next session should generate Phase 6 and/or Phase 7 prompts.
