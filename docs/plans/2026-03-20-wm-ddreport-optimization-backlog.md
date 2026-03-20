---
title: "Wealth DD Report Optimization — Implementation Backlog"
date: 2026-03-20
origin: docs/reference/wm-ddreport-optimization-2026-03-20.md
---

# Wealth DD Report Optimization — Implementation Backlog

> **STATUS (2026-03-20): ALL PHASES BLOCKED**
>
> This backlog depends on M2 of the SEC data providers layer
> (`docs/plans/2026-03-20-feat-sec-data-providers-layer-backlog.md`).
> Specifically, Phase 6 (13F Service) and Phase 7 (Institutional Service)
> must be Status: DONE before Phase 0 of this backlog can run.
>
> Current SEC layer status:
> - Phase 9 (Package Setup): DONE
> - Phase 1 (Shared Infrastructure): TODO
> - Phase 2 (credit/edgar Refactor): TODO
> - Phase 3 (Import-Linter Contracts): TODO
> - Phase 4 (Alembic Migration): TODO
> - Phase 5 (ADV Service): TODO
> - Phase 6 (13F Service): TODO <-- blocks this backlog
> - Phase 7 (Institutional Service): TODO <-- blocks this backlog
> - Phase 8 (Tests): TODO
>
> Do not execute any phase below until SEC layer M2 is complete.

Execution order: Phase 0 → 1 → 2 → 3 → 4.
Each phase is one session. `make check` must be green before closing any phase.

---

## Phase 0 — Audit (evidence_pack data source mapping)
Status: TODO
Blocked on: SEC data providers layer M2 (Phases 6 + 7 of `2026-03-20-feat-sec-data-providers-layer-backlog.md` must be DONE)
Exit criteria: Markdown audit artifact produced documenting, for each of the 8 DD chapters, exactly which fields the LLM receives and whether each comes from (a) `instruments_universe` table (API-sourced), (b) `quant_engine` computation, (c) RAG/pgvector retrieval, or (d) SEC data (`adv_service` / `thirteenf_service`). Any hybrid chapters (mixing structured + document sources) identified explicitly. Audit runs against the post-M2 evidence_pack — not the pre-M2 version.
Files modified:
- (none — read-only investigation)
Files created:
- `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
Tasks:
- [ ] Read `vertical_engines/wealth/dd_report/evidence_pack.py` — trace every field injected into chapter context
- [ ] For each DD chapter template (`fee_analysis`, `investment_strategy`, `operational_dd`, `manager_assessment`, `performance_analysis`, `risk_framework`, `executive_summary`, `recommendation`), map every template variable to its data source
- [ ] Confirm `adv_service` fields (AUM history, fees, compliance_disclosures, team bios) are arriving in evidence_pack for `manager_assessment`
- [ ] Confirm `thirteenf_service` fields (sector_weights, drift_detected, drift_quarters) are arriving in evidence_pack for `investment_strategy`
- [ ] Confirm `sec_managers.compliance_disclosures` is arriving in evidence_pack for `operational_dd`
- [ ] Check for any RAG/pgvector document retrieval injected into any chapter context
- [ ] Identify any hybrid chapters requiring dual approach (source-aware + signal-aware)
- [ ] Write audit artifact to `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
Continuation prompt:

---

## Phase 1 — Remove hedging from stable chapters
Status: TODO
Blocked on: Phase 0
Exit criteria: `fee_analysis.j2`, `investment_strategy.j2`, `operational_dd.j2` have zero hedging language ("where available", "if document evidence", "additional documentation", "site visits"). Prompt language matches structured data model (present → cite directly, absent → "[Not available from {provider}]"). `manager_assessment.j2` is NOT modified in this phase. `executive_summary.j2` uses "data-driven" not "evidence-based". All existing DD report tests pass. `make check` green.
Files modified:
- `backend/ai_engine/prompts/wealth/dd_report/fee_analysis.j2`
- `backend/ai_engine/prompts/wealth/dd_report/investment_strategy.j2`
- `backend/ai_engine/prompts/wealth/dd_report/operational_dd.j2`
- `backend/ai_engine/prompts/wealth/dd_report/executive_summary.j2`
Tasks:
- [ ] Read current `fee_analysis.j2` — remove "Where specific fee data is available...note the information gaps" hedging. Replace with: present fields cited directly as authoritative, null fields → "[Not available from YFinance/FEfundinfo]"
- [ ] Read current `investment_strategy.j2` — remove "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen" hedging. Replace with: cite structured data directly, null strategy_description → state it plainly
- [ ] Read current `operational_dd.j2` — remove "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed" hedging. Replace with: present what exists, missing → "[Not reported by provider]", no site visit language
- [ ] Read current `executive_summary.j2` — replace "evidence-based" with "data-driven"
- [ ] Do NOT touch `manager_assessment.j2` — hedging is correct pre-ADV integration
- [ ] Run existing DD report tests to confirm no regressions
- [ ] Run `make check`
Continuation prompt:

---

## Phase 2 — Source-aware context block
Status: TODO
Blocked on: Phase 1
Exit criteria: All 8 DD chapter templates include the source-aware context preamble (`structured_data_complete` / `structured_data_partial` / `structured_data_absent`). `evidence_pack.py` computes `structured_data_complete`, `structured_data_partial`, `structured_data_absent`, `data_providers`, `available_fields`, `missing_fields`, `primary_provider` per chapter and injects them into template context. For `manager_assessment`: `structured_data_complete` is true only when ADV data is present in evidence_pack (not when YFinance-only). All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/ai_engine/prompts/wealth/dd_report/fee_analysis.j2`
- `backend/ai_engine/prompts/wealth/dd_report/investment_strategy.j2`
- `backend/ai_engine/prompts/wealth/dd_report/operational_dd.j2`
- `backend/ai_engine/prompts/wealth/dd_report/manager_assessment.j2`
- `backend/ai_engine/prompts/wealth/dd_report/performance_analysis.j2`
- `backend/ai_engine/prompts/wealth/dd_report/risk_framework.j2`
- `backend/ai_engine/prompts/wealth/dd_report/executive_summary.j2`
- `backend/ai_engine/prompts/wealth/dd_report/recommendation.j2`
Tasks:
- [ ] Add source-aware context computation to `evidence_pack.py`: per-chapter field availability check, provider attribution, complete/partial/absent classification
- [ ] For `manager_assessment`: `structured_data_complete` requires ADV fields present (not just YFinance) — if ADV absent, classify as `structured_data_partial` at best
- [ ] Add source-aware Jinja2 preamble block to all 8 chapter templates (per optimization plan)
- [ ] Verify template variables (`data_providers`, `available_fields`, `missing_fields`, `primary_provider`) are populated correctly for each chapter
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:

---

## Phase 3 — SEC layer integration (13F verification, compliance, ADV fields)
Status: TODO
Blocked on: Phase 2 + M2 SEC layer confirmed in evidence_pack
Exit criteria: `investment_strategy.j2` includes 13F holdings verification conditional block (`{% if thirteenf_available %}` with `sector_weights`, `drift_detected`, `drift_quarters`). `operational_dd.j2` includes compliance_disclosures conditional block with SEC registry absence semantics. `manager_assessment.j2` updated to use ADV-sourced fields (AUM history, fee structure, team bios) — hedging removed only for fields where ADV data is present. All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/ai_engine/prompts/wealth/dd_report/investment_strategy.j2`
- `backend/ai_engine/prompts/wealth/dd_report/operational_dd.j2`
- `backend/ai_engine/prompts/wealth/dd_report/manager_assessment.j2`
Tasks:
- [ ] Wire `thirteenf_service` data into evidence_pack for `investment_strategy` chapter: `thirteenf_available` bool, `sector_weights` dict, `drift_detected` bool, `drift_quarters` int
- [ ] Add 13F holdings verification block to `investment_strategy.j2`: verify stated strategy against 13F sector allocation, flag divergence as finding for investment team (do not reconcile)
- [ ] Wire `sec_managers.compliance_disclosures` into evidence_pack for `operational_dd` chapter
- [ ] Add compliance_disclosures block to `operational_dd.j2`: report count with SEC/IAPD source, flag if > 0, absence = "[SEC registration not confirmed]" (not "provider didn't report")
- [ ] Wire ADV fields into evidence_pack for `manager_assessment` chapter: regulatory AUM history, fee structure, team bios
- [ ] Update `manager_assessment.j2`: remove hedging for ADV-sourced fields only, key person detection from structured ADV team fields
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:

---

## Phase 4 — Tighten quant-driven chapters
Status: TODO
Blocked on: Phase 0
Exit criteria: `performance_analysis.j2` references `quant_profile` fields by name (sharpe, returns, drawdown, etc.) — no generic "interpret in context" hedging. `risk_framework.j2` references CVaR windows, volatility, beta by name — no "flag concerning trends" hedging, only threshold-based language. All existing DD report tests pass. `make check` green.
Files modified:
- `backend/ai_engine/prompts/wealth/dd_report/performance_analysis.j2`
- `backend/ai_engine/prompts/wealth/dd_report/risk_framework.j2`
Tasks:
- [ ] Read current `performance_analysis.j2` — confirm it references quant_profile fields by name. Remove any "interpret in context" or interpretive hedging. Numbers are deterministic — state them.
- [ ] Read current `risk_framework.j2` — confirm it references CVaR, volatility, beta fields by name. Remove "flag concerning trends" hedging — metrics either breach thresholds or they don't.
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:
