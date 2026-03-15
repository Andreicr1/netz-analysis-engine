"""Pre-OCR skip filter for standard compliance forms.

Documents matching these patterns are excluded from the ingestion pipeline
because they are boilerplate regulatory/tax forms that pollute the analysis corpus.
"""
from __future__ import annotations

import re

_SKIP_PATTERNS = re.compile(
    r"W-8BEN"
    r"|W-9"
    r"|FATCA"
    r"|CRS.{0,10}Self.{0,10}Cert"
    r"|Self.{0,10}Certification"
    r"|KYC.{0,10}Form"
    r"|AML.{0,10}Form"
    r"|Beneficial.{0,10}Owner"
    r"|Anti.Money.Laundering",
    re.IGNORECASE,
)


def is_skippable(filename: str) -> bool:
    """Return True if the file is a standard compliance form to skip."""
    return bool(_SKIP_PATTERNS.search(filename))
