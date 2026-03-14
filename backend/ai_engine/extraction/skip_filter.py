"""Skip filter — exclude compliance/tax forms from ingestion.

Extracted from legacy ``prepare_pdfs_full.py``. Standard compliance forms
(W-8BEN, FATCA, KYC, AML) pollute the corpus and are not relevant for
deal analysis or IC Memo generation.
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


def should_skip_document(filename: str) -> bool:
    """Return True if the file is a standard compliance form to skip."""
    return bool(_SKIP_PATTERNS.search(filename))
