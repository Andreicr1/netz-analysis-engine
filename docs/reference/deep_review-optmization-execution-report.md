Aqui está o relatório completo das 6 fases implementadas.

  ---
  Deep Review Optimization — Relatório de Implementação (Fases 1–6)

  Origem: docs/reference/deep-review-optimization-plan-2026-03-20.md
  Problema: Memos de IC eram estruturalmente idênticos independente da qualidade da evidência — deals bem documentados e deals com evidência escassa recebiam as mesmas instruções
  de fallback, o mesmo tom, os mesmos protocolos defensivos.

  ---
  Phase 1 — Signal-Aware Evidence Context Block

  Commit: 1dff98d · 15 arquivos, +428/−70

  Propagou RetrievalSignal.confidence (HIGH/MODERATE/AMBIGUOUS/LOW) do retrieval até os templates Jinja2. Criou _evidence_context.j2 — bloco condicional incluído em 8 templates de
   capítulo (ch01, ch04–ch10). Cada capítulo agora recebe instruções de evidência adaptadas ao que o retrieval realmente encontrou:
  - HIGH → cite diretamente, sem proxies
  - MODERATE → derive de dados relacionados quando evidência direta falta
  - AMBIGUOUS → apresente valores concorrentes com atribuição de fonte
  - LOW → protocolo completo de fallback (derive → proxy → benchmark → [DATA GAP])

  Templates sem dependência de evidência (ch02 macro, ch03 exit, ch11 risks, critic) ficaram inalterados. Default MODERATE quando sinal indisponível.

  ---
  Phase 2 — EVIDENCE_CONTESTED in Mandatory Tables

  Commit: cb719b0 · 4 arquivos, +162

  Adicionou um terceiro estado às células de tabela dos capítulos ch06 (terms), ch08 (returns) e ch10 (covenants). Antes existiam dois estados: valor ou [NOT FOUND]. Agora quando
  retrieval_confidence == AMBIGUOUS:

  Contested: Prime+6.25% (ACV Contract) / SOFR+4.5% (Deal Term Sheet)

  O comitê de IC agora distingue entre "dado não encontrado" e "fontes discordam sobre o valor" — informação materialmente diferente para decisão de investimento. Inclui 137
  linhas de testes parametrizados validando que AMBIGUOUS produz instruções de Contested e HIGH não.

  ---
  Phase 3 — Confidence Block 2 → RetrievalSignal

  Commit: fa3557a · 3 arquivos, +295/−6

  Substituiu o proxy de qualidade de evidência em confidence.py (Block 2, 0–15 pontos) pelo sinal direto do RetrievalSignal. Antes: contava unique_docs < 3 e chunk_count < 6 por
  capítulo crítico. Agora:
  - HIGH → 0 penalidade
  - MODERATE → 1 penalidade
  - AMBIGUOUS → 2 penalidade
  - LOW → 3 penalidade

  Aplicado aos 6 capítulos críticos (sponsor, legal, terms, capital, returns, covenants). Fallback para lógica antiga quando chapter_signals está vazio (backward compat com
  reviews cacheados). 264 linhas de testes unitários + integração.

  ---
  Phase 3B — Policy Loader: Remove Azure Search Dead Code

  Commit: 4f3493c · 5 arquivos, +46/−382

  Removeu ~340 linhas de código morto de policy_loader.py: path de Azure Search (_search(), _dedup_chunks(), _build_context()), extração LLM (_extract_with_llm()), cache
  module-level, e configuração de índice. load_policy_thresholds() simplificado para delegar direto a resolve_governance_policy() (ConfigService). Callers em
  deep_review/service.py e concentration_engine.py agora passam config do ConfigService em vez de depender do path Azure que falhava silenciosamente para defaults hardcoded.

  ---
  Phase 4 — Doc-Type Filter Dead Code Removal

  Commit: 0b81e4e · 3 arquivos, +49/−280

  Removeu CHAPTER_DOC_TYPE_FILTERS de retrieval/models.py (~65 linhas de filtros OData por capítulo) e os parâmetros doc_type_filter/override_filter de gather_chapter_evidence()
  em evidence.py. Esses filtros eram artefatos da era Azure Search — após migração para pgvector, o parâmetro era aceito mas nunca aplicado às queries. O cross-encoder reranker já
   discrimina relevância de documento melhor que listas estáticas de tipo. Net: −231 linhas de código morto.

  ---
  Phase 5 — Search Tier Unification + Signal-Based Expansion

  Commit: d48e749 · 3 arquivos, +283/−13

  Substituiu CHAPTER_SEARCH_TIERS (pools estáticos: 200/300 para capítulos legais, 80/150 para demais) por DEFAULT_SEARCH_TIER = (100, 150) uniforme para todos os capítulos, com
  expansão dinâmica baseada em sinal: se o RetrievalSignal após o primeiro pass é LOW ou AMBIGUOUS, retry automático com pool expandido (200, 300). Reduz over-provisioning para
  capítulos que o reranker resolve bem, enquanto expande dinamicamente quando a evidência é genuinamente escassa. 201 linhas de testes.

  ---
  Phase 6 — Legacy Blob Fallback Removal

  Commit: 95ce5f6 · 2 arquivos, +172/−115

  Removeu 3 funções mortas de corpus.py:
  - _extract_text_from_blob() — download de blob + extração de texto
  - _gather_deal_texts_legacy() — scan de DocumentRegistry + download por deal
  - _gather_investment_texts_legacy() — idem por investment

  Essas funções eram safety net de quando o pipeline RAG não era confiável. Todos os deals agora estão indexados em pgvector. Os fallback paths agora retornam corpus vazio com
  warning rag_empty.no_indexed_chunks. _load_deal_context_from_blob() preservada (usada no path primário para deal_context.json). Limpeza de imports: text_extract, select,
  DocumentRegistry, Path removidos. 3 testes novos.

  ---
  Resumo Consolidado

  ┌─────────────────────────────┬──────────┬──────────────────┬────────────────────┬────────────────────┐
  │            Fase             │   Tipo   │ Linhas removidas │ Linhas adicionadas │ Testes adicionados │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 1 — Signal-Aware Prompts    │ feat     │ 70               │ 428                │ sim                │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 2 — EVIDENCE_CONTESTED      │ feat     │ 0                │ 162                │ 137 linhas         │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 3 — Confidence Block 2      │ feat     │ 6                │ 295                │ 264 linhas         │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 3B — Policy ConfigService   │ refactor │ 382              │ 46                 │ atualizados        │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 4 — Doc-Type Filters        │ refactor │ 280              │ 49                 │ —                  │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 5 — Search Tier Unification │ refactor │ 13               │ 283                │ 201 linhas         │
  ├─────────────────────────────┼──────────┼──────────────────┼────────────────────┼────────────────────┤
  │ 6 — Legacy Blob Fallback    │ refactor │ 115              │ 172                │ 165 linhas         │
  └─────────────────────────────┴──────────┴──────────────────┴────────────────────┴────────────────────┘

  Total: ~866 linhas removidas, ~1.435 linhas adicionadas (incluindo testes). Net: ~+569 (maioria testes).

  Phase 7 (_pre_classify_from_corpus() deprecation) permanece DEFERRED — requer dados de concordância de 50+ deals em produção.

  Status do gate: 1538 testes passando, lint clean, 30/30 contratos de arquitetura mantidos.

✻ Sautéed for 1m 17s

❯ A fase 7 é uma limitação técnica ou decisão gerencial? Qual a dificuldade de implementação, benefícios e malefícios de implementar agora.

● Decisão técnica fundamentada em risco, não limitação gerencial.

  O que é o _pre_classify_from_corpus()

  É um classificador de ~150 linhas em prompts.py que roda antes do Stage 3 (extração estruturada pelo LLM). Ele faz keyword matching no corpus para inferir o tipo de instrumento
  (term loan, fund-of-funds, CLO, etc.) e injeta essa classificação no prompt do Stage 3.

  Por que foi deferido

  O argumento é: com o reranker trazendo chunks mais específicos (Investment Parameters em vez de objetivos genéricos), o Stage 3 provavelmente já identifica o tipo de instrumento
   corretamente sem a pré-classificação. "Provavelmente" é a palavra-chave — não existe dado confirmando isso.

  A condição de 50+ deals / 95% concordância não é arbitrária. É o mínimo para ter confiança estatística de que o Stage 3 é autossuficiente. Sem esse dado, remover o classificador
   é uma aposta.

  Dificuldade de implementação

  Baixa. É deletar ~150 linhas de keyword matching e remover a chamada em prompts.py. Tecnicamente trivial — 30 minutos de trabalho.

  Benefícios de implementar agora

  - -150 linhas de código que é efetivamente um heurístico frágil (listas de keywords hardcoded)
  - Elimina um ponto de divergência potencial — se o pré-classificador diz "term loan" e o Stage 3 diz "CLO", qual prevalece? Hoje o pré-classificador "contamina" o prompt
  - Simplifica o pipeline: uma decisão a menos antes do LLM

  Riscos de implementar agora

  - Sem o classificador, o Stage 3 é a única chance de acertar o tipo de instrumento. Se ele errar, o memo inteiro é gerado com premissas erradas (covenants de term loan num
  fund-of-funds, por exemplo). O pré-classificador é uma rede de segurança determinística e barata (~0ms, sem API call)
  - O reranker ainda está com problema (PyTorch meta tensor error, mencionado no baseline). Sem reranker funcionando, os chunks que chegam ao Stage 3 são menos específicos —
  exatamente o cenário onde o pré-classificador agrega valor
  - O classificador não custa nada em produção — é regex/keyword, roda em microsegundos, zero tokens LLM. O custo de mantê-lo é essencialmente zero

  Minha avaliação

  O tradeoff é assimétrico:

  ┌─────────────────┬────────────────────────────────────────────┬───────────────────────────────────────────────┐
  │                 │                   Mantém                   │                    Remove                     │
  ├─────────────────┼────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Custo           │ ~0 (determinístico, microsegundos)         │ −150 linhas                                   │
  ├─────────────────┼────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Risco se acerta │ redundante, inofensivo                     │ nenhum                                        │
  ├─────────────────┼────────────────────────────────────────────┼───────────────────────────────────────────────┤
  │ Risco se erra   │ contamina prompt (corrigível pelo Stage 3) │ memo inteiro com premissa errada (silencioso) │
  └─────────────────┴────────────────────────────────────────────┴───────────────────────────────────────────────┘

  O cenário perigoso é: remover agora, Stage 3 errar o tipo de instrumento num deal real, ninguém perceber porque não há concordance logging, memo vai pro IC committee com análise
   de covenants de loan aplicada num fund-of-funds.

  Recomendação prática: implementar o logging de concordância agora (trivial — 5 linhas), deixar rodar em produção, e remover quando os dados confirmarem. Isso custa quase nada e
  transforma a decisão de "aposta" em "decisão informada".

❯ está correta e o raciocínio do tradeoff assimétrico é sólido. Concordo com a recomendação de implementar o logging de concordância agora.
Mas tem um detalhe que o agente não mencionou e que muda o peso da decisão: o reranker está com PyTorch meta tensor error. Isso não é um contexto neutro — é exatamente o cenário
onde o pré-classificador tem mais valor, porque os chunks chegando ao Stage 3 são menos específicos sem o reranker funcionando. Remover o classificador agora, com o reranker
degradado, é acumular dois riscos simultâneos.
A sequência correta é:
1. Agora — implementar o concordance logging (5 linhas, trivial)
pythonif pre_classified_type != stage3_classified_type:
    logger.info(
        "pre_classify_concordance=MISMATCH deal=%s pre=%s stage3=%s",
        deal_id, pre_classified_type, stage3_classified_type
    )
else:
    logger.debug("pre_classify_concordance=MATCH deal=%s type=%s", deal_id, pre_classified_type)
Isso transforma Phase 7 de "aposta" em "decisão com dados" sem nenhum risco.
2. Antes do Phase 7 — resolver o reranker
O PyTorch meta tensor error precisa estar resolvido antes de remover qualquer rede de segurança do pipeline. Com o reranker funcionando, os chunks do Stage 3 são mais específicos
 e o classificador se torna genuinamente redundante. Sem o reranker, não é redundante.
3. Phase 7 — após 50+ deals com concordância ≥95% E reranker funcionando
Aí a remoção é segura e os dados confirmam.
Resumindo: mantenha Phase 7 deferred, implemente o logging agora, coloque "resolver reranker" como pré-requisito explícito do Phase 7 junto com o critério dos 50 deals. As duas
condições precisam ser verdadeiras simultaneamente.

● Concordo 100%. A análise do reranker degradado como multiplicador de risco é o ponto que faltava. Vou implementar o concordance logging e atualizar o backlog com os
  pré-requisitos explícitos.

  Primeiro, preciso localizar onde o _pre_classify_from_corpus() é chamado e onde o Stage 3 produz o tipo de instrumento.

  Searched for 1 pattern (ctrl+o to expand)

● Agora preciso ver onde o Stage 3 produz o instrument.type — o output que o logging vai comparar.

  Read 1 file (ctrl+o to expand)

● Preciso ver onde o Stage 3 output (analysis) é parseado e o instrument.type é extraído.

  Searched for 1 pattern (ctrl+o to expand)

● Perfeito. O padrão é claro — existem dois call sites (sync e async). Em ambos:
  1. Linha 197/1445: pre_instrument_type = _pre_classify_from_corpus(corpus, deal_fields)
  2. Linha 269/1462: instrument_type = classify_instrument_type(analysis) (Stage 4.5, pós-LLM)

  O logging de concordância vai logo após a linha do classify_instrument_type. Vou ler as linhas exatas dos dois call sites.

  Read 1 file (ctrl+o to expand)

● Agora adiciono o concordance logging nos dois call sites — sync (linha 274) e async (linha 1463).

● Update(backend\vertical_engines\credit\deep_review\service.py)
  ⎿  Added 15 lines
      273          type=instrument_type,
      274      )
      275
      276 +    # ── Phase 7 prep: concordance logging (pre-classifier vs Stage 3) ──
      277 +    if pre_instrument_type != instrument_type:
      278 +        logger.warning(
      279 +            "pre_classify_concordance.mismatch",
      280 +            deal_id=str(deal_id),
      281 +            pre=pre_instrument_type,
      282 +            stage3=instrument_type,
      283 +        )
      284 +    else:
      285 +        logger.debug(
      286 +            "pre_classify_concordance.match",
      287 +            deal_id=str(deal_id),
      288 +            type=instrument_type,
      289 +        )
      290 +
      291      # ── Stage 4.7: EDGAR public filing data (multi-entity) ──────
      292      logger.info("deep_review.v4.edgar.start", deal_id=str(deal_id))
      293      edgar_context: str = ""

● Update(backend\vertical_engines\credit\deep_review\service.py)
  ⎿  Added 15 lines
      1477      instrument_type = classify_instrument_type(analysis)
      1478      logger.info("deep_review.v4.instrument_classified", deal_id=str(deal_id), type=instrument_type)
      1479
      1480 +    # ── Phase 7 prep: concordance logging (pre-classifier vs Stage 3) ──
      1481 +    if pre_instrument_type != instrument_type:
      1482 +        logger.warning(
      1483 +            "pre_classify_concordance.mismatch",
      1484 +            deal_id=str(deal_id),
      1485 +            pre=pre_instrument_type,
      1486 +            stage3=instrument_type,
      1487 +        )
      1488 +    else:
      1489 +        logger.debug(
      1490 +            "pre_classify_concordance.match",
      1491 +            deal_id=str(deal_id),
      1492 +            type=instrument_type,
      1493 +        )
      1494 +
      1495      # ══════════════════════════════════════════════════════════════
      1496      # Phase 3: Parallel stages (EDGAR, policy, sponsor, KYC, quant)
      1497      # Uses to_thread for complex sync functions. Non-fatal stages

● Agora atualizo o backlog com os pré-requisitos explícitos do Phase 7.

  Read 1 file (ctrl+o to expand)

● Update(docs\plans\2026-03-20-deep-review-optimization-backlog.md)
  ⎿  Added 19 lines, removed 7 lines
      396
      397  **Branch:** `feat/deep-review-deprecate-pre-classifier`
      398  **Risk:** Low — monitor concordance before removing
      399 -**Dependencies:** 50+ deal concordance data from production
      399 +**Status:** Concordance logging ACTIVE (added 2026-03-20 in `service.py` — both sync and async paths log `pre_classify_concordance.mismatch` / `.match`)
      400
      401 -### What
      401 +### Prerequisites (BOTH must be true simultaneously)
      402
      403 -- Log concordance between `_pre_classify_from_corpus()` result and Stage 3's `instrument.type`
      404 -- If agreement > 95% → pre-classifier is redundant, remove
      405 -- 150 lines of keyword classifier in `prompts.py` (lines 40-194)
      406 -- **Cannot implement without production data** — need real deal corpus to measure concordance
      403 +1. **CrossEncoder reranker functional** — PyTorch meta tensor error must be resolved. Without the reranker, chunks arriving at Stage 3 are less specific, making
          +the pre-classifier a genuine safety net rather than a redundant step. Removing the classifier while the reranker is degraded stacks two risks: less specific evid
          +ence + no deterministic type hint.
      404
      405 +2. **50+ deals with concordance ≥ 95%** — measured from production logs (`pre_classify_concordance.match` vs `.mismatch`). The 50-deal threshold provides minimum
          + statistical confidence that Stage 3 is self-sufficient.
      406 +
      407 +### Why both conditions matter
      408 +
      409 +The pre-classifier costs ~0 at runtime (deterministic keyword matching, no API calls). The asymmetric risk: if it's redundant, keeping it is harmless; if it's ne
          +eded, removing it means instrument misclassification propagates silently through the entire memo (wrong covenant types, wrong return analysis framework, wrong ri
          +sk categories).
      410 +
      411 +### What (when prerequisites are met)
      412 +
      413 +- Remove `_pre_classify_from_corpus()` (~150 lines in `prompts.py` lines 40-194)
      414 +- Remove concordance logging from `service.py`
      415 +- Remove `pre_instrument_type` variable and its injection into `_build_deal_review_prompt_v2()`
      416 +- Update tests
      417 +
      418  ### Acceptance Criteria
      419
      410 -- Concordance data from 50+ deals showing > 95% agreement
      420 +- Reranker operational (no meta tensor error)
      421 +- Concordance data from 50+ deals showing ≥ 95% agreement
      422  - Pre-classifier removed, tests updated
      423 +- `make check` passes
      424
      425  ---
      426

● Update(docs\plans\2026-03-20-deep-review-optimization-backlog.md)
  ⎿  Added 3 lines, removed 2 lines
      436  Phase 4 (doc-type filter dead code) ── independent
      437  Phase 6 (legacy blob removal) ── independent
      438
      439 -Phase 7 (pre-classifier deprecation) ── DEFERRED, needs 50+ deals concordance
      439 +Phase 7 (pre-classifier deprecation) ── DEFERRED, needs reranker fix + 50+ deals concordance ≥95%
      440  ```
      441
      442  **Execution order:**
      443  - Phases 1, 3B, 4, 6 can start in parallel (no interdependencies)
      444  - Phases 2 and 3 after Phase 1
      445  - Phase 5 after Phase 1
      446 -- Phase 7 deferred until production concordance data available
      446 +- Phase 7 deferred until: (a) reranker operational, AND (b) 50+ deals concordance ≥95%
      447 +- Concordance logging is ACTIVE — collecting data now
      448
      449  **Recommended sequence:** 1 → 2 → 3 → 3B → 4 → 5 → 6 (logical flow, each builds context for the next).
      450

● Agora rodo lint e testes.

● Bash(cd C:/Users/andre/projetos/netz-analysis-engine && make lint 2>&1 | tail -5 && make test 2>&1 | tail -5 && make architecture 2>&1 | tail -3)
  ⎿  cd backend && python -m ruff check .
     All checks passed!
       Enable tracemalloc to get traceback where the object was allocated.
     … +7 lines (ctrl+o to expand)
  ⎿  (timeout 10m)

● Tudo limpo. Lint ok, 1538 testes passando, 30/30 contratos de arquitetura.

  Feito:

  1. Concordance logging adicionado em ambos os paths de service.py (sync linha ~270, async linha ~1463). Em produção, cada deep review agora emite:
    - pre_classify_concordance.mismatch (WARNING) — quando pré-classificador e Stage 3 discordam
    - pre_classify_concordance.match (DEBUG) — quando concordam
  2. Backlog atualizado — Phase 7 agora tem dois pré-requisitos explícitos e simultâneos:
    - Reranker operacional (PyTorch meta tensor error resolvido)
    - 50+ deals com concordância ≥ 95%
