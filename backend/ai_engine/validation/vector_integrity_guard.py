"""Vector Integrity Guard — canonical embedding constants.

These constants enforce a single embedding model version across the pipeline:
  B2 — Single embedding model version enforced
  B1 — Embedding dimension matches Azure Search index schema

Used by:
  - openai_client.py (model consistency check)
  - unified_pipeline.py (Parquet metadata)
  - search_rebuild.py (dimension validation before upsert)
"""
from __future__ import annotations

# ── B2: Canonical embedding model constant ────────────────────────────
EMBEDDING_MODEL_NAME = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 3072
