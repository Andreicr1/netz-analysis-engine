# Deep Review V4 Baseline Metrics — BridgeInvest Credit Fund V

**Date:** 2026-03-20
**Purpose:** Pre-optimization baseline for comparison after implementing `deep-review-optimization-plan-2026-03-20.md` (Phases 1-3).

---

## Run Configuration

| Parameter | Value |
|---|---|
| **Deal** | BridgeInvest Credit Fund V |
| **Deal ID** | `66b1ed07-8274-4d96-806f-1515bb0e148b` |
| **Fund ID** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| **Org ID** | `70f19993-b0d9-42ff-b3c7-cf2bb0728cec` |
| **LLM (text generation)** | qwen/qwen3-14b via LM Studio (local, RTX 5070 Ti) |
| **LLM (sponsor analysis)** | qwen/qwen3-14b via LM Studio |
| **LLM (memo chapters)** | qwen/qwen3-14b via LM Studio (model routing: gpt-5.1 label) |
| **LLM (tone normalizer)** | qwen/qwen3-14b via LM Studio (model routing: gpt-4.1-mini label) |
| **Embeddings** | OpenAI text-embedding-3-large (3072 dim) |
| **Reranker** | DISABLED — CrossEncoder meta tensor error (PyTorch/transformers version conflict) |
| **OCR** | Not exercised (chunks already in pgvector) |
| **DB** | Timescale Cloud prod (pgvector HNSW) |
| **Corpus budget** | 100,000 chars (reduced from 300K for qwen3-14b 32K context) |
| **Context window** | 32,768 tokens |
| **full_mode** | False |

---

## Pipeline Timing

| Stage | Duration | Notes |
|---|---|---|
| Retrieval (14 chapters, pgvector) | ~30s | 100% embedding cache hit, reranker disabled |
| Stage 3: LLM structured analysis | ~45s | 100K corpus → qwen3-14b |
| Stage 4: FRED macro snapshot | ~30s | 29/32 series OK, 3 deprecated series failed |
| Stage 5: EDGAR entity resolution | ~4s | 6 entities tried, 0 CIKs resolved (private fund) |
| Stage 7: Quant profile | <1s | INSUFFICIENT_DATA (no maturity/coupon/IRR) |
| Stage 9: Sponsor analysis (LLM) | ~53s | 316 sponsor chunks, 5 key persons extracted |
| Stage 10: KYC screening | skipped | No KYC_SPIDER_PASSWORD configured |
| Stage 11: Evidence pack persist | <1s | 118K chars evidence JSON |
| Stage 12: Memo generation (14 ch) | ~18 min | Sequential LLM calls, some 400s on large chapters |
| Stage 13: Critic | ~2 min | 1 fatal flaw detected |
| Stage 14: Tone normalizer | ~5 min | 14 chapters normalized |
| **Total wall time** | **~38 min** | |

---

## Retrieval Metrics

| Metric | Value |
|---|---|
| **Retrieval policy** | IC_GRADE_V2 |
| **Total chapters** | 14 |
| **Corpus chars (final)** | 100,286 |
| **Corpus chunks (final)** | 42 |
| **Unique docs in corpus** | 4 |
| **Critical doc types forced** | legal_lpa, fund_structure (140 chunks) |
| **Retrieval confidence** | LOW |
| **Gaps** | 14 (all chapters flagged) |

### Per-Chapter Evidence

| Chapter | Chunks | Docs | Coverage Status |
|---|---|---|---|
| ch01_exec | 201 | 36 | EVIDENCE_CONTESTED |
| ch02_macro | 192 | 35 | EVIDENCE_CONTESTED |
| ch03_exit | 130 | 21 | EVIDENCE_CONTESTED |
| ch04_sponsor | 316 | 36 | EVIDENCE_CONTESTED |
| ch05_legal | 632 | 60 | EVIDENCE_CONTESTED |
| ch06_terms | 510 | 54 | EVIDENCE_CONTESTED |
| ch07_capital | 396 | 48 | EVIDENCE_CONTESTED |
| ch08_returns | 191 | 35 | EVIDENCE_CONTESTED |
| ch09_downside | 296 | 45 | EVIDENCE_CONTESTED |
| ch10_covenants | 281 | 44 | EVIDENCE_CONTESTED |
| ch11_risks | 321 | 41 | EVIDENCE_CONTESTED |
| ch12_peers | 164 | 22 | EVIDENCE_CONTESTED |
| ch13_recommendation | 100 | 16 | EVIDENCE_CONTESTED |
| ch14_governance_stress | 595 | 50 | EVIDENCE_CONTESTED |

**Note:** All chapters show EVIDENCE_CONTESTED because the cross-encoder reranker is disabled (PyTorch meta tensor error). Without reranking, delta_top1_top2 is low → RetrievalSignal classifies as AMBIGUOUS → coverage overridden to CONTESTED. This is expected behavior and will change when reranker is fixed.

---

## Memo Output Metrics

| Metric | Value |
|---|---|
| **Chapters generated** | 14 |
| **Chapters from cache** | 0 |
| **Total memo chars** | 38,879 |
| **Citations (real)** | 55 |
| **Citations (total)** | 55 |
| **Critical gaps** | 4 |
| **Unsupported claims** | 0 |
| **Recommendation** | CONDITIONAL |

### Chapters with LLM 400 errors (context overflow)

Some chapters exceeded qwen3-14b's 32K context and received fallback text instead of LLM-generated content. These were saved with `*Chapter N: Title — generation failed*` placeholder text, then the tone normalizer expanded them with available context.

---

## Confidence & Decision Metrics

| Metric | Value |
|---|---|
| **Confidence score (legacy)** | 0.182 |
| **Evidence confidence** | 0.182 |
| **Underwriting level** | MEDIUM |
| **Underwriting score** | 55 |
| **Risk band** | HIGH |
| **IC gate** | CONDITIONAL |
| **Fatal flaws** | 1 (instrument type UNKNOWN) |
| **Confidence cap applied** | LOW evidence diversity → cap 55 (was 80) |

---

## Critic Findings

| Metric | Value |
|---|---|
| **Chapters rewritten** | 0 |
| **Fatal flaws** | 1 |
| **Fatal flaw detail** | Instrument type classified as UNKNOWN |
| **Policy compliance** | COMPLIANT |

---

## Known Limitations (Baseline-Specific)

1. **Reranker disabled** — CrossEncoder `meta tensor` error prevents reranking. All chapters show EVIDENCE_CONTESTED. Production runs with working reranker will show differentiated confidence (HIGH/MODERATE/AMBIGUOUS/LOW per chapter).

2. **Corpus budget reduced** — 100K chars vs 300K production. Evidence coverage is lower but sufficient for baseline structure comparison.

3. **Local LLM (14B)** — qwen3-14b is smaller than production target (gpt-4.1 / gpt-5.1). JSON output quality is lower (some parse retries, control character issues). Baseline measures pipeline structure, not LLM quality.

4. **Context overflow on large chapters** — Chapters with >32K tokens of evidence received fallback text. Production with gpt-4.1 (128K context) won't have this limitation.

5. **No deal_context.json** — `blob_uri()` signature mismatch prevented loading deal/fund context from R2. Deal fields (vehicles, key terms, entities) were empty.

6. **Persist incomplete** — Pipeline completed all stages but final `deal_underwriting_artifacts` persist failed (organization_id propagation pending). Evidence pack and memo chapters persisted successfully.

---

## Comparison Plan

After implementing Phases 1-3 of `deep-review-optimization-plan-2026-03-20.md`:

| Metric | Baseline | Post-Optimization | Expected Change |
|---|---|---|---|
| Coverage status distribution | 14/14 CONTESTED | Mixed (HIGH/MODERATE/AMBIGUOUS) | Reranker fix → differentiated signals |
| Confidence score | 0.182 | TBD | Higher with reranker + signal-aware scoring |
| Memo diversity | Uniform tone | Signal-adapted per chapter | HIGH chapters = authoritative, LOW = hedged |
| Token waste | Full fallback protocols in all chapters | Conditional evidence blocks | ~15 lines saved per HIGH chapter |
| EVIDENCE_CONTESTED in tables | Not present | Present where sources disagree | New capability |
| Confidence Block 2 source | Count-based proxy | RetrievalSignal direct | More accurate |

---

## Related Documents

- `docs/reference/deep-review-optimization-plan-2026-03-20.md` — optimization plan (Phases 1-7)
- `docs/reference/retrieval-confidence-analysis-2026-03-20.md` — retrieval analysis
- `docs/reference/pipeline-quality-validation-2026-03-19.md` — pipeline validation data
- `docs/reference/prompt-retrieval-confidence-signals.md` — RetrievalSignal spec
