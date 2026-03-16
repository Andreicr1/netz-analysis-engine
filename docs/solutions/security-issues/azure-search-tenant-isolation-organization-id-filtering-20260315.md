---
title: "Azure Search Tenant Isolation — organization_id in OData Filters"
category: security-issues
tags: [multi-tenant, tenant-isolation, organization-id, odata-injection, azure-search, security-f2, security-f5, rag-retrieval]
module: Azure Search (search_upsert_service, azure_kb_adapter, pipeline_kb_adapter, deep_review, domain_ai, pipeline, global_agent, policy_loader)
symptom: "Azure Search queries return documents from all tenants — no organization_id filter in OData expressions"
root_cause: "Azure Search bypasses PostgreSQL RLS. Tenant isolation must be enforced explicitly in OData filters, but all search functions only filtered by deal_id/fund_id."
severity: critical
date_solved: 2026-03-15
pr: "#25"
---

# Azure Search Tenant Isolation — organization_id in OData Filters

## Problem

Multi-tenant SaaS application where PostgreSQL enforces tenant isolation via Row-Level Security (RLS) on all database queries. However, Azure AI Search is an external service that bypasses RLS entirely. All search functions (`search_deal_chunks`, `search_fund_policy_chunks`, `PipelineKBAdapter.search_live`, `AzureComplianceKBAdapter.search_live`, `policy_loader._search`) constructed OData filters without `organization_id`, meaning one tenant's RAG queries could return another tenant's documents.

**Security findings:** F2 (Critical), F5 (High) from the Wave 2 deep review modularization audit.

**Symptoms:**
- `search_deal_chunks()` filtered by `deal_id` only: `filter_expr = f"deal_id eq '{deal_id}'"`
- `search_fund_policy_chunks()` filtered by `fund_id` + `domain` only
- `PipelineKBAdapter` had no tenant filter at all (optional `deal_folder` only)
- `AzureComplianceKBAdapter` filtered by `category` only
- The entire `deep_review/` directory had zero references to `organization_id`
- Global agent performed parallel retrieval across indexes with no tenant boundary

## Root Cause

Azure Search is a separate service from PostgreSQL. While PostgreSQL RLS automatically scopes all DB queries to the current tenant via `SET LOCAL app.current_organization_id`, Azure Search has no equivalent mechanism. Tenant isolation in Azure Search must be enforced at the application layer by including `organization_id eq '{org_id}'` in every OData filter expression.

This was a design gap from the original implementation — the `CLAUDE.md` rule ("All RAG queries MUST include `$filter=organization_id eq '{org_id}'`") existed but was not enforced in code.

## Solution

### 1. Input Validation (OData Injection Prevention)

Added `validate_uuid()` and `validate_domain()` to `search_upsert_service.py`:

```python
def validate_uuid(value: str | uuid.UUID, field_name: str = "id") -> str:
    """Validate and normalize UUID for safe OData filter interpolation."""
    try:
        return str(uuid.UUID(str(value)))  # normalizes to lowercase-hyphenated
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for {field_name}: {value!r}")

_VALID_DOMAINS = frozenset({
    "credit", "wealth", "macro", "benchmark",
    "POLICY", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER", "PIPELINE",
})

def validate_domain(domain: str) -> str:
    if domain not in _VALID_DOMAINS:
        raise ValueError(f"Invalid domain filter: {domain!r}")
    return domain
```

**Key decisions:**
- `uuid.UUID()` instead of regex — faster (~2x), handles all UUID formats (uppercase, braces, URN), normalizes output
- Allowlist for domains — prevents OData injection on string fields where UUID validation doesn't apply
- Functions are public (no underscore) — imported by 3+ other packages

### 2. OData Filter Construction

Every search function now includes `organization_id` in its filter:

```python
# Before:
filter_expr = f"deal_id eq '{deal_id}'"

# After:
safe_deal = validate_uuid(deal_id, "deal_id")
safe_org = validate_uuid(organization_id, "organization_id")
filter_expr = f"deal_id eq '{safe_deal}' and organization_id eq '{safe_org}'"
```

### 3. Parameter Threading (14 files)

`organization_id: uuid.UUID | str` threaded as explicit required parameter through the entire call chain:

| Layer | Files | Pattern |
|-------|-------|---------|
| Search functions | `search_upsert_service.py` | Required keyword, validated before filter construction |
| KB adapters | `azure_kb_adapter.py`, `pipeline_kb_adapter.py` | Required parameter, validated at entry |
| Deep review | `service.py`, `corpus.py`, `policy.py`, `portfolio.py` | Required keyword on all entry points |
| Domain AI | `domain_ai/service.py` | Required on `run_portfolio_analysis`, optional on `run_pipeline_analysis` (resolves from deal) |
| Pipeline | `intelligence.py`, `screening.py` | Required on `_retrieve_deal_context`, resolved from `deal.organization_id` if not provided |
| Global agent | `agent.py` | Resolved from `organization_id` param > `actor.org_id` > fail-closed |
| Policy loader | `policy_loader.py` | Optional on `_search()` (policy indexes may be global) |

### 4. Fail-Closed Pattern (Global Agent)

```python
def _retrieve_pipeline(self, question, deal_folder, top, organization_id=None):
    if organization_id is None:
        logger.warning("GLOBAL_AGENT pipeline retrieval without organization_id")
        return []  # fail-closed — no results rather than cross-tenant leak
```

### 5. deal_folder Validation (PipelineKBAdapter)

```python
from ai_engine.pipeline.storage_routing import _SAFE_PATH_SEGMENT_RE

if deal_folder:
    if not _SAFE_PATH_SEGMENT_RE.match(deal_folder):
        raise ValueError(f"Invalid deal_folder: {deal_folder!r}")
    odata_filter = f"{org_filter} and deal_folder eq '{deal_folder}'"
```

## Bugs Caught During Code Review

4 bugs found by 7 parallel review agents + manual deep review:

1. **P1 — Async path missing `organization_id`**: `service.py:1485` called `_gather_deal_texts()` without `organization_id` inside `asyncio.to_thread()`. The sync path (line 182) had it but the async path didn't. **Entire async deep review pipeline was unprotected.**

2. **P1 — `deal_id` used as fallback for `organization_id`**: `intelligence.py` had `organization_id=organization_id or deal_id`. A deal UUID is NOT an organization UUID — would match zero documents (fail-closed) but masks a caller bug. Fixed: resolves from `deal.organization_id`.

3. **P1 — Unified entrypoint gap**: `run_deal_ai_analysis()` in `domain_ai/service.py` didn't accept or pass `organization_id`. Both PIPELINE and PORTFOLIO paths through this entrypoint had no tenant isolation.

4. **P2 — Empty string bypass**: `policy_loader.py` used `if organization_id:` (truthiness check). An empty string `""` is falsy and would skip the filter. Fixed: `if organization_id is not None:`.

## Prevention Strategies

### Code Review Checklist for Azure Search Changes

- [ ] Every `.search()` call includes `organization_id` in the OData filter
- [ ] UUID fields are validated via `validate_uuid()` before OData interpolation
- [ ] String fields are validated via `validate_domain()` or `_SAFE_PATH_SEGMENT_RE`
- [ ] New search paths follow fail-closed pattern (return empty on missing org_id)
- [ ] `organization_id` is threaded through the ENTIRE call chain — check async paths separately

### Verification Command

After any search-related changes, run:

```bash
grep -rn "\.search(" backend/ --include="*.py" | grep -v "test_" | grep -v "__pycache__"
```

Every real search call should have `organization_id` in its filter or an explicit TODO marker.

### When Adding New Search Paths

1. Add `organization_id: uuid.UUID | str` as required keyword parameter
2. Call `validate_uuid(organization_id, "organization_id")` before filter construction
3. Include `organization_id eq '{safe_org}'` in OData filter expression
4. If the caller doesn't have org_id, resolve from the deal/fund ORM object: `str(deal.organization_id)`
5. If resolution is impossible, fail-closed (return empty, log warning)

### Azure Search Index Schema Prerequisite

The `organization_id` field MUST be marked `filterable: true` in the Azure Search index definition. Without this, filter queries on `organization_id` cause a full scan or return 400 errors. Verify with:

```bash
# Check index schema via Azure CLI or REST API
az search index show --name global-vector-chunks-v2 --service-name <service>
```

## Stub Client Considerations

`AzureSearchChunksClient` in `app/services/search_index.py` is a Sprint 3 stub (`raises NotImplementedError`). When implementing the real client:

1. `search_institutional_hybrid()` MUST accept and filter by `organization_id`
2. `resolve_index_scope()` MUST include `organization_id` in scope resolution
3. All methods on `AzureSearchMetadataClient` MUST include org filtering
4. The copilot and dataroom routes have `# TODO(Phase 3 / Sprint 3):` markers — honor them

## Related Documentation

- **Phase 3 StorageClient + ADLS Dual-Write**: `docs/solutions/architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md` — designed Security F4 (org_id in search documents)
- **RLS Subselect 1000x Slowdown**: `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md` — parallel principle: tenant context must be constant, injected once
- **Wave 1 Modularization**: `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md` — parameter threading convention
- **Wave 2 Deep Review DAG**: `docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md` — import safety patterns
- **CLAUDE.md**: Critical rule — "All RAG queries MUST include `$filter=organization_id eq '{org_id}'`"
- **PR #25**: `security(F2/F5): add organization_id to all Azure Search queries`
- **Phase 3 Plan**: `docs/plans/2026-03-15-refactor-credit-deep-review-phase3-future-opportunities-plan.md`
