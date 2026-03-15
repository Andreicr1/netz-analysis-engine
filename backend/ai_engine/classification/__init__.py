"""AI Engine Classification — unified document classification.

Public API:
    classify()                     — hybrid three-layer pipeline classifier
    classify_documents()           — batch DB-level classification for Documents
    classify_registered_documents() — batch DB-level classification for DocumentRegistry
"""

from ai_engine.classification.hybrid_classifier import classify

__all__ = ["classify"]
