"""Sponsor & Key Person Intelligence Engine — institutional due diligence.

Public API:
    analyze_sponsor()                    — full sponsor analysis (never raises)
    extract_key_persons_from_analysis()  — deterministic key person extraction

Error contract: never-raises (orchestration engine called during deep review).
Returns dict with status='NOT_ASSESSED' on failure.
No models.py — returns plain dicts. Formalize when callers need type safety.
"""
from vertical_engines.credit.sponsor.person_extraction import (
    extract_key_persons_from_analysis,
)
from vertical_engines.credit.sponsor.service import analyze_sponsor

__all__ = [
    "analyze_sponsor",
    "extract_key_persons_from_analysis",
]
