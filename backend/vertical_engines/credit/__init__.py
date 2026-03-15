"""Private Credit vertical engine — IC memo generation, deep review, and deal analysis.

Extracted from ``ai_engine/intelligence/`` (Phase 4) and modularized
(Wave 1-2).  Business logic is unchanged; only import paths and session
injection were updated.

Public entry points (all accept ``db: Session`` as first arg):
  - ``run_deal_deep_review_v4``       — 13-chapter IC memo pipeline
  - ``run_portfolio_review``          — periodic portfolio review
  - ``run_pipeline_ingest``           — pipeline discovery + aggregation
  - ``run_portfolio_ingest``          — portfolio monitoring
  - ``generate_pipeline_intelligence``— structured + memo for single deal
"""
from pathlib import Path

from ai_engine.prompts import prompt_registry

# Register credit/prompts/ so all credit engines can resolve .j2
# templates by filename (e.g. "ch01_exec.j2", "sponsor_assessment.j2").
prompt_registry.add_search_path(Path(__file__).parent / "prompts")
