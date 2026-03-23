# Phase 1 Prompt — Signal-Aware Evidence Context Block

> Paste this prompt into a fresh Claude Code session to execute Phase 1.

---

## Context

You are implementing Phase 1 of the Deep Review Optimization plan. Read these documents first:

1. `docs/reference/deep-review-optimization-plan-2026-03-20.md` — the full optimization plan
2. `docs/plans/2026-03-20-deep-review-optimization-backlog.md` — the comprehensive backlog with Phase 1 details

**Goal:** Propagate `RetrievalSignal.confidence` from the retrieval layer through to Jinja2 chapter templates, so each chapter's prompt adapts to evidence quality (HIGH / MODERATE / AMBIGUOUS / LOW).

## Current State (verified 2026-03-20)

- `RetrievalSignal` is defined in `backend/ai_engine/extraction/retrieval_signal.py` (frozen dataclass, `from_results()` classmethod)
- Per-chapter signal is computed in `backend/vertical_engines/credit/retrieval/evidence.py` lines 268-293 and stored in the result dict under key `"retrieval_signal"` with subkeys `confidence`, `top1_score`, `delta_top1_top2`, `result_count`
- **The signal is NEVER consumed downstream** — `deep_review/` has zero references to `retrieval_signal`
- Templates are rendered in `backend/vertical_engines/credit/memo/chapters.py:_get_chapter_base_prompt()` (line 38-42) via `prompt_registry.render(f"{chapter_tag}.j2", **context)`
- The memo book orchestrator is in `backend/vertical_engines/credit/memo/service.py`
- `corpus.py:_gather_deal_texts()` (line 258-386) calls `gather_chapter_evidence()` and receives per-chapter results — this is where signals must be extracted
- `ch08_returns.j2` has a 15-line MISSING-DATA FALLBACK PROTOCOL (lines 102-115) that should be replaced with the signal-aware include
- `ch09_downside.j2` has a similar fallback protocol (lines 71-76)

## Implementation Steps

### Step 1: Create `_evidence_context.j2` shared include

Create `backend/vertical_engines/credit/prompts/_evidence_context.j2` with 4 conditional branches:

```jinja2
{#- Signal-aware evidence context — included per chapter based on RetrievalSignal.
    Variable `retrieval_confidence` must be set before include. Defaults to MODERATE. -#}

{% set rc = retrieval_confidence | default("MODERATE") %}

{% if rc == "HIGH" %}
=== EVIDENCE CONTEXT ===
Evidence for this chapter is comprehensive and clearly differentiated.
Cite directly from the evidence pack with source attribution.
Flag any numeric inconsistencies between sources — these are analytically significant findings, not noise.
Do not use proxy values or benchmark substitutes when direct evidence exists.

{% elif rc == "MODERATE" %}
=== EVIDENCE CONTEXT ===
Evidence for this chapter is available but may not cover all required fields.
Cite from evidence where available. For fields not directly evidenced,
derive from related data in the evidence pack and label the derivation clearly
(e.g., "Est. based on [source]").

{% elif rc == "AMBIGUOUS" %}
=== EVIDENCE CONTEXT ===
Multiple competing sources were found for this chapter with no clear dominant authority.
Where sources disagree on numeric values or terms, present BOTH values with attribution
(e.g., "PPM states X; IC Memo states Y"). Mark contested data explicitly.
Do not silently resolve disagreements — surface them for IC committee review.
The analyst must resolve contested fields before IC submission.

{% elif rc == "LOW" %}
=== EVIDENCE CONTEXT ===
Limited documentary evidence was found for this chapter.
Apply the following fallback protocol in order:
1. Derive from available evidence and label: "Est. based on [source]"
2. Calibrate using macro data or market benchmarks: "~X% (PB median proxy)"
3. Use [DATA GAP] ONLY when no derivation or proxy is possible
4. NEVER fill an entire table column with [DATA GAP] — consolidate gaps
   into a narrative assessment explaining what is missing and what would be needed.
{% endif %}
```

### Step 2: Extract `chapter_signals` from retrieval results

In `corpus.py:_gather_deal_texts()`, after `gather_chapter_evidence()` returns per-chapter results, extract a `chapter_signals: dict[str, str]` mapping `chapter_tag → confidence_level`. The result dict from `evidence.py` already has `result["retrieval_signal"]["confidence"]` per chapter.

Return `chapter_signals` alongside the corpus so callers can thread it to chapter generation.

### Step 3: Thread `chapter_signals` through memo generation

- `corpus.py:_gather_deal_texts()` returns `chapter_signals` (add to return tuple or attach to result dict)
- `service.py` (deep_review) receives it and passes to the memo book generator
- `memo/service.py` passes it to `chapters.py:generate_chapter()` calls
- `chapters.py:_get_chapter_base_prompt()` accepts `retrieval_confidence: str = "MODERATE"` and passes it to `prompt_registry.render()`

### Step 4: Inject `{% include '_evidence_context.j2' %}` in 8 templates

Add the include to these templates (after the UNIQUE SCOPE section, before the "Cover:" or analysis instructions):

| Template | Placement | Replaces existing code? |
|---|---|---|
| `ch01_exec.j2` | After line 38 (regulatory standing), before "Use the EvidencePack" | No — additive |
| `ch04_sponsor.j2` | Before "Cover:" section | No — additive |
| `ch05_legal.j2` | Before analysis section | No — additive |
| `ch06_terms.j2` | After line 81 (benchmarking), before "Target: 800-1200 words" | No — additive |
| `ch07_capital.j2` | Before analysis section | No — additive |
| `ch08_returns.j2` | Replace lines 102-115 (MISSING-DATA FALLBACK PROTOCOL) | **Yes — replaces** |
| `ch09_downside.j2` | Replace lines 71-76 (fallback protocol) | **Yes — replaces** |
| `ch10_covenants.j2` | Before "Classify each:" (line 52) | No — additive |

Do NOT modify: `ch02_macro.j2`, `ch03_exit.j2`, `ch11_risks.j2`, `ch12_peers.j2`, `ch13_recommendation.j2`, `ch14_governance_stress.j2`, `critic.j2`.

### Step 5: Tests

Write tests in `backend/tests/test_deep_review_signal_aware.py`:

1. **Template rendering test:** For each of the 4 confidence levels, render `ch08_returns.j2` and assert the correct evidence context block appears
2. **chapter_signals extraction test:** Mock `gather_chapter_evidence()` return with `retrieval_signal` dicts → verify `chapter_signals` dict is correctly built
3. **Default fallback test:** When `chapter_signals` is empty or missing a chapter, verify `"MODERATE"` is used
4. **Unchanged templates test:** Render `ch02_macro.j2`, `ch03_exit.j2`, `ch11_risks.j2` → assert no evidence context block appears

### Step 6: Validate

- Run `make check` — all 1405+ tests must pass
- Run the same e2e deep review test that was run as baseline — compare outputs

## Constraints

- Do NOT remove any existing logic — this phase is purely additive (except replacing the 2 fallback protocol sections in ch08/ch09 with the include, which provides the same LOW-signal behavior)
- Do NOT modify `RetrievalSignal` itself
- Do NOT change the JSON output schema of chapter generation
- Do NOT modify `evidence.py` — it already exposes the signal correctly
- Default to `"MODERATE"` everywhere a signal is unavailable — this matches current behavior (evidence available but not necessarily complete)
- Use `{% include '_evidence_context.j2' %}` (with underscore prefix) — convention for partial templates

## Branch & PR

- Branch: `feat/deep-review-signal-aware-prompts`
- PR title: `feat(deep-review): signal-aware evidence context in chapter prompts`
- PR description should reference the optimization plan and explain the 4 confidence levels

---

## OUTPUT: Phase 2 Prompt

After completing Phase 1, generate the following prompt and save it to `docs/plans/prompts/phase2-evidence-contested.md`. This is the prompt for the next session:

```markdown
# Phase 2 Prompt — EVIDENCE_CONTESTED in Mandatory Tables

> Paste this prompt into a fresh Claude Code session to execute Phase 2.

---

## Context

You are implementing Phase 2 of the Deep Review Optimization plan. Phase 1 is complete — signal-aware evidence context blocks are now injected into chapter templates based on RetrievalSignal.confidence (HIGH / MODERATE / AMBIGUOUS / LOW).

Read these documents first:

1. `docs/reference/deep-review-optimization-plan-2026-03-20.md` — the full optimization plan
2. `docs/plans/2026-03-20-deep-review-optimization-backlog.md` — Phase 2 details

**Goal:** When retrieval_confidence is AMBIGUOUS, chapter templates with mandatory tables (ch06, ch08, ch10) should instruct the LLM to produce `Contested: X (Source A) / Y (Source B)` cells instead of silently picking one value.

## Current State (after Phase 1)

- `_evidence_context.j2` exists in `backend/vertical_engines/credit/prompts/` with 4 conditional branches
- `retrieval_confidence` variable is available in all chapter template contexts
- AMBIGUOUS block already says "present BOTH values with attribution" — but this is generic guidance
- Mandatory tables in ch06, ch08, ch10 still only define two cell states: `value` or `[NOT FOUND]`

## Implementation Steps

### Step 1: Add table-specific AMBIGUOUS instructions to ch06_terms.j2

After the `{% include '_evidence_context.j2' %}` and before the mandatory terms table, add:

```jinja2
{% if retrieval_confidence | default("MODERATE") == "AMBIGUOUS" %}
CONTESTED TERMS PROTOCOL:
When the evidence pack contains conflicting values for a term from different source documents:
- Present both values in the table cell: "Contested: [Value A] ([Source A]) / [Value B] ([Source B])"
- In the narrative below the table, explain the discrepancy and its materiality
- Flag contested terms that affect IC decision (rate, fees, covenants) as critical_gaps with blocks_approval=true
Example: "Contested: Prime+6.25% (ACV Contract) / SOFR+4.5% (Deal Term Sheet)"
{% endif %}
```

### Step 2: Add table-specific AMBIGUOUS instructions to ch08_returns.j2

After `{% include '_evidence_context.j2' %}` and before TABLE 1:

```jinja2
{% if retrieval_confidence | default("MODERATE") == "AMBIGUOUS" %}
CONTESTED RETURNS PROTOCOL:
When return metrics differ across sources:
- In TABLE 1 cells, present the range: "Contested: X% ([Source A]) / Y% ([Source B])"
- In TABLE 2 sensitivity, use both base assumptions and show the range of outcomes
- Flag contested base yield or net IRR as critical_gaps
{% endif %}
```

### Step 3: Add table-specific AMBIGUOUS instructions to ch10_covenants.j2

After `{% include '_evidence_context.j2' %}` and before the register table:

```jinja2
{% if retrieval_confidence | default("MODERATE") == "AMBIGUOUS" %}
CONTESTED COVENANTS PROTOCOL:
When covenant thresholds differ across documents:
- Present both in the Threshold column: "Contested: 1.25x (PPM) / 1.15x (Side Letter)"
- In the Headroom Est. column, calculate headroom against BOTH thresholds
- Flag any covenant where the contested range crosses a compliance boundary as critical_gaps
{% endif %}
```

### Step 4: Tests

In `backend/tests/test_deep_review_evidence_contested.py`:

1. Render ch06 with `retrieval_confidence="AMBIGUOUS"` → assert "CONTESTED TERMS PROTOCOL" in output
2. Render ch06 with `retrieval_confidence="HIGH"` → assert "CONTESTED" NOT in output
3. Same for ch08 and ch10
4. Render ch01 with `retrieval_confidence="AMBIGUOUS"` → assert no contested protocol (ch01 has no mandatory table)

### Step 5: Validate

- `make check` passes
- Compare e2e output for a deal with known AMBIGUOUS chapters → verify contested cells appear

## Constraints

- Do NOT modify `_evidence_context.j2` — that is the generic guidance; these are table-specific additions
- Do NOT change JSON output schema
- The `Contested:` prefix is informational text, not a structured field — IC committee reads it as markdown
- Only add contested protocols to chapters with mandatory data tables (ch06, ch08, ch10)

## Branch & PR

- Branch: `feat/deep-review-evidence-contested`
- PR title: `feat(deep-review): EVIDENCE_CONTESTED in mandatory table chapters`

---

## OUTPUT: Phase 3 Prompt

After completing Phase 2, generate a prompt for Phase 3 (Confidence Block 2 migration to RetrievalSignal) and save it to `docs/plans/prompts/phase3-confidence-block2-migration.md`. Phase 3 details:

- Replace `_block_evidence_quality()` in `confidence.py` (lines 249-293) with RetrievalSignal-based scoring
- Thread `chapter_signals` dict into `compute_underwriting_confidence()`
- Map: HIGH→0, MODERATE→1, AMBIGUOUS→2, LOW→3 penalty per critical chapter
- Keep chunk-count fallback for backward compat when `chapter_signals` is empty
- Same 6 critical chapters, same max 15 points
- Tests: parametrize all signal levels, verify fallback path, integration with full confidence pipeline

After Phase 3 is complete, generate a Phase 3B prompt for policy loader ConfigService migration and save to `docs/plans/prompts/phase3b-policy-configservice.md`. Phase 3B details:

- `policy_loader.py` has dead Azure Search path: `_search()` → LLM extraction → module cache. Azure Search deprecated.
- `resolve_governance_policy(config)` already works correctly — pure ConfigService resolver
- Seed YAML at `calibration/seeds/private_credit/governance_policy.yaml` already in DB via migration 0007
- 3 callers all use dead path with `# TODO(Sprint 3)`: `service.py:312`, `policy.py:167`, `concentration_engine.py:191`
- Wire all callers to pass `ConfigService.get("private_credit", "governance_policy", org_id)` as `config=`
- Remove from `policy_loader.py`: Azure Search helpers (`_search`, `_dedup_chunks`, `_build_context`, `_first_source`), LLM extraction (`_extract_with_llm`, `_apply_extracted`), module cache (`_cache`, `invalidate_cache`), `import httpx`
- Keep: `_DEFAULTS`, `ThresholdEntry`, `PolicyThresholds`, `resolve_governance_policy`, simplified `load_policy_thresholds`
- Note: `policy.py:_gather_policy_context()` (lines 50-143) also uses deprecated `AzureSearchChunksClient` for evidence retrieval — flag with TODO, separate concern
- Tests: existing `test_governance_policy_config.py` covers ConfigService path

Phase 3B prompt should chain to Phase 4 (doc-type filter dead code removal). Phase 4 details:

- `CHAPTER_DOC_TYPE_FILTERS` in `retrieval/models.py` (lines 123-187) is dead code — OData filters from Azure Search era, never applied to pgvector queries
- `doc_type_filter` param in `evidence.py:gather_chapter_evidence()` is accepted but has no effect — remove param
- Keep `CHAPTER_DOC_AFFINITY` in `memo/prompts.py` (evidence pack section filtering, different concern)
- Keep `CRITICAL_DOC_TYPES` in `retrieval/models.py` (always-include logic, different concern)
- Tests: verify no test references removed constants, `make check` passes
- No functional change to retrieval behavior

Phase 4 prompt should chain to Phase 5 (search tier unification + signal-based expansion), which chains to Phase 6 (legacy blob fallback removal). Phase 6 details:

- Remove `_gather_deal_texts_legacy()`, `_gather_investment_texts_legacy()`, `_extract_text_from_blob()` from `corpus.py`
- Remove `from app.services.blob_storage import blob_uri, download_bytes` from corpus.py
- In `_gather_deal_texts()`: when corpus < 200 chars, return empty corpus + warning log (no blob fallback)
- In `_gather_investment_texts()`: when RAG returns no chunks, return empty string + warning log
- DO NOT remove `_load_deal_context_from_blob()` — still used in `service.py` primary path (separate concern)
- All blob data is already in pgvector — blob path was abandoned development approach

Phase 6 should note that Phase 7 (`_pre_classify_from_corpus()` deprecation) is DEFERRED pending 50+ deal concordance data from production.
```

Save this Phase 2 prompt verbatim as `docs/plans/prompts/phase2-evidence-contested.md` after Phase 1 is complete.
