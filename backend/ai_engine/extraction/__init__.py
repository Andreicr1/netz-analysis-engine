"""AI Engine Extraction — document extraction, chunking, embedding, and indexing.

Module classification
---------------------

**Pipeline stage components** (called by unified_pipeline.py / search_rebuild.py):
    skip_filter            — pre-filter gate (filename / extension rules)
    mistral_ocr            — OCR stage (Mistral API)
    governance_detector    — governance flag detection
    semantic_chunker       — document → semantic chunks
    document_intelligence  — metadata extraction from chunks
    embed_chunks           — embedding stage (build text + embed batch)
    search_upsert_service  — Azure Search upsert (push model)

**Autonomous utilities** (called by vertical engines, ingestion, or domain modules):
    embedding_service      — standalone embedding helper (used by domain_ai, pipeline screening, deep_review)
    entity_bootstrap       — deal entity bootstrap from blob storage
    obligation_extractor   — obligation register extraction (used by monitoring)
    azure_kb_adapter       — knowledge base adapter for Fund Copilot RAG
    kb_schema              — schema definitions for knowledge base chunks
    text_extraction        — text extraction from Azure Blob (used by entity_bootstrap)

**Deprecated** (will be deleted with legacy Azure Blob resources):
    extraction_orchestrator — legacy batch pipeline (see module docstring)
    deals_enrichment        — legacy chunk enrichment (called only by extraction_orchestrator)
    fund_data_bootstrap     — legacy fund data bootstrap (called only by extraction_orchestrator)
    fund_data_enrichment    — legacy fund data enrichment (called only by extraction_orchestrator)
    market_data_bootstrap   — legacy market data bootstrap (called only by extraction_orchestrator)
"""
