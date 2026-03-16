---
title: "refactor: Credit Deep Review Phase 3 — Future Opportunities"
type: refactor
status: active
date: 2026-03-15
origin: docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md
deepened: 2026-03-15
---

# refactor: Credit Deep Review Phase 3 — Future Opportunities

## Enhancement Summary

**Deepened on:** 2026-03-15
**Research agents used:** 10 (architecture-strategist, security-sentinel, performance-oracle, code-simplicity-reviewer, pattern-recognition-specialist, best-practices-researcher ×3, repo-research-analyst, learnings-researcher)
**Learnings applied:** 7 (wave1-credit-modularization, wave2-deep-review-modularization, rls-subselect-1000x-slowdown, storageclient-adls-dualwrite, unified-pipeline-ingestion, thread-unsafe-rate-limiter, alembic-migration-fk-rls)

### Key Improvements

1. **UUID validation simplified:** `uuid.UUID(value)` replaces hand-rolled regex — more Pythonic, faster (~2x), handles edge cases (uppercase, braces, urn: prefix)
2. **HTML sanitization hardened:** `nh3` library (Rust-based bleach successor) recommended over naive regex — handles unclosed tags, attribute injection, nested templates
3. **Feature flag resequenced:** Backfill search index FIRST, then enable org_id filter — eliminates vulnerability window and removes need for feature flag
4. **Helper extraction refined:** 3 small helpers (<25 LOC) kept inline instead of extracted — avoids premature abstraction per simplicity review
5. **persist_review_artifacts made sync:** Accepts plain session, async path wraps with `asyncio.to_thread()` — eliminates sync/async asymmetry in extracted helpers
6. **`sanitize_llm_text()` simplified:** `strip_html` parameter removed (always strip) — YAGNI, no caller would pass `False`
7. **Phase consolidation:** 4 phases → 3 PRs (Phase 2 + Phase 4 merged — both small, no dependencies)
8. **Azure Search index schema prerequisite added:** `organization_id` must be `filterable` in index definition before Phase 1 filter changes work
9. **Backfill script for non-ADLS environments:** `search_rebuild.py` reads from ADLS silver layer, but production has `FEATURE_ADLS_ENABLED=false`. New `scripts/backfill_search_org_id.py` reads from PostgreSQL directly for environments without ADLS.
10. **Session pattern in persist clarified:** `persist_review_artifacts()` inside `asyncio.to_thread()` creates a NEW sync session via `SessionLocal()` — NOT `session.sync_session` (internal, undocumented SQLAlchemy attribute)
11. **CRITICAL: Phase 1 scope expanded** — Security audit found 5+ additional Azure Search call sites outside deep_review that also lack `organization_id`: `global_agent/agent.py`, `global_agent/pipeline_kb_adapter.py`, `azure_kb_adapter.py`, `copilot.py`, `dataroom/routes.py`, `policy_loader.py`. All must be included in Phase 1.
12. **Sanitization: tag allowlist instead of strip-all** — `nh3.clean()` with safe tag allowlist preserves Markdown-compatible HTML (`<sup>`, `<table>`, `<br>`) that LLMs produce for financial notation. Strip-all destroys `"EBITDA<sup>1</sup>"` → `"EBITDA1"`.
13. **Sanitization placement moved** — `sanitize_llm_text()` moved from `deep_review/helpers.py` to `ai_engine/governance/output_safety.py` (mirrors existing `prompt_safety.py` for input sanitization). Cross-vertical reusable.
14. **Prompt injection marker stripping on LLM output** — Defense-in-depth against stored indirect prompt injection (OWASP LLM01). Reuse `_INJECTION_MARKERS` from `prompt_safety.py`.

### Debate: 3 PRs vs 4 PRs

The simplicity reviewer recommended merging Phase 2 (LLM sanitization) + Phase 4 (exception deprecation) into a single PR. The architecture reviewer agreed:

- **Phase 2 + Phase 4 (merge):** Both are small, independent changes. Phase 2 adds `sanitize_llm_text()` and domain validation. Phase 4 removes dead exceptions and adds `SaturationResult`. Neither has external dependencies. Combined PR stays under ~400 LOC of changes. Merging reduces review overhead and branch churn.
- **Phase 1 (keep separate):** Critical security fix with cross-cutting caller updates. Must ship independently for audit trail.
- **Phase 3 (keep separate):** Large structural refactor (~2400 LOC moved). Must be reviewable in isolation.

**Verdict:** 3 PRs. Phase ordering: PR A (tenant isolation) → PR B (sanitization + exception cleanup) → PR C (sync/async dedup).

### New Considerations Discovered

- `organization_id` must be marked `filterable` in the Azure Search index schema — without this, the new OData filter clause triggers a full scan instead of an index lookup
- `PipelineDeal` model has `organization_id` via `OrganizationScopedMixin` — confirmed available on the ORM object for extraction as scalar before search calls
- Sync batch runner uses raw SQL `text()` for status updates while async batch uses helper function — document but defer (out of scope)
- `search_fund_chunks()` (line 260) also lacks `organization_id` — confirmed as a second affected function beyond `search_deal_chunks()`
- `nh3` (v0.2+) is the community-recommended bleach replacement — zero Python dependencies, compiled Rust extension

---

## Overview

Implement the 5 deferred items from the Wave 2 deep_review modularization plan: tenant isolation in RAG queries (Critical security), LLM output sanitization, sync/async pipeline deduplication (~2400 LOC reduction), named `StageOutcome` dataclass, and retrieval exception deprecation.

This work addresses 4 deferred security findings (F2 Critical, F5 High, F6 Medium, F7 Medium) and eliminates the largest remaining technical debt in `vertical_engines/credit/deep_review/`.

## Problem Statement

After Wave 2 successfully decomposed the deep_review cluster into 11 modules with a 5-tier DAG, several items were explicitly deferred:

1. **Tenant isolation gap (F2 Critical, F5 High):** `search_deal_chunks()` and `search_fund_chunks()` filter by `deal_id`/`fund_id` only — no `organization_id`. The entire `deep_review/` directory has zero references to `organization_id`. Azure Search queries bypass PostgreSQL RLS, so tenant isolation must be enforced explicitly in OData filters.
2. **Sync/async duplication:** `service.py` (2772 lines) contains near-identical sync and async pipelines (~2400 LOC duplicated). Six extraction targets identified: return dict builder, evidence pack metadata, profile/brief/risk-flag persist, critic output injection, confidence computation, post-memo critic tag detection.
3. **Fragile stage unpacking:** Async Phase 3 gather uses index-based positional unpacking of 5 stages — adding/removing/reordering silently breaks.
4. **LLM output unsanitized (F6/F7):** LLM-generated strings persisted to JSONB without HTML stripping or length enforcement. OData filters use f-string interpolation.
5. **Dead exceptions:** `ProvenanceError` unused, `EvidenceGapError` raised but never caught.

## Proposed Solution

### Phase Ordering (Revised)

Security fixes first, then sanitization + cleanup, then dedup:

| Phase | PR | Items | Rationale |
|---|---|---|---|
| Phase 1 | PR A | Tenant isolation (org_id in RAG queries) | F2 Critical + F5 High — ship security fix immediately |
| Phase 2 | PR B | LLM sanitization + OData hardening + exception deprecation | F6 + F7 Medium + cleanup — combined for reduced review overhead |
| Phase 3 | PR C | Sync/async dedup + StageOutcome | Biggest refactor — security fixes now in duplicated code get consolidated into extracted helpers |

### Research Insights: Phase Ordering

**Best practice (security-first):** Ship tenant isolation as PR A to close the Critical finding immediately. The sanitization + exception work in PR B is lower severity and can follow. Dedup in PR C is pure structural improvement — no security implications.

**Dedup-last advantage confirmed:** By applying sanitization to the duplicated code in PR B, the dedup in PR C consolidates the fixes into single helper functions. If dedup went first, we'd extract helpers, then have to modify them again for sanitization — two rounds of changes to the same code.

## Technical Approach

### Phase 1: Tenant Isolation — `organization_id` in RAG Queries

**Goal:** All Azure Search queries include `$filter=organization_id eq '{org_id}'` per CLAUDE.md rule.

**How `organization_id` flows:** Add `organization_id: str` as an explicit required keyword argument to the deep review entry points and thread it through the call chain. The `PipelineDeal` model has `organization_id` via `OrganizationScopedMixin` (`backend/app/core/db/base.py:39`), so callers extract it as a scalar from the ORM object before passing to search functions.

#### Research Insights: Azure Search Tenant Isolation

**Azure Search index schema prerequisite:** The `organization_id` field MUST be marked as `filterable: true` in the index definition. Without this, Azure Search performs a full scan on every query with the `organization_id` filter — defeating the purpose. Verify and update the index definition before deploying the filter changes.

**OData filter best practices (Microsoft guidance):**
- Azure Search SDK does NOT support parameterized OData filters — f-string interpolation is the standard approach
- Defense is input validation, not parameterization
- For multi-tenant SaaS: Microsoft recommends `organization_id` as a filterable field in every document, with the filter applied at the application layer (exactly this plan's approach)
- OData string values: single quotes must be doubled (`O'Brien` → `O''Brien`). UUID fields don't contain quotes, but the validation function should exist as defense-in-depth

**Backfill-first approach (revised from original):** Instead of a feature flag, backfill `organization_id` into the search index FIRST, then deploy the filter code. This eliminates the vulnerability window where queries return zero results for un-backfilled documents. The feature flag (`FEATURE_SEARCH_ORG_FILTER`) is removed from the plan — simpler, safer.

**Critical: `search_rebuild.py` may not work without ADLS.** The `search_rebuild.py` script (from Phase 3 of the pipeline refactor) reads from the ADLS silver layer Parquet files. In production, `FEATURE_ADLS_ENABLED=false` — the silver layer is not populated. The backfill needs an alternative path:

1. **Check if `search_rebuild.py` can populate `organization_id` with `FEATURE_ADLS_ENABLED=false`** — it uses `LocalStorageClient` which reads from `.data/lake/`. If silver Parquet files exist locally with `organization_id`, this works.
2. **If not (likely for production):** Create `scripts/backfill_search_org_id.py` — a one-time script that:
   - Reads document metadata from PostgreSQL (documents table has `organization_id` via RLS)
   - Joins with existing Azure Search documents by `document_id`
   - Upserts the `organization_id` field into each search document
   - Logs progress and skips already-backfilled documents
   - Runs idempotently (safe to re-run)

**Deployment sequence:**
1. Verify `organization_id` is `filterable` in Azure Search index schema (update if not)
2. Run backfill: `search_rebuild.py` (if ADLS available) OR `scripts/backfill_search_org_id.py` (reads from PostgreSQL)
3. Verify backfill completeness: query Azure Search for documents where `organization_id` is null/missing
4. Deploy PR A with the org_id filter code
5. Monitor search result counts for regression

#### 1a. Fix `search_deal_chunks()` — `ai_engine/extraction/search_upsert_service.py`

Current (line 221):
```python
filter_expr = f"deal_id eq '{deal_id}'"
```

Target:
```python
def search_deal_chunks(
    deal_id: str,
    *,
    organization_id: str,  # NEW — required keyword
    ...
) -> list[dict]:
    _validate_uuid(deal_id, "deal_id")
    _validate_uuid(organization_id, "organization_id")
    filter_expr = f"deal_id eq '{deal_id}' and organization_id eq '{organization_id}'"
```

Add `_validate_uuid()` helper using stdlib `uuid.UUID()` (simpler and faster than regex):
```python
import uuid as _uuid

def _validate_uuid(value: str, field_name: str = "id") -> str:
    """Validate and normalize UUID string. Prevents OData injection on ID fields."""
    try:
        return str(_uuid.UUID(value))  # normalizes to lowercase hyphenated
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for {field_name}: {value!r}")
```

#### Research Insights: UUID Validation

**`uuid.UUID()` vs regex:** `uuid.UUID()` is ~2x faster for valid UUIDs (C implementation), handles edge cases (uppercase, braces, `urn:uuid:` prefix), and normalizes output to lowercase hyphenated form. The regex approach misses URN-style UUIDs and requires separate normalization. (see: CPython `uuid` module benchmarks, Python 3.12+ fast path)

**Normalization bonus:** `str(uuid.UUID(value))` always returns lowercase hyphenated form (`550e8400-e29b-41d4-a716-446655440000`), preventing case-mismatch issues in Azure Search filters.

#### 1b. Fix `search_fund_chunks()` — same file (line 260)

Currently filters by `fund_id` + `domain` with no `organization_id`. Add `organization_id: str` required keyword and include in filter.

**Note:** This function was missed in the original Wave 2 analysis. It has the same tenant isolation gap as `search_deal_chunks()`.

#### 1c. Fix `_gather_policy_context()` — `deep_review/policy.py`

Add `organization_id: str` parameter to function signature (currently only has `fund_id`, `deal_name`). Thread to `AzureSearchChunksClient.search_institutional_hybrid()`.

#### 1d. Fix `AzureSearchChunksClient` — `app/services/search_index.py`

Add `organization_id: str` required keyword to `search_institutional_hybrid()` and include `organization_id eq '{org_id}'` in all OData filters built by this client.

**OData escaping for non-UUID strings:** Add a helper for string values used in OData filters:
```python
def _odata_escape(value: str) -> str:
    """Escape single quotes for OData string literals."""
    return value.replace("'", "''")
```

Apply to any string field used in OData filters that isn't UUID-validated or allowlist-validated.

#### 1e. Thread `organization_id` through callers

**Deep review callers (original scope):**

| Caller | File | Change | Source of `organization_id` |
|---|---|---|---|
| `_gather_investment_texts()` | `deep_review/corpus.py:471` | Accept `organization_id`, pass to `search_deal_chunks()` | From service.py parameter |
| `_gather_deal_texts()` | `deep_review/corpus.py:299` | Accept `organization_id`, pass through retrieval chain | From service.py parameter |
| `run_deal_deep_review_v4()` | `deep_review/service.py:94` | Add `organization_id: str` keyword parameter | Caller extracts from `deal.organization_id` |
| `async_run_deal_deep_review_v4()` | `deep_review/service.py:1362` | Add `organization_id: str` keyword parameter | Caller extracts from `deal.organization_id` |
| `domain_ai/service.py:54` | `domain_ai/service.py` | Thread `organization_id` to `search_deal_chunks()` | From RLS session or deal object |
| `pipeline/screening.py:52` | `pipeline/screening.py` | Thread `organization_id` to `search_deal_chunks()` | From pipeline context |
| Batch runners | `deep_review/service.py:2564, 2661` | Thread `organization_id` from fund/deal lookup | Extract from first deal in batch |

**Additional search call sites (discovered by security audit — CRITICAL):**

| Caller | File | Current filter | Change |
|---|---|---|---|
| `NetzGlobalAgent` | `global_agent/agent.py` | Zero `organization_id` refs | Thread from authenticated request context |
| `PipelineKBAdapter.search_live()` | `global_agent/pipeline_kb_adapter.py` | No tenant filter | Add `organization_id` to all OData filters |
| `AzureComplianceKBAdapter.search_live()` | `ai_engine/extraction/azure_kb_adapter.py` | `category eq '{domain}'` only | Add `organization_id` filter |
| `copilot.py` search calls | `modules/ai/copilot.py:171, 268` | `fund_id` + `root_folder` only | Add `organization_id` filter |
| `dataroom routes` | `dataroom/routes/routes.py:161` | `fund_id` only | Add `organization_id` filter |
| `policy_loader._search()` | `ai_engine/governance/policy_loader.py:249` | No tenant filter | Add `organization_id` filter |

**Verification gate:** After Phase 1, run `grep -r "\.search(" backend/ --include="*.py"` and verify every Azure Search call includes `organization_id` in its filter. Zero exceptions.

#### Research Insights: Caller Threading

**`PipelineDeal.organization_id` confirmed available:** The `PipelineDeal` model uses `OrganizationScopedMixin` which provides `organization_id: Mapped[uuid.UUID]`. The calling code (routes/workers that invoke deep review) already has the deal loaded from an RLS-scoped session, so `str(deal.organization_id)` is the extraction point. Extract as scalar BEFORE passing to service functions (per CLAUDE.md: "Extract scalar attributes into frozen dataclasses before crossing any async/thread boundary").

**Pattern from unified pipeline:** The unified pipeline (`ai_engine/pipeline/unified_pipeline.py`) already threads `organization_id` via `IngestRequest(frozen=True)` — a frozen dataclass with path traversal validation. Deep review should follow the same pattern: extract once at the entry point, pass as explicit string.

#### 1f. Tests

- Unit test: `_validate_uuid()` accepts valid UUIDs (lowercase, uppercase, hyphenated)
- Unit test: `_validate_uuid()` rejects non-UUID strings, empty strings, SQL injection attempts
- Unit test: `search_deal_chunks()` includes `organization_id` in OData filter
- Unit test: `search_fund_chunks()` includes `organization_id` in OData filter
- Unit test: `_gather_policy_context()` passes `organization_id` to search client
- Integration test: Verify search returns only same-org documents (mock Azure Search client)
- Golden tests: existing 13 tests continue passing (they don't hit Azure Search)

#### 1g. `__init__.py` update

Update `deep_review/__init__.py` to export updated function signatures. No new public symbols.

### Phase 2: LLM Sanitization + OData Hardening + Exception Deprecation

**Goal:** All LLM-generated text is sanitized before JSONB/TEXT persistence. All OData filters use validated inputs. Dead exceptions removed.

#### 2a. Sanitization utility — `ai_engine/governance/output_safety.py`

**Placement rationale (revised):** Moved from `deep_review/helpers.py` to `ai_engine/governance/output_safety.py`. This mirrors the existing `ai_engine/governance/prompt_safety.py` (input sanitization). LLM output sanitization is cross-vertical — `memo/`, `domain_ai/`, and future verticals all persist LLM output. Placing it in `deep_review/helpers.py` would force other packages to either import from deep_review (violating package independence) or duplicate the utility. `deep_review/helpers.py` can re-import for DAG convenience.

#### Research Insights: LLM Output Sanitization

**HTML in LLM output is common:** GPT-4 and Claude regularly produce HTML tags in output — `<br>`, `<b>`, `<i>`, `<table>`, and occasionally `<script>` or `<style>` when the prompt context includes web content. Markdown output may also contain inline HTML which is part of valid Markdown spec.

**Naive regex pitfalls:** The pattern `<[^>]+>` misses:
- Unclosed tags: `<script` (no closing `>`)
- Tags with `>` in attributes: `<a title="x > y">`
- CDATA sections: `<![CDATA[...]]>`
- HTML comments: `<!-- ... -->`
- Template injection: `<%= ... %>` (ERB/ASP)

**Recommended: `nh3` library** (Rust-based, bleach successor):
- Zero Python dependencies (compiled Rust extension via PyO3)
- Handles all edge cases above
- `nh3.clean(text, tags=set())` strips ALL tags safely
- ~10x faster than regex for complex HTML
- Maintained by the PyO3 team, production-stable since v0.2.0

**Fallback if `nh3` not acceptable:** Use iterative regex with comment/CDATA handling:
```python
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]*>?")  # Note: `>?` handles unclosed tags
```

**JSONB-specific concerns:**
- Null bytes (`\x00`) must be stripped — PostgreSQL JSONB rejects them
- Control characters (U+0000–U+001F except `\t`, `\n`, `\r`) should be stripped
- No length limit on JSONB/TEXT columns needed (PostgreSQL handles up to 1GB), but application-level sanity cap prevents accidental LLM verbosity (e.g., 100KB)

**Unicode normalization:** Apply NFC normalization to ensure consistent string comparison and deduplication.

Add to `ai_engine/governance/output_safety.py` (new file, mirrors `prompt_safety.py`):

```python
"""LLM output sanitization before database persistence.

Mirrors prompt_safety.py (input sanitization) — this handles OUTPUT sanitization.
"""
from __future__ import annotations

import re
import unicodedata

import nh3
import structlog

logger = structlog.get_logger()

# Tags safe in Markdown-rendered content (financial notation needs <sup>, tables need <table>)
_SAFE_TAGS: set[str] = {
    "b", "i", "em", "strong", "code", "mark", "s", "del", "ins",
    "sup", "sub", "br",
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote", "pre",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "abbr", "hr",
}
_SAFE_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

# Reuse injection markers from prompt_safety.py for output-side defense-in-depth
_INJECTION_MARKERS: list[str] = [
    "<|system|>", "<|user|>", "<|assistant|>",
    "<|im_start|>", "<|im_end|>",
    "IGNORE PREVIOUS", "IGNORE ALL PREVIOUS",
    "DISREGARD PREVIOUS", "FORGET YOUR INSTRUCTIONS",
]

_WHITESPACE_COLLAPSE = re.compile(r"\n{3,}")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MAX_LLM_TEXT_LENGTH = 100_000  # 100KB sanity cap

def sanitize_llm_text(
    text: str | None,
    *,
    max_length: int | None = None,
    strip_all_html: bool = False,
) -> str | None:
    """Sanitize LLM output for safe DB persistence.

    Uses nh3 (Rust-based, DOM-aware) — NOT regex. Handles unclosed tags,
    attribute injection, entity encoding attacks that regex misses.

    Default: allowlist safe Markdown-compatible tags (preserves <sup>, <table>, etc.).
    strip_all_html=True: remove ALL tags (for VARCHAR fields where Markdown won't render).
    """
    if text is None:
        return None
    # 1. Unicode NFC normalization (canonical, non-lossy — NOT NFKC which destroys financial notation)
    text = unicodedata.normalize("NFC", text)
    # 2. Strip control characters (keep \t, \n, \r)
    text = _CONTROL_CHARS.sub("", text)
    # 3. HTML sanitization via nh3 (DOM-based, handles entity attacks internally)
    #    Do NOT call html.unescape() — nh3 handles entities correctly.
    #    unescape() before nh3 converts &lt;script&gt; → <script> = vulnerability.
    if strip_all_html:
        text = nh3.clean(text, tags=set())
    else:
        text = nh3.clean(text, tags=_SAFE_TAGS, attributes=_SAFE_ATTRIBUTES)
    # 4. Strip prompt injection markers (defense-in-depth against stored indirect injection)
    text_upper = text.upper()
    for marker in _INJECTION_MARKERS:
        if marker.upper() in text_upper:
            text = re.sub(re.escape(marker), "", text, flags=re.IGNORECASE)
            logger.warning("stripped_injection_marker", marker=marker)
    # 5. Collapse excessive blank lines
    text = _WHITESPACE_COLLAPSE.sub("\n\n", text.strip())
    # 6. Length enforcement
    effective_max = max_length or _MAX_LLM_TEXT_LENGTH
    if len(text) > effective_max:
        text = text[:effective_max]
    return text
```

**Key design decisions from research:**
- **`nh3.clean()` NOT regex** — DOM-based parser handles unclosed tags, attribute injection, entity encoding attacks that `re.sub(r"<[^>]+>", "")` misses entirely
- **Tag allowlist NOT strip-all** — preserves `"EBITDA<sup>1</sup>"` footnotes, `<table>` in financial analysis, `<br>` in table cells. `strip_all_html=True` available for VARCHAR fields.
- **NFC NOT NFKC** — NFKC is lossy (collapses superscripts, ligatures meaningful in financial text)
- **NO `html.unescape()`** — nh3 handles entities internally. `unescape()` before nh3 converts `&lt;script&gt;` → `<script>` = vulnerability (A10 finding)
- **Injection marker stripping** — defense-in-depth against stored indirect prompt injection (OWASP LLM01 2025/2026)

**Dependency:** Add `nh3>=0.2.0` to `requirements.txt`. Compiled Rust extension, zero Python deps, pre-built wheels for all major platforms.

#### 2b. Apply sanitization at persist boundaries in `service.py`

6 persist locations need `sanitize_llm_text()` calls:

1. **`DealIntelligenceProfile`** fields: `summary_ic_ready`, `sector_focus`, `strategy_type`, `geography` (lines ~1173-1209 sync, ~2385-2415 async)
2. **`DealICBrief`** fields: `executive_summary`, `opportunity_overview`, `return_profile`, `downside_case`, `risk_summary`, `comparison_peer_funds` (lines ~1233-1245 sync, ~2438-2449 async)
3. **`DealRiskFlag.reasoning`**: f-string from `analysis.get("riskFactors")` (lines ~1253 sync, ~2452-2468 async)
4. **`evidence_json` dict**: `citations`, `critic_output`, `decision_anchor`, `saturation_report` (lines ~1044-1095 sync, ~2258-2309 async)
5. **`MemoChapter.content_md`**: post-tone normalizer update (lines ~957-965 sync, ~2194-2202 async)
6. **KYC persist**: risk screening results (lines ~1779 sync, ~2773 async)

Each location: wrap LLM-sourced values in `sanitize_llm_text(value)` or `sanitize_llm_text(value, max_length=500)` for VARCHAR columns.

#### Research Insights: Persist Boundary Pattern

**Apply at the narrowest boundary:** Sanitize at the point where LLM text meets ORM field assignment, NOT at LLM call output. This preserves the original text for logging/debugging while ensuring only clean text reaches the database. Pattern:

```python
# Good: sanitize at persist boundary
profile.summary_ic_ready = sanitize_llm_text(analysis.get("executiveSummary"))

# Bad: sanitize at LLM output (loses original for debugging)
analysis["executiveSummary"] = sanitize_llm_text(raw_llm_output)
```

**VARCHAR vs TEXT/JSONB length strategy:**
- VARCHAR(300) fields (`sector_focus`, `strategy_type`, `geography`): `max_length=300`
- TEXT fields (`summary_ic_ready`, `executive_summary`, etc.): no explicit cap (100KB sanity cap handles pathological cases)
- JSONB fields (`evidence_json`): no cap — sanitize individual string values within the dict, not the whole JSON

#### 2c. OData injection hardening (F6)

For UUID fields (`deal_id`, `fund_id`, `organization_id`): already addressed by `_validate_uuid()` in Phase 1a.

For string fields (`domain_filter`, `source_type`, `asset_class`): add allowlist validation:

```python
# ai_engine/extraction/search_upsert_service.py
_VALID_DOMAINS = frozenset({"credit", "wealth", "macro", "benchmark"})

def _validate_domain(domain: str) -> str:
    """Validate domain against allowlist. Prevents OData injection on string fields."""
    if domain not in _VALID_DOMAINS:
        raise ValueError(f"Invalid domain filter: {domain!r}")
    return domain
```

Apply to:
- `search_upsert_service.py:223` — `domain_filter` parameter
- `azure_kb_adapter.py:42` — `domain` parameter
- `pipeline_kb_adapter.py:72` — `deal_folder` (validate with `_SAFE_PATH_SEGMENT_RE` from `storage_routing.py`)

Explicitly exclude from scope: `retrieval/benchmarks.py:71,73` — uses hardcoded constants, already safe.

#### Research Insights: OData Injection

**Azure Search SDK has NO parameterized filters.** The official `azure-search-documents` Python SDK builds OData filters via string concatenation in all examples. Microsoft's defense recommendation is input validation, which this plan implements via UUID validation + domain allowlists.

**Allowlist maintainability:** When new verticals are added, `_VALID_DOMAINS` must be updated. To prevent forgetting this:
- Add a comment: `# Update when adding new verticals — see app/shared/enums.py`
- Consider deriving from the `Vertical` enum if one exists, or creating one

#### 2d. Exception deprecation (moved from Phase 4)

**2d-i. Remove `ProvenanceError`** — `retrieval/models.py`

Completely unused (never raised, never caught). Remove from `models.py` and `__init__.py` re-exports.

**2d-ii. Convert `EvidenceGapError` to return value** — `retrieval/saturation.py`

Currently raised at line 56 but never caught — propagates as unhandled `RuntimeError` and crashes the entire review. The deep review pipeline already handles thin corpus gracefully (line 186-191 of service.py). Convert to:

```python
@dataclass(frozen=True, slots=True)
class SaturationResult:
    """Evidence saturation assessment. Replaces EvidenceGapError exception."""
    is_sufficient: bool
    coverage_score: float
    gaps: list[str]
    reason: str = ""

    def to_dict(self) -> dict:
        """API boundary serialization (Wave 1 convention #3)."""
        return {
            "is_sufficient": self.is_sufficient,
            "coverage_score": self.coverage_score,
            "gaps": self.gaps,
            "reason": self.reason,
        }
```

`saturation.py` returns `SaturationResult(is_sufficient=False, reason="...")` instead of raising. Callers check `result.is_sufficient` instead of try/except.

#### Research Insights: Exception → Return Value

**Pattern from unified pipeline:** The pipeline uses `PipelineStageResult(frozen=True)` with `success: bool` and `warnings: list[str]` — same pattern as `SaturationResult`. Callers check `result.success` instead of catching exceptions. This is the established convention in this codebase.

**`to_dict()` method required:** Wave 1 convention #3 mandates `_to_dict()` or `to_dict()` at API boundaries — not `dataclasses.asdict()` (which recurses into nested objects unexpectedly). Added above.

**2d-iii. Clarify `RetrievalScopeError` duality**

Two distinct classes exist:
- `retrieval/models.py:21` — `class RetrievalScopeError(ValueError)` — unused externally
- `app/services/search_index.py:32` — `class RetrievalScopeError(Exception)` — used by copilot

Action: Remove from `retrieval/models.py` (unused). Keep `search_index.py` version unchanged (actively used). Add a comment in `search_index.py` noting it is the canonical definition.

**2d-iv. Update `retrieval/__init__.py`**

Remove deprecated exceptions from `__all__` and re-exports. Update `test_vertical_engines.py::EXPECTED_MODULES` if needed.

#### 2e. Tests

- Unit test: `sanitize_llm_text()` strips HTML tags (including unclosed, nested, comments)
- Unit test: `sanitize_llm_text()` strips null bytes and control characters
- Unit test: `sanitize_llm_text(None)` returns `None`
- Unit test: `sanitize_llm_text()` enforces max_length
- Unit test: `sanitize_llm_text()` normalizes Unicode (NFC)
- Unit test: `_validate_domain()` rejects unknown domains
- Unit test: `SaturationResult` dataclass construction and `to_dict()`
- Verify no remaining imports of `ProvenanceError` or `EvidenceGapError` from `retrieval.models`
- Verify copilot still catches `RetrievalScopeError` from `search_index.py`
- Golden tests: existing 13 tests continue passing

### Phase 3: Sync/Async Deduplication + StageOutcome

**Goal:** Extract ~2400 LOC of duplicated business logic into shared sync helpers. Reduce `service.py` from ~2772 to ~1400 lines.

#### Research Insights: Sync/Async Deduplication Patterns

**Industry patterns (2025-2026):**

1. **Shared-core extraction (chosen):** Extract pure business logic into sync functions. Both sync and async paths call them directly (since they're CPU-bound, they don't block the event loop). This is the simplest and most maintainable approach. Used by: `httpx` (transport layer), `SQLAlchemy` (result processing), this codebase's unified pipeline (`_check_gate()` helper).

2. **`unasyncd` tool:** Auto-generates sync code from async code. Mature for simple transformations (`await` removal, `async for` → `for`), but struggles with complex patterns like `asyncio.gather` → sequential calls. Not suitable here because the sync/async difference is in orchestration topology, not just await/non-await.

3. **Async-first with sync wrappers:** Write everything async, provide `asyncio.run()` wrappers for sync callers. NOT recommended here because the sync path is used in ThreadPoolExecutor contexts where `asyncio.run()` conflicts with the outer event loop (existing workaround at line 959 already has running-loop detection).

**Recommendation confirmed:** Shared-core extraction is the right choice. The async-only differentiation (gather, to_thread, await) stays in service.py. The shared business logic (dict building, persist, confidence computation) moves to helpers.

**Testing strategy:** Capture golden output from the sync path BEFORE extraction. After extraction, both sync and async paths should produce byte-identical output for the same inputs. Use `json.dumps(result, sort_keys=True, default=str)` for deterministic comparison.

#### 3a. Named `StageOutcome` dataclass — `deep_review/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True, slots=True)
class StageOutcome:
    """Result container for async gather stages. Named fields prevent silent breakage on reorder."""
    edgar: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    sponsor: dict[str, Any] | None = None
    kyc: dict[str, Any] | None = None
    quant: dict[str, Any] | None = None
    errors: dict[str, BaseException] = field(default_factory=dict)

    @classmethod
    def from_gather(
        cls,
        stage_names: list[str],
        results: list[Any],
    ) -> StageOutcome:
        """Build from asyncio.gather(return_exceptions=True) output."""
        fields: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}
        for name, result in zip(stage_names, results, strict=True):
            if isinstance(result, BaseException):
                errors[name] = result
            else:
                fields[name] = result
        return cls(**fields, errors=errors)
```

#### Research Insights: StageOutcome Design

**`strict=True` on `zip()`:** Added to `from_gather()`. If `stage_names` and `results` have different lengths (indicating a gather configuration bug), `zip(strict=True)` raises `ValueError` immediately rather than silently truncating. Available since Python 3.10.

**Why not a NamedTuple?** NamedTuple doesn't support `default_factory` for the `errors` dict. A plain dict would lose type safety and require manual key validation. The frozen dataclass with `from_gather()` classmethod is the right level of abstraction — it's used in exactly one place (the async Phase 3 gather) and prevents exactly one class of bugs (positional unpacking breakage).

**Only for async path:** The sync path runs stages sequentially and doesn't use gather. `StageOutcome` is async-only. This is correct — don't over-generalize.

#### 3b. Shared helpers extraction — `deep_review/persist.py`

Extract into `persist.py` (Tier 3 in DAG — already exists, currently has `_index_chapter_citations` and `_build_tone_artifacts`).

#### Research Insights: What to Extract vs Keep Inline

The simplicity review identified that 3 of the 6 proposed helpers are very small:
- `inject_critic_output()` — ~25 lines
- `build_confidence_inputs()` — ~20 lines
- `detect_affected_rewrite_tags()` — ~15 lines

**Decision: Keep these 3 inline.** At <25 LOC each, the function call overhead (parameter passing, docstring, test boilerplate) exceeds the dedup benefit. They're called from exactly 2 places each (sync + async), and the dedup effort is better spent on the 3 large helpers.

**Extract only the 3 large helpers:**

**Extract 1: `build_return_dict()`** (~55 keys, identical in both pipelines)
```python
def build_return_dict(
    deal_id: str,
    fund_id: str,
    analysis: dict,
    chapter_texts: dict,
    evidence_pack_meta: dict,
    confidence_result: dict,
    critic_output: dict | None,
    decision_anchor: dict | None,
    memo_result: dict | None,
    tone_result: dict | None,
    warnings: list[str],
    *,
    cached: bool = False,
) -> dict:
    """Build the canonical deep review return dict. Single source of truth."""
    ...
```

**Extract 2: `build_evidence_pack_metadata()`** (~50 keys dict for `MemoEvidencePack.evidence_json`)
```python
def build_evidence_pack_metadata(
    analysis: dict,
    quant_results: dict | None,
    concentration_profile: dict | None,
    macro_snapshot: dict | None,
    policy_results: dict | None,
    critic_output: dict | None,
    decision_anchor: dict | None,
    saturation_report: dict | None,
    edgar_results: dict | None,
    sponsor_results: dict | None,
    kyc_results: dict | None,
    confidence_result: dict | None,
) -> dict:
    """Build evidence_json dict for MemoEvidencePack. Applies sanitize_llm_text()."""
    ...
```

**Extract 3: `persist_review_artifacts()`** (~160 lines: DealIntelligenceProfile + DealICBrief + DealRiskFlag)

#### Research Insights: persist_review_artifacts Sync/Async Design

**Original plan:** Make `persist_review_artifacts()` async (accepts `AsyncSession`). This creates asymmetry — it's the only async helper while the other 2 are sync.

**Revised approach:** Make it sync (accepts `Session`). The async path wraps it with `await asyncio.to_thread(...)`. This is consistent with how the async path already wraps sync engine calls (EDGAR, sponsor, KYC all use `asyncio.to_thread()`).

**Session pattern — follow `portfolio.py` exactly:**
- The sync path passes its existing sync `db` session directly.
- The async path creates a **new sync session** inside the `to_thread()` callback via `SessionLocal()` (NOT `async_session_factory()`). This is the same pattern used in `portfolio.py` for `ThreadPoolExecutor` workers.
- **Do NOT use `session.sync_session`** — this is an internal, undocumented SQLAlchemy attribute that exposes the underlying sync session of an `AsyncSession`. It is not safe to use across threads and not part of the public API.
- The new `SessionLocal()` session must set RLS context (`SET LOCAL app.current_organization_id`) before any queries, just like the main session.

```python
def persist_review_artifacts(
    db: Session,  # sync Session, not AsyncSession
    deal_id: str,
    fund_id: str,
    organization_id: str,
    analysis: dict,
    chapter_texts: dict,
    confidence_result: dict,
    decision_anchor: dict | None,
    *,
    deal_folder_path: str,
) -> None:
    """Persist intelligence profile, IC brief, and risk flags.

    Sync function:
    - Sync callers pass their existing db session directly.
    - Async callers use asyncio.to_thread() with a NEW SessionLocal() session
      (NOT session.sync_session). The new session must SET LOCAL RLS context.
    All string fields sanitized via sanitize_llm_text() before DB write.
    """
    ...
```

All extracted functions:
- Accept explicit scalar parameters (no ORM objects — thread safety per CLAUDE.md)
- Use `sanitize_llm_text()` at persist boundaries (from Phase 2)
- Return frozen dataclasses or plain dicts (Wave 1 convention #3/#6)
- Are sync (CPU-bound dict manipulation / DB writes) — async path uses `asyncio.to_thread()` for persist

#### 3c. Refactor `service.py`

Replace duplicated blocks with calls to extracted helpers:

```python
# Before (sync, ~55 lines):
return {
    "dealId": deal_id,
    "fundId": fund_id,
    "executiveSummary": analysis.get("executiveSummary"),
    # ... 52 more keys ...
}

# After (sync, 1 line):
return build_return_dict(deal_id, fund_id, analysis, chapter_texts, ...)
```

```python
# Before (async, index-based):
results_3 = await asyncio.gather(..., return_exceptions=True)
stage_names = ["EDGAR", "Policy", "Sponsor", "KYC", "Quant"]
for i, result in enumerate(results_3):
    if isinstance(result, BaseException):
        ...

# After (async, named):
outcome = StageOutcome.from_gather(
    ["edgar", "policy", "sponsor", "kyc", "quant"],
    await asyncio.gather(..., return_exceptions=True),
)
if outcome.errors:
    for stage, exc in outcome.errors.items():
        logger.warning("stage_failed", stage=stage, error=str(exc))
edgar_results = outcome.edgar
policy_results = outcome.policy
```

#### Research Insights: Extraction Safety

**Subtle divergence to watch:** The sync path uses `deal.deal_folder_path` (ORM attribute, line 1254) while the async path stores `deal_folder_path` as a local variable (line 2462, extracted from ORM before `to_thread`). The extracted `persist_review_artifacts()` takes `deal_folder_path: str` as an explicit parameter, so both paths work — but verify this during implementation by grepping for all `deal.` attribute accesses in the persist blocks.

**Session scope contract:** The extracted `persist_review_artifacts()` uses `begin_nested()` for savepoint-based atomicity. The caller must NOT have concurrent `to_thread` calls in flight on the same session. Document this in the docstring.

#### 3d. Batch runners — OUT OF SCOPE

`run_all_deals_deep_review_v4` and `async_run_all_deals_deep_review_v4` are thin orchestrators (~95/105 lines) with distinct divergences (raw SQL vs. helper for status updates, different session patterns). Deferring to avoid scope creep.

**Documented divergences for future cleanup:**
- Sync batch (line 2608-2620): raw SQL `text()` UPDATE on `pipeline_deals`
- Async batch (line 2707-2713): `update_deal_intelligence_status()` helper
- Sync batch: `SessionLocal()` with `with` context manager
- Async batch: `SessionLocal()` without context manager, `finally: session.close()`

#### 3e. Import-linter DAG update

The existing layers contract in `pyproject.toml` already supports this structure:

```
service > portfolio > persist > (corpus | prompts | policy | decision | confidence) > helpers > models
```

`persist.py` at Tier 3 can import `helpers.py` (Tier 2) for `sanitize_llm_text()` and `models.py` (Tier 1) for `StageOutcome`. No DAG changes needed.

#### 3f. Tests

- Unit test: `StageOutcome.from_gather()` with mixed results and errors
- Unit test: `StageOutcome.from_gather()` raises `ValueError` on length mismatch (strict=True)
- Unit test: `build_return_dict()` produces expected 55 keys
- Unit test: `build_evidence_pack_metadata()` applies sanitization to LLM-sourced values
- Unit test: `persist_review_artifacts()` with mocked session — verifies all 3 ORM objects created
- Golden tests: existing 13 tests continue passing
- **NEW golden test:** Snapshot the full return dict from a mocked single-deal review. Capture BEFORE dedup (commit snapshot), assert AFTER dedup. Use `json.dumps(result, sort_keys=True, default=str)` for deterministic comparison.

**Estimated reduction:** `service.py` drops from ~2772 to ~1600 lines. `persist.py` grows from ~80 to ~350 lines. (Revised from original estimate — 3 helpers instead of 6, small helpers remain inline.)

## System-Wide Impact

### Interaction Graph

Phase 1 (org_id) touches ALL Azure Search call sites:
```
deep_review/service.py
  → deep_review/corpus.py → ai_engine/extraction/search_upsert_service.py (search_deal_chunks, search_fund_chunks)
  → deep_review/policy.py → app/services/search_index.py (AzureSearchChunksClient)
  → domain_ai/service.py → search_upsert_service.py
  → pipeline/screening.py → search_upsert_service.py
global_agent/agent.py → global_agent/pipeline_kb_adapter.py → search_upsert_service.py
                       → ai_engine/extraction/azure_kb_adapter.py → AzureSearchChunksClient
modules/ai/copilot.py → AzureSearchChunksClient
dataroom/routes.py → AzureSearchChunksClient
ai_engine/governance/policy_loader.py → AzureSearchChunksClient
```

Phase 2 (sanitization + exceptions) touches:
```
deep_review/helpers.py (new: sanitize_llm_text)
deep_review/service.py (6 persist locations)
ai_engine/extraction/search_upsert_service.py (domain validation)
vertical_engines/credit/retrieval/models.py (exception removal)
vertical_engines/credit/retrieval/saturation.py (EvidenceGapError → SaturationResult)
vertical_engines/credit/retrieval/__init__.py (__all__ update)
```

Phase 3 (dedup) is contained within `deep_review/` — no external API changes.

### Error Propagation

- Phase 1: No new error paths. `_validate_uuid()` raises `ValueError` on bad input — caught by existing pipeline error handling.
- Phase 2: `sanitize_llm_text()` is pure transformation, no errors. `_validate_domain()` raises `ValueError`. `EvidenceGapError` → `SaturationResult` eliminates an unhandled exception path.
- Phase 3: Extracted helpers inherit existing error contracts. `StageOutcome.from_gather()` isolates errors by stage name (improvement over positional index). `strict=True` on `zip()` catches gather configuration bugs.

### State Lifecycle Risks

- Phase 1: Backfill-first approach eliminates the feature flag vulnerability window. Search documents without `organization_id` must be backfilled BEFORE deploying the filter code.
- Phase 3: Pure structural refactor of persist logic. Same DB operations, same transaction boundaries. Risk mitigated by golden test snapshot before dedup.

### API Surface Parity

After Phase 1, `run_deal_deep_review_v4()` and `async_run_deal_deep_review_v4()` gain a new required `organization_id: str` keyword argument. All callers must be updated in the same PR (Wave 1 convention #1: no backward-compat shims).

## Acceptance Criteria

### Phase 1: Tenant Isolation (PR A)

- [ ] Azure Search index schema has `organization_id` marked as `filterable` *(ops prerequisite)*
- [ ] Backfill path verified: `search_rebuild.py` works without ADLS, OR `scripts/backfill_search_org_id.py` created (reads from PostgreSQL)
- [ ] Backfill completes with zero NULL `organization_id` documents in search index
- [x] `search_deal_chunks()` includes `organization_id eq '{org_id}'` in OData filter
- [x] `search_fund_chunks()` includes `organization_id eq '{org_id}'` in OData filter
- [x] `_gather_policy_context()` passes `organization_id` to search client
- [ ] `AzureSearchChunksClient.search_institutional_hybrid()` includes org filter *(stub — deferred to Sprint 3)*
- [x] `run_deal_deep_review_v4()` and `async_run_deal_deep_review_v4()` accept `organization_id: str`
- [x] `domain_ai/service.py` and `pipeline/screening.py` thread `organization_id`
- [x] `global_agent/agent.py`, `pipeline_kb_adapter.py`, `azure_kb_adapter.py` include org filter
- [x] `copilot.py` and `dataroom/routes.py` include org filter *(TODO marker — stub clients)*
- [x] `policy_loader.py` search calls include org filter
- [x] `_validate_uuid()` normalizes and rejects non-UUID strings
- [ ] Verification: `grep -r "\.search(" backend/ --include="*.py"` — every call has org_id *(post-Sprint 3)*
- [x] `make check` passes (364 tests, 5/5 import-linter contracts, ruff clean)

### Phase 2: Sanitization + Exception Cleanup (PR B)

- [ ] `nh3>=0.2.0` added to `requirements.txt`
- [ ] `sanitize_llm_text()` in `ai_engine/governance/output_safety.py` — nh3 tag allowlist, NFC normalization, injection marker stripping
- [ ] All 6 persist locations wrap LLM-sourced values in `sanitize_llm_text()`
- [ ] `_validate_domain()` allowlists valid domain strings for OData
- [ ] `ProvenanceError` removed from `retrieval/models.py` and `__init__.py`
- [ ] `EvidenceGapError` replaced by `SaturationResult` dataclass with `to_dict()`
- [ ] `RetrievalScopeError` removed from `retrieval/models.py` (kept in `search_index.py`)
- [ ] No remaining imports of removed exceptions
- [ ] `make check` passes

### Phase 3: Sync/Async Dedup (PR C)

- [ ] `StageOutcome` dataclass in `models.py` with `from_gather()` classmethod (`strict=True`)
- [ ] 3 extracted helpers in `persist.py` (return dict, evidence meta, persist artifacts)
- [ ] All 3 helpers are sync; async path uses `asyncio.to_thread()` with `SessionLocal()` (not `session.sync_session`)
- [ ] `service.py` reduced from ~2772 to ~1600 lines
- [ ] Import-linter DAG contracts pass (no changes needed)
- [ ] Golden test snapshot captured before dedup, asserted after
- [ ] `make check` passes

### Quality Gates

- [ ] All 324+ tests pass after each phase
- [ ] Golden tests pass (deterministic outputs unchanged)
- [ ] Import DAG verified: `lint-imports` (5/5 contracts)
- [ ] Zero Azure Search `.search()` calls without `organization_id` in entire codebase after Phase 1
- [ ] `service.py` line count < 1700 after Phase 3

## Risk Analysis & Mitigation

| Risk | Severity | Mitigation |
|---|---|---|
| Search index `organization_id` not marked filterable | **High** | Verify index schema BEFORE deploying. Without `filterable`, queries do full scan. |
| Backfill incomplete — queries return zero results | **High** | Run backfill + verify `COUNT(*) WHERE organization_id IS NULL = 0` before deploying filter code |
| Semantic drift between sync/async during helper extraction | Medium | Extract from sync path first, capture golden snapshot, verify async path matches |
| ORM object passed to extracted helper crosses thread boundary | Medium | All helpers accept explicit scalars only — no ORM objects in signatures |
| `nh3` wheel not available for CI platform | Medium | Fallback regex implementation in `sanitize_llm_text()` — detected at import time |
| Golden test fragility on dict key ordering | Low | Use `json.dumps(sort_keys=True, default=str)` for deterministic comparison |
| `_validate_uuid()` rejects legitimate non-standard UUIDs | Low | `uuid.UUID()` handles all RFC 4122 formats including uppercase and URN |

## Dependencies & Prerequisites

- Wave 2 (PR #23, #24) must be merged — **already complete**
- Azure Search index schema: verify `organization_id` is `filterable` — **prerequisite for Phase 1**
- Backfill `organization_id` in search index: verify `search_rebuild.py` works with `FEATURE_ADLS_ENABLED=false`; if not, create `scripts/backfill_search_org_id.py` (reads from PostgreSQL) — **prerequisite for Phase 1**
- `nh3` library: add to `requirements.txt` — **prerequisite for Phase 2**
- No database schema changes required (all fixes are application-level)

## Sources & References

### Origin

- **Brainstorm document:** [docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md](docs/brainstorms/2026-03-15-credit-vertical-modular-alignment-brainstorm.md) — key decisions: edgar package pattern for all engines, Wave 1→2→3 phasing, no backward-compat shims
- **Wave 2 plan (parent):** [docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md](docs/plans/2026-03-15-refactor-credit-deep-review-modularization-wave2-plan.md) — Phase 3 items defined, security findings F2/F5/F6/F7 deferred

### Internal References

- Wave 1 conventions: `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md`
- Wave 2 architecture: `docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md`
- RLS subselect pattern: `docs/solutions/performance-issues/rls-subselect-1000x-slowdown-Database-20260315.md`
- StorageClient + dual-write: `docs/solutions/architecture-patterns/phase3-storageclient-adls-dualwrite-pattern-20260315.md`
- Unified pipeline patterns: `docs/solutions/architecture-patterns/unified-pipeline-ingestion-path-consolidation-Phase2-20260315.md`
- Thread safety patterns: `docs/solutions/runtime-errors/thread-unsafe-rate-limiter-FredService-20260315.md`
- Import-linter contracts: `pyproject.toml` lines 113-177

### Key Files

- `backend/vertical_engines/credit/deep_review/service.py` — main orchestrator (2772 LOC)
- `backend/vertical_engines/credit/deep_review/persist.py` — extraction target (~80 LOC → ~350 LOC)
- `backend/vertical_engines/credit/deep_review/helpers.py` — sanitization utility home
- `backend/vertical_engines/credit/deep_review/models.py` — StageOutcome dataclass home
- `backend/vertical_engines/credit/deep_review/corpus.py` — search_deal_chunks caller
- `backend/vertical_engines/credit/deep_review/policy.py` — _gather_policy_context
- `backend/ai_engine/extraction/search_upsert_service.py` — search_deal_chunks, search_fund_chunks
- `backend/app/services/search_index.py` — AzureSearchChunksClient
- `backend/app/core/db/base.py:39` — OrganizationScopedMixin (confirms org_id on PipelineDeal)
- `backend/vertical_engines/credit/retrieval/models.py` — deprecated exceptions
- `backend/vertical_engines/credit/retrieval/saturation.py` — EvidenceGapError raiser
- `backend/app/core/config/settings.py:75-77` — feature flag pattern reference
- `backend/app/domains/credit/global_agent/agent.py` — zero org_id refs (security audit A5)
- `backend/app/domains/credit/global_agent/pipeline_kb_adapter.py` — no tenant filter (security audit A1)
- `backend/ai_engine/extraction/azure_kb_adapter.py` — no tenant filter (security audit A1)
- `backend/app/domains/credit/modules/ai/copilot.py` — fund_id only, no org_id (security audit A1)
- `backend/app/domains/credit/dataroom/routes/routes.py` — fund_id only (security audit A1)
- `backend/ai_engine/governance/policy_loader.py` — no tenant filter (security audit A1)
- `backend/ai_engine/governance/prompt_safety.py` — input sanitization (pattern for output_safety.py)
- `backend/ai_engine/governance/output_safety.py` — NEW: LLM output sanitization (Phase 2)
