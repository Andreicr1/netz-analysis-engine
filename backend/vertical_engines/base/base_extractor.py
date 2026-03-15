"""Base extractor interface for vertical engines.

Extractors perform structured data extraction from documents — the
domain-specific step that turns raw text into typed fields.  The
universal extraction pipeline (``ai_engine.extraction``) handles OCR,
chunking, and embedding; this interface covers the *interpretation*
layer that varies by asset class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class BaseExtractor(ABC):
    """Abstract interface for vertical-specific structured extraction."""

    vertical: str

    @abstractmethod
    def extract_structured(
        self,
        db: Session,
        *,
        fund_id: str,
        deal_id: str,
        document_text: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract structured fields from document text.

        Parameters
        ----------
        db : Session
            Caller-provided database session.
        fund_id : str
            Fund identifier.
        deal_id : str
            Deal identifier.
        document_text : str
            Pre-processed document text (post-OCR, post-chunking).
        config : dict | None
            Resolved configuration from ConfigService.

        Returns
        -------
        dict
            Structured extraction result (schema is vertical-specific).
        """
