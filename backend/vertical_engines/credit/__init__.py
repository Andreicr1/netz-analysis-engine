"""Private Credit vertical engine — IC memo generation, deep review, and deal analysis.

Moved from ``ai_engine/intelligence/`` as part of the vertical engine
extraction (Phase 4).  Business logic is unchanged; only import paths
and session injection were updated.

Public entry points (all accept ``db: Session`` as first arg):
  - ``run_deal_deep_review_v4``       — 13-chapter IC memo pipeline
  - ``run_portfolio_review``          — periodic portfolio review
  - ``run_pipeline_ingest``           — pipeline discovery + aggregation
  - ``run_portfolio_ingest``          — portfolio monitoring
  - ``generate_pipeline_intelligence``— structured + memo for single deal
"""
