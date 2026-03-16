"""AI Engine Validation — 4-layer evaluation framework for IC memo quality.

Modules:
    eval_runner                    — end-to-end IC memo evaluation harness
                                     (entry point: run_ic_memo_eval)
    eval_metrics                   — Layers 1-3: decision integrity, retrieval, grounding
    eval_judge                     — Layer 4: LLM judge for coherence/consistency/tone
    validation_schema              — Pydantic schemas for eval framework + delta reports
    citation_formatter             — citation normalization for RAG (global_agent)
    evidence_quality               — evidence coverage + confidence scoring (global_agent)
    vector_integrity_guard         — EMBEDDING_MODEL_NAME/EMBEDDING_DIMENSIONS constants
                                     (guard functions are dead — delete or integrate)
    deep_review_comparator         — V3-vs-V4 deterministic delta computation
    deep_review_validation_runner  — V3-vs-V4 benchmark harness
                                     (entry point: run_deep_review_validation_sample)
    delta_metrics                  — engine quality scoring from delta reports

Tech debt:
    - All modules use stdlib logging instead of structlog (low priority).
    - vector_integrity_guard: 6 guard functions never called (~200 LOC dead).
      Constants are active. Delete guard functions or integrate into app startup.
"""
