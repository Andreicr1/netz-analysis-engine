# Deep Review V4 Post-Optimization Metrics — BridgeInvest Credit Fund V

**Date:** 2026-03-20
**Purpose:** Post-optimization comparison against `deep-review-baseline-metrics-2026-03-20.md` after implementing Phases 1-6 + pgvector caller migration + reranker thread-safety fix.

---

## Run Configuration

| Parameter | Value | vs Baseline |
|---|---|---|
| **Deal** | BridgeInvest Credit Fund V | Same |
| **Deal ID** | `66b1ed07-8274-4d96-806f-1515bb0e148b` | Same |
| **Fund ID** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` | Same |
| **Org ID** | `70f19993-b0d9-42ff-b3c7-cf2bb0728cec` | Same |
| **Embeddings** | OpenAI text-embedding-3-large (3072 dim) | Same |
| **Reranker** | **ACTIVE** — CrossEncoder ms-marco-MiniLM-L-6-v2 (CUDA, RTX 5070 Ti) | **CHANGED** from DISABLED (meta tensor error fixed) |
| **DB** | Timescale Cloud prod (pgvector HNSW) | Same |
| **Corpus budget** | 100,000 chars | Same |
| **Search backend** | pgvector (sync) | **CHANGED** from Azure Search stub |
| **Search tier (default)** | (100, 150) | **CHANGED** from (80, 150) standard / (200, 300) legal |
| **Search tier (expanded)** | (200, 300) | NEW — signal-based expansion |
| **Doc-type filters** | Removed (dead code) | **CHANGED** from per-chapter OData filters |
| **Legacy blob fallback** | Removed | **CHANGED** from active fallback path |
| **Scope resolution** | deal UUID direct | **CHANGED** from folder-derived `resolve_index_scope()` |
| **Pre-classifier** | OPEN_ENDED_FUND | Same classification |
| **Run scope** | Retrieval only (Stages 1-2) | Baseline ran full pipeline |

---

## Retrieval Timing

| Stage | CPU (AMD, no CUDA) | GPU (RTX 5070 Ti, CUDA) | Baseline (reranker OFF) | Delta CPU→GPU |
|---|---|---|---|---|
| Retrieval (14 chapters, pgvector + rerank) | 691s (~11.5 min) | **69.3s (~1.2 min)** | ~30s | **10x speedup** |
| Embedding calls | 100% cache hit | 100% cache hit | 100% cache hit | Same |
| CrossEncoder load | 1.9s (one-time) | ~1s (one-time) | N/A (disabled) | NEW |

**GPU validation (2026-03-20):** Re-ran on NVIDIA RTX 5070 Ti Laptop GPU with CUDA. CrossEncoder device: `cuda`. Retrieval dropped from 691s → 69.3s (10x). Signal differentiation is identical (2H + 3M + 9A confidence, 5 SAT + 9 CONT coverage). Corpus increased to 300,430 chars (more documents ingested since CPU run; TOTAL_BUDGET_CHARS was raised to 300K for production with gpt-4.1 128K context).

---

## Side-by-Side Comparison

| Metric | Baseline | Post-Optimization | Delta |
|---|---|---|---|
| Retrieval policy | IC_GRADE_V2 | IC_GRADE_V2 | Same |
| Total chapters | 14 | 14 | Same |
| Corpus chars (final) | 100,286 | 100,289 | +3 (negligible) |
| Corpus chunks (final) | 42 | 40 | -2 |
| Unique docs in corpus | 4 | 2 | -2 (reranker concentrates on highest-quality sources) |
| Retrieval confidence | LOW | LOW | Same (aggregate) |
| Gaps | 14 | 9 | **-5** (5 chapters now SATURATED) |
| Coverage: SATURATED | 0/14 | **5/14** | **+5** |
| Coverage: CONTESTED | 14/14 | **9/14** | **-5** |
| Confidence: HIGH | 0/14 | **2/14** | **+2** |
| Confidence: MODERATE | 0/14 | **3/14** | **+3** |
| Confidence: AMBIGUOUS | 14/14 | **9/14** | **-5** |
| Pre-classifier | OPEN_ENDED_FUND | OPEN_ENDED_FUND | Same |
| Search expansion triggered | N/A | 9/14 chapters | NEW (only AMBIGUOUS chapters expand) |
| Legacy blob fallback calls | possible | 0 (removed) | Phase 6 |
| Doc-type filters applied | per-chapter OData | removed (dead code) | Phase 4 |
| Search backend | Azure Search stub (dead) | pgvector + CrossEncoder (live) | Migration |

---

## Per-Chapter Evidence Comparison

| Chapter | Baseline Chunks | Post Chunks | Baseline Docs | Post Docs | Baseline Coverage | Post Coverage | Baseline Confidence | Post Confidence | top1 | delta | Expanded |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ch01_exec | 201 | 479 | 36 | 49 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 7.26 | 0.40 | True |
| ch02_macro | 192 | 225 | 35 | 33 | CONTESTED | **SATURATED** | AMBIGUOUS | **MODERATE** | 7.02 | 0.54 | False |
| ch03_exit | 130 | 321 | 21 | 41 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 5.90 | 0.15 | True |
| ch04_sponsor | 316 | 627 | 36 | 54 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 4.55 | -1.16 | True |
| ch05_legal | 632 | 621 | 60 | 58 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 5.75 | 0.01 | True |
| ch06_terms | 510 | 538 | 54 | 54 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 6.58 | 0.36 | True |
| ch07_capital | 396 | 193 | 48 | 24 | CONTESTED | **SATURATED** | AMBIGUOUS | **MODERATE** | 6.66 | 1.03 | False |
| ch08_returns | 191 | 227 | 35 | 40 | CONTESTED | **SATURATED** | AMBIGUOUS | **HIGH** | 4.76 | 2.18 | False |
| ch09_downside | 296 | 654 | 45 | 62 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 3.34 | 0.11 | True |
| ch10_covenants | 281 | 602 | 44 | 55 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 1.75 | -1.01 | True |
| ch11_risks | 321 | 626 | 41 | 52 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 2.40 | 0.09 | True |
| ch12_peers | 164 | 398 | 22 | 40 | CONTESTED | CONTESTED | AMBIGUOUS | AMBIGUOUS | 5.38 | 0.13 | True |
| ch13_recommendation | 100 | 121 | 16 | 15 | CONTESTED | **SATURATED** | AMBIGUOUS | **MODERATE** | 2.83 | 1.47 | False |
| ch14_governance | 595 | 320 | 50 | 33 | CONTESTED | **SATURATED** | AMBIGUOUS | **HIGH** | 4.82 | 2.16 | False |

### Analysis

**Signal differentiation is working.** The reranker produces real logit scores (range -1.2 to 7.3) with meaningful deltas:
- **HIGH** (delta > 2.0): ch08_returns (2.18), ch14_governance (2.16) — clear dominant chunk separates from the rest
- **MODERATE** (delta 0.5-2.0): ch02_macro (0.54), ch07_capital (1.03), ch13_recommendation (1.47) — reasonable separation
- **AMBIGUOUS** (delta < 0.5): 9 chapters — multiple sources compete, no clear winner

**5 chapters that don't expand (SATURATED)** have better evidence quality — the reranker found clear signal on the first pass, no need for expanded search. This is the signal-based expansion (Phase 5) working correctly: only AMBIGUOUS chapters retry with larger pools.

**Chapters with negative delta** (ch04_sponsor: -1.16, ch10_covenants: -1.01): the top-2 scored higher than top-1 after cross-query dedup. This is the per-chapter aggregate signal design issue you identified — when chunks from different queries compete after dedup, rankings can invert. These correctly remain AMBIGUOUS.

**Corpus concentrates on higher-quality sources** — 2 unique docs in final corpus vs 4 in baseline. The reranker's discrimination pushes the coverage reranker toward the most relevant documents, spending the 100K budget on fewer but better sources.

---

## Signal Differentiation: Reranker Impact

| Metric | Baseline (reranker OFF) | Post-Optimization (reranker ON) |
|---|---|---|
| Score type in RetrievalSignal | cosine (0.56-0.76 range) | logits (-1.2 to 7.3 range) |
| Score discrimination | delta 0.0001-0.08 | delta -1.16 to 2.18 |
| Signal HIGH | 0 chapters | **2 chapters** |
| Signal MODERATE | 0 chapters | **3 chapters** |
| Signal AMBIGUOUS | 14 chapters | **9 chapters** |
| Coverage SATURATED | 0 chapters | **5 chapters** |
| Coverage CONTESTED | 14 chapters | **9 chapters** |
| Phase 5 expansion fires | N/A | 9/14 (only AMBIGUOUS) |

The optimization plan predicted: "Deals with different evidence profiles produce meaningfully different memos in tone, specificity, and confidence markers." With the reranker active, **this is now achievable** — Phase 1 signal-aware prompts will receive HIGH/MODERATE/AMBIGUOUS signals per chapter, producing differentiated memo output.

---

## Infrastructure Changes Validated

| Change | Status | Evidence |
|---|---|---|
| pgvector search (replaces Azure Search stub) | **WORKING** | 14 chapters retrieved, 2064 chunks searchable |
| CrossEncoder reranker (thread-safe) | **WORKING** | Logit scores, signal differentiation, no meta tensor error |
| Batch embedding per chapter | **WORKING** | 100% cache hit |
| Signal-based expansion (Phase 5) | **WORKING** | 9/14 chapters expanded (AMBIGUOUS only), 5 skipped (HIGH/MODERATE) |
| Doc-type filter removal (Phase 4) | **WORKING** | Reranker discriminates better than static filters |
| Legacy blob fallback removal (Phase 6) | **WORKING** | Zero blob calls |
| Cross-deal contamination filter | **WORKING** | UUID + name matching |
| Concordance logging (Phase 7) | **WORKING** | Pre-classifier: OPEN_ENDED_FUND |
| Tone normalizer guard | **WORKING** | Error placeholders propagated, not hallucinated |
| Benchmarks early-exit (no Azure Search) | **WORKING** | Skipped when no endpoint |

---

## Bugs Found & Fixed During E2E

| Bug | File | Fix |
|---|---|---|
| `AzureSearchChunksClient` stub had no methods | 5 callers | Migrated to pgvector_search_service |
| `_get_sync_engine()` used `?ssl=require` (psycopg rejects) | pgvector_search_service.py | `?sslmode=require` |
| Cross-deal contamination filter compared UUID vs name string | evidence.py | Accept both `deal_id` and `deal_name` |
| `settings.OPENAI_API_KEY` (uppercase) vs `settings.openai_api_key` | helpers.py | Fixed to lowercase |
| `CompletionResult` constructor wrong field names for local LLM | openai_client.py | `text=`, `model=`, `raw=` |
| `response_format: json_object` not supported by local LM Studio | openai_client.py | Skip for local backend |
| `SEARCH_ENDPOINT`/`SEARCH_API_KEY` removed from policy_loader | policy_loader.py | Added stubs |
| `retrieve_market_benchmarks` tried `DefaultAzureCredential` when key empty | benchmarks.py | Early-exit when no endpoint |
| Tone normalizer rewrites error placeholders into hallucinated content | tone.py | Guard on `generation failed` markers |
| CrossEncoder meta tensor error under concurrent threads | local_reranker.py | `threading.Lock` with double-checked locking |

---

## Known Limitations

1. **Reranker on GPU validated** — 69.3s on RTX 5070 Ti (was 691s on CPU). Production deployment should ensure CUDA-enabled PyTorch. No dedicated reranker endpoint needed at current scale.

2. **Per-chapter aggregate signal** — `RetrievalSignal` is computed over all deduped chunks from multiple queries per chapter. This dilutes discrimination when queries return overlapping results. Per-query signal computation would produce sharper differentiation. This is a design improvement, not a regression.

3. **TOTAL_BUDGET_CHARS set to 100K** for this comparison (matching baseline). Production value is 300K. With gpt-4.1 (128K context), 300K is appropriate.

---

## Related Documents

- `docs/reference/deep-review-baseline-metrics-2026-03-20.md` — baseline (pre-optimization)
- `docs/reference/deep-review-optimization-plan-2026-03-20.md` — optimization plan
- `docs/plans/2026-03-20-deep-review-optimization-backlog.md` — phase details
- `docs/plans/prompts/pgvector-caller-migration-prompt.md` — migration prompt used
- `docs/plans/prompts/tone-normalizer-guard-prompt.md` — tone guard prompt used
- `docs/plans/prompts/reranker-thread-safety-prompt.md` — reranker fix prompt used
- `docs/plans/prompts/e2e-cuda-reranker-continuation-prompt.md` — CUDA GPU validation prompt (this run)


 Avaliação dos Resultados

  O que funcionou bem

  1. Signal differentiation é o resultado mais importante. Baseline tinha 14/14 AMBIGUOUS → agora 2 HIGH + 3 MODERATE + 9 AMBIGUOUS. Isso é exatamente o que o optimization plan
  previa. Com reranker ativo, o sistema agora consegue distinguir capítulos bem evidenciados (ch08_returns, ch14_governance) dos que têm fontes competindo.

  2. Phase 5 (signal-based expansion) funciona corretamente. 5/14 chapters NÃO expandiram (já tinham signal suficiente), 9/14 expandiram. Isso é o right-sizing dinâmico
  substituindo os tiers estáticos — exatamente o design proposto.

  3. Gaps reduziram de 14 → 9. 5 chapters passaram de CONTESTED → SATURATED. O pipeline agora sabe a diferença entre "evidência insuficiente" e "evidência abundante mas ambígua" —
   informação crítica para o IC committee.

  4. Cleanup de Azure relics massivo. 10 bugs encontrados e fixados, todos relacionados à migração Azure → pgvector. O E2E forçou a descoberta de todos eles.

  Pontos de atenção

  1. ~~Reranker CPU: 691s vs 30s~~ **RESOLVIDO.** GPU validado em 2026-03-20: 69.3s no RTX 5070 Ti (10x speedup). CrossEncoder roda em CUDA automaticamente quando disponível. Não precisa de endpoint separado. LM Studio e CrossEncoder coexistem na GPU sem conflito (modelo MiniLM usa ~100MB VRAM).

  2. Unique docs caiu de 4 → 2. O reranker concentra no melhor conteúdo, mas com 100K budget isso pode ser over-concentration. Com o budget de produção (300K), deve distribuir
  melhor entre mais documentos. Vale monitorar se a diversidade de fontes é suficiente para o IC committee.

  3. Deltas negativos (ch04: -1.16, ch10: -1.01). O design de signal agregado por chapter é uma limitação real. Quando queries diferentes trazem chunks com scores altos que
  competem após dedup, o ranking pode inverter. A sugestão de per-query signal computation no doc é correta — seria uma melhoria futura (não regression).

  4. Retrieval confidence agregada ainda LOW. Embora per-chapter tenha melhorado (2 HIGH, 3 MODERATE), o agregado continua LOW. Isso é esperado — o aggregate é dominado pela
  maioria AMBIGUOUS. O confidence Block 2 migration (Phase 3 do plan) vai endereçar isso usando per-chapter signals ao invés do agregado.

  Decisões para próximos passos

  1. Phase 1 (signal-aware prompts) agora pode ser implementada — os signals per-chapter estão funcionando e diferenciados. Os templates Jinja2 vão receber
  HIGH/MODERATE/AMBIGUOUS/LOW e adaptar o tom.
  2. Phase 2 (EVIDENCE_CONTESTED em tables) tem dados reais — 9 chapters CONTESTED com sources competindo. As tabelas de ch06/ch08/ch10 podem agora mostrar "PPM: X / IC Memo: Y"
  ao invés de resolver silenciosamente.
  3. Phase 3 (confidence Block 2 → RetrievalSignal) tem os signals calibrados. Map: HIGH→full, MODERATE→minor penalty, AMBIGUOUS→significant, LOW→max. Vai melhorar o 0.182
  baseline.
  4. TOTAL_BUDGET_CHARS deve voltar para 300K em prod com gpt-4.1 (128K context). O 100K foi compromise para qwen3-14b local.

  Veredicto

  A otimização é um sucesso claro. A mudança principal (reranker ativo + signal differentiation) produziu exatamente o resultado previsto no plan. O pipeline agora tem a
  infraestrutura para gerar memos diferenciados por qualidade de evidência — o que antes era impossível (14/14 AMBIGUOUS). Os próximos Phases (1-3) do plan são agora
  implementáveis com confiança nos signals.
