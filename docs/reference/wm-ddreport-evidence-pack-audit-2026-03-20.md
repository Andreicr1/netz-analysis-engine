---
title: "DD Report Evidence Pack — Data Source Audit"
date: 2026-03-23
auditor: Claude Code (Phase 0 of wm-ddreport-optimization-backlog)
---

# DD Report Evidence Pack — Data Source Audit

## Audit Scope

Traces every field injected into DD Report chapter context, mapping each to its data source:
- **(a) `instruments_universe` / Fund table** — API-sourced fund identity
- **(b) `quant_engine` computation** — `FundRiskMetrics` table (pre-computed by `risk_calc` worker)
- **(c) RAG / pgvector retrieval** — document chunks from `vector_chunks`
- **(d) SEC data** — `adv_service` / `thirteenf_service` / `institutional_service`

## Evidence Pack Construction Flow

```
Route (dd_reports.py)
  → asyncio.to_thread(_sync_generate)
    → DDReportEngine.generate(db, ...)
      → _build_evidence(db, fund_id)
        → Fund table query           → fund_data dict (11 fields)
        → gather_quant_metrics(db)    → quant_profile dict (22 fields)
        → gather_risk_metrics(db)     → risk_metrics dict (8 fields)
        → documents=[]               → NOT POPULATED (placeholder)
        → scoring_data={}            → NOT POPULATED (placeholder)
        → macro_snapshot={}          → NOT POPULATED (placeholder)
      → build_evidence_pack(fund_data, quant_profile, risk_metrics)
      → EvidencePack (frozen dataclass)
```

**Key observation:** `_build_evidence()` in `dd_report_engine.py:275-311` only queries two sources:
1. `Fund` ORM model (identity)
2. `FundRiskMetrics` ORM model (quant, via `gather_quant_metrics`)

Three EvidencePack fields are **declared but never populated**: `documents`, `scoring_data`, `macro_snapshot`.

---

## Per-Chapter Data Source Mapping

### Chapter 1: Executive Summary (`executive_summary.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `isin` | `Fund.isin` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `fund_type` | `Fund.fund_type` | (a) Fund table | ✅ Present |
| `geography` | `Fund.geography` | (a) Fund table | ✅ Present |
| `asset_class` | `Fund.asset_class` | (a) Fund table | ✅ Present |
| `aum_usd` | `Fund.aum_usd` | (a) Fund table | ✅ Present |
| `quant_profile.sharpe_1y` | `FundRiskMetrics.sharpe_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.return_1y` | `FundRiskMetrics.return_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.cvar_95_3m` | `FundRiskMetrics.cvar_95_3m` | (b) quant_engine | ✅ Present |
| `quant_profile.manager_score` | `FundRiskMetrics.manager_score` | (b) quant_engine | ✅ Present |

**Data completeness:** FULL (all structured). No documents, no SEC data.
**Hedging language:** "evidence-based" in instruction line 33 — should be "data-driven".

---

### Chapter 2: Investment Strategy (`investment_strategy.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `fund_type` | `Fund.fund_type` | (a) Fund table | ✅ Present |
| `geography` | `Fund.geography` | (a) Fund table | ✅ Present |
| `asset_class` | `Fund.asset_class` | (a) Fund table | ✅ Present |

**Data completeness:** PARTIAL — identity-only, no strategy documents, no 13F holdings.
**Hedging language:** Line 25: "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen the analysis." — **hedging to remove in Phase 1**.
**Future SEC integration (Phase 3):** `thirteenf_service` → `sector_weights`, `drift_detected`, `drift_quarters` for 13F holdings verification.

---

### Chapter 3: Manager Assessment (`manager_assessment.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `inception_date` | `Fund.inception_date` | (a) Fund table | ✅ Present |
| `aum_usd` | `Fund.aum_usd` | (a) Fund table | ✅ Present |
| `quant_profile.manager_score` | `FundRiskMetrics.manager_score` | (b) quant_engine | ✅ Present |
| `quant_profile.score_components` | `FundRiskMetrics.score_components` | (b) quant_engine | ✅ Present |
| `quant_profile.return_3y_ann` | `FundRiskMetrics.return_3y_ann` | (b) quant_engine | ✅ Present |
| `quant_profile.sharpe_3y` | `FundRiskMetrics.sharpe_3y` | (b) quant_engine | ✅ Present |

**Data completeness:** PARTIAL — has quant metrics but NO manager-specific SEC data (ADV AUM history, fee structure, team bios, compliance disclosures).
**Hedging language:** Line 32: "Provide specific evidence where available." — **correct hedging pre-ADV** (do NOT modify in Phase 1).
**Future SEC integration (Phase 3):** `adv_service` → AUM history, fee structure, team bios. Hedging removed only for ADV-sourced fields.

---

### Chapter 4: Performance Analysis (`performance_analysis.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `isin` | `Fund.isin` | (a) Fund table | ✅ Present |
| `quant_profile.return_1m` | `FundRiskMetrics.return_1m` | (b) quant_engine | ✅ Present |
| `quant_profile.return_3m` | `FundRiskMetrics.return_3m` | (b) quant_engine | ✅ Present |
| `quant_profile.return_6m` | `FundRiskMetrics.return_6m` | (b) quant_engine | ✅ Present |
| `quant_profile.return_1y` | `FundRiskMetrics.return_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.return_3y_ann` | `FundRiskMetrics.return_3y_ann` | (b) quant_engine | ✅ Present |
| `quant_profile.sharpe_1y` | `FundRiskMetrics.sharpe_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.sortino_1y` | `FundRiskMetrics.sortino_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.alpha_1y` | `FundRiskMetrics.alpha_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.information_ratio_1y` | `FundRiskMetrics.information_ratio_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.max_drawdown_1y` | `FundRiskMetrics.max_drawdown_1y` | (b) quant_engine | ✅ Present |

**Data completeness:** FULL (all structured quant). Pure quant-driven chapter.
**Hedging language:** Line 36: "Interpret numbers in context (peer group, market conditions). Flag any performance anomalies." — **interpretive hedging to tighten in Phase 4**.

---

### Chapter 5: Risk Management Framework (`risk_framework.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `fund_type` | `Fund.fund_type` | (a) Fund table | ✅ Present |
| `quant_profile.cvar_95_1m` | `FundRiskMetrics.cvar_95_1m` | (b) quant_engine | ✅ Present |
| `quant_profile.cvar_95_3m` | `FundRiskMetrics.cvar_95_3m` | (b) quant_engine | ✅ Present |
| `quant_profile.cvar_95_12m` | `FundRiskMetrics.cvar_95_12m` | (b) quant_engine | ✅ Present |
| `quant_profile.volatility_1y` | `FundRiskMetrics.volatility_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.beta_1y` | `FundRiskMetrics.beta_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.tracking_error_1y` | `FundRiskMetrics.tracking_error_1y` | (b) quant_engine | ✅ Present |
| `quant_profile.dtw_drift_score` | `FundRiskMetrics.dtw_drift_score` | (b) quant_engine | ✅ Present |
| `risk_metrics.cvar_windows` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.var_windows` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.volatility_1y` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.max_drawdown_1y` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.sharpe_1y` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.sortino_1y` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.beta_1y` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |
| `risk_metrics.dtw_drift_score` | derived from `FundRiskMetrics` | (b) quant_engine | ✅ Present |

**Data completeness:** FULL (all structured quant + risk). Pure quant-driven chapter.
**Hedging language:** Line 41: "Flag any concerning trends or limit breaches." — **vague hedging to tighten in Phase 4** (should be threshold-based).
**Note:** `risk_metrics` is a reshaped view of the same `FundRiskMetrics` row (via `gather_risk_metrics`), not a separate source.

---

### Chapter 6: Fee Analysis (`fee_analysis.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `fund_type` | `Fund.fund_type` | (a) Fund table | ✅ Present |
| `currency` | `Fund.currency` | (a) Fund table | ✅ Present |

**Data completeness:** MINIMAL — identity-only, no fee data from any source.
**Note:** `filter_for_chapter("fee_analysis")` explicitly zeroes out `quant_profile` and `risk_metrics`.
**Hedging language:** Line 25: "Where specific fee data is available from documents, cite exact figures. Where not, note the information gaps." — **hedging to remove in Phase 1**. No documents are actually passed.
**Future SEC integration:** `adv_service` → fee structure (management fee, performance fee) from Form ADV.

---

### Chapter 7: Operational DD (`operational_dd.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `domicile` | `Fund.domicile` | (a) Fund table | ✅ Present |

**Data completeness:** MINIMAL — identity-only, no operational data from any source.
**Hedging language:** Line 24: "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed." — **hedging to remove in Phase 1**.
**Future SEC integration (Phase 3):** `sec_managers.compliance_disclosures` for regulatory compliance section.

---

### Chapter 8: Recommendation (`recommendation.j2`)

| Template Variable | Source | Category | Status |
|---|---|---|---|
| `fund_name` | `Fund.name` | (a) Fund table | ✅ Present |
| `manager_name` | `Fund.manager_name` | (a) Fund table | ✅ Present |
| `chapter_summaries` | Generated chapters 1-7 (truncated at 500 chars each) | (internal) LLM output | ✅ Present |

**Data completeness:** FULL for its purpose (synthesis chapter). Receives first 500 chars of each completed chapter.
**Hedging language:** None — instructions are direct ("State clearly: APPROVE, CONDITIONAL, or REJECT"). No changes needed.

---

## Summary Matrix

| Chapter | Fund Identity (a) | Quant/Risk (b) | RAG/pgvector (c) | SEC Data (d) | Completeness |
|---|---|---|---|---|---|
| 1. Executive Summary | ✅ 7 fields | ✅ 4 fields | ❌ not wired | ❌ not wired | FULL (structured) |
| 2. Investment Strategy | ✅ 5 fields | ❌ not passed | ❌ not wired | ❌ not wired | PARTIAL (identity-only) |
| 3. Manager Assessment | ✅ 4 fields | ✅ 4 fields | ❌ not wired | ❌ not wired | PARTIAL (no ADV) |
| 4. Performance Analysis | ✅ 2 fields | ✅ 10 fields | ❌ not wired | ❌ not wired | FULL (structured) |
| 5. Risk Framework | ✅ 2 fields | ✅ 15 fields | ❌ not wired | ❌ not wired | FULL (structured) |
| 6. Fee Analysis | ✅ 4 fields | ❌ zeroed out | ❌ not wired | ❌ not wired | MINIMAL (identity-only) |
| 7. Operational DD | ✅ 3 fields | ❌ not in template | ❌ not wired | ❌ not wired | MINIMAL (identity-only) |
| 8. Recommendation | ✅ 2 fields | ❌ not in template | ❌ not wired | ❌ not wired | FULL (synthesis) |

---

## Hybrid Chapter Identification

**No hybrid chapters exist today.** All chapters consume either:
- Structured data only (chapters 1, 4, 5, 8)
- Identity-only with no supporting data (chapters 2, 6, 7)
- Identity + partial quant (chapter 3)

**Future hybrid chapters (post-Phase 3):**
- **Investment Strategy** — will mix fund identity (a) + 13F sector weights (d)
- **Manager Assessment** — will mix quant metrics (b) + ADV data (d)
- **Operational DD** — will mix fund identity (a) + compliance disclosures (d)

---

## Hedging Language Inventory

| Chapter | Line | Hedging Text | Action |
|---|---|---|---|
| Executive Summary | 33 | "evidence-based" | Phase 1: replace with "data-driven" |
| Investment Strategy | 25 | "If document evidence is available, cite specific sources. If not, note where additional documentation would strengthen the analysis." | Phase 1: remove, replace with structured data semantics |
| Manager Assessment | 32 | "Provide specific evidence where available." | Phase 1: DO NOT TOUCH (correct pre-ADV) |
| Performance Analysis | 36 | "Interpret numbers in context...Flag any performance anomalies." | Phase 4: tighten to threshold-based |
| Risk Framework | 41 | "Flag any concerning trends or limit breaches." | Phase 4: tighten to threshold-based |
| Fee Analysis | 25 | "Where specific fee data is available from documents, cite exact figures. Where not, note the information gaps." | Phase 1: remove, no documents actually passed |
| Operational DD | 24 | "Note where documentation is available vs. where additional operational due diligence site visits or calls would be needed." | Phase 1: remove site visit language |
| Recommendation | — | (none) | No changes needed |

---

## Unpopulated EvidencePack Fields

| Field | Declared In | Populated By Engine | Used By Any Template |
|---|---|---|---|
| `documents` | `evidence_pack.py:44` | ❌ always `[]` | ❌ no template references `documents` |
| `scoring_data` | `evidence_pack.py:53` | ❌ always `{}` | ❌ no template references `scoring_data` |
| `macro_snapshot` | `evidence_pack.py:56` | ❌ always `{}` | ❌ no template references `macro_snapshot` |

These fields are referenced only in `confidence_scoring.py` (evidence coverage weight) where their absence lowers the confidence score.

---

## SEC Data Not Yet Wired

| SEC Service | Table | Fields Relevant to DD | Target Chapter | Backlog Phase |
|---|---|---|---|---|
| `adv_service` | `sec_managers` | AUM history, fee structure, compliance_disclosures | Manager Assessment, Fee Analysis, Operational DD | Phase 3 |
| `adv_service` | `sec_manager_team` | Team bios, key persons | Manager Assessment | Phase 3 |
| `thirteenf_service` | `sec_13f_holdings` | sector_weights, concentration | Investment Strategy | Phase 3 |
| `thirteenf_service` | `sec_13f_diffs` | drift_detected, drift_quarters | Investment Strategy | Phase 3 |
| `institutional_service` | `sec_institutional_allocations` | (not in DD scope) | — | — |

---

## User Content Builder Analysis (`chapters.py:_build_user_content`)

The user message duplicates some template data:
- Fund identity (fund_name, ISIN, manager_name) always sent
- `quant_profile` metrics sent as bullet list for chapters: `executive_summary`, `performance_analysis`, `risk_framework`, `recommendation`
- `risk_metrics` sent as bullet list only for `risk_framework`
- `documents` sent as excerpts (capped at 20 chunks × 2000 chars) — but always empty today
- `chapter_summaries` sent for `recommendation` — first 500 chars of each chapter

This means the LLM receives data both in the system prompt (via Jinja2 template) AND in the user message (via `_build_user_content`). This is intentional redundancy — system prompt structures the analysis, user message provides the raw data.
