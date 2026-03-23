---
title: "Wealth DD Report Optimization — Implementation Backlog"
date: 2026-03-20
origin: docs/reference/wm-ddreport-optimization-2026-03-20.md
---

# Wealth DD Report Optimization — Implementation Backlog

> **STATUS (2026-03-23): UNBLOCKED — SEC layer M2 complete**
>
> SEC data providers layer dependency is fully satisfied (all phases DONE).
> All phases below are now executable in order: 0 → 1 → 2 → 3 → 4.
>
> SEC layer status (verified 2026-03-23):
> - Phase 9 (Package Setup): DONE
> - Phase 1 (Shared Infrastructure): DONE
> - Phase 2 (credit/edgar Refactor): DONE
> - Phase 3 (Import-Linter Contracts): DONE
> - Phase 4 (Alembic Migration): DONE
> - Phase 5 (ADV Service): DONE
> - Phase 6 (13F Service): DONE
> - Phase 7 (Institutional Service): DONE
> - Phase 8 (Tests): DONE
>
> **DB-first enforcement (2026-03-23):** SEC ingestion workers created
> (`sec_13f_ingestion` lock 900_021, `sec_adv_ingestion` lock 900_022).
> SEC services now expose DB-only public methods for hot-path consumption:
> - `ThirteenFService.read_holdings()`, `read_holdings_for_date()`, `get_sector_aggregation()`, `get_concentration_metrics()`, `compute_diffs()`
> - `AdvService.fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()`
> - `InstitutionalService.read_investors_in_manager()`
>
> Phase 3 MUST use these DB-only methods in evidence_pack — NEVER `fetch_holdings()` or `discover_institutional_filers()`.

Execution order: Phase 0 → 1 → 2 → 3 → 4.
Each phase is one session. `make check` must be green before closing any phase.

---

## Phase 0 — Audit (evidence_pack data source mapping)
Status: DONE
Blocked on: (none — SEC layer M2 complete)
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
Status: DONE
Blocked on: Phase 0
Exit criteria: `fee_analysis.j2`, `investment_strategy.j2`, `operational_dd.j2` have zero hedging language ("where available", "if document evidence", "additional documentation", "site visits"). Prompt language matches structured data model (present → cite directly, absent → "[Not available from {provider}]"). `manager_assessment.j2` is NOT modified in this phase. `executive_summary.j2` uses "data-driven" not "evidence-based". All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/executive_summary.j2`
Tasks:
- [ ] Read current `fee_analysis.j2` — remove "Where specific fee data is available...note the information gaps" hedging. Replace with: present fields cited directly as authoritative, null fields → "[Not available from YFinance/FEfundinfo]"
- [ ] Read current `investment_strategy.j2` — remove "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen" hedging. Replace with: cite structured data directly, null strategy_description → state it plainly
- [ ] Read current `operational_dd.j2` — remove "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed" hedging. Replace with: present what exists, missing → "[Not reported by provider]", no site visit language
- [ ] Read current `executive_summary.j2` — replace "evidence-based" with "data-driven"
- [ ] Do NOT touch `manager_assessment.j2` — hedging is correct pre-ADV integration
- [ ] Run existing DD report tests to confirm no regressions
- [ ] Run `make check`
Continuation prompt:

```
Read `docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md` before doing anything.

Phase 0 (Audit) is DONE. Exit criteria met:
- Audit artifact: `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
- All 8 chapters mapped to data sources (Fund table, FundRiskMetrics, empty placeholders)
- Hedging language inventoried per chapter with action assignments

Phase 0 findings critical for Phase 1:
- Templates are at `backend/vertical_engines/wealth/prompts/dd_chapters/*.j2` (NOT `backend/ai_engine/prompts/`)
- Templates are resolved via `get_prompt_registry()` with search path registered in `vertical_engines/wealth/__init__.py`
- The template prefix used in code is `dd_chapters/{chapter_tag}.j2` (see `chapters.py:67`)

Runtime observations from Phase 0:
- `make check` has a PRE-EXISTING import-linter violation: `data_providers.sec.seed.populate_seed` → `app.services.storage_client` → `ai_engine`. This is NOT from DD report work — it existed before. Architecture gate will fail until this is fixed separately. Tests and lint pass.
- `documents`, `scoring_data`, `macro_snapshot` fields on EvidencePack are declared but NEVER populated by the engine
- `filter_for_chapter("fee_analysis")` zeroes out `quant_profile` and `risk_metrics` — fee chapter gets identity fields only
- No SEC data (`adv_service`, `thirteenf_service`) is wired into evidence_pack yet

Execute Phase 1 next: Remove hedging from stable chapters.

Files to modify (4 Jinja2 templates):
1. `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2` — line 25: remove "Where specific fee data is available from documents, cite exact figures. Where not, note the information gaps." Replace with: "State available fee data directly. For fields not available from the data provider, write '[Not available from YFinance/FEfundinfo]' instead of speculating."
2. `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2` — line 25: remove "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen the analysis." Replace with: "Base your analysis on the fund identity and classification data provided. For strategy details not available from structured data, state plainly that the information is not available rather than speculating."
3. `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2` — line 24: remove "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed." Replace with: "Assess operational infrastructure based on available data. For information not reported by the data provider, write '[Not reported by provider]'. Do not reference site visits or calls."
4. `backend/vertical_engines/wealth/prompts/dd_chapters/executive_summary.j2` — line 33: replace "evidence-based" with "data-driven"

DO NOT modify `manager_assessment.j2` — its hedging ("Provide specific evidence where available") is correct because ADV data is not yet wired (Phase 3).

After modifying templates:
- Run `make test` to confirm no DD report test regressions
- Note: `make check` will fail on the pre-existing import-linter violation — this is expected and not a blocker for Phase 1 exit criteria (the violation is unrelated to DD report work)
- Mark Phase 1 as DONE in the backlog
- Write the continuation prompt for Phase 2
```

---

## Phase 2 — Source-aware context block
Status: DONE
Blocked on: Phase 1
Exit criteria: All 8 DD chapter templates include the source-aware context preamble (`structured_data_complete` / `structured_data_partial` / `structured_data_absent`). `evidence_pack.py` computes `structured_data_complete`, `structured_data_partial`, `structured_data_absent`, `data_providers`, `available_fields`, `missing_fields`, `primary_provider` per chapter and injects them into template context. For `manager_assessment`: `structured_data_complete` is true only when ADV data is present in evidence_pack (not when YFinance-only). All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/vertical_engines/wealth/prompts/dd_chapters/fee_analysis.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/performance_analysis.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/risk_framework.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/executive_summary.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/recommendation.j2`
Tasks:
- [ ] Add source-aware context computation to `evidence_pack.py`: per-chapter field availability check, provider attribution, complete/partial/absent classification
- [ ] For `manager_assessment`: `structured_data_complete` requires ADV fields present (not just YFinance) — if ADV absent, classify as `structured_data_partial` at best
- [ ] Add source-aware Jinja2 preamble block to all 8 chapter templates (per optimization plan)
- [ ] Verify template variables (`data_providers`, `available_fields`, `missing_fields`, `primary_provider`) are populated correctly for each chapter
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:

```
Read `docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md` before doing anything.

Phase 0 (Audit) is DONE. Phase 1 (Remove hedging) is DONE. Phase 2 (Source-aware context block) is DONE.

Key context from prior phases:
- Audit artifact: `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
- Templates at `backend/vertical_engines/wealth/prompts/dd_chapters/*.j2`
- Evidence pack at `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- Chapter rendering at `backend/vertical_engines/wealth/dd_report/chapters.py`
- All 8 templates now have source-aware preamble (structured_data_complete/partial/absent)
- `compute_source_metadata(chapter_tag)` on EvidencePack returns availability dict per chapter
- `_CHAPTER_FIELD_EXPECTATIONS` in evidence_pack.py defines per-chapter expected fields + providers
- `generate_chapter()` in chapters.py accepts optional `evidence_pack` kwarg, injects source metadata into template context
- `dd_report_engine.py` passes `evidence_pack=evidence` to both parallel and recommendation generate_chapter calls
- `manager_assessment` expects ADV fields (adv_aum_history, adv_compliance_disclosures, adv_team) — always partial/absent until Phase 3 wires SEC data
- No SEC data wired into evidence_pack yet — this phase does it
- `make check` has a PRE-EXISTING import-linter violation unrelated to DD report work

Execute Phase 3 next: SEC layer integration.

The goal: wire SEC EDGAR data (13F holdings, ADV manager info) into evidence_pack so templates receive real regulatory data. Three integration points:

1. **investment_strategy.j2** — 13F holdings verification:
   - Wire `ThirteenFService.get_sector_aggregation()` and `compute_diffs()` (DB-only methods) into evidence_pack
   - Add fields: `thirteenf_available` (bool), `sector_weights` (dict), `drift_detected` (bool), `drift_quarters` (int)
   - Add conditional block to template: verify stated strategy against 13F sector allocation
   - NEVER call `fetch_holdings()` — that triggers EDGAR API, workers-only

2. **operational_dd.j2** — compliance disclosures:
   - Wire `AdvService.fetch_manager()` (DB-only) → `sec_managers.compliance_disclosures` into evidence_pack
   - Add `compliance_disclosures` field to evidence_pack
   - Add conditional block to template: report count with SEC/IAPD source, flag if > 0
   - Absence = "[SEC registration not confirmed]"

3. **manager_assessment.j2** — ADV-sourced manager profile:
   - Wire `AdvService.fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()` (all DB-only) into evidence_pack
   - Add fields: `adv_aum_history`, `adv_fee_structure`, `adv_team` (list of team members)
   - Update template: remove hedging for ADV-sourced fields only, add key person detection
   - Update `_CHAPTER_FIELD_EXPECTATIONS["manager_assessment"]` — when ADV fields are populated, chapter can be `structured_data_complete`

After modifications:
- Update `_CHAPTER_FIELD_EXPECTATIONS` for investment_strategy to include 13F fields
- Update `_CHAPTER_FIELD_EXPECTATIONS` for operational_dd to include compliance_disclosures
- Run `make test` — confirm no regressions
- Mark Phase 3 as DONE in the backlog
- Write the continuation prompt for Phase 4
```

---

## Phase 3 — SEC layer integration (13F verification, compliance, ADV fields)
Status: DONE
Blocked on: Phase 2 (SEC layer M2 confirmed complete 2026-03-23)
Exit criteria: `investment_strategy.j2` includes 13F holdings verification conditional block (`{% if thirteenf_available %}` with `sector_weights`, `drift_detected`, `drift_quarters`). `operational_dd.j2` includes compliance_disclosures conditional block with SEC registry absence semantics. `manager_assessment.j2` updated to use ADV-sourced fields (AUM history, fee structure, team bios) — hedging removed only for fields where ADV data is present. All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- `backend/vertical_engines/wealth/prompts/dd_chapters/investment_strategy.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/operational_dd.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/manager_assessment.j2`
Files created:
- `backend/vertical_engines/wealth/dd_report/sec_injection.py`
Files also modified (wiring):
- `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`
- `backend/vertical_engines/wealth/dd_report/chapters.py`
Tasks:
- [x] Wire `ThirteenFService.get_sector_aggregation()` and `compute_diffs()` (DB-only) into evidence_pack for `investment_strategy` chapter: `thirteenf_available` bool, `sector_weights` dict, `drift_detected` bool, `drift_quarters` int. Use `read_holdings()` NOT `fetch_holdings()`.
- [x] Add 13F holdings verification block to `investment_strategy.j2`: verify stated strategy against 13F sector allocation, flag divergence as finding for investment team (do not reconcile)
- [x] Wire `AdvService.fetch_manager()` (DB-only) → `sec_managers.compliance_disclosures` into evidence_pack for `operational_dd` chapter
- [x] Add compliance_disclosures block to `operational_dd.j2`: report count with SEC/IAPD source, flag if > 0, absence = "[SEC registration not confirmed]" (not "provider didn't report")
- [x] Wire `AdvService.fetch_manager()`, `fetch_manager_funds()`, `fetch_manager_team()` (all DB-only) into evidence_pack for `manager_assessment` chapter: regulatory AUM history, fee structure, team bios
- [x] Update `manager_assessment.j2`: remove hedging for ADV-sourced fields only, key person detection from structured ADV team fields
- [x] Run existing DD report tests — 2630 passed
- [x] Run `make check` — tests green (pre-existing import-linter violation unrelated)
Continuation prompt:

```
Read `docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md` before doing anything.

Phase 0 (Audit) is DONE. Phase 1 (Remove hedging) is DONE. Phase 2 (Source-aware context block) is DONE. Phase 3 (SEC layer integration) is DONE.

Key context from prior phases:
- Audit artifact: `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
- Templates at `backend/vertical_engines/wealth/prompts/dd_chapters/*.j2`
- Evidence pack at `backend/vertical_engines/wealth/dd_report/evidence_pack.py`
- Chapter rendering at `backend/vertical_engines/wealth/dd_report/chapters.py`
- SEC injection at `backend/vertical_engines/wealth/dd_report/sec_injection.py`
- All 8 templates have source-aware preamble (structured_data_complete/partial/absent)
- `sec_injection.py` provides sync DB queries: `gather_sec_13f_data()` and `gather_sec_adv_data()`
- SEC linkage: Fund.manager_name → sec_managers.firm_name (case-insensitive) → cik/crd_number
- `investment_strategy.j2` now has 13F sector weights + drift detection block
- `operational_dd.j2` now has compliance_disclosures block with SEC registry absence semantics
- `manager_assessment.j2` now has ADV AUM, fee structure, team bios with key person detection
- `_CHAPTER_FIELD_EXPECTATIONS` updated for investment_strategy (13F fields) and operational_dd (compliance_disclosures)
- `make check` has a PRE-EXISTING import-linter violation unrelated to DD report work

Execute Phase 4 next: Tighten quant-driven chapters.

The goal: remove interpretive hedging from performance_analysis.j2 and risk_framework.j2. These chapters receive full quant_profile and risk_metrics — numbers are deterministic, not speculative.

1. **performance_analysis.j2** — references quant_profile fields by name:
   - Remove any "interpret in context" or interpretive hedging
   - Sharpe, returns, drawdown are computed numbers — state them directly
   - Numbers either meet institutional thresholds or they don't

2. **risk_framework.j2** — references CVaR, volatility, beta by name:
   - Remove "flag concerning trends" hedging
   - CVaR windows, volatility, beta are deterministic — threshold-based language only
   - Metrics breach thresholds or they don't — no "may indicate" hedging

After modifications:
- Run `make test` — confirm no regressions
- Mark Phase 4 as DONE in the backlog
```

---

## Phase 4 — Tighten quant-driven chapters
Status: DONE
Blocked on: Phase 0
Exit criteria: `performance_analysis.j2` references `quant_profile` fields by name (sharpe, returns, drawdown, etc.) — no generic "interpret in context" hedging. `risk_framework.j2` references CVaR windows, volatility, beta by name — no "flag concerning trends" hedging, only threshold-based language. All existing DD report tests pass. `make check` green.
Files modified:
- `backend/vertical_engines/wealth/prompts/dd_chapters/performance_analysis.j2`
- `backend/vertical_engines/wealth/prompts/dd_chapters/risk_framework.j2`
Tasks:
- [ ] Read current `performance_analysis.j2` — confirm it references quant_profile fields by name. Remove any "interpret in context" or interpretive hedging. Numbers are deterministic — state them.
- [ ] Read current `risk_framework.j2` — confirm it references CVaR, volatility, beta fields by name. Remove "flag concerning trends" hedging — metrics either breach thresholds or they don't.
- [ ] Run existing DD report tests
- [ ] Run `make check`
Continuation prompt:
