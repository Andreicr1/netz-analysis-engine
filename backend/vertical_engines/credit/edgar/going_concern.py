"""Going concern detection — 3-tier classification with negation detection.

Uses edgartools filing.text() for 10-K text retrieval (replaces manual HTTP).
Two-pass scan: auditor report section first, then broad scan.

Classification tiers:
  CONFIRMED  — keyword found WITHOUT negation in auditor report
  MITIGATED  — keyword found with management mitigation language
  NONE       — keyword not found, or found only with negation

Sync service — dispatched via asyncio.to_thread().
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.edgar.models import GoingConcernVerdict

logger = structlog.get_logger()


# ── Keyword lists ─────────────────────────────────────────────────

_GOING_CONCERN_KEYWORDS = [
    "going concern",
    "substantial doubt",
    "ability to continue as a going concern",
    "doubt about the company's ability to continue",
    "conditions raise substantial doubt",
    "ability to meet obligations as they become due",
    "recurring losses from operations",
    "material uncertainty related to going concern",
]

_NEGATION_PHRASES = [
    "no substantial doubt",
    "does not raise substantial doubt",
    "no longer raise substantial doubt",
    "has been alleviated",
    "doubt has been resolved",
    "does not believe",
    "management has concluded that no",
    "not raise substantial doubt",
    "there is no going concern",
    "no going concern",
    "no material uncertainty",
]

_MITIGATION_PHRASES = [
    "plans to alleviate",
    "mitigate the conditions",
    "management's plans",
    "management believes",
    "management intends",
    "expected to alleviate",
]

_AUDITOR_MARKERS = [
    "report of independent registered public accounting firm",
    "independent auditor",
    "report of independent auditor",
]


def _classify_context(text_window: str) -> GoingConcernVerdict:
    """Classify a text window containing a going-concern keyword match."""
    low = text_window.lower()

    # Check for negation within the window
    for neg in _NEGATION_PHRASES:
        if neg in low:
            return GoingConcernVerdict.NONE

    # Check for mitigation language
    for mit in _MITIGATION_PHRASES:
        if mit in low:
            return GoingConcernVerdict.MITIGATED

    return GoingConcernVerdict.CONFIRMED


def check_going_concern(
    company: Any,  # edgar.Company — typed as Any to avoid import at module level
    *,
    filing: Any | None = None,
) -> dict[str, Any] | None:
    """Scan latest 10-K for going concern language.

    Args:
        filing: Pre-fetched latest 10-K filing. When provided, skip
            ``company.get_filings()`` call to avoid duplicate SEC requests.

    Uses edgartools filing.text() for document retrieval.
    Never raises — returns None on failure.

    Returns dict with:
        verdict: "confirmed" | "mitigated" | "none"
        confidence: float (0.0-1.0)
        method: "auditor_report" | "broad_scan" | "not_found"
        filing_date: str
        accession: str
    """
    try:
        if filing is None:
            filings = company.get_filings(form="10-K")
            filing = filings.latest() if filings else None
        if not filing:
            return None

        raw_text = filing.text()
        if not raw_text:
            return None

        text_lower = raw_text[:200_000].lower()
        filing_date = str(filing.filing_date) if filing.filing_date else ""
        accession = filing.accession_no if hasattr(filing, "accession_no") else ""

        # Pass 1: Targeted — auditor report section
        for marker in _AUDITOR_MARKERS:
            idx = text_lower.find(marker)
            if idx >= 0:
                section = text_lower[idx: idx + 15_000]
                for kw in _GOING_CONCERN_KEYWORDS:
                    kw_idx = section.find(kw)
                    if kw_idx >= 0:
                        # Extract 400-char window around the keyword for context
                        start = max(0, kw_idx - 200)
                        end = min(len(section), kw_idx + len(kw) + 200)
                        context_window = section[start:end]
                        verdict = _classify_context(context_window)
                        return {
                            "verdict": verdict.value,
                            "confidence": 0.9 if verdict == GoingConcernVerdict.CONFIRMED else 0.6,
                            "method": "auditor_report",
                            "filing_date": filing_date,
                            "accession": accession,
                        }

        # Pass 2: Broad scan
        for kw in _GOING_CONCERN_KEYWORDS:
            kw_idx = text_lower.find(kw)
            if kw_idx >= 0:
                start = max(0, kw_idx - 200)
                end = min(len(text_lower), kw_idx + len(kw) + 200)
                context_window = text_lower[start:end]
                verdict = _classify_context(context_window)
                if verdict != GoingConcernVerdict.NONE:
                    return {
                        "verdict": verdict.value,
                        "confidence": 0.7 if verdict == GoingConcernVerdict.CONFIRMED else 0.4,
                        "method": "broad_scan",
                        "filing_date": filing_date,
                        "accession": accession,
                    }

        return {
            "verdict": GoingConcernVerdict.NONE.value,
            "confidence": 0.8,
            "method": "not_found",
            "filing_date": filing_date,
            "accession": accession,
        }

    except Exception as exc:
        logger.debug("going_concern_scan_failed", error=str(exc), exc_info=True)
        return None
