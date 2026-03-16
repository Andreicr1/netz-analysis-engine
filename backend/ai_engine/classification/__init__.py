"""AI Engine Classification — unified document classification.

Public API:
    classify() — hybrid three-layer pipeline classifier (rules → cosine → LLM)
"""

from ai_engine.classification.hybrid_classifier import classify

__all__ = ["classify"]
