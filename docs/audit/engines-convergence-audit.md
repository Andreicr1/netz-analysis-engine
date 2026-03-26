# Wealth Engines — Fund-Centric Convergence Audit

**Date:** 2026-03-26
**Scope:** All engines in `backend/vertical_engines/wealth/`
**Objective:** Detect any firm-centric bias (Manager 13F used where Fund N-PORT should be the primary) across all wealth engines, prompts, and data flows.

---

## Executive Summary

The DD Report engine was the **only engine** that previously suffered from the fund-centric gap (using firm 13F as primary holdings source). That has been **fully corrected** in the current codebase:

- `dd_report_engine.py:332-338` — N-PORT gathered as primary when `sec_universe == "registered_us"`
- `evidence_pack.py:150-161` — fund-level N-PORT fields defined and populated
- `investment_strategy.j2` — N-PORT primary, 13F explicitly labeled as overlay
- `manager_assessment.j2` — fund-level N-PORT section first, firm ADV section labeled "supplementary"

**All other wealth engines are clean.** No firm-centric bias was found outside the DD Report (which is now fixed).

---

## Engine-by-Engine Audit

### 1. DD Report Engine (FIXED — was the only violator)

| File | Status | Notes |
|------|--------|-------|
| `dd_report/dd_report_engine.py:332-338` | **FIXED** | N-PORT gathered via `fund_cik` for registered US funds; 13F gathered as overlay (line 340) |
| `dd_report/evidence_pack.py:150-167` | **FIXED** | Clear separation: N-PORT fields (lines 153-161) vs 13F fields (lines 163-167) |
| `dd_report/sec_injection.py:101-250` | **CORRECT** | `gather_sec_nport_data(fund_cik=...)` uses fund's own CIK (N-PORT filer) |
| `dd_report/sec_injection.py:27-99` | **CORRECT** | `gather_sec_13f_data(manager_name=...)` resolves to firm's CIK via `_resolve_cik()` — correctly labeled as firm-level |
| `prompts/dd_chapters/investment_strategy.j2` | **FIXED** | N-PORT primary (line 33), 13F overlay with explicit warnings (lines 72-88) |
| `prompts/dd_chapters/manager_assessment.j2` | **FIXED** | Fund-level section first (lines 23-36), firm context labeled "supplementary" with anti-conflation warning (line 41) |
| `prompts/dd_chapters/operational_dd.j2` | **CORRECT** | Compliance disclosures correctly scoped to firm (appropriate for ops chapter) |
| `prompts/dd_chapters/performance_analysis.j2` | **CORRECT** | Pure fund quant metrics, no SEC data |
| `prompts/dd_chapters/risk_framework.j2` | **CORRECT** | Pure fund risk metrics, no SEC data |
| `prompts/dd_chapters/fee_analysis.j2` | **CORRECT** | Fund-level fees, no SEC data |
| `prompts/dd_chapters/executive_summary.j2` | **CORRECT** | Fund identity + fund quant only |
| `prompts/dd_chapters/recommendation.j2` | **CORRECT** | Synthesis of fund chapters |

**Disclosure Matrix logic** (`dd_report_engine.py:334-338`):
```
registered_us fund + has sec_cik → N-PORT primary, 13F overlay
private/UCITS fund (no sec_cik)  → 13F proxy with explicit caution in template
```

---

### 2. Manager Spotlight Engine — CLEAN

**File:** `manager_spotlight.py` (229 lines)

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Fund (`instrument_id` UUID) |
| **Data sources** | `Fund` model + `FundRiskMetrics` (both fund-level) |
| **SEC data** | Zero imports of 13F, N-PORT, ADV, or any SEC tables |
| **CIK references** | None |
| **Template** | `prompts/content/manager_spotlight.j2` — fund identity + fund quant metrics only |
| **Peer comparison** | Allocation block (fund-level cohort), not manager firm peers |

**Verdict:** No bias. Engine operates on fund UUID with fund-specific metrics only. `manager_name` is a text field from the Fund record, not a lookup into SEC tables.

---

### 3. Flash Report Engine — CLEAN (macro-focused, no fund/firm data)

**File:** `flash_report.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Organization-level macro event |
| **Data sources** | `MacroReview.report_json` only (regional composite scores) |
| **Fund references** | Zero — no instrument_id, no Fund queries |
| **SEC data** | Zero |
| **Template** | Hardcoded system prompt (no .j2 template) — macro event narrative |

**Verdict:** Structurally incapable of fund/firm bias — operates exclusively on macro data.

---

### 4. Investment Outlook Engine — CLEAN (macro-focused)

**File:** `investment_outlook.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Organization-level quarterly macro outlook |
| **Data sources** | `MacroReview.report_json` only |
| **Fund references** | Zero |
| **SEC data** | Zero |

**Verdict:** Same as Flash Report — pure macro engine, no fund/firm confusion possible.

---

### 5. Macro Committee Engine — CLEAN (macro-focused)

**File:** `macro_committee_engine.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Global macro environment |
| **Data sources** | Regional snapshots, FRED indicators, regime detection |
| **Fund/firm references** | Zero |

**Verdict:** Macro-only engine. No fund or firm data touched.

---

### 6. Quant Analyzer — CLEAN

**File:** `quant_analyzer.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Fund (`instrument_id`) |
| **Data sources** | `NavTimeseries` (fund NAV) + `FundRiskMetrics` (fund metrics) |
| **Peer comparison** | Fund vs peers in same allocation block (fund-level cohort) |
| **SEC data** | Zero |

**Verdict:** Pure fund-centric. All metrics computed from fund-level time series.

---

### 7. Fund Analyzer (Orchestrator) — CLEAN

**File:** `fund_analyzer.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Fund (`instrument_id`) |
| **Delegation** | DDReportEngine + QuantAnalyzer (both fund-centric) |
| **SEC data** | Not directly — delegated to DD report |

**Verdict:** Orchestrator correctly routes by fund UUID.

---

### 8. Attribution (Brinson-Fachler) — CLEAN

**File:** `attribution/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Portfolio allocation blocks with fund returns |
| **Data sources** | Strategic allocations + fund return series |
| **CIK references** | None |
| **Entity mixing** | None — operates on fund-level allocation weights |

**Verdict:** Pure fund-centric attribution. No manager/firm data.

---

### 9. Rebalancing — CLEAN

**File:** `rebalancing/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Model portfolio fund allocations |
| **Data sources** | `ModelPortfolio` + `fund_selection_schema` JSONB |
| **CIK references** | None |

**Verdict:** Fund-centric weight redistribution. No firm data.

---

### 10. Correlation — CLEAN

**File:** `correlation/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Portfolio instruments (fund-level returns matrix) |
| **Data sources** | NAV timeseries (fund returns) |
| **CIK references** | None |

**Verdict:** Fund-centric diversification analysis.

---

### 11. Fee Drag — CLEAN

**File:** `fee_drag/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Individual instruments |
| **Data sources** | Instrument attributes (`management_fee_pct`, `performance_fee_pct`) |
| **CIK references** | None |

**Verdict:** Pure instrument-level fee analysis.

---

### 12. Monitoring (Alert Engine) — CLEAN

**File:** `monitoring/alert_engine.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Funds (DD expiry) + Portfolios (rebalance overdue) |
| **Data sources** | `Fund.fund_id`, `DDReport.instrument_id`, `ModelPortfolio` |
| **CIK references** | None |

**Verdict:** Fund-scoped alerts.

---

### 13. Watchlist — CLEAN

**File:** `watchlist/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Individual instruments |
| **Data sources** | Re-screening via screener service |
| **CIK references** | None |

**Verdict:** Fund-centric PASS/FAIL transition detection.

---

### 14. Mandate Fit — CLEAN

**File:** `mandate_fit/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Individual instruments |
| **Data sources** | Instrument attributes (currency, domicile, risk bucket) |
| **CIK references** | None |

**Verdict:** Pure instrument eligibility.

---

### 15. Peer Group — CLEAN

**File:** `peer_group/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Instrument within same-type peers |
| **Data sources** | `InstrumentScreeningMetrics` (fund-level) |
| **CIK references** | None |

**Verdict:** Fund-to-fund ranking within organization.

---

### 16. Screener — CLEAN

**File:** `screener/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Individual instruments |
| **Data sources** | Instrument attributes + quant metrics + peer values |
| **CIK references** | None |

**Verdict:** Three-layer deterministic screening per fund.

---

### 17. Model Portfolio — CLEAN

**File:** `model_portfolio/portfolio_builder.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | Model portfolio (collection of funds) |
| **Data sources** | Approved funds with `manager_score` + strategic allocation |
| **Note** | `manager_score` is a **fund-level** metric (from `FundRiskMetrics`), not a firm-level metric despite the name |

**Verdict:** Fund-centric selection and weighting.

---

### 18. Critic — CLEAN

**File:** `critic/service.py`

| Aspect | Finding |
|--------|---------|
| **Analysis object** | DD Report chapters (fund narrative) |
| **Data sources** | Chapter content (text review) |
| **CIK references** | None |

**Verdict:** Adversarial review of fund-level narrative.

---

## Consolidated Results

| Engine | Fund-Centric | Firm Bias | Status |
|--------|:---:|:---:|---|
| DD Report | Yes | **Was present, now FIXED** | Fixed (N-PORT primary, templates updated) |
| Manager Spotlight | Yes | No | Clean |
| Flash Report | N/A (macro) | No | Clean |
| Investment Outlook | N/A (macro) | No | Clean |
| Macro Committee | N/A (macro) | No | Clean |
| Quant Analyzer | Yes | No | Clean |
| Fund Analyzer | Yes | No | Clean |
| Attribution | Yes | No | Clean |
| Rebalancing | Yes | No | Clean |
| Correlation | Yes | No | Clean |
| Fee Drag | Yes | No | Clean |
| Monitoring | Yes | No | Clean |
| Watchlist | Yes | No | Clean |
| Mandate Fit | Yes | No | Clean |
| Peer Group | Yes | No | Clean |
| Screener | Yes | No | Clean |
| Model Portfolio | Yes | No | Clean |
| Critic | Yes | No | Clean |

**Total engines audited:** 18
**Firm-centric bias found:** 1 (DD Report — already fixed)
**Remaining action items:** 0

---

## Architecture Note: Why Only the DD Report Was Affected

The firm-centric bias was isolated to the DD Report because it is the **only engine** that consults SEC filing data (13F, N-PORT, ADV). All other engines operate on:

1. **Fund model attributes** — identity, classification, fees (from `instruments_universe`)
2. **Fund risk metrics** — pre-computed by `risk_calc` worker into `fund_risk_metrics` hypertable
3. **NAV timeseries** — fund-level price history
4. **Macro data** — organization-level regional scores (no fund/firm specificity)

The SEC filing data is inherently multi-entity (firm files 13F, fund files N-PORT, adviser files ADV) and requires explicit CIK routing to avoid conflation. This routing is now correct in `sec_injection.py` and the evidence pack architecture.

---

## Appendix: CIK Routing Map (Current — Correct)

```
Fund CIK (from instrument.attributes.sec_cik)
  └─ gather_sec_nport_data(fund_cik=...)
     └─ SecNportHolding.cik == fund_cik
     └─ Returns: fund sector weights, asset allocation, top holdings, style

Manager Name (from instrument.attributes.manager_name)
  ├─ gather_sec_13f_data(manager_name=...)
  │  └─ _resolve_cik() → SecManager.cik (firm's filer CIK)
  │  └─ Sec13fHolding.cik == firm_cik
  │  └─ Returns: firm sector weights, drift (OVERLAY only)
  │
  ├─ gather_sec_adv_data(manager_name=...)
  │  └─ _resolve_crd() → SecManager.crd_number (firm's CRD)
  │  └─ Returns: firm AUM, compliance, team (SUPPLEMENTARY)
  │
  └─ gather_sec_adv_brochure(crd_number=...)
     └─ Returns: ADV Part 2A narrative sections (SUPPLEMENTARY)
```

**Disclosure Matrix (evidence_pack.py + dd_report_engine.py):**
```
┌─────────────────────┬───────────────┬──────────────┬──────────────┐
│ Fund Universe        │ N-PORT        │ 13F          │ ADV          │
├─────────────────────┼───────────────┼──────────────┼──────────────┤
│ registered_us        │ PRIMARY       │ overlay      │ supplementary│
│ private / UCITS      │ not available │ proxy (⚠)    │ supplementary│
└─────────────────────┴───────────────┴──────────────┴──────────────┘
```
