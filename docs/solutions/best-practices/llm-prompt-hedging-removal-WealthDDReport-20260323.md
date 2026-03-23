---
module: Wealth DD Report
date: 2026-03-23
problem_type: best_practice
component: service_object
symptoms:
  - "LLM-generated DD chapters contained speculative hedging language for data never passed to context"
  - "Templates referenced non-existent document sources ('if document evidence available')"
  - "No SEC regulatory data (13F holdings, ADV profiles) wired into evidence pack"
  - "Quant-driven chapters used interpretive language instead of threshold-based assertions"
root_cause: config_error
resolution_type: code_fix
severity: high
tags: [dd-report, prompt-engineering, evidence-pack, sec-integration, hedging-removal, source-awareness]
---

# Troubleshooting: LLM Prompt Hedging & Data Awareness in DD Report Generation

## Problem

Wealth DD Report templates contained speculative hedging language ("where available", "if document evidence", "site visits") for data sources that were never populated in the evidence pack. This caused the LLM to generate vague, non-committal text instead of direct analytical statements. Additionally, SEC regulatory data (13F holdings, ADV manager profiles) was not wired into the evidence pack, leaving chapters with minimal or identity-only context.

## Environment
- Module: Wealth DD Report Engine (`vertical_engines/wealth/dd_report/`)
- Stack: Python 3.12, Jinja2 templates, OpenAI LLM, SQLAlchemy sync Session
- Affected Components: 8 Jinja2 chapter templates, `evidence_pack.py`, `chapters.py`, `dd_report_engine.py`
- Date: 2026-03-20 to 2026-03-23 (4-phase execution)

## Symptoms
- LLM output contained hedging phrases: "Where specific fee data is available from documents...", "If document evidence is available, cite specific sources...", "where additional operational due diligence site visits or calls would be needed"
- Templates referenced `documents` field that was always `[]` — never populated by the engine
- No SEC 13F sector weights or ADV compliance/team data reached the LLM context
- Quant chapters (performance_analysis, risk_framework) used "interpret in context" and "flag concerning trends" — vague instructions for deterministic numbers
- `structured_data_complete/partial/absent` status was not communicated to templates — LLM had to guess data availability

## What Didn't Work

**Direct solution:** The problem was identified through a systematic 5-phase approach (audit + 4 implementation phases). The Phase 0 audit identified all hedging language and data gaps before any code changes were made.

Key insight: attempting to fix templates without first auditing data flow would have been blind — the audit revealed that 3 EvidencePack fields (`documents`, `scoring_data`, `macro_snapshot`) were declared but never populated, and that `filter_for_chapter("fee_analysis")` zeroed out quant data.

## Solution

### Phase 1: Remove hedging from stable chapters (4 templates)

```jinja2
{# Before (broken) — fee_analysis.j2: #}
Where specific fee data is available from documents, cite exact figures.
Where not, note the information gaps.

{# After (fixed): #}
State available fee data directly. For fields not available from the data
provider, write '[Not available from YFinance/FEfundinfo]' instead of speculating.
```

```jinja2
{# Before (broken) — operational_dd.j2: #}
Note where documentation is available vs. where additional operational due
diligence site visits or calls would be needed.

{# After (fixed): #}
Assess operational infrastructure based on available data. For information not
reported by the data provider, write '[Not reported by provider]'. Do not
reference site visits or calls.
```

### Phase 2: Source-aware context block (evidence_pack.py + 8 templates)

```python
# Added to evidence_pack.py — per-chapter field expectations:
_CHAPTER_FIELD_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "fee_analysis": {
        "fields": ["fund_name", "fund_type", "currency"],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    # ... one entry per chapter
}

# compute_source_metadata() classifies each chapter:
def compute_source_metadata(self, chapter_tag: str) -> dict[str, Any]:
    # Returns structured_data_complete/partial/absent + field lists
```

```jinja2
{# Source-aware preamble added to all 8 templates: #}
{% if structured_data_complete %}
## Data Availability
All structured data fields for this chapter are available from {{ primary_provider }}.
Base your analysis on these fields directly.
{% elif structured_data_partial %}
## Data Availability
Partial structured data available from {{ data_providers | join(', ') }}.
Available: {{ available_fields | join(', ') }}.
Not available: {{ missing_fields | join(', ') }}.
For missing fields, write '[Not available from {{ primary_provider }}]'.
{% elif structured_data_absent %}
## Data Availability
No structured data available for this chapter. State this clearly and do not speculate.
{% endif %}
```

### Phase 3: SEC layer integration (new file + 3 templates)

```python
# Created sec_injection.py with two sync DB queries:

def gather_sec_13f_data(db, *, manager_name, cik=None) -> dict:
    """13F sector weights + drift detection (DB-only, never calls EDGAR API)."""
    # Resolves manager_name -> CIK via sec_managers.firm_name (case-insensitive)
    # Returns: thirteenf_available, sector_weights, drift_detected, drift_quarters

def gather_sec_adv_data(db, *, manager_name, crd_number=None) -> dict:
    """ADV manager profile (DB-only, never calls EDGAR API)."""
    # Returns: compliance_disclosures, adv_aum_history, adv_fee_structure, adv_team
```

```python
# Wired in dd_report_engine.py:_build_evidence():
sec_13f = gather_sec_13f_data(db, manager_name=manager_name)
sec_adv = gather_sec_adv_data(db, manager_name=manager_name)
return build_evidence_pack(..., sec_13f_data=sec_13f, sec_adv_data=sec_adv)
```

### Phase 4: Tighten quant-driven chapters (2 templates)

```jinja2
{# Before (broken) — performance_analysis.j2: #}
Interpret numbers in context (peer group, market conditions).
Flag any performance anomalies.

{# After (fixed): #}
State each metric directly — Sharpe below 0.5 is subpar, drawdown beyond -15%
is material, negative alpha indicates underperformance. Numbers either meet
institutional thresholds or they do not.
```

```jinja2
{# Before (broken) — risk_framework.j2: #}
Interpret CVaR and risk metrics in context. Flag any concerning trends or limit breaches.

{# After (fixed): #}
State each risk metric directly against institutional thresholds. CVaR breaching
-5% at 95% confidence is material. Volatility above 15% annualized is elevated.
Beta above 1.2 indicates amplified market exposure. Metrics either breach
thresholds or they do not — no hedging.
```

## Why This Works

1. **Root cause was template-data misalignment:** Templates instructed the LLM to reference documents, site visits, and evidence that never existed in the context. The LLM, following instructions faithfully, generated speculative conditional text.

2. **Source-aware preamble eliminates guessing:** By telling the LLM exactly which fields are present/absent before it generates text, the model produces deterministic statements (`[Not available from X]`) instead of hedging.

3. **SEC data enriches thin chapters:** Investment Strategy, Manager Assessment, and Operational DD went from identity-only to having real regulatory data (13F sector allocations, ADV compliance disclosures, team bios). This transforms LLM output from generic boilerplate to fund-specific analysis.

4. **Threshold-based language for quant chapters:** Deterministic metrics (Sharpe, CVaR, volatility) need binary assessment against thresholds, not contextual interpretation. The LLM now states "Sharpe of 0.32 is below the 0.5 institutional threshold" instead of "Sharpe of 0.32 may indicate challenges depending on market conditions."

## Prevention

- **Always audit data flow before writing prompt templates.** Map every template variable to its actual data source. Never write conditional language for data that isn't populated.
- **Use the source-aware preamble pattern** for any new chapter or LLM-driven report section. The `compute_source_metadata()` + `_CHAPTER_FIELD_EXPECTATIONS` pattern is reusable across verticals.
- **DB-only reads in hot path.** SEC injection functions (`gather_sec_13f_data`, `gather_sec_adv_data`) use only sync DB queries. Never call external APIs (EDGAR, EFTS) from user-facing code — that's for ingestion workers only.
- **Threshold-based instructions for deterministic data.** When the LLM receives computed numbers, give it concrete thresholds, not "interpret in context."
- **Test after each template change.** All 4 phases ran `make test` (2630 passing) confirming no regressions.

## Related Issues

- Promoted to Required Reading: [critical-patterns.md](../patterns/critical-patterns.md) (Patterns #1 and #2)

## References

- Full changelog: `docs/reference/wm-ddreport-optimization-changelog-2026-03-23.md`
- Phase 0 audit artifact: `docs/reference/wm-ddreport-evidence-pack-audit-2026-03-20.md`
- Implementation backlog: `docs/plans/2026-03-20-wm-ddreport-optimization-backlog.md`
