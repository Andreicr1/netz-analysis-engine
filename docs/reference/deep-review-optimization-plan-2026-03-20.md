# Deep Review Pipeline Optimization Plan — 2026-03-20

## Origin

Following the retrieval confidence analysis (2026-03-20) and the successful implementation of RetrievalSignal, an evaluation of the deep_review pipeline identified optimization opportunities in two layers: the retrieval/evidence infrastructure and the prompt architecture. The retrieval improvements make the evidence layer more reliable; the prompt optimizations leverage that reliability to produce context-aware, differentiated memo output instead of monolithic one-size-fits-all generation.

---

## Problem: Monolithic Memo Generation

The current deep_review pipeline generates IC memos that are structurally identical regardless of deal context. Every chapter receives the same fallback protocols, the same mandatory table instructions, the same evidence handling language. A well-evidenced term loan with clear documentation and a poorly-evidenced fund-of-funds with sparse data get the same prompt machinery.

This produces two problems:

1. **Memos read the same.** A deal with comprehensive evidence produces a memo with the same hedging language and fallback protocols as a deal with thin evidence. The reader cannot distinguish a high-confidence analysis from a low-confidence one by reading the memo — the tone and structure are identical.

2. **Token waste on unnecessary instructions.** Every chapter prompt includes full fallback hierarchies (derive → proxy → benchmark → [DATA GAP]) even when evidence is comprehensive and the hierarchy is never exercised. This consumes context window and dilutes the LLM's focus on the actual analytical task.

The root cause is that prompts were designed when retrieval quality was unknown and variable. Every prompt had to assume worst-case evidence. With validated retrieval (reranker 7/8 improvement, RetrievalSignal calibrated on 36-document corpus), the prompts can now adapt to what the evidence actually looks like.

---

## Layer 1: Retrieval & Evidence Infrastructure Optimization

These optimizations reduce defensive complexity in the evidence gathering layer, leveraging the validated reranker and confidence signals.

### 1.1 Doc-type filters → optional, reranker-driven

**Current state:** `CHAPTER_DOC_TYPE_FILTERS` in `retrieval/models.py` (lines 123–187) maintains per-chapter lists of allowed document types. When filtering returns < 6 chunks, a retry without filter is triggered (evidence.py lines 251–328).

**Optimization:** Make doc-type filters optional. The cross-encoder reranker already discriminates document relevance better than static type lists — validated by promoting rank #14 to #1 for risk factors and correcting topical errors (fee structure → leverage limits). The filter-then-retry pattern compensates for a problem the reranker solves natively.

**Approach:** Run parallel retrieval (with filter vs. without filter) on a representative set of chapter queries. If the reranker consistently selects the same document types that the filter would have enforced, the filter is redundant. Deprecate filters where reranker coverage is confirmed; keep for chapters where filtering provides genuine recall improvement.

### 1.2 Search tiers → uniform with signal-based expansion

**Current state:** `CHAPTER_SEARCH_TIERS` assigns different candidate pool sizes per chapter — (200, 300) for legal/governance chapters, (80, 150) for others.

**Optimization:** Start with a uniform candidate pool (~100 candidates) for all chapters. Use RetrievalSignal to decide whether to expand: if signal is LOW or AMBIGUOUS after the first pass, retry with a larger pool. This replaces static over-provisioning with dynamic right-sizing.

### 1.3 Legacy blob fallback → deprecate with monitoring

**Current state:** `_gather_deal_texts_legacy()` downloads raw documents from blob storage when RAG corpus < 200 chars. This was a safety net when retrieval was unreliable.

**Optimization:** Mark as deprecated. Monitor invocation frequency. If not triggered in 30 days of production use, remove. The validated retrieval pipeline should consistently produce corpus above the 200-char threshold for any reasonably populated dataroom.

### 1.4 Confidence scoring Block 2 → use RetrievalSignal

**Current state:** `confidence.py` Block 2 (Evidence Quality, 0–15 points) infers quality from chunk counts and doc diversity per critical chapter. This is a proxy for retrieval quality.

**Optimization:** Replace the proxy with the actual signal. RetrievalSignal.confidence per chapter query is a direct measurement of retrieval discrimination, not an inference from counts. Map HIGH → full points, MODERATE → minor penalty, AMBIGUOUS → significant penalty, LOW → maximum penalty. Simpler logic, more meaningful signal.

---

## Layer 2: Prompt Architecture Optimization — Signal-Aware Generation

This is the higher-impact optimization. Instead of static prompts that assume worst-case evidence, prompts adapt to the retrieval context of each specific deal and chapter.

### 2.1 The core change: conditional evidence context block

Replace hardcoded fallback protocols in chapter templates with a dynamic block injected during prompt construction, conditioned on the chapter's RetrievalSignal:

```jinja2
{# ── Evidence Context (injected per chapter based on retrieval signal) ── #}

{% if retrieval_confidence == "HIGH" %}
Evidence for this chapter is comprehensive and clearly differentiated.
Cite directly from the evidence pack with source attribution.
Flag any numeric inconsistencies between sources — these are analytically significant.
Do not use proxy values or benchmark substitutes when direct evidence exists.

{% elif retrieval_confidence == "MODERATE" %}
Evidence for this chapter is available but may not cover all required fields.
Cite from evidence where available. For fields not directly evidenced,
derive from related data in the evidence pack and label the derivation.

{% elif retrieval_confidence == "AMBIGUOUS" %}
Multiple competing sources were found for this chapter with no clear dominant authority.
Where sources disagree on numeric values or terms, present both values with attribution
(e.g., "PPM states X; IC Memo states Y"). Mark contested data explicitly.
The analyst must resolve contested fields before IC submission.

{% elif retrieval_confidence == "LOW" %}
Limited documentary evidence was found for this chapter.
Derive from available data where possible and label the source.
Use benchmark proxies (PitchBook/Preqin medians) where evidence is insufficient — label as "Est. based on [benchmark]".
Mark [DATA GAP] only when no derivation or proxy is possible.
Never fill an entire column with [DATA GAP] — consolidate gaps into a narrative assessment.
{% endif %}
```

### 2.2 What this changes in practice

**HIGH confidence deal (well-documented term loan):**
- Prompts are shorter and more focused on analysis
- No fallback protocol language — LLM focuses on citing and cross-referencing
- Inconsistencies between sources become analytically significant findings, not noise
- Memo reads as authoritative and specific

**AMBIGUOUS confidence deal (fund-of-funds with overlapping sources):**
- Prompts instruct the LLM to present alternatives instead of picking one
- Contested data is flagged explicitly for analyst resolution
- Memo reads as nuanced, surfaces genuine ambiguity instead of hiding it
- IC committee gets actionable information about where evidence disagrees

**LOW confidence deal (early-stage pipeline with sparse docs):**
- Full fallback protocol activates — derive, proxy, benchmark, [DATA GAP]
- Memo honestly reflects data limitations
- Confidence scoring penalizes appropriately
- IC committee knows this is a screening-grade analysis, not a diligence-grade one

**The result:** Three deals produce three meaningfully different memos — not because the analytical framework changes, but because the evidence handling adapts to what the evidence actually looks like. The memo's tone, specificity, and confidence markers reflect the deal's documentary reality.

### 2.3 Per-template impact

| Template | Current defensive complexity | Optimization |
|---|---|---|
| ch08_returns.j2 | 4-tier fallback protocol (~15 lines), mandatory [DATA GAP] handling | Replace with signal-aware block. HIGH → direct citation only. LOW → full protocol. |
| ch09_downside.j2 | Stress calibration fallbacks, scenario derivation hierarchy | Same pattern. AMBIGUOUS → present competing stress assumptions from different sources. |
| ch06_terms.j2 | [NOT FOUND IN DEAL DOCUMENTS] for every missing cell | AMBIGUOUS → "Found as X in [source A], as Y in [source B]". LOW → [NOT FOUND]. |
| ch10_covenants.j2 | "if available" for supporting details | HIGH → expect full covenant register. LOW → fallback protocol. |
| ch01_exec.j2 | Relatively clean already | Minimal change — add signal context for tone calibration. |
| ch03_exit.j2 | Macro data from FRED (deterministic, not evidence-dependent) | No change — macro data comes from system, not retrieval. |
| ch04_sponsor.j2 | Key persons extraction from evidence | AMBIGUOUS → flag when multiple sources disagree on titles/roles. |
| ch11_risks.j2 | Minimum row counts per risk category | No change — risk categories are analytical framework, not evidence-dependent. |
| critic.j2 | Adversarial review logic | No change — critic evaluates output quality, not evidence quality. |

### 2.4 _pre_classify_from_corpus() — monitor before removing

The 150-line keyword classifier in `prompts.py` runs before Stage 3 to pre-classify instrument type. With the reranker bringing more specific chunks (Investment Parameters instead of generic objectives), Stage 3's structured extraction likely identifies instrument type correctly without pre-classification.

**Approach:** Log concordance between `_pre_classify_from_corpus()` result and Stage 3's `instrument.type` output. If they agree > 95% over 50+ deals, the pre-classifier is redundant and can be removed. Until then, keep — it is deterministic, cheap, and a useful safety net.

### 2.5 EVIDENCE_CONTESTED in mandatory tables

Currently, tables in ch06 (terms), ch08 (returns), and ch10 (covenants) populate every cell with either a value or `[NOT FOUND IN DEAL DOCUMENTS]`. With RetrievalSignal producing AMBIGUOUS for chapters where sources compete, a third state becomes available:

- **Value** — evidence is clear and consistent
- **Contested: X (PPM) / Y (IC Memo)** — evidence exists but disagrees across sources
- **[NOT FOUND]** — no evidence after exhaustive search

This gives the IC committee actionable information. A contested covenant threshold (e.g., "DSCR minimum: 1.25x per PPM, 1.15x per Side Letter") is materially different from a missing one — and the current system cannot distinguish them.

---

## Implementation Sequencing

| Phase | Scope | Dependencies | Risk |
|---|---|---|---|
| **Phase 1** | Signal-aware evidence context block in Jinja2 templates | RetrievalSignal (done) | Low — additive, no existing logic removed |
| **Phase 2** | EVIDENCE_CONTESTED in mandatory tables (ch06, ch08, ch10) | Phase 1 | Low — extends existing [NOT FOUND] pattern |
| **Phase 3** | Confidence Block 2 migration to RetrievalSignal | RetrievalSignal (done) | Low — replaces proxy with direct signal |
| **Phase 4** | Doc-type filter deprecation (with A/B validation) | Reranker validation (done) | Medium — validate before removing |
| **Phase 5** | Search tier unification + signal-based expansion | Phase 4 | Low — parameter change |
| **Phase 6** | Legacy blob fallback deprecation | 30 days monitoring | Low — safety net removal after evidence |
| **Phase 7** | _pre_classify_from_corpus() deprecation | 50+ deal concordance data | Low — monitor before removing |

Phases 1–3 can be implemented now. Phases 4–7 require production data before proceeding.

---

## Expected Outcomes

- **Memo diversity:** Deals with different evidence profiles produce meaningfully different memos in tone, specificity, and confidence markers
- **Reduced token consumption:** HIGH confidence chapters skip ~15 lines of fallback instructions per template, across 8+ templates per memo
- **Better IC information:** Contested evidence surfaces explicitly instead of being silently resolved by the LLM's arbitrary choice
- **Simpler retrieval layer:** Fewer static filters, fewer retry paths, fewer hardcoded candidate pool sizes
- **More accurate confidence scoring:** Direct retrieval signal replaces count-based proxy

---

## Related Documents

- `docs/reference/retrieval-confidence-analysis-2026-03-20.md` — retrieval analysis and confidence signal decisions
- `docs/reference/retrieval-confidence-signals-spec.md` — RetrievalSignal implementation specification
- `docs/reference/pipeline-quality-validation-2026-03-19.md` — pipeline validation data (including corpus evolution section)
