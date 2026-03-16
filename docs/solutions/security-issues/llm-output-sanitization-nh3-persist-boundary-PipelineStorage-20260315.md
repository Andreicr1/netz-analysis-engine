---
title: "llm-output-sanitization-nh3-persist-boundary-PipelineStorage-20260315"
category: security-issues
severity: P1
component: backend/vertical_engines/credit/deep_review/service.py
tags:
  - llm-output-sanitization
  - xss
  - html-injection
  - prompt-injection
  - nh3
  - deep-review
  - persist-boundary
  - exception-cleanup
  - retrieval-governance
  - output-safety
date_discovered: "2026-03-15"
date_resolved: "2026-03-15"
pr_number: 26
root_cause: "LLM-generated text was persisted to database without HTML sanitization or injection marker stripping at any of the five write boundaries in the deep review pipeline."
---

# LLM Output Sanitization — nh3 at Persist Boundaries

## Problem Statement

The deep review pipeline persisted raw LLM output directly into PostgreSQL fields (DealIntelligenceProfile, DealICBrief, DealRiskFlag, evidence_json, and MemoChapter.content_md) without any sanitization. This left the system vulnerable to stored XSS via unclosed or malicious HTML tags, prompt injection marker persistence, and control character corruption (including null bytes that corrupt PostgreSQL JSONB).

Security findings F6 (Medium) and F7 (Medium) from the Wave 2 deep review modularization, deferred to Phase 3.

## Root Cause Analysis

LLMs (GPT-4, Claude) routinely produce HTML tags in output — `<br>`, `<b>`, `<table>`, and occasionally `<script>` or `<style>` when prompt context includes web content. The deep review pipeline had zero sanitization between LLM response and database write:

- **Stored XSS**: LLM output containing `<script>` tags would persist to JSONB/TEXT and execute when rendered in Markdown views.
- **Stored indirect prompt injection**: A malicious document could cause the LLM to echo injection markers (`<|system|>`, `IGNORE PREVIOUS INSTRUCTIONS`) into persisted fields, picked up by downstream LLM calls (Fund Copilot RAG).
- **Entity encoding attacks**: Raw `&lt;script&gt;` sequences could bypass naive regex-based sanitization if decoded before filtering.
- **JSONB null byte corruption**: Binary control chars (0x00) from OCR/PDF extraction corrupt PostgreSQL TEXT columns and break JSON serialization.

## Solution

### sanitize_llm_text() — `ai_engine/governance/output_safety.py`

Centralized sanitization function using `nh3` (Rust-based, DOM-aware HTML sanitizer). Mirrors the existing `prompt_safety.py` (input side) — this handles OUTPUT sanitization. Cross-vertical: used by deep_review, memo, domain_ai, and future verticals.

**6-stage sanitization pipeline:**

1. **Unicode NFC normalization** — canonical, non-lossy (NOT NFKC which destroys financial superscripts)
2. **Control character stripping** — removes 0x00-0x1F (preserving `\t`, `\n`, `\r`)
3. **HTML sanitization via nh3** — DOM-based, handles unclosed tags, attribute injection, entity encoding
4. **Injection marker stripping** — defense-in-depth against stored indirect prompt injection
5. **Whitespace collapse** — 3+ newlines reduced to 2
6. **Length enforcement** — 100KB default cap, or caller-specified `max_length`

**Two modes:**

| Mode | Use case | Tags allowed |
|------|----------|-------------|
| Default (allowlist) | TEXT/JSONB fields rendered as Markdown | `<sup>`, `<table>`, `<strong>`, `<code>`, etc. |
| `strip_all_html=True` | VARCHAR fields (plain text display) | None |

### Persist Boundary Pattern

```python
from ai_engine.governance.output_safety import sanitize_llm_text

# TEXT column (Markdown-rendered) — allowlist mode:
profile.summary_ic_ready = sanitize_llm_text(
    analysis.get("executiveSummary", "AI review pending."),
)

# VARCHAR column (plain text) — strip-all mode with length cap:
profile.sector_focus = sanitize_llm_text(
    _trunc(analysis.get("sectorFocus"), 160),
    strip_all_html=True, max_length=160,
)

# DealICBrief fields — sanitize then fallback:
brief.executive_summary = sanitize_llm_text(_exec_summary) or "See IC Memorandum."

# DealRiskFlag reasoning — strip-all (no HTML in risk descriptions):
reasoning=sanitize_llm_text(
    f"{risk.get('factor', '')}: {risk.get('mitigation', '')}",
    strip_all_html=True,
)

# MemoChapter content_md — sanitize before DB UPDATE:
_sanitized_md = sanitize_llm_text(_revised)
db.execute(update(MemoChapter).where(...).values(content_md=_sanitized_md))
```

### 5 Persist Boundaries Covered (sync + async)

1. **DealIntelligenceProfile** — `geography`, `sector_focus` (strip-all), `summary_ic_ready` (allowlist)
2. **DealICBrief** — 6 TEXT fields: `executive_summary`, `opportunity_overview`, `return_profile`, `downside_case`, `risk_summary`, `comparison_peer_funds`
3. **DealRiskFlag** — `reasoning` (strip-all)
4. **evidence_json** — `appendix_1_source_index`, `appendix_kyc_checks` (allowlist)
5. **MemoChapter.content_md** — post-tone normalizer (allowlist)

KYC persist skipped — structured API data (names, IDs, hit counts), not LLM text.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| nh3 over regex | DOM-aware; handles unclosed tags, attribute injection, entity encoding that `re.sub(r"<[^>]+>", "")` misses |
| NFC not NFKC | NFKC destroys financial notation — superscripts (`R²`→`R2`), ligatures |
| No `html.unescape()` before nh3 | Would convert `&lt;script&gt;` → `<script>` before nh3 sees it = vulnerability |
| Allowlist vs strip-all per field type | TEXT/Markdown fields need `<sup>`, `<table>`; VARCHAR fields should never have HTML |
| Sanitize at persist boundary, not LLM call site | Preserves original text for logging/debugging |
| `nh3` as core dependency (not optional) | Output sanitization is a security concern that should never be optional |

## Exception Cleanup (same PR)

**EvidenceGapError → SaturationResult return value:**

```python
@dataclass(frozen=True, slots=True)
class SaturationResult:
    is_sufficient: bool
    coverage_score: float
    gaps: list[str] = field(default_factory=list)
    reason: str = ""
    def to_dict(self) -> dict[str, Any]: ...
```

- `enforce_evidence_saturation()` returns dict with `strict_fail` flag instead of raising
- Follows `PipelineStageResult` pattern (frozen dataclass with `to_dict()`)
- Aligns with retrieval package "never-raises" error contract

**Dead exceptions removed:**
- `ProvenanceError` — completely unused (never raised, never caught)
- `RetrievalScopeError` — duplicate of `search_index.py` version (copilot's canonical source kept)

## Prevention Checklist

When adding a new LLM persist boundary:

- [ ] Import `sanitize_llm_text` from `ai_engine.governance.output_safety`
- [ ] VARCHAR fields: `strip_all_html=True` + `max_length=N` matching column constraint
- [ ] TEXT/JSONB string fields: default allowlist mode (preserves financial notation)
- [ ] Structured data (KYC, API responses): skip sanitization — not LLM prose
- [ ] Verify sync/async symmetry — same sanitization in both paths
- [ ] No `html.unescape()` before `sanitize_llm_text()`
- [ ] No `markupsafe.Markup()` wrapping of LLM output

## Code Review Checklist

- [ ] Every code path from LLM response to `session.add()` / `session.execute()` passes through `sanitize_llm_text`
- [ ] Sanitization is at the persist boundary, not at the LLM call site
- [ ] VARCHAR fields use `strip_all_html=True`
- [ ] No `script`, `style`, `iframe`, `object`, `embed`, `form`, `input` in any custom allowlist
- [ ] Null bytes stripped before JSONB persistence

## Known Gaps (absorbed into PR C scope)

- **`metadata_json` nested dicts** — LLM output in arbitrarily nested JSONB; recursive sanitization deferred
- **Remaining VARCHAR fields** — `liquidity_profile`, `capital_structure_type`, `key_risks[].mitigation` (todo 048)
- **`_INJECTION_MARKERS` duplication** — identical list in `prompt_safety.py` and `output_safety.py` (todo 049)
- **`SaturationResult` field name mismatch** — `is_sufficient` vs `all_saturated` vocabulary (todo 050)

## Testing

30 tests in `backend/tests/test_output_safety.py`:
- None/empty passthrough, null bytes, control chars
- Safe tags preserved, dangerous tags stripped, unclosed tags handled
- `strip_all_html` mode, NFC normalization, injection markers
- `max_length=0` edge case, 100KB default cap
- `SaturationResult` construction, `to_dict()`, frozen enforcement
- Exception removal verification (no remaining imports)
- `enforce_evidence_saturation` strict mode returns dict (no raise)

## Related Documentation

- **Phase 1 (PR #25):** [Azure Search tenant isolation](azure-search-tenant-isolation-organization-id-filtering-20260315.md) — `organization_id` in all OData filters
- **Wave 2 (PR #23):** `docs/solutions/architecture-patterns/wave2-deep-review-modularization-MonolithToDAGPackage-20260315.md` — original decomposition that surfaced F6/F7
- **Wave 1 (PRs #8-#19):** `docs/solutions/architecture-patterns/wave1-credit-vertical-modularization-MonolithToPackages-20260315.md` — never-raises error contract, package patterns
- **Phase 3 Plan:** `docs/plans/2026-03-15-refactor-credit-deep-review-phase3-future-opportunities-plan.md` — PR A→B→C sequencing
- **PR C (future):** Sync/async dedup will absorb remaining sanitization gaps (todos 048-050)
