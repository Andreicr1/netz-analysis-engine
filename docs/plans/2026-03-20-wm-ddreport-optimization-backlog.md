---
title: "Wealth DD Report Optimization — Implementation Backlog"
date: 2026-03-20
origin: docs/reference/wm-ddreport-optimization-2026-03-20.md
---

# Wealth DD Report Optimization — Implementation Backlog

## Status Summary (2026-03-21)

> **STATUS: PARTIALLY UNBLOCKED**
>
> SEC data providers M1 confirmed complete (Phases 1-8 DONE) per
> `docs/reference/sec-data-providers-implementation-guide.md` (2026-03-20).
> All three services (`adv_service`, `thirteenf_service`, `institutional_service`)
> are implemented with DB tables, caching, and rate limiting.
>
> **Still blocked (M2 not yet done):**
> - `adv_service` / `thirteenf_service` are NOT yet wired into
>   `vertical_engines/wealth/dd_report/evidence_pack.py` — data exists in DB
>   tables but does not flow into chapter context
> - `fetch_manager_team()` is a Stub M1 — returns `[]`, team bios require
>   Part 2A PDF OCR via Mistral (M2 scope)
> - ~~`thirteenf_service.get_sector_aggregation()` returns `asset_class` weights
>   (COM/CALL/PUT), not industry sector weights~~ RESOLVED 2026-03-21: now returns
>   GICS industry sectors via 3-tier cascade (SIC mapping, OpenFIGI/yfinance, keyword).
>   No pre-computed `drift_detected` or `drift_quarters` fields exist — Phase 3
>   must derive these from raw diffs
>
> **Unblocked phases:**
> - Phase 0 (Audit): UNBLOCKED — can run against current evidence_pack to
>   document what exists pre-M2, then identify wiring gaps
> - Phase 1 (Remove hedging): UNBLOCKED — depends only on Phase 0
> - Phase 2 (Source-aware context): UNBLOCKED — depends only on Phase 1
> - Phase 3 (SEC integration): BLOCKED — requires evidence_pack wiring (M2)
> - Phase 4 (Quant chapters): UNBLOCKED — no SEC dependency, can execute immediately

Execution order: Phase 0 → 1 → 2 → 3 → 4.
Phase 4 has no SEC dependency and can execute in parallel with 0 → 1 → 2.
Each phase is one session. `make check` must be green before closing any phase.

---

## Phase 0 — Audit (evidence_pack data source mapping)
Status: TODO (unblocked)
Blocked on: (none — SEC M1 services are available for querying; audit documents current state pre-M2 wiring)
Exit criteria: Markdown audit artifact produced documenting, for each of the 8 DD chapters, exactly which fields the LLM receives and whether each comes from (a) `instruments_universe` table (API-sourced), (b) `quant_engine` computation, (c) RAG/pgvector retrieval, or (d) SEC data (`adv_service` / `thirteenf_service`). Any hybrid chapters (mixing structured + document sources) identified explicitly. Audit must also document which SEC fields are available in DB but NOT yet wired into evidence_pack (gap analysis for Phase 3).
Files modified:
- (none — read-only investigation)
Files created:
- `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
Tasks:
- [ ] Read `vertical_engines/wealth/dd_report/evidence_pack.py` — trace every field injected into chapter context
- [ ] For each DD chapter template (`fee_analysis`, `investment_strategy`, `operational_dd`, `manager_assessment`, `performance_analysis`, `risk_framework`, `executive_summary`, `recommendation`), map every template variable to its data source
- [ ] Check if `adv_service` fields (AUM history, fees, compliance_disclosures, team bios) are wired into evidence_pack for `manager_assessment` — per implementation guide, services exist but wiring into evidence_pack is NOT confirmed; `fetch_manager_team()` is Stub M1 (returns `[]`)
- [ ] Check if `thirteenf_service` data is wired into evidence_pack for `investment_strategy` — RESOLVED 2026-03-21: `get_sector_aggregation()` now returns GICS industry sectors (Real Estate, Technology, etc.), excludes CALL/PUT; no `drift_detected`/`drift_quarters` pre-computed fields exist (must derive from `compute_diffs()`)
- [ ] Check if `sec_managers.compliance_disclosures` is wired into evidence_pack for `operational_dd` — field exists in DB as `int | None`
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
Blocked on: Phase 2 + evidence_pack wiring of SEC services (M2 scope — services exist in `data_providers/sec/` but are not yet wired into `vertical_engines/wealth/dd_report/evidence_pack.py`)
Exit criteria: `investment_strategy.j2` includes 13F holdings verification conditional block (`{% if thirteenf_available %}` with `sector_weights`, `drift_detected`, `drift_quarters`). `operational_dd.j2` includes compliance_disclosures conditional block with SEC registry absence semantics. `manager_assessment.j2` updated to use ADV-sourced fields (AUM history, fee structure, team bios) — hedging removed only for fields where ADV data is present. All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/ai_engine/prompts/wealth/dd_report/investment_strategy.j2`
- `backend/ai_engine/prompts/wealth/dd_report/operational_dd.j2`
- `backend/ai_engine/prompts/wealth/dd_report/manager_assessment.j2`
Tasks:
- [ ] Wire `thirteenf_service` data into evidence_pack for `investment_strategy` chapter: `thirteenf_available` bool, `sector_weights` dict (from `get_sector_aggregation()` — RESOLVED 2026-03-21: now returns GICS industry sectors, not COM/CALL/PUT), `concentration_metrics` dict (from `get_concentration_metrics()`). Note: `drift_detected` and `drift_quarters` must be derived from `compute_diffs()` — no pre-computed fields exist
- [ ] Add 13F holdings verification block to `investment_strategy.j2`: verify stated strategy against 13F sector allocation, flag divergence as finding for investment team (do not reconcile)
- [ ] Wire `sec_managers.compliance_disclosures` into evidence_pack for `operational_dd` chapter
- [ ] Add compliance_disclosures block to `operational_dd.j2`: report count with SEC/IAPD source, flag if > 0, absence = "[SEC registration not confirmed]" (not "provider didn't report")
- [ ] Wire ADV fields into evidence_pack for `manager_assessment` chapter: `aum_total`, `fee_types`, regulatory AUM history. Note: `fetch_manager_team()` is Stub M1 (returns `[]`) — team bios unavailable until Part 2A OCR is implemented (M2)
- [ ] Update `manager_assessment.j2`: remove hedging for ADV-sourced fields only (AUM, fees, compliance). Key person detection from structured ADV team fields deferred until `fetch_manager_team()` stub is resolved
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:

---

## Phase 4 — Tighten quant-driven chapters
Status: TODO (unblocked)
Blocked on: Phase 0. No SEC dependency — can execute immediately in parallel with Phases 1-2.
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
