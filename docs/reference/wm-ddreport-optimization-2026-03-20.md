# Wealth DD Report Optimization — 2026-03-20

## Origin

During the retrieval confidence analysis (2026-03-20), the Wealth DD Report prompts were initially assessed as candidates for the same signal-aware optimization applied to Credit deep_review. That assessment was incorrect. The Wealth vertical operates on a fundamentally different data model: structured API data (YFinance, OFR Hedge Fund Monitor, future FEfundinfo), not OCR'd dataroom documents. Mutual Funds and UCITS have standardized disclosure — there is no documentary ambiguity to resolve.

This document records the correct diagnosis and the optimization path for Wealth DD Report prompts.

---

## Problem: Prompts Written for a Data Model That Doesn't Exist

The current DD chapter prompts contain hedging language designed for uncertain documentary evidence:

| Template | Current language | Problem |
|---|---|---|
| fee_analysis.j2 | "Where specific fee data is available...note the information gaps" | Fee data comes from YFinance/FEfundinfo APIs — it is either present in DB or not. There is no "where available" gradient. |
| investment_strategy.j2 | "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen" | Strategy data comes from fund factsheets ingested via API, not ad-hoc document uploads. "Additional documentation" is not the resolution path — the API either provides it or doesn't. |
| operational_dd.j2 | "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed" | Operational data (service providers, domicile, AUM, compliance status) comes from structured API fields. Site visits are out of scope for an automated DD system. |
| manager_assessment.j2 | "Provide specific evidence where available. Flag any key person dependencies" | Manager track record, AUM history, team data come from provider APIs. "Evidence where available" implies documentary uncertainty that doesn't apply. |

These prompts were written as if the LLM were analyzing OCR'd PDFs from a private credit dataroom. For Wealth, the data enters the system clean, typed, and unambiguous from external APIs. The hedging language is not just unnecessary — it actively degrades output quality by inviting the LLM to hedge on data that is either definitively present or definitively absent.

---

## Prerequisite: Verify What the LLM Actually Consumes

Before optimizing prompts, verify that the structured API data is what the LLM receives as input. Specifically:

### Audit checklist

1. **Trace the evidence_pack construction** (`vertical_engines/wealth/dd_report/evidence_pack.py`):
   - What fields come from the `instruments_universe` table (API-sourced)?
   - What fields come from quant_engine computations (deterministic)?
   - What fields, if any, come from RAG/pgvector document retrieval?
   - Is there any OCR'd document content injected into the DD chapter context?

2. **For each DD chapter, map data source to prompt input**:
   - `fee_analysis` — Does the LLM receive TER, management fee, performance fee from DB fields, or from retrieved document chunks?
   - `investment_strategy` — Does strategy description come from a DB column (API-ingested) or from RAG search?
   - `operational_dd` — Do service provider names, domicile, compliance status come from structured fields or documents?
   - `manager_assessment` — Does manager name, AUM, track record come from `instruments_universe` columns or from document retrieval?
   - `performance_analysis` — Confirmed quant-driven (sharpe, returns, drawdown from quant_engine). Verify no document dependency.
   - `risk_framework` — Confirmed quant-driven (CVaR, volatility, beta). Verify no document dependency.

3. **Check for hybrid chapters** — If any chapter mixes API-sourced structured data with RAG-sourced document content, document which fields come from which source. These chapters may need a dual approach: source-aware for structured fields, signal-aware for document fields.

4. **Check the ingestion path** — Verify that YFinance and OFR data flows into `instruments_universe` (or equivalent table) and that `evidence_pack.py` reads from those tables, not from re-processed document stores.

### Why this audit matters

If the prompts say "cite specific sources" but the LLM receives pre-computed quant metrics with no source attribution, the instruction is meaningless. If the prompts say "note information gaps" but the LLM receives null fields with no indication of whether the API was queried and returned nothing vs. was never queried, the instruction produces noise.

The prompts must match the actual data shape the LLM sees.

---

## Data Sources Post-SEC Layer Integration

After M2 of `feat/sec-data-providers-layer`, the evidence_pack for Wealth DD Report gains the following structured data sources beyond the current YFinance/OFR baseline:

| Chapter | Current source | Post-M2 source | Impact |
|---|---|---|---|
| manager_assessment | YFinance (sparse) | Form ADV via adv_service | AUM history, fees, compliance, team bios — fully structured |
| investment_strategy | Fund classification + YFinance | + 13F-HR sector allocation + drift signal | Strategy verification against actual holdings |
| operational_dd | YFinance (compliance absent) | + sec_managers.compliance_disclosures | Compliance becomes a structured integer, not an absence |
| performance_analysis | quant_engine (unchanged) | unchanged | No impact |
| risk_framework | quant_engine (unchanged) | unchanged | No impact |
| fee_analysis | YFinance/FEfundinfo | unchanged (ADV has fee types, not fund-level fees) | Partial — ADV provides fee structure type, not exact bps |

Note on fee_analysis: Form ADV Schedule D provides fee type flags (percentage_of_aum, performance_fee, hurdle_rate_type) but not the exact basis points. FEfundinfo remains the primary source for precise fee figures. The ADV data supplements but does not replace FEfundinfo for fee_analysis.

---

## Optimization: Source-Aware Prompts (Not Signal-Aware)

The Credit optimization uses **signal-aware** prompts — adapting to retrieval confidence because documentary evidence has genuine ambiguity (multiple sources, overlapping content, varying quality). That approach does not apply to Wealth.

Wealth needs **source-aware** prompts — the LLM knows what type of data it received and handles each type accordingly.

### The distinction

| Approach | When to use | What it resolves |
|---|---|---|
| **Signal-aware** (Credit) | Evidence comes from document retrieval with variable quality | Ambiguity between competing sources, confidence in ranking |
| **Source-aware** (Wealth) | Evidence comes from structured APIs with deterministic availability | Whether data is present or absent, and what absence means |

### Source-aware context block

Replace hedging language in DD chapter templates with a source-aware preamble:

```jinja2
{# ── Data Context (injected per chapter based on available structured data) ── #}

{% if structured_data_complete %}
All required data fields for this chapter are available from verified provider sources
({{ data_providers | join(', ') }}). Cite values directly. Do not hedge or qualify
data that is present — treat it as authoritative.

{% elif structured_data_partial %}
The following fields are available from provider sources: {{ available_fields | join(', ') }}.
The following fields are not available: {{ missing_fields | join(', ') }}.
For missing fields, state "[Not available from {{ primary_provider }}]" — do not speculate,
derive, or suggest alternative documentation. The data either exists in the provider or it doesn't.

{% elif structured_data_absent %}
No structured provider data is available for this chapter.
Analysis is limited to quantitative metrics from the quant engine.
State this limitation explicitly in the opening paragraph.
{% endif %}
```

### Per-chapter optimization

| Template | Current approach | Optimized approach |
|---|---|---|
| **fee_analysis.j2** | Hedges on fee data availability | If TER/mgmt_fee/perf_fee fields present → cite directly as authoritative. If null → "[Not available from YFinance/FEfundinfo]". No "information gaps" language. |
| **investment_strategy.j2** | Asks to cite documents if available | Strategy comes from fund classification + API fields. Cite the structured data. If strategy_description is null, state it — don't suggest "additional documentation." **Holdings-based strategy verification (available post-M2 SEC layer):** When `thirteenf_service` data is available for the manager, the stated strategy can be verified against actual holdings — calculated from quarterly 13F filings. Add conditional block: `{% if thirteenf_available %}` — verify stated strategy (`strategy_classification`) against 13F sector allocation (`sector_weights`), style drift signal (`drift_detected` bool), and quarters showing drift (`drift_quarters` int). If divergence exists, flag explicitly — do not reconcile or rationalize, report as finding for investment team. `{% endif %}` This transforms the chapter from "describe stated strategy" to "verify stated strategy against evidence" — a qualitative improvement in DD depth only possible with 13F data. |
| **operational_dd.j2** | Suggests site visits for missing data | Operational fields (domicile, service providers, AUM) from API. Present what exists. Missing = "[Not reported by provider]". Site visits are not in scope. **Post-M2 SEC layer compliance block:** `sec_managers.compliance_disclosures` provides an integer count from Form ADV. `{% if compliance_disclosures is not none %}` — report count with SEC/IAPD source attribution. If count > 0, flag explicitly — do not minimize, contextualize, or compare to industry norms; require investment team review. `{% else %}` — manager not in SEC registry or not verified; state "[SEC registration not confirmed — verify regulatory status via applicable jurisdiction]"; do not proceed as if compliance is clean. `{% endif %}` Note: absence now means "not found in SEC registry" rather than "provider didn't report it" — materially different meaning the prompt must communicate accurately. |
| **manager_assessment.j2** | "Evidence where available" | **Pre-M2:** YFinance does NOT provide manager-level data (AUM history, fee structure, team). Current hedging exists because the data is genuinely absent, not as a style choice — do not remove hedging until data source exists. **Post-M2 SEC layer:** `adv_service.py` provides regulatory AUM history (Form ADV Part 1A Item 5), fee structure (% of AUM, performance fees, hurdle), compliance disclosures count (`sec_managers.compliance_disclosures`), and team bios (Part 2A PDF extraction). `structured_data_complete` becomes genuinely true for this chapter only after ADV integration into `evidence_pack.py`. Key person dependency detection from structured ADV team fields, not document inference. **Dependency:** Prompt optimization is only effective after M2 SEC layer integration (`adv_service` wired into `evidence_pack.py`). Phase 1 of DD optimization for this chapter must not run before M2 completes. Removing hedging on empty fields produces worse output than the current hedging. |
| **performance_analysis.j2** | Already quant-driven | Minimal change. Confirm prompt references quant_profile fields by name. Remove any "interpret in context" hedging — the numbers are what they are. |
| **risk_framework.j2** | Already quant-driven | Minimal change. CVaR windows, volatility, beta are deterministic. Remove "flag concerning trends" hedging — the metrics either breach thresholds or they don't. |
| **executive_summary.j2** | "Evidence-based, avoid promotional language" | Keep anti-promotional instruction. Replace "evidence-based" with "data-driven" — the inputs are structured data, not evidence in the documentary sense. |
| **recommendation.j2** | Synthesis chapter, no direct evidence | No change needed — already consumes chapter_summaries from preceding chapters. |

---

## What This Does NOT Change

- **Critic prompts** — adversarial review evaluates analytical quality, not data sourcing. Keep as-is.
- **Content engines** (flash_report, investment_outlook, manager_spotlight) — consume macro/quant data directly. Prompts are already appropriate for structured inputs.
- **Fact-sheet prompts** — seeds not yet wired to LLM. Future concern.
- **Screener** — fully deterministic, no prompts.
- **Quant injection into chapters** — `quant_injection.py` already provides typed metrics. This is correct and should remain.

---

## Relationship to Credit Optimization

| Dimension | Credit deep_review | Wealth DD report |
|---|---|---|
| Primary data source | RAG from OCR'd dataroom documents | Structured API data (YFinance, OFR, FEfundinfo) |
| Ambiguity type | Multiple documents with overlapping/conflicting content | Binary: data present or absent from provider |
| Optimization approach | Signal-aware (adapt to retrieval confidence) | Source-aware (adapt to structured data availability) |
| Hedging language | Replace with confidence-conditional block | Remove entirely — hedging on structured data is noise |
| Absence handling | [DATA GAP] with derive→proxy→benchmark hierarchy | "[Not available from {provider}]" — no derivation hierarchy |
| Chapter count | 13 + critic + rewrite loop | 8 + critic (3 iterations) |
| Prompt complexity | High (fallback protocols, third-party attribution, coverage rerank) | Low-moderate (hedging language is the main issue) |

---

## Implementation Sequencing

> **Critical dependency:** Phase 0 must run after M2 of the SEC data providers layer
> (`docs/plans/2026-03-20-feat-sec-data-providers-layer-plan.md`) is complete.
> Running Phase 0 before M2 means auditing an evidence_pack that is missing
> manager-level data — the audit will incorrectly conclude that hedging is
> appropriate for manager_assessment when the real fix is upstream data integration.
> Phase 0 through Phase 3 of this plan are blocked on M2 SEC completion.

| Phase | Scope | Dependencies |
|---|---|---|
| **Phase 0** | Audit: trace evidence_pack data sources per chapter. Run AFTER M2 SEC integration so audit reflects complete data model, not interim state. | M2 SEC layer complete (adv_service + thirteenf_service wired into evidence_pack.py) |
| **Phase 1** | Remove hedging from operational_dd, fee_analysis, investment_strategy (non-manager chapters). These have stable data sources independent of SEC layer. | Phase 0 |
| **Phase 2** | Add source-aware context block with structured_data_complete/partial/absent logic. For manager_assessment: only after ADV data confirmed arriving in evidence_pack. | Phase 0 + M2 SEC |
| **Phase 3** | Add 13F holdings verification block to investment_strategy. Add compliance_disclosures block to operational_dd. Add ADV-sourced fields to manager_assessment. | M2 SEC confirmed in evidence_pack |
| **Phase 4** | Tighten quant-driven chapters (performance, risk) — reference fields by name, remove interpretive hedging. | Phase 0 |

Phase 0 is the gate. If the audit reveals that some chapters DO consume RAG document content alongside structured data, those chapters need a hybrid approach (source-aware for structured fields + signal-aware for document fields), and the optimization plan adjusts accordingly.

---

## Related Documents

- `docs/reference/deep-review-optimization-plan-2026-03-20.md` — Credit deep_review optimization (signal-aware approach)
- `docs/reference/retrieval-confidence-analysis-2026-03-20.md` — retrieval analysis that initiated this review
- `docs/audit/system-map.md` — system architecture showing API data sources (YFinance, OFR, FEfundinfo)
