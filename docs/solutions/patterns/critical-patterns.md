# Critical Patterns — Required Reading

> Patterns that MUST be followed in every code generation session.
> Each pattern was extracted from a real incident or multi-session optimization.

---

## 1. Source-Aware LLM Prompt Templates (ALWAYS REQUIRED)

### ❌ WRONG (LLM generates speculative hedging text)
```jinja2
## Instructions
Where specific fee data is available from documents, cite exact figures.
Where not, note the information gaps.
```
```jinja2
## Instructions
If document evidence is available, cite specific sources. If not, note where
additional documentation would strengthen the analysis.
```
```jinja2
## Instructions
Interpret numbers in context (peer group, market conditions).
Flag any concerning trends.
```

### ✅ CORRECT
```jinja2
{# 1. Source-aware preamble — tells LLM exactly what data is present/absent #}
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

{# 2. Instructions reference concrete thresholds, not vague interpretation #}
## Instructions
State each metric directly — Sharpe below 0.5 is subpar, drawdown beyond -15%
is material, negative alpha indicates underperformance. Numbers either meet
institutional thresholds or they do not.
```
```python
# 3. Backend computes source metadata per chapter BEFORE template rendering:
_CHAPTER_FIELD_EXPECTATIONS = {
    "fee_analysis": {
        "fields": ["fund_name", "fund_type", "currency"],
        "providers": ["YFinance"],
        "primary_provider": "YFinance",
    },
    # ... one entry per chapter
}

# EvidencePack.compute_source_metadata(chapter_tag) returns:
# structured_data_complete, structured_data_partial, structured_data_absent,
# data_providers, available_fields, missing_fields, primary_provider
```

**Why:** LLM prompt templates that reference data sources not actually populated in the context cause the model to generate speculative conditional text ("where available", "if evidence exists", "may indicate"). This dilutes analytical quality and produces non-actionable output. The source-aware preamble pattern eliminates guessing — the LLM knows exactly what's present and what's absent before generating text.

**Placement/Context:** Every Jinja2 template used as an LLM system prompt in DD reports, memos, or any chapter-based generation. Applies to both `vertical_engines/wealth/` and `vertical_engines/credit/` when adding new LLM-driven chapters. Three rules:
1. **Audit data flow first** — map every template variable to its actual source before writing the template.
2. **Use source-aware preamble** — compute `structured_data_complete/partial/absent` and inject into context.
3. **Threshold-based language for deterministic data** — when the LLM receives computed numbers (Sharpe, CVaR, volatility), give concrete thresholds, not "interpret in context."

**Documented in:** `docs/solutions/best-practices/llm-prompt-hedging-removal-WealthDDReport-20260323.md`

---

## 2. DB-Only Reads in User-Facing Code (ALWAYS REQUIRED)

### ❌ WRONG (Calls external API from hot path)
```python
# Inside dd_report_engine.py or any route handler:
from data_providers.sec.thirteenf_service import ThirteenFService
svc = ThirteenFService(db)
holdings = await svc.fetch_holdings(cik)  # TRIGGERS EDGAR API CALL
```

### ✅ CORRECT
```python
# Inside dd_report_engine.py — sync DB-only reads:
from vertical_engines.wealth.dd_report.sec_injection import (
    gather_sec_13f_data,  # DB-only: reads sec_13f_holdings table
    gather_sec_adv_data,  # DB-only: reads sec_managers/sec_manager_team tables
)

sec_13f = gather_sec_13f_data(db, manager_name=manager_name)
sec_adv = gather_sec_adv_data(db, manager_name=manager_name)
```
```python
# EDGAR API calls belong ONLY in ingestion workers:
# sec_13f_ingestion (lock 900_021) — calls fetch_holdings()
# sec_adv_ingestion (lock 900_022) — calls FOIA bulk CSV
```

**Why:** External API calls (EDGAR, FRED, Yahoo Finance) add 2-10s latency and rate-limit risk to user-facing requests. All external data is pre-ingested by background workers into hypertables. Routes, vertical engines, and DD report chapters read from DB only. `sec_injection.py` mirrors `ThirteenFService` logic but runs sync inside `asyncio.to_thread()` — compatible with the DD report engine's threading model.

**Placement/Context:** Any code that runs inside a route handler, vertical engine, or `asyncio.to_thread()` block. Check CLAUDE.md "SEC data providers — DB-only in hot path" for the full list of allowed vs forbidden methods.

**Documented in:** `docs/solutions/best-practices/llm-prompt-hedging-removal-WealthDDReport-20260323.md`

---

## 3. StorageClient for All Storage — Never Call blob_storage or Azure SDKs (ALWAYS REQUIRED)

### ❌ WRONG (Calls deprecated blob_storage stub — crashes at runtime)
```python
from app.services.blob_storage import upload_bytes, list_blobs, blob_uri, generate_read_link

# All of these raise NotImplementedError:
upload_bytes(container="my-container", blob_name="file.pdf", data=pdf_bytes)
entries = list_blobs(container="my-container", prefix="docs/")
uri = blob_uri(container="my-container", blob_name="file.pdf")
url = generate_read_link(container="my-container", blob_name="file.pdf")
```
```python
# Also wrong — building storage paths with f-strings:
path = f"gold/{org_id}/credit/reports/{fund_id}/{filename}"
await storage.write(path, data)
```

### ✅ CORRECT
```python
from app.services.storage_client import get_storage_client
from ai_engine.pipeline.storage_routing import gold_credit_report_path

storage = get_storage_client()
path = gold_credit_report_path(org_id=actor.organization_id, fund_id=str(fund_id),
                                report_type="monthly", filename=f"{pack_id}.pdf")
await storage.write(path, pdf_bytes, content_type="application/pdf")
url = await storage.generate_read_url(path)
files = await storage.list_files(f"gold/{org_id}/credit/reports/monthly/{fund_id}/")
data = await storage.read(path)
exists = await storage.exists(path)
```

**Why:** `blob_storage.py`, `blob_client.py`, `search_index.py`, and `search_upsert_service.py` were deleted on 2026-03-23 after a full migration. Any import from these modules is a compilation error. Even before deletion, 7 of 8 functions in `blob_storage.py` raised `NotImplementedError`, silently breaking 14 credit endpoints at runtime. The `StorageClient` abstraction (R2 in prod, LocalStorage in dev) is the only valid storage interface. Path helpers in `storage_routing.py` validate segments with `_SAFE_PATH_SEGMENT_RE` and enforce the `{tier}/{org_id}/{vertical}/...` convention, preventing path traversal and tenant data leakage.

**Placement/Context:** Every file that reads, writes, lists, or generates URLs for stored files. Applies to routes, vertical engines, ai_engine modules, and workers. Available path helpers:
- `bronze_deal_path()`, `bronze_document_path()`, `bronze_upload_blob_path()`
- `silver_chunks_path()`, `silver_metadata_path()`
- `gold_ic_memo_path()`, `gold_artifact_path()`, `gold_portfolio_review_path()`, `gold_credit_report_path()`
- `gold_memo_path()`, `gold_fact_sheet_path()`, `gold_content_path()`, `gold_dd_report_path()`
- `global_reference_path()`

**Documented in:** `docs/solutions/integration-issues/incomplete-azure-blob-migration-CreditStorageIO-20260323.md`
