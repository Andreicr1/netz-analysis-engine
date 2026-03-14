"""Classifier — DELEGATION WRAPPER.

REFACTOR (Phase 2, Step 7): All logic consolidated into
ai_engine.classification.document_classifier.  This module re-exports
for backward compatibility.
"""
from __future__ import annotations

from ai_engine.classification.document_classifier import (  # noqa: F401
    INSTITUTIONAL_TYPES,
    classify_documents,
)
